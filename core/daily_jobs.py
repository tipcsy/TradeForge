"""NAPI FELADATOK — amit a program naponta egyszer, MAGÁTÓL elvégez.

⚠ MIÉRT VAN EZ (2026-09-22). A Csilla-sáv forward-tesztje 09-15-én indult, és a
fejléce szerint „naponta, a session után" kellett futnia — kézzel. Egy hét múlva
a napló EGY sort tartalmazott: senki nem indította. A felhasználó döntése: NEM
operációs rendszerbeli ütemező (a program egy másik gépen fog futni, ahol azt
senki nem állítja be), hanem a PROGRAM futtassa — naponta magától, vagy gombra.

⚠ A KERET NEM ISMER TARTALMAT. Az első változat ide drótozta a `csilla_forward`
nevet, a `main.py` pedig importálta a szkriptjét. A felhasználó kérdése — „mi
van, ha letörlöm a csilla stratégiát?" — mutatta meg: a feladat minden este
elbukott volna, a felületen egy halott doboz maradt volna. Ezért a feladatokat
a STRATÉGIÁK deklarálják (`Strategy.daily_jobs()`, a registry-n át, dinamikusan
— lásd `package-layout-frame-vs-content`), ez a modul csak a mechanizmus:
időzítés, alprocessz, állapot, napló. Törölt stratégiával a feladata is eltűnik.
A `tests/test_strategy_layout.py` őrzi, hogy ide stratégia-név ne kerüljön.

⚠ ALPROCESSZBEN, NEM A MOTOR SZÁLÁN. Ugyanaz az érv, mint az optimalizálás-
sornál (`conductor/optqueue.py`): a feladat percekig tarthat, a motor szálán a
kereskedés körideje nyúlna meg. A modul csak INDÍT és LEARAT — mindkettő
ezredmásodperces. A kimenet fájlba megy (`data/daily_jobs/<név>.log`), hogy
utólag elolvasható legyen, MIÉRT bukott, ha bukott — a `DEVNULL` néma halál volna.

⚠ EGY FUTÁS EGY NAPON. Az állapotfájl (`data/daily_jobs.json`) tartja, melyik
feladat melyik napon futott utoljára; az indítás után a nap AZONNAL beíródik,
tehát egy elhaló alprocessz sem indul újra percenként. Ha a futás elbukott, a
`last_rc` és a napló mondja meg — a következő nap újra próbálja.

⚠ A KÉZI INDÍTÁS UGYANAZ AZ ÚT. A dashboard gombja, a `jobs run <név>` parancs
és a napi időzítő ugyanazt a `start()`-ot hívja — egy második indítási út
elcsúszna az elsőtől (a projekt visszatérő hibája).

A config csak az ELTÉRÉST rögzíti (`daily_jobs.<név>.enabled` / `.time`), az
alap: bekapcsolva, a feladat saját idején. Egy kikapcsolt feladat a felületen
is kikapcsoltként látszik — nem tűnik el némán.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

try:
    from version import BASE_DIR as _BASE
except Exception:                                   # pragma: no cover
    _BASE = Path(__file__).resolve().parents[1]

# ⚠ MODUL-SZINTŰ, ÁTÁLLÍTHATÓ: a teszt ideiglenes mappára mutatja, hogy SOHA ne
# írja a valódi állapotot (lásd `tests-must-never-write-real-config`).
STATE_FILE = Path(_BASE) / "data" / "daily_jobs.json"
MAIN_PY = Path(_BASE) / "main.py"
LOG_DIR = "data/daily_jobs"                    # a BASE_DIR-hez képest

RUNNING, OK, FAILED, LOST, NEVER = "running", "ok", "failed", "lost", "never"

_state: dict | None = None
_popen: dict = {}                       # név → Popen (CSAK ebben a processzben)


def base() -> Path:
    """Az adat-gyökér (BASE_DIR) — EGY gazda; a feladatok fájljai ehhez képest.
    A teszt a modul `_BASE`-ét irányítja át, és minden útvonal vele megy."""
    return Path(_BASE)


# ── a feladatok forrása: a STRATÉGIÁK ────────────────────────────────────────
def _strategy_jobs() -> list:
    """Minden felderített stratégia `daily_jobs()`-a — dinamikusan, a
    registry-n át (a keret statikusan nem importál a `strategies/`-ből).
    Egy hibás stratégia nem viheti el a többiét: a hibát naplózzuk, és megyünk."""
    try:
        from strategy import get_strategy_by_name, registered_strategy_names
    except Exception:                                   # pragma: no cover
        return []
    out = []
    for nev in registered_strategy_names():
        try:
            for j in (get_strategy_by_name(nev).daily_jobs() or []):
                j = dict(j)
                j.setdefault("owner", nev)
                out.append(j)
        except Exception:
            log.warning("daily_jobs: a(z) %s stratégia feladatai nem olvashatók",
                        nev, exc_info=True)
    return out


# ⚠ A teszt kicserélheti: `PROVIDERS = [lambda: [...]]`.
PROVIDERS: list = [_strategy_jobs]


def jobs() -> dict:
    """`{név: spec}` — a most ISMERT feladatok. Amit egyetlen forrás sem
    deklarál (törölt stratégia), az nincs — se időzítés, se doboz."""
    out: dict = {}
    for prov in PROVIDERS:
        for j in (prov() or []):
            nev = str(j.get("name") or "").strip()
            if not nev or not callable(j.get("run")):
                log.warning("daily_jobs: hiányos feladat-leírás kihagyva: %r", j)
                continue
            if nev in out:
                # ⚠ Két azonos név némán egymást írná felül — ezt mondjuk.
                log.warning("daily_jobs: kétszer deklarált feladat: %s (%s és %s)",
                            nev, out[nev].get("owner"), j.get("owner"))
                continue
            out[nev] = dict(j, name=nev, time=str(j.get("time") or "22:30"),
                            label=str(j.get("label") or nev))
    return out


# ── config ───────────────────────────────────────────────────────────────────
def job_cfg(cfg: dict, name: str, spec: dict | None = None) -> dict:
    """`{enabled, time}` — a config eltérése az alapra vetítve."""
    alap = spec if spec is not None else (jobs().get(name) or {})
    c = ((cfg or {}).get("daily_jobs") or {}).get(name) or {}
    ido = str(c.get("time") or alap.get("time") or "")
    return {"enabled": bool(c.get("enabled", True)), "time": ido}


def _perc(hhmm: str):
    try:
        h, m = str(hhmm).split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None


# ── állapot ──────────────────────────────────────────────────────────────────
def _load() -> dict:
    global _state
    if _state is None:
        try:
            _state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            _state = {}
        if not isinstance(_state, dict):
            _state = {}
    return _state


def _save() -> bool:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_load(), ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(STATE_FILE)
        return True
    except Exception:
        # ⚠ NEM NÉMA: az állapot elvesztése azt jelenti, hogy a feladat másnap
        # kétszer futhat, vagy soha — mindkettő látszódjon a naplóban.
        log.warning("daily_jobs: az állapot nem menthető (%s)", STATE_FILE,
                    exc_info=True)
        return False


def reset_for_test() -> None:
    global _state
    _state = None
    _popen.clear()


# ── indítás / learatás ───────────────────────────────────────────────────────
def log_path(name: str) -> Path:
    return base() / LOG_DIR / f"{name}.log"


def _parancs(name: str) -> list:
    """`main.py job <név>` — az alprocessz a REGISTRY-n át találja meg a
    feladatot; az EXE-ben is ez az út."""
    return [sys.executable, str(MAIN_PY), "job", name]


def start(name: str, *, trigger: str = "manual", now: datetime | None = None,
          popen=None) -> tuple:
    """A feladat indítása alprocesszben. Vissza: `(ok, ok_kulcs_vagy_hiba)`.

    `trigger`: `"daily"` (időzítő) vagy `"manual"` (gomb / parancs).
    ⚠ Futó feladat mellett NEM indít másodikat: két egyidejű futás ugyanazt a
    naplófájlt (és a feladat saját fájljait) írná."""
    if name not in jobs():
        return False, "unknown_job"
    reap()
    st = _load().setdefault(name, {})
    if st.get("status") == RUNNING and name in _popen:
        return False, "already_running"
    now = now or datetime.now()
    popen = popen or subprocess.Popen        # futásidőben: a teszt kicserélheti
    lp = log_path(name)
    try:
        lp.parent.mkdir(parents=True, exist_ok=True)
        fh = open(lp, "a", encoding="utf-8", errors="replace")
        fh.write(f"\n===== {now:%Y-%m-%d %H:%M:%S} indítás ({trigger}) =====\n")
        fh.flush()
        p = popen(_parancs(name), stdout=fh, stderr=subprocess.STDOUT)
    except Exception as ex:
        st.update({"status": FAILED, "last_rc": None, "last_error": repr(ex),
                   "last_date": f"{now:%Y-%m-%d}",
                   "last_start": now.isoformat(timespec="seconds"), "trigger": trigger})
        _save()
        log.warning("daily_jobs: %s — az indítás nem sikerült: %s", name, ex)
        return False, "spawn_failed"
    _popen[name] = (p, fh, time.time())
    st.update({"status": RUNNING, "pid": getattr(p, "pid", None), "trigger": trigger,
               "last_date": f"{now:%Y-%m-%d}",
               "last_start": now.isoformat(timespec="seconds"),
               "last_end": None, "last_rc": None, "last_error": ""})
    _save()
    log.info("daily_jobs: %s indult (%s, pid %s)", name, trigger, st.get("pid"))
    return True, "started"


def reap() -> int:
    """A befejezett alprocesszek learatása. Vissza: hány fejeződött be."""
    kesz = 0
    for name in list(_popen):
        p, fh, t0 = _popen[name]
        rc = p.poll()
        if rc is None:
            continue
        try:
            fh.write(f"===== vége, kilépési kód {rc}, {time.time() - t0:.0f} s =====\n")
            fh.close()
        except Exception:
            pass
        st = _load().setdefault(name, {})
        st.update({"status": OK if rc == 0 else FAILED, "last_rc": int(rc),
                   "last_end": datetime.now().isoformat(timespec="seconds"),
                   "duration_s": round(time.time() - t0, 1), "pid": None})
        del _popen[name]
        kesz += 1
        (log.info if rc == 0 else log.warning)(
            "daily_jobs: %s befejeződött (kód %s, %.0f s)", name, rc, time.time() - t0)
    # ⚠ NINCS Popen, de „fut": a program ÚJRAINDULT a futás közben. Nem tudjuk,
    # mi lett vele — ezt mondjuk is, ne álljon örökre „fut"-on.
    for name, st in _load().items():
        if st.get("status") == RUNNING and name not in _popen:
            st.update({"status": LOST, "pid": None})
            kesz += 1
    if kesz:
        _save()
    return kesz


def tick(cfg: dict, now: datetime | None = None) -> list:
    """Körönként hívható (olcsó): learat, és indítja, aminek eljött az ideje.
    Vissza: a most indított feladatok nevei."""
    reap()
    now = now or datetime.now()
    ma = f"{now:%Y-%m-%d}"
    p_most = now.hour * 60 + now.minute
    indult = []
    for name, spec in jobs().items():
        c = job_cfg(cfg, name, spec)
        if not c["enabled"]:
            continue
        dp = _perc(c["time"])
        if dp is None or p_most < dp:
            continue
        st = _load().get(name) or {}
        if st.get("last_date") == ma:
            continue                    # ma már volt (akár kézzel)
        ok, _ = start(name, trigger="daily", now=now)
        if ok:
            indult.append(name)
    return indult


def run_in_process(name: str, argv: list) -> int:
    """A feladat FUTTATÁSA ebben a processzben — ezt hívja a `main.py job`
    alparancs az alprocesszben. Vissza: kilépési kód."""
    spec = jobs().get(name)
    if spec is None:
        print(f"daily_jobs: ismeretlen feladat: {name!r} (ismert: "
              f"{', '.join(sorted(jobs())) or '-'})")
        return 2
    rc = spec["run"](list(argv or []))
    return int(rc or 0)


# ── állapot a felületnek / parancsnak ────────────────────────────────────────
def status(cfg: dict, name: str) -> dict:
    """Egy feladat állapota — a felület és a `jobs` parancs EBBŐL ír, nem
    számol újra."""
    reap()
    spec = jobs().get(name) or {}
    c = job_cfg(cfg, name, spec)
    st = dict(_load().get(name) or {})
    st.setdefault("status", NEVER)
    st.update({"enabled": c["enabled"], "time": c["time"], "name": name,
               "label": spec.get("label", name), "owner": spec.get("owner", ""),
               "known": bool(spec), "log": str(log_path(name))})
    return st


def status_lines(name: str) -> list:
    """A deklaráló stratégia saját állás-sorai (ha ad ilyet) — hibatűrően:
    a felület sosem eshet el egy stratégia riportja miatt."""
    spec = jobs().get(name) or {}
    fn = spec.get("status_lines")
    if not callable(fn):
        return []
    try:
        return [str(x) for x in (fn() or [])]
    except Exception:
        log.debug("daily_jobs: %s status_lines elbukott", name, exc_info=True)
        return []


def log_tail(name: str, lines: int = 40) -> list:
    """A feladat naplójának utolsó sorai (a felületnek)."""
    try:
        return log_path(name).read_text(encoding="utf-8",
                                        errors="replace").splitlines()[-lines:]
    except Exception:
        return []

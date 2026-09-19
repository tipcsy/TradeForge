"""FEJ NÉLKÜLI OPTIMALIZÁLÁS-SOR — a karmester saját, pénzt NEM érintő akciója.

⚠ A LELET. Az optimalizálás indítása eddig CSAK a grafikus felületen létezett
(`dashboard.gui.OptimizerController`): a konzolos és a fej nélküli (VM, SSH)
futás egyáltalán nem tudott optimalizálást kérni, és a karmester
`queue_optimize` javaslata ezért csak TANÁCS lehetett. Ez a modul adja meg neki
a végrehajtási utat.

── ⚠ MIÉRT ALPROCESSZ, ÉS NEM SZÁL ────────────────────────────────────────
Az optimalizálás ÓRÁKIG tartó, CPU-nehéz munka. A motor szálán (vagy akár csak
ugyanabban a processzben, a GIL alatt) futtatva a kereskedés körideje mérhetően
megnyúlna — a projekt ezt a költséget máshol már megmérte (7,64 → 0,31 mp/kör a
felületnél). Ezért a sor a MEGLÉVŐ belépési pontot indítja külön processzként:

    python main.py optimize <SZIMBÓLUM> --strategy <STRATÉGIA>

Így nincs második optimalizáló-implementáció, ami elcsúszhatna a CLI-től, és a
`core/opt_lock.py` (processzek közötti zár) pontosan arra való, amire itt kell.

── ⚠ AMIT A SOR SOSEM TESZ MEG ────────────────────────────────────────────
**Kereskedő cellát nem optimalizál.** A futás végén a stratégia
paraméterfájlja íródna felül — az alól a cella alól, amelyik épp kereskedik
vele. Ez a felület szabálya (`OptimizerController.request_optimize`), és itt
ugyanaz a képlet dönt (`core.run_state.live_strategies`): engedélyezett ÉS
szándék=live. ⚠ A „csak jelzés" módú cella is ilyen: ott a papír-bizonyíték
gyűlik, amit egy paraméter-csere értelmetlenné tenne.

A blokkolt kérés NEM vész el és nem is fut le csendben: `blocked` állapotban
várakozik, az OKÁVAL együtt — így látod, hogy előbb le kell állítanod a cellát.

── ⚠ ADATLETÖLTÉS NINCS ───────────────────────────────────────────────────
A `main.py optimize` a lemezen lévő előzményből dolgozik (`load_data`), nem tölt
le. Az élő motor `data.gap_fill_on_start` beállítása tartja frissen; ha egy
páron nincs adat, a job HIBÁVAL áll le, és ez a sorban látszik. Nem csinálunk
úgy, mintha lefutott volna.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone

from conductor import paths as _paths

log = logging.getLogger(__name__)

# ── ÁLLAPOTOK (stabil kódok) ─────────────────────────────────────────────
QUEUED  = "queued"     # vár a sorára
BLOCKED = "blocked"    # nem indítható (pl. a cella kereskedik) — az ok ott van
RUNNING = "running"    # fut (alprocessz)
DONE    = "done"       # lefutott, rendben
FAILED  = "failed"     # lefutott, hibával (vagy elveszett az állapota)

STATES = (QUEUED, BLOCKED, RUNNING, DONE, FAILED)
_NYITOTT = (QUEUED, BLOCKED, RUNNING)

_lock = threading.RLock()
_state: dict = {}
_popen: dict = {}          # id → Popen (CSAK ebben a processzben)
_betoltve = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def _ts(v):
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _file():
    return _paths.DIR / "opt_queue.json"


def _load() -> None:
    global _betoltve
    with _lock:
        if _betoltve:
            return
        _betoltve = True
        ut = _file()
        if not ut.exists():
            return
        try:
            with open(ut, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get("items"), dict):
                _state.update(d["items"])
        except Exception as ex:
            log.warning("conductor.optqueue: a sor nem olvasható: %s", ex)


def _save_locked() -> bool:
    if not _paths.ensure():
        return False
    ut = _file()
    tmp = ut.with_suffix(".json.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "items": _state}, f,
                      ensure_ascii=False, indent=1)
        os.replace(tmp, ut)
        return True
    except Exception as ex:
        log.warning("conductor.optqueue: a sor nem írható: %s", ex)
        return False


# ---------------------------------------------------------------------------
# KÉRÉS
# ---------------------------------------------------------------------------

def enqueue(cfg: dict, symbol: str, strategy: str, *, source: str = "") -> "str | None":
    """Egy `(instrumentum, stratégia)` optimalizálás kérése. Visszaad: az azonosító,
    vagy `None`, ha MÁR sorban áll (a kérés akkor sem vész el — ott van)."""
    _load()
    with _lock:
        for e in _state.values():
            if (e.get("symbol") == symbol and e.get("strategy") == strategy
                    and e.get("state") in _NYITOTT):
                return None
        azon = secrets.token_hex(3)
        while azon in _state:
            azon = secrets.token_hex(3)
        _state[azon] = {"id": azon, "symbol": symbol, "strategy": strategy,
                        "state": QUEUED, "source": source,
                        "requested_at": _iso(_now()), "started_at": None,
                        "finished_at": None, "pid": None, "rc": None,
                        "reason": ""}
        _save_locked()
        return azon


def items(state=None) -> list:
    """A sor tételei, legrégebbi elöl (az indítás sorrendje)."""
    _load()
    with _lock:
        ki = [dict(e) for e in _state.values()
              if state is None or e.get("state") == state]
    ki.sort(key=lambda e: str(e.get("requested_at") or ""))
    return ki


def cancel(azon: str) -> bool:
    """Egy VÁRAKOZÓ tétel törlése. A futót nem bántjuk — azt a `main.py`
    saját stop-markere állítja le (`params_store.stop_marker`)."""
    _load()
    with _lock:
        e = _state.get(str(azon or "").strip().lower())
        if not e or e.get("state") not in (QUEUED, BLOCKED):
            return False
        _state.pop(e["id"], None)
        return _save_locked()


# ---------------------------------------------------------------------------
# INDÍTHATÓSÁG
# ---------------------------------------------------------------------------

def blocked_reason(cfg: dict, symbol: str, strategy: str,
                   strategies_of=None) -> str:
    """Miért NEM indítható most? Üres string = indítható.

    ⚠ A KERESKEDŐ CELLA A FŐ SZABÁLY: a futás végén a paraméterfájlja íródna
    felül az alól a cella alól, amelyik épp vele kereskedik. A képlet a MOTORÉ
    (`run_state.live_strategies`): engedélyezett ÉS szándék=live — a „csak
    jelzés" módú cella is ilyen, ott a papír-bizonyíték gyűlik."""
    from core import opt_activity as _oa
    from core import run_state as _rs

    try:
        engedett = list(strategies_of(symbol) or []) if strategies_of else []
    except Exception:
        engedett = []
    if strategy in (_rs.live_strategies(cfg, symbol, engedett) or []):
        return "cell_live"
    if _oa.busy(symbol, strategy):
        return "already_busy"
    return ""


# ---------------------------------------------------------------------------
# HAJTÁS
# ---------------------------------------------------------------------------

def _parancs(symbol: str, strategy: str) -> list:
    from version import BASE_DIR
    return [sys.executable, str(BASE_DIR / "main.py"), "optimize", symbol,
            "--strategy", strategy]


def drain(cfg: dict, *, strategies_of=None) -> dict:
    """A sor hajtása: befejezettek learatása + indíthatók indítása.

    Visszaad: `{"started": n, "finished": n, "blocked": n}`.
    ⚠ SOHA NEM DOB: a sor hajtása a motor körében fut."""
    try:
        return _drain(cfg, strategies_of)
    except Exception as ex:                                  # pragma: no cover
        log.warning("conductor.optqueue: a sor hajtása elszállt: %s", ex)
        return {"started": 0, "finished": 0, "blocked": 0}


def _drain(cfg: dict, strategies_of) -> dict:
    from conductor import config as _ccfg
    from core import opt_activity as _oa

    k = _ccfg.optqueue(cfg)
    _load()
    stat = {"started": 0, "finished": 0, "blocked": 0}
    with _lock:
        # ── 1. LEARATÁS ─────────────────────────────────────────────────
        for e in list(_state.values()):
            if e.get("state") != RUNNING:
                continue
            p = _popen.get(e["id"])
            if p is not None:
                rc = p.poll()
                if rc is None:
                    continue
                e["state"] = DONE if rc == 0 else FAILED
                e["rc"] = int(rc)
                e["finished_at"] = _iso(_now())
                e["reason"] = "" if rc == 0 else "exit_code"
                _popen.pop(e["id"], None)
                _oa.set_state(e["symbol"], e["strategy"], None)
                stat["finished"] += 1
                continue
            # ⚠ NINCS Popen: a motor ÚJRAINDULT, mióta ez elindult. Az
            # alprocessz futhat tovább (a `core/opt_lock.py` védi a
            # kettőzéstől), de az állapotát innen már nem látjuk. Nem
            # állítjuk se késznek, se hibásnak azonnal — egy türelmi idő
            # után viszont ki kell mondani, hogy ELVESZETT az állapota:
            # egy örökké „fut" sor rosszabb, mint egy bevallott hiány.
            kezd = _ts(e.get("started_at"))
            if kezd and _now() - kezd > timedelta(hours=float(k["stale_hours"])):
                e["state"] = FAILED
                e["reason"] = "lost_after_restart"
                e["finished_at"] = _iso(_now())
                _oa.set_state(e["symbol"], e["strategy"], None)
                stat["finished"] += 1

        # ── 2. INDÍTÁS ──────────────────────────────────────────────────
        fut = sum(1 for e in _state.values() if e.get("state") == RUNNING)
        szabad = max(0, int(k["max_parallel"]) - fut)
        for e in sorted((x for x in _state.values()
                         if x.get("state") in (QUEUED, BLOCKED)),
                        key=lambda x: str(x.get("requested_at") or "")):
            ok = blocked_reason(cfg, e["symbol"], e["strategy"], strategies_of)
            if ok:
                if e.get("state") != BLOCKED or e.get("reason") != ok:
                    e["state"], e["reason"] = BLOCKED, ok
                stat["blocked"] += 1
                continue
            if szabad <= 0:
                e["state"], e["reason"] = QUEUED, ""
                continue
            try:
                p = subprocess.Popen(_parancs(e["symbol"], e["strategy"]),
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
            except Exception as ex:
                e["state"], e["reason"] = FAILED, "spawn_failed"
                e["finished_at"] = _iso(_now())
                log.warning("conductor.optqueue: %s/%s — az indítás nem "
                            "sikerült: %s", e["symbol"], e["strategy"], ex)
                continue
            _popen[e["id"]] = p
            e.update({"state": RUNNING, "pid": p.pid,
                      "started_at": _iso(_now()), "reason": ""})
            # ⚠ A FELÜLET IS LÁSSA: a motor és a dashboard EGY processzben fut,
            # tehát a modul-szintű `opt_activity` állapot azonnal megjelenik az
            # OPT oszlopban — különben a felhasználó nem értené, miért nem
            # indítható kézzel ugyanaz a cella.
            _oa.set_state(e["symbol"], e["strategy"], _oa.RUNNING,
                          "karmester")
            szabad -= 1
            stat["started"] += 1
        _save_locked()
    return stat


def prune(keep_days: int = 14) -> int:
    """A LEZÁRT tételek takarítása. Visszaad: hány maradt."""
    _load()
    if keep_days is None or int(keep_days) <= 0:
        return len(_state)
    kuszob = _now() - timedelta(days=int(keep_days))
    with _lock:
        for azon in [a for a, e in _state.items()
                     if e.get("state") not in _NYITOTT
                     and (_ts(e.get("finished_at")) or _now()) < kuszob]:
            _state.pop(azon, None)
        _save_locked()
        return len(_state)


def reset_for_test() -> None:
    global _betoltve
    with _lock:
        _state.clear()
        _popen.clear()
        _betoltve = False

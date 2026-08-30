"""
PROCESSZEK KÖZÖTTI ZÁR egy optimalizálásra — per (instrumentum × stratégia).

⚠ MIÉRT KELL. 2026-08-04-én ÉLESBEN megtörtént: egy CLI-futás
(`python main.py optimize Ger40`, 15:16) és egy GUI-ból indított futás (19:56)
párhuzamosan dolgozott ugyanazon a `(Ger40, wpr_sma)` páron. Következmények:

  • **Közös optuna SQLite study**: a második futás `load_if_exists=True`-val
    ránézett az elsőére, és a `remaining = 500 − kész` alapján számolt — a
    „500 trial" tehát a KETTŐ EGYÜTTESE volt.
  • **Ugyanaz a kimeneti fájl**: a GUI-futás 22:30-kor mentett, a CLI-futás
    ~01:00-kor felülírta volna (kézi leállítással állt meg).
  • **Eltérő kódverzió**: a CLI v1.95.0-t töltötte be induláskor, a GUI
    v1.97.0-t — utólag nem bizonyítható, hogy a célfüggvény azonos volt.

A GUI önmagában védett (`_symbol_busy`), de csak a SAJÁT sorára lát: egy külső
processzről nem tud. Ez nem kényelmi kérdés — két optimalizálás ugyanarra a párra
CSENDBEN keveri a trialeket és írja felül egymás eredményét.

── A ZÁR ALAKJA ────────────────────────────────────────────────────────────
`data/optimized_params/<stratégia>/<SYM>_study.lock`, JSON: pid · gép · indulás ·
verzió · parancs. A study MELLETT lakik, mert pontosan azt védi.

⚠ ELÁRVULT ZÁR ÁTVEHETŐ. Ha a bejegyzett PID már nem él (összeomlás, kill,
áramszünet), a következő indulás ELVESZI a zárat és megy tovább. Enélkül egy
egyszeri összeomlás örökre letiltaná a pár optimalizálását — és a felhasználó
egy fájlt keresne, amiről nem tud.

⚠ AMIT NEM VÉD KI: a PID-újrahasznosítást. Ha a bejegyzett PID rég halott, de a
rendszer időközben ugyanazt a számot kiosztotta egy MÁS programnak, a zár élőnek
látszik. Ez ritka, és a következménye NEM adatromlás, hanem egy elutasítás —
amiben KI VAN ÍRVA a fájl útvonala, tehát kézzel feloldható. A fordított
(engedékeny) tévedés viszont pont az a néma összekeveredés, ami ellen az egész
készült; ezért ebbe az irányba tévedünk.
"""

from __future__ import annotations

from core.i18n import t as _t

import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Optional

from core.params_store import strategy_dir


def lock_path(symbol: str, strategy: str | None = None) -> Path:
    """A zár fájlja — a study MELLETT (`<SYM>_study.lock`)."""
    return strategy_dir(strategy) / f"{symbol}_study.lock"


def _pid_alive(pid: int) -> bool:
    """Fut-e még ez a processz? Platform-független, `psutil` NÉLKÜL.

    ⚠ Windowson az `os.kill(pid, 0)` NEM használható létezés-vizsgálatra (a
    Python `signal.CTRL_C_EVENT`-re fordítja, vagy hibát dob) — ott a Win32
    `OpenProcess` a helyes út. Az `ACCESS_DENIED` (5) hiba is LÉTEZÉST jelent:
    a processz megvan, csak nem a miénk."""
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            _PQLI = 0x1000                      # PROCESS_QUERY_LIMITED_INFORMATION
            k32 = ctypes.windll.kernel32
            h = k32.OpenProcess(_PQLI, False, int(pid))
            if h:
                k32.CloseHandle(h)
                return True
            return k32.GetLastError() == 5      # ACCESS_DENIED → létezik
        except Exception:
            return True                          # bizonytalanban ne vegyük el
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True                              # létezik, csak nem a miénk
    except (OSError, ValueError):
        return True
    return True


def read(symbol: str, strategy: str | None = None) -> Optional[dict]:
    """A zár tartalma, vagy `None`, ha nincs (vagy olvashatatlan).

    ⚠ Sérült/olvashatatlan zár = NINCS zár. Egy félig kiírt JSON miatt nem
    tagadhatjuk meg örökre az optimalizálást; a sérülés maga is azt jelzi, hogy
    az író processz nem jutott a végére."""
    p = lock_path(symbol, strategy)
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def is_held(symbol: str, strategy: str | None = None) -> bool:
    """Fut-e ÉPP optimalizálás ezen a (páron, stratégián) — bárhonnan indítva."""
    info = read(symbol, strategy)
    return bool(info) and _pid_alive(int(info.get("pid") or 0))


def acquire(symbol: str, strategy: str | None = None,
            note: str = "") -> tuple[bool, Optional[dict]]:
    """`(sikerult, akadalyozo_info)`. Sikernél `(True, None)`.

    ⚠ SZÁNDÉKOSAN NINCS atomi „csak ha nem létezik" létrehozás. Az `O_EXCL` a
    holt zárnál elakadna, és a leggyakoribb eset ÉPP az: egy korábbi futás
    összeomlott. A verseny-ablak (két processz ezredmásodpercen belül) sokkal
    ritkább, mint az elárvult zár, és a kettő közül csak az utóbbi fordul elő a
    gyakorlatban — órákig futó munkákat nem szokás egy pillanaton belül kétszer
    elindítani.
    """
    cur = read(symbol, strategy)
    # ⚠ A SAJÁT zárunkba ne akadjunk bele. Ha ugyanaz a processz kéri újra, akkor
    # már MIÉNK — az elutasítás önmagunk kizárása lenne, ami a hívó szemszögéből
    # megkülönböztethetetlen egy idegen futástól, és értelmezhetetlen üzenetet
    # adna („már fut egy optimalizálás — pid <a sajátom>").
    _pid = int(cur.get("pid") or 0) if cur else 0
    if cur and _pid != os.getpid() and _pid_alive(_pid):
        return False, cur
    p = lock_path(symbol, strategy)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "started_at": time.time(),
            "symbol": symbol,
            "strategy": strategy or "",
            "cmd": " ".join(sys.argv[:3]),
            "note": note,
        }
        try:
            from version import APP_VERSION
            payload["version"] = APP_VERSION
        except Exception:
            pass
        tmp = p.with_suffix(".lock.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)                       # atomi csere egy köteten belül
        return True, None
    except OSError:
        # ⚠ Ha a zárat nem tudjuk KIÍRNI, akkor is ENGEDÜNK. A zár védelem, nem
        # feltétel: egy írásvédett mappa miatt ne álljon le az optimalizálás —
        # csak a védelem vész el, és azt a hívó naplózza.
        return True, None


def release(symbol: str, strategy: str | None = None) -> bool:
    """A SAJÁT zárunk elengedése. Idegen zárat NEM törlünk.

    ⚠ A PID-ellenőrzés nem formaság: egy elárvult zárat átvevő processz
    befejezéskor különben letörölhetné annak a futásnak a zárát, amelyik
    időközben átvette tőle."""
    info = read(symbol, strategy)
    if info and int(info.get("pid") or 0) != os.getpid():
        return False
    try:
        lock_path(symbol, strategy).unlink(missing_ok=True)
        return True
    except OSError:
        return False


def describe(info: dict, symbol: str = "", strategy: str | None = None) -> str:
    """Az elutasítás EMBERI üzenete — a teendővel együtt.

    ⚠ A fájl útvonala BENNE VAN. Ha a zár tévesen él (PID-újrahasznosítás), ez az
    egyetlen kapaszkodó: enélkül a felhasználó egy láthatatlan akadállyal állna
    szemben, amit nem tud feloldani."""
    info = info or {}
    # ⚠ Hiányzó/hibás időbélyegnél NE írjunk kort. A `0`-ból „496316 óra" lesz,
    # ami nem hibaüzenet, hanem zaj: aki ezt olvassa, a lényeget veszti el.
    since = ""
    try:
        _st = float(info.get("started_at") or 0)
        mins = int((time.time() - _st) / 60)
        if _st > 0 and 0 <= mins < 60 * 24 * 30:
            since = (_t("lock.since_h", hours=mins // 60, min=mins % 60)
                     if mins >= 60 else _t("lock.since_m", min=mins))
    except (TypeError, ValueError):
        pass
    who = f"pid {info.get('pid')}"
    if info.get("host"):
        who += f" @ {info['host']}"
    cmd = f" ({info['cmd']})" if info.get("cmd") else ""
    return _t("lock.busy", since=since, who=who, cmd=cmd,
              path=lock_path(symbol, strategy))

"""FUTÁS-ZÁR az ÉLŐ KERESKEDÉSRE — brókerszámlánként, processzek között.

⚠ MIÉRT KELL, ÉS MIÉRT NEM OLDJA MEG A LICENC. A licenc a **brókerszámlához**
kötődik, nem a géphez: a `core.licence` a tokent és a számlaszámot küldi a
`/validate`-re, a szerver pedig azt nézi, hogy a SZÁMLA befér-e a licencbe. A
tokenfájlban lévő `machine` mező csak CÍMKE. Ebből következik, hogy **két
processz ugyanazon a gépen, ugyanazzal a számlával MINDKETTŐ átmegy a
licenc-kapun** — és mindkettő kereskedni kezd.

Ez nem elméleti kockázat. 2026-08-04-én pontosan ez történt, csak az
OPTIMALIZÁLÓVAL: egy CLI-futás és egy GUI-futás dolgozott ugyanazon a
`(Ger40, wpr_sma)` páron, keverték a trialeket, és felülírták egymás
eredményét. Emiatt született a `core.opt_lock`. A MOTORRA ilyen zár eddig nem
volt — a konzolos mód (`python main.py console`) viszont épp azt teszi
valószínűvé, hogy két példány fusson: egy grafikus a gépen, egy SSH-s a VM-en,
„csak megnézem". A következmény ott már nem elrontott mérés, hanem **dupla
kötés valódi pénzzel**.

── A ZÁR ALAKJA ────────────────────────────────────────────────────────────
`data/live_<számlaszám>.lock`, JSON: pid · gép · indulás · verzió · parancs.

⚠ SZÁMLÁNKÉNT, nem gépenként. Egy demó és egy éles számla EGYSZERRE futtatása
teljesen szabályos (sőt hasznos) — a tiltás csak azt zárja ki, hogy UGYANAZT a
számlát két motor kezelje.

⚠ ELÁRVULT ZÁR ÁTVEHETŐ. Ha a bejegyzett PID már nem él (összeomlás, kill,
áramszünet), a következő indulás ELVESZI a zárat. Enélkül egy egyszeri
összeomlás után a program többé nem indulna el, és a felhasználó egy fájlt
keresne, amiről nem tud.

⚠ AMIT NEM VÉD KI: a PID-újrahasznosítást (mint az `opt_lock`-nál). A tévedés
iránya itt is a SZIGORÚ: inkább egy fölösleges elutasítás — amiben ki van írva
a fájl útvonala, tehát kézzel feloldható —, mint két egyszerre kereskedő motor.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Optional

from version import BASE_DIR

DIR = BASE_DIR / "data"


def _safe(account: str) -> str:
    return "".join(c if (c.isalnum() or c in "._-") else "_" for c in str(account))


def lock_path(account: str) -> Path:
    """A zár fájlja — SZÁMLÁNKÉNT külön."""
    return DIR / f"live_{_safe(account) or 'unknown'}.lock"


def _pid_alive(pid: int) -> bool:
    """Fut-e még ez a processz? Platform-független, `psutil` NÉLKÜL.

    ⚠ Windowson az `os.kill(pid, 0)` NEM használható létezés-vizsgálatra (a
    Python jelzéssé fordítja, vagy hibát dob) — ott a Win32 `OpenProcess` a
    helyes út. Az `ACCESS_DENIED` (5) hiba is LÉTEZÉST jelent: a processz
    megvan, csak nem a miénk. (Ugyanaz a függvény, mint az `opt_lock`-ban;
    szándékosan másolat, hogy a két zár egymástól függetlenül élhessen.)"""
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
        return True
    except (OSError, ValueError):
        return True
    return True


def read(account: str) -> Optional[dict]:
    """A zár tartalma, vagy `None`. Sérült/olvashatatlan zár = NINCS zár."""
    try:
        with open(lock_path(account), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def is_held(account: str) -> bool:
    """Fut-e ÉPP motor ezen a számlán — bárhonnan indítva."""
    info = read(account)
    return bool(info) and _pid_alive(int(info.get("pid") or 0))


def acquire(account: str, note: str = "") -> tuple[bool, Optional[dict]]:
    """`(sikerult, akadalyozo_info)`. Sikernél `(True, None)`."""
    cur = read(account)
    # ⚠ A SAJÁT zárunkba ne akadjunk bele (újrahívás ugyanabból a processzből).
    _pid = int(cur.get("pid") or 0) if cur else 0
    if cur and _pid != os.getpid() and _pid_alive(_pid):
        return False, cur
    p = lock_path(account)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "started_at": time.time(),
            "account": str(account),
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
        # feltétel: egy írásvédett mappa miatt ne álljon le a kereskedés.
        # A hívó naplózza, hogy a védelem ezúttal elveszett.
        return True, None


def release(account: str) -> bool:
    """A SAJÁT zárunk elengedése. Idegen zárat NEM törlünk.

    ⚠ A PID-ellenőrzés nem formaság: egy elárvult zárat átvevő processz
    leállásakor nem szabad egy MÁSIK, közben elindult motor zárát kitörölni."""
    cur = read(account)
    if not cur or int(cur.get("pid") or 0) != os.getpid():
        return False
    try:
        lock_path(account).unlink(missing_ok=True)
        return True
    except OSError:
        return False


def describe(info: dict) -> str:
    """Az akadályozó futás EMBERI leírása — enélkül a felhasználó csak annyit
    látna, hogy „nem indul", és nem tudná, hol keresse a másik példányt."""
    if not info:
        return ""
    kor = ""
    try:
        _kezd = float(info.get("started_at") or 0)
        if _kezd > 0:
            perc = max(0, int((time.time() - _kezd) / 60))
            kor = f", {perc} perce" if perc else ", épp most"
    except (TypeError, ValueError):
        pass
    return (f"pid {info.get('pid')} @ {info.get('host') or '?'}{kor}"
            f" ({info.get('cmd') or '?'}"
            + (f", v{info['version']}" if info.get("version") else "") + ")")

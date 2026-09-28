"""FELÜGYELŐ — a bróker-motorok indítása, leállítása, és (kérésre) újraindítása.

⚠ 0029 „Több bróker egyszerre", 4b lépés (2026-09-28). Minden további bróker
motorja külön processz (`python main.py console --broker <id>`). A felügyelő a
felületből indítja és állítja le őket; ha a profilban `"autostart": true`,
a leállt motort újra is indítja.

⚠ FÜGGETLEN PROCESSZ. A motor a felülettől LEVÁLASZTVA indul (Windowson
DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP): ha a felület lefagy vagy
bezárod, a kereskedés megy tovább. Ez volt a döntés oka („külön processz").

⚠ MIKOR FUT EGY MOTOR — MÉRT adatból: a futás-zár (`core/live_lock`) a SZÁMLÁHOZ
tartozik, és azt nézi, él-e a bejegyzett processz. Ugyanaz a zár akadályozza
meg a dupla indítást is: egy második motor ugyanarra a számlára ki sem jut a
zárig (a `console` parancs kilép) — tehát egy félrekattintás sem kötne duplán.

⚠ AZ ÚJRAINDÍTÁS SZABÁLYAI (`tick`):
  • CSAK ha a profilban `autostart: true`;
  • CSAK ha a motor processze NEM ÉL (a zár nem foglalt);
  • NEM, ha a motor RENDBEN állt le (a te leállításod / a konzol `quit`-je:
    az állapotkép `stopped: true`) — a felügyelő nem írhatja felül a döntésedet;
  • egy élő, de beragadt motort NEM öl meg — csak a fül jelzi „hibás"-nak;
  • FÉK: `MAX_RESTARTS` / `WINDOW_SEC` — egy folyton összeomló motor nem indul
    újra végtelenül (a hiba oka a naplóban van, nem a gyakoriságban).
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from core import engine_channel as CH
from core import engine_status as ES

ROOT = Path(__file__).resolve().parents[1]
MAX_RESTARTS = 3
WINDOW_SEC = 600.0


def running(profile) -> bool:
    """Él-e a bróker motorja (a számla futás-zára foglalt-e)."""
    from core import live_lock
    return bool(profile.login) and live_lock.is_held(str(profile.login))


def log_path(profile) -> Path:
    from core import broker_paths
    return broker_paths.account(broker_paths.DATA / "engine_console.log", profile)


def command(profile) -> list:
    return [sys.executable, str(ROOT / "main.py"), "console", "--broker", profile.id]


def start(profile, popen=subprocess.Popen) -> tuple[bool, str]:
    """A motor indítása leválasztott processzként. (siker, üzenet-kulcs)."""
    if running(profile):
        return False, "already_running"
    lp = log_path(profile)
    lp.parent.mkdir(parents=True, exist_ok=True)
    flags = 0
    if sys.platform == "win32":
        flags = (getattr(subprocess, "DETACHED_PROCESS", 0x8)
                 | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200))
    with open(lp, "a", encoding="utf-8") as log:
        log.write(f"\n=== indítás {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        log.flush()
        popen(command(profile), cwd=str(ROOT), stdin=subprocess.DEVNULL,
              stdout=log, stderr=subprocess.STDOUT, creationflags=flags,
              close_fds=True)
    return True, "started"


def stop(profile, request=CH.request) -> tuple[bool, str]:
    """Rendes leállítás a csatornán (a motor a saját kilépési útján áll le)."""
    if not running(profile):
        return False, "not_running"
    r = request(profile, "quit", True)
    return (True, "stopping") if r is not None else (False, "no_answer")


class Supervisor:
    """Az `autostart` profilok figyelése. A felület hívja a `tick`-et (pl.
    30 mp-enként) — saját szál nincs, a felület ütemez."""

    def __init__(self, starter=start, is_running=running, reader=ES.read,
                 clock=time.time):
        self._start, self._running, self._read, self._clock = \
            starter, is_running, reader, clock
        self._inditasok: dict = {}                 # id -> [időpontok]

    def tick(self, profiles, autostart_of) -> list:
        """Egy kör. Visszaad: [(profil-id, esemény)] — a felület kiírja."""
        esemenyek = []
        most = self._clock()
        for p in profiles:
            if not autostart_of(p) or self._running(p):
                continue
            snap = self._read(p)
            if snap and snap.get("stopped"):
                continue                           # a te leállításod — nem írjuk felül
            friss = [t for t in self._inditasok.get(p.id, []) if most - t < WINDOW_SEC]
            if len(friss) >= MAX_RESTARTS:
                esemenyek.append((p.id, "restart_limit"))
                self._inditasok[p.id] = friss
                continue
            ok, _ = self._start(p)
            if ok:
                friss.append(most)
                esemenyek.append((p.id, "restarted"))
            self._inditasok[p.id] = friss
        return esemenyek

"""MOTOR-ÁLLAPOTKÉP — egy bróker-motor közzéteszi magát, a felület OLVASSA.

⚠ 0029 „Több bróker egyszerre", 4. lépés (2026-09-28), OLVASÓ MÓD. Minden
további bróker a fej nélküli motorral fut KÜLÖN processzben
(`python main.py console --broker roboforex`). A felület nem érheti el a
memóriáját — ezért a motor pár másodpercenként kiírja az állapotát a SAJÁT
számla-mappájába (`data/accounts/<id>/engine_status.json`), a felület pedig
ezt olvassa.

⚠ MIÉRT FÁJL, ÉS NEM SOCKET. Olvasáshoz ez a legrobusztusabb: nincs port,
tűzfal, újrakapcsolódás; a motor összeomlása után is ott marad az utolsó kép
(a korából látszik, hogy nem friss). A VEZÉRLÉS (Play/Stop, zárás) a következő
körben jön — ahhoz kétirányú csatorna kell.

⚠ ATOMIKUS ÍRÁS (temp → replace): a felület sosem láthat félig írt fájlt.

⚠ AZ ÉLETJEL ÉRTÉKELÉSE AZ OLVASÓÉ (`health`), és MÉRT adatból:
    nincs   — nincs állapotfájl (a motor sosem futott ezen a gépen)
    all     — a motor rendben leállt (kilépéskor `stopped: true`-t ír)
    hibas   — a kép ELAVULT (a motor összeomlott / lefagyott), vagy a motor
              maga jelez bajt (a kereskedő szál halott, nincs MT5-kapcsolat)
    fut     — friss kép, élő szál, él az MT5
Egy zöld pont, ami nem néz semmit, rosszabb a semminél (a konzol state_rows
elve) — ezért a „fut" három mért feltétel ÉS-e.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
from pathlib import Path

VERSION = 1
FILE = "engine_status.json"
# ⚠ 2026-09-30 (Tibi: „két instrumentum között 3-5 mp alatt frissül"): külső
# módban az ÁRAK is ebből a képből jönnek — 2 mp + a felület 3 mp-es ár-szála
# + 1 mp rajzolás = átlag 3-4 mp késés. 0,5 mp-re sűrítve; a kép elkészítése
# mérve (lásd Publisher: ha a periódus felénél tovább tart, a napló szól).
PERIOD_SEC = 0.5                 # 4b/3 S2: a fő tábla is ebből él (volt 5, majd 2 mp)
STALE_SEC = 30.0                 # ennél régebbi kép = a motor nem ír → hibás

NINCS, ALL, HIBAS, FUT = "nincs", "all", "hibas", "fut"


def path(profile=None) -> Path:
    """A bróker állapotfájlja (`data/accounts/<id>/engine_status.json`)."""
    from core import broker_paths
    return broker_paths.account(broker_paths.DATA / FILE, profile)


# ── ÍRÓ OLDAL (a motor) ─────────────────────────────────────────────────────

def _json_ok(v):
    """A pozíció-dictekben lehet datetime / numpy szám — JSON-barát alakra."""
    if isinstance(v, dict):
        return {str(k): _json_ok(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_ok(x) for x in v]
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    try:
        return float(v)
    except Exception:
        return str(v)


def snapshot(ctx, profile, *, server_offset_sec=None, stopped=False,
             now: float | None = None, optimizer_status=None,
             extra: dict | None = None) -> dict:
    """Az állapotkép a konzol KÖZÖS soraiból (`core.console_cmd`) — ugyanazt
    mutatja, amit a konzol és a TUI; külön lekérdezés nem készül."""
    from core import console_cmd as C
    from version import APP_VERSION
    now = time.time() if now is None else now
    try:
        acc = ctx.account() or {}
    except Exception:
        acc = {}
    ts = float(ctx.last_cycle_ts() or 0)
    return _json_ok({
        "v": VERSION,
        "broker": {"id": profile.id, "tag": profile.tag, "name": profile.name,
                   "server": profile.server, "login": profile.login,
                   "is_demo": profile.is_demo},
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "version": APP_VERSION,
        "ts": now,
        "stopped": bool(stopped),
        "server_offset_sec": server_offset_sec,
        "engine_alive": bool(ctx.engine_alive()),
        "mt5_ok": bool(ctx.mt5_ok()),
        "last_cycle_age": (now - ts) if ts > 0 else None,
        "account": acc,
        "pairs": C.pair_rows(ctx),
        "positions": C.position_rows(ctx),
        # ⚠ 4b/3 S2: a KIJELZÉS-TÜKÖR — a fő tábla egy másik processzben ebből
        # tölti a saját dictjeit (core/engine_mirror). A típus-visszaállítás ott.
        "dashboard": _tukor_dashboard(ctx),
        "instrument_state": dict(getattr(ctx, "instrument_state", {}) or {}),
        "optimizer_status": dict(optimizer_status or {}),
        # 4b/3 S4: amit a felület eddig SAJÁT MT5-hívással kérdezett (számla-
        # típus, pozíció-összesítő, mai lezártak) — a hívó adja (`extra`).
        **(extra or {}),
    })


# ⚠ WINDOWS: a csere (`replace`) „hozzáférés megtagadva"-val elbukik, ha a cél-
# fájlt épp OLVASSÁK (a felület 2 mp-enként olvas, a motor 5 mp-enként ír — ez
# a teszt első futásán azonnal előjött). Rövid várakozással újrapróbáljuk; az
# olvasó is újrapróbál. Enélkül a fül rendszeresen „nincs adat"-ra villanna.
# ⚠ 2026-09-29: a 6 × 50 ms (0,3 s) terhelés alatt kevés volt — a verseny-teszt
# időnként elbukott (az olvasó folyamatosan nyitva tartotta a fájlt). NÖVEKVŐ
# várakozás: 10 ms-tól duplázva, 200 ms-nál megállva, összesen ~1,2 mp.
_PROBA = 10


def _var(i: int) -> float:
    return min(0.01 * (2 ** i), 0.2)


def _tukor_dashboard(ctx) -> dict:
    try:
        from core import engine_mirror
        return engine_mirror.dump_dashboard(getattr(ctx, "dashboard", {}) or {})
    except Exception:
        return {}


def write(data: dict, p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    for i in range(_PROBA):
        try:
            tmp.replace(p)
            return
        except PermissionError:
            if i == _PROBA - 1:
                raise
            time.sleep(_var(i))


class Publisher:
    """Háttérszál: `PERIOD_SEC`-enként kiírja a képet. `stop()` a végső,
    `stopped: true` képet írja — így a felület a rendes leállást meg tudja
    különböztetni az összeomlástól."""

    def __init__(self, ctx, profile, offset_fn=lambda: None, period=PERIOD_SEC,
                 optimizer_status=None, extra_fn=None):
        self.ctx, self.profile, self.offset_fn = ctx, profile, offset_fn
        self.optimizer_status = optimizer_status
        self.extra_fn = extra_fn
        self.period = period
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._fut, daemon=True,
                                   name="EngineStatus")
        self.p = path(profile)

    def _egyszer(self, stopped=False):
        t0 = time.perf_counter()
        try:
            write(snapshot(self.ctx, self.profile, server_offset_sec=self.offset_fn(),
                           stopped=stopped, optimizer_status=self.optimizer_status,
                           extra=self._extra()),
                  self.p)
        except Exception as ex:                      # a kereskedést sosem állítja meg
            import logging
            logging.getLogger(__name__).warning("motor-állapotkép írási hiba: %s", ex)
        # ⚠ a sűrű közzététel (0,5 mp) csak akkor ér valamit, ha a kép elkészül
        # addig — ha nem, EGYSZER szólunk (a periódus nem csúszik némán)
        dt = time.perf_counter() - t0
        if dt > self.period * 0.5 and not getattr(self, "_lassu_jelezve", False):
            self._lassu_jelezve = True
            import logging
            logging.getLogger(__name__).warning(
                "motor-állapotkép: egy kép %.0f ms (a periódus %.0f ms) — a felület "
                "késve frissül", dt * 1000, self.period * 1000)

    def _extra(self) -> dict:
        try:
            return dict(self.extra_fn() or {}) if self.extra_fn else {}
        except Exception:
            return {}

    def _fut(self):
        while not self._stop.is_set():
            self._egyszer()
            self._stop.wait(self.period)

    def start(self):
        self._t.start()
        return self

    def stop(self):
        self._stop.set()
        self._t.join(timeout=5)
        self._egyszer(stopped=True)


# ── OLVASÓ OLDAL (a felület) ────────────────────────────────────────────────

def read(profile=None, p: Path | None = None) -> dict | None:
    """A bróker utolsó képe, vagy None (nincs fájl / olvashatatlan).
    Átmeneti (csere közbeni) hibánál újrapróbál — lásd `write`."""
    p = p or path(profile)
    for i in range(_PROBA):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (PermissionError, json.JSONDecodeError):
            time.sleep(_var(i))
        except Exception:
            return None
    return None


def health(snap: dict | None, now: float | None = None) -> str:
    """`nincs` | `all` | `hibas` | `fut` — lásd a modul fejlécét."""
    if not snap:
        return NINCS
    if snap.get("stopped"):
        return ALL
    now = time.time() if now is None else now
    if now - float(snap.get("ts") or 0) > STALE_SEC:
        return HIBAS
    if not snap.get("engine_alive") or not snap.get("mt5_ok"):
        return HIBAS
    return FUT


def server_clock(snap: dict | None, now: float | None = None):
    """A bróker SZERVER-órája most (naiv datetime), a kép eltolásából; None, ha
    nem ismert. A fejléc „RoboForex: 11:23" sorához."""
    import datetime as _dt
    if not snap or snap.get("server_offset_sec") is None:
        return None
    now = time.time() if now is None else now
    return (_dt.datetime(1970, 1, 1)
            + _dt.timedelta(seconds=now + float(snap["server_offset_sec"])))

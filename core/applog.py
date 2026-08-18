"""
Perzisztens futásnapló — `data/tradeforge.log` (forgó fájl).

Eddig a naplózás CSAK a konzolra ment: ha a program ablaka bezárult vagy a
konzol-puffer túlcsordult, a nap eseményei (belépők, elutasított megbízások,
kapcsolat-szakadások, breakeven/trailing lépések) nyomtalanul elvesztek — pont
azok, amikből utólag kideríthető, MIÉRT nem született meg egy kötés.

Amit ez a modul ad:
  • FÁJLBA is naplóz, UTF-8-ban (a magyar szöveg és a jelölő ikonok is olvashatók
    maradnak — a Windows-konzol kódlapja ezeket elrontja);
  • FORGATJA a fájlt (alap: 5 MB × 5 példány ≈ 25 MB felső korlát), tehát nem nő
    a végtelenségig;
  • a konzolos kimenetet MEGTARTJA (a felület napló-fülje és a fejlesztés innen
    olvas), csak kiegészíti.

Használat: a belépési pontok (`main.py`, `live_trader.main`) hívják EGYSZER,
indulás után. Idempotens — a többszöri hívás nem duplázza a sorokat.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
from pathlib import Path

LOG_DIR  = Path(__file__).resolve().parents[1] / "data"
LOG_PATH = LOG_DIR / "tradeforge.log"

MAX_BYTES     = 5 * 1024 * 1024   # egy fájl max mérete
BACKUP_COUNT  = 5                 # ennyi korábbi példány marad meg
FORMAT        = "%(asctime)s  %(levelname)-8s %(name)s: %(message)s"
DATEFMT       = "%Y-%m-%d %H:%M:%S"

_MARKER = "_tradeforge_file_log"   # az idempotenciához (a handleren jelöljük)


def harden_console() -> None:
    """A konzolos kimenet ne szálljon el a nem-latin karaktereken (✦ ↗ ⏭ 📋 ≠).

    A napló mellett a `tools/` parancssori eszközök is hívhatják.

    A Windows-konzol kódlapja (cp1250) ezeket nem tudja leképezni, és a
    `StreamHandler` `UnicodeEncodeError`-t dob — a `logging` ezt ugyan elnyeli
    (a program nem áll meg), de az ÜZENET ELVÉSZ a konzolról, és hibazaj marad
    helyette. A kódlapot NEM írjuk át (régi konzolokon az törhet), csak a
    hibakezelést lazítjuk: a leképezhetetlen karakter „?" lesz. A FÁJLBA
    mindeközben a valódi UTF-8 szöveg megy."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass                       # nem-újrakonfigurálható stream (pipe, teszt)


def setup(level: int = logging.INFO) -> "Path | None":
    """A forgó fájl-napló bekapcsolása. Visszaadja a napló útját (vagy None, ha
    nem sikerült — ilyenkor a konzolos naplózás változatlanul megy tovább, a
    program nem áll meg egy naplózási hiba miatt)."""
    root = logging.getLogger()
    harden_console()
    for h in root.handlers:
        if getattr(h, _MARKER, False):
            return LOG_PATH               # már be van kapcsolva
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            LOG_PATH, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT,
            encoding="utf-8", delay=True)
    except Exception as e:                 # csak olvasható lemez, jogosultság…
        logging.getLogger(__name__).warning(
            "A fájl-napló nem hozható létre (%s): %s — csak konzolra naplózunk.",
            LOG_PATH, e)
        return None

    handler.setFormatter(logging.Formatter(FORMAT, datefmt=DATEFMT))
    handler.setLevel(level)
    setattr(handler, _MARKER, True)
    root.addHandler(handler)
    # A gyökér szintje szűkebb lehet, mint a handleré → a fájlba semmi nem jutna.
    if root.level > level or root.level == logging.NOTSET:
        root.setLevel(level)

    # A konzolos ág megmarad: ha a modulok `basicConfig`-ja még nem futott le
    # (import-sorrend), pótoljuk, hogy ne csak fájlba menjen minden.
    if not any(isinstance(h, logging.StreamHandler)
               and not isinstance(h, logging.FileHandler) for h in root.handlers):
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-8s %(message)s", datefmt=DATEFMT))
        root.addHandler(console)

    install_thread_excepthook()
    install_tk_excepthook()
    install_sys_excepthook()
    install_error_counter()

    logging.getLogger(__name__).info(
        "Futásnapló: %s (max %d MB × %d példány)",
        LOG_PATH, MAX_BYTES // (1024 * 1024), BACKUP_COUNT + 1)
    return LOG_PATH


def install_thread_excepthook() -> None:
    """Elkapott NÉLKÜLI szál-kivétel → a NAPLÓBA is, ne csak a konzolra.

    ⚠ VALÓS KÁR (2026-08-08). A `LiveTrader` szál egy `KeyError: 'point_size'`-zal
    elhalt induláskor, tehát EGYETLEN pár sem kereskedett és a viz-fájlok sem
    íródtak. A traceback a Python alapértelmezett szál-hook-jával a STDERR-re ment
    — a `tradeforge.log`-ban NYOMA SEM VOLT. A napló utolsó sora egy ártatlan
    „CSAK JELZÉS mód" figyelmeztetés volt, a program pedig kívülről úgy nézett ki,
    mint ami fut. A hiba hetekig észrevétlen maradt.

    Idempotens: többszöri hívásnál nem láncol újra."""
    if getattr(threading.excepthook, _MARKER, False):
        return
    _prev = threading.excepthook

    def _hook(args):
        try:
            logging.getLogger("thread").critical(
                "⛔ A(z) %r szál ELHALT elkapatlan kivétellel — az általa végzett "
                "munka MEGÁLLT. A program látszólag fut tovább.",
                getattr(args.thread, "name", "?"),
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        except Exception:
            pass
        _prev(args)                        # a konzolos traceback maradjon meg

    setattr(_hook, _MARKER, True)
    threading.excepthook = _hook


def install_tk_excepthook() -> None:
    """Felület-visszahívásban dobott kivétel → a NAPLÓBA.

    ⚠ EZ VOLT A LEGNAGYOBB VAK FOLT. A Tkinter minden visszahívást (gomb-parancs,
    kötés, `after`) becsomagol, és ha az kivételt dob, a `report_callback_exception`
    a STDERR-re írja a tracebacket. Egy ABLAKOS alkalmazásban a stderr sehol nincs:
    a gomb egyszerűen „nem csinál semmit", a napló pedig hallgat.

    Mérve (2026-08-18): a naptár-választó visszahívása `AttributeError`-t dobott
    minden kattintásra — a dátum SOSEM íródott be, és sem a felületen, sem a
    `tradeforge.log`-ban nem volt nyoma. A felhasználó ezt hibaként jelentette, mi
    pedig csak forrásolvasással találtuk meg.

    A hook a `Tk` OSZTÁLYRA kerül, nem egy példányra: a `Misc._report_exception`
    mindig a GYÖKÉR ablakon hívja meg, tehát egyetlen hely lefedi az összes
    Toplevelt és widgetet — ezt a 205 külön `except`-ág sosem tudná.

    Idempotens."""
    try:
        import tkinter
    except Exception:
        return                                  # fej nélküli környezet
    if getattr(tkinter.Tk.report_callback_exception, _MARKER, False):
        return
    _prev = tkinter.Tk.report_callback_exception

    def _hook(self, exc, val, tb):
        try:
            logging.getLogger("gui").error(
                "⛔ Kezeletlen hiba egy felület-visszahívásban (%s) — a művelet "
                "NEM futott le, a felület viszont ugyanúgy néz ki, mint máskor.",
                getattr(exc, "__name__", exc), exc_info=(exc, val, tb))
        except Exception:
            pass
        try:
            _prev(self, exc, val, tb)           # a konzolos traceback maradjon
        except Exception:
            pass

    setattr(_hook, _MARKER, True)
    tkinter.Tk.report_callback_exception = _hook


def install_sys_excepthook() -> None:
    """A FŐSZÁL elkapatlan kivétele → a naplóba (a szál-hook csak a többit fedi)."""
    if getattr(sys.excepthook, _MARKER, False):
        return
    _prev = sys.excepthook

    def _hook(exc_type, exc, tb):
        try:
            logging.getLogger("main").critical(
                "⛔ A főszál elkapatlan kivétellel állt le.",
                exc_info=(exc_type, exc, tb))
        except Exception:
            pass
        _prev(exc_type, exc, tb)

    setattr(_hook, _MARKER, True)
    sys.excepthook = _hook


# ---------------------------------------------------------------------------
# HIBA-SZÁMLÁLÓ — hogy a napló ne csak létezzen, hanem LÁTSZÓDJON is
# ---------------------------------------------------------------------------
# ⚠ Egy naplófájl, amibe senki nem néz bele, majdnem annyira néma, mint a
# semmi. A számláló abból él, hogy a felület KI TUDJA írni: „⚠ 3 hiba a
# naplóban" — onnantól a felhasználó tudja, hogy van mit megnézni.

_ERR_LOCK = threading.Lock()
_ERR = {"count": 0, "last": ""}


class _ErrorCounter(logging.Handler):
    def emit(self, record):
        try:
            with _ERR_LOCK:
                _ERR["count"] += 1
                _ERR["last"] = f"{record.name}: {record.getMessage()}"[:200]
        except Exception:
            pass


def install_error_counter(level: int = logging.ERROR) -> None:
    """ERROR/CRITICAL rekordok SZÁMLÁLÁSA (a felület ebből tud szólni). Idempotens."""
    root = logging.getLogger()
    if any(isinstance(h, _ErrorCounter) for h in root.handlers):
        return
    h = _ErrorCounter(level=level)
    setattr(h, _MARKER, True)
    root.addHandler(h)


def error_stats() -> tuple:
    """`(darab, utolsó üzenet)` — az indulás óta naplózott ERROR+ rekordokból."""
    with _ERR_LOCK:
        return _ERR["count"], _ERR["last"]


def reset_error_stats() -> None:
    with _ERR_LOCK:
        _ERR["count"] = 0
        _ERR["last"] = ""

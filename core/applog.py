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
from pathlib import Path

LOG_DIR  = Path(__file__).resolve().parents[1] / "data"
LOG_PATH = LOG_DIR / "tradeforge.log"

MAX_BYTES     = 5 * 1024 * 1024   # egy fájl max mérete
BACKUP_COUNT  = 5                 # ennyi korábbi példány marad meg
FORMAT        = "%(asctime)s  %(levelname)-8s %(name)s: %(message)s"
DATEFMT       = "%Y-%m-%d %H:%M:%S"

_MARKER = "_tradeforge_file_log"   # az idempotenciához (a handleren jelöljük)


def _harden_console() -> None:
    """A konzolos kimenet ne szálljon el a naplóban használt ikonokon (✦ ↗ ⏭ 📋).

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
    _harden_console()
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

    logging.getLogger(__name__).info(
        "Futásnapló: %s (max %d MB × %d példány)",
        LOG_PATH, MAX_BYTES // (1024 * 1024), BACKUP_COUNT + 1)
    return LOG_PATH

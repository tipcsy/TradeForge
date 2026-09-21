"""A karmester fájljainak helye — EGY gazdával.

    data/conductor/
      telemetry/<ÉÉÉÉ-HH-NN>.json   — napi belépő-telemetria
      decisions.jsonl               — krónika (F1-től)
      state.json                    — a karmester perzisztens állapota (F2-től)
      off                           — KILL SWITCH: ha létezik, a karmester L-1

⚠ MIÉRT KÜLÖN MODUL EGY-KÉT ÚTVONALÉRT. A projektben a `data/` alatti fájlok
útvonala eddig minden modulban külön `Path(__file__).resolve().parents[1] / …`
sorként élt (`risky_mode`, `rr_state`, `adopted`, `position_meta`, `correlation`,
`params_store`). Ez addig jó, amíg egy modul egy fájlt kezel — a karmesternek
viszont TÖBB fájlja van, amiket a motor, a felület és a tesztek is elérnek. Ha az
útvonal öt helyen áll, egy teszt könnyen a FELHASZNÁLÓ valódi `data/` mappájába
ír (ez a projektben már háromszor megtörtént), és a teszt elirányítása sem
megoldható egy helyen.

Itt egy `DIR` van; minden más ebből származik. A teszt átállítja a `DIR`-t, és
azzal MINDEN útvonal átáll.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

# ⚠ A `version.BASE_DIR`-t használjuk, nem a `__file__` szülőjét: PyInstaller
# EXE-ben a kód a csomagban van, az adat viszont az .exe mellett — a többi
# adat-modul (`params_store`, `rr_state`) még a `__file__`-ra épül, de egy ÚJ
# csomagnál nincs okunk megismételni azt.
try:
    from version import BASE_DIR as _BASE
except Exception:                                   # pragma: no cover
    _BASE = Path(__file__).resolve().parents[1]

DIR = Path(_BASE) / "data" / "conductor"


def telemetry_dir() -> Path:
    return DIR / "telemetry"


def telemetry_file(day: str) -> Path:
    """Egy NAP telemetriája. `day`: `ÉÉÉÉ-HH-NN` (a hívó adja, lásd
    `telemetry.day_key`)."""
    return telemetry_dir() / f"{day}.json"


def journal_file() -> Path:
    return DIR / "decisions.jsonl"


def state_file() -> Path:
    return DIR / "state.json"


def trades_csv() -> Path:
    """A MOTOR kereskedési naplója (`trades.csv`) — a karmester OLVASSA, nem írja.

    ⚠ MIÉRT NEM A `live_trader.TRADES_CSV`-t importáljuk. Az a modul MT5-öt húz
    be; a karmester mérő rétege viszont MT5-mentes marad, hogy a felület, a
    tesztek és egy későbbi elemző eszköz is használhassa. Az útvonal egy sor —
    az MT5-függés az egész csomagot megfertőzné.

    ⚠ ÉS MIÉRT EBBŐL DOLGOZUNK. Ez a napló a KÖZÖS forrás: innen mennek a
    Telegram-értesítések és ebből számol a napi összesítő is. Egy külön
    karmester-nyilvántartás a lezárt kötésekről előbb-utóbb MÁS számot adna
    ugyanarra a napra — ez a projekt visszatérő hibaosztálya."""
    return Path(_BASE) / "trades.csv"


def off_switch() -> Path:
    """A KILL SWITCH fájlja. Ha létezik, a karmester L-1 (kikapcsolt) — és ezt
    a szál minden ciklus ELEJÉN, a mérés előtt megnézi."""
    return DIR / "off"


def ensure(sub: "Path | None" = None) -> bool:
    """A mappa létrehozása. Visszaad: sikerült-e.

    ⚠ NEM DOB. A karmester MÉRŐ réteg: egy írhatatlan mappa miatt nem állhat meg
    a kereskedés. De nem is néma — a hívó a `False`-ból tudja, hogy nincs hova
    írni, és egyszer naplóz."""
    try:
        (sub or DIR).mkdir(parents=True, exist_ok=True)
        return True
    except Exception as ex:
        log.warning("conductor: a mappa nem hozható létre (%s): %s", sub or DIR, ex)
        return False

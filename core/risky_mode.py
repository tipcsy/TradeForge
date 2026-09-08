"""
Risky mód állapot — instrumentumonként, perzisztens JSON-ban.

A felület gombnyomásra AZONNAL menti az állapotot (data/risky_mode.json), a
live_trader óránként újraolvassa, és egy KÜLSŐ program (indikátor) is írhatja a
fájlt — így ő mondja meg, mely instrumentum "instabil" (risky).

A GUI és a live_trader UGYANABBAN a folyamatban fut, ezért a modul-szintű
állapotot mindkettő közvetlenül látja; az újraolvasás csak a külső írásokhoz kell.

Fájlformátum:  {"XAUUSD": true, "GBPAUD": false, ...}
"""

import json
import logging
import threading
from pathlib import Path

log = logging.getLogger(__name__)

PATH = Path(__file__).resolve().parents[1] / "data" / "risky_mode.json"

_lock = threading.Lock()
_state: dict[str, bool] = {}


def load() -> dict:
    """A fájl újraolvasása a memóriába (külső módosítások átvétele).
    A fájl a mérvadó forrás (a set_risky mindig ír), ezért teljes csere."""
    with _lock:
        try:
            if PATH.exists():
                with open(PATH, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    _state.clear()
                    _state.update({str(k): bool(v) for k, v in data.items()})
        except Exception as ex:
            # ⚠ A risky KOCKÁZATI mód: némán üresen indulni azt jelenti, hogy
            # minden pár normál méretre és normál BE-re vált — a felhasználó
            # által bekapcsolt óvatosság csendben megszűnik.
            log.error("%s: a risky-állapot NEM OLVASHATÓ (%s) — minden pár "
                      "NORMÁL módra esik vissza.", PATH.name, ex)
        return dict(_state)


def is_risky(symbol: str) -> bool:
    with _lock:
        return _state.get(symbol, False)


def set_risky(symbol: str, value: bool):
    """Beállít + AZONNAL ment, így az óránkénti újraolvasás nem állítja vissza
    (pl. 0:59-kor bekapcsolva nem ugrik vissza defaultra 1 perc múlva)."""
    with _lock:
        _state[symbol] = bool(value)
        _save_locked()


def toggle(symbol: str) -> bool:
    with _lock:
        new = not _state.get(symbol, False)
        _state[symbol] = new
        _save_locked()
        return new


def all_states() -> dict:
    with _lock:
        return dict(_state)


def _save_locked():
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_state, f, indent=2, ensure_ascii=False)
        tmp.replace(PATH)
    except Exception as ex:
        log.error("%s: a risky-állapot MENTÉSE nem sikerült (%s). A kapcsoló "
                  "csak a memóriában él — újraindítás után elveszik.",
                  PATH.name, ex)

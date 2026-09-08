"""A Backtest-ablak megjegyzett beállításai (per stratégia+pár).

A felület „feltáró" beállításai (preset/építés) SZÁNDÉKOSAN nem mentődnek, de a
kényelmi mezők — Időszak (kezdő/záró dátum), Nyitó összeg, Slotok — igen: a
következő megnyitáskor visszatöltődnek, hogy ne kelljen újra beírni.

Tároló: `data/backtest_prefs.json`  →  { "<stratégia>/<SYMBOL>": {kulcs: érték} }.
Best-effort: hiba esetén üres/kihagy — a backtest működését nem érinti, tehát a
program megy tovább. De ⚠ a HIÁNYZÓ fájl (első indítás) és a SÉRÜLT fájl nem
ugyanaz: az első normális, a második elveszett beállításokat jelent, és eddig
mindkettő ugyanolyan néma volt. A sérülésről szólunk — futásonként EGYSZER, mert
ez a modul minden ablaknyitáskor olvas, és egy percenként ismétlődő figyelmeztetés
ugyanolyan használhatatlan, mint a hallgatás."""
from __future__ import annotations

import json
import logging

from version import BASE_DIR

log = logging.getLogger(__name__)

_FILE = BASE_DIR / "data" / "backtest_prefs.json"

# Futásonként egyszer szólunk az olvasási hibáról (lásd a modul fejlécét).
_read_warned = False


def _load() -> dict:
    global _read_warned
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}                      # első indítás — ez a NORMÁLIS állapot
    except Exception as ex:
        if not _read_warned:
            _read_warned = True
            log.warning("%s: a mentett backteszt-beállítások nem olvashatók "
                        "(%s) — az ablak az alapértékekkel nyílik.",
                        _FILE.name, ex)
        return {}


def _key(symbol: str, strategy: str) -> str:
    return f"{strategy}/{symbol}"


def get(symbol: str, strategy: str) -> dict:
    """A mentett beállítások (üres dict, ha nincs)."""
    return _load().get(_key(symbol, strategy), {}) or {}


def save(symbol: str, strategy: str, **vals) -> None:
    """A megadott (nem-None) kulcsok mentése. A None értékek kimaradnak."""
    data = _load()
    entry = data.get(_key(symbol, strategy), {}) or {}
    entry.update({k: v for k, v in vals.items() if v is not None})
    data[_key(symbol, strategy)] = entry
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        _FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    except Exception as ex:
        log.warning("%s: a backteszt-beállítások MENTÉSE nem sikerült (%s) — a "
                    "mezők a következő megnyitáskor üresek lesznek.",
                    _FILE.name, ex)

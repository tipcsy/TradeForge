"""A Backtest-ablak megjegyzett beállításai (per stratégia+pár).

A felület „feltáró" beállításai (preset/építés) SZÁNDÉKOSAN nem mentődnek, de a
kényelmi mezők — Időszak (kezdő/záró dátum), Nyitó összeg, Slotok — igen: a
következő megnyitáskor visszatöltődnek, hogy ne kelljen újra beírni.

Tároló: `data/backtest_prefs.json`  →  { "<stratégia>/<SYMBOL>": {kulcs: érték} }.
Best-effort: hiba esetén csendben üres/kihagy (a backtest működését nem érinti)."""
from __future__ import annotations

import json

from version import BASE_DIR

_FILE = BASE_DIR / "data" / "backtest_prefs.json"


def _load() -> dict:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception:
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
    except Exception:
        pass

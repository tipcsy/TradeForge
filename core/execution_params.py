"""
Közös végrehajtás/kockázat paraméterek — STRATÉGIA-FÜGGETLEN, instrumentumonkénti
érték. Ide tartozik: `atr_period` (a spread-kapu volatilitás-mércéje),
`breakeven_pct`/`trail_activation_atr`/`trail_distance_atr` (a BE+trailing off/
risky ága, lásd `trading/live_trader.py` `_apply_be_and_trailing`), valamint
`max_spread_atr_ratio`/`min_spread_mult` (`core/spread_gate.py`).

Korábban ez az 5-6 kulcs stratégiánként DUPLIKÁLVA élt a `strategy/config/<name>.json`
indicators/sltp/position_mgmt szekcióiban, és a `wpr_sma` az egyetlen, amelyik
ténylegesen hangolta is instrumentumonként (Optuna-tartomány). Mivel egy adott
szimbólumon TÖBB stratégia is futhat, és a BE%/trailing/spread-tűrés a piac/broker
tulajdonsága, nem a belépőjelzésé — ez a modul EGYETLEN, stratégia-független
forrást ad:

  1. `config.json` `"execution"` szekciója — globális alapérték minden párra.
  2. `data/execution_params/<SYMBOL>.json` — per-szimbólum felülírás (analóg a
     `core/params_store.py` per-stratégia tárolójával, csak stratégia-mappa
     NÉLKÜL, mert ez megosztott).

Jövőbeli munka (NEM ez a lépés): egy külön, stratégia-független kalibráló
optimalizáló idővel ide fog írni (potenciálisan TÖBB érték-készletet, pl. piaci
rezsim szerint) — ezért a per-szimbólum fájl formátuma szándékosan a meglévő
`optimized_params` mintát követi.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
EXECUTION_DIR = ROOT / "data" / "execution_params"

# Végső fallback, ha a config.json-ban sincs "execution" szekció (régi/hiányos
# config is biztonságosan fusson — visszafelé kompatibilis a korábbi
# stratégia-config alapértékekkel).
DEFAULTS = {
    "atr_period": 14,
    "breakeven_pct": 0.5,
    "trail_activation_atr": 0.5,
    "trail_distance_atr": 0.4,
    "max_spread_atr_ratio": 0.20,
    "min_spread_mult": 1.5,
}

_KEYS = tuple(DEFAULTS.keys())


def execution_params_file(symbol: str) -> Path:
    return EXECUTION_DIR / f"{symbol}.json"


def load_execution_params(symbol: str, cfg: dict) -> dict:
    """A ténylegesen ható végrehajtási paraméterek egy szimbólumra.

    Sorrend (utóbbi nyer): modul-alapértékek → `cfg["execution"]` (globális) →
    a szimbólum saját `data/execution_params/<SYMBOL>.json` fájlja (ha van)."""
    out = dict(DEFAULTS)
    out.update(cfg.get("execution", {}) or {})
    p = execution_params_file(symbol)
    if p.exists():
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            out.update(data.get("params", {}) or {})
        except Exception as ex:
            log.warning("%s — execution_params olvasási hiba: %s", symbol, ex)
    return {k: out[k] for k in _KEYS if k in out}


def save_execution_params(symbol: str, params: dict) -> None:
    """A szimbólum saját végrehajtási felülírásának atomikus mentése (tmp→replace).
    Csak az ismert 6 kulcsot menti (a hívó szűrhet vagy adhat feleslegeset)."""
    EXECUTION_DIR.mkdir(parents=True, exist_ok=True)
    p = execution_params_file(symbol)
    payload = {
        "symbol": symbol,
        "params": {k: params[k] for k in _KEYS if k in params},
    }
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    tmp.replace(p)

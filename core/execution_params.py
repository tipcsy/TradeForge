"""
Közös VÉGREHAJTÁSI paraméterek — STRATÉGIA-FÜGGETLEN, instrumentumonkénti érték.
Ide tartozik: `atr_period` (a spread-kapu volatilitás-mércéje) és
`max_spread_atr_ratio`/`min_spread_mult` (`core/spread_gate.py`).

⚠ A BE + trailing (`breakeven_pct`, `trail_activation_atr`, `trail_distance_atr`)
v1.96.0 óta NEM ITT van: átkerült a KOCKÁZATCSÖKKENTŐ modulba
(`core/risk_reduction.py` + `core/rr_state.py` per-pár kalibráció). Indok: a
preset dönti el, hogy egyáltalán hatnak-e (Fibo/Harmados preseten SEMMIT nem
csináltak), tehát a kimenet-menedzsment paraméterei — nem a végrehajtásé, és
végképp nem a stratégiáé. A `MIGRATED_KEYS` csak az egyszeri átköltöztetéshez
kell (`tools/migrate_be_trail.py`), új írás már nem történik rájuk.

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
    "max_spread_atr_ratio": 0.20,
    "min_spread_mult": 1.5,
}

_KEYS = tuple(DEFAULTS.keys())

# A v1.96.0-ban a kockázatcsökkentő modulba ÁTKÖLTÖZTETETT kulcsok. A régi
# per-szimbólum fájlokban még ott lehetnek; a `load_execution_params` NEM adja
# vissza őket (a motor máshonnan olvassa), és a `save_execution_params` sem írja
# ki. Egyedül a migráció olvassa (`tools/migrate_be_trail.py`).
MIGRATED_KEYS = ("breakeven_pct", "trail_activation_atr", "trail_distance_atr")


def read_migrated(symbol: str) -> dict:
    """A per-szimbólum fájlban MÉG MEGLÉVŐ, átköltöztetett BE/trailing értékek.
    Üres dict, ha nincs ilyen (már migrált vagy sosem volt)."""
    p = execution_params_file(symbol)
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            params = (json.load(f).get("params") or {})
    except Exception:
        return {}
    return {k: float(params[k]) for k in MIGRATED_KEYS
            if isinstance(params.get(k), (int, float))}


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

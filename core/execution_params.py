"""
Közös VÉGREHAJTÁSI paraméterek — STRATÉGIA-FÜGGETLEN, instrumentumonkénti érték.
Ide tartozik: `atr_period` (a spread-kapu volatilitás-mércéje) és
`max_spread_atr_ratio`/`min_spread_mult` (`core/spread_gate.py`), valamint
v3.103.0 óta a VOLATILITÁS-KAPU számai (`VOL_KEYS`: `atr_min_pct`,
`atr_max_pct`, `atr_baseline_bars`, `atr_avg_ref`).

⚠ A VOLATILITÁS-KAPU SZÁMAI MIÉRT ITT. v3.102.0-ig a wpr_sma MENTETT
paraméter-készletében laktak („Piac-szűrő" kategória), és az optimalizáló
hangolta őket — holott (1) a kapu dönt velük, nem a jelzés, és (2) az
`atr_avg_ref` az INSTRUMENTUM M15 ATR-átlaga, amihez a stratégia jelzés-
paramétereinek semmi köze. Egy második stratégia ugyanazon a páron külön,
más időpontban befagyasztott mércét kapott volna. Most instrumentumonként EGY
készlet van; hogy egy stratégiára HAT-e, azt a kapu per-stratégia HATÁSA dönti
el (`core.gates.effect_for`), mint minden más kapunál.

⚠ A BE + trailing (`breakeven_pct`, `trail_activation_atr`, `trail_distance_atr`)
v1.96.0 óta NEM ITT van: átkerült a KOCKÁZATCSÖKKENTŐ modulba
(`core/risk_reduction.py` + `core/rr_state.py` per-pár kalibráció). Indok: a
preset dönti el, hogy egyáltalán hatnak-e (Fibo/Harmados preseten SEMMIT nem
csináltak), tehát a kimenet-menedzsment paraméterei — nem a végrehajtásé, és
végképp nem a stratégiáé. A `MIGRATED_KEYS` csak az egyszeri átköltöztetéshez
kell (`tools/migrate_be_trail.py`), új írás már nem történik rájuk.

Korábban ez az 5-6 kulcs stratégiánként DUPLIKÁLVA élt a `strategies/config/<name>.json`
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

# A VOLATILITÁS-KAPU instrumentum-szintű számai (`gates/vol_baseline.py`).
# ⚠ NINCS ALAPÉRTÉKÜK, és ez szándékos: a hiányzó küszöb = a kapu nem szűr
# (`vol_baseline.failed` → False), ami a hangolatlan párok mai viselkedése.
# Egy beépített alapérték minden eddig szűretlen párt NÉMÁN szűrni kezdene.
# Az `atr_avg_ref` a pár SAJÁT mért száma — globálisan (cfg["execution"])
# nem is állítható, csak a küszöbök.
VOL_KEYS = ("atr_min_pct", "atr_max_pct", "atr_baseline_bars", "atr_avg_ref")
_VOL_GLOBAL_KEYS = ("atr_min_pct", "atr_max_pct", "atr_baseline_bars")

# Minden kulcs, ami az INSTRUMENTUMÉ (nem a stratégiáé) — ezeket a
# stratégia-json-ba menteni tilos, mert ott egy elavult másolat lenne belőlük.
INSTRUMENT_KEYS = _KEYS + VOL_KEYS


def without_vol_keys(params: dict) -> dict:
    """A paraméter-készlet a volatilitás-kapu kulcsai NÉLKÜL — a stratégia
    mentett json-jába ez kerülhet (lásd `VOL_KEYS`)."""
    return {k: v for k, v in (params or {}).items() if k not in VOL_KEYS}

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
    except Exception as ex:
        # ⚠ A fájl LÉTEZIK (fentebb ellenőrizve), tehát ez sérülés — és a néma
        # üres dict itt azt jelenti, hogy a régi BE/trailing értékek NEM
        # költöznek át: a pár a modul alapértékével fut tovább, hangolás nélkül.
        log.warning("%s: a migrálandó végrehajtási paraméterek nem olvashatók "
                    "(%s) — a régi BE/trailing értékek NEM költöznek át.",
                    p.name, ex)
        return {}
    return {k: float(params[k]) for k in MIGRATED_KEYS
            if isinstance(params.get(k), (int, float))}


def execution_params_file(symbol: str) -> Path:
    return EXECUTION_DIR / f"{symbol}.json"


def load_execution_params(symbol: str, cfg: dict) -> dict:
    """A ténylegesen ható végrehajtási paraméterek egy szimbólumra.

    Sorrend (utóbbi nyer): modul-alapértékek → `cfg["execution"]` (globális) →
    a szimbólum saját `data/execution_params/<SYMBOL>.json` fájlja (ha van).

    A volatilitás-kapu kulcsai (`VOL_KEYS`) CSAK akkor vannak a kimenetben, ha
    valahol meg vannak adva — a hiányuk jelentése „a kapu nem szűr"."""
    out = dict(DEFAULTS)
    _glob = cfg.get("execution", {}) or {}
    out.update({k: v for k, v in _glob.items()
                if k in _KEYS or k in _VOL_GLOBAL_KEYS})
    p = execution_params_file(symbol)
    if p.exists():
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            out.update(data.get("params", {}) or {})
        except Exception as ex:
            log.warning("%s — execution_params olvasási hiba: %s", symbol, ex)
    return {k: out[k] for k in INSTRUMENT_KEYS if k in out}


def _read_own(symbol: str) -> dict:
    """A szimbólum SAJÁT fájljának `params` szótára (alapértékek nélkül)."""
    p = execution_params_file(symbol)
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        return dict((json.load(f) or {}).get("params") or {})


def save_execution_params(symbol: str, params: dict) -> None:
    """A szimbólum saját felülírásának atomikus mentése (tmp→replace).

    ⚠ ÖSSZEFÉSÜL, NEM FELÜLÍR. A fájlban két gazda számai laknak (spread-kapu +
    volatilitás-kapu), és mindkét felület csak a SAJÁTJÁT adja át. A korábbi
    „csak az átadott kulcsok" alak a spread mentésekor NÉMÁN törölte volna a
    volatilitás-kapu küszöbeit — a pár onnantól szűretlenül kereskedett volna.
    `None` érték = a kulcs törlése (pl. a kalibrálatlan `atr_avg_ref`).
    Ismeretlen kulcs nem kerül ki."""
    EXECUTION_DIR.mkdir(parents=True, exist_ok=True)
    p = execution_params_file(symbol)
    try:
        own = _read_own(symbol)
    except Exception as ex:
        # ⚠ Sérült fájl fölé NEM írunk: a benne lévő (másik gazdától származó)
        # értékek elvesznének, és semmi nem jelezné.
        raise RuntimeError(f"{p.name} nem olvasható ({ex}) — a mentés elmarad, "
                           f"hogy a benne lévő értékek ne vesszenek el.") from ex
    for k in INSTRUMENT_KEYS:
        if k in (params or {}):
            if params[k] is None:
                own.pop(k, None)
            else:
                own[k] = params[k]
    payload = {
        "symbol": symbol,
        "params": {k: own[k] for k in INSTRUMENT_KEYS if k in own},
    }
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    tmp.replace(p)

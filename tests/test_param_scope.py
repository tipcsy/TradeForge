"""A Parameterek ablak paraméter-HATOKORE — dashboard/instrument_dialog.py.

KET, egymastol fuggetlen szivargast orzunk itt:

1. STRATEGIA-HATOKOR. A futasideju cfg az ELSODLEGES strategia szekcioival van
   merge-elve (`indicators`, `position_mgmt`, optimizer-ter). Ha a `default_params`
   ezt kapja meg, akkor egy MASIK strategia ablakaba beszivarognak a primary
   kulcsai — elesben az `ml_ai` ablakaban jelent meg a `sma_period`, a `wpr_*`,
   az `atr_min_pct`/`atr_max_pct` es a `no_trade_resets_signal`.

2. ELAVULT KULCSOK. A regi, mentett `optimized_params/<strat>/<SYM>.json`-okban
   ott maradt a `max_open_slots`. A motor SOHA nem olvassa parameterkent (a
   `trading` configbol jon), az urlapon viszont szerkeszthetonek latszott es
   mentesnel ujra kiirodott: egy beallitas, ami latszolag hat, valojaban nem.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from strategy import get_strategy_by_name
from strategy.settings import config_for_strategy, apply_strategy_config
from dashboard.instrument_dialog import default_params, _OBSOLETE_PARAM_KEYS

# A `wpr_sma` SAJAT kulcsai — ezek egyike sem tartozik az `ml_ai`-hoz.
WPR_ONLY = ("sma_period", "wpr_m15_period", "wpr_m1_period", "wpr_m1_trigger",
            "wpr_m15_buy_extreme", "wpr_m15_sell_extreme",
            "atr_min_pct", "atr_max_pct", "no_trade_resets_signal")


def base_cfg():
    """A futasideju cfg: a VAZ + az ELSODLEGES (wpr_sma) strategia beolvasztva —
    pontosan az az allapot, amit a GUI atad az ablaknak."""
    cfg = {"strategy": {"name": "wpr_sma"},
           "available_strategies": ["wpr_sma", "ml_ai"],
           "trading": {"account_risk_pct": 0.01, "max_open_slots": 4},
           "pairs": {"GOLD": {"enabled": True, "point_size": 0.01,
                              "pv1_point": 0.88, "min_lot": 0.01,
                              "lot_step": 0.01, "backtest_spread_points": 48.0,
                              "strategies": ["wpr_sma", "ml_ai"]}}}
    return apply_strategy_config(cfg)


# ══ 1. A NYERS cfg tenylegesen szennyez ═══════════════════════════════════
# Ez nem "elmeleti kockazat": ha ez a check FAIL-el, akkor a 2. check semmit
# nem bizonyit (nem volt mit kiszurni).
_raw = default_params(base_cfg(), get_strategy_by_name("ml_ai"))
check("a NYERS cfg-vel az ml_ai megkapna a wpr_sma kulcsait (a hiba oka)",
      all(k in _raw for k in WPR_ONLY),
      str(sorted(k for k in WPR_ONLY if k not in _raw)))

# ══ 2. A strategia NEZETE tiszta ══════════════════════════════════════════
_view = default_params(config_for_strategy(base_cfg(), "ml_ai"),
                       get_strategy_by_name("ml_ai"))
_leak = sorted(k for k in WPR_ONLY if k in _view)
check("a strategia-nezettel egyetlen wpr_sma-kulcs sem szivarog at", not _leak,
      str(_leak))
check("...de az ml_ai SAJAT kulcsai megvannak",
      all(k in _view for k in ("ml_warmup_bars", "sl_atr_mult", "tp_rr_ratio",
                               "dynamic_sltp")),
      str(sorted(_view)))

# ══ 3. A wpr_sma sajat ablaka VALTOZATLAN ═════════════════════════════════
# A javitas nem vehet el semmit az elsodleges strategiatol.
_wpr = default_params(config_for_strategy(base_cfg(), "wpr_sma"),
                      get_strategy_by_name("wpr_sma"))
check("a wpr_sma ablaka tovabbra is a SAJAT teljes keszletet kapja",
      all(k in _wpr for k in WPR_ONLY),
      str(sorted(k for k in WPR_ONLY if k not in _wpr)))

# ══ 4. Az elavult kulcsok listaja ═════════════════════════════════════════
check("a max_open_slots elavult parameter-kulcskent van szamon tartva",
      "max_open_slots" in _OBSOLETE_PARAM_KEYS)
check("...es a motor tenyleg NEM parameterkent olvassa (trading config)",
      "max_open_slots" not in _wpr and "max_open_slots" not in _view)

# ══ 5. A VALODI ablak: a mentett JSON elavult kulcsa sem jelenik meg ══════
try:
    import tkinter as tk
    _p = tk.Tk(); _p.destroy()
    TK_OK = True
except Exception as e:
    TK_OK = False
    print(f"KIHAGYVA (5. blokk): nincs hasznalhato tkinter ({type(e).__name__}: {e})")

if TK_OK:
    from dashboard import theme as _t
    from dashboard.instrument_dialog import InstrumentParamsDialog

    def dialog_keys(symbol, strategy):
        cfg = base_cfg()
        root = tk.Tk()
        root.withdraw()
        _t._FONTS.clear()
        f = _t.fonts()
        try:
            d = InstrumentParamsDialog(root, symbol, cfg,
                                       get_strategy_by_name(strategy),
                                       f["header"], f["small"], lambda: None,
                                       root_cfg=cfg)
            root.update_idletasks()
            return list(d._keys)
        finally:
            root.destroy()

    ml_keys = dialog_keys("GOLD", "ml_ai")
    _leak2 = sorted(k for k in WPR_ONLY if k in ml_keys)
    check("az ml_ai ablakaban nincs wpr_sma-parameter", not _leak2, str(_leak2))
    check("...de a SAJAT + a kozos vegrehajtasi kulcsok ott vannak",
          all(k in ml_keys for k in ("ml_warmup_bars", "sl_atr_mult",
                                     "atr_period", "max_spread_atr_ratio")),
          str(ml_keys))

    wpr_keys = dialog_keys("GOLD", "wpr_sma")
    check("a wpr_sma ablakabol kikerult az elavult max_open_slots",
          "max_open_slots" not in wpr_keys)
    check("...de a valodi parameterei megmaradtak",
          all(k in wpr_keys for k in ("sma_period", "wpr_m1_trigger",
                                      "sl_atr_mult", "atr_period")),
          str(wpr_keys))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

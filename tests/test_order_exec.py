"""A #2 (deviation), #3 (filling mode) es #4 (stops_level + ar-racs) tesztje."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import MetaTrader5 as mt5
from core import order_exec as ox

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


class Info:
    def __init__(self, filling_mode=3, spread=12, point=0.00001, digits=5,
                 trade_tick_size=0.00001, trade_stops_level=0):
        self.filling_mode = filling_mode
        self.spread = spread
        self.point = point
        self.digits = digits
        self.trade_tick_size = trade_tick_size
        self.trade_stops_level = trade_stops_level


# ── #3  Kitoltesi mod a szimbolum BITMASZKJABOL ────────────────────────────
ox._filling_cache.clear()
check("maszk 3 (FOK|IOC) -> IOC",
      ox.filling_mode("A", Info(filling_mode=3)) == mt5.ORDER_FILLING_IOC)
ox._filling_cache.clear()
check("maszk 1 (csak FOK) -> FOK  <- ezen bukott eddig MINDEN kotes",
      ox.filling_mode("B", Info(filling_mode=1)) == mt5.ORDER_FILLING_FOK)
ox._filling_cache.clear()
check("maszk 2 (csak IOC) -> IOC",
      ox.filling_mode("C", Info(filling_mode=2)) == mt5.ORDER_FILLING_IOC)
ox._filling_cache.clear()
check("maszk 0 (se FOK se IOC) -> RETURN",
      ox.filling_mode("D", Info(filling_mode=0)) == mt5.ORDER_FILLING_RETURN)
ox._filling_cache.clear()
check("nincs symbol_info -> a regi IOC (viselkedes valtozatlan)",
      ox.filling_mode("E", None) == mt5.ORDER_FILLING_IOC)

# ── #2  Csuszas-tures ──────────────────────────────────────────────────────
cfg = {"trading": {"deviation_points": 10}, "pairs": {"Ger40": {"deviation_points": 40}}}
check("alap 10, spread 12 -> 12 (a spread nyer)",
      ox.deviation_points("EURUSD", cfg, Info(spread=12)) == 12, )
check("alap 10, spread 3 -> 10 (az alap nyer)",
      ox.deviation_points("EURUSD", cfg, Info(spread=3)) == 10)
check("per-par felulras (Ger40=40) ervenyesul",
      ox.deviation_points("Ger40", cfg, Info(spread=5)) == 40)
check("config nelkul is van ertelmes ertek (>=1)",
      ox.deviation_points("X", None, Info(spread=0)) >= 1)

# ── #4a  Ar a szimbolum RACSARA ────────────────────────────────────────────
idx = Info(point=0.01, digits=2, trade_tick_size=0.01)
check("index (digits=2, tick=0.01): 18234.5678 -> 18234.57",
      ox.normalize_price(18234.5678, idx) == 18234.57,
      str(ox.normalize_price(18234.5678, idx)))
odd = Info(point=0.01, digits=2, trade_tick_size=0.05)
v = ox.normalize_price(18234.5678, odd)
check("0.05-os tick: 18234.5678 -> 18234.55 (0.05 tobbszorose)",
      abs(v - 18234.55) < 1e-9 and abs((v / 0.05) - round(v / 0.05)) < 1e-9, str(v))
check("nincs info -> a regi 5 tizedes",
      ox.normalize_price(1.234567891, None) == 1.23457)

# ── #4b  Minimum stop-tavolsag: SL tagitas, R:R valtozatlan ────────────────
# EURUSD-szeru: point=0.00001, pip=0.0001, stops_level=50 pont, spread=0 -> 5 pip
info = Info(point=0.00001, digits=5, trade_tick_size=0.00001, trade_stops_level=50,
            spread=0)
pip = 0.0001

sl, tp, widened = ox.enforce_min_sl_points(3.0, 6.0, info, pip)   # 3 pip < 5 pip minimum
check("tul szuk SL -> tagitva", widened)
check("az uj SL a minimum folott (5.1 pip)", abs(sl - 5.1) < 1e-9, f"sl={sl}")
check("az R:R valtozatlan (2.0)", abs((tp / sl) - 2.0) < 1e-9, f"R:R={tp/sl}")

sl2, tp2, w2 = ox.enforce_min_sl_points(20.0, 40.0, info, pip)    # boven a minimum folott
check("eleg tag SL -> valtozatlan", (not w2) and sl2 == 20.0 and tp2 == 40.0)

sl3, tp3, w3 = ox.enforce_min_sl_points(3.0, 6.0,
                                      Info(trade_stops_level=0, spread=0), pip)
check("stops_level=0 ES spread=0 -> valtozatlan", not w3)

# ── A SPREAD is beleszamit (a broker a MASIK oldalon meri a stop-tavot) ────
# A valos UK100-eset: stops_level 150 pont (=1.5), spread 141 pont (=1.41),
# point 0.01, point_size 1.0. A 1.933-as SL-tav LATSZOLAG eleg (>1.5), de a broker
# 1.933-1.41 = 0.523-at mer -> 10016. Az uj minimum: 1.5+1.41+0.01 = 2.92.
uk = Info(point=0.01, digits=2, trade_tick_size=0.01, trade_stops_level=150,
          spread=141)
sl_uk, tp_uk, w_uk = ox.enforce_min_sl_points(1.933, 3.867, uk, 1.0)
check("UK100 valos eset: a spread miatt TAGITANI kell (regen nem tette)", w_uk)
check("...az uj minimum = stops_level + spread + 1 pont = 2.92",
      abs(sl_uk - 2.92) < 1e-9, f"sl={sl_uk}")
check("...a broker altal MERT tav (SL - spread) mar a minimum folott",
      (sl_uk - 1.41) >= 1.5, f"{sl_uk-1.41:.3f} >= 1.5")
check("...az R:R valtozatlan (a BEMENO aranyhoz kepest)",
      abs(tp_uk / sl_uk - 3.867 / 1.933) < 1e-12, f"R:R={tp_uk/sl_uk:.6f}")

# stops_level=0 (dinamikus szint, pl. GOLD), de van spread -> a spread a padlo
g = Info(point=0.01, digits=2, trade_tick_size=0.01, trade_stops_level=0, spread=50)
sl_g, _, w_g = ox.enforce_min_sl_points(0.2, 0.4, g, 1.0)
check("stops_level=0 de spread>0 -> a spread a also korlat", w_g and sl_g > 0.5,
      f"sl={sl_g}")

# ── #4c  A kockazati keret NEM no a tagitastol ─────────────────────────────
from core.risk_manager import calc_lot
pair = {"pv1_point": 8.79, "min_lot": 0.01, "lot_step": 0.01}
tcfg = {"account_risk_pct": 0.01, "max_open_slots": 4}
lot_szuk = calc_lot(10000, 3.0, pair, tcfg, 4)
lot_tag = calc_lot(10000, 5.1, pair, tcfg, 4)
risk_szuk = lot_szuk * 3.0 * pair["pv1_point"]
risk_tag = lot_tag * 5.1 * pair["pv1_point"]
check("a tagitott SL kisebb lotot ad", lot_tag < lot_szuk, f"{lot_szuk} -> {lot_tag}")
check("a kockazat ($) NEM no", risk_tag <= risk_szuk + 1e-9,
      f"{risk_szuk:.2f}$ -> {risk_tag:.2f}$")

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

"""A BE-küszöb R-ben (`breakeven_r`) — és a három hívó KÖZÖS képlete.

⚠ A LELET (2026-09-08). A breakeven küszöbe a CÉLÁR százaléka volt:

    be_trigger = open + (tp − open) * breakeven_pct

Amíg a célár 2–3 R körül mozgott, ez működött. Amikor a `tp_rr_ratio`
tartományt felnyitottuk (0,5–3,0 → 2,0–15,0), az optimalizáló 16/16 páron
HOSSZÚ célárat választott (9,5–15,0 R) — és a 0,5-ös szorzóval a BE **7,25
R-re** került, amit gyakorlatilag egy kötés sem ér el. A trailing pedig a
`risk_free`-hez van kötve, tehát AZ IS meghalt. A hosszú célár így NÉMÁN
kikapcsolta a teljes kimenet-kezelést.

Mérve (14 pár, mintán kívül): BE ~7 R → −0,3198 R/kötés; BE 1 R → −0,2234.
A csatolás ára **+0,166 R/kötés**.

⚠ ÉS AMIÉRT KÖZÖS FÜGGVÉNY LETT: a képlet HÁROM helyen élt — a backtestben és
KÉT élő ágban, amelyek a kódban „IKERPÁR"-ként voltak megjelölve („HA ITT
VÁLTOZTATSZ, azt is módosítsd"). Egy ilyen szerkezetből előbb-utóbb néma
él↔backteszt eltérés lesz. Ez a teszt azt is őrzi, hogy egy forrás maradjon.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog

applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from core import risk_reduction as rr

# ══ 1. A tiszta függvény ═══════════════════════════════════════════════════
BE = rr.breakeven_trigger

check("van breakeven_trigger", callable(BE))

# be_pct-es (RÉGI) ág: TP 2 R-nél, be_pct 0,5 → a küszöb 1 R-nél
# open=100, sl_dist=1 (tehat 1 R = 1,0 ar), tp=102 (2 R)
check("régi ág (be_pct): BUY küszöb a TP felénél",
      abs(BE(100.0, 102.0, 1.0, True, 0.5, 0.0) - 101.0) < 1e-9,
      str(BE(100.0, 102.0, 1.0, True, 0.5, 0.0)))
check("régi ág (be_pct): SELL tükrözve",
      abs(BE(100.0, 98.0, 1.0, False, 0.5, 0.0) - 99.0) < 1e-9,
      str(BE(100.0, 98.0, 1.0, False, 0.5, 0.0)))

# ⚠ A LELET MAGA: hosszú célárnál a régi ág elszáll
_hosszu = BE(100.0, 115.0, 1.0, True, 0.5, 0.0)      # TP 15 R
check("⚠ a régi ág HOSSZÚ célárnál 7,5 R-re teszi a BE-t (ez volt a hiba)",
      abs(_hosszu - 107.5) < 1e-9, f"{_hosszu} (= 7,5 R)")

# ÚJ ág: be_r ugyanezen a hosszú célárnál 1 R-nél tartja
_uj = BE(100.0, 115.0, 1.0, True, 0.5, 1.0)
check("⚠ breakeven_r=1 → a küszöb 1 R, a CÉLÁRTÓL FÜGGETLENÜL",
      abs(_uj - 101.0) < 1e-9, f"{_uj}")
check("breakeven_r SELL-en is tükrözve",
      abs(BE(100.0, 85.0, 1.0, False, 0.5, 1.0) - 99.0) < 1e-9)
check("breakeven_r skálázódik a stop-távolsággal (sl_dist=2 → 2 ár)",
      abs(BE(100.0, 115.0, 2.0, True, 0.5, 1.0) - 102.0) < 1e-9)

# Visszafelé kompatibilitás
check("breakeven_r=0 → a RÉGI képlet (bitazonos)",
      BE(100.0, 102.0, 1.0, True, 0.5, 0.0) == BE(100.0, 102.0, 1.0, True, 0.5, 0))
check("be_pct=0 és be_r=0 → NINCS breakeven (None)",
      BE(100.0, 102.0, 1.0, True, 0.0, 0.0) is None)
check("risky → azonnali BE a nyitóáron (minden mást felülír)",
      BE(100.0, 115.0, 1.0, True, 0.5, 1.0, True) == 100.0)
check("hibás (nem szám) érték sem omlik össze",
      BE(100.0, 102.0, 1.0, True, "x", None) is None)

# ══ 1b. NINCS NÉMA MÓDVÁLTÁS (2026-09-08, független code review) ═══════════
# ⚠ EZ A SZERZŐDÉS MEGVÁLTOZOTT. Korábban a `be_r>0` + ismeretlen stop-táv
# VISSZAESETT a `be_pct`-re: aki R-ben kérte a küszöböt, célár-arányosat kapott
# — épp az a csatolás, aminek a felszámolására a `be_r` készült. Egy néma
# módváltás rosszabb, mint a hiányzó breakeven: a stop MÁS szabály szerint
# mozdul, mint amit a felhasználó beállított.
check("⚠ be_r>0 + ISMERETLEN stop-táv → None (NEM esik vissza a be_pct-re)",
      BE(100.0, 102.0, 0.0, True, 0.5, 1.0) is None)
check("...és None stop-távval is", BE(100.0, 102.0, None, True, 0.5, 1.0) is None)

# ⚠ A MÁSIK NÉMA ÁG: célár nélkül a `be_pct` képlet nem hibázik, hanem HAZUDIK.
# BUY-nál `open + (0 − open) × 0.5 = open/2`, azaz a küszöb a belépő FELE — ami
# az ár ALATT van, tehát AZONNAL elsül. Nem elmaradó BE: HAMIS, azonnali BE.
# És nem elméleti: a ráépített lábakat a motor `tp=0.0`-val nyitja.
_hamis = 100.0 + (0.0 - 100.0) * 0.5
check("⚠ a RÉGI képlet célár nélkül a belépő FELÉRE tette a küszöböt",
      abs(_hamis - 50.0) < 1e-9, f"{_hamis} (az ár alatt → azonnal elsül)")
check("⚠ tp=0 → None (nincs breakeven, nem hamis azonnali BE)",
      BE(100.0, 0.0, 1.0, True, 0.5, 0.0) is None)
check("...és tp=None → None", BE(100.0, None, 1.0, True, 0.5, 0.0) is None)
check("SELL-en is", BE(100.0, 0.0, 1.0, False, 0.5, 0.0) is None)
check("⚠ DE be_r-rel célár NÉLKÜL is van breakeven (ez a lényege)",
      abs(BE(100.0, 0.0, 1.0, True, 0.0, 1.0) - 101.0) < 1e-9,
      str(BE(100.0, 0.0, 1.0, True, 0.0, 1.0)))
check("...és a risky továbbra is mindent felülír (célár nélkül is)",
      BE(100.0, 0.0, 0.0, True, 0.5, 0.0, True) == 100.0)

# A `None` NEM lehet néma: a modul futásonként egyszer naplóz (szoros ciklus).
import logging as _lg


class _Cap(_lg.Handler):
    def __init__(self):
        super().__init__(level=_lg.DEBUG)
        self.recs = []

    def emit(self, r):
        self.recs.append(r)


rr._warned.clear()
_cap = _Cap()
_lg.getLogger(rr.__name__).addHandler(_cap)
try:
    BE(100.0, 102.0, 0.0, True, 0.5, 1.0)      # be_r, nincs stop-táv
    BE(100.0, 0.0, 1.0, True, 0.5, 0.0)        # be_pct, nincs célár
    BE(100.0, 102.0, 0.0, True, 0.5, 1.0)      # ISMÉTLÉS → nem szólal meg újra
finally:
    _lg.getLogger(rr.__name__).removeHandler(_cap)
check("⚠ a None NEM néma: mindkét okról szól", len(_cap.recs) == 2,
      f"{len(_cap.recs)} rekord")
check("...de okonként CSAK EGYSZER (a backteszt szoros ciklusban hívja)",
      len({r.msg for r in _cap.recs}) == len(_cap.recs))

# ══ 2. Az alapérték visszafelé kompatibilis ════════════════════════════════
_d = rr.default_config()
check("a default_config ismeri a breakeven_r-t", "breakeven_r" in _d)
check("⚠ az alapértéke 0.0 → a meglévő párok viselkedése VÁLTOZATLAN",
      _d["breakeven_r"] == 0.0, str(_d.get("breakeven_r")))

# A rögzített szerződést NEM bővítettük (három teszt egyenlőséget vár rá)
check("⚠ a breakeven_r NINCS a BE_TRAIL_KEYS-ben (rögzített szerződés)",
      "breakeven_r" not in rr.BE_TRAIL_KEYS, str(rr.BE_TRAIL_KEYS))
from core import rr_state as rrs
check("...de per-pár MENTHETŐ (benne van a kalibrációs kulcsokban)",
      "breakeven_r" in rrs._CALIB_KEYS)

# ══ 3. A BACKTEST tényleg ezt használja ════════════════════════════════════
from trading.backtest import Trade, _update_stops


def _trade(direction="BUY", open_price=100.0, tp=115.0, sl_points=100.0,
           point_size=0.01):
    return Trade(symbol="X", direction=direction, open_time=None,
                 open_price=open_price,
                 sl=open_price - 1.0 if direction == "BUY" else open_price + 1.0,
                 tp=tp, lot=0.1, point_size=point_size, pv1_point=1.0,
                 sl_points=sl_points, entry_atr=0.5)


# 1 R = sl_points * point_size = 100 * 0.01 = 1,0 ár. TP 15 R (115).
RR_REGI = {"breakeven_pct": 0.5, "breakeven_r": 0.0,
           "trail_activation_atr": 0.5, "trail_distance_atr": 0.4}
RR_UJ = {**RR_REGI, "breakeven_r": 1.0}

t = _trade()
_update_stops(t, high=102.0, low=99.5, rr=RR_REGI, point_size=0.01, risky=False)
check("⚠ backtest, RÉGI mód: 2 R profit NEM elég a BE-hez (a küszöb 7,5 R)",
      not t.risk_free)

t = _trade()
_update_stops(t, high=102.0, low=99.5, rr=RR_UJ, point_size=0.01, risky=False)
check("backtest, breakeven_r=1: 2 R profitnál MEGVAN a BE", t.risk_free)
# ⚠ A stop itt MÁR 100 FÖLÖTT van, mert a BE után UGYANEBBEN a hívásban a
# trailing is lefut (102 − 0,4×ATR). Ez helyes; a BE-t az `risk_free` jelzi.
check("...és a stop legalább a nyitóárig jött (BE-padló)", t.sl >= 100.0, str(t.sl))

# A TISZTA BE (trailing nélkül): ismeretlen ATR → a trailing kimarad, a BE nem
_t0 = _trade()
_t0.entry_atr = 0.0
_update_stops(_t0, high=102.0, low=99.5, rr=RR_UJ, point_size=0.01, risky=False)
check("...trailing nélkül a stop PONTOSAN a nyitóáron áll",
      _t0.risk_free and abs(_t0.sl - 100.0) < 1e-9, str(_t0.sl))

t = _trade()
_update_stops(t, high=100.5, low=99.5, rr=RR_UJ, point_size=0.01, risky=False)
check("breakeven_r=1: 0,5 R profit MÉG NEM elég", not t.risk_free)

t = _trade(direction="SELL", open_price=100.0, tp=85.0)
_update_stops(t, high=100.5, low=98.0, rr=RR_UJ, point_size=0.01, risky=False)
check("backtest, SELL + breakeven_r: 2 R profitnál megvan a BE", t.risk_free)

# Visszafelé kompatibilitás a MOTORBAN: rövid célárnál a két mód egyezik
ta, tb = _trade(tp=102.0), _trade(tp=102.0)
_update_stops(ta, high=101.2, low=99.5, rr=RR_REGI, point_size=0.01, risky=False)
_update_stops(tb, high=101.2, low=99.5, rr={**RR_REGI, "breakeven_r": 0.0},
              point_size=0.01, risky=False)
check("⚠ breakeven_r=0 mellett a motor viselkedése BITAZONOS",
      (ta.risk_free, ta.sl) == (tb.risk_free, tb.sl))

# ══ 4. Egy forrás: a három hívó ugyanazt a függvényt hívja ════════════════
_bt = (ROOT / "trading" / "backtest.py").read_text(encoding="utf-8")
_lt = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
check("a backtest a közös breakeven_trigger-t hívja",
      "breakeven_trigger(" in _bt)
check("⚠ MINDKÉT élő ág is (a korábbi ikerpár)",
      _lt.count("breakeven_trigger(") >= 2, f"{_lt.count('breakeven_trigger(')} hívás")
check("⚠ a régi, kézzel írt célár-arányos képlet SEHOL nem maradt",
      "(pos.tp - pos.price_open) * be_pct" not in _lt
      and "(trade.tp - trade.open_price) * be_pct" not in _bt)

print()
n, m = sum(results), len(results)
print(f"{n}/{m} teszt PASS")
sys.exit(0 if n == m else 1)

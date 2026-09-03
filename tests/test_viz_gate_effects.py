"""A chart annyi belépőt mutasson, amennyit a motor megköt — se többet, se kevesebbet.

⚠ A LELET (2026-08-25, a felhasználó vette észre): „jelez az MT5, viszont nincs
vonalam." A Ger40 MINDEN kapuja `none` hatáson állt, tehát a motor egyetlen
jelzést sem blokkolt és sorra küldte a riasztásokat — a charton viszont nem
jelent meg jelölő. Mérve aznap: **12 riasztás, 5 jelölő**.

AZ OK. A kapuknak HÁROM hatásuk lehet (`core.gates`):

    block   — nincs belépő
    reduce  — belép, de kisebb mérettel
    none    — a kapu nem szól bele

A motor ezt v1.97.0 óta tiszteletben tartja. A VIZ viszont a TF-együttállást és
a spread-kaput **kemény tiltásként** alkalmazta, hatástól függetlenül — így a
chart kevesebbet mutatott, mint a valóság.

⚠ A `reduce` ugyanígy hibás volna: ott a motor BELÉP (fele mérettel), tehát a
jelölőnek meg KELL jelennie.

Ugyanaz a konvenció, ami a sáv-állapotnál már ki volt mondva:
*„a `none` hatású kapu SOSEM zár, tehát nem is villoghat"* (`visual.BarState`).

⚠ ÉS AMIÉRT EZ NEM KOZMETIKA: a chart a felhasználó egyetlen ablaka arra, mit
csinál a motor. Ha kevesebbet mutat, a riasztás jelölő nélkül marad, és a
felhasználó azt hiszi, a program hibás — pedig épp jól működik.
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


from core import gates as gt
from strategy.base import MarketData

# ── 1. A seam alapértéke visszafelé kompatibilis ───────────────────────
md = MarketData(symbol="X", params={})
check("üres hatás-térkép → MINDEN kapu blokkol (a régi viselkedés)",
      md.gate_blocks("spread") and md.gate_blocks("tf_align"))

md.gate_effects = {"spread": gt.EFFECT_NONE, "tf_align": gt.EFFECT_REDUCE}
check("a `none` hatású kapu NEM blokkol", not md.gate_blocks("spread"))
check("⚠ a `reduce` sem blokkol (a motor belép, csak kisebb mérettel)",
      not md.gate_blocks("tf_align"))
md.gate_effects = {"spread": gt.EFFECT_BLOCK}
check("a `block` viszont igen", md.gate_blocks("spread"))
check("az ismeretlen kulcs is blokkol (óvatos alapérték)",
      md.gate_blocks("nincs_ilyen_kapu"))

# ── 2. A motor útja: a TF-kapu csak `block` hatásnál szűr ──────────────
_lt = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
check("a viz lekéri a kapuk HATÁSÁT", "effects_for(" in _lt)
check("...és átadja a stratégiának", "md.gate_effects" in _lt)
check("⚠ a TF-kapu csak `block`-nál épül fel",
      "_tf_eff != _gt.EFFECT_BLOCK" in _lt)

_ws = (ROOT / "strategy" / "wpr_sma.py").read_text(encoding="utf-8")
# v3.28.0: a kérdés SÁV-TUDATOS lett — nem „blokkol-e ez a kapu",
# hanem „blokkol-e EZEN a mérésen" (`gate_blocks_at`).
check("a spread-kapu is hatás-tudatos",
      "gate_blocks_at(" in _ws and "spread" in _ws)

# ── 3. VALÓDI adaton: a `none` hatás TÖBB jelölőt ad, mint a `block` ───
# ⚠ Ez a mérés a lelet lényege. Ha a két szám egyenlő, a hatás nem érvényesül,
# és a hiba visszatért — akkor is, ha a fenti szerkezeti ellenőrzések mennek.
try:
    from strategy import get_strategy_by_name
    from strategy.settings import load_config, config_for_strategy
    from core.execution_params import load_execution_params
    from trading.backtest import load_data
    from trading.live_trader import default_params

    cfg = load_config("config.json")
    st = get_strategy_by_name("wpr_sma")
    cs = config_for_strategy(cfg, "wpr_sma")
    sym = next((s for s in ("Ger40", "UsaTec", "UsaInd")
                if s in (cfg.get("pairs") or {})), None)
    d15, d1 = load_data(sym) if sym else (None, None)
except Exception as ex:
    d15 = None
    print(f"      (nincs adat a méréshez: {ex})")

if d15 is not None and d1 is not None and len(d15) > 4000:
    pc = cfg["pairs"][sym]
    prm = {**default_params(st, cs), **load_execution_params(sym, cfg),
           "point_size": pc.get("point_size", 0.0001),
           "backtest_spread_points": pc.get("backtest_spread_points", 1.5)}
    bars = {"M15": d15.iloc[-4000:], "M1": d1.iloc[-30000:]}

    def rekordok(effects, gate):
        r = []
        m = MarketData(symbol=sym, params=prm, bars=bars, show_signals=True,
                       on_entry_record=r.append)
        m.gate_effects = effects
        m.entry_gate = gate
        st.visual_objects(m)
        return len(r)

    # Mindent elutasító kapu — így a hatása egyértelműen mérhető.
    _mindig_nem = lambda t, price, d: False          # noqa: E731

    blokkol = rekordok({"tf_align": gt.EFFECT_BLOCK, "spread": gt.EFFECT_BLOCK},
                       _mindig_nem)
    # `none` hatásnál a KERET nem is építi meg a kaput (lásd live_trader), ezért
    # itt `None`-t adunk — pontosan azt modellezve, ami élesben történik.
    nem_szol = rekordok({"tf_align": gt.EFFECT_NONE, "spread": gt.EFFECT_NONE},
                        None)
    check("⚠ a `none` hatás TÖBB jelölőt ad, mint a `block`",
          nem_szol > blokkol, f"none={nem_szol} vs block={blokkol}")
    check("...és a blokkoló kapu tényleg elnyeli a jelölőket",
          blokkol == 0, f"{blokkol} maradt")

    # A spread-kapu külön: kapu nélkül, csak a hatást váltva.
    sp_block = rekordok({"spread": gt.EFFECT_BLOCK}, None)
    sp_none = rekordok({"spread": gt.EFFECT_NONE}, None)
    check("a spread-kapu `none`-nál nem szűr",
          sp_none >= sp_block, f"none={sp_none} vs block={sp_block}")

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

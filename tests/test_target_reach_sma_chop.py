"""
Celar-eleres + SMA-oldalazas kapu (v3.105.0) — es a keret, amire epulnek.

MIERT: a felhasznalo keresere ket, MINDEN strategiara kozos kapu:
  * target_reach — „jart-e az ar a celar 60-80%-an az utolso N gyertyaban?"
  * sma_chop     — „atutotte-e az ar az SMA-t az utolso N gyertyaban?"

A keret harom helyen bovult, es mindharmat itt orizzuk:
  1. `GateCtx.bars` — lezart OHLC-gyertyak; backtestben/vizben `bars_from_m1`.
     ⚠ Az IDOPONT-KONVENCIO a lenyeg: a jelzo M1-gyertya BENNE, a kovetkezo
     NINCS (look-ahead), nagyobb idosikon a felkesz csoport NINCS.
  2. A PORTFOLIO a terv-fazisu behelyezett kapukat is kiertekeli (eddig NEM —
     keret-lyuk volt: elesben blokkolt volna, a portfolioban nem).
  3. A VIZ (`MarketData.plugged_blocks`) a behelyezett kapukat is kerdezi.

A nem-ures bizonyitek (`vacuous-parity-tests` lecke): block hatassal a kotesek
szama TENYLEG csokken a `run_pair`-ben ES a portfolioban.
"""

import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import core.applog as _applog
_applog.harden_console()

import numpy as np                                  # noqa: E402
import pandas as pd                                 # noqa: E402

from core import gates as g                         # noqa: E402
from gates import target_reach as tr                # noqa: E402
from gates import sma_chop as sc                    # noqa: E402

_results = []
_fail = []


def check(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name + (f"  [{detail}]" if detail else ""))
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)


# ══ 1. Tiszta fuggvenyek ═══════════════════════════════════════════════════
print("== 1. check / crosses ==")
f, frac = tr.check("BUY", 100.0, 10.0, [101, 108, 103], [99, 98, 97], 0.7)
check("BUY: a csucs 8/10 -> atmegy (0,7 kell)", not f and abs(frac - 0.8) < 1e-9, frac)
f, frac = tr.check("BUY", 100.0, 10.0, [101, 105, 103], [99, 98, 97], 0.7)
check("BUY: a csucs 5/10 -> bukik", f and abs(frac - 0.5) < 1e-9, frac)
f, frac = tr.check("SELL", 100.0, 10.0, [101, 102], [95, 92], 0.7)
check("SELL tukorkep: a melypont 8/10 -> atmegy", not f and abs(frac - 0.8) < 1e-9)
check("rossz bemenet -> fail-open", tr.check("NONE", 1, 1, [1], [1], 0.7) == (False, None))
check("0 celar -> fail-open", tr.check("BUY", 1, 0, [1], [1], 0.7) == (False, None))

up = np.linspace(100, 120, 80)                       # tiszta trend: 0 atutes
check("trendben 0 atutes", sc.crosses(up, 50, 20) == 0, sc.crosses(up, 50, 20))
zig = np.r_[np.full(60, 100.0), np.tile([101.0, 99.0], 10)]   # SMA ~100 korul cikazik
check("cikazasban sok atutes", (sc.crosses(zig, 50, 20) or 0) >= 10, sc.crosses(zig, 50, 20))
check("keves adat -> None (fail-open)", sc.crosses(up[:30], 50, 20) is None)
tap = np.r_[np.full(50, 100.0), [101, 102, 100.9, 103, 104]]
check("az SMA-n zaro gyertya nem szamit ket atutesnek",
      sc.crosses(np.r_[np.linspace(90, 110, 55)], 50, 5) == 0)

# ══ 2. bars_from_m1 — az idopont-konvencio ═════════════════════════════════
print("== 2. bars_from_m1 ==")
idx = pd.date_range("2026-01-05 10:00", periods=120, freq="1min", tz="UTC")
m1 = pd.DataFrame({"open": np.arange(120.0), "high": np.arange(120.0) + 0.5,
                   "low": np.arange(120.0) - 0.5, "close": np.arange(120.0)}, index=idx)
t = idx[44]                                          # a jelzo gyertya: 10:44
b = g.bars_from_m1(m1, t)(1, 5)
check("M1: a jelzo gyertya BENNE van (utolso = 10:44)", b.index[-1] == t, b.index[-1])
check("M1: a kovetkezo NINCS benne (nincs look-ahead)", (b.index <= t).all())
check("M1: pontosan n gyertya", len(b) == 5)
b15 = g.bars_from_m1(m1, idx[43])(15, 3)            # 10:43 zarasa: a 10:30-as meg felkesz
check("M15: csak LEZART csoport (10:43-kor a 10:30-as meg felkesz -> nincs)",
      b15.index[-1] == pd.Timestamp("2026-01-05 10:15", tz="UTC"), list(b15.index))
b15c = g.bars_from_m1(m1, t)(15, 3)                 # 10:44 zarasa = 10:45: a 10:30-as lezart
check("M15: a csoport UTOLSO M1-gyertyajanak zarasakor mar lezart",
      b15c.index[-1] == pd.Timestamp("2026-01-05 10:30", tz="UTC"), list(b15c.index))
b15b = g.bars_from_m1(m1, idx[44 + 15])(15, 3)      # 10:59 -> a 10:45-os lezart
check("M15: 10:59-kor a 10:45-os lezart", b15b.index[-1] ==
      pd.Timestamp("2026-01-05 10:45", tz="UTC"), list(b15b.index))
check("M15: a high a csoport maximuma", float(b15.iloc[-1]["high"]) == float(m1.loc[
      "2026-01-05 10:15":"2026-01-05 10:29", "high"].max()))
check("nincs adat -> None", g.bars_from_m1(None, t)(1, 5) is None)

# ══ 3. Bejelentkezes a keretbe ═════════════════════════════════════════════
print("== 3. registry ==")
check("target_reach: TERV-fazisu behelyezett kapu",
      "target_reach" in g.plugged_keys(g.PHASE_PLAN))
check("sma_chop: JELZES-fazisu behelyezett kapu",
      "sma_chop" in g.plugged_keys(g.PHASE_SIGNAL))
check("alapbol NONE hatas (egy uj kapu nem kezdhet nemán szurni)",
      g.default_effect_of("target_reach") == "none" and
      g.default_effect_of("sma_chop") == "none")
_c = {"gates": {"target_reach": {"wpr_sma": "block"}},
      "dashboard": {"gate_order": ["spread"]}}
check("ha a gate_order-bol KIMARAD, a mester-kapcsolo KI (hatas none)",
      g.effect_for(_c, "X", "wpr_sma", "target_reach") == "none")
_c["dashboard"] = {"gate_order": ["target_reach"]}
check("gate_order-rel a beallitott hatas el",
      g.effect_for(_c, "X", "wpr_sma", "target_reach") == "block")

# measure a GateCtx-en, stub-gyertyakkal
_stub = pd.DataFrame({"open": [100.0] * 22, "high": [101.0] * 22,
                      "low": [99.0] * 22, "close": [100.0] * 22})
ctx = g.GateCtx(symbol="X", signal="BUY", pair_cfg={"point_size": 0.01},
                sl_points=500, tp_points=1000, bars=lambda tf, n: _stub)
check("measure: 1,0 ar elmozdulas vs 10,0 celar -> bukik",
      g.measure("target_reach", ctx)[0] is True)
ctx2 = g.GateCtx(symbol="X", signal="BUY", pair_cfg={"point_size": 0.01},
                 sl_points=50, tp_points=100, bars=lambda tf, n: _stub)
check("measure: 1,0 vs 1,0 celar -> atmegy", g.measure("target_reach", ctx2)[0] is False)
ctx3 = g.GateCtx(symbol="X", signal="BUY", pair_cfg={"point_size": 0.01},
                 sl_points=500, tp_points=1000)
check("gyertya nelkul fail-open", g.measure("target_reach", ctx3)[0] is False)
check("block_log konkret szamot mond", "%" in g.block_log("target_reach", ctx))

# ══ 4. Viz: MarketData.plugged_blocks ══════════════════════════════════════
print("== 4. viz ==")
from strategy.base import MarketData                 # noqa: E402
md = MarketData(symbol="X", params={}, bars={"M1": m1.assign(
    high=m1["close"], low=m1["close"])})
md.gate_effects = {"target_reach": "block"}
check("gate_cfg nelkul nem szur (regi viselkedes)",
      md.plugged_blocks("plan", t, "BUY", 50, 5000) is False)
md.gate_cfg = {"dashboard": {"gate_order": ["target_reach"]}}
md.pair_cfg = {"point_size": 0.01}
check("block + bukott meres -> a jelolo ELMARAD",
      md.plugged_blocks("plan", t, "BUY", 50, 5000) is True)
md.gate_effects = {"target_reach": "none"}
check("none hatas -> a jelolo MEGJELENIK",
      md.plugged_blocks("plan", t, "BUY", 50, 5000) is False)
md.gate_effects = {"target_reach": "block"}
md.exec_gates = False
check("nyers jelzes modban (exec_gates=False) nem szur",
      md.plugged_blocks("plan", t, "BUY", 50, 5000) is False)

# ══ 5. Motor: NEM ures — run_pair + portfolio ══════════════════════════════
print("== 5. motor (valodi adat) ==")
_m1p = ROOT / "data" / "m1" / "Ger40.parquet"
if not _m1p.exists():
    print("  (kihagyva: nincs Ger40 adat)")
else:
    from strategy.settings import config_for_strategy, default_params
    from strategy import get_strategy_by_name
    from trading.live_trader import strategy_params
    from trading.backtest import run_pair, run_portfolio_backtest
    raw = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

    def _v(eff):
        c = copy.deepcopy(raw)
        c.setdefault("gates", {})["target_reach"] = {"wpr_sma": eff}
        go = c.setdefault("dashboard", {}).setdefault("gate_order", [])
        if "target_reach" not in go:
            go.append("target_reach")
        return c

    st = get_strategy_by_name("wpr_sma")
    M15 = pd.read_parquet(ROOT / "data" / "m15" / "Ger40.parquet")
    M1 = pd.read_parquet(_m1p)
    e = pd.Timestamp("2026-09-24", tz=M1.index.tz)
    M15 = M15[(M15.index >= e - pd.Timedelta(days=200)) & (M15.index < e)]
    M1 = M1[(M1.index >= e - pd.Timedelta(days=40)) & (M1.index < e)]
    n = {}
    for eff in ("none", "block"):
        cs = config_for_strategy(_v(eff), "wpr_sma")
        p = strategy_params("Ger40", "wpr_sma", cs, fallback=default_params(st, cs))
        r = run_pair("Ger40", M15, M1, {**p, "symbol": "Ger40"}, cs["pairs"]["Ger40"],
                     cs["trading"], 1000.0, strategy=st, cfg=cs, exec_gates=True,
                     test_start=str((e - pd.Timedelta(days=30)).date()))
        n[eff] = len(r.closed)
    check("run_pair: block mellett KEVESEBB kotes (nem ures)",
          n["block"] < n["none"] and n["none"] > 0, n)

    pn = {}
    for eff in ("none", "block"):
        pr = run_portfolio_backtest(
            _v(eff), [], str((e - pd.Timedelta(days=30)).date()), str(e.date()),
            initial_balance=1000.0, exec_gates=True, cells=[("Ger40", "wpr_sma")])
        pn[eff] = len(pr.get("trades") or [])
    check("PORTFOLIO: a terv-fazisu behelyezett kapu IS dont (keret-lyuk bezarva)",
          pn["block"] < pn["none"] and pn["none"] > 0, pn)

# ══ 6. Feliratok + leiras ══════════════════════════════════════════════════
print("== 6. i18n + docs ==")
for lang in ("hu", "en"):
    d = json.loads((ROOT / "lang" / f"{lang}.json").read_text(encoding="utf-8"))
    need = [f"gate.name.{k}" for k in ("target_reach", "sma_chop")] + [
        f"gp.target_reach.{p['key']}.label" for p in tr.PARAMS] + [
        f"gp.sma_chop.{p['key']}.label" for p in sc.PARAMS] + [
        "target_reach.blocked", "sma_chop.blocked"]
    check(f"{lang}: minden felirat megvan", all(k in d for k in need),
          [k for k in need if k not in d])
for k in ("target_reach", "sma_chop"):
    check(f"{k}: van leirasa (hu+en)",
          (ROOT / "gates" / "docs" / f"{k}.md").exists()
          and (ROOT / "gates" / "docs" / f"{k}.en.md").exists())

print(f"\n{sum(_results)}/{len(_results)} teszt PASS")
if _fail:
    print("Bukott:", ", ".join(_fail))
sys.exit(0 if all(_results) else 1)

"""
BID/ASK PARITAS: minden kotes PONTOSAN egy spreadet fizet — mindket motorban.

Az MT5 gyertyai BID arak, ask-gyertya nincs. A helyes vegrehajtas:

    BUY   nyit ASK-on (close + spread), zar BID-en  (nyers high/low)
    SELL  nyit BID-en (close),          zar ASK-on  (high/low + spread)

A `run_pair` ezt jol csinalta, a PORTFOLIO-motor viszont a SELL kilepeset is a
nyers bid-en nezte: a short bid-en nyitott ES bid-en zart, tehat NULLA spreadet
fizetett. Egy 5 paros, 18 honapos portfolion ez +1055$ helyett +530$ — a nyereseg
majdnem KETSZERESEN volt tulbecsulve, es kizarolag a short oldalon (a BUY P&L
mindket futasban azonos volt).

Ezert a teszt nem a kodra allit, hanem a VISELKEDESRE: ha a spreadet nullara
allitjuk, a SHORT eredmenynek MEG KELL valtoznia. Ha valaki visszaveszi a nyers
bid-et, ez a teszt bukik.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import core.applog as _applog
_applog.harden_console()

import pandas as pd                                    # noqa: E402
from strategy import get_strategy_by_name              # noqa: E402
from strategy.settings import config_for_strategy      # noqa: E402
from core.execution_params import load_execution_params  # noqa: E402
from trading.backtest import run_pair                  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
_results = []
_fail = []


def check(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name + (f"  [{detail}]" if detail else ""))
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)


def _setup(sym, strat_name):
    raw = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    cfg = config_for_strategy(raw, strat_name)
    pf = ROOT / "data" / "optimized_params" / strat_name / f"{sym}.json"
    params = json.loads(pf.read_text(encoding="utf-8"))["params"]
    params = {**(load_execution_params(sym, cfg) or {}), **params}
    return cfg, params


SYM, STRAT = "Ger40", "wpr_sma"
_data_ok = ((ROOT / "data" / "m1" / f"{SYM}.parquet").exists()
            and (ROOT / "data" / "optimized_params" / STRAT / f"{SYM}.json").exists())

if not _data_ok:
    print(f"  (kihagyva: nincs {SYM} adat vagy optimalizalt parameter)")
    print("0/0 teszt PASS")
    sys.exit(0)

cfg, params = _setup(SYM, STRAT)
pair_cfg = cfg["pairs"][SYM]
ps = float(pair_cfg["point_size"])
m15 = pd.read_parquet(ROOT / "data" / "m15" / f"{SYM}.parquet")
m1 = pd.read_parquet(ROOT / "data" / "m1" / f"{SYM}.parquet")
strat = get_strategy_by_name(STRAT)

START, END = "2026-06-01", "2026-07-15"

# ---------------------------------------------------------------------------
print("== run_pair: a BELEPO oldala ==")
r = run_pair(SYM, m15, m1, params, pair_cfg, cfg["trading"], 1000.0,
             strategy=strat, test_start=START, test_end=END, cfg=cfg)
check("szuletett kotes (kulonben a teszt semmit nem mer)", len(r.trades) > 0,
      f"{len(r.trades)} kotes")

buy_off, sell_off, buy_sp = [], [], []
for t in r.trades:
    if t.open_time not in m1.index:
        continue
    bar = m1.loc[t.open_time]
    if isinstance(bar, pd.DataFrame):
        bar = bar.iloc[0]
    off = (t.open_price - float(bar["close"])) / ps
    if t.direction == "BUY":
        buy_off.append(off)
        sp = bar.get("close_spread")
        if sp is None or sp != sp or sp <= 0:
            sp = bar.get("avg_spread", float("nan"))
        buy_sp.append(float(sp) / ps if sp == sp else float("nan"))
    else:
        sell_off.append(off)

if sell_off:
    check("SELL a BID-en nyit (eltolas = 0)",
          max(abs(x) for x in sell_off) < 1e-6, f"n={len(sell_off)}")
if buy_off and buy_sp:
    pairs = [(o, s) for o, s in zip(buy_off, buy_sp) if s == s]
    check("BUY az ASK-on nyit (eltolas = a bar spreadje)",
          bool(pairs) and max(abs(o - s) for o, s in pairs) < 1e-6,
          f"n={len(pairs)}")
    check("a BUY eltolas POZITIV (nem 0 — tehat tenyleg fizet)",
          min(o for o, _ in pairs) > 0)

# ---------------------------------------------------------------------------
print("== A short oldal FIZET-E spreadet? (nulla-spread A/B) ==")


def _short_pnl(zero: bool):
    _m1 = m1
    _pc = dict(pair_cfg)
    if zero:
        _m1 = m1.copy()
        for c in ("avg_spread", "close_spread"):
            if c in _m1.columns:
                _m1[c] = 0.0
        _pc["backtest_spread_points"] = 0.0
    res = run_pair(SYM, m15, _m1, params, _pc, cfg["trading"], 1000.0,
                   strategy=strat, test_start=START, test_end=END, cfg=cfg)
    ts = [t for t in res.trades if t.direction == "SELL" and t.close_time is not None]
    return sum(t.pnl_usd for t in ts), len(ts)


p_real, n_real = _short_pnl(False)
p_zero, n_zero = _short_pnl(True)
print(f"     valos spread: SELL n={n_real} P&L={p_real:+.2f}$")
print(f"     nulla spread: SELL n={n_zero} P&L={p_zero:+.2f}$")
check("a SHORT eredmeny fugg a spreadtol (tehat fizeti)",
      n_real > 0 and abs(p_real - p_zero) > 1e-6,
      f"kulonbseg {p_zero - p_real:+.2f}$")
check("a spread NEM javit a shorton (a nulla-spread legalabb annyit hoz)",
      p_zero >= p_real - 1e-6)

# ---------------------------------------------------------------------------
print("== pnl_points: a spread NINCS ketszer levonva ==")
bad = []
for t in r.trades:
    if t.close_time is None or not t.point_size:
        continue
    exp = ((t.close_price - t.open_price) if t.direction == "BUY"
           else (t.open_price - t.close_price)) / t.point_size
    if abs(exp - t.pnl_points) > 1e-6:
        bad.append((t.direction, round(exp, 2), round(t.pnl_points, 2)))
check("a pont-oszlop az ARAKBOL jon (a spread mar bennuk van)",
      not bad, f"{len(bad)} elteres" + (f" pl. {bad[0]}" if bad else ""))

# A pont es a dollar EGY IRANYBA mutasson. ⚠ A BRUTTO dollarral kell osszevetni:
# a `pnl_points` csak az ARMOZGAS, a `pnl_usd` viszont NETTO (netto = brutto -
# jutalek + swap). Egy BE-re huzott stoppal zart kotes lehet +33 pont ES -0,84$,
# ha a swap tobbet vitt el, mint amennyit az armozgas hozott — ez nem hiba.
mism = []
for t in r.trades:
    if t.close_time is None or not t.pnl_points:
        continue
    gross = t.pnl_usd + getattr(t, "commission_usd", 0.0) - getattr(t, "swap_usd", 0.0)
    if gross and (t.pnl_points > 0) != (gross > 0):
        mism.append((t.direction, t.status, round(t.pnl_points, 2), round(gross, 2)))
check("a pont- es a BRUTTO dollar-eredmeny elojele egyezik", not mism,
      f"{len(mism)} elteres" + (f" pl. {mism[0]}" if mism else ""))

# ...es a koltseg tenyleg magyarazza a nettot (nem tunt el penz sehol)
_costed = [t for t in r.trades
           if t.close_time is not None
           and (getattr(t, "swap_usd", 0.0) or getattr(t, "commission_usd", 0.0))]
check("van koltseges kotes (a jutalek/swap modellezve van)", bool(_costed),
      f"{len(_costed)} kotesen van jutalek vagy swap")

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)

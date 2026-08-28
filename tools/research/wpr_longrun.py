"""A wpr_sma HOSSZU TAVON — a tickbol epitett mintan.

A felhasznalo kerdese (2026-08-28): "nezz ra a wpr_sma-ra, hogy az is ennyire
rossz eredmenyt hozna hosszutavon?"

Eddig ez a strategia 2 ev gyertyan volt merve. A tick-infrastruktura ota
4 parnak van hosszu elozmenye: GOLD 2013-, UsaInd/UsaTec 2017-, Ger40 2021-.

MIERT ERVENYES TESZT: a hangolt parameterek 2026-osak, a friss ablakon
optimalizalva. A korabbi evek tehat VALODI mintan kivuli szakasz — a strategia
sosem latta oket. Ez a legszigorubb teszt, ami ezzel az adattal lehetseges.

A valodi motorral fut (trading.backtest.run_pair), a valodi hangolt
parameterekkel, orakapuval es vegrehajtasi kapukkal — vagyis amit itt latunk,
azt latna az eles rendszer is.

ELFOGADASI FELTETEL (a projekt bevett merceje): nem az ossz-P&L, hanem az
EVENKENTI KONZISZTENCIA. Egy strategia, ami 14 evbol 4-ben nyer nagyot es
10-ben veszit, nem strategia, hanem szerencse.
"""

from __future__ import annotations

import json
import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

import core.applog as _applog
_applog.harden_console()

from core.execution_params import load_execution_params
from core.params_store import resolve_trade_hours
from strategy import get_strategy_by_name
from strategy.settings import config_for_strategy
from trading.backtest import run_pair

STRAT = "wpr_sma"
BALANCE = 1000.0


def setup(sym):
    raw = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    cfg = config_for_strategy(raw, STRAT)
    pf = ROOT / "data" / "optimized_params" / STRAT / f"{sym}.json"
    params = json.loads(pf.read_text(encoding="utf-8"))["params"]
    params = {**(load_execution_params(sym, cfg) or {}), **params}
    legacy = (cfg.get("pairs", {}).get(sym, {}) or {}).get("trade_hours")
    hrs = resolve_trade_hours(sym, STRAT, legacy)
    return cfg, params, (set(hrs) if hrs else None)


def run(sym):
    cfg, params, hours = setup(sym)
    m15 = pd.read_parquet(ROOT / "data" / "m15" / f"{sym}.parquet")
    m1 = pd.read_parquet(ROOT / "data" / "m1" / f"{sym}.parquet")
    strat = get_strategy_by_name(STRAT)
    r = run_pair(sym, m15, m1, params, cfg["pairs"][sym], cfg["trading"],
                 BALANCE, strategy=strat, allowed_hours=hours, cfg=cfg,
                 exec_gates=True)
    rows = []
    for t in r.closed:
        rows.append({
            "sym": sym, "ev": t.open_time.year, "irany": t.direction,
            "pnl": float(t.pnl_usd), "swap": float(t.swap_usd),
            "komm": float(t.commission_usd),
            "R": float(t.pnl_usd / t.risk_usd) if t.risk_usd else np.nan,
        })
    return pd.DataFrame(rows)


def main():
    pd.set_option("display.width", 220)
    syms = _sys.argv[1:] or ["GOLD", "UsaInd", "UsaTec", "Ger40"]
    parts = []
    for s in syms:
        if not (ROOT / "data" / "m1" / f"{s}.parquet").exists():
            print(f"   ({s}: nincs adat)"); continue
        print(f"   … {s}", flush=True)
        d = run(s)
        print(f"      {len(d)} kotes, {d.ev.min()}-{d.ev.max()}" if len(d)
              else "      nincs kotes")
        parts.append(d)
    t = pd.concat(parts, ignore_index=True)

    print("\n" + "=" * 76)
    print("=== OSSZKEP instrumentumonkent (NETTO, jutalek+swap benne) ===")
    g = t.groupby("sym")
    o = pd.DataFrame({
        "kotes": g.size(),
        "netto_$": g.pnl.sum(),
        "atlag_R": g.R.mean(),
        "talalat%": g.pnl.apply(lambda s: 100 * (s > 0).mean()),
        "PF": g.pnl.apply(lambda s: s[s > 0].sum() / abs(s[s < 0].sum())
                          if (s < 0).any() else np.nan),
        "swap_$": g.swap.sum(),
    })
    # t-statisztika az atlag R-re: van-e egyaltalan jel a zajban?
    o["t(R)"] = g.R.apply(lambda s: s.mean() / (s.std(ddof=1) / np.sqrt(s.count()))
                          if s.count() > 2 else np.nan)
    print(o.to_string(float_format=lambda v: f"{v:10.3f}"))

    print("\n=== EVENKENTI NETTO $ (ez a valodi merce) ===")
    piv = t.pivot_table(index="ev", columns="sym", values="pnl", aggfunc="sum")
    piv["OSSZ"] = piv.sum(axis=1)
    print(piv.to_string(float_format=lambda v: f"{v:9.1f}"))
    poz = (piv > 0).sum()
    db = piv.notna().sum()
    print("\n   pozitiv evek:")
    for c in piv.columns:
        print(f"      {c:8s} {int(poz[c])}/{int(db[c])}")

    print("\n=== LONG vs SHORT (a sodrodas-teszt) ===")
    ls = t.groupby(["sym", "irany"]).agg(kotes=("R", "size"),
                                         atlag_R=("R", "mean"),
                                         netto=("pnl", "sum"))
    ls["t"] = t.groupby(["sym", "irany"]).R.apply(
        lambda s: s.mean() / (s.std(ddof=1) / np.sqrt(s.count()))
        if s.count() > 2 else np.nan)
    print(ls.to_string(float_format=lambda v: f"{v:10.3f}"))
    both = [s for s in t.sym.unique()
            if (ls.loc[s].atlag_R > 0).all()]
    print(f"\n   Ahol MINDKET irany pozitiv: {len(both)}/{t.sym.nunique()} "
          f"{both if both else ''}")

    out = ROOT / "data" / "wpr_longrun.csv"
    t.to_csv(out, index=False)
    print(f"\nkotes-szintu tabla: {out}")


if __name__ == "__main__":
    main()

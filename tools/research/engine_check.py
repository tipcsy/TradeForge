"""A LELET ATVITELE A VALODI MOTORRA — a vegso ellenorzes.

A `holdout.py` merese jelzes-minoseget mert. Itt ugyanazok a mintak a
`trading.backtest.run_pair`-en futnak: slot-korlat, atfedo kotesek kizarasa,
orakapu, vegrehajtasi kapuk, valodi lot-szamitas.

MIT VARUNK: a szam ROMLANI fog. A jelzes-mereseben minden gyertya onalloan
ertekelodott; a motorban egy nyitott pozicio kizarja a kovetkezo belepot, es a
kapuk is szurnek. A kerdes az, hogy POZITIV MARAD-E.

A jeloltek KIZAROLAG a kereso szakasz (2017-2022) alapjan lettek valasztva
(`data/jeloltek_<sym>.json`), a futtatas a holdouton (2023-tol) megy.
"""

from __future__ import annotations

import json
import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

import core.applog as _applog
_applog.harden_console()

from core.execution_params import load_execution_params
from strategy.settings import config_for_strategy
from trading.backtest import run_pair

from pattern_strategy import PatternStrategy

KEZDET = "2023-01-01"
BALANCE = 1000.0


def fuss(sym: str, mintazat: str, irany: str, cfg, params, m15, m1,
         exec_gates: bool):
    st = PatternStrategy(mintazat, irany)
    r = run_pair(sym, m15, m1, params, cfg["pairs"][sym], cfg["trading"],
                 BALANCE, strategy=st, cfg=cfg, exec_gates=exec_gates,
                 test_start=KEZDET)
    zart = r.closed
    if not zart:
        return None
    R = np.array([t.pnl_usd / t.risk_usd for t in zart if t.risk_usd])
    if len(R) < 10:
        return None
    pnl = float(sum(t.pnl_usd for t in zart))
    ev = pd.Series([t.pnl_usd for t in zart],
                   index=pd.to_datetime([t.open_time for t in zart])).groupby(
                       lambda d: d.year).sum()
    return {"n": len(R), "R": float(R.mean()),
            "t": float(R.mean() / (R.std(ddof=1) / np.sqrt(len(R)))),
            "netto$": pnl, "poz_ev": f"{int((ev > 0).sum())}/{len(ev)}",
            "swap$": float(sum(t.swap_usd for t in zart))}


def main():
    sym = _sys.argv[1] if len(_sys.argv) > 1 else "UsaTec"
    _j = json.loads((ROOT / "data" / f"jeloltek_{sym}.json")
                    .read_text(encoding="utf-8"))
    # a jelolt lehet puszta string (regi alak) vagy {mintazat, irany} (uj)
    jeloltek = [(d, "BUY") if isinstance(d, str)
                else (d["mintazat"], "BUY" if d["irany"] == "long" else "SELL")
                for d in _j]
    raw = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    cfg = config_for_strategy(raw, "wpr_sma")      # a VAZ configja (kapuk, slot)
    params = {"sl_atr_mult": 1.5, "tp_rr_ratio": 2.0,
              **(load_execution_params(sym, cfg) or {})}
    m15 = pd.read_parquet(ROOT / "data" / "m15" / f"{sym}.parquet")
    m1 = pd.read_parquet(ROOT / "data" / "m1" / f"{sym}.parquet")

    print(f"=== {sym}: {len(jeloltek)} jelolt a VALODI motoron, {KEZDET}-tol ===")
    print(f"   slot-korlat: {cfg['trading'].get('max_open_slots')}   "
          f"kockazat/kotes: {cfg['trading'].get('account_risk_pct')}%\n")
    for kapuk in (False, True):
        print(f"--- vegrehajtasi kapuk: {'BE' if kapuk else 'KI'} ---")
        print(f"   {'#':>2s} {'n':>5s} {'R/kotes':>9s} {'t':>7s} "
              f"{'netto$':>9s} {'poz.ev':>7s} {'swap$':>8s}")
        sorok = []
        for i, (mp, ir) in enumerate(jeloltek, 1):
            try:
                s = fuss(sym, mp, ir, cfg, params, m15, m1, kapuk)
            except Exception as e:
                print(f"   {i:>2d} HIBA: {type(e).__name__}: {e}")
                continue
            if s is None:
                print(f"   {i:>2d} (keves kotes)")
                continue
            sorok.append(s)
            print(f"   {i:>2d}{ir[0]} {s['n']:>5d} {s['R']:>+9.4f} {s['t']:>+7.2f} "
                  f"{s['netto$']:>+9.1f} {s['poz_ev']:>7s} {s['swap$']:>+8.1f}")
        if sorok:
            R = np.array([s["R"] for s in sorok])
            print(f"   ---- {len(sorok)} jelolt atlaga: R {R.mean():+.4f}, "
                  f"ebbol pozitiv {int((R > 0).sum())}/{len(R)}")
        print()


if __name__ == "__main__":
    main()

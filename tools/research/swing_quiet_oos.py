"""Csendes otod + >=2 egyuttallas — FUGGETLEN proba a 2023 ELOTTI szakaszon (2026-10-02).

A szurot a 2023+ adaton valasztottuk (utolagos), ezert ott nem igazolhato.
ELORE ROGZITVE: vol_arany <= 0,78 (a 2023+ also otod hatara, VALTOZATLAN), >=2
egyezes {M1,M5,H1,H4}, csak long, nappali ablak (10-21h HU, zaras 21:45), egy
pozicio/instr. Siker: netto > 0, >=3 instrumentum pozitiv, evek >=60%-a pozitiv,
es a veletlen longot veri (kulonbseg > 0).
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT)); _sys.path.insert(0, str(_Path(__file__).resolve().parent))
import numpy as np
import pandas as pd
from swing_weekly_long import oat, controls, tstat
from swing_vol import vol_ratio

def main():
    X = pd.read_parquet(ROOT / "data" / "swing_weekly_m15_2013_2023.parquet")
    X = X[X.side == 1].copy()
    X["egy4"] = X.m1_ok + X.m5_ok + X.h1_ok + X.h4_ok
    X["vol"] = np.nan
    for s in X.sym.unique():
        v = vol_ratio(s, start="2013-03-01", end="2023-01-01")
        m = X.sym == s
        X.loc[m, "vol"] = v.reindex(X.loc[m, "time"]).to_numpy()
    X = X.dropna(subset=["vol"])
    print("instrumentumok es idoszak:", {s: f"{g.time.min().year}-{g.time.max().year}" for s, g in X.groupby("sym")})
    print(f"vol_arany median a regi szakaszon: {X.vol.median():.2f};  <=0,78 aranya: {100*(X.vol<=0.78).mean():.0f}%\n")

    def row(name, a):
        a = oat(a).copy()
        a["rand"] = controls(a, start="2013-03-01"); a["diff"] = a.net - a.rand
        yrs = (a.time.max() - a.time.min()).days / 365.25
        yr = a.groupby(a.time.dt.year).net.mean()
        s = a.groupby("sym").net.mean()
        print(f"{name:34} n={len(a):5d} {len(a)/yrs:5.0f}/ev  netto {100*a.net.mean():+6.2f} (t={tstat(a.net):+5.2f})  "
              f"veletlen {100*a.rand.mean():+6.2f}  kul {100*a['diff'].mean():+6.2f} (t={tstat(a['diff']):+5.2f})  "
              f"ev+ {(yr>0).sum()}/{len(yr)}  instr+ {(s>0).sum()}/{len(s)}")
        return a

    print("2013-2022, csak long, nappali, 10 000 / 100:")
    row("minden long (alap)", X)
    row(">=2 egyezes", X[X.egy4 >= 2])
    row("csendes (vol<=0,78)", X[X.vol <= 0.78])
    a = row("JELOLT: csendes + >=2 egyezes", X[(X.vol <= 0.78) & (X.egy4 >= 2)])
    print("\nJELOLT evenkent (netto/kotes, db):")
    for y, g in a.groupby(a.time.dt.year):
        print(f"   {y}  {100*g.net.mean():+7.2f}  n={len(g):4d}  veletlen {100*g.rand.mean():+6.2f}")
    print("JELOLT instrumentumonkent:")
    for s, g in a.groupby("sym"):
        print(f"   {s:7} {100*g.net.mean():+7.2f}  n={len(g):4d}  veletlen {100*g.rand.mean():+6.2f}")


if __name__ == "__main__":
    main()

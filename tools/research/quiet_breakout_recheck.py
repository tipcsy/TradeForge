"""A csendes + >=2 egyuttallas jelolt UJRAMERESE a JAVITOTT idokezelessel — 2026-10-02.

⚠ MIERT. A korabbi meresek (`swing_weekly`, `swing_vol`, `swing_quiet_oos`) a
gyertya-indexet UTC-nek vettek es Europe/Budapest-re valtottak — de az index
KANONIKUS FAL-ORA (berlini = magyar), csak „UTC" cimkevel. Igy a „10–21 ora"
valojaban nyaron 08–19, telen 09–20 volt, es a „21:45-os zaras" 19:45/20:45.
Itt ugyanaz a jelolt fut a VALODI 10:00–20:59 ablakkal es 21:45-os zarassal
(a kuszobok VALTOZATLANOK: vol <= 0,78, >= 2 egyezes, csak long).

Mindket szakasz, veletlen-long kontrollal, 10 000 szamla / 100 kockazat.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
from swing_weekly_long import oat, controls, tstat
from swing_vol import vol_ratio

def main():
    for fname, lbl, vstart, vend, cstart in (
            ("swing_weekly_m15_2013_2023.parquet", "2013-2022 (fuggetlen)", "2013-03-01", "2023-01-01", "2013-03-01"),
            ("swing_weekly_m15.parquet", "2023-2026", "2022-09-01", None, "2022-11-01")):
        X = pd.read_parquet(ROOT / "data" / fname)
        X = X[(X.side == 1)].copy()
        if "2013" not in fname:
            X = X[X.time >= pd.Timestamp("2023-01-01", tz="UTC")]
        X["egy4"] = X.m1_ok + X.m5_ok + X.h1_ok + X.h4_ok
        X["vol"] = np.nan
        for s in X.sym.unique():
            v = vol_ratio(s, start=vstart, end=vend)
            m = X.sym == s
            X.loc[m, "vol"] = v.reindex(X.loc[m, "time"]).to_numpy()
        X = X.dropna(subset=["vol"])
        print(f"\n=== {lbl}  (vol median {X.vol.median():.2f})")
        for name, sel in (("minden long", X), ("csendes", X[X.vol <= 0.78]),
                          (">=2 egyezes", X[X.egy4 >= 2]),
                          ("JELOLT csendes + >=2", X[(X.vol <= 0.78) & (X.egy4 >= 2)])):
            a = oat(sel).copy()
            a["rand"] = controls(a, start=cstart)
            a["diff"] = a.net - a.rand
            yrs = (a.time.max() - a.time.min()).days / 365.25
            yr = a.groupby(a.time.dt.year).net.mean()
            s = a.groupby("sym").net.mean()
            print(f"  {name:22} n={len(a):5d} {len(a)/yrs:5.0f}/ev  netto {100*a.net.mean():+6.2f} (t={tstat(a.net):+5.2f})  "
                  f"veletlen {100*a.rand.mean():+6.2f}  kul {100*a['diff'].mean():+6.2f} (t={tstat(a['diff']):+5.2f})  "
                  f"ev+ {(yr>0).sum()}/{len(yr)}  instr+ {(s>0).sum()}/{len(s)}")
            if name.startswith("JELOLT"):
                print("     evenkent:", " ".join(f"{y}:{100*g.net.mean():+.1f}({len(g)})" for y, g in a.groupby(a.time.dt.year)))
                print("     instr.:", " ".join(f"{k}:{100*g.net.mean():+.1f}({len(g)})" for k, g in a.groupby("sym")))


if __name__ == "__main__":
    main()

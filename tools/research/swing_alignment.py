"""Idosik-egyuttallas (M1, M5, H1, H4 + M30, D1) a csak-long, nappali belepon — 2026-10-02.

Belepo: swing_weekly.py (M15 visszahuzodas utani atzaras, 10-21h HU, zaras 21:45,
max 8 h), csak long, 2023+, egy pozicio instrumentumonkent, 10 000 / 100 nezet.
Az M15 a belepo definicioja szerint a belepes elott NEM emelkedo -> nem lehet
az egyuttallas resze.

ELORE ROGZITVE: egyuttallas-szam = hany emelkedo (HH+HL) a {M1, M5, H1, H4} kozul
(0-4). Jelolt: "mind a 4" es "mind a 4 + M30 + D1". Siker: >= +10 / kotes, t >= 2,
es a veletlen-long kontrollt t >= 2-vel veri.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
from core import broker_paths as _BP                      # noqa: E402
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
from swing_weekly_long import oat, controls, tstat

if __name__ == "__main__":
    X = pd.read_parquet(_BP.research_dir() / "swing_weekly_m15.parquet")
    X = X[(X.time >= pd.Timestamp("2023-01-01", tz="UTC")) & (X.side == 1)].copy()
    X["egy4"] = X.m1_ok + X.m5_ok + X.h1_ok + X.h4_ok
    wk = (X.time.max() - X.time.min()).days / 7
    yrs = wk / 52
    groups = {f"{k}/4 egyezik": (lambda x, k=k: x[x.egy4 == k]) for k in range(5)}
    groups["mind 4 + M30"] = lambda x: x[(x.egy4 == 4) & (x.m30_ok == 1)]
    groups["mind 4 + M30 + D1"] = lambda x: x[(x.egy4 == 4) & (x.m30_ok == 1) & (x.d1_ok == 1)]
    groups["H1+H4 (F2, osszevet.)"] = lambda x: x[(x.h1_ok == 1) & (x.h4_ok == 1)]
    print(f"CSAK LONG, nappali, 2023-01 -> {X.time.max().date()}, 10 000 / 100\n")
    print("egyedi idosikok aranya a long belepokben:",
          {c: f"{100*X[c].mean():.0f}%" for c in ("m1_ok", "m5_ok", "h1_ok", "h4_ok", "m30_ok", "d1_ok")})
    print(f"\n{'csoport':22} {'kot/ev':>6} {'kot/het/i':>9} {'brutto':>7} {'NETTO':>7} {'t':>5} {'nyero%':>6} {'$/ev':>7} | "
          f"{'veletlen':>8} {'kul':>6} {'t_kul':>6} | {'2023':>6} {'2024':>6} {'2025':>6} {'2026':>6} | instr+")
    res = []
    for name, f in groups.items():
        a = oat(f(X)).copy()
        if len(a) < 20:
            print(f"{name:22} n={len(a)}"); continue
        a["rand"] = controls(a)
        a["diff"] = a.net - a.rand
        yr = a.groupby(a.time.dt.year).net.sum() * 100
        s = a.groupby("sym").net.mean()
        print(f"{name:22} {len(a)/yrs:6.0f} {len(a)/wk/10:9.2f} {100*a.gross.mean():+7.2f} {100*a.net.mean():+7.2f} "
              f"{tstat(a.net):+5.2f} {100*(a.net>0).mean():6.1f} {100*a.net.sum()/yrs:+7.0f} | "
              f"{100*a.rand.mean():+8.2f} {100*a['diff'].mean():+6.2f} {tstat(a['diff']):+6.2f} | "
              + " ".join(f"{yr.get(y,0):+6.0f}" for y in (2023, 2024, 2025, 2026)) + f" | {(s>0).sum()}/{len(s)}")
        res.append(a.assign(csoport=name))
    pd.concat(res).to_parquet(_BP.research_dir() / "swing_alignment.parquet")

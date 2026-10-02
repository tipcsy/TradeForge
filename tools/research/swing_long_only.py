"""Csak-long valtozat: M15 belepo, H1 lab>=1 ES H1 trend (HH+HL) — 2026-10-02.

ELORE ROGZITVE:
  * Jelolt: a swing_mtf M15 belepoi kozul side=+1, h1_legs>=1, h1_ok==1.
  * Elfogadas: (1) README-protokoll: t>=2, evek >=60%-a pozitiv, >=3 instr.
    pozitiv; (2) SODRODAS-KONTROLL: veletlen long belepok ugyanazon az
    instrumentumon, ugyanabban az evben es UTC-oraban, ugyanakkora (ATR-ben mert)
    stoppal, ugyanazzal a kilepessel (stop / 8 ora / 20:45 UTC) — a jeloltnek
    ezt kell vernie, a kulonbseg t>=2.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import lab

N_RAND = 5          # veletlen parok szama jeloltenkent


def _sim(h, l, c, sp, a, mins, day, i, risk_atr, hold):
    risk = risk_atr * a[i]
    stp = c[i] - risk
    n = len(c)
    ex = np.nan
    for t in range(i + 1, min(i + hold, n - 1) + 1):
        if day[t] != day[i] or mins[t] > 20 * 60 + 45:
            ex = c[t - 1]; break
        if l[t] <= stp:
            ex = stp; break
        ex = c[t]
    if np.isnan(ex) or not np.isfinite(sp[i]):
        return np.nan, np.nan
    g = (ex - c[i]) / risk
    return g, g - sp[i] / risk


def main():
    R = pd.read_parquet(ROOT / "data" / "swing_mtf_m15.parquet").dropna(subset=["net"])
    C = R[(~R.mirror) & (R.side == 1) & (R.h1_legs >= 1) & (R.h1_ok == 1)].copy()
    rng = np.random.default_rng(7)
    rows = []
    for sym, g in C.groupby("sym"):
        d = lab.resample(lab.load_m1(sym), 15)
        h = d["high"].to_numpy(float); l = d["low"].to_numpy(float)
        c = d["close"].to_numpy(float); sp = d["avg_spread"].to_numpy(float)
        a = lab.atr(h, l, c, 14)
        mins = (d.index.hour * 60 + d.index.minute).to_numpy() + 15
        day = d.index.normalize().to_numpy()
        pos = {ts: k for k, ts in enumerate(d.index)}
        key = pd.DataFrame({"y": d.index.year, "h": d.index.hour})
        pools = {kk: v.index.to_numpy() for kk, v in key.groupby(["y", "h"])}
        for _, r in g.iterrows():
            i = pos[r.time]
            # a jelolt R-jet visszaszamoljuk a stopbol: risk_atr kell -> a koltsegbol
            risk = sp[i] / r.cost if r.cost > 0 else np.nan
            if not np.isfinite(risk) or a[i] <= 0:
                continue
            ra = risk / a[i]
            pool = pools[(r.time.year, r.time.hour)]
            nets = []
            for j in rng.choice(pool, size=N_RAND * 3, replace=True):
                if len(nets) >= N_RAND:
                    break
                if j < 20 or not np.isfinite(a[j]) or a[j] <= 0:
                    continue
                _, nt = _sim(h, l, c, sp, a, mins, day, j, ra, 32)
                if np.isfinite(nt):
                    nets.append(nt)
            rows.append((sym, r.time, r.net, r.gross, np.mean(nets) if nets else np.nan))
        print(sym, flush=True)
    out = pd.DataFrame(rows, columns=["sym", "time", "net", "gross", "rand_net"])
    out.to_parquet(ROOT / "data" / "swing_long_only.parquet")
    print("kesz", len(out))


if __name__ == "__main__":
    main()

"""Csak-long, nappali ablak (10-21h HU, zaras 21:45, max 8 h), 2023+ — 2026-10-02.

A swing_weekly.py belepoi kozul csak a long-ok; szurok F0/F1/F2/F5; egy pozicio
instrumentumonkent. KONTROLL: veletlen long ugyanazon az instrumentumon, evben
es helyi oraban, ugyanakkora (ATR-ben mert) stoppal, ugyanazzal a kilepessel —
kotesenkent 5 veletlen par atlaga. Siker (elore): atlag netto >= +10 / kotes,
t >= 2, es a kontrollt t >= 2-vel veri.
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

# ⚠ A gyertya-index KANONIKUS FAL-ÓRA (berlini = magyar helyi idő), csak „UTC"
# címkével tárolva (`core/broker_time.py`). Átváltani TILOS: 2026-10-02-ig itt
# Europe/Budapest állt, ami 1–2 órával eltolta az ablakot. Az „UTC" = nincs átváltás.
TZ = "UTC"


def oat(df):
    keep = []
    for s, g in df.sort_values("time").groupby("sym"):
        free = pd.Timestamp.min.tz_localize("UTC")
        for idx, r in g.iterrows():
            if r.time >= free:
                keep.append(idx); free = r.exit_time
    return df.loc[keep]


L3 = lambda x: (x.h1_ok == 1) & (x.h4_ok == 1)
FILTERS = {
    "F0 nincs szuro": lambda x: x,
    "F1 H1 trend": lambda x: x[x.h1_ok == 1],
    "F2 H1+H4 trend": lambda x: x[L3(x)],
    "F5 F2+napi elso": lambda x: x[L3(x)].sort_values("time").groupby(["sym", "local_day"]).head(1),
}


def controls(sel: pd.DataFrame, n_rand=5, seed=11, start="2022-11-01"):
    rng = np.random.default_rng(seed)
    out = pd.Series(np.nan, index=sel.index)
    for sym, g in sel.groupby("sym"):
        m1 = lab.load_m1(sym)
        m1 = m1[m1.index >= start]
        d = lab.resample(m1, 15)
        h = d.high.to_numpy(float); l = d.low.to_numpy(float)
        c = d.close.to_numpy(float); sp = d.avg_spread.to_numpy(float)
        a = lab.atr(h, l, c, 14)
        loc = (d.index + pd.Timedelta(minutes=15)).tz_convert(TZ)
        lmin = (loc.hour * 60 + loc.minute).to_numpy()
        lday = loc.normalize().to_numpy()
        pos = {t: k for k, t in enumerate(d.index)}
        key = pd.DataFrame({"y": loc.year, "h": loc.hour})
        pools = {k: v.index.to_numpy() for k, v in key.groupby(["y", "h"])}
        for idx, r in g.iterrows():
            i = pos[r.time]
            ra = (sp[i] / r.cost) / a[i]
            pool = pools[(loc[i].year, loc[i].hour)]
            vals = []
            for j in rng.choice(pool, size=n_rand * 4):
                if len(vals) >= n_rand:
                    break
                if j < 20 or not (np.isfinite(a[j]) and a[j] > 0 and np.isfinite(sp[j])):
                    continue
                risk = ra * a[j]; stp = c[j] - risk + sp[j] * 0  # long: bid-stop
                ex = np.nan
                for t in range(j + 1, min(j + 32, len(c) - 1) + 1):
                    if lday[t] != lday[j] or lmin[t] > 21 * 60 + 45:
                        ex = c[t - 1]; break
                    if l[t] <= stp:
                        ex = stp; break
                    ex = c[t]
                if np.isfinite(ex):
                    vals.append((ex - c[j]) / risk - sp[j] / risk)
            out[idx] = np.mean(vals) if vals else np.nan
    return out


def tstat(x):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    return x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))


if __name__ == "__main__":
    X = pd.read_parquet(ROOT / "data" / "swing_weekly_m15.parquet")
    X = X[(X.time >= pd.Timestamp("2023-01-01", tz="UTC")) & (X.side == 1)]
    wk = (X.time.max() - X.time.min()).days / 7
    yrs = wk / 52
    print(f"CSAK LONG, 10-21h HU, 2023-01 -> {X.time.max().date()}, 10 000 szamla / 100 kockazat\n")
    print(f"{'szuro':16} {'kot/het/i':>9} {'kot/ev':>6} {'brutto':>7} {'spread':>6} {'NETTO':>7} {'t':>5} {'nyero%':>6} "
          f"{'$/ev':>7} | {'veletlen':>8} {'kul':>6} {'t_kul':>6} | {'2023':>6} {'2024':>6} {'2025':>6} {'2026':>6} | instr+")
    res = {}
    for name, f in FILTERS.items():
        a = oat(f(X)).copy()
        a["rand"] = controls(a)
        a["diff"] = a.net - a.rand
        res[name] = a
        yr = a.groupby(a.time.dt.year).net.sum() * 100
        s = a.groupby("sym").net.mean()
        print(f"{name:16} {len(a)/wk/10:9.2f} {len(a)/yrs:6.0f} {100*a.gross.mean():+7.2f} {100*a.cost.mean():6.2f} "
              f"{100*a.net.mean():+7.2f} {tstat(a.net):+5.2f} {100*(a.net>0).mean():6.1f} {100*a.net.sum()/yrs:+7.0f} | "
              f"{100*a.rand.mean():+8.2f} {100*a['diff'].mean():+6.2f} {tstat(a['diff']):+6.2f} | "
              + " ".join(f"{yr.get(y,0):+6.0f}" for y in (2023, 2024, 2025, 2026)) + f" | {(s>0).sum()}/{len(s)}")
    for name in ("F2 H1+H4 trend", "F5 F2+napi elso"):
        a = res[name]
        print(f"\n{name} instrumentumonkent:  netto/kotes  (veletlen)  kotes  $/ev")
        for s, g in a.groupby("sym"):
            print(f"   {s:7} {100*g.net.mean():+7.2f}  ({100*g.rand.mean():+6.2f})  {len(g):4d}  {100*g.net.sum()/yrs:+6.0f}")
    pd.concat([v.assign(szuro=k) for k, v in res.items()]).to_parquet(ROOT / "data" / "swing_weekly_long.parquet")

"""Volatilitas-szuro + egyuttallas a csak-long, nappali belepon — 2026-10-02.

ELORE ROGZITVE:
  * vol_arany = M15 ATR(14) a belepo baran / ugyanazon HELYI ORA ATR(14)-enek
    mediánja az elozo ~20 napban (80 bar: 4 M15 bar/ora x 20 nap, 1 nappal
    eltolva -> nincs jovo-szivargas). >1 = mozgalmasabb a szokasosnal.
  * Jelolt: vol_arany >= 1,3 ES legalabb 2 egyezes {M1, M5, H1, H4} kozul.
  * Siker: >= +10 / kotes, t >= 2, a veletlen-long kontrollt t >= 2-vel veri.
  * A kontroll a vol-feltetelt NEM masolja (azonos instr./ev/ora/stop) — igy
    latszik, mennyit ad a "most nagyon megy" pillanat a sima long-hoz kepest.
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
import lab
from swing_weekly_long import oat, controls, tstat

# ⚠ A gyertya-index KANONIKUS FAL-ÓRA (berlini = magyar helyi idő), csak „UTC"
# címkével tárolva (`core/broker_time.py`). Átváltani TILOS: 2026-10-02-ig itt
# Europe/Budapest állt, ami 1–2 órával eltolta az ablakot. Az „UTC" = nincs átváltás.
TZ = "UTC"


def vol_ratio(sym, start="2022-09-01", end=None):
    m1 = lab.load_m1(sym)
    m1 = m1[m1.index >= start]
    if end is not None:
        m1 = m1[m1.index < end]
    d = lab.resample(m1, 15)
    a = pd.Series(lab.atr(d.high.to_numpy(float), d.low.to_numpy(float), d.close.to_numpy(float), 14),
                  index=d.index)
    hr = d.index.tz_convert(TZ).hour
    base = a.groupby(hr).transform(lambda s: s.rolling(80, min_periods=40).median().shift(4))
    return (a / base).rename("vol")


if __name__ == "__main__":
    X = pd.read_parquet(_BP.research_dir() / "swing_weekly_m15.parquet")
    X = X[(X.time >= pd.Timestamp("2023-01-01", tz="UTC")) & (X.side == 1)].copy()
    X["egy4"] = X.m1_ok + X.m5_ok + X.h1_ok + X.h4_ok
    X["vol"] = np.nan
    for s in X.sym.unique():
        v = vol_ratio(s)
        m = X.sym == s
        X.loc[m, "vol"] = v.reindex(X.loc[m, "time"]).to_numpy()
    X = X.dropna(subset=["vol"])
    wk = (X.time.max() - X.time.min()).days / 7
    yrs = wk / 52
    print(f"CSAK LONG, nappali, 2023+, 10 000 / 100.  vol_arany median: {X.vol.median():.2f}, "
          f">=1,3 aranya: {100*(X.vol>=1.3).mean():.0f}%\n")

    def row(name, a, ctrl=True):
        a = oat(a).copy()
        if len(a) < 20:
            print(f"{name:30} n={len(a)}"); return
        yr = a.groupby(a.time.dt.year).net.sum() * 100
        s = a.groupby("sym").net.mean()
        extra = ""
        if ctrl:
            a["rand"] = controls(a); a["diff"] = a.net - a.rand
            extra = f"{100*a.rand.mean():+8.2f} {100*a['diff'].mean():+6.2f} {tstat(a['diff']):+6.2f}"
        else:
            extra = f"{'':8} {'':6} {'':6}"
        print(f"{name:30} {len(a)/yrs:6.0f} {100*a.gross.mean():+7.2f} {100*a.net.mean():+7.2f} {tstat(a.net):+5.2f} "
              f"{100*(a.net>0).mean():6.1f} {100*a.net.sum()/yrs:+7.0f} | {extra} | "
              + " ".join(f"{yr.get(y,0):+6.0f}" for y in (2023, 2024, 2025, 2026)) + f" | {(s>0).sum()}/{len(s)}")

    hdr = (f"{'csoport':30} {'kot/ev':>6} {'brutto':>7} {'NETTO':>7} {'t':>5} {'nyero%':>6} {'$/ev':>7} | "
           f"{'veletlen':>8} {'kul':>6} {'t_kul':>6} | {'2023':>6} {'2024':>6} {'2025':>6} {'2026':>6} | instr+")
    print("A) vol_arany otodok — MINDEN long belepo"); print(hdr)
    q = X.vol.quantile([.2, .4, .6, .8]).to_numpy()
    b = np.digitize(X.vol, q)
    for j in range(5):
        lo = X.vol.min() if j == 0 else q[j - 1]
        hi = X.vol.max() if j == 4 else q[j]
        row(f"otod {j+1} ({lo:.2f}-{hi:.2f})", X[b == j], ctrl=False)
    print("\nB) vol_arany otodok — legalabb 2 egyezes"); print(hdr)
    Y = X[X.egy4 >= 2]
    b = np.digitize(Y.vol, q)
    for j in range(5):
        row(f"otod {j+1}", Y[b == j], ctrl=False)
    print("\nC) A JELOLT es szomszedai"); print(hdr)
    row(">=2 egyezes (vol nelkul)", X[X.egy4 >= 2])
    row("vol>=1,3 (egyezes nelkul)", X[X.vol >= 1.3])
    row("JELOLT: vol>=1,3 + >=2 egyezes", X[(X.vol >= 1.3) & (X.egy4 >= 2)])
    row("vol>=1,3 + >=3 egyezes", X[(X.vol >= 1.3) & (X.egy4 >= 3)])
    X.to_parquet(_BP.research_dir() / "swing_vol.parquet")

"""Csucs/volgy-szerkezet (HH/HL/LH/LL) mint trend-definicio — 2026-10-02.

A felhasznalo kerdese: (1) szamit-e, hogy trendelo piacon kereskedunk, ha a
trendet NEM indikatorral (ADX/DI, MA), hanem a swing-szerkezettel definialjuk;
(2) melyik vesztes kotes az, ami a trend VEGEN szall be — es latszik-e ez
belepeskor.

ELORE ROGZITVE (a futtatas elott):
  * Szerkezet H1-en, pivot k=3 (k=5 robusztussag). A pivot csak k gyertyaval
    kesobb ismert -> minden esemeny a MEGERŐSITES baran tortenik.
  * Emelkedo trend = az utolso ket igazolt csucs HH ES az utolso ket igazolt
    volgy HL. Eso: LH + LL. Minden mas: "vegyes".
  * Belepok:  BOS  = zaras az utolso igazolt csucs folott (long) / volgy alatt;
              HL   = uj, magasabb volgy igazolodik emelkedo trendben (long);
    mindegyik TRENDBEN es VEGYES allapotban is, es TUKORKEPPEL (ellentetes
    irany) -> a ketto kulonbsegenek fele a bruttó irany-el.
  * Stop = az utolso igazolt ellen-swing (0,5–4 ATR kozott, kulonben kihagy),
    kilepes stop vagy H oraval kesobb (H=8 es 24). Nincs TP, nincs BE.
  * Elfogadas (README): netto R t>=2, az evek >=60%-a pozitiv, >=3 instr.
  * Trend-vegi kerdes: a TRENDBEN-belepoket a belepeskor TUDHATO jellemzok
    szerint bontom (hanyadik lab, milyen messze van az ar az utolso HL-tol
    ATR-ben, ATR-arany). A szuro-kuszobot CSAK a <2023 szakaszon valasztom,
    a >=2023 holdouton tesztelem.
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

SYMS = ["UsaTec", "UsaInd", "GOLD", "USDJPY", "Ger40"]
SPLIT = pd.Timestamp("2023-01-01", tz="UTC")


def pivots(h, l, k):
    n = len(h)
    ih = np.zeros(n, bool)
    il = np.zeros(n, bool)
    for i in range(k, n - k):
        wh = h[i - k:i + k + 1]
        wl = l[i - k:i + k + 1]
        if wh.argmax() == k:
            ih[i] = True
        if wl.argmin() == k:
            il[i] = True
    return ih, il


def events(d: pd.DataFrame, k: int):
    """Bar-szintu szerkezet-allapot es esemenyek, kauzalisan."""
    h = d["high"].to_numpy(float)
    l = d["low"].to_numpy(float)
    c = d["close"].to_numpy(float)
    a = lab.atr(h, l, c, 14)
    a_ref = pd.Series(a).rolling(24 * 20).median().to_numpy()
    ih, il = pivots(h, l, k)
    n = len(c)
    highs: list[float] = []   # igazolt csucsok ara
    lows: list[float] = []
    up_legs = 0               # egymast koveto HH+HL labak szama
    dn_legs = 0
    out = []
    last_bos_hi = None        # egy csucsot csak egyszer torunk
    last_bos_lo = None
    for i in range(k, n):
        p = i - k             # most igazolodik a p-n levo pivot
        new_low = new_high = False
        if ih[p]:
            highs.append(h[p]); new_high = True
        if il[p]:
            lows.append(l[p]); new_low = True
        if len(highs) < 2 or len(lows) < 2 or not np.isfinite(a[i]) or a[i] <= 0:
            continue
        hh = highs[-1] > highs[-2]
        hl = lows[-1] > lows[-2]
        state = 1 if (hh and hl) else (-1 if (not hh and not hl) else 0)
        if new_high:
            up_legs = up_legs + 1 if hh else 0
            dn_legs = dn_legs + 1 if not hh else 0
        ar = a[i] / a_ref[i] if np.isfinite(a_ref[i]) and a_ref[i] > 0 else np.nan
        base = dict(i=i, state=state, atr=a[i], atr_ratio=ar,
                    legs_up=up_legs, legs_dn=dn_legs)
        # HL / LH megerosites
        if new_low and hl and hh:
            out.append(dict(base, kind="HL", side=1, stop=lows[-1]))
        if new_high and (not hh) and (not hl):
            out.append(dict(base, kind="HL", side=-1, stop=highs[-1]))
        # BOS: zaras az utolso igazolt csucs folott / volgy alatt (elso atlepes)
        if c[i] > highs[-1] and c[i - 1] <= highs[-1] and last_bos_hi != highs[-1]:
            last_bos_hi = highs[-1]
            out.append(dict(base, kind="BOS", side=1, stop=lows[-1]))
        if c[i] < lows[-1] and c[i - 1] >= lows[-1] and last_bos_lo != lows[-1]:
            last_bos_lo = lows[-1]
            out.append(dict(base, kind="BOS", side=-1, stop=highs[-1]))
    ev = pd.DataFrame(out)
    # trendhez viszonyitott helyzet: a belepo iranya egyezik-e a szerkezettel
    ev["ctx"] = np.where(ev["state"] == 0, "vegyes",
                         np.where(ev["state"] == ev["side"], "trendben", "trend_ellen"))
    ev["legs"] = np.where(ev["side"] == 1, ev["legs_up"], ev["legs_dn"])
    return ev


def outcome(d, ev, horizon, mirror=False):
    """Bruttó es netto R. A bid-gyertyan: long ask-on nyit (c+sp), bid-en zar."""
    h = d["high"].to_numpy(float)
    l = d["low"].to_numpy(float)
    c = d["close"].to_numpy(float)
    sp = d["avg_spread"].to_numpy(float)
    n = len(c)
    g = np.full(len(ev), np.nan)
    net = np.full(len(ev), np.nan)
    risk_atr = np.full(len(ev), np.nan)
    hit = np.zeros(len(ev), bool)
    for j, (i, side, stop, atr_i) in enumerate(ev[["i", "side", "stop", "atr"]].to_numpy()):
        i = int(i)
        side = int(side)
        if mirror:
            side = -side
            stop = c[i] + (c[i] - stop)          # tukrozott strukturalis stop
        risk = (c[i] - stop) * side
        if not (0.5 * atr_i <= risk <= 4 * atr_i) or i + horizon >= n:
            continue
        ex = c[i + horizon]
        for t in range(i + 1, i + horizon + 1):
            if side == 1 and l[t] <= stop:
                ex = stop; hit[j] = True; break
            if side == -1 and h[t] + sp[t] >= stop:
                ex = stop - sp[t]; hit[j] = True; break
        gross = (ex - c[i]) * side / risk
        g[j] = gross
        net[j] = gross - sp[i] / risk
        risk_atr[j] = risk / atr_i
    r = ev.copy()
    r["gross"] = g
    r["net"] = net
    r["stop_hit"] = hit
    r["risk_atr"] = risk_atr
    return r.dropna(subset=["net"])


def tstat(x):
    x = np.asarray(x, float)
    return x.mean() / (x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 2 else np.nan


def run(k=3, horizons=(8, 24)):
    rows = []
    for s in SYMS:
        d = lab.resample(lab.load_m1(s), 60)
        ev = events(d, k)
        ts = d.index
        for H in horizons:
            for mir in (False, True):
                r = outcome(d, ev, H, mirror=mir)
                r["sym"] = s
                r["H"] = H
                r["mirror"] = mir
                r["time"] = ts[r["i"].to_numpy()]
                rows.append(r)
    return pd.concat(rows, ignore_index=True)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    R = run(a.k)
    out = a.out or str(ROOT / "data" / f"swing_structure_k{a.k}.parquet")
    R.to_parquet(out)
    print("mentve:", out, len(R))

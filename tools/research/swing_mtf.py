"""Tobb-idosikos swing-szerkezet: trend a FELSO idosikon (H1/H4), belepo az
ALSON (M5/M15) — 2026-10-02, a swing_structure.py folytatasa.

A felhasznalo kerdese: ha a trendet magasabb idosikon keressuk, a beszallot
alacsonyabbon, es SZIGORITJUK/RITKITJUK a felteteleket (heti 1 jel x 10
instrumentum is eleg) — lesz-e el?

ELORE ROGZITVE (futtatas elott):
  * Pivot k=3 minden idosikon (a csucs/volgy k gyertyaval kesobb ismert).
  * Szerkezet-allapot: +1 = HH+HL, -1 = LH+LL, 0 = vegyes. "lab" = hany
    egymast koveto HH (ill. LL) van mogotte.
  * BELEPO (alsó idosik): visszahuzodas utani atzaras — long, ha a zaras az
    utolso igazolt also-idosiki csucs folott van (elso atlepes), ES elotte az
    also-idosiki szerkezet NEM volt emelkedo (volt visszahuzodas). Short tukor.
    Stop: az utolso igazolt also-idosiki ellen-swing (0,5-4 ATR, kulonben kihagy).
  * KILEPES: stop, 8 ora, vagy 20:45 UTC (napon belul -> nincs swap). 19:00 UTC
    utan nincs belepo.
  * SZIGORITASI LEPCSOK (mindegyik az elozore epul, kiveve L1/L2 parhuzamos):
      L0  csak a belepo (felso idosik nelkul) — alapvonal
      L1  + H1 szerkezet egyezik az irannyal
      L2  + H4 szerkezet egyezik  (L1 nelkul)
      L3  H1 ES H4 egyezik
      L4  L3 + a H4 trend KORAI (lab <= 2)
  * ITELET: (a) a szigoritas JAVIT-e — a netto R monoton no-e L0->L3->L4
    (L1/L2 oldalag); (b) a legszigorubb lepcso a README-protokollon: t>=2,
    evek >=60%-a pozitiv, >=3 instrumentum pozitiv. Tukorkep-kontroll mindenhol.
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

SYMS = ["UsaTec", "UsaInd", "GOLD", "USDJPY", "Ger40",
        "UK100", "EURUSD", "Usa500", "GBPUSD", "Jp225"]
K = 3


def pivots(h, l, k=K):
    H = pd.Series(h)
    L = pd.Series(l)
    cmax = H.rolling(2 * k + 1, center=True).max().to_numpy()
    cmin = L.rolling(2 * k + 1, center=True).min().to_numpy()
    pmax = H.shift(1).rolling(k).max().to_numpy()
    pmin = L.shift(1).rolling(k).min().to_numpy()
    ih = (h == cmax) & (h > pmax)
    il = (l == cmin) & (l < pmin)
    return ih, il


def structure(d, k=K):
    """Bar-onkent (a bar ZARASAKOR ismert): state, legs_up, legs_dn, lastH, lastL."""
    h = d["high"].to_numpy(float)
    l = d["low"].to_numpy(float)
    ih, il = pivots(h, l, k)
    n = len(h)
    st = np.zeros(n, np.int8)
    lu = np.zeros(n, np.int16)
    ld = np.zeros(n, np.int16)
    lH = np.full(n, np.nan)
    lL = np.full(n, np.nan)
    h1 = h2 = l1 = l2 = np.nan          # h1 = utolso, h2 = elotte
    up = dn = 0
    for i in range(k, n):
        p = i - k
        if ih[p]:
            h2, h1 = h1, h[p]
            if h1 > h2:
                up += 1; dn = 0
            elif h1 < h2:
                dn += 1; up = 0
        if il[p]:
            l2, l1 = l1, l[p]
        if not np.isnan(h2) and not np.isnan(l2):
            hh, hl = h1 > h2, l1 > l2
            st[i] = 1 if (hh and hl) else (-1 if (not hh and not hl) else 0)
        lu[i] = up
        ld[i] = dn
        lH[i] = h1
        lL[i] = l1
    return st, lu, ld, lH, lL


def htf_at(ltf_close_ts, htf: pd.DataFrame, minutes: int, arrs):
    """A felso idosik allapota az also bar zarasakor (csak lezart felso barok)."""
    close_ts = (htf.index + pd.Timedelta(minutes=minutes)).to_numpy()
    j = np.searchsorted(close_ts, ltf_close_ts, side="right") - 1
    ok = j >= 0
    return [np.where(ok, a[np.clip(j, 0, None)], 0) for a in arrs]


def run_sym(sym, ltf_min):
    m1 = lab.load_m1(sym)
    d = lab.resample(m1, ltf_min)
    h1d = lab.resample(m1, 60)
    h4d = lab.resample(m1, 240)
    h = d["high"].to_numpy(float)
    l = d["low"].to_numpy(float)
    c = d["close"].to_numpy(float)
    sp = d["avg_spread"].to_numpy(float)
    a = lab.atr(h, l, c, 14)
    st, lu, ld, lH, lL = structure(d)
    ltf_close = (d.index + pd.Timedelta(minutes=ltf_min)).to_numpy()
    s1, u1, d1 = htf_at(ltf_close, h1d, 60, list(structure(h1d)[:3]))
    s4, u4, d4 = htf_at(ltf_close, h4d, 240, list(structure(h4d)[:3]))
    mins = (d.index.hour * 60 + d.index.minute).to_numpy() + ltf_min
    day = d.index.normalize().to_numpy()
    hold = 8 * 60 // ltf_min
    rows = []
    broken_hi = broken_lo = np.nan
    n = len(c)
    for i in range(K + 1, n - 1):
        if not np.isfinite(a[i]) or a[i] <= 0 or mins[i] >= 19 * 60:
            continue
        side = 0
        if c[i] > lH[i] and c[i - 1] <= lH[i] and lH[i] != broken_hi and st[i] != 1:
            side, stop, broken_hi = 1, lL[i], lH[i]
        elif c[i] < lL[i] and c[i - 1] >= lL[i] and lL[i] != broken_lo and st[i] != -1:
            side, stop, broken_lo = -1, lH[i], lL[i]
        if side == 0 or np.isnan(stop):
            continue
        for mir in (False, True):
            sd = -side if mir else side
            stp = c[i] + (c[i] - stop) if mir else stop
            risk = (c[i] - stp) * sd
            if not (0.5 * a[i] <= risk <= 4 * a[i]):
                continue
            ex, hit = np.nan, False
            for t in range(i + 1, min(i + hold, n - 1) + 1):
                if day[t] != day[i] or mins[t] > 20 * 60 + 45:
                    ex = c[t - 1]; break
                if sd == 1 and l[t] <= stp:
                    ex, hit = stp, True; break
                if sd == -1 and h[t] + sp[t] >= stp:
                    ex, hit = stp - sp[t], True; break
                ex = c[t]
            if np.isnan(ex):
                continue
            gross = (ex - c[i]) * sd / risk
            legs4 = u4[i] if sd == 1 else d4[i]
            legs1 = u1[i] if sd == 1 else d1[i]
            rows.append((sym, ltf_min, d.index[i], mir, sd, gross,
                         gross - sp[i] / risk, hit, sp[i] / risk,
                         int(s1[i] == sd), int(s4[i] == sd), int(legs4), int(legs1)))
    return pd.DataFrame(rows, columns=["sym", "ltf", "time", "mirror", "side",
                                       "gross", "net", "stop_hit", "cost",
                                       "h1_ok", "h4_ok", "h4_legs", "h1_legs"])


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--ltf", type=int, default=15)
    a = ap.parse_args()
    out = pd.concat([run_sym(s, a.ltf) for s in SYMS], ignore_index=True)
    p = ROOT / "data" / f"swing_mtf_m{a.ltf}.parquet"
    out.to_parquet(p)
    print("mentve:", p, len(out))

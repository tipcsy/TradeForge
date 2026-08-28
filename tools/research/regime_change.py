"""VALTOZOTT-E A PIAC? — szerkezeti torések keresese 14 even.

A felhasznalo kerdese (2026-08-28): "hallomasbol tudom, hogy vannak nagy piaci
valtozasok. Ezeket meg tudjuk hatarozni? Be tudjuk bizonyitani?"

Igen, es ez nem velemeny-kerdes. Evenkent merjuk a piac SZERKEZETI jellemzoit,
es megnezzuk, hol vannak a torések. Ket haszna van:

  1. Megmondja, MELYIK evek adata releváns a mai piacra (ha 2018-ban tores volt,
     a 2013-2017-es meresek mast mernek, mint amiben ma kereskedunk).
  2. Megmagyarazhatja, miert "kopnak el" strategiak.

A LEGFONTOSABB MEROSZAM: a VARIANCIA-ARANY (variance ratio).

    VR(q) = Var(q-periodusos hozam) / (q * Var(1-periodusos hozam))

  VR > 1  -> TRENDELO (a mozgasok folytatodnak; a trendkoveto rendszerek elnek)
  VR = 1  -> veletlen bolyongas (nincs kinyerheto szerkezet)
  VR < 1  -> VISSZATERO (a mozgasok visszafordulnak)

Ha a VR az evek soran 1 fele konvergalt, az azt jelenti, hogy a piac
HATEKONYABBA valt — es ez KOZVETLENUL magyarazza, miert nem talalunk elt.
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

SYMS = ["Ger40", "UsaInd", "UsaTec", "GOLD", "USDJPY"]
TF = 5


def variance_ratio(r: np.ndarray, q: int) -> float:
    """VR(q). A hozamok NEM atfedo q-as blokkjaival (robusztusabb)."""
    r = r[np.isfinite(r)]
    n = (len(r) // q) * q
    if n < q * 20:
        return np.nan
    r = r[:n]
    v1 = np.var(r, ddof=1)
    vq = np.var(r.reshape(-1, q).sum(axis=1), ddof=1)
    return float(vq / (q * v1)) if v1 > 0 else np.nan


def yearly(sym: str) -> pd.DataFrame:
    m1 = lab.load_m1(sym)
    d = lab.resample(m1, TF)
    c = d["close"].to_numpy(float)
    h, l = d["high"].to_numpy(float), d["low"].to_numpy(float)
    v = d["volume"].to_numpy(float)
    sp = d["avg_spread"].to_numpy(float)
    r = np.concatenate([[np.nan], np.diff(np.log(c))])
    atr = lab.atr(h, l, c, 14)
    day = d.index.normalize()
    yr = d.index.year
    rows = []
    for y in sorted(set(yr)):
        m = yr == y
        if m.sum() < 2000:
            continue
        rr = r[m]
        g = pd.DataFrame({"c": c[m], "h": h[m], "l": l[m]},
                         index=d.index[m]).groupby(day[m])
        napi_rng = (g.h.max() - g.l.min()) / g.c.last()
        rows.append({
            "ev": y, "bar": int(m.sum()),
            "vol_evesitett%": float(np.nanstd(rr) * np.sqrt(252 * 288) * 100),
            "napi_range%": float(napi_rng.mean() * 100),
            "spread/ATR": float(np.nanmedian(sp[m] / np.where(atr[m] > 0,
                                                              atr[m], np.nan))),
            "tick/bar": float(np.nanmedian(v[m])),
            "AC1": float(pd.Series(rr).autocorr(1)),
            "VR2": variance_ratio(rr, 2),
            "VR6": variance_ratio(rr, 6),     # 30 perc
            "VR24": variance_ratio(rr, 24),   # 2 ora
            "VR96": variance_ratio(rr, 96),   # 8 ora
        })
    return pd.DataFrame(rows).set_index("ev")


def main():
    pd.set_option("display.width", 250)
    per = {}
    for sym in SYMS:
        print(f"   … {sym}", flush=True)
        per[sym] = yearly(sym)

    print("\n" + "=" * 78)
    print("=== VARIANCIA-ARANY EVENKENT (1,00 = veletlen bolyongas) ===")
    for q in ("VR6", "VR24", "VR96"):
        t = pd.DataFrame({s: per[s][q] for s in SYMS})
        t["ATLAG"] = t.mean(axis=1)
        print(f"\n-- {q} ({'30 perc' if q=='VR6' else '2 ora' if q=='VR24' else '8 ora'})")
        print(t.to_string(float_format=lambda x: f"{x:7.3f}"))

    print("\n" + "=" * 78)
    print("=== A TOBBI SZERKEZETI JELLEMZO (az 5 instrumentum atlaga) ===")
    keys = ["vol_evesitett%", "napi_range%", "spread/ATR", "tick/bar", "AC1"]
    t = pd.DataFrame({k: pd.DataFrame({s: per[s][k] for s in SYMS}).mean(axis=1)
                      for k in keys})
    print(t.to_string(float_format=lambda x: f"{x:9.4f}"))

    print("\n" + "=" * 78)
    print("=== VAN-E TORES? — az elso fel vs a masodik fel ===")
    rows = []
    for k in ["VR6", "VR24", "VR96", "vol_evesitett%", "spread/ATR", "tick/bar", "AC1"]:
        t = pd.DataFrame({s: per[s][k] for s in SYMS}).mean(axis=1).dropna()
        if len(t) < 6:
            continue
        h = len(t) // 2
        a, b = t.iloc[:h], t.iloc[h:]
        # Welch-t a ket fel kozott
        se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
        rows.append({"jellemzo": k, "elso_fel": float(a.mean()),
                     "masodik_fel": float(b.mean()),
                     "valtozas%": float(100 * (b.mean() - a.mean()) / abs(a.mean()))
                     if a.mean() else np.nan,
                     "t": float((b.mean() - a.mean()) / se) if se > 0 else np.nan})
    r = pd.DataFrame(rows)
    r["szignifikans"] = np.where(r.t.abs() >= 2, "IGEN", "nem")
    print(r.to_string(index=False, float_format=lambda x: f"{x:9.3f}"))

    out = ROOT / "data" / "regime_change.csv"
    pd.concat({s: per[s] for s in SYMS}, names=["sym"]).to_csv(out)
    print(f"\nreszletes tabla: {out}")


if __name__ == "__main__":
    main()

"""HOL KERESZTEZI a rendelesaramlas-jel a koltseget — es az meg napon belul van-e?

A flow.py azt mutatta, hogy a jel IC-je kicsi (max 0,022), de a KOLTSEG-KUSZOB
a horizonttal csokken: sigma ~ sqrt(h), a spread viszont allando. Tehat a hiany
zarodik. A kerdes: hol, es akkor mennyi ido van a poziciban.

    kellene IC(h) = koltseg_bp / sigma_bp(h)

Ket dolgot MERUNK, nem feltetelezunk:
  1. a tenyleges sigma(h) — nem sqrt-skalazassal becsulve, hanem szamolva
     (a valosagban a hozamok nem fuggetlenek, lasd a VR-t)
  2. a jel tenyleges IC(h) — a hosszabb horizontokon is

FIGYELEM a tobbszoros tesztelesre: 9 jellemzo x sok horizont x 5 instrumentum.
Az elfogadashoz nem eleg egy nagy |t|; MINDEN instrumentumon azonos elojel kell.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

CACHE = ROOT / "data" / "flow"
BAR_MS = 5 * 60_000
FEATS = ["imb_tick", "q_imb", "narrow", "widen", "aggr",
         "sp_mean", "sp_chg", "dur_med", "n_tick"]
# 5 perc .. 1 nap. 78 M5-bar ~ 6,5 ora = egy US-szesszio.
HOR = [1, 3, 6, 12, 24, 48, 78, 156, 288]


def forward(bar, c, h):
    """Elore hozam CSAK osszefuggo barokra (a hetvegi szakadas nem hozam)."""
    pos = np.searchsorted(bar, bar + h * BAR_MS)
    okp = np.clip(pos, 0, len(bar) - 1)
    ok = (pos < len(bar)) & (bar[okp] == bar + h * BAR_MS)
    f = np.full(len(bar), np.nan)
    f[ok] = np.log(c[okp[ok]] / c[ok])
    return f


def per_symbol(sym):
    d = pd.read_parquet(CACHE / f"{sym}_m5.parquet").sort_index()
    bar = d.index.to_numpy(np.int64)
    c = d.close2.to_numpy(float)
    cost_bp = float(np.nanmedian(d.sp_mean.to_numpy(float) / (c / 2))) * 1e4
    rows = []
    for h in HOR:
        f = forward(bar, c, h)
        m0 = np.isfinite(f)
        if m0.sum() < 2000:
            continue
        sig_bp = float(np.nanstd(f[m0])) * 1e4
        kell = cost_bp / sig_bp if sig_bp > 0 else np.nan
        for feat in FEATS:
            v = d[feat].to_numpy(float)
            m = m0 & np.isfinite(v)
            if m.sum() < 2000:
                continue
            ic = pd.Series(v[m]).corr(pd.Series(f[m]), method="spearman")
            n = int(m.sum())
            t = ic * np.sqrt((n - 2) / max(1e-12, 1 - ic ** 2))
            rows.append({"sym": sym, "jellemzo": feat, "h_bar": h,
                         "h_perc": h * 5, "n": n, "sigma_bp": sig_bp,
                         "koltseg_bp": cost_bp, "kellene_IC": kell,
                         "IC": float(ic), "t": float(t),
                         "fedezet": abs(ic) / kell if kell else np.nan})
    return pd.DataFrame(rows)


def main():
    pd.set_option("display.width", 240)
    syms = _sys.argv[1:] or ["Ger40", "UsaInd", "UsaTec", "GOLD", "USDJPY"]
    have = [s for s in syms if (CACHE / f"{s}_m5.parquet").exists()]
    if not have:
        raise SystemExit("nincs gyorsitotarazott jellemzo — futtasd elobb a flow.py-t")
    t = pd.concat([per_symbol(s) for s in have], ignore_index=True)

    print("=== A KOLTSEG-KUSZOB a horizont fuggvenyeben (instrumentumonkent) ===")
    k = t.drop_duplicates(["sym", "h_bar"]).pivot(
        index="h_perc", columns="sym", values="kellene_IC")
    print(k.to_string(float_format=lambda v: f"{v:8.4f}"))

    print("\n=== FEDEZET = |IC| / kellene_IC   (1,00 = eppen fedezi a spreadet) ===")
    best = (t.groupby(["sym", "h_perc"]).fedezet.max().unstack(0))
    print(best.to_string(float_format=lambda v: f"{v:8.3f}"))

    print("\n=== KONZISZTENCIA: azonos elojelu-e MINDEN instrumentumon? ===")
    print("   (ez az elfogadas felteteke — egy nagy |t| onmagaban semmit nem er)")
    rows = []
    for (feat, h), g in t.groupby(["jellemzo", "h_perc"]):
        if g.sym.nunique() < len(have):
            continue
        egyezo = (np.sign(g.IC) == np.sign(g.IC.iloc[0])).all()
        rows.append({"jellemzo": feat, "h_perc": h, "db": len(g),
                     "egyseges_elojel": bool(egyezo),
                     "atlag_IC": float(g.IC.mean()),
                     "atlag_fedezet": float(g.fedezet.mean()),
                     "min_fedezet": float(g.fedezet.min())})
    r = pd.DataFrame(rows)
    jo = r[r.egyseges_elojel].sort_values("atlag_fedezet", ascending=False)
    print(jo.head(20).to_string(index=False, float_format=lambda v: f"{v:8.4f}")
          if len(jo) else "   NINCS egyseges elojelu jellemzo egyetlen horizonton sem.")

    print("\n=== A DONTO SZAM: van-e barmi, ahol MINDEN instrumentumon fedezet>1? ===")
    gy = r[r.egyseges_elojel & (r.min_fedezet > 1.0)]
    print(gy.to_string(index=False, float_format=lambda v: f"{v:8.4f}")
          if len(gy) else "   NINCS. Egyetlen jellemzo sem fedezi a koltseget minden instrumentumon.")

    out = ROOT / "data" / "flow_horizon.csv"
    t.to_csv(out, index=False)
    print(f"\nteljes tabla: {out}")


if __name__ == "__main__":
    main()

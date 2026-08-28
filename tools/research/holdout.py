"""A HOLDOUT KIERTEKELESE — egyszer, a vegen.

FONTOS: ez a modul a kereses EREDMENYENEK ISMERETE NELKUL keszult (2026-08-28,
mig a search.py meg futott). Igy a merce nem igazithato utolag a talalt
mintahoz. Ez nem formalitas: ha a kuszoboket az eredmeny latasa utan allitjuk
be, a holdout elveszti minden ertelmet.

HAROM KERDES, novekvo szigorral:

  1. A legjobb minta hogyan teljesit a holdouton?
     A szokasos teszt — es onmagaban a LEGGYENGEBB bizonyitek. Egy darab
     kivalasztott elem, amit epp azert valasztottunk, mert kiugrott.

  2. A KOMPLEXITAS-LETRA: a puszta esemeny (szint 0), az esemeny+1 allapot
     (szint 1) es az esemeny+2 allapot (szint 2) kozul melyik viszi at magat?
     Ha a bonyolultabb szintek a keresesen jobbak, de a holdouton nem, akkor
     az egyuttallas nem tudast ad, hanem illesztest.

  3. A DONTO TESZT: JELEZ-E ELORE A KERESESI RANGSOR?
     Vesszuk a kereso szakaszon legjobb 100-at, es megnezzuk a holdout-
     eredmenyuk ELOSZLASAT. Osszehasonlitjuk VELETLENSZERUEN valasztott 100
     minta holdout-eloszlasaval. Ha a ketto nem kulonbozik, akkor a kereses
     zajt valogatott — barmilyen szep is a legjobb darab.

     Ez a teszt hianyzik a legtobb ilyen keresesbol, es emiatt hisznek el
     emberek nem letezo strategiakat.

ELFOGADASI FELTETEL (ELORE rogzitve):
  - a mintanak a holdouton a SAJAT (szimbolum, irany) alapszintje folott kell
    lennie, es
  - a rangkorrelacio (kereso tobblet vs holdout tobblet) szignifikansan
    pozitiv, es
  - a top-100 holdout-atlaga szignifikansan jobb a veletlen 100-enal.
  Barmelyik hianya = nincs bizonyitott talalat.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

import signal_lib
from search import MIN_N, VAGAS, _t

TOP = 100


def _maszk(cimke: str, A: dict, E: dict) -> np.ndarray:
    reszek = [r.strip() for r in cimke.split(" + ")]
    m = E[reszek[0]].copy()
    for r in reszek[1:]:
        m &= A[r]
    return m


def ertekel(sym: str):
    t = pd.read_parquet(ROOT / "data" / f"search_{sym}.parquet")
    o = pd.read_parquet(ROOT / "data" / "outcomes" / f"{sym}.parquet")
    ido = pd.DatetimeIndex(o["ido"])
    kereso = np.asarray(ido < pd.Timestamp(VAGAS, tz=ido.tz))
    hold = ~kereso
    A, E = signal_lib.build(sym, ido)
    R = {"long": o["long"].to_numpy(float), "short": o["short"].to_numpy(float)}
    alap_h = {k: float(np.nanmean(v[hold])) for k, v in R.items()}
    print(f"\n=== {sym} — HOLDOUT ({hold.sum():,} gyertya, {VAGAS}-tol) ===")
    print(f"   holdout alapszint: long {alap_h['long']:+.4f}  "
          f"short {alap_h['short']:+.4f}")

    # a holdout-eredmeny kiszamitasa MINDEN jeloltre (egyszer)
    hr, hn = [], []
    for cimke, irany in zip(t.mintazat, t.irany):
        try:
            m = _maszk(cimke, A, E) & hold
        except KeyError:
            hr.append(np.nan); hn.append(0); continue
        idx = np.flatnonzero(m)
        if len(idx) < MIN_N:
            hr.append(np.nan); hn.append(len(idx)); continue
        mu, _, nn = _t(R[irany][idx])
        hr.append(mu); hn.append(nn)
    t["R_h"] = hr
    t["n_h"] = hn
    t["tobblet_h"] = t.R_h - t.irany.map(alap_h)
    t = t[np.isfinite(t.R_h)].copy()
    print(f"   {len(t):,} jelolt ertekelheto a holdouton is")

    # ── 1. a legjobb ────────────────────────────────────────────────────────
    print("\n--- 1. A kereso szakasz legjobb 5 mintaja a HOLDOUTON ---")
    top5 = t.nlargest(5, "tobblet_k")
    print(top5[["szint", "irany", "n_k", "tobblet_k", "n_h", "tobblet_h"]]
          .to_string(index=False, float_format=lambda v: f"{v:+.4f}"))
    for c in top5.mintazat.head(3):
        print(f"      {c}")

    # ── 2. komplexitas-letra ────────────────────────────────────────────────
    print("\n--- 2. KOMPLEXITAS-LETRA: melyik szint viszi at magat? ---")
    print(f"   {'szint':>6s} {'db':>7s} {'kereso tobblet':>15s} "
          f"{'holdout tobblet':>16s} {'top20 holdout':>14s}")
    for sz in sorted(t.szint.unique()):
        d = t[t.szint == sz]
        top = d.nlargest(min(20, len(d)), "tobblet_k")
        print(f"   {sz:>6d} {len(d):>7,} {d.tobblet_k.mean():>+15.4f} "
              f"{d.tobblet_h.mean():>+16.4f} {top.tobblet_h.mean():>+14.4f}")
    print("   -> ha a magasabb szint a keresesen jobb, a holdouton nem: ILLESZTES")

    # ── 3. a donto teszt ────────────────────────────────────────────────────
    print("\n--- 3. JELEZ-E ELORE A KERESESI RANGSOR? ---")
    rho = t.tobblet_k.corr(t.tobblet_h, method="spearman")
    n = len(t)
    tr = rho * np.sqrt((n - 2) / max(1e-12, 1 - rho ** 2))
    print(f"   rangkorrelacio (kereso tobblet vs holdout tobblet): "
          f"{rho:+.4f}  t={tr:+.1f}  n={n:,}")

    top = t.nlargest(TOP, "tobblet_k").tobblet_h.to_numpy(float)
    rng = np.random.default_rng(0)
    veletlen = np.array([t.tobblet_h.sample(TOP, random_state=int(s)).mean()
                         for s in rng.integers(0, 10**6, 500)])
    p = float((veletlen >= top.mean()).mean())
    print(f"   a KERESO top-{TOP} atlagos holdout-tobblete: {top.mean():+.4f}")
    print(f"   veletlenszeru {TOP} minta ugyanez:            "
          f"{veletlen.mean():+.4f} (szoras {veletlen.std():.4f})")
    print(f"   p-ertek (a veletlen ennyiszer erte el): {p:.4f}")

    # ── itelet ──────────────────────────────────────────────────────────────
    f1 = top.mean() > 0
    f2 = tr > 2
    f3 = p < 0.05
    print("\n--- ITELET (mindharom feltetel kell) ---")
    print(f"   a top-{TOP} holdout-tobblete pozitiv:      {'IGEN' if f1 else 'NEM'}")
    print(f"   a rangsor elorejelzo (t>2):               {'IGEN' if f2 else 'NEM'}")
    print(f"   a top-{TOP} veri a veletlent (p<0,05):     {'IGEN' if f3 else 'NEM'}")
    print(f"   => {'TALALAT — erdemes tovabbvinni' if (f1 and f2 and f3) else 'NINCS bizonyitott talalat'}")
    t.to_parquet(ROOT / "data" / f"holdout_{sym}.parquet", index=False)
    return t


def main():
    for sym in (_sys.argv[1:] or ["UsaTec"]):
        if not (ROOT / "data" / f"search_{sym}.parquet").exists():
            print(f"({sym}: nincs kereses-eredmeny)")
            continue
        ertekel(sym)


if __name__ == "__main__":
    main()

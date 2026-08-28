"""HOLDOUT-OS KERESES — a felhasznalo altal kert milliós kombinacio-ter,
tisztessegesen kiertekelve.

A felhasznalo kifogasa (2026-08-28): "40 indikator x 6 idosik x parameterek x
egyuttallas = tobb millios kombinacio. Ebbol hogy jott neked az, hogy az
indikatorok nincsenek hatassal?" — igaza volt: 23 nyers keresztezest neztem meg
egyetlen idosikon.

MIERT VESZELYES A NAGY KERESES, es hogyan lehet megis tisztesseges:

  A veszely: egymillio kombinaciobol a legjobb MINDIG ragyogoan nez ki. Ha
  10^6 fuggetlen szabalyt probalunk, a legjobb varhatoan ~4,9 szigmara lesz
  a nullatol PUSZTA VELETLENBOL. A "t>3" kuszob itt semmit nem er.

  A megoldas EGY erintetlen HOLDOUT. A kereses CSAK a korai szakaszt latja.
  A kesoi szakaszt egyszer nezzuk meg, a vegen. Ez a szam akkor is torzitatlan,
  ha kozben tizmillio kombinaciot probaltunk — mert a holdout nem vett reszt a
  valasztasban.

  ES egy erosebb teszt, ami a legtobb ilyen keresesbol hianyzik: nem eleg a
  legjobbat megnezni a holdouton. Azt kell megnezni, hogy a KERESESI RANGSOR
  EGYALTALAN JELEZ-E ELORE. Ha a top-100 holdout-eloszlasa nem kulonbozik a
  VELETLENSZERUEN valasztott 100 kombinacioetol, akkor a kereses zajt talalt,
  barmilyen szep is a legjobb darab.

KET TOVABBI VEDELEM:

  1. AZ ALAPSZINT NEM NULLA. Egy veletlen M5 gyertyan long-ba belepve UsaTec-en
     +0,0128 R az eredmeny (sodrodas). Ezert minden szabalyt a SAJAT
     (szimbolum, irany) alapszintjehez merunk, nem nullahoz — kulonben minden
     long szabaly nyeronek latszik.

  2. MINDKET IRANY. Az elfogadashoz a mintazatnak long ES short oldalon is a
     sajat alapszintje folott kell teljesitenie.
"""

from __future__ import annotations

import itertools
import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

import signal_lib

VAGAS = "2023-01-01"           # ez elott: kereses. ez utan: ERINTETLEN holdout.
MIN_N = 300                    # ennyi kotes alatt nem ertekelunk


def _t(v):
    v = v[np.isfinite(v)]
    if len(v) < 3:
        return np.nan, np.nan, 0
    s = v.std(ddof=1)
    return v.mean(), (v.mean() / (s / np.sqrt(len(v))) if s > 0 else np.nan), len(v)


def fuss(sym: str, max_par: int = 400000):
    o = pd.read_parquet(ROOT / "data" / "outcomes" / f"{sym}.parquet")
    ido = pd.DatetimeIndex(o["ido"])
    kereso = np.asarray(ido < pd.Timestamp(VAGAS, tz=ido.tz))
    hold = ~kereso
    print(f"=== {sym}: {kereso.sum():,} kereso / {hold.sum():,} holdout gyertya ===")
    if kereso.sum() < 20000 or hold.sum() < 20000:
        print("   (tul rovid szakasz, kihagyva)")
        return None

    A, E = signal_lib.build(sym, ido)
    an, en = sorted(A), sorted(E)
    print(f"   {len(an)} allapot, {len(en)} esemeny", flush=True)

    R = {"long": o["long"].to_numpy(float), "short": o["short"].to_numpy(float)}
    # ALAPSZINT: a felteteles nelkuli varhato ertek a KERESO szakaszon
    alap = {k: np.nanmean(v[kereso]) for k, v in R.items()}
    print(f"   alapszint (kereso): long {alap['long']:+.4f}  "
          f"short {alap['short']:+.4f}")

    Aa = {k: A[k] for k in an}
    Ea = {k: E[k] for k in en}
    sorok = []
    rng = np.random.default_rng(0)

    def ertekel(maszk, cimke, szint):
        mk = maszk & kereso
        idx = np.flatnonzero(mk)
        if len(idx) < MIN_N:
            return
        for irany in ("long", "short"):
            mu, tt, nn = _t(R[irany][idx])
            if nn < MIN_N:
                return
            sorok.append({"mintazat": cimke, "szint": szint, "irany": irany,
                          "n_k": nn, "R_k": mu, "t_k": tt,
                          "tobblet_k": mu - alap[irany]})

    # ── KOMPLEXITAS-LETRA ───────────────────────────────────────────────────
    # 0: puszta esemeny | 1: esemeny + 1 allapot | 2: esemeny + 2 allapot
    # Igy a holdouton latszik, hogy az EGYUTTALLAS javit-e, vagy csak illeszt.
    print("   szint 0: puszta esemenyek", flush=True)
    for e in en:
        ertekel(Ea[e], e, 0)

    print(f"   szint 1: esemeny x allapot ({len(en)*len(an):,})", flush=True)
    for ei, e in enumerate(en, 1):
        me = Ea[e]
        for a in an:
            ertekel(me & Aa[a], f"{e} + {a}", 1)
        if ei % 40 == 0:
            print(f"      {ei}/{len(en)}, {len(sorok):,} jelolt", flush=True)

    parok = list(itertools.combinations(an, 2))
    cel = max(1, max_par // max(1, len(en)))
    if len(parok) > cel:
        parok = [parok[i] for i in rng.choice(len(parok), size=cel, replace=False)]
    print(f"   szint 2: esemeny x allapot-par ({len(en)*len(parok):,})", flush=True)
    for ei, e in enumerate(en, 1):
        me = Ea[e]
        for a1, a2 in parok:
            ertekel(me & Aa[a1] & Aa[a2], f"{e} + {a1} + {a2}", 2)
        if ei % 20 == 0:
            print(f"      {ei}/{len(en)}, {len(sorok):,} jelolt", flush=True)

    t = pd.DataFrame(sorok)
    if t.empty:
        print("   nincs ertekelheto jelolt")
        return None
    t["sym"] = sym
    dst = ROOT / "data" / f"search_{sym}.parquet"
    t.to_parquet(dst, index=False)
    print(f"\n   {len(t):,} jelolt elmentve: {dst}")
    print("   jeloltek szintenkent:")
    print(t.groupby(["szint", "irany"]).size().to_string())
    print("   a KERESO szakasz legjobb 5 tobblete:")
    print(t.nlargest(5, "tobblet_k")[["mintazat", "szint", "irany",
                                      "n_k", "R_k", "tobblet_k"]]
          .to_string(index=False, float_format=lambda v: f"{v:+.4f}"))
    return t


def main():
    for sym in (_sys.argv[1:] or ["UsaTec", "UsaInd"]):
        if not (ROOT / "data" / "outcomes" / f"{sym}.parquet").exists():
            print(f"({sym}: nincs kimenet-gyorsitotar)")
            continue
        fuss(sym)


if __name__ == "__main__":
    main()

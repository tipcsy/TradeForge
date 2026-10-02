"""Hany M15-os hullam van egy H1-es labban? — 2026-10-02.

A felhasznalo kerdese: a H1-trend 1., 2., 3. ... labjaban hany M15-os hullam van.

Definiciok (szigoru, pivot k=3, a swing_trend_length.leg_records szerint):
  * H1-lab: az alapjat ado ellen-swingtol (HL) az uj HH-ig (ill. tukor).
  * M15-hullam a H1-labon belul, ket szamlalas:
      - "M15 csucs": a lab idoablakaba eso igazolt M15 swing-csucsok szama
        (emelkedo labnal; esonel volgyek) — a nyers hullamszam;
      - "M15 trend-lab": az ablakba eso, AZONOS iranyu szigoru M15 labak (HH+HL).
  * Kiegeszito kerdes: a hullamszam elore jelzi-e, hogy jon-e meg H1-lab?
NULL: az M15-gyertyak OSSZEKEVERVE, a H1 ezekbol osszerakva (4 M15 = 1 H1) —
igy a beagyazas konzisztens, de nincs valodi sorrendi szerkezet.
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
from swing_mtf import SYMS, pivots, K
from swing_trend_length import leg_records, shuffled, signflip


def to_h1(m15: pd.DataFrame, minutes: int = 60) -> pd.DataFrame:
    return m15.resample(f"{minutes}min", label="left", closed="left").agg(
        high=("high", "max"), low=("low", "min"), close=("close", "last")).dropna()


def nested(m15: pd.DataFrame, h1: pd.DataFrame, hi_min: int = 60):
    L1 = leg_records(h1)
    L15 = leg_records(m15)
    ih, il = pivots(m15["high"].to_numpy(float), m15["low"].to_numpy(float), K)
    t15 = m15.index
    piv = {1: np.sort(t15[ih].to_numpy()), -1: np.sort(t15[il].to_numpy())}
    legt = {dr: np.sort(L15.loc[L15.dir == dr, "time"].to_numpy()) for dr in (1, -1)}
    # a H1 bar cimkeje a nyitas: a lab ablaka [base bar nyitasa, extr bar zarasa)
    t0 = L1.base_time.to_numpy()
    t1 = (L1.time + pd.Timedelta(minutes=hi_min)).to_numpy()
    out = L1.copy()
    for col, src in (("m15_csucs", piv), ("m15_lab", legt)):
        v = np.zeros(len(L1), int)
        for dr in (1, -1):
            m = (L1.dir == dr).to_numpy()
            v[m] = (np.searchsorted(src[dr], t1[m], side="left")
                    - np.searchsorted(src[dr], t0[m], side="left"))
        out[col] = v
    out["hours"] = (L1.time - L1.base_time).dt.total_seconds() / 3600 + hi_min / 60
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--lo", type=int, default=15)
    ap.add_argument("--hi", type=int, default=60)
    arg = ap.parse_args()
    rows = []
    for s in SYMS:
        m15 = lab.resample(lab.load_m1(s), arg.lo)
        for src, mm in (("piac", m15), ("kevert", shuffled(m15)), ("elojel", signflip(m15))):
            r = nested(mm, to_h1(mm, arg.hi), arg.hi)
            r["sym"], r["src"] = s, src
            rows.append(r)
        print(s, flush=True)
    out = pd.concat(rows, ignore_index=True)
    name = "swing_nested.parquet" if (arg.lo, arg.hi) == (15, 60) else f"swing_nested_{arg.lo}_{arg.hi}.parquet"
    out.to_parquet(ROOT / "data" / name)
    print("kesz", len(out))

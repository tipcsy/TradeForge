"""CSILLA — A LÁNC MÉRÉSE (H1 szerkezet-törés → pipa → M15 counter-trend belépők).

A szabályt a felhasználóval 2026-09-23-án raktuk össze, lépésről lépésre, a
Ger40 2026-01-26..28-i példáján (a „Csilla beszállója — mérés" jegyzet 13.
szakasza). A szabály a `strategies/csilla_rules`-ban él — ez a szkript csak
MÉRI; a stratégia-modul ugyanazt a három függvényt hívja majd.

    1. JELZÉS   `own_swing_events`  — a felső keret a saját swingjét töri
    ÉRVÉNYES    amíg az ár nem zár a törés előtti szélsőérték túloldalára
    2. JELZÉS   `pipa_events`       — a korrekciót elnyelő gyertya
    BELÉPŐK     `counter_entries`   — az alsó kereten, korrekciónként egy

⚠ ELŐRE RÖGZÍTETT KAPCSOLÓK (a mérés előtt, a felhasználó szavaiból):
    belepo_mod  `varj_pirosra` (alap) | `leszuras` | `piros_zaras`
    korr_min    3 (alap) | 4 | 5
    veg_mod     `h1` (alap: csak a H1-es érvénytelenítés zár)
A többi paramétert NEM hangoljuk ebben a körben.

Futtatás:
    python tools/research/csilla_chain.py                 # alap, 8 instrumentum
    python tools/research/csilla_chain.py --mod leszuras --korr 4
    python tools/research/csilla_chain.py --sym Ger40 --tol 2024-01-01
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "research"))

import lab                                      # noqa: E402
from strategies import csilla_rules as sw       # noqa: E402

SYMS = ["GOLD", "USDJPY", "UsaInd", "UsaTec", "Ger40", "EURUSD", "EURJPY", "UK100"]
BE_AT_R, TRAIL_R, MAX_HOLD_NAP = 0.67, 2.0, 5


def spread_median(m1: pd.DataFrame) -> float:
    """A pár 12 havi spread-mediánja ÁRBAN (a friss gyertyákban NaN lehet)."""
    s = m1["avg_spread"].dropna()
    if not len(s):
        return 0.0
    return float(s[s.index >= s.index.max() - pd.Timedelta(days=365)].median())


def egy_par(sym: str, P: dict, tol: str | None, ig: str | None) -> tuple:
    m1 = lab.load_m1(sym)
    if tol:
        m1 = m1[m1.index >= pd.Timestamp(tol, tz="UTC")]
    if ig:
        m1 = m1[m1.index < pd.Timestamp(ig, tz="UTC")]
    if len(m1) < 5000:
        return None
    hi = sw.resample(m1, P["hi_tf"])
    lo = m1 if P["lo_tf"] <= 1 else sw.resample(m1, P["lo_tf"])
    sp = spread_median(m1)
    su = sw.chain_setups(hi, P)
    et = sw.counter_entries(lo, su, P, spread=sp)
    if not len(et):
        return None
    # ⚠ EGY BELÉPŐ EGY GYERTYÁRA. A setupok napokig élnek és átfedik egymást,
    # tehát ugyanarra a barra több setup is adna jelet; a motor sem nyit
    # egyszerre többet ugyanarra a párra.
    et = et.sort_values("i").drop_duplicates("i", keep="first")
    ps = float(lab.PAIRS[sym]["point_size"])
    idx = et.i.to_numpy(int)
    side = et.dir.to_numpy(int)
    slp = (et.sl_abs.to_numpy(float) / ps)
    tr = lab.simulate(lo, idx, side, slp, np.zeros(len(et)), point_size=ps,
                      max_hold=MAX_HOLD_NAP * 1440 // max(1, P["lo_tf"]),
                      be_at_r=BE_AT_R, trail_r=TRAIL_R, one_at_a_time=True,
                      pair_cfg=lab.PAIRS[sym])
    if not len(tr):
        return None
    R = tr["r"]
    ev = pd.DatetimeIndex(lo.index[tr["i_open"]]).year
    evente = pd.Series(R).groupby(ev).mean()
    t = float(R.mean() / (R.std(ddof=1) / np.sqrt(len(R)))) if len(R) > 1 else 0.0
    return dict(sym=sym, setup=len(su), jel=len(et), n=len(R),
                R=float(R.mean()), sumR=float(R.sum()), t=t,
                nyero=float((R > 0).mean()),
                ev_poz=int((evente > 0).sum()), ev_db=int(len(evente)),
                sl_med=float(np.median(et.sl_abs)), spread=sp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sym", nargs="*", default=SYMS)
    ap.add_argument("--mod", default="varj_pirosra",
                    choices=("varj_pirosra", "leszuras", "piros_zaras"))
    ap.add_argument("--korr", type=int, default=3)
    ap.add_argument("--tf-pair", default="H1-M15", choices=sorted(sw.TF_PAIRS))
    ap.add_argument("--tol", default=None)
    ap.add_argument("--ig", default=None)
    a = ap.parse_args()
    P = sw.with_tf_pair(dict(sw.DEFAULTS, tf_pair=a.tf_pair,
                             belepo_mod=a.mod, korr_min=a.korr))
    print(f"CSILLA-LANC — tf_pair={a.tf_pair}  belepo={a.mod}  korr_min={a.korr}"
          f"  (BE {BE_AT_R} R, csuszo {TRAIL_R} R, celar nincs, max {MAX_HOLD_NAP} nap)\n")
    fej = (f"   {'par':8} {'setup':>6} {'jel':>7} {'kotes':>7} {'R/kotes':>9} "
           f"{'sum R':>9} {'t':>6} {'nyero':>7} {'ev+':>6} {'SL med':>8}")
    print(fej)
    sorok = []
    for sym in a.sym:
        try:
            r = egy_par(sym, P, a.tol, a.ig)
        except Exception as ex:                       # pragma: no cover
            print(f"   {sym:8} HIBA: {type(ex).__name__}: {ex}")
            continue
        if r is None:
            print(f"   {sym:8} (nincs eleg adat / jel)")
            continue
        sorok.append(r)
        print(f"   {r['sym']:8} {r['setup']:6d} {r['jel']:7d} {r['n']:7d} "
              f"{r['R']:+9.4f} {r['sumR']:+9.1f} {r['t']:+6.2f} "
              f"{100*r['nyero']:6.0f}% {r['ev_poz']:3d}/{r['ev_db']:<2d} "
              f"{r['sl_med']:8.1f}")
    if not sorok:
        return
    n = sum(x["n"] for x in sorok)
    sR = sum(x["sumR"] for x in sorok)
    poz = sum(1 for x in sorok if x["R"] > 0)
    print(f"\n   OSSZEVONT: n={n:,}  R/kotes={sR/n:+.4f}  sum R={sR:+.1f}  "
          f"pozitiv par: {poz}/{len(sorok)}")


if __name__ == "__main__":
    main()

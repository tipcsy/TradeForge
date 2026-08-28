"""KAPU-MERES: mennyit ad hozza minden egyes kapu a belepo varhato ertekehez?

A merce: R/kotes, a belepeskori spread ARBAN levonva, ido-alapu kilepessel
(nincs SL/TP ut-fuggoseg -> tisztan a jel + a kapu latszik). SL = 1,5 x ATR(M15),
ez adja az R-t. IS/OOS bontas.

Amit ki kell derulnie:
  * a NYERS szabaly varhato erteke (kapu nelkul)  -> ez volt eddig a merésem
  * kapunkent a DELTA                              -> ezt hagytam ki
  * az OSSZES kapu egyszerre                       -> a tenyleges eles beallitas
"""
from __future__ import annotations

# A repobol futtathato: a projekt gyokere ES a testvermodulok a sys.path-ra.
import sys as _sys
from pathlib import Path as _Path
ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

import gates_lab as GL
import rules as R

SYMS = ["UsaTec", "Ger40", "UsaInd", "GOLD", "UK100", "Fra40", "EURUSD", "EURJPY"]
HOLD = 16                      # M15 bar = 4 ora
SL_ATR = 1.5

RULES = {
    "3lepeses_fordulo": R.three_step,
    "1lepes_(csak tores)": R.three_step_partial,
    "donchian48_tores": R.donchian,
    "donchian48_fade": lambda C: R.donchian(C, fade=True),
    "zfade2.0": R.zfade,
}

GATES = ["piac", "piac_szigoru", "spread", "egyuttallas", "volatilitas",
         "lendulet", "szep_chart"]


def outcome(C, idx, side, hold=HOLD):
    """R/kotes ido-alapu kilepessel, a belepeskori spreadet ARBAN levonva."""
    c, atr, ps = C["c"], C["atr"], C["ps"]
    n = len(c)
    ok = (idx + hold < n) & np.isfinite(atr[idx])
    i, s = idx[ok], side[ok]
    if len(i) == 0:
        return None, None, None
    gross = s * (c[i + hold] - c[i])
    net = gross - C["sp_pts"][i] * ps
    r = net / (SL_ATR * atr[i])
    return i, s, r


def gate_mask_for(C, i, s, gate):
    g = C["gates"]
    if gate == "egyuttallas":
        # iranyt is ad: csak az EGYUTTALLASSAL AZONOS iranyu belepo mehet
        return g["_tf_dir"][i] == s
    if gate == "szep_chart":
        # a "szep chart" iranyt is hordoz (a harmados pozicio elojele)
        return (g["szep_chart"][i]) & (np.sign(g["_pos"][i]) == s)
    return g[gate][i]


def main():
    rows = []
    for sym in SYMS:
        C = GL.build(sym)
        ism = C["is_m"]
        for rname, fn in RULES.items():
            out = fn(C)
            idx, side = out[0], out[1]
            if len(idx) < 60:
                continue
            i, s, r = outcome(C, idx, side)
            if r is None or len(r) < 60:
                continue
            masks = {"— nyers —": np.ones(len(i), bool)}
            for gname in GATES:
                masks[gname] = gate_mask_for(C, i, s, gname)
            allm = np.ones(len(i), bool)
            for gname in GATES:
                if gname == "piac_szigoru":
                    continue
                allm &= gate_mask_for(C, i, s, gname)
            masks["MIND EGYUTT"] = allm
            for gname, m in masks.items():
                for tag, per in (("IS", ism[i]), ("OOS", ~ism[i])):
                    sel = m & per & np.isfinite(r)
                    if sel.sum() < 15:
                        continue
                    rows.append({"sym": sym, "szabaly": rname, "kapu": gname,
                                 "szak": tag, "n": int(sel.sum()),
                                 "R": float(r[sel].mean())})
    df = pd.DataFrame(rows)
    df.to_csv("gates_results.csv", index=False)
    pd.set_option("display.width", 240)

    piv = (df.pivot_table(index=["szabaly", "kapu"], columns="szak",
                          values="R", aggfunc="mean")
             .join(df.pivot_table(index=["szabaly", "kapu"], columns="szak",
                                  values="n", aggfunc="sum"), rsuffix="_n"))
    piv["min"] = piv[["IS", "OOS"]].min(axis=1)
    print("== R/kotes szabalyonkent es kapunkent (8 instrumentum atlaga) ==")
    print(piv.sort_values(["szabaly", "min"], ascending=[True, False])
             .to_string(float_format=lambda x: f"{x:8.4f}"))

    print()
    print("== a kapuk DELTA-ja a nyershez kepest ==")
    base = df[df.kapu == "— nyers —"].groupby(["sym", "szabaly", "szak"])["R"].mean()
    d2 = df[df.kapu != "— nyers —"].copy()
    d2["delta"] = d2.apply(
        lambda x: x["R"] - base.get((x["sym"], x["szabaly"], x["szak"]), np.nan),
        axis=1)
    g = (d2.groupby(["kapu", "szak"])["delta"]
           .agg(["mean", lambda s: 100 * (s > 0).mean(), "count"]))
    g.columns = ["atlag_delta", "javit%", "eset"]
    print(g.unstack("szak").to_string(float_format=lambda x: f"{x:8.4f}"))


if __name__ == "__main__":
    main()

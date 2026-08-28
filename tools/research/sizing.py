"""FELTETELES MERETEZES — "milyenek az utviszonyok?"

A felhasznalo kepe (2026-08-28): veroferyes napsutesben 300 m latotavval mas
sebesseggel mesz, mint kodben, jeges uton. A sebesseg = a POZICIO MERETE, az
utviszonyok = mennyire trendel/"szep" a piac.

Ez strukturalisan mas, mint amit eddig mertem. A kapukat BINARIS szurokent
neztem (kereskedj / ne). A meretezes FOLYTONOS, es — a stop-szabalyokkal
ellentetben — TUDJA mozgatni a varhato erteket, ha az el feltetelenkent elter:

    E[sulyozott] = E[w(x) * R(x)]  -> ha w korrelal R varhato ertekevel, nyerunk.

Illeszkedik egy korabbi lelethez is: a volatilitas-jellemzok azt joslak meg,
hogy MIKOR mozdul a piac, nem hogy MERRE. Irany-elorejelzesre hasznalhatatlanok
voltak — meretezesre pont ez kell.

Modszer:
  1. minden kotesnel feljegyezzuk a BELEPESKORI allapot-valtozokat,
  2. kvintilisenkent megnezzuk az atlagos R-t (+ hany EVBEN pozitiv a
     felso-also kulonbseg — kulonben ez a tulillesztes melegagya),
  3. a konzisztens valtozokbol meretezo fuggvenyt epitunk, es megmerjuk a
     SULYOZOTT osszesitett R-t az egyenletes meretezeshez kepest.
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

import lab
import gates_lab as GL
import run_gates as RG
import rules_long as RL
import build_pyramid as BP
import exp_struct as XS
from core import regime as _regime

SYMS = BP.SYMS
GATES = BP.GATES


def _nights(t0, t1, wd3):
    d, n = t0.normalize(), 0.0
    while d < t1.normalize():
        d += pd.Timedelta(days=1)
        n += 3.0 if d.weekday() == wd3 else 1.0
    return n


def collect(max_adds=0, trigger="r_fixed", r_step=1.0, sl_atr=2.5, be_r=1.0):
    """Kotesek + a BELEPESKORI allapot-valtozok, SWAPPAL."""
    out = []
    for sym in SYMS:
        C = GL.build(sym)
        i, s = RL.donchian(C, 96)
        m = np.ones(len(i), bool)
        for g in GATES:
            m &= RG.gate_mask_for(C, i, s, g)
        i, s = i[m], s[m]
        d = BP.simulate_package(C, i, s, sl_atr=sl_atr, be_r=be_r,
                                max_adds=max_adds, trigger=trigger, r_step=r_step)
        if not len(d):
            continue
        # swap
        pc = lab.PAIRS[sym]
        wd3 = int(pc.get("swap_3x_weekday", 2))
        pv1 = pc["pv1_point"]
        idx = C["d"].index
        atr = C["atr"]
        sw = np.zeros(len(d))
        pos = idx.get_indexer(d.t)
        for k in range(len(d)):
            j0 = pos[k]
            j1 = min(j0 + int(d.tart.iloc[k]), len(idx) - 1)
            nn = _nights(d.t.iloc[k], idx[j1], wd3)
            if nn <= 0:
                continue
            per = (pc.get("swap_long_per_lot", 0.0) if s[k] > 0
                   else pc.get("swap_short_per_lot", 0.0))
            Rp = sl_atr * atr[j0] / C["ps"]
            sw[k] = nn * per * d.lots.iloc[k] / (Rp * pv1) if Rp > 0 else 0.0
        d["R"] = d.R + sw

        # ── AZ "UTVISZONYOK" a belepeskor ──────────────────────────────────
        g = C["gates"]
        F, _a, _c = XS.structure_features(C["d"])
        feat = _regime.features(C["d"][["high", "low", "close"]])
        base = pd.Series(atr).rolling(2000, min_periods=200).mean().bfill().to_numpy()
        r2 = np.nanmax(np.vstack([F["r2_up"], F["r2_dn"]]), axis=0)
        cc = C["c"]
        ma = lab.sma(cc, 200)
        d["r2"] = r2[pos]                                   # trendvonal-illeszkedes
        d["pos3"] = np.abs(F["pos_robust"])[pos]            # harmados pozicio (|.|)
        d["ma_tav"] = np.abs((cc - ma) / atr)[pos]          # MA200-tavolsag ATR-ben
        d["atr_arany"] = (atr / np.where(base > 0, base, np.nan))[pos]
        d["lendulet"] = np.abs(g["_rpm"])[pos]              # |fordulatszam|
        d["adx"] = feat["adx"].to_numpy()[pos]              # trend-erosseg
        d["tf_egyez"] = (g["_tf_dir"][pos] == s).astype(float)
        d["spread_atr"] = (C["sp_pts"] * C["ps"] / atr)[pos]
        d["sym"] = sym
        out.append(d)
    return pd.concat(out, ignore_index=True)


VARS = ["r2", "pos3", "ma_tav", "atr_arany", "lendulet", "adx", "spread_atr"]


def quintiles(df, var, q=5):
    x = df[var]
    ok = np.isfinite(x)
    d = df[ok].copy()
    try:
        d["b"] = pd.qcut(d[var].rank(method="first"), q, labels=False)
    except ValueError:
        return None
    g = d.groupby("b").R.agg(n="size", R="mean")
    # a felso vs also kvintilis kulonbsege EVENKENT — ez a konzisztencia-proba
    ev = d.groupby([d.t.dt.year, "b"]).R.mean().unstack()
    if 0 in ev and (q - 1) in ev:
        sp = (ev[q - 1] - ev[0]).dropna()
        konz = f"{int((sp > 0).sum())}/{len(sp)}"
        spread = float(g.R.iloc[-1] - g.R.iloc[0])
    else:
        konz, spread = "-", np.nan
    return {"valtozo": var, "also_R": float(g.R.iloc[0]),
            "felso_R": float(g.R.iloc[-1]), "kulonbseg": spread,
            "ev_konz": konz,
            **{f"q{i+1}": float(g.R.iloc[i]) for i in range(len(g))}}


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    print("adatgyujtes…", flush=True)
    df = collect(max_adds=0)               # eloszor epites NELKUL, tisztan
    df.to_parquet("sizing_trades.parquet")
    print(f"{len(df):,} kotes, atlag R={df.R.mean():+.4f}\n")

    rows = [quintiles(df, v) for v in VARS]
    rows = [r for r in rows if r]
    t = pd.DataFrame(rows).sort_values("kulonbseg", ascending=False)
    print("=== ATLAGOS R KVINTILISENKENT (q1 = legrosszabb utviszony) ===")
    print(t.to_string(index=False, float_format=lambda x: f"{x:8.4f}"))

    print("\n=== MERETEZES: mennyit er, ha a jo utviszonyra nagyobbat nyitunk ===")
    res = []
    uni = df.R.mean()
    res.append({"meretezes": "EGYENLETES (mai)", "sulyozott_R": uni,
                "atl_meret": 1.0, "ev_poz": "-"})
    for v in VARS:
        x = df[v].to_numpy(dtype=float)
        ok = np.isfinite(x)
        if ok.sum() < 1000:
            continue
        r = pd.Series(x[ok]).rank(pct=True).to_numpy()      # 0..1 percentilis
        for lo, hi in ((0.5, 1.5), (0.25, 1.75)):
            w = lo + (hi - lo) * r                          # linearis meret-savok
            rr = df.R.to_numpy()[ok]
            sw = float((w * rr).sum() / w.sum())            # SULYOZOTT atlag
            d2 = df[ok].copy()
            d2["wR"] = w * rr
            d2["w"] = w
            ev = d2.groupby(d2.t.dt.year).apply(
                lambda z: z.wR.sum() / z.w.sum(), include_groups=False)
            res.append({"meretezes": f"{v} szerint ({lo}–{hi}x)",
                        "sulyozott_R": sw, "atl_meret": float(w.mean()),
                        "ev_poz": f"{int((ev > 0).sum())}/{len(ev)}"})
    r = pd.DataFrame(res).sort_values("sulyozott_R", ascending=False)
    print(r.to_string(index=False, float_format=lambda x: f"{x:8.4f}"))

"""KOCKAZATCSOKKENTES merese: megmenti-e a Pajzs/breakeven a rendszert?

A MAE/MFE azt mutatta, hogy a stopba futo kotesek FELE eloszor +0,5R-ig ment.
A kerdes: ha ezeket breakeven-nel nullazzuk, javul-e a varhato ertek?

⚠ Elmeleti figyelmeztetes, amit a merés elott ki kell mondani: ha a belepo
IRANY-ELE nulla (MFE/MAE = 1,036 -> majdnem az), akkor SEMMILYEN stop/cel/
breakeven/trailing szabaly nem tud pozitiv varhato erteket csinalni. Ez nem
velemeny, hanem az opcionalis megallitas tetele martingal folyamatra: barmely
megallitasi szabaly varhato erteke ugyanaz — minusz a koltseg. A kimenet-kezeles
a P&L ELOSZLASAT rajzolja at (tobb kis nyero, kevesebb nagy vesztes), nem a
kozepet.

Amit tehat merunk: MENNYIRE rajzolja at, es hogy a koltseg-oldalon nyer-e
valamit (a korabban zart kotes kevesebb swapot fizet).
"""
from __future__ import annotations

# A repobol futtathato: a projekt gyokere ES a testvermodulok a sys.path-ra.
import sys as _sys
from pathlib import Path as _Path
ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import itertools
import numpy as np
import pandas as pd

import lab
import gates_lab as GL
import run_gates as RG
import rules_long as RL

SYMS = ["Ger40", "UsaInd", "UsaTec", "GOLD", "USDJPY"]
GATES = ["spread", "volatilitas", "lendulet", "piac", "egyuttallas", "szep_chart"]
MAXH = 96


def _nights(t0, t1, wd3):
    d, n = t0.normalize(), 0.0
    while d < t1.normalize():
        d = d + pd.Timedelta(days=1)
        n += 3.0 if d.weekday() == wd3 else 1.0
    return n


def run(sl_atr, rr, be_at_r=0.0, trail_r=0.0, eod=False):
    parts = []
    for sym in SYMS:
        C = GL.build(sym)
        i, s = RL.donchian(C, 96)
        m = np.ones(len(i), bool)
        for g in GATES:
            m &= RG.gate_mask_for(C, i, s, g)
        i, s = i[m], s[m]
        atr = C["atr"]
        ok = np.isfinite(atr[i])
        i, s = i[ok], s[ok]
        if len(i) < 30:
            continue
        ps = C["ps"]
        slp = sl_atr * atr[i] / ps
        tr = lab.simulate(C["d"], i, s, slp, slp * rr, ps, max_hold=MAXH,
                          eod_min=(22 * 60 if eod else None),
                          be_at_r=be_at_r, trail_r=trail_r,
                          spread_fallback_pts=lab.PAIRS[sym].get(
                              "backtest_spread_points", 2.0))
        if len(tr) == 0:
            continue
        pc = lab.PAIRS[sym]
        wd3 = int(pc.get("swap_3x_weekday", 2))
        pv1 = pc["pv1_point"]
        t = C["d"].index
        sw = np.zeros(len(tr))
        for k in range(len(tr)):
            n = _nights(t[tr["i_open"][k]], t[tr["i_close"][k]], wd3)
            if n <= 0:
                continue
            per = (pc.get("swap_long_per_lot", 0.0) if tr["dir"][k] > 0
                   else pc.get("swap_short_per_lot", 0.0))
            sp_ = sl_atr * atr[tr["i_open"][k]] / ps
            sw[k] = n * per / (sp_ * pv1) if sp_ > 0 else 0.0
        parts.append(pd.DataFrame({"sym": sym, "t": t[tr["i_open"]],
                                   "R": tr["r"] + sw, "status": tr["status"],
                                   "tart": tr["i_close"] - tr["i_open"]}))
    if not parts:
        return None
    return pd.concat(parts, ignore_index=True)


def stat(d, label):
    r = d.R
    se = r.std(ddof=1) / np.sqrt(len(r))
    ev = d.groupby(d.t.dt.year).R.mean()
    return {"valtozat": label, "n": len(r), "R": float(r.mean()),
            "t": float(r.mean() / se) if se > 0 else 0.0,
            "nyero%": float(100 * (r > 0.01).mean()),
            "nulla%": float(100 * (r.abs() <= 0.01).mean()),
            "vesztes%": float(100 * (r < -0.01).mean()),
            "atl_nyero": float(r[r > 0.01].mean()) if (r > 0.01).any() else 0.0,
            "atl_vesztes": float(r[r < -0.01].mean()) if (r < -0.01).any() else 0.0,
            "ev_poz": f"{int((ev > 0).sum())}/{len(ev)}",
            "tart_bar": float(d.tart.mean())}


if __name__ == "__main__":
    pd.set_option("display.width", 240)
    SL, RR = 2.5, 1.5
    rows = []
    base = run(SL, RR)
    rows.append(stat(base, "alap (nincs BE/trail)"))
    for be in (0.3, 0.5, 0.8, 1.0):
        d = run(SL, RR, be_at_r=be)
        if d is not None:
            rows.append(stat(d, f"BE {be}R-nel"))
    for be, tr_ in ((0.5, 0.5), (0.5, 1.0), (1.0, 1.0)):
        d = run(SL, RR, be_at_r=be, trail_r=tr_)
        if d is not None:
            rows.append(stat(d, f"BE {be}R + trail {tr_}R"))
    print(f"=== donchian96 + kapuk, stop {SL} ATR, cel {RR}R, SWAPPAL ===")
    print(pd.DataFrame(rows).to_string(index=False,
          float_format=lambda x: f"{x:9.4f}"))

    print("\n=== ugyanez SZELESEBB stoppal (a MAE/MFE szerint az jobb) ===")
    rows = []
    for sl in (2.5, 4.0):
        for be in (0.0, 0.5, 1.0):
            d = run(sl, 1.0, be_at_r=be)
            if d is not None:
                rows.append({**stat(d, f"stop {sl} · RR 1.0 · BE {be}")})
    print(pd.DataFrame(rows).to_string(index=False,
          float_format=lambda x: f"{x:9.4f}"))

    print("\n=== napon belul zarva (nincs swap) + BE ===")
    rows = []
    for be in (0.0, 0.5, 1.0):
        d = run(SL, RR, be_at_r=be, eod=True)
        if d is not None:
            rows.append(stat(d, f"EOD · BE {be}R"))
    print(pd.DataFrame(rows).to_string(index=False,
          float_format=lambda x: f"{x:9.4f}"))

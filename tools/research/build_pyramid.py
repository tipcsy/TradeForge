"""POZICIOEPITES merese — a rendszer SAJAT szabalyaival.

`core/position_build.py` szerint:
  * gyertyas jel: akkor epitunk, ha egy ZART gyertya FELJEBB (BUY) / LEJJEBB
    (SELL) zar, mint az elozo raepites referenciaja,
  * piramidalis meret: minden add = elozo x size_factor (alap 0,7),
  * 1. szabaly: raepites UTAN az OSSZES stop az ATLAGARRA kerul -> a csomag
    lefele ~nullazva van,
  * epiteni csak KOCKAZATMENTES poziciora szabad (elobb BE).

A kimenet R-ben, ahol 1R = az INDULO lab kockazata. Igy a "45-50R" ertelmezheto.

⚠ Amit ez a merés eldont: a piramis a NYERO koteseken novel meretet, a vesztesen
nem. Ha a belepo iranyanak van BARMI ele, ez felnagyitja. Ha nincs, akkor a
varhato erteket nem mozgatja — de az ELOSZLAST igen (ritka nagy nyerok).
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

SYMS = ["Ger40", "UsaInd", "UsaTec", "GOLD", "USDJPY"]
GATES = ["spread", "volatilitas", "lendulet", "piac", "egyuttallas", "szep_chart"]
MAXH = 96


def simulate_package(C, idx, side, sl_atr=2.5, be_r=1.0, size_factor=0.7,
                     min_frac=0.05, max_adds=20, max_hold=MAXH, trigger="candle",
                     r_step=1.0):
    """Egy belepo -> a TELJES csomag eredmenye R-ben.

    R = az INDULO lab kockazata (1.0 lot x sl_atr x ATR)."""
    h, l, c, atr, ps = C["h"], C["l"], C["c"], C["atr"], C["ps"]
    sp = C["sp_pts"] * ps
    n = len(c)
    out = []
    for k in range(len(idx)):
        i, s = int(idx[k]), int(side[k])
        if not np.isfinite(atr[i]) or i + 2 >= n:
            continue
        Rp = sl_atr * atr[i]                      # 1R ARBAN
        e0 = c[i] + (sp[i] if s > 0 else 0.0)
        legs = [(e0, 1.0)]                        # (ar, lot)
        stop = e0 - s * Rp
        risk_free = False
        ref = c[i]                                # a gyertyas jel referenciaja
        adds = 0
        end = min(n - 1, i + max_hold)
        exit_p, exit_j = None, end
        for j in range(i + 1, end + 1):
            if s > 0:
                hi, lo = h[j], l[j]               # BUY: bid-en zar
            else:
                hi, lo = h[j] + sp[j], l[j] + sp[j]
            # 1) stop?
            if (lo <= stop) if s > 0 else (hi >= stop):
                exit_p, exit_j = stop, j
                break
            # 2) kockazatmentesites (BE) — ez engedi az epitest
            if not risk_free:
                fav = (hi - e0) if s > 0 else (e0 - lo)
                if fav >= be_r * Rp:
                    stop = e0
                    risk_free = True
            # 3) raepites-jel a ZART gyertyan
            if risk_free and adds < max_adds:
                cl = c[j]
                fire = False
                if trigger == "candle":
                    fire = (cl > ref) if s > 0 else (cl < ref)
                else:                              # fix R-racs
                    lvl = e0 + s * (adds + 1) * r_step * Rp
                    fire = (cl >= lvl) if s > 0 else (cl <= lvl)
                if fire:
                    lot = max(legs[-1][1] * size_factor, min_frac)
                    price = cl + (sp[j] if s > 0 else 0.0)
                    legs.append((price, lot))
                    adds += 1
                    tot = sum(x[1] for x in legs)
                    avg = sum(p * q for p, q in legs) / tot
                    stop = avg                     # 1. szabaly: kozos stop az atlagaron
                    ref = cl
        if exit_p is None:
            exit_p = c[exit_j] + (0.0 if s > 0 else sp[exit_j])
        pnl = sum(q * s * (exit_p - p) for p, q in legs)
        out.append({"sym": C["sym"], "t": C["d"].index[i], "R": pnl / Rp,
                    "adds": adds, "lots": sum(q for _, q in legs),
                    "tart": exit_j - i})
    return pd.DataFrame(out)


def stat(d, label):
    r = d.R
    se = r.std(ddof=1) / np.sqrt(len(r))
    ev = d.groupby(d.t.dt.year).R.mean()
    return {"valtozat": label, "n": len(r), "R": float(r.mean()),
            "t": float(r.mean() / se) if se > 0 else 0.0,
            "median": float(r.median()),
            "nyero%": float(100 * (r > 0.01).mean()),
            "max_R": float(r.max()), "p99_R": float(r.quantile(0.99)),
            "atl_add": float(d.adds.mean()), "max_add": int(d.adds.max()),
            "ev_poz": f"{int((ev > 0).sum())}/{len(ev)}"}


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    ent = {}
    for sym in SYMS:
        print(f"   … {sym}", flush=True)
        C = GL.build(sym)
        i, s = RL.donchian(C, 96)
        m = np.ones(len(i), bool)
        for g in GATES:
            m &= RG.gate_mask_for(C, i, s, g)
        ent[sym] = (C, i[m], s[m])

    def go(label, **kw):
        parts = [simulate_package(C, i, s, **kw) for C, i, s in ent.values()]
        d = pd.concat([p for p in parts if len(p)], ignore_index=True)
        return stat(d, label), d

    rows, keep = [], {}
    r, d = go("epites NELKUL (max_adds=0)", max_adds=0)
    rows.append(r); keep["nincs"] = d
    for be in (0.5, 1.0):
        for sf in (0.7, 1.0):
            r, d = go(f"gyertyas · BE {be}R · faktor {sf}", be_r=be, size_factor=sf)
            rows.append(r); keep[f"gy{be}_{sf}"] = d
    for st_ in (0.5, 1.0):
        r, d = go(f"fix R-racs {st_}R · BE 1.0R", be_r=1.0, trigger="r_fixed",
                  r_step=st_)
        rows.append(r)
    print("\n=== POZICIOEPITES — donchian96 + kapuk, stop 2.5 ATR ===")
    print(pd.DataFrame(rows).to_string(index=False,
          float_format=lambda x: f"{x:9.4f}"))

    d = keep["gy1.0_0.7"]
    print("\n=== a legjobb epito valtozat ELOSZLASA ===")
    print(d.R.describe(percentiles=[.05, .25, .5, .75, .95, .99])
           .to_string(float_format=lambda x: f"{x:9.3f}"))
    print(f"\n  10R folott: {100 * (d.R > 10).mean():.2f}%   "
          f"20R folott: {100 * (d.R > 20).mean():.3f}%   "
          f"45R folott: {100 * (d.R > 45).mean():.3f}%")
    print(f"  a legnagyobb 1% adja a teljes nyereseg "
          f"{100 * d.R[d.R >= d.R.quantile(0.99)].sum() / max(d.R.sum(), 1e-9):.0f}%-at"
          if d.R.sum() > 0 else "  (a teljes eredmeny negativ)")
    print("\n  evenkent:")
    ev = d.groupby(d.t.dt.year).R.agg(n="size", R="mean", osszes="sum")
    print(ev.to_string(float_format=lambda x: f"{x:9.3f}"))

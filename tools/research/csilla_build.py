"""CSILLA BESZÁLLÓJA — POZÍCIÓÉPÍTÉS: egy csomag, több láb, közös csúszó stop.

A felhasználó kérdése (2026-09-15): „kezeljük egy pozícióként — amint nullán
van az első, nyissuk a másodikat; közös SL, dinamikus csúszó, magas TP (10–20 R)."

A SZABÁLY (a futtatás ELŐTT rögzítve):

    csomag   = egy M15-törés (D1/W1 szint; `csilla_levels.hi_events`);
    lábak    = az utána jövő M1-zászló belépők (`lo_entries`), azonos irány,
               AZONOS lot; legfeljebb MAX_LEGS láb; felvételi ablak 2 óra
               (a rögzített szabály) / 8 óra (tájékoztató);
    1. láb   = az első zászló-törés; kezdő stop = belépő − 1,5 ATR15 (= 1 R);
    BE       = amikor az ár +0,25 R-t megy, a KÖZÖS stop a belépő + 2×spread;
    új láb   = csak ha a közös stop ≥ az 1. láb belépője (kockázatmentes);
    csúszó   = a közös stop = max(eddigi, legjobb ár − T·R), T = 0,5 / 1,0;
    TP       = közös célár az 1. láb belépőjétől K·R-re (10 / 20 / nincs);
    kilépés  = közös stop, közös TP, vagy 5 nap (piaci ár) — MINDEN láb együtt.

    Eredmény R-ben: a csomag P&L / az 1. láb kockázata (1 R = 1,5 ATR15 × lot).
    Költség: spread lábanként (a belépő ask-on), swap láb-éjszakánként
    (`core.trade_costs`), jutalék 0.

⚠ A lábak azonos lotja miatt a csomag VESZTESÉGE meghaladhatja az 1 R-t:
egy később nyitott láb a közös stopig (T·R) veszíthet. Ezért a max
csomag-veszteséget is közöljük.

Futtatás:
    python tools/research/csilla_build.py
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
import csilla_levels as cl
from csilla_swing_break import lo_entries, pivots
from csilla_hours_mfe import blokk_of
from core import trade_costs as _tc

STOP_ATR = 1.5
BE_AT_R = 0.25
BE_OFF_SPREADS = 2.0
MAX_LEGS = 5
MAX_HOLD = 5 * 1440
SEL = {"Ger40": "délelőtt 8–11", "UsaTec": "US-nyitás 15–18", "GOLD": "US-nyitás 15–18"}


def packages(sym: str, window_min: int):
    """[(dir, atr15, [entry_idx...])] csomagonként + az M1 tömbök."""
    m1 = lab.load_m1(sym)
    hi = lab.resample(m1, cl.P["hi_tf"])
    lv = cl.level_table(m1, ("D1", "W1"))
    trend = cl.d1_trend_series(m1)
    evs = cl.hi_events(hi, lv, trend, lv[lv.kind == "D1"])
    h, l, c = (m1[x].to_numpy(float) for x in ("high", "low", "close"))
    atr1 = lab.atr(h, l, c, 14)
    atr1 = np.where(atr1 > 0, atr1, np.nan)
    a15 = lab.atr(hi["high"].to_numpy(float), hi["low"].to_numpy(float),
                  hi["close"].to_numpy(float), 14)
    pc, pv = pivots(h, l, cl.P["k_lo"])
    start = np.searchsorted(m1.index.to_numpy(), [e["t_close"] for e in evs], side="left")
    P = {**cl.P, "max_wait_lo": window_min}
    out = []
    n = len(c)
    for e, s in zip(evs, start):
        if s >= n:
            continue
        a = a15[e["i"]]
        if not (np.isfinite(a) and a > 0):
            continue
        end = min(n - 1, int(s) + window_min)
        xs = lo_entries(e, int(s), end, h, l, c, atr1, pc, pv, cl.P["k_lo"], "break", P)
        if xs:
            out.append((int(e["dir"]), float(a), [int(x["i"]) for x in xs], e["label"]))
    return m1, out


def sim_package(m1, h, l, c, sp, csp, d, atr15, idxs, trail_r, tp_r, pair_cfg, ps):
    """Egy csomag végigjátszása. Vissza: (R_csomag, lábak száma, kilépés-ok,
    i_open, i_close)."""
    i0 = idxs[0]
    R = STOP_ATR * atr15                                   # 1 R árban (1 lot)
    e0 = c[i0] + (csp[i0] if d > 0 else 0.0)
    legs = [(i0, e0)]
    stop = e0 - d * R
    tp = e0 + d * tp_r * R if tp_r > 0 else np.nan
    best = e0
    be_done = False
    pending = [i for i in idxs[1:]]
    end = min(len(c) - 1, i0 + MAX_HOLD)
    status, xprice = "idő", np.nan
    j = i0 + 1
    while j <= end:
        bh, bl = (h[j], l[j]) if d > 0 else (h[j] + sp[j], l[j] + sp[j])
        # 1) közös stop / TP (a stop nyer)
        if (d > 0 and bl <= stop) or (d < 0 and bh >= stop):
            status, xprice = ("BE/csúszó" if be_done else "SL"), stop
            break
        if np.isfinite(tp) and ((d > 0 and bh >= tp) or (d < 0 and bl <= tp)):
            status, xprice = "TP", tp
            break
        # 2) BE + csúszó a legjobb ár szerint
        fav = (bh - e0) if d > 0 else (e0 - bl)
        best = max(best, bh) if d > 0 else min(best, bl)
        if not be_done and fav >= BE_AT_R * R:
            ns = e0 + d * BE_OFF_SPREADS * csp[i0]
            if (d > 0 and ns > stop) or (d < 0 and ns < stop):
                stop = ns
            be_done = True
        if be_done and trail_r > 0:
            ns = best - d * trail_r * R
            if (d > 0 and ns > stop) or (d < 0 and ns < stop):
                stop = ns
        # 3) új láb: csak kockázatmentes csomagra
        riskfree = (stop >= e0) if d > 0 else (stop <= e0)
        while pending and pending[0] <= j:
            k = pending.pop(0)
            if k == j and riskfree and len(legs) < MAX_LEGS:
                legs.append((k, c[k] + (csp[k] if d > 0 else 0.0)))
        j += 1
    if not np.isfinite(xprice):
        j = min(j, end)
        xprice = c[j] + (0.0 if d > 0 else sp[j])
    # P&L R-ben (azonos lot minden lábon), költséggel
    pnl = 0.0
    kock = R * float(pair_cfg.get("pv1_point", 0) or 0) / ps     # 1 R $-ban, 1 lot
    for (ik, ek) in legs:
        r_leg = d * (xprice - ek) / R
        if kock > 0:
            swp = _tc.swap_usd(1.0, "BUY" if d > 0 else "SELL",
                               m1.index[ik].timestamp(), m1.index[j].timestamp(), pair_cfg)
            r_leg += swp / kock
        pnl += r_leg
    return pnl, len(legs), status, i0, j


def run_symbol(sym, window_min, trail_r, tp_r, cache):
    if (sym, window_min) not in cache:
        cache[(sym, window_min)] = packages(sym, window_min)
    m1, pk = cache[(sym, window_min)]
    h, l, c = (m1[x].to_numpy(float) for x in ("high", "low", "close"))
    sp = m1["avg_spread"].to_numpy(float)
    sp = np.where(np.isfinite(sp) & (sp > 0), sp, np.nanmedian(sp))
    csp = m1["close_spread"].to_numpy(float)
    csp = np.where(np.isfinite(csp) & (csp > 0), csp, sp)
    ps = float(lab.PAIRS[sym]["point_size"])
    rows = []
    busy = -1
    for d, a, idxs, label in pk:
        if idxs[0] <= busy:                     # egyszerre egy csomag
            continue
        r, nl, st, i0, j = sim_package(m1, h, l, c, sp, csp, d, a, idxs, trail_r, tp_r,
                                       lab.PAIRS[sym], ps)
        busy = j
        rows.append(dict(sym=sym, t=m1.index[i0], dir=d, R=r, legs=nl, status=st,
                         label=label))
    return pd.DataFrame(rows)


def _t(x):
    return x.mean() / (x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else 0.0


def main():
    pd.set_option("display.width", 250)
    cache = {}
    V = []
    for win_h in (2, 8):
        for trail in (0.5, 1.0):
            for tp in (10.0, 20.0, 0.0):
                V.append((win_h, trail, tp))
    rows, sel = [], []
    for win_h, trail, tp in V:
        parts = [run_symbol(s, win_h * 60, trail, tp, cache) for s in cl.SYMS]
        df = pd.concat([p for p in parts if len(p)], ignore_index=True)
        nev = f"ablak {win_h}h, csúszó {trail}R, TP {'nincs' if tp == 0 else f'{tp:.0f}R'}"
        ev = df.groupby(df.t.dt.year).R.mean()
        sy = df.groupby("sym").R.mean()
        st = df.status.value_counts(normalize=True)
        rows.append({"változat": nev, "csomag": len(df), "láb/csomag": df.legs.mean(),
                     "R/csomag": df.R.mean(), "t": _t(df.R), "nyerő%": 100 * (df.R > 0).mean(),
                     "max veszt. R": df.R.min(), "SL%": 100 * st.get("SL", 0),
                     "BE/csúszó%": 100 * st.get("BE/csúszó", 0), "TP%": 100 * st.get("TP", 0),
                     "év poz.": f"{int((ev > 0).sum())}/{len(ev)}",
                     "pár poz.": f"{int((sy > 0).sum())}/{len(sy)}"})
        df["blokk"] = [blokk_of(int(x)) for x in df.t.dt.hour]
        s = df[[SEL.get(a) == b for a, b in zip(df.sym, df.blokk)]]
        if len(s):
            evs = s.groupby(s.t.dt.year).R.mean()
            sel.append({"változat": nev, "csomag": len(s), "R/csomag": s.R.mean(), "t": _t(s.R),
                        "nyerő%": 100 * (s.R > 0).mean(),
                        "év poz.": f"{int((evs > 0).sum())}/{len(evs)}",
                        "GOLD/Ger40/UsaTec": " / ".join(
                            f"{s[s.sym == k].R.mean():+.2f}" for k in ("GOLD", "Ger40", "UsaTec"))})
        print(f"   {nev:<40} csomag={len(df):5d}  R={df.R.mean():+.4f}", flush=True)
    print("\n════ MIND A 8 PÁR — csomag-eredmény az 1. láb R-jében ════")
    print(pd.DataFrame(rows).round(3).to_string(index=False))
    print("\n════ CSILLA PÁROSÍTÁSA (előre megnevezett sávok) ════")
    print(pd.DataFrame(sel).round(3).to_string(index=False))

    # ── a DAX 09-09-i csomag, 1000 $, 0,25 lot lábanként
    print("\n════ DAX 2026-09-09 csomag, 1000 $, 0,25 lot / láb ════")
    m1, pk = cache[("Ger40", 120)]
    h, l, c = (m1[x].to_numpy(float) for x in ("high", "low", "close"))
    sp = m1["avg_spread"].to_numpy(float); sp = np.where(np.isfinite(sp) & (sp > 0), sp, np.nanmedian(sp))
    csp = m1["close_spread"].to_numpy(float); csp = np.where(np.isfinite(csp) & (csp > 0), csp, sp)
    ps = float(lab.PAIRS["Ger40"]["point_size"])
    out = []
    for win_h in (2, 8):
        _, pk_w = cache[("Ger40", win_h * 60)]
        for d, a, idxs, label in pk_w:
            if not (pd.Timestamp("2026-09-09", tz="UTC") <= m1.index[idxs[0]] < pd.Timestamp("2026-09-10", tz="UTC")):
                continue
            usd_R = 0.25 * STOP_ATR * a / ps * lab.PAIRS["Ger40"]["pv1_point"]
            for trail in (0.5, 1.0):
                for tp in (10.0, 20.0, 0.0):
                    r, nl, st, i0, j = sim_package(m1, h, l, c, sp, csp, d, a, idxs, trail, tp, lab.PAIRS["Ger40"], ps)
                    out.append({"ablak": f"{win_h}h", "csúszó": f"{trail}R", "TP": "nincs" if tp == 0 else f"{tp:.0f}R",
                                "lábak": nl, "kilépés": st, "mikor": m1.index[j].strftime("%m-%d %H:%M"),
                                "R": round(r, 2), "$": round(r * usd_R)})
    print(pd.DataFrame(out).to_string(index=False))


if __name__ == "__main__":
    main()

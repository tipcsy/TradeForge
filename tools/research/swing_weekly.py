"""Ritkitott (heti 1-2 kotes) valtozat, nappali ablakkal — 2026-10-02.

ELORE ROGZITVE (a futtatas elott):
  * Belepo: a swing_mtf M15-os belepoje (visszahuzodas utani atzaras, stop az
    utolso M15 ellen-swing mogott, 0,5-4 ATR).
  * Kereskedesi ablak MAGYAR IDO szerint (Europe/Budapest): belepes 10:00-20:59,
    kenyszerzaras 21:45, max. 8 ora. (A spread-meres szerint a 02-10 ora kozotti
    sav dragabb a Ger40/UK100/UsaInd-en; a 22-05 eddig is ki volt zarva.)
  * Instrumentumonkent egyszerre EGY pozicio (a szuro UTAN alkalmazva).
  * Szamla-nezet: 10 000-es szamla, kotesenkent 100 kockazat (1%) — az R x 100.
  * Ritkito szurok (mind kozolve, nincs utolagos valasztas):
      F0  nincs szuro
      F1  H1 trend (HH+HL) + H1 lab >= 1
      F2  H1 ES H4 trend
      F3  F2 + H1 lab >= 1 + H4 lab >= 1
      F4  F2 + koltseg (spread/stop) <= 3%
      F5  F2 + napi elso jelzes
  * Ertekeles: KIZAROLAG 2023-01-01 utan. Siker: atlag netto >= +10 / kotes
    (0,1 R), t >= 2, a 4 evbol >= 3 pozitiv, >= 3 instrumentum pozitiv.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
from core import broker_paths as _BP                      # noqa: E402
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import lab
from swing_mtf import SYMS, K, structure, htf_at

# ⚠ A gyertya-index KANONIKUS FAL-ÓRA (berlini = magyar helyi idő), csak „UTC"
# címkével tárolva (`core/broker_time.py`). Átváltani TILOS: 2026-10-02-ig itt
# Europe/Budapest állt, ami 1–2 órával eltolta az ablakot. Az „UTC" = nincs átváltás.
TZ = "UTC"
START = pd.Timestamp("2022-10-01", tz="UTC")   # bemelegites a 2023-as ertekeleshez


def run_sym(sym, ltf=15, force_close=True, hold_h=8, start=None, end=None):
    start = START if start is None else start
    m1 = lab.load_m1(sym)
    m1 = m1[m1.index >= start - pd.Timedelta(days=120)]
    if end is not None:
        m1 = m1[m1.index < end]
    if len(m1) < 50_000:
        return pd.DataFrame()
    d = lab.resample(m1, ltf)
    h1d = lab.resample(m1, 60)
    h4d = lab.resample(m1, 240)
    m30d = lab.resample(m1, 30)
    d1d = lab.resample(m1, 1440)
    m5d = lab.resample(m1, 5)
    m1d = m1[["open", "high", "low", "close"]]
    h = d["high"].to_numpy(float); l = d["low"].to_numpy(float)
    c = d["close"].to_numpy(float); sp = d["avg_spread"].to_numpy(float)
    a = lab.atr(h, l, c, 14)
    st, lu, ld, lH, lL = structure(d)
    close_ts = (d.index + pd.Timedelta(minutes=ltf))
    ltf_close = close_ts.to_numpy()
    s1, u1, d1 = htf_at(ltf_close, h1d, 60, list(structure(h1d)[:3]))
    s4, u4, d4 = htf_at(ltf_close, h4d, 240, list(structure(h4d)[:3]))
    s30, = htf_at(ltf_close, m30d, 30, [structure(m30d)[0]])
    sD, = htf_at(ltf_close, d1d, 1440, [structure(d1d)[0]])
    s5, = htf_at(ltf_close, m5d, 5, [structure(m5d)[0]])
    sM1, = htf_at(ltf_close, m1d, 1, [structure(m1d)[0]])
    loc = close_ts.tz_convert(TZ)
    lmin = (loc.hour * 60 + loc.minute).to_numpy()
    lday = loc.normalize().to_numpy()
    hold = hold_h * 60 // ltf
    pc = lab.PAIRS[sym]
    n = len(c)
    rows = []
    broken_hi = broken_lo = np.nan
    for i in range(K + 1, n - 1):
        if d.index[i] < start or not np.isfinite(a[i]) or a[i] <= 0:
            continue
        if not (10 * 60 <= lmin[i] < 21 * 60) or not np.isfinite(sp[i]):
            # a toresi szintet ablakon kivul is "elhasznaltnak" vesszuk
            if c[i] > lH[i] and c[i - 1] <= lH[i]:
                broken_hi = lH[i]
            if c[i] < lL[i] and c[i - 1] >= lL[i]:
                broken_lo = lL[i]
            continue
        side = 0
        if c[i] > lH[i] and c[i - 1] <= lH[i] and lH[i] != broken_hi and st[i] != 1:
            side, stop, broken_hi = 1, lL[i], lH[i]
        elif c[i] < lL[i] and c[i - 1] >= lL[i] and lL[i] != broken_lo and st[i] != -1:
            side, stop, broken_lo = -1, lH[i], lL[i]
        if side == 0 or np.isnan(stop):
            continue
        risk = (c[i] - stop) * side
        if not (0.5 * a[i] <= risk <= 4 * a[i]):
            continue
        ex, ext = np.nan, i
        for t in range(i + 1, min(i + hold, n - 1) + 1):
            if force_close and (lday[t] != lday[i] or lmin[t] > 21 * 60 + 45):
                ex, ext = c[t - 1], t - 1; break
            if side == 1 and l[t] <= stop:
                ex, ext = stop, t; break
            if side == -1 and h[t] + sp[t] >= stop:
                ex, ext = stop - sp[t], t; break
            ex, ext = c[t], t
        if np.isnan(ex):
            continue
        gross = (ex - c[i]) * side / risk
        # swap: minden atlepett helyi ejfel 1 ej, szerdai ejfel 3x (mai rata)
        days = pd.date_range(pd.Timestamp(lday[i]), pd.Timestamp(lday[ext]), freq="D")[1:]
        nights = sum(3 if dd.dayofweek == 3 else 1 for dd in days)
        swp = pc.get("swap_long_per_lot" if side == 1 else "swap_short_per_lot")
        swp = np.nan if swp is None else swp
        risk_money = risk / pc["point_size"] * pc["pv1_point"]
        swap_r = swp * nights / risk_money
        rows.append(dict(nights=nights, swap=swap_r, sym=sym, time=d.index[i], exit_time=d.index[ext], side=side,
                         gross=gross, net=gross - sp[i] / risk, cost=sp[i] / risk,
                         h1_ok=int(s1[i] == side), h4_ok=int(s4[i] == side),
                         m30_ok=int(s30[i] == side), d1_ok=int(sD[i] == side),
                         m1_ok=int(sM1[i] == side), m5_ok=int(s5[i] == side),
                         m15_state=int(st[i] * side),
                         h1_legs=int(u1[i] if side == 1 else d1[i]),
                         h4_legs=int(u4[i] if side == 1 else d4[i]),
                         local_day=lday[i]))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", type=int, default=8)
    ap.add_argument("--no-close", action="store_true")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    arg = ap.parse_args()
    st = pd.Timestamp(arg.start, tz="UTC") if arg.start else None
    en = pd.Timestamp(arg.end, tz="UTC") if arg.end else None
    res = []
    for s in SYMS:
        r = run_sym(s, force_close=not arg.no_close, hold_h=arg.hold, start=st, end=en)
        if len(r):
            res.append(r)
    out = pd.concat(res, ignore_index=True)
    tag = "" if not arg.no_close else f"_nyitva{arg.hold}h"
    if arg.start:
        tag += f"_{arg.start[:4]}_{(arg.end or 'x')[:4]}"
    p = _BP.research_dir() / f"swing_weekly_m15{tag}.parquet"
    out.to_parquet(p)
    print("mentve:", p, len(out))

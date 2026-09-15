"""CSILLA BESZÁLLÓJA — kicsi célár és „pozitívba kockázatmentesítés".

A felhasználó két kérdése (2026-09-15) a `csilla_levels.py` szabályán
(D1/W1 szint → M15-törés → M1-belépő), fix 1,5 ATR15 stoppal, 8 páron,
teljes költséggel (spread + jutalék + swap):

  A) KICSI CÉLÁR: 0,1 / 0,25 / 0,5 / 0,75 / 1,0 R — mit hoz?
  B) „AMINT LEHET, POZITÍVBA": a stop a belépő + 2×spread-re megy, amint az
     ár elér egy küszöböt (4×spread / 0,25 R / 0,5 R); célár nélkül (2R húzó),
     0,5 R és 1 R célárral.

⚠ Utólagos, tájékoztató mérés — a szabály maga a protokollon már megbukott;
itt azt nézzük, a KIMENET-kezelés változtat-e az előjelen. Rács: 5 + 9 cella,
tehát egy kiugró cella önmagában zaj.

Futtatás:
    python tools/research/csilla_small_tp.py
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
from csilla_hours_mfe import blokk_of

STOP_ATR = 1.5
TPS = (0.1, 0.25, 0.5, 0.75, 1.0)
SEL = {"Ger40": "délelőtt 8–11", "UsaTec": "US-nyitás 15–18", "GOLD": "US-nyitás 15–18"}


def _t(x):
    return x.mean() / (x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else 0.0


def run(sym, m1, ent, ps, tp_r, be_mode, be_off_spreads=0.0, trail=0.0):
    """tp_r: célár R-ben (0 = nincs); be_mode: None | ("r", x) | ("spread", k)."""
    e = ent
    idx = e.i.to_numpy()
    slp = e.sl_pts.to_numpy(float)
    tpp = slp * tp_r if tp_r > 0 else np.zeros(len(e))
    csp = m1["close_spread"].to_numpy(float)[idx]
    csp = np.where(np.isfinite(csp) & (csp > 0), csp, np.nanmedian(m1["close_spread"]))
    kw = dict(point_size=ps, max_hold=cl.P["max_hold_days"] * 1440, one_at_a_time=True,
              pair_cfg=lab.PAIRS[sym], trail_r=trail)
    if be_mode is None:
        kw["be_at_r"] = 0.0
    else:
        kind, val = be_mode
        kw["be_at_abs"] = (slp * ps * val) if kind == "r" else (csp * val)
        kw["be_offset_abs"] = csp * be_off_spreads
    tr = lab.simulate(m1, idx, e.dir.to_numpy(), slp, tpp, **kw)
    if len(tr) == 0:
        return None
    return pd.DataFrame({"sym": sym, "t": m1.index[tr["i_open"]], "R": tr["r"],
                         "status": tr["status"]})


def main():
    pd.set_option("display.width", 250)
    cache = {}
    for sym in cl.SYMS:
        r = cl.entries(sym, ("D1", "W1"), stop_atr=STOP_ATR)
        if r is None:
            continue
        m1, ent, ps, _ = r
        cache[sym] = (m1, ent.drop_duplicates("i").reset_index(drop=True), ps)
        print(f"   … {sym} ({len(cache[sym][1])} belépő)", flush=True)

    valtozatok = []
    for tp in TPS:
        valtozatok.append((f"A  TP {tp:.2f}R, nincs BE", tp, None, 0.0, 0.0))
    for thr_name, be_mode in (("4×spread", ("spread", 4.0)), ("0,25R", ("r", 0.25)),
                              ("0,5R", ("r", 0.5))):
        for tp_name, tp, trail in (("nincs TP, 2R húzó", 0.0, 2.0), ("TP 0,5R", 0.5, 0.0),
                                   ("TP 1R", 1.0, 0.0)):
            valtozatok.append((f"B  BE→+2sp @ {thr_name}, {tp_name}", tp, be_mode, 2.0, trail))

    rows, sel_rows = [], []
    for nev, tp, be_mode, off, trail in valtozatok:
        parts = []
        for sym, (m1, ent, ps) in cache.items():
            d = run(sym, m1, ent, ps, tp, be_mode, off, trail)
            if d is not None:
                parts.append(d)
        df = pd.concat(parts, ignore_index=True)
        ev = df.groupby(df.t.dt.year).R.mean()
        sy = df.groupby("sym").R.mean()
        st = df.status.value_counts(normalize=True)
        rows.append({"változat": nev, "n": len(df), "R/kötés": df.R.mean(), "t": _t(df.R),
                     "nyerő%": 100 * (df.R > 0).mean(), "nulla%": 100 * (df.R.abs() < 0.03).mean(),
                     "SL%": 100 * st.get(0, 0), "TP%": 100 * st.get(1, 0),
                     "év poz.": f"{int((ev > 0).sum())}/{len(ev)}",
                     "pár poz.": f"{int((sy > 0).sum())}/{len(sy)}"})
        # Csilla párosítása (előre megnevezett)
        df["blokk"] = [blokk_of(int(h)) for h in df.t.dt.hour]
        s = df[[SEL.get(a) == b for a, b in zip(df.sym, df.blokk)]]
        if len(s):
            evs = s.groupby(s.t.dt.year).R.mean()
            sel_rows.append({"változat": nev, "n": len(s), "R/kötés": s.R.mean(), "t": _t(s.R),
                             "nyerő%": 100 * (s.R > 0).mean(),
                             "év poz.": f"{int((evs > 0).sum())}/{len(evs)}",
                             "GOLD/Ger40/UsaTec": " / ".join(
                                 f"{s[s.sym == k].R.mean():+.2f}" for k in ("GOLD", "Ger40", "UsaTec"))})
        print(f"   {nev:<45} n={len(df):5d}  R={df.R.mean():+.4f}", flush=True)

    print("\n════ MIND A 8 PÁR (fix 1,5 ATR15 stop, teljes költség) ════")
    print(pd.DataFrame(rows).round(3).to_string(index=False))
    print("\n════ CSILLA PÁROSÍTÁSA (Ger40 8–11, UsaTec+GOLD 15–18 — előre megnevezve) ════")
    print(pd.DataFrame(sel_rows).round(3).to_string(index=False))


if __name__ == "__main__":
    main()

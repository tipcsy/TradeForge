"""CSILLA BESZÁLLÓJA, 2. KÉRDÉS — csak a JELENTŐS (napi/heti) szintek, M15-stop.

Az első mérés (`csilla_swing_break.py`, 2026-09-14) a gépi olvasat bukását
adta: az M15 fraktál-swing MINDEN 3-baros csúcsot szintnek vett (napi 5–6
esemény), a belépőnek nem volt iránytartalma, és az M1-stop mellett a spread a
stop 6–24 %-a volt. A felhasználó döntése: MÁS kérdés, előre rögzítve —

    „Csak a jelentős napi/heti szintek törése, M15-stoppal, M1-belépővel."

A SZABÁLY (a mérés ELŐTT rögzítve, 2026-09-14):

    1. SZINTEK: igazolt D1 fraktál-swing (k=2 → 2 nappal később ismert) és
       igazolt W1 fraktál-swing (k=1 → 1 héttel később). Csúcs = ellenállás,
       völgy = támasz. Egy szint az igazolásától ÉL, amíg egy M15 gyertya át
       nem zár rajta (ez az esemény), vagy le nem jár (D1: 90 nap, W1: 365).
       Minden szint egyszer törhet.
    2. ESEMÉNY (M15): zárás egy élő ellenállás FÖLÖTT (+1) / támasz ALATT (−1).
       Címke: a D1-trend a törés előtt (HH+HL / LH+LL a két-két utolsó D1
       swingből) → folytatás / fordulat / nincs.
    3. BELÉPŐ (M1): ugyanaz, mint az első mérésben — a M15 gyertya zárása
       utáni 8×15 M1 baron belül igazolt M1-swing az irány oldalán (zászló),
       majd zárás azon túl. `lo_entries` az első mérésből, változatlanul.
    4. STOP (M15): a törés ELŐTTI utolsó igazolt M15-swing (k=3) a másik
       oldalon — a visszahúzódás M15-szélsője — mínusz 0,2 ATR(M15); padló
       1,0 ATR(M15). A spread-arányt EZ hivatott lenyomni.
    5. CÉLÁR: `fibo` = a tört szinttől 1,382 × |szint − a D1 ellenoldali
       utolsó swing|; `none` = nincs, 2R húzó stop. BE 1R. Max tartás 5 nap.

KÉT LÉPCSŐ, előre rögzített sorrendben:

    A) BRUTTÓ ÉL / SPREAD — költség nélkül, sodródásra kontrollálva, az
       M1-belépő utáni 15/60/240/480 perces elmozdulás. Kapu: a legjobb
       horizonton él ≥ 2 × spread ÉS t ≥ 2, legalább 3 páron. Ha ez nem
       teljesül, a B) csak tájékoztató.
    B) SZIMULÁCIÓ spread + jutalék + swap + BE-vel; elfogadás: t ≥ 2 ·
       az évek ≥ 60 %-a pozitív · ≥ 3 instrumentum pozitív, a `break/fibo`
       fő-változaton.

Futtatás:
    python tools/research/csilla_levels.py
    python tools/research/csilla_levels.py --symbols GOLD Ger40 --csak D1
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import argparse
import time

import numpy as np
import pandas as pd

import lab
from csilla_swing_break import summarize, bontas
from strategies.csilla_rules import lo_entries, pivots  # noqa: F401 (a többi szkript innen importálja)

SYMS = ["GOLD", "USDJPY", "UsaInd", "UsaTec", "Ger40",
        "EURUSD", "EURJPY", "UK100"]

P = dict(hi_tf=15, k_hi=3, k_lo=3, k_d1=2, k_w1=1, ttl_d1=90, ttl_w1=365,
         max_wait=8, buffer_atr=0.2, min_sl_atr=1.0, retest_tol=0.1,
         fib_ext=1.382, be_at_r=1.0, trail_r=2.0, max_hold_days=5,
         max_wait_lo=8 * 15)
HORIZ = (15, 60, 240, 480)
T_MIN, EDGE_SPREAD_MIN, INSTR_MIN = 2.0, 2.0, 3


# ── A SZABÁLY a KÖZÖS magból (strategies/csilla_rules) ────────────────────────────
# ⚠ 2026-09-15 óta a szint-/esemény-/belépő-függvények a `strategies.csilla_rules`
# modulban élnek, hogy a stratégia-modul (`strategies/csilla.py`) UGYANAZT
# hívja. Itt csak vékony burkok maradtak; a mérés eredménye bitre azonos
# (ellenőrizve Ger40-en: break/fibo n=201 R=+0,0159, break/none n=213 R=−0,0454).
from strategies import csilla_rules as _sw


def level_table(m1, kinds):
    return _sw.level_table(m1, kinds, P)


def d1_trend_series(m1):
    return _sw.d1_trend_series(m1, P)


def hi_events(hi, lv, trend, d1_opp):
    return _sw.hi_events(hi, lv, trend, d1_opp, P)


def entries(sym: str, kinds: tuple[str, ...], mode: str = "break",
            stop_atr: float | None = None):
    """`stop_atr`: ⚠ UTÓLAGOS, tájékoztató változat — fix stop_atr × ATR(M15)
    a szerkezeti M15-swing helyett. A rögzített szabály a `None`.
    Vissza: (m1, DataFrame[i, dir, sl_pts, tp_pts, kind, label, atr15, piv, b,
    level], point_size, események száma) — PONTBAN, mint eddig."""
    m1 = lab.load_m1(sym)
    et = _sw.entry_table(m1, {**P, "stop_atr": None}, kinds, mode, stop_atr=stop_atr)
    if not len(et):
        return None
    ps = float(lab.PAIRS[sym]["point_size"])
    df = pd.DataFrame(dict(i=et.i, dir=et.dir, sl_pts=et.sl_abs / ps,
                           tp_pts=et.tp_abs / ps, kind=et.kind, label=et.label,
                           atr15=et.atr15, piv=et.piv, b=et.b, level=et.level))
    return m1, df, ps, int(et.ev_i.nunique())


# ── A) bruttó él / spread ────────────────────────────────────────────────────
def gross_edge(m1: pd.DataFrame, ent: pd.DataFrame, ps: float) -> dict:
    c = m1["close"].to_numpy(float)
    csp = m1["close_spread"].to_numpy(float)
    idx = ent.i.to_numpy()
    d = ent.dir.to_numpy()
    sp = float(np.nanmedian(csp[idx])) / ps
    p_long = float((d > 0).mean())
    best = None
    for H in HORIZ:
        ok = idx + H < len(c)
        ii, dd = idx[ok], d[ok]
        mv = dd * (c[ii + H] - c[ii]) / ps
        # sodródás-kontroll: az ÖSSZES bar H-elmozdulása, ugyanazzal az
        # oldal-aránnyal (long részaránya p_long)
        allmv = (c[H:] - c[:-H]) / ps
        drift = (2 * p_long - 1) * float(np.nanmean(allmv))
        edge = float(np.nanmean(mv)) - drift
        se = float(np.nanstd(mv, ddof=1) / np.sqrt(len(mv))) if len(mv) > 2 else np.nan
        t = edge / se if se and se > 0 else 0.0
        if best is None or edge > best["edge_pts"]:
            best = dict(H=H, edge_pts=edge, t=t)
    return dict(n=len(idx), spread_pts=sp, **best,
                edge_per_spread=best["edge_pts"] / sp if sp > 0 else np.nan,
                sl_med_atr15=float(np.median(ent.sl_pts * ps / ent.atr15)),
                spread_per_sl=sp / float(np.median(ent.sl_pts)),
                tp_sl_med=float(np.median(ent.tp_pts / ent.sl_pts)))


# ── B) szimuláció ────────────────────────────────────────────────────────────
def simulate(sym, m1, ent, ps, tp_mode):
    # ugyanaz az M1-bar két szintről is jöhet (D1 és W1 egy baron) → egyszer
    e = ent.drop_duplicates("i", keep="first").copy()
    if tp_mode == "fibo":
        e = e[e.tp_pts > e.sl_pts * 0.3]
        tpp = e.tp_pts.to_numpy(float)
    else:
        tpp = np.zeros(len(e))
    if len(e) == 0:
        return None
    tr = lab.simulate(m1, e.i.to_numpy(), e.dir.to_numpy(), e.sl_pts.to_numpy(float),
                      tpp, point_size=ps, max_hold=P["max_hold_days"] * 1440,
                      be_at_r=P["be_at_r"],
                      trail_r=(P["trail_r"] if tp_mode == "none" else 0.0),
                      one_at_a_time=True, pair_cfg=lab.PAIRS[sym])
    if len(tr) == 0:
        return None
    meta = e.set_index("i")
    return pd.DataFrame({"sym": sym, "t": m1.index[tr["i_open"]], "dir": tr["dir"],
                         "R": tr["r"], "status": tr["status"],
                         "kind": meta.loc[tr["i_open"], "kind"].to_numpy(),
                         "label": meta.loc[tr["i_open"], "label"].to_numpy()})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=SYMS)
    ap.add_argument("--csak", nargs="*", default=["D1", "W1"],
                    help="szint-fajták: D1 W1")
    ap.add_argument("--stop-atr", type=float, default=None,
                    help="⚠ UTÓLAGOS: fix stop ATR(M15)-ben a szerkezeti helyett")
    a = ap.parse_args()
    kinds = tuple(a.csak)
    pd.set_option("display.width", 250)
    print(f"szintek: {kinds}, M15-stop (padló {P['min_sl_atr']} ATR15"
          f"{', ⚠ UTÓLAGOS fix ' + str(a.stop_atr) + ' ATR15' if a.stop_atr else ''}), "
          f"M1-belépő (k={P['k_lo']})\n")

    cache = {}
    print("A) BRUTTÓ ÉL / SPREAD (sodródás-kontrollal, a legjobb horizonton)")
    rowsA = []
    for sym in a.symbols:
        t0 = time.time()
        r = entries(sym, kinds, stop_atr=a.stop_atr)
        if r is None:
            print(f"   {sym}: nincs belépő")
            continue
        m1, ent, ps, n_ev = r
        cache[sym] = r
        g = gross_edge(m1, ent, ps)
        g.update(sym=sym, esemeny=n_ev, ev_per_ev=len(ent) / n_ev)
        rowsA.append(g)
        print(f"   {sym:<7} esemény={n_ev:5d} belépő={len(ent):5d}  él={g['edge_pts']:+8.1f} pt "
              f"(H={g['H']}, t={g['t']:+.2f})  spread={g['spread_pts']:.1f}  "
              f"él/spread={g['edge_per_spread']:+.2f}  spread/SL={100*g['spread_per_sl']:.1f}%  "
              f"SL={g['sl_med_atr15']:.1f} ATR15  ({time.time()-t0:.0f}s)", flush=True)
    A = pd.DataFrame(rowsA)
    atment = A[(A.edge_per_spread >= EDGE_SPREAD_MIN) & (A.t >= T_MIN)]
    print(f"\n   → él ≥ {EDGE_SPREAD_MIN}× spread ÉS t ≥ {T_MIN}: {len(atment)} pár "
          f"({', '.join(atment.sym) if len(atment) else '—'}); kapu: ≥ {INSTR_MIN} → "
          f"{'ÁTMENT' if len(atment) >= INSTR_MIN else 'BUKOTT (a B) csak tájékoztató)'}\n")

    print("B) SZIMULÁCIÓ (spread + jutalék + swap, BE 1R)")
    ossz, resz = [], {}
    for tp_mode in ("fibo", "none"):
        parts = []
        for sym, (m1, ent, ps, _) in cache.items():
            d = simulate(sym, m1, ent, ps, tp_mode)
            if d is not None:
                parts.append(d)
        if not parts:
            continue
        df = pd.concat(parts, ignore_index=True)
        resz[f"break/{tp_mode}"] = df
        s = summarize(df, f"break/{tp_mode}")
        if s:
            ossz.append(s)
    print(pd.DataFrame(ossz).round(4).to_string(index=False))
    for nev, df in resz.items():
        print(f"\n── {nev} ──")
        print("instrumentum:\n" + bontas(df, "sym").to_string())
        print("év:\n" + bontas(df, df.t.dt.year.rename("ev")).to_string())
        print("irány:\n" + bontas(df, "dir").to_string())
        print("szint-fajta:\n" + bontas(df, "kind").to_string())
        print("címke:\n" + bontas(df, "label").to_string())
        st = df.status.value_counts().rename({0: "sl", 1: "tp", 2: "idő", 3: "be/trail"})
        print("kimenet: " + ", ".join(f"{k}={v}" for k, v in st.items()))


if __name__ == "__main__":
    main()

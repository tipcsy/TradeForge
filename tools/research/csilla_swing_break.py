"""CSILLA BESZÁLLÓJA — kétszintű szerkezet-törés, mérve a hosszú mintán.

Forrás: az Obsidian „Stratégiák/Csilla beszállója" jegyzet (2026-09-07) és a
8 kép. A módszer diszkrecionális; ez a fájl a GÉPI olvasata, amit a mérés
ELŐTT rögzítettünk (2026-09-14), és a mérés után nem módosítunk.

A SZABÁLY (egy szabály; a „folytatás" és a „fordulat" csak címke rajta):

    1. MAGAS TF (alap M15): igazolt swing-csúcs/völgy (fraktál, k_hi félablak,
       a pivot csak k_hi barral KÉSŐBB ismerhető fel → nincs jövő-szivárgás).
       ESEMÉNY: egy gyertya a legutóbbi igazolt swing-csúcs FÖLÖTT zár
       (irány +1), vagy a legutóbbi igazolt swing-völgy ALATT (irány −1).
       Minden szint egyszer törhet.
       CÍMKE: a magas TF trendje a törés ELŐTT (HH+HL = fel, LH+LL = le, a
       két-két utolsó swingből). Egyezik az iránnyal → „folytatás",
       ellentétes → „fordulat", egyik sem → „nincs".

    2. ALACSONY TF (alap M1): a magas gyertya ZÁRÁSA utáni első alacsony
       bartól, legfeljebb `max_wait` alacsony baron át:
         a) legyen egy igazolt alacsony-TF swing az irány oldalán (felfelé
            törésnél swing-csúcs) — ez a visszahúzódás („zászló");
         b) egy alacsony gyertya ezen a swingen TÚL zár → ez a törés.
       BELÉPŐ:
         `break`  — a törő gyertya zárásán;
         `retest` — a törés után az első gyertya, amelyik VISSZAÉR a tört
                    szintre (low ≤ szint + tol·ATR), de fölötte zár.
       STOP: a visszahúzódás szélső pontja (a swing és a törés közti
       legalacsonyabb low) mínusz `buffer_atr`·ATR(alacsony); padló
       `min_sl_atr`·ATR, hogy ne legyen nulla-stop.
       Egy magas eseményhez TÖBB alacsony belépő is tartozhat („kitörés,
       korrekció, kitörés, korrekció — ezek mind beszállók").

    3. CÉLÁR:
         `fibo`  — a tört szinttől az irányba `fib_ext` × a magas-TF utolsó
                   swing-szakasz (csúcs–völgy táv) — a jegyzet 138,2 %-a;
         `none`  — nincs célár; BE 1R-nél, utána 2R-es húzó stop, max 2 nap.
       Mindkettőnél BE 1R-nél (a jegyzet: „amilyen gyorsan lehet 0-ba").

    KÖLTSÉG: spread (bid/ask), jutalék, swap — a motor `trade_costs`-ával.

ELŐRE RÖGZÍTETT ELFOGADÁS (a tools/research/README.md protokollja):
    t ≥ 2 az összevont mintán · az évek ≥ 60 %-a pozitív · ≥ 3 instrumentum
    pozitív. A négy változat (belépő × célár) közül annak kell átmennie, amit
    ELŐRE fő-változatnak jelölünk: `break` + `fibo` (a jegyzethez legközelebb).
    A többi tájékoztató — ha CSAK egy másik megy át, az keresési többlet, nem
    elfogadás; új, külön rögzített mérés kell hozzá.

Amit a jegyzet mond, és ITT NEM mérünk (később, ha a mag átmegy): napszak
(DAX délelőtt / Nasdaq délután — külön `--session` kapcsoló, tájékoztató),
„minden idősík egy irányba" (a TF-együttállás kapu), pozícióépítés.

Futtatás:

    python tools/research/csilla_swing_break.py
    python tools/research/csilla_swing_break.py --hi 60 --lo 5 --symbols GOLD Ger40
    python tools/research/csilla_swing_break.py --session
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

# A hosszú minták elöl (GOLD/USDJPY 2013-, UsaInd/UsaTec 2017-, Ger40 2021-),
# aztán a 2024-től létező többi — az évenkénti bontást az elsők adják.
SYMS = ["GOLD", "USDJPY", "UsaInd", "UsaTec", "Ger40",
        "EURUSD", "EURJPY", "UK100"]
# likvid ablak (szerver-idő perc) a `--session` változathoz
SESS = {"Ger40": (540, 1050), "UsaInd": (930, 1320), "UsaTec": (930, 1320),
        "GOLD": (540, 1320), "USDJPY": (480, 1320), "EURUSD": (480, 1320),
        "EURJPY": (480, 1320), "UK100": (540, 1050)}

# ── ELŐRE RÖGZÍTETT paraméterek ────────────────────────────────────────────
DEFAULTS = dict(
    hi_tf=15, lo_tf=1,      # a kért első TF-pár; parancssorból állítható
    k_hi=3, k_lo=3,         # fraktál félablak (a tananyag „N=3" ajánlása)
    max_wait=8,             # ennyi MAGAS gyertyányi alacsony bar a törés után
    buffer_atr=0.2,         # stop-puffer az alacsony ATR(14)-ben
    min_sl_atr=0.5,         # stop-padló az alacsony ATR-ben
    retest_tol=0.1,         # visszateszt: a szint ± ennyi ATR
    fib_ext=1.382,          # a jegyzet célára
    be_at_r=1.0,            # BE „amilyen gyorsan lehet" — 1R (mérhető, nem 0)
    trail_r=2.0,            # csak a `none` célárnál
    max_hold_days=2,
)

T_MIN, EV_POZ_MIN, INSTR_MIN = 2.0, 0.60, 3


# ── swing-pontok + M1 belépők: a KÖZÖS magból (2026-09-15 óta) ─────────────
from strategies.csilla_rules import lo_entries, pivots  # noqa: E402,F401


# ── a magas TF eseményei ─────────────────────────────────────────────────────
def hi_events(d: pd.DataFrame, k: int) -> list[dict]:
    """A magas TF szerkezet-törései, KAUZÁLISAN.

    Egy bar `i`-nél a „legutóbbi igazolt swing" az, amelynek pivotja ≤ i−k.
    A törés: close[i] > szint (fel) vagy < szint (le). Minden szint egyszer.
    Vissza: [{i, dir, level, leg, label}], ahol `leg` az utolsó csúcs–völgy
    táv (a fibo-célárhoz), `label` folytatás/fordulat/nincs."""
    h = d["high"].to_numpy(float)
    l = d["low"].to_numpy(float)
    c = d["close"].to_numpy(float)
    n = len(c)
    pc, pv = pivots(h, l, k)
    out = []
    # az igazolt swingek időrendben: (bar, típus, ár)
    sw_h: list[tuple[int, float]] = []
    sw_l: list[tuple[int, float]] = []
    tort_h = tort_l = -1          # az utoljára TÖRT swing indexe a listában
    for i in range(k, n):
        j = i - k                 # ez a bar MOST igazolódik pivotnak
        if pc[j]:
            sw_h.append((j, h[j]))
        if pv[j]:
            sw_l.append((j, l[j]))
        # trend-címke a két-két utolsó swingből (a törés ELŐTTI állapot)
        trend = 0
        if len(sw_h) >= 2 and len(sw_l) >= 2:
            hh = sw_h[-1][1] > sw_h[-2][1]
            hl = sw_l[-1][1] > sw_l[-2][1]
            if hh and hl:
                trend = 1
            elif (not hh) and (not hl):
                trend = -1
        if sw_h and len(sw_h) - 1 > tort_h and c[i] > sw_h[-1][1]:
            lvl = sw_h[-1][1]
            leg = (lvl - sw_l[-1][1]) if sw_l and sw_l[-1][0] < sw_h[-1][0] \
                else (lvl - min(l[sw_h[-1][0]:i + 1]))
            out.append(dict(i=i, dir=1, level=lvl, leg=max(leg, 0.0),
                            label=("folyt" if trend == 1 else
                                   "ford" if trend == -1 else "nincs")))
            tort_h = len(sw_h) - 1
        if sw_l and len(sw_l) - 1 > tort_l and c[i] < sw_l[-1][1]:
            lvl = sw_l[-1][1]
            leg = (sw_h[-1][1] - lvl) if sw_h and sw_h[-1][0] < sw_l[-1][0] \
                else (max(h[sw_l[-1][0]:i + 1]) - lvl)
            out.append(dict(i=i, dir=-1, level=lvl, leg=max(leg, 0.0),
                            label=("folyt" if trend == -1 else
                                   "ford" if trend == 1 else "nincs")))
            tort_l = len(sw_l) - 1
    return out


# ── egy instrumentum ─────────────────────────────────────────────────────────
def run_symbol(sym: str, P: dict, mode: str, tp_mode: str,
               session: bool) -> pd.DataFrame | None:
    m1 = lab.load_m1(sym)
    lo = lab.resample(m1, P["lo_tf"]) if P["lo_tf"] > 1 else m1
    hi = lab.resample(m1, P["hi_tf"])
    h, l, c = (lo[x].to_numpy(float) for x in ("high", "low", "close"))
    atr = lab.atr(h, l, c, 14)
    atr = np.where(atr > 0, atr, np.nan)
    pc, pv = pivots(h, l, P["k_lo"])
    ps = float(lab.PAIRS[sym]["point_size"])
    pair_cfg = lab.PAIRS[sym]

    evs = hi_events(hi, P["k_hi"])
    if not evs:
        return None
    # a magas gyertya ZÁRÁSA utáni első alacsony bar (look-ahead nélkül)
    zaras = hi.index + pd.Timedelta(minutes=P["hi_tf"])
    hi_close_i = np.array([zaras[e["i"]] for e in evs])
    start_i = np.searchsorted(lo.index, hi_close_i, side="left")
    wait_lo = P["max_wait"] * P["hi_tf"] // P["lo_tf"]
    P = {**P, "max_wait_lo": wait_lo}

    rows = []
    n = len(c)
    for e, s in zip(evs, start_i):
        if s >= n:
            continue
        end = min(n - 1, s + wait_lo)
        for x in lo_entries(e, int(s), end, h, l, c, atr, pc, pv, P["k_lo"],
                            mode, P):
            sl_pts = x["sl_abs"] / ps
            if tp_mode == "fibo":
                cel = e["level"] + e["dir"] * P["fib_ext"] * e["leg"]
                tp_pts = e["dir"] * (cel - c[x["i"]]) / ps
                if tp_pts <= sl_pts * 0.3:      # a célár már majdnem/át van lépve
                    continue
            else:
                tp_pts = 0.0
            rows.append((x["i"], e["dir"], sl_pts, tp_pts, e["label"]))
    if not rows:
        return None
    arr = np.array(rows, dtype=object)
    idx = arr[:, 0].astype(int)
    side = arr[:, 1].astype(int)
    slp = arr[:, 2].astype(float)
    tpp = arr[:, 3].astype(float)
    lab_ = arr[:, 4].astype(str)
    if session:
        lo_s, hi_s = SESS[sym]
        mod = (lo.index.hour * 60 + lo.index.minute).to_numpy()[idx]
        m = (mod >= lo_s) & (mod < hi_s)
        idx, side, slp, tpp, lab_ = idx[m], side[m], slp[m], tpp[m], lab_[m]
    if len(idx) == 0:
        return None
    max_hold = P["max_hold_days"] * 1440 // P["lo_tf"]
    tr = lab.simulate(lo, idx, side, slp, tpp, point_size=ps,
                      max_hold=max_hold, be_at_r=P["be_at_r"],
                      trail_r=(P["trail_r"] if tp_mode == "none" else 0.0),
                      one_at_a_time=True, pair_cfg=pair_cfg)
    if len(tr) == 0:
        return None
    # a szimulátor átugorja a foglalt belépőket → a címkét az i_open-ből
    cimke = dict(zip(idx.tolist(), lab_.tolist()))
    df = pd.DataFrame({"sym": sym, "t": lo.index[tr["i_open"]],
                       "dir": tr["dir"], "R": tr["r"], "status": tr["status"],
                       "label": [cimke[int(i)] for i in tr["i_open"]]})
    return df


# ── összegzés ────────────────────────────────────────────────────────────────
def summarize(df: pd.DataFrame, label: str) -> dict | None:
    if df is None or len(df) < 100:
        return None
    r = df.R
    se = r.std(ddof=1) / np.sqrt(len(r))
    ev = df.groupby(df.t.dt.year).R.mean()
    sy = df.groupby("sym").R.mean()
    return {"valtozat": label, "n": len(r), "R": float(r.mean()),
            "t": float(r.mean() / se) if se > 0 else 0.0,
            "win%": float(100 * (r > 0).mean()),
            "ev_poz": f"{int((ev > 0).sum())}/{len(ev)}",
            "instr_poz": f"{int((sy > 0).sum())}/{len(sy)}",
            "atmegy": bool(r.mean() / se >= T_MIN and (ev > 0).mean() >= EV_POZ_MIN
                           and (sy > 0).sum() >= INSTR_MIN)}


def bontas(df: pd.DataFrame, by: str) -> pd.DataFrame:
    g = df.groupby(by).R
    out = pd.DataFrame({"n": g.size(), "R": g.mean(),
                        "t": g.apply(lambda x: x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))
                                     if len(x) > 2 and x.std() > 0 else 0.0)})
    return out.round(4)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hi", type=int, default=DEFAULTS["hi_tf"])
    ap.add_argument("--lo", type=int, default=DEFAULTS["lo_tf"])
    ap.add_argument("--k-hi", type=int, default=DEFAULTS["k_hi"])
    ap.add_argument("--k-lo", type=int, default=DEFAULTS["k_lo"])
    ap.add_argument("--symbols", nargs="*", default=SYMS)
    ap.add_argument("--session", action="store_true",
                    help="csak a likvid ablakban nyitott belépők (tájékoztató)")
    ap.add_argument("--csak", nargs="*", default=None,
                    help="csak ezek a változatok, pl. break/fibo retest/none")
    a = ap.parse_args()
    P = {**DEFAULTS, "hi_tf": a.hi, "lo_tf": a.lo, "k_hi": a.k_hi, "k_lo": a.k_lo}
    pd.set_option("display.width", 250)
    print(f"TF-pár M{P['hi_tf']} → M{P['lo_tf']}, k_hi={P['k_hi']} k_lo={P['k_lo']}, "
          f"session={a.session}\n")

    valtozatok = [(m, t) for m in ("break", "retest") for t in ("fibo", "none")]
    if a.csak:
        valtozatok = [tuple(v.split("/")) for v in a.csak]
    ossz = []
    reszletek = {}
    for mode, tp_mode in valtozatok:
        nev = f"{mode}/{tp_mode}"
        parts = []
        t0 = time.time()
        for sym in a.symbols:
            try:
                d = run_symbol(sym, P, mode, tp_mode, a.session)
            except Exception as ex:
                print(f"   ! {nev}/{sym}: {ex!r}", flush=True)
                continue
            if d is not None:
                parts.append(d)
                print(f"   {nev:<12} {sym:<7} n={len(d):5d}  R={d.R.mean():+.4f}",
                      flush=True)
        if not parts:
            continue
        df = pd.concat(parts, ignore_index=True)
        reszletek[nev] = df
        s = summarize(df, nev)
        if s:
            ossz.append(s)
        print(f"   ({time.time() - t0:.0f} s)\n", flush=True)

    print("=" * 78)
    print("ÖSSZEVONT (fő-változat: break/fibo; küszöb: t≥2, évek≥60%, ≥3 instr.)")
    print(pd.DataFrame(ossz).round(4).to_string(index=False))
    for nev, df in reszletek.items():
        print(f"\n── {nev} ──")
        print("instrumentum:\n" + bontas(df, "sym").to_string())
        print("év:\n" + bontas(df, df.t.dt.year.rename("ev")).to_string())
        print("irány:\n" + bontas(df, "dir").to_string())
        print("címke (folytatás/fordulat):\n" + bontas(df, "label").to_string())
        st = df.status.value_counts().rename({0: "sl", 1: "tp", 2: "idő", 3: "be/trail"})
        print("kimenet: " + ", ".join(f"{k}={v}" for k, v in st.items()))


if __name__ == "__main__":
    main()

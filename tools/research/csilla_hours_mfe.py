"""CSILLA BESZÁLLÓJA — óránkénti bontás + „meddig megy el, mielőtt stopba fut".

A felhasználó két kérdése (2026-09-14), a `csilla_levels.py` szabályán
(D1/W1 jelentős szintek → M15-törés → M1-zászló belépő, M15-stop):

  1. ÓRÁNKÉNT, minden páron: Csilla DAX-on délelőtt, Nasdaq-on és aranyon
     délután kereskedik — van-e olyan óra, ahol a szabály működik?
  2. MFE/MAE: egy belépés HÁNY PONTIG megy el a javunkra, mielőtt veszteséges
     lesz / stopba fut? „Helyből negatív"-e (sosem éri el a spread-fedezetet),
     vagy elmegy annyira, hogy a 0-ba húzott stop értelmes legyen?

Mérés: a belépő utáni M1-út a rögzített M15-stop eléréséig vagy 5 napig.
A kedvező/kedvezőtlen elmozdulást a KILÉPÉSI oldalon mérjük (BUY: bid-en,
SELL: ask-on), a belépőt a spreaddel terhelve — a motor konvenciója.

Az R-referencia kétféle, mert a rögzített M15-stop mediánja 6,3 ATR15 (túl
széles ahhoz, hogy R-ben beszédes legyen): (a) a rögzített stop, (b) ATR15.

⚠ Ez LEÍRÓ mérés — nincs elfogadási küszöb, nem keresünk „jó órát" utólag.
Egy óra, ami 8 pár × 24 óra = 192 cellából kiugrik, önmagában zaj.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import argparse

import numpy as np
import pandas as pd

import lab
import csilla_levels as cl

FAV_ATR = (0.25, 0.5, 1.0, 2.0)       # „elért-e ennyi ATR15-öt a javunkra"
RACE_STOP = 1.5                       # a VERSENY-méréshez: fix 1,5 ATR15 stop
                                      # (a motor konvenciója; a rögzített 6 ATR
                                      # stop mellett az MFE csak az út terjedelme)
# napszak-blokkok SZERVER-időben (CET-szerű: DAX 9–17:30, US-nyitás 15:30)
BLOKK = [("éjszaka 0–7", 0, 7), ("délelőtt 8–11", 8, 11), ("dél 12–14", 12, 14),
         ("US-nyitás 15–18", 15, 18), ("este 19–23", 19, 23)]


def blokk_of(h: int) -> str:
    for nev, a, b in BLOKK:
        if a <= h <= b:
            return nev
    return "?"


def excursion(m1: pd.DataFrame, ent: pd.DataFrame, ps: float, max_hold: int):
    """Belépőnként: MFE/MAE pontban a stopig (vagy max_hold-ig), a stop
    elérésének ténye, és az egyes kedvező szintek elérése a STOP ELŐTT."""
    h = m1["high"].to_numpy(float)
    l = m1["low"].to_numpy(float)
    c = m1["close"].to_numpy(float)
    sp = m1["avg_spread"].to_numpy(float)
    csp = m1["close_spread"].to_numpy(float)
    sp = np.where(np.isfinite(sp) & (sp > 0), sp, np.nanmedian(sp))
    csp = np.where(np.isfinite(csp) & (csp > 0), csp, sp)
    n = len(c)
    out = []
    for r in ent.itertuples():
        i, d = int(r.i), int(r.dir)
        slp = r.sl_pts * ps
        entry = c[i] + (csp[i] if d > 0 else 0.0)
        end = min(n - 1, i + max_hold)
        mfe = 0.0
        mae = 0.0
        mfe_pre_stop = 0.0
        stopped = False
        # VERSENY fix 1,5 ATR15 stoppal: az egyes kedvező szintek elérése a
        # −1,5 ATR ELŐTT, és a −1,5 ATR előtti MFE
        race_stop = RACE_STOP * r.atr15
        race_mfe = 0.0
        race_done = False
        j = i + 1
        while j <= end:
            if d > 0:
                bh, bl = h[j], l[j]
            else:
                bh, bl = h[j] + sp[j], l[j] + sp[j]
            fav = (bh - entry) if d > 0 else (entry - bl)
            adv = (entry - bl) if d > 0 else (bh - entry)
            if not race_done:
                if adv >= race_stop:
                    race_done = True
                else:
                    race_mfe = max(race_mfe, fav)
            # a stop elérése ELŐTTI kedvező max (a stop nyer, ha egy baron mindkettő)
            if adv >= slp:
                stopped = True
                mae = max(mae, slp)
                break
            mfe = max(mfe, fav)
            mae = max(mae, adv)
            j += 1
        mfe_pre_stop = mfe
        out.append((i, d, r.sl_pts, r.atr15 / ps, mfe_pre_stop / ps, mae / ps,
                    stopped, csp[i] / ps, j - i, race_mfe / ps, race_done))
    return pd.DataFrame(out, columns=["i", "dir", "sl_pts", "atr15_pts", "mfe_pts",
                                      "mae_pts", "stopped", "spread_pts", "bars",
                                      "race_mfe_pts", "race_stopped"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=cl.SYMS)
    a = ap.parse_args()
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    max_hold = cl.P["max_hold_days"] * 1440

    osszes_ora = []
    osszes_exc = []
    osszes_blokk = []
    for sym in a.symbols:
        r = cl.entries(sym, ("D1", "W1"))
        if r is None:
            continue
        m1, ent, ps, _ = r
        ent = ent.drop_duplicates("i", keep="first").reset_index(drop=True)
        sim = cl.simulate(sym, m1, ent, ps, "none")       # BE 1R + 2R húzó
        exc = excursion(m1, ent, ps, max_hold)
        exc["sym"] = sym
        exc["hour"] = m1.index[exc.i].hour
        exc["mfe_atr"] = exc.mfe_pts / exc.atr15_pts
        exc["mfe_R"] = exc.mfe_pts / exc.sl_pts
        exc["helybol_neg"] = exc.mfe_pts <= exc.spread_pts
        exc["race_mfe_atr"] = exc.race_mfe_pts / exc.atr15_pts
        for f in FAV_ATR:
            exc[f"el_{f}atr"] = exc.mfe_atr >= f
            exc[f"race_{f}"] = exc.race_mfe_atr >= f     # elérte −1,5 ATR ELŐTT
        exc["blokk"] = [blokk_of(int(x)) for x in exc.hour]
        osszes_exc.append(exc)

        # ── 1. óránként ────────────────────────────────────────────────────
        sim["hour"] = sim.t.dt.hour
        g = sim.groupby("hour").R
        ora = pd.DataFrame({"n": g.size(), "R": g.mean().round(3),
                            "win%": (100 * sim.groupby("hour").R.apply(lambda x: (x > 0).mean())).round(0)})
        ge = exc.groupby("hour")
        ora["MFE_med_ATR"] = ge.mfe_atr.median().round(2)
        ora["el_1ATR%"] = (100 * ge["el_1.0atr"].mean()).round(0)
        ora["helyből_neg%"] = (100 * ge.helybol_neg.mean()).round(0)
        ora["stop%"] = (100 * ge.stopped.mean()).round(0)
        ora.index.name = "óra(szerver)"
        print(f"\n════ {sym} — óránként (break/none, rögzített M15-stop) ════")
        print(ora.to_string())
        ora["sym"] = sym
        osszes_ora.append(ora.reset_index())
        sim["blokk"] = [blokk_of(int(x)) for x in sim.hour]
        gb = sim.groupby("blokk").R
        bl = pd.DataFrame({"n": gb.size(), "R": gb.mean().round(3),
                           "t": gb.apply(lambda x: x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))
                                         if len(x) > 2 and x.std() > 0 else 0.0).round(2),
                           "win%": (100 * gb.apply(lambda x: (x > 0).mean())).round(0)})
        gbe = exc.groupby("blokk")
        bl["race_MFE_med_ATR"] = gbe.race_mfe_atr.median().round(2)
        bl["+0.5ATR_előbb%"] = (100 * gbe["race_0.5"].mean()).round(0)
        bl["+1ATR_előbb%"] = (100 * gbe["race_1.0"].mean()).round(0)
        bl["helyből_neg%"] = (100 * gbe.helybol_neg.mean()).round(0)
        bl = bl.reindex([b[0] for b in BLOKK]).dropna(subset=["n"])
        print(f"\n   {sym} — NAPSZAK-blokkok (verseny: fix 1,5 ATR15 stop):")
        print(bl.to_string())
        bl["sym"] = sym
        osszes_blokk.append(bl.reset_index().rename(columns={"index": "blokk"}))

        # ── 2. MFE / MAE ───────────────────────────────────────────────────
        st = exc[exc.stopped]
        print(f"\n   {sym}: belépő {len(exc)}, stopba futott {100*exc.stopped.mean():.0f}% "
              f"(a többi 5 nap után él), spread medián {exc.spread_pts.median():.0f} pt, "
              f"ATR15 medián {exc.atr15_pts.median():.0f} pt, stop medián {exc.sl_pts.median():.0f} pt")
        print(f"   MFE (max a javunkra, a stop ELŐTT): medián {exc.mfe_pts.median():.0f} pt "
              f"= {exc.mfe_atr.median():.2f} ATR15 = {exc.mfe_R.median():.2f} R;  átlag {exc.mfe_pts.mean():.0f} pt")
        if len(st):
            print(f"   …csak a STOPBA futottakon: medián {st.mfe_pts.median():.0f} pt = "
                  f"{st.mfe_atr.median():.2f} ATR15;  helyből negatív (MFE ≤ spread): {100*st.helybol_neg.mean():.0f}%")
        print("   elérte a stop előtt: " + "  ".join(
            f"{f} ATR15 → {100*exc[f'el_{f}atr'].mean():.0f}%" for f in FAV_ATR)
            + f"  |  helyből negatív: {100*exc.helybol_neg.mean():.0f}%")
        rs = exc[exc.race_stopped]
        print(f"   VERSENY fix 1,5 ATR15 stoppal: −1,5 ATR-be fut {100*exc.race_stopped.mean():.0f}%; "
              f"a −1,5 ATR ELŐTT elér: " + "  ".join(
              f"+{f} ATR → {100*exc[f'race_{f}'].mean():.0f}%" for f in FAV_ATR)
              + (f";  a stopba futók MFE-mediánja {rs.race_mfe_atr.median():.2f} ATR15 "
                 f"= {rs.race_mfe_pts.median():.0f} pt" if len(rs) else ""))

    # ── összesítő: óra × pár mátrix ──────────────────────────────────────
    O = pd.concat(osszes_ora, ignore_index=True)
    print("\n\n════ ÖSSZESÍTŐ — R/kötés óra × pár (n ≥ 15, különben ·) ════")
    piv = O.pivot(index="óra(szerver)", columns="sym", values="R")
    nn = O.pivot(index="óra(szerver)", columns="sym", values="n")
    print(piv.where(nn >= 15).round(2).fillna("·").to_string())
    print("\n════ ÖSSZESÍTŐ — kötésszám óra × pár ════")
    print(nn.fillna(0).astype(int).to_string())

    B = pd.concat(osszes_blokk, ignore_index=True)
    _ord = [b[0] for b in BLOKK]
    print("\n════ ÖSSZESÍTŐ — R/kötés NAPSZAK × pár (n ≥ 30, különben ·) ════")
    pb = B.pivot(index="blokk", columns="sym", values="R").reindex(_ord)
    nb = B.pivot(index="blokk", columns="sym", values="n").reindex(_ord)
    print(pb.where(nb >= 30).round(2).fillna("·").to_string())
    print("\n════ ÖSSZESÍTŐ — kötésszám NAPSZAK × pár ════")
    print(nb.fillna(0).astype(int).to_string())
    print(chr(10) + "==== OSSZESITO - [+1 ATR15 a -1,5 ATR15 elott] % NAPSZAK x par ====")
    print(B.pivot(index="blokk", columns="sym", values="+1ATR_előbb%")
          .reindex(_ord).where(nb >= 30).fillna("·").to_string())

    E = pd.concat(osszes_exc, ignore_index=True)
    print("\n════ ÖSSZESÍTŐ — MFE a stop előtt, páronként ════")
    t = E.groupby("sym").agg(n=("i", "size"), stop_pct=("stopped", "mean"),
                             mfe_med_pts=("mfe_pts", "median"),
                             mfe_med_atr=("mfe_atr", "median"),
                             mfe_med_R=("mfe_R", "median"),
                             helybol_neg=("helybol_neg", "mean"),
                             el_025=("el_0.25atr", "mean"), el_05=("el_0.5atr", "mean"),
                             el_1=("el_1.0atr", "mean"), el_2=("el_2.0atr", "mean"),
                             race_stop=("race_stopped", "mean"),
                             race_mfe_atr=("race_mfe_atr", "median"),
                             r025=("race_0.25", "mean"), r05=("race_0.5", "mean"),
                             r1=("race_1.0", "mean"), r2=("race_2.0", "mean"))
    for c_ in ("stop_pct", "helybol_neg", "el_025", "el_05", "el_1", "el_2",
               "race_stop", "r025", "r05", "r1", "r2"):
        t[c_] = (100 * t[c_]).round(0)
    print(t.round(2).to_string())


if __name__ == "__main__":
    main()

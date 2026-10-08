"""Hany HH/HL (ill. LL/LH) labbol all egy trend? — 2026-10-02.

A felhasznalo kerdese: "H1: 1 lab - 400 db, 2 lab - 800 db ..." eloszlas
idosikonkent, es hogy ehhez kepest hanyadik labnal lepunk be.

Definiciok (pivot k=3, a swing_mtf-fel azonos):
  SZIGORU (Dow): emelkedo trend labja = uj igazolt csucs > elozo csucs, mikozben
    az utolso igazolt volgy > az elozo volgy. A trend VEGE: az elso nem-magasabb
    csucs (LH) VAGY az elso alacsonyabb volgy (LL). Eso: tukor.
  ENGEDEKENY: a trend csak az ellen-iranyu toresnel (emelkedonel LL) er veget;
    az LH nem zarja le, csak nem ad labat.
Kimenet trendenkent: labszam, idotartam (ora), mozgas ATR-ben (a trend elotti
utolso volgytol a legmagasabb csucsig).

NULL: ugyanazok a gyertyak OSSZEKEVERT sorrendben (a gyertyak merete/alakja
megmarad, a sorrendi fuggoseg eltunik) — ha a valodi piacon nem tartanak
tovabb a trendek, mint itt, akkor a "trend" nem tobb a veletlennel.
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
from swing_mtf import pivots, SYMS, K


def shuffled(d: pd.DataFrame, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    c = d["close"].to_numpy(float)
    dc = np.diff(c, prepend=c[0])
    hi = d["high"].to_numpy(float) - c
    lo = d["low"].to_numpy(float) - c
    p = rng.permutation(len(c))
    nc = c[0] + np.cumsum(dc[p])
    return pd.DataFrame({"high": nc + hi[p], "low": nc + lo[p], "close": nc},
                        index=d.index)


def signflip(d: pd.DataFrame, seed=0) -> pd.DataFrame:
    """Szigorubb null: a gyertyak SORRENDJE es MERETE marad (volatilitas-csomosodas,
    napszak, hetvege), csak az IRANYUK veletlen (+/-). A felfele/lefele kanoc is
    tukrozodik, ha az irany megfordul."""
    rng = np.random.default_rng(seed)
    c = d["close"].to_numpy(float)
    dc = np.diff(c, prepend=c[0])
    hi = d["high"].to_numpy(float) - c
    lo = d["low"].to_numpy(float) - c
    sg = rng.choice([-1.0, 1.0], size=len(c))
    nc = c[0] + np.cumsum(dc * sg)
    nh = np.where(sg > 0, hi, -lo)
    nl = np.where(sg > 0, lo, -hi)
    return pd.DataFrame({"high": nc + nh, "low": nc + nl, "close": nc}, index=d.index)


def runs(d: pd.DataFrame, lenient=False):
    h = d["high"].to_numpy(float)
    l = d["low"].to_numpy(float)
    c = d["close"].to_numpy(float)
    a = lab.atr(h, l, c, 14)
    ih, il = pivots(h, l, K)
    ev = sorted([(i, 1, h[i]) for i in np.flatnonzero(ih)] +
                [(i, -1, l[i]) for i in np.flatnonzero(il)])
    ts = d.index
    out = []
    H = [np.nan, np.nan]          # [elozo, utolso] csucs ar
    L = [np.nan, np.nan]
    Hi = Li = 0                   # utolso csucs/volgy bar-indexe
    st = {1: [0, 0, 0.0, 0.0], -1: [0, 0, 0.0, 0.0]}   # legs, start_i, start_px, extr

    def close(dr, end):
        legs, i0, p0, ex = st[dr]
        if legs > 0:
            mv = (ex - p0) * dr / a[i0] if a[i0] > 0 else np.nan
            out.append((dr, legs, (ts[end] - ts[i0]).total_seconds() / 3600, mv, ts[i0]))
        st[dr][0] = 0

    for i, kind, px in ev:
        if kind == 1:                                   # uj csucs
            if not np.isnan(H[1]):
                if px > H[1]:                           # HH
                    close(-1, i)                        # eso trend vege
                    if lenient or L[1] > L[0]:          # HL-lel egyutt -> lab
                        u = st[1]
                        if u[0] == 0:
                            u[1], u[2], u[3] = Li, L[1], px
                        u[0] += 1; u[3] = max(u[3], px)
                elif not lenient:                       # LH -> szigoruan vege
                    close(1, i)
            H = [H[1], px]; Hi = i
        else:                                           # uj volgy
            if not np.isnan(L[1]):
                if px < L[1]:                           # LL
                    close(1, i)
                    if lenient or H[1] < H[0]:
                        dd = st[-1]
                        if dd[0] == 0:
                            dd[1], dd[2], dd[3] = Hi, H[1], px
                        dd[0] += 1; dd[3] = min(dd[3], px)
                elif not lenient:                       # HL -> eso szigoruan vege
                    close(-1, i)
            L = [L[1], px]; Li = i
    return pd.DataFrame(out, columns=["dir", "legs", "hours", "move_atr", "start"])


def leg_records(d: pd.DataFrame):
    """Laponkenti (szigoru definicio) meret: lendulet ATR-ben (az elozo ellen-swingtol
    az uj csucsig/volgyig), visszahuzodas aranya (a kovetkezo ellen-swing / a lendulet;
    >1 = a trend megtort), es hogy jott-e meg lab (cont)."""
    h = d["high"].to_numpy(float)
    l = d["low"].to_numpy(float)
    c = d["close"].to_numpy(float)
    a = lab.atr(h, l, c, 14)
    ih, il = pivots(h, l, K)
    ev = sorted([(i, 1, h[i]) for i in np.flatnonzero(ih)] +
                [(i, -1, l[i]) for i in np.flatnonzero(il)])
    ts = d.index
    out = []
    H = [np.nan, np.nan]
    L = [np.nan, np.nan]
    cur = {1: [], -1: []}
    Hi = Li = 0

    def close(dr):
        out.extend(cur[dr]); cur[dr] = []

    def add(dr, i, px, base, bi):
        if cur[dr]:
            cur[dr][-1]["cont"] = True
        prev = cur[dr][-1]["impulse"] if cur[dr] else np.nan
        imp = (px - base) * dr / a[i] if a[i] > 0 else np.nan
        cur[dr].append(dict(dir=dr, n=len(cur[dr]) + 1, impulse=imp, prev_imp=prev,
                            extr=px, base=base, retrace=np.nan, cont=False, time=ts[i],
                            base_time=ts[bi]))

    for i, kind, px in ev:
        opp = -kind                       # ez a swing az ellen-irany utolso labjanak visszahuzodasa
        if cur[opp] and np.isnan(cur[opp][-1]["retrace"]):
            r = cur[opp][-1]
            span = (r["extr"] - r["base"]) * opp
            if span > 0:
                r["retrace"] = (r["extr"] - px) * opp / span
        if kind == 1:
            if not np.isnan(H[1]):
                if px > H[1]:
                    close(-1)
                    if L[1] > L[0]:
                        add(1, i, px, L[1], Li)
                else:
                    close(1)
            H = [H[1], px]; Hi = i
        else:
            if not np.isnan(L[1]):
                if px < L[1]:
                    close(1)
                    if H[1] < H[0]:
                        add(-1, i, px, H[1], Hi)
                else:
                    close(-1)
            L = [L[1], px]; Li = i
    close(1); close(-1)
    return pd.DataFrame(out)


if __name__ == "__main__" and "--legs" in _sys.argv:
    rows = []
    for s in SYMS:
        m1 = lab.load_m1(s)
        for tf, mins in (("M15", 15), ("H1", 60), ("H4", 240)):
            d = lab.resample(m1, mins)
            for src, dd in (("piac", d), ("kevert", shuffled(d))):
                r = leg_records(dd)
                r["sym"], r["tf"], r["src"] = s, tf, src
                rows.append(r)
        print(s, flush=True)
    out = pd.concat(rows, ignore_index=True)
    out.to_parquet(_BP.research_dir() / "swing_leg_size.parquet")
    print("kesz", len(out))
elif __name__ == "__main__":
    rows = []
    for s in SYMS:
        m1 = lab.load_m1(s)
        for tf, mins in (("M15", 15), ("H1", 60), ("H4", 240)):
            d = lab.resample(m1, mins)
            for src, dd in (("piac", d), ("kevert", shuffled(d))):
                for mode in ("szigoru", "engedekeny"):
                    r = runs(dd, lenient=(mode == "engedekeny"))
                    r["sym"], r["tf"], r["src"], r["mode"] = s, tf, src, mode
                    rows.append(r)
        print(s, flush=True)
    out = pd.concat(rows, ignore_index=True)
    out.to_parquet(_BP.research_dir() / "swing_trend_length.parquet")
    print("kesz", len(out))

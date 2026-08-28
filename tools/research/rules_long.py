"""Belepo-szabalyok a HOSSZU mintas szureshez.

Mind a `gates_lab.build` kontextusan dolgozik (M15), KAUZALISAN.
Vissza: (bar-indexek, +1/-1 irany).
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

import rules as R


def _fire_first(cond_up, cond_dn, cooldown=0):
    """Felfegyverez -> tuzel: csak az ELSO atlepesnel (nem minden baron)."""
    raw = np.where(cond_up, 1, np.where(cond_dn, -1, 0))
    prev = np.concatenate([[0], raw[:-1]])
    fire = (raw != 0) & (prev != raw)
    idx = np.nonzero(fire)[0]
    if cooldown and len(idx):
        keep, last = [], -10 ** 9
        for i in idx:
            if i - last >= cooldown:
                keep.append(i); last = i
        idx = np.array(keep, np.int64)
    return idx, raw[idx].astype(np.int8)


# ── 1. Donchian kitores / fade ──────────────────────────────────────────────
def donchian(C, N=48, fade=False):
    h, l, c = C["h"], C["l"], C["c"]
    hi = pd.Series(h).rolling(N).max().shift(1).to_numpy()
    lo = pd.Series(l).rolling(N).min().shift(1).to_numpy()
    i, s = _fire_first(c > hi, c < lo)
    return i, (s * (-1 if fade else 1)).astype(np.int8)


# ── 2. SMA-tavolsag (z) fade / folytatas ────────────────────────────────────
def zrule(C, n=100, k=2.0, fade=True):
    c, atr = C["c"], C["atr"]
    z = (c - pd.Series(c).rolling(n).mean().to_numpy()) / atr
    i, s = _fire_first(z >= k, z <= -k, cooldown=8)
    return i, (s * (-1 if fade else 1)).astype(np.int8)


# ── 3. Gyertya-sorozat fade / folytatas ─────────────────────────────────────
def streak(C, k=5, fade=True):
    o = C["d"]["open"].to_numpy(float)
    c = C["c"]
    up = pd.Series(c > o).rolling(k).sum().to_numpy() == k
    dn = pd.Series(c < o).rolling(k).sum().to_numpy() == k
    i, s = _fire_first(up, dn, cooldown=k)
    return i, (s * (-1 if fade else 1)).astype(np.int8)


# ── 4. Elozo NAPI csucs/melypont attorese ───────────────────────────────────
def pd_break(C, fade=False):
    d = C["d"]
    day = d.index.normalize()
    hi = d["high"].groupby(day).max().shift(1).reindex(day).to_numpy()
    lo = d["low"].groupby(day).min().shift(1).reindex(day).to_numpy()
    i, s = _fire_first(C["c"] > hi, C["c"] < lo, cooldown=4)
    return i, (s * (-1 if fade else 1)).astype(np.int8)


# ── 5. Szukules utani kitores (Bollinger-szeru) ─────────────────────────────
def squeeze(C, look=48, pct=0.25, fade=False):
    h, l, c = C["h"], C["l"], C["c"]
    rng = pd.Series(h - l).rolling(look).mean()
    q = rng.rolling(500).rank(pct=True).to_numpy()
    hi = pd.Series(h).rolling(look).max().shift(1).to_numpy()
    lo = pd.Series(l).rolling(look).min().shift(1).to_numpy()
    quiet = q <= pct
    i, s = _fire_first(quiet & (c > hi), quiet & (c < lo), cooldown=look // 2)
    return i, (s * (-1 if fade else 1)).astype(np.int8)


# ── 6. WPR szelsoertek (a wpr_sma rokona) ───────────────────────────────────
def wpr_extreme(C, n=14, lo_thr=-90.0, hi_thr=-10.0, fade=True):
    h, l, c = C["h"], C["l"], C["c"]
    hh = pd.Series(h).rolling(n).max().to_numpy()
    ll = pd.Series(l).rolling(n).min().to_numpy()
    rngv = np.where(hh - ll > 0, hh - ll, np.nan)
    w = -100.0 * (hh - c) / rngv
    i, s = _fire_first(w >= hi_thr, w <= lo_thr, cooldown=8)
    return i, (s * (-1 if fade else 1)).astype(np.int8)


# ── 7. VWAP-tol valo elszakadas ─────────────────────────────────────────────
def vwap_stretch(C, k=2.0, fade=True):
    d = C["d"]
    day = d.index.normalize()
    v = d["volume"].to_numpy(float)
    tp = (C["h"] + C["l"] + C["c"]) / 3
    cv = pd.Series(v, index=d.index).groupby(day).cumsum().to_numpy()
    ct = pd.Series(tp * v, index=d.index).groupby(day).cumsum().to_numpy()
    vw = np.where(cv > 0, ct / np.where(cv > 0, cv, 1), np.nan)
    z = (C["c"] - vw) / C["atr"]
    i, s = _fire_first(z >= k, z <= -k, cooldown=8)
    return i, (s * (-1 if fade else 1)).astype(np.int8)


# ── 8. Harom lepeses trendfordulo (a tananyagbol) ───────────────────────────
def three_step(C, **kw):
    i, s, _ = R.three_step(C, **kw)
    return i, s


def trendline_break(C, **kw):
    i, s, _ = R.three_step_partial(C, **kw)
    return i, s


# ── a szures teljes keszlete ────────────────────────────────────────────────
CATALOG = {}
for N in (24, 48, 96):
    CATALOG[f"donchian{N}_tores"] = (lambda C, N=N: donchian(C, N))
    CATALOG[f"donchian{N}_fade"] = (lambda C, N=N: donchian(C, N, fade=True))
for k in (1.5, 2.5):
    CATALOG[f"z{k}_fade"] = (lambda C, k=k: zrule(C, k=k))
    CATALOG[f"z{k}_folyt"] = (lambda C, k=k: zrule(C, k=k, fade=False))
for k in (5, 8):
    CATALOG[f"sorozat{k}_fade"] = (lambda C, k=k: streak(C, k))
    CATALOG[f"sorozat{k}_folyt"] = (lambda C, k=k: streak(C, k, fade=False))
CATALOG["elozonap_tores"] = pd_break
CATALOG["elozonap_fade"] = lambda C: pd_break(C, fade=True)
CATALOG["szukules_tores"] = squeeze
CATALOG["szukules_fade"] = lambda C: squeeze(C, fade=True)
CATALOG["wpr14_fade"] = wpr_extreme
CATALOG["wpr14_folyt"] = lambda C: wpr_extreme(C, fade=False)
CATALOG["vwap2_fade"] = vwap_stretch
CATALOG["vwap2_folyt"] = lambda C: vwap_stretch(C, fade=False)
CATALOG["3lepeses_fordulo"] = three_step
CATALOG["trendvonal_tores"] = trendline_break

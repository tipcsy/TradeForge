"""Belepo-szabalyok, koztuk a tananyag 3 LEPESES TRENDFORDULOJA.

Mind M15 baron dolgozik, KAUZALISAN: a pivot csak k barral kesobb valik
ismertte, a trendvonal csak mar ismert pivotokra illeszkedik.
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


def _pivots(h, l, k=3):
    n = len(h)
    ih = np.zeros(n, bool); il = np.zeros(n, bool)
    for i in range(k, n - k):
        if h[i] == h[i - k:i + k + 1].max():
            ih[i] = True
        if l[i] == l[i - k:i + k + 1].min():
            il[i] = True
    return ih, il


# ── 1. HAROM LEPESES TRENDFORDULO (tananyag: TK-002) ────────────────────────
def three_step(C, k=3, n_fit=3, buf_atr=0.10, corr_atr=0.5, win=60):
    """1) trendvonal-tores  2) lathato korrekcio  3) uj csucs.

    Eso trendbol bikas fordulo (a SELL a tukorkepe):
      * a trendvonal az utolso `n_fit` swing HIGH-ra illesztett egyenes,
      * tores: Close > vonal + buf_atr*ATR,
      * korrekcio: a torestol szamitott csucsbol legalabb corr_atr*ATR visszahuzodas,
      * uj csucs: Close > az utolso swing high ZAROARA (a tananyag zaroarhoz mer).
    Mindharom lepesnek `win` baron belul kell megtortennie."""
    h, l, c, atr = C["h"], C["l"], C["c"], C["atr"]
    n = len(c)
    ih, il = _pivots(h, l, k)
    hi_i, lo_i = [], []
    idx, side, stage_hit = [], [], []
    # allapotgep iranyonkent
    st = {1: dict(phase=0, t0=0, ext=np.nan, ref=np.nan),
          -1: dict(phase=0, t0=0, ext=np.nan, ref=np.nan)}
    for i in range(n):
        j = i - k                                   # a pivot csak most ismert
        if j >= 0:
            if ih[j]:
                hi_i.append(j)
            if il[j]:
                lo_i.append(j)
        if not np.isfinite(atr[i]) or len(hi_i) < n_fit or len(lo_i) < n_fit:
            continue
        for d in (1, -1):
            s = st[d]
            pts = hi_i[-n_fit:] if d > 0 else lo_i[-n_fit:]
            x = np.array(pts, float)
            y = np.array([h[p] for p in pts] if d > 0 else [l[p] for p in pts])
            if len(np.unique(x)) < 2:
                continue
            a_, b_ = np.polyfit(x, y, 1)
            line = a_ * i + b_
            # a trendvonalnak a fordulattal ELLENTETES iranyba kell mutatnia
            trend_ok = (a_ < 0) if d > 0 else (a_ > 0)
            if s["phase"] == 0:
                if trend_ok and ((c[i] > line + buf_atr * atr[i]) if d > 0
                                 else (c[i] < line - buf_atr * atr[i])):
                    s.update(phase=1, t0=i, ext=c[i],
                             ref=(c[hi_i[-1]] if d > 0 else c[lo_i[-1]]))
            elif s["phase"] == 1:                   # varjuk a korrekciot
                if i - s["t0"] > win:
                    s["phase"] = 0; continue
                s["ext"] = max(s["ext"], c[i]) if d > 0 else min(s["ext"], c[i])
                back = (s["ext"] - c[i]) if d > 0 else (c[i] - s["ext"])
                if back >= corr_atr * atr[i]:
                    s["phase"] = 2
            elif s["phase"] == 2:                   # varjuk az uj csucsot
                if i - s["t0"] > win:
                    s["phase"] = 0; continue
                ref = c[hi_i[-1]] if d > 0 else c[lo_i[-1]]
                if (c[i] > max(ref, s["ext"])) if d > 0 else (c[i] < min(ref, s["ext"])):
                    idx.append(i); side.append(d); stage_hit.append(3)
                    s["phase"] = 0
    return np.array(idx, np.int64), np.array(side, np.int8), np.array(stage_hit)


def three_step_partial(C, stop_at=1, **kw):
    """Ugyanaz, de csak `stop_at` lepesig varunk (1 = puszta trendvonal-tores).
    A tananyag allitasa: minel tobb lepes, annal jobb -- ezt merjuk."""
    h, l, c, atr = C["h"], C["l"], C["c"], C["atr"]
    k = kw.get("k", 3); n_fit = kw.get("n_fit", 3); buf = kw.get("buf_atr", 0.10)
    n = len(c)
    ih, il = _pivots(h, l, k)
    hi_i, lo_i = [], []
    idx, side = [], []
    last = {1: -10 ** 9, -1: -10 ** 9}
    for i in range(n):
        j = i - k
        if j >= 0:
            if ih[j]:
                hi_i.append(j)
            if il[j]:
                lo_i.append(j)
        if not np.isfinite(atr[i]) or len(hi_i) < n_fit or len(lo_i) < n_fit:
            continue
        for d in (1, -1):
            pts = hi_i[-n_fit:] if d > 0 else lo_i[-n_fit:]
            x = np.array(pts, float)
            y = np.array([h[p] for p in pts] if d > 0 else [l[p] for p in pts])
            if len(np.unique(x)) < 2:
                continue
            a_, b_ = np.polyfit(x, y, 1)
            line = a_ * i + b_
            trend_ok = (a_ < 0) if d > 0 else (a_ > 0)
            brk = (c[i] > line + buf * atr[i]) if d > 0 else (c[i] < line - buf * atr[i])
            if trend_ok and brk and i - last[d] > 20:
                idx.append(i); side.append(d); last[d] = i
    o = np.argsort(idx)
    return np.array(idx, np.int64)[o], np.array(side, np.int8)[o], None


# ── 2. Donchian tores (szerkezeti kitores) ──────────────────────────────────
def donchian(C, N=48, fade=False):
    h, l, c = C["h"], C["l"], C["c"]
    hi = pd.Series(h).rolling(N).max().shift(1).to_numpy()
    lo = pd.Series(l).rolling(N).min().shift(1).to_numpy()
    up = c > hi
    dn = c < lo
    raw = np.where(up, 1, np.where(dn, -1, 0))
    prev = np.concatenate([[0], raw[:-1]])
    fire = (raw != 0) & (prev != raw)
    idx = np.nonzero(fire)[0]
    s = raw[idx] * (-1 if fade else 1)
    return idx, s.astype(np.int8), None


# ── 3. z-fade (visszateres az SMA-hoz) ──────────────────────────────────────
def zfade(C, n=100, k=2.0, fade=True):
    c, atr = C["c"], C["atr"]
    sma = pd.Series(c).rolling(n).mean().to_numpy()
    z = (c - sma) / atr
    hot = np.abs(z) >= k
    prev = np.concatenate([[False], hot[:-1]])
    fire = hot & ~prev & np.isfinite(z)
    idx = np.nonzero(fire)[0]
    s = (-np.sign(z[idx]) if fade else np.sign(z[idx])).astype(np.int8)
    return idx, s, None

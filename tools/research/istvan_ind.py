"""István indikátorai Pythonban — a `mt5/istvan/*.mq5` pontos tükre (2026-10-07).

Mindkettő az MT4-es .ex4 feketedobozos kiírásából (`MQL4/Scripts/DumpIndicator.mq4`)
visszafejtve; `python istvan_ind.py` az MT4-es dumpokra ellenőriz (gyertyára).

  gann_state(h, l, c, n=10)          -> +1/-1/0 állapot
  nonlag(c, length=40, cycle=4, pct=1.0) -> (vonal, állapot)
"""
from __future__ import annotations

import numpy as np


def gann_state(h, l, c, n=10):
    """Close > SMA(High) / < SMA(Low) az ELŐZŐ n gyertyán; köztük marad."""
    h = np.asarray(h, float); l = np.asarray(l, float); c = np.asarray(c, float)
    ch = np.r_[0.0, np.cumsum(h)]
    cl = np.r_[0.0, np.cumsum(l)]
    N = len(c)
    st = np.zeros(N, np.int8)
    cur = 0
    for i in range(n, N):
        sh = (ch[i] - ch[i - n]) / n          # h[i-n .. i-1]
        sl = (cl[i] - cl[i - n]) / n
        if c[i] > sh:
            cur = 1
        elif c[i] < sl:
            cur = -1
        st[i] = cur
    return st


def nonlag_weights(length=40, cycle=4):
    phase = length - 1
    nw = length * cycle + phase - 1
    j = np.arange(nw)
    step2 = (2.0 * cycle - 1.0) / (cycle * length - 1.0)
    t = np.where(j <= phase - 1, j / (phase - 1), 1.0 + (j - (phase - 1)) * step2)
    g = np.where(t > 0.5, 1.0 / (3.0 * np.pi * t + 1.0), 1.0)
    return g * np.cos(np.pi * t)


def nonlag(c, length=40, cycle=4, pct=1.0):
    c = np.asarray(c, float)
    w = nonlag_weights(length, cycle)
    nw = len(w)
    N = len(c)
    ma = np.full(N, np.nan)
    tr = np.zeros(N, np.int8)
    if N <= nw + 1:
        return ma, tr
    raw = np.full(N, np.nan)
    raw[nw - 1:] = np.convolve(c, w, mode="valid") / w.sum()   # w[0] a legfrissebbre
    first = nw - 1
    ma[first] = raw[first]
    de = np.zeros(N)
    av = np.zeros(N)
    cur = 0
    for i in range(first + 1, N):
        prev = ma[i - 1]
        de[i] = abs(raw[i] - prev)
        lo = max(first + 1, i - length + 1)
        av[i] = de[lo:i + 1].mean()
        f = 0.0
        if pct > 0 and i > first + 1:
            f = pct * np.sqrt(np.mean((de[lo:i + 1] - av[lo:i + 1]) ** 2))
        m = prev if de[i] < f else raw[i]
        ma[i] = m
        if m - prev > f:
            cur = 1
        if prev - m > f:
            cur = -1
        tr[i] = cur
    return ma, tr


if __name__ == "__main__":
    import pandas as pd
    F = r"C:/Metatrades/ActiveTrades Metatrade 4/MQL4/Files/"
    g = pd.read_csv(F + "dump_GannHiLo-Histo2_GOLD_60.csv", sep=";")
    s = gann_state(g.high, g.low, g.close)
    print("Gann egyezés (11.-től):", (s[11:] == g.b2.values[11:]).mean())
    d = pd.read_csv(F + "dump_NonLagDot_GOLD_60.csv", sep=";")
    ma, tr = nonlag(d.close.values)
    k = slice(600, None)
    print("NonLag vonal max hiba (600.-tól):", np.nanmax(np.abs(ma[k] - d.b0.values[k])),
          "| állapot egyezés:", (tr[k] == d.b3.values[k]).mean())

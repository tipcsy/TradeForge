"""CSENDES SZERKEZETI ÁTTÖRÉS — a szabály EGY helyen (stratégia + kutató-labor).

Származás (2026-10-02, `tools/research/swing_*.py`): a HH/HL-szerkezet
vizsgálatából. A 2023+ adaton választott szűrő (csendes piac + ≥2 idősík-
együttállás) a FÜGGETLEN 2013–2022-es szakaszon előre rögzített küszöbökkel
átment: +10,9 / kötés (100 kockázat mellett), t = 1,65, 8/10 év, 4/5 instrumentum.
⚠ t < 2 → NYOM, nem bizonyíték; 2023 óta gyengébb (+4,3, nem veri szignifikánsan
a véletlen longot).

A SZABÁLY (csak LONG):
  1. Swing-pontok minden idősíkon: k=3 pivot (a gyertya magasabb/alacsonyabb a
     3 előtte és 3 utána lévőnél) — csak k gyertyával KÉSŐBB ismert.
  2. Szerkezet-állapot: +1 = az utolsó két igazolt csúcs HH ÉS az utolsó két
     völgy HL; −1 = LH+LL; 0 = vegyes.
  3. BELÉPŐ (M15): a záró ár ELŐSZÖR lép az utolsó igazolt M15-csúcs fölé, és
     előtte az M15-szerkezet NEM volt emelkedő (visszahúzódás volt).
  4. STOP: az utolsó igazolt M15-völgy; a táv 0,5–4 ATR(14) között, különben
     nincs belépő.
  5. EGYÜTTÁLLÁS: az M1, M5, H1, H4 közül legalább `min_align` emelkedő
     (a belépő M15-gyertya ZÁRÁSAKOR lezárt gyertyák szerint).
  6. CSENDES PIAC: M15 ATR(14) / ugyanazon (fal-óra szerinti) óra ATR-jének
     mediánja az előző ~20 napban (80 megfigyelés, 4-gyel eltolva) ≤ `vol_max`.

⚠ A kutatásban a belépő csak 10:00–20:59 között (magyar idő) élt, és 21:45-kor /
8 óra után ZÁRTUNK. Ezek NEM ennek a modulnak a részei: a napszak a KERET óra-
kapuja, a kilépés a kockázatcsökkentésé (lásd `strategy/base.py`). Ez a modul
minden órára ad jelzést; az óra-szűrést a hívó végzi.

⚠ Az ATR szándékosan a true range EGYSZERŰ mozgóátlaga (nem Wilder) — a mérés
így készült (`tools/research/lab.atr`).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ⚠ A gyertya-index KANONIKUS FAL-ÓRA (berlini = magyar helyi idő), csak „UTC"
# címkével tárolva (`core/broker_time.py`). Átváltani TILOS: 2026-10-02-ig itt
# Europe/Budapest állt, ami 1–2 órával eltolta az ablakot. Az „UTC" = nincs átváltás.
TZ = "UTC"
DEFAULTS = dict(pivot_k=3, atr_len=14, vol_max=0.78, min_align=2,
                sl_min_atr=0.5, sl_max_atr=4.0)


def resample(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    o = df.resample(f"{minutes}min", label="left", closed="left").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"))
    return o.dropna(subset=["close"])


def atr(h, l, c, n):
    pc = np.concatenate([[np.nan], c[:-1]])
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    return pd.Series(tr).rolling(n).mean().to_numpy()


def pivots(h, l, k):
    H, L = pd.Series(h), pd.Series(l)
    cmax = H.rolling(2 * k + 1, center=True).max().to_numpy()
    cmin = L.rolling(2 * k + 1, center=True).min().to_numpy()
    pmax = H.shift(1).rolling(k).max().to_numpy()
    pmin = L.shift(1).rolling(k).min().to_numpy()
    return (h == cmax) & (h > pmax), (l == cmin) & (l < pmin)


def structure(d: pd.DataFrame, k: int):
    """Bar-onként (a bar ZÁRÁSAKOR ismert): állapot, utolsó igazolt csúcs/völgy."""
    h = d["high"].to_numpy(float)
    l = d["low"].to_numpy(float)
    ih, il = pivots(h, l, k)
    n = len(h)
    st = np.zeros(n, np.int8)
    lH = np.full(n, np.nan)
    lL = np.full(n, np.nan)
    h1 = h2 = l1 = l2 = np.nan
    for i in range(k, n):
        p = i - k
        if ih[p]:
            h2, h1 = h1, h[p]
        if il[p]:
            l2, l1 = l1, l[p]
        if not np.isnan(h2) and not np.isnan(l2):
            hh, hl = h1 > h2, l1 > l2
            st[i] = 1 if (hh and hl) else (-1 if (not hh and not hl) else 0)
        lH[i] = h1
        lL[i] = l1
    return st, lH, lL


def state_at(times_close: np.ndarray, d: pd.DataFrame, minutes: int, st: np.ndarray):
    """A `d` idősík állapota a megadott ZÁRÁSI időpontokban (csak lezárt gyertyák)."""
    close_ts = (d.index + pd.Timedelta(minutes=minutes)).to_numpy()
    j = np.searchsorted(close_ts, times_close, side="right") - 1
    return np.where(j >= 0, st[np.clip(j, 0, None)], 0)


def vol_ratio(d15: pd.DataFrame, a: np.ndarray) -> np.ndarray:
    s = pd.Series(a, index=d15.index)
    hr = d15.index.tz_convert(TZ).hour
    base = s.groupby(hr).transform(
        lambda x: x.rolling(80, min_periods=40).median().shift(4))
    return (s / base).to_numpy()


def entry_table(df_m1: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
    """M15-gyertyánként (a NYITÓ idővel címkézve): `sig` (long belépő a gyertya
    zárásán), `sl_dist` (a stop távolsága ÁRBAN a záró ártól), és a feltételek
    külön (`align`, `vol`, `brk`) a kijelzéshez."""
    p = {**DEFAULTS, **(params or {})}
    k = int(p["pivot_k"])
    if df_m1.index.tz is None:
        df_m1 = df_m1.tz_localize("UTC")
    m1 = df_m1[["open", "high", "low", "close"]]
    d = resample(m1, 15)
    h = d["high"].to_numpy(float)
    l = d["low"].to_numpy(float)
    c = d["close"].to_numpy(float)
    a = atr(h, l, c, int(p["atr_len"]))
    st, lH, lL = structure(d, k)
    t_close = (d.index + pd.Timedelta(minutes=15)).to_numpy()
    align = np.zeros(len(d), np.int8)
    for mins, src in ((1, m1), (5, resample(m1, 5)), (60, resample(m1, 60)),
                      (240, resample(m1, 240))):
        align += (state_at(t_close, src, mins, structure(src, k)[0]) == 1).astype(np.int8)
    vr = vol_ratio(d, a)
    n = len(c)
    brk = np.zeros(n, bool)
    sl = np.full(n, np.nan)
    broken_hi = np.nan
    for i in range(k + 1, n):
        if not (c[i] > lH[i] and c[i - 1] <= lH[i]) or lH[i] == broken_hi:
            continue
        if st[i] == 1:                       # nem volt visszahúzódás
            continue
        broken_hi = lH[i]
        risk = c[i] - lL[i]
        if not (np.isfinite(a[i]) and a[i] > 0 and np.isfinite(risk)):
            continue
        if not (p["sl_min_atr"] * a[i] <= risk <= p["sl_max_atr"] * a[i]):
            continue
        brk[i] = True
        sl[i] = risk
    sig = brk & (align >= int(p["min_align"])) & (vr <= float(p["vol_max"]))
    return pd.DataFrame({"sig": sig, "sl_dist": np.where(sig, sl, np.nan),
                         "brk": brk, "align": align, "vol": vr, "close": c},
                        index=d.index)


def m1_signal(df_m1: pd.DataFrame, tab: pd.DataFrame) -> np.ndarray:
    """A belépő az M15-gyertya ZÁRÁSA utáni ELSŐ M1-soron (esemény, nem állapot)."""
    out = np.zeros(len(df_m1), bool)
    t = tab.index[tab["sig"].to_numpy()] + pd.Timedelta(minutes=15)
    if len(t) == 0:
        return out
    idx = df_m1.index if df_m1.index.tz is not None else df_m1.index.tz_localize("UTC")
    j = np.searchsorted(idx, t, side="left")
    j = j[j < len(out)]
    out[j] = True
    return out

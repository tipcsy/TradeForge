"""Kutatasi harness: gyors, fuggetlen M1 szimulator, ami a TradeForge backtest
vegrehajtasi konvencioit koveti (bid gyertyak, ask = bid + spread, belepo a
gyertya zarasan, BUY ask-on nyit / bid-en zar, SELL bid-en nyit / ask-on zar).

Nem a projekt kodja - csak otletek szuresehez. Ami tulel, azt portoljuk a
strategy/ csomagba.
"""
from __future__ import annotations

# A repobol futtathato: a projekt gyokere ES a testvermodulok a sys.path-ra.
import sys as _sys
from pathlib import Path as _Path
ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))


import io
import json
import numpy as np
import pandas as pd
from pathlib import Path

CFG = json.load(io.open(ROOT / "config.json", encoding="utf-8"))
PAIRS = {k: v for k, v in CFG["pairs"].items() if k != "_comment"}

_CACHE: dict[str, pd.DataFrame] = {}


def load_m1(sym: str) -> pd.DataFrame:
    if sym not in _CACHE:
        df = pd.read_parquet(ROOT / "data" / "m1" / f"{sym}.parquet")
        df = df[~df.index.duplicated(keep="last")].sort_index()
        _CACHE[sym] = df
    return _CACHE[sym]


def resample(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """M1 -> nagyobb TF (zart gyertyak, a bar cimkeje a NYITO ideje)."""
    o = df.resample(f"{minutes}min", label="left", closed="left").agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum"),
        avg_spread=("avg_spread", "mean"), close_spread=("close_spread", "last"))
    return o.dropna(subset=["close"])


# ---------------------------------------------------------------------------
# indikatorok (numpy)
# ---------------------------------------------------------------------------

def sma(a, n):
    s = pd.Series(a)
    return s.rolling(n).mean().to_numpy()


def ema(a, n):
    return pd.Series(a).ewm(span=n, adjust=False).mean().to_numpy()


def atr(h, l, c, n):
    pc = np.concatenate([[np.nan], c[:-1]])
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    return pd.Series(tr).rolling(n).mean().to_numpy()


def rolling_max(a, n):
    return pd.Series(a).rolling(n).max().to_numpy()


def rolling_min(a, n):
    return pd.Series(a).rolling(n).min().to_numpy()


def wpr(h, l, c, n):
    hh = rolling_max(h, n)
    ll = rolling_min(l, n)
    rng = np.where(hh - ll == 0, np.nan, hh - ll)
    return -100.0 * (hh - c) / rng


def rsi(c, n):
    d = np.diff(c, prepend=np.nan)
    up = pd.Series(np.where(d > 0, d, 0.0)).ewm(alpha=1 / n, adjust=False).mean()
    dn = pd.Series(np.where(d < 0, -d, 0.0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).to_numpy()


def adx(h, l, c, n):
    up = np.diff(h, prepend=np.nan)
    dn = -np.diff(l, prepend=np.nan)
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    pc = np.concatenate([[np.nan], c[:-1]])
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    atrn = pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * pd.Series(plus).ewm(alpha=1 / n, adjust=False).mean() / atrn
    mdi = 100 * pd.Series(minus).ewm(alpha=1 / n, adjust=False).mean() / atrn
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean().to_numpy(), pdi.to_numpy(), mdi.to_numpy()


# ---------------------------------------------------------------------------
# szimulator
# ---------------------------------------------------------------------------

TRADE_DTYPE = [
    ("i_open", np.int64), ("i_close", np.int64), ("dir", np.int8),
    ("entry", np.float64), ("exit", np.float64), ("sl", np.float64),
    ("tp", np.float64), ("r", np.float64), ("pts", np.float64),
    ("status", np.int8),  # 0=sl 1=tp 2=time/eod 3=trail/be
]


def simulate(df: pd.DataFrame, idx: np.ndarray, side: np.ndarray,
             sl_pts: np.ndarray, tp_pts: np.ndarray, point_size: float,
             max_hold: int = 480, eod_min: int | None = None,
             be_at_r: float = 0.0, trail_r: float = 0.0,
             spread_fallback_pts: float = 0.0,
             one_at_a_time: bool = True) -> np.ndarray:
    """M1 bar-szintu szimulacio. `idx`: belepo bar indexek (a bar ZARASAN lepunk be).
    `side`: +1 BUY / -1 SELL. `sl_pts`/`tp_pts`: tavolsag PONTBAN (tp<=0 -> nincs TP).
    `eod_min`: ha nem None, a nap ezen perce (UTC perc a nap kezdetetol) utan
    piaci zaras. `be_at_r`: ennyi R-nel a stop belepore. `trail_r`: >0 -> ennyi R
    tavolsagra huzo stop, miutan a BE aktivalt.
    Visszaad: strukturalt tomb.
    """
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    sp = (df["avg_spread"].to_numpy(float) if "avg_spread" in df else
          np.full(len(df), spread_fallback_pts * point_size))
    csp = (df["close_spread"].to_numpy(float) if "close_spread" in df else sp)
    sp = np.where(np.isfinite(sp) & (sp > 0), sp, spread_fallback_pts * point_size)
    csp = np.where(np.isfinite(csp) & (csp > 0), csp, sp)
    minute_of_day = (df.index.hour * 60 + df.index.minute).to_numpy()
    day_id = df.index.normalize().view("int64")

    n = len(df)
    out = np.zeros(len(idx), dtype=TRADE_DTYPE)
    k = 0
    busy_until = -1
    for t in range(len(idx)):
        i = int(idx[t])
        if one_at_a_time and i <= busy_until:
            continue
        d = int(side[t])
        slp = sl_pts[t] * point_size
        tpp = tp_pts[t] * point_size
        if not (slp > 0):
            continue
        entry = c[i] + (csp[i] if d > 0 else 0.0)
        sl = entry - d * slp
        tp = entry + d * tpp if tpp > 0 else np.nan
        end = min(n - 1, i + max_hold)
        j = i + 1
        status, xprice, moved_be = 2, np.nan, False
        while j <= end:
            if d > 0:
                bh, bl = h[j], l[j]
            else:
                bh, bl = h[j] + sp[j], l[j] + sp[j]
            # stop elobb (konzervativ)
            hit_sl = (bl <= sl) if d > 0 else (bh >= sl)
            hit_tp = (np.isfinite(tp) and ((bh >= tp) if d > 0 else (bl <= tp)))
            if hit_sl:
                status = 3 if moved_be else 0
                xprice = sl
                break
            if hit_tp:
                status, xprice = 1, tp
                break
            # BE / trailing (a KILEPESI oldalon merunk)
            if be_at_r > 0 or trail_r > 0:
                fav = (bh - entry) if d > 0 else (entry - bl)
                if be_at_r > 0 and not moved_be and fav >= be_at_r * slp:
                    nsl = entry
                    if (d > 0 and nsl > sl) or (d < 0 and nsl < sl):
                        sl = nsl
                    moved_be = True
                if trail_r > 0 and moved_be:
                    nsl = (bh - trail_r * slp) if d > 0 else (bl + trail_r * slp)
                    if (d > 0 and nsl > sl) or (d < 0 and nsl < sl):
                        sl = nsl
            # nap vege
            if eod_min is not None and (minute_of_day[j] >= eod_min or
                                        (j + 1 <= end and day_id[j + 1] != day_id[i])):
                status = 2
                xprice = c[j] + (0.0 if d > 0 else sp[j])
                break
            j += 1
        if not np.isfinite(xprice):
            j = min(j, end)
            xprice = c[j] + (0.0 if d > 0 else sp[j])
            status = 2
        pts = d * (xprice - entry) / point_size
        out[k] = (i, j, d, entry, xprice, sl, tp, pts / (sl_pts[t]), pts, status)
        k += 1
        busy_until = j
    return out[:k]


# ---------------------------------------------------------------------------
# metrikak
# ---------------------------------------------------------------------------

def stats(tr: np.ndarray, df: pd.DataFrame | None = None, label: str = "") -> dict:
    if len(tr) == 0:
        return {"label": label, "n": 0}
    r = tr["r"]
    wins, losses = r[r > 0], r[r <= 0]
    gp, gl = wins.sum(), -losses.sum()
    d = {
        "label": label, "n": len(r), "R": float(r.sum()),
        "R/trade": float(r.mean()), "win%": float(100 * len(wins) / len(r)),
        "PF": float(gp / gl) if gl > 0 else float("inf"),
        "maxDD_R": float(_maxdd(np.cumsum(r))),
    }
    # t-statisztika (0 atlag ellen)
    if len(r) > 2 and r.std() > 0:
        d["t"] = float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r))))
    return d


def _maxdd(eq):
    peak = np.maximum.accumulate(eq)
    return float((peak - eq).max()) if len(eq) else 0.0


def fmt(rows) -> str:
    if not rows:
        return "(ures)"
    cols = ["label", "n", "R", "R/trade", "win%", "PF", "maxDD_R", "t"]
    lines = ["  ".join(f"{c:>9}" if c != "label" else f"{c:<26}" for c in cols)]
    for d in rows:
        cells = []
        for c in cols:
            v = d.get(c, "")
            if c == "label":
                cells.append(f"{str(v):<26}")
            elif isinstance(v, float):
                cells.append(f"{v:>9.2f}")
            else:
                cells.append(f"{str(v):>9}")
        lines.append("  ".join(cells))
    return "\n".join(lines)


def daily(tr: np.ndarray, df: pd.DataFrame) -> pd.Series:
    if len(tr) == 0:
        return pd.Series(dtype=float)
    t = df.index[tr["i_close"]]
    return pd.Series(tr["r"], index=t).groupby(pd.Series(t).dt.date.values).sum()

"""Törött árak kiszűrése a gyertya-építésben — EGY hely, minden író út ezt hívja.

⚠ MIÉRT (2026-10-07): a bróker tick-előzményében TÖRÖTT árak vannak — GOLD és
USDJPY 2016-05-20 13:00–13:08: bid = 0,34 / 0,341 (a valódi ár ~1256 / ~110,4),
az ask is szemét. A gyertyába bekerülve egy kutatási kötés 1256 $-os stoppal
9 évig nyitva maradt, a tükör-kontrollok +458 R-t kaptak. A GerMid50-en
2026-09-22 10:59/11:04 két magányos (1 tick, 0,45-ös spread a szokásos ~47
helyett) jegyzés 4%-kal a piac alatt.

⚠ A KÜSZÖB SZÁNDÉKOSAN TÁG. Egy 3%-os „kiugrás-szűrő" VALÓDI mozgásokat dob ki
(2025-04-07 16:13 vámhír minden indexen, 2020-03-16, CPI-napok 14:30-kor,
2018-02-05, GOLD 2015-07-20 flash crash) — mérve, 25 instrumentum M1-jén. Ezért
két, egymástól független szabály:

  1. LEHETETLEN ÁR: az ár > 50%-kal tér el a környező piaci mediántól (vagy ≤ 0).
     Tick-szinten: a tick eldobva (a jó tickekből épül a gyertya); ha csak az ask
     törött, a tick marad, a spreadje érvénytelen. Gyertya-szinten (natív,
     tick nélküli gyertya): a gyertya eldobva.
  2. BERAGADT JEGYZÉS (csak gyertya-szinten, ha van spread): > 2% eltérés
     ÉS legfeljebb 2 tick ÉS a spread a környező medián 10%-a alatt. A valódi
     kiugrások spreadje a szokásos vagy nagyobb (mérve: GerMid50 2025-04-07
     16:20 190 vs 93; UsaInd 2020-03-18 14:30 9,9 vs 10,2) — azok maradnak.

A referencia mindkét szinten a környező percek mediánja (perc-mediánok 31 perces,
középre igazított mediánja) — robusztus akkor is, ha egy percen belül a tickek
többsége törött (GOLD 13:00: 16-ból több).
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from core import epoch

log = logging.getLogger(__name__)

BROKEN_DEV = 0.50          # 1. szabály: ennyinél nagyobb relatív eltérés = lehetetlen ár
STALE_DEV = 0.02           # 2. szabály: eltérés ...
STALE_MAX_VOL = 2          #   ... legfeljebb ennyi tick ...
STALE_SPREAD_RATIO = 0.10  #   ... és a spread a környező medián ennyiszerese alatt
WINDOW = 31                # környező gyertyák / percek (középre igazítva)
_MIN_PERIODS = 5


def _ref(values: pd.Series) -> pd.Series:
    return values.rolling(WINDOW, center=True, min_periods=1).median()


def tick_masks(times, bid, ask=None):
    """Tick-szintű szűrő. `times`: datetime-szerű (vagy ms epoch int), `bid`/`ask`:
    ár VAGY pont (arányt nézünk, a skála mindegy; ask ≤ 0 = már érvénytelen).

    Visszaad: (keep, ask_ok) bool tömbök — `keep`: a tick a gyertyába kerülhet,
    `ask_ok`: a tick spreadje használható."""
    bid = np.asarray(bid, dtype=np.float64)
    n = len(bid)
    keep = np.ones(n, bool)
    ask_ok = np.ones(n, bool)
    if n == 0:
        return keep, ask_ok
    tarr = np.asarray(times)
    if np.issubdtype(tarr.dtype, np.integer):          # ms epoch (a tick-tár alakja)
        minute = tarr.astype(np.int64) // 60_000
    else:
        minute = epoch.ns(pd.to_datetime(times)) // 60_000_000_000   # felbontás-független
    pos = bid > 0
    per_min = pd.Series(np.where(pos, bid, np.nan)).groupby(minute, sort=True).median()
    ref_min = _ref(per_min)
    ref = ref_min.to_numpy()[np.searchsorted(ref_min.index.to_numpy(), minute)]
    ok_ref = np.isfinite(ref) & (ref > 0)
    keep = pos & ~(ok_ref & (np.abs(bid / np.where(ok_ref, ref, 1.0) - 1.0) > BROKEN_DEV))
    if ask is not None:
        a = np.asarray(ask, dtype=np.float64)
        ask_ok = (a > 0) & (a >= bid) & ~(ok_ref & (np.abs(a / np.where(ok_ref, ref, 1.0) - 1.0) > BROKEN_DEV))
    return keep, ask_ok


def broken_bar_mask(df: pd.DataFrame) -> pd.Series:
    """Gyertya-szintű szűrő (1. + 2. szabály). True = törött gyertya."""
    if df.empty:
        return pd.Series(False, index=df.index)
    med = df["close"].where(df["close"] > 0).rolling(WINDOW, center=True,
                                                      min_periods=_MIN_PERIODS).median()
    cols = [c for c in ("open", "high", "low", "close") if c in df.columns]
    dev = pd.concat([(df[c] / med - 1.0).abs() for c in cols], axis=1).max(axis=1)
    nonpos = (df[cols] <= 0).any(axis=1)
    bad = nonpos | (dev > BROKEN_DEV)
    vol_col = "volume" if "volume" in df.columns else ("tick_volume" if "tick_volume" in df.columns else None)
    if vol_col is not None and "avg_spread" in df.columns:
        sp = df["avg_spread"]
        sp_med = sp.rolling(WINDOW, center=True, min_periods=_MIN_PERIODS).median()
        stale = (dev > STALE_DEV) & (df[vol_col] <= STALE_MAX_VOL) & \
                (sp < STALE_SPREAD_RATIO * sp_med)
        bad |= stale.fillna(False)
    return bad.fillna(False)


def clean_bars(df: pd.DataFrame, symbol: str = "", tf: str = "",
               tail: int | None = None) -> pd.DataFrame:
    """A törött gyertyák nélküli DataFrame. `tail`: csak az utolsó `tail` sort
    vizsgálja (+ környezet) — a gap-fill ne számolja újra a több milliós fájlt."""
    if df is None or df.empty:
        return df
    if tail is not None and tail < len(df):
        lo = max(0, len(df) - tail - WINDOW)
        m = broken_bar_mask(df.iloc[lo:])
        m = m[m.index >= df.index[len(df) - tail]]
        drop = m[m].index
    else:
        m = broken_bar_mask(df)
        drop = m[m].index
    if len(drop):
        log.warning("%s %s — %d törött gyertya kiszűrve (%s%s)", symbol, tf, len(drop),
                    ", ".join(str(t)[:16] for t in drop[:5]), " …" if len(drop) > 5 else "")
        return df.drop(index=drop)
    return df

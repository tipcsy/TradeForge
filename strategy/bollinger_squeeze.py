# strategy/bollinger_squeeze.py
"""
Bollinger Squeeze & Breakout stratégia (TradeForge)

A SKILL.md alapelvei [1]:
  - CSAK belépési jelet + előszűrőt ad vissza.
  - NEM nyúl: lot-méretezéshez, trailinghez, kilépéshez, végrehajtási
    kapukhoz (spread, TF-együttállás). Ezek a core/ modulok dolga.
  - Visszaadja az SL/TP távot (sl_tp_points / EntryPlan), hogy a
    kockázatkezelő abból dolgozzon.
  - A bt_entry() és a compute() ugyanazt a logikát futtatja → paritás.

Logika (4 lépés):
  1) SQUEEZE ON  : BW az alsó percentilisben ÉS BB a KC-n belül
  2) SQUEEZE OFF : a fenti feltétel megszűnik → volatilitás éled
  3) IRÁNY       : EMA-trend + %B momentum szűrő
  4) BELÉPÉS     : záróár a sávon kívül, SL/TP ATR-alapon
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List, Dict, Any

import numpy as np
import pandas as pd

from strategy.base import Strategy, EntryPlan, MarketData


# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
@dataclass
class BollingerSqueezeConfig:
    # --- Bollinger sávok ---
    bb_period: int = 20
    bb_std: float = 2.0

    # --- Squeeze szűrő (BandWidth percentilis) ---
    bw_lookback: int = 120
    bw_percentile: float = 20.0      # alsó X% → "összeszűkült"

    # --- Keltner csatorna (BB↔KC összehasonlításhoz) ---
    kc_ema_period: int = 20
    kc_atr_period: int = 10
    kc_atr_mult: float = 1.5

    # --- Trend szűrő ---
    ema_fast: int = 50
    ema_slow: int = 200
    require_trend_alignment: bool = True

    # --- %B momentum küszöb (breakout megerősítés) ---
    pb_long_threshold: float = 1.0
    pb_short_threshold: float = 0.0

    # --- SL / TP (ATR-alapú; CSAK a távot adjuk vissza, a lotot NEM) ---
    atr_period: int = 14
    sl_atr_mult: float = 1.0
    tp_rr: float = 2.0

    # --- Időzítési védőkorlátok ---
    min_bars_since_squeeze: int = 1
    max_bars_after_squeeze: int = 5


# ---------------------------------------------------------------------------
# INDIKÁTOR SZÁMÍTÁSOK
# ---------------------------------------------------------------------------
def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _atr(df: pd.DataFrame, n: int) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(),
         (high - prev_close).abs(),
         (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(span=n, adjust=False).mean()


def _bollinger(close: pd.Series, period: int, k: float):
    mb = _ema(close, period)
    sd = close.rolling(period).std(ddof=0)
    ub = mb + k * sd
    lb = mb - k * sd
    bw = (ub - lb) / mb * 100.0     # BandWidth %-ban
    pb = (close - lb) / (ub - lb)   # %B
    return mb, ub, lb, bw, pb


def _keltner(df: pd.DataFrame, ema_n: int, atr_n: int, atr_mult: float):
    mid = _ema(df["close"], ema_n)
    a = _atr(df, atr_n)
    return mid, mid + atr_mult * a, mid - atr_mult * a


# ---------------------------------------------------------------------------
# STRATÉGIA
# ---------------------------------------------------------------------------
class BollingerSqueezeStrategy(Strategy):
    """Belépési jel + előszűrő. Nem nyúl a pozíciómérethez, a stop
    mozgatáshoz vagy a kilépéshez [1]."""

    name = "bollinger_squeeze_breakout"

    def __init__(self, cfg: Optional[BollingerSqueezeConfig] = None):
        self.cfg = cfg or BollingerSqueezeConfig()

    # ------------------------------------------------------------------ #
    # Előszámítás (egyszer fut, nem bar-onként)                          #
    # ------------------------------------------------------------------ #
    def _prep(self, df: pd.DataFrame) -> pd.DataFrame:
        cfg = self.cfg
        out = df.copy()

        mb, ub, lb, bw, pb = _bollinger(df["close"], cfg.bb_period, cfg.bb_std)
        out["bb_mb"], out["bb_ub"], out["bb_lb"] = mb, ub, lb
        out["bb_bw"], out["bb_pb"] = bw, pb

        kc_mid, kc_ub, kc_lb = _keltner(
            df, cfg.kc_ema_period, cfg.kc_atr_period, cfg.kc_atr_mult
        )
        out["kc_mid"], out["kc_ub"], out["kc_lb"] = kc_mid, kc_ub, kc_lb

        out["atr"]       = _atr(df, cfg.atr_period)
        out["ema_fast"]  = _ema(df["close"], cfg.ema_fast)
        out["ema_slow"]  = _ema(df["close"], cfg.ema_slow)

        # TTM-szerű squeeze: BB a KC-n belül + BW az alsó percentilisben
        out["squeeze_kc"] = (out["bb_ub"] < out["kc_ub"]) & (out["bb_lb"] > out["kc_lb"])
        bw_pct = (out["bb_bw"]
                  .rolling(cfg.bw_lookback, min_periods=cfg.bw_lookback // 2)
                  .quantile(cfg.bw_percentile / 100.0))
        out["bw_threshold"] = bw_pct
        out["squeeze"] = out["squeeze_kc"] & (out["bb_bw"] <= out["bw_threshold"])
        out["squeeze_off"] = (out["squeeze"].shift(1).fillna(False)) & (~out["squeeze"])

        # Squeeze hossz-számláló (extra meta)
        out["squeeze_bars"] = (out["squeeze"]
                               .groupby((~out["squeeze"]).cumsum())
                               .cumsum().astype(int))
        return out

    # ------------------------------------------------------------------ #
    # Trend irány                                                        #
    # ------------------------------------------------------------------ #
    def _trend_dir(self, row: pd.Series) -> int:
        if not self.cfg.require_trend_alignment:
            return 0
        if row["ema_fast"] > row["ema_slow"] and row["close"] > row["ema_fast"]:
            return 1
        if row["ema_fast"] < row["ema_slow"] and row["close"] < row["ema_fast"]:
            return -1
        return 0

    # ------------------------------------------------------------------ #
    # Belépési terv (SL/TP táv, NEM lot)                                #
    # ------------------------------------------------------------------ #
    def _make_plan(self, i: int, df: pd.DataFrame, direction: int) -> Optional[EntryPlan]:
        cfg = self.cfg
        row = df.iloc[i]
        atr = float(row["atr"])
        if not np.isfinite(atr) or atr <= 0:
            return None

        sl_points = cfg.sl_atr_mult * atr
        entry = float(row["close"])
        if direction == 1:
            sl, tp = entry - sl_points, entry + cfg.tp_rr * sl_points
        else:
            sl, tp = entry + sl_points, entry - cfg.tp_rr * sl_points

        return EntryPlan(
            direction=direction,        # +1 long, -1 short
            entry_price=entry,
            sl_price=sl,
            tp_price=tp,
            sl_tp_points=sl_points,      # kockázatkezelő ebből dolgozik [1]
            meta={
                "strategy": self.name,
                "atr": atr,
                "bb_bw": float(row["bb_bw"]),
                "bb_pb": float(row["bb_pb"]),
                "squeeze_bars": int(row.get("squeeze_bars", 0)),
            },
        )

    # ------------------------------------------------------------------ #
    # Belső mag — backtest ÉS live ezt hívja (paritás [1])               #
    # ------------------------------------------------------------------ #
    def _signal_at(self, i: int, df: pd.DataFrame) -> Optional[EntryPlan]:
        cfg = self.cfg
        row = df.iloc[i]
        if not bool(row["squeeze_off"]):
            return None

        # itt egyszerűsítve: azonnal reagálunk, ha a feltétel teljesül;
        # a max_bars_after_squeeze szűrést a hívó (compute/bt_entry)
        # végzi, mert az "aktuális bar"-hoz képest relatív
        trend = self._trend_dir(row)
        pb = float(row["bb_pb"])

        long_ok  = (row["close"] > row["bb_ub"]) and (pb >= cfg.pb_long_threshold)
        short_ok = (row["close"] < row["bb_lb"]) and (pb <= cfg.pb_short_threshold)

        if cfg.require_trend_alignment:
            long_ok  = long_ok  and (trend == 1)
            short_ok = short_ok and (trend == -1)

        if long_ok:
            return self._make_plan(i, df, +1)
        if short_ok:
            return self._make_plan(i, df, -1)
        return None

    # ------------------------------------------------------------------ #
    # compute() — élő / dashboard oldal: a legutolsó bar állapota         #
    # ------------------------------------------------------------------ #
    def compute(self, md: MarketData) -> List[EntryPlan]:
        cfg = self.cfg
        df = md.bars
        min_len = max(cfg.bb_period, cfg.bw_lookback, cfg.ema_slow) + 5
        if len(df) < min_len:
            return []

        df = self._prep(df)

        # Utolsó bar-hoz közeli squeeze_off keresése
        squeeze_off_idxs = np.where(df["squeeze_off"].values)[0]
        if len(squeeze_off_idxs) == 0:
            return []

        last_off = int(squeeze_off_idxs[-1])
        last_idx = len(df) - 1
        bars_since = last_idx - last_off
        if not (cfg.min_bars_since_squeeze <= bars_since <= cfg.max_bars_after_squeeze):
            return []

        plan = self._signal_at(last_idx, df)
        return [plan] if plan else []

    # ------------------------------------------------------------------ #
    # bt_entry() — backtest oldali belépés [2]                            #
    # ------------------------------------------------------------------ #
    def bt_entry(self, md: MarketData, i: int, params: dict) -> Optional[EntryPlan]:
        """A base.py konvenciója: bar-onként hívódik backtestben [2]."""
        df = md.bars
        if i < 1 or i >= len(df):
            return None
        # Az előkészítést (rolling) itt újra kell számolni, mert
        # egyes bar-okra nézve nincs érvényes indikátor.
        df_prep = self._prep(df.iloc[: i + 1])
        return self._signal_at(i, df_prep)

    # ------------------------------------------------------------------ #
    # MT5 chart-vizualizáció [2]                                         #
    # ------------------------------------------------------------------ #
    def visual_lookback_bars(self, params: dict, timeframe_label: str) -> int:
        """Mekkora ablak kell a rajzoláshoz [2]."""
        return max(self.cfg.bb_period, self.cfg.bw_lookback,
                   self.cfg.ema_slow) + 20

    def visual_objects(self, md: MarketData) -> list:
        """BB + KC + squeeze-sáv kirajzolása a chartra [2]."""
        df = self._prep(md.bars)
        objs: List[Dict[str, Any]] = []
        # BB sávok
        objs += [
            {"kind": "line", "col": "bb_ub", "color": "blue",   "width": 1},
            {"kind": "line", "col": "bb_mb", "color": "gray",   "width": 1},
            {"kind": "line", "col": "bb_lb", "color": "blue",   "width": 1},
            # KC sávok
            {"kind": "line", "col": "kc_ub", "color": "orange", "width": 1, "style": "dash"},
            {"kind": "line", "col": "kc_lb", "color": "orange", "width": 1, "style": "dash"},
            # Squeeze-sáv (a chart alján)
            {"kind": "hist", "col": "squeeze", "color_on": "lime", "color_off": "red"},
        ]
        return objs

    # ------------------------------------------------------------------ #
    # Dashboard / élő megjelenítés                                       #
    # ------------------------------------------------------------------ #
    def signal_state(self, md: MarketData) -> Dict[str, Any]:
        df = self._prep(md.bars)
        last = df.iloc[-1]
        return {
            "squeeze":     bool(last["squeeze"]),
            "squeeze_off": bool(last["squeeze_off"]),
            "bb_bw":       float(last["bb_bw"]),
            "bb_pb":       float(last["bb_pb"]),
            "trend":       self._trend_dir(last),
        }
"""TREND-VISSZAHÚZÓDÁS — a holdout-kereséssel talált belépőjel.

Származása (2026-08-29): a `tools/research/` keresőrendszer találta, 231 000
jelöltből, 2017–2022-es keresési szakaszon, majd ÉRINTETLEN 2023–2026-os
holdouton igazolva a VALÓDI motoron (`run_pair`, slot + kapuk):
R +0,1225 / kötés, t = +2,94, 4/4 pozitív év.

A minta:

    M5:  stoch(14) %K keresztezi LEFELÉ a %D-t     ← a visszahúzódás
    M30: ATR(14) > az ATR 200-as átlaga            ← él a piac
    M60: ár > Keltner(14, 2,0) FELSŐ sávja         ← erős emelkedő trend

Magyarul: **erős trendben, élénk piacon, egy rövid visszaesésre vásárolunk.**
A három feltétel három KÜLÖNBÖZŐ időkeretről jön — ez a lényege: a nagyobb
keret adja a kontextust, a kicsi az időzítést.

⚠ CSAK LONG. A short irányt a kutatás külön mérte, és NEM működött (a keresés
mind a hat short jelöltje veszített a motoron). Ne "szimmetrizáld".

⚠ CSAK UsaTec-en igazolt. 16 instrumentumon mérve egyedül ott ment át; a
bruttó (spread nélküli) él a többi US indexen is pozitív, de a költség
megeszi. Más páron csak saját méréssel élesítsd.

MI NEM EZÉ A MODULÉ (lásd `strategy/base.py`): a breakeven, a trailing és a
cost-cut a KOCKÁZATCSÖKKENTÉSÉ (`core/risk_reduction.py`). A méréskor talált
legjobb kilépés — BE a TP 50%-ánál, 3× spread pufferrel, trailing ki,
cost_cut 24 M15 gyertyánál — a PÁR rr-beállítása, nem a stratégiáé.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategy.base import (Cell, Column, MarkerColumn, MarketData, Strategy,
                           Timeframe)

MAGIC_OFFSET = 3          # 0=wpr_sma, 1=ml_ai, 2=bollinger, 30=candle_level_break

_CIRCLE = "●"
_STAGES = (("trend", "H1 trend"), ("vol", "M30 volatilitás"),
           ("belep", "M5 beszállás"))
_MARKS_EMPTY = {k: Cell(_CIRCLE, "muted") for k, _ in _STAGES}

# A három feltétel időkerete. NEM paraméter: a keresés ezeken találta, és a
# kombináció együtt érvényes — külön hangolva elveszne a jelentése.
TF_BELEP, TF_VOL, TF_TREND = 5, 30, 60


# ---------------------------------------------------------------------------
# indikátorok
# ---------------------------------------------------------------------------

def _resample(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    o = df.resample(f"{minutes}min", label="left", closed="left").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"))
    return o.dropna(subset=["close"])


def _atr(h, l, c, n):
    """ATR — a true range EGYSZERŰ mozgóátlaga.

    ⚠ SZÁNDÉKOSAN nem Wilder-simítás (`ewm`), pedig az a szabványosabb. A
    stratégiát a kutatásban az egyszerű átlaggal MÉRTÜK ÉS VALIDÁLTUK
    (`tools/research/lab.atr`); a definíció cseréje egy MÁSIK, nem tesztelt
    stratégiát adna. Mérve: a két változat a jelek 0,3%-án tér el.
    Ha valaha Wilderre váltunk, azt ÚJRA kell validálni."""
    pc = np.concatenate([[np.nan], c[:-1]])
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    return pd.Series(tr).rolling(n).mean().to_numpy()


def _ema(a, n):
    return pd.Series(a).ewm(span=n, adjust=False).mean().to_numpy()


def _stoch(h, l, c, n, d):
    s = pd.Series(h).rolling(n, min_periods=n)
    hh = s.max().to_numpy()
    ll = pd.Series(l).rolling(n, min_periods=n).min().to_numpy()
    rng = hh - ll
    k = 100.0 * (c - ll) / np.where(rng > 0, rng, np.nan)
    dd = pd.Series(k).rolling(d, min_periods=d).mean().to_numpy()
    return k, dd


def _map_to(index: pd.DatetimeIndex, src: pd.DatetimeIndex, tf_min: int,
            values: np.ndarray) -> np.ndarray:
    """A magasabb keret jelét az M1 sorokra vetíti — LOOK-AHEAD NÉLKÜL.

    Egy TF-gyertya a NYITÓ idejével van címkézve, de csak `tf_min` perccel
    később ZÁR. Ezért a jelet a ZÁRÁS utáni első M1 bartól tekintjük
    érvényesnek (`searchsorted` a zárási időkre). Enélkül a jövőt használnánk.
    """
    zaras = src + pd.Timedelta(minutes=tf_min)
    j = np.searchsorted(zaras, index, side="right") - 1
    ok = j >= 0
    out = np.zeros(len(index), dtype=bool)
    jj = np.where(ok, j, 0)
    v = np.asarray(values)
    out[ok] = np.where(np.isfinite(v[jj[ok]].astype(float)), v[jj[ok]], False)
    return out


def signal_column(df_m1: pd.DataFrame, params: dict) -> np.ndarray:
    """A hármas együttállás boolean oszlopa az M1 sorokra."""
    p_st = int(params.get("stoch_period", 14) or 14)
    p_sd = int(params.get("stoch_d", 3) or 3)
    p_atr = int(params.get("atr_ref_period", 200) or 200)
    p_kel = int(params.get("keltner_period", 14) or 14)
    k_mul = float(params.get("keltner_mult", 2.0) or 2.0)

    # ── M5: a stoch %K LEFELÉ keresztezi a %D-t (visszahúzódás) ────────────
    d5 = _resample(df_m1, TF_BELEP)
    k, dd = _stoch(d5["high"].to_numpy(float), d5["low"].to_numpy(float),
                   d5["close"].to_numpy(float), p_st, p_sd)
    pk = np.concatenate([[np.nan], k[:-1]])
    pd_ = np.concatenate([[np.nan], dd[:-1]])
    kereszt_le = (pk >= pd_) & (k < dd)
    belep = _map_to(df_m1.index, d5.index, TF_BELEP, kereszt_le)

    # ── M30: ATR a saját hosszú átlaga FÖLÖTT (él a piac) ──────────────────
    d30 = _resample(df_m1, TF_VOL)
    a30 = _atr(d30["high"].to_numpy(float), d30["low"].to_numpy(float),
               d30["close"].to_numpy(float), 14)
    ref = pd.Series(a30).rolling(p_atr, min_periods=p_atr).mean().to_numpy()
    vol = _map_to(df_m1.index, d30.index, TF_VOL, a30 > ref)

    # ── H1: ár a Keltner FELSŐ sávja fölött (erős emelkedő trend) ──────────
    d60 = _resample(df_m1, TF_TREND)
    c60 = d60["close"].to_numpy(float)
    a60 = _atr(d60["high"].to_numpy(float), d60["low"].to_numpy(float),
               c60, p_kel)
    felso = _ema(c60, p_kel) + k_mul * a60
    trend = _map_to(df_m1.index, d60.index, TF_TREND, c60 > felso)

    return belep & vol & trend


def _stage_masks(df_m1: pd.DataFrame, params: dict) -> dict:
    """A HÁROM feltétel külön — a kijelzéshez (melyik stádium ég)."""
    p_st = int(params.get("stoch_period", 14) or 14)
    p_sd = int(params.get("stoch_d", 3) or 3)
    p_atr = int(params.get("atr_ref_period", 200) or 200)
    p_kel = int(params.get("keltner_period", 14) or 14)
    k_mul = float(params.get("keltner_mult", 2.0) or 2.0)

    d5 = _resample(df_m1, TF_BELEP)
    k, dd = _stoch(d5["high"].to_numpy(float), d5["low"].to_numpy(float),
                   d5["close"].to_numpy(float), p_st, p_sd)
    pk = np.concatenate([[np.nan], k[:-1]])
    pd_ = np.concatenate([[np.nan], dd[:-1]])
    belep = _map_to(df_m1.index, d5.index, TF_BELEP, (pk >= pd_) & (k < dd))

    d30 = _resample(df_m1, TF_VOL)
    a30 = _atr(d30["high"].to_numpy(float), d30["low"].to_numpy(float),
               d30["close"].to_numpy(float), 14)
    ref = pd.Series(a30).rolling(p_atr, min_periods=p_atr).mean().to_numpy()
    vol = _map_to(df_m1.index, d30.index, TF_VOL, a30 > ref)

    d60 = _resample(df_m1, TF_TREND)
    c60 = d60["close"].to_numpy(float)
    a60 = _atr(d60["high"].to_numpy(float), d60["low"].to_numpy(float), c60, p_kel)
    trend = _map_to(df_m1.index, d60.index, TF_TREND,
                    c60 > _ema(c60, p_kel) + k_mul * a60)
    return {"trend": trend, "vol": vol, "belep": belep}


class _State:
    """A felfutó él figyeléséhez: igaz volt-e az előző zárt gyertyán."""
    __slots__ = ("symbol", "elozo")

    def __init__(self, symbol: str = ""):
        self.symbol = symbol
        self.elozo = False


class TrendPullbackStrategy(Strategy):
    name = "trend_pullback"
    short = "TrPull"
    default_sl_method = "atr"

    # --- Megjelenítés -----------------------------------------------------

    def timeframes(self) -> list[Timeframe]:
        # A VÁZ M15+M1 keretet ad (run_pair aláírása). A minta belső keretei
        # (M5/M30/H1) az M1-ből képződnek — lásd `signal_column`.
        return [Timeframe("M15", 15), Timeframe("M1", 1)]

    def columns(self) -> list[Column]:
        return [MarkerColumn("marks", self.name, stages=_STAGES)]

    def warmup_bars(self, params: dict, timeframe_label: str) -> int:
        if timeframe_label == "M15":
            return int(params.get("atr_period", 14) or 14) + 5
        return self._m1_warmup(params)

    def signal_warmup_bars(self, params: dict, timeframe_label: str) -> int:
        # A jel a legmélyebb feltételtől függ (M30 ATR-átlag 200 gyertyán),
        # ezért a sekély warmup ELTÉRŐ jelet adna a dashboardon és élesben.
        return self.warmup_bars(params, timeframe_label)

    def _m1_warmup(self, params: dict) -> int:
        """A legmélyebb feltétel M1-gyertyában: M30 × atr_ref_period."""
        p_atr = int(params.get("atr_ref_period", 200) or 200)
        return TF_VOL * (p_atr + 20) + 200

    def compute_display(self, md: MarketData) -> dict[str, Cell]:
        # ⚠ A CELLÁK kulcsa a STÁDIUM (nem az oszlopé) — lásd a skill figyelmeztetését.
        empty = dict(_MARKS_EMPTY)
        df1 = md.bars.get("M1")
        if df1 is None or len(df1) < TF_VOL * 30:
            return empty
        try:
            m = _stage_masks(df1, md.params or {})
        except Exception:
            return empty
        out = {}
        for kulcs, _ in _STAGES:
            ell = bool(m[kulcs][-1]) if len(m[kulcs]) else False
            out[kulcs] = Cell(_CIRCLE, "green" if ell else "muted")
        return out

    # --- Élő jelzés -------------------------------------------------------

    def new_signal_state(self, symbol: str) -> _State:
        return _State(symbol)

    def on_bar_close(self, state: _State, md: MarketData) -> tuple[_State, str]:
        df1 = md.bars.get("M1")
        if df1 is None or len(df1) < TF_VOL * 30:
            return state, "NONE"
        try:
            sig = signal_column(df1, md.params or {})
        except Exception:
            return state, "NONE"
        most = bool(sig[-1]) if len(sig) else False
        # FELFUTÓ ÉL: csak az állapotVÁLTÁS a belépő. Állapoton belül minden
        # gyertyán jelezni piac-időzítés lenne, nem belépőjel (mérve: az élt
        # az időszak hordozza, a belépés pillanata nem).
        jel = "BUY" if (most and not state.elozo) else "NONE"
        state.elozo = most
        return state, jel

    # --- Optimalizálás ----------------------------------------------------

    def base_params(self, cfg: dict) -> dict:
        return {**cfg.get("indicators", {}), **cfg.get("sltp", {}),
                **cfg.get("position_mgmt", {})}

    def param_space(self, cfg: dict, base_params: dict, method: str,
                    max_trials: int) -> list[dict]:
        from ml.optimizer import generate_grid_params, generate_random_params
        opt_cfg = cfg["optimizer"]
        if method == "grid":
            return generate_grid_params(opt_cfg, base_params, self.constraints_ok)
        return generate_random_params(opt_cfg, base_params, max_trials,
                                      self.constraints_ok)

    def magic(self, cfg: dict) -> int:
        return int((cfg.get("broker") or {}).get("magic", 0) or 0) + MAGIC_OFFSET

    # --- Backtest-hookok --------------------------------------------------

    def bt_indicators(self, df_hi, df_lo, params):
        hi = df_hi.copy()
        hi["atr"] = _atr(hi["high"].to_numpy(float), hi["low"].to_numpy(float),
                         hi["close"].to_numpy(float),
                         int(params.get("atr_period", 14) or 14))
        lo = df_lo.copy()
        # A hármas együttállás EGY oszlopban: a bt_on_low_close egy SORT kap,
        # tehát ami több sort igényel (resample, rolling), annak itt kell
        # oszloppá válnia.
        lo["tp_sig"] = signal_column(df_lo, params)
        return hi, lo

    def bt_warmup(self, params: dict, timeframe_label: str) -> int:
        if timeframe_label == "M15":
            return int(params.get("atr_period", 14) or 14) + 5
        return self._m1_warmup(params)

    def bt_new_state(self, symbol: str) -> _State:
        return _State(symbol)

    def bt_on_high_close(self, state, hi_row, params):
        return state

    def bt_on_low_close(self, state, prev_lo_row, lo_row, params) -> str:
        try:
            most = bool(lo_row["tp_sig"])
            elozo = bool(prev_lo_row["tp_sig"]) if prev_lo_row is not None else False
        except (KeyError, TypeError, ValueError):
            return "NONE"
        return "BUY" if (most and not elozo) else "NONE"

    def sl_tp_points(self, hi_row, params, point_size):
        """SL/TP PONTBAN, az M15 ATR-ből. None → nincs érvényes ATR."""
        a = hi_row.get("atr", 0)
        if not a or pd.isna(a) or a <= 0 or point_size <= 0:
            return None
        sl = (float(params.get("sl_atr_mult", 1.5) or 1.5) * float(a)) / point_size
        return sl, sl * float(params.get("tp_rr_ratio", 2.0) or 2.0)

    def bt_entry(self, hi_row, params, point_size):
        return self.sl_tp_points(hi_row, params, point_size)

"""CSENDES SZERKEZETI ÁTTÖRÉS (long) — a HH/HL-kutatás első túlélő szűrője.

A szabály a `strategies/quiet_breakout_rules.py`-ban él (a kutató-labor is
onnan hívja — paritás: `tests/test_quiet_breakout_parity.py`). Röviden:

    M15:  visszahúzódás után a záró ár átlépi az utolsó igazolt M15-csúcsot
    stop: az utolsó igazolt M15-völgy (0,5–4 ATR)
    együttállás: az M1 / M5 / H1 / H4 szerkezetéből legalább 2 emelkedő (HH+HL)
    csendes piac: az M15 ATR ≤ 0,78 × az ugyanabban az órában szokásos

⚠ CSAK LONG. A short oldal a kutatásban minden szűrővel negatív volt.

⚠ MÉRVE, NEM BIZONYÍTVA (2026-10-02). A 2013–2022-es FÜGGETLEN próbán
+10,9 / kötés (100 kockázat), t = 1,65, 8/10 év, 4/5 instrumentum; 2023 óta
+4,3, és ott nem veri szignifikánsan a véletlen longot. Élesben előbb CSAK
JELZÉS módban (forward), kötés nélkül.

MI NEM EZÉ A MODULÉ (lásd `strategy/base.py`):
  * a napszak — a kutatásban 10:00–20:59 (magyar idő); a KERET óra-kapuja
    (`params_store.trade_hours`: 10–20) adja — a gyertya-index fal-óra, tehát
    ez közvetlenül magyar óra;
  * a kilépés — a kutatásban 21:45-kor / 8 óra után zártunk, célár nélkül. Ezt
    a kockázatcsökkentés IDŐ-KILÉPÉSE adja (`eod_close` 21:45, `max_hold_min`
    480 — per pár; `core.risk_reduction.time_exit_due`). Nélküle a motorban
    +1,5 / kötés, vele +6,6 (2023+). A `tp_rr_ratio` alapja 15 (≈ „nincs célár").
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.i18n import t as _t
from strategy import visual as viz
from strategy.base import (Cell, Column, MarkerColumn, MarketData, Strategy,
                           Timeframe)
from strategies import quiet_breakout_rules as rules

MAGIC_OFFSET = 6          # 0=wpr_sma, 1=ml_ai, 2=bollinger, 3=trend_pullback,
#                           4=straddle, 5=csilla, 30=candle_level_break

_CIRCLE = "●"
_STAGES = (("align", _t("stage.qb_align")), ("quiet", _t("stage.qb_quiet")),
           ("entry", _t("stage.qb_entry")))
_MARKS_EMPTY = {k: Cell(_CIRCLE, "muted") for k, _ in _STAGES}

# A legmélyebb feltétel: a H4 szerkezethez ~2 igazolt csúcs + völgy kell
# (néhány hét), a csendes-arányhoz 20 nap azonos órája. 30 nap M1-ben.
_M1_WARMUP = 30 * 1440
_VIZ_DAYS = 10


def _params(params: dict) -> dict:
    p = params or {}
    return {k: p.get(k, v) for k, v in rules.DEFAULTS.items()}


class _State:
    __slots__ = ("symbol",)

    def __init__(self, symbol: str = ""):
        self.symbol = symbol


class QuietBreakoutStrategy(Strategy):
    name = "quiet_breakout"
    short = "QuietBO"
    default_sl_method = "atr"

    # --- Megjelenítés -----------------------------------------------------

    def timeframes(self) -> list[Timeframe]:
        # A váz M15+M1 keretet ad; az M5/H1/H4 az M1-ből képződik.
        return [Timeframe("M15", 15), Timeframe("M1", 1)]

    def columns(self) -> list[Column]:
        return [MarkerColumn("marks", self.name, stages=_STAGES)]

    def warmup_bars(self, params: dict, timeframe_label: str) -> int:
        if timeframe_label == "M15":
            return 30 * 96
        return _M1_WARMUP

    def signal_warmup_bars(self, params: dict, timeframe_label: str) -> int:
        return self.warmup_bars(params, timeframe_label)

    def compute_display(self, md: MarketData) -> dict[str, Cell]:
        # ⚠ A CELLÁK kulcsa a STÁDIUM, nem az oszlop.
        empty = dict(_MARKS_EMPTY)
        df1 = (md.bars or {}).get("M1")
        if df1 is None or len(df1) < 5 * 1440:
            return empty
        try:
            tab = rules.entry_table(df1, _params(md.params))
        except Exception:
            return empty
        if len(tab) < 2:
            return empty
        last = tab.iloc[-2]                       # az utolsó LEZÁRT M15
        p = _params(md.params)
        return {
            "align": Cell(_CIRCLE, "green" if last["align"] >= int(p["min_align"]) else "muted"),
            "quiet": Cell(_CIRCLE, "green" if (last["vol"] == last["vol"]
                                               and last["vol"] <= float(p["vol_max"])) else "muted"),
            "entry": Cell(_CIRCLE, "green" if bool(last["sig"]) else "muted"),
        }

    # --- Élő jelzés -------------------------------------------------------

    def new_signal_state(self, symbol: str) -> _State:
        return _State(symbol)

    def on_bar_close(self, state: _State, md: MarketData) -> tuple[_State, str]:
        df1 = (md.bars or {}).get("M1")
        if df1 is None or len(df1) < 5 * 1440:
            return state, "NONE"
        try:
            sig = rules.m1_signal(df1, rules.entry_table(df1, _params(md.params)))
        except Exception:
            return state, "NONE"
        return state, ("BUY" if len(sig) and bool(sig[-1]) else "NONE")

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
        tab = rules.entry_table(df_lo, _params(params))
        lo = df_lo.copy()
        lo["qb_sig"] = rules.m1_signal(df_lo, tab)
        hi = df_hi.copy()
        # A stop-táv (ÁRBAN) a belépő M15-gyertya sorára — a motor a jelzés
        # M1-során pont ezt a (frissen lezárt) M15-sort adja a `bt_entry`-nek.
        idx = hi.index if hi.index.tz is not None else hi.index.tz_localize("UTC")
        hi["qb_sl_dist"] = tab["sl_dist"].reindex(idx).to_numpy()
        return hi, lo

    def bt_warmup(self, params: dict, timeframe_label: str) -> int:
        return self.warmup_bars(params, timeframe_label)

    def bt_new_state(self, symbol: str) -> _State:
        return _State(symbol)

    def bt_on_high_close(self, state, hi_row, params):
        return state

    def bt_on_low_close(self, state, prev_lo_row, lo_row, params) -> str:
        try:
            return "BUY" if bool(lo_row["qb_sig"]) else "NONE"
        except (KeyError, TypeError, ValueError):
            return "NONE"

    def sl_tp_points(self, hi_row, params, point_size):
        """SL PONTBAN a szerkezeti stopból (az utolsó igazolt M15-völgy).
        None → ezen a gyertyán nincs érvényes belépő-terv."""
        try:
            d = float(hi_row.get("qb_sl_dist", float("nan")))
        except (TypeError, ValueError):
            return None
        if not (d == d) or d <= 0 or point_size <= 0:
            return None
        sl = d / point_size
        return sl, sl * float(params.get("tp_rr_ratio", 15.0) or 15.0)

    # --- MT5 chart-vizualizáció ------------------------------------------

    def visual_lookback_bars(self, params: dict, timeframe_label: str) -> int:
        if timeframe_label == "M1":
            return _M1_WARMUP + _VIZ_DAYS * 1440
        return self.warmup_bars(params, timeframe_label) + _VIZ_DAYS * 96

    def visual_objects(self, md: MarketData) -> list:
        """Csak a belépő-jelölők (a közös `viz.entry_marks`) — a chart azt
        mutassa, amit a döntés használ, ne a teljes szerkezetet."""
        df1 = (md.bars or {}).get("M1")
        if df1 is None or len(df1) < 5 * 1440:
            return []
        p = md.params or {}
        try:
            tab = rules.entry_table(df1, _params(p))
        except Exception:
            return []
        pip = p.get("point_size", 0.0001)
        tp_rr = float(p.get("tp_rr_ratio", 15.0) or 15.0)
        kezd = df1.index[-1] - pd.Timedelta(days=_VIZ_DAYS)
        sel = tab[tab["sig"].to_numpy() & (tab.index >= kezd)]
        recs: list = []
        for t, r in sel.iterrows():
            ts = int((t + pd.Timedelta(minutes=15)).timestamp())
            e = float(r["close"])
            sl_p = float(r["sl_dist"]) / pip if pip else None
            lab = f"{self.short_name} BUY"
            if sl_p and callable(getattr(md, "lot_of", None)):
                _l = md.lot_of(sl_p)
                if _l and _l > 0:
                    lab += f" {_l:.2f} lot"
            recs.append({"t": ts, "d": "BUY", "e": e, "sl": e - float(r["sl_dist"]),
                         "tp": e + tp_rr * float(r["sl_dist"]), "lab": lab})
        viz.mark_blocked(recs, df1, self.name)
        objs: list = []
        sink = getattr(md, "on_entry_record", None)
        show = getattr(md, "show_signals", True)
        for rec in recs:
            if callable(sink):
                sink(rec)
            if show:
                objs += viz.entry_marks(rec)
        return objs

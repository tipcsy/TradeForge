"""CSILLA BESZÁLLÓJA — jelentős napi/heti szint törése, M1-zászló belépővel.

Származása: az Obsidian „Stratégiák/Csilla beszállója" jegyzet (Csilla
diszkrecionális módszere: szerkezet-törés két idősíkon), gépi olvasatban. A
mérés története a „Csilla beszállója — mérés" jegyzetben; röviden:

  * a nyers szabály (minden fraktál-szint, M1-stop) 14 éven −0,22 R/kötés;
  * a JELENTŐS (D1/W1) szintek + M15-stop változat −0,07 R (8 pár, 14 év);
  * a felhasználó ELŐRE megnevezett sávja — Ger40 8–11h, UsaTec és GOLD
    15–18h (szerver-idő) — fix 1,5 ATR15 stoppal, BE +0,67 R-nél, 2R
    csúszóval, célár nélkül: **+0,12 R/kötés, t = 1,5, 9/14 év**. Ez NEM
    bizonyíték (t < 2), ezért 2026-09-15-től FORWARD papírkereskedés.

⚠ A SZABÁLY NEM ITT VAN. A szint-/esemény-/belépő-logika a `strategies/csilla_rules`
modulban él, és a kutató-labor (`tools/research/csilla_levels.py`) UGYANAZT
hívja — a paritás szerkezeti, nem ígéret (`tests/test_csilla_parity.py`).
Ez a modul csak a keret hookjait adja: időkeretek, warmup, jelölő-oszlop,
élő jelzés, backtest-oszlopok, SL/TP, viz. A napszak-sáv (Ger40 8–11,
UsaTec/GOLD 15–18) a KERET stratégia-hatókörű kereskedési-óra kapuja
(`data/optimized_params/csilla/<PÁR>_hours.json`), nem a stratégiáé.

A KILÉPÉS NEM A STRATÉGIÁÉ (lásd `strategy/base.py`): a forward-teszt
kilépését — `breakeven_r = 0,67`, trailing 2 R (= 3,0 ATR15 aktiválás és
távolság), `off` preset — a PÁR kockázatcsökkentésében kell beállítani. A
célár itt szándékosan MESSZE van (`tp_rr_ratio`, alap 30): a mért változatban
nincs célár, a BE pedig R-alapú, tehát a távoli célár nem kapcsolja ki
(lásd `be-threshold-is-tp-relative`).

⚠ MÉLY M15-WARMUP: a W1-szintek 365 napig élnek, tehát a M15 keretnek ~1 évet
kell lefednie (~36 000 gyertya). A M15-kontextus (szintek, események) csak új
M15-gyertyánál változik, ezért páronként gyorsítótárazzuk — enélkül a
dashboard minden körben újraszámolna (lásd `display-path-deep-warmup-cost`).
"""
from __future__ import annotations

from core.i18n import t as _t
import numpy as np
import pandas as pd

from strategies import csilla_rules as sw
from strategy import visual as viz
from strategy.base import (Cell, Column, MarkerColumn, MarketData, Strategy,
                           Timeframe)

MAGIC_OFFSET = 5          # 0=wpr_sma, 1=ml_ai, 2=bollinger, 3=trend_pullback, 4=straddle

_CIRCLE = "●"
_STAGES = (("szint", _t("stage.cs_level")), ("tores", _t("stage.cs_break")),
           ("belep", _t("stage.cs_entry")))
_MARKS_EMPTY = {k: Cell(_CIRCLE, "muted") for k, _ in _STAGES}

HI_TF, LO_TF = 15, 1
_M15_PER_DAY = 96


def _P(params: dict) -> dict:
    """A core paraméterei a stratégia-configból (a hiányzókra a DEFAULTS)."""
    p = dict(sw.DEFAULTS)
    for k in ("k_hi", "k_lo", "k_d1", "k_w1", "ttl_d1", "ttl_w1", "max_wait",
              "buffer_atr", "min_sl_atr"):
        if params.get(k) is not None:
            p[k] = params[k]
    p["stop_atr"] = float(params.get("stop_atr", 1.5) or 1.5)
    return p


def _closed(df: pd.DataFrame | None) -> pd.DataFrame | None:
    """A FORMÁLÓDÓ (utolsó) gyertya nélkül — a jel csak zárt gyertyából számol."""
    if df is None or len(df) < 2:
        return None
    return df.iloc[:-1]


# ⚠ NAPSZAK-SÁV: NEM stratégia-paraméter. Az első változat saját `session_hours`
# paramétert vitt (a Csilla-sáv: Ger40 8–11, UsaTec/GOLD 15–18), ami a
# Paraméterek ablakban olvashatatlan tuple-ként jelent meg — miközben a keretnek
# VAN stratégia-hatókörű kereskedési-óra kapuja (`core.params_store.trade_hours`,
# `data/optimized_params/csilla/<PÁR>_hours.json`, a dashboardról állítható; a
# motor `allowed_hours`-a és a backtest ugyanazt használja). A sáv tehát ott él;
# a stratégia minden órában jelez, az óra-kapu dönt.


class _State:
    __slots__ = ("symbol", "last_fired")

    def __init__(self, symbol: str = ""):
        self.symbol = symbol
        self.last_fired = None          # az utolsó jelzett M1 gyertya ideje


class CsillaStrategy(Strategy):
    name = "csilla"
    short = "Csilla"
    default_sl_method = "atr"

    def __init__(self):
        super().__init__()
        # (symbol, utolsó zárt M15 idő, paraméter-ujjlenyomat) → hi_context
        self._ctx_cache: dict = {}

    # --- Megjelenítés -----------------------------------------------------

    def timeframes(self) -> list[Timeframe]:
        return [Timeframe("M15", HI_TF), Timeframe("M1", LO_TF)]

    def columns(self) -> list[Column]:
        return [MarkerColumn("marks", self.name, stages=_STAGES)]

    def warmup_bars(self, params: dict, timeframe_label: str) -> int:
        if timeframe_label == "M15":
            p = _P(params)
            # a W1-szint élettartama + a heti pivot igazolása + ATR.
            # ⚠ A warmup GYERTYÁBAN megy, a szintek élettartama NAPBAN: 96 M15 /
            # nap a 24 órás piacokra (FX, arany) pont 1 év; egy index-CFD-n
            # (~56 M15 / nap) ugyanez ~1,8 év — több, mint kell, de a motor a
            # warmupot a keret ELEJÉRŐL vágja, tehát a keretnek ENNÉL hosszabbnak
            # kell lennie, különben a szimuláció üres (0 kötés, némán).
            return int(_M15_PER_DAY * (p["ttl_w1"] + 7 * (p["k_w1"] + 1) + 3)) + 50
        p = _P(params)
        # M1: a törés utáni ablak + a pivot félablak + ATR(14)
        return int(p["max_wait"] * HI_TF + 2 * p["k_lo"] + 30)

    def signal_warmup_bars(self, params: dict, timeframe_label: str) -> int:
        return self.warmup_bars(params, timeframe_label)

    # --- a közös számítás ------------------------------------------------

    def _context(self, symbol: str, hi: pd.DataFrame, params: dict) -> dict:
        p = _P(params)
        # ⚠ A kulcsban a keret AZONOSSÁGA is benne van (első/utolsó idő + az
        # utolsó két zárás): két pár M15 gyertyája UGYANAKKOR zár, tehát a
        # szimbólum + idő önmagában ütközne (a portfólió-backtest egy példányon fut).
        key = (symbol, hi.index[0], hi.index[-1], float(hi["close"].iloc[-1]),
               float(hi["close"].iloc[-2]), tuple(sorted((k, p[k]) for k in p)))
        ctx = self._ctx_cache.get(key)
        if ctx is None:
            ctx = sw.hi_context(hi, p)
            # csak a legutóbbi kontextust tartjuk páronként
            self._ctx_cache = {k: v for k, v in self._ctx_cache.items() if k[0] != symbol}
            self._ctx_cache[key] = ctx
        return ctx

    def _signals(self, symbol: str, hi: pd.DataFrame, lo: pd.DataFrame, params: dict):
        """`(sig, sl_abs, atr15, ctx)` az M1 (lo) sorokra — ZÁRT keretekből."""
        ctx = self._context(symbol, hi, params)
        sig, sl, a15 = sw.signal_column(lo, ctx=ctx, stop_atr=_P(params)["stop_atr"])
        return sig, sl, a15, ctx

    def compute_display(self, md: MarketData) -> dict[str, Cell]:
        # ⚠ A CELLÁK kulcsa a STÁDIUM (nem az oszlopé).
        empty = dict(_MARKS_EMPTY)
        hi = _closed(md.bars.get("M15"))
        lo = _closed(md.bars.get("M1"))
        if hi is None or lo is None or len(hi) < 200:
            return empty
        try:
            sig, _sl, _a, ctx = self._signals(md.symbol, hi, lo, md.params or {})
        except Exception:
            return empty
        p = ctx["P"]
        out = dict(empty)
        # szint: van-e élő D1/W1 szint az ár 1 ATR15-ös környezetében
        lv = ctx["lv"]
        a15 = ctx["a15"][-1] if len(ctx["a15"]) else np.nan
        close = float(hi["close"].iloc[-1])
        t_now = hi.index[-1]
        if len(lv) and np.isfinite(a15):
            alive = lv[(lv.t_conf <= t_now) & (lv.t_exp > t_now)]
            if ((alive.price - close).abs() <= a15).any():
                out["szint"] = Cell(_CIRCLE, "yellow")
        # törés: volt-e esemény az utolsó max_wait M15 gyertyán belül
        evs = ctx["evs"]
        if evs and evs[-1]["i"] >= len(hi) - p["max_wait"]:
            out["tores"] = Cell(_CIRCLE, "green" if evs[-1]["dir"] > 0 else "red")
        # belépő: az utolsó ZÁRT M1 gyertya jelez-e (az óra-kapu a KERETÉ)
        if len(sig) and sig[-1] != 0:
            out["belep"] = Cell(_CIRCLE, "green" if sig[-1] > 0 else "red")
        return out

    # --- Élő jelzés -------------------------------------------------------

    def new_signal_state(self, symbol: str) -> _State:
        return _State(symbol)

    def on_bar_close(self, state: _State, md: MarketData) -> tuple[_State, str]:
        hi = _closed(md.bars.get("M15"))
        lo = _closed(md.bars.get("M1"))
        if hi is None or lo is None or len(hi) < 200:
            return state, "NONE"
        try:
            sig, _sl, _a, _ctx = self._signals(md.symbol, hi, lo, md.params or {})
        except Exception:
            return state, "NONE"
        t_last = lo.index[-1]
        if not len(sig) or sig[-1] == 0 or state.last_fired == t_last:
            return state, "NONE"
        state.last_fired = t_last
        return state, ("BUY" if sig[-1] > 0 else "SELL")

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
        """hi: `atr` + `cs_atr_ref` (a törés gyertyájának ATR-je, a törés utáni
        ablakra kitöltve — az SL ebből jön, mint a laborban); lo: `cs_sig`
        (+1/−1 a belépő baron), `cs_sl` (a stop ÁRBAN)."""
        hi = df_hi.copy()
        lo = df_lo.copy()
        p = _P(params)
        hi["atr"] = sw.atr(hi["high"].to_numpy(float), hi["low"].to_numpy(float),
                           hi["close"].to_numpy(float),
                           int(params.get("atr_period", 14) or 14))
        # ⚠ A szimbólum a paraméterekből (a motor adja `symbol`-ként), különben
        # a gyorsítótár kulcsa páronként ütközne.
        sym = str(params.get("symbol", "") or "")
        ctx = self._context(sym, hi, params)
        sig, sl, _a15 = sw.signal_column(lo, ctx=ctx, stop_atr=p["stop_atr"])
        lo["cs_sig"] = sig
        lo["cs_sl"] = sl
        ref = np.full(len(hi), np.nan)
        for e in ctx["evs"]:
            i0 = int(e["i"])
            ref[i0:min(len(hi), i0 + p["max_wait"] + 1)] = ctx["a15"][i0]
        hi["cs_atr_ref"] = ref
        return hi, lo

    def bt_warmup(self, params: dict, timeframe_label: str) -> int:
        return self.warmup_bars(params, timeframe_label)

    def bt_new_state(self, symbol: str) -> _State:
        return _State(symbol)

    def bt_on_high_close(self, state, hi_row, params):
        return state

    def bt_on_low_close(self, state, prev_lo_row, lo_row, params) -> str:
        try:
            s = int(lo_row["cs_sig"])
        except (KeyError, TypeError, ValueError):
            return "NONE"
        if s == 0:
            return "NONE"
        return "BUY" if s > 0 else "SELL"

    def sl_tp_points(self, hi_row, params, point_size):
        """SL = stop_atr × a TÖRÉS M15-gyertyájának ATR-je (a laborral azonos);
        ha nincs (ablakon kívül), az aktuális M15 ATR. TP = SL × tp_rr_ratio
        (alapból messze — a mért változatban nincs célár)."""
        a = hi_row.get("cs_atr_ref", np.nan)
        if a is None or pd.isna(a) or a <= 0:
            a = hi_row.get("atr", 0)
        if not a or pd.isna(a) or a <= 0 or point_size <= 0:
            return None
        sl = float(params.get("stop_atr", 1.5) or 1.5) * float(a) / point_size
        return sl, sl * float(params.get("tp_rr_ratio", 30.0) or 30.0)

    # --- MT5 chart-vizualizáció ------------------------------------------

    def visual_lookback_bars(self, params: dict, timeframe_label: str) -> int:
        if timeframe_label == "M1":
            return 3 * 1440                 # 3 nap belépő a charton
        return self.warmup_bars(params, "M15")

    def visual_objects(self, md: MarketData) -> list:
        """M15-törések (a tört szint rövid szakaszával) + belépők (a közös
        rajzolóval, ami a belépő-naplót is tölti). Élő szint-vonalak NINCSENEK."""
        hi = _closed((md.bars or {}).get("M15"))
        lo = _closed((md.bars or {}).get("M1"))
        if hi is None or lo is None or len(hi) < 200:
            return []
        p = md.params or {}
        try:
            sig, sl, a15, ctx = self._signals(md.symbol, hi, lo, p)
        except Exception:
            return []
        objs: list = []
        t0 = lo.index[0]
        # ⚠ NINCS vízszintes szint-vonal az élő charton. Az első változat a
        # labor-viz mintájára a teljes ablakon áthúzta az élő D1/W1 szinteket
        # (kék/lila) — a felhasználó jogosan „szemétnek" olvasta (2026-09-15).
        # A szint csak OTT érdekes, ahol törik: a törés függőlegese mellé egy
        # rövid (±8 M15) szakasz mutatja, MI tört.
        for e in ctx["evs"]:
            tb = hi.index[e["i"]]
            if tb < t0:
                continue
            tc = int((tb + pd.Timedelta(minutes=HI_TF)).timestamp())
            objs.append(viz.VLine(name=f"cs_brk_{tc}", t1=tc, color="darkgold", width=2))
            col = "blue" if e["kind"] == "D1" else "magenta"
            objs.append(viz.Trend(name=f"cs_lvl_{tc}", t1=tc - 8 * HI_TF * 60, p1=float(e["level"]),
                                  t2=tc + 8 * HI_TF * 60, p2=float(e["level"]),
                                  color=col, width=2))
        # belépők: a közös rekord → napló + rajz
        pip = float(p.get("point_size", 0.0001) or 0.0001)
        _recs = []
        for i in np.flatnonzero(sig != 0):
            ti = lo.index[int(i)]
            d = "BUY" if sig[i] > 0 else "SELL"
            entry = float(lo["close"].iloc[int(i)])
            _sl = entry - (1 if d == "BUY" else -1) * float(sl[i])
            _lab = f"{self.short_name} {d}"
            if callable(getattr(md, "lot_of", None)):
                _l = md.lot_of(float(sl[i]) / pip)
                if _l and _l > 0:
                    _lab += f" {_l:.2f} lot"
            _recs.append({"t": int(ti.timestamp()) + 60, "d": d, "e": entry,
                          "sl": _sl, "tp": None, "lab": _lab})
        viz.mark_blocked(_recs, lo, self.name)
        _sink = getattr(md, "on_entry_record", None)
        _rajzol = getattr(md, "show_signals", True)
        for rec in _recs:
            if callable(_sink):
                _sink(rec)
            if _rajzol:
                objs += viz.entry_marks(rec)
        return objs

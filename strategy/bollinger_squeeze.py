"""
Bollinger Squeeze & Breakout — belépési jelző.

A sávok összeszűkülését (squeeze) és az azt követő kitörést fogja meg:

  1. SQUEEZE     BB a Keltner-csatornán BELÜL  ÉS  a BandWidth az alsó
                 percentilisben (TTM-szerű kettős feltétel)
  2. FELOLDÁS    a squeeze megszűnik → a volatilitás éled
  3. IRÁNY       a MEGTÖRT SÁV adja (az EMA-trendszűrő csak opcionális vétó,
                 alapból KI — az irány-vétó a kapuké)
  4. KITÖRÉS     záróár a sávon kívül ÉS a %B megerősíti

A leírás: `strategy/docs/bollinger_squeeze_breakout.md`.

───────────────────────────────────────────────────────────────────────────
AMI NEM EZÉ A MODULÉ

A stratégia BELÉPÉSI JELZŐ (+ előszűrő). Az SL/TP **távot** adja pontban; a
lotot, a stop későbbi mozgatását (BE/trailing), a részleges zárást és a
végrehajtási kapukat (spread, TF-együttállás) a keretrendszer intézi. Ezért
nincs itt `breakeven_pct`, `trail_*`, `max_open_slots` — és az `atr_period` sem
a stratégiáé: az a közös `core/execution_params.py`-ban lakik, a `bt_indicators`
onnan kapja a `params`-ban.

⚠ A Keltner SAJÁT ATR-periódusa (`kc_atr_period`) VISZONT a stratégiáé: az a
csatorna alakját szabja meg, nem a végrehajtást. A kettő szándékosan külön.
───────────────────────────────────────────────────────────────────────────
JELZÉS-ARCHITEKTÚRA (miért két idősík)

A motor magasabb tf-en tartja az állapotot, alsó tf-en tüzel
(`bt_on_high_close` → `bt_on_low_close`). A döntés a JEL-IDŐSÍKÉ
(`signal_tf_min`, alapból H1 — lásd fentebb), az M1 pusztán kézbesíti: a jelzés
után az ELSŐ M1 gyertyán tüzel, EGYSZER.

Ez tudatosan konzervatív: nem találunk ki M1-es finomítást olyan stratégiához,
amit kitörésként fogalmaztak meg. (Egy későbbi, M1-en finomított belépő külön
mérendő — lásd a doksi „Továbbfejlesztés" pontját.)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

from strategy.base import (
    Strategy, Column, MarkerColumn, MarketData, Cell, Timeframe,
)
from strategy import visual as viz


# A stratégia MT5 magic-eltolása. MINDEN stratégia EGYEDI eltolást kap, hogy a
# nyitott pozíciók broker-szinten szétválaszthatók legyenek (wpr_sma: 0, ml_ai: 1).
MAGIC_OFFSET = 2

# ── A SQUEEZE IDŐSÍKJA ─────────────────────────────────────────────────────
# A tananyag (Obsidian: „Bollinger Squeeze & Breakout Stratégia") méri fel:
#
#     1–5 perc   ⭐      skalp, nagyon sok zaj
#     15 perc    ⭐⭐     „sok hamis jel"
#     1 óra      ⭐⭐⭐    „jó egyensúly"
#     4 óra      ⭐⭐⭐⭐   „sok tapasztalt trader ezt preferálja"
#     D1         ⭐⭐⭐⭐⭐  ritka, de a legerősebb
#
# Az ok szerkezeti: M15-ön a squeeze gyakran 1-2 gyertyáig tart, tehát „nincs
# ideje feltöltődni" — a kitörés utána nem hordoz energiát. Ezért a jel idősíkja
# PARAMÉTER, nem beégetett érték.
#
# ⚠ A LETÖLTÖTT adat marad M15 + M1 (`timeframes()`): a durvább gyertyát ebből
# mintázzuk át. Így nem kell új adatforrás, és a resample UGYANAZ a képlet, amit
# az `ml_ai` és a `core.tf_align` is használ (bal-zárt, bal-címkés — mint az MT5).
DEFAULT_TF_MIN = 60
ALLOWED_TF_MIN = (15, 30, 60, 120, 240)
_tf_cache: dict = {}


def signal_tf_min() -> int:
    """A squeeze idősíkja PERCBEN, a stratégia SAJÁT configjából.

    Közvetlenül a fájlból (nem a futásidejű cfg-ből): a `timeframes()` és a
    warmup hívóinak nincs cfg-jük. Az mtime-cache miatt ez körönként egy `stat()`.
    (Ugyanaz a minta, mint az `ml_ai.signal_tf_min`.)"""
    from strategy.settings import strategy_config_path
    p = strategy_config_path("bollinger_squeeze_breakout")
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return DEFAULT_TF_MIN
    if _tf_cache.get("mtime") == mtime:
        return _tf_cache["v"]
    val = DEFAULT_TF_MIN
    try:
        import json as _json
        with open(p, encoding="utf-8") as f:
            raw = (_json.load(f).get("indicators") or {}).get("signal_tf_min")
        if raw is not None:
            v = int(raw)
            if v in ALLOWED_TF_MIN:
                val = v
            else:
                log.warning("bollinger — signal_tf_min=%s nem megengedett (%s) "
                            "→ %d perc", raw, ALLOWED_TF_MIN, DEFAULT_TF_MIN)
    except Exception as ex:
        log.warning("bollinger — signal_tf_min olvasási hiba: %s", ex)
    _tf_cache.update({"mtime": mtime, "v": val})
    return val


def _to_signal_tf(df: pd.DataFrame, params: dict = None) -> pd.DataFrame:
    """Az M15 frame átmintázása a beállított jel-idősíkra (15 → változatlan)."""
    tf = int((params or {}).get("signal_tf_min") or signal_tf_min())
    if tf <= 15 or df is None or len(df) < 2:
        return df
    from strategy.ml_ai import resample_ohlc
    return resample_ohlc(df, tf)


_CIRCLE = "●"

# A körös jelölő stádiumai — a `columns()` és a cellák EZEKET használják.
_STAGES = (("squeeze", "Összeszűkülés"),
           ("release", "Feloldás + trend"),
           ("entry",   "Kitörés (belépő)"))


# ---------------------------------------------------------------------------
# Indikátorok — a `bt_indicators` OSZLOPPÁ teszi őket
# ---------------------------------------------------------------------------
# ⚠ Ami több sorból számol (rolling, percentilis), az CSAK itt születhet meg: a
# `bt_*` hookok egyetlen sort (pandas Series) kapnak, nem DataFrame-et.

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=int(n), adjust=False).mean()


def _atr(df: pd.DataFrame, n: int) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([(df["high"] - df["low"]).abs(),
                    (df["high"] - prev).abs(),
                    (df["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(span=int(n), adjust=False).mean()


def compute_indicators(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """A stratégia MINDEN oszlopa egy M15 frame-re. Tiszta függvény: a live, a
    backtest és a viz UGYANEZT hívja — így a három nem csúszhat szét."""
    p = params
    # ⚠ ELŐSZÖR az idősík: a squeeze a beállított (durvább) gyertyán él, nem az
    # M15-ön. A letöltött adat M15 marad — innen mintázunk fel.
    out = _to_signal_tf(df, p).copy()
    close = out["close"]

    # ── Bollinger ─────────────────────────────────────────────────────────
    per = int(p.get("bb_period", 20))
    k = float(p.get("bb_std", 2.0))
    mb = close.rolling(per).mean()
    sd = close.rolling(per).std(ddof=0)
    ub, lb = mb + k * sd, mb - k * sd
    out["bb_mb"], out["bb_ub"], out["bb_lb"] = mb, ub, lb
    # BandWidth %-ban; a %B a sávon belüli helyzet (1.0 = a felső sávon)
    span = (ub - lb)
    out["bb_bw"] = (span / mb.replace(0, np.nan)) * 100.0
    out["bb_pb"] = (close - lb) / span.replace(0, np.nan)

    # ── Keltner (a squeeze másik fele) ────────────────────────────────────
    kc_mid = _ema(close, p.get("kc_ema_period", 20))
    kc_a = _atr(out, p.get("kc_atr_period", 10))
    kc_m = float(p.get("kc_atr_mult", 1.5))
    out["kc_ub"], out["kc_lb"] = kc_mid + kc_m * kc_a, kc_mid - kc_m * kc_a

    # ── Trend ─────────────────────────────────────────────────────────────
    out["ema_fast"] = _ema(close, p.get("ema_fast", 50))
    out["ema_slow"] = _ema(close, p.get("ema_slow", 200))

    # ── Squeeze: BB a KC-n belül ÉS a BW az alsó percentilisben ───────────
    inside = (out["bb_ub"] < out["kc_ub"]) & (out["bb_lb"] > out["kc_lb"])
    look = int(p.get("bw_lookback", 120))
    pct = float(p.get("bw_percentile", 20.0)) / 100.0
    # ⚠ A percentilis a MÚLTBÓL: a `rolling` az i. sorig zár, tehát nincs
    # look-ahead. (Egy `expanding`/teljes-minta percentilis a jövőt is látná.)
    thr = out["bb_bw"].rolling(look, min_periods=max(20, look // 2)).quantile(pct)
    out["bw_threshold"] = thr
    out["squeeze"] = (inside & (out["bb_bw"] <= thr)).fillna(False)
    # Feloldás: az ELŐZŐ gyertyán még squeeze volt, ezen már nincs
    # ⚠ `shift(1, fill_value=False)` és NEM `shift(1).fillna(False)`: az utóbbi a
    # bool sorozatot az első sor NaN-ja miatt `object` dtype-ra váltja, majd a
    # `fillna` NÉMÁN visszaalakítja bool-lá — ezt a pandas elavulttá tette
    # (FutureWarning), és egy jövőbeli verzióban a dtype `object` MARADNA. Az
    # `&` operátor object dtype-on más eredményt adhat, tehát ez nem kozmetika.
    # A `fill_value` eleve nem enged NaN-t, így a dtype végig bool marad.
    out["squeeze_off"] = out["squeeze"].shift(1, fill_value=False) & (~out["squeeze"])
    # Hány gyertya óta tart a mostani squeeze (a kijelzéshez)
    out["squeeze_bars"] = (out["squeeze"]
                           .groupby((~out["squeeze"]).cumsum()).cumsum().astype(int))

    # ── A végrehajtás ATR-je (a SL/TP mérete) ─────────────────────────────
    # A periódus a KÖZÖS execution configból jön (nem stratégia-paraméter).
    out["atr"] = _atr(out, p.get("atr_period", 14))
    return out


def _trend_dir(row, params: dict) -> int:
    """+1 / −1 / 0 — a trend-szűrő iránya. Kikapcsolva mindig 0 (nem szűr)."""
    if not bool(params.get("require_trend_alignment", True)):
        return 0
    f, s, c = row.get("ema_fast"), row.get("ema_slow"), row.get("close")
    if any(v is None or (isinstance(v, float) and math.isnan(v)) for v in (f, s, c)):
        return 0
    if f > s and c > f:
        return 1
    if f < s and c < f:
        return -1
    return 0


def _breakout_signal(row, params: dict) -> str:
    """A KITÖRÉS-feltétel egyetlen ZÁRT M15 soron. `"BUY"|"SELL"|"NONE"`.

    A doksi szerint: záróár a sávon kívül ÉS a %B megerősíti; ha a trend-szűrő
    be van kapcsolva, az iránynak egyeznie kell."""
    pb = row.get("bb_pb")
    if pb is None or (isinstance(pb, float) and math.isnan(pb)):
        return "NONE"
    c, ub, lb = row.get("close"), row.get("bb_ub"), row.get("bb_lb")
    if any(v is None or (isinstance(v, float) and math.isnan(v)) for v in (c, ub, lb)):
        return "NONE"

    long_ok = (c > ub) and (pb >= float(params.get("pb_long_threshold", 1.0)))
    short_ok = (c < lb) and (pb <= float(params.get("pb_short_threshold", 0.0)))
    if bool(params.get("require_trend_alignment", True)):
        d = _trend_dir(row, params)
        long_ok, short_ok = long_ok and d == 1, short_ok and d == -1
    if long_ok:
        return "BUY"
    if short_ok:
        return "SELL"
    return "NONE"


# ---------------------------------------------------------------------------
# Jelzés-állapot (a motor tartja életben páronként)
# ---------------------------------------------------------------------------

@dataclass
class SqueezeState:
    """A squeeze feloldása óta eltelt M15 gyertyák + a kézbesítendő jel.

    ⚠ `bars_since_off = -1` → nem volt még feloldás. A `pending` az M15-ön
    születik, és az ELSŐ M1 gyertyán fogy el (`bt_on_low_close`) — így a jel
    pontosan egyszer megy ki, akkor sem duplázódik, ha több M1 gyertya fut le
    ugyanazon az M15-ön belül."""
    symbol: str
    bars_since_off: int = -1
    in_squeeze: bool = False
    squeeze_bars: int = 0
    pending: str = "NONE"
    last_signal: str = "NONE"


def _advance(state: SqueezeState, row, params: dict) -> SqueezeState:
    """Egy ZÁRT M15 gyertya feldolgozása. A live és a backtest is ezt hívja."""
    state.in_squeeze = bool(row.get("squeeze", False))
    state.squeeze_bars = int(row.get("squeeze_bars", 0) or 0)

    if bool(row.get("squeeze_off", False)):
        state.bars_since_off = 0
    elif state.bars_since_off >= 0:
        state.bars_since_off += 1

    lo = int(params.get("min_bars_since_squeeze", 0))
    hi = int(params.get("max_bars_after_squeeze", 5))
    in_window = state.bars_since_off >= 0 and lo <= state.bars_since_off <= hi
    sig = _breakout_signal(row, params) if in_window else "NONE"
    if sig != "NONE":
        state.pending = sig
        state.last_signal = sig
        # Egy ablakból EGY belépő: a jel után az ablak bezárul, különben a
        # kitörés minden további gyertyája újra tüzelne.
        state.bars_since_off = -1
    return state


# ---------------------------------------------------------------------------
# Stratégia
# ---------------------------------------------------------------------------

class BollingerSqueezeStrategy(Strategy):
    name = "bollinger_squeeze_breakout"
    default_sl_method = "atr"      # a méret ATR-ből jön (nem swing)

    # ── Megjelenítés ──────────────────────────────────────────────────────

    def timeframes(self) -> list[Timeframe]:
        return [Timeframe("M15", 15), Timeframe("M1", 1)]

    def columns(self) -> list[Column]:
        return [MarkerColumn("marks", self.name, stages=_STAGES)]

    def _signal_bars_needed(self, params: dict) -> int:
        """Hány JEL-IDŐSÍKÚ gyertya kell az indikátorokhoz."""
        return max(int(params.get("bb_period", 20)),
                   int(params.get("bw_lookback", 120)),
                   int(params.get("ema_slow", 200)),
                   int(params.get("kc_ema_period", 20)),
                   int(params.get("atr_period", 14))) + 20

    def _tf_ratio(self, params: dict) -> int:
        """Hány M15 gyertyából áll egy jel-idősíkú gyertya (H1 → 4)."""
        tf = int((params or {}).get("signal_tf_min") or signal_tf_min())
        return max(1, tf // 15)

    def warmup_bars(self, params: dict, timeframe_label: str) -> int:
        """⚠ A LETÖLTÖTT idősík M15, az indikátorok viszont a JEL-idősíkon
        élnek — a szükséges M15-gyertyaszámot tehát FEL KELL SZOROZNI. Enélkül
        H1-en négyszer kevesebb adat jutna az indikátoroknak, és a leghosszabb
        ablak (`ema_slow`, `bw_lookback`) végig NaN maradna: a stratégia némán
        egyetlen jelet sem adna."""
        if timeframe_label == "M15":
            return self._signal_bars_needed(params) * self._tf_ratio(params)
        return 5

    def signal_warmup_bars(self, params: dict, timeframe_label: str) -> int:
        """A squeeze-percentilis `bw_lookback` gyertyát néz VISSZA, és a
        feloldás-számláló is előzményfüggő — sekély ablakon a jel MÁS lenne,
        mint a vizben. (A `wpr_sma`-nál pont ez okozott kimaradó belépőket.)"""
        if timeframe_label == "M15":
            return (self.warmup_bars(params, "M15")
                    + int(params.get("bw_lookback", 120)) * self._tf_ratio(params))
        return 10

    def visual_lookback_bars(self, params: dict, timeframe_label: str) -> int:
        if timeframe_label == "M15":
            return max(2880, self.signal_warmup_bars(params, "M15"))
        return 4000

    # ── Élő jelzés ────────────────────────────────────────────────────────

    def new_signal_state(self, symbol: str) -> Any:
        return SqueezeState(symbol=symbol)

    def on_bar_close(self, state: Any, md: MarketData) -> tuple:
        """ZÁRT M15 gyertya → (state, jel). A motor hívja élesben."""
        df = (md.bars or {}).get("M15")
        if df is None or len(df) < 3:
            return state, "NONE"
        ind = compute_indicators(df, md.params)
        state = _advance(state, ind.iloc[-2], md.params)   # az UTOLSÓ ZÁRT sor
        sig, state.pending = state.pending, "NONE"
        return state, sig

    def _marks(self, state, row, params) -> dict:
        """A három stádium köre: összeszűkülés · feloldás+trend · kitörés."""
        def dot(on, color="green"):
            return Cell(_CIRCLE, color if on else "muted")

        in_sq = bool(row.get("squeeze", False)) if row is not None else False
        d = _trend_dir(row, params) if row is not None else 0
        armed = (getattr(state, "bars_since_off", -1) >= 0) and d != 0
        sig = getattr(state, "last_signal", "NONE")
        return {
            "squeeze": dot(in_sq, "yellow"),
            "release": dot(armed, "green" if d > 0 else "red" if d < 0 else "muted"),
            "entry":   dot(sig in ("BUY", "SELL"),
                           "green" if sig == "BUY" else "red"),
        }

    def compute_display(self, md: MarketData) -> dict:
        """A kijelzés a FORMÁLÓDÓ gyertyát is használhatja (nem döntés, csak nézet)."""
        df = (md.bars or {}).get("M15")
        empty = {k: Cell(_CIRCLE, "muted") for k, _ in _STAGES}
        if df is None or len(df) < 3:
            return {"marks": empty}
        try:
            ind = compute_indicators(df, md.params)
        except Exception as e:
            log.debug("%s — bollinger kijelzés: %s", md.symbol, e)
            return {"marks": empty}
        st = _advance(SqueezeState(symbol=md.symbol), ind.iloc[-2], md.params)
        return {"marks": self._marks(st, ind.iloc[-1], md.params)}

    def live_cells(self, state: Any, md: MarketData) -> dict:
        df = (md.bars or {}).get("M15")
        if df is None or len(df) < 3:
            return {"marks": {k: Cell(_CIRCLE, "muted") for k, _ in _STAGES}}
        ind = compute_indicators(df, md.params)
        return {"marks": self._marks(state, ind.iloc[-1], md.params)}

    # ── Backtest-hookok ───────────────────────────────────────────────────

    def bt_indicators(self, df_hi, df_lo, params):
        return compute_indicators(df_hi, params), df_lo

    def bt_warmup(self, params: dict, timeframe_label: str) -> int:
        return self.warmup_bars(params, timeframe_label)

    def bt_new_state(self, symbol: str):
        return SqueezeState(symbol=symbol)

    def bt_on_high_close(self, state, hi_row, params):
        return _advance(state, hi_row, params)

    def bt_on_low_close(self, state, prev_lo_row, lo_row, params) -> str:
        """A KÉZBESÍTÉS: az M15-ön született jel az első M1 gyertyán megy ki,
        EGYSZER. (A döntés az M15-é — lásd a modul fejlécét.)"""
        sig, state.pending = state.pending, "NONE"
        return sig

    def sl_tp_points(self, hi_row, params, point_size):
        """SL/TP TÁV PONTBAN — tiszta méretezés, szűrő NÉLKÜL."""
        atr = hi_row.get("atr")
        if atr is None or (isinstance(atr, float) and math.isnan(atr)) or atr <= 0:
            return None
        if not point_size:
            return None
        sl = float(atr) * float(params.get("sl_atr_mult", 1.0)) / float(point_size)
        if sl <= 0:
            return None
        return sl, sl * float(params.get("tp_rr", 2.0))

    def bt_entry(self, hi_row, params, point_size):
        """Belépés-kapu + méretezés — a backtest ÉS az él UGYANEZT hívja.

        A közös volatilitás-mércét használja (`core.vol_baseline`), mint a
        `wpr_sma`: `atr_min_pct`/`atr_max_pct` a kalibrált mércéhez képest. Nulla
        küszöb → a szűrő kikapcsolva (ez az alapértelmezés ennél a stratégiánál:
        a squeeze MAGA a volatilitás-szűrő, kétszer szűrni értelmetlen)."""
        from core import vol_baseline as _vb
        atr = hi_row.get("atr")
        if atr is None or (isinstance(atr, float) and math.isnan(atr)) or atr <= 0:
            return None
        base = _vb.effective(params, hi_row.get("atr_avg", 0))
        if base and base > 0:
            lo, hi = _vb.band(params, base)
            if lo > 0 and atr < lo:
                return None
            if hi > 0 and atr > hi:
                return None
        return self.sl_tp_points(hi_row, params, point_size)

    # ── Optimalizálás ─────────────────────────────────────────────────────

    def base_params(self, cfg: dict) -> dict:
        return {**cfg.get("indicators", {}), **cfg.get("sltp", {})}

    def param_space(self, cfg: dict, base_params: dict, method: str,
                    max_trials: int) -> list[dict]:
        from ml.param_space import generate_grid_params, generate_random_params
        opt_cfg = cfg["optimizer"]
        if method == "grid":
            return generate_grid_params(opt_cfg, base_params, self.constraints_ok)
        return generate_random_params(opt_cfg, base_params, max_trials,
                                      self.constraints_ok)

    _constraints_cache = None

    def _opt_constraints(self) -> list:
        if self._constraints_cache is None:
            import json
            from pathlib import Path
            p = Path(__file__).resolve().parent / "config" / f"{self.name}.json"
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                self._constraints_cache = ((data.get("optimizer") or {})
                                           .get("constraints") or [])
            except Exception:
                self._constraints_cache = []
        return self._constraints_cache

    def constraints_ok(self, params: dict) -> bool:
        from core import param_constraints
        return param_constraints.check(params, self._opt_constraints())

    def magic(self, cfg: dict) -> int:
        return int(cfg.get("broker", {}).get("magic", 0)) + MAGIC_OFFSET

    # ── MT5 chart-vizualizáció ────────────────────────────────────────────

    def visual_objects(self, md: MarketData) -> list:
        """Squeeze-sáv + belépő-jelölők.

        ⚠ CSAK MEGLÉVŐ rajz-primitíveket használ (`BarState`, `VLine`, `Trend`),
        hogy NE kelljen MQL5-öt újrafordítani. A sáv-állapot ugyanabba a
        `TradeForgeBands` al-ablakba megy, mint a `wpr_sma`-é: a kék „ablak" itt
        az összeszűkülés, a zöld/piros a trend iránya."""
        df = (md.bars or {}).get("M15")
        if df is None or len(df) < 3:
            return []
        ind = compute_indicators(df, md.params)
        objs: list = []
        times = [int(t.timestamp()) for t in ind.index]
        m15_sec = (int((ind.index[1] - ind.index[0]).total_seconds())
                   if len(ind) >= 2 else 900)

        st = SqueezeState(symbol=md.symbol)
        for i in range(len(ind) - 1):              # csak ZÁRT gyertyák
            row = ind.iloc[i]
            st = _advance(st, row, md.params)
            d = _trend_dir(row, md.params)
            # A cella a KÖVETKEZŐ gyertya alá esik: a jelzés a gyertya ZÁRÁSA
            # után él (ugyanaz az igazítás, mint a `wpr_sma`-nál).
            objs.append(viz.BarState(t=times[i] + m15_sec, notrade=0, dir=d,
                                     window=1 if st.in_squeeze else 0))
            if st.pending in ("BUY", "SELL") and getattr(md, "show_signals", True):
                t = times[i] + m15_sec
                objs.append(viz.VLine(name=f"bsq_{t}", t1=t,
                                      color="lime" if st.pending == "BUY" else "red"))
                plan = self.sl_tp_points(row, md.params,
                                         md.params.get("point_size", 0.0001))
                if plan:
                    pip = md.params.get("point_size", 0.0001)
                    entry = float(row["close"])
                    sl_p, tp_p = plan
                    up = st.pending == "BUY"
                    sl = entry - sl_p * pip if up else entry + sl_p * pip
                    tp = entry + tp_p * pip if up else entry - tp_p * pip
                    for tag, price, col in (("e", entry, "orange"),
                                            ("t", tp, "lime"), ("s", sl, "red")):
                        objs.append(viz.Trend(name=f"bsq{tag}_{t}",
                                              t1=t - 3 * 60, p1=price,
                                              t2=t + 3 * 60, p2=price, color=col))
            st.pending = "NONE"
        return objs

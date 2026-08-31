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

from core.i18n import t as _t
import numpy as np
import pandas as pd

from strategy import visual as viz
from strategy.base import (Cell, Column, MarkerColumn, MarketData, Strategy,
                           Timeframe)

MAGIC_OFFSET = 3          # 0=wpr_sma, 1=ml_ai, 2=bollinger, 30=candle_level_break

_CIRCLE = "●"
# ⚠ A FELIRAT PONTOS: a feltétel az ár a H1 Keltner FELSŐ sávja fölött —
# egy szűk állapot (mérve: a percek 3-6%-a), NEM „van-e trend és merre".
# A régi „H1 trend" azt sugallta, hogy a kör IRÁNYT mutat, és a felhasználó
# jogosan hiányolta a zöld/piros színezést. A stratégia LONG-ONLY — piros
# állapot nem is létezik benne (lásd `docs/trend_pullback.md`).
_STAGES = (("trend", _t("stage.tp_trend")), ("vol", _t("stage.tp_vol")),
           ("belep", _t("stage.tp_entry")))
_MARKS_EMPTY = {k: Cell(_CIRCLE, "muted") for k, _ in _STAGES}

# A három feltétel időkerete. NEM paraméter: a keresés ezeken találta, és a
# kombináció együtt érvényes — külön hangolva elveszne a jelentése.
TF_BELEP, TF_VOL, TF_TREND = 5, 30, 60

# Hany H1 gyertyara rajzoljuk a Keltner-vonalakat. A teljes ablak
# ezres nagysagrendu objektumot jelentene; 300 H1 = ~12 nap.
_BAND_BARS = 300


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

    # --- MT5 chart-vizualizáció ------------------------------------------

    def visual_lookback_bars(self, params: dict, timeframe_label: str) -> int:
        """Mennyi gyertya kell a RAJZHOZ (a jelzés-warmup fölött).

        ⚠ A H1 vonalak az M1-ből képződnek (`_resample`), ezért az M1 ablaknak
        kell mélynek lennie — nem az M15-nek. `_BAND_BARS` H1 gyertya = 300 × 60
        perc, plusz a warmup, ami a Keltner EMA/ATR-hez kell."""
        if timeframe_label == "M1":
            return self._m1_warmup(params) + _BAND_BARS * TF_TREND
        # ⚠ AZ M15-NEK IS LE KELL FEDNIE A TELJES RAJZ-SZAKASZT. Az SL/TP méret
        # az M15 ATR-ből jön, tehát minden kirajzolt belépőhöz kell egy M15 sor
        # a saját időpontjából. Egy sekély M15 ablaknál a régebbi jelölők
        # NÉMÁN SL/TP-vonal nélkül maradnának — mérve: 17 belépőből 2-nek volt
        # csak. `_BAND_BARS` H1 = ugyanennyi × 4 M15 gyertya.
        return max(self.warmup_bars(params, "M15"),
                   _BAND_BARS * (TF_TREND // 15) + 50)

    def visual_objects(self, md: MarketData) -> list:
        """A H1 Keltner-vonalak + a hármas együttállás sávja + belépő-jelölők.

        ⚠ CSAK MEGLÉVŐ rajz-primitíveket használ (`Trend`, `BarState`, a közös
        `viz.entry_marks`) — nincs MQL5-újrafordítás.

        ⚠ MIÉRT KELL EZ EGYÁLTALÁN. A „H1 felső sáv fölött" kör a percek 3-6%-án
        ég, és a felhasználó jogosan kérdezte, mit jelent pontosan. Egy kör nem
        tudja megmutatni, hogy az ár MENNYIRE van közel a sávhoz — a chartra
        rajzolt vonal igen.

        ⚠ AZ ALSÓ SÁVOT SZÁNDÉKOSAN NEM RAJZOLJUK. A stratégia LONG-ONLY, és
        egyedül a FELSŐ sáv szerepel a feltételben (`c60 > EMA + k·ATR`). Egy
        alsó vonal azt sugallná, hogy az is számít — a chart pontosan annyit
        mutasson, amennyit a döntés használ."""
        df1 = (md.bars or {}).get("M1")
        if df1 is None or len(df1) < TF_TREND * 3:
            return []
        p = md.params or {}
        p_kel = int(p.get("keltner_period", 14) or 14)
        k_mul = float(p.get("keltner_mult", 2.0) or 2.0)

        d60 = _resample(df1, TF_TREND)
        if len(d60) < p_kel + 2:
            return []
        c60 = d60["close"].to_numpy(float)
        ema = _ema(c60, p_kel)
        atr = _atr(d60["high"].to_numpy(float), d60["low"].to_numpy(float),
                   c60, p_kel)
        felso = ema + k_mul * atr

        objs: list = []
        # ── A KÉT VONAL a charton ──────────────────────────────────────────
        # Szakaszokból (`Trend`), csak a legutóbbi `_BAND_BARS` H1 gyertyára.
        _n = min(_BAND_BARS, len(d60))
        _t60 = [int(t.timestamp()) for t in d60.index[-_n:]]
        # ⚠ A NÉV NEM LEHET `tp_…`: az MT5 objektumokat a NEVÜK azonosítja, és a
        # közös rajzoló a take-profit vonalat `tp_<időbélyeg>` néven teszi ki. Egy
        # `tp_` előtagú vonal itt összekeverhető volna vele — a chart némán
        # felülírná az egyiket a másikkal. Ezért `tpk_` (trend-pullback Keltner).
        for _nev, _sor, _szin, _w in (("tpk_mid", ema[-_n:], "blue", 1),
                                      ("tpk_up", felso[-_n:], "orange", 2)):
            for i in range(len(_sor) - 1):
                a, b = _sor[i], _sor[i + 1]
                if a != a or b != b:               # NaN-szűrő
                    continue
                objs.append(viz.Trend(name=f"{_nev}_{_t60[i]}",
                                      t1=_t60[i], p1=float(a),
                                      t2=_t60[i + 1], p2=float(b),
                                      color=_szin, width=_w))

        # ── A HÁRMAS EGYÜTTÁLLÁS sávja + a belépők ─────────────────────────
        # ⚠ UGYANAZ a `signal_column`, amivel a motor dolgozik — nem egy
        # második képlet. Így a charton látott jelölő és az élő belépő nem
        # tud szétcsúszni.
        try:
            m = _stage_masks(df1, p)
            sig = signal_column(df1, p)
        except Exception:
            return objs
        idx = df1.index
        _m1_sec = 60
        # A sáv a H1-feltételt mutatja (ez a „kontextus"): amíg világít, a
        # stratégia egyáltalán szóba jöhet. Óránként EGY rekord elég — az M1
        # felbontás itt ezres objektumszámot jelentene.
        _lep = TF_TREND
        for i in range(len(idx) - 1, max(0, len(idx) - _BAND_BARS * _lep), -_lep):
            _tr = bool(m["trend"][i])
            objs.append(viz.BarState(t=int(idx[i].timestamp()), notrade=0,
                                     dir=1 if _tr else 0, window=1 if _tr else 0))

        # Belépő: a hármas együttállás FELFUTÓ ÉLE (ugyanaz, mint az
        # `on_bar_close`-ban). A `_BAND_BARS` H1-nyi múltra nézünk vissza.
        _kezd = max(1, len(idx) - _BAND_BARS * TF_TREND)
        pip = p.get("point_size", 0.0001)
        try:
            hi, _lo = self.bt_indicators((md.bars or {}).get("M15"), df1, p)
        except Exception:
            hi = None
        for i in range(_kezd, len(idx) - 1):        # csak ZÁRT M1 gyertyák
            if not (bool(sig[i]) and not bool(sig[i - 1])):
                continue
            t = int(idx[i].timestamp()) + _m1_sec
            entry = float(df1["close"].iloc[i])
            sl = tp = None
            sl_p = None
            if hi is not None and len(hi):
                # A méret az M15 ATR-ből jön (`sl_tp_points`) — a belépő
                # időpontjához tartozó utolsó ZÁRT M15 sorból.
                _h = hi[hi.index <= idx[i]]
                if len(_h):
                    _plan = self.sl_tp_points(_h.iloc[-1], p, pip)
                    if _plan:
                        sl_p, tp_p = _plan
                        sl = entry - sl_p * pip
                        tp = entry + tp_p * pip
            _lab = f"{self.short_name} BUY"
            if sl_p and callable(getattr(md, "lot_of", None)):
                _l = md.lot_of(sl_p)
                if _l and _l > 0:
                    _lab += f" {_l:.2f} lot"
            # ⚠ A rekord a rajz-kapu ELŐTT megy a naplóba: a „K" gomb a RAJZOT
            # kapcsolja, nem a történést — különben a chart előzménye csendben
            # lyukas lenne azokon az időszakokon, amikor a jelölők ki voltak
            # kapcsolva.
            rec = {"t": t, "d": "BUY", "e": entry, "sl": sl, "tp": tp,
                   "lab": _lab}
            _sink = getattr(md, "on_entry_record", None)
            if callable(_sink):
                _sink(rec)
            if getattr(md, "show_signals", True):
                objs += viz.entry_marks(rec)
        return objs

    def bt_entry(self, hi_row, params, point_size):
        return self.sl_tp_points(hi_row, params, point_size)

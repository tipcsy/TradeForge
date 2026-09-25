"""CSILLA BESZÁLLÓJA — szerkezet-törés két idősíkon, DAYTRADE.

A módszer (az Obsidian „Stratégiák/Csilla beszállója" jegyzet, a felhasználó
2026-09-22-i olvasatában): választunk EGY idősík-párt, a FELSŐ idősík áttöri a
SAJÁT utolsó igazolt swingjét, és a belépő az ALSÓ idősík zászló-törése.

    tf_pair = "H1-M15"   a H1 töri a saját csúcsát/völgyét, belépő M15-ön
    tf_pair = "M15-M1"   a M15 töri a sajátját, belépő M1-en

⚠ H4 A PLAFON. A jegyzet négy párt sorol fel (W1-D1, D1-H4, H1-M15, M15-M1);
a felhasználó kikötése szerint ez a stratégia DAYTRADE, tehát a felső kettő nem
használható. A kikötés a `csilla_rules.MAX_TF_MIN`-ben ki is van kényszerítve —
és CSAK erre a stratégiára vonatkozik, más stratégia bármilyen idősíkot
használhat.

⚠ AMI 2026-09-22-ig ITT VOLT: egy D1/W1 SZINT-RÉTEG (napi/heti swing-szintek
élettartammal, amiket az M15 tört). Az nem a módszer volt, hanem az én
bevezetésem — a felhasználó a jegyzetet újraolvasva mondta ki, hogy a napi/heti
chart csak egy opció volt, amit nem kér. A kódja a
`tools/research/csilla_variants.py` fagyasztott modulban él tovább, a rá épülő
forward-teszt pedig lezárult (lásd `strategies/csilla_forward.py`).

⚠ A SZABÁLY NEM ITT VAN. A szerkezet-/belépő-logika a `strategies/csilla_rules`
modulban él, és a kutató-labor UGYANAZT hívja — a paritás szerkezeti, nem
ígéret (`tests/test_csilla_parity.py`). Ez a modul csak a keret hookjait adja:
időkeretek, warmup, jelölő-oszlop, élő jelzés, backtest-oszlopok, SL/TP, viz.

A KILÉPÉS NEM A STRATÉGIÁÉ (lásd `strategy/base.py`): a `breakeven_r`, a
trailing és a preset a PÁR kockázatcsökkentésében áll. A célár itt szándékosan
MESSZE van (`tp_rr_ratio`, alap 30): a mért változatban nincs célár, a BE pedig
R-alapú, tehát a távoli célár nem kapcsolja ki (`be-threshold-is-tp-relative`).

⚠ AZ IDŐSÍK-PÁR STRATÉGIA-SZINTŰ, nem instrumentumonkénti: a
`Strategy.timeframes()` az egész keret adat-szerződése (letöltés,
visszaszámlálók, portfólió-backtest, viz), és egyik hívója sem tud paramétert
adni neki. Ugyanaz a megkötés, mint az `ml_ai` jel-idősíkjánál.
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
# ⚠ ÖT ÁLLOMÁS, nem három (2026-09-23, a felhasználó kérése: „látszódjon
# minél jobban, mi is történik"). A lánc minden lépésének saját pöttye van:
#   szerk  a felső idősík áttörte a saját swingjét, a setup ÉL
#   korr   a törés megvolt, a korrekció épül, a pipa MÉG NINCS
#   pipa   a pipa megvolt → nyitva a belépő-ablak az alsó kereten
#   zaszlo az alsó kereten épp épül egy elég hosszú counter-trend korrekció
#   belep  az utolsó ZÁRT alsó gyertya belépőt ad
_STAGES = (("szerk", _t("stage.cs_struct")), ("korr", _t("stage.cs_corr")),
           ("pipa", _t("stage.cs_pipa")), ("zaszlo", _t("stage.cs_flag")),
           ("belep", _t("stage.cs_entry")))
_MARKS_EMPTY = {k: Cell(_CIRCLE, "muted") for k, _ in _STAGES}

_TF_LABEL = {1: "M1", 5: "M5", 15: "M15", 30: "M30", 60: "H1", 240: "H4"}
_tf_cache: dict = {}          # (mtime) → tf_pair; a config-fájl változását követi


def tf_pair() -> str:
    """Az idősík-pár a stratégia SAJÁT configjából (`indicators.tf_pair`).

    Közvetlenül a fájlból olvassuk, mert a `timeframes()` hívóinak nincs
    cfg-jük; az mtime-cache miatt ez körönként egy `stat()`. Ugyanaz a minta,
    mint az `ml_ai.signal_tf_min`-nél."""
    import json as _json
    from strategy.settings import strategy_config_path
    alap = sw.DEFAULTS["tf_pair"]
    try:
        f = strategy_config_path("csilla")
        mtime = f.stat().st_mtime
    except OSError:
        return alap
    if _tf_cache.get("mtime") == mtime:
        return _tf_cache["v"]
    val = alap
    try:
        with open(f, encoding="utf-8") as fh:
            nyers = (_json.load(fh).get("indicators") or {}).get("tf_pair")
        if nyers:
            kulcs = str(nyers).strip().upper().replace("_", "-")
            if kulcs in sw.TF_PAIRS:
                val = kulcs
            else:
                import logging
                logging.getLogger(__name__).warning(
                    "csilla — tf_pair=%s nem megengedett (%s) → %s",
                    nyers, tuple(sw.TF_PAIRS), alap)
    except Exception:
        pass
    _tf_cache.update({"mtime": mtime, "v": val})
    return val


def _tf_min() -> tuple:
    """`(felső perc, alsó perc)` az aktuális idősík-párból."""
    return sw.parse_tf_pair(tf_pair())


def _P(params: dict) -> dict:
    """A core paraméterei a stratégia-configból (a hiányzókra a DEFAULTS).
    `sl_atr_mult` a keret konvenciója (mint a többi stratégiánál); a core
    belső neve `stop_atr`."""
    p = dict(sw.DEFAULTS)
    for k in ("k_hi", "k_lo", "max_wait", "buffer_atr", "min_sl_atr",
              "pipa_k", "pipa_w1", "pipa_melyseg", "pipa_min_tart",
              "korr_min", "belepo_mod", "veg_mod"):
        if params.get(k) is not None:
            p[k] = params[k]
    p["stop_atr"] = float(params.get("sl_atr_mult", params.get("stop_atr", 1.5)) or 1.5)
    # ⚠ Az idősík-pár NEM a `params`-ból jön: stratégia-szintű (lásd a fejlécet).
    p["tf_pair"] = tf_pair()
    return sw.with_tf_pair(p)


def _spread_ar(params: dict) -> float:
    """A stophoz adott spread ÁRBAN. A szabály szerint a stop a korrekció
    teteje + spread — enélkül a stopot a vételi-eladási különbség önmagában
    kiütné. Ha a keret nem ad spread-becslést, 0 (és a stop pont a tetőn ül)."""
    ps = float(params.get("point_size", 0) or 0)
    pt = params.get("spread_points", params.get("backtest_spread_points", 0))
    try:
        return max(0.0, float(pt or 0)) * ps
    except (TypeError, ValueError):
        return 0.0


def _korrekcio_epul(lo: pd.DataFrame, d: int, korr_min: int) -> bool:
    """Épül-e ÉPPEN egy elég hosszú counter-trend korrekció az alsó kereten?
    Medve setupnál emelkedő aljak sorozata, legalább `korr_min` gyertya — ez az
    az állapot, amikor a következő belépőre várunk."""
    l = lo["low"].to_numpy(float)
    h = lo["high"].to_numpy(float)
    n = len(l)
    if n < korr_min + 2:
        return False
    db = 0
    for j in range(n - 1, 0, -1):
        if (l[j] > l[j - 1]) if d < 0 else (h[j] < h[j - 1]):
            db += 1
        else:
            break
    return db >= korr_min


def _last_swings(hi: pd.DataFrame, k: int) -> list:
    """A felső keret utolsó IGAZOLT csúcsának és völgyének ára (0–2 elem).
    A „szint" stádium ezt nézi: az ár közel van-e ahhoz, amit törnie kell.
    Igazolt = a pivot legfeljebb a (len−1−k)-adik bar (k barral később derül ki)."""
    h = hi["high"].to_numpy(float)
    l = hi["low"].to_numpy(float)
    pc, pv = sw.pivots(h, l, k)
    hat = len(hi) - 1 - k
    out = []
    for arr, tomb in ((pc, h), (pv, l)):
        j = np.flatnonzero(arr[:max(0, hat + 1)])
        if len(j):
            out.append(float(tomb[j[-1]]))
    return out


def _ar(x: float, point_size) -> str:
    """Ár szövegként, a pár TIZEDESEIVEL. ⚠ Soha nem `%g`: az a nagy indexeken
    exponenciálisra vált (`2.5e+04`), devizán meg levágja a tizedeseket — a
    projekt ezt háromszor tanulta meg. A tizedesek a `point_size`-ból jönnek."""
    import math
    try:
        ps = float(point_size or 0)
        tiz = min(8, max(0, int(round(-math.log10(ps))))) if ps > 0 else 2
    except (TypeError, ValueError):
        tiz = 2
    return f"{float(x):.{tiz}f}"


def _frames(md) -> tuple:
    """`(felső, alsó)` ZÁRT keret az `md.bars`-ból, az aktuális idősík-pár
    címkéi szerint. EGY hely, ahol a keret-NEVEK feloldódnak — eddig öt helyen
    állt bedrótozva az „M15"/„M1", és egy pár-váltás némán üres jelzést adott
    volna (a `bars.get("M15")` egyszerűen None-t ad, hibát nem)."""
    hi_min, lo_min = _tf_min()
    bars = (getattr(md, "bars", None) or {})
    return (_closed(bars.get(_TF_LABEL[hi_min])),
            _closed(bars.get(_TF_LABEL[lo_min])))


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
        # (symbol, utolsó zárt felső idő, paraméter-ujjlenyomat) → lánc-kontextus
        self._ctx_cache: dict = {}
        # symbol → a legutóbbi belépő stop-távolsága PONTBAN (lásd `bt_on_low_close`)
        self._pending: dict = {}

    # --- Napi feladat: a forward-napló --------------------------------------

    def daily_jobs(self) -> list:
        """A Csilla-sáv forward-tesztjének napi frissítése — a stratégia SAJÁT
        feladata (a keret nem ismeri; törölt stratégiával eltűnik). A modult itt
        importáljuk, hogy a `.tfs` csomagoló segédmodulként vigye."""
        from strategies import csilla_forward as _fw
        return [_fw.job_spec()]

    # --- Megjelenítés -----------------------------------------------------

    def timeframes(self) -> list[Timeframe]:
        hi, lo = _tf_min()
        return [Timeframe(_TF_LABEL[hi], hi), Timeframe(_TF_LABEL[lo], lo)]

    def columns(self) -> list[Column]:
        return [MarkerColumn("marks", self.name, stages=_STAGES)]

    def warmup_bars(self, params: dict, timeframe_label: str) -> int:
        """⚠ EZ MÁR NEM MÉLY. A D1/W1 szint-réteg idején a felső keretnek ~1 évet
        kellett lefednie (36 000 M15 gyertya), mert egy heti szint 365 napig élt.
        A páros olvasat csak a SAJÁT utolsó pár swingjét nézi: elég annyi gyertya,
        amiben két-két swing igazolódik (a trend-címkéhez) + ATR(14). 500 felső
        gyertya H1-en ~3 hét, M15-ön ~5 nap — bőven fedi."""
        p = _P(params)
        hi_min, lo_min = p["hi_tf"], p["lo_tf"]
        if timeframe_label == _TF_LABEL[hi_min]:
            return 500
        # alsó keret: a törés utáni ablak + a pivot félablak + ATR(14)
        return int(p["max_wait"] * hi_min // max(1, lo_min) + 2 * p["k_lo"] + 30)

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
            ctx = dict(P=p, setups=sw.chain_setups(hi, p),
                       a15=sw.atr(hi["high"].to_numpy(float),
                                  hi["low"].to_numpy(float),
                                  hi["close"].to_numpy(float), 14))
            # csak a legutóbbi kontextust tartjuk páronként
            self._ctx_cache = {k: v for k, v in self._ctx_cache.items() if k[0] != symbol}
            self._ctx_cache[key] = ctx
        return ctx

    def _signals(self, symbol: str, hi: pd.DataFrame, lo: pd.DataFrame, params: dict):
        """`(sig, sl_tav, ctx)` az ALSÓ keret soraira — ZÁRT keretekből.

        `sig` = +1/−1 a belépő baron (0 máshol), `sl_tav` a stop TÁVOLSÁGA
        ÁRBAN (a korrekció teteje + spread, a belépőtől mérve)."""
        ctx = self._context(symbol, hi, params)
        n = len(lo)
        sig = np.zeros(n, dtype=np.int8)
        sl = np.full(n, np.nan)
        et = sw.counter_entries(lo, ctx["setups"], ctx["P"],
                                spread=_spread_ar(params))
        if len(et):
            et = et.drop_duplicates("i", keep="first")
            ii = et.i.to_numpy(int)
            sig[ii] = et.dir.to_numpy(int)
            sl[ii] = et.sl_abs.to_numpy(float)
        return sig, sl, ctx

    def compute_display(self, md: MarketData) -> dict[str, Cell]:
        """A lánc öt állomása pöttyönként (lásd `_STAGES`). A szín az IRÁNYT
        mondja: zöld = felfelé, piros = lefelé; a sárga azt, hogy még várunk."""
        empty = dict(_MARKS_EMPTY)
        hi, lo = _frames(md)
        if hi is None or lo is None or len(hi) < 50:
            return empty
        try:
            sig, _sl, ctx = self._signals(md.symbol, hi, lo, md.params or {})
        except Exception:
            return empty
        out = dict(empty)
        t_now = hi.index[-1]
        elo = [x for x in ctx["setups"] if x["t_veg"] >= t_now]
        # ⚠ A NYITOTT BELÉPŐ-ABLAK AZ ÉRDEKES, nem a legfrissebb törés. Egyszerre
        # több setup is élhet; ha mindig az utolsót mutatnánk, a „pipa" pötty
        # SOHA nem gyulladna ki (a legfrissebb törésnél még nincs pipa).
        _nyit = [x for x in elo if x["i_pipa"] is not None
                 and hi.index[x["i_pipa"]] <= t_now]
        if _nyit or elo:
            su = _nyit[-1] if _nyit else elo[-1]
            szin = "green" if su["dir"] > 0 else "red"
            out["szerk"] = Cell(_CIRCLE, szin)
            van_pipa = (su["i_pipa"] is not None
                        and hi.index[su["i_pipa"]] <= t_now)
            if van_pipa:
                out["pipa"] = Cell(_CIRCLE, szin)
            else:
                out["korr"] = Cell(_CIRCLE, "yellow")
            # a ZÁSZLÓ: épül-e MÉG le nem tört counter-trend korrekció az alsón
            if van_pipa and _korrekcio_epul(lo, su["dir"], int(ctx["P"]["korr_min"])):
                out["zaszlo"] = Cell(_CIRCLE, "yellow")
        if len(sig) and sig[-1] != 0:
            out["belep"] = Cell(_CIRCLE, "green" if sig[-1] > 0 else "red")
        return out

    # --- Élő jelzés -------------------------------------------------------

    def new_signal_state(self, symbol: str) -> _State:
        return _State(symbol)

    def on_bar_close(self, state: _State, md: MarketData) -> tuple[_State, str]:
        hi, lo = _frames(md)
        if hi is None or lo is None or len(hi) < 50:
            return state, "NONE"
        try:
            sig, _sl, _ctx = self._signals(md.symbol, hi, lo, md.params or {})
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
        """hi: `atr` (a keret közös ATR-je); lo: `cs_sig` (+1/−1 a belépő baron)
        és `cs_sl_pts` (a stop TÁVOLSÁGA PONTBAN).

        ⚠ A STOP BELÉPŐNKÉNT MÁS (a korrekció teteje + spread), a keret
        `sl_tp_points`-ja viszont csak a FELSŐ sort látja. Ezért a belépő
        pillanatában a `bt_on_low_close` félreteszi a stopot páronként, és a
        `sl_tp_points` onnan veszi. A `params["symbol"]` mindkét úton megvan
        (a `run_pair` és a `live_trader` is injektálja)."""
        hi = df_hi.copy()
        lo = df_lo.copy()
        p = _P(params)
        hi["atr"] = sw.atr(hi["high"].to_numpy(float), hi["low"].to_numpy(float),
                           hi["close"].to_numpy(float),
                           int(params.get("atr_period", 14) or 14))
        sym = str(params.get("symbol", "") or "")
        ctx = self._context(sym, hi, params)
        n = len(lo)
        sig = np.zeros(n, dtype=np.int8)
        slp = np.full(n, np.nan)
        et = sw.counter_entries(lo, ctx["setups"], ctx["P"], spread=_spread_ar(params))
        ps = float(params.get("point_size", 0) or 0)
        if len(et) and ps > 0:
            et = et.drop_duplicates("i", keep="first")
            ii = et.i.to_numpy(int)
            sig[ii] = et.dir.to_numpy(int)
            slp[ii] = et.sl_abs.to_numpy(float) / ps
        lo["cs_sig"] = sig
        lo["cs_sl_pts"] = slp
        return hi, lo

    def bt_warmup(self, params: dict, timeframe_label: str) -> int:
        return self.warmup_bars(params, timeframe_label)

    def bt_new_state(self, symbol: str) -> _State:
        return _State(symbol)

    def bt_on_high_close(self, state, hi_row, params):
        return state

    def bt_on_low_close(self, state, prev_lo_row, lo_row, params) -> str:
        try:
            s_ = int(lo_row["cs_sig"])
            sl = float(lo_row["cs_sl_pts"])
        except (KeyError, TypeError, ValueError):
            return "NONE"
        if s_ == 0 or not (sl > 0):
            return "NONE"
        # ⚠ A stop félretétele PÁRONKÉNT: a `sl_tp_points` csak a felső sort
        # kapja, a mi stopunk viszont ehhez az EGY belépőhöz tartozik.
        self._pending[str(params.get("symbol", "") or state.symbol)] = sl
        return "BUY" if s_ > 0 else "SELL"

    def chart_spec(self, params: dict) -> dict:
        """A jelzés-képre: a stratégia SAJÁT idősík-párja (pl. H1 + M15). A
        swing-szerkezetnek nincs szabványos indikátora — a gyertyák és a
        belépő szintjei mutatják a törést."""
        hi, lo = _tf_min()
        return {"tfs": [int(hi), int(lo)]}

    def sl_tp_points(self, hi_row, params, point_size):
        """A stop a LEGUTÓBBI belépő korrekció-tetejéből (+ spread), pontban.
        TP = SL × `tp_rr_ratio` — alapból messze (a mért változatban nincs célár,
        a BE pedig R-alapú, tehát a távoli célár nem kapcsolja ki)."""
        sl = self._pending.get(str(params.get("symbol", "") or ""))
        if not sl or not (sl > 0):
            return None
        return sl, sl * float(params.get("tp_rr_ratio", 30.0) or 30.0)

    # --- MT5 chart-vizualizáció ------------------------------------------

    def visual_lookback_bars(self, params: dict, timeframe_label: str) -> int:
        hi_min, lo_min = _tf_min()
        if timeframe_label == _TF_LABEL[lo_min]:
            return 3 * 1440 // max(1, lo_min)      # 3 nap belépő a charton
        return max(300, 3 * 1440 // max(1, hi_min) + 100)

    def visual_objects(self, md: MarketData) -> list:
        """A LÁNC a charton: a tört H1 szint (a swingjétől a töréséig), a törés
        függőlegese felirattal, a pipa (2. jelzés), és a belépők a közös
        rajzolóval (ami a belépő-naplót is tölti).

        ⚠ NINCS teljes ablakon áthúzott vízszintes. A 2026-09-15-i változat az
        élő D1/W1 szinteket húzta át az egész charton — a felhasználó jogosan
        „szemétnek" olvasta: egy vonal, aminek se az eredete, se a vége nem
        látszik. Minden szakasz ONNAN indul, ahol a swing van, és OTT ér véget,
        ahol törik."""
        hi, lo = _frames(md)
        if hi is None or lo is None or len(hi) < 50:
            return []
        p = md.params or {}
        try:
            sig, sl, ctx = self._signals(md.symbol, hi, lo, p)
        except Exception:
            return []
        objs: list = []
        t0 = lo.index[0]
        hi_min = ctx["P"]["hi_tf"]
        pip = float(p.get("point_size", 0.0001) or 0.0001)
        for su in ctx["setups"]:
            tb = hi.index[su["i_break"]]
            if tb < t0:
                continue
            tc = int((tb + pd.Timedelta(minutes=hi_min)).timestamp())
            d = su["dir"]
            objs.append(viz.VLine(name=f"cs_brk_{tc}", t1=tc, color="darkgold", width=2))
            objs.append(viz.Trend(name=f"cs_lvl_{tc}", t1=int(tb.timestamp()),
                                  p1=float(su["level"]), t2=tc, p2=float(su["level"]),
                                  color="blue", width=2))
            objs.append(viz.Text(
                name=f"cs_brktxt_{tc}", t1=tc, p1=float(su["level"]),
                text=(f"{_TF_LABEL[hi_min]} tores {'FEL' if d > 0 else 'LE'} "
                      f"{_ar(su['level'], pip)}"),
                color=("green" if d > 0 else "red"), fontsize=9))
            # ⚠ `i_pipa` lehet None (a törés megvolt, a pipa még nem) — az
            # `hi.index[None]` nem hibát dob, hanem TÖBBDIMENZIÓS indexelést
            # próbál, és egy érthetetlen ValueError-ral áll meg.
            if su["i_pipa"] is None:
                continue
            tp_ = hi.index[int(su["i_pipa"])]
            if tp_ >= t0:
                tpc = int((tp_ + pd.Timedelta(minutes=hi_min)).timestamp())
                objs.append(viz.VLine(name=f"cs_pipa_{tpc}", t1=tpc,
                                      color="magenta", width=2))
                objs.append(viz.Text(name=f"cs_pipatxt_{tpc}", t1=tpc,
                                     p1=float(hi["close"].iloc[su["i_pipa"]]),
                                     text="pipa (2. jelzes)", color="magenta",
                                     fontsize=8))
        _recs = []
        for i in np.flatnonzero(sig != 0):
            ti = lo.index[int(i)]
            d = "BUY" if sig[i] > 0 else "SELL"
            entry = float(lo["close"].iloc[int(i)])
            _sl = entry + (1 if d == "SELL" else -1) * float(sl[i])
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

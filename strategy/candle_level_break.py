"""Gyertyaszint-törés (CLB) — H4 szint + M15 konszolidáció-kitörés.

A módszer forrása egy YouTube-videó („Hogyan alkossunk saját Forex stratégiát"),
a specifikáció a vault-ban: *Gyertyaszint stratégia — H4+M15 specifikáció*.

⚠ EZ A MI VÁLTOZATUNK, nem a szerzőé. A videó több ponton nem elég objektív
(„momentum gyertya", trendvonal-illesztés, belépő pillanata), és a szerző az
ilyen kérdésekre nem válaszol. A hiányzó döntéseket MI hoztuk meg — mindegyik
`[DÖNTÉS]` jelöléssel a kódban. A mérés is erre a változatra vonatkozik.

A SZABÁLY (LONG; SHORT tükrözve):

  1. SZINT      — a H4 swing-alj gyertyájának a TETEJE („a legmélyebb gyertya
                  legmagasabb pontjára, mert fordulást várunk").
  2. TÖRÉS      — egy H4 gyertya TESTE a szint fölé zár.
  3. VISSZATESZT— az ár visszatér a szint közelébe, és a teste nem zár alá.
  4. BELÉPŐ     — a visszateszt után M15-ön kialakul egy szűk konszolidációs
                  sáv, és egy M15 gyertya a sáv CSÚCSA fölé zár.

⚠ [DÖNTÉS] A videó „momentum gyertyát" említ, de a képen bekarikázott formáció
2-3 APRÓ gyertya a szinten, és a belépő az utánuk jövő kitörés. Így a „mekkora a
momentum gyertya?" kérdés elkerülhető: a kitörés a SÁV CSÚCSÁN mérhető, küszöb
nélkül. A trendvonalat sem implementáljuk — a rövid trendvonal kitörése ≈ a sáv
csúcsának átütése, a hosszú pedig szubjektív (mely csúcsokra illesztjük?).

⚠ IDŐSÍK. A keret adat-csővezetéke M15+M1, ezért — a `bollinger_squeeze`
mintájára — a H4-et BELÜL mintavételezzük az M15-ből. Mérve (2026-08-23), miért
épp H4 a szint-idősík:

    TF    szint/hó   szint-táv SPREADBEN (Ger40/GOLD/EURUSD/UsaTec)
    M15   230–300    13,9 / 17,9 /  4,2 / 20,6
    H1     60– 75    33,4 / 41,0 / 10,2 / 49,5
    H4     17– 19    69,2 / 77,4 / 19,9 / 107
    D1      3        118  / 269  / 57,8 / 261

Az EURUSD-n M15 szintekkel a teljes út szinttől szintig 4,2 spread — a költség
megeszi. D1-en viszont 3 szint/hó/pár, ami a 15/50-es kötésszám-korlátokat
(`ml.optimizer`, `core.quality`) nem érné el belátható időn belül.

⚠ ÉS AMIT ELŐRE TUDUNK: a strukturális hozam/kockázat (szinttől a következő
szintig, szemben a szint-gyertya aljáig tartó stoppal) MINDEN idősíkon 0,6–0,9,
tehát 1 ALATT. Az él tehát csakis a SZŰK stopból jöhet — ezért a `stop_buffer_atr`
az első mérendő paraméter, nem az utolsó.
"""

from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd

from strategy.base import (Cell, Column, MarkerColumn, MarketData, Strategy,
                           Timeframe)

log = logging.getLogger(__name__)

# A szint-idősík PERCBEN. A specifikáció szerint H4 — a `param_space` NEM
# hangolja (idősík-váltás új stratégia, nem paraméter).
LEVEL_TF_MIN = 240

_STAGES = (("level",  "Élő szint"),
           ("broken", "Szinttörés"),
           ("cons",   "Konszolidáció (belépő közel)"))


def _to_level_tf(df: pd.DataFrame) -> pd.DataFrame:
    """M15 → H4 átmintázás. A KÖZÖS helperrel (bal-zárt, bal-címkés, mint az MT5)
    — ugyanaz a képlet, amit a `bollinger_squeeze`, az `ml_ai` és a
    `core.tf_align` is használ, hogy a gyertya-határok sehol ne csússzanak el."""
    if df is None or len(df) < 2:
        return df
    from strategy.ml_ai import resample_ohlc
    return resample_ohlc(df, LEVEL_TF_MIN)


def _levels(h4: pd.DataFrame, swing_bars: int, ttl: int) -> pd.DataFrame:
    """A H4 swing-alj/csúcs SZINTEK, gyertyánként az ÉPP ÉLŐ szinttel.

    Visszaad: `long_level`, `long_stop_ref`, `short_level`, `short_stop_ref`
    oszlopok a H4 indexen.

    ⚠ A szint a swing-alj gyertyájának a TETEJE (LONG), illetve a swing-csúcs
    gyertyájának az ALJA (SHORT) — a videó szabálya. A `*_stop_ref` a gyertya
    másik vége: ez a „meddig romolhat el" strukturális pont.

    ⚠ NINCS JÖVŐ-SZIVÁRGÁS: egy `swing_bars` félablakú fraktál CSAK `swing_bars`
    gyertyával KÉSŐBB ismerhető fel, ezért a szintet is csak akkor tesszük élővé
    (`shift(swing_bars)`). Enélkül a backtest olyan szintre lépne be, ami a
    döntés pillanatában még nem létezett — pontosan az a look-ahead, ami az
    `ml_ai` portnál is előjött.
    """
    n = len(h4)
    lo, hi = h4["low"].values, h4["high"].values
    out = {k: np.full(n, np.nan) for k in
           ("long_level", "long_stop_ref", "short_level", "short_stop_ref")}
    k = max(1, int(swing_bars))
    ttl = max(1, int(ttl))
    cur_l = cur_ls = cur_s = cur_ss = np.nan
    age_l = age_s = 10 ** 9
    for i in range(n):
        # A `k`-val korábbi gyertya MOST vált felismerhetővé fraktálként.
        j = i - k
        if j - k >= 0 and j + k < n:
            win_lo = lo[j - k:j + k + 1]
            win_hi = hi[j - k:j + k + 1]
            # ⚠ EGYEDI minimum kell, nem „egyike a legkisebbeknek". Döntetlennél
            # (lapos szakasz, kerek szám körüli ragadás) MINDEN gyertya swingnek
            # számítana, a szint gyertyánként frissülne, és a TTL sosem járna le
            # — mérve: a szint a sorok 98%-ában „élt", mert folyton újraszületett.
            if lo[j] == win_lo.min() and (win_lo == lo[j]).sum() == 1:
                cur_l, cur_ls, age_l = hi[j], lo[j], 0
            if hi[j] == win_hi.max() and (win_hi == hi[j]).sum() == 1:
                cur_s, cur_ss, age_s = lo[j], hi[j], 0
        age_l += 1
        age_s += 1
        if age_l <= ttl:
            out["long_level"][i], out["long_stop_ref"][i] = cur_l, cur_ls
        if age_s <= ttl:
            out["short_level"][i], out["short_stop_ref"][i] = cur_s, cur_ss
    return pd.DataFrame(out, index=h4.index)


class CandleLevelBreakStrategy(Strategy):
    """H4 gyertyaszint törése + M15 konszolidáció-kitörés."""

    name = "candle_level_break"
    short = "CLB"
    display_name = "Gyertyaszint-törés (H4+M15)"

    # ── Váz ───────────────────────────────────────────────────────────────
    def timeframes(self) -> list[Timeframe]:
        # ⚠ A keret adat-csővezetéke M15+M1; a H4-et BELÜL mintavételezzük.
        return [Timeframe("M15", 15), Timeframe("M1", 1)]

    def columns(self) -> list[Column]:
        return [MarkerColumn("marks", self.name, stages=_STAGES)]

    def magic(self, cfg: dict) -> int:
        """EGYEDI magic — hogy a nyitott pozíciók broker-szinten is
        szétválaszthatók legyenek a többi stratégiától."""
        base = int(((cfg or {}).get("broker") or {}).get("magic", 0) or 0)
        return base + 30

    def signal_bar_seconds(self, params: dict) -> int:
        """A DÖNTÉSI gyertya M15 — a riasztás-dedup és a viz idősík-kapuja ebből
        dolgozik (a belépő M15 záráson dől el, nem M1-en)."""
        return 900

    # ── Bemelegítés ───────────────────────────────────────────────────────
    def _h4_bars_needed(self, params: dict) -> int:
        return int(params.get("level_ttl_bars", 120)) + \
            2 * int(params.get("swing_bars", 2)) + 5

    def warmup_bars(self, params: dict, tf_label: str) -> int:
        if tf_label == "M15":
            return self._h4_bars_needed(params) * 16 + 50
        return 120

    def signal_warmup_bars(self, params: dict, tf_label: str) -> int:
        """⚠ MÉLY ablak: a szint állapotgépe a TELJES előzménytől függ (egy régi
        swing-alj élesít egy szintet). Sekély warmuppal a live/dashboard MÁS
        szintet látna, mint a viz — ez a `wpr_sma`-nál valódi, kimaradó
        belépőket okozott."""
        return self.warmup_bars(params, tf_label)

    def bt_warmup(self, params: dict, tf_label: str) -> int:
        return self.warmup_bars(params, tf_label)

    def visual_lookback_bars(self, params: dict, tf_label: str) -> int:
        return self.warmup_bars(params, tf_label)

    # ── Indikátorok (a backtest ÉS az él ugyanezt látja) ──────────────────
    def bt_indicators(self, df_hi, df_lo, params):
        """M15 frame kiegészítése a H4 szintekkel és a konszolidációs sávval.

        ⚠ A `bt_*` hookok EGY SORT kapnak, tehát minden több sort igénylő
        számítás ITT lesz oszloppá."""
        from core.indicator_engine import atr as _atr
        m15 = df_hi.copy()
        h4 = _to_level_tf(m15)
        if h4 is None or len(h4) < 10:
            for c in ("long_level", "long_stop_ref", "short_level",
                      "short_stop_ref", "cons_hi", "cons_lo", "atr"):
                m15[c] = np.nan
            return m15, df_lo

        lv = _levels(h4, int(params.get("swing_bars", 2)),
                     int(params.get("level_ttl_bars", 120)))
        # A H4 értékek az M15 sorokra: `ffill` — egy H4 gyertya alatt végig az
        # akkor ismert szint él (nincs jövőbeli információ).
        for c in lv.columns:
            m15[c] = lv[c].reindex(m15.index, method="ffill")

        # ATR a stop-pufferhez és a volatilitás-szűrőhöz (közös motor).
        m15["atr"] = _atr(m15["high"], m15["low"], m15["close"],
                          int(params.get("atr_period", 14)))
        # A KONSZOLIDÁCIÓS SÁV: az utolsó `cons_bars` M15 gyertya szélsőértékei
        # — a BELÉPŐ gyertyát NEM tartalmazza (`shift(1)`), különben a kitörés
        # saját magát emelné meg.
        cb = max(2, int(params.get("cons_bars", 4)))
        m15["cons_hi"] = m15["high"].rolling(cb).max().shift(1)
        m15["cons_lo"] = m15["low"].rolling(cb).min().shift(1)
        return m15, df_lo

    # ── Élő/backtest állapotgép ──────────────────────────────────────────
    class _St:
        # ⚠ `last_bar_time`: MELYIK ZÁRT gyertyáig jutottunk. A motor 10
        # MÁSODPERCENKÉNT hívja az `on_bar_close`-t, a jel-gyertya viszont 15
        # PERCES — ugyanarra a zárt sorra tucatnyi hívás jut. E nélkül
        # mindegyik LÉPTETETT egyet, tehát a négylépcsős állapotgép
        # (szint → törés → visszateszt → kitörés) percek alatt végigfutott
        # ott, ahol a backtestben órák telnek el.
        __slots__ = ("symbol", "broke_up", "broke_dn", "retested_up",
                     "retested_dn", "fire", "last_bar_time")

        def __init__(self, symbol=""):
            self.symbol = symbol
            self.broke_up = self.broke_dn = False
            self.retested_up = self.retested_dn = False
            self.fire = "NONE"
            self.last_bar_time = None

    def new_signal_state(self, symbol: str):
        return self._St(symbol)

    def bt_new_state(self, symbol: str):
        return self._St(symbol)

    def _step(self, st, row, params) -> str:
        """EGY M15 gyertya feldolgozása. Visszaad: "BUY"|"SELL"|"NONE".

        A négy lépcső: szint → TÖRÉS (test) → VISSZATESZT → kitörés a
        konszolidációs sávból."""
        c, h, l = row.get("close"), row.get("high"), row.get("low")
        o = row.get("open")
        atr = row.get("atr")
        if c is None or atr is None or (isinstance(atr, float) and math.isnan(atr)):
            return "NONE"
        body_lo, body_hi = (min(o, c), max(o, c)) if o is not None else (c, c)
        retest_d = float(params.get("retest_atr", 0.5)) * float(atr)
        cons_max = float(params.get("cons_max_atr", 0.8)) * float(atr)
        ch, cl = row.get("cons_hi"), row.get("cons_lo")
        narrow = (ch is not None and cl is not None
                  and not (isinstance(ch, float) and math.isnan(ch))
                  and not (isinstance(cl, float) and math.isnan(cl))
                  and (ch - cl) <= cons_max)

        # ── LONG ág ───────────────────────────────────────────────────────
        lvl = row.get("long_level")
        if lvl is not None and not (isinstance(lvl, float) and math.isnan(lvl)):
            if not st.broke_up:
                # ⚠ TÖRÉS: a TEST zárjon a szint fölé („testtel nem tudta
                # átvinni" = nincs törés).
                if body_lo > lvl or (c > lvl and body_hi > lvl and c > o):
                    st.broke_up, st.retested_up = True, False
            else:
                if body_hi < lvl:            # a test a szint ALÁ került → elveszett
                    st.broke_up = st.retested_up = False
                # ⚠ A KITÖRÉST ELŐBB nézzük, mint a visszatesztet. A kitörő
                # gyertya ALJA tipikusan MÉG a visszateszt-zónában van (onnan
                # indul!) — fordított sorrendben az `elif` lánc mindig a
                # visszateszt-ágra futna, és a belépő SOSEM tüzelne. Ez volt az
                # oka, hogy az első változat 5 hónap alatt 10 kötést adott.
                elif st.retested_up and narrow and c > ch:
                    st.broke_up = st.retested_up = False
                    return "BUY"
                elif l <= lvl + retest_d:    # visszaért a szint környezetébe
                    st.retested_up = True
        else:
            st.broke_up = st.retested_up = False

        # ── SHORT ág (tükör) ──────────────────────────────────────────────
        slv = row.get("short_level")
        if slv is not None and not (isinstance(slv, float) and math.isnan(slv)):
            if not st.broke_dn:
                if body_hi < slv or (c < slv and body_lo < slv and c < o):
                    st.broke_dn, st.retested_dn = True, False
            else:
                if body_lo > slv:
                    st.broke_dn = st.retested_dn = False
                elif st.retested_dn and narrow and c < cl:   # ⚠ előbb a kitörés
                    st.broke_dn = st.retested_dn = False
                    return "SELL"
                elif h >= slv - retest_d:
                    st.retested_dn = True
        else:
            st.broke_dn = st.retested_dn = False
        return "NONE"

    def on_bar_close(self, state, md: MarketData):
        """ÉLŐ: M15 záráskor → (state, jel).

        ⚠ KÉT HIBÁT JAVÍT EGYSZERRE (2026-08-25):

        1. **A ZÁRT sort nézzük**, nem a formálódót. Korábban `df.iloc[-1]`
           állt itt, ami a MÉG NYITOTT gyertya — a live tehát megelőzte a
           backtestet, és a jel el is tűnhetett, ha a gyertya visszafordult.
           A backtest hookja (`bt_on_high_close`) zárt sorokat kap.
        2. **Egy gyertya = egy lépés.** A motor ciklusa 10 másodperc; e nélkül
           ugyanaz a sor tucatszor lépett, és a négylépcsős állapotgép percek
           alatt futott végig ott, ahol órák telnének el.

        ⚠ Az indikátorokat is KI KELL SZÁMOLNI: a `_step` `atr`-t és
        szint-oszlopokat olvas, amiket a `bt_indicators` állít elő. A nyers
        `df` sorában ezek nincsenek benne — a `_step` némán `NONE`-t adott
        volna minden hívásra.
        """
        df = (md.bars or {}).get("M15")
        if df is None or len(df) < 3:
            return state, "NONE"
        try:
            m15, _ = self.bt_indicators(df, None, md.params or {})
        except Exception as ex:
            log.debug("%s: CLB jelzés nem számolható: %s", md.symbol, ex)
            return state, "NONE"
        closed = m15.iloc[:-1]                 # az utolsó sor a FORMÁLÓDÓ
        if len(closed) == 0:
            return state, "NONE"

        t = closed.index[-1]
        elozo = getattr(state, "last_bar_time", None)
        if elozo is not None and t == elozo:
            return state, "NONE"               # ezt a gyertyát már feldolgoztuk

        if elozo is None:
            kezd = 0                           # első hívás: teljes visszajátszás
        else:
            # ⚠ TÖBB gyertya is telhetett (hálózati szünet, torlódás).
            try:
                kezd = closed.index.get_loc(elozo) + 1
            except KeyError:
                kezd = 0
        sig = "NONE"
        for i in range(kezd, len(closed)):
            # ⚠ A visszajátszás NEM KÖT: csak az UTOLSÓ zárt gyertya jele mehet
            # ki — a múltbeliek kézbesítési pillanata (az első M1 gyertya) rég
            # elmúlt.
            sig = self._step(state, closed.iloc[i], md.params or {})
        state.last_bar_time = t
        return state, sig

    def bt_on_high_close(self, state, hi_row, params):
        """M15 zárás a backtestben — a DÖNTÉS itt születik."""
        state.fire = self._step(state, hi_row, params)
        return state

    def bt_on_low_close(self, state, prev_lo_row, lo_row, params) -> str:
        """⚠ Az M1 csak KÉZBESÍT: a jelzés után az ELSŐ M1 gyertyán tüzel,
        EGYSZER. Ugyanaz a konzervatív minta, mint a `bollinger_squeeze`-nél —
        nem találunk ki M1-es finomítást egy M15-ön megfogalmazott kitöréshez."""
        sig = getattr(state, "fire", "NONE")
        state.fire = "NONE"
        return sig

    # ── Méretezés ────────────────────────────────────────────────────────
    def sl_tp_points(self, hi_row, params, point_size):
        """SL/TP TÁV PONTBAN. ⚠ A stop a KONSZOLIDÁCIÓS SÁV alja alá kerül, nem
        a szint-gyertya alja alá — a mérés szerint az él a szűk stopból jön."""
        if not point_size:
            return None
        atr, c = hi_row.get("atr"), hi_row.get("close")
        ch, cl = hi_row.get("cons_hi"), hi_row.get("cons_lo")
        for v in (atr, c, ch, cl):
            if v is None or (isinstance(v, float) and math.isnan(v)):
                return None
        buf = float(params.get("stop_buffer_atr", 0.3)) * float(atr)
        sl = (float(c) - (float(cl) - buf)) / float(point_size)
        if sl <= 0:
            return None
        # ⚠ CÉLÁR: elsődlegesen a KÖVETKEZŐ szint (szinttől szintig — a videó
        # példáiban következetesen ez). Ha nincs érvényes következő szint, az
        # `tp_rr_ratio` a tartalék.
        tp = sl * float(params.get("tp_rr_ratio", 2.0))
        nxt = hi_row.get("short_level")      # a fölöttünk lévő swing-csúcs alja
        if nxt is not None and not (isinstance(nxt, float) and math.isnan(nxt)) \
                and float(nxt) > float(c):
            cand = (float(nxt) - float(c)) / float(point_size)
            if cand > 0:
                tp = cand
        return sl, tp

    def bt_entry(self, hi_row, params, point_size):
        """Belépés-kapu + méretezés — a backtest ÉS az él UGYANEZT hívja."""
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

    # ── Megjelenítés ─────────────────────────────────────────────────────
    def compute_display(self, md: MarketData) -> dict:
        """A három stádium-kör: van-e élő szint · volt-e törés · van-e szűk sáv."""
        out = {k: Cell("○", "muted") for k, _ in _STAGES}
        df = (md.bars or {}).get("M15")
        if df is None or len(df) < 20:
            return out
        try:
            m15, _ = self.bt_indicators(df, None, md.params or {})
        except Exception as ex:
            log.debug("%s: CLB kijelzés nem számolható: %s", md.symbol, ex)
            return out
        st = self.new_signal_state(md.symbol)
        for i in range(max(0, len(m15) - 400), len(m15)):
            self._step(st, m15.iloc[i], md.params or {})
        row = m15.iloc[-1]
        lvl = row.get("long_level")
        has_lvl = lvl is not None and not (isinstance(lvl, float) and math.isnan(lvl))
        out["level"] = Cell("●", "green" if has_lvl else "muted")
        out["broken"] = Cell("●", "green" if (st.broke_up or st.broke_dn) else "muted")
        out["cons"] = Cell("●", "green" if (st.retested_up or st.retested_dn)
                           else "muted")
        # ⚠ LAPOS szótár: `{stádium_kulcs: Cell}`. A motor pontosan így bontja
        # szét: `{k: (c.text, c.color) for k, c in cells.items()}` — egy
        # `{"marks": {...}}` burkolótól a `c` szótár lenne, és a `c.text`
        # elszállna. A `marks` az OSZLOP kulcsa (`MarkerColumn`), nem a
        # celláké. Lásd `tests/test_strategy_cell_contract.py`.
        return out

    def live_cells(self, state, md: MarketData) -> dict:
        return self.compute_display(md)

    # ── Optimalizálás ────────────────────────────────────────────────────
    def base_params(self, cfg: dict) -> dict:
        return {**cfg.get("indicators", {}), **cfg.get("sltp", {})}

    def param_space(self, cfg: dict, base_params: dict, method: str,
                    max_trials: int) -> list[dict]:
        from ml.optimizer import generate_grid_params, generate_random_params
        opt_cfg = cfg["optimizer"]
        if method == "grid":
            return generate_grid_params(opt_cfg, base_params, self.constraints_ok)
        return generate_random_params(opt_cfg, base_params, max_trials,
                                      self.constraints_ok)

    _constraints_cache = None

    def _opt_constraints(self) -> list:
        if self._constraints_cache is None:
            from strategy.settings import load_strategy_config
            opt = (load_strategy_config(self.name).get("optimizer", {}) or {})
            self._constraints_cache = list(opt.get("constraints", []))
        return self._constraints_cache

    def constraints_ok(self, params: dict) -> bool:
        from core import param_constraints
        return param_constraints.check(params, self._opt_constraints())

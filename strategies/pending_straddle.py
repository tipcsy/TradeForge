"""
Függő megbízás (straddle) — WPR-triggerelt, kétirányú áttörés-belépő.

A SZABÁLY (a felhasználó specifikációja, 2026-09-07):

  1. TRIGGER   — WPR(14) a JEL-idősíkon (`signal_tf_min`, alap M1). A jel akkor
                 szól, ha az árfolyam egy EXTRÉM zónából indulva áttöri a
                 középső szintet:
                   • a felső extrémből (WPR ≥ −20) LEFELÉ töri a −50-et, VAGY
                   • az alsó extrémből (WPR ≤ −80) FELFELÉ töri a −50-et.
  2. STRADDLE  — a triggerkor KÉT függő megbízás kerül ki a jel-gyertya
                 záróárától ± `straddle_atr_mult` × M1 ATR távolságra (alap;
                 `straddle_mode="spread"` mellett spreadben mérve): egy BUY
                 fölé és egy SELL alá.
  3. OCO       — amelyik elindul, a másik azonnal törlődik.
  4. LEJÁRAT   — ha `straddle_ttl_bars` M1 gyertyán belül egyik sem indul el,
                 mindkettő törlődik (a szetup elévült).

A BETÖLTÉST (a szintek érintését) MINDIG az M1 figyeli, a jel-idősíktól
függetlenül — lásd az `ALLOWED_TF_MIN` melletti megjegyzést.

⚠ A WPR ITT NEM IRÁNYT AD, HANEM IDŐZÍTÉST. A −50 áttörése azt mondja, hogy
„most mozdul" — hogy MERRE, azt a straddle dönti el. Ez szándékos: a projekt
korábbi mérése (`timing-not-entry-signal`, `indicator-list-screened`) szerint az
indikátorok az IRÁNYRÓL nem mondanak semmit, a volatilitásról viszont igen.

────────────────────────────────────────────────────────────────────────────
⚠⚠ AMIT EZ A MODUL NEM TUD — OLVASD EL, MIELŐTT AZ EREDMÉNYT ÉRTELMEZED

A TradeForge-ban **nincs függő megbízás**. A `core.mt5_connector` kizárólag
`TRADE_ACTION_DEAL`-t (piaci kötés) küld, a backtest pedig fixen az M1 gyertya
ZÁRÁSÁN nyit (`trading/backtest.py`: `open_price = _bar_c`). Sem BUY_STOP, sem
OCO, sem lejárat nincs a keretben.

Ez a modul ezért **VIRTUÁLIS straddle**: a két szintet a stratégia tartja
nyilván, és amelyiket az M1 gyertya ELŐSZÖR megérinti, arra ad jelet — a
tényleges belépő viszont az adott M1 gyertya ZÁRÁSÁN történik, nem a szinten.

  • ELŐNY: a live és a backtest UGYANAZT csinálja (paritás — 15 000 M1 gyertyán
    498 vs 498 jel, nulla eltérés), tehát a mérés hű ahhoz, amit a motor
    ténylegesen kötne.
  • HÁTRÁNY: a betöltési ár nem a függő szint, hanem az M1 zárás.

⚠ ÉS EZT MEGMÉRTÜK (2026-09-07, 6 pár, 19 371 betöltés). A szinten való
betöltés előnye az M1 záráshoz képest ÁTLAGBAN NULLA:

    Ger40 −0,009 · UsaTec −0,032 · GOLD +0,015 · EURUSD −0,018 ·
    UsaInd −0,005 · UK100 +0,020   (átlagos előny R-ben; medián ~0,
    az esetek 38–54%-ában pozitív)

Vagyis az M1 zárás a függő szint TORZÍTATLAN közelítése — a szórása nagyobb, a
várható értéke viszont ugyanaz. Ez pontosan az, amit egy hatékony piactól várni
lehet (`market-became-efficient`). KÖVETKEZMÉNY: a valódi függő megbízás
keret-szintű megépítése ezt az eredményt NEM fordítaná meg; a mostani szám tehát
nem „ideiglenes", hanem az ítélet.

A `max_chase_spread` a modellezési rést hivatott korlátozni (ha az M1 zárás
ennyi spreadnél messzebb van a szinttől, a belépő kimarad) — a fenti mérés után
viszont alapból KI van kapcsolva (0): nem vesz meg hitelességet, viszont a
betöltések 3–44%-át eldobná.
────────────────────────────────────────────────────────────────────────────

⚠ A LÉPTÉK: M1 ATR (alap) VAGY SPREAD. `straddle_mode` / `sl_mode`.

Az ELSŐ változat mindkettőt spreadben mérte. Az M1-es mechanika-mérés
(2026-09-07) megmutatta, miért rossz ez: a 6 spreades SL a belépéskori M15 ATR
26–29%-a volt, egy MEDIÁN M1 gyertya range-e pedig 1,0–5,1 spread — UsaTec-en
tehát egyetlen átlagos perces gyertya lefedte a TELJES kockázatot. Mérve, 12 737
kötésen: a kötések 10,8%-a EGYETLEN M1 gyertyán belül stoppolt.

ATR-léptékre átállítva (szintek 1,0 × M1 ATR, stop 5,0 × M1 ATR) ez a
zaj-kiütés ELTŰNT: 10,8% → 0,5%. A `sl_mode="atr_m1"` ezért az alap — a stopot
EGYÜTT kell mozgatni a szintekkel, különben még mélyebben ülne a zajban.

A spread-léptékű változat megmaradt (`straddle_mode="spread"` +
`sl_mode="straddle"`), mert a korábbi mérések csak azzal reprodukálhatók.
A spread ilyenkor a gyertya SAJÁT oszlopából jön (`close_spread`/`avg_spread` a
parquetből, `spread` az MT5-ből — mindhárom ÁRban); ha nincs, nem jelez.

⚠ AMI NEM EZÉ A MODULÉ. A „mozgassuk az SL-t BE+spreadre" a KOCKÁZATCSÖKKENTŐ
modulé (`core/risk_reduction.py` + `core/rr_state.py`), nem a stratégiáé — lásd
`strategy/base.py`. Ott már költség-tudatos a breakeven (a puffernek a
jutalékot+swapot is fedeznie kell). A méretezés a `core/risk_manager.py`-é.

⚠ MIN_LOT FIGYELMEZTETÉS. Szűk stop mellett a `calc_lot` NAGY lotot ad. A
`min_lot`/`max_lot` és a súlyozott slot-keret ezt kezeli, de a belépés költsége
(1 spread) egy szűk stopnál az R nagy hányada — a `wpr-m1-only-sub-spread-edge`
lelet szerint ez önmagában megeszi az élt. Ezért az `sl_atr_m1_mult` tartománya
TÁG (0,5…8 × M1 ATR), és ez az ELSŐ mérendő paraméter.

────────────────────────────────────────────────────────────────────────────
⚠⚠ AZ ELSŐ MÉRÉS ÍTÉLETE (2026-09-07, ALAP paraméterek, 6 pár, ~2,5 hónap)

  • Mind a hat pár VESZTESÉGES: átlag R −0,12 … −0,26.
  • Az `sl_spread_mult` végigsöprése megmutatja, hogy az eredmény GYAKORLATILAG
    AZONOS a költséggel: a mért átlag R végig a `−1/sl_spread_mult` görbén ül
    (Ger40/UsaTec maradék ±0,03 R-en belül, EURUSD tartósan alatta).
  • KILL-TESZT: a WPR-triggert VÉLETLEN időzítésre cserélve (minden 30. M1
    gyertyán straddle, minden más változatlan) a három párból KETTŐN JOBB lett
    az eredmény. A −20/−80 → −50 áttörés tehát a belépés időzítéséhez nem ad
    mérhető információt.

  • AZ IDŐSÍK NEM SEGÍT (2026-09-07, `signal_tf_min` 1 / 5 / 15): a kötésszám
    a várt arányban esik (12 737 / 3 239 / 1 125), a KÖTÉSENKÉNTI eredmény
    viszont gyakorlatilag azonos — átlag R −0,167 / −0,160 / −0,170. M5-ön a
    KILL-TESZTET is elbukja, méghozzá HÁROM PÁRBÓL HÁRMON.

Vagyis a veszteség nem az idősík rossz megválasztása: a kötésenkénti várható
érték minden idősíkon a költség.

  • AZ ATR-LÉPTÉK SEM SEGÍT. A zaj-problémát megoldja (1-gyertyás stop 10,8% →
    0,5%), de a 2D söprés (szint 0,5/1/2 × ATR × stop 1/2/3/5/8 × ATR) MINDEN
    cellája a `−költség` görbén ül, ugyanúgy, mint a spread-léptéknél.

  • ÉS A DÖNTŐ MÉRÉS: ugyanazon az ATR-léptéken a WPR-trigger és a VÉLETLEN
    időzítés mechanikája AZONOS — az „eredeti stopon hal meg" arány 58,2% vs
    58,2% (tizedesre), a TP-arány 10,7% vs 11,7%, az átlag R −0,1125 vs
    −0,1040. A visszapattanás tehát NEM a belépőjel hibája: ennyi jön ki
    bármilyen belépőből. A jel nulla információt hordoz.

A részletes táblák: `strategies/docs/pending_straddle.md`. A modul azért marad
a repóban, mert a mérés MEGISMÉTELHETŐ kell legyen — nem azért, mert működik.
────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
import pandas as pd

from core.i18n import t as _t
from core.indicator_engine import (atr as _atr_ind, resample_ohlc as _resample,
                                   wpr as _wpr_ind)
from core.risk_manager import calc_sl_tp_points
from core import gate_bands as _gbands
from gates import spread_gate
from gates import vol_baseline as _volb
from strategy import visual as viz
from strategy.base import (Cell, Column, MarkerColumn, MarketData, Strategy,
                           Timeframe)

log = logging.getLogger(__name__)

MAGIC_OFFSET = 4          # 0=wpr_sma, 1=ml_ai, 2=bollinger, 3=trend_pullback,
                          # 30=candle_level_break

# A spread-oszlop jelöltjei, PREFERENCIA-SORRENDBEN. Mindhárom ÁRban van:
#   close_spread — a bar UTOLSÓ tickjének spreadje (parquet); ez a legpontosabb
#                  a ZÁRÁSKOR számolt szintekhez,
#   avg_spread   — a bar átlaga (parquet),
#   spread       — az MT5 `copy_rates` pont-spreadje, amit a
#                  `live_trader.get_candles` már ÁRRA váltott (× symbol_info.point).
_SPREAD_COLS = ("close_spread", "avg_spread", "spread")

# ── A JEL-IDŐSÍK (`signal_tf_min`) ─────────────────────────────────────────
# Melyik gyertyán számoljuk a WPR-t és hozzuk a TRIGGER-döntést. A BETÖLTÉST
# (a függő szintek érintését) MINDIG az M1 figyeli — ez szándékos: egy valódi
# stop-megbízás intrabar töltődne be, tehát minél finomabb a figyelés, annál
# hűbb a modell. A jel-idősík durvítása CSAK a döntést lassítja, a végrehajtás
# felbontását nem rontja.
#
# ⚠ MIÉRT PARAMÉTER, ÉS NEM KÜLÖN MODUL. Az „idősík-váltás = új stratégia"
# szabály (lásd `candle_level_break`) ott érvényes, ahol a váltás átírja a
# szabályt. Itt nem: ugyanaz a WPR, ugyanaz a straddle, ugyanaz az állapotgép —
# csak a gyertya hossza más. Két modulból viszont KÉT kód lenne, ami külön
# romlana el, és az M1↔M5 összehasonlítás sem lenne hiteles (nem ugyanazt
# mérnénk). Ugyanez a minta az `ml_ai`-ban és a `bollinger_squeeze`-ben is.
#
# ⚠ NEM OPTIMALIZÁLJUK. Az idősík szerkezeti döntés: ha az optimalizáló
# hangolná, minden trial MÁS stratégiát mérne, és a „legjobb" idősík a keresési
# zaj függvénye lenne.
ALLOWED_TF_MIN = (1, 5, 15, 30, 60)
DEFAULT_TF_MIN = 5

_CIRCLE = "●"
_STAGES = (("zone",  _t("stage.zone")),
           ("armed", _t("stage.armed")),
           ("fill",  _t("stage.fill")))
_MARKS_EMPTY = {k: Cell(_CIRCLE, "muted") for k, _ in _STAGES}

# Hány szetup függő-szintjeit rajzolja ki a viz (a legutóbbiakat). Korlát nélkül
# egy két hetes M1 ablakon több ezer vonalpár kerülne a chartra.
_VIZ_MAX_SETUPS = 150


# ---------------------------------------------------------------------------
# Spread-sorozat — a straddle LÉPTÉKE
# ---------------------------------------------------------------------------

def _spread_series(df) -> Optional[pd.Series]:
    """A gyertyánkénti spread ÁRBAN, vagy `None`, ha az adat nem tartalmazza.

    ⚠ CSAK `ffill`, `bfill` NINCS. A visszatöltés a MÚLTBA vinne jövőbeli
    spread-értéket — a sorozat elején inkább NaN marad, és ott a stratégia nem
    jelez (ez amúgy is a warmup szakasz). A nem-pozitív értékek (0 = „nincs
    adat" a natív oldalon) hiánynak számítanak."""
    if df is None or len(df) == 0:
        return None
    col = next((c for c in _SPREAD_COLS if c in df.columns), None)
    if col is None:
        return None
    s = pd.to_numeric(df[col], errors="coerce")
    s = s.where(s > 0).ffill()
    return s if bool(s.notna().any()) else None


def _tf(params: dict) -> int:
    """A jel-idősík percben, a paraméterekből. Érvénytelen érték → alap + napló
    (némán visszaesni pont az a hiba-osztály, amit a projekt irt)."""
    raw = (params or {}).get("signal_tf_min")
    if raw is None:
        return DEFAULT_TF_MIN
    try:
        v = int(raw)
    except (TypeError, ValueError):
        v = None
    if v in ALLOWED_TF_MIN:
        return v
    log.warning("pending_straddle — signal_tf_min=%r nem megengedett (%s) → M%d",
                raw, ALLOWED_TF_MIN, DEFAULT_TF_MIN)
    return DEFAULT_TF_MIN


def _signal_columns(lo, params: dict):
    """`(sig_new, sig_wpr, sig_close)` az M1 indexen — a JEL-idősík döntése,
    minden M1 sorra levetítve.

    `sig_new` = 1, ha ezen az M1 gyertyán ZÁRT le egy ÚJ jel-gyertya (tehát most
    születhet trigger); `sig_wpr`/`sig_close` a most lezárt jel-gyertya WPR-je és
    záróára.

    ⚠ NINCS JÖVŐ-SZIVÁRGÁS. Egy jel-gyertya a NYITÓ idejével azonosított
    (`resample_ohlc`: bal-zárt, bal-címkés, mint az MT5), és `tf` perc múlva ZÁR.
    Az M1 gyertya `i` a SAJÁT zárásakor dönt, vagyis `t_i + 60 mp`-kor — így csak
    azt a jel-gyertyát láthatja, amelyik addigra LEZÁRT. A hozzárendelés ezért
    `searchsorted` a jel-gyertyák ZÁRÁSI időpontjain, nem a nyitókon. (A projekt
    két legdrágább hibája — az M15 look-ahead és a `regime`-címke — pontosan ezen
    a különbségen múlt.)"""
    n = len(lo)
    per = int(params.get("wpr_period", 14) or 14)
    tf = _tf(params)
    if tf <= 1:
        return (np.ones(n),
                _wpr_ind(lo["high"], lo["low"], lo["close"], per).to_numpy(float),
                lo["close"].to_numpy(dtype=float))

    sg = _resample(lo, tf)
    if sg is None or len(sg) < 2:
        return np.zeros(n), np.full(n, np.nan), np.full(n, np.nan)
    w = _wpr_ind(sg["high"], sg["low"], sg["close"], per).to_numpy(dtype=float)
    c = sg["close"].to_numpy(dtype=float)

    close_ns = (sg.index + pd.Timedelta(minutes=tf)).asi8      # AMIKOR lezár
    dec_ns   = (lo.index + pd.Timedelta(minutes=1)).asi8       # az M1 döntése
    idx = np.searchsorted(close_ns, dec_ns, side="right") - 1
    ok  = idx >= 0
    safe = np.clip(idx, 0, len(sg) - 1)

    new = np.zeros(n)
    if n:
        new[0] = 1.0 if ok[0] else 0.0     # az első sor csak „magot vet" (nincs prev)
        new[1:] = ((idx[1:] != idx[:-1]) & ok[1:]).astype(float)
    return (new,
            np.where(ok, w[safe], np.nan),
            np.where(ok, c[safe], np.nan))


_SIG_COLS_WARNED: list = []


def _warn_missing_sig_cols() -> None:
    """Egyszeri, HANGOS jelzés, ha a jel-oszlopok hiányoznak a sorból."""
    if _SIG_COLS_WARNED:
        return
    _SIG_COLS_WARNED.append(1)
    log.warning("pending_straddle: a kapott gyertya-sorban NINCS `sig_new` "
                "oszlop — a hívó nem a `bt_indicators` kimenetéből dolgozik. A "
                "stratégia így SOHA nem jelezne; a jel most kimarad.")


_NO_SPREAD_WARNED: set = set()


def _warn_no_spread(where: str) -> None:
    """⚠ NEM NÉMA. Spread-oszlop nélkül ez a stratégia SOSEM jelez — ami
    ránézésre pontosan olyan, mint egy nyugodt piac. A projekt legdrágább
    hibaosztálya (`silent-thread-death`, `viz-band-multi-strategy-corruption`)
    pont ez: a hiányzó bemenet csendben nullát ad. Ezért egyszer szólunk."""
    if where in _NO_SPREAD_WARNED:
        return
    _NO_SPREAD_WARNED.add(where)
    log.warning("pending_straddle (%s): a gyertyákon NINCS spread-oszlop "
                "(%s) — a straddle léptéke ismeretlen, a stratégia nem ad "
                "jelet. Töltsd újra az előzményt (tools/download_history).",
                where, "/".join(_SPREAD_COLS))


# ---------------------------------------------------------------------------
# Jelzésállapot — EGY osztály az élő motornak ÉS a backtestnek
# ---------------------------------------------------------------------------

@dataclass
class StraddleState:
    """A pár jelzésállapota.

    `zone`   — a WPR járt-e azóta extrémben: "" | "high" (≥ sell_extreme) |
               "low" (≤ buy_extreme). EZ a felfegyverzés: a −50 áttörése csak
               akkor trigger, ha előtte extrémben jártunk. Az áttörés UTÁN
               nullázódik → egy szetuphoz egy straddle.
    `armed`  — kint van-e a függő pár.
    `unit`   — EGY spread ÁRBAN, a straddle kihelyezésekor (a `max_chase_spread`
               ehhez mér). Azért tároljuk, mert a betöltés egy KÉSŐBBI gyertyán
               történik, ahol a spread már más lehet.
    `setup_id` — a kihelyezések sorszáma. A rajz ebből tudja, hogy egy gyertyán
               belüli betöltés+újrafegyverzés KÉT szetup, nem egy hosszú.

    ⚠ A „nincs szint" jelölése `None`, NEM `float("nan")`. A NaN önmagával sem
    egyenlő, tehát az állapot-pillanatképek összehasonlítása (a motor
    idempotencia-őre, `tests/test_on_bar_close_idempotent.py`) egy ÉRINTETLEN
    állapotot is VÁLTOZOTTNAK látna. Egy ilyen hamis riasztás pontosan azt a
    tesztet tenné használhatatlanná, ami a kétszer-lépést kiszűri.
    """
    symbol:       str
    prev_wpr:     Optional[float] = None
    zone:         str = ""
    armed:        bool = False
    buy_level:    Optional[float] = None
    sell_level:   Optional[float] = None
    unit:         Optional[float] = None
    ttl:          int = 0
    setup_id:     int = 0
    last_signal:  str = "NONE"     # a KIJELZÉSHEZ (egy M1 gyertyás esemény)
    # Csak az ÉLŐ út bemelegítéséhez: melyik M1 gyertyáig dolgoztuk fel az
    # előzményt (None = még nem volt bemelegítés).
    last_m1_time: Any = None


def _step(st: StraddleState, o: float, h: float, l: float, c: float,
          off: float, p: dict, sig_new: float, sig_wpr: float,
          sig_close: float) -> str:
    """EGY zárt M1 gyertya feldolgozása. Visszaad: "BUY" | "SELL" | "NONE".

    ⚠ EZ AZ EGYETLEN FORRÁS. A backtest (`bt_on_low_close`), az élő motor
    (`on_bar_close`), a kijelzés (`compute_display`) és a chart-rajz
    (`visual_objects`) MIND ezt hívja. A projektben minden néma eltérés abból
    lett, hogy ugyanaz a szabály két helyen élt.

    KÉT IDŐSÍK, KÉT SZEREP:
      • BETÖLTÉS  — MINDEN M1 gyertyán fut, az M1 `h`/`l`-jével. Egy valódi
        stop-megbízás intrabar töltődne be, tehát a legfinomabb elérhető
        felbontással figyelünk. A jel-idősík durvítása ezt NEM rontja.
      • TRIGGER   — csak akkor, ha `sig_new` (most zárt le egy jel-gyertya), a
        jel-gyertya `sig_wpr`/`sig_close` értékeivel. `signal_tf_min=1` esetén
        minden M1 gyertya jel-gyertya, tehát a régi viselkedés áll vissza.

    `off` = a straddle fél-szélessége ÁRBAN (az M1 spreadjéből: a megbízást MOST
    tesszük ki, tehát a legfrissebb spread a helyes lépték).
    """
    st.last_signal = "NONE"          # egy M1 gyertyás esemény, nem latch-elünk
    sig = "NONE"

    # ── 1. BETÖLTÉS: a MÁR kint lévő függő pár ellenőrzése ─────────────────
    # ⚠ A SORREND KÖTÖTT: a betöltés a KIHELYEZÉS ELŐTT. A straddle a trigger-
    # gyertya ZÁRÓÁRÁRA kerül ki, tehát azon a gyertyán még nem töltődhet be.
    if st.armed:
        hit_buy  = h >= st.buy_level
        hit_sell = l <= st.sell_level
        if hit_buy and hit_sell:
            # [DÖNTÉS] Egy gyertyán belül mindkét szint sérült — hogy MELYIK
            # jött előbb, az OHLC-ből nem derül ki (ahhoz tick kellene). A
            # PESSZIMISTA utat vesszük, ugyanazzal a konvencióval, mint a motor
            # intrabar SL/TP-sorrendje: emelkedő gyertyánál (close ≥ open) az
            # utat az ALJÁRÓL indítjuk → a SELL töltődött be, és utána ELLENE
            # ment a piac. Ez a whipsaw — nem szépítjük el.
            sig = "SELL" if c >= o else "BUY"
        elif hit_buy:
            sig = "BUY"
        elif hit_sell:
            sig = "SELL"

        if sig != "NONE":
            # OCO: a párja törlődik — a szetupnak akkor is vége, ha a
            # „chase"-korlát végül eldobja a belépőt.
            level = st.buy_level if sig == "BUY" else st.sell_level
            chase = float(p.get("max_chase_spread", 0) or 0)
            unit  = st.unit
            st.armed, st.ttl = False, 0
            if (chase > 0 and unit is not None and unit > 0
                    and abs(c - level) > chase * unit):
                # A piaci pótlás túl messze a függő szinttől → a modellezett és
                # a valós kötés érdemben MÁS lenne. Inkább kihagyjuk.
                sig = "NONE"
        else:
            st.ttl -= 1
            if st.ttl <= 0:
                st.armed = False          # lejárat: mindkét függő törlődik

    # ── 2. ZÓNA + TRIGGER: a WPR állapotgépe a JEL-gyertyán ────────────────
    # ⚠ CSAK ÚJ jel-gyertyánál. Ha minden M1 gyertyán léptetnénk, a `prev_wpr`
    # ugyanannak a jel-gyertyának a saját értéke lenne (prev == cur), és a −50
    # keresztezését SOHA nem látnánk meg — a stratégia némán elnémulna M1
    # fölötti idősíkon.
    if not sig_new:
        if sig != "NONE":
            st.last_signal = sig
        return sig

    wpr = sig_wpr
    prev, st.prev_wpr = st.prev_wpr, wpr
    if wpr is None or math.isnan(wpr):
        st.prev_wpr = None
        if sig != "NONE":
            st.last_signal = sig
        return sig

    sell_x = float(p.get("wpr_sell_extreme", -20))
    buy_x  = float(p.get("wpr_buy_extreme",  -80))
    sell_t = float(p.get("wpr_sell_trigger", -50))
    buy_t  = float(p.get("wpr_buy_trigger",  -50))

    if wpr >= sell_x:
        st.zone = "high"
    elif wpr <= buy_x:
        st.zone = "low"

    # A straddle a JEL-gyertya záróárára kerül ki (ott hozza a döntést a
    # kereskedő). Ez rendes adatnál megegyezik az aktuális M1 zárással — de
    # gyertya-hiánynál (hétvége, kimaradás) nem, és ilyenkor a jel-gyertya
    # zárása a helyes.
    base_c = sig_close if (sig_close is not None
                           and not math.isnan(sig_close)) else c
    if (not st.armed and prev is not None and not math.isnan(prev)
            and off and off > 0 and not math.isnan(off)):
        # ⚠ FELFEGYVEREZ → TÜZEL, nem „szomszédos gyertya". A `zone` a
        # felfegyverzés (bármikor a múltban járhattunk az extrémben), a −50
        # keresztezése a tüzelés. Az `m1-entry-state-machine` lelet szerint a
        # szomszédos-gyertyás minta a fokozatos átütést kihagyja.
        fire = ((st.zone == "high" and prev > sell_t and wpr <= sell_t) or
                (st.zone == "low"  and prev < buy_t  and wpr >= buy_t))
        if fire:
            st.armed      = True
            st.buy_level  = base_c + off
            st.sell_level = base_c - off
            st.unit       = off / max(float(p.get("straddle_spread_mult", 2.0)), 1e-9)
            st.ttl        = max(1, int(p.get("straddle_ttl_bars", 15) or 15))
            st.setup_id  += 1
            st.zone       = ""        # egy szetuphoz egy straddle

    if sig != "NONE":
        st.last_signal = sig
    return sig


def _cells(st: StraddleState) -> dict:
    """A három kör az ÁLLAPOTBÓL — ugyanaz a kijelzés az élő és a rekonstruált
    úton (nincs két képlet).

    ⚠ LAPOS szótár, `{stádium: Cell}` — NEM `{"marks": {...}}`. Két korábbi
    stratégia dőlt be ennek (`tests/test_strategy_cell_contract.py`)."""
    return {
        "zone":  Cell(_CIRCLE, "yellow" if st.zone else "muted"),
        "armed": Cell(_CIRCLE, "cyan" if st.armed else "muted"),
        "fill":  Cell(_CIRCLE,
                      "green" if st.last_signal == "BUY" else
                      "red" if st.last_signal == "SELL" else "muted"),
    }


class PendingStraddleStrategy(Strategy):
    """WPR-triggerelt, kétirányú (straddle) áttörés-belépő."""

    name = "pending_straddle"
    short = "Straddle"
    display_name = "Függő megbízás (WPR straddle)"

    # A stratégia SAJÁT SL-t ad (spread- vagy ATR-léptékűt) → a keret NE írja
    # felül a swing20-szal. Az ml_ai-nál pont ez a felülírás okozta, hogy a
    # végrehajtott kötés más volt, mint amire a jel vonatkozott.
    default_sl_method = "atr"

    # ── Váz ───────────────────────────────────────────────────────────────

    def timeframes(self) -> list[Timeframe]:
        # ⚠ A DÖNTÉS TELJESEN M1-EN VAN (trigger + straddle + betöltés). Az M15
        # csak azért kell, mert a keret adat-csővezetéke két idősíkot tölt, és a
        # `sl_tp_points`/kapuk a MAGASABB tf sorát kapják (ATR, spread-mérce).
        return [Timeframe("M15", 15), Timeframe("M1", 1)]

    def columns(self) -> list[Column]:
        return [MarkerColumn("marks", self.name, stages=_STAGES)]

    def magic(self, cfg: dict) -> int:
        """EGYEDI magic — hogy a nyitott pozíciók broker-szinten is
        szétválaszthatók legyenek a többi stratégiától."""
        base = int(((cfg or {}).get("broker") or {}).get("magic", 0) or 0)
        return base + MAGIC_OFFSET

    def warmup_bars(self, params: dict, timeframe_label: str) -> int:
        if timeframe_label == "M15":
            return int(params.get("atr_period", 14) or 14) + 5
        if timeframe_label == "M1":
            # A WPR a JEL-gyertyán számol → annyiszor több M1 sor kell; az M1
            # ATR (a straddle léptéke) viszont M1 gyertyákat kér.
            return max(int(params.get("wpr_period", 14) or 14) * _tf(params),
                       int(params.get("straddle_atr_period", 14) or 14)) + 5
        return 50

    def signal_warmup_bars(self, params: dict, timeframe_label: str) -> int:
        """A `zone` (extrém-emlék) TETSZŐLEGESEN régi lehet: ha a WPR régen járt
        utoljára −20 fölött, a mai −50-es áttörés MÉGIS trigger. Sekély
        warmuppal a motor ezt „nem látná", a viz viszont igen — pontosan az
        `m15-warmup-depth-divergence` lelet. Ezért M1-en EGY NAPOT (1440
        gyertya) játszunk vissza a warmup FELETT; egy nap alatt a WPR(14) M5-ön
        is sokszor megjárja mindkét extrémet, tehát az állapot konvergál."""
        if timeframe_label == "M1":
            return self.warmup_bars(params, "M1") + 1440
        return self.warmup_bars(params, timeframe_label)

    def signal_bar_seconds(self, params: dict) -> int:
        """A DÖNTÉSI gyertya hossza másodpercben.

        ⚠ MIÉRT NEM MINDIG 0. A „csak jelzés" mód riasztásai alert-ID alapján
        dedupálnak, és az ID a gyertyaidőből képződik. Ha az M1-ét használnánk
        egy M5-ös döntéshez, EGY szetupból ÖT riasztás lenne, percenként egy —
        pontosan az, ami a `bollinger_squeeze`-nél élesben meg is történt (18:00,
        18:01, … ugyanaz a GOLD BUY). `signal_tf_min=1` → 0 (ott a végrehajtási
        idősík dönt, ami ugyanaz)."""
        tf = _tf(params)
        return tf * 60 if tf > 1 else 0

    # ── Indikátorok ───────────────────────────────────────────────────────

    def bt_indicators(self, df_hi, df_lo, params):
        """`(hi, lo)` a stratégia SAJÁT oszlopaival.

        hi: `atr` (az `sl_mode="atr"`-hez), `atr_avg` (a VOLATILITÁS-KAPU
            mércéje — a motor nem ismer 'atr'-t, a kapu ebből mér),
            `spread_ref` (a spread-léptékű SL-hez, ÁRban).
        lo: `straddle_off` (a straddle fél-szélessége ÁRban) + a JEL-idősík
            levetítve az M1 sorokra: `sig_new`, `sig_wpr`, `sig_close`.
        """
        hi = df_hi.copy()
        lo = df_lo.copy()

        per_atr = int(params.get("atr_period", 14) or 14)
        hi["atr"] = _atr_ind(hi["high"], hi["low"], hi["close"], per_atr)
        # A volatilitás-kapu mércéje — a KÖZÖS `gates.vol_baseline`-ből (fix
        # `atr_avg_ref` vagy gördülő ablak), hogy a backtest, a viz és az él
        # ugyanazt számolja (`frozen-volatility-baseline`).
        hi["atr_avg"] = _volb.series(hi["atr"], params)

        # A JEL-idősík (M1 → M5/M15/…) levetítve, look-ahead nélkül.
        sig_new, sig_wpr, sig_close = _signal_columns(lo, params)
        lo["sig_new"], lo["sig_wpr"], lo["sig_close"] = sig_new, sig_wpr, sig_close
        # `wpr`: a JEL-gyertyáé (ez megy a chartra és a naplóba is) — nem az
        # M1-é, hogy a rajz és a döntés ugyanazt a számot mutassa.
        lo["wpr"] = sig_wpr

        # ── A straddle LÉPTÉKE: spread VAGY M1 ATR ─────────────────────────
        # ⚠ MIÉRT KELL AZ ATR-VÁLTOZAT (mérve 2026-09-07). Spread-léptékű
        # szintekkel a stop a piaci ZAJON BELÜL ült: a 6 spreades SL a
        # belépéskori M15 ATR 26–29%-a volt, és egy MEDIÁN M1 gyertya range-e
        # 1,0–5,1 spread — UsaTec-en tehát egyetlen átlagos perces gyertya
        # lefedte a teljes kockázatot. Következmény: a kötések 61%-a az EREDETI
        # stopon halt meg, mielőtt a stop egyáltalán megmozdult volna. Az ATR a
        # tényleges mozgástérhez köti a szinteket, nem a bróker árréséhez.
        lo["atr_m1"] = _atr_ind(lo["high"], lo["low"], lo["close"],
                                int(params.get("straddle_atr_period", 14) or 14))
        mode = str(params.get("straddle_mode", "atr"))
        if mode == "atr":
            lo["straddle_off"] = lo["atr_m1"] * float(
                params.get("straddle_atr_mult", 1.0) or 1.0)
            sp_lo = _spread_series(lo)      # az SL spread-módjához kellhet
        else:
            k = float(params.get("straddle_spread_mult", 2.0) or 2.0)
            sp_lo = _spread_series(lo)
            if sp_lo is None:
                _warn_no_spread("M1")
                lo["straddle_off"] = np.nan
            else:
                lo["straddle_off"] = sp_lo * k

        # Az M1 ATR levetítve a magasabb tf sorára — a `sl_tp_points` csak azt
        # kapja meg. MÚLTBÓL előre (`ffill`), hogy ne legyen jövő-szivárgás.
        hi["atr_m1_ref"] = lo["atr_m1"].reindex(hi.index, method="ffill")

        sp_hi = _spread_series(hi)
        if sp_hi is None and sp_lo is not None:
            # Az M15-ön nincs spread-oszlop (pl. parquetből épített ablak) → az
            # M1 spreadjét vetítjük rá, MÚLTBÓL előre (`ffill`), hogy ne
            # kerüljön jövőbeli érték a döntési sorba.
            sp_hi = sp_lo.reindex(hi.index, method="ffill")
        if sp_hi is None:
            # ⚠ CSAK akkor szólunk, ha a spread TÉNYLEG kell. ATR-léptékű
            # szintek + `atr_m1` stop mellett a stratégia spread-független —
            # egy ilyenkor kiírt riasztás vaklárma lenne, és a vaklárma pont
            # annyira káros, mint a néma hiba: elszoktat a napló olvasásától.
            if str(params.get("sl_mode", "atr_m1")) == "straddle":
                _warn_no_spread("M15")
            hi["spread_ref"] = np.nan
        else:
            hi["spread_ref"] = sp_hi
        return hi, lo

    def bt_warmup(self, params: dict, timeframe_label: str) -> int:
        if timeframe_label == "M15":
            return int(params.get("atr_period", 14) or 14)
        return max(int(params.get("wpr_period", 14) or 14) * _tf(params),
                   int(params.get("straddle_atr_period", 14) or 14))

    # ── Jelzés: backtest-hookok ───────────────────────────────────────────

    def bt_new_state(self, symbol: str) -> StraddleState:
        return StraddleState(symbol)

    def bt_on_high_close(self, state, hi_row, params):
        """A magasabb tf nem hoz döntést — a teljes állapotgép M1-en fut."""
        return state

    def bt_on_low_close(self, state, prev_lo_row, lo_row, params) -> str:
        if lo_row is None:
            return "NONE"
        # ⚠ NEM NÉMA. A `sig_*` oszlopokat a `bt_indicators` állítja elő. Ha egy
        # hívó (kutató-harness, gyorsítótár, kézzel épített sor) régi
        # oszlopkészletet ad, a `_f(None)` NaN lesz, a `sig_new` hamis, és a
        # stratégia SOHA nem jelez — ami ránézésre nyugodt piac. Ez pontosan a
        # projekt legdrágább hibaosztálya (`silent-thread-death`), és a fejlesztés
        # közben MEG IS TÖRTÉNT egy mérő-szkripttel: 0 jel, nulla magyarázat.
        if lo_row.get("sig_new") is None:
            _warn_missing_sig_cols()
            return "NONE"
        return _step(state, _f(lo_row.get("open")), _f(lo_row.get("high")),
                     _f(lo_row.get("low")), _f(lo_row.get("close")),
                     _f(lo_row.get("straddle_off")), params,
                     _f(lo_row.get("sig_new")), _f(lo_row.get("sig_wpr")),
                     _f(lo_row.get("sig_close")))

    # ── Jelzés: élő motor ─────────────────────────────────────────────────

    def new_signal_state(self, symbol: str) -> StraddleState:
        return StraddleState(symbol)

    def on_bar_close(self, state: StraddleState, md: MarketData):
        """ZÁRT M1 gyertyán léptet. Az ELSŐ hívás BEMELEGÍT: végigjátssza a
        kapott (mély) M1 ablakot, hogy az állapot azonnal megegyezzen a vizzel
        és a backtesttel — különben egy folyamatban lévő straddle-t a motor „nem
        látna", és a betöltés kimaradna."""
        df_hi = md.bars.get("M15")
        df_lo = md.bars.get("M1")
        if df_lo is None or len(df_lo) < 3:
            return state, "NONE"
        if df_hi is None or len(df_hi) < 2:
            df_hi = df_lo          # az M15 csak a méretezéshez kell, itt nem
        try:
            _, m1 = self.bt_indicators(df_hi, df_lo, md.params)
        except Exception as ex:
            log.warning("%s: pending_straddle indikátor-hiba (%s) — nincs jel.",
                        md.symbol, ex)
            return state, "NONE"

        cols = _arrays(m1)
        m1_time = m1.index[-2]          # az AKTUÁLIS zárt gyertya

        if state.last_m1_time is None:
            # BEMELEGÍTÉS: a teljes zárt előzmény (az utolsó sor formálódik).
            for i in range(len(m1) - 1):
                _step_at(state, cols, i, md.params)
            state.last_m1_time = m1_time
            signal = state.last_signal
        elif state.last_m1_time != m1_time:
            # ⚠ MINDEN kimaradt gyertyát léptetünk, nem csak a legutolsót. A
            # motor köre 10 mp, tehát rendes esetben egyetlen új gyertya van —
            # de ha a pár szünetelt (optimalizálás, MT5-kimaradás, elakadt kör),
            # több is összegyűlhet. A `_step` a MEGELŐZŐ gyertya WPR-jéből dönti
            # el az áttörést, tehát egy átugrott gyertya nem „késleltetne",
            # hanem NÉMÁN ELNYELNE egy triggert. (Ugyanez az osztály, mint a
            # `silent-thread-death`: a hiány pontosan úgy néz ki, mint a
            # nyugalom.) A `searchsorted` a monoton időindexen olcsó.
            start = int(m1.index.searchsorted(state.last_m1_time, side="right"))
            state.last_m1_time = m1_time
            signal = "NONE"
            for i in range(max(start, 0), len(m1) - 1):
                sig = _step_at(state, cols, i, md.params)
                if sig != "NONE":
                    signal = sig     # az UTOLSÓ jel megy ki (a régebbi elévült)
        else:
            signal = "NONE"          # ugyanaz a gyertya — nem lépünk kétszer

        if signal in ("BUY", "SELL"):
            log.info("📊 %s → %s (függő straddle betöltés) | szintek: %s / %s "
                     "| WPR: %.1f", md.symbol, signal,
                     _fmt(state.buy_level, md.params), _fmt(state.sell_level, md.params),
                     state.prev_wpr if state.prev_wpr is not None else float("nan"))
        return state, signal

    def live_cells(self, state: StraddleState, md: MarketData) -> dict:
        """A körök a MOTOR élő állapotából — nincs külön rekonstrukció, tehát a
        tábla pontosan azt mutatja, amivel a motor kereskedik."""
        if not isinstance(state, StraddleState):
            return dict(_MARKS_EMPTY)
        return _cells(state)

    # ── Kijelzés (rekonstrukció: STOPPED / preview pár) ────────────────────

    def compute_display(self, md: MarketData) -> dict:
        df_hi = md.bars.get("M15")
        df_lo = md.bars.get("M1")
        if df_lo is None or len(df_lo) < 3:
            return dict(_MARKS_EMPTY)
        if df_hi is None or len(df_hi) < 2:
            df_hi = df_lo
        try:
            _, m1 = self.bt_indicators(df_hi, df_lo, md.params)
        except Exception:
            return dict(_MARKS_EMPTY)
        st = StraddleState(md.symbol)
        cols = _arrays(m1)
        for i in range(len(m1) - 1):        # csak ZÁRT gyertyák
            _step_at(st, cols, i, md.params)
        return _cells(st)

    # ── Méretezés (SL/TP TÁVOLSÁG — a lot NEM a stratégiáé) ────────────────

    def sl_tp_points(self, hi_row, params, point_size):
        """`(sl_points, tp_points)` PONTBAN, vagy `None`.

        `sl_mode="straddle"` (alap): SL = `sl_spread_mult` × spread. Ez a
        straddle természetes léptéke — a szemközti függő láb `2 ×
        straddle_spread_mult` spreadre van, tehát az „ellenoldali láb mint stop"
        klasszikus straddle-stop az `sl_spread_mult = 2 × straddle_spread_mult`
        beállítás.

        `sl_mode="atr_m1"` (az ATR-léptékű straddle párja): SL =
        `sl_atr_m1_mult` × M1 ATR. A klasszikus „ellenoldali láb a stop" itt
        `sl_atr_m1_mult = 2 × straddle_atr_mult`.

        `sl_mode="atr"`: a kódbázis szokásos M15 ATR-stopja (`sl_atr_mult`).

        ⚠ A STOPOT EGYÜTT KELL MOZGATNI A SZINTEKKEL. Ha a szintek ATR-léptékűek
        lennének, a stop viszont spreadben maradna, a stop MÉG mélyebben ülne a
        zajban, mint eddig — a mérés akkor nem az ötletet mérné, hanem egy
        elrontott arányt.
        """
        tp_rr = float(params.get("tp_rr_ratio", 2.0) or 2.0)
        mode = str(params.get("sl_mode", "atr_m1"))
        if mode == "atr":
            atr_v = hi_row.get("atr", 0) if hi_row is not None else 0
            if not atr_v or pd.isna(atr_v) or atr_v <= 0:
                return None
            return calc_sl_tp_points(float(atr_v),
                                     {**params, "point_size": point_size})
        if mode == "atr_m1":
            a1 = (hi_row.get("atr_m1_ref", float("nan"))
                  if hi_row is not None else float("nan"))
            if a1 is None or pd.isna(a1) or float(a1) <= 0 or not point_size:
                return None
            sl_points = float(a1) / float(point_size) * float(
                params.get("sl_atr_m1_mult", 2.0) or 2.0)
            if not (sl_points > 0):
                return None
            return sl_points, sl_points * tp_rr
        sp = (hi_row.get("spread_ref", float("nan"))
              if hi_row is not None else float("nan"))
        if sp is None or pd.isna(sp) or float(sp) <= 0 or not point_size:
            return None
        sl_points = float(sp) / float(point_size) * float(
            params.get("sl_spread_mult", 6.0) or 6.0)
        if not (sl_points > 0):
            return None
        return sl_points, sl_points * tp_rr

    # ⚠ NINCS SAJÁT `bt_entry`. A volatilitás-szűrés v3.27.0 óta a KAPUÉ
    # (`core.gates` + `gates.vol_baseline`) — az `atr_min_pct`/`atr_max_pct`
    # továbbra is ennek a stratégiának a paramétere, de a hatást a kapu dönti.

    # ── Optimalizálás ─────────────────────────────────────────────────────

    def base_params(self, cfg: dict) -> dict:
        return {**cfg.get("indicators", {}), **cfg.get("sltp", {}),
                **cfg.get("position_mgmt", {})}

    def param_space(self, cfg: dict, base_params: dict, method: str,
                    max_trials: int) -> list[dict]:
        from ml.optimizer import generate_random_params, generate_grid_params
        opt_cfg = cfg["optimizer"]
        if method == "grid":
            return generate_grid_params(opt_cfg, base_params, self.constraints_ok)
        return generate_random_params(opt_cfg, base_params, max_trials,
                                      self.constraints_ok)

    _constraints_cache = None

    def _opt_constraints(self) -> list:
        """A stratégia config `optimizer.constraints` listája (fájlból,
        cache-elve — a `constraints_ok` trialonként hívódik)."""
        if self._constraints_cache is None:
            from strategy.settings import load_strategy_config
            opt = (load_strategy_config(self.name).get("optimizer", {}) or {})
            self._constraints_cache = list(opt.get("constraints", []))
        return self._constraints_cache

    def constraints_ok(self, params: dict) -> bool:
        from core import param_constraints
        return param_constraints.check(params, self._opt_constraints())

    # ── MT5 chart-vizualizáció ────────────────────────────────────────────

    def visual_lookback_bars(self, params: dict, timeframe_label: str) -> int:
        days = int(params.get("viz_trade_lookback_days", 14) or 14)
        if timeframe_label == "M1":
            return int(params.get("wpr_period", 14) or 14) + days * 1440
        if timeframe_label == "M15":
            return int(params.get("atr_period", 14) or 14) + days * 96
        return 0

    def visual_objects(self, md: MarketData) -> list:
        """A chart-rajz: a függő SZINTEK (amíg kint voltak) + a betöltések
        jelölői + a WPR al-ablak.

        ⚠ A VÉGREHAJTÁSI KAPUKAT TISZTELETBEN TARTJA (`viz-must-respect-gate-
        effects`): csak a `block` hatású kapu szűrhet ki jelölőt — `none`/
        `reduce` mellett a motor BELÉP, tehát a jelölőnek látszania kell.
        """
        df_hi = md.bars.get("M15")
        df_lo = md.bars.get("M1")
        if df_lo is None or len(df_lo) < 3:
            return []
        if df_hi is None or len(df_hi) < 3:
            df_hi = df_lo
        try:
            m15, m1 = self.bt_indicators(df_hi, df_lo, md.params)
        except Exception as e:
            # ⚠ NEM néma: üres rajz + a hívó CLEAR-je kiürítené a chartot, és a
            # naplóban egy sor sem lenne róla.
            raise RuntimeError(
                f"{md.symbol}: a pending_straddle indikátorai nem számolhatók "
                f"a jelenlegi paraméterekkel ({type(e).__name__}: {e})") from e

        pip = float(md.params.get("point_size", 0.0001) or 0.0001)
        tf_min = _tf(md.params)
        tf_lab = f"M{tf_min}"
        objects: list = []
        # A rajz a DÖNTÉSI charton értelmes — ott látod a WPR-t is, amiből a
        # trigger született. (A betöltés-jelölők idő-horgonyzottak, tehát ott is
        # a helyükön vannak.) Egy másik idősíkon ugyanaz a görbe rossz
        # felbontásban jelenne meg — pontosan ezért van a TFONLY sor.
        objects.append(viz.TfOnly(tf_min))

        cols    = _arrays(m1)
        times1  = [int(t.timestamp()) for t in m1.index]
        atr15   = m15["atr"].to_numpy(dtype=float)
        t15     = [int(t.timestamp()) for t in m15.index]
        m15_sec = (int((m15.index[1] - m15.index[0]).total_seconds())
                   if len(m15) >= 2 else 900)
        _sp_m1  = _spread_series(m1)
        _sp_arr = _sp_m1.to_numpy(dtype=float) if _sp_m1 is not None else None
        _atr_mean = float(np.nanmean(atr15)) if np.isfinite(atr15).any() else 0.0

        _draw_sig = getattr(md, "show_signals", True)
        _sink = getattr(md, "on_entry_record", None)
        _exec = getattr(md, "exec_gates", True)
        _recs: list = []
        _levels: list = []          # [t_open, t_last, buy_level, sell_level, setup_id]

        st = StraddleState(md.symbol)
        p15 = 0
        for i in range(len(m1) - 1):            # az utolsó M1 formálódik
            sig = _step_at(st, cols, i, md.params)
            t = times1[i]
            if st.armed:
                if _levels and _levels[-1][4] == st.setup_id:
                    _levels[-1][1] = t
                else:
                    _levels.append([t, t, st.buy_level, st.sell_level, st.setup_id])
            elif _levels and _levels[-1][1] < t and _levels[-1][4] == st.setup_id:
                _levels[-1][1] = t              # a szetup ezen a gyertyán zárult

            if sig not in ("BUY", "SELL"):
                continue

            # Az adott M1 gyertyához tartozó UTOLSÓ ZÁRT M15 sor (a kapuk ebből
            # mérnek) — ugyanaz az igazítás, mint a motoré.
            while p15 + 1 < len(t15) and t15[p15 + 1] + m15_sec <= t:
                p15 += 1
            if t15[p15] + m15_sec > t or p15 >= len(atr15):
                continue

            # TF-együttállás kapu (a keret tölti): a DÖNTÉST hozó M1 ZÁRÓÁRÁVAL
            # — különben look-ahead lenne benne.
            if md.entry_gate is not None and not md.entry_gate(
                    t, float(cols["close"][i]), sig):
                continue

            atr_v = atr15[p15]
            if _exec and not math.isnan(atr_v):
                _base = _volb.value_at(atr15, p15, md.params, _atr_mean)
                if md.gate_blocks_at(
                        "volatility",
                        _volb.failed(float(atr_v), md.params, _base),
                        _gbands.level_volatility(float(atr_v), md.params, _base)):
                    continue
            if _exec and _sp_arr is not None and not math.isnan(atr_v):
                _spv = _sp_arr[i]
                if _spv > 0:
                    # ⚠ A `backtest_spread_points` ÁTADÁSA kötelező: abból jön a
                    # kapu RELATÍV padlója (normál spread × min_spread_mult).
                    _ok_s, _cap_s = spread_gate.spread_ok(
                        float(_spv) / pip, float(atr_v), pip, md.params,
                        md.params.get("backtest_spread_points"))
                    if md.gate_blocks_at(
                            "spread", not _ok_s,
                            _gbands.scalar_level(float(_spv) / pip, _cap_s)):
                        continue

            entry = float(cols["close"][i])
            plan = self.sl_tp_points(_hi_row_at(m15, p15), md.params, pip)
            if plan is None:
                continue
            sl_points, tp_points = plan
            if sig == "BUY":
                sl, tp = entry - sl_points * pip, entry + tp_points * pip
            else:
                sl, tp = entry + sl_points * pip, entry - tp_points * pip
            lab = f"{self.short_name} {sig}"
            if callable(getattr(md, "lot_of", None)):
                _l = md.lot_of(sl_points)
                if _l and _l > 0:
                    lab += f" {_l:.2f} lot"
            _recs.append({"t": t, "d": sig, "e": entry, "sl": sl, "tp": tp,
                          "lab": lab})

        # ⚠ KÉT MENET: hogy egy jelzésből lesz-e KÖTÉS, az csak a teljes sorozat
        # ismeretében dönthető el (egy páron egyszerre egy pozíció lehet).
        viz.mark_blocked(_recs, m1, self.name)
        for rec in _recs:
            if callable(_sink):
                _sink(rec)
            if _draw_sig:
                objects += viz.entry_marks(rec)

        # A függő szintek: zöld a BUY, piros a SELL oldal — pont ott és addig,
        # ameddig a megbízás „kint volt". Szaggatott (style=2), hogy a betöltés
        # tömör belépő-vonalától ránézésre elkülönüljön.
        if _draw_sig:
            for t0, t1, bl, sl_, _sid in _levels[-_VIZ_MAX_SETUPS:]:
                if bl is None or sl_ is None:
                    continue
                t1 = max(int(t1), int(t0) + 60)
                objects.append(viz.Trend(name=f"psbuy_{t0}", t1=int(t0), p1=bl,
                                         t2=t1, p2=bl, color="green",
                                         width=1, style=2))
                objects.append(viz.Trend(name=f"pssell_{t0}", t1=int(t0), p1=sl_,
                                         t2=t1, p2=sl_, color="red",
                                         width=1, style=2))

        # Beállítás-táblázat + a HASZNÁLT indikátor (a TradeForgeViz rakja fel).
        pm = md.params
        rows = [
            ("ps_title", "pending_straddle", 20),
            ("ps_wpr",   f"WPR {tf_lab}: {pm.get('wpr_period', '?')}", 36),
            ("ps_lvl",   f"Zona {pm.get('wpr_sell_extreme', '?')}/"
                         f"{pm.get('wpr_buy_extreme', '?')} -> trigger "
                         f"{pm.get('wpr_sell_trigger', '?')}/"
                         f"{pm.get('wpr_buy_trigger', '?')}", 52),
            ("ps_off",   ("Straddle: "
                          + (f"{pm.get('straddle_atr_mult', '?')} x M1 ATR"
                             if str(pm.get('straddle_mode', 'atr')) == 'atr'
                             else f"{pm.get('straddle_spread_mult', '?')} x spread")
                          + f", TTL {pm.get('straddle_ttl_bars', '?')} M1 bar"), 68),
            ("ps_sl",    ("SL: "
                          + {"atr_m1": f"{pm.get('sl_atr_m1_mult', '?')} x M1 ATR",
                             "atr":    f"{pm.get('sl_atr_mult', '?')} x M15 ATR"}.get(
                                 str(pm.get('sl_mode', 'atr_m1')),
                                 f"{pm.get('sl_spread_mult', '?')} x spread")
                          + f", TP RR {pm.get('tp_rr_ratio', '?')}"), 84),
        ]
        for name, text, y in rows:
            objects.append(viz.Label(name=name, text=text, corner=0, x=10, y=y,
                                     color="black", fontsize=9))
        objects.append(viz.Indicator(
            "WPR", tf_lab, int(pm.get("wpr_period", 14) or 14),
            (pm.get("wpr_sell_extreme", -20), pm.get("wpr_sell_trigger", -50),
             pm.get("wpr_buy_trigger", -50), pm.get("wpr_buy_extreme", -80)),
            color="black"))
        return objects


# ---------------------------------------------------------------------------
# Segédek (modul-szintűek: a hookok szoros ciklusban hívják őket)
# ---------------------------------------------------------------------------

def _f(v) -> float:
    """Biztonságos float — hiányzó/None/nem-szám mind `nan`."""
    if v is None:
        return float("nan")
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def _fmt(price, params: dict) -> str:
    """Ár-formázás a `point_size`-ból származó tizedesekkel.

    ⚠ SOHA NE `%.5g` (`price-format-never-5g`): az indexeknél exponenciálisba
    csap át, devizánál pedig elnyeli a pontokat."""
    if price is None or (isinstance(price, float) and math.isnan(price)):
        return "—"
    ps = float(params.get("point_size", 0.0001) or 0.0001)
    dec = max(0, min(8, int(round(-math.log10(ps))))) if ps > 0 else 5
    return f"{price:.{dec}f}"


_STEP_COLS = ("open", "high", "low", "close", "straddle_off",
              "sig_new", "sig_wpr", "sig_close")


def _arrays(df) -> dict:
    """A `_step`-hez kellő oszlopok NYERS tömbként.

    ⚠ MIÉRT: a kijelzés és a viz a MÉLY ablakot (≈20 000 M1 gyertya) játssza
    vissza, gyertyánként. A pandas `.iloc[i]` soronként új Series-t épít — a
    backtest-motor ugyanezt egyszer már 20,7×-es lassulásként mérte."""
    return {c: (df[c].to_numpy(dtype=float) if c in df.columns
                else np.full(len(df), np.nan)) for c in _STEP_COLS}


def _step_at(st: StraddleState, cols: dict, i: int, params: dict) -> str:
    return _step(st, cols["open"][i], cols["high"][i], cols["low"][i],
                 cols["close"][i], cols["straddle_off"][i], params,
                 cols["sig_new"][i], cols["sig_wpr"][i], cols["sig_close"][i])


def _hi_row_at(m15, p: int) -> dict:
    """Egy M15 sor a `sl_tp_points`-nek — dictként (a hook csak `.get`-et hív),
    hogy a viz-ciklus ne építsen soronként pandas Series-t."""
    return {
        "atr": float(m15["atr"].to_numpy(dtype=float)[p]),
        "spread_ref": (float(m15["spread_ref"].to_numpy(dtype=float)[p])
                       if "spread_ref" in m15.columns else float("nan")),
    }

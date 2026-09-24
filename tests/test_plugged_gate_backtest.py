"""A BACKTESZT OLVASSA A KAPU-REGISTRYT — a behelyezett (`.tfg`) kapuk is mérnek.

⚠ A LELET (2026-09-24). Az élő motor v3.29 óta a `REGISTRY`-t járja végig, és
minden kapu SAJÁT `measure(ctx)`-ét hívja. A BACKTESZT viszont a hat BEÉPÍTETT
kaput egyesével, kézzel importálva mérte (`from gates import spread_gate …`) —
egy `.tfg`-vel telepített kapuról NEM TUDOTT. A kovetkezmeny a projekt legdrágább
hibafajtája: NÉMA ELTÉRÉS az él és a mérés között. A backteszt megkötött volna
olyan jeleket, amiket élesben a kapu kiszűr — és a különbség sehol nem látszott
volna, csak az eredmények nem stimmelnének.

AMIT EZ A TESZT ŐRIZ, és amit külön ki kell mondani:

  1. A KAPU TÉNYLEG LEFUT. Nem elég, hogy a kód ott van: a mérést SZÁMOLJUK, és
     megnézzük, MILYEN kontextust kapott (szimbólum, irány, idő). A projektben
     egyszer már előfordult, hogy egy natív mag 0/19 cellán futott, miközben
     minden teszt zöld volt (`native-core-never-ran`).
  2. A KAPU TÉNYLEG DÖNT. Kedvezőtlenre állítva a kötés ELMARAD, `reduce`-szal
     KISEBB a lot — vagyis a hatás-létra a behelyezett kapura is él.
  3. KIKAPCSOLVA BITRE A RÉGI. Ez a legfontosabb: egy `none` hatású kapu
     PUSZTA LÉTEZÉSE nem változtathat meg egyetlen kötést sem. Az összehasonlítás
     alapja egy olyan futás, ahol a behelyezett kapuk listája ÜRES — vagyis a
     v3.101.0 előtti viselkedés.
  4. MINDKÉT MOTOR-ÚT. Az egypáros (`run_pair`) ÉS a portfólió — a kettő a
     pozíció-kezelés két leírása, és a projektben már némán szétcsúsztak egyszer
     (`portfolio-parity-and-one-engine`).

A mérés SZINTETIKUS adaton megy (nincs szükség a `data/` mappára): egyetlen
BUY-jel egy ismert időpontban, utána emelkedő ár, hogy a célár teljesüljön.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                                  # noqa: E402
applog.harden_console()

import logging                                                           # noqa: E402
logging.getLogger().setLevel(logging.ERROR)

import numpy as np                                                       # noqa: E402
import pandas as pd                                                      # noqa: E402

from core import gates as _g                                             # noqa: E402
from gates import sessions as S                                          # noqa: E402
from trading import backtest as bt                                       # noqa: E402

_results, _fail = [], []


def check(name, ok, detail=""):
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


# ---------------------------------------------------------------------------
# A szintetikus pár
# ---------------------------------------------------------------------------
# 2025-03-03 HÉTFŐ 08:00-tól. A jel a 100. M1-gyertyán (09:40 szerver-idő) —
# ilyenkor a frankfurti és a londoni tőzsde NYITVA van, tehát a kapu mér valamit,
# nem csak a hétvégi „zárva"-t adja vissza.
IDX1 = pd.date_range("2025-03-03 08:00", periods=400, freq="1min", tz="UTC")
IDX15 = pd.date_range("2025-03-03 08:00", periods=40, freq="15min", tz="UTC")
_DRIFT = np.concatenate([np.zeros(101), np.arange(1, len(IDX1) - 100) * 0.05])
M1 = pd.DataFrame({"open": 100.0 + _DRIFT, "high": 100.2 + _DRIFT,
                   "low": 99.8 + _DRIFT, "close": 100.0 + _DRIFT,
                   "avg_spread": 0.01, "close_spread": 0.01}, index=IDX1)
M15 = pd.DataFrame({"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0},
                   index=IDX15)
JEL_IDO = IDX1[100]

PAIR_CFG = {"point_size": 0.01, "pv1_point": 1.0, "min_lot": 0.01,
            "lot_step": 0.01, "backtest_spread_points": 1.0,
            "enabled": True, "strategies": ["wpr_sma"]}


class Strat:
    """A legegyszerűbb stratégia, ami EGY belépőt ad — a kapuk mérésére."""

    name = "wpr_sma"
    default_sl_method = "atr"

    def timeframes(self):
        from strategy.base import Timeframe
        return [Timeframe("M15", 15), Timeframe("M1", 1)]

    def bt_indicators(self, hi, lo, p):
        hi = hi.copy()
        hi["atr"] = 1.0
        return hi, lo

    def bt_warmup(self, p, tf):
        return 0

    def bt_new_state(self, sym):
        return {}

    def bt_on_high_close(self, st, row, p):
        return st

    def bt_on_low_close(self, st, prev, row, p):
        return "BUY" if row.name == JEL_IDO else "NONE"

    def bt_entry(self, row, p, ps):
        return (100.0, 200.0)


def _cfg(effect="none", adverse=None, bands=None):
    """Config a szintetikus párhoz. A többi kaput KIKAPCSOLJUK, hogy csak a
    behelyezett kapu hatása látsszon."""
    sess = {"sessions": {"wpr_sma": (dict(effect=effect, bands=bands)
                                     if bands else effect)}}
    return {
        "pairs": {"T": dict(PAIR_CFG, gates=sess,
                            sessions={"markets": ["europa"],
                                      "adverse": list(adverse or [])})},
        "trading": {"account_risk_pct": 0.02, "max_open_slots": 1,
                    "daily_loss_limit_usd": 0, "daily_loss_limit_pct": 100.0},
        "available_strategies": {"wpr_sma": True},
        "strategy": {"name": "wpr_sma"},
        "gates": {"spread": {"default": "none"}, "tf_align": {"default": "none"},
                  "volatility": {"default": "none"}},
    }


def _run_pair(cfg):
    # ⚠ A PAR-SZEKCIO A CONFIGBOL JON, nem egy kulon dict — pontosan ugy, ahogy
    # az eles hivo teszi (`cfg["pairs"][sym]`). Enelkul a kapu a sajat
    # beallitasait (naptar, piac-halmaz, kedvezotlen allapotok) NEM latna, es a
    # teszt azt merne, hogy egy beallitatlan kapu nem tilt — semmit.
    return bt.run_pair("T", M15, M1, {}, cfg["pairs"]["T"],
                       {"account_risk_pct": 0.02, "max_open_slots": 1},
                       10000.0, strategy=Strat(), cfg=cfg, exec_gates=True)


# ---------------------------------------------------------------------------
print("== 1. A KAPU TENYLEG LEFUT (nem eleg, hogy ott a kod) ==")
_HIVAS = []
_orig_measure = S.measure


def _spy(ctx):
    _HIVAS.append(ctx)
    return _orig_measure(ctx)


S.measure = _spy
try:
    _r = _run_pair(_cfg("block"))                  # aktív, de nincs kedvezőtlen állapot
finally:
    S.measure = _orig_measure

check("a behelyezett kapu MERESE lefutott a backtestben", bool(_HIVAS),
      f"{len(_HIVAS)} hívás")
if _HIVAS:
    _c = _HIVAS[0]
    check("...a SZIMBOLUMOT megkapta", getattr(_c, "symbol", None) == "T",
          str(getattr(_c, "symbol", None)))
    check("...az IRANYT is", getattr(_c, "signal", None) == "BUY",
          str(getattr(_c, "signal", None)))
    check("...es az IDOT: a BELEPO GYERTYA ideje (nem a falióra)",
          getattr(_c, "now", None) == JEL_IDO, str(getattr(_c, "now", None)))
    check("...a par configja is atjott (ebbol jon a naptar es a piac-halmaz)",
          (getattr(_c, "pair_cfg", None) or {}).get("sessions") is not None)
check("a kapu NEM tiltott (nincs kedvezotlen allapot) -> VAN kotes",
      len(_r.trades) == 1, str(len(_r.trades)))

# ---------------------------------------------------------------------------
print("\n== 2. A KAPU TENYLEG DONT ==")
_MIND = list(S.STATES)
_blk = _run_pair(_cfg("block", adverse=_MIND))
check("minden allapot kedvezotlen + `block` -> NINCS kotes",
      not _blk.trades, str(len(_blk.trades)))
_red = _run_pair(_cfg("reduce", adverse=_MIND))
check("`reduce` -> VAN kotes (nem tilt)", len(_red.trades) == 1,
      str(len(_red.trades)))
if _red.trades and _r.trades:
    check("...de KISEBB lottal (a hatas-letra a behelyezett kapura is el)",
          _red.trades[0].lot < _r.trades[0].lot,
          f"{_r.trades[0].lot} -> {_red.trades[0].lot}")
    check("...meghozza a felezessel",
          abs(_red.trades[0].lot - _r.trades[0].lot * _g.REDUCE_RISK_FACTOR) < 1e-9,
          f"{_red.trades[0].lot}")

# KATEGORIA-SAV: allapotonkent mas hatas — ugyanaz a letra, mint a piac-kapunal.
_sav = _run_pair(_cfg("block", bands={st: ("block" if st == S.NYITVA else "none")
                                      for st in S.STATES}))
check("kategoria-SAV: a mert allapotra irt hatas ervenyesul",
      not _sav.trades, str(len(_sav.trades)))

# ---------------------------------------------------------------------------
print("\n== 3. KIKAPCSOLVA BITRE A REGI ==")
# ⚠ EZ AZ IGAZI OR. Az alap egy olyan futás, ahol a behelyezett kapuk listája
# ÜRES — vagyis pontosan a v3.101.0 ELŐTTI viselkedés. Ha egy `none` hatású kapu
# PUSZTA LÉTEZÉSE bármit elmozdítana, az a legrosszabb fajta regresszió: minden
# korábbi mérés érvényét vesztené.
_orig_plug = _g.plugged_keys
_g.plugged_keys = lambda phase=None: ()
try:
    _alap = _run_pair(_cfg("none"))
finally:
    _g.plugged_keys = _orig_plug
_most = _run_pair(_cfg("none"))


def _ujjlenyomat(res):
    return [(t.open_time, t.close_time, t.direction, round(t.lot, 10),
             round(float(t.pnl_usd), 10), t.status) for t in res.trades]


check("`none` hatassal a kotesek BITRE azonosak a regi uttal",
      _ujjlenyomat(_alap) == _ujjlenyomat(_most),
      f"{_ujjlenyomat(_alap)} vs {_ujjlenyomat(_most)}")
check("...es nem ures a meres (kulonben az egyezes semmit nem bizonyitana)",
      len(_most.trades) == 1, str(len(_most.trades)))
check("az EGYENLEG-GORBE is azonos (nem csak a kotesek)",
      [tuple(str(v) for v in x) for x in (_alap.balance_curve or [])]
      == [tuple(str(v) for v in x) for x in (_most.balance_curve or [])],
      f"{len(_alap.balance_curve or [])} vs {len(_most.balance_curve or [])} pont")

# ...es a `none` kapu MEG CSAK NEM IS MER (nincs felesleges munka a ciklusban).
_HIVAS.clear()
S.measure = _spy
try:
    _run_pair(_cfg("none"))
finally:
    S.measure = _orig_measure
check("`none` hatasnal a kapu meg sem szolal meg (nincs felesleges meres)",
      not _HIVAS, f"{len(_HIVAS)} hívás")

# ---------------------------------------------------------------------------
print("\n== 4. A PORTFOLIO-UT IS ==")
# A portfólió a pozíció-kezelés MÁSIK leírása; a projektben a kettő már némán
# szétcsúszott egyszer. Itt ugyanazt a három állítást mérjük.
import strategy.settings as _ss                                          # noqa: E402

_orig_dp, _orig_load, _orig_get = (_ss.default_params, bt.load_data,
                                   bt.get_strategy_by_name)


def _run_pf(cfg):
    _ss.default_params = lambda st, c=None: {"atr_period": 14}
    bt.load_data = lambda sym: (M15, M1)
    bt.get_strategy_by_name = lambda n=None: Strat()
    try:
        return bt.run_portfolio_backtest(cfg, ["T"], "2025-03-03", "2025-03-04",
                                         initial_balance=10000.0,
                                         exec_gates=True, strategy_name="wpr_sma")
    finally:
        (_ss.default_params, bt.load_data,
         bt.get_strategy_by_name) = _orig_dp, _orig_load, _orig_get


_pf_ok = _run_pf(_cfg("block"))
check("portfolio: kedvezotlen allapot NELKUL van kotes",
      len(_pf_ok.get("trades") or []) == 1,
      str(len(_pf_ok.get("trades") or [])))
_pf_blk = _run_pf(_cfg("block", adverse=_MIND))
check("portfolio: kedvezotlen allapotra NINCS kotes",
      not (_pf_blk.get("trades") or []),
      str(len(_pf_blk.get("trades") or [])))
_HIVAS.clear()
S.measure = _spy
try:
    _run_pf(_cfg("block"))
finally:
    S.measure = _orig_measure
check("portfolio: a kapu MERESE tenyleg lefutott", bool(_HIVAS),
      f"{len(_HIVAS)} hívás")

_g.plugged_keys = lambda phase=None: ()
try:
    _pf_alap = _run_pf(_cfg("none"))
finally:
    _g.plugged_keys = _orig_plug
_pf_most = _run_pf(_cfg("none"))
check("portfolio: `none` hatassal BITRE a regi",
      abs(_pf_alap["final_balance"] - _pf_most["final_balance"]) < 1e-9
      and len(_pf_alap["trades"]) == len(_pf_most["trades"]) == 1,
      f'{_pf_alap["final_balance"]} vs {_pf_most["final_balance"]}')

# ---------------------------------------------------------------------------
print("\n== 5. A SZERKEZET (hogy ne csusszon vissza) ==")
_src = (ROOT / "trading" / "backtest.py").read_text(encoding="utf-8")
check("MINDKET motor-ut a registryt kerdezi", _src.count("plugged_keys(") >= 2,
      f'{_src.count("plugged_keys(")} hívás')
check("a JEL- es a TERV-fazis is megvan",
      "_gt.PHASE_SIGNAL" in _src and "_gt.PHASE_PLAN" in _src)
check("a keret tudja, mi a BEEPITETT es mi a behelyezett",
      set(_g.BUILTIN_KEYS) | set(_g.plugged_keys()) == set(_g.KEYS)
      and not (set(_g.BUILTIN_KEYS) & set(_g.plugged_keys())),
      f"{_g.BUILTIN_KEYS} | {_g.plugged_keys()}")

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)

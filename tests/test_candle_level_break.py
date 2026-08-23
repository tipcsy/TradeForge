"""CLB — gyertyaszint-törés (H4 szint + M15 konszolidáció-kitörés).

A stratégia forrása egy YouTube-videó módszere, de ⚠ **ez a MI változatunk**: a
videó több ponton nem elég objektív („momentum gyertya", trendvonal-illesztés,
a belépő pillanata), és a szerző az ilyen kérdésekre nem válaszol. A hiányzó
döntéseket mi hoztuk meg — a teszt ezeket a DÖNTÉSEKET is rögzíti, hogy később
tudjuk, hol tértünk el, és hogy egy átírás ne csendben történjen.

⚠ AMIT A BEVEZETÉS TANÍTOTT (mindkettő MÉRÉSBŐL):

1. **A `cons_max_atr` kalibrálása.** Az első változat 0,8-at használt (a
   specifikációból, mérés nélkül) — ezzel a stratégia 5 hónap alatt **10 kötést**
   adott. A tölcsért végigmérve: a 4 gyertyás M15 sáv medián szélessége
   **1,85–1,93 ATR** (négy páron feltűnően egyforma), tehát a 0,8-as küszöb azt
   kérte, hogy négy gyertya EGYÜTT keskenyebb legyen, mint fél gyertya ATR-je.
   1,4-gyel (a sorok ~22%-a) 295 kötés lett hat páron.

2. **A `bollinger_squeeze` lappangó hibája.** A `param_space` a NEM LÉTEZŐ
   `ml.param_space` modult importálta; az alapértelmezett optuna nem hívja, ezért
   a `grid`/`random` úton `ModuleNotFoundError`-ral állt volna meg. Akkor derült
   ki, amikor mintaként átmásoltam ugyanazt a sort.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


import logging
logging.disable(logging.INFO)

import numpy as np
import pandas as pd

from strategy import get_strategy_by_name, registered_strategy_names
from strategy.base import Strategy
from strategy.settings import load_strategy_config

NAME = "candle_level_break"

# ── 1. REGISZTRÁCIÓ ÉS INTERFÉSZ ────────────────────────────────────────
check("a modul automatikusan regisztrálódott", NAME in registered_strategy_names(),
      str(registered_strategy_names()))
st = get_strategy_by_name(NAME)
check("rövid neve CLB (szűk helyekre)", st.short_name == "CLB", st.short_name)

import inspect
_abs = {n for n, v in inspect.getmembers(Strategy)
        if getattr(v, "__isabstractmethod__", False)}
_missing = [m for m in _abs if getattr(type(st), m, None) is getattr(Strategy, m, None)]
check("minden KÖTELEZŐ metódus implementálva", not _missing, str(_missing))

# ⚠ EGYEDI MAGIC: enélkül a nyitott pozíciók broker-szinten nem választhatók szét
# a többi stratégiáétól.
_magics = {n: get_strategy_by_name(n).magic({"broker": {"magic": 100}})
           for n in registered_strategy_names()}
check("a magic EGYEDI minden stratégián", len(set(_magics.values())) == len(_magics),
      str(_magics))

# ⚠ A DÖNTÉSI gyertya M15 — a riasztás-dedup és a viz idősík-kapuja ebből dolgozik.
check("a döntési gyertya M15 (900 mp)", st.signal_bar_seconds({}) == 900,
      str(st.signal_bar_seconds({})))
check("a keret M15+M1 csővezetékén dolgozik (a H4 BELÜL van)",
      [t.label for t in st.timeframes()] == ["M15", "M1"],
      str([t.label for t in st.timeframes()]))


# ── 2. A CONFIG ÉS A KÉNYSZEREK ─────────────────────────────────────────
CFG = load_strategy_config(NAME)
P = {k: v for k, v in st.base_params(CFG).items() if not str(k).startswith("_")}
for _k in ("swing_bars", "level_ttl_bars", "retest_atr", "cons_bars",
           "cons_max_atr", "stop_buffer_atr", "tp_rr_ratio"):
    check(f"van alapérték: {_k}", _k in P, str(sorted(P)))

# ⚠ A MÉRT kalibráció — ha valaki visszaírja 0,8-ra, a stratégia némán elnémul.
check("a cons_max_atr a MÉRT tartományban van (1,0–2,0)",
      1.0 <= float(P["cons_max_atr"]) <= 2.0, str(P["cons_max_atr"]))
check("...és a config INDOKOLJA is (mérés a kommentben)",
      "1,85" in json.dumps(CFG, ensure_ascii=False))
_rng = CFG["optimizer"]["cons_max_atr"]
check("a keresési tartomány is a mért régióban",
      _rng["min"] >= 1.0 and _rng["max"] <= 2.0, str(_rng))

# ⚠ A stop nem eshet a konszolidációs sávon BELÜLRE — különben a belépő
# pillanatában már ki is ütné.
check("constraints_ok: érvényes kombó átmegy", st.constraints_ok(P))
check("constraints_ok: stop a sávon BELÜL → elbukik",
      not st.constraints_ok({**P, "stop_buffer_atr": 2.0, "cons_max_atr": 1.0}))
check("a param_space fut (a helper a MEGFELELŐ modulból)",
      len(st.param_space(CFG, P, "random", 5)) == 5)


# ── 3. A SZINT-SZÁMÍTÁS — és a JÖVŐ-SZIVÁRGÁS ELLENI védelem ───────────
from strategy.candle_level_break import _levels

# Szintetikus H4: egy egyértelmű swing-alj a 10. gyertyán.
_n = 30
_lo = np.full(_n, 100.0)
_hi = np.full(_n, 101.0)
_lo[10], _hi[10] = 90.0, 95.0          # a legmélyebb gyertya
_h4 = pd.DataFrame({"open": _lo, "high": _hi, "low": _lo, "close": _hi},
                   index=pd.date_range("2026-01-01", periods=_n, freq="4h", tz="UTC"))
_lv = _levels(_h4, swing_bars=2, ttl=100)

# ⚠ A SZINT a legmélyebb gyertya TETEJE („mert fordulást várunk") — nem az alja.
check("a szint a legmélyebb gyertya TETEJE", float(_lv["long_level"].iloc[15]) == 95.0,
      str(_lv["long_level"].iloc[15]))
check("...a stop-referencia pedig az ALJA",
      float(_lv["long_stop_ref"].iloc[15]) == 90.0, str(_lv["long_stop_ref"].iloc[15]))

# ⚠ NINCS JÖVŐ-SZIVÁRGÁS: egy ±2 fraktál csak 2 gyertyával KÉSŐBB ismerhető fel.
check("a szint a fraktál gyertyáján még NEM él",
      pd.isna(_lv["long_level"].iloc[10]) or _lv["long_level"].iloc[10] != 95.0,
      str(_lv["long_level"].iloc[10]))
check("...és a felismerés előtt sem", pd.isna(_lv["long_level"].iloc[11])
      or _lv["long_level"].iloc[11] != 95.0, str(_lv["long_level"].iloc[11]))
check("...de utána igen", float(_lv["long_level"].iloc[13]) == 95.0,
      str(_lv["long_level"].iloc[13]))

# ⚠ A TTL: a szint ELÉVÜL, különben a régi szintek végtelenül halmozódnának.
_lv2 = _levels(_h4, swing_bars=2, ttl=3)
check("a szint elévül a TTL után", pd.isna(_lv2["long_level"].iloc[25]),
      str(_lv2["long_level"].iloc[25]))


# ── 4. A BELÉPŐ ÁLLAPOTGÉPE ────────────────────────────────────────────
# ⚠ [DÖNTÉS] A videó „momentum gyertyát" említ, de a képen bekarikázott formáció
# 2-3 APRÓ gyertya, és a belépő az utánuk jövő KITÖRÉS. Így a „mekkora a momentum
# gyertya?" kérdés elkerülhető: a kitörés a SÁV CSÚCSÁN mérhető, küszöb nélkül.
_src = (ROOT / "strategy" / "candle_level_break.py").read_text(encoding="utf-8")
check("a döntéseink jelölve vannak a kódban", _src.count("[DÖNTÉS]") >= 2)
check("a trendvonalat SZÁNDÉKOSAN nem implementáljuk (indokkal)",
      "trendvonalat sem implementáljuk" in _src)


def _row(**kw):
    d = {"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "atr": 1.0,
         "long_level": np.nan, "short_level": np.nan,
         "cons_hi": np.nan, "cons_lo": np.nan}
    d.update(kw)
    return pd.Series(d)


_p = {"retest_atr": 0.5, "cons_max_atr": 1.4, "stop_buffer_atr": 0.3,
      "tp_rr_ratio": 2.0}
s = st.new_signal_state("X")
# (a) szint van, de az ár alatta → nincs törés
check("szint alatt nincs jel",
      st._step(s, _row(long_level=105.0, close=100.0), _p) == "NONE")
# (b) TÖRÉS: a TEST a szint fölé zár
st._step(s, _row(long_level=100.0, open=100.2, close=101.0, high=101.2, low=100.1), _p)
check("a TEST szint fölé zárása = törés", s.broke_up)
# (c) VISSZATESZT: az ár visszaér a szint környezetébe
st._step(s, _row(long_level=100.0, open=100.8, close=100.6, high=100.9, low=100.2), _p)
check("a szint környezetébe visszatérés = visszateszt", s.retested_up)
# (d) KITÖRÉS a konszolidációs sávból → BUY
_sig = st._step(s, _row(long_level=100.0, open=100.6, close=101.5, high=101.6,
                        low=100.5, cons_hi=101.0, cons_lo=100.2), _p)
check("a sáv csúcsa fölé zárás = BELÉPŐ", _sig == "BUY", _sig)
check("...és az állapot NULLÁZÓDIK (nem tüzel újra)",
      not s.broke_up and not s.retested_up)

# ⚠ SZÉLES sáv NEM konszolidáció — akkor sincs belépő, ha az ár kitör.
s2 = st.new_signal_state("X")
st._step(s2, _row(long_level=100.0, open=100.2, close=101.0, high=101.2, low=100.1), _p)
st._step(s2, _row(long_level=100.0, open=100.8, close=100.6, high=100.9, low=100.2), _p)
_wide = st._step(s2, _row(long_level=100.0, open=100.6, close=101.5, high=101.6,
                          low=100.5, cons_hi=101.0, cons_lo=98.0), _p)
check("SZÉLES sávnál nincs belépő", _wide == "NONE", _wide)


# ── 5. MÉRETEZÉS: a stop a SÁV alja alá ────────────────────────────────
_plan = st.sl_tp_points(_row(close=101.5, atr=1.0, cons_hi=101.0, cons_lo=100.2,
                             short_level=np.nan), _p, 0.01)
check("van SL/TP terv", _plan is not None)
if _plan:
    _sl, _tp = _plan
    # (101,5 − (100,2 − 0,3)) / 0,01 = 160 pont
    check("a stop a KONSZOLIDÁCIÓ alja alá kerül (nem a szint-gyertyáé)",
          abs(_sl - 160.0) < 1e-6, str(_sl))
    check("tartalék célár = tp_rr_ratio × kockázat", abs(_tp - 2.0 * _sl) < 1e-6,
          str(_tp))
# ⚠ Ha van ÉRVÉNYES következő szint, az nyer (szinttől szintig).
_plan2 = st.sl_tp_points(_row(close=101.5, atr=1.0, cons_hi=101.0, cons_lo=100.2,
                              short_level=104.5), _p, 0.01)
if _plan2:
    check("a KÖVETKEZŐ SZINT felülírja a tartalék célárat",
          abs(_plan2[1] - 300.0) < 1e-6, str(_plan2[1]))
# A múltban lévő (ár alatti) szint NEM célár.
_plan3 = st.sl_tp_points(_row(close=101.5, atr=1.0, cons_hi=101.0, cons_lo=100.2,
                              short_level=99.0), _p, 0.01)
if _plan3:
    check("az ár ALATTI szint nem lehet célár (tartalékra esik)",
          abs(_plan3[1] - 2.0 * _plan3[0]) < 1e-6, str(_plan3[1]))


# ── 6. A LAPPANGÓ IMPORT-HIBA, ami itt derült ki ───────────────────────
# ⚠ A `bollinger_squeeze.param_space` a NEM LÉTEZŐ `ml.param_space`-t importálta.
# Az optuna nem hívja, ezért a hiba a `grid`/`random` úton hetekig lappangott.
for _n in registered_strategy_names():
    _s = (ROOT / "strategy" / f"{_n}.py")
    if _s.exists():
        check(f"{_n}: nem importál nem létező param_space modult",
              "from ml.param_space import" not in _s.read_text(encoding="utf-8"))
_bb = get_strategy_by_name("bollinger_squeeze_breakout")
_bcfg = load_strategy_config("bollinger_squeeze_breakout")
check("a bollinger param_space TÉNYLEG fut (grid úton is)",
      len(_bb.param_space(_bcfg, _bb.base_params(_bcfg), "random", 3)) == 3)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

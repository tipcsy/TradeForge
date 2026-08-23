"""A felület belassulásának két gyökere — a javítás VISELKEDÉSE változatlan.

A dashboard `_refresh_pair_data`-ja MÉLY ablakot tölt (`signal_warmup_bars`:
M15 ~3000, M1 ~43 000 gyertya) és MINDEN körben (3–30 mp) újraszámolja a
kijelzést, MINDEN párra, MINDEN engedélyezett stratégiával — háttérszálon,
ami tartja a GIL-t → a Tk fő ciklusa megáll (`data/ui_watchdog.log`).

  1. `wpr_sma._rebuild_m1_armed` a teljes 43 000 M1 gyertyán VÉGIGLÉPKEDETT,
     hogy megtalálja a nyitott M15 ablak elejét — gyertyánként BOXOLVA egy
     pandas Timestampet (`m1.index[k]`). Most bináris keresés (`searchsorted`).
  2. `ml_ai.compute_display` a TELJES feature-frame-et felépítette (~3000 sor),
     hogy az UTOLSÓ sorát használja — körönként, páronként. Most memoizált: a
     kijelzés csak ZÁRT gyertyákból számol, tehát két gyertyazárás között
     ugyanaz az eredmény.

Ez a teszt azt őrzi, hogy egyik gyorsítás sem VÁLTOZTAT az eredményen.
"""
import math
import random
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy import ml_ai, wpr_sma
from strategy.base import MarketData

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ══ 1. _rebuild_m1_armed — a REFERENCIA (régi, lineáris) implementáció ═════
def ref_rebuild(state, m1, win_open_ts, params, upto: int) -> str:
    """A javítás ELŐTTI, gyertyánként lépkedő változat — igazságforrásként."""
    wl = m1["wpr"].values
    idx = m1.index
    prev = None
    last_sig = "NONE"
    for k in range(min(int(upto), len(m1))):
        cur = wl[k]
        if idx[k] <= win_open_ts:
            prev = cur
            continue
        if prev is not None and not (math.isnan(prev) or math.isnan(cur)):
            last_sig = wpr_sma.check_m1_entry(state, float(prev), float(cur), params)
        prev = cur
    return last_sig


random.seed(11)
np.random.seed(11)

N = 4000
idx = pd.date_range("2026-01-01", periods=N, freq="1min", tz="UTC")
wpr = np.random.uniform(-100.0, 0.0, N)
wpr[:30] = np.nan                       # bemelegítési NaN-ok (mint az igaziban)
wpr[1500:1510] = np.nan                 # adatlyuk a közepén
M1 = pd.DataFrame({"wpr": wpr}, index=idx)

PARAMS = {"wpr_m1_period": 8, "wpr_m1_buy_extreme": -80.0,
          "wpr_m1_sell_extreme": -20.0,
          "wpr_m1_sell_trigger": -50.0, "wpr_m1_buy_trigger": -50.0}


def both(win_open_ts, upto):
    """(referencia_jel, referencia_state) vs (új_jel, új_state)."""
    a = wpr_sma.PairState("TEST")
    a.m15_window_open = True
    a.direction = "BUY"
    b = replace(a)
    return (ref_rebuild(a, M1, win_open_ts, PARAMS, upto), a,
            wpr_sma._rebuild_m1_armed(b, M1, win_open_ts, PARAMS, upto), b)


cases = [idx[0], idx[1], idx[-1], idx[-2],
         idx[0] - pd.Timedelta("7D"),      # az ablak a tartomány ELŐTT nyílt
         idx[-1] + pd.Timedelta("7D"),     # az ablak a tartomány UTÁN nyílt
         idx[1505],                        # az adatlyuk közepén
         idx[29], idx[30]]                 # a NaN-blokk határán
cases += [idx[random.randrange(N)] for _ in range(60)]

bad_sig = bad_state = 0
for ts in cases:
    for upto in (N - 2, N - 1, N, N + 10, 250, 0):
        r_sig, r_st, n_sig, n_st = both(ts, upto)
        if r_sig != n_sig:
            bad_sig += 1
        if r_st != n_st:
            bad_state += 1

check(f"a jel bitazonos a régi implementációval ({len(cases) * 6} eset)",
      bad_sig == 0, f"eltérés={bad_sig}")
check("a felfegyverzés-ÁLLAPOT (m1_armed) is bitazonos",
      bad_state == 0, f"eltérés={bad_state}")

# A gyorsítás lényege: a nyitás ELŐTTI gyertyák nem lépnek be az állapotgépbe,
# de a közvetlenül előttük lévő `prev` igen — ezt külön is rögzítjük.
_a = wpr_sma.PairState("TEST"); _a.m15_window_open = True; _a.direction = "BUY"
_b = replace(_a)
check("a `prev` az ablak ELŐTTI utolsó gyertyáról jön (nem None-ról indul)",
      wpr_sma._rebuild_m1_armed(_a, M1, idx[2000], PARAMS, N - 1) ==
      ref_rebuild(_b, M1, idx[2000], PARAMS, N - 1))

# Üres ablak (a nyitás a `upto` UTÁN van) → nincs jel, az állapot érintetlen.
_c = wpr_sma.PairState("TEST"); _c.m15_window_open = True; _c.direction = "BUY"
_c0 = replace(_c)
check("a `upto` utáni ablaknyitás -> 'NONE' és érintetlen állapot",
      wpr_sma._rebuild_m1_armed(_c, M1, idx[-1], PARAMS, 100) == "NONE" and _c == _c0)


# ══ 2. ml_ai.compute_display memoizálás ════════════════════════════════════
# A kijelzés a formálódó gyertyát LEVÁGJA, tehát két gyertyazárás között
# ugyanaz — a cache ezt használja ki. A kulcsban minden bemenet benne van.
M = 300
i15 = pd.date_range("2026-01-01", periods=M, freq="15min", tz="UTC")
base = 100.0 + np.cumsum(np.random.normal(0, 0.5, M))
BARS = pd.DataFrame({"open": base, "high": base + 1.0, "low": base - 1.0,
                     "close": base, "tick_volume": 100}, index=i15)

calls = {"n": 0}
_real_build = ml_ai.mlf.build_feature_frame


def counting_build(df, pip):
    calls["n"] += 1
    return _real_build(df, pip)


ml_ai.mlf.build_feature_frame = counting_build
ml_ai._display_cache.clear()

# Modell-csomag ATTRAPP: a tesztszimbólumra nincs .pkl, a `compute_display`
# viszont a bundle hiányában KILÉPNE a feature-frame előtt — akkor a cache-t
# nem is érintenénk. `model: None` → a `_predict_frame` nullákat ad (sosem
# tüzel), de a feature-frame ÉPÜL, és épp azt számoljuk.
_real_load = ml_ai.load_bundle
ml_ai.load_bundle = lambda symbol: {"features": ml_ai.mlf.FEATURES,
                                    "long":  {"model": None, "threshold": 0.6},
                                    "short": {"model": None, "threshold": 0.6},
                                    "meta": {}}

strat = ml_ai.MlAiStrategy()
tf_label = strat.timeframes()[0].label
P = {"point_size": 0.1, "sess_start": 0, "sess_end": 24}


def cells_for(bars):
    md = MarketData(symbol="__TESTSYM__", params=dict(P), bars={tf_label: bars})
    return strat.compute_display(md)


c1 = cells_for(BARS)
c2 = cells_for(BARS)
check("ugyanaz a bemenet -> ugyanaz a kijelzés",
      {k: (v.text, v.color) for k, v in c1.items()} ==
      {k: (v.text, v.color) for k, v in c2.items()})

check("a második hívás NEM építi újra a feature-frame-et (memoizálás)",
      calls["n"] == 1, f"build hívások={calls['n']}")

n_before = calls["n"]
cells_for(BARS.iloc[:-1])              # eggyel korábbi zárt gyertya → más kulcs
check("ÚJ gyertyazárásnál (más utolsó zárt idő) újraszámol",
      calls["n"] == n_before + 1, f"build hívások={calls['n']}")

n_before = calls["n"]
md = MarketData(symbol="__TESTSYM__", params={**P, "sess_end": 12},
                bars={tf_label: BARS})
strat.compute_display(md)
check("a session-kapu órájának változása is ÉRVÉNYTELENÍTI a cache-t",
      calls["n"] == n_before + 1, f"build hívások={calls['n']}")

# A cache-ből visszaadott szótár MÁSOLAT: a hívó módosítása nem szennyezi be.
_c = cells_for(BARS.iloc[:-1])
_c["sig"] = "SZEMET"
check("a cache MÁSOLATOT ad vissza (a hívó nem tudja elrontani)",
      cells_for(BARS.iloc[:-1]).get("sig") != "SZEMET")

ml_ai.mlf.build_feature_frame = _real_build
ml_ai.load_bundle = _real_load


# ── A FAGYÁS-FIGYELŐ KÜSZÖBE ────────────────────────────────────────────
# ⚠ MÉRÉS, nem érzés. A 2,0 mp-es küszöb 12 nap alatt 112 riasztást adott, és
# MINDEGYIK ugyanaz volt: élő kereskedés mellett futó backtest/optimalizálás,
# három pandas-nehéz szál (LiveTrader + InstrBacktest + TradeForgeViz), a fő
# szál pedig 2,0–2,5 mp-ig nem kapta vissza a GIL-t. A leghosszabb valaha
# mért akadás 3,0 mp — a 4,0-s küszöb tehát MINDET átengedi, és csak arra szól,
# ami tényleg kilóg.
#
# ⚠ A figyelő MEGMARAD: a hallgatás nem cél. Csak a küszöb kerül oda, ahol a
# riasztás információt hordoz, nem zajt (`data/ui_watchdog.log`).
import inspect as _insp2
import json as _json2
from dashboard import gui as _g2
_ROOT2 = Path(__file__).resolve().parents[1]
_wsrc = _insp2.getsource(_g2.DashboardWindow._start_watchdog)
check("a küszöb alapértelmezése 4,0 mp",
      '"watchdog_threshold_sec", 4.0' in _wsrc, _wsrc[_wsrc.find("threshold ="):][:60])
check("...és a mérés ott van indoklásként", "3,0 mp" in _wsrc)
check("a figyelő megmarad (nem kapcsoltuk ki)",
      "_watchdog_running" in _wsrc and "_stall_report" in _wsrc)

# ⚠ HÁZIREND: a config csak az ELTÉRÉST rögzíti. Egy 4.0-ra írt kulcs a későbbi
# alapérték-változást NÉMÁN hatástalanná tenné ezen a gépen.
_cfg2 = _json2.loads((_ROOT2 / "config.json").read_text(encoding="utf-8"))
check("az éles config NEM rögzíti külön (az alapérték hat)",
      "watchdog_threshold_sec" not in (_cfg2.get("dashboard") or {}))
_ex2 = _json2.loads((_ROOT2 / "config.example.json").read_text(encoding="utf-8"))
check("a példa-config az ÚJ alapot mutatja",
      (_ex2.get("dashboard") or {}).get("watchdog_threshold_sec") == 4.0,
      str((_ex2.get("dashboard") or {}).get("watchdog_threshold_sec")))


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

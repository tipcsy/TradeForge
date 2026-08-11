"""Sopres: 1-2 parameter kimerito vegigprobalasa.

A doksi kerese: "ha a parametereink kozott van tol-ig, akkor miert ne
csinalhatnank meg azt, hogy pl. csak az SMA-t 100→200-ig backtesteljuk".

⚠ A LEGFONTOSABB ALLITAS, amit ez a teszt vedelmez: a CSOPORTOSITOTT sopres
BITAZONOS a naiv ciklussal. A sopres a jel-parameterek szerint csoportosit, hogy
a jelolt-listat ne kelljen minden pontra ujraepiteni (26 epites 338 helyett) —
ez sebesseg-optimalizacio egy SZAMITAS koruli, es ha barhol elcsuszna, a
felhasznalo egy HAMIS gorbet latna. Egy hamis gorbe rosszabb, mint a hianyzo:
abbol valaszt parametert.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from core import applog
applog.harden_console()

from core import opt_plan as op
from core import sweep as sw
from strategy import get_strategy_by_name
from trading import backtest as bt

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ── 1. A RACS ERTEKEI ──────────────────────────────────────────────────────
check("egesz tartomany -> EGESZ ertekek",
      op.grid_values({"min": 50, "max": 100, "step": 10}) == [50, 60, 70, 80, 90, 100])
check("tort tartomany -> tort ertekek",
      op.grid_values({"min": 1.0, "max": 2.0, "step": 0.5}) == [1.0, 1.5, 2.0])
# ⚠ Ha egy egesz parameter (sma_period) tort erteket kapna, az indikator-motor
# vagy elszallna, vagy neman csonkolna — es a gorben ket szomszedos pont
# ugyanaz lenne.
check("az EGESZ jelleg megorzodik (nincs 50.0)",
      all(isinstance(v, int) for v in op.grid_values({"min": 50, "max": 70, "step": 10})))
check("a lebegopontos maradek nem szivarog (0,30000000000000004)",
      op.grid_values({"min": 0.1, "max": 0.4, "step": 0.1}) == [0.1, 0.2, 0.3, 0.4],
      str(op.grid_values({"min": 0.1, "max": 0.4, "step": 0.1})))
check("ervenytelen lepeskoz -> ures", op.grid_values({"min": 1, "max": 3, "step": 0}) == [])
check("grid_size == len(grid_values) (a felulet es a futas nem terhet el)",
      all(op.grid_size(s) == len(op.grid_values(s)) for s in
          ({"min": 50, "max": 300, "step": 10}, {"min": 0.5, "max": 3.0, "step": 0.2},
           {"min": 1, "max": 1, "step": 1})))


# ── 2. KOMBINACIOK ─────────────────────────────────────────────────────────
OCFG = {"sma_period": {"min": 100, "max": 120, "step": 10},
        "tp_rr_ratio": {"min": 1.0, "max": 2.0, "step": 0.5},
        "sl_atr_mult": {"min": 1.0, "max": 3.0, "step": 0.5}}
ROWS = [{"key": "sma_period", "skipped": False},
        {"key": "tp_rr_ratio", "skipped": False},
        {"key": "sl_atr_mult", "skipped": True}]

axes, cmbs = sw.combos(ROWS, OCFG)
check("a tengelyek a BEPIPALT kulcsok", [a[0] for a in axes] ==
      ["sma_period", "tp_rr_ratio"], str([a[0] for a in axes]))
check("a kombinaciok szama a racsok SZORZATA", len(cmbs) == 3 * 3, str(len(cmbs)))
check("minden kombinacio MINDEN tengelyt tartalmaz",
      all(set(c) == {"sma_period", "tp_rr_ratio"} for c in cmbs))
check("a kihagyott kulcs NEM kerul bele",
      all("sl_atr_mult" not in c for c in cmbs))
_none, _one = sw.combos([{"key": "x", "skipped": True}], OCFG)
check("0 bepipalt -> egy ures kombinacio (egyetlen futas)",
      _none == [] and _one == [{}])


# ── 3. A CSOPORTOSITAS — ez adja a sebesseget ─────────────────────────────
# ⚠ Ez az, amiert a sopres nem egy egyszeru for-ciklus: a vegrehajtasi
# parameterek UGYANAZT a jelolt-listat hasznaljak.
_g_exec = sw.group_by_signal([{"tp_rr_ratio": v} for v in (1.0, 1.5, 2.0)], "wpr_sma")
check("CSAK vegrehajtasi parameter -> EGYETLEN csoport (1 jelolt-lista)",
      len(_g_exec) == 1, f"{len(_g_exec)} csoport")
_g_sig = sw.group_by_signal([{"sma_period": s} for s in (100, 110, 120)], "wpr_sma")
check("jel-parameter -> ertekenkent kulon csoport", len(_g_sig) == 3,
      f"{len(_g_sig)} csoport")
_g_mix = sw.group_by_signal([{"sma_period": s, "tp_rr_ratio": t}
                             for s in (100, 110, 120) for t in (1.0, 1.5, 2.0)],
                            "wpr_sma")
check("vegyes racs -> a JEL-ertekek szama a csoportszam (3, nem 9)",
      len(_g_mix) == 3, f"{len(_g_mix)} csoport")
check("...es egy csoport a hozza tartozo OSSZES vegrehajtasi pontot viszi",
      all(len(g) == 3 for _k, g in _g_mix))
check("egyetlen kombinacio sem VESZ EL a csoportositasban",
      sum(len(g) for _k, g in _g_mix) == 9)


# ── 4. A LENYEG: a csoportositott sopres BITAZONOS a naivval ──────────────
rng = np.random.default_rng(31337)


def _bars(n, freq):
    px = 25000 + np.cumsum(rng.normal(0, 4.0, n))
    idx = pd.date_range("2026-01-01", periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"open": px, "high": px + np.abs(rng.normal(0, 3.0, n)),
                         "low": px - np.abs(rng.normal(0, 3.0, n)),
                         "close": px, "volume": 1.0}, index=idx)


M15 = _bars(1200, "15min")
M1 = _bars(1200 * 15, "1min")
PAIR = {"point_size": 0.01, "pv1_point": 1.0, "min_lot": 0.01, "lot_step": 0.01,
        "backtest_spread_points": 1.5, "sess_start": 0, "sess_end": 24}
TRADING = {"max_open_slots": 4, "account_risk_pct": 1.0,
           "daily_loss_limit_pct": 100.0, "daily_loss_limit_percent": 100.0}
BASE = {"sma_period": 200, "wpr_m15_period": 21, "wpr_m1_period": 21,
        "wpr_m15_sell_extreme": -20, "wpr_m15_buy_extreme": -80,
        "wpr_m15_sell_trigger": -40, "wpr_m15_buy_trigger": -60,
        "wpr_m1_sell_extreme": -20, "wpr_m1_buy_extreme": -80,
        "wpr_m1_trigger": -50, "sl_atr_mult": 2.0, "tp_rr_ratio": 1.0,
        "atr_period": 14, "atr_min_pct": 0.5, "atr_max_pct": 3.0,
        "atr_avg_ref": 10.0, "atr_baseline_bars": 0}
ST = get_strategy_by_name("wpr_sma")

_ocfg = {"sma_period": {"min": 150, "max": 250, "step": 50},
         "tp_rr_ratio": {"min": 1.0, "max": 2.0, "step": 0.5}}
_rows = [{"key": "sma_period", "skipped": False},
         {"key": "tp_rr_ratio", "skipped": False}]
_axes, _cmbs = sw.combos(_rows, _ocfg)
check("a merohoz eloall a racs (3 x 3)", len(_cmbs) == 9, str(len(_cmbs)))

_swept = sw.run("TEST", M15, M1, BASE, PAIR, TRADING, 10000.0, ST, _cmbs)

# NAIV referencia: minden pont sajat, teljes run_pair-rel (nincs gyorsitotar).
_naive = []
for c in _cmbs:
    r = bt.run_pair("TEST", M15, M1, {**BASE, **c}, PAIR, TRADING, 10000.0,
                    strategy=ST)
    _naive.append({**c, **sw.metrics_of(r, 10000.0)})


def _key(rows):
    return sorted((tuple(sorted((k, v) for k, v in r.items()
                                if k in ("sma_period", "tp_rr_ratio"))),
                   r["trades"], round(r["total_pnl"], 8),
                   round(r["max_drawdown"], 8), round(r["profit_factor"], 8))
                  for r in rows)


check("a CSOPORTOSITOTT sopres BITAZONOS a naiv ciklussal",
      _key(_swept) == _key(_naive),
      f"{len(_swept)} vs {len(_naive)} pont")
check("...es tenyleg szuletett kotes (a teszt ertelmes)",
      sum(r["trades"] for r in _swept) > 0,
      f"{sum(r['trades'] for r in _swept)} kotes osszesen")
check("minden racspont megvan az eredmenyben", len(_swept) == 9)


# ── 5. A legjobb pont ──────────────────────────────────────────────────────
_probe = [{"a": 1, "total_pnl": 10.0, "max_drawdown": 0.5, "note": ""},
          {"a": 2, "total_pnl": 50.0, "max_drawdown": 0.9, "note": ""},
          {"a": 3, "total_pnl": 99.0, "max_drawdown": 0.1, "note": "hiba"}]
check("a legjobb P&L nyer", sw.best(_probe)["a"] == 2)
# ⚠ A visszaesesnel a KISEBB a jobb — ha ezt elvetenenk, a felulet a
# LEGROSSZABB pontot jelolne meg "legjobbkent".
check("max_drawdown-nal a KISEBB a jobb",
      sw.best(_probe, "max_drawdown")["a"] == 1)
check("az elhasalt pont (note) NEM lehet legjobb",
      all(sw.best(_probe, m)["a"] != 3 for m in ("total_pnl", "max_drawdown")))
check("ha MINDEN pont elhasalt -> None",
      sw.best([{"a": 1, "total_pnl": 0.0, "note": "hiba"}]) is None)


# ── 6. A rajz szinskalaja: a NULLA a fordulopont ──────────────────────────
from dashboard import sweep_view as sv

_neg, _zero, _pos = "#ff0000", "#000000", "#00ff00"
check("pozitiv ertek a ZOLD fele",
      sv.heat_color(100, -100, 100, _neg, _zero, _pos) == "#00ff00")
check("negativ ertek a PIROS fele",
      sv.heat_color(-100, -100, 100, _neg, _zero, _pos) == "#ff0000")
check("a nulla a SEMLEGES", sv.heat_color(0, -100, 100, _neg, _zero, _pos) == "#000000")
# ⚠ Ha a skala a min…max KOZEPERE tenne a semlegest, egy csupa veszteseges racs
# fele ZOLDNEK latszana — es a felhasznalo ott keresne "jo tartomanyt", ahol
# csak a kevesbe rossz van.
_all_neg = sv.heat_color(-10, -100, -5, _neg, _zero, _pos)
check("csupa VESZTESEGES racsban egyetlen pont sem lesz zold",
      _all_neg.startswith("#") and int(_all_neg[3:5], 16) == 0, _all_neg)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

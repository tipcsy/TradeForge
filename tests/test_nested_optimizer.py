"""Beagyazott optimalizalas: kivul a JEL, belul a VEGREHAJTAS.

A `param_meta` besorolasa alapjan a kereses kettevalik. Ket dolgot kell
garantalni, es a ketto nem egyenrangu:

  1. A LAPOS ag valtozatlan. Ez a beallitas fut elesben ma — ha a refaktor
     elmozditja, az egesz eddigi optimalizalasi elozmeny ertelmezhetetlen lesz.
     Ezert a lapos ag ROGZITETT MAGGAL BITAZONOS onmagaval.

  2. A beagyazott ag TELJES parameter-keszletet ad vissza. A kulso trial csak a
     jel-dimenziokat ismeri; ha a vegrehajtasiak nem kerulnek at a belso
     study-bol, a mentett parameterek CSENDESEN az alapertekek lennenek — a
     felhasznalo azt hinne, optimalizalt beallitassal kereskedik.

⚠ Amit ez a teszt NEM allit: hogy a beagyazott kereses JOBB. Az empirikus
kerdes, a `tools/nested_ab.py` meri (holdouton, azonos idobol). Itt csak az
gepeszet helyesseget ellenorizzuk.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from core import applog
applog.harden_console()

# ⚠ A study/CSV a data/optimized_params-be menne — a teszt SOHA nem irhatja a
# valodi allomanyt. A PARAMS_DIR-t temp mappara teritjuk, MEG az optimizer
# importja elott (a path-helperek modul-szinten olvassak).
from core import params_store as ps
_TMP = Path(tempfile.mkdtemp(prefix="nested_test_"))
ps.PARAMS_DIR = _TMP

import optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)

from strategy import get_strategy_by_name
from strategy.settings import load_strategy_config, param_class, EXEC_PARAM
from ml import optimizer as opt

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ── A felosztas ────────────────────────────────────────────────────────────
ST = get_strategy_by_name("wpr_sma")
SCFG = load_strategy_config("wpr_sma")
OCFG = {**SCFG["optimizer"], "inner_trials": 3}
SIG, EXE = opt._param_split(ST, OCFG)

check("a hangolt kulcsok kettevalnak", bool(SIG) and bool(EXE),
      f"jel {len(SIG)} | vegrehajtas {len(EXE)}")
check("a ket halmaz DISZJUNKT", not (set(SIG) & set(EXE)))
_all = [k for k, v in OCFG.items() if isinstance(v, dict) and "min" in v]
check("egyetlen hangolt kulcs sem VESZ EL", sorted(SIG + EXE) == sorted(_all))
check("a vegrehajtasi oldal a besorolast koveti",
      all(param_class(SCFG, k) == EXEC_PARAM for k in EXE), str(EXE))

# ⚠ A kenyszerek MIND jel-parameterekre hivatkoznak — erre epul, hogy a kulso
# hurok mar a belso hurok ELOTT eldobhatja az ervenytelen jel-beallitast.
_cons_keys = set()
for _expr in (OCFG.get("constraints") or []):
    for _tok in _expr.replace("<", " ").replace(">", " ").replace("=", " ").split():
        if _tok in _all:
            _cons_keys.add(_tok)
check("MINDEN kenyszer csak jel-parameterre hivatkozik "
      "(kulonben a kulso szures hibas lenne)",
      not (_cons_keys & set(EXE)), str(_cons_keys & set(EXE)))


# ── _suggest_params(keys=...) ──────────────────────────────────────────────
_study = optuna.create_study(sampler=optuna.samplers.TPESampler(seed=1))
_base = {"alap_kulcs": 42}


def _obj(t):
    p = opt._suggest_params(t, OCFG, _base, keys=EXE)
    t.set_user_attr("p", p)
    return 0.0


_study.optimize(_obj, n_trials=1)
_p = _study.trials[0].user_attrs["p"]
check("keys=... : CSAK a kert kulcsokat suggeszti",
      set(_study.trials[0].params) == set(EXE),
      str(sorted(set(_study.trials[0].params) ^ set(EXE))))
check("keys=... : a base_params tobbi kulcsa MEGMARAD", _p.get("alap_kulcs") == 42)


# ── Vegponttol vegpontig, szintetikus adaton ───────────────────────────────
rng = np.random.default_rng(4242)


def _bars(n, freq):
    px = 25000 + np.cumsum(rng.normal(0, 5.0, n))
    idx = pd.date_range("2025-01-01", periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"open": px,
                         "high": px + np.abs(rng.normal(0, 4.0, n)),
                         "low":  px - np.abs(rng.normal(0, 4.0, n)),
                         "close": px, "volume": 1.0}, index=idx)


M15 = _bars(int(370 * 96), "15min")          # ~12 honap
M1 = _bars(int(370 * 96 * 15), "1min")
PAIR = {"point_size": 0.01, "pv1_point": 1.0, "min_lot": 0.01, "lot_step": 0.01,
        "backtest_spread_points": 1.5, "sess_start": 0, "sess_end": 24,
        "enabled": True}
TRADING = {"max_open_slots": 4, "account_risk_pct": 1.0,
           "daily_loss_limit_pct": 100.0, "daily_loss_limit_percent": 100.0}
BASE = {"sma_period": 200, "wpr_m15_period": 21, "wpr_m1_period": 21,
        "wpr_m15_sell_extreme": -20, "wpr_m15_buy_extreme": -80,
        "wpr_m15_sell_trigger": -40, "wpr_m15_buy_trigger": -60,
        "wpr_m1_sell_extreme": -20, "wpr_m1_buy_extreme": -80,
        "wpr_m1_sell_trigger": -50, "wpr_m1_buy_trigger": -50,
        "sl_atr_mult": 2.0, "tp_rr_ratio": 1.0,
        "atr_period": 14, "atr_min_pct": 0.5, "atr_max_pct": 3.0,
        "atr_avg_ref": 10.0, "atr_baseline_bars": 0}


def _run(nested, seed_reset=True):
    if seed_reset:
        # A study .db-t es a markereket toroljuk -> mindig FRISS futas
        for f in _TMP.rglob("*"):
            if f.is_file():
                f.unlink()
    return opt.optimize_pair_optuna(
        "TEST", M15, M1, OCFG, BASE, PAIR, TRADING, 10000.0, ST,
        n_trials=4, n_splits=2, train_months=6, test_months=2, nested=nested)


_flat_a = _run(False)
_flat_b = _run(False)
check("a LAPOS ag onmagaval BITAZONOS (rogzitett mag)",
      (_flat_a is None) == (_flat_b is None) and
      (_flat_a is None or _flat_a["params"] == _flat_b["params"]),
      "None" if _flat_a is None else "")

_nest = _run(True)
check("a beagyazott ag lefut es ad eredmenyt", _nest is not None)

if _nest:
    # ⚠ EZ A LENYEG: a vegrehajtasi kulcsok a BELSO study-bol jonnek. Ha
    # hianyoznanak, a mentett parameterek csendben az alapertekek lennenek.
    check("a beagyazott eredmeny MINDEN hangolt kulcsot tartalmaz",
          all(k in _nest["params"] for k in SIG + EXE),
          str([k for k in SIG + EXE if k not in _nest["params"]]))
    moved = [k for k in EXE if _nest["params"].get(k) != BASE.get(k)]
    check("a vegrehajtasi kulcsok TENYLEG a belso keresesbol jonnek "
          "(nem az alapertek)", bool(moved), f"elmozdult: {moved}")

# ── Ha nincs vegrehajtasi dimenzio, a beagyazas KIMARAD (nem hibazik) ──────
_ocfg_sig_only = {k: v for k, v in OCFG.items()
                  if not (isinstance(v, dict) and "min" in v and k in EXE)}
try:
    _r = opt.optimize_pair_optuna(
        "TEST", M15, M1, _ocfg_sig_only, BASE, PAIR, TRADING, 10000.0, ST,
        n_trials=2, n_splits=2, train_months=6, test_months=2, nested=True)
    check("nincs vegrehajtasi dimenzio -> lapos keresesre esik vissza (nem hal el)",
          True)
except Exception as ex:
    check("nincs vegrehajtasi dimenzio -> lapos keresesre esik vissza",
          False, f"{type(ex).__name__}: {ex}")

import shutil
shutil.rmtree(_TMP, ignore_errors=True)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

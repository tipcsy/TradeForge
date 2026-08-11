"""„MI FOG TORTENNI, ha megnyomom az OPT gombot?"

A felhasznaloi doksi (`Parameterek vs OPT vs Backtest`) legsulyosabb panasza nem
a sebesseg volt, hanem az atlathatatlansag:

    "Nem latom az idointervallumot · nem latom a lehetseges parametereket · nem
     tudom csak egyeseket optimalizalni · nem latom, melyik kapu mukodott."

⚠ A LEGFONTOSABB ALLITAS, amit ez a teszt vedelmez: a panel NEM sajat szamitas,
hanem a VALODI forrasok tukre. Egy kulon "kijelzo-logika" az elso
config-valtozasnal elcsuszna, es a felulet MAGABIZTOSAN hazudna — a felhasznalo
pedig ez alapjan indit el egy oras futast. A hibas szam rosszabb, mint a
hianyzo.

Ezert itt vegponttol vegpontig merunk: amit a panel mutat, azt teszi az
optimalizalo.
"""
import copy
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from core import applog
applog.harden_console()

from core import opt_plan as op
from core import gates as gt
from strategy import get_strategy_by_name
from strategy.settings import load_strategy_config

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


ST = get_strategy_by_name("wpr_sma")
OCFG = load_strategy_config("wpr_sma")["optimizer"]
SYM = "TEST"


def _cfg():
    return {"pairs": {SYM: {"point_size": 0.01}}, "optimizer": {"exec_gates": True}}


# ── 1. A KIHAGYAS: config-hazirend ─────────────────────────────────────────
c = _cfg()
check("alaphelyzetben semmi nincs kihagyva", op.skip_keys(c, SYM, "wpr_sma") == set())

op.set_skip_keys(c, SYM, "wpr_sma", ["sma_period", "tp_rr_ratio"])
check("a kihagyas visszaolvashato",
      op.skip_keys(c, SYM, "wpr_sma") == {"sma_period", "tp_rr_ratio"})
check("...es a PAR alatt el (par+strategia szintu)",
      "optimizer_skip" in c["pairs"][SYM])
check("mas strategiat NEM erint", op.skip_keys(c, SYM, "masik") == set())

# ⚠ A config csak az ELTERES-t rogzitheti: ures lista eseten a bejegyzes KIKERUL.
# Kulonben egy ures lista "beallitasnak" latszana, es egy kesobbi
# alapertek-valtozas neman hatastalan maradna ra.
op.set_skip_keys(c, SYM, "wpr_sma", [])
check("ures kihagyas -> a bejegyzes KIKERUL a configbol (nem ures lista marad)",
      "optimizer_skip" not in c["pairs"][SYM], str(c["pairs"][SYM]))


# ── 2. A parameter-sorok ───────────────────────────────────────────────────
rows = op.param_rows(_cfg(), SYM, "wpr_sma", OCFG, current={"sma_period": 123})
check("minden hangolt kulcsra van sor",
      len(rows) == len(op.tuned_specs(OCFG)), f"{len(rows)} sor")
check("a sorok osztalyozva vannak (jel/vegrehajtas)",
      all(r["cls"] in ("signal", "execution") for r in rows))
check("a jelenlegi ertek atjon", next(r for r in rows if r["key"] == "sma_period")
      ["current"] == 123)
_sma = next(r for r in rows if r["key"] == "sma_period")
check("a racs-meret helyes (sma 50..300/10 -> 26)", _sma["values"] == 26,
      str(_sma["values"]))

_c2 = _cfg(); op.set_skip_keys(_c2, SYM, "wpr_sma", ["sma_period"])
_rows2 = op.param_rows(_c2, SYM, "wpr_sma", OCFG)
check("a kihagyott kulcs sora JELOLT",
      next(r for r in _rows2 if r["key"] == "sma_period")["skipped"])
check("a kihagyott kulcs KIESIK a keresesi terbol",
      op.search_space(_rows2) < op.search_space(rows),
      f"{op.search_space(rows):,} -> {op.search_space(_rows2):,}")


# ── 3. Az ABLAKOK ugyanabbol a fuggvenybol jonnek, mint a futas ────────────
rng = np.random.default_rng(11)
_n = 400 * 96
_px = 25000 + np.cumsum(rng.normal(0, 3.0, _n))
M15 = pd.DataFrame({"open": _px, "high": _px + 2, "low": _px - 2, "close": _px,
                    "volume": 1.0},
                   index=pd.date_range("2025-01-01", periods=_n, freq="15min",
                                       tz="UTC"))
plan = op.build(_cfg(), SYM, ST, OCFG, df_m15=M15)
check("a terv ad walk-forward ablakokat", len(plan["windows"]) > 0,
      f"{len(plan['windows'])} ablak")

from ml.optimizer import _walk_forward_windows
_real = _walk_forward_windows(M15, plan["wf"]["splits"],
                              plan["wf"]["train_months"], plan["wf"]["test_months"])
check("az ablakok AZONOSAK azzal, amit az optimalizalo hasznal",
      [(w["train_start"], w["test_start"], w["test_end"]) for w in _real] ==
      [(w["train_start"], w["test_start"], w["test_end"]) for w in plan["windows"]])

# ⚠ A wf-kulcsok NEM a fo configbol jonnek, hanem a STRATEGIA optimizer
# szekciojabol (`wf_n_splits`), az exec_gates viszont MOTOR-kulcs. Ha ezt
# elvetenenk, a panel mas szamot mutatna, mint amivel a futas indul.
_oc = {**OCFG, "wf_n_splits": 3, "wf_train_months": 4, "wf_test_months": 1}
_p3 = op.build(_cfg(), SYM, ST, _oc, df_m15=M15)
check("a wf beosztas a STRATEGIA optimizer szekciojabol jon",
      (_p3["wf"]["splits"], _p3["wf"]["train_months"], _p3["wf"]["test_months"])
      == (3, 4, 1), str(_p3["wf"]))
check("...es tenyleg annyi ablak lesz", len(_p3["windows"]) == 3,
      str(len(_p3["windows"])))


# ── 4. A KAPUK: ha az exec_gates KI van, a panel ne mutasson aktiv kaput ───
# Ez a legfelrevezetobb allapot: a kapuk latszolag elnek (a kapu-panel mutatja
# oket), de az optimalizalas nem tud roluk — a kapott parameterek olyan
# vilagbol jonnek, ami elesben nem letezik.
_cg = _cfg()
_cg["pairs"][SYM]["gates"] = {gt.SPREAD: {"wpr_sma": gt.EFFECT_BLOCK}}
_on = op.build(_cg, SYM, ST, OCFG, df_m15=M15)
check("bekapcsolt exec_gates mellett latszik az aktiv kapu",
      _on["gate_effects"][gt.SPREAD] == gt.EFFECT_BLOCK)
_cg["optimizer"]["exec_gates"] = False
_off = op.build(_cg, SYM, ST, OCFG, df_m15=M15)
check("KIKAPCSOLT exec_gates -> a panel EGYETLEN kaput sem mutat aktivnak",
      all(e == gt.EFFECT_NONE for e in _off["gate_effects"].values()))
check("...es a terv jelzi is, hogy a kapuk nincsenek modellezve",
      _off["exec_gates"] is False)


# ── 5. VEGPONTTOL VEGPONTIG: a kihagyas TENYLEG hat a keresesre ───────────
# A panel pipaja hazudna, ha az optimalizalo megis sorsolna a kulcsot.
from core import params_store as ps
ps.PARAMS_DIR = Path(tempfile.mkdtemp(prefix="optplan_test_"))
import optuna
optuna.logging.set_verbosity(optuna.logging.ERROR)
from ml import optimizer as _opt

M1 = pd.DataFrame({"open": np.repeat(_px, 15), "high": np.repeat(_px, 15) + 2,
                   "low": np.repeat(_px, 15) - 2, "close": np.repeat(_px, 15),
                   "volume": 1.0},
                  index=pd.date_range("2025-01-01", periods=_n * 15, freq="1min",
                                      tz="UTC"))
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

_ce = _cfg()
op.set_skip_keys(_ce, SYM, "wpr_sma", ["sma_period", "tp_rr_ratio"])
_res = _opt.optimize_pair_optuna(SYM, M15, M1, OCFG, BASE, PAIR, TRADING,
                                 10000.0, ST, n_trials=3, n_splits=2,
                                 train_months=6, test_months=2, cfg=_ce)
if _res:
    check("a KIHAGYOTT kulcs az alapertekén marad (nem sorsolta)",
          _res["params"]["sma_period"] == BASE["sma_period"] and
          _res["params"]["tp_rr_ratio"] == BASE["tp_rr_ratio"],
          f"sma={_res['params']['sma_period']} tp={_res['params']['tp_rr_ratio']}")
    _moved = [k for k in op.tuned_specs(OCFG)
              if k not in ("sma_period", "tp_rr_ratio")
              and _res["params"].get(k) != BASE.get(k)]
    check("...mikozben a TOBBI kulcsot hangolta (a teszt ertelmes)",
          bool(_moved), f"elmozdult: {len(_moved)} kulcs")
else:
    check("az optimalizalas ad eredmenyt a szintetikus adaton", False,
          "None jott vissza")

import shutil
shutil.rmtree(ps.PARAMS_DIR, ignore_errors=True)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

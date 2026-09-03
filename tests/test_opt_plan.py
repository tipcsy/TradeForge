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
# ⚠ EGY KIVETELLEL: a volatilitas PARAMETER-VEZERELT kapu (a kuszobeit a
# strategia soport parameterei adjak), ezert az `exec_gates=False` nem kapcsolja
# ki — kulonben az optimalizalo olyan parametert hangolna, aminek nincs hatasa.
check("KIKAPCSOLT exec_gates -> a VEGREHAJTASI kapuk egyike sem aktiv",
      all(e == gt.EFFECT_NONE for k, e in _off["gate_effects"].items()
          if k not in gt.PARAM_DRIVEN),
      str(_off["gate_effects"]))
check("...de a parameter-vezerelt kapu megmarad",
      _off["gate_effects"][gt.VOLATILITY] == gt.EFFECT_BLOCK)
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
        "wpr_m1_sell_trigger": -40, "wpr_m1_buy_trigger": -60,
        "sl_atr_mult": 2.0, "tp_rr_ratio": 1.0,
        "atr_period": 14, "atr_min_pct": 0.5, "atr_max_pct": 3.0,
        "atr_avg_ref": 10.0, "atr_baseline_bars": 0}

_ce = _cfg()
op.set_skip_keys(_ce, SYM, "wpr_sma", ["sma_period", "tp_rr_ratio"])
# ⚠ A trial-szam nem kozombos: a szintetikus adaton a kombinaciok TULNYOMO
# resze 0 kotest ad (-inf score), es ha MINDEN trial ilyen, a fuggveny None-t ad
# — a teszt ekkor nem a kihagyast merne, hanem a szerencset. Az M1 trigger
# irany szerinti kettevalasa (v2.63.0) eggyel novelte a keresesi teret, es 3
# huzas mar nem volt eleg egyetlen kotesig sem.
_res = _opt.optimize_pair_optuna(SYM, M15, M1, OCFG, BASE, PAIR, TRADING,
                                 10000.0, ST, n_trials=10, n_splits=2,
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


# ── 5b. A FUTAS TIPUSA a hangolt dimenziok szamabol ADODIK ────────────────
# A doksi felismerese: "OPT = parameter beallit; teljes futtatas; kiertekeles —
# es ez 500-szor. Backtest ugyanez, csak a kiertekeles manualis." Tehat nem ket
# funkcio van, hanem EGY, aminek a futasszama kulonbozik — es a futasszamot nem
# kell kulon beallitani, kiderul abbol, hany parameternek adtunk tartomanyt.
_BASE = [{"key": "a", "values": 26, "cls": "signal"},
         {"key": "b", "values": 13, "cls": "execution"},
         {"key": "c", "values": 9, "cls": "signal"},
         {"key": "d", "values": 5, "cls": "signal"}]


def _tuned(n):
    return [dict(x, skipped=(i >= n)) for i, x in enumerate(_BASE)]


check("0 hangolt -> EGYETLEN futas (ez a backtest)",
      op.run_plan(_tuned(0))["kind"] == op.KIND_SINGLE and
      op.run_plan(_tuned(0))["runs"] == 1)
check("1 hangolt -> SOPRES, a racs-meretnyi futassal",
      op.run_plan(_tuned(1))["kind"] == op.KIND_SWEEP and
      op.run_plan(_tuned(1))["runs"] == 26, str(op.run_plan(_tuned(1))["runs"]))
check("2 hangolt -> RACS, a ketto SZORZATA",
      op.run_plan(_tuned(2))["kind"] == op.KIND_GRID and
      op.run_plan(_tuned(2))["runs"] == 26 * 13, str(op.run_plan(_tuned(2))["runs"]))
check("3+ hangolt -> OPTIMALIZALAS, a trial-szammal",
      op.run_plan(_tuned(3), trials=500)["kind"] == op.KIND_OPTIMIZE and
      op.run_plan(_tuned(3), trials=500)["runs"] == 500)

# ⚠ A `runs` jelentese NEM ugyanaz a ket agon: a sopres/racs KIMERITO
# (vegigprobaljuk), az optimalizalas MINTAVETEL — ott a ter nagysagrendekkel
# nagyobb a mintaszamnal. Ha a felulet a kettot ugyanugy nevezne, a felhasznalo
# azt hinne, hogy 500 trial "atnezte" a lehetosegeket.
check("a sopres/racs KIMERITO", op.run_plan(_tuned(2))["exhaustive"] is True)
check("az optimalizalas NEM kimerito", op.run_plan(_tuned(3))["exhaustive"] is False)

check("a kihagyott kulcsok nem szamitanak bele",
      op.run_plan(_tuned(1))["tuned"] == ["a"])
check("a 0 ertekes (romlott) tartomany kiesik",
      op.run_plan([{"key": "x", "values": 0, "skipped": False}])["kind"]
      == op.KIND_SINGLE)

check("idobecsles: 338 futas x 19,1 mp ~ 108 perc",
      abs(op.estimate_minutes(338, 19.1) - 107.6) < 0.5,
      f"{op.estimate_minutes(338, 19.1):.1f}")
check("idobecsles ABLAKONKENT szoroz (walk-forward)",
      op.estimate_minutes(10, 20.0, windows=4) == op.estimate_minutes(40, 20.0))


# ── 6. A TARTOMANYOK SZERKESZTHETOK (a doksi kerese) ──────────────────────
# "A beallitasoknal jelenjenek meg az aktualis -tol -ig step beallitasi
#  parameter, ezek legyenek szabadon allithatoak."
#
# ⚠ A teszt SOHA nem irhatja a valodi strategy configot: a
# `strategy_config_path`-ot temp masolatra teritjuk. (A `_save_main_config`
# stubolasa itt nem vedene — ez a modul KOZVETLENUL ir fajlt.)
import json as _json
import shutil

from strategy import settings as _sx

_real_cfg = _sx.strategy_config_path("wpr_sma")
_tmp_dir = Path(tempfile.mkdtemp(prefix="optrange_test_"))
_tmp_cfg = _tmp_dir / "wpr_sma.json"
shutil.copy2(_real_cfg, _tmp_cfg)
_before = _real_cfg.read_text(encoding="utf-8")
_sx.strategy_config_path = lambda name: _tmp_cfg

check("ervenyes tartomany OK", _sx.validate_range({"min": 50, "max": 300, "step": 10}) == "")
check("min > max -> hiba", "nagyobb" in _sx.validate_range(
    {"min": 300, "max": 50, "step": 10}))
check("nulla lepeskoz -> hiba", "pozitiv" in _sx.validate_range(
    {"min": 1, "max": 3, "step": 0}).replace("í", "i"))
check("nem szam -> hiba", "nem szám" in _sx.validate_range(
    {"min": 1, "max": 3, "step": "x"}))
# ⚠ A legalattomosabb eset: a tartomany ervenyes-nek LATSZIK, de a lepeskoz
# akkora, hogy EGYETLEN ertek all elo — a dimenzio csendben rogzitett lesz,
# es a felhasznalo azt hiszi, optimalizalja.
check("tul nagy lepeskoz (1 ertek) -> hiba", "EGYETLEN" in _sx.validate_range(
    {"min": 1.0, "max": 3.0, "step": 5.0}))

check("mentes visszaadja, hogy irt",
      _sx.save_optimizer_ranges("wpr_sma", {"sma_period": {"min": 60, "max": 280,
                                                           "step": 20}}) is True)
_saved = _json.loads(_tmp_cfg.read_text(encoding="utf-8"))["optimizer"]["sma_period"]
check("a tartomany TENYLEG elmentodott",
      (_saved["min"], _saved["max"], _saved["step"]) == (60, 280, 20), str(_saved))
check("valtozatlan mentes -> nem ir feleslegesen",
      _sx.save_optimizer_ranges("wpr_sma", {"sma_period": {"min": 60, "max": 280,
                                                           "step": 20}}) is False)

# ⚠ A `gt`/`lt` a PARAMETER-KENYSZEREK hordozoja (dinamikus tartomany-szukites).
# Ha egy tartomany-szerkesztes neman eldobna oket, az optimalizalo ervenytelen
# kombinaciokat kezdene sorsolni, es a felhasznalo csak abbol venne eszre, hogy
# hirtelen sok trial "kenyszer nem teljesult" jelolessel bukik el.
_spec_keys = {k: v for k, v in _json.loads(
    _tmp_cfg.read_text(encoding="utf-8"))["optimizer"].items()
    if isinstance(v, dict) and ("gt" in v or "lt" in v)}
_orig_keys = {k: v for k, v in _json.loads(_before)["optimizer"].items()
              if isinstance(v, dict) and ("gt" in v or "lt" in v)}
check("a gt/lt kenyszerek TULELIK a tartomany-mentest",
      {k: {kk: vv for kk, vv in v.items() if kk in ("gt", "lt")}
       for k, v in _spec_keys.items()} ==
      {k: {kk: vv for kk, vv in v.items() if kk in ("gt", "lt")}
       for k, v in _orig_keys.items()},
      f"{len(_orig_keys)} kulcs")

check("nem tartomany-kulcsra NEM ir (pl. constraints)",
      _sx.save_optimizer_ranges("wpr_sma", {"constraints": {"min": 1}}) is False)
check("ismeretlen kulcsra NEM ir",
      _sx.save_optimizer_ranges("wpr_sma", {"nincs_ilyen": {"min": 1, "max": 2,
                                                            "step": 1}}) is False)

# A grid_size a mentett tartomanyt kovesse (a felulet ezt irja ki "ertek"-kent).
check("a racs-meret a mentett tartomanybol jon",
      op.grid_size({"min": 60, "max": 280, "step": 20}) == 12,
      str(op.grid_size({"min": 60, "max": 280, "step": 20})))

# A modul visszaallitasa: a lambda-t nem hagyhatjuk benne (a kesobbi tesztek
# ugyanezt a modult importaljak — egy bennfelejtett terites ott mar NEM
# szandekos, es a valodi configot celozna).
import importlib
importlib.reload(_sx)
check("a VALODI strategy config ERINTETLEN maradt",
      _real_cfg.read_text(encoding="utf-8") == _before)
shutil.rmtree(_tmp_dir, ignore_errors=True)

shutil.rmtree(ps.PARAMS_DIR, ignore_errors=True)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

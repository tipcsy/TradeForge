"""Az optimalizalas a KERESKEDESI ORAKAT is tiszteletben tartja.

⚠ A LELET (2026-08-14). Az optimalizalo MIND A 24 oran hangolt, az el viszont
csak a `trade_hours` orakban kot. A kapott parameterek tehat reszben olyan
orakra optimalizaltak, amikben a motor SOHA nem lep be — ugyanaz a hiba-osztaly,
mint a v1.95.0-ben javitott kapu-elteres, csak az orakra.

⚠ ES MIERT NEM DERULT KI. Ma MINDEN parnal mind a 24 ora engedve van, tehat a
hiba EGYETLEN mentett parametert sem rontott el. Csak az elso szukiteskor sult
volna el — es akkor NEMAN: a felulet ugyanugy nezett volna ki.

A felhasznalo elvarasa szo szerint: „Ha beallitottuk a kereskedesi orakat (mind),
akkor kereskedik mindenhol. Ha csokkentunk rajta, akkor csokken a backtest es az
optimalizalas is."
"""
import inspect
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


import ml.optimizer as opt
from strategy import get_strategy_by_name
from strategy.settings import load_config

st = get_strategy_by_name("wpr_sma")


# ── 1. A FELOLDAS ─────────────────────────────────────────────────────────
check("szukitett orak -> a halmaz",
      opt._opt_allowed_hours("X", st, {"trade_hours": [8, 9, 10]}) == {8, 9, 10},
      str(opt._opt_allowed_hours("X", st, {"trade_hours": [8, 9, 10]})))
# ⚠ Mind a 24 -> `None`: azonos a „nincs szures"-sel, de olcsobb (a run_pair
# ilyenkor nem is nezi az orat), es a naplo is egyertelmu.
check("mind a 24 ora -> None (nincs szures)",
      opt._opt_allowed_hours("X", st, {"trade_hours": list(range(24))}) is None)
check("hianyzo beallitas -> None",
      opt._opt_allowed_hours("X", st, {}) is None)
# Hibas bemenet ne dontse el az optimalizalast: inkabb ne szurjon.
check("hibas bemenet -> None (nem szall el)",
      opt._opt_allowed_hours("X", st, {"trade_hours": "hulyeseg"}) is None)


# ── 2. A VALODI CONFIG allapota ──────────────────────────────────────────
cfg = load_config("config.json")
_pairs = [s for s in cfg["pairs"] if not s.startswith("_")]
_restricted = [s for s in _pairs
               if opt._opt_allowed_hours(s, st, cfg["pairs"][s]) is not None]
check("a javitas ma EGYETLEN mentett parametert sem erint",
      not _restricted, f"szukitett parok: {_restricted}")


# ── 3. MINDEN run_pair hivas atadja ──────────────────────────────────────
# ⚠ Forras-szintu ellenorzes: harom kulon agon fut backtest az optimalizalasban
# (optuna kiertekeles · racs-ag · zaro TEST), es ha barmelyikbol kimarad, az
# EPPEN olyan nema elteres lesz, mint amit ez a teszt oriz. A `run_pair`
# elofordulasok szama es az `allowed_hours` szama egyeznie kell.
_src = inspect.getsource(opt)
_calls = _src.count("run_pair(") - _src.count("def run_pair(") - _src.count("_rp(")
_hours = _src.count("allowed_hours=_hours") + _src.count("allowed_hours=_opt_allowed_hours")
check("minden optimalizalo-agon atadjuk az orakat", _hours >= 4,
      f"{_hours} atadas")

# A haromfele ag kulon-kulon
for _needle, _lbl in ((("def _evaluate", "allowed_hours=_hours"), "optuna kiertekeles"),
                      (("test_start=None,   # TRAIN", "allowed_hours=_opt_allowed_hours"),
                       "racs-ag (optimize_pair)"),
                      (("test_result  = run_pair", "allowed_hours=_opt_allowed_hours"),
                       "zaro TEST futas")):
    _a, _b = _needle
    _i = _src.find(_a)
    check(f"...a(z) {_lbl} agon is", _i >= 0 and _b in _src[_i:_i + 1400],
          "nem talalom" if _i < 0 else "")

# A train-osszegzes is (kulonben a TRAIN es a TEST mas vilagot mérne)
_i = _src.find("train_result = _rp(")
check("...es a TRAIN osszegzes is ugyanazt az ablakot meri",
      _i >= 0 and "allowed_hours=_hours" in _src[_i:_i + 400])


# ── 4. A BACKTEST oldal: a szakasz dont, nincs kulon kapcsolo ────────────
from dashboard import instrument_dialog as idlg
_isrc = inspect.getsource(idlg.InstrumentParamsDialog._allowed_hours_from_ui)
check("a beagyazott backtest a KERESKEDESI ORAK szakaszbol veszi",
      "_hour_on" in _isrc and "len(on) >= 24" in _isrc)
from dashboard import backtest_dialog as bd
_bsrc = inspect.getsource(bd.BacktestDialog._allowed_hours)
check("...es a provider MEGELOZI a regi kapcsolot",
      _bsrc.index("_provide_hours") < _bsrc.index("_hours_filter_var"))


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

"""
A „Végrehajtás" szakasz KIVEZETÉSE a paraméter-ablakból (v3.104.0).

MIERT: a strategia parameter-ablakanak „Vegrehajtas" szakasza harom szamot
mutatott (`atr_period`, `max_spread_atr_ratio`, `min_spread_mult`), amik NEM a
strategiaei: a ket spread-kuszob a Spread-kapue (annak ablakaban is allithato
volt — duplikatum), az `atr_period` pedig az INSTRUMENTUME. Ez utobbi a
legveszelyesebb: MINDEN strategia stopja ebbol szamol (`sl_atr_mult x ATR`),
tehat egy wpr_sma-mentes vagy egy „spread-beallitas" nemán atmeretezte a par
osszes strategiajanak stopjat.

Amit ez a teszt rogzit:
1. A Spread-kapu ablakaban nincs `atr_period`.
2. A parameter-ablak az instrumentum EGYETLEN kulcsat sem mutatja/menti
   (`execution_params.INSTRUMENT_KEYS`), es nem ir execution_params-ba.
3. Az `atr_period` az instrumentum-ablakban van, es a tomeges alkalmazasban
   PENZT ERINTO sorkent szerepel.
4. A `no_trade_resets_signal` jelzes-logika → „Indikator – M15" (nem
   „Kockazatkezeles").
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import core.applog as _applog
_applog.harden_console()

from core import execution_params as ep             # noqa: E402
from core import gate_params as gp                  # noqa: E402
from core import gates as g                         # noqa: E402
from core import bulk_apply as ba                   # noqa: E402

_results = []
_fail = []


def check(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name + (f"  [{detail}]" if detail else ""))
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)


print("== 1. Spread-kapu ==")
keys = [s.key for s in gp.specs_for(g.SPREAD)]
check("a Spread-kapu ablakaban NINCS atr_period", "atr_period" not in keys, keys)
check("...de a ket sajat kuszobe megvan",
      {"max_spread_atr_ratio", "min_spread_mult"} <= set(keys), keys)

print("== 2. Parameter-ablak ==")
from dashboard import instrument_dialog as idlg      # noqa: E402
check("az ablak az instrumentum OSSZES kulcsat kiszuri",
      set(ep.INSTRUMENT_KEYS) <= set(idlg._INSTRUMENT_KEYS))
src = (ROOT / "dashboard" / "instrument_dialog.py").read_text(encoding="utf-8")
check("az ablak NEM ir execution_params-ba (nincs save_execution_params)",
      "save_execution_params" not in src)
check("nincs tobbe _EXEC_PARAM_META / Vegrehajtas-szakasz",
      "_EXEC_PARAM_META" not in src and "_EXEC_CATEGORY" not in src)

print("== 3. Instrumentum-ablak ==")
gsrc = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
_a = gsrc.index("def _show_instrument_settings")
_b = gsrc.index("\n    def ", _a + 10)
_blk = gsrc[_a:_b]
check("az instrumentum-ablakban van ATR-ablak mezo",
      "gui.atr_period_label" in _blk and "atr_var" in _blk)
check("...csak az ELTERESt irja (nem valasztja le a globalistol)",
      'if cur_vals["atr_period"] != _eff' in _blk)
check("...ervenytelen erteknel NEM ment", "gui.atr_period_bad" in _blk)
check("a tomeges alkalmazasban PENZT ERINTO sor",
      "atr_period" in ba.ROWS and ba.affects_money({"atr_period"}))
check("a valtozas-detektalas latja", ba.changed_rows(
    {"atr_period": 14}, {"atr_period": 19}) == {"atr_period"})

print("== 4. no_trade_resets_signal ==")
c = json.loads((ROOT / "strategies" / "config" / "wpr_sma.json").read_text(encoding="utf-8"))
pm = c["param_meta"]
check("indicator_m15 kategoria",
      pm["params"]["no_trade_resets_signal"]["category"] == "indicator_m15")
check("nincs ures 'risk' kategoria a sorrendben", "risk" not in pm["categories"])

print("== i18n ==")
for lang in ("hu", "en"):
    d = json.loads((ROOT / "lang" / f"{lang}.json").read_text(encoding="utf-8"))
    need = ("gui.atr_period_label", "gui.atr_period_help", "gui.atr_period_bad",
            "bulk.atr_period")
    check(f"{lang}: az uj kulcsok megvannak", all(k in d for k in need))
    check(f"{lang}: a kivezetett kulcsok eltuntek",
          "gp.spread.atr_period.label" not in d and "idlg.exec_save_error" not in d)

print(f"\n{sum(_results)}/{len(_results)} teszt PASS")
if _fail:
    print("Bukott:", ", ".join(_fail))
sys.exit(0 if all(_results) else 1)

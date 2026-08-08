"""
A backtest-ablak jelezze, ha belelog a modell TANITASI idoszakaba.

Miert kell: egy tanult modell a sajat tanito idoszakan nem elorejelez, hanem
EMLEKEZIK. Merve (2026-08-08, a mentett ml_ai modellek):

    AUC a tanitoadaton   0,87-0,92
    AUC friss adaton     0,48-0,56      (ermefeldobas)
    BTCUSD talalati arany  70,4% -> 26,2%  pontosan a tanitasi hataron

Egy 1000$ -> 14 398$ eredmeny ezert ugyanugy nezett ki, mint egy valodi. A
figyelmeztetes ezt teszi lathatova; a szabaly-alapu wpr_sma-nal nincs tanitasi
ablak, tehat ott NEM szabad riogatni.
"""

import json
import pathlib
import sys
import time
import tkinter as tk

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import core.applog as _applog
_applog.harden_console()

from core import training_overlap as _to        # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
_results = []
_fail = []


def check(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name + (f"  [{detail}]" if detail else ""))
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)


# ---------------------------------------------------------------------------
print("== A szamolas ==")

ov = _to.overlap("2025-01-01", "2025-12-31", "2024-01-01", "2025-07-01")
check("reszleges atfedes ~50%", 0.45 < ov["pct"] < 0.55, f"{ov['pct']:.3f}")

ov_full = _to.overlap("2025-01-01", "2025-06-30", "2024-01-01", "2026-01-01")
check("teljes atfedes = 100%", abs(ov_full["pct"] - 1.0) < 1e-9)

ov_none = _to.overlap("2026-01-01", "2026-06-30", "2024-01-01", "2025-12-31")
check("nincs atfedes = 0%", ov_none["pct"] == 0.0)

check("hatarosan erintkezo ablak sem atfedes",
      _to.overlap("2025-07-01", "2025-12-31", "2024-01-01", "2025-07-01")["pct"] < 0.01)
check("hianyos datum -> ures", _to.overlap(None, "2025-01-01", "a", "b") == {})
check("forditott ablak -> ures", _to.overlap("2026-01-01", "2025-01-01",
                                             "2024-01-01", "2025-01-01") == {})

# Idozona: a modell meta-ja tz-aware, a mezo nem — nem szabad elszallnia
ov_tz = _to.overlap("2025-01-01", "2025-12-31",
                    "2024-01-01 00:00:00+00:00", "2025-07-01 12:00:00+00:00")
check("tz-aware es naiv datum keverheto", 0.45 < ov_tz["pct"] < 0.55,
      f"{ov_tz['pct']:.3f}")

check("severity: none", _to.severity(0.0) == "none")
check("severity: partial", _to.severity(0.5) == "partial")
check("severity: full", _to.severity(0.95) == "full")

check("nincs atfedes -> nincs uzenet", _to.message(ov_none) == "")
check("ures atfedes -> nincs uzenet", _to.message({}) == "")
m = _to.message(ov)
check("az uzenet kiirja a szazalekot es a hatart",
      "%" in m and "2025-07-01" in m, m[:70])
check("teljes atfedesnel erosebb a szoveg",
      "NEM mond" in _to.message(ov_full), _to.message(ov_full)[:60])

# ---------------------------------------------------------------------------
print("== A strategia-varrat ==")
from strategy import get_strategy_by_name                 # noqa: E402
from strategy.settings import config_for_strategy         # noqa: E402
from strategy.base import Strategy                        # noqa: E402

check("az alap Strategy ad training_window-t", hasattr(Strategy, "training_window"))

raw = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
SYM = "EURUSD"

wpr = get_strategy_by_name("wpr_sma")
check("a szabaly-alapu strategianak NINCS tanitasi ablaka",
      wpr.training_window(SYM, config_for_strategy(raw, "wpr_sma")) is None)

mla = get_strategy_by_name("ml_ai")
cfg_ml = config_for_strategy(raw, "ml_ai")
win = mla.training_window(SYM, cfg_ml)
_has_model = (ROOT / "data" / "models" / "ml_ai" / f"{SYM}.pkl").exists()
if _has_model:
    check("az ml_ai visszaadja a modell tanitasi ablakat", win is not None)
    if win:
        check("az ablak rendezett (kezdet < veg)", win[0] < win[1],
              f"{win[0]} .. {win[1]}")
        # A user eredeti ablaka: 2025-02-03 .. 2026-08-03 -> jelentos atfedes
        o = _to.for_strategy(mla, SYM, cfg_ml, "2025-02-03", "2026-08-03")
        check("a user ablaka nagyresze in-sample", o.get("pct", 0) > 0.5,
              f"{100*o.get('pct',0):.0f}%")
        # A tanitas UTANI ablak legyen tiszta
        after = str((win[1] + __import__("pandas").Timedelta(days=1)).date())
        o2 = _to.for_strategy(mla, SYM, cfg_ml, after, "2026-08-03")
        check("a tanitas utani ablakra NINCS figyelmeztetes",
              _to.message(o2) == "", f"kezdet={after}")
else:
    print("  (kihagyva: nincs ml_ai modell)")

check("wpr_sma-ra a for_strategy ures",
      _to.for_strategy(wpr, SYM, config_for_strategy(raw, "wpr_sma"),
                       "2025-02-03", "2026-08-03") == {})

# ---------------------------------------------------------------------------
print("== A Backtest-ablakban ==")
root = tk.Tk()
root.withdraw()
try:
    from dashboard.backtest_dialog import BacktestDialog
    for name, expect_warning in (("ml_ai", _has_model), ("wpr_sma", False)):
        pf = ROOT / "data" / "optimized_params" / name / f"{SYM}.json"
        if not pf.exists():
            continue
        cfg = config_for_strategy(raw, name)
        params = json.loads(pf.read_text(encoding="utf-8"))["params"]
        d = BacktestDialog(root, SYM, cfg, get_strategy_by_name(name), params,
                           cfg["pairs"][SYM], None,
                           ("Segoe UI", 11, "bold"), ("Segoe UI", 9))
        for _ in range(80):
            root.update()
            time.sleep(0.05)
            if d._start_var.get():
                break
        d._start_var.set("2025-02-03")
        d._end_var.set("2026-08-03")
        root.update()
        txt = d._train_lbl.cget("text")
        check(f"{name}: {'van' if expect_warning else 'NINCS'} figyelmeztetes",
              bool(txt) == bool(expect_warning), txt[:60] or "(ures)")
        if expect_warning:
            # A datum megvaltoztatasa AZONNAL frissitse (nem futtatas utan)
            d._start_var.set("2026-05-01")
            root.update()
            check(f"{name}: tiszta idoszakra eltunik",
                  d._train_lbl.cget("text") == "",
                  d._train_lbl.cget("text")[:50] or "(ures)")
        d.win.destroy()
        root.update()
finally:
    root.destroy()

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)

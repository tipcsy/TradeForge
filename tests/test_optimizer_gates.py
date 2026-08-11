"""ÉL-PARITÁS: az optimalizáló ugyanazokat a VÉGREHAJTÁSI kapukat jarja, mint az el.

A LELET (2026-07-29, javitva v1.95.0): az `ml/optimizer.py` MINDHAROM `run_pair`-
hivasa `cfg` es `exec_gates` NELKUL ment, a `run_pair` viszont csak
`exec_gates=True` mellett epiti meg a spread-kaput es a TF-egyuttallas kaput. Az
el mindkettot alkalmazza.

  -> a `data/optimized_params/` MINDEN mentett keszlete kapu NELKULI vilagban lett
     hangolva, majd kapuzo motorba kerult. Az optimalizalo olyat optimalizalt, ami
     elesben sosem fut.

Ez okozta a felhasznaloi bejelentest is: „ha betoltok egy trials-sort es lefuttatom
a backtestet, NEM ugyanazt az eredmenyt hozza ki" — a Backtest-ablak ugyanis alapbol
KAPUZ, az optimalizalo pedig nem kapuzott.

A hiba NEMA volt: sem a naplo, sem a mentett JSON nem arulta el, melyik vilaghoz
tartozik egy keszlet. Ezert a javitas resze a `exec_gates` jelolo a mentett fajlban.
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


import ml.optimizer as opt
from trading import backtest as bt

# ══ 1. A `run_pair` elfogad ELORE MEGEPITETT TF-kapu-kiertekelot ══════════
# Enelkul a kapu-paritas ara elfogadhatatlan lenne: a kiertekelo resample-t
# igenyel, es trialonkent ujraepitve 500 trial x 4 ablak = 2000 ujraepites.
import inspect

sig = inspect.signature(bt.run_pair)
check("a run_pair-nek van `tf_eval` parametere", "tf_eval" in sig.parameters)
check("...es az alapertek SENTINEL (a None ervenyes ertek: 'nincs kapu')",
      sig.parameters["tf_eval"].default is bt._TF_EVAL_AUTO)

# ══ 2. Az optimalizalo MINDHAROM utja atadja a cfg-t es a kapu-kapcsolot ══
src = (ROOT / "ml" / "optimizer.py").read_text(encoding="utf-8")
check("az optuna-ag atadja", "cfg=cfg, exec_gates=exec_gates, tf_eval=tf_eval" in src)
check("a grid/random-ag atadja", "cfg=cfg, exec_gates=exec_gates, tf_eval=_tf_eval" in src)
check("az OOS TEST is atadja", "cfg=cfg, exec_gates=exec_gates)" in src)
# A kiertekelo a trial-cikluson KIVUL epul (nem parameter-fuggo).
_optuna_body = src[src.index("def optimize_pair_optuna"):src.index("def optimize_pair(")]
# Az ELSO celfuggveny-definicio (a beagyazott kereses ota tobb van: lapos +
# beagyazott) — a kapu-epitesnek MINDEGYIK elott kell lennie.
import re as _re
_first_obj = min(m.start() for m in _re.finditer(r"def _?objective", _optuna_body))
check("az optuna-ag ABLAKONKENT epiti a kaput, nem trialonkent",
      _optuna_body.index("_build_tf_align_evaluator") < _first_obj,
      "a kapu-epites a celfuggveny ELOTT van")
# ⚠ A beagyazott ag a JELOLT-LISTAT viszont trialonkent epiti — ez SZANDEKOS
# (a jel-parameterek trialonkent valtoznak), es pont ez a kulso hurok koltsege.
# A TF-kapu ezzel szemben parameter-fuggetlen, ezert marad kivul.
check("a beagyazott ag a jelolt-listat a KULSO trialon belul epiti",
      "build_signal_series" in _optuna_body and
      _optuna_body.index("build_signal_series", _first_obj) > _first_obj)

# ══ 3. A kapcsolo alapja BE, es configbol allithato ═══════════════════════
check("a config-minta tartalmazza az uj kulcsot",
      '"exec_gates": true' in (ROOT / "config.example.json").read_text(encoding="utf-8"))
from strategy.settings import OPTIMIZER_ENGINE_KEYS, main_config_view
check("az exec_gates MOTOR-kulcs (a config.json-ban marad, nem a strategiaeban)",
      "exec_gates" in OPTIMIZER_ENGINE_KEYS)
_view = main_config_view({"optimizer": {"exec_gates": False, "sma_period": {"min": 1}}})
check("...tehat a mentett vaz-config megorzi",
      _view["optimizer"] == {"exec_gates": False}, str(_view["optimizer"]))

# ══ 4. VISELKEDES: a grid/random ag tenylegesen kapuval hiv ═══════════════
# A `run_pair`-t kicsereljuk egy rogzitore — igy MT5 es valodi adat nelkul is
# lathato, MIT kap a motor.


class FakeResult:
    closed = []


calls = []


def fake_run_pair(*a, **kw):
    calls.append(kw)
    return FakeResult()


class FakeStrategy:
    name = "wpr_sma"

    def constraints_ok(self, params):
        return True


idx15 = pd.date_range("2025-01-01", periods=50, freq="15min")
idx1 = pd.date_range("2025-01-01", periods=200, freq="1min")
df15 = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}, index=idx15)
df1 = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}, index=idx1)

_orig = opt.run_pair
try:
    opt.run_pair = fake_run_pair
    opt.optimize_pair("GOLD", df15, df1, [{"sma_period": 100}], {}, {}, 1000.0,
                      "2025-02-01", FakeStrategy(), cfg={"pairs": {}},
                      exec_gates=True)
    check("a grid/random ag meghivta a run_pair-t", len(calls) == 1)
    check("...KAPUKKAL", calls and calls[0].get("exec_gates") is True, str(calls[:1]))
    check("...es a cfg-t is atadta (enelkul nincs TF-kapu)",
          calls and calls[0].get("cfg") is not None)

    calls.clear()
    opt.optimize_pair("GOLD", df15, df1, [{"sma_period": 100}], {}, {}, 1000.0,
                      "2025-02-01", FakeStrategy())
    check("alapertelmezett hivas (regi hivok) NEM kapuz -> bitazonos marad",
          calls and calls[0].get("exec_gates") is False, str(calls[:1]))
finally:
    opt.run_pair = _orig

# ══ 5. A `run_pair` a beadott kiertekelot HASZNALJA, nem epit ujat ════════
# Ha `exec_gates=False`, a beadott kapu sem lephet eletbe (a kikapcsolas
# kikapcsolas) — kulonben egy regi hivo veletlenul kapuzna.
_built = []
_orig_build = bt._build_tf_align_evaluator
try:
    bt._build_tf_align_evaluator = lambda *a, **k: _built.append(a) or (lambda *x: True)
    # A teljes run_pair futtatasa valodi adatot igenyel; itt csak azt allitjuk,
    # amit a kod SZERKEZETE garantal: a sentinel-ag epit, a beadott ag nem.
    bt_src = (ROOT / "trading" / "backtest.py").read_text(encoding="utf-8")
    check("beadott tf_eval -> NINCS ujraepites",
          "if tf_eval is not _TF_EVAL_AUTO:" in bt_src)
    check("...es exec_gates=False mellett a beadott kapu sem el",
          "_tf_eval = tf_eval if _exec_gates else None" in bt_src)
finally:
    bt._build_tf_align_evaluator = _orig_build

# ══ 6. A MENTETT fajl megmondja, melyik vilaghoz tartozik ═════════════════
check("az optimalizalo eredmenye hordozza a jelolot",
      '"exec_gates":    exec_gates,' in src)
check("a mentes kiirja (CLI ag)", '"exec_gates":    result.get("exec_gates", True),' in src)
gui_src = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
check("a GUI ag a teljes entry-t menti (igy a jelolot is)", "**entry," in gui_src)

# A MEGLEVO fajlokban NINCS jelolo -> a felulet figyelmeztet.
dlg_src = (ROOT / "dashboard" / "instrument_dialog.py").read_text(encoding="utf-8")
check("a parameter-ablak figyelmeztet a kapu nelkul hangolt keszletre",
      'self.data.get("exec_gates", False)' in dlg_src)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

"""Az ml_ai JEL-IDOSIKJA parameter (v1.95.0) — `signal_tf_min`.

BEJELENTES: „Egyvalamit nem latok! Hogy melyik idosikot figyeli! Ez legyen egy
paramétere!"

A VALASZTOTT HATOKOR — STRATEGIA-szintu, nem per instrumentum. Miert: a
`Strategy.timeframes()` az egesz keretrendszer ADAT-SZERZODESE (adatbetoltes,
visszaszamlalok, portfolio-backtest, viz), es egyik hivoja sem tud parametert
adni neki. Egy instrumentumonkent elteroe idosik ezeket szettorne — cserebe
semmit nem nyerne: egy modell-architektura egy idosikhoz tartozik.

A LEGFONTOSABB, AMIT ITT ORZUNK: az idosik-valtas NE legyen NEMA. A modell
bemenete mas idosikon is szerkezetileg ervenyes marad (ugyanaz az 50 oszlop),
csak MAS gyertyaket ir le — pontosan az a csendes csapda, amit a pip->pont
migracional egyszer mar megtapasztaltunk (`feature_unit`). Ezert az idosik a
modell-csomagba is bekerul, es elteresnel a modell KIMARAD.
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


from strategy import ml_ai
from strategy import get_strategy_by_name

strat = get_strategy_by_name("ml_ai")

# ══ 1. Az ALAP valtozatlan: M15 ═══════════════════════════════════════════
# A parameter bevezetese nem valtoztathat a jelenlegi viselkedesen.
check("alapertelmezett jel-idosik M15", ml_ai.signal_tf_min() == 15,
      str(ml_ai.signal_tf_min()))
tfs = strat.timeframes()
check("a timeframes() elso eleme a jel-idosik", tfs[0].label == "M15" and tfs[0].minutes == 15,
      f"{tfs[0].label}/{tfs[0].minutes}")
check("a masodik MINDIG M1 (a vegrehajtas idozitese, nem a jel)",
      tfs[1].label == "M1" and tfs[1].minutes == 1)

# ══ 2. A beallitas atuti a timeframes()-t ═════════════════════════════════
# A configfajlt NEM irjuk at (a felhasznaloe); a gyorsitotarat allitjuk.
def with_tf(minutes, fn):
    saved = dict(ml_ai._tf_cache)
    ml_ai._tf_cache.update({"mtime": -1.0, "v": minutes})
    _orig = ml_ai.signal_tf_min
    ml_ai.signal_tf_min = lambda: minutes
    try:
        return fn()
    finally:
        ml_ai.signal_tf_min = _orig
        ml_ai._tf_cache.clear()
        ml_ai._tf_cache.update(saved)

for m, label in ((5, "M5"), (30, "M30"), (60, "H1")):
    got = with_tf(m, lambda: strat.timeframes()[0])
    check(f"{m} perc -> {label} cimke", got.label == label and got.minutes == m,
          f"{got.label}/{got.minutes}")

check("a megengedett halmazban NINCS H4 (a H1-kontextus feature miatt)",
      240 not in ml_ai.ALLOWED_TF_MIN, str(ml_ai.ALLOWED_TF_MIN))

# ══ 3. A warmup a JEL idosikjara vonatkozik, nem az 'M15' szora ═══════════
# Bedrotozott "M15" eseten az atallitott jel-frame nemán a sekely warmupot
# kapna — es a feature-ok NaN-ok lennenek.
def _warm(minutes):
    return with_tf(minutes, lambda: (
        strat.warmup_bars({"ml_warmup_bars": 900}, strat.timeframes()[0].label),
        strat.bt_warmup({}, strat.timeframes()[0].label)))

for m in (5, 15, 30, 60):
    w_live, w_bt = _warm(m)
    check(f"M{m}: a jel-frame MELY warmupot kap ({w_live} / {w_bt})",
          w_live == 900 and w_bt > 100, f"{w_live} / {w_bt}")
check("az M1 warmup valtozatlanul sekely",
      strat.warmup_bars({}, "M1") == 10 and strat.bt_warmup({}, "M1") == 2)

# ══ 4. Az atmintazas HELYES gyertyakat ad ════════════════════════════════
idx = pd.date_range("2025-01-01", periods=120, freq="1min")
df1 = pd.DataFrame({"open": range(120), "high": [x + 2 for x in range(120)],
                    "low": [x - 2 for x in range(120)], "close": range(120)},
                   index=idx, dtype=float)
r15 = ml_ai.resample_ohlc(df1, 15)
check("120 M1 -> 8 M15 gyertya", len(r15) == 8, str(len(r15)))
check("az elso M15 gyertya OHLC-ja a 15 M1-bol jon",
      (r15.iloc[0]["open"] == 0.0 and r15.iloc[0]["close"] == 14.0
       and r15.iloc[0]["high"] == 16.0 and r15.iloc[0]["low"] == -2.0),
      str(r15.iloc[0].to_dict()))
check("a gyertya a NYITO idejevel azonositott (mint az MT5/tf_align)",
      str(r15.index[0]) == str(idx[0]), str(r15.index[0]))
check("az idosik visszafejtheto az indexbol", ml_ai._infer_tf_min(r15) == 15,
      str(ml_ai._infer_tf_min(r15)))

# `frame_for_signal`: ha mar jo, NEM masol; ha nem, a FINOMABBOL mintaz.
df15 = ml_ai.resample_ohlc(df1, 15)
check("mar jo idosik -> ugyanaz az objektum (nincs felesleges munka)",
      ml_ai.frame_for_signal(df15, df1, 15) is df15)
got30 = ml_ai.frame_for_signal(df15, df1, 30)
check("mas idosik -> atmintazva", ml_ai._infer_tf_min(got30) == 30,
      str(ml_ai._infer_tf_min(got30)))
check("...es az M1-bol (finomabb), nem az M15-bol", len(got30) == 4, str(len(got30)))

# ══ 5. A MODELL-EGYEZES orzese — ez a lenyeg ═════════════════════════════
# Ha a modell mas idosikon tanult, NEM kereskedunk vele.
class _FakeStat:
    st_mtime = 12345.0


def _with_fake_bundle(meta, tf_now, fn):
    saved_cache = dict(ml_ai._bundle_cache)
    ml_ai._bundle_cache.clear()
    _orig_path, _orig_tf = ml_ai.model_path, ml_ai.signal_tf_min

    class _P:
        name = "FAKE.pkl"

        def stat(self):
            return _FakeStat()

    ml_ai.model_path = lambda sym: _P()
    ml_ai.signal_tf_min = lambda: tf_now
    import builtins
    _orig_open = builtins.open
    import pickle as _pk
    _orig_load = _pk.load
    _pk.load = lambda f: {"meta": meta, "features": [], "long": {}, "short": {}}
    builtins.open = lambda *a, **k: _orig_open(__file__, "rb")
    try:
        return fn()
    finally:
        builtins.open = _orig_open
        _pk.load = _orig_load
        ml_ai.model_path, ml_ai.signal_tf_min = _orig_path, _orig_tf
        ml_ai._bundle_cache.clear()
        ml_ai._bundle_cache.update(saved_cache)


_ok = _with_fake_bundle({"feature_unit": "point", "signal_tf_min": 15}, 15,
                        lambda: ml_ai.load_bundle("FAKE"))
check("egyezo idosik -> a modell hasznalhato", _ok is not None)

_bad = _with_fake_bundle({"feature_unit": "point", "signal_tf_min": 15}, 30,
                         lambda: ml_ai.load_bundle("FAKE"))
check("MAS idosikon tanult modell -> KIHAGYVA (nem nema hiba)", _bad is None)

# Regi (idosik-jelolo nelkuli) modell: M15-osnek tekintjuk — eddig csak olyan volt.
_old15 = _with_fake_bundle({"feature_unit": "point"}, 15,
                           lambda: ml_ai.load_bundle("FAKE"))
check("regi, jelolo nelkuli modell M15-on tovabbra is mukodik", _old15 is not None)
_old30 = _with_fake_bundle({"feature_unit": "point"}, 30,
                           lambda: ml_ai.load_bundle("FAKE"))
check("...de M30-ra atallitva mar nem", _old30 is None)

# ══ 6. A tanitas a JEL idosikjan tanit, es bejegyzi ══════════════════════
tr_src = (ROOT / "strategy" / "ml_train.py").read_text(encoding="utf-8")
check("a tanitas a jel-idosikra mintaz at", "ml_ai.resample_ohlc(df_m15, tf_min)" in tr_src)
check("...es az idosik a modell fejlecebe kerul", '"signal_tf_min": tf_min,' in tr_src)
check("a feature-frame a JEL-frame-bol epul (nem a nyers M15-bol)",
      "build_feature_frame(df_sig, pip)" in tr_src)

# ══ 7. A config-minta es a param_meta megmondja a felhasznalonak ═════════
import json
cfg_ml = json.loads((ROOT / "strategy" / "config" / "ml_ai.json").read_text(encoding="utf-8"))
check("a stratégia-config tartalmazza a kulcsot",
      cfg_ml["indicators"].get("signal_tf_min") == 15)
check("...es a Parameterek ablak is megmagyarazza",
      "signal_tf_min" in (cfg_ml["param_meta"]["params"]))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

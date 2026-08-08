"""
A STRATEGIA PARAMETEREI: mentett json + a KOZOS vegrehajtasi config — EGY keplet.

⚠ VALOS HIBA (2026-08-08). Az `atr_period` (es a BE/trailing/spread-kapu)
2026-08-03 ota NEM a strategia mentett json-jaban lakik, hanem a kozos
`core/execution_params`-ban. Az EL-ut ezt rafuzte, a VIZ-ut viszont a NYERS
json-t hasznalta:

    vparams = load_pair_params(symbol, st.name) or params_by_strat[st.name]
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ a nyers json NYER

Ezert a 2026-08-03 UTAN optimalizalt parokon a `compute_indicators`
`KeyError: 'atr_period'`-del elszallt, es a chart NEMAN ures maradt. A regebbi
parok csak azert mukodtek, mert a json-jukba meg bele volt sutve az `atr_period`.
A naplo ezt irta ki (v2.18.0 ota):

    WARNING EURCHF/wpr_sma — a viz nem rajzolhato: az indikatorok nem
            szamolhatok a jelenlegi parameterekkel (KeyError: 'atr_period')

Ket keplet ugyanarra a kerdesre mindig szetcsuszik; ezert van egy.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import core.applog as _applog
_applog.harden_console()

ROOT = pathlib.Path(__file__).resolve().parents[1]
_results = []
_fail = []


def check(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name + (f"  [{detail}]" if detail else ""))
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)


from trading import live_trader as lt                    # noqa: E402
from core import execution_params as ep                  # noqa: E402

# ---------------------------------------------------------------------------
print("== A kozos keplet ==")
check("van `strategy_params` fuggveny", callable(getattr(lt, "strategy_params", None)))

raw = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
from strategy.settings import config_for_strategy        # noqa: E402
cfg = config_for_strategy(raw, "wpr_sma")

SYM = "EURCHF"        # a naploban HIBAZOTT parok egyike
_has = (ROOT / "data" / "optimized_params" / "wpr_sma" / f"{SYM}.json").exists()
if not _has:
    print(f"  (kihagyva: nincs {SYM} params)")
else:
    rawp = lt.load_pair_params(SYM, "wpr_sma")
    merged = lt.strategy_params(SYM, "wpr_sma", cfg)
    check("a NYERS json-bol tenyleg hianyzik az atr_period",
          "atr_period" not in rawp, "ez a hiba elofeltetele")
    check("a kozos keplet POTOLJA", "atr_period" in merged, str(merged.get("atr_period")))
    check("...a strategia sajat szamai valtozatlanok",
          all(merged[k] == v for k, v in rawp.items()
              if k not in (ep.load_execution_params(SYM, cfg) or {})))

    # A vegrehajtasi kulcsok mind atjonnek
    for k in (ep.load_execution_params(SYM, cfg) or {}):
        check(f"a(z) {k!r} vegrehajtasi kulcs benne van", k in merged)

check("hianyzo params -> None", lt.strategy_params("NINCS_ILYEN", "wpr_sma", cfg) is None)
check("tartalek hasznalhato",
      (lt.strategy_params("NINCS_ILYEN", "wpr_sma", cfg,
                          fallback={"sma_period": 7}) or {}).get("sma_period") == 7)

# ---------------------------------------------------------------------------
print("== A HIBA reprodukalasa igazi adaton ==")
import pandas as pd                                       # noqa: E402
from core.indicator_engine import compute_indicators      # noqa: E402

_broken, _fixed = [], []
for sym in ("EURCHF", "EURJPY", "Euro50", "GOLD", "UsaInd", "Ger40", "UsaTec"):
    pq15 = ROOT / "data" / "m15" / f"{sym}.parquet"
    pq1 = ROOT / "data" / "m1" / f"{sym}.parquet"
    pf = ROOT / "data" / "optimized_params" / "wpr_sma" / f"{sym}.json"
    if not (pq15.exists() and pq1.exists() and pf.exists()):
        continue
    m15 = pd.read_parquet(pq15).iloc[-400:]
    m1 = pd.read_parquet(pq1).iloc[-1500:]

    def _ok(prm):
        if prm is None:
            return None
        try:
            compute_indicators(m15, m1, prm)
            return True
        except Exception:
            return False

    if _ok(lt.load_pair_params(sym, "wpr_sma")) is False:
        _broken.append(sym)
    if _ok(lt.strategy_params(sym, "wpr_sma", cfg)) is True:
        _fixed.append(sym)

print(f"     a NYERS json-nal elszall: {_broken or '(egy sem)'}")
print(f"     a kozos keplettel megy:   {_fixed}")
if _broken:
    check("a kozos keplet MINDET megjavitja",
          all(s in _fixed for s in _broken), f"{_broken} vs {_fixed}")
else:
    print("  (nincs olyan par, ami a nyers json-nal elszallna — a teszt nem mer semmit)")
check("legalabb egy par atmegy a kozos keplettel", bool(_fixed), str(_fixed))

# ---------------------------------------------------------------------------
print("== A ket ut UGYANAZT hasznalja ==")
_src = pathlib.Path(lt.__file__).read_text(encoding="utf-8")
check("az el-ut a kozos fuggvenyt hivja",
      "_params = strategy_params(symbol, strat.name, cfg)" in _src)
check("a viz NEM a nyers json-t reszesiti elonyben",
      "load_pair_params(symbol, st.name) or params_by_strat" not in _src,
      "a regi `or` mintat kivettuk")
check("a viz a MERGELT pillanatkepre retegez",
      "{**_snap, **_fresh}" in _src)

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)

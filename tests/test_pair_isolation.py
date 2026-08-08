"""
EGY HIBAS PAR NE VIGYE EL AZ EGESZ MOTORT — es a szal halala legyen LATHATO.

⚠ VALOS KAR (2026-08-08). Uj instrumentumot vettek fel `point_size` nelkul. A
`pair_cfg["point_size"]` KeyError-je megolte a teljes LiveTrader szalat:

    Exception in thread LiveTrader:
      File "trading/live_trader.py", line 2496, in _make_state
        _params = {**_params, "symbol": symbol, "point_size": pair_cfg["point_size"]}
    KeyError: 'point_size'

Ettol EGYETLEN par sem kereskedett (11-bol), es a TradeForgeViz fajlok sem
irodtak — a chart uresen maradt. A traceback a Python alapertelmezett
szal-hookjaval a STDERR-re ment, a `tradeforge.log`-ban NYOMA SEM VOLT: a naplo
utolso sora egy artatlan "CSAK JELZES mod" figyelmeztetes volt. A hiba HETEKIG
eszrevetlen maradt.

Harom retegben vedunk, mindharmat ez a teszt rogziti:
  1. a config-ellenorzes INDULAS ELOTT megmondja, melyik par hianyos;
  2. a motor a hianyos part KIHAGYJA (nem hal meg tole);
  3. ha megis elhal egy szal, a NAPLOBA is bekerul.
"""

import logging
import pathlib
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import core.applog as _applog
_applog.harden_console()

from core import config_check as cc               # noqa: E402

_results = []
_fail = []


def check(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name + (f"  [{detail}]" if detail else ""))
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)


# ---------------------------------------------------------------------------
print("== 1. A config-ellenorzes szol INDULAS ELOTT ==")

check("teljes par -> nincs hianyzo kulcs",
      cc.missing_sizing_keys({"point_size": 0.01, "pv1_point": 1.0}) == [])
check("hianyzo point_size -> jelzi",
      cc.missing_sizing_keys({"pv1_point": 1.0}) == ["point_size"])
check("mindketto hianyzik -> mindketto",
      cc.missing_sizing_keys({}) == ["point_size", "pv1_point"])
check("a NULLA is hianynak szamit (0 point_size ertelmetlen)",
      cc.missing_sizing_keys({"point_size": 0, "pv1_point": 1.0}) == ["point_size"])
check("nem-dict par -> minden kulcs hianyzik",
      cc.missing_sizing_keys(None) == ["point_size", "pv1_point"])

cfg = {"pairs": {"Jo": {"point_size": 0.01, "pv1_point": 1.0},
                 "Uj": {"enabled": True, "pv1_point": 1.0}}}
finds = [f for f in cc.check(cfg) if f["code"] == "missing_sizing"]
check("a hianyos par leletet kap", len(finds) == 1, f"{len(finds)} lelet")
if finds:
    check("...a par nevevel", finds[0]["symbol"] == "Uj", str(finds[0]["symbol"]))
    check("...es megmondja a KOVETKEZMENYT (nem fog kereskedni)",
          "NEM fog keresked" in finds[0]["message"], finds[0]["message"][:60])
    check("...es a JAVITAST is", "refresh_point_values" in finds[0]["message"])
check("a jo par NEM kap leletet", all(f["symbol"] != "Jo" for f in finds))

# A motor es az ellenorzes UGYANAZT a fuggvenyt hasznalja (kulonben szetcsuszhat)
import trading.live_trader as lt                   # noqa: E402
check("a motor a KOZOS helperre tamaszkodik",
      getattr(lt, "_cfgchk", None) is cc,
      "core.config_check importalva a live_trader-be")

# ---------------------------------------------------------------------------
print("== 2. A hianyos par KIMARAD, a tobbi fut ==")
# A `_make_state` a `run()` belsejeben el (closure), ezert a DONTES logikajat
# nezzuk: a hianyos par eseten a helper nem-ures listat ad, tehat a motor kihagyja.
_src = pathlib.Path(lt.__file__).read_text(encoding="utf-8")
check("a _make_state ellenorzi a meretezesi kulcsokat",
      "_cfgchk.missing_sizing_keys(pair_cfg)" in _src)
# A nyers `pair_cfg["point_size"]` indexeles MEGMARADHAT — de csak a kapu UTAN.
# (A `process_pair` is indexel, de az mar LivePairState-et kap, amit a
# `_make_state` gyart: hibas par oda el sem jut.)
_guard = _src.index("_cfgchk.missing_sizing_keys(pair_cfg)")
_use = _src.index('"point_size": pair_cfg["point_size"]}')
check("...es a kapu MEGELOZI a nyers indexelest", _guard < _use,
      f"kapu@{_guard} < hasznalat@{_use}")
check("...a kapu return None-nal zar (nem dob)",
      "return None" in _src[_guard:_use])
check("a par-inicializalo ciklus izolalt (try/except)",
      "KIHAGYVA az indításnál" in _src)

# ---------------------------------------------------------------------------
print("== 3. A szal halala a NAPLOBA is bekerul ==")


class _Catch(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


root = logging.getLogger()
cap = _Catch()
root.addHandler(cap)
_prev_hook = threading.excepthook
try:
    _applog.install_thread_excepthook()
    _applog.install_thread_excepthook()          # idempotens
    check("a hook idempotens (nem lancol ujra)",
          getattr(threading.excepthook, _applog._MARKER, False) is True)

    def _boom():
        raise KeyError("point_size")

    t = threading.Thread(target=_boom, name="LiveTrader")
    t.start()
    t.join()

    crit = [r for r in cap.records if r.levelno >= logging.CRITICAL]
    check("a naplo kapott CRITICAL bejegyzest", bool(crit), f"{len(crit)} db")
    if crit:
        msg = crit[0].getMessage()
        check("...a szal NEVEVEL", "LiveTrader" in msg, msg[:70])
        check("...es a KOVETKEZMENNYEL (a munka megallt)",
              "MEGÁLLT" in msg, msg[:70])
        check("...a tracebackkel egyutt", crit[0].exc_info is not None)
        check("...benne a valodi kivetellel",
              crit[0].exc_info and crit[0].exc_info[0] is KeyError,
              str(crit[0].exc_info[0]) if crit[0].exc_info else "-")
    check("a program NEM allt meg a szal halalatol", True)
finally:
    root.removeHandler(cap)
    threading.excepthook = _prev_hook

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)

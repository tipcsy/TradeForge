"""KÉZI LABORATÓRIUM 3. LÉPCSŐ — a charton megrajzolt forgatókönyv.

⚠ A LÉNYEGI ÁLLÍTÁS: a chartról kattintva épített terv és a JSON-fájlból
betöltött terv UGYANAZ — ugyanabba a `lab_scenario.futtat()`-ba megy, tehát
ugyanazt az eredményt adja. Ha a chart-ablak saját végrehajtási utat kapna, a
projekt visszatérő kárforrása jönne vissza: két forrás, ami külön romlik el
(`BacktestReplayer` v4, viz ↔ backtest paritás).

Ezért a teszt nem a gombokat nyomkodja, hanem azt köti ki, hogy

  * a `_forgatokonyv()` UGYANOLYAN alakú szótárat ad, mint a `lab_scenario.MINTA`,
  * ez a szótár tényleg végigfut a valódi motoron,
  * és a chart-ablak nem tartalmaz saját szimulációt.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import logging
logging.disable(logging.INFO)

import pandas as pd

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from tools import lab_chart as lc
from tools import lab_scenario as ls


class _Var:
    """Tk-mentes helyettes a `StringVar`/`BooleanVar` helyett."""

    def __init__(self, v):
        self._v = v

    def get(self):
        return self._v


def _ablak(belepok, be_ido=None, epites=False, chart=None):
    """`LabAblak` UI-építés NÉLKÜL — csak a forgatókönyv-építéshez kell."""
    a = lc.LabAblak.__new__(lc.LabAblak)
    a._belepok = list(belepok)
    a._be_ido = be_ido
    a._epites = _Var(epites)
    a._sym = _Var("UsaTec")
    a._strat = _Var("wpr_sma")
    a._tol = _Var("")
    a._ig = _Var("")
    a._chart = chart
    return a


_idx = pd.date_range("2026-08-27 00:00", periods=96, freq="15min", tz="UTC")
_chart = pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5},
                      index=_idx)

# ── 1. A FORGATÓKÖNYV ALAKJA ──────────────────────────────────────────────
_fk = _ablak([(_idx[6], "BUY")], be_ido=_idx[20], epites=True,
             chart=_chart)._forgatokonyv()

check("a chart-terv MINDEN kulcsot megad, amit a JSON-minta",
      set(ls.MINTA).issubset(set(_fk)),
      str(sorted(set(ls.MINTA) - set(_fk))))
check("a belépő időpontja és iránya átmegy",
      _fk["entries"] == [{"time": "2026-08-27 01:30", "direction": "BUY"}],
      str(_fk["entries"]))
check("a breakeven időpont átmegy",
      _fk["breakeven_at"] == "2026-08-27 05:00", str(_fk["breakeven_at"]))
check("az építés kapcsoló átmegy", _fk["build"] is True)
# ⚠ A kézi belépő alapja a kapuk NÉLKÜLI futás — ugyanaz, mint a `--minta`-ban.
check("kézi belépőnél a kapuk KI (mint a JSON-mintában)",
      _fk["exec_gates"] is False and _fk["use_strategy_signals"] is False)

# ⚠ ÜRES `-tól`/`-ig` esetén a CHART szélei adják a szakaszt — enélkül a
# `run_pair` az egész előzményt átfutná, és a kísérlet percekig tartana.
# (96 x 15 perc = 24 ora 00:00-tol, tehat az UTOLSO gyertya 23:45 — nem masnap.)
check("üres időszaknál a chart széleit használja",
      _fk["from"] == "2026-08-27 00:00" and _fk["to"] == "2026-08-27 23:45",
      f"{_fk['from']} .. {_fk['to']}")

# ── 2. TÖBB BELÉPŐ: IDŐRENDBEN ────────────────────────────────────────────
# ⚠ A `run_pair` a jelölt-listát pozíció-index szerint dolgozza fel; egy
# fordított sorrendű lista némán mást jelentene.
_fk2 = _ablak([(_idx[30], "SELL"), (_idx[10], "BUY")],
              chart=_chart)._forgatokonyv()
check("a belépők IDŐRENDBEN kerülnek a forgatókönyvbe",
      [e["direction"] for e in _fk2["entries"]] == ["BUY", "SELL"],
      str(_fk2["entries"]))
check("breakeven nélkül a kulcs None", _fk2["breakeven_at"] is None)

# ── 3. A TERV TÉNYLEG VÉGIGFUT A VALÓDI MOTORON ───────────────────────────
# ⚠ Ez köti össze a két lépcsőt: a charton megrajzolt terv ugyanazon az úton
# megy, mint a `python tools/lab_scenario.py fk.json`.
_valos = {**ls.MINTA}
_ki = None
try:
    _ki = ls.futtat(_valos)
except SystemExit as ex:
    check("a JSON-minta lefut a motoron", False, f"SystemExit: {ex}")
if _ki is not None:
    check("a JSON-minta lefut a motoron", "res" in _ki)
    # És a chart-terv UGYANOLYAN alakú → ugyanaz a hívás fogadja el.
    _chart_terv = _ablak([(pd.Timestamp("2026-08-27 01:30", tz="UTC"), "BUY")],
                         chart=_chart)._forgatokonyv()
    _chart_terv.update({"symbol": _valos["symbol"],
                        "strategy": _valos["strategy"],
                        "from": _valos["from"], "to": _valos["to"]})
    try:
        _ki2 = ls.futtat(_chart_terv)
        _a = [(str(t.open_time), t.direction) for t in _ki["res"].trades]
        _b = [(str(t.open_time), t.direction) for t in _ki2["res"].trades]
        check("a CHART-terv ugyanazt a kötést adja, mint a JSON-terv",
              _a == _b, f"{len(_a)} vs {len(_b)}")
    except SystemExit as ex:
        check("a CHART-terv ugyanazt a kötést adja, mint a JSON-terv", False,
              f"SystemExit: {ex}")

# ── 4. NINCS SAJÁT VÉGREHAJTÁS ────────────────────────────────────────────
_src = (ROOT / "tools" / "lab_chart.py").read_text(encoding="utf-8")
check("a chart a MEGLÉVŐ forgatókönyv-motort hívja",
      "from tools.lab_scenario import futtat" in _src)
for _tilos in ("run_pair(", "def simulate", "def _manage", "close_price ="):
    check(f"nincs saját végrehajtás a chart-ablakban ({_tilos!r})",
          _tilos not in _src)

# ⚠ A `lab_scenario._hiba` SystemExit-tel áll meg (parancssori eszköz). Ha az
# ablak nem fogná el, egy elgépelt szimbólum MEGÖLNÉ a laboratóriumot.
_fut = _src.split("def futtat", 1)[1].split("\n    def ", 1)[0]
check("a futtatás elfogja a SystemExit-et (nem hal meg az ablak)",
      "except SystemExit" in _fut)

# ── 5. A KATTINTÁS csak AKTÍV MÓDBAN tesz le jelölőt ──────────────────────
# ⚠ A nagyítás/görgetés is kattintás. Ha minden kattintás belépőt tenne, a
# chart használhatatlan lenne.
_katt = _src.split("def _kattintas", 1)[1].split("\n    def ", 1)[0]
check("üres módnál a kattintás nem tesz le semmit",
      "if not mod or ev.inaxes is not self._ax" in _katt)
# ⚠ IDŐBEN tárolunk, nem bar-indexben: az idősík-váltás átszámozza az indexeket.
check("a belépő IDŐPONTKÉNT tárolódik (nem bar-indexként)",
      "t = self._chart.index[i]" in _katt)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

"""KÉZI LABORATÓRIUM — a Qt/pyqtgraph felület.

⚠ MIÉRT CSERÉLTÜK LE A MATPLOTLIB-ET (2026-09-03). A felhasználói hibalista —
nem lehet megfogni a vonalat, kicsúszik a képből, a nagyítás használhatatlan, a
tengely-felirat eltűnik, húzás közben újrarajzol — mind egy okra vezetett
vissza: a matplotlib diagram-rajzoló, nem interaktív chart. A húzható vonalat,
a találat-tesztet és a tengely-formázót kézzel írtuk meg, és a hibák is
darabonként jöttek.

MÉRVE (UsaTec, ugyanaz az adat, teljes újrarajzolás):

    gyertya   matplotlib   pyqtgraph   arány
        184      52,2 ms      3,5 ms   14,9x
      2 760     128,3 ms     20,2 ms    6,4x
     11 040     426,2 ms     89,4 ms    4,8x

⚠ EZ A TESZT NEM A RAJZOLÁST ŐRZI, HANEM A HATÁRT: hogy a csere KIZÁRÓLAG a
megjelenítést érintette. Az adat a `lab_chart.keszit()`-ből, a futtatás a
`lab_scenario.futtat()`-ból jön — ha a Qt-s ablak saját végrehajtást kapna,
visszajönne a projekt visszatérő kárforrása (két forrás, ami külön romlik el).
"""
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


try:
    import pyqtgraph  # noqa: F401
    from PySide6 import QtWidgets  # noqa: F401
    QT_OK = True
except Exception as _e:
    QT_OK = False
    print(f"KIHAGYVA: nincs Qt/pyqtgraph ({type(_e).__name__}: {_e})")

_src = (ROOT / "tools" / "lab_qt.py").read_text(encoding="utf-8")

# ── 1. A HATÁR: nincs saját adat- vagy végrehajtási út ────────────────────
check("az adat a MEGLÉVŐ `keszit()`-ből jön",
      "from tools.lab_chart import" in _src and "keszit" in _src)
check("a futtatás a MEGLÉVŐ `lab_scenario.futtat()`-ot hívja",
      "from tools.lab_scenario import futtat" in _src)
for _tilos in ("run_pair(", "def simulate", "def _manage", "open_position",
               "pair_visual_objects("):
    check(f"nincs saját végrehajtás/adatút ({_tilos!r})", _tilos not in _src)

# ⚠ A SZÍNEK IS a közös forrásból: a Qt-s és az MT5-ös chart ugyanazt a jelet
# ne mutassa más színnel — a kettő összevetése az egyik cél.
check("a színek a `lab_chart.szin`-ből (végső soron `visual.COLORS`)",
      "szin(" in _src and "from tools.lab_chart import" in _src)

if QT_OK:
    from tools import lab_qt as lq
    from tools import lab_scenario as ls

    # ── 2. A BELÉPŐ: idő az azonosító, a TP a stop függvénye ─────────────
    b = lq.Belepo(pd.Timestamp("2026-08-27 01:30", tz="UTC"), "BUY",
                  sl=29500.0, rr=2.0)
    check("a TP a stop TÁVOLSÁGÁBÓL és az R-ből",
          abs(b.tp_ar(29532.0) - (29532.0 + 2.0 * 32.0)) < 1e-6,
          str(b.tp_ar(29532.0)))
    b.rr = 3.5
    check("...és az R változása mozgatja a TP-t",
          abs(b.tp_ar(29532.0) - (29532.0 + 3.5 * 32.0)) < 1e-6)
    _s = lq.Belepo(pd.Timestamp("2026-08-27 01:30", tz="UTC"), "SELL",
                   sl=29560.0, rr=2.0)
    check("SELL-nél a TP LEFELÉ van",
          _s.tp_ar(29532.0) < 29532.0, str(_s.tp_ar(29532.0)))

    # ── 3. AZ ABLAK FELÉPÜL, és a terve ugyanaz az alak ──────────────────
    # ⚠ Valódi ablakot építünk: a `__new__`-os tesztek pont a konstruktort
    # kerülik meg, és a matplotlib-es változatnál épp ott volt egy hiba, ami
    # miatt EL SEM INDULT.
    import json as _json
    _cfg = _json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    _par = next((k for k, v in (_cfg.get("pairs") or {}).items()
                 if isinstance(v, dict)
                 and (ROOT / "data" / "m15" / f"{k}.parquet").exists()), None)
    if _par is None:
        check("van pár, amivel az ablak felépíthető", False, "nincs adat")
    else:
        _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        _w = None
        try:
            _w = lq.LabAblak(symbol=_par, tf_perc=15,
                             tol="2026-08-25", ig="2026-08-26")
            check("az ablak FELÉPÜL (a konstruktor végigfut)", True)
            check("betöltött gyertyák", _w._chart is not None and len(_w._chart) > 10,
                  str(None if _w._chart is None else len(_w._chart)))

            # A kattintás-idő gyertyán BELÜL is pontos (idősík-független).
            _t1 = _w._ido_x(10.0)
            _t2 = _w._ido_x(10.25)
            check("a gyertyán belüli kattintás finomabb időt ad",
                  _t1 is not None and _t2 is not None and _t2 > _t1,
                  f"{_t1} / {_t2}")

            # A forgatókönyv ALAKJA azonos a JSON-mintáéval.
            _w._belepok.append(lq.Belepo(_w._chart.index[20], "BUY",
                                         float(_w._chart["close"].iloc[20]) - 10,
                                         2.0))
            _fk = _w._forgatokonyv()
            check("a Qt-terv MINDEN kulcsot megad, amit a JSON-minta",
                  set(ls.MINTA).issubset(set(_fk)),
                  str(sorted(set(ls.MINTA) - set(_fk))))
            check("a belépő SL és TP-szorzó is átmegy",
                  _fk["entries"] and "sl" in _fk["entries"][0]
                  and "tp_rr" in _fk["entries"][0], str(_fk["entries"][:1]))
            # ⚠ Az üres BE/trailing mező NEM 0, hanem „maradjon a mentett".
            for _e in _w._rr_mezok.values():
                _e.setText("")
            check("üres BE/trailing mező → nincs felülírás",
                  _w._rr_ertekek() == {}, str(_w._rr_ertekek()))
        except Exception as _ex:
            check("az ablak FELÉPÜL (a konstruktor végigfut)", False,
                  f"{type(_ex).__name__}: {_ex}")
        finally:
            if _w is not None:
                _w.close()

# ── 4. A RÉGI FELÜLET MEGMARADT ───────────────────────────────────────────
# ⚠ Amíg a Qt-s nem futott elég valós helyzeten, a matplotlib-es legyen
# elérhető — egy felület, ami tegnap még működött, ne tűnjön el egy csapásra.
_main = (ROOT / "main.py").read_text(encoding="utf-8")
check("a `lab` parancs a Qt-s felületet indítja",
      "from tools.lab_qt import main" in _main)
check("a régi felület `lab-mpl` néven elérhető maradt",
      '"lab-mpl"' in _main and "from tools.lab_chart import main" in _main)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

"""A labor LEJÁTSZÁSA nem épülhet újra minden képen (v3.58.0).

⚠ A LELET (2026-09-09, mérve). A felhasználó jelezte, hogy „nagyobb mennyiségű
adatnál akadni kezd a chart", és felmerült, hogy talán másik nyelven (Rust)
kellene írni a chart-kezelőt. A mérés MÁST mondott:

    RAJZ (kurzor + gyertyák)      395 gyertya   0,58 ms/kép
                                20 325 gyertya  0,58 ms/kép   ← KONSTANS
    TÁBLA (_listak_frissit)      1000 kötés    82,90 ms/kép   ← LINEÁRIS

A gyertyaszám tehát SEMMIT nem számít (a pyqtgraph egyszer rajzol); az akadást a
KÖTÉSSZÁM okozta, három, képenként ismételt munkán keresztül:

  1. `setRowCount(0)` + új `QTableWidgetItem` MINDEN cellára, minden képen,
  2. a SZÁMLAGÖRBE teljes újraszámolása — pedig a görbe a kurzortól FÜGGETLEN,
  3. a LEZÁRT kötések sorainak újraformázása — pedig azok soha nem változnak.

Mind a három Qt-widget-allokáció és Python-string-munka, nem számítás: **másik
nyelv nem javított volna rajta semmit.**

MÉRVE, előtte → utána (Ger40, 3 hónap, ~8 nyitott pozíció a kurzornál):

    kötés     előtte      utána    gyorsulás
      250    13,20 ms   1,43 ms       9,2x
      500    30,18 ms   2,74 ms      11,0x
     1000    82,90 ms   5,16 ms      16,1x
     2000   193,37 ms  11,64 ms      16,6x

⚠ AMIT EZ A TESZT ŐRIZ: nem a sebességet (az gépfüggő), hanem a HELYESSÉGET —
egy elavult gyorsítótár NÉMÁN rossz számot mutatna a felületen, ami rosszabb a
lassúságnál. A gyorsítótárnak érvénytelenednie KELL, ha az eredmény, a chart
vagy a kezdő egyenleg változik.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog

applog.harden_console()

import logging

logging.disable(logging.INFO)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


_src = (ROOT / "tools" / "lab_qt.py").read_text(encoding="utf-8")

# ── 1. A MINTA: a képenkénti újraépítés eltűnt ────────────────────────────
check("⚠ nincs képenkénti `setRowCount(0)` letarolás",
      "for t in self._tablak.values():\n            t.setRowCount(0)" not in _src)
check("a táblát a cella-újrahasznosító `_tabla_ir` írja", "_tabla_ir(" in _src)
check("...és mindkét táblára", _src.count("self._tabla_ir(") >= 3,
      f"{_src.count('self._tabla_ir(')} hívás")
check("⚠ a számlagörbének van gyorsítótára", "_gorbe_cache" in _src)
check("⚠ a lezárt sorok memoizálva", "_lezart_cache" in _src)


# ── 2. A HELYESSÉG: a gyorsítótár érvénytelenedik ────────────────────────
try:
    import pyqtgraph  # noqa: F401
    from PySide6 import QtWidgets  # noqa: F401
    QT_OK = True
except Exception as _e:
    QT_OK = False
    print(f"KIHAGYVA (a viselkedés-rész): nincs Qt/pyqtgraph "
          f"({type(_e).__name__}: {_e})")

if QT_OK:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import numpy as np
    import pandas as pd
    from PySide6 import QtWidgets as QW

    app = QW.QApplication.instance() or QW.QApplication([])
    from tools import lab_qt as lq

    # Szintetikus chart — nem kell éles adat, a gyorsítótár logikáját mérjük.
    _idx = pd.date_range("2026-01-01", periods=200, freq="15min", tz="UTC")
    CHART = pd.DataFrame({"open": np.linspace(100, 120, 200),
                          "high": np.linspace(101, 121, 200),
                          "low": np.linspace(99, 119, 200),
                          "close": np.linspace(100, 120, 200)}, index=_idx)

    class _Res:
        def __init__(self, trades):
            self.trades = trades

    w = lq.LabAblak.__new__(lq.LabAblak)      # UI nélkül: csak a számoló rész
    w._chart = CHART
    w._kurzor = 100
    w._eredmeny = {"res": _Res([]), "balance": 1000.0}

    g1 = w._szamla_gorbe()
    g2 = w._szamla_gorbe()
    check("a görbe MÁSODSZORRA a gyorsítótárból jön (ugyanaz az objektum)",
          g1 is g2)

    # ⚠ Az érvénytelenedés HÁROM oka — mindegyik NÉMA hiba volna.
    w._eredmeny = {"res": _Res([]), "balance": 1000.0}      # ÚJ res-objektum
    g3 = w._szamla_gorbe()
    check("⚠ ÚJ eredmény → ÚJRASZÁMOL (különben a régi görbét mutatná)",
          g3 is not g1)

    w._eredmeny = {"res": w._eredmeny["res"], "balance": 5000.0}   # más kezdő
    g4 = w._szamla_gorbe()
    check("⚠ más KEZDŐ EGYENLEG → újraszámol", g4 is not g3)
    check("...és tényleg az új egyenlegről indul",
          abs(float(g4[0][0]) - 5000.0) < 1e-6, str(g4[0][0]))

    w._chart = CHART.iloc[:100]
    g5 = w._szamla_gorbe()
    check("⚠ más CHART (időszak/idősík) → újraszámol", g5 is not g4)
    check("...és az új hosszal", len(g5[0]) == 100, str(len(g5[0])))

    # A gyorsítótárazott érték EGYEZZEN a friss számítással.
    from tools.lab_qt import szamla_gorbe as _friss
    _f = _friss(w._chart, [], 5000.0)
    check("⚠ a gyorsítótárazott görbe BITAZONOS a frissen számolttal",
          np.allclose(g5[0], _f[0]) and np.allclose(g5[1], _f[1]))

    # ── A cella-újrahasznosító tábla-író ─────────────────────────────────
    t = QW.QTableWidget(0, 3)
    lq.LabAblak._tabla_ir(t, [["a", "b", "c"], ["d", "e", "f"]])
    check("a tábla-író felveszi a sorokat", t.rowCount() == 2)
    check("...a helyes tartalommal",
          t.item(1, 2).text() == "f", t.item(1, 2).text())
    _it = t.item(0, 0)
    lq.LabAblak._tabla_ir(t, [["A", "b", "c"], ["d", "e", "f"]])
    check("⚠ a cella OBJEKTUM újrahasznosul (nem allokálunk újat)",
          t.item(0, 0) is _it)
    check("...de a szöveg frissül", t.item(0, 0).text() == "A")
    lq.LabAblak._tabla_ir(t, [["x", "y", "z"]])
    check("kevesebb sor → a tábla ZSUGORODIK", t.rowCount() == 1)
    lq.LabAblak._tabla_ir(t, [])
    check("üres lista → üres tábla", t.rowCount() == 0)


# ══ 3. A GYERTYA-RAJZ: vágás + összevonás (a VALÓDI akadás oka) ══════════
# ⚠ A felhasználó pontosított: az akadás akkor jött, amikor egy heti TICK-adatot
# töltött be és M1-re váltott. A lejátszás mérése simának mutatta — mert ott
# nincs NÉZET-változás. A húzásnál/nagyításnál viszont a `paint()` minden képen
# visszajátszotta a TELJES QPicture-t (gyertyánként 2 rajzoló-művelet):
#
#     gyertya   előtte      utána
#       6 000   13,8 ms    7,9 ms
#      25 000   60,0 ms   10,0 ms      ← itt volt a panasz
#      50 000  120,3 ms    9,8 ms
#     400 000  (~890 ms)  10,0 ms      ← KONSTANS
#
# A megoldás nem másik nyelv: a képernyőn pár ezer PIXELOSZLOP van, a munka
# 95%-a olyasmire ment el, ami nem is látszik.
if QT_OK:
    from tools.lab_qt import Gyertyak, MAX_OSZLOP

    _n = 20000
    _rng = np.random.default_rng(7)
    _c = 100 + np.cumsum(_rng.normal(0, 0.3, _n))
    _df = pd.DataFrame({"open": _c, "high": _c + 0.5,
                        "low": _c - 0.5, "close": _c + _rng.normal(0, 0.1, _n)})
    # ⚠ EGY KIUGRÓ CSÚCS: a összevonás NEM tüntetheti el (ugyanaz a hibafajta,
    # mint amikor a tick-deduplikáció levágta a high/low-t).
    _df.loc[12345, "high"] = 999.0
    _df.loc[12345, "low"] = -999.0
    g = Gyertyak(_df)

    _br = g.boundingRect()
    check("⚠ a boundingRect a TELJES adatsort fedi (az autoRange-hez)",
          _br.left() <= 0 and _br.right() >= _n, f"{_br.left()}..{_br.right()}")
    check("...és a teljes ÁRSÁVOT is (a kiugró csúccsal együtt)",
          _br.top() <= -999.0 and _br.bottom() >= 999.0,
          f"{_br.top():.0f}..{_br.bottom():.0f}")

    # Nézet nélkül a teljes sorra esik vissza → ÖSSZEVONÁS lép be.
    g._frissit()
    i0, i1, lepes = g._tart
    check("⚠ teljes nézetnél ÖSSZEVONÁS (LOD) lép be", lepes > 1, f"lépés={lepes}")
    check("...és a rajzolt oszlopok száma a korlát alatt marad",
          (i1 - i0 + lepes - 1) // lepes <= MAX_OSZLOP,
          f"{(i1 - i0 + lepes - 1)//lepes} <= {MAX_OSZLOP}")

    # ⚠ A LEGFONTOSABB: a vödör CSÚCSA/ALJA a valódi szélsőérték.
    _j0 = (12345 - i0) // lepes * lepes + i0
    _h = float(np.max(_df["high"].to_numpy()[_j0:_j0 + lepes]))
    _l = float(np.min(_df["low"].to_numpy()[_j0:_j0 + lepes]))
    check("⚠ az összevont vödör a VALÓDI szélsőértéket viszi (nem vág le csúcsot)",
          _h == 999.0 and _l == -999.0, f"{_l}..{_h}")

    # Szűk nézet → NINCS összevonás, és csak a látható szakasz épül.
    from PySide6 import QtCore

    g.viewRect = lambda: QtCore.QRectF(10000, 0, 300, 1)   # 300 gyertya látszik
    g._tart = None
    g._frissit()
    i0, i1, lepes = g._tart
    check("⚠ szűk nézetnél NINCS összevonás (minden gyertya külön)", lepes == 1)
    check("⚠ ...és csak a LÁTHATÓ szakasz épül fel (vágás)",
          (i1 - i0) < _n / 5, f"{i1 - i0} gyertya a {_n}-ből")
    check("...a látható tartomány BENNE van a megépítettben",
          i0 <= 10000 and i1 >= 10300, f"{i0}..{i1}")

    # A margó miatt a KIS görgetés nem kér újraépítést (különben villogna).
    _elozo = g._tart
    g.viewRect = lambda: QtCore.QRectF(10010, 0, 300, 1)
    g._frissit()
    check("⚠ kis görgetés NEM épít újra (margó — különben villogna)",
          g._tart == _elozo, f"{g._tart} vs {_elozo}")

    # Nagy ugrás viszont IGEN.
    g.viewRect = lambda: QtCore.QRectF(500, 0, 300, 1)
    g._frissit()
    check("...nagy ugrás viszont igen", g._tart != _elozo, str(g._tart))

print()
n, m = sum(results), len(results)
print(f"{n}/{m} teszt PASS")
sys.exit(0 if n == m else 1)

"""A labor MUNKATERÜLETE: több chart egy területen, dokkolható panelekkel.

A kérés: „legyen egy terület, ahová ezeket az ablakokat szabadon be lehetne
tenni, kivenni stb. Kb. ahogy az MT5-ben is van… amikor kirakjuk nagyba, akkor
tabulátorokon mutathatná az egyes chartokat… Innentől érthető, hogy míg chart
ablakból több van, számla állapot sorból csak egy." És utána: „az egyes ablakok
is fogd meg és vidd alapon tudjanak működni. Mint pl. a számla állapot sort is."

⚠ MIÉRT KELLETT. A több-ablakos szinkron (v3.59.0) külön TOP-LEVEL ablakokat
nyitott. Használatban azonnal kiderült, hogy ez nem elrendezhető: az ablakok
egymásra csúsznak, a tálcán szétszóródnak, és a KÖZÖS elemek (számla-állapot)
ablakonként duplázódnak.

A megoldás két Qt-eszköz, pontosan erre valók:
  * `QMdiArea`  — a chartok szabadon mozgathatók/átméretezhetők a területen
    belül, mozaik/lépcsős/sor/oszlop elrendezéssel, és TABULÁTOROS nézetre
    válthatók (ez az MT5 alsó chart-füleinek párja);
  * `QDockWidget` — a számla-állapot megfogható, áthúzható a négy oldal
    bármelyikére, LEBEGŐVÉ tehető és bezárható. Az állapotsor (`statusBar`)
    ezt nem tudja: oda van szögezve az ablak aljára.

⚠ CHARTBÓL TÖBB, SZÁMLA-SORBÓL EGY — de a sor az AKTÍV charté, és KIÍRJA,
melyiké. Minden chartnak saját forgatókönyve és backteszt-eredménye van (a
szinkron csak az IDŐT osztja meg); egy közös, jelöletlen sor azt sugallná, hogy
egy számláról szól, holott három külön kísérlet állapota.

⚠ A 2. VERZIÓRA MARAD (a felhasználó így kérte): a CHART kivétele külön,
lebegő ablakba. A `QMdiArea` ezt nem adja készen — a számla-panel viszont már
ma is kiszakítható, mert az dokk.
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


try:
    import pyqtgraph  # noqa: F401
    from PySide6 import QtWidgets  # noqa: F401
    QT_OK = True
except Exception as _e:
    QT_OK = False
    print(f"KIHAGYVA: nincs Qt/pyqtgraph ({type(_e).__name__}: {_e})")
    print("\n0/0 teszt PASS")
    sys.exit(0)

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore
from PySide6 import QtWidgets as QW

app = QW.QApplication.instance() or QW.QApplication([])

import tempfile

from tools import lab_qt
from tools.lab_qt import IDOSIKOK, LabAblak, Munkaterulet

# ⚠ A TESZT SOHA NE ÍRJA A FELHASZNÁLÓ ÁLLAPOTÁT. A `Munkaterulet.closeEvent`
# MENTI az elrendezést — e nélkül a sor az ÉLES `data/lab_elrendezes.json`-t
# írná, és a KÖVETKEZŐ futás abból indulna (elsőre pont ez történt: a „dokk
# alul ül" állítás azért bukott, mert egy korábbi teszt-futás mentése a jobb
# oldalra tette). Lásd `tests-must-never-write-real-config`.
lab_qt.ELRENDEZES_PATH = (Path(tempfile.mkdtemp(prefix="tf_ws_"))
                          / "elrendezes.json")
_ELES_ELR = ROOT / "data" / "lab_elrendezes.json"
_ELES_ELR_VOLT = _ELES_ELR.exists()

PAR, TOL, IG = "UsaTec", "2026-08-25", "2026-08-26"
mt = Munkaterulet(symbol=PAR, strategy="wpr_sma", tf_perc=15, tol=TOL, ig=IG)
mt.show()
app.processEvents()


# ══ 1. A terület és a chartok ═════════════════════════════════════════════
check("indításkor EGY chart van a területen", len(mt.chartok()) == 1)
check("a chart valóban a munkaterületen belül van (nem külön ablak)",
      mt.chartok()[0]._munkaterulet is mt)

c0 = mt.chartok()[0]
c0._uj_ablak()
app.processEvents()
c0._uj_ablak()
app.processEvents()
check("három chart", len(mt.chartok()) == 3)

# ⚠ REGRESSZIÓ: a „következő idősík" a HÍVÓ chartjából számolódott, ezért két
# egymás utáni „Új chart" UGYANAZT nyitotta meg (M15-ből kétszer H1).
_tfk = [c._tf.currentText() for c in mt.chartok()]
check("⚠ minden chart MÁS idősíkon (nincs duplikátum)",
      len(set(_tfk)) == len(_tfk), str(_tfk))
check("...és mind a szabad idősíkokból való",
      all(t in dict(IDOSIKOK).values() for t in _tfk), str(_tfk))

# ⚠ A SZÁMLA ÁLLAPOTA = a sor ÉS a nyitott/lezárt LISTÁK — mindkettő a KÖZÖS
# dokkba került. Egy chart egy NÉZET ugyanarra a kísérletre; a pozíciók viszont
# a kísérlethez tartoznak, nem a nézethez. Korábban kapcsolt ablakoknál ugyanaz
# a lista jelent meg háromszor, és a chart helyét vitte.
check("⚠ a chartok SAJÁT kötés-panelje rejtve (a dokk mutatja)",
      all(not c._fulek.isVisible() for c in mt.chartok()))
check("⚠ …és a jelölője sincs ott (egy kapcsoló, ami semmit nem kapcsol)",
      all(not c._kotesek.isVisible() for c in mt.chartok()))
check("⚠ a chartok SAJÁT számla-sora rejtve (a területen egy van belőle)",
      all(not c._szamla.isVisible() for c in mt.chartok()))
check("a dokkban ott a NYITOTT és a LEZÁRT tábla",
      sorted(mt._dokk_tablak) == ["lezart", "nyitott"])
check("⚠ a dokk és a chart oszlopai EGY forrásból valók",
      mt._dokk_tablak["nyitott"].columnCount()
      == mt.chartok()[0]._tablak["nyitott"].columnCount()
      and mt._dokk_tablak["lezart"].columnCount()
      == mt.chartok()[0]._tablak["lezart"].columnCount())
check("az új chartok automatikusan KAPCSOLTAK (közös idő)",
      all(c._szinkron is not None for c in mt.chartok()))


# ══ 2. Elrendezések ══════════════════════════════════════════════════════
def geo():
    return [sw.geometry() for sw in mt._mdi.subWindowList()]


mt._rendez(True)
app.processEvents()
g = geo()
check("⚠ VÍZSZINTES: azonos szélesség, egymás ALATT",
      len({r.width() for r in g}) == 1
      and sorted(r.y() for r in g) == [r.y() for r in sorted(g, key=lambda r: r.y())]
      and len({r.y() for r in g}) == 3,
      str([(r.x(), r.y(), r.width(), r.height()) for r in g]))

mt._rendez(False)
app.processEvents()
g = geo()
check("⚠ FÜGGŐLEGES: azonos magasság, egymás MELLETT",
      len({r.height() for r in g}) == 1 and len({r.x() for r in g}) == 3,
      str([(r.x(), r.y(), r.width(), r.height()) for r in g]))

mt._mdi.tileSubWindows()
app.processEvents()
check("mozaik: nem száll el, mindhárom ablak megvan",
      len(mt._mdi.subWindowList()) == 3)
mt._mdi.cascadeSubWindows()
app.processEvents()
g = geo()
check("lépcsős: eltolt kezdőpontok",
      len({(r.x(), r.y()) for r in g}) == 3,
      str([(r.x(), r.y()) for r in g]))


# ══ 3. Tabulátoros nézet (az MT5 alsó chart-fülei) ═══════════════════════
mt._tabos.setChecked(True)
mt._tabos_valt(True)
app.processEvents()
check("⚠ TABULÁTOROS nézetre vált", mt._mdi.viewMode() == QW.QMdiArea.TabbedView)
check("...a fülek ALUL vannak (mint az MT5-ben)",
      mt._mdi.tabPosition() == QW.QTabWidget.South)
check("...és a chartok megmaradnak", len(mt.chartok()) == 3)
mt._tabos_valt(False)
app.processEvents()
check("vissza a szabad elrendezésre",
      mt._mdi.viewMode() == QW.QMdiArea.SubWindowView)
# ⚠ A sor/oszlop rendezés kapcsolja vissza magától, ha tabos nézetben nyomják.
mt._tabos.setChecked(True)
mt._tabos_valt(True)
mt._rendez(True)
app.processEvents()
check("⚠ tabos nézetben az elrendezés visszavált (különben nem látszana)",
      mt._mdi.viewMode() == QW.QMdiArea.SubWindowView)


# ══ 4. FOGD ÉS VIDD: a számla-panel dokk ════════════════════════════════
d = mt._szamla_dokk
F = QW.QDockWidget
check("⚠ a számla-panel MOZGATHATÓ", bool(d.features() & F.DockWidgetMovable))
check("⚠ …LEBEGTETHETŐ (kiszakítható külön ablakba)",
      bool(d.features() & F.DockWidgetFloatable))
check("…és bezárható", bool(d.features() & F.DockWidgetClosable))
check("alapból alul ül",
      mt.dockWidgetArea(d) == QtCore.Qt.BottomDockWidgetArea)
check("mind a négy oldalra vihető",
      d.allowedAreas() == QtCore.Qt.AllDockWidgetAreas)

d.setFloating(True)
app.processEvents()
check("⚠ tényleg kiszakítható", d.isFloating())
d.setFloating(False)
mt.addDockWidget(QtCore.Qt.RightDockWidgetArea, d)
app.processEvents()
check("⚠ és áthúzható másik oldalra",
      mt.dockWidgetArea(d) == QtCore.Qt.RightDockWidgetArea)
check("a menüből ki-be kapcsolható", d.toggleViewAction() is not None)
check("az elrendezés MENTHETŐ (a jövőbeli megjegyzéshez)",
      len(bytes(mt.saveState())) > 0)


# ══ 5. EGY számla-sor, de MEGNEVEZVE ════════════════════════════════════
# ⚠ AZ AKTÍV CHARTOT RÖGZÍTENI KELL. Az első változatom ezt elmulasztotta, és
# a „nem aktív" chart éppen az aktív volt — a teszt a saját feltevését mérte.
_ch = mt.chartok()
_sw = {sw.widget(): sw for sw in mt._mdi.subWindowList()}
mt._mdi.setActiveSubWindow(_sw[_ch[1]])
app.processEvents()
check("az aktív chart az, amit beállítottunk", mt._aktiv_chart() is _ch[1])

mt._szamla_jott(_ch[1], "egyenleg 1000,00")
check("⚠ a sor KIÍRJA, MELYIK charté (saját forgatókönyv, saját eredmény)",
      _ch[1]._sym.currentText() in mt._szamla.text()
      and "egyenleg" in mt._szamla.text(), mt._szamla.text())
mt._szamla_jott(_ch[2], "MASIK CHART")
check("⚠ a NEM AKTÍV chart frissítése nem írja felül a sort",
      "MASIK CHART" not in mt._szamla.text(), mt._szamla.text())
mt._mdi.setActiveSubWindow(_sw[_ch[2]])
app.processEvents()
check("⚠ …de az AKTÍVRA váltva azonnal az övé látszik",
      _ch[2]._sym.currentText() in mt._szamla.text(), mt._szamla.text())
# ⚠ A NÉV AKKOR IS KELL, HA NINCS ÁLLAPOT: egy chart, amin még nem futott
# forgatókönyv, üres állapotot ad. Ha a sor ilyenkor teljesen kiürülne, nem
# lehetne megkülönböztetni a „nincs mit mutatni" és a „nem frissül" esetet.
mt._szamla_kiir(_ch[0], "")
check("⚠ állapot nélkül is látszik, MELYIK chartról van szó",
      _ch[0]._sym.currentText() in mt._szamla.text()
      and "—" in mt._szamla.text(), mt._szamla.text())
mt._szamla_kiir(None, "")
check("chart nélkül üres a sor", mt._szamla.text() == "")


# ══ 5b. A KÖTÉS-LISTÁK a közös dokkba jutnak ════════════════════════════
# ⚠ A TELJES LÁNC, nem csak a végpont: a chart frissül → értesíti a
# munkaterületet → az kiírja a dokkba. Ha csak a `_kotesek_kiir`-t hívnám
# közvetlenül, a lánc közepe (az értesítés) méretlen maradna.
class _Res:
    def __init__(self, trades):
        self.trades = trades


class _Tr:
    """Egy LEZÁRT kötés — annyi mezővel, amennyit a sor-építő olvas."""
    def __init__(self, t0, t1):
        import pandas as _pd
        self.open_time, self.close_time = t0, t1
        self.direction, self.open_price, self.close_price = "BUY", 100.0, 102.0
        self.sl_points, self.point_size, self.tp = 100.0, 0.01, 102.0
        self.pnl_usd, self.risk_usd, self.status = 20.0, 10.0, "TP"
        self.risk_free = False


_akt = mt._aktiv_chart()
_idx = _akt._chart.index
_akt._eredmeny = {"res": _Res([_Tr(_idx[1], _idx[5])]), "balance": 1000.0}
_akt._kurzor = len(_idx) - 1
_akt._listak_frissit()
app.processEvents()
check("⚠ a chart kiszámolta a sorokat (rejtett saját panel MELLETT is)",
      len(_akt._kotet_sorok[1] if hasattr(_akt, "_kotet_sorok")
          else _akt._kotes_sorok[1]) == 1,
      str(_akt._kotes_sorok))
check("⚠ …és a KÖZÖS DOKK megkapta (a teljes lánc)",
      mt._dokk_tablak["lezart"].rowCount() == 1,
      f"{mt._dokk_tablak['lezart'].rowCount()} sor")

# Chart-váltásnál AZONNAL a másiké látszik (nem várunk a kurzorára).
_masik = [c for c in mt.chartok() if c is not _akt][0]
mt._mdi.setActiveSubWindow(
    {sw.widget(): sw for sw in mt._mdi.subWindowList()}[_masik])
app.processEvents()
check("⚠ chart-váltáskor a dokk AZONNAL a másik chartét mutatja",
      mt._dokk_tablak["lezart"].rowCount() == 0,
      f"{mt._dokk_tablak['lezart'].rowCount()} sor (a másiknak nincs kötése)")


# ══ 6. A HATÁR: a LabAblak önállóan is megáll ═══════════════════════════
# ⚠ Ez a 2. verzió (kiszakítás külön ablakba) előfeltétele — és a `--egy`
# parancssori kapcsolóé is. Ha a chart csak munkaterületen belül működne, a
# kiszakítás szerkezeti akadályba ütközne.
w = LabAblak(symbol=PAR, tf_perc=5, tol=TOL, ig=IG)
w.betolt()
check("⚠ a chart MUNKATERÜLET NÉLKÜL is betölt (a 2. verzió előfeltétele)",
      w._chart is not None and len(w._chart) > 0,
      f"{len(w._chart) if w._chart is not None else 0} gyertya")
check("...és ilyenkor a saját számla-sora látszik",
      w._munkaterulet is None and w._szamla_figyelo is None)
w.close()

_src = (ROOT / "tools" / "lab_qt.py").read_text(encoding="utf-8")
check("a belépési pont a MUNKATERÜLETET nyitja", "oszt = LabAblak if a.egy else Munkaterulet" in _src)
check("...de a régi, egy-ablakos mód megmarad (`--egy`)", '"--egy"' in _src)

mt.close()

check("⚠ a teszt NEM hozta létre az éles data/lab_elrendezes.json-t",
      _ELES_ELR.exists() == _ELES_ELR_VOLT,
      f"volt={_ELES_ELR_VOLT} van={_ELES_ELR.exists()}")

print()
n, m = sum(results), len(results)
print(f"{n}/{m} teszt PASS")
sys.exit(0 if n == m else 1)

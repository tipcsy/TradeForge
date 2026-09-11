"""A labor ELRENDEZÉSE megmarad két indítás közt (v3.61.0).

A kérés: „az elrendezés megjegyzése két indítás közt".

Mit jegyzünk meg: az ablak mérete/helye, a DOKKOK elrendezése (a számla-panel
melyik oldalon ül, lebeg-e), a nézet (szabad vagy tabulátoros), és a CHARTOK —
párral, stratégiával, idősíkkal, időszakkal, al-ablak-geometriával, valamint a
két kapcsolójukkal (kötés-tábla, kapcsolt idő).

⚠ A GEOMETRIÁT A QT SZERIALIZÁLJA (`saveGeometry`/`saveState`, base64-ben), a
CHARTOKAT viszont NÉVVEL írjuk le. Egy Qt-blob nem mondaná meg, MIT kell újra
betölteni — az al-ablak üresen jönne vissza.

⚠ A PARANCSSOR NYER. `--symbol`-lal indítva azt akarja látni a felhasználó, nem
azt, amit két hete bezárt. Mentett chart-készletet csak argumentum NÉLKÜLI
indításnál töltünk vissza; a keret (ablakméret, dokkok) viszont mindig.

⚠ ÉS A NÉMASÁG ELLEN (a nap visszatérő leckéje): a HIÁNYZÓ fájl az első indítás,
az NORMÁLIS → csend. A SÉRÜLT fájl elveszett beállítás → naplózunk. A configból
kikerült pár chartja sem tűnhet el szó nélkül.

⚠ A TESZT SOHA NEM ÍRJA AZ ÉLES `data/lab_elrendezes.json`-t: a modul
`ELRENDEZES_PATH`-át ideiglenes fájlra cseréli, és a végén ellenőrzi, hogy az
éles fájl érintetlen.
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
    print(f"KIHAGYVA: nincs Qt/pyqtgraph ({type(_e).__name__}: {_e})")
    print("\n0/0 teszt PASS")
    sys.exit(0)

import hashlib
import json
import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore
from PySide6 import QtWidgets as QW

app = QW.QApplication.instance() or QW.QApplication([])

from tools import lab_qt

# ── Az ÉLES fájl lenyomata: a teszt nem nyúlhat hozzá ────────────────────
_ELES = ROOT / "data" / "lab_elrendezes.json"
_ELES_ELOTT = (hashlib.sha1(_ELES.read_bytes()).hexdigest()
               if _ELES.exists() else None)

_TMP = Path(tempfile.mkdtemp(prefix="tf_lab_elrendezes_"))
lab_qt.ELRENDEZES_PATH = _TMP / "elrendezes.json"

PAR, TOL, IG = "UsaTec", "2026-08-25", "2026-08-26"


class Fogo(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.recs = []

    def __enter__(self):
        self._lg = logging.getLogger(lab_qt.__name__)
        self._r = self._lg.level
        self._lg.setLevel(logging.DEBUG)
        self._lg.addHandler(self)
        logging.disable(logging.NOTSET)
        return self

    def __exit__(self, *a):
        self._lg.removeHandler(self)
        self._lg.setLevel(self._r)
        logging.disable(logging.INFO)
        return False

    def emit(self, r):
        self.recs.append(r)

    def szintek(self):
        return [r.levelname for r in self.recs]


# ══ 1. HIÁNYZÓ fájl = első indítás → CSEND ═══════════════════════════════
with Fogo() as f:
    d = lab_qt.elrendezes_olvas()
check("hiányzó elrendezés → üres, NÉMÁN (ez az első indítás)",
      d == {} and not f.recs, str(f.szintek()))


# ══ 2. MENTÉS és VISSZAÁLLÍTÁS ═══════════════════════════════════════════
mt = lab_qt.Munkaterulet(symbol=PAR, strategy="wpr_sma", tf_perc=15,
                         tol=TOL, ig=IG)
mt.show()
app.processEvents()
mt.chartok()[0]._uj_ablak()
app.processEvents()
mt._rendez(True)
mt.addDockWidget(QtCore.Qt.RightDockWidgetArea, mt._szamla_dokk)
app.processEvents()

_elott = [(c._sym.currentText(), c._tf.currentText(),
           c._kotesek.isChecked(), c._kapcs.isChecked()) for c in mt.chartok()]
_geo_elott = [sw.geometry().getRect() for sw in mt._mdi.subWindowList()]
mt.close()
app.processEvents()

check("bezáráskor MENT (külön gomb nélkül)", lab_qt.ELRENDEZES_PATH.exists())
_d = json.loads(lab_qt.ELRENDEZES_PATH.read_text(encoding="utf-8"))
check("a chartokat NÉVVEL írjuk le (nem csak Qt-blobként)",
      len(_d.get("chartok") or []) == 2
      and _d["chartok"][0].get("symbol") == PAR,
      str([c.get("symbol") for c in _d.get("chartok") or []]))
check("...és a keretet a Qt szerializálja",
      bool(_d.get("ablak_geometria")) and bool(_d.get("ablak_allapot")))

mt2 = lab_qt.Munkaterulet()          # argumentum NÉLKÜL → visszaáll
mt2.show()
app.processEvents()
_utan = [(c._sym.currentText(), c._tf.currentText(),
          c._kotesek.isChecked(), c._kapcs.isChecked()) for c in mt2.chartok()]
check("⚠ a CHARTOK visszaálltak (pár, idősík, kapcsolók)", _elott == _utan,
      f"{_elott} vs {_utan}")
check("⚠ az AL-ABLAKOK geometriája is",
      [sw.geometry().getRect() for sw in mt2._mdi.subWindowList()] == _geo_elott)
check("⚠ a DOKK a jobb oldalon maradt",
      mt2.dockWidgetArea(mt2._szamla_dokk) == QtCore.Qt.RightDockWidgetArea)
mt2.close()
app.processEvents()


# ══ 3. A MENTETT ELRENDEZÉS NYER — a parancssor csak `--uj`-jal ═══════════
# ⚠ MEGFORDÍTVA (v3.70.2). Az első szabály itt „a parancssor nyer" volt: egy
# `--symbol`/`--from` kapcsolóval indítva a mentett elrendezés NÉMÁN kimaradt,
# és a felhasználó azt látta, hogy „nem jegyzi meg" (három ablak, görgetés,
# AutoFit — minden indításnál újra). A tiszta lapot az `--uj` kéri.
mt3 = lab_qt.Munkaterulet(symbol=PAR, tf_perc=5, tol=TOL, ig=IG)
mt3.show()
app.processEvents()
check("⚠ `--symbol`-lal indítva IS a mentett készlet jön (2 chart)",
      len(mt3.chartok()) == 2,
      f"{len(mt3.chartok())} chart, {[c._tf.currentText() for c in mt3.chartok()]}")
check("...és a KERET (dokk-hely) is visszaáll",
      mt3.dockWidgetArea(mt3._szamla_dokk) == QtCore.Qt.RightDockWidgetArea)
mt3.close()
app.processEvents()
mt3 = lab_qt.Munkaterulet(symbol=PAR, tf_perc=5, tol=TOL, ig=IG, uj=True)
mt3.show()
app.processEvents()
check("⚠ `--uj`-jal viszont a kért chart jön (tiszta lap)",
      len(mt3.chartok()) == 1 and mt3.chartok()[0]._tf.currentText() == "M5",
      f"{len(mt3.chartok())} chart, {mt3.chartok()[0]._tf.currentText()}")
mt3.close()
app.processEvents()


# ══ 4. SÉRÜLT és ELAVULT fájl — NEM némán ════════════════════════════════
lab_qt.ELRENDEZES_PATH.write_text("{ ez nem json", encoding="utf-8")
with Fogo() as f:
    d = lab_qt.elrendezes_olvas()
check("⚠ SÉRÜLT fájl → üres, de NAPLÓZ (nem ugyanaz, mint a hiányzó)",
      d == {} and any(s in ("WARNING", "ERROR") for s in f.szintek()),
      str(f.szintek()))

lab_qt.ELRENDEZES_PATH.write_text(
    json.dumps({"verzio": 999, "chartok": [{"symbol": PAR}]}), encoding="utf-8")
with Fogo() as f:
    d = lab_qt.elrendezes_olvas()
check("⚠ ELTÉRŐ VERZIÓ → kihagyva, és megmondja", d == {} and bool(f.recs),
      str(f.szintek()))

# Indulás sérült fájllal: NEM szabad elszállnia.
lab_qt.ELRENDEZES_PATH.write_text("{{{", encoding="utf-8")
try:
    mt4 = lab_qt.Munkaterulet(symbol=PAR, tf_perc=15, tol=TOL, ig=IG)
    mt4.show()
    app.processEvents()
    check("⚠ sérült elrendezéssel is ELINDUL (alapelrendezéssel)",
          len(mt4.chartok()) == 1)
    mt4.close()
except Exception as ex:
    check("⚠ sérült elrendezéssel is ELINDUL", False, f"{type(ex).__name__}: {ex}")
app.processEvents()


# ══ 5. A configból KIKERÜLT pár chartja nem tűnhet el szó nélkül ═════════
lab_qt.ELRENDEZES_PATH.write_text(json.dumps({
    "verzio": lab_qt.ELRENDEZES_VERZIO,
    "chartok": [{"symbol": "NINCS_ILYEN_PAR", "tf": 15},
                {"symbol": PAR, "tf": 15, "tol": TOL, "ig": IG}],
}), encoding="utf-8")
with Fogo() as f:
    mt5 = lab_qt.Munkaterulet()
    mt5.show()
    app.processEvents()
check("⚠ az ismeretlen pár chartja KIMARAD, de SZÓL róla",
      len(mt5.chartok()) == 1
      and any("NINCS_ILYEN_PAR" in r.getMessage() for r in f.recs),
      f"{len(mt5.chartok())} chart, {f.szintek()}")

# „Elrendezés elfelejtése"
mt5._elrendezes_felejt()
check("az Elrendezes-elfelejtes torli a fajlt",
      not lab_qt.ELRENDEZES_PATH.exists())
mt5.close()
app.processEvents()


# ══ 6. AZ ÉLES FÁJL ÉRINTETLEN ═══════════════════════════════════════════
_most = (hashlib.sha1(_ELES.read_bytes()).hexdigest() if _ELES.exists() else None)
check("⚠ a teszt NEM írta az éles data/lab_elrendezes.json-t",
      _most == _ELES_ELOTT, f"{_ELES_ELOTT} → {_most}")

print()
n, m = sum(results), len(results)
print(f"{n}/{m} teszt PASS")
sys.exit(0 if n == m else 1)

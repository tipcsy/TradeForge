"""A labor POZÍCIÓ-DOBOZA (TradingView-szerű).

A kérés: „A BUY-nál amikor rányomok, akkor előjön a képen látható ablak…
minden esetben az Entry pointra húzná ennek az ablaknak a közepét. Látható,
hogy van rajta 4 pont, a négy pont mutatja az árfolyamot, és folyamatosan
számolja az értéket. A jobb oldali ponttal csak a szélességét tudjuk állítani,
aminek igazából csak annyi a szerepe, hogy tudjuk szűkíteni, ha véget ért a
pozíció. * Ebben egyetlen egy van, hogy ez még nem a tényleges pozíciónyitás,
hanem ha a közepén lévő nyomógombra rákattintunk, akkor fogja ténylegesen
megnyitni."  És utána: „maradjon szerkeszthető megnyitás után is. Így
egyszerűbb lesz a SL-t is BE-be húzni."  Illetve: „A vonalak mindenhol, a doboz
csak az aktív ablakban."

⚠ AMI SZÁNDÉKOSAN NINCS A DOBOZBAN: a PÉNZ-érték (lot, kockázat devizában). A
méretezés a `core/risk_manager`-é. Ha a labor is kiszámolná, két méretező út
lenne — a projekt visszatérő kárforrása —, ráadásul a naiv képlet HAZUDNA, mert
a `min_lot` és a slot-keret felülírja (lásd `min-lot-forces-over-risk`). Amit a
doboz mutat — ár, távolság pontban és %-ban, R:R —, az a belépőből és a stopból
egyértelműen adódik, számla-modell nélkül. Ezt a határt teszt is őrzi lent.

⚠ A DOBOZ A CSERÉLHETŐ RÉSZ, A MOTOR NEM. A megnyitás itt jelölés (`nyitva`),
nem kötés: a `lab_scenario.futtat()` továbbra is a belépő IDEJÉT, IRÁNYÁT és
SZINTJEIT kapja, semmi mást. Ezért marad a doboz megnyitás után is
szerkeszthető — a laborban épp az a kérdés, MIT csinálnál a nyitott pozícióval.
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

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile

import pandas as pd
from PySide6 import QtCore
from PySide6 import QtWidgets as QW

app = QW.QApplication.instance() or QW.QApplication([])

from tools import lab_qt
from tools.lab_qt import Belepo, LabAblak, Munkaterulet

# ⚠ A TESZT SOHA NE ÍRJA A FELHASZNÁLÓ ÁLLAPOTÁT (lásd
# `tests-must-never-write-real-config`). A `Munkaterulet.closeEvent` MENT.
lab_qt.ELRENDEZES_PATH = (Path(tempfile.mkdtemp(prefix="tf_box_"))
                          / "elrendezes.json")
_ELES_ELR = ROOT / "data" / "lab_elrendezes.json"
_ELES_ELR_VOLT = _ELES_ELR.exists()

PAR, TOL, IG = "UsaTec", "2026-08-25", "2026-08-26"

w = LabAblak(symbol=PAR, tf_perc=15, tol=TOL, ig=IG)
w.betolt()
# ⚠ SHOW KELL. Egy meg nem jelenített ablak GYEREKEI mindig `isVisible() ==
# False`-t mondanak, függetlenül a saját beállításuktól — a doboz gomb-találata
# pedig épp ezt kérdezi. Ez a csapda ebben a projektben már kétszer elsült.
w.show()
app.processEvents()

check("betöltött chart", w._chart is not None and len(w._chart) > 0,
      f"{0 if w._chart is None else len(w._chart)} gyertya")

# ── Egy BUY-terv a chart közepére ────────────────────────────────────────
_t_be = w._chart.index[len(w._chart) // 2]
b = Belepo(_t_be, "BUY", None, 2.0)
b.sl = w._alap_sl(_t_be, "BUY")
w._belepok.append(b)
w._valasztott = b
w._terv_valtozott()
app.processEvents()

_be_ar = w._be_ar(b.ido)
check("a belépőnek van ára és stopja",
      _be_ar is not None and b.sl is not None, f"be={_be_ar} sl={b.sl}")


# ══ 1. A NÉGY PONT ═══════════════════════════════════════════════════════
# A „4 pont" a felhasználó képén: a belépő, a cél, a stop és a jobb oldali
# szélesség-fogó. Az első három HÚZHATÓ vonal volt már; a doboz a feliratokat és
# a negyedik fogót adja hozzá.
for _nev in ("vonal", "sl_vonal", "tp_vonal", "szel"):
    check(f"megvan a fogó: {_nev}", w._bel(b, _nev) is not None)
for _nev in ("cimke_tp", "cimke_sl", "cimke_kozep"):
    check(f"megvan a felirat: {_nev}", w._bel(b, _nev) is not None)

_ck = w._bel(b, "cimke_kozep")
check("⚠ a gomb a BELÉPŐ ÁRÁN ül (a doboz közepe az entry point)",
      abs(_ck.pos().y() - _be_ar) < 1e-9, f"{_ck.pos().y()} vs {_be_ar}")

_x1 = w._tengely.hol(int(b.ido.timestamp()))
_x2 = w._sav_vege(b, _x1)
check("...és vízszintesen a doboz közepén",
      abs(_ck.pos().x() - (_x1 + (_x2 - _x1) * w.DOBOZ_GOMB_X)) < 1e-6)
check("a szélesség-fogó a doboz JOBB szélén áll",
      abs(float(w._bel(b, "szel").value()) - _x2) < 1e-6)

check("a cél-felirat a CÉLÁRON",
      abs(w._bel(b, "cimke_tp").pos().y() - b.tp_ar(_be_ar)) < 1e-9)
check("a stop-felirat a STOP-áron",
      abs(w._bel(b, "cimke_sl").pos().y() - b.sl) < 1e-9)


# ══ 2. „FOLYAMATOSAN SZÁMOLJA AZ ÉRTÉKET" ════════════════════════════════
_cel_sz, _stop_sz, _kozep_sz = w._doboz_szoveg(b, _be_ar)
check("a felirat kiírja a CÉLÁRAT", w._ar(b.tp_ar(_be_ar)) in _cel_sz, _cel_sz)
check("a felirat kiírja a STOP-árat", w._ar(b.sl) in _stop_sz, _stop_sz)
check("⚠ a távolság PONTBAN is (a projekt szabálya: pontban mérünk, nem pipben)",
      "pont" in _cel_sz.lower() or "point" in _cel_sz.lower(), _cel_sz)
check("...és %-ban is", "%" in _cel_sz, _cel_sz)
check("a középső gomb R:R-t mutat", "R:R" in _kozep_sz, _kozep_sz)
check("a középső gomb az IRÁNYT is", "BUY" in _kozep_sz, _kozep_sz)

# A stop elhúzása → a szám AZONNAL követi (nem csak elengedéskor).
_reg_cel, _reg_stop, _ = w._doboz_szoveg(b, _be_ar)
_uj_sl = b.sl - abs(_be_ar - b.sl) * 0.5      # kétszer messzebb
w._bel(b, "sl_vonal").setValue(_uj_sl)         # ez HÍVJA a `_sl_mozgott`-ot
app.processEvents()
check("⚠ a stop húzása a MODELLBE is beírja az új szintet",
      abs(b.sl - _uj_sl) < 1e-9, f"{b.sl} vs {_uj_sl}")
check("⚠ a felirat HÚZÁS KÖZBEN frissül (nem csak elengedéskor)",
      w._bel(b, "cimke_sl").toPlainText() != _reg_stop,
      w._bel(b, "cimke_sl").toPlainText())
check("...és a cél-felirat is (a TP a stop függvénye)",
      w._bel(b, "cimke_tp").toPlainText() != _reg_cel)
check("⚠ a felirat NEM ÉPÜLT ÚJRA — ugyanaz a Qt-objektum maradt",
      w._bel(b, "cimke_sl") is not None
      and w._bel(b, "sl_vonal") is not None)

# ⚠ A HÚZÁS KÖZBENI ÚJRAÉPÍTÉS a kézben maradt elemen szállna el. Az összes
# húzás-kezelő `rajzol=False`-szal hív — ezt kódban is rögzítjük.
_src = (ROOT / "tools" / "lab_qt.py").read_text(encoding="utf-8")
_blokk = _src[_src.index("def _doboz_szelesseg"):
              _src.index("def _doboz_gomb_talalat")]
check("⚠ a szélesség-húzás sem épít újra (rajzol=False)",
      "_terv_valtozott(rajzol=False)" in _blokk)


# ══ 3. A JOBB OLDALI FOGÓ: CSAK a szélesség ══════════════════════════════
_sl_elott, _rr_elott, _ido_elott = b.sl, b.rr, b.ido
_szel = w._bel(b, "szel")
_uj_x2 = _x1 + max(2.0, (_x2 - _x1) * 0.4)
_szel.setValue(_uj_x2)
app.processEvents()
check("⚠ a fogó a pozíció VÉGÉT állítja (időben)", b.veg is not None, str(b.veg))
check("...és a vég a belépő UTÁN van", b.veg is not None and b.veg > b.ido)
check("⚠ a fogó SEM az árat, SEM a belépő idejét nem mozgatja",
      b.sl == _sl_elott and b.rr == _rr_elott and b.ido == _ido_elott)
check("⚠ a sáv is szűkült vele (nem csak a vonal csúszott el)",
      abs(w._bel(b, "kock").rect().right() - _uj_x2) < 1e-6,
      f"{w._bel(b, 'kock').rect().right()} vs {_uj_x2}")

# ⚠ A KÉZI VÉG NYER. Enélkül a következő lejátszó-lépésnél a sáv visszanőne a
# kurzorig, és a fogó használhatatlan volna.
w._kurzor = len(w._chart) - 1
check("⚠ a KÉZI vég erősebb a lejátszó kurzoránál",
      abs(w._sav_vege(b, _x1) - _uj_x2) < 1.5,
      f"{w._sav_vege(b, _x1)} vs {_uj_x2}")
w._kurzor = None

# A sávkövetés vigye magával a fogót és a gombot is.
w._sav_frissit()
app.processEvents()
check("a sávkövetés után a fogó a sáv szélén maradt",
      abs(float(w._bel(b, "szel").value())
          - w._bel(b, "kock").rect().right()) < 1e-6)
check("...és a gomb a szűkített doboz közepén",
      abs(w._bel(b, "cimke_kozep").pos().x()
          - (_x1 + (_uj_x2 - _x1) * w.DOBOZ_GOMB_X)) < 1.0)

# Visszafelé nem enged: a vég sosem előzheti meg a belépőt.
_veg_elott = b.veg
_szel.setValue(_x1 - 10.0)
app.processEvents()
check("⚠ a vég NEM kerülhet a belépő elé", b.veg == _veg_elott, str(b.veg))
_szel.setValue(_uj_x2)
app.processEvents()


# ══ 4. A KÖZÉPSŐ GOMB: ez nyitja meg — és TÉNYLEG rákattintunk ═══════════
class _Klikk:
    """Jelenet-kattintás utánzat: `_kattintas` ennyit használ belőle.

    ⚠ SZÁNDÉKOSAN A `_kattintas`-ON ÁT megyünk, nem a `_doboz_megnyit`-en. A
    kérdés nem az, hogy a metódus működik-e, hanem hogy a gombra KATTINTVA
    elérhető-e — a `TextItem` ugyanis nem ad kattintás-jelzést, a találatot
    kézzel számoljuk. Egy közvetlen hívás pont ezt a részt hagyná ki."""

    def __init__(self, scene_pos):
        self._p = scene_pos

    def button(self):
        return QtCore.Qt.LeftButton

    def scenePos(self):
        return self._p


def _klikk_a_gombra(ablak, belepo):
    _c = ablak._bel(belepo, "cimke_kozep")
    _kozep = _c.mapRectToView(_c.boundingRect()).center()
    ablak._kattintas(_Klikk(ablak._vb.mapViewToScene(_kozep)))
    app.processEvents()


check("kattintás ELŐTT a terv még NEM pozíció", b.nyitva is False)
_klikk_a_gombra(w, b)
check("⚠ a KÖZÉPSŐ GOMBRA kattintva nyílik meg a pozíció", b.nyitva is True)
check("...és a belépő-vonal címkéje is jelzi",
      "●" in (w._bel(b, "vonal").label.format or ""),
      str(w._bel(b, "vonal").label.format))
check("...és a gomb felirata átvált",
      "R:R" in w._bel(b, "cimke_kozep").toPlainText()
      and w._doboz_szoveg(b, w._be_ar(b.ido))[2]
      != _kozep_sz, w._bel(b, "cimke_kozep").toPlainText())

_klikk_a_gombra(w, b)
check("⚠ újra rákattintva vissza is vonható (nem egyirányú ajtó)",
      b.nyitva is False)
_klikk_a_gombra(w, b)

# ⚠ RAJZ-MÓD NÉLKÜL is működnie kell — és BUY-módban sem tehet le ÚJ belépőt a
# gomb helyére, mert a gomb hamarabb fog.
_db = len(w._belepok)
w._mod = "BUY"
_klikk_a_gombra(w, b)
check("⚠ BUY-módban a gombra kattintás NEM tesz le új belépőt",
      len(w._belepok) == _db, f"{len(w._belepok)} vs {_db}")
w._mod = None
if not b.nyitva:                       # a fenti kattintás visszavont — nyissuk
    _klikk_a_gombra(w, b)


# ══ 5. MEGNYITÁS UTÁN IS SZERKESZTHETŐ ═══════════════════════════════════
# „Az első: maradjon szerkeszthető megnyitás után is. Így egyszerűbb lesz a
# SL-t is BE-be húzni."
check("nyitott pozíció", b.nyitva is True)
check("⚠ a stop-vonal nyitva is HÚZHATÓ", bool(w._bel(b, "sl_vonal").movable))
check("⚠ a cél-vonal is", bool(w._bel(b, "tp_vonal").movable))
check("⚠ a szélesség-fogó is", bool(w._bel(b, "szel").movable))

# Az SL BE-be húzása: a nyitóárra.
w._bel(b, "sl_vonal").setValue(_be_ar)
app.processEvents()
check("⚠ nyitott pozíción az SL BE-be húzható (egy mozdulat)",
      abs(b.sl - _be_ar) < 1e-9, f"{b.sl} vs {_be_ar}")
check("...és a pozíció NYITVA maradt tőle", b.nyitva is True)
# Vissza egy használható stopra a további tesztekhez.
w._bel(b, "sl_vonal").setValue(_uj_sl)
app.processEvents()


# ══ 6. A HATÁR: a doboz NEM méretez ══════════════════════════════════════
# ⚠ SZÓHATÁRRAL, NEM RÉSZSZÖVEGGEL. A naiv `"lot" in kod` minden `self._plot`-ra
# igazat mond — a teszt így a saját rajzoló-hívásaira bukott el, nem valódi
# méretezésre. (Ugyanez a csapda a projektben már többször elsült.)
import re as _re

_doboz = _src[_src.index("══ A POZÍCIÓ-DOBOZ"):_src.index("def _trail_vonalak")]
_kod = chr(10).join(_s.split("#")[0] for _s in _doboz.splitlines())
_talalt = [_k for _k in ("lot", "lots", "account_risk", "balance", "equity",
                         "contract_size", "pv1_point", "risk_manager")
           if _re.search(r"\b" + _k + r"\b", _kod)]
check("⚠ a doboz NEM számol lotot/pénz-kockázatot (az a risk_manageré)",
      not _talalt, "méretezés szivárgott a laborba: " + str(_talalt))
check("⚠ …és ezt a kód meg is INDOKOLJA (különben a következő olvasó beteszi)",
      "risk_manager" in _doboz and "min_lot" in _doboz)

# ⚠ A LAB_SCENARIO SEM LÁTHATJA. A megnyitás jelölés, nem kötés: a motor a
# belépő idejét/irányát/szintjeit kapja, semmi mást.
_scn = (ROOT / "tools" / "lab_scenario.py").read_text(encoding="utf-8")
check("⚠ a motor nem ismer `opened`/`end` kulcsot (a doboz a laboré)",
      '"opened"' not in _scn and "'opened'" not in _scn
      and '"end"' not in _scn)


# ══ 7. MENTÉS ÉS VISSZAOLVASÁS ═══════════════════════════════════════════
# ⚠ MENTÉS VISSZAOLVASÁS NÉLKÜL FÉLKÉSZ (`lab-mt5-like-position-lines`).
_fk = w._forgatokonyv()
_e = [x for x in _fk["entries"] if x["direction"] == "BUY"][0]
check("a mentés viszi a megnyitás-jelölést", _e.get("opened") is True, str(_e))
check("...és a doboz VÉGÉT is", _e.get("end"), str(_e))

w2 = LabAblak(symbol=PAR, tf_perc=15, tol=TOL, ig=IG)
w2.betolt()
w2.show()
w2.forgatokonyv_betolt(_fk)
app.processEvents()
_b2 = w2._belepok[0]
check("⚠ visszaolvasva megmarad a megnyitás", _b2.nyitva is True)
# ⚠ PERCRE, SZÖVEGKÉNT. A forgatókönyv percre kerekítve, IDŐZÓNA NÉLKÜL tárol
# (`str(...)[:16]`) — ez a belépő idejénél is így van, tehát a vég ugyanazt az
# alakot kapja. Egy nyers kivonás itt tz-aware↔naive hibán szállna el, ami a
# tárolás alakját kérdezné, nem azt, hogy MEGMARADT-E az érték.
check("⚠ …és a doboz vége is",
      _b2.veg is not None and str(_b2.veg)[:16] == str(b.veg)[:16],
      f"{_b2.veg} vs {b.veg}")


# ══ 8. „A VONALAK MINDENHOL, A DOBOZ CSAK AZ AKTÍV ABLAKBAN" ═════════════
mt = Munkaterulet(symbol=PAR, strategy=None, tf_perc=15, tol=TOL, ig=IG)
mt.show()
app.processEvents()
c0 = mt.chartok()[0]
c0._uj_ablak()
app.processEvents()
_chartok = mt.chartok()
check("két chart a munkaterületen", len(_chartok) == 2)

for c in _chartok:
    if not c._rajz_megosztva:
        c._rajz_kozos.setChecked(True)
app.processEvents()

_bt = Belepo(_t_be, "SELL", None, 2.0)
_bt.sl = _chartok[0]._alap_sl(_t_be, "SELL")
lab_qt.rajztar().belepok.append(_bt)
_chartok[0]._terv_valtozott()
app.processEvents()

_aktiv = [c for c in _chartok if c.aktiv_e()]
_passziv = [c for c in _chartok if not c.aktiv_e()]
check("pontosan EGY aktív chart van", len(_aktiv) == 1 and len(_passziv) >= 1,
      f"aktív={len(_aktiv)} passzív={len(_passziv)}")

if _aktiv and _passziv:
    _a, _p = _aktiv[0], _passziv[0]
    check("⚠ a VONALAK a passzív ablakban is ott vannak",
          all(_p._bel(_bt, _n) is not None
              for _n in ("vonal", "sl_vonal", "tp_vonal")))
    check("⚠ a DOBOZ viszont CSAK az aktívban",
          all(_p._bel(_bt, _n) is None
              for _n in ("szel", "cimke_tp", "cimke_sl", "cimke_kozep")))
    check("...az aktívban pedig megvan",
          all(_a._bel(_bt, _n) is not None
              for _n in ("szel", "cimke_tp", "cimke_sl", "cimke_kozep")))
    # A megnyitás a MODELLEN történik → minden ablakban látszik.
    _klikk_a_gombra(_a, _bt)
    check("⚠ az egyik ablakban megnyitva MINDENHOL nyitott (közös modell)",
          _bt.nyitva is True
          and "●" in (_p._bel(_bt, "vonal").label.format or ""),
          str(_p._bel(_bt, "vonal").label.format))

lab_qt.rajztar().belepok.clear()
mt.close()
w2.close()
w.close()
app.processEvents()

check("⚠ a teszt NEM hozta létre az éles data/lab_elrendezes.json-t",
      _ELES_ELR.exists() == _ELES_ELR_VOLT,
      f"volt={_ELES_ELR_VOLT} van={_ELES_ELR.exists()}")

print()
n, m = sum(results), len(results)
print(f"{n}/{m} teszt PASS")
sys.exit(0 if n == m else 1)

"""A labor 2026-09-11-i megjelenés-javításai: a vonalak ÉLETTARTAMA, az
automatizmus KAPCSOLÓJA, a tekerés a görgetés-módban, az AutoFit átméretezéskor,
a közös kontrollpont, és a képernyő-állapot mentése.

A hét pont (felhasználói jelzés):
  1. „ha valahogy beállítottam a képernyőt, akkor azt mentse le és töltse vissza"
  2. „M1-en… a legfinomabb jelzés az a tick" → `test_lab_control_points.py`
  3. „M1-en… látni szeretném, ahogy kialakul maga az M15/H1 gyertya"
  4. „a sárga jelzés és a görgetősáv jelzése ugyanazt mutassa… ha megfogom a
     chartot és mozgatom, akkor tudjam előre és hátra tekerni"
  5. „Az AutoFit nem vette észre, hogy megnöveltem számára az ablak méretét"
  6. „bezárta (SL), de a zöld és piros vonal továbbra is élt… a nyitás
     pillanatától a zárás pillanatáig kellene élnie"
  7. „valami automatizmus túl korán lezárta (pozitívba!), pedig nincs
     bekapcsolva sem entry-to-BE"

⚠ A 7. MÖGÖTT NÉV-CSAPDA VOLT. A labor `rr_preset: "off"`-fal futott — a
`PRESET_OFF` értéke „off", a JELENTÉSE viszont „BE + trailing" (a backteszt
kódja külön megjegyzi ezt a csapdát). A pár mentett 0,5 ATR-es trailingje zárta
a pozíciót nyereségben, a felhasználó tudta nélkül. A „tényleg semmi" a
`PRESET_NONE`. Most az automatizmus egy LÁTHATÓ jelölő, alapból KI.
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
except Exception as _e:
    print(f"KIHAGYVA: nincs Qt/pyqtgraph ({type(_e).__name__}: {_e})")
    print("\n0/0 teszt PASS")
    sys.exit(0)

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile

import pandas as pd
from PySide6 import QtWidgets as QW

app = QW.QApplication.instance() or QW.QApplication([])

from tools import lab_qt
from tools.lab_qt import Belepo, LabAblak, Munkaterulet, Szakasz

lab_qt.ELRENDEZES_PATH = (Path(tempfile.mkdtemp(prefix="tf_ls_"))
                          / "elrendezes.json")
_ELES_ELR = ROOT / "data" / "lab_elrendezes.json"
_ELES_ELR_VOLT = _ELES_ELR.exists()

PAR, TOL, IG = "UsaTec", "2026-08-25", "2026-08-26"

w = LabAblak(symbol=PAR, tf_perc=15, tol=TOL, ig=IG)
w.betolt()
w.show()
app.processEvents()
check("betöltött chart", w._chart is not None and len(w._chart) > 20)

_t_be = w._chart.index[len(w._chart) // 3]
b = Belepo(_t_be, "BUY", None, 2.0)
b.sl = w._alap_sl(_t_be, "BUY")
w._belepok.append(b)
w._valasztott = b
w._terv_valtozott()
app.processEvents()
_be_ar = w._be_ar(b.ido)
_x1 = w._tengely.hol(int(b.ido.timestamp()))


# ══ 7. AZ AUTOMATIZMUS: alapból SEMMI ════════════════════════════════════
check("⚠ alapból az „Auto BE/trailing” jelölő KI", not w._rr_auto.isChecked())
check("⚠ …és a futtatás presetje `none` (TÉNYLEG semmi), nem `off`",
      w._forgatokonyv()["rr_preset"] == "none", w._forgatokonyv()["rr_preset"])
check("⚠ …és a trailing-vonalak SEM jelennek meg (nincs mit mutatniuk)",
      w._bel(b, "trail_be") is None and w._bel(b, "trail_tav") is None)

w.futtat()
app.processEvents()
_res = (w._eredmeny or {}).get("res")
_kotesek = list(getattr(_res, "trades", None) or []) if _res is not None else []
check("a futtatás lefutott és van kötés", len(_kotesek) >= 1,
      f"{len(_kotesek)} kötés")
_auto = [e for t in _kotesek for e in (getattr(t, "events", None) or [])
         if str((list(e) + [None])[0]) == "SL_MODIFY"]
check("⚠ a motor NEM mozgatta a stopot (se BE, se trailing)", not _auto,
      str(_auto[:3]))

w._rr_auto.setChecked(True)
app.processEvents()
check("bekapcsolva a preset `off` (= BE + trailing) és a pár kalibrációja jön",
      w._forgatokonyv()["rr_preset"] == "off" and w._rr_ertekek(),
      str(w._rr_ertekek()))
check("...és a trailing két vonala is megjelenik",
      w._bel(b, "trail_be") is not None or not w._rr_ertekek().get(
          "trail_activation_atr"))
w._rr_auto.setChecked(False)
app.processEvents()


# ══ 6. A VONALAK ÉLETTARTAMA: a belépőtől a zárásig ══════════════════════
_slv, _tpv = w._bel(b, "sl_vonal"), w._bel(b, "tp_vonal")
check("⚠ a terv SL/TP-vonala HATÁROLT (Szakasz), nem végtelen",
      isinstance(_slv, Szakasz) and isinstance(_tpv, Szakasz),
      f"{type(_slv).__name__}/{type(_tpv).__name__}")
check("⚠ …a belépőnél kezdődik", abs(_slv.hatarok()[0] - _x1) < 1e-6,
      f"{_slv.hatarok()} vs {_x1}")
check("⚠ …és a sáv végénél végződik (ugyanaz a forrás)",
      abs(_slv.hatarok()[1] - w._sav_vege(b, _x1)) < 1e-6,
      f"{_slv.hatarok()[1]} vs {w._sav_vege(b, _x1)}")

# Futtatás után a kötés ZÁRÁSA a vég.
w.futtat()
app.processEvents()
_kt = w._kotes_belepohoz(b)
if _kt is not None and _kt.close_time is not None:
    w._belepok_rajz()
    app.processEvents()
    _xz = w._tengely.hol(int(_kt.close_time.timestamp()))
    _slv = w._bel(b, "sl_vonal")
    check("⚠ LEZÁRT kötésnél a stop-vonal a ZÁRÁSNÁL ér véget (nem él tovább)",
          _xz is not None and abs(_slv.hatarok()[1] - _xz) < 1e-6,
          f"{_slv.hatarok()[1]} vs {_xz}")
    check("...és a cél-vonal is",
          _xz is not None and abs(w._bel(b, "tp_vonal").hatarok()[1] - _xz) < 1e-6)
    # A kurzor a zárás UTÁN: a vonal akkor sem nő tovább.
    w._kurzor = len(w._chart) - 1
    w._sav_frissit()
    check("⚠ a kurzor a zárás után áll — a vonal NEM nő vele",
          abs(w._bel(b, "sl_vonal").hatarok()[1] - _xz) < 1e-6,
          f"{w._bel(b, 'sl_vonal').hatarok()[1]} vs {_xz}")
    w._kurzor = None
else:
    print("KIHAGYVA (nincs lezárt kötés a futtatásban): a zárás-vég ellenőrzése")

# A szélesség-fogó csak a doboz MAGASSÁGÁBAN.
_szel = w._bel(b, "szel")
check("⚠ a szélesség-fogó is HATÁROLT (csak a doboz magasságában)",
      isinstance(_szel, Szakasz)
      and abs(_szel.hatarok()[0] - min(b.sl, b.tp_ar(_be_ar))) < 1e-9
      and abs(_szel.hatarok()[1] - max(b.sl, b.tp_ar(_be_ar))) < 1e-9,
      str(getattr(_szel, "hatarok", lambda: None)()))
_uj_sl = b.sl - abs(_be_ar - b.sl) * 0.5
w._bel(b, "sl_vonal").setValue(_uj_sl)
app.processEvents()
check("...és a stop húzásával a fogó magassága is követ",
      abs(w._bel(b, "szel").hatarok()[0] - min(b.sl, b.tp_ar(_be_ar))) < 1e-9)

# A húzás-terület is csak a szakaszon: a span a nézet frakciója.
w._vb.setXRange(_x1 - 20, _x1 + 60, padding=0)
app.processEvents()
_slv = w._bel(b, "sl_vonal")
_slv.boundingRect()
check("⚠ a vonal rajz-területe a szakaszra korlátozódik (span < teljes)",
      0.0 < _slv.span[0] < _slv.span[1] <= 1.0, str(_slv.span))


# ══ 4. GÖRGETÉS-MÓD: a sárga vonal = a háromszög, és a húzás TEKER ═══════
w._kurzor = len(w._chart) // 2
w._kurzor_rajz()
w._gorget.setChecked(True)
app.processEvents()
check("⚠ a kurzor-VONAL és a háromszög UGYANOTT áll",
      abs(float(w._kurzor_vonal.value()) - float(w._gorget_jelolo.value())) < 1e-6,
      f"{w._kurzor_vonal.value()} vs {w._gorget_jelolo.value()}")

check("a Nézet tud a húzásról (saját jelzés)", hasattr(w._vb, "sigHuzva"))
_k0 = int(w._kurzor)
(_v0, _v1), _ = w._vb.viewRange()
# Húzás-utánzat: a nézet eltolódik (ezt az ősosztály csinálja), majd a jelzés.
# ⚠ ELŐJEL: a `translateBy(+x)` a NÉZET tartományát tolja jobbra (későbbi
# gyertyák), ami a felhasználó kezében a chart BALRA húzása. (Elsőre fordítva
# írtam, és a helyes viselkedésre bukott a teszt.)
w._vb.translateBy(x=+12.0)          # a nézet későbbre → későbbi bar a jel alá
w._vb.sigHuzva.emit()
app.processEvents()
check("⚠ a chart elhúzásával a kurzor ELŐRE tekert (a jel alatti gyertyára)",
      int(w._kurzor) > _k0, f"{_k0} → {w._kurzor}")
check("⚠ …és a vonal továbbra is a háromszögnél áll",
      abs(float(w._kurzor_vonal.value()) - float(w._gorget_jelolo.value())) < 1.0,
      f"{w._kurzor_vonal.value()} vs {w._gorget_jelolo.value()}")
_k1 = int(w._kurzor)
w._vb.translateBy(x=-24.0)          # a nézet korábbra → korábbi bar
w._vb.sigHuzva.emit()
app.processEvents()
check("⚠ …visszafelé is (hátra tekerés)", int(w._kurzor) < _k1,
      f"{_k1} → {w._kurzor}")

# Görgő (nagyítás): a kurzor MARAD, a nézet igazodik hozzá.
_k2 = int(w._kurzor)
w._vb.scaleBy((0.5, 1.0))
w._vb.sigRangeChangedManually.emit([True, True])
app.processEvents()
check("⚠ nagyításnál a kurzor NEM ugrik", int(w._kurzor) == _k2,
      f"{_k2} vs {w._kurzor}")
check("⚠ …a nézet igazodik: a vonal a megjegyzett arányon",
      abs(float(w._kurzor_vonal.value()) - float(w._gorget_jelolo.value())) < 1e-6,
      f"{w._kurzor_vonal.value()} vs {w._gorget_jelolo.value()}")
w._gorget.setChecked(False)
app.processEvents()


# ══ 5. AUTOFIT: az ÁTMÉRETEZÉS is illesztés ══════════════════════════════
w._autofit.setChecked(True)
app.processEvents()
_h = w._lathato_savhatar()
w._vb.setYRange(_h[0] - (_h[1] - _h[0]) * 3, _h[1] + (_h[1] - _h[0]) * 3, padding=0)
# (a korlát a széthúzást visszanyomja — most jöjjön az ÁTMÉRETEZÉS)
w.resize(w.width() + 200, w.height() + 300)
app.processEvents()
w._vb.sigResized.emit(w._vb)
app.processEvents()
_, (y0, y1) = w._vb.viewRange()
_h = w._lathato_savhatar()
_p = (_h[1] - _h[0]) * 0.04
check("⚠ átméretezés után a magasság a látható gyertyákra ILLESZKEDIK",
      abs(y0 - (_h[0] - _p)) < 1e-6 and abs(y1 - (_h[1] + _p)) < 1e-6,
      f"[{y0:.2f}, {y1:.2f}] vs [{_h[0]-_p:.2f}, {_h[1]+_p:.2f}]")
w._autofit.setChecked(False)


# ══ 3. KAPCSOLT ABLAKOK: a kontrollpont KÖZÖS ════════════════════════════
w5 = LabAblak(symbol=PAR, tf_perc=5, tol=TOL, ig=IG)
w5.betolt()
w5.show()
w60 = LabAblak(symbol=PAR, tf_perc=60, tol=TOL, ig=IG)
w60.betolt()
w60.show()
app.processEvents()
for _w in (w5, w60):
    _w._kapcs.setChecked(True)
app.processEvents()
check("két kapcsolt ablak", w5._szinkron is not None and w5._szinkron is w60._szinkron)
w5._kp_pct.setValue(40)
w5._kp.setChecked(True)
app.processEvents()
check("⚠ az egyik ablakban bekapcsolt kontrollpont a MÁSIKBAN is bekapcsol",
      w60._kp.isChecked() and w60._kp_aktiv())
check("⚠ …a finomság (%) is közös", int(w60._kp_pct.value()) == 40,
      str(w60._kp_pct.value()))
w60._kp_pct.setValue(70)
app.processEvents()
check("⚠ …és visszafelé is (a % a másikból)", int(w5._kp_pct.value()) == 70,
      str(w5._kp_pct.value()))
# Aki később lép be, a bentiek beállítását kapja.
w15 = LabAblak(symbol=PAR, tf_perc=15, tol=TOL, ig=IG)
w15.betolt()
w15.show()
w15._kapcs.setChecked(True)
app.processEvents()
check("⚠ a később belépő ablak a bentiek kontrollpont-beállítását kapja",
      w15._kp.isChecked() and int(w15._kp_pct.value()) == 70,
      f"{w15._kp.isChecked()} / {w15._kp_pct.value()}")
# A H1 ablak a közös idő hányadából BONTJA a gyertyát (nem kész gyertyát mutat).
# ⚠ ÓRA KÖZEPÉN, ne óra-határon: az első próba egész órára esett, h=0,00-val
# az „idx=0" semmit nem bizonyított volna (üres teszt — lásd
# `vacuous-parity-tests`).
_fel = [i for i in range(len(w5._chart) // 2, len(w5._chart))
        if w5._chart.index[i].minute == 30]
_t5 = w5._chart.index[_fel[0] if _fel else len(w5._chart) // 2]
w5._kurzor_vissza(_t5, tartalmazo=True)
w5._kurzor_rajz()
w5._kozzetesz()
app.processEvents()
_bt = w60._chart.index[int(w60._kurzor)]
_h = (_t5 - _bt).total_seconds() / 3600.0
_pp = w60._kp_bar_pontjai(int(w60._kurzor))
check("⚠ a H1 ablak a FORMÁLÓDÓ gyertyát mutatja (az idő hányadánál jár)",
      _pp is not None and 0 < w60._kp_idx < len(_pp) - 1
      and abs(w60._kp_idx / (len(_pp) - 1) - _h) < 0.05
      and w60._formalodo.isVisible(),
      f"idx={w60._kp_idx}/{0 if _pp is None else len(_pp)} h={_h:.2f}")
for _w in (w5, w60, w15):
    _w._kapcs.setChecked(False)
    _w.close()
app.processEvents()


# ══ 1. A KÉPERNYŐ-ÁLLAPOT: mentés és visszatöltés ════════════════════════
w._csak_eddig.setChecked(True)
w._kp_pct.setValue(33)
w._sebesseg.setValue(max(w._sebesseg.minimum(), 7))
w._kurzor = len(w._chart) // 2
w._kurzor_rajz()
w._vb.setXRange(_x1 - 10, _x1 + 30, padding=0)
app.processEvents()
_d = w.nezet_leiro()
check("a nézet-leíró viszi a kapcsolókat", _d["kapcsolok"]["csak_eddig"] is True
      and _d["kapcsolok"]["gorget"] is False, str(_d["kapcsolok"]))
check("...a kontrollpont %-ot és a sebességet",
      _d["kp_pct"] == 33 and _d["sebesseg"] == float(w._sebesseg.value()))
check("...a nézetet IDŐBEN (nem bar-indexben)",
      "nezet" in _d and "tol" in _d["nezet"] and ":" in _d["nezet"]["tol"],
      str(_d.get("nezet")))
check("...a kurzort", _d.get("kurzor") == str(w._kurzor_ido())[:16])
check("...és a TERVET (belépő + rajz)", len(_d["terv"]["entries"]) == 1,
      str(_d["terv"]["entries"]))

w2 = LabAblak(symbol=PAR, tf_perc=15, tol=TOL, ig=IG)
w2.betolt()
w2.show()
app.processEvents()
w2.nezet_vissza(_d)
app.processEvents()
check("⚠ visszatöltve a kapcsolók", w2._csak_eddig.isChecked()
      and not w2._gorget.isChecked())
check("⚠ …a % és a sebesség", int(w2._kp_pct.value()) == 33
      and w2._sebesseg.value() == w._sebesseg.value())
check("⚠ …a kurzor ugyanazon az IDŐN", w2._kurzor_ido() == w._kurzor_ido(),
      f"{w2._kurzor_ido()} vs {w._kurzor_ido()}")
(_a0, _a1), _ = w2._vb.viewRange()
check("⚠ …a nézet SZÉLESSÉGE (nagyítás)", abs((_a1 - _a0) - 40.0) < 1.0,
      f"{_a1 - _a0:.1f} vs 40")
check("⚠ …és a terv: a belépő ott van, SL-lel",
      len(w2._belepok) == 1 and w2._belepok[0].sl is not None
      and w2._belepok[0].irany == "BUY")
w2.close()

# A munkaterület mentése → új munkaterület indítása visszaadja.
mt = Munkaterulet(symbol=PAR, strategy=None, tf_perc=15, tol=TOL, ig=IG)
mt.show()
app.processEvents()
c0 = mt.chartok()[0]
c0._rajz_kozos.setChecked(True)
app.processEvents()
_bk = Belepo(_t_be, "SELL", None, 2.0)
_bk.sl = c0._alap_sl(_t_be, "SELL")
lab_qt.rajztar().belepok.append(_bk)
c0._terv_valtozott()
c0._autofit.setChecked(True)
c0._kp_pct.setValue(21)
app.processEvents()
_leiro = lab_qt.elrendezes_leiro(mt)
check("az elrendezés-leíró viszi a chart nézetét", "nezet" in _leiro["chartok"][0])
check("…és a KÖZÖS tervet EGYSZER (nem chartonként)",
      _leiro.get("kozos_terv") and len(_leiro["kozos_terv"]["entries"]) == 1
      and "terv" not in _leiro["chartok"][0]["nezet"], str(_leiro.get("kozos_terv")))
mt.close()
app.processEvents()
lab_qt.rajztar().belepok.clear()
lab_qt.rajztar().lista.clear()
check("a bezárás mentett (a teszt-útvonalra)", lab_qt.ELRENDEZES_PATH.exists())

mt2 = Munkaterulet()                  # argumentum nélkül → a mentett jön
mt2.show()
app.processEvents()
_c2 = mt2.chartok()
check("⚠ újraindítva a chart visszajön", len(_c2) == 1
      and int(_c2[0]._tf.currentData()) == 15)
if _c2:
    check("⚠ …a beállításaival (AutoFit, %)",
          _c2[0]._autofit.isChecked() and int(_c2[0]._kp_pct.value()) == 21,
          f"{_c2[0]._autofit.isChecked()} / {_c2[0]._kp_pct.value()}")
    check("⚠ …és a KÖZÖS tervvel (a SELL belépő ott van)",
          any(b_.irany == "SELL" for b_ in _c2[0]._belepok),
          str([(b_.irany, str(b_.ido)[:16]) for b_ in _c2[0]._belepok]))
mt2.close()
lab_qt.rajztar().belepok.clear()
lab_qt.rajztar().lista.clear()

# ⚠ A MENTETT ELRENDEZÉS `--symbol` MELLETT IS VISSZAJÖN. Az első szabály
# fordítva szólt („a parancssor nyer"): `--symbol`/`--from`-mal indítva a
# mentett három ablak NÉMÁN kimaradt — a felhasználó: „az elrendezést nem
# jegyzi meg… 3 ablak, görgetés, AutoFit… ennek a mentése nem történik meg".
mt3 = Munkaterulet(symbol=PAR, tf_perc=5, tol=TOL, ig=IG)
mt3.show()
app.processEvents()
check("⚠ `--symbol`-lal indítva IS a mentett elrendezés jön (nem a parancssor)",
      len(mt3.chartok()) == 1 and int(mt3.chartok()[0]._tf.currentData()) == 15
      and mt3.chartok()[0]._autofit.isChecked(),
      str([int(c._tf.currentData()) for c in mt3.chartok()]))
mt3.close()
lab_qt.rajztar().belepok.clear()
lab_qt.rajztar().lista.clear()
mt4 = Munkaterulet(symbol=PAR, tf_perc=5, tol=TOL, ig=IG, uj=True)
mt4.show()
app.processEvents()
check("⚠ `--uj`-jal viszont TISZTA LAP: a parancssor chartja",
      len(mt4.chartok()) == 1 and int(mt4.chartok()[0]._tf.currentData()) == 5
      and not mt4.chartok()[0]._autofit.isChecked(),
      str([int(c._tf.currentData()) for c in mt4.chartok()]))

# ── SABLON: mentés névvel → betöltés a mostani chartok helyére ──────────
lab_qt.SABLON_DIR = Path(tempfile.mkdtemp(prefix="tf_sablon_"))
mt4.uj_chart(symbol=PAR, tf_perc=60, tol=TOL, ig=IG)
app.processEvents()
for c in mt4.chartok():
    c._gorget.setChecked(True)
mt4._rendez(True)
app.processEvents()
_sab = mt4.sablon_ment(lab_qt.SABLON_DIR / "harom.json")
check("a sablon fájlba ment (névvel)", _sab is not None and _sab.exists())
mt4.elrendezes_alkalmaz({"chartok": [{"symbol": PAR, "tf": 1, "tol": TOL, "ig": IG}]})
app.processEvents()
check("közben MÁS elrendezés (egy M1 chart)",
      [int(c._tf.currentData()) for c in mt4.chartok()] == [1])
check("⚠ a sablon betöltése a MOSTANI chartok HELYÉRE hozza a mentettet",
      mt4.sablon_betolt(_sab)
      and sorted(int(c._tf.currentData()) for c in mt4.chartok()) == [5, 60]
      and all(c._gorget.isChecked() for c in mt4.chartok()),
      str([(int(c._tf.currentData()), c._gorget.isChecked()) for c in mt4.chartok()]))
check("...nem-sablon fájlra NEM csinál semmit (és megmondja)",
      not mt4.sablon_betolt(lab_qt.ELRENDEZES_PATH.with_name("nincs.json"))
      and len(mt4.chartok()) == 2)
mt4.close()
lab_qt.rajztar().belepok.clear()
lab_qt.rajztar().lista.clear()
w.close()
app.processEvents()

check("⚠ a teszt NEM hozta létre / írta az éles data/lab_elrendezes.json-t",
      _ELES_ELR.exists() == _ELES_ELR_VOLT)

print()
n, m = sum(results), len(results)
print(f"{n}/{m} teszt PASS")
sys.exit(0 if n == m else 1)

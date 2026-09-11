"""KONTROLLPONTOK — a gyertya kibontakozása a labor lejátszásában (v3.65.0).

A kérés: „egy gyertya kialakulását próbáljuk szimulálni, de ne az összes ticken
való végigugrálással, hanem kontroll pontok megadásával… adhatnánk egy számot
(mondjuk %), hogy milyen finoman szeretnénk megjeleníteni".

⚠ A MODELL AZ MT4 „Control points"-JÁÉ: a gyertyán belüli árutat nem tickekből,
hanem a KÖVETKEZŐ KISEBB IDŐSÍK OHLC-jéből építjük. Minden al-gyertya négy
pontot ad: nyitó → (alj, csúcs) vagy (csúcs, alj) az irány szerint → záró. Az
MT5-ben ugyanez „1 minute OHLC" néven él tovább.

⚠ CSAK MEGJELENÍTÉS — ÉS EZ MÉRT DÖNTÉS. A motort NEM érinti, mert az intrabar
SL/TP sorrend súlyát megmértük: 6 pár, 15 hónap, 2759 kötés, pesszimista vs
optimista → **0,0000 R különbség, 0 eltérően zárt kötés**. A hangolt célárak
7–15 R-re vannak, egyetlen M1 gyertya sem fog át ekkora távot, tehát a
„mindkettő elérhető egy gyertyán belül" eset elő sem áll. (A kapcsolót külön
igazoltuk: tág stoppal + szűk célárral 5–10 kötés zár másként, tehát a nulla
nem üres mérés.) Finomabb végrehajtás a motorban bizonyítottan nem érne semmit.

⚠ A RITKÍTÁS NEM VÁGHAT LE CSÚCSOT. Bármilyen alacsony a százalék, a bar valódi
CSÚCSA és ALJA megmarad — különben a lejátszás MÁS gyertyát rajzolna, mint a
kész chart. Ugyanaz a hibafajta, mint amikor a tick-deduplikáció levágta a
high/low-t, vagy amikor a gyertya-összevonás (LOD) elvesztette a tüskét.
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

import numpy as np
import pandas as pd
from PySide6 import QtWidgets as QW

app = QW.QApplication.instance() or QW.QApplication([])

from tools import lab_qt
from tools.lab_qt import LabAblak, kontroll_pontok, reszgyertya


# ══ 1. A TISZTA MAG ══════════════════════════════════════════════════════
_n = 15
_o = np.full(_n, 100.0)
_c = _o + 0.1                      # minden al-gyertya EMELKEDŐ
_h = _o + 0.2
_l = _o - 0.2
_h[7] = 105.0                      # a bar CSÚCSA a 7. al-gyertyában
_l[3] = 95.0                       # az ALJA a 3.-ban
AL = pd.DataFrame({"open": _o, "high": _h, "low": _l, "close": _c})

_p100 = kontroll_pontok(AL, 100)
check("100%: al-gyertyánként NÉGY pont", len(_p100) == 4 * _n, str(len(_p100)))
check("az első pont a bar NYITÓJA", _p100[0] == _o[0])
check("az utolsó a bar ZÁRÓJA", _p100[-1] == _c[-1])
check("⚠ EMELKEDŐ al-gyertyánál a sorrend O → L → H → C",
      list(_p100[:4]) == [_o[0], _l[0], _h[0], _c[0]], str(list(_p100[:4])))

_le = AL.copy()
_le["close"] = _le["open"] - 0.1   # ESŐ al-gyertyák
_ple = kontroll_pontok(_le, 100)
check("⚠ ESŐ al-gyertyánál fordítva: O → H → L → C",
      list(_ple[:4]) == [_o[0], _h[0], _l[0], float(_le['close'].iloc[0])],
      str(list(_ple[:4])))

# ⚠ A LEGFONTOSABB: a ritkítás nem veszíthet szélsőértéket.
for _pct in (100, 50, 20, 5, 1):
    _p = kontroll_pontok(AL, _pct)
    check(f"⚠ {_pct:3d}%: a bar CSÚCSA és ALJA megmarad",
          _p.max() == 105.0 and _p.min() == 95.0,
          f"{len(_p)} pont, max={_p.max()} min={_p.min()}")
check("kevesebb % → kevesebb pont",
      len(kontroll_pontok(AL, 20)) < len(kontroll_pontok(AL, 100)))
check("a nyitó/záró ritkításnál is a helyén marad",
      kontroll_pontok(AL, 5)[0] == _o[0]
      and kontroll_pontok(AL, 5)[-1] == _c[-1])
check("üres bemenet → üres út", len(kontroll_pontok(None, 100)) == 0
      and len(kontroll_pontok(AL.iloc[0:0], 100)) == 0)
check("hibás %-érték sem omlik össze",
      len(kontroll_pontok(AL, "x")) > 0 and len(kontroll_pontok(AL, -5)) > 0
      and len(kontroll_pontok(AL, 1e9)) > 0)


# ══ 2. A FORMÁLÓDÓ GYERTYA ═══════════════════════════════════════════════
check("a 0. pontnál mind a négy érték a nyitó",
      reszgyertya(_p100, 0) == (_o[0], _o[0], _o[0], _o[0]))
_r = reszgyertya(_p100, len(_p100) - 1)
check("⚠ az UTOLSÓ pontnál a KÉSZ gyertya jön ki",
      _r == (float(_o[0]), 105.0, 95.0, float(_c[-1])), str(_r))
_elozo = None
_no = True
for _i in range(len(_p100)):
    _x = reszgyertya(_p100, _i)
    if _elozo is not None and (_x[1] < _elozo[1] or _x[2] > _elozo[2]):
        _no = False
    _elozo = _x
check("⚠ a csúcs sosem csökken, az alj sosem emelkedik (élő gyertya)", _no)
check("a nyitó VÉGIG ugyanaz",
      all(reszgyertya(_p100, i)[0] == _o[0] for i in range(0, len(_p100), 7)))
check("túlindexelés sem szál el",
      reszgyertya(_p100, 10 ** 9) == reszgyertya(_p100, len(_p100) - 1))
check("üres útra None", reszgyertya([], 0) is None)


# ══ 3. VALÓDI ADATON: a részgyertya vége == a kész gyertya ═══════════════
PAR, TOL, IG = "UsaTec", "2026-08-25", "2026-08-26"
w = LabAblak(symbol=PAR, tf_perc=15, tol=TOL, ig=IG)
w.show()
app.processEvents()
if w._chart is None or len(w._chart) < 20:
    print("KIHAGYVA (éles adat): nincs elég gyertya")
else:
    w._kurzor = len(w._chart) // 2
    w._kp.setChecked(True)
    app.processEvents()
    check("M15 charton a kontrollpont AKTÍV", w._kp_aktiv())
    _pont = w._kp_bar_pontjai(w._kurzor)
    check("⚠ egy M15 bar alá 15 M1 gyertya esik → 60 pont",
          _pont is not None and len(_pont) == 60,
          str(None if _pont is None else len(_pont)))
    _bar = w._chart.iloc[w._kurzor]
    _veg = reszgyertya(_pont, len(_pont) - 1)
    check("⚠ A LEGFONTOSABB: a VÉGSŐ részgyertya == a KÉSZ gyertya",
          abs(_veg[0] - _bar["open"]) < 1e-9
          and abs(_veg[1] - _bar["high"]) < 1e-9
          and abs(_veg[2] - _bar["low"]) < 1e-9
          and abs(_veg[3] - _bar["close"]) < 1e-9,
          f"{tuple(round(x,2) for x in _veg)} vs "
          f"({_bar['open']:.2f}, {_bar['high']:.2f}, {_bar['low']:.2f}, "
          f"{_bar['close']:.2f})")

    w._kp_pct.setValue(20)
    app.processEvents()
    _p20 = w._kp_bar_pontjai(w._kurzor)
    _v20 = reszgyertya(_p20, len(_p20) - 1)
    check("⚠ 20%-on is a VALÓDI csúcs/alj (ritkítva sem hazudik)",
          abs(_v20[1] - _bar["high"]) < 1e-9 and abs(_v20[2] - _bar["low"]) < 1e-9,
          f"h={_v20[1]:.2f} l={_v20[2]:.2f}")
    check("...és kevesebb pontból", len(_p20) < len(_pont),
          f"{len(_p20)} < {len(_pont)}")
    w._kp_pct.setValue(100)

    # ── A LEJÁTSZÁS a gyertyán BELÜL lép ────────────────────────────────
    _bar_elott, w._kp_idx = w._kurzor, 0
    _lepett = sum(1 for _ in range(5) if w._kp_lep())
    check("⚠ a lejátszás a gyertyán BELÜL lép (nem ugrik barra)",
          _lepett == 5 and w._kurzor == _bar_elott and w._kp_idx == 5,
          f"{_lepett} lépés, bar={w._kurzor} idx={w._kp_idx}")
    w._kp_idx = len(_pont) - 1
    check("⚠ …a bar VÉGÉN viszont nemet mond (jöhet a következő gyertya)",
          not w._kp_lep())

    # ── A formálódó gyertya és a maszk ──────────────────────────────────
    w._kp_idx = 10
    w._kurzor_rajz()
    app.processEvents()
    check("a formálódó gyertya LÁTSZIK", w._formalodo.isVisible())
    check("⚠ …és a maszk a KURZOR gyertyáját is takarja "
          "(különben a kész gyertya elárulná a végét)",
          w._takaro.getRegion()[0] < w._kurzor,
          f"maszk {w._takaro.getRegion()[0]} vs kurzor {w._kurzor}")
    # ⚠ „LÁTSZIK" ≠ „LÁTHATÓ". Az `isVisible()` a takaró ALATT is igaz volt: a
    # formálódó gyertya z=45-tel a takaró (z=50) alatt ült, ezért a „csak eddig
    # látszik" bekapcsolva pont a formálódást rejtette el — a felhasználó: „a
    # gyertya kialakulását továbbra sem látom… így nincs értelme az egész
    # kontrollpontnak". A z-sorrend az állítás része.
    check("⚠ a formálódó gyertya a TAKARÓ FÖLÖTT van (különben a takaró elrejti)",
          w._takaro.isVisible() and w._formalodo.zValue() > w._takaro.zValue(),
          f"formálódó z={w._formalodo.zValue()} takaró z={w._takaro.zValue()}")
    check("⚠ …és a kurzor-vonal is a takaró fölött (a baron BELÜL jár)",
          w._kurzor_vonal.zValue() > w._takaro.zValue())
    # A vonal a baron BELÜL: a 10. pontnál a bal és a jobb szél KÖZÖTT.
    _xv = float(w._kurzor_vonal.value())
    check("⚠ a kurzor-vonal a formálódó gyertyán BELÜL áll (nem a jobb szélén)",
          (w._kurzor - 0.5) < _xv < (w._kurzor + 0.5)
          and abs(_xv - (w._kurzor - 0.5 + 10 / (len(_pont) - 1))) < 1e-9,
          f"x={_xv:.3f} bar={w._kurzor}")
    # Pixel-szinten is: a formálódó gyertya testének közepe NEM háttérszínű.
    try:
        from PySide6 import QtCore as _QC
        _o, _h, _l, _c = w._formalodo._ohlc
        _sc = w._vb.mapViewToScene(_QC.QPointF(float(w._kurzor), (_o + _c) / 2))
        _pt = w._plot.mapFromScene(_sc)
        _img = w._plot.grab().toImage()
        _px = _img.pixelColor(int(_pt.x()), int(_pt.y()))
        _hatter = _img.pixelColor(int(_pt.x()) + 40, int(_pt.y()))  # a takarón
        check("⚠ PIXEL-SZINTEN: a formálódó gyertya színe eltér a takarótól",
              (_px.red(), _px.green(), _px.blue()) != (_hatter.red(), _hatter.green(), _hatter.blue())
              and max(_px.red(), _px.green()) > 80,
              f"gyertya={_px.name()} takaró={_hatter.name()}")
    except Exception as _ex:
        check("⚠ PIXEL-SZINTEN: a formálódó gyertya színe eltér a takarótól", False,
              f"{type(_ex).__name__}: {_ex}")
    w._kp.setChecked(False)
    w._kurzor_rajz()
    app.processEvents()
    check("kikapcsolva eltűnik", not w._formalodo.isVisible())
    check("...és a maszk visszaáll a kurzor UTÁNRA",
          w._takaro.getRegion()[0] > w._kurzor)

    # ── M1 charton a finomabb adat a TICK ───────────────────────────────
    # A felhasználó: „a legfinomabb jelzés az a tick. Nekem M1-en ha azt
    # látom, hogy Kontrollpont 100%, akkor az egyenrangú a tickkel!"
    w1 = LabAblak(symbol=PAR, tf_perc=1, tol=TOL, ig=IG)
    w1.show()
    app.processEvents()
    if not lab_qt.tick_van(PAR):
        print(f"KIHAGYVA (tick): nincs tick-tár a(z) {PAR} párhoz")
    else:
        w1._kurzor = len(w1._chart) // 2
        w1._kp.setChecked(True)
        app.processEvents()
        check("⚠ M1 charton a kontrollpont TICKBŐL bekapcsolható",
              w1._kp.isChecked() and w1._kp_aktiv())
        _tp = w1._kp_bar_pontjai(w1._kurzor)
        check("⚠ egy M1 bar alá SOK tick esik (több, mint 4 pont)",
              _tp is not None and len(_tp) > 4,
              f"{0 if _tp is None else len(_tp)} pont")
        if _tp is not None and len(_tp) > 4:
            _s1 = w1._chart.iloc[w1._kurzor]
            _v = lab_qt.reszgyertya(_tp, len(_tp) - 1)
            # ⚠ A tick-út vége a KÉSZ gyertya: a bid-ből épült M1 nyitó/záró
            # és a tick első/utolsó bidje ugyanaz a szám.
            check("⚠ a tick-út nyitója == a kész M1 gyertya nyitója",
                  abs(_v[0] - float(_s1["open"])) < 1e-6,
                  f"{_v[0]} vs {_s1['open']}")
            check("⚠ …a záró a záróval", abs(_v[3] - float(_s1["close"])) < 1e-6,
                  f"{_v[3]} vs {_s1['close']}")
            check("⚠ …a csúcs/alj a kész gyertyáé (a ritkítás sem vághatja le)",
                  abs(_v[1] - float(_s1["high"])) < 1e-6
                  and abs(_v[2] - float(_s1["low"])) < 1e-6,
                  f"{_v[1]}/{_v[2]} vs {_s1['high']}/{_s1['low']}")
            w1._kp_pct.setValue(5)
            _t5 = w1._kp_bar_pontjai(w1._kurzor)
            _v5 = lab_qt.reszgyertya(_t5, len(_t5) - 1)
            check("⚠ 5%-on KEVESEBB pont, de a csúcs/alj marad",
                  _t5 is not None and len(_t5) < len(_tp)
                  and abs(_v5[1] - _v[1]) < 1e-9 and abs(_v5[2] - _v[2]) < 1e-9,
                  f"{len(_t5)} vs {len(_tp)}")
            w1._kp_pct.setValue(100)
    w1.close()

    # ── Tick-tár NÉLKÜL: NEM CSENDBEN utasítja el ───────────────────────
    _tick_dir_volt = lab_qt.TICK_DIR
    lab_qt.TICK_DIR = Path(tempfile.mkdtemp(prefix="tf_notick_"))
    lab_qt._TICK_VAN.clear()             # a gyorsítótár a régi tárra emlékezne
    try:
        w0 = LabAblak(symbol=PAR, tf_perc=1, tol=TOL, ig=IG)
        w0.show()
        app.processEvents()
        w0._kp.setChecked(True)
        app.processEvents()
        check("⚠ tick-tár nélkül M1-en a kontrollpont NEM kapcsolható be",
              not w0._kp.isChecked() and not w0._kp_aktiv())
        check("⚠ …és MEGMONDJA, miért (nem néma visszautasítás)",
              "M1" in w0._allapot.text() and PAR in w0._allapot.text(),
              w0._allapot.text()[:90])
        w0.close()
    finally:
        lab_qt.TICK_DIR = _tick_dir_volt
        lab_qt._TICK_VAN.clear()
w.close()


# ══ 3b. KAPCSOLT ablakok: UGYANAZ A PILLANAT, más felbontáson ═══════════
# ⚠ A felhasználó jelezte: „nem nagyon látom, hogy működne a H1-en vagy az
# M5-ön". Az ok az volt, hogy kapcsolt ablakban a formálódó gyertyát a
# VÉGÁLLAPOTÁRA ugrasztottuk („a közös óra gyertyát ad") — így a kontrollpontok
# kapcsolt módban HALOTTAK voltak. Pedig a szinkron ideje NEM gyertya, hanem
# folytonos időpont: a bar kezdetétől mért hányadból pontosan megmondható,
# hányadik kontrollponton járunk.
import tempfile

from tools.lab_qt import Munkaterulet

lab_qt.ELRENDEZES_PATH = Path(tempfile.mkdtemp(prefix="tf_kp_")) / "e.json"
mt = Munkaterulet(symbol=PAR, tf_perc=60, tol=TOL, ig=IG)
mt.show()
app.processEvents()
_c60 = mt.chartok()[0]
if _c60._chart is None or len(_c60._chart) < 10:
    print("KIHAGYVA (kapcsolt): nincs elég H1 gyertya")
else:
    _c5 = mt.uj_chart(symbol=PAR, tf_perc=5)
    app.processEvents()
    for _c in (_c60, _c5):
        _c._kp.setChecked(True)
    _c60._kapcs.setChecked(True)
    _c5._kapcs.setChecked(True)
    app.processEvents()
    _sz = _c60._szinkron
    _bar = _c60._chart.index[len(_c60._chart) // 2]
    _meres = []
    for _r in (0.0, 0.25, 0.5, 0.75, 0.9):
        _sz.allit(_bar + pd.Timedelta(minutes=60 * _r), forras=None)
        app.processEvents()
        _pp = _c60._kp_bar_pontjai(int(_c60._kurzor))
        _meres.append(_c60._kp_idx / max(1, len(_pp) - 1))
    check("⚠ KAPCSOLT ablakban a H1 gyertya ARÁNYOSAN bontakozik ki",
          all(abs(_m - _r) < 0.03
              for _m, _r in zip(_meres, (0.0, 0.25, 0.5, 0.75, 0.9))),
          str([round(x, 3) for x in _meres]))
    check("⚠ …és a formálódó gyertya LÁTSZIK is", _c60._formalodo.isVisible())
    check("⚠ a finomabb ablak közben a SAJÁT gyertyáin lép",
          _c5._kurzor is not None and _c5._chart is not None)

    # ⚠ A `nearest` kerekítés miatt a bar FELÉNÉL a kurzor a KÖVETKEZŐ
    # gyertyára ugrott, és a kibontakozás visszaesett nullára. Lejátszásnál a
    # TARTALMAZÓ gyertya kell.
    _c60._kurzor_vissza(_bar + pd.Timedelta(minutes=50), tartalmazo=True)
    check("⚠ lejátszásnál a TARTALMAZÓ gyertya (nem a legközelebbi)",
          _c60._chart.index[int(_c60._kurzor)] == _bar,
          f"{_c60._chart.index[int(_c60._kurzor)]} vs {_bar}")
    _c60._kurzor_vissza(_bar + pd.Timedelta(minutes=50))
    check("...idősík-váltásnál viszont marad a LEGKÖZELEBBI",
          _c60._chart.index[int(_c60._kurzor)] != _bar)

    # ── A szeletelés O(log n), nem teljes pásztázás ──────────────────────
    # ⚠ A boolean maszk 3,4 millió M1 soron 20,5 ms-ot vitt MINDEN ÚJ BARON —
    # H1-en (240 kontrollpont/bar) ez volt a „stopra nem áll meg, homokórázik".
    import time as _time

    _c60._kp_bar = None
    _t0 = _time.perf_counter()
    for _ in range(10):
        _c60._kp_bar = None
        _c60._kp_bar_pontjai(int(_c60._kurzor))
    _ms = (_time.perf_counter() - _t0) / 10 * 1000
    check("⚠ a bar-szeletelés GYORS (bináris keresés, nem teljes pásztázás)",
          _ms < 5.0, f"{_ms:.2f} ms/bar (a maszkos alak 20,5 volt)")
    _lq0 = (ROOT / "tools" / "lab_qt.py").read_text(encoding="utf-8")
    check("...és a kódban is `searchsorted` van",
          "_m1.index.searchsorted(_t0" in _lq0)
mt.close()


# ══ 3c. A JÖVŐ takarása TELJESEN átlátszatlan ═══════════════════════════
# ⚠ 235/255 alfánál a jövő gyertyái halványan ÁTÜTÖTTEK — lejátszás közben épp
# azt árulták el, aminek rejtve kell maradnia.
_lq = (ROOT / "tools" / "lab_qt.py").read_text(encoding="utf-8")
check("⚠ a jövőt takaró sáv TELJESEN átlátszatlan",
      "pg.mkBrush(16, 20, 24, 255)" in _lq)


# ══ 4. A HATÁR: a MOTOR érintetlen ══════════════════════════════════════
# ⚠ A kontrollpont KIZÁRÓLAG megjelenítés. Ha valaha a motorba kerülne, az
# minden eddigi mérést összehasonlíthatatlanná tenne — és a mérés szerint nem
# is érne semmit (0,0000 R, 0/2759 kötés).
_bt = (ROOT / "trading" / "backtest.py").read_text(encoding="utf-8")
for _tilos in ("kontroll_pontok", "reszgyertya", "Formalodo"):
    check(f"a motor nem ismeri a(z) {_tilos!r}-t", _tilos not in _bt)
_ls = (ROOT / "tools" / "lab_scenario.py").read_text(encoding="utf-8")
check("a forgatókönyv-futtató sem", "kontroll_pontok" not in _ls)
_lq = (ROOT / "tools" / "lab_qt.py").read_text(encoding="utf-8")
check("⚠ a kontrollpont a FORGATÓKÖNYVBE sem szivárog be "
      "(különben a mentett kísérlet mást jelentene)",
      '"kp"' not in _lq.split("def _forgatokonyv")[1].split("def ment")[0])

print()
n, m = sum(results), len(results)
print(f"{n}/{m} teszt PASS")
sys.exit(0 if n == m else 1)

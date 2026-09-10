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
    w._kp.setChecked(False)
    w._kurzor_rajz()
    app.processEvents()
    check("kikapcsolva eltűnik", not w._formalodo.isVisible())
    check("...és a maszk visszaáll a kurzor UTÁNRA",
          w._takaro.getRegion()[0] > w._kurzor)

    # ── M1 charton nincs finomabb adat → NEM CSENDBEN utasítja el ───────
    w1 = LabAblak(symbol=PAR, tf_perc=1, tol=TOL, ig=IG)
    w1.show()
    app.processEvents()
    w1._kp.setChecked(True)
    app.processEvents()
    check("⚠ M1 charton a kontrollpont NEM kapcsolható be",
          not w1._kp.isChecked() and not w1._kp_aktiv())
    check("⚠ …és MEGMONDJA, miért (nem néma visszautasítás)",
          "M1" in w1._allapot.text(), w1._allapot.text()[:70])
    w1.close()
w.close()


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

"""Több labor-ablak KÖZÖS ideje (v3.59.0).

A kérés: „a chart-megjelenítő ablakból lehessen többet is kezelni egyszerre,
lehessen összekapcsolni őket. Pl. az első ablakon M1, a másodikon ugyanennek az
instrumentumnak az M5-e, harmadjára M15. Amikor Play-t nyomok, mind a hármon
látszik, hogy mi történik — persze más sebességgel."

⚠ A TERVEZÉS EGYETLEN VALÓDI DÖNTÉSE: a közös állapot IDŐ, nem gyertya-index.
A kurzor az ablakban bar-index (`self._kurzor`), ami IDŐSÍK-FÜGGŐ — három
ablakot indexben összekötni tizenötszörös elcsúszás lenne (ugyanaz a csapda,
amit a `_kurzor_vissza` már kivéd idősík-váltásnál). Időben számolva viszont az
„eltérő sebesség", amit a felhasználó lát, MAGÁTÓL kijön: azonos chart-idő
alatt az M1-es ablak 15 gyertyát lép, az M15-ös egyet.

⚠ EGY ÓRA, NEM HÁROM. Ha minden ablak a saját `QTimer`-ét pörgetné, a nézetek
másodpercek alatt szétcsúsznának (más képfrissítés, más rajz-költség). Ezért
lejátszás közben egyetlen időzítő fut, a szinkroné.

⚠ AMI SZÁNDÉKOSAN NEM KÖZÖS: a forgatókönyv és a backteszt-eredmény. Minden
ablak a sajátját futtatja; a megosztás az IDŐRE, a play/pause-ra és a tempóra
szorítkozik. Két végrehajtási út a projekt visszatérő kárforrása — a Qt-s labor
is épp ezért nem kapott saját végrehajtást (lásd `test_lab_qt.py`).
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

if not QT_OK:
    print("\n0/0 teszt PASS")
    sys.exit(0)

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pandas as pd
from PySide6 import QtWidgets as QW

app = QW.QApplication.instance() or QW.QApplication([])

from tools.lab_qt import LabAblak, Szinkron, kovetkezo_ido, lepes_ido


# ══ 1. A LÉPÉS IDŐBEN — ez az egész alapja ═══════════════════════════════
# A sebesség-csúszka „gyertya/mp", ami idősík-függő: 60 gyertya/mp az M15-ön
# tizenötször annyi chart-idő, mint az M1-en.
_m1 = lepes_ido(60.0, 1, kep_mp=60.0)
_m15 = lepes_ido(60.0, 15, kep_mp=60.0)
check("a lépés IDŐ (Timedelta), nem gyertyaszám",
      isinstance(_m1, pd.Timedelta), type(_m1).__name__)
check("⚠ ugyanaz a csúszka-érték M15-ön 15× annyi chart-idő",
      _m15 == _m1 * 15, f"{_m1} vs {_m15}")
check("60 gyertya/mp M1-en 60 kép/mp mellett = 1 perc/kép",
      _m1 == pd.Timedelta(minutes=1), str(_m1))
check("kétszeres sebesség → kétszeres lépés",
      lepes_ido(120.0, 1, 60.0) == _m1 * 2)
check("a hibás (0/negatív) érték sem omlik össze",
      lepes_ido(0.0, 1, 60.0) == pd.Timedelta(0)
      and lepes_ido(-5.0, 1, 60.0) == pd.Timedelta(0))


# ══ 2. A VÉGE: nem futunk túl ════════════════════════════════════════════
T0 = pd.Timestamp("2026-01-01 00:00", tz="UTC")
VEG = T0 + pd.Timedelta(hours=1)
check("normál lépés", kovetkezo_ido(T0, pd.Timedelta(minutes=10), VEG)
      == T0 + pd.Timedelta(minutes=10))
check("⚠ a végét NEM lépjük túl — pontosan rááll",
      kovetkezo_ido(VEG - pd.Timedelta(minutes=1),
                    pd.Timedelta(minutes=10), VEG) == VEG,
      "különben a gyorsabb ablak túlfutna, a lassabb sosem érné el a végét")
check("a végén None (a lejátszás megáll)",
      kovetkezo_ido(VEG, pd.Timedelta(minutes=10), VEG) is None)
check("hiányzó idő → None", kovetkezo_ido(None, pd.Timedelta(minutes=1), VEG)
      is None and kovetkezo_ido(T0, pd.Timedelta(minutes=1), None) is None)


# ══ 3. A SZINKRON — csonk-ablakokkal ═════════════════════════════════════
class Csonk:
    """Amit a `Szinkron` egyáltalán lát az ablakból: NÉGY metódus."""

    def __init__(self, ido=None, veg=None, seb=60.0, tf=1):
        self._ido, self._veg, self._seb, self._tf = ido, veg, seb, tf
        self.feliratok = []
        self.kapott = []

    def kurzor_ido(self):
        return self._ido

    def play_felirat(self, jatszik):
        self.feliratok.append(jatszik)

    def szinkron_tempo(self):
        return self._ido, self._veg, self._seb, self._tf

    def szinkron_ido(self, t):
        self.kapott.append(t)
        self._ido = t


sz = Szinkron()
a, b, c = Csonk(T0, VEG), Csonk(), Csonk()
for w in (a, b, c):
    sz.belep(w)
check("három tag", len(sz.tagok()) == 3)

sz.allit(T0, forras=a)
check("⚠ az idő MINDEN tagra kimegy…", b.kapott == [T0] and c.kapott == [T0])
check("⚠ …a FORRÁST kivéve (különben végtelen kör)", a.kapott == [])

# Egy BEZÁRT ablak ne állítsa meg a lejátszást.
class Halott(Csonk):
    def szinkron_ido(self, t):
        raise RuntimeError("az ablak bezárult")


d = Halott()
sz.belep(d)
sz.allit(T0 + pd.Timedelta(minutes=5), forras=a)
check("⚠ a bezárt ablak KIESIK, a többi megy tovább",
      d not in sz.tagok() and len(sz.tagok()) == 3,
      f"{len(sz.tagok())} tag")


# ══ 4. A LEJÁTSZÁS: egy óra, közös idő ══════════════════════════════════
sz2 = Szinkron()
vezer = Csonk(T0, T0 + pd.Timedelta(minutes=3), seb=60.0, tf=1)   # 1 perc/kép
koveto = Csonk()
sz2.belep(vezer)
sz2.belep(koveto)
sz2.play(vezer)
check("play → mindkét tag Pause feliratot kap",
      vezer.feliratok == [True] and koveto.feliratok == [True])
check("a szinkron JÁTSZIK", sz2.jatszik())

for _ in range(5):
    sz2._utem()
check("⚠ a követő ablak PONTOSAN a közös időt kapja",
      koveto.kapott[:3] == [T0 + pd.Timedelta(minutes=i) for i in (1, 2, 3)],
      str(koveto.kapott[:4]))
check("⚠ a vége után MEGÁLL (nem fut túl)", not sz2.jatszik())
check("...és a leállás feliratát is megkapják", koveto.feliratok[-1] is False)

# ⚠ REGRESSZIÓ: a DURVA idősíkú vezér kis lépéssel is haladjon.
# Az első változat a vezér `kurzor_ido()`-jét kérdezte minden képen — az viszont
# a vezér GYERTYÁJÁRA kvantált idő. M15-ös vezér + 2 perc/kép lépésnél a
# kerekítés minden körben visszaejtette ugyanarra a gyertyára, és a lejátszás
# BEFAGYOTT az első lépés után (mérve: M15 +0, M1 +2 gyertya húsz kép alatt).
# Ezért tartja a szinkron a SAJÁT, folytonos óráját.
class Durva(Csonk):
    """Vezér, aki csak 15 percre kerekítve tudja megmondani az idejét."""

    def szinkron_ido(self, t):
        self.kapott.append(t)
        self._ido = t.floor("15min")          # a bar-indexre kerekítés hatása


sz3 = Szinkron()
_v = Durva(T0, T0 + pd.Timedelta(hours=2), seb=8.0, tf=15)   # 2 perc/kép
sz3.belep(_v)
sz3.play(_v)
for _ in range(20):
    sz3._utem()
check("⚠ a DURVA idősíkú vezér is halad (nem fagy be a kerekítéstől)",
      _v.kapott and _v.kapott[-1] >= T0 + pd.Timedelta(minutes=30),
      f"20 kép x 2 perc = 40 perc; eljutott: {_v.kapott[-1] - T0 if _v.kapott else '—'}")
sz3.szunet()

sz2.kilep(koveto)
check("⚠ egyedül maradva a lejátszás leáll (nincs mit szinkronizálni)",
      not sz2.jatszik() and len(sz2.tagok()) == 1)


# ══ 5. A VALÓDI PRÓBA: két IGAZI ablak, két idősík ══════════════════════
# ⚠ Enélkül a fenti csak a csonkjaimat mérné. Itt két valódi `LabAblak` fut,
# valódi adaton, és azt nézzük, hogy AZONOS chart-időre állnak — miközben az
# M1-es ablak sokkal több gyertyát lép. Ez a kérés lényege.
_PAR, _TOL, _IG = "Ger40", "2025-06-02", "2025-06-06"
w15 = LabAblak(symbol=_PAR, tf_perc=15, tol=_TOL, ig=_IG)
w15.betolt()
if w15._chart is None or len(w15._chart) < 50:
    print(f"KIHAGYVA (éles adat): nincs elég {_PAR} gyertya a próbához")
else:
    w1 = LabAblak(symbol=_PAR, tf_perc=1, tol=_TOL, ig=_IG)
    w1.betolt()
    check("a két ablak MÁS gyertyaszámmal töltött be",
          len(w1._chart) > len(w15._chart) * 5,
          f"M1={len(w1._chart)} vs M15={len(w15._chart)}")

    w15._kurzor = len(w15._chart) // 3
    w15._kapcs.setChecked(True)          # ő megy be előbb → az ő ideje a közös
    w1._kapcs.setChecked(True)
    check("⚠ belépéskor a MÁR BENT LÉVŐ ideje nyer (nem rántja el a másikat)",
          w1.kurzor_ido() is not None
          and abs((w1.kurzor_ido() - w15.kurzor_ido()).total_seconds()) < 15 * 60,
          f"M1={w1.kurzor_ido()} M15={w15.kurzor_ido()}")

    _m1_elott, _m15_elott = w1._kurzor, w15._kurzor
    _sz = w15._szinkron
    _sz.play(w15)
    for _ in range(20):
        _sz._utem()
    _sz.szunet()
    _d1, _d15 = w1._kurzor - _m1_elott, w15._kurzor - _m15_elott
    check("⚠ MINDKÉT ablak haladt", _d1 > 0 and _d15 > 0, f"M1 +{_d1}, M15 +{_d15}")
    check("⚠ AZONOS chart-időn állnak (ez a szinkron lényege)",
          abs((w1.kurzor_ido() - w15.kurzor_ido()).total_seconds()) < 15 * 60,
          f"eltérés {(w1.kurzor_ido() - w15.kurzor_ido()).total_seconds():.0f} mp")
    check("⚠ …de az M1 SOKKAL több gyertyát lépett (a 'más sebesség')",
          _d1 > _d15 * 5, f"M1 +{_d1} vs M15 +{_d15} gyertya")

    # A kézi húzás is viszi a másikat.
    w15._kurzor = len(w15._chart) - 5
    w15._kozzetesz()
    check("⚠ a kurzor kézi mozgatása is szinkronban van",
          abs((w1.kurzor_ido() - w15.kurzor_ido()).total_seconds()) < 15 * 60,
          f"M1={w1.kurzor_ido()} M15={w15.kurzor_ido()}")

    # Kikapcsolás után MÁR NEM.
    w1._kapcs.setChecked(False)
    _fuggetlen = w1.kurzor_ido()
    w15._kurzor = 0
    w15._kozzetesz()
    check("⚠ kikapcsolva a másik ablak MÁR NEM követi",
          w1.kurzor_ido() == _fuggetlen, str(w1.kurzor_ido()))
    w1.close()
    w15.close()

# ══ 6. A HATÁR: a szinkron nem hoz be második végrehajtási utat ══════════
_src = (ROOT / "tools" / "lab_qt.py").read_text(encoding="utf-8")
_i = _src.index("class Szinkron(")
_szin = _src[_i:_src.index("\nclass ", _i + 10)] if "\nclass " in _src[_i + 10:] else _src[_i:]
for _tilos in ("run_pair(", "futtat(", "keszit(", "betolt("):
    check(f"a Szinkron nem futtat semmit ({_tilos!r})", _tilos not in _szin)
check("⚠ a szinkron az ablakból CSAK a négy metódust hívja",
      all(m in _szin for m in ("kurzor_ido", "play_felirat", "szinkron_tempo",
                               "szinkron_ido")))

print()
n, m = sum(results), len(results)
print(f"{n}/{m} teszt PASS")
sys.exit(0 if n == m else 1)

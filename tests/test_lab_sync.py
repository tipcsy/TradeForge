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

# ══ 6. AZ „A" GOMB: az automatikus nagyítás KONVERGÁLJON ════════════════
# ⚠ A LELET (2026-09-09, felhasználói jelzés): „ha rákattintok az A gombra,
# elindul egy teljes kicsinyítés és nem is hagyja abba, csak ha kilépek".
#
# A hurok: nézet változik → `sigRangeChanged` → `_cimke_helyre()` a NÉZETBŐL
# számolja az időcímke helyét → a címke határai kitolódnak → az automatikus
# nagyítás befogadja őket → a nézet ismét változik → …
# Mérve: körönként ~5% (35 335 → 44 907 hat kör alatt), megállás nélkül, és a
# gyertyák egy hajszálvékony csíkba préselődtek a nézet tetején.
#
# ⚠ NEM a v3.58.0 gyertya-átalakítás regressziója: a RÉGI `boundingRect`-tel
# ugyanígy divergált (35 334,8 → 44 907,2). Régebbi hiba, most derült ki.
#
# A javítás: a DÍSZÍTŐK (kurzorvonal, BID/ASK, jövőt takaró sáv, időcímke)
# `ignoreBounds=True`-val kerülnek be — nem hordoznak ár-információt. A
# felhasználó belépői és a stratégia jelölői bent maradnak.
w_a = LabAblak(symbol=_PAR, tf_perc=5, tol="2026-08-25", ig="2026-08-26")
w_a.betolt()
if w_a._chart is None or len(w_a._chart) < 20:
    print("KIHAGYVA (autoRange): nincs adat")
else:
    _vb = w_a._vb
    _m = []
    for _ in range(6):
        _vb.autoRange()
        app.processEvents()
        (_x0, _x1), (_y0, _y1) = _vb.viewRange()
        _m.append(_y1 - _y0)
    check("⚠ az ismételt automatikus nagyítás KONVERGÁL (nem fut el)",
          abs(_m[-1] - _m[0]) < 0.01 * _m[0],
          f"{_m[0]:.1f} → {_m[-1]:.1f}")
    _br = w_a._gyertyak.boundingRect()
    (_x0, _x1), (_y0, _y1) = _vb.viewRange()
    check("⚠ …és a GYERTYÁKRA illeszt (nem a díszítőkre)",
          _y0 < _br.top() and _y1 > _br.bottom()
          and (_y1 - _y0) < 3 * _br.height(),
          f"nézet {_y0:.0f}..{_y1:.0f} vs gyertyák {_br.top():.0f}..{_br.bottom():.0f}")
    _src0 = (ROOT / "tools" / "lab_qt.py").read_text(encoding="utf-8")
    check("a díszítők `ignoreBounds=True`-val kerülnek be",
          _src0.count("ignoreBounds=True") >= 4,
          f"{_src0.count('ignoreBounds=True')} db")

    # ── A kötés-táblák kapcsolója ────────────────────────────────────────
    w_a.show()
    app.processEvents()
    check("az ELSŐ ablakban a kötés-tábla LÁTSZIK",
          w_a._kotesek.isChecked() and w_a._fulek.isVisible())
    w_a._kotesek.setChecked(False)
    app.processEvents()
    check("⚠ kikapcsolva eltűnik (a számla-sorral együtt)",
          not w_a._fulek.isVisible() and not w_a._szamla.isVisible())
    # …és rejtve NEM is dolgozunk vele (a lejátszás legdrágább része).
    w_a._eredmeny = None
    w_a._listak_frissit()          # nem szabad elszállnia rejtett panellel
    check("rejtett panelnél a frissítés kimarad (nem száll el)", True)
    w_a._kotesek.setChecked(True)
    app.processEvents()
    check("visszakapcsolható", w_a._fulek.isVisible())
    w_a.close()


# ══ 6b. GÖRGETÉS: a kurzor marad, a chart mozog alatta ══════════════════
# A kérés: „amikor megy a play, lehessen a play vonalat ott tartani, ellenben a
# chartot mozgatni alatta (persze legyen kikapcsolható)".
if QT_OK:
    w_g = LabAblak(symbol=_PAR, tf_perc=5, tol="2026-08-25", ig="2026-08-26")
    w_g.betolt()
    if w_g._chart is None or len(w_g._chart) < 300:
        print("KIHAGYVA (görgetés): nincs elég gyertya")
    else:
        _n = len(w_g._chart)
        w_g._kurzor = _n // 2
        w_g._vb.setXRange(w_g._kurzor - 100, w_g._kurzor + 100, padding=0)
        app.processEvents()
        _x0, _x1 = w_g._vb.viewRange()[0]

        # KI: a nézet nem mozdul.
        w_g._kurzor += 50
        w_g._kurzor_rajz()
        app.processEvents()
        check("⚠ kikapcsolva a nézet NEM mozdul (a mai viselkedés)",
              abs(w_g._vb.viewRange()[0][0] - _x0) < 1e-6,
              str([round(v, 1) for v in w_g._vb.viewRange()[0]]))

        # BE: megjegyzi, HOL áll a kurzor — nem ránt a képen.
        _elotte = list(w_g._vb.viewRange()[0])
        w_g._gorget.setChecked(True)
        app.processEvents()
        check("⚠ bekapcsoláskor NEM rántja el a képet (ott folytatja)",
              abs(w_g._vb.viewRange()[0][0] - _elotte[0]) < 1e-6,
              f"{_elotte} → {[round(v,1) for v in w_g._vb.viewRange()[0]]}")
        _arany = w_g._gorget_arany
        check("...és megjegyezte a kurzor képarányát",
              0.0 < _arany < 1.0, f"{_arany:.2f}")

        _b0, _b1 = w_g._vb.viewRange()[0]
        _szel = _b1 - _b0
        w_g._kurzor += 60
        w_g._kurzor_rajz()
        app.processEvents()
        _u0, _u1 = w_g._vb.viewRange()[0]
        check("⚠ a chart PONTOSAN a kurzorral együtt tolódik",
              abs((_u0 - _b0) - 60) < 1e-6, f"{_u0 - _b0:+.1f} (várt +60)")
        check("⚠ …és a NAGYÍTÁS változatlan (nem zoomol vissza)",
              abs((_u1 - _u0) - _szel) < 1e-6, f"{_u1-_u0:.1f} vs {_szel:.1f}")
        # ⚠ +0,5: a kurzor-VONAL a gyertya közepén áll (i + 0,5). A régi képlet
        # a bar-index bal szélét vette, ezért a háromszög és a sárga vonal fél
        # gyertyával elcsúszott egymástól (felhasználói jelzés).
        check("⚠ …a kurzor-VONAL a MEGJEGYZETT arányon marad",
              abs((w_g._kurzor + 0.5 - _u0) / (_u1 - _u0) - _arany) < 1e-6,
              f"{(w_g._kurzor + 0.5 - _u0)/(_u1-_u0):.3f} vs {_arany:.3f}")

        # Kikapcsolva megint áll.
        w_g._gorget.setChecked(False)
        _k0 = w_g._vb.viewRange()[0][0]
        w_g._kurzor += 40
        w_g._kurzor_rajz()
        app.processEvents()
        check("visszakapcsolható KI-re (a nézet újra áll)",
              abs(w_g._vb.viewRange()[0][0] - _k0) < 1e-6)
    w_g.close()


# ══ 6c. ÁLLAPOT-SÁV: alapból KI, és kikapcsolva EL IS TŰNIK ═════════════
# ⚠ A felhasználó: „nem tudom, hogy ez az alsó táblázat mit takar, de szerintem
# nem fog kelleni (pláne nem minden chartra)". Diagnosztikai csík (no-trade óra
# / irány / jel-ablak / piac-besorolás), ami három kapcsolt ablaknál háromszor
# viszi a helyet. A korábbi viselkedés azért volt zavaró, mert ÜRESEN IS
# LÁTSZOTT: helyet vitt, és nem mondta meg, mi lenne benne.
if QT_OK:
    # ⚠ `show()` KELL: egy meg nem jelenített ablak MINDEN gyereke
    # `isVisible() == False`, tehát a láthatóság-mérés nélküle mindig „rejtve"
    # volna — a teszt a saját műtermékét mérné. (Kétszer futottam bele ma.)
    w_s = LabAblak(symbol=_PAR, tf_perc=15, tol="2026-08-25", ig="2026-08-26")
    w_s.show()
    app.processEvents()
    # ⚠ STRATÉGIA NÉLKÜL NINCS MIT MUTATNI (a `LabAblak` fent stratégia nélkül
    # jött létre): a csík akkor sem látszhat, ha a jelölő be van kapcsolva.
    _van_allapot = any(_o.__class__.__name__ == "BarState" for _o in w_s._objs)
    check("stratégia nélkül nincs állapot-adat", not _van_allapot)
    check("⚠ a jelölő ALAPBÓL be van kapcsolva (adat-vezérelt viselkedés)",
          w_s._savok.isChecked())
    check("⚠ …de stratégia nélkül a csík MÉGSEM látszik (ez volt a panasz)",
          not w_s._sav.isVisible())
    check("a tooltip MEGMONDJA, mit mutat (a felhasználó nem tudta)",
          len(w_s._savok.toolTip()) > 40 and "no-trade" in w_s._savok.toolTip())
    w_s._savok.setChecked(False)
    app.processEvents()
    check("kézzel kikapcsolva sem látszik", not w_s._sav.isVisible())

    # STRATÉGIÁVAL viszont van adat — és akkor a jelölő dönt.
    w_s2 = LabAblak(symbol=_PAR, strategy="wpr_sma", tf_perc=15,
                    tol="2026-08-25", ig="2026-08-26")
    w_s2.show()
    app.processEvents()
    # ⚠ EZ A SOR EGY VALÓDI HIBÁT FOGOTT MEG: a `strategy=` paramétert a
    # konstruktor NÉMÁN ELDOBTA (a `_strat_lista` csak a korábbi választást
    # őrizte, ami frissen épült combóban üres). Következmény: a
    # `main.py lab --strategy …`, a munkaterület `uj_chart(strategy=…)`-ja és
    # a mentett elrendezésből visszaállított chartok MIND stratégia nélkül
    # indultak — hibaüzenet nélkül, csak a jelölők maradtak el a charton.
    check("⚠ a `strategy=` paraméter TÉNYLEG beáll (nem néma eldobás)",
          w_s2._strat_nev() == "wpr_sma", repr(w_s2._strat_nev()))
    _van2 = any(_o.__class__.__name__ == "BarState" for _o in w_s2._objs)
    if _van2:
        check("⚠ stratégiával VAN adat → a csík látszik", w_s2._sav.isVisible())
        w_s2._savok.setChecked(False)
        app.processEvents()
        check("⚠ …és kézzel kikapcsolható", not w_s2._sav.isVisible())
    else:
        print("KIHAGYVA: a stratégia sem adott állapot-objektumot")
    w_s2.close()
    w_s.close()


# ══ 6d. GÖRGETÉS-JELÖLŐ, AUTOFIT, és a panel-sorok ══════════════════════
if QT_OK:
    w_u = LabAblak(symbol=_PAR, tf_perc=15, tol="2026-08-25", ig="2026-08-26")
    w_u.show()
    app.processEvents()
    if w_u._chart is None or len(w_u._chart) < 250:
        print("KIHAGYVA (UI): nincs elég gyertya")
    else:
        _n = len(w_u._chart)
        w_u._kurzor = _n // 2
        w_u._vb.setXRange(w_u._kurzor - 100, w_u._kurzor + 100, padding=0)
        app.processEvents()

        # ── A %-mező LEGYEN OLVASHATÓ ───────────────────────────────────
        # ⚠ 64 px-en a „100%" a két nyíl mellé szorult, és csak a nyilak
        # látszottak — egy mező, aminek az ÉRTÉKE nem olvasható, nem vezérlő.
        check("⚠ a kontrollpont-% mező elég széles a számnak",
              w_u._kp_pct.width() >= 84, f"{w_u._kp_pct.width()} px")

        # ── A POZICIONÁLÓ HÁROMSZÖG ─────────────────────────────────────
        check("görgetés nélkül nincs háromszög",
              not w_u._gorget_jelolo.isVisible())
        w_u._gorget.setChecked(True)
        app.processEvents()
        check("⚠ görgetésnél MEGJELENIK a pozicionáló háromszög",
              w_u._gorget_jelolo.isVisible())
        check("...és a kurzoron áll",
              abs(w_u._gorget_jelolo.value() - w_u._kurzor) < 1.0,
              f"{w_u._gorget_jelolo.value():.1f} vs {w_u._kurzor}")

        (_gx0, _gx1), _ = w_u._vb.viewRange()
        w_u._gorget_jelolo.setValue(_gx0 + 0.30 * (_gx1 - _gx0))
        app.processEvents()
        check("⚠ a háromszög ELHÚZÁSA átállítja a tartó-arányt",
              abs(w_u._gorget_arany - 0.30) < 0.02, f"{w_u._gorget_arany:.2f}")
        w_u._kurzor += 20
        w_u._kurzor_rajz()
        app.processEvents()
        (_a0, _a1), _ = w_u._vb.viewRange()
        check("⚠ …és a lejátszás ONNANTÓL ott tartja a kurzort",
              abs((w_u._kurzor - _a0) / (_a1 - _a0) - 0.30) < 0.02,
              f"{(w_u._kurzor - _a0) / (_a1 - _a0):.2f}")

        # ── KIKAPCSOLÁS: a kurzornak legyen hova söpörnie ────────────────
        # ⚠ A chart helyesen megállt, de a kurzor a nézet ~75%-ánál ragadt és
        # pár lépés után KIFUTOTT a képből — a felhasználó ezt úgy látta, hogy
        # „nem áll vissza arra, hogy a sáv mozogjon".
        w_u._gorget.setChecked(False)
        app.processEvents()
        (_b0, _b1), _ = w_u._vb.viewRange()
        check("⚠ kikapcsolás után a kurzor BALRA kerül (van hova söpörnie)",
              (w_u._kurzor - _b0) / (_b1 - _b0) < 0.25,
              f"{(w_u._kurzor - _b0) / (_b1 - _b0):.2f}")
        check("...és a háromszög eltűnik", not w_u._gorget_jelolo.isVisible())
        _c0 = w_u._vb.viewRange()[0][0]
        w_u._kurzor += 20
        w_u._kurzor_rajz()
        app.processEvents()
        check("...a chart pedig tényleg ÁLL (a kurzor mozog)",
              abs(w_u._vb.viewRange()[0][0] - _c0) < 1e-6)

        # ── AUTOFIT ─────────────────────────────────────────────────────
        _hat = w_u._lathato_savhatar()
        check("a látható gyertyák sáv-határa kiszámolható", _hat is not None)
        if _hat:
            _lo, _hi = _hat
            w_u._autofit.setChecked(True)
            app.processEvents()
            _y0, _y1 = w_u._vb.viewRange()[1]
            check("⚠ AutoFit: MINDEN látható gyertya belefér",
                  _y0 <= _lo and _y1 >= _hi,
                  f"nézet {_y0:.1f}..{_y1:.1f} vs gyertyák {_lo:.1f}..{_hi:.1f}")
            # BENAGYÍTÁS szabad, és MEGMARAD.
            _k, _f = (_y0 + _y1) / 2, (_y1 - _y0) / 6
            w_u._vb.setYRange(_k - _f, _k + _f, padding=0)
            app.processEvents()
            _z0, _z1 = w_u._vb.viewRange()[1]
            check("⚠ …a benagyítás (összenyomás) SZABAD és megmarad",
                  (_z1 - _z0) < (_y1 - _y0) * 0.6,
                  f"{_z1 - _z0:.1f} vs {_y1 - _y0:.1f}")
            # SZÉTHÚZÁS: csak a gyertyákig.
            w_u._vb.setYRange(_lo - 500, _hi + 500, padding=0)
            app.processEvents()
            _q0, _q1 = w_u._vb.viewRange()[1]
            check("⚠ …a széthúzás viszont FALBA ütközik",
                  _q0 > _lo - 500 + 1 and _q1 < _hi + 500 - 1,
                  f"{_q0:.1f}..{_q1:.1f}")
            check("...de minden gyertya még belefér", _q0 <= _lo and _q1 >= _hi)

        # ── A PANEL-SOROK eltüntethetők ─────────────────────────────────
        # ⚠ Az ÜRES számlagörbe-sor (0,2–0,8 tengellyel) helyet vitt, és nem
        # mondta meg, mi lenne benne — ugyanaz a panasz, mint a sávoknál.
        check("⚠ eredmény nélkül a SZÁMLAGÖRBE sora sem látszik",
              not w_u._egyenleg.isVisible())

        class _Res0:
            trades = []

        w_u._eredmeny = {"res": _Res0(), "balance": 1000.0}
        w_u._egyenleg_lathatosag()
        app.processEvents()
        check("⚠ eredménnyel viszont megjelenik", w_u._egyenleg.isVisible())
        w_u._egyenleg_kapcs.setChecked(False)
        app.processEvents()
        check("...és kézzel is kikapcsolható", not w_u._egyenleg.isVisible())
    w_u.close()


# ══ 7. A HATÁR: a szinkron nem hoz be második végrehajtási utat ══════════
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

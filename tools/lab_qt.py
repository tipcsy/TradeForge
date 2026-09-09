"""KÉZI LABORATÓRIUM — Qt/pyqtgraph felület (`python main.py lab`).

⚠ MIÉRT CSERÉLTÜK LE A MATPLOTLIB-ET. A 2026-09-03-i hibalista — nem lehet
megfogni a vonalat, kicsúszik a képből, a nagyítás használhatatlan, a
tengely-felirat eltűnik, húzás közben újrarajzol — mind EGY okra vezetett
vissza: a matplotlib diagram-rajzoló, nem interaktív chart. Nincs benne
mozgatható vonal-objektum, találat-teszt és részleges újrarajzolás, ezért
mindezt kézzel írtuk meg, darabonként — és a hibák is darabonként jöttek.

MÉRVE (UsaTec, ugyanaz az adat):

    gyertya   matplotlib   pyqtgraph   arány
        184      52,2 ms      3,5 ms   14,9x
      2 760     128,3 ms     20,2 ms    6,4x
     11 040     426,2 ms     89,4 ms    4,8x

…és ez alábecsüli a különbséget: itt a gyertyák EGYSZER rajzolódnak, a
nagyítás/görgetés/vonal-húzás után NEM. A matplotlibnél minden mozdulat teljes
újrarajzolás volt.

AMI ELTŰNT A KÓDBÓL: `_foghato`, `_foghato_sl`, `_foghato_kurzor` (találat-teszt
és tűrés-hangolás), `_huzas_kezd/_huzas/_huzas_vege`, `_gorgo`, `_y_tagit`,
`_y_illesztes`, `_ido_cimkek`, a nézet megőrzése rajzoláskor. Ezeket a
pyqtgraph készen adja (`movable=True`, `AxisItem.tickStrings`, ViewBox).

⚠ AMI NEM VÁLTOZOTT: az adat és a rajz-objektumok a MEGLÉVŐ
`tools.lab_chart.keszit()`-ből jönnek (az pedig a motor
`pair_visual_objects`-éből), a futtatás pedig a MEGLÉVŐ
`tools.lab_scenario.futtat()`-ból. A csere kizárólag a MEGJELENÍTÉS — nincs
második végrehajtási út.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import argparse
import json
import logging

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from strategy import visual as viz
from tools.lab_chart import (IDOSIKOK, NINCS_STRAT, Idotengely, keszit, szin)
from core.i18n import t as _t

log = logging.getLogger(__name__)

# A lejátszás legsűrűbb képfrissítése (kép/mp). A pyqtgraph-nál ez lényegesen
# magasabb lehet, mint a matplotlibnél volt — a gyertyák nem rajzolódnak újra.
MAX_KEP_MP = 60.0


# ── Gyertyák: EGY rajzolt objektum ────────────────────────────────────────
# A rajzolt oszlopok FELSŐ korlátja. E fölött a gyertyák összevonódnak (LOD):
# a képernyő úgyis kevesebb pixel széles, tehát egy gyertya sub-pixel lenne.
MAX_OSZLOP = 2500

# A látható tartományon TÚL ennyivel rajzolunk (a tartomány arányában). Enélkül
# minden apró görgetés újraépítést kérne, és a chart villogna.
LATHATO_MARGO = 0.35


# ══ TÖBB ABLAK KÖZÖS IDEJE ═══════════════════════════════════════════════
#
# ⚠ A LEJÁTSZÁS EGYSÉGE IDŐ, NEM GYERTYA — ez az egész szinkron alapja. A
# sebesség-csúszka „gyertya/mp"-ben áll, ami IDŐSÍK-FÜGGŐ: 8 gyertya/mp az
# M15-ön két óra chart-időt jelent másodpercenként, az M1-en nyolc percet. Ha a
# közös állapot gyertya-INDEX volna, egy M15↔M1 páros tizenötszörös ugrással
# csúszna szét (ugyanaz a csapda, amit a `_kurzor_vissza` már kivéd az
# idősík-váltásnál).
#
# Időben számolva viszont minden ablak UGYANANNYIT halad — és az „eltérő
# sebesség", amit a felhasználó lát, magától kijön: az M1-es ablak 15 gyertyát
# lép, miközben az M15-ös egyet.


def lepes_ido(sebesseg: float, tf_perc: int, kep_mp: float = MAX_KEP_MP):
    """Egy KÉPRE jutó chart-idő (`pd.Timedelta`) a lejátszás sebességéből."""
    perc = (max(0.0, float(sebesseg)) * max(1, int(tf_perc))
            / max(1e-9, float(kep_mp)))
    return pd.Timedelta(minutes=perc)


def kovetkezo_ido(most, lepes, veg):
    """A következő közös idő, vagy `None`, ha MÁR a végén vagyunk.

    A végét nem lépjük túl: az utolsó lépés pontosan `veg`-re áll. Enélkül a
    leggyorsabb ablak a saját chartja végén túlfutna, és a lassabbak sosem
    érnék el az utolsó gyertyát."""
    if most is None or veg is None:
        return None
    if most >= veg:
        return None
    uj = most + lepes
    return veg if uj > veg else uj


class Szinkron(QtCore.QObject):
    """Több labor-ablak KÖZÖS ideje, play/pause-a és tempója.

    ⚠ EGY ÓRA, NEM HÁROM. Ha minden ablak a saját `QTimer`-ét pörgetné, a
    nézetek néhány másodperc alatt szétcsúsznának (más képfrissítés, más
    gyertyaszám, más rajz-költség). Lejátszás közben ezért EGYETLEN időzítő
    fut — a szinkroné —, és az tolja a közös időt minden tagnak.

    ⚠ AMI NEM KÖZÖS: a forgatókönyv és a backteszt-eredmény. Minden ablak a
    SAJÁTJÁT futtatja; a megosztás kizárólag az IDŐRE, a play/pause-ra és a
    tempóra terjed ki. Két végrehajtási út a projekt visszatérő kárforrása —
    a Qt-s labor is épp azért nem kapott sajátot (lásd a modul fejlécét).

    ⚠ A TEMPÓT A VEZÉR ADJA: az az ablak, amelyikben a Play-t megnyomták. Az ő
    sebesség-csúszkája és idősíkja határozza meg a chart-idő/másodpercet, a
    többi ezt követi. Így a „melyik ablak sebessége számít?" kérdésnek egy
    válasza van, nem három.
    """

    def __init__(self):
        super().__init__()
        self._tagok = []
        self._vezer = None
        # ⚠ A KÖZÖS ÓRÁT A SZINKRON TARTJA, nem a vezér kurzorából olvassuk
        # vissza. Az első változat minden képen a vezér `kurzor_ido()`-jét
        # kérdezte — az viszont a vezér GYERTYÁJÁRA KVANTÁLT idő. Ha a lépés
        # kisebb a vezér gyertyájánál (M15 + 8 gyertya/mp = 2 perc/kép), a
        # kerekítés minden körben visszaejtette ugyanarra a gyertyára: a
        # lejátszás BEFAGYOTT az első lépés után (mérve: M15 +0, M1 +2 gyertya
        # húsz kép alatt). A saját, folytonos idő ezt kizárja.
        self._ido = None
        self._zito = QtCore.QTimer(self)
        self._zito.timeout.connect(self._utem)

    # ── tagság ───────────────────────────────────────────────────────────
    def belep(self, ablak) -> None:
        if ablak not in self._tagok:
            self._tagok.append(ablak)

    def kilep(self, ablak) -> None:
        if ablak in self._tagok:
            self._tagok.remove(ablak)
        if self._vezer is ablak:
            self.szunet()
        if len(self._tagok) < 2:
            self.szunet()

    def tagok(self) -> list:
        return list(self._tagok)

    def jatszik(self) -> bool:
        return self._zito.isActive()

    # ── az idő ───────────────────────────────────────────────────────────
    def allit(self, ido, forras=None) -> None:
        """A közös idő beállítása; a `forras` ablakot nem írjuk vissza."""
        self._ido = ido
        for a in list(self._tagok):
            if a is forras:
                continue
            try:
                a.szinkron_ido(ido)
            except Exception:                 # egy bezárt ablak ne állítsa meg
                self.kilep(a)

    def ido(self):
        """A közös óra állása. Ha még nem járt, a tagok kurzorából indul."""
        if self._ido is not None:
            return self._ido
        for a in ([self._vezer] if self._vezer else []) + self._tagok:
            if a is None:
                continue
            try:
                t = a.kurzor_ido()
            except Exception:
                continue
            if t is not None:
                return t
        return None

    # ── lejátszás ────────────────────────────────────────────────────────
    def play(self, vezer) -> None:
        self._vezer = vezer
        self.belep(vezer)
        # A közös óra a vezér AKTUÁLIS állásáról indul (vagy a chart elejéről).
        try:
            _most, _veg, _s, _tf = vezer.szinkron_tempo()
        except Exception:
            _most = None
        self._ido = _most if _most is not None else self._ido
        self._zito.start(int(1000 / MAX_KEP_MP))
        for a in self._tagok:
            a.play_felirat(True)

    def szunet(self) -> None:
        self._zito.stop()
        for a in list(self._tagok):
            try:
                a.play_felirat(False)
            except Exception:
                self._tagok.remove(a)

    def _utem(self) -> None:
        v = self._vezer
        if v is None or v not in self._tagok:
            self.szunet()
            return
        try:
            most, veg, seb, tf = v.szinkron_tempo()
        except Exception:
            self.szunet()
            return
        # ⚠ A SAJÁT óránkról lépünk, nem a vezér kvantált kurzoráról (lásd a
        # `_ido` mezőt). A vezértől csak a TEMPÓ és a VÉGE kell.
        uj = kovetkezo_ido(self._ido if self._ido is not None else most,
                           lepes_ido(seb, tf), veg)
        if uj is None:
            self.szunet()
            return
        self.allit(uj, forras=None)


# ⚠ A megnyitott ablakok hivatkozásai. Enélkül a `_uj_ablak`-ban létrehozott
# `QMainWindow`-t a szemétgyűjtő azonnal elvinné (a Qt-oldali objektum a Python
# hivatkozással együtt megy), és az ablak felvillanás után eltűnne.
_ABLAKOK: list = []

_SZINKRON = None


def szinkron() -> "Szinkron":
    """A folyamat KÖZÖS szinkronja (lustán jön létre)."""
    global _SZINKRON
    if _SZINKRON is None:
        _SZINKRON = Szinkron()
    return _SZINKRON


def kotes_oszlopok() -> dict:
    """A kötés-táblák oszlopnevei — EGY forrásból.

    ⚠ FÜGGVÉNY, NEM KONSTANS: a feliratok `_t()`-vel jönnek, egy modul-szintű
    tuple befagyasztaná a betöltéskori nyelvet, és a nyelvváltás után a chart
    meg a dokk MÁS fejlécet mutatna (a projekt visszatérő `LabelMap`-leckéje)."""
    return {
        "nyitott": (_t("lab.ido"), "ir", _t("lab.belepo"), "most", "P&L", "R",
                    "SL", "TP", "perc"),
        "lezart": (_t("lab.ido"), "ir", _t("lab.belepo"), _t("lab.kilepo"),
                   "P&L", "R", _t("lab.vege")),
    }


def kotes_tablak(szulo=None) -> tuple:
    """`(QTabWidget, {kulcs: QTableWidget})` — a Nyitott/Lezárt fülpár.

    Ugyanaz a felépítés kell a chart saját paneljébe ÉS a munkaterület közös
    dokkjába; két külön kódmásolat előbb-utóbb elcsúszna."""
    fulek = QtWidgets.QTabWidget(szulo)
    tablak = {}
    _cim = {"nyitott": "Nyitott", "lezart": _t("lab.lezart")}
    for kulcs, oszlopok in kotes_oszlopok().items():
        t = QtWidgets.QTableWidget(0, len(oszlopok))
        t.setHorizontalHeaderLabels(oszlopok)
        t.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Stretch)
        t.verticalHeader().setVisible(False)
        fulek.addTab(t, _cim[kulcs])
        tablak[kulcs] = t
    return fulek, tablak


class Gyertyak(pg.GraphicsObject):
    """Gyertyák — CSAK a látható szakasz, szükség esetén összevonva.

    ⚠ A LELET (2026-09-09, mérve). A régi változat a TELJES adatsort egyszer
    „kiégette" egy `QPicture`-be, és a `paint()` azt játszotta vissza. A
    kiégetés valóban egyszeri — de a VISSZAJÁTSZÁS nem: a `drawPicture` minden
    újrarajzoláskor végigfut az összes rajzoló-műveleten (gyertyánként kettő),
    és újrarajzolás MINDEN görgetésnél és nagyításnál van:

        gyertya   újrarajzolás   kép/mp
          6 000        13,8 ms       73   sima
         12 000        27,9 ms       36   észrevehető
         25 000        60,0 ms       17   AKAD
         50 000       120,3 ms        8   használhatatlan

    Egy heti M1 egy 24/7-es instrumentumon ~10 000 gyertya, egy hónap ~43 000 —
    pont a szakadó tartomány. (A kurzor-lejátszás közben ez nem látszik, mert ott
    nincs nézet-változás; a HÚZÁSNÁL viszont igen. Ezért volt a panasz „a chart
    akad", miközben a lejátszás mérése simának mutatta.)

    ⚠ ÉS AMIÉRT NEM MÁS NYELV A VÁLASZ: a költség Qt-rajzoló művelet, nem
    számítás. 50 000 gyertyából a képernyőn legfeljebb pár ezer PIXELOSZLOP van —
    a munka 95%-a olyasmire ment el, ami nem is látszik. A megoldás tehát nem
    gyorsabb nyelv, hanem KEVESEBB MUNKA:

      1. VÁGÁS: csak a látható tartomány (+ margó) rajzolódik;
      2. ÖSSZEVONÁS (LOD): ha a látható szakasz `MAX_OSZLOP`-nál több gyertyát
         tartalmaz, vödrökbe vonjuk (nyitó = az első nyitó, záró = az utolsó
         záró, csúcs/alj = a vödör szélsőértékei). Ez az, amit a kereskedői
         platformok is csinálnak: teljesen kizoomolva egy gyertya sub-pixel.

    A `boundingRect` továbbra is a TELJES adatsort adja vissza — különben az
    `autoRange()` a pillanatnyilag rajzolt szakaszra nagyítana.
    """

    def __init__(self, df):
        super().__init__()
        self._o = df["open"].to_numpy(float)
        self._h = df["high"].to_numpy(float)
        self._l = df["low"].to_numpy(float)
        self._c = df["close"].to_numpy(float)
        self._n = len(self._o)
        self._kep = None
        self._tart = None            # (i0, i1, lepes) — amit a kép tartalmaz
        if self._n:
            _lo, _hi = float(np.min(self._l)), float(np.max(self._h))
        else:
            _lo = _hi = 0.0
        _mag = (_hi - _lo) or 1.0
        self._teljes = QtCore.QRectF(-1.0, _lo, self._n + 2.0, _mag)

    # ── a rajzolandó szakasz meghatározása ────────────────────────────────
    def _szakasz(self):
        """`(v0, v1, i0, i1, lepes)` — a LÁTHATÓ és a MARGÓS tartomány + LOD-lépés.

        ⚠ A kettő KÜLÖN kell. A margó azért van, hogy a kis görgetés ne kérjen
        újraépítést — de ha a gyorsítótárat a MARGÓS tartománnyal hasonlítanánk
        össze, az minden mozdulatnál kilógna belőle, és a margó nem érne semmit
        (ez a hiba az első változatban benne volt). Az érvényesség kérdése:
        benne van-e a LÁTHATÓ szakasz abban, amit már megrajzoltunk.
        """
        if not self._n:
            return 0, 0, 0, 0, 1
        try:
            r = self.viewRect()
        except Exception:
            r = None
        if r is None or r.width() <= 0:
            v0 = i0 = 0
            v1 = i1 = self._n
        else:
            szel = r.width()
            v0 = max(0, min(self._n, int(np.floor(r.left()))))
            v1 = max(v0, min(self._n, int(np.ceil(r.right()))))
            i0 = max(0, min(self._n, int(np.floor(r.left() - szel * LATHATO_MARGO))))
            i1 = max(i0, min(self._n, int(np.ceil(r.right() + szel * LATHATO_MARGO))))
        lepes = max(1, int(np.ceil((i1 - i0) / MAX_OSZLOP)))
        return v0, v1, i0, i1, lepes

    def _epit(self, i0, i1, lepes) -> None:
        kep = QtGui.QPicture()
        p = QtGui.QPainter(kep)
        _zp, _pp = pg.mkPen(szin("green")), pg.mkPen(szin("red"))
        _zb, _pb = pg.mkBrush(szin("green")), pg.mkBrush(szin("red"))
        o, h, l, c = self._o, self._h, self._l, self._c
        # A test szélessége a LÉPÉSHEZ igazodik: összevonáskor a vödör szélessége.
        _fel_szel = 0.32 * lepes
        for i in range(i0, i1, lepes):
            j = min(i + lepes, i1)
            if lepes == 1:
                _o, _c = o[i], c[i]
                _h, _l = h[i], l[i]
                _kozep = float(i)
            else:
                _o, _c = o[i], c[j - 1]
                _h, _l = float(np.max(h[i:j])), float(np.min(l[i:j]))
                _kozep = i + (j - i - 1) / 2.0
            fel = _c >= _o
            p.setPen(_zp if fel else _pp)
            p.drawLine(QtCore.QPointF(_kozep, _l), QtCore.QPointF(_kozep, _h))
            p.setBrush(_zb if fel else _pb)
            p.drawRect(QtCore.QRectF(_kozep - _fel_szel, _o,
                                     2 * _fel_szel, _c - _o))
        p.end()
        self._kep = kep
        self._tart = (i0, i1, lepes)

    def _frissit(self) -> None:
        v0, v1, i0, i1, lepes = self._szakasz()
        t = self._tart
        # Újraépítés csak akkor, ha a LÁTHATÓ szakasz kilóg a már megrajzoltból,
        # vagy a felbontás (LOD-lépés) változott. A margó miatt a legtöbb
        # görgetés a meglévő képen belül marad.
        if t is not None and t[2] == lepes and t[0] <= v0 and v1 <= t[1]:
            return
        self._epit(i0, i1, lepes)

    def viewRangeChanged(self):        # a pyqtgraph hívja nézet-változáskor
        self._frissit()
        self.update()

    def paint(self, p, *args):
        self._frissit()
        if self._kep is not None:
            p.drawPicture(0, 0, self._kep)

    def boundingRect(self):
        return self._teljes


class IdoTengely(pg.AxisItem):
    """Dátum a vízszintes tengelyen — bar-INDEXBŐL.

    ⚠ A tengely bar-indexen áll (a hétvégék és a kereskedési szünetek miatt: a
    naptári tengelyen üres sávok lennének, és az ár ugrálna), a felirat viszont
    idő kell legyen."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._idx = None

    def index(self, idx):
        self._idx = idx
        self.picture = None
        self.update()

    def tickStrings(self, values, scale, spacing):
        if self._idx is None:
            return ["" for _ in values]
        ki = []
        for v in values:
            i = int(round(v))
            ki.append(self._idx[i].strftime("%m-%d %H:%M")
                      if 0 <= i < len(self._idx) else "")
        return ki


# ── Egy megrajzolt belépő ─────────────────────────────────────────────────
class Rajz:
    """Egy KÉZI rajz-elem: trendvonal, vízszintes vagy függőleges vonal.

    ⚠ IDŐBEN ÉS ÁRBAN TÁROLUNK, NEM BAR-INDEXBEN. Ugyanaz a szabály, mint a
    `Belepo`-nál: idősíkot váltva (M15 → H1) az indexek átszámozódnak, az
    időpont viszont ugyanaz marad. Egy indexre kötött trendvonal a váltás után
    máshova mutatna — némán, ami a legrosszabb fajta hiba.

    `fajta`: "trend" (két végpont) | "vizszintes" (ár) | "fuggoleges" (idő)."""

    FAJTAK = ("trend", "vizszintes", "fuggoleges")

    def __init__(self, fajta, ido1=None, ar1=None, ido2=None, ar2=None):
        self.fajta = fajta
        self.ido1, self.ar1 = ido1, ar1
        self.ido2, self.ar2 = ido2, ar2
        self.elem = None

    def kesz(self) -> bool:
        """Befejezett-e? A trendvonalhoz KÉT kattintás kell."""
        if self.fajta == "trend":
            return self.ido2 is not None
        return True

    def szotar(self) -> dict:
        d = {"fajta": self.fajta}
        if self.fajta != "vizszintes":
            d["ido"] = str(self.ido1)[:16]
        if self.fajta != "fuggoleges":
            d["ar"] = float(self.ar1)
        if self.fajta == "trend":
            d["ido2"] = str(self.ido2)[:16]
            d["ar2"] = float(self.ar2)
        return d

    @staticmethod
    def szotarbol(d: dict) -> "Rajz | None":
        _f = d.get("fajta")
        if _f not in Rajz.FAJTAK:
            return None
        try:
            _i1 = pd.Timestamp(d["ido"]) if "ido" in d else None
            _i2 = pd.Timestamp(d["ido2"]) if "ido2" in d else None
            return Rajz(_f, _i1, d.get("ar"), _i2, d.get("ar2"))
        except (KeyError, ValueError, TypeError):
            return None


class _Savdoboz(QtWidgets.QGraphicsRectItem):
    """Kitöltött téglalap ADAT-koordinátákban (x = bar-index, y = ár).

    ⚠ Miért nem `LinearRegionItem`: az vagy vízszintesen, vagy függőlegesen
    VÉGTELEN — a kockázat-/cél-sáv viszont csak a pozíció élettartamára szól.
    Egy sima `QGraphicsRectItem` a ViewBox-ban pontosan ezt adja, és a
    nagyítást/görgetést a ViewBox intézi (nem kell újrarajzolni)."""

    def __init__(self, x1, y1, x2, y2, brush):
        super().__init__(QtCore.QRectF(min(x1, x2), min(y1, y2),
                                       abs(x2 - x1), abs(y2 - y1)))
        self.setBrush(brush)
        self.setPen(pg.mkPen(None))

    def sav(self, y1: float, y2: float) -> None:
        """Az ÁR-sáv (függőleges kiterjedés) átállítása; az x-tartomány marad.

        ⚠ EZ A `LinearRegionItem.setRegion` PÁRJA. A sáv `LinearRegionItem`-ről
        `QGraphicsRectItem`-re cserélésekor a HÚZÁS-kezelők (`_sl_mozgott`,
        `_tp_mozgott`, `_belepo_mozgott`) még a régi nevet hívták, és az első
        SL-húzásnál `AttributeError`-ral megállt a felület. A felület fele
        ilyenkor működik, a másik fele nem — ezért van a névnek párja, és ezért
        van rá teszt, ami TÉNYLEGESEN meghúzza a vonalat."""
        r = self.rect()
        self.setRect(QtCore.QRectF(r.x(), min(y1, y2), r.width(), abs(y2 - y1)))

    def vege(self, x2: float) -> None:
        """A jobb szél áthelyezése. ⚠ Lejátszás közben KÖRÖNKÉNT hívódik, ezért
        csak a geometriát írjuk át — az elem újraépítése (eltávolítás + hozzáadás)
        a `_belepok_rajz`-ban van, és az másodpercenként több százszor futna."""
        r = self.rect()
        self.setRect(QtCore.QRectF(r.x(), r.y(), max(0.0, x2 - r.x()), r.height()))


class Belepo:
    """Egy terv-belépő: idő, irány, SL-ár, TP-szorzó — és a hozzá tartozó
    rajz-elemek.

    ⚠ AZ IDŐ AZ AZONOSÍTÓ, nem a bar-index: idősíkot váltva az indexek
    átszámozódnak, az időpont viszont ugyanaz marad."""

    def __init__(self, ido, irany, sl, rr):
        self.ido = ido
        self.irany = irany
        self.sl = sl
        self.rr = float(rr)
        self.vonal = None       # a függőleges belépő-vonal
        self.sl_vonal = None
        self.tp_vonal = None
        self.kock = None        # kockázat-sáv
        self.cel = None         # cél-sáv
        self.trail_be = None    # trailing INDULÁS (aktiválás) vonala
        self.trail_tav = None   # trailing KÖVETÉSI TÁVOLSÁG vonala

    def tp_ar(self, be_ar: float) -> float:
        d = 1 if self.irany == "BUY" else -1
        return be_ar + d * abs(be_ar - self.sl) * max(0.0, self.rr)


def szamla_gorbe(chart, trades, kezdo: float):
    """`(realizált, equity, kezdő)` bar-indexenkénti tömbök.

    ⚠ MIÉRT MODUL-SZINTEN, és nem metódusként: ez a rész SZÁMÍTÁS, nem
    megjelenítés. Metódusként csak élő Qt-ablakkal lehetne futtatni, tehát
    tesztelni sem — pedig épp ez az, ami CSENDBEN tud hibázni (egy bar-index
    elcsúszás nem látszik a charton, csak rossz görbét rajzol).

    ⚠ UGYANAZZAL A KÉPLETTEL számol, mint a „Nyitott" tábla lebegő oszlopa
    (`R = (ár − belépő) · irány / kockázat`, majd `× risk_usd`). Ha itt külön
    képlet állna, a görbe és a tábla ugyanarra a pillanatra MÁST mondana — és a
    felhasználó azt hinné, az egyik hibás.

    A ZÁRÁS bar-ja már a REALIZÁLTHOZ tartozik, nem a lebegőhöz: különben a
    záró báron kétszer számolnánk ugyanazt az eredményt.

    ⚠ NINCS GYORSÍTÓTÁR, és ez MÉRT döntés — a kurzor minden mozdulatánál
    (lejátszás közben is) újraszámol:

        25 000 bar,   1 kötés →  0,1 ms
        25 000 bar,  50 kötés →  0,8 ms
        25 000 bar, 300 kötés →  4,5 ms

    A lejátszás üteme ennél nagyságrenddel lassabb, tehát a gyorsítótár csak
    egy elavulási hibalehetőséget adna hozzá (a terv változik, a görbe nem).
    """
    idx = chart.index
    n = len(idx)
    zar = chart["close"].to_numpy(float)
    real = np.full(n, float(kezdo), dtype=float)
    lebeg = np.zeros(n, dtype=float)

    for tr in trades:
        _d = 1 if tr.direction == "BUY" else -1
        _a = int(idx.searchsorted(tr.open_time, side="left"))
        if _a >= n:
            continue
        if tr.close_time is None:
            _b = n
        else:
            # ⚠ `side="left"`: a kötés azokon a bárokon LEBEG, ahol a bár ideje
            # a nyitás és a ZÁRÁS KÖZÖTT van, és attól a bártól REALIZÁLT,
            # amelyiknek az ideje már eléri a zárást.
            #
            # ⚠ ELŐSZÖR `side="right") - 1`-et írtam, és az ELCSÚSZOTT egy
            # bárral, ha a zárás két bár-időpont KÖZÉ esett. Valós adaton ez
            # nem elméleti: egy M15-ös charton egy 21:00-kor nyílt és 21:06-kor
            # zárt kötés így a NYITÓ báron már realizáltnak látszott, miközben
            # a „Nyitott" tábla ugyanabban a pillanatban NYITOTTKÉNT mutatta.
            # A görbe és a tábla ugyanarra az időpontra mást mondott — épp az,
            # amit el akartunk kerülni. A tábla szabálya (`close_time > kurzor`)
            # az elsődleges, a görbe ahhoz igazodik.
            _b = int(idx.searchsorted(tr.close_time, side="left"))
            _b = max(_a, min(n, _b))
            if _b < n:
                real[_b:] += float(tr.pnl_usd or 0.0)
        _kock = float(tr.sl_points or 0.0) * float(tr.point_size or 0.0)
        _risk = float(tr.risk_usd or 0.0)
        if _kock > 0 and _risk > 0 and _b > _a:
            lebeg[_a:_b] += (zar[_a:_b] - tr.open_price) * _d / _kock * _risk
    return real, real + lebeg, float(kezdo)


class LabAblak(QtWidgets.QMainWindow):
    """A laboratórium fő ablaka."""

    def __init__(self, symbol=None, strategy=None, tf_perc=15, tol=None, ig=None):
        super().__init__()
        from strategy.settings import load_config
        from version import APP_NAME, APP_VERSION

        self.cfg = load_config(ROOT / "config.json")
        self._parok = sorted(k for k, v in (self.cfg.get("pairs") or {}).items()
                             if isinstance(v, dict))
        if not self._parok:
            raise SystemExit(_t("lab.hiba_a_config_json_pairs_blokk"))

        self.setWindowTitle(_t("lab.window_title", app=APP_NAME, version=APP_VERSION))
        self.resize(1500, 950)

        # ── Állapot ──────────────────────────────────────────────────────
        self._chart = None
        self._objs = []
        self._tengely = None
        # ⚠ SZINKRON: `None` = önálló ablak (a mai viselkedés, változatlanul).
        # A `_szinkron_alatt` a VISSZACSATOLÁST zárja ki: amikor a szinkron
        # állítja az időnket, nem toljuk vissza rá — különben két kapcsolt
        # ablak vég nélkül pingpongozna egy kurzor-mozdulaton.
        self._szinkron = None
        self._szinkron_alatt = False
        # A munkaterület (ha van) ide iratkozik fel a számla-állapotra.
        self._szamla_figyelo = None
        self._munkaterulet = None
        self._kotes_sorok = ([], [])
        self._belepok = []
        self._be_ido = None
        self._eredmeny = None
        self._valasztott = None     # a kiválasztott belépő (annak látszik SL/TP)
        self._kurzor = None
        self._elemek = []           # a stratégia rajz-elemei (törléshez)
        self._eredmeny_elemek = []
        self._nyitott_elemek = []   # a NYITOTT pozíció vonalai (kurzor-függő)
        self._rajzok = []           # kézi rajz-elemek (trend / vízszintes / függőleges)
        self._fel_rajz = None       # a félbehagyott trendvonal (1. kattintás megvolt)

        self._epit_ui(symbol, strategy, tf_perc, tol, ig)
        self._strat_lista()
        self.betolt()

    # ── Felület ──────────────────────────────────────────────────────────
    def _epit_ui(self, symbol, strategy, tf_perc, tol, ig):
        kozep = QtWidgets.QWidget()
        self.setCentralWidget(kozep)
        fo = QtWidgets.QVBoxLayout(kozep)
        fo.setContentsMargins(6, 6, 6, 6)
        fo.setSpacing(4)

        # 1. sor: adat-választók
        s1 = QtWidgets.QHBoxLayout()
        fo.addLayout(s1)
        s1.addWidget(QtWidgets.QLabel("Instrumentum"))
        self._sym = QtWidgets.QComboBox()
        self._sym.addItems(self._parok)
        if symbol in self._parok:
            self._sym.setCurrentText(symbol)
        self._sym.currentTextChanged.connect(lambda *_: self._strat_lista())
        s1.addWidget(self._sym)
        s1.addWidget(QtWidgets.QLabel(_t("lab.strategia")))
        self._strat = QtWidgets.QComboBox()
        s1.addWidget(self._strat)
        s1.addWidget(QtWidgets.QLabel(_t("lab.idosik")))
        self._tf = QtWidgets.QComboBox()
        for perc, cimke in IDOSIKOK:
            self._tf.addItem(cimke, perc)
        self._tf.setCurrentIndex(max(0, [p for p, _ in IDOSIKOK].index(tf_perc)
                                     if tf_perc in [p for p, _ in IDOSIKOK] else 2))
        self._tf.currentIndexChanged.connect(lambda *_: self.betolt())
        s1.addWidget(self._tf)
        s1.addWidget(QtWidgets.QLabel(_t("lab.tol_2")))
        self._tol = QtWidgets.QLineEdit(tol or "")
        self._tol.setFixedWidth(120)
        s1.addWidget(self._tol)
        s1.addWidget(QtWidgets.QLabel("-ig"))
        self._ig = QtWidgets.QLineEdit(ig or "")
        self._ig.setFixedWidth(120)
        s1.addWidget(self._ig)
        _b = QtWidgets.QPushButton(_t("lab.betolt"))
        _b.clicked.connect(self.betolt)
        s1.addWidget(_b)
        s1.addStretch(1)

        # 2. sor: terv-eszközök
        s2 = QtWidgets.QHBoxLayout()
        fo.addLayout(s2)
        s2.addWidget(QtWidgets.QLabel(_t("lab.kattintas")))
        self._mod = None
        self._mod_gombok = {}
        for ertek, cimke in (("BUY", "Add BUY"), ("SELL", "Add SELL"),
                             ("BE", "Add BE"),
                             # ⚠ RAJZ-MÓDOK: ugyanaz a mechanizmus, mint a
                             # belépő-lerakásé — egyszerre egy aktív mód.
                             ("trend", "╱ Trend"), ("vizszintes", "─ Vízsz."),
                             ("fuggoleges", "│ Függ.")):
            g = QtWidgets.QPushButton(cimke)
            g.setCheckable(True)
            g.clicked.connect(lambda _c=False, e=ertek: self._mod_valt(e))
            s2.addWidget(g)
            self._mod_gombok[ertek] = g
        s2.addWidget(QtWidgets.QLabel("  TP:"))
        self._tp_rr = QtWidgets.QDoubleSpinBox()
        self._tp_rr.setRange(0.1, 20.0)
        self._tp_rr.setSingleStep(0.5)
        self._tp_rr.setValue(2.0)
        s2.addWidget(self._tp_rr)
        s2.addWidget(QtWidgets.QLabel("R"))
        self._epites = QtWidgets.QCheckBox(_t("lab.start_epites"))
        s2.addWidget(self._epites)

        # BE / trailing
        from core import risk_reduction as _rrm0
        _alap = _rrm0.default_config()
        self._rr_mezok = {}
        for _k, _cim in (("breakeven_pct", "BE"),
                         ("trail_activation_atr", "trail@"),
                         ("trail_distance_atr", _t("lab.tav"))):
            s2.addWidget(QtWidgets.QLabel(f" {_cim}:"))
            _e = QtWidgets.QLineEdit(str(_alap.get(_k, "")))
            _e.setFixedWidth(48)
            _e.editingFinished.connect(self._terv_valtozott)
            s2.addWidget(_e)
            self._rr_mezok[_k] = _e

        for cimke, fn in ((_t("lab.torol"), self.torol),
                          (_t("lab.rajz_torol"), self.rajz_torol_mind),
                          (_t("lab.json_mentes"), self.ment),
                          (_t("lab.json_megnyit"), self.megnyit)):
            g = QtWidgets.QPushButton(cimke)
            g.clicked.connect(fn)
            s2.addWidget(g)
        s2.addStretch(1)

        # 3. sor: lejátszó
        s3 = QtWidgets.QHBoxLayout()
        fo.addLayout(s3)
        self._play = QtWidgets.QPushButton("▶ Play")
        self._play.clicked.connect(self.play_szunet)
        s3.addWidget(self._play)
        for cimke, lepes in (("⏮", -10 ** 6), ("◀◀", -50), ("◀", -1),
                             ("▶", 1), ("▶▶", 50), ("⏭", 10 ** 6)):
            g = QtWidgets.QPushButton(cimke)
            g.setFixedWidth(40)
            g.clicked.connect(lambda _c=False, n=lepes: self.leptet(n))
            s3.addWidget(g)
        s3.addWidget(QtWidgets.QLabel(_t("lab.sebesseg_2")))
        self._sebesseg = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self._sebesseg.setRange(1, 2000)      # gyertya / másodperc
        self._sebesseg.setValue(8)
        self._sebesseg.setFixedWidth(180)
        s3.addWidget(self._sebesseg)
        self._seb_cimke = QtWidgets.QLabel("8")
        self._sebesseg.valueChanged.connect(
            lambda v: self._seb_cimke.setText(str(v)))
        s3.addWidget(self._seb_cimke)
        self._csak_eddig = QtWidgets.QCheckBox(_t("lab.csak_eddig_latszik"))
        self._csak_eddig.setChecked(True)
        self._csak_eddig.stateChanged.connect(lambda *_: self._kurzor_rajz())
        s3.addWidget(self._csak_eddig)
        self._bidask = QtWidgets.QCheckBox("BID/ASK")
        self._bidask.setChecked(True)
        self._bidask.stateChanged.connect(lambda *_: self._kurzor_rajz())
        s3.addWidget(self._bidask)
        g = QtWidgets.QPushButton(_t("lab.lejatszas_vege"))
        g.clicked.connect(self.kurzor_le)
        s3.addWidget(g)
        # ── Több ablak közös ideje ──────────────────────────────────────
        self._kotesek = QtWidgets.QCheckBox(_t("lab.kotesek"))
        self._kotesek.setToolTip(_t("lab.kotesek_tipp"))
        self._kotesek.setChecked(True)
        self._kotesek.stateChanged.connect(self._kotes_panel)
        s3.addWidget(self._kotesek)
        self._kapcs = QtWidgets.QCheckBox(_t("lab.kapcsolt"))
        self._kapcs.setToolTip(_t("lab.kapcsolt_tipp"))
        self._kapcs.stateChanged.connect(
            lambda *_: self._kapcsol(self._kapcs.isChecked()))
        s3.addWidget(self._kapcs)
        g = QtWidgets.QPushButton(_t("lab.uj_ablak"))
        g.setToolTip(_t("lab.uj_ablak_tipp"))
        g.clicked.connect(self._uj_ablak)
        s3.addWidget(g)
        s3.addStretch(1)

        self._allapot = QtWidgets.QLabel("")
        fo.addWidget(self._allapot)

        # ── Chart ────────────────────────────────────────────────────────
        pg.setConfigOptions(antialias=False, background="#101418",
                            foreground="#c8c8c8")
        self._x_tengely = IdoTengely(orientation="bottom")
        self._plot = pg.PlotWidget(axisItems={"bottom": self._x_tengely})
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._vb = self._plot.getViewBox()
        self._plot.scene().sigMouseClicked.connect(self._kattintas)
        fo.addWidget(self._plot, stretch=1)

        # sáv-állapot (a stratégia BarState-jei)
        self._sav = pg.PlotWidget()
        self._sav.setMaximumHeight(70)
        self._sav.setXLink(self._plot)
        self._sav.hideAxis("left")
        self._sav.hideAxis("bottom")
        fo.addWidget(self._sav)

        # ── Számlagörbe (4. lépcső) ──────────────────────────────────────
        # ⚠ KÉT GÖRBE, és a különbségük a lényeg:
        #   • REALIZÁLT — csak a lezárt kötések; ez a „mi van a zsebemben".
        #   • EQUITY    — a realizált PLUSZ a nyitott pozíciók lebegő
        #                 eredménye; ez az, amit a bróker mutat, és amin a
        #                 drawdown látszik.
        # Egy stratégia lehet realizáltban szép és equityben rémes (mély
        # visszaesések, amiket „kiül") — ezt CSAK a kettő együtt mutatja meg.
        # `setXLink`: a chart nagyítása/görgetése ezt is viszi, tehát a görbe
        # mindig ahhoz az idősávhoz tartozik, amit épp nézel.
        self._egyenleg = pg.PlotWidget()
        self._egyenleg.setMaximumHeight(110)
        self._egyenleg.setXLink(self._plot)
        self._egyenleg.hideAxis("bottom")
        self._egyenleg.showGrid(y=True, alpha=0.15)
        self._egyenleg_elemek = []
        fo.addWidget(self._egyenleg)

        # Az IDŐPILLANAT-nézet: hol állt a számla a kurzornál?
        self._szamla = QtWidgets.QLabel("")
        self._szamla.setStyleSheet("color:#9fb4c8;")
        fo.addWidget(self._szamla)

        # ── Listák ───────────────────────────────────────────────────────
        self._fulek, self._tablak = kotes_tablak()
        self._fulek.setMaximumHeight(170)
        fo.addWidget(self._fulek)
        # A kötés-táblák ELREJTHETŐK. Kapcsolt ablakoknál (M1+M5+M15 ugyanarra
        # az instrumentumra) ugyanaz a kötéslista jelenne meg háromszor —
        # helyet visz a charttól, és képenként újra is épül.
        self._kotes_panel_lathato = True

        # ── Lejátszás-időzítő ────────────────────────────────────────────
        # ⚠ QTimer, nem `sleep`: a `sleep` befagyasztaná az ablakot.
        self._ido_zito = QtCore.QTimer(self)
        self._ido_zito.timeout.connect(self._utem)

        # ── Kurzor és BID/ASK ────────────────────────────────────────────
        self._kurzor_vonal = pg.InfiniteLine(
            angle=90, movable=True, pen=pg.mkPen(szin("yellow"), width=2),
            hoverPen=pg.mkPen("#ffff99", width=3))
        self._kurzor_vonal.sigPositionChanged.connect(self._kurzor_huzva)
        self._kurzor_vonal.setVisible(False)
        # ⚠ `ignoreBounds=True` MINDEN DÍSZÍTŐ ELEMRE — különben az „A"
        # (automatikus nagyítás) gomb VÉGTELEN CIKLUSBA fut. A hurok:
        #
        #     nézet változik → `sigRangeChanged` → `_cimke_helyre()` a NÉZETBŐL
        #     számolja az időcímke helyét → a címke határai kitolódnak → az
        #     automatikus nagyítás befogadja őket → a nézet ismét változik → …
        #
        # Mérve: körönként ~5% növekedés, megállás nélkül (35 335 → 44 907 hat
        # kör alatt), és a gyertyák egy hajszálvékony csíkba préselődnek a
        # nézet tetején. A díszítők (kurzorvonal, BID/ASK, jövőt takaró sáv,
        # időcímke) nem hordoznak ÁR-információt, tehát semmi keresnivalójuk a
        # nagyítás határai közt. A felhasználó belépői és a stratégia jelölői
        # IGEN — azok bent maradnak.
        self._plot.addItem(self._kurzor_vonal, ignoreBounds=True)
        self._bid = pg.InfiniteLine(angle=0, movable=False,
                                    pen=pg.mkPen(szin("blue"), width=1,
                                                 style=QtCore.Qt.DashLine),
                                    label="BID {value:0.2f}",
                                    labelOpts={"position": 0.02,
                                               "color": szin("blue")})
        self._ask = pg.InfiniteLine(angle=0, movable=False,
                                    pen=pg.mkPen(szin("orange"), width=1,
                                                 style=QtCore.Qt.DashLine),
                                    label="ASK {value:0.2f}",
                                    labelOpts={"position": 0.02,
                                               "color": szin("orange")})
        for _l in (self._bid, self._ask):
            _l.setVisible(False)
            self._plot.addItem(_l, ignoreBounds=True)
        # a jövőt takaró sáv
        self._takaro = pg.LinearRegionItem(
            orientation="vertical", movable=False,
            brush=pg.mkBrush(16, 20, 24, 235))
        self._takaro.setZValue(50)
        self._takaro.setVisible(False)
        self._plot.addItem(self._takaro, ignoreBounds=True)
        self._ido_cimke = pg.TextItem(anchor=(1, 1), color=szin("yellow"))
        self._ido_cimke.setZValue(60)
        self._plot.addItem(self._ido_cimke, ignoreBounds=True)
        self._vb.sigRangeChanged.connect(lambda *_: self._cimke_helyre())

    def _mod_valt(self, ertek: str) -> None:
        """Kattintás-mód váltása (egyszerre csak egy aktív)."""
        self._mod = None if self._mod == ertek else ertek
        # ⚠ Módot váltva a félbehagyott trendvonal ELVÉSZ — különben a
        # következő kattintás egy másik módban fejezné be, kiszámíthatatlanul.
        if self._mod != "trend":
            self._fel_rajz = None
        for k, g in self._mod_gombok.items():
            g.setChecked(k == self._mod)

    def _strat_lista(self) -> None:
        from strategy import available_strategy_names, enabled_strategy_names
        nevek = list(enabled_strategy_names(self.cfg, self._sym.currentText()))
        if not nevek:
            nevek = list(available_strategy_names(self.cfg))
        _elozo = self._strat.currentText()
        self._strat.blockSignals(True)
        self._strat.clear()
        self._strat.addItems([NINCS_STRAT] + nevek)
        if _elozo in ([NINCS_STRAT] + nevek):
            self._strat.setCurrentText(_elozo)
        self._strat.blockSignals(False)

    def _strat_nev(self) -> str:
        n = self._strat.currentText()
        return "" if n == NINCS_STRAT else n

    # ── Betöltés és rajzolás ─────────────────────────────────────────────
    def betolt(self) -> None:
        self._allapot.setText(_t("lab.betoltes"))
        QtWidgets.QApplication.processEvents()
        _kurzor_t = self._kurzor_ido()
        try:
            chart, objs, uzenet = keszit(
                self._sym.currentText(), self._strat_nev(),
                int(self._tf.currentData()),
                self._tol.text() or None, self._ig.text() or None, cfg=self.cfg)
        except Exception as ex:
            log.exception("a chart betöltése elbukott")
            self._allapot.setText(f"HIBA: {type(ex).__name__}: {ex}")
            return
        if chart is None:
            self._allapot.setText(f"HIBA: {uzenet}")
            return
        self._chart, self._objs = chart, objs
        self._tengely = Idotengely(chart.index)
        self._x_tengely.index(chart.index)

        for it in self._elemek:
            self._plot.removeItem(it)
        self._elemek.clear()
        self._sav.clear()

        self._gyertyak = Gyertyak(chart)
        self._plot.addItem(self._gyertyak)
        self._elemek.append(self._gyertyak)
        _db = self._objektumok_rajza()
        self._sav_rajz()
        self._vb.autoRange()
        self._kurzor_vissza(_kurzor_t)
        self._belepok_rajz()
        self._rajzok_rajza()      # ⚠ új idősík = új indexek → újra kell rakni
        self._kurzor_rajz()
        self._allapot.setText(
            _t("lab.status.markers_short", bars=len(chart), drawn=_db["kirajzolt"],
               outside=_db["idon_kivul"]))

    def _objektumok_rajza(self) -> dict:
        """A stratégia rajz-objektumai. Ugyanaz a forrás, mint az MT5-charton."""
        db = {"kirajzolt": 0, "idon_kivul": 0}

        def _x(t):
            return self._tengely.hol(int(t))

        for o in self._objs:
            if isinstance(o, viz.VLine):
                x = _x(o.t1)
                if x is None:
                    db["idon_kivul"] += 1
                    continue
                it = pg.InfiniteLine(pos=x, angle=90, movable=False,
                                     pen=pg.mkPen(szin(o.color),
                                                  width=max(1, o.width)))
            elif isinstance(o, viz.Trend):
                x1, x2 = _x(o.t1), _x(o.t2)
                if x1 is None or x2 is None:
                    db["idon_kivul"] += 1
                    continue
                it = pg.PlotDataItem([x1, x2], [o.p1, o.p2],
                                     pen=pg.mkPen(szin(o.color),
                                                  width=max(1, o.width)))
            elif isinstance(o, viz.Rect):
                x1, x2 = _x(o.t1), _x(o.t2)
                if x1 is None or x2 is None:
                    db["idon_kivul"] += 1
                    continue
                it = pg.LinearRegionItem(values=(min(o.p1, o.p2), max(o.p1, o.p2)),
                                         orientation="horizontal", movable=False,
                                         brush=pg.mkBrush(*viz.COLORS.get(
                                             o.color, (255, 255, 255)), 40))
            elif isinstance(o, viz.Arrow):
                x = _x(o.t1)
                if x is None:
                    db["idon_kivul"] += 1
                    continue
                it = pg.ScatterPlotItem([x], [o.p1], size=11,
                                        symbol="t1" if int(o.code) == 233 else "t",
                                        brush=pg.mkBrush(szin(o.color)))
            elif isinstance(o, viz.Text):
                x = _x(o.t1)
                if x is None:
                    db["idon_kivul"] += 1
                    continue
                it = pg.TextItem(o.text, color=szin(o.color), anchor=(0, 1))
                it.setPos(x, o.p1)
            else:
                continue
            self._plot.addItem(it)
            self._elemek.append(it)
            db["kirajzolt"] += 1
        return db

    def _sav_rajz(self) -> None:
        """A per-gyertya sáv-állapot (no-trade / irány / ablak / piac)."""
        allapotok = [o for o in self._objs if isinstance(o, viz.BarState)]
        self._sav.setVisible(bool(allapotok))
        if not allapotok:
            return
        _sorok = {0: ([], "gray"), 1: ([], "green"), 2: ([], "blue"),
                  3: ([], "orange")}
        _piros = []
        for o in allapotok:
            x = self._tengely.hol(o.t)
            if x is None:
                continue
            if o.notrade:
                _sorok[0][0].append(x)
                continue
            if o.dir:
                (_sorok[1][0] if o.dir > 0 else _piros).append(x)
            if o.window:
                _sorok[2][0].append(x)
            if o.market_state >= 0:
                _sorok[3][0].append(x)
        for sor, (xs, sz) in _sorok.items():
            if xs:
                self._sav.addItem(pg.BarGraphItem(
                    x=xs, height=0.9, width=1.0, y0=sor,
                    brush=pg.mkBrush(szin(sz)), pen=None))
        if _piros:
            self._sav.addItem(pg.BarGraphItem(
                x=_piros, height=0.9, width=1.0, y0=1,
                brush=pg.mkBrush(szin("red")), pen=None))
        self._sav.setYRange(0, 4)

    # ── Terv: belépők, SL, TP ────────────────────────────────────────────
    def _be_ar(self, ido) -> "float | None":
        if self._chart is None:
            return None
        # ⚠ ITT DŐL EL AZ IDŐZÓNA. A megnyitott forgatókönyv NAIV időt hoz (a
        # JSON úgy tárolja, ahogy a charton látod), a parquet indexe viszont
        # zóna-tudatos — összehasonlítva `TypeError`. Ez az EGYETLEN pont, ahol
        # a kettő találkozik, ezért itt igazítunk, nem a hívóknál (ott
        # felsorolásos hiba lenne: elég egy hívót kifelejteni).
        ido = self._ido_zonaba(ido)
        if ido is None:
            return None
        try:
            poz = self._chart.index.get_indexer([ido], method="nearest")
            return float(self._chart["close"].iloc[int(poz[0])])
        except (IndexError, ValueError, KeyError):
            return None

    def _atr_ar(self, ido) -> float:
        """A volatilitás-mérték ÁRBAN az adott gyertyánál — EGY forrásból.

        ⚠ EZ EGY KÖZELÍTÉS (20 gyertya átlagos range-e), NEM a stratégia ATR-je.
        A motor a kötés `entry_atr`-jét használja, és a `trail_distance_atr`
        AZZAL szorzódik. Amíg nincs futtatás, csak ez áll rendelkezésre — de
        futtatás UTÁN a `_trail_atr` a kötés VALÓDI `entry_atr`-jére vált, hogy
        a charton látott távolság azt mutassa, amit a motor tényleg csinál.
        (Két külön ATR-számítás pont az a néma eltérés, amiből ebben a
        projektben már több volt — ezért van egy függvényben.)"""
        ar = self._be_ar(ido)
        if ar is None or self._chart is None:
            return 0.0
        try:
            poz = int(self._chart.index.get_indexer([ido], method="nearest")[0])
            _h = self._chart["high"].iloc[max(0, poz - 20):poz + 1]
            _l = self._chart["low"].iloc[max(0, poz - 20):poz + 1]
            return float((_h - _l).mean()) or (ar * 0.001)
        except (IndexError, ValueError, KeyError):
            return ar * 0.001

    def _trail_atr(self, b: "Belepo") -> float:
        """A trailing-vonalak ATR-e: futtatás után a kötés VALÓDI `entry_atr`-je
        (amivel a motor számol), előtte a chart-közelítés."""
        _kt = self._kotes_belepohoz(b)
        _a = float(getattr(_kt, "entry_atr", 0.0) or 0.0) if _kt is not None else 0.0
        return _a or self._atr_ar(b.ido)

    def _alap_sl(self, ido, irany: str) -> "float | None":
        ar = self._be_ar(ido)
        if ar is None:
            return None
        _a = self._atr_ar(ido)
        return ar - _a if irany == "BUY" else ar + _a

    def _belepok_rajz(self) -> None:
        """A terv elemeinek (újra)építése."""
        for b in self._belepok:
            for it in (b.vonal, b.sl_vonal, b.tp_vonal, b.kock, b.cel,
                       b.trail_be, b.trail_tav):
                if it is not None:
                    self._plot.removeItem(it)
            b.vonal = b.sl_vonal = b.tp_vonal = b.kock = b.cel = None
            b.trail_be = b.trail_tav = None
        if self._tengely is None:
            return
        for b in self._belepok:
            x = self._tengely.hol(int(b.ido.timestamp()))
            if x is None:
                continue
            _sz = szin("lime" if b.irany == "BUY" else "magenta")
            b.vonal = pg.InfiniteLine(
                pos=x, angle=90, movable=True, pen=pg.mkPen(_sz, width=2),
                hoverPen=pg.mkPen(_sz, width=4), label=b.irany,
                labelOpts={"position": 0.97, "color": _sz})
            b.vonal.sigPositionChanged.connect(
                lambda _l=None, _b=b: self._belepo_mozgott(_b))
            self._plot.addItem(b.vonal)
            if b.sl is None:
                continue
            _be = self._be_ar(b.ido)
            if _be is None:
                continue
            # ⚠ CSAK A KIVÁLASZTOTT belépő SL/TP-je HÚZHATÓ és teljes szélességű.
            # Több belépőnél N pár vízszintes vonal olvashatatlan lenne; a
            # kiválasztás (kattintás a belépő-vonalra) tartja tisztán a képet.
            _akt = (b is self._valasztott) or (len(self._belepok) == 1)
            b.sl_vonal = pg.InfiniteLine(
                pos=b.sl, angle=0, movable=_akt,
                pen=pg.mkPen(szin("red"), width=2 if _akt else 1),
                hoverPen=pg.mkPen("#ff7777", width=3),
                label="SL {value:0.2f}",
                labelOpts={"position": 0.9, "color": szin("red")})
            b.tp_vonal = pg.InfiniteLine(
                pos=b.tp_ar(_be), angle=0, movable=_akt,
                pen=pg.mkPen(szin("green"), width=2 if _akt else 1),
                hoverPen=pg.mkPen("#77ff77", width=3),
                label=f"TP {b.rr:0.2f}R",
                labelOpts={"position": 0.9, "color": szin("green")})
            b.sl_vonal.sigPositionChanged.connect(
                lambda _l=None, _b=b: self._sl_mozgott(_b))
            b.tp_vonal.sigPositionChanged.connect(
                lambda _l=None, _b=b: self._tp_mozgott(_b))
            # ⚠ A SÁV CSAK A POZÍCIÓ ÉLETTARTAMÁRA. Korábban `LinearRegionItem`
            # volt, ami KONSTRUKCIÓ SZERINT végigér a képen — így a sáv olyan
            # gyertyákra is ráfeküdt, ahol a pozíció már/még nem élt, és nem
            # lehetett ránézésre megmondani, meddig tartott a kötés.
            _x2 = self._sav_vege(b, x)
            b.kock = _Savdoboz(x, min(_be, b.sl), _x2, max(_be, b.sl),
                               pg.mkBrush(220, 0, 0, 38))
            b.cel = _Savdoboz(x, min(_be, b.tp_ar(_be)), _x2,
                              max(_be, b.tp_ar(_be)),
                              pg.mkBrush(0, 170, 0, 38))
            for it in (b.kock, b.cel):
                it.setZValue(-20)
                self._plot.addItem(it)
            for it in (b.sl_vonal, b.tp_vonal):
                self._plot.addItem(it)
            if _akt:
                self._trail_vonalak(b, _be)
        self._be_jelolo_rajz()

    def _trail_vonalak(self, b: "Belepo", be_ar: float) -> None:
        """A trailing két HÚZHATÓ vonala: honnan indul, és mekkora távban követ.

        ⚠ Eddig ez két szövegmező volt ATR-SZORZÓBAN (`trail@`, `táv`) — abból
        ránézésre nem derült ki, HOL lesz a charton. A két vonal ugyanazt a két
        számot mutatja árban; húzáskor visszaszámoljuk a szorzót, tehát a mező
        és a vonal EGY állapot két nézete.

            aktiválás = belépő ± trail_activation_atr · ATR
            követés   = aktiválás ∓ trail_distance_atr · ATR

        A követési vonal ott mutatja a stopot, ahol a trailing INDULÁSAKOR
        állna — utána az árral együtt mozogna, de ez a beállító nézet."""
        _atr = self._trail_atr(b)
        if _atr <= 0:
            return
        _e = self._rr_ertekek()
        _akt_atr = float(_e.get("trail_activation_atr", 0.0) or 0.0)
        _tav_atr = float(_e.get("trail_distance_atr", 0.0) or 0.0)
        if _akt_atr <= 0 and _tav_atr <= 0:
            return
        d = 1 if b.irany == "BUY" else -1
        _akt_ar = be_ar + d * _akt_atr * _atr
        _tav_ar = _akt_ar - d * _tav_atr * _atr
        for _nev, _ar, _cim, _szn in (
                ("trail_be", _akt_ar, f"trail@ {_akt_atr:0.2f} ATR", "yellow"),
                ("trail_tav", _tav_ar, f"táv {_tav_atr:0.2f} ATR", "orange")):
            _l = pg.InfiniteLine(
                pos=_ar, angle=0, movable=True,
                pen=pg.mkPen(szin(_szn), width=1, style=QtCore.Qt.DashDotLine),
                hoverPen=pg.mkPen(szin(_szn), width=3), label=_cim,
                labelOpts={"position": 0.25, "color": szin(_szn)})
            _l.sigPositionChanged.connect(
                lambda _x=None, _b=b, _n=_nev: self._trail_mozgott(_b, _n))
            setattr(b, _nev, _l)
            self._plot.addItem(_l)

    def _trail_mozgott(self, b: "Belepo", nev: str) -> None:
        """Húzás → vissza az ATR-szorzóba (a mező és a vonal EGY állapot)."""
        _be = self._be_ar(b.ido)
        _atr = self._trail_atr(b)
        if _be is None or _atr <= 0:
            return
        d = 1 if b.irany == "BUY" else -1
        if nev == "trail_be" and b.trail_be is not None:
            _uj = max(0.0, d * (float(b.trail_be.value()) - _be) / _atr)
            self._rr_mezok["trail_activation_atr"].setText(f"{_uj:.2f}")
        elif nev == "trail_tav" and b.trail_tav is not None:
            _akt = (float(b.trail_be.value()) if b.trail_be is not None
                    else _be)
            _uj = max(0.0, d * (_akt - float(b.trail_tav.value())) / _atr)
            self._rr_mezok["trail_distance_atr"].setText(f"{_uj:.2f}")
        # ⚠ A TERV MEGVÁLTOZOTT: a korábbi futtatás eredménye már nem ehhez a
        # beállításhoz tartozik. Újrarajzolás nélkül a régi kötések maradnának
        # a képen egy másik trailinggel.
        self._terv_valtozott()

    def _kotes_belepohoz(self, b: "Belepo"):
        """A futtatás azon kötése, ami EHHEZ a terv-belépőhöz tartozik.

        A motor a jel-gyertya ZÁRÁSÁN lép be, tehát a kötés nyitó ideje a
        terv-belépő idejénél nem korábbi, de közel van hozzá — a legelső ilyen
        kötést vesszük."""
        res = (self._eredmeny or {}).get("res")
        _jelolt = None
        for t in (getattr(res, "trades", None) or []):
            if t.open_time is None or t.open_time < b.ido:
                continue
            if _jelolt is None or t.open_time < _jelolt.open_time:
                _jelolt = t
        return _jelolt

    def _sav_vege(self, b: "Belepo", x1: float) -> float:
        """A kockázat-/cél-sáv JOBB széle bar-indexben.

        Három forrás, ebben a sorrendben:
          1. a futtatás kötésének ZÁRÁSA — ez a valódi élettartam;
          2. futtatás előtt a LEJÁTSZÓ KURZORA — így a sáv a pozícióval együtt
             nő, ahogy lépkedsz (ez mutatja, hogy „még nyitva van");
          3. ha egyik sincs, a chart vége.

        ⚠ Sosem rövidebb a belépőnél: egy hátrafelé nyúló sáv azt sugallná,
        hogy a pozíció a nyitása ELŐTT élt."""
        _kt = self._kotes_belepohoz(b)
        if _kt is not None and _kt.close_time is not None and self._tengely:
            _x = self._tengely.hol(int(_kt.close_time.timestamp()))
            if _x is not None:
                return max(x1, _x)
        if self._kurzor is not None:
            return max(x1, float(self._kurzor) + 0.5)
        return max(x1, float(len(self._chart) - 1) if self._chart is not None else x1)

    # ── A NYITOTT pozíció vonalai (MT5-konvenció) ────────────────────────
    # ⚠ MT5-BEN A VONALAK A POZÍCIÓHOZ TARTOZNAK, NEM AZ IDŐVONALHOZ. Ahány
    # pozíció nyitva van, annyi Entry/SL/TP vonal látszik; ahogy a pozíció
    # lezárul, ezek ELTŰNNEK, és marad a nyitást a zárással összekötő vonal.
    # A labor ezt szimulálja: a vonalak a LEJÁTSZÓ KURZORÁNAK pillanatában
    # érvényes szinteket mutatják, és a belépőtől a kurzorig érnek.

    def _szintek_ekkor(self, t, ido) -> "tuple[float, float] | None":
        """A kötés SL/TP szintje az `ido` PILLANATÁBAN — `(sl, tp)`.

        A motor eseménynaplójából (`trade.events`) olvassuk: az utolsó olyan
        SL/TP-írás, ami az adott időpontig MEGTÖRTÉNT. A jövőbeli események
        szándékosan nem látszanak — különben a lejátszás elárulná, hova fog
        húzódni a stop."""
        _sl = float(getattr(t, "sl", 0.0) or 0.0)
        _tp = float(getattr(t, "tp", 0.0) or 0.0)
        for e in (getattr(t, "events", None) or []):
            _ev = list(e) + [None] * 5
            try:
                if pd.Timestamp(_ev[1]) > ido:
                    break
            except (TypeError, ValueError):
                continue
            if _ev[3]:
                _sl = float(_ev[3])
            # ⚠ A TP-nél a 0 IS ÉRVÉNYES ÍRÁS (az épített csomagnál a motor
            # TÖRLI a célárat) — ezért nem `if _ev[4]:`, hanem „van-e mező".
            if _ev[0] == "TP_MODIFY" or (_ev[4] is not None and _ev[0] == "OPEN"):
                _tp = float(_ev[4] or 0.0)
        return _sl, _tp

    def _nyitott_rajz(self) -> None:
        """A kurzor pillanatában NYITOTT kötések Entry/SL/TP vonalai."""
        for it in self._nyitott_elemek:
            self._plot.removeItem(it)
        self._nyitott_elemek.clear()
        res = (self._eredmeny or {}).get("res")
        if res is None or self._tengely is None or self._kurzor is None:
            return
        if self._chart is None or not (0 <= int(self._kurzor) < len(self._chart)):
            return
        _most = self._chart.index[int(self._kurzor)]
        _xm = float(self._kurzor) + 0.5
        for t in (getattr(res, "trades", None) or []):
            if t.open_time is None or t.open_time > _most:
                continue
            # ⚠ A LEZÁRT pozíció vonalai ELTŰNNEK — ez a lényege: a képen csak
            # az látszik, ami ÉPP ÉL, ahogy a terminálban.
            if t.close_time is not None and t.close_time <= _most:
                continue
            x1 = self._tengely.hol(int(t.open_time.timestamp()))
            if x1 is None:
                continue
            _sl, _tp = self._szintek_ekkor(t, _most)
            _sorok = [(float(t.open_price), "white", QtCore.Qt.SolidLine, "Entry")]
            if _sl:
                _sorok.append((_sl, "red", QtCore.Qt.DashLine, "SL"))
            if _tp:
                _sorok.append((_tp, "green", QtCore.Qt.DashLine, "TP"))
            for _ar, _sz, _stilus, _cim in _sorok:
                _it = pg.PlotDataItem(
                    [x1, _xm], [_ar, _ar],
                    pen=pg.mkPen(szin(_sz), width=2, style=_stilus))
                self._plot.addItem(_it)
                self._nyitott_elemek.append(_it)
                _c = pg.TextItem(_cim, color=szin(_sz), anchor=(0, 0.5))
                _c.setPos(_xm, _ar)
                self._plot.addItem(_c)
                self._nyitott_elemek.append(_c)

    def _trail_lathatosag(self) -> None:
        """A trailing két beállító vonala ELTŰNIK, ha a trailing MÁR ELINDULT.

        A felhasználó kérése: „a trailing stopnál, ha elindult, a vonalak
        eltűnhetnek." Igaza van — onnantól a vonalak már nem beállítanak
        semmit, csak takarják a képet; a tényleges stopot a nyitott pozíció
        (szaggatott piros) vonala mutatja.

        Az indulás tényét a motor eseménynaplójából olvassuk (`SL_MODIFY` /
        `TRAIL`), nem az árból: így pontosan akkor tűnnek el, amikor a motor
        TÉNYLEG húzni kezdett."""
        if self._chart is None or self._kurzor is None:
            _lat = True
        else:
            _lat = None
        _most = (self._chart.index[int(self._kurzor)]
                 if _lat is None and 0 <= int(self._kurzor) < len(self._chart)
                 else None)
        for b in self._belepok:
            if b.trail_be is None and b.trail_tav is None:
                continue
            _mutat = True
            if _most is not None:
                _kt = self._kotes_belepohoz(b)
                for e in (getattr(_kt, "events", None) or []):
                    _ev = list(e) + [None] * 7
                    if _ev[0] != "SL_MODIFY" or _ev[6] != "TRAIL":
                        continue
                    try:
                        if pd.Timestamp(_ev[1]) <= _most:
                            _mutat = False
                            break
                    except (TypeError, ValueError):
                        continue
            for it in (b.trail_be, b.trail_tav):
                if it is not None:
                    it.setVisible(_mutat)

    def _sav_frissit(self) -> None:
        """A kockázat-/cél-sávok jobb szélének követése a lejátszó kurzorával.
        Futtatás UTÁN a sáv a kötés zárásán áll, azt nem mozgatjuk tovább."""
        if self._tengely is None:
            return
        for b in self._belepok:
            if b.kock is None and b.cel is None:
                continue
            x1 = self._tengely.hol(int(b.ido.timestamp()))
            if x1 is None:
                continue
            _x2 = self._sav_vege(b, x1)
            for it in (b.kock, b.cel):
                if it is not None:
                    it.vege(_x2)

    # ── Kézi rajz-elemek ─────────────────────────────────────────────────
    def _rajzok_rajza(self) -> None:
        """A kézi rajzok (újra)építése.

        ⚠ MINDEN ELEM `removable=True` / jobbklikkel törölhető: rajzolni könnyű,
        törölni kell tudni, különben a chart egy kattintás után szemetes marad.
        A ROI `sigRemoveRequested`-je a MODELLBŐL is kiveszi — nem csak a
        képről —, különben mentéskor visszajönne."""
        for r in self._rajzok:
            if r.elem is not None:
                self._plot.removeItem(r.elem)
                r.elem = None
        if self._tengely is None:
            return
        for r in self._rajzok:
            _sz = szin("yellow")
            if r.fajta == "vizszintes":
                r.elem = pg.InfiniteLine(
                    pos=float(r.ar1), angle=0, movable=True,
                    pen=pg.mkPen(_sz, width=1),
                    hoverPen=pg.mkPen(_sz, width=3))
            elif r.fajta == "fuggoleges":
                x = self._tengely.hol(int(r.ido1.timestamp()))
                if x is None:
                    continue
                r.elem = pg.InfiniteLine(
                    pos=x, angle=90, movable=True,
                    pen=pg.mkPen(_sz, width=1),
                    hoverPen=pg.mkPen(_sz, width=3))
            else:
                x1 = self._tengely.hol(int(r.ido1.timestamp()))
                x2 = self._tengely.hol(int(r.ido2.timestamp()))
                if x1 is None or x2 is None:
                    continue
                r.elem = pg.LineSegmentROI(
                    [[x1, float(r.ar1)], [x2, float(r.ar2)]],
                    pen=pg.mkPen(_sz, width=2), removable=True)
                r.elem.sigRegionChangeFinished.connect(
                    lambda _x=None, _r=r: self._rajz_mozgott(_r))
                r.elem.sigRemoveRequested.connect(
                    lambda _x=None, _r=r: self._rajz_torol(_r))
            if r.elem is None:
                continue
            if r.fajta != "trend":
                r.elem.sigPositionChanged.connect(
                    lambda _x=None, _r=r: self._rajz_mozgott(_r))
                # ⚠ Az `InfiniteLine`-nak nincs jobbklikk-menüje; a törlést a
                # „Rajz törlése" gomb intézi (lásd `rajz_torol_mind`).
            r.elem.setZValue(-10)
            self._plot.addItem(r.elem)

    def _rajz_mozgott(self, r: "Rajz") -> None:
        """Húzás után VISSZAÍRJUK az időt/árat — a modell a mérvadó, nem a kép.
        Enélkül a mentés a lerakás pillanatának koordinátáit őrizné meg."""
        if r.elem is None or self._tengely is None:
            return
        if r.fajta == "vizszintes":
            r.ar1 = float(r.elem.value())
        elif r.fajta == "fuggoleges":
            _ido = self._ido_x(float(r.elem.value()))
            if _ido is not None:
                r.ido1 = _ido
        else:
            try:
                _p = r.elem.getSceneHandlePositions()
                _pk = [r.elem.mapSceneToParent(h[1]) for h in _p]
            except Exception:
                return
            if len(_pk) < 2:
                return
            _t1 = self._ido_x(_pk[0].x())
            _t2 = self._ido_x(_pk[1].x())
            if _t1 is None or _t2 is None:
                return
            r.ido1, r.ar1 = _t1, float(_pk[0].y())
            r.ido2, r.ar2 = _t2, float(_pk[1].y())

    def _rajz_torol(self, r: "Rajz") -> None:
        if r.elem is not None:
            self._plot.removeItem(r.elem)
            r.elem = None
        if r in self._rajzok:
            self._rajzok.remove(r)
        self._allapot.setText(_t("lab.rajz.db", n=len(self._rajzok)))

    def rajz_torol_mind(self) -> None:
        for r in list(self._rajzok):
            self._rajz_torol(r)
        self._fel_rajz = None

    def _be_jelolo_rajz(self) -> None:
        if getattr(self, "_be_vonal", None) is not None:
            self._plot.removeItem(self._be_vonal)
            self._be_vonal = None
        if self._be_ido is None or self._tengely is None:
            return
        x = self._tengely.hol(int(self._be_ido.timestamp()))
        if x is None:
            return
        self._be_vonal = pg.InfiniteLine(
            pos=x, angle=90, movable=True,
            pen=pg.mkPen(szin("cyan"), width=1, style=QtCore.Qt.DotLine),
            label="BE", labelOpts={"position": 0.9, "color": szin("cyan")})
        self._be_vonal.sigPositionChanged.connect(self._be_mozgott)
        self._plot.addItem(self._be_vonal)

    def _ido_x(self, x: float):
        """Chart-koordináta → IDŐPONT, a gyertyán belül is (percre kerekítve)."""
        if self._chart is None or len(self._chart) < 2:
            return None
        n = len(self._chart)
        i = int(np.floor(float(x) + 0.5))
        if not (0 <= i < n):
            i = max(0, min(n - 1, i))
        arany = max(0.0, min(0.999, float(x) + 0.5 - i))
        idx = self._chart.index
        koz = idx[1] - idx[0]
        return (idx[i] + pd.Timedelta(seconds=int(round(
            koz.total_seconds() * arany)))).floor("min")

    def _belepo_mozgott(self, b: "Belepo") -> None:
        t = self._ido_x(b.vonal.value())
        if t is None or t == b.ido:
            return
        b.ido = t
        self._terv_valtozott(rajzol=False)
        _be = self._be_ar(t)
        if _be is not None and b.sl is not None:
            self._savok_igazit(b, _be)
            if b.tp_vonal is not None:
                b.tp_vonal.setValue(b.tp_ar(_be))

    def _savok_igazit(self, b: "Belepo", be_ar: float) -> None:
        """A kockázat- és cél-sáv ÁR-tartományának igazítása a húzás után.

        ⚠ EGY HELYEN, ÉS ELLENŐRZÖTT LÉTEZÉSSEL. A húzás-kezelők a FŐSZÁLON
        futnak: ha egy hiányzó rajz-elemen szállnak el, azzal a felület
        eseményhurka áll meg (a napló `⛔ A főszál elkapatlan kivétellel állt
        le.` sora pontosan ez volt). A modell attól még helyes; a kép a
        következő teljes rajzolásnál úgyis helyreáll."""
        if b.sl is None:
            return
        if b.kock is not None:
            b.kock.sav(be_ar, b.sl)
        if b.cel is not None:
            b.cel.sav(be_ar, b.tp_ar(be_ar))

    def _sl_mozgott(self, b: "Belepo") -> None:
        b.sl = float(b.sl_vonal.value())
        _be = self._be_ar(b.ido)
        if _be is None:
            return
        # ⚠ A TP A STOP FÜGGVÉNYE: húzod a pirosat, mozog a zöld.
        b.tp_vonal.blockSignals(True)
        b.tp_vonal.setValue(b.tp_ar(_be))
        b.tp_vonal.blockSignals(False)
        self._savok_igazit(b, _be)
        self._terv_valtozott(rajzol=False)

    def _tp_mozgott(self, b: "Belepo") -> None:
        _be = self._be_ar(b.ido)
        if _be is None or b.sl is None:
            return
        _tav = abs(_be - b.sl)
        if _tav <= 0:
            return
        d = 1 if b.irany == "BUY" else -1
        b.rr = max(0.0, d * (float(b.tp_vonal.value()) - _be) / _tav)
        b.tp_vonal.label.setFormat(f"TP {b.rr:0.2f}R")
        self._savok_igazit(b, _be)
        self._terv_valtozott(rajzol=False)

    def _be_mozgott(self) -> None:
        t = self._ido_x(self._be_vonal.value())
        if t is not None:
            self._be_ido = t
            self._terv_valtozott(rajzol=False)

    def _terv_valtozott(self, rajzol: bool = True) -> None:
        """A terv változott → a korábbi futtatás érvénytelen."""
        self._eredmeny = None
        for it in getattr(self, "_egyenleg_elemek", []):
            self._egyenleg.removeItem(it)
        if hasattr(self, "_egyenleg_elemek"):
            self._egyenleg_elemek.clear()
        if hasattr(self, "_szamla"):
            self._szamla.setText("")
        for it in self._eredmeny_elemek:
            self._plot.removeItem(it)
        self._eredmeny_elemek.clear()
        if rajzol:
            self._belepok_rajz()

    # ── Kattintás ────────────────────────────────────────────────────────
    def _kattintas(self, ev) -> None:
        if self._mod is None or self._chart is None:
            return
        if ev.button() != QtCore.Qt.LeftButton:
            return
        p = self._vb.mapSceneToView(ev.scenePos())
        t = self._ido_x(p.x())
        if t is None:
            return
        if self._mod in Rajz.FAJTAK:
            # ⚠ A TRENDVONALHOZ KÉT KATTINTÁS KELL. Az elsőt félkészen
            # eltesszük, és a mód BEKAPCSOLVA MARAD, amíg a második meg nem jön
            # — különben a fél vonal ott ragadna a képen befejezhetetlenül.
            if self._mod == "trend" and self._fel_rajz is None:
                self._fel_rajz = Rajz("trend", t, float(p.y()))
                self._allapot.setText(_t("lab.rajz.trend_masodik"))
                return
            if self._mod == "trend":
                self._fel_rajz.ido2 = t
                self._fel_rajz.ar2 = float(p.y())
                self._rajzok.append(self._fel_rajz)
                self._fel_rajz = None
            else:
                self._rajzok.append(Rajz(self._mod, t, float(p.y())))
            self._mod_valt(self._mod)
            self._rajzok_rajza()
            self._allapot.setText(_t("lab.rajz.db", n=len(self._rajzok)))
            return
        if self._mod == "BE":
            self._be_ido = t
        else:
            b = Belepo(t, self._mod, self._alap_sl(t, self._mod),
                       self._tp_rr.value())
            self._belepok.append(b)
            self._valasztott = b
        # ⚠ LERAKÁS UTÁN a mód kikapcsol: a következő mozdulat IGAZÍTÁS.
        self._mod_valt(self._mod)
        self._terv_valtozott()

    # ── Forgatókönyv és futtatás ─────────────────────────────────────────
    def _rr_ertekek(self) -> dict:
        ki = {}
        for k, e in self._rr_mezok.items():
            _sz = (e.text() or "").strip().replace(",", ".")
            if not _sz:
                continue
            try:
                ki[k] = float(_sz)
            except ValueError:
                continue
        return ki

    def _forgatokonyv(self) -> dict:
        _f = self._tol.text() or (str(self._chart.index[0])[:16]
                                  if self._chart is not None else "")
        _i = self._ig.text() or (str(self._chart.index[-1])[:16]
                                 if self._chart is not None else "")
        return {
            "symbol": self._sym.currentText(),
            "strategy": self._strat_nev(),
            "from": _f, "to": _i,
            "entries": [
                {"time": str(b.ido)[:16], "direction": b.irany,
                 **({"sl": float(b.sl), "tp_rr": float(b.rr)}
                    if b.sl is not None else {})}
                for b in sorted(self._belepok, key=lambda e: e.ido)],
            "breakeven_at": (str(self._be_ido)[:16] if self._be_ido else None),
            "rr_preset": "off",
            "rr": self._rr_ertekek(),
            "build": bool(self._epites.isChecked()),
            "balance": 1000.0,
            "use_strategy_signals": False,
            "exec_gates": False,
            # ⚠ A RAJZOK CSAK A KÉPHEZ TARTOZNAK — a `lab_scenario.futtat()` nem
            # ismeri és nem is kell ismernie őket (a `MINTA`-n kívüli kulcsokat
            # figyelmen kívül hagyja). Azért kerülnek MÉGIS a fájlba, mert
            # anélkül a megrajzolt trendvonalak az ablak bezárásakor elvesznének.
            "drawings": [r.szotar() for r in self._rajzok if r.kesz()],
        }

    def ment(self) -> None:
        import json
        ut, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, _t("lab.forgatokonyv_mentese"), "fk.json", "JSON (*.json)")
        if not ut:
            return
        try:
            Path(ut).write_text(json.dumps(self._forgatokonyv(),
                                           ensure_ascii=False, indent=2),
                                encoding="utf-8")
            self._allapot.setText(f"mentve: {ut}")
        except OSError as ex:
            QtWidgets.QMessageBox.critical(self, "Mentés", str(ex))

    def megnyit(self) -> None:
        """Mentett forgatókönyv visszaolvasása.

        ⚠ EDDIG CSAK MENTÉS VOLT. A felület kiírta a JSON-t, de visszatölteni
        nem tudta — így a megrajzolt terv és a vonalak az ablak bezárásakor
        elvesztek. Egy „mentés visszaolvasás nélkül" funkció félkész: úgy
        viselkedik, mintha megőrizné a munkát, holott nem."""
        import json
        ut, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, _t("lab.forgatokonyv_megnyitasa"), "", "JSON (*.json)")
        if not ut:
            return
        try:
            fk = json.loads(Path(ut).read_text(encoding="utf-8"))
        except (OSError, ValueError) as ex:
            QtWidgets.QMessageBox.critical(self, "Megnyitás", str(ex))
            return
        if not isinstance(fk, dict):
            QtWidgets.QMessageBox.critical(self, "Megnyitás",
                                           _t("lab.hiba.nem_forgatokonyv"))
            return
        self.forgatokonyv_betolt(fk)
        self._allapot.setText(f"megnyitva: {ut}")

    def forgatokonyv_betolt(self, fk: dict) -> None:
        """Egy forgatókönyv-SZÓTÁR visszatöltése a felületre.

        ⚠ Külön a fájl-párbeszédtől (`megnyit`), hogy TESZTELHETŐ legyen: a
        `QFileDialog` nélkül is meghívható, tehát a mentés→betöltés kör
        ellenőrizhető."""
        # ── Adat-választók: CSAK ha a config ismeri ─────────────────────
        _sym = fk.get("symbol")
        if _sym in self._parok:
            self._sym.setCurrentText(_sym)
            self._strat_lista()
        _st = fk.get("strategy") or NINCS_STRAT
        if self._strat.findText(_st) >= 0:
            self._strat.setCurrentText(_st)
        for _mezo, _k in ((self._tol, "from"), (self._ig, "to")):
            if fk.get(_k):
                _mezo.setText(str(fk[_k]))
        # ── Terv ────────────────────────────────────────────────────────
        self.torol()
        self.rajz_torol_mind()
        for e in (fk.get("entries") or []):
            try:
                _b = Belepo(pd.Timestamp(e["time"]), e.get("direction", "BUY"),
                            e.get("sl"), float(e.get("tp_rr", 2.0)))
            except (KeyError, ValueError, TypeError):
                continue
            self._belepok.append(_b)
        if fk.get("breakeven_at"):
            try:
                self._be_ido = pd.Timestamp(fk["breakeven_at"])
            except ValueError:
                pass
        for _k, _e in self._rr_mezok.items():
            if _k in (fk.get("rr") or {}):
                _e.setText(str(fk["rr"][_k]))
        self._epites.setChecked(bool(fk.get("build")))
        for d in (fk.get("drawings") or []):
            r = Rajz.szotarbol(d) if isinstance(d, dict) else None
            if r is not None:
                self._rajzok.append(r)
        # ⚠ A `betolt()` ÚJRAOLVASSA a chartot (más pár/időszak lehet), és a
        # végén kirakja a tervet és a rajzokat is — ezért nem hívunk külön
        # `_belepok_rajz`-t: az az idő-tengely nélkül még nem tudna hova rakni.
        self._valasztott = self._belepok[0] if self._belepok else None
        self._eredmeny = None
        # ⚠ ELŐBB a chart, AZTÁN az időzóna-igazítás. A JSON NAIV időt tárol
        # (ahogy a charton látod), a parquet indexe viszont ZÓNA-TUDATOS
        # (szerver-idő) — a kettő összehasonlítása `TypeError`. Ugyanaz a
        # csapda, mint a `lab_chart._vag`-ban; azért itt dől el, mert a chart
        # zónáját csak a betöltés után ismerjük.
        self._idok_igazit()      # a MODELL a chart zónájába (a mentés is ezt írja)
        self.betolt()            # …majd a chart + a teljes újrarajzolás
        self._idok_igazit()      # …és ha a pár váltásával más lett a zóna
        self._belepok_rajz()
        self._rajzok_rajza()
        self._kurzor_rajz()
        self._listak_frissit()

    def _ido_zonaba(self, ts):
        """Egy időpont a CHART időzónájába (naiv → lokalizált, eltérő → váltva)."""
        if ts is None:
            return None
        try:
            ts = pd.Timestamp(ts)
        except (ValueError, TypeError):
            return None
        tz = getattr(getattr(self._chart, "index", None), "tz", None)
        if tz is None:
            return ts.tz_localize(None) if ts.tzinfo is not None else ts
        return ts.tz_localize(tz) if ts.tzinfo is None else ts.tz_convert(tz)

    def _idok_igazit(self) -> None:
        """A betöltött terv és rajzok időpontjai a chart zónájába."""
        for b in self._belepok:
            b.ido = self._ido_zonaba(b.ido)
        self._be_ido = self._ido_zonaba(self._be_ido)
        for r in self._rajzok:
            r.ido1 = self._ido_zonaba(r.ido1)
            r.ido2 = self._ido_zonaba(r.ido2)

    def torol(self) -> None:
        self._belepok.clear()
        self._be_ido = None
        self._valasztott = None
        self._terv_valtozott()
        self._listak_frissit()

    def futtat(self) -> None:
        if not self._belepok:
            return
        self._allapot.setText(_t("lab.futtatas"))
        QtWidgets.QApplication.processEvents()
        try:
            from tools.lab_scenario import futtat as _futtat
            self._eredmeny = _futtat(self._forgatokonyv())
        except SystemExit as ex:
            self._eredmeny = None
            self._allapot.setText(f"HIBA: {ex}")
            return
        except Exception as ex:
            log.exception("a forgatókönyv futtatása elbukott")
            self._eredmeny = None
            self._allapot.setText(f"HIBA: {type(ex).__name__}: {ex}")
            return
        self._eredmeny_rajz()
        self._egyenleg_rajz()
        self._listak_frissit()

    def _biztos_eredmeny(self) -> None:
        """A `Play` futtat — külön gomb nélkül, és csak ha a terv változott."""
        if self._eredmeny is None and self._belepok:
            self.futtat()

    def _eredmeny_rajz(self) -> None:
        """A motor LEZÁRT kötései: nyitó pont + a nyitást a zárással összekötő
        vonal. A nyitott pozíció Entry/SL/TP vonalait a `_nyitott_rajz` teszi
        ki, mert azok a lejátszó kurzorától függenek (MT5-konvenció)."""
        for it in self._eredmeny_elemek:
            self._plot.removeItem(it)
        self._eredmeny_elemek.clear()
        res = (self._eredmeny or {}).get("res")
        _sszeg = []
        for t in (getattr(res, "trades", None) or []):
            x1 = self._tengely.hol(int(t.open_time.timestamp()))
            if x1 is None:
                continue
            _it = pg.ScatterPlotItem([x1], [t.open_price], size=10, symbol="o",
                                     brush=pg.mkBrush(szin("white")))
            self._plot.addItem(_it)
            self._eredmeny_elemek.append(_it)
            if t.close_time is not None:
                x2 = self._tengely.hol(int(t.close_time.timestamp()))
                if x2 is not None:
                    _ny = (t.pnl_usd or 0) > 0
                    _it = pg.PlotDataItem(
                        [x1, x2], [t.open_price, t.close_price],
                        pen=pg.mkPen(szin("green" if _ny else "red"), width=2))
                    self._plot.addItem(_it)
                    self._eredmeny_elemek.append(_it)
            # ⚠ A NYITOTT pozíció Entry/SL/TP vonalai NEM ITT rajzolódnak.
            # Azok a LEJÁTSZÓ KURZORÁTÓL függnek (`_nyitott_rajz`): amíg a
            # pozíció él, ott a három vonal, ahogy MT5-ben; záráskor eltűnnek,
            # és marad az őket összekötő vonal (fent). Egy statikus, teljes
            # idővonalra kiterített stop-út mást mutatna, mint a terminál.
            if t.close_time is not None:
                try:
                    _sszeg.append(t.pnl_usd / t.risk_usd if t.risk_usd else 0.0)
                except (TypeError, ZeroDivisionError):
                    pass
        _zart = [t for t in (getattr(res, "trades", None) or [])
                 if t.close_time is not None]
        if _zart:
            self._allapot.setText(
                _t("lab.status.closed", n=len(_zart),
                   pnl=f"{sum(t.pnl_usd for t in _zart):+.2f}",
                   r=f"{sum(_sszeg):+.2f}"))

    # ── Listák ───────────────────────────────────────────────────────────
    def _szamla_gorbe(self):
        """`(realizált, equity, kezdő)` — a vékony burok a tiszta számítás körül.

        ⚠ MOST MÁR VAN GYORSÍTÓTÁR (2026-09-09). A `szamla_gorbe` fejlécében az
        állt, hogy a gyorsítótár hiánya MÉRT döntés — és az is volt, az akkori
        kötésszámoknál (300 kötés → 4,5 ms). Ez a mérés viszont NEM
        általánosított: a görbe a KURZORTÓL FÜGGETLEN (csak a chart, a kötések és
        a kezdő egyenleg határozza meg), a `_szamla_frissit` mégis minden
        lejátszás-képen újraszámolta. 1000 kötésnél ez 18 ms/kép — a 60 kép/mp
        keretének a harmada, egyetlen olyan számításra, aminek az eredménye
        képről képre BITAZONOS.

        Az érvénytelenítés AZONOSSÁG szerint megy (`is`), nem érték szerint: a
        gyorsítótár megtartja a hivatkozásokat, tehát nincs `id()`-újrafelhasználás.
        """
        res = (self._eredmeny or {}).get("res")
        if res is None or self._chart is None or len(self._chart) < 2:
            return None
        kezdo = float((self._eredmeny or {}).get("balance") or 0.0)
        c = getattr(self, "_gorbe_cache", None)
        if (c is not None and c[0] is res and c[1] is self._chart
                and c[2] == kezdo):
            return c[3]
        ki = szamla_gorbe(self._chart, getattr(res, "trades", None) or [], kezdo)
        self._gorbe_cache = (res, self._chart, kezdo, ki)
        return ki

    def _egyenleg_rajz(self) -> None:
        for it in self._egyenleg_elemek:
            self._egyenleg.removeItem(it)
        self._egyenleg_elemek.clear()
        g = self._szamla_gorbe()
        if g is None:
            self._szamla.setText("")
            return
        real, eq, kezdo = g
        x = np.arange(len(real), dtype=float)
        # A kezdő egyenleg vonala — enélkül nem látszik, mikor megyünk mínuszba.
        _ln = pg.InfiniteLine(pos=kezdo, angle=0,
                              pen=pg.mkPen("#4a5560", style=QtCore.Qt.DashLine))
        self._egyenleg.addItem(_ln)
        self._egyenleg_elemek.append(_ln)
        self._egyenleg_elemek.append(
            self._egyenleg.plot(x, eq, pen=pg.mkPen("#4ea1ff", width=1)))
        self._egyenleg_elemek.append(
            self._egyenleg.plot(x, real, pen=pg.mkPen("#7ecb7e", width=2)))
        self._szamla_frissit()

    def _szamla_frissit(self) -> None:
        """Az IDŐPILLANAT-nézet: a számla állapota a kurzornál (vagy a végén)."""
        g = self._szamla_gorbe()
        if g is None:
            self._szamla_kiir("")
            return
        real, eq, kezdo = g
        i = self._kurzor if self._kurzor is not None else len(real) - 1
        i = max(0, min(len(real) - 1, int(i)))
        _t_kurzor = self._chart.index[i]
        _res = (self._eredmeny or {}).get("res")
        _nyitott = sum(1 for tr in (getattr(_res, "trades", None) or [])
                       if tr.open_time <= _t_kurzor
                       and (tr.close_time is None or tr.close_time > _t_kurzor))
        _dd = float(np.min(eq[:i + 1] - np.maximum.accumulate(eq[:i + 1])))
        self._szamla_kiir(_t(
            "lab.status.account",
            time=str(_t_kurzor)[:16],
            balance=f"{real[i]:.2f}", floating=f"{eq[i] - real[i]:+.2f}",
            equity=f"{eq[i]:.2f}", open=_nyitott, dd=f"{_dd:.2f}"))

    def _szamla_kiir(self, szoveg: str) -> None:
        """A számla-állapot kiírása — a saját sorba ÉS a munkaterületnek.

        ⚠ CHARTBÓL TÖBB VAN, SZÁMLA-SORBÓL EGY. A munkaterületen a sor az AKTÍV
        charté; a szöveg elé odaírjuk, melyikről van szó, mert minden chartnak
        SAJÁT forgatókönyve és eredménye van (a szinkron csak az időt osztja
        meg). Egy közös, jelöletlen sor azt sugallná, hogy egy számláról szól —
        holott három külön kísérlet három külön állapota."""
        self._szamla.setText(szoveg)
        _f = getattr(self, "_szamla_figyelo", None)
        if _f is not None:
            try:
                _f(self, szoveg)
            except Exception:
                self._szamla_figyelo = None

    def _listak_frissit(self) -> None:
        """A két kötés-tábla frissítése a kurzor állásához.

        ⚠ EZ A LEJÁTSZÁS SZŰK KERESZTMETSZETE (2026-09-09, mérve). A `_utem()`
        másodpercenként akár 60-szor hívja, és a régi változat MINDEN képen
        letarolta a táblákat (`setRowCount(0)`), majd **új
        `QTableWidgetItem`-et allokált minden cellára, minden kötéshez**:

            kötés     tábla/kép     kép/mp
                0       0,07 ms      6131
              100       8,99 ms       110
              250      22,82 ms        44   ← már észrevehető
              500      47,15 ms        21   ← akad
             1000     115,78 ms         9   ← használhatatlan

        A RAJZ közben KONSTANS 0,58 ms/kép — 395 és 20 325 gyertyánál is
        ugyanannyi (a pyqtgraph a gyertyákat egyszer rajzolja). Vagyis az
        akadást SOSEM a gyertyaszám okozta, hanem a kötésszám, a tábla-újraépítésen
        keresztül. Ezért nem segítene rajta más nyelv sem: a költség Qt-widget-
        allokáció, nem számítás.

        A JAVÍTÁS: a cellák ÚJRAHASZNOSULNAK (`_tabla_ir`), és csak a
        ténylegesen megváltozott szöveg íródik ki. A `setRowCount` csak akkor
        fut, ha a sorok SZÁMA változott.
        """
        # ⚠ REJTETT PANEL → NINCS MUNKA — DE CSAK HA SENKI NEM NÉZI. A táblák
        # építése a lejátszás legdrágább része (mérve: 1000 kötésnél 5 ms/kép a
        # gyorsítótárak UTÁN is). A munkaterületen viszont a KÖZÖS dokk mutatja
        # ugyanezeket a sorokat, tehát ott akkor is kellenek, ha a chart saját
        # panelje rejtve van.
        _figyelo = getattr(self, "_szamla_figyelo", None)
        if not getattr(self, "_kotes_panel_lathato", True) and _figyelo is None:
            return
        res = (self._eredmeny or {}).get("res")
        self._kotes_sorok = ([], [])
        # ⚠ A lezárt-sor gyorsítótár a RES-hez tartozik: új futtatás → új kötés-
        # objektumok → ürítés. (A `_c[0] is not tr` őr ezt külön is elkapja, de a
        # szótár így nem nő korlátlanul egy hosszú laboratóriumi ülés alatt.)
        if getattr(self, "_lezart_cache_res", None) is not res:
            self._lezart_cache = {}
            self._lezart_cache_res = res
        if res is None:
            self._tabla_ir(self._tablak["nyitott"], [])
            self._tabla_ir(self._tablak["lezart"], [])
            self._szamla_frissit()
            return
        _kt = self._kurzor_ido()
        _nyitott_sorok, _lezart_sorok = [], []
        for tr in (getattr(res, "trades", None) or []):
            if _kt is not None:
                if tr.open_time > _kt:
                    continue
                _nyitva = (tr.close_time is None) or (tr.close_time > _kt)
            else:
                _nyitva = tr.close_time is None
            _d = 1 if tr.direction == "BUY" else -1
            _sl0 = tr.open_price - _d * tr.sl_points * tr.point_size
            if _nyitva:
                _most, _perc = self._ar_ido_kurzornal(tr.open_time)
                _r = _pnl = float("nan")
                if _most is not None:
                    _kock = tr.sl_points * tr.point_size
                    _r = ((_most - tr.open_price) * _d / _kock) if _kock else float("nan")
                    try:
                        _pnl = _r * float(tr.risk_usd or 0.0)
                    except (TypeError, ValueError):
                        _pnl = float("nan")
                _nyitott_sorok.append([
                    str(tr.open_time)[5:16], tr.direction,
                    self._ar(tr.open_price),
                    self._ar(_most) if _most is not None else "—",
                    "—" if _pnl != _pnl else f"{_pnl:+.2f}",
                    "—" if _r != _r else f"{_r:+.2f}",
                    self._ar(_sl0), self._ar(tr.tp),
                    "—" if _perc is None else f"{_perc:.0f}"])
            else:
                # ⚠ A LEZÁRT sor a kurzortól FÜGGETLEN (nyitó/záró ár és idő,
                # realizált P&L) — egyszer kiszámoljuk, utána csak elővesszük.
                # A nyitott sor viszont képről képre változik (mozog az ár),
                # azt nem lehet gyorsítótárazni.
                _c = self._lezart_cache.get(id(tr))
                if _c is None or _c[0] is not tr:
                    try:
                        _r = (tr.pnl_usd / tr.risk_usd) if tr.risk_usd else 0.0
                    except (TypeError, ZeroDivisionError):
                        _r = 0.0
                    _c = (tr, [
                        str(tr.open_time)[5:16], tr.direction,
                        self._ar(tr.open_price), str(tr.close_time)[5:16],
                        f"{tr.pnl_usd:+.2f}", f"{_r:+.2f}", tr.status])
                    self._lezart_cache[id(tr)] = _c
                _lezart_sorok.append(_c[1])
        # ⚠ A SOROKAT ELTESSZÜK: a munkaterület közös dokkja innen veszi őket
        # (a `_szamla_figyelo`-n keresztül értesül, hogy van új).
        self._kotes_sorok = (_nyitott_sorok, _lezart_sorok)
        if getattr(self, "_kotes_panel_lathato", True):
            self._tabla_ir(self._tablak["nyitott"], _nyitott_sorok)
            self._tabla_ir(self._tablak["lezart"], _lezart_sorok)
        # A kurzor mozgásakor az IDŐPILLANAT-nézet is frissül.
        self._szamla_frissit()

    @staticmethod
    def _tabla_ir(tabla, sorok) -> None:
        """A táblát a `sorok`-ra állítja — a cellák ÚJRAHASZNOSÍTÁSÁVAL.

        A régi út (`setRowCount(0)` + `insertRow` + új `QTableWidgetItem`
        cellánként) másodpercenként több ezer widget-allokációt jelentett a
        lejátszás alatt. Itt csak akkor keletkezik új cella, ha a tábla NŐTT, és
        csak akkor íródik szöveg, ha ténylegesen megváltozott.
        """
        if tabla.rowCount() != len(sorok):
            tabla.setRowCount(len(sorok))
        for r, ertekek in enumerate(sorok):
            for c, v in enumerate(ertekek):
                sz = str(v)
                it = tabla.item(r, c)
                if it is None:
                    it = QtWidgets.QTableWidgetItem(sz)
                    it.setTextAlignment(QtCore.Qt.AlignCenter)
                    tabla.setItem(r, c, it)
                elif it.text() != sz:
                    it.setText(sz)

    def _ar(self, ar) -> str:
        """Ár a pár tizedeseivel. ⚠ `%.5g` NEM: nagy szinten exponenciálisra
        vált, és a szintek egyformává válnak (a projektben már háromszor elsült)."""
        try:
            import math
            pc = (self.cfg.get("pairs") or {}).get(self._sym.currentText()) or {}
            ps = float(pc.get("point_size") or 0.0)
            tiz = 0 if ps <= 0 else min(8, max(0, int(round(-math.log10(ps)))))
            return f"{float(ar):.{tiz}f}"
        except (TypeError, ValueError, OverflowError):
            return "—"

    def _ar_ido_kurzornal(self, nyitas):
        if self._chart is None or len(self._chart) == 0:
            return None, None
        i = (int(self._kurzor) if self._kurzor is not None
             else len(self._chart) - 1)
        i = max(0, min(len(self._chart) - 1, i))
        try:
            _perc = (self._chart.index[i] - nyitas).total_seconds() / 60.0
        except (TypeError, ValueError):
            _perc = None
        return float(self._chart["close"].iloc[i]), _perc

    # ── Lejátszás ────────────────────────────────────────────────────────
    def play_szunet(self) -> None:
        if self._chart is None or len(self._chart) < 2:
            return
        self._biztos_eredmeny()
        if self._szinkron is not None and self._szinkron.jatszik():
            self._szinkron.szunet()
            return
        if self._ido_zito.isActive():
            self._ido_zito.stop()
            self._play.setText("▶ Play")
            return
        if self._kurzor is None:
            self._kurzor = 0
        # KAPCSOLT ablak: a közös óra vezet, a sajátunk NEM indul el (két
        # időzítő két ablakon néhány másodperc alatt szétcsúszna).
        if self._szinkron is not None:
            self._szinkron.play(self)
            return
        self._play.setText("⏸ Pause")
        self._utem_indit()

    def _utem_indit(self) -> None:
        _seb = max(1.0, float(self._sebesseg.value()))
        self._lepes = max(1, int(round(_seb / MAX_KEP_MP)))
        self._ido_zito.start(max(int(1000 / MAX_KEP_MP),
                                 int(1000 * self._lepes / _seb)))

    def _utem(self) -> None:
        if self._chart is None or self._kurzor is None:
            return
        if self._kurzor >= len(self._chart) - 1:
            self._ido_zito.stop()
            self._play.setText("▶ Play")
            return
        self._kurzor = min(len(self._chart) - 1,
                           self._kurzor + getattr(self, "_lepes", 1))
        self._kurzor_rajz()
        self._listak_frissit()
        self._utem_indit()

    def leptet(self, n: int) -> None:
        if self._chart is None:
            return
        self._ido_zito.stop()
        self._play.setText("▶ Play")
        self._biztos_eredmeny()
        alap = self._kurzor if self._kurzor is not None else 0
        self._kurzor = max(0, min(len(self._chart) - 1, alap + int(n)))
        self._kurzor_rajz()
        self._listak_frissit()
        self._kozzetesz()

    def kurzor_le(self) -> None:
        if self._szinkron is not None and self._szinkron.jatszik():
            self._szinkron.szunet()
        self._ido_zito.stop()
        self._play.setText("▶ Play")
        self._kurzor = None
        self._kurzor_rajz()
        self._listak_frissit()
        self._kozzetesz()

    def _kurzor_huzva(self) -> None:
        if self._chart is None:
            return
        self._ido_zito.stop()
        self._play.setText("▶ Play")
        self._biztos_eredmeny()
        self._kurzor = max(0, min(len(self._chart) - 1,
                                  int(round(self._kurzor_vonal.value()))))
        self._kurzor_rajz(vonal=False)
        self._listak_frissit()
        # ⚠ A HÚZÁS IS SZINKRON: lejátszás nélkül is ez a leggyakoribb mozdulat
        # („mit csinált ekkor a másik idősík?").
        self._kozzetesz()

    # ══ A SZINKRON FELÜLETE ══════════════════════════════════════════════
    # A `Szinkron` KIZÁRÓLAG ezt a négy metódust hívja az ablakon. Szűk felület
    # → az ablak belseje szabadon változhat anélkül, hogy a szinkron eltörne.

    def kurzor_ido(self):
        """A kurzor ideje (a szinkron ebből olvas)."""
        return self._kurzor_ido()

    def play_felirat(self, jatszik: bool) -> None:
        """A Play/Pause felirat — a szinkron állítja MINDEN tagon egyszerre."""
        self._play.setText("⏸ Pause" if jatszik else "▶ Play")

    def szinkron_tempo(self):
        """`(most, veg, sebesseg, tf_perc)` — a VEZÉR tempó-adatai.

        A `most` a kurzor ideje; ha még nincs kurzor, a chart ELEJE (a Play
        onnan indul). A `veg` a saját chartunk utolsó gyertyája — a közös óra
        eddig megy."""
        if self._chart is None or not len(self._chart):
            return None, None, 1.0, 1
        most = self._kurzor_ido()
        if most is None:
            most = self._chart.index[0]
        return (most, self._chart.index[-1],
                float(self._sebesseg.value()), int(self._tf.currentData()))

    def szinkron_ido(self, t) -> None:
        """A szinkron ÁLLÍTJA az időnket. Nem toljuk vissza (végtelen kör)."""
        self._szinkron_alatt = True
        try:
            self._biztos_eredmeny()
            self._kurzor_vissza(t)
            self._kurzor_rajz()
            self._listak_frissit()
        finally:
            self._szinkron_alatt = False

    def _kozzetesz(self) -> None:
        """A saját kurzor-időnket kitoljuk a többi kapcsolt ablakra."""
        if self._szinkron is None or self._szinkron_alatt:
            return
        self._szinkron.allit(self._kurzor_ido(), forras=self)

    def _kapcsol(self, be: bool) -> None:
        """Be/kilépés a közös időbe.

        ⚠ BELÉPÉSKOR A MÁR BENT LÉVŐK IDEJE NYER. Fordítva az újonnan
        bekapcsolt ablak elrántaná a többit oda, ahol épp a saját kurzora áll —
        ami pont az ellenkezője annak, amit a kapcsoló ígér."""
        if not be:
            if self._szinkron is not None:
                self._szinkron.kilep(self)
            self._szinkron = None
            return
        sz = szinkron()
        t = sz.ido()                 # a MÁR bent lévőké (én még nem vagyok tag)
        self._szinkron = sz
        sz.belep(self)
        if t is not None:
            self.szinkron_ido(t)
        else:
            self._kozzetesz()

    def _uj_ablak(self) -> None:
        """Új labor-ablak UGYANARRA az instrumentumra, a KÖVETKEZŐ idősíkon.

        ⚠ A hivatkozást MEG KELL TARTANI (`_ABLAKOK`): egy helyi változóban
        tartott `QMainWindow`-t a szemétgyűjtő bezárja, amint a metódus véget
        ér — az ablak felvillanna és eltűnne."""
        _tfk = [perc for perc, _ in IDOSIKOK]
        try:
            _i = _tfk.index(int(self._tf.currentData()))
        except (ValueError, TypeError):
            _i = 0
        if self._munkaterulet is not None:
            # A munkaterületen BELÜL nyílik, nem külön lebegő ablakként.
            self._munkaterulet.uj_chart(
                symbol=self._sym.currentText(), strategy=self._strat_nev(),
                tf_perc=None,           # a munkaterület a SZABAD idősíkot adja
                tol=self._tol.text() or None, ig=self._ig.text() or None,
                kapcsol_hozza=self)
            return
        w = LabAblak(symbol=self._sym.currentText(),
                     strategy=self._strat_nev(),
                     tf_perc=_tfk[(_i + 1) % len(_tfk)],
                     tol=self._tol.text() or None, ig=self._ig.text() or None)
        _ABLAKOK.append(w)
        # ⚠ A MÁSODIK ablakban a kötés-tábla felesleges: ugyanazt mutatná, mint
        # az első. A chart kapja a helyet — ezért a „＋ Új ablak" alapból
        # elrejti (a jelölővel bármikor visszakapcsolható).
        w._kotesek.setChecked(False)
        w.show()
        w.betolt()
        # Az ÚJ ablakot csak úgy van értelme megnyitni, ha van mihez kötni:
        # mindkettőt bekapcsoljuk (a sajátunkat előbb, hogy a közös idő a
        # MIÉNK legyen, és az új ablak igazodjon hozzá).
        self._kapcs.setChecked(True)
        w._kapcs.setChecked(True)

    def closeEvent(self, ev):
        """⚠ Bezáráskor KI KELL lépni: különben a szinkron egy halott ablakot
        próbálna rajzoltatni, és a lejátszás minden képen kivételt dobna."""
        try:
            if self._szinkron is not None:
                self._szinkron.kilep(self)
        finally:
            self._szinkron = None
        if self in _ABLAKOK:
            _ABLAKOK.remove(self)
        super().closeEvent(ev)

    def _kotes_panel(self, *_a) -> None:
        """A kötés-táblák mutatása/rejtése."""
        self._kotes_panel_lathato = bool(self._kotesek.isChecked())
        self._fulek.setVisible(self._kotes_panel_lathato)
        self._szamla.setVisible(self._kotes_panel_lathato)
        if self._kotes_panel_lathato:
            self._listak_frissit()

    def _kurzor_ido(self):
        if self._kurzor is None or self._chart is None:
            return None
        i = max(0, min(len(self._chart) - 1, int(self._kurzor)))
        return self._chart.index[i]

    def _kurzor_vissza(self, t) -> None:
        """Idősík-váltás után a kurzor UGYANARRA az időre. ⚠ Bar-indexben
        őrizve M15→M1 tizenötszörös ugrás lenne."""
        if t is None or self._chart is None:
            self._kurzor = None
            return
        poz = self._chart.index.get_indexer([t], method="nearest")
        self._kurzor = int(poz[0]) if len(poz) and poz[0] >= 0 else None

    def _kurzor_rajz(self, vonal: bool = True) -> None:
        van = self._kurzor is not None and self._chart is not None
        self._kurzor_vonal.setVisible(van)
        for _l in (self._bid, self._ask):
            _l.setVisible(van and self._bidask.isChecked())
        self._takaro.setVisible(van and self._csak_eddig.isChecked())
        if not van:
            self._ido_cimke.setText("")
            return
        i = int(self._kurzor)
        if vonal:
            self._kurzor_vonal.blockSignals(True)
            self._kurzor_vonal.setValue(i + 0.5)
            self._kurzor_vonal.blockSignals(False)
        sor = self._chart.iloc[i]
        if self._bidask.isChecked():
            bid = float(sor["close"])
            self._bid.setValue(bid)
            self._ask.setValue(bid + float(sor.get("avg_spread", 0.0) or 0.0))
        if self._csak_eddig.isChecked():
            self._takaro.setRegion((i + 0.5, len(self._chart) + 5))
        self._ido_cimke.setText(
            self._chart.index[i].strftime("%Y-%m-%d %H:%M"))
        self._sav_frissit()
        self._nyitott_rajz()
        self._trail_lathatosag()
        self._cimke_helyre()

    def _cimke_helyre(self) -> None:
        try:
            (x0, x1), (y0, y1) = self._vb.viewRange()
            self._ido_cimke.setPos(x1, y0)
        except Exception:
            pass


# ══ AZ ELRENDEZÉS MEGJEGYZÉSE KÉT INDÍTÁS KÖZT ═══════════════════════════

ELRENDEZES_PATH = ROOT / "data" / "lab_elrendezes.json"
ELRENDEZES_VERZIO = 1


def _b64(qba) -> str:
    return bytes(qba.toBase64()).decode("ascii")


def _qba(szoveg: str):
    return QtCore.QByteArray.fromBase64(
        QtCore.QByteArray(str(szoveg).encode("ascii")))


def elrendezes_leiro(mt) -> dict:
    """A munkaterület állapota SZÓTÁRKÉNT (menthető alak).

    ⚠ A geometriát és a dokk-elrendezést a Qt maga szerializálja
    (`saveGeometry`/`saveState`) — ezeket base64-ben tesszük el. A CHARTOKAT
    viszont nem: azokat névvel írjuk le (pár, stratégia, idősík, időszak), mert
    egy Qt-blob nem mondaná meg, MIT kell újra betölteni."""
    chartok = []
    for sw in mt._mdi.subWindowList():
        w = sw.widget()
        if not isinstance(w, LabAblak):
            continue
        r = sw.geometry()
        chartok.append({
            "symbol": w._sym.currentText(),
            "strategy": w._strat_nev(),
            "tf": int(w._tf.currentData() or 15),
            "tol": w._tol.text() or None,
            "ig": w._ig.text() or None,
            "geo": [r.x(), r.y(), r.width(), r.height()],
            "max": bool(sw.isMaximized()),
            "kotesek": bool(w._kotesek.isChecked()),
            "kapcsolt": bool(w._kapcs.isChecked()),
        })
    return {
        "verzio": ELRENDEZES_VERZIO,
        "ablak_geometria": _b64(mt.saveGeometry()),
        "ablak_allapot": _b64(mt.saveState()),
        "tabos": bool(mt._tabos.isChecked()),
        "chartok": chartok,
    }


def elrendezes_ment(mt) -> bool:
    """Az elrendezés kiírása. `False`, ha nem sikerült (és NAPLÓZ)."""
    try:
        ELRENDEZES_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = ELRENDEZES_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(elrendezes_leiro(mt), ensure_ascii=False,
                                  indent=2), encoding="utf-8")
        tmp.replace(ELRENDEZES_PATH)
        return True
    except Exception as ex:
        # ⚠ NEM NÉMA. A mentés elmaradása csak a KÖVETKEZŐ indításkor derülne
        # ki („miért nem emlékszik?"), és akkor sem tudnánk, miért.
        log.warning("%s: a labor-elrendezés MENTÉSE nem sikerült (%s) — a "
                    "következő indítás az alapelrendezéssel jön.",
                    ELRENDEZES_PATH.name, ex)
        return False


def elrendezes_olvas() -> dict:
    """A mentett elrendezés, vagy üres dict.

    ⚠ A HIÁNYZÓ fájl (első indítás) NORMÁLIS → csend. A SÉRÜLT fájl elveszett
    beállítás → naplózunk. A kettő összemosása a projekt visszatérő hibája."""
    try:
        d = json.loads(ELRENDEZES_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as ex:
        log.warning("%s: a mentett labor-elrendezés nem olvasható (%s) — az "
                    "alapelrendezéssel indulunk.", ELRENDEZES_PATH.name, ex)
        return {}
    if not isinstance(d, dict) or int(d.get("verzio") or 0) != ELRENDEZES_VERZIO:
        log.info("%s: eltérő verziójú elrendezés — kihagyva.",
                 ELRENDEZES_PATH.name)
        return {}
    return d


class Munkaterulet(QtWidgets.QMainWindow):
    """A labor MUNKATERÜLETE: több chart EGY területen (MT5-szerű).

    ⚠ MIÉRT KELL. A több-ablakos szinkron (v3.59.0) külön TOP-LEVEL ablakokat
    nyitott. Használatban azonnal kiderült, hogy ez nem elrendezhető: az
    ablakok egymásra csúsznak, a tálcán szétszóródnak, és a KÖZÖS elemek
    (számla-állapot) ablakonként duplázódnak.

    Itt a chartok egy `QMdiArea`-ban laknak: szabadon mozgathatók és
    átméretezhetők a területen belül, vagy egy gombbal mozaikba/lépcsőbe/
    sorokba/oszlopokba rendezhetők — és teljes méretben TABULÁTOROS nézetre
    válthatók, ahogy az MT5 is mutatja a chartjait.

    ⚠ CHARTBÓL TÖBB, SZÁMLA-SORBÓL EGY. Az állapotsor mindig az AKTÍV charté,
    és ki is írja, melyiké — minden chartnak SAJÁT forgatókönyve és
    backteszt-eredménye van (a szinkron csak az IDŐT osztja meg). Egy közös,
    jelöletlen sor azt sugallná, hogy egy számláról szól.

    ⚠ AMI A 2. VERZIÓRA MARAD (a felhasználó kérése szerint): a chart
    KIVÉTELE külön, lebegő ablakba. A `QMdiArea` ezt nem adja készen; a
    `LabAblak` viszont ma is megáll önállóan (a `main()` `--egy` kapcsolója
    így indítja), tehát a kiszakítás nem szerkezeti akadály, csak munka.
    """

    def __init__(self, symbol=None, strategy=None, tf_perc=15, tol=None, ig=None):
        super().__init__()
        from version import APP_NAME, APP_VERSION
        self.setWindowTitle(_t("lab.window_title", app=APP_NAME,
                               version=APP_VERSION))
        self.resize(1600, 1000)
        self._mdi = QtWidgets.QMdiArea()
        self._mdi.setViewMode(QtWidgets.QMdiArea.SubWindowView)
        self._mdi.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self._mdi.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self._mdi.subWindowActivated.connect(self._aktiv_valtozott)
        self.setCentralWidget(self._mdi)

        m = self.menuBar().addMenu(_t("lab.menu_ablak"))
        self._tett(m, _t("lab.menu_uj_chart"), self.uj_chart)
        m.addSeparator()
        self._tett(m, _t("lab.menu_mozaik"), self._mdi.tileSubWindows, "Alt+R")
        self._tett(m, _t("lab.menu_lepcsos"), self._mdi.cascadeSubWindows)
        self._tett(m, _t("lab.menu_vizszintes"), lambda: self._rendez(True))
        self._tett(m, _t("lab.menu_fuggoleges"), lambda: self._rendez(False))
        m.addSeparator()
        self._tabos = QtGui.QAction(_t("lab.menu_tabos"), self)
        self._tabos.setCheckable(True)
        self._tabos.triggered.connect(self._tabos_valt)
        m.addAction(self._tabos)

        # ── EGY számla-sor, az AKTÍV chartról — DOKKOLHATÓ panelben ──────
        # ⚠ FOGD ÉS VIDD. Az állapotsor (`statusBar`) oda van szögezve az ablak
        # aljára; a `QDockWidget` viszont megfogható, áthúzható a négy oldal
        # bármelyikére, LEBEGŐVÉ tehető (kiszakítható külön ablakba), és
        # bezárható. A chartok ugyanígy szabadon mozognak az MDI-területen —
        # így a felület minden darabja a felhasználóé.
        # ⚠ A SZÁMLA ÁLLAPOTA = a sor ÉS a nyitott/lezárt LISTÁK. A listák
        # korábban chartonként külön voltak; kapcsolt ablakoknál (M1+M5+M15
        # ugyanarra a párra) ugyanaz jelent meg háromszor, ráadásul a chart
        # helyét vitte. Egy chart = egy NÉZET ugyanarra a kísérletre; a
        # POZÍCIÓK viszont a kísérlethez tartoznak, nem a nézethez.
        self._szamla = QtWidgets.QLabel("")
        self._szamla.setStyleSheet("color:#9fb4c8; padding:6px;")
        self._szamla.setWordWrap(True)
        self._szamla.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self._dokk_fulek, self._dokk_tablak = kotes_tablak()
        _doboz = QtWidgets.QWidget()
        _el = QtWidgets.QVBoxLayout(_doboz)
        _el.setContentsMargins(0, 0, 0, 0)
        _el.setSpacing(2)
        _el.addWidget(self._szamla)
        _el.addWidget(self._dokk_fulek, 1)
        self._szamla_dokk = QtWidgets.QDockWidget(_t("lab.dokk_szamla"), self)
        self._szamla_dokk.setObjectName("szamla_dokk")
        self._szamla_dokk.setWidget(_doboz)
        self._szamla_dokk.setAllowedAreas(QtCore.Qt.AllDockWidgetAreas)
        self._szamla_dokk.setFeatures(
            QtWidgets.QDockWidget.DockWidgetMovable
            | QtWidgets.QDockWidget.DockWidgetFloatable
            | QtWidgets.QDockWidget.DockWidgetClosable)
        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea, self._szamla_dokk)
        m.addSeparator()
        m.addAction(self._szamla_dokk.toggleViewAction())

        self._tett(m, _t("lab.menu_elrendezes_felejt"), self._elrendezes_felejt)

        # ⚠ A PARANCSSOR NYER A MENTETT ELRENDEZÉS FÖLÖTT. Ha a felhasználó
        # `--symbol`-lal indít, azt akarja látni — nem azt, amit két hete
        # bezárt. Mentett elrendezést csak ARGUMENTUM NÉLKÜLI indításnál
        # töltünk vissza; a keret (ablakméret, dokkok) viszont mindig.
        _ment = elrendezes_olvas()
        if _ment.get("ablak_geometria"):
            self.restoreGeometry(_qba(_ment["ablak_geometria"]))
        if _ment.get("ablak_allapot"):
            self.restoreState(_qba(_ment["ablak_allapot"]))
        _visszaall = bool(_ment.get("chartok")) and symbol is None
        if _visszaall:
            self._chartok_vissza(_ment)
        else:
            self.uj_chart(symbol=symbol, strategy=strategy, tf_perc=tf_perc,
                          tol=tol, ig=ig)
        if _ment.get("tabos"):
            self._tabos.setChecked(True)
            self._tabos_valt(True)

    def _chartok_vissza(self, ment: dict) -> None:
        """A mentett chartok újranyitása.

        ⚠ A KIHAGYOTT CHART NEM NÉMÁN VÉSZ EL: ha a pár azóta kikerült a
        configból, megmondjuk, melyik és miért — különben a felhasználó csak
        annyit látna, hogy „egy ablakom eltűnt"."""
        _parok = set((self.cfg_parok() or []))
        _elso = True
        for c in ment.get("chartok") or []:
            _sym = c.get("symbol")
            if _parok and _sym not in _parok:
                log.warning("A mentett labor-elrendezésből KIMARAD a(z) %s: "
                            "nincs (már) a config `pairs` blokkjában.", _sym)
                continue
            try:
                w = self.uj_chart(symbol=_sym, strategy=c.get("strategy") or None,
                                  tf_perc=c.get("tf") or 15,
                                  tol=c.get("tol"), ig=c.get("ig"))
            except Exception as ex:
                log.warning("A mentett labor-chart (%s) nem nyitható meg: %s",
                            _sym, ex)
                continue
            w._kotesek.setChecked(bool(c.get("kotesek", _elso)))
            if c.get("kapcsolt"):
                w._kapcs.setChecked(True)
            _g = c.get("geo") or []
            _sw = w.parent()
            if len(_g) == 4 and isinstance(_sw, QtWidgets.QMdiSubWindow):
                if c.get("max"):
                    _sw.showMaximized()
                else:
                    _sw.setGeometry(int(_g[0]), int(_g[1]),
                                    max(120, int(_g[2])), max(80, int(_g[3])))
            _elso = False
        if not self.chartok():          # minden chart kimaradt → legyen egy
            self.uj_chart()

    def cfg_parok(self) -> list:
        """A configban létező párok (a mentett elrendezés szűréséhez)."""
        ch = self.chartok()
        if ch:
            return list(ch[0]._parok)
        try:
            from strategy.settings import load_config
            cfg = load_config(ROOT / "config.json")
            return sorted(k for k, v in (cfg.get("pairs") or {}).items()
                          if isinstance(v, dict))
        except Exception:
            return []

    def _elrendezes_felejt(self) -> None:
        """A mentett elrendezés eldobása (a következő indítás alapból jön)."""
        try:
            ELRENDEZES_PATH.unlink(missing_ok=True)
            self.statusBar().showMessage(_t("lab.elrendezes_elfelejtve"), 5000)
        except Exception as ex:
            log.warning("%s: az elrendezés nem törölhető (%s)",
                        ELRENDEZES_PATH.name, ex)

    def closeEvent(self, ev):
        """⚠ A BEZÁRÁS az egyetlen biztos pont: a felhasználó nem fog külön
        „elrendezés mentése" gombot nyomogatni."""
        elrendezes_ment(self)
        super().closeEvent(ev)

    def _tett(self, menu, cim, fn, gyorsbillentyu=None):
        a = QtGui.QAction(cim, self)
        if gyorsbillentyu:
            a.setShortcut(gyorsbillentyu)
        a.triggered.connect(lambda *_: fn())
        menu.addAction(a)
        return a

    # ── chartok ──────────────────────────────────────────────────────────
    def chartok(self) -> list:
        ki = []
        for sw in self._mdi.subWindowList():
            w = sw.widget()
            if isinstance(w, LabAblak):
                ki.append(w)
        return ki

    def _szabad_tf(self, symbol) -> int:
        """A KÖVETKEZŐ, ezen a páron még nem nyitott idősík.

        ⚠ Enélkül két „Új chart" ugyanazt az idősíkot nyitná meg kétszer (mérve:
        M15-ből kétszer H1 lett), mert a „következő" a HÍVÓ chart idősíkjából
        számolódott, nem a már meglévőkből."""
        _van = {int(c._tf.currentData() or 0) for c in self.chartok()
                if c._sym.currentText() == symbol}
        for perc, _ in IDOSIKOK:
            if perc not in _van:
                return perc
        return IDOSIKOK[0][0]

    def uj_chart(self, symbol=None, strategy=None, tf_perc=None, tol=None,
                 ig=None, kapcsol_hozza=None) -> "LabAblak":
        """Új chart a munkaterületen belül."""
        _meglevo = self.chartok()
        if symbol is None and _meglevo:
            symbol = _meglevo[-1]._sym.currentText()
        if tf_perc is None:
            tf_perc = self._szabad_tf(symbol)
        w = LabAblak(symbol=symbol, strategy=strategy, tf_perc=int(tf_perc),
                     tol=tol, ig=ig)
        w._munkaterulet = self
        w._szamla_figyelo = self._szamla_jott
        # A chart SAJÁT számla-sora elrejtve: a munkaterületen egy van belőle.
        w._szamla.setVisible(False)
        # ⚠ A chart SAJÁT kötés-panelje a munkaterületen belül nem kell: a
        # közös dokk mutatja ugyanezt. A jelölőt is elrejtjük — egy kapcsoló,
        # ami semmit nem kapcsol, rosszabb, mint ha ott sem volna.
        w._kotesek.setChecked(False)
        w._kotesek.setVisible(False)
        sw = self._mdi.addSubWindow(w)
        sw.setWindowTitle(f"{symbol or '?'} · "
                          f"{dict(IDOSIKOK).get(int(tf_perc), tf_perc)}")
        sw.resize(1000, 700)
        sw.show()
        w.betolt()
        if kapcsol_hozza is not None:
            kapcsol_hozza._kapcs.setChecked(True)
            w._kapcs.setChecked(True)
        return w

    # ── elrendezés ───────────────────────────────────────────────────────
    def _rendez(self, vizszintes: bool) -> None:
        """Sorokba (vízszintes) vagy oszlopokba (függőleges) rendezés.

        ⚠ A `QMdiArea` csak mozaikot és lépcsőt tud; a sor/oszlop az MT5
        „Vízszintes/Függőleges elrendezés" párja, azt kézzel számoljuk."""
        ablakok = [sw for sw in self._mdi.subWindowList() if not sw.isHidden()]
        if not ablakok:
            return
        if self._mdi.viewMode() != QtWidgets.QMdiArea.SubWindowView:
            self._tabos.setChecked(False)
            self._tabos_valt(False)
        ter = self._mdi.viewport().rect()
        n = len(ablakok)
        for i, sw in enumerate(ablakok):
            if sw.isMaximized():
                sw.showNormal()
            if vizszintes:
                h = max(80, ter.height() // n)
                sw.setGeometry(0, i * h, ter.width(), h)
            else:
                w_ = max(120, ter.width() // n)
                sw.setGeometry(i * w_, 0, w_, ter.height())

    def _tabos_valt(self, be: bool) -> None:
        self._mdi.setViewMode(QtWidgets.QMdiArea.TabbedView if be
                              else QtWidgets.QMdiArea.SubWindowView)
        if be:
            self._mdi.setTabsClosable(True)
            self._mdi.setTabsMovable(True)
            self._mdi.setTabPosition(QtWidgets.QTabWidget.South)

    # ── a KÖZÖS számla-sor ───────────────────────────────────────────────
    def _szamla_jott(self, chart, szoveg: str) -> None:
        """Egy chart frissítette az állapotát — csak az AKTÍV érdekel."""
        if chart is self._aktiv_chart():
            self._szamla_kiir(chart, szoveg)
            self._kotesek_kiir(chart)

    def _kotesek_kiir(self, chart) -> None:
        """Az AKTÍV chart nyitott/lezárt sorai a közös dokkba."""
        _ny, _le = (getattr(chart, "_kotes_sorok", None) or ([], [])) \
            if chart is not None else ([], [])
        LabAblak._tabla_ir(self._dokk_tablak["nyitott"], _ny)
        LabAblak._tabla_ir(self._dokk_tablak["lezart"], _le)

    def _aktiv_chart(self):
        sw = self._mdi.activeSubWindow()
        w = sw.widget() if sw is not None else None
        if isinstance(w, LabAblak):
            return w
        ch = self.chartok()
        return ch[0] if ch else None

    def _szamla_kiir(self, chart, szoveg: str) -> None:
        """A közös sor kiírása — MINDIG a chart nevével.

        ⚠ A NÉV AKKOR IS KELL, HA NINCS ÁLLAPOT. Egy chart, amin még nem futott
        forgatókönyv, üres állapotot ad; ha ilyenkor a sor teljesen kiürülne, a
        felhasználó nem tudná, hogy „nincs mit mutatni EZEN a charton", vagy
        hogy a sor épp nem frissül. A név + gondolatjel egyértelmű."""
        if chart is None:
            self._szamla.setText("")
            return
        _tf = dict(IDOSIKOK).get(int(chart._tf.currentData() or 0),
                                 chart._tf.currentData())
        self._szamla.setText(f"[{chart._sym.currentText()} · {_tf}]  "
                             f"{szoveg or '—'}")

    def _aktiv_valtozott(self, *_a) -> None:
        """Chart-váltás: a közös panel AZONNAL a másik chartét mutassa.

        ⚠ Nem várhatunk a chart következő frissítésére: az csak akkor jön, ha
        mozdul a kurzora. Addig a panel a RÉGI chart pozícióit mutatná az ÚJ
        chart neve alatt."""
        w = self._aktiv_chart()
        if w is None:
            self._szamla.setText("")
            self._kotesek_kiir(None)
            return
        self._szamla_kiir(w, w._szamla.text())
        self._kotesek_kiir(w)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbol")
    ap.add_argument("--strategy")
    ap.add_argument("--tf", type=int, default=15)
    ap.add_argument("--from", dest="tol")
    ap.add_argument("--to", dest="ig")
    ap.add_argument("--egy", action="store_true",
                    help="EGYETLEN chart-ablak, munkaterület nélkül (a régi mód)")
    a = ap.parse_args(argv)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    oszt = LabAblak if a.egy else Munkaterulet
    w = oszt(symbol=a.symbol, strategy=a.strategy, tf_perc=a.tf,
             tol=a.tol, ig=a.ig)
    w.show()
    return app.exec()


if __name__ == "__main__":
    _sys.exit(main())

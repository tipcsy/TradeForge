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
import time as _time

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
        # ⚠ NINCS ISMÉTLŐDŐ IDŐZÍTŐ — lásd `_utem`. A következő képet MINDIG a
        # kész kép UTÁN ütemezzük egyszeri időzítővel; a lejátszás állapotát
        # ez a jelző tartja, nem a `QTimer.isActive()`.
        self._jatszik = False
        self._utolso = None          # az előző ütem wall-clock ideje
        self._var_festes = False     # a vezér festésére várunk-e
        self._utem_kezdet = 0.0

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
        return bool(self._jatszik)

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

    def kp_allit(self, be: bool, pct: int, forras=None) -> None:
        """A kontrollpont-beállítás KÖZÖS: egy ablakban bekapcsolva mind bont.

        ⚠ Enélkül az M1-en lejátszva az M15/H1 ablak KÉSZ gyertyát mutatott,
        holott a felhasználó épp a kialakulását akarta látni — a jelölő
        ablakonként külön ült, és csak ott volt bekapcsolva, ahol rákattintott."""
        for a in list(self._tagok):
            if a is forras:
                continue
            try:
                a.kp_beallit(be, pct)
            except Exception:
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
        self._jatszik = True
        self._utolso = None
        self._kovetkezo_kep()
        for a in self._tagok:
            a.play_felirat(True)

    KEP_TARTALEK_MS = 150        # ha nem jön festés (rejtett ablak), ennyi után lépünk

    def _kovetkezo_kep(self) -> None:
        """A következő kép ütemezése — a MOSTANI kép KIFESTÉSE UTÁN.

        ⚠ MIÉRT A FESTÉSHEZ KÖTVE, ÉS NEM IDŐZÍTŐHÖZ. Windowson a WM_PAINT a
        LEGALACSONYABB prioritású üzenet: csak akkor jön, ha a sor egyébként
        üres. Egy 16 ms-os időzítő-lánc + a jelenet frissítései a sort sosem
        hagyták kiürülni → a Qt SOHA nem festett, és a többi időzítő (200 ms-os
        szívverés, 1,5 mp-es próba) SEM futott le — mérve: 20 másodpercen át
        „utem" 85 ms-onként, 0 festés, 0 szívverés. A felhasználó ezt látta:
        szürke, „nem válaszol" ablak, a Pause-ra nem reagál. (Előtte ugyanez
        ismétlődő időzítővel; az egyszeri lánc önmagában nem oldotta meg.)

        Ha a következő képet a VEZÉR FESTÉSE indítja, akkor a sorrend
        szerkezetileg garantált: a frissítés után az egér, a billentyű, a
        többi időzítő, VÉGÜL a festés jön — és csak azután a következő lépés.
        Tartalék-időzítő arra az esetre, ha nincs festés (rejtett/minimalizált
        ablak): akkor ritkábban, de megy tovább."""
        v = self._vezer
        self._var_festes = True
        self._utem_kezdet = _time.perf_counter()
        _lepes_kesz = False
        if v is not None:
            try:
                v.kep_utan(self._kep_kesz)
                _lepes_kesz = True
            except Exception as ex:               # régi/idegen vezér — tartalék
                log.debug("kep_utan nem elérhető: %s", ex)
        QtCore.QTimer.singleShot(self.KEP_TARTALEK_MS, self._kep_tartalek)
        if not _lepes_kesz:
            self._var_festes = False
            QtCore.QTimer.singleShot(int(1000 / MAX_KEP_MP), self._utem)

    def _kep_kesz(self) -> None:
        """A vezér kifestette a képet → jöhet a következő (legalább 16 ms-onként)."""
        if not self._var_festes:
            return
        self._var_festes = False
        _eltelt = (_time.perf_counter() - self._utem_kezdet) * 1000.0
        QtCore.QTimer.singleShot(int(max(1.0, 1000.0 / MAX_KEP_MP - _eltelt)),
                                 self._utem)

    def _kep_tartalek(self) -> None:
        if self._var_festes and self._jatszik:
            self._var_festes = False
            self._utem()

    def szunet(self) -> None:
        self._jatszik = False
        for a in list(self._tagok):
            try:
                a.play_felirat(False)
            except Exception:
                self._tagok.remove(a)

    def _utem(self) -> None:
        if not self._jatszik:
            return
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
        #
        # ⚠ MIÉRT EGYSZERI IDŐZÍTŐ, ÉS MIÉRT WALL-CLOCK LÉPÉS. Az ismétlődő
        # `QTimer` 16 ms-onként LŐTT — függetlenül attól, hogy az előző kép
        # elkészült-e. Ha a kép (Python + a Qt FESTÉSE) tovább tartott, az
        # időzítő eseménye már a sorban volt, mire a kezelő visszatért: az
        # eseményhurok SOHA nem ürült ki, a kattintás (Pause!) a sor végén
        # várt, és a felület „beragadt, homokórázott" — háromszor egymás
        # után, három különböző forró-úti tétellel. (Mérve: 3 kapcsolt ablak,
        # teljes időszak, görgetéssel: 130 ütem 10 kép alatt.) Az első
        # önszabályozó változat csak a Python-részt mérte, a festést nem —
        # ezért nem segített.
        #
        # Most: a következő képet a MOSTANI kép kezelője ütemezi, egyszeri
        # időzítővel. Két kép közt így MINDIG van legalább 16 ms, amiben a
        # festés, az egér és a billentyű sorra kerül — ez SZERKEZETI garancia,
        # nem a forró út gyorsaságán múlik. A chart-idő sebessége pedig marad:
        # a lépés a TÉNYLEGESEN eltelt wall-clock időből számolódik (lassú
        # kép → ritkább, de nagyobb lépés). Felső korlát 0,5 mp: egy
        # megakasztott alkalmazás (fájlpárbeszéd, hibernálás) után nem
        # ugrunk órákat.
        _most_wc = _time.perf_counter()
        _alap_mp = 1.0 / MAX_KEP_MP
        _eltelt = (_most_wc - self._utolso) if self._utolso is not None else _alap_mp
        self._utolso = _most_wc
        _eltelt = min(0.5, max(_alap_mp, _eltelt))
        uj = kovetkezo_ido(self._ido if self._ido is not None else most,
                           lepes_ido(seb, tf, kep_mp=1.0 / _eltelt), veg)
        if uj is None:
            self.szunet()
            return
        self.allit(uj, forras=None)
        if self._jatszik:
            self._kovetkezo_kep()


# ⚠ A megnyitott ablakok hivatkozásai. Enélkül a `_uj_ablak`-ban létrehozott
# `QMainWindow`-t a szemétgyűjtő azonnal elvinné (a Qt-oldali objektum a Python
# hivatkozással együtt megy), és az ablak felvillanás után eltűnne.
class RajzTar:
    """KÖZÖS rajz-készlet több labor-ablaknak.

    ⚠ A rajzok IDŐBEN és ÁRBAN élnek (lásd `Rajz`), tehát idősík-függetlenek —
    ugyanaz a trendvonal az M1-en és a H1-en is ugyanoda mutat. Ezért lehet
    megosztani őket anélkül, hogy bármit át kellene számolni.

    ⚠ EGY LISTA, NEM HÁROM MÁSOLAT. A tagok UGYANARRA a listára hivatkoznak,
    ezért a felhasználó által kért törlés-szemantika magától adódik: „felrajzolok
    egy trendvonalat (megjelenik mindenhol), letörlöm (törlődik mindenhol)".
    Három másolatnál ehhez azonosítani kellene, melyik másolat melyiknek felel
    meg — és az elcsúszás csak idő kérdése volna."""

    def __init__(self):
        self.lista: list = []          # a RAJZOK
        self.belepok: list = []        # és a BELÉPŐK — együtt alkotják a TERVET
        self._tagok: list = []

    def belep(self, ablak) -> None:
        if ablak not in self._tagok:
            self._tagok.append(ablak)

    def kilep(self, ablak) -> None:
        if ablak in self._tagok:
            self._tagok.remove(ablak)

    def tagok(self) -> list:
        return list(self._tagok)

    def valtozott(self, forras=None) -> None:
        """Újrarajzoltat MINDEN tagot (a forrást kivéve — az már kész)."""
        for a in list(self._tagok):
            if a is forras:
                continue
            try:
                a.rajzok_ujra()
                a.belepok_ujra()
            except Exception:          # bezárt ablak ne akassza meg a többit
                self.kilep(a)


_RAJZTAR = None


def rajztar() -> "RajzTar":
    global _RAJZTAR
    if _RAJZTAR is None:
        _RAJZTAR = RajzTar()
    return _RAJZTAR


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


def egyenleg_rajzol(plot, elemek: list, gorbe) -> None:
    """A számlagörbe kirajzolása egy tetszőleges `PlotWidget`-be.

    ⚠ EGY FORRÁS: ugyanez a görbe kell a chart alatti csíkba (önálló mód) ÉS a
    munkaterület közös „Számla állapot" dokkjába. Két külön rajzoló előbb-utóbb
    máshogy skálázna, és a felhasználó azt hinné, két különböző számláról van
    szó."""
    for it in list(elemek):
        try:
            plot.removeItem(it)
        except Exception:
            pass
    elemek.clear()
    if gorbe is None:
        return
    real, eq, kezdo = gorbe
    x = np.arange(len(real), dtype=float)
    # A kezdő egyenleg vonala — enélkül nem látszik, mikor megyünk mínuszba.
    _ln = pg.InfiniteLine(pos=kezdo, angle=0,
                          pen=pg.mkPen("#4a5560", style=QtCore.Qt.DashLine))
    plot.addItem(_ln)
    elemek.append(_ln)
    elemek.append(plot.plot(x, eq, pen=pg.mkPen("#4ea1ff", width=1)))
    elemek.append(plot.plot(x, real, pen=pg.mkPen("#7ecb7e", width=2)))


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


# ══ KONTROLLPONTOK — a gyertya kibontakozása lejátszás közben ════════════
#
# ⚠ A MODELL AZ MT4 „Control points"-JÁÉ. Az MT4 tesztere egy gyertyán belüli
# árutat NEM tickekből, hanem a KÖVETKEZŐ KISEBB IDŐSÍK OHLC-jéből épít: minden
# al-gyertya négy pontot ad — nyitó, majd az alj és a csúcs (abban a
# sorrendben, ahogy az al-gyertya záró/nyitó viszonya sugallja), végül a záró.
# Az MT5-ben ugyanez „1 minute OHLC" néven él tovább.
#
# Nálunk a chart gyertyái M1-ből (M5/M15) vagy M15-ből (H1/H4) épülnek, tehát a
# finomabb idősík ADOTT: a bar alá eső M1 gyertyák.
#
# ⚠ EZ CSAK MEGJELENÍTÉS. A motort NEM érinti — és ezt MÉRÉS támasztja alá: az
# intrabar SL/TP sorrend (pesszimista vs optimista) 6 páron, 2759 kötésen
# 0,0000 R különbséget adott, 0 eltérően zárt kötéssel. A hangolt célárak
# 7–15 R-re vannak, egyetlen M1 gyertya sem fog át ekkora távot, tehát a
# finomabb végrehajtás a motorban bizonyítottan nem érne semmit.


def kontroll_pontok(al_barok, szazalek: float = 100.0):
    """A gyertyán BELÜLI árút kontrollpontjai a finomabb idősík OHLC-jéből.

    `al_barok`: a bar alá eső finomabb gyertyák (`open/high/low/close`).
    `szazalek`: milyen finoman — 100 = MINDEN al-gyertya, kevesebb = ritkítva.

    ⚠ A RITKÍTÁS NEM VÁGHAT LE CSÚCSOT. Bármilyen alacsony a százalék, a
    kiválasztott al-gyertyák közt MINDIG ott van az, amelyik a bar CSÚCSÁT adja,
    és az is, amelyik az ALJÁT — plusz az első és az utolsó (a nyitó és a záró
    miatt). Enélkül a ritkított lejátszás MÁS gyertyát rajzolna, mint a kész
    chart: ugyanaz a hibafajta, mint amikor a tick-deduplikáció levágta a
    high/low-t, vagy amikor a gyertya-összevonás (LOD) elvesztette a tüskét.
    """
    import numpy as _np
    if al_barok is None or len(al_barok) == 0:
        return _np.empty(0, dtype=float)
    o = _np.asarray(al_barok["open"], dtype=float)
    h = _np.asarray(al_barok["high"], dtype=float)
    l = _np.asarray(al_barok["low"], dtype=float)
    c = _np.asarray(al_barok["close"], dtype=float)
    n = len(o)

    try:
        pct = float(szazalek)
    except (TypeError, ValueError):
        pct = 100.0
    pct = min(100.0, max(1.0, pct))
    if pct >= 100.0:
        valasztott = list(range(n))
    else:
        _kell = max(1, int(round(n * pct / 100.0)))
        _lepes = max(1, int(round(n / _kell)))
        valasztott = list(range(0, n, _lepes))
        # A SZÉLSŐÉRTÉKEK és a két vég MINDIG kellenek.
        valasztott += [0, n - 1, int(_np.argmax(h)), int(_np.argmin(l))]
        valasztott = sorted(set(valasztott))

    ut = []
    for i in valasztott:
        # A sorrend az al-gyertya irányából: emelkedőnél O→L→H→C, esőnél O→H→L→C.
        # (Ez az MT4/MT5 közelítése; tick nélkül ennél többet nem lehet tudni.)
        ut.append(o[i])
        if c[i] >= o[i]:
            ut.extend((l[i], h[i]))
        else:
            ut.extend((h[i], l[i]))
        ut.append(c[i])
    return _np.asarray(ut, dtype=float)


def tick_pontok(arak, szazalek: float = 100.0):
    """A gyertyán BELÜLI árút TICKEKBŐL — az M1 gyertya „kontrollpontjai".

    ⚠ M1-EN A TICK A FINOMABB ADAT. A felhasználó: „a legfinomabb jelzés az a
    tick. Nekem M1-en ha azt látom, hogy Kontrollpont 100%, akkor az egyenrangú
    a tickkel!" Tickből nincs OHLC-sorrend-találgatás: az árút maga a
    tick-sorozat, a % pedig ritkítás — de a RITKÍTÁS ITT SEM VÁGHAT LE CSÚCSOT
    (ugyanaz az elv, mint a `kontroll_pontok`-nál): az első, az utolsó, a
    legmagasabb és a legalacsonyabb tick mindig benne marad."""
    import numpy as _np
    a = _np.asarray(arak, dtype=float)
    n = len(a)
    if n == 0:
        return _np.empty(0, dtype=float)
    try:
        pct = float(szazalek)
    except (TypeError, ValueError):
        pct = 100.0
    pct = min(100.0, max(1.0, pct))
    if pct >= 100.0 or n <= 4:
        return a
    _kell = max(1, int(round(n * pct / 100.0)))
    _lepes = max(1, int(round(n / _kell)))
    v = list(range(0, n, _lepes)) + [0, n - 1, int(_np.argmax(a)),
                                     int(_np.argmin(a))]
    return a[sorted(set(v))]


TICK_DIR = ROOT / "data" / "ticks"


def tick_nap(sym: str, nap, point_size: float):
    """EGY NAP tickjei `(idő-index UTC, bid-ár)` DataFrame-ként — vagy `None`.

    ⚠ A TICK-TÁR 19 GB, ezért NAPONKÉNT olvasunk, és a hívó gyorsítótáraz. A
    napi fájl (`_napok/<nap>.parquet`) az olcsó út; ha a nap már havi fájlba
    olvadt, a havi fájlból SZŰRVE olvasunk (`filters` → row-group-statisztika
    alapján a pyarrow csak az érintett csoportokat bontja ki). Az ár PONTBAN
    tárolt egész (`bid_pt`) — itt váltjuk vissza, ugyanúgy, mint a
    gyertya-építő (`tools/build_bars._bars_from_ticks`)."""
    try:
        _nap = pd.Timestamp(nap).tz_localize(None).normalize()
    except (TypeError, ValueError):
        return None
    _d = TICK_DIR / sym
    if not _d.is_dir():
        return None
    _napi = _d / "_napok" / ("%s.parquet" % _nap.strftime("%Y-%m-%d"))
    _havi = _d / ("%s.parquet" % _nap.strftime("%Y-%m"))
    _t0 = int(_nap.tz_localize("UTC").timestamp() * 1000)
    _t1 = _t0 + 86_400_000
    try:
        if _napi.exists():
            df = pd.read_parquet(_napi, columns=["time_msc", "bid_pt"])
        elif _havi.exists():
            df = pd.read_parquet(_havi, columns=["time_msc", "bid_pt"],
                                 filters=[("time_msc", ">=", _t0),
                                          ("time_msc", "<", _t1)])
        else:
            return None
    except Exception as ex:
        log.warning("%s — a %s napi tick-adat nem olvasható: %s",
                    sym, _nap.date(), ex)
        return None
    if df is None or df.empty:
        return None
    df = df[(df["time_msc"] >= _t0) & (df["time_msc"] < _t1)]
    if df.empty:
        return None
    _idx = pd.to_datetime(df["time_msc"].to_numpy(), unit="ms", utc=True)
    _bid = df["bid_pt"].to_numpy(dtype=float) * float(point_size)
    ki = pd.DataFrame({"bid": _bid}, index=_idx)
    return ki.sort_index()


_TICK_VAN: dict = {}


def tick_van(sym: str) -> bool:
    """Van-e egyáltalán tick-tár a párhoz? — GYORSÍTÓTÁRAZVA.

    ⚠ A KÖNYVTÁR-PÁSZTÁZÁS 2 ms, ÉS KÉPENKÉNT TÖBBSZÖR HÍVÓDOTT. A `_kp_aktiv`
    minden kurzor-rajzolásnál (és a `_kurzor_x`-en át még többször) kérdezi;
    három kapcsolt ablakkal ez 1,6 mp volt 60 képből — az időzítő gyorsabban
    lőtt, mint ahogy a képek elkészültek, a kattintás sorban állt, és a Pause
    „beragadt, homokórázott". Ugyanaz a hibafajta, mint a boolean maszk volt
    (20 ms/bar): egy olcsónak látszó hívás a forró úton. A tick-tár futás közben
    nem változik, egy válasz elég."""
    if sym in _TICK_VAN:
        return _TICK_VAN[sym]
    _d = TICK_DIR / sym
    _van = _d.is_dir() and (any(_d.glob("*.parquet"))
                            or any((_d / "_napok").glob("*.parquet")))
    _TICK_VAN[sym] = bool(_van)
    return _TICK_VAN[sym]


def reszgyertya(pontok, n: int):
    """A FORMÁLÓDÓ gyertya `(open, high, low, close)`-a az `n`-edik pontig.

    A nyitó az első pont, a záró az AKTUÁLIS pont, a csúcs/alj az eddig
    bejártak szélsőértéke — pontosan úgy, ahogy egy élő gyertya alakul."""
    import numpy as _np
    if pontok is None or len(pontok) == 0:
        return None
    i = max(0, min(len(pontok) - 1, int(n)))
    _eddig = _np.asarray(pontok[:i + 1], dtype=float)
    return (float(_eddig[0]), float(_eddig.max()), float(_eddig.min()),
            float(_eddig[-1]))


class Formalodo(pg.GraphicsObject):
    """A KIBONTAKOZÓ gyertya — egyetlen, folyamatosan újrarajzolt gyertya."""

    def __init__(self):
        super().__init__()
        self._x = 0.0
        self._ohlc = None

    def allit(self, x: float, ohlc) -> None:
        self.prepareGeometryChange()
        self._x, self._ohlc = float(x), ohlc
        self.update()

    def paint(self, p, *args):
        if not self._ohlc:
            return
        o, h, l, c = self._ohlc
        fel = c >= o
        p.setPen(pg.mkPen(szin("green" if fel else "red")))
        p.drawLine(QtCore.QPointF(self._x, l), QtCore.QPointF(self._x, h))
        p.setBrush(pg.mkBrush(szin("green" if fel else "red")))
        p.drawRect(QtCore.QRectF(self._x - 0.32, o, 0.64, (c - o) or 1e-9))

    def boundingRect(self):
        if not self._ohlc:
            return QtCore.QRectF()
        o, h, l, c = self._ohlc
        return QtCore.QRectF(self._x - 0.5, l, 1.0, (h - l) or 1e-9)


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


class Nezet(pg.ViewBox):
    """ViewBox, ami külön jelzi az EGÉRREL HÚZÁST.

    ⚠ A `sigRangeChangedManually` a görgőt (nagyítás) és a húzást (eltolás)
    EGYFORMÁN jelzi. A görgetés-módban a kettő mást jelent: húzáskor a
    felhasználó TEKER (a play-vonalat viszi), nagyításkor csak közelebb
    hajol — ilyenkor a kurzor maradjon, ahol volt. Ezért kell egy jelzés,
    ami csak a húzásról szól."""
    sigHuzva = QtCore.Signal()

    huzas = False                 # igaz, amíg az ősosztály a húzást dolgozza fel

    def mouseDragEvent(self, ev, axis=None):
        self.huzas = True
        try:
            super().mouseDragEvent(ev, axis)
        finally:
            self.huzas = False
        if (ev.button() == QtCore.Qt.LeftButton
                and self.state.get("mouseMode") != pg.ViewBox.RectMode):
            self.sigHuzva.emit()


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

    # ⚠ A RAJZ NEM HORDOZ QT-ELEMET (2026-09-10). Amíg egy rajz egyetlen
    # ablakban élt, kényelmes volt a grafikus elemet is benne tartani. Ha viszont
    # UGYANAZ a rajz három ablakban látszik (M1 + M5 + M15), akkor három elem
    # tartozik hozzá — egy mezőbe ez nem fér bele, és a második ablak némán
    # felülírná az elsőét. Az elemeket ezért ABLAKONKÉNT tartjuk nyilván
    # (`LabAblak._rajz_elem`), a `Rajz` pedig tiszta MODELL marad: idő + ár.

    def __init__(self, fajta, ido1=None, ar1=None, ido2=None, ar2=None):
        self.fajta = fajta
        self.ido1, self.ar1 = ido1, ar1
        self.ido2, self.ar2 = ido2, ar2

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


class Szakasz(pg.InfiniteLine):
    """HÚZHATÓ vonal, ami csak `a..b` között látszik (és fogható).

    ⚠ MIÉRT NEM SIMA `InfiniteLine`. Az KONSTRUKCIÓ SZERINT végigér a képen —
    egy stop, ami a pozíció zárása UTÁN is ott fekszik a charton, azt sugallja,
    hogy a pozíció még él (a felhasználó jelzése: „bezárta (SL), de a zöld és
    piros vonal továbbra is élt… a nyitás pillanatától a zárás pillanatáig
    kellene élnie"). Három belépőnél ráadásul hat végtelen vonal olvashatatlan.

    ⚠ MIÉRT NEM `LineSegmentROI`. Az két sarokfogóval jön, és a sarok az ÁRAT
    is vinné — itt a vonal csak függőlegesen (árban) húzható, a hossza pedig a
    pozíció élettartama, nem kézi beállítás. Az `InfiniteLine` húzása, címkéje
    és jelzései maradnak; csak a KITERJEDÉSÉT kötjük adat-koordinátához.

    A határ a vonal SAJÁT tengelyén értendő: vízszintes vonalnál (angle=0)
    x-ben (bar-index), függőlegesnél (angle=90) y-ban (ár). Belül a
    `span`-frakcióra fordítjuk, amit az ősosztály amúgy is ismer — így a
    rajzolás, a találat-terület és a címke helye mind követi."""

    def __init__(self, a, b, **kw):
        self._hatar = (float(a), float(b))
        super().__init__(**kw)

    def hatar(self, a, b) -> None:
        """A kiterjedés átállítása (lejátszás közben körönként hívható)."""
        _uj = (float(a), float(b))
        if _uj == self._hatar:
            return
        self._hatar = _uj
        self.viewTransformChanged()          # a rajz-terület újraszámolása
        _c = getattr(self, "label", None)    # csak címkés vonalnak van
        if _c is not None:
            _c.valueChanged()                # …és a címke utána

    def hatarok(self) -> tuple:
        return self._hatar

    def _computeBoundingRect(self):
        vr = self.viewRect()
        if vr is not None and vr.width() > 0:
            a, b = self._hatar
            if self.angle == 90:
                la = self.mapFromView(QtCore.QPointF(0.0, a)).x()
                lb = self.mapFromView(QtCore.QPointF(0.0, b)).x()
            else:
                la = self.mapFromView(QtCore.QPointF(a, 0.0)).x()
                lb = self.mapFromView(QtCore.QPointF(b, 0.0)).x()
            fa = (min(la, lb) - vr.left()) / vr.width()
            fb = (max(la, lb) - vr.left()) / vr.width()
            self.span = (max(0.0, min(1.0, fa)), max(0.0, min(1.0, fb)))
        return super()._computeBoundingRect()


class Belepo:
    """Egy terv-belépő: idő, irány, SL-ár, TP-szorzó — és a hozzá tartozó
    rajz-elemek.

    ⚠ AZ IDŐ AZ AZONOSÍTÓ, nem a bar-index: idősíkot váltva az indexek
    átszámozódnak, az időpont viszont ugyanaz marad."""

    # Az ABLAK ezekben a kulcsokban tartja a belépő rajz-elemeit.
    ELEM_MEZOK = ("vonal", "sl_vonal", "tp_vonal", "kock", "cel",
                  "trail_be", "trail_tav",
                  # A doboz-felület elemei (CSAK az aktív ablakban):
                  "szel", "cimke_tp", "cimke_sl", "cimke_kozep")

    def __init__(self, ido, irany, sl, rr):
        self.ido = ido
        self.irany = irany
        self.sl = sl
        self.rr = float(rr)
        self.nyitva = False     # a terv MEGNYITOTT pozícióvá vált-e
        # ⚠ A pozíció VÉGE — IDŐBEN, mint minden más ebben az osztályban.
        # `None` = automatikus (a kötés zárása, vagy a lejátszó kurzora); a
        # jobb oldali fogóval állítható, „ha véget ért a pozíció".
        self.veg = None
        # ⚠ A RAJZ-ELEMEK MÁR NEM ITT ÜLNEK (2026-09-10). Ugyanaz a lecke, mint
        # a `Rajz`-nál: ha EGY belépő TÖBB ablakban látszik (M1-en nyitva, de az
        # M5-ön és az M15-ön is látni akarjuk), ablakonként KÜLÖN Qt-elem
        # tartozik hozzá — egy mezőbe ez nem fér bele, és a második ablak NÉMÁN
        # felülírná az elsőét. Az elemeket az ablak tartja nyilván
        # (`LabAblak._be_elem`, `(id(Belepo), mező)` kulccsal); a `Belepo`
        # tiszta MODELL: idő, irány, SL, R.

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
        # KONTROLLPONTOK: a formálódó gyertya állapota.
        self._kp_pontok = None      # az AKTUÁLIS bar árútja
        self._kp_bar = None         # melyik barhoz tartozik
        self._kp_idx = 0            # hányadik ponton állunk
        self._m1_finom = None       # a finomabb (M1) gyertyák — lustán
        self._tick_nap = None       # az M1 alá: EGY nap tickjei — lustán
        self._kp_szinkron_alatt = False
        self._belepok = []
        self._be_ido = None
        self._eredmeny = None
        self._valasztott = None     # a kiválasztott belépő (annak látszik SL/TP)
        self._kurzor = None
        self._elemek = []           # a stratégia rajz-elemei (törléshez)
        self._eredmeny_elemek = []
        self._nyitott_elemek = []   # a NYITOTT pozíció vonalai (kurzor-függő)
        self._rajzok = []           # kézi rajz-elemek (trend / vízszintes / függőleges)
        self._rajz_elem = {}        # id(Rajz) -> Qt-elem (ABLAKONKÉNT)
        self._be_elem = {}          # (id(Belepo), mező) -> Qt-elem
        self._rajz_megosztva = False
        self._fel_rajz = None       # a félbehagyott trendvonal (1. kattintás megvolt)

        self._epit_ui(symbol, strategy, tf_perc, tol, ig)
        self._strat_lista()
        # ⚠ A `strategy=` PARAMÉTERT EDDIG NÉMÁN ELDOBTUK. A `_strat_lista()`
        # csak a KORÁBBI választást őrizte meg — ami a frissen épült combóban
        # üres, tehát „— nincs —"-re esett. Következmény: a
        # `main.py lab --strategy wpr_sma` stratégia NÉLKÜL indult, a
        # munkaterület `uj_chart(strategy=…)`-ja ugyanígy, és a mentett
        # elrendezésből visszaállított chartok is elvesztették a stratégiát —
        # mindezt hibaüzenet nélkül, csak a jelölők maradtak el a charton.
        if strategy:
            _lehet = [self._strat.itemText(i)
                      for i in range(self._strat.count())]
            if strategy in _lehet:
                self._strat.setCurrentText(strategy)
            else:
                log.warning("A kért stratégia (%r) nem elérhető ezen a páron "
                            "(%s) — a chart stratégia nélkül indul. Elérhető: %s",
                            strategy, self._sym.currentText(),
                            ", ".join(x for x in _lehet if x != NINCS_STRAT)
                            or "(egy sem)")
        self.betolt()

    # ── Felület ──────────────────────────────────────────────────────────
    def _epit_ui(self, symbol, strategy, tf_perc, tol, ig):
        kozep = QtWidgets.QWidget()
        self.setCentralWidget(kozep)
        fo = QtWidgets.QVBoxLayout(kozep)
        fo.setContentsMargins(6, 6, 6, 6)
        fo.setSpacing(4)

        # ── A HÁROM ESZKÖZSOR ÖNÁLLÓ WIDGET ─────────────────────────────
        # ⚠ MIÉRT NEM CSAK LAYOUT. A munkaterületen ezek a sorok DOKKBA
        # kerülnek (egy betöltő, egy rajzoló, egy lejátszó — nem chartonként
        # három). Egy `QLayout` nem tehető dokkba; egy `QWidget` igen, és
        # ráadásul ÁTHELYEZHETŐ oda-vissza. Így nincs szükség proxy-vezérlőkre:
        # a dokkban MAGA az aktív chart sora ül, tehát garantáltan azt
        # állítja, amit mutat.
        self._sor_betolto = QtWidgets.QWidget()
        self._sor_rajz = QtWidgets.QWidget()
        self._sor_lejatszo = QtWidgets.QWidget()

        # 1. sor: adat-választók
        s1 = QtWidgets.QHBoxLayout(self._sor_betolto)
        s1.setContentsMargins(2, 2, 2, 2)
        fo.addWidget(self._sor_betolto)
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
        s2 = QtWidgets.QHBoxLayout(self._sor_rajz)
        s2.setContentsMargins(2, 2, 2, 2)
        fo.addWidget(self._sor_rajz)
        s2.addWidget(QtWidgets.QLabel(_t("lab.kattintas")))
        self._mod = None
        self._mod_gombok = {}
        for ertek, cimke in (("BUY", "Add BUY"), ("SELL", "Add SELL"),
                             # ⚠ Az „Add BE" EGYELŐRE KI (2026-09-10,
                             # felhasználói kérés: „a BE-t kapcsoljuk ki, azzal
                             # majd külön kezdünk valamit"). A mód-kezelő
                             # változatlan; ha visszakerül, ez az egy sor elég.
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

        # ⚠ A BE / TRAILING MEZŐK LEKERÜLTEK (2026-09-09, felhasználói kérés:
        # „teljesen hibásan működik, nem tudom értelmezni").
        #
        # És a panasz mögött VALÓDI ok volt: ezek a mezők a modul
        # ALAPÉRTELMEZETT `breakeven_pct`-jével indultak, tehát a labor a
        # CÉLÁR-ARÁNYOS BE-t szimulálta — azt, amit a v3.56.0 óta a motor MÁR
        # NEM használ (a párok `breakeven_r = 1` R-alapú küszöbön futnak). A
        # laborban látott stop-viselkedés így nem is EGYEZHETETT az élessel.
        #
        # A javítás nem a mezők visszatétele, hanem a forrás: a labor mostantól
        # a PÁR SAJÁT, mentett kockázatcsökkentő kalibrációját használja —
        # ugyanazt, amiből a motor és a backteszt dolgozik (`rr_state`). A
        # `_rr_mezok` üres marad, hogy a mentett forgatókönyvek betöltése
        # (`forgatokonyv_betolt`) továbbra is működjön.
        self._rr_mezok = {}
        # ⚠ AZ AUTOMATIZMUS LÁTHATÓ ÉS ALAPBÓL KI. A v3.63.0 a pár mentett
        # kalibrációját NÉMÁN alkalmazta (`rr_preset: "off"` — aminek a NEVE
        # „ki", a JELENTÉSE viszont „BE + trailing"; a név-csapdát a backteszt
        # kódja is külön megjegyzi). A felhasználó ezt így látta: „valami
        # automatizmus túl korán lezárta (pozitívba!), pedig nincs bekapcsolva
        # sem entry-to-BE" — a 0,5 ATR-es trailing zárta. A laborban a kézi
        # kezelés a lényeg, ezért a pár BE/trailingje CSAK KÉRÉSRE fut, és
        # akkor látszik is a két vonala.
        self._rr_auto = QtWidgets.QCheckBox(_t("lab.rr_auto"))
        self._rr_auto.setToolTip(_t("lab.rr_auto_tipp"))
        self._rr_auto.stateChanged.connect(lambda *_: self._terv_valtozott())
        s2.addWidget(self._rr_auto)

        self._rajz_kozos = QtWidgets.QCheckBox(_t("lab.rajz_kozos"))
        self._rajz_kozos.setToolTip(_t("lab.rajz_kozos_tipp"))
        self._rajz_kozos.stateChanged.connect(self._rajz_megoszt_valt)
        s2.addWidget(self._rajz_kozos)
        for cimke, fn in ((_t("lab.torol"), self.torol),
                          (_t("lab.rajz_torol"), self.rajz_torol_mind),
                          (_t("lab.json_mentes"), self.ment),
                          (_t("lab.json_megnyit"), self.megnyit)):
            g = QtWidgets.QPushButton(cimke)
            g.clicked.connect(fn)
            s2.addWidget(g)
        s2.addStretch(1)

        # 3. sor: lejátszó
        s3 = QtWidgets.QHBoxLayout(self._sor_lejatszo)
        s3.setContentsMargins(2, 2, 2, 2)
        fo.addWidget(self._sor_lejatszo)
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
        # ⚠ GÖRGETÉS: a kurzor a helyén marad, a CHART mozog alatta. Enélkül a
        # lejátszás kifut a képből, és kézzel kell utána húzni.
        # ⚠ ÁLLAPOT-SÁV (2026-09-10, felhasználói jelzés: „nem tudom, hogy ez
        # az alsó táblázat mit takar… pláne nem minden chartra", majd: „ha
        # nincs stratégia kiválasztva, nem kell").
        #
        # A zavaró rész NEM a csík volt, hanem hogy ÜRESEN IS LÁTSZOTT:
        # stratégia nélkül nincs miből állapotot számolni, mégis helyet vitt és
        # nem mondta meg, mi lenne benne. Ezért a helyes alapállapot ADAT-
        # VEZÉRELT: van mit mutatni → látszik, nincs → eltűnik. A jelölő ezen
        # felül kézzel is kikapcsolhatóvá teszi (a munkaterületen a második
        # charttól alapból ki — ott háromszor vinné a helyet).
        self._kp = QtWidgets.QCheckBox(_t("lab.kp"))
        self._kp.setToolTip(_t("lab.kp_tipp"))
        self._kp.stateChanged.connect(self._kp_valt)
        s3.addWidget(self._kp)
        self._kp_pct = QtWidgets.QSpinBox()
        self._kp_pct.setRange(1, 100)
        self._kp_pct.setValue(100)
        self._kp_pct.setSuffix("%")
        # ⚠ A SZÁM IS LÁTSZÓDJON. 64 px-en a „100%" alá szorult a két nyíl
        # mellett, és csak a nyilak látszottak — egy mező, aminek az ÉRTÉKE nem
        # olvasható, nem vezérlő, csak dísz.
        self._kp_pct.setFixedWidth(92)
        self._kp_pct.setToolTip(_t("lab.kp_pct_tipp"))
        self._kp_pct.valueChanged.connect(self._kp_pct_valt)
        s3.addWidget(self._kp_pct)
        # ⚠ A SZÁMLAGÖRBE SORA is eltüntethető (felhasználói jelzés: az üres
        # panel a 0,2–0,8 tengelyével helyet vitt, és nem mondta meg, mi lenne
        # benne). Ugyanaz az elv, mint a sávoknál: ADAT-VEZÉRELT — forgatókönyv
        # (és így eredmény) nélkül nincs mit rajzolni, tehát el is tűnik.
        self._egyenleg_kapcs = QtWidgets.QCheckBox(_t("lab.egyenleg"))
        self._egyenleg_kapcs.setToolTip(_t("lab.egyenleg_tipp"))
        self._egyenleg_kapcs.setChecked(True)
        self._egyenleg_kapcs.stateChanged.connect(
            lambda *_: self._egyenleg_lathatosag())
        s3.addWidget(self._egyenleg_kapcs)
        self._savok = QtWidgets.QCheckBox(_t("lab.savok"))
        self._savok.setToolTip(_t("lab.savok_tipp"))
        self._savok.setChecked(True)
        self._savok.stateChanged.connect(lambda *_: self._sav_rajz())
        s3.addWidget(self._savok)
        self._autofit = QtWidgets.QCheckBox(_t("lab.autofit"))
        self._autofit.setToolTip(_t("lab.autofit_tipp"))
        self._autofit.stateChanged.connect(self._autofit_valt)
        s3.addWidget(self._autofit)
        self._gorget = QtWidgets.QCheckBox(_t("lab.gorgetes"))
        self._gorget.setToolTip(_t("lab.gorgetes_tipp"))
        self._gorget.stateChanged.connect(self._gorgetes_valt)
        s3.addWidget(self._gorget)
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
        self._plot = pg.PlotWidget(axisItems={"bottom": self._x_tengely},
                                   viewBox=Nezet())
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._vb = self._plot.getViewBox()
        self._plot.scene().sigMouseClicked.connect(self._kattintas)
        self._vp_figyelt = self._plot.viewport()
        self._vp_figyelt.installEventFilter(self)
        self._kep_utan_fn = None
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
        self._kurzor_vonal.setZValue(56)      # a takaró fölött (a baron BELÜL jár)
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
        # ⚠ TELJESEN ÁTLÁTSZATLAN (2026-09-10, felhasználói kérés: „lehessen
        # teljesen láthatatlanná tenni"). Eddig 235/255 alfával a jövő gyertyái
        # halványan ÁTÜTÖTTEK — lejátszás közben pont azt árulták el, aminek
        # rejtve kellene maradnia. Az ÜRES TERÜLET megmarad: a pozíció-nyitáshoz
        # kell, csak nem látszik benne a jövő.
        self._takaro = pg.LinearRegionItem(
            orientation="vertical", movable=False,
            brush=pg.mkBrush(16, 20, 24, 255))
        self._takaro.setZValue(50)
        self._takaro.setVisible(False)
        self._plot.addItem(self._takaro, ignoreBounds=True)
        self._ido_cimke = pg.TextItem(anchor=(1, 1), color=szin("yellow"))
        self._ido_cimke.setZValue(60)
        self._plot.addItem(self._ido_cimke, ignoreBounds=True)
        # ── A görgetés POZICIONÁLÓ háromszöge (a chart tetején) ─────────
        self._gorget_jelolo = pg.InfiniteLine(
            angle=90, movable=True,
            pen=pg.mkPen(szin("gray"), width=1, style=QtCore.Qt.DashLine),
            hoverPen=pg.mkPen(szin("yellow"), width=2))
        self._gorget_jelolo.addMarker("v", position=1.0, size=14)
        self._gorget_jelolo.setZValue(55)
        self._gorget_jelolo.setVisible(False)
        self._gorget_jelolo.sigPositionChanged.connect(self._jelolo_huzva)
        self._plot.addItem(self._gorget_jelolo, ignoreBounds=True)
        self._autofit_alatt = False
        self._vb.sigRangeChanged.connect(lambda *_: self._cimke_helyre())
        self._vb.sigRangeChanged.connect(lambda *_: self._jelolo_helyre())
        self._vb.sigRangeChanged.connect(
            lambda _vb=None, _r=None, _v=None: self._autofit_korlat(_v))
        # ⚠ AZ ABLAK ÁTMÉRETEZÉSE IS ILLESZTÉS. Az AutoFit eddig csak lejátszás
        # közben és bekapcsoláskor futott; a felhasználó nagyobbra húzta a
        # chartot, és a gyertyák a képernyő közepén maradtak összenyomva.
        self._vb.sigResized.connect(lambda *_: self._autofit_illeszt())
        # ⚠ GÖRGETÉS-MÓDBAN A HÚZÁS = TEKERÉS. A play-vonal a képen egy fix
        # helyen áll (a háromszögnél); ha a chartot elhúzod alatta, más gyertya
        # kerül a vonal alá — tehát a kurzor odalép. Így a felület megfogásával
        # előre-hátra lehet tekerni. Nagyításkor (görgő) viszont a kurzor
        # marad, és a nézet igazodik hozzá.
        self._tekeres_alatt = False
        self._vb.sigHuzva.connect(self._gorget_tekeres)
        self._vb.sigRangeChangedManually.connect(
            lambda *_: self._gorget_nagyitas_utan())

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
        self._formalodo = Formalodo()
        # ⚠ A TAKARÓ (z=50) FÖLÉ. A formálódó gyertya z=45-tel a „csak eddig
        # látszik" takaró ALATT ült — tehát pont akkor nem látszott, amikor a
        # takaró be volt kapcsolva. A felhasználó: „a gyertya kialakulását
        # továbbra sem látom… így nincs értelme az egész kontrollpontnak". A
        # teszt `isVisible()`-t kérdezett, ami a takaró alatt is igaz — üres
        # állítás volt (lásd `vacuous-parity-tests`); most a z-sorrendet is őrzi.
        self._formalodo.setZValue(52)
        self._formalodo.setVisible(False)
        self._plot.addItem(self._formalodo, ignoreBounds=True)
        self._elemek.append(self._formalodo)
        self._kp_pontok = self._kp_bar = None
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
        self._cim_frissit()
        # ⚠ A `_kurzor_rajz` KORAI VISSZATÉRÉSE miatt itt is kell: kurzor
        # nélkül (friss betöltés) az oda tett hívás nem futna le, és az üres
        # számlagörbe-sor ott maradna — épp az, ami zavaró volt.
        self._egyenleg_lathatosag()

    def cim(self) -> str:
        """A chart neve: `PÁR · IDŐSÍK`."""
        _tf = dict(IDOSIKOK).get(int(self._tf.currentData() or 0),
                                 self._tf.currentText())
        return f"{self._sym.currentText()} · {_tf}"

    def _cim_frissit(self) -> None:
        """A befoglaló al-ablak felirata a BETÖLTÉS UTÁN.

        ⚠ EDDIG CSAK MEGNYITÁSKOR ÁLLT BE. Ha a felhasználó átváltotta az
        idősíkot vagy az instrumentumot, a cím a RÉGIT mutatta — három
        kapcsolt ablaknál (M1+M5+M15) épp az a felirat hazudott, amiből meg
        lehetne különböztetni őket."""
        _sw = self.parent()
        if isinstance(_sw, QtWidgets.QMdiSubWindow):
            _sw.setWindowTitle(self.cim())
        else:
            from version import APP_NAME
            self.setWindowTitle(f"{APP_NAME} — {self.cim()}")
        _mt = getattr(self, "_munkaterulet", None)
        if _mt is not None:
            _mt.cim_valtozott(self)

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
        # ⚠ A JELÖLŐ AZ ELSŐDLEGES: ha ki van kapcsolva, a csík EL IS TŰNIK —
        # nem csak üresen ott marad. (A képernyőn épp az üres, de látható csík
        # volt zavaró: helyet vitt, és nem mondta meg, mi lenne benne.)
        allapotok = [o for o in self._objs if isinstance(o, viz.BarState)]
        _kell = bool(allapotok) and getattr(self, "_savok", None) is not None             and self._savok.isChecked()
        self._sav.setVisible(_kell)
        if not _kell:
            self._sav.clear()
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
        # ⚠ GYORSÍTÓTÁR: a `get_indexer(method="nearest")` 1,4 ms, és lejátszás
        # közben ablakonként-képenként többször hívódik (sáv, doboz, nyitott
        # vonalak). Az eredmény a charthoz és az időhöz kötött, tehát a kulcs
        # a kettő azonossága; a chart újratöltésével a kulcs magától elévül.
        _k = (id(self._chart), ido)
        _c = self.__dict__.setdefault("_be_ar_tar", {})
        if _k in _c:
            return _c[_k]
        try:
            poz = self._chart.index.get_indexer([ido], method="nearest")
            _ar = float(self._chart["close"].iloc[int(poz[0])])
        except (IndexError, ValueError, KeyError):
            return None
        if len(_c) > 512:
            _c.clear()
        _c[_k] = _ar
        return _ar

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
        # ⚠ MINDEN korábbi elemet takarítunk, NEM csak a MOST meglévő belépőkét.
        # A régi alak a `self._belepok`-on ment végig — egy KIVETT belépő elemei
        # így sosem kerültek le a chartról: árva vonalak és sávok maradtak rajta,
        # amiket semmi nem tudott már megfogni. Megosztott tervnél ez azonnal
        # látszott is: a MÁSIK ablakból törölt belépő nyoma ittmaradt. (A teszt
        # fogta meg — a listát ott ürítettük, és az elem mégis megvolt.)
        for _it in list(self._be_elem.values()):
            if _it is not None:
                try:
                    self._plot.removeItem(_it)
                except Exception:
                    pass
        self._be_elem.clear()
        if self._tengely is None:
            return
        for b in self._belepok:
            x = self._tengely.hol(int(b.ido.timestamp()))
            if x is None:
                continue
            _sz = szin("lime" if b.irany == "BUY" else "magenta")
            _vonal = pg.InfiniteLine(
                pos=x, angle=90, movable=True, pen=pg.mkPen(_sz, width=2),
                hoverPen=pg.mkPen(_sz, width=4),
                label=(b.irany + (" ●" if b.nyitva else "")),
                labelOpts={"position": 0.97, "color": _sz})
            _vonal.sigPositionChanged.connect(
                lambda _l=None, _b=b: self._belepo_mozgott(_b))
            self._bel_set(b, "vonal", _vonal)
            self._plot.addItem(_vonal)
            if b.sl is None:
                continue
            _be = self._be_ar(b.ido)
            if _be is None:
                continue
            # ⚠ CSAK A KIVÁLASZTOTT belépő SL/TP-je HÚZHATÓ és teljes szélességű.
            # Több belépőnél N pár vízszintes vonal olvashatatlan lenne; a
            # kiválasztás (kattintás a belépő-vonalra) tartja tisztán a képet.
            _akt = (b is self._valasztott) or (len(self._belepok) == 1)
            # ⚠ A VONAL A POZÍCIÓ ÉLETTARTAMÁRA ÉR (mint a sáv): a belépőtől a
            # zárásig / a kurzorig. Végtelen vonalnál a lezárt pozíció stopja
            # is a képen maradt — lásd `Szakasz`.
            _x2 = self._sav_vege(b, x)
            _slv = Szakasz(
                x, _x2, pos=b.sl, angle=0, movable=_akt,
                pen=pg.mkPen(szin("red"), width=2 if _akt else 1),
                hoverPen=pg.mkPen("#ff7777", width=3),
                label="SL {value:0.2f}",
                labelOpts={"position": 0.9, "color": szin("red")})
            _tpv = Szakasz(
                x, _x2, pos=b.tp_ar(_be), angle=0, movable=_akt,
                pen=pg.mkPen(szin("green"), width=2 if _akt else 1),
                hoverPen=pg.mkPen("#77ff77", width=3),
                label=f"TP {b.rr:0.2f}R",
                labelOpts={"position": 0.9, "color": szin("green")})
            self._bel_set(b, "sl_vonal", _slv)
            self._bel_set(b, "tp_vonal", _tpv)
            _slv.sigPositionChanged.connect(
                lambda _l=None, _b=b: self._sl_mozgott(_b))
            _tpv.sigPositionChanged.connect(
                lambda _l=None, _b=b: self._tp_mozgott(_b))
            # ⚠ A SÁV CSAK A POZÍCIÓ ÉLETTARTAMÁRA. Korábban `LinearRegionItem`
            # volt, ami KONSTRUKCIÓ SZERINT végigér a képen — így a sáv olyan
            # gyertyákra is ráfeküdt, ahol a pozíció már/még nem élt, és nem
            # lehetett ránézésre megmondani, meddig tartott a kötés.
            # ⚠ A VONALAK MINDENHOL, A DOBOZ CSAK AZ AKTÍV ABLAKBAN
            # (felhasználói döntés). Egy belépő három ablakban látszik, de három
            # nagy színes kockázat/cél-sáv elnyomná a chartokat; a vonalak
            # viszont vékonyak, és épp azok mondják meg, HOL van a belépő, az SL
            # és a TP. Így minden idősíkon látod a pozíciót, de csak ott
            # „dolgozol" vele, ahol épp nézed.
            for it in (_slv, _tpv):
                self._plot.addItem(it)
            if not self.aktiv_e():
                continue
            _kock = _Savdoboz(x, min(_be, b.sl), _x2, max(_be, b.sl),
                              pg.mkBrush(220, 0, 0, 38))
            _cel = _Savdoboz(x, min(_be, b.tp_ar(_be)), _x2,
                             max(_be, b.tp_ar(_be)),
                             pg.mkBrush(0, 170, 0, 38))
            self._bel_set(b, "kock", _kock)
            self._bel_set(b, "cel", _cel)
            for it in (_kock, _cel):
                it.setZValue(-20)
                self._plot.addItem(it)
            self._doboz_rajz(b, x, _x2, _be)
            if _akt:
                self._trail_vonalak(b, _be)
        self._be_jelolo_rajz()

    # ══ A POZÍCIÓ-DOBOZ (TradingView-szerű) ══════════════════════════════
    #
    # ⚠ A TERV NEM POZÍCIÓ, AMÍG MEG NEM NYITOD. A doboz kirakása még csak
    # szándék; a KÖZÉPSŐ gombra kattintva válik megnyitottá. Utána is
    # SZERKESZTHETŐ marad (kifejezett felhasználói kérés) — így az SL BE-be
    # húzása egyetlen mozdulat, és a doboz utólag is szűkíthető.
    #
    # ⚠ AMI SZÁNDÉKOSAN NINCS BENNE: a PÉNZ-érték (lot, kockázat devizában).
    # A méretezés a `core/risk_manager`-é; ha itt is kiszámolnám, két méretező
    # út lenne — a projekt visszatérő kárforrása —, és a naiv képlet ráadásul
    # HAZUDNA is, mert a `min_lot` és a slot-keret felülírja (lásd a
    # „min_lot túlkockázat" leletet). A doboz ezért ÁRAT, TÁVOLSÁGOT (pontban
    # és %-ban) és R:R-t mutat: ezek a belépőből és a stopból egyértelműen
    # adódnak, nem kell hozzá számla-modell.

    DOBOZ_GOMB_X = 0.5          # a gomb helye a dobozon belül (0..1)

    def _doboz_cimke(self, szoveg: str, hatter: str, horgony) -> "pg.TextItem":
        _c = pg.TextItem(szoveg, color="#ffffff", anchor=horgony,
                         fill=pg.mkBrush(hatter), border=pg.mkPen("#000000"))
        _c.setZValue(70)
        return _c

    def _doboz_szoveg(self, b: "Belepo", be_ar: float) -> tuple:
        """A három felirat szövege: `(cél, stop, közép)`.

        ⚠ MINDIG A MODELLBŐL SZÁMOL, nem tárolt számból: a felhasználó kérése
        az volt, hogy „folyamatosan számolja az értéket". Egy eltett érték az
        első húzásnál elavulna."""
        _ps = float(((self.cfg.get("pairs") or {})
                     .get(self._sym.currentText()) or {}).get("point_size") or 0.0)
        _tp = b.tp_ar(be_ar)

        def _tav(ar):
            _d = abs(ar - be_ar)
            _pont = (_t("lab.doboz.pont", n=int(round(_d / _ps)))
                     if _ps > 0 else "")
            _szaz = ("%.3f" % (_d / be_ar * 100.0)) if be_ar else "-"
            return _szaz, _pont

        _szt, _pt_t = _tav(_tp)
        _szs, _pt_s = _tav(b.sl)
        _dt, _ds = abs(_tp - be_ar), abs(b.sl - be_ar)
        _rr = ("%.2f" % (_dt / _ds)) if _ds > 0 else "-"
        return (_t("lab.doboz.cel", ar=self._ar(_tp), szaz=_szt, pont=_pt_t),
                _t("lab.doboz.stop", ar=self._ar(b.sl), szaz=_szs, pont=_pt_s),
                "%s   %s   R:R %s" % (
                    _t("lab.doboz.nyitva" if b.nyitva else "lab.doboz.nyit"),
                    b.irany, _rr))

    def _doboz_rajz(self, b: "Belepo", x1: float, x2: float,
                    be_ar: float) -> None:
        """A doboz fogója és feliratai. CSAK az aktív ablakban hívjuk."""
        _cel_sz, _stop_sz, _kozep_sz = self._doboz_szoveg(b, be_ar)

        # ── A JOBB OLDALI FOGÓ: CSAK a szélesség ─────────────────────────
        # ⚠ Se árat, se belépő-időt nem mozgat — a pozíció VÉGÉT állítja. Ezért
        # nem sarok-pont, hanem függőleges vonal: egy sarokfogóról a felhasználó
        # joggal várná, hogy az árat is vigye.
        # ⚠ CSAK A DOBOZ MAGASSÁGÁBAN. Teljes képmagasságú vonalként a jobb
        # szél egy újabb csík volt a képen („kezd túl sok vonal lenni").
        _tp = b.tp_ar(be_ar)
        _szel = Szakasz(
            min(b.sl, _tp), max(b.sl, _tp),
            pos=x2, angle=90, movable=True,
            pen=pg.mkPen("#8aa0b8", width=1, style=QtCore.Qt.DashLine),
            hoverPen=pg.mkPen(szin("yellow"), width=3))
        _szel.addMarker("o", position=0.5, size=10)
        _szel.setZValue(58)
        _szel.sigPositionChanged.connect(
            lambda _l=None, _b=b: self._doboz_szelesseg(_b))
        self._bel_set(b, "szel", _szel)
        self._plot.addItem(_szel, ignoreBounds=True)

        _ct = self._doboz_cimke(_cel_sz, "#1b7f5a", (0.0, 1.0))
        _ct.setPos(x1, b.tp_ar(be_ar))
        _cs = self._doboz_cimke(_stop_sz, "#a03030", (0.0, 0.0))
        _cs.setPos(x1, b.sl)
        _ck = self._doboz_cimke(_kozep_sz,
                                "#2d6a4f" if b.nyitva else "#334a63", (0.5, 0.5))
        _ck.setPos(x1 + (x2 - x1) * self.DOBOZ_GOMB_X, be_ar)
        for _nev, _el in (("cimke_tp", _ct), ("cimke_sl", _cs),
                          ("cimke_kozep", _ck)):
            self._bel_set(b, _nev, _el)
            self._plot.addItem(_el, ignoreBounds=True)

    def _doboz_igazit(self, b: "Belepo", be_ar: float) -> None:
        """A feliratok újraszámolása húzás közben — ÚJRAÉPÍTÉS NÉLKÜL.

        ⚠ HÚZÁS KÖZBEN SOHA NEM ÉPÍTÜNK ÚJRA. A `_belepok_rajz` eldobná azt a
        Qt-elemet, amit a felhasználó épp fog — a húzás ettől megszakad, és a
        felület elszállhat a kézben maradt elemen. Ugyanezért hív minden
        húzás-kezelő `_terv_valtozott(rajzol=False)`-t."""
        _ct = self._bel(b, "cimke_tp")
        _cs = self._bel(b, "cimke_sl")
        _ck = self._bel(b, "cimke_kozep")
        if _ct is None or _cs is None or _ck is None or self._tengely is None:
            return
        x1 = self._tengely.hol(int(b.ido.timestamp()))
        if x1 is None:
            return
        x2 = self._sav_vege(b, x1)
        _cel_sz, _stop_sz, _kozep_sz = self._doboz_szoveg(b, be_ar)
        _ct.setText(_cel_sz)
        _ct.setPos(x1, b.tp_ar(be_ar))
        _cs.setText(_stop_sz)
        _cs.setPos(x1, b.sl)
        _ck.setText(_kozep_sz)
        _ck.setPos(x1 + (x2 - x1) * self.DOBOZ_GOMB_X, be_ar)

    def _doboz_szelesseg(self, b: "Belepo") -> None:
        """A jobb oldali fogót elhúzták → a pozíció VÉGE (időben)."""
        _el = self._bel(b, "szel")
        if _el is None:
            return
        _ido = self._ido_x(float(_el.value()))
        if _ido is None or _ido <= b.ido:
            return                      # a vég sosem előzheti meg a belépőt
        b.veg = _ido
        _x2 = float(_el.value())
        for _m in ("kock", "cel"):
            _sav = self._bel(b, _m)
            if _sav is not None:
                _sav.vege(_x2)
        _x1 = self._tengely.hol(int(b.ido.timestamp())) if self._tengely else None
        if _x1 is not None:
            for _m in ("sl_vonal", "tp_vonal"):
                _v = self._bel(b, _m)
                if isinstance(_v, Szakasz):
                    _v.hatar(_x1, _x2)
        _be = self._be_ar(b.ido)
        if _be is not None:
            self._doboz_igazit(b, _be)
        self._terv_valtozott(rajzol=False)

    def _doboz_gomb_talalat(self, p) -> "Belepo | None":
        """A kattintás a doboz KÖZÉPSŐ gombjára esett? Melyik belépőére?

        ⚠ A pyqtgraph `TextItem` nem ad kattintás-jelzést, ezért a gombot a
        jelenet-kattintásból találjuk el. A legkésőbb rajzolt (legfelső) elem
        nyerjen, ezért megyünk visszafelé a listán."""
        for b in reversed(self._belepok):
            _ck = self._bel(b, "cimke_kozep")
            if _ck is None or not _ck.isVisible():
                continue
            try:
                if _ck.mapRectToView(_ck.boundingRect()).contains(p):
                    return b
            except Exception:
                continue
        return None

    def _doboz_megnyit(self, b: "Belepo") -> None:
        """A terv MEGNYITÁSA — vagy a megnyitás visszavonása.

        ⚠ A MEGNYITÁS NEM FAGYASZT BE. Az SL, a TP és a szélesség utána is
        húzható: ezt kérte a felhasználó, „így egyszerűbb lesz az SL-t is BE-be
        húzni". Élesben ez nyilván nem így lenne — a laborban viszont épp az a
        kérdés, hogy MIT csinálnál a már nyitott pozícióval."""
        b.nyitva = not b.nyitva
        self._allapot.setText(_t(
            "lab.doboz.allapot_nyitva" if b.nyitva else "lab.doboz.allapot_terv",
            ir=b.irany, ido=str(b.ido)[:16]))
        self._terv_valtozott()

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
            # ⚠ MÁR NEM HÚZHATÓ (2026-09-09). A vonalak eddig a kézi
            # BE/trailing mezőkbe írtak vissza; azok lekerültek a felületről
            # (hibásan működtek: a modul alapértékéből indultak, tehát a
            # célár-arányos BE-t szimulálták, nem az élesben futó R-alapút).
            # A vonalak MEGMARADNAK, mert hasznosak — de innentől azt MUTATJÁK,
            # amit a pár mentett kockázatcsökkentése tényleg csinálni fog. Egy
            # húzható vonal, ami nem ír sehova, rosszabb volna a hiányánál: úgy
            # néz ki, mint egy működő vezérlő.
            _l = pg.InfiniteLine(
                pos=_ar, angle=0, movable=False,
                pen=pg.mkPen(szin(_szn), width=1, style=QtCore.Qt.DashDotLine),
                label=_cim,
                labelOpts={"position": 0.25, "color": szin(_szn)})
            self._bel_set(b, _nev, _l)
            self._plot.addItem(_l, ignoreBounds=True)

    def _trail_mozgott(self, b: "Belepo", nev: str) -> None:
        """Húzás → vissza az ATR-szorzóba (a mező és a vonal EGY állapot)."""
        _be = self._be_ar(b.ido)
        _atr = self._trail_atr(b)
        if _be is None or _atr <= 0:
            return
        d = 1 if b.irany == "BUY" else -1
        if nev == "trail_be" and self._bel(b, "trail_be") is not None:
            _uj = max(0.0, d * (float(self._bel(b, "trail_be").value()) - _be) / _atr)
            if "trail_activation_atr" in self._rr_mezok:
                self._rr_mezok["trail_activation_atr"].setText(f"{_uj:.2f}")
        elif nev == "trail_tav" and self._bel(b, "trail_tav") is not None:
            _akt = (float(self._bel(b, "trail_be").value()) if self._bel(b, "trail_be") is not None
                    else _be)
            _uj = max(0.0, d * (_akt - float(self._bel(b, "trail_tav").value())) / _atr)
            if "trail_distance_atr" in self._rr_mezok:
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
        # ⚠ A KÉZI VÉG NYER. Ha a felhasználó a jobb oldali fogóval szűkítette
        # a dobozt, azt tiszteljük — nem írja felül sem a kötés zárása, sem a
        # kurzor. Enélkül a következő lejátszó-lépésnél visszanőne, és a fogó
        # használhatatlan volna.
        if b.veg is not None and self._tengely:
            _xv = self._tengely.hol(int(b.veg.timestamp()))
            if _xv is not None:
                return max(x1, _xv)
        _kt = self._kotes_belepohoz(b)
        if _kt is not None and _kt.close_time is not None and self._tengely:
            _x = self._tengely.hol(int(_kt.close_time.timestamp()))
            if _x is not None:
                return max(x1, _x)
        if self._kurzor is not None:
            return max(x1, float(self._kurzor_x()))
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
        """A kurzor pillanatában NYITOTT kötések Entry/SL/TP vonalai.

        ⚠ AZ ELEMEKET ÚJRAHASZNOSÍTJUK, nem építjük újra. A régi alak minden
        képen leszedte és újra létrehozta a vonalakat és címkéket (3 ablak ×
        2 elem × 3 sor = 18 `addItem`/kép) — mérve 1,1 ms/hívás, ami a 16 ms-os
        képkeret hetede, semmiért: a geometria változik, az elem nem. Ugyanaz
        az elv, mint a `_Savdoboz.vege`-nél."""
        _pool = self.__dict__.setdefault("_nyitott_pool", {})
        res = (self._eredmeny or {}).get("res")
        _kell = {}
        if (res is not None and self._tengely is not None
                and self._kurzor is not None and self._chart is not None
                and 0 <= int(self._kurzor) < len(self._chart)):
            _most = self._chart.index[int(self._kurzor)]
            _xm = float(self._kurzor_x())
            for t in (getattr(res, "trades", None) or []):
                if t.open_time is None or t.open_time > _most:
                    continue
                # ⚠ A LEZÁRT pozíció vonalai ELTŰNNEK — ez a lényege: a képen
                # csak az látszik, ami ÉPP ÉL, ahogy a terminálban.
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
                    _kell[(id(t), _cim)] = (x1, _xm, _ar, _sz, _stilus, _cim)
        # Ami már nem kell, le; ami kell, frissítve vagy létrehozva.
        for _k in [k for k in _pool if k not in _kell]:
            for _it in _pool.pop(_k):
                self._plot.removeItem(_it)
        for _k, (x1, _xm, _ar, _sz, _stilus, _cim) in _kell.items():
            _pár = _pool.get(_k)
            if _pár is None:
                _it = pg.PlotDataItem(
                    [x1, _xm], [_ar, _ar],
                    pen=pg.mkPen(szin(_sz), width=2, style=_stilus))
                _c = pg.TextItem(_cim, color=szin(_sz), anchor=(0, 0.5))
                self._plot.addItem(_it)
                self._plot.addItem(_c, ignoreBounds=True)
                _pár = _pool[_k] = (_it, _c)
            else:
                _pár[0].setData([x1, _xm], [_ar, _ar])
            _pár[1].setPos(_xm, _ar)
        self._nyitott_elemek = [it for pár in _pool.values() for it in pár]

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
            if self._bel(b, "trail_be") is None and self._bel(b, "trail_tav") is None:
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
            for it in (self._bel(b, "trail_be"), self._bel(b, "trail_tav")):
                if it is not None:
                    it.setVisible(_mutat)

    def _sav_frissit(self) -> None:
        """A kockázat-/cél-sávok jobb szélének követése a lejátszó kurzorával.
        Futtatás UTÁN a sáv a kötés zárásán áll, azt nem mozgatjuk tovább."""
        if self._tengely is None:
            return
        for b in self._belepok:
            if (self._bel(b, "kock") is None and self._bel(b, "cel") is None
                    and self._bel(b, "sl_vonal") is None):
                continue
            x1 = self._tengely.hol(int(b.ido.timestamp()))
            if x1 is None:
                continue
            _x2 = self._sav_vege(b, x1)
            for it in (self._bel(b, "kock"), self._bel(b, "cel")):
                if it is not None:
                    it.vege(_x2)
            for it in (self._bel(b, "sl_vonal"), self._bel(b, "tp_vonal")):
                if isinstance(it, Szakasz):
                    it.hatar(x1, _x2)
            # ⚠ A DOBOZ IS KÖVESSE. Enélkül a fogó és a gomb a kurzortól
            # elszakadva ott maradna, ahol a rajzoláskor volt — és a gomb egy
            # olyan helyen fogadna kattintást, ahol már nincs doboz.
            _szel = self._bel(b, "szel")
            if _szel is not None:
                _szel.blockSignals(True)
                _szel.setValue(_x2)
                _szel.blockSignals(False)
            _be = self._be_ar(b.ido)
            if _be is not None:
                self._doboz_igazit(b, _be)

    # ── Kézi rajz-elemek ─────────────────────────────────────────────────
    def _rajzok_rajza(self) -> None:
        """A kézi rajzok (újra)építése.

        ⚠ MINDEN ELEM `removable=True` / jobbklikkel törölhető: rajzolni könnyű,
        törölni kell tudni, különben a chart egy kattintás után szemetes marad.
        A ROI `sigRemoveRequested`-je a MODELLBŐL is kiveszi — nem csak a
        képről —, különben mentéskor visszajönne."""
        for _e in self._rajz_elem.values():
            if _e is not None:
                self._plot.removeItem(_e)
        self._rajz_elem.clear()
        if self._tengely is None:
            return
        for r in self._rajzok:
            _sz = szin("yellow")
            _el = None
            if r.fajta == "vizszintes":
                _el = pg.InfiniteLine(
                    pos=float(r.ar1), angle=0, movable=True,
                    pen=pg.mkPen(_sz, width=1),
                    hoverPen=pg.mkPen(_sz, width=3))
            elif r.fajta == "fuggoleges":
                x = self._tengely.hol(int(r.ido1.timestamp()))
                if x is None:
                    continue
                _el = pg.InfiniteLine(
                    pos=x, angle=90, movable=True,
                    pen=pg.mkPen(_sz, width=1),
                    hoverPen=pg.mkPen(_sz, width=3))
            else:
                x1 = self._tengely.hol(int(r.ido1.timestamp()))
                x2 = self._tengely.hol(int(r.ido2.timestamp()))
                if x1 is None or x2 is None:
                    continue
                _el = pg.LineSegmentROI(
                    [[x1, float(r.ar1)], [x2, float(r.ar2)]],
                    pen=pg.mkPen(_sz, width=2), removable=True)
                _el.sigRegionChangeFinished.connect(
                    lambda _x=None, _r=r: self._rajz_mozgott(_r))
                _el.sigRemoveRequested.connect(
                    lambda _x=None, _r=r: self._rajz_torol(_r))
            if _el is None:
                continue
            if r.fajta != "trend":
                _el.sigPositionChanged.connect(
                    lambda _x=None, _r=r: self._rajz_mozgott(_r))
                # ⚠ Az `InfiniteLine`-nak nincs jobbklikk-menüje; a törlést a
                # „Rajz törlése" gomb intézi (lásd `rajz_torol_mind`).
            _el.setZValue(-10)
            self._rajz_elem[id(r)] = _el
            self._plot.addItem(_el)

    # ── A belépő rajz-elemei ABLAKONKÉNT ─────────────────────────────────
    def _bel(self, b, nev: str):
        """A `b` belépő `nev` elemének Qt-objektuma EBBEN az ablakban."""
        return self._be_elem.get((id(b), nev))

    def _bel_set(self, b, nev: str, elem) -> None:
        if elem is None:
            self._be_elem.pop((id(b), nev), None)
        else:
            self._be_elem[(id(b), nev)] = elem

    def aktiv_e(self) -> bool:
        """EZ az ablak az aktív? (Önálló ablak mindig az.)"""
        _mt = getattr(self, "_munkaterulet", None)
        if _mt is None:
            return True
        try:
            return _mt._aktiv_chart() is self
        except Exception:
            return True

    def belepok_ujra(self) -> None:
        """A közös tár kéri: rajzold újra a belépőket (publikus felület)."""
        self._belepok_rajz()

    def rajzok_ujra(self) -> None:
        """A közös tár kéri: rajzold újra a rajzokat (publikus felület)."""
        self._rajzok_rajza()

    def _rajz_valtozott(self) -> None:
        """Változás után a TÖBBI megosztott ablak is kövesse."""
        if self._rajz_megosztva:
            rajztar().valtozott(forras=self)

    def _rajz_megoszt_valt(self, *_a) -> None:
        """Be/kilépés a KÖZÖS rajz-készletbe.

        ⚠ BEKAPCSOLÁSKOR A SAJÁT RAJZOK ÁTKÖLTÖZNEK, nem vesznek el: amit eddig
        rajzoltál, azt látni akarod a többi ablakban is. Kikapcsoláskor viszont
        MÁSOLATOT kap az ablak — különben a „különvált" ablak törlése a
        közösből is kivenne, ami pont az ellenkezője a kikapcsolásnak."""
        _tar = rajztar()
        if self._rajz_kozos.isChecked():
            for r in self._rajzok:
                if r not in _tar.lista:
                    _tar.lista.append(r)
            for _b in self._belepok:
                if _b not in _tar.belepok:
                    _tar.belepok.append(_b)
            self._rajzok = _tar.lista
            self._belepok = _tar.belepok
            self._rajz_megosztva = True
            _tar.belep(self)
            _tar.valtozott(forras=None)      # mindenki lássa az újakat
        else:
            _tar.kilep(self)
            self._rajz_megosztva = False
            self._rajzok = list(self._rajzok)     # MÁSOLAT
            self._belepok = list(self._belepok)
        self._rajzok_rajza()
        self._belepok_rajz()

    def _rajz_mozgott(self, r: "Rajz") -> None:
        """Húzás után VISSZAÍRJUK az időt/árat — a modell a mérvadó, nem a kép.
        Enélkül a mentés a lerakás pillanatának koordinátáit őrizné meg."""
        _el = self._rajz_elem.get(id(r))
        if _el is None or self._tengely is None:
            return
        if r.fajta == "vizszintes":
            r.ar1 = float(_el.value())
        elif r.fajta == "fuggoleges":
            _ido = self._ido_x(float(_el.value()))
            if _ido is not None:
                r.ido1 = _ido
        else:
            try:
                _p = _el.getSceneHandlePositions()
                _pk = [_el.mapSceneToParent(h[1]) for h in _p]
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
        # ⚠ A TÖBBI ABLAK IS KÖVESSE: megosztott rajznál az elhúzott vonal
        # ugyanaz az OBJEKTUM, csak máshol kirajzolva.
        self._rajz_valtozott()

    def _rajz_torol(self, r: "Rajz") -> None:
        _el = self._rajz_elem.pop(id(r), None)
        if _el is not None:
            self._plot.removeItem(_el)
        if r in self._rajzok:
            self._rajzok.remove(r)
        self._allapot.setText(_t("lab.rajz.db", n=len(self._rajzok)))
        self._rajz_valtozott()

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
        t = self._ido_x(self._bel(b, "vonal").value())
        if t is None or t == b.ido:
            return
        b.ido = t
        self._terv_valtozott(rajzol=False)
        _be = self._be_ar(t)
        if _be is not None and b.sl is not None:
            self._savok_igazit(b, _be)
            if self._bel(b, "tp_vonal") is not None:
                self._bel(b, "tp_vonal").setValue(b.tp_ar(_be))

    def _savok_igazit(self, b: "Belepo", be_ar: float) -> None:
        """A kockázat- és cél-sáv ÁR-tartományának igazítása a húzás után.

        ⚠ EGY HELYEN, ÉS ELLENŐRZÖTT LÉTEZÉSSEL. A húzás-kezelők a FŐSZÁLON
        futnak: ha egy hiányzó rajz-elemen szállnak el, azzal a felület
        eseményhurka áll meg (a napló `⛔ A főszál elkapatlan kivétellel állt
        le.` sora pontosan ez volt). A modell attól még helyes; a kép a
        következő teljes rajzolásnál úgyis helyreáll."""
        if b.sl is None:
            return
        if self._bel(b, "kock") is not None:
            self._bel(b, "kock").sav(be_ar, b.sl)
        if self._bel(b, "cel") is not None:
            self._bel(b, "cel").sav(be_ar, b.tp_ar(be_ar))
        _szel = self._bel(b, "szel")
        if isinstance(_szel, Szakasz):
            _tp = b.tp_ar(be_ar)
            _szel.hatar(min(b.sl, _tp), max(b.sl, _tp))
        # ⚠ A SZÁM IS KÖVESSE A VONALAT. A doboz értelme, hogy húzás KÖZBEN
        # mutassa, mibe kerül a döntés; egy csak-elengedéskor frissülő felirat
        # pont a hasznos pillanatban hallgatna.
        self._doboz_igazit(b, be_ar)

    def _sl_mozgott(self, b: "Belepo") -> None:
        b.sl = float(self._bel(b, "sl_vonal").value())
        _be = self._be_ar(b.ido)
        if _be is None:
            return
        # ⚠ A TP A STOP FÜGGVÉNYE: húzod a pirosat, mozog a zöld.
        self._bel(b, "tp_vonal").blockSignals(True)
        self._bel(b, "tp_vonal").setValue(b.tp_ar(_be))
        self._bel(b, "tp_vonal").blockSignals(False)
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
        b.rr = max(0.0, d * (float(self._bel(b, "tp_vonal").value()) - _be) / _tav)
        self._bel(b, "tp_vonal").label.setFormat(f"TP {b.rr:0.2f}R")
        self._savok_igazit(b, _be)
        self._terv_valtozott(rajzol=False)

    def _be_mozgott(self) -> None:
        t = self._ido_x(self._be_vonal.value())
        if t is not None:
            self._be_ido = t
            self._terv_valtozott(rajzol=False)

    def _terv_valtozott(self, rajzol: bool = True) -> None:
        # ⚠ A TERV a többi megosztott ablakban is változzon: egy M1-en nyitott
        # pozíciónak az M5-ön és az M15-ön is látszania kell (felhasználói
        # kérés). A `Belepo` időben él, tehát idősík-független.
        if self._rajz_megosztva:
            rajztar().valtozott(forras=self)
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
        if self._chart is None:
            return
        if ev.button() != QtCore.Qt.LeftButton:
            return
        p = self._vb.mapSceneToView(ev.scenePos())
        # ⚠ A DOBOZ KÖZÉPSŐ GOMBJA RAJZ-MÓD NÉLKÜL is működik: nem rajzolni
        # akarunk vele, hanem megnyitni a tervet. Ezért ELŐBB nézzük, mint a
        # módokat — különben BUY-módban a gombra kattintás egy ÚJ belépőt tenne
        # le a régi tetejére.
        _gomb = self._doboz_gomb_talalat(p)
        if _gomb is not None:
            self._doboz_megnyit(_gomb)
            return
        if self._mod is None:
            return
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
        """A forgatókönyv kockázatcsökkentő értékei — a PÁR SAJÁT kalibrációja.

        ⚠ EDDIG A KÉZI MEZŐKBŐL JÖTT, a modul alapértékeivel feltöltve. Ez azt
        jelentette, hogy a labor a CÉLÁR-ARÁNYOS `breakeven_pct`-t szimulálta,
        miközben a motor v3.56.0 óta R-alapú `breakeven_r`-rel fut — a laborban
        látott stop-viselkedés tehát nem is EGYEZHETETT az élessel. (A
        felhasználó jelzése: „teljesen hibásan működik".)

        Most ugyanabból a forrásból dolgozunk, mint a motor és a backteszt: a
        pár mentett kalibrációjából (`core.rr_state`). Amit a mentett
        forgatókönyv EXPLICIT megad, az továbbra is nyer — a `_rr_mezok` azért
        maradt (üresen), hogy a `forgatokonyv_betolt` változatlanul működjön."""
        ki = {}
        for k, e in self._rr_mezok.items():          # mentett forgatókönyvből
            _sz = (e.text() or "").strip().replace(",", ".")
            if not _sz:
                continue
            try:
                ki[k] = float(_sz)
            except ValueError:
                continue
        if ki:
            return ki
        # ⚠ KAPCSOLÓ NÉLKÜL ÜRES — és a futtatás `none` presetet kap, tehát a
        # stop ott marad, ahová a felhasználó tette (lásd `_forgatokonyv`).
        if not self._rr_auto.isChecked():
            return {}
        try:
            from core import rr_state as _rrs
            _rrs.ensure_loaded()
            return dict(_rrs.get_calibration(self._sym.currentText()) or {})
        except Exception as ex:
            log.debug("a pár rr-kalibrációja nem olvasható: %s", ex)
            return {}

    def _rr_preset(self) -> str:
        """A futtatás presetje: `none` = TÉNYLEG semmi; `off` = BE + trailing.

        ⚠ NÉV-CSAPDA (a `core.risk_reduction` is figyelmeztet rá): a `PRESET_OFF`
        értéke `"off"`, de az az AKTÍV alapértelmezés — BE és trailing. A „ki
        (semmi)" a `PRESET_NONE`. A labor eddig `"off"`-fal futott, és ezért
        zárt „magától"."""
        return "off" if self._rr_ertekek() else "none"

    def _forgatokonyv(self) -> dict:
        _f = self._tol.text() or (str(self._chart.index[0])[:16]
                                  if self._chart is not None else "")
        _i = self._ig.text() or (str(self._chart.index[-1])[:16]
                                 if self._chart is not None else "")
        return {
            "symbol": self._sym.currentText(),
            "strategy": self._strat_nev(),
            "from": _f, "to": _i,
            # ⚠ A `nyitva` és a `veg` a LABORÉ, nem a motoré: a
            # `lab_scenario.futtat()` a belépőből csak az időt, az irányt és a
            # szinteket nézi, a többi kulcsot figyelmen kívül hagyja. Mégis ide
            # kerülnek, különben a doboz szűkítése és a megnyitás-jelölés az
            # ablak bezárásakor elveszne — ugyanaz az ok, amiért a rajzok is.
            "entries": [
                {"time": str(b.ido)[:16], "direction": b.irany,
                 **({"sl": float(b.sl), "tp_rr": float(b.rr)}
                    if b.sl is not None else {}),
                 **({"opened": True} if b.nyitva else {}),
                 **({"end": str(b.veg)[:16]} if b.veg is not None else {})}
                for b in sorted(self._belepok, key=lambda e: e.ido)],
            "breakeven_at": (str(self._be_ido)[:16] if self._be_ido else None),
            "rr_preset": self._rr_preset(),
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
            _b.nyitva = bool(e.get("opened"))
            if e.get("end"):
                try:
                    _b.veg = pd.Timestamp(e["end"])
                except (ValueError, TypeError):
                    _b.veg = None
            self._belepok.append(_b)
        if fk.get("breakeven_at"):
            try:
                self._be_ido = pd.Timestamp(fk["breakeven_at"])
            except ValueError:
                pass
        # ⚠ A mentett forgatókönyv rr-értékei: a mezők ma már nincsenek a
        # felületen, de a BETÖLTÉS nem veszhet el — rejtett tárolóba tesszük,
        # és a `_rr_ertekek` onnan olvassa (az EXPLICIT érték nyer a pár
        # kalibrációja fölött).
        for _k, _v in (fk.get("rr") or {}).items():
            if _k not in self._rr_mezok:
                _me = QtWidgets.QLineEdit(self)
                _me.setVisible(False)
                self._rr_mezok[_k] = _me
            self._rr_mezok[_k].setText(str(_v))
        # A mentett preset dönt a kapcsolóról: `none` (vagy hiány) = ki.
        self._rr_auto.blockSignals(True)
        self._rr_auto.setChecked(str(fk.get("rr_preset") or "none") != "none")
        self._rr_auto.blockSignals(False)
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

    # ══ A NÉZET ÁLLAPOTA (az elrendezés-mentéshez) ══════════════════════
    # ⚠ „HA VALAHOGY BEÁLLÍTOTTAM A KÉPERNYŐT, AKKOR AZT MENTSE LE." Az
    # elrendezés (v3.61.0) a chartok HELYÉT és ADATÁT őrizte — a nagyítást, a
    # kapcsolókat, a kurzort és a tervet nem, tehát a felhasználó minden
    # indításnál újra beállította ugyanazt. A nézet IDŐBEN mentődik (nem
    # bar-indexben), mert az index az adat újratöltésével elcsúszhat.

    KAPCSOLOK = ("gorget", "autofit", "kp", "csak_eddig", "bidask", "savok",
                 "egyenleg_kapcs", "rr_auto", "rajz_kozos")

    def nezet_leiro(self) -> dict:
        d = {"kapcsolok": {k: bool(getattr(self, "_" + k).isChecked())
                           for k in self.KAPCSOLOK},
             "kp_pct": int(self._kp_pct.value()),
             "sebesseg": float(self._sebesseg.value()),
             "gorget_arany": float(getattr(self, "_gorget_arany",
                                           self.GORGETES_ALAP))}
        if self._chart is not None and len(self._chart) > 1:
            try:
                (x0, x1), (y0, y1) = self._vb.viewRange()
                _t0, _t1 = self._ido_x(x0), self._ido_x(x1)
                d["nezet"] = {"tol": str(_t0)[:16], "ig": str(_t1)[:16],
                              "x_szel": float(x1 - x0),
                              "y": [float(y0), float(y1)]}
            except Exception as ex:
                log.debug("nézet-leírás hiba: %s", ex)
            _kt = self._kurzor_ido()
            if _kt is not None:
                d["kurzor"] = str(_kt)[:16]
        # A TERV csak akkor a charté, ha nem a közös tárból jön (azt a
        # munkaterület egyszer menti — három másolat három konfliktus volna).
        if not self._rajz_megosztva:
            d["terv"] = self.terv_leiro()
        return d

    def terv_leiro(self) -> dict:
        _fk = self._forgatokonyv()
        return {"entries": _fk.get("entries") or [],
                "drawings": _fk.get("drawings") or [],
                "breakeven_at": _fk.get("breakeven_at")}

    def terv_vissza(self, d: dict) -> None:
        """A terv (belépők + rajzok) visszatöltése a MEGLÉVŐ chartra."""
        _elemek = {"entries": d.get("entries") or [],
                   "drawings": d.get("drawings") or [],
                   "breakeven_at": d.get("breakeven_at")}
        if not (_elemek["entries"] or _elemek["drawings"]):
            return
        for e in _elemek["entries"]:
            try:
                _b = Belepo(pd.Timestamp(e["time"]), e.get("direction", "BUY"),
                            e.get("sl"), float(e.get("tp_rr", 2.0)))
            except (KeyError, ValueError, TypeError):
                continue
            _b.nyitva = bool(e.get("opened"))
            if e.get("end"):
                try:
                    _b.veg = pd.Timestamp(e["end"])
                except (ValueError, TypeError):
                    _b.veg = None
            self._belepok.append(_b)
        for r in _elemek["drawings"]:
            _r = Rajz.szotarbol(r) if isinstance(r, dict) else None
            if _r is not None:
                self._rajzok.append(_r)
        if _elemek["breakeven_at"]:
            try:
                self._be_ido = pd.Timestamp(_elemek["breakeven_at"])
            except (ValueError, TypeError):
                pass
        self._idok_igazit()
        if self._valasztott is None and self._belepok:
            self._valasztott = self._belepok[0]
        self._belepok_rajz()
        self._rajzok_rajza()

    def nezet_vissza(self, d: dict) -> None:
        """A mentett nézet visszaállítása (a chart MÁR be van töltve)."""
        for k, v in (d.get("kapcsolok") or {}).items():
            _w = getattr(self, "_" + k, None)
            if _w is None or k not in self.KAPCSOLOK:
                continue
            if k == "kp" and v and not self._kp_aktiv_lehet():
                continue                    # nincs finomabb adat → nem erőltetjük
            if bool(_w.isChecked()) != bool(v):
                _w.setChecked(bool(v))
        if d.get("kp_pct"):
            self._kp_pct.setValue(int(d["kp_pct"]))
        if d.get("sebesseg"):
            self._sebesseg.setValue(int(float(d["sebesseg"])))
        if d.get("gorget_arany") is not None:
            self._gorget_arany = min(0.95, max(0.05, float(d["gorget_arany"])))
        if d.get("terv"):
            self.terv_vissza(d["terv"])
        if self._chart is None or len(self._chart) < 2:
            return
        if d.get("kurzor"):
            try:
                self._kurzor_vissza(self._ido_zonaba(pd.Timestamp(d["kurzor"])))
                self._kurzor_rajz()
            except Exception as ex:
                log.debug("kurzor-visszaállítás hiba: %s", ex)
        _n = d.get("nezet") or {}
        try:
            _x0 = self._tengely.hol(int(self._ido_zonaba(
                pd.Timestamp(_n["tol"])).timestamp())) if self._tengely else None
            if _x0 is not None:
                _szel = float(_n.get("x_szel") or 0.0)
                if _szel <= 0:
                    _x1 = self._tengely.hol(int(self._ido_zonaba(
                        pd.Timestamp(_n["ig"])).timestamp()))
                    _szel = (_x1 - _x0) if _x1 is not None else 0.0
                if _szel > 0:
                    self._vb.setXRange(_x0, _x0 + _szel, padding=0)
            _y = _n.get("y") or []
            if len(_y) == 2 and float(_y[1]) > float(_y[0]):
                self._vb.setYRange(float(_y[0]), float(_y[1]), padding=0)
        except Exception as ex:
            log.debug("nézet-visszaállítás hiba: %s", ex)
        self._jelolo_helyre()

    def _kp_aktiv_lehet(self) -> bool:
        """Bekapcsolható-e a kontrollpont ezen a charton (van finomabb adat)?"""
        return (int(self._tf.currentData() or 0) > 1
                or tick_van(self._sym.currentText()))

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
        self._egyenleg_lathatosag()
        g = self._szamla_gorbe()
        egyenleg_rajzol(self._egyenleg, self._egyenleg_elemek, g)
        if g is None:
            self._szamla_kiir("")
            return
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
        """A következő lépés ütemezése — a FESTÉS után (lásd `Szinkron._kovetkezo_kep`).

        Az `_ido_zito` itt egyszeri: a kifestett kép után indítjuk újra, így
        a Windows-üzenetsor minden lépés közt kiürül (egér, billentyű, festés)."""
        _seb = max(1.0, float(self._sebesseg.value()))
        self._lepes = max(1, int(round(_seb / MAX_KEP_MP)))
        _koz = max(int(1000 / MAX_KEP_MP), int(1000 * self._lepes / _seb))
        self._utem_koz = _koz
        self._ido_zito.setSingleShot(True)
        self._ido_zito.start(self.UTEM_TARTALEK_MS)          # tartalék
        self._utem_kezdet = _time.perf_counter()
        self.kep_utan(self._utem_kep_kesz)

    UTEM_TARTALEK_MS = 150

    def _utem_kep_kesz(self) -> None:
        if not self._ido_zito.isActive():
            return                              # közben leállították
        _eltelt = (_time.perf_counter() - getattr(self, "_utem_kezdet", 0.0)) * 1000.0
        self._ido_zito.start(int(max(1.0, getattr(self, "_utem_koz", 16) - _eltelt)))

    def _utem(self) -> None:
        if self._chart is None or self._kurzor is None:
            return
        if self._kurzor >= len(self._chart) - 1:
            self._ido_zito.stop()
            self._play.setText("▶ Play")
            return
        # ⚠ ELŐBB A GYERTYÁN BELÜL. Ha a kontrollpontok be vannak kapcsolva, a
        # lépés a bar ÁRÚTJÁN halad; csak ha az elfogyott, megyünk a következő
        # gyertyára. Így látszik, HOGYAN alakult ki a gyertya.
        if self._kp_lep():
            self._kurzor_rajz()
            self._listak_frissit()
            self._utem_indit()
            return
        self._kurzor = min(len(self._chart) - 1,
                           self._kurzor + getattr(self, "_lepes", 1))
        self._kp_idx = 0
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

    def kep_utan(self, fn) -> None:
        """`fn` a chart KÖVETKEZŐ kifestése után fut (egyszer).

        A `viewport` Paint-eseményére kötve (eseményszűrő) — a lejátszó
        ebből tudja, hogy a kép tényleg a képernyőre került, és csak azután
        lép tovább (lásd `Szinkron._kovetkezo_kep`)."""
        self._kep_utan_fn = fn
        self._plot.viewport().update()

    def eventFilter(self, obj, ev):
        if (obj is getattr(self, "_vp_figyelt", None)
                and ev.type() == QtCore.QEvent.Paint):
            _fn = getattr(self, "_kep_utan_fn", None)
            if _fn is not None:
                self._kep_utan_fn = None
                # ⚠ A festés UTÁN, nem közben: a Paint-esemény még csak most
                # kezdődik; egy 0 ms-os időzítő a festés végére teszi a hívást.
                QtCore.QTimer.singleShot(0, _fn)
        return super().eventFilter(obj, ev)

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
            # ⚠ LEJÁTSZÁSNÁL a TARTALMAZÓ gyertya kell (lásd `_kurzor_vissza`).
            self._kurzor_vissza(t, tartalmazo=True)
            # ⚠ A KÖZÖS ÓRA FOLYTONOS IDŐT AD — ezt HASZNÁLJUK IS.
            #
            # Az első változat itt a formálódó gyertyát a végállapotára
            # ugrasztotta („kapcsolt ablakban a bar készen érkezik"), és ezzel
            # a kontrollpontok KAPCSOLT ablakban HALOTTAK voltak — a
            # felhasználó pontosan ezt jelezte: „nem nagyon látom, hogy
            # működne a H1-en vagy az M5-ön".
            #
            # Pedig a szinkron ideje NEM gyertya, hanem folytonos időpont: a
            # bar KEZDETÉTŐL mért eltelt hányadból pontosan megmondható,
            # hányadik kontrollponton járunk. Így mindhárom ablak UGYANAZT A
            # PILLANATOT mutatja, mindegyik a saját felbontásán — az M1 kész
            # gyertyákkal, az M5 negyedig kibontva, a H1 alig elkezdve.
            self._kp_idx = 10 ** 9
            if self._kp_aktiv() and self._kurzor is not None and t is not None:
                _pp = self._kp_bar_pontjai(int(self._kurzor))
                if _pp is not None and len(_pp) > 1:
                    try:
                        _bt = self._chart.index[int(self._kurzor)]
                        _tfp = int(self._tf.currentData() or 1)
                        _h = (t - _bt).total_seconds() / (_tfp * 60.0)
                        self._kp_idx = int(max(0, min(
                            len(_pp) - 1, round(_h * (len(_pp) - 1)))))
                    except Exception as ex:
                        log.debug("kontrollpont-arány hiba: %s", ex)
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
        _bent = [a for a in sz.tagok() if a is not self]
        self._szinkron = sz
        sz.belep(self)
        if _bent:                    # a kontrollpont-beállítás is a bentieké
            try:
                self.kp_beallit(bool(_bent[0]._kp.isChecked()),
                                int(_bent[0]._kp_pct.value()))
            except Exception as ex:
                log.debug("kontrollpont-átvétel hiba: %s", ex)
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
            rajztar().kilep(self)
        finally:
            self._szinkron = None
        if self in _ABLAKOK:
            _ABLAKOK.remove(self)
        super().closeEvent(ev)

    # ── GÖRGETÉS lejátszás közben ────────────────────────────────────────
    GORGETES_ALAP = 0.75          # a kurzor helye a képen, ha nem látszik

    def _gorgetes_valt(self, *_a) -> None:
        """Bekapcsoláskor MEGJEGYEZZÜK, HOL áll most a kurzor a képen.

        ⚠ A felhasználó kérése: „a play vonalat OTT tartja". Egy fix arány
        (mondjuk mindig 75%) bekapcsoláskor ELRÁNTANÁ a képet — a helyes
        viselkedés az, hogy ott marad, ahová a felhasználó tette."""
        _be = self._gorget.isChecked()
        self._jelolo_lathatosag()
        if not _be:
            # ⚠ KIKAPCSOLÁSKOR VISSZA KELL ADNI A KURZORNAK A HELYET. A chart
            # helyesen megáll — de a kurzor a nézet ~75%-ánál ragadt, és pár
            # lépés után KIFUT a képből: a felhasználó azt látja, hogy „nem áll
            # vissza arra, hogy a sáv mozogjon". Ezért a nézetet úgy toljuk,
            # hogy a kurzor a BAL oldalra kerüljön, és legyen hova söpörnie.
            self._kurzor_balra()
            return
        self._gorget_arany = self._kurzor_kepaeranya()
        self._gorgetes_kovet()
        self._jelolo_helyre()

    def _gorget_tekeres(self) -> None:
        """Húzás görgetés-módban → a kurzor arra a gyertyára, ami a jel alá került."""
        if (not self._gorget.isChecked() or self._chart is None
                or self._kurzor is None):
            return
        try:
            (x0, x1), _ = self._vb.viewRange()
        except Exception:
            return
        _szel = x1 - x0
        if not (_szel > 0):
            return
        _a = getattr(self, "_gorget_arany", self.GORGETES_ALAP)
        # A `_kurzor_x` INVERZE: kontrollpontokkal a vonal a [i − 0,5, i + 0,5)
        # baron BELÜL jár → i = ⌊x + 0,5⌋; anélkül a bar JOBB szélén (i + 0,5)
        # → a legközelebbi jobb szél, i = round(x − 0,5).
        _x = x0 + _a * _szel
        _i = int(np.floor(_x + 0.5)) if self._kp_aktiv() else int(round(_x - 0.5))
        _uj = max(0, min(len(self._chart) - 1, _i))
        if _uj == int(self._kurzor):
            return
        # Tekerés közben a lejátszás áll (mint a kurzor kézi húzásánál).
        if self._szinkron is not None and self._szinkron.jatszik():
            self._szinkron.szunet()
        self._ido_zito.stop()
        self._play.setText("▶ Play")
        self._biztos_eredmeny()
        self._kurzor = _uj
        self._kp_idx = 0
        # ⚠ A NÉZETET NEM RÁNTJUK VISSZA: a felhasználó keze van rajta. A
        # `_gorgetes_kovet` a kerek bar-indexre igazítana, ami minden
        # mozdulatnál fél gyertyányit „rángatna".
        self._tekeres_alatt = True
        try:
            self._kurzor_rajz()
        finally:
            self._tekeres_alatt = False
        self._listak_frissit()
        self._kozzetesz()

    def _gorget_nagyitas_utan(self) -> None:
        """Nagyítás (görgő) után a nézet igazodik a kurzorhoz, nem fordítva."""
        if getattr(self._vb, "huzas", False):
            return                      # húzás: azt a `_gorget_tekeres` kezeli
        if self._gorget.isChecked() and not self._tekeres_alatt:
            self._gorgetes_kovet()

    KURZOR_BAL = 0.12            # kikapcsolás után ide kerül a kurzor

    def _kurzor_balra(self) -> None:
        """A nézet eltolása úgy, hogy a kurzor a bal széphez közel kerüljön."""
        if self._kurzor is None or self._chart is None:
            return
        try:
            (x0, x1), _ = self._vb.viewRange()
        except Exception:
            return
        _szel = x1 - x0
        if not (_szel > 0):
            return
        _uj0 = float(self._kurzor) - self.KURZOR_BAL * _szel
        self._vb.setXRange(_uj0, _uj0 + _szel, padding=0)

    # ── A pozicionáló háromszög (görgetés közben) ────────────────────────
    def _jelolo_lathatosag(self) -> None:
        _j = getattr(self, "_gorget_jelolo", None)
        if _j is not None:
            _j.setVisible(bool(self._gorget.isChecked()))

    def _jelolo_helyre(self) -> None:
        """A háromszög oda, ahol a kurzor TARTÓ helye van a képen."""
        _j = getattr(self, "_gorget_jelolo", None)
        if _j is None or not self._gorget.isChecked():
            return
        try:
            (x0, x1), _ = self._vb.viewRange()
        except Exception:
            return
        _a = getattr(self, "_gorget_arany", self.GORGETES_ALAP)
        _j.blockSignals(True)
        _j.setValue(x0 + _a * (x1 - x0))
        _j.blockSignals(False)

    def _jelolo_huzva(self) -> None:
        """A háromszöget elhúzták → ONNANTÓL ott tartja a play-vonalat.

        ⚠ A felhasználó kérése: „jelenjen meg egy lefelé háromszög a chart
        tetején, amivel lehessen pozicionálni a chartot". A háromszög NEM a
        kurzort mozgatja, hanem azt mondja meg, a kép melyik pontján ÁLLJON a
        kurzor, miközben a chart csúszik alatta."""
        _j = getattr(self, "_gorget_jelolo", None)
        if _j is None or not self._gorget.isChecked():
            return
        try:
            (x0, x1), _ = self._vb.viewRange()
        except Exception:
            return
        _szel = x1 - x0
        if not (_szel > 0):
            return
        _a = (float(_j.value()) - x0) / _szel
        self._gorget_arany = min(0.95, max(0.05, _a))
        self._gorgetes_kovet()

    # ── AutoFit: a látható gyertyák FÉRJENEK BELE (magasságban) ──────────
    def _autofit_valt(self, *_a) -> None:
        if self._autofit.isChecked():
            self._autofit_illeszt()

    def _lathato_savhatar(self):
        """A LÁTHATÓ gyertyák ár-burkolója `(alj, csúcs)`, vagy `None`.

        ⚠ „LÁTHATÓ" = AMIT A FELHASZNÁLÓ LÁT. A „csak eddig látszik" takaró
        alatti (a kurzor utáni) gyertyák NEM számítanak: azok miatt az AutoFit
        egy még meg nem történt csúcsra/aljra is méretezett, és a képen látható
        gyertyák a kép közepén összenyomva ültek (felhasználói jelzés:
        „indokolatlanul összerántja a képernyőt"). A kurzor FORMÁLÓDÓ
        gyertyája viszont igen — az látszik."""
        if self._chart is None or not len(self._chart):
            return None
        try:
            (x0, x1), _ = self._vb.viewRange()
        except Exception:
            return None
        i0 = max(0, int(np.floor(x0)))
        i1 = min(len(self._chart), int(np.ceil(x1)) + 1)
        _takart = (self._kurzor is not None and self._csak_eddig.isChecked())
        if _takart:
            # A kurzor gyertyája kontrollpontokkal a formálódó alakjában látszik,
            # anélkül készen — a KÉSZ gyertyát csak az utóbbi esetben számoljuk.
            _utolso_kesz = int(self._kurzor) + (0 if self._kp_aktiv() else 1)
            i1 = min(i1, _utolso_kesz)
        _lo = _hi = None
        if i1 > i0:
            _sz = self._chart.iloc[i0:i1]
            _lo = float(np.nanmin(_sz["low"].to_numpy(dtype=float)))
            _hi = float(np.nanmax(_sz["high"].to_numpy(dtype=float)))
        if _takart and self._kp_aktiv() and i0 <= int(self._kurzor) <= i1 + 1:
            _f = getattr(self, "_formalodo", None)
            _ohlc = getattr(_f, "_ohlc", None) if _f is not None else None
            if _ohlc and x0 <= float(self._kurzor) <= x1:
                _fl, _fh = float(_ohlc[2]), float(_ohlc[1])
                _lo = _fl if _lo is None else min(_lo, _fl)
                _hi = _fh if _hi is None else max(_hi, _fh)
        if _lo is None or _hi is None:
            return None
        if not (np.isfinite(_lo) and np.isfinite(_hi)) or _hi <= _lo:
            return None
        return _lo, _hi

    def _autofit_illeszt(self) -> None:
        """A függőleges nézet a látható gyertyákra — CSAK magasságban."""
        if not self._autofit.isChecked():
            return
        _h = self._lathato_savhatar()
        if _h is None:
            return
        _lo, _hi = _h
        _p = (_hi - _lo) * 0.04
        self._vb.setYRange(_lo - _p, _hi + _p, padding=0)

    def _autofit_korlat(self, valtozott=None) -> None:
        """SZÉTHÚZÁS-korlát: a nézet nem lehet tágabb, mint amit a gyertyák
        kitöltenek — és VÍZSZINTES mozgásnál teljes újraillesztés.

        ⚠ A felhasználó kérése pontosan ez: „összenyomni össze szabad, és akkor
        tartania kellene az összenyomott állapotot, de amikor szét akarom húzni,
        akkor csak addig engedi, amíg minden gyertya látszik". Tehát a
        BENAGYÍTÁS szabad és megmarad; csak a KIZOOMOLÁS ütközik falba.

        ⚠ ÉS HA A CHART KIMEGY A KÉPBŐL: „ha jobb oldalon már kiment a
        képernyőből egy lejtő, akkor újra kellene rajzolnia". A kettő úgy fér
        össze, hogy a VÍZSZINTES változás (görgetés, lejátszás, új gyertyák a
        képen) ÚJRAILLESZT — más gyertyák látszanak, más a burkoló —, a csak
        FÜGGŐLEGES változás (kézi nagyítás) pedig marad, csupán a széthúzást
        fogjuk vissza. A `valtozott` a pyqtgraph `[x, y]` jelzője."""
        if not self._autofit.isChecked() or self._autofit_alatt:
            return
        if valtozott is not None and bool(valtozott[0]):
            self._autofit_alatt = True
            try:
                self._autofit_illeszt()
            finally:
                self._autofit_alatt = False
            return
        _h = self._lathato_savhatar()
        if _h is None:
            return
        _lo, _hi = _h
        _p = (_hi - _lo) * 0.04
        try:
            _, (y0, y1) = self._vb.viewRange()
        except Exception:
            return
        if y0 < _lo - _p or y1 > _hi + _p:
            self._autofit_alatt = True
            try:
                self._vb.setYRange(max(y0, _lo - _p), min(y1, _hi + _p),
                                   padding=0)
            finally:
                self._autofit_alatt = False

    def _kurzor_x(self):
        """A kurzor-VONAL helye bar-koordinátában, vagy `None`.

        ⚠ KONTROLLPONTOKKAL A VONAL A GYERTYÁN BELÜL JÁR: a bar bal szélétől
        (i − 0,5) a jobb széléig (i + 0,5), az árút hányada szerint. Eddig a
        vonal a bar KEZDETÉN azonnal a jobb szélre ugrott — a felirat „05:56"-ot
        mondott, a vonal a 06:00-t mutatta, és a formálódó gyertya „mögötte"
        épült. Kontrollpont nélkül a bar zárt, a vonal a jobb szélen."""
        if self._kurzor is None:
            return None
        i = int(self._kurzor)
        if self._kp_aktiv():
            _p = self._kp_bar_pontjai(i)
            if _p is not None and len(_p) > 1:
                _h = max(0, min(len(_p) - 1, int(self._kp_idx))) / (len(_p) - 1)
                return i - 0.5 + _h
        return i + 0.5

    def _kurzor_kepaeranya(self):
        """A kurzor helye a látható tartományon belül (0..1), vagy az alapérték."""
        if self._kurzor is None:
            return self.GORGETES_ALAP
        try:
            (x0, x1), _ = self._vb.viewRange()
        except Exception:
            return self.GORGETES_ALAP
        if not (x1 > x0):
            return self.GORGETES_ALAP
        # ⚠ A VONAL helye (nem a bar-index): a háromszög és a sárga vonal csak
        # így esik egybe (felhasználói kérés: „a sárga jelzés és a görgetősáv
        # jelzése ugyanazt mutassa").
        a = (float(self._kurzor_x()) - x0) / (x1 - x0)
        return a if 0.02 <= a <= 0.98 else self.GORGETES_ALAP

    def _gorgetes_kovet(self) -> None:
        """A nézet eltolása úgy, hogy a kurzor a megjegyzett arányon maradjon.

        ⚠ CSAK VÍZSZINTESEN és CSAK az X-tartományt tolja el — a SZÉLESSÉGET
        (nagyítást) és az Y-t nem bántja. Enélkül a görgetés visszanagyítana
        minden képen, és a felhasználó nem tudna belezoomolni futás közben."""
        if (not self._gorget.isChecked() or self._kurzor is None
                or getattr(self, "_tekeres_alatt", False)):
            return
        try:
            (x0, x1), _ = self._vb.viewRange()
        except Exception:
            return
        _szel = x1 - x0
        if not (_szel > 0):
            return
        _a = getattr(self, "_gorget_arany", self.GORGETES_ALAP)
        _uj0 = float(self._kurzor_x()) - _a * _szel
        if abs(_uj0 - x0) < 1e-9:
            return
        self._vb.setXRange(_uj0, _uj0 + _szel, padding=0)

    # ── KONTROLLPONTOK ───────────────────────────────────────────────────
    def _finom_barok(self):
        """A finomabb idősík gyertyái (M1) — LUSTÁN, és csak ha tényleg kell.

        ⚠ Egy M1-parquet 50–120 MB; annak, aki nem kapcsolja be a
        kontrollpontokat, semmi köze hozzá. Ezért csak az első bekapcsoláskor
        olvassuk be, és utána a párra megjegyezzük."""
        _sym = self._sym.currentText()
        if self._m1_finom is not None and self._m1_finom[0] == _sym:
            return self._m1_finom[1]
        try:
            from trading import backtest as _bt
            _, _m1 = _bt.load_data(_sym)
        except Exception as ex:
            log.warning("%s — a finom (M1) adat nem olvasható: %s", _sym, ex)
            _m1 = None
        self._m1_finom = (_sym, _m1)
        return _m1

    def _kp_aktiv(self) -> bool:
        """Van-e ÉRTELME kontrollpontnak? M5+ charton az M1-ből, M1-en TICKBŐL."""
        if not self._kp.isChecked() or self._chart is None:
            return False
        if int(self._tf.currentData() or 0) > 1:
            return True
        return tick_van(self._sym.currentText())

    def _kp_valt(self, *_a) -> None:
        if (self._kp.isChecked() and int(self._tf.currentData() or 0) <= 1
                and not tick_van(self._sym.currentText())):
            # ⚠ NEM CSENDBEN. M1-en a finomabb adat a TICK; ha a párhoz nincs
            # tick-tár, azt meg kell mondani — egy némán visszaugró jelölő
            # hibának látszana.
            self._allapot.setText(_t("lab.kp_m1_nincs_tick",
                                     sym=self._sym.currentText()))
            self._kp.blockSignals(True)
            self._kp.setChecked(False)
            self._kp.blockSignals(False)
            return
        self._kp_ujraszamol()
        # ⚠ KAPCSOLT ABLAKOKBAN A KONTROLLPONT KÖZÖS. Az M1-en lejátszva a
        # felhasználó az M15 és a H1 gyertya KIALAKULÁSÁT is látni akarja —
        # ehhez azoknak az ablakoknak is bontaniuk kell, nem csak annak, ahol
        # a jelölőt bekapcsolta. Az idő már közös; a bontás finomsága is az.
        if self._szinkron is not None and not self._kp_szinkron_alatt:
            self._szinkron.kp_allit(self._kp.isChecked(),
                                    int(self._kp_pct.value()), forras=self)

    def kp_beallit(self, be: bool, pct: int) -> None:
        """A szinkron ÁLLÍTJA a kontrollpont-beállításunkat (nem küldjük vissza)."""
        self._kp_szinkron_alatt = True
        try:
            self._kp_pct.blockSignals(True)
            self._kp_pct.setValue(int(pct))
            self._kp_pct.blockSignals(False)
            if bool(self._kp.isChecked()) != bool(be):
                self._kp.setChecked(bool(be))     # → `_kp_valt` (visszaküldés nélkül)
            else:
                self._kp_ujraszamol()
        finally:
            self._kp_szinkron_alatt = False

    def _tick_nap_barok(self, nap):
        """Az adott NAP tickjei — a párra és a napra gyorsítótárazva."""
        _sym = self._sym.currentText()
        _kulcs = (_sym, pd.Timestamp(nap).tz_localize(None).normalize())
        if self._tick_nap is not None and self._tick_nap[0] == _kulcs:
            return self._tick_nap[1]
        _ps = float(((self.cfg.get("pairs") or {}).get(_sym) or {})
                    .get("point_size") or 0.0)
        _df = tick_nap(_sym, nap, _ps) if _ps > 0 else None
        self._tick_nap = (_kulcs, _df)
        return _df

    def _kp_pct_valt(self, *_a) -> None:
        self._kp_ujraszamol()
        if self._szinkron is not None and not self._kp_szinkron_alatt:
            self._szinkron.kp_allit(self._kp.isChecked(),
                                    int(self._kp_pct.value()), forras=self)

    def _kp_ujraszamol(self) -> None:
        """Az aktuális bar kontrollpontjainak eldobása → újraszámolás."""
        self._kp_pontok = self._kp_bar = None
        self._kp_idx = 0
        self._kurzor_rajz()

    def _kp_bar_pontjai(self, i: int):
        """Az `i`-edik chart-gyertya árútja (gyorsítótárazva a barra)."""
        if self._kp_bar == i and self._kp_pontok is not None:
            return self._kp_pontok
        self._kp_bar, self._kp_pontok = i, None
        if self._chart is None:
            return None
        _tf = int(self._tf.currentData() or 1)
        if _tf <= 1:
            # ⚠ M1: TICKBŐL. Ugyanaz a `searchsorted`-elv, mint lent — a napi
            # tick-tömb 800 ezer soros, egy maszk itt is 20 ms-os lenne.
            try:
                _t0 = self._chart.index[i]
                _tk = self._tick_nap_barok(_t0)
                if _tk is None:
                    return None
                _i0 = int(_tk.index.searchsorted(_t0, side="left"))
                _i1 = int(_tk.index.searchsorted(_t0 + pd.Timedelta(minutes=1),
                                                 side="left"))
                _bid = _tk["bid"].to_numpy()[_i0:_i1]
            except Exception as ex:
                log.debug("tick-szeletelés hiba: %s", ex)
                return None
            if len(_bid) < 2:
                return None
            self._kp_pontok = tick_pontok(_bid, float(self._kp_pct.value()))
            return self._kp_pontok
        _m1 = self._finom_barok()
        if _m1 is None:
            return None
        try:
            _t0 = self._chart.index[i]
            _t1 = _t0 + pd.Timedelta(minutes=_tf)
            # ⚠ `searchsorted`, NEM boolean maszk. A maszkos alak
            # (`(idx >= t0) & (idx < t1)`) VÉGIGPÁSZTÁZZA a teljes M1-et és két
            # 3,4 millió elemű tömböt allokál — mérve 20,5 ms MINDEN ÚJ BARON.
            # H1-en (240 kontrollpont/bar) ez volt a „stopra nem áll meg, hanem
            # homokórázik" oka. Rendezett indexen a bináris keresés O(log n).
            _i0 = int(_m1.index.searchsorted(_t0, side="left"))
            _i1 = int(_m1.index.searchsorted(_t1, side="left"))
            _alk = _m1.iloc[_i0:_i1]
        except Exception as ex:
            log.debug("kontrollpont-szeletelés hiba: %s", ex)
            return None
        if len(_alk) < 2:
            return None            # nincs mit finomítani (hézag vagy M1-chart)
        self._kp_pontok = kontroll_pontok(_alk, float(self._kp_pct.value()))
        return self._kp_pontok

    def _kp_lep(self) -> bool:
        """Egy KONTROLLPONTNYIT lép. `True`, ha maradt a baron belül."""
        if not self._kp_aktiv() or self._kurzor is None:
            return False
        _p = self._kp_bar_pontjai(int(self._kurzor))
        if _p is None or len(_p) == 0:
            return False
        if self._kp_idx + 1 < len(_p):
            self._kp_idx += 1
            return True
        return False               # a bar kész → jöhet a következő

    def _formalodo_rajz(self) -> None:
        """A kibontakozó gyertya kirajzolása (vagy elrejtése)."""
        _f = getattr(self, "_formalodo", None)
        if _f is None:
            return
        if not self._kp_aktiv() or self._kurzor is None:
            _f.setVisible(False)
            return
        _p = self._kp_bar_pontjai(int(self._kurzor))
        _oh = reszgyertya(_p, self._kp_idx) if _p is not None else None
        if _oh is None:
            _f.setVisible(False)
            return
        _f.allit(float(self._kurzor), _oh)
        _f.setVisible(True)

    def _egyenleg_lathatosag(self) -> None:
        """A számlagörbe sora: csak ha KÉRIK és van is mit mutatni."""
        _e = getattr(self, "_egyenleg", None)
        if _e is None:
            return
        _van = bool((self._eredmeny or {}).get("res"))
        _e.setVisible(bool(self._egyenleg_kapcs.isChecked()) and _van)

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

    def _kurzor_vissza(self, t, tartalmazo: bool = False) -> None:
        """Idősík-váltás után a kurzor UGYANARRA az időre. ⚠ Bar-indexben
        őrizve M15→M1 tizenötszörös ugrás lenne.

        `tartalmazo=True`: az a gyertya, amelyik az időt TARTALMAZZA (nem a
        legközelebbi).

        ⚠ MIÉRT KELL A KETTŐ. Idősík-váltásnál a LEGKÖZELEBBI a jó: a kurzort
        oda tesszük, ahol a felhasználó szeme járt. LEJÁTSZÁSNÁL viszont a
        TARTALMAZÓ — egy H1 bar felénél a `nearest` már a KÖVETKEZŐ gyertyát
        adja, és a kibontakozó gyertya minden bar felénél visszaugrott a
        nullára. (Mérve: a bar 25%-ánál még 25%, 50%-ánál viszont már 0%.)"""
        if t is None or self._chart is None:
            self._kurzor = None
            return
        if tartalmazo:
            _i = int(self._chart.index.searchsorted(t, side="right")) - 1
            self._kurzor = max(0, min(len(self._chart) - 1, _i))
            return
        poz = self._chart.index.get_indexer([t], method="nearest")
        self._kurzor = int(poz[0]) if len(poz) and poz[0] >= 0 else None

    def _kurzor_rajz(self, vonal: bool = True) -> None:
        self._gorgetes_kovet()
        # ⚠ LEJÁTSZÁS KÖZBEN illesztünk: a felhasználó kérése szerint a Play
        # igazítja a magasságot. Megállított kurzornál a kézi nagyítás szabad
        # (csak a széthúzást korlátozzuk) — különben minden mozdulatot
        # visszarántanánk.
        if self._ido_zito.isActive() or (self._szinkron is not None
                                         and self._szinkron.jatszik()):
            self._autofit_illeszt()
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
            self._kurzor_vonal.setValue(self._kurzor_x())
            self._kurzor_vonal.blockSignals(False)
        sor = self._chart.iloc[i]
        if self._bidask.isChecked():
            bid = float(sor["close"])
            self._bid.setValue(bid)
            self._ask.setValue(bid + float(sor.get("avg_spread", 0.0) or 0.0))
        if self._csak_eddig.isChecked():
            # ⚠ KONTROLLPONTOKNÁL A KURZOR GYERTYÁJÁT IS TAKARJUK: helyette a
            # FORMÁLÓDÓ gyertyát rajzoljuk. Enélkül a kész gyertya látszana a
            # félkész alatt — épp azt árulná el előre, amit meg akarunk mutatni.
            _tol = (i - 0.5) if self._kp_aktiv() else (i + 0.5)
            self._takaro.setRegion((_tol, len(self._chart) + 5))
        self._formalodo_rajz()
        self._egyenleg_lathatosag()
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
SABLON_DIR = ROOT / "data" / "lab_sablonok"


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
            "nezet": w.nezet_leiro(),
        })
    _kozos = None
    _tar = rajztar()
    if _tar.lista or _tar.belepok:
        # ⚠ A KÖZÖS TERV EGYSZER, nem chartonként: a tagok UGYANARRA a listára
        # mutatnak, három másolat visszatöltve háromszor annyi belépő volna.
        for w in (sw.widget() for sw in mt._mdi.subWindowList()):
            if isinstance(w, LabAblak) and w._rajz_megosztva:
                _kozos = w.terv_leiro()
                break
    return {
        "verzio": ELRENDEZES_VERZIO,
        "kozos_terv": _kozos,
        "ablak_geometria": _b64(mt.saveGeometry()),
        "ablak_allapot": _b64(mt.saveState()),
        "tabos": bool(mt._tabos.isChecked()),
        "chartok": chartok,
    }


def elrendezes_ment(mt, csak_ha_valtozott: bool = False) -> bool:
    """Az elrendezés kiírása. `False`, ha nem sikerült (és NAPLÓZ).

    `csak_ha_valtozott`: az időzített mentés nem koptatja a lemezt, ha semmi
    nem változott az előző kiírás óta."""
    try:
        _szoveg = json.dumps(elrendezes_leiro(mt), ensure_ascii=False, indent=2)
        if csak_ha_valtozott and _szoveg == getattr(mt, "_elrendezes_utolso", None):
            return True
        ELRENDEZES_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = ELRENDEZES_PATH.with_suffix(".tmp")
        tmp.write_text(_szoveg, encoding="utf-8")
        tmp.replace(ELRENDEZES_PATH)
        mt._elrendezes_utolso = _szoveg
        log.info("%s: labor-elrendezés mentve (%d chart).", ELRENDEZES_PATH.name,
                 len(mt.chartok()))
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

    def __init__(self, symbol=None, strategy=None, tf_perc=15, tol=None, ig=None,
                 uj: bool = False):
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
        # ⚠ HARMADIK FÜL: a SZÁMLAGÖRBE. A felhasználó: „ez minden idősíkon
        # felesleges… a nyitott, lezárt mellé lehetne tenni. Nem?" — de igen: a
        # görbe is SZÁMLA-szintű, nem chart-szintű. Egy chart egy NÉZET
        # ugyanarra a kísérletre; a számla állapota a kísérleté.
        self._dokk_egyenleg = pg.PlotWidget()
        self._dokk_egyenleg.showGrid(y=True, alpha=0.15)
        self._dokk_egyenleg.hideAxis("bottom")
        self._dokk_egyenleg_elemek = []
        self._dokk_fulek.addTab(self._dokk_egyenleg, _t("lab.egyenleg"))
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

        # ── ESZKÖZ-DOKKOK: betöltő / rajzoló / lejátszó ─────────────────
        # ⚠ EGY BETÖLTŐ SOR, NEM CHARTONKÉNT HÁROM. Minden dokk egy
        # `QStackedWidget`, amiben MINDEN chart saját sora ott van lapként; a
        # chart-váltás csak lapot vált. Így a dokkban MAGA az aktív chart
        # vezérlője ül — nem egy másolat, amit szinkronban kellene tartani. Egy
        # proxy-vezérlő előbb-utóbb elcsúszna attól, amit vezérel; ez a
        # projekt visszatérő kárforrása.
        self._eszkoz_dokkok = {}
        for _kulcs, _cim, _mezo, _terulet in (
                ("betolto", _t("lab.dokk_betolto"), "_sor_betolto",
                 QtCore.Qt.TopDockWidgetArea),
                ("rajz", _t("lab.dokk_rajz"), "_sor_rajz",
                 QtCore.Qt.TopDockWidgetArea),
                ("lejatszo", _t("lab.dokk_lejatszo"), "_sor_lejatszo",
                 QtCore.Qt.BottomDockWidgetArea)):
            _dk = QtWidgets.QDockWidget(_cim, self)
            _dk.setObjectName(f"{_kulcs}_dokk")
            _dk.setAllowedAreas(QtCore.Qt.AllDockWidgetAreas)
            _dk.setFeatures(QtWidgets.QDockWidget.DockWidgetMovable
                            | QtWidgets.QDockWidget.DockWidgetFloatable
                            | QtWidgets.QDockWidget.DockWidgetClosable)
            _st = QtWidgets.QStackedWidget()
            _dk.setWidget(_st)
            self.addDockWidget(_terulet, _dk)
            self._eszkoz_dokkok[_kulcs] = (_dk, _st, _mezo)

        m.addSeparator()
        for _kulcs in ("betolto", "rajz", "lejatszo"):
            m.addAction(self._eszkoz_dokkok[_kulcs][0].toggleViewAction())
        m.addAction(self._szamla_dokk.toggleViewAction())

        m.addSeparator()
        # ⚠ SABLONOK (felhasználói ötlet: „ez lehetne akár valamilyen sablon
        # is"). Ugyanaz a leíró, mint az automatikus mentésé, csak NÉVVEL, a
        # `data/lab_sablonok/` mappában — így egy bevált képernyő (H1 / M15 /
        # M1 egymás alatt, görgetéssel, AutoFittel) egy kattintással
        # visszahozható, és instrumentumonként több is tartható.
        self._tett(m, _t("lab.menu_sablon_ment"), self.sablon_ment)
        self._tett(m, _t("lab.menu_sablon_betolt"), self.sablon_betolt)
        self._tett(m, _t("lab.menu_elrendezes_felejt"), self._elrendezes_felejt)

        # ⚠ A MENTETT ELRENDEZÉS NYER — a parancssor csak akkor, ha kéred.
        # Az első szabály fordítva szólt („a parancssor nyer"): egy
        # `--symbol`/`--from` kapcsolóval indítva a mentett elrendezés NÉMÁN
        # kimaradt, és a felhasználó azt látta, hogy „nem jegyzi meg" (három
        # ablak, görgetés, AutoFit — minden indításnál újra). Aki tiszta lapot
        # akar, azt az `--uj` kapcsolóval kéri; a parancssor egyéb értékei
        # ilyenkor (vagy mentés híján) adják az első chartot.
        _ment = {} if uj else elrendezes_olvas()
        if _ment.get("chartok"):
            self.elrendezes_alkalmaz(_ment)
            log.info("%s: labor-elrendezés visszaállítva (%d chart).",
                     ELRENDEZES_PATH.name, len(self.chartok()))
        else:
            if _ment.get("ablak_geometria"):
                self.restoreGeometry(_qba(_ment["ablak_geometria"]))
            if _ment.get("ablak_allapot"):
                self.restoreState(_qba(_ment["ablak_allapot"]))
            self.uj_chart(symbol=symbol, strategy=strategy, tf_perc=tf_perc,
                          tol=tol, ig=ig)
        # ⚠ IDŐZÍTETT MENTÉS IS, nem csak bezáráskor. Ha a folyamat nem a
        # bezárás-gombbal ér véget (lefagyott ablak, leölt processz, áramszünet),
        # a `closeEvent` nem fut le, és a felhasználó azt látja, hogy „nem jegyzi
        # meg az elrendezést". 20 másodpercenként, és csak ha változott.
        self._elrendezes_zito = QtCore.QTimer(self)
        self._elrendezes_zito.setInterval(20_000)
        self._elrendezes_zito.timeout.connect(
            lambda: elrendezes_ment(self, csak_ha_valtozott=True))
        self._elrendezes_zito.start()
        self._aktiv_valtozott()

    def elrendezes_alkalmaz(self, ment: dict) -> None:
        """Egy elrendezés-leíró ALKALMAZÁSA a meglévő chartok helyére.

        Ugyanaz az út az induláskori visszaállításnak és a sablon
        betöltésének — két külön út előbb-utóbb máshogy állítana vissza."""
        for sw in list(self._mdi.subWindowList()):
            sw.close()
        _tar = rajztar()
        _tar.lista.clear()
        _tar.belepok.clear()
        if ment.get("ablak_geometria"):
            self.restoreGeometry(_qba(ment["ablak_geometria"]))
        if ment.get("ablak_allapot"):
            self.restoreState(_qba(ment["ablak_allapot"]))
        self._chartok_vissza(ment)
        _tabos = bool(ment.get("tabos"))
        if self._tabos.isChecked() != _tabos:
            self._tabos.setChecked(_tabos)
        self._tabos_valt(_tabos)
        self._aktiv_valtozott()

    # ── SABLONOK ─────────────────────────────────────────────────────────
    def sablon_ment(self, ut=None) -> "Path | None":
        """A mostani képernyő NÉVVEL (fájl-párbeszéd, ha nincs út)."""
        SABLON_DIR.mkdir(parents=True, exist_ok=True)
        if ut is None:
            ut, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, _t("lab.sablon_mentese"), str(SABLON_DIR / "sablon.json"),
                "JSON (*.json)")
            if not ut:
                return None
        ut = Path(ut)
        try:
            ut.write_text(json.dumps(elrendezes_leiro(self), ensure_ascii=False,
                                     indent=2), encoding="utf-8")
        except Exception as ex:
            log.warning("A sablon mentése nem sikerült (%s): %s", ut, ex)
            self.statusBar().showMessage(f"HIBA: {ex}", 8000)
            return None
        self.statusBar().showMessage(_t("lab.sablon_mentve", nev=ut.name), 5000)
        return ut

    def sablon_betolt(self, ut=None) -> bool:
        """Egy sablon betöltése a mostani chartok HELYÉRE."""
        if ut is None:
            SABLON_DIR.mkdir(parents=True, exist_ok=True)
            ut, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, _t("lab.sablon_betoltese"), str(SABLON_DIR), "JSON (*.json)")
            if not ut:
                return False
        try:
            d = json.loads(Path(ut).read_text(encoding="utf-8"))
        except Exception as ex:
            log.warning("A sablon nem olvasható (%s): %s", ut, ex)
            self.statusBar().showMessage(f"HIBA: {ex}", 8000)
            return False
        if not isinstance(d, dict) or not d.get("chartok"):
            self.statusBar().showMessage(_t("lab.sablon_ures", nev=Path(ut).name), 8000)
            return False
        self.elrendezes_alkalmaz(d)
        self.statusBar().showMessage(_t("lab.sablon_betoltve", nev=Path(ut).name,
                                        n=len(self.chartok())), 5000)
        return True

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
            try:
                w.nezet_vissza(c.get("nezet") or {})
            except Exception as ex:
                log.warning("A mentett chart-nézet (%s) nem állítható vissza: %s",
                            _sym, ex)
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
        # A KÖZÖS terv: az első megosztott chartba töltjük — a tár közös, tehát
        # a többi megosztott ablak is látja.
        _kozos = ment.get("kozos_terv")
        if _kozos:
            for w in self.chartok():
                if w._rajz_megosztva:
                    try:
                        w.terv_vissza(_kozos)
                        w._terv_valtozott()
                        w._rajz_valtozott()
                    except Exception as ex:
                        log.warning("A mentett közös terv nem tölthető vissza: %s", ex)
                    break

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
        # ⚠ A SZÁMLAGÖRBE a közös dokkba került (harmadik fül) — a chart alatti
        # csík a munkaterületen belül CSAK duplikálná, minden idősíkon.
        w._egyenleg_kapcs.setChecked(False)
        w._egyenleg_kapcs.setVisible(False)
        if _meglevo:
            # A második charttól az állapot-sáv is ki: háromszor vinné a helyet.
            w._savok.setChecked(False)
        # A chart ESZKÖZSORAI a közös dokkokba költöznek (lapként).
        for _dk, _st, _mezo in self._eszkoz_dokkok.values():
            _st.addWidget(getattr(w, _mezo))
        sw = self._mdi.addSubWindow(w)
        sw.setWindowTitle(f"{symbol or '?'} · "
                          f"{dict(IDOSIKOK).get(int(tf_perc), tf_perc)}")
        # A cím a betöltés után a chart SAJÁT állapotából frissül (idősík- és
        # instrumentum-váltás is átírja) — lásd `LabAblak._cim_frissit`.
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
        _g = None
        if chart is not None:
            try:
                _g = chart._szamla_gorbe()
            except Exception:
                _g = None
        # ⚠ CSAK HA MÁS GÖRBE. A `_szamla_gorbe` gyorsítótárazott (ugyanaz az
        # objektum jön vissza képről képre), a rajzoló viszont minden képen
        # leszedte és újrarakta a három elemet — 5 ms/kép, semmiért.
        if _g is getattr(self, "_dokk_egyenleg_utolso", object()):
            return
        self._dokk_egyenleg_utolso = _g
        egyenleg_rajzol(self._dokk_egyenleg, self._dokk_egyenleg_elemek, _g)

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

    def cim_valtozott(self, chart) -> None:
        """Egy chart átnevezte magát (idősík/instrumentum) — ha ő az aktív, a
        közös számla-sor felirata is kövesse."""
        if chart is self._aktiv_chart():
            self._szamla_kiir(chart, chart._szamla.text())

    def _aktiv_valtozott(self, *_a) -> None:
        """Chart-váltás: a közös panel AZONNAL a másik chartét mutassa.

        ⚠ A BELÉPŐ-SÁVOKAT is újra kell rajzolni: a doboz csak az AKTÍV ablakban
        látszik, tehát a váltásnál az EDDIGIRŐL le kell kerülnie, az ÚJON meg
        meg kell jelennie. Csak a két érintett ablakot rajzoljuk újra — minden
        chart újrarajzolása chart-váltásonként fölösleges munka volna.

        ⚠ Nem várhatunk a chart következő frissítésére: az csak akkor jön, ha
        mozdul a kurzora. Addig a panel a RÉGI chart pozícióit mutatná az ÚJ
        chart neve alatt."""
        w = self._aktiv_chart()
        _elozo = getattr(self, "_utolso_aktiv", None)
        if _elozo is not w:
            self._utolso_aktiv = w
            for _ch in (_elozo, w):
                if _ch is None:
                    continue
                try:
                    _ch.belepok_ujra()
                except Exception:
                    pass
        if w is None:
            self._szamla.setText("")
            self._kotesek_kiir(None)
            return
        self._szamla_kiir(w, w._szamla.text())
        self._kotesek_kiir(w)
        self._eszkozok_valt(w)

    def _eszkozok_valt(self, chart) -> None:
        """Az eszköz-dokkok az AKTÍV chart sorait mutassák."""
        for _dk, _st, _mezo in self._eszkoz_dokkok.values():
            _sor = getattr(chart, _mezo, None)
            if _sor is not None and _st.indexOf(_sor) >= 0:
                _st.setCurrentWidget(_sor)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbol")
    ap.add_argument("--strategy")
    ap.add_argument("--tf", type=int, default=15)
    ap.add_argument("--from", dest="tol")
    ap.add_argument("--to", dest="ig")
    ap.add_argument("--egy", action="store_true",
                    help="EGYETLEN chart-ablak, munkaterület nélkül (a régi mód)")
    ap.add_argument("--uj", action="store_true",
                    help="TISZTA LAP: a mentett elrendezés figyelmen kívül hagyva")
    a = ap.parse_args(argv)
    # ⚠ A LABORNAK SAJÁT NAPLÓJA VAN. A dashboard `data/tradeforge.log`-ja egy
    # másik processzé (forgó fájl — két író egyszerre Windowson elakadna); a
    # labor figyelmeztetései eddig csak a konzolra mentek, és egy bezárt
    # ablak után nem lehetett megnézni, mi történt.
    try:
        import logging.handlers as _lh
        _h = _lh.RotatingFileHandler(ROOT / "data" / "lab.log", maxBytes=2_000_000,
                                     backupCount=2, encoding="utf-8")
        _h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s %(name)s: %(message)s",
                                          datefmt="%Y-%m-%d %H:%M:%S"))
        _root = logging.getLogger()
        _root.addHandler(_h)
        if _root.level > logging.INFO or _root.level == logging.NOTSET:
            _root.setLevel(logging.INFO)
    except Exception as _ex:
        log.warning("A labor naplófájlja nem nyitható: %s", _ex)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    if a.egy:
        w = LabAblak(symbol=a.symbol, strategy=a.strategy, tf_perc=a.tf,
                     tol=a.tol, ig=a.ig)
    else:
        w = Munkaterulet(symbol=a.symbol, strategy=a.strategy, tf_perc=a.tf,
                         tol=a.tol, ig=a.ig, uj=a.uj)
    w.show()
    return app.exec()


if __name__ == "__main__":
    _sys.exit(main())

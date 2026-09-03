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
import logging

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from strategy import visual as viz
from tools.lab_chart import (IDOSIKOK, NINCS_STRAT, Idotengely, keszit, szin)

log = logging.getLogger(__name__)

# A lejátszás legsűrűbb képfrissítése (kép/mp). A pyqtgraph-nál ez lényegesen
# magasabb lehet, mint a matplotlibnél volt — a gyertyák nem rajzolódnak újra.
MAX_KEP_MP = 60.0


# ── Gyertyák: EGY rajzolt objektum ────────────────────────────────────────
class Gyertyak(pg.GraphicsObject):
    """⚠ A rajzot EGYSZER „kiégetjük" egy `QPicture`-be; a nagyítás és a
    görgetés utána a megjelenítő dolga. Ez a pyqtgraph mintája, és ez adja a
    fenti sebesség-különbséget."""

    def __init__(self, df):
        super().__init__()
        self._kep = QtGui.QPicture()
        p = QtGui.QPainter(self._kep)
        o = df["open"].to_numpy(float)
        h = df["high"].to_numpy(float)
        l = df["low"].to_numpy(float)
        c = df["close"].to_numpy(float)
        _zp, _pp = pg.mkPen(szin("green")), pg.mkPen(szin("red"))
        _zb, _pb = pg.mkBrush(szin("green")), pg.mkBrush(szin("red"))
        for i in range(len(df)):
            fel = c[i] >= o[i]
            p.setPen(_zp if fel else _pp)
            p.drawLine(QtCore.QPointF(i, l[i]), QtCore.QPointF(i, h[i]))
            p.setBrush(_zb if fel else _pb)
            p.drawRect(QtCore.QRectF(i - 0.32, o[i], 0.64, c[i] - o[i]))
        p.end()

    def paint(self, p, *args):
        p.drawPicture(0, 0, self._kep)

    def boundingRect(self):
        return QtCore.QRectF(self._kep.boundingRect())


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

    def tp_ar(self, be_ar: float) -> float:
        d = 1 if self.irany == "BUY" else -1
        return be_ar + d * abs(be_ar - self.sl) * max(0.0, self.rr)


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
            raise SystemExit("HIBA: a config.json `pairs` blokkja üres.")

        self.setWindowTitle(f"{APP_NAME} {APP_VERSION} — kézi laboratórium")
        self.resize(1500, 950)

        # ── Állapot ──────────────────────────────────────────────────────
        self._chart = None
        self._objs = []
        self._tengely = None
        self._belepok = []
        self._be_ido = None
        self._eredmeny = None
        self._valasztott = None     # a kiválasztott belépő (annak látszik SL/TP)
        self._kurzor = None
        self._elemek = []           # a stratégia rajz-elemei (törléshez)
        self._eredmeny_elemek = []

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
        s1.addWidget(QtWidgets.QLabel("Stratégia"))
        self._strat = QtWidgets.QComboBox()
        s1.addWidget(self._strat)
        s1.addWidget(QtWidgets.QLabel("Idősík"))
        self._tf = QtWidgets.QComboBox()
        for perc, cimke in IDOSIKOK:
            self._tf.addItem(cimke, perc)
        self._tf.setCurrentIndex(max(0, [p for p, _ in IDOSIKOK].index(tf_perc)
                                     if tf_perc in [p for p, _ in IDOSIKOK] else 2))
        self._tf.currentIndexChanged.connect(lambda *_: self.betolt())
        s1.addWidget(self._tf)
        s1.addWidget(QtWidgets.QLabel("-tól"))
        self._tol = QtWidgets.QLineEdit(tol or "")
        self._tol.setFixedWidth(120)
        s1.addWidget(self._tol)
        s1.addWidget(QtWidgets.QLabel("-ig"))
        self._ig = QtWidgets.QLineEdit(ig or "")
        self._ig.setFixedWidth(120)
        s1.addWidget(self._ig)
        _b = QtWidgets.QPushButton("Betölt")
        _b.clicked.connect(self.betolt)
        s1.addWidget(_b)
        s1.addStretch(1)

        # 2. sor: terv-eszközök
        s2 = QtWidgets.QHBoxLayout()
        fo.addLayout(s2)
        s2.addWidget(QtWidgets.QLabel("Kattintás:"))
        self._mod = None
        self._mod_gombok = {}
        for ertek, cimke in (("BUY", "Add BUY"), ("SELL", "Add SELL"),
                             ("BE", "Add BE")):
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
        self._epites = QtWidgets.QCheckBox("Start építés")
        s2.addWidget(self._epites)

        # BE / trailing
        from core import risk_reduction as _rrm0
        _alap = _rrm0.default_config()
        self._rr_mezok = {}
        for _k, _cim in (("breakeven_pct", "BE"),
                         ("trail_activation_atr", "trail@"),
                         ("trail_distance_atr", "táv")):
            s2.addWidget(QtWidgets.QLabel(f" {_cim}:"))
            _e = QtWidgets.QLineEdit(str(_alap.get(_k, "")))
            _e.setFixedWidth(48)
            _e.editingFinished.connect(self._terv_valtozott)
            s2.addWidget(_e)
            self._rr_mezok[_k] = _e

        for cimke, fn in (("Töröl", self.torol), ("JSON mentés", self.ment)):
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
        s3.addWidget(QtWidgets.QLabel("sebesség"))
        self._sebesseg = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self._sebesseg.setRange(1, 2000)      # gyertya / másodperc
        self._sebesseg.setValue(8)
        self._sebesseg.setFixedWidth(180)
        s3.addWidget(self._sebesseg)
        self._seb_cimke = QtWidgets.QLabel("8")
        self._sebesseg.valueChanged.connect(
            lambda v: self._seb_cimke.setText(str(v)))
        s3.addWidget(self._seb_cimke)
        self._csak_eddig = QtWidgets.QCheckBox("csak eddig látszik")
        self._csak_eddig.setChecked(True)
        self._csak_eddig.stateChanged.connect(lambda *_: self._kurzor_rajz())
        s3.addWidget(self._csak_eddig)
        self._bidask = QtWidgets.QCheckBox("BID/ASK")
        self._bidask.setChecked(True)
        self._bidask.stateChanged.connect(lambda *_: self._kurzor_rajz())
        s3.addWidget(self._bidask)
        g = QtWidgets.QPushButton("Lejátszás vége")
        g.clicked.connect(self.kurzor_le)
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

        # ── Listák ───────────────────────────────────────────────────────
        self._fulek = QtWidgets.QTabWidget()
        self._fulek.setMaximumHeight(170)
        self._tablak = {}
        for kulcs, cim, oszlopok in (
            ("nyitott", "Nyitott",
             ("idő", "ir", "belépő", "most", "P&L", "R", "SL", "TP", "perc")),
            ("lezart", "Lezárt",
             ("idő", "ir", "belépő", "kilépő", "P&L", "R", "vége")),
        ):
            t = QtWidgets.QTableWidget(0, len(oszlopok))
            t.setHorizontalHeaderLabels(oszlopok)
            t.horizontalHeader().setSectionResizeMode(
                QtWidgets.QHeaderView.Stretch)
            t.verticalHeader().setVisible(False)
            self._fulek.addTab(t, cim)
            self._tablak[kulcs] = t
        fo.addWidget(self._fulek)

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
        self._plot.addItem(self._kurzor_vonal)
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
            self._plot.addItem(_l)
        # a jövőt takaró sáv
        self._takaro = pg.LinearRegionItem(
            orientation="vertical", movable=False,
            brush=pg.mkBrush(16, 20, 24, 235))
        self._takaro.setZValue(50)
        self._takaro.setVisible(False)
        self._plot.addItem(self._takaro)
        self._ido_cimke = pg.TextItem(anchor=(1, 1), color=szin("yellow"))
        self._ido_cimke.setZValue(60)
        self._plot.addItem(self._ido_cimke)
        self._vb.sigRangeChanged.connect(lambda *_: self._cimke_helyre())

    def _mod_valt(self, ertek: str) -> None:
        """Kattintás-mód váltása (egyszerre csak egy aktív)."""
        self._mod = None if self._mod == ertek else ertek
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
        self._allapot.setText("betöltés…")
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
        self._kurzor_rajz()
        self._allapot.setText(
            f"{len(chart)} gyertya · {_db['kirajzolt']} jelölő · "
            f"{_db['idon_kivul']} a kijelölésen kívül")

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
        try:
            poz = self._chart.index.get_indexer([ido], method="nearest")
            return float(self._chart["close"].iloc[int(poz[0])])
        except (IndexError, ValueError, KeyError):
            return None

    def _alap_sl(self, ido, irany: str) -> "float | None":
        ar = self._be_ar(ido)
        if ar is None:
            return None
        try:
            poz = int(self._chart.index.get_indexer([ido], method="nearest")[0])
            _h = self._chart["high"].iloc[max(0, poz - 20):poz + 1]
            _l = self._chart["low"].iloc[max(0, poz - 20):poz + 1]
            _a = float((_h - _l).mean()) or (ar * 0.001)
        except (IndexError, ValueError, KeyError):
            _a = ar * 0.001
        return ar - _a if irany == "BUY" else ar + _a

    def _belepok_rajz(self) -> None:
        """A terv elemeinek (újra)építése."""
        for b in self._belepok:
            for it in (b.vonal, b.sl_vonal, b.tp_vonal, b.kock, b.cel):
                if it is not None:
                    self._plot.removeItem(it)
            b.vonal = b.sl_vonal = b.tp_vonal = b.kock = b.cel = None
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
            b.kock = pg.LinearRegionItem(
                values=(min(_be, b.sl), max(_be, b.sl)),
                orientation="horizontal", movable=False,
                brush=pg.mkBrush(220, 0, 0, 38))
            b.cel = pg.LinearRegionItem(
                values=(min(_be, b.tp_ar(_be)), max(_be, b.tp_ar(_be))),
                orientation="horizontal", movable=False,
                brush=pg.mkBrush(0, 170, 0, 38))
            for it in (b.kock, b.cel):
                it.setZValue(-20)
                self._plot.addItem(it)
            for it in (b.sl_vonal, b.tp_vonal):
                self._plot.addItem(it)
        self._be_jelolo_rajz()

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
            b.kock.setRegion((min(_be, b.sl), max(_be, b.sl)))
            b.cel.setRegion((min(_be, b.tp_ar(_be)), max(_be, b.tp_ar(_be))))
            b.tp_vonal.setValue(b.tp_ar(_be))

    def _sl_mozgott(self, b: "Belepo") -> None:
        b.sl = float(b.sl_vonal.value())
        _be = self._be_ar(b.ido)
        if _be is None:
            return
        # ⚠ A TP A STOP FÜGGVÉNYE: húzod a pirosat, mozog a zöld.
        b.tp_vonal.blockSignals(True)
        b.tp_vonal.setValue(b.tp_ar(_be))
        b.tp_vonal.blockSignals(False)
        b.kock.setRegion((min(_be, b.sl), max(_be, b.sl)))
        b.cel.setRegion((min(_be, b.tp_ar(_be)), max(_be, b.tp_ar(_be))))
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
        b.cel.setRegion((min(_be, b.tp_ar(_be)), max(_be, b.tp_ar(_be))))
        self._terv_valtozott(rajzol=False)

    def _be_mozgott(self) -> None:
        t = self._ido_x(self._be_vonal.value())
        if t is not None:
            self._be_ido = t
            self._terv_valtozott(rajzol=False)

    def _terv_valtozott(self, rajzol: bool = True) -> None:
        """A terv változott → a korábbi futtatás érvénytelen."""
        self._eredmeny = None
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
        }

    def ment(self) -> None:
        import json
        ut, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Forgatókönyv mentése", "fk.json", "JSON (*.json)")
        if not ut:
            return
        try:
            Path(ut).write_text(json.dumps(self._forgatokonyv(),
                                           ensure_ascii=False, indent=2),
                                encoding="utf-8")
            self._allapot.setText(f"mentve: {ut}")
        except OSError as ex:
            QtWidgets.QMessageBox.critical(self, "Mentés", str(ex))

    def torol(self) -> None:
        self._belepok.clear()
        self._be_ido = None
        self._valasztott = None
        self._terv_valtozott()
        self._listak_frissit()

    def futtat(self) -> None:
        if not self._belepok:
            return
        self._allapot.setText("futtatás…")
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
        self._listak_frissit()

    def _biztos_eredmeny(self) -> None:
        """A `Play` futtat — külön gomb nélkül, és csak ha a terv változott."""
        if self._eredmeny is None and self._belepok:
            self.futtat()

    def _eredmeny_rajz(self) -> None:
        """A motor kötései + a STOP ÚTJA (BE / trailing)."""
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
            # ── A STOP ÚTJA ──────────────────────────────────────────────
            _x, _y = [], []
            for e in (getattr(t, "events", None) or []):
                _tip, _ido, _ar, _sl = (list(e) + [None] * 4)[:4]
                if not _sl:
                    continue
                _px = self._tengely.hol(int(pd.Timestamp(_ido).timestamp()))
                if _px is not None:
                    _x.append(_px)
                    _y.append(float(_sl))
            if _x:
                if t.close_time is not None:
                    _vx = self._tengely.hol(int(t.close_time.timestamp()))
                    if _vx is not None:
                        _x.append(_vx)
                        _y.append(_y[-1])
                _it = pg.PlotDataItem(_x, _y, stepMode="right" if False else None,
                                      pen=pg.mkPen(szin("cyan"), width=2))
                self._plot.addItem(_it)
                self._eredmeny_elemek.append(_it)
            if t.close_time is not None:
                try:
                    _sszeg.append(t.pnl_usd / t.risk_usd if t.risk_usd else 0.0)
                except (TypeError, ZeroDivisionError):
                    pass
        _zart = [t for t in (getattr(res, "trades", None) or [])
                 if t.close_time is not None]
        if _zart:
            self._allapot.setText(
                f"{len(_zart)} lezárt kötés · "
                f"{sum(t.pnl_usd for t in _zart):+.2f} · {sum(_sszeg):+.2f} R")

    # ── Listák ───────────────────────────────────────────────────────────
    def _listak_frissit(self) -> None:
        for t in self._tablak.values():
            t.setRowCount(0)
        res = (self._eredmeny or {}).get("res")
        if res is None:
            return
        _kt = self._kurzor_ido()
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
                self._sor(self._tablak["nyitott"], [
                    str(tr.open_time)[5:16], tr.direction,
                    self._ar(tr.open_price),
                    self._ar(_most) if _most is not None else "—",
                    "—" if _pnl != _pnl else f"{_pnl:+.2f}",
                    "—" if _r != _r else f"{_r:+.2f}",
                    self._ar(_sl0), self._ar(tr.tp),
                    "—" if _perc is None else f"{_perc:.0f}"])
            else:
                try:
                    _r = (tr.pnl_usd / tr.risk_usd) if tr.risk_usd else 0.0
                except (TypeError, ZeroDivisionError):
                    _r = 0.0
                self._sor(self._tablak["lezart"], [
                    str(tr.open_time)[5:16], tr.direction,
                    self._ar(tr.open_price), str(tr.close_time)[5:16],
                    f"{tr.pnl_usd:+.2f}", f"{_r:+.2f}", tr.status])

    @staticmethod
    def _sor(tabla, ertekek) -> None:
        r = tabla.rowCount()
        tabla.insertRow(r)
        for c, v in enumerate(ertekek):
            it = QtWidgets.QTableWidgetItem(str(v))
            it.setTextAlignment(QtCore.Qt.AlignCenter)
            tabla.setItem(r, c, it)

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
        if self._ido_zito.isActive():
            self._ido_zito.stop()
            self._play.setText("▶ Play")
            return
        if self._kurzor is None:
            self._kurzor = 0
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

    def kurzor_le(self) -> None:
        self._ido_zito.stop()
        self._play.setText("▶ Play")
        self._kurzor = None
        self._kurzor_rajz()
        self._listak_frissit()

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
        self._cimke_helyre()

    def _cimke_helyre(self) -> None:
        try:
            (x0, x1), (y0, y1) = self._vb.viewRange()
            self._ido_cimke.setPos(x1, y0)
        except Exception:
            pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbol")
    ap.add_argument("--strategy")
    ap.add_argument("--tf", type=int, default=15)
    ap.add_argument("--from", dest="tol")
    ap.add_argument("--to", dest="ig")
    a = ap.parse_args(argv)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = LabAblak(symbol=a.symbol, strategy=a.strategy, tf_perc=a.tf,
                 tol=a.tol, ig=a.ig)
    w.show()
    return app.exec()


if __name__ == "__main__":
    _sys.exit(main())

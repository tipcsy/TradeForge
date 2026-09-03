"""PYQTGRAPH-PRÓBA — megéri-e lecserélni a matplotlib-et a kézi laborban?

    python tools/lab_qt_spike.py --symbol UsaTec --tf 15 --from 2026-08-25 --to 2026-08-26

⚠ EZ NEM TERMÉK, HANEM DÖNTÉSI PRÓBA. Egyetlen kérdést válaszol meg: azok a
dolgok, amiket a matplotlib-es laborban KÉZZEL kellett megírni (és amelyek
sorra hibásnak bizonyultak), a pyqtgraph-ban KÉSZEN vannak-e, és tényleg
jobbak-e. Ezért szándékosan hiányzik belőle minden más: nincs forgatókönyv,
nincs futtatás, nincs lista. A motor-oldal (`lab_scenario`, `run_pair`) a
cserétől függetlenül változatlan marad — a próba csak a RAJZOLÁST méri.

A MÉRT PONTOK (mind a felhasználó 2026-09-03-i panaszaiból):

  1. Húzható SL/TP vonal, ami MAGÁTÓL követi az egeret és nem lehet elveszíteni
     (matplotlib: kézzel írt találat-teszt, tűrés-hangolás, és a vonal kicsúszott
     a képből).
  2. Görgő-nagyítás és húzás (matplotlib: az eszköztár használhatatlan volt,
     saját kezelőket kellett írni).
  3. Dátum a vízszintes tengelyen (matplotlib: a formázó a REJTETT sáv-tengelyre
     került, és eltűnt).
  4. Újrarajzolási sebesség — ez korlátozta a `Play` gyorsítását.

A gyertyákat és az adatot a MEGLÉVŐ modulokból veszi (`tools.lab_chart.keszit`),
hogy az összehasonlítás tisztességes legyen: ugyanaz az adat, ugyanaz a szakasz.
"""
from __future__ import annotations

import sys as _sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import argparse

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets


class Gyertyak(pg.GraphicsObject):
    """Gyertya-sorozat EGY rajzolt objektumként.

    ⚠ Ez a pyqtgraph mintája: a rajzot egyszer „kiégetjük" egy `QPicture`-be, és
    a nagyítás/görgetés utána a GPU dolga — nem rajzolunk újra. A matplotlib-es
    változatban minden nézet-változás teljes újrarajzolás volt, és ez korlátozta
    a `Play` sebességét."""

    def __init__(self, df):
        super().__init__()
        self.df = df
        self._kep = pg.QtGui.QPicture()
        self._rajzol()

    def _rajzol(self):
        p = pg.QtGui.QPainter(self._kep)
        o = self.df["open"].to_numpy(float)
        h = self.df["high"].to_numpy(float)
        l = self.df["low"].to_numpy(float)
        c = self.df["close"].to_numpy(float)
        _zold = pg.mkPen("#00aa00")
        _piros = pg.mkPen("#dc0000")
        _zb = pg.mkBrush("#00aa00")
        _pb = pg.mkBrush("#dc0000")
        for i in range(len(self.df)):
            fel = c[i] >= o[i]
            p.setPen(_zold if fel else _piros)
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

    ⚠ A tengely bar-indexen áll (a hétvégék miatt), a felirat viszont idő. A
    pyqtgraph-ban ez egy metódus felülírása; a matplotlib-es változatban a
    formázó a REJTETT sáv-tengelyre került, és a dátum egyszerűen eltűnt."""

    def __init__(self, index, *a, **kw):
        super().__init__(*a, **kw)
        self._idx = index

    def tickStrings(self, values, scale, spacing):
        ki = []
        for v in values:
            i = int(round(v))
            ki.append(self._idx[i].strftime("%m-%d %H:%M")
                      if 0 <= i < len(self._idx) else "")
        return ki


def fut(symbol: str, tf: int, tol, ig) -> int:
    from tools.lab_chart import keszit

    t0 = time.perf_counter()
    chart, objs, uzenet = keszit(symbol, "", tf, tol, ig)
    if chart is None:
        print(f"HIBA: {uzenet}")
        return 2
    _betoltes = time.perf_counter() - t0

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    pg.setConfigOptions(antialias=False, background="#101418", foreground="#c8c8c8")

    abl = pg.PlotWidget(axisItems={"bottom": IdoTengely(chart.index,
                                                        orientation="bottom")})
    abl.setWindowTitle(f"pyqtgraph-próba — {symbol} M{tf} ({len(chart)} gyertya)")
    abl.showGrid(x=True, y=True, alpha=0.15)

    t1 = time.perf_counter()
    abl.addItem(Gyertyak(chart))
    _rajz = time.perf_counter() - t1

    # ── A LÉNYEG: HÚZHATÓ SL / TP ────────────────────────────────────────
    # ⚠ EZ AZ EGÉSZ PRÓBA CÉLJA. A matplotlib-es változatban a fogás
    # találat-teszttel, tűrés-hangolással és kézi újrarajzolással készült — és
    # a vonal el tudott veszni a képből. Itt EGY sor: `movable=True`.
    be_ar = float(chart["close"].iloc[len(chart) // 3])
    _tav = float((chart["high"] - chart["low"]).mean()) * 3
    sl = pg.InfiniteLine(pos=be_ar - _tav, angle=0, movable=True,
                         pen=pg.mkPen("#dc0000", width=2),
                         hoverPen=pg.mkPen("#ff6666", width=3),
                         label="SL {value:0.2f}",
                         labelOpts={"position": 0.95, "color": "#dc0000"})
    tp = pg.InfiniteLine(pos=be_ar + 2 * _tav, angle=0, movable=True,
                         pen=pg.mkPen("#00aa00", width=2),
                         hoverPen=pg.mkPen("#66ff66", width=3),
                         label="TP {value:0.2f}",
                         labelOpts={"position": 0.95, "color": "#00aa00"})
    belepo = pg.InfiniteLine(pos=be_ar, angle=0, movable=False,
                             pen=pg.mkPen("#ffffff", width=1,
                                          style=QtCore.Qt.DashLine))
    kurzor = pg.InfiniteLine(pos=len(chart) // 3, angle=90, movable=True,
                             pen=pg.mkPen("#f0d200", width=2),
                             hoverPen=pg.mkPen("#ffff88", width=3))
    for it in (belepo, sl, tp, kurzor):
        abl.addItem(it)

    # ── A KOCKÁZAT / CÉL SÁV ─────────────────────────────────────────────
    # `LinearRegionItem` vízszintesen: a sáv MAGÁTÓL követi a vonalakat.
    kock = pg.LinearRegionItem(values=(sl.value(), be_ar), orientation="horizontal",
                               brush=pg.mkBrush(220, 0, 0, 40), movable=False)
    cel = pg.LinearRegionItem(values=(be_ar, tp.value()), orientation="horizontal",
                              brush=pg.mkBrush(0, 170, 0, 40), movable=False)
    for r in (kock, cel):
        r.setZValue(-10)
        abl.addItem(r)

    cimke = pg.TextItem(anchor=(1, 1), color="#f0d200")
    abl.addItem(cimke)

    def _frissit():
        """A sávok és a felirat követése. ⚠ Csak a MOZGATOTT elem rajzolódik
        újra — a gyertyák nem. A matplotlib-nél minden mozdulat teljes
        újrarajzolás volt."""
        kock.setRegion((sl.value(), be_ar))
        cel.setRegion((be_ar, tp.value()))
        _r = abs(tp.value() - be_ar) / max(1e-9, abs(be_ar - sl.value()))
        i = max(0, min(len(chart) - 1, int(round(kurzor.value()))))
        cimke.setText(f"{chart.index[i]:%Y-%m-%d %H:%M}   TP {_r:.2f} R")
        _vb = abl.getViewBox().viewRange()
        cimke.setPos(_vb[0][1], _vb[1][0])

    for it in (sl, tp, kurzor):
        it.sigPositionChanged.connect(_frissit)
    abl.getViewBox().sigRangeChanged.connect(lambda *_: _frissit())
    _frissit()

    abl.resize(1400, 800)
    abl.show()

    print(f"  adat+objektumok betöltése : {_betoltes * 1000:7.1f} ms")
    print(f"  gyertyák kirajzolása      : {_rajz * 1000:7.1f} ms  "
          f"({len(chart)} gyertya)")
    print()
    print("  PRÓBÁLD KI:")
    print("   · fogd meg a piros/zöld vonalat és húzd — bárhova, akár a képen kívülre")
    print("   · görgő = nagyítás, húzás = görgetés (jobb gomb: függőleges nagyítás)")
    print("   · a sárga függőleges vonal a lejátszás-kurzor — az is húzható")
    print("   · a jobb alsó sarokban a kurzor ideje és az aktuális R")
    return app.exec()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbol", default="UsaTec")
    ap.add_argument("--tf", type=int, default=15)
    ap.add_argument("--from", dest="tol", default=None)
    ap.add_argument("--to", dest="ig", default=None)
    a = ap.parse_args(argv)
    return fut(a.symbol, a.tf, a.tol, a.ig)


if __name__ == "__main__":
    _sys.exit(main())

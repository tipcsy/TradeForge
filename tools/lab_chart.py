"""KÉZI LABORATÓRIUM — 2. LÉPCSŐ: chart-ablak (`python main.py lab`).

    python main.py lab
    python main.py lab --symbol UsaTec --strategy wpr_sma --tf 15

⚠ MIÉRT PYTHONBAN, ÉS NEM AZ MT5-ÖN. A gombos forgatókönyv-építés a Strategy
Testerben ELVI lehetetlenség (nincs eseménykezelés), az élő charton pedig egy
teljes „úgy csinálj, mintha kötnél" réteget kellene MQL5-ben megírni —
pozíciónyilvántartással, SL/TP-figyeléssel, BE-vel, ráépítéssel. Az a réteg
MÁSODSZOR implementálná azt, ami Pythonban már megvan, és a projekt pontosan
ettől szenvedett többször: két forrás, ami külön romlik el.

⚠ EZÉRT NINCS ITT SEMMI ÚJRASZÁMOLVA. A chart

  * a gyertyákat a MEGLÉVŐ parquetből veszi (`trading.backtest.load_data`),
  * a rajzot a MEGLÉVŐ `live_trader.pair_visual_objects()`-ból kapja — ugyanaz
    a hívás, amiből az MT5-fájl is készül, ugyanazokkal a kapukkal,
  * a színeket a `strategy.visual.COLORS`-ból, a durvább idősíkot a
    `strategy.ml_ai.resample_ohlc`-ból.

Ha itt bármit „egyszerűbb lenne újraírni", az a másolat, amit el kell kerülni.

⚠ KÜLÖN PROCESSZ. A felhasználó kérése: „Igen, ez egy teljesen független
»program« legyen, de használja a program egyes moduljait úgy, hogy ne
keletkezzenek belőle másolatok." Egy chart-rajzoló ablak ne ugyanabban a
processzben legyen, mint az élő kereskedés — épp a 2. pont (gyenge gép) szólt
arról, hogy a motor önmagában fusson.

── MI VAN BENNE (2. lépcső) ───────────────────────────────────────────────
Gyertyák, idősík-váltás (M1/M5/M15/H1), a mi indikátoraink és jelölőink,
-tól/-ig kijelölés. A gombok (`Add BUY`, `Add BE`, `Start építés`) és a `Play`
a 3. lépcső; az időpillanat-nézet és a számlagörbe a 4.

⚠ AZ X TENGELY GYERTYA-INDEX, NEM IDŐ. Naptári tengelyen a hétvégék és a
kereskedési szünetek üres sávként jelennének meg, és az ár „ugrálna" — az MT5
chartja is bar-indexet használ. A rajz-objektumok viszont EPOCH időt hordoznak,
ezért az `Idotengely` fordítja őket a legközelebbi gyertyára.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import logging
log = logging.getLogger(__name__)

import numpy as np
import pandas as pd

from strategy import visual as viz


# ── Színek: EGY forrásból ─────────────────────────────────────────────────
def szin(nev: str) -> str:
    """A `strategy.visual` szemantikus színneve → matplotlib hex.

    ⚠ NINCS SAJÁT PALETTA. Ha itt külön színek lennének, a Python chart és az
    MT5 chart ugyanazt a jelet MÁS színnel mutatná — és a kettő összevetése
    pont az, amiért a labor készült."""
    r, g, b = viz.COLORS.get(nev, viz.COLORS["white"])
    return f"#{r:02x}{g:02x}{b:02x}"


# ── Idősíkok ──────────────────────────────────────────────────────────────
# A parquetből M1 és M15 jön; a többi ezekből mintázódik át.
IDOSIKOK = ((1, "M1"), (5, "M5"), (15, "M15"), (60, "H1"), (240, "H4"))


def chart_barok(df_m1, df_m15, perc: int):
    """A CHART gyertyái a kért idősíkon — a meglévő átmintázóval.

    ⚠ Csak FELFELÉ mintázunk: M5 az M1-ből, H1/H4 az M15-ből. Lefelé (finomabb
    idősík durvábból) nem létező adatot találna ki."""
    from strategy.ml_ai import resample_ohlc
    perc = int(perc)
    if perc == 1:
        return df_m1
    if perc == 15:
        return df_m15
    if perc < 15:
        return resample_ohlc(df_m1, perc)
    return resample_ohlc(df_m15, perc)


class Idotengely:
    """EPOCH ↔ gyertya-index fordítás.

    ⚠ A rajz-objektumok epoch másodpercet hordoznak (ahogy az MT5 `copy_rates`),
    a chart viszont bar-indexen rajzol. A `hol()` a LEGKÖZELEBBI gyertyát adja,
    de csak ha az tényleg közel van: egy hónappal arrébb tett jelölő nem
    ugyanaz a jel, azt inkább hagyjuk ki, mint hogy a chart szélére ragasszuk."""

    def __init__(self, index, turés_bar: float = 1.5):
        self._ts = np.asarray([int(t.timestamp()) for t in index], dtype=np.int64)
        # A gyertya-köz (mp) — ehhez mérjük a tűrést.
        self._koz = int(np.median(np.diff(self._ts))) if len(self._ts) > 2 else 60
        self._tures = self._koz * float(turés_bar)

    def hol(self, t) -> "float | None":
        if not len(self._ts):
            return None
        i = int(np.searchsorted(self._ts, int(t)))
        jeloltek = [j for j in (i - 1, i) if 0 <= j < len(self._ts)]
        if not jeloltek:
            return None
        j = min(jeloltek, key=lambda k: abs(self._ts[k] - int(t)))
        if abs(self._ts[j] - int(t)) > self._tures:
            return None
        # Tört index: a gyertyán BELÜLI pozíció (a jelölő ne ugorjon a bár elejére).
        return j + max(0.0, min(1.0, (int(t) - self._ts[j]) / self._koz)) - 0.5


# ── Rajzolás ──────────────────────────────────────────────────────────────
def gyertyak(ax, df) -> None:
    """Gyertyák — vektorosan (kanócok egy LineCollection-ben, testek egy
    PolyCollection-ben). ⚠ Gyertyánként külön patch 5000 báron már másodperces;
    a vászon-tábla migrációnál ugyanez a lecke jött ki a widget-számból."""
    from matplotlib.collections import LineCollection, PolyCollection
    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    x = np.arange(len(df), dtype=float)
    fel = c >= o
    ax.add_collection(LineCollection(
        [[(xi, li), (xi, hi)] for xi, li, hi in zip(x, l, h)],
        colors=np.where(fel, szin("green"), szin("red")), linewidths=0.8))
    _sz = 0.36
    test = [[(xi - _sz, oi), (xi - _sz, ci), (xi + _sz, ci), (xi + _sz, oi)]
            for xi, oi, ci in zip(x, o, c)]
    ax.add_collection(PolyCollection(
        test, facecolors=np.where(fel, szin("green"), szin("red")),
        edgecolors=np.where(fel, szin("green"), szin("red")), linewidths=0.5))
    ax.set_xlim(-1, len(df))
    _also, _felso = float(np.min(l)), float(np.max(h))
    _rés = (_felso - _also) * 0.06 or 1.0
    ax.set_ylim(_also - _rés, _felso + _rés)


def objektumok_rajza(ax, objektumok, tengely: "Idotengely") -> dict:
    """A `strategy.visual` primitívek kirajzolása. Visszaad egy SZÁMLÁLÓT:
    típusonként hány objektum került ki, és hány esett ki időn kívül.

    ⚠ A KIESŐKET SZÁMOLJUK. Ha egy jelölő azért nem látszik, mert a kijelölt
    időszakon kívülre esik, azt tudni kell — különben a chart csendben
    kevesebbet mutat, mint amit a motor csinált. Ez a projekt visszatérő
    hibája (viz ↔ backtest paritás)."""
    from matplotlib.patches import Rectangle
    db = {"kirajzolt": 0, "idon_kivul": 0, "ismeretlen": 0}

    def _x(t):
        return tengely.hol(t)

    for o in objektumok:
        nev = type(o).__name__
        if isinstance(o, viz.Rect):
            x1, x2 = _x(o.t1), _x(o.t2)
            if x1 is None or x2 is None:
                db["idon_kivul"] += 1
                continue
            ax.add_patch(Rectangle((min(x1, x2), min(o.p1, o.p2)),
                                   abs(x2 - x1) or 0.5, abs(o.p2 - o.p1),
                                   facecolor=szin(o.color),
                                   edgecolor=szin(o.color),
                                   alpha=0.25 if o.fill else 0.0, linewidth=0.6,
                                   zorder=1))
        elif isinstance(o, viz.VLine):
            x1 = _x(o.t1)
            if x1 is None:
                db["idon_kivul"] += 1
                continue
            ax.axvline(x1, color=szin(o.color), linewidth=max(0.6, o.width * 0.7),
                       alpha=0.75, zorder=2)
        elif isinstance(o, viz.Trend):
            x1, x2 = _x(o.t1), _x(o.t2)
            if x1 is None or x2 is None:
                db["idon_kivul"] += 1
                continue
            ax.plot([x1, x2], [o.p1, o.p2], color=szin(o.color),
                    linewidth=max(0.7, o.width * 0.8),
                    linestyle="--" if o.style else "-", zorder=3)
        elif isinstance(o, viz.Arrow):
            x1 = _x(o.t1)
            if x1 is None:
                db["idon_kivul"] += 1
                continue
            # 233 = fel (BUY), 234 = le (SELL) — a Wingdings-kód jelentése.
            ax.plot([x1], [o.p1], marker="^" if int(o.code) == 233 else "v",
                    color=szin(o.color), markersize=9, zorder=5)
        elif isinstance(o, viz.Text):
            x1 = _x(o.t1)
            if x1 is None:
                db["idon_kivul"] += 1
                continue
            ax.annotate(o.text, (x1, o.p1), color=szin(o.color),
                        fontsize=max(6, o.fontsize - 2), zorder=6,
                        xytext=(3, 3), textcoords="offset points")
        elif isinstance(o, (viz.BarState, viz.TfOnly, viz.Indicator,
                            viz.Alert, viz.Label)):
            # Nem geometria: a sáv és a kísérőszövegek külön kezelendők.
            db.setdefault(nev, 0)
            db[nev] += 1
            continue
        else:
            db["ismeretlen"] += 1
            continue
        db["kirajzolt"] += 1
    return db


def allapot_sav(ax, objektumok, tengely: "Idotengely") -> int:
    """A per-gyertya SÁV-ÁLLAPOT (`BarState`) csíkja a chart alatt.

    Három réteg, ahogy az MT5 TradeForgeBands: szürke no-trade / zöld-piros
    SMA-irány / kék M15-ablak. A negyedik (piac-állapot) `-1`-nél kimarad."""
    allapotok = [o for o in objektumok if isinstance(o, viz.BarState)]
    if not allapotok:
        ax.set_visible(False)
        return 0
    ax.set_visible(True)
    for o in allapotok:
        x = tengely.hol(o.t)
        if x is None:
            continue
        if o.notrade:
            ax.add_patch(_sav(x, 0, szin("gray")))
            continue
        if o.dir:
            ax.add_patch(_sav(x, 1, szin("green" if o.dir > 0 else "red")))
        if o.window:
            ax.add_patch(_sav(x, 2, szin("blue")))
        if o.market_state >= 0:
            ax.add_patch(_sav(x, 3, szin("orange")))
    ax.set_ylim(0, 4)
    ax.set_yticks([0.5, 1.5, 2.5, 3.5])
    ax.set_yticklabels(["no-trade", "irány", "ablak", "piac"], fontsize=7)
    return len(allapotok)


def _sav(x: float, sor: int, sz: str):
    from matplotlib.patches import Rectangle
    return Rectangle((x - 0.5, sor), 1.0, 0.9, facecolor=sz, edgecolor="none")


def kiserok(objektumok) -> list:
    """A NEM geometrikus objektumok olvasható sorai (indikátorok, riasztás,
    sarok-címkék) — a chart melletti panelbe."""
    ki = []
    for o in objektumok:
        if isinstance(o, viz.Indicator):
            _lv = ("  " + " / ".join(f"{x:g}" for x in o.levels)) if o.levels else ""
            ki.append(f"{o.kind} {o.timeframe}({o.period}){_lv}")
        elif isinstance(o, viz.TfOnly):
            ki.append(f"csak M{o.minutes} charton")
        elif isinstance(o, viz.Alert):
            ki.append(f"RIASZTÁS: {o.text}")
        elif isinstance(o, viz.Label):
            ki.extend(str(o.text).split("|"))
    return ki


# ── Adat + objektumok EGY helyen ──────────────────────────────────────────
def keszit(symbol: str, strategy_name: str, tf_perc: int,
           tol=None, ig=None, cfg=None):
    """`(barok_df, objektumok, uzenet)` — a chart teljes tartalma.

    ⚠ A `cfg` MUSZÁJ: enélkül a TF-együttállás kapu némán kimarad, és a chartra
    több jelölő kerülne, mint amit a motor kötött volna. (Mérve, UsaInd
    2026-06-08..12: 48 jelölő 19 helyett.) Ezt a `pair_visual_objects`
    docstringje is kimondja; itt csak nem hagyjuk kihagyni."""
    from strategy import get_strategy_by_name
    from strategy.settings import config_for_strategy, load_config
    from trading import backtest as bt
    from trading.live_trader import (default_params, pair_visual_objects,
                                     strategy_params)

    cfg = cfg if cfg is not None else load_config(ROOT / "config.json")
    pair_cfg = (cfg.get("pairs") or {}).get(symbol)
    if not pair_cfg:
        return None, [], f"a(z) {symbol} nincs a config.json `pairs` blokkjában"
    try:
        strategy = get_strategy_by_name(strategy_name)
    except Exception:
        return None, [], f"ismeretlen stratégia: {strategy_name!r}"

    df15, df1 = bt.load_data(symbol)
    if df15 is None or df1 is None:
        return None, [], (f"nincs letöltött adat a(z) {symbol} párhoz — "
                          f"`python main.py download`")

    cs = config_for_strategy(cfg, strategy_name)
    params = strategy_params(symbol, strategy_name, cs,
                             fallback=default_params(strategy, cs))

    # ⚠ A RAJZ a stratégia MÉLY ablakából jön (visual_lookback_bars), nem a
    # kijelölt szakaszból: egy sekélyebb ablak MÁS M15-jelet adna. (Ez a
    # `m15-warmup-depth-divergence` lelet.) A kijelölés csak a NÉZETET szűkíti.
    barok = {}
    for tf in strategy.timeframes():
        n = strategy.visual_lookback_bars(params, tf.label)
        if n <= 0:
            continue
        _f = df1 if tf.minutes == 1 else df15
        _f = _vag(_f, None, ig)          # a jövőt levágjuk, a múltat nem
        barok[tf.label] = _f.tail(n)
    objektumok = pair_visual_objects(
        symbol, params, strategy, float(pair_cfg.get("point_size") or 0.0),
        pair_cfg=pair_cfg, bars=barok, cfg=cfg)

    chart = _vag(chart_barok(df1, df15, tf_perc), tol, ig)
    if chart is None or len(chart) < 2:
        return None, objektumok, "a megadott időszakra nincs elég gyertya"
    return chart, objektumok, ""


def _vag(df, tol, ig):
    """Időszak-szűrés. A határok NAIV időként érkeznek (ahogy a charton látod),
    az index viszont időzóna-tudatos — a `TypeError` itt dőljön el, ne beljebb."""
    if df is None or (tol is None and ig is None):
        return df
    tz = getattr(df.index, "tz", None)

    def _t(x, veg=False):
        if x in (None, ""):
            return None
        t = pd.Timestamp(x)
        if veg and t.hour == 0 and t.minute == 0:
            t = t + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        if tz is not None:
            t = t.tz_localize(tz) if t.tzinfo is None else t.tz_convert(tz)
        return t

    a, b = _t(tol), _t(ig, veg=True)
    if a is not None:
        df = df[df.index >= a]
    if b is not None:
        df = df[df.index <= b]
    return df


# ── Az ablak ──────────────────────────────────────────────────────────────
class LabAblak:
    """A chart-ablak. ⚠ Külön processz — nem a kereskedő felület része."""

    def __init__(self, symbol=None, strategy=None, tf_perc=15, tol=None, ig=None):
        import tkinter as tk
        from tkinter import ttk
        from strategy.settings import load_config

        self.cfg = load_config(ROOT / "config.json")
        self._parok = sorted((self.cfg.get("pairs") or {}).keys())
        if not self._parok:
            raise SystemExit("HIBA: a config.json `pairs` blokkja üres.")

        self.root = tk.Tk()
        from version import APP_NAME, APP_VERSION
        self.root.title(f"{APP_NAME} {APP_VERSION} — kézi laboratórium")
        self.root.geometry("1500x900")

        sav = tk.Frame(self.root)
        sav.pack(fill="x", padx=8, pady=6)

        self._sym = tk.StringVar(value=symbol or self._parok[0])
        self._strat = tk.StringVar(value=strategy or "")
        self._tf = tk.IntVar(value=int(tf_perc))
        self._tol = tk.StringVar(value=tol or "")
        self._ig = tk.StringVar(value=ig or "")

        tk.Label(sav, text="Instrumentum").pack(side="left")
        self._sym_box = ttk.Combobox(sav, textvariable=self._sym, width=12,
                                     values=self._parok, state="readonly")
        self._sym_box.pack(side="left", padx=(4, 12))
        self._sym_box.bind("<<ComboboxSelected>>", lambda e: self._strat_lista())

        tk.Label(sav, text="Stratégia").pack(side="left")
        self._strat_box = ttk.Combobox(sav, textvariable=self._strat, width=18,
                                       state="readonly")
        self._strat_box.pack(side="left", padx=(4, 12))

        tk.Label(sav, text="Idősík").pack(side="left")
        for perc, cimke in IDOSIKOK:
            tk.Radiobutton(sav, text=cimke, value=perc, variable=self._tf,
                           command=self.betolt).pack(side="left")

        tk.Label(sav, text="  -tól").pack(side="left")
        tk.Entry(sav, textvariable=self._tol, width=17).pack(side="left", padx=2)
        tk.Label(sav, text="-ig").pack(side="left")
        tk.Entry(sav, textvariable=self._ig, width=17).pack(side="left", padx=2)
        tk.Button(sav, text="Betölt", command=self.betolt).pack(side="left", padx=8)

        self._allapot = tk.Label(self.root, text="", anchor="w", fg="#666")
        self._allapot.pack(fill="x", padx=10)

        import matplotlib
        matplotlib.use("TkAgg")
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_tkagg import (
            FigureCanvasTkAgg, NavigationToolbar2Tk)
        self._fig = Figure(figsize=(15, 8), dpi=96)
        self._ax, self._ax_sav = self._fig.subplots(
            2, 1, sharex=True, gridspec_kw={"height_ratios": [4, 1]})
        self._vaszon = FigureCanvasTkAgg(self._fig, master=self.root)
        NavigationToolbar2Tk(self._vaszon, self.root).update()
        self._vaszon.get_tk_widget().pack(fill="both", expand=True,
                                          padx=8, pady=(0, 8))
        self._strat_lista()
        self.betolt()

    def _strat_lista(self) -> None:
        """A PÁR saját engedélyezett stratégiái — ugyanaz a halmaz, amit a motor
        futtat. ⚠ Nem az összes létező: egy máshol nem futó stratégia rajza
        félrevezető lenne (a labor azt mutassa, ami élesben történne)."""
        from strategy import enabled_strategy_names
        nevek = list(enabled_strategy_names(self.cfg, self._sym.get()))
        if not nevek:
            from strategy import available_strategy_names
            nevek = list(available_strategy_names(self.cfg))
        self._strat_box["values"] = nevek
        if self._strat.get() not in nevek:
            self._strat.set(nevek[0] if nevek else "")

    def betolt(self) -> None:
        self._allapot.config(text="betöltés…", fg="#666")
        self.root.update_idletasks()
        try:
            chart, objs, uzenet = keszit(
                self._sym.get(), self._strat.get(), self._tf.get(),
                self._tol.get() or None, self._ig.get() or None, cfg=self.cfg)
        except Exception as ex:
            # ⚠ KIMONDJUK. Egy labor, ami csak üres chartot mutat, használhatatlan.
            log.exception("a chart betöltése elbukott")
            self._allapot.config(text=f"HIBA: {type(ex).__name__}: {ex}",
                                 fg="#c00")
            return
        self._ax.clear()
        self._ax_sav.clear()
        if chart is None:
            self._allapot.config(text=f"HIBA: {uzenet}", fg="#c00")
            self._vaszon.draw()
            return
        gyertyak(self._ax, chart)
        tengely = Idotengely(chart.index)
        db = objektumok_rajza(self._ax, objs, tengely)
        allapot_sav(self._ax_sav, objs, tengely)
        self._ax.set_title(
            f"{self._sym.get()} / {self._strat.get()}  "
            f"{dict(IDOSIKOK).get(self._tf.get(), self._tf.get())}")
        # Az időcímkék a gyertya-indexhez.
        _n = max(1, len(chart) // 12)
        self._ax_sav.set_xticks(list(range(0, len(chart), _n)))
        self._ax_sav.set_xticklabels(
            [t.strftime("%m-%d %H:%M") for t in chart.index[::_n]],
            rotation=45, fontsize=7, ha="right")
        self._fig.tight_layout()
        self._vaszon.draw()
        # ⚠ AZ IDŐN KÍVÜLI JELÖLŐK SZÁMÁT KIÍRJUK: ha egy jel azért nem látszik,
        # mert a kijelölésen kívülre esik, azt tudni kell — a csendben kevesebbet
        # mutató chart ebben a projektben már többször tévútra vitt.
        self._allapot.config(
            text=(f"{len(chart)} gyertya · {db['kirajzolt']} jelölő kirajzolva"
                  f" · {db['idon_kivul']} a kijelölésen kívül"
                  + ("   |   " + "   ".join(kiserok(objs)) if objs else "")),
            fg="#666")

    def fut(self) -> None:
        self.root.mainloop()


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="TradeForge kézi laboratórium (chart)")
    ap.add_argument("--symbol")
    ap.add_argument("--strategy")
    ap.add_argument("--tf", type=int, default=15, help="chart-idősík percben")
    ap.add_argument("--from", dest="tol")
    ap.add_argument("--to", dest="ig")
    a = ap.parse_args(argv)
    LabAblak(symbol=a.symbol, strategy=a.strategy, tf_perc=a.tf,
             tol=a.tol, ig=a.ig).fut()
    return 0


if __name__ == "__main__":
    sys.exit(main())

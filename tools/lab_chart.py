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

── MI VAN BENNE ───────────────────────────────────────────────────────────
2. lépcső: gyertyák, idősík-váltás (M1/M5/M15/H1/H4), a mi indikátoraink és
jelölőink, -tól/-ig kijelölés.

3. lépcső: **kattintásra belépő** (`Add BUY` / `Add SELL`), `Add BE`,
`Start építés`, és a `Futtat`, ami a megrajzolt forgatókönyvet a VALÓDI motoron
futtatja végig. Plusz a **lejátszás**: `Play` / `Pause`, léptetés, sebesség,
visszatekerés, BID/ASK vonal, és a „csak eddig látszik" kapcsoló.

⚠ A LEJÁTSZÁS NEM FUTTATJA A MOTORT LÉPÉSENKÉNT. Egy időkurzor halad a
szakaszon; a jelölőket menet közben rakod le, és a `Futtat` a végén ugyanúgy a
`lab_scenario.futtat()`-ot hívja. Ha a lejátszás maga „kereskedne", az egy
MÁSODIK végrehajtási út lenne — pontosan az, amitől a projekt már többször
megszenvedett. A `Play` a LÁTVÁNYT animálja, a döntés a tiéd, a végrehajtás a
motoré.

⚠ MIÉRT KELL A „CSAK EDDIG LÁTSZIK". Enélkül a lejátszás alatt végig látod a
jövőt, és az egész csak animáció. A jövő elrejtése az EGYETLEN dolog, ami a
`Play`-t valódi döntés-teszteléssé teszi — onnantól nem a menedzsmentet
próbálod, hanem azt, hogy felismered-e a helyzetet ELŐRE.

⚠ A FUTTATÁS NEM ITT TÖRTÉNIK. A gombok csak egy forgatókönyv-szótárat építenek,
és azt a MEGLÉVŐ `tools/lab_scenario.futtat()`-nak adják át — ugyanannak, ami a
JSON-fájlt is futtatja, és ami a `trading.backtest.run_pair`-t hívja. Így a
chartról indított kísérlet és a fájlból indított BITRE ugyanaz; nincs második
végrehajtási út, ami elcsúszhatna.

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

# A stratégia-választó „nincs" eleme: tiszta chart, jelölők nélkül.
NINCS_STRAT = "— nincs —"


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
    if not strategy_name:
        # ⚠ „nincs stratégia": TISZTA chart, a rajz-objektumok nélkül. A
        # gyertyák ugyanabból a parquetből jönnek — csak a jelölők maradnak el.
        df15, df1 = bt.load_data(symbol)
        if df15 is None or df1 is None:
            return None, [], (f"nincs letöltött adat a(z) {symbol} párhoz — "
                              f"`python main.py download`")
        chart = _vag(chart_barok(df1, df15, tf_perc), tol, ig)
        if chart is None or len(chart) < 2:
            return None, [], "a megadott időszakra nincs elég gyertya"
        return chart, [], ""
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

        # ── A FORGATÓKÖNYV-GOMBOK ────────────────────────────────────
        gs = tk.Frame(self.root)
        gs.pack(fill="x", padx=8, pady=(0, 4))
        self._mod = tk.StringVar(value="")
        tk.Label(gs, text="Kattintás:").pack(side="left")
        for ertek, cimke in (("BUY", "Add BUY"), ("SELL", "Add SELL"),
                             ("BE", "Add BE")):
            tk.Radiobutton(gs, text=cimke, value=ertek, variable=self._mod,
                           indicatoron=False, padx=8,
                           width=9).pack(side="left", padx=2)
        tk.Radiobutton(gs, text="—", value="", variable=self._mod,
                       indicatoron=False, padx=8, width=4).pack(side="left",
                                                                padx=(2, 12))
        self._epites = tk.BooleanVar(value=False)
        tk.Checkbutton(gs, text="Start építés", variable=self._epites).pack(
            side="left", padx=(0, 12))
        tk.Button(gs, text="Futtat", command=self.futtat, width=10).pack(
            side="left", padx=2)
        tk.Button(gs, text="Töröl", command=self.torol, width=8).pack(
            side="left", padx=2)
        tk.Button(gs, text="JSON mentés", command=self.ment).pack(
            side="left", padx=(12, 2))
        tk.Label(gs, text="  (lerakás után: húzd a jelölőt · jobb gomb: törli)",
                 fg="#888").pack(side="left")

        # ── LEJÁTSZÓ ─────────────────────────────────────────────────
        ls = tk.Frame(self.root)
        ls.pack(fill="x", padx=8, pady=(0, 4))
        self._play_gomb = tk.Button(ls, text="▶ Play", width=9,
                                    command=self.play_szunet)
        self._play_gomb.pack(side="left", padx=2)
        for cimke, lepes in (("⏮", -1000), ("◀◀", -50), ("◀", -1),
                             ("▶", 1), ("▶▶", 50), ("⏭", 1000)):
            tk.Button(ls, text=cimke, width=4,
                      command=lambda n=lepes: self.leptet(n)).pack(side="left")
        tk.Label(ls, text="  sebesség").pack(side="left")
        self._sebesseg = tk.DoubleVar(value=4.0)     # gyertya / másodperc
        tk.Scale(ls, from_=0.5, to=40.0, resolution=0.5, orient="horizontal",
                 variable=self._sebesseg, length=140,
                 showvalue=True).pack(side="left")
        self._csak_eddig = tk.BooleanVar(value=True)
        tk.Checkbutton(ls, text="csak eddig látszik",
                       variable=self._csak_eddig,
                       command=self._rajzol).pack(side="left", padx=(12, 4))
        self._bidask = tk.BooleanVar(value=True)
        tk.Checkbutton(ls, text="BID/ASK", variable=self._bidask,
                       command=self._rajzol).pack(side="left")
        tk.Button(ls, text="Lejátszás vége", command=self.kurzor_le).pack(
            side="left", padx=(12, 2))

        self._allapot = tk.Label(self.root, text="", anchor="w", fg="#666")
        self._allapot.pack(fill="x", padx=10)
        self._eredmeny_cimke = tk.Label(self.root, text="", anchor="w",
                                        fg="#046", justify="left")
        self._eredmeny_cimke.pack(fill="x", padx=10)

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
        self._vaszon.mpl_connect("button_press_event", self._kattintas)
        # ⚠ A BEÉPÍTETT ESZKÖZTÁR NAGYÍTÁSA KÉNYELMETLEN (mód-váltás, keretes
        # kijelölés). A görgő-nagyítás és a húzás az, amit egy chartnál
        # megszokott az ember — és nem kell hozzá új függőség.
        self._vaszon.mpl_connect("scroll_event", self._gorgo)
        self._vaszon.mpl_connect("button_press_event", self._huzas_kezd)
        self._vaszon.mpl_connect("motion_notify_event", self._huzas)
        self._vaszon.mpl_connect("button_release_event", self._huzas_vege)
        self._huzas_x = None     # a chart görgetése
        self._fogott = None      # a MEGFOGOTT jelölő ("be"|"belepo", index)
        # ── A 3. LÉPCSŐ ÁLLAPOTA ─────────────────────────────────────
        # ⚠ IDŐBEN tároljuk, nem bar-indexben: az idősík-váltás átszámozza az
        # indexeket, az időpont viszont ugyanaz marad. Enélkül egy M15-ön
        # kattintott belépő M1-re váltva máshova ugrana.
        # ⚠ A CHART-MEZŐK MÁR ITT LÉTEZZENEK. A `betolt()` legelső dolga a
        # látott időszak elmentése (`_lathato_ido`), ami a `self._chart`-ot
        # olvassa — az első hívásnál viszont az még nem jött létre, és az ablak
        # `AttributeError`-ral el sem indult. A unit-tesztek ezt nem fogták meg:
        # azok `__new__`-val építik az objektumot és kézzel állítják a mezőket.
        # UI-változtatás után EL KELL INDÍTANI az ablakot.
        self._chart = None          # a kirajzolt gyertyák (DataFrame)
        self._objs = []             # a stratégia rajz-objektumai
        self._tengely = None        # epoch ↔ bar-index leképezés
        self._belepok = []          # [(pd.Timestamp, "BUY"|"SELL"), …]
        self._be_ido = None         # a kézi breakeven időpontja
        self._eredmeny = None       # a legutóbbi futtatás kimenete
        # ── LEJÁTSZÁS ────────────────────────────────────────────────────
        self._kurzor = None         # a lejátszás helye (bar-index) vagy None
        self._jatszik = False
        self._utem_id = None        # a Tk `after` azonosítója
        self._strat_lista()
        self.betolt()

    def _strat_nev(self) -> str:
        """A kiválasztott stratégia neve — a „nincs" üres sztringre fordul."""
        n = self._strat.get()
        return "" if n == NINCS_STRAT else n

    # ── LEJÁTSZÁS ────────────────────────────────────────────────────
    def play_szunet(self) -> None:
        """`Play` / `Pause`. Az első indításnál a kurzor a szakasz elejére áll."""
        if self._chart is None or len(self._chart) < 2:
            return
        self._jatszik = not self._jatszik
        if self._jatszik and self._kurzor is None:
            self._kurzor = 0
        self._play_gomb.config(text="⏸ Pause" if self._jatszik else "▶ Play")
        if self._jatszik:
            self._utem()
        elif self._utem_id is not None:
            try:
                self.root.after_cancel(self._utem_id)
            except Exception:
                pass
            self._utem_id = None

    def _utem(self) -> None:
        """Egy lejátszási lépés. ⚠ A Tk `after`-jével, NEM `sleep`-pel: a
        `sleep` befagyasztaná az ablakot, és a gombok sem működnének közben."""
        if not self._jatszik or self._chart is None:
            return
        if self._kurzor is None or self._kurzor >= len(self._chart) - 1:
            self._jatszik = False
            self._play_gomb.config(text="▶ Play")
            return
        self._kurzor += 1
        self._rajzol()
        _mp = max(0.02, 1.0 / max(0.5, float(self._sebesseg.get())))
        self._utem_id = self.root.after(int(_mp * 1000), self._utem)

    def leptet(self, n: int) -> None:
        """Léptetés/visszatekerés. A lejátszást megállítja — különben a
        kézi léptetés és az ütem egymás ellen dolgozna."""
        if self._chart is None or len(self._chart) < 2:
            return
        self._jatszik = False
        self._play_gomb.config(text="▶ Play")
        alap = self._kurzor if self._kurzor is not None else 0
        self._kurzor = max(0, min(len(self._chart) - 1, alap + int(n)))
        self._rajzol()

    def kurzor_le(self) -> None:
        """A lejátszás vége: nincs kurzor, a teljes chart látszik."""
        self._jatszik = False
        self._play_gomb.config(text="▶ Play")
        self._kurzor = None
        self._rajzol()

    def _rajzol_kurzor(self) -> None:
        """Az időkurzor, a BID/ASK vonal, és a jövő elrejtése."""
        if self._kurzor is None or self._chart is None:
            return
        i = int(self._kurzor)
        x = i - 0.5 + 1.0                       # a gyertya jobb széle: „eddig"
        self._ax.axvline(x, color=szin("yellow"), linewidth=1.4, alpha=0.9,
                         zorder=10)
        sor = self._chart.iloc[i]
        # ── BID / ASK ────────────────────────────────────────────────────
        # ⚠ A SPREAD AZ ADATBÓL JÖN (`avg_spread`), nem találjuk ki. Ugyanaz az
        # oszlop, amivel a backtest is számol — különben a labor mást mutatna,
        # mint amit a motor fizet.
        if self._bidask.get():
            bid = float(sor["close"])
            _sp = float(sor.get("avg_spread", 0.0) or 0.0)
            ask = bid + _sp
            for ar, sz, cim in ((bid, "blue", "BID"), (ask, "orange", "ASK")):
                self._ax.axhline(ar, color=szin(sz), linewidth=0.9,
                                 linestyle="--", alpha=0.8, zorder=10)
                self._ax.annotate(f"{cim} {self._ar_szoveg(ar)}",
                                  (self._ax.get_xlim()[1], ar),
                                  color=szin(sz), fontsize=8, ha="right",
                                  va="bottom", zorder=11)
        # ── A JÖVŐ ELREJTÉSE ─────────────────────────────────────────────
        # ⚠ Nem a gyertyákat hagyjuk ki (az újrarajzolást drágítaná), hanem
        # letakarjuk — így a lejátszás gyors marad.
        if self._csak_eddig.get():
            _a, _b = self._ax.get_xlim()
            if _b > x:
                self._ax.axvspan(x, _b, color="#101010", alpha=0.93, zorder=9)

    def _ar_szoveg(self, ar: float) -> str:
        """Ár a pár tizedeseivel. ⚠ `%.5g` NEM: nagy szinten exponenciálisra vált
        és a szintek egyformává válnak (ez a projektben már háromszor elsült)."""
        try:
            import math
            pc = (self.cfg.get("pairs") or {}).get(self._sym.get()) or {}
            ps = float(pc.get("point_size") or 0.0)
            tiz = 0 if ps <= 0 else min(8, max(0, int(round(-math.log10(ps)))))
            return f"{float(ar):.{tiz}f}"
        except (TypeError, ValueError, OverflowError):
            return f"{float(ar):.5f}"

    def _rajzol(self) -> None:
        """Újrarajzolás ADAT-BETÖLTÉS nélkül — a terv változásakor.

        ⚠ Nem a `betolt()`-öt hívjuk: az újraszámolná a mély ablakot és a
        rajz-objektumokat (másodpercek), miközben csak egy vonalat kell kitenni."""
        if self._chart is None:
            return
        self._ax.clear()
        self._ax_sav.clear()
        gyertyak(self._ax, self._chart)
        objektumok_rajza(self._ax, self._objs, self._tengely)
        allapot_sav(self._ax_sav, self._objs, self._tengely)
        self._rajzol_terv()
        self._rajzol_kurzor()
        self._fig.tight_layout()
        self._vaszon.draw()

    def _strat_lista(self) -> None:
        """A PÁR saját engedélyezett stratégiái — ugyanaz a halmaz, amit a motor
        futtat. ⚠ Nem az összes létező: egy máshol nem futó stratégia rajza
        félrevezető lenne (a labor azt mutassa, ami élesben történne)."""
        from strategy import enabled_strategy_names
        nevek = list(enabled_strategy_names(self.cfg, self._sym.get()))
        if not nevek:
            from strategy import available_strategy_names
            nevek = list(available_strategy_names(self.cfg))
        # ⚠ „nincs": a stratégia jelölői nélküli, TISZTA chart. A felhasználó
        # kérése — a saját belépőit néha a stratégia rajza nélkül akarja látni.
        nevek = [NINCS_STRAT] + nevek
        self._strat_box["values"] = nevek
        if self._strat.get() not in nevek:
            self._strat.set(nevek[0] if nevek else "")

    def _lathato_ido(self):
        """A jelenleg LÁTOTT x-tartomány IDŐBEN — az idősík-váltáshoz.

        ⚠ Idősíkot váltva a bar-index MÁST jelent (M15-ön 96 gyertya egy nap,
        M1-en 1440). Ha a nézetet indexben őriznénk, a váltás után teljesen más
        szakaszra ugranánk; időben őrizve ugyanaz a szakasz marad, csak
        finomabb/durvább felbontásban."""
        if self._chart is None:
            return None
        try:
            a, b = self._ax.get_xlim()
        except Exception:
            return None
        ta, tb = self.ido_x(a), self.ido_x(b)
        return (ta, tb) if (ta is not None and tb is not None) else None

    def _allitsd_ido(self, tart) -> None:
        """A mentett IDŐ-tartomány visszaállítása az ÚJ idősíkon."""
        if tart is None or self._chart is None or self._tengely is None:
            return
        xa = self._tengely.hol(int(tart[0].timestamp()))
        xb = self._tengely.hol(int(tart[1].timestamp()))
        # A széleken a `hol()` `None`-t ad (kívül esik) — akkor a szélre húzzuk.
        xa = 0 - 0.5 if xa is None else xa
        xb = (len(self._chart) - 0.5) if xb is None else xb
        if xb > xa:
            self._ax.set_xlim(xa, xb)
            self._y_illesztes(xa, xb)

    def _y_illesztes(self, xa: float, xb: float) -> None:
        """Az ÁR-tengely a LÁTHATÓ szakaszra. Enélkül egy kinagyított részlet
        lapos vonallá préselődne a teljes szakasz ár-tartományában."""
        if self._chart is None:
            return
        i0 = max(0, int(np.floor(xa + 0.5)))
        i1 = min(len(self._chart), int(np.ceil(xb + 0.5)) + 1)
        if i1 - i0 < 2:
            return
        _l = float(self._chart["low"].iloc[i0:i1].min())
        _h = float(self._chart["high"].iloc[i0:i1].max())
        _r = (_h - _l) * 0.06 or 1.0
        self._ax.set_ylim(_l - _r, _h + _r)

    def _kurzor_ido(self):
        """A kurzor IDŐPONTJA — az idősík-váltáshoz.

        ⚠ Ugyanaz a csapda, mint a nézetnél: bar-indexben őrizve a váltás után
        máshova ugrana (M15-ön 96 gyertya egy nap, M1-en 1440)."""
        if self._kurzor is None or self._chart is None:
            return None
        i = max(0, min(len(self._chart) - 1, int(self._kurzor)))
        return self._chart.index[i]

    def _kurzor_vissza(self, t) -> None:
        if t is None or self._chart is None:
            self._kurzor = None
            return
        poz = self._chart.index.get_indexer([t], method="nearest")
        self._kurzor = int(poz[0]) if len(poz) and poz[0] >= 0 else None

    def betolt(self) -> None:
        _elozo_ido = self._lathato_ido()
        _kurzor_t = self._kurzor_ido()
        self._allapot.config(text="betöltés…", fg="#666")
        self.root.update_idletasks()
        try:
            chart, objs, uzenet = keszit(
                self._sym.get(), self._strat_nev(), self._tf.get(),
                self._tol.get() or None, self._ig.get() or None, cfg=self.cfg)
        except Exception as ex:
            # ⚠ KIMONDJUK. Egy labor, ami csak üres chartot mutat, használhatatlan.
            log.exception("a chart betöltése elbukott")
            self._allapot.config(text=f"HIBA: {type(ex).__name__}: {ex}",
                                 fg="#c00")
            return
        self._ax.clear()
        self._ax_sav.clear()
        self._chart = self._tengely = None
        if chart is None:
            self._allapot.config(text=f"HIBA: {uzenet}", fg="#c00")
            self._vaszon.draw()
            return
        self._chart, self._objs = chart, objs
        self._tengely = Idotengely(chart.index)
        gyertyak(self._ax, chart)
        tengely = self._tengely
        db = objektumok_rajza(self._ax, objs, tengely)
        allapot_sav(self._ax_sav, objs, tengely)
        self._rajzol_terv()
        self._ax.set_title(
            f"{self._sym.get()} / {self._strat.get()}  "
            f"{dict(IDOSIKOK).get(self._tf.get(), self._tf.get())}")
        # Az időcímkék a gyertya-indexhez.
        _n = max(1, len(chart) // 12)
        self._ax_sav.set_xticks(list(range(0, len(chart), _n)))
        self._ax_sav.set_xticklabels(
            [t.strftime("%m-%d %H:%M") for t in chart.index[::_n]],
            rotation=45, fontsize=7, ha="right")
        self._kurzor_vissza(_kurzor_t)
        self._rajzol_kurzor()
        self._allitsd_ido(_elozo_ido)
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

    # ── 3. LÉPCSŐ: forgatókönyv-építés a charton ─────────────────────
    def _kattintas(self, ev) -> None:
        """Kattintás a charton: belépő vagy BE az adott gyertyán.

        ⚠ CSAK AKKOR, HA VAN AKTÍV MÓD. A nagyítás/görgetés is kattintás — ha
        minden kattintás belépőt tenne, a chart használhatatlan lenne."""
        mod = self._mod.get()
        if not mod or ev.inaxes is not self._ax or ev.xdata is None:
            return
        if self._chart is None or len(self._chart) == 0:
            return
        t = self.ido_x(float(ev.xdata))
        if t is None:
            return
        if ev.button == 3:                       # jobb gomb: TÖRLÉS
            self._torol_kozeli(t)
            return
        if mod == "BE":
            self._be_ido = t
        else:
            self._belepok.append((t, mod))
        # ⚠ LERAKÁS UTÁN AZONNAL FOGD-ÉS-VIDD. A felhasználó kérése
        # (2026-09-03): „általában leteszem és beigazítom". Ha a mód aktív
        # maradna, a következő kattintás egy ÚJABB belépőt tenne le ahelyett,
        # hogy a meglévőt igazítaná — és a chart tele lenne véletlen jelölőkkel.
        self._mod.set("")
        self._eredmeny = None          # az új terv érvényteleníti a régi futást
        self._rajzol()

    def _gorgo(self, ev) -> None:
        """Görgő = nagyítás az EGÉR KÖRÜL (nem a chart közepére)."""
        if ev.inaxes is not self._ax or ev.xdata is None or self._chart is None:
            return
        a, b = self._ax.get_xlim()
        f = 0.8 if ev.button == "up" else 1.25
        uj_a = ev.xdata - (ev.xdata - a) * f
        uj_b = ev.xdata + (b - ev.xdata) * f
        if uj_b - uj_a < 5:                      # ne lehessen 5 gyertya alá
            return
        self._ax.set_xlim(uj_a, uj_b)
        self._y_illesztes(uj_a, uj_b)
        self._vaszon.draw_idle()

    # A jelölő megfogásának tűrése CHART-KOORDINÁTÁBAN (gyertya). A nézettel
    # együtt kell tágulnia: kinagyítva egy gyertya sok képpont, kicsinyítve
    # kevés — fix gyertya-tűrés mellett kicsinyítve képtelenség lenne eltalálni.
    FOGAS_TURES_ARANY = 0.012          # a látható szélesség ennyied része

    def _foghato(self, x: float):
        """Melyik jelölő van a `x` közelében? `("be", None)` | `("belepo", i)`."""
        if self._chart is None or self._tengely is None:
            return None
        a, b = self._ax.get_xlim()
        tures = max(0.5, abs(b - a) * self.FOGAS_TURES_ARANY)
        jelolt = []
        if self._be_ido is not None:
            _x = self._tengely.hol(int(self._be_ido.timestamp()))
            if _x is not None:
                jelolt.append((abs(_x - x), ("be", None)))
        for i, (t, _d) in enumerate(self._belepok):
            _x = self._tengely.hol(int(t.timestamp()))
            if _x is not None:
                jelolt.append((abs(_x - x), ("belepo", i)))
        if not jelolt:
            return None
        tav, mit = min(jelolt, key=lambda p: p[0])
        return mit if tav <= tures else None

    def _huzas_kezd(self, ev) -> None:
        """Bal gomb: MEGFOGJA a közeli jelölőt, különben görgeti a chartot.

        ⚠ Csak akkor, ha NINCS aktív kattintás-mód — különben a belépő-lerakás
        és a görgetés ütné egymást."""
        if (ev.inaxes is not self._ax or ev.button != 1
                or self._mod.get() or ev.xdata is None):
            return
        self._fogott = self._foghato(float(ev.xdata))
        if self._fogott is None:
            self._huzas_x = float(ev.xdata)

    def _huzas(self, ev) -> None:
        if ev.inaxes is not self._ax or ev.xdata is None:
            return
        # ── A MEGFOGOTT JELÖLŐ mozgatása ─────────────────────────────────
        if self._fogott is not None:
            t = self.ido_x(float(ev.xdata))
            if t is None:
                return
            mit, i = self._fogott
            if mit == "be":
                if t == self._be_ido:
                    return                 # ugyanaz a perc — ne rajzoljunk újra
                self._be_ido = t
            else:
                if t == self._belepok[i][0]:
                    return
                self._belepok[i] = (t, self._belepok[i][1])
            # ⚠ CSAK PERC-VÁLTÁSKOR rajzolunk újra. Egérmozgásonként a teljes
            # chart (gyertyák + rajz-objektumok) újrarajzolása akadozna.
            self._eredmeny = None
            self._rajzol()
            return
        # ── Görgetés ─────────────────────────────────────────────────────
        if self._huzas_x is None:
            return
        d = self._huzas_x - float(ev.xdata)
        a, b = self._ax.get_xlim()
        self._ax.set_xlim(a + d, b + d)
        self._y_illesztes(a + d, b + d)
        self._vaszon.draw_idle()

    def _huzas_vege(self, ev) -> None:
        self._huzas_x = None
        self._fogott = None

    def ido_x(self, x: float):
        """Chart-koordináta → IDŐPONT, a gyertyán BELÜL is.

        ⚠ EZ VOLT A „FURASÁG" (2026-09-03). Korábban a gyertya NYITÓ idejét
        adtuk vissza (`index[round(x)]`), tehát M15-ön bárhova kattintottál a
        gyertyán belül, a belépő a gyertya elejére ugrott — M1-en viszont a
        percre. Ugyanaz a vizuális pont így akár 15 perccel (H4-en 4 órával)
        máshova került, holott a motor M1-en hajt végre.

        Most a TÖRT pozíciót is használjuk: a gyertya [i-0.5, i+0.5) sávot
        foglal el, a benne mért arány pedig a gyertyán belüli időt adja. Így a
        kattintás minden idősíkon UGYANOTT van."""
        if self._chart is None or len(self._chart) < 2:
            return None
        n = len(self._chart)
        i = int(np.floor(x + 0.5))
        if not (0 <= i < n):
            return None
        arany = float(x + 0.5 - i)               # 0..1 a gyertyán belül
        arany = max(0.0, min(0.999, arany))
        idx = self._chart.index
        koz = (idx[1] - idx[0]) if n > 1 else pd.Timedelta(minutes=1)
        # ⚠ EGÉSZ MÁSODPERCRE ELŐBB, PERCRE UTÁNA. A közvetlen
        # `(idx[i] + koz*arany).floor("min")` lebegőpontos hibát hoz: M15-ön a
        # 0,53333 × 15 perc = 7,99999… percből a `floor` 7-et csinál, tehát
        # ugyanaz a kattintás M1-en 01:08-at, M15-ön 01:07-et adott. A
        # másodperc-kerekítés ezt elrendezi, a percre vágás pedig azért marad,
        # mert a motor M1-es gyertyákon dolgozik — finomabb felbontásnak nincs
        # értelme.
        _mp = int(round(koz.total_seconds() * arany))
        return (idx[i] + pd.Timedelta(seconds=_mp)).floor("min")

    def _torol_kozeli(self, t) -> None:
        """A legközelebbi jelölő törlése (jobb egérgomb).

        ⚠ A `Töröl` gomb MINDENT kiürít; egyetlen elrontott kattintás miatt az
        egész tervet újra kellene rajzolni."""
        if self._be_ido is not None and self._belepok:
            _be_tav = abs((self._be_ido - t).total_seconds())
            _e_tav = min(abs((x - t).total_seconds()) for x, _ in self._belepok)
            if _be_tav <= _e_tav:
                self._be_ido = None
                self._eredmeny = None
                self._rajzol()
                return
        if self._belepok:
            _i = min(range(len(self._belepok)),
                     key=lambda k: abs((self._belepok[k][0] - t).total_seconds()))
            self._belepok.pop(_i)
        elif self._be_ido is not None:
            self._be_ido = None
        self._eredmeny = None
        self._rajzol()

    def torol(self) -> None:
        self._belepok.clear()
        self._be_ido = None
        self._eredmeny = None
        self._rajzol()

    def _forgatokonyv(self) -> dict:
        """A megrajzolt terv → forgatókönyv-szótár (ugyanaz az alak, mint a JSON).

        ⚠ EGY ALAK, KÉT BEMENET. A chartról és a fájlból ugyanaz a szótár megy a
        `lab_scenario.futtat()`-ba — így a „kattintva kipróbálom, aztán elmentem
        és megismétlem" út végig ugyanazt adja."""
        _f = self._tol.get() or (str(self._chart.index[0])[:16]
                                 if self._chart is not None else "")
        _i = self._ig.get() or (str(self._chart.index[-1])[:16]
                                if self._chart is not None else "")
        return {
            "symbol": self._sym.get(),
            "strategy": self._strat_nev(),
            "from": _f, "to": _i,
            "entries": [{"time": str(t)[:16], "direction": d}
                        for t, d in sorted(self._belepok)],
            "breakeven_at": (str(self._be_ido)[:16] if self._be_ido else None),
            "rr_preset": "off",
            "build": bool(self._epites.get()),
            "balance": 1000.0,
            "use_strategy_signals": False,
            "exec_gates": False,
        }

    def ment(self) -> None:
        """A terv kimentése JSON-ba — onnantól a parancssoros úton is fut."""
        from tkinter import filedialog, messagebox
        import json as _json
        ut = filedialog.asksaveasfilename(
            defaultextension=".json", initialfile="fk.json",
            filetypes=[("JSON", "*.json")], parent=self.root)
        if not ut:
            return
        try:
            Path(ut).write_text(_json.dumps(self._forgatokonyv(),
                                            ensure_ascii=False, indent=2),
                                encoding="utf-8")
            self._allapot.config(text=f"mentve: {ut}", fg="#666")
        except OSError as ex:
            messagebox.showerror("Mentés", str(ex), parent=self.root)

    def futtat(self) -> None:
        """A megrajzolt forgatókönyv lefuttatása a VALÓDI motoron."""
        if not self._belepok:
            self._eredmeny_cimke.config(
                text="Előbb tegyél le legalább egy belépőt "
                     "(Add BUY / Add SELL, majd kattints a chartra).",
                fg="#a60")
            return
        self._eredmeny_cimke.config(text="futtatás…", fg="#666")
        self.root.update_idletasks()
        try:
            from tools.lab_scenario import futtat as _futtat
            self._eredmeny = _futtat(self._forgatokonyv())
        except SystemExit as ex:
            # ⚠ A `lab_scenario._hiba` SystemExit-tel áll meg (parancssori
            # eszköz). Az ablakot ez megölné — itt üzenetté váltjuk.
            self._eredmeny = None
            self._eredmeny_cimke.config(text=f"HIBA: {ex}", fg="#c00")
            return
        except Exception as ex:
            log.exception("a forgatókönyv futtatása elbukott")
            self._eredmeny = None
            self._eredmeny_cimke.config(
                text=f"HIBA: {type(ex).__name__}: {ex}", fg="#c00")
            return
        self._rajzol()
        self._osszegzes()

    def _osszegzes(self) -> None:
        res = (self._eredmeny or {}).get("res")
        if res is None:
            return
        zart = [t for t in res.closed if t.close_time is not None]
        if not zart:
            self._eredmeny_cimke.config(
                text="Egyetlen kötés sem született ezen a terven.", fg="#a60")
            return
        _r = 0.0
        for t in zart:
            try:
                _r += t.pnl_usd / t.risk_usd if t.risk_usd else 0.0
            except (TypeError, ZeroDivisionError):
                pass
        _pnl = sum(t.pnl_usd for t in zart)
        _veg = " · ".join(f"{str(t.close_time)[11:16]} {t.status}" for t in zart[:6])
        self._eredmeny_cimke.config(
            text=(f"{len(zart)} lezárt kötés · összesen {_pnl:+.2f} · {_r:+.2f} R"
                  + (f"   |   {_veg}" if _veg else "")), fg="#046")

    def _rajzol_terv(self) -> None:
        """A megrajzolt (még nem futtatott) terv jelölői + a futtatás kötései."""
        if self._chart is None or self._tengely is None:
            return
        for t, d in self._belepok:
            x = self._tengely.hol(int(t.timestamp()))
            if x is None:
                continue
            self._ax.axvline(x, color=szin("lime" if d == "BUY" else "magenta"),
                             linewidth=1.6, alpha=0.9, zorder=7)
            self._ax.annotate(d, (x, self._ax.get_ylim()[1]),
                              color=szin("lime" if d == "BUY" else "magenta"),
                              fontsize=8, ha="center", va="top", zorder=8)
        if self._be_ido is not None:
            x = self._tengely.hol(int(self._be_ido.timestamp()))
            if x is not None:
                self._ax.axvline(x, color=szin("cyan"), linewidth=1.2,
                                 linestyle=":", zorder=7)
                self._ax.annotate("BE", (x, self._ax.get_ylim()[1]),
                                  color=szin("cyan"), fontsize=8, ha="center",
                                  va="top", zorder=8)
        # ── A FUTTATÁS eredménye: a valódi kötések a charton ──────────────
        res = (self._eredmeny or {}).get("res")
        for t in (getattr(res, "trades", None) or []):
            x1 = self._tengely.hol(int(t.open_time.timestamp()))
            x2 = (self._tengely.hol(int(t.close_time.timestamp()))
                  if t.close_time is not None else None)
            if x1 is None:
                continue
            self._ax.plot([x1], [t.open_price], marker="o", color=szin("white"),
                          markersize=7, zorder=9)
            if x2 is not None:
                _ny = (t.pnl_usd or 0) > 0
                self._ax.plot([x1, x2], [t.open_price, t.close_price],
                              color=szin("green" if _ny else "red"),
                              linewidth=2.0, alpha=0.9, zorder=9)

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

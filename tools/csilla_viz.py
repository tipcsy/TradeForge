"""CSILLA — A SZABÁLY KIRAJZOLÁSA az MT5 chartra (TradeForgeViz).

A felhasználó kérése: „nem tudom, mit számolsz pontosan — rajzold ki, hogy
tudjam ellenőrizni". Ez az eszköz a `strategies/csilla_rules` FÜGGVÉNYEIT
hívja (nem másolat), tehát amit a charton látsz, az pontosan az, amit a
stratégia számol.

LÉPÉSENKÉNT rajzol (`--lepes`), mert a szabályt lépésről lépésre beszéljük meg:

  1  FELSŐ IDŐSÍK — a swing-pontok, a belőlük lett szintek és a törések:
     * minden IGAZOLT csúcs/völgy: kis jelölő a gyertyán (szürke), a felirat
       megmondja az árat, a gyertya idejét és azt, MIKOR vált igazolttá;
     * a TÖRT szint: vízszintes vonal a swing gyertyájától a törésig (kék);
     * a törés: függőleges (sötét-arany) + felirat (irány, ár, folytatás/
       fordulat, a törő gyertya ideje és zárása).
  2  A TELJES LÁNC, ahogy MAGA A STRATÉGIA rajzolja (`CsillaStrategy.visual_objects`)
     — ugyanaz a hívás, mint élesben: törés + tört szint, pipa (2. jelzés), és
     minden belépő a stopjával. Ez az, amit az MT5-ön élőben is látni fogsz.

⚠ 2026-09-22-ig ez a D1/W1 szint-réteget rajzolta. Az kikerült a szabályból
(nem a módszer volt, hanem az én bevezetésem); a helyén a páros olvasat áll:
a felső idősík a SAJÁT utolsó igazolt swingjét töri.

Futtatás:
    python tools/csilla_viz.py --symbol Ger40 --from 2026-01-23 --to 2026-01-28
    python tools/csilla_viz.py --symbol Ger40 --from 2026-01-23 --to 2026-01-28 --k-hi 2
    python tools/csilla_viz.py --symbol Ger40 --from ... --to ... --dry   (csak kiír)

⚠ A `--to` napja MÉG BELEFÉR (a nap végéig rajzol).
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "research"))

import lab                                      # noqa: E402
from strategies import csilla_rules as sw       # noqa: E402
from strategy import visual as viz              # noqa: E402

STRAT = "csilla"
_TF_LABEL = {1: "M1", 5: "M5", 15: "M15", 30: "M30", 60: "H1", 240: "H4"}


def _ts(t) -> int:
    return int(pd.Timestamp(t).timestamp())


def _ar(x: float, point_size: float) -> str:
    """Ár a pár TIZEDESEIVEL. ⚠ Soha nem `%g`: az a nagy indexeken
    exponenciálisra vált, a devizán meg levágja a tizedeseket."""
    tiz = min(8, max(0, int(round(-math.log10(point_size))))) if point_size > 0 else 2
    return f"{float(x):.{tiz}f}"


def _lanc_objektumok(symbol: str, t_from: str, t_to: str, P: dict) -> tuple[list, str]:
    """A 2. lépés: a STRATÉGIA saját rajza. Nem másolat — a `visual_objects`-et
    hívjuk, ugyanazzal a két kerettel, amit a motor is ad neki."""
    from strategy import get_strategy_by_name
    from strategy.base import MarketData
    st = get_strategy_by_name("csilla")
    m1 = lab.load_m1(symbol)
    t0 = pd.Timestamp(t_from, tz="UTC")
    t1 = pd.Timestamp(t_to, tz="UTC") + pd.Timedelta(days=1)
    # ⚠ A FELSŐ keret TÖBBET lát az ablaknál (a szerkezet onnan jön), az ALSÓ
    # viszont csak az ablakot — különben a rajz tele lenne régi belépőkkel.
    hi = sw.resample(m1[m1.index < t1], P["hi_tf"])
    lo = sw.resample(m1[(m1.index >= t0 - pd.Timedelta(days=2)) & (m1.index < t1)],
                     P["lo_tf"])
    ps = float(lab.PAIRS[symbol]["point_size"])
    md = MarketData(symbol=symbol, params={"symbol": symbol, "point_size": ps,
                                           "atr_period": 14,
                                           "backtest_spread_points": 213},
                    bars={_TF_LABEL[P["hi_tf"]]: hi, _TF_LABEL[P["lo_tf"]]: lo})
    objs = st.visual_objects(md)
    n_be = sum(1 for o in objs if str(getattr(o, "name", "")).startswith("m1sig_"))
    n_tor = sum(1 for o in objs if str(getattr(o, "name", "")).startswith("cs_brk_"))
    n_pipa = sum(1 for o in objs if str(getattr(o, "name", "")).startswith("cs_pipa"))
    return objs, (f"{symbol} {t_from}->{t_to}  A STRATEGIA sajat rajza: "
                  f"{n_tor} tores, {n_pipa} pipa, {n_be} belepo "
                  f"({len(objs)} objektum)")


def build_objects(symbol: str, t_from: str, t_to: str, tf_pair: str = "H1-M15",
                  k_hi: int | None = None, lepes: int = 1) -> tuple[list, str]:
    lab._CACHE.clear()
    m1 = lab.load_m1(symbol)
    P = dict(sw.DEFAULTS, tf_pair=tf_pair)
    if k_hi:
        P["k_hi"] = int(k_hi)
    P = sw.with_tf_pair(P)
    if lepes >= 2:
        return _lanc_objektumok(symbol, t_from, t_to, P)
    hi_min = P["hi_tf"]
    hi = sw.resample(m1, hi_min)
    ps = float(lab.PAIRS[symbol]["point_size"])

    t0 = pd.Timestamp(t_from, tz="UTC")
    t1 = pd.Timestamp(t_to, tz="UTC") + pd.Timedelta(days=1)
    # ⚠ A SZÁMÍTÁS TÖBBET LÁT, MINT A RAJZ: a swingek és a törések a TELJES
    # előzményből jönnek (különben az ablak első gyertyáinál nem volna mihez
    # viszonyítani), és csak a KIRAJZOLÁST szűrjük az ablakra. Enélkül a kép
    # mást mutatna, mint amit a stratégia élesben lát.
    evs = sw.own_swing_events(hi, P)
    h = hi["high"].to_numpy(float)
    l = hi["low"].to_numpy(float)
    pc, pv = sw.pivots(h, l, P["k_hi"])

    objs: list = []
    n_sw = n_ev = 0
    tf_nev = _TF_LABEL.get(hi_min, f"{hi_min}p")

    # ── 1a. az IGAZOLT swing-pontok (amiket a k_hi kiválaszt) ──────────────
    for j in np.flatnonzero(pc | pv):
        t = hi.index[j]
        if not (t0 <= t < t1):
            continue
        # az igazolás ideje: a pivot utáni k_hi-edik gyertya ZÁRÁSA — ettől
        # kezdve „létezik" a swing, addig nem szabad rá hivatkozni.
        t_conf = hi.index[min(len(hi) - 1, j + P["k_hi"])] + pd.Timedelta(minutes=hi_min)
        for csucs in (True, False):
            if (csucs and not pc[j]) or (not csucs and not pv[j]):
                continue
            n_sw += 1
            ar = h[j] if csucs else l[j]
            nev = f"{'cs' if csucs else 'vo'}_{_ts(t)}"
            objs.append(viz.Arrow(name=f"sw_{nev}", t1=_ts(t), p1=float(ar),
                                  code=159, color="gray", width=1))
            objs.append(viz.Text(
                name=f"swtxt_{nev}", t1=_ts(t), p1=float(ar),
                text=(f"{'csucs' if csucs else 'volgy'} {_ar(ar, ps)} "
                      f"({str(t)[5:16]}, igazolva {str(t_conf)[5:16]})"),
                color="gray", fontsize=7))

    # ── 1b. a TÖRÉSEK: a tört szint vonala + a törés függőlegese ───────────
    for e in evs:
        tb = hi.index[e["i"]]
        if not (t0 <= tb < t1):
            continue
        n_ev += 1
        t_sw = hi.index[int(e["piv_hi"])]
        tc = _ts(tb + pd.Timedelta(minutes=hi_min))
        col = "green" if e["dir"] > 0 else "red"
        objs.append(viz.Trend(name=f"lvl_{tc}", t1=_ts(t_sw), p1=float(e["level"]),
                              t2=tc, p2=float(e["level"]), color="blue", width=2))
        objs.append(viz.VLine(name=f"brk_{tc}", t1=tc, color="darkgold", width=2))
        cim = {"folyt": "folytatas", "ford": "fordulat"}.get(e["label"], "trend nelkul")
        objs.append(viz.Text(
            name=f"brktxt_{tc}", t1=tc, p1=float(e["level"]),
            text=(f"{tf_nev} TORES {'FEL' if e['dir'] > 0 else 'LE'} "
                  f"{_ar(e['level'], ps)} - {cim} "
                  f"[{str(tb)[5:16]} zaras {_ar(hi['close'].iloc[e['i']], ps)}]"),
            color=col, fontsize=9))

    msg = (f"{symbol} {tf_nev} {t_from}->{t_to}  (tf_pair={P['tf_pair']}, "
           f"k_hi={P['k_hi']}): {n_sw} igazolt swing, {n_ev} tores")
    return objs, msg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="Ger40")
    ap.add_argument("--from", dest="t_from", required=True)
    ap.add_argument("--to", dest="t_to", required=True, help="a nap végéig")
    ap.add_argument("--tf-pair", default="H1-M15", choices=sorted(sw.TF_PAIRS))
    ap.add_argument("--k-hi", type=int, default=None)
    ap.add_argument("--lepes", type=int, default=1, choices=(1, 2))
    ap.add_argument("--dry", action="store_true", help="csak kiír, nem ír fájlt")
    a = ap.parse_args()
    objs, msg = build_objects(a.symbol, a.t_from, a.t_to, a.tf_pair, a.k_hi, a.lepes)
    print(msg)
    if a.dry:
        for o in objs:
            print("  ", o.line())
        return
    from core import mt5_visual
    lines = [viz.tag_line(o.line(), STRAT) for o in objs]
    path = mt5_visual.write_lines(a.symbol, lines, clear_first=True)
    print(f"{len(lines)} objektum -> {path}")


if __name__ == "__main__":
    main()

"""CSILLA BESZÁLLÓJA — a kutató-szabály KIRAJZOLÁSA az MT5 chartra (TradeForgeViz).

A felhasználó kérése (2026-09-14): „nem tudom, mit számolsz pontosan — mutasd
a DAX összes belépőjét a múlt hétre MT5-ön". Ez az eszköz a
`tools/research/csilla_levels.py` szabályát (D1/W1 jelentős szintek → M15
törés → M1-zászló belépő, fix 1,5 ATR15 stop) rajzolja ki egy megadott
ablakra a `TFV_<symbol>.csv` fájlba, amit a TradeForgeViz indikátor felolvas.

⚠ NEM stratégia-modul és nem a motor: a kutató-szkript függvényeit hívja
(nem másolat), hogy a chart PONTOSAN azt mutassa, amit a mérés számolt.

Mit rajzol:
  * ÉLŐ szintek az ablakban — D1 (kék) / W1 (lila) vízszintes szakasz az
    igazolástól a törésig (vagy az ablak végéig), felirattal;
  * M15 törés — sötét-arany függőleges + felirat (irány, szint, folytatás/fordulat);
  * M1 pullback — kék pont a tört M1-swing csúcsán + kék szaggatott szint a törésig;
  * belépők — függőleges + a szokásos 6 gyertyás (−3/+3 bar) vízszintes
    szegmensek: belépő (narancs), SL (piros), fibo-TP (zöld); a kilépés
    (SL / TP / 8h) a címkében.
    A megadott óra-sávon KÍVÜLI belépő címkéje jelzi, hogy kívül esik.

Futtatás:
    python tools/csilla_viz.py --symbol Ger40 --from 2026-09-07 --to 2026-09-11
    python tools/csilla_viz.py --symbol Ger40 --from 2026-09-07 --to 2026-09-11 --hours 8 11
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "research"))

import lab                                      # noqa: E402
import csilla_levels as cl                      # noqa: E402
from strategy import visual as viz              # noqa: E402

STRAT = "csilla"


def _ts(t) -> int:
    return int(pd.Timestamp(t).timestamp())


def build_objects(symbol: str, t_from: str, t_to: str, hours: tuple[int, int] | None,
                  stop_atr: float = 1.5) -> tuple[list, str]:
    lab._CACHE.clear()
    m1 = lab.load_m1(symbol)
    hi = lab.resample(m1, cl.P["hi_tf"])
    t0 = pd.Timestamp(t_from, tz="UTC")
    t1 = pd.Timestamp(t_to, tz="UTC") + pd.Timedelta(days=1)

    lv = cl.level_table(m1, ("D1", "W1"))
    trend = cl.d1_trend_series(m1)
    evs = cl.hi_events(hi, lv, trend, lv[lv.kind == "D1"])
    r = cl.entries(symbol, ("D1", "W1"), stop_atr=stop_atr)
    ent = r[1].drop_duplicates("i") if r else pd.DataFrame()
    ps = float(lab.PAIRS[symbol]["point_size"])

    objs: list = []
    close = hi["close"].to_numpy(float)
    hi_t = hi.index

    # ── szintek: mikor törtek? (első M15 zárás a szinten túl az igazolás után)
    # Csak az ablak ársávjának ±3 %-án belüli szinteket rajzoljuk — a többi élő
    # szint is szabályos, de a charton csak zsúfolna.
    _w = m1[(m1.index >= t0) & (m1.index < t1)]
    lo_p, hi_p = float(_w["low"].min()) * 0.97, float(_w["high"].max()) * 1.03
    for k, L in enumerate(lv.itertuples()):
        if L.t_conf > t1 or L.t_exp < t0 or not (lo_p <= L.price <= hi_p):
            continue
        j0 = int(np.searchsorted(hi_t, L.t_conf, side="left"))
        seg = close[j0:]
        hit = np.flatnonzero(seg > L.price) if L.side > 0 else np.flatnonzero(seg < L.price)
        t_break = hi_t[j0 + hit[0]] + pd.Timedelta(minutes=cl.P["hi_tf"]) if len(hit) else None
        t_end = min(t_break or t1, min(L.t_exp, t1))
        if t_end <= t0:
            continue                                  # az ablak előtt tört/lejárt
        a = max(L.t_conf, t0 - pd.Timedelta(days=1))
        col = "blue" if L.kind == "D1" else "magenta"
        nev = f"lvl_{L.kind}_{k}"
        objs.append(viz.Trend(name=nev, t1=_ts(a), p1=float(L.price), t2=_ts(t_end),
                              p2=float(L.price), color=col,
                              width=1 if L.kind == "D1" else 2))
        objs.append(viz.Text(name=f"lvltxt_{L.kind}_{k}", t1=_ts(a), p1=float(L.price),
                             text=f"{L.kind} {'ellenallas' if L.side > 0 else 'tamasz'} "
                                  f"{L.price:.1f}", color=col, fontsize=8))

    # ── M15 törések az ablakban
    n_ev = 0
    for e in evs:
        tb = hi_t[e["i"]]
        if not (t0 <= tb < t1):
            continue
        n_ev += 1
        tc = _ts(tb + pd.Timedelta(minutes=cl.P["hi_tf"]))
        objs.append(viz.VLine(name=f"brk_{tc}", t1=tc, color="darkgold", width=2))
        cim = {"folyt": "folytatas", "ford": "fordulat", "nincs": "trend nelkul"}[e["label"]]
        objs.append(viz.Text(name=f"brktxt_{tc}", t1=tc, p1=float(e["level"]),
                             text=f"M15 tores {'FEL' if e['dir'] > 0 else 'LE'} - "
                                  f"{e['kind']} {e['level']:.1f} ({cim})",
                             color="darkgold", fontsize=9))

    # ── M1 zászlók (pullback) + belépők a POZÍCIÓ vonalaival
    # A vonalak a pozícióhoz tartoznak: a belépőtől a kilépésig (SL vagy TP
    # elérése, legfeljebb 8 óra) — nem ±3 perces szegmensek.
    h1 = m1["high"].to_numpy(float)
    l1 = m1["low"].to_numpy(float)
    sp1 = m1["avg_spread"].to_numpy(float)
    sp1 = np.where(np.isfinite(sp1) & (sp1 > 0), sp1, 0.0)
    n_in = n_out = 0
    for x in ent.itertuples():
        i = int(x.i)
        ti = m1.index[i]
        if not (t0 <= ti < t1):
            continue
        d = int(x.dir)
        entry = float(m1["close"].iloc[i])
        sl = entry - d * x.sl_pts * ps
        tp = entry + d * x.tp_pts * ps if x.tp_pts > 0 else None
        # kilépés: SL vagy TP első érintése (a stop nyer), max 8 óra
        j_end = min(len(m1) - 1, i + 480)
        j_exit, mi = j_end, ""
        for j in range(i + 1, j_end + 1):
            bh, bl = (h1[j], l1[j]) if d > 0 else (h1[j] + sp1[j], l1[j] + sp1[j])
            if (d > 0 and bl <= sl) or (d < 0 and bh >= sl):
                j_exit, mi = j, "SL"
                break
            if tp is not None and ((d > 0 and bh >= tp) or (d < 0 and bl <= tp)):
                j_exit, mi = j, "TP"
                break
        t_ent = _ts(ti) + 60
        # A vonalak a SZOKÁSOS 6 gyertyás szegmensek (−3 / +3 bar a belépő
        # körül), mint a közös `entry_marks` — a kilépésig húzott vonal napokon
        # át zavaró volt. A kilépés ténye a címkében marad (-> SL / TP / 8h).
        t_a, t_ex = t_ent - 180, t_ent + 180
        h = ti.hour
        inside = hours is None or (hours[0] <= h <= hours[1])
        n_in += inside
        n_out += (not inside)
        dn = "BUY" if d > 0 else "SELL"
        col = "green" if d > 0 else "red"
        lab_ = (f"Csilla {dn} {h:02d}:{ti.minute:02d}"
                + ("" if inside else " (savon kivul)")
                + (f" -> {mi}" if mi else " -> 8h"))
        objs.append(viz.VLine(name=f"m1sig_{t_ent}", t1=t_ent, color=col, width=2))
        objs.append(viz.Trend(name=f"pos_entry_{t_ent}", t1=t_a, p1=entry, t2=t_ex,
                              p2=entry, color="orange", width=2))
        objs.append(viz.Trend(name=f"pos_sl_{t_ent}", t1=t_a, p1=float(sl), t2=t_ex,
                              p2=float(sl), color="red", width=2))
        objs.append(viz.Text(name=f"pos_sltxt_{t_ent}", t1=t_ent, p1=float(sl),
                             text=f"SL {x.sl_pts * ps:.0f} pt", color="red", fontsize=8))
        if tp is not None:
            objs.append(viz.Trend(name=f"pos_tp_{t_ent}", t1=t_a, p1=float(tp), t2=t_ex,
                                  p2=float(tp), color="green", width=2))
            objs.append(viz.Text(name=f"pos_tptxt_{t_ent}", t1=t_ent, p1=float(tp),
                                 text=f"TP fibo 138.2 ({x.tp_pts * ps:.0f} pt)",
                                 color="green", fontsize=8))
        objs.append(viz.Text(name=f"m1lbl_{t_ent}", t1=t_ent, p1=entry, text=lab_,
                             color=col, fontsize=9))
        # a PULLBACK: a tört M1-swing (zászló) csúcsa jelölővel + a szint a törésig
        if x.piv is not None:
            tp_iv = _ts(m1.index[int(x.piv)])
            p_piv = float(x.level)
            objs.append(viz.Arrow(name=f"flagpk_{t_ent}", t1=tp_iv, p1=p_piv,
                                  code=159, color="blue", width=2))
            objs.append(viz.Text(name=f"flagtxt_{t_ent}", t1=tp_iv, p1=p_piv,
                                 text="pullback", color="blue", fontsize=8))
            objs.append(viz.Trend(name=f"flag_{t_ent}", t1=tp_iv, p1=p_piv,
                                  t2=_ts(m1.index[int(x.b)]) + 60, p2=p_piv,
                                  color="blue", width=1, style=1))

    msg = (f"{symbol} {t_from}→{t_to}: {n_ev} M15-törés, {n_in + n_out} M1-belépő "
           f"({n_in} a {hours[0]}–{hours[1]}h sávban, {n_out} kívül)" if hours else
           f"{symbol} {t_from}→{t_to}: {n_ev} M15-törés, {n_in + n_out} M1-belépő")
    return objs, msg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="Ger40")
    ap.add_argument("--from", dest="t_from", required=True)
    ap.add_argument("--to", dest="t_to", required=True, help="a nap végéig")
    ap.add_argument("--hours", nargs=2, type=int, default=(8, 11),
                    help="a megbeszélt óra-sáv (szerver-idő), pl. 8 11")
    ap.add_argument("--stop-atr", type=float, default=1.5)
    ap.add_argument("--dry", action="store_true", help="csak kiír, nem ír fájlt")
    a = ap.parse_args()
    objs, msg = build_objects(a.symbol, a.t_from, a.t_to, tuple(a.hours), a.stop_atr)
    print(msg)
    if a.dry:
        for o in objs:
            print("  ", o.line())
        return
    from core import mt5_visual
    lines = [viz.tag_line(o.line(), STRAT) for o in objs]
    path = mt5_visual.write_lines(a.symbol, lines, clear_first=True)
    print(f"{len(lines)} objektum → {path}")


if __name__ == "__main__":
    main()

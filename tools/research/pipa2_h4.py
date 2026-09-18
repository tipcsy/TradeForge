"""PIPA2 (szigoru ✓) H1 / H4 — SAJAT MEROHELY — eloregisztralt meres (2026-09-18,
vault „Pipa2 H1-H4 — eloregisztralt kerdes").

A KERDES: hordoz-e a szigoru pipa H1-en es H4-en — a sajat idosik ATR-jevel mert
stoppal, tobb napos tartassal, spreaddel ES swappal — a kitores iranyaban olyan
elt, amely a koltseg utan is pozitiv, es nem a sodrodas?

MEROHELY:
  minta     candle_lib.pipa_szigoru az adott idosikon (K=12, melyseg >= 1,5 ATR_TF)
  belepes   a kitoro gyertya ZARASA utani elso M1-en (lab.simulate: az M1 bar
            zarasan, ask/bid), valodi spread
  stop      1,5 x ATR(14)_TF pontban; nincs celar
  kilepes   BE a belepore +0,67 R-nel, 2 R csuszo, idokorlat H1 5 nap / H4 15 nap
  koltseg   spread + swap + jutalek (pair_cfg)
  ket szam  fuggetlen (minden talalat kulon) es egyszerre-egy-pozicio paronkent
  alapszint ugyanez a keszlet MINDEN H4 gyertya zarasan (H1-en minden 4.), mindket
            iranyban, fuggetlenul -> tobblet = pipa2 R - alapszint(par, irany)
  tukor     az ellenkezo irany ugyanazokon a talalatokon

ELFOGADAS (iranyonkent es osszevonva, idosikonkent):
  netto R > 0 >= 3/5 paron ES t >= 2 osszevontan (fuggetlen) ES evek >= 60 %
  pozitiv ES tobblet > 0 ES a tukor netto R-je kisebb. n < 300 -> nem ertekelheto.

Tajekoztato: celar 2 R BE/csuszo nelkul; stop 1,0 ATR; tartas fele / ketszerese.

Futtatas: python tools/research/pipa2_h4.py            (~25 perc, az alapszint miatt)
          python tools/research/pipa2_h4.py --gyors    (alapszint nelkul)
          python tools/research/pipa2_h4.py --minta dupla   (masik minta ugyanezen a merohelyen;
                                                            az alapszint gyorsitotarbol: data/alap_h1h4.parquet)
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

import candle_lib
import lab
from search import _t

SYMS = ["Ger40", "UsaInd", "UsaTec", "GOLD", "USDJPY"]
TFS = {60: dict(hold=5 * 1440, alap_lepes=4), 240: dict(hold=15 * 1440, alap_lepes=1)}
STOP_ATR, BE_R, TRAIL_R = 1.5, 0.67, 2.0
MINTA = "pipa2"
ALAP_CACHE = ROOT / "data" / "alap_h1h4.parquet"
T_MIN, YEAR_FRAC, INSTR_MIN, MIN_N, MIN_YEAR_N = 2.0, 0.60, 3, 300, 20


def _entries(sym, tf):
    """(m1, d, idx_m1 a TF gyertyakhoz, atr_tf, E) — az M1 index a TF bar utolso M1-e."""
    m1 = lab.load_m1(sym)
    d = lab.resample(m1, tf)
    o, h, l, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    atr = lab.atr(h, l, c, 14)
    E, Q = candle_lib.gyertyak_minoseg(o, h, l, c, atr)
    zaras = d.index + pd.Timedelta(minutes=tf)
    idx = np.searchsorted(m1.index.to_numpy(), zaras.to_numpy(), side="left") - 1
    return m1, d, idx, atr, E, Q


def _sim(m1, sym, idx, dirs, sl_pts, hold, one, tp_rr=0.0, be=BE_R, trail=TRAIL_R):
    ps = float(lab.PAIRS[sym]["point_size"])
    tp = sl_pts * tp_rr if tp_rr > 0 else np.zeros(len(idx))
    return lab.simulate(m1, idx, dirs.astype(np.int8), sl_pts, tp, ps, max_hold=hold,
                        be_at_r=be, trail_r=trail, one_at_a_time=one,
                        pair_cfg=lab.PAIRS[sym])


def _alapszint(m1, d, sym, tf, irany, jel, idx_all, ok, atr, ps, hold):
    """Az alapszint (minden gyertya, fuggetlen) — gyorsitotarazva, mert ~20 perc."""
    key = (sym, tf, irany)
    if ALAP_CACHE.exists():
        cache = pd.read_parquet(ALAP_CACHE)
        hit = cache[(cache.sym == sym) & (cache.tf == tf) & (cache.irany == irany)]
        if len(hit):
            return (float(hit.R.mean()), int(len(hit)), hit.groupby("ev").R.mean())
    lep = TFS[tf]["alap_lepes"]
    ja = np.flatnonzero(ok)[::lep]
    ta = _sim(m1, sym, idx_all[ja], np.full(len(ja), jel), STOP_ATR * atr[ja] / ps, hold, one=False)
    rows = pd.DataFrame({"sym": sym, "tf": tf, "irany": irany, "ev": d.index[ja].year[:len(ta)],
                         "R": ta["r"]})
    cache = pd.concat([pd.read_parquet(ALAP_CACHE), rows]) if ALAP_CACHE.exists() else rows
    cache.to_parquet(ALAP_CACHE, index=False)
    return (float(rows.R.mean()), int(len(rows)), rows.groupby("ev").R.mean())


def gyujt(sym, tf, gyors=False):
    m1, d, idx_all, atr, E, Q = _entries(sym, tf)
    ps = float(lab.PAIRS[sym]["point_size"])
    hold = TFS[tf]["hold"]
    ok = (idx_all >= 0) & np.isfinite(atr) & (atr > 0) & (idx_all < len(m1) - 2)
    rows, alap = [], {}
    for irany, jel in (("long", 1), ("short", -1)):
        m = E[f"gy_{MINTA}->{irany}"] & ok
        j = np.flatnonzero(m)
        if len(j) == 0:
            continue
        idx = idx_all[j]
        slp = STOP_ATR * atr[j] / ps
        # fuggetlen, elsodleges keszlet
        tr = _sim(m1, sym, idx, np.full(len(j), jel), slp, hold, one=False)
        # tukor
        tm = _sim(m1, sym, idx, np.full(len(j), -jel), slp, hold, one=False)
        # egyszerre egy pozicio
        t1 = _sim(m1, sym, idx, np.full(len(j), jel), slp, hold, one=True)
        # tajekoztato valtozatok
        t_tp = _sim(m1, sym, idx, np.full(len(j), jel), slp, hold, one=False, tp_rr=2.0, be=0, trail=0)
        t_sl1 = _sim(m1, sym, idx, np.full(len(j), jel), slp / 1.5, hold, one=False)
        t_h2 = _sim(m1, sym, idx, np.full(len(j), jel), slp, hold * 2, one=False)
        t_h05 = _sim(m1, sym, idx, np.full(len(j), jel), slp, hold // 2, one=False)
        assert len(tr) == len(j) == len(tm)
        rows.append(pd.DataFrame({
            "sym": sym, "tf": tf, "irany": irany, "ido": d.index[j], "ev": d.index[j].year,
            "minoseg": Q[f"gy_{MINTA}->{irany}"][j],
            "R": tr["r"], "R_tukor": tm["r"], "status": tr["status"],
            "napok": (tr["i_close"] - tr["i_open"]) / 1440.0,
            "R_tp2": t_tp["r"], "R_sl1": t_sl1["r"], "R_h2": t_h2["r"], "R_h05": t_h05["r"],
        }))
        # egyszerre-egy: kulon (kevesebb sor)
        rows[-1].attrs["egy"] = float(np.mean(t1["r"])) if len(t1) else np.nan
        rows[-1].attrs["egy_n"] = int(len(t1))
        if not gyors:
            alap[irany] = _alapszint(m1, d, sym, tf, irany, jel, idx_all, ok, atr, ps, hold)
    out = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    egy = {r.irany.iloc[0]: (r.attrs["egy"], r.attrs["egy_n"]) for r in rows}
    print(f"   {sym} M{tf}: long {int((out.irany == 'long').sum()) if len(out) else 0}, "
          f"short {int((out.irany == 'short').sum()) if len(out) else 0} talalat"
          + ("" if gyors else f"; alapszint L {alap.get('long', (np.nan,))[0]:+.4f} "
                              f"S {alap.get('short', (np.nan,))[0]:+.4f}"), flush=True)
    return out, alap, egy


def itelet(df, alap, egy, tf, irany):
    d = df[(df.tf == tf) & ((df.irany == irany) if irany != "OSSZ" else True)]
    if len(d) < MIN_N:
        return {"tf": f"M{tf}", "irany": irany, "n": len(d), "itelet": "nem ertekelheto (n<300)"}
    mu, t, n = _t(d.R.to_numpy(float))
    mu_m, _, _ = _t(d.R_tukor.to_numpy(float))
    parok = d.groupby("sym").R.mean()
    ev = d.groupby("ev").R.agg(["mean", "size"])
    ev = ev[ev["size"] >= MIN_YEAR_N]
    # tobblet: paronkent es iranyonkent a sajat alapszinthez
    exc = []
    for (s, ir), g in d.groupby(["sym", "irany"]):
        a = alap.get((s, tf), {}).get(ir)
        if a is not None:
            exc.append(g.R.to_numpy(float) - a[0])
    tobblet = float(np.concatenate(exc).mean()) if exc else np.nan
    egy_r = [egy.get((s, tf), {}).get(ir) for (s, ir) in d.groupby(["sym", "irany"]).size().index]
    egy_r = [e for e in egy_r if e is not None and np.isfinite(e[0])]
    egy_w = (sum(e[0] * e[1] for e in egy_r) / sum(e[1] for e in egy_r)) if egy_r else np.nan
    f = {"parok_net+": int((parok > 0).sum()), "t": t, "evek": f"{int((ev['mean'] > 0).sum())}/{len(ev)}",
         "ev_frac": float((ev["mean"] > 0).mean()) if len(ev) else np.nan,
         "tobblet": tobblet, "tukor": mu_m}
    ok = ((f["parok_net+"] >= INSTR_MIN) and (t >= T_MIN) and (f["ev_frac"] >= YEAR_FRAC)
          and (np.isnan(tobblet) or tobblet > 0) and (mu_m < mu))
    return {"tf": f"M{tf}", "irany": irany, "n": n, "R_net": mu, "t": t, "tobblet": tobblet,
            "tukor_R": mu_m, "parok_net+": f"{f['parok_net+']}/{parok.size}", "evek+": f["evek"],
            "egyszerre_egy_R": egy_w, "R_tp2": d.R_tp2.mean(), "R_sl1": d.R_sl1.mean(),
            "R_h2": d.R_h2.mean(), "R_h05": d.R_h05.mean(), "napok_med": d.napok.median(),
            "itelet": "TALALAT" if ok else "BUKOTT"}


def main():
    global MINTA
    pd.set_option("display.width", 250)
    gyors = "--gyors" in _sys.argv
    if "--minta" in _sys.argv:
        MINTA = _sys.argv[_sys.argv.index("--minta") + 1]
    print(f"MINTA: {MINTA}")
    dfs, alap, egy = [], {}, {}
    for tf in TFS:
        for sym in SYMS:
            out, a, e = gyujt(sym, tf, gyors)
            if len(out):
                dfs.append(out)
            alap[(sym, tf)] = a
            egy[(sym, tf)] = e
    df = pd.concat(dfs, ignore_index=True)
    df.to_parquet(ROOT / "data" / f"{MINTA}_h4_trades.parquet", index=False)

    for tf in TFS:
        print(f"\n════ M{tf} — paronkent (fuggetlen, elsodleges kilepes) ════")
        d = df[df.tf == tf]
        g = d.groupby(["sym", "irany"]).agg(n=("R", "size"), R_net=("R", "mean"),
                                            tukor=("R_tukor", "mean"), napok=("napok", "median"),
                                            sl=("status", lambda s: float((s == 0).mean())),
                                            be_trail=("status", lambda s: float((s == 3).mean())))
        g["alap"] = [alap[(s, tf)].get(ir, (np.nan,))[0] for s, ir in g.index]
        g["tobblet"] = g.R_net - g.alap
        g["egyszerre_egy"] = [egy[(s, tf)].get(ir, (np.nan, 0))[0] for s, ir in g.index]
        print(g.round(4).to_string())
        print(f"\n── M{tf} — evenkent (R_net, long / short) ──")
        print(d.pivot_table(index="ev", columns="irany", values="R", aggfunc=["mean", "size"])
              .round(3).to_string())

    print("\n════ ITELET (a rogzitett szabaly) ════")
    rows = [itelet(df, alap, egy, tf, ir) for tf in TFS for ir in ("long", "short", "OSSZ")]
    print(pd.DataFrame(rows).round(4).to_string(index=False))


if __name__ == "__main__":
    main()

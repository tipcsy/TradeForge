"""GYERTYA-/ALAKZAT-JELEK BONTASA PIACI ALLAPOT ES NAPSZAK SZERINT (2026-09-18).

A felhasznalo kerese: „nezd meg, milyen piac van epp (a piac-kapu: szep-e a
chart), es nezz idoszakokat is — delelott, del, delutan, 15:30–16:00 (ott nagy
mozgasok vannak, ki kellene hagyni)".

MEROHELY: a kimenet-racs (M5 racspont, stop 1,5 ATR15, celar 2 R, 8 ora, valodi
spread) — minden mintara ugyanaz. A jel a `candle_patterns.candle_masks`
(felfuto el a zaras utani elso racsponton).

BONTAS:
  piac    core.regime.classify az M15 gyertyakon (a keret piac-kapuja), a jel
          idejen ervenyes (utolso LEZART M15) kategoria; 9 kategoria, osszevonva:
          szep (clean_bull/bear), ideges (volatile_*), oldalazas, erdektelen (dead),
          bizonytalan (uncertain), atmenet (transition), nincs (uncategorized)
  napszak szerveridoben (az M1 index; a projektben szerver ≈ CET):
          ejszaka 0–8, delelott 8–12, del 12–15:30, US-nyitas 15:30–16:00,
          delutan 16–22, este 22–24

ALAPSZINT CELLANKENT: a (par, irany, piac, napszak) cella MINDEN racspontjanak
atlaga → a tobblet a cella sajat alapszintjehez kepest. Ez valasztja le a
napszak koltseg-szerkezetet (a spread/ATR napszakonkent 2–3x valtozik) es a
sodrodast a mintarol.

Kimenet: konzol + data/candle_split_piac.csv, data/candle_split_napszak.csv.
Futtatas: python tools/research/candle_split.py [--tf 15,60] [--csak fejvall,pipa2]
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
import candle_patterns as CP
import lab
from core import regime as _regime

SYMS = ["Ger40", "UsaInd", "UsaTec", "GOLD", "USDJPY"]
PIAC = {"clean_bull": "szep", "clean_bear": "szep", "volatile_bull": "ideges",
        "volatile_bear": "ideges", "ranging": "oldalazas", "dead": "erdektelen",
        "uncertain": "bizonytalan", "transition": "atmenet", "uncategorized": "nincs"}
PIAC_SORREND = ["szep", "ideges", "oldalazas", "erdektelen", "bizonytalan", "atmenet", "nincs"]
NAPSZAK_SORREND = ["ejszaka", "delelott", "del", "US-nyitas", "delutan", "este"]
MIN_CELL = 100


def napszak(ido: pd.DatetimeIndex) -> np.ndarray:
    m = ido.hour * 60 + ido.minute
    return np.select([m < 8 * 60, m < 12 * 60, m < 15 * 60 + 30, m < 16 * 60, m < 22 * 60],
                     ["ejszaka", "delelott", "del", "US-nyitas", "delutan"], "este")


def piac_cimke(sym: str, ido: pd.DatetimeIndex) -> np.ndarray:
    m1 = lab.load_m1(sym)
    d15 = lab.resample(m1, 15)
    cat = _regime.classify(d15[["high", "low", "close"]]).to_numpy()
    zaras = d15.index + pd.Timedelta(minutes=15)
    j = np.searchsorted(zaras.to_numpy(), ido.to_numpy(), side="right") - 1
    out = np.full(len(ido), "nincs", dtype=object)
    ok = j >= 0
    out[ok] = [PIAC.get(c, "nincs") for c in cat[j[ok]]]
    return out


def gyujt(sym: str, tfs, csak):
    ido, R = CP._load(sym)
    E = CP.candle_masks(sym, ido, tfs)
    if csak:
        E = {k: v for k, v in E.items() if any(x in k for x in csak)}
    ns = napszak(ido)
    pc = piac_cimke(sym, ido)
    # cella-alapszint: (irany, piac, napszak) -> atlag R
    alap = {}
    for irany in ("long", "short"):
        df = pd.DataFrame({"R": R[irany], "piac": pc, "ns": ns})
        alap[irany] = df.groupby(["piac", "ns"]).R.mean().to_dict()
        alap[(irany, "piac")] = df.groupby("piac").R.mean().to_dict()
        alap[(irany, "ns")] = df.groupby("ns").R.mean().to_dict()
    rows = []
    for cimke, m in E.items():
        d = candle_lib.irany(cimke)
        idx = np.flatnonzero(m)
        r = R[d][idx]
        ok = np.isfinite(r)
        idx, r = idx[ok], r[ok]
        rows.append(pd.DataFrame({
            "sym": sym, "minta": cimke, "irany": d, "R": r, "piac": pc[idx], "ns": ns[idx],
            "alap_cella": [alap[d].get((p, n), np.nan) for p, n in zip(pc[idx], ns[idx])],
            "alap_piac": [alap[(d, "piac")].get(p, np.nan) for p in pc[idx]],
            "alap_ns": [alap[(d, "ns")].get(n, np.nan) for n in ns[idx]],
        }))
    base = []
    for irany in ("long", "short"):
        df = pd.DataFrame({"sym": sym, "irany": irany, "R": R[irany], "piac": pc, "ns": ns})
        base.append(df)
    print(f"   {sym}: {sum(len(x) for x in rows):,} jel, {len(E)} minta-jel", flush=True)
    return pd.concat(rows, ignore_index=True), pd.concat(base, ignore_index=True)


def _cell(g):
    n = len(g)
    exc = g.R - g.alap_cella
    t = exc.mean() / (exc.std(ddof=1) / np.sqrt(n)) if n > 2 and exc.std(ddof=1) > 0 else np.nan
    return pd.Series({"n": n, "R_net": g.R.mean(), "tobblet": exc.mean(), "t": t})


def _fmt(v):
    n, r, e, t = v
    if not np.isfinite(n) or n < MIN_CELL:
        return f"({int(n) if np.isfinite(n) else 0})"
    return f"{e:+.3f}{'*' if abs(t) >= 2 else ' '}[{r:+.2f}|{int(n)}]"


def main():
    pd.set_option("display.width", 300)
    pd.set_option("display.max_colwidth", 40)
    argv = _sys.argv[1:]
    tfs = tuple(int(x) for x in argv[argv.index("--tf") + 1].split(",")) if "--tf" in argv else (15, 60)
    csak = tuple(argv[argv.index("--csak") + 1].split(",")) if "--csak" in argv else ()
    ev, base = [], []
    for sym in SYMS:
        e, b = gyujt(sym, tfs, csak)
        ev.append(e)
        base.append(b)
    ev = pd.concat(ev, ignore_index=True)
    base = pd.concat(base, ignore_index=True)

    print("\n════ ALAPSZINT — minden racspont, nettó R napszakonkent es piaconkent (5 par) ════")
    print("napszak:")
    print(base.groupby(["irany", "ns"]).R.agg(["mean", "size"]).unstack("ns")
          .reindex(columns=NAPSZAK_SORREND, level=1).round(4).to_string())
    print("piac:")
    print(base.groupby(["irany", "piac"]).R.agg(["mean", "size"]).unstack("piac")
          .reindex(columns=PIAC_SORREND, level=1).round(4).to_string())

    ev["tf"] = ev.minta.str.split(":").str[0]
    ev["nev"] = ev.minta.str.split(":").str[1]
    for tf in [f"M{t}" for t in tfs]:
        d = ev[ev.tf == tf]
        if d.empty:
            continue
        print(f"\n════ {tf} — NAPSZAK szerint: tobblet a cella-alapszinthez [nettó R | n]; * = |t|≥2 ════")
        g = d.groupby(["nev", "ns"]).apply(_cell, include_groups=False)
        tab = g.apply(lambda r: _fmt((r.n, r.R_net, r.tobblet, r.t)), axis=1).unstack("ns")
        tab = tab.reindex(columns=[c for c in NAPSZAK_SORREND if c in tab.columns])
        print(tab.fillna("").to_string())
        print(f"\n── {tf} — a 15:30–16:00 ablak KIHAGYASAVAL: nettó R / tobblet (osszes → US-nyitas nelkul) ──")
        for nev, gg in d.groupby("nev"):
            nn = gg[gg.ns != "US-nyitas"]
            print(f"   {nev:28s} n {len(gg):6d} → {len(nn):6d}   R {gg.R.mean():+.4f} → {nn.R.mean():+.4f}   "
                  f"tobblet {(gg.R - gg.alap_cella).mean():+.4f} → {(nn.R - nn.alap_cella).mean():+.4f}")
        print(f"\n════ {tf} — PIAC (regime) szerint: tobblet a cella-alapszinthez [nettó R | n]; * = |t|≥2 ════")
        g = d.groupby(["nev", "piac"]).apply(_cell, include_groups=False)
        tab = g.apply(lambda r: _fmt((r.n, r.R_net, r.tobblet, r.t)), axis=1).unstack("piac")
        tab = tab.reindex(columns=[c for c in PIAC_SORREND if c in tab.columns])
        print(tab.fillna("").to_string())

    outp = ev.groupby(["tf", "nev", "piac"]).apply(_cell, include_groups=False).reset_index()
    outp.to_csv(ROOT / "data" / "candle_split_piac.csv", index=False)
    outn = ev.groupby(["tf", "nev", "ns"]).apply(_cell, include_groups=False).reset_index()
    outn.to_csv(ROOT / "data" / "candle_split_napszak.csv", index=False)
    print("\nCSV: data/candle_split_piac.csv, data/candle_split_napszak.csv")


if __name__ == "__main__":
    main()

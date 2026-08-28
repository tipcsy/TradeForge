"""RENDELESARAMLAS a tick-adatbol — jegyzes-alapu kozelitesek.

FONTOS KORLAT, elore: a tick-tar CSAK JEGYZEST tartalmaz (time_msc, bid_pt,
ask_pt). Nincs `last`, nincs `volume`, nincs `flags`. Ezert a klasszikus,
KOTES-alapu rendelesaramlas (elojeles koteti volumen, Lee-Ready besorolas)
NEM szamolhato. Ami szamolhato: a JEGYZES-REVIZIO szerkezete.

Miert erdemes megis megnezni? Mert ez az egyetlen jel a projektben, ami NEM az
arbol szarmazik. Minden eddigi belepo (WPR, SMA, Donchian, ORB, Bollinger) az
ar transzformacioja volt, es mind ugyanabba a falba utkozott. A jegyzes-revizio
mas informacio: azt mondja meg, hogyan VISELKEDNEK az arjegyzok, nem azt, hova
ment az ar.

JELLEMZOK (barononkent):
  n_tick     jegyzes-darabszam
  imb_tick   tick-szabaly a kozeparfolyamon: (fel - le) / mozgasok
  q_imb      egyutt-mozgo jegyzesek: (mindketto fel - mindketto le) / mozgasok
  narrow     spread-szukules aranya (bid fel ES ask le)
  widen      spread-tagulas aranya (bid le ES ask fel) — likviditas visszavonas
  aggr       "agressziv" tickek: |d(kozep)| > spread/2
  sp_mean    atlagos spread pontban
  sp_chg     a spread valtozasa a bar folyaman (veg / eleje)
  dur_med    median jegyzes-koz ms-ban (intenzitas inverze)

A MERES: informacios egyutthato (IC) az ELORE mutato hozamra. A jelen-bar
hozamaval valo korrelacio ERTELMETLEN — a tick-egyensuly konstrukciobol
korrelal vele. Csak a KOVETKEZO barok hozama szamit.
"""

from __future__ import annotations

import glob
import os
import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

TICKS = ROOT / "data" / "ticks"
CACHE = ROOT / "data" / "flow"
BAR_MS = 5 * 60_000                      # M5

FEATS = ["imb_tick", "q_imb", "narrow", "widen", "aggr",
         "sp_mean", "sp_chg", "dur_med", "n_tick"]


def _month_features(path: str) -> pd.DataFrame:
    d = pq.read_table(path).to_pandas()
    if len(d) < 100:
        return pd.DataFrame()
    t = d.time_msc.to_numpy(np.int64)
    b = d.bid_pt.to_numpy(np.int64)
    a = d.ask_pt.to_numpy(np.int64)

    ok = (b > 0) & (a > b)               # ask==0 = ervenytelen (lasd downloader)
    t, b, a = t[ok], b[ok], a[ok]
    if len(t) < 100:
        return pd.DataFrame()

    mid2 = b + a                          # 2*kozep, egeszben marad
    sp = a - b

    db = np.diff(b, prepend=b[0])
    da = np.diff(a, prepend=a[0])
    dm = np.diff(mid2, prepend=mid2[0])
    dt = np.diff(t, prepend=t[0])

    up, dn = dm > 0, dm < 0
    q_up = (db > 0) & (da > 0)
    q_dn = (db < 0) & (da < 0)
    nar = (db > 0) & (da < 0)
    wid = (db < 0) & (da > 0)
    agg = np.abs(dm) > sp                 # |d(kozep)| > spread/2  (mid2 skalan)

    bar = (t // BAR_MS) * BAR_MS
    g = pd.DataFrame({
        "bar": bar, "mid2": mid2, "sp": sp, "dt": dt,
        "up": up, "dn": dn, "q_up": q_up, "q_dn": q_dn,
        "nar": nar, "wid": wid, "ag": agg,
    }).groupby("bar", sort=True)

    # szogletes zarojel mindenhol: a g.agg utkozne a groupby sajat agg()-javal
    n = g.size()
    mv = (g["up"].sum() + g["dn"].sum()).replace(0, np.nan)   # valodi mozgasok
    out = pd.DataFrame({
        "n_tick": n,
        "imb_tick": (g["up"].sum() - g["dn"].sum()) / mv,
        "q_imb": (g["q_up"].sum() - g["q_dn"].sum()) / mv,
        "narrow": g["nar"].sum() / n,
        "widen": g["wid"].sum() / n,
        "aggr": g["ag"].sum() / n,
        "sp_mean": g["sp"].mean(),
        "sp_chg": g["sp"].last() / g["sp"].first().replace(0, np.nan),
        "dur_med": g["dt"].median(),
        "close2": g["mid2"].last(),        # 2*zaro kozeparfolyam
    })
    return out


def build(sym: str, force: bool = False) -> pd.DataFrame:
    CACHE.mkdir(parents=True, exist_ok=True)
    dst = CACHE / f"{sym}_m5.parquet"
    if dst.exists() and not force:
        return pd.read_parquet(dst)
    files = sorted(glob.glob(str(TICKS / sym / "*.parquet")))
    if not files:
        raise SystemExit(f"nincs tick-adat: {sym}")
    parts = []
    for i, f in enumerate(files, 1):
        parts.append(_month_features(f))
        if i % 12 == 0 or i == len(files):
            print(f"   {sym}: {i}/{len(files)} ho", flush=True)
    out = pd.concat([p for p in parts if len(p)]).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    out.to_parquet(dst)
    return out


def ic_table(df: pd.DataFrame, horizons=(1, 3, 12)) -> pd.DataFrame:
    """Informacios egyutthato: Spearman-rho a jellemzo es az ELORE hozam kozott.

    Csak OSSZEFUGGO barokra: a hetvegi/ejszakai szakadas nem 5 perces hozam.
    """
    x = df.copy()
    bar = x.index.to_numpy(np.int64)
    c = x.close2.to_numpy(float)
    rows = []
    for h in horizons:
        # a t+h bar letezik ES pontosan h*BAR_MS-mal kesobb van
        nxt = np.full(len(x), np.nan)
        pos = np.searchsorted(bar, bar + h * BAR_MS)
        vand = (pos < len(bar)) & (bar[np.clip(pos, 0, len(bar) - 1)]
                                   == bar + h * BAR_MS)
        nxt[vand] = c[pos[vand]]
        fwd = np.log(nxt / c)
        for f in FEATS:
            v = x[f].to_numpy(float)
            m = np.isfinite(v) & np.isfinite(fwd)
            if m.sum() < 500:
                continue
            rho = pd.Series(v[m]).corr(pd.Series(fwd[m]), method="spearman")
            n = int(m.sum())
            t = rho * np.sqrt((n - 2) / max(1e-12, 1 - rho ** 2))
            rows.append({"jellemzo": f, "horizont_bar": h, "n": n,
                         "IC": float(rho), "t": float(t)})
    return pd.DataFrame(rows)


def main():
    pd.set_option("display.width", 200)
    syms = _sys.argv[1:] or ["Ger40"]
    allic = []
    for sym in syms:
        print(f"=== {sym} ===", flush=True)
        df = build(sym)
        print(f"   {len(df)} M5 bar, {df.index.min()} .. {df.index.max()}")
        ic = ic_table(df)
        ic.insert(0, "sym", sym)
        allic.append(ic)
        print(ic.pivot(index="jellemzo", columns="horizont_bar",
                       values="IC").to_string(float_format=lambda v: f"{v:+.4f}"))
    t = pd.concat(allic)
    print("\n" + "=" * 70)
    print("=== |t| >= 3 (a sok teszt miatt szigoru kuszob) ===")
    s = t[t.t.abs() >= 3].sort_values("t", key=abs, ascending=False)
    print(s.to_string(index=False, float_format=lambda v: f"{v:+.4f}")
          if len(s) else "   NINCS ilyen.")
    out = ROOT / "data" / "flow_ic.csv"
    t.to_csv(out, index=False)
    print(f"\nteljes tabla: {out}")


if __name__ == "__main__":
    main()

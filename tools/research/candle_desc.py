"""GYERTYA-ALAKZATOK — LEIRO STATISZTIKA (a felhasznalo szempontjai, 2026-09-17).

Nem P&L-teszt: azt irja le, hogy a felismert alakzatok UTAN mi tortent.

  1. FELISMERES MINOSEGE: `candle_lib.gyertyak_minoseg` 0..1 (alak + meret),
     fokozat: gyenge < 0,33 <= kozepes < 0,66 <= eros.
  2. TREND a minta ELOTT: a minta elso gyertyaja elotti zaras vs 20 gyertyaval
     korabbi zaras, ATR-ben: > +1 fel, < -1 le, kozte oldalazas.
  3. FORDITAS: le -> fel ("lentrol fel"), fel -> le ("fentrol le"),
  4. FOLYTATAS: le -> le, fel -> fel — a minta UTANI 20 gyertya (zaras vs a
     minta zaroara, ATR-ben, ugyanaz a +-1 ATR kuszob). Az oldalazasbol indulo
     es az oldalazasba erkezo esetek kulon oszlopban.
  5. az ALAKZAT NEVE szerint (a tankonyvi irany a nevben),
  6. EVES bontas (a fo tablaban), HAVI es NAPI bontas CSV-ben.

ALAPSZINT: ugyanezek az aranyok MINDEN gyertyara (minta nelkul) — enelkul a
darabszamok nem ertelmezhetok (egy le-trend utan amugy is X %-ban jon fel).

Kimenet: konzol + data/candle_desc_*.csv + vault-jegyzet (a hivo irja).
Futtatas: python tools/research/candle_desc.py [M15 M60]
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

SYMS = ["Ger40", "UsaInd", "UsaTec", "GOLD", "USDJPY"]
TFS = (15, 60)
ELOTT, UTAN, KUSZOB = 20, 20, 1.0
HOSSZ = {"doji": 1, "kalapacs": 1, "akasztott": 1, "ford_kalapacs": 1, "hullocsillag": 1,
         "marubozu": 1, "bika_elnyelo": 2, "medve_elnyelo": 2, "bika_harami": 2,
         "medve_harami": 2, "attoro": 2, "sotet_felho": 2, "csipesz_alj": 2,
         "csipesz_teto": 2, "hajnalcsillag": 3, "esti_csillag": 3, "harom_katona": 3,
         "harom_varju": 3, "pipa": 12, "pinbar": 1, "pipa2": 12}
KAT = ["lentrol_fel", "fentrol_le", "le_folyt", "fel_folyt", "oldal->fel", "oldal->le", "->oldal"]


def _osztaly(x):
    return np.where(x > KUSZOB, 1, np.where(x < -KUSZOB, -1, 0))


def _kategoria(elott, utan):
    k = np.full(len(elott), "->oldal", dtype=object)
    k[(elott == -1) & (utan == 1)] = "lentrol_fel"
    k[(elott == 1) & (utan == -1)] = "fentrol_le"
    k[(elott == -1) & (utan == -1)] = "le_folyt"
    k[(elott == 1) & (utan == 1)] = "fel_folyt"
    k[(elott == 0) & (utan == 1)] = "oldal->fel"
    k[(elott == 0) & (utan == -1)] = "oldal->le"
    return k


def fokozat(q):
    return np.where(q >= 0.66, "eros", np.where(q >= 0.33, "kozepes", "gyenge"))


def gyujt(sym: str, tf: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(esemenyek, alap): mintankent egy sor / minden gyertyara az alap-kategoria."""
    m1 = lab.load_m1(sym)
    d = lab.resample(m1, tf)
    o, h, l, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    atr = lab.atr(h, l, c, 14)
    E, Q = candle_lib.gyertyak_minoseg(o, h, l, c, atr)
    n = len(c)
    i = np.arange(n)
    utan_ok = i + UTAN < n
    utan = np.full(n, np.nan)
    utan[utan_ok] = (c[i[utan_ok] + UTAN] - c[i[utan_ok]]) / atr[i[utan_ok]]
    rows = []
    for nev, m in E.items():
        alap = candle_lib.alap_nev(nev)
        L = HOSSZ[alap]
        idx = np.flatnonzero(m & utan_ok & (i >= L + ELOTT))
        elott = (c[idx - L] - c[idx - L - ELOTT]) / atr[idx]
        rows.append(pd.DataFrame({
            "sym": sym, "tf": tf, "minta": alap, "irany": candle_lib.irany(nev),
            "ido": d.index[idx], "minoseg": Q[nev][idx], "fokozat": fokozat(Q[nev][idx]),
            "elott_atr": elott, "utan_atr": utan[idx],
            "kat": _kategoria(_osztaly(elott), _osztaly(utan[idx]))}))
    ev = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    # alapszint: MINDEN gyertya (1-gyertyas "minta")
    idx = np.flatnonzero(utan_ok & (i >= 1 + ELOTT) & np.isfinite(atr))
    elott = (c[idx - 1] - c[idx - 1 - ELOTT]) / atr[idx]
    alap = pd.DataFrame({"sym": sym, "tf": tf, "ido": d.index[idx],
                         "kat": _kategoria(_osztaly(elott), _osztaly(utan[idx]))})
    return ev, alap


def _aranyok(kat: pd.Series) -> pd.Series:
    n = len(kat)
    s = kat.value_counts().reindex(KAT, fill_value=0)
    out = {"n": n}
    for k in KAT:
        out[k] = int(s[k])
    # forditas-arany a TRENDES elozmenyuek kozott (oldalazas nelkul)
    tr = s["lentrol_fel"] + s["fentrol_le"] + s["le_folyt"] + s["fel_folyt"]
    out["fordit%"] = 100.0 * (s["lentrol_fel"] + s["fentrol_le"]) / tr if tr else np.nan
    out["folyt%"] = 100.0 * (s["le_folyt"] + s["fel_folyt"]) / tr if tr else np.nan
    out["n_trendes"] = int(tr)
    return pd.Series(out)


def main():
    pd.set_option("display.width", 250)
    tfs = [int(a[1:]) for a in _sys.argv[1:] if a.startswith("M")] or list(TFS)
    ev_all, alap_all = [], []
    for sym in SYMS:
        for tf in tfs:
            ev, alap = gyujt(sym, tf)
            ev_all.append(ev)
            alap_all.append(alap)
            print(f"   {sym} M{tf}: {len(ev):,} felismert minta, {len(alap):,} gyertya", flush=True)
    ev = pd.concat(ev_all, ignore_index=True)
    alap = pd.concat(alap_all, ignore_index=True)
    ev["ev"] = ev.ido.dt.year
    ev["ho"] = ev.ido.dt.to_period("M").astype(str)
    ev["nap"] = ev.ido.dt.date.astype(str)
    ev.to_csv(ROOT / "data" / "candle_desc_events.csv", index=False)

    for tf in tfs:
        e, a = ev[ev.tf == tf], alap[alap.tf == tf]
        print(f"\n════ M{tf} — ALAKZATONKENT, az 5 paron osszevonva "
              f"(elott/utan {ELOTT}/{UTAN} gyertya, kuszob ±{KUSZOB} ATR) ════")
        t = e.groupby(["minta", "irany"]).kat.apply(_aranyok).unstack()
        t.loc[("ALAP (minden gyertya)", "-"), :] = _aranyok(a.kat)
        t = t.astype({k: int for k in ["n", "n_trendes"] + KAT})
        print(t.sort_values("fordit%", ascending=False).round(1).to_string())

        print(f"\n── M{tf} — FELISMERES MINOSEGE x kimenet (fordit% a trendes elozmenyuek kozott) ──")
        q = e.groupby(["minta", "fokozat"]).kat.apply(_aranyok).unstack()[["n", "fordit%", "folyt%"]]
        q = q.unstack("fokozat").round(1)
        print(q.to_string())

        print(f"\n── M{tf} — a trend ELOTT (a minta hany %-a jon le / oldalazas / fel utan) ──")
        el = e.assign(e_oszt=_osztaly(e.elott_atr.to_numpy()))
        tt = pd.crosstab([el.minta, el.irany], el.e_oszt, normalize="index").round(3) * 100
        tt.columns = ["le%", "oldal%", "fel%"][:len(tt.columns)]
        print(tt.round(1).to_string())

        print(f"\n── M{tf} — EVENKENT: fordit% (trendes elozmenyuek kozott), alakzatonkent ──")
        y = e.groupby(["minta", "ev"]).kat.apply(_aranyok).unstack()["fordit%"].unstack("ev")
        ay = a.assign(ev=a.ido.dt.year).groupby("ev").kat.apply(_aranyok).unstack()["fordit%"]
        y.loc["ALAP"] = ay
        print(y.round(0).to_string())

        print(f"\n── M{tf} — TANKONYVI TESZT: long-minta LE-trend utan hany %-ban jon FEL "
              f"(short-minta FEL utan hany %-ban LE), az alapszinthez kepest ──")
        rows = []
        for (minta, irany), g in e.groupby(["minta", "irany"]):
            if irany == "long":
                m = g.kat.isin(["lentrol_fel", "le_folyt"]); hit = (g.kat == "lentrol_fel")
                ab = a.kat.isin(["lentrol_fel", "le_folyt"]); ah = (a.kat == "lentrol_fel")
            else:
                m = g.kat.isin(["fentrol_le", "fel_folyt"]); hit = (g.kat == "fentrol_le")
                ab = a.kat.isin(["fentrol_le", "fel_folyt"]); ah = (a.kat == "fentrol_le")
            n_, p_ = int(m.sum()), 100.0 * hit[m].mean()
            alap_ = 100.0 * ah[ab].mean()
            se = 100.0 * np.sqrt(p_ / 100 * (1 - p_ / 100) / max(n_, 1))
            rows.append({"minta": minta, "irany": irany, "n(trend a tankonyv szerint)": n_,
                         "tankonyvi kimenet%": p_, "alap%": alap_, "kulonbseg pp": p_ - alap_,
                         "z": (p_ - alap_) / se if se > 0 else np.nan})
        print(pd.DataFrame(rows).sort_values("kulonbseg pp", ascending=False)
              .round(2).to_string(index=False))

        print(f"\n── M{tf} — PARONKENT: fordit% ──")
        s = e.groupby(["minta", "sym"]).kat.apply(_aranyok).unstack()["fordit%"].unstack("sym")
        s.loc["ALAP"] = a.groupby("sym").kat.apply(_aranyok).unstack()["fordit%"]
        print(s.round(1).to_string())

    # havi + napi bontas CSV-be (a konzolra tul sok)
    ev.groupby(["tf", "minta", "ho"]).kat.apply(_aranyok).unstack().to_csv(
        ROOT / "data" / "candle_desc_havi.csv")
    ev.groupby(["tf", "minta", "nap"]).kat.apply(_aranyok).unstack().to_csv(
        ROOT / "data" / "candle_desc_napi.csv")
    print("\nCSV: data/candle_desc_events.csv (minden felismert minta), "
          "candle_desc_havi.csv, candle_desc_napi.csv")


if __name__ == "__main__":
    main()

"""KI TUDJUK-E KAPCSOLNI A ROSSZ NAPOKAT? — elore merheto jellemzokbol.

A felhasznalo atfogalmazasa (2026-08-28): "nekem nem faj az, ha olyan a piaci
helyzet, amin nem lehet kereskedni, akkor egyszeruen kapcsoljuk le."

Ez MAS es KONNYEBB kerdes, mint a [[daily_params]]-e. Ott azt kerdeztuk, melyik
BEALLITAS jo ma (es a valasz: nem viheto at). Itt csak binaris dontes kell:
kereskedjunk-e ma egyaltalan. Ehhez nem kell, hogy a parameterek atvihetok
legyenek.

KET SZABALY, amit be kell tartani, kulonben a meres onmagat csalja meg:

  1. MINDEN jellemzo a nap KEZDETE ELOTTI adatbol szamol. Egy "aznapi
     volatilitas" jellemzo utolagos cimke lenne — igaz, de hasznalhatatlan.
     (Lasd a korabbi tanulsagot: "az ablak utolso jelzese veszit" 5/5 paron
     igaz, de tautologia.)

  2. SOK jellemzot probalunk -> a legjobb mindig jonak latszik. Ezert a mintat
     FELEZZUK: az elso felen keressuk a szabalyt, a MASODIKON merjuk. Amit a
     masodik fel mutat, az az igazi szam.
"""

from __future__ import annotations

import json
import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

import core.applog as _applog
_applog.harden_console()

from core.execution_params import load_execution_params
from core.params_store import resolve_trade_hours
from strategy import get_strategy_by_name
from strategy.settings import config_for_strategy
from trading.backtest import run_pair

STRAT = "wpr_sma"
START = "2022-01-01"
BAR_MS = 5 * 60_000


def napi_R(sym: str) -> pd.Series:
    """A VALODI hangolt parameterekkel elert napi R-osszeg."""
    raw = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    cfg = config_for_strategy(raw, STRAT)
    p = json.loads((ROOT / "data" / "optimized_params" / STRAT /
                    f"{sym}.json").read_text(encoding="utf-8"))["params"]
    p = {**(load_execution_params(sym, cfg) or {}), **p}
    legacy = (cfg.get("pairs", {}).get(sym, {}) or {}).get("trade_hours")
    hrs = resolve_trade_hours(sym, STRAT, legacy)
    m15 = pd.read_parquet(ROOT / "data" / "m15" / f"{sym}.parquet")
    m1 = pd.read_parquet(ROOT / "data" / "m1" / f"{sym}.parquet")
    r = run_pair(sym, m15, m1, p, cfg["pairs"][sym], cfg["trading"], 1000.0,
                 strategy=get_strategy_by_name(STRAT),
                 allowed_hours=set(hrs) if hrs else None, cfg=cfg,
                 exec_gates=True, test_start=START)
    rows = [{"nap": t.open_time.date(), "R": t.pnl_usd / t.risk_usd}
            for t in r.closed if t.risk_usd]
    s = pd.DataFrame(rows).groupby("nap").R.sum()
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def elore_jellemzok(sym: str) -> pd.DataFrame:
    """Napi jellemzok — MIND az ELOZO napokbol (shift(1) mindenutt)."""
    f = ROOT / "data" / "flow" / f"{sym}_m5.parquet"
    d = pd.read_parquet(f).sort_index()
    ts = pd.to_datetime(d.index.to_numpy(np.int64), unit="ms")
    d = d.set_index(ts)
    c = d.close2.to_numpy(float)
    r = np.concatenate([[np.nan], np.diff(np.log(c))])
    d["r"] = r
    nap = d.index.normalize()
    g = d.groupby(nap)
    napi = pd.DataFrame({
        "vol": g.r.std() * 1e4,                 # napi realizalt volatilitas, bp
        "akt": g.n_tick.mean(),                 # jegyzes-aktivitas
        "spread": g.sp_mean.mean(),
        "tag": g.widen.mean(),                  # likviditas-visszavonas
        "zaro": g.close2.last(),
    })
    napi["hozam"] = np.log(napi.zaro / napi.zaro.shift(1)) * 1e4
    napi["ejszakai_res"] = np.nan               # nyito vs elozo zaro
    ny = g.close2.first()
    napi["ejszakai_res"] = (np.log(ny / napi.zaro.shift(1)) * 1e4).abs()

    out = pd.DataFrame(index=napi.index)
    # MINDEN jellemzo shift(1) — a nap kezdetekor csak a TEGNAPI ismert
    out["tegnapi_vol"] = napi.vol.shift(1)
    out["vol_5n"] = napi.vol.rolling(5).mean().shift(1)
    out["vol_arany"] = (napi.vol / napi.vol.rolling(20).mean()).shift(1)
    out["tegnapi_akt"] = napi.akt.shift(1)
    out["akt_arany"] = (napi.akt / napi.akt.rolling(20).mean()).shift(1)
    out["tegnapi_spread"] = napi.spread.shift(1)
    out["spread_vol"] = (napi.spread / napi.vol).shift(1)
    out["tegnapi_tagulas"] = napi.tag.shift(1)
    out["tegnapi_hozam"] = napi.hozam.shift(1)
    out["tegnapi_hozam_abs"] = napi.hozam.abs().shift(1)
    out["ejszakai_res"] = napi.ejszakai_res      # a nap ELEJEN mar ismert
    out["het_napja"] = out.index.dayofweek
    out["trend_5n"] = napi.hozam.rolling(5).sum().shift(1)
    return out


def ertekel(sym: str):
    R = napi_R(sym)
    F = elore_jellemzok(sym)
    if R.index.tz is not None:
        R.index = R.index.tz_localize(None)
    if F.index.tz is not None:
        F.index = F.index.tz_localize(None)
    df = F.join(R.rename("R"), how="inner").dropna(subset=["R"])
    feats = [c for c in df.columns if c != "R"]
    n = len(df)
    fel = n // 2
    A, B = df.iloc[:fel], df.iloc[fel:]

    print("\n" + "=" * 78)
    print(f"=== {sym}: {n} nap  (kereso fel: {fel}, MERO fel: {n-fel}) ===")
    print(f"   szures nelkul — kereso fel: {A.R.mean():+.4f}   "
          f"MERO fel: {B.R.mean():+.4f}")

    # a kereso felen: minden jellemzo, minden kuszob (also/felso otod-harmad)
    jeloltek = []
    for f in feats:
        v = A[f].to_numpy(float)
        if not np.isfinite(v).sum() > 50:
            continue
        for q in (0.2, 0.33, 0.5, 0.67, 0.8):
            k = np.nanquantile(v, q)
            for irany in ("alatta_kihagy", "felette_kihagy"):
                keep = (A[f] > k) if irany == "alatta_kihagy" else (A[f] <= k)
                keep = keep.fillna(False)
                # a minimum a minta MERETEHEZ igazodik (GOLD: 70 kereso nap)
                if keep.sum() < max(20, len(A) // 5):
                    continue
                jeloltek.append({"f": f, "q": q, "irany": irany, "k": float(k),
                                 "kereso_R": float(A.R[keep].mean()),
                                 "megtartott": int(keep.sum())})
    if not jeloltek:
        print("\n   (nincs ervenyes szabaly-jelolt — tul keves nap)")
        return _jellemzo_tabla(B, feats)
    j = pd.DataFrame(jeloltek).sort_values("kereso_R", ascending=False)
    print(f"\n   {len(j)} szabaly-jelolt a kereso felen. A legjobb 5:")
    print(j.head(5).to_string(index=False, float_format=lambda v: f"{v:9.4f}"))

    # a legjobb szabaly a MERO felen
    print(f"\n   --- A kereso felen legjobb szabaly a MERO felen ---")
    top = j.iloc[0]
    keep_B = ((B[top.f] > top.k) if top.irany == "alatta_kihagy"
              else (B[top.f] <= top.k)).fillna(False)
    if keep_B.sum() > 20:
        a = B.R[keep_B].to_numpy(float)
        b = B.R.to_numpy(float)
        t = (a.mean() - b.mean()) / np.sqrt(a.var(ddof=1) / len(a)
                                            + b.var(ddof=1) / len(b))
        print(f"   szabaly: {top.f} {top.irany} @ {top.k:.4f}")
        print(f"   szures NELKUL: {b.mean():+.4f} ({len(b)} nap)")
        print(f"   szuressel:     {a.mean():+.4f} ({len(a)} nap)  t={t:+.2f}")
        print(f"   -> {'JAVIT' if t > 2 else 'nincs bizonyitott javulas'}")

    return _jellemzo_tabla(B, feats)


def _jellemzo_tabla(B, feats):
    """Minden jellemzo onalloan a MERO felen — hogy a tobbszoros teszt LATSZODJON.

    13 jellemzo x instrumentum: |t|>=2 varhatoan is elofordul veletlenul. Ezert
    ez a tabla NEM lelet, hanem hipotezis-forras: amit itt latunk, azt friss
    instrumentumon kell megerositeni.
    """
    print("\n   --- MINDEN jellemzo also/felso harmada a MERO felen ---")
    print(f"   {'jellemzo':>18s} {'also 1/3':>10s} {'felso 1/3':>10s} "
          f"{'kulonbseg t':>12s}")
    for f in feats:
        v = B[f].to_numpy(float)
        if np.isfinite(v).sum() < 60:
            continue
        lo, hi = np.nanquantile(v, 0.33), np.nanquantile(v, 0.67)
        a = B.R[(B[f] <= lo).fillna(False)].to_numpy(float)
        c = B.R[(B[f] >= hi).fillna(False)].to_numpy(float)
        if len(a) < 20 or len(c) < 20:
            continue
        t = (c.mean() - a.mean()) / np.sqrt(a.var(ddof=1) / len(a)
                                            + c.var(ddof=1) / len(c))
        jel = "  <<<" if abs(t) >= 2 else ""
        print(f"   {f:>18s} {a.mean():>+10.3f} {c.mean():>+10.3f} "
              f"{t:>+12.2f}{jel}")


def main():
    for s in (_sys.argv[1:] or ["Ger40", "UsaInd", "UsaTec"]):
        if not (ROOT / "data" / "flow" / f"{s}_m5.parquet").exists():
            print(f"({s}: nincs flow-gyorsitotar, kihagyva)")
            continue
        ertekel(s)


if __name__ == "__main__":
    main()

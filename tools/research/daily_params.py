"""MINDEN PIACI HELYZETHEZ TARTOZIK-E NYERESEGES BEALLITAS?

A felhasznalo hipotezise (2026-08-28): "lehet, hogy az egyik nap az mukodik,
hogy az M1 WPR 21, a masik nap viszont 13. Minden piaci helyzethez tartozhat egy
nyereseges beallitas." Es o maga tette fel a donto kerdest: "mennyire fogjuk
elore tudni a piaci helyzetet?"

A kerdes HAROM reszre bomlik, es a sorrend szamit:

  A. LETEZIK-e minden naphoz nyereseges beallitas?
     Ez szinte biztosan IGEN — es ONMAGABAN SEMMIT NEM BIZONYIT. 100 kombinacio
     kozul a legjobbat kivalasztva egy 5-20 koteses napon a SZELEKCIO maga
     gyart nyereseget. Ezert a merese melle NULL-KALIBRACIO kell: ugyanez a
     szam permutalt (osszekevert) adaton. Ha a ketto egyezik, a "minden napnak
     van nyertese" allitas ures.

  B. ATVIHETO-e? A tegnapi legjobb beallitas jo-e ma?
     EZ A DONTO. Ha nincs atvihetoseg, akkor SEMMILYEN piac-osztalyozas nem
     menti meg az otletet — nincs mit osztalyozni, mert a "jo beallitas" nem
     tulajdonsaga a napnak, csak a mult zajanak.

  C. Elore merheto piaci allapotbol megjosolhato-e a jo beallitas?
     Csak akkor van ertelme megnezni, ha B atment.

A meres: a 3 JEL-parameter racsa (sma_period x wpr_m15_period x wpr_m1_period).
Mindharom jel-parameter, tehat a sweep csoportositasi trukkje nem segit — minden
kombinacio sajat jel-listat igenyel. Ezert kombinaciónkent EGY teljes futas, es
a koteseket utolag bontjuk napokra (nem naponkent futtatunk: ugyanaz az
eredmeny toredek ido alatt).
"""

from __future__ import annotations

import itertools
import json
import sys as _sys
import time
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
BALANCE = 1000.0
CACHE = ROOT / "data" / "daily_params"

SMA = [50, 100, 150, 200, 300]
W15 = [9, 14, 21, 26, 34]
W1 = [9, 13, 21, 34]


def setup(sym):
    raw = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    cfg = config_for_strategy(raw, STRAT)
    p = json.loads((ROOT / "data" / "optimized_params" / STRAT /
                    f"{sym}.json").read_text(encoding="utf-8"))["params"]
    p = {**(load_execution_params(sym, cfg) or {}), **p}
    legacy = (cfg.get("pairs", {}).get(sym, {}) or {}).get("trade_hours")
    hrs = resolve_trade_hours(sym, STRAT, legacy)
    return cfg, p, (set(hrs) if hrs else None)


def build(sym: str) -> pd.DataFrame:
    """(kombinacio, nap) -> napi R. Egy futas kombinaciónkent."""
    CACHE.mkdir(parents=True, exist_ok=True)
    dst = CACHE / f"{sym}.parquet"
    if dst.exists():
        return pd.read_parquet(dst)
    cfg, base, hours = setup(sym)
    m15 = pd.read_parquet(ROOT / "data" / "m15" / f"{sym}.parquet")
    m1 = pd.read_parquet(ROOT / "data" / "m1" / f"{sym}.parquet")
    st = get_strategy_by_name(STRAT)
    grid = list(itertools.product(SMA, W15, W1))
    rows = []
    t0 = time.time()
    for i, (a, b, c) in enumerate(grid, 1):
        prm = {**base, "sma_period": a, "wpr_m15_period": b, "wpr_m1_period": c}
        r = run_pair(sym, m15, m1, prm, cfg["pairs"][sym], cfg["trading"],
                     BALANCE, strategy=st, allowed_hours=hours, cfg=cfg,
                     exec_gates=True, test_start=START)
        for t in r.closed:
            if t.risk_usd:
                rows.append({"combo": f"{a}_{b}_{c}", "sma": a, "w15": b,
                             "w1": c, "nap": t.open_time.date(),
                             "R": float(t.pnl_usd / t.risk_usd)})
        if i % 10 == 0 or i == len(grid):
            el = time.time() - t0
            print(f"   {sym}: {i}/{len(grid)} kombinacio, {el/60:.1f} perc "
                  f"(hatra ~{el/i*(len(grid)-i)/60:.0f} perc)", flush=True)
    d = pd.DataFrame(rows)
    d.to_parquet(dst)
    return d


def analyze(sym: str, d: pd.DataFrame):
    # (nap x kombinacio) napi R-osszeg. NaN = azon a napon nem kotott.
    m = d.groupby(["nap", "combo"]).R.sum().unstack("combo")
    m.index = pd.to_datetime(m.index)
    m = m.sort_index()
    print("\n" + "=" * 76)
    print(f"=== {sym}: {len(m)} nap x {len(m.columns)} kombinacio ===")

    # ── A. LETEZES + NULL-KALIBRACIO ────────────────────────────────────────
    best_val = m.max(axis=1)
    van = float((best_val > 0).mean())
    atlag_legjobb = float(best_val.mean())
    atlag_osszes = float(m.stack().mean())
    rng = np.random.default_rng(0)
    A = m.to_numpy(float)
    null_van, null_best = [], []
    for _ in range(200):
        P = A.copy()
        for j in range(P.shape[1]):          # kombinaciónkent KULON keveres
            col = P[:, j]
            ok = np.isfinite(col)
            v = col[ok]
            rng.shuffle(v)
            col[ok] = v
        with np.errstate(all="ignore"):
            b = np.nanmax(P, axis=1)
        b = b[np.isfinite(b)]
        null_van.append((b > 0).mean())
        null_best.append(b.mean())
    print("\n--- A. Van-e minden naphoz nyereseges beallitas? ---")
    print(f"   napok, ahol a LEGJOBB kombinacio pozitiv:  {van:6.1%}")
    print(f"   ugyanez PERMUTALT (ures) adaton:           "
          f"{np.mean(null_van):6.1%} +/- {np.std(null_van):.1%}")
    print(f"   a legjobb kombinacio atlagos napi R-je:    {atlag_legjobb:+.3f}")
    print(f"   permutalt nullon:                          {np.mean(null_best):+.3f}")
    print(f"   AZ OSSZES kombinacio atlaga (a valosag):   {atlag_osszes:+.3f}")
    print("   -> ha a valos ~ a permutalt, a 'minden napnak van nyertese' URES")

    # ── B. ATVIHETOSEG — EZ A DONTO ─────────────────────────────────────────
    print("\n--- B. Atviheto-e? A tegnapi (vagy a mult heti) legjobb jo-e ma? ---")
    print(f"   {'ablak':>12s} {'kovetkezo napi R':>17s} {'t':>7s} {'nap':>6s}")
    for w in (1, 5, 20, 60):
        vals = []
        for i in range(w, len(m)):
            sc = m.iloc[i - w:i].mean(axis=0, skipna=True)
            if not np.isfinite(sc.to_numpy(float)).any():
                continue
            v = m.iloc[i].get(sc.idxmax(), np.nan)
            if np.isfinite(v):
                vals.append(float(v))
        if len(vals) > 30:
            a = np.array(vals)
            t = a.mean() / (a.std(ddof=1) / np.sqrt(len(a)))
            print(f"   {w:>9d} nap {a.mean():>+17.4f} {t:>+7.2f} {len(a):>6d}")
    veletlen = float(m.stack().mean())
    fix_best = float(m.mean(axis=0, skipna=True).max())
    print(f"   {'VELETLEN kombinacio':>21s} {veletlen:>+13.4f}   <- EZ A MERCE")
    print(f"   {'fix legjobb (in-sample)':>21s} {fix_best:>+13.4f}   "
          f"(elore NEM elerheto)")

    rk = m.rank(axis=1)
    cors = [rk.iloc[i].corr(rk.iloc[i + 1]) for i in range(len(rk) - 1)]
    cors = [c for c in cors if np.isfinite(c)]
    if cors:
        ca = np.array(cors)
        t = ca.mean() / (ca.std(ddof=1) / np.sqrt(len(ca)))
        print(f"\n   a kombinaciok RANGSORANAK korrelacioja nap->nap: "
              f"{ca.mean():+.4f} (t={t:+.1f}, n={len(ca)})")
        print("   -> ~0 = a tegnapi sorrend semmit nem mond a mairol")
    return m


def main():
    pd.set_option("display.width", 200)
    syms = _sys.argv[1:] or ["Ger40", "UsaInd"]
    for s in syms:
        print(f"=== epites: {s} ===", flush=True)
        analyze(s, build(s))


if __name__ == "__main__":
    main()

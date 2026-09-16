"""ESEMÉNY-IDŐ REPREZENTÁCIÓ — előregisztrált mérés (2026-09-16).

A KÉRDÉS (a vault „Esemény-idő reprezentáció — előregisztrált kérdés"
jegyzetében rögzítve a mérés ELŐTT):

    Esemény-időben mintavételezve jobban előrejelezhető-e a következő időszak
    MOZGÉKONYSÁGA, mint faliórában — és ha igen, mennyivel javítja a
    volatilitás-feltételes méretezés hozadékát?

NEM kérdés az irány (tick-szinten már mértük: a spread alatt).

HÁROM REPREZENTÁCIÓ, mind a tickből (`data/ticks/<SYM>/<YYYY-MM>.parquet`,
mid = (bid+ask)/2 pontban):
    A — falióra: 15 perces barok;
    B — tick-bar: N jegyzés / bar; N az ELSŐ ÉVBŐL úgy, hogy a bar-szám = A-é;
    C — út-bar: a mid |Δ| kumulált útja T-nként zár; T az első évből, mint N.
    (A C a kumulált út egész többszöröseinél zár — a túlfutás átvitelével —,
    így vektorizált és determinisztikus.)

CÉL: a mid realizált volatilitása (log RV = az 1 perces log-hozamok
négyzetösszege) a következő 60 és 240 FALIÓRÁS percben — mindhárom
reprezentációnál UGYANAZ. Kiértékelés minden óra-határon.

JELLEMZŐK (a legutóbbi ZÁRT barokból): log trailing RV az utolsó 4/16/64
baron, az utolsó bar tick-sűrűsége (log tick/perc), átlagos spreadje (log).
Lineáris modell, évenkénti walk-forward (az (y−1). évre illesztve, az y. éven
tesztelve); az első év csak kalibráció.

ELFOGADÁS (B vagy C jobb A-nál): OOS Spearman-ρ ≥ +0,03 különbség, ≥ 4/5
instrumentumon, az évek ≥ 60 %-ában, mindkét horizonton azonos előjellel.

Futtatás:
    python tools/research/event_time.py --build      # barok a tickből (cache)
    python tools/research/event_time.py              # kiértékelés
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))

import argparse
import glob
import json
import os
import time

import numpy as np
import pandas as pd

SYMS = ["GOLD", "USDJPY", "UsaInd", "UsaTec", "Ger40"]
OUT = ROOT / "data" / "event_time"
CLOCK_MIN = 15
KS = (4, 16, 64)
HORIZ = (60, 240)
RHO_MIN, INSTR_MIN, YEAR_FRAC = 0.03, 4, 0.60


# ── tick → barok (havi darabokban, átvitellel) ──────────────────────────────
def _tick_files(sym):
    return sorted(glob.glob(str(ROOT / "data" / "ticks" / sym / "*.parquet")))


def _load_month(f):
    d = pd.read_parquet(f)
    t = d["time_msc"].to_numpy(np.int64)
    mid = (d["bid_pt"].to_numpy(np.float64) + d["ask_pt"].to_numpy(np.float64)) / 2.0
    sp = (d["ask_pt"].to_numpy(np.float64) - d["bid_pt"].to_numpy(np.float64))
    ok = (mid > 0) & (sp >= 0)
    return t[ok], mid[ok], sp[ok]


def _bars_from_groups(t, mid, sp, gid):
    """Bar-aggregátum csoport-azonosítóból: end_ms, close, ticks, spread-átlag,
    időtartam (ms). A csoportok monoton nemcsökkenők."""
    df = pd.DataFrame({"g": gid, "t": t, "mid": mid, "sp": sp})
    g = df.groupby("g", sort=True)
    out = pd.DataFrame({"end_ms": g["t"].last(), "start_ms": g["t"].first(),
                        "close": g["mid"].last(), "ticks": g["t"].size(),
                        "spread": g["sp"].mean()})
    out.index.name = "g"
    return out.reset_index()


def build(sym: str, force: bool = False):
    OUT.mkdir(parents=True, exist_ok=True)
    meta_p = OUT / f"{sym}_meta.json"
    if meta_p.exists() and not force:
        print(f"   {sym}: kész (cache)")
        return
    files = _tick_files(sym)
    if not files:
        print(f"   {sym}: nincs tick")
        return
    t0 = time.time()
    # ── kalibráció az ELSŐ 12 hónapból: N (tick/bar) és T (út/bar) ──────
    n_ticks = 0
    path = 0.0
    n_clock = 0
    for f in files[:12]:
        t, mid, sp = _load_month(f)
        n_ticks += len(t)
        path += float(np.abs(np.diff(mid)).sum())
        n_clock += len(np.unique(t // (CLOCK_MIN * 60_000)))
    N = max(10, int(round(n_ticks / max(1, n_clock))))
    T = max(1.0, path / max(1, n_clock))
    print(f"   {sym}: kalibráció (első 12 hó): {n_ticks:,} tick, {n_clock:,} M15-bar → "
          f"N={N} tick/bar, T={T:.1f} pont/bar", flush=True)

    # ── barok, havonta, átvitellel ──────────────────────────────────────
    A_parts, B_parts, C_parts, M1_parts = [], [], [], []
    tick_off = 0          # eddig látott tickek száma (B)
    path_off = 0.0        # eddigi kumulált út (C)
    last_mid = None
    for i, f in enumerate(files):
        t, mid, sp = _load_month(f)
        if len(t) == 0:
            continue
        # A: falióra 15 perc
        A_parts.append(_bars_from_groups(t, mid, sp, t // (CLOCK_MIN * 60_000)))
        # M1 mid (a célhoz): percenként az utolsó mid
        m1 = _bars_from_groups(t, mid, sp, t // 60_000)[["end_ms", "close"]]
        m1["minute_ms"] = (m1["end_ms"] // 60_000) * 60_000
        M1_parts.append(m1[["minute_ms", "close"]])
        # B: tick-bar — globális tick-sorszám // N
        gid_b = (tick_off + np.arange(len(t))) // N
        B_parts.append(_bars_from_groups(t, mid, sp, gid_b))
        tick_off += len(t)
        # C: út-bar — globális kumulált út // T
        d = np.abs(np.diff(mid, prepend=(last_mid if last_mid is not None else mid[0])))
        cum = path_off + np.cumsum(d)
        gid_c = np.floor(cum / T).astype(np.int64)
        C_parts.append(_bars_from_groups(t, mid, sp, gid_c))
        path_off = float(cum[-1])
        last_mid = float(mid[-1])
        if (i + 1) % 12 == 0:
            print(f"      … {os.path.basename(f)[:7]}  ({time.time() - t0:.0f} s)", flush=True)

    def _merge(parts):
        # A hónap-határon kettévágott bar (B/C: a csoport-id globális, a két
        # darab külön sorként jött) — a csoport-id szerint ÚJRA összevonjuk.
        df = pd.concat(parts, ignore_index=True)
        g = df.groupby("g", sort=True)
        w = df["ticks"]
        out = pd.DataFrame({"end_ms": g["end_ms"].max(), "start_ms": g["start_ms"].min(),
                            "close": g["close"].last(), "ticks": g["ticks"].sum(),
                            "spread": (df["spread"] * w).groupby(df["g"]).sum() / g["ticks"].sum()})
        return out.sort_values("end_ms").reset_index(drop=True)

    A = _merge(A_parts)
    B = _merge(B_parts)
    C = _merge(C_parts)
    M1 = pd.concat(M1_parts, ignore_index=True).drop_duplicates("minute_ms", keep="last")
    for name, df in (("A", A), ("B", B), ("C", C)):
        df.to_parquet(OUT / f"{sym}_{name}.parquet")
    M1.to_parquet(OUT / f"{sym}_M1.parquet")
    json.dump({"symbol": sym, "N": N, "T": T, "clock_min": CLOCK_MIN,
               "bars": {"A": len(A), "B": len(B), "C": len(C)},
               "from": os.path.basename(files[0])[:7], "to": os.path.basename(files[-1])[:7]},
              open(meta_p, "w"), indent=2)
    print(f"   {sym}: A={len(A):,} B={len(B):,} C={len(C):,} bar, M1={len(M1):,}  ({time.time() - t0:.0f} s)")


# ── jellemzők és cél ─────────────────────────────────────────────────────────
def _features(bars: pd.DataFrame, eval_ms: np.ndarray) -> np.ndarray:
    """Minden kiértékelési időponthoz a legutóbbi ZÁRT bar (end_ms < eval) alapján:
    [log RV_4, log RV_16, log RV_64, log tick-sűrűség, log spread]."""
    end = bars["end_ms"].to_numpy(np.int64)
    close = bars["close"].to_numpy(float)
    lr2 = np.diff(np.log(close), prepend=np.log(close[0])) ** 2
    cs = np.cumsum(lr2)
    dur_min = np.maximum((bars["end_ms"] - bars["start_ms"]).to_numpy(float) / 60_000.0, 1e-3)
    dens = np.log(bars["ticks"].to_numpy(float) / dur_min)
    spr = np.log(np.maximum(bars["spread"].to_numpy(float), 1e-6))
    j = np.searchsorted(end, eval_ms, side="left") - 1      # utolsó zárt bar
    cols = []
    for k in KS:
        a = cs[np.maximum(j, 0)]
        b = cs[np.maximum(j - k, 0)]
        rv = np.where(j - k >= 0, a - b, np.nan)
        cols.append(np.log(np.maximum(rv, 1e-12)))
    cols.append(np.where(j >= 0, dens[np.maximum(j, 0)], np.nan))
    cols.append(np.where(j >= 0, spr[np.maximum(j, 0)], np.nan))
    X = np.column_stack(cols)
    X[j < 64] = np.nan
    return X


def _targets(m1: pd.DataFrame, eval_ms: np.ndarray, horizon_min: int):
    """log RV a következő `horizon_min` percben az 1 perces mid-ből; NaN, ha a
    percek < 80 %-a hiányzik (hétvége, szünet)."""
    mm = m1["minute_ms"].to_numpy(np.int64)
    lc = np.log(m1["close"].to_numpy(float))
    lr2 = np.diff(lc, prepend=lc[0]) ** 2
    cs = np.cumsum(lr2)
    a = np.searchsorted(mm, eval_ms, side="left")
    b = np.searchsorted(mm, eval_ms + horizon_min * 60_000, side="left")
    n = b - a
    rv = cs[np.minimum(b, len(cs) - 1)] - cs[np.minimum(a, len(cs) - 1)]
    ok = (n >= 0.8 * horizon_min) & (b < len(cs))
    return np.where(ok, np.log(np.maximum(rv, 1e-12)), np.nan)


def _ols_fit(X, y):
    Xb = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(Xb, y, rcond=None)
    return beta


def _ols_pred(beta, X):
    return np.column_stack([np.ones(len(X)), X]) @ beta


def _spearman(a, b):
    ra = pd.Series(a).rank().to_numpy()
    rb = pd.Series(b).rank().to_numpy()
    if ra.std() == 0 or rb.std() == 0:
        return np.nan
    return float(np.corrcoef(ra, rb)[0, 1])


def evaluate(sym: str) -> pd.DataFrame:
    meta = json.load(open(OUT / f"{sym}_meta.json"))
    m1 = pd.read_parquet(OUT / f"{sym}_M1.parquet").sort_values("minute_ms")
    bars = {r: pd.read_parquet(OUT / f"{sym}_{r}.parquet") for r in ("A", "B", "C")}
    # kiértékelési pontok: óra-határok, ahol van M1 adat az órán belül
    mm = m1["minute_ms"].to_numpy(np.int64)
    hours = np.unique(mm // 3_600_000) * 3_600_000
    years = pd.to_datetime(hours, unit="ms").year
    y_first = years.min()
    X = {r: _features(bars[r], hours) for r in bars}
    rows = []
    kurt = {r: float(pd.Series(np.diff(np.log(bars[r]["close"].to_numpy(float)))).kurt()) for r in bars}
    for H in HORIZ:
        y = _targets(m1, hours, H)
        for yr in sorted(set(years)):
            if yr <= y_first:                      # az első év csak kalibráció
                continue
            tr = years == yr - 1
            te = years == yr
            for r in bars:
                ok_tr = tr & np.isfinite(y) & np.isfinite(X[r]).all(axis=1)
                ok_te = te & np.isfinite(y) & np.isfinite(X[r]).all(axis=1)
                if ok_tr.sum() < 500 or ok_te.sum() < 500:
                    continue
                beta = _ols_fit(X[r][ok_tr], y[ok_tr])
                p = _ols_pred(beta, X[r][ok_te])
                rows.append(dict(sym=sym, H=H, year=yr, rep=r, n=int(ok_te.sum()),
                                 rho=_spearman(p, y[ok_te]),
                                 mae=float(np.mean(np.abs(p - y[ok_te]))),
                                 kurt=kurt[r]))
    df = pd.DataFrame(rows)
    df.attrs["meta"] = meta
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--symbols", nargs="*", default=SYMS)
    a = ap.parse_args()
    pd.set_option("display.width", 250)
    if a.build:
        for s in a.symbols:
            build(s, a.force)
        return
    res = []
    for s in a.symbols:
        if not (OUT / f"{s}_meta.json").exists():
            print(f"   {s}: nincs cache — előbb --build")
            continue
        d = evaluate(s)
        res.append(d)
        print(f"   {s}: {json.dumps(d.attrs['meta']['bars'])}  N={d.attrs['meta']['N']} T={d.attrs['meta']['T']:.1f}")
    R = pd.concat(res, ignore_index=True)
    R.to_csv(OUT / "event_time_results.csv", index=False)

    print("\n════ OOS Spearman-ρ (előrejelzett vs valós log RV), instrumentum × horizont, évek átlaga ════")
    piv = R.pivot_table(index=["sym", "H"], columns="rep", values="rho", aggfunc="mean")
    piv["B−A"] = piv["B"] - piv["A"]
    piv["C−A"] = piv["C"] - piv["A"]
    print(piv.round(3).to_string())

    print("\n════ ELFOGADÁS (ρ-különbség ≥ +0,03, ≥ 4/5 instr., évek ≥ 60 %, mindkét horizont) ════")
    for cand in ("B", "C"):
        ok_instr = 0
        details = []
        for sym in R.sym.unique():
            per_h = []
            for H in HORIZ:
                d = R[(R.sym == sym) & (R.H == H)].pivot(index="year", columns="rep", values="rho")
                if cand not in d or "A" not in d:
                    per_h.append((np.nan, 0.0))
                    continue
                diff = (d[cand] - d["A"]).dropna()
                per_h.append((float(diff.mean()), float((diff >= RHO_MIN).mean())))
            pass_sym = all(m >= RHO_MIN and f >= YEAR_FRAC for m, f in per_h)
            ok_instr += pass_sym
            details.append(f"{sym}: " + " | ".join(f"H{H} Δρ={m:+.3f} évek≥{RHO_MIN}: {100*f:.0f}%"
                                                    for H, (m, f) in zip(HORIZ, per_h))
                           + (" ✓" if pass_sym else ""))
        print(f"  {cand} vs A → {ok_instr}/{len(R.sym.unique())} instrumentum megy át"
              + (" → ÁTMENT" if ok_instr >= INSTR_MIN else " → BUKOTT"))
        for l in details:
            print("     " + l)

    print("\n════ leíró: a bar-hozamok csúcsossága (kurtózis; kisebb = Gauss-közelibb) ════")
    print(R.groupby(["sym", "rep"]).kurt.first().unstack().round(1).to_string())
    print("\n════ MAE (log-hiba), évek átlaga ════")
    print(R.pivot_table(index=["sym", "H"], columns="rep", values="mae", aggfunc="mean").round(3).to_string())


if __name__ == "__main__":
    main()

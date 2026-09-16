"""A TISZTA BESZÁLLÓ — előregisztrált mérés (2026-09-16, vault: „A tiszta
beszálló — előregisztrált kérdés").

KÉRDÉS: van-e chart-mentes (csak statisztikai állapot-változókból számolt)
beszálló, amely a következő 4 óra hozam-előjelét úgy találja el, hogy a random
fel/le belépőt a KÖLTSÉG KÉTSZERESÉNÉL többel veri?

JELLEMZŐK (csak számok): z-hozam 1/4/24/96 óra (a 96 órás RV-vel normálva);
a 240 perces log-RV mintán kívüli előrejelzése (`event_time.forecast_A`); log
spread/ATR; log tick-sűrűség; napszak (24) + hét napja (5) egy-forró; nappali
swap-mentes jelző. MODELL: logisztikus regresszió a 4 órás hozam előjelére,
évenkénti walk-forward, első két év kimarad. BELÉPŐ: p > 0,55, 4 órás tartás,
R = hozam / (1,5 × ATR15). KONTROLL: random előjel (5 mag). TÜKÖR: ellenirány.

ELFOGADÁS: bruttó él (modell − random) ≥ 2 × költség ≥ 3/5 páron ÉS t ≥ 2
összevontan ÉS évek ≥ 60 % ÉS a tükör negatív. Egy olvasat.

Futtatás:  python tools/research/pure_entry.py
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import json

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

import event_time as ET
import lab

SYMS = ["GOLD", "USDJPY", "UsaInd", "UsaTec", "Ger40"]
H_MIN = 240
P_THR = 0.55
SL_ATR = 1.5
ROLLOVER_H = (21, 22, 23)          # szerver-óra: a rollover-sáv (2–4× drágább)
SEEDS = (1, 2, 3, 4, 5)
COST_MULT, INSTR_MIN, YEAR_FRAC, T_MIN = 2.0, 3, 0.60, 2.0


def _minute_series(sym):
    m1 = pd.read_parquet(ET.OUT / f"{sym}_M1.parquet").sort_values("minute_ms")
    return m1["minute_ms"].to_numpy(np.int64), np.log(m1["close"].to_numpy(float))


def _at(mm, lc, t_ms):
    """log mid az adott időpont ELŐTTI utolsó percen (zárt)."""
    j = np.searchsorted(mm, t_ms, side="left") - 1
    ok = j >= 0
    return np.where(ok, lc[np.maximum(j, 0)], np.nan), ok


def build_table(sym):
    mm, lc = _minute_series(sym)
    hours = np.unique(mm // 3_600_000) * 3_600_000
    bars = pd.read_parquet(ET.OUT / f"{sym}_A.parquet")
    # ── cél: a következő 4 óra log-hozama (csak ha a percek ≥ 80 %-a megvan)
    l0, ok0 = _at(mm, lc, hours + 1)               # a záró perc az óra-határon
    l4, ok4 = _at(mm, lc, hours + H_MIN * 60_000 + 1)
    a = np.searchsorted(mm, hours, side="left")
    b = np.searchsorted(mm, hours + H_MIN * 60_000, side="left")
    full = (b - a) >= 0.8 * H_MIN
    y_ret = np.where(ok0 & ok4 & full, l4 - l0, np.nan)
    # ── múltbeli hozamok 1/4/24/96 óra
    feats = {}
    for h in (1, 4, 24, 96):
        lp, okp = _at(mm, lc, hours - h * 3_600_000 + 1)
        feats[f"r{h}"] = np.where(okp, l0 - lp, np.nan)
    # 96 órás RV (a normáláshoz) az 1 perces hozamokból
    lr2 = np.diff(lc, prepend=lc[0]) ** 2
    cs = np.cumsum(lr2)
    a96 = np.searchsorted(mm, hours - 96 * 3_600_000, side="left")
    rv96 = np.sqrt(np.maximum(cs[np.maximum(a - 1, 0)] - cs[np.maximum(a96 - 1, 0)], 1e-12))
    for h in (1, 4, 24, 96):
        feats[f"z{h}"] = feats[f"r{h}"] / rv96
    # ── RV-előrejelzés (mintán kívül), spread/ATR, tick-sűrűség az A-barokból
    feats["fc_rv240"] = ET.forecast_A(sym, hours, 240)
    X_bar = ET._features(bars, hours)            # [logRV4, logRV16, logRV64, logdens, logspread]
    feats["log_dens"] = X_bar[:, 3]
    feats["log_spread_atr"] = X_bar[:, 4] - 0.5 * X_bar[:, 2]   # log(spread) − log(RV64^0.5) ≈ spread/vol
    # ── naptár
    ts = pd.to_datetime(hours, unit="ms")
    hour = ts.hour.to_numpy()
    dow = ts.dayofweek.to_numpy()
    for h in range(24):
        feats[f"h{h}"] = (hour == h).astype(float)
    for d in range(5):
        feats[f"d{d}"] = (dow == d).astype(float)
    feats["nappal"] = (~np.isin(hour, ROLLOVER_H) & ~np.isin((hour + 4) % 24, ROLLOVER_H)
                       & (hour + 4 <= 24)).astype(float)
    # ── ATR15 a R-hez (az A-barok 64-bar RV-jéből → per-bar szórás ≈ ATR arány); a
    # klasszikus ATR15-öt a lab-M1-ből vesszük, hogy a R azonos legyen a többi méréssel
    m1 = lab.load_m1(sym)
    from strategies import csilla_rules as sw
    hi15 = sw.resample(m1, 15)
    atr15 = pd.Series(sw.atr(hi15["high"].to_numpy(float), hi15["low"].to_numpy(float),
                             hi15["close"].to_numpy(float), 14), index=hi15.index)
    j = np.searchsorted((hi15.index.astype("int64") // 10**6).to_numpy(), hours, side="left") - 1
    atr_at = np.where(j >= 0, atr15.to_numpy()[np.maximum(j, 0)], np.nan)
    # ⚠ Az event_time mid PONTBAN van (bid_pt), a lab ATR15 ÁRBAN — az első
    # futás ezt keverte (R ×100–1000-szeresre fújva: „+38 R / 4 óra").
    ps = float(lab.PAIRS[sym]["point_size"])
    px_pts = np.exp(l0)                                     # mid pontban
    feats["atr_rel"] = atr_at / (px_pts * ps)               # ATR15 az ár arányában
    sp_rel = np.exp(X_bar[:, 4]) / px_pts                   # spread az ár arányában
    df = pd.DataFrame(feats)
    df["t_ms"] = hours
    df["year"] = ts.year
    df["y_ret"] = y_ret
    df["cost_R"] = sp_rel / (SL_ATR * df["atr_rel"])       # a spread R-ben (1,5 ATR stop)
    df["sym"] = sym
    return df


FEATS = (["z1", "z4", "z24", "z96", "fc_rv240", "log_dens", "log_spread_atr", "nappal"]
         + [f"h{h}" for h in range(24)] + [f"d{d}" for d in range(5)])


def run_sym(df):
    d = df.dropna(subset=FEATS + ["y_ret", "cost_R", "atr_rel"]).copy()
    d["R_up"] = d["y_ret"] / (SL_ATR * d["atr_rel"])        # long 4 óra, R-ben, stop nélkül
    years = sorted(d.year.unique())
    out = []
    for yr in years[1:]:
        tr = d[d.year == yr - 1]
        te = d[d.year == yr]
        if len(tr) < 1000 or len(te) < 500:
            continue
        Xtr, ytr = tr[FEATS].to_numpy(float), (tr["y_ret"] > 0).astype(int).to_numpy()
        mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9
        clf = LogisticRegression(C=1.0, max_iter=500)
        clf.fit((Xtr - mu) / sd, ytr)
        p = clf.predict_proba((te[FEATS].to_numpy(float) - mu) / sd)[:, 1]
        te = te.assign(p=p)
        sig = np.where(p > P_THR, 1, np.where(p < 1 - P_THR, -1, 0))
        te = te.assign(dir=sig)
        out.append(te)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def summarize(res: pd.DataFrame, sym: str) -> dict:
    k = res[res.dir != 0]
    if len(k) < 100:
        return {"sym": sym, "n": len(k)}
    r_model = (k.dir * k.R_up).to_numpy()
    r_mirror = -r_model
    rng_rs = []
    for s in SEEDS:
        rs = np.random.default_rng(s).choice([-1, 1], size=len(k))
        rng_rs.append(float((rs * k.R_up.to_numpy()).mean()))
    r_rand = float(np.mean(rng_rs))
    cost = float(k.cost_R.mean())
    brutto = float(r_model.mean()) - r_rand
    # évenkénti bontás a modell R-jén (a random várható értéke ~0 R-ben; a
    # költség a random és a modell kötésén ugyanaz)
    ev_b = k.assign(rm=r_model).groupby("year").rm.mean()
    t = float(r_model.mean() / (r_model.std(ddof=1) / np.sqrt(len(r_model))))
    return {"sym": sym, "n": len(k), "kötés%": 100 * len(k) / len(res),
            "modell R": float(r_model.mean()), "random R": r_rand, "tükör R": float(r_mirror.mean()),
            "bruttó él": brutto, "költség R": cost, "él/költség": brutto / cost if cost > 0 else np.nan,
            "t": t, "évek poz.": f"{int((ev_b > 0).sum())}/{len(ev_b)}", "évek%": float((ev_b > 0).mean()),
            "long%": 100 * float((k.dir > 0).mean())}


def main():
    pd.set_option("display.width", 250)
    rows, allk = [], []
    for sym in SYMS:
        df = build_table(sym)
        res = run_sym(df)
        if not len(res):
            print(f"   {sym}: nincs elég adat")
            continue
        s = summarize(res, sym)
        rows.append(s)
        k = res[res.dir != 0].assign(rm=res[res.dir != 0].dir * res[res.dir != 0].R_up, sym=sym)
        allk.append(k)
        print(f"   {sym}: n={s['n']:,} ({s.get('kötés%', 0):.0f}% az órákból)  modell {s.get('modell R', np.nan):+.4f}  "
              f"random {s.get('random R', np.nan):+.4f}  tükör {s.get('tükör R', np.nan):+.4f}  "
              f"költség {s.get('költség R', np.nan):.3f}  él/költség {s.get('él/költség', np.nan):+.2f}  "
              f"t={s.get('t', np.nan):+.2f}  évek {s.get('évek poz.', '-')}", flush=True)
    R = pd.DataFrame(rows)
    K = pd.concat(allk, ignore_index=True)
    print("\n════ ÖSSZEVONT ════")
    print(R.round(4).to_string(index=False))
    t_all = float(K.rm.mean() / (K.rm.std(ddof=1) / np.sqrt(len(K))))
    ev_all = K.groupby("year").rm.mean()
    print(f"   összevont: n={len(K):,}  modell R={K.rm.mean():+.4f}  t={t_all:+.2f}  "
          f"évek poz. {int((ev_all > 0).sum())}/{len(ev_all)}")
    print("   évenként: " + "  ".join(f"{y}:{v:+.3f}" for y, v in ev_all.items()))
    ok_pairs = int((R["él/költség"] >= COST_MULT).sum()) if "él/költség" in R else 0
    mirror_neg = bool((R["tükör R"] < 0).all()) if "tükör R" in R else False
    verdict = (ok_pairs >= INSTR_MIN and t_all >= T_MIN
               and (ev_all > 0).mean() >= YEAR_FRAC and mirror_neg)
    print("\n════ ELFOGADÁS: bruttó él ≥ 2×költség ≥3/5 páron · t ≥ 2 · évek ≥ 60 % · tükör negatív ════")
    print(f"   párok ≥ 2×költség: {ok_pairs}/5 · t={t_all:+.2f} · évek {100*(ev_all > 0).mean():.0f}% · "
          f"tükör negatív mindenhol: {mirror_neg}  → {'ÁTMENT' if verdict else 'BUKOTT'}")
    K.to_parquet(ET.OUT / "pure_entry_trades.parquet")


if __name__ == "__main__":
    main()

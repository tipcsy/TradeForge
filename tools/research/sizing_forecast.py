"""ELŐREJELZETT MOZGÉKONYSÁG SZERINTI MÉRETEZÉS — előregisztrált mérés (2026-09-16).

A KÉRDÉS (a vault „Előrejelzett mozgékonyság szerinti méretezés —
előregisztrált kérdés" jegyzetében rögzítve a mérés ELŐTT):

    A következő 240 (ill. 60) perc mozgékonyságának ELŐREJELZÉSE szerinti
    fordított méretezés többet ad-e, mint (a) az egyenletes és (b) a múltbeli
    `atr_arany` szerinti méretezés — ugyanazon a kötés-halmazon?

KÖTÉS-HALMAZ: pontosan `sizing.collect(max_adds=0)` (donchian96 + 6 kapu,
5 instrumentum, csomag-szimuláció SL 2,5 ATR / BE 1 R, swappal). Az első két
év kötései MINDEN karból kimaradnak (ott nincs mintán kívüli előrejelzés).

ELŐREJELZÉS: `event_time.forecast_A` — a falióra-modell, az (y−1). év
óra-határain illesztve, a belépés idején kiértékelve az y. évben.

KAROK (rang-alapú lineáris súly, FORDÍTVA: kisebb érték → nagyobb méret;
0,5–1,5× elsődleges, 0,25–1,75× másodlagos):
    1. egyenletes  2. atr_arany (múlt)  3. előrejelzett log RV 240  4. …RV 60

ELFOGADÁS (3. kar, 0,5–1,5×): ≥ +0,005 R az egyenleteshez ≥ 3/5 páron ÉS
≥ +0,003 R az atr_arany-hoz ≥ 3/5 páron ÉS az évek ≥ 60 %-ában pozitív ÉS
ugyanez a KAUZÁLIS (bővülő ablakú) ranggal is.

Futtatás:
    python tools/research/sizing_forecast.py
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

import event_time as ET
import sizing as SZ

BANDS = ((0.5, 1.5), (0.25, 1.75))
ARMS = ("atr_arany", "fc_rv240", "fc_rv60")
D_EQ, D_ATR, YEAR_FRAC, INSTR_MIN = 0.005, 0.003, 0.60, 3


def _weights(x: np.ndarray, lo: float, hi: float, causal: bool) -> np.ndarray:
    """Fordított rang-súly: a KISEBB x kap nagyobb méretet. `causal`: a rang a
    korábbi kötések között (bővülő ablak, a kötések időrendjében)."""
    if causal:
        r = np.full(len(x), np.nan)
        for i in range(len(x)):
            prev = x[:i]
            prev = prev[np.isfinite(prev)]
            if len(prev) >= 30:
                r[i] = (prev < x[i]).mean()
    else:
        r = pd.Series(x).rank(pct=True).to_numpy()
    return lo + (hi - lo) * (1.0 - r)


def _wmean(w, r):
    ok = np.isfinite(w) & np.isfinite(r)
    return float((w[ok] * r[ok]).sum() / w[ok].sum()) if ok.any() and w[ok].sum() > 0 else np.nan


def main():
    pd.set_option("display.width", 250)
    print("kötések gyűjtése (sizing.collect)…", flush=True)
    df = SZ.collect(max_adds=0)
    df = df.sort_values(["sym", "t"]).reset_index(drop=True)
    print(f"   {len(df):,} kötés, egyenletes R = {df.R.mean():+.4f}")

    # előrejelzés a belépés idején, mintán kívül
    df["t_ms"] = (df.t.astype("int64") // 10**6).astype(np.int64)
    for H, col in ((240, "fc_rv240"), (60, "fc_rv60")):
        df[col] = np.nan
        for sym in df.sym.unique():
            m = df.sym == sym
            df.loc[m, col] = ET.forecast_A(sym, df.loc[m, "t_ms"].to_numpy(), H)
    ok = np.isfinite(df.fc_rv240) & np.isfinite(df.fc_rv60) & np.isfinite(df.atr_arany)
    print(f"   előrejelzéssel lefedett kötések: {int(ok.sum()):,} / {len(df):,} "
          f"(az első két év kimarad)")
    d = df[ok].reset_index(drop=True)
    print(f"   korreláció (Spearman) fc_rv240 ↔ atr_arany: "
          f"{d[['fc_rv240', 'atr_arany']].corr(method='spearman').iloc[0, 1]:+.3f}")

    rows, verdict = [], {}
    for causal in (False, True):
        for lo, hi in BANDS:
            base = d.R.mean()
            res = {"egyenletes": base}
            per_sym = {}
            for arm in ARMS:
                w = np.zeros(len(d))
                for sym in d.sym.unique():
                    m = (d.sym == sym).to_numpy()
                    w[m] = _weights(d.loc[m, arm].to_numpy(float), lo, hi, causal)
                d[f"w_{arm}"] = w
                res[arm] = _wmean(w, d.R.to_numpy())
                per_sym[arm] = {}
                for sym in d.sym.unique():
                    m = (d.sym == sym).to_numpy()
                    per_sym[arm][sym] = (_wmean(w[m], d.R.to_numpy()[m]) - d.R[m].mean())
            ev = d.groupby(d.t.dt.year).apply(
                lambda z: _wmean(z["w_fc_rv240"].to_numpy(), z.R.to_numpy()) - z.R.mean(),
                include_groups=False)
            r = {"rang": "kauzális" if causal else "teljes", "sáv": f"{lo}–{hi}×",
                 "n": len(d), "egyenletes": base}
            for arm in ARMS:
                r[f"{arm}"] = res[arm]
                r[f"{arm} − egyenl."] = res[arm] - base
            r["fc240 − atr_arany"] = res["fc_rv240"] - res["atr_arany"]
            r["fc240 párok ≥+0,005 vs egyenl."] = sum(v >= D_EQ for v in per_sym["fc_rv240"].values())
            r["fc240 párok ≥+0,003 vs atr"] = sum(
                (per_sym["fc_rv240"][s] - per_sym["atr_arany"][s]) >= D_ATR for s in per_sym["fc_rv240"])
            r["évek poz. (fc240 vs egyenl.)"] = f"{int((ev > 0).sum())}/{len(ev)}"
            rows.append(r)
            if (lo, hi) == BANDS[0]:
                verdict[causal] = (r["fc240 párok ≥+0,005 vs egyenl."] >= INSTR_MIN
                                   and r["fc240 párok ≥+0,003 vs atr"] >= INSTR_MIN
                                   and (ev > 0).mean() >= YEAR_FRAC)
            print(f"\n── rang={r['rang']}, sáv {r['sáv']} — páronként (súlyozott − egyenletes, R/kötés) ──")
            print(pd.DataFrame(per_sym).round(4).to_string())

    print("\n════ ÖSSZESÍTVE ════")
    print(pd.DataFrame(rows).round(4).to_string(index=False))
    print("\n════ ELFOGADÁS (fc_rv240, 0,5–1,5×: ≥+0,005 vs egyenl. ≥3/5 · ≥+0,003 vs atr_arany ≥3/5 · évek ≥60 % · kauzális ranggal is) ════")
    print(f"   teljes rang: {'✓' if verdict.get(False) else '✗'}   kauzális rang: {'✓' if verdict.get(True) else '✗'}"
          f"   → {'ÁTMENT' if verdict.get(False) and verdict.get(True) else 'BUKOTT'}")


if __name__ == "__main__":
    main()

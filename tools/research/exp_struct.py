"""H8 - SZERKEZET (geometria), nem indikator.

Miert ez a kovetkezo: az eddigi IC-terkepem INDIKATOR-teret fedett le (momentum,
SMA-tavolsag, oszcillatorok, VWAP, volatilitas, gyertya-alak). Az FX Tanoda
modszere (vault: "Trendek", "Szep chart definicio") viszont SZERKEZETET nez:
swing-sorozatok, trendvonal >=3 erintessel, csatorna, harmados/otodos pozicio,
R^2 illeszkedes. Ebbol EGYET SEM merten meg.

Itt a vault-ban mar formalizalt jellemzoket merem ugyanazzal a modszerrel, mint
az indikatorokat: elore-hozam ATR-egysegben, IS/OOS bontasban.
"""
from __future__ import annotations

# A repobol futtathato: a projekt gyokere ES a testvermodulok a sys.path-ra.
import sys as _sys
from pathlib import Path as _Path
ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import lab

TRAIN_END = pd.Timestamp("2025-10-31", tz="UTC")
SYMS = ["UsaTec", "Ger40", "UsaInd", "GOLD", "UK100", "Fra40", "EURUSD", "EURJPY"]


# ── swing pontok (fraktal / pivot) ──────────────────────────────────────────
def swings(h, l, k=3):
    """Pivot high/low: a kozepso gyertya extremuma az elozo/kovetkezo k-nak.
    Vissza: (is_high, is_low) bool tombok. A pivot csak k barral KESOBB
    ismerheto fel -> a hasznalatnal ezt el kell tolni (nincs jovo-szivargas)."""
    n = len(h)
    ih = np.zeros(n, bool)
    il = np.zeros(n, bool)
    for i in range(k, n - k):
        w_h = h[i - k:i + k + 1]
        w_l = l[i - k:i + k + 1]
        if h[i] == w_h.max() and (w_h.argmax() == k):
            ih[i] = True
        if l[i] == w_l.min() and (w_l.argmin() == k):
            il[i] = True
    return ih, il


def structure_features(d, k=3, n_sw=4):
    """A vault-ban formalizalt SZERKEZETI jellemzok, mind KAUZALIS
    (a pivot csak k barral kesobb valik ismertte -> minden jelzes eltolva)."""
    h = d["high"].to_numpy(float)
    l = d["low"].to_numpy(float)
    c = d["close"].to_numpy(float)
    n = len(c)
    a = lab.atr(h, l, c, 14)
    a = np.where(a > 0, a, np.nan)
    ih, il = swings(h, l, k)

    hh = np.full(n, np.nan)      # utolso n_sw swing high-bol: emelkedo-e (HH)
    ll = np.full(n, np.nan)      # ...swing low: emelkedo-e (HL)
    r2_up = np.full(n, np.nan)   # a swing LOW-okra illesztett regresszio R^2
    r2_dn = np.full(n, np.nan)   # a swing HIGH-okra illesztett R^2
    slope = np.full(n, np.nan)   # a swing-kozeppontok meredeksege (ATR/bar)
    touches = np.full(n, np.nan)

    hi_idx, lo_idx = [], []
    for i in range(n):
        # a pivot csak k barral kesobb ismert
        j = i - k
        if j >= 0:
            if ih[j]:
                hi_idx.append(j)
            if il[j]:
                lo_idx.append(j)
        if len(hi_idx) >= n_sw and len(lo_idx) >= n_sw and np.isfinite(a[i]):
            H = np.array([h[x] for x in hi_idx[-n_sw:]])
            L = np.array([l[x] for x in lo_idx[-n_sw:]])
            xh = np.array(hi_idx[-n_sw:], float)
            xl = np.array(lo_idx[-n_sw:], float)
            hh[i] = np.mean(np.diff(H) > 0) - 0.5      # +0.5 = tiszta HH
            ll[i] = np.mean(np.diff(L) > 0) - 0.5      # +0.5 = tiszta HL
            r2_up[i] = _r2(xl, L)
            r2_dn[i] = _r2(xh, H)
            mid_x = np.concatenate([xh, xl])
            mid_y = np.concatenate([H, L])
            o = np.argsort(mid_x)
            sl_ = np.polyfit(mid_x[o], mid_y[o], 1)[0] if len(o) > 2 else np.nan
            slope[i] = sl_ / a[i]
            touches[i] = min(len(hi_idx), len(lo_idx))

    # harmados/otodos pozicio TOBB skalan (a "zoom-relativitas" ellen)
    pos = {}
    for N in (50, 100, 200):
        hi = pd.Series(c).rolling(N).max().to_numpy()
        lo = pd.Series(c).rolling(N).min().to_numpy()
        rng = np.where(hi - lo > 0, hi - lo, np.nan)
        pos[N] = (c - lo) / rng - 0.5
    pos_robust = np.nanmean(np.vstack([pos[50], pos[100], pos[200]]), axis=0)

    ma = lab.sma(c, 200)
    d_norm = (c - ma) / a
    d_abs = np.abs(d_norm)

    F = {
        "sw_HH": hh,                       # swing high-ok emelkednek-e
        "sw_HL": ll,                       # swing low-ok emelkednek-e
        "sw_struct": (hh + ll),            # egyutt: tiszta emelkedo szerkezet
        "sw_slope": slope,                 # a swing-vaz meredeksege
        "r2_up": r2_up, "r2_dn": r2_dn,
        "pos50": pos[50], "pos200": pos[200], "pos_robust": pos_robust,
        "ma_dist": d_norm,
    }
    # SCS ("szep chart score") - a vault kompozitja, IRANNYAL szorozva
    scs_ok = ((np.nanmax(np.vstack([r2_up, r2_dn]), axis=0) >= 0.80) * 0.4
              + (np.abs(pos_robust) >= 0.17) * 0.3
              + (d_abs >= 0.30) * 0.3)
    F["SCS"] = scs_ok * np.sign(pos_robust)
    F["SCS_ok"] = scs_ok                   # irany nelkul: SZURO-jelolt
    return F, a, c


def _r2(x, y):
    if len(x) < 3:
        return np.nan
    p = np.polyfit(x, y, 1)
    yh = np.polyval(p, x)
    ss_t = ((y - y.mean()) ** 2).sum()
    return 1 - ((y - yh) ** 2).sum() / ss_t if ss_t > 0 else np.nan


def run(tf=15, hors=(4, 8, 16, 32)):
    agg = {}
    for sym in SYMS:
        d = lab.resample(lab.load_m1(sym), tf)
        F, a, c = structure_features(d)
        ism = np.asarray(d.index <= TRAIN_END)
        for hz in hors:
            f = np.concatenate([c[hz:], np.full(hz, np.nan)])
            y = (f - c) / a
            for name, x in F.items():
                ok = np.isfinite(x) & np.isfinite(y)
                for tag, m in (("IS", ism & ok), ("OOS", (~ism) & ok)):
                    if m.sum() < 300:
                        continue
                    xs, ys = x[m], y[m]
                    if np.std(xs) == 0:
                        continue
                    ic = np.corrcoef(pd.Series(xs).rank(),
                                     pd.Series(ys).rank())[0, 1]
                    agg.setdefault((name, hz), {}).setdefault(tag, []).append(ic)
    rows = []
    for (name, hz), v in agg.items():
        i_, o_ = np.array(v.get("IS", [])), np.array(v.get("OOS", []))
        if len(i_) < 4 or len(o_) < 4:
            continue
        rows.append({"jellemzo": name, "h": hz, "IC_IS": i_.mean(),
                     "IC_OOS": o_.mean(),
                     "jel_egyez%": 100 * np.mean(np.sign(i_) == np.sign(o_)),
                     "OOS_azonos%": 100 * max(np.mean(o_ > 0), np.mean(o_ < 0))})
    r = pd.DataFrame(rows)
    r["min_abs"] = np.minimum(r.IC_IS.abs(), r.IC_OOS.abs()) * \
        (np.sign(r.IC_IS) == np.sign(r.IC_OOS))
    return r.sort_values("min_abs", ascending=False)


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    r = run()
    print("== SZERKEZETI jellemzok IC-je (8 instrumentum, M15) ==")
    print(r.head(22).to_string(index=False, float_format=lambda x: f"{x:8.4f}"))

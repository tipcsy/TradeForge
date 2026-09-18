"""Egy felismert gyertya-minta KIRAJZOLASA (ellenorzeshez, 2026-09-18).

A `candle_desc.py` altal irt data/candle_desc_events.csv sorai kozul valaszt
(minta + irany + idosik szerint), es matplotlib gyertyas kepet rajzol a minta
kornyezeterol: a pipanal a K-ablak, a melypont, a P0 kezdoszint es a kitoro
gyertya; minden mintanal az „elott/utan 20 gyertya" ablak es az ATR-kuszob.

Futtatas:
    python tools/research/candle_draw.py pipa long 15 19123          # az N. talalat (1-tol)
    python tools/research/candle_draw.py pipa long 15 random 3       # 3 veletlen
Kimenet: data/candle_draw/<minta>_<irany>_M<tf>_<N>.png
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import candle_lib
import lab

OUT = ROOT / "data" / "candle_draw"
ELOTT, UTAN = 40, 20


def _candles(ax, d: pd.DataFrame, x0: int):
    for i, (_, r) in enumerate(d.iterrows()):
        x = x0 + i
        szin = "#2a9d4b" if r.close >= r.open else "#d33a2c"
        ax.plot([x, x], [r.low, r.high], color=szin, lw=0.9)
        lo, hi = sorted((r.open, r.close))
        ax.add_patch(plt.Rectangle((x - 0.35, lo), 0.7, max(hi - lo, 1e-9),
                                   facecolor=szin, edgecolor=szin))


def rajz(row: pd.Series, n_cimke: str) -> _Path:
    sym, tf, minta, irany = row.sym, int(row.tf), row.minta, row.irany
    t_ido = pd.Timestamp(row.ido)
    m1 = lab.load_m1(sym)
    d = lab.resample(m1, tf)
    t = int(d.index.get_indexer([t_ido])[0])
    if t < 0:
        raise SystemExit(f"nincs ilyen gyertya: {sym} M{tf} {t_ido}")
    o, h, l, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    atr = lab.atr(h, l, c, 14)
    a, b = max(0, t - ELOTT), min(len(d), t + UTAN + 1)
    seg = d.iloc[a:b]
    fig, ax = plt.subplots(figsize=(14, 6.5))
    _candles(ax, seg, a)
    ax.axvline(t, color="k", lw=0.8, ls=":")
    ax.axvspan(t - ELOTT // 2, t, color="#f0f0f0", zorder=0)     # „elott 20"
    ax.axvspan(t, t + UTAN, color="#eaf3ff", zorder=0)           # „utan 20"

    cim = f"{sym} M{tf} — {minta} {irany} — {n_cimke} — {t_ido:%Y-%m-%d %H:%M} (szerveridő)"
    if minta in ("pipa", "pipa2"):
        K, W1 = candle_lib.PIPA_K, candle_lib.PIPA_W1
        if irany == "long":
            m = t - K + int(np.argmin(l[t - K:t]))
            lo_a = m - W1 if minta == "pipa" else t - K
            aidx = lo_a + int(np.argmax(c[lo_a:m]))
            P0, ext = c[aidx], l[m]
        else:
            m = t - K + int(np.argmax(h[t - K:t]))
            lo_a = m - W1 if minta == "pipa" else t - K
            aidx = lo_a + int(np.argmin(c[lo_a:m]))
            P0, ext = c[aidx], h[m]
        ax.axvspan(t - K, t, color="#fff3c4", zorder=0, alpha=0.8)
        ax.hlines(P0, aidx, t + 2, color="#b8860b", lw=1.6, label=f"P0 kezdőszint {P0:.5g}")
        ax.plot([aidx, m, t], [P0, ext, c[t]], color="#7b2cbf", lw=2.2, alpha=0.8,
                label="✓ bal szár → mélypont → kitörés")
        ax.annotate("mélypont" if irany == "long" else "csúcs", (m, ext),
                    xytext=(0, -18 if irany == "long" else 12), textcoords="offset points",
                    ha="center", fontsize=9, color="#7b2cbf")
        ax.annotate(f"kitörés  c={c[t]:.5g}", (t, c[t]), xytext=(8, 0), textcoords="offset points",
                    fontsize=9, color="#7b2cbf")
        melyseg = abs(P0 - ext) / atr[t]
        cim += (f"\nK={K} ablak (sárga), bal szár {m - aidx} gy., jobb szár {t - m} gy., "
                f"mélység {melyseg:.2f} ATR, minőség {row.minoseg:.2f} ({row.fokozat})")
    else:
        ax.annotate(f"{minta}", (t, h[t]), xytext=(0, 10), textcoords="offset points",
                    ha="center", fontsize=9, color="#7b2cbf")
        cim += f"\nminőség {row.minoseg:.2f} ({row.fokozat})"

    # elott/utan: a +-1 ATR kuszob a zaroarhoz kepest
    ax.hlines([c[t] + atr[t], c[t] - atr[t]], t, t + UTAN, color="#888", lw=0.8, ls="--",
              label="±1 ATR a kitörés zárásától (a 20-gyertyás kimenet küszöbe)")
    ax.annotate(f"utána 20 gy.: {row.utan_atr:+.2f} ATR → {row.kat}", (t + UTAN, c[t]),
                xytext=(-4, 12), textcoords="offset points", ha="right", fontsize=9)
    ax.annotate(f"előtte 20 gy.: {row.elott_atr:+.2f} ATR", (t - 20, c[t]),
                xytext=(0, -14), textcoords="offset points", ha="center", fontsize=9)
    ax.set_xlim(a - 1, b + 1)
    xt = list(range(a, b, max(1, (b - a) // 10)))
    ax.set_xticks(xt)
    ax.set_xticklabels([d.index[i].strftime("%m-%d %H:%M") for i in xt], rotation=30, fontsize=8)
    ax.set_title(cim, fontsize=10)
    ax.legend(loc="best", fontsize=8)
    ax.grid(alpha=0.25)
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{minta}_{irany}_M{tf}_{n_cimke.replace(' ', '_').replace('.', '')}.png"
    fig.tight_layout()
    fig.savefig(p, dpi=110)
    plt.close(fig)
    return p


def main():
    minta, irany, tf = _sys.argv[1], _sys.argv[2], int(_sys.argv[3])
    ev = pd.read_csv(ROOT / "data" / "candle_desc_events.csv")
    sel = ev[(ev.minta == minta) & (ev.irany == irany) & (ev.tf == tf)].reset_index(drop=True)
    print(f"{minta} {irany} M{tf}: {len(sel):,} találat")
    if _sys.argv[4] == "random":
        k = int(_sys.argv[5]) if len(_sys.argv) > 5 else 3
        rng = np.random.default_rng(int(_sys.argv[6]) if len(_sys.argv) > 6 else 0)
        idx = sorted(rng.choice(len(sel), size=k, replace=False))
    else:
        idx = [int(a) - 1 for a in _sys.argv[4:]]
    for i in idx:
        p = rajz(sel.iloc[i], f"{i + 1}. találat")
        print("   ", p)


if __name__ == "__main__":
    main()

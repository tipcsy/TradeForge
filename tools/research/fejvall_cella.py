"""FORDITOTT FEJ-VALL — IDEGES PIACON, DELUTAN — eloregisztralt meres (2026-09-18,
vault „Fej-vall ideges piacon delutan — eloregisztralt kerdes").

A cella UTOLAG lett valasztva (~440 cellabol, ugyanazon az 5 paron), ezert:
  1. a kimenet-racs szama in-sample (kozoljuk, nem itel);
  2. itel: a sajat H1 merohely (pipa2_h4 keszlet: 1,5 ATR_TF stop, BE 0,67 R,
     2 R csuszo, 5 nap, spread + swap) a szurt kotesekre; a 2023 utani szakasz
     kulon; a 11 masik par tajekoztato.
  Szuro: piac == ideges (core.regime volatile_bull/bear az M15-on a jel idejen)
  ES napszak == delutan (szerverido 16–22). H1 elsodleges, M15 tajekoztato.
  ELFOGADAS: sajat H1: netto > 0 ES t >= 2 ES >= 3/5 par ES evek >= 60 % ES a
  2023+ szakasz netto > 0. n < 100 -> nem ertekelheto.

Futtatas: python tools/research/fejvall_cella.py
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

import candle_patterns as CP
import candle_split as CS
from search import _t

SYMS5 = ["Ger40", "UsaInd", "UsaTec", "GOLD", "USDJPY"]
SYMS11 = ["EURUSD", "UK100", "EURCHF", "EURGBP", "EURJPY", "BTCUSD", "Fra40", "EURHUF",
          "Usa500", "Bra50", "Euro50"]
VAGAS = pd.Timestamp("2023-01-01", tz="UTC")


def _cimkez(df: pd.DataFrame) -> pd.DataFrame:
    """piac + napszak cimke a kotesek idejere (parokent)."""
    out = []
    for sym, g in df.groupby("sym"):
        ido = pd.DatetimeIndex(g.ido)
        g = g.copy()
        g["piac"] = CS.piac_cimke(sym, ido)
        g["ns"] = CS.napszak(ido)
        out.append(g)
    return pd.concat(out, ignore_index=True)


def _osszegzes(d: pd.DataFrame, cimke: str, min_n=100):
    if len(d) < min_n:
        return {"szakasz": cimke, "n": len(d), "itelet": f"nem ertekelheto (n<{min_n})"}
    mu, t, n = _t(d.R.to_numpy(float))
    parok = d.groupby("sym").R.agg(["mean", "size"])
    parok = parok[parok["size"] >= 10]
    ev = d.groupby(d.ido.dt.year).R.agg(["mean", "size"])
    ev = ev[ev["size"] >= 10]
    return {"szakasz": cimke, "n": n, "R_net": mu, "t": t,
            "parok_net+": f"{int((parok['mean'] > 0).sum())}/{len(parok)}",
            "evek+": f"{int((ev['mean'] > 0).sum())}/{len(ev)}",
            "tukor": d.R_tukor.mean() if "R_tukor" in d else np.nan}


def main():
    pd.set_option("display.width", 250)
    # ── 1. sajat H1 merohely: a mar lefuttatott trade-tablak ─────────────────
    a = pd.read_parquet(ROOT / "data" / "fejvall_h4_trades.parquet")
    b = pd.read_parquet(ROOT / "data" / "fejvall_h4_trades_rep_M60.parquet")
    a = a[(a.tf == 60) & (a.irany == "long")].copy()
    b = b[(b.tf == 60) & (b.irany == "long")].copy()
    a["ido"] = pd.to_datetime(a.ido, utc=True)
    b["ido"] = pd.to_datetime(b.ido, utc=True)
    a, b = _cimkez(a), _cimkez(b)
    print("════ SAJAT H1 MEROHELY — fordított fej-váll long, 5 pár ════")
    print("   cellák (n / nettó R):")
    print(a.groupby(["piac", "ns"]).R.agg(["size", "mean"]).unstack("ns").round(3).to_string())
    rows = []
    cell = a[(a.piac == "ideges") & (a.ns == "delutan")]
    rows.append(_osszegzes(cell, "ideges ÉS délután (a rögzített szűrő)"))
    rows.append(_osszegzes(cell[cell.ido >= VAGAS], "  …csak 2023 után", min_n=30))
    rows.append(_osszegzes(a[a.piac == "ideges"], "csak ideges (táj.)"))
    rows.append(_osszegzes(a[a.ns == "delutan"], "csak délután (táj.)"))
    rows.append(_osszegzes(a[a.piac.isin(["ideges", "bizonytalan"]) & (a.ns == "delutan")],
                           "ideges+bizonytalan ÉS délután (táj.)"))
    rows.append(_osszegzes(a, "szűrő nélkül (referencia)"))
    cb = b[(b.piac == "ideges") & (b.ns == "delutan")]
    rows.append(_osszegzes(cb, "11 másik pár, ideges ÉS délután (táj.)", min_n=30))
    print("\n" + pd.DataFrame(rows).round(4).to_string(index=False))

    # ── 2. kimenet-racs (in-sample, tajekoztato) ─────────────────────────────
    print("\n════ KIMENET-RÁCS (in-sample — itt választottuk a cellát; nem ítél) ════")
    ev, base = [], []
    for sym in SYMS5:
        e, bb = CS.gyujt(sym, (15, 60), ("fejvall->long",))
        ev.append(e)
        base.append(bb)
    ev = pd.concat(ev, ignore_index=True)
    ev["tf"] = ev.minta.str.split(":").str[0]
    for tf in ("M15", "M60"):
        d = ev[(ev.tf == tf) & (ev.minta.str.contains("gy_fejvall->long"))]
        c = d[(d.piac == "ideges") & (d.ns == "delutan")]
        exc = (c.R - c.alap_cella)
        t = exc.mean() / (exc.std(ddof=1) / np.sqrt(len(c))) if len(c) > 2 else np.nan
        print(f"   {tf}: ideges ÉS délután n={len(c)}  nettó R {c.R.mean():+.4f}  többlet {exc.mean():+.4f}  t {t:+.2f}"
              f"   | csak ideges n={int((d.piac == 'ideges').sum())} R {d[d.piac == 'ideges'].R.mean():+.4f}"
              f"   | csak délután n={int((d.ns == 'delutan').sum())} R {d[d.ns == 'delutan'].R.mean():+.4f}")


if __name__ == "__main__":
    main()

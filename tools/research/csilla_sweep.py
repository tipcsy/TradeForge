"""A KÉT NYITOTT KAPCSOLÓ MÉRÉSE: `korr_min` × `belepo_mod`.

A 2026-09-23-i lánc két kapcsolóját hagytuk mérésre. Ez a szkript végigméri a
rácsot, és MINDEN cellához odateszi a kontrollt is — mert a nyers R-t a kilépés
(BE + csúszó stop) bármiből pozitívba viszi, tehát a szint nem lelet, csak a
TÖBBLET az.

KONTROLL: azonos irány, véletlen időpont, a stop a HELYI ATR-hez skálázva (a
valódi belépők stop/ATR arányaiból húzva), `--huzas` db húzás eloszlása. A valós
R-t z-pontszámmal hasonlítjuk hozzá. (A nyers stop-méret átvitele véletlen barra
HIBA: egy apró stop trendes szakaszon több száz R-t hoz — ezzel a hibával a
GOLD kontrollja +3,17 R-t adott 2026-09-23-án.)

Futtatás:
    python tools/research/csilla_sweep.py
    python tools/research/csilla_sweep.py --huzas 5 --sym Ger40 UsaTec
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "research"))

import lab                                      # noqa: E402
from strategies import csilla_rules as sw       # noqa: E402

SYMS = ["Ger40", "UsaTec", "GOLD", "EURUSD"]
MODOK = ["varj_pirosra", "leszuras", "piros_zaras"]
KORR = [3, 4, 5, 6]
BE_AT_R, TRAIL_R, MAX_HOLD_NAP = 0.67, 2.0, 5


def _adat(sym: str, P: dict):
    m1 = lab.load_m1(sym)
    hi = sw.resample(m1, P["hi_tf"])
    lo = m1 if P["lo_tf"] <= 1 else sw.resample(m1, P["lo_tf"])
    s = m1["avg_spread"].dropna()
    sp = float(s[s.index >= s.index.max() - pd.Timedelta(days=365)].median()) if len(s) else 0.0
    a14 = sw.atr(lo["high"].to_numpy(float), lo["low"].to_numpy(float),
                 lo["close"].to_numpy(float), 14)
    return hi, lo, sp, a14, float(lab.PAIRS[sym]["point_size"])


def _fut(lo, ps, pair_cfg, lo_tf, idx, side, slp):
    tr = lab.simulate(lo, idx, side, slp, np.zeros(len(idx)), point_size=ps,
                      max_hold=MAX_HOLD_NAP * 1440 // max(1, lo_tf),
                      be_at_r=BE_AT_R, trail_r=TRAIL_R, one_at_a_time=True,
                      pair_cfg=pair_cfg)
    return tr["r"] if len(tr) else np.array([])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sym", nargs="*", default=SYMS)
    ap.add_argument("--huzas", type=int, default=5)
    ap.add_argument("--tf-pair", default="H1-M15", choices=sorted(sw.TF_PAIRS))
    a = ap.parse_args()
    print(f"CSILLA — korr_min x belepo_mod  ({len(a.sym)} par, {a.huzas} veletlen huzas "
          f"cellankent)\n")
    print(f"   {'mod':14} {'korr':>4} {'kotes':>7} {'VALOS R':>9} {'veletlen':>9} "
          f"{'TOBBLET':>9} {'z':>6}  paronkenti tobblet")
    for mod in MODOK:
        for korr in KORR:
            P = sw.with_tf_pair(dict(sw.DEFAULTS, tf_pair=a.tf_pair,
                                     belepo_mod=mod, korr_min=korr))
            n_ossz, R_ossz, V_ossz, z_par, tb_par = 0, [], [], [], []
            for sym in a.sym:
                try:
                    hi, lo, sp, a14, ps = _adat(sym, P)
                    et = sw.counter_entries(lo, sw.chain_setups(hi, P), P, spread=sp)
                    if not len(et):
                        continue
                    et = et.sort_values("i").drop_duplicates("i", keep="first")
                    idx = et.i.to_numpy(int)
                    side = et.dir.to_numpy(int)
                    sl_ar = et.sl_abs.to_numpy(float)
                    _a = a14[idx]
                    ar = sl_ar / np.where(np.isfinite(_a) & (_a > 0), _a, np.nan)
                    ar = ar[np.isfinite(ar)]
                    if not len(ar):
                        continue
                    pc = lab.PAIRS[sym]
                    R = _fut(lo, ps, pc, P["lo_tf"], idx, side, sl_ar / ps)
                    if not len(R):
                        continue
                    vR = []
                    for sd in range(a.huzas):
                        rng = np.random.default_rng(7000 + sd)
                        vi = np.sort(rng.choice(np.arange(60, len(lo) - 600),
                                                size=len(idx), replace=False))
                        va = a14[vi]
                        ok = np.isfinite(va) & (va > 0)
                        vi, va = vi[ok], va[ok]
                        o = rng.permutation(len(idx))[:len(vi)]
                        _r = _fut(lo, ps, pc, P["lo_tf"], vi, side[o],
                                  (rng.choice(ar, size=len(vi)) * va) / ps)
                        if len(_r):
                            vR.append(float(_r.mean()))
                    if not vR:
                        continue
                    vR = np.array(vR)
                    n_ossz += len(R)
                    R_ossz.append(float(R.sum()))
                    V_ossz.append(float(vR.mean()) * len(R))
                    tb_par.append(float(R.mean()) - float(vR.mean()))
                    if vR.std(ddof=1) > 0:
                        z_par.append((float(R.mean()) - vR.mean()) / vR.std(ddof=1))
                except Exception as ex:                       # pragma: no cover
                    print(f"      {sym}: HIBA {type(ex).__name__}: {ex}")
            if not n_ossz:
                print(f"   {mod:14} {korr:4d}  (nincs jel)")
                continue
            vR_ = sum(R_ossz) / n_ossz
            vV_ = sum(V_ossz) / n_ossz
            print(f"   {mod:14} {korr:4d} {n_ossz:7d} {vR_:+9.4f} {vV_:+9.4f} "
                  f"{vR_ - vV_:+9.4f} {np.mean(z_par):+6.2f}  "
                  f"{'/'.join(f'{x:+.3f}' for x in tb_par)}")


if __name__ == "__main__":
    main()

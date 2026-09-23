"""A COUNTER-TREND TRIGGER ÖNMAGÁBAN — H1-lánc nélkül, mindkét irányba.

ELŐZMÉNY (2026-09-23, a 13. szakasz): a teljes Csilla-lánc egészében nem ad élt
— a +0,038 R a kilépésből jön —, DE a bontás megmutatta, hogy az M15-ös
kiváltónak **van időzítés-értéke**: ugyanabban az ablakban, ugyanabba az irányba
+0,19…+0,28 R-rel jobb a véletlen pillanatnál. A lánc IRÁNYA viszont rossz
(−0,11…−0,25 R). A felhasználó döntése: vegyük le a triggert a láncról.

A KÉRDÉS (előre rögzítve, a futtatás előtt):

  > Hordoz-e a counter-trend törés + szín-feltétel önmagában — H1-setup nélkül,
  > mindkét irányba — olyan IDŐZÍTÉS-élt, ami a saját irány-arányára illesztett
  > VÉLETLEN belépőnél jobb, és a költség után is pozitív?

A KONTROLL (ez dönt, nem a nyers szám): minden valódi belépőhöz egy PÁROSÍTOTT
véletlen belépő — UGYANAZ az irány, véletlen időpont, és a stop a HELYI ATR-hez
skálázva (a valódi belépők stop/ATR arányaiból húzva). Így az irány-arány és a
KOCKÁZAT mérete rögzítve van, és csak az időzítés marad szabad.

⚠ A NYERS STOP-MÉRETET ÁTVINNI A VÉLETLEN BARRA HIBA. Az első változat ezt
csinálta, és a GOLD véletlen kontrollja +3,17 R/kötést adott: egy apró stop egy
trendes szakaszon több száz R-t hoz, mert a stop már nem illik a helyi
mozgékonysághoz. A hibás kontroll miatt úgy tűnt, hogy a véletlen belépő jobb a
szabálynál — a javítással ez megfordult (2026-09-23). A nyers R-t a kilépés (BE + csúszó) amúgy is pozitívba
viszi bármiből (lásd a 13. szakaszt) — a TÖBBLET a lelet, nem a szint.

A szabály a `strategies/csilla_rules.counter_entries`-ből jön: a lánc helyett egy
TELJES ablakot fedő ál-setupot adunk neki irányonként. Így nincs második példány.

Futtatás:
    python tools/research/csilla_trigger.py
    python tools/research/csilla_trigger.py --mod leszuras --korr 4
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "research"))

import lab                                      # noqa: E402
from strategies import csilla_rules as sw       # noqa: E402

SYMS = ["GOLD", "USDJPY", "UsaInd", "UsaTec", "Ger40", "EURUSD", "EURJPY", "UK100"]
BE_AT_R, TRAIL_R, MAX_HOLD_NAP = 0.67, 2.0, 5


def _spread(m1: pd.DataFrame) -> float:
    s = m1["avg_spread"].dropna()
    if not len(s):
        return 0.0
    return float(s[s.index >= s.index.max() - pd.Timedelta(days=365)].median())


def _al_setup(lo: pd.DataFrame, d: int) -> dict:
    """Ál-setup, ami a TELJES keretet lefedi — így a `counter_entries` a lánc
    nélkül is használható, és nem kell második példány a szabályból."""
    return dict(i_break=0, dir=d, level=0.0, hatar=0.0, i_pipa=0,
                t_pipa_close=lo.index[0], t_veg=lo.index[-1], label="")


def egy_par(sym: str, P: dict, rng) -> dict | None:
    m1 = lab.load_m1(sym)
    lo = m1 if P["lo_tf"] <= 1 else sw.resample(m1, P["lo_tf"])
    sp = _spread(m1)
    ps = float(lab.PAIRS[sym]["point_size"])
    et = sw.counter_entries(lo, [_al_setup(lo, -1), _al_setup(lo, +1)], P, spread=sp)
    if not len(et):
        return None
    et = et.sort_values("i").drop_duplicates("i", keep="first")

    def fut(idx, side, slp):
        tr = lab.simulate(lo, idx, side, slp, np.zeros(len(idx)), point_size=ps,
                          max_hold=MAX_HOLD_NAP * 1440 // max(1, P["lo_tf"]),
                          be_at_r=BE_AT_R, trail_r=TRAIL_R, one_at_a_time=True,
                          pair_cfg=lab.PAIRS[sym])
        if not len(tr):
            return None
        R = tr["r"]
        return dict(n=len(R), R=float(R.mean()), sumR=float(R.sum()),
                    t=float(R.mean() / (R.std(ddof=1) / np.sqrt(len(R)))) if len(R) > 1 else 0.0,
                    nyero=float((R > 0).mean()))

    idx = et.i.to_numpy(int)
    side = et.dir.to_numpy(int)
    slp = et.sl_abs.to_numpy(float) / ps
    valos = fut(idx, side, slp)
    if valos is None:
        return None
    # ── PÁROSÍTOTT VÉLETLEN: azonos irány, a stop a HELYI ATR-hez skálázva ──
    a14 = sw.atr(lo["high"].to_numpy(float), lo["low"].to_numpy(float),
                 lo["close"].to_numpy(float), 14)
    _a = a14[idx]
    arany = (et.sl_abs.to_numpy(float) / np.where(np.isfinite(_a) & (_a > 0), _a, np.nan))
    arany = arany[np.isfinite(arany)]
    v_idx = np.sort(rng.choice(np.arange(60, len(lo) - 600), size=len(idx), replace=False))
    _va = a14[v_idx]
    _ok = np.isfinite(_va) & (_va > 0)
    v_idx, _va = v_idx[_ok], _va[_ok]
    o = rng.permutation(len(idx))[:len(v_idx)]
    veletlen = fut(v_idx, side[o], (rng.choice(arany, size=len(v_idx)) * _va) / ps)
    # ── TÜKÖR ──────────────────────────────────────────────────────────────
    tukor = fut(idx, -side, slp)
    return dict(sym=sym, jel=len(et), valos=valos, veletlen=veletlen, tukor=tukor,
                long_arany=float((side > 0).mean()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sym", nargs="*", default=SYMS)
    ap.add_argument("--mod", default="varj_pirosra",
                    choices=("varj_pirosra", "leszuras", "piros_zaras"))
    ap.add_argument("--korr", type=int, default=3)
    ap.add_argument("--tf-pair", default="H1-M15", choices=sorted(sw.TF_PAIRS))
    ap.add_argument("--seed", type=int, default=20260923)
    a = ap.parse_args()
    P = sw.with_tf_pair(dict(sw.DEFAULTS, tf_pair=a.tf_pair,
                             belepo_mod=a.mod, korr_min=a.korr))
    rng = np.random.default_rng(a.seed)
    print(f"COUNTER-TREND TRIGGER ONALLOAN — also keret M{P['lo_tf']}  "
          f"belepo={a.mod}  korr_min={a.korr}")
    print(f"   (BE {BE_AT_R} R, csuszo {TRAIL_R} R, celar nincs, max {MAX_HOLD_NAP} nap, "
          f"valodi spread)\n")
    print(f"   {'par':8} {'kotes':>7} {'long%':>6} {'VALOS R':>9} {'t':>6} "
          f"{'veletlen':>9} {'TOBBLET':>9} {'tukor':>9}")
    sorok = []
    for sym in a.sym:
        try:
            r = egy_par(sym, P, rng)
        except Exception as ex:                       # pragma: no cover
            print(f"   {sym:8} HIBA: {type(ex).__name__}: {ex}")
            continue
        if r is None or r["veletlen"] is None:
            print(f"   {sym:8} (nincs eleg jel)")
            continue
        tobb = r["valos"]["R"] - r["veletlen"]["R"]
        sorok.append((r, tobb))
        print(f"   {sym:8} {r['valos']['n']:7d} {100*r['long_arany']:5.0f}% "
              f"{r['valos']['R']:+9.4f} {r['valos']['t']:+6.2f} "
              f"{r['veletlen']['R']:+9.4f} {tobb:+9.4f} {r['tukor']['R']:+9.4f}")
    if not sorok:
        return
    n = sum(r["valos"]["n"] for r, _ in sorok)
    sR = sum(r["valos"]["sumR"] for r, _ in sorok)
    sV = sum(r["veletlen"]["sumR"] for r, _ in sorok)
    poz = sum(1 for _r, tb in sorok if tb > 0)
    print(f"\n   OSSZEVONT: n={n:,}  valos R={sR/n:+.4f}  veletlen R={sV/n:+.4f}  "
          f"TOBBLET={+(sR - sV)/n:+.4f}   a tobblet pozitiv: {poz}/{len(sorok)} paron")


if __name__ == "__main__":
    main()

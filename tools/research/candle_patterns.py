"""GYERTYA-ALAKZATOK — eloregisztralt meres (2026-09-17, a vault
„Gyertya-alakzatok — eloregisztralt kerdes" jegyzete).

A KERDES: hordoznak-e a klasszikus japan gyertyamintak (doji, kalapacs,
akasztott ember, forditott kalapacs, hullocsillag, elnyelo, harami, attoro /
sotet felho, hajnal- / esti csillag, harom katona / varju, csipesz, marubozu)
M15 es H1 idosikon a TANKONYVI iranyban olyan elt, amely a koltseg utan is
pozitiv, es nem a sodrodas?

MEROHELY: a kimenet-racs (`outcomes.py`: M5 racspont, belepes a gyertya
zarasan, stop 1,5 ATR15, celar 2 R, max 8 ora, valodi spread). A mintak a
`candle_lib`-ben, a jel a zaro gyertya ZARASA utani elso racsponttol (felfuto el).

KET LEPCSO:
  A) szures a TELJES mintan, minta x idosik, az 5 paron osszevonva:
     nettó R (tankonyvi irany), TOBBLET a sajat (par, irany) alapszintjehez
     kepest (= sodrodas levalasztva), tukor (ellenkezo irany ugyanott), evek.
  B) holdout-kereses a meglevo keresogepen (`signal_lib` + a `search.py` /
     `holdout.py` logikaja), CSAK a gyertya-esemenyekkel, 0. es 1. szinten
     (2. szint nincs — az mar illeszt), keresés 2023-01-01 elott, holdout utana.

ELFOGADAS (egyetlen szabaly, a jegyzetbol):
  minta x idosik TALALAT, ha A) nettó R > 0 >= 3/5 paron ES tobblet t >= 2
  osszevontan ES az evek >= 60 %-aban pozitiv a tobblet ES a tukor nettó R-je
  kisebb — ES B) 0. szinten a holdouton is a sajat alapszintje folott van a
  tankonyvi iranyban. A B) 1. szint onmagaban a `holdout.py` harom feltetelevel.

Futtatas:
    python tools/research/candle_patterns.py            # A + B
    python tools/research/candle_patterns.py --csak-a   # csak a szures
    python tools/research/candle_patterns.py --csak pipa,pinbar --elsodleges 5,15
        # csak a nevben ezeket tartalmazo mintak; elsodleges idosikok M5+M15
        # (a „Pipa szignal" eloregisztralt meres, 2026-09-18)
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

import candle_lib
import lab
import signal_lib
from search import MIN_N, VAGAS, _t

SYMS = ["Ger40", "UsaInd", "UsaTec", "GOLD", "USDJPY"]
B_SYMS = ["UsaTec", "UsaInd", "GOLD", "Ger40"]
PRIMARY_TFS = (15, 60)
INFO_TFS = (5, 30, 240)
CSAK: tuple = ()          # ha nem ures: csak az ezeket tartalmazo minta-nevek
T_MIN, YEAR_FRAC, INSTR_MIN, MIN_YEAR_N, TOP = 2.0, 0.60, 3, 30, 100
OPP = {"long": "short", "short": "long"}


# ── kozos: a gyertya-esemenyek az M5 racson (a signal_lib vetitesevel) ───────

def candle_masks(sym: str, racs_ido: pd.DatetimeIndex, tfs) -> dict:
    m1 = lab.load_m1(sym)
    E = {}
    for tf in tfs:
        d = lab.resample(m1, tf)
        zaras = d.index + pd.Timedelta(minutes=tf)
        j = np.searchsorted(zaras, racs_ido, side="right") - 1
        ok = j >= 0
        jj = np.where(ok, j, 0)
        for nev, arr in candle_lib.gyertyak(d["open"].to_numpy(), d["high"].to_numpy(),
                                            d["low"].to_numpy(), d["close"].to_numpy()).items():
            if CSAK and not any(x in nev for x in CSAK):
                continue
            out = np.zeros(len(racs_ido), dtype=bool)
            out[ok] = arr[jj[ok]]
            E[f"M{tf}:{nev}"] = signal_lib.felfuto(out)
    return E


def _load(sym):
    o = pd.read_parquet(ROOT / "data" / "outcomes" / f"{sym}.parquet")
    ido = pd.DatetimeIndex(o["ido"])
    R = {"long": o["long"].to_numpy(float), "short": o["short"].to_numpy(float)}
    return ido, R


# ── A) szures a teljes mintan ────────────────────────────────────────────────

def lepcso_a():
    per_sym = {}       # sym -> {cimke: dict(net, exc, mir, ev)}
    for sym in SYMS:
        p = ROOT / "data" / "outcomes" / f"{sym}.parquet"
        if not p.exists():
            print(f"   ({sym}: nincs kimenet-racs, kihagyva)")
            continue
        ido, R = _load(sym)
        alap = {k: float(np.nanmean(v)) for k, v in R.items()}
        E = candle_masks(sym, ido, PRIMARY_TFS + INFO_TFS)
        ev = ido.year.to_numpy()
        rows = {}
        for cimke, m in E.items():
            d = candle_lib.irany(cimke)
            idx = np.flatnonzero(m)
            net = R[d][idx]
            ok = np.isfinite(net)
            rows[cimke] = {"net": net[ok], "exc": net[ok] - alap[d],
                           "mir": R[OPP[d]][idx][ok], "ev": ev[idx][ok]}
        per_sym[sym] = rows
        print(f"   {sym}: {len(ido):,} racspont, alapszint long {alap['long']:+.4f} "
              f"short {alap['short']:+.4f}, {len(E)} minta-jel", flush=True)

    cimkek = sorted({c for r in per_sym.values() for c in r})
    out = []
    for c in cimkek:
        parts = [per_sym[s][c] for s in per_sym if c in per_sym[s] and len(per_sym[s][c]["net"])]
        if not parts:
            continue
        net = np.concatenate([p["net"] for p in parts])
        exc = np.concatenate([p["exc"] for p in parts])
        mir = np.concatenate([p["mir"] for p in parts])
        ev = np.concatenate([p["ev"] for p in parts])
        mu_n, t_n, n = _t(net)
        mu_e, t_e, _ = _t(exc)
        yrs = pd.Series(exc).groupby(ev).agg(["mean", "size"])
        yrs = yrs[yrs["size"] >= MIN_YEAR_N]
        n_syms_net = sum(p["net"].mean() > 0 for p in parts)
        n_syms_exc = sum(p["exc"].mean() > 0 for p in parts)
        tf = int(c.split(":")[0][1:])
        out.append({"minta": c, "tf": tf, "irany": candle_lib.irany(c), "n": n,
                    "R_net": mu_n, "t_net": t_n, "tobblet": mu_e, "t_tobblet": t_e,
                    "tukor_R": float(np.nanmean(mir)),
                    "parok_net+": f"{n_syms_net}/{len(parts)}",
                    "parok_tobblet+": f"{n_syms_exc}/{len(parts)}",
                    "evek+": f"{int((yrs['mean'] > 0).sum())}/{len(yrs)}",
                    "_ev_frac": float((yrs["mean"] > 0).mean()) if len(yrs) else np.nan,
                    "_n_syms_net": n_syms_net, "_n_parts": len(parts)})
    t = pd.DataFrame(out)
    t["A_atment"] = ((t._n_syms_net >= INSTR_MIN) & (t.t_tobblet >= T_MIN)
                     & (t._ev_frac >= YEAR_FRAC) & (t.tukor_R < t.R_net))
    return t


def _print_a(t: pd.DataFrame):
    cols = ["minta", "irany", "n", "R_net", "t_net", "tobblet", "t_tobblet", "tukor_R",
            "parok_net+", "parok_tobblet+", "evek+", "A_atment"]
    fmt = lambda v: f"{v:+.4f}" if isinstance(v, float) else str(v)
    for tf in PRIMARY_TFS:
        d = t[t.tf == tf].sort_values("tobblet", ascending=False)
        print(f"\n── A) M{tf} (ELSODLEGES) — az 5 paron osszevonva, a teljes minta ──")
        print(d[cols].to_string(index=False, float_format=fmt))
    for tf in INFO_TFS:
        d = t[t.tf == tf].sort_values("tobblet", ascending=False)
        print(f"\n── A) M{tf} (tajekoztato) ──")
        print(d[cols].to_string(index=False, float_format=fmt))


# ── B) holdout-kereses csak a gyertya-esemenyekkel (0. + 1. szint) ───────────

def lepcso_b(sym: str):
    p = ROOT / "data" / "outcomes" / f"{sym}.parquet"
    if not p.exists():
        print(f"   ({sym}: nincs kimenet-racs)")
        return None, None
    ido, R = _load(sym)
    kereso = np.asarray(ido < pd.Timestamp(VAGAS, tz=ido.tz))
    hold = ~kereso
    print(f"\n=== B) {sym}: {kereso.sum():,} kereso / {hold.sum():,} holdout ===", flush=True)
    if kereso.sum() < 20000 or hold.sum() < 20000:
        print("   (tul rovid szakasz, kihagyva)")
        return None, None
    A, E = signal_lib.build(sym, ido)
    an = sorted(A)
    en = sorted(k for k in E if ":gy_" in k and (not CSAK or any(x in k for x in CSAK)))
    alap_k = {k: float(np.nanmean(v[kereso])) for k, v in R.items()}
    alap_h = {k: float(np.nanmean(v[hold])) for k, v in R.items()}
    print(f"   {len(en)} gyertya-esemeny x {len(an)} allapot; alapszint kereso "
          f"L {alap_k['long']:+.4f} S {alap_k['short']:+.4f} | holdout "
          f"L {alap_h['long']:+.4f} S {alap_h['short']:+.4f}", flush=True)

    sorok = []

    def ertekel(maszk, cimke, szint):
        fm = signal_lib.felfuto(maszk)
        ik = np.flatnonzero(fm & kereso)
        ih = np.flatnonzero(fm & hold)
        if len(ik) < MIN_N:
            return
        for irany in ("long", "short"):
            mu, tt, nn = _t(R[irany][ik])
            if nn < MIN_N:
                continue
            mh, th, nh = _t(R[irany][ih]) if len(ih) >= MIN_N else (np.nan, np.nan, len(ih))
            sorok.append({"mintazat": cimke, "szint": szint, "irany": irany,
                          "tankonyvi": irany == candle_lib.irany(cimke.split(" + ")[0]),
                          "n_k": nn, "R_k": mu, "t_k": tt, "tobblet_k": mu - alap_k[irany],
                          "n_h": nh, "R_h": mh, "tobblet_h": mh - alap_h[irany]})

    for e in en:
        ertekel(E[e], e, 0)
    n0 = len(sorok)
    for e in en:
        for a in an:
            ertekel(E[e] & A[a], f"{e} + {a}", 1)
    t = pd.DataFrame(sorok)
    if t.empty:
        print("   (nincs ertekelheto jelolt a keresoben)")
        return None, None
    t["sym"] = sym
    print(f"   {n0} jelolt 0. szinten, {len(t) - n0:,} 1. szinten "
          f"(min. {MIN_N} kotes a keresoben)")
    tag = ("_" + "_".join(CSAK)) if CSAK else ""
    t.to_parquet(ROOT / "data" / f"search_candle{tag}_{sym}.parquet", index=False)

    # ── holdout: a harom teszt (holdout.py) — csak a holdouton is ertekelheto jeloltek
    h = t[np.isfinite(t.R_h)].copy()
    if len(h) < 50:
        print("   (tul keves holdouton ertekelheto jelolt)")
        return t, None
    print(f"   {len(h):,} jelolt a holdouton is ertekelheto")
    for sz in sorted(h.szint.unique()):
        d = h[h.szint == sz]
        top = d.nlargest(min(20, len(d)), "tobblet_k")
        print(f"   szint {sz}: {len(d):>6,} db | kereso tobblet {d.tobblet_k.mean():+.4f} | "
              f"holdout tobblet {d.tobblet_h.mean():+.4f} | top20 holdout {top.tobblet_h.mean():+.4f}"
              f" ({int((top.tobblet_h > 0).sum())}/{len(top)} poz.)")
    rho = h.tobblet_k.corr(h.tobblet_h, method="spearman")
    n = len(h)
    tr = rho * np.sqrt((n - 2) / max(1e-12, 1 - rho ** 2))
    top = h.nlargest(min(TOP, n), "tobblet_k").tobblet_h.to_numpy(float)
    rng = np.random.default_rng(0)
    vel = np.array([h.tobblet_h.sample(len(top), random_state=int(s)).mean()
                    for s in rng.integers(0, 10**6, 500)])
    pv = float((vel >= top.mean()).mean())
    f1, f2, f3 = top.mean() > 0, tr > 2, pv < 0.05
    print(f"   rangkorrelacio {rho:+.4f} (t {tr:+.1f}) | top-{len(top)} holdout-tobblet "
          f"{top.mean():+.4f} vs veletlen {vel.mean():+.4f}±{vel.std():.4f}, p={pv:.3f}")
    print(f"   -> holdout.py-itelet: {'TALALAT' if (f1 and f2 and f3) else 'NINCS bizonyitott talalat'} "
          f"(poz {f1}, elorejelzo {f2}, veri a veletlent {f3})")
    itelet = {"sym": sym, "rho": rho, "t_rho": tr, "top_h": float(top.mean()),
              "p": pv, "talalat": bool(f1 and f2 and f3)}
    return t, itelet


def main():
    global CSAK, PRIMARY_TFS, INFO_TFS
    pd.set_option("display.width", 250)
    csak_a = "--csak-a" in _sys.argv
    argv = _sys.argv[1:]
    if "--csak" in argv:
        CSAK = tuple(argv[argv.index("--csak") + 1].split(","))
    if "--elsodleges" in argv:
        PRIMARY_TFS = tuple(int(x) for x in argv[argv.index("--elsodleges") + 1].split(","))
        INFO_TFS = tuple(tf for tf in (5, 15, 30, 60, 240) if tf not in PRIMARY_TFS)
    if CSAK:
        print(f"CSAK: {CSAK}; elsodleges idosikok: {PRIMARY_TFS}")
    print("════ A) SZURES A TELJES MINTAN ════", flush=True)
    ta = lepcso_a()
    _print_a(ta)
    ta.to_csv(ROOT / "data" / ("candle_A" + ("_" + "_".join(CSAK) if CSAK else "") + ".csv"),
              index=False)
    atment = ta[ta.A_atment & ta.tf.isin(PRIMARY_TFS)]
    print(f"\nA) atment (elsodleges idosikok): {len(atment)} / "
          f"{int(ta.tf.isin(PRIMARY_TFS).sum())}")
    for _, r in atment.iterrows():
        print(f"   {r.minta}  tobblet {r.tobblet:+.4f} t {r.t_tobblet:+.2f} evek {r['evek+']} "
              f"parok {r['parok_net+']}")
    if csak_a:
        return

    print("\n════ B) HOLDOUT-KERESES (csak gyertya-esemenyek, 0.+1. szint) ════", flush=True)
    tabs, iteletek = [], []
    for sym in B_SYMS:
        t, it = lepcso_b(sym)
        if t is not None:
            tabs.append(t)
        if it is not None:
            iteletek.append(it)
    if not tabs:
        return
    tb = pd.concat(tabs, ignore_index=True)

    # 0. szint, tankonyvi irany, holdout — a B) feltetel az A)-n atment mintakhoz
    l0 = tb[(tb.szint == 0) & tb.tankonyvi & np.isfinite(tb.R_h)]
    print("\n── B) 0. szint a HOLDOUTON, tankonyvi irany, paronkent (tobblet_h) ──")
    piv = l0.pivot_table(index="mintazat", columns="sym", values="tobblet_h", aggfunc="first")
    nh = l0.groupby("mintazat").n_h.sum()
    wsum = (l0.tobblet_h * l0.n_h).groupby(l0.mintazat).sum() / nh
    piv["OSSZ(sulyozott)"] = wsum
    piv["n_h"] = nh
    print(piv.round(4).to_string())

    print("\n════ ITELET ════")
    for _, r in atment.iterrows():
        w = wsum.get(r.minta, np.nan)
        if not np.isfinite(w):
            print(f"   {r.minta}: A) atment; B) a holdouton NEM ERTEKELHETO "
                  f"(< {MIN_N} kotes a keresoben) -> nincs bizonyitott talalat")
            continue
        print(f"   {r.minta}: A) atment; B) holdout tobblet {w:+.4f} -> "
              f"{'TALALAT' if w > 0 else 'BUKOTT a holdouton'}")
    if atment.empty:
        print("   egyetlen minta x idosik sem ment at az A) lepcson -> nincs talalat")
    print("   B) 1. szint (minta + 1 allapot), holdout.py-itelet paronkent: "
          + ", ".join(f"{i['sym']}={'TALALAT' if i['talalat'] else 'nincs'}" for i in iteletek))


if __name__ == "__main__":
    main()

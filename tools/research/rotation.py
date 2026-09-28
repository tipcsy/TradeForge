"""ROTACIOS MATRIX: a mult idoszak nyertese nyer-e a kovetkezoben is?

A kerdes (2026-09-28): „lehet, hogy az egyik evben ez a strategia megy jol, a
masikban egy masik — probaljunk mintazatot keresni ebben."

A CSAPDA, amit a meres kikuszobol: ha N nulla varhato erteku strategiad van,
MINDEN evben lesz koztuk egy „jol meno" — pusztan veletlenbol. Visszanezve ez
rotacionak latszik. Az egyetlen ervenyes kerdes: az N. idoszak rangsora
ELOREJELZI-E az N+1.-et.

Mit mer:
  1. KOTES-NAPLO. Az `indicator_screen` 23 szabalya + a `rules_long` katalogusa
     (24), 5 instrumentumon, LONG es SHORT kulon -> ~470 „strategia". M15 jel,
     M1 vegrehajtas, SL 1,5 ATR, TP 2R, max 480 perc — az indicator_screen
     konvencioi. KOLTSEGGEL: spread + jutalek + SWAP (`pair_cfg`).
  2. MATRIX: strategia x idoszak (honap / negyedev / ev) -> nettó R-osszeg.
  3. HAROM TESZT, mindegyik a KOZOS IDOSZAK-KEVERES null ellen: a periodusok
     sorrendjet egyutt keverjuk minden strategiara. Ez MEGTARTJA a statikus
     kulonbsegeket (ami mindig jobb, a keveres utan is jobb) es a
     strategiak kozti egyideju korrelaciot, csak az IDOBELI egymasutanisagot
     toeri el. Ami a null felett van, az valodi rotacio/perzisztencia.
       A. rangsor-perzisztencia: Spearman(perf_t, perf_t+1) a strategiakon at
       B. rotacio: a mult L idoszak top-K strategiaja a kovetkezo idoszakban
       C. idosor-szuro: minden strategia csak akkor fut, ha a mult L idoszaka > 0

ELORE ROGZITETT ELFOGADAS (a futtatas ELOTT irva, 2026-09-28):
  Elsodleges konfiguracio: NEGYEDEVES atsulyozas, L = 4 negyedev (1 ev),
  K = 10, a 4 instrumentumos panelen (GOLD, USDJPY, UsaTec, UsaInd; 2017-04-tol).
  A rotacio akkor ER VALAMIT, ha MIND teljesul:
    (1) nettó atlag R / negyedev > 0, t >= 2 (a negyedevek a klaszterek),
    (2) az evek >= 60%-aban pozitiv,
    (3) a kozos-keveres null felett p < 0,05,
    (4) a 13 eves (GOLD+USDJPY, 2013-tol) panelen is pozitiv es a null felett.
  Minden mas konfiguracio (honap / ev, L, K, a forditott „vesztes-visszater"
  valtozat) MASODLAGOS: tobbszoros teszteles, csak iranyt mutat.

VARAKOZAS (joslat, nem meres): a napi parameter-valtasnal a rangsor-korrelacio
+0,01 volt, a rezsim-cimke a multat irja le. Azt varom, hogy a statikus resz
(a shortok swapot kapnak, a longok fizetnek) ad pozitiv nyers perzisztenciat,
de a keveres-null felett nem marad semmi.

EREDMENY (2026-09-28, 468 strategia, 2,55 M kotes) — MEGBUKOTT:
  Elsodleges: top-10 = -5,70 R/negyedev (t=-4,08), null -6,45, p=0,24;
  az evek 11%-aban pozitiv. A 13 eves panelen -5,34 (p=0,07). 0/207
  masodlagos konfiguracio pozitiv ES a null felett (veletlenbol ~10 varhato).
  VAN valodi idobeli perzisztencia (Spearman 0,33 vs null 0,27, p=0,001,
  minden panelen es idoszak-hosszon), de a VESZTES oldalon el: a bottom-K
  a null alatt 7 R-rel, a top-K felett csak 0,75-tel. R/kotesre szamolva is
  (0,19 vs 0,12), de a top-10 R/kotes szerint valasztva -0,108 R/kotes
  (null -0,099). Vagyis: a rossz strategiak rosszak maradnak, a jok nem
  maradnak jok -> a rotacio nem kereskedheto.

Futtatas:  python tools/research/rotation.py            (naplo + elemzes)
           python tools/research/rotation.py --elemzes  (csak elemzes a mentett naplobol)
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

import lab

SYMS = ["GOLD", "USDJPY", "UsaTec", "UsaInd", "Ger40"]
TF = 15
SL_ATR = 1.5
TP_RR = 2.0
MAX_HOLD = 480
MIN_KOTES = 200
NAPLO = ROOT / "data" / "rotation_trades.parquet"
KIMENET = ROOT / "data" / "rotation_result.csv"

PANEL_FO = (["GOLD", "USDJPY", "UsaTec", "UsaInd"], "2017-04-01")
PANEL_HOSSZU = (["GOLD", "USDJPY"], "2013-07-01")
PANEL_OT = (SYMS, "2022-01-01")
VEG = "2026-07-01"          # az utolso TELJES negyedev vege (kizarolagos)
N_NULL = 2000
SEED = 20260928


# ── 1. jelek ────────────────────────────────────────────────────────────────

def _jelek(sym: str) -> dict:
    """{szabaly: (m15_idx, irany)} egy szimbolumra, mindket katalogusbol."""
    import indicator_screen as IS
    import rules_long as RL
    m1 = lab.load_m1(sym)
    d = lab.resample(m1, TF)
    h = d["high"].to_numpy(float); l = d["low"].to_numpy(float)
    c = d["close"].to_numpy(float)
    atr = lab.atr(h, l, c, 14)
    atr = np.where(atr > 0, atr, np.nan)
    out = {}
    for nev, sig in IS.build_rules(d).items():
        idx = np.flatnonzero(sig != 0)
        out[nev] = (idx, sig[idx].astype(np.int8))
    C = dict(d=d, c=c, h=h, l=l, atr=atr)
    for nev, fn in RL.CATALOG.items():
        idx, s = fn(C)
        out[nev] = (np.asarray(idx, np.int64), np.asarray(s, np.int8))
    return {"d_index": d.index, "atr": atr, "jelek": out}


def _szimulal(args):
    sym, nev, irany, idx15, d_index, atr = args
    m1 = lab.load_m1(sym)
    ps = float(lab.PAIRS[sym]["point_size"])
    sel = idx15[(idx15 > 60) & (idx15 < len(d_index) - 1)]
    sel = sel[np.isfinite(atr[sel])]
    if len(sel) < MIN_KOTES:
        return None
    pos = np.clip(m1.index.searchsorted(d_index[sel]) + TF - 1, 0, len(m1) - 1)
    slp = SL_ATR * atr[sel] / ps
    tr = lab.simulate(m1, pos, np.full(len(pos), irany, dtype=int), slp,
                      slp * TP_RR, ps, max_hold=MAX_HOLD,
                      pair_cfg=lab.PAIRS[sym])
    if len(tr) < MIN_KOTES:
        return None
    return pd.DataFrame({
        "strat": f"{sym}|{nev}|{'L' if irany > 0 else 'S'}",
        "sym": sym, "ido": m1.index[tr["i_close"]], "r": tr["r"]})


def naplo_epites():
    t0 = time.time()
    with ProcessPoolExecutor(len(SYMS)) as ex:
        J = dict(zip(SYMS, ex.map(_jelek, SYMS)))
    print(f"jelek kesz ({time.time() - t0:.0f} s)", flush=True)
    feladat = []
    for sym, j in J.items():
        for nev, (idx, s) in j["jelek"].items():
            for irany in (1, -1):
                feladat.append((sym, nev, irany, idx[s == irany],
                                j["d_index"], j["atr"]))
    print(f"{len(feladat)} szimulacio ...", flush=True)
    darabok = []
    with ProcessPoolExecutor(12) as ex:
        for k, df in enumerate(ex.map(_szimulal, feladat, chunksize=4), 1):
            if df is not None:
                darabok.append(df)
            if k % 50 == 0:
                print(f"  {k}/{len(feladat)}  ({time.time() - t0:.0f} s)", flush=True)
    napl = pd.concat(darabok, ignore_index=True)
    napl.to_parquet(NAPLO)
    print(f"naplo: {len(napl)} kotes, {napl.strat.nunique()} strategia -> {NAPLO}")
    return napl


# ── 2. matrix ───────────────────────────────────────────────────────────────

def matrix(napl: pd.DataFrame, syms, kezdet, freq: str) -> pd.DataFrame:
    """idoszak x strategia nettó R-osszeg; a teljes idoszakok, hiany = 0 kotes."""
    x = napl[napl.sym.isin(syms)]
    ido = x.ido.dt.tz_convert(None) if x.ido.dt.tz is not None else x.ido
    x = x.assign(per=ido.dt.to_period(freq))
    x = x[(ido >= kezdet) & (ido < VEG)]
    M = x.pivot_table(index="per", columns="strat", values="r",
                      aggfunc="sum", fill_value=0.0)
    teljes = pd.period_range(pd.Timestamp(kezdet), pd.Timestamp(VEG) - pd.Timedelta(days=1),
                             freq=freq)
    return M.reindex(teljes, fill_value=0.0)


# ── 3. tesztek ──────────────────────────────────────────────────────────────

def _rang(a):
    return a.argsort(axis=-1).argsort(axis=-1).astype(float)


def perzisztencia(X: np.ndarray) -> float:
    """atlagos Spearman az egymast koveto idoszakok kozt, a strategiakon at."""
    R = _rang(X)
    a, b = R[:-1], R[1:]
    a = a - a.mean(1, keepdims=True); b = b - b.mean(1, keepdims=True)
    return float(np.mean((a * b).sum(1) / np.sqrt((a * a).sum(1) * (b * b).sum(1))))


def rotacio(X: np.ndarray, L: int, K: int, forditott=False) -> np.ndarray:
    """idoszakonkenti hozam: a mult L idoszak top-K (vagy bottom-K) atlaga."""
    cs = np.cumsum(np.vstack([np.zeros(X.shape[1]), X]), 0)
    mult = cs[L:-1] - cs[:-L - 1]                # t = L..T-1 elotti L idoszak
    kov = X[L:]
    o = np.argsort(mult, axis=1)
    val = o[:, :K] if forditott else o[:, -K:]
    return np.take_along_axis(kov, val, 1).mean(1)


def idosor_szuro(X: np.ndarray, L: int) -> np.ndarray:
    cs = np.cumsum(np.vstack([np.zeros(X.shape[1]), X]), 0)
    mult = cs[L:-1] - cs[:-L - 1]
    kov = X[L:]
    akt = mult > 0
    n = akt.sum(1)
    return np.where(n > 0, (kov * akt).sum(1) / np.maximum(n, 1), 0.0)


def _t(v):
    v = np.asarray(v, float)
    return float(v.mean() / (v.std(ddof=1) / np.sqrt(len(v)))) if len(v) > 2 and v.std() > 0 else np.nan


def _ev_pozitiv(v, per):
    ev = pd.Series(v, index=[p.year for p in per]).groupby(level=0).sum()
    return float((ev > 0).mean())


def ertekel(M: pd.DataFrame, L: int, K: int, cimke: str, rng) -> list[dict]:
    X = M.to_numpy(float)
    per = M.index[L:]
    alap = X[L:].mean(1)                        # minden strategia egyenlo sullyal
    sorok = []
    nulls = {"top": [], "bottom": [], "ts": [], "rho": []}
    for _ in range(N_NULL):
        Xp = X[rng.permutation(len(X))]
        nulls["top"].append(rotacio(Xp, L, K).mean())
        nulls["bottom"].append(rotacio(Xp, L, K, True).mean())
        nulls["ts"].append(idosor_szuro(Xp, L).mean())
        nulls["rho"].append(perzisztencia(Xp))
    rho = perzisztencia(X)
    for nev, v, kulcs in (("top-K", rotacio(X, L, K), "top"),
                          ("bottom-K (visszater)", rotacio(X, L, K, True), "bottom"),
                          ("idosor-szuro", idosor_szuro(X, L), "ts")):
        nl = np.asarray(nulls[kulcs])
        sorok.append({
            "panel": cimke, "L": L, "K": K, "szabaly": nev, "n_per": len(v),
            "R/per": v.mean(), "t": _t(v), "ev+%": _ev_pozitiv(v, per),
            "null_atl": nl.mean(), "p_null": float((nl >= v.mean()).mean()),
            "alap_R/per": alap.mean(),
            "rho": rho, "rho_null": float(np.mean(nulls["rho"])),
            "p_rho": float((np.asarray(nulls["rho"]) >= rho).mean()),
        })
    return sorok


def elemzes(napl: pd.DataFrame):
    pd.set_option("display.width", 240)
    rng = np.random.default_rng(SEED)
    # csak a stabil (elegendo koteses) strategiak
    n = napl.groupby("strat").size()
    napl = napl[napl.strat.isin(n[n >= MIN_KOTES].index)]
    print(f"{napl.strat.nunique()} strategia, {len(napl)} kotes\n")

    sorok = []
    for (syms, kezdet), pnev in ((PANEL_FO, "4 instr. 2017-"),
                                 (PANEL_HOSSZU, "GOLD+USDJPY 2013-"),
                                 (PANEL_OT, "5 instr. 2022-")):
        for freq, Ls in (("Q", (1, 2, 4)), ("M", (3, 6, 12)), ("Y", (1, 2))):
            M = matrix(napl, syms, kezdet, freq)
            for L in Ls:
                for K in (5, 10, 20):
                    if M.shape[0] - L < 4:
                        continue
                    for s in ertekel(M, L, K, f"{pnev} {freq}", rng):
                        sorok.append(s)
            print(f"  {pnev} {freq}: {M.shape[0]} idoszak x {M.shape[1]} strategia", flush=True)
    T = pd.DataFrame(sorok)
    T.to_csv(KIMENET, index=False, sep=";", decimal=",")

    f = lambda v: f"{v:+.3f}"
    print("\n=== ELSODLEGES (elore rogzitett): 4 instr., negyedev, L=4, K=10 ===")
    fo = T[(T.panel == "4 instr. 2017- Q") & (T.L == 4) & (T.K == 10)]
    print(fo.to_string(index=False, float_format=f))
    print("\n=== 4. feltetel: 13 eves panel, negyedev, L=4, K=10 ===")
    print(T[(T.panel == "GOLD+USDJPY 2013- Q") & (T.L == 4) & (T.K == 10)]
          .to_string(index=False, float_format=f))

    print("\n=== RANGSOR-PERZISZTENCIA (Spearman t -> t+1), idoszak-hossz szerint ===")
    print(T.drop_duplicates(["panel"])[["panel", "rho", "rho_null", "p_rho"]]
          .to_string(index=False, float_format=f))

    print(f"\n=== MASODLAGOS racs: {len(T)} konfiguracio (tobbszoros teszteles!) ===")
    jo = T[(T["R/per"] > 0) & (T.p_null < 0.05)]
    print(f"   pozitiv ES a null felett (p<0,05): {len(jo)} / {len(T)}  "
          f"(veletlenbol varhato ~{0.05 * len(T):.0f})")
    if len(jo):
        print(jo.sort_values("p_null").head(15).to_string(index=False, float_format=f))
    print(f"\nteljes tabla: {KIMENET}")


if __name__ == "__main__":
    if "--elemzes" in _sys.argv and NAPLO.exists():
        elemzes(pd.read_parquet(NAPLO))
    else:
        elemzes(naplo_epites())

"""NAPON BELULI, SODRODASTOL FUGGETLEN el keresese — kis idosikon.

Miert most: a [[drift-equals-financing]] lelet szerint a hosszu oldal brutto ele
(+0,089R) MAGA a reszvenypiaci sodrodas, es a CFD-finanszirozas (-0,079R) pont
ennyit ker erte. Tokeattetellel a sodrodas nem gyujtheto be. Marad az, ami NEM
sodrodas — es az csak napon beluli, iranyban SZIMMETRIKUS el lehet.

KET SZIGORITAS az eddigiekhez kepest:

  1. MINDEN pozicio a session vegeig zar -> NINCS SWAP. A koltseg csak a spread.
  2. A LONG es a SHORT oldalt KULON merjuk, es az elfogadashoz MINDKETTONEK
     pozitivnak kell lennie. Egy sodrodas-alapu "el" ezen bukik: a long pozitiv,
     a short negativ. Ez a legolcsobb es legerosebb sodrodas-szuro.

Plusz elfogadasi feltetel (valtozatlanul, lasd README):
  t >= 2  ES  az evek >=60%-aban pozitiv  ES  >=3 instrumentumon pozitiv

UJ INFORMACIO, amit eddig nem hasznaltunk: a gyertyak most VALODI tickbol
epulnek, tehat a `volume` (tick-darabszam) es a spread-dinamika
(`avg_spread` vs `close_spread`) valodi mikrostruktura-jel, nem becsles.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

import lab

SYMS = ["Ger40", "UsaInd", "UsaTec", "GOLD", "USDJPY"]
# session (szerver-ido perc): a LIKVID ablak, amiben kereskedunk es zarunk
SESS = {"Ger40": (540, 1050), "UsaInd": (930, 1320), "UsaTec": (930, 1320),
        "GOLD": (540, 1320), "USDJPY": (480, 1320)}
TF = 5                      # M5 — eleg gyors, de nem fulladunk a zajba
HOLDS = (6, 12, 24)         # 30 / 60 / 120 perc
SL_ATR = 1.5

_C = {}


def ctx(sym):
    if sym in _C:
        return _C[sym]
    m1 = lab.load_m1(sym)
    d = lab.resample(m1, TF)
    h, l, c, o = (d[x].to_numpy(float) for x in ("high", "low", "close", "open"))
    v = d["volume"].to_numpy(float)
    atr = lab.atr(h, l, c, 14)
    atr = np.where(atr > 0, atr, np.nan)
    ps = lab.PAIRS[sym]["point_size"]
    csp = d["close_spread"].to_numpy(float)
    asp = d["avg_spread"].to_numpy(float)
    csp = np.where(np.isfinite(csp) & (csp > 0), csp, asp)
    mod = (d.index.hour * 60 + d.index.minute).to_numpy()
    day = np.asarray(d.index.normalize().view("int64"))
    lo, hi = SESS[sym]
    C = dict(d=d, h=h, l=l, c=c, o=o, v=v, atr=atr, ps=ps, sp=csp,
             mod=mod, day=day, sess=(lo, hi), sym=sym,
             inses=(mod >= lo) & (mod < hi))
    _C[sym] = C
    return C


# ── kimenet: mindig a session vegeig zarunk -> NINCS SWAP ───────────────────
def outcome(C, idx, side, hold):
    c, atr, sp, ps = C["c"], C["atr"], C["sp"], C["ps"]
    mod, day = C["mod"], C["day"]
    hi_min = C["sess"][1]
    n = len(c)
    rows = []
    for k in range(len(idx)):
        i, s = int(idx[k]), int(side[k])
        if not np.isfinite(atr[i]) or not np.isfinite(sp[i]):
            continue
        j = min(i + hold, n - 1)
        # a session vegeig (vagy a nap valtasaig) zarunk
        while j > i and (day[j] != day[i] or mod[j] > hi_min):
            j -= 1
        if j <= i:
            continue
        net = s * (c[j] - c[i]) - sp[i]        # egy teljes spread kor-fordulora
        rows.append((C["d"].index[i], net / (SL_ATR * atr[i]), s))
    if not rows:
        return None
    return pd.DataFrame(rows, columns=["t", "R", "dir"])


# ── szabalyok: mind (C) -> (idx, side), CSAK session-on belul ───────────────
def _fire(C, up, dn, cooldown=0):
    ok = C["inses"]
    raw = np.where(up & ok, 1, np.where(dn & ok, -1, 0))
    prev = np.concatenate([[0], raw[:-1]])
    f = (raw != 0) & (prev != raw)
    idx = np.nonzero(f)[0]
    if cooldown and len(idx):
        keep, last = [], -10 ** 9
        for i in idx:
            if i - last >= cooldown:
                keep.append(i); last = i
        idx = np.array(keep, np.int64)
    return idx, raw[idx].astype(np.int8)


def orb(C, orb_bars=6, win=24, fade=False):
    """Nyitasi tartomany attorese / fade-je."""
    lo_m = C["sess"][0]
    mod, h, l, c = C["mod"], C["h"], C["l"], C["c"]
    day = C["day"]
    uniq, st = np.unique(day, return_index=True)
    st = list(st) + [len(day)]
    idx, side = [], []
    for k in range(len(uniq)):
        a, b = st[k], st[k + 1]
        m = mod[a:b]
        inor = (m >= lo_m) & (m < lo_m + orb_bars * TF)
        if inor.sum() < 2:
            continue
        hh, ll = h[a:b][inor].max(), l[a:b][inor].min()
        w = np.nonzero((m >= lo_m + orb_bars * TF) &
                       (m < lo_m + (orb_bars + win) * TF))[0]
        for p in w:
            j = a + p
            d = 1 if c[j] > hh else (-1 if c[j] < ll else 0)
            if d:
                idx.append(j); side.append(-d if fade else d)
                break
    return np.array(idx, np.int64), np.array(side, np.int8)


def donch(C, N=24, fade=False):
    h, l, c = C["h"], C["l"], C["c"]
    hi = pd.Series(h).rolling(N).max().shift(1).to_numpy()
    lo = pd.Series(l).rolling(N).min().shift(1).to_numpy()
    return _fire(C, c > hi, c < lo)[0], (
        _fire(C, c > hi, c < lo)[1] * (-1 if fade else 1)).astype(np.int8)


def vwap_rev(C, k=2.0, fade=True):
    d = C["d"]
    day = pd.Index(C["day"])
    tp = (C["h"] + C["l"] + C["c"]) / 3
    cv = pd.Series(C["v"], index=d.index).groupby(day.values).cumsum().to_numpy()
    ct = pd.Series(tp * C["v"], index=d.index).groupby(day.values).cumsum().to_numpy()
    vw = np.where(cv > 0, ct / np.where(cv > 0, cv, 1), np.nan)
    z = (C["c"] - vw) / C["atr"]
    i, s = _fire(C, z >= k, z <= -k, cooldown=6)
    return i, (s * (-1 if fade else 1)).astype(np.int8)


def vol_spike(C, mult=3.0, fade=False):
    """Tick-darabszam kiugras — VALODI mikrostruktura (tickbol epult gyertya)."""
    v = C["v"]
    base = pd.Series(v).rolling(96).median().to_numpy()
    spike = v >= mult * base
    up = spike & (C["c"] > C["o"])
    dn = spike & (C["c"] < C["o"])
    i, s = _fire(C, up, dn, cooldown=6)
    return i, (s * (-1 if fade else 1)).astype(np.int8)


def spread_spike(C, mult=2.5, fade=True):
    """Spread-kitagulas = stressz. A fade azt teszteli, visszater-e."""
    sp = C["sp"]
    base = pd.Series(sp).rolling(288).median().to_numpy()
    stress = sp >= mult * base
    up = stress & (C["c"] > C["o"])
    dn = stress & (C["c"] < C["o"])
    i, s = _fire(C, up, dn, cooldown=6)
    return i, (s * (-1 if fade else 1)).astype(np.int8)


def streak(C, k=4, fade=True):
    up = pd.Series(C["c"] > C["o"]).rolling(k).sum().to_numpy() == k
    dn = pd.Series(C["c"] < C["o"]).rolling(k).sum().to_numpy() == k
    i, s = _fire(C, up, dn, cooldown=k)
    return i, (s * (-1 if fade else 1)).astype(np.int8)


def range_pos(C, k=0.8, fade=True):
    """A NAPI tartomanyban elfoglalt hely (0..1) szelso ertekei."""
    d = C["d"]
    day = pd.Index(C["day"])
    hi = pd.Series(C["h"], index=d.index).groupby(day.values).cummax().to_numpy()
    lo = pd.Series(C["l"], index=d.index).groupby(day.values).cummin().to_numpy()
    rng = np.where(hi - lo > 0, hi - lo, np.nan)
    p = (C["c"] - lo) / rng
    i, s = _fire(C, p >= k, p <= 1 - k, cooldown=6)
    return i, (s * (-1 if fade else 1)).astype(np.int8)


CATALOG = {}
for ob in (3, 6, 12):
    CATALOG[f"ORB{ob*TF}p_tores"] = lambda C, ob=ob: orb(C, ob)
    CATALOG[f"ORB{ob*TF}p_fade"] = lambda C, ob=ob: orb(C, ob, fade=True)
for N in (12, 24, 48):
    CATALOG[f"donch{N}_tores"] = lambda C, N=N: donch(C, N)
    CATALOG[f"donch{N}_fade"] = lambda C, N=N: donch(C, N, fade=True)
for k in (1.5, 2.5):
    CATALOG[f"vwap{k}_fade"] = lambda C, k=k: vwap_rev(C, k)
    CATALOG[f"vwap{k}_folyt"] = lambda C, k=k: vwap_rev(C, k, fade=False)
for m in (3.0, 5.0):
    CATALOG[f"volugras{m}_folyt"] = lambda C, m=m: vol_spike(C, m)
    CATALOG[f"volugras{m}_fade"] = lambda C, m=m: vol_spike(C, m, fade=True)
CATALOG["spreadugras_fade"] = spread_spike
CATALOG["spreadugras_folyt"] = lambda C: spread_spike(C, fade=False)
for k in (3, 5):
    CATALOG[f"sorozat{k}_fade"] = lambda C, k=k: streak(C, k)
    CATALOG[f"sorozat{k}_folyt"] = lambda C, k=k: streak(C, k, fade=False)
CATALOG["napi_szel_fade"] = range_pos
CATALOG["napi_szel_folyt"] = lambda C: range_pos(C, fade=False)


def summarize(df, label):
    if df is None or len(df) < 200:
        return None
    r = df.R
    se = r.std(ddof=1) / np.sqrt(len(r))
    ev = df.groupby(df.t.dt.year).R.mean()
    sy = df.groupby("sym").R.mean()
    lo = df[df.dir > 0].R
    sh = df[df.dir < 0].R
    return {"jel": label, "n": len(r), "R": float(r.mean()),
            "t": float(r.mean() / se) if se > 0 else 0.0,
            "R_long": float(lo.mean()) if len(lo) else np.nan,
            "R_short": float(sh.mean()) if len(sh) else np.nan,
            "mindketto": float(min(lo.mean() if len(lo) else -9,
                                   sh.mean() if len(sh) else -9)),
            "ev_poz%": float(100 * (ev > 0).mean()), "ev_db": len(ev),
            "instr_poz": int((sy > 0).sum())}


def main():
    pd.set_option("display.width", 250)
    for sym in SYMS:
        print(f"   … {sym}", flush=True)
        ctx(sym)
    rows = []
    for name, fn in CATALOG.items():
        ent = {}
        for sym in SYMS:
            try:
                ent[sym] = fn(ctx(sym))
            except Exception as ex:
                print(f"   ! {name}/{sym}: {ex}", flush=True)
        for hold in HOLDS:
            parts = []
            for sym, (i, s) in ent.items():
                if len(i) < 50:
                    continue
                o = outcome(ctx(sym), i, s, hold)
                if o is not None:
                    o["sym"] = sym
                    parts.append(o)
            if not parts:
                continue
            df = pd.concat(parts, ignore_index=True)
            r = summarize(df, f"{name} | h{hold * TF}p")
            if r:
                rows.append(r)
    res = pd.DataFrame(rows)
    res.to_csv(ROOT / "data" / "intraday_screen.csv", index=False)

    print("\n=== ELFOGADVA: t>=2 ES ev>=60% ES instr>=3 ES MINDKET IRANY pozitiv ===")
    ok = res[(res.t >= 2) & (res["ev_poz%"] >= 60) & (res.instr_poz >= 3)
             & (res.mindketto > 0)]
    print(ok.sort_values("t", ascending=False).to_string(index=False,
          float_format=lambda x: f"{x:8.3f}") if len(ok)
          else "(egyetlen kombinacio sem felel meg)")

    print("\n=== a 15 legjobb 'mindketto' (a sodrodas-fuggetlenseg merceje) ===")
    print(res.sort_values("mindketto", ascending=False).head(15)
             .to_string(index=False, float_format=lambda x: f"{x:8.3f}"))

    print("\n=== osszkep ===")
    print(f"  kombinaciok: {len(res)}   |  t>=2: {int((res.t >= 2).sum())}   "
          f"t<=-2: {int((res.t <= -2).sum())}")
    print(f"  R atlag {res.R.mean():+.4f}  |  ahol MINDKET irany pozitiv: "
          f"{int((res.mindketto > 0).sum())} db")


if __name__ == "__main__":
    main()

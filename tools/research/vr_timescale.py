"""MILYEN IDOTAVON MUKODIK a variancia-arany mint rezsim-mutato?

A felhasznalo kerdese (2026-08-28): "naponta tobbszor valtozik? Hetente? Havonta?
Evente? Mivel napon beluli kereskedest preferalok, az lenne jo, ha napon belul
tudna mukodni."

Harom kulon kerdes, es MINDHARMAT meg kell valaszolni ahhoz, hogy hasznalhato
legyen:

  1. ZAJ — mekkora ablak kell egy MEGBIZHATO becsleshez? A VR variancia-alapu,
     a hibaja ~1/sqrt(n). Egy nap M5-on ~100-160 gyertya -> SE ~0,09, mikozben
     a kimutatando jel (0,92 -> 1,00) mindossze 0,08. Ha a zaj nagyobb a jelnel,
     a mutato hasznalhatatlan, barmilyen szep is az eves atlaga.

  2. PERZISZTENCIA — meddig tart egy allapot? Ha a VR naponta ide-oda ugral,
     nincs mire kapcsolni. Ha honapokig kitart, akkor van.

  3. ELOREJELZO-E? Ez a lenyeg. Egy MULTBELI ablakon mert VR megmondja-e a
     KOVETKEZO idoszak VR-jet (es a strategia eredmenyet)? Ha csak leiro, akkor
     utolag magyaraz, de nem hasznalhato.
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
TF = 5
# q=6 (30 perc): a NAPON BELULI kerdeshez ez az egyetlen jarhato horizont.
# q=24 (2 ora) egy napra nem is szamolhato — 8 blokkhoz 192 gyertya kellene,
# egy nap M5-on ~100-160 van. A 30 perces 8 blokkhoz 48 eleg.
Q = 6


def vr(r: np.ndarray, q: int = Q) -> float:
    r = r[np.isfinite(r)]
    n = (len(r) // q) * q
    if n < q * 8:
        return np.nan
    r = r[:n]
    v1 = np.var(r, ddof=1)
    if v1 <= 0:
        return np.nan
    vq = np.var(r.reshape(-1, q).sum(axis=1), ddof=1)
    return float(vq / (q * v1))


_MEMO: dict = {}


def daily_returns(sym):
    """Hozamok + a napi hatarok.

    Az adat ido szerint rendezett, tehat egy nap ossszefuggo szelet -> a napi
    hatarokat EGYSZER kiszamoljuk, es utana minden ablak egy sima szeletelés.
    (A korabbi valtozat np.isin-t hivott ablakonkent a teljes tombre: ~2
    milliard felesleges muvelet.)
    """
    if sym in _MEMO:
        return _MEMO[sym]
    d = lab.resample(lab.load_m1(sym), TF)
    c = d["close"].to_numpy(float)
    r = np.concatenate([[np.nan], np.diff(np.log(c))])
    day = d.index.normalize()
    kod, napok = pd.factorize(day, sort=False)      # rendezett -> novekvo kod
    # minden nap kezdo offszetje + a zaro sentinel
    hat = np.searchsorted(kod, np.arange(len(napok) + 1))
    _MEMO[sym] = (r, hat, pd.DatetimeIndex(napok), d.index)
    return _MEMO[sym]


def szelet(r, hat, i, j):
    """Az i..j (nap-index) tartomany hozamai — O(1)."""
    return r[hat[i]:hat[j]]


def main():
    pd.set_option("display.width", 240)

    # ── 1. ZAJ: mekkora ablakkal mekkora a becsles szorasa? ─────────────────
    print("=== 1. A BECSLES ZAJA — mekkora ablak kell? ===")
    print("   (a mert szoras EGY NYUGODT szakaszon belul = tiszta becslesi zaj)")
    rows = []
    for sym in SYMS:
        r, hat, napok, _ = daily_returns(sym)
        # 2022+: a "stabil" (VR~1) szakasz. FIGYELEM: az itt mert szoras nem
        # tisztan becslesi zaj — a valodi rezsim-ingadozas is benne van, tehat
        # FELSO korlat. A napon beluli kerdesnel ez nem baj: ott a zaj dominal.
        hatar = pd.Timestamp("2022-01-01")
        if napok.tz is not None:                  # az index tz-aware
            hatar = hatar.tz_localize(napok.tz)
        i0 = int(np.searchsorted(napok, hatar))
        for nap in (1, 5, 20, 60, 250):
            est = []
            for i in range(i0, len(napok) - nap, max(1, nap // 2)):
                v = vr(szelet(r, hat, i, i + nap))
                if np.isfinite(v):
                    est.append(v)
            if len(est) > 5:
                rows.append({"sym": sym, "ablak_nap": nap, "becsles_db": len(est),
                             "atlag_VR": float(np.mean(est)),
                             "szoras(zaj)": float(np.std(est, ddof=1))})
    z = pd.DataFrame(rows)
    piv = z.pivot_table(index="ablak_nap", values="szoras(zaj)", aggfunc="mean")
    piv["atlag_VR"] = z.pivot_table(index="ablak_nap", values="atlag_VR",
                                    aggfunc="mean")
    piv["jel/zaj"] = 0.08 / piv["szoras(zaj)"]     # a kimutatando jel: 0,92->1,00
    print(piv.to_string(float_format=lambda x: f"{x:9.4f}"))
    print("   -> jel/zaj < 1 = a mutato HASZNALHATATLAN azon az ablakon")

    # ── 2. PERZISZTENCIA: meddig tart egy allapot? ──────────────────────────
    print("\n=== 2. PERZISZTENCIA — meddig tart egy VR-allapot? ===")
    rows = []
    for sym in SYMS:
        r, hat, napok, _ = daily_returns(sym)
        for nap in (5, 20, 60):
            ser, idx = [], []
            for i in range(0, len(napok) - nap, nap):    # NEM atfedo ablakok
                v = vr(szelet(r, hat, i, i + nap))
                if np.isfinite(v):
                    ser.append(v); idx.append(napok[i])
            ss = pd.Series(ser, index=idx)
            if len(ss) > 10:
                ac1 = ss.autocorr(1)
                hl = (np.log(0.5) / np.log(abs(ac1)) * nap
                      if 0 < abs(ac1) < 1 else np.nan)
                rows.append({"sym": sym, "ablak_nap": nap, "n": len(ss),
                             "AC1(ablak)": float(ac1),
                             "felezesi_ido_nap": float(hl)})
    p = pd.DataFrame(rows)
    print(p.groupby("ablak_nap")[["AC1(ablak)", "felezesi_ido_nap"]].mean()
           .to_string(float_format=lambda x: f"{x:9.3f}"))
    print("   -> AC1 ~0 = az allapot NEM tart ki, a kovetkezo ablak fuggetlen")

    # ── 3. ELOREJELZO-E? ────────────────────────────────────────────────────
    print("\n=== 3. ELOREJELZO-E? — a MULTBELI VR megmondja-e a KOVETKEZOT ===")
    rows = []
    for sym in SYMS:
        r, hat, napok, _ = daily_returns(sym)
        for nap in (5, 20, 60):
            pairs = []
            for i in range(0, len(napok) - 2 * nap, nap):
                va = vr(szelet(r, hat, i, i + nap))
                vb = vr(szelet(r, hat, i + nap, i + 2 * nap))
                if np.isfinite(va) and np.isfinite(vb):
                    pairs.append((va, vb))
            if len(pairs) > 20:
                A = np.array(pairs)
                r_ = np.corrcoef(A[:, 0], A[:, 1])[0, 1]
                n_ = len(A)
                t_ = r_ * np.sqrt((n_ - 2) / max(1e-9, 1 - r_ ** 2))
                rows.append({"sym": sym, "ablak_nap": nap, "par": n_,
                             "korrelacio": float(r_), "t": float(t_)})
    f = pd.DataFrame(rows)
    print(f.groupby("ablak_nap")[["par", "korrelacio", "t"]].mean()
           .to_string(float_format=lambda x: f"{x:9.3f}"))
    print("   -> korrelacio ~0 = a multbeli VR NEM jelzi elore a kovetkezot")
    print("\n   per instrumentum (20 napos ablak):")
    print(f[f.ablak_nap == 20].to_string(index=False,
          float_format=lambda x: f"{x:9.3f}"))

    valtas_detektalas()




# ══════════════════════════════════════════════════════════════════════════
# 4-5. MIKOR ROMLIK EL A PIAC? — a VALTAS detektalasa
#
# A felhasznalo kerdese: "mar az is erdekes lehet, ha magat a valtast is
# detektalni tudjuk."
#
# EZ KET KULON KERDES, es a kulonbseg dont el mindent:
#
#   UTOLAG (4.) — a teljes idosorra visszanezve hol a tores? Ez KONNYU, es
#     mindig ad valamilyen valaszt. Magyarazatra jo, kereskedesre nem.
#
#   MENET KOZBEN (5.) — CSAK a multbeli adatbol, akkor, amikor tortenik.
#     Ez ER valamit. Ket ara van: a KESES (hany honappal a tores utan szol) es
#     a TEVES RIASZTAS (hanyszor szol, amikor nincs semmi).
# ══════════════════════════════════════════════════════════════════════════


def havi_vr(sym, q=6):
    """Havi VR-sorozat egy instrumentumra (a napi hatarokbol, szeleteles)."""
    r, hat, napok, _ = daily_returns(sym)
    ho = napok.tz_localize(None).to_period("M") if napok.tz is not None         else napok.to_period("M")
    out = {}
    for p in ho.unique():
        w = np.flatnonzero(ho == p)
        v = vr(szelet(r, hat, w[0], w[-1] + 1), q)
        if np.isfinite(v):
            out[p.to_timestamp()] = v
    return pd.Series(out).sort_index()


def binseg(s, mind=12, depth=0, out=None):
    """Binaris szegmentacio: a legerosebb tores keresese, majd rekurzio."""
    out = [] if out is None else out
    if len(s) < 2 * mind or depth > 2:
        return out
    best_t, best_i = 0.0, None
    for i in range(mind, len(s) - mind):
        a, b = s.iloc[:i], s.iloc[i:]
        se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
        if se <= 0:
            continue
        t = abs((b.mean() - a.mean()) / se)
        if t > best_t:
            best_t, best_i = t, i
    if best_i is None or best_t < 3.0:          # szigoru kuszob
        return out
    a, b = s.iloc[:best_i], s.iloc[best_i:]
    out.append({"datum": s.index[best_i], "t": best_t,
                "elotte": a.mean(), "utana": b.mean(), "n_ho": len(s)})
    binseg(s.iloc[:best_i], mind, depth + 1, out)
    binseg(s.iloc[best_i:], mind, depth + 1, out)
    return out


def cusum_online(s, tanulo=24, k=0.5, h=5.0):
    """ONLINE CUSUM: minden pontban CSAK a multat hasznalja.

    A tanulo szakaszbol veszi a referencia atlagot es szorast, utana
    folyamatosan gyujti az elterest. Riaszt, ha a halmozott elteres > h*sigma.
    Riasztas utan ujraindul (uj referencia), mintha uj rezsim kezdodne.
    """
    v = s.to_numpy(float)
    if len(v) < tanulo + 6:
        return []
    riasztasok = []
    i0 = 0
    while i0 + tanulo + 6 <= len(v):
        mu = v[i0:i0 + tanulo].mean()
        sd = v[i0:i0 + tanulo].std(ddof=1)
        if sd <= 0:
            break
        sp = sm = 0.0
        tuz = None
        for j in range(i0 + tanulo, len(v)):
            z = (v[j] - mu) / sd
            sp = max(0.0, sp + z - k)
            sm = min(0.0, sm + z + k)
            if sp > h or sm < -h:
                tuz = j
                break
        if tuz is None:
            break
        riasztasok.append({"datum": s.index[tuz],
                           "irany": "NO" if sp > h else "CSOKKEN",
                           "ref_atlag": mu})
        i0 = tuz
    return riasztasok


def valtas_detektalas():
    print("\n" + "=" * 78)
    print("=== 4. UTOLAG: hol vannak a torések? (havi VR30p, binaris szegm.) ===")
    havi = {}
    for sym in SYMS:
        havi[sym] = havi_vr(sym)
    atlag = pd.DataFrame(havi).mean(axis=1).dropna()
    print(f"   havi VR-sorozat: {len(atlag)} honap "
          f"({atlag.index[0]:%Y-%m} … {atlag.index[-1]:%Y-%m})")
    tores = sorted(binseg(atlag), key=lambda d: d["datum"])
    if not tores:
        print("   NINCS t>=3 tores a havi sorozatban.")
    for d in tores:
        print(f"   {d['datum']:%Y-%m}  t={d['t']:5.2f}   "
              f"VR {d['elotte']:.3f} -> {d['utana']:.3f}")

    print("\n=== 5. MENET KOZBEN: eszrevettuk volna? (online CUSUM) ===")
    riaszt = cusum_online(atlag)
    if not riaszt:
        print("   a detektor SOHA nem szolalt meg.")
    for d in riaszt:
        # keses: a legkozelebbi utolagos toreshez kepest
        if tores:
            kul = [(d["datum"] - t["datum"]).days / 30.44 for t in tores]
            legkoz = min(kul, key=abs)
            jel = (f"{legkoz:+5.1f} ho a legkozelebbi toreshez kepest"
                   if abs(legkoz) < 24 else "NINCS kozeli tores -> TEVES")
        else:
            jel = "nincs mihez merni"
        print(f"   {d['datum']:%Y-%m}  {d['irany']:8s}  {jel}")

    n_valos = 0
    if tores:
        for d in riaszt:
            if min(abs((d["datum"] - t["datum"]).days / 30.44)
                   for t in tores) < 24:
                n_valos += 1
    print(f"\n   riasztas: {len(riaszt)} db, ebbol valos toreshez kotheto: "
          f"{n_valos}  -> teves: {len(riaszt) - n_valos}")
    print("   (a detektor CSAK multbeli adatot lat — ez a becsuletes teszt)")


if __name__ == "__main__":
    main()

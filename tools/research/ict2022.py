"""ICT 2022 MENTORSHIP MODELL — a mi protokollunkon.

A felvetes (2026-09-28): „Fent van a neten, egy csomoan kereskednek vele, nem
csinalnak evek ota, ha nem lenne belole hasznuk." — a forras az ICT (Inner
Circle Trader) 2022-es mentor-sorozata (YouTube, 2. resz: tmeCWULSTHc).

A videot nem neztem vegig (nem tudok); a modellt a 2022-es mentorprogram
szeles korben dokumentalt, NYILVANOS leirasabol formalizaltam. Ha a te
olvasatod mas (pl. mas kill zone, mas stop), az EGY sor itt — de akkor azt is
futtatas ELOTT kell rogziteni.

A MODELL (elsodleges, elore rogzitve 2026-09-28, a futtatas ELOTT):
  1. IDO — kill zone-ok New York-i idoben (a szerver-ido berlini helyi ido,
     lasd gates/sessions.py): LONDON 02:00-05:00, NEW YORK 08:30-11:00.
  2. LIKVIDITAS — a „nyilvanvalo" szintek, amik a kill zone elejen meg
     erintetlenek: elozo NY-nap csucs/alja, azsiai sav (NY 20:00-24:00) csucs/
     alja, es a NY kill zone-ban a londoni kill zone csucs/alja is.
  3. SWEEP — az M5 gyertya a kill zone-ban tullepi a legkozelebbi erintetlen
     csucsot (-> SHORT setup) vagy aljat (-> LONG setup).
  4. PIACSZERKEZET-VALTAS (MSS) — a sweep utani 12 M5 gyertyan (1 ora) belul
     egy M5 ZARAS a sweep elotti utolso megerositett M5 swing-pont (3 gyertyas
     fraktal) masik oldalan.
  5. ELMOZDULAS + FVG — a szelsoertektol az MSS-ig tarto lab tartalmaz egy
     fair value gap-et (SHORT: low[j-2] > high[j]; LONG: high[j-2] < low[j]).
     A LEGUTOLSOT hasznaljuk.
  6. BELEPES — LIMIT az FVG kozeli szelen (SHORT: high[j], LONG: low[j]; a
     chart bid, a BUY limit ask-on tolt). 60 percig el; torlodik, ha az ar
     elobb eleri a celart.
  7. STOP — a sweep-szelsoerteken tul (az uj szelsoertek utni). CEL — 2R.
  8. KILEPES legkesobb NY 16:00-kor. Kill zone-onkent legfeljebb EGY kotes.
  Koltseg: bid gyertyak + valodi spread (SELL ask-on zar, BUY ask-on nyit),
  jutalek a configbol. (NY 16:00 elott zar -> swap nincs.)

ELFOGADAS (a README protokollja, valtozatlanul):
  (1) netto R/kotes > 0, napra klaszterezett t >= 2 az osszevont mintan,
  (2) az evek >= 60%-aban pozitiv,
  (3) >= 3 instrumentumon pozitiv.
  Masodlagos (csak iranyt mutat, tobbszoros teszteles): 1R/3R cel, FVG nelkul
  piaci belepes az MSS zarasan, csak London / csak NY, M1 szerkezet helyett
  nem vizsgalt.

VARAKOZAS (joslat): a sweep+MSS egy swing-toresi fordulo; a csilla_swing_break
es a gyertya-alakzatok hasonlo fordulo-szerkezete ~0 bruttot adott. Azt varom,
hogy a brutto ~0, a netto a koltseggel negativ — de ez joslat, nem meres.

EREDMENY (2026-09-28, 8 instrumentum, 2013-2026) — MEGBUKOTT, mindharom feltetelen:
  Elsodleges (FVG-limit, 2R): 2735 kotes, -0,097 R/kotes, t(nap) -3,69,
  nyero 32,7%; az evek 2/14-eben pozitiv, 2/8 instrumentumon (EURUSD +0,036,
  UsaInd +0,009 — mindketto zaj). Egyik celar sem ment at (1R -0,091, 3R -0,111).
  MSS-piaci belepes: -0,18 R/kotes, 0/14 ev, 0/8 instrumentum.
  A legolcsobb (spread/R) otodben -0,013, a legdragabban -0,212: a brutto ~0,
  a veszteseg = a koltseg — ugyanaz a kep, mint minden eddigi belepon.

Futtatas:  python tools/research/ict2022.py [SZIMBOLUMOK...]
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

import lab

SYMS = ["UsaTec", "UsaInd", "Usa500", "Ger40", "GOLD", "EURUSD", "GBPUSD", "USDJPY"]
KZ = {"London": ((2, 0), (5, 0)), "NewYork": ((8, 30), (11, 0))}
MSS_ABLAK = 12          # M5 gyertya a sweep utan
LIMIT_PERC = 60
ZARAS_NY = 16 * 60
CELOK = (1.0, 2.0, 3.0)
FO_CEL = 2.0
KIMENET = ROOT / "data" / "ict2022_trades.parquet"


def _ny_ido(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """szerver (berlini fali ido, UTC-cimkevel tarolva) -> New York helyi ido."""
    naiv = idx.tz_localize(None)
    return (naiv.tz_localize("Europe/Berlin", ambiguous="NaT", nonexistent="NaT")
            .tz_convert("America/New_York"))


def _fraktal(h, l):
    """3 gyertyas swing: csucs k-n, ha h[k] > h[k-1] es h[k] >= h[k+1];
    MEGEROSITVE a k+1. gyertya zarasan."""
    ph = np.zeros(len(h), bool); pl = np.zeros(len(l), bool)
    ph[1:-1] = (h[1:-1] > h[:-2]) & (h[1:-1] >= h[2:])
    pl[1:-1] = (l[1:-1] < l[:-2]) & (l[1:-1] <= l[2:])
    return ph, pl


def _kotes(m1h, m1l, m1c, m1sp, m1min, t0, t_end, irany, P, SL, azonnal=False):
    """Limit-belepes + SL/TP az M1 gyertyakon. Bid gyertyak.
    SHORT: tolt, ha bid high >= P; zar ask-on (SL: high+sp >= SL, TP: low+sp <= TP).
    LONG : tolt, ha ask low (= low+sp) <= P; zar bid-en (SL: low <= SL, TP: high >= TP).
    Vissza: dict R-ekkel celonkent, vagy None (nem tolt)."""
    R = (SL - P) if irany < 0 else (P - SL)
    if not (R > 0):
        return None
    tp_elso = P - FO_CEL * R if irany < 0 else P + FO_CEL * R
    i = t0
    lim_vege = min(t_end, t0 + LIMIT_PERC)
    f = t0 if azonnal else -1
    while f < 0 and i < lim_vege:
        if irany < 0:
            if m1h[i] >= P:
                f = i; break
            if m1l[i] + m1sp[i] <= tp_elso:
                return None
        else:
            if m1l[i] + m1sp[i] <= P:
                f = i; break
            if m1h[i] >= tp_elso:
                return None
        i += 1
    if f < 0:
        return None
    out = {"i_be": f, "R_ar": R, "sp_R": float(m1sp[f] / R)}
    for cel in CELOK:
        tp = P - cel * R if irany < 0 else P + cel * R
        r = None
        for j in range(f, t_end + 1):
            if irany < 0:
                hs = m1h[j] + m1sp[j] >= SL
                ht = m1l[j] + m1sp[j] <= tp
            else:
                hs = m1l[j] <= SL
                ht = m1h[j] >= tp
            if hs:                        # konzervativ: a stop elobb
                # a tenyleges kilepesi ar a stop (a stop-szint ask/bid oldalon)
                r = (P - SL) / R if irany < 0 else (SL - P) / R
                break
            if ht and j > f:
                r = cel
                break
            if m1min[j] >= ZARAS_NY:
                x = (m1c[j] + m1sp[j]) if irany < 0 else m1c[j]
                r = (P - x) / R if irany < 0 else (x - P) / R
                break
        if r is None:
            j = t_end
            x = (m1c[j] + m1sp[j]) if irany < 0 else m1c[j]
            r = (P - x) / R if irany < 0 else (x - P) / R
        out[f"r{cel:g}"] = r
    return out


def fut(sym: str) -> pd.DataFrame:
    m1 = lab.load_m1(sym)
    ny1 = _ny_ido(m1.index)
    ok1 = ~ny1.isna()
    m1 = m1[ok1]; ny1 = ny1[ok1]
    sp1 = m1.close_spread.where(m1.close_spread > 0, m1.avg_spread).ffill().to_numpy(float)
    m1h, m1l, m1c = (m1[c].to_numpy(float) for c in ("high", "low", "close"))
    m1min = (ny1.hour * 60 + ny1.minute).to_numpy()
    m1nap = ny1.normalize().tz_localize(None).to_numpy()

    m5 = lab.resample(m1, 5)
    ny5 = _ny_ido(m5.index)
    ok5 = ~ny5.isna()
    m5 = m5[ok5]; ny5 = ny5[ok5]
    h, l, c = (m5[x].to_numpy(float) for x in ("high", "low", "close"))
    mn = (ny5.hour * 60 + ny5.minute).to_numpy()
    nap = ny5.normalize().tz_localize(None)
    ph, pl = _fraktal(h, l)
    # az M5 gyertya ZARASA -> az M1 index, ahonnan a limit elhet
    m5_zar_m1 = np.searchsorted(m1.index.to_numpy(), (m5.index + pd.Timedelta(minutes=5)).to_numpy())

    napok = pd.Index(nap.unique())
    nap_arr = nap.to_numpy()
    kezd = np.searchsorted(nap_arr, napok.to_numpy(), "left")
    veg = np.searchsorted(nap_arr, napok.to_numpy(), "right")
    pcfg = lab.PAIRS.get(sym, {})
    sorok = []
    utolso_ph = np.full(len(h), -1); utolso_pl = np.full(len(l), -1)
    lh = ll = -1
    for i in range(len(h)):
        # a k pivot a k+1 zarasakor ismert
        if i >= 1 and ph[i - 1]:
            lh = i - 1
        if i >= 1 and pl[i - 1]:
            ll = i - 1
        utolso_ph[i], utolso_pl[i] = lh, ll

    for d in range(1, len(napok)):
        a, b = kezd[d], veg[d]
        pa, pb = kezd[d - 1], veg[d - 1]
        mm = mn[a:b]
        # szintek
        pdh, pdl = h[pa:pb].max(), l[pa:pb].min()
        az = np.flatnonzero(mn[pa:pb] >= 20 * 60) + pa          # elozo nap 20:00-24:00
        azh = h[az].max() if len(az) else np.nan
        azl = l[az].min() if len(az) else np.nan
        lon = np.flatnonzero((mm >= 120) & (mm < 300)) + a
        lonh = h[lon].max() if len(lon) else np.nan
        lonl = l[lon].min() if len(lon) else np.nan
        for kz, ((h0, m0), (h1, mi1)) in KZ.items():
            k0, k1 = h0 * 60 + m0, h1 * 60 + mi1
            zona = np.flatnonzero((mm >= k0) & (mm < k1)) + a
            if len(zona) < 6:
                continue
            elotte = np.arange(a, zona[0])
            hi_eddig = h[elotte].max() if len(elotte) else -np.inf
            lo_eddig = l[elotte].min() if len(elotte) else np.inf
            fent = [pdh, azh] + ([lonh] if kz == "NewYork" else [])
            lent = [pdl, azl] + ([lonl] if kz == "NewYork" else [])
            if kz == "NewYork" and len(lon):
                # a londoni szint csak akkor erintetlen, ha 05:00 ota nem lepte at
                ut = np.arange(lon[-1] + 1, zona[0])
                if len(ut):
                    if h[ut].max() > lonh: fent[-1] = np.nan
                    if l[ut].min() < lonl: lent[-1] = np.nan
            fent = [x for x in fent if np.isfinite(x) and x > hi_eddig]
            lent = [x for x in lent if np.isfinite(x) and x < lo_eddig]
            szint_fent = min(fent) if fent else np.nan
            szint_lent = max(lent) if lent else np.nan
            kesz = False
            for s in zona:
                if kesz:
                    break
                for irany, szint in ((-1, szint_fent), (1, szint_lent)):
                    if kesz or not np.isfinite(szint):
                        continue
                    if irany < 0 and not (h[s] > szint):
                        continue
                    if irany > 0 and not (l[s] < szint):
                        continue
                    # sweep az s gyertyan -> MSS keresese
                    ref_i = utolso_pl[s] if irany < 0 else utolso_ph[s]
                    if ref_i < 0:
                        continue
                    ref = l[ref_i] if irany < 0 else h[ref_i]
                    ext_i = s
                    for m in range(s + 1, min(s + 1 + MSS_ABLAK, b)):
                        if irany < 0 and h[m] > h[ext_i]: ext_i = m
                        if irany > 0 and l[m] < l[ext_i]: ext_i = m
                        mss = (c[m] < ref) if irany < 0 else (c[m] > ref)
                        if not mss:
                            continue
                        fvg = -1
                        for j in range(ext_i + 2, m + 1):
                            if irany < 0 and l[j - 2] > h[j]: fvg = j
                            if irany > 0 and h[j - 2] < l[j]: fvg = j
                        ext = h[ext_i] if irany < 0 else l[ext_i]
                        t0 = m5_zar_m1[m]
                        # a nap vege (NY 16:00) az M1-en
                        t_end = t0
                        while t_end + 1 < len(m1min) and m1nap[t_end + 1] == m1nap[t0] \
                                and m1min[t_end] < ZARAS_NY:
                            t_end += 1
                        if t0 >= len(m1h) or t_end <= t0:
                            break
                        for valt, P in (("FVG_limit", (h[fvg] if irany < 0 else l[fvg]) if fvg >= 0 else np.nan),
                                        ("MSS_piaci", np.nan)):
                            if valt == "FVG_limit" and not np.isfinite(P):
                                continue
                            # SL: a szelsoerteken tul. SHORT: ask >= ext + sp <=> bid >= ext
                            SL = (ext + sp1[t0]) if irany < 0 else ext
                            if valt == "MSS_piaci":
                                # piaci belepes az MSS zarasan (SHORT bid-en, LONG ask-on)
                                P = c[m] if irany < 0 else c[m] + sp1[t0]
                            res = _kotes(m1h, m1l, m1c, sp1, m1min, t0, t_end, irany,
                                         P, SL, azonnal=(valt == "MSS_piaci"))
                            if res is None:
                                continue
                            # jutalek R-ben (ha a config ad ilyet)
                            kom = 0.0
                            try:
                                comm = float(pcfg.get("commission_per_lot", 0) or 0)
                                pv1 = float(pcfg.get("pv1_point", 0) or 0)
                                ps = float(pcfg.get("point_size", 0) or 0)
                                if comm > 0 and pv1 > 0 and ps > 0:
                                    kom = comm / (res["R_ar"] / ps * pv1)
                            except Exception:
                                pass
                            sor = {"sym": sym, "nap": napok[d], "kz": kz, "irany": irany,
                                   "valtozat": valt, "sp_R": res["sp_R"],
                                   "ido": m1.index[res["i_be"]]}
                            for cel in CELOK:
                                sor[f"r{cel:g}"] = res[f"r{cel:g}"] - kom
                            sorok.append(sor)
                        kesz = True
                        break
    return pd.DataFrame(sorok)


def _t_nap(r: pd.Series, nap: pd.Series) -> float:
    s = r.groupby(nap.values).sum(); n = r.groupby(nap.values).size()
    N = n.sum(); m = s.sum() / N
    e = s - m * n
    se = np.sqrt((e ** 2).sum() * len(s) / max(len(s) - 1, 1)) / N
    return float(m / se) if se > 0 else np.nan


def osszegez(T: pd.DataFrame, valt: str, cel: float, cimke: str):
    x = T[T.valtozat == valt]
    col = f"r{cel:g}"
    if x.empty:
        print(f"{cimke}: nincs kotes"); return
    evr = x.groupby(x.nap.dt.year)[col].mean()
    sym = x.groupby("sym")[col].agg(["size", "mean"])
    print(f"\n=== {cimke} ===")
    print(f"   {len(x)} kotes, R/kotes {x[col].mean():+.4f}, t(nap) {_t_nap(x[col], x.nap):+.2f}, "
          f"nyero% {100 * (x[col] > 0).mean():.1f}, spread/R median {x.sp_R.median():.3f}")
    print(f"   evek pozitiv: {(evr > 0).sum()}/{len(evr)}   "
          + "  ".join(f"{y}:{v:+.3f}" for y, v in evr.items()))
    print(f"   instrumentum pozitiv: {(sym['mean'] > 0).sum()}/{len(sym)}   "
          + "  ".join(f"{s}:{r['mean']:+.3f}({int(r['size'])})" for s, r in sym.iterrows()))
    return x


def main():
    syms = _sys.argv[1:] or [s for s in SYMS if (ROOT / "data" / "m1" / f"{s}.parquet").exists()]
    with ProcessPoolExecutor(len(syms)) as ex:
        T = pd.concat(list(ex.map(fut, syms)), ignore_index=True)
    T.to_parquet(KIMENET)
    print(f"{len(T)} kotes, {T.sym.nunique()} instrumentum -> {KIMENET}")
    osszegez(T, "FVG_limit", FO_CEL, "ELSODLEGES: FVG-limit, 2R cel (elore rogzitett)")
    print("\n--- masodlagos (tobbszoros teszteles, csak irany) ---")
    for cel in CELOK:
        if cel != FO_CEL:
            osszegez(T, "FVG_limit", cel, f"FVG-limit, {cel:g}R")
    for cel in CELOK:
        osszegez(T, "MSS_piaci", cel, f"MSS piaci belepes, {cel:g}R")
    x = T[T.valtozat == "FVG_limit"]
    print("\n   kill zone / irany szerint (FVG, 2R):")
    print(x.groupby(["kz", "irany"])["r2"].agg(["size", "mean"]).round(4).to_string())
    print("\n   a spread/R otodeiben (FVG, 2R) — a kis stopot eszi a koltseg?")
    q = pd.qcut(x.sp_R, 5, duplicates="drop")
    print(x.groupby(q, observed=True)["r2"].agg(["size", "mean"]).round(4).to_string())


if __name__ == "__main__":
    main()

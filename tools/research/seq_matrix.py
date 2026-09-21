"""SORREND-MÁTRIX — „mi UTÁN mi jön", idősíkonként.

A felhasználó kérése (2026-09-19): *„több dimenziós mátrix: az egyik dimenzió
M15-M5-M1, a másik a stratégiák. Csak itt volna egy trükk: szerintem nem
egyszerre kell ezeket keresni, hanem azt feltárni, hogy mi után mi jön. Dupla
csúcs után doji után trendváltozás. Ezt megismétli M5 is, vagy M15."*

A mátrix cellája: (A esemény, A idősíkja) -> (B esemény, B idősíkja), egy
időablakon belül. Két KÜLÖN kérdést mérünk, ebben a sorrendben:

  1. VAN-E EGYÁLTALÁN NYELVTAN?  Gyakrabban jön-e B az A után, mint véletlenül?
     Ez a kérdés az ÁRFOLYAM-HOZAMOT NEM HASZNÁLJA — tehát olcsó, és nem lehet
     rajta „szerencsét" találni. Ha a válasz nem, a 2. kérdést fel sem kell
     tenni: nincs mit kereskedni.

  2. FIZET-E A SORREND?  Többet ér-e a B esemény akkor, ha A előzte meg, mint
     önmagában? A mérce nem a nulla, hanem MAGA A B ESEMÉNY — ez az egyetlen
     összehasonlítás, ami a sorrend hozzáadott értékét méri.

⚠ MIÉRT ÍGY, ÉS NEM „még egy nagy keresés". A `search.py` 480 000 jelöltje után
a `holdout.py` ítélete az volt, hogy a keresési rangsor NEM jelez előre. Egy
újabb dimenzió (a sorrend) a kombinációk számát megint szorozza — ugyanabba a
falba mennénk. Három dolog változik itt:

  (a) A szótár KICSI és emberi nevű (`seq_events.py`, 18 esemény x 3 idősík).
      A rendezett párok száma pár ezer, nem millió — a Bonferroni-küszöb
      teljesíthető.
  (b) Az 1. kérdés HOZAM NÉLKÜLI. Ez a kutatás legolcsóbb és legerősebb lépése:
      ha a nyelvtan nem létezik, minden további mérés zaj-halászat.
  (c) A nullhipotézis KÖRKÖRÖS ELTOLÁS, nem függetlenség. Enélkül a közös
      napszaki/volatilitási ritmus önmagában „szignifikáns" sorrendnek látszik.
      (`seq_stat.py` magyarázza.)

⚠ AMIT AZ 1. KÉRDÉS NEM JELENT. A „B gyakrabban jön A után" akkor is IGAZ,
ha a két esemény MECHANIKUSAN fedi egymást: egy M15 külső bar M5-ön is külső
barokat tartalmaz, egy M15 swing-törés M5-ön is törés. A mérés ezt helyesen
szignifikánsnak mutatja — csak épp semmit nem jelent. Ezért a riport a valódi
piacot nem csak az eltolásos nullhoz, hanem egy SZINTETIKUS (blokk-bootstrap)
piachoz is méri (`--szintetikus`): ott ugyanaz a mechanikus átfedés megvan, de
a hosszabb távú szerkezet nincs. A kettő KÜLÖNBSÉGE az érdekes szám.

⚠ ELŐRE RÖGZÍTETT VÁRAKOZÁS (2026-09-19, a mérés előtt leírva). Azt várom, hogy
az 1. kérdésre IGEN a válasz (a gyertya-alakzatok sorrendje nem független: a
szorulás után tényleg gyakoribb a kitörés), a 2.-ra viszont NEM — mert a
`README.md` szerint a belépő iránya MFE/MAE = 1,036, és egy szűrő nem tud
irányt teremteni ott, ahol nincs. Ha a 2. mégis IGEN, az az egyetlen eset,
amikor érdemes továbbmenni.

⚠ ELŐRE RÖGZÍTETT VÁLOGATÁSI SZABÁLY (hogy a holdout ne legyen utólag hangolva):
a jelölt a KERESŐ szakasz `sorrend_delta` értéke szerint kerül a top-listára;
a holdout-számot ezután EGYSZER nézzük meg. A küszöbök a README protokollja:
napra klaszterezett t >= 2, az évek >= 60%-ában pozitív, >= 3 instrumentum.

Futtatás:

    python tools/research/seq_matrix.py --symbols Ger40 UsaTec
    python tools/research/seq_matrix.py --ablak 15 60 --null-korok 10
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import argparse

import numpy as np
import pandas as pd

import core.applog as _applog
_applog.harden_console()   # cp1250 konzol: a ⚠ / ≥ / → ne dobjon UnicodeEncodeError-t

import lab
import seq_events as SE
import seq_stat as ST

VAGAS = "2023-01-01"        # ugyanaz a vágás, mint a search.py-ban
ABLAK_PERC = (15, 60, 240)  # „A után B" — ennyi percen belül
MIN_N = 500                 # ennél kevesebb eset nem értékelhető
# ⚠ A KÜSZÖB TÖRTÉNETE (search.py, 2026-08-29): 150-es MIN_N mellett a
# „nyertesek" rendszeresen a legkisebb minták voltak — nem jobbak, csak
# zajosabbak, és a valódi motoron -0,31 R-t hoztak. Ne vidd 500 alá.
NULL_KOROK = 5              # hány globálisan eltolt másolaton fut a teljes mátrix
Z_KUSZOB = 4.0              # az 1. kérdés „találat" küszöbe a szűrő z-re


def _betolt(sym: str):
    o = pd.read_parquet(ROOT / "data" / "outcomes" / f"{sym}.parquet")
    ido = pd.DatetimeIndex(o["ido"])
    R = {"long": o["long"].to_numpy(float), "short": o["short"].to_numpy(float)}
    nap = ST.ns(pd.DatetimeIndex(ido).floor("D"))
    kereso = np.asarray(ido < pd.Timestamp(VAGAS, tz=ido.tz))
    return ido, R, nap, kereso


def _matrix_z(jelek: dict, nevek: list[str], lo_of: np.ndarray,
              b_idx: dict, eltolas: int = 0) -> np.ndarray:
    """A teljes (A x B) szűrő-z mátrix EGY ablakra.

    A szűrő-z a binomiális közelítés a „megelőzve" arányra, az A FELTÉTEL
    NÉLKÜLI előfordulási arányához mérve.

    ⚠ EZ A SZÁM ANTIKONZERVATÍV (a B események egymással korreláltak, tehát a
    binomiális SE túl kicsi). CSAK RANGSOROLÁSRA és a null-körökkel való
    ÖSSZEHASONLÍTÁSRA használjuk — a tényleges p-érték az eltolásos nullból jön,
    és mivel a null-körök UGYANEZZEL a torzított statisztikával készülnek,
    az összehasonlítás érvényes.
    """
    Z = np.full((len(nevek), len(nevek)), np.nan)
    minden = np.arange(len(lo_of), dtype=np.int64)
    for ai, A in enumerate(nevek):
        el = ST.Elozmeny(jelek[A])
        alap = float(el.elozve(minden, lo_of).mean())     # P(megelőzve) mindenütt
        if not (0 < alap < 1):
            continue
        for bi, B in enumerate(nevek):
            if ai == bi:
                continue
            b = b_idx[B]
            if len(b) < MIN_N:
                continue
            ar = float(el.elozve(b, lo_of, eltolas).mean())
            se = np.sqrt(alap * (1 - alap) / len(b))
            Z[ai, bi] = (ar - alap) / se if se > 0 else np.nan
    return Z


def nyelvtan_teszt(sym: str, jelek: dict, ido: pd.DatetimeIndex,
                   ablakok, null_korok: int) -> pd.DataFrame:
    """1. KÉRDÉS: van-e egyáltalán sorrendi szerkezet? (hozam nélkül)

    A valódi mátrixban megszámoljuk a |z| > küszöb cellákat, majd ugyanezt
    megismételjük `null_korok` darab GLOBÁLISAN eltolt másolaton. A globális
    eltolás megtartja az A-A és B-B önkorrelációt (a napszaki ritmust is),
    és csak az A-B időbeli kapcsolatot töri el.
    """
    nevek = sorted(jelek)
    b_idx = {n: np.flatnonzero(jelek[n]).astype(np.int64) for n in nevek}
    rng = np.random.default_rng(7)
    n = len(ido)
    sorok = []
    for perc in ablakok:
        lo_of = ST.ablak_kezdet(ido, perc)
        Z = _matrix_z(jelek, nevek, lo_of, b_idx)
        valodi = int(np.nansum(np.abs(Z) > Z_KUSZOB))
        ertekelt = int(np.isfinite(Z).sum())
        nullak = []
        for _ in range(null_korok):
            e = int(rng.integers(2000, max(2001, n - 2000)))
            Zn = _matrix_z(jelek, nevek, lo_of, b_idx, eltolas=e)
            nullak.append(int(np.nansum(np.abs(Zn) > Z_KUSZOB)))
        sorok.append({"sym": sym, "ablak_perc": perc, "cellak": ertekelt,
                      "valodi_talalat": valodi,
                      "talalat_%": 100 * valodi / max(1, ertekelt),
                      "null_atlag": float(np.mean(nullak)) if nullak else np.nan,
                      "null_max": int(np.max(nullak)) if nullak else -1,
                      "tobblet": valodi - (float(np.mean(nullak)) if nullak else 0)})
        print(f"   ablak {perc:>4d} perc: {valodi:5d} / {ertekelt} cella "
              f"|z|>{Z_KUSZOB:.0f}   null-átlag "
              f"{sorok[-1]['null_atlag']:7.1f} (max {sorok[-1]['null_max']})",
              flush=True)
    return pd.DataFrame(sorok)


def fizet_teszt(sym: str, jelek: dict, ido, R, nap, kereso, ablakok) -> pd.DataFrame:
    """2. KÉRDÉS: a sorrend hozzáad-e a puszta B eseményhez?

    Minden sor egy (A, B, ablak, irány) cella. A kulcs-oszlop a
    `sorrend_delta` = E[R | A után B] - E[R | B], a KERESŐ szakaszon.
    """
    nevek = sorted(jelek)
    hold = ~kereso
    alap_k = {k: float(np.nanmean(v[kereso])) for k, v in R.items()}
    b_k = {n: np.flatnonzero(jelek[n] & kereso).astype(np.int64) for n in nevek}
    b_h = {n: np.flatnonzero(jelek[n] & hold).astype(np.int64) for n in nevek}

    # a puszta B esemény értéke (a MÉRCE)
    B_ert = {}
    for n in nevek:
        for irany in ("long", "short"):
            for cimke, bb in (("k", b_k[n]), ("h", b_h[n])):
                v = R[irany][bb] if len(bb) else np.array([])
                B_ert[(n, irany, cimke)] = (float(np.nanmean(v)) if len(v) else np.nan,
                                            len(bb))

    sorok = []
    for perc in ablakok:
        lo_of = ST.ablak_kezdet(ido, perc)
        for A in nevek:
            el = ST.Elozmeny(jelek[A])
            for B in nevek:
                if A == B:
                    continue
                bk, bh = b_k[B], b_h[B]
                if len(bk) < MIN_N:
                    continue
                mk = el.elozve(bk, lo_of)
                if int(mk.sum()) < MIN_N:
                    continue
                mh = el.elozve(bh, lo_of) if len(bh) else np.array([], bool)
                egy = el.egyutt(jelek[A], bk)          # lag = 0 (összehasonlítás)
                for irany in ("long", "short"):
                    v = R[irany]
                    ab = v[bk[mk]]
                    csak_b = v[bk[~mk]]
                    mu, t, n_ab = ST.t_klaszter(ab, nap[bk[mk]])
                    ar, evek = ST.evek_pozitiv(ab, ido[bk[mk]],
                                               B_ert[(B, irany, "k")][0])
                    ab_h = v[bh[mh]] if len(bh) else np.array([])
                    sorok.append({
                        "sym": sym, "A": A, "B": B, "ablak_perc": perc,
                        "irany": irany,
                        "n_B": len(bk), "n_AB": n_ab,
                        "R_alap": alap_k[irany],
                        "R_B": B_ert[(B, irany, "k")][0],
                        "R_AB": mu,
                        "tobblet_B": B_ert[(B, irany, "k")][0] - alap_k[irany],
                        "sorrend_delta": mu - B_ert[(B, irany, "k")][0],
                        "t_nap": t,
                        "welch_t": ST.welch(ab, csak_b),
                        "R_egyutt": float(np.nanmean(v[bk[egy]])) if egy.any() else np.nan,
                        "n_egyutt": int(egy.sum()),
                        "evek_poz": ar, "evek": evek,
                        "n_AB_h": int(len(ab_h)),
                        "R_AB_h": float(np.nanmean(ab_h)) if len(ab_h) else np.nan,
                        "R_B_h": B_ert[(B, irany, "h")][0],
                    })
        print(f"   ablak {perc:>4d} perc kész, {len(sorok):,} cella", flush=True)
    t = pd.DataFrame(sorok)
    if not t.empty:
        t["sorrend_delta_h"] = t.R_AB_h - t.R_B_h
    return t


def _itelet(t: pd.DataFrame, top: int = 50) -> None:
    """A holdout EGYSZERI kiértékelése az ELŐRE rögzített válogatási szabállyal."""
    j = t[np.isfinite(t.sorrend_delta_h) & (t.n_AB_h >= MIN_N // 2)].copy()
    if j.empty:
        print("\n   (nincs a holdouton is értékelhető cella)")
        return
    valasztott = j.nlargest(min(top, len(j)), "sorrend_delta")
    rho = ST.spearman(j.sorrend_delta, j.sorrend_delta_h)
    n = len(j)
    tr = rho * np.sqrt((n - 2) / max(1e-12, 1 - rho ** 2)) if n > 3 else np.nan
    rng = np.random.default_rng(0)
    vel = np.array([j.sorrend_delta_h.sample(len(valasztott),
                                             random_state=int(s)).mean()
                    for s in rng.integers(0, 10 ** 6, 400)])
    p = float((vel >= valasztott.sorrend_delta_h.mean()).mean())
    print(f"\n--- ÍTÉLET (2. kérdés) — {n:,} cella mindkét szakaszon ---")
    print(f"   a kereső top-{len(valasztott)} holdout sorrend-deltája: "
          f"{valasztott.sorrend_delta_h.mean():+.4f}")
    print(f"   véletlen {len(valasztott)} cella ugyanez:               "
          f"{vel.mean():+.4f} (szórás {vel.std():.4f}), p = {p:.3f}")
    print(f"   rangkorreláció (kereső vs holdout delta): {rho:+.4f}  t={tr:+.1f}")
    f1 = valasztott.sorrend_delta_h.mean() > 0
    f2 = np.isfinite(tr) and tr > 2
    f3 = p < 0.05
    print(f"   pozitív holdout-delta: {'IGEN' if f1 else 'NEM'} | "
          f"előrejelző rangsor: {'IGEN' if f2 else 'NEM'} | "
          f"veri a véletlent: {'IGEN' if f3 else 'NEM'}")
    print(f"   => {'TALÁLAT — vihető tovább' if (f1 and f2 and f3) else 'NINCS bizonyított találat'}")


def visszhang(t: pd.DataFrame) -> pd.DataFrame:
    """„Ezt megismétli az M5 is, vagy az M15?" — UGYANAZ az esemény, kisebb
    idősíkon, a nagyobb után. Ez a felhasználó külön kérdése."""
    def _bont(s):
        tf, nev = s.split(":", 1)
        return int(tf[1:]), nev
    sor = []
    for _, r in t.iterrows():
        ta, na = _bont(r.A)
        tb, nb = _bont(r.B)
        if na == nb and ta > tb:
            sor.append(r)
    return pd.DataFrame(sor)


def fuss(sym: str, ablakok, null_korok: int, top: int,
         szintetikus: bool = False) -> pd.DataFrame | None:
    p = ROOT / "data" / "outcomes" / f"{sym}.parquet"
    if not p.exists():
        print(f"({sym}: nincs kimenet-gyorsítótár — futtasd: "
              f"python tools/research/outcomes.py {sym})")
        return None
    ido, R, nap, kereso = _betolt(sym)
    print(f"=== {sym}: {kereso.sum():,} kereső / {(~kereso).sum():,} holdout "
          f"rácspont ===")
    SE.onteszt(sym, ido)
    for _p in ablakok:
        ST.ablak_onteszt(ido, _p)
    jelek = SE.build(sym, ido)

    print("\n--- 1. KÉRDÉS: van-e sorrendi szerkezet? (hozam nélkül) ---")
    ny = nyelvtan_teszt(sym, jelek, ido, ablakok, null_korok)
    if szintetikus:
        print("   ugyanez egy SZINTETIKUS (szerkezet nélküli) piacon:")
        import sl_paths as SP
        jn = SE.build(sym, ido, m1=SP.szintetikus(lab.load_m1(sym), 60, 0))
        nyn = nyelvtan_teszt(sym, jn, ido, ablakok, 0)
        # ⚠ ARÁNYT hasonlítunk, nem darabszámot: a két piacon nem ugyanannyi
        # cella éri el a MIN_N küszöböt, tehát a nyers darabszám félrevezet.
        ny = ny.merge(nyn[["ablak_perc", "talalat_%"]]
                      .rename(columns={"talalat_%": "szintetikus_%"}),
                      on="ablak_perc", how="left")
        print("   -> a VALÓDI és a SZINTETIKUS találatszám különbsége az, ami")
        print("      nem magyarázható a gyertya-szerkezet mechanikus átfedésével.")
        print(ny[["ablak_perc", "cellak", "talalat_%", "szintetikus_%",
                  "null_atlag"]].to_string(index=False,
                                           float_format=lambda v: f"{v:8.2f}"))
    ny.to_parquet(ROOT / "data" / f"seq_nyelvtan_{sym}.parquet", index=False)

    print("\n--- 2. KÉRDÉS: fizet-e a sorrend? ---")
    t = fizet_teszt(sym, jelek, ido, R, nap, kereso, ablakok)
    if t.empty:
        print("   nincs értékelhető cella")
        return None
    t.to_parquet(ROOT / "data" / f"seq_{sym}.parquet", index=False)
    oszl = ["A", "B", "ablak_perc", "irany", "n_AB", "R_B", "R_AB",
            "sorrend_delta", "t_nap", "evek_poz", "sorrend_delta_h"]
    print(f"\n   {len(t):,} cella. A KERESŐ szakasz legjobb {min(top, len(t))}:")
    print(t.nlargest(min(top, len(t)), "sorrend_delta")[oszl].head(15)
          .to_string(index=False, float_format=lambda v: f"{v:+.4f}"))
    print(f"\n   Bonferroni-küszöb {len(t):,} cellára: |t| > "
          f"{abs(_norm_kvantilis(0.05 / max(1, len(t)))):.2f}")
    v = visszhang(t)
    if not v.empty:
        print("\n   VISSZHANG (ugyanaz az esemény kisebb idősíkon, a nagyobb után):")
        print(v.nlargest(min(10, len(v)), "sorrend_delta")[oszl]
              .to_string(index=False, float_format=lambda x: f"{x:+.4f}"))
    _itelet(t, top)
    return t


def _norm_kvantilis(p: float) -> float:
    """A standard normális kétoldali kvantilise (SciPy nélkül, bisectio)."""
    from math import erf, sqrt
    lo, hi = 0.0, 12.0
    cel = 1 - p / 2
    for _ in range(80):
        k = (lo + hi) / 2
        if 0.5 * (1 + erf(k / sqrt(2))) < cel:
            lo = k
        else:
            hi = k
    return (lo + hi) / 2


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", nargs="*", default=["Ger40", "UsaTec"])
    ap.add_argument("--ablak", nargs="*", type=int, default=list(ABLAK_PERC))
    ap.add_argument("--null-korok", type=int, default=NULL_KOROK)
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--szintetikus", action="store_true",
                    help="az 1. kérdés null-piaci összehasonlítása is lefut")
    a = ap.parse_args()
    for sym in a.symbols:
        fuss(sym, a.ablak, a.null_korok, a.top, a.szintetikus)


if __name__ == "__main__":
    main()

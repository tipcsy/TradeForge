"""KÖZÖS STATISZTIKA a sorrend-mátrixhoz és az SL-tanulmányhoz.

Egy helyen, mert mindkét mérés ugyanazt a három dolgot kérdezi, és ha két
példányban élnének, előbb-utóbb elcsúsznának egymástól:

  1. `t_klaszter` — t-statisztika ÁTFEDŐ kötésekre.
  2. `evek_pozitiv` — az évenkénti konzisztencia (a README elfogadási feltétele).
  3. `eltolas_null` — körkörös eltolásos nullhipotézis eseménysorozatokra.

⚠ 1. MIÉRT NEM JÓ A SIMA t. Az `outcomes.py` MINDEN rácspontot önállóan
értékel, a tartás viszont 480 perc = 96 rácspont. Két szomszédos „kötés" tehát
a pályája 99%-át megosztja: nem 96 független megfigyelés, hanem közelítőleg
egy. A sima t ilyenkor akár √96 ≈ 10x-esen túlbecsüli a bizonyítékot — és
pontosan ez az a hiba, amitől egy zaj-minta „t = 4"-nek látszik.

Ezért minden itteni t NAPRA KLASZTEREZETT (cluster-robust SE): a napon belüli
tetszőleges korrelációt megengedjük, a napok között függetlenséget feltételezünk.
A megmaradó átfedés (a 8 órás tartás átnyúlik a következő napra) miatt ez még
mindig enyhén optimista, de nagyságrenddel közelebb van az igazsághoz.

⚠ 2. MIÉRT KELL AZ ÉVENKÉNTI JEL. A `tools/research/README.md` esete: a
`donchian48 + kapuk` 2 éven +0,100 R (t = +2,04), 14 éven −0,038 (t = −2,94),
és 14-ből 11 évben negatív. A t-statisztika NEM ölte volna meg; az évenkénti
konzisztencia igen.

⚠ 3. MIÉRT KELL AZ ELTOLÁSOS NULL. „A dupla csúcs után gyakrabban jön doji" —
igen, de mindkettő a mozgalmas órákban sűrűsödik. A függetlenség-feltevésre
épülő khí-négyzet ezt a közös napszaki/volatilitás-ritmust is szignifikanciának
olvassa. A körkörös eltolás MEGTARTJA mindkét sorozat saját sűrűsödését, és
CSAK a kettő közti időbeli kapcsolatot töri el — így a p-érték arra a kérdésre
válaszol, amit tényleg kérdezünk.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def t_klaszter(v: np.ndarray, klaszter: np.ndarray) -> tuple[float, float, int]:
    """(átlag, klaszter-robusztus t, n). `klaszter`: pl. a nap azonosítója.

    A becslés a szokásos klaszter-robusztus átlag-SE:
        Var(mean) = Σ_g (Σ_{i∈g} (v_i - mean))² / n²
    """
    v = np.asarray(v, float)
    k = np.asarray(klaszter)
    ok = np.isfinite(v)
    v, k = v[ok], k[ok]
    n = len(v)
    if n < 3:
        return (float(v.mean()) if n else np.nan), np.nan, n
    mu = float(v.mean())
    dev = pd.Series(v - mu).groupby(k).sum().to_numpy()
    g = len(dev)
    if g < 2:
        return mu, np.nan, n
    # kis-minta korrekció (g/(g-1)) — a szokásos CR1
    var = (dev ** 2).sum() * (g / (g - 1)) / (n ** 2)
    if not (var > 0):
        return mu, np.nan, n
    return mu, mu / float(np.sqrt(var)), n


def evek_pozitiv(v: np.ndarray, ido: pd.DatetimeIndex,
                 alap: float = 0.0) -> tuple[float, int]:
    """Az évek hányad részében pozitív a TÖBBLET (és hány év van egyáltalán)."""
    v = np.asarray(v, float)
    s = pd.Series(v - alap, index=pd.DatetimeIndex(ido))
    ev = s.groupby(s.index.year).mean()
    ev = ev[np.isfinite(ev)]
    if len(ev) == 0:
        return np.nan, 0
    return float((ev > 0).mean()), int(len(ev))


def welch(a: np.ndarray, b: np.ndarray) -> float:
    """Welch-féle t két minta átlagkülönbségére (a > b irányban pozitív)."""
    a = np.asarray(a, float)[np.isfinite(a)]
    b = np.asarray(b, float)[np.isfinite(b)]
    if len(a) < 3 or len(b) < 3:
        return np.nan
    va, vb = a.var(ddof=1) / len(a), b.var(ddof=1) / len(b)
    if va + vb <= 0:
        return np.nan
    return float((a.mean() - b.mean()) / np.sqrt(va + vb))


def ns(ido) -> np.ndarray:
    """Időbélyegek int64 NANOSZEKUNDUMBAN — mértékegység-függetlenül.

    ⚠ EZ EGY MEGTÖRTÉNT HIBA JAVÍTÁSA (2026-09-19, önteszt). A `DatetimeIndex.asi8`
    az index SAJÁT felbontásában ad számot, és a pandas 2.0 óta ez nem mindig
    nanoszekundum: egy Parquet-körút után lehet mikroszekundum is. A 15 PERCES
    ablakból így csendben 15 000 perces (≈10 napos) ablak lett — a mérés futott,
    csak épp mást mért. Ezért minden időaritmetika ezen a függvényen megy át.
    """
    return np.asarray(pd.DatetimeIndex(ido).as_unit("ns").asi8)


def ablak_kezdet(ido: pd.DatetimeIndex, perc: int) -> np.ndarray:
    """Minden rácsponthoz: az ABLAK ELSŐ rácsindexe (idő szerint, nem lépésben).

    ⚠ Miért nem „w rácslépés": a rácsban hétvégi és ünnepnapi LYUKAK vannak.
    12 rácslépés hétfő reggel visszafelé nem egy óra, hanem három nap. A
    sorrend-állításnak („dupla csúcs UTÁN doji") csak akkor van értelme, ha a
    két esemény tényleges ideje közel van.
    """
    t = ns(ido)
    return np.searchsorted(t, t - int(perc) * 60 * 1_000_000_000, side="left")


class Elozmeny:
    """„Az A esemény megtörtént-e az ablakban, a kérdezett pont ELŐTT?"

    A prefix-összeg miatt egy lekérdezés O(1)/pont, az eltolás pedig csak a
    KÉRDEZETT pozíciókat tolja el (a prefix-összeget nem kell újraszámolni) —
    így 200 eltolásos null-minta is másodpercek alatt lefut.
    """

    def __init__(self, a_mask: np.ndarray):
        a = np.asarray(a_mask, bool)
        self.n = len(a)
        self.pre = np.concatenate([[0], np.cumsum(a, dtype=np.int64)])

    def elozve(self, b_idx: np.ndarray, lo_of: np.ndarray,
               eltolas: int = 0) -> np.ndarray:
        """bool: a b_idx pontok előtt (SZIGORÚAN, azonos rácspont nélkül) volt-e A.

        `lo_of`: az `ablak_kezdet` tömbje. `eltolas`: a kérdezett pozíciókat
        körkörösen eltoljuk — ez a null-minta.
        """
        b = np.asarray(b_idx, np.int64)
        if eltolas:
            b = (b + eltolas) % self.n
        lo = lo_of[b]
        return (self.pre[b] - self.pre[lo]) > 0

    def egyutt(self, a_mask: np.ndarray, b_idx: np.ndarray,
               eltolas: int = 0) -> np.ndarray:
        """Ugyanazon a rácsponton (lag = 0) — az „egyszerre" összehasonlítás."""
        b = np.asarray(b_idx, np.int64)
        if eltolas:
            b = (b + eltolas) % self.n
        return np.asarray(a_mask, bool)[b]


def eltolas_null(el: Elozmeny, b_idx: np.ndarray, lo_of: np.ndarray,
                 db: int = 200, mag: int = 0,
                 min_eltolas: int = 2000) -> np.ndarray:
    """A „megelőzve" ARÁNY null-eloszlása körkörös eltolásokkal.

    `min_eltolas`: ennél kisebb eltolás nem törné el a kapcsolatot (a rács M5,
    tehát 2000 lépés ≈ 7 kereskedési nap).
    """
    rng = np.random.default_rng(mag)
    n = el.n
    if n <= 2 * min_eltolas + 10 or len(b_idx) == 0:
        return np.array([])
    sz = rng.integers(min_eltolas, n - min_eltolas, size=db)
    return np.array([el.elozve(b_idx, lo_of, int(s)).mean() for s in sz])


def p_ketoldali(ertek: float, null: np.ndarray) -> float:
    """Empirikus kétoldali p-érték (a null mediánjától mért távolság alapján)."""
    null = np.asarray(null, float)
    null = null[np.isfinite(null)]
    if len(null) < 10 or not np.isfinite(ertek):
        return np.nan
    kozep = float(np.median(null))
    tav = abs(ertek - kozep)
    return float((np.abs(null - kozep) >= tav).mean())


def spearman(a, b) -> float:
    """Rangkorreláció SciPy nélkül (rang + Pearson).

    ⚠ A `Series.corr(method="spearman")` SciPy-t húz be, ami NINCS a
    `requirements.txt`-ben (csak a scikit-learn függőségeként kerül fel).
    Egy kutató-szkript ne dőljön el egy nem deklarált csomagon.
    """
    x = pd.Series(np.asarray(a, float))
    y = pd.Series(np.asarray(b, float))
    ok = x.notna() & y.notna()
    if int(ok.sum()) < 4:
        return np.nan
    return float(x[ok].rank().corr(y[ok].rank()))


def ablak_onteszt(ido, perc: int) -> bool:
    """ÖNTESZT: az `ablak_kezdet` tényleg `perc` hosszú ablakot ad-e?

    Ez a teszt egy VALÓDI, megtörtént hibát fog meg (lásd `ns`): a mértékegység
    elcsúszásától a 15 perces ablakból 10 napos lett, és a mérés attól még
    lefutott. Egy csendben rossz mérés rosszabb, mint egy elszálló program.
    """
    t = ns(ido)
    lo = ablak_kezdet(ido, perc)
    tav = (t - t[lo]) / 60e9              # percben
    ok = bool(np.all(tav <= perc + 1e-6))
    print(f"   ablak-önteszt ({perc} perc): leghosszabb visszanézés "
          f"{tav.max():.1f} perc, medián lépésszám "
          f"{np.median(np.arange(len(lo)) - lo):.0f}  -> "
          f"{'rendben' if ok else 'HIBA'}")
    return ok

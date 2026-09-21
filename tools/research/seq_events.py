"""ESEMÉNY-SZÓTÁR — a mátrix 2. dimenziója: MI történt, és MELYIK idősíkon.

A felhasználó kérése (2026-09-19): *„nem egyszerre kell ezeket keresni, hanem
azt feltárni, hogy mi után mi jön. Dupla csúcs után doji után trendváltozás."*

Ez a modul adja a SZÓTÁRAT: emberi nevű események (gyertya-alakzat, szerkezet,
trend, szorulás), idősíkonként, a közös rácsra vetítve, look-ahead nélkül.
A sorrend-mérés a `seq_matrix.py`-ban van.

⚠ MIÉRT KICSI SZÁNDÉKOSAN A SZÓTÁR. A `signal_lib` + `search` 480 000 jelöltet
állított elő, és a `holdout` ítélete az lett, hogy a keresési rangsor NEM jelez
előre. Itt 18 esemény x 3 idősík = 54 jel, a rendezett párok száma 54x53 ≈ 2862
— ez Bonferroni-val IS túlélhető (5% / 2862 = 1,7e-5), és minden cellának
emberi neve van, tehát a lelet elmondható és megcáfolható. A nagy szótár nem
„több esély", hanem kisebb bizonyító erő.

LOOK-AHEAD. Egy M15 bar, aminek a címkéje 08:00, 08:15-kor ZÁR. Az eseménye
csak a zárás UTÁNI első rácspontban válik igazzá (`searchsorted` a zárási
időkre) — ugyanaz a védelem, mint a `signal_lib`-ben, és ugyanaz az önteszt
(`onteszt()`) vonatkozik rá.

⚠ A RÁCS M5 (lásd `outcomes.STEP_MIN`). Ezért egy M1 esemény a KÖVETKEZŐ M5
rácspontra kerül, vagyis legfeljebb 5 perc késéssel. A mátrix M1 sora tehát azt
jelenti: „az elmúlt ≤5 percben történt". Ha a valódi M1-es ütem számít, az
`outcomes.py`-t kell `STEP_MIN = 1`-gyel újraépíteni (5x-ös költség).

Használat:

    import seq_events as SE
    jelek = SE.build("Ger40", racs_ido)      # név -> bool tömb a rácson
    SE.IRANY["M15:dupla_csucs"]              # -1 (medve), +1 (bika), 0 (semleges)
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
import seq_stat as ST

TFS = (1, 5, 15)            # a felhasználó hármasa: M1 - M5 - M15
PIVOT_K = 3                 # a swing-pont ennyi bar múlva válik ISMERTTÉ
ATR_N = 14

# Az esemény irány-elfogultsága. 0 = semleges (a doji önmagában nem irány!).
# ⚠ Ez NEM állítás arról, hogy működik — ez csak az az irány, amit a tankönyv
# hozzárendel. A mátrix pont azt méri, hogy hordoz-e bármit.
IRANY_ALAP = {
    "doji": 0, "pin_bika": +1, "pin_medve": -1,
    "elnyelo_bika": +1, "elnyelo_medve": -1,
    "belso_bar": 0, "kulso_bar": 0,
    "nagy_test_fel": +1, "nagy_test_le": -1,
    "dupla_csucs": -1, "dupla_alj": +1,
    "magasabb_alj": +1, "alacsonyabb_csucs": -1,
    "swing_tores_fel": +1, "swing_tores_le": -1,
    "trend_valtas_fel": +1, "trend_valtas_le": -1,
    "szorulas": 0,
}
NEVEK = tuple(IRANY_ALAP)
IRANY: dict[str, int] = {f"M{tf}:{n}": v for tf in TFS
                         for n, v in IRANY_ALAP.items()}


def _elozo(a: np.ndarray, n: int = 1) -> np.ndarray:
    """Az `a` tömb n barral eltolva (a jelen bar SOSEM látja a jövőt)."""
    out = np.full(len(a), np.nan, dtype=float)
    if n < len(a):
        out[n:] = a[:-n]
    return out


def _pivotok(h: np.ndarray, l: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Pivot high / low bool tömbök — VEKTORIZÁLVA.

    ⚠ Nem az `exp_struct.swings`-et hívjuk: az bar-onkénti Python ciklus, és a
    GOLD M1 mintája 4,7 millió bar (percekig futna). A középre igazított
    gördülő maximum ugyanazt adja, egy nagyságrenddel gyorsabban. A holtverseny
    (két azonos csúcs az ablakban) itt MINDKETTŐT pivotnak veszi — a dupla-csúcs
    mérésnél ez épp kívánatos.

    A visszaadott tömb a PIVOT BARJÁN igaz; ismertté csak k barral később válik,
    ezért minden felhasználás `_elozo(..., k)`-val tolva történik.
    """
    w = 2 * k + 1
    rmax = pd.Series(h).rolling(w, center=True, min_periods=w).max().to_numpy()
    rmin = pd.Series(l).rolling(w, center=True, min_periods=w).min().to_numpy()
    return (h >= rmax) & np.isfinite(rmax), (l <= rmin) & np.isfinite(rmin)


def _szerkezet(h, l, c, a, k=PIVOT_K) -> dict:
    """Szerkezeti események: dupla csúcs/alj, HL/LH, swing-törés.

    Minden esemény azon a baron keletkezik, ahol a pivot ISMERTTÉ válik
    (pivot bar + k), tehát nincs jövő-szivárgás.
    """
    n = len(c)
    ph, pl = _pivotok(h, l, k)
    E = {nev: np.zeros(n, bool) for nev in
         ("dupla_csucs", "dupla_alj", "magasabb_alj", "alacsonyabb_csucs",
          "swing_tores_fel", "swing_tores_le")}

    # ── a pivotok listája, ÉS a hozzájuk tartozó „ismertté válás" barja ──
    hi = np.flatnonzero(ph)
    lo = np.flatnonzero(pl)

    # dupla csúcs: két közeli magasságú pivot high, köztük érdemi völggyel
    def _dupla(idx, ar, jel, volgy_ar, volgy_jel):
        for t in range(1, len(idx)):
            i0, i1 = idx[t - 1], idx[t]
            tav = i1 - i0
            if not (5 <= tav <= 60):
                continue
            j = i1 + k                      # ekkor válik ismertté
            if j >= n or not np.isfinite(a[j]) or a[j] <= 0:
                continue
            if abs(ar[i1] - ar[i0]) > 0.25 * a[j]:
                continue
            # a két csúcs között legyen legalább 0,7 ATR mélységű völgy
            koz = volgy_ar[i0:i1 + 1]
            if len(koz) == 0:
                continue
            melyseg = (min(ar[i0], ar[i1]) - koz.min() if volgy_jel > 0
                       else koz.max() - max(ar[i0], ar[i1]))
            if melyseg >= 0.7 * a[j]:
                E[jel][j] = True

    _dupla(hi, h, "dupla_csucs", l, +1)
    _dupla(lo, l, "dupla_alj", h, -1)

    # magasabb alj / alacsonyabb csúcs: az ÚJ pivot a régihez képest
    for idx, ar, jel, elojel in ((lo, l, "magasabb_alj", +1),
                                 (hi, h, "alacsonyabb_csucs", -1)):
        for t in range(1, len(idx)):
            i0, i1 = idx[t - 1], idx[t]
            j = i1 + k
            if j >= n or not np.isfinite(a[j]) or a[j] <= 0:
                continue
            kul = (ar[i1] - ar[i0]) * elojel
            if kul >= 0.10 * a[j]:
                E[jel][j] = True

    # swing-törés: a záró átlépi a LEGUTÓBB ISMERTTÉ VÁLT pivot árát
    def _szint(idx, ar):
        s = np.full(n, np.nan)
        for i in idx:
            j = i + k
            if j < n:
                s[j] = ar[i]
        return pd.Series(s).ffill().to_numpy()

    felso = _szint(hi, h)
    also = _szint(lo, l)
    pc = _elozo(c)
    E["swing_tores_fel"] = (c > felso) & ~(pc > felso)
    E["swing_tores_le"] = (c < also) & ~(pc < also)
    return E


def _esemenyek(d: pd.DataFrame) -> dict:
    """Egy idősík ÖSSZES eseménye — bar-szintű bool tömbök."""
    o = d["open"].to_numpy(float)
    h = d["high"].to_numpy(float)
    l = d["low"].to_numpy(float)
    c = d["close"].to_numpy(float)
    a = lab.atr(h, l, c, ATR_N)
    a = np.where(np.isfinite(a) & (a > 0), a, np.nan)

    rng = h - l
    test = np.abs(c - o)
    felso = h - np.maximum(o, c)
    also = np.minimum(o, c) - l
    po, pc, ph_, pl_ = _elozo(o), _elozo(c), _elozo(h), _elozo(l)

    with np.errstate(invalid="ignore"):
        E = {
            # ── gyertya-alakzatok ──────────────────────────────────────────
            "doji": (test <= 0.10 * rng) & (rng >= 0.30 * a),
            "pin_bika": (also >= 2 * test) & (also >= 0.50 * rng) & (rng >= 0.5 * a),
            "pin_medve": (felso >= 2 * test) & (felso >= 0.50 * rng) & (rng >= 0.5 * a),
            "elnyelo_bika": (c > o) & (pc < po) & (c >= po) & (o <= pc),
            "elnyelo_medve": (c < o) & (pc > po) & (c <= po) & (o >= pc),
            "belso_bar": (h <= ph_) & (l >= pl_),
            "kulso_bar": (h > ph_) & (l < pl_),
            "nagy_test_fel": (c > o) & (test >= 1.0 * a),
            "nagy_test_le": (c < o) & (test >= 1.0 * a),
        }
        E.update(_szerkezet(h, l, c, a))

        # ── trend-változás: az SMA50 5-bares meredekségének ELŐJEL-VÁLTÁSA ─
        ma = lab.sma(c, 50)
        mer = ma - _elozo(ma, 5)
        pmer = _elozo(mer)
        E["trend_valtas_fel"] = (mer > 0) & (pmer <= 0)
        E["trend_valtas_le"] = (mer < 0) & (pmer >= 0)

        # ── szorulás: az ATR a saját alapmércéje alá esik ──────────────────
        alap = pd.Series(a).rolling(100, min_periods=50).mean().to_numpy()
        szuk = a < 0.70 * alap
        E["szorulas"] = szuk & ~np.concatenate([[False], szuk[:-1]])

    # a NaN-okból származó „igaz" eseményeket kizárjuk
    ervenyes = np.isfinite(a)
    return {k: np.asarray(v, bool) & ervenyes for k, v in E.items()}


def _racsra(bar_mask: np.ndarray, zaras: pd.DatetimeIndex,
            racs: pd.DatetimeIndex) -> np.ndarray:
    """Bar-szintű esemény -> RÁCS-PILLANAT, a bar zárása UTÁNI első rácspontra.

    Nem „ffill + felfutó él": ha ugyanaz az esemény két egymás utáni baron is
    igaz, mindkettő külön pillanat marad. (A `signal_lib.felfuto` a második
    ismétlést elnyelné — ott ez helyes, mert ott ÁLLAPOTBÓL csinál eseményt,
    itt viszont már eleve esemény van.)
    """
    ts = zaras[np.flatnonzero(bar_mask)]
    # ⚠ int64 NANOSZEKUNDUMBAN hasonlítunk (`ST.ns`): a Parquet-körút után a két
    # index felbontása eltérhet (ns vs us), és a keveredés csendben rossz
    # illesztést adna.
    j = np.searchsorted(ST.ns(racs), ST.ns(ts), side="left")
    j = j[(j >= 0) & (j < len(racs))]
    out = np.zeros(len(racs), bool)
    out[j] = True
    return out


def build(sym: str, racs_ido: pd.DatetimeIndex, tfs=TFS,
          m1: pd.DataFrame | None = None) -> dict:
    """Minden (esemény, idősík) a közös rácsra vetítve. név -> bool tömb.

    `m1`: ha megadod, ezt használjuk a betöltött előzmény HELYETT — így
    ugyanaz a szótár futtatható egy SZINTETIKUS (null-)piacon is
    (`sl_paths.szintetikus`), ami a sorrend-mátrix null-összehasonlítása.
    """
    m1 = lab.load_m1(sym) if m1 is None else m1
    racs = pd.DatetimeIndex(racs_ido)
    ki: dict[str, np.ndarray] = {}
    for tf in tfs:
        d = m1 if tf == 1 else lab.resample(m1, tf)
        zaras = d.index + pd.Timedelta(minutes=tf)
        E = _esemenyek(d)
        for nev in NEVEK:
            ki[f"M{tf}:{nev}"] = _racsra(E[nev], zaras, racs)
        print(f"   {sym} M{tf}: {len(NEVEK)} esemény, "
              f"{sum(int(ki[f'M{tf}:{n}'].sum()) for n in NEVEK):,} pillanat",
              flush=True)
    return ki


def onteszt(sym: str, racs_ido: pd.DatetimeIndex, tf: int = 15) -> bool:
    """LOOK-AHEAD önteszt: egy esemény nem jelenhet meg a barja ZÁRÁSA előtt."""
    m1 = lab.load_m1(sym)
    d = lab.resample(m1, tf)
    zaras = d.index + pd.Timedelta(minutes=tf)
    E = _esemenyek(d)
    racs = pd.DatetimeIndex(racs_ido)
    hiba = 0
    for nev in NEVEK:
        bars = np.flatnonzero(E[nev])
        if len(bars) == 0:
            continue
        j = np.searchsorted(ST.ns(racs), ST.ns(zaras[bars]), side="left")
        ok = j < len(racs)
        hiba += int((racs[j[ok]] < zaras[bars][ok]).sum())
    print(f"   look-ahead önteszt ({sym}, M{tf}): {hiba} korai pillanat "
          f"-> {'HIBA' if hiba else 'rendben'}")
    return hiba == 0


if __name__ == "__main__":
    sym = _sys.argv[1] if len(_sys.argv) > 1 else "Ger40"
    o = pd.read_parquet(ROOT / "data" / "outcomes" / f"{sym}.parquet")
    ido = pd.DatetimeIndex(o["ido"])
    onteszt(sym, ido)
    jelek = build(sym, ido)
    sor = []
    for nev, m in jelek.items():
        sor.append({"jel": nev, "db": int(m.sum()),
                    "gyakorisag_%": 100 * float(m.mean()),
                    "irany": IRANY[nev]})
    t = pd.DataFrame(sor).sort_values("db", ascending=False)
    print(f"\n{sym}: {len(jelek)} jel, {len(ido):,} rácspont")
    print(t.to_string(index=False, float_format=lambda v: f"{v:8.3f}"))

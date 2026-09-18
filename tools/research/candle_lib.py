"""GYERTYA-ALAKZATOK mint ESEMENY-jelek — a klasszikus japan mintak szamszeru
definicioi (eloregisztralva 2026-09-17, a vault „Gyertya-alakzatok —
eloregisztralt kerdes" jegyzeteben).

Minden fuggveny egy OHLC tablabol (egy idosik) ad vissza egy
`nev -> bool tomb` szotart, ahol a nev a TANKONYVI IRANYT is hordozza
(`…->long` / `…->short`). A jel azon a gyertyan igaz, amelyik a mintat LEZARJA
— a `signal_lib.build` ezt tolja a zaras utani elso M5 racspontra.

Konvenciok (a jegyzettel azonosan):
    test      = |c - o|            tartomany = h - l
    felso     = h - max(o, c)      also      = min(o, c) - l
    ATR       = ATR(14) az adott idosikon
    elozmeny  = a minta ELOTTI gyertya zarasa az 5-tel korabbi zarashoz kepest
                (le = ereszkedo, fel = emelkedo)
    torpe     = tartomany < 0,5 ATR  -> a minta-gyertyak egyike sem lehet torpe
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import numpy as np

import lab

MIN_RANGE_ATR = 0.5     # a minta-gyertya tartomanya legalabb ennyi ATR
TREND_LOOKBACK = 5      # az elozmeny: c[-1] vs c[-1-5]
# PIPA (✓) — eloregisztralva 2026-09-18 (vault „Pipa szignal — eloregisztralt kerdes")
PIPA_K = 12             # ablak: a melypont ennyi gyertyan belul van a kitores elott
PIPA_W1 = 5             # a kezdoszint: a legmagasabb zaras a melypont elotti W1 gyertyan
PIPA_MELYSEG = 1.0      # (P0 - melypont) / ATR legalabb ennyi
# PIN BAR — ugyanott rogzitve: kanoc >= 2/3 tartomany, a test a masik harmadban
PIN_KANOC = 2.0 / 3.0
# PIPA2 (szigoru) — 2026-09-18, a rajzok utan rogzitve: P0 a TELJES ablak legmagasabb
# zarasa a melypont elott, melyseg >= 1,5 ATR, es az ablak elotti 20 gyertya nem eso
PIPA2_MELYSEG = 1.5
PIPA2_ELOTT = 20
PIPA2_ELOTT_MIN_ATR = -1.0
# DUPLA CSUCS / ALJ — 2026-09-18 (vault „Dupla csucs-alj — eloregisztralt kerdes")
DUPLA_K = 3              # swing: a ±K gyertyan belul szelsoertek
DUPLA_TAV = (5, 40)      # a ket swing tavolsaga gyertyaban
DUPLA_TOL = 0.25         # a ket szelsoertek egyezese ATR-ben
DUPLA_MELYSEG = 1.0      # nyakvonal - szelsoertek >= ennyi ATR
DUPLA_ELOTT = 20         # az elozmeny: a p1 elotti 20 gyertya legmagasabb zarasa >= nyakvonal
DUPLA_K2 = 30            # a kitores legfeljebb ennyi gyertyaval p2 utan


def _prev(a: np.ndarray, k: int = 1) -> np.ndarray:
    """`a` eltolva k gyertyaval hatra (az elso k ertek NaN)."""
    out = np.full_like(a, np.nan, dtype=float)
    if k < len(a):
        out[k:] = a[:-k]
    return out


def gyertyak(o, h, l, c, atr=None) -> dict[str, np.ndarray]:
    """nev -> bool tomb (a minta a gyertyan lezarul)."""
    return _szamol(o, h, l, c, atr)[0]


def gyertyak_minoseg(o, h, l, c, atr=None) -> tuple[dict, dict]:
    """(E, Q): a maszkok ES a FELISMERES MINOSEGE 0..1 (NaN, ahol nincs minta).

    minoseg = 0,5 x alak + 0,5 x meret, ahol
      alak  = mennyivel haladja meg a minta a sajat kuszobet (a kuszobon 0,
              a kuszob ketszeresenel / a teljes alaknal 1),
      meret = (tartomany/ATR - 0,5) / 1,0 levagva 0..1 (0,5 ATR -> 0, 1,5 ATR -> 1).
    Fokozatok: gyenge < 0,33 <= kozepes < 0,66 <= eros.
    """
    return _szamol(o, h, l, c, atr)


def _cl(x):
    return np.clip(x, 0.0, 1.0)


def _ablak(a: np.ndarray, k: int) -> np.ndarray:
    """(n, k) nezet: az i. sor = a[i-k .. i-1] (a MEGELOZO k ertek); az elso k
    sor NaN."""
    from numpy.lib.stride_tricks import sliding_window_view
    out = np.full((len(a), k), np.nan)
    if len(a) > k:
        out[k:] = sliding_window_view(a[:-1], k)
    return out


def pipa(o, h, l, c, atr, K=PIPA_K, W1=PIPA_W1, melyseg=PIPA_MELYSEG):
    """PIPA (✓): gyors eses, majd a kezdoszint FOLE zaro visszapattanas.

    Bika, a t gyertyan (a kitores):
      m  = a legalacsonyabb low helye a [t-K, t) ablakban
      P0 = a legmagasabb ZARAS az [m-W1, m) gyertyakon, helye a -> bal szar = m-a
      (P0 - low[m]) / ATR[t] >= melyseg
      close[t] > P0 es az (m, t) kozotti zarasok egyike sem > P0 (ELSO kitores)
      jobb szar = t-m >= bal szar
    Visszaad: (bika_maszk, medve_maszk, minoseg_bika, minoseg_medve) — a
    minoseg az alak-resz (melyseg/ATR: 1 -> 0, 3 -> 1).
    """
    n = len(c)
    t = np.arange(n)
    # a megelozo K low / high -> melypont / csucs helye (abszolut index)
    L = _ablak(l, K)
    H = _ablak(h, K)
    ok = t >= K + W1 + 1
    m_lo = np.where(ok, t - K + np.nanargmin(np.where(np.isnan(L), np.inf, L), axis=1), 0)
    m_hi = np.where(ok, t - K + np.nanargmax(np.where(np.isnan(H), -np.inf, H), axis=1), 0)
    # kezdoszint: a legmagasabb (bika) / legalacsonyabb (medve) zaras a melypont
    # elotti W1 gyertyan
    C = _ablak(c, W1)                       # C[i] = c[i-W1 .. i-1]
    Cm = C[m_lo]
    a_rel = np.nanargmax(np.where(np.isnan(Cm), -np.inf, Cm), axis=1)
    P0_b = Cm[np.arange(n), a_rel]
    bal_b = m_lo - (m_lo - W1 + a_rel)      # = W1 - a_rel  (1..W1)
    Cm2 = C[m_hi]
    a_rel2 = np.nanargmin(np.where(np.isnan(Cm2), np.inf, Cm2), axis=1)
    P0_m = Cm2[np.arange(n), a_rel2]
    bal_m = W1 - a_rel2
    jobb_b = t - m_lo
    jobb_m = t - m_hi
    # az (m, t) kozotti zarasok maximuma / minimuma: a K-ablak zarasai, az m-ig
    # tartokat kizarva
    CK = _ablak(c, K)                       # CK[i] = c[i-K .. i-1]
    pos = np.arange(K)[None, :] + (t - K)[:, None]   # abszolut indexek
    kozott_b = np.where(pos > m_lo[:, None], CK, -np.inf).max(axis=1)
    kozott_m = np.where(pos > m_hi[:, None], CK, np.inf).min(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        mely_b = (P0_b - l[m_lo]) / atr
        mely_m = (h[m_hi] - P0_m) / atr
        nagy = np.isfinite(atr) & ((h - l) >= MIN_RANGE_ATR * atr)
        bika = (ok & nagy & np.isfinite(P0_b) & (mely_b >= melyseg) & (c > P0_b)
                & (kozott_b <= P0_b) & (jobb_b >= bal_b) & (jobb_b >= 1))
        medve = (ok & nagy & np.isfinite(P0_m) & (mely_m >= melyseg) & (c < P0_m)
                 & (kozott_m >= P0_m) & (jobb_m >= bal_m) & (jobb_m >= 1))
        q_b = _cl((mely_b - melyseg) / 2.0)
        q_m = _cl((mely_m - melyseg) / 2.0)
    return bika, medve, q_b, q_m


def pipa_szigoru(o, h, l, c, atr, K=PIPA_K, melyseg=PIPA2_MELYSEG,
                 elott=PIPA2_ELOTT, elott_min=PIPA2_ELOTT_MIN_ATR):
    """PIPA2 (szigoru ✓): a kezdoszint az ESES TENYLEGES KEZDETE az ablakon belul.

    Bika, a t gyertyan:
      m  = a legalacsonyabb low helye a [t-K, t) ablakban
      P0 = a legmagasabb ZARAS a [t-K, m) szakaszon (helye a) -> bal szar = m-a >= 1
      (P0 - low[m]) / ATR[t] >= melyseg
      close[t] > P0, az (m, t) kozotti zarasok egyike sem > P0, jobb szar t-m >= bal
      az ablak ELOTTI `elott` gyertya netto elmozdulasa (ATR-ben) > elott_min
      (nem egy mar zuhano piac kozepen)
    Medve: tukor. Visszaad: (bika, medve, q_bika, q_medve)."""
    n = len(c)
    t = np.arange(n)
    ok = t >= K + elott + 2
    L = _ablak(l, K)
    H = _ablak(h, K)
    CK = _ablak(c, K)                                   # CK[i] = c[i-K .. i-1]
    pos = np.arange(K)[None, :] + (t - K)[:, None]      # abszolut indexek
    j_lo = np.nanargmin(np.where(np.isnan(L), np.inf, L), axis=1)
    j_hi = np.nanargmax(np.where(np.isnan(H), -np.inf, H), axis=1)
    m_lo = np.where(ok, t - K + j_lo, 0)
    m_hi = np.where(ok, t - K + j_hi, 0)
    # P0: a melypont ELOTTI zarasok maximuma (bika) / a csucs elotti minimuma (medve)
    elotte_b = np.where(pos < m_lo[:, None], CK, -np.inf)
    elotte_m = np.where(pos > -1, np.where(pos < m_hi[:, None], CK, np.inf), np.inf)
    a_b = np.argmax(elotte_b, axis=1)
    a_m = np.argmin(elotte_m, axis=1)
    P0_b = elotte_b[np.arange(n), a_b]
    P0_m = elotte_m[np.arange(n), a_m]
    bal_b = j_lo - a_b
    bal_m = j_hi - a_m
    jobb_b = t - m_lo
    jobb_m = t - m_hi
    kozott_b = np.where(pos > m_lo[:, None], CK, -np.inf).max(axis=1)
    kozott_m = np.where(pos > m_hi[:, None], CK, np.inf).min(axis=1)
    # az ablak elotti `elott` gyertya netto elmozdulasa
    c_ablak_elott = _prev(c, K + 1)
    c_regen = _prev(c, K + 1 + elott)
    with np.errstate(invalid="ignore", divide="ignore"):
        elmozd = (c_ablak_elott - c_regen) / atr
        mely_b = (P0_b - l[m_lo]) / atr
        mely_m = (h[m_hi] - P0_m) / atr
        nagy = np.isfinite(atr) & ((h - l) >= MIN_RANGE_ATR * atr)
        bika = (ok & nagy & np.isfinite(P0_b) & (bal_b >= 1) & (mely_b >= melyseg)
                & (c > P0_b) & (kozott_b <= P0_b) & (jobb_b >= bal_b)
                & (elmozd > elott_min))
        medve = (ok & nagy & np.isfinite(P0_m) & (bal_m >= 1) & (mely_m >= melyseg)
                 & (c < P0_m) & (kozott_m >= P0_m) & (jobb_m >= bal_m)
                 & (elmozd < -elott_min))
        q_b = _cl((mely_b - melyseg) / 2.0)
        q_m = _cl((mely_m - melyseg) / 2.0)
    return bika, medve, q_b, q_m


def _swing(x, k, also=True):
    """Igazolt swing-pontok: az i. gyertya a ±k ablakban szelsoertek (szigoru
    min/max a tobbivel szemben, dontetlen: az elso). Az i+k gyertyanal igazolodik."""
    n = len(x)
    out = np.zeros(n, dtype=bool)
    if n < 2 * k + 1:
        return out
    from numpy.lib.stride_tricks import sliding_window_view
    W = sliding_window_view(x, 2 * k + 1)          # W[j] = x[j .. j+2k], kozep j+k
    mid = W[:, k][:, None]
    tobbi = np.delete(W, k, axis=1)
    if also:
        ok = (mid < tobbi).all(axis=1) | ((mid <= tobbi).all(axis=1) & (np.argmin(W, axis=1) == k))
    else:
        ok = (mid > tobbi).all(axis=1) | ((mid >= tobbi).all(axis=1) & (np.argmax(W, axis=1) == k))
    out[k:n - k] = ok
    return out


def dupla(o, h, l, c, atr, k=DUPLA_K, tav=DUPLA_TAV, tol=DUPLA_TOL,
          melyseg=DUPLA_MELYSEG, elott=DUPLA_ELOTT, k2=DUPLA_K2, gyengulo=False):
    """DUPLA ALJ (long) / DUPLA CSUCS (short) — a nyakvonal toresen.

    Visszaad: (long_maszk, short_maszk, q_long, q_short) — a maszk a KITORO
    gyertyan igaz; q = 0,5 x egyezes + 0,5 x melyseg-alak.

    `gyengulo=True` (2. valtozat, 2026-09-18, a felhasznalo kerese): a masodik
    szelsoertek a GYENGEBB oldalon van — dupla csucsnal a 2. csucs ALACSONYABB
    (0 < high[p1]-high[p2] <= tol ATR), dupla aljnal a 2. alj MAGASABB; `tol`
    itt 0,5 ATR."""
    n = len(c)
    nagy = np.isfinite(atr) & ((h - l) >= MIN_RANGE_ATR * atr)
    res = {}
    for irany, x, y, sw_also in (("long", l, h, True), ("short", h, l, False)):
        maszk = np.zeros(n, dtype=bool)
        q = np.full(n, np.nan)
        sw = np.flatnonzero(_swing(x, k, also=sw_also))
        sgn = 1.0 if irany == "long" else -1.0
        for j2 in range(len(sw)):
            p2 = sw[j2]
            a2 = atr[p2]
            if not np.isfinite(a2) or a2 <= 0:
                continue
            # a p2-hoz legkozelebbi korabbi swing, ami egyezik es a tavolsag jo
            p1 = -1
            for j1 in range(j2 - 1, -1, -1):
                d = p2 - sw[j1]
                if d > tav[1]:
                    break
                if gyengulo:
                    # long: a 2. alj magasabb (x=low, sgn=+1); short: a 2. csucs alacsonyabb
                    delta = sgn * (x[p2] - x[sw[j1]])
                    egyezik = (delta > 0) and (delta <= tol * a2)
                else:
                    egyezik = abs(x[sw[j1]] - x[p2]) <= tol * a2
                if d >= tav[0] and egyezik:
                    p1 = sw[j1]
                    break
            if p1 < 0:
                continue
            # nyakvonal: a kozbenso szakasz szelsoerteke (long: max high)
            kozott = y[p1 + 1:p2]
            if len(kozott) == 0:
                continue
            N = kozott.max() if irany == "long" else kozott.min()
            mely = sgn * (N - max(x[p1], x[p2])) if irany == "long" else (min(x[p1], x[p2]) - N)
            if mely < melyseg * a2:
                continue
            # elozmeny: a p1 elotti `elott` gyertya legmagasabb (long) / legalacsonyabb zarasa
            if p1 - elott < 0:
                continue
            ce = c[p1 - elott:p1]
            if irany == "long" and ce.max() < N:
                continue
            if irany == "short" and ce.min() > N:
                continue
            # kitores: az elso zaras a nyakvonalon tul p2+k utan, legfeljebb k2-vel p2 utan
            lo, hi = p2 + k + 1, min(n, p2 + k2 + 1)
            if lo >= hi:
                continue
            cc = c[lo:hi]
            tul = (cc > N) if irany == "long" else (cc < N)
            if not tul.any():
                continue
            t = lo + int(np.argmax(tul))
            if not nagy[t]:
                continue
            # a p2..t kozott sem zart mar tul (az elso zaras) — cc[:t-lo] mind nem tul, ok
            # es a p2+1..p2+k kozott sem
            kz = c[p2 + 1:lo]
            if len(kz) and ((kz > N).any() if irany == "long" else (kz < N).any()):
                continue
            maszk[t] = True
            egyezes = 1.0 - abs(x[p1] - x[p2]) / (tol * a2)
            q[t] = 0.5 * _cl(egyezes) + 0.5 * _cl((mely / a2 - melyseg) / 2.0)
        res[irany] = (maszk, q)
    return res["long"][0], res["short"][0], res["long"][1], res["short"][1]


def pinbar(o, h, l, c, atr, kanoc=PIN_KANOC):
    """PIN BAR: az egyik kanoc >= kanoc x tartomany, a test (o es c) a masik
    harmadban; NINCS trend-feltetel. Irany a kanoc ELLEN.
    Visszaad: (long_maszk, short_maszk, minoseg_long, minoseg_short)."""
    tart = h - l
    also = np.minimum(o, c) - l
    felso = h - np.maximum(o, c)
    with np.errstate(invalid="ignore", divide="ignore"):
        nagy = np.isfinite(atr) & (tart >= MIN_RANGE_ATR * atr)
        lo_ok = nagy & (also >= kanoc * tart) & (np.minimum(o, c) >= h - (1 - kanoc) * tart)
        hi_ok = nagy & (felso >= kanoc * tart) & (np.maximum(o, c) <= l + (1 - kanoc) * tart)
        q_lo = _cl((also / tart - kanoc) / (1 - kanoc))
        q_hi = _cl((felso / tart - kanoc) / (1 - kanoc))
    return lo_ok, hi_ok, q_lo, q_hi


def _szamol(o, h, l, c, atr=None):
    o, h, l, c = (np.asarray(x, float) for x in (o, h, l, c))
    if atr is None:
        atr = lab.atr(h, l, c, 14)
    test = np.abs(c - o)
    tart = h - l
    felso = h - np.maximum(o, c)
    also = np.minimum(o, c) - l
    poz = c > o
    neg = c < o
    nagy = np.isfinite(atr) & (tart >= MIN_RANGE_ATR * atr)   # nem torpe

    # elozmeny: a minta ELOTTI gyertya zarasa vs 5-tel korabbi
    def elozmeny(elso_gyertya_eltolas: int):
        """`elso_gyertya_eltolas` = hany gyertyaval korabban KEZDODIK a minta
        (1-gyertyas minta: 0; 2-gyertyas: 1; 3-gyertyas: 2)."""
        k = elso_gyertya_eltolas + 1
        c_elott = _prev(c, k)
        c_regen = _prev(c, k + TREND_LOOKBACK)
        le = c_elott < c_regen
        fel = c_elott > c_regen
        return le, fel

    # az elozmeny (a jegyzet szerint) CSAK az egygyertyas fordulos mintakhoz
    # kell (doji, kalapacs/akasztott, forditott kalapacs/hullocsillag); a
    # tobbgyertyas mintak alakja onmagaban hordozza az iranyt.
    le1, fel1 = elozmeny(0)

    p1 = {k: _prev(v, 1) for k, v in dict(o=o, h=h, l=l, c=c, test=test,
                                            tart=tart, poz=poz, neg=neg,
                                            nagy=nagy).items()}
    p2 = {k: _prev(v, 2) for k, v in dict(o=o, c=c, test=test, tart=tart,
                                            poz=poz, neg=neg, nagy=nagy).items()}
    p1poz, p1neg, p1nagy = p1["poz"] == 1, p1["neg"] == 1, p1["nagy"] == 1
    p2poz, p2neg, p2nagy = p2["poz"] == 1, p2["neg"] == 1, p2["nagy"] == 1

    E: dict[str, np.ndarray] = {}
    Q: dict[str, np.ndarray] = {}      # alak-minoseg 0..1 mintankent (nev '->' nelkul)
    np.seterr(divide="ignore", invalid="ignore")
    q_meret = _cl((tart / atr - MIN_RANGE_ATR) / 1.0)

    # 1. doji
    doji = nagy & (test <= 0.1 * tart)
    E["gy_doji->long"] = doji & le1
    E["gy_doji->short"] = doji & fel1
    Q["gy_doji"] = _cl(1.0 - (test / tart) / 0.1)

    # 2–3. kalapacs / akasztott ember (azonos alak, mas elozmeny)
    kalapacs_alak = nagy & (also >= 2 * test) & (felso <= 0.1 * tart) & (test > 0)
    E["gy_kalapacs->long"] = kalapacs_alak & le1
    E["gy_akasztott->short"] = kalapacs_alak & fel1
    Q["gy_kalapacs"] = Q["gy_akasztott"] = _cl((also / test - 2.0) / 2.0)

    # 4–5. forditott kalapacs / hullocsillag
    ford_alak = nagy & (felso >= 2 * test) & (also <= 0.1 * tart) & (test > 0)
    E["gy_ford_kalapacs->long"] = ford_alak & le1
    E["gy_hullocsillag->short"] = ford_alak & fel1
    Q["gy_ford_kalapacs"] = Q["gy_hullocsillag"] = _cl((felso / test - 2.0) / 2.0)

    # 6. elnyelo
    E["gy_bika_elnyelo->long"] = (nagy & p1nagy & p1neg & poz & (o <= p1["c"])
                                  & (c >= p1["o"]) & (test > p1["test"]))
    E["gy_medve_elnyelo->short"] = (nagy & p1nagy & p1poz & neg & (o >= p1["c"])
                                    & (c <= p1["o"]) & (test > p1["test"]))
    Q["gy_bika_elnyelo"] = Q["gy_medve_elnyelo"] = _cl(test / p1["test"] - 1.0)

    # 7. harami (az elozo nagy testu, a mostani a testen belul)
    p1_nagytest = p1nagy & (p1["test"] >= 0.5 * p1["tart"])
    belul = (np.maximum(o, c) <= np.maximum(p1["o"], p1["c"])) & \
            (np.minimum(o, c) >= np.minimum(p1["o"], p1["c"]))
    E["gy_bika_harami->long"] = p1_nagytest & p1neg & belul & poz
    E["gy_medve_harami->short"] = p1_nagytest & p1poz & belul & neg
    Q["gy_bika_harami"] = Q["gy_medve_harami"] = _cl(1.0 - test / p1["test"])

    # 8. attoro / sotet felho
    p1_kozep = (p1["o"] + p1["c"]) / 2
    E["gy_attoro->long"] = (nagy & p1nagy & p1neg & poz & (o < p1["c"])
                            & (c > p1_kozep) & (c < p1["o"]))
    E["gy_sotet_felho->short"] = (nagy & p1nagy & p1poz & neg & (o > p1["c"])
                                  & (c < p1_kozep) & (c > p1["o"]))
    Q["gy_attoro"] = _cl((c - p1_kozep) / (p1["test"] / 2))
    Q["gy_sotet_felho"] = _cl((p1_kozep - c) / (p1["test"] / 2))

    # 9. hajnalcsillag / esti csillag (3 gyertya: -2 nagy, -1 kicsi, 0 zaro)
    p2_nagytest = p2nagy & (p2["test"] >= 0.5 * p2["tart"])
    p2_kozep = (p2["o"] + p2["c"]) / 2
    kicsi_kozep = p1["test"] <= 0.3 * p2["test"]
    E["gy_hajnalcsillag->long"] = (p2_nagytest & p2neg & kicsi_kozep & nagy & poz
                                   & (c > p2_kozep))
    E["gy_esti_csillag->short"] = (p2_nagytest & p2poz & kicsi_kozep & nagy & neg
                                   & (c < p2_kozep))
    Q["gy_hajnalcsillag"] = _cl((c - p2_kozep) / (p2["test"] / 2))
    Q["gy_esti_csillag"] = _cl((p2_kozep - c) / (p2["test"] / 2))

    # 10. harom feher katona / harom fekete varju
    teltest = nagy & (test >= 0.5 * tart)
    p1_teltest = p1nagy & (p1["test"] >= 0.5 * p1["tart"])
    p2_teltest = p2nagy & (p2["test"] >= 0.5 * p2["tart"])
    o_p1testben = (o >= np.minimum(p1["o"], p1["c"])) & (o <= np.maximum(p1["o"], p1["c"]))
    p1o_p2testben = (p1["o"] >= np.minimum(p2["o"], p2["c"])) & \
                    (p1["o"] <= np.maximum(p2["o"], p2["c"]))
    E["gy_harom_katona->long"] = (teltest & p1_teltest & p2_teltest & poz & p1poz & p2poz
                                  & (c > p1["c"]) & (p1["c"] > p2["c"])
                                  & o_p1testben & p1o_p2testben)
    E["gy_harom_varju->short"] = (teltest & p1_teltest & p2_teltest & neg & p1neg & p2neg
                                  & (c < p1["c"]) & (p1["c"] < p2["c"])
                                  & o_p1testben & p1o_p2testben)
    Q["gy_harom_katona"] = Q["gy_harom_varju"] = _cl(
        ((test / tart + p1["test"] / p1["tart"] + p2["test"] / p2["tart"]) / 3 - 0.5) / 0.5)

    # 11. csipesz (ket gyertya, azonos szelsoertek 0,1 ATR-en belul)
    E["gy_csipesz_alj->long"] = (nagy & p1nagy & (np.abs(l - p1["l"]) <= 0.1 * atr)
                                 & p1neg & poz)
    E["gy_csipesz_teto->short"] = (nagy & p1nagy & (np.abs(h - p1["h"]) <= 0.1 * atr)
                                   & p1poz & neg)
    Q["gy_csipesz_alj"] = _cl(1.0 - np.abs(l - p1["l"]) / (0.1 * atr))
    Q["gy_csipesz_teto"] = _cl(1.0 - np.abs(h - p1["h"]) / (0.1 * atr))

    # 12. marubozu (folytatas)
    maru = nagy & (test >= 0.9 * tart)
    E["gy_marubozu->long"] = maru & poz
    E["gy_marubozu->short"] = maru & neg
    Q["gy_marubozu"] = _cl((test / tart - 0.9) / 0.1)

    # 13. PIPA (✓) es 14. PIN BAR — 2026-09-18, kulon eloregisztralva
    pb, pm, qpb, qpm = pipa(o, h, l, c, atr)
    E["gy_pipa->long"], E["gy_pipa->short"] = pb, pm
    Q["gy_pipa"] = np.where(pb, qpb, qpm)
    lb, sb, qlb, qsb = pinbar(o, h, l, c, atr)
    E["gy_pinbar->long"], E["gy_pinbar->short"] = lb, sb
    Q["gy_pinbar"] = np.where(lb, qlb, qsb)
    # 15. PIPA2 (szigoru) — 2026-09-18, a rajzok utan kulon rogzitve
    pb2, pm2, qpb2, qpm2 = pipa_szigoru(o, h, l, c, atr)
    E["gy_pipa2->long"], E["gy_pipa2->short"] = pb2, pm2
    Q["gy_pipa2"] = np.where(pb2, qpb2, qpm2)
    # 16. DUPLA ALJ / CSUCS — 2026-09-18, kulon eloregisztralva
    dl, ds, qdl, qds = dupla(o, h, l, c, atr)
    E["gy_dupla->long"], E["gy_dupla->short"] = dl, ds
    Q["gy_dupla"] = np.where(dl, qdl, qds)
    # 17. DUPLA2 — a masodik szelsoertek gyengebb (2. valtozat)
    dl2, ds2, qdl2, qds2 = dupla(o, h, l, c, atr, tol=0.5, gyengulo=True)
    E["gy_dupla2->long"], E["gy_dupla2->short"] = dl2, ds2
    Q["gy_dupla2"] = np.where(dl2, qdl2, qds2)

    E = {k: np.where(np.isfinite(v.astype(float)), v, False).astype(bool)
         for k, v in E.items()}
    Qout = {}
    for k, m in E.items():
        q = 0.5 * Q[k.split("->")[0]] + 0.5 * q_meret
        Qout[k] = np.where(m & np.isfinite(q), q, np.nan)
    return E, Qout


def irany(nev: str) -> str:
    """A tankonyvi irany a nevbol: 'long' / 'short'."""
    return nev.rsplit("->", 1)[-1].split(" ")[0]


def alap_nev(nev: str) -> str:
    """'M15:gy_kalapacs->long' -> 'kalapacs'."""
    n = nev.split(":", 1)[-1]
    n = n.split("->", 1)[0]
    return n[3:] if n.startswith("gy_") else n


if __name__ == "__main__":
    sym = _sys.argv[1] if len(_sys.argv) > 1 else "Ger40"
    m1 = lab.load_m1(sym)
    for tf in (15, 60):
        d = lab.resample(m1, tf)
        E = gyertyak(d["open"].to_numpy(), d["high"].to_numpy(),
                     d["low"].to_numpy(), d["close"].to_numpy())
        print(f"{sym} M{tf}: {len(d):,} gyertya")
        for k, v in E.items():
            print(f"   {k:28s} {int(v.sum()):7d}  ({100 * v.mean():.2f} %)")

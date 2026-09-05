"""
„SZÉP CHART" MÉRŐSZÁMOK — a trendvonal-illeszkedés (R²) és ami köré épül.

Forrás: `Tananyagok/Szép chart definíció` (TK-002, FX Tanoda). Az előadó
kulcsmondata: *„Ha gondolkodnod kell rajta, hogy mi a trend, az azt jelenti,
hogy nincsen trend."* A „szép" itt nem esztétika, hanem KERESKEDHETŐSÉG.

A tananyag hierarchiája szerint a legfontosabb (0,4 súly) a **trendvonal
illeszkedése**: eső trendnél a csúcsokra, emelkedőnél a völgyekre illesztett
egyenes R²-e. `R² ≥ 0,80` = szép, `< 0,50` = choppy.

── HÁROM DOLOG, AMIT EZ A MODUL KOMOLYAN VESZ ──────────────────────────

**1. A SWING-PONT KÉSVE IGAZOLÓDIK — ez look-ahead csapda.**
Egy gyertya akkor swing-csúcs, ha a `high`-ja a [i−n, i+n] ablak maximuma. Az
`i+n` viszont a JÖVŐ: az i. báron még nem tudható. A projekt ebbe már többször
belefutott (viz↔backtest paritás, a kutató-labor `_map_to`-ja), ezért itt a
swing-maszk `n` bárral EL VAN TOLVA: a t. bár csak azokat a swingeket látja,
amelyek `t−n`-ig igazolódtak. Enélkül a mérőszám a jövőt olvasná, és minden
backteszt szépnek látszana.

**2. A ZOOM-RELATIVITÁS — a tananyag maga figyelmeztet rá.**
*„Egy zoom: emelkedő trend. Más zoom: eső trend. Harmadik zoom: oldalazás."*
A tananyag a percentilis-pozícióra ad multi-scale receptet (N=50/100/200), az
R²-re NEM — pedig ott ugyanez a probléma. Ezért itt az R² TÖBB ablakon számol,
és az összevonás alapból a **minimum**: egy chart csak akkor „szép", ha MINDEN
nagyításban az. Ez az előadó saját szabálya (*„Ha kizoom másként néz ki: nem
szép"*), és egyben a konzervatív irány.

**3. AZ R² = a swing-pontok x/y korrelációjának NÉGYZETE.**
Egyszerű lineáris regresszióra a kettő azonos, viszont így gördülő
összegekből számolható (Σx, Σy, Σx², Σy², Σxy) — vektorizáltan, nem
báronkénti regresszióval. 1,3 millió gyertyán ez a különbség percek és órák
között dönt.

⚠ A TÖKÉLETES TREND NEM KAP PONTSZÁMOT — és ez nem hiba, hanem a definíció
következménye. Egy szigorúan monoton szakaszon NINCS lokális minimum/maximum,
tehát nincs swing-pont sem, amire vonalat lehetne illeszteni → az R² `NaN`.
A trendvonalhoz ÉRINTÉSEK kellenek (a tananyag is ≥3-at ír elő), az érintés
pedig visszahúzódást feltételez. Valós adaton ez nem korlát (a medián R² ~0,5,
tehát bőven van swing), de a mérőszám olvasásakor tudni kell: a `NaN` nem
„csúnya", hanem „nincs mihez illeszteni".

⚠ EZ A MODUL CSAK MÉR. Nem kapu, nem stratégia, és semmit nem szűr. A
küszöbök (`R2_SZEP`, `R2_CHOPPY`) a tananyagból valók — hogy a MI adatunkon
állnak-e, azt mérés dönti el (lásd `0016 - Szép chart score`).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# A tananyag küszöbei. ⚠ NEM a mi adatunkon validálva — lásd a modul-fejlécet.
R2_SZEP = 0.80          # e fölött „szép chart" (erős lineáris trend)
R2_CHOPPY = 0.50        # e alatt choppy, nem kereskedhető
MIN_SWING = 3           # ennyi swing-pont kell; 2 pontra az R² MINDIG 1,0

# Az alapértelmezett nagyítások. A tananyag a percentilis-pozícióra ezeket
# ajánlja (H1-en), és az R²-re ugyanez az elv áll.
SKALAK = (50, 100, 200)

# A swing-detektálás fél-ablaka. A tananyag „N=3 H1-en" ajánlást ad.
SWING_N = 3


def swing_mask(df: pd.DataFrame, n: int = SWING_N,
               tol_atr: float = 0.0, atr_n: int = 14) -> tuple:
    """`(csúcs, völgy)` boolean Series — a MÁR IGAZOLÓDOTT swing-pontok.

    ⚠ AZ ELTOLÁS NEM KOZMETIKA. Egy swing-csúcshoz a jobb oldali `n` gyertya is
    kell, ami a döntés pillanatában még nem létezik. A maszkot ezért `n` bárral
    előre toljuk: a t. báron az látszik, ami `t−n`-ig eldőlt. Így a mérőszám
    ok-okozatilag helyes — pontosan az, ami élesben is tudható.

    ⚠ A TŰRÉS (`tol_atr`) SEM KOZMETIKA. Tűrés nélkül a feltétel PONTOS
    egyenlőség (`high == az ablak maxa`), és egy 0,01-es eltérés kizár egy
    egyébként nyilvánvaló fordulópontot. A piacon nincs pontos egyenlőség —
    ahogy a felhasználó fogalmazott: *„sosem lesz olyan, hogy pontosan 4000-nél
    pattan vissza"*. `tol_atr > 0` esetén a küszöb `ablak_max − tol·ATR`.

    ⚠ TŰRÉSSEL RITKÍTANI IS KELL: különben egy lapos tető MINDEN bárja swing
    lenne, és a pontok összecsomósodnának. Egy csoportból a LEGSZÉLSŐ marad."""
    h, l = df["high"], df["low"]
    w = 2 * n + 1
    mx = h.rolling(w, center=True).max()
    mn = l.rolling(w, center=True).min()
    if tol_atr > 0:
        tol = tol_atr * _atr(df, atr_n)
        csucs, volgy = (h >= mx - tol), (l <= mn + tol)
        # ritkítás: egy `w` széles csoportból csak a legszélső pont marad
        csucs &= h == h.where(csucs).rolling(w, center=True, min_periods=1).max()
        volgy &= l == l.where(volgy).rolling(w, center=True, min_periods=1).min()
    else:
        csucs, volgy = (mx == h), (mn == l)
    return (csucs.fillna(False).shift(n, fill_value=False).astype(bool),
            volgy.fillna(False).shift(n, fill_value=False).astype(bool))


def _r2_gordulo(ertek: pd.Series, maszk: pd.Series, ablak: int) -> pd.Series:
    """Az ablakban lévő (maszkolt) pontokra illesztett egyenes R²-e.

    A képlet a Pearson-korreláció négyzete — egyszerű lineáris regresszióra ez
    AZONOS az R²-vel, viszont gördülő összegekből számolható:

        R² = (n·Σxy − Σx·Σy)² / ((n·Σx² − (Σx)²) · (n·Σy² − (Σy)²))

    `NaN`, ha kevesebb mint `MIN_SWING` pont van, vagy ha bármelyik szórás
    nulla (függőleges/vízszintes pontsor — ott az illesztés értelmetlen)."""
    x = pd.Series(np.arange(len(ertek), dtype=float), index=ertek.index)
    m = maszk.astype(float)
    xs, ys = x * m, ertek.to_numpy() * m
    ys = pd.Series(ys, index=ertek.index)

    def g(s):
        return s.rolling(ablak, min_periods=1).sum()

    n = g(m)
    Sx, Sy = g(xs), g(ys)
    Sxx, Syy, Sxy = g(xs * x), g(ys * ertek), g(xs * ertek)

    szam = (n * Sxy - Sx * Sy) ** 2
    nev = (n * Sxx - Sx ** 2) * (n * Syy - Sy ** 2)
    r2 = szam / nev.replace(0, np.nan)
    return r2.where(n >= MIN_SWING).clip(0.0, 1.0)


def trendline_szoras(ertek: pd.Series, maszk: pd.Series, ablak: int,
                     atr: pd.Series) -> pd.Series:
    """A swing-pontok TÁVOLSÁGA az illesztett egyenestől, **ATR-ben**.

    ⚠ MIÉRT KELL AZ R² MELLÉ. Az R² skálafüggetlen: azt mondja meg, a szórás
    hány százalékát magyarázza a vonal — de NEM azt, hogy a pontok milyen
    KÖZEL vannak hozzá. Lapos piacon a pontok lehetnek fél gyertyányira a
    vonaltól, az R² mégis alacsony (alig van mit magyarázni); meredek trendben
    fordítva. A tananyag „érintésszám ≥3 (tolerance-sáv alapú)" kritériuma épp
    ezt a hiányzó felet adná — ez itt annak a folytonos változata.

    A képlet a gördülő összegekből jön (nincs báronkénti regresszió):

        SS_res / n = var_y · (1 − R²)      →      szórás = √(…) / ATR

    Olvasata: **hány szokásos gyertyányira szórnak a fordulópontok a vonaltól.**
    `0,5` = fél gyertyán belül (szoros vonal), `3,0` = szétszórt."""
    x = pd.Series(np.arange(len(ertek), dtype=float), index=ertek.index)
    m = maszk.astype(float)
    xs = x * m
    ys = pd.Series(ertek.to_numpy() * m, index=ertek.index)

    def g(s_):
        return s_.rolling(ablak, min_periods=1).sum()

    n = g(m)
    Sx, Sy = g(xs), g(ys)
    Sxx, Syy, Sxy = g(xs * x), g(ys * ertek), g(xs * ertek)
    nn = n.replace(0, np.nan)
    var_y = Syy / nn - (Sy / nn) ** 2
    var_x = Sxx / nn - (Sx / nn) ** 2
    cov = Sxy / nn - (Sx / nn) * (Sy / nn)
    r2 = (cov ** 2) / (var_x * var_y).replace(0, np.nan)
    ss = (var_y * (1.0 - r2.clip(0.0, 1.0))).clip(lower=0)
    return (np.sqrt(ss) / atr.replace(0, np.nan)).where(n >= MIN_SWING)


def trendline_r2(df: pd.DataFrame, ablak: int, n: int = SWING_N) -> pd.Series:
    """A trendvonal R²-e EGY nagyításon.

    ⚠ MELYIK PONTSORRA ILLESZTÜNK? A tananyag szerint eső trendnél a
    CSÚCSOKRA, emelkedőnél a VÖLGYEKRE — mert a trendvonal a mozgás „alját"
    (emelkedő) vagy „tetejét" (eső) fogja össze. Az irányt az ablak nettó
    elmozdulása adja; iránytalan ablaknál a két illesztés közül a ROSSZABBAT
    vesszük, mert ott egyik oldal sem meggyőző."""
    csucs, volgy = swing_mask(df, n)
    c = df["close"]
    r2_cs = _r2_gordulo(df["high"], csucs, ablak)
    r2_vo = _r2_gordulo(df["low"], volgy, ablak)
    fel = (c - c.shift(ablak)) > 0
    le = (c - c.shift(ablak)) < 0
    out = pd.concat([r2_cs, r2_vo], axis=1).min(axis=1)     # iránytalan eset
    out = out.where(~fel, r2_vo)
    out = out.where(~le, r2_cs)
    return out


def r2_multi(df: pd.DataFrame, skalak=SKALAK, n: int = SWING_N,
             mod: str = "min") -> pd.Series:
    """Multi-scale R² — a zoom-relativitás kezelése.

    `mod`:
      `min`   (alap) — csak akkor szép, ha MINDEN nagyításon az. Ez az előadó
                       szabálya: *„Ha kizoom másként néz ki: nem szép."*
      `mean`  — a három skála átlaga (a tananyag `Pos_robust` receptje)
      `max`   — elég egy nagyításon szépnek lennie (megengedő)

    ⚠ A `min` SZÁNDÉKOSAN az alapértelmezés. Egyetlen skálán mérve az R² annak
    a skálának a műterméke; a szűk ablak szinte mindig „szép" (kevés pontra
    könnyű egyenest illeszteni)."""
    tabla = pd.concat([trendline_r2(df, w, n) for w in skalak], axis=1)
    if mod == "mean":
        return tabla.mean(axis=1)
    if mod == "max":
        return tabla.max(axis=1)
    return tabla.min(axis=1)


def swing_db(df: pd.DataFrame, ablak: int, n: int = SWING_N) -> pd.DataFrame:
    """Hány IGAZOLÓDOTT swing-pont van az ablakban (csúcs és völgy külön).

    A tananyag „érintésszám" kritériuma: ≥3 érvényes vonal, ≥5 „nincs kérdés".
    Két pont bármit összeköt — ezért nem elég."""
    csucs, volgy = swing_mask(df, n)
    return pd.DataFrame({
        "csucs": csucs.astype(float).rolling(ablak, min_periods=1).sum(),
        "volgy": volgy.astype(float).rolling(ablak, min_periods=1).sum(),
    }, index=df.index)


# ---------------------------------------------------------------------------
# Percentilis pozíció — a chart „harmadai" (a tananyag 0,3 súlyú jellemzője)
# ---------------------------------------------------------------------------

def pos(df: pd.DataFrame, ablak: int) -> pd.Series:
    """`(Close − Low_N) / (High_N − Low_N)` — hol áll az ár az ablakban.

    A tananyag szerint a felső/alsó harmad = trend, a középső = oldalazás.
    ⚠ A tananyag ZÁRÓÁRAKKAL definiálja a szélsőértékeket (nem high/low-val),
    ezért itt is úgy — különben más mérőszám lenne ugyanazon a néven."""
    c = df["close"]
    lo = c.rolling(ablak).min()
    hi = c.rolling(ablak).max()
    return (c - lo) / (hi - lo).replace(0, np.nan)


def pos_robust(df: pd.DataFrame, skalak=SKALAK) -> pd.Series:
    """A `pos` átlaga több nagyításon — a tananyag saját receptje a
    zoom-relativitásra (N=50/100/200). `≥0,67` felső, `≤0,33` alsó harmad."""
    return pd.concat([pos(df, w) for w in skalak], axis=1).mean(axis=1)


# ---------------------------------------------------------------------------
# MEGEGYEZÉSI SZINT — „van-e olyan szint, ami megfogja a csapkodást?"
# ---------------------------------------------------------------------------
# ⚠ EZ NEM A TANANYAGBÓL VAN, hanem a felhasználó megfigyeléséből (2026-09-05),
# és a mérések szerint pont az hiányzott. A példája:
#
#   CSAPKODÁS:  4000 → 4013 → 3980 → 4022 → 3965   (a szélsőértékek TÁGULNAK,
#               nincs szint, amihez visszatérne)
#   SZÉP:       4000 → 4013 → 3980 → 4003 → 3970   (a 4000 környékére VISSZATÉR,
#               „arról pattant vissza")
#
# A kettő ADX-ben, ATR-arányban és trendvonal-R²-ben nagyjából EGYFORMA — mégis
# az egyik kereskedhető, a másik nem. Ezt egyik eddigi dimenzió sem fogja meg.
#
# ⚠ A TŰRÉS NEM ELHAGYHATÓ. A felhasználó külön kiemelte: „sosem lesz olyan,
# hogy pontosan 4000-nél pattan vissza". A sáv ezért ATR-ben van megadva, nem
# abszolút árban — így instrumentum- és rezsim-független.

TOL_ATR = 0.5           # a megegyezési sáv fél-szélessége, ATR-ben

# ── A CSATORNA-TŰRÉSEK — MÉRT kvantilisekből, nem tippből ───────────────
# ⚠ KÉT KÜLÖN DOLOG, ezért két külön szám. Eddig egy tűrés szolgálta mindkettőt,
# és az rossz volt: a „mozdul-e a fal" és a „széttart-e a kettő" nem ugyanaz.
#
# Mérve (6 pár, 60 000 M15 gyertya, 100-as ablak):
#
#   a fal meredeksége |ATR/bár|   10%: 0,0094 · 20%: 0,0189 · 50%: 0,0517
#   a falak széttartása (ATR)     10%: 0,16   · 30%: 0,51   · 50%: 0,91
#
# `TOL_MEREDEK`: e alatt a fal az ablakon át kevesebb mint ~1 ATR-t mozdul —
#   vagyis VÍZSZINTES. Ez a meredekségek alsó 10%-a.
# `TOL_SZETTART`: e alatt a két fal az ablakon át kevesebb mint fél ATR-t
#   távolodik — vagyis PÁRHUZAMOS. Ez a legszorosabb ~30%.
TOL_MEREDEK = 0.01      # ATR/bár — e alatt a fal „nem megy sehova"
TOL_SZETTART = 0.5      # ATR az EGÉSZ ablakon — e alatt „párhuzamos"
# A tágulás tűrése ARÁNYRA vonatkozik: ennyivel kell nagyobbnak lennie az
# ablak friss felének, hogy tágulásnak számítson (1,01 még zaj).
TOL_TAGULAS = 0.25


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    prev = c.shift(1)
    tr = pd.concat([h - l, (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def agreement(df: pd.DataFrame, ablak: int = 100, tol_atr: float = TOL_ATR,
              atr_n: int = 14) -> pd.DataFrame:
    """Egyeznek-e a FORDULÓPONTOK egy közös szinten?

    ⚠ AZ ELSŐ NEKIFUTÁSOM MEGBUKOTT, és érdemes tudni, min. Először a gördülő
    MEDIÁNT vettem szintnek, és azt mértem, mennyi időt tölt ott az ár. A
    felhasználó két példáján ez FORDÍTVA sült el (a csapkodásra adott magasabb
    sűrűséget). Az ok: a megegyezési szint nem ott van, ahol az ár időt tölt,
    hanem ahol **visszafordul**.

        CSAPKODÁS:  csúcsok 4013 → 4022 (tágul),  völgyek 3980 → 3965 (tágul)
        SZÉP:       csúcsok 4013 → 4003 (egy szinten), völgyek 3980 → 3970

    Ez a VÍZSZINTES megfelelője annak, amit a `trendline_r2` ferdén mér: ott a
    swingek egy lejtős egyenesre esnek, itt egy vízszintesre. A tananyag
    „≥3 érintés" szabálya mindkettőre áll.

    Visszaad:

    `csucs_szoras` a swing-CSÚCSOK szórása az ablakban, **ATR-ben**. Kicsi =
                   a csúcsok egyetértenek egy ellenállás-szintben.
    `volgy_szoras` ugyanez a völgyekre (támasz).
    `szoras`       a kettő minimuma — elég, ha az EGYIK oldal egyértelmű
                   (a tananyag is így fogalmaz: eső trendnél a csúcsok,
                   emelkedőnél a völgyek).
    `csucs_db` / `volgy_db`  hány igazolt swing van az ablakban (az „érintés").

    ⚠ A TŰRÉS ATR-BEN van, nem árban — a felhasználó külön kiemelte, hogy
    „sosem lesz olyan, hogy pontosan 4000-nél pattan vissza". Ezért ATR-re
    normálunk: így instrumentum- és rezsim-független a mérőszám.

    ⚠ OK-OKOZATI: a swing-maszk `n` bárral eltolt (lásd `swing_mask`), tehát
    csak a MÁR IGAZOLÓDOTT fordulópontok számítanak."""
    csucs, volgy = swing_mask(df, SWING_N)
    atr = _atr(df, atr_n)

    def _szoras(ertek: pd.Series, maszk: pd.Series) -> tuple:
        m = maszk.astype(float)
        y = ertek.to_numpy() * m
        y = pd.Series(y, index=ertek.index)
        n = m.rolling(ablak, min_periods=1).sum()
        Sy = y.rolling(ablak, min_periods=1).sum()
        Syy = (y * ertek).rolling(ablak, min_periods=1).sum()
        var = (Syy - Sy ** 2 / n.replace(0, np.nan)) / (n - 1).replace(0, np.nan)
        sz = np.sqrt(var.clip(lower=0)) / atr.replace(0, np.nan)
        return sz.where(n >= MIN_SWING), n

    cs_sz, cs_db = _szoras(df["high"], csucs)
    vo_sz, vo_db = _szoras(df["low"], volgy)
    return pd.DataFrame({
        "csucs_szoras": cs_sz, "volgy_szoras": vo_sz,
        "szoras": pd.concat([cs_sz, vo_sz], axis=1).min(axis=1),
        "csucs_db": cs_db, "volgy_db": vo_db,
    }, index=df.index)


def _regi_agreement(df: pd.DataFrame, ablak: int = 100,
 tol_atr: float = TOL_ATR,
              atr_n: int = 14) -> pd.DataFrame:
    """A megegyezési szint és az ereje.

    Visszaad három oszlopot:

    `szint`     a jelölt szint — az ablak **medián** záróára. A medián azért jó,
                mert robusztus: néhány kilógó csúcs/völgy nem mozdítja el, épp
                azok viszont a „csapkodás" tüskéi.
    `suru`      az ablak záróárainak hányada a `szint ± tol` sávban. Ez a
                KONCENTRÁCIÓ: 1,0 = minden ár a szinten, 0,0 = sehol.
    `erintes`   hányszor lépett vissza az ár KÍVÜLRŐL a sávba az ablakban.
                Ez a „pattanás" — a felhasználó szerinti bizonyíték arra, hogy a
                szint tényleg megfogja.

    ⚠ A KETTŐ NEM UGYANAZ, és külön is kell nézni. Egy szűk oldalazásban a
    `suru` magas, de az `erintes` alacsony (ki sem megy a sávból). A
    felhasználó „szép csapkodása" épp a fordítottja: az ár KIMEGY, majd
    VISSZAJÖN — ott az `erintes` a jellemző, nem a sűrűség.

    ⚠ OK-OKOZATI: minden gördülő ablak csak a múltat nézi."""
    c = df["close"]
    szint = c.rolling(ablak).median()
    tol = tol_atr * _atr(df, atr_n)

    # Sűrűség: hány záróár esik a MOSTANI szint ± tol sávba az ablakban.
    # ⚠ Ez ablakonként más referenciát jelent, ezért nem lehet egy maszkból
    # gördülő összeget csinálni — darabolva, csúszó nézettel számoljuk.
    cv, sv, tv = c.to_numpy(float), szint.to_numpy(float), tol.to_numpy(float)
    n = len(cv)
    suru = np.full(n, np.nan)
    if n >= ablak:
        abl = np.lib.stride_tricks.sliding_window_view(cv, ablak)
        LEP = 50_000                       # memória-korlát: darabonként
        for a in range(0, len(abl), LEP):
            b = min(a + LEP, len(abl))
            i = np.arange(a, b) + ablak - 1
            d = np.abs(abl[a:b] - sv[i, None])
            suru[i] = (d <= tv[i, None]).mean(axis=1)

    # Érintés: a sávba KÍVÜLRŐL való visszalépések száma az ablakban.
    benne = (c - szint).abs() <= tol
    belep = benne & ~benne.shift(1, fill_value=False)
    erintes = belep.astype(float).rolling(ablak, min_periods=1).sum()

    return pd.DataFrame({"szint": szint, "suru": pd.Series(suru, index=df.index),
                         "erintes": erintes}, index=df.index)


def trendline(df: pd.DataFrame, ablak: int, n: int = SWING_N,
              atr_n: int = 14) -> pd.DataFrame:
    """A trendvonal KÉT mérőszáma együtt — mert külön egyik sem elég.

    `r2`      a szórás hány %-át magyarázza a vonal (skálafüggetlen, tűrés nélkül)
    `szoras`  a fordulópontok távolsága a vonaltól, **ATR-ben** (ez a tűrés)

    ⚠ A KETTŐ KÜLÖN IS FÉLREVEZET. Magas R² + nagy szórás = meredek trend, amin
    a swingek tágan szórnak. Alacsony R² + kicsi szórás = szűk oldalazás, ahol
    minden pont közel van a (vízszintes) vonalhoz. A tananyag „szép chart"-ja
    az, ahol MINDKETTŐ jó: a vonal magyaráz IS, és a pontok közel IS vannak."""
    csucs, volgy = swing_mask(df, n)
    atr = _atr(df, atr_n)
    c = df["close"]
    fel = (c - c.shift(ablak)) > 0
    r2_cs = _r2_gordulo(df["high"], csucs, ablak)
    r2_vo = _r2_gordulo(df["low"], volgy, ablak)
    sz_cs = trendline_szoras(df["high"], csucs, ablak, atr)
    sz_vo = trendline_szoras(df["low"], volgy, ablak, atr)
    return pd.DataFrame({
        "r2": r2_vo.where(fel, r2_cs),
        "szoras": sz_vo.where(fel, sz_cs),
    }, index=df.index)


def _meredekseg(ertek: pd.Series, maszk: pd.Series, ablak: int) -> pd.Series:
    """Az illesztett egyenes MEREDEKSÉGE (ár/bár), gördülő összegekből."""
    x = pd.Series(np.arange(len(ertek), dtype=float), index=ertek.index)
    m = maszk.astype(float)
    xs = x * m
    ys = pd.Series(ertek.to_numpy() * m, index=ertek.index)

    def g(s_):
        return s_.rolling(ablak, min_periods=1).sum()

    n = g(m)
    nn = n.replace(0, np.nan)
    Sx, Sy = g(xs), g(ys)
    Sxx, Sxy = g(xs * x), g(xs * ertek)
    var_x = Sxx / nn - (Sx / nn) ** 2
    cov = Sxy / nn - (Sx / nn) * (Sy / nn)
    return (cov / var_x.replace(0, np.nan)).where(n >= MIN_SWING)


def csatorna(df: pd.DataFrame, ablak: int, n: int = SWING_N,
             atr_n: int = 14, tol_atr: float = TOL_ATR) -> pd.DataFrame:
    """CSATORNA vagy ÉK? — a tananyag 3. pontja, és ez hiányzott a legjobban.

    ⚠ MIÉRT NEM ELÉG AZ R². Egy TÁGULÓ ÉK (a csúcsok emelkednek, a völgyek
    süllyednek — a felhasználó „csapkodás" példája) a legrondább chart, amit a
    piac gyárt. Az R²-je viszont ~1,00, mert a csúcsok TÖKÉLETESEN egy emelkedő
    egyenesre esnek. Megmérve: a táguló ék R² 0,99 / vonal-szórás 0,07 — vagyis
    az R² szerint SZEBB, mint egy valódi, szint körül rendeződő piac (0,46).

    A tananyag épp erre ad választ: *„a trendvonal mellé PÁRHUZAMOS csatornafal
    is húzható"*. A csatorna két fala párhuzamos; az éké széttart.

    Visszaad:

    `parhuzam`   a két meredekség eltérése, **ATR/bár egységben**. 0 = tökéletes
                 csatorna, nagy = ék (széttartó vagy összetartó falak).
    `tagul`      True, ha a falak SZÉTtartanak (csúcsok fel, völgyek le) — ez a
                 „csapkodás" alakzata.
    `mer_csucs` / `mer_volgy`  a két meredekség (ATR/bár), a diagnosztikához.

    ⚠ ATR-RE NORMÁLVA, mert egy „0,5 ár/bár" meredekség aranyon és egy indexen
    teljesen mást jelent."""
    csucs, volgy = swing_mask(df, n, TOL_ATR, atr_n)
    atr = _atr(df, atr_n).replace(0, np.nan)
    m_cs = _meredekseg(df["high"], csucs, ablak) / atr
    m_vo = _meredekseg(df["low"], volgy, ablak) / atr
    # ⚠ KÉT KÜLÖN TŰRÉS, mért kvantilisekből (lásd `TOL_MEREDEK` / `TOL_SZETTART`).
    # A „mozdul-e ez a fal" és a „széttart-e a kettő" nem ugyanaz a kérdés, és
    # egyetlen tűrés nem szolgálhatja mindkettőt.
    szettart = (m_cs - m_vo).abs() * float(ablak)      # ATR az EGÉSZ ablakon
    return pd.DataFrame({
        "parhuzam": szettart,
        "parhuzamos": szettart <= TOL_SZETTART,
        "tagul": (m_cs > TOL_MEREDEK) & (m_vo < -TOL_MEREDEK),
        "szukul": (m_cs < -TOL_MEREDEK) & (m_vo > TOL_MEREDEK),
        "mer_csucs": m_cs, "mer_volgy": m_vo,
    }, index=df.index)


def tagulas(df: pd.DataFrame, ablak: int = 100, atr_n: int = 14) -> pd.DataFrame:
    """TÁGUL-e a mozgás? — a csapkodás gyakori alakja.

    ⚠ MIÉRT KELLETT A `csatorna.tagul` MELLÉ. Az szigorú geometriai ék (a
    csúcsok emelkednek ÉS a völgyek süllyednek, mindkettő tűrésen túl): mérve a
    kötések **0,1%-án** tüzel. Igaz, de túl ritka ahhoz, hogy szűrő legyen.

    A felhasználó leírása viszont nem ritka jelenség: *„hirtelen sokat mozdul
    felfelé, majd hirtelen sokat mozdul lefelé"* — vagyis a LENGÉSEK NŐNEK.
    A példáiban a lengés-amplitúdók:

        csapkodás:  13 → 33 → 42 → 57   (nő)
        szép:       13 → 33 → 23 → 33   (állandó)

    Visszaad:

    `arany`   az ablak MÁSODIK felének ártartománya osztva az ELSŐÉVEL.
              `>1` = tágul, `<1` = szűkül. Ez a folytonos mérőszám.
    `tagul`   `arany > 1 + TOL_TAGULAS` — tűréssel, mert az 1,01 még zaj.
    `sav_atr` a teljes ablak ártartománya ATR-ben (a nagyságrendhez).

    ⚠ A TŰRÉS ITT IS KELL, és arányra vonatkozik: a `TOL_TAGULAS` azt mondja,
    hány százalékkal kell nagyobbnak lennie a második félnek, hogy tágulásnak
    számítson."""
    h, l = df["high"], df["low"]
    fel = ablak // 2
    # elso fel: az ablak regebbi fele (eltolva), masodik fel: a friss
    r_uj = h.rolling(fel).max() - l.rolling(fel).min()
    r_regi = r_uj.shift(fel)
    arany = r_uj / r_regi.replace(0, np.nan)
    sav = (h.rolling(ablak).max() - l.rolling(ablak).min()) / _atr(df, atr_n).replace(0, np.nan)
    return pd.DataFrame({"arany": arany, "tagul": arany > 1.0 + TOL_TAGULAS,
                         "sav_atr": sav}, index=df.index)

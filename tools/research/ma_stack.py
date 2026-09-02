"""NEGY MOZGOATLAG TAVOLSAGA — mintazatok es trendfordulo (M1, SMA 8/21/100/250).

A FELHASZNALO KERESE (2026-09-02): "4 mozgoatlagot szeretnek hasznalni, idosik
M1, SMA 8, 21, 100, 250 … folyamatosan merjuk a 4 mozgoatlag kozotti tavolsagot,
es talaljunk benne mintazatokat. Peldaul ha 100-250 tavolodik a trend marad, ha
21-250 kozelit, valtozni fog … a trendfordulot a leheto legkorabban csipjuk el
… nezd meg, mi van ha a ket nagy trendvonal tavolodik, es mi van akkor, ha
kozelit, a kozelitéskor mikor erdemes kiszallni."

Harom kerdes, harom kulon meres:

  A) LEIRO. Tavolodo vs kozelito 100-250 mellett mi a KOVETKEZO n perc hozama a
     trend iranyaban? (Ez a hipotezis nyers formaja — meg nem kereskedes.)
  B) FORDULO. A 21-250 kozelitese tenyleg elorejelzi-e az irany-valtast? A
     merce a FELTETELES valoszinuseg az ALAPRATAHOZ kepest — enelkul minden
     jelzes "mukodni latszik", mert a trend amugy is valt neha.
  C) BELEPO/KISZALLAS. Ami A-ban es B-ben latszik, atmegy-e KOLTSEGGEL egy
     szimulacion, kulon LONG es SHORT iranyban, evenkent.

⚠ AZ ELFOGADASI PROTOKOLL (a research/README.md-bol, elore rogzitve):
   1. t >= 2 az osszevont mintan,
   2. az evek legalabb 60%-aban pozitiv,
   3. legalabb 3 instrumentumon pozitiv.
A 2. pont oli meg a "haromevnyi szerencses szakaszt", amit a t-statisztika nem.

⚠ ELORE ROGZITETT VARAKOZAS (hogy utolag ne lehessen atirni). Az eddigi
meresek szerint a korlat a KOLTSEG, nem az indikator-valasztas:
`indicator-list-screened` (23 szabaly x 5 par x 2 irany = 230 teszt, NULLA olyan,
ahol mindket irany pozitiv), `expectancy-equals-minus-cost` (minden belepo
≈ −(spread/stop)), `breakout-signal-equals-its-cost` (14 even van irany-el
bruttoban, de a spread+swap pontosan felemeszti). Ezert azt varom, hogy az (A)
leiro osszefugges VALODI lesz (a mozgoatlagok definicio szerint az arbol
szarmaznak, tehat a tavolsaguk egyutt mozog a trenddel), a (C) kereskedheto el
viszont NEM. Ez joslat, nem eredmeny — a meres dontse el.

⚠ AMI NEM MERES, HANEM TAUTOLOGIA. A "100-250 tavolodik" allapot RESZBEN mar
tartalmazza a mult hozamat: a tavolodas AZERT tortent, mert az ar ment. Ha a
"kovetkezo n perc"-et a tavolodas MERTEKEVEL magyarazzuk, konnyen csak azt
mondjuk vissza, hogy a trend trendelt. Ezert az (A) merve van az ALAPRATAHOZ
(feltetel nelkuli atlaghoz) kepest is, es a (B) a fordulo FELTETELES
valoszinuseget az alapratahoz meri.

Futtatas a projekt gyokerebol:

    python tools/research/ma_stack.py
    python tools/research/ma_stack.py --symbols GOLD USDJPY --reszek A B
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

import lab

# A negy periodus — a felhasznalo keresenek megfeleloen, M1-en.
PERIODUSOK = (8, 21, 100, 250)
# Ennyi baron nezzuk, tagul-e vagy szukul-e a tavolsag. 60 perc: eleg hosszu,
# hogy ne a zajt merje, eleg rovid, hogy a "korai" fordulohoz meg idoben legyen.
LEJTO_ABLAK = 60
# Elore-tekintesi tavok percben (a leiro meres horizontjai).
HORIZONTOK = (30, 60, 120, 240)
# Az ATR ablaka a NORMALIZALASHOZ: a leglassabb MA-val egyutt mozogjon, hogy a
# tavolsagok instrumentumok kozott osszehasonlithatok legyenek.
ATR_ABLAK = 250

# 13,3 / 9,5 / 4,9 ev — az evenkenti konzisztenciahoz ez kell.
SYMS = ["GOLD", "USDJPY", "UsaInd", "UsaTec", "Ger40"]


# ── Jellemzok ─────────────────────────────────────────────────────────────
def jellemzok(df: pd.DataFrame) -> dict:
    """A negy SMA, a tavolsagaik es a tagulas/szukules — MIND a t-edik barig.

    ⚠ NINCS ELORE-TEKINTES: minden `rolling`/`shift` visszafele nez. A projekt
    mar megjart egy M15 look-ahead hibat (a jel a sajat gyertyaja zarasat
    hasznalta), ezert itt a `lejto` is a MULTBELI ablakbol szamol."""
    c = df["close"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    ki = {"close": c}
    for n in PERIODUSOK:
        ki[f"sma{n}"] = lab.sma(c, n)
    ki["atr"] = lab.atr(h, l, c, ATR_ABLAK)

    # ⚠ ATR-BEN MERUNK, NEM PONTBAN. Egy 30 pontos GOLD-tavolsag es egy 30
    # pontos USDJPY-tavolsag semmit nem mond egymasrol; az instrumentum
    # koltseg-sorrendje (`instrument-cost-ranking`) 22x szorast mutatott.
    _atr = np.where(ki["atr"] > 0, ki["atr"], np.nan)
    for a, b in ((8, 21), (21, 100), (100, 250), (21, 250), (8, 250)):
        d = (ki[f"sma{a}"] - ki[f"sma{b}"]) / _atr
        ki[f"d{a}_{b}"] = d                      # elojeles: + = a gyorsabb feljebb
        ki[f"t{a}_{b}"] = np.abs(d)              # TAVOLSAG (elojel nelkul)
    # Tagulas/szukules: a tavolsag valtozasa az ablakon.
    for kulcs in ("t100_250", "t21_250", "t21_100", "t8_21"):
        v = ki[kulcs]
        ki["lejto_" + kulcs] = v - _shift(v, LEJTO_ABLAK)
    # ── A NEGY SMA SAJAT LEJTESE (a felhasznalo kerese, 2026-09-02:
    # "rakjuk meg hozza az egyes sma vonalak iranyat, mennyire mutatnak felfele
    # vagy lefele"). Ez MAS informacio, mint a tavolsag: ket atlag lehet allando
    # tavolsagra ugy is, hogy MINDKETTO emelkedik, es ugy is, hogy mindketto esik.
    #
    # ⚠ ATR-BEN, ES BARRA VETITVE. A nyers kulonbseg egy 250-es atlagon
    # definicio szerint kisebb, mint egy 8-ason — ha nem osztunk az ablakkal es
    # az ATR-rel, akkor a "meredekseg" valojaban azt merne, melyik atlag
    # gyorsabb. Igy viszont a negy szam OSSZEHASONLITHATO egymassal.
    for n in PERIODUSOK:
        v = ki[f"sma{n}"]
        ki[f"lejto{n}"] = (v - _shift(v, LEJTO_ABLAK)) / (_atr * LEJTO_ABLAK)

    # A TREND IRANYA a ket nagy atlagbol (a felhasznalo "ket nagy trendvonala").
    ki["trend"] = np.sign(ki["d100_250"])

    # EGYETERTES: hany SMA lejt a trend iranyaba (0..4). A "szalag rendezett"
    # allapot szamszeru merteke.
    egyet = np.zeros_like(ki["trend"])
    for n in PERIODUSOK:
        egyet = egyet + (np.sign(ki[f"lejto{n}"]) == ki["trend"]).astype(float)
    egyet[~np.isfinite(ki["lejto250"])] = np.nan
    ki["egyetertes"] = egyet
    return ki


def _shift(a, n: int):
    ki = np.full_like(a, np.nan, dtype=float)
    if n < len(a):
        ki[n:] = a[:-n]
    return ki


def _elore(a, n: int):
    """A JOVOBELI ertek — CSAK a cimkehez (elore-tekintes), sosem jellemzohoz."""
    ki = np.full_like(a, np.nan, dtype=float)
    if n < len(a):
        ki[:-n] = a[n:]
    return ki


def _t_stat(x) -> float:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 30 or x.std(ddof=1) == 0:
        return 0.0
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x))))


# ── A) LEIRO: tavolodo vs kozelito 100-250 ────────────────────────────────
def resz_a(sym: str, j: dict, ev: np.ndarray) -> list:
    """A trend iranyaba mert jovobeli hozam (ATR-ben), tavolodo vs kozelito
    100-250 mellett — es az ALAPRATA (feltetel nelkuli atlag).

    ⚠ AZ ALAPRATA NELKUL ez a meres ertelmezhetetlen. Ha a "tavolodo" allapotban
    +0,05 ATR a hozam, az csak akkor jelent valamit, ha a feltetel nelkuli atlag
    ennel kisebb. Enelkul a szam a piaci sodrodast merne (`drift-equals-financing`
    ott bukott meg, hogy a long brutto ele pontosan a swap volt)."""
    sorok = []
    trend = j["trend"]
    lejto = j["lejto_t100_250"]
    ervenyes = np.isfinite(trend) & np.isfinite(lejto) & (trend != 0)
    for h in HORIZONTOK:
        # A trend IRANYABA mert hozam ATR-ben.
        jov = (_elore(j["close"], h) - j["close"]) / np.where(j["atr"] > 0, j["atr"], np.nan)
        r = jov * trend
        ok = ervenyes & np.isfinite(r)
        tav = ok & (lejto > 0)                    # a ket nagy atlag TAVOLODIK
        koz = ok & (lejto < 0)                    # KOZELIT
        sorok.append({
            "sym": sym, "h": h,
            "alap": float(np.nanmean(r[ok])), "alap_n": int(ok.sum()),
            "tavolodo": float(np.nanmean(r[tav])), "tav_n": int(tav.sum()),
            "tav_t": _t_stat(r[tav] - np.nanmean(r[ok])),
            "kozelito": float(np.nanmean(r[koz])), "koz_n": int(koz.sum()),
            "koz_t": _t_stat(r[koz] - np.nanmean(r[ok])),
        })
    return sorok


# ── B) FORDULO: elorejelzi-e a 21-250 kozelitese? ─────────────────────────
def resz_b(sym: str, j: dict) -> list:
    """P(a trend valt n percen belul | 21-250 kozelit) vs az ALAPRATA.

    A "trend valt": a `sign(sma100 - sma250)` elojelet valt a kovetkezo n barban.

    ⚠ EZ A MERES A FELHASZNALO HIPOTEZISENEK KOZVETLEN PROBAJA: "ha 21-250
    kozelit, valtozni fog". Ha a felteteles valoszinuseg nem nagyobb az
    alapratanal, akkor a jelzes nem hordoz informaciot — barmilyen meggyozo is
    a charton visszanezve (`retrospective-label-trap`)."""
    sorok = []
    trend = j["trend"]
    koz21 = j["lejto_t21_250"] < 0                     # 21-250 KOZELIT
    tav21 = j["lejto_t21_250"] > 0
    # Kuszob-valtozat: nem eleg, hogy kozelit — LEGYEN IS kozel.
    kozel_es_szuk = koz21 & (j["t21_250"] < 0.5)
    for n in (60, 120, 240, 480):
        jov_trend = _elore(trend, n)
        valt = np.isfinite(trend) & np.isfinite(jov_trend) & (trend != 0) & \
            (jov_trend != 0) & (jov_trend != trend)
        ok = np.isfinite(trend) & np.isfinite(jov_trend) & (trend != 0) & (jov_trend != 0)
        def _p(maszk):
            m = ok & maszk
            return (float(valt[m].mean()) if m.sum() else float("nan"), int(m.sum()))
        alap = float(valt[ok].mean())
        p_koz, n_koz = _p(koz21)
        p_tav, n_tav = _p(tav21)
        p_szuk, n_szuk = _p(kozel_es_szuk)
        sorok.append({"sym": sym, "n": n, "alap": alap,
                      "kozelit": p_koz, "koz_n": n_koz,
                      "tavolodik": p_tav, "tav_n": n_tav,
                      "kozel_szuk": p_szuk, "szuk_n": n_szuk})
    return sorok


# ── E) LEIRO: a NEGY SMA LEJTESE ──────────────────────────────────────────
def resz_e(sym: str, j: dict) -> list:
    """A trend iranyaba mert jovobeli hozam az EGYETERTES szerint (hany SMA lejt
    a trend iranyaba, 0..4) — es kulon a leggyorsabb/leglassabb lejtese szerint.

    ⚠ A KERDES: hozzatesz-e a LEJTES ahhoz, amit a TAVOLSAG mar elmondott? Ket
    atlag lehet allando tavolsagra ugy is, hogy mindketto emelkedik, es ugy is,
    hogy mindketto esik — a tavolsag ezt nem kulonbozteti meg, a lejtes igen."""
    trend = j["trend"]
    atr = np.where(j["atr"] > 0, j["atr"], np.nan)
    sorok = []
    for h in (60, 240):
        r = ((_elore(j["close"], h) - j["close"]) / atr) * trend
        ok = np.isfinite(r) & np.isfinite(j["egyetertes"]) & (trend != 0)
        alap = float(np.nanmean(r[ok]))
        sor = {"sym": sym, "h": h, "alap": alap}
        for k in range(5):
            m = ok & (j["egyetertes"] == k)
            sor[f"e{k}"] = float(np.nanmean(r[m])) if m.sum() > 100 else float("nan")
            sor[f"n{k}"] = int(m.sum())
        # ⚠ A LEGGYORSABB SMA LEJTESE KULON: ez fordul elobb, tehat ha a lejtes
        # egyaltalan elorejelez, itt kell latszania.
        _f = np.sign(j["lejto8"]) == trend
        sor["sma8_egyezik"] = float(np.nanmean(r[ok & _f]))
        sor["sma8_ellen"] = float(np.nanmean(r[ok & ~_f]))
        sor["t8"] = _t_stat(r[ok & ~_f] - alap)
        sorok.append(sor)
    return sorok


# ── F) MIND A HAT KERESZTEZODES, MINDKET IRANYBAN ─────────────────────────
# A felhasznalo kerese (2026-09-02): "nezzuk meg, mi tortenik, ha keresztezi
# A-B A-C A-D B-C B-D C-D egymast. es persze azt, hogy lentrol fol vagy fentrol
# le". A = SMA8, B = SMA21, C = SMA100, D = SMA250.
BETU = {8: "A", 21: "B", 100: "C", 250: "D"}
PAROK = ((8, 21), (8, 100), (8, 250), (21, 100), (21, 250), (100, 250))


def keresztezesek(j: dict) -> dict:
    """A 12 esemeny: `{"A-B fel": maszk, "A-B le": maszk, ...}`.

    "Fel" = a GYORSABB atlag alulrol keresztezi a lassabbat. A par sorrendje
    mindig (gyorsabb, lassabb), tehat a `d = sma_gyors - sma_lassu` elojelvaltasa
    egyertelmuen iranyt jelent."""
    ki = {}
    for a, b in PAROK:
        d = j[f"sma{a}"] - j[f"sma{b}"]
        e = _shift(d, 1)
        nev = f"{BETU[a]}-{BETU[b]}"
        ki[nev + " fel"] = np.isfinite(e) & (e <= 0) & (d > 0)
        ki[nev + " le"] = np.isfinite(e) & (e >= 0) & (d < 0)
    return ki


def resz_f(sym: str, j: dict) -> list:
    """Mit ER egy keresztezodes? A KERESZTEZODES IRANYABA mert jovobeli hozam
    (ATR-ben), az ALAPRATAHOZ (a feltetel nelkuli sodrodashoz) merve.

    ⚠ AZ ALAPRATA ITT NEM NULLA. A piac hosszu tavon sodrodik (a long brutto ele
    a `drift-equals-financing` szerint pontosan a swap), tehat egy "fel"
    keresztezodes utani pozitiv hozam onmagaban semmit nem bizonyit — a
    kulonbseget kell nezni. Ezert szerepel minden sorban az `alap` es a `t`
    (a felteteles ATLAG es az alaprata kulonbsegenek t-ertéke)."""
    atr = np.where(j["atr"] > 0, j["atr"], np.nan)
    ki = keresztezesek(j)
    sorok = []
    for h in (30, 60, 240):
        fwd = (_elore(j["close"], h) - j["close"]) / atr
        ok = np.isfinite(fwd)
        alap = float(np.nanmean(fwd[ok]))
        for nev, m in ki.items():
            mm = ok & m
            if mm.sum() < 200:
                continue
            # "le" keresztezodesnel a VART irany lefele -> az elojelet forditjuk,
            # hogy minden sor "a keresztezodes iranyaba mert hozam" legyen.
            jel = 1.0 if nev.endswith("fel") else -1.0
            r = fwd[mm] * jel
            sorok.append({"sym": sym, "h": h, "esemeny": nev, "n": int(mm.sum()),
                          "hozam": float(np.nanmean(r)),
                          "alap": alap * jel,
                          "tobblet": float(np.nanmean(r)) - alap * jel,
                          "t": _t_stat(r - alap * jel)})
    return sorok


# ── C) BELEPO: a legkorabbi fordulo-jel, KOLTSEGGEL ───────────────────────
def belepok(j: dict) -> dict:
    """Fordulo-jelolt belepok. Mind a "legkorabbi" elv szerint: a GYORS atlag
    fordul elobb, a lassu csak megerositi.

    ⚠ A "legkorabban elcsipni" ara a TEVES RIASZTAS. Minel korabbi a jel, annal
    tobbszor lesz csak zaj — ezert kell mind a negy valtozatot ugyanazzal a
    mercevel megmerni, nem a charton kivalasztani a szepet."""
    d8_21 = j["d8_21"]
    d21_100 = j["d21_100"]
    trend = j["trend"]
    koz = j["lejto_t21_250"] < 0
    elozo8 = _shift(d8_21, 1)
    elozo21 = _shift(d21_100, 1)

    ki = {}
    # 1. A leggyorsabb par fordul a TREND ELLEN (a legkorabbi jel).
    ki["8x21_trend_ellen"] = (
        ((elozo8 <= 0) & (d8_21 > 0) & (trend < 0)) * 1 +
        ((elozo8 >= 0) & (d8_21 < 0) & (trend > 0)) * -1)
    # 2. Ugyanaz, de CSAK ha a 21-250 kozelit (a felhasznalo szurofeltetele).
    _sz = ki["8x21_trend_ellen"].copy()
    _sz[~koz] = 0
    ki["8x21_trend_ellen_ha_kozelit"] = _sz
    # 3. A kozepso par fordul (kesobbi, de megbizhatobbnak "erzett" jel).
    ki["21x100_trend_ellen"] = (
        ((elozo21 <= 0) & (d21_100 > 0) & (trend < 0)) * 1 +
        ((elozo21 >= 0) & (d21_100 < 0) & (trend > 0)) * -1)
    # 4. KONTROLL: a trend IRANYABA tuzelo 8x21 — ha ez ugyanolyan jo, akkor a
    #    "fordulo" nem magyaraz semmit, csak a kereszrezes gyakorisaga.
    ki["8x21_trend_iranyaba"] = (
        ((elozo8 <= 0) & (d8_21 > 0) & (trend > 0)) * 1 +
        ((elozo8 >= 0) & (d8_21 < 0) & (trend < 0)) * -1)

    # ── A LEJTESRE EPULO JELEK (a felhasznalo kerese) ─────────────────────
    l8, l21 = j["lejto8"], j["lejto21"]
    e8, e21 = _shift(l8, 1), _shift(l21, 1)
    egyet = j["egyetertes"]

    # 5. A LEGGYORSABB SMA LEJTESE FORDUL a trend ellen — a lehető legkorabbi
    #    jel, amit a lejtes adhat (elobb fordul, mint barmelyik kereszrezes).
    ki["lejto8_fordul_trend_ellen"] = (
        ((e8 <= 0) & (l8 > 0) & (trend < 0)) * 1 +
        ((e8 >= 0) & (l8 < 0) & (trend > 0)) * -1)
    # 6. Ugyanaz a 21-esen: kesobbi, de kevesebb teves riasztas varhato.
    ki["lejto21_fordul_trend_ellen"] = (
        ((e21 <= 0) & (l21 > 0) & (trend < 0)) * 1 +
        ((e21 >= 0) & (l21 < 0) & (trend > 0)) * -1)
    # 7. TELJES SZALAG-FORDULAS: a 8 lejtese fordul, ES mar csak legfeljebb egy
    #    SMA lejt a regi trend iranyaba (a szalag "szetesett").
    _sz = ki["lejto8_fordul_trend_ellen"].copy()
    _sz[~(egyet <= 1)] = 0
    ki["lejto8_fordul_szalag_szetesett"] = _sz
    # 8. KONTROLL a lejtesre: a trend IRANYABA fordulo lejtes + teljes egyetertes.
    #    Ha ez jobb, akkor megint nem a "fordulo" a lenyeg.
    ki["lejto8_trend_iranyaba_egyetertve"] = (
        (((e8 <= 0) & (l8 > 0) & (trend > 0)) * 1 +
         ((e8 >= 0) & (l8 < 0) & (trend < 0)) * -1) * (egyet >= 3))
    return ki


def belepok_kereszt(j: dict) -> dict:
    """A 12 keresztezodes BELEPOKENT: "fel" -> long, "le" -> short."""
    ki = {}
    for nev, m in keresztezesek(j).items():
        jel = np.zeros(len(m), dtype=float)
        jel[m] = 1.0 if nev.endswith("fel") else -1.0
        ki["X " + nev] = jel
    return ki


def resz_c(sym: str, df: pd.DataFrame, j: dict, sl_atr: float = 1.5,
           tp_rr: float = 0.0, max_hold: int = 480, kereszt: bool = False) -> list:
    """Szimulacio KOLTSEGGEL, kulon LONG es SHORT, evenkenti bontassal.

    ⚠ TP NELKUL (tp_rr=0) az alapertelmezes: a meres szerint a celar elhagyasa
    volt a legnagyobb egyetlen javulas (+0,031 R, `outcome-management-measured`).
    A `--tp` kapcsoloval visszakapcsolhato."""
    pc = lab.PAIRS.get(sym) or {}
    point = float(pc.get("point_size") or 0.0)
    if point <= 0:
        return []
    atr_pts = j["atr"] / point
    sorok = []
    _jelek = belepok_kereszt(j) if kereszt else belepok(j)
    for nev, jel in _jelek.items():
        idx = np.flatnonzero((jel != 0) & np.isfinite(atr_pts) & (atr_pts > 0))
        if len(idx) < 100:
            sorok.append({"sym": sym, "jel": nev, "n": len(idx), "ures": True})
            continue
        side = jel[idx].astype(int)
        slp = atr_pts[idx] * sl_atr
        tpp = slp * tp_rr if tp_rr > 0 else np.zeros(len(idx))
        tr = lab.simulate(df, idx, side, slp, tpp, point,
                          max_hold=max_hold,
                          spread_fallback_pts=float(pc.get("backtest_spread_points") or 1.5))
        if not len(tr):
            sorok.append({"sym": sym, "jel": nev, "n": 0, "ures": True})
            continue
        r = tr["r"]
        ev = pd.to_datetime(df.index[tr["i_open"]]).year
        evenkent = pd.Series(r).groupby(ev).mean()
        _long = tr["dir"] > 0
        sorok.append({
            "sym": sym, "jel": nev, "n": len(r),
            "r": float(r.mean()), "t": _t_stat(r),
            "long": float(r[_long].mean()) if _long.any() else float("nan"),
            "short": float(r[~_long].mean()) if (~_long).any() else float("nan"),
            "ev_poz": float((evenkent > 0).mean()), "evek": len(evenkent),
            "ures": False})
    return sorok


# ── D) KISZALLAS KOZELITESKOR ─────────────────────────────────────────────
def resz_d(sym: str, j: dict) -> list:
    """"A kozelitéskor mikor erdemes kiszallni?" — a trend iranyaba nyitott
    pozicio JOVOBELI hozama, miutan a 21-250 kozeliteni kezd.

    A kerdes ugy merheto, hogy MEGKERDEZZUK: a kozelites pillanatatol szamitva a
    kovetkezo n perc hozama a trend iranyaban POZITIV-e meg. Ha mar nem, akkor a
    kozelites tenyleg kiszallasi jel; ha igen, akkor korai."""
    trend = j["trend"]
    atr = np.where(j["atr"] > 0, j["atr"], np.nan)
    kezd = (j["lejto_t21_250"] < 0) & (_shift(j["lejto_t21_250"], 1) >= 0)
    sorok = []
    for h in (15, 30, 60, 120, 240, 480):
        r = ((_elore(j["close"], h) - j["close"]) / atr) * trend
        m = kezd & np.isfinite(r) & (trend != 0)
        alap_m = np.isfinite(r) & (trend != 0)
        sorok.append({"sym": sym, "h": h, "n": int(m.sum()),
                      "utana": float(np.nanmean(r[m])) if m.sum() else float("nan"),
                      "alap": float(np.nanmean(r[alap_m])),
                      "t": _t_stat(r[m] - np.nanmean(r[alap_m]))})
    return sorok


def _spread_nelkul(df: pd.DataFrame) -> pd.DataFrame:
    """A spread kinullazasa — CSAK diagnosztika.

    ⚠ EZ NEM KERESKEDHETO EREDMENY. A brutto szam azt mondja meg, hordoz-e a
    jel egyaltalan iranyt; a kulonbseg a nettotol a KOLTSEG. Osszekeverni a
    kettot a projekt egyik regi hibaja (`backtest-bidask-and-insample-inflation`:
    a portfolio shortjai ingyen kaptak a spreadet)."""
    d = df.copy()
    for oszlop in ("avg_spread", "close_spread"):
        if oszlop in d:
            d[oszlop] = 1e-12
    return d


# ── Futtatas ──────────────────────────────────────────────────────────────
def _tabla(cim: str, sorok: list, oszlopok: list) -> None:
    print()
    print(cim)
    print("-" * 100)
    print("  ".join(f"{c:>12}" if i else f"{c:<24}" for i, c in enumerate(oszlopok)))
    for s in sorok:
        cellak = []
        for i, c in enumerate(oszlopok):
            v = s.get(c, "")
            if isinstance(v, float):
                v = "—" if not np.isfinite(v) else f"{v:+.4f}"
            cellak.append(f"{v:>12}" if i else f"{str(v):<24}")
        print("  ".join(cellak))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbols", nargs="*", default=SYMS)
    ap.add_argument("--reszek", nargs="*", default=["A", "B", "C", "D", "E", "F"])
    ap.add_argument("--kereszt", action="store_true",
                    help="a C resz a 12 keresztezodest szimulalja (nem a fordulo-jeleket)")
    ap.add_argument("--tp", type=float, default=0.0, help="TP az R tobbszorosekent (0 = nincs)")
    ap.add_argument("--sl", type=float, default=1.5, help="stop az ATR tobbszorosekent")
    # ⚠ A BRUTTO A DONTO DIAGNOSZTIKA. Ha a jel bruttoban is nulla, akkor a
    # mintazat nem hordoz iranyt; ha bruttoban pozitiv, de nettoban nem, akkor a
    # KOLTSEG a korlat — ket teljesen kulonbozo tanulsag, es a kettot csak igy
    # lehet szetvalasztani (a README sajat eredmenye is igy all elo:
    # "nelkule a rendszer +0,064 (t=2,85) lenne").
    ap.add_argument("--brutto", action="store_true",
                    help="spread NELKUL (csak diagnosztika, nem kereskedheto)")
    a = ap.parse_args(argv)

    A, B, C, D, E, F = [], [], [], [], [], []
    for sym in a.symbols:
        try:
            df = lab.load_m1(sym)
        except Exception as ex:
            print(f"  {sym}: NINCS ADAT ({ex})")
            continue
        j = jellemzok(df)
        ev = df.index.year.to_numpy()
        print(f"  {sym}: {len(df):,} M1 bar  {df.index[0].date()}..{df.index[-1].date()}")
        if "A" in a.reszek:
            A += resz_a(sym, j, ev)
        if "B" in a.reszek:
            B += resz_b(sym, j)
        if "C" in a.reszek:
            _d = _spread_nelkul(df) if a.brutto else df
            C += resz_c(sym, _d, j, sl_atr=a.sl, tp_rr=a.tp, kereszt=a.kereszt)
        if "D" in a.reszek:
            D += resz_d(sym, j)
        if "E" in a.reszek:
            E += resz_e(sym, j)
        if "F" in a.reszek:
            F += resz_f(sym, j)

    if A:
        _tabla("A) A TREND IRANYABA MERT JOVOBELI HOZAM (ATR-ben) — 100-250",
               [{**x, "kulcs": f"{x['sym']} h={x['h']}"} for x in A],
               ["kulcs", "alap", "tavolodo", "tav_t", "kozelito", "koz_t"])
    if B:
        _tabla("B) P(trend valt n percen belul) — a 21-250 allapota szerint",
               [{**x, "kulcs": f"{x['sym']} n={x['n']}"} for x in B],
               ["kulcs", "alap", "kozelit", "tavolodik", "kozel_szuk"])
    if C:
        _tabla("C) BELEPO-SZIMULACIO KOLTSEGGEL (R/kotes)",
               [{**x, "kulcs": f"{x['sym']} {x['jel']}"} for x in C if not x.get("ures")],
               ["kulcs", "n", "r", "t", "long", "short", "ev_poz"])
    if F:
        for _h in (30, 60, 240):
            _tabla(f"F) A HAT KERESZTEZODES, MINDKET IRANYBAN — h={_h} perc "
                   f"(hozam a keresztezodes iranyaba, ATR-ben)",
                   [{**x, "kulcs": f"{x['sym']} {x['esemeny']}"} for x in F
                    if x["h"] == _h],
                   ["kulcs", "n", "hozam", "alap", "tobblet", "t"])
    if E:
        _tabla("E) A NEGY SMA LEJTESE: hozam az EGYETERTES szerint (0..4 SMA lejt a trendbe)",
               [{**x, "kulcs": f"{x['sym']} h={x['h']}"} for x in E],
               ["kulcs", "alap", "e0", "e1", "e2", "e3", "e4"])
        _tabla("E2) A LEGGYORSABB SMA (8) LEJTESE kulon",
               [{**x, "kulcs": f"{x['sym']} h={x['h']}"} for x in E],
               ["kulcs", "alap", "sma8_egyezik", "sma8_ellen", "t8"])
    if D:
        _tabla("D) KISZALLAS: a hozam a KOZELITES KEZDETE utan (ATR-ben)",
               [{**x, "kulcs": f"{x['sym']} h={x['h']}"} for x in D],
               ["kulcs", "n", "utana", "alap", "t"])
    return 0


if __name__ == "__main__":
    _sys.exit(main())

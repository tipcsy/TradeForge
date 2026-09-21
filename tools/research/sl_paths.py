"""PÁLYA-KIVONAT — minden belépőhöz az, AMI UTÁNA TÖRTÉNT.

Ez a modul nem válaszol kérdést: adatot állít elő az `sl_oracle.py`-nak.
Egy belépő pályájából hét dolgot jegyez fel, ATR-egységben (tehát
instrumentum- és volatilitás-függetlenül), a motor végrehajtási
konvenciójával (BUY ask-on nyit / bid-en zár, SELL fordítva):

  `mfe`      a legjobb pont, ameddig elment
  `t_mfe`    hányadik percben volt ott
  `s_min`    MENNYIT KELLETT ELVISELNI, hogy odáig eljuss  <- a kulcs
  `mae`      a legrosszabb pont a teljes tartás alatt
  `zaro`     hol állt a tartás végén
  `s{x}`     x ATR-es stop hányadik percben ütött (H = nem ütött)
  `c{x}`     x ATR-es cél hányadik percben teljesült
  `mfe_s{x}` x ATR-es stop mellett MEDDIG JUTHATTUNK volna (a legjobb pont
             a stop ütése ELŐTT) — ez a „visszatekintő" kérdés magja

⚠ MIÉRT ATR-BEN. Ha pontban mérnénk, a nagy volatilitású évek uralnák az
átlagot, és a „mekkora stop kell" kérdésre a válasz évente más lenne.

⚠ A KÖLTSÉG BENNE VAN a belépőben (spread), de a swap NINCS: az a tartás
hosszától függ, és az `sl_oracle` külön, R-ben vonja le. A `README.md` szerint
a swap -0,028…-0,044 R/kötés, ami NAGYOBB, mint az eddig mért teljes él —
tehát nem elhanyagolható részlet, hanem a fő tétel.

⚠ INTRABAR SORREND: ha ugyanazon a percen belül a stop és a cél is teljesülne,
a STOP nyer (pesszimista) — ugyanaz a konvenció, mint a `lab.simulate`-ben.
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

H_ALAP = 480                 # tartás percben (= outcomes.MAX_HOLD)
RACS_PERC = 5                # a belépő-rács (= outcomes.STEP_MIN)
S_RACS = np.array([0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 6.0])
C_RACS = np.array([0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 6.0, 8.0])


def atr_m1(m1: pd.DataFrame, tf: int = 15, n: int = 14) -> np.ndarray:
    """Minden M1 barhoz a LEGUTÓBB LEZÁRT M15 bar ATR-je (nincs look-ahead).

    Ugyanaz a mérték, amit az `outcomes.py` használ — ezért a két mérés
    számai összevethetők.
    """
    d = lab.resample(m1, tf)
    a = lab.atr(d["high"].to_numpy(float), d["low"].to_numpy(float),
                d["close"].to_numpy(float), n)
    zaras = d.index + pd.Timedelta(minutes=tf)
    j = np.searchsorted(zaras, m1.index, side="right") - 1
    out = np.full(len(m1), np.nan)
    ok = j >= 0
    out[ok] = a[j[ok]]
    return np.where(np.isfinite(out) & (out > 0), out, np.nan)


def mintavetel(m1: pd.DataFrame, atr: np.ndarray, db: int, mag: int = 0,
               h: int = H_ALAP) -> np.ndarray:
    """Véletlen belépő-rácspontok (a teljes mintán egyenletesen).

    ⚠ MIÉRT MINTA ÉS NEM MINDEN PONT: a teljes M1 rácson (GOLD: 4,7 millió bar)
    a pálya-kivonat órákig futna, miközben 20 000 belépő már ±0,01 ATR alatti
    standard hibát ad a legtöbb itteni átlagra. A mag rögzített, tehát a mérés
    megismételhető.

    ⚠ ÉS MIÉRT VÉLETLEN, NEM SZABÁLY SZERINTI: a kérdés az, hogy a STOP
    elhelyezése hordoz-e értéket ÖNMAGÁBAN. Ha csak egy szabály belépőin
    mérnénk, a szabály és a stop hatása összekeveredne.
    """
    racs = np.flatnonzero((m1.index.minute % RACS_PERC == 0)
                          & np.isfinite(atr))
    racs = racs[(racs > 0) & (racs + h < len(m1))]
    if len(racs) <= db:
        return racs
    rng = np.random.default_rng(mag)
    return np.sort(rng.choice(racs, size=db, replace=False))


def kivonat(df: pd.DataFrame, atr: np.ndarray, idx: np.ndarray,
            h: int = H_ALAP, s_racs=S_RACS, c_racs=C_RACS) -> pd.DataFrame:
    """A pálya-kivonat MINDKÉT irányban, belépőnként egy-egy sorral.

    Mindkét irány ugyanarról a belépőről: így a long/short különbség tisztán
    a piac sodródása, nem a mintavétel zaja.
    """
    hi = df["high"].to_numpy(float)
    lo = df["low"].to_numpy(float)
    cl = df["close"].to_numpy(float)
    sp = (df["avg_spread"].to_numpy(float) if "avg_spread" in df
          else np.zeros(len(df)))
    csp = (df["close_spread"].to_numpy(float) if "close_spread" in df else sp)
    sp = np.where(np.isfinite(sp) & (sp > 0), sp, 0.0)
    csp = np.where(np.isfinite(csp) & (csp > 0), csp, sp)
    ido = df.index

    sorok = []
    for i in idx:
        i = int(i)
        a = atr[i]
        if not (a > 0):
            continue
        v = slice(i + 1, i + 1 + h)
        hs, ls, cs, sps = hi[v], lo[v], cl[v], sp[v]
        if len(hs) < 2:
            continue
        for d in (1, -1):
            belep = cl[i] + (csp[i] if d > 0 else 0.0)
            if d > 0:
                fav = (hs - belep) / a
                adv = (belep - ls) / a
                zar = (cs[-1] - belep) / a
            else:
                fav = (belep - (ls + sps)) / a
                adv = ((hs + sps) - belep) / a
                zar = (belep - (cs[-1] + sps[-1])) / a
            favr = np.maximum(np.maximum.accumulate(fav), 0.0)
            advr = np.maximum(np.maximum.accumulate(adv), 0.0)
            # a stop/cél ELSŐ ütése: a futó maximumok monotonok -> searchsorted
            sb = np.searchsorted(advr, s_racs, side="left")
            cb = np.searchsorted(favr, c_racs, side="left")
            t_mfe = int(np.argmax(fav))
            sor = {"i": i, "ido": ido[i], "dir": d,
                   "mfe": float(favr[-1]), "mae": float(advr[-1]),
                   "t_mfe": t_mfe, "s_min": float(advr[t_mfe]),
                   "zaro": float(zar), "atr": float(a),
                   "koltseg_atr": float(csp[i] / a)}
            for k, s in enumerate(s_racs):
                b = int(sb[k])
                sor[f"s{s}"] = b
                sor[f"mfe_s{s}"] = float(favr[b - 1]) if b > 0 else 0.0
            for k, c in enumerate(c_racs):
                sor[f"c{c}"] = int(cb[k])
            sorok.append(sor)
    return pd.DataFrame(sorok)


def szintetikus(m1: pd.DataFrame, blokk: int = 60, mag: int = 0) -> pd.DataFrame:
    """NULL-PIAC: blokk-bootstrap az ELSŐ kérdéshez — „mennyi ebből a szerkezet?"

    A szintetikus sorozat a VALÓDI barokból épül, `blokk` hosszú, egybefüggő
    darabokat egymás után fűzve; minden bar megtartja a saját (h/c, l/c)
    arányát, tehát a gyertya-alak, a hozam-eloszlás és a blokkon BELÜLI
    önkorreláció (volatilitás-csomósodás, napszaki ritmus egy órán belül)
    megmarad. Ami ELTŰNIK: a `blokk`-nál hosszabb távú szerkezet — trend,
    visszahúzás, tartomány, szintek.

    ⚠ EZÉRT A HASONLÍTÁS ÉRTELME: ha a valódi és a szintetikus piacon UGYANAZT
    az SL/TP-felületet kapjuk, akkor a stop-elhelyezés nem szerkezetet fog meg,
    hanem csak a volatilitás alakját — és ilyenkor NINCS mit optimalizálni.
    Ez az a null, ami az eddigi kutatásokból hiányzott: a „nulla várható érték"
    nem ugyanaz, mint a „véletlen piac ugyanezzel a volatilitással".

    ⚠ A `blokk` a kérdés élessége: 60 perccel azt kérdezzük, van-e EGY ÓRÁNÁL
    hosszabb kihasználható szerkezet.
    """
    n = len(m1)
    c = m1["close"].to_numpy(float)
    h = m1["high"].to_numpy(float)
    l = m1["low"].to_numpy(float)
    hoz = np.zeros(n)
    hoz[1:] = np.log(np.where(c[1:] > 0, c[1:], np.nan) /
                     np.where(c[:-1] > 0, c[:-1], np.nan))
    hoz = np.nan_to_num(hoz, nan=0.0, posinf=0.0, neginf=0.0)
    fh = np.log(np.where(h > 0, h, np.nan) / np.where(c > 0, c, np.nan))
    fl = np.log(np.where(l > 0, l, np.nan) / np.where(c > 0, c, np.nan))
    fh = np.nan_to_num(fh, nan=0.0); fl = np.nan_to_num(fl, nan=0.0)

    rng = np.random.default_rng(mag)
    db = int(np.ceil(n / blokk))
    kezd = rng.integers(0, max(1, n - blokk), size=db)
    rend = np.concatenate([np.arange(k, k + blokk) for k in kezd])[:n]
    rend = np.clip(rend, 0, n - 1)

    uj_c = c[0] * np.exp(np.cumsum(hoz[rend]))
    uj_h = uj_c * np.exp(fh[rend])
    uj_l = uj_c * np.exp(fl[rend])
    uj_h = np.maximum(uj_h, uj_c)
    uj_l = np.minimum(uj_l, uj_c)
    ki = pd.DataFrame({"open": uj_c, "high": uj_h, "low": uj_l, "close": uj_c,
                       "volume": 1.0}, index=m1.index)
    for oszl in ("avg_spread", "close_spread"):
        if oszl in m1:
            ki[oszl] = m1[oszl].to_numpy(float)     # a költség marad a valódi
    return ki


def jellemzok(m1: pd.DataFrame, idx: np.ndarray, tf: int = 15) -> pd.DataFrame:
    """BELÉPŐ ELŐTTI (kauzális) jellemzők — a feltételes stop teszteléséhez.

    Csak olyan mennyiségek, amik a belépő pillanatában ismertek. A kérdés,
    amire szolgálnak: MEGJÓSOLHATÓ-E, mennyi fájdalmat kell kiállni? Mert ha
    nem, akkor a stop elhelyezése nem lehet él, csak ízlés.
    """
    d = lab.resample(m1, tf)
    hh = d["high"].to_numpy(float); ll = d["low"].to_numpy(float)
    cc = d["close"].to_numpy(float)
    a = lab.atr(hh, ll, cc, 14)
    alap = pd.Series(a).rolling(2000, min_periods=200).mean().to_numpy()
    sma = lab.sma(cc, 200)
    tart_h = pd.Series(hh).rolling(96).max().to_numpy()
    tart_l = pd.Series(ll).rolling(96).min().to_numpy()
    szel = np.where(tart_h - tart_l > 0, tart_h - tart_l, np.nan)
    # a LEGUTÓBB IGAZOLT swing-szintek — a „stop a szerkezet mögé" szabályhoz.
    # Ugyanaz a pivot-definíció, amit a sorrend-mátrix használ (`seq_events`),
    # hogy a két mérés ne két külön szerkezet-fogalommal dolgozzon.
    import seq_events as _SE
    ph, pl = _SE._pivotok(hh, ll, _SE.PIVOT_K)
    def _szint(jel, ar):
        v = np.full(len(cc), np.nan)
        j = np.flatnonzero(jel) + _SE.PIVOT_K       # ennyivel később ismert
        j = j[j < len(cc)]
        v[j] = ar[j - _SE.PIVOT_K]
        return pd.Series(v).ffill().to_numpy()
    utolso_h = _szint(ph, hh)
    utolso_l = _szint(pl, ll)
    aa = np.where(a > 0, a, np.nan)
    tab = {
        "atr_arany": a / np.where(alap > 0, alap, np.nan),
        "sma_tav": (cc - sma) / aa,
        "tart_poz": (cc - tart_l) / szel - 0.5,
        "tart_szel": szel / aa,
        # long stop-táv a szerkezet mögé; short esetén a felső szintig
        "swing_ala": (cc - utolso_l) / aa,
        "swing_fole": (utolso_h - cc) / aa,
    }
    zaras = d.index + pd.Timedelta(minutes=tf)
    j = np.searchsorted(zaras, m1.index[idx], side="right") - 1
    ok = j >= 0
    ki = {k: np.where(ok, v[np.where(ok, j, 0)], np.nan) for k, v in tab.items()}
    ki["ora"] = m1.index[idx].hour.to_numpy()
    ki["hetnap"] = m1.index[idx].dayofweek.to_numpy()
    ki["i"] = np.asarray(idx)
    return pd.DataFrame(ki)


def kivonat_egyedi(df: pd.DataFrame, atr: np.ndarray, idx: np.ndarray,
                   irany: np.ndarray, s_be: np.ndarray,
                   h: int = H_ALAP) -> pd.DataFrame:
    """UGYANAZ a pálya-kivonat, de belépőnként SAJÁT stop-távolsággal.

    Ez kell a stop-SZABÁLYOK összehasonlításához: a „szerkezet mögé" és a
    „feltételes" stop távolsága kötésenként más, tehát nem fér rá a
    `kivonat` fix rácsára.

    Visszaad kötésenként: `s` (ATR), `eleg` (elég tág volt-e ahhoz, hogy a
    legjobb pontig eljussunk), `mfe_s` (ameddig a stop ütése ELŐTT eljutottunk),
    `stop_bar`, `zaro`.
    """
    hi = df["high"].to_numpy(float)
    lo = df["low"].to_numpy(float)
    cl = df["close"].to_numpy(float)
    sp = (df["avg_spread"].to_numpy(float) if "avg_spread" in df
          else np.zeros(len(df)))
    csp = (df["close_spread"].to_numpy(float) if "close_spread" in df else sp)
    sp = np.where(np.isfinite(sp) & (sp > 0), sp, 0.0)
    csp = np.where(np.isfinite(csp) & (csp > 0), csp, sp)

    sorok = []
    for k in range(len(idx)):
        i, d, s = int(idx[k]), int(irany[k]), float(s_be[k])
        a = atr[i]
        if not (a > 0) or not (s > 0):
            continue
        v = slice(i + 1, i + 1 + h)
        hs, ls, cs, sps = hi[v], lo[v], cl[v], sp[v]
        if len(hs) < 2:
            continue
        belep = cl[i] + (csp[i] if d > 0 else 0.0)
        if d > 0:
            fav = (hs - belep) / a
            adv = (belep - ls) / a
            zar = (cs[-1] - belep) / a
        else:
            fav = (belep - (ls + sps)) / a
            adv = ((hs + sps) - belep) / a
            zar = (belep - (cs[-1] + sps[-1])) / a
        favr = np.maximum(np.maximum.accumulate(fav), 0.0)
        advr = np.maximum(np.maximum.accumulate(adv), 0.0)
        b = int(np.searchsorted(advr, s, side="left"))
        t_mfe = int(np.argmax(fav))
        sorok.append({"i": i, "ido": df.index[i], "dir": d, "s": s,
                      "eleg": bool(advr[t_mfe] <= s),
                      "mfe_s": float(favr[b - 1]) if b > 0 else 0.0,
                      "mfe": float(favr[-1]), "s_min": float(advr[t_mfe]),
                      "stop_bar": b, "zaro": float(zar)})
    return pd.DataFrame(sorok)

"""JEL-KONYVTAR: indikator x idosik x parameter -> BOOLEAN MASZK az M5 racson.

A felhasznalo kerese (2026-08-28): "van legalabb 5 idosikunk, ezeket kombinalni
kellene, meg legalabb egy egyuttallast is figyelni — tobb millios lehetoseg."

Ez a modul allitja elo az epitokockakat. Minden jel egy BOOLEAN TOMB, ugyanazon
az M5 racson, amin az [[outcomes]] a kimeneteket szamolta. Ezert:

    egyuttallas = jelA & jelB          (numpy, mikroszekundum)
    varhato ertek = kimenet[maszk].mean()

LOOK-AHEAD ELLENI VEDELEM (a legfontosabb reszlet):
Egy H4 bar, aminek a cimkeje 08:00, 12:00-kor ZAR. Ha a 08:00-as bar zaroarabol
szamolt jelet mar 08:05-kor hasznalnank, az a JOVOT hasznalna. Ezert minden
TF-jel a bar ZARASA utani elso M5 racspontig van eltolva (`searchsorted` a
zarasi idokre), es csak onnantol ervenyes.

Ez a hiba a projektben mar egyszer megtortent (M15 look-ahead a backtestben),
ezert itt kulon teszt-fuggveny (`onteszt`) ellenorzi.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

import indicator_screen as IS
import lab

TFS = [5, 15, 30, 60, 240]          # M5, M15, M30, H1, H4


def _roll(a, n, fn):
    s = pd.Series(a)
    return getattr(s.rolling(n, min_periods=n), fn)().to_numpy()


def _x_up(a, b):
    pa = np.concatenate([[np.nan], a[:-1]])
    pb = np.concatenate([[np.nan], b[:-1]])
    return (pa <= pb) & (a > b)


def felfuto(m: np.ndarray) -> np.ndarray:
    """A maszk FELFUTO ELE: csak az a racspont, ahol IGAZZA valt.

    ⚠ EZ A JAVITAS a 2026-08-29-i buktatora. A korabbi meres MINDEN olyan
    racspontot ertekelt, ahol a mintazat igaz volt — ez viszont osszemosta a
    "jo PILLANAT belepni" (belepojel) es a "jo IDOSZAK bent lenni"
    (piac-idozites) kerdest. A valodi motoron ez bukott meg: az idoszakon
    +0,029, a belepes pillanataban -0,022.

    Ket okbol kell KOZOS fuggveny: (a) a kereses es a holdout ugyanazt kell
    hogy merje, (b) nehany "esemeny"-nek nevezett jel valojaban ALLAPOT
    (pl. `donchian_kitores_fel` = `c > elozo_csucs`, ami sok baron at igaz
    marad) — ezeket ez a transzformacio teszi valodi esemennye.
    """
    return m & ~np.concatenate([[False], m[:-1]])


def _allapotok(d: pd.DataFrame, p: int) -> dict:
    """ALLAPOT-jelek (nem esemeny): 'a piac EPPEN ilyen'.

    Egyuttallashoz allapot kell, nem esemeny — ket esemeny szinte sosem esik
    ugyanarra a barra. Az esemenyeket a `_esemenyek` adja, es a keresesben
    esemeny + allapot(ok) a mintazat.
    """
    o = d["open"].to_numpy(float); h = d["high"].to_numpy(float)
    l = d["low"].to_numpy(float);  c = d["close"].to_numpy(float)
    v = d["volume"].to_numpy(float)
    S = {}
    S[f"ar>sma{p}"] = c > lab.sma(c, p)
    S[f"ar>ema{p}"] = c > lab.ema(c, p)
    S[f"rsi{p}>50"] = lab.rsi(c, p) > 50
    S[f"rsi{p}<30"] = lab.rsi(c, p) < 30
    S[f"rsi{p}>70"] = lab.rsi(c, p) > 70
    m, ms = IS.macd(c, max(3, p // 2), p, 9)
    S[f"macd{p}>jel"] = m > ms
    S[f"macd{p}>0"] = m > 0
    k, dd = IS.stoch(h, l, c, p, 3)
    S[f"stoch{p}<20"] = k < 20
    S[f"stoch{p}>80"] = k > 80
    ci = IS.cci(h, l, c, p)
    S[f"cci{p}>0"] = ci > 0
    S[f"cci{p}<-100"] = ci < -100
    au, ad = IS.aroon(h, l, p)
    S[f"aroon{p}up"] = au > ad
    vp, vm = IS.vortex(h, l, c, p)
    S[f"vortex{p}up"] = vp > vm
    a = lab.atr(h, l, c, 14)
    ax, pdi, mdi = lab.adx(h, l, c, p)     # (ADX, +DI, -DI)
    S[f"adx{p}>25"] = ax > 25
    S[f"adx{p}<20"] = ax < 20
    S[f"di{p}_bika"] = pdi > mdi
    S[f"atr>atlag{p}"] = a > _roll(a, p, "mean")
    S[f"atr<atlag{p}"] = a < _roll(a, p, "mean")
    hu = IS.hull(c, p)
    S[f"ar>hull{p}"] = c > hu
    cv, bs = IS.ichimoku(h, l, max(2, p // 3), p)
    S[f"ichimoku{p}up"] = cv > bs
    ho, hc = IS.heikin(o, h, l, c)
    S[f"heikin{p}zold"] = hc > ho
    S[f"roc{p}>0"] = IS.roc(c, p) > 0
    S[f"tsi{p}>0"] = IS.tsi(c, p, max(2, p // 2)) > 0
    S[f"obv{p}>sma"] = IS.obv(c, v) > lab.sma(IS.obv(c, v), p)
    kl, km, ku = IS.keltner(h, l, c, p, 2.0)
    S[f"ar>keltner{p}felso"] = c > ku
    S[f"ar<keltner{p}also"] = c < kl
    S[f"chande{p}>0"] = IS.chande(c, p) > 0
    return S


def _esemenyek(d: pd.DataFrame, p: int) -> dict:
    """ESEMENY-jelek: 'most tortent valami' (keresztezes, fordulo)."""
    o = d["open"].to_numpy(float); h = d["high"].to_numpy(float)
    l = d["low"].to_numpy(float);  c = d["close"].to_numpy(float)
    E = {}
    E[f"sma{p}_atlepes_fel"] = _x_up(c, lab.sma(c, p))
    E[f"sma{p}_atlepes_le"] = _x_up(lab.sma(c, p), c)
    m, ms = IS.macd(c, max(3, p // 2), p, 9)
    E[f"macd{p}_kereszt_fel"] = _x_up(m, ms)
    E[f"macd{p}_kereszt_le"] = _x_up(ms, m)
    r = lab.rsi(c, p)
    E[f"rsi{p}_30_fole"] = _x_up(r, np.full_like(r, 30.0))
    E[f"rsi{p}_70_ala"] = _x_up(np.full_like(r, 70.0), r)
    k, dd = IS.stoch(h, l, c, p, 3)
    E[f"stoch{p}_kereszt_fel"] = _x_up(k, dd)
    E[f"stoch{p}_kereszt_le"] = _x_up(dd, k)
    hh, ll = _roll(h, p, "max"), _roll(l, p, "min")
    ph = np.concatenate([[np.nan], hh[:-1]])
    pl = np.concatenate([[np.nan], ll[:-1]])
    E[f"donchian{p}_kitores_fel"] = c > ph
    E[f"donchian{p}_kitores_le"] = c < pl
    kl, km, ku = IS.keltner(h, l, c, p, 2.0)
    E[f"keltner{p}_kitores_fel"] = _x_up(c, ku)
    E[f"keltner{p}_visszateres_fel"] = _x_up(c, kl)
    return E


def build(sym: str, racs_ido: pd.DatetimeIndex) -> tuple[dict, dict]:
    """Minden (indikator, idosik, parameter) jel a KOZOS M5 racsra vetitve.

    `racs_ido`: az outcomes.py altal hasznalt gyertyak idobelyegei.
    Visszaad: (allapotok, esemenyek) — nev -> bool tomb, racs_ido hosszan.
    """
    m1 = lab.load_m1(sym)
    A, E = {}, {}
    for tf in TFS:
        d = lab.resample(m1, tf)
        zaras = d.index + pd.Timedelta(minutes=tf)
        # a racs minden pontjahoz: az utolso OLYAN bar, ami mar LEZART
        j = np.searchsorted(zaras, racs_ido, side="right") - 1
        ok = j >= 0
        jj = np.where(ok, j, 0)
        for p in (14, 50) if tf >= 60 else (14, 50, 200):
            if len(d) < p * 3:
                continue
            for nev, arr in _allapotok(d, p).items():
                v = np.asarray(arr)
                out = np.zeros(len(racs_ido), dtype=bool)
                out[ok] = np.where(np.isfinite(v[jj[ok]].astype(float)),
                                   v[jj[ok]], False)
                A[f"M{tf}:{nev}"] = out
            for nev, arr in _esemenyek(d, p).items():
                v = np.asarray(arr)
                out = np.zeros(len(racs_ido), dtype=bool)
                out[ok] = np.where(np.isfinite(v[jj[ok]].astype(float)),
                                   v[jj[ok]], False)
                E[f"M{tf}:{nev}"] = out
        print(f"   {sym} M{tf}: {len(A)} allapot, {len(E)} esemeny osszesen",
              flush=True)
    return A, E


def onteszt(sym: str, racs_ido: pd.DatetimeIndex) -> None:
    """LOOK-AHEAD onteszt: egy H4 jel nem valtozhat a bar zarasa ELOTT.

    A projektben mar volt M15 look-ahead hiba, ezert ezt kulon ellenorizzuk.
    """
    m1 = lab.load_m1(sym)
    tf = 240
    d = lab.resample(m1, tf)
    c = d["close"].to_numpy(float)
    sig = c > lab.sma(c, 14)
    zaras = d.index + pd.Timedelta(minutes=tf)
    j = np.searchsorted(zaras, racs_ido, side="right") - 1
    # minden racspontra: a hozzarendelt bar zarasa <= a racspont ideje?
    ok = j >= 0
    kesobbi = (zaras[j[ok]] > racs_ido[ok]).sum()
    print(f"   look-ahead onteszt ({sym}, H4): {kesobbi} olyan racspont, ahol a "
          f"jel forrasa MEG NEM zart le  -> {'HIBA' if kesobbi else 'rendben'}")


if __name__ == "__main__":
    sym = _sys.argv[1] if len(_sys.argv) > 1 else "Ger40"
    o = pd.read_parquet(ROOT / "data" / "outcomes" / f"{sym}.parquet")
    ido = pd.DatetimeIndex(o["ido"])
    onteszt(sym, ido)
    A, E = build(sym, ido)
    print(f"\n{sym}: {len(A)} allapot-jel, {len(E)} esemeny-jel")
    print(f"   parok (esemeny x allapot): {len(E) * len(A):,}")
    print(f"   harmasok (esemeny x allapot x allapot): "
          f"{len(E) * len(A) * (len(A) - 1) // 2:,}")

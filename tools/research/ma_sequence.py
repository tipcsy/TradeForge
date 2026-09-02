"""SORRENDHEZ KOTOTT SZALAG-SZETESES — a felhasznalo 3 lepcsos szetupja.

A LEIRAS (2026-09-02, chart-kepbol). Szinek: barna = SMA250, kek = SMA100,
piros = SMA21, sarga = SMA8.

  1. FELFEGYVERZES: a PIROS (21) keresztezi a BARNAT (250) ES a KEKET (100) is,
     es lefele indul  ->  az irany SELL. (BUY-nal minden forditva.)
  2. BELEPO: a KEK (100) felulrol keresztezi a BARNAT (250) — "a zuhanas
     kezdete".
  3. KISZALLAS: a PIROS (21) iranyt valt es keresztezi a KEKET (100).

⚠ A SORREND KOTELEZO. A felhasznalo kiemelte: "az egyes utan jojjon a kettes
belepo, ha valamiert nem az tortenik, akkor az egyes szitacio megszunik". Ezert
ez NEM ugyanaz, mint a `ma_stack.py`-ban mert egyedi keresztezodes: ott minden
100/250 kereszt szamitott, itt csak az, amit MEGELOZOTT egy 21-es szeteses, es
kozben nem tortent visszalepes.

⚠ EZ A KULONBSEG A MERES TARGYA. Az elso kor azt mutatta, hogy egy MAGABAN allo
keresztezodes iranya semmit nem hordoz (az ar mindket irany utan emelkedett).
A kerdes most az, hogy a SORREND ad-e hozza — vagyis a ritkabb, felteteles
esemeny jobb-e, mint a gyakori.

⚠ ELORE ROGZITETT VARAKOZAS. Ket ellentetes hatas kuzd:
  (+) a sorrend valodi szurest jelent: sokkal kevesebb, de "tisztabb" eset;
  (-) a kevesebb eset nagyobb szorast es rosszabb statisztikat ad, es a
      `holdout-search-first-signal` szerint 1 plusz feltetel meg segit, 2 mar
      illeszt — itt harom van.
Azt varom, hogy a brutto atlag pozitiv lesz (a szetup definicio szerint egy mar
elindult mozgast fog meg), de az ESETSZAM kicsi, es a nettó eredmeny a
tartas hosszatol fugg. A meres dontse el.

Futtatas:

    python tools/research/ma_sequence.py
    python tools/research/ma_sequence.py --symbols Ger40 --reszletek
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
import ma_stack as ms

SYMS = ["GOLD", "USDJPY", "UsaInd", "UsaTec", "Ger40"]

# A felfegyverzes ennyi bar utan elavul, ha nem jon a belepo. 3 nap M1-en.
# ⚠ KELL EGY KORLAT: enelkul egy honapokkal korabbi "felfegyverzes" is
# ervenyesitene egy kesobbi 100/250 keresztet, es a sorrend elvesztene az
# ertelmet.
FEGYVER_MAX = 3 * 1440
# A pozicio maximalis tartasa, ha a 3. lepcso nem jon el.
TARTAS_MAX = 10 * 1440
# A stop a kockazat normalizalasahoz (R = ennyi ATR).
STOP_ATR = 1.5


def _keresztek(a, b):
    """`(fel, le)` bool tombok: az `a` sorozat alulrol/felulrol keresztezi `b`-t."""
    d = a - b
    e = ms._shift(d, 1)
    ok = np.isfinite(e) & np.isfinite(d)
    return (ok & (e <= 0) & (d > 0)), (ok & (e >= 0) & (d < 0))


def szetupok(j: dict) -> list:
    """A 3 lepcsos szetupok: `[(irany, fegyver_i, belepo_i, kilepo_i), ...]`.

    Az allapotgep bar-onkent lep, de csak az ESEMENYEKEN — a keresztek ritkak,
    tehat a hurok rovid."""
    s8, s21, s100, s250 = (j["sma8"], j["sma21"], j["sma100"], j["sma250"])
    f21_250, l21_250 = _keresztek(s21, s250)
    f21_100, l21_100 = _keresztek(s21, s100)
    f100_250, l100_250 = _keresztek(s100, s250)

    # A 21 HELYZETE a masik kettohoz kepest (a felfegyverzes feltetele).
    alatt = np.isfinite(s21) & np.isfinite(s250) & np.isfinite(s100) \
        & (s21 < s250) & (s21 < s100)
    folott = np.isfinite(s21) & np.isfinite(s250) & np.isfinite(s100) \
        & (s21 > s250) & (s21 > s100)

    # Esemeny-indexek egyben, idorendben.
    esem = []
    for nev, m in (("21le", l21_250 | l21_100), ("21fel", f21_250 | f21_100),
                   ("100le", l100_250), ("100fel", f100_250),
                   ("21fel100", f21_100), ("21le100", l21_100)):
        for i in np.flatnonzero(m):
            esem.append((int(i), nev))
    esem.sort()

    ki = []
    fegyver = None          # (irany, felfegyverzes_index) — vagy None
    nyitva = None           # (irany, belepo_index, felfegyverzes_index)
    for i, nev in esem:
        # ── NYITOTT pozicio: csak a 3. lepcsot (vagy az idokorlatot) figyeljuk
        if nyitva is not None:
            irany, be, fi = nyitva
            zar = ((irany == "SELL" and nev == "21fel100") or
                   (irany == "BUY" and nev == "21le100"))
            if zar:
                ki.append((irany, fi, be, i))
                nyitva = None
            elif i - be > TARTAS_MAX:
                ki.append((irany, fi, be, be + TARTAS_MAX))
                nyitva = None
            continue

        # ── FELFEGYVERZETT allapot: a 2. lepcsot varjuk
        if fegyver is not None:
            irany, fi = fegyver
            if i - fi > FEGYVER_MAX:
                fegyver = None                      # elavult
            # ⚠ A VISSZALEPES TORLI a felfegyverzest (a felhasznalo szabalya:
            # "ha valamiert nem az tortenik, akkor az egyes szitacio megszunik").
            elif ((irany == "SELL" and nev == "21fel") or
                  (irany == "BUY" and nev == "21le")):
                fegyver = None
            elif ((irany == "SELL" and nev == "100le") or
                  (irany == "BUY" and nev == "100fel")):
                nyitva = (irany, i, fi)             # 2. lepcso: BELEPO
                fegyver = None
                continue

        # ── 1. lepcso: a 21 MOST kerult mindketto ALA (SELL) / FOLE (BUY)
        if nev == "21le" and alatt[i]:
            fegyver = ("SELL", i)
        elif nev == "21fel" and folott[i]:
            fegyver = ("BUY", i)
    return ki


def kiertekel(df, j, szet, stop_atr=STOP_ATR):
    """Minden szetupra: R, tartas, MAE — KOLTSEGGEL es anelkul.

    ⚠ A STOP ELOSZOR. Ha a pozicio a 3. lepcso ELOTT elerne a stopot, akkor a
    valosagban ott zarna — a jel-alapu kiszallas nem menti meg. Enelkul a meres
    egy "stop nelkuli" vilagot merne, ami nem letezik."""
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = j["close"]
    atr = j["atr"]
    sp = (df["avg_spread"].to_numpy(float) if "avg_spread" in df else
          np.zeros(len(df)))
    sorok = []
    for irany, _fi, be, ki in szet:
        if not (np.isfinite(atr[be]) and atr[be] > 0) or ki >= len(c):
            continue
        d = 1 if irany == "BUY" else -1
        a = atr[be]
        stop = stop_atr * a
        belep = c[be]
        koltseg = (sp[be] + sp[min(ki, len(sp) - 1)]) / a   # be + ki, ATR-ben
        veg, mae, stoppolt = None, 0.0, False
        for t in range(be + 1, min(ki, len(c) - 1) + 1):
            kedvezotlen = (belep - l[t]) if d > 0 else (h[t] - belep)
            if kedvezotlen > mae:
                mae = kedvezotlen
            if kedvezotlen >= stop:
                veg, stoppolt = belep - d * stop, True
                ki = t
                break
        if veg is None:
            veg = c[ki]
        r_brutto = d * (veg - belep) / stop
        r_netto = r_brutto - koltseg * a / stop
        sorok.append({"irany": irany, "be": be, "ki": ki,
                      "bar": ki - be, "stop": stoppolt,
                      "r_brutto": r_brutto, "r_netto": r_netto,
                      "mae_atr": mae / a, "ev": df.index[be].year})
    return pd.DataFrame(sorok)


# ── SZUROK: pontositjak-e a belepot? ──────────────────────────────────────
def szurok(df, j, t: "pd.DataFrame") -> dict:
    """`{nev: bool maszk}` a szetup-sorokra.

    KET KERDES egy futasban:

    (a) A FELHASZNALO KERDESE (2026-09-02): "rakjunk hozza egy CCI-t, WPR-t vagy
        egy RSI indikatort, ami pontositja a beszallot?" — UJ BELEPO-JELKENT az
        oszcillatorok mar at vannak vizsgalva (`indicator-list-screened`: 230
        teszt, NULLA ahol mindket irany pozitiv). SZUROKENT viszont mas a
        szerepuk: nem uj kotest hoznak, hanem elvesznek a meglevokbol — es ez az
        egyetlen mechanizmus, ami a KOLTSEG-korlaton segithet.

        A hipotezis: a 100/250 keresztezodesnel a mozgas nagy resze MAR
        megtortent; ha az oszcillator ekkor mar EXTREM a kotes iranyaba, akkor a
        veget vesszuk meg. Tehat a szuro azt tartja meg, ahol MEG NEM extrem.

    (b) A KOLTSEG-SZURO: a belepeskori spread/ATR also negyede. A merések
        makacs kozos vonasa, hogy bruttoban a szetup pozitiv, nettoban nulla —
        tehat nem a jelzes a korlat, hanem az ar.

    ⚠ TOBBSZOROS TESZTELES. Hat szuro x 5 instrumentum: a legjobb MINDIG jonak
    latszik. Ezert a jelentesben ott van, hany instrumentumon pozitiv ES hogy
    mindket irany pozitiv-e — nem a legjobb cella szamit."""
    import numpy as _np
    import lab as _lab
    from indicator_screen import cci as _cci
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    be = t["be"].to_numpy(int)
    d = _np.where(t["irany"].to_numpy() == "BUY", 1, -1)

    _rsi = _lab.rsi(c, 14)[be]
    _wpr = _lab.wpr(h, l, c, 14)[be]
    _cciv = _cci(h, l, c, 20)[be]
    _sp = ((df["avg_spread"].to_numpy(float) if "avg_spread" in df
            else _np.zeros(len(df))) / _np.where(j["atr"] > 0, j["atr"], _np.nan))[be]

    _q1 = _np.nanpercentile(_sp[_np.isfinite(_sp)], 25) if _np.isfinite(_sp).any() else 0.0
    mind = _np.ones(len(be), dtype=bool)
    return {
        "alap (minden szetup)": mind,
        "olcso (spread/ATR Q1)": _np.isfinite(_sp) & (_sp <= _q1),
        "RSI meg nem extrem": _np.where(d > 0, _rsi < 65, _rsi > 35) & _np.isfinite(_rsi),
        "CCI meg nem extrem": _np.where(d > 0, _cciv < 100, _cciv > -100) & _np.isfinite(_cciv),
        "WPR meg nem extrem": _np.where(d > 0, _wpr < -20, _wpr > -80) & _np.isfinite(_wpr),
        "olcso + RSI nem extrem": (_np.isfinite(_sp) & (_sp <= _q1)
                                   & _np.where(d > 0, _rsi < 65, _rsi > 35)),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbols", nargs="*", default=SYMS)
    ap.add_argument("--reszletek", action="store_true")
    ap.add_argument("--szurok", action="store_true",
                    help="oszcillator- es koltseg-szurok merese a szetupokon")
    # ⚠ AZ IDOSIK DONTO. A koltseg KOTESENKENT fix, az ATR viszont az idosikkal
    # no — ugyanaz a szabaly M1-en a stop 20-40%-at fizeti spreadre, H1-en a
    # toredeket. A minta ugyanaz; csak az ara nem.
    ap.add_argument("--tf", type=int, default=1, help="chart-idosik percben")
    ap.add_argument("--stop", type=float, default=STOP_ATR,
                    help="a stop az ATR tobbszorosekent")
    a = ap.parse_args(argv)

    osszes = []
    print(f"  idosik M{a.tf} · stop {a.stop} x ATR · FEGYVER_MAX {FEGYVER_MAX} bar")
    print(f"  {'instrumentum':<10}{'db':>6}{'long':>6}{'short':>7}"
          f"{'R brutto':>11}{'R netto':>10}{'t':>8}{'talalat':>9}"
          f"{'ev+':>7}{'bar':>8}")
    print("  " + "-" * 82)
    for sym in a.symbols:
        try:
            df = lab.load_m1(sym)
        except Exception as ex:
            print(f"  {sym}: NINCS ADAT ({ex})")
            continue
        if a.tf > 1:
            df = lab.resample(df, a.tf)
        j = ms.jellemzok(df)
        szet = szetupok(j)
        t = kiertekel(df, j, szet, stop_atr=a.stop)
        if t.empty:
            print(f"  {sym:<10}{0:>6}   (nincs szetup)")
            continue
        t["sym"] = sym
        if a.szurok:
            for nev, m in szurok(df, j, t).items():
                t["SZ_" + nev] = m
        osszes.append(t)
        evenkent = t.groupby("ev")["r_netto"].mean()
        print(f"  {sym:<10}{len(t):>6}{int((t.irany=='BUY').sum()):>6}"
              f"{int((t.irany=='SELL').sum()):>7}"
              f"{t.r_brutto.mean():>+11.3f}{t.r_netto.mean():>+10.3f}"
              f"{ms._t_stat(t.r_netto.to_numpy()):>+8.2f}"
              f"{100*(t.r_netto>0).mean():>8.0f}%"
              f"{100*(evenkent>0).mean():>6.0f}%{t.bar.mean():>8.0f}")
        if a.reszletek:
            print(f"      long  R {t[t.irany=='BUY'].r_netto.mean():+.3f}   "
                  f"short R {t[t.irany=='SELL'].r_netto.mean():+.3f}   "
                  f"stopolt {100*t['stop'].mean():.0f}%   "
                  f"MAE atlag {t.mae_atr.mean():.2f} ATR")
    if osszes:
        mind = pd.concat(osszes, ignore_index=True)
        print("  " + "-" * 82)
        print(f"  {'OSSZES':<10}{len(mind):>6}"
              f"{int((mind.irany=='BUY').sum()):>6}"
              f"{int((mind.irany=='SELL').sum()):>7}"
              f"{mind.r_brutto.mean():>+11.3f}{mind.r_netto.mean():>+10.3f}"
              f"{ms._t_stat(mind.r_netto.to_numpy()):>+8.2f}"
              f"{100*(mind.r_netto>0).mean():>8.0f}%")
        print()
        print(f"  long  : {int((mind.irany=='BUY').sum()):>5} db   "
              f"R {mind[mind.irany=='BUY'].r_netto.mean():+.3f}")
        print(f"  short : {int((mind.irany=='SELL').sum()):>5} db   "
              f"R {mind[mind.irany=='SELL'].r_netto.mean():+.3f}")
        print(f"  a szetupok {100*mind['stop'].mean():.0f}%-a STOPPAL zart, "
              f"atlagos tartas {mind.bar.mean():.0f} bar "
              f"({mind.bar.mean()/60:.1f} ora)")
        if a.szurok:
            print()
            print("  SZUROK — pontositjak-e a belepot?")
            print(f"  {'szuro':<26}{'db':>6}{'R netto':>10}{'t':>8}"
                  f"{'long':>9}{'short':>9}{'poz.par':>9}")
            print("  " + "-" * 71)
            for _o in [c for c in mind.columns if c.startswith("SZ_")]:
                m = mind[_o].fillna(False).to_numpy(bool)
                if m.sum() < 200:
                    continue
                _r = mind.loc[m, "r_netto"]
                _lo = mind.loc[m & (mind.irany == "BUY"), "r_netto"]
                _sh = mind.loc[m & (mind.irany == "SELL"), "r_netto"]
                _pp = sum(1 for _s in mind["sym"].unique()
                          if mind.loc[m & (mind["sym"] == _s), "r_netto"].mean() > 0)
                print(f"  {_o[3:]:<26}{len(_r):>6}{_r.mean():>+10.3f}"
                      f"{ms._t_stat(_r.to_numpy()):>+8.2f}"
                      f"{_lo.mean():>+9.3f}{_sh.mean():>+9.3f}"
                      f"{_pp:>6}/{mind['sym'].nunique()}")
    return 0


if __name__ == "__main__":
    _sys.exit(main())

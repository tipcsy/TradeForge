"""AR-ALAPU FORDULO-CIMKE — elorejelzi-e a mozgoatlag-allapot a NYERESEGET?

⚠ MIERT KELLETT UJ CIMKE. Az elso koros meresben (`ma_stack.py`) a
"trendfordulo" a `sign(sma100 - sma250)` elojelvaltasa volt — vagyis egy
DEFINICIO, nem armozgas. Ezert jott ki, hogy a 21-250 kozelitese 61,9%-ban
"elorejelzi a fordulot": reszben csak azt mondtuk vissza, hogy ha az atlagok
osszeernek, akkor osszeernek. (`retrospective-label-trap`.)

Itt a cimke ARBAN van megadva, es KERESKEDHETO:

    fordulo = a jelenlegi trenddel SZEMBEN az ar elobb megy +2 ATR-t,
              mint amennyit -1 ATR-t menne ellene, 8 oran belul

Ez mar magaban hordozza a nyereseget: aki a cimkere lep be, 2R-t nyer vagy 1R-t
veszit. A kerdes tehat nem az, hogy "a keresztezodes jelzi-e a keresztezodest",
hanem hogy a mozgoatlag-allapot jelzi-e a PENZT.

⚠ A CIMKE BRUTTO (spread nelkul). Szandekosan: itt azt merjuk, van-e egyaltalan
elorejelezheto armozgas. A koltseget a `ma_stack.py` mar megmerte (a brutto el
2-9-szerese) — ha a cimke sem jelezheto elore, akkor a koltseg kerdese fel sem
merul.

⚠ ELORE ROGZITETT VARAKOZAS. Azt varom, hogy a felteteles valoszinusegek KOZEL
lesznek az alapratahoz (a lift < 10%), mert az elso kor szerint a keresztezodes
iranya semmit nem hordozott, es a "fordulo" jelzesek nagy resze definicio-hatas
volt. Ha viszont a lejtes-egyetertes erdemi liftet ad, az UJ informacio — az
volt az elso kor legerosebb leiro leletje (t = -3,89).

Futtatas:

    python tools/research/ma_reversal.py
    python tools/research/ma_reversal.py --symbols Ger40 --paritas
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

# A cimke parameterei.
CEL_ATR = 2.0        # ennyit kell mennie a fordulo iranyaba…
STOP_ATR = 1.0       # …mielott ennyit menne ellene
HORIZONT = 480       # 8 ora M1-en
MINTA = 30           # minden ennyiedik bart cimkezunk (sebesseg)

SYMS = ["GOLD", "USDJPY", "UsaInd", "UsaTec", "Ger40"]


def cimke(h, l, c, atr, idx, side, cel_atr=CEL_ATR, stop_atr=STOP_ATR,
          horizont=HORIZONT):
    """ELSO ERINTES cimke, VEKTORIZALVA: `(nyert, vesztett)` bool tombok.

    ⚠ EZ A `mae_mfe.excursions` IKERTESTVERE. Az ottani valtozat belepésenkent
    fut egy Python-hurokban (par ezer kotesre keszult); itt szazezres
    nagysagrendben kell cimkezni, ezert a hurok a HORIZONTON megy, es minden
    belepore EGYSZERRE szamol. A konvencio ugyanaz — es a `--paritas` kapcsolo
    ossze is veti a kettot, mert ket kulon implementacio kulon romlik el
    (ebbol tanult a projekt a `BacktestReplayer` v4-nel).

    ⚠ BRUTTO: spread nelkul. A cimke azt kerdezi, VAN-E armozgas; a koltseget a
    `ma_stack.py` meri."""
    be = c[idx]
    a = atr[idx]
    nyert = np.zeros(len(idx), dtype=bool)
    veszt = np.zeros(len(idx), dtype=bool)
    kesz = np.zeros(len(idx), dtype=bool)
    n = len(c)
    for j in range(1, horizont + 1):
        p = idx + j
        el = p < n
        if not el.any():
            break
        pp = np.where(el, p, 0)
        hi, lo = h[pp], l[pp]
        # A kedvezo/kedvezotlen elmozdulas az IRANY szerint.
        kedv = np.where(side > 0, hi - be, be - lo) / a
        kedvez = np.where(side > 0, be - lo, hi - be) / a
        _uj_ny = (~kesz) & el & (kedv >= cel_atr)
        _uj_ve = (~kesz) & el & (kedvez >= stop_atr)
        # ⚠ Ha EGY BARON mindketto teljesul, a STOP nyer — konzervativ, es
        # ugyanaz a konvencio, mint a `mae_mfe.outcome_at`-ban.
        nyert |= _uj_ny & ~_uj_ve
        veszt |= _uj_ve
        kesz |= _uj_ny | _uj_ve
        if kesz.all():
            break
    return nyert, veszt


def _kvintilis(x, m):
    """Az `x` kvintilisei a MASZKOLT mintan (1..5); 0 = ervenytelen."""
    ki = np.zeros(len(x), dtype=int)
    v = x[m]
    v = v[np.isfinite(v)]
    if len(v) < 100:
        return ki
    hat = np.nanpercentile(v, [20, 40, 60, 80])
    ki[m] = np.digitize(x[m], hat) + 1
    ki[~np.isfinite(x)] = 0
    return ki


def merj(sym: str) -> list:
    df = lab.load_m1(sym)
    j = ms.jellemzok(df)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = j["close"]
    atr = j["atr"]
    trend = j["trend"]

    # ⚠ A FORDULO IRANYA a TRENDDEL SZEMBEN van: ha a trend le, a fordulo LONG.
    ervenyes = (np.isfinite(atr) & (atr > 0) & np.isfinite(trend) & (trend != 0)
                & np.isfinite(j["egyetertes"]))
    idx_mind = np.flatnonzero(ervenyes)
    idx = idx_mind[::MINTA]
    idx = idx[idx + HORIZONT < len(c)]
    if len(idx) < 5000:
        return []
    side = (-trend[idx]).astype(int)

    nyert, veszt = cimke(h, l, c, atr, idx, side)
    # R: nyeres +2, vesztes -1, idokilepes 0 (konzervativ).
    r = np.where(nyert, CEL_ATR / STOP_ATR, np.where(veszt, -1.0, 0.0))
    alap_p = float(nyert.mean())
    alap_r = float(r.mean())

    sorok = [{"sym": sym, "felt": "ALAPRATA", "n": len(idx),
              "p": alap_p, "r": alap_r, "lift": 0.0, "t": 0.0}]

    def _sor(nev, m):
        if m.sum() < 500:
            return
        sorok.append({"sym": sym, "felt": nev, "n": int(m.sum()),
                      "p": float(nyert[m].mean()), "r": float(r[m].mean()),
                      "lift": float(nyert[m].mean() / alap_p - 1.0) if alap_p else 0.0,
                      "t": ms._t_stat(r[m] - alap_r)})

    # 1. LEJTES-EGYETERTES (az elso kor legerosebb leletje). A fordulohoz az
    #    ALACSONY egyetertes kellene, hogy segitsen: a szalag szetesett.
    egyet = j["egyetertes"][idx]
    for k in range(5):
        _sor(f"egyetertes={k}", egyet == k)

    # 2. A SZALAG SZELESSEGE saját magahoz merve (szuk = squeeze).
    szel = (np.abs(j["sma8"] - j["sma250"]) / np.where(atr > 0, atr, np.nan))[idx]
    kv = _kvintilis(szel, np.isfinite(szel))
    for k in (1, 5):
        _sor(f"szalag-szelesseg Q{k}", kv == k)

    # 3. A 21-250 KOZELITESE (a felhasznalo eredeti hipotezise, most AR-cimken).
    _sor("21-250 kozelit", j["lejto_t21_250"][idx] < 0)
    _sor("21-250 kozelit ES kozel", (j["lejto_t21_250"][idx] < 0)
         & (j["t21_250"][idx] < 0.5))

    # 4. A LEGGYORSABB SMA lejtese MAR a fordulo iranyaba mutat.
    _sor("sma8 lejtese mar fordult", np.sign(j["lejto8"][idx]) == side)
    _sor("sma8 ES sma21 mar fordult",
         (np.sign(j["lejto8"][idx]) == side) & (np.sign(j["lejto21"][idx]) == side))

    # 5. EGYUTT: szetesett szalag + a gyors atlagok mar fordultak.
    _sor("szalag szetesett + gyorsak fordultak",
         (egyet <= 1) & (np.sign(j["lejto8"][idx]) == side)
         & (np.sign(j["lejto21"][idx]) == side))
    return sorok


def paritas(sym: str = "Ger40", db: int = 300) -> None:
    """A vektorizalt cimke ossszevetese a `mae_mfe.excursions`-szel.

    ⚠ KET IMPLEMENTACIO KULON ROMLIK EL. A projekt ezt tobbszor megfizette;
    ezert nem eleg, hogy "ugyanaz a konvencio" — meg is kell mutatni."""
    import mae_mfe as mm
    import gates_lab as gl
    C = gl.build(sym)
    j = ms.jellemzok(C["d"])
    atr = C["atr"]
    ok = np.flatnonzero(np.isfinite(atr) & (atr > 0)
                        & np.isfinite(j["trend"]) & (j["trend"] != 0))
    ok = ok[(ok > 1000) & (ok + HORIZONT < len(atr) - 1)]
    idx = ok[:: max(1, len(ok) // db)][:db]
    side = (-j["trend"][idx]).astype(int)

    # A sajat (vektorizalt) cimke — a `mae_mfe` KOLTSEGES konvenciojaval nem
    # osszemerheto, ezert a spreadet ott is kinullazzuk.
    _sp = C["sp_pts"]
    C["sp_pts"] = np.zeros_like(_sp)
    e = mm.excursions(C, idx, side, max_hold=HORIZONT)
    C["sp_pts"] = _sp
    r_ref, win_ref, lose_ref = mm.outcome_at(e, STOP_ATR, CEL_ATR)

    nyert, veszt = cimke(C["h"], C["l"], C["c"], atr, idx, side)
    # Az `excursions` kihagyja az ervenytelen sorokat -> illesszuk a hosszt.
    m = min(len(nyert), len(win_ref))
    egyezik_ny = int((nyert[:m] == win_ref[:m]).sum())
    egyezik_ve = int((veszt[:m] == lose_ref[:m]).sum())
    print(f"  PARITAS ({sym}, {m} minta):")
    print(f"    nyertes egyezes : {egyezik_ny}/{m}  ({100*egyezik_ny/m:.1f}%)")
    print(f"    vesztes egyezes : {egyezik_ve}/{m}  ({100*egyezik_ve/m:.1f}%)")
    if egyezik_ny < m or egyezik_ve < m:
        _e = np.flatnonzero((nyert[:m] != win_ref[:m]) | (veszt[:m] != lose_ref[:m]))
        print(f"    ⚠ ELTERES {len(_e)} soron — elso par index: {_e[:5]}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbols", nargs="*", default=SYMS)
    ap.add_argument("--paritas", action="store_true")
    a = ap.parse_args(argv)
    if a.paritas:
        paritas(a.symbols[0] if a.symbols else "Ger40")
        return 0
    sorok = []
    for sym in a.symbols:
        try:
            print(f"  … {sym}", flush=True)
            sorok += merj(sym)
        except Exception as ex:
            print(f"  {sym}: HIBA — {type(ex).__name__}: {ex}")
    ms._tabla("AR-ALAPU FORDULO-CIMKE: P(a fordulo +2 ATR-t megy -1 ATR elott)",
              [{**x, "kulcs": f"{x['sym']} {x['felt']}"} for x in sorok],
              ["kulcs", "n", "p", "r", "lift", "t"])
    return 0


if __name__ == "__main__":
    _sys.exit(main())

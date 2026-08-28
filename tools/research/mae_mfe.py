"""MENNYIRE LOTTUNK MELLE? — MAE/MFE elemzes a legjobb belepon.

A felhasznalo kerdesei (2026-08-28), es hogy melyiket mi valaszolja meg:

  4.2.1 "nyitsz egy BUY-t es rogton elindul lefele — mennyit ment lefele"
        -> MAE (Maximum Adverse Excursion), ATR-egysegben
  4.2.2 "mennyit ment felfele, mennyire talaltad el az iranyt"
        -> MFE (Maximum Favorable Excursion)
  4.2.3 "mennyi ido telt el pozitiv tartomanyban"
  4.2.4 "mennyi ido telt el negativban"
  4.3   "nem-e a SL volt tul kozel vagy tul tavol"
        -> a stop-szelesseg szerinti varhato ertek + a MEGMENTHETO vesztesek

A KULCS-kerdes (Pajzs-technika): hany olyan vesztes van, ami eloszor elment
+0,5R / +0,8R-ig, es CSAK AZUTAN fordult stopba? Azok nulla-zhatok vagy akar
nyereseggel zarhatok.

Modszer: minden belepore ELORE vegigmegyunk, es feljegyezzuk, MELYIK BARON eri
el eloszor az egyes kedvezo/kedvezotlen szinteket. Ebbol minden tovabbi kerdes
(stop, cel, breakeven, pajzs) SZAMOLHATO — nem kell ujraszimulalni.
"""
from __future__ import annotations

# A repobol futtathato: a projekt gyokere ES a testvermodulok a sys.path-ra.
import sys as _sys
from pathlib import Path as _Path
ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import sys
import numpy as np
import pandas as pd

import lab
import gates_lab as GL
import run_gates as RG
import rules_long as RL

SYMS = ["Ger40", "UsaInd", "UsaTec", "GOLD", "USDJPY"]
GATES = ["spread", "volatilitas", "lendulet", "piac", "egyuttallas", "szep_chart"]
MAXH = 96                      # 24 ora — hagyjunk helyet a kifutasnak
# a szintek ATR-egysegben (a stop-fuggetlenseg miatt)
FAV = np.array([0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0])
ADV = np.array([0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 4.0, 6.0])


def excursions(C, idx, side, max_hold=MAXH):
    """Minden belepore: az egyes szintek ELSO elerese (bar-index), plusz
    MAE/MFE es a pozitiv/negativ tartomanyban toltott ido.

    A vegrehajtas konvencioja a motore: BUY ask-on nyit / bid-en zar, SELL
    forditva — tehat a kedvezo/kedvezotlen elmozdulast a KILEPESI oldalon
    merjuk, a belepot pedig a spreaddel terhelve."""
    h, l, c, atr, ps = C["h"], C["l"], C["c"], C["atr"], C["ps"]
    sp = C["sp_pts"] * ps
    n = len(c)
    rows = []
    for k in range(len(idx)):
        i, s = int(idx[k]), int(side[k])
        if not np.isfinite(atr[i]) or i + 2 >= n:
            continue
        a = atr[i]
        entry = c[i] + (sp[i] if s > 0 else 0.0)      # BUY ask-on lep be
        end = min(n - 1, i + max_hold)
        f_hit = np.full(len(FAV), -1, dtype=np.int32)
        a_hit = np.full(len(ADV), -1, dtype=np.int32)
        mfe = mae = 0.0
        t_pos = t_neg = 0
        for j in range(i + 1, end + 1):
            if s > 0:
                hi, lo = h[j], l[j]                    # BUY: bid-en zar
            else:
                hi, lo = h[j] + sp[j], l[j] + sp[j]    # SELL: ask-on zar
            fav = (hi - entry) / a if s > 0 else (entry - lo) / a
            adv = (entry - lo) / a if s > 0 else (hi - entry) / a
            if fav > mfe:
                mfe = fav
            if adv > mae:
                mae = adv
            for m in range(len(FAV)):
                if f_hit[m] < 0 and mfe >= FAV[m]:
                    f_hit[m] = j - i
            for m in range(len(ADV)):
                if a_hit[m] < 0 and mae >= ADV[m]:
                    a_hit[m] = j - i
            close_r = ((c[j] - entry) if s > 0 else (entry - c[j] - sp[j])) / a
            if close_r > 0:
                t_pos += 1
            elif close_r < 0:
                t_neg += 1
        rows.append({"sym": C["sym"], "t": C["d"].index[i], "dir": s,
                     "mfe": mfe, "mae": mae, "t_poz": t_pos, "t_neg": t_neg,
                     "koltseg_atr": sp[i] / a,
                     **{f"f{FAV[m]}": f_hit[m] for m in range(len(FAV))},
                     **{f"a{ADV[m]}": a_hit[m] for m in range(len(ADV))}})
    return pd.DataFrame(rows)


def outcome_at(df, stop_atr, target_atr):
    """Kimenet ADOTT stop/cel mellett — az elso eleres sorrendjebol.
    Vissza: R-ben (R = stop_atr), es a status."""
    fs = f"f{target_atr}"
    as_ = f"a{stop_atr}"
    ft = df[fs].to_numpy()
    at = df[as_].to_numpy()
    hit_f = ft >= 0
    hit_a = at >= 0
    # ha mindketto: amelyik ELOBB volt (egyenlonel a stop nyer = konzervativ)
    win = hit_f & (~hit_a | (ft < at))
    lose = hit_a & (~hit_f | (at <= ft))
    r = np.where(win, target_atr / stop_atr, np.where(lose, -1.0, 0.0))
    # ido-kilepes (se stop, se cel): a MFE/MAE-bol nem tudjuk pontosan, 0-nak
    # vesszuk — ez KONZERVATIV a nyertesekre nezve.
    return r, win, lose


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    parts = []
    for sym in SYMS:
        print(f"   … {sym}", flush=True)
        C = GL.build(sym)
        i, s = RL.donchian(C, 96)
        m = np.ones(len(i), bool)
        for g in GATES:
            m &= RG.gate_mask_for(C, i, s, g)
        parts.append(excursions(C, i[m], s[m]))
    df = pd.concat(parts, ignore_index=True)
    df.to_parquet("mae_mfe.parquet")
    print(f"\n{len(df):,} kotes, {df.t.min():%Y-%m} … {df.t.max():%Y-%m}")

    print("\n=== 1. MENNYIRE TALALTUK EL AZ IRANYT ===")
    print(f"  MFE (max kedvezo elmozdulas) atlaga: {df.mfe.mean():.2f} ATR")
    print(f"  MAE (max kedvezotlen)        atlaga: {df.mae.mean():.2f} ATR")
    print(f"  MFE/MAE arany: {df.mfe.mean() / df.mae.mean():.3f}  "
          f"(1,0 = nincs irany-el)")
    print(f"  a kotesek {100 * (df.mfe > df.mae).mean():.1f}%-anal ment TOBBET "
          f"a jo iranyba, mint a rosszba")
    print("\n  eloszlas:")
    print(pd.DataFrame({"MFE": df.mfe.describe(
        percentiles=[.1, .25, .5, .75, .9]),
        "MAE": df.mae.describe(percentiles=[.1, .25, .5, .75, .9])}
    ).to_string(float_format=lambda x: f"{x:8.2f}"))

    print("\n=== 2. AZONNAL ROSSZ IRANYBA (soha nem ment plusszba) ===")
    soha = (df["f0.25"] < 0)
    print(f"  a kotesek {100 * soha.mean():.1f}%-a el sem erte a +0,25 ATR-t")
    for lv in (0.5, 1.0, 2.0):
        print(f"  +{lv} ATR-t elerte: {100 * (df[f'f{lv}'] >= 0).mean():5.1f}%   "
              f"| -{lv} ATR-t elerte: {100 * (df[f'a{lv}'] >= 0).mean():5.1f}%")

    print("\n=== 3. IDO POZITIV vs NEGATIV TARTOMANYBAN ===")
    tot = df.t_poz + df.t_neg
    ar = df.t_poz / tot.replace(0, np.nan)
    print(f"  az ido {100 * ar.mean():.1f}%-a telt PLUSZBAN (medián "
          f"{100 * ar.median():.1f}%)")
    print(f"  a kotesek {100 * (ar > 0.5).mean():.1f}%-a tolti az ideje "
          f"tobbet pluszban")

    print("\n=== 4. A STOP SZELESSEGE (a 4.3 kerdes) ===")
    rows = []
    for st in (0.5, 1.0, 1.5, 2.0, 2.5, 4.0):
        for tg in (0.5, 1.0, 1.5, 2.0, 3.0, 4.0):
            if tg not in FAV or st not in ADV:
                continue
            r, w, l = outcome_at(df, st, tg)
            rows.append({"stop_ATR": st, "cel_ATR": tg, "RR": tg / st,
                         "nyero%": 100 * w.mean(), "vesztes%": 100 * l.mean(),
                         "ido_kilepes%": 100 * (~w & ~l).mean(),
                         "R/kotes": float(r.mean())})
    st = pd.DataFrame(rows)
    print(st.sort_values("R/kotes", ascending=False).head(12)
            .to_string(index=False, float_format=lambda x: f"{x:8.3f}"))

    print("\n=== 5. MEGMENTHETO VESZTESEK (a Pajzs-kerdes) ===")
    print("  A stopba futo kotesek kozul hany ment ELOSZOR a jo iranyba?")
    for st_ in (1.0, 1.5, 2.0, 2.5):
        at = df[f"a{st_}"].to_numpy()
        stopos = at >= 0
        if stopos.sum() == 0:
            continue
        sor = [f"  stop {st_} ATR ({100 * stopos.mean():4.1f}% fut stopba):"]
        for lv in (0.25, 0.5, 0.75, 1.0):
            ft = df[f"f{lv}"].to_numpy()
            # eloszor elerte a +lv-t, es CSAK AZUTAN a stopot
            menthet = stopos & (ft >= 0) & (ft < at)
            sor.append(f"+{lv}R elott: {100 * menthet.sum() / stopos.sum():4.1f}%")
        print("   ".join(sor))

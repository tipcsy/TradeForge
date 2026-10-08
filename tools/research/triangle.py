"""DEVIZA-HAROMSZOG: a kereszt-arfolyam lemarad-e a ket USD-lab mogott?

A kerdes (2026-09-28): „nezz mas instrumentumot is, EURUSD -> GBPUSD -> EURGBP".
A GBPUSD nincs letoltve, ezert az ELSO haromszog, ami tickben teljes:

        EURJPY  =  EURUSD  x  USDJPY          (2024-01 .. 2026-08, tick)

Ez mas TIPUSU hipotezis, mint az eddigiek: nem az ar sajat multjabol josol,
hanem egy KENYSZER-kapcsolatbol (a harom arfolyam nem mozoghat fuggetlenul).

H1  ARBITRAZS: a jegyzett EURJPY bid a szamolt (EURUSD x USDJPY) ask FOLE megy-e,
    vagy az ask a szamolt bid ALA — mindharom lab bid/ask-javal. Ha igen,
    kockazatmentes; a kerdes, milyen gyakran es mekkora.
H2  KESES (lead-lag): dev = ln(EURJPY_kozep) - ln(EURUSD_kozep x USDJPY_kozep)
    bazispontban. Ha a kereszt LEMARAD, dev < -kuszob utan az EURJPY felfele
    zar. Kereskedes CSAK az EURJPY-n (egy lab, egy spread):
      dev <= -k -> BUY ask-on,  dev >= +k -> SELL bid-en,
      BELEPES a jel utan KESES masodperccel (a retail MT5 nem nulla idoben tolt),
      kilepes h masodperccel kesobb a masik oldalon.

ELORE ROGZITETT ELFOGADAS (a futtatas ELOTT irva, 2026-09-28):
  Elsodleges: k = 1,0 bp, h = 30 s, keses = 1 s.
    (1) netto atlag > 0 bp/kotes, napra klaszterezett t >= 2,
    (2) a honapok >= 60%-aban pozitiv,
    (3) mindket feleben (2024-01..2025-04 es 2025-05..2026-08) pozitiv,
    (4) keses = 2 s mellett is netto pozitiv (kulonben latencia-jatek, nem el).
  A tobbi (k, h, keses) racs MASODLAGOS — tobbszoros teszteles.

VARAKOZAS (joslat): a retail CFD-broker a keresztet valoszinuleg a ket labbol
SZAMOLJA, igy a dev nagyreszt a tickek aszinkronitasa. H1-re ~0, H2-re brutto
van valami (a nem egyszerre frissulo jegyzes), de a spread folott nem marad.

EREDMENY (2026-09-28, 31 honap, 38 M masodperc) — MINDKETTO MEGBUKOTT:
  H2: NINCS keses. Brutto (kozep->kozep) +0,004 bp/kotes 1 s kesessel
      (t=+0,4), netto -1,61 bp (t=-35,6); 0/64 konfiguracio pozitiv. A kereszt
      nem marad le a labak mogott.
  H1: a pillanatkep „arbitrazst" mutat (a masodpercek 2,7%-a, atl. 1,67 bp,
      masodpercekig tart, evrol evre gyakoribb) — de CFD-n a harom labat
      VISSZA KELL ZARNI, es a zaraskor mindharom spread ujra fizetendo. A
      teljes oda-vissza kotes (1 s keses, bid/ask, korai zaras nullan felul):
      -2,6 .. -3,1 bp/kotes, csak 0,5-15%-ban zarodik a rés nullan felul,
      mindharom evben negativ (data/triangle_roundtrip.parquet). A dev havi
      atlaga +-0,5 bp-en belul: nem tartos eltolas, hanem a spreadeken belul
      mozgo zaj.

Futtatas:  python tools/research/triangle.py
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
from core import broker_paths as _BP                      # noqa: E402

from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

TICKS = _BP.feed_dir("ticks")
LABAK = {"EURUSD": 1e-5, "USDJPY": 1e-3, "EURJPY": 1e-3}   # point
KERESZT = "EURJPY"
RACS_MS = 1000
FRISS_MS = 3000            # minden labnak ennyin belul kellett tick
KUSZOB = (0.5, 1.0, 2.0, 3.0)
TARTAS = (5, 30, 120, 600)
KESES = (0, 1, 2, 5)
FO = (1.0, 30, 1)
KIMENET = _BP.research_dir() / "triangle_result.csv"


def _racs(ho: str):
    """1 mp-es racs, minden labra az utolso jegyzes (bid, ask) es a frissesseg."""
    t = {}
    for s, pt in LABAK.items():
        f = TICKS / s / f"{ho}.parquet"
        if not f.exists():
            return None
        d = pd.read_parquet(f)
        t[s] = (d.time_msc.to_numpy(), d.bid_pt.to_numpy() * pt, d.ask_pt.to_numpy() * pt)
    t0 = max(v[0][0] for v in t.values())
    t1 = min(v[0][-1] for v in t.values())
    g = np.arange(t0 - t0 % RACS_MS + RACS_MS, t1, RACS_MS, dtype=np.int64)
    out = {"g": g}
    friss = np.ones(len(g), bool)
    for s, (tm, b, a) in t.items():
        i = np.searchsorted(tm, g, "right") - 1
        out[s] = (b[i], a[i])
        friss &= (g - tm[i]) <= FRISS_MS
    out["friss"] = friss
    return out


def _honap(ho: str):
    R = _racs(ho)
    if R is None:
        return None
    g, fr = R["g"], R["friss"]
    eb, ea = R["EURUSD"]; ub, ua = R["USDJPY"]; xb, xa = R[KERESZT]
    ib, ia = eb * ub, ea * ua                    # szamolt kereszt bid / ask
    xm, im = (xb + xa) / 2, (ib + ia) / 2
    dev = 1e4 * np.log(xm / im)
    spr = 1e4 * (xa - xb) / xm                   # a kereszt spreadje bp-ben
    # rendellenes spread (rollover, hir) kizarva: a honap medianjanak 3x-a
    ok = fr & (spr > 0) & (spr <= 3 * np.nanmedian(spr[fr]))

    # H1: kockazatmentes haromszog (mindharom lab bid/ask-javal)
    arb = ok & ((xb > ia) | (xa < ib))
    arb_bp = np.where(xb > ia, 1e4 * np.log(xb / ia),
                      np.where(xa < ib, 1e4 * np.log(ib / xa), 0.0))
    h1 = {"ho": ho, "mp": int(ok.sum()), "arb_mp": int(arb.sum()),
          "arb_atl_bp": float(arb_bp[arb].mean()) if arb.any() else 0.0,
          "dev_szoras_bp": float(np.nanstd(dev[ok])),
          "spread_med_bp": float(np.nanmedian(spr[ok]))}

    # H2: keses-jatek csak a kereszten
    nap = (g // 86_400_000).astype(np.int64)
    sorok = []
    n = len(g)
    for k in KUSZOB:
        jel = np.where(ok & (dev <= -k), 1, np.where(ok & (dev >= k), -1, 0))
        elozo = np.concatenate([[0], jel[:-1]])
        indul = np.flatnonzero((jel != 0) & (jel != elozo))
        for h in TARTAS:
            for L in KESES:
                be = indul + L
                ki = be + h
                v = ki < n
                be, ki, irany = be[v], ki[v], jel[indul[v]]
                v = fr[be] & fr[ki] & ((g[ki] - g[be]) == h * RACS_MS)
                be, ki, irany = be[v], ki[v], irany[v]
                # egyszerre egy kotes (ne szamoljuk tobbszor ugyanazt a mozgast)
                keep, foglalt = [], -1
                for j in range(len(be)):
                    if be[j] > foglalt:
                        keep.append(j); foglalt = ki[j]
                keep = np.asarray(keep, np.int64)
                if len(keep) == 0:
                    continue
                be, ki, irany = be[keep], ki[keep], irany[keep]
                nyito = np.where(irany > 0, xa[be], xb[be])
                zaro = np.where(irany > 0, xb[ki], xa[ki])
                netto = 1e4 * irany * np.log(zaro / nyito)
                brutto = 1e4 * irany * np.log(xm[ki] / xm[be])
                df = pd.DataFrame({"nap": nap[be], "netto": netto, "brutto": brutto})
                a = df.groupby("nap").agg(n=("netto", "size"), netto=("netto", "sum"),
                                          brutto=("brutto", "sum")).reset_index()
                a["k"], a["h"], a["L"], a["ho"] = k, h, L, ho
                sorok.append(a)
    return h1, (pd.concat(sorok) if sorok else pd.DataFrame())


def _t_nap(x: pd.DataFrame, col: str) -> float:
    """napra klaszterezett t a kotesenkenti atlagra (arany-becslo)."""
    N = x.n.sum()
    m = x[col].sum() / N
    e = x[col] - m * x.n
    se = np.sqrt((e ** 2).sum() * len(x) / max(len(x) - 1, 1)) / N
    return float(m / se) if se > 0 else np.nan


def main():
    pd.set_option("display.width", 220)
    honapok = sorted(p.stem for p in (TICKS / KERESZT).glob("*.parquet")
                     if all((TICKS / s / p.name).exists() for s in LABAK))
    print(f"{len(honapok)} honap: {honapok[0]} .. {honapok[-1]}", flush=True)
    with ProcessPoolExecutor(8) as ex:
        res = [r for r in ex.map(_honap, honapok) if r is not None]
    H1 = pd.DataFrame([r[0] for r in res])
    D = pd.concat([r[1] for r in res], ignore_index=True)

    print("\n=== H1: kockazatmentes haromszog (mindharom bid/ask) ===")
    ossz = H1.mp.sum()
    print(f"   {H1.arb_mp.sum()} mp a {ossz}-bol ({100 * H1.arb_mp.sum() / ossz:.4f}%), "
          f"atlag {np.average(H1.arb_atl_bp, weights=H1.arb_mp.clip(lower=1)):.2f} bp; "
          f"dev szoras {H1.dev_szoras_bp.mean():.2f} bp, "
          f"kereszt-spread median {H1.spread_med_bp.median():.2f} bp")

    fel = "2025-05"
    sorok = []
    for (k, h, L), x in D.groupby(["k", "h", "L"]):
        N = x.n.sum()
        ho = x.groupby("ho").netto.sum()
        sorok.append({
            "k": k, "h": h, "L": L, "n": int(N),
            "brutto_bp": x.brutto.sum() / N, "netto_bp": x.netto.sum() / N,
            "t_netto": _t_nap(x, "netto"), "t_brutto": _t_nap(x, "brutto"),
            "ho+%": float((ho > 0).mean()),
            "elso_fel": x[x.ho < fel].netto.sum() / max(x[x.ho < fel].n.sum(), 1),
            "masod_fel": x[x.ho >= fel].netto.sum() / max(x[x.ho >= fel].n.sum(), 1)})
    T = pd.DataFrame(sorok)
    T.to_csv(KIMENET, index=False, sep=";", decimal=",")
    f = lambda v: f"{v:+.3f}"

    k0, h0, L0 = FO
    print(f"\n=== H2 ELSODLEGES (k={k0} bp, h={h0} s, keses={L0} s) + a 4. feltetel (keses=2) ===")
    print(T[(T.k == k0) & (T.h == h0) & T.L.isin([L0, 2])].to_string(index=False, float_format=f))
    print("\n=== H2: brutto (kozep->kozep) a kesessel — VAN-E egyaltalan elorejelzes ===")
    print(T[(T.k == k0)].pivot_table(index="h", columns="L", values="brutto_bp")
          .to_string(float_format=f))
    print("\n=== H2: legjobb netto konfiguraciok (masodlagos) ===")
    print(T.sort_values("netto_bp", ascending=False).head(10).to_string(index=False, float_format=f))
    print(f"   pozitiv netto: {(T.netto_bp > 0).sum()} / {len(T)}")
    print(f"\nteljes tabla: {KIMENET}")


# ── M1-mod: barmelyik haromszog a gyertya-fajlokbol ─────────────────────────
# (2026-09-28) A GBPUSD-hoz csak M1 gyertya van (tick nincs). Kitevo: +1 = a
# lab szorzodik, -1 = osztodik:  EURGBP = EURUSD / GBPUSD.
HAROMSZOG_M1 = {
    "EURJPY": {"EURUSD": +1, "USDJPY": +1},       # kontroll: a tickessel vetjuk ossze
    "EURGBP": {"EURUSD": +1, "GBPUSD": -1},
}


def m1_haromszog(kereszt: str, h_perc=(1, 5, 15, 60), k_bp=(0.5, 1.0, 2.0, 3.0)):
    """Keses + teljes oda-vissza „arbitrazs" M1 zarasokon (bid = close,
    ask = close + close_spread). A belepes a jel UTANI gyertya zarasan."""
    labak = HAROMSZOG_M1[kereszt]
    B = {}
    for s in [kereszt, *labak]:
        d = pd.read_parquet(_BP.bars_file("m1", s))
        d = d[~d.index.duplicated(keep="last")]
        sp = d.close_spread.where(d.close_spread > 0, d.avg_spread)
        B[s] = pd.DataFrame({"b": d.close, "a": d.close + sp})
    idx = B[kereszt].index
    for s in labak:
        idx = idx.intersection(B[s].index)
    X = {s: B[s].reindex(idx) for s in B}
    ib = np.ones(len(idx)); ia = np.ones(len(idx))
    for s, e in labak.items():
        b, a = X[s].b.to_numpy(), X[s].a.to_numpy()
        ib *= b if e > 0 else 1 / a
        ia *= a if e > 0 else 1 / b
    xb, xa = X[kereszt].b.to_numpy(), X[kereszt].a.to_numpy()
    xm, im = (xb + xa) / 2, (ib + ia) / 2
    dev = 1e4 * np.log(xm / im)
    spr = 1e4 * (xa - xb) / xm
    ok = np.isfinite(dev) & (spr > 0) & (spr <= 3 * np.nanmedian(spr))
    t = idx.to_numpy().astype("datetime64[m]").astype(np.int64)
    ev = idx.year.to_numpy()
    print(f"\n##### {kereszt} (M1): {len(idx)} kozos perc, {idx[0]:%Y-%m-%d} .. "
          f"{idx[-1]:%Y-%m-%d}; dev szoras {np.nanstd(dev[ok]):.2f} bp, "
          f"kereszt-spread median {np.nanmedian(spr[ok]):.2f} bp")

    # keses: csak a kereszten kereskedunk
    sorok = []
    for k in k_bp:
        jel = np.where(ok & (dev <= -k), 1, np.where(ok & (dev >= k), -1, 0))
        prev = np.concatenate([[0], jel[:-1]])
        ind = np.flatnonzero((jel != 0) & (jel != prev))
        for h in h_perc:
            be = ind + 1; ki = be + h
            v = ki < len(t)
            be, ki, ir = be[v], ki[v], jel[ind[v]]
            v = ((t[ki] - t[be]) == h) & ((t[be] - t[be - 1]) == 1)
            be, ki, ir = be[v], ki[v], ir[v]
            keep, fog = [], -1
            for j in range(len(be)):
                if be[j] > fog:
                    keep.append(j); fog = ki[j]
            be, ki, ir = be[keep], ki[keep], ir[keep]
            if len(be) < 30:
                continue
            nyito = np.where(ir > 0, xa[be], xb[be]); zaro = np.where(ir > 0, xb[ki], xa[ki])
            net = 1e4 * ir * np.log(zaro / nyito)
            br = 1e4 * ir * np.log(xm[ki] / xm[be])
            evp = pd.Series(net).groupby(ev[be]).mean()
            sorok.append({"k": k, "h_perc": h, "n": len(net), "brutto_bp": br.mean(),
                          "t_brutto": br.mean() / (br.std(ddof=1) / np.sqrt(len(br))),
                          "netto_bp": net.mean(), "ev+%": float((evp > 0).mean())})
    L = pd.DataFrame(sorok)
    f = lambda v: f"{v:+.3f}"
    print("\n  KESES (a kereszt utanhuz-e a labak utan):")
    print(L.to_string(index=False, float_format=f))
    print(f"  pozitiv netto: {(L.netto_bp > 0).sum()} / {len(L)}")

    # oda-vissza haromszog: nyitas, ha a rés a teljes bid/ask felett van,
    # zaras az elso percben, amikor a nyitott rés + a zaro rés >= 0, max H perc
    op_s, cl_s = 1e4 * np.log(xb / ia), -1e4 * np.log(xa / ib)
    op_l, cl_l = 1e4 * np.log(ib / xa), -1e4 * np.log(ia / xb)
    print("\n  ODA-VISSZA HAROMSZOG (mindharom lab, 1 perc keses):")
    for H in (15, 60, 240):
        eredm = []
        for op, cl in ((op_s, cl_s), (op_l, cl_l)):
            jel = ok & (op > 0)
            ind = np.flatnonzero(jel & ~np.concatenate([[False], jel[:-1]]))
            fog = -1
            for i in ind:
                b = i + 1
                if b <= fog or b + H >= len(t) or not ok[b]:
                    continue
                seg = op[b] + cl[b + 1:b + H + 1]
                z = np.flatnonzero(seg >= 0)
                k = z[0] if len(z) else H - 1
                eredm.append((op[b], seg[k], len(z) > 0)); fog = b + k + 1
        e = np.asarray(eredm) if eredm else np.zeros((0, 3))
        print(f"    H={H:>3} perc: {len(e):>6} kotes, nyito rés {e[:, 0].mean() if len(e) else 0:+.2f} bp, "
              f"netto {e[:, 1].mean() if len(e) else 0:+.3f} bp/kotes, "
              f"nullan felul zarult {e[:, 2].mean() if len(e) else 0:.1%}")


if __name__ == "__main__":
    if "--m1" in _sys.argv:
        for x in [a for a in _sys.argv[1:] if not a.startswith("--")] or list(HAROMSZOG_M1):
            m1_haromszog(x)
    else:
        main()

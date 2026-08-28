"""A FELHASZNALO INDIKATOR-LISTAJANAK SZISZTEMATIKUS ATVIZSGALASA.

A brief resze volt egy 40 elemu indikator-lista
(`Tananyagok/Indikator lista.md`). Eddig ebbol 9-et probaltunk ki (MA, Bollinger,
ATR, Williams %R, Momentum, Donchian, DMI, ADX, SuperTrend), 2 nem elerheto
(VIX, McClellan — kulso adat kellene). A tobbi 29-et SOHA nem neztuk meg.

Ez a modul azokat vizsgalja at, ugyanazzal a mercevel, amivel eddig minden mast:

  1. KOLTSEGGEL. A lab.simulate a valodi spreaddel dolgozik (bid barok,
     BUY ask-on nyit / bid-en zar). Nincs "brutto" illuzio.
  2. LONG ES SHORT KULON. Az elfogadashoz MINDKETTONEK pozitivnak kell lennie.
     Egy sodrodas-alapu "el" ezen bukik el — lasd [[drift-equals-financing]].
  3. EVENKENTI KONZISZTENCIA. Egy szabaly, ami 14 evbol 3-ban nyer nagyot,
     nem szabaly, hanem szerencse.
  4. TOBBSZOROS TESZTELES. Sok szabalyt probalunk -> a legjobb MINDIG jonak
     latszik. Ezert a kuszob |t|>=3, es a jelentesben ott van, hany tesztbol.

VARAKOZAS (elore rogzitve, hogy utolag ne lehessen atirni): a korabbi meresek
szerint a korlat a KOLTSEG, nem az indikator-valasztas — a mikrostruktura-teszt
mar nem is arjelet nezett, megis ugyanaz jott ki. Ezert azt varom, hogy ezek is
elbuknak. De ez joslat, nem meres.
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

SYMS = ["Ger40", "UsaInd", "UsaTec", "GOLD", "USDJPY"]
TF = 15                      # M15 jelzes, M1 vegrehajtas
SL_ATR = 1.5
TP_RR = 2.0
MAX_HOLD = 480               # perc


# ── indikatorok (numpy, mind a listarol) ────────────────────────────────────

def _roll(a, n, fn):
    s = pd.Series(a)
    return getattr(s.rolling(n, min_periods=n), fn)().to_numpy()


def macd(c, f=12, s=26, sig=9):
    m = lab.ema(c, f) - lab.ema(c, s)
    return m, lab.ema(m, sig)


def stoch(h, l, c, n=14, d=3):
    hh, ll = _roll(h, n, "max"), _roll(l, n, "min")
    k = 100 * (c - ll) / np.where(hh - ll > 0, hh - ll, np.nan)
    return k, _roll(k, d, "mean")


def cci(h, l, c, n=20):
    tp = (h + l + c) / 3
    ma = _roll(tp, n, "mean")
    md = pd.Series(tp).rolling(n, min_periods=n).apply(
        lambda x: np.abs(x - x.mean()).mean(), raw=True).to_numpy()
    return (tp - ma) / np.where(md > 0, 0.015 * md, np.nan)


def keltner(h, l, c, n=20, k=2.0):
    m = lab.ema(c, n)
    a = lab.atr(h, l, c, n)
    return m - k * a, m, m + k * a


def aroon(h, l, n=25):
    up = pd.Series(h).rolling(n + 1, min_periods=n + 1).apply(
        lambda x: 100 * (n - (len(x) - 1 - int(np.argmax(x)))) / n, raw=True)
    dn = pd.Series(l).rolling(n + 1, min_periods=n + 1).apply(
        lambda x: 100 * (n - (len(x) - 1 - int(np.argmin(x)))) / n, raw=True)
    return up.to_numpy(), dn.to_numpy()


def vortex(h, l, c, n=14):
    tr = np.abs(h - l)
    pc = np.concatenate([[np.nan], c[:-1]])
    tr = np.maximum(tr, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    pl = np.concatenate([[np.nan], l[:-1]])
    ph = np.concatenate([[np.nan], h[:-1]])
    vp, vm = np.abs(h - pl), np.abs(l - ph)
    s = _roll(tr, n, "sum")
    return _roll(vp, n, "sum") / s, _roll(vm, n, "sum") / s


def hull(c, n=20):
    def wma(a, k):
        w = np.arange(1, k + 1, dtype=float)
        return pd.Series(a).rolling(k, min_periods=k).apply(
            lambda x: np.dot(x, w) / w.sum(), raw=True).to_numpy()
    return wma(2 * wma(c, n // 2) - wma(c, n), max(2, int(np.sqrt(n))))


def roc(c, n=12):
    p = np.concatenate([np.full(n, np.nan), c[:-n]])
    return 100 * (c - p) / p


def trix(c, n=15):
    e = lab.ema(lab.ema(lab.ema(c, n), n), n)
    p = np.concatenate([[np.nan], e[:-1]])
    return 100 * (e - p) / p


def psar(h, l, af0=0.02, afmax=0.2):
    n = len(h)
    ps = np.full(n, np.nan)
    bull, af, ep, sar = True, af0, h[0], l[0]
    for i in range(1, n):
        sar = sar + af * (ep - sar)
        if bull:
            if l[i] < sar:
                bull, sar, ep, af = False, ep, l[i], af0
            elif h[i] > ep:
                ep, af = h[i], min(af + af0, afmax)
        else:
            if h[i] > sar:
                bull, sar, ep, af = True, ep, h[i], af0
            elif l[i] < ep:
                ep, af = l[i], min(af + af0, afmax)
        ps[i] = sar if not bull else -sar        # elojel = irany
    return ps


def obv(c, v):
    d = np.sign(np.concatenate([[0.0], np.diff(c)]))
    return np.cumsum(d * v)


def force_index(c, v, n=13):
    return lab.ema(np.concatenate([[0.0], np.diff(c)]) * v, n)


def elder(h, l, c, n=13):
    e = lab.ema(c, n)
    return h - e, l - e                          # bika-ero, medve-ero


def heikin(o, h, l, c):
    hc = (o + h + l + c) / 4
    ho = np.empty_like(hc)
    ho[0] = (o[0] + c[0]) / 2
    for i in range(1, len(hc)):
        ho[i] = (ho[i - 1] + hc[i - 1]) / 2
    return ho, hc


def ichimoku(h, l, n1=9, n2=26):
    conv = (_roll(h, n1, "max") + _roll(l, n1, "min")) / 2
    base = (_roll(h, n2, "max") + _roll(l, n2, "min")) / 2
    return conv, base


def stc(c, f=23, s=50, n=10):
    m = lab.ema(c, f) - lab.ema(c, s)
    lo, hi = _roll(m, n, "min"), _roll(m, n, "max")
    k = 100 * (m - lo) / np.where(hi - lo > 0, hi - lo, np.nan)
    d = lab.ema(k, 3)
    lo2, hi2 = _roll(d, n, "min"), _roll(d, n, "max")
    return 100 * (d - lo2) / np.where(hi2 - lo2 > 0, hi2 - lo2, np.nan)


def chande(c, n=14):
    d = np.concatenate([[0.0], np.diff(c)])
    up = _roll(np.where(d > 0, d, 0.0), n, "sum")
    dn = _roll(np.where(d < 0, -d, 0.0), n, "sum")
    return 100 * (up - dn) / np.where(up + dn > 0, up + dn, np.nan)


def tsi(c, r=25, s=13):
    d = np.concatenate([[0.0], np.diff(c)])
    return 100 * (lab.ema(lab.ema(d, r), s) /
                  np.where(lab.ema(lab.ema(np.abs(d), r), s) > 0,
                           lab.ema(lab.ema(np.abs(d), r), s), np.nan))


def alligator(c):
    return lab.sma(c, 13), lab.sma(c, 8), lab.sma(c, 5)   # allkapocs/fog/ajak


# ── a szabalyok: (nev, fuggveny -> +1/-1/0 jelzes soronkent) ────────────────

def _x_up(a, b):
    """a keresztezi b-t FELFELE (elozo bar alatt, ez folött)."""
    pa = np.concatenate([[np.nan], a[:-1]])
    pb = np.concatenate([[np.nan], b[:-1]])
    return (pa <= pb) & (a > b)


def build_rules(d):
    o = d["open"].to_numpy(float); h = d["high"].to_numpy(float)
    l = d["low"].to_numpy(float);  c = d["close"].to_numpy(float)
    v = d["volume"].to_numpy(float)
    R = {}

    m, ms = macd(c)
    R["MACD kereszt"] = np.where(_x_up(m, ms), 1, np.where(_x_up(ms, m), -1, 0))
    R["MACD nulla"] = np.where(_x_up(m, np.zeros_like(m)), 1,
                               np.where(_x_up(np.zeros_like(m), m), -1, 0))

    r = lab.rsi(c, 14)
    R["RSI 30/70 fordulo"] = np.where(_x_up(r, np.full_like(r, 30.)), 1,
                                      np.where(_x_up(np.full_like(r, 70.), r), -1, 0))
    R["RSI 50 atlepes"] = np.where(_x_up(r, np.full_like(r, 50.)), 1,
                                   np.where(_x_up(np.full_like(r, 50.), r), -1, 0))

    k, dd = stoch(h, l, c)
    R["Stoch kereszt"] = np.where(_x_up(k, dd) & (k < 30), 1,
                                  np.where(_x_up(dd, k) & (k > 70), -1, 0))

    ci = cci(h, l, c)
    R["CCI +-100"] = np.where(_x_up(ci, np.full_like(ci, -100.)), 1,
                              np.where(_x_up(np.full_like(ci, 100.), ci), -1, 0))

    kl, km, ku = keltner(h, l, c)
    R["Keltner kitores"] = np.where(_x_up(c, ku), 1, np.where(_x_up(kl, c), -1, 0))
    R["Keltner visszateres"] = np.where(_x_up(c, kl), 1, np.where(_x_up(ku, c), -1, 0))

    au, ad = aroon(h, l)
    R["Aroon kereszt"] = np.where(_x_up(au, ad), 1, np.where(_x_up(ad, au), -1, 0))

    vp, vm = vortex(h, l, c)
    R["Vortex kereszt"] = np.where(_x_up(vp, vm), 1, np.where(_x_up(vm, vp), -1, 0))

    hu = hull(c, 20)
    R["Hull irany"] = np.where(_x_up(c, hu), 1, np.where(_x_up(hu, c), -1, 0))

    rc = roc(c, 12)
    R["ROC nulla"] = np.where(_x_up(rc, np.zeros_like(rc)), 1,
                              np.where(_x_up(np.zeros_like(rc), rc), -1, 0))

    tx = trix(c, 15)
    R["TRIX nulla"] = np.where(_x_up(tx, np.zeros_like(tx)), 1,
                               np.where(_x_up(np.zeros_like(tx), tx), -1, 0))

    ps = psar(h, l)
    sg = np.sign(ps)
    psg = np.concatenate([[np.nan], sg[:-1]])
    R["Parabolic SAR fordulo"] = np.where((psg < 0) & (sg > 0), 1,
                                          np.where((psg > 0) & (sg < 0), -1, 0))

    ob = obv(c, v)
    obm = lab.sma(ob, 20)
    R["OBV trend"] = np.where(_x_up(ob, obm), 1, np.where(_x_up(obm, ob), -1, 0))

    fi = force_index(c, v, 13)
    R["Force Index nulla"] = np.where(_x_up(fi, np.zeros_like(fi)), 1,
                                      np.where(_x_up(np.zeros_like(fi), fi), -1, 0))

    be, se = elder(h, l, c)
    R["Elder Ray"] = np.where((se < 0) & (be > 0) & (c > lab.ema(c, 13)), 1,
                              np.where((be > 0) & (se < 0) & (c < lab.ema(c, 13)), -1, 0))

    ho, hc = heikin(o, h, l, c)
    hs = np.sign(hc - ho)
    phs = np.concatenate([[np.nan], hs[:-1]])
    R["Heikin Ashi fordulo"] = np.where((phs < 0) & (hs > 0), 1,
                                        np.where((phs > 0) & (hs < 0), -1, 0))

    cv, bs = ichimoku(h, l)
    R["Ichimoku TK kereszt"] = np.where(_x_up(cv, bs), 1, np.where(_x_up(bs, cv), -1, 0))

    st = stc(c)
    R["STC 25/75"] = np.where(_x_up(st, np.full_like(st, 25.)), 1,
                              np.where(_x_up(np.full_like(st, 75.), st), -1, 0))

    cm = chande(c, 14)
    R["Chande +-50"] = np.where(_x_up(cm, np.full_like(cm, -50.)), 1,
                                np.where(_x_up(np.full_like(cm, 50.), cm), -1, 0))

    ts = tsi(c)
    R["TSI nulla"] = np.where(_x_up(ts, np.zeros_like(ts)), 1,
                              np.where(_x_up(np.zeros_like(ts), ts), -1, 0))

    ja, fo, aj = alligator(c)
    R["Alligator ebredes"] = np.where(_x_up(aj, ja), 1, np.where(_x_up(ja, aj), -1, 0))

    return R


def main():
    pd.set_option("display.width", 220)
    syms = _sys.argv[1:] or SYMS
    minden = []
    for sym in syms:
        m1 = lab.load_m1(sym)
        d15 = lab.resample(m1, TF)
        ps = None
        try:
            import json
            cfgp = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
            ps = float(cfgp["pairs"][sym]["point_size"])
        except Exception:
            ps = 0.01
        a15 = lab.atr(d15["high"].to_numpy(float), d15["low"].to_numpy(float),
                      d15["close"].to_numpy(float), 14)
        rules = build_rules(d15)
        # az M15 bar zarasa -> a hozza tartozo M1 bar indexe
        pos = m1.index.searchsorted(d15.index) + TF - 1
        pos = np.clip(pos, 0, len(m1) - 1)
        print(f"=== {sym}: {len(d15)} M15 bar, {len(rules)} szabaly ===", flush=True)
        for nev, sig in rules.items():
            for irany, jel in (("LONG", 1), ("SHORT", -1)):
                sel = np.flatnonzero((sig == jel) & np.isfinite(a15) & (a15 > 0))
                sel = sel[(sel > 60) & (sel < len(d15) - 1)]
                if len(sel) < 200:
                    continue
                idx = pos[sel]
                slp = (SL_ATR * a15[sel]) / ps
                tr = lab.simulate(m1, idx, np.full(len(idx), jel, dtype=int),
                                  slp, slp * TP_RR, ps, max_hold=MAX_HOLD)
                if len(tr) < 100:
                    continue
                s = lab.stats(tr, label=f"{sym} | {nev} | {irany}")
                s.update({"sym": sym, "szabaly": nev, "irany": irany})
                minden.append(s)
    t = pd.DataFrame(minden)
    if t.empty:
        print("nincs eredmeny"); return
    out = ROOT / "data" / "indicator_screen.csv"
    t.to_csv(out, index=False)

    print("\n" + "=" * 78)
    print("=== AHOL MINDKET IRANY POZITIV (ez az elfogadas elso felteteke) ===")
    piv = t.pivot_table(index=["sym", "szabaly"], columns="irany",
                        values="R/trade")
    if {"LONG", "SHORT"} <= set(piv.columns):
        jo = piv[(piv.LONG > 0) & (piv.SHORT > 0)]
        print(jo.to_string(float_format=lambda v: f"{v:+.4f}") if len(jo)
              else "   NINCS ilyen (sym, szabaly) par.")
    print(f"\n=== |t| >= 3 (a {len(t)} teszt miatt szigoru kuszob) ===")
    s = t[t.t.abs() >= 3].sort_values("t", key=abs, ascending=False)
    cols = ["sym", "szabaly", "irany", "n", "R/trade", "PF", "t"]
    print(s[cols].head(20).to_string(index=False,
          float_format=lambda v: f"{v:+.4f}") if len(s) else "   NINCS ilyen.")
    print(f"\n   osszesen {len(t)} teszt, pozitiv R/trade: "
          f"{int((t['R/trade'] > 0).sum())}, |t|>=3: {int((t.t.abs() >= 3).sum())}")
    print(f"\nteljes tabla: {out}")


if __name__ == "__main__":
    main()

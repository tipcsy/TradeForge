"""A `trend_pullback` belepoje a HOSSZU mintan, az elfogadasi protokoll szerint.

⚠ MIERT: a felhasznalo a charton egy jelzes-csomot latott egy nagy elmozdulas
korul, es azt kerdezte, nem a GAP rontotta-e el az indikatorokat. A rovid ablak
erre nem tud valaszolni -- a README sajat pelda ja szerint egy 2 eves mintan
+0,100 R/kotes latszott, a 14 evesen -0,038 (t = -2,94).

AZ ELFOGADASI PROTOKOLL (a README-bol, elore rogzitve):
  1. t >= 2 az osszevont mintan,
  2. az evek legalabb 60%-aban pozitiv,
  3. legalabb 3 instrumentumon pozitiv.

A vegrehajtas a kutato-labor szimulatoraval megy (`lab.simulate`), tehat a
spread-kezeles, az `one_at_a_time` (egy par = egy pozicio) es az R-szamitas
UGYANAZ, mint a tobbi meresnel.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import logging
logging.disable(logging.INFO)

import numpy as np
import pandas as pd

from tools.research import lab
import strategies.trend_pullback as T
from strategy import get_strategy_by_name
from strategy.settings import config_for_strategy, load_config
from trading.live_trader import default_params, strategy_params

SN = "trend_pullback"
st = get_strategy_by_name(SN)
cfg = load_config("config.json")
cs = config_for_strategy(cfg, SN)

# Csak a MELY elozmenyu instrumentumok (a rovid mintan nincs ertelme evenkenti
# konzisztenciat merni).
MIN_EV = 4


def _vetit_float(index, src, tf_min: int, values: np.ndarray) -> np.ndarray:
    """Magasabb keret FLOAT sorozata az M1 sorokra — look-ahead nelkul.

    Ugyanaz a logika, mint a `trend_pullback._map_to` (a ZARASI idore keresunk,
    tehat a jovot nem hasznaljuk), de az ERTEKET megtartja. A strategiaban a
    `_map_to` maszkokra keszult (`dtype=bool`) — egy float sorozat ott 1.0-ra
    kerekedne.
    """
    zaras = src + pd.Timedelta(minutes=tf_min)
    j = np.searchsorted(zaras, index, side="right") - 1
    out = np.full(len(index), np.nan)
    ok = j >= 0
    out[ok] = np.asarray(values, dtype=float)[j[ok]]
    return out


def parameterek(sym: str) -> dict:
    p = strategy_params(sym, SN, cs, fallback=default_params(st, cs))
    pc = (cfg.get("pairs") or {}).get(sym) or {}
    return {**p, "symbol": sym,
            "point_size": pc.get("point_size", 0.01)}


def merj(sym: str):
    df = lab.load_m1(sym)
    evek = df.index.year.nunique()
    if evek < MIN_EV:
        return None
    p = parameterek(sym)
    pont = float(p["point_size"])

    # A JEL: ugyanaz a `signal_column`, amit a motor hasznal -- nem masolat.
    sig = T.signal_column(df, p)
    el = np.where(sig[1:] & ~sig[:-1])[0] + 1
    if len(el) < 30:
        return None

    # A MERET: sl_atr_mult x M15 ATR (a strategia `sl_tp_points`-ja), az M1
    # sorokra vetitve. A `_map_to` a ZARASI idore keres -> nincs look-ahead.
    d15 = lab.resample(df, 15)
    a15 = lab.atr(d15["high"].to_numpy(float), d15["low"].to_numpy(float),
                  d15["close"].to_numpy(float),
                  int(p.get("atr_period", 14) or 14))
    # ⚠ A `T._map_to` MASZK-vetito: `dtype=bool` tomböt ad, tehat egy ATR-sort
    # NEMAN 1.0-ra kerekitene (a stop 1,5 ATR helyett 1,5 AR-EGYSEG lenne).
    # Elso nekifutasra pontosan ez tortent: a veletlen belepok "-0,632 R"-t
    # adtak, ami lehetetlen -- a null-teszt fogta meg.
    atr_m1 = _vetit_float(df.index, d15.index, 15, a15)

    sl_pts = (float(p.get("sl_atr_mult", 1.5) or 1.5)
              * np.nan_to_num(atr_m1[el], nan=0.0) / pont)
    tp_pts = sl_pts * float(p.get("tp_rr_ratio", 2.0) or 2.0)
    jo = sl_pts > 0
    el, sl_pts, tp_pts = el[jo], sl_pts[jo], tp_pts[jo]
    if len(el) < 30:
        return None

    tr = lab.simulate(df, el, np.ones(len(el), dtype=int), sl_pts, tp_pts,
                      point_size=pont, one_at_a_time=True)
    return df, tr


def evenkent(df, tr):
    """Evenkenti R -- a protokoll 2. feltetelehez."""
    if not len(tr):
        return {}
    ev = pd.DatetimeIndex(df.index[tr["i_open"]]).year
    return pd.Series(tr["r"], index=ev).groupby(level=0).sum().to_dict()


print("A `trend_pullback` belepoje a HOSSZU mintan")
print("(a kutato-labor szimulatoraval; egy par = egy pozicio)\n")
print(f"{'instrumentum':<12} {'ev':>4} {'kotes':>6} {'R':>9} {'R/kotes':>9} "
      f"{'talalat':>8} {'PF':>6} {'t':>7}")
print("-" * 68)

osszes_r = []
poz_instr = 0
n_instr = 0
ev_osszes = {}
for sym in ("GOLD", "USDJPY", "Ger40", "UsaTec", "UsaInd", "Usa500", "EURUSD"):
    if not (ROOT / "data" / "m1" / f"{sym}.parquet").exists():
        continue
    try:
        res = merj(sym)
    except Exception as ex:
        print(f"{sym:<12} HIBA: {type(ex).__name__}: {ex}")
        continue
    if res is None:
        continue
    df, tr = res
    if not len(tr):
        continue
    s = lab.stats(tr, df, sym)
    n_instr += 1
    if s["R"] > 0:
        poz_instr += 1
    osszes_r.append(tr["r"])
    print(f"{sym:<12} {df.index.year.nunique():>4} {s['n']:>6} {s['R']:>9.1f} "
          f"{s['R/trade']:>9.3f} {s['win%']:>7.1f}% {s['PF']:>6.2f} "
          f"{s.get('t', float('nan')):>7.2f}")
    for e, r in evenkent(df, tr).items():
        ev_osszes[e] = ev_osszes.get(e, 0.0) + r

print("-" * 68)
if osszes_r:
    r = np.concatenate(osszes_r)
    t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r))) if r.std() > 0 else 0.0
    print(f"{'OSSZEVONT':<12} {'':>4} {len(r):>6} {r.sum():>9.1f} "
          f"{r.mean():>9.3f} {'':>8} {'':>6} {t:>7.2f}")
    print()
    print("Evenkent (osszevont R):")
    for e in sorted(ev_osszes):
        jel = "+" if ev_osszes[e] > 0 else " "
        print(f"   {e}  {ev_osszes[e]:>+8.1f} {jel}")
    poz_ev = sum(1 for v in ev_osszes.values() if v > 0)
    print()
    print("AZ ELFOGADASI PROTOKOLL:")
    print(f"   1. t >= 2                     : t = {t:+.2f}   "
          f"{'TELJESUL' if t >= 2 else 'NEM'}")
    print(f"   2. az evek >= 60%-a pozitiv   : {poz_ev}/{len(ev_osszes)} = "
          f"{100*poz_ev/max(1,len(ev_osszes)):.0f}%   "
          f"{'TELJESUL' if poz_ev >= 0.6*len(ev_osszes) else 'NEM'}")
    print(f"   3. >= 3 instrumentumon pozitiv: {poz_instr}/{n_instr}   "
          f"{'TELJESUL' if poz_instr >= 3 else 'NEM'}")

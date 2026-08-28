"""ELORE KISZAMOLT KIMENETEK — ez teszi futtathatova a milliós kereseset.

A felhasznalo eszrevetele (2026-08-28): 40 indikator x 6 idosik x parameterek x
egyuttallas = tobb millio kombinacio, es abbol csak 23 nyers keresztezest
neztem meg egyetlen idosikon. Igaza volt.

A NAIV megkozelites (kombinaciónkent egy szimulacio) nem jarhato: egy szimulacio
tobb masodperc, egymillio kombinacio evekig futna.

A TRUKK: a kimenet NEM fugg a szabalytol. Ha egy adott M1 gyertyan belepek LONG
iranyba 1,5xATR stoppal, akkor az eredmeny egyertelmuen adott — fuggetlenul
attol, MELYIK szabaly kuldott oda. Tehat:

  1. EGYSZER kiszamoljuk MINDEN gyertyara mindket iranyban a kimenetet (R-ben).
  2. Utana barmely szabaly = egy BOOLEAN MASZK a gyertyakon,
     a varhato erteke = a kimenetek atlaga a maszk alatt.

Igy egy kombinacio kiertekelese numpy-atlag: mikroszekundum. Millio kombinacio
percek alatt.

KORLAT, amit ki kell mondani: ez a "jelzes-minoseget" meri, nem a portfoliot.
Az egymast atfedo kotesek (one_at_a_time) itt nincsenek kizarva — minden gyertya
onalloan ertekelodik. Ez a HELYES modszer szabalyok osszehasonlitasara, de a
vegso, elfogadott jeloltet at kell vinni a valodi motorra.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import json

import numpy as np
import pandas as pd

import lab

CACHE = ROOT / "data" / "outcomes"
SL_ATR = 1.5            # stop = ennyiszer az M15 ATR
TP_RR = 2.0             # celar R-ben (0 = nincs TP)
MAX_HOLD = 480          # perc
# A kimeneteket az M5 racson szamoljuk: ez a legfinomabb idosik, amit a kereses
# hasznal, es 5x kevesebb szimulacio, mint a teljes M1 (a GOLD 4,7M gyertya).
STEP_MIN = 5


def _point_size(sym: str) -> float:
    try:
        c = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        return float(c["pairs"][sym]["point_size"])
    except Exception:
        return 0.01


def build(sym: str, force: bool = False) -> pd.DataFrame:
    """Minden M1 gyertyara: a LONG es a SHORT belepo kimenete R-ben.

    A stop-tavolsag az M15 ATR-bol jon (ez a projekt bevett merteke), es minden
    M1 gyertyara az EPPEN ERVENYES (mar lezart) M15 ATR-t hasznaljuk — nincs
    elore-tekintes.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    dst = CACHE / f"{sym}.parquet"
    if dst.exists() and not force:
        return pd.read_parquet(dst)

    m1 = lab.load_m1(sym)
    d15 = lab.resample(m1, 15)
    ps = _point_size(sym)
    a15 = lab.atr(d15["high"].to_numpy(float), d15["low"].to_numpy(float),
                  d15["close"].to_numpy(float), 14)

    # minden M1 gyertyahoz a LEGUTOBB LEZART M15 bar ATR-je (nincs look-ahead:
    # a d15 bar cimkeje a NYITO ideje, tehat +15 perccel zar)
    zaras = d15.index + pd.Timedelta(minutes=15)
    j = np.searchsorted(zaras, m1.index, side="right") - 1
    ok = j >= 0
    atr_m1 = np.full(len(m1), np.nan)
    atr_m1[ok] = a15[j[ok]]

    racs = (m1.index.minute % STEP_MIN == 0)          # M5 hatarok
    hasznos = np.flatnonzero(np.isfinite(atr_m1) & (atr_m1 > 0) & racs)
    hasznos = hasznos[hasznos < len(m1) - 2]
    slp = (SL_ATR * atr_m1[hasznos]) / ps

    out = {"i": hasznos}
    for nev, jel in (("long", 1), ("short", -1)):
        tr = lab.simulate(m1, hasznos, np.full(len(hasznos), jel, dtype=np.int8),
                          slp, slp * TP_RR, ps, max_hold=MAX_HOLD,
                          one_at_a_time=False)
        # one_at_a_time=False + slp>0 mindenhol -> MINDEN belepo rogzul.
        # Ha megsem, a maszkok elcsusznanak a kimenetektol -> inkabb allj meg.
        if len(tr) != len(hasznos):
            raise SystemExit(f"{sym}/{nev}: {len(tr)} kimenet {len(hasznos)} "
                             f"belepore — az 1:1 megfeleltetes serult")
        rr = tr["r"].astype(float)
        out[nev] = rr
        print(f"   {sym} {nev}: {len(rr)} kimenet, atlag R {np.nanmean(rr):+.4f}",
              flush=True)

    d = pd.DataFrame(out)
    d["ido"] = m1.index[hasznos]
    d["sl_pts"] = slp
    d.to_parquet(dst, index=False)
    return d


def main():
    for sym in (_sys.argv[1:] or ["Ger40", "UsaInd", "UsaTec", "GOLD", "USDJPY"]):
        print(f"=== {sym} ===", flush=True)
        d = build(sym)
        print(f"   {len(d)} gyertya, {d.ido.min()} .. {d.ido.max()}")
        for k in ("long", "short"):
            v = d[k].to_numpy(float)
            v = v[np.isfinite(v)]
            t = v.mean() / (v.std(ddof=1) / np.sqrt(len(v)))
            print(f"   {k:6s} atlag R {v.mean():+.4f}  t {t:+7.1f}  n {len(v)}")


if __name__ == "__main__":
    main()

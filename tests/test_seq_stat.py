"""A SORREND-MÁTRIX STATISZTIKÁJA — tools/research/seq_stat.py.

Miért van ez a kutató-modul tesztelve, amikor a `tools/research` többi része
nem: mert itt két olyan hiba lakik, ami CSENDBEN rossz eredményt ad, nem
elszállást.

  1. IDŐEGYSÉG. A `DatetimeIndex.asi8` az index saját felbontásában ad számot,
     és egy Parquet-körút után ez lehet mikroszekundum. A 15 perces ablakból
     így 15 000 perces lett — a mérés lefutott, csak mást mért. (Megtörtént,
     2026-09-19.)

  2. ÁTFEDŐ KÖTÉSEK t-JE. Az `outcomes.py` minden rácspontot önállóan értékel,
     a tartás viszont 96 rácspontnyi. A sima t ilyenkor nagyságrenddel
     túlbecsüli a bizonyítékot — a napra klaszterezett t nem.

Futtatás:  python tests/test_seq_stat.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "research"))

from core import applog
applog.harden_console()

import numpy as np
import pandas as pd

import seq_stat as ST

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ══ 1. IDŐEGYSÉG-FÜGGETLENSÉG ═════════════════════════════════════════════
ido_ns = pd.date_range("2024-01-01", periods=600, freq="5min", tz="UTC")
ido_us = pd.DatetimeIndex(ido_ns).as_unit("us")

check("ns(): a mikroszekundumos index is nanoszekundumot ad",
      np.array_equal(ST.ns(ido_ns), ST.ns(ido_us)))

for egys, idx in (("ns", ido_ns), ("us", ido_us)):
    lo = ST.ablak_kezdet(idx, 15)
    tav = (ST.ns(idx) - ST.ns(idx)[lo]) / 60e9
    check(f"ablak_kezdet(15 perc) a(z) {egys} indexen legfeljebb 15 perc",
          tav.max() <= 15 + 1e-9, f"max {tav.max():.1f} perc")
    check(f"ablak_kezdet(15 perc) a(z) {egys} indexen 3 rácslépés",
          int(np.median(np.arange(len(lo)) - lo)) == 3)

check("ablak_onteszt jelzi a rendben állapotot", ST.ablak_onteszt(ido_us, 60))

# ══ 2. LYUKAS RÁCS (hétvége) — idő, nem lépésszám ═════════════════════════
lyukas = pd.DatetimeIndex(
    list(pd.date_range("2024-01-05 20:00", periods=6, freq="5min", tz="UTC"))
    + list(pd.date_range("2024-01-08 08:00", periods=6, freq="5min", tz="UTC")))
lo = ST.ablak_kezdet(lyukas, 60)
check("a hétvégi lyukon NEM néz át a 60 perces ablak",
      lo[6] == 6, f"lo[6]={lo[6]} (a hétfői első pont önmaga)")

# ══ 3. ELŐZMÉNY-SZÁMLÁLÁS ═════════════════════════════════════════════════
a = np.zeros(20, bool)
a[[2, 10]] = True
el = ST.Elozmeny(a)
racs = pd.date_range("2024-01-01", periods=20, freq="5min", tz="UTC")
lo15 = ST.ablak_kezdet(racs, 15)          # 3 rácslépés
b = np.arange(20)
m = el.elozve(b, lo15)
check("az A esemény a SAJÁT pontját nem előzi meg", not m[2] and not m[10])
check("A a következő 3 rácsponton előzmény", m[3] and m[4] and m[5])
check("a 4. rácsponton már nem", not m[6])
check("egyutt(): lag = 0 az esemény saját pontja",
      el.egyutt(a, np.array([2, 3]))[0] and not el.egyutt(a, np.array([2, 3]))[1])

# ══ 4. KLASZTEREZETT t ════════════════════════════════════════════════════
rng = np.random.default_rng(0)
alap = rng.standard_normal(200)
v = np.repeat(alap, 20)                    # minden nap 20x ugyanaz az érték
nap = np.repeat(np.arange(200), 20)
mu, t_kl, n = ST.t_klaszter(v, nap)
t_naiv = v.mean() / (v.std(ddof=1) / np.sqrt(len(v)))
check("a klaszterezett t kisebb a naivnál átfedő mintán",
      abs(t_kl) < abs(t_naiv) / 3, f"naiv {t_naiv:+.2f} vs klaszter {t_kl:+.2f}")
check("a klaszterezett t közel a független napok t-jéhez",
      abs(abs(t_kl) - abs(alap.mean() / (alap.std(ddof=1) / np.sqrt(200)))) < 0.1)

# ══ 5. ÉVENKÉNTI KONZISZTENCIA ════════════════════════════════════════════
ev = pd.DatetimeIndex(["2020-06-01"] * 10 + ["2021-06-01"] * 10
                      + ["2022-06-01"] * 10, tz="UTC")
vv = np.concatenate([np.full(10, 1.0), np.full(10, -1.0), np.full(10, 1.0)])
ar, db = ST.evek_pozitiv(vv, ev)
check("evek_pozitiv: 3-ból 2 év pozitív", abs(ar - 2 / 3) < 1e-9 and db == 3)

# ══ 6. SPEARMAN SCIPY NÉLKÜL ══════════════════════════════════════════════
x = np.array([1.0, 2, 3, 4, 5])
check("spearman: tökéletes monoton = +1", abs(ST.spearman(x, x ** 3) - 1) < 1e-9)
check("spearman: fordított = -1", abs(ST.spearman(x, -x ** 3) + 1) < 1e-9)

# ══ ÖSSZESÍTÉS ════════════════════════════════════════════════════════════
jo = sum(results)
print(f"\n{jo}/{len(results)} teszt PASS")
sys.exit(0 if jo == len(results) else 1)

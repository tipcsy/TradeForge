"""IDŐBÉLYEG-MÉRTÉKEGYSÉG — core/epoch.py, és az ŐR, hogy ne jöjjön vissza.

⚠ A HIBA, AMIÉRT EZ A TESZT VAN (2026-09-19). A `DatetimeIndex.values.astype
("int64")` / `.asi8` / `.view("int64")` az index SAJÁT felbontását adja, a
pandas 2.0 óta pedig ez nem mindig nanoszekundum (a pandas 3 `date_range`-e
mikroszekundumot ad). A motorban a `Timedelta.value` viszont MINDIG ns.

A következmény nem elszállás, hanem NÉMÁN rossz szám. Mérve, pandas 3.0.6-tal,
a projekt saját regressziós tesztjével (`test_backtest_hot_path.py`): a
gyorsított backteszt-út **197 jelzés helyett 0-t** adott, mert a
`_t15_ns[...] + _delta_ns <= _t1_ns[i]` feltétel soha nem teljesült. Ugyanez
vitte el a `strategy/visual.py` KÖTNE/KIMARAD jelölését és a `signal_series`-t.

KÉT DOLGOT mér ez a fájl:
  1. az átváltás felbontástól függetlenül ugyanazt adja, ÉS ns-es indexen
     BITRE a régi kódot (tehát a meglévő eredmények nem változnak);
  2. ŐR: a motor egyik modulja se csinálja újra kézzel.

Futtatás:  python tests/test_epoch.py
"""
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import numpy as np
import pandas as pd

from core import epoch

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ══ 1. FELBONTÁS-FÜGGETLENSÉG ═════════════════════════════════════════════
alap = pd.date_range("2026-01-01", periods=4, freq="15min", tz="UTC")
minta = {u: alap.as_unit(u) for u in ("s", "ms", "us", "ns")}

for u, idx in minta.items():
    d = epoch.ns(idx)
    check(f"ns(): a(z) {u} felbontású index is ns-t ad",
          d.dtype == np.int64 and int(d[1] - d[0]) == 900_000_000_000,
          f"delta={int(d[1] - d[0])}")
    check(f"sec(): a(z) {u} felbontású indexen 900 s a lépés",
          int(epoch.sec(idx)[1] - epoch.sec(idx)[0]) == 900)

check("ns(): minden felbontás UGYANAZT a tömböt adja",
      all(np.array_equal(epoch.ns(minta["ns"]), epoch.ns(v))
          for v in minta.values()))

# ══ 2. NS-ES INDEXEN BITRE A RÉGI VISELKEDÉS ══════════════════════════════
# Ez a feltétele annak, hogy a javítás ne mozdítson el semmilyen korábbi
# eredményt: ahol eddig is ns volt, ott a szám azonos.
ns_idx = minta["ns"]
check("ns(): ns-es indexen bitre = a régi `.values.astype(int64)`",
      np.array_equal(epoch.ns(ns_idx), ns_idx.values.astype("int64")))
check("sec(): ns-es indexen bitre = a régi `// 1_000_000_000`",
      np.array_equal(epoch.sec(ns_idx),
                     ns_idx.values.astype("int64") // 1_000_000_000))

# ══ 3. A `Timedelta.value`-VAL EGY MÉRTÉKEGYSÉGBEN ════════════════════════
# A motor így használja: `_t15_ns[j] + _delta_ns <= _t1_ns[i]`.
for u, idx in minta.items():
    delta = pd.Timedelta(minutes=15).value
    check(f"a Timedelta.value ({u} indexnél) pont egy lépés",
          int(epoch.ns(idx)[1] - epoch.ns(idx)[0]) == delta)

# ══ 4. ŐR: a motor nem csinálja újra kézzel ═══════════════════════════════
# ⚠ Ez a lényeg. Az 1-3. pont a modult méri; ez azt, hogy HASZNÁLJÁK is.
MAPPAK = ("core", "trading", "strategy", "strategies", "gates", "dashboard", "ml")
TILTOTT = re.compile(r"\.asi8\b"
                     r"|\.view\(\s*[\"']int64[\"']\s*\)"
                     r"|index\.values\.astype\(\s*[\"']int64[\"']\s*\)")
KIVETEL = {Path("core") / "epoch.py"}          # a központi átváltás maga

talalatok = []
for mappa in MAPPAK:
    for f in sorted((ROOT / mappa).rglob("*.py")):
        rel = f.relative_to(ROOT)
        if rel in KIVETEL or "__pycache__" in rel.parts:
            continue
        for i, sor in enumerate(io.open(f, encoding="utf-8").read().splitlines(), 1):
            # a MAGYARÁZÓ megjegyzés említheti a tiltott formát (és említi is:
            # épp azt mondja el, miért nem azt használjuk) — a kódot nézzük
            kod = sor.split("#", 1)[0]
            if TILTOTT.search(kod):
                talalatok.append(f"{rel}:{i}")

check("a motorban nincs kézi időbélyeg-átváltás (core.epoch-on át kell menni)",
      not talalatok, ", ".join(talalatok[:5]))

# ══ ÖSSZESÍTÉS ════════════════════════════════════════════════════════════
jo = sum(results)
print(f"\n{jo}/{len(results)} teszt PASS")
sys.exit(0 if jo == len(results) else 1)

"""Az ActivTrades szerver-zónája a VALÓDI adatból: Europe/Berlin.

⚠ MIÉRT KÜLÖN, ÉLŐ ADATOS TESZT. A `gates/sessions.py` teljes naptára és a
`core/broker_time.py` kanonikus órája arra épül, hogy a mai szerver
Europe/Berlin — EU szerint vált nyári időre. 2026-09-28-án egy (hibás) heti-
nyitás mérés ennek az ellenkezőjét mondta („NY+6", USA-váltással). A
tőzsdenyitás-horgonyos mérés az évi eltérő heteken döntött: Berlin 25–34%,
NY+6 2–13% (perc-merce); a vegleges merce a nyitas utani volatilitas-lepcso. Ha egy bróker-váltás vagy adat-újraépítés után ez megfordulna, a
naptár egy órát tévedne az eltérő heteken — ez a teszt azt fogja meg.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import broker_paths as _BP                      # noqa: E402
from tests import _broker_pin                            # noqa: E402
_broker_pin.pin()   # a valódi adat az ActivTradesé, akármelyik a főszámla
sys.path.insert(0, str(ROOT / "tools"))

from core import applog                                                  # noqa: E402
applog.harden_console()

import pandas as pd                                                      # noqa: E402

import detect_server_zone as D                                           # noqa: E402

_results, _fail = [], []


def check(name, ok, detail=""):
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


for sym in ("UsaTec", "Ger40"):
    f = _BP.bars_file("m1", sym)
    check(f"{sym}: van adat", f.exists(), str(f))
    if not f.exists():
        continue
    T = D.felismer(pd.read_parquet(f, columns=["high", "low"]))
    b = T.iloc[0]
    check(f"{sym}: Europe/Berlin", b.zona == "Europe/Berlin",
          f"{b.zona} {b.lepcso:.2f}")
    ny6 = T[T.zona == "America/New_York+6"].iloc[0]
    check(f"{sym}: az eltero heteken Berlin >> NY+6",
          b.elteres_heteken - ny6.elteres_heteken >= 0.10,
          f"{b.elteres_heteken:.2f} vs {ny6.elteres_heteken:.2f}")

# ⚠ A DEVIZA NEM ALKALMAS — az eszkoznek ezt KI KELL MONDANIA, nem magabiztosan
# tevednie (az EURUSD a 2026-09-28-i meresen „Europe/London"-t adott).
f = _BP.bars_file("m1", "EURUSD")
if f.exists():
    it = D.itelet(D.felismer(pd.read_parquet(f, columns=["high", "low"])))
    check("EURUSD (deviza): NINCS magabiztos itelet", it.startswith("!!"), it)

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)

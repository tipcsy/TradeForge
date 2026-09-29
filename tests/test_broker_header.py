"""0029/5a: a fejléc bróker-órái.

Tibi kérése (2026-09-28): „Bróker helyett: ActivTrader: 11:23.. Ha van több,
akkor alatta Roboforex: 11:23 (még ha ugyanaz is!)".
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                         # noqa: E402
applog.harden_console()

from dashboard.broker_header import clock_text                 # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


most = datetime(2026, 9, 29, 19, 25, 7, tzinfo=timezone.utc)
at = NS(id="activtrades", name="ActivTrades")
rob = NS(id="roboforex", name="RoboForex")

egy = clock_text([at], {"activtrades": 7200}, most)
check("egy bróker: EGY sor", "\n" not in egy, egy)
check("...a bróker NEVE és a szerverideje (nem „Bróker”)", egy.startswith("ActivTrades: 21:25:07"), egy)
check("...és az UTC is", "UTC 19:25" in egy, egy)

ket = clock_text([at, rob], {"activtrades": 7200, "roboforex": 7200}, most)
sorok = ket.split("\n")
check("két bróker: KÉT sor", len(sorok) == 2, repr(ket))
check("⚠ azonos idő mellett is külön sor, mindkettő névvel",
      sorok[0].startswith("ActivTrades: 21:25:07")
      and sorok[1] == "RoboForex: 21:25:07", repr(ket))
check("az UTC csak egyszer (az első sorban)", ket.count("UTC") == 1)

mas = clock_text([at, rob], {"activtrades": 7200, "roboforex": 10800}, most)
check("eltérő zóna: mindegyik a SAJÁT idejét", mas.split("\n")[1] == "RoboForex: 22:25:07", mas)

nem = clock_text([at, rob], {"activtrades": 7200}, most)
check("ismeretlen idő (nem fut a motorja): „—”, nem hamis idő",
      nem.split("\n")[1] == "RoboForex: —", nem)
check("az otthoni ideje sem ismert: akkor is látszik a név",
      clock_text([at], {}, most).startswith("ActivTrades: —"))

_g = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
check("a felület ezt a függvényt használja", "clock_text(_profs, _offs, now)" in _g)
check("a régi „Bróker {broker}” kulcs nincs már használatban", '"gui.hdr.clock"' not in _g)
check("a többi bróker ideje a motorja állapotképéből",
      '_es.read(_p) or {}).get("server_offset_sec")' in _g)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

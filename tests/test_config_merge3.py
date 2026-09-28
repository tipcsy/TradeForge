"""KET PROCESSZ, EGY config.json — a mentes nem torolheti a masik processz valtozasat.

⚠ A LELET (2026-09-28, 0029/4b): a broker-motor (kulon processz) a Play-t a
sajat blokkjaba mentette; a felulet a regi, inditaskor betoltott configot
tartotta a memoriajaban, es a kovetkezo mentese (barmilyen beallitas) CSENDBEN
visszairta — a motor Play-je eltunt. Ez a teszt pontosan ezt jatssza le.

MIT ORZUNK:
  1. A masik processz valtozasa (itt: a roboforex run_state-je) MEGMARAD, ha mi
     mast mentunk.
  2. A mi valtozasunk (itt: a slot-szam) is bekerul.
  3. Amit mi toroltunk, es a lemezen senki nem modositott — torlodik; amit
     kozben mas modositott — marad.
  4. Ugyanaz a kulcs mindket helyen: az utolso mentes nyer (mint eddig).
  5. Betoltott alap nelkul (a tesztek ideiglenes fajljai) a regi viselkedes.
⚠ CSAK ideiglenes fajlba ir.
"""
import sys
import copy
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                                  # noqa: E402
applog.harden_console()

from strategy import settings as S                                       # noqa: E402

_results, _fail = [], []


def check(name, ok, detail=""):
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


TMP = Path(tempfile.mkdtemp())
f = TMP / "config.json"
ALAP = {"trading": {"max_open_slots": 4, "daily_loss_limit_usd": 50},
        "pairs": {"GOLD": {"point_size": 0.01, "run_state": {"wpr_sma": "live"}},
                  "EURUSD": {"point_size": 1e-05, "regi_kulcs": 1}}}
f.write_text(json.dumps(ALAP, indent=2), encoding="utf-8")


def lemez():
    return json.loads(f.read_text(encoding="utf-8"))


def masik_processz_ir(fn):
    """A masik processz (pl. a roboforex motor) sajat mentese a lemezre."""
    d = lemez()
    fn(d)
    f.write_text(json.dumps(d, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
print("== A lelet forgatokonyve: a motor Play-je a felulet mentese utan ==")
cfg = S.load_config(f)                               # a FELULET betolt
masik_processz_ir(lambda d: d["pairs"]["GOLD"].setdefault("brokers", {})
                  .setdefault("roboforex", {}).update(run_state={"wpr_sma": "live"}))
cfg["trading"]["max_open_slots"] = 6                 # a felulet mast allit
hiba = S.save_main_config(cfg, f)
d = lemez()
check("mentes sikeres", hiba == "", hiba)
check("a MOTOR Play-je MEGMARADT",
      d["pairs"]["GOLD"].get("brokers", {}).get("roboforex", {}).get("run_state")
      == {"wpr_sma": "live"}, str(d["pairs"]["GOLD"]))
check("a felulet valtozasa bekerult", d["trading"]["max_open_slots"] == 6)
check("az erintetlen kulcsok valtozatlanok", d["trading"]["daily_loss_limit_usd"] == 50
      and d["pairs"]["EURUSD"]["point_size"] == 1e-05)

print("\n== Torles es utkozes ==")
masik_processz_ir(lambda d: d["trading"].update(daily_loss_limit_usd=80))
del cfg["pairs"]["EURUSD"]["regi_kulcs"]            # mi toroltunk egy erintetlent
cfg["trading"]["daily_loss_limit_usd"] = 30          # UTKOZES: mindketten allitottuk
S.save_main_config(cfg, f)
d = lemez()
check("amit mi toroltunk (es mas nem modositott) -> torlodik", "regi_kulcs" not in d["pairs"]["EURUSD"])
check("utkozesnel az utolso mentes nyer", d["trading"]["daily_loss_limit_usd"] == 30)
check("a motor korabbi valtozasa tovabbra is megvan",
      d["pairs"]["GOLD"]["brokers"]["roboforex"]["run_state"] == {"wpr_sma": "live"})

masik_processz_ir(lambda d: d["pairs"]["EURUSD"].update(uj_kulcs=7))
S.save_main_config(cfg, f)
check("a masik processz UJ kulcsa megmarad", lemez()["pairs"]["EURUSD"].get("uj_kulcs") == 7)

masik_processz_ir(lambda d: d["pairs"]["GOLD"].update(point_size=0.001))
del cfg["pairs"]["GOLD"]["point_size"]              # mi torolnenk, de kozben modosult
S.save_main_config(cfg, f)
check("torles, de kozben mas modositotta -> MARAD",
      lemez()["pairs"]["GOLD"].get("point_size") == 0.001)

print("\n== A merge3 alapesetei ==")
check("nem nyultam hozza -> a lemez", S.merge3({"a": 1}, {"a": 1}, {"a": 2}) == {"a": 2})
check("en valtoztattam -> az enyem", S.merge3({"a": 1}, {"a": 3}, {"a": 1}) == {"a": 3})
check("lista egeszben", S.merge3({"l": [1]}, {"l": [1, 2]}, {"l": [1]}) == {"l": [1, 2]})
check("beagyazott: mindket oldal mas kulcsot", S.merge3(
    {"p": {"x": 1, "y": 1}}, {"p": {"x": 2, "y": 1}}, {"p": {"x": 1, "y": 3}})
    == {"p": {"x": 2, "y": 3}})

print("\n== Betoltott alap nelkul: a regi viselkedes ==")
g = TMP / "masik.json"
g.write_text(json.dumps({"a": 1, "b": 2}), encoding="utf-8")
S.write_config_file({"a": 5}, g)
check("alap nelkul: pontosan az irodik ki, amit adtunk", json.loads(g.read_text()) == {"a": 5})

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)

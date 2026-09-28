"""CONFIG-FIGYELO — a kulon processzben futo motor lassa a felulet beallitasait.

⚠ MIT ORZUNK (0029, 4b/3 S1, 2026-09-28):
  1. A figyelo csak ELOKESZIT; a config CSAK a motor `apply_pending` hivasara all
     at (a motor kor-elejen) — egy masik szalbol torteno atiras a bejaras
     kozben „dictionary changed size" hibaval olhetne meg a kereskedo szalat.
  2. HELYBEN, a beagyazott dict-OBJEKTUMOK megtartasaval (a motor tart
     alhivatkozast: `trading_cfg = cfg["trading"]`).
  3. A haromutas mentes ALAPJA csak az alkalmazaskor all at.
  4. Felig irt / hibas fajl: a regi config marad, a kovetkezo kor ujraprobal.
  5. Figyelo nelkul (a felulet processzeben futo motor) az alkalmazas ures.
⚠ CSAK ideiglenes fajlokkal.
"""
import sys
import json
import time
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                                  # noqa: E402
applog.harden_console()

from core import config_watch as CW                                      # noqa: E402
from strategy import settings as S                                       # noqa: E402

_results, _fail = [], []


def check(name, ok, detail=""):
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


TMP = Path(tempfile.mkdtemp())
f = TMP / "config.json"


def ir(d):
    f.write_text(json.dumps(d), encoding="utf-8")
    time.sleep(0.02)                      # a modositasi ido biztosan lepjen


def olvas(p):                             # a teszt betoltoje: nyers JSON (strategia nelkul)
    return json.loads(Path(p).read_text(encoding="utf-8"))


ir({"trading": {"max_open_slots": 4, "daily_loss_limit_usd": 50},
    "pairs": {"GOLD": {"enabled": True}}, "torlendo": 1})
cfg = S.load_config(f)
trading_ref = cfg["trading"]                                             # a motor alhivatkozasa
kulcs = S._alap_kulcs(f)
alap_elotte = json.dumps(S._ALAP[kulcs], sort_keys=True)

print("== Figyelo nelkul az alkalmazas ures ==")
CW._pending = None
check("nincs varakozo -> False", CW.apply_pending(cfg) is False)

print("\n== A figyelo ELOKESZIT, de nem alkalmaz ==")
w = CW.Watcher(f, loader=olvas, period=999)
check("valtozas nelkul nincs teendo", w.check_once() is False)
uj = {"trading": {"max_open_slots": 6, "daily_loss_limit_usd": 50},
      "pairs": {"GOLD": {"enabled": False}, "EURUSD": {"enabled": True}}}
ir(uj)
check("a valtozast eszleli", w.check_once() is True)
check("... de a motor configja MEG a regi", cfg["trading"]["max_open_slots"] == 4)
check("... es az osszefesules ALAPJA meg a regi",
      json.dumps(S._ALAP[kulcs], sort_keys=True) == alap_elotte)

print("\n== A motor alkalmazza (helyben) ==")
check("apply_pending -> True", CW.apply_pending(cfg) is True)
check("az uj ertek", cfg["trading"]["max_open_slots"] == 6 and cfg["pairs"]["GOLD"]["enabled"] is False)
check("uj par megjelent", cfg["pairs"]["EURUSD"]["enabled"] is True)
check("torolt kulcs eltunt", "torlendo" not in cfg)
check("a motor ALHIVATKOZASA el (ugyanaz az objektum, friss ertekkel)",
      cfg["trading"] is trading_ref and trading_ref["max_open_slots"] == 6)
check("az osszefesules alapja MOST allt at", S._ALAP[kulcs] == uj)
check("masodszor nincs teendo", CW.apply_pending(cfg) is False)

print("\n== Felig irt / hibas fajl ==")
f.write_text('{"trading": {"max_open_', encoding="utf-8")
time.sleep(0.02)
check("hibas fajl -> nincs uj config", w.check_once() is False and CW._pending is None)
ir(dict(uj, trading={"max_open_slots": 8, "daily_loss_limit_usd": 50}))
check("javitas utan a kovetkezo kor felveszi", w.check_once() is True)
CW.apply_pending(cfg)
check("... es alkalmazza", cfg["trading"]["max_open_slots"] == 8)

print("\n== Hatterszal: a vegigjatszott ut ==")
ww = CW.Watcher(f, loader=olvas, period=0.05).start()
ir(dict(uj, trading={"max_open_slots": 3, "daily_loss_limit_usd": 50}))
vege = time.time() + 3
while time.time() < vege and CW._pending is None:
    time.sleep(0.02)
ww.stop()
check("a szal eszlelte", CW._pending is not None)
CW.apply_pending(cfg)
check("a motor korben alkalmazza", cfg["trading"]["max_open_slots"] == 3)

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)

"""FELUGYELO — a broker-motorok inditasa / leallitasa / ujrainditasa (0029, 4b).

⚠ MIT ORZUNK (2026-09-28):
  1. Az inditas LEVALASZTOTT processz a SAJAT brokerrel (`--broker <id>`) —
     a felulet bezarasa nem allitja le a kereskedest.
  2. Futo motort nem inditunk masodszor (a szamla futas-zara a merce).
  3. Az UJRAINDITAS szabalyai: csak `autostart`-ra; csak ha a processz NEM el;
     SOHA, ha a motor rendben allt le (a felhasznalo dontese); FEK: legfeljebb
     MAX_RESTARTS / WINDOW_SEC — egy folyton osszeomlo motor nem porog.
⚠ A teszt valodi processzt NEM indit, es a valodi data/ mappaba NEM ir.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                                  # noqa: E402
applog.harden_console()

from core import broker_profile as P                                     # noqa: E402
from core import engine_supervisor as SV                                 # noqa: E402

_results, _fail = [], []


def check(name, ok, detail=""):
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


PROFS = P.profiles({"brokers": [
    {"id": "activtrades", "tag": "At", "login": 1},
    {"id": "roboforex", "tag": "Rob", "login": 555, "autostart": True},
    {"id": "icm", "tag": "IC", "login": 777}]})
_, ROBO, ICM = PROFS
TMP = Path(tempfile.mkdtemp())

print("== A profil autostart mezoje ==")
check("autostart: true a roboforexen", ROBO.autostart)
check("alapbol NEM (egy kereskedo motor magatol ne induljon)", not ICM.autostart)

print("\n== Inditas: levalasztott processz, a sajat brokerrel ==")
hivas = {}


def hamis_popen(args, **kw):
    hivas.update(args=args, **kw)
    return object()


_regi = (SV.running, SV.log_path)
SV.log_path = lambda p: TMP / f"{p.id}.log"
SV.running = lambda p: False
ok, kulcs = SV.start(ROBO, popen=hamis_popen)
check("indul", ok and kulcs == "started")
check("a parancs: main.py console --broker roboforex",
      hivas["args"][2:] == ["console", "--broker", "roboforex", "--headless"]
      and hivas["args"][1].endswith("main.py"), str(hivas["args"]))
check("nincs bemenet (nem var input()-ra)", hivas["stdin"] is not None)
# ⚠ A DEMO-PROBA LELETE (2026-09-29): Windowson a NUL bemenetre az isatty() True,
# a motor promptot irt, az input() fajlveget kapott, es a motor leallt. A
# `--headless` kapcsolo nelkul ez visszajonne.
check("--headless kapcsoloval indul (a Windows isatty-csapda ellen)",
      "--headless" in hivas["args"])
if sys.platform == "win32":
    check("LEVALASZTVA (a felulet bezarasa nem allitja le)", hivas["creationflags"] & 0x8)
check("a kimenet a broker naplojaba", (TMP / "roboforex.log").exists())
SV.running = lambda p: True
ok, kulcs = SV.start(ROBO, popen=hamis_popen)
check("futo motort NEM indit masodszor", not ok and kulcs == "already_running")

print("\n== Leallitas a csatornan ==")
SV.running = lambda p: False
check("nem futo motor", SV.stop(ROBO, request=lambda *a: {}) == (False, "not_running"))
SV.running = lambda p: True
kuldott = []
check("futo motor -> quit megy", SV.stop(ROBO, request=lambda p, l, c: kuldott.append((l, c)) or {})
      == (True, "stopping") and kuldott == [("quit", True)])
check("valasz nelkul", SV.stop(ROBO, request=lambda *a: None) == (False, "no_answer"))
SV.running, SV.log_path = _regi

print("\n== Az UJRAINDITAS szabalyai ==")
ora = [1000.0]
elo, kep, inditott = set(), {}, []
sv = SV.Supervisor(starter=lambda p: (inditott.append(p.id) or True, "started"),
                   is_running=lambda p: p.id in elo, reader=lambda p: kep.get(p.id),
                   clock=lambda: ora[0])
auto = lambda p: p.autostart                                           # noqa: E731

check("autostart NELKUL nincs ujrainditas", sv.tick([ICM], auto) == [] and inditott == [])
elo.add("roboforex")
check("futo motort nem inditja", sv.tick([ROBO], auto) == [])
elo.clear()
kep["roboforex"] = {"stopped": True}
check("RENDBEN leallitott motort NEM inditja (a te dontesed)", sv.tick([ROBO], auto) == [])
kep["roboforex"] = {"stopped": False, "ts": 1}                         # osszeomlott
check("osszeomlott motor -> ujraindit", sv.tick([ROBO], auto) == [("roboforex", "restarted")])
sv.tick([ROBO], auto); sv.tick([ROBO], auto)
check("3 ujrainditas a keretben", inditott.count("roboforex") == 3)
check("a 4. -> FEK (restart_limit)", sv.tick([ROBO], auto) == [("roboforex", "restart_limit")]
      and inditott.count("roboforex") == 3)
ora[0] += SV.WINDOW_SEC + 1
check("a keret lejarta utan ujra probalhat", sv.tick([ROBO], auto) == [("roboforex", "restarted")])
kep.pop("roboforex")
check("allapotkep nelkul (sosem futott) is indit, ha autostart",
      sv.tick([ROBO], auto) == [("roboforex", "restarted")])

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)

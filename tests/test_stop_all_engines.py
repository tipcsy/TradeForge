"""A program bezarasakor MINDEN motor leall (Tibi dontese, 2026-09-30).

Kulso modban (engine.external) a felulet bezarasa eddig NEM allitotta le a
motort; normal modban a TOBBI broker motorja futott tovabb. Most mindket uton
a `main.stop_all_engines` a rendes kilepesi uton (quit) allit le mindent.
⚠ Hamis feluegyelo — a valodi motorokat a teszt nem allitja le.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                          # noqa: E402
applog.harden_console()

import main as M                                                 # noqa: E402
from core import engine_supervisor as SV                        # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


CFG = {"brokers": [{"id": "act", "tag": "At", "login": 1, "server": "a"},
                   {"id": "rob", "tag": "Rob", "login": 2, "server": "b"}]}
hivott = []
_regi = SV.stop
SV.stop = lambda p, request=None: (hivott.append(p.id) or (True, "stopping"))
try:
    out = M.stop_all_engines(CFG)
    check("kulso mod: MINDEN broker motorja leall", hivott == ["act", "rob"], str(hivott))
    check("visszaadja az eredmenyt brokerenkent", out == [("At", "stopping"), ("Rob", "stopping")], str(out))
    hivott.clear()
    M.stop_all_engines(CFG, skip_ids=("act",))
    check("normal mod: az otthoni kimarad (a felulettel egyutt all le)", hivott == ["rob"], str(hivott))
    SV.stop = lambda p, request=None: (_ for _ in ()).throw(RuntimeError("x"))
    out = M.stop_all_engines(CFG)
    check("egy hibas leallitas nem viszi el a tobbit", len(out) == 2, str(out))
finally:
    SV.stop = _regi

_m = (ROOT / "main.py").read_text(encoding="utf-8")
check("a kulso mod bezarasa hivja", "    finally:\n        stop_all_engines(cfg)\n" in _m)
check("a normal mod bezarasa is (az otthoni nelkul)",
      "stop_all_engines(cfg, skip_ids=(_bp.active(cfg).id,))" in _m)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

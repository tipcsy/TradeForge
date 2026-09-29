"""KULSO MOTOR kapcsolo (`engine.external`) — 0029, 4b/3 S5.

⚠ MIT ORZUNK (2026-09-29):
  1. KI (alapbol): a `cmd_live` a regi uton megy — kapcsolodik, sajat motort indit.
  2. BE: a felulet NEM kapcsolodik MT5-hoz es NEM indit sajat motort; ha az
     otthoni motor nem fut, a felugyelo inditja; a felulet tavoli modban
     (start_remote_mode) — es az atjaro MAR A FELULET LETREHOZASA ELOTT tavoli
     (a konstruktor hatter-lekerdezoje kulonben egy pillanatig helyi MT5-ot hivna).
  3. Futo motort nem indit masodszor.
⚠ Valodi ablakot, processzt, MT5-ot NEM hasznal: minden kulso hatas hamisitvany.
"""
import sys
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                                  # noqa: E402
applog.harden_console()

import main as M                                                         # noqa: E402
from core import broker_profile as P                                     # noqa: E402
from core import engine_supervisor as SV                                 # noqa: E402
from core import mt5_connector as MC                                     # noqa: E402
from dashboard import engine_gateway as GW                               # noqa: E402

_results, _fail = [], []


def check(name, ok, detail=""):
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


TMP = Path(tempfile.mkdtemp())
CFG = {"broker": {"name": "ActivTrades", "server": "AT", "login": 6264021},
       "mt5": {}, "trading": {"max_open_slots": 4}, "pairs": {},
       "engine": {"external": True}}
esemeny = []


class HamisAblak:
    def __init__(self, cfg, d, i, o, **kw):
        esemeny.append(("ablak", GW.is_remote(), kw.get("on_slots_change")))
        self.root = self

    def start_remote_mode(self, profil):
        esemeny.append(("tavoli", profil.id))

    def after(self, ms, fn):
        esemeny.append(("after", ms))

    def run(self):
        esemeny.append(("run",))


import dashboard.gui as G                                                # noqa: E402
_regi = (G.DashboardWindow, SV.running, SV.start, MC.connect)
G.DashboardWindow = HamisAblak


mt5_kapcs = []


def _tilos(*a, **k):
    mt5_kapcs.append(1)
    raise AssertionError("kulso motornal a felulet NEM kapcsolodhat MT5-hoz")


MC.connect = _tilos
try:
    print("== BE: kulso motor, a motor nem fut ==")
    inditott = []
    SV.running = lambda p: False
    SV.start = lambda p: inditott.append(p.id) or (True, "started")
    GW.reset()
    M._cmd_live_external(CFG)
    home = P.active(CFG)
    check("a felugyelo inditja az otthoni motort", inditott == [home.id], str(inditott))
    check("az atjaro MAR a felulet letrehozasakor tavoli", esemeny[0][:2] == ("ablak", True),
          str(esemeny[:1]))
    check("slot-visszahivas nincs (a configon at er a motorhoz)", esemeny[0][2] is None)
    check("a felulet tavoli modban", ("tavoli", home.id) in esemeny)
    check("a fejlec frissitese utemezve, a felulet fut", ("after", 1000) in esemeny
          and ("run",) in esemeny)
    check("MT5-kapcsolodas NEM tortent", mt5_kapcs == [], str(mt5_kapcs))

    print("\n== BE: a motor mar fut ==")
    esemeny.clear()
    inditott.clear()
    SV.running = lambda p: True
    M._cmd_live_external(CFG)
    check("futo motort NEM indit masodszor", inditott == [])

    print("\n== KI (alapbol): a regi ut ==")
    cfgf = TMP / "config.json"
    cfgf.write_text(json.dumps(dict(CFG, engine={"external": False})), encoding="utf-8")
    kapcsolodott = []
    MC.connect = lambda cfg: kapcsolodott.append(1) or False    # a regi ut itt kilep
    _regi_path, _regi_argv = M.CFG_PATH, list(sys.argv)
    M.CFG_PATH, sys.argv = cfgf, ["main.py", "live"]
    try:
        M.cmd_live()
        check("a regi ut kilep, ha nincs MT5", False, "nem lepett ki")
    except SystemExit:
        check("KI: a regi ut — kapcsolodni probal (a felulet processzeben)", kapcsolodott == [1])
    finally:
        M.CFG_PATH, sys.argv = _regi_path, _regi_argv
    print("\n== engine-stop: az otthoni motor leallitasa ==")
    # ⚠ Kulso motornal az otthoni motor konzol nelkul fut, es a Brokerek ful
    # csak a TOVABBI brokereket mutatja — enelkul nem lehetne leallitani.
    _regi_stop, _regi_load = SV.stop, M.load_cfg
    M.load_cfg = lambda: CFG
    try:
        for eredmeny, kod in (((True, "stopping"), 0), ((False, "not_running"), 0),
                              ((False, "no_answer"), 1)):
            SV.stop = lambda p, e=eredmeny: e
            check(f"engine-stop: {eredmeny[1]} -> kilepesi kod {kod}",
                  M.cmd_engine_stop() == kod)
    finally:
        SV.stop, M.load_cfg = _regi_stop, _regi_load
    check("az engine-stop a parancsok kozott", "engine-stop" in M.COMMANDS)
finally:
    G.DashboardWindow, SV.running, SV.start, MC.connect = _regi
    GW.reset()

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)

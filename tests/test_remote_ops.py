"""STRUKTURALT TAVOLI MUVELETEK + az atjaro (0029, 4b/3 S3b).

⚠ MIT ORZUNK (2026-09-28):
  1. A csatorna `op` agai: csak a motor muvelet-listajabol fut; ismeretlen /
     ELAVULT nem fut; hiba nem viszi el a motort; False = sikertelen, dict = siker
     (egy KIKAPCSOLT trailing nem „hiba").
  2. A motor muvelet-listaja PONTOSAN a nyolc engedelyezett muvelet.
  3. EGY implementacio: a BE, a trailing-jelzok es az orokbefogadas a
     live_trader kozos fuggvenyeiben — a felulet helyi utja is ezt hivja.
  4. Az atjaro HELYI modban a helyi fuggvenyt hivja, es a csatornat NEM erinti
     (a mai ut); TAVOLI modban a muvelet + argumentumok mennek ki.
⚠ Minden fajliras ideiglenes utvonalra (adopted / position_meta atallitva).
"""
import sys
import time
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                                  # noqa: E402
applog.harden_console()

from core import engine_channel as CH                                    # noqa: E402
from core import broker_profile as P                                     # noqa: E402
from core import console_cmd as C                                        # noqa: E402

_results, _fail = [], []


def check(name, ok, detail=""):
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


ROBO = P.profiles({"brokers": [{"id": "a", "tag": "A"}, {"id": "rob", "tag": "Rob"}]})[1]
TMP = Path(tempfile.mkdtemp())
IB, OB = TMP / "in", TMP / "out"
ctx = C.Context(cfg={}, save_config=lambda: True, positions=list,
                close_position=lambda t: False, account=dict, dashboard={},
                instrument_state={}, strategies_of=lambda s: [])
hivott = []
OPS = {"ok": lambda x: hivott.append(("ok", x)) or {"value": x},
       "hamis": lambda: False,
       "hiba": lambda: 1 / 0}


def futtat(op, args=None, kor=0.0):
    a = CH.send(ROBO, op=op, args=args or {}, now=time.time() - kor, inbox=IB)
    return {v["id"]: v for v in CH.process_once(ctx, ROBO, inbox=IB, outbox=OB, ops=OPS)}[a]


print("== A csatorna strukturalt muveletei ==")
v = futtat("ok", {"x": 5})
check("engedelyezett muvelet lefut az argumentumaival", hivott == [("ok", 5)] and v["ok"]
      and v["result"] == {"value": 5}, str(v))
check("ismeretlen muvelet NEM fut", futtat("rm_rf").get("reason") == "not_allowed")
hivott.clear()
check("ELAVULT muvelet NEM fut", futtat("ok", {"x": 1}, kor=CH.MAX_AGE_SEC + 5).get("reason")
      == "stale" and hivott == [])
check("hiba: a motor nem szall el", futtat("hiba").get("reason") == "error")
check("False eredmeny = sikertelen", futtat("hamis")["ok"] is False)

print("\n== A motor muvelet-listaja ==")
from trading import live_trader as LT                                    # noqa: E402
check("pontosan a 14 engedelyezett muvelet (9 iro + 5 OLVASO, S4)", set(LT.remote_ops({})) ==
      {"open", "build", "be", "ptoggle", "pset", "adopt", "release", "viz_clear",
       "viz_render", "symbols", "symbol_info", "rates", "tf_closes", "closed_range"},
      str(sorted(LT.remote_ops({}))))

print("\n== EGY implementacio: a kozos fuggvenyek ==")
T = 987654321
LT.position_state.pop(T, None)
check("trailing kapcsolo: alapbol BE -> KI", LT.toggle_position_flag(T, "trailing_enabled") is False
      and LT.position_state[T]["trailing_enabled"] is False)
check("... es vissza BE", LT.toggle_position_flag(T, "trailing_enabled") is True)
LT.set_position_flag(T, "trail_points", 150)
check("trail-tavolsag", LT.position_state[T]["trail_points"] == 150)
try:
    LT.set_position_flag(T, "original_sl", 0.0)
    check("tiltott kulcs (original_sl) elutasitva", False)
except ValueError:
    check("tiltott kulcs (original_sl) elutasitva", True)
check("a rekord teljes alaku (a pstate-e, nem kitalalt)", "original_sl" in LT.position_state[T])

_regi_be = LT.mt5_connector.move_to_breakeven
LT.mt5_connector.move_to_breakeven = lambda t: False
check("BE, ha az ar meg nem fedezi: False, be_done nincs",
      LT.manual_breakeven(T, 2390.0) is False and not LT.position_state[T].get("be_done"))
LT.mt5_connector.move_to_breakeven = lambda t: True
check("BE sikeres: be_done", LT.manual_breakeven(T, 2390.0) is True
      and LT.position_state[T]["be_done"] is True)
LT.mt5_connector.move_to_breakeven = _regi_be
LT.position_state.pop(T, None)

from core import adopted as AD, position_meta as PM                      # noqa: E402
_rp = (AD.PATH, PM.PATH)
AD.PATH, PM.PATH = TMP / "adopted.json", TMP / "pmeta.json"
try:
    AD.load(); PM.load()
    LT.adopt_position(T, "wpr_sma", "GOLD",
                      {"volume": 0.1, "price_open": 2400.0, "sl": 2390.0},
                      {"point_size": 0.01, "pv1_point": 0.01})
    check("orokbefogadas: a hozzarendeles fajlba irodott (IDEIGLENES)",
          (TMP / "adopted.json").exists() and str(T) in (TMP / "adopted.json").read_text())
    check("... es a belepeskori kockazat is", (TMP / "pmeta.json").exists()
          and str(T) in (TMP / "pmeta.json").read_text())
finally:
    AD.PATH, PM.PATH = _rp
    AD.load(); PM.load()

print("\n== Az atjaro ==")
from dashboard import engine_gateway as GW                               # noqa: E402
GW.reset()
helyi = []
kert = []
check("HELYI mod: a helyi fuggveny, a csatorna erintetlen",
      GW.op("be", lambda: helyi.append(1) or "h", ticket=1) == "h" and helyi == [1])
GW.configure(ROBO, None, request=lambda p, **kw: kert.append(kw) or {"ok": True, "result": 42})
check("TAVOLI mod, szinkron: a motor eredmenye", GW.op("open", lambda: helyi.append(2),
      sync=True, symbol="GOLD", lot=0.1) == 42 and helyi == [1])
check("... a muvelet es az argumentumok mentek ki",
      kert and kert[-1]["op"] == "open" and kert[-1]["args"] == {"symbol": "GOLD", "lot": 0.1},
      str(kert[-1:]))
uzenet = []
GW.configure(ROBO, None, status_cb=uzenet.append, request=lambda p, **kw: None)
check("nem valaszol: None + uzenet", GW.op("open", lambda: 1, sync=True) is None and uzenet)
GW.reset()

print("\n== A felulet kezeloi tavoli modban az atjaron mennek ==")
from dashboard.gui import DashboardWindow as W                           # noqa: E402
kuldott = []
GW.configure(ROBO, None, request=lambda p, **kw: kuldott.append((kw["op"], kw["args"]))
             or {"ok": True, "result": True})


class Hamis:
    _mt5_cache = {"positions_detail": [{"ticket": 7, "sl": 2390.0, "symbol": "GOLD",
                                        "magic": 0}]}

    def _strategy_of_position(self, pos):
        return "wpr_sma"


h = Hamis()
W._pos_trail(h, 7)
W._pos_trail_dist(h, 7, 120)
W._pos_be(h, 7)
W._pos_build(h, 7)
vege = time.time() + 3
while time.time() < vege and len(kuldott) < 4:
    time.sleep(0.02)
kuld = sorted(kuldott, key=lambda x: x[0])
check("trailing / tavolsag / BE / raepites a motorhoz ment",
      kuld == sorted([("ptoggle", {"ticket": 7, "key": "trailing_enabled"}),
                      ("pset", {"ticket": 7, "key": "trail_points", "value": 120}),
                      ("be", {"ticket": 7, "orig_sl": 2390.0}),
                      ("build", {"symbol": "GOLD", "strategy": "wpr_sma"})],
                     key=lambda x: x[0]), str(kuld))
check("... es a helyi position_state ERINTETLEN", 7 not in LT.position_state)
GW.reset()

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)

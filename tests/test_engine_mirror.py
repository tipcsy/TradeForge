"""KIJELZES-TUKOR — a motor paronkenti allapota oda-vissza a JSON-on at (0029, 4b/3 S2).

⚠ MIT ORZUNK (2026-09-28):
  1. ODA-VISSZA BITRE: a motor allapotkepe -> JSON -> a felulet tukre utan
     MINDEN `PairDashboardState` mezo pontosan egyezik — kulonosen azok, ahol a
     JSON elveszi a tipust: a `None` kulcs (daily_by_strategy), az egesz kulcsok
     (timeframe_remaining), a tuple-ok (opt_grade, a strategia-cellak).
  2. HELYBEN: a meglevo objektum ugyanaz marad (a felulet hivatkozast tarthat
     ra), a kikerult par torlodik, az instrument_state / optimizer_status tukrozodik.
  3. Ismeretlen mezo (ujabb motor) nem szall el; tukor nelkuli kep (regebbi
     motor) -> False, a felulet dictjei erintetlenek.
"""
import sys
import json
import dataclasses
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                                  # noqa: E402
applog.harden_console()

from core import console_cmd as C                                        # noqa: E402
from core import engine_mirror as M                                      # noqa: E402
from core import engine_status as ES                                     # noqa: E402
from core import broker_profile as P                                     # noqa: E402
from trading.live_trader import PairDashboardState as PDS                # noqa: E402

_results, _fail = [], []


def check(name, ok, detail=""):
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


GOLD = PDS(symbol="GOLD", bid=2400.12, ask=2400.45, digits=2, point=0.01,
           session={"state": "open", "age_sec": 1.5}, position_pnl=-12.5, pos_count=2,
           daily_by_strategy={"wpr_sma": {"pnl": 10.0, "count": 1},
                              None: {"pnl": -3.0, "count": 1}},
           opt_grade=("Jo", "green"), opt_grade_reason="PF 1,4",
           timeframe_remaining={1: 12, 15: 540},
           strategy_cells={"wpr_sma": {"m15": ("▲ 12", "green"), "m1": ("—", "muted")}},
           enabled_strategies=["wpr_sma"], tf_align_signs=[1, 1, -1],
           tf_align_dir="BUY", tf_align_labels=["M1", "M5", "M15"],
           market_state="trend", risky=True)
EUR = PDS(symbol="EURUSD", bid=1.17, ask=1.17002)
ENGINE_DASH = {"GOLD": GOLD, "EURUSD": EUR}

ctx = C.Context(cfg={"pairs": {}}, save_config=lambda: True, positions=list,
                close_position=lambda t: False, account=dict,
                dashboard=ENGINE_DASH, instrument_state={"GOLD": "LIVE", "EURUSD": "STOPPED"},
                strategies_of=lambda s: [])
ROBO = P.profiles({"brokers": [{"id": "a", "tag": "A"}, {"id": "rob", "tag": "Rob"}]})[1]

# a motor kepe -> JSON (ahogy a fajlba kerul) -> vissza
snap = json.loads(json.dumps(ES.snapshot(ctx, ROBO, optimizer_status={"GOLD": "Opt 40%"})))

print("== Oda-vissza: MINDEN mezo ==")
gui_dash, gui_inst, gui_opt = {}, {}, {}
check("a tukor alkalmazhato", M.apply(snap, gui_dash, gui_inst, gui_opt))
for sym, eredeti in ENGINE_DASH.items():
    ered = dataclasses.asdict(eredeti)
    tukor = dataclasses.asdict(gui_dash[sym])
    elter = [k for k in ered if ered[k] != tukor[k]]
    check(f"{sym}: minden mezo egyezik", not elter, str([(k, ered[k], tukor[k]) for k in elter]))
g = gui_dash["GOLD"]
check("a None kulcs vissza (gazdatlan poziciok)", None in g.daily_by_strategy)
check("egesz kulcsok vissza (timeframe_remaining)", set(g.timeframe_remaining) == {1, 15})
check("tuple vissza (opt_grade)", isinstance(g.opt_grade, tuple))
check("tuple vissza (strategia-cella)", isinstance(g.strategy_cells["wpr_sma"]["m15"], tuple))
check("instrument_state tukrozve", gui_inst == {"GOLD": "LIVE", "EURUSD": "STOPPED"})
check("optimizer_status tukrozve", gui_opt == {"GOLD": "Opt 40%"})

print("\n== Helyben frissit ==")
regi_obj = gui_dash["GOLD"]
GOLD.bid = 2401.0
del ENGINE_DASH["EURUSD"]
snap2 = json.loads(json.dumps(ES.snapshot(ctx, ROBO)))
M.apply(snap2, gui_dash, gui_inst, gui_opt)
check("ugyanaz az objektum, friss ertekkel", gui_dash["GOLD"] is regi_obj and regi_obj.bid == 2401.0)
check("a kikerult par torolve", "EURUSD" not in gui_dash)

print("\n== Verzio-elteres ==")
snap3 = json.loads(json.dumps(snap2))
snap3["dashboard"]["GOLD"]["uj_mezo_a_jovobol"] = 42
check("ismeretlen mezo nem szall el", M.apply(snap3, gui_dash) and gui_dash["GOLD"].bid == 2401.0)
elotte = dict(gui_dash)
check("tukor nelkuli kep (regebbi motor) -> False", M.apply({"ts": 1}, gui_dash) is False)
check("... es a felulet dictje erintetlen", gui_dash == elotte)
check("None kep -> False", M.apply(None, gui_dash) is False)

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)

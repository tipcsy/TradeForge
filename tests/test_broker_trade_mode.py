"""0031: a kötés-mód (csak jelzés / valódi) BRÓKERENKÉNT, és egy új brókeren
alapból CSAK JELZÉS.

⚠ A LELET (2026-09-30 12:08): a RoboForex motor az OTTHONI (ActivTrades) módot
látta; az AUDCHF-nek ott nem volt módja → alapérték VALÓDI kötés → a motor
élesben megpróbált egy AUDCHF SELL 0,09 lotot nyitni (csak a terminál
AutoTrading-tiltása állította meg), hangolatlanul, mért szerverzóna nélkül.
⚠ IDEIGLENES config — a valódi config.json-t a teszt nem írja.
"""
import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                          # noqa: E402
applog.harden_console()

from core import broker_profile as BP, trade_mode as TM         # noqa: E402
from strategy import settings as S                              # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


ALAP = {
    "trading": {},
    "brokers": [{"id": "act", "tag": "At", "server": "a", "login": 1},
                {"id": "rob", "tag": "Rob", "server": "b", "login": 2}],
    "pairs": {
        "AUDCHF": {"brokers": {"rob": {"run_state": {"wpr_sma": "live"}, "enabled": True}}},
        "GOLD": {"strategy_mode": {"csilla": "signal"},
                 "brokers": {"rob": {"run_state": {"wpr_sma": "live"}, "enabled": True,
                                     "strategy_mode": {"*": "signal", "wpr_sma": "live"}}}},
    },
}
ps = BP.profiles(ALAP)

# ── otthon: VÁLTOZATLAN ─────────────────────────────────────────────────
otthon = copy.deepcopy(ALAP)
BP.overlay_pairs(otthon, ps[0])
check("otthon: a hiányzó mód továbbra is VALÓDI (a régi viselkedés)",
      TM.mode_of(otthon, "AUDCHF", "wpr_sma") == TM.MODE_LIVE)
check("otthon: a beírt jelzés-mód marad", TM.is_signal_only(otthon, "GOLD", "csilla"))

# ── a második brókeren ──────────────────────────────────────────────────
rob = copy.deepcopy(ALAP)
BP.overlay_pairs(rob, ps[1])
check("⚠ Rob AUDCHF (sehol nincs mód): CSAK JELZÉS — nem az otthoni valódi",
      TM.is_signal_only(rob, "AUDCHF", "wpr_sma"))
check("Rob: minden más stratégia is csak jelez", TM.is_signal_only(rob, "AUDCHF", "csilla"))
check("Rob GOLD: a SAJÁT kifejezett valódi-kötése érvényes",
      TM.mode_of(rob, "GOLD", "wpr_sma") == TM.MODE_LIVE)
check("Rob GOLD: az otthoni jelzés-beállítás NEM szivárog át (a helyettesítő dönt)",
      TM.is_signal_only(rob, "GOLD", "csilla"))

# ── módváltás a második brókeren, és a mentés ───────────────────────────
TM.set_mode(rob, "AUDCHF", "wpr_sma", TM.MODE_LIVE)
check("valódira váltva KIFEJEZETT bejegyzés (a helyettesítő mellett)",
      rob["pairs"]["AUDCHF"]["strategy_mode"] == {"*": "signal", "wpr_sma": "live"},
      str(rob["pairs"]["AUDCHF"].get("strategy_mode")))
check("...és a kifejezett `live` érvényes érték (nem takarítandó maradék)",
      TM.stored_is_valid(rob, "AUDCHF", "wpr_sma"))
TM.set_mode(rob, "AUDCHF", "wpr_sma", TM.MODE_SIGNAL)
check("vissza jelzésre", TM.is_signal_only(rob, "AUDCHF", "wpr_sma"))
check("a jelzés-lista a helyettesítőt nem sorolja fel",
      all(n != TM.WILDCARD for _, n in TM.signal_only_pairs(rob)))

TMP = Path(tempfile.mkdtemp())
p = TMP / "config.json"
p.write_text(json.dumps(ALAP, ensure_ascii=False, indent=2), encoding="utf-8")
BP.set_override("rob")
try:
    cfg = S.load_config(p)
    check("betöltve (Rob motorja): AUDCHF csak jelzés", TM.is_signal_only(cfg, "AUDCHF", "wpr_sma"))
    TM.set_mode(cfg, "AUDCHF", "wpr_sma", TM.MODE_LIVE)
    S.write_config_file(cfg, p)
finally:
    BP.set_override(None)
ki = json.loads(p.read_text(encoding="utf-8"))
check("⚠ mentés: az OTTHONI pár nem kapott módot (az ActivTrades nem változott)",
      "strategy_mode" not in ki["pairs"]["AUDCHF"], str(ki["pairs"]["AUDCHF"]))
check("⚠ mentés: a Rob módváltása a Rob SAJÁT blokkjába került",
      ki["pairs"]["AUDCHF"]["brokers"]["rob"].get("strategy_mode", {}).get("wpr_sma") == "live",
      str(ki["pairs"]["AUDCHF"]["brokers"]["rob"]))
check("az otthoni GOLD jelzés-módja érintetlen",
      ki["pairs"]["GOLD"]["strategy_mode"] == {"csilla": "signal"})

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

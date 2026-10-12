"""Egy `brokers` lista + főszámla (`main`) + kikapcsolt bróker (`active`).

Tibi kérése (2026-10-12): a config-ban csak a `brokers` szekció legyen (a
régi `broker` blokk kikerült, a belső motor is a listából olvas); brókerenként
`main` (a főszámla — ha több van, az első számít) és `active` (kikapcsolva a
program sehol nem látja). Plusz: a kikapcsolt stratégia sora üres lehet.

⚠ A teszt a valódi config.json-t NEM olvassa és NEM írja — kézi dictekkel dolgozik.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                         # noqa: E402
applog.harden_console()

from core import broker_profile as B, broker_time as BT          # noqa: E402
from dashboard import canvas_cells as CC                         # noqa: E402
from dashboard.broker_header import show_broker_column           # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def br(i, **kw):
    d = {"id": i, "tag": i[:3], "name": i, "server": i + "-srv", "login": len(i) * 11,
         "magic": 100}
    d.update(kw)
    return d


AT, ROB, IC = "activtrades", "roboforex", "icmarkets"

# ── alapeset: jelzők nélkül = a régi viselkedés ──────────────────────────
c = {"brokers": [br(AT), br(ROB)]}
ps = B.profiles(c)
check("jelzők nélkül az első a főszámla", [p.id for p in ps] == [AT, ROB] and ps[0].home)
check("...és az alap-értékek gazdája is", ps[0].base and not ps[1].base)

# ── főszámla a második ────────────────────────────────────────────────────
c = {"brokers": [br(AT), br(ROB, main=True, magic=200, server_zone="America/New_York+7")]}
ps = B.profiles(c)
check("a főszámla kerül előre", [p.id for p in ps] == [ROB, AT], [p.id for p in ps])
check("...ő az otthoni (a felület saját motorja)", ps[0].home and not ps[1].home)
check("⚠ az ALAP-értékek gazdája NEM vált (különben a Rob motor az At Play/Stop-ját örökölné)",
      not ps[0].base and ps[1].base)
check("az aktív profil alapból a főszámla", B.active(c).id == ROB)
check("a magic az aktív brókeré (nem a régi `broker` blokkból)", B.magic_of(c) == 200)
check("a szerver-zóna is", BT.of_config(c).zone == "America/New_York")
_cfg = {"pairs": {"GOLD": {"point_size": 0.01, "run_state": {"x": "live"},
                           "brokers": {ROB: {"point_size": 0.1}}}}, **c}
B.overlay_pairs(_cfg, B.active(_cfg))
check("a főszámlára állított Rob a SAJÁT blokkjából kap értékeket",
      _cfg["pairs"]["GOLD"]["point_size"] == 0.1
      and _cfg["pairs"]["GOLD"]["run_state"] == {}, _cfg["pairs"]["GOLD"])

# ── több főszámla: az első számít ─────────────────────────────────────────
c = {"brokers": [br(AT), br(ROB, main=True), br(IC, main=True)]}
check("több `main`: az ELSŐ találat", B.profiles(c)[0].id == ROB)
check("...és a validate szól róla", any("főszámla" in h for h in B.validate(c)), B.validate(c))

# ── kikapcsolt bróker ─────────────────────────────────────────────────────
c = {"brokers": [br(AT, main=True), br(ROB, active=False)]}
ps = B.profiles(c)
check("a kikapcsolt bróker NEM látszik", [p.id for p in ps] == [AT])
check("...egy bróker marad → nincs bróker-oszlop", not show_broker_column(ps))
check("...de az all_profiles eléri (bezáráskor a motorja leállítható)",
      [p.id for p in B.all_profiles(c)] == [AT, ROB])
B.set_override(ROB)
try:
    B.active(c)
    ok = False
except ValueError:
    ok = True
finally:
    B.set_override(None)
check("`--broker` egy kikapcsolt brókerre: hiba (nem indul motor)", ok)

c = {"brokers": [br(AT, main=True, active=False), br(ROB)]}
ps = B.profiles(c)
check("kikapcsolt főszámla → az első aktív a főszámla", [p.id for p in ps] == [ROB] and ps[0].home)
check("...a kikapcsolt első bróker alap-értékei nem kerülnek a Robra", not ps[0].base)

c = {"brokers": [br(AT, active=False), br(ROB, active=False)]}
check("minden bróker kikapcsolva: a főszámla/első marad (bróker nélkül nincs mihez kapcsolódni)",
      [p.id for p in B.profiles(c)] == [AT])
check("...és a validate szól", any("ki van kapcsolva" in h for h in B.validate(c)))

# ── régi config (lista nélkül) továbbra is olvasható ─────────────────────
check("régi `broker` blokk: egy profil, a magic onnan",
      B.magic_of({"broker": {"magic": 7}}) == 7)

# ── a valódi config.json szerkezete (csak OLVASÁS) ──────────────────────
import json                                                      # noqa: E402
_p = ROOT / "config.example.json"
_ex = json.loads(_p.read_text(encoding="utf-8"))
check("a példa-configban nincs régi `broker`/`mt5` blokk",
      "broker" not in _ex and "mt5" not in _ex and _ex.get("brokers"))
check("...a példa brókere főszámla és aktív",
      _ex["brokers"][0].get("main") is True and _ex["brokers"][0].get("active") is True)

# ── kikapcsolt stratégia üres sora ───────────────────────────────────────
_d = {"symbol": "GOLD", "digits": 2, "strategies": [
    {"name": "a", "enabled": True, "stages": [], "position": {}, "daily": {}},
    {"name": "b", "enabled": False, "stages": [], "position": {}, "daily": {}}]}
_alap = CC.cells_for(_d, {})
_ures = CC.cells_for(_d, {"hide_disabled": True})
check("kapcsoló nélkül a kikapcsolt stratégia halvány cellái megvannak",
      "b|stages" in _alap and "b|ctrl" in _alap)
check("kapcsolóval a kikapcsolt stratégia blokkja ÜRES",
      not any(k.startswith("b|") for k in _ures))
check("...a bekapcsolt érintetlen", "a|stages" in _ures and "a|ctrl" in _ures)

print(f"\n{sum(results)}/{len(results)} PASS")
sys.exit(0 if all(results) else 1)

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

# ── FUTÁS KÖZBEN felvett pár (2026-10-13, BRENT) ──────────────────────────
import copy as _cp                                               # noqa: E402
_run = {"brokers": [br(AT), br(ROB, main=True)],
        "pairs": {"GOLD": {"point_size": 0.01, "run_state": {"x": "live"}}}}
B.overlay_pairs(_run, B.active(_run))
# a felület MOST vesz fel egy új párt, Play-t nyom rajta (a futásidejű dictben)
_run["pairs"]["BRENT"] = {"point_size": 0.01, "pv1_point": 10.0, "enabled": True,
                          "run_state": {"wpr_sma": "live"},
                          "strategy_mode": {"*": "signal"}, "strategies": ["wpr_sma"]}
_ki = B.restore_for_save(_cp.deepcopy(_run))["pairs"]["BRENT"]
check("új pár: a Play-állapot a FUTÓ bróker blokkjába kerül, nem az alapba",
      "run_state" not in _ki and _ki["brokers"][ROB]["run_state"] == {"wpr_sma": "live"}, _ki)
check("...a kötés-mód is", "strategy_mode" not in _ki
      and _ki["brokers"][ROB]["strategy_mode"] == {"*": "signal"})
check("...a pont-méret ODA is kerül, és az alapban is marad",
      _ki["brokers"][ROB]["point_size"] == 0.01 and _ki["point_size"] == 0.01)
check("...a stratégia-lista (nem bróker-függő) az alapban marad",
      _ki["strategies"] == ["wpr_sma"])
_ujra = _cp.deepcopy(B.restore_for_save(_cp.deepcopy(_run)))
B.overlay_pairs(_ujra, B.active(_ujra))
check("újraindítás után a Rob motor FUTÓNAK látja (nem leállítottnak)",
      _ujra["pairs"]["BRENT"]["run_state"] == {"wpr_sma": "live"})
_at = {**_cp.deepcopy(B.restore_for_save(_cp.deepcopy(_run))),
       "brokers": [br(AT, main=True), br(ROB)]}
B.overlay_pairs(_at, B.active(_at))
check("...az ActivTrades viszont NEM örökli a Rob-on nyomott Play-t",
      not _at["pairs"]["BRENT"].get("run_state"))

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
B.set_override(ROB, allow_inactive=True)
try:
    _p = B.active(c)
finally:
    B.set_override(None)
check("teszt/kutatás KIFEJEZETTEN kérheti a kikapcsolt bróker adatát",
      _p.id == ROB and _p.base is False)
check("...a felülírás visszavonása után újra a főszámla", B.active(c).id == AT)

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

# ── ismeretlen piacú instrumentumok szűrője ─────────────────────────────
from dashboard.row_source import filter_rows                    # noqa: E402
_rows = [{"symbol": "GOLD", "session": {"state": "open"}},
         {"symbol": "UK100", "session": {"state": "unknown"}},
         {"symbol": "Fra40", "session": {"state": "closed"}}]
check("alapból az ismeretlen is LÁTSZIK", len(filter_rows(_rows)) == 3)
check("pipával az ismeretlen eltűnik, a zárt piac marad",
      [r["symbol"] for r in filter_rows(_rows, hide_unknown=True)] == ["GOLD", "Fra40"])

print(f"\n{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

"""BRÓKER-ADAT ÉS SZÁMLA-ÁLLAPOT SZÉTVÁLASZTÁSA + bróker-függő instrumentum-értékek.

⚠ MIT ŐRZÜNK (0029 „Több bróker egyszerre", 3. lépés, 2026-09-28; az otthoni
  bróker átköltözése 2026-10-08):
  1. MINDEN BRÓKER — AZ OTTHONI IS: a feed a `data/brokers/<id>/`, a számla-
     állapot a `data/accounts/<id>/` alá kerül — a modulok SAJÁT útvonal-
     függvényein át is. Profil nélkül a config aktív (otthoni) profilja számít,
     a `TRADEFORGE_BROKER` környezeti változó felülírja. A kutatási kimenetek
     brókerenként külön: `data/research/<id>/`.
     A `data/`-n kívüli útvonal (a tesztek ideiglenes fájljai) érintetlen, és egy
     már áthelyezett útvonal nem duplázódik.
  3. A MENTÉS NEM KEVERHET: egy nem-otthoni bróker betöltéskor felülírt
     instrumentum-értékei (point_size, pv1, költség) a mentéskor NEM kerülnek az
     otthoni helyre; a futás közbeni módosítás a bróker saját blokkjába megy.
     ⚠ A teszt CSAK ideiglenes fájlba ír — a valódi config.json-t sosem érinti.
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

from core import broker_adapter as A                                     # noqa: E402
from core import broker_paths as BP                                      # noqa: E402
from core import broker_profile as P                                     # noqa: E402

_results, _fail = [], []


def check(name, ok, detail=""):
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


CFG = {"brokers": [{"id": "activtrades", "tag": "At", "server": "AT", "login": 1},
                   {"id": "roboforex", "tag": "Rob", "server": "RF", "login": 2,
                    "server_zone": "America/New_York+7", "symbols": {"GOLD": "XAUUSD"}}]}
HOME, ROBO = P.profiles(CFG)
D = BP.DATA
tmp = Path(tempfile.mkdtemp()) / "sajat.json"

# ---------------------------------------------------------------------------
print("== A profilok otthoni jelzoje ==")
check("a lista elso eleme az otthoni", HOME.home and not ROBO.home)
check("a regi config egyetlen profilja otthoni", P.active({"broker": {"login": 1}}).home)

print("\n== OTTHONI broker: a SAJAT mappajaban (2026-10-08) ==")
A.configure(HOME)
check("otthoni: feed data/brokers/activtrades/m1",
      BP.feed_dir("m1") == D / "brokers" / "activtrades" / "m1", str(BP.feed_dir("m1")))
check("otthoni: gyertya-fajl", BP.bars_file("m15", "GOLD")
      == D / "brokers" / "activtrades" / "m15" / "GOLD.parquet")
check("otthoni: trades.csv a szamla-mappaban",
      BP.account(BP.TRADES) == D / "accounts" / "activtrades" / "trades.csv")
check("otthoni: szamla-allapot", BP.account(D / "adopted_positions.json")
      == D / "accounts" / "activtrades" / "adopted_positions.json")
check("otthoni: kutatasi mappa", BP.research_dir() == D / "research" / "activtrades")
check("a kutatasi mappa NEM helyezodik at meg egyszer",
      BP.feed(D / "research" / "x.parquet") == D / "research" / "x.parquet")

print("\n== Profil NELKUL: a config aktiv profilja; TRADEFORGE_BROKER felulirja ==")
import os                                                                # noqa: E402
A.configure(None)
_cfg_regi = BP._config
BP._config = lambda: CFG                                # a valodi config.json-t NEM olvassuk
try:
    os.environ.pop(BP.ENV, None)
    check("nincs profil -> a config elso (otthoni) profilja",
          BP.feed_dir("m1") == D / "brokers" / "activtrades" / "m1", str(BP.feed_dir("m1")))
    os.environ[BP.ENV] = "roboforex"
    check("TRADEFORGE_BROKER=roboforex -> a roboforex gyertyai",
          BP.bars_file("m1", "GOLD") == D / "brokers" / "roboforex" / "m1" / "GOLD.parquet")
    check("TRADEFORGE_BROKER=roboforex -> a roboforex kutatasi mappaja",
          BP.research_dir() == D / "research" / "roboforex")
    os.environ[BP.ENV] = "nincsilyen"
    try:
        BP.feed_dir("m1")
        check("ismeretlen TRADEFORGE_BROKER -> ValueError (NEM csendes otthoni)", False)
    except ValueError:
        check("ismeretlen TRADEFORGE_BROKER -> ValueError (NEM csendes otthoni)", True)
    A.configure(ROBO)
    os.environ[BP.ENV] = "activtrades"
    check("a beallitott aktiv profil erosebb a kornyezeti valtozonal",
          BP.feed_dir("m1") == D / "brokers" / "roboforex" / "m1")
finally:
    os.environ.pop(BP.ENV, None)
    BP._config = _cfg_regi
    A.configure(None)

print("\n== MASIK broker: feed brokerenkent, allapot szamlankent ==")
A.configure(ROBO)
check("feed: data/brokers/roboforex/m1",
      BP.feed_dir("m1") == D / "brokers" / "roboforex" / "m1", str(BP.feed_dir("m1")))
check("gyertya-fajl", BP.bars_file("m1", "GOLD") == D / "brokers" / "roboforex" / "m1" / "GOLD.parquet")
check("trades.csv: data/accounts/roboforex/trades.csv",
      BP.account(BP.TRADES) == D / "accounts" / "roboforex" / "trades.csv")
check("szamla-allapot: data/accounts/roboforex/…",
      BP.account(D / "sl_moves") == D / "accounts" / "roboforex" / "sl_moves")
check("data/-n KIVULI utvonal (teszt ideiglenes fajlja) erintetlen", BP.account(tmp) == tmp)
m = BP.feed_dir("m1")
check("mar athelyezett utvonal NEM duplazodik", BP.feed(m) == m, str(BP.feed(m)))
check("explicit profil felulirja az aktivat",
      BP.feed_dir("m1", HOME) == D / "brokers" / "activtrades" / "m1")

print("\n== A modulok SAJAT utvonal-fuggvenyei is athelyeznek ==")
from core import adopted, position_meta, signal_delivery, mt5_connector   # noqa: E402
from strategy import signal_journal                                      # noqa: E402
from conductor import paths as cpaths                                    # noqa: E402
acc = D / "accounts" / "roboforex"
check("adopted", adopted._path() == acc / "adopted_positions.json", str(adopted._path()))
check("position_meta", position_meta._path() == acc / "position_meta.json")
check("signal_delivery", signal_delivery._path() == acc / "signal_delivery.csv")
check("karmester trades_csv", cpaths.trades_csv() == acc / "trades.csv", str(cpaths.trades_csv()))
check("karmester mappaja", cpaths.state_file().parent == acc / "conductor")
check("jelzes-naplo (feed)", signal_journal._dir() == D / "brokers" / "roboforex" / "signal_journal")
check("szerver-eltolas (feed)", mt5_connector._offset_file()
      == D / "brokers" / "roboforex" / "server_offset.json", str(mt5_connector._offset_file()))
_regi = adopted.PATH
adopted.PATH = tmp                                     # igy cserelnek a tesztek
check("a teszt allando-csereje tovabbra is ervenyes", adopted._path() == tmp)
adopted.PATH = _regi
A.configure(HOME)
check("otthoni: adopted a sajat szamla-mappajaban",
      adopted._path() == D / "accounts" / "activtrades" / "adopted_positions.json")
A.configure(None)

# ---------------------------------------------------------------------------
print("\n== Broker-fuggo instrumentum-ertekek: betoltes es MENTES ==")
cfg = dict(copy.deepcopy(CFG), pairs={
    "GOLD": {"point_size": 0.01, "pv1_point": 0.88, "min_lot": 0.01,
             "brokers": {"roboforex": {"point_size": 0.001, "pv1_point": 0.1,
                                       "commission_per_lot": 7.0}}},
    "EURUSD": {"point_size": 1e-05, "enabled": True,
               "run_state": {"wpr_sma": "live"}}})
alap = copy.deepcopy(cfg)

P.overlay_pairs(cfg, HOME)
check("otthoni broker: NINCS felulirás", cfg == alap)

P.overlay_pairs(cfg, ROBO)
g = cfg["pairs"]["GOLD"]
check("roboforex: a GOLD a broker ertekeivel", (g["point_size"], g["pv1_point"],
      g["commission_per_lot"]) == (0.001, 0.1, 7.0), str(g))
check("a nem erintett kulcs (min_lot) marad", g["min_lot"] == 0.01)
e = cfg["pairs"]["EURUSD"]
check("broker-blokk nelkuli par: az instrumentum-ertek marad", e["point_size"] == 1e-05)
check("SZANDEK: a nem-otthoni broker NEM orokli az otthoni Play-t (leallitva)",
      e["enabled"] is False and e["run_state"] == {}, str(e))

ki = P.restore_for_save(copy.deepcopy(cfg))
check("mentes: az OTTHONI ertekek vissza", (ki["pairs"]["GOLD"]["point_size"],
      ki["pairs"]["GOLD"]["pv1_point"]) == (0.01, 0.88))
check("mentes: az alapban NEM volt kulcs (jutalek) nem kerul be",
      "commission_per_lot" not in ki["pairs"]["GOLD"])
check("mentes: a broker blokkja valtozatlan",
      ki["pairs"]["GOLD"]["brokers"]["roboforex"]
      == {"point_size": 0.001, "pv1_point": 0.1, "commission_per_lot": 7.0})
check("mentes: a rejtett kulcs eltunt", P.OVERLAY_KEY not in ki)
check("mentes == az eredeti fajl", ki == alap)

cfg["pairs"]["GOLD"]["pv1_point"] = 0.12               # futas kozben modosult
ki = P.restore_for_save(copy.deepcopy(cfg))
check("futas kozbeni modositas a BROKER blokkjaba kerul",
      ki["pairs"]["GOLD"]["brokers"]["roboforex"]["pv1_point"] == 0.12
      and ki["pairs"]["GOLD"]["pv1_point"] == 0.88)

print("\n== A kereskedesi SZANDEK brokerenkent ==")
from core import run_state as RS                                         # noqa: E402
RS.set_state(cfg, "EURUSD", "wpr_sma", RS.LIVE)        # Play a roboforex motoron
ki = P.restore_for_save(copy.deepcopy(cfg))
e = ki["pairs"]["EURUSD"]
check("Play a roboforexen -> a SAJAT blokkjaba",
      e["brokers"]["roboforex"]["run_state"] == {"wpr_sma": "live"}, str(e))
check("... es az OTTHONI szandek erintetlen", e["run_state"] == {"wpr_sma": "live"}
      and e["enabled"] is True)
cfg2 = copy.deepcopy(ki)
P.overlay_pairs(cfg2, ROBO)
check("ujratoltes: a roboforex a SAJAT szandekaval indul",
      cfg2["pairs"]["EURUSD"]["run_state"] == {"wpr_sma": "live"})
check("... es ami ott nincs (GOLD), az leallitva",
      cfg2["pairs"]["GOLD"]["run_state"] == {} and cfg2["pairs"]["GOLD"]["enabled"] is False)

print("\n== A --broker valasztas (futasideju, NEM a configba) ==")
P.set_override("roboforex")
check("--broker roboforex -> az aktiv", P.active(CFG).id == "roboforex")
P.set_override("nincsilyen")
try:
    P.active(CFG)
    check("ismeretlen --broker -> ValueError (NEM csendes otthoni visszaeses)", False)
except ValueError:
    check("ismeretlen --broker -> ValueError (NEM csendes otthoni visszaeses)", True)
P.set_override(None)
check("felulirás nelkul az elso", P.active(CFG).id == "activtrades")

from strategy import settings                                            # noqa: E402
hiba = settings.write_config_file(cfg, tmp)
iras = json.loads(tmp.read_text(encoding="utf-8"))
check("write_config_file (IDEIGLENES fajlba): az otthoni ertekek irodnak",
      hiba == "" and iras["pairs"]["GOLD"]["point_size"] == 0.01, hiba)
check("write_config_file: a hivo dictje NEM modosult",
      cfg["pairs"]["GOLD"]["point_size"] == 0.001 and P.OVERLAY_KEY in cfg)

pc = {"point_size": 0.01}
P.write_target(pc, ROBO)["commission_per_lot"] = 7.0
check("eszkoz-iras nem-otthoni brokernel a blokkba",
      pc == {"point_size": 0.01, "brokers": {"roboforex": {"commission_per_lot": 7.0}}})
check("eszkoz-iras otthoni brokernel a parba", P.write_target(pc, HOME) is pc)

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)

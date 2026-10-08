"""MOTOR-ÁLLAPOTKÉP + BRÓKEREK fül (olvasó mód) + a --broker választás.

⚠ MIT ŐRZÜNK (0029 „Több bróker egyszerre", 4. lépés, 2026-09-28):
  1. A kép a konzol KÖZÖS soraiból épül, és JSON-ná alakul akkor is, ha a
     pozíciókban datetime / nem-JSON szám van (különben a közzététel némán
     elhallgatna).
  2. Az ÉLETJEL mért adatból: nincs fájl → nincs; rendes leállás → áll;
     ELAVULT kép / halott szál / nincs MT5 → hibás; különben fut. Egy zöld pont,
     ami nem néz semmit, rosszabb a semminél.
  3. A közzétevő leállításkor a „rendben leállt" képet írja — ebből különbözik
     a leállás az összeomlástól.
  4. Ismeretlen `--broker` → KILÉPÉS (2-es kód), NEM csendes visszaesés az
     otthoni brókerre (a második motor azzal az otthoni számlán kereskedne).
⚠ A teszt a valódi data/ mappába NEM ír: ideiglenes fájlokkal dolgozik.
"""
import sys
import json
import time
import tempfile
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                                  # noqa: E402
applog.harden_console()

from core import console_cmd as C                                        # noqa: E402
from core import engine_status as ES                                     # noqa: E402
from core import broker_profile as P                                     # noqa: E402

_results, _fail = [], []


def check(name, ok, detail=""):
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


CFG = {"brokers": [{"id": "activtrades", "tag": "At", "server": "AT", "login": 1},
                   {"id": "roboforex", "tag": "Rob", "name": "RoboForex",
                    "server": "RF-Pro", "login": 555}],
       "pairs": {"GOLD": {"run_state": {"wpr_sma": "live"}}}}
HOME, ROBO = P.profiles(CFG)
TMP = Path(tempfile.mkdtemp())

POZ = [{"ticket": 7, "symbol": "GOLD", "type": "BUY", "volume": 0.1,
        "price_open": 2400.5, "sl": 2390.0, "tp": 0.0, "profit": 12.3,
        "opened": dt.datetime(2026, 9, 28, 10, 0)}]


def ctx(alive=True, mt5=True, cycle=None):
    return C.Context(cfg=CFG, save_config=lambda: True, positions=lambda: POZ,
                     close_position=lambda t: False,
                     account=lambda: {"balance": 1000.0, "currency": "USD",
                                      "daily_pnl": -5.5},
                     dashboard={}, instrument_state={"GOLD": "RUN"},
                     strategies_of=lambda s: ["wpr_sma"],
                     engine_alive=lambda: alive, mt5_ok=lambda: mt5,
                     last_cycle_ts=lambda: (time.time() - 3) if cycle is None else cycle)


# ---------------------------------------------------------------------------
print("== A kep a konzol kozos soraibol ==")
s = ES.snapshot(ctx(), ROBO, server_offset_sec=10800.0)
check("bróker-azonosítás", s["broker"]["id"] == "roboforex" and s["broker"]["tag"] == "Rob")
check("szamla", s["account"]["balance"] == 1000.0 and s["account"]["daily_pnl"] == -5.5)
check("parok (a konzol pair_rows-a)", s["pairs"][0]["symbol"] == "GOLD"
      and s["pairs"][0]["strategies"] == [["wpr_sma", True]], str(s["pairs"]))
check("poziciok", s["positions"][0]["ticket"] == 7)
check("datetime a poziciokban -> JSON-barat", isinstance(json.dumps(s), str)
      and isinstance(s["positions"][0]["opened"], str))
check("eletjel mezok", s["engine_alive"] and s["mt5_ok"] and s["last_cycle_age"] >= 0)

print("\n== Az ELETJEL erteklese ==")
most = time.time()
check("nincs fajl -> nincs", ES.health(None, most) == ES.NINCS)
check("rendes leallas -> all", ES.health(dict(s, stopped=True), most) == ES.ALL)
check("friss, elo -> fut", ES.health(s, s["ts"] + 1) == ES.FUT)
check("ELAVULT kep (osszeomlott motor) -> hibas",
      ES.health(s, s["ts"] + ES.STALE_SEC + 1) == ES.HIBAS)
check("halott kereskedo szal -> hibas",
      ES.health(ES.snapshot(ctx(alive=False), ROBO)) == ES.HIBAS)
check("nincs MT5 -> hibas", ES.health(ES.snapshot(ctx(mt5=False), ROBO)) == ES.HIBAS)

ora = ES.server_clock({"server_offset_sec": 10800.0},
                      now=(dt.datetime(2026, 9, 28, 8, 23) - dt.datetime(1970, 1, 1)).total_seconds())
check("szerveriora: UTC 08:23 + 3 ora = 11:23", ora.strftime("%H:%M") == "11:23", str(ora))
check("eltolas nelkul nincs ora", ES.server_clock({"server_offset_sec": None}) is None)

print("\n== Az allapotfajl helye ==")
check("otthoni: data/accounts/<otthoni>/engine_status.json (2026-10-08 ota az otthoni is)",
      ES.path(HOME).parts[-3:] == ("accounts", HOME.id, "engine_status.json"), str(ES.path(HOME)))
check("roboforex: data/accounts/roboforex/engine_status.json",
      ES.path(ROBO).parts[-3:] == ("accounts", "roboforex", "engine_status.json"),
      str(ES.path(ROBO)))

print("\n== A kozzetevo (IDEIGLENES fajlba) ==")
pub = ES.Publisher(ctx(), ROBO, offset_fn=lambda: 7200.0, period=0.05)
pub.p = TMP / "engine_status.json"
pub.start()
time.sleep(0.3)
elo = json.loads(pub.p.read_text(encoding="utf-8"))
check("futas kozben ir, stopped=False", elo["stopped"] is False and elo["server_offset_sec"] == 7200.0)
pub.stop()
veg = json.loads(pub.p.read_text(encoding="utf-8"))
check("leallitaskor a VEGSO kep: stopped=True -> all", ES.health(veg) == ES.ALL)
check("nem maradt felig irt .tmp", not (TMP / "engine_status.tmp").exists())

# ⚠ WINDOWS csere-verseny: az iro es egy folyamatos olvaso EGYSZERRE — az elso
# futason „hozzaferes megtagadva" jott. Az olvaso SOSEM kaphat None-t, amig a
# fajl letezik.
import threading                                                         # noqa: E402
hibak, nonek = [], [0]
cel = TMP / "verseny.json"
ES.write({"ts": 1}, cel)


def _iro():
    for i in range(150):
        try:
            ES.write({"ts": i}, cel)
        except Exception as ex:
            hibak.append(ex)


t = threading.Thread(target=_iro)
t.start()
while t.is_alive():
    if ES.read(p=cel) is None:
        nonek[0] += 1
t.join()
check("iras-olvasas verseny: az iro nem bukik", not hibak, str(hibak[:1]))
check("iras-olvasas verseny: az olvaso sosem kap None-t", nonek[0] == 0, str(nonek[0]))

print("\n== A BROKEREK ful adat-sorai ==")
from dashboard import brokers_tab as BT                                  # noqa: E402
sorok = BT.rows([ROBO], now=s["ts"] + 2, reader=lambda p: s)
r = sorok[0]
check("sor: cimke, allapot, egyenleg, pozicioszam",
      (r["tag"], r["health"], r["n_pos"]) == ("Rob", ES.FUT, 1) and "1,000.00" in r["balance"],
      str(r))
check("a poziciok a broker cimkejevel", r["positions"][0]["tag"] == "Rob")
check("szamla-szoveg", r["account"] == "#555 RF-Pro")
ures = BT.rows([ROBO], reader=lambda p: None)[0]
check("kep nelkul: nincs adat, kotojelek", ures["health"] == ES.NINCS and ures["clock"] == "—")

print("\n== A ful felepul (Tk, hamis keppel) ==")
import tkinter as tk                                                     # noqa: E402
_regi_read = ES.read
ES.read = lambda p=None, **kw: dict(s, ts=time.time())
try:
    root = tk.Tk(); root.withdraw()
    fr = tk.Frame(root); fr.pack()
    tab = BT.BrokersTab(fr, profiles_provider=lambda: [ROBO],
                        running=lambda p: True)      # a hamis kep motorja „el"
    root.update_idletasks()
    szovegek = [w.cget("text") for sor in tab._fo.winfo_children()
                for w in sor.winfo_children()]
    check("a fo sor kirajzolva (cimke + allapot)", "Rob" in szovegek
          and any("fut" in x or "running" in x for x in szovegek), str(szovegek))
    check("a pozicio-sor kirajzolva", len(tab._poz.winfo_children()) == 1)
    root.destroy()
finally:
    ES.read = _regi_read

print("\n== Ismeretlen --broker -> KILEPES ==")
import main as M                                                         # noqa: E402
cfgf = TMP / "config.json"
cfgf.write_text(json.dumps(CFG), encoding="utf-8")
_regi_path, _regi_argv = M.CFG_PATH, list(sys.argv)
M.CFG_PATH = cfgf
sys.argv = ["main.py", "console", "--broker", "nincsilyen"]
try:
    M.load_cfg()
    check("ismeretlen --broker -> SystemExit(2)", False, "nem lepett ki")
except SystemExit as e:
    check("ismeretlen --broker -> SystemExit(2)", e.code == 2, str(e.code))
finally:
    M.CFG_PATH, sys.argv = _regi_path, _regi_argv
    P.set_override(None)
check("a config fajl erintetlen (a --broker nem irodik bele)",
      json.loads(cfgf.read_text(encoding="utf-8")) == CFG)

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)

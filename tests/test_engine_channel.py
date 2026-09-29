"""VEZERLO CSATORNA a broker-motorhoz + a Brokerek ful vezerlese (0029, 4b).

⚠ MIT ORZUNK (2026-09-28):
  1. A SZABALYOK A KOZOS PARANCS-RETEGBEN: a zaras megerosites NELKUL NEM
     hajtodik vegre — a motor a kerdest adja vissza; csak a megerositett
     masodik kuldes zar. A Play/Stop ugyanazt a run_state-et irja, mint a konzol.
  2. ELAVULT parancs (a motor tul kesobb veszi fel) NEM fut le — egy orakkal
     korabbi "close all" nem sulhet el ujrainditas utan.
  3. Csak az ENGEDELYEZETT parancsok futnak tavolrol.
  4. Valasz nelkuli keres (a motor nem fut) -> None, es a parancs VISSZAVONVA
     (nem marad a postaladaban egy kesobbi indulasra).
  5. A ful: megerosito kerdesnel rakerdez; "nem"-re NEM kuld masodszor.
⚠ A teszt CSAK ideiglenes postaladakat hasznal.
"""
import sys
import time
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                                  # noqa: E402
applog.harden_console()

from core import console_cmd as C                                        # noqa: E402
from core import engine_channel as CH                                    # noqa: E402
from core import broker_profile as P                                     # noqa: E402
from core import run_state as RS                                         # noqa: E402

_results, _fail = [], []


def check(name, ok, detail=""):
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


PROFS = P.profiles({"brokers": [{"id": "activtrades", "tag": "At"},
                                {"id": "roboforex", "tag": "Rob", "name": "RoboForex"}]})
ROBO = PROFS[1]
TMP = Path(tempfile.mkdtemp())
IB, OB = TMP / "in", TMP / "out"

CFG = {"pairs": {"GOLD": {"enabled": False, "run_state": {}, "strategies": ["wpr_sma"]}}}
ZART, MENTES = [], [0]


def _mentes():
    MENTES[0] += 1
    return True


ctx = C.Context(cfg=CFG, save_config=_mentes,
                positions=lambda: [{"ticket": 12345, "symbol": "GOLD", "type": "BUY",
                                    "volume": 0.1, "profit": 1.0}],
                close_position=lambda t: ZART.append(t) or True,
                account=dict, dashboard={}, instrument_state={},
                strategies_of=lambda s: ["wpr_sma"])


def kuld(line, confirmed=False, kor=0.0):
    return CH.send(ROBO, line, confirmed, now=time.time() - kor, inbox=IB)


def feldolgoz():
    return {v["id"]: v for v in CH.process_once(ctx, ROBO, inbox=IB, outbox=OB)}


# ---------------------------------------------------------------------------
print("== Zaras: a megerosites a MOTORBOL jon ==")
a = kuld("close 12345")
v = feldolgoz()[a]
check("megerosites nelkul NEM zar", ZART == [] and v["confirm"], str(v))
check("a kerdes a parancs-retege (jegy + szimbolum)",
      "12345" in v["confirm"] and "GOLD" in v["confirm"], v["confirm"])
b = kuld("close 12345", confirmed=True)
v = feldolgoz()[b]
check("megerositve zar", ZART == [12345] and v["ok"], str(v))
check("a valasz a kimeno postaladaban", CH.result(ROBO, b, outbox=OB)["id"] == b)
check("a valasz olvasas utan torlodik", CH.result(ROBO, b, outbox=OB) is None)

print("\n== Play/Stop: ugyanaz a run_state, mint a konzolon ==")
c = kuld("play GOLD wpr_sma")
v = feldolgoz()[c]
check("play -> a szandek live", RS.get_state(CFG, "GOLD", "wpr_sma") == RS.LIVE, str(v))
check("... es a config mentve (a motor sajat utjan)", MENTES[0] >= 1)
d = kuld("stop GOLD wpr_sma")
v = feldolgoz()[d]
if v.get("confirm"):                  # a stop rakerdezhet (kivezetes) — megerositjuk
    kuld("stop GOLD wpr_sma", confirmed=True)
    feldolgoz()
check("stop -> a szandek stopped", RS.get_state(CFG, "GOLD", "wpr_sma") == RS.STOPPED)

print("\n== Elavult es tiltott parancs ==")
ZART.clear()
e = kuld("close 12345", confirmed=True, kor=CH.MAX_AGE_SEC + 5)
v = feldolgoz()[e]
check("ELAVULT megerositett zaras NEM fut le", ZART == [] and v.get("reason") == "stale", str(v))
f = kuld("photo GOLD")
check("nem engedelyezett parancs elutasitva", feldolgoz()[f].get("reason") == "not_allowed")
g = kuld("karmester on")
check("karmester sem futhat tavolrol", feldolgoz()[g].get("reason") == "not_allowed")
check("a feldolgozott parancsok eltuntek a postaladabol", not list(IB.glob("*.json")))

print("\n== Keres valasz nelkul (a motor nem fut) ==")
t0 = time.time()
r = CH.request(ROBO, "pos", timeout=0.5, inbox=IB, outbox=OB)
check("None a timeout utan", r is None and time.time() - t0 < 3)
check("a parancs VISSZAVONVA (nem marad kesobbi indulasra)", not list(IB.glob("*.json")))

print("\n== Vegigjatszva: Processor szal + request ==")
kilepett = []
proc = CH.Processor(ctx, ROBO, on_quit=lambda: kilepett.append(1), period=0.05,
                    inbox=IB, outbox=OB).start()
r = CH.request(ROBO, "pos", timeout=5, inbox=IB, outbox=OB)
check("a motor valaszol (pos)",
      r is not None and r["ok"] and any("12345" in x for x in r["lines"]), str(r))
r = CH.request(ROBO, "quit", timeout=5, inbox=IB, outbox=OB)
time.sleep(0.2)
check("quit -> a motor rendes kilepese hivodik", r is not None and r["quit"] and kilepett == [1])
proc.stop()

print("\n== A ful: rakerdez, es nem-re nem kuld masodszor ==")
import tkinter as tk                                                     # noqa: E402
from dashboard import brokers_tab as BT                                  # noqa: E402
check("Play/Stop gomb parancssora",
      BT.toggle_line("GOLD", "wpr_sma", False) == "play GOLD wpr_sma"
      and BT.toggle_line("GOLD", "wpr_sma", True) == "stop GOLD wpr_sma")
hivasok = []


def hamis_request(p, line, megerositve):
    hivasok.append((line, megerositve))
    return ({"ok": True, "lines": [], "confirm": "Biztos?"} if not megerositve
            else {"ok": True, "lines": ["kesz"], "confirm": ""})


root = tk.Tk()
root.withdraw()
for valasz, vart in ((True, [("close 1", False), ("close 1", True)]),
                     (False, [("close 1", False)])):
    hivasok.clear()
    fr = tk.Frame(root)
    tab = BT.BrokersTab(fr, profiles_provider=lambda: [], confirm=lambda s: valasz,
                        request=hamis_request)
    tab.send(ROBO, "close 1")
    vege = time.time() + 3
    while time.time() < vege and len(hivasok) < len(vart):
        root.update()
        time.sleep(0.02)
    for _ in range(20):
        root.update()
        time.sleep(0.01)
    check(f"megerosites={'igen' if valasz else 'nem'}: {len(vart)} kuldes",
          hivasok == vart, str(hivasok))
    if valasz:
        check("az allapotsor a motor valaszat mutatja",
              "kesz" in tab._lbl_statusz.cget("text"), tab._lbl_statusz.cget("text"))
    fr.destroy()
root.destroy()

print("\n== Arva valaszok takaritasa (demo-proba, 2026-09-29) ==")
# ⚠ Induláskor a felulet mar kerdez, a motor meg kapcsolodik: a keso valasz a
# kimeno postaladaban marad — a motor ORPHAN_SEC utan torli.
import os                                                                # noqa: E402
OB.mkdir(parents=True, exist_ok=True)
regi_f, friss_f = OB / "regi.json", OB / "friss.json"
regi_f.write_text("{}", encoding="utf-8")
friss_f.write_text("{}", encoding="utf-8")
os.utime(regi_f, (time.time() - CH.ORPHAN_SEC - 10,) * 2)
CH.process_once(ctx, ROBO, inbox=IB, outbox=OB)
check("a regi arva valasz torolve", not regi_f.exists())
check("a friss valasz (meg varhatnak ra) megmarad", friss_f.exists())

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)

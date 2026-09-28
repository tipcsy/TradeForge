"""TAVOLI MOD a feluleten + az allapotfajlok ujratoltese (0029, 4b/3 S3a).

⚠ MIT ORZUNK (2026-09-28):
  1. Az allapot-modulok (itt: rr_state) egy MASIK processz modositasat
     ujratoltessel latjak; valtozatlan fajlnal nincs ujratoltes; eltunt fajlnal
     a memoria marad (nem nullazunk).
  2. A kozos tavoli-parancs segéd: a mar megerositett parancs EGYSZER megy ki.
  3. A felulet TAVOLI modban a Play/Stop/zarast a CSATORNARA kuldi, es helyben
     NEM nyul se a kozos retegre, se az MT5-re; helyi modban (a mai ut) nem kuld
     semmit a csatornara.
⚠ Az rr_state utvonala ideiglenes fajlra van allitva — a valodi data/-t nem erinti.
"""
import sys
import json
import time
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                                  # noqa: E402
applog.harden_console()

from core import state_reload as SR                                      # noqa: E402
from core import rr_state as RR                                          # noqa: E402

_results, _fail = [], []


def check(name, ok, detail=""):
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


TMP = Path(tempfile.mkdtemp())
_regi_path = RR.PATH
RR.PATH = TMP / "risk_mode.json"
try:
    print("== Allapotfajl-ujratoltes (rr_state) ==")
    RR.PATH.write_text(json.dumps({"GOLD": {"preset": "shield"}}), encoding="utf-8")
    RR.load()
    SR._utolso.clear()
    check("elso megfigyeles: nincs ujratoltes (a modul mar betoltott)",
          SR.refresh_all(("core.rr_state",)) == [])
    check("valtozatlan fajl -> nincs ujratoltes", SR.refresh_all(("core.rr_state",)) == [])
    time.sleep(0.02)
    RR.PATH.write_text(json.dumps({"GOLD": {"preset": "halving"}}), encoding="utf-8")
    check("masik processz modositott -> ujratoltes",
          SR.refresh_all(("core.rr_state",)) == ["core.rr_state"])
    check("... es a memoria az uj erteket tartja", RR._state["GOLD"]["preset"] == "halving",
          str(RR._state.get("GOLD")))
    RR.PATH.unlink()
    SR.refresh_all(("core.rr_state",))
    check("eltunt fajl: a memoria MARAD", RR._state.get("GOLD", {}).get("preset") == "halving")
    check("be nem toltott modul kimarad", SR.refresh_all(("core.nincs_ilyen_modul",)) == [])
finally:
    RR.PATH = _regi_path
    RR.load()

print("\n== A kozos tavoli-parancs seged ==")
import tkinter as tk                                                     # noqa: E402
from dashboard import remote_cmd as RC                                   # noqa: E402
root = tk.Tk()
root.withdraw()
pump = RC.Pump(root)
hivasok, eredm = [], []
RC.send(pump, object(), "close 5", confirm=lambda s: True,
        on_result=lambda r, m: eredm.append((r, m)), confirmed=True,
        request=lambda p, l, c: hivasok.append((l, c)) or {"ok": True, "lines": ["ok"]})
vege = time.time() + 3
while time.time() < vege and not eredm:
    root.update()
    time.sleep(0.02)
check("mar megerositett: EGYSZER megy, megerositve", hivasok == [("close 5", True)], str(hivasok))
check("az eredmeny a foszalon megerkezett", eredm and eredm[0][1] is False)

print("\n== A felulet agai (az ablak felepitese nelkul) ==")
from dashboard.gui import DashboardWindow as W                           # noqa: E402


class Hamis:
    """A DashboardWindow metodusainak eleg ennyi — a teljes ablak nem kell."""

    def __init__(self, remote):
        self._remote = remote
        self.kuldott = []
        self._mt5_cache = {"positions_detail": [{"ticket": 1}, {"ticket": 2}]}

    def _remote_cmd(self, line, confirmed=False):
        self.kuldott.append((line, confirmed))

    def _confirm(self, *a, **k):
        return True

    def _cmd_ctx(self):
        raise AssertionError("tavoli modban a helyi kozos reteget NEM szabad hivni")


h = Hamis(remote=object())
W._run_play(h, "GOLD", ["wpr_sma", "bollinger"])
check("Play: strategiankent a csatornara", h.kuldott == [("play GOLD wpr_sma", False),
                                                          ("play GOLD bollinger", False)], str(h.kuldott))
h.kuldott.clear()
W._run_stop(h, "GOLD", ["wpr_sma"])
check("Stop: a csatornara, MEGEROSITES NELKUL (a motor kerdez, ha kell)",
      h.kuldott == [("stop GOLD wpr_sma", False)], str(h.kuldott))
h.kuldott.clear()
W._pos_panic(h, 12345)
check("Zaras: a csatornara, megerositve (a felulet mar rakerdezett)",
      h.kuldott == [("close 12345", True)], str(h.kuldott))
h.kuldott.clear()
W._pos_close_all(h)
check("Mindet zar: EGY parancs (close all), megerositve", h.kuldott == [("close all", True)])
root.destroy()

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)

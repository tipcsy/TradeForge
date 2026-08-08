"""Indulaskor toltodjon a leallas alatt keletkezett elozmeny-res (gap).

Keres: "Amikor betoltom a programot, akkor egy hatterszal toltse le a GAP-et."

Miert szamit? A leallas alatt keletkezett res NEM latszik sehol — a `wpr_sma`
M15-ablaka viszont MELY warmupot ker, tehat a hianyzo gyertyak NEMAN mas jelzest
adnak, mint az el. Eddig a potlas csak akkor futott le, amikor egy Backtest/Opt
mar beleutkozott.

A masik fele (uj instrumentum -> auto letoltes) v1.42.0 ota mar megvolt; ez a
teszt azt is orzi, hogy meg ne kopjon.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


GUI_SRC = (Path(__file__).resolve().parents[1] / "dashboard" / "gui.py").read_text(
    encoding="utf-8")

# ── 1. Az indito hurok bekoti a gap-toltest ───────────────────────────────
run_pos = GUI_SRC.index("    def run(self):")
run_body = GUI_SRC[run_pos:run_pos + 1200]
check("a run() elinditja az indulasi gap-toltest",
      "_start_startup_gap_fill" in run_body)
check("config-kapcsolo van ra (data.gap_fill_on_start)",
      "gap_fill_on_start" in run_body)
check("az alapertelmezes BE (a kapcsolo hianya ne nemitsa el)",
      'gap_fill_on_start", True' in run_body)
check("kesleltetve indul (az ablak eloszor rajzolodjon ki)",
      "after(2000" in run_body)

# ── 2. Uj instrumentum -> auto letoltes (regota megvan, ne kopjon ki) ──────
check("uj instrumentum felvetele is inditja a letoltest",
      "self._start_history_download(symbol)" in GUI_SRC)

# ── 3. A gap-toltes a KOZOS uton megy (kulon processz + fajl-zar) ─────────
gap_pos = GUI_SRC.index("    def _start_startup_gap_fill(self):")
gap_body = GUI_SRC[gap_pos:gap_pos + 1800]
check("a kozos _start_history_download-ot hivja (nem sajat letolto ut)",
      "_start_history_download(" in gap_body)
check("csak az ENGEDELYEZETT parokat sorolja",
      'p.get("enabled", False)' in gap_body)

# ── 4. Funkcionalis: sorosan halad, paronkent EGYSZER ─────────────────────
# A metodust a peldany nelkul hivjuk (a GUI-t nem epitjuk fel): csak a `cfg`-t
# es a `_start_history_download`-ot hasznalja.
from dashboard.gui import DashboardWindow


class FakeGui:
    def __init__(self, cfg):
        self.cfg = cfg
        self.calls = []
        self.pending_cb = None

    def _start_history_download(self, symbol, on_done=None):
        self.calls.append(symbol)
        self.pending_cb = on_done


CFG = {"pairs": {
    "AAA": {"enabled": True},
    "BBB": {"enabled": False},      # kikapcsolt -> kimarad
    "CCC": {"enabled": True},
    "_comment": "nem par",           # nem dict -> kimarad
}}

g = FakeGui(CFG)
DashboardWindow._start_startup_gap_fill(g)
check("elsokent EGY par indul (sorosan, nem mind egyszerre)",
      g.calls == ["AAA"], str(g.calls))

g.pending_cb(True, "")               # az elso kesz -> jojjon a kovetkezo
check("a callback inditja a kovetkezot", g.calls == ["AAA", "CCC"], str(g.calls))

cb = g.pending_cb
cb(True, "")                          # nincs tobb -> ne induljon ujabb
check("a lista vegen megall", g.calls == ["AAA", "CCC"], str(g.calls))

check("a kikapcsolt par kimaradt", "BBB" not in g.calls)
check("a _comment kulcs nem lett par", "_comment" not in g.calls)

# Hibas letoltes se akassza meg a sort.
g2 = FakeGui({"pairs": {"P1": {"enabled": True}, "P2": {"enabled": True}}})
DashboardWindow._start_startup_gap_fill(g2)
g2.pending_cb(False, "hiba")
check("egy SIKERTELEN letoltes utan is folytatodik a sor",
      g2.calls == ["P1", "P2"], str(g2.calls))

# Nincs aktiv par -> ne inditson semmit.
g3 = FakeGui({"pairs": {"X": {"enabled": False}}})
DashboardWindow._start_startup_gap_fill(g3)
check("nincs aktiv par -> nem indul letoltes", g3.calls == [])

g4 = FakeGui({})
DashboardWindow._start_startup_gap_fill(g4)
check("hianyzo 'pairs' kulcs -> nem hasal el", g4.calls == [])

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

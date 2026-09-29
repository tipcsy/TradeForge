"""0029/5a: a fejléc bróker-órái.

Tibi kérése (2026-09-28): „Bróker helyett: ActivTrader: 11:23.. Ha van több,
akkor alatta Roboforex: 11:23 (még ha ugyanaz is!)".
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                         # noqa: E402
applog.harden_console()

from dashboard.broker_header import clock_text                 # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


most = datetime(2026, 9, 29, 19, 25, 7, tzinfo=timezone.utc)
at = NS(id="activtrades", name="ActivTrades")
rob = NS(id="roboforex", name="RoboForex")

egy = clock_text([at], {"activtrades": 7200}, most)
check("egy bróker: EGY sor", "\n" not in egy, egy)
check("...a bróker NEVE és a szerverideje (nem „Bróker”)", egy.startswith("ActivTrades: 21:25:07"), egy)
check("...és az UTC is", "UTC 19:25" in egy, egy)

ket = clock_text([at, rob], {"activtrades": 7200, "roboforex": 7200}, most)
sorok = ket.split("\n")
check("két bróker: KÉT sor", len(sorok) == 2, repr(ket))
check("⚠ azonos idő mellett is külön sor, mindkettő névvel",
      sorok[0].startswith("ActivTrades: 21:25:07")
      and sorok[1] == "RoboForex: 21:25:07", repr(ket))
check("az UTC csak egyszer (az első sorban)", ket.count("UTC") == 1)

mas = clock_text([at, rob], {"activtrades": 7200, "roboforex": 10800}, most)
check("eltérő zóna: mindegyik a SAJÁT idejét", mas.split("\n")[1] == "RoboForex: 22:25:07", mas)

nem = clock_text([at, rob], {"activtrades": 7200}, most)
check("ismeretlen idő (nem fut a motorja): „—”, nem hamis idő",
      nem.split("\n")[1] == "RoboForex: —", nem)
check("az otthoni ideje sem ismert: akkor is látszik a név",
      clock_text([at], {}, most).startswith("ActivTrades: —"))

_g = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
check("a felület ezt a függvényt használja", "clock_text(_profs, _offs, now)" in _g)
check("a régi „Bróker {broker}” kulcs nincs már használatban", '"gui.hdr.clock"' not in _g)
check("a többi bróker ideje a motorja állapotképéből",
      '_kepek = {_p.id: (_es.read(_p) or {})' in _g
      and '_k.get("server_offset_sec")' in _g)

# ── 5b: „Bróker" oszlop ────────────────────────────────────────────────
from dashboard.broker_header import broker_tags, show_broker_column   # noqa: E402
from dashboard import canvas_columns as CC, canvas_cells as CE, row_source as RS  # noqa: E402

at.tag, rob.tag = "Act", "Rob"
check("egy brókernél NINCS Bróker oszlop", not show_broker_column([at]))
check("kettőnél van", show_broker_column([at, rob]))
check("a címkék: az otthonié mindig, a másiké ahol a motorja futtatja",
      broker_tags([at, rob], "GOLD", {"roboforex": {"GOLD"}}) == "Act, Rob"
      and broker_tags([at, rob], "Ger40", {"roboforex": {"GOLD"}}) == "Act")
check("nem futó (nincs állapotkép) második bróker: csak az otthoni",
      broker_tags([at, rob], "GOLD", {}) == "Act")

k1 = CC.column_keys(["wpr_sma"], {"gate_columns": []})
k2 = CC.column_keys(["wpr_sma"], {"gate_columns": [], "show_broker": True})
check("egy brókernél az oszlop-lista VÁLTOZATLAN", "broker" not in k1)
check("több brókernél a „broker” a Symbol UTÁN áll",
      k2[:3] == ["symbol", "broker", "bid"], str(k2[:4]))
check("a Bróker oszlop a rögzített BAL sávban (a Symbollal együtt görög)",
      CE.PANE_OF("broker") == "left")
_d = {"symbol": "GOLD", "broker": "Act, Rob", "digits": 2}
check("a cella a címkéket mutatja", CE.cells_for(_d, {"show_broker": True})["broker"].text == "Act, Rob")
check("...egy brókernél nincs ilyen cella", "broker" not in CE.cells_for(_d, {}))
check("rendezhető", RS.sort_value({"broker": "Act, Rob"}, "broker") == (0, "Act, Rob"))
from dashboard import live_row as LR                                    # noqa: E402
check("van szélesség-mintája (különben a layout elszáll)", "broker" in LR._SAMPLE)
check("a felület átadja az oszlop kapcsolóját és a címkéket",
      '"show_broker": self._show_broker_column()' in _g
      and "broker_tags=_btags(_profs, sym, _mas)" in _g)

# ── 5c: a többi bróker pozíciói és lezártjai ──────────────────────────
from dashboard.broker_header import other_positions, merge_closed      # noqa: E402

_snaps = {"roboforex": {"positions_detail": [{"ticket": 7, "symbol": "GOLD", "profit": 1.5}],
                        "closed_today": [{"position": 7, "symbol": "GOLD", "pnl": 2.0}]}}
op = other_positions([at, rob], _snaps)
check("a többi bróker pozíciója a címkéjével jön", len(op) == 1 and op[0]["broker"] == "Rob", str(op))
check("egy brókernél nincs „más” pozíció", other_positions([at], _snaps) == [])
check("nem futó motor (nincs kép): üres, nem hiba", other_positions([at, rob], {}) == [])
_home = [{"position": 7, "symbol": "EURUSD", "pnl": -1.0}]
mc = merge_closed([at, rob], _home, _snaps)
check("a lezártak minden brókertől, soronként címkével",
      [(c["broker"], c["symbol"]) for c in mc] == [("Act", "EURUSD"), ("Rob", "GOLD")], str(mc))
check("⚠ egy brókernél a lista VÁLTOZATLAN (nincs címke → nincs oszlop)",
      merge_closed([at], _home, _snaps) == _home and "broker" not in merge_closed([at], _home, {})[0])
check("⚠ ugyanaz a pozíció-azonosító két brókernél KÉT sor (a kulcs a címkét is tartalmazza)",
      'pid = (c.get("broker"), c["position"]) if "broker" in c else c["position"]' in _g)
_m = (ROOT / "main.py").read_text(encoding="utf-8")
check("a motor a részletes pozíciólistát is közzéteszi",
      '"positions_detail": mt5_connector.open_positions_detailed()' in _m)
check("a többi bróker pozícióin NINCS művelet (külön, csak-megtekintés blokk)",
      "others_provider=self._other_broker_positions" in _g
      and "def _refresh_others(self):" in _g)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

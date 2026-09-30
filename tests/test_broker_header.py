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

# ── 5d: számlák + pénznemenkénti összesítő; Telegram-előtag ─────────────
from dashboard.broker_header import accounts_text                     # noqa: E402
lim = {"activtrades": 90.0, "roboforex": 90.0}
check("egy brókernél nincs számla-sor (a fejléc változatlan)",
      accounts_text([at], {"activtrades": {"balance": 946.64, "currency": "EUR"}}, lim) == "")
x = accounts_text([at, rob], {
    "activtrades": {"balance": 946.64, "currency": "EUR", "daily_pnl": 0, "health": "fut"},
    "roboforex": {"balance": 1000.0, "currency": "USD", "daily_pnl": 3.2, "health": "fut"}}, lim)
check("soronként egy számla, címkével", x.split(chr(10))[0].startswith("Act: 946.64 EUR")
      and x.split(chr(10))[1].startswith("Rob: 1,000.00 USD"), x)
check("⚠ eltérő pénznem: KÜLÖN összesítő (nincs átváltás, nincs keverés)",
      "Σ EUR: 946.64" in x and "Σ USD: 1,000.00" in x, x)
y = accounts_text([at, rob], {
    "activtrades": {"balance": 500.0, "currency": "EUR", "daily_pnl": -10, "health": "fut"},
    "roboforex": {"balance": 300.0, "currency": "EUR", "daily_pnl": 4, "health": "fut"}}, lim)
check("azonos pénznem: összeadva", "Σ EUR: 800.00 · napi -6.00" in y or "Σ EUR: 800.00 · daily -6.00" in y, y)
z = accounts_text([at, rob], {
    "activtrades": {"balance": 500.0, "currency": "EUR", "daily_pnl": -95, "health": "fut"}}, lim)
check("a limit elérése a SOR-ban látszik", "LIMIT" in z.split(chr(10))[0], z)
check("nem futó / adat nélküli motor: állapot, nem hamis szám",
      z.split(chr(10))[1].startswith("Rob: —"), z)
check("egyetlen ismert számlánál nincs összesítő (nincs mit összeadni)", "Σ" not in z, z)
w = accounts_text([at, rob], {
    "activtrades": {"balance": 1.0, "currency": "EUR", "daily_pnl": 0, "health": "fut"},
    "roboforex": {"balance": 1.0, "currency": "EUR", "daily_pnl": 0, "health": "hibas"}}, lim)
check("a hibás motor állapota a sorában", w.split(chr(10))[1].endswith(("hibás", "faulty")), w)

from core import telegram as TG                                        # noqa: E402
_regi = TG._ELOTAG
try:
    TG.set_tag(None)
    check("egy brókernél a Telegram-szöveg VÁLTOZATLAN", TG._elo("Jelzés") == "Jelzés")
    TG.set_tag("Rob")
    check("több brókernél a címke az elején", TG._elo("Jelzés") == "[Rob] Jelzés")
    check("⚠ nem duplázódik (a hosszú képaláírás kétszer megy át)",
          TG._elo(TG._elo("Jelzés")) == "[Rob] Jelzés")
finally:
    TG._ELOTAG = _regi
_tg = (ROOT / "core" / "telegram.py").read_text(encoding="utf-8")
check("mind a négy küldő út előtagol (send, kép, gombos, átírás)",
      _tg.count("_elo(") >= 4 + 1, str(_tg.count("_elo(")))
_mc = (ROOT / "core" / "mt5_connector.py").read_text(encoding="utf-8")
check("a kapcsolódás állítja be (egy brókernél None)",
      "_tg.set_tag(profil.tag if len(broker_profile.profiles(cfg)) > 1 else None)" in _mc)

# ── Brókerek fül: nem villog (Tibi, 2026-09-30) ───────────────────────
from dashboard.brokers_tab import structure_signature                  # noqa: E402
_r = lambda clock, age, pnl, sl=0: [{"tag": "At", "name": "A", "account": "1", "health": "fut",
     "balance": "1", "daily": "0", "n_pos": 1, "clock": clock, "age": age,
     "pairs": [{"symbol": "GOLD", "state": "LIVE", "strategies": [["wpr_sma", True]]}],
     "positions": [{"ticket": 7, "symbol": "GOLD", "sl": sl, "profit": pnl}]}]
check("az óra, a kor és a P&L változása NEM szerkezeti (helyben frissül)",
      structure_signature(_r("11:00:01", "1 mp", 1.0)) == structure_signature(_r("11:00:03", "3 mp", 9.0)))
check("egy SL-mozgás igen (újraépít)",
      structure_signature(_r("x", "1", 1.0)) != structure_signature(_r("x", "1", 1.0, sl=5)))
_bt = (ROOT / "dashboard" / "brokers_tab.py").read_text(encoding="utf-8")
check("a fül csak szerkezeti változásnál rombol",
      "if alairas == getattr(self, \"_alairas\", None):" in _bt and "self._helyben(adat)" in _bt)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

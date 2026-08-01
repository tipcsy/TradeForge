"""A 2.0 sor adata az elo allapotbol — dashboard/row_source.py.

Tiszta lekepezes: minden kulso forras beadhato, tehat MT5 es tkinter nelkul
merheto, hogy a felulet PONTOSAN mit fog mutatni.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard import row_source as rs

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


class DS:
    """Kitalalt PairDashboardState (duck-typed, mint az eles)."""
    bid = 25443.91
    ask = 25446.00
    change_pct = 0.03
    digits = 2
    spread_pts = 250
    atr_price = 5.0
    tf_align_signs = [1, -1, -1]
    tf_align_labels = ["M1", "M5", "M15"]
    tf_align_dir = None                 # nincs egyuttallas -> a tf_align blokkolna
    market_strategy = "regime"
    market_state_label = "Sz.Bika"
    strategy_cells = {
        "wpr_sma": {"sma": ("●", "green"), "m15": ("●", "green"), "m1": ("●", "muted")},
        "ml_ai":   {"model": ("●", "red"), "sig": ("●", "muted")},
    }
    daily_by_strategy = {
        "wpr_sma": {"pnl": 12.0, "count": 2, "wins": 1, "losses": 1,
                    "r": 0.8, "r_count": 2},
        "ml_ai":   {"pnl": -4.0, "count": 1, "wins": 0, "losses": 1,
                    "r": 0.0, "r_count": 0},        # nincs ismert kockazat
    }


PAIR = {"point_size": 0.01, "backtest_spread_points": 230.0}
PARAMS = {"max_spread_atr_ratio": 0.6}      # ATR 5.0/0.01 x 0.6 = 300 -> atenged
NAMES = ["wpr_sma", "ml_ai"]

POSITIONS = [
    {"ticket": 1, "symbol": "Ger40", "profit": 10.0, "magic": 100},
    {"ticket": 2, "symbol": "Ger40", "profit": -2.0, "magic": 100},
    {"ticket": 3, "symbol": "Ger40", "profit": 5.0, "magic": 101},
    {"ticket": 9, "symbol": "GOLD", "profit": 99.0, "magic": 100},   # mas par
]
OWNER = {1: "wpr_sma", 2: "wpr_sma", 3: "ml_ai", 9: "wpr_sma"}
RISKS = {1: 20.0, 2: 20.0}                  # a 3-ashoz NINCS rogzitett kockazat


def build(cfg=None, **kw):
    kw.setdefault("positions", POSITIONS)
    kw.setdefault("owner_of", lambda t, m: OWNER.get(t))
    kw.setdefault("risk_of", RISKS.get)
    return rs.row_data("Ger40", DS(), NAMES, cfg or {}, PARAMS, PAIR, **kw)


# ══ 1. Instrumentum-adat ═══════════════════════════════════════════════════
r = build()
check("a szimbolum atkerul", r["symbol"] == "Ger40")
check("BID/ASK atkerul", (r["bid"], r["ask"]) == (25443.91, 25446.00))
check("a tizedesjegyek atkerulnek", r["digits"] == 2)

# ══ 2. Kapu-cellak ═════════════════════════════════════════════════════════
# A hatar NEM csak az ATR-bol jon: a spread-kapunak PADLOJA van, az instrumentum
# normal spreadjenek min_spread_mult-szorosa (230 x 1.5 = 345). Itt ez nagyobb az
# ATR-tagnal (500 x 0.6 = 300), tehat a PADLO dont. Ez a spread_gate szandekolt
# mukodese — a teszt ezt is rogziti, mert konnyu elfelejteni.
check("a spread KONKRET szamparral jelenik meg (nem betukod)",
      r["gates"]["spread"]["text"] == "250/345", r["gates"]["spread"]["text"])
check("...es nem blokkol (250 <= 345)", r["gates"]["spread"]["blocking"] is False)
check("a PADLO felulirja a szukebb ATR-tagot (230 x 1.5 = 345 > 500 x 0.2)",
      rs.row_data("Ger40", DS(), NAMES, {}, {"max_spread_atr_ratio": 0.2},
                  PAIR)["gates"]["spread"]["text"] == "250/345")
check("az idosik-elojelek atkerulnek", r["gates"]["align"]["signs"] == [1, -1, -1])
check("a piac-cimke atkerul", r["gates"]["market"]["text"] == "Sz.Bika")

# A K.Ossz. a MEREST szamolja: hany kapu all blokkolo allapotban, strategiatol
# fuggetlenul. Itt a tf_align (nincs egyuttallas) -> 1.
check("K.Ossz. = hany kapu all blokkolo allapotban", r["gates"]["badge"] == "⛔1",
      r["gates"]["badge"])

_r_ok = rs.row_data("Ger40", type("D", (DS,), {"tf_align_dir": "BUY"})(), NAMES,
                    {}, PARAMS, PAIR)
check("ha semmi nem blokkol -> pipa", _r_ok["gates"]["badge"] == "✓")

# Tag spread (a padlo folott) -> a spread is blokkol, tehat KET kapu
class _DSWide(DS):
    spread_pts = 400            # 400 > 345 (padlo)


_r_wide = rs.row_data("Ger40", _DSWide(), NAMES, {}, PARAMS, PAIR)
check("tag spreadnel a spread is blokkol -> 2",
      _r_wide["gates"]["badge"] == "⛔2", _r_wide["gates"]["badge"])
check("...es a spread-cella blokkolonak jeloli",
      _r_wide["gates"]["spread"]["blocking"] is True)

# ══ 3. A KERET per strategia — ez a lenyeg ════════════════════════════════
# A tf_align kapu csak a wpr_sma-t kapuzza (config), tehat az ml_ai szabadon fut.
CFG = {"gates": {"tf_align": {"wpr_sma": "block"}, "spread": {"default": "none"}}}
r2 = build(CFG)
by = {s["name"]: s for s in r2["strategies"]}
check("a kapuzott strategia kerete 'blocked'", by["wpr_sma"]["frame"] == "blocked")
check("a NEM kapuzotte URES (nema)", by["ml_ai"]["frame"] == "")

CFG_RED = {"gates": {"tf_align": {"wpr_sma": "reduce"}, "spread": {"default": "none"}}}
check("'reduce' hatasnal a keret 'reduced'",
      {s["name"]: s for s in build(CFG_RED)["strategies"]}["wpr_sma"]["frame"]
      == "reduced")

# ══ 4. Stadium-pottyok ════════════════════════════════════════════════════
check("a stadium-szinek a motor strategy_cells-ebol jonnek",
      by["wpr_sma"]["stages"] == ["green", "green", "muted"],
      str(by["wpr_sma"]["stages"]))
check("a stadiumok szama strategiankent kulonbozhet",
      len(by["ml_ai"]["stages"]) == 2)
check("megadott sorrend eseten AZ dont",
      rs._stages(DS(), "wpr_sma", ("m1", "sma")) == ["muted", "green"])
check("ismeretlen strategia -> ures", rs._stages(DS(), "nincs") == [])

# ══ 5. Nyitott pozicio per strategia ══════════════════════════════════════
check("a wpr_sma ket poziciojanak osszege", by["wpr_sma"]["position"]["money"] == 8.0)
check("...ket darab", by["wpr_sma"]["position"]["count"] == 2)
check("...R = 8 / (20+20) = 0.2",
      abs(by["wpr_sma"]["position"]["r"] - 0.2) < 1e-9)
check("az ml_ai kulon szamol", by["ml_ai"]["position"]["money"] == 5.0)
check("...rogzitett kockazat nelkul NINCS R (nem 0)",
      by["ml_ai"]["position"]["r"] is None)
check("MAS par pozicioja NEM szamit bele",
      by["wpr_sma"]["position"]["money"] != 107.0)

_empty = rs.row_data("NINCS", DS(), NAMES, {}, PARAMS, PAIR, positions=POSITIONS,
                     owner_of=lambda t, m: OWNER.get(t))
check("pozicio nelkul a cella ures (None, nem 0)",
      _empty["strategies"][0]["position"]["money"] is None)

# ══ 6. Napi P&L per strategia ═════════════════════════════════════════════
check("a napi P&L a pnl_split bontasabol jon", by["wpr_sma"]["daily"]["money"] == 12.0)
check("...R-rel egyutt", abs(by["wpr_sma"]["daily"]["r"] - 0.8) < 1e-9)
check("r_count=0 eseten NINCS R (nem 0 R)", by["ml_ai"]["daily"]["r"] is None)
check("...de a penz attol meg latszik", by["ml_ai"]["daily"]["money"] == -4.0)

# ══ 7. Osszesito = a blokkok osszege ══════════════════════════════════════
check("az osszesito pozicio a blokkok osszege",
      r2["total"]["position"]["money"] == 13.0)
check("az osszesito napi P&L a blokkok osszege",
      r2["total"]["daily"]["money"] == 8.0)
check("az R-ek kozul csak a LETEZOK adodnak ossze",
      abs(r2["total"]["daily"]["r"] - 0.8) < 1e-9)
check("ha egyik blokkban sincs R, az osszesitoben sincs",
      rs._sum_money_r([{"money": 1.0, "r": None}])["r"] is None)

# ══ 8. Beadhato forrasok ══════════════════════════════════════════════════
r3 = build(CFG,
           quality_of=lambda s, n: ("Jó", "green") if n == "wpr_sma" else ("Gyenge", "red"),
           opt_of=lambda s, n: "06/29" if n == "wpr_sma" else "85%",
           live_of=lambda s, n: n == "wpr_sma")
b3 = {s["name"]: s for s in r3["strategies"]}
check("a minoseg per STRATEGIA jon (nem szimbolum-szinten)",
      (b3["wpr_sma"]["quality"], b3["ml_ai"]["quality"]) == ("Jó", "Gyenge"))
check("az opt-statusz per strategia", b3["ml_ai"]["opt"] == "85%")
check("a fut-e jelzo per strategia",
      (b3["wpr_sma"]["live"], b3["ml_ai"]["live"]) == (True, False))
check("forrasok nelkul sem szall el", build()["strategies"][0]["quality"] is None)

# ══ 9. build_rows ═════════════════════════════════════════════════════════
rows = rs.build_rows(["Ger40", "GOLD", "NINCS_ILYEN"],
                     {"Ger40": DS(), "GOLD": DS()},
                     lambda s: NAMES, cfg={}, params=PARAMS, pair_cfg=PAIR)
check("build_rows a letezo szimbolumokra ad sort", [x["symbol"] for x in rows]
      == ["Ger40", "GOLD"])
check("minden sorban AZONOS a strategia-lista (kulonben elcsusznanak az oszlopok)",
      all([s["name"] for s in x["strategies"]] == NAMES for x in rows))

# ══ 10. Szures ════════════════════════════════════════════════════════════
def mkrow(sym, **kw):
    r = {"symbol": sym, "bid": kw.get("bid"), "ask": kw.get("ask"),
         "change_pct": kw.get("change"),
         "gates": {"spread": {"value": kw.get("spread")},
                   "market": {"text": kw.get("market", "")},
                   "blocking_count": kw.get("blocking", 0)},
         "strategies": [{"name": "wpr_sma", "live": kw.get("live", False),
                         "frame": kw.get("frame", ""),
                         "position": {"money": kw.get("pos")},
                         "daily": {"money": kw.get("daily")},
                         "quality": kw.get("q"), "opt": kw.get("opt", "")}],
         "total": {"position": {"money": kw.get("tpos")},
                   "daily": {"money": kw.get("tdaily")}}}
    return r


ROWS = [mkrow("GOLD", bid=4000, change=1.5, spread=300, blocking=2, live=True,
              pos=10.0, daily=-5.0, q="Gyenge", tdaily=-5.0, frame="blocked"),
        mkrow("EURUSD", bid=1.1, change=-0.5, spread=100, blocking=0, live=False,
              pos=None, daily=12.0, q="Jó", tdaily=12.0, frame=""),
        mkrow("Ger40", bid=25000, change=0.2, spread=200, blocking=1, live=True,
              pos=3.0, daily=0.0, q="Közepes", tdaily=0.0, frame="reduced")]

check("kereses szurkit", [r["symbol"] for r in rs.filter_rows(ROWS, "EUR")] == ["EURUSD"])
check("a kereses kis/nagybetu-fuggetlen",
      len(rs.filter_rows(ROWS, "gold")) == 1)
check("ures kereses -> minden sor", len(rs.filter_rows(ROWS, "")) == 3)
check("nincs talalat -> ures", rs.filter_rows(ROWS, "NINCSILYEN") == [])
check("STOPPED elrejtese: csak ahol FUT valamelyik strategia",
      [r["symbol"] for r in rs.filter_rows(ROWS, hide_stopped=True)]
      == ["GOLD", "Ger40"])
check("a ketto EGYUTT is mukodik",
      [r["symbol"] for r in rs.filter_rows(ROWS, "GER", True)] == ["Ger40"])

# ══ 11. Rendezes ══════════════════════════════════════════════════════════
def order(key, rev=False):
    return [r["symbol"] for r in rs.sort_rows(ROWS, key, rev)]


check("kulcs nelkul az EREDETI sorrend", order(None) == ["GOLD", "EURUSD", "Ger40"])
check("symbol szerint", order("symbol") == ["EURUSD", "GOLD", "Ger40"])
check("...forditva", order("symbol", True) == ["Ger40", "GOLD", "EURUSD"])
check("bid szerint (szam, nem szoveg)", order("bid") == ["EURUSD", "GOLD", "Ger40"])
check("valtozas% szerint", order("change") == ["EURUSD", "Ger40", "GOLD"])
check("spread szerint", order("spread") == ["EURUSD", "Ger40", "GOLD"])
check("K.Ossz. (hany kapu blokkol) szerint",
      order("badge") == ["EURUSD", "Ger40", "GOLD"])
check("strategia-pozicio szerint", order("wpr_sma|position") == ["Ger40", "GOLD", "EURUSD"])
check("strategia napi P&L szerint", order("wpr_sma|daily") == ["GOLD", "Ger40", "EURUSD"])
check("osszesito napi P&L szerint", order("total_daily") == ["GOLD", "Ger40", "EURUSD"])

# A minoseg SZOVEGKENT rendezve "Gyenge" < "Jo" lenne — ami hazugsag.
check("minoseg RANGSOR szerint (Jo elol), nem abecerendben",
      order("wpr_sma|quality") == ["EURUSD", "Ger40", "GOLD"])

# A jelzes-oszlop: ahol TEENDO van (blokkolt), az elore
check("jelzes szerint a blokkoltak elol",
      order("wpr_sma|stages") == ["GOLD", "Ger40", "EURUSD"])

# A hianyzo adat MINDIG hatul — novekvo es csokkeno sorrendben is. Kulonben a
# "nincs adat" sorok a lista elejere ugrananak, mintha ok lennenek a legjobbak.
check("hianyzo ertek novekvoben is hatul", order("wpr_sma|position")[-1] == "EURUSD")
check("...es csokkenoben is hatul",
      rs.sort_rows(ROWS, "wpr_sma|position", True)[-1]["symbol"] == "EURUSD")

check("ismeretlen kulcs nem szall el", len(rs.sort_rows(ROWS, "nincs_ilyen")) == 3)
check("ismeretlen strategia nem szall el", len(rs.sort_rows(ROWS, "x|position")) == 3)
check("ures listan sem", rs.sort_rows([], "symbol") == [])

# STABIL: azonos ertekeknel a szimbolum dont, tehat a sorok nem cserelgetik
# egymast frissitesenkent (az ugralo tabla olvashatatlan).
same = [mkrow("BBB", daily=1.0), mkrow("AAA", daily=1.0), mkrow("CCC", daily=1.0)]
check("azonos ertekeknel STABIL (szimbolum szerint)",
      [r["symbol"] for r in rs.sort_rows(same, "wpr_sma|daily")]
      == ["AAA", "BBB", "CCC"])

# ══ 12. Vegtelen spread-hatar (nincs meg ATR) ═════════════════════════════
# A spread_gate fail-open: ervenyes ATR nelkul VEGTELEN a hatar. Ez indulaskor,
# a bemelegites elott normalis — de "inf"-et kiirni a cellaba ertelmetlen.
# (A valodi indulasnal "8/inf" jelent meg; a demo-inditas mutatta meg.)
class _DSNoATR(DS):
    atr_price = None


_r_noatr = rs.row_data("Ger40", _DSNoATR(), NAMES, {}, PARAMS, PAIR)
check("nincs ATR -> a hatar '—', nem 'inf'",
      _r_noatr["gates"]["spread"]["text"] == "250/—",
      _r_noatr["gates"]["spread"]["text"])
check("...es ilyenkor NEM blokkol (fail-open)",
      _r_noatr["gates"]["spread"]["blocking"] is False)
check("...de a spread erteke megmarad rendezeshez",
      _r_noatr["gates"]["spread"]["value"] == 250)
# A K.Ossz.-hoz a tf_align-t is rendbe kell tenni, kulonben AZ blokkol (nincs
# egyuttallas) — a spread hatasat kulon kell szigetelni.
class _DSNoATROk(_DSNoATR):
    tf_align_dir = "BUY"


check("nincs ATR -> a spread NEM szamit blokkolonak (fail-open)",
      rs.row_data("Ger40", _DSNoATROk(), NAMES, {}, PARAMS,
                  PAIR)["gates"]["badge"] == "✓")

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

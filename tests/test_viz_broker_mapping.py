"""TradeForgeViz a nem-kanonikus brókeren (RoboForex, 2026-10-13).

Tibi: „ha ráhúzom a TradeForgeViz-et a RoboForexes chartra, nem látható semmi."
Az indikátor a chart SAJÁT szimbólumát olvassa (`TFV_<_Symbol>.csv`), a Python
viszont kanonikus névvel írt (`TFV_Ger40.csv` — a RoboForexen `.DE40Cash`), és a
kanonikus (berlini) órával — a RoboForex szervere NY+7 (nyáron +1 óra).

⚠ MT5 és valódi Common-mappa nélkül: ideiglenes mappába ír.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                         # noqa: E402
applog.harden_console()

from core import broker_adapter as A, broker_profile as B       # noqa: E402
from core import broker_time as T, mt5_visual as V, mt_charts as MC  # noqa: E402
from strategy.visual import Rect, BarState, Alert               # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


ROB = {"id": "roboforex", "tag": "Rob", "name": "RoboForex", "server": "R", "login": 1,
       "server_zone": "America/New_York+7", "symbols": {"Ger40": ".DE40Cash", "GOLD": "XAUUSD"}}
AT = {"id": "activtrades", "tag": "At", "name": "ActivTrades", "server": "A", "login": 2}
_eredeti = A.current()
try:
    # ── RoboForex ─────────────────────────────────────────────────────────
    A.configure(B.profiles({"brokers": [dict(ROB, main=True)]})[0])
    check("a fájlnév a BRÓKER szimbóluma", V.chart_symbol("Ger40") == ".DE40Cash"
          and V.chart_symbol("GOLD") == "XAUUSD" and V.chart_symbol("EURUSD") == "EURUSD")
    check("az életjel visszafordul kanonikusra", V.canonical_symbol(".DE40Cash") == "Ger40")
    t = 1792000000
    sz = A.current().server_zone
    o = V.to_chart_time([Rect(name="x", t1=t, p1=1.0, t2=t + 60, p2=2.0, color="red"),
                         BarState(t=t), Alert(aid="a", text="b")])
    check("az objektum-idő a szerver órájára vált",
          o[0].t1 == T.canonical_to_server_epoch(t, sz) and o[0].t1 != t, o[0])
    check("...minden időmező (t1, t2, a sáv t-je)",
          o[0].t2 - o[0].t1 == 60 and o[1].t == o[0].t1)
    check("...az idő nélküli sor érintetlen", o[2] == Alert(aid="a", text="b"))

    _d = Path(tempfile.mkdtemp())
    _orig_dir = V.files_dir
    V.files_dir = lambda: _d
    try:
        p = V.write_lines("Ger40", ["RECT;x"])
        check("a fájl a chart nevén: TFV_.DE40Cash.csv", p.name == "TFV_.DE40Cash.csv", p)
        p = V.clear("GOLD")
        check("a törlés is: TFV_XAUUSD.csv", p.name == "TFV_XAUUSD.csv", p)
        (_d / "TFV_ALIVE_.DE40Cash_1.txt").write_text(
            "ALIVE;.DE40Cash;1;;2026.10.13 11:43:19;1", encoding="utf-8")
        _orig_cd = MC.common_dir
        MC.common_dir = lambda: _d
        try:
            check("a nyitott chart a KANONIKUS névvel jelenik meg (Ger40)",
                  MC.is_open("Ger40"), MC.open_symbols())
        finally:
            MC.common_dir = _orig_cd
    finally:
        V.files_dir = _orig_dir

    # ── a név-buborék (Tibi: „Ger40 --> .DE40Cash --> Teljes név: DAX") ──
    from dashboard import row_source as RS, canvas_cells as CC
    _nt = RS.name_tip("Ger40", {"description": "DAX Cash Index"})
    check("buborék: kanonikus → bróker név + teljes név",
          _nt.startswith("Ger40 → .DE40Cash") and "DAX Cash Index" in _nt, _nt)
    check("azonos névnél nincs nyíl", RS.name_tip("EURUSD", {}) == "EURUSD")
    _c = CC.cells_for({"symbol": "Ger40", "digits": 1, "name_tip": _nt,
                       "session": {"state": "open", "tip": "nyitva"}}, {})["symbol"]
    check("a cella buboréka: név + piac-állapot", _c.tip == _nt + chr(10) + "nyitva", _c.tip)

    # ── ActivTrades (kanonikus): semmi nem változik ─────────────────────
    A.configure(B.profiles({"brokers": [dict(AT, main=True)]})[0])
    check("kanonikus brókeren a név változatlan", V.chart_symbol("Ger40") == "Ger40")
    r = Rect(name="x", t1=t, p1=1.0, t2=t + 60, p2=2.0, color="red")
    check("...és az idő is", V.to_chart_time([r])[0] is r)
    A.configure(None)
    check("profil nélkül (eszközök) változatlan", V.chart_symbol("Ger40") == "Ger40"
          and V.to_chart_time([r])[0] is r)
finally:
    A.configure(_eredeti)

src = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
check("az élő viz-út a chart-órára vált", "mt5_visual.to_chart_time(pair_visual_objects(" in src)

print(f"\n{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

"""A Dashboard 2.0 bekotese a VALODI DashboardWindow-ba — MT5 nelkul.

Az 1. kor tanulsaga: a sor-widget onmagaban rendereltetheto, DE a bekotes csak
akkor bizonyitott, ha a VALODI ablak is felepul vele. Ezert itt a tenyleges
DashboardWindow-t epitjuk fel (a frissito ciklus es az MT5-poller kiloveasevel),
kitalalt motor-allapottal.

A `classic` marad az alapertelmezes: az 1. korben HAROM elrendezes bukott meg,
tehat a 2.0 addig valaszthato marad, amig nem bizonyitott.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


try:
    import tkinter as tk
    _p = tk.Tk(); _p.destroy()
    TK_OK = True
except Exception as e:
    TK_OK = False
    print(f"KIHAGYVA: nincs hasznalhato tkinter ({type(e).__name__}: {e})")

if TK_OK:
    import dashboard.gui as G
    from dashboard import theme as _t
    from trading.live_trader import PairDashboardState

    CFG = {
        "strategy": {"name": "wpr_sma"},
        "available_strategies": ["wpr_sma", "ml_ai"],
        "dashboard": {"price_refresh_sec": 3, "live_refresh_sec": 7,
                      "all_refresh_sec": 30, "countdown_timeframes": [15, 1]},
        "trading": {"account_risk_pct": 0.01, "max_open_slots": 4,
                    "daily_loss_limit_pct": 0.015},
        "gates": {"tf_align": {"wpr_sma": "block"}},
        "pairs": {
            "Ger40": {"enabled": True, "point_size": 0.01, "pv1_point": 0.01,
                      "min_lot": 0.1, "lot_step": 0.1,
                      "backtest_spread_points": 230.0,
                      "strategies": ["wpr_sma", "ml_ai"]},
            "GOLD": {"enabled": True, "point_size": 0.01, "pv1_point": 0.88,
                     "min_lot": 0.01, "lot_step": 0.01,
                     "backtest_spread_points": 48.0,
                     "strategies": ["wpr_sma", "ml_ai"]},
        },
    }

    def make_ds(sym):
        d = PairDashboardState(symbol=sym, trained=True, enabled=True)
        d.bid, d.ask, d.digits, d.change_pct = 25443.91, 25446.0, 2, 0.03
        d.spread_pts, d.atr_price = 250, 5.0
        d.tf_align_signs = [1, -1, -1]
        d.tf_align_labels = ["M1", "M5", "M15"]
        d.tf_align_dir = None                    # nincs egyuttallas -> blokkol
        d.market_strategy, d.market_state_label = "regime", "Sz.Bika"
        d.strategy_cells = {
            "wpr_sma": {"sma": ("●", "green"), "m15": ("●", "green"),
                        "m1": ("●", "muted")},
            "ml_ai": {"model": ("●", "red"), "sig": ("●", "muted")}}
        d.daily_by_strategy = {
            "wpr_sma": {"pnl": 12.0, "r": 0.8, "r_count": 2},
            "ml_ai": {"pnl": -4.0, "r": 0.0, "r_count": 0}}
        return d

    def build_window(layout):
        """A VALODI DashboardWindow — frissito ciklus es MT5-poller nelkul."""
        import copy
        cfg = copy.deepcopy(CFG)
        cfg["dashboard"]["layout"] = layout
        _t._FONTS.clear()            # a szingleton az elozo (eldobott) gyokerhez kotodott
        G.DashboardWindow._start_refresh_loops = lambda self: None
        G.DashboardWindow._start_bg_poller = lambda self: None
        G.DashboardWindow._poll_mt5 = lambda self: None
        # Az optimalizalo process-poolt sem inditjuk: szkriptbol futtatva a
        # gyerek-processzek ujra importalnak (multiprocessing figyelmeztetes), es
        # a teszthez semmi kozuk.
        G.DashboardWindow._ensure_pool = lambda self: None
        ds = {s: make_ds(s) for s in cfg["pairs"]}
        w = G.DashboardWindow(cfg, ds, {s: "STOPPED" for s in ds}, {},
                              on_play_pair=None, on_stop_pair=None)
        w.root.withdraw()
        w.root.update_idletasks()
        return w

    # ══ 1. A 2.0 elrendezes felepul ═══════════════════════════════════════
    w2 = None
    try:
        w2 = build_window("live2")
        check("a layout felismerve", w2._layout_mode() == "live2")
        check("felepult a 2.0 tabla", getattr(w2, "_live2", None) is not None)
        check("annyi sor, ahany par", len(w2._live2._row_widgets) == len(CFG["pairs"]))
        # A classic sorok URESEN maradnak -> a classic frissito-ag magatol kimarad
        check("a classic sorok uresek (nincs ketto tabla)", len(w2.rows) == 0)

        rows = w2._live2_rows()
        check("a sor-adat eloallt", len(rows) == 2)
        by = {r["symbol"]: r for r in rows}
        check("a K.Ossz. a merest mutatja (nincs egyuttallas -> blokkol)",
              by["Ger40"]["gates"]["badge"].startswith("⛔"),
              by["Ger40"]["gates"]["badge"])
        st = {s["name"]: s for s in by["Ger40"]["strategies"]}
        check("a kapuzott strategia kerete 'blocked'",
              st["wpr_sma"]["frame"] == "blocked")
        check("a nem kapuzotte URES", st["ml_ai"]["frame"] == "")
        check("a napi P&L a pnl_split bontasabol jon",
              st["wpr_sma"]["daily"]["money"] == 12.0)
        check("MINDEN sorban azonos a strategia-lista (oszlop-igazitas)",
              all([s["name"] for s in r["strategies"]]
                  == [s["name"] for s in rows[0]["strategies"]] for r in rows))

        # A frissites HELYBEN megy (nem epul ujra): ugyanazok a widgetek.
        ids_before = [id(x) for x in w2._live2._row_widgets]
        w2._live2.refresh(w2._live2_rows())
        check("a frissites HELYBEN tortenik (nincs ujraepites)",
              [id(x) for x in w2._live2._row_widgets] == ids_before)
    finally:
        if w2 is not None:
            w2.root.destroy()

    # ══ 2. A classic VALTOZATLAN ══════════════════════════════════════════
    wc = None
    try:
        wc = build_window("classic")
        check("classic: nincs 2.0 tabla", getattr(wc, "_live2", None) is None)
        check("classic: vannak PairRow-sorok", len(wc.rows) == len(CFG["pairs"]))
        check("classic az ALAPERTELMEZES",
              G.DashboardWindow._layout_mode(
                  type("C", (), {"cfg": {"dashboard": {}}})()) == "classic")
    finally:
        if wc is not None:
            wc.root.destroy()

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

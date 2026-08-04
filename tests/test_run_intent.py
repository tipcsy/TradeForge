"""A kereskedes-SZANDEK per (par x strategia) — a 2.0 Play/Stop gombja.

BEJELENTES: „Ha a wpr_sma-nal megnyomjuk a Play gombot, akkor csak a wpr_sma
strategia kereskedest nyissa meg (ekkor ne kapcsoljon be az ml_ai)."

KET hiba volt egyszerre, es CSAK EGYUTT javithatok:

  1. A 2.0 sor `on_toggle`-je eldobta a strategia nevet
     (`lambda s, n: self._handle_run(s)`) — a gomb a SZIMBOLUMOT kapcsolta.
  2. A `live_trader` futasideju ciklusa a `run_state`-et NEM olvasta: a LIVE ag
     minden ENGEDELYEZETT strategiahoz letrehozta az allapotot. Igy a feluleten
     leallitott strategiat a KOVETKEZO KOR visszainditotta volna — a javitas
     ujrainditasig hatott volna csak, es ezt semmi nem jelezte volna.

A 2. pontot forras-szinten orizzuk (a `test_strategy_toggle.py` mintajara): a
ciklus egy hosszu, MT5-fuggo fuggveny, viszont a REGRESSZIO pont az, ha a
`run_state`-olvasas kikerul belole.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from core import run_state as rs

# ══ 1. A szandek-feloldas per strategia ═══════════════════════════════════
CFG = {"pairs": {"GOLD": {"enabled": True,
                          "run_state": {"wpr_sma": "live", "ml_ai": "stopped"}}}}
check("csak a 'live' szandeku strategia fut",
      rs.live_strategies(CFG, "GOLD", ["wpr_sma", "ml_ai"]) == ["wpr_sma"],
      str(rs.live_strategies(CFG, "GOLD", ["wpr_sma", "ml_ai"])))
# Az `enabled` a SZIMBOLUM szintje: van-e barmely elo strategia. Ezen dol el,
# hogy a motor egyaltalan hozzanyul-e a parhoz.
check("az `enabled` szinkronban marad (van elo strategia)",
      CFG["pairs"]["GOLD"]["enabled"] is True)
rs.set_state(CFG, "GOLD", "wpr_sma", rs.STOPPED)
check("az UTOLSO strategia leallitasa az `enabled`-et is leveszi",
      CFG["pairs"]["GOLD"]["enabled"] is False)
rs.set_state(CFG, "GOLD", "ml_ai", rs.LIVE)
check("...es egy strategia inditasa vissza is kapcsolja",
      CFG["pairs"]["GOLD"]["enabled"] is True)

# Legacy (meg nincs run_state map): a regi config valtozatlanul mukodik.
LEG = {"pairs": {"X": {"enabled": True}, "Y": {"enabled": False}}}
check("legacy: enabled=true -> minden megadott strategia fut",
      rs.live_strategies(LEG, "X", ["wpr_sma", "ml_ai"]) == ["wpr_sma", "ml_ai"])
check("legacy: enabled=false -> egyik sem",
      rs.live_strategies(LEG, "Y", ["wpr_sma", "ml_ai"]) == [])

# ══ 2. A MOTOR ciklusa tiszteletben tartja a szandekot ════════════════════
src = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
loop = src[src.index("while True:"):]
check("a ciklus UJRAOLVASSA a kereskedes-szandekot",
      "run_state.live_strategies(" in loop)
check("a LIVE ag KIHAGYJA a nem 'live' szandeku strategiat",
      "if st.name not in _active:" in loop)
check("a leallitott strategia allapota torlodik / kivezetesbe megy",
      "_n in _active" in loop and "disabled_closing" in loop)
# A KIKAPCSOLT (config) es a LEALLITOTT (Play/Stop) ket KULON ok — a naplobol
# derüljön ki, melyik tortent.
check("a naplo megkulonbozteti a ket okot",
      "KIKAPCSOLTAD" in loop and "LEÁLLÍTOTTAD" in loop)

# ══ 3. A GUI gombja — a VALODI ablakon ════════════════════════════════════
try:
    import tkinter as tk
    _p = tk.Tk(); _p.destroy()
    TK_OK = True
except Exception as e:
    TK_OK = False
    print(f"KIHAGYVA (3. blokk): nincs hasznalhato tkinter ({type(e).__name__}: {e})")

if TK_OK:
    import dashboard.gui as G
    from dashboard import theme as _t
    from trading.live_trader import PairDashboardState

    BASE = {
        "strategy": {"name": "wpr_sma"},
        "available_strategies": ["wpr_sma", "ml_ai"],
        "dashboard": {"layout": "live2", "price_refresh_sec": 3,
                      "live_refresh_sec": 7, "all_refresh_sec": 30,
                      "countdown_timeframes": [15, 1]},
        "trading": {"account_risk_pct": 0.01, "max_open_slots": 4,
                    "daily_loss_limit_pct": 0.015},
        "pairs": {
            "GOLD": {"enabled": True, "point_size": 0.01, "pv1_point": 0.88,
                     "min_lot": 0.01, "lot_step": 0.01,
                     "backtest_spread_points": 48.0,
                     "strategies": ["wpr_sma", "ml_ai"],
                     "run_state": {"wpr_sma": "live", "ml_ai": "live"}},
        },
    }

    def build(position_pnl=None):
        import copy
        cfg = copy.deepcopy(BASE)
        _t._FONTS.clear()
        G.DashboardWindow._start_refresh_loops = lambda self: None
        G.DashboardWindow._start_bg_poller = lambda self: None
        G.DashboardWindow._poll_mt5 = lambda self: None
        G.DashboardWindow._ensure_pool = lambda self: None
        # ⚠ A VALODI `_save_main_config` a repo config.json-jat irna felul.
        saves = []
        G.DashboardWindow._save_main_config = lambda self: saves.append(1)
        ds = PairDashboardState(symbol="GOLD", trained=True, enabled=True)
        ds.digits, ds.bid, ds.ask = 2, 2000.0, 2000.5
        ds.position_pnl = position_pnl
        w = G.DashboardWindow(cfg, {"GOLD": ds}, {"GOLD": "LIVE"}, {},
                              on_play_pair=None, on_stop_pair=None)
        w.root.withdraw()
        w.root.update_idletasks()
        return w, cfg, saves

    # ── 3a. Stop CSAK az egyik strategiara ────────────────────────────────
    w, cfg, saves = None, None, None
    try:
        w, cfg, saves = build()
        check("indulaskor mindketto fut",
              w._strategy_live("GOLD", "wpr_sma")
              and w._strategy_live("GOLD", "ml_ai"))

        w._handle_run_strategy("GOLD", "wpr_sma")
        check("a wpr_sma leallt", not w._strategy_live("GOLD", "wpr_sma"))
        check("...az ml_ai VALTOZATLANUL fut (ez volt a bejelentes)",
              w._strategy_live("GOLD", "ml_ai"))
        check("...a par a MOTOR szemeben is LIVE marad",
              w.instrument_state["GOLD"] == "LIVE")
        check("...es a szandek PERZISZTALT (restart-biztos)",
              cfg["pairs"]["GOLD"]["run_state"] == {"wpr_sma": "stopped",
                                                    "ml_ai": "live"},
              str(cfg["pairs"]["GOLD"].get("run_state")))
        check("...a mentes megtortent", saves and len(saves) >= 1)

        # Ujra Play -> csak ez indul
        w._handle_run_strategy("GOLD", "wpr_sma")
        check("ujra inditva csak a wpr_sma valtozik",
              cfg["pairs"]["GOLD"]["run_state"] == {"wpr_sma": "live",
                                                    "ml_ai": "live"},
              str(cfg["pairs"]["GOLD"].get("run_state")))
    finally:
        if w is not None:
            w.root.destroy()

    # ── 3b. Az UTOLSO strategia leallitasa a part is lezarja ──────────────
    w = None
    try:
        w, cfg, _ = build()                       # nincs nyitott pozicio
        w._handle_run_strategy("GOLD", "wpr_sma")
        w._handle_run_strategy("GOLD", "ml_ai")
        check("az utolso strategia leallitasa utan a par STOPPED",
              w.instrument_state["GOLD"] == "STOPPED",
              w.instrument_state["GOLD"])
    finally:
        if w is not None:
            w.root.destroy()

    w = None
    try:
        w, cfg, _ = build(position_pnl=12.5)      # NYITOTT pozicioval
        w._handle_run_strategy("GOLD", "wpr_sma")
        w._handle_run_strategy("GOLD", "ml_ai")
        check("nyitott pozicioval KIVEZETES lesz (a motor tovabb kezeli)",
              w.instrument_state["GOLD"] == "CLOSING",
              w.instrument_state["GOLD"])
    finally:
        if w is not None:
            w.root.destroy()

    # ── 3c. Az OPT allapota koveti a kereskedest ──────────────────────────
    w = None
    try:
        w, cfg, _ = build()
        st = {s["name"]: s for s in w._live2_rows()[0]["strategies"]}
        check("kereskedo strategianal az OPT INAKTIV",
              st["wpr_sma"]["opt_enabled"] is False)
        w._handle_run_strategy("GOLD", "wpr_sma")
        st = {s["name"]: s for s in w._live2_rows()[0]["strategies"]}
        check("...leallitas utan optimalizalhato",
              st["wpr_sma"]["opt_enabled"] is True)
        check("...a meg futo ml_ai viszont nem",
              st["ml_ai"]["opt_enabled"] is False)
        # KIVEZETES alatt egyik sem: ott minden strategia poziciot kezel.
        w.instrument_state["GOLD"] = "CLOSING"
        check("KIVEZETES alatt egyik strategia sem optimalizalhato",
              not w._live2_opt_enabled("GOLD", "wpr_sma"))
    finally:
        if w is not None:
            w.root.destroy()

    # ── 3d. A kattintasok BE VANNAK KOTVE ─────────────────────────────────
    w = None
    try:
        w, cfg, _ = build()
        row = w._live2_rows()[0]
        check("az instrumentum neve kattinthato", callable(row.get("on_symbol")))
        check("a Spread kattinthato", callable((row["gates"]).get("on_spread")))
        check("az Egyutt kattinthato",
              callable((row["gates"]["align"]).get("on_click")))
        check("a jelzes-cella kattinthato (strategiankent)",
              all(callable(s.get("on_stages")) for s in row["strategies"]))

        # A jelzes-kattintas a SAJAT strategiajanak ablakat nyitja
        opened = []
        w._show_strategy_params = lambda sym, name="": opened.append((sym, name))
        for s in w._live2_rows()[0]["strategies"]:
            s["on_stages"]()
        check("...es a SAJAT strategiajaval hivja meg",
              opened == [("GOLD", "wpr_sma"), ("GOLD", "ml_ai")], str(opened))

        # A Spread a KOZOS vegrehajtasi parametereket nyitja (barmely strategia
        # nezeteben ugyanaz az ertek — az elsot hasznaljuk)
        opened.clear()
        w._show_spread_params("GOLD")
        check("a Spread a parameter-ablakot nyitja",
              opened == [("GOLD", "wpr_sma")], str(opened))
    finally:
        if w is not None:
            w.root.destroy()

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

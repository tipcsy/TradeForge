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

# A K.Ossz. badge ⛔ glifat ir ki, a Windows-konzol pedig cp1250: enelkul a
# `print` szallna el, nem a teszt. (A `run_all.py` maga is ezt hivja.)
from core import applog
applog.harden_console()

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
        # FONTOS: az `ml_ai` a KET stadiuma melle az `ml_proba` SZAM-cellat is
        # beleirja a `live_cells`-be. Ha a sor a dict osszes kulcsat pottynek
        # veszi, egy harmadik, orokke halvany kor jelenik meg (elesben pont ez
        # tortent) — ezert szerepel itt is.
        d.strategy_cells = {
            "wpr_sma": {"sma": ("●", "green"), "m15": ("●", "green"),
                        "m1": ("●", "muted")},
            "ml_ai": {"model": ("●", "red"), "sig": ("●", "muted"),
                      "ml_proba": ("0.31/0.12", "white")}}
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
        # A REGI "live2" ertek v2.7.0 ota `canvas`-ra fordul (a widget-alapu
        # renderelo megszunt) — a meglevo configok nem torhetnek el emiatt.
        w2 = build_window("live2")
        check("a regi 'live2' config-ertek canvas-ra fordul",
              w2._layout_mode() == "canvas", w2._layout_mode())
        check("felepult a 2.0 tabla", getattr(w2, "_live2", None) is not None)
        _syms = {k[0] for k in w2._live2._items}
        check("annyi sor, ahany par", len(_syms) == len(CFG["pairs"]), str(_syms))
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
        # A frissites HELYBEN megy: ugyanazok a vaszon-ELEMEK maradnak
        # (ujraepiteskor uj azonositokat kapnanak).
        ids_before = dict(w2._live2._items)
        w2._live2.refresh(w2._live2_rows())
        check("a frissites HELYBEN tortenik (nincs ujraepites)",
              w2._live2._items == ids_before)
    finally:
        if w2 is not None:
            w2.root.destroy()

    # ══ 2. A classic VALTOZATLAN ══════════════════════════════════════════
    wc = None
    try:
        wc = build_window("classic")
        check("classic: nincs 2.0 tabla", getattr(wc, "_live2", None) is None)
        check("classic: vannak PairRow-sorok", len(wc.rows) == len(CFG["pairs"]))
        # v2.7.0 ota a VASZON az alapertelmezes (a widget-alapu 2.0 tabla
        # megszunt, a classic pedig kifejezetten kerendo).
        _no_key = type("C", (), {"cfg": {"dashboard": {}}})()
        check("hianyzo kulcs -> canvas az ALAPERTELMEZES",
              G.DashboardWindow._layout_mode(_no_key) == "canvas",
              G.DashboardWindow._layout_mode(_no_key))
        _classic = type("C", (), {"cfg": {"dashboard": {"layout": "classic"}}})()
        check("...a classic viszont kifejezetten kerheto",
              G.DashboardWindow._layout_mode(_classic) == "classic")
    finally:
        if wc is not None:
            wc.root.destroy()

    # ══ 3. Az Opt cella PER STRATEGIA es ROVID ════════════════════════════
    # Elesben itt "ia — ·" jelent meg: az elso valtozat a SZIMBOLUM-szintu,
    # OSSZETETT optimizer_status-t adta (pl. "Opt: wpr_sma 07/28 · ml_ai 07/28"),
    # amit a szuk cella kozepre igazitva vagott — a szoveg KOZEPE latszott, es
    # mindket strategia-blokk ugyanazt mutatta.
    w3 = None
    try:
        from core import opt_activity as _oa
        w3 = build_window("live2")

        # Nincs marker -> "—" (nem hosszu szoveg, nem szimbolum-szintu allapot)
        check("ismeretlen par Opt-cellaja rovid '—'",
              w3._live2_opt("NINCS_ILYEN_PAR", "wpr_sma") == "—")

        # A szimbolum-szintu (hosszu) statusz NEM szivarog be
        w3.optimizer_status["NINCS_ILYEN_PAR"] = "Opt: wpr_sma 07/28 · ml_ai 07/28"
        check("a hosszu szimbolum-szintu statusz NEM jelenik meg a cellaban",
              w3._live2_opt("NINCS_ILYEN_PAR", "wpr_sma") == "—")

        # Ha az ADOTT strategia epp fut, a SAJAT allapota latszik
        _oa.set_state("NINCS_ILYEN_PAR", "wpr_sma", "OPTIMIZING")
        try:
            check("futo optimalizalasnal rovid jelzes",
                  w3._live2_opt("NINCS_ILYEN_PAR", "wpr_sma") == "fut…",
                  w3._live2_opt("NINCS_ILYEN_PAR", "wpr_sma"))
            check("...a MASIK strategia ettol nem valtozik",
                  w3._live2_opt("NINCS_ILYEN_PAR", "ml_ai") == "—")
        finally:
            _oa.clear_symbol("NINCS_ILYEN_PAR")

        check("minden Opt-ertek elfer egy rovid cellaban (<= 8 karakter)",
              all(len(w3._live2_opt(s, n)) <= 8
                  for s in CFG["pairs"] for n in ("wpr_sma", "ml_ai")))
    finally:
        if w3 is not None:
            w3.root.destroy()

    # ══ 4. Az OPT gomb KOZVETLENUL hat, menu nelkul ═══════════════════════
    # A classic OPT gombja szimbolum-szintu, ezert tobb strategianal valaszto-
    # menut nyit. A 2.0-ban a gomb a strategia SAJAT blokkjaban ul, tehat a
    # valasztas mar megtortent — a menu ott folosleges kerdes lenne.
    w4 = None
    try:
        w4 = build_window("live2")
        calls = []
        # ⚠ A csonk ALAIRASA kovesse a valodit: a `request_optimize` v2.64.0 ota
        # `all_params`-t is kap (a „teljes ter" mod). Egy szuk csonk itt olyan
        # hibat produkal, aminek semmi koze a mert viselkedeshez.
        w4._opt_ctrl.request_optimize = (
            lambda s, n=None, all_params=False:
            calls.append(("start", s, n, all_params)))
        w4._opt_ctrl.request_stop = lambda s, n=None: calls.append(("stop", s, n))
        w4._opt_ctrl.cancel_queued = lambda s, n=None: calls.append(("cancel", s, n))
        w4._opt_ctrl._strategy_live = lambda s, n: False

        w4._live2_opt_click("Ger40", "ml_ai")
        check("az OPT KOZVETLENUL azt a strategiat inditja (nincs menu)",
              calls == [("start", "Ger40", "ml_ai", False)], str(calls))

        # ⚠ A SOR OPT gombja a MEGSZOKOTT futast kerje: `all_params=False`, azaz a
        # mentett kihagyas-lista ERVENYES. A „teljes ter" kifejezett valasztas, a
        # parameter-ablak Optimalizalas modja — nem eshet ide melle.
        check("a sor OPT gombja a mentett kihagyas-listaval indit",
              calls and calls[-1][3] is False, str(calls))

        # Futo optimalizalasnal LEALLIT — es CSAK azt a strategiat
        from core import opt_activity as _oa
        _oa.set_state("Ger40", "ml_ai", "OPTIMIZING")
        try:
            calls.clear()
            w4._live2_opt_click("Ger40", "ml_ai")
            check("futo optimalizalasnal leallit, a SAJAT strategiajara",
                  calls == [("stop", "Ger40", "ml_ai")], str(calls))
            calls.clear()
            w4._live2_opt_click("Ger40", "wpr_sma")
            check("...a MASIK strategia ettol fuggetlenul indithato",
                  calls == [("start", "Ger40", "wpr_sma", False)], str(calls))
        finally:
            _oa.clear_symbol("Ger40")

        # KERESKEDO strategiat nem optimalizalunk (a futas vegen felulirodna a
        # parameterfajlja, es egy nyilo belepo a REGI parameterekkel menne)
        calls.clear()
        w4._opt_ctrl._strategy_live = lambda s, n: True
        w4._live2_opt_click("Ger40", "wpr_sma")
        check("kereskedo strategiat NEM indit el", calls == [], str(calls))
    finally:
        if w4 is not None:
            w4.root.destroy()

    # ══ 5. A jelzes-pottyok a strategia KANONIKUS stadiumai ═══════════════
    # A motor a `strategy_cells`-be a stadiumok MELLE mas cellakat is irhat (az
    # `ml_ai` az `ml_proba` szam-cellat). A pottyoknek a `columns()` stages
    # mezoje a forrasa — ugyanaz, amibol a `classic` korei jonnek —, kulonben
    # a szam-cella harmadik, orokke halvany pottykent jelenne meg.
    w5 = None
    try:
        w5 = build_window("live2")
        st = {s["name"]: s for s in w5._live2_rows()[0]["strategies"]}
        check("az ml_ai-nak PONTOSAN 2 pottye van (a proba-cella nem pötty)",
              len(st["ml_ai"]["stages"]) == 2, str(st["ml_ai"]["stages"]))
        check("...es a sorrend a columns() szerinti (model, sig)",
              st["ml_ai"]["stages"] == ["red", "muted"], str(st["ml_ai"]["stages"]))
        check("a wpr_sma harom stadiuma valtozatlan",
              st["wpr_sma"]["stages"] == ["green", "green", "muted"],
              str(st["wpr_sma"]["stages"]))
        check("a stadium-sorrend a strategiabol jon, nem a dict-bol",
              w5._live2_stage_order("ml_ai") == ("model", "sig"),
              str(w5._live2_stage_order("ml_ai")))
        check("ismeretlen strategianal None (marad a regi viselkedes)",
              w5._live2_stage_order("nincs_ilyen") is None)
    finally:
        if w5 is not None:
            w5.root.destroy()

    # ══ 6. Napi P&L bontas a GUI-ban — MEGALLITOTT paron is ═══════════════
    # A `live_trader.daily_split_cached()` csak a `process_pair`-bol hivodik, az
    # pedig KIZAROLAG LIVE/CLOSING paron fut. Egy megallitott paron (vagy a bot
    # ujrainditasa utan) a bontas sosem szuletett meg, es a cella `—` maradt,
    # holott a `classic` oszlop ugyanabbol a `closed_today` cache-bol hozta a
    # szamot. A GUI ezert maga is kiszamolja.
    w6 = None
    try:
        w6 = build_window("live2")
        closed = [
            {"symbol": "GOLD", "magic": 0, "position": 111, "pnl": 21.0},
            {"symbol": "GOLD", "magic": 0, "position": 112, "pnl": -6.0},
            {"symbol": "Ger40", "magic": 0, "position": 113, "pnl": 3.0},
        ]
        # A feloldo a magicbol dolgozik: a `wpr_sma` magicje a broker.magic (0).
        split = w6._daily_split(closed)
        check("a bontas eloallt a lezart listabol", split is not None)
        check("a GOLD ket kotese OSSZEADODIK",
              split.get(("GOLD", "wpr_sma"), {}).get("pnl") == 15.0, str(split))
        check("a masik szimbolum kulon bucket",
              split.get(("Ger40", "wpr_sma"), {}).get("pnl") == 3.0, str(split))

        # A sor tenyleg ezt mutatja — egy MEGALLITOTT paron is (minden par
        # STOPPED ebben a tesztben).
        for _sym, _ds in w6.dashboard_ref.items():
            _ds.daily_by_strategy = G._pnl_split.for_symbol(split, _sym)
        by = {r["symbol"]: r for r in w6._live2_rows()}
        gold = {s["name"]: s for s in by["GOLD"]["strategies"]}
        check("a megallitott par Napi P&L cellaja NEM ures",
              gold["wpr_sma"]["daily"]["money"] == 15.0,
              str(gold["wpr_sma"]["daily"]))
        check("a sor osszesitoje a blokkok osszege",
              by["GOLD"]["total"]["daily"]["money"] == 15.0,
              str(by["GOLD"]["total"]["daily"]))

        # A gyorsitotar: valtozatlan lista -> UGYANAZ az objektum (a `_refresh`
        # masodpercenkent hiv, folosleges ujraszamolas nelkul).
        check("valtozatlan listanal a bontas gyorsitotarazott",
              w6._daily_split(closed) is split)
        check("valtozott listanal ujraszamol",
              w6._daily_split(closed[:1]) is not split)

        # Hozza nem rendelt kotes: `None` strategia (nem "—") — az adat ne
        # keveredjen a formazassal, lasd core/pnl_split.py.
        orphan = w6._daily_split([{"symbol": "GOLD", "magic": 999999,
                                   "position": 900, "pnl": 5.0}])
        check("a hozza nem rendelt kotes None strategiahoz kerul",
              ("GOLD", None) in orphan, str(orphan))
    finally:
        if w6 is not None:
            w6.root.destroy()

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

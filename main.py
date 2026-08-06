"""
Főindító script.

Parancsok:
  python main.py download     — historikus adatok letöltése MT5-ből
  python main.py optimize     — AI paraméter optimalizálás / tanítás
  python main.py live         — élő kereskedés + dashboard
  python main.py dashboard    — csak dashboard (demo mód, MT5 nélkül)
  python main.py backtest     — backtest futtatás az alapértelmezett paraméterekkel

Az `optimize` pár × STRATÉGIA szinten dolgozik. Stratégia megadása nélkül minden
páron a SAJÁT engedélyezett stratégiái futnak (pairs.<sym>.strategies) — ugyanaz a
halmaz, amit a motor is futtat:

  python main.py optimize                         — minden aktív pár, mindegyik stratégiája
  python main.py optimize EURUSD GBPJPY           — csak ez a két pár
  python main.py optimize Ger40 --strategy ml_ai  — egy pár, egy stratégia (tanítható → tanítás)
  python main.py optimize --strategy ml_ai        — minden pár, csak az ml_ai
  python main.py optimize -s wpr_sma,ml_ai        — vesszős rövid alak

TradeForge — Copyright (C) 2026 tipcsy. Ez a program MINDENFÉLE GARANCIA NÉLKÜL
készült, és szabadon terjesztheted a GNU GPL v3 feltételei szerint (lásd LICENSE).
"""

import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CFG_PATH = ROOT / "config.json"


def load_cfg() -> dict:
    # A váz config.json + az aktív stratégia saját beállításainak beolvasztása.
    from strategy.settings import load_config
    cfg = load_config(CFG_PATH)
    # KOHERENCIA-ellenőrzés: az önmagában érvényes, de önellentmondó beállítások
    # kiírása (pl. bekapcsolt kapu, aminek nincs mit mérnie). MINDEN parancs ezen
    # a függvényen jön be, tehát a live, a backteszt és az optimalizálás ugyanazt
    # a képet kapja. Csak SZÓL — nem javít és nem gátol (lásd core/config_check.py).
    try:
        from core import config_check
        config_check.log_findings(cfg)
    except Exception:
        pass
    return cfg


def _setup_log():
    """Perzisztens (forgó) futásnapló: data/tradeforge.log. A konzolos kimenet
    marad — ez csak kiegészíti, hogy utólag is visszakereshető legyen, mi történt."""
    from core import applog
    applog.setup()


def cmd_download():
    from tools.download_history import main
    main()


def cmd_optimize(symbols=None, strategies=None):
    """Optimalizálás/tanítás — pár × STRATÉGIA.

    `strategies` nélkül páronként a SAJÁT engedélyezett stratégiái futnak
    (`pairs.<sym>.strategies`), tehát ugyanaz a halmaz, amit a motor is futtat.
    A v1.97.0-ig ez mindig a config elsődleges stratégiája volt, függetlenül a
    pártól — így az `ml_ai`-t CLI-ből egyáltalán nem lehetett tanítani."""
    from ml.optimizer import run_optimizer
    from strategy import available_strategy_names, registered_strategy_names
    cfg = load_cfg()
    if strategies:
        avail = available_strategy_names(cfg)
        unknown = [n for n in strategies if n not in avail]
        if unknown:
            # Beszédes hiba: a puszta „ismeretlen stratégia" nem mondaná meg,
            # hogy a név ROSSZ-e, vagy csak ki van kapcsolva a configban.
            reg = registered_strategy_names()
            for n in unknown:
                if n in reg:
                    print(f"A(z) {n!r} stratégia ki van kapcsolva "
                          f"(config.json → available_strategies).")
                else:
                    print(f"Ismeretlen stratégia: {n!r}")
            print(f"Elérhető: {', '.join(avail)}")
            return 1
    run_optimizer(cfg, symbols or None, strategies or None)
    return 0


def cmd_backtest():
    from trading.backtest import run_backtest
    cfg = load_cfg()
    run_backtest(cfg)


def cmd_live():
    from core import mt5_connector
    from core.risk_manager import SlotManager
    from trading.live_trader import run, dashboard, instrument_state, optimizer_status
    from dashboard.gui import DashboardWindow

    cfg = load_cfg()

    if not mt5_connector.connect(cfg):
        sys.exit(1)

    slot_mgr = SlotManager(cfg["trading"]["max_open_slots"])

    # Live trader szálban fut
    trader_thread = threading.Thread(
        target=run,
        args=(cfg, slot_mgr),
        daemon=True,
        name="LiveTrader",
    )
    trader_thread.start()

    # Rövid várakozás hogy a live_trader inicializálja a dashboard/instrument_state dict-eket
    import time
    time.sleep(1)

    # Dashboard főszálon (tkinter csak főszálból futhat)
    def on_slots_change(new_max):
        slot_mgr.max_slots = new_max

    win = DashboardWindow(
        cfg, dashboard, instrument_state, optimizer_status,
        on_play_pair=None,   # instrument_state váltás elegendő, a run() loop felkapja
        on_stop_pair=None,
        on_slots_change=on_slots_change,
        auto_resume_opt=True,   # induláskor a megszakadt optimalizálások folytatása
    )

    def update_header():
        balance = mt5_connector.account_balance()
        win.set_balance(balance)
        free = slot_mgr.free()
        win.set_slots(free, slot_mgr.max_slots)
        win.root.after(5000, update_header)

    win.root.after(1000, update_header)

    try:
        win.run()
    finally:
        mt5_connector.disconnect()


def cmd_dashboard():
    """Demo mód — MT5 nélkül, szimulált adatokkal."""
    from dashboard.gui import DashboardWindow, _demo_dashboard
    cfg = load_cfg()
    db, inst_state, opt_status, n_pos = _demo_dashboard(cfg)
    win = DashboardWindow(
        cfg, db, inst_state, opt_status,
        on_play_pair=None,
        on_stop_pair=None,
    )
    max_s = cfg["trading"]["max_open_slots"]
    win.set_balance(1024.50)
    win.set_slots(free=max(0, max_s - n_pos), max_s=max_s)
    win.run()


COMMANDS = {
    "download":  (cmd_download,   []),
    "optimize":  (cmd_optimize,   "symbols"),
    "backtest":  (cmd_backtest,   []),
    "live":      (cmd_live,       []),
    "dashboard": (cmd_dashboard,  []),
}


def parse_optimize_args(argv: list) -> tuple:
    """`optimize` argumentumok → `(symbols, strategies)`; `None` = „mind/alapértelmezett".

    Alakok (a `--strategy` bárhol állhat, és ismételhető):

        optimize                                → minden pár, páronként a sajátjai
        optimize Ger40 UsaTec                   → két pár, páronként a sajátjai
        optimize Ger40 --strategy ml_ai         → egy pár, csak az ml_ai
        optimize --strategy ml_ai               → minden pár, csak az ml_ai
        optimize -s wpr_sma,ml_ai               → vesszős rövid alak

    Külön függvény (nem inline az `__main__`-ban), hogy TESZTELHETŐ legyen — a
    parancssor-értelmezés csendes hibája máskülönben csak élesben derülne ki."""
    symbols, strategies = [], []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--strategy", "-s"):
            i += 1
            if i < len(argv):
                strategies += [x for x in argv[i].split(",") if x]
        elif a.startswith("--strategy="):
            strategies += [x for x in a.split("=", 1)[1].split(",") if x]
        else:
            symbols.append(a)
        i += 1
    return (symbols or None), (strategies or None)


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]
    fn, arg_spec = COMMANDS[cmd]
    _setup_log()

    if arg_spec == "symbols":
        _syms, _strats = parse_optimize_args(sys.argv[2:])
        sys.exit(fn(_syms, _strats) or 0)
    else:
        fn()

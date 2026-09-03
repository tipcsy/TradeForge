"""
Főindító script.

Parancsok:
  python main.py download     — historikus adatok letöltése MT5-ből
  python main.py optimize     — AI paraméter optimalizálás / tanítás
  python main.py live         — élő kereskedés + dashboard
  python main.py console      — élő kereskedés FELÜLET NÉLKÜL (gyenge gép, VM, SSH)
  python main.py console --tui — ugyanaz, élő táblázattal (a `rich` csomag kell hozzá)
  python main.py notify-test  — a Telegram-értesítés beüzemelése és próbája
  python main.py dashboard    — csak dashboard (demo mód, MT5 nélkül)
  python main.py backtest     — backtest futtatás az alapértelmezett paraméterekkel
  python main.py lab          — kézi laboratórium: chart-ablak (Qt, külön processz)
  python main.py lab-mpl      — ugyanaz a régi, matplotlib-es felülettel

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

from core.i18n import t as _t
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
                    print(_t("cli.strategy_off", name=repr(n)))
                else:
                    print(_t("cli.strategy_unknown", name=repr(n)))
            print(_t("cli.available", names=", ".join(avail)))
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

    # ── LICENC-KAPU ───────────────────────────────────────────────────────
    # ⚠ CSAK az élő kereskedés van kapuzva. A backtest, az optimalizálás és az
    # adatletöltés licenc nélkül is fut: azok nem nyúlnak a brókerszámlához, és
    # ha egy lejárt licenc a backtestet is blokkolná, épp akkor nem tudnál
    # dolgozni a rendszeren, amikor a megújításról döntesz.
    #
    # ⚠ A KAPCSOLÓDÁS UTÁN van, mert a számlaszám az MT5-ből jön — a licenc
    # ehhez a SZÁMLÁHOZ szól, nem a géphez.
    from core.licence_gate import ensure_licence
    from version import APP_VERSION
    _acc = mt5_connector.connection_info(cfg)
    if not ensure_licence(cfg, str(_acc.get("login") or ""),
                          account_name=str(_acc.get("name") or ""),
                          broker_server=str(_acc.get("server") or ""),
                          app_version=APP_VERSION):
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
        # A slot-keret az egyenleggel és a felületen állított kockázat-%-kal is
        # változik → frissítjük, mielőtt a szabad keretet kiolvassuk.
        slot_mgr.set_budget(balance, cfg["trading"])
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


def cmd_console():
    """FEJ NÉLKÜLI élő kereskedés + egyszerű parancssor.

    ⚠ MIÉRT VAN EZ KÜLÖN PARANCS. A `live` a tkinter-felületet a FŐSZÁLON
    futtatja (a tkinter csak onnan mehet), a motort pedig szálban — gyenge
    gépen (VM) viszont épp a felület a fölösleges. Itt fordítva: a motor megy
    szálban, a főszálon pedig egy parancssor ül. **A motor kódja ugyanaz**; a
    `trading.live_trader.run` nem ismeri, ki figyeli.

    ⚠ A PARANCSOK NEM ITT LAKNAK. A szabályok (`play`/`stop`/`close`) a
    `core.console_cmd`-ben vannak — ugyanonnan fogja használni a TUI és a
    Telegram is. Ez a függvény csak beolvas, kiír, és rákérdez."""
    from core import console_cmd, licence, live_lock, mt5_connector
    from core.risk_manager import SlotManager
    from trading.live_trader import run
    from trading import live_trader as lt
    from version import APP_VERSION

    _setup_log()
    cfg = load_cfg()

    if not mt5_connector.connect(cfg):
        print(_t("console.mt5.failed"))
        return 1

    _acc = mt5_connector.connection_info(cfg)
    _szamla = str(_acc.get("login") or "")

    # ⚠ A FUTÁS-ZÁR A LICENC ELŐTT. Egy második példány ne is kopogtasson a
    # licencszerveren — és a felhasználó a VALÓDI okot lássa elsőként.
    _ok, _akadaly = live_lock.acquire(_szamla, note="console")
    if not _ok:
        print(_t("console.lock.held", account=_szamla,
                 info=live_lock.describe(_akadaly),
                 path=live_lock.lock_path(_szamla)))
        mt5_connector.disconnect()
        return 1
    # ⚠ A ZÁR VÉDELEM, NEM FELTÉTEL: ha nem sikerült KIÍRNI (írásvédett mappa,
    # tele lemez), az `acquire` szándékosan enged — egy fájlhiba miatt ne álljon
    # le a kereskedés. De akkor SZÓLUNK: a védelem elveszett, és a felhasználó
    # ne higgye, hogy egy második indítás fel fog akadni rajta.
    if not live_lock.lock_path(_szamla).exists():
        print(_t("console.lock.unprotected", path=live_lock.lock_path(_szamla)))

    # ⚠ `interactive=False`: a licenc-kapu belépő-ablaka TKINTER — SSH-n meg sem
    # jelenne, a program pedig egy láthatatlan ablakra várva állna. Fej nélkül
    # inkább megmondjuk, mit kell tenni.
    from core.licence_gate import ensure_licence
    if not ensure_licence(cfg, _szamla,
                          account_name=str(_acc.get("name") or ""),
                          broker_server=str(_acc.get("server") or ""),
                          app_version=APP_VERSION, interactive=False):
        _r = licence.last_result()
        if _r is not None and _r.needs_login:
            print(_t("console.licence.missing"))
        elif _r is not None:
            print(_r.message)
        live_lock.release(_szamla)
        mt5_connector.disconnect()
        return 1

    slot_mgr = SlotManager(cfg["trading"]["max_open_slots"])
    szal = threading.Thread(target=run, args=(cfg, slot_mgr),
                            daemon=True, name="LiveTrader")
    szal.start()

    def _kilep():
        """A leállítás EGY helyen: a motor körhatáron áll meg, aztán elengedjük
        a zárat és a kapcsolatot. ⚠ A zár elengedése nem elhagyható — enélkül a
        következő indulás egy elárvult zárat találna."""
        print(_t("console.quit"))
        lt.request_stop()
        szal.join(timeout=15)
        print(_t("console.stopped"))
        live_lock.release(_szamla)
        mt5_connector.disconnect()

    ctx = console_cmd.live_context(cfg, CFG_PATH)
    _interaktiv = bool(sys.stdin) and sys.stdin.isatty()

    # ── TÁBLÁZATOS NÉZET (--tui) ──────────────────────────────────────────
    # ⚠ Ugyanaz a `ctx`, ugyanazok a parancsok — csak MÁS megjelenítő. A `rich`
    # hiánya nem hiba: a parancssoros mód enélkül is megy, csak megmondjuk, mit
    # kell telepíteni. Egy importhiba miatt ne álljon meg a kereskedés.
    if "--tui" in sys.argv:
        from core import console_tui
        if not console_tui.elerheto():
            print(_t("console.tui.missing"))       # → marad a parancssor
        elif _interaktiv:                          # élő táblát csak terminálra
            try:
                console_tui.fut(ctx, megall=lt.stop_requested)
            except KeyboardInterrupt:
                pass
            finally:
                _kilep()
            return 0

    print(_t("console.banner", version=APP_VERSION))

    try:
        # ⚠ NEM INTERAKTÍV indulásnál (szolgáltatás, átirányított bemenet) az
        # `input()` azonnal EOF-ot adna, és a program kilépne — pont akkor, ha
        # a legkevésbé akarjuk. Ott a motor prompt nélkül fut.
        if not _interaktiv:
            print(_t("console.noninteractive"))
            while szal.is_alive():
                szal.join(timeout=1.0)
            return 0
        while True:
            try:
                sor = input(_t("console.prompt"))
            except EOFError:
                break
            res = console_cmd.dispatch(ctx, sor)
            if res.confirm:
                valasz = input(_t("console.confirm", text=res.confirm))
                if valasz.strip().lower() != _t("console.confirm_yes"):
                    print(_t("console.cancelled"))
                    continue
                res = console_cmd.dispatch(ctx, sor, confirmed=True)
            for ln in res.lines:
                print(ln)
            if res.quit:
                break
    except KeyboardInterrupt:
        pass
    finally:
        _kilep()
    return 0


def cmd_notify_test():
    """A Telegram-értesítés BEÜZEMELÉSE és próbája.

    ⚠ MIÉRT KELL EZ A PARANCS. Egy elgépelt tokentől vagy egy hiányzó
    címzettől a program **némán** nem küld semmit — és a felhasználó a
    kereskedésben keresné a hibát. Itt mindegyik lépés megmondja, mi a baj,
    és a `chat_id`-t magától megtalálja."""
    from core import telegram
    from strategy.settings import save_main_config
    from version import APP_VERSION

    cfg = load_cfg()
    n = (cfg.get("notify") or {})
    tg = n.get("telegram") or {}
    token = str(tg.get("token") or "")
    if not n:
        print(_t("notify.cli.no_config"))
        return 1
    if not token:
        print(_t("notify.cli.no_token"))
        return 1

    # 1. A TOKEN — ez az egyetlen olcsó módja megmondani, hogy elgépelted-e.
    ok, nev = telegram.me(token)
    if not ok:
        print(_t("notify.cli.bad_token", hiba=nev))
        return 1
    print(_t("notify.cli.ok_token", name=nev))
    if not n.get("enabled"):
        # ⚠ NEM állítjuk át magunktól: a kikapcsolt állapot lehet szándékos.
        print(_t("notify.cli.disabled"))

    # 2. A CÍMZETT — ha nincs, megkeressük, ki írt eddig a botnak.
    ids = [str(x) for x in (tg.get("chat_ids") or []) if str(x).strip()]
    if ids:
        print(_t("notify.cli.have_ids", ids=", ".join(ids)))
    else:
        print(_t("notify.cli.searching"))
        talalt = telegram.discover_chats(token)
        if not talalt:
            print(_t("notify.cli.none_found", name=nev))
            return 1
        for t in talalt:
            print("  " + _t("notify.cli.found", name=t["name"], id=t["id"]))
        ids = [t["id"] for t in talalt]
        # ⚠ AZ `isatty()` NEM ELÉG. Van olyan környezet (átirányított bemenet,
        # leválasztott konzol), ahol terminált jelez, az `input()` mégis
        # EOF-ot dob — és akkor a beüzemelő parancs egy stack trace-szel áll
        # meg, pont a legutolsó lépés előtt. A hiányzó válasz nem hiba: ezt a
        # parancsot azért futtatod, hogy beállítsa.
        _ir = True
        if sys.stdin and sys.stdin.isatty():
            try:
                _ir = input(_t("notify.cli.save_q")).strip().lower() in ("i", "y")
            except EOFError:
                _ir = True
        if _ir:
            tg["chat_ids"] = ids
            cfg.setdefault("notify", {})["telegram"] = tg
            try:
                save_main_config(cfg, CFG_PATH)
                print(_t("notify.cli.saved"))
            except Exception:
                print(_t("notify.cli.save_failed"))

    # 3. A PRÓBAÜZENET — a teljes út végigjárása, a valódi küldő függvénnyel.
    print(_t("notify.cli.sending"))
    if telegram.send(token, ids, _t("notify.cli.test_text", version=APP_VERSION)):
        print(_t("notify.cli.sent"))
        return 0
    print(_t("notify.cli.send_failed"))
    return 1


def cmd_lab(argv=None):
    """Kezi laboratorium — chart-ablak (2. lepcso).

    KULON PROCESSZ, szandekosan: a 2. pont epp arrol szolt, hogy a motor gyenge
    gepen onmagaban fusson — egy chart-rajzolo ablak ne ugyanabban a
    processzben legyen, mint az elo kereskedes. A modulokat viszont HASZNALJA
    (nem masolja): a gyertyak a parquetbol, a rajz a `pair_visual_objects`-bol."""
    from tools.lab_qt import main as _lab
    return _lab(argv or [])


def cmd_lab_mpl(argv=None):
    """A kezi labor REGI, matplotlib-es valtozata.

    ⚠ SZANDEKOSAN MEGMARADT. A Qt-s valtozat (v3.24.0) mindent tud, amit ez —
    de amig nem futott eleg valos helyzeten, a regi legyen elerheto. Ha a
    Qt-s bevalt, ez torolheto."""
    from tools.lab_chart import main as _lab
    return _lab(argv or [])


COMMANDS = {
    "download":  (cmd_download,   []),
    "optimize":  (cmd_optimize,   "symbols"),
    "backtest":  (cmd_backtest,   []),
    "live":      (cmd_live,       []),
    "console":   (cmd_console,    []),
    "notify-test": (cmd_notify_test, []),
    "dashboard": (cmd_dashboard,  []),
    "lab":       (cmd_lab,        "argv"),
    "lab-mpl":   (cmd_lab_mpl,    "argv"),
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
    # ⚠ A KONZOL-KÓDLAP MÁR A SÚGÓ ELŐTT. A Windows-konzol cp1250: a súgó
    # nyilai (→) és gondolatjelei `UnicodeEncodeError`-ral szálltak el, tehát
    # `python main.py` ARGUMENTUM NÉLKÜL egy stack trace-t adott a parancsok
    # listája helyett. Épp azt, amivel egy konzolos felhasználó kezdi.
    try:
        from core import applog as _applog
        _applog.harden_console()
    except Exception:
        pass

    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]
    fn, arg_spec = COMMANDS[cmd]
    _setup_log()

    if arg_spec == "symbols":
        _syms, _strats = parse_optimize_args(sys.argv[2:])
        sys.exit(fn(_syms, _strats) or 0)
    elif arg_spec == "argv":
        # A parancs SAJAT argumentumai (a `lab` argparse-a dolgozza fel).
        sys.exit(fn(sys.argv[2:]) or 0)
    else:
        # ⚠ A KILÉPÉSI KÓD SZÁMÍT: a `notify-test` és a `console` hibát is
        # jelenthet, és egy szkript (vagy egy szolgáltatás-felügyelő) ebből
        # tudja meg, hogy baj van. Eddig minden futás 0-val tért vissza.
        sys.exit(fn() or 0)

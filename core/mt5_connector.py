import MetaTrader5 as mt5
import logging
import threading
from pathlib import Path
from typing import Optional

from core import order_exec

log = logging.getLogger(__name__)

# MT5 Python API nem thread-safe — minden hívást ezen a lockon keresztül kell intézni.
#
# RE-ENTRÁNS (RLock), szándékosan: a hívási láncok mélyek (pl. a viz-szál →
# get_candles → symbol_info), és egy sima Lock-nál egyetlen véletlen egymásba
# ágyazás AZONNALI HOLTPONTOT okozna — a kereskedési szál némán megállna, nyitott
# pozíciókkal. Az RLock ugyanazon a szálon újra fogható; a szálak közti kizárás
# (ami a cél) változatlan.
#
# A lockot RÖVIDEN kell fogni: csak a konkrét MT5-hívás idejére, sosem a rá épülő
# Python-számítás (indikátorok, rajz-objektumok) alatt — különben a viz-szál
# kiéheztetné a kereskedést.
MT5_LOCK = threading.RLock()


def _init_kwargs(mt5_cfg: dict) -> dict:
    """A config `mt5` szekciójából az initialize kwargs-ai (path + portable).
    A `path` a KONKRÉT terminált adja meg — több MT5 esetén EZ dönti el, melyikhez
    kapcsolódunk; portable módban a terminál a saját mappájából olvas."""
    kwargs = {}
    if mt5_cfg.get("path"):
        kwargs["path"] = mt5_cfg["path"]
    if mt5_cfg.get("portable"):
        kwargs["portable"] = True
    return kwargs


# ---------------------------------------------------------------------------
# Számla margin-mód (NETTING / HEDGING / EXCHANGE)
# ---------------------------------------------------------------------------
# A számlatípus futás közben NEM változik → induláskor (connect) EGYSZER
# lekérdezzük és cache-eljük. Miért számít: NETTING (és EXCHANGE) számlán egy
# szimbólumon csak EGY nettó pozíció lehet, így a kockázatmentes runner mellé
# nyíló új belépő ÖSSZEVONÓDIK vele — a részleges záráson alapuló technikák
# (Felező/Pajzs/Pajzs↔Fibo) ilyenkor nem működnek helyesen.
MARGIN_NETTING  = 0   # ACCOUNT_MARGIN_MODE_RETAIL_NETTING
MARGIN_EXCHANGE = 1   # ACCOUNT_MARGIN_MODE_EXCHANGE
MARGIN_HEDGING  = 2   # ACCOUNT_MARGIN_MODE_RETAIL_HEDGING
MARGIN_NAME = {MARGIN_NETTING: "NETTING", MARGIN_EXCHANGE: "EXCHANGE",
               MARGIN_HEDGING: "HEDGE"}

_MARGIN_MODE = None   # a connect() tölti; None = még ismeretlen


def margin_mode():
    """A számla margin-módja (0/1/2), vagy None ha ismeretlen. Első hívásra
    lekérdezi, utána cache-elt (a számlatípus futás közben nem változik)."""
    global _MARGIN_MODE
    if _MARGIN_MODE is None:
        try:
            with MT5_LOCK:
                info = mt5.account_info()
            if info is not None:
                _MARGIN_MODE = int(info.margin_mode)
        except Exception:
            pass
    return _MARGIN_MODE


def margin_mode_name() -> str:
    """A számlatípus emberi neve a kijelzéshez: NETTING | HEDGE | EXCHANGE | —."""
    m = margin_mode()
    if m is None:
        return "—"
    return MARGIN_NAME.get(m, f"MODE{m}")


def is_netting() -> bool:
    """Nettósító számla-e (NETTING vagy EXCHANGE)? Ilyenkor a részleges záráson
    alapuló kockázatcsökkentő technikák TILTVA/degradálva vannak. Ismeretlen
    (None) → False, hogy a kapcsolat nélküli/demo állapot ne tiltson feleslegesen."""
    return margin_mode() in (MARGIN_NETTING, MARGIN_EXCHANGE)


def connect(cfg: dict) -> bool:
    """MT5 inicializálás + bejelentkezés a config alapján, ELLENŐRZÉSSEL.

    Több MT5 párhuzamos futásakor kulcsfontosságú, hogy a config `mt5.path`
    terminálját a config `broker` fiókjával nyissuk — NEM a futó/alap MT5-öt.
    Ezért: (1) a login/server-t átadjuk az initialize-nak (a config terminálját
    a config fiókjával indítja), (2) a végén ELLENŐRIZZÜK, hogy tényleg a várt
    login@server-re kapcsolódtunk — ha nem, HIBÁVAL leállunk (nem dolgozunk
    csendben rossz fiókon)."""
    broker  = cfg["broker"]
    mt5_cfg = cfg.get("mt5", {})
    kwargs  = _init_kwargs(mt5_cfg)
    want_login  = int(broker["login"])
    want_server = broker["server"]

    with MT5_LOCK:
        # Robusztus út: path + portable + login/password/server EGYSZERRE →
        # a config terminálját a config fiókjával indítja/kapcsolja.
        ok = mt5.initialize(login=want_login, password=broker["password"],
                            server=want_server, **kwargs)
        if not ok:
            # Fallback (régi út): initialize path-tal, majd külön login.
            log.warning("MT5 initialize(login) sikertelen: %s — próbálom path+login úttal.",
                        mt5.last_error())
            if not mt5.initialize(**kwargs):
                log.error("MT5 initialize hiba: %s", mt5.last_error())
                return False
            if not mt5.login(want_login, password=broker["password"], server=want_server):
                log.error("MT5 login hiba: %s", mt5.last_error())
                mt5.shutdown()
                return False
        info = mt5.account_info()
        term = mt5.terminal_info()

    # ── ELLENŐRZÉS: tényleg a config FIÓKJÁHOZ kapcsolódtunk? ─────────────
    # A LOGIN a mérvadó fiók-azonosító (ez különbözteti meg a rossz terminált /
    # rossz brókert). A szerver-NÉV eltérése (azonos login mellett) NEM hiba, csak
    # elavult config-érték (pl. bróker átnevezte a szervert) → figyelmeztetés.
    if info is None:
        log.error("MT5 account_info üres a kapcsolódás után.")
        return False
    if int(info.login) != want_login:
        term_path = getattr(term, "path", "?") if term else "?"
        log.error(
            "MT5 ROSSZ FIÓK/TERMINÁL! Vártam login: %s (%s), kaptam: %s@%s (terminál: %s). "
            "Több MT5 fut? Ellenőrizd a config mt5.path-ot, és hogy MINDEN terminál "
            "PORTABLE módban fusson (külön mappával).",
            want_login, want_server, info.login, info.server, term_path)
        with MT5_LOCK:
            mt5.shutdown()
        return False
    if str(info.server) != str(want_server):
        log.warning(
            "MT5 szerver-név eltér: config '%s' != tényleges '%s' (login EGYEZIK: %s). "
            "Valószínűleg elavult config broker.server — ezzel a fiókkal FOLYTATOM. "
            "Érdemes a config-ban a broker.server-t '%s'-re frissíteni.",
            want_server, info.server, want_login, info.server)

    # Számlatípus EGYSZERI lekérdezése (nem változik futás közben). NETTING/EXCHANGE
    # esetén a részleges záráson alapuló technikák tiltva lesznek (lásd is_netting).
    global _MARGIN_MODE
    try:
        _MARGIN_MODE = int(info.margin_mode)
    except Exception:
        _MARGIN_MODE = None

    log.info("MT5 kapcsolódva | %s (login %s) | Egyenleg: %.2f %s | számlatípus: %s | terminál: %s",
             info.server, info.login, info.balance, info.currency,
             margin_mode_name(), mt5_cfg.get("path", "(alapértelmezett)"))
    if is_netting():
        log.warning("A számla %s → a részleges záráson alapuló technikák "
                    "(Felező/Pajzs/Pajzs↔Fibo) NEM választhatók és nem futnak "
                    "(egy szimbólumon csak egy nettó pozíció lehet).",
                    margin_mode_name())
    return True


def disconnect():
    with MT5_LOCK:
        mt5.shutdown()
    log.info("MT5 kapcsolat lezárva.")


# ---------------------------------------------------------------------------
# Kapcsolat-felügyelet (a kereskedési ciklus hívja minden körben)
# ---------------------------------------------------------------------------
# Eddig NEM volt újrakapcsolódás: ha az MT5 terminál újraindult (pl. éjszakai
# bróker-frissítés) vagy megszakadt a kapcsolat, a `copy_rates` None-t adott, a
# `process_pair` csendben visszatért — a motor tétlen maradt, a NYITOTT pozíciók
# pedig menedzsment (breakeven, trailing, kiszállási jel) NÉLKÜL, és semmi nem jelezte.

RECONNECT_BACKOFF_SEC = (5, 15, 30, 60, 120, 300)   # növekvő várakozás a próbák közt

_conn_state = {
    "next_try":  0.0,    # ekkor próbálkozhatunk újra (monoton óra)
    "attempt":   0,      # hányadik sikertelen próba sorozatban
    "was_down":  False,  # naplózás: a „megszakadt" üzenet egyszer menjen ki
    "last_note": "",     # az utoljára naplózott ok (ne ismétlődjön 10 mp-enként)
}


def connection_lost_since() -> bool:
    """Épp szakadt állapotban vagyunk-e (a felület jelzéséhez)."""
    return bool(_conn_state["was_down"])


def _note_once(msg: str, *args) -> None:
    """Ugyanazt az okot ne írjuk ki minden körben (10 mp-enként), csak változáskor."""
    key = msg % args if args else msg
    if _conn_state["last_note"] != key:
        _conn_state["last_note"] = key
        log.warning("%s", key)


def ensure_connected(cfg: dict) -> bool:
    """A kereskedéshez HASZNÁLHATÓ-e most az MT5? Ha nem, megpróbálja helyreállítani.

    Két, KÜLÖNBÖZŐ kezelést igénylő szakadás van:

      • **Terminál ↔ szerver**: a terminál fut, de nincs bróker-kapcsolat
        (`terminal_info().connected == False`). Újrainicializálni FELESLEGES —
        várni kell. Ilyenkor False-t adunk, de nem bántjuk a kapcsolatot.
      • **Python ↔ terminál**: az `account_info()` üres (a terminál újraindult, a
        session elszállt). Ezt ÚJRA-INICIALIZÁLÁSSAL lehet helyreállítani — ezt
        teszi a `connect()`, a fiók-ellenőrzésével együtt (sosem dolgozunk rossz
        fiókon), NÖVEKVŐ várakozással a próbák közt (ne ostromoljuk a terminált).

    True → mehet a kereskedés. False → ezt a kört ki kell hagyni.
    """
    import time as _t
    now = _t.monotonic()

    try:
        with MT5_LOCK:
            info = mt5.account_info()
            term = mt5.terminal_info()
    except Exception:
        info = term = None

    if info is not None:
        # Van API-kapcsolat — de a terminál össze van-e kötve a szerverrel?
        if term is not None and not getattr(term, "connected", True):
            _note_once("MT5: a terminál NINCS összekötve a bróker szerverével — "
                       "várakozás (ÚJ belépő nem nyílik, a meglévők kezelése is szünetel).")
            _conn_state["was_down"] = True
            return False
        if _conn_state["was_down"]:
            log.info("MT5 kapcsolat HELYREÁLLT (%s, login %s). A kereskedés folytatódik.",
                     info.server, info.login)
            _conn_state.update(was_down=False, attempt=0, next_try=0.0, last_note="")
        return True

    # ── Python ↔ terminál szakadás → újrakapcsolódás, backoff-fal ──────────
    _conn_state["was_down"] = True
    _note_once("MT5 KAPCSOLAT MEGSZAKADT (account_info üres). Újrakapcsolódás "
               "folyamatban — amíg nem áll helyre, a motor NEM kereskedik és a "
               "nyitott pozíciókat sem tudja kezelni!")
    if now < _conn_state["next_try"]:
        return False

    attempt = _conn_state["attempt"]
    wait = RECONNECT_BACKOFF_SEC[min(attempt, len(RECONNECT_BACKOFF_SEC) - 1)]
    _conn_state["next_try"] = now + wait
    _conn_state["attempt"]  = attempt + 1

    log.warning("MT5 újrakapcsolódási kísérlet #%d…", attempt + 1)
    try:
        with MT5_LOCK:
            mt5.shutdown()          # a fél-holt session eltakarítása az új initialize előtt
    except Exception:
        pass
    try:
        ok = connect(cfg)           # initialize + login + FIÓK-ELLENŐRZÉS
    except Exception as e:
        log.error("MT5 újrakapcsolódás kivétel: %s", e)
        ok = False
    if ok:
        log.info("MT5 újrakapcsolódás SIKERES (%d. kísérlet).", attempt + 1)
        _conn_state.update(was_down=False, attempt=0, next_try=0.0, last_note="")
        return True
    log.warning("MT5 újrakapcsolódás sikertelen — következő próba %d mp múlva.", wait)
    return False


def account_balance() -> float:
    with MT5_LOCK:
        info = mt5.account_info()
    return info.balance if info else 0.0


def account_currency() -> str:
    with MT5_LOCK:
        info = mt5.account_info()
    return info.currency if info else "USD"


def daily_pnl() -> Optional[float]:
    """
    A mai (BRÓKER-nap) lezárt ügyletek összesített P&L-je MT5-ből.
    None ha nem kapcsolódtunk, 0.0 ha nem volt kereskedés.

    A nap határa a `server_day_bounds`-ból jön (nem a gép helyi dátumából) — ez a
    napi veszteséglimit kapuja, tehát a határ csúszása azt jelentené, hogy a limit
    rossz időpontban nullázódik.

    Az összegzés MINDEN záró dealt tartalmaz: az `OUT` mellett az `OUT_BY`-t is (a
    fedező pozíciók egymással szembeni zárása). Eddig csak az `entry == 1` (OUT)
    számított, így a close-by-jal zárt ügyletek P&L-je kimaradt a napi limitből —
    miközben a „Lezárt ma" fül (`closed_positions_today`) már mindkettőt vette,
    tehát a két kijelzés ellentmondott egymásnak."""
    try:
        frm, to = server_day_bounds()
        with MT5_LOCK:
            deals = mt5.history_deals_get(frm, to)
        if deals is None:
            return None
        return sum(d.profit + d.commission + d.swap for d in deals
                   if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY))
    except Exception:
        return None


# A daily_pnl TTL-cache-e a live NAPI-LIMIT kapujához: a process_pair páronként
# másodpercenként fut, a history-lekérés viszont drága → 15 mp-ig a cache-elt
# értéket adjuk. Hiba/lekapcsolódás esetén a legutóbbi ismert érték él tovább
# (konzervatív: a limit-kapu nem "felejti el" a veszteséget egy hibás lekérésen).
_daily_pnl_cache = {"t": 0.0, "v": None}


def daily_pnl_cached(ttl: float = 15.0) -> Optional[float]:
    """A mai realizált P&L (daily_pnl) TTL-cache-elt változata a live kapuhoz."""
    import time as _t
    now = _t.time()
    if _daily_pnl_cache["v"] is not None and now - _daily_pnl_cache["t"] < ttl:
        return _daily_pnl_cache["v"]
    v = daily_pnl()
    if v is not None:
        _daily_pnl_cache["t"] = now
        _daily_pnl_cache["v"] = v
        return v
    return _daily_pnl_cache["v"]


def _pos_risk_free(p) -> bool:
    """Kockázatmentes-e a pozíció: az SL már a belépőn TÚL van a profit irányában.
    Ugyanaz az elv, mint a SlotManager induló helyreállításánál — így a kijelzés és
    a slot-számolás egyezik a motor logikájával."""
    if not p.sl or p.sl == 0.0:
        return False
    if p.type == 0:                 # BUY
        return p.sl >= p.price_open
    return p.sl <= p.price_open     # SELL


def open_positions_by_symbol() -> dict:
    """
    Visszaadja az MT5-ben nyitott pozíciókat szimbólum szerint AGGREGÁLVA.
    Egy szimbólumon több pozíció is lehet → összegzett P&L + darabszám.
    {symbol: {"pnl": float, "count": int, "occupied": int,
              "direction": "BUY"|"SELL"|"MIX", "risk_free": bool}}
      - occupied: a NEM kockázatmentes pozíciók száma (ennyi slotot foglal valóban)
      - risk_free: True, ha a szimbólum teljes kitettsége kockázatmentes
    """
    try:
        with MT5_LOCK:
            positions = mt5.positions_get()
        if not positions:
            return {}
        result = {}
        for pos in positions:
            agg = result.setdefault(pos.symbol, {
                "pnl": 0.0, "count": 0, "occupied": 0,
                "direction": None, "risk_free": False})
            agg["pnl"]   += pos.profit
            agg["count"] += 1
            if not _pos_risk_free(pos):
                agg["occupied"] += 1
            d = "BUY" if pos.type == 0 else "SELL"
            agg["direction"] = d if agg["direction"] in (None, d) else "MIX"
        for agg in result.values():
            agg["pnl"] = round(agg["pnl"], 2)
            agg["risk_free"] = (agg["occupied"] == 0)   # minden pozíció kockázatmentes
        return result
    except Exception:
        return {}


def open_positions_detailed() -> list:
    """Per-ticket részletes nyitott pozíciók (összes, magic-tól függetlenül).
    A pozíciókezelő fül ezt használja."""
    try:
        with MT5_LOCK:
            positions = mt5.positions_get()
        if not positions:
            return []
        out = []
        for p in positions:
            # Költség-tudatos BE mozgatható-e MOST? (a kézi BE gomb tiltásához a GUI-n —
            # így nem lehet némán nyomkodni, amíg a profit nem fedezi a költséget).
            be_feasible = False
            try:
                _pinfo = mt5.symbol_info(p.symbol)
                if _pinfo is not None:
                    _, be_feasible = _breakeven_plan(p, _pinfo)
            except Exception:
                be_feasible = False
            out.append({
                "ticket":        p.ticket,
                "symbol":        p.symbol,
                "type":          "BUY" if p.type == 0 else "SELL",
                "volume":        p.volume,
                "price_open":    p.price_open,
                "price_current": p.price_current,
                "sl":            p.sl,
                "tp":            p.tp,
                "profit":        round(p.profit + p.swap, 2),
                "magic":         p.magic,
                "risk_free":     _pos_risk_free(p),
                "be_feasible":   bool(be_feasible),
            })
        return out
    except Exception:
        return []


def closed_positions_today() -> list:
    """A MAI napon (a BRÓKER naptára szerint) LEZÁRT pozíciók — a „Lezárt napi
    pozíciók" fülhöz. A felület felirata („MT5 szerver-idő") eddig nem teljesült:
    a nap határa a gép HELYI dátumából jött, UTC-nek címkézve.

    Az MT5 deal-előzményből pozíciónként összegzi: nyitó/záró ár, irány, lot,
    P&L (a záró deal-ök profit+jutalék+swap-ja — a daily_pnl konvenciójával
    egyezik), magic. A ma zárt, de KORÁBBAN nyitott pozíciók nyitó dealjét külön
    lekéri. Rendezve zárási idő szerint.
    """
    try:
        frm, to = server_day_bounds()          # a BRÓKER napja (nem a gép helyi dátuma)
        with MT5_LOCK:
            deals = mt5.history_deals_get(frm, to)
        if not deals:
            return []
        agg: dict = {}
        for d in deals:
            p = agg.setdefault(d.position_id, {
                "in": None, "pnl": 0.0, "close_price": None, "close_time": None})
            if d.entry == mt5.DEAL_ENTRY_IN:
                p["in"] = d
            elif d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY):
                p["pnl"]        += d.profit + d.commission + d.swap
                p["close_price"] = d.price
                p["close_time"]  = d.time
        out = []
        for pid, p in agg.items():
            if p["close_time"] is None:
                continue                     # ma nyitott, még nyitva → nem lezárt
            din = p["in"]
            if din is None:                  # korábban nyitott, ma zárt → nyitó deal külön
                with MT5_LOCK:
                    hist = mt5.history_deals_get(position=pid)
                for d in hist or []:
                    if d.entry == mt5.DEAL_ENTRY_IN:
                        din = d
                        break
                if din is None:
                    continue
            # KEZDETI SL a nyitó ORDER-ből (a deal nem hordozza). Ebből számol R-t a
            # dashboard. A SL-módosítás (pl. breakeven) külön order → a nyitó order
            # sl-je marad az EREDETI kockázati táv. Hiány/0 → None (R = „—").
            sl_open = None
            try:
                with MT5_LOCK:
                    ords = mt5.history_orders_get(ticket=din.order)
                if ords and ords[0].sl:
                    sl_open = ords[0].sl
            except Exception:
                sl_open = None
            out.append({
                "position":    pid,
                "symbol":      din.symbol,
                "type":        "BUY" if din.type == mt5.DEAL_TYPE_BUY else "SELL",
                "volume":      din.volume,
                "price_open":  din.price,
                "price_close": p["close_price"],
                "close_time":  p["close_time"],
                "magic":       din.magic,
                "sl":          sl_open,
                "pnl":         round(p["pnl"], 2),
            })
        out.sort(key=lambda x: x["close_time"])
        return out
    except Exception:
        return []


def close_position(ticket: int) -> bool:
    """Egy pozíció azonnali piaci zárása (Pánik gomb)."""
    try:
        with MT5_LOCK:
            pos = mt5.positions_get(ticket=ticket)
            if not pos:
                return False
            p = pos[0]
            tick = mt5.symbol_info_tick(p.symbol)
            if tick is None:
                return False
            close_type = mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY
            price = tick.bid if p.type == 0 else tick.ask
            # Csúszás-tűrés + a szimbólum által TÁMOGATOTT kitöltési mód: enélkül a
            # zárás pont akkor bukhat el (requote / 10030), amikor a legfontosabb.
            info = mt5.symbol_info(p.symbol)
            req = {
                "action":       mt5.TRADE_ACTION_DEAL,
                "symbol":       p.symbol,
                "volume":       p.volume,
                "type":         close_type,
                "position":     ticket,
                "price":        price,
                "deviation":    order_exec.deviation_points(p.symbol, None, info),
                "magic":        p.magic,
                "comment":      "panic_close",
                "type_time":    mt5.ORDER_TIME_GTC,
                "type_filling": order_exec.filling_mode(p.symbol, info),
            }
            res = mt5.order_send(req)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            log.error("%s #%d — zárás SIKERTELEN: retcode=%s %s", p.symbol, ticket,
                      getattr(res, "retcode", "—"),
                      res.comment if res else mt5.last_error())
            return False
        return True
    except Exception as e:
        log.error("#%d — zárás kivétel: %s", ticket, e)
        return False


def close_position_partial(ticket: int, volume: float) -> bool:
    """Egy pozíció RÉSZLEGES piaci zárása `volume` lot mennyiséggel (Felező/Pajzs
    kockázatcsökkentés). Biztonság: a `volume` lot_step-re illesztve (lefelé), és
    úgy, hogy a lezárt rész ÉS a maradék runner is ≥ volume_min maradjon. Ha a
    mennyiség érvénytelen (0, > pozíció, vagy a runner min_lot alá menne) → False,
    NEM zár."""
    try:
        import math
        with MT5_LOCK:
            pos = mt5.positions_get(ticket=ticket)
            if not pos:
                return False
            p = pos[0]
            info = mt5.symbol_info(p.symbol)
            tick = mt5.symbol_info_tick(p.symbol)
            if info is None or tick is None:
                return False
            step = info.volume_step or 0.01
            vmin = info.volume_min or 0.01
            vol = math.floor(round(volume / step, 9)) * step   # step-re, lefelé
            vol = round(vol, 8)
            if vol < vmin - 1e-9 or vol > p.volume - vmin + 1e-9:
                return False   # a lezárt rész vagy a runner min_lot alá menne
            close_type = mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY
            price = tick.bid if p.type == 0 else tick.ask
            # A RÉSZLEGES zárás IOC-t igényel (a FOK a rész-mennyiséget elutasítja),
            # de csak akkor, ha a szimbólum engedi — ezt az order_exec dönti el.
            req = {
                "action":       mt5.TRADE_ACTION_DEAL,
                "symbol":       p.symbol,
                "volume":       vol,
                "type":         close_type,
                "position":     ticket,
                "price":        price,
                "deviation":    order_exec.deviation_points(p.symbol, None, info),
                "magic":        p.magic,
                "comment":      "rr_partial",
                "type_time":    mt5.ORDER_TIME_GTC,
                "type_filling": order_exec.filling_mode(p.symbol, info),
            }
            res = mt5.order_send(req)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            log.error("%s #%d — RÉSZLEGES zárás (%.2f lot) SIKERTELEN: retcode=%s %s",
                      p.symbol, ticket, vol, getattr(res, "retcode", "—"),
                      res.comment if res else mt5.last_error())
            return False
        return True
    except Exception as e:
        log.error("#%d — részleges zárás kivétel: %s", ticket, e)
        return False


def has_partial_close(ticket: int) -> bool:
    """Volt-e már RÉSZLEGES zárás (rr_partial deal) ezen a pozíción? Restart-védelem
    a Felező/Pajzs kockázatcsökkentéshez — hogy újraindítás után NE duplázzon."""
    try:
        with MT5_LOCK:
            deals = mt5.history_deals_get(position=ticket)
        for d in deals or []:
            if (d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY)
                    and "rr_partial" in (getattr(d, "comment", "") or "")):
                return True
    except Exception:
        pass
    return False


# MEGJEGYZÉS: a korábbi `modify_position_sl` (csak SL, TP marad) INNEN TÖRÖLVE —
# egyetlen hívója sem volt. Az élő trailing/BE a `live_trader.modify_sl`-t
# használja, a ráépítés pedig az alábbi `modify_position_sltp`-t (az törli a TP-t
# is, hogy a csomag egyben fusson). Két, majdnem azonos SL-író út félrevezető volt.

def modify_position_sltp(ticket: int, new_sl: float, new_tp: float) -> bool:
    """SL ÉS TP egyidejű beállítása (new_tp=0 → a TP TÖRLÉSE). A pozícióépítés ezzel
    nullázza az összes láb TP-jét, hogy az induló láb ne zárjon önállóan a saját TP-jén
    (ami a TP nélküli adalékokat védtelenül hagyná) — a csomag EGYBEN fut, az átlagár-
    stopig / kiszállási jelig / kézi zárásig."""
    try:
        with MT5_LOCK:
            pos = mt5.positions_get(ticket=ticket)
            if not pos:
                return False
            p = pos[0]
            info = mt5.symbol_info(p.symbol)
            req = {
                "action":   mt5.TRADE_ACTION_SLTP,
                "symbol":   p.symbol,
                "position": ticket,
                "sl":       order_exec.normalize_price(new_sl, info),
                # tp=0 a TP TÖRLÉSE — azt nem szabad a rácsra igazítani.
                "tp":       order_exec.normalize_price(new_tp, info) if new_tp else 0.0,
            }
            res = mt5.order_send(req)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            log.error("%s #%d — SL/TP beállítás SIKERTELEN (sl=%s tp=%s): retcode=%s %s",
                      p.symbol, ticket, new_sl, new_tp, getattr(res, "retcode", "—"),
                      res.comment if res else mt5.last_error())
            return False
        return True
    except Exception as e:
        log.error("#%d — SL/TP beállítás kivétel: %s", ticket, e)
        return False


# A nyitó jutalék a pozíció élete alatt FIX (a nyitó deal(ek)ben) → position_id-re
# cache-eljük, hogy a GUI gyakori feasibility-ellenőrzése ne kérje le újra és újra a
# deal-history-t. (A swap ezzel szemben napról napra változik → azt sosem cache-eljük.)
_commission_cache: dict = {}


def _position_cost_ccy(p) -> float:
    """A pozíció kilépési költsége a SZÁMLA DEVIZÁJÁBAN: jutalék round-trip +
    a felhalmozott NEGATÍV swap. A pozitív swap szándékosan nem számít — az nem
    ad plusz kockázatot a záráshoz. Hiba/hiányzó adat → 0.0.

    KÖZÖS forrás: a költség-tudatos breakeven (`_breakeven_plan`) és a
    pozícióépítés csomag-stopja (`package_cost_buffer`) is EZT használja, hogy a
    két hely ne csúszhasson szét. (Egyszer már szétcsúszott: a csomag-stop a
    NYERS átlagárra került, és a csomag nettó mínuszban zárt.)"""
    try:
        # Jutalék a nyitó deal(ek)ből (cache-elve); a zárás ~ugyanannyi → round-trip ≈ ×2.
        pid = getattr(p, "identifier", None)
        if pid in _commission_cache:
            commission = _commission_cache[pid]
        else:
            commission = 0.0
            deals = mt5.history_deals_get(position=pid)
            if deals:
                commission = sum(getattr(d, "commission", 0.0) for d in deals)
            if pid is not None:
                _commission_cache[pid] = commission
        swap = getattr(p, "swap", 0.0) or 0.0
        return 2.0 * abs(commission) + max(0.0, -swap)
    except Exception:
        return 0.0


def _ccy_to_price(cost_ccy: float, volume: float, info) -> float:
    """Számla-devizás összeg → ÁR-távolság az adott (össz)volumenre. 0.0, ha nem
    számolható. A képlet a bróker tick-adataiból jön, nem a configból — élesben az
    MT5 az igazság."""
    if cost_ccy <= 0 or volume <= 0:
        return 0.0
    tick_value = getattr(info, "trade_tick_value", 0.0) or 0.0
    tick_size  = getattr(info, "trade_tick_size", 0.0) or info.point
    if tick_value > 0 and tick_size > 0:
        return cost_ccy * tick_size / (tick_value * volume)
    return 0.0


def _position_costs_price(p, info) -> float:
    """A pozíció TELJES kilépési költsége ÁR-egységben kifejezve (jutalék
    round-trip + felhalmozott negatív swap). Ennyivel kell az SL-t az entry
    FÖLÉ (BUY) / ALÁ (SELL) tolni, hogy a zárás nettó (jutalék+swap után) ne
    legyen mínusz. Ha az adat nem elérhető → 0.0 (csak a spread-puffer marad)."""
    return _ccy_to_price(_position_cost_ccy(p),
                         getattr(p, "volume", 0.0) or 0.0, info)


def package_cost_buffer(positions, info) -> float:
    """A CSOMAG (több láb) nettó null pontjához szükséges ÁR-puffer: a lábak
    összköltsége + spread-cushion. A `position_build.package_stop` `cost_buffer`
    argumentuma.

    Miért nem a lábankénti puffer ÖSSZEGE: a költséget a csomag ÖSSZVOLUMENE
    fizeti ki, ezért az összeget devizában kell összeadni, és EGYSZER átváltani az
    összvolumennel. A lábankénti ártávolságok összege nagyságrenddel túlbecsülne.

    A spread-cushion (≥1 pont) ugyanaz, mint a breakevennél: a BUY a BID-en zár,
    tehát az árrés önmagában is költség."""
    legs = list(positions or [])
    if not legs:
        return 0.0
    total_vol = sum((getattr(p, "volume", 0.0) or 0.0) for p in legs)
    cost_ccy  = sum(_position_cost_ccy(p) for p in legs)
    point        = getattr(info, "point", 0.0) or 0.0
    spread_price = (getattr(info, "spread", 0) or 0) * point
    return _ccy_to_price(cost_ccy, total_vol, info) + max(spread_price, point)


def _breakeven_plan(p, info):
    """(target_sl, feasible) — a költség-tudatos BE cél-SL és hogy a JELENLEGI árnál
    a helyes oldalra mozgatható-e (nettó ≥ 0 zárás). `feasible=False`, ha a profit még
    nem fedezi a spread+jutalék+swap költséget. Nincs order_send. HívóJA fogja a
    MT5_LOCK-ot (a _position_costs_price deal-history-t olvashat)."""
    point        = info.point
    spread_price = info.spread * point
    entry        = p.price_open
    is_buy       = (p.type == mt5.ORDER_TYPE_BUY)
    sign         = 1 if is_buy else -1
    cost_price   = _position_costs_price(p, info)
    buffer_price = cost_price + max(spread_price, point)   # költség + spread cushion (≥1 pont)
    target_sl    = order_exec.normalize_price(entry + sign * buffer_price, info)
    cur          = p.price_current
    # A bróker MINIMUM stop-távolsága: az árhoz ennél közelebbi SL-t `10016 Invalid
    # stops`-szal utasít vissza. Enélkül a BE „megvalósíthatónak" látszott, a
    # mozgatás mégis némán elbukott (és a GUI BE-gombja is engedélyezett maradt).
    gap = order_exec.min_stop_price(info)
    feasible = ((cur - target_sl) > gap) if is_buy else ((target_sl - cur) > gap)
    return target_sl, feasible


_TF_CONST = None   # perc → MT5 timeframe konstans (lazán, első híváskor töltve)


def tf_closes(symbol: str, timeframes: list, count: int) -> dict:
    """Idősíkonként (perc) az utolsó `count` ZÁRÓár, NATIVE copy_rates-ből
    (nincs resample-torzítás). {perc: [close,…]}; a nem elérhetőt kihagyja. A
    TF-együttállás figyelő (dashboard + élő kapu) ezt használja."""
    global _TF_CONST
    if _TF_CONST is None:
        _TF_CONST = {1: mt5.TIMEFRAME_M1, 5: mt5.TIMEFRAME_M5, 15: mt5.TIMEFRAME_M15,
                     30: mt5.TIMEFRAME_M30, 60: mt5.TIMEFRAME_H1, 240: mt5.TIMEFRAME_H4}
    out: dict = {}
    try:
        with MT5_LOCK:
            for tf in timeframes:
                const = _TF_CONST.get(int(tf))
                if const is None:
                    continue
                r = mt5.copy_rates_from_pos(symbol, const, 0, int(count))
                if r is not None and len(r):
                    out[int(tf)] = [float(x["close"]) for x in r]
    except Exception:
        return out
    return out


def breakeven_reached(ticket: int) -> bool:
    """A pozíció JELENLEGI SL-je már eléri-e (vagy túllépi) a költség-tudatos BE
    szintet a PROFIT oldalon — függetlenül attól, KI mozgatta (a motor VAGY a
    felhasználó kézzel, a charton). Így a kézi SL-húzás is „BE kész"-nek számít, ha
    valóban fedezi a spread+jutalék+swap költséget. A naiv (költséget nem fedező,
    de az entryt épp túllépő) BE-t SZÁNDÉKOSAN nem fogadja el — a modell végig
    költség-tudatos. Nincs order_send."""
    try:
        with MT5_LOCK:
            pos = mt5.positions_get(ticket=ticket)
            if not pos or not pos[0].sl:
                return False
            p = pos[0]
            info = mt5.symbol_info(p.symbol)
            if info is None:
                return False
            target_sl, _ = _breakeven_plan(p, info)
            tol = info.point or 1e-9
            # Profit oldal: BUY → az SL a cél FÖLÖTT/egyenlő; SELL → ALATT/egyenlő.
            return ((p.sl >= target_sl - tol) if p.type == mt5.ORDER_TYPE_BUY
                    else (p.sl <= target_sl + tol))
    except Exception:
        return False


def breakeven_feasible(ticket: int) -> bool:
    """Mozgatható-e MOST a pozíció a költség-tudatos breakevenre (a profit fedezi a
    spread+jutalék+swap költséget)? A GUI ez alapján TILTJA/engedélyezi a kézi BE
    gombot — így nem lehet némán „a semmibe" nyomkodni. Nincs order_send.
    Pontosan azt a feltételt adja, amit a `move_to_breakeven` is használ."""
    try:
        with MT5_LOCK:
            pos = mt5.positions_get(ticket=ticket)
            if not pos:
                return False
            info = mt5.symbol_info(pos[0].symbol)
            if info is None:
                return False
            _, feasible = _breakeven_plan(pos[0], info)
            return bool(feasible)
    except Exception:
        return False


def move_to_breakeven(ticket: int) -> bool:
    """SL áthelyezése VALÓDI (költség-tudatos) breakeven + spread-puffer szintre.

    A puffer = spread + a kilépési költség (jutalék round-trip + negatív swap),
    ÁR-egységre átszámolva. Így a zárás nettó (jutalék/swap után) is ≥ 0, nem
    csak ár-szinten. BUY: SL = entry + puffer | SELL: SL = entry − puffer.

    KRITIKUS: ha az ár még nincs elég messze ahhoz, hogy ezt az SL-t a helyes
    oldalra (BUY: az aktuális ár alá / SELL: fölé) tegyük, akkor NEM mozgatunk és
    False-t adunk vissza — így sosem rögzítünk veszteséget és a slot sem szabadul
    fel idő előtt. (A régi „pontos entry" fallback ezt a veszteséget okozta.)
    Ugyanezt hívja a kézi BE gomb és az automatikus BE — azonos viselkedés.
    """
    try:
        with MT5_LOCK:
            pos = mt5.positions_get(ticket=ticket)
            if not pos:
                return False
            p = pos[0]
            info = mt5.symbol_info(p.symbol)
            if info is None:
                return False
            # Költség-tudatos cél-SL + feasibility (közös a kézi-gomb tiltásával).
            # Csak a HELYES oldalon mozgatunk (különben veszteséget rögzítenénk /
            # a bróker elutasítja): BUY → target < aktuális ár; SELL → target > ár.
            target_sl, feasible = _breakeven_plan(p, info)
            if not feasible:
                return False

            req = {
                "action":   mt5.TRADE_ACTION_SLTP,
                "symbol":   p.symbol,
                "position": ticket,
                "sl":       target_sl,
                "tp":       p.tp,
            }
            res = mt5.order_send(req)
            return res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
    except Exception:
        return False


def is_connected() -> bool:
    try:
        with MT5_LOCK:
            info = mt5.account_info()
        return info is not None
    except Exception:
        return False


# A legutóbb mért szerver-eltolás. A `server_offset_sec` frissíti, a nap-határt
# számoló `server_day_bounds` pedig ebből dolgozik — így a napi limit akkor is a
# BRÓKER napjához igazodik, ha épp nincs friss tick (pl. hétvégén).
_server_offset = {"v": None}


def server_offset_sec(symbols) -> Optional[float]:
    """A bróker/szerver-idő eltolása a valós UTC-hez képest, MÁSODPERCben.

    A megadott szimbólumok LEGFRISSEBB tickjéből (a bróker faliórája epoch-ként).
    EHHEZ igazodik az óra-kapu (trade_hours), a chart és a no-trade szürke sáv —
    ezért a felületen a BRÓKER-időt ebből számoljuk. None, ha nincs elérhető tick
    (pl. nincs kapcsolat). Zárt piacon a legutóbbi tick alapján közelít.

    A mért értéket eltesszük (`_server_offset`), hogy a nap-határ számítása is
    elérje — az a kereskedési nap definíciója a napi veszteséglimithez."""
    try:
        latest = None
        with MT5_LOCK:
            for sym in symbols:
                tick = mt5.symbol_info_tick(sym)
                if tick and tick.time and (latest is None or tick.time > latest):
                    latest = int(tick.time)
        if latest is not None:
            from datetime import datetime, timezone
            off = float(latest - datetime.now(timezone.utc).timestamp())
            _server_offset["v"] = off
            return off
    except Exception:
        pass
    return None


def server_day_bounds():
    """A MAI kereskedési nap határai a bróker naptára szerint: `(tól, ig)` — olyan
    datetime-ok, amiket a `history_deals_get` közvetlenül megkap.

    MIÉRT NEM `date.today()`: az a GÉP HELYI dátuma volt, `.replace(tzinfo=utc)`-val
    UTC-nek CÍMKÉZVE. A kettő nem ugyanaz, és a különbség a napi veszteséglimitet
    érinti: a helyi éjfél (nyáron 22:00 UTC) után a lekérdezés egy MÉG EL SEM KEZDŐDÖTT
    napra mutatott → a `daily_pnl` 0.0-t adott, azaz **a napi limit órákkal korábban
    lenullázódott**, és a 22:00–24:00 UTC közti veszteség nem számított bele.

    Az MT5 deal-időbélyegei a BRÓKER faliórájában értendők (a felület „Lezárt ma
    (MT5 szerver-idő)" felirata is ezt ígéri — eddig nem ez teljesült). Ezért a
    határt a szerver-eltolással számoljuk. Ha az eltolás ismeretlen (nincs még
    tick), a valós UTC-napra esünk vissza — az is helyesebb a helyi dátumnál."""
    from datetime import datetime, timedelta, timezone
    off = _server_offset["v"] or 0.0
    now_srv = datetime.now(timezone.utc).timestamp() + off      # a bróker faliórája
    day_start = (now_srv // 86400) * 86400                      # szerver-éjfél
    return (datetime.fromtimestamp(day_start, tz=timezone.utc),
            datetime.fromtimestamp(day_start + 86400, tz=timezone.utc))


def connection_info(cfg: dict) -> dict:
    """
    Visszaadja a kapcsolat állapotát és a számla adatait.
    Demo módban (MT5 nem elérhető) a config-ból tölt.
    """
    try:
        with MT5_LOCK:
            info = mt5.account_info()
        if info is not None:
            return {
                "connected": True,
                "login":     info.login,
                "server":    info.server,
                "name":      info.name,
                "balance":   info.balance,
                "currency":  info.currency,
                "is_demo":   info.trade_mode == 0,
                "margin_mode":      margin_mode(),
                "margin_mode_name": margin_mode_name(),
                "is_netting":       is_netting(),
            }
    except Exception:
        pass

    broker = cfg.get("broker", {})
    return {
        "connected": False,
        "login":     broker.get("login", "—"),
        "server":    broker.get("server", "—"),
        "name":      "—",
        "balance":   0.0,
        "currency":  "—",
        "is_demo":   broker.get("is_demo", True),
        "margin_mode":      None,
        "margin_mode_name": "—",
        "is_netting":       False,
    }

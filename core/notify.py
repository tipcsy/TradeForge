"""ÉRTESÍTÉS-KIMENET (Telegram) — hálózat-mentes SEAM.

⚠ MIÉRT KÜLÖN MODUL, ÉS MIÉRT NEM A MOTORBAN. Az értesítés **sosem
állíthatja meg a kereskedést**. Ha a Telegram lassú, elérhetetlen vagy
korlátoz, az a motor körét nem érintheti — ezért minden esemény egy SORBA
kerül, és egy külön szál küldi. A hívó oldalon a `trade_event()` mindig azonnal
visszatér, kivételt nem enged ki.

⚠ ÉS MIÉRT EGY BEKÖTÉSI PONT. A kötés, a zárás és a jelzés MÁR MA is egy közös
csatornán megy a naplóba (`live_trader.log_trade`), ugyanabból a rekordból.
Az értesítés is onnan dolgozik: így a Telegram-üzenet és a `trades.csv`
**nem tud elcsúszni egymástól** — ez a projekt visszatérő hibaosztálya (két
forrás, ami külön romlik).

── AMIT A FELHASZNÁLÓ ELDÖNTÖTT (2026-08-31) ───────────────────────────────
* **Két kapcsoló pár+stratégia szinten** (`core.viz_prefs` NOTIFY_* tengelyei):
  a JELZÉS-értesítés alapból KI (abból sok van), a KÖTÉS-értesítés alapból BE.
* **Csendes órák HELYI idő szerint** — „az ember nem szerver-időben alszik".
  A csendben keletkező JELZÉSEK **elvesznek** (alvás közben úgysem lépnél be),
  a KÖTÉSEK viszont reggel **összesítve** megjönnek.
* **Négy kritikus esemény PUSH-ként**, naponta legfeljebb egyszer: a motor
  szála elhalt · MT5-kapcsolat elveszett · napi veszteséglimit elérve · a
  licenc N napon belül lejár. Minden más a `/state` alatt marad.
  ⚠ Ezt eredetileg a felhasználó is a `/state`-hez kötötte volna; a néma
  szál-halál (11 pár állt le, a napló hallgatott) viszont épp arról szól, hogy
  **nem jut eszedbe megkérdezni** — nincs miért.
* **Életjel** a `config.json`-ban megadott időpontokban (üres lista = nincs).
  ⚠ Ez a valódi halál-érzékelő: egy halott program a `/heart`-ra sem válaszol,
  tehát a hallgatás és a „minden rendben" különben megkülönböztethetetlen.

⚠ A MODUL HÁLÓZAT NÉLKÜL TESZTELHETŐ: a küldés egy cserélhető `transport`
függvény, az idő pedig egy cserélhető óra. A `core.telegram` csak akkor kerül
be, ha tényleg küldeni kell.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime

from core import viz_prefs
from core.i18n import t as _t

log = logging.getLogger(__name__)

# ── Esemény-fajták ────────────────────────────────────────────────────────
OPEN      = "open"        # valódi kötés nyílt
CLOSE     = "close"       # pozíció lezárult (SL/TP/kézi/kiszállás)
SIGNAL    = "signal"      # jelzés — „csak jelzés" módban nincs kötés
SL_MOVE   = "sl_move"     # a stop elmozdult (breakeven, trailing)
ERROR     = "error"       # a NÉGY kritikus esemény
HEARTBEAT = "heartbeat"   # ütemezett életjel
DAILY     = "daily"       # napi zárás-összefoglaló

# ⚠ A KÖTÉS-tengelyhez tartozó fajták (a másik a SIGNAL). A számla-szintű
# események (hiba, életjel, napi összefoglaló) EGYIK pár-kapcsolóhoz sem
# tartoznak — azokat nem lehet egy instrumentummal elnémítani.
_TRADE_KINDS = (OPEN, CLOSE, SL_MOVE)
_PAIR_KINDS = _TRADE_KINDS + (SIGNAL,)

# Percenként ennyi üzenetnél többet nem küldünk; a fölötte lévők EGY
# összevont sorban mennek. ⚠ Nem a Telegram korlátja a lényeg, hanem hogy egy
# zajos nap ne tegye olvashatatlanná a beszélgetést.
PERC_LIMIT = 12


@dataclass
class Event:
    kind: str
    text: str
    symbol: str = ""
    strategy: str = ""
    # Dedup-kulcs: azonos kulcsú esemény NAPONTA egyszer megy ki (a négy
    # kritikus hibánál ez a lényeg). Üres → nincs dedup.
    key: str = ""


@dataclass
class Config:
    """A `config.json` → `notify` szekció kiolvasott alakja."""
    enabled: bool = False
    token: str = ""
    chat_ids: tuple = ()
    quiet_from: str = ""            # "22:00" — HELYI idő
    quiet_to: str = ""              # "07:00"
    heartbeat_times: tuple = ()     # ("08:00", "12:00", "15:00")
    daily_time: str = ""            # "23:00" — a napi összefoglaló ideje

    @property
    def kesz(self) -> bool:
        """Van-e mivel küldeni. ⚠ Token vagy címzett nélkül az `enabled` önmagában
        nem elég — különben minden esemény némán a semmibe menne."""
        return bool(self.enabled and self.token and self.chat_ids)


def read_config(cfg: dict) -> Config:
    n = (cfg or {}).get("notify") or {}
    tg = n.get("telegram") or {}
    csend = n.get("quiet_hours") or {}
    _ids = tg.get("chat_ids") or []
    if isinstance(_ids, (str, int)):
        _ids = [_ids]
    return Config(
        enabled=bool(n.get("enabled", False)),
        token=str(tg.get("token") or ""),
        chat_ids=tuple(str(x) for x in _ids if str(x).strip()),
        quiet_from=str(csend.get("from") or ""),
        quiet_to=str(csend.get("to") or ""),
        heartbeat_times=tuple(str(x) for x in (n.get("heartbeat_times") or [])),
        daily_time=str(n.get("daily_summary_time") or ""),
    )


# ── Idő-segédek ───────────────────────────────────────────────────────────

def _perc(hhmm: str) -> "int | None":
    """"22:00" → 1320. Hibás értéknél `None` (és NEM kivétel: egy elgépelt
    időpont miatt ne álljon meg az értesítés)."""
    try:
        h, m = str(hhmm).strip().split(":")
        h, m = int(h), int(m)
        if 0 <= h < 24 and 0 <= m < 60:
            return h * 60 + m
    except (ValueError, AttributeError):
        pass
    return None


def csendben(cfg: Config, most: "datetime | None" = None) -> bool:
    """Csendes órában vagyunk-e? ⚠ HELYI idő szerint — a felhasználó döntése:
    „az ember nem szerver-időben alszik"."""
    a, b = _perc(cfg.quiet_from), _perc(cfg.quiet_to)
    if a is None or b is None or a == b:
        return False
    most = most or datetime.now()
    p = most.hour * 60 + most.minute
    # ⚠ ÁTNYÚLÓ INTERVALLUM (22:00–07:00): a nap végén ÉS az elején is csend van.
    return (a <= p < b) if a < b else (p >= a or p < b)


# ── A küldő ───────────────────────────────────────────────────────────────

class Notifier:
    """Sorba állít, szűr, és egy külön szálon küld.

    ⚠ Az `óra` és a `transport` cserélhető — így a teljes viselkedés
    (csendes órák, dedup, összevonás, életjel) hálózat és várakozás nélkül
    lejátszható tesztben."""

    def __init__(self, cfg: Config, transport=None, ora=None, health=None):
        self.cfg = cfg
        self.transport = transport
        self.ora = ora or time.time
        # ⚠ AZ ÁLLAPOT-FIGYELŐ NEM A MOTORÉ. Egy elhalt szál nem tud üzenni
        # magáról — ezért a NÉGY kritikus eseményt ez a (külön) szál kérdezi
        # meg periodikusan. A `health()` `[(kulcs, szöveg), …]` listát ad: ami
        # benne van, az BAJ. A motort nem ismerjük, a hívó köti be.
        self.health = health
        self._q: "queue.Queue" = queue.Queue(maxsize=500)
        self._szal = None
        self._leall = threading.Event()
        self._elkuldve: dict = {}        # dedup-kulcs → melyik NAPON ment ki
        self._perc_ablak: list = []      # a legutóbbi küldések időbélyegei
        self._halasztott: list = []      # csendes órában keletkezett KÖTÉSEK
        self._utolso_heartbeat = ""      # "2026-08-31 08:00" — ne menjen kétszer
        self._utolso_daily = ""
        self._utolso_ellenorzes = 0.0
        self._csend_volt = False
        self.kuldve = 0
        self.eldobva = 0

    # ── A hívó felülete ───────────────────────────────────────────────
    def start(self) -> None:
        if self._szal is not None:
            return
        self._szal = threading.Thread(target=self._munka, daemon=True,
                                      name="TradeForgeNotify")
        self._szal.start()

    def stop(self) -> None:
        self._leall.set()

    def push(self, ev: Event) -> bool:
        """Esemény a sorba. ⚠ SOSEM DOB és sosem vár: a motor köre nem
        függhet az értesítéstől. Tele sornál eldobunk — és naplózzuk."""
        try:
            self._q.put_nowait(ev)
            return True
        except queue.Full:
            self.eldobva += 1
            log.warning("értesítés: a sor tele van, az esemény eldobva (%s/%s)",
                        ev.kind, ev.symbol)
            return False

    # ── A szűrés (tiszta döntés, tesztelhető) ─────────────────────────
    def kimehet(self, ev: Event, cfg_json: dict,
                most: "datetime | None" = None) -> tuple:
        """`(kimehet_e, ok)`. Az `ok` a naplóé és a teszté."""
        if not self.cfg.kesz:
            return False, "nincs beállítva"
        most = most or datetime.fromtimestamp(self.ora())
        # 1. Pár + stratégia kapcsoló
        if ev.kind in _PAIR_KINDS and ev.symbol and ev.strategy:
            be = (viz_prefs.notify_signal_on if ev.kind == SIGNAL
                  else viz_prefs.notify_trade_on)(cfg_json, ev.symbol, ev.strategy)
            if not be:
                return False, "a pár/stratégia némítva"
        # 2. Csendes órák
        if csendben(self.cfg, most):
            if ev.kind == SIGNAL:
                # ⚠ A felhasználó döntése: a csendben keletkezett JELZÉS
                # ELVESZIK. Reggel egy lejárt ajánlat csak bosszúság volna.
                return False, "csendes óra (a jelzés elvész)"
            if ev.kind in _TRADE_KINDS:
                # ⚠ NEM VESZIK EL: reggel, a csend végén EGY összesítőben jön.
                # (A jelzés viszont igen — arra reggel már úgysem lépnél be.)
                if len(self._halasztott) < 200:
                    self._halasztott.append(ev.text)
                return False, "csendes óra (reggel összesítve)"
            if ev.kind in (HEARTBEAT, DAILY):
                return False, "csendes óra"
            # ⚠ A HIBA a csendet is átüti: ha a motor éjjel elhalt, azt reggel
            # tudni kell, nem holnapután.
        # 3. Napi dedup (a négy kritikus hiba)
        if ev.key:
            nap = most.strftime("%Y-%m-%d")
            if self._elkuldve.get(ev.key) == nap:
                return False, "ma már ment ilyen"
        return True, ""

    # ── A szál ────────────────────────────────────────────────────────
    ELLENORZES_MP = 30.0

    def _munka(self) -> None:
        while not self._leall.is_set():
            try:
                ev = self._q.get(timeout=1.0)
            except queue.Empty:
                self._idozitett()
                continue
            try:
                self._idozitett()
                self._kuld(ev)
            except Exception:
                # ⚠ Egy küldési hiba NEM viheti el a szálat: onnantól néma
                # lenne minden értesítés — épp az a hibaosztály, ami ellen ez
                # az egész készült.
                log.warning("értesítés: a küldés hibára futott", exc_info=True)

    def _idozitett(self) -> None:
        """Ami nem eseményre, hanem IDŐRE történik: állapot-figyelés, életjel,
        és a csendes óra végén a halasztott kötések összesítése."""
        _most = self.ora()
        if _most - self._utolso_ellenorzes < self.ELLENORZES_MP:
            return
        self._utolso_ellenorzes = _most
        now = datetime.fromtimestamp(_most)

        # ── A csendes óra VÉGE: ami éjjel történt, most jön meg összesítve ──
        _csend = csendben(self.cfg, now)
        if self._csend_volt and not _csend and self._halasztott:
            # ⚠ ÖSSZESÍTVE, nem egyesével: reggel nem húsz külön üzenetet akarsz.
            sorok = list(self._halasztott)
            self._halasztott.clear()
            self._kuld(Event(kind=DAILY,
                             text=_t("notify.night", n=len(sorok))
                                  + chr(10) + chr(10).join(sorok)))
        self._csend_volt = _csend

        # ── A NÉGY kritikus esemény ────────────────────────────────────────
        if callable(self.health):
            try:
                for kulcs, szoveg in (self.health() or ()):
                    ev = Event(kind=ERROR, text=szoveg, key=str(kulcs))
                    ok, _ = self.kimehet(ev, _cfg_json, now)
                    if ok:
                        self._kuld(ev)
            except Exception:
                log.debug("értesítés: az állapot-figyelő hibára futott",
                          exc_info=True)

        # ── Ütemezett életjel ──────────────────────────────────────────────
        # ⚠ EZ A VALÓDI HALÁL-ÉRZÉKELŐ: egy halott program a `/heart`-ra sem
        # válaszol, tehát a hallgatás és a „minden rendben" különben
        # megkülönböztethetetlen. Ha reggel nem jött meg, baj van.
        for hhmm in self.cfg.heartbeat_times:
            p = _perc(hhmm)
            if p is None:
                continue
            jel = now.strftime("%Y-%m-%d ") + hhmm
            # A megadott perctől számítva egy ÖTPERCES ablakban tüzel egyszer
            # (a szál 30 mp-enként néz oda, tehát pontos időpontra nem lehet
            # építeni; egy leállás-újraindulás se hagyja ki).
            _p_most = now.hour * 60 + now.minute
            if p <= _p_most < p + 5 and self._utolso_heartbeat != jel:
                self._utolso_heartbeat = jel
                ev = Event(kind=HEARTBEAT, text=self._eletjel_szoveg())
                ok, _ = self.kimehet(ev, _cfg_json, now)
                if ok:
                    self._kuld(ev)

    def _eletjel_szoveg(self) -> str:
        """Az életjel szövege. ⚠ Ha van állapot-figyelő, a BAJT is beleírjuk —
        egy „minden rendben", ami nem néz semmit, rosszabb a semminél."""
        gond = []
        if callable(self.health):
            try:
                gond = [sz for _k, sz in (self.health() or ())]
            except Exception:
                gond = []
        if gond:
            return _t("notify.heartbeat_bad") + chr(10) + chr(10).join(gond)
        return _t("notify.heartbeat_ok")

    def _kuld(self, ev: Event) -> bool:
        # Perc-limit: a fölösleget összevonjuk, nem küldjük egyesével.
        _most = self.ora()
        self._perc_ablak = [t for t in self._perc_ablak if _most - t < 60]
        if len(self._perc_ablak) >= PERC_LIMIT:
            self.eldobva += 1
            return False
        ok = bool(self.transport and self.transport(ev.text))
        if ok:
            self.kuldve += 1
            self._perc_ablak.append(_most)
            if ev.key:
                self._elkuldve[ev.key] = datetime.fromtimestamp(
                    _most).strftime("%Y-%m-%d")
        return ok


# ── Modul-szintű egyke (a motor ezt hívja) ────────────────────────────────
_aktiv: "Notifier | None" = None
_cfg_json: dict = {}


def setup(cfg: dict, health=None) -> "Notifier | None":
    """Az értesítés bekapcsolása a `config.json` alapján. `None`, ha nincs
    beállítva — a hívó ilyenkor sem kap hibát, csak nem megy üzenet."""
    global _aktiv, _cfg_json
    _cfg_json = cfg or {}
    c = read_config(cfg)
    if not c.kesz:
        log.info("értesítés: nincs beállítva (notify.enabled / token / chat_ids)")
        _aktiv = None
        return None
    from core import telegram
    _aktiv = Notifier(c, transport=lambda szoveg: telegram.send(
        c.token, c.chat_ids, szoveg), health=health)
    _aktiv.start()
    log.info("értesítés: BEKAPCSOLVA (%d címzett)", len(c.chat_ids))
    return _aktiv


def active() -> "Notifier | None":
    return _aktiv


def _kuld(ev: Event) -> bool:
    n = _aktiv
    if n is None:
        return False
    ok, _ok_szoveg = n.kimehet(ev, _cfg_json)
    if not ok:
        return False
    return n.push(ev)


# ── A motor bekötési pontjai ──────────────────────────────────────────────

def trade_event(row: dict) -> bool:
    """A `live_trader.log_trade` rekordjából. EGY bekötési pont a kötésre, a
    zárásra és a jelzésre — ugyanabból az adatból, amit a `trades.csv` őriz."""
    try:
        kind = str(row.get("event") or "")
        if kind not in (OPEN, CLOSE, SIGNAL):
            return False
        sym = str(row.get("symbol") or "")
        strat = str(row.get("strategy") or "")
        if kind == CLOSE:
            _p = row.get("pnl_usd")
            szoveg = _t("notify.close", symbol=sym, strategy=strat,
                        ticket=row.get("ticket"),
                        pnl=("?" if _p is None else f"{float(_p):+.2f}"))
        else:
            szoveg = _t("notify.open" if kind == OPEN else "notify.signal",
                        symbol=sym, strategy=strat,
                        dir=str(row.get("direction") or ""),
                        lot=row.get("lot"), price=_szam(row.get("price")),
                        sl=_szam(row.get("sl")), tp=_szam(row.get("tp")))
        return _kuld(Event(kind=kind, text=szoveg, symbol=sym, strategy=strat))
    except Exception:
        # ⚠ Az értesítés SOHA nem viheti el a napló-írást, ami hívja.
        log.debug("értesítés: a kereskedési esemény kihagyva", exc_info=True)
        return False


def sl_moved(symbol: str, strategy: str, ticket: int, sl: float,
             breakeven: bool = False) -> bool:
    """Elmozdult a stop (breakeven vagy trailing)."""
    return _kuld(Event(
        kind=SL_MOVE, symbol=symbol, strategy=strategy,
        text=_t("notify.be" if breakeven else "notify.sl_move",
                symbol=symbol, ticket=int(ticket), sl=_szam(sl))))


def signal_offer(ajanlat) -> bool:
    """JÓVÁHAGYÁSRA VÁRÓ belépő — gombokkal.

    ⚠ MIÉRT KÜLÖN ÚT a sima jelzés-értesítéstől: ez nem hír, hanem KÉRDÉS, és
    a válasza pozíciót nyit. Ezért a `NOTIFY_SIGNAL` kapcsolótól FÜGGETLENÜL
    kimegy — aki bekapcsolta a válaszos kötést, az épp azért tette, hogy
    megkérdezzük. (A csendes óra viszont itt is érvényes: egy reggel meglátott
    ajánlat addigra amúgy is lejárt volna.)"""
    n = _aktiv
    if n is None:
        return False
    ev = Event(kind=SIGNAL, text="", symbol=getattr(ajanlat, "symbol", ""),
               strategy=getattr(ajanlat, "strategy", ""))
    # A csendes órát és a `kesz` állapotot ugyanazzal a szabállyal nézzük — de a
    # pár-kapcsolót NEM (lásd fent), ezért a szimbólumot kiürítjük hozzá.
    _proba = Event(kind=SIGNAL, text="")
    ok, _ok_szoveg = n.kimehet(_proba, _cfg_json)
    if not ok:
        log.info("jelzés-ajánlat NEM ment ki (%s): %s", ev.symbol, _ok_szoveg)
        return False
    try:
        from core import telegram
        _perc = max(1, int((ajanlat.expires - ajanlat.created) // 60))
        # ⚠ A SZINTEKET AZ AJÁNLAT SZÁMOLJA (`celok`) — ugyanaz a képlet, amivel
        # a kötés is készül. Külön kiszámolva az üzenet MÁS SL-t mutathatna,
        # mint ami a pozícióra kerül.
        _sl, _tp = ajanlat.celok(ajanlat.entry)
        szoveg = _t("tg.offer.title", symbol=ajanlat.symbol,
                    strategy=ajanlat.strategy, dir=ajanlat.direction,
                    lot=f"{ajanlat.lot:.2f}", price=ajanlat.fmt(ajanlat.entry),
                    sl=ajanlat.fmt(_sl), tp=ajanlat.fmt(_tp), minutes=_perc)
        gombok = ((_t("tg.btn.yes"), f"a:{ajanlat.id}"),
                  (_t("tg.btn.no"), f"x:{ajanlat.id}"))
        for cid in n.cfg.chat_ids:
            telegram.send_buttons(n.cfg.token, cid, szoveg, gombok)
        return True
    except Exception:
        log.warning("jelzés-ajánlat: a küldés hibára futott", exc_info=True)
        return False


def error(key: str, text: str) -> bool:
    """A NÉGY kritikus esemény egyike. `key` → naponta legfeljebb egyszer.

    ⚠ Ez az egyetlen fajta, ami a CSENDES ÓRÁT is átüti: ha a motor éjjel
    elhalt, azt reggel tudni kell, nem holnapután."""
    return _kuld(Event(kind=ERROR, text=text, key=str(key)))


def _szam(v) -> str:
    try:
        return f"{float(v):.5g}"
    except (TypeError, ValueError):
        return "-"

"""BRÓKER-PROFIL + ADAPTER — a második bróker fordítása, és a mai viselkedés BITRE.

⚠ MIT ŐRZÜNK (0029 „Több bróker egyszerre", 2. lépés, 2026-09-28):
  1. IDENTITÁS: a mai config (nincs `brokers` lista) EGY profilt ad a régi
     `broker` + `mt5` blokk értékeivel, és az adapter minden hívásnál
     UGYANAZT AZ OBJEKTUMOT adja vissza, amit a nyers csomag. Ha ez eltörne,
     az élő motor minden gyertyája/pozíciója egy átalakításon menne át.
  2. FORDÍTÁS: egy NY-zárásos (NY+7), `GOLD`→`XAUUSD` aliasú brókernél
     befelé a bróker neve és szerver-órája megy, kifelé a kanonikus név és
     óra jön — gyertyán, tickon, pozíción, deal-en, lekérdezési határon, és a
     `group="*GOLD*"` mintán is (a live_trader így kérdez).
  3. A PROFIL-LISTA ŐREI: legfeljebb 5 bróker, egyedi azonosító/címke/számla,
     érvényes zóna, létező aktív bróker.
"""
import sys
import datetime as dt
from collections import namedtuple
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                                  # noqa: E402
applog.harden_console()

import numpy as np                                                       # noqa: E402

from core import broker_adapter as A                                     # noqa: E402
from core import broker_profile as P                                     # noqa: E402

_results, _fail = [], []


def check(name, ok, detail=""):
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


def _tipus(nev, mezok):
    """Az MT5 eredmény-típusai EGY tuple-t kapnak a konstruktorban."""
    alap = namedtuple(nev, mezok)

    class T(alap):
        def __new__(cls, t):
            return super().__new__(cls, *t)
    T.__name__ = nev
    return T


Tick = _tipus("Tick", "time bid ask time_msc")
Pos = _tipus("TradePosition", "ticket symbol time time_msc time_update volume")
Deal = _tipus("TradeDeal", "ticket symbol time time_msc profit")
Info = _tipus("SymbolInfo", "name point digits")


def ep(y, m, d, h=0, mi=0):
    return int((dt.datetime(y, m, d, h, mi) - dt.datetime(1970, 1, 1)).total_seconds())


class NyersMT5:
    """A MetaTrader5 csomag hamisítványa: rögzíti, mit kapott, és ÁLLANDÓ
    objektumokat ad vissza (az identitás-teszt az `is`-t nézi)."""
    TIMEFRAME_M1 = 1
    ORDER_TYPE_BUY = 0

    def __init__(self):
        self.hivasok = []
        t_szerver = ep(2026, 1, 12, 0, 0)               # hétfő 00:00 szerver (tél)
        self.tick = Tick((t_szerver, 1.0, 1.1, t_szerver * 1000 + 250))
        self.info = Info(("XAUUSD", 0.01, 2))
        self.rates = np.array([(ep(2026, 1, 12), 1.0), (ep(2026, 6, 15), 2.0),
                               (ep(2026, 3, 16), 3.0)],
                              dtype=[("time", "<i8"), ("close", "<f8")])
        self.pos = (Pos((7, "XAUUSD", ep(2026, 3, 16), ep(2026, 3, 16) * 1000, 0, 0.1)),)
        self.deals = (Deal((9, "XAUUSD", ep(2026, 6, 15), ep(2026, 6, 15) * 1000, 5.0)),)

    def _h(self, nev, *a, **kw):
        self.hivasok.append((nev, a, kw))

    def symbol_info(self, s):            self._h("symbol_info", s); return self.info
    def symbol_info_tick(self, s):       self._h("symbol_info_tick", s); return self.tick
    def symbol_select(self, s, e=True):  self._h("symbol_select", s); return True
    def copy_rates_from_pos(self, s, tf, st, n):
        self._h("copy_rates_from_pos", s); return self.rates
    def copy_rates_range(self, s, tf, a, b):
        self._h("copy_rates_range", s, a, b); return self.rates
    def positions_get(self, **kw):       self._h("positions_get", **kw); return self.pos
    def history_deals_get(self, *a, **kw):
        self._h("history_deals_get", *a, **kw); return self.deals
    def order_send(self, req):           self._h("order_send", req); return "OK"
    def order_calc_margin(self, act, s, v, p):
        self._h("order_calc_margin", s); return 12.5


nyers = NyersMT5()
A._raw = lambda: nyers                   # a teszt a csomag helyére a hamisítványt teszi

# ---------------------------------------------------------------------------
print("== A mai config: EGY profil a regi broker + mt5 blokkbol ==")
REGI = {"broker": {"name": "ActivTrades", "server": "ActivTradesEU-Server",
                   "login": 6264021, "password": "x", "is_demo": True, "magic": 20260627},
        "mt5": {"path": "c:/mt5/terminal64.exe", "portable": True}}
ps = P.profiles(REGI)
p0 = P.active(REGI)
check("egy profil", len(ps) == 1)
check("ugyanazok az ertekek (login, szerver, magic, jelszo)",
      (p0.login, p0.server, p0.magic, p0.password)
      == (6264021, "ActivTradesEU-Server", 20260627, "x"))
check("a terminal a regi mt5 blokkbol", p0.mt5 == REGI["mt5"])
check("rovid cimke alapbol: 'Act'", p0.tag == "Act", p0.tag)
check("IDENTITAS (kanonikus ora, nincs alias)", p0.is_identity)
check("a regi confignak nincs profil-hibaja", P.validate(REGI) == [], P.validate(REGI))

print("\n== IDENTITAS: az adapter UGYANAZT AZ OBJEKTUMOT adja ==")
for profil, cim in ((None, "nincs profil"), (p0, "a mai profil")):
    A.configure(profil)
    check(f"{cim}: symbol_info", A.mt5.symbol_info("GOLD") is nyers.info)
    check(f"{cim}: symbol_info_tick", A.mt5.symbol_info_tick("GOLD") is nyers.tick)
    check(f"{cim}: copy_rates_from_pos", A.mt5.copy_rates_from_pos("GOLD", 1, 0, 3) is nyers.rates)
    check(f"{cim}: positions_get", A.mt5.positions_get(symbol="GOLD") is nyers.pos)
    check(f"{cim}: history_deals_get", A.mt5.history_deals_get(1, 2, group="*GOLD*") is nyers.deals)
    check(f"{cim}: a szimbolum ERINTETLENUL megy at",
          nyers.hivasok[-1] == ("history_deals_get", (1, 2), {"group": "*GOLD*"}),
          str(nyers.hivasok[-1]))
check("konstans a csomagbol", A.mt5.TIMEFRAME_M1 == 1)

# ---------------------------------------------------------------------------
print("\n== MASODIK BROKER: NY+7 szerver, GOLD -> XAUUSD ==")
ROBO = {"brokers": [dict(REGI["broker"], id="activtrades", tag="At", mt5=REGI["mt5"]),
                    {"id": "roboforex", "tag": "Rob", "name": "RoboForex",
                     "server": "RoboForex-Pro", "login": 555,
                     "server_zone": "America/New_York+7",
                     "symbols": {"GOLD": "XAUUSD"}}],
        "active_broker": "roboforex"}
rp = P.active(ROBO)
check("az aktiv a roboforex", rp.id == "roboforex" and not rp.is_identity)
check("a lista rendben", P.validate(ROBO) == [], P.validate(ROBO))
A.configure(rp)

i = A.mt5.symbol_info("GOLD")
check("symbol_info: a brokernek XAUUSD megy", nyers.hivasok[-1] == ("symbol_info", ("XAUUSD",), {}))
check("symbol_info: a hivo GOLD-ot kap vissza", i.name == "GOLD" and i.point == 0.01, str(i))

t = A.mt5.symbol_info_tick("GOLD")
# hetfo 00:00 NY+7 szerver (tel) = vasarnap 23:00 Berlin
check("tick ideje kanonikus (tel: 00:00 -> 23:00 elozo nap)", t.time == ep(2026, 1, 11, 23, 0), t.time)
check("tick_msc is, az ezredmasodperc megmarad",
      t.time_msc == ep(2026, 1, 11, 23, 0) * 1000 + 250, t.time_msc)
check("tick ara erintetlen", (t.bid, t.ask) == (1.0, 1.1))

r = A.mt5.copy_rates_from_pos("GOLD", 1, 0, 3)
check("rates: a brokernek XAUUSD", nyers.hivasok[-1][1] == ("XAUUSD",))
check("rates: tel / nyar / ELTERO het kanonikus ideje",
      list(r["time"]) == [ep(2026, 1, 11, 23), ep(2026, 6, 14, 23), ep(2026, 3, 15, 22)],
      str(list(r["time"])))
check("rates: a nyers tomb NEM modosult (masolat)", nyers.rates["time"][0] == ep(2026, 1, 12))
check("rates: az ar erintetlen", list(r["close"]) == [1.0, 2.0, 3.0])

pz = A.mt5.positions_get(symbol="GOLD")
check("positions_get: symbol=XAUUSD megy", nyers.hivasok[-1] == ("positions_get", (), {"symbol": "XAUUSD"}))
check("pozicio: GOLD es kanonikus ido (eltero het: 00:00 -> 22:00)",
      pz[0].symbol == "GOLD" and pz[0].time == ep(2026, 3, 15, 22), str(pz[0]))
check("pozicio: a 0 ido (nincs) 0 marad", pz[0].time_update == 0)

d_from = dt.datetime(2026, 6, 14, 23, 0, tzinfo=dt.timezone.utc)      # kanonikus
A.mt5.history_deals_get(d_from, dt.datetime(2026, 6, 15, 23, 0, tzinfo=dt.timezone.utc),
                        group="*GOLD*")
nev, a, kw = nyers.hivasok[-1]
check("history: a hatar szerver-idore (23:00 Berlin nyar -> 00:00 szerver)",
      a[0] == dt.datetime(2026, 6, 15, 0, 0, tzinfo=dt.timezone.utc), str(a[0]))
check("history: group='*GOLD*' -> '*XAUUSD*'", kw.get("group") == "*XAUUSD*", str(kw))

req = {"symbol": "GOLD", "volume": 0.1}
A.mt5.order_send(req)
check("order_send: a brokernek XAUUSD", nyers.hivasok[-1][1][0]["symbol"] == "XAUUSD")
check("order_send: a hivo keres-dict-je NEM modosult", req["symbol"] == "GOLD")
check("order_calc_margin: XAUUSD", A.mt5.order_calc_margin(0, "GOLD", 0.1, 1.0) == 12.5
      and nyers.hivasok[-1][1] == ("XAUUSD",))
check("alias nelkuli szimbolum valtozatlan", (A.mt5.symbol_select("EURUSD")
                                              and nyers.hivasok[-1][1] == ("EURUSD",)))
A.configure(None)

# ---------------------------------------------------------------------------
print("\n== A profil-lista orei ==")
def br(i, **kw):
    return dict({"id": f"b{i}", "tag": f"T{i}", "server": f"S{i}", "login": 100 + i}, **kw)


check("5 broker megengedett", P.validate({"brokers": [br(i) for i in range(5)]}) == [])
h = P.validate({"brokers": [br(i) for i in range(6)]})
check("6 broker HIBA (max 5)", any("legfeljebb 5" in x for x in h), h)
h = P.validate({"brokers": [br(1), br(2, tag="T1")]})
check("ismetlodo cimke HIBA", any("tag" in x for x in h), h)
h = P.validate({"brokers": [br(1), br(2, id="b1")]})
check("ismetlodo azonosito HIBA", any("-id" in x for x in h), h)
h = P.validate({"brokers": [br(1), br(2, server="S1", login=101)]})
check("ugyanaz a szamla ketszer HIBA", any("számla" in x for x in h), h)
h = P.validate({"brokers": [br(1, server_zone="Europe/Berlni")]})
check("elgepelt zona HIBA (nem csendes visszaeses)", any("időzóna" in x for x in h), h)
h = P.validate({"brokers": [br(1)], "active_broker": "nincs"})
check("nem letezo aktiv broker HIBA", any("active_broker" in x for x in h), h)
h = P.validate({"brokers": [br(1, symbols={"GOLD": "XAUUSD", "XAU": "XAUUSD"})]})
check("ket kanonikus nev ugyanarra a bróker-szimbolumra HIBA",
      any("ugyanarra" in x for x in h), h)

print("\n== A connect() az aktiv profilt allitja be az adapterben ==")
from core import mt5_connector as mc                                     # noqa: E402
_eredeti = mc.mt5
Acct = SimpleNamespace(login=555, server="RoboForex-Pro", balance=1.0, currency="USD",
                       margin_mode=2)
mc.mt5 = SimpleNamespace(initialize=lambda **kw: True, account_info=lambda: Acct,
                         terminal_info=lambda: SimpleNamespace(path="x"),
                         last_error=lambda: (0, ""), shutdown=lambda: None)
try:
    ok = mc.connect(dict(ROBO, broker={"password": "p"}))
    check("connect sikeres a roboforex profillal", ok)
    check("az adapter profilja a roboforex", A.current() is not None
          and A.current().id == "roboforex")
finally:
    mc.mt5 = _eredeti
    A.configure(None)

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)

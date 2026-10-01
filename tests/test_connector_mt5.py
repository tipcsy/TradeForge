"""0032/1a: a bróker-semleges csatlakozó és az MT5-ös megvalósítás.

⚠ VISELKEDÉS-AZONOSSÁG: a csatlakozón át kimenő megbízás mezőről mezőre
ugyanaz, mint a mai `live_trader.open_position` / `mt5_connector.close_position`
kérése (csúszás-tűrés, kitöltési mód, GTC, bid/ask). Hamis MT5 — a valódi
terminált a teszt nem éri el.
"""
import contextlib
import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                          # noqa: E402
applog.harden_console()

from core import connector as C, connector_mt5 as CM, order_exec  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


class HamisMT5:
    TRADE_ACTION_DEAL, TRADE_ACTION_SLTP = 1, 6
    ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
    ORDER_TIME_GTC = 0
    TIMEFRAME_M1, TIMEFRAME_M15 = 1, 15

    def __init__(self):
        self.kuldott = []
        self.retcode = 10009
        self.pozik = [NS(ticket=7, symbol="GOLD", type=0, volume=0.05, price_open=4100.0,
                         price_current=4110.0, sl=4090.0, tp=4150.0, profit=5.0, swap=-0.2,
                         magic=20260627, comment="x", time=1, time_update=2, identifier=7)]

    def symbol_info_tick(self, s):
        return NS(bid=4110.0, ask=4110.5, time=123)

    def symbol_info(self, s):
        return NS(name=s, point=0.01, digits=2, trade_tick_size=0.01, trade_tick_value=1.0,
                  volume_min=0.01, volume_max=100.0, volume_step=0.01,
                  trade_stops_level=10, spread=50, filling_mode=2)

    def positions_get(self, ticket=None, symbol=None):
        if ticket is not None:
            return tuple(p for p in self.pozik if p.ticket == ticket)
        return tuple(self.pozik)

    def order_send(self, req):
        self.kuldott.append(dict(req))
        return NS(retcode=self.retcode, order=99, comment="Done")

    def last_error(self):
        return (1, "ok")

    def account_info(self):
        return NS(login=1, balance=1000.0, equity=1005.0, currency="USD", margin_free=900.0,
                  leverage=100, server="S", margin_mode=2)

    def history_deals_get(self, *a, **k):
        return (NS(ticket=1, position_id=7, symbol="GOLD", type=0, entry=0, volume=0.05,
                   price=4100.0, profit=0.0, commission=-0.3, swap=0.0, magic=5, time=1),)


hamis = HamisMT5()
_regi_mt5, _regi_lock = CM.mt5, CM._lock
CM.mt5 = hamis
CM._lock = contextlib.nullcontext
try:
    k = CM.MT5Connector()
    check("a szerződést teljesíti (Protocol)", isinstance(k, C.Connector))

    # ── nyitás: a kérés UGYANAZ, mint a mai open_position-é ──
    r = k.open_market("GOLD", C.BUY, 0.05, 4090.0, 4150.0, 20260627, "wpr_sma")
    req = hamis.kuldott[-1]
    info = hamis.symbol_info("GOLD")
    vart = {"action": 1, "symbol": "GOLD", "volume": 0.05, "type": 0, "price": 4110.5,
            "sl": 4090.0, "tp": 4150.0,
            "deviation": order_exec.deviation_points("GOLD", None, info),
            "magic": 20260627, "comment": "wpr_sma", "type_time": 0,
            "type_filling": order_exec.filling_mode("GOLD", info)}
    check("⚠ BUY: a kimenő kérés mezőről mezőre a mai", req == vart, str(req))
    check("siker → Code.OK, a ticket a válaszból", r.ok and r.ticket == 99)
    k.open_market("GOLD", C.SELL, 0.05, 4120.0, 4050.0, 1)
    check("SELL: a BID áron, SELL típussal",
          hamis.kuldott[-1]["price"] == 4110.0 and hamis.kuldott[-1]["type"] == 1)

    # ── kódfordítás ──
    for rc, kod in ((10019, C.Code.NO_MONEY), (10027, C.Code.TRADE_DISABLED),
                    (10030, C.Code.UNSUPPORTED), (10016, C.Code.INVALID_STOPS),
                    (10004, C.Code.PRICE_CHANGED), (12345, C.Code.ERROR)):
        hamis.retcode = rc
        r = k.open_market("GOLD", C.BUY, 0.05, 0, 0, 1)
        check(f"retcode {rc} → {kod} (a nyers kód megmarad naplóra)",
              r.code == kod and r.raw_code == rc and not r.ok)
    hamis.retcode = 10009

    # ── SL/TP és zárás ──
    k.modify_sltp(7, 4095.123, 4150.0)
    m = hamis.kuldott[-1]
    check("SL-módosítás: SLTP-akció, a szimbólum rácsára illesztett SL",
          m["action"] == 6 and m["position"] == 7
          and m["sl"] == order_exec.normalize_price(4095.123, info), str(m))
    check("nem létező pozíció → NOT_FOUND (nem kivétel)",
          k.modify_sltp(999, 1, 1).code == C.Code.NOT_FOUND
          and k.close(999).code == C.Code.NOT_FOUND)
    k.close(7)
    z = hamis.kuldott[-1]
    check("teljes zárás: ellentétes irány, BID (BUY-ról), a teljes lot, a pozíció jegye",
          z["type"] == 1 and z["price"] == 4110.0 and z["volume"] == 0.05 and z["position"] == 7)
    k.close(7, 0.02)
    check("részleges zárás: a kért lot", hamis.kuldott[-1]["volume"] == 0.02)

    # ── rekordok: a mai mezőnevek ──
    p = k.positions()[0]
    check("pozíció-rekord a mai mezőnevekkel",
          (p.ticket, p.symbol, p.type, p.volume, p.price_open, p.sl, p.tp, p.magic, p.side)
          == (7, "GOLD", 0, 0.05, 4100.0, 4090.0, 4150.0, 20260627, "BUY"))
    s = k.symbol_spec("GOLD")
    check("szimbólum-rekord: a ténylegesen olvasott mezők",
          (s.point, s.digits, s.trade_tick_value, s.volume_step, s.filling_mode) == (0.01, 2, 1.0, 0.01, 2))
    a = k.account()
    check("számla", (a.balance, a.currency, a.is_hedging) == (1000.0, "USD", True))
    d = k.deals(position=7)[0]
    check("kötés-előzmény (a jutalékkal — a RoboForex-kutatáshoz kell)",
          d.commission == -0.3 and d.entry == C.ENTRY_IN)
    check("ár", k.tick("GOLD").ask == 4110.5)
    # ⚠ fantom-zárás elleni védelem: a HIBA (None) nem azonos az üres listával
    hamis.positions_get = lambda **kw: None
    hamis.history_deals_get = lambda *a, **kw: None
    check("⚠ hibás pozíció-lekérdezés → None (NEM üres lista)", k.positions() is None)
    check("⚠ hibás előzmény → None", k.deals(position=7) is None)
    hamis.positions_get = lambda **kw: ()
    check("üres számla → [] (nem None)", k.positions() == [])
finally:
    CM.mt5, CM._lock = _regi_mt5, _regi_lock

# ── az aktív csatlakozó ──
C.set_active(None)
check("alapból az MT5-ös csatlakozó", isinstance(C.get(), CM.MT5Connector))
C.set_active(None)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

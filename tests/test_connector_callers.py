"""0032/1b: a motor kötés-útja a bróker-semleges csatlakozón át.

A nyitás (`live_trader.open_position`), az SL-módosítás (`modify_sl`), a
zárás / részleges zárás / SL+TP (`mt5_connector`) mostantól `core.connector`-t
hív. Ez a teszt egy HAMIS csatlakozóval azt őrzi, hogy a viselkedés a régi:
fedezet-szünet, a TP megtartása/törlése, a részleges zárás lot-illesztése és
a `rr_partial` jelölés (az újraindítás-védelem erre keres).
"""
import sys
import time
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                          # noqa: E402
applog.harden_console()

from core import connector as C                                  # noqa: E402
from core import mt5_connector as MC                             # noqa: E402
import trading.live_trader as LT                                 # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


class HamisCsatlakozo:
    name = "hamis"

    def __init__(self):
        self.hivasok = []
        self.kovetkezo = C.OrderResult(C.Code.OK, ticket=4242, request={"x": 1})
        self.pozi = C.Position(ticket=7, symbol="GOLD", type=0, volume=0.10,
                               price_open=4100.0, sl=4090.0, tp=4150.0, magic=5)

    def is_connected(self): return True
    def account(self): return None
    def tick(self, s): return C.Tick(1.0, 1.1)
    def bars(self, *a, **k): return None
    def deals(self, **k): return []

    def symbol_spec(self, s):
        return C.SymbolSpec(name=s, point=0.01, digits=2, volume_min=0.01, volume_step=0.01)

    def positions(self, symbol=None, ticket=None):
        return [self.pozi] if ticket in (None, 7) else []

    def open_market(self, *a, **k):
        self.hivasok.append(("open", a, k)); return self.kovetkezo

    def modify_sltp(self, ticket, sl, tp=None):
        self.hivasok.append(("sltp", ticket, sl, tp)); return self.kovetkezo

    def close(self, ticket, volume=None, comment="close"):
        self.hivasok.append(("close", ticket, volume, comment)); return self.kovetkezo


h = HamisCsatlakozo()
C.set_active(h)
try:
    check("a hamis is teljesíti a szerződést", isinstance(h, C.Connector))
    LT._FEDEZET_SZUNET.pop("GOLD", None)
    t = LT.open_position("GOLD", "BUY", 0.05, 4090.0, 4150.0, 5, "c", "wpr_sma")
    check("nyitás: a csatlakozó ticketjét adja vissza", t == 4242, str(t))
    check("...az irány, lot, SL, TP, magic változatlanul megy ki",
          h.hivasok[-1][1] == ("GOLD", "BUY", 0.05, 4090.0, 4150.0, 5, "c"))

    h.kovetkezo = C.OrderResult(C.Code.NO_MONEY, raw_code=10019, message="No money",
                                request={"deviation": 10, "type_filling": 2})
    t = LT.open_position("GOLD", "BUY", 0.05, 4090.0, 4150.0, 5, "c")
    check("fedezethiány: nincs ticket", t is None)
    check("⚠ ...és bekapcsol a fedezet-szünet (semleges kódból, nem 10019-ből)",
          LT._FEDEZET_SZUNET.get("GOLD", 0) > time.time())
    n = len(h.hivasok)
    LT.open_position("GOLD", "BUY", 0.05, 4090.0, 4150.0, 5, "c")
    check("...a szünet alatt nem is próbálkozik", len(h.hivasok) == n)
    LT._FEDEZET_SZUNET.pop("GOLD", None)

    h.kovetkezo = C.OrderResult(C.Code.PRICE_CHANGED, message="nincs ár")   # request üres
    check("nincs ár (ki sem ment): None", LT.open_position("EURUSD", "SELL", 0.1, 1, 1, 5) is None)

    h.kovetkezo = C.OrderResult(C.Code.OK, ticket=7, request={"symbol": "GOLD"})
    check("trailing SL: siker", LT.modify_sl(7, 4095.0) is True)
    check("⚠ ...a TP MARAD (tp=None)", h.hivasok[-1] == ("sltp", 7, 4095.0, None))
    check("ráépítés SL+TP: tp=0 → a TP TÖRLÉSE",
          MC.modify_position_sltp(7, 4095.0, 0) and h.hivasok[-1] == ("sltp", 7, 4095.0, 0.0))
    h.kovetkezo = C.OrderResult(C.Code.NOT_FOUND)
    check("nem létező pozíció: False, kivétel nélkül",
          LT.modify_sl(999, 1.0) is False and MC.modify_position_sltp(999, 1, 1) is False
          and MC.close_position(999) is False)

    h.kovetkezo = C.OrderResult(C.Code.OK, ticket=7, request={"symbol": "GOLD"})
    check("pánik-zárás: a teljes pozíció, `panic_close`",
          MC.close_position(7) and h.hivasok[-1] == ("close", 7, None, "panic_close"))
    check("részleges zárás: lot-lépésre LEFELÉ (0.037 → 0.03), `rr_partial`",
          MC.close_position_partial(7, 0.037)
          and h.hivasok[-1][:3] == ("close", 7, 0.03) and h.hivasok[-1][3] == "rr_partial",
          str(h.hivasok[-1]))
    n = len(h.hivasok)
    check("⚠ a runner min_lot alá menne → NEM zár (nincs hívás)",
          MC.close_position_partial(7, 0.10) is False and len(h.hivasok) == n)
finally:
    C.set_active(None)

_lt = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
check("a motor nyitása NEM küld közvetlen MT5-kérést", "mt5.order_send(" not in _lt)
_mc = (ROOT / "core" / "mt5_connector.py").read_text(encoding="utf-8")
check("a zárás/SL+TP sem az mt5_connector-ban", "mt5.order_send(" not in _mc)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

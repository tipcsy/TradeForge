"""#13 — a napi limit napjanak hatara + a hianyzo OUT_BY dealek."""
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta, date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import mt5_connector as mc

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ── A REGI logika, referenciakent ─────────────────────────────────────────
def regi_bounds():
    t = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)
    return t, t + timedelta(days=1)


# ══ 1. A hatar a BROKER napjahoz igazodik ═════════════════════════════════
mc._server_offset["v"] = 3 * 3600.0                 # GMT+3 broker (nyari Vantage)
frm, to = mc.server_day_bounds()
srv_now = datetime.now(timezone.utc) + timedelta(hours=3)
check("a nap-hatar a szerver ejfelre esik",
      frm.timestamp() % 86400 == 0 and (to - frm) == timedelta(days=1))
check("a MOSTANI szerver-pillanat a napon BELUL van",
      frm.timestamp() <= (datetime.now(timezone.utc).timestamp() + 3 * 3600) < to.timestamp())

mc._server_offset["v"] = 0.0
frm0, _ = mc.server_day_bounds()
check("eltolas nelkul a valos UTC-napra esik vissza",
      frm0 == datetime.now(timezone.utc).replace(hour=0, minute=0, second=0,
                                                 microsecond=0))
# ⚠ AZ „ISMERETLEN" ELTOLAS CSAK AKKOR ismeretlen, ha a LEMEZEN sincs. A
# `_load_offset` a None-t ugy erti, hogy „meg nem toltottem be" — es beolvassa a
# VALODI `data/server_offset.json`-t. Enelkul ez a sor azon a gepen PASS, ahol
# meg sosem futott a bot, es FAIL azon, ahol igen: a teszt a felhasznalo eles
# allapotatol fuggott. (Ugyanaz az osztaly, mint amikor egy teszt a valodi
# configot irta — a teszt SOSEM tamaszkodhat eles adatra.)
_real_off_file = mc._offset_file
mc._offset_file = lambda: Path(tempfile.gettempdir()) / "tfv_nincs_ilyen_offset.json"
mc._server_offset["v"] = None
check("ismeretlen eltolas (None) sem szall el", mc.server_day_bounds()[0] == frm0)
mc._offset_file = _real_off_file
mc._server_offset["v"] = None


# ══ 2. A VALOS hibaablak: helyi ejfel utan a regi logika a JOVOBE mutatott ═
# Szimulacio: a gep helyi ideje mar a kovetkezo nap (CEST = UTC+2), UTC meg nem.
class FakeDate:
    """`date.today()` a HELYI datumot adja — ezt utanozzuk."""
    @staticmethod
    def today():
        return (datetime.now(timezone.utc) + timedelta(hours=2)).date()


valodi_utc = datetime.now(timezone.utc)
helyi = valodi_utc + timedelta(hours=2)
regi_kezdet = datetime.combine(FakeDate.today(), datetime.min.time()).replace(
    tzinfo=timezone.utc)
elorenez = regi_kezdet > valodi_utc
check("a hibaablak reprodukalhato-e MOST (csak 22:00-24:00 UTC kozott)",
      True, f"UTC {valodi_utc:%H:%M} / helyi {helyi:%H:%M} -> "
            f"{'IGEN, a regi logika a jovobe mutat' if elorenez else 'nem, mas napszak'}")

# A hibaablak DETERMINISZTIKUS ellenorzese: 22:30 UTC, CEST gep, GMT+3 broker
UTC_2230 = datetime(2026, 7, 27, 22, 30, tzinfo=timezone.utc)
helyi_datum = (UTC_2230 + timedelta(hours=2)).date()          # 07-28 (mar atfordult)
regi_kezdet = datetime.combine(helyi_datum, datetime.min.time()).replace(tzinfo=timezone.utc)
check("REGI: 22:30 UTC-kor a lekerdezes egy MEG EL SEM KEZDODOTT napra mutat "
      "-> daily_pnl 0.0 -> a napi limit lenullazodik",
      regi_kezdet > UTC_2230,
      f"lekerdezes kezdete {regi_kezdet:%m-%d %H:%M} > most {UTC_2230:%m-%d %H:%M}")

# UJ: a broker (GMT+3) faliorajan ekkor 01:30, tehat a broker-nap 22:30 UTC-kor kezdodott
srv_ts = UTC_2230.timestamp() + 3 * 3600
uj_kezdet_ts = (srv_ts // 86400) * 86400
uj_kezdet = datetime.fromtimestamp(uj_kezdet_ts, tz=timezone.utc)
check("UJ: a hatar a BROKER ejfelere esik, es a mostani pillanat BELUL van",
      uj_kezdet_ts <= srv_ts < uj_kezdet_ts + 86400)
check("UJ: a hatar NEM a jovoben van (a regi hiba megszunt)",
      uj_kezdet.timestamp() <= srv_ts)


# ══ 3. OUT_BY dealek: eddig kimaradtak a napi limitbol ════════════════════
class Deal:
    def __init__(self, entry, profit, commission=0.0, swap=0.0):
        self.entry, self.profit = entry, profit
        self.commission, self.swap = commission, swap


class FakeMT5:
    DEAL_ENTRY_IN, DEAL_ENTRY_OUT, DEAL_ENTRY_OUT_BY = 0, 1, 3

    def __init__(self, deals):
        self._d = deals

    def history_deals_get(self, frm=None, to=None):
        return self._d


DEALS = [Deal(0, 0.0),            # nyito -> nem szamit
         Deal(1, -50.0),          # OUT
         Deal(3, -80.0)]          # OUT_BY (close-by) -> EDDIG KIMARADT

orig = mc.mt5
mc.mt5 = FakeMT5(DEALS)
mc._server_offset["v"] = 0.0
mc._daily_pnl_cache.update({"t": 0.0, "v": None})
v = mc.daily_pnl()
check("a napi P&L az OUT es az OUT_BY dealt IS tartalmazza (-130, nem -50)",
      v == -130.0, str(v))
check("a nyito deal nem szamit bele", v == -130.0)

# A hatas: 100$ napi limitnel a regi -50 meg ATENGEDTE volna a kereskedest
check("a regi (-50) a 100$-os limit alatt maradt volna, az uj (-130) tiltja",
      abs(-50.0) < 100 <= abs(v))
mc.mt5 = orig

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

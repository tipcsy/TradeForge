"""A FELULET MT5-ADATFORRASA — helyi MT5 vagy a motor (0029, 4b/3 S4).

⚠ MIT ORZUNK (2026-09-28, Tibi dontese: B — minden MT5-adat a broker motorjan at):
  1. HELYI modban (ma) minden a mai MT5-hivas, ugyanazzal az objektummal es a
     valodi MT5-zarral — a mai viselkedes nem valtozik.
  2. TAVOLI modban minden nev a helyes forrasbol jon (allapotkep / a motor olvaso
     muvelete), a tipusok a feluletnek megfeleloek (numpy gyertya-tomb, int
     kulcsok), es EGYETLEN MT5-hivas sem tortenik.
  3. OR: a gui.py-ban nem lehet uj kozvetlen MT5-import — csak a ket, mar
     elagaztatott helyi zarasi ag.
"""
import sys
import time
import datetime as dt
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                                  # noqa: E402
applog.harden_console()

import numpy as np                                                       # noqa: E402

from core import broker_adapter as BA                                    # noqa: E402
from core import broker_profile as P                                     # noqa: E402
from core import engine_channel as CH                                    # noqa: E402
from core import engine_status as ES                                     # noqa: E402
from dashboard import engine_gateway as GW                               # noqa: E402
from dashboard import mt5_view as MV                                     # noqa: E402

_results, _fail = [], []


def check(name, ok, detail=""):
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


ROBO = P.profiles({"brokers": [{"id": "a", "tag": "A"},
                               {"id": "rob", "tag": "Rob", "server": "RF", "login": 555}]})[1]

print("== HELYI mod: a mai MT5-hivas ==")
nyers_info = SimpleNamespace(point=0.01)
mt5_hivas = []


class NyersMT5:
    def symbol_info(self, s):
        mt5_hivas.append(("symbol_info", s))
        return nyers_info

    def symbol_select(self, s, e=True):
        mt5_hivas.append(("select", s))
        return True


_regi_raw = BA._raw
BA._raw = lambda: NyersMT5()
BA.configure(None)
GW.reset()
MV.clear_cache()
# 0032: helyi módban a CSATLAKOZÓN át — a semleges rekord, ugyanazzal az adattal
_si = MV.symbol_info("GOLD")
check("symbol_info: a bróker adata (a csatlakozón át, semleges rekordban)",
      _si is not None and _si.point == 0.01 and _si.name == "GOLD", repr(_si))
from core.mt5_connector import MT5_LOCK                                  # noqa: E402
check("lock(): a valodi MT5-zar", MV.lock() is MT5_LOCK)

print("\n== TAVOLI mod: allapotkep + motor-muveletek, MT5 NELKUL ==")
mt5_hivas.clear()
kert = []
SZERVER = 7200.0
tomb = np.array([(1_700_000_000, 1.0, 2.0, 0.5, 1.5, 10, 3, 0)],
                dtype=[("time", "<i8"), ("open", "<f8"), ("high", "<f8"), ("low", "<f8"),
                       ("close", "<f8"), ("tick_volume", "<i8"), ("spread", "<i8"),
                       ("real_volume", "<i8")])


def fake_request(profile, line="", confirmed=False, timeout=8.0, *, op=None, args=None, **kw):
    kert.append((op or line, args, confirmed))
    if op == "symbol_info":
        return {"ok": True, "result": {"point": 0.01, "digits": 2, "description": "Gold"}}
    if op == "rates":                                   # PONTOSAN a motor _rates alakja
        return {"ok": True, "result": {"names": list(tomb.dtype.names),
                                       "rows": [list(map(lambda v: v.item(), x)) for x in tomb]}}
    if op == "tf_closes":
        return {"ok": True, "result": {"15": [1.0, 2.0]}}
    if op == "closed_range":
        return {"ok": True, "result": [{"ticket": 9}]}
    if op == "symbols":
        return {"ok": True, "result": [["GOLD", "Gold spot"]]}
    if line.startswith("close"):
        return {"ok": True, "lines": ["zarva"]}
    return None


KEP = {"ts": time.time(), "stopped": False, "engine_alive": True, "mt5_ok": True,
       "broker": {"id": "rob", "login": 555, "server": "RF", "name": "RoboForex"},
       "account": {"balance": 1000.0, "currency": "USD", "daily_pnl": -3.5},
       "server_offset_sec": SZERVER, "margin_mode": 2, "margin_mode_name": "HEDGING",
       "positions": [{"ticket": 1, "symbol": "GOLD"}],
       "positions_by_symbol": {"GOLD": {"count": 1}},
       "closed_today": [{"ticket": 8}],
       # ⚠ A demo-proba lelete (2026-09-29): az arakat EDDIG a felulet toltotte,
       # a motor sosem — a motor most minden parra kozzeteszi [bid, ask, ido].
       "ticks": {"GOLD": [2400.1, 2400.4, 1_790_000_000]},
       "dashboard": {"GOLD": {"bid": None, "ask": None}}}
_regi_read = ES.read
ES.read = lambda p=None, **kw: dict(KEP, ts=time.time())
_regi_req = CH.request
CH.request = fake_request
GW.configure(ROBO, None, request=fake_request)
MV.clear_cache()
try:
    i = MV.symbol_info("GOLD")
    check("symbol_info a motortol (mezonevekkel)", i.point == 0.01 and i.description == "Gold")
    n = len(kert)
    MV.symbol_info("GOLD")
    check("symbol_info gyorsitotarbol (nincs ujabb keres)", len(kert) == n)
    t = MV.symbol_info_tick("GOLD")
    check("tick a motor kozzetett tickjeibol (a dashboard-tukorben NINCS ar)",
          t is not None and (t.bid, t.ask) == (2400.1, 2400.4), str(t))
    check("a tick IDEJE is megvan (a nyitva/zarva allapothoz)", t.time == 1_790_000_000)
    check("a spread a FRISS tickbol (nem az 5 percig tarolt szimbolum-adatbol)",
          MV.symbol_info("GOLD").spread == 30, str(MV.symbol_info("GOLD").spread))
    check("ismeretlen par tickje: None", MV.symbol_info_tick("XYZ") is None)
    r = MV.copy_rates_from_pos("GOLD", 15, 0, 1)
    check("gyertyak numpy strukturalt tombkent (mint az MT5-e)",
          isinstance(r, np.ndarray) and r.dtype.names == tomb.dtype.names
          and r["close"][0] == 1.5 and r["time"][0] == 1_700_000_000, str(r))
    check("tf_closes: int kulcsok", MV.tf_closes("GOLD", [15], 2) == {15: [1.0, 2.0]})
    check("szamlatipus: nem netting (hedging)", MV.is_netting() is False
          and MV.margin_mode_name() == "HEDGING")
    check("poziciok az allapotkepbol", MV.open_positions_detailed() == [{"ticket": 1, "symbol": "GOLD"}])
    check("pozicio-osszesito", MV.open_positions_by_symbol() == {"GOLD": {"count": 1}})
    check("mai lezartak", MV.closed_positions_today() == [{"ticket": 8}])
    check("napi P&L", MV.daily_pnl() == -3.5)
    ci = MV.connection_info({})
    check("fejlec: kapcsolat = friss kep + elo motor + elo MT5",
          ci["connected"] and ci["login"] == 555 and ci["balance"] == 1000.0
          and ci["margin_mode_name"] == "HEDGING", str(ci))
    most = dt.datetime.now(dt.timezone.utc)
    check("szerveriora a motor eltolasabol", abs((MV.server_now() - most).total_seconds()
                                                 - SZERVER) < 5)
    check("zaras a csatornan, megerositve", MV.close_position(5) is True
          and ("close 5", None, True) in kert, str(kert[-1:]))
    check("Lezart ful datumszuro: a motor szamolja",
          MV.closed_positions_range(dt.date(2026, 9, 1), dt.date(2026, 9, 2)) == [{"ticket": 9}])
    check("szimbolumlista", [(x.name, x.description) for x in MV.symbols_get()]
          == [("GOLD", "Gold spot")])
    check("ujrakapcsolodas: a motor dolga", MV.connect({}) is True)
    check("lock(): tavolrol nincs mit zarni", MV.lock() is not MT5_LOCK)
    check("⚠ EGYETLEN MT5-hivas sem tortent", mt5_hivas == [], str(mt5_hivas))
    KEP["mt5_ok"] = False
    MV.clear_cache()
    check("a motor MT5-je halott -> nincs kapcsolat", MV.connection_info({})["connected"] is False)
finally:
    ES.read, CH.request, BA._raw = _regi_read, _regi_req, _regi_raw
    GW.reset()
    MV.clear_cache()

print("\n== OR: a gui.py-ban nincs uj kozvetlen MT5-import ==")
kod = [ln for ln in (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8").splitlines()
       if ln.strip() and not ln.strip().startswith("#")]
check("nincs `broker_adapter import mt5` (minden a mt5_view-n at)",
      not [ln for ln in kod if "broker_adapter import mt5" in ln])
kozvetlen = [ln.strip() for ln in kod if "from core import mt5_connector" in ln
             or "from core.mt5_connector import" in ln]
check("csak a ket, mar elagaztatott helyi zarasi ag hivja kozvetlenul",
      len(kozvetlen) == 2, str(kozvetlen))

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)

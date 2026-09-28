"""BRÓKER-ADAPTER — az EGYETLEN kapu a program és a MetaTrader5 csomag között.

⚠ 0029 „Több bróker egyszerre", 2. lépés (2026-09-28). A kód ~60 helyen hívja
közvetlenül az MT5-öt (a felület és az élő motor is). Egy második bróker
két dolgot hoz, amit a hívók nem tudhatnak:
  1. más SZIMBÓLUMNEVET (`GOLD` → `XAUUSD`),
  2. más SZERVER-IDŐZÓNÁT (a gyertyák, tickek, pozíciók, deal-ek ideje).
Ezt nem 60 helyen oldjuk meg, hanem itt: a modul egy `mt5` objektumot ad,
UGYANAZOKKAL a függvénynevekkel, mint a `MetaTrader5` csomag. A hívók csak az
importot cserélik (`from core.broker_adapter import mt5`), és:
  • befelé a kanonikus szimbólumnév a bróker nevére fordul, a kanonikus
    időhatár a szerver órájára;
  • kifelé a bróker neve kanonikusra, minden idő (rates/ticks `time`,
    `time_msc`, pozíció/megbízás/deal idők) kanonikus órára.

⚠ A MAI VISELKEDÉS BITRE VÁLTOZATLAN. Ha az aktív profil „identitás"
(kanonikus óra, nincs alias — a mai ActivTrades-config ilyen), minden hívás
ÉRINTETLENÜL megy át a csomagnak, és az eredmény is érintetlenül jön vissza
(ugyanaz az objektum). A fordítás csak valódi második brókernél dolgozik.

⚠ A TESZTEK a modulok `mt5` nevét hamisítványra cserélik (`lt.mt5 = Fake()`);
ez az import-csere után is így marad — a hamisítvány az adapter helyére kerül.

⚠ Konstansok (TIMEFRAME_M1, ORDER_TYPE_BUY, TRADE_RETCODE_DONE…) és minden,
ami nem hordoz szimbólumot vagy időt (initialize, account_info, last_error…),
változatlanul a csomagból jön (`__getattr__`).
"""
from __future__ import annotations

import datetime as _dt
import importlib

import numpy as np

from core import broker_time as BT

_profil = None                       # BrokerProfile | None  (None = identitás)

# A MetaTrader5 eredmény-típusok időmezői (másodperc; a `_msc` végűek ms).
_IDO_MEZOK = ("time", "time_msc", "time_update", "time_update_msc",
              "time_setup", "time_setup_msc", "time_done", "time_done_msc",
              "time_expiration")


def configure(profile) -> None:
    """Az aktív bróker-profil beállítása (a `mt5_connector.connect` hívja).
    None → identitás."""
    global _profil
    _profil = profile


def current():
    return _profil


def _raw():
    return importlib.import_module("MetaTrader5")


def _aktiv() -> bool:
    return _profil is not None and not _profil.is_identity


# ── átalakítók ──────────────────────────────────────────────────────────────

def _be_sym(sym):
    return _profil.to_broker(sym)


def _ki_sym(sym):
    return _profil.to_canonical(sym)


def _ki_ido(v, mezo: str):
    if not v:                                    # 0 = „nincs" (pl. lejárat)
        return v
    return BT.epoch_to_canonical(int(v), _profil.server_zone,
                                 "ms" if mezo.endswith("_msc") else "s")


def _be_datum(d):
    """Kanonikus lekérdezési határ → szerver-idő. datetime vagy epoch-szám."""
    sz = _profil.server_zone
    if sz.is_canonical or d is None:
        return d
    if isinstance(d, _dt.datetime):
        naiv = d.replace(tzinfo=None)
        sec = int((naiv - _dt.datetime(1970, 1, 1)).total_seconds())
        uj = _dt.datetime(1970, 1, 1) + _dt.timedelta(
            seconds=BT.canonical_to_server_epoch(sec, sz))
        return uj.replace(tzinfo=d.tzinfo)
    return BT.canonical_to_server_epoch(int(d), sz)


def _ki_tuple(obj):
    """MT5 eredmény (tuple-alapú névvel ellátott típus) szimbóluma és ideje."""
    if obj is None:
        return obj
    d = obj._asdict()
    valt = False
    for k in ("symbol", "name"):
        if k in d and isinstance(d[k], str):
            uj = _ki_sym(d[k])
            if uj != d[k]:
                d[k] = uj; valt = True
    if not _profil.server_zone.is_canonical:
        for k in _IDO_MEZOK:
            if k in d:
                d[k] = _ki_ido(d[k], k); valt = True
    return type(obj)(tuple(d.values())) if valt else obj


def _ki_sorozat(res):
    if res is None:
        return res
    return tuple(_ki_tuple(x) for x in res)


def _ki_tomb(arr):
    """rates / ticks numpy tömb `time` és `time_msc` mezője."""
    if arr is None or _profil.server_zone.is_canonical or len(arr) == 0:
        return arr
    out = arr.copy()
    names = out.dtype.names or ()
    if "time" in names:
        out["time"] = BT.epoch_to_canonical(np.asarray(out["time"]), _profil.server_zone, "s")
    if "time_msc" in names:
        out["time_msc"] = BT.epoch_to_canonical(np.asarray(out["time_msc"]),
                                                _profil.server_zone, "ms")
    return out


def _be_group(kw: dict) -> dict:
    """`group="*GOLD*"` → `group="*XAUUSD*"`: a minta minden vesszős tagjában
    a csillagok nélküli kanonikus nevet a bróker nevére fordítjuk."""
    g = kw.get("group")
    if isinstance(g, str) and _profil.symbols:
        tagok = []
        for t in g.split(","):
            neg = t.startswith("!")
            mag = t[1:] if neg else t
            tiszta = mag.strip("*")
            if tiszta in _profil.symbols:
                mag = mag.replace(tiszta, _profil.symbols[tiszta])
            tagok.append(("!" if neg else "") + mag)
        kw["group"] = ",".join(tagok)
    return kw


def _be_request(req):
    if isinstance(req, dict) and "symbol" in req:
        req = dict(req); req["symbol"] = _be_sym(req["symbol"])
    return req


# ── a proxy ─────────────────────────────────────────────────────────────────

class _Mt5:
    """A `MetaTrader5` csomag helyettesítője (lásd a modul fejlécét)."""

    def __getattr__(self, name):
        return getattr(_raw(), name)

    # szimbólum
    def symbol_info(self, symbol):
        if not _aktiv():
            return _raw().symbol_info(symbol)
        return _ki_tuple(_raw().symbol_info(_be_sym(symbol)))

    def symbol_info_tick(self, symbol):
        if not _aktiv():
            return _raw().symbol_info_tick(symbol)
        return _ki_tuple(_raw().symbol_info_tick(_be_sym(symbol)))

    def symbol_select(self, symbol, *a, **kw):
        if not _aktiv():
            return _raw().symbol_select(symbol, *a, **kw)
        return _raw().symbol_select(_be_sym(symbol), *a, **kw)

    def symbols_get(self, *a, **kw):
        if not _aktiv():
            return _raw().symbols_get(*a, **kw)
        kw = _be_group(dict(kw))
        return _ki_sorozat(_raw().symbols_get(*a, **kw))

    # gyertyák / tickek
    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        if not _aktiv():
            return _raw().copy_rates_from_pos(symbol, timeframe, start_pos, count)
        return _ki_tomb(_raw().copy_rates_from_pos(_be_sym(symbol), timeframe,
                                                   start_pos, count))

    def copy_rates_from(self, symbol, timeframe, date_from, count):
        if not _aktiv():
            return _raw().copy_rates_from(symbol, timeframe, date_from, count)
        return _ki_tomb(_raw().copy_rates_from(_be_sym(symbol), timeframe,
                                               _be_datum(date_from), count))

    def copy_rates_range(self, symbol, timeframe, date_from, date_to):
        if not _aktiv():
            return _raw().copy_rates_range(symbol, timeframe, date_from, date_to)
        return _ki_tomb(_raw().copy_rates_range(_be_sym(symbol), timeframe,
                                                _be_datum(date_from), _be_datum(date_to)))

    def copy_ticks_from(self, symbol, date_from, count, flags):
        if not _aktiv():
            return _raw().copy_ticks_from(symbol, date_from, count, flags)
        return _ki_tomb(_raw().copy_ticks_from(_be_sym(symbol), _be_datum(date_from),
                                               count, flags))

    def copy_ticks_range(self, symbol, date_from, date_to, flags):
        if not _aktiv():
            return _raw().copy_ticks_range(symbol, date_from, date_to, flags)
        return _ki_tomb(_raw().copy_ticks_range(_be_sym(symbol), _be_datum(date_from),
                                                _be_datum(date_to), flags))

    # pozíciók / megbízások / előzmény
    def positions_get(self, *a, **kw):
        if not _aktiv():
            return _raw().positions_get(*a, **kw)
        kw = _be_group(dict(kw))
        if "symbol" in kw:
            kw["symbol"] = _be_sym(kw["symbol"])
        return _ki_sorozat(_raw().positions_get(*a, **kw))

    def orders_get(self, *a, **kw):
        if not _aktiv():
            return _raw().orders_get(*a, **kw)
        kw = _be_group(dict(kw))
        if "symbol" in kw:
            kw["symbol"] = _be_sym(kw["symbol"])
        return _ki_sorozat(_raw().orders_get(*a, **kw))

    def history_deals_get(self, *a, **kw):
        if not _aktiv():
            return _raw().history_deals_get(*a, **kw)
        kw = _be_group(dict(kw))
        a = tuple(_be_datum(x) for x in a)
        for k in ("date_from", "date_to"):
            if k in kw:
                kw[k] = _be_datum(kw[k])
        return _ki_sorozat(_raw().history_deals_get(*a, **kw))

    def history_orders_get(self, *a, **kw):
        if not _aktiv():
            return _raw().history_orders_get(*a, **kw)
        kw = _be_group(dict(kw))
        a = tuple(_be_datum(x) for x in a)
        for k in ("date_from", "date_to"):
            if k in kw:
                kw[k] = _be_datum(kw[k])
        return _ki_sorozat(_raw().history_orders_get(*a, **kw))

    # kereskedés
    def order_send(self, request):
        if not _aktiv():
            return _raw().order_send(request)
        return _raw().order_send(_be_request(request))

    def order_check(self, request):
        if not _aktiv():
            return _raw().order_check(request)
        return _raw().order_check(_be_request(request))

    def order_calc_margin(self, action, symbol, *a):
        if not _aktiv():
            return _raw().order_calc_margin(action, symbol, *a)
        return _raw().order_calc_margin(action, _be_sym(symbol), *a)

    def order_calc_profit(self, action, symbol, *a):
        if not _aktiv():
            return _raw().order_calc_profit(action, symbol, *a)
        return _raw().order_calc_profit(action, _be_sym(symbol), *a)


mt5 = _Mt5()

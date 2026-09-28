"""A FELÜLET MT5-ADATFORRÁSA — helyi MT5 vagy a (külön processzben futó) motor.

⚠ 0029, 4b/3 S4 (2026-09-28). Tibi döntése (B): a felület NEM kapcsolódik
közvetlenül MT5-höz, ha a motor külön processzben fut — minden MT5-adat a
bróker SAJÁT motorján át jön. Ok: a MetaTrader5 csomag egy processzből egyszerre
csak EGY terminálhoz kapcsolódik; több brókernél a felület nem tarthatna
kapcsolatot mindegyikkel.

Ez a modul UGYANAZOKAT a neveket adja, amelyeket a felület eddig használt
(`symbol_info`, `symbol_info_tick`, `copy_rates_from_pos`, `tf_closes`,
`open_positions_detailed`, `closed_positions_range`…), így a hívási helyeken
jórészt csak az import cserélődik:

  • HELYI mód (ma, alapértelmezés): a mai MT5-hívás, a közös MT5-zárral.
  • TÁVOLI mód (`engine_gateway.is_remote()`): az állapotképből (számla,
    pozíciók, árak, mai lezártak — `core/engine_status`) vagy a motor OLVASÓ
    műveletéből (`symbol_info`, `rates`, `tf_closes`, `closed_range`).

⚠ A SZÁMÍTÁS A FELÜLETEN MARAD, csak a NYERS adat jön a motorból — a kijelzés
számítása egyszer már GIL-fogással lassította a kereskedési kört.

⚠ GYORSÍTÓTÁR távoli módban: a szimbólum-adat statikus (5 perc), a gyertyák
rövid ideig (`RATES_TTL`), az állapotkép 1 mp. A csatorna egy fájl-postaláda —
egy lekérdezés ~1 mp; a felület ezért nem kérdezhet mindent minden körben.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import time
from types import SimpleNamespace

import numpy as np

from dashboard import engine_gateway as _gw

INFO_TTL, RATES_TTL, SNAP_TTL = 300.0, 5.0, 1.0
_cache: dict = {}


def _remote() -> bool:
    return _gw.is_remote()


def _tar(kulcs, ttl, fn):
    most = time.time()
    hit = _cache.get(kulcs)
    if hit is not None and most - hit[0] < ttl:
        return hit[1]
    v = fn()
    if v is not None:
        _cache[kulcs] = (most, v)
    return v


def clear_cache() -> None:
    _cache.clear()


def _snap() -> dict:
    from core import engine_status as ES
    return _tar(("snap",), SNAP_TTL, lambda: ES.read(_gw._remote)) or {}


def _op(name, **args):
    """Szinkron olvasó művelet a motortól (None, ha nem válaszol)."""
    return _gw.op(name, lambda: None, sync=True, timeout=8.0, **args)


# ── MT5-zár és konstansok ───────────────────────────────────────────────────

def lock():
    """A közös MT5-zár helyben; távoli módban nincs mit zárni."""
    if _remote():
        return contextlib.nullcontext()
    from core.mt5_connector import MT5_LOCK
    return MT5_LOCK


def __getattr__(name):
    # TIMEFRAME_* és egyéb konstansok a csomagból (terminál nélkül is elérhetők).
    if name.startswith(("TIMEFRAME_", "ORDER_", "TRADE_")):
        import MetaTrader5 as _m
        return getattr(_m, name)
    raise AttributeError(name)


# ── szimbólum ───────────────────────────────────────────────────────────────

def symbol_select(symbol, enable=True):
    if _remote():
        return True                          # a motor maga választja ki
    from core.broker_adapter import mt5
    return mt5.symbol_select(symbol, enable)


def symbols_get():
    """A bróker szimbólumai (az „Instrumentum hozzáadása" ablaknak)."""
    if not _remote():
        from core.broker_adapter import mt5
        return mt5.symbols_get()
    d = _tar(("symbols",), INFO_TTL, lambda: _op("symbols")) or []
    return [SimpleNamespace(name=n, description=dsc) for n, dsc in d]


def symbol_info(symbol):
    if not _remote():
        from core.broker_adapter import mt5
        return mt5.symbol_info(symbol)
    d = _tar(("info", symbol), INFO_TTL, lambda: _op("symbol_info", symbol=symbol))
    return SimpleNamespace(**d) if d else None


def symbol_info_tick(symbol):
    if not _remote():
        from core.broker_adapter import mt5
        return mt5.symbol_info_tick(symbol)
    ds = (_snap().get("dashboard") or {}).get(symbol) or {}
    if ds.get("bid") is None or ds.get("ask") is None:
        return None
    return SimpleNamespace(bid=ds["bid"], ask=ds["ask"])


def copy_rates_from_pos(symbol, timeframe, start, count):
    if not _remote():
        from core.broker_adapter import mt5
        return mt5.copy_rates_from_pos(symbol, timeframe, start, count)
    d = _tar(("rates", symbol, int(timeframe), int(start), int(count)), RATES_TTL,
             lambda: _op("rates", symbol=symbol, tf=int(timeframe), start=int(start),
                         count=int(count)))
    return rates_from_payload(d)


def rates_from_payload(d):
    """A motor `rates` válasza → numpy struktúrált tömb (mint az MT5-é)."""
    if not d or not d.get("rows"):
        return None
    names = d["names"]
    tipus = [(n, "<i8" if n in ("time", "tick_volume", "spread", "real_volume")
              else "<f8") for n in names]
    return np.array([tuple(r) for r in d["rows"]], dtype=tipus)


def tf_closes(symbol, timeframes, count) -> dict:
    if not _remote():
        from core import mt5_connector
        return mt5_connector.tf_closes(symbol, timeframes, count)
    d = _tar(("tfc", symbol, tuple(timeframes), int(count)), RATES_TTL,
             lambda: _op("tf_closes", symbol=symbol, tfs=list(timeframes),
                         count=int(count))) or {}
    return {int(k): v for k, v in d.items()}


# ── számla / pozíciók / idő ─────────────────────────────────────────────────

def is_netting() -> bool:
    if not _remote():
        from core import mt5_connector
        return mt5_connector.is_netting()
    from core.mt5_connector import MARGIN_NETTING, MARGIN_EXCHANGE
    return _snap().get("margin_mode") in (MARGIN_NETTING, MARGIN_EXCHANGE)


def margin_mode_name() -> str:
    if not _remote():
        from core import mt5_connector
        return mt5_connector.margin_mode_name()
    return str(_snap().get("margin_mode_name") or "")


def open_positions_detailed() -> list:
    if not _remote():
        from core import mt5_connector
        return mt5_connector.open_positions_detailed()
    return list(_snap().get("positions") or [])


def open_positions_by_symbol() -> dict:
    if not _remote():
        from core import mt5_connector
        return mt5_connector.open_positions_by_symbol()
    return dict(_snap().get("positions_by_symbol") or {})


def closed_positions_today() -> list:
    if not _remote():
        from core import mt5_connector
        return mt5_connector.closed_positions_today()
    return list(_snap().get("closed_today") or [])


def daily_pnl():
    if not _remote():
        from core import mt5_connector
        return mt5_connector.daily_pnl()
    return float((_snap().get("account") or {}).get("daily_pnl") or 0.0)


def server_offset_sec(symbols=None):
    if not _remote():
        from core import mt5_connector
        return mt5_connector.server_offset_sec(symbols)
    return _snap().get("server_offset_sec")


def server_now():
    """A bróker faliórája (UTC-nek címkézve — a `mt5_connector.server_now`
    konvenciója). Távoli módban a motor mért eltolásából."""
    if not _remote():
        from core import mt5_connector
        return mt5_connector.server_now()
    off = _snap().get("server_offset_sec")
    most = _dt.datetime.now(_dt.timezone.utc)
    return most + _dt.timedelta(seconds=float(off)) if off is not None else most


def connection_info(cfg) -> dict:
    """A fejléc adatai. Távoli módban az állapotképből: kapcsolat = a motor
    MT5-je él ÉS a kép friss."""
    if not _remote():
        from core import mt5_connector
        return mt5_connector.connection_info(cfg)
    from core import engine_status as ES
    s = _snap()
    acc = s.get("account") or {}
    b = s.get("broker") or {}
    return {"connected": ES.health(s) == ES.FUT, "login": b.get("login"),
            "server": b.get("server"), "name": b.get("name", ""),
            "balance": acc.get("balance") or 0.0,
            "currency": acc.get("currency", ""), "is_demo": b.get("is_demo"),
            "margin_mode": s.get("margin_mode"),
            "margin_mode_name": s.get("margin_mode_name") or "",
            "is_netting": is_netting()}


def server_today():
    """A bróker naptára szerinti MAI nap."""
    if not _remote():
        from core import mt5_connector
        return mt5_connector.server_today()
    return server_now().date()


def close_position(ticket) -> bool:
    """Pozíció zárása. Távoli módban a MOTOR zárja (a csatornán, a közös
    parancs-rétegen; a hívó már rákérdezett)."""
    if not _remote():
        from core import mt5_connector
        return bool(mt5_connector.close_position(ticket))
    from core import engine_channel as CH
    r = CH.request(_gw._remote, f"close {int(ticket)}", True, timeout=8.0)
    return bool(r and r.get("ok"))


def closed_positions_range(date_from, date_to) -> list:
    """A Lezárt fül dátum-szűrője. Helyben a mai út (a bróker naptárával);
    távoli módban a MOTOR számolja a határokat és a listát."""
    if not _remote():
        from core.mt5_connector import closed_positions_range as _r, server_day_bounds_for
        frm, to = server_day_bounds_for(date_from, date_to)
        return _r(frm, to)
    return _op("closed_range", date_from=str(date_from), date_to=str(date_to)) or []


def connect(cfg) -> bool:
    """Újrakapcsolódás. Távoli módban a MOTOR dolga — a felület nem kapcsolódik."""
    if _remote():
        return True
    from core import mt5_connector
    return mt5_connector.connect(cfg)

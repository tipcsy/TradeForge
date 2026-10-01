"""Az MT5 mint csatlakozó (0032, 1. lépés) — a `core.connector.Connector`
első megvalósítása, a MAI kódból.

⚠ VISELKEDÉS-AZONOSSÁG: a megbízás ugyanazokkal a mezőkkel megy ki, mint
eddig a `live_trader.open_position` / `mt5_connector.close_position`
(csúszás-tűrés `order_exec.deviation_points`, a szimbólum TÁMOGATOTT
kitöltési módja `order_exec.filling_mode`, GTC, az ár a bid/ask szerint) —
a csatlakozóra váltás nem változtathat a kötéseken. A `test_connector_mt5`
a kimenő kérés-szótárt mezőről mezőre ellenőrzi.

Minden hívás a `core.broker_adapter`-en (név- és időfordítás) és az MT5-
zár alatt megy.
"""
from __future__ import annotations

from typing import Optional

from core import order_exec
from core.broker_adapter import mt5
from core.connector import (Account, Code, Deal, OrderResult, Position, SymbolSpec,
                            Tick, BUY, SELL)

# MT5 retcode → semleges kód (a lista a mai kódban ténylegesen előfordulók +
# a dokumentált társaik)
_KOD = {
    10008: Code.OK, 10009: Code.OK, 10010: Code.OK,
    10019: Code.NO_MONEY,
    10016: Code.INVALID_STOPS,
    10014: Code.INVALID_VOLUME,
    10004: Code.PRICE_CHANGED, 10015: Code.PRICE_CHANGED,
    10020: Code.PRICE_CHANGED, 10021: Code.PRICE_CHANGED,
    10018: Code.MARKET_CLOSED,
    10017: Code.TRADE_DISABLED, 10026: Code.TRADE_DISABLED,
    10027: Code.TRADE_DISABLED,
    10030: Code.UNSUPPORTED,
}

_TF = {1: "TIMEFRAME_M1", 5: "TIMEFRAME_M5", 15: "TIMEFRAME_M15",
       30: "TIMEFRAME_M30", 60: "TIMEFRAME_H1", 240: "TIMEFRAME_H4",
       1440: "TIMEFRAME_D1"}


def minutes_of(tf) -> int:
    """MT5 idősík-konstans VAGY perc → perc. A mai hívók egy része az MT5-
    konstanst adja (`mt5.TIMEFRAME_H1` = 16385), a semleges felület percet vár.
    (M1–M30 konstansa egyezik a percével, ezért mindkét irány egyértelmű.)"""
    tf = int(tf)
    if tf in _TF:
        return tf
    for perc, nev in _TF.items():
        if getattr(mt5, nev, None) == tf:
            return perc
    raise ValueError(f"ismeretlen idősík: {tf}")


def _lock():
    from core.mt5_connector import MT5_LOCK
    return MT5_LOCK


def code_of(retcode) -> str:
    if retcode is None:
        return Code.ERROR
    return _KOD.get(int(retcode), Code.ERROR)


def _pos(p) -> Position:
    g = lambda k, alap=0: getattr(p, k, alap)   # noqa: E731
    return Position(
        ticket=int(g("ticket") or 0), symbol=g("symbol", ""), type=int(g("type") or 0),
        volume=float(g("volume") or 0.0), price_open=float(g("price_open") or 0.0),
        price_current=float(getattr(p, "price_current", 0.0) or 0.0),
        sl=float(getattr(p, "sl", 0.0) or 0.0), tp=float(getattr(p, "tp", 0.0) or 0.0),
        profit=float(getattr(p, "profit", 0.0) or 0.0),
        swap=float(getattr(p, "swap", 0.0) or 0.0),
        magic=int(getattr(p, "magic", 0) or 0), comment=str(getattr(p, "comment", "") or ""),
        time=int(getattr(p, "time", 0) or 0),
        time_update=int(getattr(p, "time_update", 0) or 0),
        identifier=int(getattr(p, "identifier", 0) or 0))


def _deal(d) -> Deal:
    g = lambda k, alap=0: getattr(d, k, alap)   # noqa: E731
    return Deal(
        ticket=int(g("ticket") or 0), position_id=int(g("position_id") or 0),
        symbol=g("symbol", ""), type=int(g("type") or 0), entry=int(g("entry") or 0),
        volume=float(g("volume") or 0.0), price=float(g("price") or 0.0),
        profit=float(getattr(d, "profit", 0.0) or 0.0),
        commission=float(getattr(d, "commission", 0.0) or 0.0),
        swap=float(getattr(d, "swap", 0.0) or 0.0),
        fee=float(getattr(d, "fee", 0.0) or 0.0),
        magic=int(getattr(d, "magic", 0) or 0), time=int(getattr(d, "time", 0) or 0),
        comment=str(getattr(d, "comment", "") or ""), order=int(getattr(d, "order", 0) or 0))


def _spec(i, symbol: str = "") -> SymbolSpec:
    g = lambda k, alap=0: getattr(i, k, alap)   # noqa: E731
    return SymbolSpec(
        name=g("name", symbol) or symbol, point=float(g("point", 0.0) or 0.0),
        digits=int(g("digits", 0) or 0),
        trade_tick_size=float(g("trade_tick_size", 0.0) or 0.0),
        trade_tick_value=float(g("trade_tick_value", 0.0) or 0.0),
        trade_contract_size=float(g("trade_contract_size", 0.0) or 0.0),
        volume_min=float(g("volume_min", 0.0) or 0.0),
        volume_max=float(g("volume_max", 0.0) or 0.0),
        volume_step=float(g("volume_step", 0.0) or 0.0),
        trade_stops_level=int(g("trade_stops_level", 0) or 0),
        spread=int(g("spread", 0) or 0), filling_mode=int(g("filling_mode", 0) or 0),
        trade_mode=int(g("trade_mode", 0) or 0), margin_mode=int(g("margin_mode", 0) or 0),
        currency_profit=str(g("currency_profit", "") or ""),
        description=str(g("description", "") or ""))


class MT5Connector:
    name = "mt5"

    # ── kapcsolat ──
    def is_connected(self) -> bool:
        with _lock():
            return mt5.terminal_info() is not None

    # ── adatok ──
    def account(self) -> Optional[Account]:
        with _lock():
            a = mt5.account_info()
        if a is None:
            return None
        return Account(login=int(a.login), balance=float(a.balance),
                       equity=float(getattr(a, "equity", a.balance)),
                       currency=str(a.currency),
                       margin_free=float(getattr(a, "margin_free", 0.0) or 0.0),
                       leverage=int(getattr(a, "leverage", 0) or 0),
                       server=str(getattr(a, "server", "") or ""),
                       is_hedging=int(getattr(a, "margin_mode", 2) or 2) == 2)

    def symbol_spec(self, symbol: str) -> Optional[SymbolSpec]:
        with _lock():
            i = mt5.symbol_info(symbol)
        return _spec(i, symbol) if i is not None else None

    def tick(self, symbol: str) -> Optional[Tick]:
        with _lock():
            t = mt5.symbol_info_tick(symbol)
        if t is None:
            return None
        return Tick(bid=float(t.bid), ask=float(t.ask), time=int(getattr(t, "time", 0) or 0))

    def bars(self, symbol: str, timeframe_min: int, count: int, start: int = 0):
        tf = getattr(mt5, _TF[minutes_of(timeframe_min)])
        with _lock():
            return mt5.copy_rates_from_pos(symbol, tf, int(start), int(count))

    def positions(self, symbol: Optional[str] = None,
                  ticket: Optional[int] = None) -> list:
        with _lock():
            if ticket is not None:
                r = mt5.positions_get(ticket=int(ticket))
            elif symbol is not None:
                r = mt5.positions_get(symbol=symbol)
            else:
                r = mt5.positions_get()
        # ⚠ None = HIBA (nem „nincs pozíció"): a lezárás-felismerés erre épül —
        # egy pillanatnyi hiba nem könyvelhet el minden pozíciót lezártnak
        if r is None:
            return None
        return [_pos(p) for p in r]

    def deals(self, *, position: Optional[int] = None, frm=None, to=None,
              symbol: Optional[str] = None) -> list:
        with _lock():
            if position is not None:
                r = mt5.history_deals_get(position=int(position))
            elif symbol is not None:
                r = mt5.history_deals_get(frm, to, group=f"*{symbol}*")
            else:
                r = mt5.history_deals_get(frm, to)
        if r is None:
            return None                       # HIBA ≠ üres előzmény (lásd fent)
        return [_deal(d) for d in r]

    # ── végrehajtás ──
    def _kuld(self, request: dict) -> OrderResult:
        with _lock():
            res = mt5.order_send(request)
            hiba = None if res is not None else mt5.last_error()
        if res is None:
            return OrderResult(Code.ERROR, message=str(hiba), request=request)
        rc = getattr(res, "retcode", None)
        return OrderResult(code_of(rc), ticket=int(getattr(res, "order", 0) or 0),
                           raw_code=rc, message=str(getattr(res, "comment", "") or ""),
                           request=request)

    def open_market(self, symbol: str, side: str, volume: float, sl: float,
                    tp: float, magic: int, comment: str = "",
                    cfg: Optional[dict] = None) -> OrderResult:
        """`cfg`: a futó config (a pár csúszás-tűréséhez — `deviation_points`)."""
        with _lock():
            t = mt5.symbol_info_tick(symbol)
            info = mt5.symbol_info(symbol)
        if t is None:
            return OrderResult(Code.PRICE_CHANGED, message="nincs ár (tick)")
        request = {
            "action":    mt5.TRADE_ACTION_DEAL,
            "symbol":    symbol,
            "volume":    volume,
            "type":      mt5.ORDER_TYPE_BUY if side == BUY else mt5.ORDER_TYPE_SELL,
            "price":     t.ask if side == BUY else t.bid,
            "sl":        sl,
            "tp":        tp,
            "deviation": order_exec.deviation_points(symbol, cfg, info),
            "magic":     magic,
            "comment":   comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": order_exec.filling_mode(symbol, info),
        }
        return self._kuld(request)

    def modify_sltp(self, ticket: int, sl: float,
                    tp: Optional[float] = None) -> OrderResult:
        with _lock():
            r = mt5.positions_get(ticket=int(ticket))
            if not r:
                return OrderResult(Code.NOT_FOUND, message=f"#{ticket} nincs nyitva")
            p = r[0]
            info = mt5.symbol_info(p.symbol)
        if tp is None:
            uj_tp = p.tp                                  # a mostani marad (trailing)
        elif not tp:
            uj_tp = 0.0                                   # TÖRLÉS — nem rácsra igazítjuk
        else:
            uj_tp = order_exec.normalize_price(tp, info)
        request = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "symbol":   p.symbol,
            "sl":       order_exec.normalize_price(sl, info),
            "tp":       uj_tp,
            "position": int(ticket),
        }
        return self._kuld(request)

    def close(self, ticket: int, volume: Optional[float] = None,
              comment: str = "close") -> OrderResult:
        """Piaci zárás; `volume` None → a teljes pozíció. A részleges zárás
        lot-illesztése (step, min, a maradék runner) a HÍVÓ dolga."""
        with _lock():
            r = mt5.positions_get(ticket=int(ticket))
            if not r:
                return OrderResult(Code.NOT_FOUND, message=f"#{ticket} nincs nyitva")
            p = r[0]
            t = mt5.symbol_info_tick(p.symbol)
            info = mt5.symbol_info(p.symbol)
        if t is None:
            return OrderResult(Code.PRICE_CHANGED, message="nincs ár (tick)")
        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       p.symbol,
            "volume":       p.volume if volume is None else volume,
            "type":         mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
            "position":     int(ticket),
            "price":        t.bid if p.type == 0 else t.ask,
            "deviation":    order_exec.deviation_points(p.symbol, None, info),
            "magic":        p.magic,
            "comment":      comment,
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": order_exec.filling_mode(p.symbol, info),
        }
        return self._kuld(request)

"""BRÓKER-SEMLEGES CSATLAKOZÓ-FELÜLET (0032, 1. lépés).

Tibi kérdése (2026-09-30): „úgy kellene megírni a motorokat, hogy az csak
kiküldi és kéri az adatot, és az egyes konnektor végrehajtja”. Eddig a motor
MT5-ALAKÚ volt: MT5 megbízás-szótárakat küldött (`TRADE_ACTION_DEAL`,
filling-mód, deviation), MT5 retcode-okat várt. Ez a modul a SZERZŐDÉS: mit
kér a motor egy brókertől, és milyen alakban kapja vissza.

A REKORDOK MEZŐNEVEI SZÁNDÉKOSAN A MAI NEVEK (`ticket`, `price_open`,
`magic`, `point`, `trade_tick_value`…): a meglévő kód (méretezés, BE,
trailing, felület) változtatás nélkül olvassa őket — egy új csatlakozónak
viszont CSAK ezeket kell kitöltenie, nem egy MT5-objektumot utánoznia.

Irányok és kódok BRÓKER-SEMLEGESEK (`BUY`/`SELL`, `Code.*`); a nyers
bróker-kód (`raw_code`) csak naplózásra.

Az első (és ma egyetlen) megvalósítás: `core.connector_mt5.MT5Connector`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

BUY, SELL = "BUY", "SELL"
# A pozíció `type` mezője a mai kódban 0 = BUY, 1 = SELL (MT5-örökség, 29 helyen
# olvassuk) — a semleges rekord is így adja, plusz a `side` szöveggel.
TYPE_BUY, TYPE_SELL = 0, 1


class Code:
    """A megbízás eredménye — bróker-semlegesen. A motor EZEKRE dönt (pl.
    fedezet-szünet), a nyers kód csak a naplóba megy."""
    OK = "ok"
    NO_MONEY = "no_money"            # fedezethiány
    INVALID_STOPS = "invalid_stops"  # SL/TP túl közel / érvénytelen
    INVALID_VOLUME = "invalid_volume"
    PRICE_CHANGED = "price_changed"  # requote / nincs ár / csúszás
    MARKET_CLOSED = "market_closed"
    TRADE_DISABLED = "trade_disabled"  # pl. AutoTrading kikapcsolva a terminálban
    UNSUPPORTED = "unsupported"      # pl. nem támogatott kitöltési mód
    NOT_FOUND = "not_found"          # nincs ilyen pozíció
    ERROR = "error"                  # minden más


@dataclass
class Tick:
    bid: float
    ask: float
    time: int = 0                    # a bróker ideje (epoch mp), ahogy jön


@dataclass
class SymbolSpec:
    """Az instrumentum kereskedési adatai — a mai kódban ténylegesen olvasott
    mezők (felmérve 2026-10-01)."""
    name: str
    point: float
    digits: int
    trade_tick_size: float = 0.0
    trade_tick_value: float = 0.0
    trade_contract_size: float = 0.0
    volume_min: float = 0.0
    volume_max: float = 0.0
    volume_step: float = 0.0
    trade_stops_level: int = 0
    spread: int = 0                  # pontban
    filling_mode: int = 0            # bróker-specifikus bitmaszk (MT5: 1=FOK, 2=IOC)
    trade_mode: int = 0
    margin_mode: int = 0
    currency_profit: str = ""
    description: str = ""


@dataclass
class Position:
    ticket: int
    symbol: str
    type: int                        # TYPE_BUY / TYPE_SELL
    volume: float
    price_open: float
    price_current: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    profit: float = 0.0
    swap: float = 0.0
    magic: int = 0
    comment: str = ""
    time: int = 0
    time_update: int = 0
    identifier: int = 0

    @property
    def side(self) -> str:
        return BUY if self.type == TYPE_BUY else SELL


@dataclass
class Deal:
    ticket: int
    position_id: int
    symbol: str
    type: int
    entry: int                       # 0 = nyitó, 1 = záró, 2 = fordító, 3 = záró (out_by)
    volume: float
    price: float
    profit: float = 0.0
    commission: float = 0.0
    swap: float = 0.0
    fee: float = 0.0
    magic: int = 0
    time: int = 0
    comment: str = ""
    order: int = 0


ENTRY_IN, ENTRY_OUT, ENTRY_INOUT, ENTRY_OUT_BY = 0, 1, 2, 3


@dataclass
class Account:
    login: int
    balance: float
    equity: float
    currency: str
    margin_free: float = 0.0
    leverage: int = 0
    server: str = ""
    is_hedging: bool = True


@dataclass
class OrderResult:
    code: str                        # Code.*
    ticket: int = 0                  # a nyitott/érintett pozíció (vagy megbízás)
    raw_code: Optional[int] = None   # a bróker saját kódja — CSAK naplóra
    message: str = ""
    request: dict = field(default_factory=dict)   # amit elküldtünk (naplóra)

    @property
    def ok(self) -> bool:
        return self.code == Code.OK


@runtime_checkable
class Connector(Protocol):
    """Amit a motor egy brókertől kér. Minden ár/idő a BRÓKER szerint (a
    szerveridő-fordítás a `core.broker_adapter` dolga); a szimbólum KANONIKUS
    név (a fordítás szintén ott)."""

    name: str

    # ── kapcsolat ──
    def is_connected(self) -> bool: ...

    # ── adatok ──
    def account(self) -> Optional[Account]: ...
    def symbol_spec(self, symbol: str) -> Optional[SymbolSpec]: ...
    def tick(self, symbol: str) -> Optional[Tick]: ...
    def bars(self, symbol: str, timeframe_min: int, count: int, start: int = 0):
        """Gyertyák (numpy rekord-tömb: time, open, high, low, close,
        tick_volume, spread) — a legfrissebbtől `start` gyertyával vissza."""
        ...
    def positions(self, symbol: Optional[str] = None,
                  ticket: Optional[int] = None) -> Optional[list]:
        """⚠ None = a lekérdezés HIBÁS (nem „nincs pozíció"); [] = nincs. A
        lezárás-felismerés erre épül (fantom-zárás elleni védelem)."""
        ...
    def deals(self, *, position: Optional[int] = None, frm=None, to=None,
              symbol: Optional[str] = None) -> Optional[list]:
        """Mint a `positions`: None = hiba, [] = nincs kötés."""
        ...

    def margin_required(self, symbol: str, side: str, volume: float,
                        price: float) -> Optional[float]:
        """A kötéshez szükséges fedezet a számla devizájában (None: nem ismert)."""
        ...

    # ── végrehajtás ──
    def open_market(self, symbol: str, side: str, volume: float, sl: float,
                    tp: float, magic: int, comment: str = "",
                    cfg: Optional[dict] = None) -> OrderResult:
        """`cfg`: a futó config (pl. a pár csúszás-tűréséhez)."""
        ...
    def modify_sltp(self, ticket: int, sl: float,
                    tp: Optional[float] = None) -> OrderResult:
        """`tp`: None → a mostani marad; 0 → a TP TÖRLÉSE; különben az új TP."""
        ...
    def close(self, ticket: int, volume: Optional[float] = None,
              comment: str = "close") -> OrderResult:
        """`volume` None → a teljes pozíció. A `comment` a bróker-oldali jelölés
        (pl. `rr_partial` — az újraindítás-védelem erre épül)."""
        ...


# ── az aktív csatlakozó ─────────────────────────────────────────────────────
_aktiv: Optional[Connector] = None


def get() -> Connector:
    """Az aktív csatlakozó. Alapból az MT5-ös (a mai egyetlen bróker-típus)."""
    global _aktiv
    if _aktiv is None:
        from core.connector_mt5 import MT5Connector
        _aktiv = MT5Connector()
    return _aktiv


def set_active(conn: Optional[Connector]) -> None:
    """Teszt / jövőbeli bróker-típus: a csatlakozó cseréje (None → alap)."""
    global _aktiv
    _aktiv = conn

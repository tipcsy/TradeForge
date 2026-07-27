"""
Végrehajtási (order) réteg — EGY forrás a megbízások BRÓKER-FÜGGŐ paramétereire.

A jelzés lehet tökéletes: ha a megbízás formája nem felel meg annak, amit a bróker
az adott szimbólumon elfogad, a kötés egyszerűen elmarad. Ez a modul azt a három
dolgot adja meg, amit eddig sehol nem kérdeztünk meg a brókertől:

  1. **Csúszás-tűrés (`deviation`)** — enélkül az `order_send` 0 pont csúszást enged,
     így gyors piacon (index, hír) requote / „Invalid price" a válasz, és a jel
     elveszik. Az effektív érték `max(alap, aktuális spread pontban)`: a spread-kapu
     már úgyis korlátozza, mekkora spreadnél lépünk be, tehát legfeljebb ~egy
     spreadnyi csúszást fogadunk el a jegyzett áron túl.
  2. **Kitöltési mód (`type_filling`)** — a `symbol_info.filling_mode` BITMASZK
     mondja meg, mit fogad el a szimbólum. A fixen bedrótozott IOC ott, ahol a
     bróker FOK-ot vár, MINDEN kötést elbukik (retcode 10030).
  3. **Minimum stop-távolság (`trade_stops_level`) és ár-normalizálás** — a
     brókernél közelebbi SL/TP-t `10016 Invalid stops`-szal utasít vissza, a
     tick-méretre nem illeszkedő árat pedig `10015 Invalid price`-szal.

ZÁROLÁS: ez a modul NEM fogja az `MT5_LOCK`-ot — a hívó felelőssége (a
`mt5_connector` belső hívói már a lock alatt futnak, így az itteni lock-vétel
holtponthoz vezetne). Ugyanaz a konvenció, mint a `_breakeven_plan`-nél.
"""

from __future__ import annotations

import MetaTrader5 as mt5

# A `symbol_info.filling_mode` BITMASZK értékei. A MetaTrader5 Python csomag NEM
# exportálja a SYMBOL_FILLING_* konstansokat (csak az ORDER_FILLING_*-ot), ezért itt
# vannak — az MQL5 dokumentáció szerinti értékekkel.
SYMBOL_FILLING_FOK = 1
SYMBOL_FILLING_IOC = 2

# A csúszás-tűrés ALAPÉRTÉKE pontban, ha a config nem mond mást. Az effektív érték
# ennél sosem kisebb, de az aktuális spreadnél sem (lásd `deviation_points`).
DEFAULT_DEVIATION_POINTS = 10

# szimbólum → kitöltési mód. A szimbólum végrehajtási beállítása futás közben nem
# változik, a maszk-lekérdezés viszont minden megbízásnál futna → cache.
_filling_cache: dict[str, int] = {}


def filling_mode(symbol: str, info=None) -> int:
    """A szimbólumon TÁMOGATOTT kitöltési mód (`ORDER_FILLING_*`).

    A `symbol_info.filling_mode` bitmaszk; a piaci megbízáshoz IOC a preferált
    (részleges kitöltést enged, tehát ritkábban bukik el), utána FOK, végül RETURN.
    Ha a szimbólum-információ nem elérhető, az eddigi IOC-ra esik vissza — így a
    viselkedés a régi marad ott, ahol nincs mit eldönteni."""
    cached = _filling_cache.get(symbol)
    if cached is not None:
        return cached
    if info is None:
        info = mt5.symbol_info(symbol)
    mask = getattr(info, "filling_mode", 0) if info is not None else 0
    if mask & SYMBOL_FILLING_IOC:
        mode = mt5.ORDER_FILLING_IOC
    elif mask & SYMBOL_FILLING_FOK:
        mode = mt5.ORDER_FILLING_FOK
    else:
        # Se IOC, se FOK: a szimbólum csak RETURN-t enged (jellemzően tőzsdei/
        # exchange végrehajtás). Maszk nélkül (info hiány) marad a régi IOC.
        mode = mt5.ORDER_FILLING_RETURN if info is not None else mt5.ORDER_FILLING_IOC
    if info is not None:
        _filling_cache[symbol] = mode
    return mode


def deviation_points(symbol: str, cfg: dict | None = None, info=None) -> int:
    """A megengedett csúszás PONTBAN egy piaci megbízáshoz.

    `max(alap, aktuális spread pontban)` — a spread-kapu már eldöntötte, hogy a
    pillanatnyi spread elfogadható, ezért ennyi csúszást a belépő is elbír. Az alap
    a config `trading.deviation_points`-ból jön (per-pár felülírható a
    `pairs.<sym>.deviation_points`-szal), alapértéke `DEFAULT_DEVIATION_POINTS`."""
    base = DEFAULT_DEVIATION_POINTS
    if cfg:
        try:
            base = int((cfg.get("trading") or {}).get(
                "deviation_points", DEFAULT_DEVIATION_POINTS))
            pair = (cfg.get("pairs") or {}).get(symbol)
            if isinstance(pair, dict) and pair.get("deviation_points") is not None:
                base = int(pair["deviation_points"])
        except (TypeError, ValueError):
            base = DEFAULT_DEVIATION_POINTS
    if info is None:
        info = mt5.symbol_info(symbol)
    spread = int(getattr(info, "spread", 0) or 0) if info is not None else 0
    return max(1, base, spread)


def normalize_price(price: float, info) -> float:
    """Az ár a szimbólum RÁCSÁRA igazítva: `trade_tick_size` többszöröse, a
    `digits` szerint kerekítve. A fix 5 tizedes helyett — az indexeknél/GOLD-nál
    (digits 1-2) az fölösleges pontosság volt, a nem tizedes tick-méretű
    szimbólumoknál (pl. 0.05 lépés) pedig érvénytelen árat adott."""
    if info is None:
        return round(float(price), 5)
    digits = int(getattr(info, "digits", 5) or 5)
    tick   = float(getattr(info, "trade_tick_size", 0.0) or 0.0)
    p = float(price)
    if tick > 0:
        p = round(p / tick) * tick
    return round(p, digits)


def min_stop_price(info) -> float:
    """A bróker MINIMUM stop-távolsága ÁR-egységben (`trade_stops_level` × point).
    0.0, ha nincs korlát vagy nem elérhető az adat."""
    if info is None:
        return 0.0
    point = float(getattr(info, "point", 0.0) or 0.0)
    level = int(getattr(info, "trade_stops_level", 0) or 0)
    return max(0.0, level * point)


def enforce_min_sl_pips(sl_pips: float, tp_pips: float, info,
                        pip_size: float) -> tuple[float, float, bool]:
    """(sl_pips, tp_pips, tágítottunk-e) — az SL-táv felhúzva a bróker minimumára.

    Ha a számított SL közelebb van, mint a `trade_stops_level`, a bróker
    `10016 Invalid stops`-szal utasítja el a megbízást (a jel elveszik). Ilyenkor
    az SL-t a minimumra tágítjuk, ÉS a TP-t UGYANAZZAL az aránnyal — így az R:R
    változatlan marad.

    FONTOS: ezt a méretezés ELŐTT kell hívni. A nagyobb SL-táv kisebb lotot ad
    (`calc_lot`), tehát a kockázati keret ($) NEM nő — csak a stop kerül messzebb.
    Egy pont ráhagyás, hogy a határon álló érték se bukjon el."""
    if pip_size <= 0 or sl_pips <= 0:
        return sl_pips, tp_pips, False
    point = float(getattr(info, "point", 0.0) or 0.0) if info is not None else 0.0
    floor_price = min_stop_price(info)
    if floor_price <= 0:
        return sl_pips, tp_pips, False
    min_pips = (floor_price + point) / pip_size      # +1 pont ráhagyás
    if sl_pips >= min_pips:
        return sl_pips, tp_pips, False
    scale = min_pips / sl_pips
    return min_pips, tp_pips * scale, True

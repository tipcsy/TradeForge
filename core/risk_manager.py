"""
Portfólió szintű kockázatkezelés.

Alapelv: account × risk_pct = az összes slot EGYÜTTES kockázata.
  - Normál eset: lot = (teljes_cél / max_slots) / (sl_points × point_value)  → FLOOR-ra kerekítve
  - Kis számla (min_lot kényszer): effective_slots = ROUND(cél / tényleges_kockázat × max_slots)
"""

import math


def calc_sl_tp_points(atr_value: float, params: dict) -> tuple[float, float]:
    """SL és TP mérete PONTBAN, ATR alapján."""
    sl_points = atr_value / params.get("point_size", 0.0001) * params["sl_atr_mult"]
    tp_points = sl_points * params["tp_rr_ratio"]
    return sl_points, tp_points


def calc_swing_sl_tp_points(entry_price: float, direction: str, lows, highs,
                          params: dict, point_size: float, spread_points: float):
    """SL az utolsó N M1 gyertya SWINGJÉBŐL (ATR helyett, `sl_method="swing20"`):
      • BUY  → SL = a legalacsonyabb LOW − spread  (a támasz ALÁ),
      • SELL → SL = a legmagasabb HIGH + spread     (az ellenállás FÖLÉ).
    `sl_points` = |entry − SL_szint| / point_size; `tp_points` = sl_points × tp_rr_ratio (R marad).
    `lows`/`highs`: az M1 gyertyák low/high tömbje (az utolsó `sl_swing_bars` számít).
    None, ha degenerált (kevés adat, vagy a belépő a swingen túl → nem-pozitív SL)."""
    bars = int(params.get("sl_swing_bars", 20) or 20)
    if bars <= 0 or entry_price <= 0 or point_size <= 0:
        return None
    lo_w = list(lows)[-bars:]
    hi_w = list(highs)[-bars:]
    if not lo_w or not hi_w:
        return None
    sp    = float(spread_points) * point_size
    tp_rr = float(params.get("tp_rr_ratio", 1.5))
    if direction == "BUY":
        sl_level = min(lo_w) - sp
        sl_points  = (entry_price - sl_level) / point_size
    else:
        sl_level = max(hi_w) + sp
        sl_points  = (sl_level - entry_price) / point_size
    if not (sl_points > 0):
        return None
    return sl_points, sl_points * tp_rr


def calc_lot(
    balance: float,
    sl_points: float,
    pair_cfg: dict,
    trading_cfg: dict,
    effective_slots: int,
) -> float:
    """
    Lot méret számítása egy slothoz.
    Mindig FLOOR-ra kerekít (soha nem lép túl a kockázaton lot oldalon).
    """
    risk_pct      = trading_cfg["account_risk_pct"]
    total_risk    = balance * risk_pct
    risk_per_slot = total_risk / effective_slots

    # 1 lot × 1 PONT mozgás értéke a SZÁMLA devizájában (a név „usd" része
    # történeti — a bróker trade_tick_value-ja mindig a számla devizájában van).
    # Élesben a motor ezt MT5-ből frissíti.
    point_value  = pair_cfg["pv1_point"]
    # min_lot/lot_step hiányozhat (pl. GUI-ból hozzáadott vagy hiányos config) →
    # biztonságos alapérték, hogy az optimalizálás/backteszt ne szálljon el csendben.
    lot_step   = pair_cfg.get("lot_step", 0.01)
    min_lot    = pair_cfg.get("min_lot", 0.01)
    max_lot    = pair_cfg.get("max_lot")     # a bróker volume_max-ja (None = nincs)

    if sl_points <= 0 or point_value <= 0:
        return min_lot

    raw_lot = risk_per_slot / (sl_points * point_value)
    lot = math.floor(raw_lot / lot_step) * lot_step
    lot = max(lot, min_lot)
    # A bróker FELSŐ korlátja: enélkül nagy egyenlegnél / szűk stopnál a számított
    # lot fölé mehetett, és a megbízás `10014 Invalid volume`-mal elbukott (a jel
    # némán elveszett). A vágás a kockázatot csak CSÖKKENTI.
    if max_lot:
        lot = min(lot, float(max_lot))
    return lot


def calc_effective_slots(
    balance: float,
    sl_points: float,
    pair_cfg: dict,
    trading_cfg: dict,
) -> int:
    """
    Ha a min_lot kockázat meghaladja a cél kockázatot slotanként,
    csökkenti az elérhető slotok számát arányosan (ROUND, min 1).
    """
    max_slots  = trading_cfg["max_open_slots"]
    risk_pct   = trading_cfg["account_risk_pct"]
    total_risk = balance * risk_pct

    point_value = pair_cfg["pv1_point"]
    min_lot   = pair_cfg.get("min_lot", 0.01)

    actual_risk = min_lot * sl_points * point_value

    if actual_risk <= 0:
        return max_slots

    slots = round(total_risk / actual_risk * max_slots)
    return max(1, min(slots, max_slots))


class SlotManager:
    """
    Globális slot kezelés: nyomon követi a nyitott és kockázatmentes pozíciókat.
    """

    def __init__(self, max_slots: int):
        self.max_slots = max_slots
        self._positions: dict[int, bool] = {}  # ticket → risk_free

    def occupied(self) -> int:
        """Valóban foglalt (nem kockázatmentes) slotok száma."""
        return sum(1 for rf in self._positions.values() if not rf)

    def free(self) -> int:
        return self.max_slots - self.occupied()

    def can_open(self) -> bool:
        return self.free() > 0

    def add(self, ticket: int):
        self._positions[ticket] = False

    def ensure(self, ticket: int) -> bool:
        """Nyomon követésbe vétel, ha még nem ismert — a MEGLÉVŐ kockázatmentes
        jelölést nem írja felül (ellentétben az `add`-del). Az utólag stratégiához
        rendelt (kézzel nyitott) pozíciók így nem maradnak ki a slot-számlálásból.
        True, ha most került be."""
        if ticket in self._positions:
            return False
        self._positions[ticket] = False
        return True

    def set_risk_free(self, ticket: int):
        if ticket in self._positions:
            self._positions[ticket] = True

    def remove(self, ticket: int):
        self._positions.pop(ticket, None)

    def is_risk_free(self, ticket: int) -> bool:
        return self._positions.get(ticket, False)

    def all_tickets(self) -> list[int]:
        return list(self._positions.keys())

"""
Portfólió szintű kockázatkezelés.

Alapelv: account × risk_pct = az összes slot EGYÜTTES kockázata.
  - Normál eset: lot = (teljes_cél / max_slots) / (sl_points × point_value)  → FLOOR-ra kerekítve
  - Kis számla (min_lot kényszer): effective_slots = ROUND(cél / tényleges_kockázat × max_slots)

⚠ A SLOT KOCKÁZATI KERET, NEM DARABSZÁM
---------------------------------------
A `SlotManager` sokáig minden pozíciót PONTOSAN 1 slotnak számolt, függetlenül
attól, mekkora kockázat volt benne. Kis számlán ez lyuk: ha a bróker `min_lot`-ja
nagyobb lotot kényszerít, mint amennyi a slot kockázati keretébe férne, a
pozíció túlkockáztat — és mégis csak 1 slotot foglal. Mért példa (981 EUR
egyenleg, `account_risk_pct` 1%, 4 slot → egy slot = 2,45 EUR):

    UsaTec  min_lot 0,2 → 12,36 EUR kockázat = a slot-keret 5,04-szerese
    GOLD    min_lot 0,01 → 10,91 EUR         = 4,45 slot
    Ger40   min_lot 0,25 →  9,00 EUR         = 3,67 slot

Négy ilyen UsaTec-pozíció szabályosnak LÁTSZOTT, és közben 5% volt kockázatban
1% helyett. Ezért a foglaltság mostantól SÚLYOZOTT:

    súly = pozíció_kockázata / (egyenleg × risk_pct / max_slots)

A `can_open(súly)` akkor enged, ha `foglalt_súly + súly ≤ max_slots`. Egyetlen
kivétel: ha egy pozíció súlya EGYMAGA nagyobb a teljes keretnél (a `min_lot`
miatt), akkor is nyitható — de csak ÜRES kerettel, vagyis elviszi az összes
slotot. E nélkül a UsaTec ezen a számlán soha nem lenne kereskedhető.

A súly TÖRT, nem egészre kerekített: a UsaInd 1,08-as súlya felfelé kerekítve
2 slotot enne el egy 8%-os túllépésért, ami feleslegesen szigorú.

A kockázatmentesre állított pozíció (`set_risk_free`) a TELJES súlyát
felszabadítja — ez már korábban is így volt, és pontosan illik a keret-modellhez
(nulla kockázat = nulla keret-fogyasztás).

⚠ A KÉT KORLÁT EGYÜTT ÉL — a keret SZŰKÍT, nem tágít
----------------------------------------------------
A súly-modell önmagában SZIMMETRIKUS lenne: ahol a `min_lot` a szándékoltnál
KISEBB kockázatot ad (UK100 0,60 · Fra40 0,67 slot), ott hatot is engedne négy
helyett. Ez nem cél — a `max_open_slots` a DARABSZÁMRA is korlát marad:

    nyitható  ⟺  darabszám < max_slots   ÉS   foglalt_súly + súly ≤ max_slots

Így a változtatás CSAK a túlkockáztatást zárja ki; ahol eddig is belefért a
kockázat, ott a viselkedés (és minden korábbi backteszt eredménye) változatlan.
"""

import math

# Lebegőpontos összeadás miatt a keret-ellenőrzés apró tűrést kap: e nélkül négy
# 0,25-ös súly összege 1,0000000000000002 lehet, és a negyedik belépő némán
# elmaradna.
_EPS = 1e-9


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


def slot_weight(risk_ccy: float, balance: float, trading_cfg: dict) -> float:
    """Egy pozíció SÚLYA slot-egységben: a kockázata / egy slot kockázati kerete.

    1.0 = pontosan annyit kockáztat, amennyit egy slot elbír. Ismeretlen/hibás
    bemenetnél 1.0 (a régi, darabszám-alapú viselkedés) — soha nem 0, mert az
    korlátlan nyitást engedne."""
    try:
        risk_pct = float(trading_cfg["account_risk_pct"])
        max_slots = int(trading_cfg["max_open_slots"])
    except (KeyError, TypeError, ValueError):
        return 1.0
    per_slot = float(balance) * risk_pct / max_slots if max_slots > 0 else 0.0
    if not (per_slot > 0) or not (risk_ccy > 0):
        return 1.0
    return float(risk_ccy) / per_slot


def fits_budget(occupied_weight: float, new_weight: float, max_slots: float) -> bool:
    """Belefér-e az új súly a keretbe? Lásd a modul fejlécét a szabályokért."""
    if new_weight <= 0:
        return True                      # nulla kockázat nem fogyaszt keretet
    if new_weight > max_slots:
        # A `min_lot` miatt egymaga túllóg a teljes kereten → csak ÜRES kerettel,
        # és akkor elviszi az összeset.
        return occupied_weight <= _EPS
    return occupied_weight + new_weight <= max_slots + _EPS


class SlotManager:
    """
    Globális slot kezelés: nyomon követi a nyitott és kockázatmentes pozíciókat.

    A foglaltság SÚLYOZOTT (lásd a modul fejlécét). ⚠ Nem a SÚLYT tároljuk, hanem
    a pozíció KOCKÁZATÁT a számla devizájában — a súly ebből és az ÉPPEN aktuális
    keretből számolódik. Enélkül a felületen állított `account_risk_pct` (vagy a
    növekvő egyenleg) után a már nyitott pozíciók súlya elavulna, és a motor
    máshogy számolna, mint amit a felület mutat.

    A kockázatot nem ismerő hívó (vagy a `set_budget` elmaradása) esetén a súly
    1.0 — vagyis a korábbi, darabszám-alapú viselkedés.
    """

    def __init__(self, max_slots: int):
        self.max_slots = max_slots
        self._positions: dict[int, bool] = {}   # ticket → risk_free
        self._risk: dict[int, float] = {}       # ticket → belépéskori 1R (deviza)
        self._per_slot: float = 0.0             # egy slot kerete (deviza)

    # ── keret ────────────────────────────────────────────────────────────────
    def set_budget(self, balance: float, trading_cfg: dict) -> float:
        """Egy slot kockázati keretének frissítése. Rendszeresen hívandó (az
        egyenleg változik), és MINDIG a súly-alapú döntések előtt."""
        try:
            pct = float(trading_cfg["account_risk_pct"])
            slots = int(trading_cfg["max_open_slots"])
        except (KeyError, TypeError, ValueError):
            return self._per_slot
        if slots > 0 and pct > 0 and balance > 0:
            self._per_slot = float(balance) * pct / slots
        return self._per_slot

    def weight_of(self, ticket: int) -> float:
        """A ticket súlya slot-egységben. 1.0, ha a kockázata vagy a keret
        ismeretlen — soha nem 0, mert az korlátlan nyitást engedne."""
        r = self._risk.get(ticket, 0.0)
        if r > 0 and self._per_slot > 0:
            return r / self._per_slot
        return 1.0

    def risk_of(self, ticket: int) -> float:
        return self._risk.get(ticket, 0.0)

    # ── foglaltság ───────────────────────────────────────────────────────────
    def occupied(self) -> float:
        """A ténylegesen lekötött keret slot-egységben (a nem kockázatmentes
        pozíciók súly-összege). TÖRT lehet."""
        return sum(self.weight_of(t)
                   for t, rf in self._positions.items() if not rf)

    def occupied_count(self) -> int:
        """A nem kockázatmentes pozíciók DARABSZÁMA — a `max_open_slots` erre is
        korlát marad (lásd a modul fejlécét)."""
        return sum(1 for rf in self._positions.values() if not rf)

    def occupied_risk(self) -> float:
        """A lekötött kockázat a számla devizájában (a felület ezt írja ki)."""
        return sum(self._risk.get(t, 0.0)
                   for t, rf in self._positions.items() if not rf)

    def free(self) -> float:
        return self.max_slots - self.occupied()

    def can_open(self, weight: float = 1.0) -> bool:
        """Mindkét korlát: darabszám ÉS kockázati keret."""
        if self.occupied_count() >= self.max_slots:
            return False
        return fits_budget(self.occupied(), weight, self.max_slots)

    def can_open_risk(self, risk_ccy: float) -> bool:
        """Kényelmi alak: a kockázatból maga számolja a súlyt (a `set_budget`
        által beállított kerettel)."""
        w = (risk_ccy / self._per_slot
             if risk_ccy > 0 and self._per_slot > 0 else 1.0)
        return self.can_open(w)

    # ── nyilvántartás ────────────────────────────────────────────────────────
    def add(self, ticket: int, risk_ccy: float = 0.0):
        self._positions[ticket] = False
        self._risk[ticket] = float(risk_ccy or 0.0)

    def ensure(self, ticket: int, risk_ccy: float = 0.0) -> bool:
        """Nyomon követésbe vétel, ha még nem ismert — a MEGLÉVŐ kockázatmentes
        jelölést nem írja felül (ellentétben az `add`-del). Az utólag stratégiához
        rendelt (kézzel nyitott) pozíciók így nem maradnak ki a slot-számlálásból.
        True, ha most került be."""
        if ticket in self._positions:
            return False
        self._positions[ticket] = False
        self._risk[ticket] = float(risk_ccy or 0.0)
        return True

    def set_risk_free(self, ticket: int):
        if ticket in self._positions:
            self._positions[ticket] = True

    def remove(self, ticket: int):
        self._positions.pop(ticket, None)
        self._risk.pop(ticket, None)

    def is_risk_free(self, ticket: int) -> bool:
        return self._positions.get(ticket, False)

    def all_tickets(self) -> list[int]:
        return list(self._positions.keys())

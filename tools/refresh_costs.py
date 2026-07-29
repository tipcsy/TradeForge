"""
Kereskedési KÖLTSÉGEK kimérése a saját MT5-előzményből a `config.json`-ba.

Miért
----
A backteszt a v1.65.9 óta modellezi a jutalékot és a swapot, de a számokat nem
találja ki: a `pairs.<sym>.commission_per_lot` / `swap_long_per_lot` /
`swap_short_per_lot` kulcsokból dolgozik. Hiányzó kulcs → 0.0, azaz a régi
(költségmentes, tehát OPTIMISTA) eredmény.

Ez az eszköz a SAJÁT SZÁMLÁD valóságából tölti fel őket:

  • **Jutalék** — a lezárt deal-ök `commission` mezőjéből, lotra vetítve. Ez a
    tényleges, oda-vissza jutalék a te számladevizádban — nem a bróker
    marketing-táblázata.
  • **Swap** — elsősorban a `symbol_info.swap_long/swap_short`-ból (a MOST
    érvényes napi terhelés), a `swap_mode` figyelembevételével. Ahol a mód nem
    egyértelműen átváltható, ott a MÉRT előzményből (a pozíciókra terhelt swap /
    lot / éjszaka), ha van elég mintád.
  • **3×-os nap** — a `symbol_info.swap_rollover3days`-ből.

Használat
---------
    python tools/refresh_costs.py                 # csak MEGMUTATJA
    python tools/refresh_costs.py --write         # be is írja a config.json-ba
    python tools/refresh_costs.py --days 180      # ennyi nap előzményből mér

Alapból NEM ír. A `--write` KIZÁRÓLAG a fenti négy kulcsot érinti.

FIGYELEM: a beírás után a backteszt/optimalizálás eredménye ROMLANI fog — nem
azért, mert elromlott valami, hanem mert eddig egy költségmentes világot mért. A
korábbi optimalizált paraméterek egy olcsóbb világra lettek illesztve.
"""

import json
import sys
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CFG_PATH = ROOT / "config.json"

# A `symbol_info.swap_mode` értékei, amiket biztonságosan át tudunk váltani
# számla-devizára. Az MQL5 ENUM_SYMBOL_SWAP_MODE-ból:
SWAP_MODE_POINTS = 1          # pontban → ár-egység → számladeviza a tick-értékkel
SWAP_MODE_CURRENCY_SYMBOL = 2  # a szimbólum bázisdevizájában
SWAP_MODE_CURRENCY_MARGIN = 3  # margin-devizában
SWAP_MODE_CURRENCY_DEPOSIT = 4  # MÁR a számla devizájában → közvetlenül használható
SWAP_MODE_INTEREST_CURRENT = 5  # ÉVES KAMAT% a pozíció AKTUÁLIS értékére (CFD-k)

# Az INTEREST módok banki éve (MQL5: „standard bank year is 360 days").
BANK_YEAR_DAYS = 360

MIN_SWAP_SAMPLES = 3          # ennyi mért éjszaka alatt nem hiszünk a mérésnek


def mt5_day_to_weekday(mt5_day: int) -> int:
    """MT5 `ENUM_DAY_OF_WEEK` (VASÁRNAP=0 … SZOMBAT=6) → Python `weekday()`
    (HÉTFŐ=0 … VASÁRNAP=6).

    Enélkül a `swap_rollover3days` nyers értéke rossz napot jelölne: az indexeknél
    az 5 PÉNTEKET jelent, Python-indexben viszont az 5 SZOMBAT — a 3×-os swap
    sosem esett volna egy tényleges kereskedési napra."""
    return (int(mt5_day) - 1) % 7


def _point_size(info) -> float:
    """A szimbólum PONT-mérete. A `symbol_info.point` maga — nincs digits-alapú
    szorzás, mert az a PIP-et adná (5 tizedesnél ×10, 2-3 tizedesnél ×100).
    Tartalék, ha a config `point_size`-a hiányzik."""
    return float(getattr(info, "point", 0.0) or 0.0)


def measure_from_history(mt5, mc, days: int) -> dict:
    """{szimbólum: {"comm_per_lot": x, "swap_per_lot_night": y|None, "n": db}}
    a lezárt deal-ökből. A jutalék ODA-VISSZA (a nyitó és a záró deal együtt)."""
    frm = datetime.now(timezone.utc) - timedelta(days=days)
    to = datetime.now(timezone.utc) + timedelta(days=1)
    with mc.MT5_LOCK:
        deals = mt5.history_deals_get(frm, to)
    if not deals:
        return {}

    # pozíciónként: össz-jutalék, össz-swap, lot, nyitó/záró idő
    pos = defaultdict(lambda: {"comm": 0.0, "swap": 0.0, "lot": 0.0,
                               "sym": None, "t_in": None, "t_out": None})
    for d in deals:
        if d.entry == mt5.DEAL_ENTRY_IN:
            p = pos[d.position_id]
            p["sym"] = d.symbol
            p["lot"] = max(p["lot"], float(d.volume or 0.0))
            p["t_in"] = int(d.time)
        elif d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY):
            p = pos[d.position_id]
            p["sym"] = p["sym"] or d.symbol
            p["t_out"] = int(d.time)
        else:
            continue
        pos[d.position_id]["comm"] += float(getattr(d, "commission", 0.0) or 0.0)
        pos[d.position_id]["swap"] += float(getattr(d, "swap", 0.0) or 0.0)

    agg = defaultdict(lambda: {"comm": 0.0, "lot": 0.0, "swap": 0.0,
                               "nights": 0.0, "n": 0})
    from core import trade_costs as tc
    for p in pos.values():
        if not p["sym"] or p["lot"] <= 0 or p["t_in"] is None or p["t_out"] is None:
            continue
        a = agg[p["sym"]]
        a["comm"] += abs(p["comm"])
        a["lot"] += p["lot"]
        a["n"] += 1
        nights = tc.nights_held(p["t_in"], p["t_out"], None)   # 3×-t itt nem súlyozunk
        if nights > 0:
            a["swap"] += p["swap"]
            a["nights"] += nights * p["lot"]

    out = {}
    for sym, a in agg.items():
        out[sym] = {
            "comm_per_lot": (a["comm"] / a["lot"]) if a["lot"] > 0 else None,
            "swap_per_lot_night": (a["swap"] / a["nights"]
                                   if a["nights"] >= MIN_SWAP_SAMPLES else None),
            "n": a["n"],
        }
    return out


def swap_from_symbol(mt5, info, point_size: float) -> tuple:
    """(swap_long, swap_short) a SZÁMLA devizájában, 1.0 lotra/éjszaka — vagy
    (None, None), ha a `swap_mode` nem váltható át megbízhatóan."""
    mode = int(getattr(info, "swap_mode", 0) or 0)
    sl = float(getattr(info, "swap_long", 0.0) or 0.0)
    ss = float(getattr(info, "swap_short", 0.0) or 0.0)
    tv = float(getattr(info, "trade_tick_value", 0.0) or 0.0)
    ts = float(getattr(info, "trade_tick_size", 0.0) or 0.0)
    pt = float(getattr(info, "point", 0.0) or 0.0)

    if mode == SWAP_MODE_CURRENCY_DEPOSIT:
        return sl, ss                      # már a számla devizájában

    if mode == SWAP_MODE_POINTS:
        if tv > 0 and ts > 0 and pt > 0:
            per_point = tv / ts * pt       # 1 pont értéke 1 lotra, számladevizában
            return sl * per_point, ss * per_point
        return None, None

    if mode == SWAP_MODE_INTEREST_CURRENT:
        # A swap ÉVES KAMAT% a pozíció aktuális értékére (a CFD-k tipikus módja):
        #     éjszakai swap = ár × lot × kontraktus × (kamat% / 100 / 360)
        # a szimbólum PROFIT-devizájában. Számladevizára a `tick_value/tick_size`
        # arány vált (az MT5 a tick-értéket MÁR a számla devizájában adja), és
        # ebben a kontraktus-méret kiesik:
        #     per_lot_night = ár × (kamat% / 100 / 360) × tick_value / tick_size
        #
        # FIGYELEM: ez az AKTUÁLIS árra vonatkozik, tehát PILLANATKÉP — ugyanúgy
        # frissíteni kell időnként, mint a `pv1_point`-t.
        with_price = _mid_price(mt5, info)
        if with_price and tv > 0 and ts > 0:
            f = with_price * (tv / ts) / (100.0 * BANK_YEAR_DAYS)
            return sl * f, ss * f
        return None, None

    return None, None


def _mid_price(mt5, info) -> float:
    """Az aktuális közép-ár (a kamat-alapú swap alapja). 0.0, ha nincs tick."""
    tick = mt5.symbol_info_tick(info.name)
    if tick and tick.bid and tick.ask:
        return (float(tick.bid) + float(tick.ask)) / 2.0
    return float(getattr(info, "bid", 0.0) or 0.0)


def main() -> int:
    write = "--write" in sys.argv
    days = 365
    if "--days" in sys.argv:
        try:
            days = int(sys.argv[sys.argv.index("--days") + 1])
        except (IndexError, ValueError):
            pass

    from core import mt5_connector as mc
    from strategy.settings import load_config

    cfg = load_config(CFG_PATH)
    if not mc.connect(cfg):
        print("Nem sikerult csatlakozni az MT5-hoz.")
        return 1
    import MetaTrader5 as mt5

    raw = json.loads(CFG_PATH.read_text(encoding="utf-8"),
                     object_pairs_hook=OrderedDict)
    pairs = raw.get("pairs", {})

    rows = []
    try:
        measured = measure_from_history(mt5, mc, days)
        for symbol, pc in pairs.items():
            if not isinstance(pc, dict):
                continue
            with mc.MT5_LOCK:
                mt5.symbol_select(symbol, True)
                info = mt5.symbol_info(symbol)
            if info is None:
                rows.append((symbol, "-", "-", "-", "nincs ilyen szimbolum"))
                continue

            m = measured.get(symbol) or {}
            comm = m.get("comm_per_lot")
            src_c = f"merve ({m.get('n', 0)} kotes)" if comm is not None else "nincs adat"
            if comm is None:
                comm = float(pc.get("commission_per_lot", 0.0) or 0.0)
                src_c = "valtozatlan"

            pip = float(pc.get("point_size") or _point_size(info))
            sw_l, sw_s = swap_from_symbol(mt5, info, pip)
            src_s = "symbol_info"
            if sw_l is None:
                # nem atvalthato mod -> a MERT ertek (mindket iranyra ugyanaz)
                mv = m.get("swap_per_lot_night")
                if mv is not None:
                    sw_l = sw_s = mv
                    src_s = "merve"
                else:
                    sw_l = float(pc.get("swap_long_per_lot", 0.0) or 0.0)
                    sw_s = float(pc.get("swap_short_per_lot", 0.0) or 0.0)
                    src_s = "valtozatlan (ismeretlen swap_mode)"

            w3 = getattr(info, "swap_rollover3days", None)
            rows.append((symbol, f"{comm:.2f}", f"{sw_l:.3f}", f"{sw_s:.3f}",
                         f"{src_c} / {src_s}"))

            if write:
                pc["commission_per_lot"] = round(float(comm), 4)
                pc["swap_long_per_lot"] = round(float(sw_l), 4)
                pc["swap_short_per_lot"] = round(float(sw_s), 4)
                if w3 is not None:
                    # MT5 ENUM_DAY_OF_WEEK → Python weekday() (lásd a fenti helper)
                    pc["swap_3x_weekday"] = mt5_day_to_weekday(w3)
    finally:
        mc.disconnect()

    w = max((len(r[0]) for r in rows), default=8)
    print(f"\n{'szimbolum'.ljust(w)}  {'jutalek/lot':>11}  {'swap_long':>10}  "
          f"{'swap_short':>10}  forras")
    print("-" * (w + 50))
    for r in rows:
        print(f"{r[0].ljust(w)}  {r[1]:>11}  {r[2]:>10}  {r[3]:>10}  {r[4]}")

    if not write:
        print("\nNEM irtam semmit. A beirashoz:")
        print("    python tools/refresh_costs.py --write")
        return 0

    raw["pairs"] = pairs
    CFG_PATH.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print("\nconfig.json FRISSITVE.")
    print("FIGYELEM: a backteszt/optimalizalas eredmenye mostantol ROSSZABB lesz — "
          "nem romlott el semmi, eddig egy koltsegmentes vilagot mert. "
          "Az optimalizalast erdemes ujrafuttatni.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Pip-érték és lot-korlátok FRISSÍTÉSE a brókertől a `config.json`-ba.

Miért kell
----------
A `pairs.<sym>.pv1_usd` (1 lot × 1 pip értéke a SZÁMLA devizájában) egyetlen
PILLANATKÉP arról, amikor az instrumentumot felvetted. Két baja lehet:

  • **Elavult.** Nem számla-devizás instrumentumnál (EUR-számlán minden USD/GBP/
    JPY-alapú) az érték az ÁRFOLYAMMAL sodródik, tehát a tényleges kockázat
    eltér a beállított %-tól.
  • **Kézzel beírt.** A configban több index kerek `1.0`-val szerepel — UK100-on
    ez ~15% ALULbecslés (túl nagy lot), UsaTec/UsaInd-en ~14% FELÜLbecslés.

Az ÉLŐ motor a v1.65.6 óta MT5-ből frissíti a pip-értéket minden méretezéskor,
tehát élesben helyesen köt akkor is, ha a config elavult. A BACKTESZT és az
OPTIMALIZÁLÁS viszont a configból dolgozik — ezért érdemes ezt időnként lefuttatni,
különben a mért eredmény más mérettel számol, mint az él.

Használat
---------
    python tools/refresh_pip_values.py            # csak MEGMUTATJA az eltéréseket
    python tools/refresh_pip_values.py --write    # be is írja a config.json-ba

Alapból NEM ír (a config.json a te élő beállításod). A `--write` a
`pv1_usd`, `min_lot`, `lot_step`, `max_lot` és `backtest_spread_pips` mezőket
frissíti; minden mást (engedélyezés, órák, stratégiák, run_state) érintetlenül hagy.
"""

import json
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CFG_PATH = ROOT / "config.json"

# Ennyi relatív eltérés fölött tekintjük „érdemi" változásnak (a kijelzéshez).
SIGNIFICANT = 0.02


def _pip_size(info) -> float:
    """A pip mérete a szimbólum tizedeseiből — ugyanaz a szabály, amit a felület
    használ új instrumentum felvételekor (a config `pip_size`-a a mérvadó, ez csak
    tartalék, ha az hiányzik)."""
    d = info.digits
    if d in (4, 5):
        return info.point * 10
    if d in (2, 3):
        return info.point * 100
    return info.point


def main() -> int:
    write = "--write" in sys.argv

    from core import mt5_connector, order_exec
    from strategy.settings import load_config

    cfg = load_config(CFG_PATH)
    if not mt5_connector.connect(cfg):
        print("Nem sikerult csatlakozni az MT5-hoz.")
        return 1

    import MetaTrader5 as mt5

    raw = json.loads(CFG_PATH.read_text(encoding="utf-8"),
                     object_pairs_hook=OrderedDict)
    pairs = raw.get("pairs", {})

    rows, changed = [], 0
    try:
        for symbol, pc in pairs.items():
            if not isinstance(pc, dict):
                continue
            with mt5_connector.MT5_LOCK:
                mt5.symbol_select(symbol, True)
                info = mt5.symbol_info(symbol)
            if info is None:
                rows.append((symbol, "—", "—", "NINCS ilyen szimbolum a brokerne1"))
                continue

            pip_size = float(pc.get("pip_size") or _pip_size(info))
            pv1_new  = order_exec.pip_value(symbol, pip_size, info)
            vb       = order_exec.volume_bounds(info)
            if pv1_new is None:
                rows.append((symbol, pc.get("pv1_usd"), "—", "nincs tick-ertek"))
                continue

            pv1_old = float(pc.get("pv1_usd") or 0.0)
            diff = (abs(pv1_new - pv1_old) / pv1_old) if pv1_old > 0 else 1.0
            note = ""
            if diff > SIGNIFICANT:
                note = f"ELTERES {diff*100:+.1f}%"
                changed += 1
            rows.append((symbol, f"{pv1_old:.4f}", f"{pv1_new:.4f}", note))

            if write:
                pc["pv1_usd"] = round(pv1_new, 4)
                if vb:
                    vmin, vmax, vstep = vb
                    pc["min_lot"]  = vmin
                    pc["lot_step"] = vstep
                    if vmax != float("inf"):
                        pc["max_lot"] = vmax
                if pip_size > 0 and info.point > 0:
                    pc["backtest_spread_pips"] = round(
                        info.spread * info.point / pip_size, 1)
    finally:
        mt5_connector.disconnect()

    w = max((len(r[0]) for r in rows), default=8)
    print(f"\n{'szimbolum'.ljust(w)}  {'config':>10}  {'broker':>10}  megjegyzes")
    print("-" * (w + 36))
    for sym, old, new, note in rows:
        print(f"{str(sym).ljust(w)}  {str(old):>10}  {str(new):>10}  {note}")

    if not write:
        print(f"\n{changed} instrumentumnal erdemi ({SIGNIFICANT*100:.0f}% folotti) "
              f"elteres. NEM irtam semmit — a beirashoz:")
        print("    python tools/refresh_pip_values.py --write")
        return 0

    raw["pairs"] = pairs
    CFG_PATH.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(f"\nconfig.json FRISSITVE ({changed} erdemi elteres).")
    print("A backteszt/optimalizalas mostantol a helyes merettel szamol — a korabbi "
          "eredmenyek ehhez kepest eltolodhatnak.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

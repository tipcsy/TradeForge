"""
Fix volatilitás-mérce (`atr_avg_ref`) BACKFILL a meglévő optimalizált
paraméterekbe — újraoptimalizálás NÉLKÜL.

Miért: a `bt_entry` volatilitás-szűrője eddig az ADATABLAKBÓL számolt ATR-átlagot
(baseline) használta → a backtest (teljes előzmény), a chart-viz (~30 nap) és az él
(friss bárok) MÁS mércét kapott, így eltérő kötéseket adtak. A fix mérce EGY szám,
amit mindhárom használ → egyeznek, és a backtest reprodukálható.

Ez a script minden mentett params-fájlhoz kiszámolja a mentett `atr_period`-del az
ATR átlagát a letöltött adaton, és `atr_avg_ref`-ként elmenti. Az optimalizálás
mostantól magától is elmenti ezt; ez csak a MEGLÉVŐ készleteket tölti fel.

Futtatás:
    python tools/backfill_atr_avg_ref.py            # csak a hiányzókat
    python tools/backfill_atr_avg_ref.py --force     # a meglévőket is újraszámolja
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.params_store import PARAMS_DIR
from strategy import get_strategy_by_name
from strategy.settings import load_config
from trading.backtest import load_data


def _compute_ref(strategy, df_m15, df_m1, params, point_size):
    """Az adott (mentett) paraméterekkel az ATR ablak-átlaga — EGY szám, vagy None."""
    m15_ind, _ = strategy.bt_indicators(
        df_m15, df_m1, {**params, "point_size": point_size})
    if "atr_avg" in m15_ind.columns and len(m15_ind):
        av = float(m15_ind["atr_avg"].iloc[0])
        return av if av > 0 else None
    return None


def main():
    ap = argparse.ArgumentParser(description="atr_avg_ref backfill a mentett paraméterekbe.")
    ap.add_argument("--force", action="store_true",
                    help="A már meglévő atr_avg_ref-et is újraszámolja.")
    args = ap.parse_args()

    cfg = load_config(ROOT / "config.json")
    pairs = cfg.get("pairs", {})

    done = skipped = failed = 0
    # optimized_params/<strategia>/<SZIMBOLUM>.json
    for strat_dir in sorted(p for p in PARAMS_DIR.iterdir() if p.is_dir()):
        strat_name = strat_dir.name
        try:
            strategy = get_strategy_by_name(strat_name)
        except Exception as ex:
            print(f"[{strat_name}] ismeretlen stratégia, kihagyva ({ex})")
            continue

        for pf in sorted(strat_dir.glob("*.json")):
            if pf.stem.endswith("_hours"):
                continue
            sym = pf.stem
            # csak a jelenleg a configban lévő párok (a szellemeket kihagyjuk)
            if sym not in pairs or not isinstance(pairs[sym], dict):
                print(f"[{strat_name}] {sym}: nincs a configban, kihagyva")
                skipped += 1
                continue
            try:
                data = json.loads(pf.read_text(encoding="utf-8"))
            except Exception as ex:
                print(f"[{strat_name}] {sym}: olvasási hiba ({ex})")
                failed += 1
                continue
            params = data.get("params")
            if not isinstance(params, dict):
                print(f"[{strat_name}] {sym}: nincs 'params', kihagyva")
                skipped += 1
                continue
            if params.get("atr_avg_ref") and not args.force:
                print(f"[{strat_name}] {sym}: már van atr_avg_ref="
                      f"{params['atr_avg_ref']:.4g}, kihagyva")
                skipped += 1
                continue

            df_m15, df_m1 = load_data(sym)
            if df_m15 is None or df_m1 is None:
                print(f"[{strat_name}] {sym}: nincs letöltött adat, kihagyva")
                skipped += 1
                continue
            try:
                point_size = float(pairs[sym].get("point_size", 0.0001))
                ref = _compute_ref(strategy, df_m15, df_m1, params, point_size)
            except Exception as ex:
                print(f"[{strat_name}] {sym}: számítási hiba ({ex})")
                failed += 1
                continue
            if ref is None:
                print(f"[{strat_name}] {sym}: nincs atr_avg (a stratégia nem ad) — kihagyva")
                skipped += 1
                continue

            params["atr_avg_ref"] = ref
            tmp = pf.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str),
                           encoding="utf-8")
            tmp.replace(pf)
            print(f"[{strat_name}] {sym}: atr_avg_ref = {ref:.4g}  -> mentve")
            done += 1

    print(f"\nKész. Mentve: {done} | Kihagyva: {skipped} | Hiba: {failed}")


if __name__ == "__main__":
    main()

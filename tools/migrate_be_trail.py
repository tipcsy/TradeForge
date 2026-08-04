"""EGYSZERI migráció (v1.96.0): BE + trailing → a kockázatcsökkentő modulba.

A `breakeven_pct`, `trail_activation_atr` és `trail_distance_atr` a közös
VÉGREHAJTÁSI configból (`data/execution_params/<SYM>.json`) átkerül a per-pár
KOCKÁZATCSÖKKENTŐ állapotba (`data/risk_mode.json`).

MIÉRT KELL EZ A LÉPÉS: a három érték páronként HANGOLT (a `wpr_sma` korábbi
optimalizálásaiból seedelve, lásd „Változtatás 2026-07-30-3"). Ha csak a kódot
írnánk át, minden pár némán a modul-alapértékre esne vissza (0,5 / 0,5 / 0,4) —
azaz a BE és a trailing viselkedése ÉLESBEN megváltozna. Ez a szkript ezt előzi
meg: az értékek pontosan ugyanazok maradnak, csak máshol laknak.

Idempotens: ami már át van írva (nincs a régi fájlban), azt nem bántja.
Alapból SZÁRAZ futás — ténylegesen írni a `--apply` kapcsolóval kell.

    python tools/migrate_be_trail.py           # mit tenne?
    python tools/migrate_be_trail.py --apply   # meg is teszi
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import execution_params as _execp     # noqa: E402
from core import rr_state as _rrs               # noqa: E402


def main(apply: bool = False) -> int:
    files = sorted(_execp.EXECUTION_DIR.glob("*.json"))
    if not files:
        print("Nincs execution_params fájl — nincs mit migrálni.")
        return 0

    _rrs.load()
    moved, skipped = [], []
    for p in files:
        symbol = p.stem
        vals = _execp.read_migrated(symbol)
        if not vals:
            skipped.append(symbol)
            continue
        moved.append((symbol, vals))

    print(f"{'ÉLES FUTÁS' if apply else 'SZÁRAZ FUTÁS (nem ír)'} — "
          f"{len(moved)} pár migrálandó, {len(skipped)} már kész/üres\n")
    if moved:
        print(f"{'symbol':10} {'breakeven_pct':>14} {'trail_act_atr':>14} {'trail_dist_atr':>15}")
        for symbol, v in moved:
            print(f"{symbol:10} {v.get('breakeven_pct', float('nan')):14.2f} "
                  f"{v.get('trail_activation_atr', float('nan')):14.2f} "
                  f"{v.get('trail_distance_atr', float('nan')):15.2f}")
    if skipped:
        print(f"\nKihagyva (nincs benne a három kulcs): {', '.join(skipped)}")

    if not apply:
        print("\nA tényleges írás: python tools/migrate_be_trail.py --apply")
        return 0

    for symbol, vals in moved:
        # 1) az értékek a per-pár kockázatcsökkentő állapotba (kalibrációs kulcsok)
        _rrs._set(symbol, **vals)
        # 2) a régi fájlból kikerülnek — a `save_execution_params` már csak a
        #    megmaradó három kulcsot írja ki, tehát elég újramenteni.
        keep = _execp.load_execution_params(symbol, {})
        _execp.save_execution_params(symbol, keep)
        print(f"  ✓ {symbol}")

    print(f"\nKész: {len(moved)} pár átírva "
          f"({_rrs.PATH.name} + data/execution_params/).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(apply="--apply" in sys.argv))

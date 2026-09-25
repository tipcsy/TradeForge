"""
A volatilitás-kapu befagyasztott mércéje (`atr_avg_ref`) — kitöltés vagy
újramérés az INSTRUMENTUM fájljában (`data/execution_params/<SYM>.json`).

v3.103.0 óta a mérce az instrumentumé, nem a stratégia-készleté: az M15
ATR(`atr_period`) átlaga a teljes letöltött előzményen
(`gates.vol_baseline.calibrate`). Ugyanezt a Volatilitás-kapu ablakának
„Mérce újramérése" gombja is megcsinálja párosával; ez a szkript tömegesen.

⚠ Csak azokat a párokat nézi, ahol van küszöb (`atr_min_pct`/`atr_max_pct`):
küszöb nélkül a mérce semmit nem jelent. A `--force` a MEGLÉVŐ mércét is
felülírja — ezzel a küszöbök jelentése is elmozdul (együtt kalibráltak).

Futtatás:
    python tools/backfill_atr_avg_ref.py            # csak a hiányzókat
    python tools/backfill_atr_avg_ref.py --force     # a meglévőket is újraméri
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd                                          # noqa: E402

from core import execution_params as _ep                    # noqa: E402
from core.i18n import t as _t                                # noqa: E402
from gates import vol_baseline as _vb                        # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=_t("cli.backfill_atr_avg_ref.atr_avg_ref_backfill_a_mentett"))
    ap.add_argument("--force", action="store_true",
                    help=_t("cli.backfill_atr_avg_ref.a_mar_meglevo_atr_avg_ref_et_i"))
    args = ap.parse_args()

    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    done = skipped = 0
    for sym, pc in sorted((cfg.get("pairs") or {}).items()):
        if not isinstance(pc, dict):
            continue
        prm = _ep.load_execution_params(sym, cfg)
        if not (prm.get("atr_min_pct") or prm.get("atr_max_pct")):
            continue
        if prm.get("atr_avg_ref") and not args.force:
            print(f"{sym}: már van mérce ({prm['atr_avg_ref']:.6g}), kihagyva")
            skipped += 1
            continue
        f = ROOT / "data" / "m15" / f"{sym}.parquet"
        if not f.exists():
            print(f"{sym}: nincs letöltött M15 előzmény, kihagyva")
            skipped += 1
            continue
        ref = _vb.calibrate(pd.read_parquet(f), int(prm.get("atr_period", 14)))
        if ref is None:
            print(f"{sym}: nincs érvényes ATR, kihagyva")
            skipped += 1
            continue
        _ep.save_execution_params(sym, {"atr_avg_ref": ref})
        print(f"{sym}: atr_avg_ref {prm.get('atr_avg_ref')} → {ref:.6g}")
        done += 1
    print(f"\nKész. Mentve: {done} | Kihagyva: {skipped}")


if __name__ == "__main__":
    main()

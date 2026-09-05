"""AZ OPTIMALIZALO NEM LATHATJA A HOLDOUTOT — or a legdragabb hibafajta ellen.

⚠ MI TORTENT (2026-09-05). A `ml/optimizer.py` fejlece ezt igeri:

    1. TRAIN adat (history_start -> test_start_date)
    3. TEST adat (test_start_date -> ma): out-of-sample validalas

A `grid` es a `random` ag tartotta is — megkapjak a `test_start`-ot. Az OPTUNA
ag viszont a TELJES szeletet kapta, es a walk-forward NEGY ablakabol HAROM a
deklaralt holdoutban tesztelt:

    train 2025-01-01 · test_start 2026-05-01
    Ablak 2: TEST 2026-03-04 -> 2026-05-04   <- a holdoutban
    Ablak 3: TEST 2026-05-04 -> 2026-07-04   <- a holdoutban
    Ablak 4: TEST 2026-07-04 -> 2026-09-04   <- a holdoutban

Utana UGYANEZEN a szakaszon futott a „validalas", es abbol lett a mentett
`test_summary`. Vagyis a jelentett OOS-minoseg olyan adaton merodott, amit a
kereses mar latott.

⚠ MIERT EZ A LEGDRAGABB HIBAFAJTA. Nem osszeomlast okoz, hanem HITELESIT egy
merest, ami nem igaz. A projekt ezt mar egyszer megmerte: a szennyezett
OOS-szamok **2,51x-esre** fujtak fel.

Ez a teszt HAROM dolgot orzi:
  1. a walk-forward ablakok nem erhetnek a `test_start` moge,
  2. az optuna ag TENYLEG levagja az OOS-szeletet a kereses elol,
  3. a VALIDALAS viszont tovabbra is a teljes adatot kapja (kulonben nem lenne
     mivel validalni).
"""
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog  # noqa: E402
applog.harden_console()

import pandas as pd  # noqa: E402
import numpy as np   # noqa: E402
from ml.optimizer import _walk_forward_windows  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


def _adat(tol, ig):
    idx = pd.date_range(tol, ig, freq="15min", tz="UTC")
    ar = np.linspace(100.0, 110.0, len(idx))
    return pd.DataFrame({"open": ar, "high": ar + 1, "low": ar - 1, "close": ar},
                        index=idx)


TEST_START = pd.Timestamp("2026-05-01", tz="UTC")
TELJES = _adat("2025-01-01", "2026-09-04")
VAGOTT = TELJES[TELJES.index < TEST_START]

# ── 1. A HIBA REPRODUKALASA: a teljes adaton BELELOG ────────────────────
# ⚠ Ez SZANDEKOSAN a rossz viselkedest allitja — ha valaki „megjavitja" a
# `_walk_forward_windows`-t ugy, hogy magatol kerulje a holdoutot, ez a sor
# szol. A megoldas az ADAT levagasa, nem az ablak-epito okoskodasa.
_w_teljes = _walk_forward_windows(TELJES, 4, 6, 2)
_belelog = [w for w in _w_teljes if w["test_end"] > TEST_START]
check("a TELJES adaton a walk-forward beleer a holdoutba (a hiba)",
      len(_belelog) > 0, f"{len(_belelog)}/{len(_w_teljes)} ablak")

# ── 2. A JAVITAS: a vagott adaton EGY ablak sem er tul ───────────────────
_w = _walk_forward_windows(VAGOTT, 4, 6, 2)
check("a vagott adaton EGYETLEN ablak sem er a test_start moge",
      all(w["test_end"] <= TEST_START for w in _w),
      f"{len(_w)} ablak, utolso vege {str(max(w['test_end'] for w in _w))[:10]}")
check("...es mind a NEGY ablak elfer (nem veszitunk validalast)",
      len(_w) == 4, f"{len(_w)} ablak")
check("az ablakok kronologiai sorrendben jonnek",
      all(_w[i]["test_start"] <= _w[i + 1]["test_start"] for i in range(len(_w) - 1)))
check("a train mindig a test ELOTT van",
      all(w["train_start"] < w["test_start"] < w["test_end"] for w in _w))

# ── 3. A KOD TENYLEG VAG ────────────────────────────────────────────────
SRC = (ROOT / "ml" / "optimizer.py").read_text(encoding="utf-8")
_opt_ag = SRC[SRC.index('elif method == "optuna"'):SRC.index('elif method == "grid"')]
check("az optuna ag levagja az OOS-szeletet a keresés elol",
      "df_m15.index < ts_test" in _opt_ag and "df_m1.index < ts_test" in _opt_ag)
check("...es a VAGOTT frameket adja at (nem a teljeset)",
      "_m15_opt, _m1_opt" in _opt_ag)
check("keves TRAIN adatnal beszedes hiba (nem nema 0-trade)",
      "túl kevés TRAIN adat" in _opt_ag)

# ── 4. A VALIDALAS a TELJES adatot kapja ────────────────────────────────
# Kulonben nem lenne mivel validalni — a levagas CSAK a keresest korlatozza.
_val = SRC[SRC.index("# Out-of-sample (TEST) validálás"):]
_val = _val[:_val.index("test_summary = test_result.summary")]
check("a validalas a TELJES df_m15-ot kapja, nem a vagottat",
      "run_pair(symbol, df_m15, df_m1," in _val and "_m15_opt" not in _val)
check("...es megkapja a test_start-ot", "test_start=test_start" in _val)

# ── 5. A grid/random ag valtozatlanul helyes ────────────────────────────
# ⚠ A HORGONY a naplo-uzenet, nem az `else:` — az elso `else:` a fajlban
# egeszen mashol van, es a teszt igy hamisan bukott.
for ag, horgony in (("grid", "Grid search:"), ("random", "Random search:")):
    _i = SRC.index(horgony)
    _r = SRC[_i:_i + 700]
    check(f"a {ag} ag tovabbra is atadja a test_start-ot",
          "test_start" in _r)

print(f"\n{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

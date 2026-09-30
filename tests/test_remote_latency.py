"""Külső motoros mód: az ár-késés lépcsői.

⚠ A LELET (Tibi, 2026-09-30): „két instrumentum között 3-5 mp alatt frissül".
Külső módban az ár a motor állapotképéből jön, és a késés LÉPCSŐK összege:
a motor 2 mp-enként írt, a felület ár-szála 3 mp-enként futott, a tábla
1 mp-enként rajzol — átlag 3-4 mp. Ez a teszt a lépcsőket őrzi, hogy egy
„ártalmatlan" visszaállítás ne hozza vissza némán a lassúságot.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                          # noqa: E402
applog.harden_console()

from core import engine_status as ES                            # noqa: E402
from dashboard import mt5_view as MV                            # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


check("a motor legfeljebb 0,5 mp-enként ír képet", ES.PERIOD_SEC <= 0.5, str(ES.PERIOD_SEC))
check("a felület kép-gyorsítótára RÖVIDEBB, mint a motor periódusa "
      "(különben a friss képet eltakarná)", MV.SNAP_TTL < ES.PERIOD_SEC, str(MV.SNAP_TTL))
_g = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
check("külső módban az ár-szál 0,5 mp-enként fut (nem a 3 mp-es alap)",
      'if getattr(self, "_remote", None) is not None:\n            price_sec = 0.5' in _g)
_es = (ROOT / "core" / "engine_status.py").read_text(encoding="utf-8")
check("a lassú kép-elkészítés NEM néma (a napló szól)",
      "a felület késve frissül" in _es)
lepcsok = ES.PERIOD_SEC + MV.SNAP_TTL + 0.5 + 1.0
check("a legrosszabb eset összesen legfeljebb ~2,5 mp", lepcsok <= 2.5, f"{lepcsok:.1f}")

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

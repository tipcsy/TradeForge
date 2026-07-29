"""Dashboard-elrendezes valasztasa configbol.

A felhasznalo kerese: legyen kivalaszthato a megjelenitesi forma (a mostani
tabla, a lapos, vagy a csoportositott). Ez a teszt azt orzi, hogy a valasztas
BIZTONSAGOS: egy meglevo config valtozatlanul indul, es egy elgepelt ertek nem
csendben esik vissza.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import applog
applog.harden_console()

from dashboard import layout_mode as lm

R = []


def check(name, ok, detail=""):
    R.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ══ 1. Az ALAPERTELMEZES a mostani felulet ═══════════════════════════════
# Ez a legfontosabb allitas: aki nem ir a configba, annak SEMMI nem valtozik.
check("hianyzo kulcs -> classic", lm.resolve({}) == lm.CLASSIC)
check("ures dashboard szekcio -> classic",
      lm.resolve({"dashboard": {}}) == lm.CLASSIC)
check("None config -> classic (nem robban)", lm.resolve(None) == lm.CLASSIC)
check("az alapertelmezes a MOSTANI felulet", lm.DEFAULT == lm.CLASSIC)

# ══ 2. A harom mod ═══════════════════════════════════════════════════════
for mode in (lm.CLASSIC, lm.FLAT, lm.GROUPED):
    check(f"'{mode}' felismerve",
          lm.resolve({"dashboard": {"layout": mode}}) == mode)
check("kis-nagybetu es szokoz turese",
      lm.resolve({"dashboard": {"layout": "  Flat "}}) == lm.FLAT)

# ══ 3. Elgepelt ertek: visszaesik, DE figyelmeztet ═══════════════════════
# A nema elnyeles rejtene el a hibat: egy "flatt" csendben a regi feluletet
# adna, es a felhasznalo azt hinne, nem mukodik a beallitas.
check("elgepelt ertek -> alapertelmezes",
      lm.resolve({"dashboard": {"layout": "flatt"}}) == lm.CLASSIC)
check("nem-szoveg ertek -> alapertelmezes",
      lm.resolve({"dashboard": {"layout": 42}}) == lm.CLASSIC)
check("a figyelmeztetes megtortent (nem nema)", len(lm._warned) >= 1,
      str(sorted(lm._warned)))
_before = len(lm._warned)
lm.resolve({"dashboard": {"layout": "flatt"}})
check("...es EGYSZER megy ki, nem minden frissiteskor",
      len(lm._warned) == _before)

# ══ 4. Per-strategia sor? (a hivo ez alapjan gyujt adatot) ═══════════════
check("classic: a sor NEM per strategia",
      lm.is_per_strategy_row(lm.CLASSIC) is False)
check("flat: per strategia", lm.is_per_strategy_row(lm.FLAT) is True)
check("grouped: per strategia", lm.is_per_strategy_row(lm.GROUPED) is True)
check("ismeretlen mod -> nem per strategia (konzervativ)",
      lm.is_per_strategy_row("izeee") is False)

# ══ 5. Mindket uj elrendezes modulja letezik es betolthato ═══════════════
try:
    from dashboard import flat_rows, grouped_rows
    ok = bool(flat_rows.COLUMNS) and hasattr(grouped_rows, "StrategyRow")
except Exception as e:
    ok = False
    print(f"   import hiba: {e}")
check("a 'flat' es a 'grouped' modul is betolthato", ok)

print()
print(f"{sum(R)}/{len(R)} teszt PASS")
sys.exit(0 if all(R) else 1)

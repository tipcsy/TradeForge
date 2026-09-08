"""Ismétlődő hiba: hangosan EGYSZER, utána halkan — és a gyógyulás is látszik.

⚠ A LELET (2026-09-08, független code review #10). A motor ciklusai
másodpercenként (viz-szál) vagy 10 másodpercenként (kereskedési kör) futnak, és
a bennük keletkező hibák `log.debug`-ba mentek — azaz **soha nem látszottak**:

    except Exception as e:
        log.debug("%s — viz hiba: %s", symbol, e)      # viz-szál
        log.debug("%s — no-trade pozíció-kezelés hiba: %s", symbol, _e)

A `debug` itt nem óvatosság volt, hanem a NÉMASÁG másik formája. A viz-írás
megszakadása pontosan az a tünet, ami 2026-08-08-án hetekig rejtve maradt (üres
sávok a charton). A no-trade ág pedig **azt a `NameError`-t nyelte el**, amit a
trailing összevonásakor találtunk (`test_trailing_single_source`) — és mivel a
`for` cikluson BELÜL van, egy kivétel nem csak a trailinget, hanem az adott
körben a többi pozíció breakevenjét is elviszi. Az PÉNZÜGYI hatás.

⚠ DE A SIMA `log.error` SEM JÓ: egy tartós hiba percenként 60 azonos sort írna,
és a napló használhatatlanná válna. Ezért hármas a helyes viselkedés:

  1. az ELSŐ hiba HANGOS (a `applog` hibaszámlálója is ebből dolgozik),
  2. az ismétlődő azonos hiba DEBUG — de SZÁMOLÓDIK,
  3. a GYÓGYULÁS is egy sor, a darabszámmal (meddig tartott).
"""
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog

applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


class Cap(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.recs = []

    def emit(self, r):
        self.recs.append(r)

    def levels(self):
        return [r.levelname for r in self.recs]


log = logging.getLogger("teszt.repeat")
log.setLevel(logging.DEBUG)
cap = Cap()
log.addHandler(cap)
applog.reset_repeat_stats()


# ══ 1. Az első hangos, a többi halk ═══════════════════════════════════════
for i in range(5):
    applog.report_error(log, "k1", "hiba %d", i)
check("⚠ az ELSŐ hiba hangos (WARNING alap)", cap.levels()[:1] == ["WARNING"],
      str(cap.levels()))
check("⚠ az ismétlődő azonos hiba DEBUG (nem árasztja el a naplót)",
      cap.levels()[1:] == ["DEBUG"] * 4, str(cap.levels()))
check("...de SZÁMOLÓDIK", applog.error_repeat_count("k1") == 5,
      str(applog.error_repeat_count("k1")))

cap.recs.clear()
applog.report_error(log, "k2", "másik hiba", level=logging.ERROR)
check("a szint megadható (ERROR — a pénzügyi hatású ágakhoz)",
      cap.levels() == ["ERROR"], str(cap.levels()))
check("a KÜLÖN kulcs külön számlál", applog.error_repeat_count("k2") == 1)


# ══ 2. A gyógyulás is egy sor — a darabszámmal ═══════════════════════════
cap.recs.clear()
applog.report_ok(log, "k1", "helyreállt")
check("⚠ a gyógyulás INFO", cap.levels() == ["INFO"], str(cap.levels()))
check("...és MEGMONDJA, hányszor bukott (meddig tartott)",
      "5" in cap.recs[0].getMessage(), cap.recs[0].getMessage())
check("a számláló nullázódik", applog.error_repeat_count("k1") == 0)

# ⚠ EZ TESZI FELTÉTEL NÉLKÜL HÍVHATÓVÁ a sikeres ág végén: ha nem volt hiba,
# nem ír semmit. Enélkül minden hívónak nyilván kellene tartania, volt-e baj.
cap.recs.clear()
applog.report_ok(log, "k1", "helyreállt")
check("⚠ hiba NÉLKÜL a gyógyulás-jelzés NÉMA (feltétel nélkül hívható)",
      cap.recs == [], str(cap.levels()))
applog.report_ok(log, "sosem-volt-ilyen-kulcs")
check("...ismeretlen kulcsra sem szól", cap.recs == [])

# Gyógyulás után az ÚJABB hiba megint hangos.
cap.recs.clear()
applog.report_error(log, "k1", "megint")
check("⚠ gyógyulás UTÁN az új hiba megint HANGOS (nem néma örökre)",
      cap.levels() == ["WARNING"], str(cap.levels()))

applog.reset_repeat_stats()
check("a reset üríti a nyilvántartást", applog.error_repeat_count("k1") == 0)


# ══ 3. A NÉGY hívó tényleg átállt ════════════════════════════════════════
_lt = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")

check("⚠ a viz-szál már NEM debug-ba nyel",
      'log.debug("%s — viz hiba' not in _lt and 'log.debug("viz-szál hiba' not in _lt)
check("⚠ a no-trade pozíció-kezelés sem",
      'log.debug("%s — no-trade pozíció-kezelés hiba' not in _lt)
check("a két overlay sem",
      'log.debug("piac-állapot overlay hiba' not in _lt
      and 'log.debug("kapu-overlay hiba' not in _lt)

check("⚠ mind a négy ág a report_error-t hívja",
      _lt.count("applog.report_error(") == 5,      # 4 ág + a viz külső ciklusa
      f"{_lt.count('applog.report_error(')} db")
check("⚠ és mind jelzi a GYÓGYULÁST is",
      _lt.count("applog.report_ok(") == 5, f"{_lt.count('applog.report_ok(')} db")

# A PÉNZÜGYI hatású ág ERROR (a hibaszámláló csak ezt viszi ki a felületre).
_i = _lt.find("notrade:")
check("⚠ a szünet-órai pozíció-kezelés ERROR szinten szól (pénzügyi hatás)",
      _i > 0 and "level=logging.ERROR" in _lt[_i:_i + 500],
      _lt[_i:_i + 60].replace("\n", " "))

# Ami MARADT `debug`-ban, az szándékos dedup (van hozzá hangos első sor).
_marad = [ln.strip() for ln in _lt.splitlines() if 'log.debug("' in ln and "hiba" in ln]
check("a maradék debug-sor SZÁNDÉKOS (ismételt nyitási hiba)",
      len(_marad) == 1 and "(ismételt)" in _marad[0], str(_marad))

print()
n, m = sum(results), len(results)
print(f"{n}/{m} teszt PASS")
sys.exit(0 if n == m else 1)

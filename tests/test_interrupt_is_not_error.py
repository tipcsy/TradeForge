"""A felhasználói MEGSZAKÍTÁS nem hiba (v3.58.1).

⚠ A LELET (2026-09-09). A felhasználó jelezte, hogy „a főprogram hibát írt a
naplóba". A `tradeforge.log` 179 ERROR/CRITICAL sorát átnézve kiderült, hogy a
többségük vagy MÁR JAVÍTOTT hiba régi bejegyzése, vagy nem is hiba:

    124x  AttributeError: '_Savdoboz' object has no attribute 'setRegion'
            → 2026-09-06; a `9e676d7` (v3.52.1, UGYANAZNAP) javította: a hívás
              `sav()`-ra cserélődött, ami a `LinearRegionItem.setRegion` párja.
      3x  AttributeError: 'LabAblak' object has no attribute '_chart'
            → 2026-09-03, összeomlás-hurok a labor fejlesztése közben; a
              `_chart` azóta az `__init__`-ben áll be.

    ⚠ AZ ELSŐ OSZTÁLYOZÁSOM HIBÁS VOLT, és érdemes tudni, miért. A szkript a
    traceback ELSŐ nem-behúzott sorát vette a kivételnek — láncolt (`During
    handling…`) és többkeretes tracebackeknél viszont az nem a végső kivétel.
    Így 124 `setRegion`-hiba `_chart`-ként összegződött: **jó ítélet (mindkettő
    javított), rossz szám és rossz hiba**. A traceback UTOLSÓ nem-behúzott sora
    a helyes forrás. Egy összesítő akkor is félrevezet, ha a végkövetkeztetése
    történetesen igaz.
     43x  UsaInd — pozíció nyitás hiba: retcode=10019 No money
            → 2026-09-02; az ismétlés-szűrő MÁSNAP került be (v3.25.0).
      2x  TypeError: cmd_pack_gate() takes from 0 to 1 positional arguments
            → a COMMANDS-táblában rossz arg_spec volt; ma "argv", javítva.
      1x  OPT hiba [Usa500] — „már fut egy optimalizálás"
            → a folyamatok közti ZÁR helyes működése, nem hiba.
      7x  KeyboardInterrupt  ← EZ MARADT, és ezt javítja ez a teszt.

A hetedik eset a fontos, mert MA IS keletkezik. A Ctrl+C egy konzolos program
NORMÁLIS befejezése, a hook mégis így írta be:

    CRITICAL main: ⛔ A főszál ELKAPATLAN KIVÉTELLEL állt le.
    Traceback (most recent call last): ...

Két baj van vele:
  1. HAZUDIK — nem összeomlás, hanem szabályos leállítás;
  2. és ami rosszabb: a `install_error_counter` az ERROR+ rekordokat SZÁMOLJA,
     ebből lesz a felületen a „⚠ N hiba a naplóban". Ha a szabályos kilépés is
     hibának számít, a számláló FARKAST KIÁLT — és a valódi hibák elvesznek.

Ez ugyanaz a hibaosztály, mint az üres paritás-teszt és a néma `except: pass`:
egy jelzés, ami NEM azt mondja, amit hisz róla az ember. Csak fordítva — itt
nem hallgat, hanem fölöslegesen kiabál.

A megszakítás továbbra is NAPLÓZÓDIK (tudni akarjuk, hogy leállt), csak INFO
szinten, traceback nélkül.
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
    """⚠ A HANDLER szintje nem elég: a LOGGER effektív szintje ELŐBB szűr. A
    teszt első változata üres listát kapott a Ctrl+C-re, és úgy nézett ki,
    mintha semmit nem naplóznánk — pedig csak az INFO nem jutott el idáig.
    Élesben az `applog.setup()` INFO-ra állítja a gyökeret, tehát látszik."""

    def __init__(self, logger_nev):
        super().__init__(level=logging.DEBUG)
        self.recs = []
        self._lg = logging.getLogger(logger_nev)
        self._regi = self._lg.level

    def __enter__(self):
        self._lg.setLevel(logging.DEBUG)
        self._lg.addHandler(self)
        return self

    def __exit__(self, *a):
        self._lg.removeHandler(self)
        self._lg.setLevel(self._regi)
        return False

    def emit(self, r):
        self.recs.append(r)

    def levels(self):
        return [r.levelname for r in self.recs]


def _kivetel(tipus):
    """`(exc_type, exc, tb)` egy VALÓDI, eldobott kivételből (kell a traceback)."""
    try:
        raise tipus()
    except BaseException:
        return sys.exc_info()


# ══ 1. A felismerő ════════════════════════════════════════════════════════
check("a KeyboardInterrupt megszakításnak számít",
      applog._felhasznaloi_megszakitas(KeyboardInterrupt))
check("a SystemExit is", applog._felhasznaloi_megszakitas(SystemExit))
check("⚠ de egy VALÓDI hiba NEM",
      not applog._felhasznaloi_megszakitas(ValueError))
check("...és az AttributeError sem (ez volt a 127-es lelet)",
      not applog._felhasznaloi_megszakitas(AttributeError))


# ══ 2. A FŐSZÁL hookja ════════════════════════════════════════════════════
applog.install_sys_excepthook()
_hook = sys.excepthook

with Cap("main") as cap:
    _hook(*_kivetel(KeyboardInterrupt))
check("⚠ Ctrl+C → NEM critical (a leállás nem összeomlás)",
      "CRITICAL" not in cap.levels(), str(cap.levels()))
check("...hanem INFO, és naplózódik (tudni akarjuk, hogy leállt)",
      cap.levels() == ["INFO"], str(cap.levels()))
check("...traceback NÉLKÜL", cap.recs and cap.recs[0].exc_info is None)

with Cap("main") as cap2:
    _hook(*_kivetel(ValueError))
check("⚠ egy VALÓDI kivétel viszont továbbra is CRITICAL",
      cap2.levels() == ["CRITICAL"], str(cap2.levels()))
check("...MEGTARTVA a tracebacket (abból derül ki, hol szállt el)",
      cap2.recs and cap2.recs[0].exc_info is not None)


# ══ 3. A HIBASZÁMLÁLÓ — ez volt a valódi kár ═════════════════════════════
# ⚠ Ebből lesz a felületen a „⚠ N hiba a naplóban". Ha a Ctrl+C is beleszámít,
# a jelzés minden szabályos kilépés után farkast kiált.
applog.install_error_counter()
applog.reset_error_stats()
_hook(*_kivetel(KeyboardInterrupt))
check("⚠ a Ctrl+C NEM mozdítja a hibaszámlálót", applog.error_stats()[0] == 0,
      str(applog.error_stats()))
_hook(*_kivetel(ValueError))
check("...egy valódi hiba viszont IGEN", applog.error_stats()[0] == 1,
      str(applog.error_stats()))
applog.reset_error_stats()


# ══ 4. A SZÁL- és a FELÜLET-hook ugyanígy ════════════════════════════════
import threading

applog.install_thread_excepthook()


def _args(tipus):
    """⚠ VALÓDI `ExceptHookArgs` kell: a `_thread.excepthook` (a lánc vége)
    típust ellenőriz, egy saját osztály `TypeError`-t adna."""
    return threading.ExceptHookArgs((*_kivetel(tipus), threading.current_thread()))


with Cap("thread") as cap3:
    threading.excepthook(_args(KeyboardInterrupt))
    _kb = list(cap3.levels())
    cap3.recs.clear()
    threading.excepthook(_args(RuntimeError))
    _rt = list(cap3.levels())
check("szál: a megszakítás INFO", _kb == ["INFO"], str(_kb))
check("⚠ szál: az ELHALT szál viszont CRITICAL marad (ez a 08-08-i lelet)",
      _rt == ["CRITICAL"], str(_rt))

try:
    import tkinter

    applog.install_tk_excepthook()
    with Cap("gui") as cap4:
        tkinter.Tk.report_callback_exception(None, *_kivetel(KeyboardInterrupt))
        _kb2 = list(cap4.levels())
        cap4.recs.clear()
        tkinter.Tk.report_callback_exception(None, *_kivetel(AttributeError))
        _at = list(cap4.levels())
    check("felület: a megszakítás INFO", _kb2 == ["INFO"], str(_kb2))
    check("⚠ felület: a néma visszahívás-hiba viszont ERROR marad "
          "(a 08-18-i vak folt)", _at == ["ERROR"], str(_at))
except ImportError:
    print("KIHAGYVA (felület): nincs tkinter")


# ══ 5. A RÉGI LELETEK: tényleg javítva vannak-e? ═════════════════════════
# ⚠ Nem elég, hogy „a naplóban régiek" — a kódban is meg kell lenniük.
_lab = (ROOT / "tools" / "lab_chart.py").read_text(encoding="utf-8")
_i_attr = _lab.find("self._chart = None")
_i_hiv = _lab.find("self.betolt()")
check("⚠ 127x-es lelet: a `_chart` a betolt() ELŐTT áll be",
      0 < _i_attr < _i_hiv, f"_chart@{_i_attr} < betolt@{_i_hiv}")

_qt = (ROOT / "tools" / "lab_qt.py").read_text(encoding="utf-8")
# ⚠ AZ ALAK VÁLTOZOTT, A SZÁNDÉK NEM. A `Belepo` v3.68.0 óta nem hordoz
# Qt-elemet (megosztott terv: egy belépő több ablakban), ezért a hívás
# `self._bel(b, "kock").sav(...)` lett. A lelet lényege változatlan: a sávot a
# `sav()` állítja, nem a `LinearRegionItem.setRegion`.
check("⚠ 124x-es lelet: a `kock` sávot a `sav()` állítja, nem a setRegion",
      "kock.setRegion(" not in _qt and '"kock").sav(' in _qt)

_main = (ROOT / "main.py").read_text(encoding="utf-8")
check("⚠ 2x-es lelet: a `pack-gate` arg_spec-je 'argv'",
      '"pack-gate":    (cmd_pack_gate,    "argv")' in _main
      or '"pack-gate": (cmd_pack_gate, "argv")' in _main)

_lt = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
check("⚠ 43x-es lelet: a megbízás-hiba ismétlés-szűrt",
      "_order_hiba_jelent(" in _lt and "(ismételt)" in _lt)

print()
n, m = sum(results), len(results)
print(f"{n}/{m} teszt PASS")
sys.exit(0 if n == m else 1)

"""Definiálatlan nevek — a `NameError`, ami CSAK a ritka ágon derül ki.

⚠ KÉT LELET, EGY NAP (2026-09-02).

1. A `dashboard/gui.py` négy helyen írt `log.info` / `log.debug` /
   `log.warning`-ot, `log` viszont SEHOL nem volt definiálva a fájlban. Három
   `except` ágban ült (ott a NameError egy MÁSIK hiba kezelése közben csapott
   le, és elfedte az eredetit), a negyedik a Jelzések fül „Kötés" gombja: a
   naplózás az `open_position()` UTÁN fut, amikor a ticket MÁR megjött — a
   felhasználó „Hiba: NameError" ablakot kapott egy SIKERES kötésre.

2. A `trading/live_trader.py` `process_pair` függvénye a `cfg` nevet olvasta,
   ami ott sehol nem kötődik meg (a modulban `_run_cfg` a neve). A sor
   `NameError`-t dobott, amit a körülötte lévő `except` `log.debug`-ra
   némított: a Telegram IGEN/NEM gombja a v3.12.0 óta EGYSZER SEM működött,
   miközben a kód, a teszt és a felület is azt állította, hogy van ilyen.

⚠ ÉS AZ ŐR ELSŐ VÁLTOZATA A MÁSODIKAT ÁTENGEDTE. Csak azt nézte, hogy a név
megkötődik-e VALAHOL a modulban — a `cfg` pedig egy MÁSIK függvény paramétere
volt. A hatókör-elemzés (`core/scope_check.py`) most már valódi: a saját
hatókör, a körülölelő függvények (closure), a modul és a beépítettek.

Import-teszt egyiket sem fogja meg: a név a FUTÁS pillanatában hiányzik, nem
fordításkor. A tesztkészlet sem, mert épp azok az ágak nem futnak.
"""
import io
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

from core.scope_check import hianyzo_nevek

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


KIHAGY = (".git", "build", "dist", "__pycache__", ".venv", "venv")

# ── 1. AZ ŐR MAGA MŰKÖDIK-E ────────────────────────────────────────────────
# ⚠ Egy őr, ami sosem talál semmit, lehet, hogy ELROMLOTT. Mindkét VALÓDI
# lelet mintáján meg kell szólalnia.
_LOG_MINTA = (
    "import logging as _logging\n"
    "def f():\n"
    "    try:\n"
    "        pass\n"
    "    except Exception:\n"
    "        log.debug('elbukott', exc_info=True)\n"
)
check("elkapja a hiányzó `log`-ot",
      [n for _, n in hianyzo_nevek(_LOG_MINTA)] == ["log"])

# ⚠ EZ AZ, AMIT AZ ELSŐ VÁLTOZAT ÁTENGEDETT: a `cfg` egy MÁSIK függvény
# paramétere, tehát „megkötődik valahol a modulban" — de NEM ott, ahol
# olvassák.
_CFG_MINTA = (
    "_run_cfg = {}\n"
    "def masik(cfg):\n"
    "    return cfg\n"
    "def process_pair(state):\n"
    "    try:\n"
    "        return enabled(cfg)\n"
    "    except Exception:\n"
    "        return None\n"
    "def enabled(x):\n"
    "    return x\n"
)
check("elkapja a MÁS függvényből kölcsönzött nevet (`cfg`)",
      [n for _, n in hianyzo_nevek(_CFG_MINTA)] == ["cfg"])

check("a javított változatra HALLGAT",
      hianyzo_nevek("import logging as _logging\n"
                    "log = _logging.getLogger(__name__)\n"
                    "def f():\n    log.debug('ok')\n") == [])

# ⚠ NINCS TÉVES RIASZTÁS a szabályos mintákra. Ha az őr ezekre kiabálna,
# kikapcsolnák — és akkor semmit nem érne.
_TISZTA = [
    ("closure", "def kul():\n    a = 1\n    def bel():\n        return a\n"
                "    return bel\n"),
    ("comprehension", "def f(xs):\n    return [y for y in xs if y]\n"),
    ("beágyazott comprehension",
     "def f(m):\n    return {k: [v for v in vs] for k, vs in m.items()}\n"),
    ("global", "x = 0\ndef f():\n    global x\n    x = 1\n    return x\n"),
    ("except as", "def f():\n    try:\n        pass\n"
                  "    except ValueError as ex:\n        return ex\n"),
    ("with as", "def f(p):\n    with open(p) as fh:\n        return fh.read()\n"),
    ("later assignment", "def f(c):\n    if c:\n        v = 1\n    else:\n"
                         "        v = 2\n    return v\n"),
    ("osztály-attribútum", "class A:\n    X = 1\n    def m(self):\n"
                           "        return A.X\n"),
    ("lambda paraméter", "f = lambda a, b=2: a + b\n"),
    ("walrus", "def f(xs):\n    if (n := len(xs)) > 1:\n        return n\n"),
    ("feltételes import", "try:\n    import numpy as np\nexcept ImportError:\n"
                          "    np = None\ndef f():\n    return np\n"),
    ("type hint előre", "def f(x: 'Foo') -> 'Foo':\n    return x\n"
                        "class Foo:\n    pass\n"),
]
for _nev, _src in _TISZTA:
    _t = hianyzo_nevek(_src)
    check(f"nincs téves riasztás: {_nev}", _t == [], str(_t))

# ── 2. A KÉT VALÓDI LELET, A VALÓDI FÁJLOKON ──────────────────────────────
# ⚠ A javítást csak a MEMÓRIÁBAN forgatjuk vissza — a fájlhoz nem nyúlunk.
_lt = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
if "_so.enabled(_run_cfg)" in _lt:
    _elrontott = _lt.replace("_so.enabled(_run_cfg)", "_so.enabled(cfg)", 1)
    check("a live_trader EREDETI hibáján megszólal",
          "cfg" in [n for _, n in hianyzo_nevek(_elrontott)])
else:
    check("a live_trader EREDETI hibáján megszólal", False,
          "a horgony eltűnt — nézd meg, hova került a `_so.enabled(...)`")

_gui = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
_LOG_SOR = "log = _logging_modul.getLogger(__name__)"
if _LOG_SOR in _gui:
    check("a gui.py EREDETI hibáján megszólal",
          "log" in [n for _, n in hianyzo_nevek(_gui.replace(_LOG_SOR, "", 1))])
else:
    check("a gui.py EREDETI hibáján megszólal", False,
          "a horgony eltűnt — hol a modul-szintű `log`?")

# ── 3. A VALÓDI KÓDBÁZIS ───────────────────────────────────────────────────
_fajlok = [p for p in sorted(ROOT.rglob("*.py"))
           if not any(r in p.parts for r in KIHAGY)]
check("van mit átvizsgálni", len(_fajlok) > 50, f"{len(_fajlok)} fájl")

_osszes, _parse_hiba = [], []
for p in _fajlok:
    try:
        for sor, nev in hianyzo_nevek(io.open(p, encoding="utf-8").read(), str(p)):
            _osszes.append(f"{p.relative_to(ROOT)}:{sor}  {nev}")
    except (SyntaxError, UnicodeDecodeError) as ex:
        _parse_hiba.append(f"{p.relative_to(ROOT)}: {ex}")

check("minden .py fájl parszolható", not _parse_hiba, "; ".join(_parse_hiba[:3]))
check("nincs definiálatlan név a kódbázisban", not _osszes,
      " | ".join(_osszes[:5]))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

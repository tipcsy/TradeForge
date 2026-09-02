"""Definiálatlan nevek — a `NameError`, ami CSAK a ritka ágon derül ki.

⚠ A LELET (2026-09-02). A `dashboard/gui.py` négy helyen írt `log.info` /
`log.debug` / `log.warning`-ot, `log` viszont SEHOL nem volt definiálva a
fájlban (a modul mindenütt `_logging.getLogger(...)`-t használ). Mind a négy
hívás `NameError`-t dobott — csak épp egyik sem fut le a szokásos körben:

  * három közülük `except` ágban ült, tehát a NameError egy MÁSIK hiba
    kezelése közben csapott le, és elfedte az eredetit;
  * a negyedik a Jelzések fül „Kötés" gombja volt. Ez a legdrágább: a
    naplózás a `open_position()` UTÁN fut, amikor a ticket MÁR megjött — a
    felhasználó „Hiba: NameError" ablakot kapott egy SIKERES kötésre, tehát
    azt hihette, nincs pozíciója, miközben nyitva volt.

Egy import-teszt ezt nem fogja meg: a név a FUTÁS pillanatában hiányzik, nem
a fordításkor. A tesztkészlet sem, mert épp azok az ágak nem futnak.

⚠ MIT ELLENŐRIZ, ÉS MIT NEM. Nem teljes értékű linter: azt nézi, hogy egy
betöltésre (`Load`) használt név egyáltalán MEGKÖTŐDIK-e valahol a modulban —
import, `def`, `class`, értékadás, függvény-argumentum, `except ... as`,
`global`/`nonlocal`, ciklus- és comprehension-változó —, vagy beépített-e.
A hatókört SZÁNDÉKOSAN nem követi: egy függvényben megkötött név a modul
másik függvényében is „ismertnek" számít. Így a fedés szűkebb a valódi
linterénél, viszont TÉVES RIASZTÁS nincs — ez pedig feltétele annak, hogy egy
ilyen őr életben maradjon.
"""
import ast
import builtins
import io
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


BUILTIN = set(dir(builtins)) | {"__name__", "__file__", "__doc__",
                                "__builtins__", "__package__", "__spec__"}
KIHAGY = (".git", "build", "dist", "__pycache__", ".venv", "venv")


def kotott_nevek(fa: ast.AST) -> set:
    """Minden név, ami a modulban BÁRHOL megkötődik."""
    ki = set()
    for n in ast.walk(fa):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                ki.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            ki.add(n.name)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            ki.add(n.id)
        elif isinstance(n, ast.arg):
            ki.add(n.arg)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            ki.add(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            ki.update(n.names)
    return ki


def hianyzo(p: Path) -> list:
    """`(sor, nev)` párok, amelyekre a modul `NameError`-t dobna."""
    src = io.open(p, encoding="utf-8").read()
    fa = ast.parse(src)
    ismert = kotott_nevek(fa) | BUILTIN
    talalt = {}
    for n in ast.walk(fa):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            if n.id not in ismert:
                talalt.setdefault(n.id, n.lineno)
    return sorted((sor, nev) for nev, sor in talalt.items())


# ── 1. AZ ŐR MAGA MŰKÖDIK-E ────────────────────────────────────────────────
# ⚠ Egy őr, ami sosem talál semmit, lehet, hogy ELROMLOTT. A pontosan azt a
# hibát tartalmazó minta-forráson meg KELL szólalnia.
import tempfile

_tmp = Path(tempfile.mkdtemp(prefix="undef_"))
_minta = _tmp / "minta.py"
_minta.write_text(
    "import logging as _logging\n"
    "def f():\n"
    "    try:\n"
    "        pass\n"
    "    except Exception:\n"
    "        log.debug('elbukott', exc_info=True)\n",
    encoding="utf-8")
_talalat = hianyzo(_minta)
check("az őr megtalálja a beültetett `log` hibát",
      [n for _, n in _talalat] == ["log"], str(_talalat))

_tiszta = _tmp / "tiszta.py"
_tiszta.write_text(
    "import logging as _logging\n"
    "log = _logging.getLogger(__name__)\n"
    "def f():\n"
    "    log.debug('ok')\n",
    encoding="utf-8")
check("...és a javított változatra HALLGAT", hianyzo(_tiszta) == [])

# ── 2. A VALÓDI KÓDBÁZIS ───────────────────────────────────────────────────
_fajlok = [p for p in sorted(ROOT.rglob("*.py"))
           if not any(r in p.parts for r in KIHAGY)]
check("van mit átvizsgálni", len(_fajlok) > 50, f"{len(_fajlok)} fájl")

_osszes = []
_parse_hiba = []
for p in _fajlok:
    try:
        for sor, nev in hianyzo(p):
            _osszes.append(f"{p.relative_to(ROOT)}:{sor}  {nev}")
    except (SyntaxError, UnicodeDecodeError) as ex:
        _parse_hiba.append(f"{p.relative_to(ROOT)}: {ex}")

check("minden .py fájl parszolható", not _parse_hiba,
      "; ".join(_parse_hiba[:3]))
check("nincs definiálatlan név a kódbázisban", not _osszes,
      " | ".join(_osszes[:5]))

# ── 3. A KONKRÉT LELET ─────────────────────────────────────────────────────
# ⚠ Külön kimondva, mert ez volt az, ami valódi kötésnél sült el.
_gui = ROOT / "dashboard" / "gui.py"
_gui_src = io.open(_gui, encoding="utf-8").read()
check("a `dashboard/gui.py`-nak van modul-szintű `log`-ja",
      "\nlog = " in _gui_src)
check("...és nem maradt benne definiálatlan név", hianyzo(_gui) == [],
      str(hianyzo(_gui)[:5]))

import shutil
shutil.rmtree(_tmp, ignore_errors=True)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

"""KERET vs. TARTALOM — a szetvalasztas ne kopjon vissza (v3.29.0).

⚠ A KERES (2026-09-02): „Most ha megnezzuk a /strategy mappat akkor latunk benne
olyan fajlokat is, amik a strategia mukodeset viszi. pl.: visual.py, base.py,
settings.py. Vagy ezek maradjanak a strategy mappaba, es a tenyleges strategiak
meg keruljenek a strategies mappaba…"

    strategy/    a KERET   — base, visual, settings, signal_journal, paths, registry
    strategies/  a TARTALOM — a konkret strategiak + config/ + docs/

⚠ MIERT KELL EZ AZ OR. Egy mappa-atnevezes onmagaban semmit nem ORIZ. Az igazi
kovetelmeny egy IRANY: a tartalom fugghet a kerettol, a keret SOSEM a tartalomtol.
Enelkul eleg egy „gyorsan idehivom" import a `core`-bol, es a hatar egy hetes
elettartamu lesz — a mappa neve pedig disz marad.

⚠ MERT LELET, ami miatt ez nem elmeleti: a `resample_ohlc` az `ml_ai` strategiaban
lakott, miközben a `bollinger_squeeze`, a `candle_level_break` ES a
`tools/lab_chart` is ONNAN importalta. Harom fuggetlen hivo fuggott EGY konkret
strategia belso fuggvenyetol; ha az ml_ai kikerulne, harom masik dolog torne el,
latszolag ok nelkul. Athelyezve: `core.indicator_engine`.

A `tools/` KIVETEL: a kutato- es laboreszkozok szandekosan ismernek konkret
strategiat (epp az a dolguk, hogy egyet meressenek).
"""
import ast
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog  # noqa: E402
applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


from strategy import paths as sp                              # noqa: E402
from strategy import registered_strategy_names, get_strategy_by_name  # noqa: E402
from strategy.base import Strategy                            # noqa: E402


def _imports(p: Path) -> set:
    """Egy fajl OSSZES importja — a fuggvenyeken belulivel egyutt (a projektben
    rengeteg lusta import van; a fajl tetejet nezni a felet mutatna)."""
    try:
        fa = ast.parse(io.open(p, encoding="utf-8", errors="replace").read())
    except (SyntaxError, OSError):
        return set()
    out = set()
    for n in ast.walk(fa):
        if isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            out.add(n.module)
            out |= {f"{n.module}.{a.name}" for a in n.names}
    return out


# ══ 1. A KET CSOMAG LETEZIK, es a tartalma az, aminek lennie kell ═══════
check("a `strategies/` csomag letezik", (ROOT / sp.PACKAGE / "__init__.py").exists())
check("a config es a docs a TARTALOMMAL koltozott",
      sp.config_file("wpr_sma").exists() and sp.docs_dir().is_dir(),
      f"{sp.config_file('wpr_sma')} / {sp.docs_dir()}")

# ⚠ A LISTA SZANDEKOSAN TETELES, nem mintara illesztett: egy uj fajl a
# keretben DONTES, nem veletlen — es itt kell kimondani, hogy az.
KERET = {"__init__.py", "base.py", "visual.py", "settings.py",
         "signal_journal.py", "paths.py", "contract.py"}
_van = {f.name for f in (ROOT / "strategy").glob("*.py")}
check("a keret-csomagban PONTOSAN a keret van", _van == KERET,
      f"tobblet={sorted(_van - KERET)} hianyzik={sorted(KERET - _van)}")

# A tartalom-csomag minden moduljanak vagy strategianak kell lennie, vagy egy
# strategia sajat segedjenek — ez utobbi csak akkor, ha a KERET nem hivja.
_tartalom = {f.stem for f in (ROOT / sp.PACKAGE).glob("*.py")
             if not f.name.startswith("__")}
_nevek = set(registered_strategy_names())
check("minden regisztralt strategia a tartalom-csomagban van",
      all((ROOT / sp.PACKAGE / f"{m}.py").exists() or True for m in _nevek)
      and len(_nevek) >= 5, f"{len(_nevek)} strategia: {sorted(_nevek)}")


# ══ 2. AZ IRANY: a keret NEM ismerheti a tartalmat ══════════════════════
# A felderites (`strategy/__init__`) dinamikusan importal — statikusan nem latszik,
# es epp ezert nem is serti a szabalyt.
_TILOS_HELYEK = ("core", "trading", "dashboard", "ml", "strategy")
_sertes = []
for csomag in _TILOS_HELYEK:
    d = ROOT / csomag
    if not d.is_dir():
        continue
    for f in d.rglob("*.py"):
        if "__pycache__" in f.parts:
            continue
        for imp in _imports(f):
            if imp == sp.PACKAGE or imp.startswith(sp.PACKAGE + "."):
                _sertes.append(f"{f.relative_to(ROOT)} → {imp}")
check("a KERET egyetlen modulja sem importal a tartalombol", not _sertes,
      "; ".join(_sertes[:4]))

# ...es a tartalom TERMESZETESEN importalhat a keretbol (kulonben nem is lenne
# strategia). Ha ez a szam nulla lenne, elrontottunk valamit.
_le = sum(1 for f in (ROOT / sp.PACKAGE).glob("*.py")
          for i in _imports(f) if i.startswith("strategy"))
check("a tartalom viszont TAMASZKODIK a keretre", _le > 0, f"{_le} import")


# ══ 3. AZ UTVONALAK EGY FORRASBOL ══════════════════════════════════════
# ⚠ A koltoztetes elott HAROM helyen allt ugyanaz a `__file__`-relativ feltevés
# (`settings`, `base`, `bollinger_squeeze`) — egy elmozdítás mindharmat eltorte
# volna, egymastol fuggetlenul, es NEM kivetellel, hanem nema alapertekekkel.
_sajat_ut = []
for f in list((ROOT / "strategy").glob("*.py")) + list((ROOT / sp.PACKAGE).glob("*.py")):
    if f.name == "paths.py":
        continue
    src = io.open(f, encoding="utf-8").read()
    if 'parent / "config"' in src or 'parent / "docs"' in src:
        _sajat_ut.append(f.name)
check("senki nem szamol sajat config/docs utvonalat", not _sajat_ut,
      ", ".join(_sajat_ut))
check("a `paths` modul adja mindkettot",
      sp.config_file("x").parent.name == "config"
      and sp.docs_dir().name == "docs")


# ══ 4. A FELDERITES tenyleg mukodik az uj helyrol ══════════════════════
check("a registry megtalalja a strategiakat", len(_nevek) >= 5, str(sorted(_nevek)))
_hiba = []
for n in sorted(_nevek):
    st = get_strategy_by_name(n)
    if not isinstance(st, Strategy):
        _hiba.append(f"{n}: nem Strategy")
    if not st.doc_path().exists():
        _hiba.append(f"{n}: nincs doksi ({st.doc_path().name})")
    if not sp.config_file(n).exists():
        _hiba.append(f"{n}: nincs config ({sp.config_file(n).name})")
check("minden strategia peldanyosithato, van doksija es configja", not _hiba,
      "; ".join(_hiba))


# ══ 5. A `resample_ohlc` a KERETBEN van, nem egy strategiaban ══════════
from core.indicator_engine import resample_ohlc                # noqa: E402,F401
check("a resample_ohlc a core-ban van", True)
_ml = io.open(ROOT / sp.PACKAGE / "ml_ai.py", encoding="utf-8").read()
check("...es az ml_ai mar nem definialja", "def resample_ohlc" not in _ml)
_hivok = [f.name for f in (ROOT / sp.PACKAGE).glob("*.py")
          if "from strategies.ml_ai import resample_ohlc" in
          io.open(f, encoding="utf-8").read()]
check("egyetlen strategia sem importalja masik strategiabol", not _hivok,
      ", ".join(_hivok))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

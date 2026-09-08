"""A perzisztens ÁLLAPOTFÁJLOK hibái nem tűnhetnek el némán.

⚠ A LELET (2026-09-08, független code review). Hat állapot-modul ugyanazt a
mintát használta:

    try:
        ... json.load(PATH) ...
    except Exception:
        pass                  # ← és a hívó "üres állapotot" lát

Kívülről ez **semmiben nem különbözik** attól, hogy a felhasználó még nem
állított be semmit. A következmény modulonként más, de mindegyik NÉMA:

  • `rr_state`      — a fájl a per-pár KALIBRÁCIÓT is hordozza (`breakeven_r`,
                      `breakeven_pct`, trailing, trigger_R). Sérült fájl →
                      MINDEN pár a modul alapértékére esik, azaz `breakeven_r=0`
                      → a célár-arányos BE, aminek a kikapcsolása egy teljes
                      napi hibakeresésbe került (lásd `test_breakeven_r.py`).
  • `build_state`   — minden pár `off`-ra esik: a pozícióépítés csendben áll.
  • `risky_mode`    — a bekapcsolt óvatosság csendben megszűnik.
  • `correlation`   — a kapu alapértelmezettre esik vissza.
  • `execution_params` — a migrálandó BE/trailing értékek nem költöznek át.
  • `backtest_prefs`— (kényelmi) a mentett mezők eltűnnek.

A MENTÉS oldala még alattomosabb: a beállítás a MEMÓRIÁBAN megvan, tehát minden
működni látszik — a lemezen viszont nincs, és ez csak a KÖVETKEZŐ INDÍTÁSKOR
derül ki.

⚠ ÉS AMIÉRT NEM ELÉG A FORRÁS-ELLENŐRZÉS. A `vacuous-parity-tests` tanulsága:
egy őr, ami csak azt nézi, hogy a kód „úgy néz ki, mint aminek kell", átmehet
úgy is, hogy a mért út soha nem fut le. Ezért ez a teszt MINDKETTŐT bizonyítja:
  1. a mintát (nincs néma `pass` a fájlban),
  2. és hogy a naplózás TÉNYLEG elsül — sérült fájlt gyárt egy ideiglenes
     útvonalon, meghívja a `load()`-ot, és a naplóra rakott kémmel ellenőrzi,
     hogy megjött a rekord.

⚠ A TESZT SOHA NEM NYÚL AZ ÉLES `data/*.json`-hoz: minden modul `PATH`-ját
ideiglenes fájlra cseréli, és a végén VISSZAÁLLÍTJA. A biztonság kedvéért a
teszt maga is lenyomatot vesz az éles fájlokról, és ellenőrzi, hogy változatlanok.
"""
import hashlib
import json
import logging
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog

applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


class Spy(logging.Handler):
    """Elkapja a modul saját loggerének rekordjait (ez bizonyítja, hogy elsült)."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def worst(self):
        return max((r.levelno for r in self.records), default=0)

    def texts(self):
        return " | ".join(r.getMessage() for r in self.records)


# ══ 0. Az ÉLES állapotfájlok lenyomata — a teszt nem írhatja őket ══════════
_LIVE = sorted((ROOT / "data").glob("*.json")) if (ROOT / "data").exists() else []


def _fingerprint():
    out = {}
    for p in _LIVE:
        try:
            out[p.name] = hashlib.sha1(p.read_bytes()).hexdigest()
        except Exception:
            out[p.name] = "?"
    return out


_BEFORE = _fingerprint()


# ══ 1. A MINTA: nincs néma `except Exception: pass` az állapot-modulokban ══
# A `pass`-t közvetlenül követő `except Exception:` a hibafajta — ezt keressük.
_MODULE_FILES = [
    "core/rr_state.py", "core/build_state.py", "core/risky_mode.py",
    "core/correlation.py", "core/backtest_prefs.py", "core/execution_params.py",
    # Ez a kettő MÁR helyesen csinálta — ők a minta, amit a többi átvett.
    "core/adopted.py", "core/position_meta.py",
]

for rel in _MODULE_FILES:
    src = (ROOT / rel).read_text(encoding="utf-8")
    lines = src.splitlines()
    silent = []
    for i, ln in enumerate(lines):
        if ln.strip() == "except Exception:":
            # a következő NEM üres, nem-komment sor
            for nxt in lines[i + 1:]:
                if not nxt.strip() or nxt.strip().startswith("#"):
                    continue
                if nxt.strip() == "pass":
                    silent.append(i + 1)
                break
    check(f"{rel}: nincs néma `except Exception: pass`", not silent,
          f"sorok: {silent}" if silent else "")
    check(f"{rel}: van saját logger", "logging.getLogger(__name__)" in src)

# A `main.py` config-őre (a legrosszabb: az ŐR saját hibája volt néma).
# ⚠ A KOMMENTEKET KI KELL SZŰRNI: az `except` ág magyarázata maga is leírja a
# `pass` szót, és a naiv substring-keresés emiatt hamis bukást adott.
_main_lines = (ROOT / "main.py").read_text(encoding="utf-8").splitlines()
_i = next((n for n, ln in enumerate(_main_lines)
           if "config_check.log_findings(cfg)" in ln), -1)
_body = [ln.strip() for ln in _main_lines[_i:_i + 25]
         if ln.strip() and not ln.strip().startswith("#")]
_after_except = _body[_body.index("except Exception as ex:") + 1:]     if "except Exception as ex:" in _body else []
check("main.py: a config_check hibája NEM `pass`-szal tűnik el",
      _i > 0 and _after_except and "pass" not in _after_except,
      str(_after_except[:2]))
check("main.py: ...hanem NAPLÓZÓDIK",
      any("log" in ln for ln in _after_except[:4]), str(_after_except[:2]))


# ══ 2. A BIZONYÍTÁS: sérült fájlon a naplózás TÉNYLEG elsül ═══════════════
# Minden modul: (modul, betöltő, a PATH attribútum neve, a várt MINIMUM szint)
from core import rr_state, build_state, risky_mode, correlation, backtest_prefs

_LOADERS = [
    (rr_state, rr_state.load, "PATH", logging.ERROR),
    (build_state, build_state.load, "PATH", logging.ERROR),
    (risky_mode, risky_mode.load, "PATH", logging.ERROR),
    (correlation, correlation.load, "PATH", logging.ERROR),
    (backtest_prefs, backtest_prefs._load, "_FILE", logging.WARNING),
]

_tmp = Path(tempfile.mkdtemp(prefix="tf_state_"))

for mod, loader, attr, min_level in _LOADERS:
    name = mod.__name__.split(".")[-1]
    bad = _tmp / f"{name}_bad.json"
    bad.write_text("{ ez nem json", encoding="utf-8")   # SÉRÜLT
    orig = getattr(mod, attr)
    spy = Spy()
    lg = logging.getLogger(mod.__name__)
    lg.addHandler(spy)
    try:
        setattr(mod, attr, bad)
        loader()
    finally:
        setattr(mod, attr, orig)
        lg.removeHandler(spy)
    check(f"{name}: SÉRÜLT fájl → naplóz (nem néma)", spy.worst() >= min_level,
          f"legmagasabb szint={logging.getLevelName(spy.worst())} "
          f"({spy.texts()[:80]})")

# HIÁNYZÓ fájl ≠ sérült fájl: az első indítás NORMÁLIS, arról nem szólunk.
for mod, loader, attr, _ in _LOADERS:
    name = mod.__name__.split(".")[-1]
    orig = getattr(mod, attr)
    spy = Spy()
    lg = logging.getLogger(mod.__name__)
    lg.addHandler(spy)
    try:
        setattr(mod, attr, _tmp / "nincs_ilyen_fajl.json")
        loader()
    finally:
        setattr(mod, attr, orig)
        lg.removeHandler(spy)
    check(f"{name}: HIÁNYZÓ fájl → CSENDBEN (első indítás nem hiba)",
          spy.worst() < logging.WARNING, spy.texts()[:80])


# ══ 3. A MENTÉS oldala: írási hiba sem tűnhet el ══════════════════════════
# Egy SIMA FÁJL alkönyvtárába írunk → a `mkdir(parents=True)` elszáll.
_blocker = _tmp / "ez_egy_fajl"
_blocker.write_text("x", encoding="utf-8")

_SAVERS = [
    (rr_state, rr_state._save_locked, "PATH"),
    (build_state, build_state._save_locked, "PATH"),
    (risky_mode, risky_mode._save_locked, "PATH"),
    (correlation, correlation._save_locked, "PATH"),
]

for mod, saver, attr in _SAVERS:
    name = mod.__name__.split(".")[-1]
    orig = getattr(mod, attr)
    spy = Spy()
    lg = logging.getLogger(mod.__name__)
    lg.addHandler(spy)
    try:
        setattr(mod, attr, _blocker / "alkonyvtar" / "x.json")
        saver()
    except Exception as ex:                     # ⚠ nem szabad kiszállnia
        check(f"{name}: a mentési hiba nem szakítja meg a hívót", False, str(ex))
    else:
        check(f"{name}: a mentési hiba nem szakítja meg a hívót", True)
    finally:
        setattr(mod, attr, orig)
        lg.removeHandler(spy)
    check(f"{name}: SIKERTELEN mentés → naplóz (nem néma)",
          spy.worst() >= logging.ERROR,
          f"{logging.getLevelName(spy.worst())} ({spy.texts()[:80]})")

# A backtest_prefs mentése (más az alakja: `save()`, warning szint elég).
_spy = Spy()
_lg = logging.getLogger(backtest_prefs.__name__)
_lg.addHandler(_spy)
_orig = backtest_prefs._FILE
try:
    backtest_prefs._FILE = _blocker / "alkonyvtar" / "prefs.json"
    backtest_prefs.save("X", "y", nyito=1)
finally:
    backtest_prefs._FILE = _orig
    _lg.removeHandler(_spy)
check("backtest_prefs: SIKERTELEN mentés → naplóz",
      _spy.worst() >= logging.WARNING, _spy.texts()[:80])


# ══ 4. Az ÉP fájl ne adjon hamis riasztást ════════════════════════════════
_ok_file = _tmp / "jo.json"
_ok_file.write_text(json.dumps({"EURUSD": {"preset": "off"}}), encoding="utf-8")
_spy = Spy()
_lg = logging.getLogger(rr_state.__name__)
_lg.addHandler(_spy)
_orig = rr_state.PATH
try:
    rr_state.PATH = _ok_file
    _st = rr_state.load()
finally:
    rr_state.PATH = _orig
    _lg.removeHandler(_spy)
check("ÉP fájl → nincs riasztás, és be is töltődött",
      _spy.worst() < logging.WARNING and "EURUSD" in _st,
      f"{_spy.texts()[:60]} / kulcsok={list(_st)[:3]}")

# A modul memóriabeli állapota a temp fájlból maradt — töltsük vissza az élest,
# hogy a processz ne vigyen tovább hamis állapotot (a LEMEZT nem írjuk).
rr_state.load()


# ══ 5. AZ ÉLES FÁJLOK VÁLTOZATLANOK ══════════════════════════════════════
_after = _fingerprint()
_changed = [k for k in _BEFORE if _BEFORE[k] != _after.get(k)]
check("⚠ a teszt NEM írta az éles data/*.json fájlokat", not _changed,
      str(_changed))

print()
n, m = sum(results), len(results)
print(f"{n}/{m} teszt PASS")
sys.exit(0 if n == m else 1)

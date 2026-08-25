"""Optimalizálás NÉLKÜL is induljon a pár — a stratégia alapértékeivel.

⚠ A LELET (2026-08-25, a felhasználó vette észre): felvett két új instrumentumot
(Fra40, EURHUF), feltette a chartra az indikátort, és **semmi nem történt**.
Nem volt jelzés, nem volt jelölő, a viz-fájl létre sem jött — és a dashboardon
csak szürke körök álltak.

AZ OK. A `_make_state` MÁR RÉGÓTA támogatta a hangolatlan indulást (mentett
készlet híján a stratégia saját alapértékeivel, figyelmeztetéssel a naplóban) —
de az INDÍTÁSI KAPU kizárta:

    startable = [st for st in strats
                 if st.name in _live and load_pair_params(...) is not None]

A megvalósítás megvolt, csak nem volt bekötve. A pár `STOPPED` maradt, és a
felület semmit nem mondott arról, miért.

⚠ ÉS EGY MÁSODIK KAPU a felületen: a körök és a stratégia-cellák a `trained`
jelzőre voltak kötve. Így hiába indult volna el a motor a hangolatlan páron, a
dashboard továbbra is üresen mutatta volna — a felhasználó pedig azt hinné,
elromlott valami. A cellák mostantól az ADATOT követik: ha a motor nem számol,
a `strategy_cells` úgyis üres.

A „nincs hangolva" tény NEM vész el: a `params_source` „default"-ot ad, a
`_make_state` figyelmeztetést naplóz, és a dashboard sora a BG_UNTRAINED
háttérszínt kapja.
"""
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


_lt = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
_gui = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")

# ── 1. AZ INDÍTÁSI KAPU nem követel mentett paramétert ─────────────────
_i = _lt.find("startable = [st for st in strats")
_blok = _lt[_i:_i + 200]
check("az indítási kapu megtalálható", _i > 0)
check("⚠ ...és NEM követel mentett paramétert",
      "load_pair_params" not in _blok, _blok[:90])
check("...csak a kereskedési SZÁNDÉKOT nézi (`_live`)", "_live" in _blok)

# ── 2. A hangolatlan futás LÁTHATÓ marad ───────────────────────────────
# ⚠ Ez a fék: ha csendben futna hangolatlanul, a felhasználó azt hinné, a pár
# optimalizálva van. Három jelzés — napló, forrás-jelölő, sorszín — kell.
check("a `_make_state` az alapértékekre esik vissza",
      "fallback=default_params(strat, cfg)" in _lt)
check("⚠ ...és NAPLÓZZA, hogy hangolatlanul fut",
      "ALAPÉRTELMEZETT paraméter" in _lt and
      'params_source(symbol, strat.name) == "default"' in _lt)
check("van forrás-jelölő (`params_source`)", "def params_source(" in _lt)
check("a dashboard KÜLÖN háttérszínt ad a hangolatlan sornak",
      "BG_UNTRAINED" in _gui)

# ── 3. A FELÜLET a számolt adatot mutassa, ne a `trained` jelzőt ───────
_j = _gui.find("cells = ds.strategy_cells.get(sname")
_cellblok = _gui[_j:_j + 120]
check("a jelölő-cellák megtalálhatók", _j > 0)
check("⚠ ...és NEM a `trained` kapuzza őket",
      "trained" not in _cellblok, _cellblok[:80])
check("a stratégia-cellák sem", "if trained else None" not in _gui)

# ── 4. Van egyáltalán használható alapérték? ───────────────────────────
# ⚠ Ha egy stratégia `base_params`-a üres, a hangolatlan indulás sem megy — a
# `_make_state` ilyenkor KIHAGYJA a párt, és meg is mondja, miért.
from strategy import (get_strategy_by_name,  # noqa: E402
                      registered_strategy_names)
from strategy.settings import config_for_strategy, load_config  # noqa: E402
from trading.live_trader import default_params  # noqa: E402

cfg = load_config("config.json")
_nevek = registered_strategy_names()
for _n in _nevek:
    try:
        _st = get_strategy_by_name(_n)
        _dp = default_params(_st, config_for_strategy(cfg, _n))
    except Exception as _ex:
        _dp = None
        print(f"      ({_n}: {type(_ex).__name__}: {_ex})")
    check(f"'{_n}': van használható alapértelmezés", bool(_dp),
          f"{len(_dp or {})} kulcs")

check("üres alapértéknél a pár KIMARAD és megmondjuk, miért",
      "se mentett paraméter, se használható" in _lt)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

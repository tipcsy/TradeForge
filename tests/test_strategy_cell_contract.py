"""A cella-hookok SZERZŐDÉSE — minden stratégiára, egységesen.

⚠ A LELET (2026-08-25, a felhasználó naplójából): a futó program percenként
ontotta a sorokat —

    UK100/bollinger_squeeze_breakout: a stratégia live_cells hookja hibázik
    ('dict' object has no attribute 'text') — a sor jelzés-cellái üresen maradnak.

A SZERZŐDÉS. A `live_cells` és a `compute_display` **lapos** szótárat ad:
`{stádium_kulcs: Cell}`. A motor pontosan így bontja szét:

    {k: (c.text, c.color) for k, c in cells.items()}

A `bollinger_squeeze_breakout` és a `candle_level_break` viszont egy szinttel
mélyebben adta vissza (`{"marks": {stádium: Cell}}`), tehát a `c` egy szótár
volt, és a `c.text` elszállt. Mindkettő a két LEGÚJABB stratégia — vázlatból
írva, kitalált interfészre. Ugyanaz a gyökér, ami a Bollinger bevezetésekor is
előjött.

⚠ ÉS AMIÉRT EDDIG CSAK FÉLIG LÁTSZOTT: a MOTOR útja beszédes (`_warn_once`), a
KIJELZÉS útja viszont `except Exception: pass`-szal nyelte el ugyanezt a hibát
(`dashboard/gui.py`). A táblázat üres cellái pontosan úgy néznek ki, mint egy
stratégia, ami épp nem jelez — a felhasználó nem tudhatta, hogy hibáról van szó.

Ez a teszt a SZERZŐDÉST méri, nem egy konkrét stratégiát: minden bejegyzett
stratégiára lefut, tehát egy új stratégia ugyanezt a hibát nem hozhatja vissza.
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


from strategy import get_strategy_by_name, registered_strategy_names
from strategy.base import Cell, MarketData
from strategy.settings import config_for_strategy, load_config

cfg = load_config("config.json")


def _md(strat, symbol="Ger40"):
    """Minimális piaci adat: ÜRES gyertyakészlet.

    ⚠ Szándékosan üres. Így minden stratégia a saját „nincs mit mutatni" ágára
    fut — és épp ott is deklarálja a cellák alakját. A hibás alak mindkét
    stratégiánál MÁR ITT látszik, valódi árfolyamadat nélkül."""
    p = dict(strat.base_params(config_for_strategy(cfg, strat.name)) or {})
    p.setdefault("symbol", symbol)
    p.setdefault("point_size", 0.01)
    return MarketData(symbol=symbol, params=p, bars={})


def _lapos(cellak, hol, nev):
    """A visszaadott szótár MINDEN értéke `Cell`-e?"""
    if not isinstance(cellak, dict):
        check(f"'{nev}'.{hol} szótárat ad", False, type(cellak).__name__)
        return False
    rossz = {k: type(v).__name__ for k, v in cellak.items()
             if not isinstance(v, Cell)}
    check(f"⚠ '{nev}'.{hol} LAPOS: minden érték Cell", not rossz,
          str(rossz) if rossz else "")
    if rossz:
        return False
    # A motor pontosan ezt teszi — ha ez elszáll, a sor üresen marad.
    try:
        {k: (c.text, c.color) for k, c in cellak.items()}
    except Exception as ex:
        check(f"'{nev}'.{hol} szétbontható (a motor útja)", False,
              f"{type(ex).__name__}: {ex}")
        return False
    return True


nevek = registered_strategy_names()
check("van bejegyzett stratégia", bool(nevek), ", ".join(nevek))

for nev in nevek:
    strat = get_strategy_by_name(nev)
    md = _md(strat)

    # ── compute_display ────────────────────────────────────────────────
    try:
        cd = strat.compute_display(md)
    except Exception as ex:
        cd = None
        check(f"'{nev}'.compute_display lefut üres adaton", False,
              f"{type(ex).__name__}: {ex}")
    if cd is not None:
        check(f"'{nev}'.compute_display lefut üres adaton", True)
        _lapos(cd, "compute_display", nev)

    # ── live_cells ─────────────────────────────────────────────────────
    # A motor a stratégia SAJÁT jelzés-állapotával hívja.
    try:
        st = strat.new_signal_state(md.symbol)
    except Exception:
        st = None
    try:
        lc = strat.live_cells(st, md)
    except Exception as ex:
        lc = None
        check(f"'{nev}'.live_cells lefut üres adaton", False,
              f"{type(ex).__name__}: {ex}")
    if lc is not None:
        check(f"'{nev}'.live_cells lefut üres adaton", True)
        _lapos(lc, "live_cells", nev)

    # ── A KULCSOK a deklarált stádiumok ────────────────────────────────
    # ⚠ Enélkül a cellák megvolnának, de MÁS kulcson — a jelölő-oszlop
    # stádiumonként keresi őket, és néma üres körök maradnának. A rossz kulcs
    # ugyanolyan láthatatlan, mint a rossz alak.
    stagek = set()
    for col in strat.columns():
        for kulcs, _felirat in (getattr(col, "stages", ()) or ()):
            stagek.add(kulcs)
    if stagek and isinstance(lc, dict):
        hianyzo = stagek - set(lc.keys())
        check(f"⚠ '{nev}': a live_cells fedi a deklarált stádiumokat",
              not hianyzo, f"hiányzik: {sorted(hianyzo)}" if hianyzo else "")
    if stagek and isinstance(cd, dict):
        hianyzo = stagek - set(cd.keys())
        check(f"⚠ '{nev}': a compute_display is fedi őket",
              not hianyzo, f"hiányzik: {sorted(hianyzo)}" if hianyzo else "")

# ── A KIJELZÉS útja se legyen néma ─────────────────────────────────────
# ⚠ A motor útja `_warn_once`-szal szól (ez hozta elő a leletet). A dashboard
# ugyanezt a hívást `except Exception: pass`-szal nyelte el, tehát a hiba
# FELÉT nem lehetett látni.
_gui = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
_i = _gui.find("cells = st.compute_display(smd)")
check("megvan a dashboard cella-útja", _i > 0)
_blok = _gui[_i:_i + 700]
check("⚠ a kijelzés-út hibája NEM néma",
      "except Exception:\n                    pass" not in _blok,
      _blok[_blok.find("except"):][:60].replace("\n", " "))
check("...és MEGNEVEZI a stratégiát", "compute_display" in _blok and
      ("_warn_once" in _blok or "warning" in _blok))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

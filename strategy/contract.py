"""
A STRATÉGIA-SZERZŐDÉS: meddig kompatibilis egy stratégia a programmal?

⚠ A KÉRÉS (2026-09-02, a `.tfs` csomagolás 3/b kérdésére adott válaszból):
„Igen a betöltéskor közölje, hogy inkompatibilis verziót akarunk használni.
(Dobjon hibát. Ez viszont felvet egy új kérdéskört, meddig kompatibilis egy
stratégia a programmal? Erre kellene egy kidolgozás, vagy egy szigorúbb
verziókezelés.)"

Ez a modul az a kidolgozás. Két dolgot ad:

  1. egy SZÁMOT, amit a stratégia deklarál (`Strategy.api`), és amit a program
     betöltéskor összevet a sajátjával — ez a kapu;
  2. egy UJJLENYOMATOT a tényleges interfészről, ami MEGFOGJA, ha a szerződés
     megváltozik, de a szám nem — ez az, ami miatt az 1. pont nem hazudik.

── MIÉRT NEM ELÉG A SZÁM ÖNMAGÁBAN ──────────────────────────────────────
Egy verziószám pontosan annyit ér, amennyire fegyelmezetten emelik. Ebben a
projektben ez már egyszer megbukott: a `version.py` ÖT funkción át nem
emelkedett, miközben a commitok új verziót hirdettek (lásd
`tests/test_version_discipline.py`). Ugyanez a hiba itt sokkal drágább lenne: a
`.tfs` csomag `api: 1`-et mondana, a program `1`-et várna, és mégis más
szerződésre épülne — a stratégia betöltődne, majd valahol mélyen, futás közben
törne el, vagy ami rosszabb, NÉMÁN mást csinálna.

Ezért a szám mellé egy ujjlenyomat is jár. Ugyanaz a trükk, ami a keresési tér
elmozdulását fogja meg az optimalizálónál (v3.25.1): nem megakadályozza a
változást, hanem LÁTHATÓVÁ teszi, és döntést kényszerít.

── MI KÉNYSZERÍT VERZIÓEMELÉST (`STRATEGY_API` + 1) ─────────────────────
Az, ami egy MA MŰKÖDŐ stratégiát elromlana:

  * egy absztrakt metódus törlése vagy átnevezése;
  * egy meglévő metódus ALÁÍRÁSÁNAK szűkítése (új kötelező paraméter, egy
    paraméter jelentésének megváltozása);
  * a visszaadott ALAK megváltozása (pl. ha a `sl_tp_points` hármast adna);
  * a stratégia-config kötelező szekcióinak átrendezése.

── MI NEM ────────────────────────────────────────────────────────────────
Az, ami egy régi stratégiát változatlanul hagy:

  * ÚJ hook felvétele alapértelmezett megvalósítással (a régi stratégia nem is
    tud róla, és nem is kell tudnia);
  * új mező a `MarketData`-ban (aki nem olvassa, nem veszi észre);
  * új, alapértékkel rendelkező config-kulcs;
  * a KERET belső átszervezése (pl. a v3.29.0-s csomag-szétválasztás: a
    stratégiák helye változott, a szerződés nem).

⚠ A KETTŐ KÖZÖTTI HATÁRT EMBER HÚZZA MEG, nem a gép. Az ujjlenyomat csak azt
mondja meg, hogy VALAMI változott; hogy törő-e, azt a fenti lista alapján kell
eldönteni — és a döntést a `tests/test_strategy_contract.py` kényszeríti ki.

TISZTA modul: se tkinter, se MT5, se fájl.
"""

from __future__ import annotations

import hashlib
import inspect


def _surface() -> list:
    """A szerződés SORAI — determinisztikusan, olvashatóan.

    Nem a `base.py` bájtjait hasheljük: az minden kommentjavításra elmozdulna, és
    egy hét alatt megtanulnánk figyelmen kívül hagyni. Csak azt vesszük, ami a
    stratégia felől TÉNYLEGESEN látszik: a publikus metódusok neve és aláírása,
    hogy melyik absztrakt, és a `MarketData` mezőnevei (ez a KERET → stratégia
    adatszállítója)."""
    from strategy.base import Strategy, MarketData

    sorok = []
    for nev, tag in sorted(vars(Strategy).items()):
        if nev.startswith("_"):
            continue
        if isinstance(tag, property):
            sorok.append(f"property {nev}")
            continue
        if not callable(tag):
            continue
        try:
            alairas = str(inspect.signature(tag))
        except (TypeError, ValueError):
            alairas = "(?)"
        absztrakt = "abstract " if getattr(tag, "__isabstractmethod__", False) else ""
        sorok.append(f"{absztrakt}def {nev}{alairas}")
    mezok = sorted(getattr(MarketData, "__dataclass_fields__", {}))
    sorok.append("MarketData(" + ", ".join(mezok) + ")")
    return sorok


def surface_text() -> str:
    """A szerződés ember által olvasható alakja — ezt írja ki a bukó teszt, hogy
    ne kelljen találgatni, MI változott."""
    return "\n".join(_surface())


def fingerprint() -> str:
    """A szerződés 12 karakteres ujjlenyomata."""
    return hashlib.sha1(surface_text().encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# A KAPU: elfogadható-e egy stratégia által deklarált API-verzió?
# ---------------------------------------------------------------------------

def compatible(api) -> tuple:
    """`(elfogadható_e, indok)` — az indok ÜRES, ha rendben.

    ⚠ A KÉT IRÁNY MÁS HIBA, és mást is kell mondani róluk:

    * `api > STRATEGY_API` — a stratégia ÚJABB programhoz készült. Itt nincs mit
      tenni a stratégiával; a PROGRAMOT kell frissíteni.
    * `api < STRATEGY_API_MIN` — a stratégia RÉGEBBI szerződésre épül, amit már
      nem szolgálunk ki. Itt a stratégiát kell átírni.

    Egy közös „inkompatibilis" üzenet mindkét esetben rossz irányba küldene."""
    from core.i18n import t as _t
    from strategy.base import STRATEGY_API, STRATEGY_API_MIN
    try:
        v = int(api)
    except (TypeError, ValueError):
        return False, _t("contract.err.not_int", value=repr(api))
    if v > STRATEGY_API:
        return False, _t("contract.err.too_new", api=v, program=STRATEGY_API)
    if v < STRATEGY_API_MIN:
        return False, _t("contract.err.too_old", api=v, minimum=STRATEGY_API_MIN)
    return True, ""

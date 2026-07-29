"""
„Minden instrumentumra" — MELYIK beállítás terjed szét, és mi ennek a tétje.

A beállítás-ablak egyetlen pipával rá tudja húzni a módosításokat az összes
instrumentumra. A naiv megvalósítás (az ablak TELJES állapotának átmásolása)
veszélyes lenne: aki csak a vizualizációs pipát akarja mindenhová, annak a
KÖTÉS-MÓDJA is ráíródna minden párra — vagyis egyetlen kattintás valódi
megbízásokat kapcsolhatna be 10 instrumentumon.

Ezért a szabály: **csak azok a sorok terjednek, amiket az ablakban ténylegesen
megváltoztattál.** Ez a modul dönti el, melyek ezek — tiszta függvényekkel, se
tkinter, se config, se MT5 —, hogy a döntés egy sorban tesztelhető legyen.

Az ablak állapotát egy „pillanatkép" szótár írja le (sor-azonosító → érték); a
kezdeti és a mostani pillanatkép különbsége adja a terjedő sorokat.
"""

from __future__ import annotations

# sor-azonosító → (emberi név, PÉNZT érint-e)
#
# A „pénzt érint" jelölés nem díszítés: ezek a sorok kapnak külön figyelmeztetést
# a megerősítő ablakban. Az `strategies` azért van benne, mert egy stratégia
# bekapcsolása minden páron új belépőket nyithat; a `mode` pedig azért, mert a
# „Valódi" mód valódi megbízásokat küld.
ROWS = {
    "strategies": ("Aktív stratégia",       True),
    "viz":        ("Vizualizáció látszik",  False),
    "trades":     ("Kötések látszanak",     False),
    "mode":       ("Kötés módja",           True),
    "market":     ("Piac-előszűrő",         False),
    "market_viz": ("Piac-állapot sáv",      False),
}


def changed_rows(initial: dict, current: dict) -> set:
    """A MEGVÁLTOZOTT sorok azonosítói. Csak az ISMERT (ROWS-beli) kulcsokat
    nézzük: egy jövőbeli, véletlenül a pillanatképbe került segédmező ne
    terjedjen szét némán az összes instrumentumra."""
    return {k for k in ROWS
            if k in initial and k in current and initial[k] != current[k]}


def label_of(row: str) -> str:
    return ROWS.get(row, (row, False))[0]


def affects_money(rows) -> bool:
    """Van-e a terjedő sorok közt pénzt érintő? A hívó ez alapján ad nyomatékosabb
    figyelmeztetést."""
    return any(ROWS.get(r, ("", False))[1] for r in (rows or ()))


def summary(rows) -> str:
    """A megerősítő ablak sorlistája — a pénzt érintő tételek megjelölve.

    Rendezve, hogy ugyanaz a változás-halmaz mindig ugyanúgy nézzen ki."""
    out = []
    for r in sorted(rows or ()):
        name, money = ROWS.get(r, (r, False))
        out.append(f"   • {name}" + ("   ⚠ PÉNZT ÉRINT" if money else ""))
    return "\n".join(out)


def targets(pairs: dict, symbol: str, apply_all: bool) -> list:
    """Mely instrumentumokra alkalmazzuk. `apply_all=False` → csak a sajátjára.

    A LETILTOTT párokat is beleértve: a beállítások (viz, piac-előszűrő,
    kötés-mód) a backtesztet és a későbbi élesítést is érintik, ezért egy
    „minden instrumentumra" nem hagyhatja ki őket csendben. A saját szimbólum
    MINDIG az első — a hívó így stabil sorrendben dolgozhat."""
    others = sorted(s for s, pc in (pairs or {}).items()
                    if s != symbol and isinstance(pc, dict))
    return [symbol] + (others if apply_all else [])

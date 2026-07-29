"""
Melyik dashboard-ELRENDEZÉS legyen aktív. Configból választható.

    "dashboard": { "layout": "classic" | "flat" | "grouped" }

`classic`  — a MOSTANI tábla (egy sor = egy instrumentum, a stratégia-cellák
             egymás mellett). Ez az ALAPÉRTELMEZÉS: egy meglévő config.json
             változatlanul indul, a felület nem mozdul meg magától.
`flat`     — egy sor = egy (instrumentum × stratégia). Semmi nincs elrejtve; a
             sorrend fontosság szerinti (ami él, az felül), a nyitott pozíció
             ÉLŐ eredménnyel látszik. (`dashboard.flat_rows`)
`grouped`  — instrumentum-sor + összecsukható stratégia-alsorok.
             (`dashboard.grouped_rows`)

**Miért van egyáltalán választás.** A `grouped` a fejlesztés közben megbukott a
felhasználónál: csukott állapotban nem látszott, melyik stratégia hol tart, és a
nyitott pozíciók sem — csak a lezárt kötések összege. Ezért mindig mindent ki
kellett volna nyitni, és akkor a fa csak plusz üres instrumentum-sorokat ad. A
`flat` erre a válasz. A `grouped` azért maradt bent, mert a felhasználó KÉRTE a
választás lehetőségét — nem azért, mert bele lett fektetve munka.

**Ennek költsége van, és ezt nyíltan írjuk ide:** két elrendezés = minden
jövőbeli oszlop/kapu-változást KÉTSZER kell megcsinálni. Ha a döntés megszilárdul,
a vesztes ág törlendő (a `grouped_rows` + a hozzá tartozó teszt), és ez a modul
két értékűre egyszerűsödik.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

CLASSIC = "classic"
FLAT = "flat"
GROUPED = "grouped"
MODES = (CLASSIC, FLAT, GROUPED)

DEFAULT = CLASSIC

_warned: set = set()


def resolve(cfg: dict) -> str:
    """Az érvényes elrendezés-mód. Hiányzó kulcs → `classic` (a mostani felület).

    ÉRVÉNYTELEN érték esetén az alapértelmezésre esünk vissza, de EGYSZER
    figyelmeztetünk. A néma elnyelés lenne a rossz válasz: egy elgépelt
    `"flatt"` csendben a régi felületet adná, és azt hinnéd, nem működik a
    beállítás."""
    val = ((cfg or {}).get("dashboard") or {}).get("layout")
    if val is None:
        return DEFAULT
    norm = val.strip().lower() if isinstance(val, str) else None
    if norm in MODES:
        return norm
    key = str(val)
    if key not in _warned:
        _warned.add(key)
        log.warning("Ismeretlen dashboard-elrendezés a configban: %r. Érvényes "
                    "értékek: %s. Az alapértelmezést (%s) használom.",
                    val, ", ".join(MODES), DEFAULT)
    return DEFAULT


def is_per_strategy_row(mode: str) -> bool:
    """Ebben a módban a SOR a (instrumentum × stratégia) párhoz tartozik?

    A `flat` és a `grouped` gyerek-sorai igen, a `classic` nem. A hívó ez alapján
    dönti el, hogy per-stratégia kell-e adatot gyűjtenie (kapu-állapotok,
    per-stratégia minőség és P&L) — a `classic` úton ez a munka kihagyható."""
    return mode in (FLAT, GROUPED)

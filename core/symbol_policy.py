"""
Szimbólum-szintű belépési házirend — mit tehet EGY páron TÖBB stratégia egyszerre.

Egy instrumentumon több stratégia is futhat (pl. `wpr_sma` + `ml_ai`), külön
magickel. HEDGE számlán ezek egymástól függetlenül nyithatnak — akár EGYMÁSSAL
SZEMBE is. Ez nem feltétlenül baj (két önálló modell két önálló tézise), de fizetsz
érte: két spread, két jutalék, és a két pozíció részben kioltja egymást.

Ezért a viselkedés VÁLASZTHATÓ, nem bedrótozott:

    "independent"     — a stratégiák egymástól függetlenek (a v1.69.0–1.99.0
                        alapértelmezése; a több-stratégia előtti viselkedés mása)
    "one_per_symbol"  — szimbólumonként EGY pozíció: aki előbb jelez, az köt
    "no_opposite"     — azonos irányba többen is nyithatnak (piramis), de
                        ELLENTÉTES irányba nem   ← **ALAPÉRTELMEZÉS (v2.0.0)**

Az alapértelmezés v2.0.0-ban `independent`-ről `no_opposite`-ra változott. MIÉRT:
a házirend v1.69.0 óta készen állt, teszteltten és bekötve — de a `config.json`-ba
sosem került bele a kulcs, az alapértelmezés pedig a megengedő `independent` volt,
így a mechanizmus **nyolc napon át némán tétlen maradt**. Ugyanaz a minta, ami a
2026-08-05-i átvizsgálás gyökere volt: a config csak az ELTÉRÉST rögzítette, tehát
egy kész funkció úgy nézett ki, mintha nem is lenne.

A váltás IRÁNYA teszi biztonságossá: a házirend csak SZIGORÍTHAT (lásd lent), tehát
egy alapértelmezés-váltás sosem nyithat váratlanul új pozíciót — legfeljebb kihagy
egyet, és azt meg is indokolja a naplóban.

Config (a per-pár nyer a globális fölött):

    "trading":            { "same_symbol_policy": "independent" }
    "pairs": { "Ger40":   { "same_symbol_policy": "no_opposite" } }

FONTOS: a stratégia SAJÁT nyitott pozíciója MINDIG blokkol (ez a régi, per-stratégia
szabály — „ne halmozzon ugyanarra a párra"). A házirend ehhez ad HOZZÁ: sosem enged
meg többet, mint az `independent`, csak szigoríthat. Így a bekapcsolása nem tud
váratlanul új pozíciót nyitni.

A „mi könyvünk" = a MOTOR által kezelt pozíciók az adott szimbólumon: bármelyik
stratégiánk magicjével nyitottak + a felületről hozzárendelt (örökbefogadott)
kéziek. Egy hozzá nem rendelt, idegen kézi pozícióról nem feltételezzük, hogy a
motornak kellene róla döntenie.
"""

from __future__ import annotations

from core.i18n import t as _t

import logging

log = logging.getLogger(__name__)

INDEPENDENT = "independent"
ONE_PER_SYMBOL = "one_per_symbol"
NO_OPPOSITE = "no_opposite"
POLICIES = (INDEPENDENT, ONE_PER_SYMBOL, NO_OPPOSITE)

# v2.0.0: `independent` → `no_opposite` (lásd a modul-doksit). Csak szigorít, tehát
# a váltás sosem nyit váratlanul új pozíciót.
DEFAULT = NO_OPPOSITE


_warned: set = set()


def resolve(cfg: dict, symbol: str) -> str:
    """Az adott instrumentumra érvényes házirend: per-pár → globális → alapértelmezés.

    ÉRVÉNYTELEN érték (elgépelés) esetén a szokásos rétegzés folytatódik — de EGYSZER
    figyelmeztetünk. A néma elnyelés lenne a rossz válasz: az elgépelt házirend
    csendben mást csinálna, mint amit a felhasználó gondol."""
    pair = ((cfg.get("pairs") or {}).get(symbol) or {}).get("same_symbol_policy")
    glob = (cfg.get("trading") or {}).get("same_symbol_policy")
    for v, where in ((pair, symbol), (glob, "trading")):
        if v is None:
            continue
        norm = v.strip().lower() if isinstance(v, str) else None
        if norm in POLICIES:
            return norm
        key = (where, str(v))
        if key not in _warned:
            _warned.add(key)
            log.warning("Ismeretlen szimbólum-házirend a configban (%s): %r. "
                        "Érvényes értékek: %s. Ezt a szintet KIHAGYOM.",
                        where, v, ", ".join(POLICIES))
    return DEFAULT


def blocks(policy: str, signal: str, book_dirs) -> "str | None":
    """Blokkolja-e a házirend az ÚJ belépőt? Az indoklás szövege, vagy None.

    `signal`: "BUY" | "SELL" — a most nyitandó irány.
    `book_dirs`: a MÁS stratégiáink nyitott pozícióinak iránya ugyanezen a
        szimbólumon, pl. `["BUY", "SELL"]`. (A saját pozíciót a hívó külön
        kezeli — az mindig blokkol.)

    Tiszta függvény: se MT5, se config — így a döntés egy sorban tesztelhető."""
    dirs = [d for d in (book_dirs or []) if d in ("BUY", "SELL")]
    if not dirs:
        return None
    if policy == ONE_PER_SYMBOL:
        return _t("policy.one_per_symbol")
    if policy == NO_OPPOSITE:
        if any(d != signal for d in dirs):
            return _t("policy.no_opposite")
        return None
    return None          # independent — nem szólunk bele

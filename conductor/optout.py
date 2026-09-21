"""AMIT NEM BÁNTUNK — a karmesterből kivont cellák.

⚠ MIÉRT KELL. Nem minden cellát akarsz optimalizálni. Van, ami kísérlet, van,
amit kézzel hangoltál be, és van, aminél a több órás keresés egyszerűen nem éri
meg. A karmester viszont MÉR, és a mérésből következik a javaslat: a hangolatlan
cella minden körben „optimalizáld" javaslatot kapna, az avult készlet ugyanúgy.
Egy javaslat, amit sosem fogadsz el, nem semleges: megtanít arra, hogy a
postaládát át lehet lapozni — és akkor a mellette álló FONTOS javaslat is
elvész.

⚠ A KIZÁRÁS NEM „ELVETÉS". Az elvetés egy KONKRÉT javaslatról mond nemet, és
türelmi idő után visszatér (`inbox.reject_cooldown_days`). A kizárás egy TARTÓS
döntés a cellárról: a javaslat létre sem jön, a sorba be sem kerülhet.

── A FELOLDÁS SORRENDJE ───────────────────────────────────────────────────
  1. CELLA-szint: `pairs.<SYM>.no_optimize.<stratégia>` — ha van, ez dönt.
  2. STRATÉGIA-szint: `conductor.no_optimize.<stratégia>` — az alapértelmezés
     minden páron.
  3. Egyik sincs → `False` (optimalizálható).

A cella-szintű `false` tehát VISSZAKAPCSOLJA azt, amit a stratégia-szintű `true`
kizárt — ezért kell a két szintet megkülönböztetni. A „nincs bejegyzés" és a
„kifejezetten `false`" NEM ugyanaz: az első követi az alapértelmezést, a
második felülírja. Ezt a különbséget egyetlen `bool()` hívás elmosná.

⚠ TÍPUSHŰ OLVASÁS. A `x or alapértelmezés` minta itt némán hazudna: a `False`
hamis, tehát az alapértelmezésre esne vissza — vagyis a KIKAPCSOLÁS kapcsolna
BE valamit. Ez a `conductor/config.py`-ban már egyszer megtörtént; itt
`_ertek()` olvas, ami a `None`-t (nincs bejegyzés) megkülönbözteti a `False`-tól,
és az értelmezhetetlen értékre SZÓL, nem találgat.

⚠ TISZTA MODUL: csak a config dict-tel dolgozik — se fájl, se MT5, se felület.
Az írás a hívóé (`console_cmd` menti a configot), ahogy a `run_state`-nél is.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

KULCS = "no_optimize"

# Honnan jött a válasz — stabil kódok, a felirat ezekből fordul.
FORRAS_CELLA     = "cell"
FORRAS_STRATEGIA = "strategy"
FORRAS_NINCS     = ""


def _ertek(nyers) -> "bool | None":
    """`True` / `False` / `None` (= nincs érvényes bejegyzés).

    A JSON-ban kézzel átírt `"true"` szöveg is előfordul — azt elfogadjuk, de a
    valódi szemétre SZÓLUNK: a néma alapértelmezés pont az a hiba, ami elől ez
    az egész modul védeni akar."""
    if nyers is None:
        return None
    if isinstance(nyers, bool):
        return nyers
    if isinstance(nyers, str):
        sz = nyers.strip().lower()
        if sz in ("true", "1", "igen", "yes", "on"):
            return True
        if sz in ("false", "0", "nem", "no", "off"):
            return False
    log.warning("conductor.optout: értelmezhetetlen %r érték — figyelmen kívül "
                "hagyva (a cella optimalizálható marad)", nyers)
    return None


def _cella_tabla(cfg: dict, symbol: str) -> dict:
    p = (cfg.get("pairs") or {}).get(symbol)
    t = p.get(KULCS) if isinstance(p, dict) else None
    return t if isinstance(t, dict) else {}


def _strategia_tabla(cfg: dict) -> dict:
    b = cfg.get("conductor")
    t = b.get(KULCS) if isinstance(b, dict) else None
    return t if isinstance(t, dict) else {}


# ---------------------------------------------------------------------------
# OLVASÁS
# ---------------------------------------------------------------------------

def forras(cfg: dict, symbol: str, strategy: str) -> str:
    """MELYIK szint döntött? `cell` · `strategy` · `""` (egyik sem).

    ⚠ A FELÜLETNEK EZ KELL. Egy pipa, ami nem mondja meg, HONNAN kapta az
    értékét, hazudik: a felhasználó azt hiszi, ezen a cellán állította be, pedig
    a stratégia alapértelmezését látja."""
    if _ertek(_cella_tabla(cfg, symbol).get(strategy)) is not None:
        return FORRAS_CELLA
    if _ertek(_strategia_tabla(cfg).get(strategy)) is not None:
        return FORRAS_STRATEGIA
    return FORRAS_NINCS


def no_optimize(cfg: dict, symbol: str, strategy: str) -> bool:
    """Ki van-e zárva EZ a cella az optimalizálásból?"""
    v = _ertek(_cella_tabla(cfg, symbol).get(strategy))
    if v is not None:
        return v
    v = _ertek(_strategia_tabla(cfg).get(strategy))
    return bool(v) if v is not None else False


def cella_ertek(cfg: dict, symbol: str, strategy: str) -> "bool | None":
    """A CELLA saját bejegyzése — `None`, ha a stratégiát követi."""
    return _ertek(_cella_tabla(cfg, symbol).get(strategy))


def strategia_ertek(cfg: dict, strategy: str) -> "bool | None":
    """A STRATÉGIA alapértelmezése — `None`, ha nincs bejegyzés."""
    return _ertek(_strategia_tabla(cfg).get(strategy))


def kizartak(cfg: dict, *, strategies_of=None) -> list:
    """`[(symbol, strategy, forrás)]` — MINDEN kizárt cella, rendezve.

    ⚠ HOGY LÁTHASD, MIT ZÁRTÁL KI. Egy tartós döntés, amit sehol nem lehet
    egyben megnézni, lassan elfelejtődik — és egy fél év múlva nem érted, miért
    nem javasol semmit a karmester arra a cellára."""
    ki = []
    for sym, p in sorted((cfg.get("pairs") or {}).items()):
        if not isinstance(p, dict):
            continue
        nevek = []
        if strategies_of is not None:
            try:
                nevek = list(strategies_of(sym) or [])
            except Exception:
                nevek = []
        else:
            nevek = [n for n in (p.get("strategies") or []) if n]
        for n in sorted(set(nevek)):
            if no_optimize(cfg, sym, n):
                ki.append((sym, n, forras(cfg, sym, n)))
    return ki


# ---------------------------------------------------------------------------
# ÍRÁS — a configot a HÍVÓ menti (ugyanúgy, mint a `run_state`-nél)
# ---------------------------------------------------------------------------

def set_cella(cfg: dict, symbol: str, strategy: str, ertek: "bool | None") -> bool:
    """A cella saját bejegyzése. `None` → törlés (= kövesse a stratégiát).

    Visszaad: VÁLTOZOTT-e. ⚠ A hívó csak akkor mentsen, ha igen — egy fölösleges
    mentés minden körben átírná a config fájlt."""
    p = (cfg.get("pairs") or {}).get(symbol)
    if not isinstance(p, dict):
        return False
    t = p.get(KULCS)
    if not isinstance(t, dict):
        t = {}
    regi = _ertek(t.get(strategy))
    if regi == ertek and (strategy in t) == (ertek is not None):
        return False
    if ertek is None:
        t.pop(strategy, None)
    else:
        t[strategy] = bool(ertek)
    # ⚠ AZ ÜRES TÁBLÁT KITAKARÍTJUK: egy `"no_optimize": {}` blokk a configban
    # azt sugallná, hogy van itt valami beállítás — pedig nincs.
    if t:
        p[KULCS] = t
    else:
        p.pop(KULCS, None)
    return True


def set_strategia(cfg: dict, strategy: str, ertek: "bool | None") -> bool:
    """A stratégia alapértelmezése minden páron. `None` → törlés."""
    b = cfg.get("conductor")
    if not isinstance(b, dict):
        b = {}
        cfg["conductor"] = b
    t = b.get(KULCS)
    if not isinstance(t, dict):
        t = {}
    regi = _ertek(t.get(strategy))
    if regi == ertek and (strategy in t) == (ertek is not None):
        return False
    if ertek is None:
        t.pop(strategy, None)
    else:
        t[strategy] = bool(ertek)
    if t:
        b[KULCS] = t
    else:
        b.pop(KULCS, None)
    return True

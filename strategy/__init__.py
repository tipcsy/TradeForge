"""
Stratégia réteg.

A dashboard "váza" (megjelenítés, optimalizálás, futtatás, MT5 kapcsolat,
portfólió backteszt) stratégia-független. A konkrét stratégia ezen a
csomagon keresztül csatlakozik: deklarálja a saját oszlopait, kiszámítja a
megjelenítendő értékeket, kezeli a jelzéslogikát és megadja az optimalizálandó
paramétertartományt.

Új stratégia = EGY új modul a `strategies/` csomagban, ami a `Strategy`
interfészt implementálja. A regisztráció AUTOMATIKUS (a modul felderítése) — ezt
a fájlt (a vázat) NEM kell szerkeszteni. A `get_strategy()` adja vissza az
aktívat (config-vezérelt).

⚠ KÉT CSOMAG, KÉT SZEREP (v3.29.0): ez a modul a KERET (`strategy/`), a konkrét
stratégiák a TARTALOM csomagban élnek (`strategies/`). A keret sosem importálhat
a tartalomból — kivéve ITT, a felderítésben, ami épp arra való.
"""

import importlib
import logging
import pkgutil

from strategy.base import (
    Strategy, Column, CountdownColumn, StrategyColumn, MarkerColumn,
    MarketData, Cell, Timeframe,
)

log = logging.getLogger(__name__)

# A `strategies/` csomag NEM-stratégia segédmoduljai — a felderítés kihagyja
# őket. (Nem kötelező: a felderítés amúgy is csak a Strategy-alosztályokat
# regisztrálja; ez a lista pusztán az importjukat spórolja meg.)
#
# ⚠ A KERET MODULJAI (base, settings, visual, signal_journal) v3.29.0 óta NINCSENEK
# ITT: átkerültek a `strategy/` csomagba, tehát a felderítés eleve nem látja őket.
_SKIP_MODULES = {"ml_features", "ml_train"}

_REGISTRY: "dict[str, type] | None" = None   # név → Strategy-osztály (lazán felderítve)

# Amit a szerződés-kapu KIZÁRT: `{név: indok}`. A felderítés tölti; a felület és
# a config-ellenőrzés innen tudja megmondani, MIÉRT nem látszik egy stratégia,
# ami pedig ott van a mappában. Enélkül a „nincs is ilyen" és a „van, de nem
# kompatibilis" ránézésre EGYFORMA lenne.
_INCOMPATIBLE: dict = {}


def incompatible_strategies() -> dict:
    """`{név: indok}` — a szerződés-kapun fennakadt stratégiák.

    ⚠ A felderítés LUSTA: amíg senki nem kérte a registryt, ez üres. Ezért a
    hívó előbb kérje le a neveket (`registered_strategy_names`), és csak utána
    ezt — különben egy inkompatibilis csomag néma maradna."""
    _registry()
    return dict(_INCOMPATIBLE)


def _registry() -> "dict[str, type]":
    """A `strategies/` csomag AUTOMATIKUS felderítése: végignézi a moduljait, és a
    talált `Strategy`-alosztályokat a `.name`-jük alapján regisztrálja. Egyszer fut
    (cache-elve). ÍGY egy új stratégia = EGY új modul a strategies/-ben — a
    registry-t (ezt a fájlt) nem kell módosítani. Determinisztikus (ábécé)
    sorrend; a be nem tölthető modult átugorja (figyelmeztetéssel)."""
    global _REGISTRY
    if _REGISTRY is not None:
        return _REGISTRY
    from strategy import paths as _paths
    _pkg = importlib.import_module(_paths.PACKAGE)
    reg: dict = {}
    for _mi in pkgutil.iter_modules(_pkg.__path__):
        nm = _mi.name
        if nm.startswith("_") or nm in _SKIP_MODULES:
            continue
        try:
            mod = importlib.import_module(f"{_paths.PACKAGE}.{nm}")
        except Exception as e:
            log.warning("Stratégia-modul nem tölthető be: %s.%s (%s)",
                        _paths.PACKAGE, nm, e)
            continue
        for obj in vars(mod).values():
            if (isinstance(obj, type) and issubclass(obj, Strategy)
                    and obj is not Strategy):
                sn = getattr(obj, "name", None)
                if not sn or sn in reg:
                    continue
                # ⚠ A SZERZŐDÉS-KAPU. Egy más API-verzióra írt stratégia NEM
                # kerül be — és nem némán marad ki: a napló megmondja, MELYIK
                # oldalt kell frissíteni (a programot vagy a stratégiát).
                # Enélkül egy kívülről behozott csomag betöltődne, majd valahol
                # mélyen, futás közben törne el — vagy ami rosszabb, működni
                # látszana és mást csinálna.
                from strategy import contract as _contract
                ok, indok = _contract.compatible(getattr(obj, "api", None))
                if not ok:
                    log.warning("Stratégia KIMARAD — %s: %s", sn, indok)
                    _INCOMPATIBLE[sn] = indok
                    continue
                reg[sn] = obj
    _REGISTRY = dict(sorted(reg.items()))
    return _REGISTRY


def registered_strategy_names() -> list[str]:
    """A felderített (ismert) stratégiák nevei, ábécé sorrendben. A MEGJELENÍTÉSI
    sorrendet a config `available_strategies` (whitelist) / az elsődleges stratégia
    felülírja — lásd `available_strategy_names`."""
    return list(_registry().keys())


# A stratégia-példányok gyorsítótára (stratégia-nevenként EGY példány; a példány
# állapotmentes az élő jelzésállapoton kívül, amit páronként külön tartunk).
_INSTANCES: dict[str, Strategy] = {}


def get_strategy_by_name(name: str) -> Strategy:
    """Stratégia-példány NÉV alapján (a felderített registry-ből, cache-elve).
    Új stratégia = egy új modul a strategies/-ben (Strategy-alosztály) — itt nincs mit írni."""
    if name not in _INSTANCES:
        cls = _registry().get(name)
        if cls is None:
            from core.i18n import t as _t
            raise ValueError(_t("strategy.unknown", name=repr(name)))
        _INSTANCES[name] = cls()
    return _INSTANCES[name]


def _all_registered_ordered(cfg: dict) -> list[str]:
    """Az ÖSSZES regisztrált stratégia, a config elsődlegesével ELÖL (a megszokott
    oszlopsorrend megőrzése; a többi ábécében). A primary-t NYERSEN olvassuk (nem
    `default_strategy_name`-en át), hogy ne legyen ciklus."""
    reg = registered_strategy_names()
    primary = (cfg.get("strategy", {}) or {}).get("name", "")
    if primary in reg:
        return [primary] + [n for n in reg if n != primary]
    return reg


def available_strategy_names(cfg: dict) -> list[str]:
    """A programban ELÉRHETŐVÉ tett stratégiák — a regisztráltak config-vezérelt
    szűrése (config.json: `available_strategies`). Ez határozza meg, MIT kínál a
    per-pár választó és MIBŐL képződnek a dashboard-oszlopok.

    KÉT alak támogatott — ugyanaz a jelentés, más olvashatóság:

    * **térkép** (ajánlott, ezt írja a ⚙ Beállítás):
      ``{"wpr_sma": true, "ml_ai": false}`` — a kikapcsolt stratégia is LÁTSZIK a
      configban, tehát a fájlból kiderül, mi LÉTEZIK, nem csak az, mi tér el az
      alapértelmezéstől. 4-5 stratégiánál ez az egyetlen olvasható forma.
    * **lista** (régi): ``["wpr_sma", "ml_ai"]`` — whitelist, a fel nem sorolt
      stratégia kimarad. Változatlanul működik.

    Hiány/üres/csupa-érvénytelen → az ÖSSZES regisztrált (visszafelé kompatibilis).
    A config SORRENDJÉT megtartja, csak érvényes+egyedi neveket ad vissza.

    Térképnél a NEM SZEREPLŐ (de regisztrált) stratégia **elérhető** — egy frissen
    hozzáadott stratégia-modul így nem tűnik el némán, csak mert a config még nem
    tud róla. Kikapcsolni KIFEJEZETTEN kell (`false`)."""
    reg = registered_strategy_names()
    want = cfg.get("available_strategies")
    if isinstance(want, dict):
        res = [n for n in want if n in reg and want[n]]
        # A config által nem ismert, de regisztrált stratégiák a végére — lásd a
        # docstring utolsó bekezdését (néma eltűnés helyett látható újdonság).
        res += [n for n in _all_registered_ordered(cfg)
                if n not in want and n not in res]
        return res or reg
    if not want:
        return _all_registered_ordered(cfg)
    seen, res = set(), []
    for n in want:
        if n in reg and n not in seen:
            seen.add(n)
            res.append(n)
    return res or reg


def strategy_availability(cfg: dict) -> dict:
    """`{stratégia_név: elérhető_e}` az ÖSSZES regisztrált stratégiára.

    A ⚙ Beállítás jelölőnégyzetei ebből töltődnek, és ezt írja vissza a configba —
    így a `config.json` MINDIG felsorolja a teljes készletet (a kikapcsoltakat is).
    A sorrend a megjelenítési sorrend: az elérhetők előbb (az `available_strategy_names`
    szerint), utánuk a kikapcsoltak."""
    avail = available_strategy_names(cfg)
    rest = [n for n in _all_registered_ordered(cfg) if n not in avail]
    return {**{n: True for n in avail}, **{n: False for n in rest}}


def default_strategy_name(cfg: dict) -> str:
    """A config elsődleges/alapértelmezett stratégiája (config.json strategy.name):
    az a stratégia, amit egy pár akkor használ, ha nincs saját `strategies` listája.
    Ha az érték nincs az elérhetők (available_strategies) között, az első elérhetőre
    esik vissza — így egy kikapcsolt stratégia nem marad ‚láthatatlan alapértelmezett'."""
    name = (cfg.get("strategy", {}) or {}).get("name", "wpr_sma")
    avail = available_strategy_names(cfg)
    return name if name in avail else (avail[0] if avail else name)


def get_strategy(cfg: dict) -> Strategy:
    """Az ELSŐDLEGES stratégia példánya a config alapján (visszafelé kompatibilis).

    config.json:  "strategy": { "name": "wpr_sma" }   (alapértelmezett: wpr_sma)
    """
    return get_strategy_by_name(default_strategy_name(cfg))


def enabled_strategy_names(cfg: dict, symbol: str) -> list[str]:
    """Az adott instrumentumon ENGEDÉLYEZETT stratégiák nevei (több is lehet).

    Forrás: `pairs.<symbol>.strategies` névlista. Ha hiányzik/üres → az elsődleges
    stratégia (a jelenlegi, egy-stratégiás viselkedés bitazonos marad)."""
    pc = (cfg.get("pairs", {}) or {}).get(symbol, {}) or {}
    names = pc.get("strategies")
    if not names:
        # Hiányzó/üres lista → az ELSŐDLEGES (egy-stratégiás viselkedés).
        out = [default_strategy_name(cfg)]
    else:
        # Csak érvényes/ismert nevek, a config sorrendjében (egyediesítve).
        out, seen = [], set()
        for n in names:
            if n and n not in seen:
                out.append(n)
                seen.add(n)
    # ⚠ A GLOBÁLISAN KIKAPCSOLT STRATÉGIA NEM FUTHAT. Ez a lista a MOTORÉ
    # (`strategies_for` → `live_trader`), és eddig KIZÁRÓLAG a pár `strategies`
    # listáját nézte — az `available_strategies` kapcsolót nem.
    #
    # ⚠ ÉLESBEN MEGTÖRTÉNT (2026-08-23): a felhasználó KIVETTE a bollingert az
    # aktív stratégiák közül (`available_strategies.bollinger_squeeze_breakout =
    # false`), a motor viszont TOVÁBBRA IS futtatta 9 páron, mert a párok
    # `strategies` listájában benne maradt. A felületen közben oszlopa sem volt,
    # tehát sem elindítani, sem leállítani nem lehetett — „sem live, sem off,
    # semmi", miközben kereskedhetett volna.
    #
    # A kikapcsolás így MOST már mindenhol ugyanazt jelenti: a per-pár lista a
    # SZÁNDÉK, a globális kapcsoló a LEHETŐSÉG, és a motor a kettő METSZETÉN fut.
    #
    # ⚠ A SZŰRÉS UTÁN NINCS TARTALÉK. Ha a páron kiválasztott ÖSSZES stratégia ki
    # van kapcsolva, az eredmény ÜRES — és ez a helyes válasz: „ezen a páron
    # nincs mit futtatni". Az elsődlegesre visszaesni azt jelentené, hogy olyan
    # stratégiát indítunk, amit a felhasználó erre a párra SOSEM választott ki.
    _avail = set(available_strategy_names(cfg))
    return [n for n in out if n in _avail]


def strategies_for(cfg: dict, symbol: str) -> list[Strategy]:
    """Az instrumentumon engedélyezett stratégia-példányok (az elsődleges az első)."""
    return [get_strategy_by_name(n) for n in enabled_strategy_names(cfg, symbol)]


__all__ = [
    "Strategy", "Column", "CountdownColumn", "StrategyColumn", "MarkerColumn",
    "MarketData", "Cell", "Timeframe",
    "get_strategy", "get_strategy_by_name", "default_strategy_name",
    "enabled_strategy_names", "strategies_for", "registered_strategy_names",
    "available_strategy_names", "strategy_availability",
    "incompatible_strategies",
]

"""
Optimalizálási TEVÉKENYSÉG per (instrumentum × stratégia).

Miért külön modul: az `instrument_state` eddig **két különböző dolgot** préselt egy
változóba —

    kereskedési SZÁNDÉK        : LIVE | STOPPED | CLOSING
    optimalizálási TEVÉKENYSÉG : OPTIMIZING | QUEUED

—, ráadásul csak SZIMBÓLUM-kulccsal. Ebből két hiba következett:

  1. Az `OPTIMIZING` **felülírta** a kereskedési szándékot, ezért az optimalizálás
     végén a szimbólum kényszerűen `STOPPED`-re esett (akkor is, ha előtte
     kereskedett).
  2. Egy szimbólumon EGY stratégia optimalizálása a TÖBBIT is megbénította:
     a `request_optimize` egy LIVE szimbólumot egyáltalán nem engedett
     optimalizálni, tehát előbb Stopot kellett nyomni — ami az összes stratégiát
     leállította rajta. Pedig a `wpr_sma` hangolása alatt az `ml_ai` zavartalanul
     kereskedhetne: külön magic, külön paraméterfájl, külön pozíciók.

Ez a modul a MÁSODIK tengelyt viszi el, per (symbol, strategy) kulccsal — így az
`instrument_state` visszakapja az EGYETLEN jelentését (kereskedési szándék).

**Miért mégis szünetel a SAJÁT stratégia kereskedése optimalizálás alatt:** a futás
végén felülíródik a `data/optimized_params/<strategy>/<SYMBOL>.json`. Ha közben
nyílna belépő, az a RÉGI paraméterekkel menne, a menedzsment viszont már az újakkal
— ezért az adott (symbol, strategy) párost szándékosan kihagyjuk a körből. A pár
TÖBBI stratégiáját nem.

Futásidejű állapot, NEM perzisztálódik: újraindítás után a befejezetlen study-kat a
`params_store.unfinished_studies()` találja meg a fájlrendszerből.
"""

from __future__ import annotations

import threading

RUNNING = "OPTIMIZING"
QUEUED = "QUEUED"

_lock = threading.RLock()
# (symbol, strategy) -> {"state": RUNNING|QUEUED, "status": "szöveg"}
_act: dict = {}


def set_state(symbol: str, strategy: str, state: "str | None",
              status: "str | None" = None) -> None:
    """Tevékenység beállítása. `state=None` → a bejegyzés TÖRLÉSE (kész/megszakadt).

    A `status` a haladás-szöveg (pl. „40/500  8%"); `None` → a meglévő marad."""
    key = (symbol, strategy)
    with _lock:
        if state is None:
            _act.pop(key, None)
            return
        cur = _act.get(key) or {}
        _act[key] = {"state": state,
                     "status": cur.get("status", "") if status is None else status}


def set_status(symbol: str, strategy: str, status: str) -> None:
    """Csak a haladás-szöveg frissítése (a tevékenység-állapot érintetlen).

    Ha nincs bejegyzés, nem hozunk létre: a szöveg egy már befejezett futásra
    vonatkozna, és „élőnek" látszana a felületen."""
    with _lock:
        cur = _act.get((symbol, strategy))
        if cur is not None:
            cur["status"] = status


def state_of(symbol: str, strategy: str) -> "str | None":
    with _lock:
        cur = _act.get((symbol, strategy))
        return cur["state"] if cur else None


def status_of(symbol: str, strategy: str) -> str:
    with _lock:
        cur = _act.get((symbol, strategy))
        return cur.get("status", "") if cur else ""


def busy(symbol: str, strategy: str) -> bool:
    """Fut VAGY sorban áll-e ez a (symbol, strategy)? A `live_trader` ez alapján
    hagyja ki a stratégiát a körből — a sorban állót is, mert bármikor indulhat."""
    return state_of(symbol, strategy) is not None


def symbol_state(symbol: str) -> "str | None":
    """A szimbólum ÖSSZEVONT tevékenysége a kijelzéshez: `RUNNING`, ha bármelyik
    stratégiája fut; `QUEUED`, ha csak sorban áll; különben None.

    A régi, szimbólum-szintű megjelenítés így változatlan marad — a kijelzés
    összevon, a DÖNTÉS viszont per stratégia történik."""
    with _lock:
        states = [v["state"] for (s, _), v in _act.items() if s == symbol]
    if RUNNING in states:
        return RUNNING
    if QUEUED in states:
        return QUEUED
    return None


def symbol_status(symbol: str) -> str:
    """A szimbólum összevont haladás-szövege: a FUTÓ stratégiáé (az a lényeges),
    különben az első sorban állóé. Nincs tevékenység → üres."""
    with _lock:
        items = [(k[1], v) for k, v in _act.items() if k[0] == symbol]
    for name, v in items:
        if v["state"] == RUNNING:
            return v.get("status", "") or name
    for name, v in items:
        return v.get("status", "") or name
    return ""


def symbol_busy(symbol: str) -> bool:
    """Van-e BÁRMELY futó/sorban álló tétele a szimbólumnak? (Erőforrás-döntés: egy
    szimbólumon egyszerre egy optimalizálást engedünk — ez NEM kereskedési korlát.)"""
    return symbol_state(symbol) is not None


def strategies_of(symbol: str) -> list:
    """A szimbólum foglalt stratégiái, `(név, állapot)` párként — naplózáshoz és a
    per-stratégia kijelzéshez."""
    with _lock:
        return sorted((k[1], v["state"]) for k, v in _act.items() if k[0] == symbol)


def clear_symbol(symbol: str) -> None:
    """A szimbólum összes bejegyzésének törlése (pár törlésekor / sor ürítésekor)."""
    with _lock:
        for key in [k for k in _act if k[0] == symbol]:
            _act.pop(key, None)

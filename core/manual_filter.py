"""
MANUÁLIS ELŐSZŰRŐ — a reggeli kézi piac-áttekintés eredménye, instrumentumonként.

Tibi (2026-10-12, „Program működése" rajz): minden reggel van egy teljesen kézi
piaci áttekintés. Az eredménye instrumentumonként egy lenyílóból választható:

    Nincs            — nincs beállítva semmi, nyugodtan kereskedhet
    Ne kereskedj!    — minden beszállás gátolva
    Óvatosan         — beszáll, de fele kockázattal
    Szép chart ↑     — bika piac: CSAK felfelé (a lefelé belépő gátolva)
    Szép chart ↓     — medve piac: CSAK lefelé (a felfelé belépő gátolva)
    Szép chart ↕     — szép chart, mindkét irány mehet

⚠ ÚJ NAP → MINDEN „Nincs". A beállítás a NAP döntése, nem tartós tulajdonság: a
fájl a dátumot is tárolja, és egy régebbi dátumú bejegyzés NEM ÉRVÉNYES (olvasáskor
üresnek számít). Így nincs szükség éjféli feladatra, és egy tegnapi „Ne
kereskedj!" sem ragadhat be, ha a program nem futott át éjfélen.

⚠ A NAP a gép HELYI dátuma (Tibi magyar ideje) — a reggeli áttekintés is ehhez
igazodik, nem a bróker szerveridejéhez.

⚠ NEM BRÓKERFÜGGŐ. A piac-kép az INSTRUMENTUMRÓL szól (kanonikus név), nem a
számláról: ugyanaz a GOLD-ítélet érvényes minden brókerre. Ezért a `data/`
gyökerében él (`data/manual_filter.json`), nem a számla-mappában.

A beállítás a config-ban kapcsolható (`manual_filter.enabled`); kikapcsolva se
oszlop, se hatás. A motorban KAPU (`gates/manual.py`): a döntést a keret hozza
meg (gátol / felez), ugyanúgy, mint bármely más kapunál — csak a táblán a Kapuk
blokk ELŐTT áll, mert a kapuk előtti, kézi lépés.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import threading
from pathlib import Path

from core.i18n import LabelMap as _LabelMap

NONE = "none"
NO_TRADE = "no_trade"
CAUTIOUS = "cautious"
BULL = "bull"
BEAR = "bear"
NICE = "nice"
STATES = (NONE, NO_TRADE, CAUTIOUS, BULL, BEAR, NICE)

# Hosszú felirat (a lenyíló) és rövid (a tábla cellája).
LABEL = _LabelMap("manual.state", STATES)
SHORT = _LabelMap("manual.short", STATES)
# A cella színe (szemantikus név → a felület fordítja színre).
COLOR = {NONE: "muted", NO_TRADE: "red", CAUTIOUS: "yellow",
         BULL: "green", BEAR: "green", NICE: "green"}

try:                                             # EXE-ben az adat az .exe mellett van
    from version import BASE_DIR as _BASE
    _BASE = Path(_BASE)
except Exception:                                # pragma: no cover
    _BASE = Path(__file__).resolve().parents[1]
PATH = _BASE / "data" / "manual_filter.json"

_lock = threading.Lock()
_cache: dict = {"path": None, "mtime": None, "data": None}


def enabled(cfg: dict | None) -> bool:
    """Be van-e kapcsolva a manuális előszűrő (`manual_filter.enabled`, alap: ki)."""
    mf = (cfg or {}).get("manual_filter")
    return bool(isinstance(mf, dict) and mf.get("enabled", False))


def today() -> str:
    return _dt.date.today().isoformat()


def _read() -> dict:
    p = Path(PATH)
    try:
        mt = p.stat().st_mtime
    except OSError:
        return {}
    if _cache["path"] == str(p) and _cache["mtime"] == mt:
        return _cache["data"] or {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except Exception:
        data = {}
    _cache.update(path=str(p), mtime=mt, data=data)
    return data


def states(day: str | None = None) -> dict:
    """`{szimbólum: állapot}` a MAI napra. Régebbi dátumú fájl → üres (új nap)."""
    data = _read()
    if data.get("date") != (day or today()):
        return {}
    return {str(k): v for k, v in (data.get("states") or {}).items() if v in STATES}


def state_of(symbol: str, day: str | None = None) -> str:
    """Az instrumentum mai állapota (nincs bejegyzés / tegnapi → `none`)."""
    return states(day).get(symbol, NONE)


def set_state(symbol: str, state: str, day: str | None = None) -> None:
    """Egy instrumentum mai állapotának beírása (atomikusan). A `none` törli a
    bejegyzést; egy régebbi napi fájl a beíráskor kiürül (új nap)."""
    if state not in STATES:
        raise ValueError(f"ismeretlen manuális állapot: {state!r}")
    nap = day or today()
    with _lock:
        cur = states(nap)
        if state == NONE:
            cur.pop(symbol, None)
        else:
            cur[symbol] = state
        p = Path(PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"date": nap, "states": cur}, ensure_ascii=False,
                                  indent=1), encoding="utf-8")
        os.replace(tmp, p)
        _cache.update(path=None, mtime=None, data=None)


# ── a kapu döntése (tiszta) ─────────────────────────────────────────────────
# A kapu SZINTJE a jelzés irányával feloldott ítélet — ezt a sávos hatás-létra
# fordítja hatásra (`gates/manual.py` alap-létrája):
LEVEL_OK = "ok"
LEVEL_NO_TRADE = "no_trade"      # → gátol
LEVEL_CAUTIOUS = "cautious"      # → fele kockázat
LEVEL_AGAINST = "against"        # → gátol (a választott iránnyal szemben)
LEVELS = (LEVEL_OK, LEVEL_NO_TRADE, LEVEL_CAUTIOUS, LEVEL_AGAINST)


def level_of(state: str, signal: str) -> str:
    """Az állapot + a jelzés iránya → a kapu szintje."""
    if state == NO_TRADE:
        return LEVEL_NO_TRADE
    if state == CAUTIOUS:
        return LEVEL_CAUTIOUS
    if state == BULL and signal == "SELL":
        return LEVEL_AGAINST
    if state == BEAR and signal == "BUY":
        return LEVEL_AGAINST
    return LEVEL_OK

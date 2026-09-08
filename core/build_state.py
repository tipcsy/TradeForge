"""Per-instrumentum POZÍCIÓÉPÍTÉS-állapot — perzisztens JSON (`data/build_mode.json`).

Instrumentumonként: `mode` (off|manual|auto) + `size_factor` (piramidális méret).
Az `off` az alap → visszafelé kompatibilis (aki nem állítja, annak nincs építés).
A GUI a módot körbe-váltja (Ki → Kézi → Auto), és a live/GUI ez alapján dönt.
"""

import json
import logging
import threading
from pathlib import Path

from core.i18n import LabelMap as _LabelMap

from core.position_build import (
    default_config, MODES, MODE_OFF, MODE_MANUAL, MODE_AUTO, TRIGGERS, TRIGGER_CANDLE,
)

log = logging.getLogger(__name__)

PATH = Path(__file__).resolve().parents[1] / "data" / "build_mode.json"

CYCLE = (MODE_OFF, MODE_MANUAL, MODE_AUTO)
# ⚠ LabelMap (lásd `core.i18n.LabelMap`): a legördülő és a visszafejtése
# ugyanabból a hívásból dolgozik.
MODES = (MODE_OFF, MODE_MANUAL, MODE_AUTO)
NAME = _LabelMap("build.mode", MODES)

_lock = threading.Lock()
_state: dict[str, dict] = {}

_KEYS = ("mode", "size_factor", "trigger", "r_step", "r_shrink",
         "target_r", "target_trail_pct")


def _norm(v) -> dict:
    d: dict = {}
    if isinstance(v, dict):
        m = v.get("mode", MODE_OFF)
        d["mode"] = m if m in MODES else MODE_OFF
        if isinstance(v.get("size_factor"), (int, float)):
            d["size_factor"] = float(v["size_factor"])
        if v.get("trigger") in TRIGGERS:
            d["trigger"] = v["trigger"]
        for k in ("r_step", "r_shrink"):
            if isinstance(v.get(k), (int, float)):
                d[k] = float(v[k])
        # ⚠ A csomag célára R-ben. A NEGATÍVAT nullára vágjuk (nincs cél), nem
        # tartjuk meg: egy negatív cél az ár ROSSZ oldalára tenné a TP-t, amit a
        # bróker vagy elutasít, vagy azonnal teljesít — mindkettő rosszabb, mint
        # a cél nélküli futás.
        if isinstance(v.get("target_r"), (int, float)):
            d["target_r"] = max(0.0, float(v["target_r"]))
        # A kúszó stop HÁNYAD (0…1). Az 1 fölötti érték a stopot a CÉLÁR FÖLÉ
        # tenné, a negatív a rossz oldalra — mindkettőt a tartományra vágjuk,
        # nem dobjuk el: a mező visszaírja a ténylegesen hatót.
        if isinstance(v.get("target_trail_pct"), (int, float)):
            d["target_trail_pct"] = min(1.0, max(0.0, float(v["target_trail_pct"])))
    else:
        d["mode"] = MODE_OFF
    return d


def load() -> dict:
    with _lock:
        try:
            if PATH.exists():
                with open(PATH, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    _state.clear()
                    _state.update({str(k): _norm(v) for k, v in data.items()})
        except Exception as ex:
            # ⚠ Némán üresen indulni itt azt jelenti, hogy MINDEN pár `off`-ra
            # esik — a ráépítés (és a csomag-célár) csendben nem működik. Ez
            # kívülről ugyanúgy néz ki, mint egy pár, amin épp nincs jel.
            log.error("%s: az építés-állapot NEM OLVASHATÓ (%s) — minden pár "
                      "'Ki' módra esik vissza, a pozícióépítés nem indul.",
                      PATH.name, ex)
        return dict(_state)


def _entry(symbol: str) -> dict:
    return _state.get(symbol, {"mode": MODE_OFF})


def get_config(symbol: str) -> dict:
    """A teljes építés-config (default + per-pár override)."""
    with _lock:
        return {**default_config(), **{k: v for k, v in _entry(symbol).items() if k in _KEYS}}


def get_mode(symbol: str) -> str:
    with _lock:
        return _entry(symbol).get("mode", MODE_OFF)


def _save_locked():
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_state, f, indent=2, ensure_ascii=False)
        tmp.replace(PATH)
    except Exception as ex:
        log.error("%s: az építés-állapot MENTÉSE nem sikerült (%s). A beállítás "
                  "csak a memóriában él — újraindítás után elveszik.",
                  PATH.name, ex)


def _set(symbol: str, **kw):
    with _lock:
        d = dict(_entry(symbol))
        d.update(kw)
        _state[symbol] = _norm(d)
        _save_locked()


def set_mode(symbol: str, mode: str):
    _set(symbol, mode=mode if mode in MODES else MODE_OFF)


def set_config(symbol: str, **params):
    upd = {k: params[k] for k in _KEYS if k in params}
    if upd:
        _set(symbol, **upd)


def cycle_mode(symbol: str) -> str:
    """Ki → Kézi → Auto → Ki (a GUI gombja ezt hívja)."""
    with _lock:
        cur = _entry(symbol).get("mode", MODE_OFF)
        nxt = CYCLE[(CYCLE.index(cur) + 1) % len(CYCLE)] if cur in CYCLE else MODE_MANUAL
        d = dict(_entry(symbol)); d["mode"] = nxt
        _state[symbol] = _norm(d)
        _save_locked()
        return nxt

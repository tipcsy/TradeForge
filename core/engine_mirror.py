"""KIJELZÉS-TÜKÖR — a motor páronkénti állapota egy MÁSIK processz felületén.

⚠ 0029, 4b/3 — S2 (2026-09-28). A fő tábla ma a motor memóriájából olvas: a
`live_trader.dashboard` (páronként egy `PairDashboardState`), az
`instrument_state` és az `optimizer_status` KÖZÖS dictek. Ha a motor külön
processzben fut, ezek nem közösek többé. A motor ezért az állapotképébe
(`core/engine_status`) teszi őket, a felület pedig ebből TÖLTI a saját
dictjeit — a fő tábla kódja így változatlan maradhat: ugyanazt a dictet olvassa.

⚠ A JSON ELVESZI A TÍPUSOKAT, és a tükörnek VISSZA kell adnia őket — különben a
felület egy része csendben rosszul rajzolna:
  • `daily_by_strategy` — a `None` kulcs (a gazdátlan pozícióké) szöveg lesz;
  • `timeframe_remaining` — az egész (perc) kulcsok szöveggé válnak;
  • `opt_grade` és a stratégia-cellák `(szöveg, szín)` tuple-jei listák lesznek.
Az oda-vissza teszt (`tests/test_engine_mirror.py`) MINDEN mezőt összevet.

⚠ HELYBEN FRISSÍT: a meglévő `PairDashboardState` objektumok mezőit írja át
(a felület hivatkozást tarthat rájuk), az új párokhoz újat hoz létre, a
kikerülteket törli. Ismeretlen mező (újabb motor-verzió) → kimarad, nem száll el.
"""
from __future__ import annotations

import dataclasses


def _state_cls():
    from trading.live_trader import PairDashboardState
    return PairDashboardState


# ── MOTOR OLDAL ─────────────────────────────────────────────────────────────

def _ser(v):
    if isinstance(v, dict):
        return {("None" if k is None else str(k)): _ser(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_ser(x) for x in v]
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    try:
        return float(v)
    except Exception:
        return str(v)


def dump_dashboard(dashboard: dict) -> dict:
    """`{szimbólum: PairDashboardState}` → JSON-barát dict."""
    out = {}
    for sym, st in list(dashboard.items()):
        try:
            out[str(sym)] = _ser(dataclasses.asdict(st))
        except Exception:
            continue
    return out


# ── FELÜLET OLDAL ───────────────────────────────────────────────────────────

def _int_kulcs(d):
    out = {}
    for k, v in (d or {}).items():
        try:
            out[int(k)] = v
        except (TypeError, ValueError):
            out[k] = v
    return out


def _vissza(nev: str, v):
    """A JSON-ban elveszett típusok visszaállítása mezőnként."""
    if nev == "daily_by_strategy" and isinstance(v, dict):
        return {(None if k == "None" else k): x for k, x in v.items()}
    if nev == "timeframe_remaining" and isinstance(v, dict):
        return _int_kulcs(v)
    if nev == "opt_grade" and isinstance(v, list):
        return tuple(v)
    if nev == "strategy_cells" and isinstance(v, dict):
        return {s: {st: (tuple(c) if isinstance(c, list) else c)
                    for st, c in (cells or {}).items()}
                for s, cells in v.items()}
    return v


def load_state(sym: str, d: dict, cls=None):
    cls = cls or _state_cls()
    mezok = {f.name for f in dataclasses.fields(cls)}
    kw = {k: _vissza(k, v) for k, v in (d or {}).items() if k in mezok}
    kw["symbol"] = sym
    return cls(**kw)


# ⚠ A MOTOR MEZŐI (demó-próba lelete, 2026-09-29). Közös processzben a motor és
# a felület UGYANAZT az objektumot írta, ki-ki a SAJÁT mezőit: az árakat, a
# spreadet, a napi változást, a tőzsdei állapotot, a TF-együttállást és a
# leállított párok előnézetét a FELÜLET számolta. Az első tükör MINDEN mezőt
# felülírt a motor értékeivel — a felület számolt mezői másodpercenként
# visszanullázódtak (és mivel a motor sosem töltötte az árat, üres lett).
# A tükör ezért CSAK a motor mezőit írja; a stratégia-cellákat a felület mai
# szabályával: a motoré nyer, ha FRISS a `cells_ts`.
ENGINE_FIELDS = ("position_pnl", "pos_count", "risk_free", "risky", "rr_preset",
                 "daily_pnl", "daily_by_strategy", "market_state",
                 "market_state_color", "market_strategy", "atr_price", "cells_ts")
CELLS_FRESH_SEC = 30.0


def apply(snap: dict | None, dashboard: dict, instrument_state: dict | None = None,
          optimizer_status: dict | None = None, cls=None, now: float | None = None) -> bool:
    """Az állapotkép tükrözése a felület dictjeibe (helyben). False, ha a kép
    nem tartalmaz tükröt (régebbi motor)."""
    import time as _time
    if not snap or not isinstance(snap.get("dashboard"), dict):
        return False
    cls = cls or _state_cls()
    now = _time.time() if now is None else now
    uj = snap["dashboard"]
    for sym in list(dashboard):
        if sym not in uj:
            del dashboard[sym]
    for sym, d in uj.items():
        friss = load_state(sym, d, cls)
        regi = dashboard.get(sym)
        if not isinstance(regi, cls):
            dashboard[sym] = friss                  # új pár: a motor teljes képe
            continue
        for f in ENGINE_FIELDS:
            if hasattr(friss, f):
                setattr(regi, f, getattr(friss, f))
        if friss.cells_ts and now - float(friss.cells_ts) < CELLS_FRESH_SEC:
            for s, cells in (friss.strategy_cells or {}).items():
                regi.strategy_cells[s] = cells      # élő pár: a motor jelzés-állapota
    for cel, kulcs in ((instrument_state, "instrument_state"),
                       (optimizer_status, "optimizer_status")):
        if cel is not None and isinstance(snap.get(kulcs), dict):
            cel.clear()
            cel.update(snap[kulcs])
    return True

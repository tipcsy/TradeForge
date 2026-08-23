"""Pozíciók BELÉPÉSKORI adatai — perzisztens JSON (`data/position_meta.json`).

MIÉRT KELL: az **R-egység** alapja a belépéskor kockáztatott összeg („erre az
irányra feltettem 15 $-t" → 15 $ = 1 R; +2 R = +30 $). Ez a szám a nyitás
pillanatában dől el, és **utólag NEM rekonstruálható**:

  1. a breakeven és a trailing **felülírja** az MT5-beli SL-t → a belépéskori
     stop-távolság eltűnik a bróker oldaláról;
  2. a motor futásidejű `pstate`-je **memóriabeli** → újraindításkor elvész;
  3. a **lezárt** kötések R-je (napi P&L R-ben) a lezárás UTÁN is kell.

Ezért a nyitás pillanatában ide írjuk, és a lezárás után is megtartjuk — pontosan
úgy, ahogy a `core/adopted.py` teszi a ticket→stratégia hozzárendeléssel. A két
modul azonos mintát követ, és a takarításuk is közös beállításból megy.

A TÉNYLEGES kockázatot tároljuk, nem a szándékoltat. A `risk_manager.calc_lot`
ugyanis lefelé kerekít a `lot_step`-re, de a `min_lot` FÖLFELÉ is kényszerítheti a
lotot (és a `max_lot` levághatja) — ilyenkor a valóban feltett tét eltér a
`balance × account_risk_pct / slots` szándéktól. Az R-nek a valósághoz kell
igazodnia, különben a mutatott R hazudna.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "data" / "position_meta.json"

log = logging.getLogger(__name__)

_lock = threading.Lock()
_state: dict[str, dict] = {}
_loaded = False


# ---------------------------------------------------------------------------
# Kockázat-számítás — TISZTA függvények (nincs MT5/fájl függés, jól tesztelhető)
# ---------------------------------------------------------------------------

def risk_from_points(lot: float, sl_points: float, pv1_point: float) -> float:
    """A feltett tét a SZÁMLA devizájában: `lot × sl_points × pv1_point`.

    Ez a `calc_lot` megfordítása (ott: `raw_lot = risk_per_slot / (sl_points ×
    point_value)`). 0.0, ha bármelyik bemenet érvénytelen — a hívó ilyenkor NE
    írjon be nullát, hanem hagyja ki a bejegyzést (a 0 R-osztás hamis végtelen)."""
    try:
        lot, sl_points, pv1_point = float(lot), float(sl_points), float(pv1_point)
    except (TypeError, ValueError):
        return 0.0
    if lot <= 0 or sl_points <= 0 or pv1_point <= 0:
        return 0.0
    return lot * sl_points * pv1_point


def risk_from_prices(lot: float, entry_price: float, sl_price: float,
                     point_size: float, pv1_point: float) -> float:
    """Ugyanaz ÁRAKBÓL — a kézzel nyitott (örökbefogadott) pozícióhoz, ahol nincs
    motor-számolta `sl_points`, csak a bróker nyitóára és stopja.

    0.0, ha nincs érvényes stop (`sl_price` hiányzik vagy egyenlő a nyitóárral) —
    stop nélküli pozíciónak NINCS értelmezhető kockázata, tehát nincs R sem."""
    try:
        entry_price, sl_price = float(entry_price), float(sl_price)
        point_size = float(point_size)
    except (TypeError, ValueError):
        return 0.0
    if point_size <= 0 or not sl_price or entry_price <= 0:
        return 0.0
    return risk_from_points(lot, abs(entry_price - sl_price) / point_size, pv1_point)


# ---------------------------------------------------------------------------
# Perzisztens tároló (a core/adopted.py mintájára)
# ---------------------------------------------------------------------------

def _norm(v) -> dict | None:
    if not isinstance(v, dict):
        return None
    try:
        risk = float(v.get("risk_ccy") or 0.0)
    except (TypeError, ValueError):
        return None
    if risk <= 0:
        return None
    d = {
        "symbol":   str(v.get("symbol") or ""),
        "strategy": str(v.get("strategy") or ""),
        "risk_ccy": risk,
        "opened_at": str(v.get("opened_at") or ""),
    }
    for k in ("lot", "sl_points", "entry_price"):
        if v.get(k) is not None:
            try:
                d[k] = float(v[k])
            except (TypeError, ValueError):
                # ⚠ JOGOSAN NÉMA: egyetlen elrontott számmező (kézi szerkesztés,
                # régi formátum) nem teheti olvashatatlanná az EGÉSZ bejegyzést.
                # A mező kimarad, a többi adat megmarad — a hívók amúgy is
                # `None`-ra készülnek. Szűk kivétel, nem catch-all.
                pass
    if v.get("closed_at"):
        d["closed_at"] = str(v["closed_at"])
    return d


def load() -> dict:
    """Beolvasás lemezről (idempotens). Egy folyamaton belül a memóriabeli állapot
    az igazság — azonos minta, mint a többi állapot-modulnál."""
    global _loaded
    with _lock:
        try:
            if PATH.exists():
                with open(PATH, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    _state.clear()
                    for k, v in data.items():
                        n = _norm(v)
                        if n is not None:
                            _state[str(k)] = n
        except Exception as ex:
            # ⚠ SÉRÜLT/OLVASHATATLAN FÁJL. Üresen indulni ANNYI, mintha soha nem
            # lett volna belépéskori kockázat (1 R) — a motor a pozíciókat
            # gazdátlannak látná. A program fut tovább (ez a helyes: egy régi
            # nyilvántartás nem érhet többet a kereskedésnél), de a napló
            # MEGKAPJA az okot, mert kívülről ez semmiben nem különbözik az
            # „még nincs bejegyzés" állapottól.
            log.warning("%s: a nyilvántartás nem olvasható (%s) — ÜRESEN indul. "
                        "A korábbi bejegyzések nem érvényesülnek.",
                        PATH.name, ex)
        _loaded = True
        return dict(_state)


def _ensure_loaded():
    if not _loaded:
        load()


def _save_locked():
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_state, f, indent=2, ensure_ascii=False)
        tmp.replace(PATH)
    except Exception as ex:
        # ⚠ EZ A LEGROSSZABB NÉMA HIBA a modulban: a bejegyzés a MEMÓRIÁBAN
        # megvan, tehát minden működni látszik — a lemezen viszont nincs, és ez
        # csak a KÖVETKEZŐ INDÍTÁSKOR derülne ki, amikor a pozíció már gazdátlan.
        log.error("%s: a nyilvántartás MENTÉSE nem sikerült (%s). A bejegyzés "
                  "csak a memóriában él — újraindítás után elveszik.",
                  PATH.name, ex)


def record(ticket: int, symbol: str, strategy: str, risk_ccy: float,
           lot: float = 0.0, sl_points: float = 0.0,
           entry_price: float = 0.0) -> bool:
    """A pozíció belépéskori adatainak rögzítése. `risk_ccy` = a feltett tét a
    számla devizájában (1 R). Visszaad: rögzítettük-e.

    `risk_ccy <= 0` → NEM írunk bejegyzést (stop nélküli / ismeretlen kockázat).
    Így a hiány `None`-ként jelenik meg a kijelzésen („—"), nem 0-ként — a nullával
    való osztás hamis végtelen R-t adna.

    Meglévő ticketet NEM ír felül: a belépéskori adat definíció szerint egyszer
    keletkezik (a ráépítés új ticketet kap, saját bejegyzéssel)."""
    _ensure_loaded()
    try:
        risk_ccy = float(risk_ccy)
    except (TypeError, ValueError):
        return False
    if risk_ccy <= 0:
        return False
    key = str(int(ticket))
    with _lock:
        if key in _state:
            return False
        e = {"symbol": str(symbol), "strategy": str(strategy),
             "risk_ccy": risk_ccy,
             "opened_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if lot:
            e["lot"] = float(lot)
        if sl_points:
            e["sl_points"] = float(sl_points)
        if entry_price:
            e["entry_price"] = float(entry_price)
        _state[key] = e
        _save_locked()
    return True


def mark_closed(ticket: int):
    """A pozíció lezárult — a bejegyzés MEGMARAD (a lezárt kötések R-je is kell),
    csak időbélyeget kap. A `prune` takarítja el később."""
    _ensure_loaded()
    with _lock:
        e = _state.get(str(int(ticket)))
        if e is not None and not e.get("closed_at"):
            e["closed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            _save_locked()


def risk_of(ticket) -> "float | None":
    """A ticket belépéskori kockázata (1 R) a számla devizájában, vagy None."""
    _ensure_loaded()
    if ticket is None:
        return None
    with _lock:
        e = _state.get(str(int(ticket)))
        return e["risk_ccy"] if e else None


def meta_of(ticket) -> "dict | None":
    """A ticket teljes belépéskori bejegyzése (másolat), vagy None."""
    _ensure_loaded()
    if ticket is None:
        return None
    with _lock:
        e = _state.get(str(int(ticket)))
        return dict(e) if e else None


def risk_of_closed(closed_row: dict, pair_cfg: dict) -> "float | None":
    """Egy LEZÁRT kötés belépéskori kockázata (1 R) — két forrásból, sorrendben:

      1. a **rögzített** érték (`risk_of`) — ez a pontos: a nyitáskori `pv1_point`-tal
         számolt tényleges tét;
      2. tartalék: a **nyitó order SL-jéből** visszaszámolva. A `closed_positions_range`
         az `sl` mezőbe a NYITÓ order stopját teszi (az SL-módosítás külön order,
         tehát ez az EREDETI kockázati táv). Ez a régi, még nem rögzített kötésekhez
         kell — enélkül az R-oszlop minden múltbeli kötésnél kiürülne.

    None, ha nincs érvényes stop (stop nélküli pozíciónak nincs értelmezhető
    kockázata) — a hívó ilyenkor „—"-t mutasson, ne 0-t.

    A tartalék-ág a MAI `pv1_point`-tal számol, ami a nem számla-devizás
    instrumentumoknál sodródhat a nyitáskorihoz képest — ezért csak tartalék."""
    if not isinstance(closed_row, dict):
        return None
    rec = risk_of(closed_row.get("position"))
    if rec:
        return rec
    pc = pair_cfg or {}
    v = risk_from_prices(closed_row.get("volume", 0.0),
                         closed_row.get("price_open", 0.0),
                         closed_row.get("sl", 0.0),
                         pc.get("point_size", 0.0), pc.get("pv1_point", 0.0))
    return v or None


def r_multiple(ticket, pnl_ccy) -> "float | None":
    """Egy pozíció eredménye R-ben: `pnl / belépéskori kockázat`.
    None, ha nincs rögzített kockázat — a hívó ilyenkor „—"-t mutasson."""
    risk = risk_of(ticket)
    if not risk:
        return None
    try:
        return float(pnl_ccy) / risk
    except (TypeError, ValueError):
        return None


def prune(open_tickets=None, keep_days: int = 3):
    """Takarítás induláskor: a régen lezárt bejegyzések törlése.

    `keep_days <= 0` → **soha nem törlünk** (a bejegyzések elférnek: ~170 byte
    darabja, és csak nyitáskor keletkeznek). Ha `open_tickets` meg van adva, a MÁR
    NEM NYITOTT (de lezártként sem jelölt — pl. a program állása közben zárt)
    ticketek is lezártnak számítanak."""
    _ensure_loaded()
    with _lock:
        changed = False
        for k in list(_state):
            e = _state[k]
            if open_tickets is not None and int(k) not in open_tickets \
                    and not e.get("closed_at"):
                e["closed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                changed = True
        if keep_days and keep_days > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
            for k in list(_state):
                ca = _state[k].get("closed_at")
                if ca:
                    try:
                        if datetime.fromisoformat(ca) < cutoff:
                            del _state[k]
                            changed = True
                    except Exception as ex:
                        # Hibás időbélyeg → a bejegyzést MEGTARTJUK (a törlés
                        # visszafordíthatatlan), de nem hallgatunk róla.
                        log.debug("%s: hibás closed_at (%s): %s", PATH.name, k, ex)
        if changed:
            _save_locked()

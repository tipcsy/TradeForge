"""KÖZÖS KITETTSÉGI KORLÁT minden számlán át (0029, 6b).

Tibi döntése (2026-09-30): egy instrumentumon az ÖSSZES számlán egyszerre
legfeljebb N nyitott pozíció (`trading.shared_max_per_instrument`, alap 1;
0 = kikapcsolva). Ha az egyik brókeren már van GOLD, a másik nem nyit.

KÉT SZÁNDÉKOS SZŰKÍTÉS:
  1. Csak akkor TILT, ha egy MÁSIK számlán is van pozíció az instrumentumon.
     Egy számlán belül a mai házirend (`same_symbol_policy`) dönt — enélkül
     N=1 mellett egy számla két stratégiája sem nyithatna ugyanarra a párra,
     ami egy brókernél is megváltoztatná a viselkedést.
  2. Egy brókernél a korlát nem létezik (nincs kivel osztozni).

⚠ A NEM FUTÓ MOTOR IS SZÁMÍT. A másik számla pozícióit a motorja
állapotképéből látjuk. Ha az a motor áll, a pozíciói a számlán ettől még
NYITVA vannak — ezért az UTOLSÓ ismert képet vesszük (kortól függetlenül),
nem „nincs adat = nincs pozíció"-t. Ami soha nem írt képet, arról tényleg
nem tudunk: arról a hívó naplóz.
"""
from __future__ import annotations

KULCS = "shared_max_per_instrument"
ALAP = 1


def limit_of(trading_cfg: dict | None) -> int:
    """A korlát a `trading` beállításból; hibás érték → az alap (nem 0: a
    kikapcsolás legyen szándékos)."""
    try:
        n = int((trading_cfg or {}).get(KULCS, ALAP))
    except (TypeError, ValueError):
        return ALAP
    return max(0, n)


def _counts_of_snapshot(snap: dict) -> dict:
    """{szimbólum: nyitott pozíciók száma} egy motor képéből. A részletes lista
    (5c óta) az elsődleges; régebbi képnél az aggregált `positions_by_symbol`."""
    out: dict = {}
    det = snap.get("positions_detail")
    if isinstance(det, list):
        for p in det:
            if isinstance(p, dict) and p.get("symbol"):
                out[p["symbol"]] = out.get(p["symbol"], 0) + 1
        return out
    for sym, agg in (snap.get("positions_by_symbol") or {}).items():
        try:
            out[sym] = int((agg or {}).get("count") or 0)
        except (TypeError, ValueError, AttributeError):
            continue
    return out


def other_counts(profiles, active_id: str, read) -> tuple[dict, list]:
    """A TÖBBI számla nyitott pozíciói szimbólumonként, és azok a brókerek,
    amelyekről NINCS kép (a hívó naplózza őket).

    `read(profile) -> dict | None` — a motor állapotképe (engine_status.read)."""
    osszes: dict = {}
    ismeretlen = []
    for p in profiles or []:
        if p.id == active_id:
            continue
        snap = read(p)
        if not snap:
            ismeretlen.append(p.tag or p.id)
            continue
        for sym, n in _counts_of_snapshot(snap).items():
            osszes[sym] = osszes.get(sym, 0) + n
    return osszes, ismeretlen


def decide(symbol: str, own_count: int, others: dict, limit: int,
           n_profiles: int) -> tuple[bool, str]:
    """(engedélyezett-e, indok). Lásd a modul fejlécét."""
    if n_profiles <= 1 or limit <= 0:
        return True, ""
    masik = int(others.get(symbol, 0) or 0)
    if masik <= 0:
        return True, ""                          # csak a saját számla — a házirend dönt
    if own_count + masik >= limit:
        return False, (f"közös korlát: {symbol} már {masik} nyitott pozíció a "
                       f"többi számlán (+{own_count} itt), a korlát {limit}")
    return True, ""

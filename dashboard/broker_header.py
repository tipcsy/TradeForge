"""A fejléc bróker-órái (0029, 5. lépés).

Tibi kérése (2026-09-28): a „Bróker 11:23" helyett a bróker NEVE és a SAJÁT
szerverideje; több brókernél soronként egy („ActivTrades: 11:23", alatta
„RoboForex: 11:23") — akkor is külön sorban, ha az idő egyezik: a sor azt
mondja meg, melyik bróker órája az, nem csak azt, hogy mennyi az idő.

Tiszta függvény (nincs Tk, nincs MT5) → tesztelhető; a felület csak kiírja.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from core.i18n import t as _t


def clock_text(profiles, offsets: dict, now_utc: datetime) -> str:
    """A fejléc óra-szövege.

    `profiles`: a bróker-profilok (az otthoni az első); `offsets`: {id: a
    szerveróra eltolása mp-ben, vagy None, ha nem ismert}; `now_utc`: most.
    Az első sor végén az UTC is (egyszer — mindenkinek ugyanaz)."""
    sorok = []
    for p in profiles:
        off = offsets.get(p.id)
        ido = ("—" if off is None
               else f"{now_utc + timedelta(seconds=float(off)):%H:%M:%S}")
        sorok.append(_t("gui.hdr.clock_line", name=p.name or p.id, time=ido))
    if not sorok:
        return now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    sorok[0] += _t("gui.hdr.clock_utc", utc=f"{now_utc:%H:%M}")
    return "\n".join(sorok)


def show_broker_column(profiles) -> bool:
    """A „Bróker” oszlop csak TÖBB brókernél látszik (Tibi: „ha csak egy
    brókercég van, nem látszódik”)."""
    return len(list(profiles or [])) > 1


def broker_tags(profiles, symbol: str, other_pairs: dict) -> str:
    """Az instrumentum soránál a brókerek címkéi („Act, Rob”).

    Az OTTHONI brókeré mindig (a pár a configjában van); a többié csak akkor,
    ha a motorja futtatja a párt (`other_pairs`: {id: a motor párjainak
    halmaza, az állapotképéből}) — ahol az instrumentum nem létezik, ott a
    bróker nem látszik."""
    tags = []
    for i, p in enumerate(profiles or []):
        if i == 0 or symbol in (other_pairs.get(p.id) or ()):
            tags.append(p.tag or p.id)
    return ", ".join(tags)


def other_positions(profiles, snaps: dict) -> list:
    """A TÖBBI bróker nyitott pozíciói — címkével, CSAK MEGTEKINTÉSRE.

    `snaps`: {id: a motor állapotképe}. A gombok (zárás, BE, trailing) a mai
    felületen a ticket alapján az OTTHONI motornak szólnak; egy másik bróker
    pozícióján rossz motornak mennének. Ezért itt nincs művelet: a kezelés a
    Brókerek fülön, a saját motorján (Tibi döntése, 2026-09-30)."""
    out = []
    for p in list(profiles or [])[1:]:
        for pos in (snaps.get(p.id) or {}).get("positions_detail") or []:
            if isinstance(pos, dict):
                out.append({**pos, "broker": p.tag or p.id})
    return out


def merge_closed(profiles, home_closed, snaps: dict) -> list:
    """A lezárt kötések MINDEN brókertől — soronként a bróker címkéjével.

    Egy brókernél a lista változatlan (címke nélkül): az oszlop sem látszik."""
    ps = list(profiles or [])
    if len(ps) <= 1:
        return list(home_closed or [])
    out = [{**c, "broker": ps[0].tag or ps[0].id} for c in (home_closed or [])]
    for p in ps[1:]:
        for c in (snaps.get(p.id) or {}).get("closed_today") or []:
            if isinstance(c, dict):
                out.append({**c, "broker": p.tag or p.id})
    return out

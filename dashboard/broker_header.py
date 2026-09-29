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


def accounts_text(profiles, accounts: dict, limit_of) -> str:
    """A számlák sora a fejlécben — CSAK több brókernél (egynél: "").

    `accounts`: {id: {"balance", "currency", "daily_pnl", "health"}} — az
    otthonié a saját kapcsolatból, a többié a motorja állapotképéből.
    `limit_of(balance) -> float`: a napi veszteséglimit az adott számlára
    (a `trading` beállításból — százalékos módban számlánként más).

    Soronként: „Act: 946.64 EUR · napi +0.00 · limit 90"; ha a motor nem fut,
    az állapota is („· áll"). Alul az ÖSSZESÍTŐ PÉNZNEMENKÉNT (Tibi döntése,
    2026-09-30): eltérő pénznemű számlákat nem adunk össze, átváltás nincs."""
    ps = list(profiles or [])
    if len(ps) <= 1:
        return ""
    sorok, ossz = [], {}
    for p in ps:
        a = accounts.get(p.id) or {}
        tag = p.tag or p.id
        allapot = a.get("health")
        if a.get("balance") is None:
            sorok.append(_t("gui.acc.row_none", tag=tag,
                            state=_t("gui.acc.state." + (allapot or "nincs"))))
            continue
        bal, cur = float(a["balance"]), str(a.get("currency") or "")
        napi = float(a.get("daily_pnl") or 0.0)
        lim = float(limit_of(bal) or 0.0)
        sor = _t("gui.acc.row", tag=tag, balance=f"{bal:,.2f}", cur=cur,
                 daily=f"{napi:+.2f}", limit=f"{lim:.0f}")
        if lim > 0 and napi <= -lim:
            sor += _t("gui.acc.limit_hit")
        if allapot and allapot != "fut":
            sor += _t("gui.acc.state_suffix", state=_t("gui.acc.state." + allapot))
        sorok.append(sor)
        o = ossz.setdefault(cur, [0.0, 0.0, 0])
        o[0] += bal
        o[1] += napi
        o[2] += 1
    if sum(v[2] for v in ossz.values()) > 1:
        sorok.append("   ".join(
            _t("gui.acc.total", cur=c, balance=f"{v[0]:,.2f}", daily=f"{v[1]:+.2f}")
            for c, v in sorted(ossz.items())))
    return "\n".join(sorok)

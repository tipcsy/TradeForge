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

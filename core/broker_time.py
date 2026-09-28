"""BRÓKER-IDŐ → KANONIKUS IDŐ — a több-brókeres működés időalapja.

⚠ A KÉRDÉS (2026-09-28, 0029 „Több bróker egyszerre"): a program minden órája
— a hangolt óra-paraméterek, a kereskedési sáv, a tiltott órák, a kapuk, az
ml_ai modelljeinek „óra" jellemzője — az ActivTrades SZERVER-idejében van. Egy
másik bróker szervere más zónában jár (a RoboForex-féle „New York-zárásos"
szerverek NY+7 órában), és ha a gyertyáit átváltás nélkül olvassuk be, minden
óra-alapú beállítás NÉMÁN elcsúszik — hibaüzenet nélkül.

⚠ A DÖNTÉS: NEM migráljuk a tárolt órákat UTC-re. Kanonikus órának a BERLINI
helyi időt vesszük — pontosan azt, amiben ma minden adat, paraméter és modell
van (az ActivTrades szervere ebben jár, lásd `gates/sessions.py` mérését).
Minden bróker saját szerver-idejét A HATÁRON váltjuk át erre. Így:
  • egyetlen hangolt paraméter és betanított modell sem változik;
  • ActivTrades-nél az átváltás ÜRES művelet → bitre ugyanaz a viselkedés;
  • a többi bróker ideje a nyári időszámítással együtt helyes.
A UTC-migráció ugyanezt érné el, de minden paramétert és modellt átírna.

⚠ A ZÓNA NEM TIPP, HANEM MÉRÉS: `tools/detect_server_zone.py` a bróker saját
gyertyáiból olvassa ki (a devizapiac hete NY 17:00-kor nyit — a hét első
gyertyájának szerver-órája évekre visszamenőleg megmutatja a zónát ÉS a nyári
átállás szabályát).

A zóna leírása: `"<IANA zóna>"` vagy `"<IANA zóna>+<óra>"` — pl.
`"Europe/Berlin"`, `"America/New_York+7"` (NY-zárásos szerver: az óra a NY
helyi idő +7 óra, és az USA szerint vált nyári időre).

TISZTA modul: se MT5, se fájl — a hívó adja a zónát (a configból: `broker.server_zone`).
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

CANONICAL_ZONE = "Europe/Berlin"


@dataclass(frozen=True)
class ServerZone:
    """Egy szerver órája: IANA zóna + egész órás eltolás (a zóna helyi idejéhez)."""
    zone: str = CANONICAL_ZONE
    shift_h: int = 0

    @property
    def is_canonical(self) -> bool:
        return self.zone == CANONICAL_ZONE and self.shift_h == 0

    def __str__(self) -> str:
        return self.zone if not self.shift_h else f"{self.zone}{self.shift_h:+d}"


CANONICAL = ServerZone()


def parse(spec) -> ServerZone:
    """`"Europe/Berlin"` / `"America/New_York+7"` / ServerZone / None → ServerZone.

    None vagy üres → a kanonikus (a mai egy-brókeres config így változatlan).
    Érvénytelen zónanévre ValueError — egy elgépelt zóna NÉMÁN elcsúsztatná az
    összes órát, ezért nem esünk vissza csendben."""
    if isinstance(spec, ServerZone):
        return spec
    if spec is None or str(spec).strip() == "":
        return CANONICAL
    s = str(spec).strip()
    zone, shift = s, 0
    for jel in ("+", "-"):
        i = s.rfind(jel)
        if i > 0 and s[i + 1:].isdigit():
            zone, shift = s[:i], int(s[i:])
            break
    try:
        ZoneInfo(zone)
    except Exception as e:                       # noqa: BLE001
        raise ValueError(f"ismeretlen időzóna: {spec!r}") from e
    return ServerZone(zone, shift)


def of_config(cfg: dict | None) -> ServerZone:
    """A config `broker.server_zone` mezője (hiányzik → kanonikus)."""
    return parse(((cfg or {}).get("broker") or {}).get("server_zone"))


# ── egyedi időpont ──────────────────────────────────────────────────────────

def wall_to_utc(wall: _dt.datetime, sz: ServerZone) -> _dt.datetime:
    """A szerver fal-órája (tzinfo-t figyelmen kívül hagyva) → valódi UTC."""
    naiv = _dt.datetime(wall.year, wall.month, wall.day, wall.hour, wall.minute,
                        wall.second, wall.microsecond)
    helyi = naiv - _dt.timedelta(hours=sz.shift_h)
    return helyi.replace(tzinfo=ZoneInfo(sz.zone)).astimezone(_dt.timezone.utc)


def utc_to_wall(utc: _dt.datetime, sz: ServerZone) -> _dt.datetime:
    """Valódi UTC → a szerver fal-órája (naiv datetime)."""
    if utc.tzinfo is None:
        utc = utc.replace(tzinfo=_dt.timezone.utc)
    helyi = utc.astimezone(ZoneInfo(sz.zone)).replace(tzinfo=None)
    return helyi + _dt.timedelta(hours=sz.shift_h)


def to_canonical(wall: _dt.datetime, sz: ServerZone) -> _dt.datetime:
    """Egy szerver-időpont kanonikus (berlini fal-óra) megfelelője.
    A bemenet tzinfo-ját (a fájlok „UTC" címkéjét) megőrizzük."""
    if sz.is_canonical:
        return wall
    k = utc_to_wall(wall_to_utc(wall, sz), CANONICAL)
    return k.replace(tzinfo=wall.tzinfo)


# ── vektorizált (gyertya-index) ─────────────────────────────────────────────

def index_to_utc(idx: pd.DatetimeIndex, sz: ServerZone) -> pd.DatetimeIndex:
    """Szerver fal-óra index → valódi UTC index.

    A visszaálláskor ismétlődő órát (őszi óraátállítás) téli időnek vesszük; a
    tavaszi „nem létező" órát előre toljuk. Deviza/index piacon ezek hétvégére
    esnek (zárva), kriptón egy-egy órát érinthetnek."""
    naiv = idx.tz_localize(None) if idx.tz is not None else idx
    naiv = naiv - pd.Timedelta(hours=sz.shift_h)
    lok = naiv.tz_localize(sz.zone, ambiguous=np.zeros(len(naiv), bool),
                           nonexistent="shift_forward")
    return lok.tz_convert("UTC")


def index_to_canonical(idx: pd.DatetimeIndex, sz: ServerZone) -> pd.DatetimeIndex:
    """Szerver fal-óra index → kanonikus fal-óra index, a bemenet címkéjével
    (a gyertya-fájlok „UTC"-nek címkézett fal-órát tárolnak).
    Kanonikus zónánál a bemenetet adja vissza VÁLTOZATLANUL (ugyanaz az objektum)."""
    if sz.is_canonical:
        return idx
    kan = index_to_utc(idx, sz).tz_convert(CANONICAL_ZONE).tz_localize(None)
    return kan.tz_localize(idx.tz) if idx.tz is not None else kan


def frame_to_canonical(df: pd.DataFrame, sz: ServerZone) -> pd.DataFrame:
    """Gyertya-tábla indexének átváltása (kanonikusnál a bemenet, másolás nélkül)."""
    if sz.is_canonical:
        return df
    out = df.copy()
    out.index = index_to_canonical(df.index, sz)
    return out[~out.index.duplicated(keep="last")]

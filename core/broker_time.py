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
    """Az aktív bróker `server_zone` mezője (hiányzik → kanonikus)."""
    from core import broker_profile
    try:
        return broker_profile.active(cfg).server_zone
    except ValueError:
        return broker_profile.main(cfg).server_zone


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


def _epoch_ki(idx: pd.DatetimeIndex, unit: str) -> np.ndarray:
    """⚠ A `core.epoch`-on át: a nyers int64-nézet az index SAJÁT felbontását adja (s/ms/
    us/ns) — egy fix `// 10**9` nem-ns indexen csendben rossz számot adna."""
    from core import epoch
    return epoch.sec(idx) if unit == "s" else epoch.ns(idx) // 10 ** 6


def epoch_to_canonical(sec, sz: ServerZone, unit: str = "s"):
    """MT5-időbélyeg (a szerver fal-órája epoch-ként: `time`, `time_msc`) →
    ugyanez kanonikus fal-órában. Skalár vagy numpy tömb; `unit` "s" vagy "ms".
    Kanonikus zónánál a bemenet VÁLTOZATLANUL."""
    if sz.is_canonical:
        return sec
    skalar = np.isscalar(sec)
    a = np.atleast_1d(np.asarray(sec, dtype=np.int64))
    idx = pd.to_datetime(a, unit=unit)
    kan = index_to_canonical(pd.DatetimeIndex(idx), sz)
    out = _epoch_ki(kan, unit)
    return int(out[0]) if skalar else out


def canonical_to_server_epoch(sec, sz: ServerZone, unit: str = "s"):
    """Az `epoch_to_canonical` fordítottja — MT5-lekérdezés határaihoz
    (`copy_rates_range`, `history_deals_get` stb.)."""
    if sz.is_canonical:
        return sec
    skalar = np.isscalar(sec)
    a = np.atleast_1d(np.asarray(sec, dtype=np.int64))
    idx = pd.DatetimeIndex(pd.to_datetime(a, unit=unit))
    utc = index_to_utc(idx, CANONICAL)
    fal = utc.tz_convert(sz.zone).tz_localize(None) + pd.Timedelta(hours=sz.shift_h)
    out = _epoch_ki(fal, unit)
    return int(out[0]) if skalar else out


# ── ÓRÁNKÉNTI ELTOLÁS-TÁBLÁZAT (2026-10-13, Tibi: „Egy brókernél egy idő
# van. Nem elég azt használni?") ─────────────────────────────────────────────
# Az eltolás CSAK a zónától és az időponttól függ — instrumentumtól és
# stratégiától nem. Ezért zónánként EGY táblázat (`óra → másodperc`), amit
# minden pár és stratégia közösen olvas; egy óra eltolását EGYSZER számoljuk ki.
# Egy fix szám nem elég: a NY és a berlini nyári átállás hetekkel eltér (évente
# ~4 hétig 0 vagy 2 óra a megszokott 1 helyett).
#
# ⚠ Mérve (2026, 5 percenként, 105 408 időpont): a táblázat MINDEN valódi
# időpontra bitre a pontos átváltást adja. Az egyetlen eltérés a berlini tavaszi
# átállás NEM LÉTEZŐ órája (vasárnap 02:00–03:00) — ott gyertya sincs, és a
# pontos számítás is értelmetlen értéket ad.
_OFFSET_TABLAK: dict = {}


def canonical_to_server_epoch_fast(sec, sz: ServerZone):
    """Ugyanaz, mint a `canonical_to_server_epoch` (másodpercben), de a zóna
    ÓRÁNKÉNTI eltolás-táblázatából. Skalár vagy numpy tömb."""
    if sz.is_canonical:
        return sec
    skalar = np.isscalar(sec)
    a = np.atleast_1d(np.asarray(sec, dtype=np.int64))
    tabla = _OFFSET_TABLAK.setdefault((sz.zone, sz.shift_h), {})
    orak = a // 3600
    uj = [h for h in np.unique(orak).tolist() if h not in tabla]
    if uj:
        uj_a = np.asarray(uj, dtype=np.int64) * 3600
        for h, o in zip(uj, (canonical_to_server_epoch(uj_a, sz) - uj_a).tolist()):
            tabla[h] = int(o)
    out = a + np.fromiter((tabla[h] for h in orak.tolist()), dtype=np.int64,
                          count=len(a))
    return int(out[0]) if skalar else out


def frame_to_canonical(df: pd.DataFrame, sz: ServerZone) -> pd.DataFrame:
    """Gyertya-tábla indexének átváltása (kanonikusnál a bemenet, másolás nélkül)."""
    if sz.is_canonical:
        return df
    out = df.copy()
    out.index = index_to_canonical(df.index, sz)
    return out[~out.index.duplicated(keep="last")]

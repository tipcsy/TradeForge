"""
MT5 chart-vizualizáció ÍRÓCSATORNA.

A stratégia rajzolási primitíveket ad (`strategy.visual`: Rect/VLine/Trend/Text/
Label); ez a modul ezeket az MT5 Common\\Files mappájába sorosítja, ahonnan a
`TradeForgeViz.mq5` indikátor felolvassa és kirajzolja. A Python NEM tud MT5
chartra rajzolni (a MetaTrader5 API csak adat + kereskedés — nincs benne
objektum-/chart-vezérlés), ezért fájl + indikátor a csatorna.

A fájl a kívánt ÁLLAPOT teljes PILLANATKÉPE: minden objektum a jelenlegi
méretével újra kiíródik, az indikátor upsert-el és sosem töröl (lásd
strategy.visual). Az idő NYERS bar-idő integer (a copy_rates adja), így nincs
időzóna-csúszás. Írás atomikus (temp → replace), hogy az indikátor sose olvasson
fél fájlt.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

from core.broker_adapter import mt5

from core.mt5_connector import MT5_LOCK
from strategy.visual import PREFIX


def files_dir() -> Optional[Path]:
    """Az MT5 Common\\Files mappa (FILE_COMMON).

    Elsődlegesen az MT5-öt kérdezzük. Ha nincs kapcsolat, a SZABVÁNYOS MetaQuotes
    Common útra esünk vissza — így az offline export (MT4-es visszajátszás) MT5
    futtatása NÉLKÜL is működik.

    ⚠ Mérve (MT4-szonda, 2026-08-09): a Common mappa **közös** az MT4 és az MT5
    között, és **PORTABLE módban sem költözik** (a terminál adatmappája
    `C:\\Metatrades\\…` volt, a Common mégis az AppData alatt). Ezért írhat ide a
    Python egyszer, és olvashatja mindkét terminál."""
    with MT5_LOCK:
        info = mt5.terminal_info()
    if info is not None:
        return Path(info.commondata_path) / "Files"
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "MetaQuotes" / "Terminal" / "Common" / "Files"
    return None


# ── A CHART a BRÓKER világában él (2026-10-13) ────────────────────────────
# A Python mindent KANONIKUS névvel és órával számol (`GOLD`, berlini fal-óra).
# A TradeForgeViz viszont a chart SAJÁT szimbólumát (`_Symbol`) és a SZERVER
# óráját látja. ActivTradesnél a kettő azonos volt — RoboForexnél nem: ott a
# Ger40 `.DE40Cash`, a GOLD `XAUUSD`, a szerver-óra pedig NY+7. Így az indikátor
# `TFV_.DE40Cash.csv`-t keresett (nem volt), a fájl `TFV_Ger40.csv` volt: a chart
# ÜRES maradt, „mintha rajta sem lenne". A határon fordítunk, mint az adapter.

def chart_symbol(symbol: str) -> str:
    """Kanonikus név → a futó bróker chart-szimbóluma (nincs profil → változatlan)."""
    try:
        from core import broker_adapter
        p = broker_adapter.current()
        return p.to_broker(symbol) if p is not None else symbol
    except Exception:
        return symbol


def canonical_symbol(chart_sym: str) -> str:
    """A chart-szimbólum → kanonikus név (az életjel-fájlok olvasásához)."""
    try:
        from core import broker_adapter
        p = broker_adapter.current()
        return p.to_canonical(chart_sym) if p is not None else chart_sym
    except Exception:
        return chart_sym


_IDO_ATTR = ("t", "t1", "t2")


def to_chart_time(objects: list) -> list:
    """A rajz-objektumok idői (kanonikus) → a futó bróker SZERVER-órájára.
    Kanonikus szerverórájú brókernél (ActivTrades) a bemenet változatlan.

    ⚠ EGYETLEN TÖMBÖS ÁTVÁLTÁS (2026-10-13, Tibi: „iszonyatosan lassú lett a
    program"). Az első változat objektumonként és mezőnként külön hívta a
    `canonical_to_server_epoch`-ot — minden hívás egy pandas-index + időzóna-
    konverzió. Egy pár rajza több ezer objektum (minden gyertyának sáv-állapota
    van): mérve 1,4 mp / pár / stratégia, a GIL-t fogva — a felület akadozott.
    Most minden időt EGY numpy-tömbben váltunk át (a nyári időszámítás miatt nem
    elég egy fix eltolás: a NY és a berlini átállás hetekkel eltér)."""
    try:
        from core import broker_adapter, broker_time as _bt
        p = broker_adapter.current()
        sz = getattr(p, "server_zone", None)
        if sz is None or sz.is_canonical:
            return objects
    except Exception:
        return objects
    import dataclasses
    import numpy as np
    hely, ertek = [], []                      # (objektum-index, mező) → érték
    for i, o in enumerate(objects):
        if not dataclasses.is_dataclass(o):
            continue
        for a in _IDO_ATTR:
            v = getattr(o, a, None)
            if isinstance(v, (int, float)) and v:
                hely.append((i, a))
                ertek.append(int(v))
    if not ertek:
        return objects
    uj = _bt.canonical_to_server_epoch(np.asarray(ertek, dtype=np.int64), sz)
    # ⚠ MÁSOLATON írunk (a stratégia rajz-objektumai lehetnek tároltak — helyben
    # átírva körönként ÚJRA eltolódnának), de `copy.copy` + mezőírással: a
    # `dataclasses.replace` újrafuttatja az `__init__`-et, ez itt a költség zöme.
    import copy as _copy
    out = list(objects)
    utolso = -1
    for (i, a), v in zip(hely, uj):
        if i != utolso:
            out[i] = _copy.copy(objects[i])
            utolso = i
        object.__setattr__(out[i], a, int(v))
    return out


def write_lines(symbol: str, lines: list, clear_first: bool = False,
                name_suffix: str = "") -> Optional[Path]:
    """A `symbol` teljes pillanatképét kiírja `TFV_<symbol>.csv`-be ELŐRE
    sorosított sorokból (több-stratégiás viz: a hívó stratégiánként `tag_line`-nal
    megjelölt sorokat ad). Atomikus (temp → replace).

    `clear_first=True` → a pillanatkép ELÉ egy `CLEAR` sort tesz. Az indikátor a
    fájlt sorrendben dolgozza fel: előbb LETÖRLI az összes saját objektumát, majd
    frissen kirajzolja a következő sorokat — így paraméter-váltás után a régi
    (elavult) belépő-jelzések garantáltan eltűnnek, EGY atomi írásban (nincs
    verseny a külön CLEAR-fájl és a rajz között)."""
    d = files_dir()
    if d is None:
        return None
    d.mkdir(parents=True, exist_ok=True)
    # `name_suffix`: a visszajátszás-export SAJÁT fájlba mehet (pl. `TFV_Ger40_BT.csv`),
    # így az élő motor pillanatképe nem írja felül, és fordítva.
    path = d / f"{PREFIX}{chart_symbol(symbol)}{name_suffix}.csv"
    tmp  = path.with_suffix(".csv.tmp")

    payload = "\n".join((["CLEAR"] if clear_first else []) + list(lines))
    if payload:
        payload += "\n"
    tmp.write_text(payload, encoding="ascii", errors="replace")

    # os.replace atomikus egy köteten belül. Ritka verseny: az MQL5 épp olvassa
    # → Windows PermissionError; pár próbálkozás elég (a beolvasás mikroszekundum).
    for _ in range(5):
        try:
            os.replace(tmp, path)
            return path
        except PermissionError:
            time.sleep(0.05)
    return None


def write(symbol: str, objects: list) -> Optional[Path]:
    """A `symbol` objektum-pillanatképe (nem-tagelt, egy-stratégiás). Visszafelé
    kompatibilis burok a `write_lines` fölött."""
    return write_lines(symbol, [o.line() for o in objects])


def clear(symbol: str) -> Optional[Path]:
    """A `symbol` chart-objektumainak TÖRLÉSE: egy `CLEAR` direktívát ír a
    fájlba, amit az indikátor a saját (TFV_ prefixű) objektumai törlésével
    értelmez. A vizualizáció KI-kapcsolásához (V gomb) használjuk."""
    d = files_dir()
    if d is None:
        return None
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{PREFIX}{chart_symbol(symbol)}.csv"
    tmp  = path.with_suffix(".csv.tmp")
    tmp.write_text("CLEAR\n", encoding="ascii")
    for _ in range(5):
        try:
            os.replace(tmp, path)
            return path
        except PermissionError:
            time.sleep(0.05)
    return None

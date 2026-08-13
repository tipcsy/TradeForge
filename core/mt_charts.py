"""NYITVA VAN-E A CHART? — a TradeForgeViz életjele.

A felhasználó kérdése: „valahogy azt tudjuk-e nézni, hogy az MT5-ön a chart
éppen nyitva van-e? A cél, hogy elkerüljük azt, hogy jelzésre van téve, de az
MT5-ön nincs beállítva az adott chart — így nem fogja megkapni a jelzést."

⚠ EZ EGY NÉMA HIBA VOLT. A Python a viz-fájlba ÍR, de eddig nem láthatta, hogy
olvassa-e valaki. Ha egy pár „csak jelzés" módban áll, és nincs hozzá nyitott
chart a TradeForgeViz-cel, a jelzés SEHOL nem jelenik meg — a felhasználó pedig
várja, és csak annyi történik, hogy nincs. A program semmit nem tudott mondani.

A megoldás az indikátor oldaláról jön: a `TradeForgeViz.mq5` időnként ír egy
`TFV_ALIVE_<szimbólum>_<idősík>[_<stratégia>].txt` fájlt a közös mappába, és
chart-bezáráskor TÖRLI. Ez a modul csak beolvassa.

⚠ PÉLDÁNYONKÉNT KÜLÖN FÁJL. Ha minden chart ugyanabba írna, egymást nyomnák el,
és a legutolsó író elfedné a többit — egyetlen nyitott chartnál is „minden
rendben" látszana. Külön fájlnál a mappa-listázás megmondja, ki él.

⚠ AZ IDŐT A FÁJL KORÁBÓL vesszük, nem a fájlban levő időbélyegből: a terminál
SZERVER-időt ír, ami órákkal eltérhet a gép órájától. A fájl `mtime`-ja viszont
a helyi óra — és a kérdés („frissült-e az utóbbi percben") csak így válaszolható
meg helyesen.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

log = logging.getLogger(__name__)

PREFIX = "TFV_ALIVE_"

# Meddig tekintünk élőnek egy chartot? Az indikátor `TimerSeconds`-onként ír
# (alap 1 mp), de a terminál elfoglaltság esetén késhet, és a fájlrendszer
# időbélyege is durva. 90 mp bőven fedi a normális ingadozást, és elég szoros
# ahhoz, hogy egy lefagyott/leállított terminál pár percen belül kiessen.
MAX_AGE_SEC = 90


def common_dir() -> Path | None:
    """Az MT5 KÖZÖS (Common) mappája — ahova a viz-fájlok mennek."""
    try:
        from core import mt5_visual
        d = mt5_visual.common_files_dir()
        return Path(d) if d else None
    except Exception:
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return None
        d = Path(appdata) / "MetaQuotes" / "Terminal" / "Common" / "Files"
        return d if d.is_dir() else None


def _parse(p: Path) -> dict | None:
    """Egy életjel-fájl → `{symbol, timeframe, strategy}`.

    A NÉVBŐL is kiolvasható, de a TARTALMAT részesítjük előnyben: a szimbólum
    tartalmazhat aláhúzást (pl. `US_500`), amitől a névből való bontás elhasalna.
    """
    try:
        txt = p.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    parts = [x.strip() for x in txt.split(";")]
    if len(parts) >= 4 and parts[0] == "ALIVE":
        return {"symbol": parts[1], "timeframe": parts[2], "strategy": parts[3]}
    # Régi/sérült fájl → a névből, best-effort.
    stem = p.stem[len(PREFIX):] if p.stem.startswith(PREFIX) else p.stem
    return {"symbol": stem, "timeframe": "", "strategy": ""}


def open_charts(max_age_sec: int = MAX_AGE_SEC) -> list:
    """A MOST nyitott, Viz-t futtató chartok: `[{symbol, timeframe, strategy, age}, …]`."""
    d = common_dir()
    if d is None or not d.is_dir():
        return []
    now = time.time()
    out = []
    try:
        for p in d.glob(PREFIX + "*.txt"):
            try:
                age = now - p.stat().st_mtime
            except OSError:
                continue
            if age > max_age_sec:
                continue
            rec = _parse(p)
            if rec:
                rec["age"] = age
                out.append(rec)
    except OSError as ex:
        log.debug("életjel-olvasás hiba: %s", ex)
    return out


def open_symbols(max_age_sec: int = MAX_AGE_SEC) -> set:
    """Mely INSTRUMENTUMOKHOZ van nyitott, Viz-t futtató chart."""
    return {r["symbol"] for r in open_charts(max_age_sec) if r.get("symbol")}


def is_open(symbol: str, max_age_sec: int = MAX_AGE_SEC) -> bool:
    return symbol in open_symbols(max_age_sec)


def cleanup_stale(max_age_sec: int = MAX_AGE_SEC * 20) -> int:
    """Nagyon régi életjel-fájlok törlése (a terminál összeomlása után maradók).

    ⚠ Nem a `max_age_sec`-kel törlünk: egy pár percre megakadt terminál fájlját
    eldobni azt jelentené, hogy a chart „bezárult", holott csak lassú. Ezért a
    takarítás küszöbe SOKKAL nagyobb — a kijelzés amúgy is a kor alapján dönt.
    """
    d = common_dir()
    if d is None or not d.is_dir():
        return 0
    now, n = time.time(), 0
    for p in d.glob(PREFIX + "*.txt"):
        try:
            if now - p.stat().st_mtime > max_age_sec:
                p.unlink()
                n += 1
        except OSError:
            continue
    return n

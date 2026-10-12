"""
Piac-stratégia (MarketStrategy) — pluggable PIAC-OSZTÁLYOZÓK könnyű registere.

A kereskedő-stratégiákkal szimmetrikus, DE instrumentumonként EGY (a piac-képnek
egy koherens forrása kell). A választás 2026-10-12 óta a PIAC-KAPU beállítása
(`gates.market.classifier`, alap `regime`; feloldás: `core.gates.market_classifier`)
— korábban az instrumentum (`pairs.<sym>.market_strategy`) kapcsolta be, és
nélküle a kapu némán semmit nem csinált. A chart-sáv: `gates.market.viz`.

Jelenleg egyetlen osztályozó: `regime` (core.regime, ADX/DI/ATR → 8 kategória).
Új piac-stratégia = egy név ide + a classify/legend ág. A dashboard és a viz
GENERIKUSAN kezeli (kód + címke + szín), így az osztályozó cserélhető.
"""

from __future__ import annotations
from core.i18n import LabelMap as _LabelMap, t as _t

from core import regime

# A regisztrált piac-osztályozók (a GUI ebből kínál választékot).
_REGISTERED = ("regime",)
NAME_HU = {"regime": "Regime (ADX/DI/ATR)"}

# Megjelenítés kategóriánként: (rövid címke, szemantikus szín-név a dashboardhoz).
# ⚠ A SZÍN itt marad (viselkedés), a RÖVID CÍMKE a katalógusban van
# (`regime.short.<kategória>`) — a tábla oszlopa szűk, ezért külön a hosszú
# névtől (`regime.name.*`).
_COLOR = {
    regime.CLEAN_BULL:    "green",
    regime.CLEAN_BEAR:    "red",
    regime.VOLATILE_BULL: "yellow",
    regime.VOLATILE_BEAR: "yellow",
    regime.RANGING:       "white",
    regime.DEAD:          "muted",
    regime.UNCERTAIN:     "red",
    regime.TRANSITION:    "muted",
    regime.UNCATEGORIZED: "muted",
}
_SHORT = _LabelMap("regime.short", tuple(_COLOR))


def registered_market_names() -> list[str]:
    return list(_REGISTERED)


def name_for(cfg: dict, symbol: str) -> "str | None":
    """A piac-kapu osztályozója ezen a páron (lásd `core.gates.market_classifier`)."""
    from core import gates as _g
    return _g.market_classifier(cfg, symbol)


def classify_series(name: str, df15):
    """Per-gyertya kategória-sorozat az adott osztályozóval (None, ha ismeretlen)."""
    if name == "regime":
        return regime.classify(df15)
    return None


# Az utolsó besorolás gyertyánként: a kijelzés-út (felület, motor) ütemenként
# kérdez, a besorolás viszont csak ÚJ M15 gyertyánál változhat. Mérve párankként
# 6–16 ms — mióta MINDEN páron fut (nem csak ahol az instrumentum bekapcsolta),
# ez ~26 párnál ütemenként már érezhető volna.
_LATEST: dict = {}


def latest_category(name: str, df15) -> "str | None":
    """A LEGUTOLSÓ gyertya piac-kategóriája (a dashboard-kijelzéshez)."""
    if df15 is None or len(df15) == 0:
        return None
    try:
        kulcs = (name, len(df15), df15.index[-1], float(df15["close"].iloc[-1]),
                 float(df15["close"].iloc[0]))
    except Exception:
        kulcs = None
    if kulcs is not None and kulcs in _LATEST:
        return _LATEST[kulcs]
    s = classify_series(name, df15)
    cat = None if s is None or len(s) == 0 else s.iloc[-1]
    if kulcs is not None:
        if len(_LATEST) > 512:
            _LATEST.clear()
        _LATEST[kulcs] = cat
    return cat


def code(name: str, category: str) -> int:
    """Kategória → egész kód (a viz STATE-sorához / a Bands szín-indexéhez)."""
    if name == "regime":
        return regime.code(category)
    return 0


def display(category: str) -> tuple:
    """Kategória → (rövid címke, szemantikus szín-név) a dashboard-cellához."""
    return (_SHORT.get(category, "—"), _COLOR.get(category, "muted"))


def display_labels() -> list:
    """MINDEN lehetséges kategória-címke — az oszlop-szélesség méréséhez.

    A `Piac` oszlop mintaszövege eddig egy bedrótozott „Sz.Bika" volt, holott a
    leghosszabb címke az „Érdektelen": élesben az „Id.Medve"/„Oldalazás"/
    „Érdektelen" vége levágódott. Ha új kategória kerül a `_COLOR`-ba, az
    oszlop MAGÁTÓL követi — nem kell egy távoli mintaszöveget karbantartani."""
    return _SHORT.values()

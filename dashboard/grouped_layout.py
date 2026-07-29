"""
Csoportosított dashboard-elrendezés: instrumentum-sor + stratégia-alsorok.

**A probléma, amit megold.** A jelenlegi tábla EGY sorban keveri a két szintet:

    | Symbol | BID | ASK | Vált% |   ← instrumentum („élő bizonyíték")
    | Spread | Együtt | Piac |        ← ELŐSZŰRŐK — valójában per STRATÉGIA
    | Minőség | Vezérlés | OPT |      ← per STRATÉGIA
    | Pozíció | Napi P&L |            ← per STRATÉGIA (összegezve látszik)

Ezért nem lehet megmondani, MELYIK stratégia minősége „rossz", melyik vezérlés
melyikhez tartozik, és melyik stratégia kötött. A config viszont már régóta
per (pár × stratégia) — a felület mutatott mást.

**A megoldás.** A sor kettéválik:

    ▼ GOLD   4006,8 / 4007,2  +0,4%      ●○     +12,40 $   [gombok]
       └ wpr_sma  KÖT    ▮▨▮ ⛔1   jó     [R]  [OPT 40%]  1 poz.  +14,60 $
       └ ml_ai    jelez  ▮▮▮ ✓     rossz  [R]  [OPT]      —       −2,20 $

Két stratégia = HÁROM sor, nem hat: a kapuk CELLÁK maradnak, nem sorok.

**A kapu-csík betű nélkül.** Egy szegmens = egy regisztrált kapu (`core.gates`),
mindig ugyanabban a sorrendben. Nem kell tudni, melyik a harmadik szegmens ahhoz,
hogy lásd: valami blokkol — a nevek teljes alakban a kapu-panelen élnek. Így egy
10 kapus jövőben sem lesz belőle `E`/`E2`/`E3`.

Ez a modul csak az ELRENDEZÉST adja; az adatot a hívó tölti.
"""

from __future__ import annotations

from strategy.base import Column

# ── Mi tartozik az INSTRUMENTUMHOZ ───────────────────────────────────────
# Szigorúan csak az, ami a stratégiától FÜGGETLEN. Az „élő bizonyíték" csoport
# (ár + változás) a felhasználó kifejezett kérése: nem az ár érdekes, hanem hogy
# LÁTSZIK a kommunikáció.
INSTRUMENT_COLUMNS = [
    Column("symbol", "Symbol", 12, "w",      kind="fixed"),
    Column("bid",    "BID",     9, "center", kind="fixed"),
    Column("ask",    "ASK",     9, "center", kind="fixed"),
    Column("change", "Vált.%",  7, "center", kind="fixed"),
    Column("spread", "Spread",  8, "center", kind="fixed"),
    Column("ready",  "Kész",    6, "center", kind="fixed"),
    Column("daily",  "Napi P&L", 9, "center", kind="fixed"),
]

# ── Mi tartozik a (INSTRUMENTUM × STRATÉGIA) párhoz ──────────────────────
# A `gates` cella a kapu-CSÍK + badge; a `quality`/`opt`/`position`/`daily`
# mostantól egyértelmű, mert a sor megmondja, melyik stratégiáé.
STRATEGY_COLUMNS = [
    Column("strategy", "Stratégia", 12, "w",      kind="fixed"),
    Column("mode",     "Mód",        7, "center", kind="fixed"),
    Column("gates",    "Kapuk",      9, "center", kind="fixed"),
    Column("quality",  "Minőség",    9, "center", kind="fixed"),
    Column("position", "Pozíció",   10, "center", kind="fixed"),
    Column("daily",    "Napi P&L",   9, "center", kind="fixed"),
    Column("opt",      "Opt",       18, "w",      kind="fixed"),
]


def instrument_indent(mono_font) -> int:
    """A gyerek-sorok behúzása pixelben — a nyitó/csukó jel szélessége.
    Egy helyen, hogy a fejléc és a sorok ne csússzanak szét."""
    return mono_font.measure("0") * 3


# ── Automatikus kinyitás ─────────────────────────────────────────────────
def should_expand(ds, per_strategy_states: dict, blocked_fn) -> bool:
    """Kinyíljon-e MAGÁTÓL ez az instrumentum?

    A felhasználó dilemmája szó szerint: „sok hasznos információ, de nem túl
    sok". A válasz nem az információ csökkentése, hanem hogy alapból CSUKVA
    legyen minden, és magától nyíljon ki az, amin VAN MIRE NÉZNI:

      • van nyitott pozíció, VAGY
      • valamelyik stratégiát épp blokkolja egy kapu.

    A csendes párok egy sorban maradnak. A felhasználó kézi nyitása/csukása
    ezt FELÜLÍRJA (a hívó tartja nyilván) — különben a következő frissítés
    visszazárná, amit épp kinyitott."""
    if (getattr(ds, "pos_count", 0) or 0) > 0:
        return True
    return any(blocked_fn(st) for st in (per_strategy_states or {}).values())


def ready_badge(ok: int, total: int) -> str:
    """Az instrumentum-sor összegzése: hány stratégiája kereskedésre kész.

    Tömör, betű nélküli jelölés (`●○` = kettőből egy kész), hogy csukott
    állapotban is látszódjon, van-e baj — kinyitás nélkül."""
    if total <= 0:
        return "—"
    return "●" * ok + "○" * max(0, total - ok)

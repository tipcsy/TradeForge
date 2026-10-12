"""
MANUÁLIS ELŐSZŰRŐ — a reggeli kézi piac-áttekintés mint KAPU.

Az állapotot Tibi választja ki naponta, instrumentumonként (`core/manual_filter.py`).
A kapu a jelzés IRÁNYÁVAL együtt ítél:

    Ne kereskedj!   → gátol (minden irány)
    Óvatosan        → fele kockázat
    Szép chart ↑    → a SELL gátolva, a BUY mehet
    Szép chart ↓    → a BUY gátolva, a SELL mehet
    Nincs / ↕       → nem szól bele

⚠ A HATÁS A KAPU SAJÁT ALAP-LÉTRÁJÁBÓL jön (`GATE["bands"]`), nem egy
egyetlen hatásból: ugyanaz a kapu egyszer gátol, máskor felez. Stratégiánként a
szokásos módon kikapcsolható (`pairs.<SYM>.gates.manual.<stratégia>: "none"`),
és a létra is felülírható — mint bármely kategória-kapunál.

⚠ ALAPBÓL `block` (a beépített kapuk közül a volatilitáson kívül egyedül), és ez
nem sérti az „új kapu ne kezdjen némán kereskedni másképp" szabályt: a kapu csak
akkor él, ha a config-ban bekapcsolták (`manual_filter.enabled`), ÉS aznap
kézzel kiválasztottak egy állapotot. Egy frissítéstől semmi nem változik.

⚠ BACKTESTBEN NINCS ADAT (a reggeli kézi ítéletnek nincs múltja) → fail-open.

TISZTA modul: a mai állapotot a hívó adja (`ctx.ds.manual_state` a motorban,
`ctx["manual_state"]` a kijelzésnél).
"""

from __future__ import annotations

GATE = {"key": "manual", "default_effect": "block", "phase": "signal",
        "kind": "category",
        # Az alap-létra: a kapu szintje → hatás (lásd core.manual_filter.LEVELS).
        "bands": {"no_trade": "block", "cautious": "reduce", "against": "block"}}


def _state(ctx) -> str | None:
    ds = getattr(ctx, "ds", None)
    return getattr(ds, "manual_state", None) if ds is not None else None


def measure(ctx) -> tuple:
    """`(bukott_e, szint)` — a szint az iránnyal feloldott ítélet."""
    from core import manual_filter as _mf
    signal = getattr(ctx, "signal", "NONE")
    st = _state(ctx)
    if signal == "NONE" or not st:
        return False, None
    lvl = _mf.level_of(st, signal)
    return lvl != _mf.LEVEL_OK, lvl


def block_log(ctx) -> str:
    from core import manual_filter as _mf
    st = _state(ctx) or _mf.NONE
    return (f"manuális előszűrő: {_mf.LABEL.get(st, st)} "
            f"(jel: {getattr(ctx, 'signal', '?')}) → kimarad.")


def evaluate(ctx: dict) -> tuple:
    """A KIJELZÉS állapota. Irány nélkül (nincs jelzés) csak a „Ne kereskedj!"
    gátol egyértelműen — a többi állapot a jelzéstől függ, ezért átenged."""
    from core.gates import PASS, BLOCKING
    from core import manual_filter as _mf
    st = (ctx or {}).get("manual_state") or _mf.NONE
    return (BLOCKING if st == _mf.NO_TRADE else PASS), _mf.LABEL.get(st, st)

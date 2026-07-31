"""Lezárt kötések bontása (szimbólum × stratégia) — TISZTA függvények.

A motor a napi P&L-t nem bontja stratégiánként: az MT5 deal-előzményből csak a
`magic` jön, a kézzel nyitott (majd utólag hozzárendelt) pozíciónál pedig a magic
a kézi marad. A hozzárendelést a saját nyilvántartásunk tudja
(`core/adopted.py` → `live_trader.strategy_of_ticket`).

Ez a modul CSAK az összegzést végzi, és szándékosan nincs MT5/tkinter függése:
a hívó adja be a lezárt kötések listáját és a feloldó függvényeket. Így a
dashboard, a „Lezárt" fül és a tesztek UGYANAZT a számot kapják — nem tud
szétcsúszni, mint korábban a Minőség-oszlopnál.

Az R-ről: a **pénz-alapú** definíciót használjuk (`P&L / belépéskori kockázat`),
mert a felhasználó így határozta meg (15 $ tét = 1 R → +1 R = +15 $). Ez eltér az
ÁR-alapú közelítéstől (`elmozdulás / SL-táv`), és **részleges zárásnál vagy
költséggel** a kettő MÁS eredményt ad — lásd a modul tesztjeit.
"""

from __future__ import annotations


def _bucket() -> dict:
    return {"pnl": 0.0, "count": 0, "wins": 0, "losses": 0,
            "r": 0.0, "r_count": 0}


def split_by_strategy(closed, resolve=None, risk_of=None) -> dict:
    """Lezárt kötések → `{(symbol, strategy): {pnl, count, wins, losses, r, r_count}}`.

    `closed`   — a `mt5_connector.closed_positions_range/today` kimenete (dict-ek:
                 `symbol`, `magic`, `position`, `pnl`).
    `resolve`  — `fn(magic, position_id) -> str | None`, a stratégia feloldója
                 (`live_trader.strategy_of_ticket`). None → minden kötés a `None`
                 stratégiához kerül.
    `risk_of`  — `fn(position_id) -> float | None`, a belépéskori kockázat
                 (`core.position_meta.risk_of`). Hiányzó kockázat → a kötés NEM
                 számít bele az R-be (de a P&L-be igen), és `r_count` sem nő.

    A `strategy` értéke **None**, ha a kötés egyik stratégiához sem rendelhető
    (idegen vagy hozzá nem rendelt kézi pozíció) — a hívó dönti el, hogyan jeleníti
    meg. Szándékosan nem „—", hogy az adat ne keveredjen a formázással.
    """
    out: dict = {}
    for c in closed or []:
        if not isinstance(c, dict):
            continue
        sym = c.get("symbol")
        if not sym:
            continue
        pid = c.get("position")
        name = None
        if resolve is not None:
            try:
                name = resolve(c.get("magic"), pid)
            except Exception:
                name = None
        b = out.setdefault((sym, name), _bucket())
        try:
            pnl = float(c.get("pnl") or 0.0)
        except (TypeError, ValueError):
            pnl = 0.0
        b["pnl"] += pnl
        b["count"] += 1
        if pnl > 0:
            b["wins"] += 1
        elif pnl < 0:
            b["losses"] += 1
        if risk_of is not None:
            try:
                risk = risk_of(pid)
            except Exception:
                risk = None
            if risk:
                b["r"] += pnl / float(risk)
                b["r_count"] += 1
    return out


def totals_by_symbol(split) -> dict:
    """A (szimbólum × stratégia) bontásból az INSTRUMENTUM-szintű összesítő:
    `{symbol: {pnl, count, wins, losses, r, r_count}}`.

    A 2.0 terv jobb szélső „Összesítő" oszlopa ezt mutatja — és mivel ugyanabból a
    bontásból származik, a sor vége SOSEM mondhat mást, mint a blokkjai összege."""
    out: dict = {}
    for (sym, _name), b in (split or {}).items():
        t = out.setdefault(sym, _bucket())
        for k in t:
            t[k] += b.get(k, 0)
    return out


def for_symbol(split, symbol) -> dict:
    """Egy szimbólum stratégia-bontása: `{strategy: bucket}` (a `strategy` lehet
    None). Kényelmi nézet a sor kirajzolásához."""
    return {name: b for (sym, name), b in (split or {}).items() if sym == symbol}


def r_text(bucket, digits: int = 2) -> "str | None":
    """A bucket R-je megjelenítésre, vagy None, ha EGYETLEN kötéshez sem volt
    ismert a belépéskori kockázat. A None jelentése: „—", nem 0 R — a kettő
    összekeverése azt sugallná, hogy a kereskedés nullán zárt."""
    if not bucket or not bucket.get("r_count"):
        return None
    return f"{bucket['r']:+.{digits}f}R"

"""
BELELÓG-E A BACKTEST-ABLAK A MODELL TANÍTÁSI IDŐSZAKÁBA?

Egy tanult modell a saját tanító időszakán nem előrejelez, hanem EMLÉKEZIK.
Ott a backtest nem a stratégia képességét méri, hanem azt, mennyit jegyzett meg
— és ez nem apró torzítás:

    a mentett `ml_ai` modellek AUC-ja  a tanítóadaton  0,87–0,92
                                        friss adaton   0,48–0,56  (érmefeldobás)
    BTCUSD találati arány               in-sample      70,4%
                                        OOS            26,2%      (nullszaldó ~33%)

A 1000$ → 14 398$ tehát nem hiba a motorban (a spread-modell mérve helyes),
hanem annak a következménye, hogy a kötések ~89%-a a tanítási ablakon belül
esett, és a lot az egyenlegből számol (kamatos kamat).

Ez a modul CSAK SZÁMOL — a stratégiától kapja az ablakot (`training_window`),
és a felület dönti el, hogyan mutatja. Szabály-alapú stratégiánál (`wpr_sma`)
nincs tanítási ablak, tehát nincs mit jelezni.
"""

from __future__ import annotations

import pandas as pd


def _ts(v):
    if v is None:
        return None
    try:
        t = pd.Timestamp(v)
    except (ValueError, TypeError):
        return None
    return t.tz_localize(None) if t.tzinfo is not None else t


def overlap(bt_start, bt_end, train_from, train_to) -> dict:
    """`{"pct", "days", "bt_days", "from", "to"}` — mennyi a KÖZÖS rész.

    `pct`: a backtest-ablak hány százaléka esik a tanítási időszakba (0.0–1.0).
    Átfedés nélkül `pct = 0.0`. Hiányos dátumnál üres szótár."""
    a, z = _ts(bt_start), _ts(bt_end)
    ta, tz = _ts(train_from), _ts(train_to)
    if None in (a, z, ta, tz) or z <= a:
        return {}
    lo, hi = max(a, ta), min(z, tz)
    bt_days = max((z - a).total_seconds() / 86400.0, 1e-9)
    if hi <= lo:
        return {"pct": 0.0, "days": 0.0, "bt_days": bt_days, "from": None, "to": None}
    days = (hi - lo).total_seconds() / 86400.0
    return {"pct": min(days / bt_days, 1.0), "days": days, "bt_days": bt_days,
            "from": lo, "to": hi}


# A sávok szándékosan durvák: a lényeg nem a pontos százalék, hanem hogy az
# eredmény MENNYIRE olvasható. 100%-os átfedésnél a szám semmit nem mond a
# jövőről; 0% alatt viszont nincs miért riogatni.
def severity(pct: float) -> str:
    """`"none"` | `"partial"` | `"full"`"""
    if pct <= 0.001:
        return "none"
    return "full" if pct >= 0.85 else "partial"


def message(ov: dict) -> str:
    """Egysoros, ember-olvasható figyelmeztetés (üres szöveg = nincs mit mondani)."""
    if not ov or ov.get("pct", 0.0) <= 0.001:
        return ""
    pct = ov["pct"] * 100.0
    if severity(ov["pct"]) == "full":
        return (f"⚠ Az ablak {pct:.0f}%-a a modell TANÍTÁSI időszakára esik — "
                f"itt a modell emlékszik, nem előrejelez. Az eredmény NEM mond "
                f"semmit a jövőbeli teljesítményről.")
    return (f"⚠ Az ablak {pct:.0f}%-a a modell tanítási időszakára esik "
            f"({ov['from']:%Y-%m-%d} … {ov['to']:%Y-%m-%d}) — ennyivel felfelé "
            f"torzít. Tiszta méréshez válassz {ov['to']:%Y-%m-%d} utáni kezdetet.")


def for_strategy(strategy, symbol: str, cfg: dict, bt_start, bt_end) -> dict:
    """A stratégiától elkéri a tanítási ablakot, és visszaadja az átfedést.
    Nincs tanulás (vagy nincs modell) → üres szótár."""
    try:
        win = strategy.training_window(symbol, cfg)
    except Exception:
        return {}
    if not win:
        return {}
    return overlap(bt_start, bt_end, win[0], win[1])

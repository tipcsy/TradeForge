"""
Az oszlopok X-ELTOLÁSA — EGYETLEN igazságforrás a fejlécnek és a soroknak.

MIÉRT KÜLÖN MODUL. A widget-alapú táblában az oszlop-igazítás *alku* eredménye:
a fejléc és minden sor külön `pack`-láncot épít, és ezeknek véletlenül egyezniük
kell. A kód tele van erre figyelmeztető kommentekkel („a hívóknak UGYANAZT a két
értéket kell átadniuk, különben a fejléc és a sorok elcsúsznának"), és a
`test_live_table` oszlop-igazítási állítása pontosan ezt őrzi.

Vászonra rajzolva az oszlop nem alku, hanem ARITMETIKA: mindenki ugyanabból az
`[(kulcs, x, szélesség), …]` listából dolgozik. Az igazítás így KONSTRUKCIÓ
SZERINT igaz, nem véletlen — ezért van ez a néhány sor külön, tisztán,
tkinter-widgetek nélkül (a `live_row.widths()` betű-mérése az egyetlen Tk-függés,
azt a hívó adja be).

A SORREND kötött, és pontosan a `live_row.build_header` sorrendje:

    symbol bid ask change | [spread align market? momentum?] badge |
    stratégiánként: stages [position daily quality] ctrl [opt] |
    total_pos total_daily close
"""

from __future__ import annotations

from dashboard import live_row as _lr

# A cellák közti hézag — a widget-táblában `padx=(0, GAP)`, itt az x-lépés része.
GAP = _lr.GAP


def column_keys(strategies, collapsed: dict = None) -> list:
    """A megjelenő oszlopok kulcsai, a rajzolási sorrendben.

    A stratégia-oszlopok kulcsa `"<név>|<mező>"` — ugyanaz a mező stratégiánként
    külön oszlop, tehát a rendezés arra a blokkra hat, amelyikben kattintottál
    (a widget-tábla fejléce is így azonosítja őket)."""
    collapsed = collapsed or {}
    keys = ["symbol", "bid", "ask", "change"]
    if not collapsed.get("gates"):
        keys += ["spread", "align"]
        if _lr.show_market(collapsed):
            keys.append("market")
        if _lr.show_momentum(collapsed):
            keys.append("momentum")
        if _lr.show_cost(collapsed):
            keys.append("cost")
    keys.append("badge")
    for name in (strategies or []):
        keys.append(f"{name}|stages")
        if _lr.is_collapsed(collapsed, name):
            # Összecsukva a jelzés MELLETT a Vezérlés is marad (indítani/leállítani
            # összecsukva is lehessen) — a fejlécnek követnie kell, különben minden
            # további oszlop elcsúszik.
            keys.append(f"{name}|ctrl")
            continue
        keys += [f"{name}|position", f"{name}|daily", f"{name}|quality",
                 f"{name}|ctrl", f"{name}|opt"]
    keys += ["total_pos", "total_daily", "close"]
    return keys


def base_key(key: str) -> str:
    """`"wpr_sma|stages"` → `"stages"`. A szélesség-tábla ezzel van kulcsolva."""
    return key.split("|", 1)[1] if "|" in key else key


def layout(fonts: dict, strategies, collapsed: dict = None) -> list:
    """`[(kulcs, x, szélesség), …]` — a teljes oszlop-térkép.

    A szélességeket a MEGLÉVŐ `live_row.widths()` adja (ugyanazok a mintaszövegek,
    ugyanaz a betű-mérés), tehát a vászon-tábla oszlopai pixelre azonosak a
    widget-tábláéval. Ez szándékos: a renderelő cseréje NEM változtathat a
    látványon."""
    w = _lr.widths(fonts, strategies or (), collapsed)
    out, x = [], 0
    for k in column_keys(strategies, collapsed):
        wd = w.get(base_key(k), 60)
        out.append((k, x, wd))
        x += wd + GAP
    return out


def total_width(cols: list) -> int:
    """A tábla teljes szélessége (a görgetési tartományhoz)."""
    return (cols[-1][1] + cols[-1][2]) if cols else 0


def x_of(cols: list, key: str):
    """Egy oszlop `(x, szélesség)` párja, vagy `None`, ha nem látszik."""
    for k, x, wd in cols:
        if k == key:
            return x, wd
    return None

"""
A 2.0 sor ADATA az élő állapotból — tiszta leképezés.

A `dashboard/live_row.py` szándékosan csak megjelenít: egy sima dictet kap. Ez a
modul állítja elő azt a dictet a motor pillanatképeiből. Külön modul, mert így

  • a leképezés MT5 és tkinter nélkül tesztelhető (minden forrás beadható),
  • a megjelenítés és az adat-összeszedés nem keveredik — a `classic` úton az
    ilyen keveredés miatt lett a Minőség-oszlop néma „—" egy hiányzó import
    miatt (a `except Exception` elnyelte a `NameError`-t).

MINDEN KÜLSŐ FORRÁS BEADHATÓ (`owner_of`, `risk_of`, `quality_of`, …). Nincs
benne rejtett globális állapot, tehát a teszt pontosan azt méri, amit a
felület mutatni fog.

────────────────────────────────────────────────────────────────────────────
A `K.Össz.` JELENTÉSE — egy döntés, amit itt kell rögzíteni

A kapuk hatása stratégiánként állítható, a `K.Össz.` viszont INSTRUMENTUM-szintű
cella. Mit számoljon?

    „Hány kapu áll BLOKKOLÓ ÁLLAPOTBAN" — a MÉRÉS, stratégiától függetlenül.

Nem azt, hogy „hány kapu blokkol engem", mert az stratégiánként más, és egyetlen
cellába nem fér bele. Ez egybevág a terv logikájával: a kapu-oszlopok a PIACI
TÉNYT mondják („mi a helyzet"), a stratégia jelzés-cellájának KERETE pedig az
engedélyt („engem ez blokkol-e"). A kettő szándékosan más kérdésre válaszol.
────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from core import gates as _g


def _spread_cell(ctx: dict) -> dict:
    """`250/1312` — az aktuális és a megengedett spread PONTBAN.

    Konkrét szám, nem betűkód: az 1. kör tanulsága szerint az `S`/`E`/`E2` típusú
    jelölést senki nem tudja fejben tartani, a két szám viszont önmagát magyarázza."""
    cur, cap = ctx.get("spread_points"), ctx.get("max_spread_points")
    if cur is None:
        return {"text": "—", "blocking": False}
    if not cap:
        return {"text": f"{cur:.0f}/—", "blocking": False}
    return {"text": f"{cur:.0f}/{cap:.0f}", "blocking": cur > cap}


def _stages(ds, name: str, order=None) -> list:
    """A stratégia stádium-pöttyeinek SZÍNNEVEI, a stádiumok sorrendjében.

    A motor a `ds.strategy_cells[név]`-be írja (`{stádium: (glifa, szín-név)}`) —
    ugyanaz a forrás, amiből a `classic` tábla körei jönnek, tehát a két nézet
    nem mondhat mást. `order`: a stádiumok kanonikus sorrendje (a stratégia
    `columns()`-ából); enélkül a dict beszúrási sorrendje dönt."""
    cells = (getattr(ds, "strategy_cells", None) or {}).get(name) or {}
    keys = list(order) if order else list(cells)
    return [(cells.get(k) or ("", "muted"))[1] for k in keys]


def _open_position(positions, symbol: str, name: str, owner_of=None,
                   risk_of=None) -> dict:
    """A stratégia NYITOTT pozíciója ezen a páron: élő P&L + R.

    Per-ticket adatból dolgozik (`open_positions_detailed`), nem a szimbólumra
    aggregáltból: az utóbbiban NINCS stratégia, és az 1. körben pont ezért maradt
    a „Nyitott" oszlop némán üres.

    Az R a belépéskori kockázatokra vetítve: `Σ P&L / Σ kockázat`. Ha egyetlen
    pozícióhoz sincs rögzített kockázat, az R None (nem 0 — az azt állítaná, hogy
    nullán áll)."""
    pnl, risk, n = 0.0, 0.0, 0
    for p in positions or []:
        if not isinstance(p, dict) or p.get("symbol") != symbol:
            continue
        owner = p.get("strategy")
        if owner is None and owner_of is not None:
            try:
                owner = owner_of(p.get("ticket"), p.get("magic"))
            except Exception:
                owner = None
        if owner != name:
            continue
        n += 1
        pnl += float(p.get("profit") or 0.0)
        if risk_of is not None:
            try:
                r = risk_of(p.get("ticket"))
            except Exception:
                r = None
            if r:
                risk += float(r)
    if not n:
        return {"money": None, "r": None, "count": 0}
    return {"money": pnl, "r": (pnl / risk if risk else None), "count": n}


def _daily(ds, name: str) -> dict:
    """A mai LEZÁRT P&L erre a stratégiára (`core/pnl_split.py` bontásából)."""
    b = (getattr(ds, "daily_by_strategy", None) or {}).get(name)
    if not b:
        return {"money": None, "r": None}
    return {"money": b.get("pnl", 0.0),
            "r": (b.get("r") if b.get("r_count") else None)}


def _sum_money_r(parts) -> dict:
    """Az instrumentum-szintű összesítő: a blokkok összege.

    Az R-eket NEM adjuk össze vakon — csak azokat, amelyek léteznek; ha egyik
    blokkban sincs R, az összesítőben sem lesz."""
    money = [p.get("money") for p in parts if p.get("money") is not None]
    rs = [p.get("r") for p in parts if p.get("r") is not None]
    return {"money": (sum(money) if money else None),
            "r": (sum(rs) if rs else None)}


def row_data(symbol: str, ds, strategy_names, cfg: dict = None,
             params: dict = None, pair_cfg: dict = None, *,
             positions=None, owner_of=None, risk_of=None, quality_of=None,
             opt_of=None, live_of=None, stage_order_of=None,
             on_toggle=None, on_opt=None) -> dict:
    """Egy instrumentum sorának adata a `live_row.LiveRow` számára.

    `ds`          — `live_trader.PairDashboardState` (duck-typed).
    `params`      — a pár futásidejű paraméterei (a spread-küszöbhöz).
    `quality_of(symbol, strategy) -> (szöveg, szín) | None`
    `opt_of(symbol, strategy) -> str`      — dátum vagy folyamat-%
    `live_of(symbol, strategy) -> bool`    — fut-e a stratégia
    """
    ctx = _g.ctx_from_state(ds, params or {}, pair_cfg or {})

    # A K.Össz.-hez a MÉRÉST nézzük: minden kaput blokkolónak véve megkapjuk,
    # hány kapu áll blokkoló állapotban (lásd a modul fejlécét).
    measure_effects = {k: _g.EFFECT_BLOCK for k in _g.KEYS}
    badge = _g.badge(_g.evaluate(ctx, measure_effects))

    strategies = []
    for name in strategy_names or []:
        states = _g.evaluate(ctx, _g.effects_for(cfg or {}, symbol, name))
        q = quality_of(symbol, name) if quality_of else None
        strategies.append({
            "name": name,
            "stages": _stages(ds, name,
                              stage_order_of(name) if stage_order_of else None),
            "frame": _g.frame_state(states),
            "position": _open_position(positions, symbol, name, owner_of, risk_of),
            "daily": _daily(ds, name),
            "quality": (q[0] if q else None),
            "live": bool(live_of(symbol, name)) if live_of else False,
            "opt": (opt_of(symbol, name) if opt_of else None),
            "on_toggle": (lambda n=name: on_toggle(symbol, n)) if on_toggle else None,
            "on_opt": (lambda n=name: on_opt(symbol, n)) if on_opt else None,
        })

    return {
        "symbol": symbol,
        "bid": getattr(ds, "bid", None),
        "ask": getattr(ds, "ask", None),
        "change_pct": getattr(ds, "change_pct", None),
        "digits": getattr(ds, "digits", 5),
        "gates": {
            "spread": _spread_cell(ctx),
            "align": {"signs": ctx.get("tf_align_signs") or []},
            "market": {"text": getattr(ds, "market_state_label", "") or "—"},
            "badge": badge,
        },
        "strategies": strategies,
        "total": {
            "position": _sum_money_r([s["position"] for s in strategies]),
            "daily": _sum_money_r([s["daily"] for s in strategies]),
        },
    }


def build_rows(symbols, ds_map, strategies_of, **kw) -> list:
    """Több sor egyszerre. `strategies_of(symbol) -> [név, …]`.

    A stratégia-LISTÁNAK minden sorban azonosnak kell lennie, különben a tábla
    oszlopai nem állnának egy vonalban — a hívó felelőssége, hogy így töltse."""
    out = []
    for sym in symbols or []:
        ds = (ds_map or {}).get(sym)
        if ds is None:
            continue
        out.append(row_data(sym, ds, strategies_of(sym), **kw))
    return out

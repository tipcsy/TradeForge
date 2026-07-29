"""
A (instrumentum × stratégia) sorok ADATA — egy helyen, tkinter nélkül.

A lapos/csoportosított elrendezés soronként a következőket kéri: kapu-állapotok,
kereskedési mód, minőség, NYITOTT pozíció élő eredménye, napi (lezárt) P&L, és
hogy él-e a stratégia. Ezek négy különböző forrásból jönnek (`core.gates`,
`core.trade_mode`, `core.run_state`, a mentett paraméterfájl, MT5-pozíciók), és
ha a GUI-ban gyűjtjük össze, akkor a logika tesztelhetetlenné válik.

Ezért itt van, tiszta függvényekkel: a hívó átadja a MÁR MEGLÉVŐ pillanatképeket
(dashboard-állapot, pozíció-összesítő), és kap egy sor-leírót.

**A `classic` úton ez a modul NEM fut** — ott a sor az instrumentumhoz tartozik,
és a per-stratégia gyűjtés kidobott munka lenne (lásd `layout_mode.is_per_strategy_row`).
"""

from __future__ import annotations

from core import gates as _g


def gate_ctx(ds, params: dict, pair_cfg: dict, strategy_name: str,
             tf_gate: list) -> dict:
    """A `core.gates.evaluate()` bemenete EGY (pár × stratégia) sorra.

    A spread-korlát a STRATÉGIA paramétereiből jön (`core.spread_gate`), ezért
    per stratégia más lehet ugyanazon a páron — a felület eddig egyetlen,
    instrumentum-szintű Spread-cellát mutatott, ami félrevezetett.

    A TF-kapu `gate` listája szó szerint stratégia-neveket sorol, tehát abból
    közvetlenül eldönthető, hogy erre a stratégiára hat-e."""
    point_size = float((pair_cfg or {}).get("point_size") or 0.0) or None
    atr = getattr(ds, "atr_price", None)
    cap = 0.0
    try:
        from core import spread_gate as _sg
        if point_size:
            cap = _sg.max_spread_points(atr, point_size, params or {},
                                        normal_spread_points=None)
    except Exception:
        cap = 0.0
    return {
        "spread_points": getattr(ds, "spread_pts", None),
        "max_spread_points": cap,
        "tf_align_gated": strategy_name in (tf_gate or []),
        "tf_align_signs": list(getattr(ds, "tf_align_signs", []) or []),
        "tf_align_labels": list(getattr(ds, "tf_align_labels", []) or []),
        "tf_align_dir": getattr(ds, "tf_align_dir", None),
        "market_name": getattr(ds, "market_strategy", None),
        "market_label": getattr(ds, "market_state_label", "") or "",
    }


def split_open(positions_detail, symbol: str, strategy_name: str,
               owner_of=None) -> tuple:
    """A NYITOTT pozíciók (élő P&L, darabszám) EGY (pár × stratégia) sorra.

    `positions_detail`: a `core.mt5_connector.open_positions_detailed()` LISTÁJA —
    per ticket, `{"ticket", "symbol", "profit", "magic", …}`.

    **Miért a részletes lista és nem az összesítő.** A GUI másik gyorsítótára
    (`open_positions_by_symbol()`) SZIMBÓLUMRA aggregál, tehát nincs benne
    stratégia. Az első változatom azt kapta, és ezért MINDIG (0, 0)-t adott: a
    „Nyitott" oszlop némán üres maradt, holott futottak pozíciók. Per-stratégia
    sorhoz per-ticket adat kell.

    `owner_of`: `fn(ticket, magic) -> stratégia-név` — a motor igazságforrása
    (magic + örökbefogadás). Enélkül a magic-alapú hozzárendelés hiányzik, és a
    kézzel nyitott, hozzárendelt pozíciók kimaradnának.

    Miért kell egyáltalán: a felhasználó észrevétele szerint eddig „csak az
    összesítést láttuk, amikor már lezárult egy kötés" — a futó pozícióról a
    tábla hallgatott."""
    pnl, n = 0.0, 0
    for p in (positions_detail or []):
        if not isinstance(p, dict) or p.get("symbol") != symbol:
            continue
        owner = p.get("strategy")
        if owner is None and owner_of is not None:
            try:
                owner = owner_of(p.get("ticket"), p.get("magic"))
            except Exception:
                owner = None
        if owner != strategy_name:
            continue
        pnl += float(p.get("profit", p.get("pnl", 0.0)) or 0.0)
        n += 1
    return round(pnl, 2), n


def row_items(*, symbols: list, cfg: dict, dashboard_ref: dict,
              strategies_of, params_of, quality_of, mode_of, live_of,
              tf_gate_of, open_of, daily_of, opt_status_of,
              trained_of=None) -> list:
    """A tábla sor-leíróinak listája — RENDEZÉS ELŐTT.

    Minden bemenet függvény, hogy a modul ne kötődjön se confighoz, se MT5-hez,
    és a teszt behelyettesíthesse őket. A visszaadott szótárak kulcsai pontosan
    azok, amiket a `flat_rows.order()` és a `FlatRow.update()` vár."""
    from dashboard.flat_rows import row_state
    out = []
    for sym in symbols:
        ds = (dashboard_ref or {}).get(sym)
        pair_cfg = ((cfg or {}).get("pairs") or {}).get(sym) or {}
        tf_gate = tf_gate_of(sym)
        for idx, sname in enumerate(strategies_of(sym)):
            states = _g.evaluate(gate_ctx(ds, params_of(sym, sname), pair_cfg,
                                          sname, tf_gate))
            live = bool(live_of(sym, sname))
            mode = mode_of(sym, sname)
            opnl, oncnt = open_of(sym, sname)
            out.append({
                "symbol": sym, "strategy": sname, "strategy_order": idx,
                "ds": ds, "states": states, "mode": mode,
                "quality": quality_of(sym, sname),
                "open_pnl": opnl, "open_n": oncnt,
                "daily": float(daily_of(sym, sname) or 0.0),
                "opt_status": opt_status_of(sym, sname) or "",
                "trained": True if trained_of is None else bool(trained_of(sym, sname)),
                "live": live,
                "state": row_state(has_position=bool(oncnt),
                                   blocked=_g.is_blocked(states),
                                   signal_only=(mode != "KÖT"), live=live),
            })
    return out

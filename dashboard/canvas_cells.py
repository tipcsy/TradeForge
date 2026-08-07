"""
Egy sor cellái ADATKÉNT — rajzolás nélkül, tkinter nélkül.

MIÉRT KÜLÖN. A vászon-tábla kétféleképpen nyúl egy cellához: FELÉPÍTÉSKOR rajzol,
FRISSÍTÉSKOR viszont csak akkor ír, ha a tartalom ténylegesen változott
(`itemconfigure` a tárolt elem-azonosítón — pontosan az a trükk, amivel a mai
widget-tábla `_set`-je elkerüli a villogást). Ha a „mit kell kiírni" logika a
rajzolásba lenne szőve, a két útnak külön-külön kellene ugyanazt kiszámolnia, és
szét tudnának csúszni.

Ezért ez a modul EGY dolgot csinál: a sor-dictből előállítja, hogy oszloponként
mi a SZÖVEG, a SZÍN és az IGAZÍTÁS. A formázók (`_money_r`, `_run_text`,
`_stage_color`, …) a MEGLÉVŐ `live_row`-ból jönnek — nem másoljuk őket, tehát a
két renderelő garantáltan ugyanazt írja ki.

A cella-fajták (`kind`) a rajzolónak szólnak:
    "text"   egyszerű szöveg
    "dots"   pöttyök sora (idősík-irányok / stádiumok), esetleg KERETTEL
    "ctrl"   két kattintható vezérlő egy cellában (Play/Stop + OPT)
"""

from __future__ import annotations

from dashboard import live_row as _lr
from dashboard.theme import (FG_WHITE, FG_GREEN, FG_RED, FG_GRAY, FG_GRAY_DIM)


class Cell:
    """Egy megrajzolandó cella. `key` az oszlop kulcsa (`"wpr_sma|opt"` alakban is)."""

    __slots__ = ("key", "kind", "text", "fg", "anchor", "font", "on_click",
                 "dots", "frame", "parts")

    def __init__(self, key, kind="text", text="", fg=FG_WHITE, anchor="w",
                 font="mono", on_click=None, dots=None, frame="", parts=None):
        self.key = key
        self.kind = kind
        self.text = text
        self.fg = fg
        self.anchor = anchor
        self.font = font
        self.on_click = on_click
        self.dots = list(dots or [])      # [(szín, ), …] — a pöttyök színei
        self.frame = frame                 # "" | "blocked" | "reduced"
        self.parts = list(parts or [])     # ctrl: [(alkulcs, szöveg, szín, cb, aktív)]

    def visual(self) -> tuple:
        """A cella LÁTHATÓ állapota — a frissítés ezt hasonlítja össze.
        Ha nem változott, egyetlen `itemconfigure` sem fut."""
        return (self.text, self.fg, tuple(self.dots), self.frame,
                tuple((p[0], p[1], p[2]) for p in self.parts))


def _pane_of(key: str) -> str:
    """Melyik rögzített sávba tartozik az oszlop: bal | közép | jobb.
    (A tábla fix–görgethető–fix elrendezésű, mint a mai widget-változat.)"""
    if key in ("symbol", "bid", "ask", "change"):
        return "left"
    if key in ("total_pos", "total_daily", "close"):
        return "right"
    return "mid"


PANE_OF = _pane_of


def cells_for(d: dict, collapsed: dict, on_close=None) -> dict:
    """`{oszlop_kulcs: Cell}` egy sorra. A `d` a `row_source.row_data` kimenete."""
    pnl = _lr.pnl_mode(collapsed)
    dg = d.get("digits", 2)
    g = d.get("gates") or {}
    out = {}

    # ── bal: instrumentum ────────────────────────────────────────────────
    out["symbol"] = Cell("symbol", text=d.get("symbol", "—"), font="mono_bold",
                         on_click=d.get("on_symbol"))
    out["bid"] = Cell("bid", text=_lr._fmt_price(d.get("bid"), dg), anchor="e")
    out["ask"] = Cell("ask", text=_lr._fmt_price(d.get("ask"), dg), anchor="e")
    ch = d.get("change_pct")
    out["change"] = Cell("change", anchor="e",
                         text=("—" if ch is None else f"{ch:+.2f}%"),
                         fg=(FG_GRAY if ch is None
                             else (FG_GREEN if ch >= 0 else FG_RED)))

    # ── közép: kapuk ─────────────────────────────────────────────────────
    if not (collapsed or {}).get("gates"):
        sp = g.get("spread") or {}
        out["spread"] = Cell("spread", text=sp.get("text", "—"), anchor="center",
                             fg=(FG_RED if sp.get("blocking") else FG_GREEN),
                             on_click=g.get("on_spread"))
        al = g.get("align") or {}
        out["align"] = Cell("align", kind="dots", on_click=al.get("on_click"),
                            dots=[_sign_color(s) for s in (al.get("signs") or [])])
        if _lr.show_market(collapsed):
            mk = g.get("market") or {}
            out["market"] = Cell("market", text=mk.get("text", "—"), fg=FG_GRAY,
                                 font="small", on_click=mk.get("on_click"))
        if _lr.show_momentum(collapsed):
            mo = g.get("momentum") or {}
            out["momentum"] = Cell("momentum", text=mo.get("text", "—"),
                                   anchor="center", on_click=mo.get("on_click"),
                                   fg=(FG_RED if mo.get("blocking") else FG_WHITE))
    badge = g.get("badge", "✓")
    out["badge"] = Cell("badge", text=badge, anchor="center",
                        fg=(FG_RED if badge != "✓" else FG_GREEN))

    # ── közép: stratégiánként ────────────────────────────────────────────
    for st in (d.get("strategies") or []):
        n = st.get("name", "")
        coll = _lr.is_collapsed(collapsed, n)
        out[f"{n}|stages"] = Cell(
            f"{n}|stages", kind="dots", on_click=st.get("on_stages"),
            frame=(st.get("frame") or ""),
            dots=[_lr._stage_color(s) for s in (st.get("stages") or [])])
        if not coll:
            pos, day = st.get("position") or {}, st.get("daily") or {}
            out[f"{n}|position"] = Cell(
                f"{n}|position", anchor="e",
                text=_lr._money_r(pos.get("money"), pos.get("r"), pnl))
            out[f"{n}|daily"] = Cell(
                f"{n}|daily", anchor="e",
                text=_lr._money_r(day.get("money"), day.get("r"), pnl),
                fg=_lr._pnl_color(day.get("money")))
            q = st.get("quality") or "—"
            out[f"{n}|quality"] = Cell(f"{n}|quality", text=q, anchor="center",
                                       font="small", fg=_lr._quality_color(q))
        run_txt, run_fg = _lr._run_text(st)
        opt_txt, opt_fg = _lr._opt_text(st)
        out[f"{n}|ctrl"] = Cell(f"{n}|ctrl", kind="ctrl", parts=[
            ("run", run_txt, run_fg, st.get("on_toggle"),
             bool(st.get("enabled", True))),
            ("opt", opt_txt, opt_fg, st.get("on_opt"),
             bool(st.get("opt_enabled", True) or st.get("opt_state"))),
        ])
        if not coll:
            out[f"{n}|opt"] = Cell(f"{n}|opt", text=st.get("opt") or "—",
                                   anchor="center", font="small", fg=FG_GRAY)

    # ── jobb: összesítő ──────────────────────────────────────────────────
    t = d.get("total") or {}
    tp, td = t.get("position") or {}, t.get("daily") or {}
    out["total_pos"] = Cell("total_pos", anchor="e", font="mono_bold",
                            text=_lr._money_r(tp.get("money"), tp.get("r"), pnl))
    out["total_daily"] = Cell("total_daily", anchor="e", font="mono_bold",
                              text=_lr._money_r(td.get("money"), td.get("r"), pnl),
                              fg=_lr._pnl_color(td.get("money")))
    out["close"] = Cell("close", text="✕", anchor="center", font="small",
                        fg=FG_GRAY_DIM, on_click=on_close)
    return out


def _sign_color(s):
    """Az idősík-irány pöttyének színe — ugyanaz a szabály, mint a widget-sorban."""
    return FG_GREEN if s > 0 else FG_RED if s < 0 else FG_GRAY_DIM

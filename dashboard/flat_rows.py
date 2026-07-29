"""
LAPOS dashboard-sorok: egy sor = egy (instrumentum × stratégia).

**Miért nem a szülő-gyerek fa.** Kipróbáltuk, és a felhasználó egy döntő érvvel
elvetette: csukott állapotban nem látszik, melyik stratégia hol tart, és nem
látszanak a NYITOTT pozíciók sem — csak a lezárt kötések összege. Vagyis mindig
mindent ki kellene nyitni, és akkor a fa csak **plusz 10 üres instrumentum-sort**
ad a 20 hasznos mellé. Ráadásul „keresni kell a sorokat".

Itt semmi nincs elrejtve: **minden kereskedni képes egység saját, állandóan
látható sora van.** A kérdés nem az, mit rejtsünk el, hanem hogyan legyen 20 sor
ÁTFUTHATÓ. Három eszköz, egyik sem hidegen hagyja a szemet:

1. **Csoport-sávozás.** Az instrumentum adatai (ár, változás, spread) CSAK a
   csoport első sorában látszanak; a folytatás-sorok üresen hagyják. A csoportok
   váltakozó háttérrel különülnek el — a szem a sávokat találja meg, nem olvasni
   kell.
2. **Fontosság szerinti sorrend.** Ami él, az FELÜL van: nyitott pozíció →
   blokkolt → aktív → csendes. Így nem kell keresni; ami számít, az odajön.
3. **Bal szélső állapot-csík.** Színes él a sor bal oldalán: nyitott pozíció,
   blokkolva, csak jelzés, áll. Egy pillantás, olvasás nélkül.

A nyitott pozíció ÉLŐ eredménye külön oszlop (`open`), a lezártak napi összege
(`daily`) mellett — a felhasználó észrevétele szerint eddig „csak az összesítést
láttuk, amikor már lezárult egy kötés".
"""

from __future__ import annotations

import tkinter as tk

from core import gates as _g
from dashboard import grouped_layout as _gl
from dashboard import theme as _theme
from dashboard.theme import (BG_HEADER, BG_INACTIVE, BG_OPT_ROW, BG_ROW_EVEN,
                             BG_ROW_ODD, BG_UNTRAINED, BTN_DIS_BG, BTN_DIS_FG,
                             BTN_OPT_BG, BTN_OPT_FG, BTN_PLAY_BG, BTN_PLAY_FG,
                             BTN_STOP_BG, BTN_STOP_FG, FG_CYAN, FG_GRAY,
                             FG_GRAY_DIM, FG_GREEN, FG_ORANGE, FG_RED, FG_WHITE,
                             FG_YELLOW)
from dashboard.theme import color as sem_color
from strategy.base import Column

# ── Az oszlopok EGY sorban: instrumentum-rész + stratégia-rész ───────────
# Az instrumentum-rész csak a csoport ELSŐ sorában van kitöltve.
COLUMNS = [
    Column("symbol",   "Symbol",    10, "w",      kind="fixed"),
    Column("bid",      "BID",        9, "center", kind="fixed"),
    Column("ask",      "ASK",        9, "center", kind="fixed"),
    Column("change",   "Vált.%",     7, "center", kind="fixed"),
    Column("spread",   "Spread",     7, "center", kind="fixed"),
    Column("strategy", "Stratégia", 10, "w",      kind="fixed"),
    Column("mode",     "Mód",        6, "center", kind="fixed"),
    Column("gates",    "Kapuk",      9, "center", kind="fixed"),
    Column("quality",  "Minőség",    8, "center", kind="fixed"),
    Column("open",     "Nyitott",   11, "center", kind="fixed"),
    Column("daily",    "Napi P&L",   9, "center", kind="fixed"),
]
INSTRUMENT_KEYS = ("symbol", "bid", "ask", "change", "spread")

# ── Bal szélső állapot-csík ──────────────────────────────────────────────
# A szín MAGA az információ: nem kell hozzá se betű, se szám.
EDGE = {
    "position": FG_CYAN,     # nyitott pozíció fut — ez a legfontosabb
    "blocked":  FG_RED,      # kapu blokkol
    "signal":   FG_YELLOW,   # csak jelzés módban van
    "live":     FG_GREEN,    # kereskedhet, nincs akadály
    "idle":     FG_GRAY_DIM, # áll
}

# Rendezési SÚLY: ami él, az felül. A felhasználó panasza szó szerint „keresni
# kell a sorokat" — a válasz nem a rejtés, hanem hogy ami számít, az ODAJÖN.
SORT_WEIGHT = {"position": 0, "blocked": 1, "signal": 2, "live": 3, "idle": 4}


def row_state(*, has_position: bool, blocked: bool, signal_only: bool,
              live: bool) -> str:
    """A sor állapot-kulcsa (a csíkhoz és a rendezéshez).

    A sorrend SZÁNDÉKOS: a nyitott pozíció mindent megelőz — az van kockán. Utána
    a blokkolt (ott MOST nem történik, ami történhetne), majd a jelzés-mód, majd
    az egészséges élő, végül az álló."""
    if has_position:
        return "position"
    if not live:
        return "idle"
    if blocked:
        return "blocked"
    if signal_only:
        return "signal"
    return "live"


def sort_key(item: dict) -> tuple:
    """Rendezés: állapot-súly, majd az instrumentum neve (a csoportok együtt
    maradjanak), majd a stratégia. A csoport-EGYSÉG a kulcs: a rendezés az
    INSTRUMENTUM legjobb (legkisebb súlyú) sora szerint viszi az egész csoportot,
    különben egy pár sorai szétszóródnának a táblában."""
    return (item["group_weight"], item["symbol"], item["strategy"])


def order(items: list) -> list:
    """A sorok végleges sorrendje.

    CSOPORTOK között: a csoport LEGFONTOSABB sora dönt (a nyitott pozíciós pár
    felkerül a tetejére) — így nem kell keresni, ami számít, az odajön.

    CSOPORTON BELÜL: a stratégiák sorrendje **ÁLLANDÓ** (a `strategy_order`
    szerint, alapból ábécé). Ez nem részletkérdés: az első változat itt is
    fontosság szerint rendezett, amitől az egyik páron a `wpr_sma`, a másikon az
    `ml_ai` lett az első sor — és pontosan ez az, amitől „keresni kell a sorokat".
    Ha a stratégia mindig ugyanott van a csoportjában, a szem megtanulja."""
    best: dict = {}
    for it in items:
        w = SORT_WEIGHT.get(it["state"], 9)
        best[it["symbol"]] = min(best.get(it["symbol"], 9), w)
    for it in items:
        it["group_weight"] = best[it["symbol"]]
        it["own_weight"] = SORT_WEIGHT.get(it["state"], 9)
    return sorted(items, key=lambda it: (it["group_weight"], it["symbol"],
                                         it.get("strategy_order", 0),
                                         it["strategy"]))


class FlatRow:
    """Egy (instrumentum × stratégia) sor — semmi nincs elrejtve."""

    def __init__(self, parent, symbol, strategy, group_idx, mono_font, small_font,
                 on_gates=None, on_params=None, on_opt=None, on_name=None,
                 on_run=None):
        self.symbol = symbol
        self.strategy = strategy
        self._mono = mono_font
        self._on_gates = None
        # A SÁVOZÁS CSOPORTONKÉNT vált, nem soronként: így a szem az
        # instrumentum-blokkokat látja, és nem kell a neveket olvasni ahhoz,
        # hogy tudja, hol kezdődik a következő pár.
        self._bg = BG_ROW_ODD if group_idx % 2 == 0 else BG_ROW_EVEN
        self.frame = tk.Frame(parent, bg=self._bg)
        self.labels: dict = {}

        # Bal szélső állapot-csík (2 px): a szín maga az információ.
        self.edge = tk.Frame(self.frame, bg=self._bg, width=5)
        self.edge.pack(side="left", fill="y")

        for col in COLUMNS:
            if col.key == "gates":
                cell = tk.Frame(self.frame, bg=self._bg,
                                width=_gl.gates_cell_px(mono_font, len(_g.REGISTRY)),
                                height=mono_font.metrics("linespace") + 6)
                cell.pack(side="left")
                cell.pack_propagate(False)
                self._gate_cell = cell
                self._gate_segs: list = []
                self._gate_badge = tk.Label(cell, text="", bg=self._bg, fg=FG_GRAY,
                                            font=mono_font, padx=2)
                self._gate_badge.pack(side="right")
                self.labels[col.key] = cell
                continue
            lbl = tk.Label(self.frame, text="", width=col.width, anchor=col.anchor,
                           bg=self._bg, fg=FG_GRAY, font=mono_font, padx=4, pady=2)
            lbl.pack(side="left")
            self.labels[col.key] = lbl

        if on_gates:
            self._on_gates = on_gates
            for _w in (self._gate_cell, self._gate_badge):
                _w.config(cursor="hand2")
                _w.bind("<Button-1>", lambda e: on_gates(symbol, strategy, None))
        if on_params:
            self.labels["strategy"].config(cursor="hand2")
            self.labels["strategy"].bind("<Button-1>",
                                         lambda e: on_params(symbol, strategy))
        if on_name:
            self.labels["symbol"].config(cursor="hand2")
            self.labels["symbol"].bind("<Button-1>", lambda e: on_name(symbol))

        # Play/Stop PER STRATEGIA: a `core.run_state` szandeka mar igy is
        # (symbol, strategy) kulcsu, tehat itt a helyes granularitas. Igy egy
        # paron elinditható az egyik strategia a masik nelkul — a klasszikus
        # tablan ez nem volt kifejezheto.
        self.btn_run = tk.Button(self.frame, text="▶", width=3, bg=BTN_DIS_BG,
                                 fg=BTN_DIS_FG, font=small_font, relief="flat",
                                 bd=0, highlightthickness=0, padx=0, pady=0,
                                 command=(lambda: on_run(symbol, strategy))
                                 if on_run else None)
        self.btn_run.pack(side="left", padx=(4, 1), pady=1)
        self.btn_opt = tk.Button(self.frame, text="OPT", width=9, bg=BTN_DIS_BG,
                                 fg=BTN_DIS_FG, font=small_font, relief="flat",
                                 bd=0, highlightthickness=0, padx=0, pady=0,
                                 command=(lambda: on_opt(symbol, strategy))
                                 if on_opt else None)
        self.btn_opt.pack(side="left", padx=4, pady=1)

    # ── Frissítés ────────────────────────────────────────────────────────
    def update(self, *, ds, first_of_group: bool, state: str, mode_label: str,
               states: list, quality: tuple, open_pnl, open_count: int,
               daily: float, opt_status: str, trained: bool = True,
               connected: bool = True):
        bg = self._bg if trained else BG_UNTRAINED
        self.frame.config(bg=bg)
        self.edge.config(bg=EDGE.get(state, FG_GRAY_DIM))
        for key, lbl in self.labels.items():
            lbl.config(bg=bg)
        self._gate_badge.config(bg=bg)
        for s in self._gate_segs:
            s.config(bg=bg)

        _f = _theme.fonts()
        blocked = (state == "blocked")
        dim = FG_GRAY_DIM if blocked or state == "idle" else None

        # ── Instrumentum-rész: CSAK a csoport első sorában ────────────────
        # A folytatás-soroknál üres, hogy az ár ne ismétlődjön 2-3-szor. Így a
        # csoport egyetlen "blokként" olvasható.
        if first_of_group:
            self.labels["symbol"].config(
                text=self.symbol,
                fg=FG_GRAY_DIM if not connected else FG_WHITE,
                font=_f["mono_bold"])
            d = getattr(ds, "digits", 5)
            for key, val in (("bid", getattr(ds, "bid", None)),
                             ("ask", getattr(ds, "ask", None))):
                self.labels[key].config(text=f"{val:.{d}f}" if val else "—",
                                        fg=FG_GRAY)
            ch = getattr(ds, "change_pct", None)
            self.labels["change"].config(
                text=f"{ch:+.2f}%" if ch is not None else "—",
                fg=(FG_GREEN if (ch or 0) > 0 else
                    FG_RED if (ch or 0) < 0 else FG_GRAY))
            sp = getattr(ds, "spread_pts", 0)
            self.labels["spread"].config(text=f"{sp:.0f}" if sp else "—", fg=FG_GRAY)
        else:
            for key in INSTRUMENT_KEYS:
                self.labels[key].config(text="")

        # ── Stratégia-rész: MINDEN sorban ────────────────────────────────
        self.labels["strategy"].config(
            text=self.strategy, fg=dim or FG_WHITE,
            font=_f["mono_bold"] if state in ("position", "live") else _f["mono"])
        self.labels["mode"].config(
            text=mode_label,
            fg=dim or (FG_GREEN if mode_label == "KÖT" else FG_YELLOW))
        self._render_gates(states, bg)
        qtxt, qcol = (quality or ("—", "muted"))
        self.labels["quality"].config(text=qtxt, fg=dim or sem_color(qcol))

        # NYITOTT pozíció: darabszám + ÉLŐ eredmény. Ez volt a hiányzó darab —
        # eddig csak a LEZÁRT kötések napi összege látszott, tehát amíg futott
        # egy pozíció, a tábla hallgatott róla.
        if open_count:
            _p = float(open_pnl or 0.0)
            self.labels["open"].config(
                text=f"{_p:+.2f} ({open_count})",
                fg=FG_GREEN if _p > 0 else FG_RED if _p < 0 else FG_CYAN,
                font=_f["mono_bold"])
        else:
            self.labels["open"].config(text="—", fg=FG_GRAY_DIM, font=_f["mono"])

        self.labels["daily"].config(
            text=f"{daily:+.2f}" if daily else "—",
            fg=dim or (FG_GREEN if daily > 0 else
                       FG_RED if daily < 0 else FG_GRAY))

        # Play/Stop morph: ELO -> Stop (■), egyebkent Play (▶). A tanitatlan
        # strategiat nem indítjuk (a klasszikus tabla is így viselkedett).
        _running = state in ("position", "blocked", "signal", "live")
        self.btn_run.config(
            text="■" if _running else "▶",
            bg=BTN_STOP_BG if _running else (BTN_PLAY_BG if trained else BTN_DIS_BG),
            fg=BTN_STOP_FG if _running else (BTN_PLAY_FG if trained else BTN_DIS_FG),
            state="normal" if (_running or trained) else "disabled")

        busy = bool(opt_status)
        self.btn_opt.config(text=f"OPT {opt_status}" if busy else "OPT",
                            bg=BTN_STOP_BG if busy else BTN_OPT_BG,
                            fg=BTN_STOP_FG if busy else BTN_OPT_FG,
                            state="normal")

    _SEG_FG = {_g.PASS: FG_GREEN, _g.BLOCKING: FG_RED,
               _g.OFF: FG_GRAY_DIM, _g.UNKNOWN: FG_GRAY_DIM}

    def _new_seg(self, bg, gate_key=None):
        lbl = tk.Label(self._gate_cell, text="", bg=bg, font=self._mono, padx=0)
        lbl.pack(side="left")
        if self._on_gates:
            lbl.config(cursor="hand2")
            lbl.bind("<Button-1>",
                     lambda e, k=gate_key: self._on_gates(self.symbol,
                                                          self.strategy, k))
        return lbl

    def _render_gates(self, states, bg):
        states = states or []
        glyph = {_g.PASS: "▮", _g.BLOCKING: "▨"}
        if len(states) > _gl.GATE_SEGMENTS_MAX:
            parts = _g.compact(states)
            if len(self._gate_segs) != len(parts):
                for w in self._gate_segs:
                    w.destroy()
                self._gate_segs = [self._new_seg(bg) for _ in parts]
            for lbl, (txt, st) in zip(self._gate_segs, parts):
                lbl.config(text=txt + " ", fg=self._SEG_FG.get(st, FG_GRAY_DIM),
                           bg=bg)
            self._gate_badge.config(text="", bg=bg)
            return
        if len(self._gate_segs) != len(states):
            for w in self._gate_segs:
                w.destroy()
            self._gate_segs = [self._new_seg(bg, st.get("key")) for st in states]
        for lbl, st in zip(self._gate_segs, states):
            lbl.config(text=glyph.get(st.get("state"), "▯"),
                       fg=self._SEG_FG.get(st.get("state"), FG_GRAY_DIM), bg=bg)
        _blk = _g.is_blocked(states)
        self._gate_badge.config(text=_g.badge(states),
                                fg=FG_RED if _blk else FG_GREEN, bg=bg)

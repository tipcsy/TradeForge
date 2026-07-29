"""
Csoportosított dashboard-sorok: instrumentum-sor + stratégia-alsorok (tkinter).

Az elrendezés indoklása és az oszlop-szétválasztás a `grouped_layout` modulban
van; ez a fájl a tényleges widgetek.

    ▼ GOLD   4006,8 / 4007,2  +0,4%   ●○   +12,40 $   [▶][R][✕]
       └ wpr_sma  KÖT    ▮▮▮ ✓     jó      [OPT]      1 poz.  +14,60 $
       └ ml_ai    jelez  ▨▮▮ ⛔1    rossz   [OPT 40%]  —       −2,20 $

Két elv, amit a kód végig tart:

* **A sorban nincs betűkód.** A kapu-csík szegmensei betű nélkül mutatják az
  állapotot; a nevek a kapu-panelen (a cellára kattintva) élnek, teljes alakban.
  Így 10 kapunál sem lesz `E`/`E2`/`E3`.
* **Ha bármi blokkol, a stratégia-sor HALVÁNYODIK.** A „miért nem köt?"
  kérdésre így nem kell se betűt, se számot olvasni.
"""

from __future__ import annotations

import tkinter as tk

from core import gates as _g
from dashboard import theme as _theme
from dashboard import grouped_layout as _gl
from dashboard.grouped_layout import (INSTRUMENT_COLUMNS, STRATEGY_COLUMNS,
                                      ready_badge)
from dashboard.theme import (BG_HEADER, BG_INACTIVE, BG_OPT_ROW, BG_ROW_EVEN, BG_ROW_ODD,
                             BG_UNTRAINED, BTN_DIS_BG, BTN_DIS_FG, BTN_OPT_BG,
                             BTN_OPT_FG, BTN_PLAY_BG, BTN_PLAY_FG, BTN_STOP_BG,
                             BTN_STOP_FG, FG_GRAY, FG_GRAY_DIM, FG_GREEN,
                             FG_ON_ACCENT, FG_ORANGE, FG_RED, FG_WHITE,
                             FG_YELLOW)
from dashboard.theme import color as sem_color

# A blokkolt stratégia-sor betűszíne. Nem külön háttér: a halványítás így a
# téma bármelyik változatában működik, és nem versenyez a sávozással.
FG_BLOCKED = FG_GRAY_DIM


class InstrumentRow:
    """Az instrumentum (szülő) sora: nyitó jel + a stratégiától FÜGGETLEN adatok
    + a pár-szintű vezérlés."""

    def __init__(self, parent, symbol, row_idx, mono_font, small_font,
                 on_toggle=None, on_run=None, on_delete=None, on_name_click=None):
        self.symbol = symbol
        self._bg = BG_ROW_ODD if row_idx % 2 == 0 else BG_ROW_EVEN
        self._mono = mono_font
        self.frame = tk.Frame(parent, bg=self._bg)
        self.labels: dict = {}

        # Nyitó/csukó jel. Külön Label (nem Button): a sor tetszőleges pontján
        # kattintva is nyíljon — a kis háromszögre célozni bosszantó lenne.
        self.exp = tk.Label(self.frame, text="▶", width=2, bg=self._bg,
                            fg=FG_GRAY, font=mono_font, cursor="hand2")
        self.exp.pack(side="left")
        if on_toggle:
            self.exp.bind("<Button-1>", lambda e: on_toggle(symbol))

        for col in INSTRUMENT_COLUMNS:
            if col.key == "ready":
                # STRATEGIANKENT egy pont, SAJAT szinnel. Egyetlen szoveg-cimke
                # csak annyit tudna mondani, hogy "kettobol egy kesz" — azt nem,
                # hogy MELYIK. Csukott allapotban pont ez a lenyeg: ne kelljen
                # kinyitni ahhoz, hogy lasd, melyik strategia akadt meg.
                # (A betukod-erv itt NEM all: strategiabol 2-3 van, te valasztottad
                # oket, a pozicio megjegyezheto — a kapuknal 10 is lehet.)
                cell = tk.Frame(self.frame, bg=self._bg,
                                width=mono_font.measure("●") * 4 + 8,
                                height=mono_font.metrics("linespace") + 6)
                cell.pack(side="left")
                cell.pack_propagate(False)
                self._ready_cell = cell
                self._ready_dots: list = []
                self.labels[col.key] = cell
                continue
            lbl = tk.Label(self.frame, text="—", width=col.width, anchor=col.anchor,
                           bg=self._bg, fg=FG_GRAY, font=mono_font, padx=4, pady=3)
            lbl.pack(side="left")
            self.labels[col.key] = lbl
        if on_toggle:
            for _w in (self.frame, self.labels["bid"], self.labels["ask"],
                       self.labels["change"], self.labels["ready"]):
                _w.config(cursor="hand2")
                _w.bind("<Button-1>", lambda e: on_toggle(symbol))
        if on_name_click:
            self.labels["symbol"].config(cursor="hand2")
            self.labels["symbol"].bind("<Button-1>", lambda e: on_name_click(symbol))

        self.ctrl = tk.Frame(self.frame, bg=self._bg)
        self.ctrl.pack(side="left", padx=(8, 0))
        self.btn_run = tk.Button(self.ctrl, text="▶", width=3, bg=BTN_DIS_BG,
                                 fg=BTN_DIS_FG, font=small_font, relief="flat",
                                 command=(lambda: on_run(symbol)) if on_run else None)
        self.btn_run.pack(side="left", padx=1)
        self.btn_del = tk.Button(self.ctrl, text="✕", width=2, bg=BTN_DIS_BG,
                                 fg=BTN_DIS_FG, font=small_font, relief="flat",
                                 command=(lambda: on_delete(symbol)) if on_delete else None)
        self.btn_del.pack(side="left", padx=(1, 4))

    def update(self, ds, inst_state: str, expanded: bool, ready: tuple,
               connected: bool = True):
        bg = (BG_OPT_ROW if inst_state in ("OPTIMIZING", "QUEUED")
              else BG_INACTIVE if inst_state == "STOPPED" else self._bg)
        self.frame.config(bg=bg)
        self.ctrl.config(bg=bg)
        self.exp.config(bg=bg, text="▼" if expanded else "▶")
        for key, lbl in self.labels.items():
            lbl.config(bg=bg)
            if key == "ready":
                for d in getattr(self, "_ready_dots", []):
                    d.config(bg=bg)

        _f = _theme.fonts()
        if not connected:
            self.labels["symbol"].config(text=self.symbol, fg=FG_GRAY_DIM,
                                         font=_f["mono_italic"])
        elif inst_state == "CLOSING":
            self.labels["symbol"].config(text=f"⏹ {self.symbol}", fg=FG_ORANGE,
                                         font=_f["mono_bold"])
        elif inst_state == "LIVE":
            self.labels["symbol"].config(text=self.symbol, fg=FG_WHITE,
                                         font=_f["mono_bold"])
        else:
            self.labels["symbol"].config(text=self.symbol, fg=FG_GRAY, font=_f["mono"])

        d = getattr(ds, "digits", 5)
        for key, val in (("bid", getattr(ds, "bid", None)),
                         ("ask", getattr(ds, "ask", None))):
            self.labels[key].config(text=f"{val:.{d}f}" if val else "—", fg=FG_GRAY)
        ch = getattr(ds, "change_pct", None)
        self.labels["change"].config(
            text=f"{ch:+.2f}%" if ch is not None else "—",
            fg=(FG_GREEN if (ch or 0) > 0 else FG_RED if (ch or 0) < 0 else FG_GRAY))
        sp = getattr(ds, "spread_pts", 0)
        self.labels["spread"].config(text=f"{sp:.0f}" if sp else "—", fg=FG_GRAY)

        self._render_ready(ready, bg)
        # Az instrumentum ÖSSZESÍTETT napi eredménye; a per-stratégia bontás a
        # gyerek-sorokban van (a felhasználó mindkettőt kérte).
        dp = getattr(ds, "daily_pnl", 0.0) or 0.0
        self.labels["daily"].config(
            text=f"{dp:+.2f}" if dp else "—",
            fg=(FG_GREEN if dp > 0 else FG_RED if dp < 0 else FG_GRAY))

        _en = (inst_state == "LIVE")
        self.btn_run.config(text="■" if _en else "▶",
                            bg=BTN_STOP_BG if _en else BTN_PLAY_BG,
                            fg=BTN_STOP_FG if _en else BTN_PLAY_FG, state="normal")
        _delok = (inst_state == "STOPPED")
        self.btn_del.config(bg=BG_INACTIVE if _delok else BTN_DIS_BG,
                            fg=FG_RED if _delok else BTN_DIS_FG,
                            state="normal" if _delok else "disabled")

    def _render_ready(self, ready, bg):
        """A „Kész" cella: stratégiánként egy pont.

        `ready` lehet `(ok, total)` — visszafelé kompatibilis, ilyenkor nincs
        per-stratégia bontás —, VAGY `[(név, kész?), …]`, és akkor minden pont a
        SAJÁT stratégiája állapotát mutatja. A név tooltipben (a pont maga nem
        fér feliratozni), így nem kell fejből tudni a sorrendet."""
        if ready and isinstance(ready, (list, tuple)) and ready                 and isinstance(ready[0], (list, tuple)):
            items = list(ready)
        else:
            ok, total = (ready or (0, 0))
            items = [(None, i < ok) for i in range(total)]
        if len(self._ready_dots) != len(items):
            for d in self._ready_dots:
                d.destroy()
            self._ready_dots = []
            for _ in items:
                d = tk.Label(self._ready_cell, text="", bg=bg, font=self._mono, padx=0)
                d.pack(side="left")
                self._ready_dots.append(d)
        if not items:
            return
        for d, (name, ok_) in zip(self._ready_dots, items):
            d.config(text="●" if ok_ else "○",
                     fg=FG_GREEN if ok_ else FG_RED, bg=bg)
            if name:
                d.config(cursor="hand2")
                _tip = f"{name}: {'kereskedésre kész' if ok_ else 'blokkolva'}"
                d.bind("<Enter>", lambda e, t=_tip: self._tip_show(e, t))
                d.bind("<Leave>", self._tip_hide)

    _tip_win = None

    def _tip_show(self, event, text):
        self._tip_hide()
        try:
            w = tk.Toplevel(event.widget)
            w.wm_overrideredirect(True)
            w.wm_geometry(f"+{event.x_root + 12}+{event.y_root + 12}")
            tk.Label(w, text=text, bg=BG_HEADER, fg=FG_WHITE,
                     font=self._mono, padx=6, pady=2).pack()
            self._tip_win = w
        except Exception:
            self._tip_win = None

    def _tip_hide(self, _event=None):
        if self._tip_win is not None:
            try:
                self._tip_win.destroy()
            except Exception:
                pass
            self._tip_win = None


class StrategyRow:
    """Egy (instrumentum × stratégia) alsora — MINDEN, ami a stratégiához tartozik."""

    def __init__(self, parent, symbol, strategy, row_idx, mono_font, small_font,
                 indent_px, on_gates=None, on_params=None, on_opt=None):
        self.symbol = symbol
        self.strategy = strategy
        self._mono = mono_font
        self._on_gates = None
        self._bg = BG_ROW_ODD if row_idx % 2 == 0 else BG_ROW_EVEN
        self.frame = tk.Frame(parent, bg=self._bg)
        self.labels: dict = {}

        tk.Frame(self.frame, bg=self._bg, width=indent_px).pack(side="left")
        tk.Label(self.frame, text="└", bg=self._bg, fg=FG_GRAY_DIM,
                 font=mono_font).pack(side="left")

        for col in STRATEGY_COLUMNS:
            if col.key == "opt":
                continue                      # a gomb UTÁN jön, lásd lent
            if col.key == "gates":
                # A kapu-cella SZEGMENSENKENT kulon Label, hogy mindegyik SAJAT
                # szint kaphasson. Egyetlen szoveg-cimke csak egyszinu lehetne, es
                # akkor a blokkolo kaput csak a glifa kulonboztetne meg — a szin
                # az, amitol a sor ATFUTHATO lesz (nem kell olvasni, eleg ranezni).
                # MAGASSAG IS kell: `pack_propagate(False)` mellett a keret
                # kulonben osszeesik, es fuggolegesen LEVAGJA a glifakat (az
                # elonezeten vekony vonalkak latszottak teljes blokkok helyett).
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
            lbl = tk.Label(self.frame, text="—", width=col.width, anchor=col.anchor,
                           bg=self._bg, fg=FG_GRAY, font=mono_font, padx=4, pady=2)
            lbl.pack(side="left")
            self.labels[col.key] = lbl

        # A kapu-cella a BELÉPŐ a részletekhez: rákattintva nyílik a panel, ahol a
        # kapuk TELJES NEVE és a mért értékek (pl. „1721 / 1111 pont") látszanak.
        # Ezért nincs a sorban se betű, se szám a kapukról — csak állapot.
        if on_gates:
            for _w in (self._gate_cell, self._gate_badge):
                _w.config(cursor="hand2")
                _w.bind("<Button-1>", lambda e: on_gates(symbol, strategy, None))
            self._on_gates = on_gates
        if on_params:
            self.labels["strategy"].config(cursor="hand2")
            self.labels["strategy"].bind(
                "<Button-1>", lambda e: on_params(symbol, strategy))

        # A gomb ne legyen MAGASABB a cellaknal: sajat keret/parnazas nelkul,
        # kulonben a strategia-sor magasabb lesz az instrumentum-sornal, es a
        # tabla "ugral". (Az elonezeten pontosan ez latszott.)
        self.btn_opt = tk.Button(self.frame, text="OPT", width=9, bg=BTN_DIS_BG,
                                 fg=BTN_DIS_FG, font=small_font, relief="flat",
                                 bd=0, highlightthickness=0, padx=0, pady=0,
                                 command=(lambda: on_opt(symbol, strategy))
                                 if on_opt else None)
        self.btn_opt.pack(side="left", padx=4, pady=1)

    def update(self, *, mode_label: str, states: list, quality: tuple,
               pos_text: str, daily: float, opt_status: str, live: bool,
               trained: bool = True):
        blocked = _g.is_blocked(states)
        # HALVÁNYÍTÁS, ha bármi blokkol: a „miért nem köt?" kérdésre ne kelljen
        # se betűt, se számot olvasni — elég ránézni.
        base = FG_BLOCKED if blocked else None
        bg = self._bg if trained else BG_UNTRAINED
        self.frame.config(bg=bg)
        for key, lbl in self.labels.items():
            lbl.config(bg=bg)
            if key == "gates":
                self._gate_badge.config(bg=bg)
                for seg in self._gate_segs:
                    seg.config(bg=bg)

        _f = _theme.fonts()
        self.labels["strategy"].config(
            text=self.strategy, fg=base or (FG_WHITE if live else FG_GRAY),
            font=_f["mono_bold"] if live and not blocked else _f["mono"])
        self.labels["mode"].config(
            text=mode_label,
            fg=base or (FG_GREEN if mode_label == "KÖT" else FG_YELLOW))

        self._render_gates(states, bg)

        qtxt, qcol = (quality or ("—", "muted"))
        self.labels["quality"].config(text=qtxt, fg=base or sem_color(qcol))
        self.labels["position"].config(text=pos_text or "—",
                                       fg=base or FG_GRAY)
        self.labels["daily"].config(
            text=f"{daily:+.2f}" if daily else "—",
            fg=base or (FG_GREEN if daily > 0 else FG_RED if daily < 0 else FG_GRAY))

        # Az Opt-státusz BADGE-ként a gombon — így egy teljes oszlop felszabadul,
        # és az információ ott van, ahol keresed (a felhasználó észrevétele: az
        # Opt-státusz túl sok helyet foglalt egy nem túl fontos adathoz).
        busy = bool(opt_status)
        self.btn_opt.config(text=f"OPT {opt_status}" if busy else "OPT",
                            bg=BTN_STOP_BG if busy else BTN_OPT_BG,
                            fg=BTN_STOP_FG if busy else BTN_OPT_FG,
                            state="disabled" if live and not busy else "normal")

    # SZIN a szegmensekhez: zold = atenged, piros = BLOKKOL, halvany = ki/ismeretlen.
    _SEG_FG = {_g.PASS: FG_GREEN, _g.BLOCKING: FG_RED,
               _g.OFF: FG_GRAY_DIM, _g.UNKNOWN: FG_GRAY_DIM}

    def _new_seg(self, bg, gate_key=None):
        """Egy csík-szegmens (vagy összevont számláló) címkéje.

        A kattintás a kapu-PANELT nyitja — de a KONKRÉT szegmensre kattintva
        átadjuk, melyik kapuról van szó, hogy a panel azt kiemelve nyíljon. Így a
        pontos kattintás jutalmat ad, de nem követelmény: 10 kapunál a szegmensek
        pár pixel szélesek, és összevont módban nincs is szegmens — ezért a
        MEGBÍZHATÓ út mindig a panel."""
        lbl = tk.Label(self._gate_cell, text="", bg=bg, font=self._mono, padx=0)
        lbl.pack(side="left")
        if getattr(self, "_on_gates", None):
            lbl.config(cursor="hand2")
            lbl.bind("<Button-1>",
                     lambda e, k=gate_key: self._on_gates(self.symbol,
                                                          self.strategy, k))
        return lbl

    def _render_gates(self, states, bg):
        """A kapu-csik: szegmensenkent egy Label, sajat szinnel. A szegmensek
        SORRENDJE a `core.gates.REGISTRY`-bol jon, tehat allando — a pozíciok
        maguktol rogzulnek, anelkul hogy barkinek MEG KELLENE tanulnia oket."""
        states = states or []
        glyph = {_g.PASS: "▮", _g.BLOCKING: "▨"}
        # SOK kapunal osszevont szamlalo: a szegmenses csik ~6-ig olvashato,
        # afolott nem fer ki (merve: 80px cella vs 10 kapu 165px) ES ugysem
        # tudnad megszamolni, hogy a HETEDIK a piros. Az elso valtozat NEMAN
        # levagta a tobbletet -> a 10 kapus sor NEGYNEK latszott.
        if len(states) > _gl.GATE_SEGMENTS_MAX:
            parts = _g.compact(states)
            if len(self._gate_segs) != len(parts):
                for w in self._gate_segs:
                    w.destroy()
                self._gate_segs = [self._new_seg(bg) for _ in parts]  # összevont: nincs egyedi kapu
            for lbl, (txt, st) in zip(self._gate_segs, parts):
                lbl.config(text=txt + " ", fg=self._SEG_FG.get(st, FG_GRAY_DIM), bg=bg)
            self._gate_badge.config(text="", bg=bg)
            return
        # A szegmensek szama valtozhat (uj kapu regisztralasa) -> ujraepitjuk,
        # ha nem stimmel; kulonben csak atszinezunk (nincs villogas).
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

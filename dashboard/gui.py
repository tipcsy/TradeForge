"""
Élő Dashboard — tkinter GUI (stratégia-független váz)

Fülek:
  [Live Dashboard]      — élő kereskedés táblázat, Play/Stop/OPT gombok
  [Portfólió Backtest]  — eszközválasztás, dátum, equity görbe, eredménytáblázat

A táblázat OSZLOP-VEZÉRELT:
  • A VÁZ adja a fix oszlopokat: Instrumentum, BID, ASK, Vált.%, Spread,
    Pozíció, Napi P&L, Opt státusz, Vezérlés.
  • A STRATÉGIA (strategy.get_strategy) adja a középső oszlopokat és a
    visszaszámlálókat, valamint kiszámítja a megjelenítendő cellákat.
Új stratégia = új modul a `strategy` csomagban; ehhez a fájlhoz nem kell nyúlni.
"""

import json
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dashboard.theme import (
    BG, BG_HEADER, BG_ROW_ODD, BG_ROW_EVEN, BG_INACTIVE, BG_UNTRAINED,
    BG_OPT_ROW, BG_BT,
    FG_WHITE, FG_GREEN, FG_RED, FG_YELLOW, FG_GRAY, FG_GRAY_DIM, FG_BLUE,
    FG_CYAN, FG_ORANGE, FG_PURPLE, FG_TEAL,
    BTN_PLAY_BG, BTN_PLAY_FG, BTN_STOP_BG, BTN_STOP_FG, BTN_OPT_BG, BTN_OPT_FG,
    BTN_BT_BG, BTN_BT_FG, BTN_DIS_BG, BTN_DIS_FG,
    CANVAS_BG, CANVAS_LINE, CANVAS_REF,
    FG_ON_ACCENT, TOOLTIP_BG, TOOLTIP_FG,
    color as sem_color,
)
from dashboard import theme as _theme
from strategy import get_strategy
from strategy.base import Column
from strategy.settings import apply_strategy_config, main_config_view
from core import risky_mode
from core import adopted as _adopted
from core import position_meta as _pmeta
from core import pnl_split as _pnl_split
from core import opt_activity as _opt_activity
from core import gate_layout as _gate_layout
from core import quality as _quality
from core import i18n as _i18n
from core.i18n import t as _t, num as _fmtnum
from version import APP_NAME, APP_VERSION

import logging as _logging_modul

# ⚠ MIÉRT KELL EZ AZ EGY SOR. A fájl négy helyen `log.info/debug/warning`-ot
# írt, `log` viszont sehol nem volt definiálva — mind a négy hívás
# `NameError`-t dobott. A legdrágább a „Kézi kötés" volt: a megbízás MÁR
# KIMENT (a ticket megjött), és csak UTÁNA robbant a naplózás — a felhasználó
# „Hiba"-ablakot kapott egy SIKERES kötésre, tehát azt hihette, nincs
# pozíciója, miközben nyitva volt. A másik három `except` ágban ült, ahol a
# NameError elfedte az EREDETI hibát is.
log = _logging_modul.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fix (váz-szintű) oszlopok
# ---------------------------------------------------------------------------

# Instrumentum-szintű (stratégia-független) oszlopok — elöl
LEADING_COLUMNS = [
    Column("symbol", "Symbol",  10, "w",      kind="fixed"),
    Column("bid",    "BID",      9, "center", kind="fixed"),
    Column("ask",    "ASK",      9, "center", kind="fixed"),
    Column("change", _t("col.change"),   7, "center", kind="fixed"),
    Column("spread", "Spread",   9, "center", kind="fixed"),
]
# Pozíció- és vezérlés-szintű oszlopok — hátul
TRAILING_COLUMNS = [
    Column("position", _t("col.position"),    10, "center", kind="fixed"),
    Column("daily",    "Napi P&L",    9, "center", kind="fixed"),
    Column("market",   "Piac",       10, "center", kind="fixed"),
    Column("quality",  _t("gui2.minoseg"),     9, "center", kind="fixed"),
    Column("opt",      _t("gui2.opt_statusz"),18, "w",      kind="fixed"),
]


# A KIJELZÉSI ÚT fájl-olvasásai gyorsítótáron át mennek: a 2.0 sor soronként
# hívja őket, minden képfrissítésnél, a FŐ SZÁLON. Egy 672 futásos hangolás alatt
# ezek beragadtak és 93,5 mp-es fő szál-megállást okoztak (2026-08-27). A TTL
# alatt a lemezhez hozzá sem nyúlunk; utána is csak `stat()`, olvasás CSAK ha a
# fájl változott. Lásd `core/fs_cache.py`.
from core.fs_cache import FileCache as _FileCache      # noqa: E402
_DISPLAY_FS_CACHE = _FileCache(ttl=10.0)


def opt_done_date(symbol: str, strategy_name: str):
    """Az ADOTT stratégia utolsó optimalizálásának ideje a done-marker fájlból
    (`{symbol}_study.done`, a stratégia mappájában), vagy None ha nincs marker."""
    try:
        from core.params_store import done_marker
        import datetime as _dt
        dm = done_marker(symbol, strategy_name)
        return _DISPLAY_FS_CACHE.get(
            dm, lambda p: _dt.datetime.fromtimestamp(p.stat().st_mtime))
    except Exception:
        return None


# ── Az optimalizálás-státusz: SZÖVEG + nyelvfüggetlen FAJTA ────────────────
# ⚠ A felület korábban a SZÖVEGBEN keresett: `"Kész" in txt or "Utolsó opt" in
# txt` döntötte el, hogy zöld-e a cella, és hogy felülírható-e a perzisztens
# címkével. Lefordítva egyik sem talált volna — a státusz némán szürke marad, a
# perzisztens „utolsó opt" pedig sosem íródik ki.
#
# Ezért a státusz egy `str` LESZÁRMAZOTT: minden megjelenítési hely változatlanul
# szövegként kezeli (nincs 40 hívóhely átírva), a döntés viszont a `.kind`-ra
# épül. A kettő így nem tud elcsúszni egymástól — egy szöveg mellé nem lehet
# „elfelejteni" beállítani a fajtát, mert együtt keletkeznek.
OPT_DONE = "done"


class OptStatus(str):
    """Optimalizálás-státusz szöveg, `kind` fajtával (`""` | `OPT_DONE`)."""

    kind: str = ""

    def __new__(cls, text: str, kind: str = ""):
        o = super().__new__(cls, text)
        o.kind = kind
        return o


def opt_kind(value) -> str:
    """Egy státusz fajtája — sima `str` (idegen forrás) esetén üres."""
    return getattr(value, "kind", "")


def opt_done_label(symbol: str, strategy_name: str) -> str:
    """PERZISZTENS 'utolsó optimalizálás' címke EGY stratégiára, pl.
    'Utolsó opt: 26/07/16'. '' ha nincs marker. Modul-szintű (a vezérlő és az
    ablak is használja — az OptimizerController-nek nincs `strategy` tagja)."""
    d = opt_done_date(symbol, strategy_name)
    return OptStatus(_t("opt.last", date=d.strftime('%y/%m/%d')), OPT_DONE) if d else ""


def build_columns(strategies) -> list[Column]:
    """A teljes oszloplista: fix elöl + stratégiánként a középső oszlopok + fix hátul.

    `strategies`: egy Strategy VAGY Strategy-lista (több-stratégia). Minden stratégia
    jelölő-oszlopa a stratégia nevét kapja fejlécnek + egyedi kulcsot + strategy_name-t
    (így a per-instrumentum be/ki és a per-stratégia cellák szétválaszthatók)."""
    from dataclasses import replace as _replace
    if not isinstance(strategies, (list, tuple)):
        strategies = [strategies]
    mid: list[Column] = []
    for st in strategies:
        for col in st.columns():
            if col.kind == "marker":
                # A FEJLÉC a rövid név (szűk oszlop), a KULCS és a
                # `strategy_name` viszont a teljes név marad — az azonosít.
                mid.append(_replace(col, key=f"{col.key}_{st.name}",
                                    header=st.short_name, strategy_name=st.name))
            else:
                mid.append(col)
    # A TF-együttállás („Együtt") oszlop a stratégia-oszlopok ELÉ kerül.
    tfalign = [Column("tfalign", _t("col.align"), 10, "center", kind="tfalign")]
    return LEADING_COLUMNS + tfalign + mid + TRAILING_COLUMNS


# ---------------------------------------------------------------------------
# Cella-formázó segédek (váz-szintű oszlopokhoz)
# ---------------------------------------------------------------------------

def _fmt_price(v: Optional[float], digits: int) -> str:
    if v is None:
        return "—"
    return f"{v:.{digits}f}"


def _tick_color(cur: Optional[float], prev: Optional[float]) -> str:
    """Ár tick-szín: növekvő=zöld, csökkenő=piros, egyenlő/nincs=fehér."""
    if cur is None or prev is None:
        return "neutral"
    if cur > prev:
        return "up"
    if cur < prev:
        return "down"
    return "neutral"


def _fixed_cell(key: str, ds, opt_status: str, inst_state: str) -> tuple[str, str]:
    """Egy fix oszlop (text, szemantikus-szín) értéke a dashboard state-ből."""
    if key == "symbol":
        return ds.symbol, "white"
    if key == "bid":
        return _fmt_price(ds.bid, ds.digits), _tick_color(ds.bid, ds.prev_bid)
    if key == "ask":
        return _fmt_price(ds.ask, ds.digits), _tick_color(ds.ask, ds.prev_ask)
    if key == "change":
        if ds.change_pct is None:
            return "—", "muted"
        col = "up" if ds.change_pct > 0 else "down" if ds.change_pct < 0 else "neutral"
        return f"{ds.change_pct:+.2f}%", col
    if key == "spread":
        sp, sp_max = ds.spread_pts, ds.max_spread_pts
        if sp_max > 0:
            return f"{sp}/{sp_max}", ("red" if sp > sp_max else "green")
        return (f"{sp}" if sp > 0 else "—"), "muted"
    if key == "position":
        if ds.position_pnl is not None:
            txt = f"{ds.position_pnl:+.2f}$"
            if getattr(ds, "pos_count", 0) > 1:
                txt += f" ×{ds.pos_count}"
            if ds.risk_free:
                txt += " ✦"
            return txt, ("green" if ds.position_pnl >= 0 else "red")
        return "—", "muted"
    if key == "daily":
        return f"{ds.daily_pnl:+.2f}$", ("green" if ds.daily_pnl >= 0 else "red")
    if key == "market":
        # Piac-előszűrő aktuális állapota (ha van kiválasztva); egyébként „—".
        if getattr(ds, "market_strategy", None):
            return (getattr(ds, "market_state_label", "") or "—",
                    getattr(ds, "market_state_color", "muted"))
        return "—", "muted"
    if key == "quality":
        g = getattr(ds, "opt_grade", None)
        if g:
            return g[0], g[1]
        return "—", "muted"
    if key == "opt":
        txt = opt_status or "—"
        if inst_state in ("OPTIMIZING", "QUEUED"):
            col = "yellow" if inst_state == "OPTIMIZING" else "muted"
        else:
            col = "green" if opt_kind(opt_status) == OPT_DONE else "muted"
        return txt, col
    return "—", "muted"


# ---------------------------------------------------------------------------
# Live Dashboard — egy sor widgetei (oszlop-vezérelt)
# ---------------------------------------------------------------------------

class PairRow:
    def __init__(self, parent: tk.Frame, symbol: str, row_idx: int, columns: list,
                 on_run, on_opt, on_delete, on_risky, on_name_click, mono_font, small_font,
                 on_status_click=None, on_marker_click=None, on_opt_menu=None,
                 on_tfalign=None):
        self.symbol  = symbol
        self.columns = columns
        self._bg     = BG_ROW_ODD if row_idx % 2 == 0 else BG_ROW_EVEN
        self._mono   = mono_font
        self._opt_full = ""       # az Opt státusz TELJES szövege (tooltiphez)
        self._opt_tip  = None     # a lebegő tooltip-ablak (Toplevel), ha látszik

        self.frame = tk.Frame(parent, bg=self._bg)
        # Nem csomagoljuk magát — _apply_filter_sort() kezeli

        self.labels: dict[str, tk.Label] = {}
        # Körös jelölő-oszlopok: col.key → (frame, [(stádium_kulcs, kör-Label), …]).
        # A fix szélességű Frame (pack_propagate ki) igazodik a fejléc-oszlophoz
        # (width karakter × mono px + 2×padx), a körök benne elosztva.
        self.markers: dict[str, tuple] = {}
        self.tfalign = None            # TF-együttállás cella (dots + S), lazán építve
        self._on_tfalign = None        # kattintás-callback a TF-align cellához
        _charpx = mono_font.measure("0")
        _cellh  = mono_font.metrics("linespace") + 6
        for col in self.columns:
            if col.kind == "marker":
                cell = tk.Frame(self.frame, bg=self._bg,
                                width=_charpx * col.width + 8, height=_cellh)
                cell.pack(side="left")
                cell.pack_propagate(False)
                # A körökre kattintva → az adott STRATÉGIA paraméterei (Stratégia
                # Paraméterek ablak). A stratégia neve az oszlopból (col.strategy_name).
                if on_marker_click is not None:
                    cell.config(cursor="hand2")
                    cell.bind("<Button-1>",
                              lambda e, sn=col.strategy_name: on_marker_click(symbol, sn))
                # „Lego-kocka" keret: vékony szegély KÖRBEN (fent/lent is), benne
                # a stratégia körei → a stratégiák jelölő-csoportjai dobozokként
                # különülnek el: ▢● ● ●▢ ▢● ●▢
                inner = tk.Frame(cell, bg=self._bg, highlightthickness=1,
                                 highlightbackground=FG_GRAY_DIM,
                                 highlightcolor=FG_GRAY_DIM)
                inner.pack(expand=True, pady=2)
                _click = (lambda e, sn=col.strategy_name:
                          on_marker_click(symbol, sn)) if on_marker_click else None
                if _click is not None:
                    inner.config(cursor="hand2")
                    inner.bind("<Button-1>", _click)
                # No-trade (⏸) jel KÜLÖN helyen — nem az első kört cseréli le,
                # így az irány-szín (zöld/piros pötty) a szünet alatt is látszik.
                pause = tk.Label(inner, text="", bg=self._bg, fg=FG_GRAY,
                                 font=mono_font, padx=0)
                pause.pack(side="left")
                circles = []
                for skey, _slabel in col.stages:
                    c = tk.Label(inner, text="●", bg=self._bg, fg=FG_GRAY,
                                 font=mono_font, padx=1)
                    if _click is not None:
                        c.config(cursor="hand2")
                        c.bind("<Button-1>", _click)
                    c.pack(side="left", expand=True)
                    circles.append((skey, c))
                self.markers[col.key] = (cell, circles, pause, inner)
                continue
            if col.kind == "tfalign":
                # TF-együttállás cella: idősíkonként egy színes pont (zöld BUY / piros
                # SELL / szürke semleges) + egy erős „S", ha MIND egyezik. A pontokat
                # az első frissítéskor építjük (a figyelt idősíkok számától függően).
                # A cellára kattintva → a TF-együttállás beállítás-ablaka (idősíkok+SMA).
                cell = tk.Frame(self.frame, bg=self._bg,
                                width=_charpx * col.width + 8, height=_cellh)
                cell.pack(side="left")
                cell.pack_propagate(False)
                inner = tk.Frame(cell, bg=self._bg)
                inner.pack(expand=True)
                self._on_tfalign = on_tfalign
                if on_tfalign is not None:
                    _tclick = lambda e: on_tfalign(symbol)
                    for _w in (cell, inner):
                        _w.config(cursor="hand2")
                        _w.bind("<Button-1>", _tclick)
                self.tfalign = {"inner": inner, "dots": [], "s": None}
                continue
            if col.key == "opt":
                # Az Opt státusz a Vezérlés gombok UTÁN jön, és az ablak MARADÉK
                # szélességét tölti ki (lásd lent) → a hosszú szöveg is kifér.
                continue
            lbl = tk.Label(self.frame, text="—", width=col.width, anchor=col.anchor,
                           bg=self._bg, fg=FG_GRAY, font=mono_font, padx=4, pady=3)
            lbl.pack(side="left")
            self.labels[col.key] = lbl

        # A Symbol cellára kattintva → optimalizált paraméterek szerkesztője
        self.labels["symbol"].config(cursor="hand2")
        self.labels["symbol"].bind("<Button-1>", lambda e: on_name_click(symbol))

        # Egy gomb a futtatáshoz (Play↔Stop morph) és egy az OPT-hoz (OPT↔STOP morph).
        # A gombok egy KERETBEN ülnek → a keret tényleges pixel-szélessége adja a
        # fejléc "Vezérlés" cellájának szélességét (pontos oszlop-igazítás).
        self.ctrl_frame = tk.Frame(self.frame, bg=self._bg)
        self.ctrl_frame.pack(side="left")
        self.btn_run = tk.Button(self.ctrl_frame, text="▶", width=3,
                                 bg=BTN_DIS_BG, fg=BTN_DIS_FG, font=small_font,
                                 relief="flat", command=lambda: on_run(symbol))
        self.btn_run.pack(side="left", padx=1)
        self.btn_risky = tk.Button(self.ctrl_frame, text="R", width=2,
                                   bg=BTN_DIS_BG, fg=BTN_DIS_FG, font=small_font,
                                   relief="flat", command=lambda: on_risky(symbol))
        self.btn_risky.pack(side="left", padx=1)
        # A korábbi „V" (vizualizáció) és „K" (jel-replay) gomb ÁTKÖLTÖZÖTT az
        # instrumentum-beállítások táblázatába (az instrumentum NEVÉRE kattintva),
        # ahol PER STRATÉGIA pipálható — a sorban egy pár-szintű gomb nem tudta
        # volna kifejezni a több-stratégiás esetet. Lásd `_show_instrument_settings`.
        self.btn_opt = tk.Button(self.ctrl_frame, text="OPT", width=4,
                                 bg=BTN_DIS_BG, fg=BTN_DIS_FG, font=small_font,
                                 relief="flat", command=lambda: on_opt(symbol))
        self.btn_opt.pack(side="left", padx=1)
        # JOBB-klikk az OPT-on → konkrét stratégia választása (több-stratégiás eset)
        if on_opt_menu is not None:
            self.btn_opt.bind("<Button-3>", lambda e: on_opt_menu(symbol, e))
        self.btn_del = tk.Button(self.ctrl_frame, text="✕", width=2,
                                 bg=BTN_DIS_BG, fg=BTN_DIS_FG, font=small_font,
                                 relief="flat", command=lambda: on_delete(symbol))
        self.btn_del.pack(side="left", padx=(1, 4))

        # ── Opt státusz — a Vezérlés UTÁN, az ablak MARADÉK szélességében ────
        # (fill+expand → a hosszú státusz-szöveg is kifér; a tooltip marad,
        # hátha nagyon keskeny az ablak).
        _opt_col = next((c for c in self.columns if c.key == "opt"), None)
        if _opt_col is not None:
            lbl = tk.Label(self.frame, text="—", width=_opt_col.width,
                           anchor=_opt_col.anchor, bg=self._bg, fg=FG_GRAY,
                           font=mono_font, padx=4, pady=3)
            lbl.pack(side="left", fill="x", expand=True)
            self.labels["opt"] = lbl
            # Kattintás → részletes állapot / hibalog / trials CSV; hover → teljes
            # szöveg tooltipben.
            if on_status_click:
                lbl.config(cursor="hand2")
                lbl.bind("<Button-1>", lambda e: on_status_click(symbol))
            lbl.bind("<Enter>", self._opt_tip_show)
            lbl.bind("<Leave>", self._opt_tip_hide)

    def _morph_btn(self, btn, text, enabled, active_bg, active_fg):
        if enabled:
            btn.config(text=text, bg=active_bg, fg=active_fg, state="normal")
        else:
            btn.config(text=text, bg=BTN_DIS_BG, fg=BTN_DIS_FG, state="disabled")

    # ── Opt státusz tooltip (a keskeny cellában elcsúszó teljes szöveg) ──────
    def _opt_tip_show(self, event):
        text = (self._opt_full or "").strip()
        if not text or text == "—" or self._opt_tip is not None:
            return
        lbl = self.labels.get("opt")
        tip = tk.Toplevel(lbl)
        tip.wm_overrideredirect(True)       # keret nélküli buborék
        tip.attributes("-topmost", True)
        x = lbl.winfo_rootx()
        y = lbl.winfo_rooty() + lbl.winfo_height() + 2
        tk.Label(tip, text=text, bg=TOOLTIP_BG, fg=TOOLTIP_FG,
                 font=self._mono, padx=6, pady=3, relief="solid", bd=1,
                 justify="left").pack()
        tip.wm_geometry(f"+{x}+{y}")
        self._opt_tip = tip

    def _opt_tip_hide(self, event=None):
        if self._opt_tip is not None:
            try:
                self._opt_tip.destroy()
            except Exception:
                pass
            self._opt_tip = None

    def _blank_all(self, fg, except_keys=()):
        for col in self.columns:
            if col.key == "symbol" or col.key in except_keys:
                continue
            if col.kind == "marker":
                _c, circles, pause, _i = self.markers[col.key]
                pause.config(text="")
                for _skey, c in circles:
                    c.config(text="●", fg=fg)
                continue
            if col.kind == "tfalign":
                # Az „Együtt" cella nem a `labels`-ben él (saját pont-sor + „S"),
                # ezért a halványítást külön kell elvégezni — enélkül KeyError.
                if self.tfalign:
                    for d in self.tfalign.get("dots") or []:
                        d.config(fg=fg)
                    _s = self.tfalign.get("s")
                    if _s is not None:
                        _s.config(text="–", fg=fg)
                continue
            self.labels[col.key].config(text="—", fg=fg)

    def _render_marker(self, col, ds, trained, no_trade, bg):
        """A jelölő-oszlop köreinek frissítése egy STRATÉGIÁHOZ (col.strategy_name):
        stádiumonként egy kör a strategy_cells[strat][stádium] cellából (glifa+szín).
        Ha a stratégia ezen az instrumentumon KI van kapcsolva → halvány pontok.
        A no-trade órát KÜLÖN ⏸ jel mutatja a doboz elején — nem az első kört
        cseréli le, így az irány-szín (zöld/piros pötty) a szünet alatt is látszik."""
        _frame, circles, pause, _inner = self.markers[col.key]
        sname = col.strategy_name
        enabled_list = getattr(ds, "enabled_strategies", None) or []
        # Üres lista → az egyetlen/aktív stratégia engedélyezett (visszafelé komp.).
        strat_enabled = (sname in enabled_list) if enabled_list else True
        # ⚠ A CELLÁK AZ ADATOT KÖVETIK, NEM A `trained` JELZŐT. Egy hangolatlan
        # (alapértelmezett paraméterekkel futó) pár is SZÁMOL — ha a `trained`
        # kapuzna, a körök szürkék maradnának, miközben a motor dolgozik, és a
        # felhasználó azt hinné, elromlott valami. Ha a motor nem számol, a
        # `strategy_cells` úgyis üres, tehát a körök maguktól szürkék.
        # A „nincs hangolva" tényt a SOR HÁTTÉRSZÍNE mondja el (BG_UNTRAINED).
        cells = ds.strategy_cells.get(sname, {}) if strat_enabled else {}
        pause.config(text="⏸" if (no_trade and strat_enabled) else "", bg=bg)
        for skey, c in circles:
            if not strat_enabled:
                # Kikapcsolt stratégia ezen az instrumentumon: apró pont (nem kör)
                # → ránézésre elválik, melyik stratégia él az adott soron.
                c.config(text="·", fg=FG_GRAY_DIM, bg=bg)
                continue
            cell = cells.get(skey)
            if cell:
                c.config(text=cell[0], fg=sem_color(cell[1]), bg=bg)
            else:
                c.config(text="●", fg=FG_GRAY, bg=bg)

    def _render_tfalign(self, ds, bg):
        """TF-együttállás cella: idősíkonként egy színes pont (zöld=fölfelé /
        piros=lefelé / szürke=semleges) + egy erős „S", ha MIND egy irányba mutat
        (zöld BUY / piros SELL). A pontokat az idősíkok számához igazítva építjük."""
        if not self.tfalign:
            return
        signs = getattr(ds, "tf_align_signs", None) or []
        direction = getattr(ds, "tf_align_dir", None)
        inner, dots = self.tfalign["inner"], self.tfalign["dots"]
        # Pontok (újra)építése, ha a szám változott (config-váltás/első frissítés).
        if len(dots) != len(signs):
            _tclick = (lambda e: self._on_tfalign(self.symbol)) if self._on_tfalign else None
            for w in inner.winfo_children():
                w.destroy()
            dots = []
            for _ in signs:
                d = tk.Label(inner, text="●", bg=bg, fg=FG_GRAY, font=self._mono, padx=1)
                if _tclick is not None:
                    d.config(cursor="hand2")
                    d.bind("<Button-1>", _tclick)
                d.pack(side="left")
                dots.append(d)
            s_lbl = tk.Label(inner, text=" ", bg=bg, fg=FG_GRAY, font=self._mono, padx=1)
            if _tclick is not None:
                s_lbl.config(cursor="hand2")
                s_lbl.bind("<Button-1>", _tclick)
            s_lbl.pack(side="left")
            self.tfalign["dots"], self.tfalign["s"] = dots, s_lbl
        # Pontok színe a per-idősík irányból.
        for d, s in zip(self.tfalign["dots"], signs):
            col = FG_GREEN if s > 0 else FG_RED if s < 0 else FG_GRAY
            d.config(fg=col, bg=bg)
        # Erős „S" csak együttállásnál (különben halvány „–").
        s_lbl = self.tfalign["s"]
        if s_lbl is not None:
            if direction == "BUY":
                s_lbl.config(text="S", fg=FG_GREEN, bg=bg)
            elif direction == "SELL":
                s_lbl.config(text="S", fg=FG_RED, bg=bg)
            else:
                s_lbl.config(text="–", fg=FG_GRAY_DIM, bg=bg)

    def update(self, ds, inst_state: str, opt_status: str, connected: bool = True,
               no_trade: bool = False):
        trained      = ds.trained
        self._opt_full = opt_status or ""     # a tooltip a belépéskori teljes szöveget mutatja

        if inst_state == "OPTIMIZING":
            bg = BG_OPT_ROW
        elif not trained:
            bg = BG_UNTRAINED
        elif inst_state == "STOPPED":
            bg = BG_INACTIVE
        elif no_trade:
            bg = BG_INACTIVE   # LIVE, de no-trade óra (aktív stratégia) → "letiltva"
        else:
            bg = self._bg
        self.frame.config(bg=bg)
        self.ctrl_frame.config(bg=bg)
        for lbl in self.labels.values():
            lbl.config(bg=bg)
        for frame, circles, pause, inner in self.markers.values():
            frame.config(bg=bg)
            inner.config(bg=bg)
            pause.config(bg=bg)
            for _skey, c in circles:
                c.config(bg=bg)

        sym_lbl = self.labels["symbol"]

        # „R" gomb = kockázatcsökkentő PRESET (kattintásra körbe-vált). A gomb a
        # ténylegesen érvényes presetet mutatja: — Ki | R Risky | F Felező | P Pajzs
        # | Fi Fibo.
        _rp = getattr(ds, "rr_preset", "off")
        _rrmap = {"risky": ("R", FG_ORANGE), "halving": ("F", FG_CYAN),
                  "shield": ("P", FG_GREEN), "fibo": ("Fi", FG_YELLOW),
                  "thirds": ("H", FG_PURPLE), "shield_fibo": ("PF", FG_TEAL)}
        if _rp in _rrmap:
            _txt, _col = _rrmap[_rp]
            self.btn_risky.config(text=_txt, bg=_col, fg=FG_ON_ACCENT, state="normal")
        else:
            self.btn_risky.config(text="—", bg=BTN_DIS_BG, fg=FG_GRAY, state="normal")

        # (A V/K gomb-állapot innen elkerült — a kapcsolók az instrumentum-
        # beállítások táblázatában élnek, per stratégia.)

        # ── Offline ───────────────────────────────────────────────────────
        if not connected and inst_state not in ("OPTIMIZING", "QUEUED"):
            sym_lbl.config(text=self.symbol, fg=FG_GRAY_DIM,
                           font=_theme.fonts()["mono_italic"])
            self._blank_all(FG_GRAY_DIM)
            self._morph_btn(self.btn_run, "▶",   False, BTN_PLAY_BG, BTN_PLAY_FG)
            self._morph_btn(self.btn_opt, "OPT", False, BTN_OPT_BG,  BTN_OPT_FG)
            self._morph_btn(self.btn_del, "✕",   False, BG_INACTIVE, FG_RED)
            return

        # ── Optimalizálás / sorban áll ──────────────────────────────────────
        if inst_state in ("OPTIMIZING", "QUEUED"):
            sym_lbl.config(text=self.symbol, fg=FG_YELLOW,
                           font=_theme.fonts()["mono_bold"])
            self._blank_all(FG_GRAY_DIM, except_keys=("opt",))
            txt, col = _fixed_cell("opt", ds, opt_status, inst_state)
            self.labels["opt"].config(text=txt, fg=sem_color(col))
            self._morph_btn(self.btn_run, "▶", False, BTN_PLAY_BG, BTN_PLAY_FG)
            # QUEUED → STOP (sorból törlés); OPTIMIZING (fut) → STOP (leállítás-
            # kérés: a szubprocessz trial-/lépés-határon áll le, eredmény eldobva).
            self._morph_btn(self.btn_opt, "STOP", True, BTN_STOP_BG, BTN_STOP_FG)
            self._morph_btn(self.btn_del, "✕", False, BG_INACTIVE, FG_RED)
            return

        # ── LIVE / KIVEZETÉS / STOPPED ──────────────────────────────────────
        if inst_state == "CLOSING":
            # Stop kérve, de még fut a pozíció: a motor kezeli (BE/trailing), de
            # ÚJ belépőt nem nyit. Narancs ⏹ — a ⏸ (no-trade) mintájára.
            sym_lbl.config(text=f"⏹ {self.symbol}", fg=FG_ORANGE,
                           font=_theme.fonts()["mono_bold"])
        elif inst_state == "LIVE":
            if no_trade:
                # Aktív, de az aktuális (bróker-)óra a stratégia trade_hours-ából
                # kimarad → "letiltott" kinézet (mint egy disabled gomb) + ⏸ jel.
                sym_lbl.config(text=f"⏸ {self.symbol}", fg=FG_GRAY,
                               font=_theme.fonts()["mono_italic"])
            else:
                sym_lbl.config(text=self.symbol, fg=FG_WHITE, font=_theme.fonts()["mono_bold"])
        elif trained:
            sym_lbl.config(text=self.symbol, fg=FG_GRAY, font=_theme.fonts()["mono"])
        else:
            sym_lbl.config(text=self.symbol, fg=FG_GRAY_DIM, font=_theme.fonts()["mono_italic"])

        for col in self.columns:
            key = col.key
            if key == "symbol":
                continue
            if col.kind == "fixed":
                txt, c = _fixed_cell(key, ds, opt_status, inst_state)
                self.labels[key].config(text=txt, fg=sem_color(c))
            elif col.kind == "countdown":
                rem = ds.timeframe_remaining.get(col.timeframe_min)
                if rem is None:
                    self.labels[key].config(text="—", fg=FG_GRAY)
                else:
                    self.labels[key].config(text=f"{rem//60}:{rem%60:02d}", fg=FG_GRAY)
            elif col.kind == "marker":
                self._render_marker(col, ds, trained, no_trade, bg)
            elif col.kind == "tfalign":
                self._render_tfalign(ds, bg)
            else:  # strategy
                cell = ds.strategy_cells.get(key)   # lásd `_render_marker`
                if cell:
                    self.labels[key].config(text=cell[0], fg=sem_color(cell[1]))
                else:
                    self.labels[key].config(text="—", fg=FG_GRAY)

        # Gombok
        if inst_state == "CLOSING":
            # Kivezetés: a gomb VISSZAVONJA a leállítást (▶ narancs = „mégis fusson").
            # Az Opt/Törlés tiltva marad, amíg a pozíció ki nem fut.
            self._morph_btn(self.btn_run, "▶", True, FG_ORANGE, FG_ON_ACCENT)
            self._morph_btn(self.btn_opt, "OPT", False, BTN_OPT_BG, BTN_OPT_FG)
            self._morph_btn(self.btn_del, "✕",  False, BG_INACTIVE, FG_RED)
        elif inst_state == "LIVE":
            # Play→Stop morph. Nyitott pozícióval IS leállítható → kivezetés.
            self._morph_btn(self.btn_run, "■", True, BTN_STOP_BG, BTN_STOP_FG)
            self._morph_btn(self.btn_opt, "OPT", False, BTN_OPT_BG, BTN_OPT_FG)
            self._morph_btn(self.btn_del, "✕",  False, BG_INACTIVE, FG_RED)
        else:  # STOPPED
            self._morph_btn(self.btn_run, "▶",  trained, BTN_PLAY_BG, BTN_PLAY_FG)
            self._morph_btn(self.btn_opt, "OPT", True,   BTN_OPT_BG,  BTN_OPT_FG)
            self._morph_btn(self.btn_del, "✕",   True,   BG_INACTIVE, FG_RED)


# ---------------------------------------------------------------------------
# Live Dashboard — fejléc sor (oszlop-vezérelt, rendezhető)
# ---------------------------------------------------------------------------

class HeaderRow:
    def __init__(self, parent: tk.Frame, columns: list, header_font, small_font,
                 on_col_click=None):
        self.columns = columns
        self.frame = tk.Frame(parent, bg=BG_HEADER)
        self.frame.pack(fill="x", padx=2, pady=(4, 0))
        self._lbls: list[tk.Label] = []
        self._ctrl_hdr = None
        for i, col in enumerate(columns):
            # A Vezérlés fejléc az Opt státusz ELÉ kerül (a sorokban is a gombok
            # előzik meg a státuszt); az Opt státusz a maradék szélességet kapja.
            # A Vezérlés cella fix PIXEL-szélességű keret: a sorok gombsorának
            # tényleges szélességét a sync_ctrl_width() tükrözi rá (pontos igazítás).
            if col.key == "opt":
                self._ctrl_hdr = tk.Frame(self.frame, bg=BG_HEADER)
                _cl = tk.Label(self._ctrl_hdr, text=_t("col.ctrl"), anchor="w",
                               bg=BG_HEADER, fg=FG_BLUE, font=header_font,
                               padx=4, pady=3)
                _cl.pack(fill="both", expand=True)
                self._ctrl_hdr.config(width=_cl.winfo_reqwidth(),
                                      height=_cl.winfo_reqheight())
                self._ctrl_hdr.pack_propagate(False)
                self._ctrl_hdr.pack(side="left")
            lbl = tk.Label(
                self.frame, text=col.header, width=col.width, anchor=col.anchor,
                bg=BG_HEADER, fg=FG_BLUE, font=header_font,
                padx=4, pady=3, cursor="hand2",
            )
            if on_col_click:
                lbl.bind("<Button-1>", lambda e, idx=i: on_col_click(idx))
            lbl.pack(side="left", fill="x" if col.key == "opt" else "none",
                     expand=(col.key == "opt"))
            self._lbls.append(lbl)
        tk.Frame(parent, bg=FG_GRAY_DIM, height=1).pack(fill="x", padx=2)

    def sync_ctrl_width(self, px: int):
        """A Vezérlés fejléc-cella szélessége = a sorok gombsorának TÉNYLEGES
        pixel-szélessége (a PairRow ctrl_frame <Configure>-je hívja)."""
        if self._ctrl_hdr is not None and px > 1:
            self._ctrl_hdr.config(width=px)

    def set_sort(self, col_idx: Optional[int], direction: int):
        for i, lbl in enumerate(self._lbls):
            col = self.columns[i]
            if i == col_idx and direction != 0:
                arrow = "▲" if direction == 1 else "▼"
                lbl.config(fg=FG_CYAN, text=f"{col.header} {arrow}", width=col.width)
            else:
                lbl.config(fg=FG_BLUE, text=col.header, width=col.width)


# ---------------------------------------------------------------------------
# Optimizer vezérlő — adat-előkészítés háttérSZÁLON, számítás külön PROCESSZBEN
# ---------------------------------------------------------------------------

class _LocalProgress:
    """Tartalék haladásjelző, ha a process-pool nem érhető el (egy folyamatban).
    A .put((symbol, done, total)) hívás közvetlenül a státusz dict-be ír."""
    def __init__(self, status: dict):
        self._status = status

    def put(self, item):
        symbol, done, total = item
        pct = int(done / total * 100) if total else 0
        self._status[symbol] = f"{done}/{total}  {pct}%"


class OptimizerController:
    def __init__(self, cfg: dict, strategy, dashboard_ref: dict,
                 instrument_state: dict, optimizer_status: dict,
                 max_parallel: int = 2):
        self.cfg              = cfg
        self.strategy         = strategy
        self.dashboard_ref    = dashboard_ref
        self.instrument_state = instrument_state
        self.optimizer_status = optimizer_status
        self.max_parallel     = max_parallel
        self._lock            = threading.Lock()
        self._queue: list     = []
        self._running: set    = set()
        # Utolsó haladás időbélyege páronként — a "nem halad" (stall) timeouthoz
        self._last_progress: dict = {}

        # Process-pool + folyamatok közti progress-queue (lazán, háttérben)
        self._pool        = None
        self._manager     = None
        self._progress_q  = None
        self._pool_lock   = threading.Lock()
        self._pool_failed = False
        # Eager létrehozás háttérszálon, hogy az első OPT kattintás se akadjon
        threading.Thread(target=self._ensure_pool, daemon=True,
                         name="OptPoolInit").start()

    # ── Process-pool életciklus ──────────────────────────────────────────
    def _ensure_pool(self):
        with self._pool_lock:
            if self._pool is not None or self._pool_failed:
                return
            try:
                import multiprocessing as mp
                from concurrent.futures import ProcessPoolExecutor
                self._manager    = mp.Manager()
                self._progress_q = self._manager.Queue()
                self._pool       = ProcessPoolExecutor(max_workers=self.max_parallel)
                threading.Thread(target=self._drain_progress, daemon=True,
                                 name="OptProgress").start()
            except Exception:
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "Process-pool nem hozható létre — szálon belüli tartalék.",
                    exc_info=True)
                self._pool = None
                self._pool_failed = True

    def _drain_progress(self):
        """A gyermekfolyamatok haladását a fő státusz dict-be vezeti. A progress-queue
        szimbólum-szintű (symbol, done, total); a MELYIK stratégia a futó tételből
        derül ki (egy szimbólumon egyszerre egy fut)."""
        while True:
            try:
                symbol, done, total = self._progress_q.get()
            except Exception:
                break
            strat = next((st for (s, st) in self._running if s == symbol), None)
            if strat is not None:
                pct = int(done / total * 100) if total else 0
                self.optimizer_status[symbol] = f"{strat} {done}/{total}  {pct}%"
                # A 2.0 rövid Opt-cellájához: a haladás SZÁMKÉNT is elérhető legyen
                # per (pár, stratégia). Enélkül a cella csak „fut…"-ot tudott
                # mondani — a `classic` hosszú szövege oda nem fér ki.
                _opt_activity.set_progress(symbol, strat, done, total)
                self._last_progress[symbol] = time.time()   # halad → stall-óra újraindul

    def shutdown(self):
        try:
            if self._pool is not None:
                self._pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        try:
            if self._manager is not None:
                self._manager.shutdown()
        except Exception:
            pass

    # ── Vezérlés ──────────────────────────────────────────────────────────
    # A munkatételek (symbol, strategy) párok — így per-stratégia tudjuk, MELYIK
    # optimalizál. A KIJELZÉS (instrument_state / optimizer_status) szimbólum-szintű
    # marad (aggregátum): egy szimbólumon EGYSZERRE EGY stratégia optimalizál (a
    # másik sorba kerül), így a szimbólum egyértelműen egy futó tételt azonosít.

    def _default_strategy(self) -> str:
        return getattr(self.strategy, "name", "wpr_sma")

    def _strategy_live(self, symbol: str, strategy: str) -> bool:
        """Kereskedik-e ÉPP ez a (symbol, strategy)? Ez az OPT kapuja: a kereskedő
        stratégiát nem optimalizáljuk (a futás végén felülíródna a paraméterfájlja).

        A képlet a MOTORÉ (`live_trader.run`): a szándék (`core.run_state`) ÉS a
        pár engedélyezett stratégiái (`pairs.<sym>.strategies`) METSZETE. A szándék
        önmagában nem elég: a `run_state` bejegyzés akkor is ott marad, ha közben
        kikapcsoltad a stratégiát a páron — ilyenkor a motor NEM futtatja, tehát
        nincs mit félteni, és épp ilyenkor akarnád optimalizálni (mielőtt
        bekapcsolod). A szűrés nélkül ez NÉMÁN tagadta meg az OPT-ot
        (`request_optimize` szó nélkül visszatért).

        Hibánál KONZERVATÍV: True (inkább nem optimalizálunk, mint hogy egy
        kereskedő stratégia paraméterei alóla íródjanak át)."""
        try:
            from core import run_state as _rs
            from strategy import enabled_strategy_names
            if strategy not in (enabled_strategy_names(self.cfg, symbol) or []):
                return False
            return _rs.get_state(self.cfg, symbol, strategy,
                                 self._default_strategy()) == _rs.LIVE
        except Exception:
            return True

    def _symbol_busy(self, symbol: str) -> bool:
        """Fut vagy sorban áll-e MÁR bármely stratégia ezen a szimbólumon.

        ERŐFORRÁS-korlát (egy szimbólumon egyszerre egy optimalizálás), NEM
        kereskedési korlát — a többi stratégia közben kereskedhet."""
        return (any(s == symbol for s, _ in self._running)
                or any(s == symbol for s, _ in self._queue))

    def request_optimize(self, symbol: str, strategy: str | None = None,
                         all_params: bool = False):
        """Egy (symbol, strategy) optimalizálás kérése. Ugyanarra a szimbólumra TÖBB
        stratégia is kérhető — egyszerre EGY fut, a többi sorba kerül.

        A KERESKEDŐ stratégiát nem optimalizáljuk — de ezt PER STRATÉGIA nézzük.
        Korábban a szimbólum állapota döntött, ezért egy kereskedő páron egyáltalán
        nem lehetett optimalizálni: előbb Stopot kellett nyomni, ami a pár ÖSSZES
        stratégiáját leállította. Pedig a `wpr_sma` hangolása alatt az `ml_ai`
        zavartalanul kereskedhet (külön magic, külön paraméterfájl, külön pozíciók)."""
        strategy = strategy or self._default_strategy()
        with self._lock:
            # KIVEZETÉS alatt is fut a stratégia (nyitott pozíciót kezel) → nem
            # optimalizáljuk. A kivezetés a SZIMBÓLUM szintjén él, ezért azt még
            # szimbólum-szinten kérdezzük; a LIVE viszont per stratégia dől el.
            # ⚠ MINDHÁROM ELUTASÍTÁS OKOT AD. Eddig néma `return` volt: a hívó
            # „elindítottam"-ot jelentett vissza, a felület pedig ugyanúgy nézett
            # ki, mint máskor — a felhasználó szemszögéből a gomb nem csinált
            # semmit.
            # ⚠ A kivezetés SZIMBÓLUM-szintű, az optimalizálás viszont PER
            # STRATÉGIA. Ha ezt a stratégiát épp most állítottuk le (a futás
            # kedvéért), a pár attól még kivezetésben lehet egy nyitott pozíció
            # miatt — de új belépő NEM nyílik, tehát a paraméterfájl felülírása
            # nem szivároghat egy friss belépőbe. Csak akkor tiltunk, ha a
            # stratégia TÉNYLEG kereskedik.
            if (self.instrument_state.get(symbol) == "CLOSING"
                    and self._strategy_live(symbol, strategy)):
                return (_t("gui.opt.closing", symbol=symbol))
            # ⚠ VÉGSŐ VÉDELEM: a felület (`_live2_opt_click`) már leállította a
            # stratégiát, mielőtt idáig jutott. Ha ide MÉGIS kereskedő
            # stratégiával érkezünk (más hívó, sikertelen leállítás), nem
            # optimalizálunk — a paraméterfájl nem íródhat át egy futó
            # stratégia alól.
            if self._strategy_live(symbol, strategy):
                return (_t("gui.opt.trading", symbol=symbol, strategy=strategy))
            job = (symbol, strategy)
            if job in self._running or job in self._queue:
                return _t("gui.opt.already", symbol=symbol, strategy=strategy)
            # ⚠ „TELJES tér" kérés: a (pár, stratégia) kihagyás-listáját ennél az
            # EGY futásnál figyelmen kívül hagyjuk. A jelzőt itt jegyezzük meg,
            # mert a munka sorba is kerülhet — a kérés szándéka nem veszhet el a
            # várakozás alatt.
            if not hasattr(self, "_all_params"):
                self._all_params = {}
            self._all_params[job] = bool(all_params)
            # Elavult leállítás-marker törlése: MOST kértek friss futást — egy
            # korábbi (már lezárt futás után maradt) STOP ne szakítsa meg azonnal.
            try:
                from core.params_store import stop_marker
                stop_marker(symbol, strategy).unlink(missing_ok=True)
            except Exception:
                pass
            symbol_running = any(s == symbol for s, _ in self._running)
            if len(self._running) < self.max_parallel and not symbol_running:
                self._start(job)
            else:
                self._queue.append(job)
                # A tevékenység PER STRATÉGIA jelölődik; a szimbólum-szintű kijelzést
                # az `opt_activity.symbol_state()` vonja össze. Az `instrument_state`-et
                # NEM írjuk: az a kereskedési szándék, és nem szabad elveszítenie.
                _opt_activity.set_state(symbol, strategy, _opt_activity.QUEUED,
                                        _t("gui.opt.waiting", strategy=strategy))
                self.optimizer_status[symbol] = _t("gui.opt.waiting", strategy=strategy)
        return ""

    def cancel_queued(self, symbol: str, strategy: str = None):
        """Sorban álló (QUEUED) optimalizálás visszavonása.

        `strategy=None` → a szimbólum ÖSSZES sorban álló tétele (a classic OPT
        gombja szimbólum-szintű). Névvel CSAK azt az egyet — a 2.0 OPT gombja a
        stratégia saját blokkjában ül, tehát ott a többihez nem szabad nyúlni."""
        with self._lock:
            def _match(s, st):
                return s == symbol and (strategy is None or st == strategy)
            _dropped = [st for (s, st) in self._queue if _match(s, st)]
            self._queue = [(s, st) for (s, st) in self._queue if not _match(s, st)]
            for _st in _dropped:
                _opt_activity.set_state(symbol, _st, None)
            # Az `instrument_state`-hez NEM nyúlunk: a sor ürítése nem kereskedési
            # döntés. (Korábban STOPPED-re állította — ez törölte a Play szándékot.)
            if not self._symbol_busy(symbol):
                self.optimizer_status[symbol] = ""

    def request_stop(self, symbol: str, strategy: str = None):
        """FUTÓ optimalizálás/tanítás leállítás-kérése + a sorban állók törlése.

        `strategy=None` → a szimbólum összes futó tétele (classic). Névvel CSAK
        azt az egyet (2.0: a gomb a stratégia blokkjában ül).

        A stop-marker fájlt a szubprocessz trial-/lépés-határon észleli (optuna:
        study.stop) → az eredmény ELDOBVA, a korábban mentett paraméterek
        érintetlenek, nincs auto-folytatás."""
        from core.params_store import stop_marker
        with self._lock:
            running = [j for j in self._running
                       if j[0] == symbol and (strategy is None or j[1] == strategy)]
        for s, strat in running:
            try:
                stop_marker(s, strat).touch()
            except Exception:
                pass
        self.cancel_queued(symbol, strategy)   # a sorban állók is törölve
        for _s, _strat in running:
            _opt_activity.set_status(_s, _strat, _t("gui2.leallitas_kerve"))
        if running:
            self.optimizer_status[symbol] = _t("gui2.leallitas_kerve")

    def resume_unfinished(self):
        """INDÍTÁSKOR: a fájlrendszerben talált BEFEJEZETLEN study-k (van `_study.db`,
        nincs `.done`) automatikus sorba állítása — per (symbol, strategy). Az optuna a
        `.db`-ből folytat. A LIVE (kereskedő) szimbólumokat kihagyja (azok szándéka a
        kereskedés). A `live_trader` induló állapot-beállítása után hívandó (kis
        késleltetéssel, hogy a LIVE jelölés már beálljon)."""
        try:
            from core.params_store import unfinished_studies
            pending = unfinished_studies()
        except Exception:
            return
        for symbol, strat in pending:
            # Per STRATÉGIA: egy kereskedő páron a MÁSIK stratégia befejezetlen
            # study-ja nyugodtan folytatódhat.
            if (self.instrument_state.get(symbol) == "CLOSING"
                    or self._strategy_live(symbol, strat)):
                continue
            self.request_optimize(symbol, strat)   # per-job dedup + sor a request-ben

    def _start(self, job):
        symbol, strategy = job
        self._running.add(job)
        _opt_activity.set_state(symbol, strategy, _opt_activity.RUNNING,
                                f"Indul... ({strategy})")
        self.optimizer_status[symbol] = f"Indul... ({strategy})"
        threading.Thread(target=self._run_worker, args=(job,), daemon=True).start()

    def _run_worker(self, job):
        """HáttérSZÁL: adat-előkészítés (MT5, IO) → a CPU-nehéz optimalizálás
        külön PROCESSZBE. A fő (UI) szál egyiket sem érinti → nem fagy.
        `job` = (symbol, strategy) — per-stratégia optimalizálás."""
        symbol, strategy = job
        try:
            from ml.optimizer import optimize_job, params_file
            from trading.backtest import load_data
            from strategy import get_strategy_by_name
            job_strat = get_strategy_by_name(strategy)

            opt_cfg     = self.cfg["optimizer"]
            initial_bal = self.cfg.get("ml", {}).get("starting_balance_eur", 1000.0)

            # ⚠ TELJES TÉR: a kihagyás-lista csak EBBŐL a másolatból tűnik el —
            # a lemezen lévő config VÁLTOZATLAN. A felhasználó pipái beállítások,
            # nem egyszeri döntések: egy „mindent optimalizálj" futás nem
            # törölheti őket csendben.
            job_cfg = self.cfg
            if getattr(self, "_all_params", {}).get(job):
                import copy as _copy
                from core import opt_plan as _oplan
                job_cfg = _copy.deepcopy(self.cfg)
                _oplan.set_skip_keys(job_cfg, symbol, strategy, set())

            # ── Adat előkészítés (háttérszálon) — a KÖZÖS letöltő úton ────
            from tools.download_history import ensure_history

            def _st(msg):
                self.optimizer_status[symbol] = msg

            ok, msg = ensure_history(
                symbol, self.cfg,
                tuple(t.label for t in job_strat.timeframes()), status=_st)
            self.optimizer_status[symbol] = (
                _t("gui2.adat_kesz_optimalizalas") if ok else msg)

            df_m15, df_m1 = load_data(symbol)
            if df_m15 is None:
                self.optimizer_status[symbol] = f"Hiba: nincs adat — {msg}"
                self._log_error(symbol, _t("gui.opt.no_data", msg=msg))
                return

            # ── KÖZÖS dispatch: az optimize_job (→ optimize_symbol) dönt a
            #    módszerről (optuna|grid|random), szeletel, CSV-t ír és tesztel —
            #    PONTOSAN ugyanaz, mint a CLI-ben. A GUI csak a processzt/timeoutot/
            #    haladást intézi. A method-választás EGY helyen (optimize_symbol) él. ──
            self._ensure_pool()
            # "Nem halad" (stall) alapú védelem: NEM a teljes futásidőt limitáljuk
            # (ezek hosszú folyamatok!), hanem azt figyeljük, hogy jön-e haladás.
            # Ha stall_timeout_sec ideje NINCS előrelépés → tényleg beragadt → zárjuk.
            # hard_timeout_sec (0 = kikapcsolva) opcionális abszolút végső határ.
            stall_sec = opt_cfg.get("stall_timeout_sec", 900)   # 15 perc haladás nélkül
            hard_cap  = opt_cfg.get("hard_timeout_sec", 0)      # 0 = nincs abszolút limit
            self.optimizer_status[symbol] = _t("gui2.optimalizalas_indul")
            args = (symbol, df_m15, df_m1, job_cfg, initial_bal)

            if self._pool is not None:
                from concurrent.futures import TimeoutError as _FutTimeout
                t_submit = time.time()
                self._last_progress[symbol] = t_submit
                fut = self._pool.submit(optimize_job, *args, self._progress_q, strategy)
                while True:
                    try:
                        entry = fut.result(timeout=10)   # rövid poll
                        break
                    except _FutTimeout:
                        now  = time.time()
                        idle = now - self._last_progress.get(symbol, now)
                        if idle > stall_sec:
                            fut.cancel()
                            self._log_error(symbol,
                                _t("gui.opt.stuck_log", sec=int(idle), limit=stall_sec))
                            self.optimizer_status[symbol] = \
                                _t("gui.opt.stuck", min=int(idle // 60))
                            return   # a finally STOPPED-ra állít → UI nem ragad be
                        if hard_cap and (now - t_submit) > hard_cap:
                            fut.cancel()
                            self._log_error(symbol, _t("gui.opt.hard_cap", sec=hard_cap))
                            self.optimizer_status[symbol] = _t("gui2.hiba_abszolut_idolimit")
                            return
            else:
                entry = optimize_job(*args, _LocalProgress(self.optimizer_status), strategy)

            if "error" in entry:
                if entry.get("stopped"):
                    # User-cancel (STOP gomb) — nem hiba: rövid státusz, nincs log.
                    self.optimizer_status[symbol] = _t("gui2.megszakitva")
                    return
                self.optimizer_status[symbol] = f"Hiba: {entry['error']}"
                self._log_error(
                    symbol, entry.get("traceback") or _t("gui.opt.result_error", error=entry["error"]))
                return

            full = {
                "symbol":       symbol,
                "optimized_at": datetime.utcnow().isoformat(),
                **entry,
            }
            # rr-optimalizálás eredménye (ha volt): tisztán ne írjunk "rr": null-t;
            # ha van, a JSON-ba kerül ÉS a live per-pár állapotba (rr_state).
            _rr = full.get("rr")
            if not _rr:
                full.pop("rr", None)
            out = params_file(symbol, strategy)
            tmp = out.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(full, f, indent=2, ensure_ascii=False, default=str)
            tmp.replace(out)
            if _rr:
                from ml.optimizer import apply_optimized_rr
                apply_optimized_rr(symbol, _rr)

            # Sikeres: a pár azonnal "tanított" → Play aktiválható
            ds = self.dashboard_ref.get(symbol)
            if ds is not None:
                ds.trained = True
            # A frissen írt done-marker idejéből a perzisztens 'Utolsó opt: <dátum>'
            # címke — a MOST futtatott stratégia markeréből (pl. ml_ai tanítás).
            self.optimizer_status[symbol] = (opt_done_label(symbol, strategy)
                                             or OptStatus(_t("opt.done"), OPT_DONE))

        except Exception as e:
            import traceback
            self._log_error(symbol, traceback.format_exc())
            self.optimizer_status[symbol] = f"Hiba: {e}"
        finally:
            with self._lock:
                self._running.discard(job)
                # A tevékenység-jelölés törlése — CSAK ezé a stratégiáé. Az
                # `instrument_state`-et NEM állítjuk STOPPED-re: az a kereskedési
                # szándék, és az optimalizálásnak nincs joga eldobni. (Korábban ez
                # tette, ezért esett a pár Stopba minden optimalizálás végén.)
                _opt_activity.set_state(symbol, strategy, None)
                if not self._symbol_busy(symbol):
                    self._last_progress.pop(symbol, None)
                self._try_start_next()

    @staticmethod
    def _log_error(symbol: str, tb: str):
        import logging as _logging
        _logging.getLogger(__name__).error("OPT hiba [%s]:\n%s", symbol, tb)
        try:
            with open(ROOT / "data" / "opt_error.log", "a", encoding="utf-8") as _ef:
                _ef.write(f"\n{'='*60}\n{datetime.now()} [{symbol}]\n{tb}\n")
        except Exception:
            pass

    def _try_start_next(self):
        # A sorból az ELSŐ olyan tételt indítjuk, amelynek a szimbóluma épp NEM fut
        # (egy szimbólumon egyszerre egy stratégia optimalizál). A többi a sorban marad.
        while len(self._running) < self.max_parallel:
            nxt = next((j for j in self._queue
                        if not any(s == j[0] for s, _ in self._running)), None)
            if nxt is None:
                break
            self._queue.remove(nxt)
            self._start(nxt)


# ---------------------------------------------------------------------------
# Portfólió Backtest Tab  (változatlan logika)
# ---------------------------------------------------------------------------

class PortfolioBacktestTab:
    def __init__(self, parent: tk.Frame, cfg: dict,
                 mono_font, small_font, header_font):
        self.cfg        = cfg
        self.parent     = parent
        self._thread    = None
        self._stop_flag = threading.Event()
        self._progress  = {
            "running": False, "date": "—", "balance": 0.0,
            "n_open": 0, "n_closed": 0, "pct": 0.0,
            "result": None, "error": None,
        }
        self._equity_pts: list = []   # (date_str, balance)
        self._mono   = mono_font
        self._small  = small_font
        self._header = header_font

        self._build_ui()

    def _build_ui(self):
        p = self.parent
        p.configure(bg=BG_BT)

        top = tk.Frame(p, bg=BG_BT)
        top.pack(fill="x", padx=8, pady=6)

        ctrl = tk.Frame(top, bg=BG_BT)
        ctrl.pack(side="left", fill="y")

        # ── Stratégia-választó — a portfólió ezen a stratégián fut; a párlista is
        # ehhez igazodik (az adott stratégia optimalizált almappája). ──────────
        from strategy import available_strategy_names, default_strategy_name
        strat_row = tk.Frame(ctrl, bg=BG_BT)
        strat_row.pack(fill="x", pady=(0, 4))
        tk.Label(strat_row, text=_t("gui.strategia"), bg=BG_BT, fg=FG_BLUE,
                 font=self._header).pack(side="left")
        self._strat_var = tk.StringVar(value=default_strategy_name(self.cfg))
        _snames = available_strategy_names(self.cfg)
        self._strat_menu = tk.OptionMenu(strat_row, self._strat_var, *_snames,
                                         command=lambda _=None: self._reload_symbols())
        self._strat_menu.config(bg=BG_HEADER, fg=FG_WHITE, font=self._small,
                                relief="flat", highlightthickness=0,
                                activebackground=BG_HEADER)
        self._strat_menu["menu"].config(bg=BG_HEADER, fg=FG_WHITE)
        self._strat_menu.pack(side="left", padx=6)

        tk.Label(ctrl, text=_t("gui.instrumentumok_optimalizaltak"),
                 bg=BG_BT, fg=FG_BLUE, font=self._header).pack(anchor="w", pady=(2, 4))
        # A párlista dinamikusan újraépül a stratégiaváltásra.
        self._sym_frame = tk.Frame(ctrl, bg=BG_BT)
        self._sym_frame.pack(fill="x")
        self._sym_vars: dict = {}
        self._reload_symbols()

        # ── Űrlap: dátum / tőke / slotok / kockázatcsökkentés / építés / gombok ─
        form = tk.Frame(ctrl, bg=BG_BT)
        form.pack(fill="x", pady=(8, 0))

        tk.Label(form, text=_t("gui.tol"), bg=BG_BT, fg=FG_GRAY,
                 font=self._small).grid(row=0, column=0, sticky="e", pady=6)
        self._entry_from = tk.Entry(form, width=12, bg=BG_HEADER, fg=FG_WHITE,
                                    font=self._small, insertbackground=FG_WHITE)
        self._entry_from.insert(0, self.cfg.get("optimizer", {}).get(
            "test_start_date", "2025-10-01"))
        self._entry_from.grid(row=0, column=1, padx=4)

        tk.Label(form, text="Ig:", bg=BG_BT, fg=FG_GRAY,
                 font=self._small).grid(row=0, column=2, sticky="e")
        self._entry_to = tk.Entry(form, width=12, bg=BG_HEADER, fg=FG_WHITE,
                                  font=self._small, insertbackground=FG_WHITE)
        self._entry_to.insert(0, datetime.now().strftime("%Y-%m-%d"))
        self._entry_to.grid(row=0, column=3, padx=4)

        tk.Label(form, text=_t("gui.kezdo_toke"), bg=BG_BT, fg=FG_GRAY,
                 font=self._small).grid(row=1, column=0, sticky="e", pady=4)
        self._entry_bal = tk.Entry(form, width=10, bg=BG_HEADER, fg=FG_WHITE,
                                   font=self._small, insertbackground=FG_WHITE)
        self._entry_bal.insert(0, str(int(
            self.cfg.get("ml", {}).get("starting_balance_eur", 1000))))
        self._entry_bal.grid(row=1, column=1, padx=4)

        # Egyszerre nyitott (nem risk-free) pozíciók száma — alap: trading.max_open_slots.
        tk.Label(form, text="Slotok:", bg=BG_BT, fg=FG_GRAY,
                 font=self._small).grid(row=1, column=2, sticky="e", pady=4)
        self._entry_slots = tk.Entry(form, width=6, bg=BG_HEADER, fg=FG_WHITE,
                                     font=self._small, insertbackground=FG_WHITE)
        self._entry_slots.insert(0, str(int(
            self.cfg.get("trading", {}).get("max_open_slots", 4))))
        self._entry_slots.grid(row=1, column=3, padx=4, sticky="w")

        # Kockázatcsökkentés preset (MIND a párra) — a technikák összevetéséhez.
        tk.Label(form, text=_t("gui.kockazatcsokkentes"), bg=BG_BT, fg=FG_GRAY,
                 font=self._small).grid(row=2, column=0, sticky="e", pady=4)
        # ⚠ A legördülő FELIRATOKAT mutat, a döntés KÓDON megy. Amíg a kettő egy
        # volt, a preset-választás egy magyar szöveg megtalálásán múlt: angolul a
        # `.get()` `None`-t adott volna, tehát a backtest CSENDBEN a régi
        # („Auto") viselkedéssel futott volna — más eredménnyel, hibaüzenet nélkül.
        self._rr_choices = [(c, _t(f"rr.preset.{c}")) for c in
                            ("auto", "off", "risky", "halving", "shield",
                             "fibo", "thirds", "shield_fibo")]
        self._rr_var = tk.StringVar(value=self._rr_choices[0][1])
        self._rr_combo = ttk.Combobox(
            form, textvariable=self._rr_var, width=16, state="readonly",
            font=self._small,
            values=[lbl for _c, lbl in self._rr_choices])
        self._rr_combo.grid(row=2, column=1, padx=4, sticky="w")

        # Pozícióépítés (piramidális ráépítés a risk-free runnereken) ki/be.
        self._build_var = tk.BooleanVar(value=False)
        tk.Checkbutton(form, text=_t("gui.pozicioepites"), variable=self._build_var,
                       bg=BG_BT, fg=FG_WHITE, selectcolor=BG_HEADER,
                       activebackground=BG_BT, activeforeground=FG_WHITE,
                       font=self._small).grid(row=2, column=2, columnspan=2,
                                              sticky="w", padx=4)

        # Reális végrehajtási kapuk (TF-együttállás + spread), mint élesben. Alap BE →
        # a portfólió sem nyit olyat, amit egy él-oldali kapu kiszűrne. Per-pár config
        # tiszteletben (ha egy párra ki van kapcsolva az Együtt, arra nem kapuz).
        self._pf_exec_gates_var = tk.BooleanVar(value=True)
        tk.Checkbutton(form, text=_t("gui.realis_kapuk_tf_spread"),
                       variable=self._pf_exec_gates_var,
                       bg=BG_BT, fg=FG_WHITE, selectcolor=BG_HEADER,
                       activebackground=BG_BT, activeforeground=FG_WHITE,
                       font=self._small).grid(row=3, column=2, columnspan=2,
                                              sticky="w", padx=4)

        self._btn_start = tk.Button(form, text=_t("gui.backtest_inditasa"), width=20,
                                    bg=BTN_BT_BG, fg=BTN_BT_FG, font=self._small,
                                    relief="flat", command=self._start_bt)
        self._btn_start.grid(row=3, column=0, columnspan=2, pady=8, sticky="w")

        self._btn_stop_bt = tk.Button(form, text=_t("gui.leallitas2"), width=12,
                                      bg=BTN_DIS_BG, fg=BTN_DIS_FG, font=self._small,
                                      relief="flat", command=self._stop_bt,
                                      state="disabled")
        self._btn_stop_bt.grid(row=3, column=2, columnspan=2, pady=8, sticky="w")

        right = tk.Frame(top, bg=BG_BT)
        right.pack(side="left", fill="both", expand=True, padx=(20, 0))

        prog_frame = tk.Frame(right, bg=BG_BT)
        prog_frame.pack(fill="x")

        self._lbl_status  = tk.Label(prog_frame, text=_t("bt.done"), bg=BG_BT,
                                     fg=FG_GRAY, font=self._small)
        self._lbl_status.grid(row=0, column=0, sticky="w")
        self._lbl_date    = tk.Label(prog_frame, text=_t("gui.datum"), bg=BG_BT,
                                     fg=FG_WHITE, font=self._mono)
        self._lbl_date.grid(row=1, column=0, sticky="w")
        self._lbl_bal     = tk.Label(prog_frame, text="Egyenleg: —", bg=BG_BT,
                                     fg=FG_WHITE, font=self._mono)
        self._lbl_bal.grid(row=1, column=1, sticky="w", padx=16)
        self._lbl_pnl     = tk.Label(prog_frame, text="P&L: —", bg=BG_BT,
                                     fg=FG_WHITE, font=self._mono)
        self._lbl_pnl.grid(row=1, column=2, sticky="w", padx=8)
        self._lbl_trades  = tk.Label(prog_frame, text=_t("gui.lezart_0_nyitott_0"),
                                     bg=BG_BT, fg=FG_GRAY, font=self._small)
        self._lbl_trades.grid(row=2, column=0, columnspan=2, sticky="w")

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("BT.Horizontal.TProgressbar",
                        troughcolor=BG_HEADER, background=BTN_BT_BG, thickness=8)
        self._progressbar = ttk.Progressbar(right, style="BT.Horizontal.TProgressbar",
                                            orient="horizontal", length=400,
                                            mode="determinate", maximum=100)
        self._progressbar.pack(fill="x", pady=(4, 6))

        tk.Label(right, text=_t("gui.equity_gorbe"), bg=BG_BT, fg=FG_GRAY,
                 font=self._small).pack(anchor="w")
        self._canvas = tk.Canvas(right, height=140, bg=CANVAS_BG, highlightthickness=0)
        self._canvas.pack(fill="x", pady=(0, 6))

        tk.Frame(p, bg=FG_GRAY_DIM, height=1).pack(fill="x", padx=4, pady=2)

        tk.Label(p, text=_t("gui.eredmenyek"), bg=BG_BT, fg=FG_BLUE,
                 font=self._header).pack(anchor="w", padx=8, pady=(4, 0))

        res_frame = tk.Frame(p, bg=BG_BT)
        res_frame.pack(fill="both", expand=True, padx=8, pady=4)

        res_header = tk.Frame(res_frame, bg=BG_HEADER)
        res_header.pack(fill="x")
        for col, w in [(_t("gui2.par"), 10), ("Trade", 6), ("Win%", 7),
                       ("P&L$", 9), ("MaxDD%", 7), ("PF", 6), (_t("gui2.vegegyenleg"), 12)]:
            tk.Label(res_header, text=col, width=w, anchor="center",
                     bg=BG_HEADER, fg=FG_BLUE, font=self._small,
                     padx=4, pady=3).pack(side="left")

        tk.Frame(res_frame, bg=FG_GRAY_DIM, height=1).pack(fill="x")

        self._res_rows_frame = tk.Frame(res_frame, bg=BG_BT)
        self._res_rows_frame.pack(fill="both", expand=True)

        self._lbl_res_total = tk.Label(p, text="", bg=BG_BT,
                                       fg=FG_YELLOW, font=self._mono)
        self._lbl_res_total.pack(anchor="w", padx=8, pady=4)

    def _reload_symbols(self):
        """A párlista (jelölőnégyzetek) újraépítése a választott stratégia
        optimalizált almappájából (stratégiaváltáskor és induláskor)."""
        from core.params_store import strategy_dir
        for w in self._sym_frame.winfo_children():
            w.destroy()
        self._sym_vars = {}
        strat_name = getattr(self, "_strat_var", None)
        params_dir = strategy_dir(strat_name.get() if strat_name else None)
        # A *_hours.json a kereskedési-óra fájl, NEM optimalizált param — kiszűrjük
        # (ilyet kiválasztva a portfólió-backtest elszállna a hiányzó params miatt).
        # FONTOS: CSAK a jelenleg a configban SZEREPLŐ párokat listázzuk. Az
        # optimized_params/ mappában bróker-váltás/törlés után is ott maradhatnak régi
        # fájlok (pl. XAUUSD a régi arany-névvel) — ezek „szellemként" jelentek meg a
        # listában, holott már nem léteznek. A metszet a config-párokkal ezt megszünteti.
        _pairs = set(self.cfg.get("pairs", {}))
        optimized  = sorted([f.stem for f in params_dir.glob("*.json")
                             if not f.stem.endswith("_hours") and f.stem in _pairs]) \
                     if params_dir.exists() else []
        if not optimized:
            tk.Label(self._sym_frame, text=_t("gui.nincs_optimalizalt_instrumentum"),
                     bg=BG_BT, fg=FG_GRAY, font=self._small).grid(
                         row=0, column=0, columnspan=4, sticky="w")
            return
        cols = 4
        for i, sym in enumerate(optimized):
            var = tk.BooleanVar(value=True)
            self._sym_vars[sym] = var
            tk.Checkbutton(self._sym_frame, text=sym, variable=var,
                           bg=BG_BT, fg=FG_WHITE, selectcolor=BG_HEADER,
                           activebackground=BG_BT, activeforeground=FG_WHITE,
                           font=self._small).grid(row=i // cols, column=i % cols,
                                                  sticky="w", padx=6)

    def _start_bt(self):
        if self._thread and self._thread.is_alive():
            return
        symbols = [s for s, v in self._sym_vars.items() if v.get()]
        if not symbols:
            self._lbl_status.config(text=_t("gui.valassz_legalabb_egy_instrumentumot"), fg=FG_RED)
            return
        date_from = self._entry_from.get().strip()
        date_to   = self._entry_to.get().strip()
        try:
            init_bal = float(self._entry_bal.get().strip())
        except ValueError:
            init_bal = 1000.0
        try:
            n_slots = max(1, int(self._entry_slots.get().strip()))
        except ValueError:
            n_slots = None          # → a config max_open_slots
        build_on   = self._build_var.get()
        strat_name = self._strat_var.get()
        exec_gates = bool(self._pf_exec_gates_var.get())

        self._stop_flag.clear()
        self._equity_pts = []
        self._clear_results()
        self._draw_equity([])

        self._btn_start.config(state="disabled", bg=BTN_DIS_BG, fg=BTN_DIS_FG)
        self._btn_stop_bt.config(state="normal", bg=BTN_STOP_BG, fg=BTN_STOP_FG)
        self._progressbar["value"] = 0
        self._lbl_status.config(text=_t("gui.pbt.running", n=len(symbols)), fg=FG_YELLOW)

        self._thread = threading.Thread(
            target=self._run_thread,
            args=(symbols, date_from, date_to, init_bal, self._rr_spec(),
                  strat_name, n_slots, build_on, exec_gates),
            daemon=True,
        )
        self._thread.start()
        self.parent.after(200, self._poll_progress)

    def _stop_bt(self):
        self._stop_flag.set()
        self._lbl_status.config(text=_t("gui.leallitas"), fg=FG_ORANGE)

    def _rr_spec(self):
        """A választott preset → kockázatcsökkentő spec (mind a párra), vagy None
        ('Auto' = a per-pár auto-risky, a jelenlegi viselkedés)."""
        from core import risk_reduction as _rr
        _code = next((c for c, lbl in self._rr_choices
                      if lbl == self._rr_var.get()), "auto")
        preset = {"off": _rr.PRESET_OFF, "risky": _rr.PRESET_RISKY,
                  "halving": _rr.PRESET_HALVING,
                  "shield": _rr.PRESET_SHIELD,
                  "fibo": _rr.PRESET_FIBO,
                  "thirds": _rr.PRESET_THIRDS,
                  "shield_fibo": _rr.PRESET_SHIELD_FIBO}.get(_code)
        if preset is None:          # "auto" — a per-pár auto-risky marad
            return None
        return {**_rr.default_config(), "preset": preset}

    def _run_thread(self, symbols, date_from, date_to, init_bal, rr_spec=None,
                    strat_name=None, n_slots=None, build_on=False, exec_gates=False):
        from trading.backtest import run_portfolio_backtest, _save_backtest_results

        def on_progress(date_str, balance, n_open, n_closed, pct):
            self._progress.update({
                "running": True, "date": date_str, "balance": balance,
                "n_open": n_open, "n_closed": n_closed, "pct": pct,
            })
            self._equity_pts.append((date_str, balance))

        try:
            result = run_portfolio_backtest(
                self.cfg, symbols, date_from, date_to,
                initial_balance=init_bal,
                progress_callback=on_progress,
                stop_flag=self._stop_flag,
                rr=rr_spec,
                strategy_name=strat_name,
                max_slots=n_slots,
                build=build_on,
                exec_gates=exec_gates,
            )
            if result.get("trades"):
                _save_backtest_results(
                    result["trades"],
                    list(result.get("per_pair", {}).values()),
                    init_bal, date_from,
                )
            self._progress["result"] = result
            self._progress["running"] = False
        except Exception as e:
            self._progress["error"]   = str(e)
            self._progress["running"] = False

    def _poll_progress(self):
        prog = self._progress
        if prog.get("running") or (self._thread and self._thread.is_alive()):
            date_str  = prog.get("date", "—")
            balance   = prog.get("balance", 0.0)
            init_bal  = float(self._entry_bal.get().strip() or 1000)
            pnl       = balance - init_bal
            pnl_pct   = pnl / init_bal * 100 if init_bal else 0
            n_open    = prog.get("n_open", 0)
            n_closed  = prog.get("n_closed", 0)
            pct       = prog.get("pct", 0.0)

            self._lbl_date.config(text=_t("gui.pbt.date", date=date_str))
            self._lbl_bal.config(text=f"Egyenleg: ${balance:,.2f}")
            pnl_fg = FG_GREEN if pnl >= 0 else FG_RED
            self._lbl_pnl.config(text=f"P&L: {pnl:+.2f}$ ({pnl_pct:+.1f}%)", fg=pnl_fg)
            self._lbl_trades.config(text=_t("gui.pbt.counts", closed=n_closed, open=n_open))
            self._progressbar["value"] = pct

            self._draw_equity(self._equity_pts, init_bal)
            self.parent.after(300, self._poll_progress)
        else:
            self._progressbar["value"] = 100
            self._btn_start.config(state="normal", bg=BTN_BT_BG, fg=BTN_BT_FG)
            self._btn_stop_bt.config(state="disabled", bg=BTN_DIS_BG, fg=BTN_DIS_FG)

            err = prog.get("error")
            result = prog.get("result")
            if err:
                self._lbl_status.config(text=f"Hiba: {err}", fg=FG_RED)
            elif result:
                n = len(result.get("trades", []))
                init_bal = result.get("initial_balance", 1000)
                final    = result.get("final_balance", init_bal)
                pnl      = final - init_bal
                self._lbl_status.config(
                    text=_t("gui.pbt.done", n=n, pnl=_fmtnum(f"{pnl:+.2f}"),
                        pct=_fmtnum(f"{pnl / init_bal * 100:+.1f}")),
                    fg=FG_GREEN if pnl >= 0 else FG_RED)
                self._show_results(result)
                self._draw_equity(result.get("equity_curve", []), init_bal)
            else:
                self._lbl_status.config(text=_t("gui.leallitva"), fg=FG_GRAY)

    def _draw_equity(self, points: list, init_bal: float = 1000.0):
        c = self._canvas
        c.delete("all")
        w = c.winfo_width() or 500
        h = c.winfo_height() or 140
        pad = 8
        if not points or len(points) < 2:
            c.create_text(w // 2, h // 2, text="Nincs adat", fill=FG_GRAY,
                          font=_theme.fonts()["mono"])
            return
        balances = [b for _, b in points]
        mn = min(balances + [init_bal])
        mx = max(balances + [init_bal])
        rng = mx - mn or 1

        def px(i):
            return pad + (i / (len(points) - 1)) * (w - 2 * pad)
        def py(b):
            return h - pad - ((b - mn) / rng) * (h - 2 * pad)

        ref_y = py(init_bal)
        c.create_line(pad, ref_y, w - pad, ref_y, fill=CANVAS_REF, dash=(4, 4), width=1)

        coords = []
        for i, (_, b) in enumerate(points):
            coords += [px(i), py(b)]
        if len(coords) >= 4:
            final_bal = balances[-1]
            col = CANVAS_LINE if final_bal >= init_bal else FG_RED
            c.create_line(*coords, fill=col, width=2, smooth=True)

        c.create_text(pad + 2, h - pad - 2, text=f"${mn:.0f}", fill=FG_GRAY,
                      font=_theme.fonts()["tiny"], anchor="sw")
        c.create_text(pad + 2, pad + 2, text=f"${mx:.0f}", fill=FG_GRAY,
                      font=_theme.fonts()["tiny"], anchor="nw")
        if points:
            c.create_text(w - pad, h - pad - 2, text=str(points[-1][0])[:7],
                          fill=FG_GRAY, font=_theme.fonts()["tiny"], anchor="se")
            c.create_text(pad, h - pad - 2, text=str(points[0][0])[:7],
                          fill=FG_GRAY, font=_theme.fonts()["tiny"], anchor="sw")

    def _clear_results(self):
        for w in self._res_rows_frame.winfo_children():
            w.destroy()
        self._lbl_res_total.config(text="")

    def _show_results(self, result: dict):
        self._clear_results()
        per_pair  = result.get("per_pair", {})
        init_bal  = result.get("initial_balance", 1000.0)
        final_bal = result.get("final_balance", init_bal)

        all_trades = result.get("trades", [])
        from collections import defaultdict
        by_sym = defaultdict(list)
        for t in all_trades:
            by_sym[t.symbol].append(t)

        row_idx = 0
        for sym in sorted(per_pair, key=lambda s: -per_pair[s].get("total_pnl", 0)):
            s   = per_pair[sym]
            pnl = s.get("total_pnl", 0)
            pf  = s.get("profit_factor", 0)
            pf_str = f"{min(pf, 99):.2f}" if pf != float("inf") else "∞"
            sym_final = init_bal + pnl

            is_risky = s.get("risky", False)

            bg = BG_ROW_ODD if row_idx % 2 == 0 else BG_ROW_EVEN
            fr = tk.Frame(self._res_rows_frame, bg=bg)
            fr.pack(fill="x")
            vals = [
                (f"{sym} ⚠R" if is_risky else sym, 10, FG_ORANGE if is_risky else FG_WHITE),
                (str(s.get("trades", 0)),         6, FG_WHITE),
                (f"{s.get('win_rate',0):.0%}",    7, FG_GREEN if s.get('win_rate',0) >= 0.5 else FG_RED),
                (f"{pnl:+.2f}",                   9, FG_GREEN if pnl >= 0 else FG_RED),
                (f"{s.get('max_drawdown',0)*100:.1f}%", 7, FG_YELLOW),
                (pf_str,                           6, FG_WHITE),
                (f"${sym_final:.0f}",             12, FG_GREEN if sym_final >= init_bal else FG_RED),
            ]
            for txt, w, fg in vals:
                tk.Label(fr, text=txt, width=w, anchor="center",
                         bg=bg, fg=fg, font=self._small, padx=4, pady=2).pack(side="left")
            row_idx += 1

        total_pnl = final_bal - init_bal
        n_all  = len(all_trades)
        n_wins = sum(1 for t in all_trades if t.pnl_usd > 0)
        wr_all = n_wins / max(n_all, 1)

        eq = init_bal; peak = eq; mdd = 0.0
        for t in sorted(all_trades, key=lambda x: x.close_time or x.open_time):
            eq += t.pnl_usd
            if eq > peak: peak = eq
            dd = (peak - eq) / peak * 100
            if dd > mdd: mdd = dd

        win_sum  = sum(t.pnl_usd for t in all_trades if t.pnl_usd > 0)
        loss_sum = sum(t.pnl_usd for t in all_trades if t.pnl_usd < 0)
        pf_all   = abs(win_sum / loss_sum) if loss_sum != 0 else float("inf")
        pf_str   = f"{min(pf_all, 99):.2f}" if pf_all != float("inf") else "∞"

        risky_pairs = result.get("risky_pairs", [])
        risky_note  = (f"   ·   ⚠R risky ({len(risky_pairs)}): {', '.join(risky_pairs)}"
                       if risky_pairs else "")
        self._lbl_res_total.config(
            text=_t("gui.pbt.total", trades=n_all, win=f"{wr_all:.0%}",
                 pnl=_fmtnum(f"{total_pnl:+.2f}"), mdd=_fmtnum(f"{mdd:.1f}"),
                 pf=pf_str, final=_fmtnum(f"{final_bal:.0f}"), note=risky_note),
            fg=FG_GREEN if total_pnl >= 0 else FG_RED,
        )


# ---------------------------------------------------------------------------
# Pozíciók fül — nyitott pozíciók kezelése
# ---------------------------------------------------------------------------

POSITION_COLUMNS = [
    ("symbol",  "Symbol",     10, "w"),
    ("strategy",_t("signals.col.strategy"),   9, "center"),
    ("exit",    _t("gui2.kiszallas"),  18, "w"),        # a kiszállási terv: hol tart + mi jön
    ("type",    _t("signals.col.dir"),       6, "center"),
    ("volume",  "Lot",         6, "center"),
    ("open",    _t("gui2.nyito"),      10, "center"),
    ("current", "Akt.",       10, "center"),
    ("sl",      "SL",         10, "center"),
    ("sl_pnl",  "SL P&L",     12, "center"),   # ha az SL bekövetkezik: R + $
    ("tp",      "TP",         10, "center"),
    ("tp_pnl",  _t("gui2.tp_cel"),     12, "center"),   # a TP-nél várható eredmény: R + $
    ("orig_sl", "Er. SL",     10, "center"),
    ("pnl",     "P&L",        13, "center"),   # folyó eredmény: $ + R (egy cellában)
]


def _exit_plan(symbol: str, pstate: dict | None, ctx: dict | None = None) -> dict:
    """A pozíció KISZÁLLÁSI TERVE — HOL TART most és MI TÖRTÉNIK a következő
    triggernél (mennyit zár, mivel megy tovább).

    A pozíció sorsát a `rr_state` preset dönti el (nem a Pozíciók fül gombjai). Ez
    a helper egy helyen fejti meg az egészet, így a Kiszállás-oszlop szövege, a
    Trail gomb állapota és a részletes tooltip mind ugyanabból a forrásból jön.

    ctx (opcionális, a soron kiszámolt számok — enélkül csak a preset-terv, „hol
    tart" nélkül):  cur_r, risk_price, risk_usd, entry, cur, tp, dir_s, be_pct.

    Visszaad:
      text/color : a Kiszállás-cella (rövid: fázis + következő lépés);
      trails     : trailel-e a preset (a motor `_do_trailing`-jének kijelzés-mása);
      tooltip    : a teljes életciklus (trigger, hány %-ot zár, mivel megy tovább,
                   most hol tart)."""
    from core import rr_state as _rrs
    from core import risk_reduction as _rrx

    try:
        preset  = _rrs.effective_preset(symbol)
        runner  = (pstate or {}).get("runner_mode") or _rrs.get_runner(symbol)
        cost_cut = _rrs.get_cost_cut(symbol)
        cc_bars  = _rrs.get_cost_cut_bars(symbol)
        spec     = _rrs.spec_for(symbol)
        exind    = (spec.get("exit") or {}).get("indicator", "supertrend")
    except Exception:
        preset, runner, cost_cut, cc_bars = "off", "trailing", False, 12
        spec, exind = {}, "supertrend"

    ps = pstate or {}
    ctx = ctx or {}
    cur_r   = ctx.get("cur_r")
    risk    = ctx.get("risk_price") or 0.0
    risk_usd = ctx.get("risk_usd")
    entry   = ctx.get("entry"); cur = ctx.get("cur"); tp = ctx.get("tp")
    dir_s   = ctx.get("dir_s", 1)
    be_pct  = ctx.get("be_pct", 0.5)

    _IND = {"supertrend": "ST", "wpr": "WPR", "divergence": "Div"}
    _RUNNER_DESC = {
        _rrx.RUNNER_TRAILING: _t("gui2.a_maradek_trailinggel_fut"),
        _rrx.RUNNER_KEEP:     _t("gui2.a_stop_a_tavoli"),
        _rrx.RUNNER_BREAKEVEN: _t("gui2.a_stop_a_belepore"),
        _rrx.RUNNER_EXIT:     _t("gui.exit.on_signal", indicator=_IND.get(exind, exind)),
    }
    _RUNSH = {_rrx.RUNNER_TRAILING: "Trail", _rrx.RUNNER_KEEP: "Marad",
              _rrx.RUNNER_BREAKEVEN: "BE",
              _rrx.RUNNER_EXIT: f"Jel({_IND.get(exind, exind)})"}
    runsh    = _RUNSH.get(runner, runner)
    run_desc = _RUNNER_DESC.get(runner, runner)

    def r_to(target):
        """Hány R kell még, hogy az ár elérje a `target` árszintet (profit-irány)."""
        if not target or risk <= 0 or cur is None:
            return None
        return (target - cur) / risk * dir_s

    def usd(frac):
        """A pozíció `frac` részének realizált $-a a triggernél (≈ frac × 1R $)."""
        return (frac * risk_usd) if risk_usd else None

    def prog(rem):
        return (f" Most {cur_r:+.2f}R, a triggerig +{rem:.2f}R."
                if (cur_r is not None and rem is not None and rem > 0) else
                (f" Most {cur_r:+.2f}R." if cur_r is not None else ""))

    # Pajzs↔Fibo: a hatásos ág pozíciónként dől el (a motor pstate-be cache-eli)
    eff, undecided_sf = preset, False
    if preset == _rrx.PRESET_SHIELD_FIBO:
        _m = ps.get("sf_mode")
        if _m in (_rrx.PRESET_SHIELD, _rrx.PRESET_FIBO):
            eff = _m
        else:
            undecided_sf = True
    is_fibo   = eff == _rrx.PRESET_FIBO
    is_thirds = eff == _rrx.PRESET_THIRDS
    is_partial = eff in (_rrx.PRESET_HALVING, _rrx.PRESET_SHIELD)

    # Trailel-e a preset? (a is_rf/enabled kaput a hívó adja hozzá)
    if undecided_sf:
        trails = (runner == _rrx.RUNNER_TRAILING)
    else:
        trails = (not is_fibo) and (not is_thirds) and \
                 (not is_partial or runner == _rrx.RUNNER_TRAILING)

    reduced   = bool(ps.get("rr_reduced"))
    be_done   = bool(ps.get("be_done"))

    # ── Fázis-tudatos szöveg + tooltip presetenként ─────────────────────────
    if eff == _rrx.PRESET_OFF:
        color = FG_GRAY
        be_price = (entry + be_pct * (tp - entry)) if (entry and tp) else None
        if not be_done:
            rem = r_to(be_price)
            text = "Ki →BE"
            tip = (_t("gui.exit.be_trail", pct=f"{be_pct * 100:.0f}") + prog(rem))
        else:
            text = "Ki: Trail fut"
            tip = _t("gui2.a_be_megvolt_a")
    elif eff == _rrx.PRESET_RISKY:
        color = FG_ORANGE
        rem = (1.0 - cur_r) if cur_r is not None else None
        if not be_done:
            text = "Risky →1R"
            tip = (_t("gui2.risky_felezett_belepo_meret") + prog(rem))
        else:
            text = "Risky: Trail fut"
            tip = _t("gui2.1r_megvolt_a_stop")
    elif is_partial:
        frac = 0.75 if eff == _rrx.PRESET_SHIELD else 0.5
        pname = "Pajzs" if eff == _rrx.PRESET_SHIELD else _t("tech.halving")
        color = FG_TEAL if runner == _rrx.RUNNER_EXIT else FG_CYAN
        if not reduced:
            rem = (1.0 - cur_r) if cur_r is not None else None
            text = f"{pname} →1R {frac*100:.0f}%"
            _u = usd(frac)
            _ur = _t("gui.exit.realise", amount=_fmtnum(f"{_u:.0f}")) if _u is not None else ""
            tip = (_t("gui.exit.partial_plan", preset=pname, pct=f"{frac * 100:.0f}",
                   realise=_ur, rest=f"{(1 - frac) * 100:.0f}", desc=run_desc) + prog(rem))
        else:
            text = f"{pname}✓ →{runsh}"
            tip = (_t("gui.exit.partial_done", pct=f"{frac * 100:.0f}",
                   runner=_rrs.RUNNER_NAME.get(runner, runner), desc=run_desc))
    elif is_fibo:
        color = FG_PURPLE
        lvl = spec.get("fibo_level", 0.618)
        stop_lvl = spec.get("fibo_stop_level", 0.0)
        stop_desc = "BE" if abs(stop_lvl) < 1e-9 else f"{stop_lvl*100:.0f}%"
        trig_price = (entry + lvl * (tp - entry)) if (entry and tp) else None
        if not ps.get("rr_fibo_done"):
            rem = r_to(trig_price)
            text = f"Fibo →{lvl*100:.0f}% ⇒{stop_desc}"
            tip = (_t("gui.exit.fibo", pct=f"{lvl * 100:.0f}", stop=stop_desc) + prog(rem))
        else:
            text = "Fibo ✓ · TP fut"
            tip = _t("gui2.a_fibo_stop_beallt")
    elif is_thirds:
        color = FG_PURPLE
        if not ps.get("rr_thirds1"):
            rem = (1.0 - cur_r) if cur_r is not None else None
            text = "Harmados →1R ⅓"
            tip = (_t("gui2.harmados_1r_nel_a") + prog(rem))
        elif not ps.get("rr_thirds2"):
            text = "Harmados ⅓ →TP ⅔"
            tip = _t("gui2.az_1_3_stop")
        else:
            text = "Harmados ⅔ · TP fut"
            tip = _t("gui2.a_2_3_stop")
    elif undecided_sf:
        color = FG_CYAN
        text = "Pajzs↔Fibo ?"
        tip = (_t("gui2.pajzs_fibo_belepeskor_dol"))
    else:
        color, text, tip = FG_GRAY, str(preset), ""

    if cost_cut:
        text += " +CC"
        tip += _t("gui.exit.costcut", bars=cc_bars)

    return {"text": text, "color": color, "trails": trails, "tooltip": tip}


class PositionRow:
    def __init__(self, parent, ticket, mono_font, small_font,
                 on_be, on_trail, on_panic, on_name_click, on_trail_dist,
                 on_build=None, on_build_mode=None, on_strategy_click=None,
                 on_exit_click=None):
        self.ticket = ticket
        self._small = small_font
        self._symbol = None
        self._on_name_click = on_name_click
        self._on_trail_dist = on_trail_dist
        self._on_build_mode = on_build_mode
        self._on_strategy_click = on_strategy_click
        self.frame = tk.Frame(parent, bg=BG_ROW_EVEN)
        self.labels = {}
        for key, hdr, w, anchor in POSITION_COLUMNS:
            lbl = tk.Label(self.frame, text="—", width=w, anchor=anchor,
                           bg=BG_ROW_EVEN, fg=FG_WHITE, font=mono_font, padx=4, pady=2)
            lbl.pack(side="left")
            self.labels[key] = lbl
        # Symbol cellára kattintva → optimalizált paraméterek (mint a Live fülön)
        self.labels["symbol"].config(cursor="hand2")
        self.labels["symbol"].bind(
            "<Button-1>",
            lambda e: self._symbol and self._on_name_click(self._symbol))
        # Stratégia-cella: KATTINTHATÓ — kézzel nyitott pozíciót itt lehet
        # stratégiához rendelni (a motor onnantól sajátjaként kezeli), illetve
        # a hozzárendelést visszavonni.
        if on_strategy_click is not None:
            self.labels["strategy"].config(cursor="hand2")
            self.labels["strategy"].bind(
                "<Button-1>",
                lambda e: self._symbol and on_strategy_click(
                    self.ticket, self._symbol, e.widget))
        # Kiszállás-cella: KATTINTHATÓ (a preset állítása) + HOVER-tooltip (a teljes
        # életciklus: trigger, hány %-ot zár, mivel megy tovább, most hol tart).
        self._exit_tip_text = ""
        self._exit_tip = None
        self.labels["exit"].bind("<Enter>", self._exit_tip_show)
        self.labels["exit"].bind("<Leave>", self._exit_tip_hide)
        if on_exit_click is not None:
            self.labels["exit"].config(cursor="hand2")
            self.labels["exit"].bind(
                "<Button-1>",
                lambda e: self._symbol and on_exit_click(self._symbol, e.widget))
        self.btn_be = tk.Button(self.frame, text="BE", width=4, font=small_font,
                                relief="flat", bg=BTN_OPT_BG, fg=BTN_OPT_FG,
                                command=lambda: on_be(ticket))
        self.btn_be.pack(side="left", padx=1)
        # A BE-gomb tiltva, ha a profit még nem fedezi a költséget → tooltip mondja meg
        self._be_tip_text = ""
        self._be_tip = None
        self.btn_be.bind("<Enter>", self._be_tip_show)
        self.btn_be.bind("<Leave>", self._be_tip_hide)
        # Építés MÓD-váltó (Ki/Kézi/Auto) — per SZIMBÓLUM (a soron állítható, nem kell
        # az instrumentum-ablak). Kattintásra körben vált; a szín jelzi az állapotot.
        self.btn_bmode = tk.Button(self.frame, text=_t("gui.ep"), width=7, font=small_font,
                                   relief="flat", bg=BTN_DIS_BG, fg=FG_GRAY,
                                   command=(lambda: self._symbol and on_build_mode(self._symbol))
                                           if on_build_mode else None)
        self.btn_bmode.pack(side="left", padx=1)
        # „＋" pozícióépítés (ráépítés): csak akkor aktív, ha az építés-mód Kézi és a
        # gyertyás jel szól (a pozíció kockázatmentes). Tooltip mondja meg az okot.
        self.btn_build = tk.Button(self.frame, text="＋", width=2, font=small_font,
                                   relief="flat", bg=BTN_DIS_BG, fg=FG_GRAY,
                                   state="disabled",
                                   command=(lambda: on_build(ticket)) if on_build else None)
        self.btn_build.pack(side="left", padx=1)
        self._build_tip_text = ""
        self._build_tip = None
        self.btn_build.bind("<Enter>", self._build_tip_show)
        self.btn_build.bind("<Leave>", self._build_tip_hide)
        self.btn_trail = tk.Button(self.frame, text="Trail", width=5, font=small_font,
                                   relief="flat", bg=BTN_DIS_BG, fg=FG_GRAY,
                                   command=lambda: on_trail(ticket))
        self.btn_trail.pack(side="left", padx=1)
        # A Trail gomb ÉS a táv-mező közös tooltipje: mikor húz a trailing.
        self._trail_tip_text = ""
        self._trail_tip = None
        self.btn_trail.bind("<Enter>", self._trail_tip_show)
        self.btn_trail.bind("<Leave>", self._trail_tip_hide)
        # Trail távolság (pont) — kézzel szerkeszthető; Enter/fókuszvesztés menti
        self._trail_var = tk.StringVar()
        self.ent_trail = tk.Entry(self.frame, textvariable=self._trail_var, width=4,
                                  font=small_font, bg=BG_HEADER, fg=FG_WHITE,
                                  insertbackground=FG_WHITE, relief="flat",
                                  justify="center")
        self.ent_trail.pack(side="left", padx=1)
        self.ent_trail.bind("<Return>",   self._apply_trail_dist)
        self.ent_trail.bind("<FocusOut>", self._apply_trail_dist)
        # A táv R/$ ekvivalense a HOVER-tooltipben (inline elférne, de a keskeny
        # vezérlő-sávban levágódott) — a mezőre/gombra állva látszik.
        self.ent_trail.bind("<Enter>", self._trail_tip_show)
        self.ent_trail.bind("<Leave>", self._trail_tip_hide)
        self.btn_panic = tk.Button(self.frame, text=_t("gui.zar"), width=4, font=small_font,
                                   relief="flat", bg=BTN_STOP_BG, fg=BTN_STOP_FG,
                                   command=lambda: on_panic(ticket))
        self.btn_panic.pack(side="left", padx=(1, 4))

    def _apply_trail_dist(self, _event=None):
        # PONT, egész szám (tizedes nélkül). Toleráns beolvasás, de egészre kerekít.
        raw = self._trail_var.get().strip().replace(",", ".")
        try:
            val = int(round(float(raw)))
        except ValueError:
            return
        if val > 0:
            self._on_trail_dist(self.ticket, val)

    # ── BE-gomb tooltip (miért tiltott: a profit nem fedezi a költséget) ──────
    def _be_tip_show(self, _event=None):
        text = (self._be_tip_text or "").strip()
        if not text or self._be_tip is not None:
            return
        tip = tk.Toplevel(self.btn_be)
        tip.wm_overrideredirect(True)
        tip.attributes("-topmost", True)
        x = self.btn_be.winfo_rootx()
        y = self.btn_be.winfo_rooty() + self.btn_be.winfo_height() + 2
        tk.Label(tip, text=text, bg=TOOLTIP_BG, fg=TOOLTIP_FG, font=self._small,
                 padx=6, pady=3, relief="solid", bd=1, justify="left",
                 wraplength=320).pack()
        tip.wm_geometry(f"+{x}+{y}")
        self._be_tip = tip

    def _be_tip_hide(self, _event=None):
        if self._be_tip is not None:
            try:
                self._be_tip.destroy()
            except Exception:
                pass
            self._be_tip = None

    def _build_tip_show(self, _event=None):
        text = (self._build_tip_text or "").strip()
        if not text or self._build_tip is not None:
            return
        tip = tk.Toplevel(self.btn_build)
        tip.wm_overrideredirect(True)
        tip.attributes("-topmost", True)
        x = self.btn_build.winfo_rootx()
        y = self.btn_build.winfo_rooty() + self.btn_build.winfo_height() + 2
        tk.Label(tip, text=text, bg=TOOLTIP_BG, fg=TOOLTIP_FG, font=self._small,
                 padx=6, pady=3, relief="solid", bd=1, justify="left",
                 wraplength=320).pack()
        tip.wm_geometry(f"+{x}+{y}")
        self._build_tip = tip

    def _build_tip_hide(self, _event=None):
        if self._build_tip is not None:
            try:
                self._build_tip.destroy()
            except Exception:
                pass
            self._build_tip = None

    def _trail_tip_show(self, _event=None):
        text = (self._trail_tip_text or "").strip()
        if not text or self._trail_tip is not None:
            return
        tip = tk.Toplevel(self.btn_trail)
        tip.wm_overrideredirect(True)
        tip.attributes("-topmost", True)
        x = self.btn_trail.winfo_rootx()
        y = self.btn_trail.winfo_rooty() + self.btn_trail.winfo_height() + 2
        tk.Label(tip, text=text, bg=TOOLTIP_BG, fg=TOOLTIP_FG, font=self._small,
                 padx=6, pady=3, relief="solid", bd=1, justify="left",
                 wraplength=360).pack()
        tip.wm_geometry(f"+{x}+{y}")
        self._trail_tip = tip

    def _trail_tip_hide(self, _event=None):
        if self._trail_tip is not None:
            try:
                self._trail_tip.destroy()
            except Exception:
                pass
            self._trail_tip = None

    def _exit_tip_show(self, _event=None):
        text = (self._exit_tip_text or "").strip()
        if not text or self._exit_tip is not None:
            return
        w = self.labels["exit"]
        tip = tk.Toplevel(w)
        tip.wm_overrideredirect(True)
        tip.attributes("-topmost", True)
        x = w.winfo_rootx()
        y = w.winfo_rooty() + w.winfo_height() + 2
        tk.Label(tip, text=text, bg=TOOLTIP_BG, fg=TOOLTIP_FG, font=self._small,
                 padx=6, pady=3, relief="solid", bd=1, justify="left",
                 wraplength=420).pack()
        tip.wm_geometry(f"+{x}+{y}")
        self._exit_tip = tip

    def _exit_tip_hide(self, _event=None):
        if self._exit_tip is not None:
            try:
                self._exit_tip.destroy()
            except Exception:
                pass
            self._exit_tip = None

    def update(self, pos, pstate, digits, trail_default=None, point=None,
               strategy_name="—", adopted=False, params=None):
        self._symbol = pos["symbol"]
        self.labels["symbol"].config(text=pos["symbol"])
        # Örökbefogadott (kézzel nyitott, utólag hozzárendelt) pozíció: „⇩" jelöli
        # és cián, hogy egy pillantással megkülönböztethető a bot sajátjától.
        self.labels["strategy"].config(
            text=(f"⇩{strategy_name}" if adopted else (strategy_name or "—")),
            fg=FG_CYAN if adopted else FG_GRAY)

        t = pos["type"]
        self.labels["type"].config(text=t, fg=FG_GREEN if t == "BUY" else FG_RED)
        self.labels["volume"].config(text=f'{pos["volume"]:.2f}', fg=FG_WHITE)
        self.labels["open"].config(text=_fmt_price(pos["price_open"], digits), fg=FG_GRAY)
        self.labels["current"].config(text=_fmt_price(pos["price_current"], digits), fg=FG_WHITE)

        entry   = pos["price_open"]
        cur     = pos["price_current"]
        sl_lvl  = pos["sl"]
        profit  = pos["profit"]
        dir_s   = 1 if t == "BUY" else -1   # a profit iránya

        sl, tp = pos["sl"], pos["tp"]
        orig = pstate.get("original_sl", sl) if pstate else sl
        # A kezdeti kockázat árban (1R): |belépő − EREDETI SL|. Ehhez mérünk minden
        # R-értéket (SL P&L, TP cél, folyó R) — így egységes az egész sor.
        _risk_price = abs(entry - orig) if orig else 0.0

        # P&L, ha az AKTUÁLIS SL bekövetkezik — R ÉS $ (mint a TP cél). A profit
        # lineáris az árban, így a lebegő P&L-ből arányosítható: pnl_sl =
        # P&L × (SL−entry)/(ár−entry); a lekötött R = (SL−belépő)/kockázat (előjeles:
        # −1R = teljes veszteség, 0 = BE, + = profitba húzott stop).
        if sl_lvl and abs(cur - entry) > (point or 1e-9):
            sl_pnl = profit * (sl_lvl - entry) / (cur - entry)
            sl_r   = ((sl_lvl - entry) / _risk_price * dir_s
                      if _risk_price > (point or 1e-9) else None)
            _slr   = f"{sl_r:+.1f}R " if sl_r is not None else ""
            self.labels["sl_pnl"].config(text=f"{_slr}{sl_pnl:+.0f}$",
                                         fg=FG_GREEN if sl_pnl >= 0 else FG_RED)
        else:
            self.labels["sl_pnl"].config(text="—", fg=FG_GRAY)

        be_done = bool(pstate and pstate.get("be_done"))
        trail_moved = bool(pstate and pstate.get("trail_moved"))
        moved = bool(sl and orig and abs(sl - orig) > 1e-9)
        # SL kijelzés: ha a TRAILING mozgatta → zöld + irányjel + "T" (látható, hogy
        # a trailing húzta); ha BE megvolt de a trailing még nem húzott → cián.
        if sl:
            sl_txt = _fmt_price(sl, digits)
            if trail_moved and moved:
                arrow = "⇗" if pos["type"] == "BUY" else "⇘"
                self.labels["sl"].config(text=f"{sl_txt} {arrow}T", fg=FG_GREEN)
            else:
                self.labels["sl"].config(text=sl_txt,
                                         fg=FG_CYAN if be_done else FG_WHITE)
        else:
            self.labels["sl"].config(text="—", fg=FG_WHITE)
        self.labels["tp"].config(text=_fmt_price(tp, digits) if tp else "—", fg=FG_GRAY)
        # TP cél: mennyit ér a TP R-ben és $-ban. Az R = |TP−belépő| / |belépő−er.SL|
        # (a kezdeti kockázathoz mérve); a $ ugyanaz a lineáris arányosítás, mint az
        # SL P&L-nél (profit × (TP−belépő)/(ár−belépő)). Így egy pillantással látod,
        # megéri-e a TP-ig kivárni. „—", ha nincs TP.
        if tp and abs(cur - entry) > (point or 1e-9):
            tp_pnl = profit * (tp - entry) / (cur - entry)
            tp_r   = (abs(tp - entry) / _risk_price) if _risk_price > (point or 1e-9) else None
            _rtxt  = f"{tp_r:.1f}R " if tp_r is not None else ""
            self.labels["tp_pnl"].config(text=f"{_rtxt}{tp_pnl:+.0f}$",
                                         fg=FG_GREEN if tp_pnl >= 0 else FG_RED)
        else:
            self.labels["tp_pnl"].config(text="—", fg=FG_GRAY)
        # Eredeti SL: fehér, de ha a trailing már elmozdította → szürke
        self.labels["orig_sl"].config(text=_fmt_price(orig, digits) if orig else "—",
                                      fg=FG_GRAY if moved else FG_WHITE)
        # Folyó eredmény EGY cellában: R ELÖL, $ HÁTUL — pontosan úgy, mint az SL P&L
        # és a TP cél (mindenhol egységes sorrend). A folyó R = (ár − belépő)/kockázat
        # a profit irányában; a kockázat (_risk_price) ugyanaz, amivel az SL P&L / TP
        # cél R-je is számol.
        pnl = pos["profit"]
        cur_r = None
        if _risk_price > (point or 1e-9):
            cur_r = (cur - entry) / _risk_price * dir_s
            self.labels["pnl"].config(text=f"{cur_r:+.2f}R {pnl:+.2f}$",
                                      fg=FG_GREEN if pnl >= 0 else FG_RED)
        else:
            self.labels["pnl"].config(text=f"{pnl:+.2f}$",
                                      fg=FG_GREEN if pnl >= 0 else FG_RED)

        # ── Kiszállási terv: HOL TART + MI JÖN (mennyit zár, mivel megy tovább) ──
        # Egy forrás hajtja a Kiszállás-cellát, a Trail gomb állapotát ÉS a
        # részletes tooltipet — így sose mondanak mást, mint a motor.
        _risk_usd = abs(profit / cur_r) if (cur_r not in (None, 0)) else None
        _ctx = {"cur_r": cur_r, "risk_price": _risk_price, "risk_usd": _risk_usd,
                "entry": entry, "cur": cur, "tp": tp, "dir_s": dir_s,
                "be_pct": (params or {}).get("breakeven_pct", 0.5)}
        plan = _exit_plan(pos["symbol"], pstate, _ctx)
        self.labels["exit"].config(text=plan["text"], fg=plan["color"])
        self._exit_tip_text = plan["tooltip"]

        # Gombok állapota (aktív-e?). A kézi BE csak akkor engedélyezett, ha a
        # költség-tudatos BE MOST mozgatható (a profit fedezi a spread+jutalék+swap
        # költséget) — különben TILTVA + tooltip, hogy ne lehessen némán nyomkodni.
        be_feasible = pos.get("be_feasible", True)   # True fallback (demo/régi cache)
        if be_done:
            self.btn_be.config(text="BE ✓", bg=BTN_PLAY_BG, fg=BTN_PLAY_FG, state="normal")
            self._be_tip_text = ""
        elif not be_feasible:
            self.btn_be.config(text="BE", bg=BTN_DIS_BG, fg=FG_GRAY, state="disabled")
            self._be_tip_text = (_t("gui2.be_meg_nem_lehetseges"))
        else:
            self.btn_be.config(text="BE", bg=BTN_OPT_BG, fg=BTN_OPT_FG, state="normal")
            self._be_tip_text = ""

        # Építés MÓD + „＋" gomb — a motor build_runtime-jából. A kulcs
        # (szimbólum, STRATÉGIA): egy instrumentumon több stratégia is építhet, és a
        # sor annak a csomagnak az állapotát mutatja, amelyikhez EZ a pozíció tartozik.
        # A mód a soron állítható (Ép-gomb); a „＋" csak Kézi módban + a jelre aktív.
        sym = pos.get("symbol")
        _rt = None
        try:
            from trading.live_trader import build_runtime as _br
            _strat = self._strategy_of_position(pos)
            _rt = _br.get((sym, _strat)) if (sym and _strat) else None
        except Exception:
            _rt = None
        # A tényleges mód: a build_runtime-ból, vagy közvetlenül a build_state-ből
        # (ha a motor még nem töltötte fel — pl. épp most állítottad át).
        _mode = (_rt or {}).get("mode")
        if _mode is None:
            try:
                from core import build_state as _bst
                _mode = _bst.get_mode(sym) if sym else "off"
            except Exception:
                _mode = "off"
        _MODE_LBL = {"off": _t("gui2.ep_ki"), "manual": _t("gui2.ep_kezi"), "auto": _t("gui2.ep_auto")}
        _MODE_COL = {"off": FG_GRAY, "manual": FG_WHITE, "auto": FG_CYAN}
        self.btn_bmode.config(text=_MODE_LBL.get(_mode, _t("gui2.ep_ki")),
                              fg=_MODE_COL.get(_mode, FG_GRAY),
                              relief="sunken" if _mode in ("manual", "auto") else "flat")
        if _mode == "manual" and _rt and _rt.get("ready"):
            self.btn_build.config(state="normal", bg=BTN_OPT_BG, fg=BTN_OPT_FG)
            self._build_tip_text = (_t("gui.pos.build_add", lot=_fmtnum(f"{_rt.get('next_lot', 0):.2f}"),
                                    price=_fmtnum(f"{_rt.get('avg_price', 0):.5f}")))
        elif _mode == "manual":
            self.btn_build.config(state="disabled", bg=BTN_DIS_BG, fg=FG_GRAY)
            self._build_tip_text = (_t("gui2.epites_kezi_a_gomb"))
        elif _mode == "auto":
            # Auto: a motor magától épít → a gomb tiltva, de cián jelzi, hogy aktív.
            self.btn_build.config(text="＋", state="disabled", bg=BTN_DIS_BG, fg=FG_CYAN)
            self._build_tip_text = _t("gui2.epites_auto_a_motor")
        else:
            self.btn_build.config(state="disabled", bg=BTN_DIS_BG, fg=FG_GRAY)
            self._build_tip_text = (_t("gui2.epites_pozicioepites_kikapcsolva_az"))

        # Trail gomb — a MOTOR valódi feltételét tükrözi (nem csak a be_done-t):
        #   • KI (lapos, szürke):        kézzel kikapcsoltad (trailing_enabled=False)
        #   • NEM TRAILEL (lapos, lila): a preset szerint a stop a kijelölt szinten
        #     marad (Fibo/Harmados, vagy Felező/Pajzs runner≠Trailing) — a szín (lila)
        #     jelzi (a legenda magyarázza), a szöveg marad „Trail", hogy ne vágódjon le
        #   • VÁR (benyomott, narancs):  trailelne, de még nem kockázatmentes (1R/BE
        #     előtt) → még nem húz
        #   • HÚZ (benyomott, zöld):     kockázatmentes ÉS a preset trailel → húz
        trail_on = bool(pstate.get("trailing_enabled", True)) if pstate else True
        # A motor is_rf-jének kijelzés-oldali mása: SL a belépőn túl (ár-igazság),
        # vagy a motor már BE-kész, vagy volt részleges zárás.
        rf_now = (bool(pos.get("risk_free")) or be_done
                  or bool(pstate and pstate.get("rr_reduced")))
        if not trail_on:
            self.btn_trail.config(text="Trail", relief="flat",
                                  bg=BTN_DIS_BG, fg=FG_GRAY)
            _trail_state = (_t("gui2.kikapcsolva_a_trail_gombbal"))
        elif not plan["trails"]:
            self.btn_trail.config(text="Trail", relief="flat",
                                  bg=BTN_DIS_BG, fg=FG_PURPLE)
            _trail_state = (_t("gui2.ennel_a_beallitasnal_nincs"))
        elif rf_now:
            self.btn_trail.config(text="Trail", relief="sunken",
                                  bg=FG_GREEN, fg=FG_ON_ACCENT)
            _trail_state = _t("gui2.huz_a_pozicio_kockazatmentes")
        else:
            self.btn_trail.config(text="Trail", relief="sunken",
                                  bg=FG_ORANGE, fg=FG_ON_ACCENT)
            _trail_state = (_t("gui2.var_amint_a_pozicio"))

        # Trail távolság mező — PONTBAN, egész szám. A kézi felülírás, ha van;
        # egyébként az optimalizált alapérték. Gépelés közben NEM írjuk felül.
        override = pstate.get("trail_points") if pstate else None
        eff = override if override is not None else trail_default
        try:
            focused = self.ent_trail.focus_get() is self.ent_trail
        except Exception:
            focused = False
        if not focused:
            self._trail_var.set(str(int(eff)) if eff is not None else "")
        # Vizuális jelzés: kézi felülírás = cián, alapérték = halványabb
        self.ent_trail.config(fg=FG_CYAN if override is not None else FG_GRAY)

        # A táv R/$ ekvivalense — a nyers pont-szám (pl. „600") önmagában keveset
        # mond; a tooltipben látod, a kockázat hányad része (R) és kb. hány $ a
        # követési táv. R = trail_táv / kezdeti kockázat (pontban); $ = R × (a
        # kezdeti kockázat $-a a lebegő P&L-ből arányosítva, mint az SL P&L).
        _rr_txt = ""
        if eff and point and point > 0 and _risk_price > (point or 1e-9):
            _risk_pts = _risk_price / point
            _r_of_trail = eff / _risk_pts
            _rr_txt = f"≈{_r_of_trail:.2f}R"
            if abs(cur - entry) > (point or 1e-9):
                _risk_usd = abs(profit * (_risk_price) / (cur - entry))
                _rr_txt += f" / {_r_of_trail * _risk_usd:.0f}$"

        # A Trail gomb + táv-mező közös tooltipje: a távolság ÉS mikor húz.
        _tip = _t("gui.pos.trail_dist", points=int(eff)) if eff else \
               _t("gui2.trailing_kovetes_nincs_beallitott")
        if _rr_txt:
            _tip += f"  ({_rr_txt.strip()})"
        _tip += (_t("gui.pos.trail_tip", state=_trail_state, plan=plan["tooltip"]))
        self._trail_tip_text = _tip


class PositionsTab:
    def __init__(self, parent, cfg, mono_font, small_font, header_font,
                 positions_provider, pos_state, digits_provider,
                 on_be, on_trail, on_panic, on_close_all,
                 on_name_click, on_trail_dist, trail_default_provider,
                 point_provider, strategy_provider=None, on_build=None,
                 on_build_mode=None, on_strategy_click=None, on_exit_click=None,
                 params_provider=None):
        self.parent = parent
        self.cfg = cfg
        self._mono, self._small, self._header = mono_font, small_font, header_font
        self._positions_provider = positions_provider
        self._strategy_provider = strategy_provider
        self._pos_state = pos_state
        self._digits_provider = digits_provider
        self._on_be, self._on_trail, self._on_panic = on_be, on_trail, on_panic
        self._on_close_all = on_close_all
        self._on_name_click = on_name_click
        self._on_trail_dist = on_trail_dist
        self._on_build = on_build
        self._on_build_mode = on_build_mode
        self._on_strategy_click = on_strategy_click
        self._on_exit_click = on_exit_click
        self._params_provider = params_provider
        self._trail_default_provider = trail_default_provider
        self._point_provider = point_provider
        self._rows: dict[int, PositionRow] = {}
        self._build_ui()

    def _build_ui(self):
        p = self.parent
        p.configure(bg=BG)
        top = tk.Frame(p, bg=BG, pady=4)
        top.pack(fill="x", padx=8)
        tk.Button(top, text=_t("gui.osszes_zarasa"), font=self._small,
                  bg=BTN_STOP_BG, fg=BTN_STOP_FG, relief="flat", cursor="hand2",
                  command=self._on_close_all).pack(side="left")
        self._lbl_total = tk.Label(top, text=_t("gui.osszes_p_l"), bg=BG,
                                   fg=FG_WHITE, font=self._header)
        self._lbl_total.pack(side="right", padx=8)

        self._lbl_breakdown = tk.Label(p, text="", bg=BG, fg=FG_GRAY,
                                       font=self._small, anchor="w", justify="left")
        self._lbl_breakdown.pack(fill="x", padx=10, pady=(0, 4))

        # Jelmagyarázat — a Trail gomb színei és az SL trailing-jelölés
        legend = tk.Frame(p, bg=BG)
        legend.pack(fill="x", padx=10, pady=(0, 4))
        tk.Label(legend, text="Trail:", bg=BG, fg=FG_GRAY, font=self._small).pack(side="left")
        for txt, col in [(_t("gui2.huz"), FG_GREEN), (_t("gui2.var_kockazatmentesre"), FG_ORANGE),
                         ("■ nem trailel (Fibo/Harmados…)", FG_PURPLE),
                         ("■ kikapcsolva", FG_GRAY)]:
            tk.Label(legend, text=txt, bg=BG, fg=col, font=self._small, padx=4).pack(side="left")
        tk.Label(legend, text=_t("gui.sl_t_trailing_mozgatta"),
                 bg=BG, fg=FG_GRAY, font=self._small).pack(side="left")
        tk.Label(p, text=_t("gui2.kiszallas_hol_tart_a") +
                         _t("gui2.1r_nel_75_zar"),
                 bg=BG, fg=FG_GRAY_DIM, font=self._small, anchor="w",
                 justify="left").pack(fill="x", padx=10, pady=(0, 4))

        # Fejléc
        hdr = tk.Frame(p, bg=BG_HEADER)
        hdr.pack(fill="x", padx=2)
        for key, label, w, anchor in POSITION_COLUMNS:
            tk.Label(hdr, text=label, width=w, anchor=anchor, bg=BG_HEADER,
                     fg=FG_BLUE, font=self._header, padx=4, pady=3).pack(side="left")
        tk.Label(hdr, text=_t("gui.vezerles_be_ep_mod"), width=40, anchor="w",
                 bg=BG_HEADER, fg=FG_BLUE, font=self._header).pack(side="left")
        tk.Frame(p, bg=FG_GRAY_DIM, height=1).pack(fill="x", padx=2)

        self._rows_frame = tk.Frame(p, bg=BG)
        self._rows_frame.pack(fill="both", expand=True, padx=2)

    def refresh(self):
        positions = self._positions_provider() or []
        seen = set()
        for pos in positions:
            tid = pos["ticket"]
            seen.add(tid)
            row = self._rows.get(tid)
            if row is None:
                row = PositionRow(self._rows_frame, tid, self._mono, self._small,
                                  self._on_be, self._on_trail, self._on_panic,
                                  self._on_name_click, self._on_trail_dist,
                                  on_build=self._on_build,
                                  on_build_mode=self._on_build_mode,
                                  on_strategy_click=self._on_strategy_click,
                                  on_exit_click=self._on_exit_click)
                self._rows[tid] = row
            trail_def = self._trail_default_provider(pos["symbol"])
            point     = self._point_provider(pos["symbol"])
            strat     = (self._strategy_provider(pos.get("magic"), tid)
                         if self._strategy_provider else "—")
            params    = (self._params_provider(pos["symbol"])
                         if self._params_provider else None)
            row.update(pos, self._pos_state.get(tid),
                       self._digits_provider(pos["symbol"]), trail_def, point,
                       strategy_name=strat,
                       adopted=_adopted.is_open_adopted(tid),
                       params=params)

        for tid in list(self._rows):
            if tid not in seen:
                self._rows[tid].frame.destroy()
                del self._rows[tid]

        # Rendezett csomagolás (szimbólum szerint) — CSAK ha a sorrend változott.
        # Enélkül minden ciklusban (~1 mp) újracsomagolnánk, ami a kurzor alatt
        # álló sorból is Enter/Leave eseményt vált ki → a hover-tooltip villog.
        order = [pos["ticket"] for pos in
                 sorted(positions, key=lambda x: (x["symbol"], x["ticket"]))]
        if order != getattr(self, "_order", None):
            for r in self._rows.values():
                r.frame.pack_forget()
            for tid in order:
                self._rows[tid].frame.pack(fill="x", padx=2)
            self._order = order

        # Összesítés + instrumentumonkénti bontás
        total = sum(p["profit"] for p in positions)
        by_sym: dict[str, list] = {}
        for p in positions:
            a = by_sym.setdefault(p["symbol"], [0.0, 0])
            a[0] += p["profit"]
            a[1] += 1
        self._lbl_total.config(
            text=_t("gui.pos.total", pnl=_fmtnum(f"{total:+.2f}"), n=len(positions)),
            fg=FG_GREEN if total >= 0 else FG_RED)
        if by_sym:
            parts = [f"{s}: {v[0]:+.2f}$ ({v[1]})" for s, v in sorted(by_sym.items())]
            self._lbl_breakdown.config(text="   |   ".join(parts), fg=FG_GRAY)
        else:
            self._lbl_breakdown.config(text=_t("gui.nincs_nyitott_pozicio"), fg=FG_GRAY)


# ---------------------------------------------------------------------------
# Lezárt napi pozíciók fül — a mai (UTC) lezárt kereskedések + összesítés
# ---------------------------------------------------------------------------

CLOSED_COLUMNS = [
    ("symbol",   "Symbol",     10, "w"),
    ("strategy", _t("signals.col.strategy"),   9, "center"),
    ("type",     _t("signals.col.dir"),       6, "center"),
    ("volume",   "Lot",         6, "center"),
    ("open",     _t("gui2.nyito"),      10, "center"),
    ("close",    _t("gui2.zaro"),       10, "center"),
    ("time",     _t("gui2.zaras"),       8, "center"),
    ("pnl",      "P&L",         9, "center"),
    ("r",        "R",           6, "center"),
]


def _r_multiple(c: dict, risk_provider=None):
    """A trade R-szorzója — **PÉNZ-alapú**: `realizált P&L / belépéskori kockázat`.

    A korábbi képlet ÁR-alapú volt (`elmozdulás / SL-táv`). Az kényelmesen
    lot-független, DE **részleges zárásnál félrevezet**, mert csak az UTOLSÓ
    záróárat nézi: egy Pajzs-kötésnél (75% zárva 1R-nél, a runner 3R-nél) 3,00R-t
    mondott, holott a valós pénz-eredmény 1,50R. A jutalékot és a swapot sem
    tartalmazta, a `pnl` viszont igen.

    `risk_provider(c) -> float | None` adja a belépéskori kockázatot (rögzített
    érték, tartalékként a nyitó order SL-jéből). None → nincs R („—")."""
    if risk_provider is None:
        return None
    risk = risk_provider(c)
    if not risk:
        return None
    try:
        return float(c.get("pnl") or 0.0) / float(risk)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


class ClosedTab:
    """Mai lezárt kereskedések (MT5 history), stratégiánkénti bontással.
    A sorok kulcsa a pozíció-azonosító; a lista a nap során csak bővül."""

    def __init__(self, parent, mono_font, small_font, header_font,
                 closed_provider, strategy_provider, digits_provider,
                 range_provider=None, risk_provider=None):
        self.parent = parent
        self._mono, self._small, self._header = mono_font, small_font, header_font
        self._closed_provider = closed_provider
        self._strategy_provider = strategy_provider
        self._digits_provider = digits_provider
        # `risk_provider(closed_row) -> float | None` — a belépéskori kockázat (1 R).
        # Enélkül az R-oszlop „—" (nem 0): a hiányzó adat nem nulla eredmény.
        self._risk_provider = risk_provider
        # `range_provider(date_from, date_to) -> list` — MT5-lekérés egy időszakra.
        # None → csak a „ma" nézet él (visszafelé kompatibilis).
        self._range_provider = range_provider
        self._rows: dict = {}
        self._day = None          # az utolsó frissítés napja (napváltás-detektálás)
        self._custom: list | None = None   # a betöltött időszak adata (None = ma)
        self._custom_label = ""
        self._pending_reset = False        # nézet-váltásnál a sorokat törölni kell
        self._build_ui()

    def _build_ui(self):
        p = self.parent
        p.configure(bg=BG)
        top = tk.Frame(p, bg=BG, pady=4)
        top.pack(fill="x", padx=8)
        self._lbl_title = tk.Label(top, text=_t("gui.lezart_kereskedesek_mt5_szerver"),
                                   bg=BG, fg=FG_WHITE, font=self._header)
        self._lbl_title.pack(side="left")
        self._lbl_total = tk.Label(top, text=_t("gui.osszes_p_l"), bg=BG, fg=FG_WHITE,
                                   font=self._header)
        self._lbl_total.pack(side="right", padx=8)

        # ── Időszak-választó ─────────────────────────────────────────────
        # A „ma" a leggyakoribb eset, ezért ELŐVÁLASZTOTT gyorsgombok vannak, és a
        # tól–ig csak akkor él, ha tényleg intervallumot kérsz. A dátumot SZÖVEGBŐL
        # olvassuk (nincs külön naptár-widget a tkinterben, és egy `YYYY-MM-DD`
        # mező itt nem lassítja a munkát).
        sel = tk.Frame(p, bg=BG)
        sel.pack(fill="x", padx=10, pady=(0, 2))
        self._range_var = tk.StringVar(value="today")
        for _val, _txt in (("today", "Ma"), ("7", "7 nap"), ("30", "30 nap"),
                           ("custom", _t("range.custom"))):
            tk.Radiobutton(sel, text=_txt, value=_val, variable=self._range_var,
                           bg=BG, fg=FG_WHITE, selectcolor=BG_HEADER,
                           activebackground=BG, activeforeground=FG_WHITE,
                           font=self._small,
                           command=self._on_range_change).pack(side="left", padx=(0, 6))
        _today = datetime.now().date()
        self._from_var = tk.StringVar(value=str(_today))
        self._to_var   = tk.StringVar(value=str(_today))
        for _v in (self._from_var, self._to_var):
            tk.Entry(sel, textvariable=_v, width=11, bg=BG_HEADER, fg=FG_WHITE,
                     font=self._small, insertbackground=FG_WHITE,
                     relief="flat").pack(side="left", padx=2)
        tk.Button(sel, text=_t("range.load"), bg=BTN_OPT_BG, fg=BTN_OPT_FG, relief="flat",
                  font=self._small, command=self._on_range_change).pack(side="left",
                                                                       padx=6)
        self._lbl_range_err = tk.Label(sel, text="", bg=BG, fg=FG_RED,
                                       font=self._small)
        self._lbl_range_err.pack(side="left", padx=6)

        self._lbl_breakdown = tk.Label(p, text="", bg=BG, fg=FG_GRAY, font=self._small,
                                       anchor="w", justify="left")
        self._lbl_breakdown.pack(fill="x", padx=10, pady=(0, 4))

        hdr = tk.Frame(p, bg=BG_HEADER)
        hdr.pack(fill="x", padx=2)
        for key, label, w, anchor in CLOSED_COLUMNS:
            tk.Label(hdr, text=label, width=w, anchor=anchor, bg=BG_HEADER,
                     fg=FG_BLUE, font=self._header, padx=4, pady=3).pack(side="left")
        tk.Frame(p, bg=FG_GRAY_DIM, height=1).pack(fill="x", padx=2)

        holder = tk.Frame(p, bg=BG)
        holder.pack(fill="both", expand=True, padx=2)
        canvas = tk.Canvas(holder, bg=BG, highlightthickness=0)
        vsb = tk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self._rows_frame = tk.Frame(canvas, bg=BG)
        canvas.create_window((0, 0), window=self._rows_frame, anchor="nw")
        self._rows_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

    def refresh(self):
        # Napváltás (a provider csak a MAI trade-eket adja, a sorok viszont csak
        # bővültek) → új napon nulláznunk kell, különben két nap adata keveredne.
        today = datetime.now().date()
        if self._day is not None and today != self._day:
            for w in self._rows_frame.winfo_children():
                w.destroy()
            self._rows.clear()
        self._day = today
        # Időszakos nézetben a lista NEM „csak bővül": másik időszak MÁS trade-ek.
        # A `_reset_rows()` a betöltésnél már törölt; itt csak a mai nézetre
        # visszatérés esetét kell kezelni.
        if self._pending_reset:
            self._pending_reset = False
            for w in self._rows_frame.winfo_children():
                w.destroy()
            self._rows.clear()

        # Az adat forrása: „ma" → a folyamatos gyorsítótár; időszak → a betöltött
        # pillanatkép. Az utóbbi SZÁNDÉKOSAN nem frissül magától: egy múltbeli
        # időszak nem változik, és minden körben újra lekérni az MT5-öt pazarlás.
        if self._custom is not None:
            closed = list(self._custom)
        else:
            closed = self._closed_provider() or []
        for c in closed:
            pid = c["position"]
            if pid not in self._rows:
                self._rows[pid] = self._make_row(c)   # nincs törlés — a lista csak bővül

        total   = sum(c["pnl"] for c in closed)
        wins    = sum(1 for c in closed if c["pnl"] > 0)
        losses  = sum(1 for c in closed if c["pnl"] < 0)
        r_vals  = [_r_multiple(c, self._risk_provider) for c in closed]
        total_r = sum(r for r in r_vals if r is not None)
        r_txt   = f"   |   {total_r:+.2f}R" if any(r is not None for r in r_vals) else ""
        self._lbl_total.config(
            text=_t("gui.closed.total", pnl=_fmtnum(f"{total:+.2f}"), r=r_txt,
            n=len(closed), wins=wins, losses=losses),
            fg=FG_GREEN if total >= 0 else FG_RED)

        by_strat: dict = {}
        for c in closed:
            nm = (self._strategy_provider(c.get("magic"), c.get("position"))
                  if self._strategy_provider else "—")
            a = by_strat.setdefault(nm, [0.0, 0])
            a[0] += c["pnl"]
            a[1] += 1
        if by_strat:
            parts = [f"{s}: {v[0]:+.2f}$ ({v[1]})" for s, v in sorted(by_strat.items())]
            self._lbl_breakdown.config(text="   |   ".join(parts), fg=FG_GRAY)
        else:
            self._lbl_breakdown.config(
                text=(_t("gui.closed.none", label=self._custom_label)
                      if self._custom is not None
                      else _t("gui2.ma_meg_nincs_lezart")), fg=FG_GRAY)

    def _on_range_change(self):
        """Az időszak-választó kezelője: betölti a kért intervallumot az MT5-ből.

        A „Ma" visszaáll a folyamatos gyorsítótárra (az frissül magától). A többi
        eset EGYSZERI pillanatkép: egy lezárt múltbeli időszak nem változik, ezért
        nem kérjük le minden körben."""
        from datetime import timedelta
        from core.mt5_connector import server_today
        mode = self._range_var.get()
        self._lbl_range_err.config(text="")
        if mode == "today":
            self._custom, self._custom_label = None, ""
            self._pending_reset = True
            self._lbl_title.config(text=_t("gui.lezart_kereskedesek_ma_mt5"))
            self.refresh()
            return
        if self._range_provider is None:
            self._lbl_range_err.config(text="nincs MT5-kapcsolat")
            return
        # A BRÓKER mai dátuma (nem a gépé): a szerver-éjfél környékén a kettő
        # eltér, és akkor a „Ma" más trade-eket mutatna, mint a napi összesítő.
        today = server_today()
        if mode in ("7", "30"):
            d_from, d_to = today - timedelta(days=int(mode) - 1), today
            self._from_var.set(str(d_from))
            self._to_var.set(str(d_to))
        else:
            from datetime import date as _date
            try:
                d_from = _date.fromisoformat(self._from_var.get().strip())
                d_to   = _date.fromisoformat(self._to_var.get().strip())
            except ValueError:
                # A hibát KIÍRJUK, nem nyeljük el: enélkül a felület csak annyit
                # mutatna, hogy „nincs lezárt kereskedés" — ami hazugság lenne.
                self._lbl_range_err.config(text=_t("gui.datum_eeee_hh_nn"))
                return
        try:
            data = self._range_provider(d_from, d_to) or []
        except Exception as e:
            self._lbl_range_err.config(text=_t("gui.closed.fetch_error", error=e))
            return
        self._custom = data
        self._custom_label = (str(d_from) if d_from == d_to
                              else f"{d_from} … {d_to}")
        self._pending_reset = True
        self._lbl_title.config(
            text=_t("gui.closed.title", label=self._custom_label))
        self.refresh()

    def _make_row(self, c):
        digits = self._digits_provider(c["symbol"])
        strat  = (self._strategy_provider(c.get("magic"), c.get("position"))
                  if self._strategy_provider else "—")
        t      = c["type"]
        pnl    = c["pnl"]
        r      = _r_multiple(c, self._risk_provider)
        tstr   = datetime.fromtimestamp(c["close_time"], tz=timezone.utc).strftime("%H:%M")
        vals = {
            "symbol":   (c["symbol"],                       FG_WHITE),
            "strategy": (strat,                             FG_GRAY),
            "type":     (t,                 FG_GREEN if t == "BUY" else FG_RED),
            "volume":   (f'{c["volume"]:.2f}',              FG_WHITE),
            "open":     (_fmt_price(c["price_open"], digits),  FG_GRAY),
            "close":    (_fmt_price(c["price_close"], digits), FG_WHITE),
            "time":     (tstr,                              FG_GRAY),
            "pnl":      (f"{pnl:+.2f}$",     FG_GREEN if pnl >= 0 else FG_RED),
            "r":        (f"{r:+.2f}R" if r is not None else "—",
                         FG_GRAY if r is None else (FG_GREEN if r >= 0 else FG_RED)),
        }
        row = tk.Frame(self._rows_frame, bg=BG_ROW_EVEN)
        for key, label, w, anchor in CLOSED_COLUMNS:
            txt, fg = vals[key]
            tk.Label(row, text=txt, width=w, anchor=anchor, bg=BG_ROW_EVEN, fg=fg,
                     font=self._mono, padx=4, pady=2).pack(side="left")
        row.pack(fill="x", padx=2)
        return row


# ---------------------------------------------------------------------------
# Fő Dashboard ablak
# ---------------------------------------------------------------------------

class DashboardWindow:
    def __init__(self, cfg: dict, dashboard_ref: dict,
                 instrument_state: dict, optimizer_status: dict,
                 on_play_pair, on_stop_pair, strategy=None,
                 on_slots_change=None, auto_resume_opt=False):
        self.cfg              = cfg
        self._auto_resume_opt = auto_resume_opt
        self.dashboard_ref    = dashboard_ref
        self.instrument_state = instrument_state
        self.optimizer_status = optimizer_status

        self._on_play         = on_play_pair
        self._on_stop         = on_stop_pair
        self._on_slots_change = on_slots_change
        self.strategy         = strategy or get_strategy(cfg)
        # Több-stratégia: oszlop MINDEN ELÉRHETŐ stratégiához (fejléc = neve). Az
        # elérhetők a config `available_strategies` whitelistje (alap = az összes
        # regisztrált) — így egy kikapcsolt stratégia nem kap oszlopot.
        from strategy import available_strategy_names, get_strategy_by_name
        self._all_strategies  = [get_strategy_by_name(n)
                                 for n in available_strategy_names(cfg)]
        self._columns         = build_columns(self._all_strategies)
        # Stratégia-hatókörű params-tárolás: aktív stratégia + egyszeri migráció.
        from core.params_store import set_active_strategy, migrate_flat_layout
        set_active_strategy(self.strategy.name)
        migrate_flat_layout(self.strategy.name)

        # Frissítési ütemezés (config-vezérelt)
        dash_cfg = cfg.get("dashboard", {})
        self._price_refresh_sec = dash_cfg.get("price_refresh_sec", 3)   # ár MINDEN párra
        self._fast_refresh_sec  = dash_cfg.get("live_refresh_sec", 7)    # indikátor: LIVE
        self._all_refresh_sec   = dash_cfg.get("all_refresh_sec", 30)    # indikátor: mind

        max_par = cfg.get("optimizer", {}).get("max_parallel_optimizers", 2)
        self._opt_ctrl = OptimizerController(
            cfg, self.strategy, dashboard_ref,
            instrument_state, optimizer_status, max_parallel=max_par)

        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} v{APP_VERSION} — Live Dashboard")
        self.root.configure(bg=BG)
        self.root.resizable(True, True)

        # A betű-objektumok a témából (config: dashboard.font_family/font_size).
        # ÉLŐK: a beállító ablak `configure()`-ral azonnal átállítja őket, és minden
        # widget követi — ezért nem kell újraindítás a betűméret-váltáshoz.
        self._fonts = _theme.fonts()
        mono_font   = self._fonts["mono"]
        header_font = self._fonts["header"]
        small_font  = self._fonts["small"]
        title_font  = self._fonts["title"]
        info_font   = self._fonts["info"]

        # ── Globális fejléc ─────────────────────────────────────────────
        top_bar = tk.Frame(self.root, bg=BG_HEADER, pady=5)
        top_bar.pack(fill="x", padx=4, pady=(4, 0))
        tk.Label(top_bar, text=APP_NAME,
                 bg=BG_HEADER, fg=FG_BLUE, font=title_font).pack(side="left", padx=(10, 3))
        # Verzió — jól látható helyen, a név mellett (build-azonosításhoz)
        tk.Label(top_bar, text=f"v{APP_VERSION}",
                 bg=BG_HEADER, fg=FG_CYAN, font=info_font).pack(side="left", padx=(0, 10))
        self.lbl_time = tk.Label(top_bar, text="", bg=BG_HEADER, fg=FG_GRAY, font=info_font)
        self.lbl_time.pack(side="right", padx=10)
        self._btn_connect = tk.Button(
            top_bar, text=_t("gui.kapcsolodas2"), font=small_font,
            bg=BTN_OPT_BG, fg=BTN_OPT_FG, relief="flat", command=self._handle_connect)
        self._btn_connect.pack(side="right", padx=6)
        self._btn_connect.pack_forget()
        self.lbl_conn = tk.Label(top_bar, text="● Offline", bg=BG_HEADER,
                                 fg=FG_RED, font=info_font)
        self.lbl_conn.pack(side="right", padx=(0, 4))
        self.lbl_account = tk.Label(top_bar, text="", bg=BG_HEADER, fg=FG_GRAY, font=info_font)
        self.lbl_account.pack(side="right", padx=10)
        # ── LICENC-FELHASZNÁLÓ ────────────────────────────────────────────
        # ⚠ Melyik fiók belépője van EZEN a gépen. Több fiók / több gép mellett
        # ez az egyetlen hely, ahol látszik — a portálon a token címkéje a gép
        # neve, itt viszont a fordítottja kell: melyik felhasználóé a gép.
        # A licenc ÉRVÉNYESSÉGÉT nem ez mondja meg (arról a napló és az
        # indításkori kapu szól); ez csak azonosít.
        self.lbl_licence = tk.Label(top_bar, text="", bg=BG_HEADER,
                                    fg=FG_GRAY, font=info_font)
        self.lbl_licence.pack(side="right", padx=(10, 0))
        self._refresh_licence_label()

        info_bar = tk.Frame(self.root, bg=BG_HEADER, pady=2)
        info_bar.pack(fill="x", padx=4)
        self.lbl_balance = tk.Label(info_bar, text="Egyenleg: —",
                                    bg=BG_HEADER, fg=FG_WHITE, font=info_font)
        self.lbl_balance.pack(side="left", padx=10)
        self.lbl_daily   = tk.Label(info_bar, text="Napi P&L: —",
                                    bg=BG_HEADER, fg=FG_WHITE, font=info_font)
        self.lbl_daily.pack(side="left", padx=10)
        self.lbl_slots   = tk.Label(info_bar, text="Szabad slotok: —/—",
                                    bg=BG_HEADER, fg=FG_WHITE, font=info_font)
        self.lbl_slots.pack(side="left", padx=(10, 2))
        # Max slotszám állítása a felületről (csökkenteni csak a foglaltakig lehet)
        tk.Button(info_bar, text="▼", font=small_font, width=2,
                  bg=BG_INACTIVE, fg=FG_WHITE, relief="flat", cursor="hand2",
                  command=lambda: self._change_slots(-1)).pack(side="left", padx=1)
        tk.Button(info_bar, text="▲", font=small_font, width=2,
                  bg=BG_INACTIVE, fg=FG_WHITE, relief="flat", cursor="hand2",
                  command=lambda: self._change_slots(+1)).pack(side="left", padx=(1, 10))
        # Kockázat/számla állítása — a slotok PÁRJA: a `max_open_slots` azt mondja
        # meg, HÁNY felé osztjuk, ez pedig azt, MENNYIT. A kettő együtt adja egy
        # slot keretét (egyenleg × risk_pct / max_slots).
        self.lbl_risk = tk.Label(info_bar, text=_t("gui.kockazat"),
                                 bg=BG_HEADER, fg=FG_WHITE, font=info_font)
        self.lbl_risk.pack(side="left", padx=(10, 2))
        tk.Button(info_bar, text="▼", font=small_font, width=2,
                  bg=BG_INACTIVE, fg=FG_WHITE, relief="flat", cursor="hand2",
                  command=lambda: self._change_risk_pct(-0.001)).pack(side="left", padx=1)
        tk.Button(info_bar, text="▲", font=small_font, width=2,
                  bg=BG_INACTIVE, fg=FG_WHITE, relief="flat", cursor="hand2",
                  command=lambda: self._change_risk_pct(+0.001)).pack(side="left", padx=(1, 10))
        self.lbl_limit   = tk.Label(info_bar, text="Napi limit: OK",
                                    bg=BG_HEADER, fg=FG_GREEN, font=info_font)
        self.lbl_limit.pack(side="left", padx=(10, 2))
        # Napi limit állítása a felületről (mint a slotoké): ▼/▲ 10$-os lépésben,
        # a config.json trading.daily_loss_limit_usd kulcsába perzisztálva. A live
        # motor UGYANEZT a cfg-dictet olvassa → azonnal él.
        tk.Button(info_bar, text="▼", font=small_font, width=2,
                  bg=BG_INACTIVE, fg=FG_WHITE, relief="flat", cursor="hand2",
                  command=lambda: self._change_daily_limit(-10)).pack(side="left", padx=1)
        tk.Button(info_bar, text="▲", font=small_font, width=2,
                  bg=BG_INACTIVE, fg=FG_WHITE, relief="flat", cursor="hand2",
                  command=lambda: self._change_daily_limit(+10)).pack(side="left", padx=(1, 10))

        tk.Frame(self.root, bg=FG_GRAY_DIM, height=1).pack(fill="x", pady=2)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=BG_HEADER, foreground=FG_GRAY,
                        padding=[12, 4], font=_theme.fonts()["mono"])
        style.map("TNotebook.Tab", background=[("selected", BG)],
                  foreground=[("selected", FG_BLUE)])

        self._notebook = ttk.Notebook(self.root)
        self._notebook.pack(fill="both", expand=True, padx=2)

        live_frame = tk.Frame(self._notebook, bg=BG)
        self._notebook.add(live_frame, text="  Live Dashboard  ")
        self._build_live_tab(live_frame, mono_font, header_font, small_font)

        pos_frame = tk.Frame(self._notebook, bg=BG)
        self._notebook.add(pos_frame, text=_t("gui.poziciok"))
        from trading.live_trader import position_state as _pos_state
        self._pos_tab = PositionsTab(
            pos_frame, cfg, mono_font, small_font, header_font,
            positions_provider=lambda: getattr(self, "_mt5_cache", {}).get("positions_detail", []),
            pos_state=_pos_state,
            digits_provider=lambda sym: getattr(self.dashboard_ref.get(sym), "digits", 5),
            on_be=self._pos_be, on_trail=self._pos_trail,
            on_panic=self._pos_panic, on_close_all=self._pos_close_all,
            on_name_click=self._show_instrument_params,
            on_trail_dist=self._pos_trail_dist,
            trail_default_provider=self._trail_default,
            point_provider=lambda sym: getattr(self.dashboard_ref.get(sym), "point", None),
            strategy_provider=self._strategy_by_magic,
            on_build=self._pos_build,
            on_build_mode=self._pos_build_mode,
            on_strategy_click=self._pos_strategy_menu,
            on_exit_click=self._pos_exit_menu,
            params_provider=self._pos_params)

        closed_frame = tk.Frame(self._notebook, bg=BG)
        # A fül neve már nem „(ma)": időszak is választható.
        self._notebook.add(closed_frame, text=_t("gui.lezart"))
        self._closed_tab = ClosedTab(
            closed_frame, mono_font, small_font, header_font,
            closed_provider=lambda: getattr(self, "_mt5_cache", {}).get("closed_today", []),
            strategy_provider=self._strategy_by_magic,
            digits_provider=lambda sym: getattr(self.dashboard_ref.get(sym), "digits", 5),
            range_provider=self._closed_in_range,
            risk_provider=self._closed_risk)

        sig_frame = tk.Frame(self._notebook, bg=BG)
        self._notebook.add(sig_frame, text=_t("gui.jelzesek"))
        from dashboard.signals_tab import SignalsTab
        from trading.live_trader import TRADES_CSV as _TCSV
        self._signals_tab = SignalsTab(
            sig_frame, _TCSV,
            on_trade=self._signal_manual_trade,
            price_of=self._signal_price_of,
            digits_of=self._signal_digits_of,
            lot_step_of=self._signal_lot_step_of,
            max_age_hours=self._signal_max_age_hours,
            open_of=self._signal_open_of)

        bt_frame = tk.Frame(self._notebook, bg=BG_BT)
        self._notebook.add(bt_frame, text=_t("gui.portfolio_backtest"))
        self._bt_tab = PortfolioBacktestTab(bt_frame, cfg, mono_font, small_font, header_font)

        self._balance    = 0.0
        self._free_slots = float(cfg["trading"]["max_open_slots"])
        self._max_slots  = cfg["trading"]["max_open_slots"]
        # A lekötött keret a számla devizájában (None = ismeretlen, ilyenkor a
        # darabszám a mérce). Ebből számoljuk a kiírt „terhelés %"-ot.
        self._occupied_risk = None
        # A nyitott pozíciók BONTÁSA a slot-címkéhez: összes darab vs. ebből
        # ténylegesen slotot foglaló (nem kockázatmentes). Enélkül a „8 nyitott
        # pozíció 4 slot mellett" jogos gyanút kelt — pedig szabályos, ha a
        # többi már BE-re húzott. Lásd `_render_slots_label`.
        self._open_total    = 0
        self._open_occupied = 0

        self._refresh()

    def _build_live_tab(self, parent, mono_font, header_font, small_font):
        self._mono_font   = mono_font
        self._small_font  = small_font
        self._header_font = header_font
        self._sort_col    = None
        self._sort_dir    = 1

        toolbar = tk.Frame(parent, bg=BG, pady=3)
        toolbar.pack(fill="x", padx=6)
        tk.Label(toolbar, text=_t("gui.kereses"), bg=BG, fg=FG_GRAY,
                 font=small_font).pack(side="left")
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._apply_filter_sort())
        tk.Entry(toolbar, textvariable=self._search_var, width=12,
                 bg=BG_HEADER, fg=FG_WHITE, font=small_font,
                 insertbackground=FG_WHITE, relief="flat").pack(side="left", padx=(3, 12))
        self._hide_stopped_var = tk.BooleanVar(value=False)
        tk.Checkbutton(toolbar, text=_t("gui.stopped_elrejtese"), variable=self._hide_stopped_var,
                       bg=BG, fg=FG_GRAY, selectcolor=BG_HEADER,
                       activebackground=BG, activeforeground=FG_WHITE, font=small_font,
                       command=self._apply_filter_sort).pack(side="left", padx=4)
        tk.Button(toolbar, text="  +  Instrumentum", font=small_font,
                  bg=BTN_OPT_BG, fg=BTN_OPT_FG, relief="flat", cursor="hand2",
                  command=self._show_add_instrument).pack(side="right", padx=4)
        tk.Button(toolbar, text=_t("gui.beallitas"), font=small_font,
                  bg=BG_INACTIVE, fg=FG_WHITE, relief="flat", cursor="hand2",
                  command=self._show_settings).pack(side="right", padx=4)

        legend = tk.Frame(parent, bg=BG, pady=2)
        legend.pack(fill="x", padx=6)
        # A jelmagyarázat a `classic` nézet SZÍNKÓDJAIT írja le: ott a szimbólum
        # neve az állapot szerint színeződik, és a soron van egy kattintható „R"
        # (kockázatcsökkentő preset) gomb. A 2.0 sorban EGYIK SEM létezik — a
        # szimbólum mindig fehér, preset-cella pedig nincs —, tehát ott mind a 12
        # elem félrevezet, és elvisz egy sávnyi helyet a főképernyőről.
        #
        # Ezért config-vezérelt (`dashboard.show_legend`), és az ALAPÉRTELMEZÉS
        # elrendezés-függő: `classic`-ban BE (ott igaz), `live2`-ben KI.
        if self._show_legend():
            for text, col in [
                ("■ LIVE", FG_GREEN), ("■ STOPPED", FG_GRAY),
                (_t("gui2.kivezetes_nincs_uj_belepo"), FG_ORANGE),
                (_t("gui2.nem_tanitott"), FG_GRAY_DIM),
                (_t("gui2.optimalizalas"), FG_YELLOW), (_t("gui2.kockazatmentes"), FG_CYAN),
                (_t("gui2.kockazatcsokk_kattints"), FG_GRAY),
                ("R Risky", FG_ORANGE), (_t("gui2.f_felezo"), FG_CYAN), ("P Pajzs", FG_GREEN),
                ("Fi Fibo", FG_YELLOW), ("H Harmados", FG_PURPLE),
                ("PF Pajzs↔Fibo", FG_TEAL),
            ]:
                tk.Label(legend, text=text, bg=BG, fg=col, font=small_font,
                         padx=6).pack(side="left")

        # ── Visszaszámláló-sáv (közös, minden instrumentumnál azonos) ───────
        # Config-vezérelt: dashboard.countdown_timeframes (percek listája) vagy
        # üres → a stratégia összes időkerete.
        strat_tfs = {tf.minutes: tf.label for tf in self.strategy.timeframes()}
        cd_cfg = self.cfg.get("dashboard", {}).get("countdown_timeframes")
        if cd_cfg:
            self._countdown_tfs = [(m, strat_tfs.get(m, f"{m}p")) for m in cd_cfg
                                   if m in strat_tfs]
        else:
            self._countdown_tfs = [(tf.minutes, tf.label) for tf in self.strategy.timeframes()]
        self._countdown_lbls = {}
        for minutes, label in self._countdown_tfs:
            lbl = tk.Label(legend, text=_t("gui.tf.close_unknown", label=label), bg=BG,
                           fg=FG_CYAN, font=header_font, padx=8)
            lbl.pack(side="right")
            self._countdown_lbls[minutes] = lbl

        tk.Frame(parent, bg=FG_GRAY_DIM, height=1).pack(fill="x", padx=2, pady=2)

        # ── Görgethető tábla: rögzített fejléc + scrollozható sorok ─────────
        table_holder = tk.Frame(parent, bg=BG)
        table_holder.pack(fill="both", expand=True, padx=2)

        header_holder = tk.Frame(table_holder, bg=BG)
        self._header_row = HeaderRow(
            header_holder, self._columns, header_font, small_font,
            on_col_click=self._on_header_click)
        # A 2.0 tábla SAJÁT (kétsoros, csoportosított) fejlécet hoz — a classic
        # fejléc ilyenkor nem jelenik meg. Megépítjük, de nem csomagoljuk ki: a
        # rendezés/szűrés kódja hivatkozik rá (`_header_row.set_sort`), és egy
        # None-ellenőrzés minden hívási helyre elszórva több kárt okozna.
        if not self._is_table_layout():
            header_holder.pack(fill="x")

        # ── A VÁSZON-tábla SAJÁT görgetést hoz → nincs külső görgethető vászon ──
        # A `canvas` elrendezés lényege, hogy a függőleges görgetés a vászon NATÍV
        # `yview`-ja. Ha ilyenkor a táblát mégis beletennénk a lenti, görgethető
        # külső vászonba, KÉT egymásba ágyazott görgetősáv keletkezne: a külsőnek
        # nincs mit görgetnie (teljes magasságú, inaktív sáv), a belső pedig csak
        # akkora helyet kapna, amekkorát a külső ad neki — rövid, nehezen fogható
        # fogantyú. Pontosan ez látszott az első éles próbán.
        if self._layout_mode() == "canvas":
            self._table_frame = tk.Frame(table_holder, bg=BG)
            self._table_frame.pack(fill="both", expand=True)
            self.rows: dict[str, PairRow] = {}
            self._build_live2(self._table_frame)
            tk.Frame(parent, bg=FG_GRAY_DIM, height=1).pack(fill="x", padx=2, pady=2)
            self.lbl_status = tk.Label(parent, text=_t("gui.indulas"), bg=BG,
                                       fg=FG_GRAY, font=small_font)
            self.lbl_status.pack(side="bottom", pady=4)
            self._make_error_badge(parent, small_font)
            return

        canvas = tk.Canvas(table_holder, bg=BG, highlightthickness=0)
        vsb = tk.Scrollbar(table_holder, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        # A fejléc a canvason KÍVÜL van, így alapból a scrollbar FÖLÖTT is
        # végigérne → jobb oldalt a scrollbar tényleges szélességével behúzzuk,
        # hogy az (expandáló) Opt státusz fejléc pontosan a sorok széléig érjen.
        vsb.bind("<Configure>",
                 lambda e: self._header_row.frame.pack_configure(padx=(2, 2 + e.width)))

        self._table_frame = tk.Frame(canvas, bg=BG)   # ide kerülnek a sorok
        _win = canvas.create_window((0, 0), window=self._table_frame, anchor="nw")
        self._table_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        # A canvas-ba ágyazott frame NEM veszi fel magától a canvas szélességét
        # (a create_window a kért méretet használja) → átméretezéskor ráhúzzuk,
        # így a sorok fill="x"-e tényleg az ablak széléig ér (az Opt státusz
        # expand-ja a maradék szélességet kapja). Kis ablaknál a természetes
        # (kért) szélesség marad, hogy a cellák ne nyomódjanak össze.
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfigure(
                _win, width=max(e.width, self._table_frame.winfo_reqwidth())))

        # Egérgörgő csak akkor görget, ha a kurzor a tábla fölött van
        def _on_wheel(e):
            canvas.yview_scroll(int(-e.delta / 120), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        self.rows: dict[str, PairRow] = {}

        # ── Dashboard 2.0 (opcionális) ──────────────────────────────────
        # `dashboard.layout = "live2"` → a 2.0 tábla (fix–görgethető–fix,
        # összecsukható blokkok, per-stratégia oszlopok). Alapértelmezés a
        # `classic`: az 1. körben HÁROM elrendezés bukott meg, ezért a 2.0 nem
        # veszi át a helyét, amíg nem bizonyított — a `self.rows` üresen marad,
        # így a classic frissítő-ág (`hasattr`/üres ciklus) magától kimarad.
        if self._is_table_layout():
            self._build_live2(self._table_frame)
            tk.Frame(parent, bg=FG_GRAY_DIM, height=1).pack(fill="x", padx=2, pady=2)
            self.lbl_status = tk.Label(parent, text=_t("gui.indulas"), bg=BG,
                                       fg=FG_GRAY, font=small_font)
            self.lbl_status.pack(side="bottom", pady=4)
            self._make_error_badge(parent, small_font)
            return

        for idx, (symbol, pair_cfg) in enumerate(self.cfg["pairs"].items()):
            if not isinstance(pair_cfg, dict):
                continue
            self.rows[symbol] = PairRow(
                self._table_frame, symbol, idx, self._columns,
                on_run=self._handle_run, on_opt=self._handle_opt,
                on_delete=self._handle_delete, on_risky=self._handle_risky,
                on_name_click=self._show_instrument_settings,
                mono_font=mono_font, small_font=small_font,
                on_status_click=self._show_opt_log,
                on_marker_click=self._show_strategy_params,
                on_opt_menu=self._handle_opt_menu,
                on_tfalign=self._show_tfalign_settings)
            self._bind_ctrl_width_sync(self.rows[symbol])

        self._apply_filter_sort()

        tk.Frame(parent, bg=FG_GRAY_DIM, height=1).pack(fill="x", padx=2, pady=2)
        self.lbl_status = tk.Label(parent, text=_t("gui.indulas"), bg=BG, fg=FG_GRAY, font=small_font)
        self.lbl_status.pack(side="bottom", pady=4)
        self._make_error_badge(parent, small_font)

    def _make_error_badge(self, parent, font):
        """A hiba-jelző címke (alapból REJTVE — nulla hibánál nincs mit mondani)."""
        self.lbl_errors = tk.Label(parent, text="", bg=BG, fg=FG_RED, font=font)
        self.lbl_errors.bind("<Button-1>", self._open_log)
        # ⚠ PIAC-ÁLLAPOT: szintén csak akkor látszik, ha van mit mondani. Nyitott
        # piacon egy állandó „minden nyitva" felirat ugyanolyan zaj volna, mint
        # egy mindig kint lévő „nincs hiba".
        self.lbl_market = tk.Label(parent, text="", bg=BG, fg=FG_GRAY, font=font)

    # ── Dashboard 2.0 tábla ──────────────────────────────────────────────
    def _layout_mode(self) -> str:
        """`canvas` (ALAP) vagy `classic`. A configból: `dashboard.layout`.

        A `live2` (widget-alapú 2.0 tábla) v2.7.0-ban megszűnt: ugyanazt mutatta,
        mint a `canvas`, csak cellánként két widgetből — a cél-skálán (30
        instrumentum × 10 stratégia) 6427 widgetből, 13 mp-es újraépítéssel. A
        régi config-érték NEM hiba: `canvas`-ra fordítjuk, hogy egy frissítés
        után senkinek ne álljon meg a felülete."""
        v = str((self.cfg.get("dashboard") or {}).get("layout", "canvas"))
        return "canvas" if v == "live2" else v

    def _is_table_layout(self) -> bool:
        """A 2.0 tábla fut-e (szemben a `classic`-kal)?

        Ami ettől függ, az a TÁBLA szerkezetéből következik: a saját fejléc-sáv,
        a jelmagyarázat és a P&L-mód."""
        return self._layout_mode() != "classic"

    def _show_legend(self) -> bool:
        """Látszik-e a felső jelmagyarázat-sáv (`dashboard.show_legend`).

        HIÁNYZÓ kulcs → az ELRENDEZÉS dönt: `classic`-ban BE (a szín-jelmagyarázat
        ott érvényes: a szimbólum állapot szerint színeződik, és a soron ott az
        „R" preset-gomb), `live2`-ben KI (ott egyik elem sem igaz).

        Így senki nem veszít: a régi nézet változatlan, a 2.0-ból eltűnik a
        félrevezető sáv, és aki mégis kéri, egy kulccsal visszakapja."""
        v = (self.cfg.get("dashboard") or {}).get("show_legend")
        if v is None:
            return not self._is_table_layout()
        return bool(v)

    def _build_live2(self, parent):
        """A 2.0 tábla felépítése. A sor-adatot a `dashboard.row_source` állítja
        elő a motor pillanatképeiből — itt csak a forrásokat kötjük be."""
        from dashboard import theme as _t
        from dashboard.canvas_table import CanvasTable as _Table
        self._live2 = _Table(
            parent, _t.fonts(), rows=self._live2_visible_rows(),
            collapsed={"pnl_mode": self._pnl_display(),
                       # Mely kapu-oszlopok látszanak és milyen sorrendben —
                       # a Beállítások „Kapuk" fülének eredménye.
                       "gate_columns": _gate_layout.enabled_columns(self.cfg)},
            on_close=self._handle_delete)
        self._live2.frame.pack(fill="both", expand=True)

    def _pnl_display(self) -> str:
        """A `Pozíció` / `Napi P&L` cellák tartalma: `money` | `r` | `both`.

        ALAPÉRTELMEZÉS: `money` (csak dollár). A „mindkettő" azért nem az, mert
        R csak akkor van, ha a belépéskori kockázat rögzült — enélkül a cella
        fele üresen áll, és a tábla ettől „szétesik". Configból:
        `dashboard.pnl_display`."""
        from dashboard.live_row import PNL_MODES
        v = str((self.cfg.get("dashboard") or {}).get("pnl_display", "money"))
        return v if v in PNL_MODES else "money"

    def _live2_strategies(self, symbol: str) -> list:
        """A soron megjelenő stratégiák. MINDEN sorban ugyanaz a lista kell
        legyen, különben a tábla oszlopai nem állnának egy vonalban — ezért a
        config `available_strategies`-éből dolgozunk, nem a pár sajátjából."""
        from strategy import available_strategy_names
        return list(available_strategy_names(self.cfg))

    def _live2_visible_rows(self) -> list:
        """A MEGJELENÍTENDŐ sorok: keresés + „STOPPED elrejtése" alkalmazva.

        A 2.0 az ADATOT szűri (nem a widgeteket csomagolja újra, mint a classic),
        így a viselkedés tkinter nélkül is mérhető. A rendezést a tábla maga
        végzi, mert a fejléc-kattintás ott keletkezik."""
        from dashboard import row_source as _rsrc
        return _rsrc.filter_rows(
            self._live2_rows(),
            search=(self._search_var.get() if hasattr(self, "_search_var") else ""),
            hide_stopped=(self._hide_stopped_var.get()
                          if hasattr(self, "_hide_stopped_var") else False))

    def _live2_rows(self) -> list:
        """A 2.0 sorok adata. Minden külső forrás ITT kötődik be — a leképezés
        maga tiszta és tesztelt (`dashboard/row_source.py`)."""
        from dashboard import row_source as _rsrc
        from core import position_meta as _pm
        try:
            from trading.live_trader import strategy_of_ticket as _owner
        except Exception:
            _owner = None
        positions = (getattr(self, "_mt5_cache", {}) or {}).get("positions_detail") or []
        syms = [s for s, p in self.cfg["pairs"].items() if isinstance(p, dict)]

        # ⚠ NYITOTT MT5-CHARTOK — KÖRÖNKÉNT EGYSZER. Mappa-listázás; páronként
        # lekérdezve 12-30× futna feleslegesen minden frissítésnél. A hiba, amit
        # megelőz: „csak jelzés" módban álló pár, amihez nincs nyitott chart —
        # a jelzés sehol nem jelenik meg, és eddig semmi nem szólt róla.
        try:
            from core import mt_charts as _mch
            # Szintén a fő szál útja: könyvtár-glob + fájlonkénti stat a MT5
            # Common mappában. A heartbeat 90 mp-ig érvényes (MAX_AGE_SEC), így
            # egy 5 mp-es memó semmit nem torzít — a `mt_charts` viszont TISZTA
            # marad (a tesztjei frissen írt fájlt olvasnak vissza).
            _now = time.monotonic()
            if _now - getattr(self, "_open_charts_at", -1e9) < 5.0:
                _open_charts = self._open_charts_memo
            else:
                _open_charts = _mch.open_symbols()
                self._open_charts_memo, self._open_charts_at = _open_charts, _now
        except Exception:
            _open_charts = set()

        # ⚠ NYITVA VAN-E A PIAC. A HÁTTÉRSZÁL már kiszámolta (`_refresh_price`),
        # itt csak összeszedjük — a fő szálon EGYETLEN MT5-hívás sincs.
        _market = {s: (getattr(ds, "session", None) or {})
                   for s, ds in (self.dashboard_ref or {}).items()}

        rows = []
        for sym in syms:
            ds = self.dashboard_ref.get(sym)
            if ds is None:
                continue
            pc = self.cfg["pairs"].get(sym) or {}
            rows.append(_rsrc.row_data(
                sym, ds, self._live2_strategies(sym), self.cfg,
                getattr(ds, "params", None) or {}, pc,
                positions=positions, owner_of=_owner, risk_of=_pm.risk_of,
                quality_of=self._live2_quality,
                opt_of=self._live2_opt,
                live_of=self._strategy_live,
                stage_order_of=self._live2_stage_order,
                opt_enabled_of=self._live2_opt_enabled,
                opt_state_of=self._live2_opt_state,
                enabled_of=self._strategy_enabled,
                open_charts=_open_charts,
                market_states=_market,
                on_toggle=self._handle_run_strategy,
                on_opt=self._live2_opt_click,
                on_stages=self._show_strategy_params,
                on_symbol=self._show_instrument_settings,
                on_align=self._show_tfalign_settings,
                on_spread=self._show_spread_params,
                on_market=self._show_market_gate,
                on_momentum=self._show_momentum_gate,
                on_cost=self._show_cost_gate,
                on_volatility=self._show_volatility_gate))
        return rows

    def _strategy_enabled(self, symbol: str, name: str) -> bool:
        """Engedélyezve van-e ez a stratégia EZEN a páron (`pairs.<sym>.strategies`)?

        A 2.0 sor MINDEN páron ugyanazt a stratégia-listát rajzolja
        (`_live2_strategies` → `available_strategies`), különben az oszlopok nem
        állnának egy vonalban. A MOTOR viszont a pár saját listájából dolgozik —
        ez a metódus hozza vissza a különbséget a felületre, hogy a sor ne
        ígérjen olyat, amit a motor nem teljesít."""
        from strategy import enabled_strategy_names
        return name in (enabled_strategy_names(self.cfg, symbol) or [])

    def _strategy_live(self, symbol: str, name: str) -> bool:
        """Kereskedik-e ÉPP ez a (pár, stratégia)?

        A képlet SZÓ SZERINT a motoré (`live_trader.run`):

            _active = _enabled & _intent
                      ↑ a pár `strategies` listája  ↑ a run_state szándék

        Korábban itt csak a SZÁNDÉK szerepelt, az `available_strategies` listával
        felkínálva — így egy olyan stratégia is „futónak" látszott, ami nincs
        engedélyezve a páron, és amivel a motor SOHA nem futott. A `run_state`
        bejegyzése ilyenkor is ott marad a configban (nem takarítjuk: ha újra
        engedélyezed a stratégiát, a korábbi szándékod érvényes) — ezért nem elég
        a szándékot nézni.

        EGY igazságforrás: a sor Play/Stop jelzése, az OPT engedélyezettsége és a
        „STOPPED elrejtése" szűrő is ezt hívja."""
        from core import run_state as _rst
        from strategy import enabled_strategy_names
        _enabled = enabled_strategy_names(self.cfg, symbol) or []
        if name not in _enabled:
            return False
        return name in (_rst.live_strategies(self.cfg, symbol, _enabled) or [])

    def _live2_opt_enabled(self, symbol: str, name: str) -> bool:
        """Optimalizálható-e MOST ez a (pár, stratégia)? Nem, ha kereskedik (a
        futás végén felülíródna a paraméterfájlja), és nem KIVEZETÉS alatt sem
        (ott minden stratégia pozíciót kezel). Pontosan az a két feltétel, amit
        az `OptimizerController.request_optimize` is ellenőriz — így a halvány
        gomb nem ígér mást, mint amit a kattintás tenne."""
        if self.instrument_state.get(symbol) == "CLOSING":
            return False
        return not self._strategy_live(symbol, name)

    def _live2_opt_state(self, symbol: str, name: str) -> str:
        """Az OPT vezérlő MORPH-állapota: `""` | `"running"` | `"queued"`.

        Ugyanaz a logika, amit a `_live2_opt_click` is követ (fut → leállítás,
        sorban → törlés, egyébként indítás) — a gomb FELIRATA így sosem ígér
        mást, mint amit a kattintás tesz."""
        try:
            st = _opt_activity.state_of(symbol, name)
        except Exception:
            return ""
        if st == _opt_activity.RUNNING:
            return "running"
        if st == _opt_activity.QUEUED:
            return "queued"
        return ""

    def _open_gate_dialog(self, symbol: str, gate_key: str):
        """A kapu SAJÁT beállító ablaka (`dashboard/gate_dialog.py`).

        MIÉRT NEM a stratégia paraméter-ablaka. A `Spread` cella korábban a teljes
        wpr_sma-paraméterlistát nyitotta meg abban a reményben, hogy a felhasználó
        megtalálja benne a „Végrehajtás" kategóriát — miközben a spread-kapunak
        mindössze három saját száma van, és azok stratégia-FÜGGETLENEK. Most
        minden kapu ugyanazt a vázat kapja: mért állapot → saját számok →
        per-stratégia hatás."""
        from dashboard.gate_dialog import open_gate_dialog
        ds = self.dashboard_ref.get(symbol)
        pc = self.cfg.get("pairs", {}).get(symbol) or {}
        # A MÉRT állapot pontosan az, amiből a kapu dönt — ugyanaz a ctx, amit a
        # sor is kap (`row_source`), nem külön számolt „kb. ugyanaz".
        try:
            from core import gates as _g
            ctx = _g.ctx_from_state(ds, getattr(ds, "params", None) or {}, pc)
        except Exception:
            ctx = {}
        open_gate_dialog(
            self.root, self.cfg, symbol, gate_key,
            self._live2_strategies(symbol), ctx=ctx,
            all_symbols=[s for s, p in self.cfg.get("pairs", {}).items()
                         if isinstance(p, dict)],
            on_saved=lambda: self._on_gate_saved(symbol))

    def _on_gate_saved(self, symbol: str):
        """Mentés után: config.json kiírása + a pár adatainak frissítése, hogy a
        sor AZONNAL az új küszöbbel számoljon (különben a következő kör
        piaci-adat-frissítéséig a régi határ látszana)."""
        try:
            self._save_main_config()
        except Exception as ex:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "A kapu-beállítás mentése elbukott: %s", ex)
        # A chart azonnal kövesse a rajz-kapcsolókat (SMA-vonalak, piac-sáv):
        # egyszeri CLEAR + friss pillanatkép. A viz-modell nem töröl magától, így
        # enélkül a levett vonalak a következő paraméter-váltásig ottmaradnának.
        try:
            from trading import live_trader as _lt
            _lt.request_viz_clear(symbol)
        except Exception:
            pass
        threading.Thread(target=lambda: self._refresh_pair_data(symbol),
                         daemon=True, name="GateSaveRefresh").start()

    def _show_spread_params(self, symbol: str):
        """A `Spread` cellára kattintva a SPREAD-KAPU ablaka nyílik."""
        from core import gates as _g
        self._open_gate_dialog(symbol, _g.SPREAD)

    def _show_momentum_gate(self, symbol: str):
        """A `Lendület` cellára kattintva a LENDÜLET-KAPU ablaka nyílik."""
        from core import gates as _g
        self._open_gate_dialog(symbol, _g.MOMENTUM)

    def _show_cost_gate(self, symbol: str):
        """A `Költség` cellára kattintva a KÖLTSÉG/KOCKÁZAT kapu ablaka nyílik."""
        from core import gates as _g
        self._open_gate_dialog(symbol, _g.COST)

    def _show_volatility_gate(self, symbol: str):
        """A Volatilitás-oszlop CSAK KIJELZÉS: az ablak megmutatja a mostani
        ATR-t, a kalibrált mércét és az engedett sávot — hatást nem állít.

        ⚠ Innen HIÁNYZOTT a `core.gates` importja (a testvér-metódusokban ott
        van). Nem derült ki, mert a `Volat.` cellát a tábla SOSEM rajzolta meg
        (lásd v2.37.1) — így erre a kódra rá sem lehetett kattintani. Amint a
        cella megjelent, azonnal `NameError`-ral szállt el."""
        from core import gates as _g
        self._open_gate_dialog(symbol, _g.VOLATILITY)

    def _show_market_gate(self, symbol: str):
        """A `Piac` cellára kattintva a PIAC-KAPU ablaka nyílik (osztályozó
        választás + mely besorolások számítanak kedvezőtlennek)."""
        from core import gates as _g
        self._open_gate_dialog(symbol, _g.MARKET)

    def _live2_stage_order(self, name: str) -> tuple:
        """A stratégia jelölő-stádiumainak KANONIKUS sorrendje (`columns()`).

        Enélkül a `row_source._stages` a `ds.strategy_cells[név]` dict MINDEN
        kulcsát pöttynek veszi — az `ml_ai` viszont a két stádium mellé a
        `ml_proba` SZÁM-cellát is beleírja, tehát egy harmadik, örökké halvány
        pötty jelent meg. A `classic` tábla sosem hibázott ebben, mert ott az
        oszlop-deklaráció `stages` mezője adja a köröket — most a 2.0 is onnan
        veszi. Ismeretlen stratégia → `None` (marad a régi, dict szerinti sorrend)."""
        try:
            from strategy import get_strategy_by_name
            for col in get_strategy_by_name(name).columns():
                if col.kind == "marker" and col.stages:
                    return tuple(k for k, _lbl in col.stages)
        except Exception:
            pass
        return None

    def _live2_opt_click(self, symbol: str, name: str, all_params: bool = False):
        """A 2.0 OPT gombja — KÖZVETLENÜL erre a stratégiára hat, menü nélkül.

        A `classic` OPT gombja szimbólum-szintű, ezért több stratégiánál választó-
        menüt nyit. A 2.0-ban a gomb a stratégia SAJÁT blokkjában ül, tehát a
        választás már megtörtént — a menü ott fölösleges kérdés lenne.

        A morph ugyanaz, mint a classicban: fut → leállítás, sorban → törlés,
        egyébként indítás. Csak a hatókör szűkebb (egy stratégia, nem az egész
        szimbólum).

        VISSZAAD: `""` ha megtörtént, különben az ELUTASÍTÁS OKA (a hívó ablak
        kiírhatja ott, ahol a gomb van)."""
        from core import opt_activity as _oa
        st = _oa.state_of(symbol, name)
        if st == "OPTIMIZING":
            self._opt_ctrl.request_stop(symbol, name)
            return
        if st == "QUEUED":
            self._opt_ctrl.cancel_queued(symbol, name)
            return
        # ⚠ KERESKEDŐ STRATÉGIÁT LEÁLLÍTUNK — nem tagadjuk meg az indítást.
        #
        # A szabály oka változatlan: a futás végén felülíródna a paraméterfájlja,
        # és egy nyíló belépő a RÉGI paraméterekkel menne. A korábbi válasz erre
        # a tiltás volt („előbb állítsd meg"), ami egy fölösleges oda-vissza:
        # a felhasználó úgyis leállítja, aztán elindítja az optimalizálást.
        # A kérése szó szerint: „nyugodtan leállíthatja a stratégiát, amíg a
        # hangolás fut… ha el van indítva, akkor állítsa le!"
        #
        # ⚠ A leállítás UGYANAZON az úton megy, mint a ■ gomb (`_stop_strategy`):
        # nyitott pozícióval KIVEZETÉS lesz belőle — a pozíciót a motor tovább
        # kezeli, új belépő viszont nem nyílik. Épp ezért biztonságos ilyenkor
        # optimalizálni: friss belépő nem születhet a régi paraméterekkel.
        #
        # ⚠ ÉS NEM NÉMÁN: a válasz megmondja, hogy leállítottuk — a stratégia
        # magától NEM indul újra a futás végén.
        _stopped = ""
        try:
            if self._opt_ctrl._strategy_live(symbol, name):
                self._stop_strategy(symbol, name)
                _stopped = (_t("gui.ctrl.stopped_for_opt", name=name))
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).exception(
                "a stratégia leállítása nem sikerült (%s/%s)", symbol, name)
        _refused = self._opt_ctrl.request_optimize(symbol, name,
                                                   all_params=all_params)
        if _refused:
            return _stopped + _refused
        if _stopped:
            self.lbl_status.config(text=_stopped)
        return _stopped

    def _live2_opt(self, symbol: str, name: str) -> str:
        """Az Opt cella PER STRATÉGIA — rövid, cellába férő alak.

        Az első változat a `self.optimizer_status`-t adta, ami SZIMBÓLUM-szintű és
        ÖSSZETETT (pl. `"Opt: wpr_sma 07/28 · ml_ai 07/28"`). A szűk cella ezt
        középre igazítva vágta, tehát a szöveg KÖZEPE látszott — élesben `ia — ·`
        jelent meg, és mindkét stratégia-blokk ugyanazt mutatta. Pontosan az a
        kétértelműség, amit a 2.0 orvosolni akar.

        Most: ha ez a stratégia ÉPP fut, a HALADÁSA (pl. `12%` — a terv 2. pontja:
        „dátum VAGY folyamat-százalék"); különben a SAJÁT utolsó optimalizálásának
        dátuma. A `fut…` csak addig áll ott, amíg az első haladás-jelentés meg nem
        érkezik (az adat-előkészítés alatt még nincs trial)."""
        try:
            from core import opt_activity as _oa
            if _oa.busy(symbol, name):
                if _oa.state_of(symbol, name) != _oa.RUNNING:
                    return "sorban"
                pct = _oa.progress_pct(symbol, name)
                return f"{pct}%" if pct is not None else "fut…"
        except Exception:
            pass
        d = opt_done_date(symbol, name)
        return d.strftime("%m/%d") if d else "—"

    def _live2_quality(self, symbol: str, name: str):
        """A minősítés PER STRATÉGIA — a stratégia SAJÁT mentett eredményéből.

        A `ds.opt_grade` szimbólum-szintű, tehát több stratégiánál mindig az
        elsődlegesét mutatná; pont ez a kétértelműség, amit a 2.0 orvosol. Szűk
        kivétel-kezelés: a `NameError`/elírás ne látszódjon adathiánynak (ez az
        1. körben a Minőség-oszlopot némán „—"-re állította)."""
        from core.params_store import params_file
        from strategy import get_strategy_by_name

        def _load(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)

        # ⚠ Gyorsítótáron át: ez a fő szál képfrissítési útja (lásd a
        # `_DISPLAY_FS_CACHE` melletti megjegyzést). Enélkül soronként egy
        # open()+json.load() futott 3 mp-enként.
        data = _DISPLAY_FS_CACHE.get(params_file(symbol, name), _load)
        if not isinstance(data, dict):
            return None
        # ⚠ A KÓD IS MEGY: a cella SZÖVEGE fordítható, de a rendezés és a szín a
        # kódra épül. Enélkül angolra kapcsolva a „Minőség" oszlop rendezése
        # némán ábécésorrendre esne vissza (Bad < Fair < Good), a szín pedig
        # szürkére — mindkettő hiba nélkül, észrevétlenül.
        _s = get_strategy_by_name(name)
        code, col, _reason = _s.grade_code(data.get("test_summary", {}), self.cfg)
        return (_quality.label(code) if code else "—", col, code)

    def _on_header_click(self, col_idx: int):
        if self._sort_col == col_idx:
            if self._sort_dir == 1:
                self._sort_dir = -1
            else:
                self._sort_col = None
                self._sort_dir = 1
        else:
            self._sort_col = col_idx
            self._sort_dir = 1
        self._header_row.set_sort(self._sort_col, self._sort_dir)
        self._apply_filter_sort()

    @staticmethod
    def _sortable(v):
        """Vegyes típusú értékeket összehasonlíthatóvá tesz: (rang, érték)."""
        if isinstance(v, (int, float)):
            return (0, v)
        s = str(v)
        try:
            return (0, float(s.replace("%", "").replace("$", "")
                              .replace("+", "").replace("▲", "").replace("▼", "").strip()))
        except ValueError:
            return (1, s)

    def _sort_key(self, symbol: str):
        if self._sort_col is None:
            return (0, symbol)
        key = self._columns[self._sort_col].key
        ds  = self.dashboard_ref.get(symbol)
        if ds is None:
            return (1, "")
        if key == "symbol":
            return (0, symbol)
        if key == "bid":      return self._sortable(ds.bid if ds.bid is not None else 0)
        if key == "ask":      return self._sortable(ds.ask if ds.ask is not None else 0)
        if key == "change":   return self._sortable(ds.change_pct if ds.change_pct is not None else 0)
        if key == "spread":   return self._sortable(ds.spread_pts)
        if key == "position": return self._sortable(ds.position_pnl if ds.position_pnl is not None else 0)
        if key == "daily":    return self._sortable(ds.daily_pnl)
        if key == "opt":      return self._sortable(self.optimizer_status.get(symbol, ""))
        col = self._columns[self._sort_col]
        if col.kind == "countdown":
            return self._sortable(ds.timeframe_remaining.get(col.timeframe_min, 0))
        cell = ds.strategy_cells.get(key)
        return self._sortable(cell[0] if cell else "—")

    def _bind_ctrl_width_sync(self, row):
        """A sor gombsor-keretének TÉNYLEGES pixel-szélességét a fejléc Vezérlés
        cellájára tükrözi (fix karakter-szélesség helyett pontos igazítás).
        Minden sor ugyanakkora gombsort kap, így bármelyik sor jó forrás."""
        row.ctrl_frame.bind(
            "<Configure>",
            lambda e: self._header_row.sync_ctrl_width(e.width))

    def _apply_filter_sort(self):
        # A 2.0 tabla az ADATOT szuri (a classic a widgeteket csomagolja ujra) —
        # a kereso mezo es a "STOPPED elrejtese" ugyanezt a belepesi pontot hivja,
        # tehat itt agazunk el. A rendezes a 2.0-nal a fejlec-kattintasbol jon.
        if getattr(self, "_live2", None) is not None:
            self._live2.refresh(self._live2_visible_rows())
            return
        search = self._search_var.get().upper().strip() if hasattr(self, "_search_var") else ""
        hide_stopped = self._hide_stopped_var.get() if hasattr(self, "_hide_stopped_var") else False

        visible = []
        for symbol in self.rows:
            if search and search not in symbol.upper():
                continue
            st = self._display_state(symbol)
            if hide_stopped and st == "STOPPED":
                continue
            visible.append(symbol)

        if self._sort_col is not None:
            visible.sort(key=self._sort_key, reverse=(self._sort_dir == -1))

        for sym in self.rows:
            self.rows[sym].frame.pack_forget()
        for sym in visible:
            self.rows[sym].frame.pack(fill="x", padx=2, pady=0)

    # ── Instrumentum hozzáadása ──────────────────────────────────────────
    def _show_add_instrument(self):
        popup = tk.Toplevel(self.root)
        popup.title(_t("gui2.instrumentum_hozzaadasa"))
        popup.configure(bg=BG)
        popup.resizable(False, False)
        popup.grab_set()
        tk.Label(popup, text=_t("gui.elerheto_szimbolumok_mt5"), bg=BG, fg=FG_BLUE,
                 font=self._header_font).pack(padx=12, pady=(10, 4), anchor="w")
        search_var = tk.StringVar()
        tk.Entry(popup, textvariable=search_var, width=28, bg=BG_HEADER, fg=FG_WHITE,
                 font=self._small_font, insertbackground=FG_WHITE,
                 relief="flat").pack(padx=12, pady=(0, 6))
        in_config = set(self.rows.keys())
        available: list = []      # háttérszálból töltődik: [(name, description), ...]
        shown_names: list = []    # a listbox aktuális soraival igazított névlista

        frame_lb = tk.Frame(popup, bg=BG)
        frame_lb.pack(padx=12, fill="both", expand=True)
        scrollbar = tk.Scrollbar(frame_lb)
        scrollbar.pack(side="right", fill="y")
        listbox = tk.Listbox(frame_lb, width=46, height=18, bg=BG_HEADER, fg=FG_WHITE,
                             selectbackground=BTN_OPT_BG, font=self._small_font,
                             relief="flat", yscrollcommand=scrollbar.set)
        listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=listbox.yview)

        def refresh_list(*_):
            q = search_var.get().upper()
            listbox.delete(0, "end")
            shown_names.clear()
            for name, desc in available:
                # Keresés névre ÉS leírásra is
                if q and q not in name.upper() and q not in (desc or "").upper():
                    continue
                label = f"{name:<12} {desc}" if desc else name
                listbox.insert("end", label)
                shown_names.append(name)
        search_var.trace_add("write", refresh_list)

        lbl_info = tk.Label(popup, text=_t("gui.szimbolumok_betoltese"), bg=BG,
                            fg=FG_GRAY, font=self._small_font)
        lbl_info.pack(pady=(4, 0))

        # MT5 szimbólum-lekérés HÁTTÉRSZÁLON; a UI-t after(0)-val frissítjük.
        def _load_syms():
            try:
                import MetaTrader5 as mt5
                syms = mt5.symbols_get()
                pairs = sorted(((s.name, getattr(s, "description", "")) for s in syms),
                               key=lambda x: x[0]) if syms else []
            except Exception:
                pairs = []
            result = [(n, d) for n, d in pairs if n not in in_config]

            def _apply():
                if not popup.winfo_exists():
                    return
                available[:] = result
                refresh_list()
                if not result:
                    lbl_info.config(
                        text=_t("gui.minden_mt5_szimbolum_mar"), fg=FG_YELLOW)
                else:
                    lbl_info.config(text=_t("gui.ctrl.symbols_found", n=len(result)), fg=FG_GRAY)
            try:
                self.root.after(0, _apply)
            except Exception:
                pass
        threading.Thread(target=_load_syms, daemon=True, name="MT5Symbols").start()

        def add_selected():
            sel = listbox.curselection()
            if not sel:
                return
            self._add_instrument(shown_names[sel[0]])
            popup.destroy()

        btn_frame = tk.Frame(popup, bg=BG)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text=_t("gui.hozzaadas"), bg=BTN_PLAY_BG, fg=BTN_PLAY_FG,
                  font=self._small_font, relief="flat",
                  command=add_selected).pack(side="left", padx=6)
        tk.Button(btn_frame, text=_t("btn.cancel"), bg=BTN_DIS_BG, fg=BTN_DIS_FG,
                  font=self._small_font, relief="flat",
                  command=popup.destroy).pack(side="left", padx=6)
        listbox.bind("<Double-Button-1>", lambda _: add_selected())

    def _add_instrument(self, symbol: str):
        if symbol in self.rows:
            return

        # MT5 symbol_info lekérés HÁTTÉRSZÁLON (MT5_LOCK alatt), majd a config-írás
        # és a widget-építés a FŐ szálon (tkinter csak onnan biztonságos).
        def _work():
            point_size, pv1_point, spread_points = 0.0001, 10.0, 1.5
            min_lot, lot_step, max_lot = 0.01, 0.01, 0.0
            description = ""
            try:
                import MetaTrader5 as _mt5
                from core.mt5_connector import MT5_LOCK
                with MT5_LOCK:
                    info = _mt5.symbol_info(symbol)
                if info:
                    description = getattr(info, "description", "") or ""
                    # A PONT a bróker natív egysége — nincs digits-alapú
                    # szorzás (az a pipet adná).
                    point_size = float(info.point)
                    tv, ts = info.trade_tick_value, info.trade_tick_size
                    pv1_point = round(tv / ts * point_size, 4) if ts > 0 else tv
                    spread_points = round(info.spread * info.point / point_size, 1) \
                                  if point_size > 0 else 1.5
                    # Lot-korlátok a brókertől — enélkül az optimalizálás/backteszt elszáll
                    min_lot  = getattr(info, "volume_min", 0.01) or 0.01
                    lot_step = getattr(info, "volume_step", 0.01) or 0.01
                    # FELSŐ korlát is: nagy egyenlegnél / szűk stopnál a számított lot
                    # fölé mehet, és a megbízás `10014 Invalid volume`-mal bukna el.
                    max_lot  = getattr(info, "volume_max", 0.0) or 0.0
            except Exception:
                pass
            try:
                self.root.after(
                    0, lambda: self._finalize_add_instrument(
                        symbol, point_size, pv1_point, spread_points, description,
                        min_lot, lot_step, max_lot))
            except Exception:
                pass
        threading.Thread(target=_work, daemon=True, name="MT5AddInstr").start()

    def _finalize_add_instrument(self, symbol, point_size, pv1_point, spread_points,
                                 description="", min_lot=0.01, lot_step=0.01,
                                 max_lot=0.0):
        """A fő szálon fut: config-írás + dashboard state + új tábla-sor."""
        if symbol in self.rows:
            return
        self.cfg["pairs"][symbol] = {
            "enabled": False, "point_size": point_size, "pv1_point": pv1_point,
            "min_lot": min_lot, "lot_step": lot_step,
            "backtest_spread_points": spread_points, "sess_start": 0, "sess_end": 24,
            "description": description,
        }
        if max_lot:
            self.cfg["pairs"][symbol]["max_lot"] = max_lot
        self._save_main_config()

        from trading.live_trader import PairDashboardState
        self.dashboard_ref[symbol] = PairDashboardState(
            symbol=symbol, trained=False, enabled=False)
        self.instrument_state[symbol] = "STOPPED"
        self.optimizer_status[symbol] = ""

        idx = len(self.rows)
        self.rows[symbol] = PairRow(
            self._table_frame, symbol, idx, self._columns,
            on_run=self._handle_run, on_opt=self._handle_opt,
            on_delete=self._handle_delete, on_risky=self._handle_risky,
            on_name_click=self._show_instrument_settings,
            mono_font=self._mono_font, small_font=self._small_font,
            on_status_click=self._show_opt_log,
            on_marker_click=self._show_strategy_params,
            on_opt_menu=self._handle_opt_menu,
            on_tfalign=self._show_tfalign_settings)
        self._bind_ctrl_width_sync(self.rows[symbol])
        self._apply_filter_sort()

        # Frissen felvett instrumentum → AZONNAL töltsük le az előzmény-adatot.
        # Enélkül az első Backtest/Opt „nincs letöltött adat"-tal állna meg (a
        # letöltés eddig csak az Opt indításakor futott le).
        self._start_history_download(symbol)

    def _start_history_download(self, symbol: str, on_done=None):
        """Előzmény-adat (M15/M1…) letöltése KÜLÖN PROCESSZBEN, a sor Opt-státuszában
        (és a naplóban) visszajelezve. Az engedélyezett stratégiák időkereteit tölti
        (union), hogy minden stratégia backtestje/optimalizálása futtatható legyen.

        Miért külön processz és nem szál? A tick→bar `resample()` CPU-kötött pandas-
        munka, ami havonta több millió tick felett fut és TARTJA a Python GIL-t — egy
        háttérszál emiatt ugyanúgy befagyasztotta a Tkinter főciklust (a watchdog
        „a FŐ SZÁL … nem frissült" jelzései). Külön processznek SAJÁT GIL-je (és saját
        MT5-sessionje) van → a GUI végig reszponzív marad. A processzek közti
        parquet-ütközést a `download_history._history_lock` fájl-alapú zára gátolja.

        `on_done`: opcionális callback(ok: bool, msg: str) a FŐ szálon."""
        try:
            from strategy import enabled_strategy_names, get_strategy_by_name
            tfs = []
            for nm in enabled_strategy_names(self.cfg, symbol) or [self.strategy.name]:
                for t in get_strategy_by_name(nm).timeframes():
                    if t.label not in tfs:
                        tfs.append(t.label)
        except Exception:
            tfs = ["M15", "M1"]

        def _short(line: str) -> str:
            """A letöltő stdout-sorából tömör sor-státusz (a cella keskeny)."""
            s = line.strip()
            if s.startswith(_t("gui2.statusz")):
                return s[len(_t("gui2.statusz")):].strip() or _t("gui2.letoltes")
            # havi haladás: „2025-08 ... 7,704,574 tick -> 42,214 bar  (5.5s)"
            if len(s) >= 8 and s[4] == "-" and s[7] == " " and s[:4].isdigit():
                return _t("gui.ctrl.downloading", symbol=s[:7])
            # naplósor: „… INFO  BTCJPY M1 — … mentve …" → az üzenet-rész
            for lvl in ("WARNING", "ERROR", "INFO"):
                i = s.find(lvl)
                if i != -1:
                    tail = s[i + len(lvl):].strip()
                    if tail:
                        return tail[:60]
            return s[:60]

        def _reader():
            import os
            import subprocess
            import logging as _logging
            _log = _logging.getLogger("history")
            cmd = [sys.executable, "-u",
                   str(ROOT / "tools" / "download_history.py"),
                   "--symbol", symbol, "--tfs", ",".join(tfs)]
            # ⚠ A gyerek is UTF-8-ban ÍRJON, mert mi úgy OLVASSUK.
            # Windowson a Python a CSŐRE írva a területi kódolást használja
            # (`locale.getpreferredencoding`, magyar rendszeren cp1250) — a szülő
            # viszont `encoding="utf-8"`-cal olvas, így minden ékezet és nyíl
            # `?`-re romlott a naplóban. A `PYTHONIOENCODING` a gyerek stdout-ját
            # állítja át; enélkül a két oldal némán MÁS kódolást használ.
            _env = dict(os.environ, PYTHONIOENCODING="utf-8")
            kwargs = dict(cwd=str(ROOT), stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True,
                          encoding="utf-8", errors="replace", bufsize=1,
                          env=_env)
            if os.name == "nt":
                kwargs["creationflags"] = 0x08000000   # CREATE_NO_WINDOW
            try:
                proc = subprocess.Popen(cmd, **kwargs)
            except Exception as ex:
                self.optimizer_status[symbol] = f"Hiba: {ex}"
                if on_done is not None:
                    try:
                        self.root.after(0, lambda: on_done(False, str(ex)))
                    except Exception:
                        pass
                return

            last = ""
            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                last = line
                self.optimizer_status[symbol] = _short(line)
                _log.info("[%s] %s", symbol, line)   # a napló is lássa a haladást
            ok = (proc.wait() == 0)
            self.optimizer_status[symbol] = (
                _t("gui2.adat_kesz") if ok else
                _t("gui.download_failed",
                   msg=_short(last) or _t("gui.download_failed_generic")))
            if on_done is not None:
                try:
                    self.root.after(0, lambda: on_done(ok, last))
                except Exception:
                    pass

        self.optimizer_status[symbol] = _t("gui2.elozmeny_letoltese")
        threading.Thread(target=_reader, daemon=True,
                         name=f"History-{symbol}").start()

    def _start_startup_gap_fill(self):
        """INDÍTÁSKOR pótolja a hiányzó előzmény-adatot (gap) minden aktív páron.

        Enélkül a leállás alatt keletkezett rés csak akkor tűnt fel, amikor egy
        Backtest/Opt már beleütközött — a `wpr_sma` M15-ablaka viszont MÉLY
        warmupot kér, tehát a hiányzó gyertyák némán MÁS jelzést adnak, mint az
        él. A pótlás ugyanazon a közös úton fut, mint az új instrumentum
        felvétele (`_start_history_download` → külön processz, fájl-zár).

        Miért SOROSAN? Minden letöltés saját processzt és MT5-sessiont nyit;
        11 pár egyszerre fölöslegesen terhelné a brókerszervert és a gépet, és a
        sor-státusz is olvashatatlanná válna. Így egyszerre legfeljebb egy fut.

        A per-szimbólum fájl-zár miatt ez biztonságosan együtt él egy közben
        induló Opt/Backtest letöltéssel: a második a kész fájlt találja."""
        import logging as _logging
        _log = _logging.getLogger(__name__)
        pending = [s for s, p in (self.cfg.get("pairs") or {}).items()
                   if isinstance(p, dict) and p.get("enabled", False)]
        if not pending:
            return
        _log.info("Indítási gap-letöltés: %d pár sorba állítva.", len(pending))

        def _next(ok: bool = True, msg: str = ""):
            if not pending:
                _log.info("Indítási gap-letöltés: kész.")
                return
            self._start_history_download(pending.pop(0), on_done=_next)

        _next()

    # ── JSON szintaxis-színezés (Text widgethez) ─────────────────────────
    @staticmethod
    def _highlight_json(text):
        import re
        content = text.get("1.0", "end-1c")
        for tag in ("json_key", "json_str", "json_num", "json_bool"):
            text.tag_remove(tag, "1.0", "end")
        token = re.compile(
            r'"(?:\\.|[^"\\])*"'                  # idézőjeles szöveg
            r'|-?\d+\.?\d*(?:[eE][+-]?\d+)?'      # szám
            r'|\b(?:true|false|null)\b')          # logikai / null
        for m in token.finditer(content):
            s, e, tok = m.start(), m.end(), m.group()
            if tok[0] == '"':
                after = content[e:e + 8].lstrip()
                tag = "json_key" if after.startswith(":") else "json_str"
            elif tok in ("true", "false", "null"):
                tag = "json_bool"
            else:
                tag = "json_num"
            text.tag_add(tag, f"1.0+{s}c", f"1.0+{e}c")

    # ── config.json perzisztálás (CSAK a váz-szekciók) ───────────────────
    def _save_main_config(self) -> bool:
        """A config.json-ba csak a VÁZ-szekciókat írjuk (a stratégia-config a
        saját fájljában él) — így a merge-elt futásidejű cfg nem szennyezi vissza.

        Visszaad: sikerült-e. HIBA esetén az állapotsorba írunk: korábban egy néma
        `except Exception: pass` állt itt, tehát egy zárolt/írhatatlan fájlnál a
        Play/Stop, a slot- és a limit-állítás úgy nézett ki, mintha megtörtént
        volna — a futásidejű cfg-ben meg is történt —, és csak ÚJRAINDÍTÁSKOR
        derült volna ki, hogy semmi nem perzisztált.

        Az atomicitásról (temp→replace) a közös `settings.save_main_config`
        gondoskodik."""
        from strategy.settings import save_main_config as _save
        err = _save(self.cfg, ROOT / "config.json")
        if err:
            self._set_status(_t("gui.ctrl.not_saved", error=err))
            return False
        return True

    # ── Megjelenés + Nyelv ───────────────────────────────────────────────
    # ⚠ NINCS külön „Megjelenés" ablak és nincs saját eszközsáv-gomb. 2026-08-31
    # óta mindkettő a `⚙ Beállítás` ablak KÜLÖN-KÜLÖN lapja (`appearance`,
    # `language`) — a felhasználó kérésére. A kódot szándékosan NEM hagytuk itt
    # másodpéldányban: két forrás előbb-utóbb elcsúszna, és a felület két helyen
    # mást mutatna ugyanarra a beállításra.

    # ── Beállítás-szerkesztő (config.json) ───────────────────────────────
    def _apply_gate_columns(self):
        """A ⚙ → Kapuk fül eredményének átvezetése a FUTÓ táblára.

        A kapu KIKAPCSOLÁSA két dolgot jelent: az oszlop eltűnik (ez itt), és a
        kapu sehol nem szól bele a kereskedésbe (az a `gates.effect_with_source`
        mester-kapcsolója, ami a configból olvas — tehát az AZONNAL él, külön
        teendő nélkül)."""
        tbl = getattr(self, "_live2", None)
        if tbl is None or not hasattr(tbl, "set_gate_columns"):
            return
        try:
            tbl.set_gate_columns(_gate_layout.enabled_columns(self.cfg))
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "A kapu-oszlopok frissítése elbukott.", exc_info=True)

    # ── Megjelenés + Nyelv lap (a ⚙ Beállítás ablakban) ──────────────────
    def _build_appearance_tab(self, parent) -> dict:
        """Téma + betűtípus egy meglévő lapra. Visszaadja a változóit.

        A BETŰ azonnal érvényesül (a `theme.fonts()` objektumok élők, minden
        widget követi őket) — így élőben lehet belőni. A SZÍNEK viszont csak
        újraindításkor: a modulok `from dashboard.theme import BG, …` alakban
        ÉRTÉK szerint kötik a neveket, a futásidejű átírás nem propagálna."""
        _orig_family = _theme.FONT_FAMILY
        _orig_size   = _theme.FONT_SIZE
        _orig_theme  = (self.cfg.get("dashboard") or {}).get(
            "theme", _theme.ACTIVE_THEME)

        frm = tk.Frame(parent, bg=BG)
        frm.pack(anchor="w", padx=12, pady=12)

        tk.Label(frm, text=_t("gui.tema"), bg=BG, fg=FG_GRAY,
                 font=self._small_font).grid(row=0, column=0, sticky="e", pady=3)
        # ⚠ A legördülő FELIRATOKAT mutat, a config KÓDOT tárol. A `theme_code`
        # fordít köztük — így a mentett érték nyelvfüggetlen marad, és a régi,
        # magyar nevű mentés is felismerhető.
        theme_var = tk.StringVar(value=_theme.theme_label(
            _theme.theme_code(str(_orig_theme))))
        _omt = tk.OptionMenu(frm, theme_var,
                             *[_theme.theme_label(c) for c in _theme.THEMES])
        _omt.config(bg=BG_HEADER, fg=FG_WHITE, font=self._small_font, relief="flat",
                    highlightthickness=0, activebackground=BG_HEADER, width=20)
        _omt["menu"].config(bg=BG_HEADER, fg=FG_WHITE)
        _omt.grid(row=0, column=1, sticky="w", padx=6, pady=3)

        # Csak a rendszeren TÉNYLEGESEN elérhető családokat kínáljuk: a hiányzót
        # a tkinter némán helyettesítené („beállítottam, de nem változott").
        try:
            from tkinter import font as _tkf
            _avail = set(_tkf.families(self.root))
        except Exception:
            _avail = set()
        _fams = [f for f in _theme.FONT_FAMILIES if not _avail or f in _avail]
        if _orig_family not in _fams:
            _fams.insert(0, _orig_family)
        tk.Label(frm, text=_t("gui.betutipus"), bg=BG, fg=FG_GRAY,
                 font=self._small_font).grid(row=1, column=0, sticky="e", pady=3)
        fam_var = tk.StringVar(value=_orig_family)
        _omf = tk.OptionMenu(frm, fam_var, *_fams)
        _omf.config(bg=BG_HEADER, fg=FG_WHITE, font=self._small_font, relief="flat",
                    highlightthickness=0, activebackground=BG_HEADER, width=20)
        _omf["menu"].config(bg=BG_HEADER, fg=FG_WHITE)
        _omf.grid(row=1, column=1, sticky="w", padx=6, pady=3)

        tk.Label(frm, text=_t("gui.betumeret"), bg=BG, fg=FG_GRAY,
                 font=self._small_font).grid(row=2, column=0, sticky="e", pady=3)
        size_var = tk.IntVar(value=_orig_size)

        def _preview(*_a):
            """Betű-előnézet ÉLŐBEN (a méret/típus azonnal átüt a felületen)."""
            try:
                _theme.apply_fonts(fam_var.get(), int(size_var.get()))
            except Exception:
                pass

        tk.Spinbox(frm, from_=_theme.FONT_SIZE_MIN, to=_theme.FONT_SIZE_MAX,
                   textvariable=size_var, width=5, bg=BG_HEADER, fg=FG_WHITE,
                   font=self._small_font, relief="flat", justify="center",
                   buttonbackground=BG_INACTIVE,
                   command=lambda: _preview()).grid(row=2, column=1, sticky="w",
                                                    padx=6, pady=3)
        fam_var.trace_add("write", _preview)
        try:
            size_var.trace_add("write", _preview)
        except Exception:
            pass
        return {"theme_var": theme_var, "fam_var": fam_var, "size_var": size_var,
                "orig_family": _orig_family, "orig_size": _orig_size,
                "preview": _preview}

    def _build_language_tab(self, parent) -> dict:
        """Nyelvválasztó egy meglévő lapra. Visszaadja a változóit.

        ⚠ A NYELVEK SAJÁT NEVÜKÖN állnak („Magyar", „English") — sosem fordítjuk
        le őket. Aki véletlenül egy számára olvashatatlan nyelvre kapcsolt, ezen
        a listán akkor is megtalálja a sajátját."""
        frm = tk.Frame(parent, bg=BG)
        frm.pack(anchor="w", padx=12, pady=12)
        tk.Label(frm, text=_t("lang.label") + ":", bg=BG, fg=FG_GRAY,
                 font=self._small_font).grid(row=0, column=0, sticky="e", pady=3)
        _orig_lang = _i18n.language()
        lang_var = tk.StringVar(value=_i18n.LANGUAGES.get(_orig_lang, _orig_lang))
        _oml = tk.OptionMenu(frm, lang_var, *_i18n.LANGUAGES.values())
        _oml.config(bg=BG_HEADER, fg=FG_WHITE, font=self._small_font, relief="flat",
                    highlightthickness=0, activebackground=BG_HEADER, width=20)
        _oml["menu"].config(bg=BG_HEADER, fg=FG_WHITE)
        _oml.grid(row=0, column=1, sticky="w", padx=6, pady=3)

        def _lang_code():
            """A választott felirat → nyelvkód (a legördülő saját neveket mutat)."""
            _lbl = lang_var.get()
            return next((c for c, n in _i18n.LANGUAGES.items() if n == _lbl),
                        _orig_lang)

        tk.Label(frm, text=_t("gui.language_note"), bg=BG, fg=FG_GRAY_DIM,
                 font=self._small_font, wraplength=380, justify="left").grid(
                 row=1, column=1, sticky="w", padx=6, pady=(2, 0))
        return {"lang_var": lang_var, "lang_code": _lang_code,
                "orig_lang": _orig_lang}

    def _show_settings(self):
        popup = tk.Toplevel(self.root)
        popup.title(_t("gui2.beallitasok_config_json"))
        popup.configure(bg=BG)
        popup.geometry("720x640")
        popup.grab_set()

        # ── ABLAK-SZINTŰ gombsor: MINDEN fül alatt ugyanaz ───────────────
        # ⚠ A CSOMAGOLÁSI SORREND itt működés, nem stílus. A `pack` a hívás
        # sorrendjében oszt helyet: ha előbb a tartalom kapná meg a területet
        # `expand=True`-val, a gombok kis ablaknál egyszerűen KISZORULNÁNAK — épp
        # ezt panaszolta a felhasználó („csak akkor jelenik meg, ha szélesebbre
        # nyitom"). Ezért a gombsor és a hibasor FOGLAL ELŐSZÖR, alulról.
        btns = tk.Frame(popup, bg=BG)
        btns.pack(side="bottom", fill="x", pady=8)
        lbl_err = tk.Label(popup, text="", bg=BG, fg=FG_RED, font=self._small_font,
                           anchor="w", justify="left", wraplength=660)
        lbl_err.pack(side="bottom", fill="x", padx=10)
        _btn_save = tk.Button(btns, text=_t("btn.save"), bg=BTN_PLAY_BG, fg=BTN_PLAY_FG,
                              relief="flat", font=self._small_font)
        _btn_save.pack(side="left", padx=(10, 6))
        # ⚠ A Mégse a BETŰ-ELŐNÉZETET is visszaállítja. Enélkül a kipróbált betű
        # a Mégse után is a felületen maradna — a felhasználó azt hinné, mégis
        # mentett. A `_megse` a lapok felépítése UTÁN kap tartalmat (a
        # `_orig_family` csak ott jön létre), ezért itt csak a keret áll.
        _btn_cancel = tk.Button(btns, text=_t("btn.cancel"), bg=BTN_DIS_BG,
                                fg=BTN_DIS_FG, relief="flat",
                                font=self._small_font)
        _btn_cancel.pack(side="left", padx=6)

        # ── BAL OLDALI FÜLEK (közös váz: `dashboard/tab_shell.py`) ───────
        from dashboard.tab_shell import TabShell
        # ⚠ A MEGJELENÉS és a NYELV KÜLÖN lap. Egy ablakba kerültek (a
        # felhasználó kérésére: „ne a főképernyőn legyen"), de nem EGY lapra:
        # a nyelv ritkán állított, egyszeri döntés, a betű/téma viszont
        # kísérletezős. Egy lapon a ritka beállítás elveszne a gyakori mellett.
        _shell = TabShell(popup, (("json", _t("tab.json")),
                                  ("gates", _t("tab.gates")),
                                  ("strategies", _t("tab.strategies")),
                                  ("telegram", _t("tab.telegram")),
                                  ("appearance", _t("gui.megjelenes")),
                                  ("language", _t("lang.label"))))
        _page = {n: _shell.page(n) for n in _shell.names()}

        # ── KAPUK lap ────────────────────────────────────────────────────
        from core import gates as _gts, gate_layout as _glay
        from dashboard.order_editor import OrderEditor
        _kp = _page["gates"]
        tk.Label(_kp, text=_t("gui.mely_kapuk_latszanak_es"),
                 bg=BG, fg=FG_BLUE, font=self._header_font, anchor="w").pack(
                 anchor="w", padx=10, pady=(10, 4))
        _gate_ed = OrderEditor(
            _kp, {k: _gts.label_of(k) for k in _gts.KEYS},
            _glay.enabled_gates(self.cfg),
            note=_t("gui2.a_kikapcsolt_kapu_oszlopa"))
        _gate_ed.frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # ── STRATÉGIÁK lap ───────────────────────────────────────────────
        _st = _page["strategies"]
        tk.Label(_st, text=_t("gui.mely_strategiak_elerhetok_es"),
                 bg=BG, fg=FG_BLUE, font=self._header_font, anchor="w").pack(
                 anchor="w", padx=10, pady=(10, 4))
        from strategy import strategy_availability as _savail
        _av_now = _savail(self.cfg)
        _strat_ed = OrderEditor(
            _st, {n: n for n in _av_now},
            [n for n, on in _av_now.items() if on],
            note=_t("gui2.a_program_a_bekapcsoltakat"))
        _strat_ed.frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # ── TELEGRAM lap ─────────────────────────────────────────────────
        # ⚠ MIÉRT KELLETT IDE KAPCSOLÓ. A válaszos kötés (`notify.answer_trading`)
        # a v3.12.0 óta MEGVOLT, de sehol nem lehetett bekapcsolni: a kulcs
        # hiányzott a configból, alapból KI, és a felületen nyoma sem volt. A
        # felhasználó jelzései kimentek a Telegramra — gomb nélkül —, és nem
        # volt honnan megtudni, hogy a funkció létezik. Egy kész funkció, amit
        # nem lehet elérni, pontosan annyit ér, mint a hiányzó.
        _tg = _page["telegram"]
        _tg_var = tk.BooleanVar(
            value=bool((self.cfg.get("notify") or {}).get("answer_trading", False)))
        tk.Checkbutton(_tg, text=_t("notify.answer_trading"), variable=_tg_var,
                       bg=BG, fg=FG_WHITE, selectcolor=BG_HEADER,
                       activebackground=BG, activeforeground=FG_WHITE,
                       font=self._small_font, anchor="w").pack(
                       anchor="w", padx=10, pady=(12, 2))
        # ⚠ EGY sor figyelmeztetés — ez az egyetlen kapcsoló a felületen, ami
        # egy CHATÜZENETBŐL valódi megbízást csinál.
        tk.Label(_tg, text=_t("notify.answer_trading.warn"), bg=BG, fg=FG_YELLOW,
                 font=self._small_font, justify="left", wraplength=620,
                 anchor="w").pack(anchor="w", padx=32, pady=(0, 10))

        # ── JSON lap (a korábbi tartalom) ────────────────────────────────
        # ⚠ A Json lap tartalma ide épül. Régen itt egy `popup = _page["json"]`
        # újrakötés állt — és a mentés végi `popup.destroy()` emiatt a LAPOT
        # törölte az ABLAK helyett: utána bármelyik fülre kattintva
        # „bad window path name" jött. A Toplevel neve marad `popup`.
        json_page = _page["json"]
        _shell.show("json")

        tk.Label(json_page, text=_t("gui.config_json_szerkesztese_menteskor"),
                 bg=BG, fg=FG_BLUE, font=self._header_font).pack(anchor="w", padx=10, pady=(10, 2))
        tk.Label(json_page, text=_t("gui.megjegyzes_itt_csak_a"),
                 bg=BG, fg=FG_GRAY, font=self._small_font, justify="left",
                 wraplength=680).pack(anchor="w", padx=10)

        txt_frame = tk.Frame(json_page, bg=BG)
        txt_frame.pack(fill="both", expand=True, padx=10, pady=4)
        sb = tk.Scrollbar(txt_frame)
        sb.pack(side="right", fill="y")
        text = tk.Text(txt_frame, bg=BG_HEADER, fg=FG_WHITE, insertbackground=FG_WHITE,
                       font=self._mono_font, wrap="none", yscrollcommand=sb.set)
        text.pack(side="left", fill="both", expand=True)
        sb.config(command=text.yview)
        # JSON szintaxis-színezés
        text.tag_configure("json_key",  foreground=FG_BLUE)
        text.tag_configure("json_str",  foreground=FG_GREEN)
        text.tag_configure("json_num",  foreground=FG_ORANGE)
        text.tag_configure("json_bool", foreground=FG_CYAN)
        # Csak a VÁZ-config látszik/szerkeszthető; a stratégia beállításai a
        # stratégia saját fájljában élnek (strategies/config/<name>.json).
        text.insert("1.0", json.dumps(main_config_view(self.cfg), indent=2, ensure_ascii=False))
        self._highlight_json(text)

        # Élő újraszínezés szerkesztés közben (debounce-olva, hogy ne akadjon)
        def _schedule_hl(_event=None):
            prev = getattr(self, "_hl_after_id", None)
            if prev:
                try:
                    popup.after_cancel(prev)
                except Exception:
                    pass
            self._hl_after_id = popup.after(200, lambda: self._highlight_json(text))
        text.bind("<KeyRelease>", _schedule_hl)

        # ⚠ A két lap KÜLÖN metódusban épül (`_build_appearance_tab`,
        # `_build_language_tab`). Nem stílus: így a teszt önmagában is meg tudja
        # nyitni és MEGNYOMNI őket, a teljes Beállítás-ablak (JSON-szerkesztő,
        # kapu- és stratégia-editor) felépítése nélkül. Enélkül csak a forrás
        # szövegét lehetne vizsgálni — az pedig nem viselkedést mér.
        _megj = self._build_appearance_tab(_page["appearance"])
        _nyelv = self._build_language_tab(_page["language"])
        theme_var, fam_var, size_var = (_megj["theme_var"], _megj["fam_var"],
                                        _megj["size_var"])
        _orig_family, _orig_size = _megj["orig_family"], _megj["orig_size"]
        _preview = _megj["preview"]
        lang_var, _lang_code = _nyelv["lang_var"], _nyelv["lang_code"]
        _orig_lang = _nyelv["orig_lang"]

        def save():
            try:
                new = json.loads(text.get("1.0", "end"))
            except Exception as e:
                lbl_err.config(text=_t("gui.json.invalid", error=e))
                return
            # Az 'Elérhető stratégiák' jelölőnégyzetek az irányadók az
            # available_strategies kulcsra (a szerkesztő JSON-ját felülírják).
            #
            # MINDIG a TELJES készletet írjuk ki, térkép alakban — a kikapcsoltat is.
            # Korábban a kulcs TÖRLŐDÖTT, ha minden stratégia be volt kapcsolva
            # („ne szennyezze a configot"), a kikapcsolt pedig egyszerűen kimaradt
            # a listából. Ennek az volt az ára, hogy a config.json nem mondta meg,
            # MI LÉTEZIK — csak azt, mi tér el az alapértelmezéstől. Két stratégiánál
            # ez zavaró volt, 4-5-nél használhatatlan.
            # A „Stratégiák" fül SORRENDBEN adja a bekapcsoltakat; a kikapcsoltak
            # utána jönnek, hogy a fájlból kiderüljön, MI LÉTEZIK (nem csak az,
            # mi tér el az alapértelmezéstől).
            _on = _strat_ed.get()
            if not _on:
                lbl_err.config(text=_t("gui.legalabb_egy_strategia_legyen2"))
                return
            chosen_av = {n: True for n in _on}
            for n in _strat_ed.disabled():
                chosen_av[n] = False
            new["available_strategies"] = chosen_av
            # A „Kapuk" fül: mely kapuk látszanak/hatnak, milyen sorrendben.
            _glay.apply_order(new, _gate_ed.get())
            # ── A MEGJELENÉS és a NYELV lap ────────────────────────────
            # ⚠ EZEKET IS a `new`-ba kell írni, nem a `self.cfg`-be: a mentés a
            # JSON-szerkesztő szövegéből építi újra a configot, tehát bármit,
            # amit közben a `self.cfg`-n állítanánk, NÉMÁN felülírna.
            # ⚠ A KULCSOT MINDIG KIÍRJUK, `false`-ként is. A projekt szokása
            # az, hogy a config csak az ELTÉRÉST rögzíti — itt viszont épp ez
            # okozta a bajt: a hiányzó kulcs miatt a funkció létezését sem
            # lehetett megtudni a fájlból. Egy pénzt érintő kapcsoló legyen
            # KIMONDVA, akkor is, ha ki van kapcsolva.
            new.setdefault("notify", {})["answer_trading"] = bool(_tg_var.get())
            _dash = new.setdefault("dashboard", {})
            _dash["language"]    = _lang_code()
            _dash["theme"]       = _theme.theme_code(theme_var.get())
            _dash["font_family"] = fam_var.get()
            _dash["font_size"]   = int(size_var.get())
            # A `new` MÁR váz-config (a szerkesztő a `main_config_view`-t mutatta),
            # ezért a nyers írót hívjuk — a nézet-szűrés pontosan egyszer fut.
            from strategy.settings import write_config_file as _write
            _err = _write(new, ROOT / "config.json")
            if _err:
                lbl_err.config(text=_err)
                return
            # In-place frissítés → a live_trader ugyanazt a dict-et látja.
            # A `new` a VÁZ-config; a stratégia beállításait újra beolvasztjuk,
            # hogy a merge-elt futásidejű cfg (indicators/quality/…) megmaradjon.
            self.cfg.clear()
            self.cfg.update(new)
            apply_strategy_config(self.cfg)
            # A kapu-oszlopok AZONNAL kövessék a beállítást (a stratégia-lista
            # változása továbbra is újraindítást kíván — az mélyebben ül).
            self._apply_gate_columns()
            _preview()          # a betű már él; a szín és a nyelv indítás után
            # ⚠ A NYELVET NEM ÁLLÍTJUK ÁT MENET KÖZBEN (`set_language`), pedig
            # technikailag lehetne. A már megépült widgetek felirata nem
            # változna, az ezután nyílóké igen — a felület fele magyar, fele
            # angol lenne. Egy KEVERT felület rosszabb, mint egy egynyelvű.
            _restart = []
            if _lang_code() != _orig_lang:
                _restart.append(_t("gui.restart.language"))
            if _theme.theme_code(theme_var.get()) != _theme.ACTIVE_THEME:
                _restart.append(_t("gui.restart.theme"))
            if _restart:
                # ⚠ AZ ABLAK NYITVA MARAD, ha van mit elmondani. Bezárva az
                # üzenet a bezárással együtt tűnne el, és a felhasználó azt
                # hinné, a nyelv azonnal átvált.
                lbl_err.config(text=_t("gui.saved_restart",
                                       what=" + ".join(_restart)), fg=FG_YELLOW)
                _btn_save.config(state="disabled")
                return
            popup.destroy()

        def _megse():
            # Az élő előnézetet vissza kell állítani, különben a Mégse után is
            # a kipróbált betű maradna a felületen.
            try:
                _theme.apply_fonts(_orig_family, _orig_size)
            except Exception:
                pass
            popup.destroy()

        # A gombsor FENT készült el (hogy kis ablaknál se szoruljon ki); a
        # mentés- és mégse-függvény csak most áll rendelkezésre, ezért itt
        # kötjük rájuk.
        _btn_save.config(command=save)
        _btn_cancel.config(command=_megse)
        popup.protocol("WM_DELETE_WINDOW", _megse)

    # ── Stratégia Paraméterek (a KÖRRE kattintva — az adott stratégiáé) ──
    def _show_strategy_params(self, symbol: str, strategy_name: str = ""):
        """A jelölő-körre kattintva az ADOTT stratégia paraméter-ablaka nyílik.
        Optimalizálatlan párnál is nyílik (alap-paraméterek); a Mentés létrehozza
        a data/optimized_params/<strategy>/<symbol>.json-t."""
        from dashboard.instrument_dialog import InstrumentParamsDialog
        from strategy import get_strategy_by_name
        strat = get_strategy_by_name(strategy_name) if strategy_name else self.strategy
        # ⚠ AZ OPTIMALIZÁLÁS INNEN INDUL. A sorból az OPT vezérlőt levettük (a
        # gomb órákra indított valamit, amiről a felület semmit nem mondott) —
        # a helyére a paraméter-ablak Futtatás szakasza lépett, ahol LÁTOD, mi
        # fog történni. A bekötés viszont sokáig HIÁNYZOTT: a szakasz csak
        # annyit írt ki, hogy „azt a főképernyő OPT gombja indítja", ami addigra
        # már nem létezett — az optimalizálás így SEHONNAN nem volt indítható.
        _dlg = InstrumentParamsDialog(
            self.root, symbol, self.cfg, strat,
            self._header_font, self._small_font, self._save_main_config,
            root_cfg=self.cfg)
        # Ugyanaz a morph, mint a régi gombé (indít / leállít / sorból kivesz) —
        # egy helyen él (`_live2_opt_click`), tehát a két út nem csúszhat szét.
        _dlg.on_optimize = self._live2_opt_click
        # A gomb ebből tudja, hogy ÉPP fut-e (akkor leállít, nem újraindít).
        from core import opt_activity as _oa
        _dlg.opt_state_of = _oa.state_of
        # ⚠ AZ ÉLŐ STÁDIUM-CELLÁK: az Áttekintés karika-magyarázata ebből
        # színezi a köreit. UGYANAZ a forrás, amiből a sor dolgozik — egy külön
        # képlet előbb-utóbb mást mutatna, mint amit magyaráz.
        _dlg.stage_cells_of = lambda sym, nm: (
            getattr(self.dashboard_ref.get(sym), "strategy_cells", {}) or {}
        ).get(nm) or {}

    def _show_instrument_params(self, symbol: str):
        """Visszafelé komp.: az elsődleges stratégia paraméterei (a Pozíciók fül
        a Symbol-névre kattintva ezt hívja)."""
        self._show_strategy_params(symbol, self.strategy.name)

    # ── Instrumentum beállítások (az instrumentum NEVÉRE kattintva) ──────
    def _show_instrument_settings(self, symbol: str):
        """Per-instrumentum beállítások TÁBLÁZATOSAN: oszlop = stratégia, sor =
        tulajdonság (aktív / vizualizáció / kötés-réteg). A korábbi sorbeli „V" és
        „K" gomb ide költözött pipa formában, és PER STRATÉGIA állítható — eddig
        pár-szintű volt, így egy több-stratégiás páron nem lehetett külön
        kikapcsolni az egyik rajzát (lásd core.viz_prefs)."""
        from strategy import (available_strategy_names, enabled_strategy_names,
                              default_strategy_name)
        from core import viz_prefs as _vp
        from core import trade_mode as _tm
        popup = tk.Toplevel(self.root)
        popup.title(_t("gui.ctrl.dialog_title", symbol=symbol))
        popup.configure(bg=BG)
        popup.grab_set()
        tk.Label(popup, text=symbol, bg=BG, fg=FG_WHITE,
                 font=self._header_font).pack(anchor="w", padx=12, pady=(12, 2))

        # ── Stratégia-táblázat ───────────────────────────────────────────────
        _names = available_strategy_names(self.cfg)
        cur    = set(enabled_strategy_names(self.cfg, symbol))
        tbl = tk.Frame(popup, bg=BG)
        tbl.pack(anchor="w", padx=12, pady=(6, 2))
        tk.Label(tbl, text="", bg=BG).grid(row=0, column=0)
        for c, n in enumerate(_names, start=1):
            tk.Label(tbl, text=n, bg=BG, fg=FG_WHITE, font=self._small_font,
                     padx=8).grid(row=0, column=c)
        # (KULCS, sor-címke, kezdőérték-függvény) — a sorrend a táblázat sorrendje.
        # ⚠ A KULCS NEM DÍSZ. Korábban a `_vars` a SOR INDEXÉVEL volt kulcsozva
        # (`_vars[(2, n)]` = vizualizáció), tehát egy új sor beszúrása némán
        # elcsúsztatta volna az összes alatta lévőt — a mentés MÁS kapcsolót
        # írt volna, mint amit a felhasználó átállított.
        _ROWS = [
            ("strategies", _t("gui2.aktiv_strategia"),
             lambda n: n in cur),
            ("viz", _t("gui2.vizualizacio_latszik"),
             lambda n: _vp.viz_on(self.cfg, symbol, n)),
            ("trades", _t("gui2.kotesek_latszanak"),
             lambda n: _vp.trades_on(self.cfg, symbol, n)),
            ("notify_trade", _t("gui2.telegram_kotes"),
             lambda n: _vp.notify_trade_on(self.cfg, symbol, n)),
            ("notify_signal", _t("gui2.telegram_jelzes"),
             lambda n: _vp.notify_signal_on(self.cfg, symbol, n)),
        ]
        # Jelölőnégyzetek — ugyanaz a recept, mint az ablak többi kapcsolójánál:
        # az `fg` ADJA A PIPA SZÍNÉT, ezért kötelező megadni. Nélküle a rendszer
        # alapértelmezett (sötét) pipája rajzolódna a sötét `selectcolor`-ra, és
        # gyakorlatilag láthatatlan lenne.
        _vars = {}          # (sor-KULCS, stratégia-név) → BooleanVar
        for r, (_kulcs, label, initial) in enumerate(_ROWS, start=1):
            tk.Label(tbl, text=label, bg=BG, fg=FG_GRAY, font=self._small_font,
                     anchor="w").grid(row=r, column=0, sticky="w", pady=1)
            for c, n in enumerate(_names, start=1):
                v = tk.BooleanVar(value=bool(initial(n)))
                _vars[(_kulcs, n)] = v
                tk.Checkbutton(tbl, variable=v, bg=BG, fg=FG_WHITE,
                               selectcolor=BG_HEADER, activebackground=BG,
                               activeforeground=FG_WHITE).grid(row=r, column=c)

        # ── Kötés-mód sor: valódi kötés vagy CSAK JELZÉS (teszteléshez) ──────
        # Nem pipa, hanem legördülő: a „nem kereskedik" állapot legyen KIÍRVA,
        # ne egy üres checkbox — ez pénzt érintő beállítás.
        _r_mode = len(_ROWS) + 1
        tk.Label(tbl, text=_t("gui.kotes_modja"), bg=BG, fg=FG_GRAY, font=self._small_font,
                 anchor="w").grid(row=_r_mode, column=0, sticky="w", pady=(4, 1))
        _mode_vars = {}
        for c, n in enumerate(_names, start=1):
            mv = tk.StringVar(value=_tm.LABELS[_tm.mode_of(self.cfg, symbol, n)])
            _mode_vars[n] = mv
            _om2 = tk.OptionMenu(tbl, mv, _tm.LABELS[_tm.MODE_LIVE],
                                 _tm.LABELS[_tm.MODE_SIGNAL])
            _om2.config(bg=BG_HEADER, fg=FG_WHITE, font=self._small_font,
                        relief="flat", highlightthickness=0,
                        activebackground=BG_HEADER)
            _om2["menu"].config(bg=BG_HEADER, fg=FG_WHITE)
            _om2.grid(row=_r_mode, column=c, padx=4, pady=(4, 1), sticky="ew")

        tk.Label(popup, text=_t("gui.a_tenyleges_mt5_kotesek"),
                 bg=BG, fg=FG_GRAY_DIM, font=self._small_font,
                 wraplength=360, justify="left").pack(anchor="w", padx=12, pady=(0, 2))
        tk.Label(popup, text=_t("gui.jelzes_modban_a_motor"),
                 bg=BG, fg=FG_YELLOW, font=self._small_font,
                 wraplength=360, justify="left").pack(anchor="w", padx=12, pady=(0, 4))
        tk.Label(popup, text=_t("gui.telegram_ertesites_magyarazat"),
                 bg=BG, fg=FG_GRAY_DIM, font=self._small_font,
                 wraplength=360, justify="left").pack(anchor="w", padx=12, pady=(0, 4))

        # ── Piac-előszűrő (piac-állapot osztályozó) — instrumentumonként EGY ──
        from core import market_strategy as _ms
        _pc0 = (self.cfg.get("pairs", {}).get(symbol, {}) or {})
        tk.Label(popup, text=_t("gui.piac_eloszuro_piac_allapot"),
                 bg=BG, fg=FG_GRAY, font=self._small_font).pack(anchor="w", padx=12, pady=(8, 2))
        ms_var = tk.StringVar(value=(_ms.market_name_of(_pc0) or "Nincs"))
        _om = tk.OptionMenu(popup, ms_var, *(["Nincs"] + _ms.registered_market_names()))
        _om.config(bg=BG_HEADER, fg=FG_WHITE, font=self._small_font, relief="flat",
                   highlightthickness=0, activebackground=BG_HEADER)
        _om["menu"].config(bg=BG_HEADER, fg=FG_WHITE)
        _om.pack(anchor="w", padx=20)
        viz_var = tk.BooleanVar(value=bool(_pc0.get("market_viz", True)))
        tk.Checkbutton(popup, text=_t("gui.piac_allapot_sav_a"), variable=viz_var,
                       bg=BG, fg=FG_WHITE, selectcolor=BG_HEADER, font=self._small_font,
                       activebackground=BG, activeforeground=FG_WHITE).pack(anchor="w", padx=20)

        # ── Kockázatcsökkentő PRESET — instrumentumonként EGY ────────────────
        # MIÉRT ITT. A preset PER INSTRUMENTUM él (nem per stratégia és nem per
        # pozíció), tehát ez az ablak a helye — nem a stratégia-paraméterek ablaké.
        # A `classic` sor „R" gombja állította; a 2.0 elrendezésben viszont NINCS
        # ilyen cella, így egy nyitott pozíció NÉLKÜLI párra sehogy nem lehetett
        # beállítani (a Pozíciók-fül menüje csak meglévő pozíciónál nyílik).
        from core import rr_state as _rrs
        from core import risk_reduction as _rrx
        from core import mt5_connector as _mc
        _pl = (self.cfg.get("pairs", {}).get(symbol, {}) or {})
        try:
            _netting = _mc.is_netting()
        except Exception:
            _netting = False
        # cur_lot=None: nincs (még) pozíció → a lot-alapú tiltás nem érvényes, a
        # jövőbeli belépő mérete még nem ismert. A netting-korlát viszont áll.
        _lots_now = [float(p.get("volume", 0.0) or 0.0)
                     for p in getattr(self, "_mt5_cache", {}).get("positions_detail", [])
                     if p.get("symbol") == symbol]
        _blocked_rr = _rrx.preset_blockers(
            max(_lots_now) if _lots_now else None,
            float(_pl.get("min_lot", 0.01) or 0.01),
            float(_pl.get("lot_step", 0.01) or 0.01), _netting)
        tk.Label(popup, text=_t("gui.kockazatcsokkentes_a_par_minden"),
                 bg=BG, fg=FG_GRAY, font=self._small_font).pack(anchor="w", padx=12,
                                                                pady=(8, 2))
        _rr_choices = [_rrs.NAME[p] + (f"  — {_blocked_rr[p]}" if p in _blocked_rr else "")
                       for p in _rrs.CYCLE]
        _rr_by_label = {lbl: p for lbl, p in zip(_rr_choices, _rrs.CYCLE)}
        _rr_cur = _rrs.effective_preset(symbol)
        rr_var = tk.StringVar(value=next(
            (l for l, p in _rr_by_label.items() if p == _rr_cur), _rrs.NAME[_rr_cur]))
        _om3 = tk.OptionMenu(popup, rr_var, *_rr_choices)
        _om3.config(bg=BG_HEADER, fg=FG_WHITE, font=self._small_font, relief="flat",
                    highlightthickness=0, activebackground=BG_HEADER)
        _om3["menu"].config(bg=BG_HEADER, fg=FG_WHITE)
        # A TILTOTT tételek látszanak (az OKKAL), de nem választhatók — ugyanaz a
        # recept, mint a Pozíciók-fül menüjében: a néma hiány rejtélyes volna.
        for _i, _p in enumerate(_rrs.CYCLE):
            if _p in _blocked_rr:
                _om3["menu"].entryconfig(_i, state="disabled")
        _om3.pack(anchor="w", padx=20)

        # ── „Minden instrumentumra" ─────────────────────────────────────────
        # SZÁNDÉKOSAN nem az egész ablakot viszi át, hanem CSAK AZT, AMIT ITT
        # MEGVÁLTOZTATTÁL. Egy mindent-átmásoló pipa ugyanis a nem piszkált
        # sorokat (pl. a kötés-módot) is ráhúzná minden párra — az pénzt érintő,
        # néma mellékhatás lenne. Így a jelentés kiszámítható: „amit itt
        # átállítottam, az menjen mindenhová".
        _init = {
            "strategies": sorted(cur),
            "viz":    {n: bool(_vp.viz_on(self.cfg, symbol, n))    for n in _names},
            "trades": {n: bool(_vp.trades_on(self.cfg, symbol, n)) for n in _names},
            "notify_trade":  {n: bool(_vp.notify_trade_on(self.cfg, symbol, n))
                              for n in _names},
            "notify_signal": {n: bool(_vp.notify_signal_on(self.cfg, symbol, n))
                              for n in _names},
            "mode":   {n: _tm.mode_of(self.cfg, symbol, n)         for n in _names},
            "market":     (_ms.market_name_of(_pc0) or "Nincs"),
            "market_viz": bool(_pc0.get("market_viz", True)),
            "rr_preset":  _rr_cur,
        }
        all_var = tk.BooleanVar(value=False)
        tk.Checkbutton(popup, text=_t("gui.a_modositott_sorokat_minden"),
                       variable=all_var, bg=BG, fg=FG_YELLOW, selectcolor=BG_HEADER,
                       font=self._small_font, activebackground=BG,
                       activeforeground=FG_YELLOW).pack(anchor="w", padx=12, pady=(10, 0))
        tk.Label(popup, text=_t("gui.csak_azok_a_sorok"),
                 bg=BG, fg=FG_GRAY_DIM, font=self._small_font,
                 wraplength=360, justify="left").pack(anchor="w", padx=32, pady=(0, 2))

        lbl = tk.Label(popup, text="", bg=BG, fg=FG_GRAY, font=self._small_font,
                       wraplength=360, justify="left")
        lbl.pack(anchor="w", padx=12, pady=(8, 0))

        def _current():
            """Az ablak MOSTANI állapota — ugyanabban az alakban, mint az `_init`,
            hogy a kettő közvetlenül összevethető legyen."""
            _l2m = {v: k for k, v in _tm.LABELS.items()}
            return {
                "strategies": sorted(n for n in _names
                                     if _vars[("strategies", n)].get()),
                "viz":    {n: bool(_vars[("viz", n)].get()) for n in _names},
                "trades": {n: bool(_vars[("trades", n)].get()) for n in _names},
                "notify_trade":  {n: bool(_vars[("notify_trade", n)].get())
                                  for n in _names},
                "notify_signal": {n: bool(_vars[("notify_signal", n)].get())
                                  for n in _names},
                "mode":   {n: _l2m.get(_mode_vars[n].get(), _tm.MODE_LIVE)
                           for n in _names},
                "market":     ms_var.get(),
                "market_viz": bool(viz_var.get()),
                "rr_preset":  _rr_by_label.get(rr_var.get(), _rr_cur),
            }

        # A sor-metaadat és a „mi terjed" döntés a core.bulk_apply-ban él (tiszta
        # függvények, tkinter nélkül) — így egy sorban tesztelhető, hogy egy
        # tömeges mentés pontosan mihez nyúl hozzá.
        from core import bulk_apply as _ba

        def _apply_to(sym: str, rows: set, chosen: list, cur_vals: dict):
            """A megadott SOROK alkalmazása EGY instrumentumra.

            A `rows` szűkítése miatt egy tömeges mentés nem nyúl a nem piszkált
            beállításokhoz — ezért lehet biztonságosan minden párra ráengedni."""
            pc = self.cfg.setdefault("pairs", {}).setdefault(sym, {})
            # ⚠ A NÉGY PER-STRATÉGIA KAPCSOLÓ EGY TÁBLÁBÓL. Külön `if`-ekkel
            # egy új tengely hozzáadásakor könnyű kihagyni valamelyiket — és a
            # mentés utána NÉMÁN nem írná ki azt az egyet.
            _TENGELYEK = (("viz", _vp.VIZ), ("trades", _vp.TRADES),
                          ("notify_trade", _vp.NOTIFY_TRADE),
                          ("notify_signal", _vp.NOTIFY_SIGNAL))
            if any(k in rows for k, _a in _TENGELYEK):
                for n in _names:
                    for _k, _axis in _TENGELYEK:
                        if _k in rows:
                            _vp.set_on(self.cfg, sym, n, _axis, cur_vals[_k][n])
                _vp.prune(self.cfg, sym, _names)
            if "mode" in rows:
                for n in _names:
                    _tm.set_mode(self.cfg, sym, n, cur_vals["mode"][n])
            if "strategies" in rows:
                if chosen == [default_strategy_name(self.cfg)]:
                    pc.pop("strategies", None)
                else:
                    pc["strategies"] = list(chosen)
            if "market" in rows:
                if cur_vals["market"] in ("Nincs", "", "none"):
                    pc.pop("market_strategy", None)
                else:
                    pc["market_strategy"] = cur_vals["market"]
            if "market_viz" in rows:
                if cur_vals["market_viz"]:
                    pc.pop("market_viz", None)     # True az alap → ne szennyezze
                else:
                    pc["market_viz"] = False
            if "rr_preset" in rows:
                # NEM a config.json-ba megy: a preset a per-pár `data/risk_mode.json`-ban
                # él (`rr_state`). Ugyanazt az utat járjuk, mint a Pozíciók-fül menüje
                # és a `classic` „R" gombja — a régi `risky_mode` szinkronban tartásával
                # együtt, hogy az azt olvasó live/backtest változatlanul működjön.
                from core import risky_mode as _rm
                _rrs.set_preset(sym, cur_vals["rr_preset"])
                try:
                    _rm.set_risky(sym, cur_vals["rr_preset"] == _rrx.PRESET_RISKY)
                except Exception:
                    pass
                _ds_rr = self.dashboard_ref.get(sym)
                if _ds_rr is not None:
                    _ds_rr.rr_preset = cur_vals["rr_preset"]
                    _ds_rr.risky = (cur_vals["rr_preset"] == _rrx.PRESET_RISKY)
            # A chart azonnal kövesse: egyszeri CLEAR + friss pillanatkép, hogy a
            # kikapcsolt stratégia objektumai eltűnjenek (a viz-modell nem töröl
            # magától). Ha EGYIK stratégia rajza sem látszik, a motor meg sem
            # nyitja az írási utat → a törlést itt kell elvégezni, különben a régi
            # objektumok ottragadnának a charton.
            try:
                from trading import live_trader as _lt
                from core import mt5_visual as _viz
                _act = (list(chosen) if "strategies" in rows
                        else enabled_strategy_names(self.cfg, sym))
                if _vp.any_viz_on(self.cfg, sym, _act):
                    _lt._viz_pending_clear[sym] = True
                    _lt._viz_last_write.pop(sym, None)
                else:
                    _viz.clear(sym)
            except Exception:
                pass
            ds = self.dashboard_ref.get(sym)
            if ds is not None:
                if "strategies" in rows:
                    ds.enabled_strategies = list(chosen)
                if "market" in rows:
                    ds.market_strategy = pc.get("market_strategy")

        def _save():
            chosen = [n for n in _names if _vars[("strategies", n)].get()]
            if not chosen:
                lbl.config(text=_t("gui.legalabb_egy_strategia_legyen"), fg=FG_RED)
                return
            now = _current()
            changed = _ba.changed_rows(_init, now)

            targets = [symbol]
            if all_var.get():
                if not changed:
                    lbl.config(text=_t("gui.nincs_modositott_sor_nincs"), fg=FG_YELLOW)
                    return
                others = _ba.targets(self.cfg.get("pairs"), symbol, True)[1:]
                # MEGERŐSÍTÉS: tételesen kiírjuk, MI és HÁNY páron változik. Enélkül
                # egy pipa csendben átírná 10 instrumentum kötés-módját.
                _warn = (_t("gui2.ez_penzt_erint_a")
                         if _ba.affects_money(changed) else "")
                from tkinter import messagebox
                if not messagebox.askyesno(
                        "Minden instrumentumra",
                        _t("gui.bulk.confirm", n=len(others), rows=_ba.summary(changed),
                        symbols=", ".join(others), warn=_warn),
                        parent=popup):
                    return
                targets += others

            for _sym in targets:
                _apply_to(_sym, changed if all_var.get() else set(_ba.ROWS),
                          chosen, now)
            try:
                self._save_main_config()
                _mstxt = (now["market"] if now["market"] != "Nincs"
                          else _t("gui2.nincs_piac_eloszuro"))
                if len(targets) > 1:
                    _rows = ", ".join(sorted(_ba.label_of(k) for k in changed))
                    lbl.config(text=_t("gui.bulk.saved", n=len(targets), rows=_rows), fg=FG_GREEN)
                else:
                    lbl.config(text=_t("gui.bulk.saved_one", names=", ".join(chosen), market=_mstxt), fg=FG_GREEN)
                # Az ablak állapota lesz az ÚJ kiindulás: különben egy második
                # Mentés ugyanazokat a sorokat „módosítottnak" látná, és a pipa
                # újra szétterítené őket.
                _init.update({k: (dict(v) if isinstance(v, dict) else v)
                              for k, v in now.items()})
            except Exception as ex:
                lbl.config(text=_t("save.error", error=ex), fg=FG_RED)

        btns = tk.Frame(popup, bg=BG)
        btns.pack(pady=10)
        tk.Button(btns, text=_t("btn.save"), bg=BTN_PLAY_BG, fg=BTN_PLAY_FG, relief="flat",
                  font=self._small_font, command=_save).pack(side="left", padx=6)
        tk.Button(btns, text=_t("btn.close"), bg=BTN_DIS_BG, fg=BTN_DIS_FG, relief="flat",
                  font=self._small_font, command=popup.destroy).pack(side="left", padx=6)

    # ── Opt státusz részletek (a státusz-cellára kattintva) ──────────────
    # A hibanapló és a blokk-elválasztója — egy igazságforrás az olvasáshoz és a
    # törléshez (a `_run_worker` ugyanezt a fájlt bővíti).
    OPT_LOG_SEP = "=" * 60

    @staticmethod
    def _opt_log_file():
        return ROOT / "data" / "opt_error.log"

    @classmethod
    def _read_opt_log_for(cls, symbol: str, max_blocks: int = 6) -> str:
        """Az adott instrumentumhoz tartozó legutóbbi hiba-blokkok az opt_error.log-ból."""
        log_file = cls._opt_log_file()
        if not log_file.exists():
            return ""
        try:
            with open(log_file, encoding="utf-8") as f:
                raw = f.read()
        except Exception:
            return ""
        sep = cls.OPT_LOG_SEP
        blocks = [b for b in raw.split(sep) if f"[{symbol}]" in b]
        return sep.join(blocks[-max_blocks:]).strip() if blocks else ""

    @classmethod
    def _clear_opt_log_for(cls, symbol: str) -> "tuple[int, str|None]":
        """Az ADOTT instrumentum hiba-blokkjainak törlése az opt_error.log-ból,
        AZONNALI kiírással (a törölt állapot rögtön a lemezre kerül — nem csak a
        megjelenítésből tűnik el).

        SZÁNDÉKOSAN csak ennek a szimbólumnak a blokkjait viszi el: a napló közös,
        és a többi instrumentum hibái még hasznosak lehetnek.

        Vissza: (törölt blokkok száma, hibaüzenet vagy None). Az írás atomikus
        (temp → replace), hogy egy megszakadás ne csonkítsa a naplót."""
        log_file = cls._opt_log_file()
        if not log_file.exists():
            return 0, None
        sep = cls.OPT_LOG_SEP
        try:
            with open(log_file, encoding="utf-8") as f:
                raw = f.read()
        except Exception as ex:
            return 0, str(ex)
        blocks = raw.split(sep)
        keep   = [b for b in blocks if f"[{symbol}]" not in b]
        removed = len(blocks) - len(keep)
        if not removed:
            return 0, None
        payload = sep.join(keep).strip()
        if payload:
            payload += "\n"
        try:
            tmp = log_file.with_suffix(".log.tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(log_file)
        except Exception as ex:
            return 0, str(ex)
        return removed, None

    def _show_opt_log(self, symbol: str):
        """Részletes optimalizálási állapot: státusz + trials CSV + hibalog."""
        popup = tk.Toplevel(self.root)
        popup.title(_t("gui.opt.title", symbol=symbol))
        popup.configure(bg=BG)
        popup.geometry("780x540")
        popup.grab_set()

        state  = self._display_state(symbol)
        status = self.optimizer_status.get(symbol, "—")
        tk.Label(popup, text=_t("gui.opt.state", symbol=symbol, state=state), bg=BG, fg=FG_BLUE,
                 font=self._header_font).pack(anchor="w", padx=10, pady=(10, 2))
        tk.Label(popup, text=_t("gui.opt.status_full", status=status), bg=BG, fg=FG_WHITE,
                 font=self._small_font, anchor="w", justify="left",
                 wraplength=740).pack(anchor="w", padx=10)

        # Trials CSV állapota + megnyitás
        from core.params_store import trials_file
        csv = trials_file(symbol)
        row = tk.Frame(popup, bg=BG)
        row.pack(anchor="w", padx=10, pady=(6, 0))
        if csv.exists():
            try:
                with open(csv, encoding="utf-8-sig") as f:
                    n = max(0, sum(1 for _ in f) - 1)
            except Exception:
                n = "?"
            tk.Label(row, text=f"Trials CSV: {n} sor  —  {csv.name}", bg=BG,
                     fg=FG_GREEN, font=self._small_font).pack(side="left")
            tk.Button(row, text=_t("gui.megnyitas"), bg=BTN_BT_BG, fg=BTN_BT_FG, relief="flat",
                      font=self._small_font,
                      command=lambda: self._open_file(csv)).pack(side="left", padx=8)
        else:
            tk.Label(row, text=_t("gui.trials_csv_nincs_meg"), bg=BG, fg=FG_YELLOW,
                     font=self._small_font).pack(side="left")

        tk.Label(popup, text=_t("gui.legutobbi_hibak_esemenyek_data"),
                 bg=BG, fg=FG_GRAY, font=self._small_font).pack(anchor="w", padx=10, pady=(8, 0))

        # FONTOS a sorrend: az alsó sáv (visszajelzés + gombok) LENTRŐL foglalja a
        # helyét, MÉG a táguló szövegdoboz előtt. Fordítva a `expand=True` szövegdoboz
        # felenné az egész maradékot, és a gombok kiszorulnának a látható területről
        # (magasság 1 px) — a Bezár gombbal együtt.
        lbl_res = tk.Label(popup, text="", bg=BG, font=self._small_font)
        btns = tk.Frame(popup, bg=BG)
        btns.pack(side="bottom", pady=8)

        txt_frame = tk.Frame(popup, bg=BG)
        txt_frame.pack(fill="both", expand=True, padx=10, pady=4)
        sb = tk.Scrollbar(txt_frame)
        sb.pack(side="right", fill="y")
        text = tk.Text(txt_frame, bg=BG_HEADER, fg=FG_WHITE, insertbackground=FG_WHITE,
                       font=self._mono_font, wrap="word", yscrollcommand=sb.set)
        text.pack(side="left", fill="both", expand=True)
        sb.config(command=text.yview)
        _EMPTY = (_t("gui2.nincs_naplozott_hiba_ehhez"))
        text.insert("1.0", self._read_opt_log_for(symbol) or _EMPTY)
        text.config(state="disabled")

        def _clear_log():
            """A megjelenített (ehhez az instrumentumhoz tartozó) napló-bejegyzések
            törlése — a lemezre is AZONNAL kiírva, nem csak a nézetből."""
            n, err = self._clear_opt_log_for(symbol)
            if err:
                lbl_res.config(text=_t("gui.opt.log_unwritable", error=err), fg=FG_RED)
            elif n:
                lbl_res.config(text=_t("gui.opt.log_cleared", n=n),
                               fg=FG_GREEN)
            else:
                lbl_res.config(text=_t("gui.nem_volt_torolheto_bejegyzes"), fg=FG_GRAY)
            lbl_res.pack(side="bottom", pady=(0, 6), before=btns)
            # A nézet kövesse: friss (immár üres) tartalom.
            text.config(state="normal")
            text.delete("1.0", "end")
            text.insert("1.0", self._read_opt_log_for(symbol) or _EMPTY)
            text.config(state="disabled")

        tk.Button(btns, text=_t("gui.log_torlese"), bg=BTN_BT_BG, fg=BTN_BT_FG,
                  relief="flat", font=self._small_font, cursor="hand2",
                  command=_clear_log).pack(side="left", padx=6)
        tk.Button(btns, text=_t("gui.bezar"), bg=BTN_DIS_BG, fg=BTN_DIS_FG, relief="flat",
                  font=self._small_font, command=popup.destroy).pack(side="left", padx=6)

    @staticmethod
    def _open_file(path):
        try:
            import os
            os.startfile(str(path))
        except Exception:
            pass

    # ── Gomb handlerek ────────────────────────────────────────────────────
    def _handle_run(self, symbol: str):
        """A futtató gomb (Play↔Stop morph) kezelője. KIVEZETÉS alatt a gomb
        VISSZAVONJA a leállítást (a pár újra kereskedhet)."""
        st = self._display_state(symbol)
        if st == "STOPPED":
            self._handle_play(symbol)
        elif st == "LIVE":
            self._handle_stop(symbol)
        elif st == "CLOSING":
            self._handle_resume(symbol)

    # ── Per-stratégia Play/Stop (a 2.0 tábla vezérlője) ──────────────────
    def _handle_run_strategy(self, symbol: str, name: str):
        """A 2.0 Play/Stop gombja — CSAK ezt a (pár, stratégia) párost kapcsolja.

        A `classic` gombja szimbólum-szintű, mert ott egy sor = egy instrumentum
        ÖSSZES stratégiája. A 2.0-ban a gomb a stratégia SAJÁT blokkjában ül,
        tehát a szimbólum-szintű kapcsolás itt hazugság volna: a `wpr_sma` Play
        gombja az `ml_ai`-t is elindította.

        A szimbólum-szintű `instrument_state` ettől nem tűnik el — a motor
        ciklusa azon dönt, hogy egy párt egyáltalán feldolgoz-e. A két szint
        viszonya: a szimbólum LIVE, ha BÁRMELY stratégiája él."""
        if self._strategy_live(symbol, name):
            self._stop_strategy(symbol, name)
        else:
            self._start_strategy(symbol, name)

    def _start_strategy(self, symbol: str, name: str):
        """Egy stratégia indítása ezen a páron."""
        from core import run_state as _rs
        from trading import live_trader as _lt
        # A stratégiának ENGEDÉLYEZVE kell lennie ezen a páron, különben a motor
        # (`_active = _enabled & _intent`) sosem futtatná — a sor viszont futónak
        # mutatta volna, a `run_state` pedig `live`-ban ragadt volna a configban.
        # Néma no-op helyett megmondjuk, hol lehet bekapcsolni.
        if not self._strategy_enabled(symbol, name):
            self._set_status(_t("gui.ctrl.not_enabled", symbol=symbol, name=name))
            return
        # ⚠ MENTETT KÉSZLET NÉLKÜL IS INDULHAT — a stratégia SAJÁT alapértékeivel
        # (`live_trader.default_params`). Korábban itt egy tiltás állt („előbb
        # futtasd az OPT-ot"), ami egy ÚJ stratégiát minden páron használhatatlanná
        # tett, amíg le nem futott rá egy több órás optimalizálás — akkor is, ha az
        # alapértékek épp jók. A doksi kérése az ellenkezője: „az alapértelmezett
        # paramétereket vegye alapul, és azzal helyből engedjen kereskedni".
        #
        # ⚠ De NEM NÉMÁN: kiírjuk, hogy hangolatlanul indul, és az Áttekintés lap
        # figyelmeztetése is fennmarad, amíg le nem fut rá egy optimalizálás.
        # Egy hangolt és egy hangolatlan pár ránézésre egyforma volna.
        _untuned = _lt.params_source(symbol, name) == "default"
        if _opt_activity.busy(symbol, name):
            self._set_status(_t("gui.ctrl.opt_running", symbol=symbol, name=name))
            return
        if _untuned:
            self._set_status(_t("gui.ctrl.default_params", symbol=symbol, name=name))
        _rs.set_state(self.cfg, symbol, name, _rs.LIVE)
        _saved = self._save_main_config()
        # A pár szintjén is engedni kell, különben a motor hozzá sem nyúl.
        # KIVEZETÉS alatt ez egyben a leállítás visszavonása.
        if self.instrument_state.get(symbol) != "LIVE":
            self.instrument_state[symbol] = "LIVE"
            if self._on_play:
                self._on_play(symbol)
        # Sikertelen mentésnél NEM írjuk felül a hibaüzenetet: a stratégia MOST
        # elindul (a futásidejű cfg-t a motor ugyanabból a dictből olvassa), de a
        # SZÁNDÉK nem perzisztált — újraindítás után nem folytatódna.
        if _saved:
            self._set_status(_t("gui.ctrl.started", symbol=symbol, name=name))
        else:
            self._set_status(_t("gui.ctrl.started_unsaved", symbol=symbol, name=name))
        self._apply_filter_sort()

    def _stop_strategy(self, symbol: str, name: str):
        """Egy stratégia leállítása ezen a páron.

        Amíg MARAD élő stratégia, a pár LIVE marad, és a motor a leállítottat
        magától elengedi (nyitott pozícióval kivezetésbe teszi — lásd
        `live_trader.run`). Ha ez volt az UTOLSÓ, a szimbólumot is le kell zárni,
        és ott ugyanaz a szabály él, mint a `classic` Stopnál: nyitott
        pozícióval KIVEZETÉS (a motor tovább kezeli), különben STOPPED."""
        from core import run_state as _rs
        _rs.set_state(self.cfg, symbol, name, _rs.STOPPED)
        _saved = self._save_main_config()
        # ⚠ A KÉRDÉS: fut-e MÉG valami EZEN A PÁRON? A választ a MOTOR listájából
        # kell venni (a pár `strategies` listája), nem a soron MEGJELENÍTETT
        # listából (`available_strategy_names`) — a kettő eltérhet.
        #
        # ⚠ ÉLESBEN MEGTÖRTÉNT (2026-08-23): az `available_strategies` blokkban a
        # bollinger `false` volt (nem jelenik meg oszlopként), a párokon viszont
        # ENGEDÉLYEZVE volt és FUTOTT. A megjelenítési listát nézve a Stop arra
        # jutott, hogy „nem maradt élő stratégia", a szimbólumot STOPPED-re tette,
        # a motor pedig a bollingert is LEÁLLÍTOTTA — három páron, egyetlen
        # kattintásból. A szándéka a configban közben végig `live` maradt.
        from strategy import enabled_strategy_names as _ensn
        _others = _ensn(self.cfg, symbol) or []
        if any(self._strategy_live(symbol, n) for n in _others):
            # Mint az indításnál: a hibaüzenetet nem nyomjuk el. A leállítás MOST
            # érvényes, de újraindítás után a stratégia visszaindulna.
            self._set_status(
                _t("gui.ctrl.stopped_one", symbol=symbol, name=name)
                if _saved else
                _t("gui.ctrl.stopped_unsaved", symbol=symbol, name=name))
            self._apply_filter_sort()
            return
        ds = self.dashboard_ref.get(symbol)
        if ds is not None and ds.position_pnl is not None:
            self.instrument_state[symbol] = "CLOSING"
            self._set_status(_t("gui.ctrl.closing", symbol=symbol))
        else:
            self.instrument_state[symbol] = "STOPPED"
            self._set_status(_t("gui.ctrl.stopped", symbol=symbol))
            if self._on_stop:
                self._on_stop(symbol)
        self._apply_filter_sort()

    def _set_status(self, text: str):
        """Állapotsor-üzenet — az alsó sáv még nem biztos, hogy létezik (a tábla
        felépítése közben is hívódhat)."""
        lbl = getattr(self, "lbl_status", None)
        if lbl is not None:
            lbl.config(text=text)

    def _handle_resume(self, symbol: str):
        """A kivezetés visszavonása: a pár újra nyithat belépőt. A motor állapota
        megmaradt (a pozíciót végig kezelte), ezért csak a szándékot állítjuk vissza."""
        if self.instrument_state.get(symbol) != "CLOSING":
            return
        self.instrument_state[symbol] = "LIVE"
        self._persist_run_state(symbol, "live")
        self._refresh_row(symbol)

    def _persist_run_state(self, symbol: str, state: str):
        """A kereskedés-SZÁNDÉK perzisztálása a config.json-ba (restart-biztos):
        a szimbólum engedélyezett stratégiáira beállítja a `run_state`-et (+ az
        `enabled`-et szinkronban), majd ment. Így újraindításkor a `run()` a
        korábban futó párokat magától LIVE-ba teszi."""
        try:
            from core import run_state as _rs
            from strategy import enabled_strategy_names
            strat_names = enabled_strategy_names(self.cfg, symbol) or [self.strategy.name]
            for sn in strat_names:
                _rs.set_state(self.cfg, symbol, sn, state)
            self._save_main_config()
        except Exception:
            pass

    def _handle_play(self, symbol: str):
        ds = self.dashboard_ref.get(symbol)
        if ds is None or not ds.trained:
            return
        if self.instrument_state.get(symbol) != "STOPPED":
            return
        self.instrument_state[symbol] = "LIVE"
        self._persist_run_state(symbol, "live")      # restart után folytassa a kereskedést
        if self._on_play:
            self._on_play(symbol)

    def _handle_stop(self, symbol: str):
        """Leállítás. NYITOTT POZÍCIÓVAL is megengedett: ilyenkor KIVEZETÉS
        (`CLOSING`) állapotba kerül — a motor tovább kezeli a meglévő pozíciót
        (breakeven, trailing, kiszállási jel), de ÚJ belépőt nem nyit. Amint a
        pozíció lezárult, magától valódi STOPPED lesz.

        A mentett szándék MINDKÉT esetben „stopped": újraindítás után sem kezd
        magától kereskedni (nyitott pozíciónál a motor kivezetésbe áll vissza)."""
        ds = self.dashboard_ref.get(symbol)
        if ds is None:
            return
        if self.instrument_state.get(symbol) != "LIVE":
            return
        self._persist_run_state(symbol, "stopped")   # restart után NE induljon magától
        if ds.position_pnl is not None:
            self.instrument_state[symbol] = "CLOSING"
            self._refresh_row(symbol)
            return
        self.instrument_state[symbol] = "STOPPED"
        if self._on_stop:
            self._on_stop(symbol)

    def _opt_strategies_for(self, symbol: str) -> list:
        """Az instrumentumon OPTIMALIZÁLHATÓ stratégiák (az engedélyezettek; ha nincs
        explicit lista, az elsődleges/aktív)."""
        from strategy import enabled_strategy_names
        return enabled_strategy_names(self.cfg, symbol) or [self.strategy.name]

    def _handle_opt(self, symbol: str):
        """OPT↔STOP morph. STOPPED → EGY stratégiánál azonnal indít; TÖBB engedélyezett
        stratégiánál VÁLASZTÓ-MENÜ nyílik (melyiket — vagy mindet), hogy egyértelmű
        legyen, mi fog futni (az ml_ai-nál az Opt = tanítás!). QUEUED → a szimbólum
        sorban álló tételeinek törlése."""
        st = self._display_state(symbol)
        # LIVE páron IS indítható optimalizálás — de csak a NEM kereskedő
        # stratégiákra. Ha van ilyen, a menü nyílik (a kereskedő tételt tiltottként,
        # indoklással mutatja); ha nincs, nem csinálunk semmit.
        if st in ("LIVE", "CLOSING"):
            names = self._opt_strategies_for(symbol)
            if st == "LIVE" and any(not self._opt_ctrl._strategy_live(symbol, s)
                                    for s in names):
                row = self.rows.get(symbol)
                btn = getattr(row, "btn_opt", None)
                x = btn.winfo_rootx() if btn else self.root.winfo_pointerx()
                y = (btn.winfo_rooty() + btn.winfo_height()) if btn \
                    else self.root.winfo_pointery()
                self._show_opt_menu(symbol, names, x, y)
            return
        if st == "STOPPED":
            names = self._opt_strategies_for(symbol)
            if len(names) > 1:
                # A menü az OPT gomb alá nyílik (gomb-kattintásnál nincs event-koordináta)
                row = self.rows.get(symbol)
                btn = getattr(row, "btn_opt", None)
                x = btn.winfo_rootx() if btn else self.root.winfo_pointerx()
                y = (btn.winfo_rooty() + btn.winfo_height()) if btn \
                    else self.root.winfo_pointery()
                self._show_opt_menu(symbol, names, x, y)
                return
            for sn in names:
                self._opt_ctrl.request_optimize(symbol, sn)
        elif st == "QUEUED":
            self._opt_ctrl.cancel_queued(symbol)
        elif st == "OPTIMIZING":
            # FUTÓ optimalizálás/tanítás leállítása (stop-marker → trial-határon
            # áll le; az eredmény eldobva, a mentett paraméterek érintetlenek).
            self._opt_ctrl.request_stop(symbol)
        else:
            return
        self._refresh_row(symbol)

    def _show_opt_menu(self, symbol: str, names: list, x: int, y: int):
        """Stratégiaválasztó menü az optimalizáláshoz (bal-klikk több stratégiánál
        és jobb-klikk is ezt használja). Az ml_ai-féle tanítható stratégiát a
        felirat is jelzi (Opt = tanítás)."""
        from strategy import get_strategy_by_name
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label=_t("gui.opt.header", symbol=symbol), state="disabled")
        # A KERESKEDŐ stratégiát nem optimalizáljuk (a futás végén felülíródna a
        # paraméterfájlja) — de ez PER STRATÉGIA dől el, tehát a pár többi
        # stratégiája menüből indítható akkor is, ha a pár épp kereskedik.
        # A tiltott tételt LÁTHATÓAN, indoklással mutatjuk: ha csak kihagynánk, a
        # hiányzó sor rejtélyes lenne.
        _closing = self.instrument_state.get(symbol) == "CLOSING"
        free = []
        for sn in names:
            trainable = callable(getattr(get_strategy_by_name(sn), "fit", None))
            label = (_t("gui.opt.start_one", name=sn) if trainable
                     else f"▶ {sn}")
            if _closing or self._opt_ctrl._strategy_live(symbol, sn):
                menu.add_command(
                    label=_t("gui.opt.trading_stop_first", name=sn), state="disabled")
                continue
            free.append(sn)
            menu.add_command(
                label=label,
                command=lambda s=sn: (self._opt_ctrl.request_optimize(symbol, s),
                                      self._refresh_row(symbol)))
        if len(free) > 1:
            menu.add_separator()
            menu.add_command(
                label="▶ Mind",
                command=lambda: ([self._opt_ctrl.request_optimize(symbol, s)
                                  for s in free], self._refresh_row(symbol)))
        try:
            menu.tk_popup(int(x), int(y))
        finally:
            menu.grab_release()

    def _handle_opt_menu(self, symbol: str, event):
        """JOBB-klikk az OPT gombon: stratégiaválasztó menü (ugyanaz, mint a
        bal-klikk több stratégiánál). KIVEZETÉS alatt nem nyitjuk meg (ott minden
        stratégia pozíciót kezel); LIVE páron IGEN — a menü stratégiánként jelzi,
        melyik indítható és melyik kereskedik épp."""
        if self.instrument_state.get(symbol) == "CLOSING":
            return
        self._show_opt_menu(symbol, self._opt_strategies_for(symbol),
                            event.x_root, event.y_root)

    def _refresh_row(self, symbol: str):
        row = self.rows.get(symbol)
        ds  = self.dashboard_ref.get(symbol)
        if row and ds:
            row.update(ds, self._display_state(symbol),
                       self.optimizer_status.get(symbol, ""),
                       connected=getattr(self, "_connected", True))

    def _handle_risky(self, symbol: str):
        """Az „R" gomb: a kockázatcsökkentő PRESET körbe-váltása
        (Ki → Risky → Felező → Pajzs → Fibo → Harmados), per-pár mentve
        (data/risk_mode.json).
        A régi risky_mode-ot szinkronban tartjuk (preset==risky), hogy az azt
        olvasó live/backtest változatlanul működjön."""
        from core import rr_state, risky_mode, risk_reduction as _rr
        preset = rr_state.cycle_preset(symbol)
        risky_mode.set_risky(symbol, preset == _rr.PRESET_RISKY)
        ds = self.dashboard_ref.get(symbol)
        if ds is not None:
            ds.rr_preset = preset
            ds.risky = (preset == _rr.PRESET_RISKY)
            row = self.rows.get(symbol)
            if row is not None:
                no_trade = (self.instrument_state.get(symbol) == "LIVE"
                            and self._is_no_trade_now(symbol))
                row.update(ds, self._display_state(symbol),
                           self.optimizer_status.get(symbol, ""),
                           connected=getattr(self, "_connected", False),
                           no_trade=no_trade)

    def _show_tfalign_settings(self, symbol: str):
        """Az „Együtt" cellára kattintva a TF-EGYÜTTÁLLÁS kapu ablaka nyílik.

        Korábban ez egy külön, kézzel írt dialógus volt — most a közös kapu-vázat
        használja (`dashboard/gate_dialog.py`), mint a Spread és a Piac. Ugyanaz
        állítható benne (figyelés be/ki, idősíkok, SMA-periódus, chart-vonalak),
        a per-stratégia kapuzás viszont már nem csak pipa: a három hatás
        (akadályoz / kockázatcsökkentés / ki) közül lehet választani."""
        from core import gates as _g
        self._open_gate_dialog(symbol, _g.TF_ALIGN)

    def _display_state(self, symbol: str) -> str:
        """A soron MEGJELENÍTETT állapot: a kereskedési szándék, az optimalizálási
        tevékenységgel felülrétegezve.

        A kettő már KÜLÖN él (`instrument_state` = szándék, `core.opt_activity` =
        tevékenység), a jelenlegi EGYSOROS felület viszont egy badge-et tud mutatni.
        Szabály: ha a pár kereskedik, azt mutatjuk — az a fontosabb jelzés, és a
        haladás úgyis ott van az Opt-státusz szövegben. Csak nem-kereskedő párnál
        lép elő az OPTIMIZING/QUEUED. Így a régi munkamenet (Stop → OPT) képe
        VÁLTOZATLAN, az új képesség (kereskedés közbeni optimalizálás) pedig nem
        hazudja azt, hogy a pár áll.

        A per-stratégia sorok bevezetésekor (dashboard-átstrukturálás) ez a
        kompromisszum megszűnik: ott mindkettő a saját sorában látszik."""
        st = self.instrument_state.get(symbol, "STOPPED")
        if st in ("LIVE", "CLOSING"):
            return st
        return _opt_activity.symbol_state(symbol) or st

    def _handle_delete(self, symbol: str):
        """Instrumentum törlése a config-ból és a táblából (megerősítéssel).
        Csak megállított (STOPPED) párra engedélyezett — optimalizálás alatt sem."""
        if self._display_state(symbol) != "STOPPED":
            return
        from tkinter import messagebox
        if not messagebox.askyesno(
                _t("gui.torles_megerositese"),
                _t("gui.ctrl.delete_confirm", symbol=symbol)):
            return
        self.cfg["pairs"].pop(symbol, None)
        self._save_main_config()
        row = self.rows.pop(symbol, None)
        if row is not None:
            row.frame.destroy()
        self.dashboard_ref.pop(symbol, None)
        self.instrument_state.pop(symbol, None)
        self.optimizer_status.pop(symbol, None)
        self._apply_filter_sort()

    # ── Jelzések fül: kézi kötés ──────────────────────────────────────────
    def _signal_price_of(self, symbol: str):
        """(bid, ask) a mostani árból — a megerősítő ablak ebből mutatja, mennyit
        mozdult az ár a jelzés óta. None, ha nincs kapcsolat."""
        try:
            import MetaTrader5 as _mt5
            from core.mt5_connector import MT5_LOCK
            with MT5_LOCK:
                t = _mt5.symbol_info_tick(symbol)
            return (float(t.bid), float(t.ask)) if t else None
        except Exception:
            log.debug("A jelzés-ár lekérdezése elbukott (%s)", symbol,
                      exc_info=True)
            return None

    def _signal_digits_of(self, symbol: str) -> int:
        """Az ár tizedesjegyei. A `pairs.<sym>.point_size`-ból vezetjük le, mert
        az MINDIG megvan (a `digits` csak élő MT5-kapcsolatnál). Bra50 →
        point_size 0.01 → 2 tizedes; EURUSD → 0.00001 → 5."""
        try:
            ps = float((self.cfg["pairs"][symbol] or {})["point_size"])
            if ps > 0:
                import math
                return max(0, min(8, int(round(-math.log10(ps)))))
        except Exception:
            pass
        return 5

    def _signal_lot_step_of(self, symbol: str):
        """(min_lot, lépés, max_lot). A LÉPÉS a `min_lot` — a felhasználó kérése:
        „mindig min_lottal növelje/csökkentse". Így a beállítható értékek mindig
        a bróker által elfogadható rácson vannak."""
        pc = (self.cfg.get("pairs") or {}).get(symbol) or {}
        try:
            mn = float(pc.get("min_lot") or 0.01)
        except (TypeError, ValueError):
            mn = 0.01
        try:
            mx = float(pc.get("max_lot") or (mn * 100.0))
        except (TypeError, ValueError):
            mx = mn * 100.0
        return mn, mn, max(mn, mx)

    def _signal_max_age_hours(self) -> float:
        """Ennél régebbi jelzésre a Kötés gomb PASSZÍV.
        `dashboard.signal_trade_max_age_hours`, alap 4 óra."""
        try:
            v = float((self.cfg.get("dashboard") or {})
                      .get("signal_trade_max_age_hours", 4.0))
            return v if v > 0 else 4.0
        except (TypeError, ValueError):
            return 4.0

    def _signal_open_of(self, symbol: str, strategy: str):
        """Van-e NYITOTT pozíció ezen a páron ezzel a stratégiával? → irány|None.

        A Jelzések fül „Kötés" gombja ebből lesz „Kötve" és passzív.

        ⚠ MIÉRT NEM A GOMBNYOMÁST JEGYEZZÜK MEG. Ugyanez a kötés létrejöhet a
        Telegram „Igen" gombjáról, egy másik gépen futó felületről, vagy kézzel
        az MT5-ben — a gombnyomás egyikről sem tudna, és újraindításkor amúgy is
        elveszne. A bróker viszont mindegyikről tud.

        A `positions_detail` a felület MEGLÉVŐ cache-e (a `_refresh` tölti),
        tehát ez a hívás NEM megy az MT5-höz — a Jelzések fül másodpercenként
        frissül, egy pár-stratégiánkénti MT5-kérdés ott érezhető lenne.

        A stratégia feloldása ugyanaz (`_strategy_by_magic`: örökbefogadás
        ELŐBB, aztán a magic), mint a Pozíciók és a Lezárt fülön — különben a
        két nézet mást mondana ugyanarról a pozícióról."""
        if not symbol or not strategy:
            return None
        for p in (getattr(self, "_mt5_cache", {}) or {}).get("positions_detail", []):
            if str(p.get("symbol") or "") != symbol:
                continue
            if self._strategy_by_magic(p.get("magic"), p.get("ticket")) == strategy:
                return str(p.get("type") or "") or None
        return None

    def _signal_positions_refresh(self) -> None:
        """A nyitott pozíciók cache-ének AZONNALI frissítése egy kézi kötés után.

        ⚠ MIÉRT KELL. A siker-ablakot elhagytuk: a visszajelzés az, hogy a gomb
        „Kötve"-re vált. Csakhogy a `_signal_open_of` a `positions_detail`
        cache-ből olvas, amit egy 5 másodperces háttérszál tölt — a gomb tehát
        addig még „Kötés" maradna egy MÁR MEGNYITOTT pozíció mellett. Pontosan
        ez a duplakattintás ablaka, és most nincs ablak, ami feltartaná a kezet.

        ⚠ A HIBÁJA NEM SZÁMÍT. Ez a hívás a ticket UTÁN fut: a pozíció nyitva
        van. Ha az MT5-kérdés elbukik, a háttérszál pár másodperc múlva úgyis
        pótolja — de kivételt itt dobni nem szabad, mert a hívó azt „sikertelen
        kötésnek" mutatná."""
        try:
            from core.mt5_connector import open_positions_detailed
            if isinstance(getattr(self, "_mt5_cache", None), dict):
                self._mt5_cache["positions_detail"] = open_positions_detailed()
        except Exception:
            log.debug("A pozíció-cache frissítése kézi kötés után elbukott",
                      exc_info=True)

    def _signal_manual_trade(self, row: dict, lot: float | None = None):
        """A Jelzések fül „Kötés" gombja. Visszaad: `(ticket|None, üzenet)`.

        ⚠ A stop és a célár a jelzéskori TÁVOLSÁGBÓL, a MOSTANI árhoz igazítva
        megy ki. Egy régi jelzés ABSZOLÚT stopja ma más kockázatot jelentene: a
        stratégiából a TÁVOLSÁG jön (ATR × szorzó), nem a szint — így a kötés
        1 R-je ugyanaz marad, mint amit a jel tervezett.

        A megbízást a `live_trader.open_position()` küldi — UGYANAZ az út, amit a
        motor használ (csúszás-tűrés, kitöltési mód, naplózás). Nincs második
        kötés-implementáció, ami elcsúszhatna tőle."""
        from trading import live_trader as _lt
        sym = str(row.get("symbol") or "")
        irany = str(row.get("direction") or "")
        if irany not in ("BUY", "SELL") or not sym:
            return None, _t("gui2.hianyos_jelzes_sor_instrumentum")
        try:
            # a lotot a megerősítő ablak adja (ott állítható); ha nincs, a jelzésé
            lot = float(lot) if lot is not None else float(row.get("lot"))
            jelzett = float(row.get("price"))
            sl0, tp0 = float(row.get("sl")), float(row.get("tp"))
        except (TypeError, ValueError):
            return None, _t("manual.bad_row")
        if lot <= 0:
            return None, _t("gui2.a_jelzesben_nincs_ervenyes")

        ar = self._signal_price_of(sym)
        if not ar:
            return None, _t("gui2.nincs_elo_ar_mt5")
        belepo = ar[1] if irany == "BUY" else ar[0]

        sl_tav, tp_tav = abs(jelzett - sl0), abs(tp0 - jelzett)
        if sl_tav <= 0:
            return None, _t("gui2.a_jelzes_stop_tavolsaga")
        if irany == "BUY":
            sl, tp = belepo - sl_tav, belepo + tp_tav
        else:
            sl, tp = belepo + sl_tav, belepo - tp_tav

        strat = str(row.get("strategy") or "")
        try:
            magic = int(row.get("magic"))
        except (TypeError, ValueError):
            magic = 0
        ticket = _lt.open_position(sym, irany, lot, sl, tp, magic,
                                   comment="ErikBot-kezi", strategy_name=strat)
        if ticket:
            # ⚠ A TICKET UTÁN MÁR SEMMI NEM BUKHAT EL. Itt a megbízás KIMENT, a
            # pozíció NYITVA van. Ha bármi (naplózás, formázás) kivételt dob, a
            # hívó `except` ága „Hiba"-ablakot mutat — a felhasználó azt hiszi,
            # nincs kötése, és akár újra megnyomja a gombot. Pontosan ez történt
            # 2026-09-02-án egy hiányzó `log` név miatt: valódi pozíció nyílt,
            # a felület mégis hibát jelentett.
            try:
                log.info("Kézi kötés a Jelzések fülről: %s %s lot=%.2f SL=%.5g "
                         "TP=%.5g (a jelzés ideje: %s)", sym, irany, lot, sl, tp,
                         row.get("time"))
            except Exception:
                pass                   # a NAPLÓ hiánya nem tehet kárt a kötésben
            self._signal_positions_refresh()
            return ticket, ""
        return None, (_t("gui2.a_megbizas_nem_ment"))

    def _closed_in_range(self, date_from, date_to) -> list:
        """LEZÁRT pozíciók egy dátum-intervallumra (a „Lezárt" fül tól–ig nézete).

        A nap határát a BRÓKER naptára adja (`server_day_bounds_for`), nem a gép
        helyi dátuma — különben a felirat („MT5 szerver-idő") megint nem
        teljesülne, és a napváltás környékén más trade-ek jönnének, mint amit a
        „ma" nézet mutat."""
        from core.mt5_connector import (closed_positions_range,
                                        server_day_bounds_for)
        frm, to = server_day_bounds_for(date_from, date_to)
        return closed_positions_range(frm, to)

    def _closed_risk(self, c: dict):
        """Egy lezárt kötés belépéskori kockázata (1 R) — a `Lezárt` fül R-oszlopához.

        A rögzített értéket (`core.position_meta`) használja, tartalékként a nyitó
        order SL-jéből számol. A tartalék a v1.81.0 ELŐTT nyitott kötésekhez kell:
        azoknál még nincs rögzítés, de a nyitó order stopja az MT5-ben megvan."""
        pc = (self.cfg.get("pairs") or {}).get(c.get("symbol")) or {}
        return _pmeta.risk_of_closed(c, pc)

    def _daily_split(self, closed_today):
        """A mai lezárt kötések `{(szimbólum, stratégia): bucket}` bontása — a 2.0
        tábla `Napi P&L` cellájához.

        Miért ITT és nem a motorban: a `live_trader.daily_split_cached()` a
        `process_pair`-ből hívódik, az pedig CSAK LIVE/CLOSING páron fut. Egy
        megállított páron (vagy a bot újraindítása után, mielőtt a kör odaér) a
        bontás sosem született meg, és a cella `—` maradt — miközben a `classic`
        `Napi P&L` oszlopa ugyanebből a `closed_today` cache-ből hozta a számot.
        Ugyanaz a feloldás (`_strategy_by_magic`: örökbefogadás ELŐBB, aztán a
        magic) és ugyanaz az R-forrás, tehát a két nézet nem mondhat mást.

        A számítás a lista VÁLTOZÁSAKOR fut (a `_refresh` másodpercenként hív);
        hiba esetén `None` → a hívó nem írja felül a meglévő bontást."""
        try:
            sig = (len(closed_today),
                   sum(float(c.get("pnl") or 0.0) for c in closed_today))
        except (TypeError, ValueError):
            return None
        cached = getattr(self, "_daily_split_cache", None)
        if cached is not None and cached[0] == sig:
            return cached[1]
        def _resolve(magic, pid):
            # A `_strategy_by_magic` a TÁBLÁZATNAK „—"-t ad a hozzá nem rendelt
            # kötésre; a bontásban viszont `None` a megállapodás (lásd
            # `core/pnl_split.py`), hogy az adat ne keveredjen a formázással.
            nm = self._strategy_by_magic(magic, pid)
            return None if nm == "—" else nm

        try:
            split = _pnl_split.split_by_strategy(
                closed_today, resolve=_resolve, risk_of=_pmeta.risk_of)
        except Exception:
            return None
        self._daily_split_cache = (sig, split)
        return split

    def _strategy_by_magic(self, magic, ticket=None) -> str:
        """magic (+ ticket) → stratégianév a Pozíciók / Lezárt fülre.

        ELSŐ a ticket-alapú hozzárendelés (örökbefogadott KÉZI pozíció): a magic
        utólag nem írható át az MT5-ben, ezért a kézzel nyitott pozíció stratégiáját
        csak a saját nyilvántartásunk (core.adopted) tudja. Utána a magic → az
        elérhető stratégiák magicjeinek leképezése."""
        nm = _adopted.strategy_of(ticket)
        if nm:
            return nm
        try:
            if magic is not None:
                from strategy import available_strategy_names, get_strategy_by_name
                m = int(magic)
                for name in available_strategy_names(self.cfg):
                    if get_strategy_by_name(name).magic(self.cfg) == m:
                        return name
        except Exception:
            pass
        return "—"

    # ── Kézi pozíció → stratégiához rendelés (örökbefogadás) ─────────────
    def _pos_strategy_menu(self, ticket, symbol, widget):
        """A Pozíciók fül Stratégia-cellájára kattintva: melyik stratégia kezelje
        ezt a (kézzel nyitott) pozíciót?

        Az MT5-ben a magic és a comment az order elküldésekor dől el és utólag NEM
        módosítható — ezért a hozzárendelést a `core.adopted` tartja nyilván
        (ticket → stratégia), és a motor onnantól sajátjaként kezeli a pozíciót
        (BE, trailing, kockázatcsökkentés, kiszállási jel, cost-cut, építés)."""
        from strategy import enabled_strategy_names

        cur_adopted = _adopted.strategy_of(ticket) if _adopted.is_open_adopted(ticket) else None
        native = self._strategy_by_magic(
            next((p.get("magic") for p in
                  getattr(self, "_mt5_cache", {}).get("positions_detail", [])
                  if p.get("ticket") == ticket), None))
        menu = tk.Menu(self.root, tearoff=0, bg=BG_HEADER, fg=FG_WHITE,
                       activebackground=BTN_OPT_BG, activeforeground=FG_ON_ACCENT)
        if native != "—" and not cur_adopted:
            # A bot SAJÁT (magicjével nyitott) pozíciója — nincs mit hozzárendelni.
            menu.add_command(label=_t("gui.adopt.native", native=native),
                             state="disabled")
        else:
            menu.add_command(label=_t("gui.kezelje_ez_a_strategia"), state="disabled")
            for name in enabled_strategy_names(self.cfg, symbol):
                menu.add_command(
                    label=("✓ " if name == cur_adopted else "    ") + name,
                    command=lambda n=name: self._adopt_position(ticket, symbol, n))
            if cur_adopted:
                menu.add_separator()
                menu.add_command(label=_t("gui.hozzarendeles_visszavonasa_kezi_marad"),
                                 command=lambda: self._release_position(ticket))
        try:
            menu.tk_popup(widget.winfo_rootx(),
                          widget.winfo_rooty() + widget.winfo_height())
        finally:
            menu.grab_release()

    def _adopt_position(self, ticket, symbol, strategy_name):
        """Örökbefogadás: a kézi pozíciót a motor ettől kezdve sajátjaként kezeli."""
        from tkinter import messagebox
        from core.params_store import params_file
        # ⚠ A MENTETT PARAMÉTER HIÁNYA MÁR NEM AKADÁLY. A v2.47.0 óta a motor a
        # stratégia SAJÁT alapértékeivel is elindul (`live_trader.default_params`),
        # tehát a régi tiltás („nincs optimalizálva, így a motor nem tudja kezelni
        # a pozíciót") egyszerűen NEM IGAZ többé — csak megakadályozott egy
        # műveletet, ami működne.
        #
        # AMI VISZONT TÉNYLEG AKADÁLY: ha a stratégia nincs ENGEDÉLYEZVE ezen a
        # páron, a motor sosem futtatja (`_active = _enabled & _intent`) — akkor a
        # pozíció valóban kezeletlen maradna.
        if not self._strategy_enabled(symbol, strategy_name):
            messagebox.showwarning(
                _t("gui.nincs_engedelyezve"),
                _t("gui.adopt.not_enabled", strategy=strategy_name, symbol=symbol)
                + chr(10) + chr(10) +
                _t("gui2.kapcsold_be_az_instrumentum"))
            return
        _untuned = not params_file(symbol, strategy_name).exists()
        pos = next((p for p in getattr(self, "_mt5_cache", {}).get("positions_detail", [])
                    if p.get("ticket") == ticket), None)
        warn = ""
        if _untuned:
            # ⚠ NEM tiltás, hanem TÁJÉKOZTATÁS — de kimondva. Egy hangolatlan
            # stratégia KEZELI a pozíciót, csak nem erre az instrumentumra
            # hangolt számokkal; ezt tudni kell, mielőtt rábízod.
            warn += (chr(10) + chr(10) + _t("gui2.megjegyzes_ez_a_strategia"))
        if pos is not None and not pos.get("sl"):
            warn = (_t("gui2.figyelem_ennek_a_pozicionak"))
        if not messagebox.askyesno(
                _t("gui.pozicio_hozzarendelese"),
                _t("gui.adopt.confirm", ticket=ticket, symbol=symbol,
                   strategy=strategy_name, warn=warn)):
            return
        _adopted.adopt(ticket, strategy_name, symbol)
        # A BELÉPÉSKORI kockázat (1 R) rögzítése a kézi pozícióra is — a motor
        # innentől húzza a stopot, tehát a mostani SL-táv hamarosan elveszne.
        # SL NÉLKÜLI pozíciónál a kockázat nem értelmezhető → nem írunk bejegyzést,
        # és az R „—" marad (a fenti figyelmeztetés épp erről szól).
        if pos is not None:
            _pc = (self.cfg.get("pairs") or {}).get(symbol) or {}
            _pmeta.record(
                ticket, symbol, strategy_name,
                _pmeta.risk_from_prices(
                    pos.get("volume", 0.0), pos.get("price_open", 0.0),
                    pos.get("sl", 0.0), _pc.get("point_size", 0.0),
                    _pc.get("pv1_point", 0.0)),
                lot=pos.get("volume", 0.0), entry_price=pos.get("price_open", 0.0))
        # Ha a pár áll, a live loop KIVEZETÉS-be teszi (kezeli a pozíciót, de új
        # belépőt nem nyit) — a szándékot nem írjuk felül.
        self._pos_tab.refresh()

    def _release_position(self, ticket):
        """A hozzárendelés visszavonása — a motor elengedi a pozíciót."""
        from tkinter import messagebox
        if not messagebox.askyesno(
                _t("gui.hozzarendeles_visszavonasa"),
                _t("gui.adopt.release", ticket=ticket)):
            return
        _adopted.release(ticket)
        self._pos_tab.refresh()

    # ── Kiszállás (kockázatcsökkentő preset) a soron ────────────────────
    def _pos_exit_menu(self, symbol, widget):
        """A Kiszállás-cellára kattintva: a per-INSTRUMENTUM kockázatcsökkentő
        preset (+ runner + cost-cut) gyorsan állítható a soron.

        FONTOS: a preset PER INSTRUMENTUM él (nem per pozíció) — a(z) {symbol}
        MINDEN mostani ÉS jövőbeli pozíciójára hat. A menü fejléce ezt kiírja. A
        finomabb beállítás (Óvatos méret, Exit-indikátor, kalibráció) a Stratégia
        Paraméterek ablakban van — ide egy gyors mutató is kerül."""
        from core import rr_state as _rrs
        from core import risk_reduction as _rrx

        cur_preset = _rrs.effective_preset(symbol)
        cur_runner = _rrs.get_runner(symbol)

        # Felezhetőség: ha van NYITOTT pozíció a páron, a TÉNYLEGES lotja alapján. A
        # részleges zárást igénylő presetek (Felező/Pajzs/Pajzs↔Fibo) csak akkor
        # választhatók, ha a lot ≥ 2× min_lot (különben nem lehet megfelezni — pl. a
        # min-loton nyíló indexeknél). Nyitott pozíció híján nem tiltunk (nem tudjuk a
        # jövőbeli méretet), a preset úgyis risky/BE-re degradál, ha nem osztható.
        pair_cfg = (self.cfg.get("pairs", {}) or {}).get(symbol, {}) or {}
        min_lot  = float(pair_cfg.get("min_lot", 0.01) or 0.01)
        lot_step = float(pair_cfg.get("lot_step", 0.01) or 0.01)
        _lots = [float(p.get("volume", 0.0) or 0.0)
                 for p in getattr(self, "_mt5_cache", {}).get("positions_detail", [])
                 if p.get("symbol") == symbol]
        cur_lot  = max(_lots) if _lots else None
        # MELYIK preset nem választható és MIÉRT — a KÖZÖS szabályból (ugyanezt
        # hívja az instrumentum-ablak preset-választója is, lásd
        # `risk_reduction.preset_blockers`).
        from core import mt5_connector as _mc
        _netting = _mc.is_netting()
        _blocked = _rrx.preset_blockers(cur_lot, min_lot, lot_step, _netting)
        halvable = not _blocked

        menu = tk.Menu(self.root, tearoff=0, bg=BG_HEADER, fg=FG_WHITE,
                       activebackground=BTN_OPT_BG, activeforeground=FG_ON_ACCENT)
        menu.add_command(label=_t("gui.close.title", symbol=symbol),
                         state="disabled")
        if _netting:
            menu.add_command(
                label=_t("gui.close.margin_mode", mode=_mc.margin_mode_name()),
                state="disabled")
        elif not halvable:
            menu.add_command(
                label=_t("gui.close.lot_small", lot=_fmtnum(f"{cur_lot:.2f}"),
                    min=_fmtnum(f"{min_lot:.2f}")),
                state="disabled")
        for preset in _rrs.CYCLE:
            if preset in _blocked:
                # Netting számla / nem felezhető lot → a részleges zárást igénylő
                # preset nem választható. Az OKOT is kiírjuk.
                menu.add_command(label=f"    {_rrs.NAME[preset]}  — {_blocked[preset]}",
                                 state="disabled")
                continue
            menu.add_command(
                label=("● " if preset == cur_preset else "    ") + _rrs.NAME[preset],
                command=lambda p=preset: self._set_exit_preset(symbol, p))

        # Runner-almenü — csak Felező/Pajzs presetnél van értelme (a részleges
        # zárás UTÁNI maradék stopja). Az „exit" (Kiszállási jel) indikátorát a
        # Stratégia Paraméterek ablak állítja.
        if cur_preset in (_rrx.PRESET_HALVING, _rrx.PRESET_SHIELD, _rrx.PRESET_SHIELD_FIBO):
            menu.add_separator()
            rsub = tk.Menu(menu, tearoff=0, bg=BG_HEADER, fg=FG_WHITE,
                           activebackground=BTN_OPT_BG, activeforeground=FG_ON_ACCENT)
            for r in _rrs.RUNNERS:
                rsub.add_command(
                    label=("● " if r == cur_runner else "    ") + _rrs.RUNNER_NAME[r],
                    command=lambda rr=r: self._set_exit_runner(symbol, rr))
            menu.add_cascade(label=_t("gui.runner_a_maradek_stopja"), menu=rsub)

        menu.add_separator()
        _cc = _rrs.get_cost_cut(symbol)
        menu.add_command(
            label=("✓ " if _cc else "    ") + _t("gui.close.costcut", bars=_rrs.get_cost_cut_bars(symbol)),
            command=lambda: self._toggle_exit_cost_cut(symbol))
        menu.add_separator()
        menu.add_command(label=_t("gui.reszletes_strategia_parameterek"),
                         command=lambda: self._show_instrument_params(symbol))
        try:
            menu.tk_popup(widget.winfo_rootx(),
                          widget.winfo_rooty() + widget.winfo_height())
        finally:
            menu.grab_release()

    def _set_exit_preset(self, symbol, preset):
        from core import rr_state as _rrs
        from core import risky_mode, risk_reduction as _rrx
        _rrs.set_preset(symbol, preset)
        # A régi risky_mode-ot szinkronban tartjuk (mint a Stratégia-ablak / R gomb).
        try:
            risky_mode.set_risky(symbol, preset == _rrx.PRESET_RISKY)
        except Exception:
            pass
        self._pos_tab.refresh()

    def _set_exit_runner(self, symbol, runner):
        from core import rr_state as _rrs
        _rrs.set_runner(symbol, runner)
        self._pos_tab.refresh()

    def _toggle_exit_cost_cut(self, symbol):
        from core import rr_state as _rrs
        _rrs.set_cost_cut(symbol, not _rrs.get_cost_cut(symbol))
        self._pos_tab.refresh()

    # ── Pozíciókezelő handlerek (Pozíciók fül) ──────────────────────────
    def _pos_panic(self, ticket: int):
        from tkinter import messagebox
        if not messagebox.askyesno(_t("gui.pozicio_zarasa"),
                                   _t("gui.close.one", ticket=ticket)):
            return
        def _w():
            from core import mt5_connector
            mt5_connector.close_position(ticket)
        threading.Thread(target=_w, daemon=True, name="PanicClose").start()

    def _pos_close_all(self):
        from tkinter import messagebox
        positions = getattr(self, "_mt5_cache", {}).get("positions_detail", [])
        if not positions:
            return
        if not messagebox.askyesno(
                _t("gui.osszes_pozicio_zarasa"),
                _t("gui.close.all", n=len(positions))):
            return
        tickets = [p["ticket"] for p in positions]
        def _w():
            from core import mt5_connector
            for t in tickets:
                mt5_connector.close_position(t)
        threading.Thread(target=_w, daemon=True, name="CloseAll").start()

    def _pos_be(self, ticket: int):
        pos = next((p for p in getattr(self, "_mt5_cache", {}).get("positions_detail", [])
                    if p["ticket"] == ticket), None)
        if not pos:
            return
        orig_sl = pos["sl"]
        def _w():
            import logging as _logging
            from core import mt5_connector
            from trading.live_trader import position_state
            _log = _logging.getLogger(__name__)
            # Költség-tudatos BE (spread + jutalék + swap fedezve). Ha az ár még
            # nincs elég messze a nettó ≥ 0-hoz, a hívás False-t ad → NEM BE-zünk.
            if mt5_connector.move_to_breakeven(ticket):
                st = position_state.setdefault(
                    ticket, {"original_sl": orig_sl, "trailing_enabled": True,
                             "be_done": False, "trail_points": None, "trail_moved": False})
                st["be_done"] = True
                _log.info("✦ #%d — kézi költség-tudatos breakeven beállítva", ticket)
            else:
                # A gomb rendes esetben tiltva van ilyenkor; ha mégis idejut (a
                # háttér-frissítés és a kattintás közti ár-mozgás miatt), csak logol.
                _log.info("#%d — BE még nem lehetséges (az ár nem fedezi a "
                          "spread+jutalék+swap költséget) → SL változatlan", ticket)
        threading.Thread(target=_w, daemon=True, name="ManualBE").start()

    def _pos_build(self, ticket: int):
        """A „＋" gomb: kézi ráépítés ENNEK a pozíciónak a CSOMAGJÁRA (a motor
        manual_build-jét hívja háttérszálon — az nyit egy piramidális adalékot +
        közös átlagár-stopot).

        A csomagot a pozíció STRATÉGIÁJA azonosítja (örökbefogadás vagy magic), nem
        pusztán a szimbólum: egy instrumentumon több stratégia is futhat, és a
        ráépítés csak a saját lábakra nyúlhat."""
        pos = next((p for p in getattr(self, "_mt5_cache", {}).get("positions_detail", [])
                    if p["ticket"] == ticket), None)
        if not pos:
            return
        symbol = pos["symbol"]
        strat  = self._strategy_of_position(pos)
        def _w():
            import logging as _logging
            from trading.live_trader import manual_build
            if not manual_build(symbol, strat):
                _logging.getLogger(__name__).info(
                    "%s — ráépítés kihagyva (nincs érvényes építés-jel).", symbol)
        threading.Thread(target=_w, daemon=True, name="ManualBuild").start()

    @staticmethod
    def _strategy_of_position(pos: dict) -> "str | None":
        """Egy pozíció-sor stratégiája: a felületről hozzárendelt (örökbefogadott),
        különben a magic alapján. None, ha egyikből sem derül ki."""
        try:
            from trading.live_trader import strategy_of_ticket
            return strategy_of_ticket(pos.get("ticket"), pos.get("magic"))
        except Exception:
            return None

    def _pos_build_mode(self, symbol: str):
        """Az „Ép:" gomb: a SZIMBÓLUM építés-módját körbe-váltja (Ki → Kézi → Auto),
        mint az instrumentum-ablak Építés-választója. A motor a következő ciklusban a
        build_runtime-ot ehhez igazítja (a „＋" akkortól él Kézinél)."""
        try:
            from core import build_state as _bst
            _bst.cycle_mode(symbol)
        except Exception:
            pass

    _DEFAULT_PSTATE = {"original_sl": 0.0, "trailing_enabled": True,
                       "be_done": False, "trail_points": None, "trail_moved": False}

    def _pos_trail(self, ticket: int):
        from trading.live_trader import position_state
        st = position_state.setdefault(ticket, dict(self._DEFAULT_PSTATE))
        st["trailing_enabled"] = not st.get("trailing_enabled", True)

    def _pos_trail_dist(self, ticket: int, points: int):
        """Kézi trail-távolság beállítása egy ticketre PONTBAN (Pozíciók fül)."""
        from trading.live_trader import position_state
        st = position_state.setdefault(ticket, dict(self._DEFAULT_PSTATE))
        st["trail_points"] = points

    def _pos_params(self, symbol: str) -> dict:
        """Egy szimbólum optimalizált paraméterei (a Pozíciók fül kiszállás-
        progressziójához, pl. breakeven_pct). A tickethez rendelt stratégia
        (örökbefogadás) paramétereit preferálja, különben az elsődlegesét. Rövid
        életű, olcsó JSON-olvasás; ha nincs fájl, üres dict."""
        from core.params_store import params_file
        pf = params_file(symbol)
        if pf.exists():
            try:
                with open(pf, encoding="utf-8") as f:
                    return json.load(f).get("params", {}) or {}
            except Exception:
                pass
        return {}

    def _trail_default(self, symbol: str) -> Optional[int]:
        """Egy szimbólum optimalizált trail-távolsága PONTBAN (a Pozíciók fül
        mezőjéhez). A paraméter ATR-SZORZÓKÉNT van tárolva → pont =
        szorzó × ATR / point. Ha az ATR vagy a 'point' még nem ismert (MT5 adat
        nélkül), None-t ad — a mező üresen marad, mint eddig."""
        mult = self._pos_params(symbol).get("trail_distance_atr")
        if mult is None:
            mult = self.cfg.get("position_mgmt", {}).get("trail_distance_atr")
        if mult is None:
            return None
        _ds = self.dashboard_ref.get(symbol)
        atr_price = getattr(_ds, "atr_price", None) if _ds else None
        if not atr_price:
            return None
        pair_cfg = self.cfg["pairs"].get(symbol, {})
        point_size = pair_cfg.get("point_size")
        ds = self.dashboard_ref.get(symbol)
        point = getattr(ds, "point", None) if ds else None
        # On-demand `point`: ha a szimbólum még nem streamelt point-ot (pl. nem aktívan
        # pollozott pár, de VAN rajta nyitott pozíció — pl. SP500), közvetlenül lekérjük
        # az MT5-ből és cache-eljük a ds-be. Enélkül a trail-távolság mező üres marad.
        if not point:
            try:
                import MetaTrader5 as _mt5
                from core.mt5_connector import MT5_LOCK
                with MT5_LOCK:
                    _mt5.symbol_select(symbol, True)
                    _info = _mt5.symbol_info(symbol)
                if _info and _info.point > 0:
                    point = _info.point
                    if ds is not None:
                        ds.point = point
                    # point_size hiánynál (nem konfigurált pár) heurisztikus tartalék a
                    # digits alapján (mint a light-poll), hogy a mező akkor is kiírjon.
                    if not point_size and _info:
                        point_size = point      # a pont maga, nincs szorzó
            except Exception:
                pass
        if not point_size or not point:
            return None
        return int(round(float(mult) * float(atr_price) / point))

    def _handle_connect(self):
        # A connect() blokkoló MT5-login — háttérszálon, hogy a UI ne fagyjon.
        # Az eredményt a bg-poller (5 mp) és a _refresh úgyis felkapja a cache-ből.
        self.lbl_conn.config(text=_t("gui.kapcsolodas"), fg=FG_YELLOW)

        def _work():
            try:
                from core import mt5_connector
                mt5_connector.connect(self.cfg)
            except Exception:
                pass
        threading.Thread(target=_work, daemon=True, name="MT5Connect").start()

    # ── Publikus API ──────────────────────────────────────────────────────
    def set_balance(self, balance: float):
        self._balance = balance

    def set_slots(self, free: int, max_s: int):
        self._free_slots = free
        self._max_slots  = max_s

    def _render_slots_label(self):
        """A slot-címke — EGY igazságforrás (a ▼/▲ állítás és a periodikus MT5
        frissítés is ezt hívja).

        A szabad slotok mellett kiírja a nyitott pozíciók BONTÁSÁT is, mert csak
        a NEM kockázatmentes pozíciók foglalnak slotot (core.risk_manager.
        SlotManager.occupied) — így max 4 slot mellett is lehet szabályosan 8
        nyitott pozíció, ha 4 már biztosított. A bontás nélkül ez bugnak látszik.
        A ráépített lábak eleve kockázatmentesek (az SL az átlagáron), ezért is
        nőhet a darabszám a kockázat növekedése nélkül."""
        free = self._free_slots
        # A szabad keret TÖRT lehet (a slot kockázati keret, nem darabszám) —
        # egész értéknél ne írjunk ki felesleges tizedest.
        _f = f"{free:.0f}" if abs(free - round(free)) < 0.05 else f"{free:.1f}"
        txt  = f"Szabad slotok: {_f}/{self._max_slots}"
        if self._open_total:
            rf = self._open_total - self._open_occupied
            txt += (_t("gui.hdr.open", open=self._open_total,
                       occupied=self._open_occupied)
                    + (_t("gui.hdr.riskfree", n=rf) if rf else ")"))
        # Tényleges terhelés: a lekötött keret a számla %-ában. Ha ez a beállított
        # risk_pct fölé megy, azt LÁTNI kell — a `min_lot` kis számlán fölé viheti,
        # és korábban ez sehol nem látszott.
        _load = self._risk_load_pct()
        _cfg_pct = float(self.cfg.get("trading", {}).get("account_risk_pct", 0.0))
        over = _load > _cfg_pct * 100 + 1e-9
        if _load > 0:
            txt += _t("gui.hdr.load", pct=_fmtnum(f"{_load:.2f}"))
        self.lbl_slots.config(
            text=txt, fg=FG_RED if (free <= 0 or over) else FG_GREEN)

    def _per_slot_risk(self) -> float:
        """EGY slot kockázati kerete a számla devizájában
        (egyenleg × account_risk_pct / max_open_slots)."""
        t = self.cfg.get("trading", {})
        try:
            pct = float(t.get("account_risk_pct", 0.0))
            slots = int(t.get("max_open_slots", 0))
        except (TypeError, ValueError):
            return 0.0
        if slots <= 0 or pct <= 0 or self._balance <= 0:
            return 0.0
        return self._balance * pct / slots

    def _risk_load_pct(self) -> float:
        """A ténylegesen lekötött kockázat a számla százalékában. 0.0, ha nem
        mérhető (nincs nyitott pozíció, vagy a kockázatuk ismeretlen)."""
        occ = getattr(self, "_occupied_risk", None)
        if not occ or self._balance <= 0:
            return 0.0
        return occ / self._balance * 100.0

    def _render_risk_label(self):
        """A kockázat-címke — EGY igazságforrás (a ▼/▲ és a periodikus frissítés
        is ezt hívja). A slot kerete azért látszik, mert a `max_open_slots`-szal
        EGYÜTT adja meg, mekkora egy pozíció szánt kockázata."""
        if not hasattr(self, "lbl_risk"):
            return
        pct = float(self.cfg.get("trading", {}).get("account_risk_pct", 0.0))
        per_slot = self._per_slot_risk()
        txt = _t("gui.hdr.risk", pct=_fmtnum(f"{pct * 100:.1f}"))
        if per_slot > 0:
            txt += f" ({per_slot:.2f}/slot)"
        self.lbl_risk.config(text=txt, fg=FG_WHITE)

    def _change_risk_pct(self, delta: float):
        """A számla-kockázat állítása a felületről (0,1%-os lépés, 0,1%–10%).

        Ez az ÖSSZES slot EGYÜTTES kockázata — nem per-kötés. A live motor
        UGYANEZT a cfg-dictet olvassa, tehát a következő belépőnél már él; a
        MÁR NYITOTT pozíciókra nem hat visszamenőleg."""
        t = self.cfg.setdefault("trading", {})
        cur = float(t.get("account_risk_pct", 0.01))
        new = round(cur + delta, 4)
        if new < 0.001 or new > 0.10:
            return
        t["account_risk_pct"] = new
        self._save_main_config()
        self._render_risk_label()
        self._render_slots_label()

    def _change_slots(self, delta: int):
        """Max slotszám növelése/csökkentése a felületről.
        Csökkenteni csak a jelenleg FOGLALT (nyitott) slotok számáig lehet —
        egy nyitott pozíciót sosem 'zárunk ki' a limit alá szorítással."""
        occupied = max(0, self._max_slots - self._free_slots)
        new_max  = self._max_slots + delta
        if new_max < 1 or new_max < occupied:
            return
        self._max_slots  = new_max
        self._free_slots = max(0, new_max - occupied)
        # A motor SlotManager-ének frissítése (élő módban)
        if self._on_slots_change:
            try:
                self._on_slots_change(new_max)
            except Exception:
                pass
        # Perzisztálás a config.json-ba (csak a váz-szekciók)
        self.cfg["trading"]["max_open_slots"] = new_max
        self._save_main_config()
        self._render_slots_label()
        self._render_risk_label()   # egy slot kerete = risk_pct / max_slots

    def _change_daily_limit(self, delta: int):
        """A napi veszteség-limit állítása a felületről (10$-os lépés, min. 10$).
        Az abszolút $ értéket a config trading.daily_loss_limit_usd kulcsa tárolja;
        első állításkor a jelenlegi effektív (pct-alapú) limitből indulunk. A live
        motor ugyanezt a cfg-dictet olvassa → a következő ciklusban már él."""
        from trading.backtest import daily_limit_usd as _dlim
        cur = _dlim(self.cfg["trading"], self._balance)
        # 10$-ra kerekített kiindulás (a pct-ből származó érték tört lehet)
        new = max(10, int(round(cur / 10.0)) * 10 + delta)
        self.cfg["trading"]["daily_loss_limit_usd"] = float(new)
        self._save_main_config()
        # Azonnali kijelzés-frissítés (a periodikus update is felülírja majd)
        total_daily = sum(ds.daily_pnl for ds in self.dashboard_ref.values())
        hit = total_daily <= -new
        self.lbl_limit.config(
            text=(f"Napi limit: STOP  ({total_daily:+.0f}$ / -{new}$)" if hit
                  else f"Napi limit: {total_daily:+.0f}$ / -{new}$"),
            fg=FG_RED if hit else FG_GREEN)

    # ── Kapcsolat UI ────────────────────────────────────────────────────
    def _update_connection_ui(self, info: dict):
        self._connected = info.get("connected", False)
        if info["connected"]:
            demo_tag = "  [DEMO]" if info.get("is_demo") else _t("gui2.eles2")
            demo_fg  = FG_YELLOW if info.get("is_demo") else FG_RED
            # Számlatípus (NETTING / HEDGE / EXCHANGE) — NETTING-nél a részleges
            # záráson alapuló technikák (Felező/Pajzs) tiltva vannak, ezért kiírjuk.
            mm_tag = f"  [{info.get('margin_mode_name', '—')}]"
            self.lbl_conn.config(text="● Online", fg=FG_GREEN)
            self.lbl_account.config(
                text=f"#{info['login']}  {info['server']}{demo_tag}{mm_tag}", fg=demo_fg)
            self._btn_connect.pack_forget()
            if info["balance"] > 0:
                self._balance = info["balance"]
                cur = info.get("currency", "")
                self.lbl_balance.config(text=f"Egyenleg: {info['balance']:,.2f} {cur}")
        else:
            self.lbl_conn.config(text="● Offline", fg=FG_RED)
            broker = self.cfg.get("broker", {})
            demo_tag = "  [DEMO]" if broker.get("is_demo") else _t("gui2.eles")
            self.lbl_account.config(
                text=f"#{broker.get('login','—')}  {broker.get('server','—')}{demo_tag}",
                fg=FG_GRAY)
            self._btn_connect.pack(side="right", padx=6)

    def _refresh_licence_label(self) -> None:
        """A licenc-fiók ÉS az állapota a fejlécben.

        ⚠ A TÜRELMI IDŐ EDDIG CSAK A NAPLÓBAN LÉTEZETT. Ha a licencszerver nem
        érhető el, a program a mentett ellenőrzésből indul — és egy ablakos
        programban a naplóba senki nem néz. A felhasználó tehát napokig futott
        volna abban a hitben, hogy minden rendben, a hiány pedig pontosan akkor
        derült volna ki, amikor a program 72 óra múlva már nem indul el.

        ⚠ Ha ebben a futásban NEM volt ellenőrzés (backtest, optimalizálás —
        azok licenc nélkül is mennek), a mező csak az e-mailt mutatja. Nem
        állítunk semmit a licencről, amiről nem tudunk."""
        try:
            from core import licence as _lic
            st = _lic.status()
        except Exception as _ex:
            # ⚠ LOKÁLIS import. Ebben a fájlban a `logging` SEHOL nincs
            # modul-szinten importálva (csak függvényeken belül) — egy
            # modul-szintűnek hitt `_logging` itt NameError-t adna, és
            # Tk-visszahívásban az a stderr-re menne, ahol egy ablakos
            # programban SENKI nem látja.
            import logging as _logging
            _logging.getLogger(__name__).debug(
                "a licenc-állapot nem olvasható: %s", _ex)
            st = {}

        _email = str(st.get("email") or "")
        szoveg, szin = _email, FG_GRAY

        if st.get("allapot") == "grace":
            # A szerver nem válaszolt: mentésből futunk, és ez VÉGES.
            ora = st.get("turelmi_ora")
            szoveg = _t("gui.hdr.no_licence_server", email=_email, hours=ora)
            szin = FG_RED if (ora is None or ora <= 12) else FG_YELLOW
        elif st.get("allapot") == "ok":
            # ⚠ A közelgő lejárat is ide tartozik: azt AZELŐTT kell látni, hogy
            # megállítana. 30 nap alatt szólunk, 7 nap alatt pirosan.
            nap = st.get("lejar_nap")
            if nap is not None and nap <= 30:
                szoveg = _t("gui.hdr.licence_expires", email=_email, days=nap)
                szin = FG_RED if nap <= 7 else FG_YELLOW

        # ⚠ Csak VÁLTOZÁSKOR nyúlunk a widgethez: ez másodpercenként fut, és a
        # felesleges `config` hívás fölöslegesen újrarajzoltatná a fejlécet.
        if (szoveg, szin) != getattr(self, "_lic_utolso", None):
            self._lic_utolso = (szoveg, szin)
            # ⚠ NINCS ikon a szöveg előtt. Az „ember" jel (U+1F464) EMOJI-kódpont:
            # a mono betűtípusból hiányzik, ezért a rendszer emoji-fontjából esik
            # vissza, aminek MÁS az alapvonala — láthatóan lejjebb ül a szövegnél.
            # A fejléc többi szimbóluma BMP-ből való és a SZÖVEGFONTBÓL jön
            # (fogaskerék, körös nyíl, állapot-pont) — azok ezért ülnek jól.
            self.lbl_licence.config(text=szoveg, fg=szin)

    # ── Piaci adat háttérszál (egységes) ────────────────────────────────
    def _start_market_data_poll(self):
        if hasattr(self, "_poll_running"):
            return
        self._poll_running = True
        threading.Thread(target=self._market_data_loop, daemon=True,
                         name="MarketData").start()

    def _market_data_loop(self):
        import time as _time
        _time.sleep(5)  # UI stabilizálódjon
        price_sec  = max(1, self._price_refresh_sec)
        live_every = max(1, round(self._fast_refresh_sec / price_sec))
        all_every  = max(1, round(self._all_refresh_sec  / price_sec))
        counter = 0
        while getattr(self, "_poll_running", False):
            all_syms = [s for s in self.dashboard_ref
                        if isinstance(self.cfg["pairs"].get(s), dict)]
            # 1) Olcsó ár-frissítés MINDEN párra, MINDIG — optimalizálás alatt IS!
            #    Ez tartja naprakészen a BID/ASK/Vált.%/Spread-et (a live kereskedéshez
            #    kell). Biztonságos: az optimizer NEM nyúl MT5-höz (parquet/Optuna), a
            #    hívás MT5_LOCK alatt fut, mint a live_trader (ami szintén megy közben).
            #    KORÁBBI HIBA: az egész loop az opt-kapu alá volt zárva → opt közben
            #    eltűnt a BID/ASK minden páron, a live DJ30-on is.
            for sym in all_syms:
                try:
                    self._refresh_price(sym)
                    self._refresh_light_extras(sym)   # napi nyitóár + max spread (opt közben is)
                except Exception:
                    pass
            # 2) Drága indikátor-számítás: CSAK ha nincs optimizer (CPU-kímélés + az
            #    indikátor-út bar-letöltést is végez). Minden pár ritkán, LIVE gyakrabban.
            if not self._opt_ctrl._running:
                if counter % all_every == 0:
                    ind_targets = all_syms
                elif counter % live_every == 0:
                    ind_targets = [s for s, st in self.instrument_state.items()
                                   if st == "LIVE"]
                else:
                    ind_targets = []
                for sym in ind_targets:
                    if self._opt_ctrl._running:
                        break
                    try:
                        self._refresh_pair_data(sym)
                    except Exception:
                        pass
            counter += 1
            _time.sleep(price_sec)

    def _refresh_price(self, symbol: str):
        """Olcsó ár-frissítés: BID/ASK/tizedes/spread + napi változás%.
        Bars/indikátor NÉLKÜL → minden párra futtatható gyakran. A symbol_select
        biztosítja, hogy a (akár letiltott) szimbólum is streameljen MT5-ben."""
        try:
            import MetaTrader5 as _mt5
            from core.mt5_connector import MT5_LOCK
        except Exception:
            return
        ds = self.dashboard_ref.get(symbol)
        if ds is None:
            return
        with MT5_LOCK:
            _mt5.symbol_select(symbol, True)
            tick = _mt5.symbol_info_tick(symbol)
            info = _mt5.symbol_info(symbol)
        if tick and tick.bid:
            ds.prev_bid, ds.prev_ask = ds.bid, ds.ask
            ds.bid, ds.ask = tick.bid, tick.ask
        # ⚠ NYITVA VAN-E A PIAC — ITT, a HÁTTÉRSZÁLON. A tick már a kezünkben
        # van, tehát nem kerül EGYETLEN extra MT5-hívásba sem. A fő szálon
        # kiszámolva 10-30 hívás menne körönként a UI-szálra, ami pont az a
        # fajta terhelés, amit a fagyás-watchdog jelez.
        try:
            from core import market_state as _msx
            _mi = _msx.info_of(symbol) if tick is None else _msx.from_tick(
                getattr(tick, "time", 0))
            _mi["tip"] = _msx.tip_of(_mi)
            ds.session = _mi
        except Exception:
            ds.session = {"state": "unknown", "age_sec": None, "tip": ""}
        if info:
            ds.digits     = info.digits
            ds.spread_pts = info.spread
            ds.point      = info.point
        ref = ds.bid if ds.bid is not None else ds.ask
        if ref is not None and ds.day_open:
            ds.change_pct = (ref - ds.day_open) / ds.day_open * 100.0

    def _light_pair_data(self, symbol: str) -> dict:
        """Az optimalizált JSON TELJES tartalma (params + test_summary) az extra-frissítő-
        höz: a params az ATR/spread-számításhoz, a test_summary a Minőség-grade-hez.
        Throttle-olva hívjuk, ezért a JSON-olvasás elenyésző. Üres dict, ha nincs/hiba."""
        try:
            # FONTOS: lokális import — modul-szinten nincs params_file; enélkül
            # NameError keletkezett, amit a except lenyelt → a Minőség-grade
            # optimalizálás alatt SOSEM jelent meg (v1.30.3 regresszió).
            from core.params_store import params_file
            pf = params_file(symbol, self.strategy.name)
            if pf.exists():
                return json.load(open(pf, encoding="utf-8")) or {}
        except Exception:
            pass
        return {}

    def _refresh_light_extras(self, symbol: str):
        """Olcsó 'extrák', amikhez PÁR GYERTYA kell (nem tick): NAPI NYITÓÁR (Vált.%-hoz)
        + MAX SPREAD (ATR-alapú, a Spread 'kereskedhető?' zöld/piros jelzéséhez). A DRÁGA
        indikátor-úttól FÜGGETLENÜL fut — így optimalizálás alatt sem tűnik el a Vált.%
        és a kereskedhető-spread. Ritkán (throttle), mert lassan változnak."""
        ds = self.dashboard_ref.get(symbol)
        if ds is None:
            return
        import time as _t
        if _t.time() - getattr(ds, "_extras_ts", 0.0) < 15.0:
            return
        ds._extras_ts = _t.time()
        try:
            import MetaTrader5 as _mt5
            import pandas as _pd
            from core.mt5_connector import MT5_LOCK
            from core.indicator_engine import atr as _atr
        except Exception:
            return
        data = self._light_pair_data(symbol)
        prm = data.get("params") or {}
        if not prm:
            try:
                prm = self.strategy.base_params(self.cfg)
            except Exception:
                prm = {}
        atr_period = int(prm.get("atr_period", 14))
        # Minőség (grade) a test_summary-ből — OLCSÓ (nincs gyertya) → opt közben is.
        _ts = data.get("test_summary") or {}
        if _ts:
            try:
                _gt, _gc, _gr = self.strategy.grade(_ts, self.cfg)
                ds.opt_grade = (_gt, _gc)
                ds.opt_grade_reason = _gr
            except Exception:
                pass
        # ~300 M15 gyertya: fedi az ATR-t (max spread) ÉS a regime-osztályozó warmupját
        # (atr_avg_period=100) a Piac oszlophoz. Egyetlen copy_rates hívás → olcsó.
        with MT5_LOCK:
            _mt5.symbol_select(symbol, True)
            d1  = _mt5.copy_rates_from_pos(symbol, _mt5.TIMEFRAME_D1, 0, 1)
            m15 = _mt5.copy_rates_from_pos(symbol, _mt5.TIMEFRAME_M15, 0, 300)
        # Napi nyitóár → Vált.% (a legfrissebb bid-del arányosítva)
        if d1 is not None and len(d1):
            ds.day_open = float(d1[-1]["open"])
            ref = ds.bid if ds.bid is not None else ds.ask
            if ref is not None and ds.day_open:
                ds.change_pct = (ref - ds.day_open) / ds.day_open * 100.0
        point = getattr(ds, "point", None)
        _df15 = _pd.DataFrame(m15) if (m15 is not None and len(m15) > 2) else None
        # Max spread (ATR × ratio, min-padlóval) → a Spread cella zöld/piros jelzése
        if _df15 is not None and point:
            try:
                atr_val = _atr(_df15["high"], _df15["low"], _df15["close"], atr_period).iloc[-2]
                if atr_val == atr_val:   # not NaN
                    atr_pts  = int(atr_val / point)
                    ratio    = float(prm.get("max_spread_atr_ratio", 0.20))
                    pair_pip = float(self.cfg["pairs"].get(symbol, {}).get(
                                     "point_size", point))
                    pip_to_pt = max(1, round(pair_pip / point))
                    min_pts  = max(1, int(float(prm.get("min_spread_points", 2.0)) * pip_to_pt))
                    ds.max_spread_pts = max(min_pts, int(atr_pts * ratio))
            except Exception:
                pass
        # Piac (regime) állapot → a Piac oszlop — opt közben is (a drága út opt-kapuzott)
        if _df15 is not None:
            try:
                from core import market_strategy as _ms
                _msname = _ms.market_name_of(self.cfg.get("pairs", {}).get(symbol, {}) or {})
                ds.market_strategy = _msname
                if _msname:
                    _cat = _ms.latest_category(_msname, _df15)
                    if _cat:
                        ds.market_state_label, ds.market_state_color = _ms.display(_cat)
            except Exception:
                pass
        # TF-együttállás (M1/M5/M15 SMA-irány) → az „Együtt" oszlop. Idősíkonként
        # NATIVE copy_rates (nincs resample-torzítás); sign(close − SMA(n)).
        try:
            from core import tf_align as _tfa
            from core import mt5_connector as _mc
            _tfa_en, _tfa_tfs, _tfa_sma, _ = _tfa.config_for(self.cfg, symbol)
            if _tfa_en:
                _closes = _mc.tf_closes(symbol, _tfa_tfs, _tfa_sma + 5)
                # HIÁNYZÓ idősík: a `tf_closes` a nem elérhetőt CSENDBEN kihagyja,
                # az `alignment` pedig 0-t (semleges pötty) ad rá — vagyis egy
                # tartósan üres idősík úgy néz ki, mint egy semleges piac.
                # Szimbólumonként EGYSZER kiírjuk, hogy ne kelljen találgatni.
                _miss = [t for t in _tfa_tfs if len(_closes.get(t) or []) < _tfa_sma]
                if _miss and symbol not in getattr(self, "_tfa_warned", set()):
                    if not hasattr(self, "_tfa_warned"):
                        self._tfa_warned = set()
                    self._tfa_warned.add(symbol)
                    import logging as _logging
                    _logging.getLogger(__name__).warning(
                        "%s — TF-együttállás: nincs elég gyertya (%s; kell "
                        "%d). Az érintett idősík SEMLEGES pöttyöt kap, és a "
                        "kapu emiatt blokkolhat.", symbol,
                        ", ".join(_tfa.TF_LABEL.get(t, str(t)) for t in _miss),
                        _tfa_sma)
                ds.tf_align_dir, ds.tf_align_signs = _tfa.alignment(
                    _closes, _tfa_tfs, _tfa_sma)
                ds.tf_align_labels = _tfa.labels(_tfa_tfs)
            else:
                ds.tf_align_signs, ds.tf_align_dir = [], None
        except Exception as _e:
            # Korábban néma `pass` állt itt. Az „Együtt" oszlop üresen maradása
            # PONTOSAN így nézne ki, mint egy hiányzó adat — a kettőt meg kell
            # tudni különböztetni. Szimbólumonként egyszer szólunk.
            if symbol not in getattr(self, "_tfa_err", set()):
                if not hasattr(self, "_tfa_err"):
                    self._tfa_err = set()
                self._tfa_err.add(symbol)
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "%s — TF-együttállás számítási hiba: %s", symbol, _e)
        # 'Utolsó opt' PERZISZTENS címke (a done-marker idejéből) — ha nem épp optimalizál.
        # Így restart / opt közben sem tűnik el (nem az in-memory 'Kész ✓'-ra hagyatkozik).
        if not _opt_activity.symbol_busy(symbol):
            _cur = self.optimizer_status.get(symbol, "")
            if not _cur or opt_kind(_cur) == OPT_DONE:
                _lbl = self._opt_done_label(symbol)
                if _lbl:
                    self.optimizer_status[symbol] = _lbl

    def _opt_done_label(self, symbol: str) -> str:
        """'Utolsó opt' címke a perzisztens frissítéshez. Egy stratégia esetén a
        klasszikus 'Utolsó opt: yy/mm/dd'. TÖBB stratégia esetén PER-STRATÉGIA
        bontás ('Opt: wpr_sma 07/16 · ml_ai —'), hogy látsszon MELYIK stratégia
        MIKOR frissült (a '—' a még nem optimalizáltat jelöli)."""
        try:
            from strategy import enabled_strategy_names
            names = enabled_strategy_names(self.cfg, symbol)
        except Exception:
            names = [self.strategy.name]
        if not names:
            return ""
        if len(names) == 1:
            return opt_done_label(symbol, names[0])
        parts = []
        for n in names:
            d = opt_done_date(symbol, n)
            parts.append(f"{n} {d.strftime('%m/%d')}" if d else f"{n} —")
        return OptStatus(_t("opt.multi", parts=" · ".join(parts)), OPT_DONE)

    # MT5 timeframe leképezés perc → konstans (lazán, futásidőben)
    @staticmethod
    def _mt5_timeframe(mt5, minutes: int):
        table = {
            1:   mt5.TIMEFRAME_M1,   5:   mt5.TIMEFRAME_M5,
            15:  mt5.TIMEFRAME_M15,  30:  mt5.TIMEFRAME_M30,
            60:  mt5.TIMEFRAME_H1,   240: mt5.TIMEFRAME_H4,
        }
        return table.get(minutes, mt5.TIMEFRAME_M1)

    def _refresh_pair_data(self, symbol: str):
        """Egy pár piaci adatainak frissítése MT5-ből: ár, spread, változás%,
        és a stratégia megjelenítési cellái."""
        try:
            import MetaTrader5 as _mt5
            from core.mt5_connector import MT5_LOCK
        except Exception:
            return
        import pandas as _pd
        from strategy.base import MarketData
        from core.params_store import params_file

        ds = self.dashboard_ref.get(symbol)
        if ds is None or not isinstance(self.cfg["pairs"].get(symbol), dict):
            return

        # Paraméterek: optimalizált, ha van; egyébként alap.
        params_f = params_file(symbol)
        if params_f.exists():
            with open(params_f, encoding="utf-8") as f:
                data = json.load(f)
            params = data.get("params", {})
            ds.trained = True
            # Minősítés a test_summary (out-of-sample) alapján — a stratégián át
            txt, col, reason = self.strategy.grade(data.get("test_summary", {}), self.cfg)
            ds.opt_grade = (txt, col)
            ds.opt_grade_reason = reason
            # Külsőleg (más app által) optimalizált párt is "vegyük észre":
            # ha nem épp most optimalizál, a perzisztens 'Utolsó opt: <dátum>' címke.
            if not _opt_activity.symbol_busy(symbol):
                self.optimizer_status[symbol] = (self._opt_done_label(symbol)
                                                 or OptStatus(_t("opt.done"), OPT_DONE))
        else:
            params = self.strategy.base_params(self.cfg)
            ds.trained = False
            ds.opt_grade = None
            ds.opt_grade_reason = ""
            if not params.get("sma_period"):
                return

        timeframes = self.strategy.timeframes()

        primary = timeframes[0].label  # a "fő" időkeret (ATR-hez)

        with MT5_LOCK:
            _mt5.symbol_select(symbol, True)   # streameljen akkor is, ha letiltott
            raw_bars = {}
            for tf in timeframes:
                # MÉLY ablak (signal_warmup_bars) — hogy a compute_display jelzés-
                # állapota EGYEZZEN a vizzel és a motorral (a sekély warmup nem látná
                # a régi „jó zóna"-élesítést → a kör tévesen szürke maradna).
                warmup = self.strategy.signal_warmup_bars(params, tf.label)
                raw_bars[tf.label] = _mt5.copy_rates_from_pos(
                    symbol, self._mt5_timeframe(_mt5, tf.minutes), 0, warmup)
            info = _mt5.symbol_info(symbol)
            d1   = _mt5.copy_rates_from_pos(symbol, _mt5.TIMEFRAME_D1, 0, 1)

        # Ha nincs gyertyaadat (pl. demo / offline) → ne írjuk felül a cellákat.
        # (Az ár ettől függetlenül friss marad a _refresh_price révén.)
        if any(raw_bars[tf.label] is None for tf in timeframes):
            return

        bars = {}
        for label, arr in raw_bars.items():
            df = _pd.DataFrame(arr)
            df["time"] = _pd.to_datetime(df["time"], unit="s", utc=True)
            df.set_index("time", inplace=True)
            bars[label] = df

        # No-trade órák → a compute_display jelzés-visszajátszása ugyanúgy RESETEL a
        # szüneteknél, mint a live motor és a viz (a kör a szünet után nulláról).
        from core.params_store import resolve_trade_hours as _rth
        _th = _rth(symbol, self.strategy.name,
                   (self.cfg.get("pairs", {}).get(symbol, {}) or {}).get("trade_hours"))
        _nt = (set(range(24)) - {int(h) for h in _th}) if _th is not None else set()
        md = MarketData(symbol=symbol, params=params, bars=bars, no_trade_hours=_nt)
        # Az instrumentumon ENGEDÉLYEZETT stratégiák (a GUI szürkíti a kikapcsoltakat).
        from strategy import enabled_strategy_names, get_strategy_by_name
        enabled = enabled_strategy_names(self.cfg, symbol)
        ds.enabled_strategies = enabled
        # Piac-előszűrő AKTUÁLIS állapota a „Piac" oszlophoz (ha van kiválasztva).
        from core import market_strategy as _ms
        _pcfg = self.cfg.get("pairs", {}).get(symbol, {}) or {}
        ds.market_strategy = _ms.market_name_of(_pcfg)
        if ds.market_strategy and bars.get("M15") is not None:
            try:
                _cat = _ms.latest_category(ds.market_strategy, bars["M15"])
                if _cat:
                    ds.market_state_label, ds.market_state_color = _ms.display(_cat)
            except Exception:
                pass
        # Ha a MOTOR (LIVE pár) frissen írta a jelzés-cellákat a saját állapotából,
        # NE írjuk felül a rekonstrukcióval — a motor az egyetlen forrás. Ha a motor
        # rég nem frissített (STOPPED / session-en kívül / demo), a GUI rekonstruál
        # STRATÉGIÁNKÉNT, mindegyik a SAJÁT paramétereivel (per-stratégia cellák).
        if time.time() - getattr(ds, "cells_ts", 0.0) >= 30.0:
            for sn in enabled:
                try:
                    st = get_strategy_by_name(sn)
                    if sn == self.strategy.name:
                        sp = params                    # már betöltve fent
                    else:
                        _f = params_file(symbol, sn)
                        if _f.exists():
                            sp = json.load(open(_f, encoding="utf-8")).get("params", {})
                        else:
                            # A stratégia SAJÁT config-nézetéből (a cfg a primary
                            # szekcióival van merge-elve — az nem az övé).
                            from strategy.settings import config_for_strategy
                            sp = st.base_params(config_for_strategy(self.cfg, sn))
                    # Pár-azonosító injektálás (mint a motoroknál): pl. az ml_ai
                    # feature-számítása/modell-betöltése igényli.
                    sp = {**sp, "symbol": symbol,
                          "point_size": _pcfg.get("point_size", 0.0001)}
                    sp.setdefault("sess_start", _pcfg.get("sess_start", 0))
                    sp.setdefault("sess_end",   _pcfg.get("sess_end", 24))
                    smd = MarketData(symbol=symbol, params=sp, bars=bars)
                    cells = st.compute_display(smd)
                    ds.strategy_cells[sn] = {k: (c.text, c.color)
                                             for k, c in cells.items()}
                except Exception as _cex:
                    # ⚠ NEM NÉMA. Ez a hook a STRATÉGIÁÉ; ha hibás, a pár sora
                    # ÖRÖKRE üresen marad — és az pontosan úgy néz ki, mint egy
                    # stratégia, ami épp nem jelez. A motor útja már beszédes
                    # volt (`_warn_once`), ez viszont `except: pass`-t
                    # csinált, tehát ugyanannak a hibának a FELÉT elnyelte.
                    # Így derült ki 2026-08-25-én, hogy két stratégia egy
                    # szinttel mélyebben adta vissza a cellákat.
                    #
                    # Egyszer pár+stratégia párosonként: a kör másodpercenként
                    # fut, egy ismétlődő sor elmosná a naplót.
                    _k = ("compute_display", symbol, sn)
                    if _k not in getattr(self, "_cell_warn", set()):
                        self._cell_warn = getattr(self, "_cell_warn", set())
                        self._cell_warn.add(_k)
                        import logging as _logging
                        _logging.getLogger(__name__).warning(
                            "%s/%s: a stratégia compute_display hookja hibázik "
                            "(%s) — a sor jelzés-cellái üresen maradnak.",
                            symbol, sn, _cex)

        # Lendület („fordulatszám") — a mérés instrumentum-tulajdonság, ezért
        # ITT készül, nem stratégiánként. A záróárakat UGYANAZON a csatornán
        # kérjük, amin a TF-együttallás is (`tf_closes`) — így a két alap
        # (egy idősík 3 SMA-val / három idősík) EGY kódúton fut, és az M5-höz
        # sem kell új adatút.
        try:
            from core import momentum as _mom
            from core import gates as _gts
            from core import mt5_connector as _mc
            _mcfg = _gts.momentum_config(_pcfg, self.cfg)
            _mcloses = _mc.tf_closes(symbol, _mom.needed_timeframes(_mcfg),
                                     _mom.needed_bars(_mcfg))
            ds.momentum = _mom.rpm(_mcloses, _mcfg)
        except Exception:
            ds.momentum = float("nan")

        # A TERVEZETT stop/cél a KÖLTSÉG-kapuhoz. A stratégia adja (`sl_tp_points`),
        # nem a kapu számol sajátot — így a cella pontosan azt mutatja, amivel a
        # motor is dolgozna, ha most jelet kapna.
        #
        # ⚠ A stratégia INDIKÁTOR-oszlopot vár a soron (`wpr_sma` → `atr`,
        # `ml_ai` → `atr14`), a `bars` viszont NYERS MT5-gyertya: nincs benne
        # egyik sem. Az első változat emiatt mindig `None`-t kapott, és a
        # Költség-oszlop SOSEM jelent meg — némán, mert a `sl_tp_points` a
        # hiányzó ATR-re szabályosan `None`-t ad. Ezért itt SZÁMOLJUK az ATR-t
        # (ugyanazzal az `indicator_engine.atr`-rel és `atr_period`-dal, amit a
        # motor is használ), és MINDKÉT néven ráírjuk az utolsó ZÁRT sorra.
        ds.plan_sl_points = ds.plan_tp_points = None
        ds.atr_price = ds.atr_baseline = None
        try:
            from core.indicator_engine import atr as _atr_fn
            _pf = bars.get(primary)
            if _pf is not None and len(_pf) > 2:
                _atr_s = _atr_fn(_pf["high"], _pf["low"], _pf["close"],
                                 params.get("atr_period", 14))
                _a = _atr_s.iloc[-2]
                if _a == _a and _a > 0:                     # not NaN
                    _row = _pf.iloc[-2].copy()
                    _row["atr"] = _row["atr14"] = float(_a)
                    _plan = self.strategy.sl_tp_points(
                        _row, params, _pcfg.get("point_size", 0.0001))
                    if _plan:
                        ds.plan_sl_points, ds.plan_tp_points = _plan
                    # VOLATILITÁS-oszlop: a mostani ATR és a kalibrált MÉRCE.
                    # A `vol_baseline` dönti el, hogy a befagyasztott
                    # `atr_avg_ref` vagy a gördülő ablak a mérce — UGYANAZ a
                    # képlet, mint a backtestben és a vizben (`core/vol_baseline`).
                    from core import vol_baseline as _vb
                    ds.atr_price = float(_a)
                    ds.atr_baseline = _vb.effective(
                        params,
                        _vb.value_at(_atr_s.to_numpy(), len(_pf) - 2,
                                     params, float(_a)))
        except Exception:
            pass

        # Max spread (ATR-alapú) — a fő időkeret ATR-jéből
        if info and info.point > 0:
            try:
                from core.indicator_engine import atr as _atr
                dfp = bars.get(primary)
                if dfp is not None and len(dfp) > 2:
                    atr_ser = _atr(dfp["high"], dfp["low"], dfp["close"],
                                   params.get("atr_period", 14))
                    atr_val = atr_ser.iloc[-2]
                    if atr_val == atr_val:   # not NaN
                        atr_pts  = int(atr_val / info.point)
                        ratio    = params.get("max_spread_atr_ratio", 0.20)
                        pair_pip = float(self.cfg["pairs"].get(symbol, {}).get(
                                         "point_size", info.point))
                        pip_to_pt = max(1, round(pair_pip / info.point))
                        min_pts  = max(1, int(params.get("min_spread_points", 2.0)
                                              * pip_to_pt))
                        ds.max_spread_pts = max(min_pts, int(atr_pts * ratio))
            except Exception:
                pass

        # Napi nyitóár (változás% alaphoz) — a _refresh_price ebből számol
        if d1 is not None and len(d1) > 0:
            ds.day_open = float(d1[-1]["open"])

    # ── Account háttérszál ────────────────────────────────────────────────
    def _start_bg_poller(self):
        if hasattr(self, "_bg_poller_running"):
            return
        self._bg_poller_running = True
        self._mt5_cache = {"connected": False, "info": {}, "daily_pnl": None,
                           "positions": {}, "positions_detail": []}

        def _loop():
            import time as _t
            while getattr(self, "_bg_poller_running", False):
                try:
                    from core.mt5_connector import (
                        connection_info, daily_pnl as _dpnl,
                        open_positions_by_symbol, open_positions_detailed,
                        closed_positions_today, server_offset_sec)
                    info = connection_info(self.cfg)
                    self._mt5_cache["connected"] = info.get("connected", False)
                    self._mt5_cache["info"]      = info
                    if info.get("connected"):
                        self._mt5_cache["daily_pnl"] = _dpnl()
                        self._mt5_cache["positions"] = open_positions_by_symbol()
                        self._mt5_cache["positions_detail"] = open_positions_detailed()
                        self._mt5_cache["closed_today"] = closed_positions_today()
                        # Bróker-idő eltolás (a trade_hours/chart szerver-idejéhez)
                        _off = server_offset_sec(list(self.cfg.get("pairs", {}).keys()))
                        if _off is not None:
                            self._mt5_cache["server_offset_sec"] = _off
                    else:
                        self._mt5_cache["daily_pnl"] = None
                        self._mt5_cache["positions"] = {}
                        self._mt5_cache["positions_detail"] = []
                        self._mt5_cache["closed_today"] = []
                except Exception:
                    pass
                _t.sleep(5)
        threading.Thread(target=_loop, daemon=True, name="MT5BgPoller").start()

    def _is_no_trade_now(self, symbol: str) -> bool:
        """A jelenlegi BRÓKER-óra kimarad-e az aktív stratégia trade_hours-ából
        erre a párra? (A live óra-kapujával azonos logika — szerver/chart idő.)
        A jelölés STRATÉGIA-hatókörű: az ELSŐDLEGES (első engedélyezett) stratégia
        óra-fájlját nézi (`{symbol}_hours.json`), visszaesve a config.json legacy
        `trade_hours`-ra — így ugyanaz, amivel a live óra-kapuja számol."""
        off = getattr(self, "_mt5_cache", {}).get("server_offset_sec")
        if off is None:
            return False   # nincs bróker-idő → ne jelezzünk félre
        pc = self.cfg.get("pairs", {}).get(symbol, {})
        if not isinstance(pc, dict):
            return False
        bh = (datetime.now(timezone.utc) + timedelta(seconds=off)).hour
        from core.params_store import resolve_trade_hours
        from strategy import enabled_strategy_names
        _names = enabled_strategy_names(self.cfg, symbol)
        _sn = _names[0] if _names else None
        th = resolve_trade_hours(symbol, _sn, pc.get("trade_hours"))
        if th is not None:
            return bh not in {int(h) for h in th}
        # Visszafelé kompatibilis: sess_start/sess_end tartomány (mint a live).
        return not (pc.get("sess_start", 0) <= bh < pc.get("sess_end", 24))

    # ── Fő frissítés (1 mp, csak Python — nem blokkol MT5-re) ────────────
    def _refresh(self):
        now = datetime.now(timezone.utc)
        # A felső óra a BRÓKER-időt mutatja (a trade_hours/óra-kapu és a chart is
        # ezen jár), az UTC-t másodlagosként. Így nincs félreértés a no-trade
        # órákkal. Ha nincs kapcsolat/offset, csak UTC látszik.
        _off = getattr(self, "_mt5_cache", {}).get("server_offset_sec")
        if _off is not None:
            bt = now + timedelta(seconds=_off)
            self.lbl_time.config(text=_t("gui.hdr.clock", broker=f"{bt:%H:%M:%S}", utc=f"{now:%H:%M}"))
        else:
            self.lbl_time.config(text=now.strftime("%Y-%m-%d %H:%M:%S UTC"))

        # ⚠ A licenc-mező IS frissül, mert a türelmi idő FOGY: egy induláskor
        # kiírt „még 51 óra" órákkal később hazugság volna. Olcsó — a mező csak
        # akkor nyúl a widgethez, ha a szöveg tényleg megváltozott.
        self._refresh_licence_label()

        # Visszaszámlálók a stratégia időkereteire (közös felső sáv + per-pár állapot)
        try:
            from trading.live_trader import seconds_to_candle_close
            # A gyertyahatár a BRÓKER óráján áll — H1 fölött (H4) az eltolás órákat
            # számít a visszaszámlálóban.
            _soff = getattr(self, "_mt5_cache", {}).get("server_offset_sec") or 0.0
            for tf in self.strategy.timeframes():
                rem = seconds_to_candle_close(tf.minutes, _soff)
                for ds in self.dashboard_ref.values():
                    ds.timeframe_remaining[tf.minutes] = rem
                lbl = getattr(self, "_countdown_lbls", {}).get(tf.minutes)
                if lbl is not None:
                    lbl.config(text=_t("gui.tf.close_in", label=tf.label, min=rem // 60,
                                     sec=f"{rem % 60:02d}"))
        except Exception:
            pass

        if not hasattr(self, "_conn_tick"):
            self._conn_tick = 0
            self._last_heartbeat = time.monotonic()
            risky_mode.load()                 # induló risky állapot
            from core import rr_state as _rrs0
            _rrs0.load()                      # induló per-pár preset állapot
            self._start_bg_poller()
            self._start_market_data_poll()
            self._start_watchdog()
        self._conn_tick += 1

        # Risky állapot periodikus újraolvasása (külső program írhatja)
        if self._conn_tick % 60 == 0:
            risky_mode.load()

        cache     = getattr(self, "_mt5_cache", {})
        connected = cache.get("connected", False)
        mt5_info  = cache.get("info", {})
        mt5_pnl   = cache.get("daily_pnl", None)
        mt5_positions = cache.get("positions", {})

        # Per-instrumentum NAPI P&L a MAI lezárt trade-ekből (MT5 history — HITELES,
        # újraindítás-biztos). Korábban a state.daily_pnl session-local volt: bot-
        # újraindítás után a korábbi zárt trade-eket "elfelejtette", és egy páron a
        # napi P&L csak az UTOLSÓ zárt trade-et mutatta (nem az összeg). Így most a
        # "Lezárt (ma)" füllel és a felső összesítővel is egyezik. Csak kapcsolódva
        # írjuk felül (offline a closed_today [] fallback → nem hiteles).
        if connected:
            closed_today = cache.get("closed_today") or []
            daily_by_symbol: dict = {}
            for c in closed_today:
                s = c.get("symbol")
                if s is not None:
                    daily_by_symbol[s] = daily_by_symbol.get(s, 0.0) + c.get("pnl", 0.0)
            # A 2.0 tábla STRATÉGIÁNKÉNTI napi bontása UGYANEBBŐL a forrásból.
            # Korábban csak a `live_trader.process_pair` töltötte, az viszont
            # kizárólag LIVE/CLOSING párra fut — egy megállított páron (vagy
            # a bot újraindítása után) a cella némán „—" maradt, holott a
            # kereskedés megvolt és a `classic` oszlop hozta is.
            split = self._daily_split(closed_today)
            for _sym, _ds in self.dashboard_ref.items():
                if _ds is not None:
                    _ds.daily_pnl = daily_by_symbol.get(_sym, 0.0)
                    if split is not None:
                        _ds.daily_by_strategy = _pnl_split.for_symbol(split, _sym)

        if mt5_info:
            self._update_connection_ui(mt5_info)

        if self._balance > 0:
            cur = mt5_info.get("currency", "")
            self.lbl_balance.config(text=f"Egyenleg: {self._balance:,.2f} {cur}".rstrip())

        if mt5_pnl is not None:
            daily_total = mt5_pnl
            pnl_src = ""
        else:
            daily_total = sum(ds.daily_pnl for ds in self.dashboard_ref.values())
            pnl_src = " (demo)"
        self.lbl_daily.config(text=f"Napi P&L: {daily_total:+.2f}${pnl_src}",
                              fg=FG_GREEN if daily_total >= 0 else FG_RED)

        # EGY igazságforrás: a címkét mindig a `_render_slots_label` rajzolja
        # (korábban itt egy második, formázásban eltérő út is volt).
        self._free_slots = max(0.0, self._free_slots)
        self._render_slots_label()
        self._render_risk_label()

        total_daily = sum(ds.daily_pnl for ds in self.dashboard_ref.values())
        # A limit értéke EGY igazságforrásból (mint a live kapué): abszolút $
        # (daily_loss_limit_usd, a ▼/▲ állítja), különben pct × egyenleg.
        from trading.backtest import daily_limit_usd as _dlim
        _limit = _dlim(self.cfg["trading"], self._balance)
        limit_hit = (_limit > 0 and total_daily <= -_limit)
        self.lbl_limit.config(
            text=(f"Napi limit: STOP  ({total_daily:+.0f}$ / -{_limit:.0f}$)" if limit_hit
                  else f"Napi limit: {total_daily:+.0f}$ / -{_limit:.0f}$"),
            fg=FG_RED if limit_hit else FG_GREEN)

        if mt5_positions is not None:
            # Csak a NEM kockázatmentes pozíciók foglalnak slotot (a kockázatmentes
            # felszabadítja) — egyezik a motor SlotManager-ének logikájával.
            # SÚLYOZOTT foglaltság: egy pozíció annyi slotot fogyaszt, ahányszorosa
            # a kockázata egy slot keretének (core.risk_manager). A darabszám csak
            # akkor a mérce, ha a kockázat ismeretlen (régi/örökbefogadott pozíció).
            occupied_n = sum(p.get("occupied", p.get("count", 1))
                             for p in mt5_positions.values())
            per_slot = self._per_slot_risk()
            risk_sum = sum(float(p.get("risk_ccy", 0.0) or 0.0)
                           for p in mt5_positions.values())
            if per_slot > 0 and risk_sum > 0:
                occupied = risk_sum / per_slot
                self._occupied_risk = risk_sum
            else:
                occupied = occupied_n
                self._occupied_risk = None
            self._free_slots = max(0.0, self._max_slots - occupied)
            # A bontáshoz az ÖSSZES nyitott darab is kell (a `count` a
            # kockázatmenteseket is tartalmazza) — lásd `_render_slots_label`.
            self._open_total    = sum(p.get("count", 1) for p in mt5_positions.values())
            self._open_occupied = occupied_n
            self._render_slots_label()
            self._render_risk_label()

        live_count = 0
        if hasattr(self, "rows"):
            for symbol, row in self.rows.items():
                ds         = self.dashboard_ref.get(symbol)
                inst_state = self._display_state(symbol)
                opt_status = self.optimizer_status.get(symbol, "")
                if ds is not None and mt5_positions is not None:
                    pos = mt5_positions.get(symbol)
                    ds.position_pnl = pos["pnl"] if pos else None
                    ds.pos_count    = pos.get("count", 1) if pos else 0
                    ds.risk_free    = pos["risk_free"] if pos else False
                if ds is not None:
                    from core import rr_state as _rrs
                    ds.rr_preset = _rrs.effective_preset(symbol)
                    ds.risky = (ds.rr_preset == "risky")
                    no_trade = (inst_state == "LIVE" and self._is_no_trade_now(symbol))
                    row.update(ds, inst_state, opt_status,
                               connected=getattr(self, "_connected", False),
                               no_trade=no_trade)
                if inst_state == "LIVE":
                    live_count += 1

        # ── Dashboard 2.0 tábla frissítése ──────────────────────────────
        # HELYBEN frissül (a LiveTable csak szerkezet-változáskor épít újra),
        # tehát a 3 másodperces ütem nem villog.
        if getattr(self, "_live2", None) is not None:
            try:
                self._live2.refresh(self._live2_visible_rows())
            except Exception:
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "A 2.0 tábla frissítése elbukott.", exc_info=True)
            live_count = sum(1 for s in self.cfg["pairs"]
                             if self._display_state(s) == "LIVE")

        if hasattr(self, "lbl_status"):
            # "Utolsó frissítés" = lokális UI-esemény → HELYI idő (nem UTC/bróker).
            local_now = datetime.now().strftime("%H:%M:%S")
            self.lbl_status.config(
                text=_t("gui.hdr.updated", time=local_now, n=live_count))

        # Pozíciók fül frissítése
        if hasattr(self, "_pos_tab"):
            try:
                self._pos_tab.refresh()
            except Exception:
                pass

        # Lezárt (ma) fül frissítése
        if hasattr(self, "_signals_tab"):
            try:
                self._signals_tab.refresh()
            except Exception:
                log.debug("A Jelzések fül frissítése elbukott", exc_info=True)
        if hasattr(self, "_closed_tab"):
            try:
                self._closed_tab.refresh()
            except Exception:
                pass

        # ⚠ A NAPLÓ NE CSAK LÉTEZZEN — LÁTSZÓDJON. Egy fájl, amibe senki nem néz
        # bele, majdnem annyira néma, mint a semmi. Ha bármi ERROR/CRITICAL
        # keletkezett (felület-visszahívás, elhalt szál, kapcsolat), itt kiderül,
        # hogy VAN mit megnézni — és hogy hol.
        self._refresh_error_badge()
        self._refresh_market_badge()

        # Heartbeat: a teljes tick lefutott → a fő szál él
        self._last_heartbeat = time.monotonic()
        self.root.after(1000, self._refresh)

    def _refresh_error_badge(self):
        """„⚠ N hiba a naplóban" — a `core.applog` számlálójából."""
        _lbl = getattr(self, "lbl_errors", None)
        if _lbl is None:
            return
        try:
            from core import applog as _al
            n, last = _al.error_stats()
        except Exception:
            return
        try:
            if n:
                _lbl.config(text=_t("gui.hdr.errors", n=n),
                            fg=FG_RED, cursor="hand2")
                _lbl.pack(side="bottom")
                self._err_tip = last
            else:
                _lbl.pack_forget()
        except tk.TclError:
            pass

    def _refresh_market_badge(self):
        """„Piac: 9/10 zárva" — a háttérszál által számolt állapotokból.

        ⚠ MIÉRT KELL. Egy zárt piacú pár eddig pontosan úgy nézett ki, mint egy
        nyitott, amelyik épp nem talál belépőt. A soron a HALVÁNY ár mondja meg
        páronként; itt az összkép látszik — hétvégén vagy ünnepnapon egy
        pillantás alatt kiderül, hogy nem a programmal van baj."""
        _lbl = getattr(self, "lbl_market", None)
        if _lbl is None:
            return
        try:
            from core import market_state as _ms
            txt = _ms.summary({s: (getattr(ds, "session", None) or {})
                               for s, ds in (self.dashboard_ref or {}).items()})
        except Exception:
            return
        try:
            if txt:
                _lbl.config(text=txt)
                _lbl.pack(side="bottom")
            else:
                _lbl.pack_forget()
        except tk.TclError:
            pass

    def _open_log(self, _e=None):
        """A futásnapló megnyitása a rendszer alapértelmezett programjával."""
        try:
            from core.applog import LOG_PATH
            import os
            os.startfile(str(LOG_PATH))               # Windows
        except Exception as ex:
            try:
                self.lbl_status.config(text=_t("gui.log.open_error", error=ex))
            except tk.TclError:
                pass

    # ── Fagyás-watchdog ──────────────────────────────────────────────────
    @staticmethod
    def _stall_report() -> str:
        """MINDEN élő szál Python-hívási verme, a fő szállal az élen.

        A puszta „nem frissült N mp-ig" üzenet csak azt mondta, hogy VOLT akadás
        — azt nem, hogy HOL. Márpedig a fő szál gyakran ártatlan: a Tk ciklusát
        egy HÁTTÉRSZÁL is megállítja, ha CPU-kötött pandas/numpy munkát végez,
        mert az tartja a GIL-t (pontosan ez volt a `_refresh_pair_data` →
        `compute_display` út). Ezért nem elég a fő szálat kiírni: a vermek
        EGYÜTT mutatják meg, ki fogja a GIL-t. Legfeljebb 6 keret szálanként,
        hogy a napló olvasható maradjon."""
        import traceback as _tb
        frames = sys._current_frames()
        main_id = threading.main_thread().ident
        alive = {t.ident: (t.name or "?") for t in threading.enumerate()}
        out = []
        for tid in sorted(frames, key=lambda i: (i != main_id, alive.get(i, ""))):
            if tid not in alive:
                continue          # időközben véget ért szál
            head = _t("gui2.fo_szal") if tid == main_id else alive[tid]
            stack = "".join(_tb.format_stack(frames[tid])[-6:]).rstrip()
            body = "\n".join(f"    {ln}" for ln in stack.splitlines())
            out.append(f"    [{head}]\n{body}")
        return "\n".join(out)

    def _start_watchdog(self):
        """Háttérszál: jelzi, ha a fő (UI) szál túl sokáig nem lélegzett.
        A küszöb fölötti késés = blokkoló hívás a fő szálon VAGY GIL-t tartó
        háttérmunka — a naplózott vermek (`_stall_report`) megmondják, melyik."""
        if hasattr(self, "_watchdog_running"):
            return
        self._watchdog_running = True
        _dash = self.cfg.get("dashboard", {})
        # ⚠ 4,0 mp — MÉRÉS alapján, nem érzésre. A 2,0-s küszöb 112 riasztást
        # adott 12 nap alatt, és MINDEGYIK ugyanaz volt: élő kereskedés mellett
        # futó backtest/optimalizálás, három pandas-nehéz szál, a fő szál pedig
        # 2,0–2,5 mp-ig nem kapta vissza a GIL-t. A leghosszabb valaha 3,0 mp.
        # Ez tehát nem „blokkoló hívás", hanem processzor-telítettség — a
        # 4,0-s küszöb fölött már tényleg olyasmi áll, amit meg kell nézni.
        threshold = _dash.get("watchdog_threshold_sec", 4.0)
        # A vermek kiírása hasznos, de bőbeszédű — kapcsolható, és epizódonként
        # EGYSZER megy ki (a `warned` kapu alatt), nem félmásodpercenként.
        want_stacks = bool(_dash.get("watchdog_stacks", True))

        def _loop():
            import logging as _logging
            log = _logging.getLogger("ui.watchdog")
            warned = False
            while getattr(self, "_watchdog_running", False):
                lag = time.monotonic() - getattr(self, "_last_heartbeat", time.monotonic())
                if lag > threshold:
                    if not warned:
                        msg = _t("gui.hdr.mainthread_lag", sec=_fmtnum(f"{lag:.1f}"))
                        report = ""
                        if want_stacks:
                            try:
                                report = self._stall_report()
                            except Exception as ex:
                                report = _t("gui.hdr.stacks_failed", error=ex)
                        log.warning(msg + ("\n" + report if report else ""))
                        try:
                            with open(ROOT / "data" / "ui_watchdog.log", "a",
                                      encoding="utf-8") as f:
                                f.write(f"{datetime.now()}  {msg}\n")
                                if report:
                                    f.write(report + "\n")
                        except Exception:
                            pass
                        warned = True
                else:
                    warned = False
                time.sleep(0.5)
        threading.Thread(target=_loop, daemon=True, name="UIWatchdog").start()

    def run(self):
        # Indítási gap-letöltés: a leállás alatt keletkezett rés pótlása, sorosan,
        # háttérben. A 2 mp késleltetés csak annyi, hogy az ablak előbb kirajzolódjon
        # — a letöltés külön processzben fut, a GUI nem akad meg tőle.
        if self.cfg.get("data", {}).get("gap_fill_on_start", True):
            self.root.after(2000, self._start_startup_gap_fill)
        # Auto-folytatás: a megszakadt optimalizálások újraindítása INDÍTÁSKOR.
        # Késleltetve, hogy a live_trader induló LIVE-jelölése (magic-recovery +
        # run_state) már beálljon → a kereskedő szimbólumokat NE optimalizáljuk.
        if self._auto_resume_opt:
            self.root.after(4000, self._resume_optimizations)
        try:
            self.root.mainloop()
        finally:
            try:
                self._opt_ctrl.shutdown()
            except Exception:
                pass

    def _resume_optimizations(self):
        """A befejezetlen study-k sorba állítása (háttérszálon, hogy az UI ne akadjon)."""
        threading.Thread(target=self._opt_ctrl.resume_unfinished, daemon=True,
                         name="OptResume").start()


# ---------------------------------------------------------------------------
# Demo mód
# ---------------------------------------------------------------------------

def _demo_dashboard(cfg: dict):
    """Demo: UI layout + state machine bemutatása MT5 nélkül.
    A stratégia-cellákat szimulált értékekkel tölti, hogy az oszlopok lássanak."""
    import random
    from trading.live_trader import PairDashboardState

    strategy   = get_strategy(cfg)
    from core.params_store import set_active_strategy, strategy_dir
    set_active_strategy(strategy.name)
    params_dir = strategy_dir(strategy.name)
    real_trained = {f.stem for f in params_dir.glob("*.json")} if params_dir.exists() else set()
    symbols = [s for s, p in cfg["pairs"].items() if isinstance(p, dict)]

    states_pool = ["LIVE"] * 4 + ["STOPPED"] * 6
    random.shuffle(states_pool)

    db, inst_state, opt_status = {}, {}, {}
    from strategy import (available_strategy_names, get_strategy_by_name,
                          enabled_strategy_names as _enabled_names)
    reg_strats = [get_strategy_by_name(n) for n in available_strategy_names(cfg)]
    # Per-stratégia stádium-kulcsok a demó köreihez {strat_név: [stádium_kulcs,…]}
    stages_by_strat = {st.name: [sk for c in st.columns() if c.kind == "marker"
                                 for sk, _ in c.stages] for st in reg_strats}

    for i, symbol in enumerate(symbols):
        trained = symbol in real_trained
        st      = states_pool[i % len(states_pool)] if trained else "STOPPED"
        inst_state[symbol] = st
        opt_status[symbol] = OptStatus(_t("opt.done"), OPT_DONE) if trained else ""

        # Valós minősítés a test_summary alapján (ha optimalizált)
        grade_cell, grade_reason = None, ""
        if trained:
            try:
                _data = json.load(open(params_dir / f"{symbol}.json", encoding="utf-8"))
                gtxt, gcol, greason = strategy.grade(_data.get("test_summary", {}), cfg)
                grade_cell, grade_reason = (gtxt, gcol), greason
            except Exception:
                pass

        base = round(random.uniform(0.9, 1.6), 5)
        ds = PairDashboardState(
            symbol=symbol, enabled=trained, trained=trained,
            bid=base, ask=round(base + 0.0002, 5), prev_bid=base, prev_ask=base,
            digits=5, day_open=round(base * random.uniform(0.99, 1.01), 5),
            change_pct=round(random.uniform(-0.6, 0.6), 2),
            spread_pts=random.randint(6, 18), max_spread_pts=random.randint(12, 25),
            position_pnl=None, risk_free=False, daily_pnl=0.0,
            opt_grade=grade_cell, opt_grade_reason=grade_reason,
            # Per-pár engedélyezett stratégiák (mint az éles induláskor) — a
            # jelölő-oszlop a nem engedélyezettet apró ponttal különbözteti meg.
            enabled_strategies=_enabled_names(cfg, symbol),
        )
        # Stratégia-cellák szimulálása per stratégia (csak LIVE pároknál)
        if st == "LIVE":
            for sname, sks in stages_by_strat.items():
                ds.strategy_cells[sname] = {
                    sk: ("●", random.choice(["green", "red", "muted", "muted"]))
                    for sk in sks}
        for tf in strategy.timeframes():
            ds.timeframe_remaining[tf.minutes] = random.randint(0, tf.minutes * 60 - 1)
        db[symbol] = ds

    return db, inst_state, opt_status, 0


if __name__ == "__main__":
    cfg_path = ROOT / "config.json"
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    db, inst_state, opt_status, n_pos = _demo_dashboard(cfg)
    win = DashboardWindow(cfg, db, inst_state, opt_status,
                          on_play_pair=None, on_stop_pair=None)
    max_s = cfg["trading"]["max_open_slots"]
    win.set_balance(1024.50)
    win.set_slots(free=max(0, max_s - n_pos), max_s=max_s)
    win.run()

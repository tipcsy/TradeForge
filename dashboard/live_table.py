"""
A Dashboard 2.0 TÁBLÁJA — fix bal · görgethető közép · fix jobb.

A felhasználó terve (7. pont): „az elején fix (Instrumentum) és a végén fix
(Összesítő) szélesség van, a közepén, azok amik többen vannak és összecsukhatóak,
azok meg scrollozhatóak jobbra balra."

A LEGFONTOSABB SZERKEZETI DÖNTÉS — miért nem tud elcsúszni a fejléc:

    A fejléc közepe és a sorok közepe UGYANABBA a vászonba kerül.

Kézenfekvő lenne két külön vászon (egy a fejlécnek, egy a törzsnek), és a két
`xview` szinkronban tartása. Az viszont *futásidejű* egyezés: elég egy elmaradt
frissítés, és a fejléc az oszlopok mellé csúszik — pontosan az a hiba, ami ellen
a legnehezebb védekezni, mert csak görgetés közben látszik. Egy vászonnal ez
SZERKEZETILEG lehetetlen: nincs mit szinkronizálni.

FÜGGŐLEGES GÖRGETÉS NINCS, és ez szándékos: a sorok fix magasságúak (~28 px), és
egy-két tucat instrumentum elfér egy képernyőn. Ha egyszer mégis kell, a három
oszlopot EGY közös függőleges vászonba kell tenni — nem oszloponként külön,
mert akkor a sorok elcsúsznának egymáshoz képest.

ÖSSZECSUKÁS: tábla-szintű (kapuk), illetve stratégiánként — de MINDEN sorra
egyszerre. Ha soronként lehetne, az oszlopok nem állnának egy vonalban. A
kapcsolók a fejléc csoport-felirataiban vannak (`▾`/`▸`), ott, ahol a hatásuk
látszik.
"""

from __future__ import annotations

import tkinter as tk

from dashboard.theme import BG, BG_HEADER, FG_GRAY_DIM
from dashboard.live_row import (
    LiveRow, build_header, row_height, is_collapsed, GAP,
)

# A sorok közti függőleges hézag — MINDHÁROM oszlopban azonos, különben a
# bal/közép/jobb sorai elcsúsznának egymáshoz képest.
ROW_PAD = 1

# A saját gördítősáv magassága.
BAR_H = 8


class _ThinScrollbar(tk.Canvas):
    """Vékony, TÉMÁHOZ ILLŐ vízszintes gördítősáv.

    Miért nem `tk.Scrollbar`: Windowson a natív megjelenítést használja, és a
    `bg`/`troughcolor` beállítást FIGYELMEN KÍVÜL HAGYJA — a sötét táblán vakító
    fehér csík marad. (Ellenőrizve: feltűnő zöldre állítva is fehér maradt.)

    Miért nem `ttk.Scrollbar`: az színezhető lenne, de csak a `clam` témával, a
    `theme_use` viszont GLOBÁLIS — átírná az alkalmazás összes ttk-widgetjét
    (fülek, legördülők). Egy gördítősáv nem ér ennyit.

    Marad a saját rajz: teljes kontroll, nulla mellékhatás. Húzható, és a
    `Shift`+görgő is működik (a vízszintes görgetés szokásos billentyűje)."""

    def __init__(self, parent, canvas):
        super().__init__(parent, height=BAR_H, bg=BG, highlightthickness=0, bd=0)
        self._c = canvas
        self._lo, self._hi = 0.0, 1.0
        self._thumb = self.create_rectangle(0, 0, 0, BAR_H, fill=BG_HEADER,
                                            outline="")
        self._drag_x = None
        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", lambda _e: self._end())
        for w in (canvas, self):
            w.bind("<Shift-MouseWheel>", self._wheel, add="+")

    def set(self, lo, hi):
        self._lo, self._hi = float(lo), float(hi)
        self._redraw()

    def _redraw(self):
        w = max(1, self.winfo_width())
        x0, x1 = self._lo * w, self._hi * w
        if x1 - x0 < 24:                 # túl rövid fogantyú nem megfogható
            x1 = x0 + 24
        self.coords(self._thumb, x0, 1, min(x1, w), BAR_H - 1)

    def _press(self, e):
        w = max(1, self.winfo_width())
        x0, x1 = self._lo * w, self._hi * w
        if x0 <= e.x <= x1:
            self._drag_x = e.x           # a fogantyún kezdtük → húzás
        else:
            self._c.xview_moveto(max(0.0, e.x / w - (self._hi - self._lo) / 2))

    def _drag(self, e):
        if self._drag_x is None:
            return
        w = max(1, self.winfo_width())
        self._c.xview_moveto(max(0.0, self._lo + (e.x - self._drag_x) / w))
        self._drag_x = e.x

    def _end(self):
        self._drag_x = None

    def _wheel(self, e):
        self._c.xview_scroll(-1 if e.delta > 0 else 1, "units")
        return "break"


class LiveTable:
    """A teljes tábla. `refresh(rows)` cseréli az adatot; a `collapsed` állapotot
    a fejléc kapcsolói állítják, és a tábla újraépíti magát."""

    def __init__(self, parent, fonts: dict, rows=None, collapsed: dict = None,
                 on_close=None, on_collapse_change=None):
        self._parent = parent
        self._f = fonts
        self._rows = list(rows or [])
        self._collapsed = {"gates": False, "strategies": set()}
        self._collapsed.update(collapsed or {})
        self._on_close = on_close
        self._on_collapse_change = on_collapse_change

        self.frame = tk.Frame(parent, bg=BG)
        self._build()

    # ── Felépítés ────────────────────────────────────────────────────────
    def _build(self):
        for w in self.frame.winfo_children():
            w.destroy()
        h = row_height(self._f)

        body = tk.Frame(self.frame, bg=BG)
        body.pack(fill="both", expand=True)

        # BAL — fix
        self._left = tk.Frame(body, bg=BG)
        self._left.pack(side="left", fill="y")

        # JOBB — fix. A `pack` ELŐBB kapja meg a helyét, mint a közép (side=right
        # a maradékból dolgozik), így a görgethető rész csak a MARADÉKOT kapja —
        # enélkül a közép kiszorítaná a jobb oszlopot a képernyőről.
        self._right = tk.Frame(body, bg=BG)
        self._right.pack(side="right", fill="y")

        # KÖZÉP — görgethető vászon. A fejléc és a sorok EGY vásznon (lásd doksi).
        wrap = tk.Frame(body, bg=BG)
        wrap.pack(side="left", fill="both", expand=True)
        self._canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0, bd=0)
        self._canvas.pack(side="top", fill="both", expand=True)
        self._hbar = _ThinScrollbar(wrap, self._canvas)
        self._canvas.configure(xscrollcommand=self._on_xscroll)
        self._mid = tk.Frame(self._canvas, bg=BG)
        self._mid_id = self._canvas.create_window((0, 0), window=self._mid,
                                                  anchor="nw")

        # ── Fejléc: a három rész a három oszlopba ──
        names = self._strategy_names()
        build_header((self._left, self._mid, self._right), self._f, names,
                     self._collapsed, on_toggle=self._toggle)

        # ── Sorok ──
        self._row_widgets = []
        for i, d in enumerate(self._rows):
            r = LiveRow((self._left, self._mid, self._right), d, self._f,
                        self._collapsed, stripe=i,
                        on_close=(lambda s=d.get("symbol"): self._close(s)))
            for part in (r.left, r.mid, r.right):
                part.pack_configure(pady=(0, ROW_PAD))
            self._row_widgets.append(r)

        self._mid.bind("<Configure>", self._sync_scrollregion)
        self._canvas.bind("<Configure>", self._sync_scrollregion)
        self.frame.after_idle(self._sync_scrollregion)

    def _strategy_names(self) -> list:
        """A stratégiák a SORREND szerint, az első sorból. Minden sornak ugyanaz
        a listája kell legyen — különben az oszlopok nem állnának egy vonalban.
        (A hívó dolga, hogy így töltse; itt csak az első sor a mérvadó.)"""
        for d in self._rows:
            return [s.get("name", "") for s in (d.get("strategies") or [])]
        return []

    # ── Görgetés ─────────────────────────────────────────────────────────
    def _on_xscroll(self, lo, hi):
        """A vízszintes gördítősáv CSAK akkor látszik, ha van mit görgetni.
        Enélkül összecsukott állapotban is ott ülne egy használhatatlan sáv."""
        self._hbar.set(lo, hi)
        needed = not (float(lo) <= 0.0 and float(hi) >= 1.0)
        if needed and not self._hbar.winfo_ismapped():
            self._hbar.pack(side="bottom", fill="x")
        elif not needed and self._hbar.winfo_ismapped():
            self._hbar.pack_forget()

    def _sync_scrollregion(self, _e=None):
        """A vászon görgetési tartománya = a benne lévő keret TÉNYLEGES mérete.
        A magasságot rá is kényszerítjük a vászonra, különben a vászon a saját
        kért méretét tartaná, és a sorok alja levágódna."""
        self._canvas.update_idletasks()
        w = self._mid.winfo_reqwidth()
        h = self._mid.winfo_reqheight()
        self._canvas.configure(scrollregion=(0, 0, w, h), height=h)
        self._canvas.itemconfigure(self._mid_id, width=w, height=h)

    # ── Vezérlés ─────────────────────────────────────────────────────────
    def _toggle(self, key: str):
        """Összecsukás/kinyitás. `key` = `"gates"` vagy egy stratégia neve.

        A tábla ÚJRAÉPÜL: az oszlop-szélességek az összecsukástól függenek
        (`live_row.widths`), tehát részleges frissítés úgyis mindent érintene —
        egy-két tucat sornál az újraépítés a rövidebb és biztosabb út."""
        if key == "gates":
            self._collapsed["gates"] = not self._collapsed.get("gates")
        else:
            s = self._collapsed.get("strategies")
            s = set() if s is True or not s else set(s)
            s.symmetric_difference_update({key})
            self._collapsed["strategies"] = s
        self._build()
        if self._on_collapse_change:
            self._on_collapse_change(dict(self._collapsed))

    def _close(self, symbol):
        if self._on_close:
            self._on_close(symbol)

    # ── Adat ─────────────────────────────────────────────────────────────
    def refresh(self, rows):
        """Új adat. Egyelőre teljes újraépítés — a cellánkénti frissítés akkor
        válik fontossá, amikor a tábla élő adatra kerül (másodpercenként)."""
        self._rows = list(rows or [])
        self._build()

    @property
    def collapsed(self) -> dict:
        return {"gates": self._collapsed.get("gates"),
                "strategies": set(self._collapsed.get("strategies") or ())}


# ---------------------------------------------------------------------------
# Bemutató a tools/ui_preview.py-hoz
# ---------------------------------------------------------------------------

def build_demo(parent, collapsed: dict = None, rows: int = 4):
    from tkinter import font as tkfont
    from dashboard.live_row import demo_row
    fonts = {
        "mono": tkfont.Font(family="Consolas", size=10),
        "mono_b": tkfont.Font(family="Consolas", size=10, weight="bold"),
        "small": tkfont.Font(family="Segoe UI", size=9),
    }
    syms = ("Ger 40", "UsaTec", "EURUSD", "GOLD")
    data = []
    for i in range(rows):
        d = demo_row()
        d["symbol"] = syms[i % len(syms)]
        if i == 1:
            d["gates"]["badge"] = "✓"
            d["gates"]["spread"]["text"] = "180/1312"
            d["strategies"][0]["frame"] = ""
        if i == 2:
            d["gates"]["badge"] = "✓"
            d["strategies"][0]["frame"] = "reduced"
            d["strategies"][1]["daily"] = {"money": -4.20, "r": -0.28}
        if i == 3:
            d["strategies"][1]["position"] = {"money": None, "r": None}
            d["strategies"][1]["daily"] = {"money": 0.0, "r": None}
        data.append(d)
    t = LiveTable(parent, fonts, data, collapsed)
    t.frame.pack(fill="both", expand=True)
    return t

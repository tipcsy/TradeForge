"""
A tábla VÁSZONRA rajzolva — ugyanaz a látvány, nagyságrendekkel olcsóbban.

MIÉRT. A widget-tábla cellánként egy `Frame` + egy `Label`; a cél-skálán
(30 instrumentum × 10 stratégia) ez 6427 widget, és a Tk geometria-kezelése
lineárisan drágul vele. Mérve: a tábla FELÉPÍTÉSE 13,3 mp (és az minden
összecsukásnál/rendezésnél lefut), egy átméretezési lépés 585 ms. Ugyanez
vászonra rajzolva 396 ms, illetve 6,8 ms — 34×, illetve 86×.

Fontos, amit a mérés CÁFOLT: a lassúság NEM elrontott `<Configure>`-kezelőből
jön. Csupasz Tk ugyanennyi widgettel 224–315 ms/lépés — a program a Tk saját
alapköltségén van. A kezelők csillapítását A/B-vel megmértem, nem hozott
mérhető javulást, ezért nem is maradt bent. A widget-szám az egyetlen kar.

HÁROM DOLOG, AMIT A VÁSZON INGYEN AD:
  • Görgetés: a `yview` a vászon natív művelete — NEM jár újrarajzolással,
    tehát nincs szükség sor-virtualizálásra sem. (Ezért rajzolunk MINDEN sort
    egyszer, és utána csak `itemconfigure`-ozunk.)
  • Átméretezés: az oszlopok x-e nem függ az ablakmérettől (aritmetika, lásd
    `canvas_columns`), tehát átméretezéskor NINCS elrendezés-számítás.
  • Rajzelemek (elválasztó vonalak, nyilak) — widgetekkel költségesek, itt
    egy `create_line`.

AZONOS LÁTVÁNY. Az oszlop-szélességek a meglévő `live_row.widths()`-ből jönnek,
a cellák szövegét/színét pedig a `canvas_cells` állítja elő a `live_row`
formázóival. A renderelő cseréje nem változtathat azon, ami a képernyőn van.
"""

from __future__ import annotations

import tkinter as tk

from dashboard import canvas_cells as _cc
from dashboard import canvas_columns as _cols
from dashboard import live_row as _lr
from dashboard.theme import (BG, BG_HEADER, BG_ROW_ODD, BG_ROW_EVEN, FG_WHITE,
                             FG_GRAY_DIM, FG_BLUE, FG_ORANGE, FG_RED)

PAD = _lr.PAD
GAP = _lr.GAP
ROW_PAD = 1
BAR_H = 8      # a vízszintes sáv magassága
BAR_W = 14     # a FÜGGŐLEGESÉ szélesebb: azt húzod a leggyakrabban

# A jelzes-cella KERETE: tomor piros = blokkolva, SZAGGATOTT sarga =
# kockazatcsokkentes. A szaggatas az EREDETI terv volt (lasd `live_row.py`
# `_DOT` folott): widgetekkel nem ment, mert a `highlightthickness` nem tud
# szaggatott lenni, es cellankent kulon `Canvas` "sok sornal folosleges teher"
# lett volna. A tabla most eleve vaszon -> ingyen van.
#
# MIERT SZAMIT: eddig a ket allapotot CSAK a szin kulonboztette meg. Most az
# ALAKJA is mas, tehat egy pillantasbol — es szin-teveszto szemmel is —
# megkulonboztetheto, hogy a kapu blokkol-e vagy csak meretet csokkent.
_FRAME_STYLE = {"blocked":  {"outline": FG_RED,    "dash": (), "width": 1},
                "reduced":  {"outline": FG_ORANGE, "dash": (3, 2), "width": 1}}


def groups(strategies, collapsed: dict = None) -> list:
    """`[(felirat, [oszlopkulcs, …], kapcsoló_kulcs), …]` — a fejléc 1. sora.

    A `kapcsoló_kulcs` az összecsukó gomb azonosítója (`"gates"` vagy a
    stratégia neve); `None` = nem összecsukható csoport."""
    collapsed = collapsed or {}
    out = [("Instrumentum", ["symbol", "bid", "ask", "change"], None)]
    if not collapsed.get("gates"):
        gk = ["spread", "align"]
        if _lr.show_market(collapsed):
            gk.append("market")
        if _lr.show_momentum(collapsed):
            gk.append("momentum")
        out.append(("Kapuk", gk, "gates"))
    for n in (strategies or []):
        if _lr.is_collapsed(collapsed, n):
            out.append((n, [f"{n}|stages", f"{n}|ctrl"], n))
        else:
            out.append((n, [f"{n}|{k}" for k in
                            ("stages", "position", "daily", "quality", "ctrl", "opt")], n))
    out.append(("Összesítő", ["total_pos", "total_daily"], None))
    return out


class _ThinScrollbar(tk.Canvas):
    """Vékony, TÉMÁHOZ ILLŐ gördítősáv — vízszintes ÉS függőleges.

    Miért nem `tk.Scrollbar`: Windowson a natív megjelenítést használja, és a
    `bg`/`troughcolor` beállítást figyelmen kívül hagyja — a sötét táblán vakító
    fehér csík marad. (A `live_table` ugyanezért rajzolja a sajátját; itt a
    függőleges változat is kellett, mert a vászon-tábla maga görget.)

    A FÜGGŐLEGES szándékosan szélesebb (`BAR_W`), mint a vízszintes magassága:
    azt húzod a leggyakrabban, és egy 8 px-es csíkot nehéz eltalálni."""

    def __init__(self, parent, canvases, orient="horizontal"):
        self._vert = (orient == "vertical")
        kw = ({"width": BAR_W} if self._vert else {"height": BAR_H})
        super().__init__(parent, bg=BG, highlightthickness=0, bd=0, **kw)
        self._cs = list(canvases)
        self._lo, self._hi = 0.0, 1.0
        self._thumb = self.create_rectangle(0, 0, 0, 0, fill=BG_HEADER, outline="")
        self._drag = None
        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", lambda _e: setattr(self, "_drag", None))

    def set(self, lo, hi):
        self._lo, self._hi = float(lo), float(hi)
        self._redraw()

    def _span(self) -> int:
        return max(1, self.winfo_height() if self._vert else self.winfo_width())

    def _redraw(self):
        n = self._span()
        a, b = self._lo * n, self._hi * n
        if b - a < 24:                      # túl rövid fogantyú nem megfogható
            b = a + 24
        b = min(b, n)
        if self._vert:
            self.coords(self._thumb, 1, a, BAR_W - 1, b)
        else:
            self.coords(self._thumb, a, 1, b, BAR_H - 1)

    def _moveto(self, frac):
        for c in self._cs:
            (c.yview_moveto if self._vert else c.xview_moveto)(max(0.0, frac))

    def _pos(self, e):
        return e.y if self._vert else e.x

    def _press(self, e):
        n = self._span()
        a, b = self._lo * n, self._hi * n
        if a <= self._pos(e) <= b:
            self._drag = self._pos(e)       # a fogantyún kezdtük → húzás
        else:
            self._moveto(self._pos(e) / n - (self._hi - self._lo) / 2)

    def _motion(self, e):
        if self._drag is None:
            return
        n = self._span()
        self._moveto(self._lo + (self._pos(e) - self._drag) / n)
        self._drag = self._pos(e)


class CanvasTable:
    """A `LiveTable` vászon-alapú megfelelője — AZONOS publikus felülettel
    (`frame`, `refresh(rows)`, `rebuild()`, `sort()`, `collapsed()`), hogy a
    `gui.py` szempontjából csereszabatos legyen."""

    def __init__(self, parent, fonts: dict, rows=None, collapsed: dict = None,
                 on_close=None, on_collapse_change=None, on_sort_change=None):
        self._parent = parent
        self._f = fonts
        self._rows = list(rows or [])
        self._collapsed = {"gates": False, "strategies": set()}
        self._collapsed.update(collapsed or {})
        self._on_close = on_close
        self._on_collapse_change = on_collapse_change
        self._on_sort_change = on_sort_change
        self._sort_key, self._sort_dir = None, 1
        self._h = _lr.row_height(fonts)
        self._items = {}        # (sor_index, oszlop_kulcs) -> [elem_id, …]
        self._visual = {}       # (sor_index, oszlop_kulcs) -> a kiírt állapot
        # (sor_index, oszlop_kulcs[, alkulcs]) -> visszahívás. KÖZPONTI elosztó:
        # a `tag_bind` csak ide mutat. Így a kattintás-huzalozás EGY helyen
        # ellenőrizhető (a teszt közvetlenül a `fire()`-t hívja, nem szintetikus
        # egéreseményt kerget), és nem szóródnak szét closure-ök a rajzolóban.
        self._clicks = {}
        self.frame = tk.Frame(parent, bg=BG)
        self._build()

    # ── Felépítés ────────────────────────────────────────────────────────
    def _build(self):
        for w in self.frame.winfo_children():
            w.destroy()
        self._items.clear()
        self._visual.clear()
        self._clicks.clear()
        rows = self._visible()
        strategies = self._strategy_names()
        self._collapsed["hide_market"] = self._want_hide("market")
        self._collapsed["hide_momentum"] = self._want_hide("momentum")
        self._cols = _cols.layout(self._f, strategies, self._collapsed)
        # Sávonként külön vászon: a bal és a jobb RÖGZÍTETT, a közép görög —
        # ugyanaz az elrendezés, mint a widget-táblában.
        self._by_pane = {"left": [], "mid": [], "right": []}
        for key, x, w in self._cols:
            self._by_pane[_cc.PANE_OF(_cols.base_key(key))].append((key, x, w))
        self._pane_x0 = {}
        for pane, cs in self._by_pane.items():
            x0 = cs[0][1] if cs else 0
            self._pane_x0[pane] = x0

        head = tk.Frame(self.frame, bg=BG_HEADER)
        head.pack(fill="x")
        body = tk.Frame(self.frame, bg=BG)
        body.pack(fill="both", expand=True)

        self._hc, self._bc = {}, {}
        # A JOBB sáv kapja meg először a helyét (mint a widget-táblában), különben
        # a közép kiszorítaná a képernyőről.
        self._vbar = _ThinScrollbar(body, [], orient="vertical")
        self._vbar.pack(side="right", fill="y")
        for pane, side in (("left", "left"), ("right", "right"), ("mid", "left")):
            wd = self._pane_width(pane)
            hc = tk.Canvas(head, bg=BG_HEADER, highlightthickness=0,
                           height=2 * self._h, width=wd)
            bc = tk.Canvas(body, bg=BG, highlightthickness=0, width=wd)
            if pane == "mid":
                hc.pack(side=side, fill="x", expand=True)
                bc.pack(side=side, fill="both", expand=True)
            else:
                hc.pack(side=side, fill="y")
                bc.pack(side=side, fill="y")
            bc.configure(yscrollcommand=self._vbar.set)
            self._hc[pane], self._bc[pane] = hc, bc

        # A közép vízszintes görgetése: a fejléc és a törzs EGYÜTT mozog.
        self._vbar._cs = list(self._bc.values())     # mind a három sáv EGYÜTT gördül
        self._hbar = _ThinScrollbar(self.frame, [self._hc["mid"], self._bc["mid"]])
        self._bc["mid"].configure(xscrollcommand=self._on_xscroll)

        self._draw_header()
        self._draw_rows(rows)
        self._sync_regions()
        # ⚠ A görgetési tartományt SZÁNDÉKOSAN NEM kötjük `<Configure>`-re.
        # Az a TARTALOMTÓL függ (oszlop-szélesség × sorszám), nem az ablakmérettől
        # — átméretezéskor tehát nincs mit újraszámolni. Egy korábbi változat
        # mégis rákötötte, és ezzel visszahozta pontosan azt a mintát, amit a
        # widget-tábláról kimutattunk: a kezelő `configure()`-t hív, az ÚJABB
        # `<Configure>`-t kelt. Mérve 75 → 156 ms/lépés volt az ára.
        for pane in ("left", "mid", "right"):
            self._bc[pane].bind("<Enter>", self._wheel_on)
            self._bc[pane].bind("<Leave>", self._wheel_off)

    def _pane_width(self, pane: str) -> int:
        cs = self._by_pane.get(pane) or []
        if not cs:
            return 1
        return (cs[-1][1] + cs[-1][2]) - cs[0][1] + GAP

    def _want_hide(self, key: str) -> bool:
        """Elrejtsük-e a `Piac` / `Lendület` oszlopot? Ugyanaz a szabály, mint a
        widget-táblában: ha EGYETLEN soron sincs mért érték, az oszlop végig `—`
        lenne. A döntés EGY helyen születik, a fejléc és a sorok ugyanazt kapják."""
        return not any(((d.get("gates") or {}).get(key) or {}).get("text")
                       not in (None, "", "—") for d in self._rows)

    # ── Fejléc ───────────────────────────────────────────────────────────
    def _draw_header(self):
        f_small = self._f["small"]
        for pane, hc in self._hc.items():
            hc.delete("all")
            x0 = self._pane_x0[pane]
            # 1. sor: csoportok
            for label, keys, tkey in groups(self._strategy_names(), self._collapsed):
                spans = [c for c in self._by_pane[pane] if c[0] in keys]
                if not spans:
                    continue
                gx0 = spans[0][1] - x0
                gx1 = spans[-1][1] + spans[-1][2] - x0
                txt = label
                if tkey is not None:
                    txt = ("▸ " if self._is_coll(tkey) else "▾ ") + label
                t = hc.create_text((gx0 + gx1) / 2, self._h / 2, text=txt,
                                   fill=(FG_BLUE if tkey and tkey != "gates"
                                         else FG_GRAY_DIM), font=f_small)
                if tkey is not None:
                    hc.tag_bind(t, "<Button-1>",
                                lambda _e, k=tkey: self._toggle(k))
                    hc.itemconfigure(t, tags=(f"grp_{tkey}",))
                    hc.tag_bind(f"grp_{tkey}", "<Button-1>",
                                lambda _e, k=tkey: self._toggle(k))
            # Összecsukott kapuknál a K.Össz. fejléce a kapcsoló (különben nem
            # lehetne visszanyitni — a „Kapuk" felirat ilyenkor nem létezik).
            if self._collapsed.get("gates") and pane == "mid":
                sp = _cols.x_of(self._cols, "badge")
                if sp:
                    t = hc.create_text(sp[0] - x0 + sp[1] / 2, self._h / 2,
                                       text="▸ K.Ö.", fill=FG_GRAY_DIM, font=f_small)
                    hc.tag_bind(t, "<Button-1>", lambda _e: self._toggle("gates"))
            # 2. sor: oszlopnevek (kattintva rendez)
            for key, x, w in self._by_pane[pane]:
                base = _cols.base_key(key)
                label = _lr._HEADER_TEXT.get(base, "")
                if not label:
                    continue
                mark = ""
                if self._sort_key == key:
                    mark = " ▼" if self._sort_dir < 0 else " ▲"
                # Az „Együtt" a pöttyök oszlopa: nincs értelmes rendezési értéke,
                # ezért az egyetlen nem kattintható fejléc a blokkban.
                sortable = base != "align"
                t = hc.create_text(x - x0 + PAD, self._h + self._h / 2,
                                   text=label + mark, anchor="w", font=f_small,
                                   fill=(FG_WHITE if self._sort_key == key
                                         else FG_GRAY_DIM))
                if sortable:
                    hc.tag_bind(t, "<Button-1>", lambda _e, k=key: self._sort(k))

    # ── Sorok ────────────────────────────────────────────────────────────
    def _draw_rows(self, rows):
        for pane, bc in self._bc.items():
            bc.delete("all")
        for i, d in enumerate(rows):
            self._draw_row(i, d)
        self._draw_separators(len(rows))

    def _block_edges(self) -> dict:
        """Sávonként az x-ek, ahol EGYIK blokk véget ér és a másik kezdődik.

        Widgetekkel ez külön keret-widgeteket jelentett volna SORONKÉNT (10 sor ×
        12 blokk = 120 widget csak a vonalakhoz); vásznon sávonként EGY
        `create_line` az egész oszlopra. A 10 stratégiás nézetben ez az, ami a
        blokkokat egyáltalán elkülöníthetővé teszi."""
        out = {"left": [], "mid": [], "right": []}
        for _label, keys, _tkey in groups(self._strategy_names(), self._collapsed):
            cols = [c for c in self._cols if c[0] in keys]
            if not cols:
                continue
            key = cols[-1][0]
            pane = _cc.PANE_OF(_cols.base_key(key))
            out[pane].append(cols[-1][1] + cols[-1][2] + GAP / 2)
        return out

    def _draw_separators(self, n_rows: int):
        """Függőleges blokk-elválasztók a TELJES tábla magasságában.

        ⚠ A SZÍN nem mindegy. Az első változat `BG_HEADER`-rel rajzolt, ami a
        Mocha témában `#181825` — a sorok háttere `#1e1e2e` és `#242438`, tehát
        csatornánként ~6 árnyalat a különbség: a vonal LÉTEZETT, de gyakorlatilag
        láthatatlan volt (a felhasználó éles próbán nem is vette észre). A
        `FG_GRAY_DIM` az a szín, amit a keretrendszer máshol is elválasztásra
        használ — látszik, de nem hangos."""
        h = max(1, n_rows * (self._h + ROW_PAD))
        edges = self._block_edges()
        for pane, bc in self._bc.items():
            x0 = self._pane_x0[pane]
            right = self._pane_width(pane) + x0
            for x in edges[pane]:
                if x >= right - 1:
                    continue          # a sáv szélén nem kell vonal
                bc.create_line(x - x0, 0, x - x0, h, fill=FG_GRAY_DIM,
                               tags="sep")
            self._hc[pane].delete("sep")
            for x in edges[pane]:
                if x >= right - 1:
                    continue
                self._hc[pane].create_line(x - x0, 0, x - x0, 2 * self._h,
                                           fill=FG_GRAY_DIM, tags="sep")

    def _draw_row(self, i: int, d: dict):
        y0 = i * (self._h + ROW_PAD)
        bg = BG_ROW_EVEN if i % 2 == 0 else BG_ROW_ODD
        cells = _cc.cells_for(d, self._collapsed,
                              on_close=(lambda s=d.get("symbol"): self._close(s)))
        for pane, bc in self._bc.items():
            x0 = self._pane_x0[pane]
            bc.create_rectangle(0, y0, self._pane_width(pane) + 4000,
                                y0 + self._h, fill=bg, outline="")
        for key, x, w in self._cols:
            cell = cells.get(key)
            if cell is None:
                continue
            pane = _cc.PANE_OF(_cols.base_key(key))
            self._draw_cell(self._bc[pane], i, cell, x - self._pane_x0[pane], w,
                            y0, bg)

    def _draw_cell(self, bc, i, cell, x, w, y0, bg):
        ids = []
        cy = y0 + self._h / 2
        tag = f"c{i}_{cell.key}"
        if cell.kind == "dots":
            # A pöttyök a cella KÖZEPÉN, egy sorban — a keret (az engedély
            # jelzése) egy 1 px-es téglalap köréjük.
            # MINDEN pötty ● marad — az „Együtt" oszlopban is. (Egy köztes
            # változat ott ▲/▼ nyilat rajzolt, hogy az irány ne csak a színen
            # múljon; a felhasználó eldobta: a zöld/piros pötty a megszokott, és
            # a nyilak zsúfoltabbá tették a cellát.)
            fdot = self._f["mono"]
            dw = fdot.measure(_lr._DOT)
            total = dw * max(1, len(cell.dots))
            sx = x + (w - total) / 2
            if cell.frame:
                st = _FRAME_STYLE.get(cell.frame) or {}
                r = bc.create_rectangle(sx - 4, y0 + 2, sx + total + 4,
                                        y0 + self._h - 2, outline="",
                                        dash=st.get("dash", ()),
                                        width=st.get("width", 1))
                ids.append(r)
            for k, col in enumerate(cell.dots):
                ids.append(bc.create_text(sx + k * dw + dw / 2, cy, text=_lr._DOT,
                                          fill=col, font=fdot, tags=(tag,)))
        elif cell.kind == "ctrl":
            fsm = self._f["small"]
            widths = [fsm.measure(p[1]) + 2 * _lr.CTRL_PADX for p in cell.parts]
            total = sum(widths) + _lr.CTRL_GAP
            sx = x + (w - total) / 2
            for (sub, txt, fg, cb, active), pw in zip(cell.parts, widths):
                t = bc.create_text(sx + pw / 2, cy, text=txt, fill=fg, font=fsm,
                                   tags=(f"{tag}_{sub}",))
                ids.append(t)
                if cb:
                    self._clicks[(i, cell.key, sub)] = cb
                    bc.tag_bind(f"{tag}_{sub}", "<Button-1>",
                                lambda _e, a=(i, cell.key, sub): self.fire(*a))
                sx += pw + (_lr.CTRL_GAP if sub == "run" else 0)
        else:
            if cell.anchor == "e":
                tx, anc = x + w - PAD, "e"
            elif cell.anchor == "center":
                tx, anc = x + w / 2, "center"
            else:
                tx, anc = x + PAD, "w"
            ids.append(bc.create_text(tx, cy, text=cell.text, fill=cell.fg,
                                      anchor=anc, font=self._f[cell.font],
                                      tags=(tag,)))
        if cell.on_click:
            # A kattintható cella TELJES területe fogjon, ne csak a betűk — a
            # widget-változatban ezt a keret adta. Átlátszó téglalap NINCS a
            # vásznon, ezért a háttér színével rajzolunk, és legalulra tesszük.
            hit = bc.create_rectangle(x, y0, x + w, y0 + self._h,
                                      fill=bg, outline="", tags=(tag,))
            bc.tag_lower(hit)
            ids.insert(0, hit)
            self._clicks[(i, cell.key)] = cell.on_click
            bc.tag_bind(tag, "<Button-1>",
                        lambda _e, a=(i, cell.key): self.fire(*a))
            bc.tag_bind(tag, "<Enter>", lambda _e, b=bc: b.configure(cursor="hand2"))
            bc.tag_bind(tag, "<Leave>", lambda _e, b=bc: b.configure(cursor=""))
        self._items[(i, cell.key)] = ids
        self._visual[(i, cell.key)] = cell.visual()
        if cell.kind == "dots" and cell.frame:
            bc.itemconfigure(ids[1] if cell.on_click else ids[0],
                             outline=(_FRAME_STYLE.get(cell.frame) or {}).get(
                                 "outline", ""))

    def fire(self, row_index: int, key: str, sub: str = None) -> bool:
        """Egy cella kattintásának KIVÁLTÁSA. Minden `tag_bind` ide mutat, tehát
        ez az EGYETLEN út — amit a teszt közvetlenül hívhat, szintetikus
        egéresemény nélkül (az a vászon görgetési állapotától és attól függene,
        hogy az ablak látszik-e)."""
        cb = self._clicks.get((row_index, key, sub) if sub else (row_index, key))
        if cb is None:
            return False
        cb()
        return True

    def clickable(self) -> set:
        """Mely cellák kattinthatók — a huzalozás ellenőrzéséhez."""
        return set(self._clicks)

    # ── HELYBEN frissítés ────────────────────────────────────────────────
    def refresh(self, rows):
        """Új adat. Ha a SZERKEZET változott (más sorok/stratégiák/oszlopok),
        újraépít; egyébként CSAK a ténylegesen megváltozott cellákat írja át —
        ez az, ami miatt a 3 másodperces frissítés nem villog."""
        old_key = self._structure_key()
        self._rows = list(rows)
        if self._structure_key() != old_key:
            self._build()
            return
        for i, d in enumerate(self._visible()):
            cells = _cc.cells_for(d, self._collapsed,
                                  on_close=(lambda s=d.get("symbol"): self._close(s)))
            for key, cell in cells.items():
                if self._visual.get((i, key)) == cell.visual():
                    continue          # nem változott → egyetlen írás sem
                self._visual[(i, key)] = cell.visual()
                self._apply(i, cell)

    def _apply(self, i: int, cell):
        ids = self._items.get((i, cell.key)) or []
        pane = _cc.PANE_OF(_cols.base_key(cell.key))
        bc = self._bc[pane]
        texts = [t for t in ids if bc.type(t) == "text"]
        if cell.kind == "dots":
            for t, col in zip(texts, cell.dots):
                bc.itemconfigure(t, fill=col)
            rects = [t for t in ids if bc.type(t) == "rectangle"]
            if cell.frame and rects:
                st = _FRAME_STYLE.get(cell.frame) or {}
                bc.itemconfigure(rects[-1], outline=st.get("outline", ""),
                                 dash=st.get("dash", ()), width=st.get("width", 1))
            elif rects:
                bc.itemconfigure(rects[-1], outline="", dash=())
        elif cell.kind == "ctrl":
            for t, part in zip(texts, cell.parts):
                bc.itemconfigure(t, text=part[1], fill=part[2])
        elif texts:
            bc.itemconfigure(texts[0], text=cell.text, fill=cell.fg)

    def _structure_key(self) -> tuple:
        """Mi kényszerít ÚJRAÉPÍTÉST: a sorok azonossága/sorrendje, a stratégiák
        listája, a pöttyök száma és az elrejthető oszlopok állapota."""
        return (tuple(d.get("symbol") for d in self._visible()),
                tuple(self._strategy_names()),
                tuple(len(((d.get("gates") or {}).get("align") or {}).get("signs") or [])
                      for d in self._visible()),
                self._want_hide("market"), self._want_hide("momentum"),
                _lr.pnl_mode(self._collapsed))

    def rebuild(self):
        """Újraépítés VÁLTOZATLAN adattal — betűváltás után kell."""
        self._h = _lr.row_height(self._f)
        self._build()

    # ── Görgetés / tartomány ─────────────────────────────────────────────
    def _yview(self, *args):
        for bc in self._bc.values():
            bc.yview(*args)

    def _on_xscroll(self, lo, hi):
        self._hc["mid"].xview_moveto(float(lo))
        self._hbar.set(lo, hi)
        needed = not (float(lo) <= 0.0 and float(hi) >= 1.0)
        if needed and not self._hbar.winfo_ismapped():
            self._hbar.pack(side="bottom", fill="x")
        elif not needed and self._hbar.winfo_ismapped():
            self._hbar.pack_forget()

    def _sync_regions(self):
        h = max(1, len(self._visible()) * (self._h + ROW_PAD))
        for pane, bc in self._bc.items():
            w = self._pane_width(pane)
            bc.configure(scrollregion=(0, 0, w, h))
            self._hc[pane].configure(scrollregion=(0, 0, w, 2 * self._h))

    def _wheel_on(self, _e):
        self.frame.bind_all("<MouseWheel>", self._wheel)

    def _wheel_off(self, _e):
        self.frame.unbind_all("<MouseWheel>")

    def _wheel(self, e):
        for bc in self._bc.values():
            bc.yview_scroll(int(-e.delta / 120), "units")

    # ── Vezérlés ─────────────────────────────────────────────────────────
    def _is_coll(self, key: str) -> bool:
        if key == "gates":
            return bool(self._collapsed.get("gates"))
        return _lr.is_collapsed(self._collapsed, key)

    def _toggle(self, key: str):
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

    def _sort(self, key: str):
        if self._sort_key == key:
            self._sort_dir = -self._sort_dir
        else:
            self._sort_key, self._sort_dir = key, 1
        self._build()
        if self._on_sort_change:
            self._on_sort_change(self._sort_key, self._sort_dir)

    def sort(self) -> tuple:
        return self._sort_key, self._sort_dir

    def collapsed(self) -> dict:
        return dict(self._collapsed)

    def _close(self, symbol):
        if self._on_close and symbol:
            self._on_close(symbol)

    # ── Adat ─────────────────────────────────────────────────────────────
    def _visible(self) -> list:
        from dashboard import row_source as _rsrc
        return _rsrc.sort_rows(self._rows, self._sort_key, self._sort_dir < 0)

    def _strategy_names(self) -> list:
        for d in self._rows:
            return [s.get("name", "") for s in (d.get("strategies") or [])]
        return []

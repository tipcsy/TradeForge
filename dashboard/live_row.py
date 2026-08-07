"""
A Dashboard 2.0 SORA — egy instrumentum, a stratégia-blokkok vízszintesen.

A felhasználó terve (`tananyag/Dashboard Live kinézeti terv.ods`, értelmezve az
Obsidian „Dashboard 2.0 terv" jegyzetben):

    │ Instrumentum │ Kapuk │ K.Össz. │ wpr_sma │ ml_ai │ … │ Összesítő │ X │
      FIX            összecsukható      összecsukható (stratégiánként)  FIX

Se fa, se lapos: **egy sor = egy instrumentum**, és a per-stratégia adat
VÍZSZINTESEN ismétlődik. A fa azért bukott, mert elrejtett dolgokat; a lapos
azért, mert függőlegesen ismételt.

HÁROM SZERKEZETI DÖNTÉS, AMI A KÓDBAN IS LÁTSZIK:

1. A sor HÁROM keretet ad ki (`left` / `mid` / `right`). A tervezett szélesség-
   kezelés fix–görgethető–fix: a tábla a `mid`-et teszi majd görgethető vászonra,
   a két szélső rögzítve marad. A sor ezt nem tudja magáról — csak a darabolást
   biztosítja hozzá.

2. Az ÖSSZECSUKÁS TÁBLA-SZINTŰ, nem soronkénti. Ha soronként lehetne csukni, a
   sorok oszlopai nem állnának egy vonalban — a tábla olvashatatlan lenne. Ezért
   a `collapsed` a sor BEMENETE, nem belső állapota.

3. GOMB HELYETT KATTINTHATÓ LABEL. Mérve: a `tk.Button` a betű sormagasságán
   felül még ~6 px-t tesz hozzá (Windows), amit a `pady=0` nem fog meg — ettől a
   sorok „ugrálnának". A `bd/padx/pady/highlightthickness=0` recept ehhez KEVÉS
   (lásd `tests/test_ui_preview.py`).

A modul TISZTA MEGJELENÍTÉS: az adatot egy sima dict-ben kapja (lásd `demo_row`),
nincs MT5/live_trader függése. Így a `tools/ui_preview.py`-jal kitalált adattal is
renderelhető, és a geometriája teszteléssel őrizhető.
"""

from __future__ import annotations

import tkinter as tk

from dashboard.theme import (
    BG, BG_HEADER, BG_ROW_ODD, BG_ROW_EVEN,
    FG_WHITE, FG_GREEN, FG_RED, FG_GRAY, FG_GRAY_DIM, FG_BLUE, FG_ORANGE,
)

# A cellák közötti hézag és a belső margó — egy helyen, hogy a fejléc és a sor
# BIZTOSAN ugyanúgy számoljon (különben az oszlopok elcsúsznak).
GAP = 6
PAD = 4

# A Vezérlés-cella belső térközei. Élesben a Play/Stop és az OPT „összemosódott",
# ezért mindkettő saját belső margót és egy elválasztó hézagot kapott.
# ⚠ A `widths()` EBBŐL számol: ha itt változtatsz, a cella szélessége követi —
# különben a tartalom kilógna (az első próbánál pontosan ez történt).
CTRL_PADX = 6      # egy vezérlő belső margója (mindkét oldalon)
CTRL_GAP = 8       # a Play/Stop és az OPT közti elválasztás

# Oszlop-szélességek: a LEGROSSZABB ESETŰ szöveg MÉRT szélességéből.
#
# Szándékosan nem karakterszámból és nem bedrótozott pixelből:
#   • a karakter-alapú becslés túlcsordul, mert a `●`, `⛔`, `✓` szélesebb a
#     számjegyeknél — az 1. körben pont ettől vágódott le némán a tartalom;
#   • a fix pixel a felületről állítható betűmérettel csúszna el.
# A mintaszövegek a ténylegesen előforduló leghosszabb alakot képviselik.
_SAMPLE = {
    # A spread-hatar OTJEGYU is lehet: nagy point_size-u parnal az ATR-tag
    # ezresekben jon ki (a valodi dashboardon "370/100000" jelent meg).
    "symbol": ("mono_bold", "XXXXXXXX"), "bid": ("mono", "99999.99"),
    "ask": ("mono", "99999.99"), "change": ("mono", "+99.99%"),
    "spread": ("mono", "99999/99999"), "align": ("mono", "●●●●"),
    "market": ("small", "Sz.Bika"), "badge": ("mono", "⛔9"),
    "stages": ("mono", "●●●●"), "quality": ("small", "Közepes"),
    "ctrl": ("small", "■ OPT"), "opt": ("small", "99/99"),
    "position": ("mono", "+9999.99$ +99.99R"),
    "daily": ("mono", "+9999.99$ +99.99R"),
    "total_pos": ("mono_bold", "+9999.99$ +99.99R"),
    "total_daily": ("mono_bold", "+9999.99$ +99.99R"),
    "close": ("small", "✕"),
}

# ── P&L megjelenítési mód ────────────────────────────────────────────────
# A `Pozíció` és a `Napi P&L` cella mutathat pénzt, R-t vagy mindkettőt. Ha
# nincs rögzített belépéskori kockázat (kézi pozíció SL nélkül, v1.81.0 előtti
# kötés), a „mindkettő" módban a sor fele üresen áll — ezért választható.
#
# A mód a `collapsed` dictben utazik, nem külön paraméterként. Ez tudatos: a
# modul legfontosabb invariánsa, hogy a FEJLÉC és a SOROK ugyanazokat az
# értékeket kapják (különben elcsúsznak az oszlopok) — a `hide_market` már
# ugyanezért került ide. Egy dict = egy dolgot kell átadni, nem hármat.
PNL_MODES = ("money", "r", "both")
_PNL_SAMPLE = {"both": "+9999.99$ +99.99R", "money": "+9999.99$", "r": "+99.99R"}
_PNL_KEYS = ("position", "daily", "total_pos", "total_daily")


def pnl_mode(collapsed: dict) -> str:
    """A P&L-cellák megjelenítési módja: `money` | `r` | `both`.

    Alap: `both` — a modul nem dönt a termék helyett. A tényleges ALAPÉRTELMEZÉS
    (csak dollár) a configban él, lásd `dashboard.pnl_display`."""
    m = (collapsed or {}).get("pnl_mode")
    return m if m in PNL_MODES else "both"


# A FEJLÉC szövegei — az oszlop szélességét ezek is meghatározzák. (Első
# változatban kimaradtak, és a mérés emiatt levágta a „K.Össz." és a „Vezérlés"
# feliratot: a fejléc is tartalom.)
_HEADER_TEXT = {
    "symbol": "Symbol", "bid": "BID", "ask": "ASK", "change": "Vált.%",
    "spread": "Spread", "align": "Együtt", "market": "Piac",
    "badge": "K.Össz.", "stages": "jelzés", "position": "Pozíció",
    "daily": "Napi P&L", "quality": "Min.", "ctrl": "Vezérlés", "opt": "Opt",
    "total_pos": "Pozíció", "total_daily": "Napi P&L", "close": "",
}


def show_market(collapsed: dict) -> bool:
    """Latszik-e a `Piac` oszlop?

    Ha EGYETLEN paron sincs piac-eloszuro kivalasztva, az oszlop minden soron
    `—` lenne: helyet foglal, de nem mond semmit. A hivo `collapsed["market"]`-be
    teszi a dontest (a tabla szamolja ki az adatbol) — a sor es a fejlec
    UGYANAZT az erteket kapja, kulonben elcsusznanak az oszlopok."""
    return not (collapsed or {}).get("hide_market")


def is_collapsed(collapsed: dict, name: str = None) -> bool:
    """Össze van-e csukva ez a stratégia-blokk?

    A `collapsed["strategies"]` lehet:
      • `True`  — MINDEN stratégia összecsukva;
      • halmaz/lista — csak a felsoroltak (a fejlécen egyenként kapcsolhatók);
      • hamis érték — egyik sem.

    `name=None` → „össze van-e csukva bármelyik" (a szélesség-számításhoz)."""
    v = (collapsed or {}).get("strategies")
    if not v:
        return False
    if v is True:
        return True
    return True if name is None else name in v


def widths(fonts: dict, strategy_names=(), collapsed: dict = None) -> dict:
    """Az oszlop-szélességek MÉRVE, az aktuális betűkkel.

    Minden oszlop a LEGSZÉLESEBB tartalmához igazodik: a legrosszabb esetű adat
    ÉS a fejléc-felirat közül a nagyobbhoz.

    `strategy_names` + `collapsed`: összecsukott stratégia-blokknál a csoport-
    felirat (= a stratégia NEVE) csak a `stages` oszlop fölé fér ki, tehát annak
    a nevet is el kell bírnia. Kinyitva ez nem gond: ott a felirat a teljes blokk
    fölött áll. A hívóknak UGYANAZT a két értéket kell átadniuk, különben a
    fejléc és a sorok elcsúsznának."""
    small = fonts["small"]
    mode = pnl_mode(collapsed)
    out = {}
    for k, (fkey, txt) in _SAMPLE.items():
        # A P&L-cellák mintaszövege a megjelenítési módtól függ: „csak dollár"
        # módban az R-nek fenntartott hely FELESLEGES lenne (a felhasználó
        # panasza pont ez volt — „túl sok az üres rész").
        if k in _PNL_KEYS:
            txt = _PNL_SAMPLE[mode]
        # A fejlec-felirat a RENDEZES-JELZOT is viselheti (" ▲") — enelkul az
        # aktiv oszlop feliratanak vege levagodna.
        head = _HEADER_TEXT.get(k, "")
        w = max(fonts[fkey].measure(txt),
                small.measure(head + " ▲") if head else 0)
        out[k] = w + 2 * PAD
    # A Vezérlés a mintaszövegnél SZÉLESEBB: két külön vezérlő, saját margóval és
    # elválasztó hézaggal. Karakterből becsülve kilógna.
    # A második vezérlő MORPHOL (OPT → STOP → SOR), ezért a LEGSZÉLESEBB felirathoz
    # mérünk — különben a `STOP` megjelenésekor ugrálna a tábla, vagy levágódna.
    _opt_w = max(fonts["small"].measure(t) for t in OPT_LABELS.values())
    out["ctrl"] = max(out["ctrl"],
                      fonts["small"].measure("■") + 2 * CTRL_PADX + CTRL_GAP
                      + _opt_w + 2 * CTRL_PADX + 2 * PAD)
    if is_collapsed(collapsed) and strategy_names:
        # A felirat a KAPCSOLÓ-NYILAT is tartalmazza (`▸ wpr_sma`) — enélkül a
        # mérés 4 px-szel kevesebbet ad, és a név utolsó betűje levágódik.
        # Összecsukva a jelzés MELLETT a Vezérlés is ott marad (a blokkot akkor
        # is lehessen indítani/leállítani), tehát a felirat a KETTŐ fölött áll:
        # csak a hiányzó részt kell a jelzés-oszlophoz adni.
        longest = max((small.measure(f"▸ {n}") for n in strategy_names), default=0)
        span = out["stages"] + GAP + out["ctrl"]
        if longest + 2 * PAD > span:
            out["stages"] += longest + 2 * PAD - span
    return out

# A stádium-pöttyök színe (a stratégia belső állapota), és a keret (az engedély).
#
# A keret CSAK SZÍNNEL különbözteti meg a két esetet — ez tudatos döntés
# (2026-07-31), nem hiányosság: az eredeti terv szaggatott keretet szánt a
# kockázatcsökkentésnek, de a tkinter `highlightthickness` nem tud szaggatott
# lenni, ahhoz cellánként `Canvas` kellene. Sok sornál az fölösleges teher.
# → NE „javítsd meg" Canvas-szal. Ha később mégis kell egy szín-független jel,
#   a legolcsóbb út a keret VASTAGSÁGA (2 px vs 1 px), nem új widget.
_DOT = "●"
_FRAME = {"blocked": FG_RED, "reduced": FG_ORANGE}


# A sor által HASZNÁLT betű-szerepek (`dashboard.theme.FONT_ROLES` kulcsai).
# Csak ezeket nézzük a magasság/szélesség számításnál — a `theme.fonts()` a
# TELJES szerep-készletet adja (`title`, `tiny`, …), és a `title` nagyobb betűje
# fölöslegesen magasra tolná a sorokat.
ROLES = ("mono", "mono_bold", "small")


def row_height(fonts: dict) -> int:
    """A sor MAGASSÁGA a betűből származtatva.

    ⚠ A `pack_propagate(False)` MAGASSÁG NÉLKÜL 1 px-re lapítja a keretet — a
    tartalom eltűnik, és a hiba némán megy át (a méret-alapú levágás-detektálás
    is kihagyja). Ezért minden fix cella MINDKÉT méretet megkapja.

    Származtatva, nem konstans: a betűméret a felületről állítható
    (`dashboard.theme`), és egy bedrótozott 22 px nagyobb betűnél levágna."""
    return max(fonts[r].metrics("linespace") for r in ROLES) + 2 * PAD


def _cell(parent, text, width, fg=FG_WHITE, font=None, anchor="w", bg=None,
          height=None):
    """Egy fix szélességű cella. MINDEN cella ezen megy át, hogy a fejléc és a
    sor ugyanazt a szélességet kapja."""
    f = tk.Frame(parent, width=width, bg=bg or parent["bg"],
                 height=height or 1)
    f.pack(side="left", padx=(0, GAP))
    if height:                       # fix méret CSAK ha magasságot is adtunk
        f.pack_propagate(False)
    lbl = tk.Label(f, text=text, fg=fg, bg=bg or parent["bg"], font=font,
                   anchor=anchor, bd=0, padx=0, pady=0, highlightthickness=0)
    lbl.pack(fill="both", expand=True)
    return f, lbl


def _click_label(parent, text, width, fg, font, on_click=None, bg=None,
                 height=None):
    """Kattintható Label — GOMB HELYETT.

    A `tk.Button` magasabb a `Label`-nél (mérve ~6 px-szel, Windows), és ezt a
    `pady=0` sem tünteti el; a sorok ettől „ugrálnának". A kattinthatóságot
    ezért kötéssel adjuk, a magasság így betűre pontosan egyezik a cellákéval."""
    f, lbl = _cell(parent, text, width, fg=fg, font=font, anchor="center", bg=bg,
                   height=height)
    lbl.configure(cursor="hand2")
    if on_click is not None:
        lbl.bind("<Button-1>", lambda _e: on_click())
    return f, lbl


def _bind_click(widget, on_click):
    """Egy MÁR MEGLÉVŐ cella kattinthatóvá tétele (a `_click_label` mindig
    középre igazít — a `Symbol` és a `Napi P&L` viszont nem középre való).

    A kurzor is átvált: a `classic` nézetben ez jelzi, hogy a cella megnyit
    valamit, és a felhasználó ezt onnan már ismeri."""
    if on_click is None or widget is None:
        return
    widget.configure(cursor="hand2")
    widget.bind("<Button-1>", lambda _e: on_click())


def _fmt_price(v, digits):
    return "—" if v is None else f"{v:.{digits}f}"


def _money_r(money, r, mode="both"):
    """`+0.03$ +0.01R` — a P&L és az R egy cellában, a `mode` szerint szűrve.

    Az R ELHAGYHATÓ: ha nincs rögzített belépéskori kockázat, csak a pénz
    látszik (nem 0 R — az mást állítana, lásd `core/position_meta.py`). Ezért
    `r` módban a hiányzó kockázat `—`: az „ismeretlen" nem nulla."""
    if mode == "r":
        return "—" if r is None else f"{r:+.2f}R"
    if money is None:
        return "—"
    s = f"{money:+.2f}$"
    if mode == "money" or r is None:
        return s
    return f"{s} {r:+.2f}R"


class LiveRow:
    """Egy instrumentum sora. `left` / `mid` / `right` keretet ad ki a
    fix–görgethető–fix elrendezéshez."""

    def __init__(self, parent, data: dict, fonts: dict, collapsed: dict = None,
                 stripe: int = 0, on_close=None):
        """`parent` lehet EGY widget (a három rész egymás mellé kerül benne), vagy
        HÁROM widget `(bal, közép, jobb)`.

        A három szülő azért kell, mert a tábla fix–görgethető–fix elrendezésű: a
        bal és jobb oszlop rögzített, a közép külön vásznon görög. Ilyenkor a sor
        részei KÜLÖN oszlopokba épülnek, nem egymás mellé."""
        self.data = data
        self._f = fonts
        self._collapsed = collapsed or {}
        self._h = row_height(fonts)      # MINDEN fix cella ezt kapja (lásd row_height)
        self._w = widths(fonts, [x.get("name", "") for x in (data.get("strategies") or [])],
                         self._collapsed)   # MÉRT szélességek (lásd widths)
        bg = BG_ROW_EVEN if stripe % 2 == 0 else BG_ROW_ODD

        if isinstance(parent, (tuple, list)):
            self.frame = None
            self.left, self.mid, self.right = (
                tk.Frame(p, bg=bg, height=self._h) for p in parent)
            for f in (self.left, self.mid, self.right):
                f.pack(fill="x")
        else:
            self.frame = tk.Frame(parent, bg=bg, height=self._h)
            self.left = tk.Frame(self.frame, bg=bg, height=self._h)
            self.mid = tk.Frame(self.frame, bg=bg, height=self._h)
            self.right = tk.Frame(self.frame, bg=bg, height=self._h)
            for f in (self.left, self.mid, self.right):
                f.pack(side="left", fill="y")

        self._lbl = {}      # cella-kulcs -> Label (a HELYBEN frissiteshez)
        self._dots = {}     # kulcs -> [Label, …] (pottyok)
        self._box = {}      # strategia -> a jelzes-cella KERETE
        self._bg = bg
        self._pnl = pnl_mode(self._collapsed)
        self._build_instrument(bg)
        self._build_gates(bg)
        self._build_strategies(bg)
        self._build_total(bg, on_close)

    def _rc(self, key, parent, text, width, fg, font, **kw):
        """`_cell` + a Label FELJEGYZESE, hogy a `update()` helyben frissithesse.

        Miert kell: a tabla 3 masodpercenkent frissul. Teljes ujraepitessel a
        widgetek eldobasa/letrehozasa lathatoan villogna; helyben csak a
        megvaltozott szoveget/szint irjuk at."""
        _f, lbl = _cell(parent, text, width, fg, font, **kw)
        self._lbl[key] = lbl
        return lbl

    # ── bal: fix ────────────────────────────────────────────────────────
    def _build_instrument(self, bg):
        d = self.data
        dg = d.get("digits", 2)
        ch = d.get("change_pct")
        # Az instrumentum NEVE megnyitja az instrumentum-beállításokat — pontosan
        # úgy, ahogy a `classic` nézetben. A 2.0-ból ez kimaradt, és a beállítások
        # elérhetetlenné váltak (a `classic`-ban ez volt az EGYETLEN útjuk).
        _sym_lbl = self._rc("symbol", self.left, d.get("symbol", "—"),
                            self._w["symbol"], FG_WHITE, self._f["mono_bold"],
                            bg=bg, height=self._h)
        _bind_click(_sym_lbl, d.get("on_symbol"))
        self._rc("bid", self.left, _fmt_price(d.get("bid"), dg), self._w["bid"], FG_WHITE,
                 self._f["mono"], anchor="e", bg=bg, height=self._h)
        self._rc("ask", self.left, _fmt_price(d.get("ask"), dg), self._w["ask"], FG_WHITE,
                 self._f["mono"], anchor="e", bg=bg, height=self._h)
        self._rc("change", self.left, "—" if ch is None else f"{ch:+.2f}%", self._w["change"],
                 FG_GRAY if ch is None else (FG_GREEN if ch >= 0 else FG_RED),
                 self._f["mono"], anchor="e", bg=bg, height=self._h)

    # ── közép: összecsukható ────────────────────────────────────────────
    def _build_gates(self, bg):
        """Kapu-blokk + a mindig látszó K.Össz.

        Összecsukva CSAK a K.Össz. marad — az mondja meg, hogy van-e valami, ami
        beleszól. Hogy KIT érint, azt a stratégia jelzés-cellájának kerete mondja
        meg (a kapuk hatása stratégiánként állítható)."""
        g = self.data.get("gates") or {}
        if not self._collapsed.get("gates"):
            sp = g.get("spread") or {}
            # KÖZÉPRE igazítva: a cella két számot tart (`250/1312`), és balra
            # húzva a fejléc alatt „lógott". Kattintva a spread-küszöb
            # (végrehajtási) paraméterei nyílnak.
            _sp_lbl = self._rc("spread", self.mid, sp.get("text", "—"),
                               self._w["spread"],
                               FG_RED if sp.get("blocking") else FG_GREEN,
                               self._f["mono"], anchor="center", bg=bg,
                               height=self._h)
            _bind_click(_sp_lbl, g.get("on_spread"))
            self._align_cell(bg, g.get("align") or {})
            if show_market(self._collapsed):
                _mk = g.get("market") or {}
                _mk_lbl = self._rc("market", self.mid, _mk.get("text", "—"),
                                   self._w["market"], FG_GRAY, self._f["small"],
                                   bg=bg, height=self._h)
                # Kattintva a PIAC-kapu ablaka nyílik (osztályozó + mely
                # besorolások kedvezőtlenek) — eddig ez a cella néma volt, és a
                # beállítás csak az instrumentum-ablakból volt elérhető.
                _bind_click(_mk_lbl, _mk.get("on_click"))
        badge = g.get("badge", "✓")
        self._rc("badge", self.mid, badge, self._w["badge"],
                 FG_RED if badge != "✓" else FG_GREEN, self._f["mono"],
                 anchor="center", bg=bg, height=self._h)

    def _align_cell(self, bg, al: dict):
        """Az idősík-irányok pöttyei — KERET NÉLKÜL.

        A keret a stratégia jelzés-cellájának van fenntartva: ott az „engedélyt"
        jelenti. Itt csak a piaci tény látszik (együtt állnak-e az idősíkok), és
        ez instrumentum-tulajdonság.

        Kattintva a TF-együttállás beállításai nyílnak (mint a `classic`-ban). A
        kötés a KERETRE és minden pöttyre megy: a pöttyök takarják a keretet,
        tehát csak a kereten kötve a kattintás nagy része elveszne."""
        on_click = al.get("on_click")
        f = tk.Frame(self.mid, width=self._w["align"], bg=bg, height=self._h)
        f.pack(side="left", padx=(0, GAP))
        f.pack_propagate(False)
        inner = tk.Frame(f, bg=bg, height=self._h)
        inner.pack(expand=True)
        _bind_click(f, on_click)
        _bind_click(inner, on_click)
        signs = al.get("signs") or []
        if not signs:
            _empty = tk.Label(inner, text="—", fg=FG_GRAY_DIM, bg=bg,
                              font=self._f["mono"], bd=0, padx=0, pady=0,
                              highlightthickness=0)
            _empty.pack()
            _bind_click(_empty, on_click)
            return
        self._dots["align"] = []
        for s in signs:
            l = tk.Label(inner, text=_DOT, bg=bg, font=self._f["mono"],
                         fg=FG_GREEN if s > 0 else FG_RED if s < 0 else FG_GRAY_DIM,
                         bd=0, padx=0, pady=0, highlightthickness=0)
            l.pack(side="left")
            _bind_click(l, on_click)
            self._dots["align"].append(l)

    def _build_strategies(self, bg):
        for st in self.data.get("strategies") or []:
            self._build_one_strategy(bg, st)

    def _build_one_strategy(self, bg, st: dict):
        """Egy stratégia blokkja.

        Összecsukva a jelzés-cella MELLETT a Vezérlés is megmarad. Az eredeti
        terv csak a jelzést hagyta meg — élesben viszont kiderült, hogy így egy
        összecsukott blokkot nem lehet elindítani/leállítani, tehát az
        összecsukás nem „tömörít", hanem HASZNÁLHATATLANNÁ tesz. A jelzés a
        keretével továbbra is hordozza a kapu-érintettséget, tehát a tömör nézet
        most sem veszít információt — csak a kezelhetőséget nyeri vissza."""
        collapsed = is_collapsed(self._collapsed, st.get("name"))
        pos = st.get("position") or {}
        day = st.get("daily") or {}
        n = st.get("name", "")
        self._stages_cell(bg, st)
        if not collapsed:
            self._rc(f"{n}|position", self.mid,
                     _money_r(pos.get("money"), pos.get("r"), self._pnl),
                     self._w["position"], FG_WHITE, self._f["mono"], anchor="e",
                     bg=bg, height=self._h)
            self._rc(f"{n}|daily", self.mid,
                     _money_r(day.get("money"), day.get("r"), self._pnl),
                     self._w["daily"], _pnl_color(day.get("money")), self._f["mono"],
                     anchor="e", bg=bg, height=self._h)
            q = st.get("quality") or "—"
            self._rc(f"{n}|quality", self.mid, q, self._w["quality"], _quality_color(q),
                     self._f["small"], anchor="center", bg=bg, height=self._h)
        self._ctrl_cell(bg, st, n)
        if not collapsed:
            self._rc(f"{n}|opt", self.mid, st.get("opt") or "—", self._w["opt"],
                     FG_GRAY, self._f["small"], anchor="center", bg=bg,
                     height=self._h)

    def _ctrl_cell(self, bg, st: dict, n: str):
        """Vezérlés: Play/Stop + OPT — kattintható Labelek (NEM Button, lásd a
        modul-doksit).

        Az OPT HALVÁNY, ha a stratégia épp kereskedik: a futás végén felülíródna
        a paraméterfájlja, tehát ilyenkor tiltott művelet. A kötés viszont
        MEGMARAD — a hívó így ki tudja írni az OKOT az állapotsorba. Egy néma,
        nem reagáló gomb rosszabb, mint egy halvány, ami megmondja, miért nem."""
        ctrl = tk.Frame(self.mid, width=self._w["ctrl"], bg=bg, height=self._h)
        ctrl.pack(side="left", padx=(0, GAP))
        ctrl.pack_propagate(False)
        inner = tk.Frame(ctrl, bg=bg, height=self._h)
        inner.pack(expand=True)
        _run_lbl, _run_fg = _run_text(st)
        _opt_lbl, _opt_fg = _opt_text(st)
        run_on = st.get("enabled", True)
        opt_on = st.get("opt_enabled", True) or st.get("opt_state")
        for key, txt, fg, cb in (("run", _run_lbl, _run_fg, st.get("on_toggle")),
                                 ("opt", _opt_lbl, _opt_fg, st.get("on_opt"))):
            # A ket vezerlo KULON dobozban, elvalaszto hezaggal: elesben
            # "osszemosodtak" (padx=3 nem eleg, a Play/Stop es az OPT egy
            # foltnak latszott). A Play/Stop szeles kattinto-feluletet kap.
            l = tk.Label(inner, text=txt, fg=fg, bg=bg, font=self._f["small"],
                         cursor="hand2" if (opt_on if key == "opt" else run_on) else "",
                         bd=0, padx=CTRL_PADX, pady=0, highlightthickness=0)
            l.pack(side="left", padx=(0, CTRL_GAP) if key == "run" else 0)
            self._lbl[f"{n}|ctrl_{key}"] = l
            if cb:
                l.bind("<Button-1>", lambda _e, c=cb: c())

    def _stages_cell(self, bg, st: dict):
        """A jelzés-cella: stádium-pöttyök + KERET.

        A pöttyök a stratégia belső állapotát mondják (SMA irány · M15 jel · M1
        belépő), a keret az engedélyt: tömör piros = blokkolva, szaggatott sárga =
        kockázatcsökkentés, NINCS keret = semmi nem szól bele.

        A „nincs keret" a leggyakoribb eset, ezért néma — a jelölés csak akkor
        szóljon, ha tényleg történik valami."""
        frame_st = st.get("frame") or ""
        color = _FRAME.get(frame_st)
        on_click = st.get("on_stages")
        holder = tk.Frame(self.mid, width=self._w["stages"], bg=bg, height=self._h)
        holder.pack(side="left", padx=(0, GAP))
        holder.pack_propagate(False)
        # A keret egy 1 px-es szegélyű belső keret. Egységes belső margó, hogy a
        # keretes és keret nélküli cella pöttyei EGY VONALBAN legyenek.
        box = tk.Frame(holder, bg=bg, highlightthickness=1,
                       highlightbackground=color or bg, highlightcolor=color or bg)
        box.pack(expand=True)
        dots = tk.Frame(box, bg=bg, height=self._h)
        dots.pack(padx=2)
        nm = st.get("name", "")
        self._box[nm] = box
        self._dots[nm] = []
        # Kattintva ENNEK a stratégiának a paraméter-ablaka nyílik (mint a
        # `classic` körökre kattintva). A kötés minden szintre kell: a pöttyök
        # eltakarják a keretet, a keret a holdert — csak a legkülsőn kötve a
        # kattintások nagy része nem érne célba.
        for w in (holder, box, dots):
            _bind_click(w, on_click)
        for s in (st.get("stages") or []):
            l = tk.Label(dots, text=_DOT, bg=bg, font=self._f["mono"],
                         fg=_stage_color(s), bd=0, padx=0, pady=0,
                         highlightthickness=0)
            l.pack(side="left")
            _bind_click(l, on_click)
            self._dots[nm].append(l)

    # ── jobb: fix ───────────────────────────────────────────────────────
    def _build_total(self, bg, on_close):
        t = self.data.get("total") or {}
        pos, day = t.get("position") or {}, t.get("daily") or {}
        self._rc("total_pos", self.right,
                 _money_r(pos.get("money"), pos.get("r"), self._pnl),
                 self._w["total_pos"], FG_WHITE, self._f["mono_bold"], anchor="e",
                 bg=bg, height=self._h)
        self._rc("total_daily", self.right,
                 _money_r(day.get("money"), day.get("r"), self._pnl),
                 self._w["total_daily"], _pnl_color(day.get("money")),
                 self._f["mono_bold"], anchor="e", bg=bg, height=self._h)
        # Az X az instrumentum TÖRLÉSE — a sor legvégén, megerősítéssel (a hívó
        # dolga). Szándékosan nincs a stratégia vezérlői közt: az más művelet.
        _click_label(self.right, "✕", self._w["close"], FG_GRAY_DIM, self._f["small"],
                     on_click=on_close, bg=bg, height=self._h)


    # ── HELYBEN frissítés ────────────────────────────────────────────────
    def structure_key(self) -> tuple:
        """A sor SZERKEZETÉT azonosító kulcs: a stratégiák neve+sorrendje, a
        stádiumok száma és az IDŐSÍK-PÖTTYÖK SZÁMA. Ha ez változik, a sort ÚJRA
        KELL ÉPÍTENI (más cellák kellenek); ha nem, elég a helyben frissítés.

        MIÉRT VAN BENNE AZ „EGYÜTT" PÖTTYEINEK SZÁMA (v2.1.2). A sor INDULÁSKOR
        épül fel, amikor a TF-együttállás még ÜRES (a piaci adat-loop 5 mp-et vár
        az első lekérés előtt). Az `_align_cell` ilyenkor egy `—` címkét rajzol és
        KILÉP — a pötty-listát (`_dots["align"]`) meg sem hozza létre. Az `update()`
        viszont csak MEGLÉVŐ pöttyöket színez át, tehát amikor megjött az adat, a
        cella `—` maradt… és mivel a kulcs nem vette észre a 0 → 3 változást, a
        tábla sosem építette újra. Az „Együtt" oszlop így az EGÉSZ munkamenetre
        beragadt (élesben bejelentve: „az együttállás nem működik").

        Ugyanaz a fajta hiba, mint a stádium-pöttyöknél — azért van ott a
        `len(stages)` is. A tanulság: MINDEN olyan cella, ami VÁLTOZÓ SZÁMÚ
        widgetből áll, tartozzon bele ebbe a kulcsba."""
        return (tuple((s.get("name", ""), len(s.get("stages") or []))
                      for s in (self.data.get("strategies") or [])),
                len(((self.data.get("gates") or {}).get("align") or {}).get("signs") or []))

    def _set(self, key, text, fg):
        """Egy cella átírása — CSAK ha tényleg változott.

        A fölösleges `config()` hívás nem csak lassú: a tkinter újrarajzolja a
        widgetet, ami 3 másodpercenként, tucatnyi soron látható villogás."""
        lbl = self._lbl.get(key)
        if lbl is None:
            return
        if lbl.cget("text") != text:
            lbl.config(text=text)
        if fg is not None and lbl.cget("fg") != fg:
            lbl.config(fg=fg)

    def update(self, data: dict) -> bool:
        """Az adat frissítése HELYBEN. Visszaad: sikerült-e.

        `False`, ha a SZERKEZET változott (más stratégiák/stádiumok) — ilyenkor a
        hívó (a tábla) újraépít. Így a gyakori eset olcsó, a ritka eset helyes."""
        new_key = (tuple((s.get("name", ""), len(s.get("stages") or []))
                         for s in (data.get("strategies") or [])),
                   len(((data.get("gates") or {}).get("align") or {}).get("signs") or []))
        if new_key != self.structure_key():
            return False
        self.data = data
        dg = data.get("digits", 2)
        ch = data.get("change_pct")
        self._set("symbol", data.get("symbol", "—"), None)
        self._set("bid", _fmt_price(data.get("bid"), dg), None)
        self._set("ask", _fmt_price(data.get("ask"), dg), None)
        self._set("change", "—" if ch is None else f"{ch:+.2f}%",
                  FG_GRAY if ch is None else (FG_GREEN if ch >= 0 else FG_RED))

        g = data.get("gates") or {}
        sp = g.get("spread") or {}
        self._set("spread", sp.get("text", "—"),
                  FG_RED if sp.get("blocking") else FG_GREEN)
        self._set("market", (g.get("market") or {}).get("text", "—"), None)
        badge = g.get("badge", "✓")
        self._set("badge", badge, FG_RED if badge != "✓" else FG_GREEN)

        for i, s in enumerate((g.get("align") or {}).get("signs") or []):
            dots = self._dots.get("align") or []
            if i < len(dots):
                c = FG_GREEN if s > 0 else FG_RED if s < 0 else FG_GRAY_DIM
                if dots[i].cget("fg") != c:
                    dots[i].config(fg=c)

        for st in data.get("strategies") or []:
            n = st.get("name", "")
            pos, day = st.get("position") or {}, st.get("daily") or {}
            self._set(f"{n}|position",
                      _money_r(pos.get("money"), pos.get("r"), self._pnl), None)
            self._set(f"{n}|daily",
                      _money_r(day.get("money"), day.get("r"), self._pnl),
                      _pnl_color(day.get("money")))
            q = st.get("quality") or "—"
            self._set(f"{n}|quality", q, _quality_color(q))
            self._set(f"{n}|opt", st.get("opt") or "—", None)
            # A Play/Stop MORPHOL: ▶ / ■ / halvány `–` (nincs engedélyezve a
            # páron). Az utóbbinál a kurzort is levesszük, különben kattinthatónak
            # látszana — a KÖTÉS viszont marad, hogy kiírhassuk az okot.
            _run_w = self._lbl.get(f"{n}|ctrl_run")
            if _run_w is not None:
                _rtxt, _rfg = _run_text(st)
                self._set(f"{n}|ctrl_run", _rtxt, _rfg)
                _rcur = "hand2" if st.get("enabled", True) else ""
                if _run_w.cget("cursor") != _rcur:
                    _run_w.config(cursor=_rcur)
            # Az OPT vezérlő MORPHOL: OPT → STOP (futó optimalizálás leállítása) →
            # SOR (sorból kivétel). Elhalványul, ha a stratégia kereskedni kezd —
            # a Play/Stop UGYANEBBEN a frissítésben vált, tehát a kettő sosem
            # mond mást.
            _opt_w = self._lbl.get(f"{n}|ctrl_opt")
            if _opt_w is not None:
                _txt, _fg = _opt_text(st)
                self._set(f"{n}|ctrl_opt", _txt, _fg)
                _on = bool(st.get("opt_enabled", True) or st.get("opt_state"))
                _cur = "hand2" if _on else ""
                if _opt_w.cget("cursor") != _cur:
                    _opt_w.config(cursor=_cur)
            for i, sc in enumerate(st.get("stages") or []):
                dots = self._dots.get(n) or []
                if i < len(dots) and dots[i].cget("fg") != _stage_color(sc):
                    dots[i].config(fg=_stage_color(sc))
            box = self._box.get(n)
            if box is not None:
                c = _FRAME.get(st.get("frame") or "") or self._bg
                if box.cget("highlightbackground") != c:
                    box.config(highlightbackground=c, highlightcolor=c)

        t = data.get("total") or {}
        tp, td = t.get("position") or {}, t.get("daily") or {}
        self._set("total_pos", _money_r(tp.get("money"), tp.get("r"), self._pnl), None)
        self._set("total_daily", _money_r(td.get("money"), td.get("r"), self._pnl),
                  _pnl_color(td.get("money")))
        return True


def _stage_color(name):
    """A stádium-pötty színe SZEMANTIKUS SZÍN-NÉVBŐL (`green` / `red` / `muted`…).

    Ez pontosan az, amit a stratégia előállít (`Cell.color`, lásd `strategy/base.py`)
    és amit a motor a `ds.strategy_cells`-be ír — így a 2.0 sor és a `classic`
    tábla körei UGYANABBÓL dolgoznak, nem tudnak szétcsúszni. Ismeretlen név →
    halvány (a `theme.color` alapértelmezése helyett tudatosan tompa)."""
    from dashboard import theme as _t
    return _t.SEMANTIC.get(name, FG_GRAY_DIM)


# Az OPT vezérlő FELIRATA az optimalizálás állapotától függ — a gomb ugyanaz a
# morph, mint a Play/Stop: ami épp fut, azt a saját gombja állítja le.
#   ""        → OPT   (kék)     — indítható
#   "running" → STOP  (piros)   — kattintva leállítja a futó optimalizálást
#   "queued"  → SOR   (narancs) — kattintva kiveszi a sorból
OPT_LABELS = {"": "OPT", "running": "STOP", "queued": "SOR"}
_OPT_COLORS = {"": FG_BLUE, "running": FG_RED, "queued": FG_ORANGE}


def _run_text(st: dict) -> tuple:
    """A Play/Stop vezérlő (felirat, szín).

    HALVÁNY `–`, ha a stratégia nincs ENGEDÉLYEZVE ezen a páron
    (`pairs.<sym>.strategies`): a motor ilyenkor sosem futtatná, tehát a `▶`
    hazugság volna. A blokk nem tűnik el (az oszlopoknak egy vonalban kell
    állniuk), és a KÖTÉS is megmarad — ugyanaz a recept, mint a halvány OPT-nál:
    a hívó így ki tudja írni az OKOT az állapotsorba. Egy néma, nem reagáló gomb
    rosszabb, mint egy halvány, ami megmondja, miért nem."""
    if not st.get("enabled", True):
        return "–", FG_GRAY_DIM
    live = st.get("live")
    return ("■" if live else "▶"), (FG_RED if live else FG_GREEN)


def _opt_text(st: dict) -> tuple:
    """Az OPT vezérlő (felirat, szín) az állapot szerint.

    HALVÁNY (és OPT feliratú), ha a stratégia kereskedik: akkor nem
    optimalizálható (a futás végén felülíródna a paraméterfájlja). Egy FUTÓ
    optimalizálás viszont mindig leállítható — azt nem halványítjuk."""
    state = str(st.get("opt_state") or "")
    if state in ("running", "queued"):
        return OPT_LABELS[state], _OPT_COLORS[state]
    return OPT_LABELS[""], (FG_BLUE if st.get("opt_enabled", True) else FG_GRAY_DIM)


def _pnl_color(v):
    if v is None:
        return FG_GRAY
    return FG_GREEN if v > 0 else FG_RED if v < 0 else FG_GRAY


def _quality_color(q):
    return {"Jó": FG_GREEN, "Közepes": FG_ORANGE,
            "Gyenge": FG_RED, "Rossz": FG_RED}.get(q, FG_GRAY)


# ---------------------------------------------------------------------------
# Fejléc — UGYANAZOKKAL a szélességekkel és betűvel
# ---------------------------------------------------------------------------

def _sorted_head(parent, key, text, width, f, h, on_sort, sort_key, sort_dir):
    """Egy KATTINTHATO oszlopfejlec + rendezes-jelzo.

    A jelzo (`▲`/`▼`) csak az AKTIV oszlopon jelenik meg. A szelesseget a
    `widths()` mar a jelzovel egyutt merte, tehat nem csordul tul."""
    mark = ""
    if on_sort is not None and sort_key == key:
        mark = " ▼" if sort_dir < 0 else " ▲"
    if on_sort is None:
        _cell(parent, text, width, FG_GRAY_DIM, f, bg=BG_HEADER, height=h)
        return
    _click_label(parent, text + mark, width,
                 FG_WHITE if sort_key == key else FG_GRAY_DIM, f,
                 on_click=lambda k=key: on_sort(k), bg=BG_HEADER, height=h)


def build_header(parent, fonts: dict, strategies: list, collapsed: dict = None,
                 on_toggle=None, on_sort=None, sort_key=None, sort_dir=1):
    """A sorokkal EGYEZŐ fejléc.

    A fejlécnek ugyanazt a betűt és ugyanazokat a szélességeket kell használnia,
    mint a celláknak — különben az oszlopok nem illeszkednek (ez az 1. körben
    ténylegesen előfordult).

    `parent` itt is lehet EGY widget vagy HÁROM `(bal, közép, jobb)` — utóbbi a
    fix–görgethető–fix táblához.

    `on_toggle(kulcs)`: az összecsukó kapcsoló. A kulcs `"gates"` vagy a stratégia
    NEVE. A csoport-feliratok kattinthatók, és `▾`/`▸` mutatja az állapotot — így
    a kapcsoló ott van, ahol a hatása látszik, nem külön eszköztárban."""
    collapsed = collapsed or {}
    f = fonts["small"]
    h = row_height(fonts)            # a sorokkal AZONOS magasság
    w = widths(fonts, strategies, collapsed)   # a sorokkal AZONOS szélességek

    def group(parent_, keys, text, fg=FG_GRAY_DIM, key=None, is_coll=False):
        """Csoport-felirat, ami a hozzá tartozó oszlopok FÖLÖTT áll végig.
        A szélessége a tagoszlopok összege + a köztük lévő hézagok — így a
        két fejlécsor és a cellák egy vonalban maradnak."""
        span = sum(w[k] for k in keys) + GAP * (len(keys) - 1)
        if key is None or on_toggle is None:
            _cell(parent_, text, span, fg, f, anchor="center", bg=BG_HEADER,
                  height=h)
            return
        _click_label(parent_, f"{'▸' if is_coll else '▾'} {text}", span, fg, f,
                     on_click=lambda k=key: on_toggle(k), bg=BG_HEADER, height=h)

    if isinstance(parent, (tuple, list)):
        head = None
        tl, tm, tr = (tk.Frame(p, bg=BG_HEADER, height=h) for p in parent)
        bl, bm, br = (tk.Frame(p, bg=BG_HEADER, height=h) for p in parent)
        for x in (tl, tm, tr, bl, bm, br):
            x.pack(fill="x")
    else:
        head = tk.Frame(parent, bg=BG_HEADER)
        top = tk.Frame(head, bg=BG_HEADER, height=h)
        top.pack(fill="x")
        tl, tm, tr = (tk.Frame(top, bg=BG_HEADER, height=h) for _ in range(3))
        bot = tk.Frame(head, bg=BG_HEADER, height=h)
        bot.pack(fill="x")
        bl, bm, br = (tk.Frame(bot, bg=BG_HEADER, height=h) for _ in range(3))
        for x in (tl, tm, tr, bl, bm, br):
            x.pack(side="left", fill="y")

    # ── 1. sor: csoportok (a terv „Instrumentum / Kapuk / Stratégiák" sávja) ──
    group(tl, ("symbol", "bid", "ask", "change"), "Instrumentum")
    if not collapsed.get("gates"):
        _gk = ("spread", "align", "market") if show_market(collapsed)             else ("spread", "align")
        group(tm, _gk, "Kapuk", key="gates")
    _cell(tm, "", w["badge"], FG_GRAY_DIM, f, bg=BG_HEADER, height=h)
    for name in strategies:
        coll = is_collapsed(collapsed, name)
        # Összecsukva a jelzés MELLETT a Vezérlés is marad (indítani/leállítani
        # összecsukva is lehessen), tehát a csoport-felirat KÉT oszlop fölött áll.
        keys = ("stages", "ctrl") if coll else ("stages", "position", "daily",
                                                "quality", "ctrl", "opt")
        group(tm, keys, name, FG_BLUE, key=name, is_coll=coll)
    group(tr, ("total_pos", "total_daily"), "Összesítő")
    _cell(tr, "", w["close"], FG_GRAY_DIM, f, bg=BG_HEADER, height=h)

    # ── 2. sor: oszlopnevek ──
    for key, txt in (("symbol", "Symbol"), ("bid", "BID"), ("ask", "ASK"),
                     ("change", "Vált.%")):
        _sorted_head(bl, key, txt, w[key], f, h, on_sort, sort_key, sort_dir)
    if not collapsed.get("gates"):
        # A SORREND kötött: Spread · Együtt · Piac — pontosan úgy, ahogy a sorok
        # cellái. (Egy korábbi változat itt átrendezte őket, és a feliratok rossz
        # oszlopok fölé kerültek; a `test_live_table` oszlop-igazítási állítása
        # fogta meg.) Az „Együtt" a pöttyök oszlopa: nincs értelmes rendezési
        # értéke, ezért az egyetlen nem kattintható fejléc a blokkban.
        _sorted_head(bm, "spread", "Spread", w["spread"], f, h, on_sort,
                     sort_key, sort_dir)
        _cell(bm, "Együtt", w["align"], FG_GRAY_DIM, f, bg=BG_HEADER, height=h)
        if show_market(collapsed):
            _sorted_head(bm, "market", "Piac", w["market"], f, h, on_sort,
                         sort_key, sort_dir)
    # Összecsukott kapuknál a K.Össz. fejléce lesz a kapcsoló (különben nem
    # lehetne visszanyitni — a „Kapuk" felirat ilyenkor nem létezik).
    if collapsed.get("gates") and on_toggle is not None:
        _click_label(bm, "▸ K.Ö.", w["badge"], FG_GRAY_DIM, f,
                     on_click=lambda: on_toggle("gates"), bg=BG_HEADER, height=h)
    else:
        _sorted_head(bm, "badge", "K.Össz.", w["badge"], f, h, on_sort,
                     sort_key, sort_dir)
    for name in strategies:
        # A strategia-oszlopok kulcsa "<nev>|<mezo>": ugyanaz az oszlop
        # strategiankent kulon letezik, tehat a rendezes is arra a blokkra hat,
        # amelyikben kattintottal.
        _sorted_head(bm, f"{name}|stages", "jelzés", w["stages"], f, h, on_sort,
                     sort_key, sort_dir)
        if is_collapsed(collapsed, name):
            # Osszecsukva is van Vezerles-oszlop a sorokban — a fejlecnek KOVETNIE
            # kell, kulonben minden tovabbi oszlop elcsuszik.
            _cell(bm, "Vezérlés", w["ctrl"], FG_GRAY_DIM, f, bg=BG_HEADER, height=h)
            continue
        for key, txt in (("position", "Pozíció"), ("daily", "Napi P&L"),
                         ("quality", "Min.")):
            _sorted_head(bm, f"{name}|{key}", txt, w[key], f, h, on_sort,
                         sort_key, sort_dir)
        _cell(bm, "Vezérlés", w["ctrl"], FG_GRAY_DIM, f, bg=BG_HEADER, height=h)
        _sorted_head(bm, f"{name}|opt", "Opt", w["opt"], f, h, on_sort,
                     sort_key, sort_dir)
    _sorted_head(br, "total_pos", "Pozíció", w["total_pos"], f, h, on_sort,
                 sort_key, sort_dir)
    _sorted_head(br, "total_daily", "Napi P&L", w["total_daily"], f, h, on_sort,
                 sort_key, sort_dir)
    _cell(br, "", w["close"], FG_GRAY_DIM, f, bg=BG_HEADER, height=h)
    return head


# ---------------------------------------------------------------------------
# Bemutató adat — a tervben szereplő Ger 40 sor
# ---------------------------------------------------------------------------

def demo_row() -> dict:
    """A felhasználó .ods-tervében szereplő sor, adatként. Ez a modul BEMENETI
    SZERZŐDÉSE is: a live bekötés majd ilyen dictet állít elő."""
    return {
        "symbol": "Ger 40", "bid": 25443.91, "ask": 25446.00,
        "change_pct": 0.03, "digits": 2,
        "gates": {
            "spread": {"text": "250/1312", "blocking": False},
            "align": {"signs": [1, -1, -1]},
            "market": {"text": "Sz.Bika"},
            "badge": "⛔1",
        },
        "strategies": [
            # A KERESKEDŐ stratégiánál az OPT halvány (a futás felülírná a
            # paraméterfájlt) — a bemutatóban is így látszik.
            {"name": "wpr_sma", "stages": ["green", "green", "muted"], "frame": "blocked",
             "position": {"money": 1.00, "r": 1.0},
             "daily": {"money": 0.03, "r": 0.01},
             "quality": "Jó", "live": True, "opt": "06/29", "opt_enabled": False,
             "enabled": True},
            {"name": "ml_ai", "stages": ["red", "muted"], "frame": "",
             "position": {"money": 1.00, "r": 1.0},
             "daily": {"money": 0.03, "r": 0.01},
             "quality": "Jó", "live": False, "opt": "85%", "opt_enabled": True,
             "enabled": True},
        ],
        "total": {"position": {"money": 2.00, "r": 2.0},
                  "daily": {"money": 0.06, "r": 0.02}},
    }


def build_demo(parent, collapsed: dict = None, rows: int = 3):
    """Fejléc + néhány sor kitalált adattal — a `tools/ui_preview.py`-hoz."""
    # A TÉMA megosztott betű-objektumai — nem sajátok. Így a bemutató pontosan
    # azt mutatja, amit a felhasználó látni fog a saját beállításaival, és a
    # betűméret-változás (theme.apply_fonts) élőben átüt rajta is.
    #
    # A gyorsítótár ürítése CSAK a bemutatóhoz kell: a `theme.fonts()` szingleton
    # az ELSŐ Tk-gyökérhez köti a Font-objektumokat, a képernyőkép-eszköz viszont
    # eldobható ablakokban rendereli. Az alkalmazásban egy gyökér van, ott ez
    # sosem áll elő.
    from dashboard import theme as _t
    _t._FONTS.clear()
    fonts = _t.fonts()
    holder = tk.Frame(parent, bg=BG)
    holder.pack(fill="both", expand=True)
    names = [s["name"] for s in demo_row()["strategies"]]
    build_header(holder, fonts, names, collapsed).pack(fill="x", pady=(0, 2))
    syms = ("Ger 40", "UsaTec", "EURUSD")
    for i in range(rows):
        d = demo_row()
        d["symbol"] = syms[i % len(syms)]
        if i == 1:                      # egy sor, ahol semmi nem blokkol
            d["gates"]["badge"] = "✓"
            d["gates"]["spread"]["text"] = "180/1312"
            d["strategies"][0]["frame"] = ""
            # + egy stratégia, ami NINCS engedélyezve ezen a páron: a blokk marad
            # (az oszlopok egy vonalban), a Play viszont halvány `–` és tétlen.
            # A képernyőkép-ellenőrzés így ezt az állapotot is lefedi.
            d["strategies"][1]["enabled"] = False
            d["strategies"][1]["live"] = False
        if i == 2:
            # Kockázatcsökkentés: a K.Össz. PIPA marad, mert a `reduce` hatású
            # kapu NEM akadályozza a kötést — csak kisebbre veszi. (Az első
            # változatban itt `⛔1` állt narancs kerettel: ellentmondás, amit a
            # képernyőkép mutatott meg.)
            d["gates"]["badge"] = "✓"
            d["gates"]["spread"]["text"] = "210/1312"
            d["strategies"][0]["frame"] = "reduced"
            d["strategies"][1]["daily"] = {"money": -4.20, "r": -0.28}
        LiveRow(holder, d, fonts, collapsed, stripe=i).frame.pack(fill="x", pady=1)
    return holder

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

# Oszlop-szélességek: a LEGROSSZABB ESETŰ szöveg MÉRT szélességéből.
#
# Szándékosan nem karakterszámból és nem bedrótozott pixelből:
#   • a karakter-alapú becslés túlcsordul, mert a `●`, `⛔`, `✓` szélesebb a
#     számjegyeknél — az 1. körben pont ettől vágódott le némán a tartalom;
#   • a fix pixel a felületről állítható betűmérettel csúszna el.
# A mintaszövegek a ténylegesen előforduló leghosszabb alakot képviselik.
_SAMPLE = {
    "symbol": ("mono_b", "XXXXXXXX"), "bid": ("mono", "99999.99"),
    "ask": ("mono", "99999.99"), "change": ("mono", "+99.99%"),
    "spread": ("mono", "9999/9999"), "align": ("mono", "●●●●"),
    "market": ("small", "Sz.Bika"), "badge": ("mono", "⛔9"),
    "stages": ("mono", "●●●●"), "quality": ("small", "Közepes"),
    "ctrl": ("small", "■ OPT"), "opt": ("small", "99/99"),
    "position": ("mono", "+9999.99$ +99.99R"),
    "daily": ("mono", "+9999.99$ +99.99R"),
    "total_pos": ("mono_b", "+9999.99$ +99.99R"),
    "total_daily": ("mono_b", "+9999.99$ +99.99R"),
    "close": ("small", "✕"),
}


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
    out = {}
    for k, (fkey, txt) in _SAMPLE.items():
        w = max(fonts[fkey].measure(txt), small.measure(_HEADER_TEXT.get(k, "")))
        out[k] = w + 2 * PAD
    if (collapsed or {}).get("strategies") and strategy_names:
        longest = max((small.measure(n) for n in strategy_names), default=0)
        out["stages"] = max(out["stages"], longest + 2 * PAD)
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


def row_height(fonts: dict) -> int:
    """A sor MAGASSÁGA a betűből származtatva.

    ⚠ A `pack_propagate(False)` MAGASSÁG NÉLKÜL 1 px-re lapítja a keretet — a
    tartalom eltűnik, és a hiba némán megy át (a méret-alapú levágás-detektálás
    is kihagyja). Ezért minden fix cella MINDKÉT méretet megkapja.

    Származtatva, nem konstans: a betűméret a felületről állítható
    (`dashboard.theme`), és egy bedrótozott 22 px nagyobb betűnél levágna."""
    return max(f.metrics("linespace") for f in fonts.values()) + 2 * PAD


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


def _fmt_price(v, digits):
    return "—" if v is None else f"{v:.{digits}f}"


def _money_r(money, r):
    """`+0.03$ +0.01R` — a P&L és az R egy cellában. Az R ELHAGYHATÓ: ha nincs
    rögzített belépéskori kockázat, csak a pénz látszik (nem 0 R — az mást
    állítana, lásd `core/position_meta.py`)."""
    if money is None:
        return "—"
    s = f"{money:+.2f}$"
    return s if r is None else f"{s} {r:+.2f}R"


class LiveRow:
    """Egy instrumentum sora. `left` / `mid` / `right` keretet ad ki a
    fix–görgethető–fix elrendezéshez."""

    def __init__(self, parent, data: dict, fonts: dict, collapsed: dict = None,
                 stripe: int = 0, on_close=None):
        self.data = data
        self._f = fonts
        self._collapsed = collapsed or {}
        self._h = row_height(fonts)      # MINDEN fix cella ezt kapja (lásd row_height)
        self._w = widths(fonts, [x.get("name", "") for x in (data.get("strategies") or [])],
                         self._collapsed)   # MÉRT szélességek (lásd widths)
        bg = BG_ROW_EVEN if stripe % 2 == 0 else BG_ROW_ODD

        self.frame = tk.Frame(parent, bg=bg, height=self._h)
        self.left = tk.Frame(self.frame, bg=bg, height=self._h)
        self.mid = tk.Frame(self.frame, bg=bg, height=self._h)
        self.right = tk.Frame(self.frame, bg=bg, height=self._h)
        for f in (self.left, self.mid, self.right):
            f.pack(side="left", fill="y")

        self._build_instrument(bg)
        self._build_gates(bg)
        self._build_strategies(bg)
        self._build_total(bg, on_close)

    # ── bal: fix ────────────────────────────────────────────────────────
    def _build_instrument(self, bg):
        d = self.data
        dg = d.get("digits", 2)
        ch = d.get("change_pct")
        _cell(self.left, d.get("symbol", "—"), self._w["symbol"], FG_WHITE,
              self._f["mono_b"], bg=bg, height=self._h)
        _cell(self.left, _fmt_price(d.get("bid"), dg), self._w["bid"], FG_WHITE,
              self._f["mono"], anchor="e", bg=bg, height=self._h)
        _cell(self.left, _fmt_price(d.get("ask"), dg), self._w["ask"], FG_WHITE,
              self._f["mono"], anchor="e", bg=bg, height=self._h)
        _cell(self.left, "—" if ch is None else f"{ch:+.2f}%", self._w["change"],
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
            _cell(self.mid, sp.get("text", "—"), self._w["spread"],
                  FG_RED if sp.get("blocking") else FG_GREEN, self._f["mono"], bg=bg, height=self._h)
            self._align_cell(bg, g.get("align") or {})
            _cell(self.mid, (g.get("market") or {}).get("text", "—"), self._w["market"],
                  FG_GRAY, self._f["small"], bg=bg, height=self._h)
        badge = g.get("badge", "✓")
        _cell(self.mid, badge, self._w["badge"],
              FG_RED if badge != "✓" else FG_GREEN, self._f["mono"],
              anchor="center", bg=bg, height=self._h)

    def _align_cell(self, bg, al: dict):
        """Az idősík-irányok pöttyei — KERET NÉLKÜL.

        A keret a stratégia jelzés-cellájának van fenntartva: ott az „engedélyt"
        jelenti. Itt csak a piaci tény látszik (együtt állnak-e az idősíkok), és
        ez instrumentum-tulajdonság."""
        f = tk.Frame(self.mid, width=self._w["align"], bg=bg, height=self._h)
        f.pack(side="left", padx=(0, GAP))
        f.pack_propagate(False)
        inner = tk.Frame(f, bg=bg, height=self._h)
        inner.pack(expand=True)
        signs = al.get("signs") or []
        if not signs:
            tk.Label(inner, text="—", fg=FG_GRAY_DIM, bg=bg, font=self._f["mono"],
                     bd=0, padx=0, pady=0, highlightthickness=0).pack()
            return
        for s in signs:
            tk.Label(inner, text=_DOT, bg=bg, font=self._f["mono"],
                     fg=FG_GREEN if s > 0 else FG_RED if s < 0 else FG_GRAY_DIM,
                     bd=0, padx=0, pady=0, highlightthickness=0).pack(side="left")

    def _build_strategies(self, bg):
        for st in self.data.get("strategies") or []:
            self._build_one_strategy(bg, st)

    def _build_one_strategy(self, bg, st: dict):
        """Egy stratégia blokkja. Összecsukva CSAK a jelzés-cella marad — az
        viszont a keretével a kapu-érintettséget is hordozza, tehát a legtömörebb
        nézet sem veszít információt."""
        self._stages_cell(bg, st)
        if self._collapsed.get("strategies"):
            return
        pos = st.get("position") or {}
        day = st.get("daily") or {}
        _cell(self.mid, _money_r(pos.get("money"), pos.get("r")), self._w["position"],
              FG_WHITE, self._f["mono"], anchor="e", bg=bg, height=self._h)
        _cell(self.mid, _money_r(day.get("money"), day.get("r")), self._w["daily"],
              _pnl_color(day.get("money")), self._f["mono"], anchor="e", bg=bg, height=self._h)
        q = st.get("quality") or "—"
        _cell(self.mid, q, self._w["quality"], _quality_color(q), self._f["small"],
              anchor="center", bg=bg, height=self._h)
        # Vezérlés: kattintható Labelek (NEM Button — lásd a modul-doksit)
        ctrl = tk.Frame(self.mid, width=self._w["ctrl"], bg=bg, height=self._h)
        ctrl.pack(side="left", padx=(0, GAP))
        ctrl.pack_propagate(False)
        inner = tk.Frame(ctrl, bg=bg, height=self._h)
        inner.pack(expand=True)
        live = st.get("live")
        for txt, fg, cb in (("■" if live else "▶", FG_RED if live else FG_GREEN,
                             st.get("on_toggle")),
                            ("OPT", FG_BLUE, st.get("on_opt"))):
            l = tk.Label(inner, text=txt, fg=fg, bg=bg, font=self._f["small"],
                         cursor="hand2", bd=0, padx=3, pady=0, highlightthickness=0)
            l.pack(side="left")
            if cb:
                l.bind("<Button-1>", lambda _e, c=cb: c())
        _cell(self.mid, st.get("opt") or "—", self._w["opt"], FG_GRAY,
              self._f["small"], anchor="center", bg=bg, height=self._h)

    def _stages_cell(self, bg, st: dict):
        """A jelzés-cella: stádium-pöttyök + KERET.

        A pöttyök a stratégia belső állapotát mondják (SMA irány · M15 jel · M1
        belépő), a keret az engedélyt: tömör piros = blokkolva, szaggatott sárga =
        kockázatcsökkentés, NINCS keret = semmi nem szól bele.

        A „nincs keret" a leggyakoribb eset, ezért néma — a jelölés csak akkor
        szóljon, ha tényleg történik valami."""
        frame_st = st.get("frame") or ""
        color = _FRAME.get(frame_st)
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
        for s in (st.get("stages") or []):
            tk.Label(dots, text=_DOT, bg=bg, font=self._f["mono"],
                     fg=_stage_color(s), bd=0, padx=0, pady=0,
                     highlightthickness=0).pack(side="left")

    # ── jobb: fix ───────────────────────────────────────────────────────
    def _build_total(self, bg, on_close):
        t = self.data.get("total") or {}
        pos, day = t.get("position") or {}, t.get("daily") or {}
        _cell(self.right, _money_r(pos.get("money"), pos.get("r")), self._w["total_pos"],
              FG_WHITE, self._f["mono_b"], anchor="e", bg=bg, height=self._h)
        _cell(self.right, _money_r(day.get("money"), day.get("r")), self._w["total_daily"],
              _pnl_color(day.get("money")), self._f["mono_b"], anchor="e", bg=bg, height=self._h)
        # Az X az instrumentum TÖRLÉSE — a sor legvégén, megerősítéssel (a hívó
        # dolga). Szándékosan nincs a stratégia vezérlői közt: az más művelet.
        _click_label(self.right, "✕", self._w["close"], FG_GRAY_DIM, self._f["small"],
                     on_click=on_close, bg=bg, height=self._h)


def _stage_color(s):
    return {"buy": FG_GREEN, "sell": FG_RED, "on": FG_GREEN}.get(s, FG_GRAY_DIM)


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

def build_header(parent, fonts: dict, strategies: list, collapsed: dict = None):
    """A sorokkal EGYEZŐ fejléc.

    A fejlécnek ugyanazt a betűt és ugyanazokat a szélességeket kell használnia,
    mint a celláknak — különben az oszlopok nem illeszkednek (ez az 1. körben
    ténylegesen előfordult)."""
    collapsed = collapsed or {}
    f = fonts["small"]
    h = row_height(fonts)            # a sorokkal AZONOS magasság
    w = widths(fonts, strategies, collapsed)   # a sorokkal AZONOS szélességek

    def group(parent_, keys, text, fg=FG_GRAY_DIM):
        """Csoport-felirat, ami a hozzá tartozó oszlopok FÖLÖTT áll végig.
        A szélessége a tagoszlopok összege + a köztük lévő hézagok — így a
        két fejlécsor és a cellák egy vonalban maradnak."""
        span = sum(w[k] for k in keys) + GAP * (len(keys) - 1)
        _cell(parent_, text, span, fg, f, anchor="center", bg=BG_HEADER, height=h)

    head = tk.Frame(parent, bg=BG_HEADER)
    # ── 1. sor: csoportok (a terv „Instrumentum / Kapuk / Stratégiák" sávja) ──
    top = tk.Frame(head, bg=BG_HEADER, height=h)
    top.pack(fill="x")
    tl, tm, tr = (tk.Frame(top, bg=BG_HEADER, height=h) for _ in range(3))
    for x in (tl, tm, tr):
        x.pack(side="left", fill="y")
    group(tl, ("symbol", "bid", "ask", "change"), "Instrumentum")
    gate_keys = ("spread", "align", "market")
    if not collapsed.get("gates"):
        group(tm, gate_keys, "Kapuk")
    _cell(tm, "", w["badge"], FG_GRAY_DIM, f, bg=BG_HEADER, height=h)
    strat_keys = (("stages",) if collapsed.get("strategies")
                  else ("stages", "position", "daily", "quality", "ctrl", "opt"))
    for name in strategies:
        group(tm, strat_keys, name, FG_BLUE)
    group(tr, ("total_pos", "total_daily"), "Összesítő")
    _cell(tr, "", w["close"], FG_GRAY_DIM, f, bg=BG_HEADER, height=h)

    # ── 2. sor: oszlopnevek ──
    bot = tk.Frame(head, bg=BG_HEADER, height=h)
    bot.pack(fill="x")
    left, mid, right = (tk.Frame(bot, bg=BG_HEADER, height=h) for _ in range(3))
    for x in (left, mid, right):
        x.pack(side="left", fill="y")

    for key, txt in (("symbol", "Symbol"), ("bid", "BID"), ("ask", "ASK"),
                     ("change", "Vált.%")):
        _cell(left, txt, w[key], FG_GRAY_DIM, f, bg=BG_HEADER, height=h)
    if not collapsed.get("gates"):
        for key, txt in (("spread", "Spread"), ("align", "Együtt"),
                         ("market", "Piac")):
            _cell(mid, txt, w[key], FG_GRAY_DIM, f, bg=BG_HEADER, height=h)
    _cell(mid, "K.Össz.", w["badge"], FG_GRAY_DIM, f, anchor="center",
          bg=BG_HEADER, height=h)
    for _name in strategies:
        _cell(mid, "jelzés", w["stages"], FG_GRAY_DIM, f, anchor="center",
              bg=BG_HEADER, height=h)
        if collapsed.get("strategies"):
            continue
        for key, txt in (("position", "Pozíció"), ("daily", "Napi P&L"),
                         ("quality", "Min."), ("ctrl", "Vezérlés"),
                         ("opt", "Opt")):
            _cell(mid, txt, w[key], FG_GRAY_DIM, f, bg=BG_HEADER, height=h)
    _cell(right, "Pozíció", w["total_pos"], FG_GRAY_DIM, f, anchor="e",
          bg=BG_HEADER, height=h)
    _cell(right, "Napi P&L", w["total_daily"], FG_GRAY_DIM, f, anchor="e",
          bg=BG_HEADER, height=h)
    _cell(right, "", w["close"], FG_GRAY_DIM, f, bg=BG_HEADER, height=h)
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
            {"name": "wpr_sma", "stages": ["buy", "buy", "off"], "frame": "blocked",
             "position": {"money": 1.00, "r": 1.0},
             "daily": {"money": 0.03, "r": 0.01},
             "quality": "Jó", "live": True, "opt": "06/29"},
            {"name": "ml_ai", "stages": ["sell", "off", "off"], "frame": "",
             "position": {"money": 1.00, "r": 1.0},
             "daily": {"money": 0.03, "r": 0.01},
             "quality": "Jó", "live": False, "opt": "85%"},
        ],
        "total": {"position": {"money": 2.00, "r": 2.0},
                  "daily": {"money": 0.06, "r": 0.02}},
    }


def build_demo(parent, collapsed: dict = None, rows: int = 3):
    """Fejléc + néhány sor kitalált adattal — a `tools/ui_preview.py`-hoz."""
    from tkinter import font as tkfont
    fonts = {
        "mono": tkfont.Font(family="Consolas", size=10),
        "mono_b": tkfont.Font(family="Consolas", size=10, weight="bold"),
        "small": tkfont.Font(family="Segoe UI", size=9),
    }
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

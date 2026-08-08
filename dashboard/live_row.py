"""
A Dashboard 2.0 tábla MODELLJE — oszlop-szélességek, formázók, alapértékek.

    │ Instrumentum │ Kapuk │ K.Össz. │ wpr_sma │ ml_ai │ … │ Összesítő │ X │
      FIX            összecsukható      összecsukható (stratégiánként)  FIX

Egy sor = egy instrumentum, és a per-stratégia adat VÍZSZINTESEN ismétlődik.
(A fa-elrendezés azért bukott, mert elrejtett dolgokat; a lapos azért, mert
függőlegesen ismételt.)

⚠ EZ A MODUL MÁR NEM RAJZOL. v2.7.0-ig itt lakott a widget-alapú renderelő is
(`LiveRow`, `build_header`, `_cell`, …), cellánként egy `Frame` + egy `Label`.
Az a rész megszűnt: a cél-skálán (30 instrumentum × 10 stratégia) 6427 widgetből
épült volna a tábla, egy összecsukás 13,3 mp-et vett volna el, és a Tk
geometria-kezelése lineárisan drágult a widget-számmal. A rajzolást a
`dashboard/canvas_table.py` vette át (vászon-elemek: 0,46 mp, ill. 12 ms
átméretezési lépésenként).

AMI ITT MARADT, azt a vászon-tábla HASZNÁLJA — és pont ezért maradt itt:

  • `widths()` / `row_height()` — a MÉRT oszlop-szélességek és sormagasság.
    A vászon ebből számolja az x-eltolásokat (`dashboard/canvas_columns.py`),
    tehát az oszlopok pixelre ugyanott vannak, ahol a widget-táblában voltak.
  • Formázók (`_money_r`, `_fmt_price`, `_run_text`, `_opt_text`, `_stage_color`,
    `_pnl_color`, `_quality_color`) — EGY forrás arra, hogy mi kerül a cellába.
  • Az összecsukás/megjelenítés szabályai (`pnl_mode`, `is_collapsed`,
    `show_market`, `show_momentum`) — a fejléc és a sorok közös igazsága.
  • `demo_row()` — a bemeneti szerződés, adatként (a `tools/ui_preview.py` és a
    tesztek ezt használják).

A modul TISZTA: az adatot sima dictben kapja, nincs MT5/live_trader függése, és
a `tkinter` is csak a betű-méréshez kell (`fonts[...].measure`).
"""

from __future__ import annotations

from dashboard.theme import (FG_WHITE, FG_GREEN, FG_RED, FG_GRAY, FG_GRAY_DIM,
                             FG_BLUE, FG_ORANGE)

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
    "market": ("small", "Sz.Bika"), "momentum": ("mono", "↑9.99"),
    "cost": ("mono", "99.9:1 +999%"),
    "volatility": ("mono", "9.99×"),
    "badge": ("mono", "⛔9"),
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
    "momentum": "Lendület", "cost": "Költség",
    "volatility": "Volat.",
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


def show_momentum(collapsed: dict) -> bool:
    """Latszik-e a `Lendulet` oszlop?

    Ugyanaz a szabaly, mint a `Piac`-nal: ha egyetlen paron sincs bekapcsolva a
    kapu, az oszlop minden soron ugyanazt mondana ket szammal — helyet foglal,
    informaciot nem ad. A hivo `collapsed["hide_momentum"]`-ba teszi a dontest,
    es a SOR es a FEJLEC ugyanazt kapja (kulonben elcsusznanak az oszlopok)."""
    return not (collapsed or {}).get("hide_momentum")


def show_cost(collapsed: dict) -> bool:
    """Latszik-e a `Koltseg` oszlop? Ugyanaz a szabaly, mint a Piac/Lendulet:
    ha egyetlen paron sincs merheto terv (SL/TP), az oszlop vegig `—` lenne."""
    return not (collapsed or {}).get("hide_cost")


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
    # A `Piac` oszlop a VALÓDI kategória-címkék közül a leghosszabbhoz igazodik.
    # A `_SAMPLE`-ben szereplő „Sz.Bika" (7 betű) rövidebb volt, mint az
    # „Érdektelen" (10) vagy az „Oldalazás" (9) — élesben levágódott a végük.
    # Lusta import: a `market_strategy` a `regime`-et húzza be, és ez a modul
    # enélkül is használható (a szélesség ilyenkor a mintaszövegé marad).
    try:
        from core import market_strategy as _ms
        out["market"] = max(out["market"],
                            max(small.measure(t) for t in _ms.display_labels())
                            + 2 * PAD)
    except Exception:
        pass
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

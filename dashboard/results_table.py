"""Az optimalizálás eredménytáblája — a trials CSV OLVASHATÓ formában.

A felhasználói dokumentáció (`Paraméterek vs OPT vs Backtest`) kérése:

    „Láthatóvá teszem az exportált CSV fájlt táblázat formátumban. Az oszlopok
     ugyanazok mint a CSV exportban, legyen szűrhető és rendezhető, illetve a
     megfelelő mezők legyenek megfelelő típusúak (pl. DD = %). Az egyes sorai
     legyenek zöldek, ha pozitív az eredmény és piros, ha negatív."

⚠ A modul KÉT rétegre válik szét, és ez szándékos: a beolvasás/típusolás/
szűrés/rendezés TISZTA függvények (nincs Tk), a nézet csak megjeleníti őket.
Így a szűrő-logika tesztelhető anélkül, hogy ablakot kellene nyitni — egy hibás
összehasonlítás itt azt jelentené, hogy a felhasználó egy nem létező sort
választ ki és ELINDÍTJA vele az élő kereskedést.

⚠ A CSV magyar Excel-formátumú: `;` elválasztó és `,` tizedesjel. Ha ezt
elvétenénk, a „0,1864" 1864-nek olvasódna — a 18,6%-os visszaesés 186400%-ként
jelenne meg, és a szűrő minden sort átengedne.
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# ── Oszlop-típusok. A nevekhez kötjük, mert a CSV fejléce stabil szerződés ──
KIND_INT = "int"
KIND_PCT = "pct"          # 0…1 arány → százalék
KIND_MONEY = "money"
KIND_FLOAT = "float"
KIND_TEXT = "text"

_KINDS = {
    "rank": KIND_INT, "trades": KIND_INT,
    "win_rate": KIND_PCT, "max_drawdown": KIND_PCT,
    "total_pnl": KIND_MONEY,
    "score": KIND_FLOAT, "profit_factor": KIND_FLOAT,
    "note": KIND_TEXT,
}

# A szűrhető mezők — pontosan azok, amiket a doksi kért.
FILTER_COLS = ("trades", "win_rate", "max_drawdown", "profit_factor")
OPS = ("≥", ">", "=", "<", "≤")

# Az „eredmény" oszlopa, ami a sor SZÍNÉT adja.
RESULT_COL = "total_pnl"

# Nem torheto szokoz — az ezres elvalaszto a penz-oszlopban.
NBSP = " "


def kind_of(col: str) -> str:
    """Egy oszlop típusa. Ismeretlen (paraméter-)oszlop → szám, ha az."""
    return _KINDS.get(col, KIND_FLOAT)


def to_num(raw):
    """Magyar Excel-szám → float. `None`, ha nem szám.

    ⚠ A tizedes VESSZŐ a lényeg: `0,1864` → 0.1864. Az ezres elválasztót nem
    használjuk a CSV-ben, tehát a vesszőt egyértelműen tizedesnek vehetjük.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if not s:
        return None
    if s.lower() == "inf":
        return float("inf")
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def load_csv(path) -> tuple:
    """`(oszlopok, sorok)` — a sorok NYERS szótárak (oszlop → szöveg)."""
    p = Path(path)
    if not p.exists():
        return [], []
    try:
        with open(p, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f, delimiter=";"))
    except Exception as ex:
        log.warning("trials CSV olvasási hiba (%s): %s", p, ex)
        return [], []
    if len(rows) < 2:
        return (rows[0] if rows else []), []
    header = [h.strip() for h in rows[0]]
    out = []
    for raw in rows[1:]:
        if not raw:
            continue
        out.append({header[j]: raw[j] for j in range(min(len(header), len(raw)))})
    return header, out


def fmt(col: str, raw) -> str:
    """Egy cella EMBERI alakja."""
    k = kind_of(col)
    if k == KIND_TEXT:
        return "" if raw is None else str(raw)
    v = to_num(raw)
    if v is None:
        return "" if raw is None else str(raw)
    if k == KIND_INT:
        return f"{int(round(v))}"
    # ⚠ MAGYAR alak: tizedes VESSZŐ, ezres SZÓKÖZ — ugyanaz, amit a CSV-ben és
    # az Excelben látsz. Vegyes írásmódnál (tábla pont, CSV vessző) a két nézet
    # összevetése folyamatos fordítgatás lenne.
    if k == KIND_PCT:
        return f"{v * 100:.1f}".replace(".", ",") + "%"
    if k == KIND_MONEY:
        # Az ezres elvalaszto NEM TORHETO szokoz (U+00A0): a szam igy nem
        # szakad kette a cella szelen. NEVESITVE, mert a forrasban egy sima
        # szokoztol megkulonboztethetetlen volna — a teszt is erre hivatkozik.
        return f"{v:,.2f}".replace(",", NBSP).replace(".", ",")
    if v == float("inf"):
        return "∞"
    return f"{v:g}".replace(".", ",")


def _cmp(op: str, a: float, b: float) -> bool:
    if op == ">":
        return a > b
    if op == "≥":
        return a >= b
    if op == "<":
        return a < b
    if op == "≤":
        return a <= b
    # Egyenlőség lebegőpontos értékre: a felhasználó „0,35"-öt ír, az adat
    # 0,3494 — a szigorú == gyakorlatilag SOSEM találna. A megjelenített
    # pontossághoz igazítunk, hogy az „=" azt jelentse, amit a szem lát.
    return abs(a - b) < 5e-4


def apply_filters(rows: list, filters: list) -> list:
    """`filters`: `[(oszlop, operátor, érték), …]` — MINDEN feltételnek teljesülnie kell.

    ⚠ A százalékos mezőknél a felhasználó SZÁZALÉKOT ír (35), az adat arány
    (0,35). A konverzió itt történik, egy helyen — ha a nézetre bíznánk, a
    tesztek zöldek lennének, a felület mégis rosszul szűrne.
    A nem szám cellájú sor NEM felel meg (nem tudjuk összevetni → kiesik).
    """
    out = []
    for r in rows:
        ok = True
        for col, op, val in filters:
            v = to_num(r.get(col))
            if v is None:
                ok = False
                break
            ref = float(val)
            if kind_of(col) == KIND_PCT:
                ref = ref / 100.0
            if not _cmp(op, v, ref):
                ok = False
                break
        if ok:
            out.append(r)
    return out


def sort_rows(rows: list, col: str, descending: bool) -> list:
    """Rendezés egy oszlop szerint. A számokat SZÁMKÉNT (nem szövegként)."""
    if not col:
        return list(rows)
    text = kind_of(col) == KIND_TEXT

    def key(r):
        if text:
            return str(r.get(col) or "")
        v = to_num(r.get(col))
        # A hiányzó érték MINDIG a végére kerül, bármelyik irányba rendezünk —
        # különben csökkenőben az üres cellák ülnének a lista tetején.
        if v is None:
            return float("-inf") if descending else float("inf")
        return v

    return sorted(rows, key=key, reverse=descending)


def row_tone(row: dict) -> str:
    """A sor színe az EREDMÉNY szerint: `pos` / `neg` / `zero`."""
    v = to_num(row.get(RESULT_COL))
    if v is None or v == 0:
        return "zero"
    return "pos" if v > 0 else "neg"


# ---------------------------------------------------------------------------
# A nézet
# ---------------------------------------------------------------------------

def build(parent, path, fonts, on_export=None, theme=None):
    """Az eredménytábla felépítése egy szülő keretbe. Visszaad egy vezérlőt.

    `path`: a trials CSV. `on_export`: az Export gomb (a doksi kérése szerint
    ide költözött). A hívó adja a betűket és a témát → a modul stratégia- és
    instrumentum-független marad.
    """
    import tkinter as tk
    from tkinter import ttk
    from dashboard import theme as _th

    th = theme or _th
    BG, FG_WHITE, FG_GRAY = th.BG, th.FG_WHITE, th.FG_GRAY
    FG_GREEN, FG_RED, FG_GRAY_DIM = th.FG_GREEN, th.FG_RED, th.FG_GRAY_DIM

    cols, rows = load_csv(path)
    wrap = tk.Frame(parent, bg=BG)
    wrap.pack(fill="both", expand=True)

    if not cols:
        tk.Label(wrap, bg=BG, fg=FG_GRAY, font=fonts["small"], justify="left",
                 anchor="w", text=(
                     "Még nincs eredmény ehhez a párhoz és stratégiához.\n\n"
                     f"Várt fájl:  {path}\n\n"
                     "Az optimalizálás menet közben, 10 trialonként írja — "
                     "tehát futás közben is meg lehet nézni.")
                 ).pack(anchor="w", padx=12, pady=12)
        return None

    state = {"sort": "rank", "desc": False, "rows": rows, "all": rows}

    # ── Szűrő-sáv ───────────────────────────────────────────────────────────
    bar = tk.Frame(wrap, bg=BG)
    bar.pack(fill="x", padx=10, pady=(8, 4))
    tk.Label(bar, text="Szűrés:", bg=BG, fg=FG_GRAY, font=fonts["small"]
             ).pack(side="left", padx=(0, 6))

    widgets = {}
    for col in FILTER_COLS:
        if col not in cols:
            continue
        cell = tk.Frame(bar, bg=BG)
        cell.pack(side="left", padx=(0, 12))
        label = col + (" %" if kind_of(col) == KIND_PCT else "")
        tk.Label(cell, text=label, bg=BG, fg=FG_GRAY_DIM, font=fonts["small"]
                 ).pack(side="left")
        ov = tk.StringVar(value="≥")
        om = ttk.Combobox(cell, textvariable=ov, values=list(OPS), width=3,
                          state="readonly")
        om.pack(side="left", padx=2)
        ev = tk.StringVar(value="")
        en = tk.Entry(cell, textvariable=ev, width=6, bg=th.BG_HEADER,
                      fg=FG_WHITE, insertbackground=FG_WHITE, relief="flat",
                      font=fonts["small"])
        en.pack(side="left")
        widgets[col] = (ov, ev)

    count_lbl = tk.Label(bar, text="", bg=BG, fg=FG_GRAY, font=fonts["small"])
    count_lbl.pack(side="left", padx=(6, 0))

    # ── A tábla ─────────────────────────────────────────────────────────────
    holder = tk.Frame(wrap, bg=BG)
    holder.pack(fill="both", expand=True, padx=10, pady=(0, 6))
    tree = ttk.Treeview(holder, columns=cols, show="headings", height=18)
    ysb = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
    xsb = ttk.Scrollbar(holder, orient="horizontal", command=tree.xview)
    tree.configure(yscroll=ysb.set, xscroll=xsb.set)
    tree.grid(row=0, column=0, sticky="nsew")
    ysb.grid(row=0, column=1, sticky="ns")
    xsb.grid(row=1, column=0, sticky="ew")
    holder.rowconfigure(0, weight=1)
    holder.columnconfigure(0, weight=1)

    # A sor SZÍNE az eredmény szerint (a doksi kérése).
    tree.tag_configure("pos", foreground=FG_GREEN)
    tree.tag_configure("neg", foreground=FG_RED)
    tree.tag_configure("zero", foreground=FG_GRAY)

    def _redraw():
        tree.delete(*tree.get_children())
        for r in state["rows"]:
            tree.insert("", "end", tags=(row_tone(r),),
                        values=[fmt(c, r.get(c)) for c in cols])
        count_lbl.config(
            text=f"{len(state['rows'])} / {len(state['all'])} sor")

    def _refilter(*_a):
        flt = []
        for col, (ov, ev) in widgets.items():
            raw = ev.get().strip().replace(",", ".")
            if not raw:
                continue
            try:
                flt.append((col, ov.get(), float(raw)))
            except ValueError:
                continue          # félkész gépelés — ne ugráljon a tábla
        state["rows"] = sort_rows(apply_filters(state["all"], flt),
                                  state["sort"], state["desc"])
        _redraw()

    for _ov, _ev in widgets.values():
        _ev.trace_add("write", _refilter)
        _ov.trace_add("write", _refilter)

    def _on_head(col):
        state["desc"] = (not state["desc"]) if state["sort"] == col else True
        state["sort"] = col
        _refilter()
        for c in cols:
            arrow = "" if c != col else (" ▼" if state["desc"] else " ▲")
            tree.heading(c, text=c + arrow)

    for c in cols:
        tree.heading(c, text=c, command=lambda cc=c: _on_head(cc))
        w = 150 if c == "note" else (90 if c in _KINDS else 80)
        tree.column(c, width=w, anchor="e" if kind_of(c) != KIND_TEXT else "w",
                    stretch=False)

    if on_export:
        btns = tk.Frame(wrap, bg=BG)
        btns.pack(fill="x", padx=10, pady=(0, 8))
        tk.Button(btns, text="CSV megnyitása", bg=th.BTN_BT_BG, fg=th.BTN_BT_FG,
                  relief="flat", font=fonts["small"], command=on_export
                  ).pack(side="left")
        tk.Label(btns, bg=BG, fg=FG_GRAY_DIM, font=fonts["small"],
                 text=f"   {Path(path).name}").pack(side="left")

    _refilter()
    return {"tree": tree, "state": state, "refresh": _refilter,
            "filters": widgets}

"""
KÖTÉS-LISTA — egy backtest-futás kötései tételesen.

Eddig a futás EGYETLEN sorban végződött („42 kötés, +1 234$, PF 1,31"), és ha a
szám nem tetszett, nem volt hova továbbmenni: nem derült ki, hogy egy rossz
átlagot két katasztrofális kötés húz-e le, vagy negyven közepes; hogy a nyereség
a célárból jön-e vagy a trailingből; hogy a cost-cut mit vágott le.

⚠ A ZÁRÁS OKA A LEGFONTOSABB OSZLOP, és nem a `status` nyers átvétele:

    sl + risk_free=True   →  „Stop (BE/trail)"   ‼ ez NYERESÉG is lehet
    sl + risk_free=False  →  „Stop"
    tp                    →  „Célár"
    exit                  →  „Kiszállási jel"
    cut                   →  „Cost-cut (idő)"

A `risk_free` megkülönböztetés nélkül a lista önellentmondónak látszana: egy
„Stop"-ként zárt kötés +240$-ral. Az a stop viszont már a belépőn (vagy azon
túl) állt — a kockázatcsökkentés eredménye, nem veszteség.

⚠ AZ `R` OSZLOP a P&L-nél TÖBBET mond: a $ összeg a méretezéstől is függ, az R
csak a kereskedéstől. Két +100$-os kötés közül a +2,0R jó belépő volt, a +0,3R
csak nagy méret. Ahol a `risk_usd` nem ismert (0), ott a cella ÜRES marad —
nem 0,0, mert az azt hazudná, hogy megmértük és nulla lett.

TISZTA modul: a számoló rész se tkintert, se fájlt nem lát (soronként
tesztelhető), a `build()` pedig csak a megjelenítés.
"""

from __future__ import annotations

# A tábla oszlopai — a sorrend a KÉRDÉSEK sorrendje: mikor · merre · hol be/ki ·
# mennyi · mennyi kockázathoz képest · MIÉRT ért véget.
COLS = ("nyitás", "irány", "be", "ki", "zárva", "P&L", "R", "ok")

# Oszlop-fajták: a rendezés és a formázás ebből dől el (nem oszlopnév-találgatásból).
KIND_TIME, KIND_TEXT, KIND_PRICE, KIND_MONEY, KIND_R = (
    "time", "text", "price", "money", "r")
KINDS = {
    "nyitás": KIND_TIME, "zárva": KIND_TIME,
    "irány": KIND_TEXT, "ok": KIND_TEXT,
    "be": KIND_PRICE, "ki": KIND_PRICE,
    "P&L": KIND_MONEY, "R": KIND_R,
}

# A zárás okának EMBERI neve. A kulcs a `Trade.status`; az `sl` kettéválik a
# `risk_free` szerint (lásd a modul fejlécét).
REASON = {
    "tp":       "Célár",
    "sl":       "Stop",
    "sl_free":  "Stop (BE/trail)",
    "exit":     "Kiszállási jel",
    "cut":      "Cost-cut (idő)",
    "open":     "nyitva",
}

# A szűrő-sáv választható okai (a „mind" mellett). Sorrend = gyakoriság.
REASON_KEYS = ("tp", "sl", "sl_free", "exit", "cut")


def reason_of(status: str, risk_free: bool) -> str:
    """A zárás okának kulcsa. ⚠ A `risk_free` stop KÜLÖN eset: az a stop már a
    belépőn (vagy azon túl) állt, tehát nyereséggel is zárhatott."""
    st = (status or "").strip().lower()
    if st == "sl" and risk_free:
        return "sl_free"
    return st if st in REASON else (st or "open")


def rows_from(result) -> list:
    """`BacktestResult` → sor-szótárak. `None`/üres bemenetre üres lista.

    A `result.closed` a LEZÁRT kötések listája. A nyitva maradtakat szándékosan
    NEM vesszük be: nincs záró áruk, tehát se P&L-jük, se R-jük — egy „—"-okkal
    teli sor csak zajt adna a listához, a darabszámuk pedig a metrikákban ott van.
    """
    out = []
    for t in (getattr(result, "closed", None) or []):
        risk = float(getattr(t, "risk_usd", 0.0) or 0.0)
        pnl = float(getattr(t, "pnl_usd", 0.0) or 0.0)
        out.append({
            "nyitás": getattr(t, "open_time", None),
            "irány": getattr(t, "direction", "") or "",
            "be": _f(getattr(t, "open_price", None)),
            "ki": _f(getattr(t, "close_price", None)),
            "zárva": getattr(t, "close_time", None),
            "P&L": pnl,
            # ⚠ ÜRES, ha a kockázat nem ismert — a 0,0 azt hazudná, hogy mértük.
            "R": (pnl / risk) if risk > 0 else None,
            "ok": reason_of(getattr(t, "status", ""),
                            bool(getattr(t, "risk_free", False))),
            # Nem oszlop, de a szűrés és a színezés használja:
            "_win": pnl > 0,
            "_built": len(getattr(t, "legs", []) or []) > 1,
        })
    return out


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── Formázás (magyar: tizedesVESSZŐ, ezres NEM törhető szóköz) ───────────────
NBSP = " "


def fmt(col: str, v) -> str:
    """Egy cella szövege. `None` → „—" (nem üres: az üres cellát a szem
    hiányzó ADATNAK olvassa, a gondolatjel azt mondja, hogy nincs értelmezve)."""
    if v is None or v == "":
        return "—"
    kind = KINDS.get(col, KIND_TEXT)
    if kind == KIND_TIME:
        try:
            return v.strftime("%m-%d %H:%M")
        except AttributeError:
            return str(v)
    if kind == KIND_TEXT:
        return REASON.get(v, v) if col == "ok" else str(v)
    if kind == KIND_PRICE:
        return f"{float(v):,.2f}".replace(",", NBSP).replace(".", ",")
    if kind == KIND_MONEY:
        return f"{float(v):+,.2f}".replace(",", NBSP).replace(".", ",")
    if kind == KIND_R:
        return f"{float(v):+.2f}".replace(".", ",")
    return str(v)


# ── Rendezés ────────────────────────────────────────────────────────────────
def sort_rows(rows: list, col: str, descending: bool) -> list:
    """⚠ A HIÁNYZÓ érték MINDIG a lista VÉGÉRE kerül, akármelyik irányba
    rendezel. Különben az R szerinti rendezés a nem mért kötéseket egyszer
    legfelülre, egyszer legalulra dobná — és ott, ahol az adat HIÁNYZIK, nincs
    olyan hely, ami igazat mondana; a végén legalább nem tolja el a képet."""
    def key(r):
        v = r.get(col)
        missing = v is None or v == ""
        if missing:
            return (1, 0.0, "")
        if KINDS.get(col) in (KIND_PRICE, KIND_MONEY, KIND_R):
            return (0, float(v), "")
        if KINDS.get(col) == KIND_TIME:
            try:
                return (0, v.timestamp(), "")
            except AttributeError:
                return (0, 0.0, str(v))
        return (0, 0.0, str(v))

    body = sorted([r for r in rows if not _missing(r, col)],
                  key=key, reverse=descending)
    return body + [r for r in rows if _missing(r, col)]


def _missing(r, col):
    v = r.get(col)
    return v is None or v == ""


# ── Szűrés ──────────────────────────────────────────────────────────────────
def apply_filters(rows: list, direction: str = "", outcome: str = "",
                  reason: str = "") -> list:
    """`direction`: "BUY"/"SELL"/""; `outcome`: "win"/"loss"/"";
    `reason`: a REASON kulcsa vagy "". Üres = nincs szűrés."""
    out = list(rows)
    if direction:
        out = [r for r in out if r.get("irány") == direction]
    if outcome == "win":
        out = [r for r in out if r.get("_win")]
    elif outcome == "loss":
        out = [r for r in out if not r.get("_win")]
    if reason:
        out = [r for r in out if r.get("ok") == reason]
    return out


def row_tone(row: dict) -> str:
    return "pos" if row.get("_win") else ("neg" if row.get("P&L") else "zero")


# ── Összegzés ───────────────────────────────────────────────────────────────
def summary_line(rows: list) -> str:
    """A SZŰRT halmaz egy sorban. ⚠ A szűrt halmazé, nem az összesé: ha a
    „csak Stop" szűrő be van kapcsolva, a lényeg épp az, hogy AZOK mennyit
    visznek — az összes kötés összege máshol (a metrika-sávon) ott van."""
    if not rows:
        return "nincs megjelenített kötés"
    n = len(rows)
    wins = sum(1 for r in rows if r.get("_win"))
    pnl = sum(float(r.get("P&L") or 0.0) for r in rows)
    rs = [float(r["R"]) for r in rows if r.get("R") is not None]
    txt = (f"{n} kötés · {wins} nyerő ({wins / n * 100:.0f}%) · "
           f"{pnl:+,.0f}$".replace(",", NBSP))
    if rs:
        txt += f" · átlag {sum(rs) / len(rs):+.2f}R".replace(".", ",")
    return txt


# ── CSV-export ──────────────────────────────────────────────────────────────
# A projekt máshol is `;` elválasztót és tizedesVESSZŐT használ (trials CSV):
# a magyar Excel így nyitja meg kattintásra, átalakítás nélkül.
def to_csv(rows: list) -> str:
    lines = [";".join(COLS)]
    for r in rows:
        lines.append(";".join(_csv_cell(c, r.get(c)) for c in COLS))
    return "\n".join(lines) + "\n"


def _csv_cell(col: str, v) -> str:
    if v is None or v == "":
        return ""
    kind = KINDS.get(col, KIND_TEXT)
    if kind == KIND_TIME:
        try:
            return v.strftime("%Y-%m-%d %H:%M")
        except AttributeError:
            return str(v)
    if kind == KIND_TEXT:
        return REASON.get(v, str(v)) if col == "ok" else str(v)
    return f"{float(v):.4f}".replace(".", ",")


# ── Nézet ───────────────────────────────────────────────────────────────────
def build(parent, fonts, theme=None, on_export=None):
    """Kötés-lista egy szülő keretbe. Visszaad egy vezérlőt `set_rows`-szal.

    A tábla ÜRESEN is felépül: a futás előtt is ott a helye, tehát nem ugrál az
    elrendezés, amikor megjön az eredmény."""
    import tkinter as tk
    from tkinter import ttk
    from dashboard import theme as _th

    th = theme or _th
    BG, FG_WHITE, FG_GRAY = th.BG, th.FG_WHITE, th.FG_GRAY
    FG_GREEN, FG_RED, FG_GRAY_DIM = th.FG_GREEN, th.FG_RED, th.FG_GRAY_DIM
    sf = fonts["small"]

    state = {"all": [], "rows": [], "sort": "nyitás", "desc": False}

    wrap = tk.Frame(parent, bg=BG)
    wrap.pack(fill="both", expand=True)

    # ── Szűrő-sáv ───────────────────────────────────────────────────────────
    bar = tk.Frame(wrap, bg=BG)
    bar.pack(fill="x", padx=10, pady=(6, 4))
    tk.Label(bar, text="Szűrés:", bg=BG, fg=FG_GRAY, font=sf).pack(side="left",
                                                                   padx=(0, 6))
    _dir = tk.StringVar(value="mind")
    _out = tk.StringVar(value="mind")
    _rsn = tk.StringVar(value="mind")
    for _var, _vals, _w in ((_dir, ("mind", "BUY", "SELL"), 6),
                            (_out, ("mind", "nyerő", "vesztő"), 8),
                            (_rsn, ("mind",) + tuple(REASON[k] for k in REASON_KEYS),
                             16)):
        cb = ttk.Combobox(bar, textvariable=_var, values=list(_vals), width=_w,
                          state="readonly", font=sf)
        cb.pack(side="left", padx=(0, 8))
    sum_lbl = tk.Label(bar, text="", bg=BG, fg=FG_GRAY, font=sf)
    sum_lbl.pack(side="left", padx=(6, 0))
    if on_export is not None:
        tk.Button(bar, text="CSV", bg=th.BG_HEADER, fg=FG_WHITE, relief="flat",
                  font=sf, cursor="hand2",
                  command=lambda: on_export(state["rows"])).pack(side="right")

    # ── A tábla ─────────────────────────────────────────────────────────────
    # ⚠ A ttk.Treeview NEM örökli a tk widgetek színeit (saját, világos
    # alapértelmezése van) — a stílust a BETÖLTÖTT témából építjük, és a
    # stílus-NEVET is a színekhez kötjük, különben bőrváltás után egy korábban
    # regisztrált, régi színű stílus maradna érvényben.
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass
    sname = f"Trd{abs(hash((BG, th.BG_HEADER, FG_WHITE))) % 10 ** 8}.Treeview"
    style.configure(sname, background=BG, fieldbackground=BG, foreground=FG_WHITE,
                    borderwidth=0, rowheight=20)
    style.configure(sname + ".Heading", background=th.BG_HEADER, foreground=FG_GRAY,
                    relief="flat", borderwidth=0)
    style.map(sname + ".Heading", background=[("active", th.BG_HEADER)])
    style.map(sname, background=[("selected", th.BG_HEADER)],
              foreground=[("selected", FG_WHITE)])

    holder = tk.Frame(wrap, bg=BG)
    holder.pack(fill="both", expand=True, padx=10, pady=(0, 6))
    tree = ttk.Treeview(holder, columns=COLS, show="headings", height=12,
                        style=sname)
    ysb = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
    tree.configure(yscroll=ysb.set)
    tree.grid(row=0, column=0, sticky="nsew")
    ysb.grid(row=0, column=1, sticky="ns")
    holder.rowconfigure(0, weight=1)
    holder.columnconfigure(0, weight=1)

    tree.tag_configure("pos", foreground=FG_GREEN)
    tree.tag_configure("neg", foreground=FG_RED)
    tree.tag_configure("zero", foreground=FG_GRAY)

    _EMPTY = tk.Label(wrap, bg=BG, fg=FG_GRAY_DIM, font=sf, anchor="w",
                      justify="left",
                      text="Még nincs futás — indítsd el fent, és ide kerülnek "
                           "a kötések tételesen.")

    def _redraw():
        tree.delete(*tree.get_children())
        for r in state["rows"]:
            tree.insert("", "end", tags=(row_tone(r),),
                        values=[fmt(c, r.get(c)) for c in COLS])
        sum_lbl.config(text=summary_line(state["rows"]))
        if state["all"]:
            _EMPTY.pack_forget()
        else:
            _EMPTY.pack(anchor="w", padx=12, pady=(0, 8))

    def _refilter(*_a):
        _r = {v: k for k, v in REASON.items()}.get(_rsn.get(), "")
        state["rows"] = sort_rows(
            apply_filters(state["all"],
                          "" if _dir.get() == "mind" else _dir.get(),
                          {"nyerő": "win", "vesztő": "loss"}.get(_out.get(), ""),
                          "" if _rsn.get() == "mind" else _r),
            state["sort"], state["desc"])
        _redraw()

    for _v in (_dir, _out, _rsn):
        _v.trace_add("write", _refilter)

    def _on_head(col):
        state["desc"] = (not state["desc"]) if state["sort"] == col else True
        state["sort"] = col
        _refilter()
        for c in COLS:
            tree.heading(c, text=c + ("" if c != col
                                      else (" ▼" if state["desc"] else " ▲")))

    for c in COLS:
        tree.heading(c, text=c, command=lambda cc=c: _on_head(cc))
        tree.column(c, width=(96 if KINDS[c] == KIND_TIME else
                              (128 if c == "ok" else 72)),
                    anchor=("w" if KINDS[c] == KIND_TEXT else "e"))

    class Ctl:
        frame = wrap

        def set_rows(self, rows):
            state["all"] = list(rows or [])
            _refilter()

        def rows(self):
            return list(state["rows"])

    ctl = Ctl()
    ctl.set_rows([])
    return ctl

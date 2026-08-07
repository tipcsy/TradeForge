"""A VASZON-TABLA (dashboard/canvas_table.py) — es a PARITAS a widget-tablaval.

Az elfogadasi feltetel nem az, hogy "mukodik", hanem hogy UGYANAZT MUTATJA, mint
a mai tabla — csak gyorsan. Ezert a legfontosabb allitas itt egy KERESZT-ELLENOR-
ZES: ugyanarra a sor-adatra felepitunk egy valodi `LiveRow`-t es a vaszon
cella-modelljet, majd cellankent osszevetjuk a KIIRT SZOVEGET es SZINT.

Igy ha barmelyik formazo elvandorol egymastol (mas kerekites, mas szin-szabaly),
a teszt megfogja — nem a felhasznalo veszi eszre elesben.
"""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import applog
applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


try:
    import tkinter as tk
    _p = tk.Tk(); _p.destroy()
    TK_OK = True
except Exception as e:
    TK_OK = False
    print(f"KIHAGYVA: nincs hasznalhato tkinter ({type(e).__name__}: {e})")

if TK_OK:
    from dashboard import canvas_cells as cc
    from dashboard import canvas_table as ct
    from dashboard import live_row as lr
    from dashboard import theme as _theme

    root = tk.Tk(); root.withdraw()
    _theme._FONTS.clear()
    fonts = _theme.fonts()

    def make_rows(n=3, strategies=("wpr_sma", "ml_ai")):
        base = lr.demo_row()
        proto = base["strategies"][0]
        out = []
        for i in range(n):
            r = copy.deepcopy(base)
            r["symbol"] = f"SYM{i}"
            r["bid"] = 1000.0 + i
            r["ask"] = 1000.5 + i
            r["change_pct"] = (i - 1) * 0.5          # negativ, nulla, pozitiv
            r["strategies"] = []
            for s in strategies:
                st = copy.deepcopy(proto)
                st["name"] = s
                r["strategies"].append(st)
            out.append(r)
        return out

    # ══ 1. PARITAS: ugyanaz a szoveg es szin, mint a widget-sorban ═══════
    holder = tk.Frame(root)
    rows = make_rows(3)
    collapsed = {"gates": False, "strategies": set()}
    mismatch = []
    for i, d in enumerate(rows):
        wrow = lr.LiveRow(holder, d, fonts, collapsed, stripe=i)
        cells = cc.cells_for(d, collapsed)
        for key, lbl in wrow._lbl.items():
            if key.endswith("|ctrl_run") or key.endswith("|ctrl_opt"):
                n, sub = key.split("|ctrl_")
                cell = cells.get(f"{n}|ctrl")
                part = next((p for p in cell.parts if p[0] == sub), None)
                got = (part[1], part[2])
            else:
                cell = cells.get(key)
                if cell is None:
                    continue
                got = (cell.text, cell.fg)
            want = (lbl.cget("text"), str(lbl.cget("fg")))
            if (str(got[0]), str(got[1])) != want:
                mismatch.append((key, want, got))
        # a pottyok szine is
        for nm, dots in wrow._dots.items():
            cell = cells.get(f"{nm}|stages") if nm != "align" else cells.get("align")
            if cell is None:
                continue
            wd = [str(x.cget("fg")) for x in dots]
            if [str(c) for c in cell.dots] != wd:
                mismatch.append((f"dots:{nm}", wd, cell.dots))

    check("MINDEN cella szovege es szine egyezik a widget-sorral",
          not mismatch, str(mismatch[:3]))
    check("...es a paritas tenylegesen mert valamit (nem ures halmaz)",
          len(rows) * 10 < sum(len(lr.LiveRow(holder, d, fonts, collapsed)._lbl)
                               for d in rows[:1]) * len(rows) + 1)

    # ══ 2. A tabla felepul es ELEMEKET rajzol, nem widgeteket ═══════════
    tbl = ct.CanvasTable(root, fonts, rows=rows, collapsed={},
                         on_close=lambda s: None)
    tbl.frame.pack(fill="both", expand=True)
    root.update_idletasks()

    def widget_count(w):
        return 1 + sum(widget_count(c) for c in w.winfo_children())

    items = sum(len(c.find_all()) for c in tbl._bc.values())
    check("a sorok VASZON-ELEMEK, nem widgetek",
          items > 50 and widget_count(tbl.frame) < 20,
          f"elem={items}, widget={widget_count(tbl.frame)}")

    # ══ 3. Kattintasok — a cella teljes teruleten fognak ════════════════
    clicks = []
    rows2 = make_rows(2)
    rows2[0]["on_symbol"] = lambda: clicks.append("symbol")
    rows2[0]["gates"]["on_spread"] = lambda: clicks.append("spread")
    rows2[0]["gates"]["align"]["on_click"] = lambda: clicks.append("align")
    rows2[0]["gates"]["momentum"] = {"text": "↑1.2", "on_click":
                                     lambda: clicks.append("momentum")}
    rows2[0]["strategies"][0]["on_stages"] = lambda: clicks.append("stages")
    rows2[0]["strategies"][0]["on_toggle"] = lambda: clicks.append("run")
    rows2[0]["strategies"][0]["on_opt"] = lambda: clicks.append("opt")
    closed = []
    tbl2 = ct.CanvasTable(root, fonts, rows=rows2, collapsed={},
                          on_close=lambda s: closed.append(s))
    tbl2.frame.pack(fill="both", expand=True)
    root.update_idletasks()

    # A kattintas-huzalozast a KOZPONTI elosztobol ellenorizzuk (`fire`), nem
    # szintetikus egeresemennyel: az a vaszon gorgetesi allapotatol es attol is
    # fuggene, hogy az ablak lathato-e — es egy elmaradt kattintas ilyenkor nem
    # a kod hibaja lenne, hanem a teszte.
    def fire(key, sub=None):
        return tbl2.fire(0, key, sub)

    check("MINDEN kattinthato cella be van kotve",
          {("symbol",), ("spread",), ("align",), ("momentum",)}
          <= {(k[1],) for k in tbl2.clickable() if k[0] == 0},
          str(sorted(k[1] for k in tbl2.clickable() if k[0] == 0)))

    for key, sub, expect in (("symbol", None, "symbol"),
                             ("spread", None, "spread"),
                             ("align", None, "align"),
                             ("momentum", None, "momentum"),
                             ("wpr_sma|stages", None, "stages"),
                             ("wpr_sma|ctrl", "run", "run"),
                             ("wpr_sma|ctrl", "opt", "opt")):
        clicks.clear()
        ok = fire(key, sub)
        check(f"kattintas: {expect}", ok and clicks == [expect],
              f"talalt={ok}, {clicks}")

    clicks.clear()
    fire("close")
    check("a sor vegi ✕ a TORLEST hivja", closed == ["SYM0"], str(closed))

    # ══ 4. HELYBEN frissites — szerkezet-valtozas nelkul nincs ujraepites ═
    ids_before = dict(tbl2._items)
    rows2[0]["bid"] = 12345.67
    tbl2.refresh(rows2)
    check("valtozo adatnal NEM epul ujra (ugyanazok az elem-azonositok)",
          tbl2._items.keys() == ids_before.keys()
          and tbl2._items[(0, "bid")] == ids_before[(0, "bid")])
    bc = tbl2._bc["left"]
    txt = bc.itemcget([t for t in tbl2._items[(0, "bid")]
                       if bc.type(t) == "text"][0], "text")
    check("...de az uj ertek KIIRODIK", "12345.67" in txt, txt)

    # Szerkezet-valtozas (uj sor) -> ujraepites
    rows3 = make_rows(4)
    tbl2.refresh(rows3)
    check("uj instrumentumnal UJRAEPUL", (3, "symbol") in tbl2._items)

    # ══ 5. Osszecsukas es rendezes ══════════════════════════════════════
    tbl3 = ct.CanvasTable(root, fonts, rows=make_rows(3), collapsed={})
    tbl3.frame.pack(fill="both", expand=True)
    root.update_idletasks()
    check("alapbol latszik a Spread oszlop", (0, "spread") in tbl3._items)
    tbl3._toggle("gates")
    check("a kapu-blokk osszecsukhato (a Spread eltunik, a K.Ossz. marad)",
          (0, "spread") not in tbl3._items and (0, "badge") in tbl3._items)
    tbl3._toggle("gates")
    check("...es visszanyithato", (0, "spread") in tbl3._items)
    tbl3._toggle("wpr_sma")
    check("a strategia-blokk osszecsukva a jelzest ES a vezerlest tartja",
          (0, "wpr_sma|stages") in tbl3._items
          and (0, "wpr_sma|ctrl") in tbl3._items
          and (0, "wpr_sma|position") not in tbl3._items)

    tbl3._sort("symbol")
    check("rendezes: elso kattintas novekvo", tbl3.sort() == ("symbol", 1),
          str(tbl3.sort()))
    tbl3._sort("symbol")
    check("...masodikra csokkeno", tbl3.sort() == ("symbol", -1), str(tbl3.sort()))

    # ══ 6. Az elrejtheto oszlopok szabalya AZONOS a widget-tablaeval ════
    plain = make_rows(2)
    for r in plain:
        r["gates"]["market"] = {"text": "—"}
        r["gates"]["momentum"] = {"text": "—"}
    tbl4 = ct.CanvasTable(root, fonts, rows=plain, collapsed={})
    check("ha egy soron sincs mert Piac/Lendulet, az oszlop KIMARAD",
          (0, "market") not in tbl4._items and (0, "momentum") not in tbl4._items)

    root.destroy()

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

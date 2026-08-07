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
    from dashboard.theme import BG_ROW_ODD, BG_ROW_EVEN

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

    # ══ 6b. AMIT CSAK A VASZON TUD ══════════════════════════════════════
    # Ezek NEM a widget-tabla masolatai — az a paritas mar igazolva van. Ezek az
    # a haromfele rajzelem, amit widgetekkel nem (vagy csak dragan) lehetett.
    marked = make_rows(3)
    marked[0]["strategies"][0]["frame"] = "blocked"
    marked[1]["strategies"][0]["frame"] = "reduced"
    marked[2]["strategies"][0]["frame"] = ""
    tblv = ct.CanvasTable(root, fonts, rows=marked, collapsed={})
    tblv.frame.pack(fill="both", expand=True)
    root.update_idletasks()
    bmid = tblv._bc["mid"]

    def frame_rect(i):
        ids = tblv._items[(i, "wpr_sma|stages")]
        rects = [t for t in ids if bmid.type(t) == "rectangle"]
        return rects[-1] if rects else None

    # A SZAGGATOTT keret az EREDETI terv volt (live_row.py `_DOT` folott): a
    # tkinter `highlightthickness` nem tud szaggatott lenni, ezert maradt a
    # csak-szines megkulonboztetes. Vasznon ingyen van.
    r0, r1 = frame_rect(0), frame_rect(1)
    check("blokkolo kapunal TOMOR keret",
          bmid.itemcget(r0, "dash") in ("", "()") and
          str(bmid.itemcget(r0, "outline")) != "",
          f"dash={bmid.itemcget(r0, 'dash')!r}")
    check("kockazatcsokkentesnel SZAGGATOTT keret (nem csak mas szin)",
          bmid.itemcget(r1, "dash") not in ("", "()"),
          f"dash={bmid.itemcget(r1, 'dash')!r}")
    check("...es a ket keret szine is kulonbozo",
          bmid.itemcget(r0, "outline") != bmid.itemcget(r1, "outline"))
    r2 = frame_rect(2)
    check("keret nelkuli allapotban nincs latszo keret",
          r2 is None or str(bmid.itemcget(r2, "outline")) in ("", "{}"))

    # A POTTYOK MINDENHOL POTTYOK maradnak — az „Egyutt" oszlopban is. Egy
    # koztes valtozat ott ▲/▼ nyilat rajzolt (hogy az irany ne csak a szinen
    # muljon); a felhasznalo eldobta. Ez az allitas orzi, hogy ne csusszon vissza.
    def glyphs(i, key):
        pane = cc.PANE_OF(key.split("|")[-1])
        b = tblv._bc[pane]
        return [b.itemcget(t, "text") for t in tblv._items[(i, key)]
                if b.type(t) == "text"]

    al = glyphs(0, "align")
    check("az „Egyutt” oszlop zold/piros POTTYOKAT rajzol (nem nyilat)",
          bool(al) and all(ch == "●" for ch in al), str(al))
    stg = glyphs(0, "wpr_sma|stages")
    check("...es a stadium-cella is pottyokkel",
          bool(stg) and all(ch == "●" for ch in stg), str(stg))
    dot_colors = [tblv._bc["mid"].itemcget(t, "fill")
                  for t in tblv._items[(0, "align")]
                  if tblv._bc["mid"].type(t) == "text"]
    check("...a SZIN hordozza az iranyt (zold/piros/halvany)",
          all(c for c in dot_colors) and len(set(dot_colors)) >= 2,
          str(dot_colors))

    # BLOKK-ELVALASZTO VONALAK: soronkent kulon keret-widget helyett savonkent
    # EGY vonal az egesz oszlopra.
    lines = [t for t in bmid.find_all() if bmid.type(t) == "line"]
    check("a blokkok kozott elvalaszto VONAL van",
          len(lines) >= 2, f"vonal={len(lines)}")
    # ⚠ A vonal LETEZESE nem eleg: az elso valtozat BG_HEADER-rel rajzolt, ami a
    # sorok hattereten gyakorlatilag lathatatlan volt (a user eles proban nem is
    # vette eszre). Azt is meg kell kovetelni, hogy ELUSSON a hattertol.
    def rgb(w, c):
        r, g, b = w.winfo_rgb(c)
        return (r // 256, g // 256, b // 256)

    lc = rgb(bmid, bmid.itemcget(lines[0], "fill"))
    for bgname in (BG_ROW_ODD, BG_ROW_EVEN):
        d = sum(abs(a - b) for a, b in zip(lc, rgb(bmid, bgname)))
        check(f"...es LATSZIK is a sorhatteren ({bgname})", d >= 40,
              f"csatorna-kulonbseg={d}")
    check("...es a vonal a TELJES tabla magassagaban fut (nem soronkent)",
          bool(lines) and bmid.coords(lines[0])[3] >= 3 * tblv._h,
          str(bmid.coords(lines[0]) if lines else None))

    # A K.OSSZ. A KAPU-BLOKK VEGE, nem a kovetkezo strategiae. Eles proban a
    # kapuk osszesitoje vizualisan a wpr_sma blokkjaba csuszott, mert az
    # elvalaszto a FELIRAT-csoportokbol (`groups`) szuletett, a badge fole pedig
    # szandekosan nem kerul felirat -> a vonal a badge ELE kerult. Osszecsukott
    # kapuknal nem latszott, mert ott nincs kapu-blokk.
    for coll, ahol in (({}, "kinyitva"), ({"gates": True}, "osszecsukva")):
        blk = ct.blocks(["wpr_sma", "ml_ai"], coll)
        gate = next(b for b in blk if "badge" in b)
        check(f"a K.Ossz. a KAPU-blokkban van ({ahol})",
              gate[-1] == "badge" and not any("wpr_sma" in k for k in gate),
              str(gate))
    strat_blk = [b for b in ct.blocks(["wpr_sma"], {}) if b[0].startswith("wpr_sma")]
    check("...es a strategia blokkja NEM tartalmazza",
          strat_blk and "badge" not in strat_blk[0], str(strat_blk))

    # A vonal tenylegesen a badge UTAN fusson (x szerint)
    tblb = ct.CanvasTable(root, fonts, rows=make_rows(2), collapsed={})
    tblb.frame.pack(fill="both", expand=True)
    root.update_idletasks()
    from dashboard import canvas_columns as _cx
    bx, bw = _cx.x_of(tblb._cols, "badge")
    sx, _sw = _cx.x_of(tblb._cols, "wpr_sma|stages")
    edges = tblb._block_edges()["mid"]
    check("a kapu-blokk vonala a K.Ossz. UTAN es a jelzes ELOTT fut",
          any(bx + bw <= e <= sx for e in edges), f"badge veg={bx+bw}, jelzes={sx}, vonalak={edges}")

    # ══ 7. EGYETLEN fuggoleges gorgetosav ═══════════════════════════════
    # Az elso eles proban KETTO latszott: a vaszon-tabla sajat gorgetese MELLE a
    # gui.py regi, kulso gorgetheto vaszna is odatette a magaet. A kulsonek nem
    # volt mit gorgetnie (teljes magassagu, INAKTIV sav), a belso pedig csak
    # akkora helyet kapott, amekkorat a kulso adott — rovid fogantyu.
    def scrollbars(w, out=None):
        out = [] if out is None else out
        for c in w.winfo_children():
            if isinstance(c, tk.Scrollbar) or isinstance(c, ct._ThinScrollbar):
                out.append(c)
            scrollbars(c, out)
        return out

    tbl5 = ct.CanvasTable(root, fonts, rows=make_rows(3), collapsed={})
    tbl5.frame.pack(fill="both", expand=True)
    root.update_idletasks()
    bars = scrollbars(tbl5.frame)
    check("a tabla PONTOSAN egy fuggoleges gorgetosavot hoz",
          len([b for b in bars if getattr(b, "_vert", False)]) == 1,
          f"osszes sav={len(bars)}")
    check("...es az NEM a natív (Windowson fehér, a sotet temahoz nem illo)",
          not any(isinstance(b, tk.Scrollbar) for b in bars))

    # A gui.py oldala: `canvas` elrendezesben a tabla NEM kerulhet a kulso,
    # gorgetheto vaszonba — ez a szerkezeti feltetel, ami a ket savot okozta.
    import dashboard.gui as G
    from trading.live_trader import PairDashboardState
    _theme._FONTS.clear()
    G.DashboardWindow._start_bg_poller = lambda self: None
    G.DashboardWindow._poll_mt5 = lambda self: None
    G.OptimizerController._ensure_pool = lambda self: None
    G.DashboardWindow._save_main_config = lambda self: None
    cfgc = {"strategy": {"name": "wpr_sma"},
            "available_strategies": {"wpr_sma": True},
            "trading": {"account_risk_pct": 0.01, "max_open_slots": 4,
                        "daily_loss_limit_pct": 0.015, "daily_loss_limit_usd": 0},
            "dashboard": {"layout": "canvas"},
            "pairs": {"GOLD": {"enabled": True, "point_size": 0.01,
                               "pv1_point": 0.88, "min_lot": 0.01,
                               "lot_step": 0.01, "strategies": ["wpr_sma"]}}}
    ds = PairDashboardState(symbol="GOLD", trained=True, enabled=True)
    ds.digits, ds.bid, ds.ask = 2, 2000.0, 2000.5
    w = None
    try:
        w = G.DashboardWindow(cfgc, {"GOLD": ds}, {"GOLD": "LIVE"}, {},
                              on_play_pair=None, on_stop_pair=None)
        w.root.withdraw(); w.root.update_idletasks()
        check("a `canvas` elrendezes NEM agyazza a tablat kulso gorgetheto vaszonba",
              not isinstance(w._table_frame.master, tk.Canvas),
              type(w._table_frame.master).__name__)
        # CSAK a tabla teruletet nezzuk: a tobbi ful (Poziciok, Lezart,
        # Backtest) sajat gorgetosavja jogos, es nem ehhez a kerdeshez tartozik.
        area = w._table_frame.master
        vbars = [b for b in scrollbars(area) if getattr(b, "_vert", False)]
        natives = [b for b in scrollbars(area) if isinstance(b, tk.Scrollbar)]
        check("...igy a tabla teruleten EGY fuggoleges sav van, natív nelkul",
              len(vbars) == 1 and not natives,
              f"tematizalt={len(vbars)}, nativ={len(natives)}")
    finally:
        if w is not None:
            w.root.destroy()

    root.destroy()

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

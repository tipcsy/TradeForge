"""A Dashboard 2.0 tablaja — dashboard/live_table.py.

Fix bal · gorgetheto kozep · fix jobb. A LEGFONTOSABB tulajdonsag, amit ez a
teszt oriz: a fejlec es a sorok oszlopai EGY VONALBAN maradnak — gorgetes kozben
is. Ezt a tabla szerkezetileg garantalja (a fejlec kozepe es a sorok kozepe
UGYANABBAN a vasznon van), es a teszt azt allitja, hogy ez igy is marad.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


try:
    import tkinter as tk
    from tkinter import font as tkfont
    _p = tk.Tk(); _p.destroy()
    TK_OK = True
except Exception as e:
    TK_OK = False
    print(f"KIHAGYVA: nincs hasznalhato tkinter ({type(e).__name__}: {e})")

if TK_OK:
    from tools import ui_preview as up
    from dashboard import live_table as lt
    from dashboard import live_row as lr

    ALL_COLL = {"gates": True, "strategies": True}

    def with_table(fn, collapsed=None, size=(1500, 240)):
        """Felepit egy tablat egy valodi ablakban, lefuttatja `fn(tabla)`-t."""
        up._make_dpi_aware()
        root = tk.Tk()
        root.geometry(f"{size[0]}x{size[1]}+40+40")
        root.attributes("-topmost", True)
        try:
            t = lt.build_demo(root, collapsed)
            root.update_idletasks()
            root.update()
            return fn(t)
        finally:
            root.destroy()

    # ══ 1. AZ OSZLOPOK EGY VONALBAN — a fejlec es a sorok ══════════════════
    def col_offsets(t):
        """A `_mid` kozvetlen gyermekei: a fejlec ket sora + soronkent egy keret.
        Mindegyikbol kiolvassuk a CELLAK x-eltolasait."""
        out = []
        for child in t._mid.winfo_children():
            xs = [c.winfo_x() for c in child.winfo_children()]
            if xs:
                out.append(xs)
        return out

    offs = with_table(col_offsets)
    # A fejlec ALSO sora es minden adatsor ugyanazokat az oszlopokat tartalmazza,
    # tehat az x-eltolasaiknak azonosnak kell lenniuk. (A fejlec FELSO sora a
    # csoport-feliratoke, az szandekosan mas tagolasu.)
    check("van fejlec + sorok a kozepen", len(offs) >= 3, f"{len(offs)} savszelet")
    data_offs = offs[1:]                      # az elso a csoport-sav
    check("a fejlec-oszlopok es a sor-oszlopok EGY VONALBAN vannak",
          all(o == data_offs[0] for o in data_offs),
          f"{len(set(map(tuple, data_offs)))} kulonbozo tagolas")

    # A csoport-sav SZELESSEGE fedje a tagoszlopokat: az utolso csoport jobb szele
    # egyezzen az utolso oszlop jobb szelevel (kulonben a felirat elcsuszna).
    def band_widths(t):
        out = []
        for child in t._mid.winfo_children():
            w = sum(c.winfo_width() for c in child.winfo_children())
            w += lr.GAP * max(0, len(child.winfo_children()) - 1)
            out.append(w)
        return out

    bw = with_table(band_widths)
    check("a csoport-sav ugyanolyan szeles, mint az oszlop-savok",
          len(set(bw)) == 1, f"szelessegek: {sorted(set(bw))}")

    # OSSZECSUKVA is: a strategia-blokkbol a jelzes MELLETT a Vezerles is marad
    # (osszecsukva is lehessen inditani/leallitani), tehat a FEJLECNEK is ket
    # oszlopa van ott. Ha a ketto szetcsuszik, minden tovabbi oszlop elcsuszik.
    offs_c = with_table(col_offsets, ALL_COLL)
    data_c = offs_c[1:]
    check("osszecsukva is EGY VONALBAN a fejlec es a sorok",
          all(o == data_c[0] for o in data_c),
          f"{len(set(map(tuple, data_c)))} kulonbozo tagolas")
    bw_c = with_table(band_widths, ALL_COLL)
    check("...es a csoport-sav is fedi a tagoszlopokat",
          len(set(bw_c)) == 1, f"szelessegek: {sorted(set(bw_c))}")

    def ctrl_labels(t):
        """Osszecsukva is ott van-e a Play/Stop es az OPT MINDEN strategianal?"""
        return [sorted(k for k in r._lbl if "|ctrl_" in k) for r in t._row_widgets]

    ctrls = with_table(ctrl_labels, ALL_COLL)
    check("osszecsukva is van Play/Stop es OPT minden strategianal",
          all(c == ["ml_ai|ctrl_opt", "ml_ai|ctrl_run",
                    "wpr_sma|ctrl_opt", "wpr_sma|ctrl_run"] for c in ctrls),
          str(ctrls[:1]))

    # ══ 2. Fuggoleges igazitas: a harom oszlop sorai egy magassagban ═══════
    def row_tops(t):
        """Soronkent a bal/kozep/jobb resz y-pozicioja. Ha elternek, a sorok
        elcsusznanak egymashoz kepest (kulon oszlopokban vannak!)."""
        return [(r.left.winfo_y(), r.mid.winfo_y(), r.right.winfo_y())
                for r in t._row_widgets]

    tops = with_table(row_tops)
    check("minden sor harom resze AZONOS magassagban van",
          all(len(set(t3)) == 1 for t3 in tops),
          f"{sum(1 for t3 in tops if len(set(t3)) > 1)} elcsuszott sor")
    check("a sorok NEM fedik egymast (novekvo y)",
          [t3[0] for t3 in tops] == sorted(t3[0] for t3 in tops))

    # ══ 3. Osszecsukas ════════════════════════════════════════════════════
    def mid_width(t):
        return t._mid.winfo_reqwidth()

    w_open = with_table(mid_width)
    w_coll = with_table(mid_width, ALL_COLL)
    check("az osszecsukas erdemben szukiti a kozepet", w_coll < w_open / 2,
          f"{w_coll} < {w_open // 2}")

    def toggle_and_measure(t):
        """A fejleces kapcsolo tenylegesen ujraepiti a tablat."""
        before = t._mid.winfo_reqwidth()
        t._toggle("gates")
        t.frame.update_idletasks()
        after = t._mid.winfo_reqwidth()
        return before, after, t.collapsed

    b, a, coll = with_table(toggle_and_measure)
    check("a 'Kapuk' kapcsolo osszecsukja a kapu-blokkot", a < b, f"{a} < {b}")
    check("...es az allapot is atbillen", coll["gates"] is True)

    def toggle_one_strategy(t):
        t._toggle("wpr_sma")
        t.frame.update_idletasks()
        return t.collapsed

    coll1 = with_table(toggle_one_strategy)
    check("EGYETLEN strategia is osszecsukhato",
          coll1["strategies"] == {"wpr_sma"}, f'{coll1["strategies"]}')

    # ══ 4. A gorditosav csak akkor latszik, ha van mit gorgetni ════════════
    check("kinyitva (1500 px-en nem fer ki) -> van gorditosav",
          with_table(lambda t: t._hbar.winfo_ismapped(), size=(1500, 240)))
    check("osszecsukva (kifer) -> NINCS gorditosav",
          not with_table(lambda t: t._hbar.winfo_ismapped(), ALL_COLL,
                         size=(1500, 240)))

    # ══ 5. Nincs osszeeses / levagas ══════════════════════════════════════
    for label, coll_, w in (("kinyitva", None, 1500), ("csukva", ALL_COLL, 1500)):
        b_ = (lambda c: (lambda p: lt.build_demo(p, c)))(coll_)
        n = up.inspect(b_, size=(w, 240))
        real = [x for x in up.truncated(n)
                if not (x["cls"] in ("Frame", "Canvas") and x["req_w"] > w)]
        check(f"{label}: semmi nem esik ossze", up.collapsed(n) == [])
        check(f"{label}: semmi nem vagodik le", real == [],
              "; ".join(f'{x["text"]!r} {x["req_w"]}>{x["w"]}' for x in real[:3]))

    # ══ 5b. TEMA es BETU — a programban valaszthato ═══════════════════════
    # A tabla a TEMA szineit es a TEMA megosztott betu-objektumait hasznalja,
    # nem sajatokat. A betu azonnal atut (megosztott Font), a szin viszont csak
    # ujraindulaskor — ez a program egeszenek konvencioja (dashboard/theme.py).
    from dashboard import theme as _t

    def uses_theme(t):
        """A tabla hattere a TEMA hattere legyen, ne bedrotozott hex."""
        return t.frame.cget("bg")

    check("a tabla a TEMA hatterszinet hasznalja", with_table(uses_theme) == _t.BG)

    def demo_fonts_are_shared(t):
        """A bemutato a theme.fonts() MEGOSZTOTT objektumait kapja — kulonben a
        betumeret-valtas nem utne at rajta."""
        shared = _t.fonts()
        return all(t._f.get(r) is shared.get(r) for r in lr.ROLES)

    check("a betuk a TEMA megosztott objektumai (nem sajat peldanyok)",
          with_table(demo_fonts_are_shared))

    # A sor csak a SAJAT szerepeit nezi: a theme.fonts() a teljes keszletet adja
    # (`title` nagyobb, `tiny` kisebb), es a `title` folosleges magasra tolna.
    _rt = tk.Tk()
    try:
        _t._FONTS.clear()          # a szingleton az ELOZO (mar eldobott) gyokerhez kotodott
        f = _t.fonts()
        h_used = lr.row_height(f)
        h_all = max(x.metrics("linespace") for x in f.values()) + 2 * lr.PAD
        check("a sor-magassag CSAK a hasznalt szerepekbol jon (nem a 'title'-bol)",
              h_used <= h_all, f"{h_used} <= {h_all}")
        check("a hasznalt szerepek mind leteznek a temaban",
              all(r in f for r in lr.ROLES), str(lr.ROLES))
    finally:
        _rt.destroy()

    def rebuild_works(t):
        """Betuvaltas utan a tabla ujraepitheto (a fix cella-meretek kulonben a
        REGI betuvel maradnanak kimerve)."""
        t.rebuild()
        t.frame.update_idletasks()
        return len(t._row_widgets)

    check("rebuild() ujraepiti a sorokat (betuvaltas utan kell)",
          with_table(rebuild_works) == 4)

    # ══ 6. A jobb oszlop MINDIG latszik (nem szoritja ki a kozep) ══════════
    def right_visible(t):
        t.frame.update_idletasks()
        return t._right.winfo_ismapped() and t._right.winfo_width() > 1

    check("kinyitva is latszik az Osszesito oszlop", with_table(right_visible))
    check("...osszecsukva is", with_table(right_visible, ALL_COLL))

    # ══ 7. A `Piac` oszlop elrejtese, ha egyik paron sincs beallitva ═══════
    def market_headers(t):
        return len([1 for w in _all_widgets(t.frame)
                    if w.winfo_class() == "Label" and w.cget("text") == "Piac"])

    def _all_widgets(w):
        yield w
        for c in w.winfo_children():
            yield from _all_widgets(c)

    def with_market(t):
        return market_headers(t)

    def without_market(t):
        for d in t._rows:
            d["gates"]["market"]["text"] = "—"
        t.refresh(t._rows)
        t.frame.update_idletasks()
        return market_headers(t)

    check("van piac-allapot -> latszik a Piac oszlop", with_table(with_market) == 1)
    check("egyik paron sincs -> ELTUNIK", with_table(without_market) == 0)

    # A megjelenes/eltunes SZERKEZETI valtozas: ujra kell epiteni, kulonben a
    # helyben frissites a regi oszlopokkal maradna (es elcsusznanak a cellak).
    def rebuild_on_market_change(t):
        # SZAMLALOVAL, nem id()-vel: a felszabadult objektumok cime UJRA-
        # HASZNOSULHAT, es a teszt hamis egyezest merne (elso valtozatban
        # pontosan ez tortent — a kod jol mukodott, a MERES volt rossz).
        calls = []
        orig = t._build
        t._build = lambda: (calls.append(1), orig())[1]
        for d in t._rows:
            d["gates"]["market"]["text"] = "—"
        t.refresh(t._rows)
        return len(calls) == 1

    check("a Piac-oszlop eltunese UJRAEPITEST valt ki",
          with_table(rebuild_on_market_change))

    # ══ 8. A gorgetesi szinkron OSSZEVONVA (a "flow"-akadas javitasa) ═════
    # Az elso valtozat a <Configure> esemenyre AZONNAL futtatta a szinkront,
    # `update_idletasks()`-szel a kezelon belul — ablak-huzaskor ez lathato
    # akadast okozott, es a `configure()` ujabb <Configure>-t keltett (hurok).
    def sync_coalesces(t):
        t._sync_pending = False
        t._queue_sync(); t._queue_sync(); t._queue_sync()
        return t._sync_pending          # EGY utemezett munka, nem harom

    check("sok <Configure> EGY szinkronna olvad ossze", with_table(sync_coalesces))

    def no_op_guard(t):
        t.frame.update_idletasks()
        t._sync_scrollregion()
        first = t._last_sync
        t._sync_scrollregion()          # valtozatlan meret -> nem ir ujra
        return first is not None and first == t._last_sync

    check("valtozatlan meretnel nincs ujra-konfiguralas (nincs visszacsatolas)",
          with_table(no_op_guard))

    # A <Configure> az UTEMEZOT hivja, nem kozvetlenul a szinkront
    check("a <Configure> az utemezohoz kotodik",
          with_table(lambda t: "_queue_sync" in t._canvas.bind("<Configure>")))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

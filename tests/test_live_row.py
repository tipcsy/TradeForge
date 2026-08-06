"""A Dashboard 2.0 sora — dashboard/live_row.py.

A geometriat orzik: az 1. kor tanulsagai szerint a sor akkor bukik meg, ha
NEMAN levag vagy ugral. Mindketto merheto kepernyokep nelkul, ezert itt fut.
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
    from dashboard import live_row as lr

    OPEN = None
    GATES = {"gates": True}
    ALL = {"gates": True, "strategies": True}

    # A SOR-demo egy szuloben rakja egymas melle a harom reszt (a tablaban ezek
    # KULON oszlopok). Ezert az ablaknak el kell birnia a TELJES sort, kulonben a
    # `pack` a jobb oszlopot osszeszoritja — az nem a sor hibaja, hanem a demo
    # elrendezese. (Az elso valtozat 2200-at hasznalt, es a szuk ablak miatt
    # levagott jobb oszlopot a `truncated` szuroje elrejtette.)
    WIDE = 3000

    def nodes_for(collapsed, w=WIDE):
        return up.inspect(lambda p: lr.build_demo(p, collapsed), size=(w, 300))

    def real_truncation(nodes, w):
        """A kulso keretek azert 'lognak ki', mert a tartalom szelesebb az
        ablaknal — ez a TERVEZETT allapot (a kozep gorgetheto lesz). Csak azt
        nezzuk, ami az ablakon BELUL vagodott le.

        ⚠ A `req_w > w` szuro KORABBAN tul sokat rejtett: a szuk ablakban
        osszeszoritott JOBB oszlop levagott feliratai is kiestek. A LABEL-eket
        ezert MINDIG nezzuk — egy levagott felirat sosem "tervezett"."""
        return [t for t in up.truncated(nodes)
                if t["cls"] == "Label"
                or not (t["cls"] == "Frame" and t["req_w"] > w)]

    # ══ 1. Semmi nem esik ossze, semmi nem vagodik le ══════════════════════
    # A pack_propagate(False) MAGASSAG NELKUL 1 px-re lapitja a keretet — ez a
    # sor elso valtozataban tenylegesen meg is tortent, a kepernyokep mutatta meg.
    for label, coll, w in (("kinyitva", OPEN, WIDE), ("kapuk csukva", GATES, WIDE),
                           ("minden csukva", ALL, 1400)):
        n = nodes_for(coll, w)
        check(f"{label}: semmi nem esik ossze", up.collapsed(n) == [],
              f"{len(up.collapsed(n))} osszeesett")
        check(f"{label}: semmi nem vagodik le", real_truncation(n, w) == [],
              "; ".join(f"{t['text']!r} {t['req_w']}>{t['w']}"
                        for t in real_truncation(n, w)[:3]))

    # ══ 2. A sorok NEM ugralnak ════════════════════════════════════════════
    # Az 1. korben a Button magasabb volt a Label-nel, es a tabla ugralt.
    # A fa: content(0) > holder(1) > sor(2) > left/mid/right(3) > CELLA(4) >
    # belso diszek(5+). A cellak a 4. szinten vannak; a melyebb keretek (pottyok,
    # vezerlok kozepre igazitott dobozai) jogosan alacsonyabbak.
    n = nodes_for(OPEN)
    cells = [x for x in n if x["cls"] == "Frame" and x["mapped"]
             and x["h"] > 1 and x["depth"] in (3, 4)]
    heights = {x["h"] for x in cells}
    check("minden oszlop-cella AZONOS magassagu", len(heights) == 1,
          f"{len(cells)} cella, magassagok: {sorted(heights)}")

    # Nincs egyetlen Button sem: a vezerlok kattinthato Labelek (lasd modul-doksi)
    check("a sorban NINCS tk.Button (kattinthato Label helyette)",
          not [x for x in n if x["cls"] == "Button"])

    # ══ 3. Az osszecsukas TENYLEG szukit ═══════════════════════════════════
    def total_w(collapsed, w=WIDE):
        return max(x["req_w"] for x in nodes_for(collapsed, w) if x["depth"] <= 1)

    w_open, w_gates, w_all = total_w(OPEN), total_w(GATES), total_w(ALL, 1400)
    check("a kapuk osszecsukasa szukit", w_gates < w_open, f"{w_gates} < {w_open}")
    check("a strategiak osszecsukasa tovabb szukit", w_all < w_gates,
          f"{w_all} < {w_gates}")
    check("teljesen osszecsukva a felenel is keskenyebb", w_all < w_open / 2,
          f"{w_all} < {w_open // 2}")

    # ══ 4. A szelessegek MERTEK, nem bedrotozottak ═════════════════════════
    _r = tk.Tk()
    try:
        small = tkfont.Font(family="Segoe UI", size=9)
        f1 = {"mono": tkfont.Font(family="Consolas", size=10),
              "mono_bold": tkfont.Font(family="Consolas", size=10, weight="bold"),
              "small": small}
        f2 = {"mono": tkfont.Font(family="Consolas", size=14),
              "mono_bold": tkfont.Font(family="Consolas", size=14, weight="bold"),
              "small": tkfont.Font(family="Segoe UI", size=13)}
        w1, w2 = lr.widths(f1), lr.widths(f2)
        check("nagyobb betuhoz szelesebb oszlop tartozik",
              w2["position"] > w1["position"], f'{w2["position"]} > {w1["position"]}')
        check("nagyobb betuhoz magasabb sor tartozik",
              lr.row_height(f2) > lr.row_height(f1))
        # A FEJLEC is tartalom: az elso valtozat ezt kihagyta, es levagta a
        # "K.Ossz." / "Vezerles" feliratot.
        check("a badge oszlop elbirja a 'K.Ossz.' fejlecet",
              w1["badge"] >= small.measure("K.Össz."))
        check("a vezerles oszlop elbirja a 'Vezerles' fejlecet",
              w1["ctrl"] >= small.measure("Vezérlés"))
        # Osszecsukva a strategia NEVE a megmarado oszlopok (jelzes + Vezerles)
        # FOLOTT all — a felirat tehat a KETTO egyuttes szelessegebe kell ferjen.
        w_coll = lr.widths(f1, ["wpr_sma", "nagyon_hosszu_strategia_nev"],
                           {"strategies": True})
        _span = w_coll["stages"] + lr.GAP + w_coll["ctrl"]
        check("osszecsukva a megmarado blokk elbirja a leghosszabb strategia-nevet",
              _span >= small.measure("▸ nagyon_hosszu_strategia_nev") + 2 * lr.PAD,
              f'{_span} >= {small.measure("▸ nagyon_hosszu_strategia_nev")}')
        check("...kinyitva ez nem szelesiti (ott a blokk folott all a felirat)",
              lr.widths(f1, ["nagyon_hosszu_strategia_nev"])["stages"]
              == w1["stages"])

        # ── A P&L megjelenitesi mod SZUKITI az oszlopot ──────────────────
        # A felhasznalo panasza: "tul sok az ures resz". Csak-dollar modban az
        # R-nek fenntartott hely nem foglalhat.
        w_money = lr.widths(f1, (), {"pnl_mode": "money"})
        w_both = lr.widths(f1, (), {"pnl_mode": "both"})
        check("csak-dollar modban keskenyebb a Pozicio oszlop",
              w_money["position"] < w_both["position"],
              f'{w_money["position"]} < {w_both["position"]}')
        check("...es az Osszesito is", w_money["total_daily"] < w_both["total_daily"])
        check("a 'both' az alapertelmezes (nincs csendes viselkedes-valtas)",
              lr.widths(f1)["position"] == w_both["position"])
        check("ismeretlen mod -> 'both' (nem omlik ossze)",
              lr.pnl_mode({"pnl_mode": "nincs_ilyen"}) == "both")
    finally:
        _r.destroy()

    # ══ 5. A megjelenites szerzodese ═══════════════════════════════════════
    check("R nelkul csak a penz latszik (nem '0.00R')",
          lr._money_r(1.5, None) == "+1.50$")
    check("R-rel mindketto", lr._money_r(1.5, 1.0) == "+1.50$ +1.00R")
    check("hianyzo penz -> '-'", lr._money_r(None, None) == "—")
    check("csak-dollar mod: az R-t elhagyja",
          lr._money_r(1.5, 1.0, "money") == "+1.50$")
    check("csak-R mod: a penzt elhagyja", lr._money_r(1.5, 1.0, "r") == "+1.00R")
    check("csak-R mod, ismeretlen kockazat -> '-' (nem 0R)",
          lr._money_r(1.5, None, "r") == "—")

    demo = lr.demo_row()
    check("a bemutato-adat a terv Ger 40 sora", demo["symbol"] == "Ger 40")
    check("...ketto strategiaval", len(demo["strategies"]) == 2)
    check("...es az osszesito a blokkok osszege",
          abs(demo["total"]["position"]["money"]
              - sum(s["position"]["money"] for s in demo["strategies"])) < 1e-9)

    # ══ Az „Együtt" cella BERAGADASA (elesben bejelentve, v2.1.2) ═════════
    #
    # A sor INDULASKOR epul fel, amikor a TF-egyuttallas meg URES (a piaci
    # adat-loop 5 mp-et var az elso lekeres elott). Az `_align_cell` ilyenkor egy
    # `—` cimket rajzol es KILEP — a pottylistat meg sem hozza letre. Az
    # `update()` viszont csak MEGLEVO pottyoket szinez, tehat amikor megjott az
    # adat, a cella `—` maradt. A `structure_key` pedig nem vette eszre a 0 -> 3
    # valtozast, igy a tabla SOSEM epitette ujra: az oszlop az EGESZ
    # munkamenetre beragadt.

    from dashboard.theme import FG_GREEN as _FG_GREEN

    def _row(signs):
        d = lr.demo_row()
        d["gates"]["align"] = {"signs": signs}
        return d

    _root2 = tk.Tk()
    try:
        _f = {"mono": tkfont.Font(family="Consolas", size=10),
              "mono_bold": tkfont.Font(family="Consolas", size=10, weight="bold"),
              "small": tkfont.Font(family="Segoe UI", size=9)}

        _a = lr.LiveRow(_root2, _row([]), _f)
        check("A HIBA: ures jelekkel epult sor -> nincs pottylista",
              _a._dots.get("align") is None)
        check("JAVITAS: a megjott adat SZERKEZET-valtozas -> a tabla ujraepit",
              _a.update(_row([1, -1, -1])) is False)

        _b = lr.LiveRow(_root2, _row([1, -1, -1]), _f)
        check("meglevo pottyok szinvaltasa viszont HELYBEN megy (nem epit ujra)",
              _b.update(_row([1, 1, 1])) is True)
        check("...es a szinek tenyleg valtoznak",
              all(w.cget("fg") == _FG_GREEN for w in _b._dots["align"]))
        check("ures -> ures: nincs felesleges ujraepites",
              lr.LiveRow(_root2, _row([]), _f).update(_row([])) is True)
        check("HAROM -> KETTO idosik is ujraepitest kivan (mas cellaszam)",
              lr.LiveRow(_root2, _row([1, 1, 1]), _f).update(_row([1, 1])) is False)
        _c, _d2 = lr.LiveRow(_root2, lr.demo_row(), _f), lr.demo_row()
        _d2["strategies"][0]["stages"] = ["green"]
        check("a strategia-stadiumok szama tovabbra is a kulcs resze",
              _c.update(_d2) is False)
    finally:
        _root2.destroy()

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

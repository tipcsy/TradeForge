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
        # Osszecsukva a strategia NEVE all a jelzes-oszlop folott
        w_coll = lr.widths(f1, ["wpr_sma", "nagyon_hosszu_strategia_nev"],
                           {"strategies": True})
        check("osszecsukva a jelzes-oszlop elbirja a leghosszabb strategia-nevet",
              w_coll["stages"] >= small.measure("nagyon_hosszu_strategia_nev"))
        check("...kinyitva ez nem szelesiti (ott a blokk folott all a felirat)",
              lr.widths(f1, ["nagyon_hosszu_strategia_nev"])["stages"]
              == w1["stages"])
    finally:
        _r.destroy()

    # ══ 5. A megjelenites szerzodese ═══════════════════════════════════════
    check("R nelkul csak a penz latszik (nem '0.00R')",
          lr._money_r(1.5, None) == "+1.50$")
    check("R-rel mindketto", lr._money_r(1.5, 1.0) == "+1.50$ +1.00R")
    check("hianyzo penz -> '-'", lr._money_r(None, None) == "—")

    demo = lr.demo_row()
    check("a bemutato-adat a terv Ger 40 sora", demo["symbol"] == "Ger 40")
    check("...ketto strategiaval", len(demo["strategies"]) == 2)
    check("...es az osszesito a blokkok osszege",
          abs(demo["total"]["position"]["money"]
              - sum(s["position"]["money"] for s in demo["strategies"])) < 1e-9)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

"""A Dashboard 2.0 tabla MODELLJE — dashboard/live_row.py.

⚠ Ez a modul v2.7.0 ota MAR NEM RAJZOL: a widget-alapu renderelo (`LiveRow`,
`build_header`, `_cell`) megszunt, a rajzolas a `dashboard/canvas_table.py`-e.
Ami itt maradt — es amit ez a teszt oriz —, azt a VASZON-tabla hasznalja:

  • `widths()` / `row_height()`: a MERT oszlop-szelessegek. A vaszon ebbol
    szamolja az x-eltolasokat, tehat ha ez elcsuszik, az egesz tabla elcsuszik.
  • a formazok (`_money_r`, …): EGY forras arra, mi kerul a cellaba.
  • `demo_row()`: a bemeneti szerzodes, adatkent.

A korabbi geometria-allitasok (semmi nem esik ossze / nem vagodik le / a cellak
azonos magassaguak) a WIDGET-renderelot mertek — azzal egyutt megszuntek. Amit
ertelmes volt atmenteni, az az OSSZECSUKAS szukito hatasa: az most a MODELLBOL
merodik (oszlop-terkep), nem a kirajzolt keretekbol.
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

    # ══ 3. Az osszecsukas TENYLEG szukit ═══════════════════════════════════
    # A tabla teljes szelessege az OSZLOP-TERKEPBOL (nem a kirajzolt keretekbol):
    # ugyanaz a szam, amibol a vaszon-tabla is dolgozik.
    from dashboard import canvas_columns as _cx
    _rt = tk.Tk(); _rt.withdraw()
    from dashboard import theme as _th
    _th._FONTS.clear()
    _fonts = _th.fonts()
    STRATS = ["wpr_sma", "ml_ai"]

    def total_w(collapsed, w=None):
        return _cx.total_width(_cx.layout(_fonts, STRATS, collapsed or {}))

    w_open, w_gates, w_all = total_w(OPEN), total_w(GATES), total_w(ALL)
    _rt.destroy()
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

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

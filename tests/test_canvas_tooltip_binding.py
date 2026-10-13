"""A vászon-tábla buboréka KATTINTHATÓ cellán is (2026-10-13).

Tibi: „Újraindítás után még nem jelenik meg a tooltip" (a név-buborék). Ok: a
`_tb` kötés-kulcsa (vászon, címke, esemény, add) volt — a kattintható cellán a
kéz-kurzor `<Enter>`-je ELŐBB foglalta a kulcsot, és a buborék kötése NÉMÁN
kimaradt. Ez a név-, a Tőzsdék- és a kapu-cellák buborékát is megölte.
Második lelet: a buborék szövege csak az ELSŐ rajzoláskor íródott — rendezés
után a rekeszben más instrumentum ült, a buborék a régit mutatta volna.
"""
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                         # noqa: E402
applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


try:
    import tkinter as tk
    _p = tk.Tk(); _p.destroy()
    TK_OK = True
except Exception as e:                                           # noqa: BLE001
    TK_OK = False
    print(f"KIHAGYVA: nincs tkinter ({e})")

if TK_OK:
    from dashboard import canvas_table as ct, live_row as lr, theme as _theme
    root = tk.Tk(); root.withdraw()
    fonts = _theme.fonts()

    def rows_for(syms):
        out = []
        for s in syms:
            r = copy.deepcopy(lr.demo_row())
            r["symbol"] = s
            r["name_tip"] = f"{s} → X{s}"
            r["on_symbol"] = lambda: None          # KATTINTHATÓ név-cella
            out.append(r)
        return out

    tbl = ct.CanvasTable(root, fonts, rows=rows_for(["Ger40", "GOLD"]), collapsed={})
    root.update_idletasks()
    bc = tbl._bc[ct._cc.PANE_OF("symbol")]
    tag = "c0_symbol"
    check("a név-cella buborék-szövege a szótárban",
          tbl._tip_of(bc, tag).startswith("Ger40 → XGer40"), tbl._tip_of(bc, tag))
    check("a buborék <Enter> kötése LÉTREJÖTT (nem nyelte el a kurzor-kötés)",
          (str(bc), tag, "<Enter>", True, "tip") in tbl._bound)
    check("...és a kéz-kurzoré is megmaradt",
          (str(bc), tag, "<Enter>", True, "") in tbl._bound)
    _script = bc.tag_bind(tag, "<Enter>")
    check("a vásznon KÉT <Enter>-kezelő ül a név-cellán", _script.count("\n") >= 1
          or _script.count("if {") >= 2, _script[:120])

    tbl.refresh(rows_for(["GOLD", "Ger40"]))
    root.update_idletasks()
    check("rendezés/csere után a buborék a rekesz MOSTANI instrumentumáé",
          tbl._tip_of(bc, tag).startswith("GOLD → XGOLD"), tbl._tip_of(bc, tag))
    _n = len(tbl._bound)
    tbl.refresh(rows_for(["GOLD", "Ger40"]))
    check("frissítés nem köt újra (nincs kötés-szivárgás)", len(tbl._bound) == _n)
    root.destroy()

print(f"\n{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

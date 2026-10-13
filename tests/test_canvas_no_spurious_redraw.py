"""A vászon-tábla NEM rajzolja újra a sorokat feleslegesen (2026-10-13).

Tibi: „iszonyatosan lassú lett a program". A fagyásfigyelő szerint a fő szál a
`refresh` → `_redraw_row` → betű-mérés úton állt 4 mp-ig, 7–8 mp-enként. Ok: a
sor-szerkezet összevetése (v3.137.0) a `_visual` OSZLOP NÉLKÜLI kulcsait is
számolta (a frissítés a kikapcsolt kapuk celláit is beírja) → sosem egyezett →
MINDEN sor MINDEN frissítéskor újrarajzolódott.
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
    rows = [copy.deepcopy(lr.demo_row()) for _ in range(3)]
    for i, r in enumerate(rows):
        r["symbol"] = f"S{i}"
    # CSAK a spread-oszlop látszik: a többi kapu cellája oszlop NÉLKÜL készül
    tbl = ct.CanvasTable(root, _theme.fonts(), rows=rows,
                         collapsed={"gate_columns": ["spread"]})
    root.update_idletasks()
    hivas = []
    _eredeti = tbl._redraw_row
    tbl._redraw_row = lambda i, d: (hivas.append(i), _eredeti(i, d))
    for _ in range(3):
        tbl.refresh(copy.deepcopy(rows))
    check("változatlan adatnál EGYETLEN sor sem rajzolódik újra", hivas == [], hivas)
    rows2 = copy.deepcopy(rows)
    rows2[1]["strategies"][0]["stages"] = list(rows2[1]["strategies"][0]["stages"]) + ["ok"]
    tbl.refresh(rows2)
    check("valódi szerkezet-változásnál (több pötty) csak az az EGY sor", hivas == [1], hivas)
    root.destroy()

print(f"\n{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

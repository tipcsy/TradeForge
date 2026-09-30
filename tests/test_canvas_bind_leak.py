"""A vaszon-tabla sor-ujrarajzolasa NEM szivarogtathat Tcl-parancsokat.

LELET (2026-09-30): a felulet 2,4 ora alatt 3,2 GB-ra nott, a rendszer
behalt. Minden `tag_bind` UJ Tcl-parancsot regisztral, ami csak a vaszon
megszunesekor szabadul — a `_redraw_row` viszont a vasznat MEGTARTJA, es a
buborek `add="+"`-szal meg HALMOZODOTT is. Merve: 1500 sor-ujrarajzolas =
+4500 parancs (soronkent 3). A javitas: (vaszon, cimke, esemeny) harmasonkent
EGYSZER kotunk (`CanvasTable._tb`).
"""
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                          # noqa: E402
applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


try:
    import tkinter as tk
    _p = tk.Tk(); _p.destroy()
    TK_OK = True
except Exception as e:
    TK_OK = False
    print(f"KIHAGYVA: nincs hasznalhato tkinter ({e})")

if TK_OK:
    from dashboard import canvas_table as ct, live_row as lr, theme as _theme
    root = tk.Tk(); root.withdraw()
    _theme._FONTS.clear()
    base = lr.demo_row()
    rows = []
    for s in ["AAA", "BBB", "CCC"]:
        r = copy.deepcopy(base); r["symbol"] = s; rows.append(r)
    tbl = ct.CanvasTable(root, _theme.fonts(), rows=rows, collapsed={})
    root.update_idletasks()
    n = lambda: len(root.tk.call("info", "commands"))
    a = n()
    for _ in range(100):
        for i, d in enumerate(tbl._visible()):
            tbl._redraw_row(i, d)
    root.update_idletasks()
    b = n()
    check("300 sor-ujrarajzolas utan NEM nott a Tcl-parancsok szama", b - a == 0, f"+{b - a}")
    # a kattintas tovabbra is a FRISS visszahivast eri el
    check("a kotesek szama korlatos (nem no az ujrarajzolassal)",
          len(tbl._bound) < 200, str(len(tbl._bound)))
    root.destroy()

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

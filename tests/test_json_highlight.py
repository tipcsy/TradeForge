"""A Beállítások Json-lapjának színezése: ugyanaz az eredmény, gyorsan (2026-10-13).

Tibi: „a Beállításokra kattintva 4-5 mp-et kell várni". A színező minden
találatot `1.0+<n>c` indexszel jelölt — a Tk ezt a szöveg elejétől lépkedve
oldja fel, ~3000 soros confignál 1,1 mp. Az új út `sor.oszlop` indexet számol
Pythonban, és címkénként egy hívással jelöl. Ez a teszt a RÉGI algoritmussal
veti össze az eredményt (tartományra pontosan).
"""
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                         # noqa: E402
applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def regi(text):
    """A 2026-10-13 előtti színező (referencia)."""
    content = text.get("1.0", "end-1c")
    token = re.compile(r'"(?:\\.|[^"\\])*"|-?\d+\.?\d*(?:[eE][+-]?\d+)?'
                       r'|\b(?:true|false|null)\b')
    for m in token.finditer(content):
        s, e, tok = m.start(), m.end(), m.group()
        if tok[0] == '"':
            tag = "json_key" if content[e:e + 8].lstrip().startswith(":") else "json_str"
        elif tok in ("true", "false", "null"):
            tag = "json_bool"
        else:
            tag = "json_num"
        text.tag_add(tag, f"1.0+{s}c", f"1.0+{e}c")


try:
    import tkinter as tk
    _p = tk.Tk(); _p.destroy()
    TK_OK = True
except Exception as e:                                           # noqa: BLE001
    TK_OK = False
    print(f"KIHAGYVA: nincs tkinter ({e})")

if TK_OK:
    from dashboard.gui import DashboardWindow
    minta = {"pairs": {f"P{i}": {"point_size": 0.01 * i, "name": f'nev "{i}" \\ é',
                                 "on": i % 2 == 0, "x": None, "e": -1.5e-3,
                                 "lista": [1, 2.5, "a:b", True]}
                       for i in range(400)}}
    szoveg = json.dumps(minta, indent=2, ensure_ascii=False)
    root = tk.Tk(); root.withdraw()
    TAGS = ("json_key", "json_str", "json_num", "json_bool")

    def futtat(fn):
        t = tk.Text(root)
        t.insert("1.0", szoveg)
        t0 = time.perf_counter()
        fn(t)
        return time.perf_counter() - t0, {g: [str(x) for x in t.tag_ranges(g)] for g in TAGS}

    d_regi, a = futtat(regi)
    d_uj, b = futtat(DashboardWindow._highlight_json)
    check("az új színezés PONTOSAN ugyanazokat a tartományokat jelöli", a == b,
          {g: (len(a[g]), len(b[g])) for g in TAGS})
    check("mind a négy fajta előfordul a mintában", all(b[g] for g in TAGS))
    check(f"gyorsabb (régi {d_regi:.3f} s, új {d_uj:.3f} s)", d_uj < d_regi / 3)
    root.destroy()

print(f"\n{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

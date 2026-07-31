"""A kepernyokep-alapu UI-ellenorzes eszkoze — tools/ui_preview.py.

Az 1. korben ez a modszer NEGY valodi hibat fogott meg, de session-lokalis
szkriptkent elveszett. Most a repoban van, es ezek a tesztek a SZERZODESET
orzik: eszreveszi-e a ket konkret hibafajtat, ami akkor tenylegesen elofordult.

A kepernyokep-keszites NINCS itt tesztelve (kepernyot igenyelne, es zarolt gepen
vagy RDP-n hamis bukast adna) — az a `python tools/ui_preview.py` fejlesztoi
futtatas dolga. Itt csak a MERES fut, ami kep nelkul is mukodik.
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
    _probe = tk.Tk()
    _probe.destroy()
    TK_OK = True
except Exception as e:                                   # fej nelkuli kornyezet
    TK_OK = False
    print(f"KIHAGYVA: nincs hasznalhato tkinter ({type(e).__name__}: {e})")

if TK_OK:
    from tools import ui_preview as up

    # ══ 1. Levagas-detektalas ══════════════════════════════════════════════
    # Ez a hiba az 1. korben egy 10 kapus sort NEGYNEK mutatott: a cella nemán
    # levagta a szegmenseket. A neman a lenyeg — semmi nem jelezte.
    def build_truncated(parent):
        cell = tk.Frame(parent, width=50, height=20)
        cell.pack()
        cell.pack_propagate(False)          # fix meret -> a tartalom nem fer ki
        tk.Label(cell, text="⛔1 ●●● 250/1312 nagyon hosszu").pack(fill="both",
                                                                  expand=True)

    nodes = up.inspect(build_truncated, size=(400, 80))
    trunc = up.truncated(nodes)
    check("a levagott widget megtalalhato", len(trunc) >= 1)
    check("...es tenyleg tobbet kert, mint amit kapott",
          all(t["req_w"] > t["w"] or t["req_h"] > t["h"] for t in trunc))

    def build_fits(parent):
        tk.Label(parent, text="⛔1 ●●● 250/1312").pack(padx=20, pady=20)

    check("ami kifer, arra NEM jelez levagast",
          up.truncated(up.inspect(build_fits, size=(400, 80))) == [])

    # A meg nem elrendezett (1x1) widget nem szamit levagasnak — kulonben minden
    # futas tele lenne hamis riasztassal.
    check("az 1x1 meretu (meg nem elrendezett) elem nem hamis riasztas",
          all(n["w"] > 1 and n["h"] > 1 for n in up.truncated(nodes)))

    # ══ 2. Sor-magassag elteres ════════════════════════════════════════════
    # Az 1. korben a Button magasabb volt a Label-nel (bd/highlightthickness/
    # padx/pady nelkul), amitol a tabla "ugralt".
    def build_mixed(parent):
        row = tk.Frame(parent)
        row.pack()
        tk.Label(row, text="cella").pack(side="left")
        tk.Button(row, text="gomb").pack(side="left")       # magasabb!

    hg = up.height_groups(up.inspect(build_mixed, size=(400, 80)),
                          cls=None)
    _row_items = [n for n in up.inspect(build_mixed, size=(400, 80))
                  if n["cls"] in ("Label", "Button")]
    _heights = {n["h"] for n in _row_items}
    check("a nyers Button es Label magassaga ELTER (ezert ugralt a tabla)",
          len(_heights) > 1, f"magassagok: {sorted(_heights)}")

    # HELYESBITES az 1. kor jegyzetehez: a bd/padx/pady/highlightthickness=0
    # recept NEM ELEG. Merve: a Button a betu sormagassagan FELUL meg ~6 px-t tesz
    # hozza (Windows-specifikus belso terkoz), amit a pady=0 nem fog meg. A
    # height=1 / relief=flat / overrelief sem segit.
    def build_zeroed(parent):
        row = tk.Frame(parent)
        row.pack()
        Z = dict(bd=0, padx=0, pady=0, highlightthickness=0)
        tk.Label(row, text="cella", **Z).pack(side="left")
        tk.Button(row, text="gomb", **Z).pack(side="left")

    _z = {n["h"] for n in up.inspect(build_zeroed, size=(400, 80))
          if n["cls"] in ("Label", "Button")}
    check("a nullazott Button MEG MINDIG magasabb (a jegyzet receptje keves)",
          len(_z) > 1, f"magassagok: {sorted(_z)}")

    # A MUKODO recept: kattinthato Label (al-gomb) — pontosan egyezo magassag.
    def build_fake_button(parent):
        row = tk.Frame(parent)
        row.pack()
        Z = dict(bd=0, padx=0, pady=0, highlightthickness=0)
        tk.Label(row, text="cella", **Z).pack(side="left")
        b = tk.Label(row, text="gomb", cursor="hand2", **Z)
        b.bind("<Button-1>", lambda _e: None)
        b.pack(side="left")

    _fb = {n["h"] for n in up.inspect(build_fake_button, size=(400, 80))
           if n["cls"] == "Label"}
    check("kattinthato Label (al-gomb) -> EGYFORMA magassag",
          len(_fb) == 1, f"magassagok: {sorted(_fb)}")

    # ══ 3. A glifa-szelesseg csapdaja ══════════════════════════════════════
    # Karakterszambol becsulni HIBA: a blokk-glifak es a tilto jel SZELESEBBEK,
    # mint a szamjegyek — ettol csordult tul a cella az 1. korben.
    _r = tk.Tk()
    try:
        mono = tkfont.Font(family="Consolas", size=11)
        w_digits = up.text_width("000", mono)
        w_blocks = up.text_width("▮▨▯", mono)
        w_stop = up.text_width("⛔", mono)
        w_zero = up.text_width("0", mono)
        check("harom blokk-glifa SZELESEBB, mint harom szamjegy",
              w_blocks > w_digits, f"{w_blocks} > {w_digits}")
        check("a tilto jel szelesebb, mint egy szamjegy",
              w_stop > w_zero, f"{w_stop} > {w_zero}")
        check("a meres pozitiv szamot ad", w_digits > 0)
    finally:
        _r.destroy()

    # ══ 4. Az inspect szerzodese ═══════════════════════════════════════════
    check("az inspect a widget-fat adja vissza", len(nodes) >= 2)
    check("minden csomopontnak van osztalya es merete",
          all({"cls", "w", "h", "req_w", "req_h"} <= set(n) for n in nodes))
    check("truncated(None) ures", up.truncated(None) == [])
    check("height_groups(None) ures", up.height_groups(None) == {})

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

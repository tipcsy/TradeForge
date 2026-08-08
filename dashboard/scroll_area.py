"""
GÖRGETHETŐ TARTALOM-TERÜLET — közös váz a beállító ablakokhoz.

Ugyanaz a gond mindenhol: az ablak alján rögzített gombsor (Mentés/Mégse) alatt
a tartalom lelóghat, ha sok a paraméter vagy kicsi a képernyő. A megoldás nem az
ablak nagyobbra vétele, hanem hogy a TARTALOM görgessen, a gombsor pedig maradjon.

Eddig ez az `instrument_dialog`-ban lakott privát függvényként, így a kapu-ablak
nem kapta meg — a Lendületnek nyolc paramétere van, és a „Hatás stratégiánként”
blokk némán levágódott az ablak alján. Egy helyen definiálva mindkettő ugyanúgy
viselkedik, és a következő ablak ingyen kapja meg.

⚠ AZ EGÉRGÖRGŐ A TOPLEVEL-RE KÖTŐDIK, nem a vászonra: a Tk `bindtags` miatt
csak így működik a gyerek-widgetek (beviteli mezők, legördülők) FÖLÖTT is. Ennek
az ára, hogy egy ablakban több görgethető terület is hallja ugyanazt az eseményt
— ezért nézi meg a kezelő, hogy éppen LÁTSZIK-e (`winfo_ismapped`). Fülekre
bontott ablakban enélkül a leírás görgetése a háttérben elmozdítaná a beállítás-
lapot is, és visszaváltáskor máshol állna, mint ahol hagytuk.
"""

from __future__ import annotations

import tkinter as tk

from dashboard.theme import BG


def scrollable(parent):
    """`(holder, inner, canvas)` — a hívó a `holder`-t csomagolja, az `inner`-be épít."""
    holder = tk.Frame(parent, bg=BG)
    canvas = tk.Canvas(holder, bg=BG, highlightthickness=0)
    vsb = tk.Scrollbar(holder, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    inner = tk.Frame(canvas, bg=BG)
    win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>",
               lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    # A tartalom szélessége kövesse az ablakot (különben nem nyúlnak a mezők)
    canvas.bind("<Configure>",
                lambda e: canvas.itemconfigure(win_id, width=e.width))

    def _wheel(e):
        if not canvas.winfo_ismapped():   # másik fül van elöl — nem a miénk
            return
        # Csak ha van mit görgetni (különben „ugrik" a rövid tartalom)
        lo, hi = canvas.yview()
        if lo > 0.0 or hi < 1.0:
            canvas.yview_scroll(int(-e.delta / 120), "units")

    parent.winfo_toplevel().bind("<MouseWheel>", _wheel, add="+")
    return holder, inner, canvas

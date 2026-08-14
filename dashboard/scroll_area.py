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


def scrollable(parent, horizontal: bool = False):
    """`(holder, inner, canvas)` — a hívó a `holder`-t csomagolja, az `inner`-be épít.

    `horizontal=True` esetén a TELJES OLDAL vízszintesen is görgethető, és a
    csúszka CSAK AKKOR jelenik meg, ha tényleg van mit görgetni.

    ⚠ Miért az OLDAL, és nem az egyes szakaszok. Egy szakaszra rakott vízszintes
    csúszka azt a látszatot kelti, hogy csak ott lóg ki valami — holott a
    szomszéd szakasz épp úgy levágódhat, csak nincs csúszkája. Egy sáv az oldal
    alján egy kérdést old meg egy helyen.

    ⚠ ÉS CSAK HA KELL. Egy állandóan ott ülő, végig kihasználatlan csúszka
    ugyanaz a zaj, mint egy mindig látszó „nincs hiba" felirat: elveszi a helyet,
    és megtanítja a szemet, hogy ne nézzen oda.
    """
    holder = tk.Frame(parent, bg=BG)
    canvas = tk.Canvas(holder, bg=BG, highlightthickness=0)
    vsb = tk.Scrollbar(holder, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    hsb = None
    if horizontal:
        hsb = tk.Scrollbar(holder, orient="horizontal", command=canvas.xview)
        canvas.configure(xscrollcommand=hsb.set)
    canvas.pack(side="left", fill="both", expand=True)

    inner = tk.Frame(canvas, bg=BG)
    win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

    def _fit(_e=None):
        w = canvas.winfo_width()
        # A tartalom szélessége kövesse az ablakot (különben nem nyúlnak a mezők).
        # Vízszintes görgetésnél viszont a SAJÁT igényét is megkapja, ha az több —
        # enélkül a Tk visszaszorítaná az ablakra, és nem volna mit görgetni.
        need = inner.winfo_reqwidth()
        canvas.itemconfigure(win_id, width=(max(w, need) if horizontal else w))
        canvas.configure(scrollregion=canvas.bbox("all"))
        if hsb is not None:
            if need > w + 1:
                if not hsb.winfo_manager():
                    # ⚠ `before=canvas`: a csomagolási SORREND számít. A canvas
                    # `expand=True`, tehát ha utána kerülne be, nem maradna neki
                    # hely — a csúszka meglenne, de láthatatlanul.
                    hsb.pack(side="bottom", fill="x", before=canvas)
            elif hsb.winfo_manager():
                hsb.pack_forget()

    inner.bind("<Configure>", _fit)
    canvas.bind("<Configure>", _fit)

    def _wheel(e):
        if not canvas.winfo_ismapped():   # másik fül van elöl — nem a miénk
            return
        # Csak ha van mit görgetni (különben „ugrik" a rövid tartalom)
        lo, hi = canvas.yview()
        if lo > 0.0 or hi < 1.0:
            canvas.yview_scroll(int(-e.delta / 120), "units")

    def _wheel_x(e):
        """Shift+görgő = vízszintes — a Windows-on megszokott mozdulat."""
        if hsb is None or not canvas.winfo_ismapped():
            return
        lo, hi = canvas.xview()
        if lo > 0.0 or hi < 1.0:
            canvas.xview_scroll(int(-e.delta / 120), "units")

    top = parent.winfo_toplevel()
    top.bind("<MouseWheel>", _wheel, add="+")
    if horizontal:
        top.bind("<Shift-MouseWheel>", _wheel_x, add="+")
    return holder, inner, canvas

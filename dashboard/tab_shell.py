"""
BAL OLDALI FÜLEK — közös váz a beállító ablakokhoz.

A felhasználó terve szerint (Obsidian, Változtatások/2026-08-07) a beállítások
bal oldali füleken sorakoznak, és ami eddig KÜLÖN ABLAKBAN nyílt (a stratégia
leírása), az ugyanannak a formnak egy lapja legyen. Három hely használja:

    ⚙ Beállítások          Json · Kapuk · Stratégiák
    Kapu beállító ablak    Beállítás · Leírás
    Stratégia-paraméterek  Paraméter · Leírás

MIÉRT NEM `ttk.Notebook`. Annak a bal oldali fülei (`tabposition="wn"`)
Windowson ELFORGATOTT feliratot adnak, ami olvashatatlan. Saját gombsáv +
tartalom-keret: teljes kontroll, nulla mellékhatás — ugyanaz a döntés, mint a
gördítősávnál és a táblánál.

⚠ A CSOMAGOLÁSI SORREND itt működés, nem stílus. A hívónak a gombsorát ELŐBB
kell `side="bottom"`-mal becsomagolnia, mint ezt a vázat: a `pack` a hívás
sorrendjében oszt helyet, tehát ha a tartalom `expand=True`-val előbb elviszi a
területet, a gombok kis ablaknál KISZORULNAK. (Ez élesben elő is fordult: a
Mentés csak széles ablaknál látszott.)
"""

from __future__ import annotations

import tkinter as tk

from dashboard import theme as _theme
from dashboard.theme import BG, BG_HEADER, FG_WHITE, FG_GRAY


class TabShell:
    """`names`: a fülek feliratai, sorrendben. A lapok üres keretek — a hívó
    tölti fel őket (`shell.page("Leírás")`).

    `on_show(name)`: opcionális, a lapváltáskor fut. A LUSTA feltöltéshez kell:
    egy Markdown-leírást fölösleges megjeleníteni, amíg rá sem néztek.

    `notify_every_show`: alapból HAMIS — az `on_show` laponként EGYSZER fut
    (lusta feltöltés). Igazra állítva MINDEN megjelenítéskor fut.

    ⚠ Miért kell a választás: van lap, amit egyszer felépíteni elég (statikus
    leírás), és van, aminek a tartalma KÖZBEN elavul — futó optimalizálás alatt
    frissülő eredmény-CSV, a pár állapota, vagy a másik lapon átírt paraméterek.
    Az utóbbiaknál a laponként-egyszer szemantika azt jelentené, hogy a felület
    MAGABIZTOSAN elavult adatot mutat: a felhasználó visszakattint „megnézni,
    hogy áll", és ugyanazt látja, mint tíz perce. Ilyenkor a hívó dönt, mit épít
    újra — de ahhoz értesülnie kell."""

    def __init__(self, parent, names, width: int = 130, on_show=None,
                 notify_every_show: bool = False):
        self._f = _theme.fonts()
        self._on_show = on_show
        self._pages: dict = {}
        self._btns: dict = {}
        self._shown: set = set()
        self._always = bool(notify_every_show)
        self.current: str = ""

        self.frame = tk.Frame(parent, bg=BG)
        self.frame.pack(fill="both", expand=True)
        self._tabs = tk.Frame(self.frame, bg=BG_HEADER, width=width)
        self._tabs.pack(side="left", fill="y")
        self._tabs.pack_propagate(False)
        self._body = tk.Frame(self.frame, bg=BG)
        self._body.pack(side="left", fill="both", expand=True)

        for name in names:
            self._pages[name] = tk.Frame(self._body, bg=BG)
            lbl = tk.Label(self._tabs, text=name, bg=BG_HEADER, fg=FG_GRAY,
                           font=self._f["small"], anchor="w", padx=12, pady=8,
                           cursor="hand2")
            lbl.pack(fill="x")
            lbl.bind("<Button-1>", lambda _e, n=name: self.show(n))
            self._btns[name] = lbl
        if names:
            self.show(list(names)[0])

    def page(self, name) -> tk.Frame:
        """A lap kerete — ide épít a hívó."""
        return self._pages[name]

    def show(self, name):
        """Lapváltás. ⚠ A lapok NEM semmisülnek meg, csak kicsomagolódnak — egy
        korábbi változatban a mentés-ág egy újrakötött néven a LAPOT törölte az
        ABLAK helyett, és utána bármelyik fülre kattintva `bad window path name`
        jött."""
        for n, pg in self._pages.items():
            pg.pack_forget()
            self._btns[n].config(bg=BG_HEADER, fg=FG_GRAY)
        self._pages[name].pack(fill="both", expand=True)
        self._btns[name].config(bg=BG, fg=FG_WHITE)
        self.current = name
        if self._on_show is not None and (self._always or name not in self._shown):
            self._shown.add(name)
            self._on_show(name)

    def names(self) -> list:
        return list(self._pages)

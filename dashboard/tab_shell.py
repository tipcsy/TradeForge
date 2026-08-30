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
    """`names`: a fülek, sorrendben — `(kód, felirat)` párok VAGY sima szövegek.

    ⚠ A KÓD ÉS A FELIRAT KÜLÖNVÁLIK. A lapot a hívó a KÓDJÁN kéri
    (`shell.page("docs")`), a felhasználó pedig a FELIRATOT látja („Leírás" /
    „Description"). Korábban a kettő ugyanaz a magyar szöveg volt, tehát az
    `on_show` ágai (`if name == "Leírás"`) a fordítás után SOSEM tüzeltek volna:
    a lap üresen maradt volna, hibaüzenet nélkül — a felhasználó annyit lát, hogy
    egy fül nem csinál semmit.

    Sima szöveget adva a kód és a felirat ugyanaz (visszafelé kompatibilis, a
    technikai neveknek — „MT4", „MT5" — pont ez kell).

    `on_show(kód)`: opcionális, a lapváltáskor fut. A LUSTA feltöltéshez kell:
    egy Markdown-leírást fölösleges megjeleníteni, amíg rá sem néztek.

    `side`: a fülsáv helye — `"left"` (alap) vagy `"top"`. A felső elrendezés
    ALFÜLEKHEZ való: egy bal oldali fülsávon BELÜL egy másik bal oldali sáv két
    függőleges oszlopot adna egymás mellett, ami elveszi a tartalom helyét és
    nehéz eldönteni, melyik szint melyik.

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
                 notify_every_show: bool = False, side: str = "left"):
        self._f = _theme.fonts()
        self._on_show = on_show
        self._pages: dict = {}
        self._btns: dict = {}
        self._shown: set = set()
        self._always = bool(notify_every_show)
        self.current: str = ""

        self._side = "top" if str(side).lower() == "top" else "left"
        self.frame = tk.Frame(parent, bg=BG)
        self.frame.pack(fill="both", expand=True)
        if self._side == "top":
            self._tabs = tk.Frame(self.frame, bg=BG_HEADER)
            self._tabs.pack(side="top", fill="x")
        else:
            self._tabs = tk.Frame(self.frame, bg=BG_HEADER, width=width)
            self._tabs.pack(side="left", fill="y")
            self._tabs.pack_propagate(False)
        self._body = tk.Frame(self.frame, bg=BG)
        self._body.pack(side="top" if self._side == "top" else "left",
                        fill="both", expand=True)

        for _item in names:
            # `(kód, felirat)` vagy sima szöveg (ilyenkor a kettő ugyanaz).
            name, text = _item if isinstance(_item, (tuple, list)) else (_item, _item)
            self._pages[name] = tk.Frame(self._body, bg=BG)
            lbl = tk.Label(self._tabs, text=text, bg=BG_HEADER, fg=FG_GRAY,
                           font=self._f["small"],
                           anchor="center" if self._side == "top" else "w",
                           padx=16 if self._side == "top" else 12, pady=8,
                           cursor="hand2")
            if self._side == "top":
                lbl.pack(side="left")
            else:
                lbl.pack(fill="x")
            lbl.bind("<Button-1>", lambda _e, n=name: self.show(n))
            self._btns[name] = lbl
        if self._pages:
            self.show(next(iter(self._pages)))

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

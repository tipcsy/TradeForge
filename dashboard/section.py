"""ÖSSZECSUKHATÓ SZAKASZ — teljes szélességű blokk, összegző fejléccel.

A paraméter-ablak látványterve szerint az oldal egymás alatti, teljes szélességű
szakaszokból áll: kereskedési órák · kapuk · paraméterek · kockázatcsökkentés ·
futtatás · eredmény. Napi munkában legfeljebb kettő-három kell nyitva.

⚠ A BECSUKÁS NEM REJTHET EL INFORMÁCIÓT, csak a SZERKESZTÉST. Ezért a fejléc
összegzést mutat: „kereskedési órák · 08–17 · 10 óra engedve". Enélkül a
becsukott szakasz azt a kérdést szülné, amit az egész átalakítás megszüntetni
próbál: „most akkor mi van beállítva?" — és a felhasználónak ki kellene nyitnia,
hogy megtudja. Az összegzőt a hívó adja, mert csak ő tudja, mi a lényeg.

⚠ AZ ÁLLAPOT MEGJEGYZŐDIK (pár + stratégia szinten). Egy ablak, amit minden
megnyitáskor újra szét kell csukdosni, pár nap alatt elveszi a kedvet a
használatától — és a becsukás épp azért van, hogy a napi nézet gyors legyen.

TISZTA VÁZ: nem tud semmit a tartalomról. A hívó a `body`-ba épít, és ha az
összegzés változik, hívja a `set_summary`-t.
"""
from __future__ import annotations

import tkinter as tk

from dashboard.theme import (BG, BG_HEADER, FG_WHITE, FG_GRAY, FG_GRAY_DIM)

# A fejléc nyíl-jelei. Ugyanaz a két glifa, amit a tábla-fejléc használ az
# összecsukható stratégia-blokkokhoz — a felhasználó ugyanazt a mozdulatot
# tanulja meg egyszer.
OPEN, CLOSED = "▼", "▶"


class Section:
    """Egy összecsukható szakasz. A tartalom a `.body` keretbe megy."""

    __slots__ = ("key", "frame", "head", "_arrow", "_title", "_sum", "body",
                 "_open", "_on_toggle", "_fonts")

    def __init__(self, parent, key: str, title: str, fonts: dict,
                 open_: bool = True, on_toggle=None, summary: str = ""):
        self.key = key
        self._fonts = fonts
        self._open = bool(open_)
        self._on_toggle = on_toggle

        self.frame = tk.Frame(parent, bg=BG)
        self.head = tk.Frame(self.frame, bg=BG_HEADER, cursor="hand2")
        self.head.pack(fill="x")
        self._arrow = tk.Label(self.head, text=(OPEN if self._open else CLOSED),
                               bg=BG_HEADER, fg=FG_GRAY, font=fonts["small"],
                               cursor="hand2")
        self._arrow.pack(side="left", padx=(8, 4), pady=3)
        self._title = tk.Label(self.head, text=title, bg=BG_HEADER, fg=FG_WHITE,
                               font=fonts["header"], cursor="hand2")
        self._title.pack(side="left")
        self._sum = tk.Label(self.head, text=summary, bg=BG_HEADER,
                             fg=FG_GRAY_DIM, font=fonts["small"], cursor="hand2",
                             anchor="w")
        self._sum.pack(side="left", padx=(10, 8))

        self.body = tk.Frame(self.frame, bg=BG)
        if self._open:
            self.body.pack(fill="both", expand=True)

        # ⚠ A KATTINTÁS A FEJLÉC MINDEN RÉSZÉN fog: a nyíl, a cím és az
        # összegzés is. Ha csak a nyíl volna kattintható, egy 12 px-es célpontot
        # kellene eltalálni — a fejléc egésze a természetes gomb.
        for w in (self.head, self._arrow, self._title, self._sum):
            w.bind("<Button-1>", lambda _e: self.toggle())

    # ── állapot ────────────────────────────────────────────────────────────
    @property
    def is_open(self) -> bool:
        return self._open

    def set_open(self, value: bool, notify: bool = True) -> None:
        value = bool(value)
        if value == self._open:
            return
        self._open = value
        self._arrow.config(text=(OPEN if value else CLOSED))
        if value:
            self.body.pack(fill="both", expand=True)
        else:
            self.body.pack_forget()
        if notify and self._on_toggle:
            self._on_toggle(self.key, value)

    def toggle(self) -> None:
        self.set_open(not self._open)

    def set_summary(self, text: str) -> None:
        """A fejléc összegzése — a becsukott szakasz EGYETLEN információja."""
        try:
            self._sum.config(text=text or "")
        except tk.TclError:
            pass

    def set_title(self, text: str) -> None:
        try:
            self._title.config(text=text)
        except tk.TclError:
            pass

    def pack(self, **kw):
        """A szakasz elhelyezése. Alapból teljes szélesség, kis függőleges réssel."""
        kw.setdefault("fill", "x")
        kw.setdefault("pady", (0, 6))
        self.frame.pack(**kw)
        return self


# ---------------------------------------------------------------------------
# A becsukott/nyitott állapot MEGJEGYZÉSE
# ---------------------------------------------------------------------------
# A `core.backtest_prefs` tárában, `sec_` előtaggal — ugyanott, ahol az időszak
# és a nyitó összeg. Nem a config.json-ban: ez pusztán megjelenítési kényelem,
# a motor viselkedésére nincs hatása, és a config csak az ELTÉRÉST rögzítheti.

_PREFIX = "sec_"


def load_open(symbol: str, strategy: str, defaults: dict) -> dict:
    """`{kulcs: nyitva?}` — a mentett állapot, hiányzóra az alapértelmezés."""
    try:
        from core import backtest_prefs as _bp
        saved = _bp.get(symbol, strategy) or {}
    except Exception:
        saved = {}
    out = {}
    for key, dflt in (defaults or {}).items():
        v = saved.get(_PREFIX + key)
        out[key] = bool(dflt) if v is None else bool(v)
    return out


def save_open(symbol: str, strategy: str, key: str, value: bool) -> None:
    try:
        from core import backtest_prefs as _bp
        _bp.save(symbol, strategy, **{_PREFIX + key: bool(value)})
    except Exception:
        pass

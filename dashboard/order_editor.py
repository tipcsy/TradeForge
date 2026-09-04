"""
KÉT LISTÁS rendező: „Kikapcsolt" ↔ „Bekapcsolt" + sorrend.

A Beállítások „Kapuk" és „Stratégiák" füle ugyanezt a vezérlőt használja — a két
kérdés ugyanaz („mi látszik, milyen sorrendben"), csak más a készlet.

MIÉRT KÉT LISTA ÉS NEM JELÖLŐNÉGYZETEK. A jelölőnégyzet a ki/be-t megmutatja, a
SORRENDET viszont nem — ahhoz külön fel/le gombok kellenének minden sor mellé.
Két listával a sorrend ott van, ahol nézed: a jobb oldali lista MAGA a sorrend.
"""

from __future__ import annotations

import tkinter as tk

from dashboard import theme as _theme
from dashboard.theme import (BG, BG_HEADER, FG_WHITE, FG_GRAY, FG_GRAY_DIM,
                             FG_BLUE, BTN_DIS_BG, BTN_DIS_FG)


class OrderEditor:
    """`labels`: `{kulcs: felirat}`. `enabled`: a bekapcsoltak kulcsai, SORRENDBEN.

    `get()` a bekapcsoltak listáját adja vissza (sorrendben). A vezérlő nem ment
    és nem olvas configot — az a hívó dolga, hogy a mentés EGY helyen történjen."""

    def __init__(self, parent, labels: dict, enabled, title_off="Kikapcsolt",
                 title_on="Bekapcsolt", note: str = ""):
        self._labels = dict(labels)
        f = _theme.fonts()
        self.frame = tk.Frame(parent, bg=BG)
        if note:
            tk.Label(self.frame, text=note, bg=BG, fg=FG_GRAY, font=f["small"],
                     justify="left", wraplength=520).pack(anchor="w", pady=(0, 8))

        body = tk.Frame(self.frame, bg=BG)
        body.pack(fill="both", expand=True)

        self._off = self._make_list(body, title_off, "left")
        mid = tk.Frame(body, bg=BG)
        mid.pack(side="left", padx=10)
        self._on = self._make_list(body, title_on, "left")

        for txt, cmd in (("→", self._enable), ("←", self._disable),
                         ("", None), ("▲", self._up), ("▼", self._down)):
            if cmd is None:
                tk.Frame(mid, bg=BG, height=14).pack()
                continue
            tk.Button(mid, text=txt, command=cmd, bg=BG_HEADER, fg=FG_WHITE,
                      font=f["small"], bd=0, width=3,
                      activebackground=BG).pack(pady=2)

        on = [k for k in (enabled or []) if k in self._labels]
        for k in on:
            self._on.insert("end", self._labels[k])
        for k in self._labels:
            if k not in on:
                self._off.insert("end", self._labels[k])
        self._on_keys = list(on)
        self._off_keys = [k for k in self._labels if k not in on]

    def _make_list(self, parent, title, side):
        f = _theme.fonts()
        box = tk.Frame(parent, bg=BG)
        box.pack(side=side, fill="both", expand=True)
        tk.Label(box, text=title, bg=BG, fg=FG_BLUE, font=f["small"],
                 anchor="w").pack(anchor="w")
        lb = tk.Listbox(box, bg=BG_HEADER, fg=FG_WHITE, font=f["small"],
                        selectbackground=FG_BLUE, selectforeground=FG_WHITE,
                        highlightthickness=0, bd=0, activestyle="none",
                        exportselection=False, height=8)
        lb.pack(fill="both", expand=True, pady=(2, 0))
        return lb

    # ── Mozgatás ─────────────────────────────────────────────────────────
    def _move(self, src, dst, src_keys, dst_keys):
        sel = src.curselection()
        if not sel:
            return
        i = sel[0]
        key = src_keys.pop(i)
        src.delete(i)
        dst_keys.append(key)
        dst.insert("end", self._labels[key])
        dst.selection_clear(0, "end")
        dst.selection_set("end")

    def _enable(self):
        self._move(self._off, self._on, self._off_keys, self._on_keys)

    def _disable(self):
        self._move(self._on, self._off, self._on_keys, self._off_keys)

    def _shift(self, delta: int):
        sel = self._on.curselection()
        if not sel:
            return
        i = sel[0]
        j = i + delta
        if not (0 <= j < len(self._on_keys)):
            return
        self._on_keys[i], self._on_keys[j] = self._on_keys[j], self._on_keys[i]
        self._on.delete(0, "end")
        for k in self._on_keys:
            self._on.insert("end", self._labels[k])
        self._on.selection_set(j)

    def _up(self):
        self._shift(-1)

    def _down(self):
        self._shift(1)

    # ── Bővítés / lekérdezés ─────────────────────────────────────────────
    def add(self, key: str, label: str = "", enabled: bool = False) -> bool:
        """ÚJ tétel felvétele futás közben. `False`, ha már szerepel.

        ⚠ MIÉRT KELL. A `.tfs` telepítése közben új stratégia kerül a gépre. Ha
        a lista csak az ablak MEGNYITÁSAKOR épülne fel, a felhasználó a sikeres
        telepítés után egy változatlan listát látna — vagyis pontosan azt, hogy
        „nem történt semmi". Az újat ALAPBÓL a kikapcsolt oldalra tesszük: a
        gépre kerülés és a használatba vétel két különböző döntés."""
        if key in self._labels:
            return False
        self._labels[key] = label or key
        if enabled:
            self._on_keys.append(key)
            self._on.insert("end", self._labels[key])
        else:
            self._off_keys.append(key)
            self._off.insert("end", self._labels[key])
        return True

    def selected(self) -> str:
        """A ÉPPEN kijelölt tétel kulcsa (bármelyik oldalon), vagy `""`."""
        for lb, keys in ((self._on, self._on_keys), (self._off, self._off_keys)):
            sel = lb.curselection()
            if sel and sel[0] < len(keys):
                return keys[sel[0]]
        return ""

    # ── Eredmény ─────────────────────────────────────────────────────────
    def get(self) -> list:
        """A BEKAPCSOLTAK kulcsai, a beállított sorrendben."""
        return list(self._on_keys)

    def disabled(self) -> list:
        return list(self._off_keys)

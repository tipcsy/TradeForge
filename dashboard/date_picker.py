"""Könnyű naptár-választó popup (tkinter, KÜLSŐ FÜGGŐSÉG NÉLKÜL).

A Backtest-ablak Időszak mezőihez: a 📅 gomb nyitja, a kiválasztott napot
`YYYY-MM-DD` formában adja vissza az `on_pick(str)` visszahíváson. Opcionális
`lo`/`hi` (datetime.date) tartomány: a rajta kívüli napok halványak és nem
választhatók (a letöltött history-hoz igazítható). A stdlib `calendar` modulra
épül, hétfő-kezdetű, magyar hónap/nap feliratokkal — semmi extra csomag."""
from __future__ import annotations

import calendar
from datetime import date

import tkinter as tk

from dashboard.theme import (BG, BG_HEADER, FG_WHITE, FG_GRAY, FG_GRAY_DIM,
                             FG_BLUE, BTN_BT_BG, BTN_BT_FG)

_MONTHS_HU = ["", "január", "február", "március", "április", "május", "június",
              "július", "augusztus", "szeptember", "október", "november", "december"]
_WD_HU = ["H", "K", "Sze", "Cs", "P", "Szo", "V"]   # hétfő-kezdet


class CalendarPopup(tk.Toplevel):
    """Kis, modális naptár-popup egy dátum kiválasztásához."""

    def __init__(self, parent, anchor=None, initial=None, lo=None, hi=None,
                 on_pick=None, font=None):
        super().__init__(parent)
        self._parent  = parent
        self._on_pick = on_pick
        self._lo      = lo
        self._hi      = hi
        self._font    = font
        self._sel     = initial            # datetime.date | None
        self.title("Dátum")
        self.configure(bg=BG_HEADER)
        self.resizable(False, False)

        base = initial or hi or date.today()
        self._vy, self._vm = base.year, base.month

        header = tk.Frame(self, bg=BG_HEADER)
        header.pack(padx=8, pady=(8, 2))
        tk.Button(header, text="◀", width=2, bg=BTN_BT_BG, fg=BTN_BT_FG,
                  relief="flat", cursor="hand2", command=lambda: self._shift(-1),
                  **self._f()).pack(side="left")
        self._hdr = tk.Label(header, text="", width=18, bg=BG_HEADER, fg=FG_WHITE,
                             **self._f())
        self._hdr.pack(side="left", padx=4)
        tk.Button(header, text="▶", width=2, bg=BTN_BT_BG, fg=BTN_BT_FG,
                  relief="flat", cursor="hand2", command=lambda: self._shift(1),
                  **self._f()).pack(side="left")

        self._days = tk.Frame(self, bg=BG_HEADER)
        self._days.pack(padx=8, pady=(0, 8))
        self._render()

        try:
            self.transient(parent)
        except Exception:
            pass
        self._place(anchor)
        self.grab_set()
        self.bind("<Escape>", lambda e: self._close())
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _f(self, **kw):
        """Font-kiegészítő (ha kaptunk fontot, minden widget azt kapja)."""
        d = {"font": self._font} if self._font else {}
        d.update(kw)
        return d

    def _shift(self, d):
        m = self._vm + d
        self._vy += (m - 1) // 12
        self._vm  = (m - 1) % 12 + 1
        self._render()

    def _render(self):
        self._hdr.config(text=f"{self._vy}. {_MONTHS_HU[self._vm]}")
        for w in self._days.winfo_children():
            w.destroy()
        for i, wd in enumerate(_WD_HU):
            tk.Label(self._days, text=wd, width=3, bg=BG_HEADER, fg=FG_GRAY,
                     **self._f()).grid(row=0, column=i, padx=1, pady=1)
        cal = calendar.Calendar(firstweekday=0)   # hétfő
        for r, week in enumerate(cal.monthdayscalendar(self._vy, self._vm), start=1):
            for c, day in enumerate(week):
                if day == 0:
                    continue
                d = date(self._vy, self._vm, day)
                in_range = ((self._lo is None or d >= self._lo) and
                            (self._hi is None or d <= self._hi))
                is_sel = self._sel is not None and d == self._sel
                fg = (BG if is_sel else (FG_WHITE if in_range else FG_GRAY_DIM))
                bg = FG_BLUE if is_sel else BG_HEADER
                tk.Button(self._days, text=str(day), width=3, bg=bg, fg=fg,
                          relief="flat", cursor=("hand2" if in_range else "arrow"),
                          state=("normal" if in_range else "disabled"),
                          activebackground=FG_BLUE, activeforeground=BG,
                          command=lambda dd=d: self._pick(dd),
                          **self._f()).grid(row=r, column=c, padx=1, pady=1)

    def _pick(self, d):
        if self._on_pick:
            try:
                self._on_pick(d.strftime("%Y-%m-%d"))
            except Exception:
                pass
        self._close()

    def _place(self, anchor):
        try:
            self.update_idletasks()
            if anchor is not None:
                x = anchor.winfo_rootx()
                y = anchor.winfo_rooty() + anchor.winfo_height() + 2
            else:
                x = self._parent.winfo_rootx() + 60
                y = self._parent.winfo_rooty() + 60
            self.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

    def _close(self):
        try:
            self.grab_release()
        except Exception:
            pass
        try:
            self._parent.grab_set()   # a grabot visszaadjuk a szülő ablaknak
        except Exception:
            pass
        self.destroy()

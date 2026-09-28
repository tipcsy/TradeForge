"""TÁVOLI PARANCS a felületről egy külön processzben futó motornak — EGY helyen.

⚠ 0029, 4b/3 S3a (2026-09-28). A „háttérszálas küldés + kétlépcsős megerősítés
+ válasz a főszálra" logika a Brókerek fülben született (4b). A fő táblának
(Play/Stop, zárás) PONTOSAN ugyanez kell — ezért itt él egyszer. Két példányban
egy ilyen logika a projektben már elcsúszott (a duplikált trailing egyik
példánya NameError-t dobott, némán).

A szabályok:
  • a parancs a KÖZÖS parancs-rétegen fut a motorban (`core/engine_channel`);
  • ha a motor megerősítést kér, a felület rákérdez, és csak igen esetén küldi
    újra megerősítve;
  • a háttérszál SOSEM nyúl a Tk-hoz (a Tk nem szálbiztos — az első változat
    így csendben elvesztette a megerősítő kérdést): sorba tesz, a FŐSZÁL
    100 ms-enként kiveszi (`Pump`).
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk

from core import engine_channel as CH


class Pump:
    """A háttérszálak eredményei a FŐSZÁLON. Egy felületen egy példány."""

    def __init__(self, widget, period_ms: int = 100):
        self.widget = widget
        self.period_ms = period_ms
        self.q: queue.Queue = queue.Queue()
        self._fut()

    def put(self, fn):
        self.q.put(fn)

    def _fut(self):
        while True:
            try:
                fn = self.q.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except tk.TclError:
                pass
        try:
            self.widget.after(self.period_ms, self._fut)
        except tk.TclError:
            pass                                  # az ablak bezárult


def send(pump: Pump, profile, line: str, *, confirm, on_result,
         confirmed: bool = False, request=None) -> None:
    """Parancs a motornak, a kétlépcsős megerősítéssel. Azonnal visszatér.

    `confirm(szöveg) -> bool` — a felület kérdése (főszálon hívódik).
    `on_result(válasz | None, megszakítva: bool)` — főszálon; None: a motor
    nem válaszolt. `confirmed=True`: a felület MÁR rákérdezett (pl. zárás)."""
    request = request or CH.request

    def _vissza(r, megerositve):
        if r is not None and r.get("confirm") and not megerositve:
            if confirm(r["confirm"]):
                _hatter(True)
            else:
                on_result(r, True)
            return
        on_result(r, False)

    def _hatter(megerositve):
        def _fut():
            r = request(profile, line, megerositve)
            pump.put(lambda: _vissza(r, megerositve))
        threading.Thread(target=_fut, daemon=True, name="RemoteCmd").start()

    _hatter(bool(confirmed))

"""BRÓKEREK fül — a többi bróker motorja, CSAK OLVASÁS.

⚠ 0029 „Több bróker egyszerre", 4. lépés (2026-09-28). Minden további bróker
külön processzben fut (`python main.py console --broker <id>`), és a saját
állapotképét írja (`core/engine_status`). Ez a fül azokat olvassa és mutatja:
életjel (fut / áll / hibás / nincs adat), a bróker SZERVER-órája, egyenleg,
napi P&L, nyitott pozíciók.

⚠ CSAK OLVASÁS, SZÁNDÉKOSAN (Tibi döntése): nincs Play/Stop, nincs zárás —
a vezérlő csatorna a következő kör. A fül ezt ki is írja, hogy senki ne
keressen rajta gombot.

⚠ A fül csak akkor jön létre, ha egynél több bróker-profil van (egy brókernél
nincs mit mutatnia — a felhasználó kérése szerint egy brókernél a bróker-
jelölés sem látszik).

A fül NEM ismer MT5-öt: a profilokat és a képeket a hívó / a modul adja.
"""
from __future__ import annotations

import time
import tkinter as tk

from core import engine_status as ES
from core.i18n import t as _t
from dashboard import theme as _theme
from dashboard.scroll_area import scrollable
from dashboard.theme import (BG, BG_HEADER, BG_ROW_EVEN, BG_ROW_ODD, FG_GRAY,
                             FG_GREEN, FG_RED, FG_WHITE, FG_YELLOW)

FRISSITES_MS = 2000

_ALLAPOT_SZIN = {ES.FUT: FG_GREEN, ES.ALL: FG_GRAY, ES.HIBAS: FG_RED,
                 ES.NINCS: FG_YELLOW}


def _penz(v, cur=""):
    try:
        return f"{float(v):+,.2f} {cur}".strip()
    except (TypeError, ValueError):
        return "—"


def rows(profiles, now=None, reader=ES.read) -> list:
    """A fül adat-sorai (a teszt ezt nézi, a felület ezt rajzolja).
    `[{tag, name, account, health, clock, balance, daily, n_pos, age, positions}]`"""
    now = time.time() if now is None else now
    out = []
    for p in profiles:
        snap = reader(p)
        acc = (snap or {}).get("account") or {}
        cur = acc.get("currency", "")
        clock = ES.server_clock(snap, now)
        poz = (snap or {}).get("positions") or []
        out.append({
            "tag": p.tag, "name": p.name,
            "account": f"#{p.login} {p.server}".strip(),
            "health": ES.health(snap, now),
            "clock": clock.strftime("%H:%M") if clock else "—",
            "balance": (f"{float(acc['balance']):,.2f} {cur}".strip()
                        if acc.get("balance") is not None else "—"),
            "daily": _penz(acc.get("daily_pnl"), cur) if acc.get("daily_pnl") is not None else "—",
            "n_pos": len(poz),
            "age": (_t("age.sec", n=f"{max(0.0, now - float(snap['ts'])):.0f}")
                    if snap and snap.get("ts") else "—"),
            "positions": [dict(x, tag=p.tag) for x in poz],
        })
    return out


class BrokersTab:
    """`profiles_provider() -> [BrokerProfile]` — a MÁSIK (nem-otthoni) brókerek."""

    def __init__(self, parent, profiles_provider):
        self.parent = parent
        self._profiles = profiles_provider
        # Az utolsó JÓ kép brókerenként: egy átmeneti olvasási hiba (a motor épp
        # cseréli a fájlt) ne villantsa „nincs adat"-ra a sort. Nem hazudik: az
        # életjel KORA tovább nő, és egy tartós hiba így is „hibás"-ra vált.
        self._utolso: dict = {}
        self._build_ui()
        self._frissit()

    def _build_ui(self):
        f = _theme.fonts()
        self._mono, self._small, self._header = f["mono"], f["small"], f["header"]
        p = self.parent
        top = tk.Frame(p, bg=BG)
        top.pack(fill="x", padx=10, pady=(8, 2))
        tk.Label(top, text=_t("brokers.title"), bg=BG, fg=FG_WHITE,
                 font=self._header).pack(side="left")
        tk.Label(p, text=_t("brokers.readonly"), bg=BG, fg=FG_YELLOW,
                 font=self._small, anchor="w", justify="left").pack(
                     fill="x", padx=10, pady=(0, 6))

        self._fo_oszlop = [(_t("brokers.col.tag"), 5), (_t("brokers.col.broker"), 14),
                           (_t("brokers.col.account"), 26), (_t("brokers.col.state"), 12),
                           (_t("brokers.col.clock"), 9), (_t("brokers.col.balance"), 16),
                           (_t("brokers.col.daily"), 14), (_t("brokers.col.npos"), 6),
                           (_t("brokers.col.age"), 9)]
        self._fo = self._tabla(p, self._fo_oszlop, expand=False)

        tk.Label(p, text=_t("brokers.positions"), bg=BG, fg=FG_WHITE,
                 font=self._header, anchor="w").pack(fill="x", padx=10, pady=(10, 2))
        self._poz_oszlop = [(_t("brokers.col.tag"), 5), (_t("brokers.col.symbol"), 12),
                            (_t("brokers.col.dir"), 6), ("Lot", 7),
                            (_t("brokers.col.open"), 12), ("SL", 12), ("TP", 12),
                            (_t("brokers.col.pnl"), 12)]
        self._poz = self._tabla(p, self._poz_oszlop, expand=True)

    def _tabla(self, p, oszlopok, expand):
        fej = tk.Frame(p, bg=BG_HEADER)
        fej.pack(fill="x", padx=10)
        for cim, w in oszlopok:
            tk.Label(fej, text=cim, width=w, anchor="w", bg=BG_HEADER, fg=FG_GRAY,
                     font=self._header).pack(side="left", padx=2)
        if expand:
            holder, inner, _ = scrollable(p)
            holder.pack(fill="both", expand=True, padx=10, pady=(0, 8))
            return inner
        inner = tk.Frame(p, bg=BG)
        inner.pack(fill="x", padx=10)
        return inner

    def _sor(self, hova, i, cellak):
        bg = BG_ROW_EVEN if i % 2 == 0 else BG_ROW_ODD
        r = tk.Frame(hova, bg=bg)
        r.pack(fill="x")
        for szoveg, w, szin in cellak:
            tk.Label(r, text=szoveg, width=w, anchor="w", bg=bg, fg=szin,
                     font=self._mono).pack(side="left", padx=2)

    def _frissit(self):
        def _olvas(p):
            snap = ES.read(p)
            if snap is None and ES.path(p).exists():
                return self._utolso.get(p.id)
            self._utolso[p.id] = snap
            return snap
        try:
            adat = rows(self._profiles(), reader=_olvas)
        except Exception:
            adat = []
        for w in list(self._fo.winfo_children()) + list(self._poz.winfo_children()):
            w.destroy()
        for i, r in enumerate(adat):
            ertek = (r["tag"], r["name"], r["account"],
                     _t(f"brokers.state.{r['health']}"), r["clock"], r["balance"],
                     r["daily"], str(r["n_pos"]), r["age"])
            szinek = [FG_WHITE] * len(ertek)
            szinek[3] = _ALLAPOT_SZIN.get(r["health"], FG_GRAY)
            self._sor(self._fo, i, [(v, w, c) for v, (_, w), c
                                    in zip(ertek, self._fo_oszlop, szinek)])
        k = 0
        for r in adat:
            for x in r["positions"]:
                pnl = x.get("profit")
                ertek = (x["tag"], str(x.get("symbol", "")), str(x.get("type", "")),
                         f"{x.get('volume', '')}", f"{x.get('price_open', '')}",
                         f"{x.get('sl', '')}", f"{x.get('tp', '')}", _penz(pnl))
                szinek = [FG_WHITE] * len(ertek)
                try:
                    szinek[7] = FG_GREEN if float(pnl) >= 0 else FG_RED
                except (TypeError, ValueError):
                    pass
                self._sor(self._poz, k, [(v, w, c) for v, (_, w), c
                                         in zip(ertek, self._poz_oszlop, szinek)])
                k += 1
        try:
            self.parent.after(FRISSITES_MS, self._frissit)
        except tk.TclError:
            pass                                  # az ablak bezárult

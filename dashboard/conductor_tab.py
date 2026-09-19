"""KARMESTER fül — postaláda · mátrix · krónika.

Amit a terv (`docs/karmester.md`, 12. szakasz) kér, és amiért ez a fül a napi
használat helye lesz:

  • **Postaláda** — javaslat-kártyák: *mit, miért, mi a bizonyíték, mi a
    visszaút* → Elfogad / Elvet / Elhalaszt.
  • **Mátrix** — a `(instrumentum × stratégia)` rács EGY képen, cellánként az
    életciklus-fokkal és a legsúlyosabb lelettel. ⚠ Ez váltja ki azt, amit ma
    fejben kell tartani.
  • **Krónika** — mit tett a karmester, visszavonás gombbal.

── ⚠ A FÜL NEM TUD SEMMIT ─────────────────────────────────────────────────
Se házirendet, se küszöböt, se végrehajtást nem ismer: MINDEN a `conductor/`
csomagban van, és a döntés a KÖZÖS parancs-rétegen megy
(`conductor.actions` → `core.console_cmd`). A felület egyetlen dolga a
megjelenítés és a gombnyomás továbbítása. Egy „felületi másolat" a szabályokból
az első config-változásnál elcsúszna, és a fül MAGABIZTOSAN hazudna — a projekt
visszatérő hibaosztálya.

── ⚠ KÉT FRISSÍTÉS, KÉT KÖLTSÉG ───────────────────────────────────────────
A `refresh()` OLCSÓ: a postaláda-fájlt és a krónika végét olvassa. A
dashboard ciklusa 30 másodpercenként hívja — a házirendek újraszámolása
(egészségőr + életciklus, cellánként fájlokkal) itt mérhető lassulást okozna a
FELÜLET szálán, és a projekt ezt egyszer már megmérte (7,64 → 0,31 mp/kör).

A DRÁGA út (`reload()`) a házirendeket is lefuttatja, és a mátrixot is
újraépíti — ezt a „Frissítés" gomb és az első megnyitás indítja. A postaláda
attól még megtelik magától: a motor óránként beolvasztja a friss javaslatokat.
"""

from __future__ import annotations

import logging

import tkinter as tk

from core.i18n import t as _t

from dashboard import theme as _theme
from dashboard.scroll_area import scrollable
from dashboard.theme import (BG, BG_HEADER, BG_ROW_EVEN, BG_ROW_ODD,
                             BTN_DIS_BG, BTN_DIS_FG, BTN_PLAY_BG, BTN_PLAY_FG,
                             BTN_STOP_BG, BTN_STOP_FG, FG_GRAY, FG_GRAY_DIM,
                             FG_GREEN, FG_ORANGE, FG_RED, FG_WHITE, FG_YELLOW)

log = logging.getLogger(__name__)

MAX_KRONIKA = 40

# Életciklus-fok → szín. ⚠ A KÓD a kulcs, nem a felirat (nyelvváltás után egy
# magyar szóra kulcsolt tábla némán nem találna).
_FOK_SZIN = {"live": FG_GREEN, "paper": FG_YELLOW, "untuned": FG_ORANGE,
             "stopped": FG_GRAY_DIM}
_SEV_SZIN = {"risk": FG_RED, "warn": FG_YELLOW, "info": FG_GRAY}


class ConductorTab:
    """`ctx_provider() -> core.console_cmd.Context` — a KÖZÖS parancs-réteg
    környezete (a `DashboardWindow._cmd_ctx` adja).

    `on_changed()` — a hívó frissítse a saját tábláját: egy elfogadott javaslat
    megváltoztathatja a kötés-módot, és a sor azonnal mutassa.

    `confirm(szoveg, cim, parent) -> bool` — az IGEN/NEM kérdés. A dashboard a
    SAJÁT `_confirm`-jét adja be; ez a fül nem nyit közvetlenül modális ablakot
    (lásd ott a ⚠-t: egy programvezérelt kattintás örökre megállna rajta).
    """

    def __init__(self, parent, ctx_provider, on_changed=None, confirm=None):
        self.parent = parent
        self._ctx_provider = ctx_provider
        self._on_changed = on_changed or (lambda: None)
        self._confirm = confirm or self._sajat_confirm
        self._cellak: list = []          # a mátrix pillanatképei (drága)
        self._betoltve = False
        # ⚠ MIKOR RAJZOLUNK ÚJRA. A dashboard köre 30 mp-enként hív; ha minden
        # körben ledobnánk és újraépítenénk a kártyákat, a fül VILLOGNA, a
        # görgetés visszaugrana olvasás közben, és egy épp megnyomott gomb
        # kicsúszhatna az ujjad alól. Ezért a két állapotfájl MÓDOSULÁSI IDEJÉT
        # figyeljük (ugyanaz a minta, mint a Jelzések fülön a `trades.csv`-nél):
        # ha nem változott, nincs mit újrarajzolni.
        self._mtime = None
        self._build_ui()

    # ── felépítés ────────────────────────────────────────────────────────
    def _build_ui(self):
        f = _theme.fonts()
        self._small, self._header = f["small"], f["header"]
        p = self.parent

        top = tk.Frame(p, bg=BG)
        top.pack(fill="x", padx=10, pady=(8, 2))
        tk.Label(top, text=_t("cond.tab.title"), bg=BG, fg=FG_WHITE,
                 font=self._header).pack(side="left")
        tk.Button(top, text=_t("cond.tab.reload"), bg=BG_HEADER, fg=FG_WHITE,
                  relief="flat", font=self._small, padx=10,
                  command=self.reload).pack(side="right", padx=4)
        self._lbl_info = tk.Label(top, text="—", bg=BG, fg=FG_GRAY,
                                  font=self._small)
        self._lbl_info.pack(side="right", padx=8)

        # ⚠ AZ ÁRNYÉK-MÓD FIGYELMEZTETÉSE ÁLLANDÓ. A javaslatok nem hajtódnak
        # végre maguktól; enélkül a felhasználó azt hinné, a rendszer már lépett.
        tk.Label(p, text=_t("cond.tab.shadow"), bg=BG, fg=FG_GRAY_DIM,
                 font=self._small, wraplength=900, justify="left",
                 anchor="w").pack(fill="x", padx=10, pady=(0, 6))

        holder, self._inner, _ = scrollable(p)
        holder.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        self._box_inbox = tk.Frame(self._inner, bg=BG)
        self._box_inbox.pack(fill="x", pady=(0, 10))
        self._box_matrix = tk.Frame(self._inner, bg=BG)
        self._box_matrix.pack(fill="x", pady=(0, 10))
        self._box_kronika = tk.Frame(self._inner, bg=BG)
        self._box_kronika.pack(fill="x")

    # ── frissítés ────────────────────────────────────────────────────────
    def _allapot_ideje(self):
        """A postaláda és a krónika módosulási ideje — a rajzolás kapuja."""
        from conductor import paths as _p
        ki = []
        for ut in (_p.DIR / "inbox.json", _p.journal_file()):
            try:
                ki.append(ut.stat().st_mtime if ut.exists() else 0.0)
            except OSError:
                ki.append(0.0)
        return tuple(ki)

    def refresh(self, force: bool = False):
        """OLCSÓ frissítés: postaláda + krónika (fájlolvasás, nem házirend).

        ⚠ CSAK HA VÁLTOZOTT. Lásd a `_mtime` melletti indoklást: a felesleges
        újrarajzolás nem „csak" pazarlás, hanem használhatatlanná teszi a fület
        olvasás közben."""
        try:
            if not self._betoltve:
                # Az első megnyitáskor a mátrix is kell — utána csak gombra.
                self._betoltve = True
                self.reload()
                return
            most = self._allapot_ideje()
            if not force and most == self._mtime:
                return
            self._mtime = most
            self._rajzol_inbox()
            self._rajzol_kronika()
        except Exception:
            log.debug("Karmester fül: a frissítés elbukott", exc_info=True)

    def reload(self):
        """DRÁGA frissítés: a házirendek újrafuttatása + a mátrix újraépítése."""
        from conductor import inbox as _ib
        from conductor import snapshot as _snap
        from conductor.policies import health as _h, lifecycle as _lc

        ctx = self._ctx()
        if ctx is None:
            return
        try:
            _sof = lambda s: ctx.strategies_of(s) or []
            lel = _h.findings(ctx.cfg, strategies_of=_sof)
            jav = _lc.proposals(ctx.cfg, strategies_of=_sof, health_findings=lel)
            _ib.sync(ctx.cfg, jav)
            # A mátrixhoz a fokot és a legsúlyosabb leletet tesszük el.
            self._cellak = []
            for sn in _snap.cells(ctx.cfg, strategies_of=_sof):
                _c = [f for f in lel if f.get("symbol") == sn["symbol"]
                      and f.get("strategy") == sn["strategy"]]
                _c.sort(key=lambda f: _h.RANK.get(f.get("sev"), 9))
                self._cellak.append({"sn": sn, "fok": _lc.stage_of(sn),
                                     "lelet": _c[0] if _c else None,
                                     "leletek": len(_c)})
            self._lbl_info.config(text=_t("cond.tab.cells", n=len(self._cellak)))
        except Exception:
            log.warning("Karmester fül: az átvizsgálás elbukott", exc_info=True)
            self._lbl_info.config(text=_t("cond.tab.error"))
        self._mtime = self._allapot_ideje()
        self._rajzol_inbox()
        self._rajzol_matrix()
        self._rajzol_kronika()

    # ── postaláda ────────────────────────────────────────────────────────
    def _rajzol_inbox(self):
        from conductor import actions as _act
        from conductor import inbox as _ib

        for w in self._box_inbox.winfo_children():
            w.destroy()
        tetelek = _ib.items(_ib.PENDING)
        tk.Label(self._box_inbox,
                 text=_t("cond.tab.inbox", n=len(tetelek)), bg=BG, fg=FG_WHITE,
                 font=self._header, anchor="w").pack(fill="x", pady=(0, 4))
        if not tetelek:
            tk.Label(self._box_inbox, text=_t("conductor.inbox.none"), bg=BG,
                     fg=FG_GRAY_DIM, font=self._small,
                     anchor="w").pack(fill="x", padx=8)
            return

        for i, e in enumerate(tetelek):
            self._kartya(self._box_inbox, e, i,
                         vegrehajthato=_act.can_execute(e.get("action")))

    def _kartya(self, szulo, e, i, vegrehajthato: bool):
        """Egy javaslat-kártya: mit · miért · mi a bizonyíték · mit tehetsz."""
        bg = BG_ROW_EVEN if i % 2 == 0 else BG_ROW_ODD
        k = tk.Frame(szulo, bg=bg)
        k.pack(fill="x", pady=1)

        sor = tk.Frame(k, bg=bg)
        sor.pack(fill="x", padx=8, pady=(5, 0))
        # ⚠ A PÉNZT BEKAPCSOLÓ javaslat megjelölve — a terv szerint ez emberi
        # jóváhagyáshoz kötött, autonómia-szinttől függetlenül.
        jel = "⚠" if e.get("needs_human") else ("ℹ" if not vegrehajthato else "•")
        tk.Label(sor, text=jel, bg=bg,
                 fg=(FG_RED if e.get("needs_human") else FG_GRAY),
                 font=self._header, width=2).pack(side="left")
        tk.Label(sor, text=e.get("text") or e.get("code") or "", bg=bg,
                 fg=FG_WHITE, font=self._small, wraplength=620, justify="left",
                 anchor="w").pack(side="left", fill="x", expand=True)

        # ── A BIZONYÍTÉK. ⚠ Enélkül a kártya csak egy vélemény: a terv
        # invariánsa szerint indok nélkül nincs döntés.
        biz = e.get("evidence") or {}
        _reszek = [f"{kulcs}={biz[kulcs]}" for kulcs in
                   ("live_trades", "live_pf", "activity_ratio", "paper_signals",
                    "paper_days", "params_age_days")
                   if biz.get(kulcs) is not None]
        if _reszek:
            tk.Label(k, text="   " + " · ".join(_reszek), bg=bg, fg=FG_GRAY_DIM,
                     font=self._small, anchor="w").pack(fill="x", padx=8)

        gombok = tk.Frame(k, bg=bg)
        gombok.pack(fill="x", padx=8, pady=(2, 6))
        if vegrehajthato:
            tk.Button(gombok, text=_t("cond.tab.accept"), bg=BTN_PLAY_BG,
                      fg=BTN_PLAY_FG, relief="flat", font=self._small, padx=10,
                      command=lambda a=e["id"]: self._accept(a)).pack(side="left")
        else:
            # ⚠ NEM TESZÜNK KI GOMBOT, AMI NEM MŰKÖDIK. Az optimalizálás ma
            # csak az OPT gombbal indítható — egy halott „Elfogad" arra
            # tanítana, hogy a fül gombjai megbízhatatlanok.
            tk.Label(gombok, text=_t("cond.tab.advice_only"), bg=bg,
                     fg=FG_GRAY_DIM, font=self._small).pack(side="left")
        tk.Button(gombok, text=_t("cond.tab.reject"), bg=BTN_STOP_BG,
                  fg=BTN_STOP_FG, relief="flat", font=self._small, padx=10,
                  command=lambda a=e["id"]: self._dontes(a, "reject")).pack(
                      side="left", padx=6)
        tk.Button(gombok, text=_t("cond.tab.defer"), bg=BTN_DIS_BG,
                  fg=BTN_DIS_FG, relief="flat", font=self._small, padx=10,
                  command=lambda a=e["id"]: self._dontes(a, "defer")).pack(
                      side="left")
        tk.Label(gombok, text=f"[{e.get('id')}]", bg=bg, fg=FG_GRAY_DIM,
                 font=self._small).pack(side="right")

    # ── mátrix ───────────────────────────────────────────────────────────
    def _rajzol_matrix(self):
        for w in self._box_matrix.winfo_children():
            w.destroy()
        tk.Label(self._box_matrix, text=_t("cond.tab.matrix"), bg=BG,
                 fg=FG_WHITE, font=self._header,
                 anchor="w").pack(fill="x", pady=(0, 4))
        if not self._cellak:
            tk.Label(self._box_matrix, text=_t("cond.tab.matrix_empty"), bg=BG,
                     fg=FG_GRAY_DIM, font=self._small,
                     anchor="w").pack(fill="x", padx=8)
            return

        # oszlop = stratégia, sor = instrumentum (a 2.0 tábla elrendezése)
        strategiak = sorted({c["sn"]["strategy"] for c in self._cellak})
        szimbolumok = sorted({c["sn"]["symbol"] for c in self._cellak})
        racs = {(c["sn"]["symbol"], c["sn"]["strategy"]): c for c in self._cellak}

        tbl = tk.Frame(self._box_matrix, bg=BG)
        tbl.pack(fill="x", padx=8)
        tk.Label(tbl, text="", bg=BG, width=12).grid(row=0, column=0)
        for j, n in enumerate(strategiak, start=1):
            tk.Label(tbl, text=n, bg=BG, fg=FG_GRAY, font=self._small,
                     width=14, anchor="w").grid(row=0, column=j, padx=2)
        for i, sym in enumerate(szimbolumok, start=1):
            tk.Label(tbl, text=sym, bg=BG, fg=FG_WHITE, font=self._small,
                     width=12, anchor="w").grid(row=i, column=0, sticky="w")
            for j, n in enumerate(strategiak, start=1):
                c = racs.get((sym, n))
                if c is None:
                    tk.Label(tbl, text="–", bg=BG, fg=FG_GRAY_DIM,
                             font=self._small, width=14,
                             anchor="w").grid(row=i, column=j, padx=2)
                    continue
                # ⚠ A FOK ÉS A LELET EGY CELLÁBAN: a „fut"-ból önmagában nem
                # derül ki, hogy közben valami nincs rendben vele.
                cimke = _t("cond.tab.cell", stage=_t(f"cond.stage.{c['fok']}"),
                           marks=("⚠" * min(3, c.get("leletek") or 0)))
                tk.Label(tbl, text=cimke, bg=BG,
                         fg=_FOK_SZIN.get(c["fok"], FG_GRAY), font=self._small,
                         width=14, anchor="w").grid(row=i, column=j, padx=2)

    # ── krónika ──────────────────────────────────────────────────────────
    def _rajzol_kronika(self):
        from conductor import inbox as _ib
        from conductor import journal as _j

        for w in self._box_kronika.winfo_children():
            w.destroy()
        tk.Label(self._box_kronika, text=_t("cond.tab.journal"), bg=BG,
                 fg=FG_WHITE, font=self._header,
                 anchor="w").pack(fill="x", pady=(0, 4))
        sorok = _j.read(limit=MAX_KRONIKA)
        if not sorok:
            tk.Label(self._box_kronika, text=_t("cond.tab.journal_empty"), bg=BG,
                     fg=FG_GRAY_DIM, font=self._small,
                     anchor="w").pack(fill="x", padx=8)
            return
        for i, e in enumerate(sorok):
            bg = BG_ROW_EVEN if i % 2 == 0 else BG_ROW_ODD
            s = tk.Frame(self._box_kronika, bg=bg)
            s.pack(fill="x", pady=1)
            tk.Label(s, text=(e.get("ts") or "")[:16], bg=bg, fg=FG_GRAY_DIM,
                     font=self._small, width=17, anchor="w").pack(side="left", padx=6)
            tk.Label(s, text=(e.get("kind") or "")[:6], bg=bg, fg=FG_GRAY,
                     font=self._small, width=8, anchor="w").pack(side="left")
            tk.Label(s, text=e.get("text") or e.get("code") or "", bg=bg,
                     fg=_SEV_SZIN.get(e.get("sev"), FG_WHITE), font=self._small,
                     wraplength=560, justify="left",
                     anchor="w").pack(side="left", fill="x", expand=True)
            # ⚠ VISSZAVONÁS csak arra, ami TÉNYLEG megtörtént, és még
            # visszavonható (a tétel `accepted`, és van hozzá visszaút).
            _azon = (e.get("data") or {}).get("inbox_id")
            if e.get("kind") == _j.KIND_ACTION and _azon:
                _tetel = _ib.get(_azon)
                if (_tetel and _tetel.get("state") == _ib.ACCEPTED
                        and _tetel.get("undo")):
                    tk.Button(s, text=_t("cond.tab.undo"), bg=BG_HEADER,
                              fg=FG_WHITE, relief="flat", font=self._small,
                              padx=8,
                              command=lambda a=_azon: self._undo(a)).pack(
                                  side="right", padx=6)

    # ── döntések ─────────────────────────────────────────────────────────
    def _ctx(self):
        try:
            return self._ctx_provider()
        except Exception:
            log.warning("Karmester fül: a parancs-környezet nem áll elő",
                        exc_info=True)
            return None

    def _accept(self, azon: str):
        from conductor import actions as _act
        from conductor import inbox as _ib
        self._futtat(lambda ctx, megerosit: _act.apply(
            ctx, _ib.get(azon) or {}, confirmed=megerosit, by="human"))

    def _undo(self, azon: str):
        from conductor import actions as _act
        from conductor import inbox as _ib
        self._futtat(lambda ctx, megerosit: _act.undo(
            ctx, _ib.get(azon) or {}, confirmed=megerosit, by="human"))

    def _dontes(self, azon: str, mit: str):
        """Elvetés / elhalasztás — a KÖZÖS parancs-rétegen, mint a konzolon."""
        from core import console_cmd as _cc
        ctx = self._ctx()
        if ctx is None:
            return
        res = _cc.dispatch(ctx, f"{mit} {azon}")
        self._visszajelez(res)
        # ⚠ KÉNYSZERÍTETT újrarajzolás: a fájl módosulási ideje másodperc-
        # felbontású, tehát egy gyors döntés utáni változás ugyanabba a
        # másodpercbe eshet — a kapu ilyenkor kiszűrné a SAJÁT hatásunkat.
        self.refresh(force=True)

    def _futtat(self, fn):
        """A MEGERŐSÍTÉS-MINTA: ha a közös réteg rákérdez, megkérdezzük.

        ⚠ Ugyanaz a kör, mint a konzolon és a Telegramon — a szabály nem a
        felületben lakik, csak a kérdés alakja más."""
        ctx = self._ctx()
        if ctx is None:
            return
        res = fn(ctx, False)
        if getattr(res, "confirm", ""):
            if not self._confirm(res.confirm, _t("gui.ctrl.confirm_title"),
                                 self.parent):
                return
            res = fn(ctx, True)
        self._visszajelez(res)
        self.refresh(force=True)      # lásd `_dontes`: a saját hatásunk
        try:
            self._on_changed()
        except Exception:
            log.debug("Karmester fül: a hívó frissítése elbukott", exc_info=True)

    def _sajat_confirm(self, szoveg: str, cim: str = "", parent=None) -> bool:
        """Tartalék, ha a fül önállóan (dashboard nélkül) áll fel."""
        from tkinter import messagebox
        return bool(messagebox.askyesno(cim or _t("gui.ctrl.confirm_title"),
                                        szoveg, parent=parent or self.parent))

    def _visszajelez(self, res):
        sorok = list(getattr(res, "lines", []) or [])
        if sorok:
            self._lbl_info.config(text=" · ".join(sorok)[:160])

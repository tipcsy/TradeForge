"""
MT4/MT5 KAPCSOLAT — az indikátorok kitelepítése a terminálokba (Beállítások).

⚠ MIÉRT KÜLÖN, ÉS MIÉRT A BEÁLLÍTÁSOKBAN (Tibi, 2026-10-13): „A Kapcsolat
tab-nak ki kellene venni a stratégia alól … és áttenni a Beállításokba. …
stratégiánként nem kell külön MT5-t, meg MT4-et frissíteni/telepíteni." A
kitelepítés a GÉP dolga (minden terminál-mappába ugyanazok a fájlok mennek), nem
egy pár+stratégiáé — a stratégia-ablakban csak azt kellett volna minden
megnyitáskor átlapozni. A stratégia ablakában a PÁRHOZ tartozó két művelet marad
(„Chart" fül: küldés a chartra, MT4-visszajátszás).

A tartalom változatlan a régi Kapcsolat-laphoz képest: terminál-állapot (friss /
elavult / hiányzó), Kitelepítés, Lefordított beolvasása, és hogy melyik fájl mit
csinál.
"""

from __future__ import annotations

import tkinter as tk

from core.i18n import t as _t
from dashboard.scroll_area import scrollable as _scrollable
from dashboard.theme import (BG, FG_WHITE, FG_GRAY, FG_GRAY_DIM, FG_RED, FG_GREEN,
                             FG_YELLOW, BTN_PLAY_BG, BTN_PLAY_FG, BTN_BT_BG, BTN_BT_FG)


class MtLinkPanel:
    """MT4 | MT5 al-fülek a kitelepítéssel. `fonts`: (címsor, kis betű)."""

    def __init__(self, parent, header_font, small_font):
        from dashboard.tab_shell import TabShell
        self._hf, self._sf = header_font, small_font
        self.frame = tk.Frame(parent, bg=BG)
        # ⚠ A TabShell a konstruktorában megmutatja az első lapot — a visszahívás
        # ezért csak a létrehozás UTÁN kötődik be (ugyanaz a csapda, mint régen).
        self._sub = TabShell(self.frame, ("MT4", "MT5"), notify_every_show=True,
                             side="top")
        self._sub._on_show = self.build_pane
        self._status = {}
        self._sub.show("MT4")

    def build_pane(self, name: str):
        from core import mt_deploy as _md
        pane = self._sub.page(name)
        for w in pane.winfo_children():
            w.destroy()
        holder, body, _cv = _scrollable(pane)
        holder.pack(side="top", fill="both", expand=True)

        def _h(txt):
            tk.Label(body, text=txt, bg=BG, fg=FG_WHITE, font=self._hf,
                     anchor="w").pack(anchor="w", padx=10, pady=(10, 2))

        def _n(txt, fg=FG_GRAY):
            tk.Label(body, text=txt, bg=BG, fg=fg, font=self._sf, anchor="w",
                     justify="left", wraplength=820).pack(anchor="w", padx=10)

        roots = _md.discover_roots()
        st = _md.status(name, roots)
        tgts = _md.targets(name, roots)

        # ── MI VAN KINT ─────────────────────────────────────────────────────
        _h(_t("idlg.terminals_title", platform=name))
        if not tgts:
            _n(_t("idlg2.nem_talaltam_terminal_mappat"), FG_RED)
        else:
            from collections import Counter
            cnt = Counter(s["state"] for s in st)
            _fg = (FG_RED if cnt.get(_md.ST_STALE) else
                   (FG_YELLOW if cnt.get(_md.ST_MISSING) else FG_GREEN))
            _n(_t("idlg.terminal_counts", n=len(tgts),
                  fresh_l=_md.state_label(_md.ST_FRESH), fresh=cnt.get(_md.ST_FRESH, 0),
                  stale_l=_md.state_label(_md.ST_STALE), stale=cnt.get(_md.ST_STALE, 0),
                  missing_l=_md.state_label(_md.ST_MISSING),
                  missing=cnt.get(_md.ST_MISSING, 0)), _fg)
            # ⚠ Az ELAVULT a legfontosabb: ott MÁS fut, mint amit a repóban látsz.
            bad = [s for s in st if s["state"] == _md.ST_STALE]
            for s in bad:
                tk.Label(body, bg=BG, fg=FG_RED, font=self._sf, anchor="w",
                         justify="left", wraplength=820,
                         text=f"   ⚠ ELAVULT: {s['file']}  —  {s['target']}"
                         ).pack(anchor="w", padx=10)
            if bad:
                _n(_t("idlg2.az_elavult_fajlnal_a"), FG_RED)
            for t in tgts:
                tk.Label(body, bg=BG, fg=FG_GRAY_DIM, font=self._sf, anchor="w",
                         text=f"   {t}").pack(anchor="w", padx=10)

        row = tk.Frame(body, bg=BG)
        row.pack(anchor="w", padx=10, pady=(6, 2))
        tk.Button(row, text=_t("idlg.kitelepites"), bg=BTN_PLAY_BG, fg=BTN_PLAY_FG,
                  relief="flat", font=self._sf,
                  command=lambda p=name: self.deploy(p)).pack(side="left")
        # ⚠ NINCS „Fordítás" gomb: a MetaEditor parancssori fordítása egyetlen
        # dokumentált alakra sem működött. A F7 UTÁN ide lehet behozni a
        # lefordítottat a repóba — így verziózva tárolódik.
        tk.Button(row, text=_t("idlg.leforditott_beolvasasa"), bg=BTN_BT_BG, fg=BTN_BT_FG,
                  relief="flat", font=self._sf,
                  command=lambda p=name: self.capture(p)).pack(side="left", padx=(6, 0))
        self._status[name] = tk.Label(row, text="", bg=BG, fg=FG_GRAY, font=self._sf)
        self._status[name].pack(side="left", padx=(10, 0))

        # ── MELYIK FÁJL MICSODA ─────────────────────────────────────────────
        _h(_t("idlg2.mit_telepit_ki"))
        cs = {c["file"]: c for c in _md.compiled_status(name)}
        for src in _md.sources(name):
            rovid, _hasznalat = _md.describe(src)
            line = tk.Frame(body, bg=BG)
            line.pack(anchor="w", fill="x", padx=10)
            _sub = _md.subfolder_of(src)
            tk.Label(line, text=f"   {src.name}", bg=BG,
                     fg=(FG_YELLOW if _sub == "Experts" else FG_WHITE),
                     font=self._sf, anchor="w", width=26).pack(side="left")
            tk.Label(line, text=_sub, bg=BG, fg=FG_GRAY_DIM, font=self._sf,
                     width=11, anchor="w").pack(side="left")
            _v = _md.source_version(src)
            tk.Label(line, text=(f"v{_v}" if _v else "—"), bg=BG, fg=FG_GRAY_DIM,
                     font=self._sf, width=7, anchor="w").pack(side="left")
            tk.Label(line, text=rovid, bg=BG, fg=FG_GRAY, font=self._sf,
                     anchor="w").pack(side="left")
            _c = cs.get(src.name) or {}
            if _c.get("state") == _md.ST_OTHER_SOURCE:
                tk.Label(line, text=_t("idlg.a_tarolt_leforditott_mas"),
                         bg=BG, fg=FG_RED, font=self._sf, anchor="w").pack(side="left")
            elif _c.get("state") == _md.ST_MATCH:
                tk.Label(line, text=_t("idlg.leforditott_tarolva"), bg=BG, fg=FG_GREEN,
                         font=self._sf, anchor="w").pack(side="left")
        _n(_md.usage_of(name), FG_GRAY)
        # ⚠ Nem fordítunk — és ezt nem szépítjük: a „kitelepítve" önmagában NEM
        # jelenti, hogy az új kód FUT (a régi .ex4/.ex5 addig érvényben marad).
        _n(_t("idlg2.a_kitelepites_a_forrast"), FG_YELLOW)

    def _say(self, platform: str, text: str, fg):
        lbl = self._status.get(platform)
        if lbl is not None:
            try:
                lbl.config(text=text, fg=fg)
            except tk.TclError:
                pass

    def capture(self, platform: str):
        """A terminálban LEFORDÍTOTT fájlok beemelése a repóba (F7 után)."""
        from core import mt_deploy as _md
        try:
            res = _md.capture_compiled(platform, _md.discover_roots())
        except Exception as ex:
            self._say(platform, f"Hiba: {ex}", FG_RED)
            return
        msg = _t("idlg.compiled_taken", n=len(res["taken"]))
        if res["missing"]:
            msg += _t("idlg.compiled_missing", files=", ".join(res["missing"][:3]),
                      more=("…" if len(res["missing"]) > 3 else ""))
        self.build_pane(platform)
        self._say(platform, msg[:170], FG_YELLOW if res["missing"] else FG_GREEN)

    def deploy(self, platform: str):
        """A repó indikátorainak kimásolása MINDEN megtalált terminál-mappába."""
        from core import mt_deploy as _md
        try:
            res = _md.deploy(platform, _md.discover_roots())
        except Exception as ex:
            self._say(platform, f"Hiba: {ex}", FG_RED)
            return
        if res["errors"]:
            self._say(platform, res["errors"][0][:110], FG_RED)
            return
        # A lap újraépül, hogy az állapot AZONNAL a valóságot mutassa.
        self.build_pane(platform)
        self._say(platform, _t("idlg.deployed", n=len(res["copied"]),
                               targets=res["targets"], skipped=len(res["skipped"])),
                  FG_GREEN)

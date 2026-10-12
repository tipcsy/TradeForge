"""
KAPU-ÖSSZESÍTŐ — a `K.Össz.` cellára kattintva: egy instrumentum ÖSSZES kapuja.

Tibi kérése (2026-10-12): „ha rákattintok egy instrumentum sor K.Össz. cellájára
… egy összesítést kapnánk arról, hogy az adott instrumentumon melyik kapu fut,
melyik gátol, és melyik szabad, melyik kapu aktív, és melyik nem. Esetleg be is
tudnánk, vagy ki is tudnánk kapcsolni az egyes kapuk működését."

    ┌ GOLD — Kapuk ─────────────────────────────────────────────────────────┐
    │ Kapu                Rövid név  Most       │ wpr_sma       │ csilla     │
    │ Spread              Spread     ✓ szabad   │ [Gátol ▾] ✓   │ [Örökölt▾]✓│
    │ Idősík-együttállás  Együtt     ⛔ gátol    │ [Gátol ▾] ⛔  │ [Ki ▾]   – │
    └───────────────────────────────────────────────────────────────────────┘

Csak a BEKAPCSOLT kapuk látszanak, a Beállítások „Kapuk" fülén megadott
SORRENDBEN (ugyanaz, mint a tábla oszlopaié). Egy kikapcsolt kapu itt úgysem
kapcsolható be (az globális, nem a páré), ezért nincs sora (Tibi, 2026-10-12).
A név mellett a tábla oszlopának RÖVID neve áll, hogy a sor egyértelműen
azonosítható legyen a táblán.

  • **Most** — a mért állapot: szabad / gátol / nincs adat. Ugyanaz, amiből a
    `K.Össz.` számol (minden bekapcsolt kaput blokkolónak véve).
  • **Stratégiánként** — a hatás (Gátol / Csökkent / Ki / Örökölt) és hogy
    erre a stratégiára MOST mit jelent. Ez állítható; a mentés pontosan oda ír,
    ahová a kapu saját ablaka (`pairs.<SYM>.gates.<kapu>.<stratégia>`).

A tiszta rész (`rows`, `apply_effects`) tkinter nélkül tesztelhető; az ablak csak
rajzol.
"""

from __future__ import annotations

from core import gates as _g
from core import gate_layout as _gl
from core.i18n import t as _t

# A legördülő „Örökölt" tétele — a mentés ezt a pár-szintű felülírás TÖRLÉSÉNEK
# veszi (a config csak az eltérést rögzítse), nem egy konkrét hatás beírásának.
INHERIT = None


def short_label(key: str) -> str:
    """A kapu RÖVID neve = a tábla oszlopfejléce („Együtt", „Volat.×")."""
    from dashboard import live_row as _lr
    return _lr.header_text(_gl.column_key(key))


def rows(cfg: dict, symbol: str, ctx: dict, strategies) -> list:
    """BEKAPCSOLT kapunként egy sor, a Beállításokban megadott sorrendben.

    `[{key, label, short, enabled, state, detail,
       per: {stratégia: {effect, source, override, state}}}]`
    — `state` a kapu MÉRT állapota (PASS/BLOCKING/UNKNOWN; OFF, ha a kapu ki van
    kapcsolva), a `per[..]["state"]` pedig az, amit a stratégia a SAJÁT hatásával
    lát (OFF, ha rá a hatás `none`)."""
    cfg = cfg or {}
    ctx = ctx or {}
    on = set(_gl.enabled_gates(cfg))
    measured = {s["key"]: s for s in _g.evaluate(
        ctx, {k: (_g.EFFECT_BLOCK if k in on else _g.EFFECT_NONE) for k in _g.KEYS})}
    per_strategy = {}
    for name in strategies or []:
        eff = _g.effects_for(cfg, symbol, name)
        per_strategy[name] = {s["key"]: s for s in _g.evaluate(ctx, eff)}
    pg = ((cfg.get("pairs") or {}).get(symbol) or {}).get("gates") or {}
    out = []
    for key in _gl.enabled_gates(cfg):
        m = measured.get(key) or {}
        per = {}
        for name in strategies or []:
            e, src = _g.effect_with_source(cfg, symbol, name, key)
            per[name] = {
                "effect": e, "source": src,
                "override": _g._as_effect((pg.get(key) or {}).get(name)) is not None,
                "state": (per_strategy[name].get(key) or {}).get("state", _g.OFF),
            }
        out.append({"key": key, "label": _g.label_of(key), "short": short_label(key),
                    "enabled": key in on,
                    "state": m.get("state", _g.OFF), "detail": m.get("detail", ""),
                    "per": per})
    return out


def apply_effects(cfg: dict, symbol: str, changes: dict) -> bool:
    """A változtatások beírása a pár kapu-blokkjába. `changes`: {(kapu, stratégia):
    hatás | INHERIT}. Visszaad: változott-e bármi.

    ⚠ A Lendület bejegyzése lehet SZÓTÁR (`{"effect", "mode"}`) — ilyenkor csak a
    hatást írjuk át, a MÓD marad (különben egy hatás-váltás némán visszaállítaná
    a módot az alapra)."""
    if not changes:
        return False
    pc = cfg.setdefault("pairs", {}).setdefault(symbol, {})
    gates = pc.setdefault("gates", {})
    valtozott = False
    for (key, name), eff in changes.items():
        gg = gates.setdefault(key, {})
        regi = gg.get(name)
        if eff is INHERIT:
            if name in gg:
                gg.pop(name)
                valtozott = True
        elif eff in _g.EFFECTS:
            uj = ({**regi, "effect": eff} if isinstance(regi, dict) else eff)
            if regi != uj:
                gg[name] = uj
                valtozott = True
        if not gg:
            gates.pop(key, None)
    if not gates:
        pc.pop("gates", None)
    return valtozott


# ---------------------------------------------------------------------------
# Az ablak
# ---------------------------------------------------------------------------

def _state_text(state: str) -> tuple:
    """(felirat, szín-név) egy mért / stratégia-állapotra."""
    return {
        _g.PASS: (_t("gsum.state.pass"), "green"),
        _g.BLOCKING: (_t("gsum.state.blocking"), "red"),
        _g.UNKNOWN: (_t("gsum.state.unknown"), "gray"),
        _g.OFF: (_t("gsum.state.off"), "dim"),
    }.get(state, (state, "gray"))


class GateSummaryDialog:
    """`on_saved()` a mentés UTÁN fut (a hívó menti a config.json-t és frissít);
    `on_open_gate(kulcs)` egy kapu saját ablakát nyitja (a kapu nevére kattintva)."""

    def __init__(self, parent, cfg: dict, symbol: str, strategies, ctx: dict = None,
                 on_saved=None, on_open_gate=None):
        import tkinter as tk
        from dashboard import theme as _theme
        from dashboard.theme import (BG, BG_HEADER, FG_WHITE, FG_GRAY, FG_GRAY_DIM,
                                     FG_BLUE, FG_RED, FG_GREEN,
                                     BTN_PLAY_BG, BTN_PLAY_FG)
        from dashboard.gate_dialog import _style_om
        from dashboard.scroll_area import scrollable as _scrollable

        self.cfg, self.symbol = cfg, symbol
        self.strategies = list(strategies or [])
        self.ctx = ctx or {}
        self.on_saved, self.on_open_gate = on_saved, on_open_gate
        self._vars = {}          # (kapu, stratégia) → (StringVar, {felirat: hatás})
        f = _theme.fonts()
        szin = {"green": FG_GREEN, "red": FG_RED, "gray": FG_GRAY, "dim": FG_GRAY_DIM}

        self.top = tk.Toplevel(parent)
        self.top.title(_t("gsum.title", symbol=symbol))
        self.top.configure(bg=BG)
        self.top.geometry(f"{min(1400, 520 + 230 * max(1, len(self.strategies)))}x560")
        self.top.grab_set()

        tk.Label(self.top, text=_t("gsum.title", symbol=symbol), bg=BG, fg=FG_WHITE,
                 font=f["header"], anchor="w").pack(anchor="w", padx=12, pady=(12, 0))
        tk.Label(self.top, text=_t("gsum.help"), bg=BG, fg=FG_GRAY_DIM,
                 font=f["small"], anchor="w", justify="left",
                 wraplength=900).pack(anchor="w", padx=12, pady=(2, 6))

        # Gombsor ELŐSZÖR (alulról foglal), különben kis ablaknál kiszorul.
        bar = tk.Frame(self.top, bg=BG)
        bar.pack(side="bottom", fill="x", padx=12, pady=10)
        self._msg = tk.Label(bar, text="", bg=BG, fg=FG_GRAY, font=f["small"])
        self._msg.pack(side="left")
        tk.Button(bar, text=_t("gsum.close"), command=self.top.destroy,
                  bg=BG_HEADER, fg=FG_WHITE, font=f["small"], bd=0,
                  padx=12, pady=3).pack(side="right", padx=(6, 0))
        tk.Button(bar, text=_t("gsum.save"), command=self._save,
                  bg=BTN_PLAY_BG, fg=BTN_PLAY_FG, font=f["small"], bd=0,
                  padx=12, pady=3).pack(side="right")

        holder, page, _ = _scrollable(self.top)
        holder.pack(fill="both", expand=True, padx=12)
        grid = tk.Frame(page, bg=BG)
        grid.pack(fill="x")

        fejlec = [_t("gsum.col.gate"), _t("gsum.col.short"), _t("gsum.col.now")] \
            + list(self.strategies)
        for c, txt in enumerate(fejlec):
            tk.Label(grid, text=txt, bg=BG, fg=FG_BLUE, font=f["small"],
                     anchor="w").grid(row=0, column=c, sticky="w", padx=(0, 14), pady=(0, 4))

        for r, row in enumerate(rows(cfg, symbol, self.ctx, self.strategies), start=1):
            key = row["key"]
            nev = tk.Label(grid, text=row["label"], bg=BG, fg=FG_WHITE,
                           font=f["mono_bold"] if "mono_bold" in f else f["small"],
                           anchor="w", cursor=("hand2" if on_open_gate else ""))
            nev.grid(row=r, column=0, sticky="w", padx=(0, 14), pady=2)
            if on_open_gate:
                nev.bind("<Button-1>", lambda _e, k=key: self._open(k))
            tk.Label(grid, text=row["short"], bg=BG, fg=FG_GRAY,
                     font=f["small"], anchor="w").grid(row=r, column=1, sticky="w",
                                                       padx=(0, 14))
            st_txt, st_col = _state_text(row["state"])
            det = f"  {row['detail']}" if row["enabled"] and row["detail"] else ""
            tk.Label(grid, text=st_txt + det, bg=BG, fg=szin[st_col], font=f["small"],
                     anchor="w").grid(row=r, column=2, sticky="w", padx=(0, 14))
            for c, name in enumerate(self.strategies, start=3):
                p = row["per"][name]
                cell = tk.Frame(grid, bg=BG)
                cell.grid(row=r, column=c, sticky="w", padx=(0, 14))
                inh, _src = _g.inherited_effect(cfg, symbol, name, key)
                cimkek = {_t("gate.effect.inherited",
                             effect=_g.EFFECT_LABEL[inh]): INHERIT}
                for e in _g.EFFECTS:
                    cimkek[_g.EFFECT_LABEL[e]] = e
                lista = list(cimkek)
                sv = tk.StringVar(value=(_g.EFFECT_LABEL[p["effect"]] if p["override"]
                                         else lista[0]))
                self._vars[(key, name)] = (sv, cimkek, sv.get())
                om = tk.OptionMenu(cell, sv, *lista)
                _style_om(om, f["small"])
                om.config(width=max(len(x) for x in lista), anchor="w")
                om.pack(side="left")
                s_txt, s_col = _state_text(p["state"])
                if p["effect"] == _g.EFFECT_REDUCE and p["state"] == _g.BLOCKING:
                    s_txt, s_col = _t("gsum.state.reducing"), "gray"
                tk.Label(cell, text=s_txt, bg=BG, fg=szin[s_col],
                         font=f["small"]).pack(side="left", padx=(6, 0))

    def _changes(self) -> dict:
        out = {}
        for (key, name), (sv, cimkek, eredeti) in self._vars.items():
            if sv.get() != eredeti:
                out[(key, name)] = cimkek.get(sv.get(), INHERIT)
        return out

    def _save(self):
        if apply_effects(self.cfg, self.symbol, self._changes()):
            if self.on_saved:
                self.on_saved()
            self.top.destroy()
        else:
            self._msg.config(text=_t("gsum.nothing"))

    def _open(self, key: str):
        self.top.destroy()
        self.on_open_gate(key)


def open_gate_summary(parent, cfg, symbol, strategies, ctx=None, on_saved=None,
                      on_open_gate=None):
    return GateSummaryDialog(parent, cfg, symbol, strategies, ctx=ctx,
                             on_saved=on_saved, on_open_gate=on_open_gate)

"""
KOCKÁZATKEZELÉS — egy ablak, minden pár, minden stratégia (2026-10-13).

Tibi: „Most három+ helyen lehet kockázatot kezelni, instrumentumon, és a
stratégiában. Illetve a nyitott pozícióknál is külön." … „az egyes
stratégiáknak lehet külön kiszállójuk". A válasz a kapuk mintája:

    ┌ Kockázatkezelés ─────────────────────────────────────────────────────┐
    │ Pár     │ Alap (a pár)        │ wpr_sma          │ csilla            │
    │ Ger40   │ BE+trailing · BE 1R │ (örökölt)        │ Pajzs · Jel       │
    │ GOLD    │ Pajzs · Trail       │ (örökölt)        │ (örökölt)         │
    └─────────┴─────────────────────┴──────────────────┴───────────────────┘

Egy cellára kattintva a részletes szerkesztő nyílik. A pár ALAPJÁNÁL minden mező
saját érték; egy STRATÉGIÁNÁL minden mező lehet „Örökölt (…)" — ilyenkor a pár
alapja érvényes —, vagy saját érték (felülírás). A tárolás `core/rr_state.py`
(`strategies` blokk); a motor és a backtest a pozíció/futás stratégiája szerint
old fel.

A tiszta rész (mezők, összefoglaló, mentés-terv) tkinter nélkül tesztelhető.
"""

from __future__ import annotations

from core.i18n import t as _t

# ── A szerkeszthető mezők ────────────────────────────────────────────────────
# (kulcs, fajta). A sorrend a felületen látszó sorrend. Az `exit_indicator` a
# kiszállási jel indikátora (az `exit` blokk `indicator` kulcsa).
FIELDS = (
    ("preset", "choice"),
    ("cautious", "tristate"),
    ("runner", "choice"),
    ("breakeven_r", "float"),
    ("breakeven_pct", "float"),
    ("trail_activation_atr", "float"),
    ("trail_distance_atr", "float"),
    ("trigger_R", "float"),
    ("halving_fraction", "float"),
    ("shield_fraction", "float"),
    ("fibo_level", "float"),
    ("fibo_stop_level", "float"),
    ("thirds_base_R", "float"),
    ("big_move_atr_mult", "float"),
    ("cost_cut", "bool"),
    ("cost_cut_bars", "int"),
    ("eod_close", "time"),
    ("max_hold_min", "float"),
    ("exit_indicator", "choice"),
)
FIELD_KEYS = tuple(k for k, _f in FIELDS)
EXIT_INDICATORS = ("supertrend", "wpr", "divergence")


def choices(key: str) -> list:
    """`[(kód, felirat)]` a választós mezőkhöz."""
    from core import rr_state as R
    if key == "preset":
        return [(p, R.NAME[p]) for p in R.CYCLE]
    if key == "runner":
        return [(r, R.RUNNER_NAME[r]) for r in R.RUNNERS]
    if key == "exit_indicator":
        # Indikátor-nevek (nem fordítjuk — ugyanúgy, mint a stratégia ablaka);
        # csak a „Divergencia" magyar szó.
        return [("supertrend", "Supertrend"), ("wpr", "WPR"),
                ("divergence", _t("exit.ind.divergence"))]
    if key == "cautious":
        return [(None, _t("risk.cautious.auto")), (True, _t("risk.yes")),
                (False, _t("risk.no"))]
    return []


def relevant(spec: dict) -> set:
    """Mely mezők HATNAK a mostani preseten (a többi halványan látszik)."""
    from core import risk_reduction as RR
    preset = spec.get("preset", RR.PRESET_OFF)
    runner = spec.get("runner_stop", RR.RUNNER_TRAILING)
    out = {"preset", "cautious", "cost_cut", "cost_cut_bars", "eod_close",
           "max_hold_min"}
    out |= RR.be_trail_active(preset, runner)
    out |= RR.partial_active(preset)
    if preset in (RR.PRESET_OFF,):
        out.add("breakeven_r")
    if preset in RR.PARTIAL_CLOSE_PRESETS:
        out.add("runner")
        if runner == RR.RUNNER_EXIT:
            out.add("exit_indicator")
    if preset in (RR.PRESET_FIBO, RR.PRESET_SHIELD_FIBO):
        out |= {"fibo_level", "fibo_stop_level"}
    if preset == RR.PRESET_SHIELD_FIBO:
        out.add("big_move_atr_mult")
    if preset == RR.PRESET_THIRDS:
        out.add("thirds_base_R")
    return out


def values(symbol: str, strategy: str = None) -> dict:
    """A mezők ÉRVÉNYES értéke (a pár alapja, ill. a stratégiára feloldva)."""
    from core import rr_state as R
    spec = R.spec_for(symbol, strategy)
    out = {k: spec.get(k) for k in FIELD_KEYS}
    out["runner"] = spec.get("runner_stop")
    out["cautious"] = R.get_cautious(symbol, strategy)
    out["exit_indicator"] = (spec.get("exit") or {}).get("indicator", "supertrend")
    out["cost_cut_bars"] = R.get_cost_cut_bars(symbol, strategy)
    return out


def overridden(symbol: str, strategy: str) -> set:
    """A stratégia által FELÜLÍRT mezők (a többi örökölt)."""
    from core import rr_state as R
    ov = R.override_of(symbol, strategy)
    out = {k for k in ov if k in FIELD_KEYS}
    if "exit" in ov and "indicator" in (ov.get("exit") or {}):
        out.add("exit_indicator")
    return out


def summary(symbol: str, strategy: str = None) -> str:
    """Egy cella rövid szövege: preset · a legfontosabb szám · kiegészítők."""
    from core import rr_state as R, risk_reduction as RR
    v = values(symbol, strategy)
    preset = v["preset"] or RR.PRESET_OFF
    darab = [R.NAME.get(preset, preset)]
    if preset == RR.PRESET_OFF:
        darab.append(f"BE {v['breakeven_r']:g}R" if (v.get("breakeven_r") or 0) > 0
                     else f"BE {float(v.get('breakeven_pct') or 0) * 100:.0f}%")
    if preset in RR.PARTIAL_CLOSE_PRESETS:
        darab.append(R.RUNNER_NAME.get(v["runner"], v["runner"]))
    if v.get("cost_cut"):
        darab.append("cost-cut")
    if v.get("eod_close"):
        darab.append(str(v["eod_close"]))
    return " · ".join(darab)


INHERIT = object()          # „Örökölt" a szerkesztőben


def plan_changes(symbol: str, strategy, before: dict, after: dict) -> list:
    """A mentés lépései: `[(művelet, kulcs, érték)]` — művelet: "set" | "clear".
    A pár alapján csak a MEGVÁLTOZOTT mezők íródnak; stratégián az `INHERIT`
    a felülírás törlése."""
    out = []
    for k in FIELD_KEYS:
        if k not in after:
            continue
        uj, regi = after[k], before.get(k)
        if uj is INHERIT:
            if strategy and regi is not INHERIT:
                out.append(("clear", k, None))
            continue
        if uj != regi:
            out.append(("set", k, uj))
    return out


def apply_changes(symbol: str, strategy, steps: list) -> None:
    """A `plan_changes` lépéseinek végrehajtása az `rr_state`-en."""
    from core import rr_state as R
    torol = [k for op, k, _v in steps if op == "clear"]
    if torol and strategy:
        R.clear_override(symbol, strategy,
                         keys=[("exit" if k == "exit_indicator" else
                                ("runner" if k == "runner" else k)) for k in torol])
    for op, k, v in steps:
        if op != "set":
            continue
        if k == "preset":
            R.set_preset(symbol, v, strategy=strategy)
        elif k == "runner":
            R.set_runner(symbol, v, strategy=strategy)
        elif k == "cautious":
            R.set_cautious(symbol, v, strategy=strategy)
        elif k == "exit_indicator":
            R.set_exit_config(symbol, strategy=strategy, indicator=v)
        elif k == "cost_cut":
            R.set_cost_cut(symbol, bool(v), strategy=strategy)
        elif k == "cost_cut_bars":
            R.set_cost_cut_bars(symbol, int(v), strategy=strategy)
        elif k in ("eod_close", "max_hold_min"):
            te = R.get_time_exit(symbol, strategy)
            te[k] = v
            R.set_time_exit(symbol, te["eod_close"], float(te["max_hold_min"]),
                            strategy=strategy)
        else:
            R._set(symbol, strategy, **{k: float(v)})


def columns(cfg: dict) -> list:
    """A mátrix stratégia-oszlopai: az elérhető stratégiák (a Beállításokból)."""
    from strategy import available_strategy_names
    try:
        return list(available_strategy_names(cfg or {}))
    except Exception:
        return []


def pairs(cfg: dict) -> list:
    return [s for s, p in ((cfg or {}).get("pairs") or {}).items() if isinstance(p, dict)]


# ---------------------------------------------------------------------------
# Az ablak
# ---------------------------------------------------------------------------

class RiskWindow:
    """A mátrix. `on_changed()` mentés után fut (a hívó frissít)."""

    def __init__(self, parent, cfg: dict, focus=None, on_changed=None):
        import tkinter as tk
        from dashboard import theme as _theme
        from dashboard.scroll_area import scrollable as _scrollable
        from dashboard.theme import BG, FG_WHITE, FG_GRAY_DIM, FG_BLUE
        self.tk, self.cfg, self.on_changed = tk, cfg, on_changed
        self._f = _theme.fonts()
        self.top = tk.Toplevel(parent)
        self.top.title(_t("risk.title"))
        self.top.configure(bg=BG)
        self.top.geometry("1100x640")
        tk.Label(self.top, text=_t("risk.title"), bg=BG, fg=FG_WHITE,
                 font=self._f["header"], anchor="w").pack(anchor="w", padx=12, pady=(12, 0))
        tk.Label(self.top, text=_t("risk.help"), bg=BG, fg=FG_GRAY_DIM,
                 font=self._f["small"], anchor="w", justify="left",
                 wraplength=1050).pack(anchor="w", padx=12, pady=(2, 8))
        holder, self._body, _cv = _scrollable(self.top, horizontal=True)
        holder.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._fej = FG_BLUE
        self.render()
        if focus:
            self.edit(*focus)

    def render(self):
        tk = self.tk
        from strategy import enabled_strategy_names
        from dashboard.theme import (BG, BG_HEADER, FG_WHITE, FG_GRAY, FG_GRAY_DIM,
                                     FG_BLUE, FG_CYAN)
        for w in self._body.winfo_children():
            w.destroy()
        oszl = columns(self.cfg)
        fejlec = [_t("risk.col.pair"), _t("risk.col.base")] + oszl
        for c, txt in enumerate(fejlec):
            tk.Label(self._body, text=txt, bg=BG, fg=FG_BLUE, font=self._f["small"],
                     anchor="w").grid(row=0, column=c, sticky="w", padx=(0, 14), pady=(0, 4))
        for r, sym in enumerate(pairs(self.cfg), start=1):
            tk.Label(self._body, text=sym, bg=BG, fg=FG_WHITE,
                     font=self._f.get("mono_bold", self._f["small"]),
                     anchor="w").grid(row=r, column=0, sticky="w", padx=(0, 14), pady=1)
            self._cell(r, 1, summary(sym), FG_WHITE, (sym, None))
            engedett = set(enabled_strategy_names(self.cfg, sym) or [])
            for c, name in enumerate(oszl, start=2):
                sajat = bool(overridden(sym, name))
                txt = summary(sym, name) if sajat else _t("risk.inherited")
                fg = FG_CYAN if sajat else FG_GRAY
                if name not in engedett:
                    fg = FG_GRAY_DIM          # a páron nem fut — szerkeszthető, halvány
                self._cell(r, c, txt, fg, (sym, name))

    def _cell(self, r, c, txt, fg, key):
        tk = self.tk
        from dashboard.theme import BG
        lbl = tk.Label(self._body, text=txt, bg=BG, fg=fg, font=self._f["small"],
                       anchor="w", cursor="hand2")
        lbl.grid(row=r, column=c, sticky="w", padx=(0, 14), pady=1)
        lbl.bind("<Button-1>", lambda _e, k=key: self.edit(*k))

    def edit(self, symbol, strategy=None):
        RiskEditor(self.top, symbol, strategy, on_saved=self._saved)

    def _saved(self):
        self.render()
        if self.on_changed:
            self.on_changed()


class RiskEditor:
    """Egy pár ALAPJA vagy egy (pár, stratégia) felülírása — mezőnként."""

    def __init__(self, parent, symbol: str, strategy=None, on_saved=None):
        import tkinter as tk
        from dashboard import theme as _theme
        from dashboard.gate_dialog import _style_om
        from dashboard.scroll_area import scrollable as _scrollable
        from dashboard.theme import (BG, BG_HEADER, FG_WHITE, FG_GRAY, FG_GRAY_DIM,
                                     FG_RED, BTN_PLAY_BG, BTN_PLAY_FG)
        self.symbol, self.strategy, self.on_saved = symbol, strategy, on_saved
        f = _theme.fonts()
        self.top = tk.Toplevel(parent)
        cim = (_t("risk.edit.base", symbol=symbol) if not strategy
               else _t("risk.edit.strategy", symbol=symbol, strategy=strategy))
        self.top.title(cim)
        self.top.configure(bg=BG)
        self.top.geometry("620x680")
        self.top.grab_set()
        tk.Label(self.top, text=cim, bg=BG, fg=FG_WHITE, font=f["header"],
                 anchor="w").pack(anchor="w", padx=12, pady=(12, 2))
        tk.Label(self.top, text=(_t("risk.edit.help_strategy") if strategy
                                 else _t("risk.edit.help_base")),
                 bg=BG, fg=FG_GRAY_DIM, font=f["small"], anchor="w", justify="left",
                 wraplength=580).pack(anchor="w", padx=12, pady=(0, 6))
        bar = tk.Frame(self.top, bg=BG)
        bar.pack(side="bottom", fill="x", padx=12, pady=10)
        self._msg = tk.Label(bar, text="", bg=BG, fg=FG_RED, font=f["small"])
        self._msg.pack(side="left")
        tk.Button(bar, text=_t("btn.close"), command=self.top.destroy, bg=BG_HEADER,
                  fg=FG_WHITE, font=f["small"], bd=0, padx=12, pady=3).pack(side="right",
                                                                             padx=(6, 0))
        tk.Button(bar, text=_t("btn.save"), command=self._save, bg=BTN_PLAY_BG,
                  fg=BTN_PLAY_FG, font=f["small"], bd=0, padx=12, pady=3).pack(side="right")
        holder, body, _cv = _scrollable(self.top)
        holder.pack(fill="both", expand=True, padx=12)

        self._ertek = values(symbol, strategy)
        self._orokolt = values(symbol, None) if strategy else {}
        self._sajat = overridden(symbol, strategy) if strategy else set(FIELD_KEYS)
        hat = relevant({"preset": self._ertek["preset"], "runner_stop": self._ertek["runner"]})
        self._vars = {}
        self._before = {}
        for r, (k, fajta) in enumerate(FIELDS):
            fg = FG_WHITE if k in hat else FG_GRAY_DIM
            tk.Label(body, text=_t(f"risk.field.{k.lower()}"), bg=BG, fg=fg, font=f["small"],
                     anchor="w", width=30).grid(row=r, column=0, sticky="w", pady=1)
            opts = self._opts(k, fajta)
            jelen = (self._ertek[k] if (not strategy or k in self._sajat) else INHERIT)
            self._before[k] = jelen
            if opts is not None:
                cimkek = [c for _v, c in opts]
                sv = tk.StringVar(value=next((c for v, c in opts if v is jelen or v == jelen),
                                             cimkek[0]))
                om = tk.OptionMenu(body, sv, *cimkek)
                _style_om(om, f["small"])
                om.config(width=max(len(c) for c in cimkek), anchor="w")
                om.grid(row=r, column=1, sticky="w", pady=1)
                self._vars[k] = ("opt", sv, opts)
            else:
                # szám / idő: egy mező + (stratégián) „örökölt" pipa
                sv = tk.StringVar(value="" if jelen is INHERIT else self._fmt(jelen))
                e = tk.Entry(body, textvariable=sv, width=10, bg=BG_HEADER, fg=FG_WHITE,
                             insertbackground=FG_WHITE, font=f["small"])
                e.grid(row=r, column=1, sticky="w", pady=1)
                inh = None
                if strategy:
                    inh = tk.BooleanVar(value=jelen is INHERIT)
                    tk.Checkbutton(body, text=_t("risk.inherited_val",
                                                 value=self._fmt(self._orokolt.get(k))),
                                   variable=inh, bg=BG, fg=FG_GRAY, selectcolor=BG_HEADER,
                                   font=f["small"], activebackground=BG).grid(
                                       row=r, column=2, sticky="w", padx=(8, 0))
                self._vars[k] = ("entry", sv, inh, fajta)

    @staticmethod
    def _fmt(v):
        if v is None:
            return ""
        if isinstance(v, float):
            return f"{v:g}"
        return str(v)

    def _opts(self, k, fajta):
        """A legördülő tételei `[(érték, felirat)]` — stratégián az elején
        „Örökölt (…)"; számmezőnél None."""
        if fajta in ("choice", "tristate"):
            base = choices(k)
        elif fajta == "bool":
            base = [(True, _t("risk.yes")), (False, _t("risk.no"))]
        else:
            return None
        if self.strategy:
            orok = self._orokolt.get(k)
            felirat = next((c for v, c in base if v is orok or v == orok), self._fmt(orok))
            return [(INHERIT, _t("risk.inherited_val", value=felirat))] + base
        return base

    def _after(self) -> dict:
        out = {}
        for k, spec in self._vars.items():
            if spec[0] == "opt":
                _m, sv, opts = spec
                out[k] = next((v for v, c in opts if c == sv.get()), INHERIT)
            else:
                _m, sv, inh, fajta = spec
                if inh is not None and inh.get():
                    out[k] = INHERIT
                    continue
                raw = sv.get().strip().replace(",", ".")
                if fajta == "time":
                    out[k] = raw
                elif raw == "":
                    out[k] = self._before[k]
                else:
                    out[k] = int(float(raw)) if fajta == "int" else float(raw)
        return out

    def _save(self):
        try:
            after = self._after()
            steps = plan_changes(self.symbol, self.strategy, self._before, after)
            apply_changes(self.symbol, self.strategy, steps)
        except (ValueError, TypeError) as ex:
            self._msg.config(text=_t("risk.save_error", error=ex))
            return
        if self.on_saved:
            self.on_saved()
        self.top.destroy()


def open_risk_window(parent, cfg, focus=None, on_changed=None):
    return RiskWindow(parent, cfg, focus=focus, on_changed=on_changed)

"""
KÖZÖS beállító ablak a belépő-kapukhoz — egy váz, minden kapunak.

Eddig minden kapu máshogy volt elérhető: a `Spread` cellára kattintva a teljes
stratégia-paraméterlista nyílt (a keresett három szám az egyik kategóriában
elrejtve), az `Együtt` egy kézzel írt külön ablakot kapott, a `Piac` pedig csak
az instrumentum-ablakból volt állítható. Ez a modul EGY felületet ad
mindegyiknek:

    ┌ <SYM> — <Kapu neve> ────────────────────────────┐
    │ MOST                (mért, csak olvasható)      │
    │ BEÁLLÍTÁSOK         (a kapu saját számai)       │
    │ HATÁS STRATÉGIÁNKÉNT (Ki / Akadályoz / Kockázat)│
    │ [ ] Az összes instrumentumra                    │
    └─────────────────────────────────────────────────┘

A rajzoláson kívül semmi nem itt lakik: a paraméterek LEÍRÁSA és ellenőrzése a
tiszta `core/gate_params.py`-ban, a hatás-feloldás a `core/gates.py`-ban, a
tárolás pedig a mai gazdájánál marad (`execution_params`, `tf_align`, config).
Ezért az új kapu ingyen kapja meg az ablakot: elég egy `ParamSpec`-sor és egy
tároló-adapter.
"""

from __future__ import annotations

import tkinter as tk

from core import gate_params as _gp
from core import gates as _g
from core.i18n import t as _t
from dashboard import theme as _theme
from dashboard.scroll_area import scrollable as _scrollable
from dashboard.theme import (BG, BG_HEADER, FG_WHITE, FG_GRAY, FG_GRAY_DIM,
                             FG_BLUE, FG_RED, FG_GREEN,
                             BTN_PLAY_BG, BTN_PLAY_FG, BTN_DIS_BG, BTN_DIS_FG)


# ---------------------------------------------------------------------------
# Tároló-adapterek — kapunként honnan olvasunk / hová írunk
# ---------------------------------------------------------------------------
# Szándékosan NEM egységesítjük a tárolást: a spread küszöbei stratégia-független
# végrehajtási paraméterek (saját per-szimbólum fájl), a TF-együttállás a pár
# config-szekciójában lakik, a piac-előszűrő pedig két külön kulcsban. Egy erőltetett
# közös tároló mindhármat elrontaná; a közös nyelv az ŰRLAP, nem a lemez.

def _load_spread(cfg: dict, symbol: str) -> dict:
    from core.execution_params import load_execution_params
    return dict(load_execution_params(symbol, cfg) or {})


def _save_spread(cfg: dict, symbol: str, values: dict, all_symbols: list):
    from core.execution_params import (load_execution_params,
                                       save_execution_params)
    for sym in all_symbols:
        cur = dict(load_execution_params(sym, cfg) or {})
        cur.update(values)
        save_execution_params(sym, cur)


def _load_tf_align(cfg: dict, symbol: str) -> dict:
    from core import tf_align as _tfa
    en, tfs, sma, _gate = _tfa.config_for(cfg, symbol)
    return {"enabled": en, "timeframes": list(tfs), "sma_period": sma,
            "viz": _tfa.viz_on(cfg, symbol)}


def _save_tf_align(cfg: dict, symbol: str, values: dict, all_symbols: list):
    for sym in all_symbols:
        pc = cfg.setdefault("pairs", {}).setdefault(sym, {})
        ta = pc.setdefault("tf_align", {})
        if "enabled" in values:
            ta["enabled"] = values["enabled"]
        if "timeframes" in values:
            ta["timeframes"] = list(values["timeframes"])
        if "sma_period" in values:
            ta["sma_period"] = values["sma_period"]
        if "viz" in values:
            ta["viz"] = values["viz"]


def _load_market(cfg: dict, symbol: str) -> dict:
    pc = ((cfg.get("pairs") or {}).get(symbol) or {})
    return {"market_strategy": pc.get("market_strategy") or "",
            "adverse": sorted(_g.market_adverse(cfg, symbol)),
            "market_viz": bool(pc.get("market_viz", False))}


def _save_market(cfg: dict, symbol: str, values: dict, all_symbols: list):
    for sym in all_symbols:
        pc = cfg.setdefault("pairs", {}).setdefault(sym, {})
        if "market_strategy" in values:
            v = values["market_strategy"]
            if v:
                pc["market_strategy"] = v
            else:
                pc.pop("market_strategy", None)
        if "market_viz" in values:
            pc["market_viz"] = values["market_viz"]
        if "adverse" in values:
            gates = pc.setdefault("gates", {})
            m = gates.setdefault(_g.MARKET, {})
            # Az ALAPÉRTELMEZÉSSEL egyező listát nem írjuk ki: a config csak az
            # ELTÉRÉST rögzítse, különben egy jövőbeli alapérték-változás némán
            # hatástalan maradna ezen a páron.
            if set(values["adverse"]) == set(_g.MARKET_ADVERSE_DEFAULT):
                m.pop("adverse", None)
            else:
                m["adverse"] = list(values["adverse"])
            if not m:
                gates.pop(_g.MARKET, None)
            if not gates:
                pc.pop("gates", None)


def _load_momentum(cfg: dict, symbol: str) -> dict:
    pc = ((cfg.get("pairs") or {}).get(symbol) or {})
    return dict(_g.momentum_config(pc, cfg))


def _save_momentum(cfg: dict, symbol: str, values: dict, all_symbols: list):
    """A MÉRÉS paraméterei a `pairs.<SYM>.gates.momentum`-ba mennek — ugyanabba a
    szótárba, ahol a per-stratégia hatás/mód is lakik. Nem ütköznek: a mérési
    kulcsok (`basis`, `sma_fast`, …) és a stratégia-nevek diszjunktak (a `market`
    kapu `adverse` kulcsa ugyanígy él a stratégia-nevek mellett)."""
    from core import momentum as _m
    for sym in all_symbols:
        pc = cfg.setdefault("pairs", {}).setdefault(sym, {})
        g = pc.setdefault("gates", {}).setdefault(_g.MOMENTUM, {})
        for k, v in values.items():
            # A config csak az ELTÉRÉST rögzítse: az alapértékkel egyező mezőt
            # kivesszük, hogy egy jövőbeli alapérték-változás ne maradjon némán
            # hatástalan ezen a páron.
            if k in _m.DEFAULTS and v == _m.DEFAULTS[k]:
                g.pop(k, None)
            else:
                g[k] = list(v) if isinstance(v, list) else v


def _load_cost(cfg: dict, symbol: str) -> dict:
    pc = ((cfg.get("pairs") or {}).get(symbol) or {})
    return {"max_rr_distortion": _g.cost_max_distortion(pc, cfg)}


def _save_cost(cfg: dict, symbol: str, values: dict, all_symbols: list):
    from core import cost_gate as _cg
    for sym in all_symbols:
        pc = cfg.setdefault("pairs", {}).setdefault(sym, {})
        g = pc.setdefault("gates", {}).setdefault(_g.COST, {})
        v = values.get("max_rr_distortion")
        if v is None or v == _cg.DEFAULT_MAX_DISTORTION:
            g.pop("max_rr_distortion", None)   # csak az ELTÉRÉST rögzítjük
        else:
            g["max_rr_distortion"] = v


_STORE = {
    _g.SPREAD:   (_load_spread,   _save_spread),
    _g.TF_ALIGN: (_load_tf_align, _save_tf_align),
    _g.MARKET:   (_load_market,   _save_market),
    _g.MOMENTUM: (_load_momentum, _save_momentum),
    _g.COST:     (_load_cost, _save_cost),
}


def register_store(key: str, load, save):
    """Új kapu bekötése (a `core/gates.REGISTRY` bővítése mellé). A `save` a
    `(cfg, symbol, values, all_symbols)` négyest kapja — az „összes
    instrumentumra” pipát a váz intézi, a tároló csak végigmegy a listán."""
    _STORE[key] = (load, save)


# ---------------------------------------------------------------------------
# Az ablak
# ---------------------------------------------------------------------------

def _section(parent, title: str):
    box = tk.Frame(parent, bg=BG)
    box.pack(fill="x", padx=12, pady=(10, 0))
    hdr = tk.Frame(box, bg=BG)
    hdr.pack(fill="x")
    tk.Label(hdr, text=title, bg=BG, fg=FG_BLUE,
             font=_theme.fonts()["small"], anchor="w").pack(side="left")
    tk.Frame(hdr, bg=BG_HEADER, height=1).pack(side="left", fill="x",
                                               expand=True, padx=(8, 0))
    return box


def _style_om(om, font):
    om.config(bg=BG_HEADER, fg=FG_WHITE, font=font, highlightthickness=0,
              activebackground=BG_HEADER, activeforeground=FG_WHITE,
              bd=0, relief="flat")
    om["menu"].config(bg=BG_HEADER, fg=FG_WHITE, font=font,
                      activebackground=BG, activeforeground=FG_WHITE)


class GateDialog:
    """A kapu beállító ablaka. `on_saved()` a mentés UTÁN fut (a hívó ebből
    frissíti a táblát és menti a config.json-t)."""

    def __init__(self, parent, cfg: dict, symbol: str, gate_key: str,
                 strategies: list, ctx: dict = None, on_saved=None,
                 all_symbols: list = None):
        self.cfg = cfg
        self.symbol = symbol
        self.key = gate_key
        self.strategies = list(strategies or [])
        self.ctx = ctx or {}
        self.on_saved = on_saved
        self._all_symbols = list(all_symbols or [symbol])
        self._f = _theme.fonts()
        self._vars = {}          # paraméter-kulcs → tk változó (vagy dict MULTI-nál)
        self._eff_vars = {}      # stratégia → tk.StringVar (hatás)
        self._eff_by_label = {}
        self._mode_vars = {}     # stratégia → tk.StringVar (mód — csak a Lendületnél)

        self.top = tk.Toplevel(parent)
        self.top.title(f"{symbol} — {_g.label_of(gate_key)}")
        self.top.configure(bg=BG)
        self.top.resizable(True, True)
        self.top.geometry("720x620")
        self.top.grab_set()

        tk.Label(self.top, text=_t("gate.dialog.title", symbol=symbol,
                                   gate=_g.label_of(gate_key)),
                 bg=BG, fg=FG_WHITE, font=self._f["header"], anchor="w").pack(
                 anchor="w", padx=12, pady=(12, 0))

        # ⚠ A gombsor foglal ELŐSZÖR (alulról), különben kis ablaknál kiszorul —
        # a `pack` a hívás sorrendjében oszt helyet (lásd `tab_shell`).
        self._build_footer()

        # ── Bal oldali fülek: Beállítás · Leírás ─────────────────────────
        # A leírás a felhasználó kérésére NEM külön ablak: a paraméterek MELLETT
        # kell tudni, mit is állítunk.
        from dashboard.tab_shell import TabShell
        self._shell = TabShell(self.top,
                               (("settings", _t("tab.settings")),
                                ("docs", _t("tab.docs"))),
                               on_show=self._on_tab)

        # A Beállítás lap GÖRGETHETŐ: a Lendületnek nyolc paramétere van, és
        # alatta még a stratégiánkénti hatás-blokk is jön — ez kis ablaknál
        # levágódott, gördítősáv nélkül pedig NÉMÁN (semmi nem jelezte, hogy van
        # még lejjebb). A Leírás lap nem kap külön görgetőt: a Markdown-nézet
        # Text-widgetje magától görget, két sáv egymás mellett zavaró lenne.
        _holder, self._page, _ = _scrollable(self._shell.page("settings"))
        _holder.pack(fill="both", expand=True)

        self._build_measured()
        self._build_params()
        self._build_effects()

    def _on_tab(self, name):
        """LUSTA feltöltés: a leírást csak akkor rendereljük, ha rá is néztek.
        A lemezről olvassa, tehát szerkesztés után újranyitva azonnal friss."""
        if name != "docs":
            return
        from dashboard import md_view
        md_view.render(self._shell.page("docs"), _g.doc_text(self.key),
                       source=str(_g.doc_path(self.key)))

    # ── MOST (mért) ──────────────────────────────────────────────────────
    def _build_measured(self):
        rows = _gp.measured_rows(self.key, self.ctx)
        if not rows:
            return
        box = _section(self._page, "Most")
        grid = tk.Frame(box, bg=BG)
        grid.pack(fill="x", pady=(4, 0))
        for i, (label, value) in enumerate(rows):
            tk.Label(grid, text=label, bg=BG, fg=FG_GRAY, font=self._f["small"],
                     anchor="w", width=30).grid(row=i, column=0, sticky="w")
            tk.Label(grid, text=value, bg=BG, fg=FG_WHITE, font=self._f["mono"],
                     anchor="w").grid(row=i, column=1, sticky="w")

    # ── BEÁLLÍTÁSOK (a kapu saját számai) ────────────────────────────────
    def _build_params(self):
        specs = _gp.specs_for(self.key)
        if not specs:
            return
        load, _save = _STORE.get(self.key, (None, None))
        cur = load(self.cfg, self.symbol) if load else {}
        box = _section(self._page, _t("gate.section.settings"))
        for spec in specs:
            val = cur.get(spec.key, spec.default)
            self._build_one(box, spec, val)

    def _build_one(self, box, spec, val):
        row = tk.Frame(box, bg=BG)
        row.pack(fill="x", pady=(6, 0))
        if spec.kind == _gp.BOOL:
            v = tk.BooleanVar(value=bool(val))
            self._vars[spec.key] = v
            tk.Checkbutton(row, text=spec.label, variable=v, bg=BG, fg=FG_WHITE,
                           selectcolor=BG_HEADER, font=self._f["small"],
                           activebackground=BG, activeforeground=FG_WHITE,
                           anchor="w").pack(anchor="w")
        elif spec.kind == _gp.MULTI:
            tk.Label(row, text=spec.label, bg=BG, fg=FG_GRAY,
                     font=self._f["small"], anchor="w").pack(anchor="w")
            inner = tk.Frame(row, bg=BG)
            inner.pack(anchor="w", padx=12)
            picked = set(val or [])
            vmap = {}
            for value, label in _gp.choices_of(spec):
                bv = tk.BooleanVar(value=(value in picked))
                vmap[value] = bv
                tk.Checkbutton(inner, text=label, variable=bv, bg=BG, fg=FG_WHITE,
                               selectcolor=BG_HEADER, font=self._f["small"],
                               activebackground=BG,
                               activeforeground=FG_WHITE).pack(side="left",
                                                               padx=(0, 8))
            self._vars[spec.key] = vmap
        elif spec.kind == _gp.CHOICE:
            tk.Label(row, text=spec.label, bg=BG, fg=FG_GRAY,
                     font=self._f["small"], anchor="w").pack(side="left")
            opts = _gp.choices_of(spec)
            labels = [lb for _v, lb in opts]
            cur_lb = next((lb for v, lb in opts if v == val), labels[0] if labels else "")
            sv = tk.StringVar(value=cur_lb)
            self._vars[spec.key] = (sv, opts)
            om = tk.OptionMenu(row, sv, *(labels or [""]))
            _style_om(om, self._f["small"])
            om.config(width=max((len(x) for x in labels), default=8), anchor="w")
            om.pack(side="left", padx=8)
        else:                                   # FLOAT / INT
            tk.Label(row, text=spec.label, bg=BG, fg=FG_GRAY,
                     font=self._f["small"], anchor="w", width=30).pack(side="left")
            sv = tk.StringVar(value=str(val))
            self._vars[spec.key] = sv
            tk.Entry(row, textvariable=sv, width=10, bg=BG_HEADER, fg=FG_WHITE,
                     font=self._f["mono"],
                     insertbackground=FG_WHITE).pack(side="left")
        if spec.help:
            tk.Label(box, text=spec.help, bg=BG, fg=FG_GRAY_DIM,
                     font=self._f["small"], anchor="w", justify="left",
                     wraplength=460).pack(anchor="w", padx=12)

    # ── HATÁS stratégiánként ─────────────────────────────────────────────
    def _inherited_label(self, name: str) -> str:
        inh, _src = _g.inherited_effect(self.cfg, self.symbol, name, self.key)
        return _t("gate.effect.inherited", effect=_g.EFFECT_LABEL[inh])

    def _effect_choices(self, name: str) -> list:
        """A legördülő feliratai — és a FELIRAT → KÓD leképezés eltéve.

        ⚠ Az „Örökölt" sort korábban a felirat ELŐTAGJA azonosította
        (`txt.startswith("Örökölt")`). Lefordítva ez sosem talált volna: a
        mentés az öröklés visszavonása helyett egy konkrét hatást írt volna a
        configba — csendben, rossz értékkel."""
        labels = [self._inherited_label(name)] + \
                 [_g.EFFECT_LABEL[e] for e in _g.EFFECTS]
        self._eff_by_label[name] = {labels[0]: None}
        for e in _g.EFFECTS:
            self._eff_by_label[name][_g.EFFECT_LABEL[e]] = e
        return labels

    def _has_override(self, name: str) -> bool:
        pg = ((self.cfg.get("pairs") or {}).get(self.symbol) or {}).get("gates") or {}
        return (pg.get(self.key) or {}).get(name) in _g.EFFECTS

    def _build_effects(self):
        if not self.strategies:
            return
        # ⚠ CSAK KIJELZÉS kapu: NINCS állítható hatás. A szűrés máshol (a
        # stratégia `bt_entry`-jében) történik. Egy hatás-választó itt vagy
        # duplán szűrne, vagy `none`-ra állítva azt ígérné, hogy kikapcsoltad a
        # szűrést — a némán hatástalan beállítás pont az, amit ez a projekt a
        # legrosszabbnak tart. Ezért a választó helyett MEGMONDJUK, hol lakik.
        if _g.is_display_only(self.key):
            box = _section(self._page, _t("gate.section.effect"))
            tk.Label(box, text=_t("gate.display_only"),
                bg=BG, fg=FG_GRAY, font=self._f["small"], anchor="w",
                justify="left", wraplength=560).pack(anchor="w", pady=(4, 0))
            return
        box = _section(self._page, _t("gate.section.when_blocking"))
        grid = tk.Frame(box, bg=BG)
        grid.pack(fill="x", pady=(4, 0))
        for i, name in enumerate(self.strategies):
            tk.Label(grid, text=name, bg=BG, fg=FG_WHITE, font=self._f["small"],
                     anchor="w", width=16).grid(row=i, column=0, sticky="w", pady=1)
            eff, src = _g.effect_with_source(self.cfg, self.symbol, name, self.key)
            # ALAPBÓL az „Örökölt (…)" tétel áll, ha nincs pár-szintű felülírás —
            # így a Mentés nem RÖGZÍTI némán az örökölt értéket. Ez nem
            # kozmetika: az `Együtt` hatása a régi `tf_align.gate` listából is
            # öröklődhet, és egy néma `none` KIKAPCSOLTA volna a kaput.
            choices = self._effect_choices(name)
            sv = tk.StringVar(value=(_g.EFFECT_LABEL[eff]
                                     if self._has_override(name) else choices[0]))
            self._eff_vars[name] = sv
            om = tk.OptionMenu(grid, sv, *choices)
            _style_om(om, self._f["small"])
            om.config(width=max(len(t) for t in choices), anchor="w")
            om.grid(row=i, column=1, sticky="w", padx=6)
            col = 2
            # A Lendület KÉTFÉLEKÉPPEN bukhat (alapjárat / irány), és a kettő más
            # kereskedési döntés — ezért itt a hatás mellé egy „mit figyeljen"
            # választó is kell, szintén stratégiánként.
            if self.key == _g.MOMENTUM:
                mode, _msrc = _g.mode_with_source(self.cfg, self.symbol, name)
                mv = tk.StringVar(value=_g.MOM_MODE_LABEL[mode])
                self._mode_vars[name] = mv
                mom = tk.OptionMenu(grid, mv,
                                    *[_g.MOM_MODE_LABEL[m] for m in _g.MOM_MODES])
                _style_om(mom, self._f["small"])
                mom.config(width=max(len(t) for t in _g.MOM_MODE_LABEL.values()),
                           anchor="w")
                mom.grid(row=i, column=col, sticky="w", padx=6)
                col += 1
            tk.Label(grid, text=f"→ {_g.EFFECT_LABEL[eff]}  "
                                f"({_g.SOURCE_LABEL.get(src, src)})", bg=BG,
                     fg=(FG_WHITE if src == _g.SRC_PAIR else FG_GRAY_DIM),
                     font=self._f["small"], anchor="w").grid(
                     row=i, column=col, sticky="w", padx=(6, 0))

    # ── Lábléc: „összes instrumentumra” + gombok ─────────────────────────
    def _build_footer(self):
        self._all_var = tk.BooleanVar(value=False)
        _foot = tk.Frame(self.top, bg=BG)
        _foot.pack(side="bottom", fill="x")
        tk.Checkbutton(_foot,
                       text=_t("gate.all_symbols"),
                       variable=self._all_var, bg=BG, fg=FG_WHITE,
                       selectcolor=BG_HEADER, font=self._f["small"],
                       activebackground=BG, activeforeground=FG_WHITE).pack(
                       anchor="w", padx=12, pady=(12, 0))
        self.lbl_err = tk.Label(_foot, text="", bg=BG, fg=FG_RED,
                                font=self._f["small"], anchor="w",
                                justify="left", wraplength=460)
        self.lbl_err.pack(anchor="w", padx=12, pady=(6, 0))
        bar = tk.Frame(_foot, bg=BG)
        bar.pack(fill="x", padx=12, pady=12)
        tk.Button(bar, text=_t("btn.save"), command=self._save, bg=BTN_PLAY_BG,
                  fg=BTN_PLAY_FG, font=self._f["small"], bd=0,
                  padx=14, pady=4).pack(side="left")
        tk.Button(bar, text=_t("btn.cancel"), command=self.top.destroy, bg=BTN_DIS_BG,
                  fg=BTN_DIS_FG, font=self._f["small"], bd=0,
                  padx=14, pady=4).pack(side="left", padx=8)

    # ── Beolvasás / mentés ───────────────────────────────────────────────
    def raw_values(self) -> dict:
        """A nyers űrlap-értékek — a `gate_params.parse_all` bemenete."""
        out = {}
        for spec in _gp.specs_for(self.key):
            v = self._vars.get(spec.key)
            if v is None:
                continue
            if spec.kind == _gp.MULTI:
                out[spec.key] = [val for val, bv in v.items() if bv.get()]
            elif spec.kind == _gp.CHOICE:
                sv, opts = v
                out[spec.key] = next((val for val, lb in opts if lb == sv.get()), "")
            else:
                out[spec.key] = v.get()
        return out

    def _save(self):
        values, errors = _gp.parse_all(self.key, self.raw_values())
        errors += _gp.extra_errors(self.key, values)
        if errors:
            # RÉSZLEGES mentés SOHA: a fele beállítás elmenne, a másik fele nem,
            # és utána semmi nem mondaná meg, melyik melyik.
            self.lbl_err.config(text=_t("save.errors",
                                        list="\n• ".join(errors)))
            return
        targets = self._all_symbols if self._all_var.get() else [self.symbol]
        try:
            _load, save = _STORE.get(self.key, (None, None))
            if save:
                save(self.cfg, self.symbol, values, targets)
            self._save_effects(targets)
        except Exception as ex:
            self.lbl_err.config(text=_t("save.error", error=ex))
            return
        if self.on_saved:
            self.on_saved()
        self.top.destroy()

    def _save_effects(self, targets: list):
        """A per-stratégia hatás a `pairs.<SYM>.gates.<kapu>.<stratégia>`-ba megy —
        ugyanaz a hely, amit az instrumentum-ablak is ír, tehát a két felület
        nem csúszik szét.

        Az „Örökölt (…)" választás VISSZAVONJA a pár-szintű felülírást (és
        kitakarítja az üresen maradt szótárakat), nem pedig beírja az örökölt
        értéket: a config csak az ELTÉRÉST rögzítse."""
        by_label = {lb: e for e, lb in _g.EFFECT_LABEL.items()}
        for sym in targets:
            pc = self.cfg.setdefault("pairs", {}).setdefault(sym, {})
            for name, sv in self._eff_vars.items():
                txt = sv.get()
                gates = pc.setdefault("gates", {})
                gg = gates.setdefault(self.key, {})
                if self._eff_by_label.get(name, {}).get(txt, "?") is None:
                    gg.pop(name, None)
                else:
                    eff = by_label.get(txt)
                    if eff is None:
                        continue
                    mv = self._mode_vars.get(name)
                    if mv is None:
                        gg[name] = eff
                    else:
                        # A Lendületnél a bejegyzés SZÓTÁR: a hatás mellé a mód is
                        # kell (`{"effect": …, "mode": …}`) — a `gates._as_effect`
                        # mindkét alakot érti, a régi configok nem törnek.
                        mode = next((m for m in _g.MOM_MODES
                                     if _g.MOM_MODE_LABEL[m] == mv.get()),
                                    _g.MOM_MODE_DEFAULT)
                        gg[name] = {"effect": eff, "mode": mode}
                if not gg:
                    gates.pop(self.key, None)
                if not gates:
                    pc.pop("gates", None)


def open_gate_dialog(parent, cfg, symbol, gate_key, strategies, ctx=None,
                     on_saved=None, all_symbols=None):
    """Kényelmi belépő — a `gui` ezt hívja a kapu-cella kattintására."""
    return GateDialog(parent, cfg, symbol, gate_key, strategies, ctx=ctx,
                      on_saved=on_saved, all_symbols=all_symbols)

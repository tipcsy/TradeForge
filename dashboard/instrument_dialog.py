"""
Instrumentum-paraméter szerkesztő ablak (a Symbol-cellára kattintva nyílik).

Korábban a `dashboard/gui.py`-ban élt (`_show_instrument_params`); kiszervezve,
mert a gui.py túl nagy lett és ez az ablak önállóan is bővül.

Mit tud:
  • Optimalizált párnál: minősítés + metrikák fejléc, a trials CSV **sorszám
    (minőségi rangsor, 1 = legjobb)** szerinti betöltése ▲/▼ nyilakkal, óránkénti
    kereskedési kapcsoló (trade_hours), kézi paraméter-módosítás.
  • Optimalizálatlan párnál (nincs JSON): ugyanez az ablak nyílik **alap-
    paraméterekkel**, így GUI-ból is létrehozható a `{symbol}.json` optimalizálás
    nélkül (rövid életű / friss instrumentumokhoz).
  • Kézi paraméter-készlet, ami nincs a listában, **új sorszámként** (501…)
    menthető a trials CSV-be és a JSON-ba.

A trials CSV formátuma: ';' elválasztó + ',' tizedes (magyar Excel), utf-8-sig.
Score szerint csökkenő sorrendben van → a sor sorszáma = minőségi rangsor.
"""

from __future__ import annotations

import csv
import json
import threading
import tkinter as tk
from datetime import datetime

from dashboard.theme import (
    BG, BG_HEADER,
    FG_WHITE, FG_GREEN, FG_RED, FG_YELLOW, FG_GRAY, FG_GRAY_DIM, FG_BLUE,
    BTN_PLAY_BG, BTN_PLAY_FG, BTN_BT_BG, BTN_BT_FG,
    BTN_DIS_BG, BTN_DIS_FG,
    FG_ON_ACCENT, TOOLTIP_BG, TOOLTIP_FG,
    color as sem_color,
)
from dashboard import theme as _theme
from core.quality import metric_colors
from core.params_store import (
    params_file, trials_file, resolve_trade_hours, save_trade_hours,
)
from core import execution_params as _execp
from core import risk_reduction as _rrx

# A közös, stratégia-független "Végrehajtás" kategória (atr_period + spread-kapu)
# — minden stratégia-configból kikerült, itt jelenik meg egységesen.
# `_EXEC_KEYS` a `core.execution_params.DEFAULTS` kulcsai.
#
# ⚠ A BE/trailing v1.96.0 óta NEM ITT van: a kockázatcsökkentő beállító ablakban
# jelenik meg, és CSAK azokon a preseteken, ahol tényleg hat (Fibo/Harmados
# preseten például semmit nem csinált — lásd `core.risk_reduction.be_trail_active`).
_EXEC_CATEGORY = "Végrehajtás"
_EXEC_KEYS = frozenset(_execp.DEFAULTS)
_EXEC_PARAM_META = {
    "atr_period": {"category": _EXEC_CATEGORY,
                   "comment": "ATR periódus (spread-kapu + BE/trailing volatilitás-mércéje)"},
    "max_spread_atr_ratio": {"category": _EXEC_CATEGORY,
                              "comment": "Spread-kapu: max spread az ATR arányában"},
    "min_spread_mult": {"category": _EXEC_CATEGORY,
                         "comment": "Spread-kapu alsó küszöbe (a normál spread ennyiszerese)"},
}

# ELAVULT paraméter-kulcsok a régi, mentett `optimized_params/<strat>/<SYM>.json`
# fájlokban. Ezeket a motor SOHA nem paraméterként olvassa — a `max_open_slots`
# a `trading` configból jön (`core.risk_manager.calc_lot`), és a Backtest-ablak
# „Slotok" mezője is azt írja felül. A JSON-ban maradt másolat viszont megjelent
# a Paraméterek ablakban szerkeszthetőként, és mentéskor újra kiíródott: egy
# beállítás, ami látszólag hat, valójában nem. Betöltéskor kidobjuk.
# A `max_open_slots` mellé v1.96.0-ban jött a BE/trailing: azok a KOCKÁZAT-
# CSÖKKENTÉS paraméterei lettek (`core/risk_reduction.py`), tehát a stratégia
# paraméter-ablakában sem szerkesztendők többé. A régi mentett JSON-okban még
# ott lehetnek — betöltéskor kidobjuk, hogy ne látszódjanak hatásosnak.
_OBSOLETE_PARAM_KEYS = frozenset({"max_open_slots", *_rrx.BE_TRAIL_KEYS})

# A trials CSV metrika-oszlopai (ezek NEM paraméterek, hanem az eredmény jellemzői)
_METRIC_COLS = frozenset({
    "rank", "score", "trades", "win_rate", "total_pnl", "max_drawdown",
    "profit_factor", "note",
})
# Az első manuálisan mentett sor sorszáma (megkülönbözteti az optimalizáltaktól)
_MANUAL_RANK_BASE = 501


def _fmt_ranges(nums, max_runs: int = 3) -> str:
    """Egész sorszámok TÖMÖR felsorolása: az egymást követőket tartományba vonja.

        [501…575]            → "501–575"
        [501, 502, 505]      → "501–502, 505"

    Miért: a kézi sorszámok tételes felsorolása (`501, 502, 503, …`) néhány tucat
    bejegyzésnél méterekre kitolta a paraméter-ablakot jobbra. `max_runs` fölött
    az elejét mutatjuk + a darabszámot, így a felirat hossza felülről korlátos."""
    nums = sorted(set(int(n) for n in nums))
    if not nums:
        return ""
    runs = [[nums[0], nums[0]]]
    for n in nums[1:]:
        if n == runs[-1][1] + 1:
            runs[-1][1] = n
        else:
            runs.append([n, n])
    parts = [(f"{a}" if a == b else f"{a}–{b}") for a, b in runs[:max_runs]]
    if len(runs) > max_runs:
        parts.append(f"… ({len(nums)} db)")
    return ", ".join(parts)


def _num(s):
    """Magyar-tizedes ('1,75') vagy sima szám → float; hiba esetén None."""
    try:
        return float(str(s).replace(",", "."))
    except (ValueError, TypeError):
        return None


def default_params(cfg: dict, strategy) -> dict:
    """Alapértelmezett paraméter-készlet optimalizálatlan instrumentumhoz.

    A stratégia `base_params`-ából indul, és kiegészíti az optimizer-tér összes
    hangolható kulcsával (érték: a trading-config, különben a tartomány alja),
    hogy a kézi űrlap ugyanazt a teljes paraméterlistát kínálja, amit egy
    optimalizált JSON tartalmazna.

    ⚠ A `cfg` MINDIG a `strategy` SAJÁT nézete legyen
    (`strategy.settings.config_for_strategy`), ne a nyers futásidejű cfg! Az
    utóbbi az ELSŐDLEGES stratégia `indicators`/`position_mgmt`/optimizer-terével
    van merge-elve, tehát egy másik stratégia űrlapjára beszivárognának a primary
    kulcsai (az `ml_ai` ablakában így jelent meg a `sma_period`, a `wpr_*`, az
    `atr_min_pct`/`atr_max_pct` és a `no_trade_resets_signal`).
    """
    base = dict(strategy.base_params(cfg))
    opt = cfg.get("optimizer", {}) or {}
    trading = cfg.get("trading", {}) or {}
    for key, spec in opt.items():
        if key.startswith("_") or key in base:
            continue
        if not isinstance(spec, dict) or "min" not in spec:
            continue
        base[key] = trading.get(key, spec["min"])
    return base


def _style_om(om, font):
    """OptionMenu egységes sötét stílusa (a sok ismételt config kiemelve)."""
    om.config(bg=BG_HEADER, fg=FG_WHITE, font=font, relief="flat",
              highlightthickness=0, activebackground=BG_HEADER)
    om["menu"].config(bg=BG_HEADER, fg=FG_WHITE)


def _attach_tooltip(widget, text):
    """Egyszerű hover-tooltip egy widgethez. `text` lehet str VAGY callable→str
    (utóbbi a dinamikus, pl. indikátor-függő szöveghez)."""
    state = {"win": None}

    def show(_e=None):
        txt = text() if callable(text) else text
        if state["win"] is not None or not txt:
            return
        t = tk.Toplevel(widget)
        t.wm_overrideredirect(True)
        t.attributes("-topmost", True)
        x = widget.winfo_rootx()
        y = widget.winfo_rooty() + widget.winfo_height() + 2
        tk.Label(t, text=txt, bg=TOOLTIP_BG, fg=TOOLTIP_FG, font=_theme.fonts()["small"],
                 padx=6, pady=3, relief="solid", bd=1, justify="left",
                 wraplength=340).pack()
        t.wm_geometry(f"+{x}+{y}")
        state["win"] = t

    def hide(_e=None):
        if state["win"] is not None:
            try:
                state["win"].destroy()
            except Exception:
                pass
            state["win"] = None

    widget.bind("<Enter>", show, add="+")
    widget.bind("<Leave>", hide, add="+")


# A görgethető terület KÖZÖS lett (`dashboard/scroll_area.py`), hogy a kapu-ablak
# is megkapja — itt csak a régi név marad meg, hogy a hívások ne változzanak.
from dashboard.scroll_area import scrollable as _scrollable


class InstrumentParamsDialog:
    """Optimalizált paraméterek szerkesztője egy instrumentumhoz."""

    def __init__(self, parent, symbol, cfg, strategy,
                 header_font, small_font, save_main_config, root_cfg=None):
        self.parent  = parent
        self.symbol  = symbol
        # A `self.cfg` a stratégia NÉZETE — `config_for_strategy` deepcopy-t ad,
        # tehát ABBA írni nem hat a programra. A kapu-hatás viszont a VALÓDI
        # config.json-ba megy (`pairs.<SYM>.gates`), ezért kell az ÉLŐ cfg is.
        # (Enélkül a legördülő némán semmit nem mentett volna.)
        self.root_cfg = root_cfg if root_cfg is not None else cfg
        # A cfg átképezése ENNEK a stratégiának a nézetére: a futásidejű cfg az
        # ELSŐDLEGES stratégia szekcióival (indicators/sltp/param_meta/quality/
        # optimizer-tér) van merge-elve — egy MÁSIK stratégia ablaka különben a
        # primary paraméterlistáját/minősítés-küszöbeit mutatná (pl. az ml_ai a
        # wpr_sma-ét). A váz-szekciók (pairs, trading, ml) változatlanok.
        from strategy.settings import config_for_strategy
        self.cfg     = config_for_strategy(cfg, strategy.name)
        self.strategy = strategy
        self._hf     = header_font
        self._sf     = small_font
        self._save_main_config = save_main_config

        # Stratégia-hatókörű tárolás: data/optimized_params/<strategy>/<symbol>.*
        self.pf = params_file(symbol, self.strategy.name)
        self.trials_csv = trials_file(symbol, self.strategy.name)

        # ── JSON betöltése (ha van) ─────────────────────────────────────────
        self.data = None
        try:
            if self.pf.exists():
                with open(self.pf, encoding="utf-8") as f:
                    self.data = json.load(f)
        except Exception:
            self.data = None
        self.is_new = self.data is None
        params = (self.data or {}).get("params", {})

        # A megjelenített/menthető paraméter-forrás: optimalizált JSON, vagy alap.
        # A (esetleg RÉGI sémájú) JSON-t a JELENLEGI sémához igazítjuk: a hiányzó ÚJ
        # kulcsokat kiegészítjük (alapérték), a meglévőket megtartjuk — így az új
        # paraméterek akkor is megjelennek/menthetők, ha a pár még nincs újraoptimali-
        # zálva. Migráció: a régi közös wpr_m15_trigger értékét átvisszük a külön
        # BUY/SELL triggerbe (a stratégiánál külön paraméter lett).
        if params:
            src = dict(params)
            if "wpr_m15_trigger" in src:
                _old = src.pop("wpr_m15_trigger")
                src.setdefault("wpr_m15_sell_trigger", _old)
                src.setdefault("wpr_m15_buy_trigger",  _old)
            for _k, _v in default_params(self.cfg, strategy).items():
                src.setdefault(_k, _v)
            # Elavult kulcsok kidobása: a régi JSON-okban maradt olyan érték,
            # amit a motor SOHA nem paraméterként olvas — a felületen viszont
            # szerkeszthetőnek látszott, és mentéskor újra kiíródott.
            for _k in _OBSOLETE_PARAM_KEYS:
                src.pop(_k, None)
            self._src = src
        else:
            self._src = default_params(self.cfg, strategy)
        # Közös, stratégia-független végrehajtási paraméterek (BE/trailing/
        # atr_period/spread-kapu) — MINDIG a ténylegesen ható (execution-config)
        # értéket mutatjuk, felülírva egy esetleges elavult másolatot a régi
        # optimalizált JSON-ban.
        self._orig_exec_params = _execp.load_execution_params(symbol, cfg)
        self._src = {**self._src, **self._orig_exec_params}
        self._keys  = sorted(k for k in self._src if not k.startswith("_"))
        # Típus-minta a mentéskori konverzióhoz (int/float/bool/str)
        self._types = {k: self._src[k] for k in self._keys}

        # ── trials CSV betöltése → {rank: {oszlop: nyers_str}} ──────────────
        self._rank_rows = self._load_trials()
        self._ranks = sorted(self._rank_rows)

        # A Backtest gomb eredménye (a Mentés ezt írja test_summary-ként a JSON-ba,
        # így a minősítés megjelenik a soron). None = még nem futott backtest.
        self._bt_summary = None
        self._bt_running = False
        # True, ha a _bt_summary a MENTETT test_summary újrafelhasználása
        # (változatlan készlet) — ilyenkor a backtested_at nem frissül.
        self._bt_from_saved = False
        # Az egyetlen Mentés gomb új kombónál auto-backtestet futtat; ez a flag
        # jelzi a _bt_done-nak, hogy a backtest UTÁN folytassa a mentést.
        self._save_after_bt = False

        # ── A FUTTATÁS lap állapota ────────────────────────────────────────
        # ⚠ Ezeknek a `_build()` ELŐTT kell létezniük: a lap lustán épül, de a
        # Paraméter lap pipái (`_on_skip_change` → `_refresh_opt_space`) és a
        # bezárás-kezelő már előbb hozzájuk nyúlhat.
        self._run_tab = None        # a beágyazott backtest
        self._run_params = None     # amivel épült (paraméter-változásra újraépül)
        self._tuned_lbl = None      # a terv-sáv címkéi
        self._space_lbl = None
        self._sweep_box = None
        self._sw_stop = None        # futó söprés megszakító-jelzője (háttérszál)
        self._sw_rows, self._sw_axes = [], []
        self._opt_rows = []
        self._opt_plan = None
        self._opt_cfg_cache = {}

        self._build()

    # ── trials CSV ──────────────────────────────────────────────────────────
    def _load_trials(self) -> dict:
        """A trials CSV beolvasása. Kulcs = sorszám (rank), érték = oszlop→str.

        A CSV score szerint csökkenő sorrendben van; ha nincs explicit `rank`
        oszlop, a sor pozíciója adja a rangsort (1 = első/legjobb)."""
        if not self.trials_csv.exists():
            return {}
        try:
            with open(self.trials_csv, encoding="utf-8-sig", newline="") as f:
                rows = list(csv.reader(f, delimiter=";"))
        except Exception:
            return {}
        if len(rows) < 2:
            return {}
        header = rows[0]
        out = {}
        for i, raw in enumerate((r for r in rows[1:] if r), start=1):
            rec = {header[j]: raw[j] for j in range(min(len(header), len(raw)))}
            if "rank" in rec:
                r = _num(rec["rank"])
                rank = int(r) if r is not None else i
            else:
                rank = i
            out[rank] = rec
        return out

    def _fmt_param(self, key: str, raw: str) -> str:
        """CSV-nyers érték → az Entry-be írható, tiszta szöveg (típus szerint)."""
        val = _num(raw)
        if val is None:
            return str(raw)
        t = self._types.get(key)
        if isinstance(t, bool):
            return "True" if val != 0 else "False"
        if isinstance(t, int):
            return str(int(round(val)))
        return f"{val:g}"          # 0.6000000000000001 → 0.6 ; 1.75 → 1.75

    # ── UI felépítés ─────────────────────────────────────────────────────────
    def _build(self):
        popup = tk.Toplevel(self.parent)
        self.popup = popup
        # A címben az instrumentum ÉS a stratégia is látszik (több stratégia esetén
        # egyértelmű, MELYIK stratégia paraméterei jelennek meg).
        title = f"{self.symbol} — {self.strategy.name} paraméterek"
        if self.is_new:
            title += " (új / kézi)"
        popup.title(title)
        popup.configure(bg=BG)
        popup.grab_set()
        # ⚠ Bezárás-jelző a HÁTTÉRSZÁLAKNAK (söprés). Enélkül egy futó söprés a
        # már megsemmisült widgetekhez nyúlna, és a szál `TclError`-ral halna meg
        # — némán, mert egy daemon-szál kivétele nem jut el sehova. A `<Destroy>`
        # a gyerek-widgetekre is elsül, ezért kell a `widget is popup` szűrés.
        self._closed = False

        def _on_destroy(ev, _p=popup):
            if ev.widget is _p:
                self._closed = True
                if getattr(self, "_sw_stop", None) is not None:
                    self._sw_stop.set()      # a futó söprés álljon le magától
                _bt = getattr(self, "_run_tab", None)
                if _bt is not None:
                    _bt.shutdown()           # a beágyazott backtest is

        popup.bind("<Destroy>", _on_destroy)

        # ── Rögzített alsó sáv ELŐSZÖR (side="bottom") ──────────────────────
        # Kis képernyőn a hosszú paraméterlista miatt a gombok lelógtak; a
        # pack-sorrend miatt a lentre kötött sáv KAPJA MEG a helyét először, a
        # görgethető törzs csak a maradékot → a Mentés/Backtest/Mégse MINDIG látszik.
        footer = tk.Frame(popup, bg=BG)
        footer.pack(side="bottom", fill="x")

        # ── Bal oldali fülek: Paraméter · Leírás ────────────────────────────
        # A leírás korábban KÜLÖN ABLAKBAN nyílt egy gombról. A felhasználó
        # kérésére ugyanennek a formnak a lapja lett: a paraméterek MELLETT kell
        # tudni olvasni, mit is állítunk.
        from dashboard.tab_shell import TabShell
        self._shell = TabShell(popup, ("Áttekintés", "Paraméter", "Futtatás",
                                "Eredmények", "Leírás"),
                               on_show=self._on_tab, notify_every_show=True)

        # Görgethető törzs — innentől MINDEN tartalom ide (`body`) megy.
        holder, body, self._body_canvas = _scrollable(self._shell.page("Paraméter"))
        holder.pack(side="top", fill="both", expand=True)
        self._body = body

        # Fejléc-sor a tartalomban is (a címsor könnyen elsiklik): instrumentum + stratégia.
        tk.Label(body, text=f"{self.symbol}  ·  stratégia: {self.strategy.name}",
                 bg=BG, fg=FG_WHITE, font=self._hf, anchor="w").pack(
                 anchor="w", padx=10, pady=(8, 0))

        ts = (self.data or {}).get("test_summary", {})

        # ── EGYETLEN metrika-sáv ────────────────────────────────────────────
        # Korábban UGYANAZ a metrika 3 helyen jelent meg (fejléc + sorszám-sor +
        # backtest-sor), más-más sorrendben. Most EGY sáv, ami a PILLANATNYILAG
        # betöltött paraméterkészletet tükrözi (mentett eredmény / #N trials-sor /
        # friss backtest), egységes sorrendben: Trade · Win · MaxDD · P&L · PF.
        self._grade_lbl = tk.Label(body, bg=BG, font=self._hf, anchor="w")
        self._grade_lbl.pack(anchor="w", padx=10, pady=(10, 0))
        self._metrics_frame = tk.Frame(body, bg=BG)
        self._metrics_frame.pack(anchor="w", padx=10, pady=(0, 1))
        self._src_lbl = tk.Label(body, bg=BG, fg=FG_GRAY_DIM, font=self._sf,
                                 anchor="w")
        self._src_lbl.pack(anchor="w", padx=10, pady=(0, 4))
        if ts:
            self._render_metrics(ts, "mentett eredmény")
        else:
            self._render_metrics(
                None, "nincs mentett eredmény — állíts be paramétert, a Mentés "
                      "lefuttatja a backtestet és eltárolja")

        # ── Figyelmeztetés: a készlet KAPUK NÉLKÜL lett hangolva ────────────
        # A v1.95.0 előtti optimalizáló a spread- és a TF-együttállás kapu NÉLKÜL
        # futott, az él viszont mindkettőt alkalmazza — a mentett paraméterek
        # tehát egy olyan világhoz tartoznak, ami élesben nem létezik. Ez eddig
        # LÁTHATATLAN volt: a régi és az új eredmény ránézésre egyforma. Ezért
        # kiírjuk, ha a JSON-ban nincs (vagy hamis) az `exec_gates` jelölő.
        if self.data is not None and not self.data.get("exec_gates", False):
            tk.Label(body, bg=BG, fg=FG_YELLOW, font=self._sf, anchor="w",
                     justify="left", wraplength=560,
                     text=("⚠ Ez a készlet a VÉGREHAJTÁSI KAPUK NÉLKÜL lett "
                           "hangolva (spread + TF-együttállás), az él viszont "
                           "kapuz → a backtest más eredményt ad, mint az "
                           "optimalizáló mutatott. Futtasd újra az OPT-ot.")
                     ).pack(anchor="w", padx=10, pady=(0, 4))

        # ── Óra-rács (trade_hours) — a config.json-ba ment ──────────────────
        self._build_hours(body, ts)

        # ── Kézi paraméter-űrlap ────────────────────────────────────────────
        tk.Label(body, text="Kézi módosítás — a következő Play-nél lép életbe:",
                 bg=BG, fg=FG_GRAY, font=self._sf).pack(anchor="w", padx=10)

        # ── Sorszám-választó (csak ha van trials CSV) ───────────────────────
        self.lbl_rank = None
        if self._ranks:
            self._build_rank_selector(body)

        form = tk.Frame(body, bg=BG)
        form.pack(fill="both", expand=True, padx=10, pady=6)
        self.entries = {}
        self._comment_entries = {}

        # ── Kategóriák + megjegyzések a stratégia-configból (param_meta) ────────
        # A 'categories' a megjelenítési SORREND; a 'params.<kulcs>' adja a kategóriát
        # és a (szerkeszthető) megjegyzést. Ismeretlen kulcs → 'Egyéb' a végén.
        _pm     = self.cfg.get("param_meta") or {}
        _cat_ord = list(_pm.get("categories") or [])
        _pmeta  = {**(_pm.get("params") or {}), **_EXEC_PARAM_META}
        if _EXEC_CATEGORY not in _cat_ord:
            _insert_at = _cat_ord.index("Egyéb") if "Egyéb" in _cat_ord else len(_cat_ord)
            _cat_ord.insert(_insert_at, _EXEC_CATEGORY)

        def _cat_of(k):
            return (_pmeta.get(k, {}) or {}).get("category") or "Egyéb"

        # ── EGY paraméter = EGY sor: érték ÉS söprési tartomány ─────────────
        # Korábban ugyanazt a paramétert három helyen kellett kezelni (érték itt,
        # érték a backtest-ablakban, tartomány az Optimalizálás lapon). A doksi
        # panasza: „két külön kinézet ugyanarra a paraméterre".
        #
        # A tartomány-adat OLCSÓ (csak a stratégia configját olvassa, nem kell
        # hozzá árfolyam-előzmény), ezért itt, az ablak felépítésekor betölthető.
        # A walk-forward ablakok — amikhez parquet kell — maradnak lustán az
        # Optimalizálás lapon.
        from core import opt_plan as _op
        from strategy.settings import load_strategy_config as _lsc
        try:
            self._opt_cfg_cache = _lsc(self.strategy.name).get("optimizer", {}) or {}
        except Exception:
            self._opt_cfg_cache = {}
        self._opt_rows = _op.param_rows(self.root_cfg, self.symbol,
                                        self.strategy.name, self._opt_cfg_cache)
        _range_by_key = {r["key"]: r for r in self._opt_rows}
        self._skip_vars = {}
        self._range_vars = {}
        self._range_lbls = {}

        _by_cat: dict[str, list] = {}
        for k in self._keys:                     # self._keys már ábécésorrendben
            _by_cat.setdefault(_cat_of(k), []).append(k)
        _ordered = [c for c in _cat_ord if c in _by_cat] + \
                   [c for c in _by_cat if c not in _cat_ord]

        # Oszlop-fejléc. A „söprés" blokk (pipa + -tól/-ig/lépés + érték-szám)
        # AZT mondja meg, mit csinál az optimalizálás EZZEL a paraméterrel.
        for _c, (_t, _w) in enumerate((("Paraméter", 24), ("Érték", 8),
                                       ("", 3), ("-tól", 7), ("-ig", 7),
                                       ("lépés", 7), ("db", 4))):
            tk.Label(form, text=_t, bg=BG, fg=FG_GRAY_DIM, font=self._sf,
                     anchor="w", width=_w).grid(row=0, column=_c, sticky="w",
                                                padx=(0, 3))
        tk.Label(form, text="Megjegyzés (szerkeszthető)", bg=BG, fg=FG_GRAY_DIM,
                 font=self._sf, anchor="w").grid(row=0, column=7, sticky="w")
        form.grid_columnconfigure(7, weight=1)
        _NCOL = 8

        _r = 1
        for cat in _ordered:
            # Kategória-elválasztó fejléc (név + vékony vonal)
            hdr = tk.Frame(form, bg=BG)
            hdr.grid(row=_r, column=0, columnspan=_NCOL, sticky="we", pady=(8, 1))
            tk.Label(hdr, text=cat, bg=BG, fg=FG_BLUE, font=self._sf,
                     anchor="w").pack(side="left")
            tk.Frame(hdr, bg=BG_HEADER, height=1).pack(
                side="left", fill="x", expand=True, padx=(8, 0))
            _r += 1
            for k in _by_cat[cat]:
                _rr = _range_by_key.get(k)
                # A JEL-osztályú paraméter neve más színnel: az újraszámoltatja a
                # teljes belépő-listát (drága), a végrehajtási csak szűr/méretez.
                _kfg = FG_WHITE
                if _rr is not None:
                    _kfg = FG_YELLOW if _rr["cls"] == "signal" else FG_BLUE
                tk.Label(form, text=k, bg=BG, fg=_kfg, font=self._sf,
                         anchor="w", width=24).grid(row=_r, column=0, sticky="w", pady=1)
                e = tk.Entry(form, width=8, bg=BG_HEADER, fg=FG_WHITE,
                             font=self._sf, insertbackground=FG_WHITE)
                e.insert(0, str(self._src[k]))
                e.grid(row=_r, column=1, padx=(0, 3), pady=1, sticky="w")
                # Kézi átírásnál a korábbi backtest-eredmény elavul → a Mentés újraszámol.
                e.bind("<KeyRelease>", lambda ev: self._invalidate_bt())
                self.entries[k] = e

                # ── Söprési tartomány — CSAK ha van hangolható tartománya ───
                # Ami nincs az optimalizáló terében, annál a mezők üresen
                # maradnak: az „—" világosabban mondja, hogy ez a paraméter
                # rögzített, mint egy kitölthetőnek látszó, de hatástalan mező.
                if _rr is None:
                    tk.Label(form, text="—", bg=BG, fg=FG_GRAY_DIM, font=self._sf,
                             width=3, anchor="w").grid(row=_r, column=2, sticky="w")
                else:
                    bv = tk.BooleanVar(value=not _rr["skipped"])
                    self._skip_vars[k] = bv
                    tk.Checkbutton(form, variable=bv, bg=BG, fg=FG_WHITE,
                                   selectcolor=BG_HEADER, activebackground=BG,
                                   activeforeground=FG_WHITE,
                                   command=lambda kk=k: self._on_skip_change(kk)
                                   ).grid(row=_r, column=2, sticky="w")
                    _vars = {}
                    for _ci, _field in enumerate(("min", "max", "step"), start=3):
                        sv = tk.StringVar(value=self._fmt_range(_rr[_field]))
                        re_ = tk.Entry(form, textvariable=sv, width=7, bg=BG_HEADER,
                                       fg=FG_WHITE, insertbackground=FG_WHITE,
                                       relief="flat", font=self._sf)
                        re_.grid(row=_r, column=_ci, sticky="w", padx=(0, 3), pady=1)
                        # Enter ÉS fókusz-vesztés is ment: vagy leütöd az Entert,
                        # vagy csak továbbkattintasz — mindkettő „kész vagyok".
                        re_.bind("<Return>",
                                 lambda _ev, kk=k: self._on_range_change(kk))
                        re_.bind("<FocusOut>",
                                 lambda _ev, kk=k: self._on_range_change(kk))
                        _vars[_field] = sv
                    self._range_vars[k] = _vars
                    _nl = tk.Label(form, text=str(_rr["values"]), bg=BG,
                                   fg=FG_GRAY, font=self._sf, width=4, anchor="w")
                    _nl.grid(row=_r, column=6, sticky="w")
                    self._range_lbls[k] = _nl

                # Megjegyzés — szerkeszthető; a Mentés a stratégia-configba írja vissza.
                ce = tk.Entry(form, bg=BG_HEADER, fg=FG_GRAY, font=self._sf,
                              insertbackground=FG_WHITE, relief="flat")
                ce.insert(0, (_pmeta.get(k, {}) or {}).get("comment", ""))
                ce.grid(row=_r, column=7, sticky="we", padx=(0, 2), pady=1)
                self._comment_entries[k] = ce
                _r += 1

        # A tartomány-szerkesztés visszajelzése (mentve / hibás → visszaállt).
        self._range_err = tk.Label(body, text="", bg=BG, fg=FG_RED, font=self._sf,
                                   anchor="w", justify="left")
        self._range_err.pack(anchor="w", padx=10)
        tk.Label(body, bg=BG, fg=FG_GRAY_DIM, font=self._sf, anchor="w",
                 justify="left", text=(
                     "A pipa: bevonjuk-e a paramétert a keresésbe (pár+stratégia "
                     "szintű). A -tól/-ig/lépés a STRATÉGIA közös tartománya — "
                     "minden instrumentumra hat.\n"
                     "Sárga = jel (újraszámolja a belépő-listát) · kék = végrehajtás "
                     "(csak szűr és méretez) · „—” = nincs hangolható tartománya."
                 )).pack(anchor="w", padx=10, pady=(2, 0))

        # ── Kapuk: mit tegyenek EZZEL a stratégiával ezen a páron ───────────
        self._build_gates(body)

        # A hibaüzenet a RÖGZÍTETT alsó sávba kerül (a görgethető törzsben
        # elgörgetve nem látszana — pedig épp a Mentés hibáját mondja).
        self.lbl_err = tk.Label(footer, text="", bg=BG, fg=FG_RED, font=self._sf)
        self.lbl_err.pack(anchor="w", padx=10)

        # ── Vezérlő-csoportok: Kockázatcsökkentés + Pozícióépítés ───────────
        # Logikai tiltás: a nem releváns vezérlők ELREJTVE (a preset/runner szerint).
        # A Backtest gomb ugyanezt méri; a Live-on per-pár állapotba ment.
        from core import rr_state as _rrs
        from core import risk_reduction as _rrx
        from core import build_state as _bst
        self._rrs, self._bst = _rrs, _bst
        self._EXIND_NAME = {"supertrend": "Supertrend", "wpr": "WPR",
                            "divergence": "Divergencia"}
        self._EXIT_PARAM_SPEC = {
            "supertrend": [("st_period", "Per"), ("st_multiplier", "Szorzó")],
            "wpr":        [("wpr_period", "Per"), ("wpr_ma_period", "MA")],
            "divergence": [("osc", "Oszc"), ("div_period", "Per"), ("div_pivot", "Pivot")],
        }
        self._EXIT_TIP = {
            "st_period": "Supertrend periódus (az ATR-ablak hossza).",
            "st_multiplier": "Supertrend ATR-szorzó — nagyobb = lazább sáv, később zár.",
            "wpr_period": "WPR periódus.", "wpr_ma_period": "A WPR mozgóátlagának periódusa (ezt keresztezi).",
            "osc": "Oszcillátor a divergenciához: rsi vagy cci.",
            "div_period": "A divergencia-oszcillátor periódusa.",
            "div_pivot": "Pivot-szélesség — hány gyertya erősíti meg a csúcsot/mélyet.",
        }

        ctl = tk.Frame(body, bg=BG)
        ctl.pack(anchor="w", fill="x", padx=10, pady=(6, 0))

        # ── 1. csoport: Kockázatcsökkentés (ha már bent vagy) ────────────────
        rrg = tk.LabelFrame(ctl, text=" Kockázatcsökkentés (ha már bent vagy egy pozícióban) ",
                            bg=BG, fg=FG_BLUE, font=self._sf, labelanchor="nw")
        rrg.pack(anchor="w", fill="x")
        row = tk.Frame(rrg, bg=BG)
        row.pack(anchor="w", padx=6, pady=4)
        tk.Label(row, text="Preset:", bg=BG, fg=FG_GRAY, font=self._sf).grid(row=0, column=0, sticky="w")
        self._rr_name = tk.StringVar(value=_rrs.NAME.get(_rrs.get_preset(self.symbol), "Ki"))
        om = tk.OptionMenu(row, self._rr_name, *[_rrs.NAME[p] for p in _rrs.CYCLE],
                           command=self._on_rr_change)
        _style_om(om, self._sf)
        om.grid(row=0, column=1, padx=(4, 0))
        _attach_tooltip(om, "Ki (semmi) = a stop MARAD, ahol a belépéskor volt — "
                            "se BE, se trailing (a nyers stratégia-él méréséhez). "
                            "BE + trailing = a korábbi „Ki”: breakeven a BE %-nál, "
                            "utána trailing. "
                            "Risky = felezett méret + azonnali BE 1R-nél. "
                            "Felező/Pajzs = 1R-nél 50%/75% zárás + a maradék (runner) külön kezelése. "
                            "Fibo = a belépő→TP táv 61,8%-ánál a stop BE-re (nincs zárás, "
                            "nincs trailing — a stop ott marad, a TP fut). "
                            "Harmados = 1/3–2/3: az alap-táv (1R) megtételekor a stop az "
                            "1/3-ra (profitban), célárnál a 2/3-ra. "
                            "Pajzs↔Fibo = auto: nagy mozgásnál (ATR >> átlag) Fibo, "
                            "különben Pajzs — belépéskor dől el.")

        # Óvatos méret — Ki-nél elrejtve; Riskynél alapból pipa (de átállítható)
        _c0 = _rrs.get_cautious(self.symbol)
        if _c0 is None:
            _c0 = _rrx.wants_cautious_size(_rrs.get_preset(self.symbol))
        self._cautious_var = tk.BooleanVar(value=bool(_c0))
        self._cautious_cb = tk.Checkbutton(
            row, text="Óvatos méret", variable=self._cautious_var,
            bg=BG, fg=FG_GRAY, selectcolor=BG_HEADER, font=self._sf,
            activebackground=BG, activeforeground=FG_WHITE,
            command=self._on_cautious_change)
        self._cautious_cb.grid(row=0, column=2, padx=(10, 0))
        _attach_tooltip(self._cautious_cb, "Felezett belépő-méret. A Risky mindig felez; "
                                           "Felező/Pajzsnál extra óvatosságként bekapcsolható.")

        # Runner — csak Felező/Pajzsnál (a részleges zárás UTÁNI maradék stopja)
        self._runner_frame = tk.Frame(row, bg=BG)
        self._runner_frame.grid(row=0, column=3, padx=(10, 0), sticky="w")
        tk.Label(self._runner_frame, text="Runner:", bg=BG, fg=FG_GRAY,
                 font=self._sf).pack(side="left")
        self._runner_name = tk.StringVar(
            value=_rrs.RUNNER_NAME.get(_rrs.get_runner(self.symbol), "Trailing"))
        omr = tk.OptionMenu(self._runner_frame, self._runner_name,
                            *[_rrs.RUNNER_NAME[r] for r in _rrs.RUNNERS],
                            command=self._on_runner_change)
        _style_om(omr, self._sf)
        omr.pack(side="left", padx=(4, 0))
        _attach_tooltip(self._runner_frame,
                        "A Felező/Pajzs részleges zárása UTÁN maradó darab (runner) stopja: "
                        "Trailing (követ) / Marad távol (eredeti stop) / BE (belépőre) / "
                        "Kiszállási jel (indikátorra zár).")

        # Cost-cut — idő-stop, bármely presettel kombinálható (Ki-vel is)
        self._cc_frame = tk.Frame(row, bg=BG)
        self._cc_frame.grid(row=0, column=5, padx=(10, 0), sticky="w")
        self._cc_var = tk.BooleanVar(value=_rrs.get_cost_cut(self.symbol))
        _ccb = tk.Checkbutton(self._cc_frame, text="Cost-cut", variable=self._cc_var,
                              bg=BG, fg=FG_GRAY, selectcolor=BG_HEADER, font=self._sf,
                              activebackground=BG, activeforeground=FG_WHITE,
                              command=self._on_cost_cut_change)
        _ccb.pack(side="left")
        self._cc_bars_var = tk.StringVar(value=str(_rrs.get_cost_cut_bars(self.symbol)))
        _cce = tk.Entry(self._cc_frame, textvariable=self._cc_bars_var, width=4,
                        bg=BG_HEADER, fg=FG_WHITE, font=self._sf, relief="flat",
                        insertbackground=FG_WHITE)
        _cce.pack(side="left", padx=(4, 0))
        _cce.bind("<FocusOut>", self._on_cost_cut_bars_save)
        _cce.bind("<Return>",   self._on_cost_cut_bars_save)
        _attach_tooltip(self._cc_frame,
                        "Idő-stop (tananyag): ha ennyi fő-gyertya (M15) után a pozíció "
                        "még veszteséges, piaci áron zárjuk — a kanóc/zaj korai levágása "
                        "töredék-R veszteséggel. Bármely presettel kombinálható.")

        # Exit — csak Felező/Pajzs + Runner=Kiszállási jel (a maradékot indikátor zárja)
        self._exit_frame = tk.Frame(row, bg=BG)
        self._exit_frame.grid(row=0, column=4, padx=(10, 0), sticky="w")
        tk.Label(self._exit_frame, text="Exit:", bg=BG, fg=FG_GRAY,
                 font=self._sf).pack(side="left")
        _exind = _rrs.get_exit_config(self.symbol).get("indicator", "supertrend")
        self._exit_ind_name = tk.StringVar(value=self._EXIND_NAME.get(_exind, "Supertrend"))
        ome = tk.OptionMenu(self._exit_frame, self._exit_ind_name,
                            *self._EXIND_NAME.values(), command=self._on_exit_ind_change)
        _style_om(ome, self._sf)
        ome.pack(side="left", padx=(4, 0))
        _attach_tooltip(ome, "Melyik indikátor zárja a maradékot: Supertrend-flip / "
                             "WPR-átzárás / Divergencia.")
        self._exit_pfrm = tk.Frame(self._exit_frame, bg=BG)
        self._exit_pfrm.pack(side="left", padx=(6, 0))
        self._exit_param_vars = {}
        self._rebuild_exit_params()

        # ── BE + trailing — a preset SAJÁT paraméterei (v1.96.0) ─────────────
        # Korábban a Stratégia Paraméterek „Végrehajtás" kategóriájában ültek,
        # MINDEN preseten láthatóan — holott a legtöbbön semmit nem csináltak
        # (Fibo/Harmados: soha; Felező/Pajzs runner=keep/BE: soha). Itt a helyük,
        # és CSAK azok látszanak, amelyek az adott preseten tényleg hatnak
        # (`core.risk_reduction.be_trail_active` — közös igazságforrás a
        # felületnek és a jövőbeli rr-optimalizálásnak).
        _bt_row = tk.Frame(rrg, bg=BG)
        _bt_row.pack(anchor="w", padx=6, pady=(0, 4))
        self._bt_frames = {}
        self._bt_vars = {}
        _BT_META = [
            ("breakeven_pct", "BE %",
             "A TP hány részénél megy az SL a belépőre (0 = nincs BE).\n"
             "Csak a 'BE + trailing' preseten hat — a Risky azonnal BE-zik."),
            ("trail_activation_atr", "Trail indul",
             "Ennyi ATR-nyi profit UTÁN indul a trailing.\n"
             "A Risky azonnal trailel, ezért ott nem látszik."),
            ("trail_distance_atr", "Trail táv",
             "Ennyi ATR-rel követi a stop az árat.\n"
             "Riskynél a motor még felezi is ezt a távolságot."),
        ]
        _spec0 = _rrs.spec_for(self.symbol)
        for _k, _lbl, _tip in _BT_META:
            _f = tk.Frame(_bt_row, bg=BG)
            tk.Label(_f, text=f"{_lbl}:", bg=BG, fg=FG_GRAY,
                     font=self._sf).pack(side="left")
            _v = tk.StringVar(value=f"{float(_spec0.get(_k, 0)):g}")
            _e = tk.Entry(_f, textvariable=_v, width=5, bg=BG_HEADER, fg=FG_WHITE,
                          font=self._sf, relief="flat", insertbackground=FG_WHITE)
            _e.pack(side="left", padx=(2, 0))
            _e.bind("<FocusOut>", lambda _ev, k=_k: self._on_be_trail_save(k))
            _e.bind("<Return>",   lambda _ev, k=_k: self._on_be_trail_save(k))
            _attach_tooltip(_f, _tip)
            self._bt_frames[_k] = _f
            self._bt_vars[_k] = _v

        # ── 2. csoport: Pozícióépítés (külön tengely) ────────────────────────
        # A kockázatcsökkentés ALATT (nem mellette, mint korábban): annak a sora
        # Pajzs + Kiszállási jelnél hosszú, mellette ez kilógott az ablakból —
        # a Backtest-ablakkal EGYEZŐ elrendezés.
        bldg = tk.LabelFrame(ctl, text=" Pozícióépítés (ráépítés a nyerőre) ",
                             bg=BG, fg=FG_BLUE, font=self._sf, labelanchor="nw")
        bldg.pack(anchor="w", fill="x", pady=(6, 0))
        brow = tk.Frame(bldg, bg=BG)
        brow.pack(anchor="w", padx=6, pady=4)
        tk.Label(brow, text="Építés:", bg=BG, fg=FG_GRAY, font=self._sf).pack(side="left")
        self._build_mode_name = tk.StringVar(value=_bst.NAME.get(_bst.get_mode(self.symbol), "Ki"))
        omb = tk.OptionMenu(brow, self._build_mode_name, *_bst.NAME.values(),
                            command=self._on_build_mode_change)
        _style_om(omb, self._sf)
        omb.pack(side="left", padx=(4, 0))
        _attach_tooltip(omb, "Ki / Kézi (a +gombbal TE építesz) / Auto (a motor magától). "
                             "Backtestben: Auto mindig; a Kézi CSAK R-alapú triggernél "
                             "modellezhető (az determinisztikus).")
        from core import position_build as _pb
        self._pb = _pb
        _bc0 = _bst.get_config(self.symbol)
        # Faktor — csak Építés ≠ Ki
        self._build_faktor_frame = tk.Frame(brow, bg=BG)
        tk.Label(self._build_faktor_frame, text="Faktor:", bg=BG, fg=FG_GRAY,
                 font=self._sf).pack(side="left")
        self._build_sf_var = tk.StringVar(value=str(_bc0.get("size_factor", 0.7)))
        _fe = tk.Entry(self._build_faktor_frame, textvariable=self._build_sf_var, width=5,
                       bg=BG_HEADER, fg=FG_WHITE, font=self._sf, relief="flat",
                       insertbackground=FG_WHITE)
        _fe.pack(side="left", padx=(2, 0))
        _fe.bind("<FocusOut>", self._on_build_faktor_save)
        _fe.bind("<Return>",   self._on_build_faktor_save)
        _attach_tooltip(self._build_faktor_frame,
                        "Piramidális méret-szorzó: minden ráépítés = előző × Faktor "
                        "(min_lot-ig csökken). — MENNYIT (a MIKOR a Trigger).")
        # Trigger — csak Építés ≠ Ki
        self._build_trig_frame = tk.Frame(brow, bg=BG)
        tk.Label(self._build_trig_frame, text="Trigger:", bg=BG, fg=FG_GRAY,
                 font=self._sf).pack(side="left")
        self._build_trig_name = tk.StringVar(
            value=_pb.TRIGGER_NAME.get(_bc0.get("trigger", _pb.TRIGGER_CANDLE), "Gyertyás"))
        omt = tk.OptionMenu(self._build_trig_frame, self._build_trig_name,
                            *_pb.TRIGGER_NAME.values(), command=self._on_build_trigger_change)
        _style_om(omt, self._sf)
        omt.pack(side="left", padx=(4, 0))
        _attach_tooltip(omt, "Gyertyás = trendkövető (új csúcs/mély-zárás). Fix R = +1R, +2R… "
                             "(állandó lépés). R-felező = a lépés zsugorodik (1R, +0.5R, +0.25R…) "
                             "→ egyre sűrűbben. Az R-alapúak determinisztikusak.")
        # R-lépés — csak R-alapú triggernél
        self._build_rstep_frame = tk.Frame(brow, bg=BG)
        tk.Label(self._build_rstep_frame, text="R-lépés:", bg=BG, fg=FG_GRAY,
                 font=self._sf).pack(side="left")
        self._build_rstep_var = tk.StringVar(value=str(_bc0.get("r_step", 1.0)))
        _re = tk.Entry(self._build_rstep_frame, textvariable=self._build_rstep_var, width=4,
                       bg=BG_HEADER, fg=FG_WHITE, font=self._sf, relief="flat",
                       insertbackground=FG_WHITE)
        _re.pack(side="left", padx=(2, 0))
        _re.bind("<FocusOut>", self._on_build_rstep_save)
        _re.bind("<Return>",   self._on_build_rstep_save)
        _attach_tooltip(self._build_rstep_frame,
                        "Az (első) lépés R-ben (alap 1R). Fix R-nél a rács-köz; R-felezőnél a kezdő lépés.")
        # Zsugorodás — csak R-felezőnél
        self._build_rshrink_frame = tk.Frame(brow, bg=BG)
        tk.Label(self._build_rshrink_frame, text="Zsug:", bg=BG, fg=FG_GRAY,
                 font=self._sf).pack(side="left")
        self._build_rshrink_var = tk.StringVar(value=str(_bc0.get("r_shrink", 0.5)))
        _rse = tk.Entry(self._build_rshrink_frame, textvariable=self._build_rshrink_var, width=4,
                        bg=BG_HEADER, fg=FG_WHITE, font=self._sf, relief="flat",
                        insertbackground=FG_WHITE)
        _rse.pack(side="left", padx=(2, 0))
        _rse.bind("<FocusOut>", self._on_build_rshrink_save)
        _rse.bind("<Return>",   self._on_build_rshrink_save)
        _attach_tooltip(self._build_rshrink_frame,
                        "A lépés szorzója add-onként (0.5 = felező; 2/3; 3/4…). Kisebb = "
                        "gyorsabban sűrűsödik. Konvergál egy R-plafonhoz.")

        self._update_rr_visibility()

        # Lot-létra tipp (a részleges záráshoz ≥2× min_lot kell)
        _ml = (self.cfg.get("pairs", {}).get(self.symbol, {}) or {}).get("min_lot", 0.01)
        tk.Label(body, text=f"(A Felező/Pajzs részleges záráshoz ≥2× min_lot ({_ml}) "
                             f"kell; kisebbnél Risky/BE-re esik vissza. A Backtest a "
                             f"ténylegesen alkalmazott technikát mutatja.)",
                 bg=BG, fg=FG_GRAY_DIM, font=self._sf, justify="left",
                 wraplength=560).pack(anchor="w", padx=10, pady=(1, 0))

        # ── Backtest-eredmény sor (a Backtest gomb tölti) — a rögzített sávban,
        #    hogy a futás állapota („Backtest fut…", letöltés) mindig látszódjon.
        self.lbl_bt = tk.Label(footer, text="", bg=BG, fg=FG_GRAY_DIM, font=self._sf,
                               justify="left", wraplength=560)
        self.lbl_bt.pack(anchor="w", padx=10, pady=(0, 2))

        # ── Gombsor ─────────────────────────────────────────────────────────
        # EGYETLEN Mentés: elmenti az órákat + a paramétereket (aktív készlet),
        # és ha ez a paraméter-kombináció még nincs a trials CSV-ben, ODA IS
        # beírja — kötelezően backtest-eredménnyel (ha nincs friss eredmény, a
        # Mentés magától lefuttatja a backtestet, majd ment). A régi „Ment új
        # sorszámként" így feleslegessé vált (a CSV-be írás automatikus).
        btns = tk.Frame(footer, bg=BG)
        btns.pack(pady=10)
        self._btn_save = tk.Button(btns, text="Mentés", bg=BTN_PLAY_BG,
                                   fg=BTN_PLAY_FG, relief="flat", font=self._sf,
                                   command=self._save)
        self._btn_save.pack(side="left", padx=6)
        self._btn_bt = tk.Button(btns, text="Backtest", bg=BTN_BT_BG, fg=BTN_BT_FG,
                                 relief="flat", font=self._sf,
                                 command=self._open_backtest_window)
        self._btn_bt.pack(side="left", padx=6)
        tk.Button(btns, text="Trials CSV", bg=BTN_BT_BG, fg=BTN_BT_FG, relief="flat",
                  font=self._sf, command=self._open_trials).pack(side="left", padx=6)
        # MT4-es manuális visszajátszás: EBBEN az ablakban van a helye, mert a
        # belépők STRATÉGIA-FÜGGŐK — más stratégia más jelzéseket ad ugyanarra a
        # hétre. (Egy globális gomb nem tudná, melyiket exportálja.)
        tk.Button(btns, text="MT4 visszajátszás", bg=BTN_BT_BG, fg=BTN_BT_FG,
                  relief="flat", font=self._sf,
                  command=self._open_mt4_export).pack(side="left", padx=6)
        tk.Button(btns, text="Mégse", bg=BTN_DIS_BG, fg=BTN_DIS_FG, relief="flat",
                  font=self._sf, command=popup.destroy).pack(side="left", padx=6)

        self._fit_to_screen(popup, body, footer)
        # Az ELSŐ lap feltöltése — most már van `self._shell` (lásd `_on_tab`).
        self._build_overview_tab()

    def _open_mt4_export(self):
        """MT4-es manuális visszajátszás: tól-ig ablak kiírása a viz-fájlba.

        ⚠ STRATÉGIA-FÜGGŐ: az exportot EZZEL az ablakkal nyitott stratégiával
        (`self.strategy.name`) számoljuk — más stratégia ugyanarra a hétre MÁS
        belépőket ad. Ezért van a gomb itt, és nem egy globális menüben.

        Külön fájlba (`_BT`) ír, hogy az élő motor pillanatképét ne írja felül.
        A valós kötések alapból KIMARADNAK: manuális teszten azok a megfejtés."""
        import threading
        from datetime import date, timedelta

        pop = tk.Toplevel(self.popup)
        pop.title(f"MT4 visszajátszás — {self.symbol} / {self.strategy.name}")
        pop.configure(bg=BG)
        pop.transient(self.parent)

        tk.Label(pop, text=f"{self.symbol}  ·  stratégia: {self.strategy.name}",
                 bg=BG, fg=FG_WHITE, font=self._sf).grid(row=0, column=0, columnspan=3,
                                                   sticky="w", padx=10, pady=(10, 2))
        tk.Label(pop, text="A jelzéseket EZZEL a stratégiával számoljuk.",
                 bg=BG, fg=FG_GRAY_DIM, font=self._sf).grid(
                     row=1, column=0, columnspan=3, sticky="w", padx=10)

        _to = date.today()
        _fr = _to - timedelta(days=12)
        v_from = tk.StringVar(value=_fr.isoformat())
        v_to = tk.StringVar(value=_to.isoformat())
        v_trades = tk.BooleanVar(value=False)

        tk.Label(pop, text="-tól (ÉÉÉÉ-HH-NN):", bg=BG, fg=FG_WHITE, font=self._sf).grid(
            row=2, column=0, sticky="e", padx=(10, 4), pady=(10, 2))
        tk.Entry(pop, textvariable=v_from, width=14, font=self._sf).grid(
            row=2, column=1, sticky="w", pady=(10, 2))
        tk.Label(pop, text="-ig:", bg=BG, fg=FG_WHITE, font=self._sf).grid(
            row=3, column=0, sticky="e", padx=(10, 4))
        tk.Entry(pop, textvariable=v_to, width=14, font=self._sf).grid(
            row=3, column=1, sticky="w")

        tk.Checkbutton(pop, text="A bot VALÓS kötései is látszódjanak (manuális teszthez NE)",
                       variable=v_trades, bg=BG, fg=FG_GRAY_DIM, selectcolor=BG,
                       activebackground=BG, font=self._sf).grid(
                           row=4, column=0, columnspan=3, sticky="w", padx=10, pady=(8, 2))

        lbl = tk.Label(pop, text="", bg=BG, fg=FG_GRAY_DIM, font=self._sf,
                       justify="left", wraplength=460)
        lbl.grid(row=5, column=0, columnspan=3, sticky="w", padx=10, pady=(6, 2))

        btn = tk.Button(pop, text="Export", bg=BTN_PLAY_BG, fg=BTN_PLAY_FG,
                        relief="flat", font=self._sf)
        btn.grid(row=6, column=0, padx=10, pady=10, sticky="w")
        tk.Button(pop, text="Bezár", bg=BTN_DIS_BG, fg=BTN_DIS_FG, relief="flat",
                  font=self._sf, command=pop.destroy).grid(row=6, column=1,
                                                           pady=10, sticky="w")

        def _run():
            btn.config(state="disabled")
            lbl.config(text="Export fut…", fg=FG_GRAY_DIM)

            def _work():
                # A KÖZÖS exportáló út (a CLI is ezt hívja) — nincs másolt logika.
                from tools.viz_export import export_window
                try:
                    ok, msg = export_window(
                        self.symbol, v_from.get().strip(), v_to.get().strip(),
                        strategy_name=self.strategy.name, suffix="_BT",
                        show_trades=bool(v_trades.get()), cfg=self.root_cfg,
                        status=lambda m: pop.after(0, lambda: lbl.config(text=m)))
                except Exception as ex:
                    ok, msg = False, f"Hiba: {ex}"
                def _done():
                    lbl.config(text=msg, fg=(FG_GREEN if ok else FG_RED))
                    btn.config(state="normal")
                pop.after(0, _done)

            threading.Thread(target=_work, daemon=True, name="MT4Export").start()

        btn.config(command=_run)

    def _on_tab(self, name):
        # ⚠ A TabShell a KONSTRUKTORÁBAN megmutatja az első lapot — vagyis ez a
        # visszahívás lefut, mielőtt a `self._shell` értéket kapna. A lapokat
        # ilyenkor még nem lehet felépíteni (nincs mihez kérni az oldalt); az
        # első lap feltöltése a `_build` végén, expliciten történik.
        if not hasattr(self, "_shell"):
            return
        """A „Leírás" lap LUSTA feltöltése (`strategy/docs/<név>.md`).

        Ha a fájl nincs, a nézet KIÍRJA az elvárt útvonalat — így a hiányzó doksi
        nem üres lap, hanem felszólítás. Mindig a lemezről olvas, tehát
        szerkesztés után újranyitva azonnal friss (nincs gyorsítótár, ami
        elavulhatna)."""
        if name == "Áttekintés":
            # LUSTA + MINDIG FRISS: az állapot (él/áll, kézi szerkesztés,
            # kapuk) menet közben változhat, egy gyorsítótárazott lap pedig
            # éppen a figyelmeztetéseket mutatná elavultan.
            self._build_overview_tab()
            return
        if name == "Futtatás":
            self._build_run_tab()
            return
        if name == "Eredmények":
            # LUSTA: az 500 soros CSV beolvasása és a tábla felépítése nem
            # kell minden ablak-megnyitáskor. Minden megjelenítéskor ÚJRAOLVAS:
            # futó optimalizálás alatt a CSV 10 trialonként frissül, tehát a
            # lap visszakattintása friss allast mutat (nem elavult masolatot).
            self._build_results_tab()
            return
        if name != "Leírás":
            return
        from dashboard import md_view
        try:
            md_view.render(self._shell.page("Leírás"), self.strategy.doc_text(),
                           source=str(self.strategy.doc_path()))
        except Exception as e:
            self.lbl_err.config(text=f"A leírás nem nyitható meg: {e}")

    # ── „Futtatás” lap — a backtest, BEÁGYAZVA ─────────────────────────────
    # A doksi panasza: ugyanazt a paramétert két külön kinézetben kellett
    # kezelni. A backtest innentől nem külön ablak, hanem lap — a paraméterek
    # mellett, ugyanabban az ablakban.
    #
    # ⚠ A tartalom NEM másolat: ugyanaz a `BacktestDialog` épül ide, csak egy
    # keretbe ablak helyett. Egy „majdnem ugyanolyan" második változat pont
    # abban térne el, ami ritkán fut (megszakítás, hibaág, MT5-export), és az
    # nem derülne ki.

    def _build_run_tab(self):
        page = self._shell.page("Futtatás")
        if getattr(self, "_run_tab", None) is not None:
            # ⚠ ÚJRAÉPÍTÉS, ha a paraméterek közben változtak. A backtest a
            # MEGNYITÁSKORI paraméterekkel dolgozik; ha a Paraméter lapon
            # átírtál valamit, egy régi példány CSENDBEN a régi értékekkel
            # futna — és a lap fejléce mégis az újakat sugallná.
            cur = self._collect_params()
            if cur is not None and cur == getattr(self, "_run_params", None):
                return
            self._run_tab.shutdown()
            self._run_tab = None
        for w in page.winfo_children():
            w.destroy()

        params = self._collect_params()
        if params is None:
            return                      # hibás mező — a lbl_err már szól róla
        pair_cfg = self.cfg.get("pairs", {}).get(self.symbol)
        if not isinstance(pair_cfg, dict):
            tk.Label(page, text="Nincs pár-config ehhez az instrumentumhoz.",
                     bg=BG, fg=FG_RED, font=self._sf).pack(anchor="w", padx=12,
                                                           pady=12)
            return
        # ── A lap KÉT részből áll ──────────────────────────────────────────
        # Fent a TERV (mi fog történni és milyen feltételek mellett), alatta a
        # tényleges futtató. A korábbi külön „Optimalizálás" lap tartalma ide
        # költözött: ugyanarra a kérdésre válaszolt, csak más számmal.
        plan_box = tk.Frame(page, bg=BG)
        plan_box.pack(side="top", fill="x")
        bt_host = tk.Frame(page, bg=BG)
        bt_host.pack(side="top", fill="both", expand=True)

        self._build_plan_strip(plan_box)

        from dashboard.backtest_dialog import BacktestDialog
        self._run_params = dict(params)
        self._run_tab = BacktestDialog(
            self.popup, self.symbol, self.cfg, self.strategy, params, pair_cfg,
            self._rr_spec_from_ui(), self._hf, self._sf,
            on_result=self._on_bt_window_result,
            preset_name=self._rr_name.get(),
            on_apply_params=self._apply_params_from_bt,
            host=bt_host, on_state=self._on_run_state)

    # ── A TERV-SÁV: mi fog történni, ha elindítod ──────────────────────────
    # A felhasználó észrevétele: „a Paraméter, Futtatás, Optimalizálás igazából
    # egy és ugyanaz — de valahogy mégsem." Igaza volt, és a törés itt van:
    #
    #     Paraméter        → MILYEN érték?
    #     Futtatás         → futtasd le EGYSZER
    #     Optimalizálás    → futtasd le SOKSZOR
    #
    # A második és a harmadik UGYANAZ a kérdés, más számmal — és a számot nem
    # kell külön beállítani, kiderül abból, hány paramétert pipáltál be
    # (`core.opt_plan.run_plan`). Ezért lett a három lapból kettő.

    def _build_plan_strip(self, box):
        from core import opt_plan as _op
        from core import gates as _gt
        from strategy.settings import load_strategy_config as _lsc

        try:
            self._opt_cfg_cache = _lsc(self.strategy.name).get("optimizer", {}) or {}
        except Exception:
            self._opt_cfg_cache = {}
        df15 = None
        try:
            from trading.backtest import load_data
            df15, _ = load_data(self.symbol)
        except Exception:
            pass
        try:
            plan = _op.build(self.root_cfg, self.symbol, self.strategy,
                             self._opt_cfg_cache, df_m15=df15)
        except Exception:
            plan = None
        self._opt_plan = plan

        head = tk.Frame(box, bg=BG)
        head.pack(anchor="w", fill="x", padx=12, pady=(10, 0))
        tk.Label(head, text="Mi fog történni", bg=BG, fg=FG_WHITE,
                 font=self._hf).pack(side="left")
        self._plan_btn = tk.Button(head, text="Indítás", bg=BTN_PLAY_BG,
                                   fg=BTN_PLAY_FG, relief="flat", font=self._sf,
                                   command=self._start_planned)
        self._plan_btn.pack(side="right", padx=(8, 0))

        self._tuned_lbl = tk.Label(box, bg=BG, fg=FG_GRAY, font=self._sf,
                                   anchor="w", justify="left")
        self._tuned_lbl.pack(anchor="w", padx=12)
        self._space_lbl = tk.Label(box, bg=BG, fg=FG_GRAY_DIM, font=self._sf,
                                   anchor="w", justify="left")
        self._space_lbl.pack(anchor="w", padx=12, pady=(0, 4))

        # ── A FELTÉTELEK: időszakok és kapuk (a volt Optimalizálás lapról) ──
        if plan:
            cond = tk.Frame(box, bg=BG)
            cond.pack(anchor="w", fill="x", padx=12)
            w = plan["wf"]
            _txt = (f"Walk-forward: {w['splits']} ablak × ({w['train_months']} hó "
                    f"tanulás + {w['test_months']} hó vizsga)")
            if plan["windows"]:
                _last = plan["windows"][-1]
                _txt += (f"  ·  utolsó vizsga: {str(_last['test_start'])[:10]} → "
                         f"{str(_last['test_end'])[:10]}")
            tk.Label(cond, text=_txt, bg=BG, fg=FG_GRAY_DIM, font=self._sf,
                     anchor="w").pack(anchor="w")
            if not plan["windows"]:
                tk.Label(cond, bg=BG, fg=FG_RED, font=self._sf, anchor="w",
                         justify="left", wraplength=820,
                         text=("⚠ Egyetlen walk-forward ablak sem áll össze — kevés "
                               "az előzmény. Az optimalizálás nem indul el.")
                         ).pack(anchor="w")
            if not plan["exec_gates"]:
                tk.Label(cond, bg=BG, fg=FG_RED, font=self._sf, anchor="w",
                         justify="left", wraplength=820,
                         text=("⚠ A végrehajtási kapuk KI vannak kapcsolva az "
                               "optimalizálásban — a kapott paraméterek olyan "
                               "világból jönnek, ami élesben nem létezik.")
                         ).pack(anchor="w")
            else:
                act = sorted(k for k, e in (plan["gate_effects"] or {}).items()
                             if e != _gt.EFFECT_NONE)
                tk.Label(cond, bg=BG, fg=FG_GRAY_DIM, font=self._sf, anchor="w",
                         text=("Kapuk: " + (", ".join(
                             f"{_gt.label_of(k)} "
                             f"({_gt.EFFECT_LABEL.get(plan['gate_effects'][k], '')})"
                             for k in act) if act else "egyik sem aktív"))
                         ).pack(anchor="w")
            tk.Label(cond, bg=BG, fg=FG_GRAY_DIM, font=self._sf, anchor="w",
                     justify="left", wraplength=820,
                     text=("A mentett minősítés CSAK a vizsga-ablakok kötéseiből "
                           "számol. A paramétereket és a tartományokat a "
                           "Paraméter lapon állítod.")).pack(anchor="w")

        # ── SÖPRÉS: a rajz és a mércéje (1–2 hangolt paraméternél) ──────────
        self._sweep_box = tk.Frame(box, bg=BG)
        self._sweep_box.pack(anchor="w", fill="x", padx=12, pady=(4, 0))
        _sb = tk.Frame(self._sweep_box, bg=BG)
        _sb.pack(anchor="w", fill="x")
        tk.Label(_sb, text="mérce", bg=BG, fg=FG_GRAY_DIM,
                 font=self._sf).pack(side="left", padx=(0, 3))
        self._sw_metric = tk.StringVar(value="total_pnl")
        _mm = tk.OptionMenu(_sb, self._sw_metric, "total_pnl", "profit_factor",
                            "win_rate", "trades", "max_drawdown")
        _mm.config(bg=BG_HEADER, fg=FG_WHITE, relief="flat", font=self._sf,
                   highlightthickness=0, activebackground=BG_HEADER)
        _mm["menu"].config(bg=BG_HEADER, fg=FG_WHITE, font=self._sf)
        _mm.pack(side="left", padx=(0, 10))
        self._sw_metric.trace_add("write", lambda *_a: self._redraw_sweep())
        self._sw_status = tk.Label(_sb, text="", bg=BG, fg=FG_GRAY, font=self._sf)
        self._sw_status.pack(side="left")
        self._sw_canvas = tk.Canvas(self._sweep_box, bg=BG, height=260,
                                    highlightthickness=0)
        self._sw_canvas.bind("<Configure>", lambda _e: self._redraw_sweep())
        self._sw_best = tk.Label(self._sweep_box, text="", bg=BG, fg=FG_GRAY,
                                 font=self._sf, anchor="w", justify="left")
        self._sw_rows, self._sw_axes = [], []
        # A söprés IDŐSZAKA a backtest mezőiből jön (egy helyen állítod) — a
        # `_start_sweep` onnan olvassa, ezért itt nincs külön dátum-mező.
        self._refresh_opt_space()

    def _on_run_state(self, running: bool):
        """A beágyazott backtest futás-állapota → a terv-sáv EGYETLEN gombja.

        Enélkül a gomb futás közben is „Indítás"-t mutatna, és egy második
        kattintás újraindítaná azt, ami épp fut."""
        try:
            if running:
                self._plan_btn.config(text="Megszakítás",
                                      command=self._run_tab._cancel)
            else:
                self._plan_btn.config(text="Indítás", state="normal",
                                      command=self._start_planned)
        except (tk.TclError, AttributeError):
            pass

    def _start_planned(self):
        """Az EGYETLEN Indítás gomb: a bepipált dimenziók száma dönti el, mi fut.

        ⚠ Ez nem kényelmi összevonás. Eddig ugyanaz a művelet (paraméter beállít
        → teljes futtatás → kiértékelés) HÁROM helyen indult, más-más néven, és
        a felhasználónak kellett fejben tartania, melyik mit jelent."""
        from core import opt_plan as _op
        rows = [dict(r, skipped=not self._skip_vars[r["key"]].get())
                for r in self._opt_rows if r["key"] in self._skip_vars]
        kind = _op.run_plan(rows, 0)["kind"]
        if kind == _op.KIND_SINGLE:
            # 0 hangolt → EGYETLEN futás: ez maga a backtest.
            if self._run_tab is not None:
                self._sweep_box.pack_forget()
                self._run_tab._start()
            return
        if kind in (_op.KIND_SWEEP, _op.KIND_GRID):
            self._sweep_box.pack(anchor="w", fill="x", padx=12, pady=(4, 0))
            self._sw_canvas.pack(fill="x", pady=(4, 2))
            self._sw_best.pack(anchor="w", pady=(0, 8))
            self._start_sweep()
            return
        # 3+ hangolt → OPTIMALIZÁLÁS. Az OPT a főképernyő vezérlője (külön
        # processz, folytatható study) — innen csak elindítjuk, ha a hívó
        # bekötötte; különben megmondjuk, hol van.
        self._sweep_box.pack_forget()
        if callable(getattr(self, "on_optimize", None)):
            try:
                self.on_optimize(self.symbol, self.strategy.name)
                self._sw_status.config(text="Optimalizálás elindítva.", fg=FG_GREEN)
                return
            except Exception as ex:
                self._sw_status.config(text=f"Indítási hiba: {ex}", fg=FG_RED)
                return
        self._sw_status.config(
            text=("Ennyi hangolt paraméternél az OPTIMALIZÁLÁS fut — azt a "
                  "főképernyő OPT gombja indítja (folytatható, külön processz). "
                  "Söpréshez pipálj ki mindent 1–2 paraméter kivételével."),
            fg=FG_YELLOW)

    # ── „Áttekintés” lap — mi ennek a párnak az ÁLLAPOTA ───────────────────
    # A kérés: „az első oldalon csak egy dashboard-szerű dolog lehetne, ahol
    # látod, hogy mikor kereskedik, meg a minőséget, meg ilyeneket."
    #
    # ⚠ A lap ÉRTÉKE nem a metrikák megismétlése — azok máshol is látszanak —,
    # hanem a FIGYELMEZTETÉSEK: azok az állapotok, amikben minden rendben
    # LÁTSZIK, közben nem (kézi szerkesztés a mentett minősítés után, kapu-
    # eltérés, szennyezett OOS). Ezek ma mind némák.

    _HOUR_H = 74            # az óra-sáv magassága képpontban

    def _build_overview_tab(self):
        page = self._shell.page("Áttekintés")
        for w in page.winfo_children():
            w.destroy()
        from core import overview as _ov
        from core import gates as _gt
        try:
            df15, _ = __import__("trading.backtest", fromlist=["x"]).load_data(self.symbol)
        except Exception:
            df15 = None
        try:
            o = _ov.build(self.root_cfg, self.symbol, self.strategy,
                          self.data or {}, df_m15=df15)
        except Exception as ex:
            tk.Label(page, text=f"Az áttekintés nem építhető: {ex}", bg=BG,
                     fg=FG_RED, font=self._sf).pack(anchor="w", padx=12, pady=12)
            return

        holder, body, _cv = _scrollable(page)
        holder.pack(side="top", fill="both", expand=True)

        # ── Fejléc: mi ez, és mit csinál MOST ──────────────────────────────
        head = tk.Frame(body, bg=BG)
        head.pack(anchor="w", fill="x", padx=12, pady=(10, 2))
        tk.Label(head, text=f"{o['symbol']}  ·  {o['strategy']}", bg=BG,
                 fg=FG_WHITE, font=self._hf).pack(side="left")
        _state_txt = {"live": "ÉL", "stopped": "ÁLLÍTVA"}.get(o["state"], o["state"] or "—")
        _state_fg = FG_GREEN if o["state"] == "live" else FG_GRAY
        tk.Label(head, text=f"   {_state_txt}", bg=BG, fg=_state_fg,
                 font=self._hf).pack(side="left")
        if o["mode"] == "signal":
            tk.Label(head, text="  · csak jelzés", bg=BG, fg=FG_YELLOW,
                     font=self._sf).pack(side="left")
        from dashboard import theme as _th
        _gfg = _th.color(o.get("grade_color_name") or "muted")
        tk.Label(head, text=f"   Minőség: {o['grade']}", bg=BG, fg=_gfg,
                 font=self._hf).pack(side="left")
        if o.get("grade_why"):
            tk.Label(head, text=f"  ({o['grade_why']})", bg=BG, fg=FG_GRAY_DIM,
                     font=self._sf).pack(side="left")

        s = o["summary"] or {}
        if s.get("trades"):
            _pf = s.get("profit_factor", 0) or 0
            tk.Label(body, bg=BG, fg=FG_GRAY, font=self._sf, anchor="w",
                     text=(f"Trade {int(s.get('trades', 0))} · "
                           f"Win {s.get('win_rate', 0) * 100:.0f}% · "
                           f"MaxDD {s.get('max_drawdown', 0) * 100:.1f}% · "
                           f"P&L {s.get('total_pnl', 0):+.0f}$ · "
                           f"PF {'∞' if _pf == float('inf') else f'{_pf:.2f}'}")
                     ).pack(anchor="w", padx=12)
        else:
            tk.Label(body, text="Nincs mentett minősítés.", bg=BG, fg=FG_GRAY_DIM,
                     font=self._sf).pack(anchor="w", padx=12)

        # ── Figyelmeztetések — ez a lap valódi haszna ──────────────────────
        if o["warnings"]:
            box = tk.Frame(body, bg=BG)
            box.pack(anchor="w", fill="x", padx=12, pady=(8, 2))
            _fg = {_ov.SEV_RISK: FG_RED, _ov.SEV_WARN: FG_YELLOW,
                   _ov.SEV_INFO: FG_GRAY_DIM}
            _ic = {_ov.SEV_RISK: "⚠", _ov.SEV_WARN: "!", _ov.SEV_INFO: "·"}
            for w in o["warnings"]:
                tk.Label(box, bg=BG, fg=_fg.get(w["sev"], FG_GRAY),
                         font=self._sf, anchor="w", justify="left",
                         wraplength=820,
                         text=f"{_ic.get(w['sev'], '·')}  {w['text']}"
                         ).pack(anchor="w")

        # ── MIKOR kereskedik ──────────────────────────────────────────────
        tk.Label(body, text="Mikor kereskedik", bg=BG, fg=FG_WHITE,
                 font=self._hf, anchor="w").pack(anchor="w", padx=12, pady=(12, 2))
        has_hours = any(h["pnl"] is not None for h in o["hours"])
        if not has_hours:
            tk.Label(body, bg=BG, fg=FG_GRAY_DIM, font=self._sf, anchor="w",
                     text=("Nincs óránkénti adat — az optimalizálás írja a mentett "
                           "minősítésbe. Futtass optimalizálást.")
                     ).pack(anchor="w", padx=12)
        else:
            cv = tk.Canvas(body, bg=BG, height=self._HOUR_H + 26,
                           highlightthickness=0)
            cv.pack(fill="x", padx=12, pady=(2, 0))
            cv.bind("<Configure>",
                    lambda _e, c=cv, hh=o["hours"]: self._draw_hours(c, hh))
            self._ov_canvas = cv
            tk.Label(body, bg=BG, fg=FG_GRAY_DIM, font=self._sf, anchor="w",
                     justify="left", wraplength=820, text=(
                         "Oszlop = az adott óra P&L-je a mentett minősítésből; a szám "
                         "alatta a kötésszám. A halvány órák a kereskedési órákon "
                         "KÍVÜL esnek.\n"
                         "⚠ Egy enyhén mínuszos óra 3 kötésből zaj, 300 kötésből "
                         "rendszeres veszteség — a kettőből ellentétes teendő "
                         "következik. Ezért van kiírva a kötésszám is.")
                     ).pack(anchor="w", padx=12, pady=(2, 0))

        # ── Kapuk / adat / kor ────────────────────────────────────────────
        tk.Label(body, text="Környezet", bg=BG, fg=FG_WHITE, font=self._hf,
                 anchor="w").pack(anchor="w", padx=12, pady=(12, 2))
        act = [k for k, e in (o["gates"] or {}).items() if e != _gt.EFFECT_NONE]
        tk.Label(body, bg=BG, fg=FG_GRAY, font=self._sf, anchor="w",
                 justify="left", text=(
                     "Kapuk: " + (", ".join(
                         f"{_gt.label_of(k)} ({_gt.EFFECT_LABEL.get(o['gates'][k], '')})"
                         for k in sorted(act)) if act else "egyik sem aktív"))
                 ).pack(anchor="w", padx=12)
        if o["data_from"] is not None:
            tk.Label(body, bg=BG, fg=FG_GRAY, font=self._sf, anchor="w",
                     text=(f"Előzmény: {str(o['data_from'])[:10]} … "
                           f"{str(o['data_to'])[:10]}")).pack(anchor="w", padx=12)
        _age = o["optimized_age_days"]
        tk.Label(body, bg=BG, fg=FG_GRAY, font=self._sf, anchor="w",
                 text=(f"Utolsó optimalizálás: {str(o['optimized_at'])[:10]}"
                       f"  ({_age:.0f} napja)" if _age is not None
                       else "Utolsó optimalizálás: —")).pack(anchor="w", padx=12,
                                                             pady=(0, 10))

    def _draw_hours(self, cv, hours):
        """A 24 órás sáv. Oszlop = P&L, alatta a kötésszám."""
        try:
            cv.delete("all")
            w = max(int(cv.winfo_width()), 320)
        except tk.TclError:
            return
        vals = [h["pnl"] for h in hours if h["pnl"] is not None]
        if not vals:
            return
        top = max(abs(min(vals)), abs(max(vals))) or 1.0
        pad = 24
        bw = (w - 2 * pad) / 24.0
        mid = self._HOUR_H / 2 + 4
        cv.create_line(pad, mid, w - pad, mid, fill=FG_GRAY_DIM)
        for i, h in enumerate(hours):
            x = pad + i * bw
            v = h["pnl"]
            if v is not None:
                hh = (abs(v) / top) * (self._HOUR_H / 2 - 6)
                # A tiltott óra HALVÁNY: látszik, hogy ott van eredmény, de nem
                # kereskedünk — enélkül a felhasználó nem értené, miért nincs
                # kötés egy nyereséges órában.
                col = (FG_GREEN if v > 0 else FG_RED) if h["allowed"] else FG_GRAY_DIM
                y0, y1 = (mid - hh, mid) if v > 0 else (mid, mid + hh)
                cv.create_rectangle(x + 1, y0, x + bw - 1, y1, fill=col, width=0)
            if i % 2 == 0:
                cv.create_text(x + bw / 2, self._HOUR_H + 8, text=f"{h['hour']:02d}",
                               fill=FG_GRAY_DIM, font=self._sf)
            if h.get("count"):
                cv.create_text(x + bw / 2, self._HOUR_H + 19, text=str(h["count"]),
                               fill=FG_GRAY_DIM, font=self._sf)

    # ── „Eredmények” lap — a trials CSV OLVASHATÓ formában ─────────────────
    # A doksi kérése: szűrhető, rendezhető tábla, típusos mezőkkel (DD = %), a
    # sorok színe az eredmény szerint, és ide költözik a CSV-gomb.

    def _build_results_tab(self):
        page = self._shell.page("Eredmények")
        # ⚠ MINDIG újraépítjük. Futó optimalizálás alatt a CSV 10 trialonként
        # frissül; egy gyorsítótárazott tábla azt sugallná, hogy nincs új
        # eredmény — pont az ellenkezőjét annak, amiért a lap készült.
        for w in page.winfo_children():
            w.destroy()
        from dashboard import results_table
        try:
            results_table.build(page, self.trials_csv,
                                {"small": self._sf, "header": self._hf},
                                on_export=self._open_trials)
        except Exception as ex:
            self.lbl_err.config(text=f"Az eredménytábla nem építhető: {ex}",
                                fg=FG_RED)

    def _start_sweep(self):
        """A bepipált 1–2 paraméter kimerítő végigpróbálása háttérszálon."""
        import threading
        from core import opt_plan as _op
        from core import sweep as _sw

        if self._sw_stop is not None:            # fut → megszakítás
            self._sw_stop.set()
            self._plan_btn.config(text="Megszakítás…", state="disabled")
            return

        rows = [dict(r, skipped=not self._skip_vars[r["key"]].get())
                for r in self._opt_rows if r["key"] in self._skip_vars]
        plan = _op.run_plan(rows, 0)
        if plan["kind"] not in (_op.KIND_SWEEP, _op.KIND_GRID):
            # ⚠ Nem csendes tétlenség: megmondjuk, MIT kell tenni.
            self._sw_status.config(
                text=("A söpréshez PONTOSAN 1 vagy 2 paraméter legyen bepipálva "
                      f"(most {len(plan['tuned'])}). Több dimenziónál az "
                      f"optimalizálás a helyes eszköz."), fg=FG_YELLOW)
            return

        params = self._collect_params()
        if params is None:
            return
        try:
            from trading.backtest import load_data
            df15, df1 = load_data(self.symbol)
        except Exception as ex:
            self._sw_status.config(text=f"Adat-hiba: {ex}", fg=FG_RED)
            return
        if df15 is None:
            self._sw_status.config(text="Nincs letöltött előzmény.", fg=FG_RED)
            return

        axes, combos = _sw.combos(rows, self._opt_cfg_cache)
        self._sw_axes, self._sw_rows = axes, []
        self._sw_stop = threading.Event()
        self._plan_btn.config(text="Megszakítás")
        # ⚠ Az IDOSZAK a backtest mezoibol jon — EGY helyen allitod. Korabban a
        # sopresnek sajat datum-mezoi voltak, tehat ugyanazt ketszer kellett
        # beirni, es a ket ertek csendben elterhetett.
        _bt = getattr(self, "_run_tab", None)
        _start = (_bt._start_var.get().strip() or None) if _bt else None
        _end = (_bt._end_var.get().strip() or None) if _bt else None
        _ib = self._cfg_initial_balance()
        _tcfg = self.root_cfg.get("trading", {})
        _pcfg = self.cfg.get("pairs", {}).get(self.symbol) or {}
        _exec_gates = bool(self.root_cfg.get("optimizer", {}).get("exec_gates", True))

        # ⚠ A HÁTTÉRSZÁL NEM NYÚLHAT A Tk-HOZ — még `after()`-rel sem. A Tcl
        # értelmező egyszálú; egy másik szálból hívott `after` megsérti, és a
        # tünet nem kivétel, hanem hogy a widgetek EGYSZER CSAK ELTŰNNEK (mérve:
        # a felugró ablak ~55 mp után magától megsemmisült futó söprés közben).
        # Helyes minta: a szál egy SORBA ír, a főszál periodikusan kiolvassa.
        import queue
        self._sw_queue = queue.Queue()
        q = self._sw_queue

        def _prog(done, total, _row):
            q.put(("progress", done, total))

        def _work():
            try:
                res = _sw.run(self.symbol, df15, df1, params, _pcfg,
                              _tcfg, _ib, self.strategy, combos,
                              test_start=_start, test_end=_end,
                              cfg=self.root_cfg, exec_gates=_exec_gates,
                              progress=_prog, stop_flag=self._sw_stop)
                q.put(("done", res, ""))
            except Exception as ex:
                q.put(("done", [], f"{type(ex).__name__}: {ex}"))

        threading.Thread(target=_work, daemon=True, name="SweepRun").start()
        self.popup.after(150, self._sw_poll)      # a főszálról indítva

    def _sw_poll(self):
        """A söprés-szál üzeneteinek kiolvasása — MINDIG a főszálon."""
        import queue
        if self._closed:
            return
        finished = False
        try:
            while True:
                msg = self._sw_queue.get_nowait()
                if msg[0] == "progress":
                    self._sw_status.config(text=f"{msg[1]}/{msg[2]} futás…",
                                           fg=FG_GRAY)
                else:
                    self._sweep_done(msg[1], msg[2])
                    finished = True
        except queue.Empty:
            pass
        except tk.TclError:
            return
        if not finished and self._sw_stop is not None:
            self.popup.after(150, self._sw_poll)

    def _cfg_initial_balance(self) -> float:
        try:
            return float((self.root_cfg.get("ml") or {}).get(
                "starting_balance_eur", 10000.0))
        except Exception:
            return 10000.0

    def _sweep_done(self, rows, err):
        self._sw_stop = None
        try:
            self._plan_btn.config(text="Indítás", state="normal")
        except tk.TclError:
            return
        if err:
            self._sw_status.config(text=err, fg=FG_RED)
            return
        self._sw_rows = rows
        self._sw_status.config(text=f"{len(rows)} futás kész.", fg=FG_GREEN)
        self._redraw_sweep()

    def _redraw_sweep(self):
        from core import sweep as _sw
        from dashboard import sweep_view as _sv
        from dashboard import theme as _th
        if not getattr(self, "_sw_rows", None) or not self._sw_axes:
            return
        metric = self._sw_metric.get()
        try:
            _sv.draw(self._sw_canvas, self._sw_axes, self._sw_rows, metric,
                     _th, self._sf, on_pick=self._apply_sweep_point)
        except tk.TclError:
            return
        b = _sw.best(self._sw_rows, metric)
        if b:
            where = " · ".join(f"{k}={v}" for k, v in b.items()
                               if k in [a[0] for a in self._sw_axes])
            self._sw_best.config(
                text=(f"Legjobb ({metric}): {where}  →  {b['trades']} kötés · "
                      f"P&L {b['total_pnl']:+.0f}$ · PF {b['profit_factor']:.2f} · "
                      f"DD {b['max_drawdown'] * 100:.1f}%\n"
                      f"Kattints a rajzra egy pont paramétereinek betöltéséhez."))

    def _apply_sweep_point(self, values: dict):
        """Egy söprés-pont paramétereinek betöltése a Paraméter lap mezőibe.

        ⚠ Csak a MEZŐKBE ír, nem ment: a mentés külön, tudatos lépés (a Mentés
        gomb backtestet is futtat és minősít). Így a rajzon lehet kísérletezni
        anélkül, hogy az élő beállítás elmozdulna."""
        for k, v in values.items():
            e = self.entries.get(k)
            if e is None:
                continue
            e.delete(0, "end")
            e.insert(0, self._fmt_range(v))
        self._invalidate_bt()
        self._sw_status.config(
            text="A pont paraméterei betöltve a Paraméter lapra (nincs mentve).",
            fg=FG_GREEN)

    def _refresh_opt_space(self):
        """A terv-sáv frissítése a PILLANATNYI pipák szerint.

        A Paraméter lap pipái ezt hívják — de a terv-sáv a FUTTATÁS lapon él, és
        az lustán épül. Amíg nincs meg, nincs mit frissíteni (a lap felépülésekor
        magától lefut)."""
        if getattr(self, "_tuned_lbl", None) is None:
            return
        from core import opt_plan as _op
        rows = [dict(r, skipped=not self._skip_vars[r["key"]].get())
                for r in self._opt_rows if r["key"] in self._skip_vars]
        space = _op.search_space(rows)
        tuned = [r for r in rows if not r["skipped"]]
        n_sig = sum(1 for r in tuned if r["cls"] == "signal")
        trials = int((self._opt_cfg_cache or {}).get("max_trials", 500) or 500)
        space_txt = ("gyakorlatilag végtelen" if space >= 10 ** 18
                     else f"{space:,}".replace(",", " "))
        # ⚠ Ez a legfontosabb szám az egész lapon: az optuna NEM járja be a
        # teret, hanem mintavételez. A trial-szám önmagában semmit nem mond —
        # csak a térhez viszonyítva. Enélkül könnyű azt hinni, hogy 500 trial
        # „átnézte” a lehetőségeket.
        try:
            self._space_lbl.config(
                text=(f"{len(tuned)} hangolt dimenzió ({n_sig} jel + "
                      f"{len(tuned) - n_sig} végrehajtás), rácson "
                      f"{space_txt} kombináció.\n"
                      f"Az optimalizálás ebből {trials} mintát vesz — nem járja be "
                      f"a teret, hanem tanul belőle. Kevesebb hangolt dimenzió = "
                      f"sűrűbb minta = megbízhatóbb eredmény."))
            # A FUTÁS TÍPUSA a hangolt dimenziók számából adódik — ugyanaz a
            # gépezet 0, 1, 2 vagy több paraméterrel mást JELENT. A levezetés a
            # `core.opt_plan.run_plan`-ban van (tesztelhető, és a jövőbeli
            # Futtatás lap ugyanazt hívja majd) — itt csak megjelenítjük.
            rp = _op.run_plan(rows, trials)
            self._tuned_lbl.config(
                text=rp["text"] + chr(10) + "Hangolva: " + (", ".join(rp["tuned"]) or "—"))
        except (tk.TclError, AttributeError):
            pass

    @staticmethod
    def _fmt_range(v):
        """Tartomány-érték szerkeszthető alakja. Egészre nem írunk `.0`-t, és a
        lebegőpontos maradékot sem (`0.30000000000000004` → `0.3`)."""
        if isinstance(v, bool) or v is None:
            return "" if v is None else str(v)
        if isinstance(v, int):
            return str(v)
        if isinstance(v, float):
            return f"{v:g}"
        return str(v)

    def _on_range_change(self, key: str):
        """A -tól/-ig/lépés mentése a STRATÉGIA configjába.

        ⚠ Az EGÉSZ/TÖRT jelleget megőrizzük: az optimalizáló abból dönti el,
        hogy `suggest_int`-et vagy `suggest_float`-ot hív. Ha egy egész
        paraméter (pl. sma_period) tartománya véletlenül float-tá válna, az
        optuna tizedes SMA-periódust sorsolna — az indikátor-motor pedig
        vagy elszállna, vagy némán csonkolna.
        """
        from strategy.settings import save_optimizer_ranges, validate_range
        vars_ = (getattr(self, "_range_vars", {}) or {}).get(key)
        if not vars_:
            return
        orig = next((r for r in self._opt_rows if r["key"] == key), None)
        if orig is None:
            return
        spec, changed = {}, False
        for field in ("min", "max", "step"):
            raw = vars_[field].get().strip().replace(",", ".")
            was = orig[field]
            try:
                val = int(round(float(raw))) if isinstance(was, int) else float(raw)
            except (ValueError, TypeError):
                self._range_err.config(
                    text=f"{key}: a(z) „{field}” értéke nem szám — a mező visszaállt.",
                    fg=FG_RED)
                vars_[field].set(self._fmt_range(was))
                return
            spec[field] = val
            changed = changed or val != was
        if not changed:
            self._range_err.config(text="", fg=FG_RED)
            return

        err = validate_range(spec)
        if err:
            # ⚠ NEM mentünk hibás tartományt, és VISSZAÁLLÍTJUK a mezőket. Egy
            # elmentett `min > max` az összes trialt elbuktatná — a felhasználó
            # órákkal később, egy üres eredménytáblából venné észre.
            self._range_err.config(text=f"{key}: {err} — a mezők visszaálltak.",
                                   fg=FG_RED)
            for field in ("min", "max", "step"):
                vars_[field].set(self._fmt_range(orig[field]))
            return

        if save_optimizer_ranges(self.strategy.name, {key: spec}):
            orig.update(spec)
            from core import opt_plan as _op
            n = _op.grid_size(spec)
            self._range_lbls[key].config(text=str(n))
            orig["values"] = n
            self._range_err.config(
                text=f"{key}: mentve ({spec['min']:g} … {spec['max']:g} / "
                     f"{spec['step']:g} → {n} érték)", fg=FG_GREEN)
            self._refresh_opt_space()
        else:
            self._range_err.config(text=f"{key}: a mentés nem sikerült "
                                        f"(lásd a naplót).", fg=FG_RED)

    def _on_skip_change(self, key: str):
        """A pipa AZONNAL a config.json-ba megy (mint a kapu-választók).

        Nem a Mentés gombhoz kötjük: az a paraméter-KÉSZLETET menti; hogy mit
        hangolunk, az más kérdés — félrevezető volna, ha némán arra várna."""
        from core import opt_plan as _op
        skip = {k for k, v in self._skip_vars.items() if not v.get()}
        _op.set_skip_keys(self.root_cfg, self.symbol, self.strategy.name, skip)
        try:
            self._save_main_config()
        except Exception as ex:
            self.lbl_err.config(text=f"Mentési hiba: {ex}", fg=FG_RED)
            return
        self._refresh_opt_space()

    def _fit_to_screen(self, popup, body, footer):
        """Az ablak méretezése a KÉPERNYŐHÖZ, majd a méret RÖGZÍTÉSE.

        Ha a tartalom elfér, minden látszik; ha nem, a törzs görgethetővé
        zsugorodik, a gombsor pedig marad az alján.

        ⚠ A méret rögzítése nem kozmetika. A Tk egy toplevelt alapból a tartalma
        köré méretez — lapváltáskor tehát az ablak ugrálna: a Paraméter lap magas,
        az Eredmények széles, a Leírás keskeny. A doksi ezt külön panaszolja
        („amikor megnyitom, az egész Paraméter ablak összeugrik kicsire").
        Egy explicit `geometry()` után a Tk abbahagyja az automatikus méretezést,
        így a lapok EGYFORMA ablakban nyílnak. Átméretezni a felhasználó továbbra
        is tud — csak a program nem teszi meg helyette."""
        try:
            popup.update_idletasks()
            need_h = body.winfo_reqheight()
            need_w = body.winfo_reqwidth()
            # Ennyi marad a törzsnek: a képernyő 85%-a mínusz a gombsor + ablakkeret
            avail = int(popup.winfo_screenheight() * 0.85) - footer.winfo_reqheight() - 80
            self._body_canvas.config(height=max(240, min(need_h, avail)),
                                     width=need_w)
            popup.update_idletasks()
            # A lapok eltérő szélességűek (az Eredmények tábla a legszélesebb) —
            # a rögzített méret a KÉPERNYŐHÖZ igazodik, hogy egyik lap se lógjon ki.
            # ⚠ A méretet a LEGSZÉLESEBB laphoz kell szabni, nem az éppen
            # láthatóhoz. Az első lap az Áttekintés (keskeny), a Paraméter
            # tábla viszont 8 oszlop — ha a `popup` pillanatnyi igényéből
            # méreteznénk, a paraméter-tábla beszorulna, és pont azt kellene
            # kézzel átméretezni, ami a napi munka.
            need = max(body.winfo_reqwidth() + 40, popup.winfo_reqwidth())
            w = min(max(need, 900), int(popup.winfo_screenwidth() * 0.92))
            h = min(max(body.winfo_reqheight() + footer.winfo_reqheight() + 90,
                        popup.winfo_reqheight(), 600),
                    int(popup.winfo_screenheight() * 0.88))
            popup.geometry(f"{w}x{h}")
            popup.minsize(720, 480)
        except Exception:
            pass

    # ── EGYETLEN metrika-sáv renderelése ────────────────────────────────────
    # (label, érték-formázó, metrika-kulcs vagy None). A None kulcs = fehér
    # (semleges) szín; egyébként a metric_colors szemantikus színe.
    _METRIC_ORDER = [
        ("Trade ", lambda s: str(int(s.get("trades", 0))), None),
        ("Win ",   lambda s: f"{s.get('win_rate', 0) * 100:.0f}%", "win_rate"),
        ("MaxDD ", lambda s: f"{s.get('max_drawdown', 0) * 100:.1f}%", "max_drawdown"),
        ("P&L ",   lambda s: f"{s.get('total_pnl', 0):+.0f}$", "total_pnl"),
        ("PF ",    lambda s: (f"{s.get('profit_factor', 0):.2f}"
                              if s.get('profit_factor', 0) != float('inf') else "∞"),
         "profit_factor"),
    ]

    def _render_metrics(self, summary, source: str):
        """A metrika-sáv frissítése a betöltött paraméterkészlet eredményével.

        summary=None → nincs eredmény; trades==0 → 0-trade jelzés. `source` a
        forrás rövid megnevezése (mentett / #N sor / friss backtest)."""
        for w in self._metrics_frame.winfo_children():
            w.destroy()
        self._src_lbl.config(text=(f"forrás: {source}" if source else ""))
        if not summary or summary.get("trades", 0) == 0:
            self._grade_lbl.config(text="Minősítés: —", fg=FG_GRAY)
            if summary is not None and summary.get("trades", 0) == 0:
                tk.Label(self._metrics_frame, text="0 trade ezen a paraméterezésen",
                         bg=BG, fg=FG_YELLOW, font=self._sf).pack(side="left")
            return
        gtxt, gcol, greason = self.strategy.grade(summary, self.cfg)
        self._grade_lbl.config(
            text=f"Minősítés: {gtxt}" + (f"   ({greason})" if greason else ""),
            fg=sem_color(gcol))
        mc = metric_colors(summary, self.cfg)
        for label, fn, key in self._METRIC_ORDER:
            color = "white" if key is None else mc.get(key, "white")
            cell = tk.Frame(self._metrics_frame, bg=BG)
            cell.pack(side="left", padx=(0, 12))
            tk.Label(cell, text=label, bg=BG, fg=FG_GRAY,
                     font=self._sf).pack(side="left")
            tk.Label(cell, text=fn(summary), bg=BG, fg=sem_color(color),
                     font=self._sf).pack(side="left")

    def _summary_from_row(self, row: dict):
        """Egy trials-CSV sorból metrika-összegzés a minősítéshez/megjelenítéshez.
        None, ha a sorban nincs értelmezhető backtest-eredmény."""
        summ = {
            "trades":        int(_num(row.get("trades")) or 0),
            "total_pnl":     _num(row.get("total_pnl")) or 0.0,
            "win_rate":      _num(row.get("win_rate")) or 0.0,
            "profit_factor": _num(row.get("profit_factor")) or 0.0,
            "max_drawdown":  _num(row.get("max_drawdown")) or 0.0,
        }
        if summ["trades"] == 0 and not any(row.get(c) for c in ("win_rate", "total_pnl")):
            return None
        return summ

    def _invalidate_bt(self):
        """Kézi paraméter-átírásnál a friss backtest-eredmény elavul."""
        if self._bt_summary is not None:
            self._bt_summary = None
            self._render_metrics(
                None, "paraméter módosítva — a Mentés lefuttatja a backtestet")

    # ── Sorszám-választó (minőségi rangsor) ─────────────────────────────────
    def _build_rank_selector(self, popup):
        best, worst = self._ranks[0], self._ranks[-1]
        opt_ranks = [r for r in self._ranks if r < _MANUAL_RANK_BASE]
        man_ranks = [r for r in self._ranks if r >= _MANUAL_RANK_BASE]

        bar = tk.Frame(popup, bg=BG)
        bar.pack(anchor="w", padx=10, pady=(2, 0))
        tk.Label(bar, text="Sorszám (minőség, 1 = legjobb):", bg=BG, fg=FG_GRAY,
                 font=self._sf).pack(side="left")

        self.rank_var = tk.StringVar(value="")
        ent = tk.Entry(bar, width=5, textvariable=self.rank_var, bg=BG_HEADER,
                       fg=FG_WHITE, font=self._sf, insertbackground=FG_WHITE,
                       justify="center")
        ent.pack(side="left", padx=(4, 2))
        ent.bind("<Return>", lambda e: self._load_current_rank())

        tk.Button(bar, text="▲", width=2, bg=BG_HEADER, fg=FG_WHITE, relief="flat",
                  font=self._sf, cursor="hand2",
                  command=lambda: self._step_rank(-1)).pack(side="left", padx=1)
        tk.Button(bar, text="▼", width=2, bg=BG_HEADER, fg=FG_WHITE, relief="flat",
                  font=self._sf, cursor="hand2",
                  command=lambda: self._step_rank(+1)).pack(side="left", padx=1)
        tk.Button(bar, text="Betölt", bg=BG_HEADER, fg=FG_WHITE, relief="flat",
                  font=self._sf, cursor="hand2",
                  command=self._load_current_rank).pack(side="left", padx=(4, 0))

        avail = f"Elérhető: 1–{max(opt_ranks)}" if opt_ranks else "Elérhető: —"
        if man_ranks:
            avail += f"  (kézi: {_fmt_ranges(man_ranks)})"
        tk.Label(bar, text=avail, bg=BG, fg=FG_GRAY_DIM,
                 font=self._sf).pack(side="left", padx=(8, 0))

        # Az adott sorszámhoz tartozó metrikák
        self.lbl_rank = tk.Label(popup, text="Válassz sorszámot a betöltéshez.",
                                 bg=BG, fg=FG_GRAY_DIM, font=self._sf)
        self.lbl_rank.pack(anchor="w", padx=10, pady=(1, 2))

    def _step_rank(self, direction: int):
        """▲ = jobb (kisebb sorszám felé), ▼ = rosszabb — az elérhető ranksoron."""
        cur = _num(self.rank_var.get())
        if cur is None:
            target = self._ranks[0]
        else:
            cur = int(cur)
            after = [r for r in self._ranks if (r > cur if direction > 0 else r < cur)]
            if not after:
                return
            target = after[0] if direction > 0 else after[-1]
        self.rank_var.set(str(target))
        self._load_rank(target)

    def _load_current_rank(self):
        r = _num(self.rank_var.get())
        if r is None:
            self.lbl_rank.config(text="Érvénytelen sorszám.", fg=FG_RED)
            return
        self._load_rank(int(r))

    def _load_rank(self, rank: int):
        row = self._rank_rows.get(rank)
        if row is None:
            self.lbl_rank.config(
                text=f"Nincs {rank}. sorszámú sor (elérhető: "
                     f"{self._ranks[0]}–{self._ranks[-1]}).", fg=FG_RED)
            return
        for k, e in self.entries.items():
            if k in row:
                e.delete(0, "end")
                e.insert(0, self._fmt_param(k, row[k]))
        # Betöltéskor a korábbi friss backtest már nem erre a készletre vonatkozik.
        self._bt_summary = None
        note = (row.get("note") or "").strip()
        summ = self._summary_from_row(row)
        if summ is None:
            self._render_metrics(None, f"#{rank} sor — nincs mentett metrika")
            self.lbl_rank.config(
                text=f"#{rank} betöltve" + (f" ({note})" if note else "")
                     + " — nincs mentett metrika.", fg=FG_GRAY)
        else:
            src = f"#{rank} sor (trials CSV)" + (f", {note}" if note else "")
            self._render_metrics(summ, src)
            self.lbl_rank.config(text=f"#{rank} betöltve.", fg=FG_GRAY)

    # ── Óra-rács (trade_hours) ──────────────────────────────────────────────
    def _build_hours(self, popup, ts):
        """A live óra-kapuja a STRATÉGIA-hatókörű órákat nézi (`{symbol}_hours.json`
        a stratégia mappájában), visszaesve a régi config.json szimbólum-szintű
        `trade_hours`-ra. Az óránkénti P&L (az optimalizált test_summary-ből) segít
        eldönteni, mely órákat vegyük ki (a mínuszosakat kézzel kikattintva). A
        bepipált órákat az EGYETLEN Mentés gomb menti a stratégia óra-fájljába."""
        params = self._src
        hp_raw = (ts or {}).get("hourly_pnl", {})
        hourly = {}
        for _k, _v in hp_raw.items():
            try:
                hourly[int(_k)] = _v
            except (ValueError, TypeError):
                pass

        _pc = self.cfg.get("pairs", {}).get(self.symbol, {})
        _cur = resolve_trade_hours(self.symbol, self.strategy.name,
                                   _pc.get("trade_hours"))
        if _cur is not None:
            _checked0 = {int(h) for h in _cur}
        else:
            _hs, _he = params.get("trade_hour_start"), params.get("trade_hour_end")
            if isinstance(_hs, (int, float)) and isinstance(_he, (int, float)):
                _checked0 = {h for h in range(24) if int(_hs) <= h < int(_he)}
            else:
                _checked0 = set(range(24))

        tk.Label(popup, text="Kereskedési órák (szerver/chart idő) — pipáld be, mely órákban "
                             "kereskedjen (óránkénti P&L az optimalizálásból):",
                 bg=BG, fg=FG_GRAY, font=self._sf).pack(anchor="w", padx=10, pady=(8, 0))

        hours_frame = tk.Frame(popup, bg=BG)
        hours_frame.pack(anchor="w", padx=10, pady=(2, 2))
        hour_on = {h: (h in _checked0) for h in range(24)}
        hour_btns = {}

        def _paint(h):
            btn = hour_btns[h]
            if hour_on[h]:
                btn.config(bg=FG_GREEN, fg=FG_ON_ACCENT)     # BE — zöld
            else:
                btn.config(bg=BG_HEADER, fg=FG_GRAY_DIM)  # KI — sötét

        def _toggle(h):
            hour_on[h] = not hour_on[h]
            _paint(h)

        for h in range(24):
            colf = tk.Frame(hours_frame, bg=BG)
            colf.grid(row=0, column=h, padx=1)
            btn = tk.Label(colf, text=f"{h:02d}", width=2, padx=2, pady=2,
                           font=_theme.fonts()["small_bold"], cursor="hand2")
            btn.pack()
            btn.bind("<Button-1>", lambda e, hh=h: _toggle(hh))
            hour_btns[h] = btn
            _paint(h)
            _b = hourly.get(h)
            if _b:
                _pnl, _cnt = _b.get("pnl", 0.0), _b.get("count", 0)
                tk.Label(colf, text=f"{_pnl:+.0f}", bg=BG,
                         fg=FG_GREEN if _pnl >= 0 else FG_RED,
                         font=_theme.fonts()["tiny"]).pack()
                tk.Label(colf, text=f"{_cnt}", bg=BG, fg=FG_GRAY,
                         font=_theme.fonts()["tiny"]).pack()
            else:
                tk.Label(colf, text="—", bg=BG, fg=FG_GRAY_DIM,
                         font=_theme.fonts()["tiny"]).pack()
                tk.Label(colf, text="", bg=BG, font=_theme.fonts()["tiny"]).pack()

        # Az óraállapotot az EGYETLEN Mentés gomb olvassa ki és menti (nincs külön
        # „Órák mentése" gomb). Az „Auto-javasol" is elmaradt: az óránkénti P&L jól
        # látható a rácsban, így a mínuszos órák kézzel kikattinthatók.
        self._hour_on = hour_on

    # ── Kapu-hatások (per pár × stratégia) ──────────────────────────────────
    def _build_gates(self, parent):
        """A belépő-kapuk HATÁSA ERRE a stratégiára, ezen az instrumentumon.

        Ide tartozik, mert ez az ablak már eleve per (instrumentum × stratégia)
        nyílik — pontosan a kapu-config szemcsézettsége, tehát nem kell új
        felület-fogalom.

        Minden sor kiírja, hogy az érték ÖRÖKÖLT vagy ezen a páron beállított.
        Enélkül nem derülne ki, mit állítottál el ténylegesen, és mi jön
        feljebbről (`core/gates.py` feloldási lánc)."""
        from core import gates as _g
        self._g = _g
        box = tk.Frame(parent, bg=BG)
        box.pack(fill="x", padx=10, pady=(10, 2))
        hdr = tk.Frame(box, bg=BG)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Kapuk", bg=BG, fg=FG_BLUE, font=self._sf,
                 anchor="w").pack(side="left")
        tk.Frame(hdr, bg=BG_HEADER, height=1).pack(side="left", fill="x",
                                                   expand=True, padx=(8, 0))
        tk.Label(box, text=f"Mit tegyen a kapu, ha blokkoló állapotban van — "
                           f"a(z) {self.strategy.name} stratégiára, ezen a páron:",
                 bg=BG, fg=FG_GRAY, font=self._sf, anchor="w").pack(anchor="w",
                                                                    pady=(2, 4))
        self._gate_vars = {}
        self._gate_src_lbl = {}
        grid = tk.Frame(box, bg=BG)
        grid.pack(fill="x")
        for i, g in enumerate(_g.REGISTRY):
            key = g["key"]
            tk.Label(grid, text=g["label"], bg=BG, fg=FG_WHITE, font=self._sf,
                     anchor="w", width=22).grid(row=i, column=0, sticky="w", pady=1)
            eff, _src = _g.effect_with_source(self.root_cfg, self.symbol,
                                              self.strategy.name, key)
            var = tk.StringVar(value=self._gate_choice_text(key, eff))
            om = tk.OptionMenu(grid, var, *self._gate_choices(key),
                               command=lambda _v, k=key: self._on_gate_change(k))
            _style_om(om, self._sf)
            # A szelesseg a LEGHOSSZABB felirathoz igazodik ("Örökölt (…)"),
            # mert az OptionMenu levagja a tullogot — merve, nem becsulve.
            om.config(width=max(len(t) for t in self._gate_choices(key)),
                      anchor="w")
            om.grid(row=i, column=1, sticky="w", padx=6)
            lbl = tk.Label(grid, text="", bg=BG, fg=FG_GRAY_DIM, font=self._sf,
                           anchor="w")
            lbl.grid(row=i, column=2, sticky="w", padx=(6, 0))
            self._gate_vars[key] = var
            self._gate_src_lbl[key] = lbl
            self._refresh_gate_source(key)
        tk.Label(box, text="A „csak jelzés” NEM kapu-hatás: az a stratégia "
                           "kötés-módja (a soron állítható).",
                 bg=BG, fg=FG_GRAY_DIM, font=self._sf, anchor="w").pack(
                 anchor="w", pady=(4, 0))

    def _gate_choices(self, key: str) -> list:
        """A választható értékek: a három hatás + az „Örökölt (…)" visszaállítás.

        Az örökölt opció KIÍRJA, mi lenne az érték felülírás nélkül — így nem
        kell kitalálni, mit kapsz vissza, ha visszavonod a beállítást."""
        inh, _src = self._g.inherited_effect(self.root_cfg, self.symbol,
                                             self.strategy.name, key)
        return [f"Örökölt ({self._g.EFFECT_LABEL[inh]})"] + \
               [self._g.EFFECT_LABEL[e] for e in self._g.EFFECTS]

    def _gate_choice_text(self, key: str, eff: str) -> str:
        """A legördülő AKTUÁLIS felirata: felülírt értéknél a konkrét hatás, ha
        nincs pár-szintű felülírás, akkor az „Örökölt (…)" tétel."""
        pg = ((self.root_cfg.get("pairs") or {}).get(self.symbol) or {}).get("gates") or {}
        g = pg.get(key) or {}
        if g.get(self.strategy.name) in self._g.EFFECTS:
            return self._g.EFFECT_LABEL[eff]
        return self._gate_choices(key)[0]

    def _refresh_gate_source(self, key: str):
        eff, src = self._g.effect_with_source(self.root_cfg, self.symbol,
                                              self.strategy.name, key)
        lbl = self._gate_src_lbl.get(key)
        if lbl is not None:
            lbl.config(text=f"→ {self._g.EFFECT_LABEL[eff]}  "
                            f"({self._g.SOURCE_LABEL.get(src, src)})",
                       fg=FG_WHITE if src == self._g.SRC_PAIR else FG_GRAY_DIM)

    def _on_gate_change(self, key: str):
        """A választás AZONNAL a config.json-ba megy (`pairs.<SYM>.gates`).

        Nem a Mentés gombhoz kötjük: az a paraméter-készletet menti és backtestet
        futtat — a kapu-hatásnak semmi köze ahhoz, és félrevezető volna, ha egy
        legördülő némán a Mentésre várna."""
        txt = self._gate_vars[key].get()
        pairs = self.root_cfg.setdefault("pairs", {})
        pc = pairs.setdefault(self.symbol, {})
        gates = pc.setdefault("gates", {})
        g = gates.setdefault(key, {})
        if txt.startswith("Örökölt"):
            g.pop(self.strategy.name, None)     # felülírás visszavonása
            if not g:
                gates.pop(key, None)
            if not gates:
                pc.pop("gates", None)
        else:
            eff = next((e for e in self._g.EFFECTS
                        if self._g.EFFECT_LABEL[e] == txt), None)
            if eff is None:
                return
            g[self.strategy.name] = eff
        try:
            self._save_main_config()
        except Exception as ex:
            self.lbl_err.config(text=f"Kapu-mentési hiba: {ex}", fg=FG_RED)
            return
        self._refresh_gate_source(key)
        # A választható „Örökölt (…)" felirat is változhat, ha közben a felsőbb
        # szint mást mond — újraépítjük a menüt, hogy ne mutasson elavult értéket.
        self._gate_vars[key].set(self._gate_choice_text(
            key, self._g.effect_for(self.root_cfg, self.symbol,
                                    self.strategy.name, key)))

    # ── Mentés ──────────────────────────────────────────────────────────────
    def _collect_params(self):
        """Az Entry-k tartalma → típusos paraméter-dict. Hiba esetén None."""
        new_params = {k: v for k, v in self._src.items() if not k.startswith("_")}
        for k, e in self.entries.items():
            v = e.get().strip()
            orig = self._types.get(k)
            try:
                if isinstance(orig, bool):
                    new_params[k] = v.lower() in ("true", "1", "igen", "yes")
                elif isinstance(orig, int):
                    new_params[k] = int(float(v))
                elif isinstance(orig, float):
                    new_params[k] = float(v)
                else:
                    # Nincs típus-minta (pl. tisztán CSV-ből jött kulcs): próbáljunk
                    # számot, különben szöveg.
                    fv = _num(v)
                    new_params[k] = fv if (fv is not None and v != "") else v
            except ValueError:
                self.lbl_err.config(text=f"Hibás érték: {k} = {v!r}")
                return None
        return new_params

    def _write_json(self, new_params: dict, extra: dict | None = None) -> bool:
        data = dict(self.data) if self.data else {"symbol": self.symbol}
        data["params"] = new_params
        data["manually_edited_at"] = datetime.utcnow().isoformat()
        if self.is_new and "source" not in data:
            data["source"] = "manual"
        # Ha futott Backtest, a friss összegzés kerül a JSON-ba → a soron
        # megjelenik a minősítés (Win/MaxDD/P&L a test_summary-ből). Ha az
        # eredmény a MENTETT summary újrafelhasználása (változatlan készlet),
        # a backtested_at időbélyeg NEM frissül (nem futott új backtest).
        if self._bt_summary is not None:
            data["test_summary"] = self._bt_summary
            if not getattr(self, "_bt_from_saved", False):
                data["backtested_at"] = datetime.utcnow().isoformat()
        if extra:
            data.update(extra)
        try:
            tmp = self.pf.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            tmp.replace(self.pf)
        except Exception as ex:
            self.lbl_err.config(text=f"Mentési hiba: {ex}")
            return False
        self.data = data
        self.is_new = False
        # A chart-viz a friss JSON-paramétert olvassa → CLEAR + azonnali újrarajz,
        # hogy a TradeForgeViz a KÖVETKEZŐ ciklusban az új paraméterekkel rajzoljon,
        # ÉS a régi (elavult) belépő-jelzések egy atomi írásban eltűnjenek (nem kell
        # a V-t ki/be kapcsolni). Csak ha fut a live loop.
        try:
            from trading import live_trader as _lt
            _lt.request_viz_clear(self.symbol)
        except Exception:
            pass
        return True

    def _save_hours(self) -> int:
        """A bepipált órák mentése a STRATÉGIA óra-fájljába
        (`data/optimized_params/<strategy>/<symbol>_hours.json`) — NEM a
        config.json-ba, így minden stratégiának SAJÁT órái lehetnek ugyanazon az
        instrumentumon. Visszaadja a kiválasztott órák számát."""
        sel = [h for h in range(24) if self._hour_on.get(h)]
        save_trade_hours(self.symbol, sel, self.strategy.name)
        # A live loop és a viz a stratégia óra-fájlját olvassa (feloldó) → a
        # következő ciklusban azonnal él. CLEAR + azonnali újrarajz, hogy AZONNAL az
        # új órákkal rajzoljon és a régi jelzések eltűnjenek. Csak ha fut a live loop.
        try:
            from trading import live_trader as _lt
            _lt.request_viz_clear(self.symbol)
        except Exception:
            pass
        return len(sel)

    def _save_comments(self):
        """A szerkesztett paraméter-megjegyzések mentése a stratégia-configba
        (param_meta.params.<kulcs>.comment). Stratégia-szintű (minden szimbólumra közös).
        Csak akkor ír, ha változott (a helper ellenőrzi). A közös "Végrehajtás"
        kategória kulcsai (BE/trailing/atr_period/spread-kapu) NEM a stratégia-
        configé — a megjegyzésük itt fixen `_EXEC_PARAM_META`-ból jön, nem menthető
        szerkesztve (kockázat/végrehajtási dokumentáció, nem stratégia-specifikus)."""
        if not getattr(self, "_comment_entries", None):
            return
        comments = {k: e.get().strip() for k, e in self._comment_entries.items()
                   if k not in _EXEC_KEYS}
        if not comments:
            return
        try:
            from strategy.settings import save_param_comments
            save_param_comments(self.strategy.name, comments)
        except Exception as ex:
            self.lbl_err.config(text=f"Megjegyzés-mentési hiba: {ex}", fg=FG_RED)

    def _save(self):
        """EGYETLEN Mentés: órák + paraméterek (aktív készlet) + trials CSV (ha a
        kombó még nincs benne), KÖTELEZŐEN backtest-eredménnyel. Ha új a kombó és
        nincs friss eredmény → előbb lefuttatja a backtestet (a _bt_done folytatja
        a mentést); egyébként azonnal ír. A paraméter-megjegyzéseket is menti."""
        self._save_comments()
        params = self._collect_params()
        if params is None:
            return
        dup = self._find_matching_rank(params) if self._rank_rows else None
        if dup is None and self._bt_summary is None:
            # Ha a készlet megegyezik a MENTETT paraméterekkel és van érvényes
            # mentett eredmény (már minősítve van), NEM futtatunk újra backtestet
            # — a mentett metrikával perzisztálunk (pl. csak óra/megjegyzés változott).
            saved_ts = (self.data or {}).get("test_summary") or {}
            if saved_ts.get("trades", 0) > 0 and self._matches_saved_params(params):
                self._bt_summary = dict(saved_ts)
                self._bt_from_saved = True
            else:
                # Új kombó, nincs eredmény → kötelező backtest, utána _persist.
                self._save_after_bt = True
                self.lbl_err.config(text="")
                self._run_backtest()
                return
        self._persist(params, dup)

    def _matches_saved_params(self, params: dict) -> bool:
        """A szerkesztett készlet numerikusan megegyezik-e a MENTETT (JSON)
        paraméterekkel. Csak az űrlap-mezőket veti össze (mint a
        _find_matching_rank a CSV-sorokat)."""
        import math
        saved = (self.data or {}).get("params") or {}
        if not saved:
            return False
        for k in self.entries:
            # A közös végrehajtási kulcsok NEM a stratégia-JSON-ban vannak (lásd
            # `_persist`) — az EREDETI (dialog-nyitáskori) execution-config érték
            # ellenében vetjük össze, nem a `saved` stratégia-params ellen.
            sv = self._orig_exec_params.get(k) if k in _EXEC_KEYS else saved.get(k)
            pv = params.get(k)
            if sv is None or pv is None:
                return False
            try:
                if not math.isclose(float(sv), float(pv), rel_tol=1e-9, abs_tol=1e-6):
                    return False
            except (TypeError, ValueError):
                if str(sv) != str(pv):
                    return False
        return True

    def _persist(self, params: dict, dup):
        """A tényleges kiírás: órák + JSON (aktív készlet) + trials CSV (ha új kombó
        és van érdemi eredmény). `dup` = a megegyező sorszám vagy None."""
        try:
            self._save_hours()
        except Exception as ex:
            self.lbl_err.config(text=f"Óra-mentési hiba: {ex}", fg=FG_RED)
            return
        # A JSON test_summary: friss backtest, vagy a megegyező sor mentett metrikái.
        if self._bt_summary is None and dup is not None:
            self._bt_summary = self._summary_from_row(self._rank_rows.get(dup, {}))
        extra = None
        has_result = bool(self._bt_summary) and self._bt_summary.get("trades", 0) > 0
        if dup is None and has_result:
            # Új kombó → felvesszük a trials CSV-be (eredménnyel), hogy visszatölthető.
            new_rank = _MANUAL_RANK_BASE
            while new_rank in self._rank_rows:
                new_rank += 1
            try:
                self._append_manual_trial(new_rank, params, self._bt_summary)
            except Exception as ex:
                self.lbl_err.config(text=f"CSV-mentési hiba: {ex}", fg=FG_RED)
                return
            rec = {k: str(v) for k, v in params.items()}
            rec.update({"rank": str(new_rank), "note": "manual"})
            for mk in ("trades", "win_rate", "total_pnl", "profit_factor", "max_drawdown"):
                rec[mk] = str(self._bt_summary.get(mk, ""))
            self._rank_rows[new_rank] = rec
            self._ranks = sorted(self._rank_rows)
            extra = {"manual_rank": new_rank}
        # A közös, stratégia-független végrehajtási kulcsok (BE/trailing/atr_period/
        # spread-kapu) a data/execution_params/<SYMBOL>.json-ba mennek — MINDEN
        # stratégia ugyanazt olvassa vissza. A stratégia-JSON csak a saját (jelzés+
        # SL/TP) paramétereit kapja, hogy ne duplikálódjanak.
        _exec_vals = {k: params[k] for k in _EXEC_KEYS if k in params}
        if _exec_vals:
            try:
                _execp.save_execution_params(self.symbol, _exec_vals)
            except Exception as ex:
                self.lbl_err.config(text=f"Végrehajtás-config mentési hiba: {ex}", fg=FG_RED)
                return
        strat_params = {k: v for k, v in params.items() if k not in _EXEC_KEYS}
        if not self._write_json(strat_params, extra=extra):
            return
        self.popup.destroy()

    _METRIC_SAVE_COLS = ("trades", "win_rate", "total_pnl", "profit_factor",
                         "max_drawdown")

    def _append_manual_trial(self, rank: int, params: dict, summary: dict | None = None):
        """Egy kézi paraméter-sor hozzáfűzése a trials CSV-hez, `rank` oszloppal +
        (ha van) a backtest-eredmény metrika-oszlopaival.

        pandas-szal olvassuk/írjuk vissza (magyar ';'+','), így ha a régi CSV-ben
        még nincs `rank` oszlop, most bekerül (a sor pozíciója szerint 1…N)."""
        import pandas as pd
        if self.trials_csv.exists():
            df = pd.read_csv(self.trials_csv, sep=";", decimal=",",
                             encoding="utf-8-sig")
        else:
            df = pd.DataFrame()
        if df.empty:
            # Nincs még CSV → fejléc a paraméterekből + metrikákból, hogy az érték
            # tényleg elmentődjön (üres df-nél nem lenne oszlop, amibe írjunk).
            cols = ["rank"] + list(params.keys()) + list(self._METRIC_SAVE_COLS) + ["note"]
            df = pd.DataFrame(columns=cols)
        if "rank" not in df.columns:
            df.insert(0, "rank", range(1, len(df) + 1))
        row = {c: "" for c in df.columns}
        row["rank"] = rank
        if "note" in df.columns:
            row["note"] = "manual"
        for k, v in params.items():
            if k in df.columns:
                row[k] = v
            # Ha a paraméter-oszlop hiányzik a CSV-ből, kihagyjuk (ne torzítsuk
            # a fejlécet — a betöltés úgyis csak a meglévő oszlopokat használja).
        if summary:
            for mk in self._METRIC_SAVE_COLS:
                if mk in df.columns:
                    row[mk] = summary.get(mk, "")
        new_df = pd.DataFrame([row], columns=list(df.columns))
        df = new_df if len(df) == 0 else pd.concat([df, new_df], ignore_index=True)
        df.to_csv(self.trials_csv, sep=";", decimal=",", index=False,
                  encoding="utf-8-sig")

    def _open_trials(self):
        if not self.trials_csv.exists():
            self.lbl_err.config(text="Nincs trials CSV — futtass optimalizálást előbb.")
            return
        try:
            import os
            os.startfile(str(self.trials_csv))   # Windows: alap app (Excel)
        except Exception as ex:
            self.lbl_err.config(text=f"Megnyitási hiba: {ex}")

    # ── Duplikátum-keresés a rangsorban ─────────────────────────────────────
    def _find_matching_rank(self, params: dict):
        """Van-e már olyan sorszám, aminek a szerkeszthető paraméterei (az űrlap
        mezői) numerikusan megegyeznek a `params`-szal? Visszaad rangot vagy None."""
        import math
        for rank in sorted(self._rank_rows):
            row = self._rank_rows[rank]
            ok = True
            for k in self.entries:
                rv = _num(row.get(k))
                pv = params.get(k)
                if rv is None or pv is None:
                    ok = False
                    break
                try:
                    if not math.isclose(float(rv), float(pv), rel_tol=1e-9, abs_tol=1e-6):
                        ok = False
                        break
                except (TypeError, ValueError):
                    ok = False
                    break
            if ok:
                return rank
        return None

    # ── Kockázatcsökkentés preset (per-pár) ─────────────────────────────────
    def _preset_from_name(self, name: str) -> str:
        return {v: k for k, v in self._rrs.NAME.items()}.get(name, self._rrs.PRESET_OFF)

    def _runner_from_name(self, name: str) -> str:
        return {v: k for k, v in self._rrs.RUNNER_NAME.items()}.get(
            name, self._rrs.RUNNER_TRAILING)

    def _on_rr_change(self, name: str):
        """A választott preset mentése a per-pár állapotba (data/risk_mode.json).
        A régi risky_mode-ot szinkronban tartjuk (preset==risky), mint a sor R gombja.
        Frissíti a vezérlők láthatóságát + az Óvatos méret alapértékét."""
        preset = self._preset_from_name(name)
        self._rrs.set_preset(self.symbol, preset)
        try:
            from core import risky_mode, risk_reduction as _rr
            risky_mode.set_risky(self.symbol, preset == _rr.PRESET_RISKY)
        except Exception:
            pass
        # Óvatos alapérték: ha nincs kézi override, a preset szerint (Risky→pipa).
        from core import risk_reduction as _rr
        if self._rrs.get_cautious(self.symbol) is None:
            self._cautious_var.set(_rr.wants_cautious_size(preset))
        self._update_rr_visibility()

    def _on_be_trail_save(self, key: str):
        """Egy BE/trailing mező mentése a per-pár kockázatcsökkentő állapotba.

        Azonnal ment (mint a többi rr-vezérlő), nem a Mentés gombra vár: ezek
        NEM stratégia-paraméterek, tehát nincs közük a paraméter-űrlap
        mentéséhez. Érvénytelen szám → visszaírjuk a ténylegesen ható értéket,
        hogy a mező ne mutasson mást, mint amivel a motor dolgozik."""
        v = _num(self._bt_vars[key].get())
        if v is not None and v >= 0:
            self._rrs._set(self.symbol, **{key: float(v)})
        cur = self._rrs.spec_for(self.symbol).get(key, 0)
        self._bt_vars[key].set(f"{float(cur):g}")

    def _on_cautious_change(self):
        self._rrs.set_cautious(self.symbol, bool(self._cautious_var.get()))

    def _on_cost_cut_change(self):
        self._rrs.set_cost_cut(self.symbol, bool(self._cc_var.get()))

    def _on_cost_cut_bars_save(self, _event=None):
        raw = self._cc_bars_var.get().strip().replace(",", ".")
        try:
            v = int(float(raw))
        except ValueError:
            return
        if v > 0:
            self._rrs.set_cost_cut_bars(self.symbol, v)

    def _on_runner_change(self, name: str):
        self._rrs.set_runner(self.symbol, self._runner_from_name(name))
        self._update_rr_visibility()   # Exit csak Runner=Kiszállási jelnél látszik

    def _on_exit_ind_change(self, name: str):
        ind = {v: k for k, v in self._EXIND_NAME.items()}.get(name, "supertrend")
        self._rrs.set_exit_config(self.symbol, indicator=ind)
        self._rebuild_exit_params()

    def _on_build_mode_change(self, name: str):
        mode = {v: k for k, v in self._bst.NAME.items()}.get(name, self._bst.MODE_OFF)
        self._bst.set_mode(self.symbol, mode)
        self._update_rr_visibility()   # Faktor csak Építés ≠ Ki esetén látszik

    def _on_build_faktor_save(self, _event=None):
        """A piramidális méret-faktor mentése a per-pár építés-configba."""
        raw = self._build_sf_var.get().strip().replace(",", ".")
        try:
            v = float(raw)
        except ValueError:
            return
        if v > 0:
            self._bst.set_config(self.symbol, size_factor=v)

    def _on_build_trigger_change(self, name: str):
        trig = {v: k for k, v in self._pb.TRIGGER_NAME.items()}.get(
            name, self._pb.TRIGGER_CANDLE)
        self._bst.set_config(self.symbol, trigger=trig)
        self._update_rr_visibility()   # R-lépés/Zsug csak a trigger szerint látszik

    def _on_build_rstep_save(self, _event=None):
        try:
            v = float(self._build_rstep_var.get().strip().replace(",", "."))
        except ValueError:
            return
        if v > 0:
            self._bst.set_config(self.symbol, r_step=v)

    def _on_build_rshrink_save(self, _event=None):
        try:
            v = float(self._build_rshrink_var.get().strip().replace(",", "."))
        except ValueError:
            return
        if 0 < v < 1:
            self._bst.set_config(self.symbol, r_shrink=v)

    def _update_rr_visibility(self):
        """A vezérlők logikai elrejtése/megjelenítése a preset/runner/építés szerint:
        Óvatos csak ha van kockázatcsökkentés; Runner csak Felező/Pajzsnál; Exit csak
        Felező/Pajzs + Runner=Kiszállási jel; Építésnél: Faktor+Trigger csak ha ≠ Ki,
        R-lépés csak R-alapú triggernél, Zsug csak R-felezőnél."""
        from core import risk_reduction as _rr
        preset = self._preset_from_name(self._rr_name.get())
        # Óvatos: ahol nincs érdemi kockázatcsökkentés, elrejtve
        (self._cautious_cb.grid_remove
         if preset in (_rr.PRESET_NONE, _rr.PRESET_OFF)
         else self._cautious_cb.grid)()
        # Runner: csak Felező/Pajzs (+ Pajzs↔Fibo auto, mert Pajzsra oldódhat)
        partial = preset in (_rr.PRESET_HALVING, _rr.PRESET_SHIELD,
                             _rr.PRESET_SHIELD_FIBO)
        (self._runner_frame.grid if partial else self._runner_frame.grid_remove)()
        # Exit: csak Felező/Pajzs + Runner=Kiszállási jel
        runner = self._runner_from_name(self._runner_name.get())
        show_exit = partial and runner == _rr.RUNNER_EXIT
        (self._exit_frame.grid if show_exit else self._exit_frame.grid_remove)()
        # BE/trailing: CSAK azok, amelyek ezen a preset+runner páron TÉNYLEG hatnak.
        # Sorrend-tartó (mind elrejt, majd a látókat sorban pack) — mint az
        # építés-vezérlőknél; enélkül a mezők sorrendje váltogatna.
        _act = _rr.be_trail_active(preset, runner)
        for _k, _f in self._bt_frames.items():
            _f.pack_forget()
        for _k in _rr.BE_TRAIL_KEYS:
            if _k in _act:
                self._bt_frames[_k].pack(side="left", padx=(0, 10))
        # ── Építés-vezérlők (sorrend-tartó: mind elrejt, majd a látókat sorban pack) ──
        for f in (self._build_faktor_frame, self._build_trig_frame,
                  self._build_rstep_frame, self._build_rshrink_frame):
            f.pack_forget()
        build_on = self._build_mode_name.get() != self._bst.NAME[self._bst.MODE_OFF]
        trig = {v: k for k, v in self._pb.TRIGGER_NAME.items()}.get(
            self._build_trig_name.get(), self._pb.TRIGGER_CANDLE)
        if build_on:
            self._build_faktor_frame.pack(side="left", padx=(8, 0))
            self._build_trig_frame.pack(side="left", padx=(10, 0))
            if trig in (self._pb.TRIGGER_R_FIXED, self._pb.TRIGGER_R_CONVERGE):
                self._build_rstep_frame.pack(side="left", padx=(8, 0))
            if trig == self._pb.TRIGGER_R_CONVERGE:
                self._build_rshrink_frame.pack(side="left", padx=(8, 0))
        self._refit_width()

    def _refit_width(self):
        """A törzs szélessége kövesse az ELŐBUKKANÓ vezérlőket: a kockázatcsökkentés
        sora Pajzs + Kiszállási jelnél jóval szélesebb, mint Ki-nél — különben a jobb
        széle levágódna. Csak NŐ (nem ugrál vissza), a képernyőre vágva."""
        try:
            cv = self._body_canvas
            cv.update_idletasks()
            need = self._body.winfo_reqwidth()
            cap  = int(cv.winfo_toplevel().winfo_screenwidth() * 0.95)
            cv.config(width=max(int(cv.cget("width")), min(need, cap)))
        except Exception:
            pass

    def _rebuild_exit_params(self):
        """Az exit-indikátor SZERKESZTHETŐ paraméter-mezőinek újraépítése (a kiválasztott
        indikátor szerint), a per-pár exit-configból feltöltve."""
        for w in self._exit_pfrm.winfo_children():
            w.destroy()
        self._exit_param_vars = {}
        ind = {v: k for k, v in self._EXIND_NAME.items()}.get(self._exit_ind_name.get(), "supertrend")
        cfg = self._rrs.get_exit_config(self.symbol)
        for key, label in self._EXIT_PARAM_SPEC.get(ind, []):
            lbl = tk.Label(self._exit_pfrm, text=f"{label}:", bg=BG, fg=FG_GRAY,
                           font=self._sf)
            lbl.pack(side="left")
            var = tk.StringVar(value=str(cfg.get(key, "")))
            e = tk.Entry(self._exit_pfrm, textvariable=var, width=(5 if key == "osc" else 4),
                         bg=BG_HEADER, fg=FG_WHITE, font=self._sf, relief="flat",
                         insertbackground=FG_WHITE)
            e.pack(side="left", padx=(2, 6))
            e.bind("<FocusOut>", lambda ev, k=key: self._save_exit_param(k))
            e.bind("<Return>",   lambda ev, k=key: self._save_exit_param(k))
            # Tooltip a címkén ÉS a mezőn (melyik paraméter mit állít).
            _tip = self._EXIT_TIP.get(key, "")
            _attach_tooltip(lbl, _tip)
            _attach_tooltip(e, _tip)
            self._exit_param_vars[key] = var

    def _save_exit_param(self, key: str):
        """Egy exit-paraméter mentése a per-pár configba (típus-validálással)."""
        raw = self._exit_param_vars[key].get().strip()
        if key == "osc":
            val = raw.lower() if raw.lower() in ("rsi", "cci") else "rsi"
        elif key == "st_multiplier":
            try:
                val = float(raw)
            except ValueError:
                return
        else:
            try:
                val = int(float(raw))
            except ValueError:
                return
        self._rrs.set_exit_config(self.symbol, **{key: val})

    def _rr_spec_from_ui(self):
        """A UI-ban beállított teljes spec (preset + óvatos méret + runner + exit +
        cost-cut). None, ha 'Ki' ÉS a cost-cut is ki (→ a run_pair az alap OFF
        viselkedést futtatja). A cost-cut Ki preset mellett is élhet (idő-stop)."""
        from core import risk_reduction as _rr
        preset = self._preset_from_name(self._rr_name.get())
        cc_on  = bool(self._cc_var.get())
        if preset == _rr.PRESET_OFF and not cc_on:
            return None
        runner = self._runner_from_name(self._runner_name.get())
        exit_cfg = self._rrs.get_exit_config(self.symbol)
        exit_cfg["enabled"] = (runner == _rr.RUNNER_EXIT)   # a UI runner-választása dönt
        spec = {**_rr.default_config(), "preset": preset,
                "runner_stop": runner,
                # Ki presetnél az Óvatos pipa rejtett → ne hasson a méretezésre.
                "cautious": (bool(self._cautious_var.get())
                             if preset != _rr.PRESET_OFF else False),
                "exit": exit_cfg,
                "cost_cut": cc_on}
        try:
            _b = int(float(self._cc_bars_var.get().strip().replace(",", ".")))
            if _b > 0:
                spec["cost_cut_bars"] = _b
        except ValueError:
            pass
        return spec

    # ── Backtest önálló ablak (progress + időszak + élő egyenleg) ────────────
    def _open_backtest_window(self):
        """A „Backtest" gomb a FUTTATÁS LAPRA vált (a backtest odaköltözött).

        ⚠ A gomb megmarad, és nem nyit új ablakot: a doksi panasza épp az volt,
        hogy ugyanaz a paraméter két külön kinézetben jelenik meg. A megszokott
        gomb viszont ne tűnjön el — csak vezessen a helyére.
        """
        try:
            self._shell.show("Futtatás")
            return
        except Exception:
            pass          # ha valamiért nincs lap, marad a régi, ablakos út
        params = self._collect_params()
        if params is None:
            return
        pair_cfg = self.cfg.get("pairs", {}).get(self.symbol)
        if not isinstance(pair_cfg, dict):
            self.lbl_bt.config(text="Nincs pár-config ehhez az instrumentumhoz.",
                               fg=FG_RED)
            return
        from dashboard.backtest_dialog import BacktestDialog
        BacktestDialog(
            self.popup, self.symbol, self.cfg, self.strategy, params, pair_cfg,
            self._rr_spec_from_ui(), self._hf, self._sf,
            on_result=self._on_bt_window_result,
            preset_name=self._rr_name.get(),
            on_apply_params=self._apply_params_from_bt)

    def _on_bt_window_result(self, summary):
        """A Backtest-ablak végeredménye → a közös metrika-sávba + a Mentés forrása."""
        self._bt_summary = summary
        self._render_metrics(summary, "friss backtest")

    def _apply_params_from_bt(self, params: dict, summary=None):
        """A Backtest-ablak „Mentés a Paraméterekhez" gombja → a (feltáró) paraméterek
        visszaírása EBBE az űrlapba (a lemezre mentést a Mentés gomb végzi). Ha van
        friss backtest-eredmény, azt is átvesszük forrásként."""
        for k, e in self.entries.items():
            if k in params:
                e.delete(0, "end")
                e.insert(0, self._fmt_param(k, params[k]))
        if summary and summary.get("trades", 0) > 0:
            self._bt_summary = summary
            self._render_metrics(summary, "friss backtest (a Backtest-ablakból)")
        else:
            self._bt_summary = None
            self._render_metrics(
                None, "paraméterek a Backtest-ablakból — a Mentés lefuttatja a backtestet")

    def _bt_status(self, text: str):
        """Háttérszálról biztonságos státusz a backtest-sorba (adat-letöltés stb.)."""
        try:
            self.popup.after(0, lambda: self.lbl_bt.config(text=text, fg=FG_GRAY))
        except Exception:
            pass

    # ── Backtest inline (a Mentés auto-útja: gyors, ablak nélkül) ────────────
    def _run_backtest(self):
        if self._bt_running:
            return
        params = self._collect_params()
        if params is None:
            return
        pair_cfg = self.cfg.get("pairs", {}).get(self.symbol)
        if not isinstance(pair_cfg, dict):
            self.lbl_bt.config(text="Nincs pár-config ehhez az instrumentumhoz.", fg=FG_RED)
            return
        self._bt_running = True
        rr_spec = self._rr_spec_from_ui()          # a választott preset (vagy None)
        self._btn_bt.config(text="Backtest fut…", state="disabled")
        # Futás alatt a Mentés is tiltva (az auto-mentés amúgy is a végén folytatódik).
        try:
            self._btn_save.config(state="disabled")
        except Exception:
            pass
        _pname = self._rr_name.get()
        _saving = " — mentés a végén" if self._save_after_bt else ""
        self.lbl_bt.config(text=f"Backtest fut (teljes hist., {_pname}){_saving} — kis türelmet…",
                           fg=FG_GRAY)

        def work():
            summary, err = None, None
            try:
                from trading.backtest import load_data_ensure, run_pair
                # Hiányzó előzmény → MAGÁTÓL letölti (frissen felvett instrumentum)
                df15, df1, err = load_data_ensure(
                    self.symbol, self.cfg,
                    status=lambda m: self._bt_status(f"Előzmény: {m}"))
                if df15 is not None:
                    ib = float(self.cfg.get("ml", {}).get("starting_balance_eur", 1000.0))
                    res = run_pair(self.symbol, df15, df1, params, pair_cfg,
                                   self.cfg["trading"], ib, strategy=self.strategy,
                                   rr=rr_spec)
                    summary = res.summary(ib)
                    # A ténylegesen alkalmazott technikák (lot-létra hatása)
                    from collections import Counter
                    tech = Counter(t.rr_technique for t in res.closed
                                   if getattr(t, "rr_technique", ""))
                    if summary and tech:
                        summary["_rr_tech"] = dict(tech)
            except Exception as ex:
                err = str(ex)
            try:
                self.popup.after(0, lambda: self._bt_done(summary, err))
            except Exception:
                pass

        threading.Thread(target=work, daemon=True, name="InstrBacktest").start()

    def _bt_done(self, summary, err):
        self._bt_running = False
        try:
            self._btn_bt.config(text="Backtest", state="normal")
            self._btn_save.config(state="normal")
        except Exception:
            return   # a popup közben bezárult
        # Volt-e függő (auto-)mentés? Elfogyasztjuk, majd a végén folytatjuk.
        pending = self._save_after_bt
        self._save_after_bt = False
        if err:
            self.lbl_bt.config(text=f"Backtest hiba: {err}", fg=FG_RED)
            self._render_metrics(None, "backtest hiba")
            return
        # A metrikák a KÖZÖS sávba kerülnek (nincs külön backtest-metrikasor). Az
        # lbl_bt már csak a ténylegesen alkalmazott kockázati technikát mutatja.
        tech = (summary or {}).pop("_rr_tech", None) or {}
        _names = {"shield": "Pajzs", "halving": "Felező", "risky": "Risky",
                  "fibo": "Fibo", "thirds": "Harmados"}
        tech_s = (", ".join(f"{_names.get(k, k)}×{v}" for k, v in tech.items())) if tech else ""
        self._bt_summary = summary or {"trades": 0}
        self._bt_from_saved = False   # ez valódi friss backtest
        self._render_metrics(self._bt_summary, "friss backtest")
        self.lbl_bt.config(
            text=(f"Ténylegesen alkalmazott technika: {tech_s}" if tech_s else ""),
            fg=FG_GRAY_DIM)
        if pending:
            # Auto-mentés folytatása: a friss eredménnyel most már perzisztálunk.
            params = self._collect_params()
            if params is not None:
                dup = self._find_matching_rank(params) if self._rank_rows else None
                self._persist(params, dup)

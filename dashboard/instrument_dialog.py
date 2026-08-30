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
import logging
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
from core.i18n import t as _t, num as _fmtnum

log = logging.getLogger(__name__)

# A közös, stratégia-független "Végrehajtás" kategória (atr_period + spread-kapu)
# — minden stratégia-configból kikerült, itt jelenik meg egységesen.
# `_EXEC_KEYS` a `core.execution_params.DEFAULTS` kulcsai.
#
# ⚠ A BE/trailing v1.96.0 óta NEM ITT van: a kockázatcsökkentő beállító ablakban
# jelenik meg, és CSAK azokon a preseteken, ahol tényleg hat (Fibo/Harmados
# preseten például semmit nem csinált — lásd `core.risk_reduction.be_trail_active`).
# ⚠ NEM FORDÍTJUK — ez ADAT-AZONOSÍTÓ, nem felirat. A paraméter-kategóriák
# nevei a stratégiák config-JSON-jaiban élnek (`param_meta.categories`), és
# a kód ezekre hasonlít. Lefordítva a csoportosítás szétesne: minden
# paraméter az „Egyéb" ágra kerülne. A kategóriák nyelvesítése külön
# lépés (a configban kellene kódot tárolni, felirattal együtt).
_EXEC_CATEGORY = "Végrehajtás"
_EXEC_KEYS = frozenset(_execp.DEFAULTS)
_EXEC_PARAM_META = {
    "atr_period": {"category": _EXEC_CATEGORY,
                   "comment": _t("idlg3.atr_periodus_spread_kapu")},
    "max_spread_atr_ratio": {"category": _EXEC_CATEGORY,
                              "comment": _t("idlg3.spread_kapu_max_spread")},
    "min_spread_mult": {"category": _EXEC_CATEGORY,
                         "comment": _t("idlg3.spread_kapu_also_kuszobe")},
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


def _autowrap(lbl, source=None, min_px: int = 360):
    """A címke tördelése KÖVESSE a lap szélességét.

    ⚠ Nem kényelmi finomítás. A `wraplength` alapból 0 = „ne törd" — egy hosszú,
    összefűzött szöveg (pl. „Hangolva: " + 14 paraméternév) EGYETLEN sorban
    2 220 px-et kért, és mivel az oldal a legszélesebb gyereke szerint méretezi
    magát, EMIATT lógott ki a teljes lap: a vízszintes csúszka 1 900 px-es
    ablakon sem tűnt el, és az órák sem nyúltak, mert a tartalom szélessége
    fixen a címkéé maradt.

    A máshol használt `wraplength=820` ezt megoldaná, de egy 4K képernyőn a hely
    kétharmadát eldobná.

    ⚠⚠ A `source` NEM a szülő, hanem a GÖRGETŐ VÁSZON — és ez nem stílus, hanem
    a helyes működés feltétele. A szülőhöz kötve VÉGTELEN CIKLUS keletkezik a
    vízszintes görgetéssel:

        wraplength ← szülő szélessége → a címke igényelt szélessége változik
                  → a lap igényelt szélessége változik
                  → a `scroll_area` átméretezi a belső keretet (`max(w, need)`)
                  → a szülő szélessége változik → vissza az elejére

    (Mérve: a Tk `update()` nem tért vissza — az ablak befagyott.) A vászon
    szélessége viszont az ABLAK mérete, tehát FÜGGETLEN bemenet: nem a tartalom
    állítja. Így a tördelt címke soha nem hízlalja a lapot — ami egyben azt is
    jelenti, hogy nem ő szabja meg, mikor kell vízszintes csúszka.
    """
    src = source if source is not None else lbl.master

    def _on(ev, _l=lbl):
        w = max(min_px, int(ev.width) - 40)
        try:
            if abs(int(_l.cget("wraplength") or 0) - w) > 8:
                _l.config(wraplength=w)
        except tk.TclError:
            pass

    src.bind("<Configure>", _on, add="+")
    try:                       # induláskor is (a Configure csak változáskor jön)
        _on(type("E", (), {"width": src.winfo_width() or 900})())
    except tk.TclError:
        pass
    return lbl


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
        title = _t("idlg.title", symbol=self.symbol, strategy=self.strategy.name)
        if self.is_new:
            title += _t("idlg3.uj_kezi")
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
        # ⚠ A „Futtatás" lap MEGSZŰNT: a futtatás és az eredmény a Paraméter
        # oldal két SZAKASZA lett. A felhasználó észrevétele — „a Paraméter,
        # Futtatás, Optimalizálás igazából egy és ugyanaz, de valahogy mégsem" —
        # addig nem oldódott meg, amíg LAPOKON ültek: külön lapon nem látszik,
        # MILYEN értékkel fog futni, tehát oda kellett lapozni ellenőrizni.
        #
        # A „Kísérletek" a volt „Eredmények": az optimalizálás trial-listája.
        # Egy lapon „Eredmények" ÉS egy szakaszon „Eredmény" kibírhatatlanul
        # összekeverhető lett volna — a kettő nem ugyanaz: a szakasz a MOST
        # lefuttatott futásé, a lap az összes korábbi PRÓBÁLKOZÁSÉ.
        self._shell = TabShell(popup, (("overview", _t("tab.overview")),
                                       ("params",   _t("tab.params")),
                                       ("trials",   _t("tab.trials")),
                                       ("link",     _t("tab.link")),
                                       ("docs",     _t("tab.docs"))),
                               on_show=self._on_tab, notify_every_show=True)

        # Görgethető törzs — innentől MINDEN tartalom ide (`body`) megy.
        # ⚠ VÍZSZINTESEN IS, de csak ha kell: a kockázatcsökkentés sora Pajzs +
        # Kiszállási jelnél jóval szélesebb, mint Ki-nél, és keskeny ablakon a
        # jobb széle eddig NÉMÁN levágódott. A csúszka az OLDAL alján ül, nem egy
        # szakaszon belül — így egy kérdést old meg egy helyen.
        holder, body, self._body_canvas = _scrollable(self._shell.page("params"),
                                                      horizontal=True)
        holder.pack(side="top", fill="both", expand=True)
        self._body = body

        # Fejléc-sor a tartalomban is (a címsor könnyen elsiklik): instrumentum + stratégia.
        tk.Label(body, text=_t("idlg.subtitle", symbol=self.symbol, strategy=self.strategy.name),
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
            self._render_metrics(ts, _t("idlg2.mentett_eredmeny"))
        else:
            self._render_metrics(
                None, _t("idlg2.nincs_mentett_eredmeny_allits"))

        # ── Figyelmeztetés: a készlet KAPUK NÉLKÜL lett hangolva ────────────
        # A v1.95.0 előtti optimalizáló a spread- és a TF-együttállás kapu NÉLKÜL
        # futott, az él viszont mindkettőt alkalmazza — a mentett paraméterek
        # tehát egy olyan világhoz tartoznak, ami élesben nem létezik. Ez eddig
        # LÁTHATATLAN volt: a régi és az új eredmény ránézésre egyforma. Ezért
        # kiírjuk, ha a JSON-ban nincs (vagy hamis) az `exec_gates` jelölő.
        if self.data is not None and not self.data.get("exec_gates", False):
            tk.Label(body, bg=BG, fg=FG_YELLOW, font=self._sf, anchor="w",
                     justify="left", wraplength=560,
                     text=(_t("idlg.ez_a_keszlet_a"))
                     ).pack(anchor="w", padx=10, pady=(0, 4))

        # ── A LAP TELJES SZÉLESSÉGŰ, ÖSSZECSUKHATÓ SZAKASZOKBÓL áll ────────
        # Sorrend az ÁLTALÁNOSTÓL a KONKRÉTIG: mikor kereskedhet · mi engedi be ·
        # milyen számokkal · mi történik belépés után. Napi munkában legfeljebb
        # kettő-három kell nyitva; a becsukott fejléc ÖSSZEGZÉST mutat, tehát a
        # becsukás a szerkesztést rejti el, nem az információt.
        from dashboard import section as _sec
        _sec_def = {"orak": False, "kapuk": True, "parameterek": True,
                    "kockazat": False, "futtatas": True, "eredmeny": True}
        _open = _sec.load_open(self.symbol, self.strategy.name, _sec_def)
        self._sections = {}

        def _mk(key, title):
            sc = _sec.Section(body, key, title, {"header": self._hf,
                                                 "small": self._sf},
                              open_=_open.get(key, True),
                              on_toggle=self._on_section_toggle)
            sc.pack()
            self._sections[key] = sc
            return sc.body

        # ── Óra-rács (trade_hours) — a config.json-ba ment ──────────────────
        self._build_hours(_mk("orak", _t("idlg2.kereskedesi_orak")), ts)

        # ── Kapuk: mit tegyenek EZZEL a stratégiával ezen a páron ───────────
        self._build_gates(_mk("kapuk", "Kapuk"))

        _pbody = _mk("parameterek", _t("idlg2.parameterek"))

        # ── Kézi paraméter-űrlap ────────────────────────────────────────────
        tk.Label(_pbody, text=_t("idlg.kezi_modositas_a_kovetkezo"),
                 bg=BG, fg=FG_GRAY, font=self._sf).pack(anchor="w", padx=10)

        # ── Sorszám-választó (csak ha van trials CSV) ───────────────────────
        self.lbl_rank = None
        if self._ranks:
            self._build_rank_selector(_pbody)

        form = tk.Frame(_pbody, bg=BG)
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
        # ⚠ A ciklusváltozó NEM `_t` — az a fordító (`core.i18n`) neve ebben a
        # modulban, és egy azonos nevű lokális az EGÉSZ metódusban elfedné
        # (UnboundLocalError, a metódus legelső i18n-hívásánál).
        for _c, (_hdr, _w) in enumerate(((_t("tab.params"), 24), (_t("idlg3.ertek"), 8),
                                         ("", 3), (_t("idlg3.tol"), 7), ("-ig", 7),
                                         (_t("idlg3.lepes"), 7), ("db", 4))):
            tk.Label(form, text=_hdr, bg=BG, fg=FG_GRAY_DIM, font=self._sf,
                     anchor="w", width=_w).grid(row=0, column=_c, sticky="w",
                                                padx=(0, 3))
        tk.Label(form, text=_t("idlg.megjegyzes_szerkesztheto"), bg=BG, fg=FG_GRAY_DIM,
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
        self._range_err = tk.Label(_pbody, text="", bg=BG, fg=FG_RED, font=self._sf,
                                   anchor="w", justify="left")
        self._range_err.pack(anchor="w", padx=10)
        tk.Label(_pbody, bg=BG, fg=FG_GRAY_DIM, font=self._sf, anchor="w",
                 justify="left", text=(
                     _t("idlg.a_pipa_bevonjuk_e")
                 )).pack(anchor="w", padx=10, pady=(2, 0))

        # ── Kapuk: mit tegyenek EZZEL a stratégiával ezen a páron ───────────
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
            "supertrend": [("st_period", "Per"), ("st_multiplier", _t("exit.param.mult"))],
            "wpr":        [("wpr_period", "Per"), ("wpr_ma_period", "MA")],
            "divergence": [("osc", "Oszc"), ("div_period", "Per"), ("div_pivot", "Pivot")],
        }
        self._EXIT_TIP = {
            "st_period": _t("exit.tip.st_period"),
            "st_multiplier": _t("exit.tip.st_multiplier"),
            "wpr_period": _t("exit.tip.wpr_period"), "wpr_ma_period": _t("exit.tip.wpr_ma_period"),
            "osc": _t("exit.tip.osc"),
            "div_period": _t("exit.tip.div_period"),
            "div_pivot": _t("exit.tip.div_pivot"),
        }

        # A kockázatcsökkentés SAJÁT, teljes szélességű szakaszt kap: preset-
        # váltáskor MÁS mezők jelennek meg (runner, hányad, trigger R…), tehát
        # egy keskeny oldalsávba nem fér be kiszámíthatóan.
        ctl = tk.Frame(_mk("kockazat", _t("idlg2.kockazatcsokkentes")), bg=BG)
        ctl.pack(anchor="w", fill="x", padx=10, pady=(6, 0))

        # ── 1. csoport: Kockázatcsökkentés (ha már bent vagy) ────────────────
        rrg = tk.LabelFrame(ctl, text=_t("idlg.kockazatcsokkentes_ha_mar_bent"),
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
        _attach_tooltip(om, _t("idlg.ki_semmi_a_stop"))

        # Óvatos méret — Ki-nél elrejtve; Riskynél alapból pipa (de átállítható)
        _c0 = _rrs.get_cautious(self.symbol)
        if _c0 is None:
            _c0 = _rrx.wants_cautious_size(_rrs.get_preset(self.symbol))
        self._cautious_var = tk.BooleanVar(value=bool(_c0))
        self._cautious_cb = tk.Checkbutton(
            row, text=_t("bt.cautious"), variable=self._cautious_var,
            bg=BG, fg=FG_GRAY, selectcolor=BG_HEADER, font=self._sf,
            activebackground=BG, activeforeground=FG_WHITE,
            command=self._on_cautious_change)
        self._cautious_cb.grid(row=0, column=2, padx=(10, 0))
        _attach_tooltip(self._cautious_cb, _t("bt.cautious_tip"))

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
                        _t("idlg.a_felezo_pajzs_reszleges"))

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
                        _t("idlg.ido_stop_tananyag_ha"))

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
        _attach_tooltip(ome, _t("bt.exit_tip"))
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
             _t("idlg3.a_tp_hany_reszenel")),
            ("trail_activation_atr", "Trail indul",
             _t("idlg3.ennyi_atr_nyi_profit")),
            ("trail_distance_atr", _t("idlg3.trail_tav"),
             _t("idlg3.ennyi_atr_rel_koveti")),
            # ── Részleges zárás (Felező / Pajzs) ─────────────────────────
            # ⚠ Eddig CSAK fájlból volt állítható. A `trigger_R` dönti el,
            # MIKOR zár a Pajzs — és ha a TP ugyanoda esik, SOHA nem hat.
            ("trigger_R", "Trigger R",
             _t("idlg3.hany_r_nel_zarja") + chr(10) +
             _t("idlg3.ha_a_celar_ugyanide") + chr(10) +
             _t("idlg3.zaras_soha_nem_hat") + chr(10) +
             _t("idlg3.zarja_tegyel_ide_kisebbet")),
            ("halving_fraction", _t("idlg3.zart_hanyad"),
             _t("idlg3.a_felezo_ekkora_reszt")),
            ("shield_fraction", _t("idlg3.zart_hanyad"),
             _t("idlg3.a_pajzs_ekkora_reszt")),
        ]
        # ⚠ A FIGYELMEZTETÉS HELYE: ha a részleges zárás triggere a TP-re (vagy
        # azon túlra) esik, a Pajzs/Felező SOHA nem hat — a célár előbb zár. A
        # felületen ez eddig SEHOL nem látszott: a preset „Pajzs"-t mutatott, a
        # kötések meg egytől egyig teljes zárással, 1R-en.
        self._trig_warn = tk.Label(rrg, text="", bg=BG, fg=FG_YELLOW,
                                   font=self._sf, anchor="w", justify="left",
                                   wraplength=820)
        self._trig_warn.pack(anchor="w", padx=6, pady=(0, 4))
        # ⚠ A figyelmeztetés a `tp_rr_ratio`-tól is függ — az a PARAMÉTER
        # szakaszban él, tehát oda is be kell kötni, különben a mező átírása
        # után elavult képet mutatna.
        try:
            _tpe = (getattr(self, "entries", None) or {}).get("tp_rr_ratio")
            if _tpe is not None:
                _tpe.bind("<KeyRelease>",
                          lambda _e: self._warn_trigger_vs_tp(), add="+")
                _tpe.bind("<FocusOut>",
                          lambda _e: self._warn_trigger_vs_tp(), add="+")
        except tk.TclError:
            pass
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
        bldg = tk.LabelFrame(ctl, text=_t("idlg.pozicioepites_raepites_a_nyerore"),
                             bg=BG, fg=FG_BLUE, font=self._sf, labelanchor="nw")
        bldg.pack(anchor="w", fill="x", pady=(6, 0))
        brow = tk.Frame(bldg, bg=BG)
        brow.pack(anchor="w", padx=6, pady=4)
        tk.Label(brow, text=_t("bt.build"), bg=BG, fg=FG_GRAY, font=self._sf).pack(side="left")
        self._build_mode_name = tk.StringVar(value=_bst.NAME.get(_bst.get_mode(self.symbol), "Ki"))
        omb = tk.OptionMenu(brow, self._build_mode_name, *_bst.NAME.values(),
                            command=self._on_build_mode_change)
        _style_om(omb, self._sf)
        omb.pack(side="left", padx=(4, 0))
        _attach_tooltip(omb, _t("idlg.ki_kezi_a_gombbal"))
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
                        _t("idlg.piramidalis_meret_szorzo_minden"))
        # Trigger — csak Építés ≠ Ki
        self._build_trig_frame = tk.Frame(brow, bg=BG)
        tk.Label(self._build_trig_frame, text="Trigger:", bg=BG, fg=FG_GRAY,
                 font=self._sf).pack(side="left")
        self._build_trig_name = tk.StringVar(
            value=_pb.TRIGGER_NAME.get(_bc0.get("trigger", _pb.TRIGGER_CANDLE), _t("idlg3.gyertyas")))
        omt = tk.OptionMenu(self._build_trig_frame, self._build_trig_name,
                            *_pb.TRIGGER_NAME.values(), command=self._on_build_trigger_change)
        _style_om(omt, self._sf)
        omt.pack(side="left", padx=(4, 0))
        _attach_tooltip(omt, _t("idlg.gyertyas_trendkoveto_uj_csucs"))
        # R-lépés — csak R-alapú triggernél
        self._build_rstep_frame = tk.Frame(brow, bg=BG)
        tk.Label(self._build_rstep_frame, text=_t("bt.rstep"), bg=BG, fg=FG_GRAY,
                 font=self._sf).pack(side="left")
        self._build_rstep_var = tk.StringVar(value=str(_bc0.get("r_step", 1.0)))
        _re = tk.Entry(self._build_rstep_frame, textvariable=self._build_rstep_var, width=4,
                       bg=BG_HEADER, fg=FG_WHITE, font=self._sf, relief="flat",
                       insertbackground=FG_WHITE)
        _re.pack(side="left", padx=(2, 0))
        _re.bind("<FocusOut>", self._on_build_rstep_save)
        _re.bind("<Return>",   self._on_build_rstep_save)
        _attach_tooltip(self._build_rstep_frame,
                        _t("idlg.az_elso_lepes_r"))
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
                        _t("idlg.a_lepes_szorzoja_add"))

        self._update_rr_visibility()

        # Lot-létra tipp (a részleges záráshoz ≥2× min_lot kell)
        _ml = (self.cfg.get("pairs", {}).get(self.symbol, {}) or {}).get("min_lot", 0.01)
        tk.Label(body, text=_t("idlg.minlot_note", minlot=_ml),
                 bg=BG, fg=FG_GRAY_DIM, font=self._sf, justify="left",
                 wraplength=560).pack(anchor="w", padx=10, pady=(1, 0))

        # ── FUTTATÁS + EREDMÉNY: a lap utolsó két szakasza ──────────────────
        # ⚠ A sorrend a MUNKA sorrendje: mikor · mi engedi be · milyen számokkal ·
        # mi történik belépés után · FUTTASD · MI LETT BELŐLE. A futtatás nem
        # külön lap: külön lapon oda kellene lapozni megnézni, MILYEN értékkel
        # fut — és pont ez volt a panasz.
        _mk("futtatas", _t("idlg2.futtatas"))
        _mk("eredmeny", _t("idlg2.eredmeny"))

        # ── Backtest-eredmény sor (a Mentés-ág tölti) — szintén a rögzített
        #    sávban, hogy a futás állapota („Backtest fut…", letöltés) látszódjon.
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
        self._btn_save = tk.Button(btns, text=_t("btn.save"), bg=BTN_PLAY_BG,
                                   fg=BTN_PLAY_FG, relief="flat", font=self._sf,
                                   command=self._save)
        self._btn_save.pack(side="left", padx=6)
        # ⚠ A GOMBSOR MEGTISZTÍTVA. A „Backtest", a „Trials CSV" és az „MT4
        # visszajátszás" mind LEKERÜLT: az első kettő a Paraméter lap Futtatás /
        # Eredmény szakasza, a harmadik a Kapcsolat→MT4 lap — és a lapos
        # változat többet
        # tud — megjegyzett időszakot, szűrést, naptárat, élő tervet.
        #
        # Két belépési pont ugyanahhoz a művelethez nem kényelem, hanem kérdés:
        # „melyik a mérvadó?". Éppen ezt a kérdést szüntettük meg a lapok
        # összevonásával; egy megmaradt gomb visszahozta volna.
        #
        # A `_btn_bt` widget LÉTREJÖN (a Mentés-ág állítgatja az állapotát),
        # csak nincs kicsomagolva.
        self._btn_bt = tk.Button(btns, text="Backtest", bg=BTN_BT_BG, fg=BTN_BT_FG,
                                 relief="flat", font=self._sf,
                                 command=self._open_backtest_window)
        tk.Button(btns, text=_t("btn.cancel"), bg=BTN_DIS_BG, fg=BTN_DIS_FG, relief="flat",
                  font=self._sf, command=popup.destroy).pack(side="left", padx=6)

        self._fit_to_screen(popup, body, footer)
        self._refresh_section_summaries()
        # Az ELSŐ lap feltöltése — most már van `self._shell` (lásd `_on_tab`).
        self._build_overview_tab()
        self._maybe_build_run()
        self._opt_poll()

    def _maybe_build_run(self):
        """A futtatás-szakasz LUSTÁN épül: csak ha NYITVA van.

        ⚠ Nem óvatoskodás. A beágyazott backtest felépülésekor NEKIÁLL betölteni
        az M1 előzményt (több százezer gyertya) — ez korábban azért nem
        látszott, mert külön lapon ült, és csak akkor futott le, ha odalapoztál.
        Ha becsukva tartod a szakaszt, ez a költség sem jelentkezik."""
        try:
            if self._sections["futtatas"].is_open:
                self._build_run_sections()
        except (KeyError, AttributeError, tk.TclError):
            pass

    def _on_tab(self, name):
        """Lapváltás — a lapok LUSTA feltöltése (pl. `strategy/docs/<név>.md`).

        Ha a leírás-fájl nincs, a nézet KIÍRJA az elvárt útvonalat — így a
        hiányzó doksi nem üres lap, hanem felszólítás. Mindig a lemezről olvas,
        tehát szerkesztés után újranyitva azonnal friss.

        ⚠ A dokumentáció korábban a metódus KÖZEPÉN állt (egy `return` után),
        ahol a Python már nem docstringnek, hanem egy értelmetlen kifejezésnek
        látja: a `help()` és a szerkesztő sem mutatta.
        """
        # ⚠ A TabShell a KONSTRUKTORÁBAN megmutatja az első lapot — vagyis ez a
        # visszahívás lefut, mielőtt a `self._shell` értéket kapna. A lapokat
        # ilyenkor még nem lehet felépíteni (nincs mihez kérni az oldalt); az
        # első lap feltöltése a `_build` végén, expliciten történik.
        if not hasattr(self, "_shell"):
            return
        if name == "overview":
            # LUSTA + MINDIG FRISS: az állapot (él/áll, kézi szerkesztés,
            # kapuk) menet közben változhat, egy gyorsítótárazott lap pedig
            # éppen a figyelmeztetéseket mutatná elavultan.
            self._build_overview_tab()
            return
        if name == "params":
            # A futtatás-szakasz újraépül, ha a paraméterek közben változtak —
            # a `_build_run_sections` maga dönti el, kell-e (értékre hasonlít).
            self._maybe_build_run()
            return
        if name == "link":
            # MINDIG friss: a terminál-mappák állapota (mi van kint, mi elavult)
            # két megnyitás között is változhat — egy gyorsítótárazott lap épp
            # azt takarná el, amiért készült.
            self._build_link_tab()
            return
        if name == "trials":
            # LUSTA: az 500 soros CSV beolvasása és a tábla felépítése nem
            # kell minden ablak-megnyitáskor. Minden megjelenítéskor ÚJRAOLVAS:
            # futó optimalizálás alatt a CSV 10 trialonként frissül, tehát a
            # lap visszakattintása friss allast mutat (nem elavult masolatot).
            self._build_results_tab()
            return
        if name != "docs":
            return
        from dashboard import md_view
        try:
            md_view.render(self._shell.page("docs"), self.strategy.doc_text(),
                           source=str(self.strategy.doc_path()))
        except Exception as e:
            self.lbl_err.config(text=_t("docs.open_error", error=e))

    # ── „Futtatás” lap — a backtest, BEÁGYAZVA ─────────────────────────────
    # A doksi panasza: ugyanazt a paramétert két külön kinézetben kellett
    # kezelni. A backtest innentől nem külön ablak, hanem lap — a paraméterek
    # mellett, ugyanabban az ablakban.
    #
    # ⚠ A tartalom NEM másolat: ugyanaz a `BacktestDialog` épül ide, csak egy
    # keretbe ablak helyett. Egy „majdnem ugyanolyan" második változat pont
    # abban térne el, ami ritkán fut (megszakítás, hibaág, MT5-export), és az
    # nem derülne ki.

    def _build_run_sections(self):
        """A FUTTATÁS és az EREDMÉNY szakasz — ugyanazon az oldalon, mint a
        paraméterek.

        ⚠ Miért nem maradt külön lap. Egy másik lapon futtatni azt jelenti, hogy
        oda kell lapozni MEGNÉZNI, milyen értékkel fut — és pont ez volt a
        panasz. Itt a beállítás és az indítás EGY görgetésnyire van, a becsukott
        szakaszok fejléce pedig összegzést mutat, tehát a hosszú oldal nem ár."""
        page = self._sections["futtatas"].body
        # ⚠ FUTÁS KÖZBEN SOSEM ÉPÍTÜNK ÚJRA. Az újraépítés eldobja a szakasz
        # tartalmát és NULLÁZZA a végigpróbálás tengelyeit (`_sw_axes`) — a
        # háttérszál viszont fut tovább, és a végén az ÚJ (csomagolatlan)
        # vászonra próbálna rajzolni üres tengelyekkel. Élesben pontosan ez
        # történt: „546 futás kész." kiíródott, rajz sehol.
        # (A beágyazott backtestre ugyanez áll: egy futó példány `shutdown()`-ja
        # a szál alól húzná ki a widgeteket.)
        if self._sw_stop is not None or getattr(self, "_bt_running", False):
            return
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
        _res = self._sections["eredmeny"].body
        for w in _res.winfo_children():
            w.destroy()

        params = self._collect_params()
        if params is None:
            return                      # hibás mező — a lbl_err már szól róla
        pair_cfg = self.cfg.get("pairs", {}).get(self.symbol)
        if not isinstance(pair_cfg, dict):
            tk.Label(page, text=_t("idlg.nincs_par_config_ehhez"),
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
        self._build_result_section(_res)

        from dashboard.backtest_dialog import BacktestDialog
        self._run_params = dict(params)
        # ⚠ `host_scroll=False`: ez az oldal MAGA görget. Egy második görgethető
        # terület beleépítve összelapulna (a belső vászonnak nincs természetes
        # magassága), az egérgörgő pedig MINDKETTŐT mozdítaná.
        self._run_tab = BacktestDialog(
            self.popup, self.symbol, self.cfg, self.strategy, params, pair_cfg,
            self._rr_spec_from_ui(), self._hf, self._sf,
            on_result=self._on_bt_window_result,
            preset_name=self._rr_name.get(),
            on_apply_params=self._apply_params_from_bt,
            host=bt_host, on_state=self._on_run_state, host_scroll=False,
            on_run_done=self._on_run_done,
            provide_hours=self._allowed_hours_from_ui,
            provide_rr=self._rr_spec_from_ui,
            provide_build=self._build_cfg_from_ui)
        self._refresh_section_summaries()

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

    # A futás MÓDJA — a felhasználó kérése: „ne kelljen állandóan kivenni a
    # pipát, ha csak egy paramétert akarok megvizsgálni".
    RUN_BACKTEST = "backtest"     # egyetlen futás a MOSTANI értékekkel
    RUN_PLANNED = "planned"       # a bepipált dimenziók szerint (söprés/rács/opt)
    RUN_OPTIMIZE = "optimize"     # TELJES optimalizálás — a pipákat FIGYELMEN KÍVÜL

    _RUN_MODES = (RUN_BACKTEST, RUN_PLANNED, RUN_OPTIMIZE)

    def _load_run_mode(self) -> str:
        try:
            from core import backtest_prefs as _bp
            v = (_bp.get(self.symbol, self.strategy.name) or {}).get("run_mode")
            if v in self._RUN_MODES:
                return v
        except Exception:
            pass
        return self.RUN_PLANNED

    def _save_run_mode(self, v: str):
        try:
            from core import backtest_prefs as _bp
            _bp.save(self.symbol, self.strategy.name, run_mode=v)
        except Exception:
            pass

    def _sync_run_params(self):
        """A Paraméter szakasz MOSTANI értékei → a beágyazott backtest.

        Nem újraépítés: az eldobná a betöltött adatot, az időszakot és az előző
        eredményt. Csak az értékeket cseréljük — a jel-gyorsítótár magától
        érvénytelenít, ha a JEL-oldal változott (`signal_series_cached`)."""
        bt = getattr(self, "_run_tab", None)
        if bt is None:
            return
        cur = self._collect_params()
        if cur is None or cur == getattr(bt, "params", None):
            return
        bt.params = dict(cur)
        self._run_params = dict(cur)
        try:
            self.lbl_err.config(text="", fg=FG_GRAY_DIM)
        except (tk.TclError, AttributeError):
            pass

    def _on_run_mode(self):
        self._save_run_mode(self._run_mode.get())
        self._refresh_opt_space()
        self._refresh_run_mode_ui()
        self._refresh_section_summaries()

    def _note(self, text: str, fg=None):
        """RAGADÓS üzenet a gomb alatt.

        ⚠ A 2 mp-es állapot-lekérdezés eddig FELÜLÍRTA minden kilépési ág
        üzenetét az általános „Az optimalizálás nem fut."-tal — a felhasználó
        látta felvillanni, de nem tudta elolvasni, MIÉRT nem indult el semmi.
        Az üzenet addig marad, amíg a futás tényleg el nem indul, vagy amíg a
        mód/pipa nem változik (az új helyzet)."""
        self._run_note = (text, fg or FG_YELLOW)
        try:
            self._run_status.config(text=text, fg=fg or FG_YELLOW)
        except tk.TclError:
            pass
        self._prog_hide()

    def _prog_show(self, pct=None, text=""):
        """Haladás-sáv a gomb ALATT. `pct=None` → határozatlan (fut, de nem
        tudjuk, hol tart) — ez őszintébb, mint egy kitalált százalék."""
        try:
            if not self._prog_box.winfo_manager():
                # ⚠ `before`: a `pack` alapból a doboz VÉGÉRE tenné, a feltételek
                # és a keresési tér alá — a kérés viszont „közvetlen az indítás
                # gomb alatt".
                self._prog_box.pack(anchor="w", fill="x", padx=12, pady=(4, 0),
                                    before=self._run_status)
            if pct is None:
                if str(self._prog.cget("mode")) != "indeterminate":
                    self._prog.config(mode="indeterminate")
                    self._prog.start(60)
            else:
                self._prog.stop()
                self._prog.config(mode="determinate",
                                  value=max(0.0, min(100.0, float(pct))))
            self._prog_lbl.config(text=text)
        except (tk.TclError, AttributeError):
            pass

    def _prog_hide(self):
        try:
            self._prog.stop()
            self._prog_box.pack_forget()
        except (tk.TclError, AttributeError):
            pass

    def _refresh_run_mode_ui(self):
        """⚠ A mód/pipa változása ÚJ helyzet: a korábbi elutasítás oka elavult.

        A mód-választáshoz igazítja, MI látszik: a konfliktus-figyelmeztetés
        és az optimalizálás feltételei."""
        try:
            _m = self._run_mode.get()
        except (AttributeError, tk.TclError):
            return
        self._run_note = None
        _lbl = getattr(self, "_mode_lbl", None)
        if _lbl is not None:
            try:
                _c = self._mode_conflict()
                _lbl.config(text=_c)
                _lbl.pack_configure(pady=(2, 0) if _c else (0, 0))
            except tk.TclError:
                pass
        _cond = getattr(self, "_cond_box", None)
        if _cond is not None:
            try:
                if _m == self.RUN_OPTIMIZE:
                    _cond.pack(anchor="w", fill="x", padx=12)
                else:
                    _cond.pack_forget()
            except tk.TclError:
                pass

    def _tuned_rows(self) -> list:
        """A paraméter-sorok a PILLANATNYI pipákkal (egy helyen, hogy a terv és
        az indítás ugyanabból dolgozzon)."""
        return [dict(r, skipped=not self._skip_vars[r["key"]].get())
                for r in (self._opt_rows or []) if r["key"] in self._skip_vars]

    def _effective_mode(self) -> str:
        """A TÉNYLEGES mód. ⚠ Ha nincs mit hangolni, a „Hangolás" üres ígéret
        volna — ilyenkor magától Backtest, ahogy kérted.

        ⚠ Az OPTIMALIZÁLÁS mód SOSEM esik vissza: az a pipáktól FÜGGETLENÜL a
        teljes teret járja be, tehát üres pipa-listával is értelmes."""
        _m = getattr(self, "_run_mode", None)
        _m = _m.get() if _m is not None else self.RUN_PLANNED
        if _m == self.RUN_PLANNED and not any(
                not r.get("skipped") and r.get("values", 0) > 0
                for r in self._tuned_rows()):
            return self.RUN_BACKTEST
        return _m

    def _mode_conflict(self) -> str:
        """MIT hagy figyelmen kívül a MOSTANI mód — vagy üres, ha semmit.

        ⚠ EZ VOLT A HIBA GYÖKERE (a felhasználótól, 2026-08-18): „az Opt nem
        működik, ha egynél több paramétert választok ki… nem látszik, hogy
        történne valami." Nem hiba volt: a mentett mód `backtest` maradt, tehát
        a gomb HELYESEN egyetlen futást indított — a pipák pedig NÉMÁN nem
        számítottak. A mód és a pipák ellentmondását ki KELL mondani ott, ahol a
        gomb van; különben a felület úgy néz ki, mintha nem csinálna semmit."""
        _m = getattr(self, "_run_mode", None)
        _m = _m.get() if _m is not None else self.RUN_PLANNED
        _rows = self._tuned_rows()
        _n = sum(1 for r in _rows
                 if not r.get("skipped") and r.get("values", 0) > 0)
        if _m == self.RUN_BACKTEST and _n:
            return _t("idlg.tick_ignored", name=_n)
        if _m == self.RUN_OPTIMIZE:
            return _t("idlg3.a_pipak_nem_szamitanak")
        if _m == self.RUN_PLANNED and _n == 0:
            return _t("idlg3.nincs_pipa_igy_ez")
        return ""

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
        tk.Label(head, text=_t("idlg.mi_fog_tortenni"), bg=BG, fg=FG_WHITE,
                 font=self._hf).pack(side="left")

        # ── MI FUSSON: választó + Indítás, közvetlenül a cím alatt, BALRA ───
        # ⚠ A VÁLASZTÓ nem kényelmi elem. A futás típusát eddig KIZÁRÓLAG a
        # paraméterek pipái döntötték el — ha egyetlen paramétert akartál
        # megnézni egy sima backteszttel, előbb ki kellett venni MINDEN pipát,
        # utána vissza. A „Backtest" mód ezt megkerüli: az AKTUÁLIS értékekkel
        # fut egyszer, akkor is, ha minden be van pipálva.
        mode_box = tk.Frame(box, bg=BG)
        mode_box.pack(anchor="w", fill="x", padx=12, pady=(6, 0))
        self._run_mode = tk.StringVar(value=self._load_run_mode())
        for _val, _txt, _tip in (
                (self.RUN_BACKTEST, "Backtest",
                 _t("idlg3.egyszer_fut_le_pontosan")),
                (self.RUN_PLANNED, _t("idlg3.hangolas"),
                 _t("idlg3.a_bepipalt_dimenziok_szamabol")),
                (self.RUN_OPTIMIZE, _t("idlg3.optimalizalas"),
                 _t("idlg3.a_megszokott_opt_minden"))):
            _rb = tk.Radiobutton(mode_box, text=_txt, value=_val,
                                 variable=self._run_mode, bg=BG, fg=FG_GRAY,
                                 selectcolor=BG_HEADER, font=self._sf,
                                 activebackground=BG, activeforeground=FG_WHITE,
                                 anchor="w", command=self._on_run_mode)
            _rb.pack(side="left", padx=(0, 12))
            _attach_tooltip(_rb, _tip)
            if _val == self.RUN_PLANNED:
                self._rb_planned = _rb

        act = tk.Frame(box, bg=BG)
        act.pack(anchor="w", fill="x", padx=12, pady=(6, 0))
        self._plan_btn = tk.Button(act, text=_t("idlg.inditas"), bg=BTN_PLAY_BG,
                                   fg=BTN_PLAY_FG, relief="flat", font=self._sf,
                                   command=self._start_planned)
        self._plan_btn.pack(side="left")
        self._plan_short = tk.Label(act, text="", bg=BG, fg=FG_GRAY,
                                    font=self._sf, anchor="w", justify="left")
        self._plan_short.pack(side="left", padx=(10, 0), fill="x", expand=True)

        # ── HALADÁS-SÁV, KÖZVETLENÜL a gomb alatt ──────────────────────────
        # ⚠ A kérés szó szerint: „elinduljon egy progress bar közvetlen az
        # indítás gomb alatt, hogy látszódjon, hogy történik valami". A gomb
        # felirata (Indítás → Leállítás) megmondja, hogy FUT; a sáv azt, hogy
        # HALAD — a kettő nem ugyanaz. Egy órákig tartó optimalizálásnál az
        # „elindult" önmagában nem nyugtat meg senkit.
        #
        # ⚠ Alapból NINCS kicsomagolva: egy 0%-on álló sáv tétlenségben azt
        # sugallná, hogy fut valami, ami nem halad.
        from tkinter import ttk as _ttk
        self._prog_box = tk.Frame(box, bg=BG)
        self._prog = _ttk.Progressbar(self._prog_box, mode="determinate",
                                      maximum=100, length=260)
        self._prog.pack(side="left")
        self._prog_lbl = tk.Label(self._prog_box, text="", bg=BG, fg=FG_GRAY,
                                  font=self._sf)
        self._prog_lbl.pack(side="left", padx=(8, 0))

        self._run_status = _autowrap(tk.Label(box, text="", bg=BG, fg=FG_GRAY,
                                              font=self._sf, anchor="w",
                                              justify="left"),
                                     self._body_canvas)
        self._run_status.pack(anchor="w", fill="x", padx=12, pady=(2, 0))
        # ⚠ A KONFLIKTUS a gomb KÖZVETLEN közelébe: ott nézel, amikor nyomod.
        self._mode_lbl = _autowrap(tk.Label(box, text="", bg=BG, fg=FG_YELLOW,
                                            font=self._sf, anchor="w",
                                            justify="left"),
                                   self._body_canvas)
        self._mode_lbl.pack(anchor="w", fill="x", padx=12)

        self._tuned_lbl = _autowrap(tk.Label(box, bg=BG, fg=FG_GRAY, font=self._sf,
                                             anchor="w", justify="left"),
                                    self._body_canvas)
        self._tuned_lbl.pack(anchor="w", fill="x", padx=12)
        self._space_lbl = _autowrap(tk.Label(box, bg=BG, fg=FG_GRAY_DIM,
                                             font=self._sf, anchor="w",
                                             justify="left"),
                                    self._body_canvas)
        self._space_lbl.pack(anchor="w", fill="x", padx=12, pady=(0, 4))

        # ── A FELTÉTELEK: időszakok és kapuk (a volt Optimalizálás lapról) ──
        # ⚠ A FELTÉTELEK (walk-forward ablakok, kapuk, minősítés) CSAK az
        # optimalizálásra vonatkoznak — a kérés szerint csak akkor látszódjanak.
        # Backtest módban egy walk-forward magyarázat félrevezető: ott nincsenek
        # tanuló/vizsga ablakok, egyetlen futás megy.
        self._cond_box = None
        if plan:
            cond = tk.Frame(box, bg=BG)
            self._cond_box = cond
            w = plan["wf"]
            _txt = (_t("idlg.walkforward", splits=w["splits"], train=w["train_months"],
                       test=w["test_months"]))
            if plan["windows"]:
                _last = plan["windows"][-1]
                _txt += (_t("idlg.last_exam", start=str(_last["test_start"])[:10],
                          end=str(_last["test_end"])[:10]))
            tk.Label(cond, text=_txt, bg=BG, fg=FG_GRAY_DIM, font=self._sf,
                     anchor="w").pack(anchor="w")
            if not plan["windows"]:
                tk.Label(cond, bg=BG, fg=FG_RED, font=self._sf, anchor="w",
                         justify="left", wraplength=820,
                         text=(_t("idlg.egyetlen_walk_forward_ablak"))
                         ).pack(anchor="w")
            if not plan["exec_gates"]:
                tk.Label(cond, bg=BG, fg=FG_RED, font=self._sf, anchor="w",
                         justify="left", wraplength=820,
                         text=(_t("idlg.a_vegrehajtasi_kapuk_ki"))
                         ).pack(anchor="w")
            else:
                act = sorted(k for k, e in (plan["gate_effects"] or {}).items()
                             if e != _gt.EFFECT_NONE)
                tk.Label(cond, bg=BG, fg=FG_GRAY_DIM, font=self._sf, anchor="w",
                         text=("Kapuk: " + (", ".join(
                             f"{_gt.label_of(k)} "
                             f"({_gt.EFFECT_LABEL.get(plan['gate_effects'][k], '')})"
                             for k in act) if act else _t("idlg3.egyik_sem_aktiv")))
                         ).pack(anchor="w")
            tk.Label(cond, bg=BG, fg=FG_GRAY_DIM, font=self._sf, anchor="w",
                     justify="left", wraplength=820,
                     text=(_t("idlg.a_mentett_minosites_csak"))).pack(anchor="w")

        self._refresh_opt_space()
        self._refresh_run_mode_ui()

    # ── AZ EREDMÉNY-SZAKASZ ───────────────────────────────────────────────
    # ⚠ Miért KÜLÖN szakasz a futtatástól. A kettő különböző életciklusú: a
    # futtatás beállításai a következő indításról szólnak, az eredmény az
    # ELŐZŐRŐL. Egy szakaszban a friss szám és a most átállított kapcsoló
    # egymás mellett azt sugallná, hogy a szám ehhez a beállításhoz tartozik.

    def _build_result_section(self, box):
        # ── A rajz és a mércéje (1–2 hangolt paraméternél a végigmérés) ─────
        self._sweep_box = tk.Frame(box, bg=BG)
        self._sweep_box.pack(anchor="w", fill="x", padx=12, pady=(4, 0))
        _sb = tk.Frame(self._sweep_box, bg=BG)
        _sb.pack(anchor="w", fill="x")
        tk.Label(_sb, text=_t("idlg.merce"), bg=BG, fg=FG_GRAY_DIM,
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
        # A végigmérés IDŐSZAKA a futtatás mezőiből jön (egy helyen állítod).

        # ── KÖTÉS-LISTA: a futás kötései TÉTELESEN ─────────────────────────
        # ⚠ Ez az, ami eddig hiányzott. A futás egyetlen sorban végződött
        # („42 kötés, +1 234$, PF 1,31"), és ha a szám nem tetszett, nem volt
        # hova továbbmenni: nem derült ki, hogy egy rossz átlagot két
        # katasztrofális kötés húz-e le vagy negyven közepes, és hogy a
        # nyereség a célárból jön-e vagy a trailingből.
        from dashboard import trade_list as _tl
        tk.Label(box, text=_t("idlg.kotesek"), bg=BG, fg=FG_WHITE, font=self._hf,
                 anchor="w").pack(anchor="w", padx=12, pady=(10, 2))
        self._trades = _tl.build(box, {"small": self._sf},
                                 on_export=self._export_trades)
        self._trade_rows = []

    def _allowed_hours_from_ui(self):
        """A KERESKEDÉSI ÓRÁK szakasz pillanatnyi állapota — ez a mérés óra-kapuja.

        ⚠ Nincs külön „csak a kereskedési órákban" kapcsoló. A felhasználó
        kérése szó szerint: „azért raktuk egy helyre, hogy egy helyen legyen
        állítható. Ha mind, akkor kereskedik mindenhol; ha csökkentünk rajta,
        akkor csökken a backtest és az optimalizálás is."

        Mind a 24 óra → `None`: az azonos a „nincs szűrés"-sel, de olcsóbb (a
        `run_pair` ilyenkor nem is nézi az órát), és a naplóban is egyértelmű."""
        try:
            on = {int(h) for h, v in (self._hour_on or {}).items() if v}
        except (TypeError, ValueError, AttributeError):
            return None
        return None if len(on) >= 24 else on

    def _build_cfg_from_ui(self):
        """A POZÍCIÓÉPÍTÉS szakasz pillanatnyi állapota (a `run_pair` build
        override-ja) — ugyanaz az egy-forrás elv, mint az óráknál és az rr-nél."""
        _bst, _pb = self._bst, self._pb
        mode = {v: k for k, v in _bst.NAME.items()}.get(
            self._build_mode_name.get(), _bst.MODE_OFF)
        trig = {v: k for k, v in _pb.TRIGGER_NAME.items()}.get(
            self._build_trig_name.get(), _pb.TRIGGER_CANDLE)

        def _f(var, dflt, lo=None, hi=None):
            v = _num(var.get())
            if v is None or (lo is not None and v <= lo) or                (hi is not None and v >= hi):
                return dflt
            return v

        return {"mode": mode,
                "size_factor": _f(self._build_sf_var, 0.7, lo=0),
                "trigger": trig,
                "r_step": _f(self._build_rstep_var, 1.0, lo=0),
                "r_shrink": _f(self._build_rshrink_var, 0.5, lo=0, hi=1)}

    def _export_trades(self, rows):
        """A MEGJELENÍTETT (szűrt) kötések CSV-be — a magyar Excel formátumában.

        ⚠ A szűrt halmazt írjuk, nem az összeset: ha valaki „csak Stop"-ra
        szűrt és exportál, azt akarja tovább nézni, nem az egészet."""
        from tkinter import filedialog, messagebox
        from dashboard import trade_list as _tl
        if not rows:
            messagebox.showinfo(_t("idlg.kotesek"), _t("idlg.nincs_megjelenitheto_kotes"),
                                parent=self.popup)
            return
        path = filedialog.asksaveasfilename(
            parent=self.popup, defaultextension=".csv",
            initialfile=f"{self.symbol}_{self.strategy.name}_kotesek.csv",
            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            # ⚠ utf-8-SIG: a magyar Excel BOM nélkül cp1250-nek olvasná az
            # ékezeteket („Kiszállási jel" → olvashatatlan).
            with open(path, "w", encoding="utf-8-sig", newline="") as fh:
                fh.write(_tl.to_csv(rows))
            self.lbl_err.config(text=_t("idlg.trades_saved", n=len(rows), path=path),
                                fg=FG_GREEN)
        except OSError as ex:
            self.lbl_err.config(text=_t("save.error", error=ex), fg=FG_RED)

    def _on_run_done(self, result):
        """A backtest LEFUTOTT — a kötés-lista feltöltése.

        ⚠ Ez NEM ugyanaz, mint az `on_result`. Az a MENTETT minősítést írja
        vissza a főképernyőre, és csak akkor, ha ugyanazzal a kockázat-
        csökkentéssel mértünk, mint a mentett — különben egy feltáró futás
        szennyezné a nyilvántartott számot. A kötés-lista viszont a MOST
        lefuttatott futás nézete: annak akkor is látszania kell, ha feltáró
        beállítással mértél. Épp olyankor a legérdekesebb."""
        from dashboard import trade_list as _tl
        try:
            self._trade_rows = _tl.rows_from(result)
            self._trades.set_rows(self._trade_rows)
            self._refresh_section_summaries()
        except (tk.TclError, AttributeError):
            pass

    _OPT_TEXT = {
        "OPTIMIZING": (_t("idlg3.optimalizalas_fut_a_haladas"), FG_GREEN),
        "QUEUED": (_t("idlg3.optimalizalas_sorban_all_masik"), FG_YELLOW),
    }

    def _opt_poll(self):
        """Amíg az ablak nyitva, KÖVETJÜK az optimalizáló állapotát.

        ⚠ Enélkül a gomb „Optimalizálás leállítása" maradna azután is, hogy a
        futás befejeződött — és a következő kattintás egy már nem létező futást
        próbálna leállítani. Az állapotot MÁSIK PROCESSZ írja, tehát nincs
        esemény, amire feliratkozhatnánk; kérdezni kell.

        2 mp: elég ritka ahhoz, hogy ne látszódjon a terhelésen (fájl-stat), és
        elég sűrű ahhoz, hogy a gomb ne mutasson elavult állapotot."""
        if getattr(self, "_closed", False):
            return
        if callable(getattr(self, "opt_state_of", None)) and                 getattr(self, "_plan_btn", None) is not None:
            # Csak akkor nyúlunk a gombhoz, ha ÉPP nem egy beágyazott backtest
            # futása birtokolja (az `_on_run_state` állítja Megszakításra).
            if not getattr(self, "_bt_running", False):
                self._sync_opt_status()
        # A legenda körei az ÉLŐ állapotot mutatják — velük is lépést tartunk.
        self._refresh_legend_dots()
        try:
            self.popup.after(2000, self._opt_poll)
        except tk.TclError:
            pass

    def _sync_opt_status(self):
        """A futás-állapot az OPTIMALIZÁLÓ TÉNYLEGES állapotából.

        ⚠ Nem abból, hogy meghívtuk-e az indítót: a `_live2_opt_click` MORPH —
        futó optimalizálást LEÁLLÍT, sorban állót KIVESZ, kereskedő stratégiát
        el sem indít. Egy fix „elindítva" felirat ezekben hazudna."""
        _st = ""
        _of = getattr(self, "opt_state_of", None)
        if callable(_of):
            try:
                _st = str(_of(self.symbol, self.strategy.name) or "")
            except Exception:
                _st = ""
        _note = getattr(self, "_run_note", None)
        if _st not in self._OPT_TEXT and _note:
            txt, fg = _note          # az elutasítás oka MEGMARAD, amíg nem indul
        else:
            txt, fg = self._OPT_TEXT.get(_st, (
                _t("idlg3.az_optimalizalas_nem_fut"), FG_GRAY))
            if _st in self._OPT_TEXT:
                self._run_note = None
        # ⚠ A HALADÁS a MÁSIK PROCESSZ állapotából jön (`opt_activity`) — ugyanaz
        # a forrás, amit a főképernyő Opt-cellája mutat. Így az ablakban látott
        # százalék és a soron látott SOSEM tér el.
        if _st == "OPTIMIZING":
            _pct = None
            try:
                from core import opt_activity as _oa
                _pct = _oa.progress_pct(self.symbol, self.strategy.name)
            except Exception:
                _pct = None
            # ⚠ A trialok ELŐTT (adat-előkészítés) még nincs haladás: ilyenkor
            # határozatlan sáv megy — nem hazudunk 0%-ot egy dolgozó futásra.
            self._prog_show(_pct, f"{_pct}%" if _pct is not None
                            else _t("idlg3.elokeszites"))
        elif not getattr(self, "_bt_running", False) and self._sw_stop is None:
            self._prog_hide()
        try:
            self._run_status.config(text=txt, fg=fg)
            self._plan_btn.config(
                text=(_t("idlg3.optimalizalas_leallitasa") if _st == "OPTIMIZING"
                      else (_t("idlg3.kivetel_a_sorbol") if _st == "QUEUED" else _t("idlg.inditas"))))
        except tk.TclError:
            pass

    def _on_run_state(self, running: bool):
        """A beágyazott backtest futás-állapota → a terv-sáv EGYETLEN gombja.

        ⚠ A jelző (`_bt_running`) azért kell, hogy az optimalizáló-lekérdező
        (`_opt_poll`) NE írja felül a „Megszakítás" feliratot egy futó backtest
        közben: a kettő ugyanazt a gombot használja.

        Enélkül a gomb futás közben is „Indítás"-t mutatna, és egy második
        kattintás újraindítaná azt, ami épp fut."""
        self._bt_running = bool(running)
        try:
            if running:
                self._plan_btn.config(text=_t("idlg.leallitas"),
                                      command=self._run_tab._cancel)
                self._prog_show(None, "backtest fut…")
            else:
                self._prog_hide()
                self._plan_btn.config(text=_t("idlg.inditas"), state="normal",
                                      command=self._start_planned)
                self._sync_opt_status()   # hátha közben optimalizálás indult
        except (tk.TclError, AttributeError):
            pass

    def _start_planned(self):
        """Az EGYETLEN Indítás gomb: a bepipált dimenziók száma dönti el, mi fut.

        ⚠ Ez nem kényelmi összevonás. Eddig ugyanaz a művelet (paraméter beállít
        → teljes futtatás → kiértékelés) HÁROM helyen indult, más-más néven, és
        a felhasználónak kellett fejben tartania, melyik mit jelent."""
        # ⚠ A PARAMÉTEREK FRISSÍTÉSE AZ INDÍTÁS ELŐTT. A beágyazott backtest a
        # FELÉPÍTÉSKORI pillanatképpel dolgozik (`self.params`); az újraépítés
        # eddig csak lapváltáskor vagy a szakasz kinyitásakor futott le. A
        # leggyakoribb munkamenetben viszont — átírod a mezőt, és RÖGTÖN
        # Indítást nyomsz ugyanazon a lapon — egyik sem történik meg, tehát a
        # futás a RÉGI értékkel ment. A felület közben azt írta ki, hogy „ha ott
        # átírsz valamit, ez a lap magától frissül".
        #
        # Mérve: a `tp_rr_ratio` 1,0 → 2,0 átírása után minden kötés továbbra is
        # ±1,00R-en zárt — a célár nem mozdult, mert a futás nem is látta az új
        # értéket.
        self._sync_run_params()

        from core import opt_plan as _op
        rows = self._tuned_rows()
        # ⚠ A MÓD-VÁLASZTÓ ELSŐBBSÉGET ÉLVEZ. „Backtest" módban egyetlen futás
        # megy a mostani értékekkel, AKKOR IS, ha minden paraméter be van
        # pipálva — épp ezért van a választó: hogy egyetlen próbához ne kelljen
        # kiszedni, majd visszatenni az összes pipát.
        _mode = self._effective_mode()
        # ⚠ OPTIMALIZÁLÁS: a pipákat FIGYELMEN KÍVÜL hagyja, a TELJES teret
        # keresi. A „Hangolás" 3+ ága ettől KÜLÖNBÖZIK: az a bepipáltakon
        # optimalizál (a kivett kulcsok az alapértéken maradnak). A kettő
        # ugyanazt a motort hívja, más kereséssel — ezért egy függvény.
        if _mode == self.RUN_OPTIMIZE:
            self._start_optimize(all_params=True)
            return
        kind = (_op.KIND_SINGLE if _mode == self.RUN_BACKTEST
                else _op.run_plan(rows, 0)["kind"])
        if kind == _op.KIND_SINGLE:
            # 0 hangolt → EGYETLEN futás: ez maga a backtest.
            if self._run_tab is not None:
                self._sweep_box.pack_forget()
                self._run_status.config(text="Backtest indul…", fg=FG_GRAY)
                self._run_tab._start()
            return
        if kind in (_op.KIND_SWEEP, _op.KIND_GRID):
            self._sweep_box.pack(anchor="w", fill="x", padx=12, pady=(4, 0))
            self._sw_canvas.pack(fill="x", pady=(4, 2))
            self._sw_best.pack(anchor="w", pady=(0, 8))
            self._run_status.config(
                text=_t("idlg.runs_start", runs=_op.run_plan(rows, 0)["runs"]), fg=FG_GRAY)
            self._start_sweep()
            return
        # 3+ hangolt → OPTIMALIZÁLÁS a BEPIPÁLTAKON.
        self._start_optimize(all_params=False)

    def _start_optimize(self, all_params: bool = False):
        """Az optimalizálás indítása (vagy leállítása) — külön processzben.

        `all_params=True` → a kihagyás-lista FIGYELMEN KÍVÜL marad, a teljes
        teret keressük (ez az „Optimalizálás" mód). `False` → a bepipált
        dimenziókon (a „Hangolás" 3+ ága).
        """
        # ⚠ EZ AZ EGYETLEN INDÍTÁSI PONT. A sorból az OPT vezérlőt levettük (egy
        # gomb, ami órákra indított valamit, amiről a felület semmit nem mondott)
        # — a helyére EZ a szakasz lépett, ahol előtte látod az időszakokat, a
        # kapukat, a hangolt dimenziókat és a keresési teret. A bekötés viszont
        # sokáig HIÁNYZOTT: a szakasz csak annyit írt ki, hogy „azt a főképernyő
        # OPT gombja indítja" — ami addigra már nem létezett, tehát az
        # optimalizálás SEHONNAN nem volt indítható.
        self._sweep_box.pack_forget()
        _opt = getattr(self, "on_optimize", None)
        if not callable(_opt):
            self._note(_t("idlg3.ez_az_ablak_nincs"), FG_YELLOW)
            return
        # ⚠ ELŐBB NÉZZÜK MEG, fut-e MÁSHOL. A zárat úgyis a munkás-processz
        # ellenőrzi, de akkor már elindult egy processz, ami rögtön el is hasal —
        # a felhasználó pedig egy „Hiba:" sort lát a soron, nem itt, ahol
        # megnyomta. Csak INDÍTÁS előtt kérdezünk: ha épp MI futtatjuk, a gomb
        # LEÁLLÍT, és azt nem szabad a zárral megakadályozni.
        _cur = ""
        _of = getattr(self, "opt_state_of", None)
        if callable(_of):
            try:
                _cur = str(_of(self.symbol, self.strategy.name) or "")
            except Exception:
                _cur = ""
        if _cur not in ("OPTIMIZING", "QUEUED"):
            from core import opt_lock as _ol
            if _ol.is_held(self.symbol, self.strategy.name):
                self._note(_ol.describe(_ol.read(self.symbol, self.strategy.name),
                                        self.symbol, self.strategy.name), FG_RED)
                return
        try:
            # ⚠ A régi (2 argumentumos) bekötés is működjön: egy önállóan
            # megnyitott ablakban a hívó lehet régebbi aláírású.
            try:
                _refused = _opt(self.symbol, self.strategy.name,
                                all_params=all_params)
            except TypeError:
                _refused = _opt(self.symbol, self.strategy.name)
        except Exception as ex:
            log.exception("optimalizálás indítási hiba (%s/%s)",
                          self.symbol, self.strategy.name)
            self._note(_t("idlg.start_error", error=ex), FG_RED)
            return
        # ⚠ AZ ELUTASÍTÁST ITT KELL KIÍRNI, a gomb mellett. A hívó eddig a
        # FŐABLAK állapotsorába írta az okot — az a paraméter-ablak alatt van,
        # tehát a felhasználó szemszögéből a gomb egyszerűen nem csinált semmit.
        if _refused:
            self._note(str(_refused), FG_YELLOW)
            return
        self._run_note = None
        # ⚠ A VISSZAJELZÉS a TÉNYLEGES állapotból jön, nem abból, hogy hívtuk a
        # függvényt. A `_live2_opt_click` MORPH: ha épp futott, LEÁLLÍTOTTA; ha
        # a stratégia kereskedik, el sem indítja. Egy fix „elindítva" felirat
        # ezekben az esetekben hazudna.
        self._sync_opt_status()

    # ── „Áttekintés” lap — mi ennek a párnak az ÁLLAPOTA ───────────────────
    # A kérés: „az első oldalon csak egy dashboard-szerű dolog lehetne, ahol
    # látod, hogy mikor kereskedik, meg a minőséget, meg ilyeneket."
    #
    # ⚠ A lap ÉRTÉKE nem a metrikák megismétlése — azok máshol is látszanak —,
    # hanem a FIGYELMEZTETÉSEK: azok az állapotok, amikben minden rendben
    # LÁTSZIK, közben nem (kézi szerkesztés a mentett minősítés után, kapu-
    # eltérés, szennyezett OOS). Ezek ma mind némák.

    _HOUR_H = 74            # az óra-sáv magassága képpontban

    def _build_stage_legend(self, body):
        """A jelölő-körök MAGYARÁZATA — a stratégia saját stádium-listájából.

        Az `n.` sorszám a soron látható BALRÓL JOBBRA sorrend: a kör helye a
        táblán pontosan ez, tehát össze lehet párosítani ránézésre.

        ⚠ A SZÍNEK jelentése is ide tartozik. Egy zöld és egy piros kör NEM
        ugyanaz a stádium két állapota: az IRÁNYT mondja (BUY/SELL). Enélkül a
        piros kör „hibának" látszik, holott egy kész SELL-szetup."""
        try:
            _stages = list(self.strategy.columns()[0].stages)
        except (AttributeError, IndexError, TypeError):
            return
        if not _stages:
            return
        tk.Label(body, text=_t("idlg.mit_jelentenek_a_karikak"), bg=BG, fg=FG_WHITE,
                 font=self._hf, anchor="w").pack(anchor="w", padx=12, pady=(12, 2))
        tk.Label(body, bg=BG, fg=FG_GRAY_DIM, font=self._sf, anchor="w",
                 text=(_t("idlg.stages_hint", n=len(_stages)))
                 ).pack(anchor="w", padx=12)
        grid = tk.Frame(body, bg=BG)
        grid.pack(anchor="w", fill="x", padx=12, pady=(2, 0))
        # ⚠ A KÖRÖK AZ ÉLŐ ÁLLAPOTOT MUTATJÁK, nem egy dísz-zöldet. Egy statikus
        # példa-kör mellett a magyarázat elolvasható, de nem használható: a
        # kérdés nem az, hogy „mit jelentene, ha zöld volna", hanem hogy MOST
        # melyik feltétel áll. A színt UGYANABBÓL a forrásból vesszük, amiből a
        # sor (`ds.strategy_cells`) — így a két nézet nem csúszhat szét.
        self._legend_dots = {}
        for i, (_key, _label) in enumerate(_stages, start=1):
            row = tk.Frame(grid, bg=BG)
            row.pack(anchor="w", fill="x")
            tk.Label(row, text=f"{i}.", bg=BG, fg=FG_GRAY_DIM, font=self._sf,
                     width=3, anchor="e").pack(side="left")
            _dot = tk.Label(row, text="●", bg=BG, fg=FG_GRAY_DIM, font=self._sf)
            _dot.pack(side="left", padx=(4, 6))
            self._legend_dots[_key] = _dot
            tk.Label(row, text=_label, bg=BG, fg=FG_WHITE, font=self._sf,
                     anchor="w").pack(side="left")
            tk.Label(row, text=f"({_key})", bg=BG, fg=FG_GRAY_DIM,
                     font=self._sf, anchor="w").pack(side="left", padx=(6, 0))
        self._refresh_legend_dots()
        tk.Label(body, bg=BG, fg=FG_GRAY, font=self._sf, anchor="w",
                 justify="left", wraplength=820, text=(
                     _t("idlg3.a_kor_szine_az") +
                     chr(10) + _t("idlg3.a_korok_elotti_betu"))
                 ).pack(anchor="w", padx=12, pady=(4, 0))

    def _refresh_legend_dots(self):
        """A legenda köreinek színe az ÉLŐ stádium-cellákból.

        ⚠ UGYANAZ A FORRÁS, mint a soré (`ds.strategy_cells` → `_stage_color`):
        két képlet ugyanarra a kérdésre mindig szétcsúszik, és itt épp az volna a
        baj, ha a magyarázat mást mutatna, mint amit magyaráz.

        Ha a hívó nem adott hozzáférést az élő állapothoz (önálló/fejlesztői
        megnyitás), a körök HALVÁNYAK maradnak — nem hazudunk zöldet."""
        _dots = getattr(self, "_legend_dots", None)
        if not _dots:
            return
        cells = {}
        _get = getattr(self, "stage_cells_of", None)
        if callable(_get):
            try:
                cells = _get(self.symbol, self.strategy.name) or {}
            except Exception:
                cells = {}
        from dashboard import live_row as _lr
        for key, lbl in _dots.items():
            _c = cells.get(key)
            _color = _c[1] if isinstance(_c, (tuple, list)) and len(_c) > 1 else                 getattr(_c, "color", None)
            try:
                lbl.config(fg=_lr._stage_color(_color or "muted"))
            except tk.TclError:
                pass

    def _build_overview_tab(self):
        page = self._shell.page("overview")
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
            tk.Label(page, text=_t("idlg.overview_error", error=ex), bg=BG,
                     fg=FG_RED, font=self._sf).pack(anchor="w", padx=12, pady=12)
            return

        holder, body, _cv = _scrollable(page)
        holder.pack(side="top", fill="both", expand=True)

        # ── Fejléc: mi ez, és mit csinál MOST ──────────────────────────────
        head = tk.Frame(body, bg=BG)
        head.pack(anchor="w", fill="x", padx=12, pady=(10, 2))
        tk.Label(head, text=f"{o['symbol']}  ·  {o['strategy']}", bg=BG,
                 fg=FG_WHITE, font=self._hf).pack(side="left")
        _state_txt = {"live": "ÉL", "stopped": _t("idlg3.allitva")}.get(o["state"], o["state"] or "—")
        _state_fg = FG_GREEN if o["state"] == "live" else FG_GRAY
        tk.Label(head, text=f"   {_state_txt}", bg=BG, fg=_state_fg,
                 font=self._hf).pack(side="left")
        if o["mode"] == "signal":
            tk.Label(head, text=_t("idlg.csak_jelzes"), bg=BG, fg=FG_YELLOW,
                     font=self._sf).pack(side="left")
        from dashboard import theme as _th
        _gfg = _th.color(o.get("grade_color_name") or "muted")
        tk.Label(head, text=_t("idlg.quality_line", grade=o["grade"]), bg=BG, fg=_gfg,
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
            tk.Label(body, text=_t("idlg.nincs_mentett_minosites"), bg=BG, fg=FG_GRAY_DIM,
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

        # ── MIT JELENTENEK A KARIKÁK ──────────────────────────────────────
        # ⚠ A soron stádiumonként egy kör mutatja, hol tart a szetup — de eddig
        # SEHOL nem volt kiírva, MELYIK kör mit jelent. A jelölő maga a napi
        # használat legfontosabb eleme; egy meg nem magyarázott jelrendszert a
        # felhasználónak kellett kikövetkeztetnie a viselkedésből.
        #
        # A lista a STRATÉGIA SAJÁT deklarációjából épül (`columns()[0].stages`),
        # nem bedrótozott szövegből: így egy új stratégia ingyen megkapja, és
        # nem csúszhat el a valóságtól. (A wpr_sma-nak és a bollingernek 3
        # stádiuma van, az ml_ai-nak KETTŐ — egy „három karika" felirat máris
        # hazudna.)
        self._build_stage_legend(body)

        # ── MIKOR kereskedik ──────────────────────────────────────────────
        tk.Label(body, text="Mikor kereskedik", bg=BG, fg=FG_WHITE,
                 font=self._hf, anchor="w").pack(anchor="w", padx=12, pady=(12, 2))
        has_hours = any(h["pnl"] is not None for h in o["hours"])
        if not has_hours:
            tk.Label(body, bg=BG, fg=FG_GRAY_DIM, font=self._sf, anchor="w",
                     text=(_t("idlg.nincs_orankenti_adat_az"))
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
                         _t("idlg.oszlop_az_adott_ora"))
                     ).pack(anchor="w", padx=12, pady=(2, 0))

        # ── Kapuk / adat / kor ────────────────────────────────────────────
        tk.Label(body, text=_t("idlg.kornyezet"), bg=BG, fg=FG_WHITE, font=self._hf,
                 anchor="w").pack(anchor="w", padx=12, pady=(12, 2))
        act = [k for k, e in (o["gates"] or {}).items() if e != _gt.EFFECT_NONE]
        tk.Label(body, bg=BG, fg=FG_GRAY, font=self._sf, anchor="w",
                 justify="left", text=(
                     "Kapuk: " + (", ".join(
                         f"{_gt.label_of(k)} ({_gt.EFFECT_LABEL.get(o['gates'][k], '')})"
                         for k in sorted(act)) if act else _t("idlg3.egyik_sem_aktiv")))
                 ).pack(anchor="w", padx=12)
        if o["data_from"] is not None:
            tk.Label(body, bg=BG, fg=FG_GRAY, font=self._sf, anchor="w",
                     text=(_t("idlg.history_span", start=str(o["data_from"])[:10],
                           end=str(o["data_to"])[:10]))).pack(anchor="w", padx=12)
        _age = o["optimized_age_days"]
        tk.Label(body, bg=BG, fg=FG_GRAY, font=self._sf, anchor="w",
                 text=(_t("idlg.last_opt", date=str(o["optimized_at"])[:10],
                       days=f"{_age:.0f}") if _age is not None
                       else _t("idlg3.utolso_optimalizalas"))).pack(anchor="w", padx=12,
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

    # ── A szakaszok nyitott/csukott állapota ───────────────────────────────

    def _on_section_toggle(self, key: str, is_open: bool):
        """A becsukás/kinyitás MEGJEGYZŐDIK (pár + stratégia szinten).

        ⚠ Nem a config.json-ba: ez pusztán megjelenítési kényelem, a motor
        viselkedésére nincs hatása — a config csak az ELTÉRÉST rögzítheti."""
        from dashboard import section as _sec
        _sec.save_open(self.symbol, self.strategy.name, key, is_open)
        if key == "futtatas" and is_open:
            self._maybe_build_run()      # az első kinyitáskor épül fel
        if is_open:
            # ⚠ A KINYITOTT SZAKASZ GÖRDÜLJÖN A LÁTÓTÉRBE. A lap 3000 px magas —
            # a Futtatás szakasz 1495 px-nél kezdődik, tehát az Indítás gomb
            # kinyitás után is a képernyő alatt maradna, és a felhasználó nem
            # látná, mit nyitott ki. A `after_idle` kell: a görgetés csak azután
            # helyes, hogy a Tk újraszámolta az elrendezést.
            try:
                self.popup.after_idle(lambda k=key: self._scroll_section_into_view(k))
            except (tk.TclError, AttributeError):
                pass

    def _scroll_section_into_view(self, key: str):
        """A szakasz FEJLÉCE kerüljön a látható terület tetejére.

        A vászon `yview_moveto` arányt vár (0..1), ezért a widget helyét a törzs
        TELJES magasságához viszonyítjuk. Ha a tartalom elfér, nincs mit
        görgetni — akkor nem is nyúlunk hozzá."""
        sc = (getattr(self, "_sections", None) or {}).get(key)
        cv = getattr(self, "_body_canvas", None)
        if sc is None or cv is None:
            return
        try:
            cv.update_idletasks()
            total = max(1, self._body.winfo_reqheight())
            if total <= cv.winfo_height():
                return                       # elfér, nincs görgetés
            y = sc.frame.winfo_y()
            cv.yview_moveto(max(0.0, min(1.0, y / total)))
        except (tk.TclError, AttributeError, ZeroDivisionError):
            pass

    def _refresh_section_summaries(self):
        """A becsukott szakasz EGYETLEN információja a fejléc-összegzés.

        ⚠ Enélkül a becsukás épp azt a kérdést szülné, amit az egész átalakítás
        megszüntetni próbál: „most akkor mi van beállítva?" — és ki kellene
        nyitni, hogy megtudd."""
        secs = getattr(self, "_sections", None) or {}
        if not secs:
            return
        try:
            from core import gates as _gt
            eff = _gt.effects_for(self.root_cfg, self.symbol, self.strategy.name)
            n_on = sum(1 for e in eff.values() if e != _gt.EFFECT_NONE)
            if "kapuk" in secs:
                _txt = _t("idlg.n_active", n=n_on) if n_on else _t("idlg3.egyik_sem_aktiv")
                # ⚠ Az ELTÉRÉS a becsukott fejlécen is látszik: különben egy
                # feltáró beállítás (pl. „mérjük meg a lendület-kaput") némán
                # ott maradna, és a backtest hetekig mást mérne, mint az él.
                _d = _gt.backtest_differs(self.root_cfg, self.symbol,
                                          self.strategy.name)
                if _d:
                    _txt += _t("idlg.gates_differ", n=len(_d))
                secs["kapuk"].set_summary(_txt)
        except Exception:
            pass
        try:
            hrs = sorted(int(h) for h, on in (self._hour_on or {}).items() if on)
            if "orak" in secs:
                if len(hrs) == 24 or not hrs:
                    secs["orak"].set_summary(_t("idlg3.mind_a_24_ora") if hrs else _t("idlg3.egy_ora_sincs_engedve"))
                else:
                    secs["orak"].set_summary(
                        _t("idlg.hours_line", first=f"{hrs[0]:02d}", last=f"{hrs[-1]:02d}", n=len(hrs)))
        except Exception:
            pass
        try:
            rows = [dict(r, skipped=not self._skip_vars[r["key"]].get())
                    for r in (self._opt_rows or []) if r["key"] in self._skip_vars]
            tuned = [r for r in rows if not r["skipped"]]
            if "parameterek" in secs:
                secs["parameterek"].set_summary(
                    _t("idlg.tuned_of", tuned=len(tuned), total=len(self._opt_rows))
                    if self._opt_rows else "")
        except Exception:
            pass
        # ── FUTTATÁS: mi fog történni, ha most megnyomod ───────────────────
        try:
            if "futtatas" in secs:
                from core import opt_plan as _op
                rows = [dict(r, skipped=not self._skip_vars[r["key"]].get())
                        for r in (self._opt_rows or []) if r["key"] in self._skip_vars]
                _rp = _op.run_plan(rows, int((getattr(self, "_opt_cfg_cache", None)
                                              or {}).get("max_trials", 500) or 500))
                _n = len(_rp["tuned"])
                secs["futtatas"].set_summary(
                    _t("idlg3.egyetlen_futas_backtest") if _n == 0 else
                    _t("idlg.tuned_runs", tuned=_n, runs=_rp["runs"]))
        except Exception:
            pass
        # ── EREDMÉNY: a legutóbbi futás egy sorban ─────────────────────────
        # ⚠ Becsukva ez az EGYETLEN jele annak, hogy egyáltalán futott már —
        # üres fejléccel a becsukott szakasz megkülönböztethetetlen volna attól,
        # amiben eredmény VAN.
        try:
            if "eredmeny" in secs:
                from dashboard import trade_list as _tl
                _rows = getattr(self, "_trade_rows", None)
                secs["eredmeny"].set_summary(
                    _tl.summary_line(_rows) if _rows else _t("idlg3.meg_nem_futott"))
        except Exception:
            pass
        try:
            if "kockazat" in secs:
                # ⚠ NEM elég a preset neve. A szakasz három FÜGGETLEN tengelyt
                # tartalmaz (preset · runner · építés) + két kapcsolót, és
                # becsukva eddig csak az elsőt lehetett látni — pont az volt a
                # kérdés, „mi van bekapcsolva", amit a becsukás nem szülhet újra.
                _bits = [self._rr_name.get()]
                _rn = getattr(self, "_runner_name", None)
                if _rn is not None and self._runner_frame.winfo_manager():
                    _bits.append(f"runner: {_rn.get()}")
                if getattr(self, "_cautious_var", None) is not None                         and self._cautious_var.get():
                    _bits.append(_t("idlg3.ovatos_meret"))
                if getattr(self, "_cc_var", None) is not None and self._cc_var.get():
                    _bits.append(f"cost-cut {self._cc_bars_var.get()}")
                _bm = getattr(self, "_build_mode_name", None)
                if _bm is not None and _bm.get() not in ("Ki", ""):
                    _bits.append(_t("idlg.build_mode", mode=_bm.get()))
                secs["kockazat"].set_summary(" · ".join(_bits))
        except Exception:
            pass

    # ── „Kapcsolat” lap — MT4 / MT5 ────────────────────────────────────────
    # A doksi kérése: az indikátorok kimásolása a megfelelő MetaTrader mappába,
    # backtest-generálás az AKTUÁLIS paraméterekkel, és leírás a működésről.
    #
    # ⚠ MIÉRT EZ A LAP LEGFONTOSABB RÉSZE AZ ÁLLAPOT, nem a gomb: a `.mq4`/`.mq5`
    # a repóban él, a terminál a SAJÁTJÁBÓL olvas. Ha a kettő eltér, a terminál
    # CSENDBEN a régit futtatja, és a javítást hiába keresed a képernyőn — pont
    # ez történt az MT4-es visszajátszás fejlesztésekor (kilenc verzió, mind néma
    # hiba). A lap ezért ELŐSZÖR megmondja, mi van kint, és csak utána kínál gombot.

    def _build_link_tab(self):
        page = self._shell.page("link")
        for w in page.winfo_children():
            w.destroy()
        from dashboard.tab_shell import TabShell
        # ⚠ A TabShell a KONSTRUKTORÁBAN megmutatja az első lapot, tehát a
        # visszahívás lefutna, mielőtt a `self._link_sub` létezne. Ezért előbb
        # LÉTREHOZZUK visszahívás nélkül, elmentjük, és csak utána kötjük be —
        # majd expliciten megmutatjuk az elsőt. (Ugyanez a csapda a fő héjnál is
        # elsült; lásd `_on_tab`.)
        # A fülek FENT: egy bal oldali fülsávon BELÜL egy másik bal oldali sáv
        # két függőleges oszlopot adna egymás mellett — elveszi a tartalom
        # helyét, és nehéz eldönteni, melyik szint melyik.
        sub = TabShell(page, ("MT4", "MT5"), notify_every_show=True,
                       side="top")
        self._link_sub = sub
        sub._on_show = self._build_link_pane
        sub.show("MT4")

    def _diag_viz(self):
        """Végigkérdezi, MIÉRT nem jön létre a chart-fájl.

        ⚠ Egy hiányzó fájl önmagában néma: a motor viz-írója öt ponton lép ki
        csendben, és kívülről mind ugyanúgy néz ki. Egy MÁSIK gépen ezt kitalálni
        reménytelen — ezért a program mondja meg."""
        lbl = getattr(self, "_viz_send_lbl", None)
        if lbl is None:
            return
        try:
            from trading.live_trader import viz_diagnose
            rows = viz_diagnose(self.symbol, self.root_cfg)
        except Exception as ex:
            lbl.config(text=_t("idlg.check_error", error=ex), fg=FG_RED)
            return
        bad = [t for ok, t in rows if not ok]
        _p = self._viz_diag_win if getattr(self, "_viz_diag_win", None) else None
        if _p is not None and _p.winfo_exists():
            _p.destroy()
        win = tk.Toplevel(self.popup)
        self._viz_diag_win = win
        win.title(_t("idlg.why_no_chart", symbol=self.symbol))
        win.configure(bg=BG)
        win.transient(self.popup)
        tk.Label(win, bg=BG, fg=(FG_RED if bad else FG_GREEN), font=self._hf,
                 anchor="w", text=(_t("idlg.constraints_bad", n=len(bad))
                                   if bad else _t("idlg3.minden_feltetel_rendben"))
                 ).pack(anchor="w", padx=12, pady=(10, 4))
        for ok, txt in rows:
            tk.Label(win, bg=BG, fg=(FG_GRAY if ok else FG_RED), font=self._sf,
                     anchor="w", justify="left", wraplength=760,
                     text=("   ✓  " if ok else "   ⚠  ") + txt
                     ).pack(anchor="w", padx=12)
        if not bad:
            tk.Label(win, bg=BG, fg=FG_GRAY_DIM, font=self._sf, anchor="w",
                     justify="left", wraplength=760, pady=6,
                     text=(_t("idlg3.minden_feltetel_teljesul_ilyenkor") + chr(0x201D) + _t("idlg3.gomb_azonnal_letrehozza_a"))
                     ).pack(anchor="w", padx=12)
        tk.Button(win, text=_t("btn.close"), bg=BTN_DIS_BG, fg=BTN_DIS_FG, relief="flat",
                  font=self._sf, command=win.destroy).pack(pady=10)

    def _send_viz(self):
        """A chart-fájl újrarajzolása a MOSTANI beállításokkal.

        ⚠ A VISSZAJELZÉS RÉSZLETES. Egy „kész" felirat itt keveset érne: ha 0
        objektum ment ki, vagy épp az egyik stratégia kimaradt (mert a rajza ki
        van kapcsolva), azt látni kell — különben a felhasználó a chartot nézné,
        és nem értené, miért nem változott."""
        lbl = getattr(self, "_viz_send_lbl", None)
        if lbl is None:
            return
        try:
            lbl.config(text=_t("idlg.rajzolas"), fg=FG_GRAY)
            lbl.update_idletasks()
            from trading.live_trader import render_symbol_viz
            r = render_symbol_viz(self.symbol, self.root_cfg)
        except Exception as ex:
            lbl.config(text=f"Hiba: {ex}", fg=FG_RED)
            return
        if r["errors"]:
            lbl.config(text=" · ".join(r["errors"])[:200], fg=FG_RED)
            return
        _who = ", ".join(f"{n} ({c})" for n, c in r["strategies"]) or "—"
        _txt = _t("idlg.sent", n=r["lines"], who=_who)
        if r["skipped"]:
            # ⚠ NEM néma kihagyás: a kikapcsolt rajzú stratégia hiánya különben
            # úgy nézne ki, mintha a küldés nem működne.
            _txt += _t("idlg.skipped_off", names=", ".join(r["skipped"]))
        lbl.config(text=_txt, fg=FG_GREEN)

    def _build_link_pane(self, name: str):
        from core import mt_deploy as _md
        pane = self._link_sub.page(name)
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

        # ── 1. MI VAN KINT ─────────────────────────────────────────────────
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
               missing=cnt.get(_md.ST_MISSING, 0)),
               _fg)
            # ⚠ Az ELAVULT a legfontosabb: ott MÁS fut, mint amit a repóban látsz.
            bad = [s for s in st if s["state"] == _md.ST_STALE]
            for s in bad:
                tk.Label(body, bg=BG, fg=FG_RED, font=self._sf, anchor="w",
                         justify="left", wraplength=820,
                         text=f"   ⚠ ELAVULT: {s['file']}  —  {s['target']}"
                         ).pack(anchor="w", padx=10)
            if bad:
                _n(_t("idlg2.az_elavult_fajlnal_a"),
                   FG_RED)
            for t in tgts:
                tk.Label(body, bg=BG, fg=FG_GRAY_DIM, font=self._sf, anchor="w",
                         text=f"   {t}").pack(anchor="w", padx=10)

        row = tk.Frame(body, bg=BG)
        row.pack(anchor="w", padx=10, pady=(6, 2))
        tk.Button(row, text=_t("idlg.kitelepites"), bg=BTN_PLAY_BG, fg=BTN_PLAY_FG,
                  relief="flat", font=self._sf,
                  command=lambda p=name: self._deploy_mql(p)).pack(side="left")
        # ⚠ NINCS „Fordítás" gomb: a MetaEditor parancssori fordítása egyetlen
        # dokumentált alakra sem működött (rc=0, semmi kimenet). Helyette a
        # F7 UTÁN ide lehet BEHOZNI a lefordítottat a repóba — így verziózva
        # tárolódik, és a következő kitelepítés már viheti is.
        tk.Button(row, text=_t("idlg.leforditott_beolvasasa"), bg=BTN_BT_BG, fg=BTN_BT_FG,
                  relief="flat", font=self._sf,
                  command=lambda p=name: self._capture_mql(p)).pack(side="left",
                                                                    padx=(6, 0))
        self._link_status = tk.Label(row, text="", bg=BG, fg=FG_GRAY,
                                     font=self._sf)
        self._link_status.pack(side="left", padx=(10, 0))

        # ── MELYIK FÁJL MICSODA ────────────────────────────────────────────
        # ── KÜLDÉS A CHARTHOZ (csak MT5 — ott van élő kapcsolat) ───────────
        # ⚠ A spec kérése: „ha beállítom a spread kaput, akkor rögtön reagálja le
        # a TBAND". A viz-fájlt eddig KIZÁRÓLAG a futó motor írta, a saját
        # ütemében: egy leállított páron egyáltalán nem lehetett megnézni, mit
        # csinálna a mostani beállításokkal, futó páron pedig várni kellett a
        # következő viz-körre.
        #
        # ⚠ ÉS A KÜLDÉS NEM MENTÉS — ahogy a spec külön kiköti. Ez csak KIRAJZOL:
        # a config/paraméterek attól még változatlanok maradnak.
        if name == _md.MT5:
            _h(_t("idlg.kuldes_a_charthoz"))
            _n(_t("idlg.redraw_tip", file=f"TFV_{self.symbol}.csv"))
            _n(_t("idlg2.a_kuldes_nem_mentes"), FG_GRAY_DIM)
            _srow = tk.Frame(body, bg=BG)
            _srow.pack(anchor="w", fill="x", padx=10, pady=(4, 0))
            tk.Button(_srow, text=_t("idlg.kuldes_a_charthoz"), bg=BTN_BT_BG, fg=BTN_BT_FG,
                      relief="flat", font=self._sf, cursor="hand2",
                      command=self._send_viz).pack(side="left")
            # ⚠ Ha a fájl NEM jön létre, a motor öt ponton lép ki csendben —
            # kívülről mind ugyanúgy néz ki (nincs ott a fájl). Ez a gomb
            # végigkérdezi a feltételeket, és megnevezi az elsőt, ami bukik.
            tk.Button(_srow, text=_t("idlg.miert_nincs_fajl"), bg=BG_HEADER, fg=FG_WHITE,
                      relief="flat", font=self._sf, cursor="hand2",
                      command=self._diag_viz).pack(side="left", padx=(6, 0))
            self._viz_send_lbl = tk.Label(_srow, text="", bg=BG, fg=FG_GRAY,
                                          font=self._sf, anchor="w",
                                          justify="left")
            self._viz_send_lbl.pack(side="left", padx=(10, 0), fill="x",
                                    expand=True)

        # A kérés: „nem látom, milyen fájlokat is szeretne odamásolni, és egy
        # rövid leírás sem ártana, hogy melyik mit csinál."
        _h(_t("idlg2.mit_telepit_ki"))
        cs = {c["file"]: c for c in _md.compiled_status(name)}
        for src in _md.sources(name):
            rovid, hasznalat = _md.describe(src)
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
            # A TÁROLT lefordított állapota — ha más forráshoz készült, az baj.
            _c = cs.get(src.name) or {}
            if _c.get("state") == _md.ST_OTHER_SOURCE:
                tk.Label(line, text=_t("idlg.a_tarolt_leforditott_mas"),
                         bg=BG, fg=FG_RED, font=self._sf, anchor="w").pack(side="left")
            elif _c.get("state") == _md.ST_MATCH:
                tk.Label(line, text=_t("idlg.leforditott_tarolva"), bg=BG, fg=FG_GREEN,
                         font=self._sf, anchor="w").pack(side="left")
        _n(_md.USAGE.get(name, ""), FG_GRAY)

        # ⚠ Nem fordítunk — és ezt nem szépítjük. A „kitelepítve" önmagában NEM
        # jelenti azt, hogy az új kód FUT: a régi .ex4/.ex5 addig érvényben marad.
        _n(_t("idlg2.a_kitelepites_a_forrast"), FG_YELLOW)

        # ── 2. AMIT INNEN INDÍTHATSZ ───────────────────────────────────────
        if name == "MT4":
            # ── A VISSZAJÁTSZÁS ITT, a lapon (nem külön ablakban) ───────────
            _h(_t("idlg2.visszajatszas_generalasa"))
            _n(_t("idlg2.a_parameter_lap_aktualis"))
            self._build_mt4_export(body)
        else:
            _h(_t("idlg2.elo_megjelenites"))
            _n(_t("idlg2.az_elo_motor_folyamatosan"))
            _n(_t("idlg2.a_kapuk_ablakban_allitod"), FG_GRAY_DIM)

    def _build_mt4_export(self, body):
        """A visszajátszás-export a LAPON — nem külön ablakban.

        ⚠ Az időszak MEGJEGYZŐDIK (pár+stratégia szintű), és van naptár-ikon.
        Külön ablakban a dátumot minden megnyitáskor újra be kellett gépelni, és
        a legutóbb használt hét sem látszott — pedig manuális teszteléskor
        pontosan ugyanarra a hétre akarsz visszatérni.
        """
        from datetime import date, timedelta
        # A megjegyzett beállítások ugyanabban a tárban, ahol a backtest-ablak
        # időszaka — pár+stratégia szintű, `mt4_` előtaggal elkülönítve.
        from core import backtest_prefs as _bp

        try:
            saved = _bp.get(self.symbol, self.strategy.name) or {}
        except Exception:
            saved = {}
        _to = date.today()
        _fr = _to - timedelta(days=12)
        self._mx_from = tk.StringVar(value=saved.get("mt4_from") or _fr.isoformat())
        self._mx_to = tk.StringVar(value=saved.get("mt4_to") or _to.isoformat())
        self._mx_trades = tk.BooleanVar(value=bool(saved.get("mt4_trades")))
        self._mx_gates = tk.BooleanVar(value=bool(saved.get("mt4_gates", True)))

        row = tk.Frame(body, bg=BG)
        row.pack(anchor="w", padx=10, pady=(6, 2))
        for lbl, var in ((_t("idlg3.tol"), self._mx_from), ("-ig", self._mx_to)):
            tk.Label(row, text=lbl, bg=BG, fg=FG_GRAY_DIM,
                     font=self._sf).pack(side="left", padx=(0, 3))
            e = tk.Entry(row, textvariable=var, width=11, bg=BG_HEADER,
                         fg=FG_WHITE, insertbackground=FG_WHITE, relief="flat",
                         font=self._sf)
            e.pack(side="left")
            tk.Button(row, text="📅", bg=BG_HEADER, fg=FG_WHITE, relief="flat",
                      font=self._sf, cursor="hand2",
                      command=lambda v=var, a=e: self._pick_date(v, a)
                      ).pack(side="left", padx=(2, 12))

        # ── MI KERÜLJÖN A CHARTRA ──────────────────────────────────────────
        # ⚠ A két beállítás KÉT KÜLÖNBÖZŐ dolgot ír a chartra, és korábban a
        # feliratuk ezt elmosta:
        #   • az első a BELÉPŐ-JELZÉSEK körét szűkíti (mit jelzett volna a
        #     stratégia, illetve ebből mi ment volna át a szűrőkön),
        #   • a második EXTRA réteg: a bot ténylegesen megnyitott pozíciói.
        # A „kapu" szó ráadásul foglalt (együttállás, spread, volatilitás), és a
        # jelölők NEM kapuk — belépési pontok. Ezért itt a szűrők NEVE szerepel.
        tk.Label(body, text=_t("idlg.mi_keruljon_a_chartra"), bg=BG, fg=FG_WHITE,
                 font=self._sf, anchor="w").pack(anchor="w", padx=10, pady=(6, 0))
        opt = tk.Frame(body, bg=BG)
        opt.pack(anchor="w", padx=10)
        tk.Checkbutton(opt, text=_t("idlg.belepo_jelzesek_csak_a"),
                       variable=self._mx_gates, bg=BG, fg=FG_WHITE,
                       selectcolor=BG_HEADER, activebackground=BG,
                       activeforeground=FG_WHITE, font=self._sf).pack(anchor="w")
        tk.Label(opt, bg=BG, fg=FG_GRAY_DIM, font=self._sf, anchor="w",
                 justify="left", wraplength=780,
                 text=(_t("idlg.kipipalva_azt_latod_amit"))).pack(anchor="w")
        tk.Checkbutton(opt, text=_t("idlg.az_eles_kotesek_is"),
                       variable=self._mx_trades, bg=BG, fg=FG_GRAY,
                       selectcolor=BG_HEADER, activebackground=BG,
                       activeforeground=FG_WHITE, font=self._sf).pack(anchor="w",
                                                                      pady=(4, 0))
        tk.Label(opt, bg=BG, fg=FG_GRAY_DIM, font=self._sf, anchor="w",
                 justify="left", wraplength=780,
                 text=(_t("idlg.ez_kulon_reteg_a"))).pack(anchor="w")

        brow = tk.Frame(body, bg=BG)
        brow.pack(anchor="w", padx=10, pady=(6, 2))
        self._mx_btn = tk.Button(brow, text="Export", bg=BTN_PLAY_BG,
                                 fg=BTN_PLAY_FG, relief="flat", font=self._sf,
                                 command=self._run_mt4_export)
        self._mx_btn.pack(side="left")
        self._mx_lbl = tk.Label(brow, text="", bg=BG, fg=FG_GRAY_DIM,
                                font=self._sf, justify="left", wraplength=620)
        self._mx_lbl.pack(side="left", padx=(10, 0))
        tk.Label(body, bg=BG, fg=FG_GRAY_DIM, font=self._sf, anchor="w",
                 justify="left", wraplength=820,
                 text=(_t("idlg.kapukkal_az_export_csak"))
                 ).pack(anchor="w", padx=10, pady=(2, 8))

    def _pick_date(self, var, anchor):
        """Naptár-ikon → dátumválasztó, a mező mellé kihorgonyozva."""
        from datetime import date
        from dashboard.date_picker import CalendarPopup
        try:
            cur = date.fromisoformat(var.get().strip())
        except (ValueError, AttributeError):
            cur = date.today()
        # ⚠ A visszahívás SZTRINGET kap (`YYYY-MM-DD`), nem `date`-et. Az első
        # változat `d.isoformat()`-ot hívott rajta — az `AttributeError`-t pedig
        # a popup elnyelte, tehát a kattintás NÉMÁN nem írt vissza semmit.
        CalendarPopup(self.popup, anchor=anchor, initial=cur, font=self._sf,
                      on_pick=lambda s: var.set(s))

    def _run_mt4_export(self):
        import threading
        from core import backtest_prefs as _bp

        t_from = self._mx_from.get().strip()
        t_to = self._mx_to.get().strip()
        # Az időszak MEGJEGYZŐDIK — a következő megnyitáskor ez jön vissza.
        try:
            _bp.save(self.symbol, self.strategy.name,
                     mt4_from=t_from, mt4_to=t_to,
                     mt4_trades=bool(self._mx_trades.get()),
                     mt4_gates=bool(self._mx_gates.get()))
        except Exception:
            pass
        self._mx_btn.config(state="disabled")
        self._mx_lbl.config(text="Export fut…", fg=FG_GRAY_DIM)
        _gates = bool(self._mx_gates.get())
        _trades = bool(self._mx_trades.get())
        q = __import__("queue").Queue()

        def _work():
            from tools.viz_export import export_window
            try:
                ok, msg = export_window(
                    self.symbol, t_from, t_to, strategy_name=self.strategy.name,
                    suffix="_BT", show_trades=_trades, cfg=self.root_cfg,
                    exec_gates=_gates, status=lambda m: q.put(("s", m)))
            except Exception as ex:
                ok, msg = False, f"Hiba: {ex}"
            q.put(("d", (ok, msg)))

        def _poll():
            import queue as _q
            done = False
            try:
                while True:
                    kind, val = q.get_nowait()
                    if kind == "s":
                        self._mx_lbl.config(text=str(val), fg=FG_GRAY_DIM)
                    else:
                        ok, msg = val
                        self._mx_lbl.config(text=msg,
                                            fg=(FG_GREEN if ok else FG_RED))
                        self._mx_btn.config(state="normal")
                        done = True
            except _q.Empty:
                pass
            except tk.TclError:
                return
            if not done:
                self.popup.after(150, _poll)

        threading.Thread(target=_work, daemon=True, name="MT4Export").start()
        self.popup.after(150, _poll)

    def _capture_mql(self, platform: str):
        """A terminálban LEFORDÍTOTT fájlok beemelése a repóba (F7 után).

        ⚠ A jegyzék a FORRÁS TARTALMÁNAK ujjlenyomatát tárolja, nem csak a
        `#property version`-t: az utóbbit kézzel írják, és két különböző forrás
        viselheti ugyanazt. Így ha később a forrás változik, a tárolt
        lefordítottról KIDERÜL, hogy már máshoz tartozik."""
        from core import mt_deploy as _md
        try:
            res = _md.capture_compiled(platform, _md.discover_roots())
        except Exception as ex:
            self._link_status.config(text=f"Hiba: {ex}", fg=FG_RED)
            return
        msg = _t("idlg.compiled_taken", n=len(res["taken"]))
        if res["missing"]:
            msg += (_t("idlg.compiled_missing", files=", ".join(res["missing"][:3]),
                       more=("…" if len(res["missing"]) > 3 else "")))
        self._link_status.config(
            text=msg[:170], fg=(FG_YELLOW if res["missing"] else FG_GREEN))
        try:
            self._build_link_pane(platform)
        except Exception:
            pass

    def _deploy_mql(self, platform: str):
        """A repó indikátorainak kimásolása MINDEN megtalált terminál-mappába."""
        from core import mt_deploy as _md
        try:
            res = _md.deploy(platform, _md.discover_roots())
        except Exception as ex:
            self._link_status.config(text=f"Hiba: {ex}", fg=FG_RED)
            return
        if res["errors"]:
            self._link_status.config(text=res["errors"][0][:110], fg=FG_RED)
            return
        self._link_status.config(
            text=(_t("idlg.deployed", n=len(res["copied"]), targets=res["targets"],
                  skipped=len(res["skipped"]))),
            fg=FG_GREEN)
        # A lap újraépül, hogy az állapot AZONNAL a valóságot mutassa.
        try:
            self._build_link_pane(platform)
        except Exception:
            pass

    # ── „Eredmények” lap — a trials CSV OLVASHATÓ formában ─────────────────
    # A doksi kérése: szűrhető, rendezhető tábla, típusos mezőkkel (DD = %), a
    # sorok színe az eredmény szerint, és ide költözik a CSV-gomb.

    def _build_results_tab(self):
        page = self._shell.page("trials")
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
            self.lbl_err.config(text=_t("idlg.table_error", error=ex),
                                fg=FG_RED)

    def _start_sweep(self):
        """A bepipált 1–2 paraméter kimerítő végigpróbálása háttérszálon."""
        import threading
        from core import opt_plan as _op
        from core import sweep as _sw

        if self._sw_stop is not None:            # fut → megszakítás
            self._sw_stop.set()
            self._plan_btn.config(text=_t("bt.cancelling"), state="disabled")
            return

        rows = [dict(r, skipped=not self._skip_vars[r["key"]].get())
                for r in self._opt_rows if r["key"] in self._skip_vars]
        plan = _op.run_plan(rows, 0)
        if plan["kind"] not in (_op.KIND_SWEEP, _op.KIND_GRID):
            # ⚠ Nem csendes tétlenség: megmondjuk, MIT kell tenni.
            self._sw_status.config(
                text=(_t("idlg.sweep_needs_dims", n=len(plan["tuned"]))), fg=FG_YELLOW)
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
            self._sw_status.config(text=_t("idlg.nincs_letoltott_elozmeny"), fg=FG_RED)
            return

        axes, combos = _sw.combos(rows, self._opt_cfg_cache)
        self._sw_axes, self._sw_rows = axes, []
        self._sw_stop = threading.Event()
        self._plan_btn.config(text=_t("idlg.leallitas"))
        self._prog_show(0.0, _t("idlg.runs_progress", done=0, total=len(combos)))
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
                    self._sw_status.config(text=_t("idlg.runs_progress_dots", done=msg[1], total=msg[2]),
                                           fg=FG_GRAY)
                    _tot = max(1, int(msg[2]))
                    self._prog_show(100.0 * int(msg[1]) / _tot,
                                    _t("idlg.runs_progress", done=msg[1], total=msg[2]))
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
        self._prog_hide()
        try:
            self._plan_btn.config(text=_t("idlg.inditas"), state="normal")
        except tk.TclError:
            return
        if err:
            self._sw_status.config(text=err, fg=FG_RED)
            return
        self._sw_rows = rows
        self._sw_status.config(text=_t("idlg.runs_done", n=len(rows)), fg=FG_GREEN)
        # ⚠ A RAJZ LEGYEN LÁTHATÓ, akkor is, ha közben bármi átrendezte a
        # szakaszt. Az `pack` ismételve ártalmatlan (a Tk nem duplikál).
        try:
            self._sw_canvas.pack(fill="x", pady=(4, 2))
            self._sw_best.pack(anchor="w", pady=(0, 8))
        except tk.TclError:
            pass
        self._redraw_sweep()

    def _redraw_sweep(self):
        from core import sweep as _sw
        from dashboard import sweep_view as _sv
        from dashboard import theme as _th
        if not getattr(self, "_sw_rows", None):
            return
        if not self._sw_axes:
            # ⚠ Volt eredmény, de nincs tengely — a rajz némán elmaradna, és a
            # felhasználó egy „kész" feliratot látna üres hely fölött.
            try:
                self._sw_status.config(
                    text=(_t("idlg.runs_done_axes", n=len(self._sw_rows))),
                    fg=FG_YELLOW)
            except tk.TclError:
                pass
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
                text=(_t("idlg.sweep_best", metric=metric, where=where, trades=b["trades"],
                      pnl=_fmtnum(f"{b['total_pnl']:+.0f}"),
                      pf=_fmtnum(f"{b['profit_factor']:.2f}"),
                      dd=_fmtnum(f"{b['max_drawdown'] * 100:.1f}"))))

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
            text=_t("idlg.a_pont_parameterei_betoltve"),
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
        space_txt = (_t("idlg3.gyakorlatilag_vegtelen") if space >= 10 ** 18
                     else f"{space:,}".replace(",", " "))
        # ⚠ Ez a legfontosabb szám az egész lapon: az optuna NEM járja be a
        # teret, hanem mintavételez. A trial-szám önmagában semmit nem mond —
        # csak a térhez viszonyítva. Enélkül könnyű azt hinni, hogy 500 trial
        # „átnézte” a lehetőségeket.
        try:
            self._space_lbl.config(
                text=(_t("idlg.space_note", tuned=len(tuned), signal=n_sig,
                      exec=len(tuned) - n_sig, space=space_txt, trials=trials)))
            # A FUTÁS TÍPUSA a hangolt dimenziók számából adódik — ugyanaz a
            # gépezet 0, 1, 2 vagy több paraméterrel mást JELENT. A levezetés a
            # `core.opt_plan.run_plan`-ban van (tesztelhető, és a jövőbeli
            # Futtatás lap ugyanazt hívja majd) — itt csak megjelenítjük.
            rp = _op.run_plan(rows, trials)
            # ⚠ A KIÍRT TERV a TÉNYLEGES módot tükrözze. Backtest módban a pipák
            # NEM számítanak — ha ilyenkor is az optimalizálás tervét írnánk ki,
            # a felület mást ígérne, mint ami elindul.
            _mode = self._effective_mode()
            _bt_txt = (_t("idlg3.egyetlen_futas_a_mostani"))
            self._tuned_lbl.config(
                text=(_bt_txt if _mode == self.RUN_BACKTEST else
                      rp["text"] + chr(10) + "Hangolva: "
                      + (", ".join(rp["tuned"]) or "—")))
            try:
                self._plan_short.config(
                    text=(_bt_txt if _mode == self.RUN_BACKTEST else rp["text"]))
                # ⚠ Ha nincs mit hangolni, a „Hangolás" ÜRES ÍGÉRET — letiltjuk,
                # és a választó magától Backtestre áll (nem némán: a felirat is
                # megmondja, miért).
                _has = bool(rp["tuned"])
                _rb = getattr(self, "_rb_planned", None)
                if _rb is not None:
                    _rb.config(state=("normal" if _has else "disabled"),
                               text=(_t("idlg3.hangolas_a_bepipalt_parameterek")
                                     if _has else
                                     _t("idlg3.hangolas_nincs_bepipalt_parameter")))
            except (tk.TclError, AttributeError):
                pass
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
                    text=_t("idlg.not_a_number", key=key, field=field),
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
            self._range_err.config(text=_t("idlg.range_reverted", key=key, error=err),
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
                text=_t("idlg.range_saved", key=key, min=f"{spec['min']:g}",
                     max=f"{spec['max']:g}", step=f"{spec['step']:g}", n=n), fg=FG_GREEN)
            self._refresh_opt_space()
        else:
            self._range_err.config(text=_t("idlg.range_save_failed", key=key), fg=FG_RED)

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
            self.lbl_err.config(text=_t("save.error", error=ex), fg=FG_RED)
            return
        self._refresh_opt_space()
        # ⚠ A pipa átállítása MEGVÁLTOZTATJA a mód-konfliktust (pl. Backtest
        # módban most lett először bepipálva valami) — a figyelmeztetés nem
        # maradhat elavult.
        self._refresh_run_mode_ui()
        self._refresh_section_summaries()

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
        self._src_lbl.config(text=(_t("idlg.source", source=source) if source else ""))
        if not summary or summary.get("trades", 0) == 0:
            self._grade_lbl.config(text=_t("idlg.minosites"), fg=FG_GRAY)
            if summary is not None and summary.get("trades", 0) == 0:
                tk.Label(self._metrics_frame, text=_t("bt.no_trades"),
                         bg=BG, fg=FG_YELLOW, font=self._sf).pack(side="left")
            return
        gtxt, gcol, greason = self.strategy.grade(summary, self.cfg)
        self._grade_lbl.config(
            text=_t("bt.grade", grade=gtxt) + (f"   ({greason})" if greason else ""),
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
                None, _t("idlg2.parameter_modositva_a_mentes"))

    # ── Sorszám-választó (minőségi rangsor) ─────────────────────────────────
    def _build_rank_selector(self, popup):
        best, worst = self._ranks[0], self._ranks[-1]
        opt_ranks = [r for r in self._ranks if r < _MANUAL_RANK_BASE]
        man_ranks = [r for r in self._ranks if r >= _MANUAL_RANK_BASE]

        bar = tk.Frame(popup, bg=BG)
        bar.pack(anchor="w", padx=10, pady=(2, 0))
        tk.Label(bar, text=_t("idlg.sorszam_minoseg_1_legjobb"), bg=BG, fg=FG_GRAY,
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
        tk.Button(bar, text=_t("range.load"), bg=BG_HEADER, fg=FG_WHITE, relief="flat",
                  font=self._sf, cursor="hand2",
                  command=self._load_current_rank).pack(side="left", padx=(4, 0))

        avail = _t("idlg.rank_available", max=max(opt_ranks)) if opt_ranks else _t("idlg3.elerheto")
        if man_ranks:
            avail += _t("idlg.rank_manual", ranks=_fmt_ranges(man_ranks))
        tk.Label(bar, text=avail, bg=BG, fg=FG_GRAY_DIM,
                 font=self._sf).pack(side="left", padx=(8, 0))

        # Az adott sorszámhoz tartozó metrikák
        self.lbl_rank = tk.Label(popup, text=_t("idlg.valassz_sorszamot_a_betolteshez"),
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
            self.lbl_rank.config(text=_t("idlg.ervenytelen_sorszam"), fg=FG_RED)
            return
        self._load_rank(int(r))

    def _load_rank(self, rank: int):
        row = self._rank_rows.get(rank)
        if row is None:
            self.lbl_rank.config(
                text=_t("idlg.rank_missing", rank=rank, lo=self._ranks[0],
                     hi=self._ranks[-1]), fg=FG_RED)
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
            self._render_metrics(None, _t("idlg.rank_no_metric", rank=rank))
            self.lbl_rank.config(
                text=_t("idlg.rank_loaded_short", rank=rank)
                     + (f" ({note})" if note else "")
                     + _t("idlg.rank_no_metric_suffix"), fg=FG_GRAY)
        else:
            src = _t("idlg.rank_row", rank=rank) + (f", {note}" if note else "")
            self._render_metrics(summ, src)
            self.lbl_rank.config(text=_t("idlg.rank_loaded", rank=rank), fg=FG_GRAY)

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

        tk.Label(popup, text=_t("idlg.kereskedesi_orak_szerver_chart"),
                 bg=BG, fg=FG_GRAY, font=self._sf).pack(anchor="w", padx=10, pady=(8, 0))

        hours_frame = tk.Frame(popup, bg=BG)
        hours_frame.pack(fill="x", padx=10, pady=(2, 2))
        # ⚠ TELJES SZÉLESSÉG: a 24 óra EGYENLŐEN osztozik a rendelkezésre álló
        # helyen (`uniform` — enélkül a P&L-számot tartalmazó oszlopok szélesebbek
        # lennének, és a rács „lélegezne" a számok hosszától). Így az ablakot
        # szélesítve nagyobbak a kattintható célpontok, nem marad üres jobb oldal.
        for _h in range(24):
            hours_frame.grid_columnconfigure(_h, weight=1, uniform="ora")
        hour_on = {h: (h in _checked0) for h in range(24)}
        hour_btns = {}
        self._hour_btns = hour_btns

        def _paint(h):
            btn = hour_btns[h]
            if hour_on[h]:
                btn.config(bg=FG_GREEN, fg=FG_ON_ACCENT)     # BE — zöld
            else:
                btn.config(bg=BG_HEADER, fg=FG_GRAY_DIM)  # KI — sötét

        def _toggle(h):
            hour_on[h] = not hour_on[h]
            _paint(h)
            self._refresh_section_summaries()

        for h in range(24):
            colf = tk.Frame(hours_frame, bg=BG)
            colf.grid(row=0, column=h, padx=1, sticky="nsew")
            # A `width` KIKERÜLT: fix karakter-szélességgel a címke nem nyúlna a
            # rendelkezésre álló helyre, és a rács szélesedne ugyan, a gombok nem.
            btn = tk.Label(colf, text=f"{h:02d}", padx=2, pady=3,
                           font=_theme.fonts()["small_bold"], cursor="hand2")
            btn.pack(fill="x")
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
        tk.Label(box, text=_t("idlg.gate_question", strategy=self.strategy.name),
                 bg=BG, fg=FG_GRAY, font=self._sf, anchor="w").pack(anchor="w",
                                                                    pady=(2, 4))
        self._gate_vars = {}
        self._gate_src_lbl = {}
        self._gate_bt_vars = {}
        self._gate_bt_cb = {}
        grid = tk.Frame(box, bg=BG)
        grid.pack(fill="x")
        # ── OSZLOP-FEJLÉC: név · állapot (élesben) · backtest ───────────────
        # ⚠ A korábbi harmadik oszlop („→ hatás (forrás)") KIKERÜLT: szó szerint
        # ugyanazt mondta, ami a legördülőben állt. Egyetlen dolgot vitt, amit a
        # legördülő NEM: ha a kapu a Beállításokban globálisan ki van kapcsolva.
        # Az megmaradt — de csak akkor jelenik meg, amikor tényleg ez a helyzet.
        for _c, _hdr in ((0, _t("idlg3.nev")), (1, _t("idlg3.allapot_elesben")), (2, "backtest")):
            tk.Label(grid, text=_hdr, bg=BG, fg=FG_GRAY_DIM, font=self._sf,
                     anchor=("center" if _c == 2 else "w")).grid(
                         row=0, column=_c, sticky="we", pady=(0, 2),
                         padx=(0 if _c == 0 else 6, 0))
        for i, g in enumerate(_g.REGISTRY, start=1):
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

            # ── A BACKTEST-PIPA: modellezze-e a mérés ezt a kaput? ──────────
            # ⚠ Ezzel mérhető meg, mennyit visz el egy kapu: kipipálod,
            # futtatsz, kiveszed, futtatsz — a különbség a kapué.
            bv = tk.BooleanVar(value=_g.backtest_enabled(
                self.root_cfg, self.symbol, self.strategy.name, key))
            self._gate_bt_vars[key] = bv
            cb = tk.Checkbutton(grid, variable=bv, bg=BG, fg=FG_WHITE,
                                selectcolor=BG_HEADER, activebackground=BG,
                                activeforeground=FG_WHITE,
                                command=lambda k=key: self._on_gate_bt_change(k))
            cb.grid(row=i, column=2, padx=(6, 0))
            self._gate_bt_cb[key] = cb
            lbl = tk.Label(grid, text="", bg=BG, fg=FG_GRAY_DIM, font=self._sf,
                           anchor="w")
            lbl.grid(row=i, column=3, sticky="w", padx=(6, 0))
            self._gate_vars[key] = var
            self._gate_src_lbl[key] = lbl
            self._refresh_gate_source(key)
            self._refresh_gate_bt(key)
        self._refresh_section_summaries()
        tk.Label(box, text=_t("idlg.a_csak_jelzes_nem"),
                 bg=BG, fg=FG_GRAY_DIM, font=self._sf, anchor="w").pack(
                 anchor="w", pady=(4, 0))

    def _gate_choices(self, key: str) -> list:
        """A választható értékek: a három hatás + az „Örökölt (…)" visszaállítás.

        Az örökölt opció KIÍRJA, mi lenne az érték felülírás nélkül — így nem
        kell kitalálni, mit kapsz vissza, ha visszavonod a beállítást."""
        inh, _src = self._g.inherited_effect(self.root_cfg, self.symbol,
                                             self.strategy.name, key)
        return [_t("gate.effect.inherited", effect=self._g.EFFECT_LABEL[inh])] + \
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
        """A sor VÉGI megjegyzés — csak akkor szól, ha van MIT mondania.

        ⚠ Korábban itt a „→ hatás (forrás)" állt, ami szó szerint ugyanaz volt,
        mint a legördülő felirata („Örökölt (akadályozza a beszállást)").

        Amit MOND, az három dolog, ebben a fontossági sorrendben:
          1. ELTÉR-e a mérés az élestől — ez a legfontosabb, mert egy feltáró
             beállítás különben hetekig ott maradna, és a backtest csendben mást
             mérne, mint ami történik;
          2. hogy a kapu CSAK KIJELZÉS (a szűrés a paraméterekben van);
          3. hogy a Beállításokban GLOBÁLISAN ki van kapcsolva — mert a legördülő
             olyankor „Ki"-t mutat, mintha te állítottad volna úgy.
        """
        lbl = self._gate_src_lbl.get(key)
        if lbl is None:
            return
        eff, src = self._g.effect_with_source(self.root_cfg, self.symbol,
                                              self.strategy.name, key)
        if self._g.is_display_only(key):
            lbl.config(text=_t("idlg.csak_kijelzes_a_szures"),
                       fg=FG_GRAY_DIM)
            return
        bt = self._g.effects_for(self.root_cfg, self.symbol, self.strategy.name,
                                 for_backtest=True)[key]
        if bt != eff:
            lbl.config(fg=FG_YELLOW, text=(
                _t("idlg3.a_meresbol_kiveve_elesben")
                if bt == self._g.EFFECT_NONE else
                _t("idlg3.csak_a_meresben_elesben")))
        elif src == self._g.SRC_MASTER_OFF:
            lbl.config(text=_t("idlg.a_beallitasokban_kikapcsolva"), fg=FG_YELLOW)
        else:
            lbl.config(text="")

    def _refresh_gate_bt(self, key: str):
        """A backtest-pipa ÁLLAPOTA és értéke.

        ⚠ A pipa FÜGGETLEN az éles hatástól — mindkét irányban. Egy élesben
        kikapcsolt kapu is bekapcsolható a mérésre: a „mi lenne, ha
        bekapcsolnám?" épp a backtest dolga, és a tiltása elvette volna a
        legfontosabb kérdést — megéri-e egyáltalán bekapcsolni. Az ELTÉRÉST a
        sor végi megjegyzés mondja ki, hogy ne maradjon néma.

        Az EGYETLEN kivétel a CSAK KIJELZÉS kapu, és az nem házirend, hanem
        tény: a `decide` átugorja, tehát a bepipálás semmit nem tenne."""
        cb = (getattr(self, "_gate_bt_cb", None) or {}).get(key)
        var = (getattr(self, "_gate_bt_vars", None) or {}).get(key)
        if cb is None or var is None:
            return
        usable = not self._g.is_display_only(key)
        var.set(usable and self._g.backtest_enabled(
            self.root_cfg, self.symbol, self.strategy.name, key))
        try:
            cb.config(state=("normal" if usable else "disabled"))
        except tk.TclError:
            pass

    def _on_gate_bt_change(self, key: str):
        """A backtest-pipa AZONNAL a config.json-ba megy.

        ⚠ Ez NEM az éles hatást állítja: az „állapot" oszlop marad, ami volt. Ez
        csak azt mondja meg, hogy a MÉRÉS modellezze-e a kaput — épp ezzel
        mérhető, mennyit visz el (kipipálod, futtatsz, kiveszed, futtatsz)."""
        val = bool(self._gate_bt_vars[key].get())
        self._g.set_backtest(self.root_cfg, self.symbol, self.strategy.name,
                             key, val)
        try:
            self._save_main_config()
        except Exception as ex:
            self.lbl_err.config(text=_t("save.error", error=ex), fg=FG_RED)
            return
        self._refresh_gate_source(key)   # az ELTÉRÉS azonnal látszódjék
        self._refresh_section_summaries()
        self._invalidate_bt()      # a korábbi backtest MÁS kapukkal futott

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
        # ⚠ Az „Örökölt" sort a LISTA ELSŐ ELEMÉHEZ hasonlítjuk, nem a felirat
        # előtagjához. A `startswith("Örökölt")` a fordítás után SOSEM talált
        # volna: a felülírás visszavonása helyett a kód a hatás-ágra futott
        # volna, és egy `None`-nál csendben visszatér — a kapu beállítása
        # látszólag nem történik meg.
        if txt == self._gate_choices(key)[0]:
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
            self.lbl_err.config(text=_t("idlg.gate_save_error", error=ex), fg=FG_RED)
            return
        self._refresh_gate_bt(key)
        self._refresh_gate_source(key)   # a hatás váltása ELTÉRÉST szülhet
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
                self.lbl_err.config(text=_t("bt.bad_value", key=k, value=repr(v)))
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
            self.lbl_err.config(text=_t("save.error", error=ex))
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
            self.lbl_err.config(text=_t("idlg.note_save_error", error=ex), fg=FG_RED)

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
            self.lbl_err.config(text=_t("idlg.hours_save_error", error=ex), fg=FG_RED)
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
                self.lbl_err.config(text=_t("idlg.csv_save_error", error=ex), fg=FG_RED)
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
                self.lbl_err.config(text=_t("idlg.exec_save_error", error=ex), fg=FG_RED)
                return
        strat_params = {k: v for k, v in params.items() if k not in _EXEC_KEYS}
        if not self._write_json(strat_params, extra=extra):
            return
        # ⚠ A MENTÉS UTÁN A CHART IS FRISSÜL. A spec külön kiköti: „a küldés nem
        # egyenlő a mentéssel… persze a mentéskor is le kell futnia". Enélkül a
        # mentett érték és a charton látszó rajz szétcsúszna, amíg a motor
        # következő viz-köre meg nem érkezik — leállított páron pedig sosem.
        # CSENDES ág: itt nincs hova visszajelezni (az ablak bezárul), és egy
        # sikertelen rajzolás nem akadályozhatja meg a MENTÉST.
        try:
            from trading.live_trader import render_symbol_viz
            _r = render_symbol_viz(self.symbol, self.root_cfg)
            if _r.get("errors"):
                import logging as _lg
                _lg.getLogger(__name__).info(
                    "%s — mentés utáni chart-küldés: %s",
                    self.symbol, "; ".join(_r["errors"]))
        except Exception as _ex:
            import logging as _lg
            _lg.getLogger(__name__).info(
                "%s — mentés utáni chart-küldés nem sikerült: %s",
                self.symbol, _ex)
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
            self.lbl_err.config(text=_t("idlg.nincs_trials_csv_futtass"))
            return
        try:
            import os
            os.startfile(str(self.trials_csv))   # Windows: alap app (Excel)
        except Exception as ex:
            self.lbl_err.config(text=_t("bt.open_error", error=ex))

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
        self._refresh_section_summaries()
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
        # ⚠ HATÁROK KULCSONKÉNT. A hányadok ARÁNYOK (0..1): egy beírt „75" nem
        # 75%-ot jelentene, hanem 75-szörös méretet — a motor a lot ennyiszeresét
        # zárná. Az elutasított érték nem tűnik el némán: visszaírjuk a
        # ténylegesen hatót, tehát a mező sosem mutat mást, mint amivel fut.
        v = _num(self._bt_vars[key].get())
        _ok = v is not None
        if _ok and key in ("halving_fraction", "shield_fraction"):
            _ok = 0.0 < v < 1.0
        elif _ok and key == "trigger_R":
            _ok = v > 0.0
        elif _ok:
            _ok = v >= 0.0
        if _ok:
            self._rrs._set(self.symbol, **{key: float(v)})
        cur = self._rrs.spec_for(self.symbol).get(key, 0)
        self._bt_vars[key].set(f"{float(cur):g}")
        self._warn_trigger_vs_tp()      # a trigger/TP viszony változhatott

    def _on_cautious_change(self):
        self._rrs.set_cautious(self.symbol, bool(self._cautious_var.get()))
        self._refresh_section_summaries()

    def _on_cost_cut_change(self):
        self._rrs.set_cost_cut(self.symbol, bool(self._cc_var.get()))
        self._refresh_section_summaries()

    def _on_cost_cut_bars_save(self, _event=None):
        raw = self._cc_bars_var.get().strip().replace(",", ".")
        try:
            v = int(float(raw))
        except ValueError:
            return
        if v > 0:
            self._rrs.set_cost_cut_bars(self.symbol, v)
            self._refresh_section_summaries()

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
        _act = _rr.be_trail_active(preset, runner) | _rr.partial_active(preset)
        for _k, _f in self._bt_frames.items():
            _f.pack_forget()
        for _k in tuple(_rr.BE_TRAIL_KEYS) + tuple(_rr.PARTIAL_KEYS):
            if _k in _act:
                self._bt_frames[_k].pack(side="left", padx=(0, 10))
        self._warn_trigger_vs_tp()
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
        self._rr_summary_changed()

    def _warn_trigger_vs_tp(self):
        """⚠ „A Pajzs be van kapcsolva, mégsem csinál semmit."

        Ha a részleges zárás triggere (`trigger_R`) NEM ESIK a célár ELÉ, a
        célár ér oda előbb, és a TELJES pozíciót zárja — a Pajzs/Felező tehát
        néma marad. Élesben pontosan ez történt: `tp_rr_ratio` 1,0, `trigger_R`
        1,0, és minden kötés ±1,00R-en, teljes zárással végződött.

        A számokat nem hasonlítjuk, ha a preset nem részleges zárású — ott a
        `trigger_R`-nek nincs szerepe, és egy felirat csak zavarna."""
        lbl = getattr(self, "_trig_warn", None)
        if lbl is None:
            return
        from core import risk_reduction as _rr
        preset = self._preset_from_name(self._rr_name.get())
        if "trigger_R" not in _rr.partial_active(preset):
            try:
                lbl.config(text="")
            except tk.TclError:
                pass
            return
        _trig = _num((self._bt_vars.get("trigger_R").get()
                      if self._bt_vars.get("trigger_R") is not None else ""))
        _tp = None
        _e = (getattr(self, "entries", None) or {}).get("tp_rr_ratio")
        if _e is not None:
            _tp = _num(_e.get())
        txt = ""
        if _trig is not None and _tp is not None and _trig >= _tp:
            txt = (_t("idlg.partial_never", trigger=f"{_trig:g}", tp=f"{_tp:g}",
                   suggest=f"{max(0.1, _tp * 0.8):g}"))
        try:
            lbl.config(text=txt)
        except tk.TclError:
            pass

    def _rr_summary_changed(self):
        """A kockázat-vezérlők LÁTHATÓSÁGA befolyásolja az összegzést (a runner
        csak Felező/Pajzsnál szerepelhet benne), ezért a láthatóság-frissítés
        UTÁN kell újraszámolni — nem előtte."""
        self._refresh_section_summaries()

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
        """A „Backtest" a Paraméter lap FUTTATÁS szakaszához visz.

        ⚠ Nem nyit új ablakot: a doksi panasza épp az volt, hogy ugyanaz a
        paraméter két külön kinézetben jelenik meg. A megszokott hívási pont
        viszont ne tűnjön el — csak vezessen a helyére."""
        try:
            self._shell.show("params")
            self._sections["futtatas"].set_open(True)
            self._maybe_build_run()
            return
        except Exception:
            pass          # ha valamiért nincs szakasz, marad a régi, ablakos út
        params = self._collect_params()
        if params is None:
            return
        pair_cfg = self.cfg.get("pairs", {}).get(self.symbol)
        if not isinstance(pair_cfg, dict):
            self.lbl_bt.config(text=_t("idlg.nincs_par_config_ehhez"),
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
            self._render_metrics(summary, _t("idlg2.friss_backtest_a_backtest"))
        else:
            self._bt_summary = None
            self._render_metrics(
                None, _t("idlg2.parameterek_a_backtest_ablakbol"))

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
            self.lbl_bt.config(text=_t("idlg.nincs_par_config_ehhez"), fg=FG_RED)
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
        _saving = _t("idlg3.mentes_a_vegen") if self._save_after_bt else ""
        self.lbl_bt.config(text=_t("idlg.bt_running", params=_pname, saving=_saving),
                           fg=FG_GRAY)

        def work():
            summary, err = None, None
            try:
                from trading.backtest import load_data_ensure, run_pair
                # Hiányzó előzmény → MAGÁTÓL letölti (frissen felvett instrumentum)
                df15, df1, err = load_data_ensure(
                    self.symbol, self.cfg,
                    status=lambda m: self._bt_status(_t("idlg.history_msg", msg=m)))
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
        _names = {"shield": "Pajzs", "halving": _t("tech.halving"), "risky": "Risky",
                  "fibo": "Fibo", "thirds": "Harmados"}
        tech_s = (", ".join(f"{_names.get(k, k)}×{v}" for k, v in tech.items())) if tech else ""
        self._bt_summary = summary or {"trades": 0}
        self._bt_from_saved = False   # ez valódi friss backtest
        self._render_metrics(self._bt_summary, "friss backtest")
        self.lbl_bt.config(
            text=(_t("idlg.tech_used", tech=tech_s) if tech_s else ""),
            fg=FG_GRAY_DIM)
        if pending:
            # Auto-mentés folytatása: a friss eredménnyel most már perzisztálunk.
            params = self._collect_params()
            if params is not None:
                dup = self._find_matching_rank(params) if self._rank_rows else None
                self._persist(params, dup)

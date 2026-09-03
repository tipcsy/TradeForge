"""
Backtest-ablak (B3) — a Stratégia Paraméterek ablak „Backtest" gombja nyitja.

Szabványos, önálló ablak egy paraméterkészlet backtesteléséhez:
  • a backtestelt PARAMÉTEREK láthatók és SZERKESZTHETŐK (feltáró) — „Vissza"
    visszaállítja a megnyitáskori értékeket, „Mentés a Paraméterekhez" visszaírja
    az aktuális készletet a szülő (Stratégia Paraméterek) űrlapjába,
  • állítható időszak (kezdő/záró dátum; üresen = a teljes letöltött history),
  • választható óra-kapu: „Csak a kereskedési órákban" (trade_hours, mint élesben) —
    ekkor a `no_trade_resets_signal` param is életbe lép (a szünet reseteli az M15-öt),
  • állítható Kockázatcsökkentés + Óvatos méret + Runner + Exit (indikátor+paraméterek),
    ALATTA az Építés (Ki/Kézi/Auto + méret-faktor + trigger) — mind FELTÁRÓ
    (nem ment, nem érinti a live-ot),
  • a TÖRZS görgethető, a gombsor (Backtest indítása / Mentés a Paraméterekhez /
    Bezárás) az ablak alján RÖGZÍTVE — sok paraméternél is elérhető,
  • progress bar + százalék a futás közben,
  • élő kijelzés: aktuális szimulált idő, egyenleg, nyitott/lezárt kötések,
    és a ténylegesen alkalmazott kockázati technikák (Felező/Pajzs/Risky) száma,
  • a végén: minősítés + metrikák (Trade·Win·MaxDD·P&L·PF), a POZÍCIÓÉPÍTÉS
    hozadéka (hány ráépítés hány kötésen + R/$; tételesen az „Építés CSV"
    gombbal) és egy egyszerű egyenleg-görbe (sparkline) — az ELŐZŐ / EREDETI
    futás halványan összevethető.

A futás a `trading.backtest.run_pair`-t hívja külön szálon; a `progress_callback`
a fő (UI) szálra marshalol (`after(0, …)`) — az UI SOHA nem blokkol. A végeredményt
egy opcionális `on_result(summary)` visszahívással adja a hívó ablaknak (így a
metrika-sáv és a Mentés is látja a friss eredményt).
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

import pandas as pd

from core.i18n import t as _t
from dashboard.theme import (
    BG, BG_HEADER,
    FG_WHITE, FG_GREEN, FG_RED, FG_YELLOW, FG_GRAY, FG_GRAY_DIM, FG_BLUE,
    BTN_PLAY_BG, BTN_PLAY_FG, BTN_BT_BG, BTN_BT_FG, BTN_DIS_BG, BTN_DIS_FG,
    color as sem_color,
)
from dashboard.instrument_dialog import _attach_tooltip, _style_om, _scrollable
from dashboard.date_picker import CalendarPopup
from core.quality import metric_colors
from core.params_store import resolve_trade_hours
from core import rr_state as _rrs
from core import risk_reduction as _rrx
from core import build_state as _bst
from core import position_build as _pb
from core import backtest_prefs as _bprefs
from core.i18n import num as _fmtnum

# A technika-kulcsok emberi nevei (a rr_technique / progress tech dict-hez).
# ⚠ FÜGGVÉNY, nem modul-szintű tábla — lásd az `_exind_name()` melletti okot.
_TECH_KEYS = ("shield", "halving", "risky", "fibo", "thirds")


def _tech_name(key: str) -> str:
    return _t(f"tech.{key}") if key in _TECH_KEYS else str(key)

# A metrika-sáv egységes sorrendje (mint a Stratégia Paraméterek ablakban)
_METRIC_ORDER = [
    ("Trade ", lambda s: str(int(s.get("trades", 0))), None),
    ("Win ",   lambda s: f"{s.get('win_rate', 0) * 100:.0f}%", "win_rate"),
    ("MaxDD ", lambda s: f"{s.get('max_drawdown', 0) * 100:.1f}%", "max_drawdown"),
    ("P&L ",   lambda s: f"{s.get('total_pnl', 0):+.0f}$", "total_pnl"),
    ("PF ",    lambda s: (f"{s.get('profit_factor', 0):.2f}"
                          if s.get('profit_factor', 0) != float('inf') else "∞"),
     "profit_factor"),
]

# Az exit-indikátor emberi nevei + indikátor-függő SZERKESZTHETŐ paraméter-mezők
# (kulcs, rövid címke) — az instrumentum-ablakkal EGYEZŐEN (egy igazságforrás elv).
# ⚠ FÜGGVÉNY, nem modul-szintű szótár: a katalógus a nyelvvel változik, egy
# betöltéskor kiszámolt tábla pedig befagyna (a legördülő és a visszafejtése
# ugyanabból a hívásból dolgozik, tehát nem tudnak elcsúszni).
def _exind_name() -> dict:
    return {"supertrend": "Supertrend", "wpr": "WPR",
            "divergence": _t("exit.ind.divergence")}
_EXIT_PARAM_SPEC = {
    "supertrend": [("st_period", "Per"), ("st_multiplier", _t("exit.param.mult"))],
    "wpr":        [("wpr_period", "Per"), ("wpr_ma_period", "MA")],
    "divergence": [("osc", _t("exit.param.osc")), ("div_period", "Per"),
                   ("div_pivot", "Pivot")],
}
def _exit_tip(key: str) -> str:
    return _t(f"exit.tip.{key}") if _t(f"exit.tip.{key}") != f"exit.tip.{key}" else ""


def _num(s):
    """Magyar-tizedes ('1,75') vagy sima szám → float; hiba esetén None."""
    try:
        return float(str(s).replace(",", "."))
    except (ValueError, TypeError):
        return None


class BacktestDialog:
    """Önálló backtest-ablak egy adott paraméterkészlethez."""

    def __init__(self, parent, symbol, cfg, strategy, params, pair_cfg,
                 rr_spec, header_font, small_font, on_result=None,
                 preset_name: str = "Ki", on_apply_params=None, host=None,
                 on_state=None, host_scroll: bool = True, on_run_done=None,
                 provide_hours=None, provide_rr=None, provide_build=None):
        # `host`: ha adott (egy Frame), a tartalom ODA épül, nem külön ablakba —
        # így ugyanez az osztály szolgálja ki a Paraméterek ablak „Futtatás"
        # lapját is. A logika (haladás, grafikon, összevetés, CSV, MT5-export)
        # BETŰRE ugyanaz; csak a befogadó és a bezárás-szemantika más.
        #
        # ⚠ Miért nem másoltam ki a tartalmat a lapra: két példány óhatatlanul
        # elcsúszna. A backtest-ablak a projekt egyik legtöbbet használt felülete
        # — egy „majdnem ugyanolyan" második változat pont abban térne el, ami
        # ritkán fut (megszakítás, hibaág, MT5-export), és az nem derülne ki.
        self._host    = host
        # ⚠ `host_scroll=False`: a gazda MAGA görget (a Paraméter lap egy
        # görgethető oldal). Sajat gorgetheto teruletet epiteni bele KETTOS
        # csapda volna: (1) a belso vaszonnak nincs termeszetes magassaga egy
        # nyujtozo szuloben — osszelapulna; (2) az egergorgo mindketto
        # kezelojet elerné (a `scroll_area` csak azt nezi, LATSZIK-e a vaszon),
        # tehat egy gorgetes ket teruletet mozditana el egyszerre.
        self._host_scroll = bool(host_scroll)
        # `on_state(fut: bool)` — a beágyazó ebből tudja, mikor váltson a
        # saját gombja Megszakításra és vissza. Enélkül a gazda gombja
        # futás közben is „Indítás"-t mutatna.
        self._on_state = on_state
        # `on_run_done(result)` — a NYERS futás-eredmény (BacktestResult) a
        # befogadónak, hogy tételes nézetet (kötés-lista) építhessen rá.
        # ⚠ Ez SZÁNDÉKOSAN más, mint az `on_result`: azt a mentett minősítés
        # visszaírására hívjuk, és CSAK ha ugyanazzal a kockázatcsökkentéssel
        # mértünk, mint a mentett — különben egy feltáró futás szennyezné a
        # nyilvántartott számot. A nyers eredményt viszont MINDIG átadjuk: az a
        # most lefuttatott futás nézete, és épp feltáró beállításnál a
        # legérdekesebb.
        self._on_run_done = on_run_done
        # ── EGY FORRÁS: a beágyazó ad ÉLŐ értéket, nem pillanatképet ────────
        # ⚠ Beágyazva ugyanezek a beállítások ott állnak a lap FELJEBBI
        # szakaszaiban (Kereskedési órák · Kapuk · Kockázatcsökkentés). Egy
        # második, szerkeszthető másolat pontosan azt a kérdést szüli, amiért az
        # egész átalakítás elindult: „most akkor melyiket használja?".
        #
        # ⚠ ÉS MIÉRT FÜGGVÉNY, NEM ÉRTÉK. A beágyazott példány csak akkor épül
        # újra, ha a PARAMÉTEREK változnak. Ha a kockázatcsökkentést a szakaszban
        # átállítod, egy átadott pillanatkép elavulna — a futás némán a régivel
        # menne. A hívó függvényét FUTÁSKOR kérdezzük meg.
        self._provide_hours = provide_hours
        self._provide_rr    = provide_rr
        self._provide_build = provide_build
        self.parent   = parent
        self.symbol   = symbol
        self.cfg      = cfg
        self.strategy = strategy
        self.params   = dict(params)
        # A megnyitáskori paraméterek — a „Vissza" gomb ide állít vissza; a típus-
        # minta (int/float/bool/str) a szerkesztett érték visszakonvertálásához.
        self._init_params = dict(params)
        self._param_keys  = sorted(k for k in params if not str(k).startswith("_"))
        self.pair_cfg = pair_cfg
        self.rr_spec  = rr_spec
        self._hf      = header_font
        self._sf      = small_font
        self._on_result = on_result
        self._on_apply_params = on_apply_params   # visszaírás a szülő űrlapba
        self._preset_name = preset_name

        # A megnyitáskori (fő ablak) rr — ehhez viszonyítunk a visszaíráskor:
        # csak akkor írunk vissza a főképernyőre, ha a Backtest-ablakban ugyanezt
        # az rr-t mértük (különben feltáró futtatás, nem szennyezi a mentendőt).
        self._opened_rr_key = self._rr_key(rr_spec)
        _s0 = rr_spec or {}
        self._init_preset   = _s0.get("preset", _rrx.PRESET_OFF)
        self._init_runner   = _s0.get("runner_stop", _rrx.RUNNER_TRAILING)
        self._init_cautious = bool(_s0.get("cautious", False))
        self._init_cc       = bool(_s0.get("cost_cut", False))
        self._init_cc_bars  = int(_s0.get("cost_cut_bars",
                                          _rrx.default_config()["cost_cut_bars"]))
        # Exit-config (FELTÁRÓ, LOKÁLIS — nem írjuk a per-pár állapotba). A megnyitáskori
        # rr-spec exitjéből indul, különben a per-pár mentett exit-configból.
        _ex0 = dict((_s0.get("exit") or _rrs.get_exit_config(symbol)))
        self._exit_cfg = _ex0
        # Építés (FELTÁRÓ, LOKÁLIS) — a per-pár mentett módból/faktorból indul.
        self._init_build = _bst.get_config(symbol)

        # Előző / eredeti futás (a #4 összevetéshez)
        self._cur_result  = None
        self._cur_summary = None
        self._prev_result = None
        self._prev_summary = None
        self._orig_result = None
        self._orig_summary = None
        self._ib = float(cfg.get("ml", {}).get("starting_balance_eur", 1000.0))
        # Megjegyzett (per stratégia+pár) kényelmi beállítások: időszak, nyitó
        # összeg, slotok. A preset/építés SZÁNDÉKOSAN nem mentődik (feltáró).
        self._prefs = _bprefs.get(symbol, strategy.name)

        self._df15 = None
        self._df1  = None
        self._build_csv = None      # a legutóbbi futás Építés CSV-je (gomb)
        self._running = False
        self._closed  = False       # az ablak bezárult-e (a háttérszál ne piszkálja a widgeteket)
        self._stop_flag = None      # threading.Event a futó backtest megszakításához
        self._summary = None
        # Jelölt-lista gyorsítótár: a feltáró munka során a VÉGREHAJTÁST hangoljuk
        # (SL/TP, rr, slotok, kapuk), a jel-oldal változatlan → nem kell újra
        # kiszámolni. Az ablakhoz kötött (bezáráskor eldobódik).
        self._sig_cache = None
        import queue as _queue
        self._ui_q = _queue.Queue()      # háttérszál → főszál (lásd `_post`)
        self._build()
        self._ui_poll()                  # a FŐSZÁLRÓL indítva
        # Adat betöltése háttérben (a dátum-tartományhoz + a futáshoz cache-elve)
        self._load_data_async()

    # ── rr (kockázatcsökkentés) segédek ──────────────────────────────────────
    @staticmethod
    def _rr_key(spec):
        """A spec összehasonlítható kulcsa (preset, runner, óvatos). OFF/None → ('off',)."""
        if not spec or spec.get("preset", _rrx.PRESET_OFF) == _rrx.PRESET_OFF:
            return ("off",)
        return (spec.get("preset"), spec.get("runner_stop"),
                bool(spec.get("cautious")))

    def _preset_from_name(self, name: str) -> str:
        return {v: k for k, v in _rrs.NAME.items()}.get(name, _rrx.PRESET_OFF)

    def _runner_from_name(self, name: str) -> str:
        return {v: k for k, v in _rrs.RUNNER_NAME.items()}.get(
            name, _rrx.RUNNER_TRAILING)

    def _current_rr_spec(self):
        """Az ablakban BEÁLLÍTOTT rr-spec (feltáró). None, ha 'Ki' ÉS a cost-cut
        is ki. Tartalmazza az Exit-configot (Runner=Kiszállási jel dönti) és a
        cost-cutot (Ki preset mellett is élhet — önálló idő-stop)."""
        if self._provide_rr is not None:
            return self._provide_rr()          # a szakasz az EGYETLEN forrás
        preset = self._preset_from_name(self._rr_name.get())
        cc_on  = bool(self._cc_var.get())
        if preset == _rrx.PRESET_OFF and not cc_on:
            return None
        runner = self._runner_from_name(self._runner_name.get())
        exit_cfg = dict(self._exit_cfg)
        exit_cfg["enabled"] = (runner == _rrx.RUNNER_EXIT)
        spec = {**_rrx.default_config(), "preset": preset,
                "runner_stop": runner,
                "cautious": (bool(self._cautious_var.get())
                             if preset != _rrx.PRESET_OFF else False),
                "exit": exit_cfg,
                "cost_cut": cc_on}
        try:
            _b = int(float(self._cc_bars_var.get().strip().replace(",", ".")))
            if _b > 0:
                spec["cost_cut_bars"] = _b
        except ValueError:
            pass
        return spec

    def _cfg_max_slots(self) -> int:
        """A config szerinti slot-szám (a mező alapértéke). Hiány/hibás → 4."""
        try:
            return max(1, int(self.cfg.get("trading", {}).get("max_open_slots", 4)))
        except (TypeError, ValueError):
            return 4

    def _run_trading_cfg(self) -> dict:
        """A futtatáshoz használt trading_cfg — a `Slotok` mezővel felülírt
        `max_open_slots`-szal. MÁSOLAT: a feltáró futtatás nem írja a live configot.
        Érvénytelen/üres mező → a config értéke (a korábbi viselkedés)."""
        n = _num(self._slots_var.get())
        slots = max(1, int(n)) if n is not None and n >= 1 else self._cfg_max_slots()
        return {**self.cfg["trading"], "max_open_slots": slots}

    def _allowed_hours(self):
        """A backtest óra-kapuja. None → minden óra (a checkbox KI). Bekapcsolva a
        stratégia kereskedési órái (trade_hours), a live `process_pair`-rel EGYEZŐ
        feloldással: stratégia-hatókörű `{symbol}_hours.json` → legacy trade_hours →
        sess_start/sess_end tartomány."""
        # Beágyazva a KERESKEDÉSI ÓRÁK szakasz dönt (egy helyen állítod), és
        # nincs kapcsoló: ha ott szűkítesz, a mérés is szűkül.
        if self._provide_hours is not None:
            return self._provide_hours()
        if not self._hours_filter_var.get():
            return None
        th = resolve_trade_hours(self.symbol, self.strategy.name,
                                 self.pair_cfg.get("trade_hours"))
        if th is not None:
            return {int(h) for h in th}
        return set(range(int(self.pair_cfg.get("sess_start", 0)),
                         int(self.pair_cfg.get("sess_end", 24))))

    def _current_build_cfg(self):
        """Az ablakban BEÁLLÍTOTT építés-config (feltáró) — mode + size_factor + trigger
        + R-paraméterek (a run_pair `build` override-jához)."""
        if self._provide_build is not None:
            return self._provide_build()       # a szakasz az EGYETLEN forrás
        mode = {v: k for k, v in _bst.NAME.items()}.get(
            self._build_mode_name.get(), _bst.MODE_OFF)
        sf = _num(self._build_sf_var.get())
        trig = {v: k for k, v in _pb.TRIGGER_NAME.items()}.get(
            self._build_trig_name.get(), _pb.TRIGGER_CANDLE)
        rstep = _num(self._build_rstep_var.get())
        rshrink = _num(self._build_rshrink_var.get())
        return {"mode": mode, "size_factor": sf if sf and sf > 0 else 0.7,
                "trigger": trig,
                "r_step": rstep if rstep and rstep > 0 else 1.0,
                "r_shrink": rshrink if rshrink and 0 < rshrink < 1 else 0.5}

    # ── UI ──────────────────────────────────────────────────────────────────
    def _build(self):
        if self._host is not None:
            # Beágyazva: a tartalom a kapott keretbe megy. A `self.win` a
            # BEFOGLALÓ ablak — az `after()`, a képernyőméret-lekérdezés és a
            # grab ugyanúgy működik, csak nem mi hoztuk létre, tehát nem is mi
            # zárjuk be.
            container = self._host
            win = self._host.winfo_toplevel()
            self.win = win
        else:
            win = tk.Toplevel(self.parent)
            self.win = win
            container = win
            win.title(f"{self.symbol} — {self.strategy.name} Backtest")
            win.configure(bg=BG)

        if self._host is not None and not self._host_scroll:
            # LAPOS beágyazás: a gazda oldal görget, mi csak egymás alá pakolunk.
            # A „rögzített alsó sáv" itt értelmetlen volna: nincs saját ablak,
            # amihez képest rögzülhetne — a sáv egyszerűen a tartalom VÉGÉRE
            # kerül, és a gazda görgetője viszi.
            body = tk.Frame(container, bg=BG)
            body.pack(side="top", fill="both", expand=True)
            footer = tk.Frame(container, bg=BG)
            footer.pack(side="top", fill="x")
            self._body_canvas = None
            self._body = body
        else:
            # ── Rögzített alsó sáv ELŐSZÖR (side="bottom") ──────────────────
            # A pack-sorrend miatt a lentre kötött sáv kapja meg a helyét először,
            # a görgethető törzs csak a maradékot → a Backtest indítása / Mentés a
            # Paraméterekhez / Bezárás gombok kis képernyőn is MINDIG látszanak.
            footer = tk.Frame(container, bg=BG)
            footer.pack(side="bottom", fill="x")

            # Görgethető törzs — innentől MINDEN tartalom ide (`body`) megy.
            holder, body, self._body_canvas = _scrollable(container)
            holder.pack(side="top", fill="both", expand=True)
            self._body = body

        tk.Label(body, text=f"{self.symbol}  ·  {self.strategy.name} — Backtest",
                 bg=BG, fg=FG_WHITE, font=self._hf).pack(anchor="w", padx=12, pady=(12, 2))

        # ── Időszak ─────────────────────────────────────────────────────────
        rng = tk.Frame(body, bg=BG)
        rng.pack(anchor="w", padx=12, pady=(4, 0))
        tk.Label(rng, text=_t("bt.range"), bg=BG,
                 fg=FG_GRAY, font=self._sf).pack(side="left")
        self._start_var = tk.StringVar()
        self._end_var   = tk.StringVar()
        e1 = tk.Entry(rng, width=12, textvariable=self._start_var, bg=BG_HEADER,
                      fg=FG_WHITE, font=self._sf, insertbackground=FG_WHITE,
                      justify="center")
        e1.pack(side="left", padx=(6, 2))
        _cb1 = tk.Button(rng, text="📅", bg=BG_HEADER, fg=FG_WHITE, relief="flat",
                         cursor="hand2", font=("Segoe UI Emoji", 10),
                         command=lambda: self._open_calendar(self._start_var, e1))
        _cb1.pack(side="left", padx=(0, 4))
        _attach_tooltip(_cb1, _t("bt.cal_from"))
        tk.Label(rng, text="→", bg=BG, fg=FG_GRAY, font=self._sf).pack(side="left")
        e2 = tk.Entry(rng, width=12, textvariable=self._end_var, bg=BG_HEADER,
                      fg=FG_WHITE, font=self._sf, insertbackground=FG_WHITE,
                      justify="center")
        e2.pack(side="left", padx=(2, 2))
        _cb2 = tk.Button(rng, text="📅", bg=BG_HEADER, fg=FG_WHITE, relief="flat",
                         cursor="hand2", font=("Segoe UI Emoji", 10),
                         command=lambda: self._open_calendar(self._end_var, e2))
        _cb2.pack(side="left")
        _attach_tooltip(_cb2, _t("bt.cal_to"))
        self._span_lbl = tk.Label(body, text=_t("bt.loading"), bg=BG,
                                  fg=FG_GRAY_DIM, font=self._sf)
        self._span_lbl.pack(anchor="w", padx=12, pady=(1, 4))

        # ── Tanítási ablak figyelmeztetés ───────────────────────────────────
        # Tanult modellnél a saját tanító időszakán a backtest a MEMÓRIÁT méri,
        # nem a képességet (`core/training_overlap.py` — ott a számok is). Ez
        # eddig sehol nem látszott: egy 1000$ → 14 398$ eredmény ugyanúgy nézett
        # ki, mint egy valódi. A sor a dátumok MINDEN változásánál frissül, tehát
        # a figyelmeztetés a választás közben jön, nem a futtatás után.
        self._train_lbl = tk.Label(body, text="", bg=BG, fg=FG_RED,
                                   font=self._sf, anchor="w", justify="left",
                                   wraplength=680)
        self._train_lbl.pack(anchor="w", padx=12, pady=(0, 4))
        for _v in (self._start_var, self._end_var):
            _v.trace_add("write", lambda *_a: self._update_training_warning())

        # ── Óra-kapu (kereskedési órák szűrése) ─────────────────────────────
        # Ha bekapcsolod, a backtest CSAK a stratégia kereskedési óráiban (trade_hours,
        # mint a live) nyit — a többi óra kimarad, és ha a `no_trade_resets_signal`
        # param be van kapcsolva, a szünet reseteli az M15 ablakot (mint élesben).
        # Alap: KI → minden órában kereskedik (a korábbi backtest-ablak viselkedése).
        hrow = tk.Frame(body, bg=BG)
        hrow.pack(anchor="w", padx=12, pady=(0, 4))
        self._hours_filter_var = tk.BooleanVar(value=False)
        _hcb = tk.Checkbutton(hrow,
                              text=_t("bt.hours_only"),
                              variable=self._hours_filter_var, bg=BG, fg=FG_GRAY,
                              selectcolor=BG_HEADER, font=self._sf,
                              activebackground=BG, activeforeground=FG_WHITE)
        # ⚠ Beágyazva NINCS kapcsoló: a lap tetején ott a Kereskedési órák
        # szakasz, és az dönt. Egy kapcsoló, ami felülírhatja, azt jelentené,
        # hogy a beállított órák néha nem érvényesek — épp azt a bizonytalanságot
        # hozná vissza, amiért az órákat egy helyre tettük.
        if self._host is None:
            _hcb.pack(side="left")

        # ── Végrehajtási kapuk (él-paritás) ─────────────────────────────────
        # Bekapcsolva a backtest UGYANAZT a két VÉGREHAJTÁSI kaput modellezi, amit az
        # él: spread-kapu (gates.spread_gate) + TF-együttállás (ha az adott stratégiára/
        # instrumentumra a configban be van kapcsolva). Így a backtest nem nyit olyan
        # belépőt, amit élesben egy kapu kiszűrne. Alap: BE. KI → nyers jelek.
        grow = tk.Frame(body, bg=BG)
        # ⚠ Beágyazva NINCS mester-kapcsoló: a Kapuk szakaszban KAPUNKÉNT
        # eldöntöd, modellezze-e a mérés (`gates_backtest`). Egy fölérendelt
        # „mind vagy semmi" kapcsoló mellett nem lehetne tudni, melyik nyert —
        # és épp a kapunkénti mérés volt az, amiért a harmadik oszlop készült.
        if self._host is None:
            grow.pack(anchor="w", padx=12, pady=(0, 4))
        self._exec_gates_var = tk.BooleanVar(value=True)
        tk.Checkbutton(grow,
                       text=_t("bt.exec_gates"),
                       variable=self._exec_gates_var, bg=BG, fg=FG_GRAY,
                       selectcolor=BG_HEADER, font=self._sf, activebackground=BG,
                       activeforeground=FG_WHITE).pack(side="left")

        # ── Slotok ──────────────────────────────────────────────────────────
        # ⚠ A KORÁBBI MEGJEGYZÉS ITT TÉVES VOLT. Azt állította, hogy „egy páron
        # amúgy is legfeljebb EGY pozíció fut", tehát a slot-szám csak a MÉRETET
        # állítja. A motor viszont EGY PÁRON IS annyi pozíciót nyithat, ahány
        # szabad slot van (`free_slots = max_open_slots − occupied`, ahol az
        # `occupied` csak a NEM kockázatmentes pozíciókat számolja) — élesben
        # ugyanígy.
        #
        # A slot-szám tehát KÉT dolgot állít egyszerre, és a kettő ellentétes
        # irányba húz. Mérve (Ger40, 2026-06-01→08-14, kapukkal):
        #
        #     slot   kötés     P&L     átlag lot   max egyszerre
        #        1      84    −827$        3,97          1
        #        2     180    −569$        2,11          2
        #        4     252    −217$        1,09          4
        #        8     298    −279$        0,47          4
        #
        # 1 slot = egyszerre EGY pozíció, de NÉGYSZERES lottal: a jelek nagy része
        # kimarad, mert nyitott pozíció mellett nincs hova belépni. A teljes
        # kockázat nagyjából állandó marad — a slot-szám azt osztja szét
        # (`risk_per_slot = egyenleg × account_risk_pct / slotok`, `calc_lot`).
        tk.Label(hrow, text="Slotok:", bg=BG, fg=FG_GRAY,
                 font=self._sf).pack(side="left", padx=(16, 2))
        self._slots_var = tk.StringVar(
            value=str(self._prefs.get("slots", self._cfg_max_slots())))
        _se = tk.Entry(hrow, width=4, textvariable=self._slots_var, bg=BG_HEADER,
                       fg=FG_WHITE, font=self._sf, insertbackground=FG_WHITE,
                       justify="center")
        _se.pack(side="left")
        _attach_tooltip(_se, _t("bt.slots_tip"))

        # ── Nyitó összeg (kezdő tőke a futtatáshoz) ─────────────────────────
        # A lot-méretezés (kockázat = egyenleg × account_risk_pct) és a %-os hozam
        # ettől függ. Üres/érvénytelen → a config starting_balance_eur (alap 1000).
        tk.Label(hrow, text=_t("bt.initial"), bg=BG, fg=FG_GRAY,
                 font=self._sf).pack(side="left", padx=(16, 2))
        self._ib_var = tk.StringVar(value=str(self._prefs.get("ib", f"{self._ib:.0f}")))
        _ie = tk.Entry(hrow, width=8, textvariable=self._ib_var, bg=BG_HEADER,
                       fg=FG_WHITE, font=self._sf, insertbackground=FG_WHITE,
                       justify="center")
        _ie.pack(side="left")
        _attach_tooltip(_ie, _t("bt.initial_tip"))

        # ── Paraméterek ─────────────────────────────────────────────────────
        # ⚠ BEÁGYAZVA NINCS paraméter-lista. A lap MELLETT ott a Paraméter lap,
        # ugyanazokkal a kulcsokkal — két szerkeszthető másolat ugyanarra az
        # értékre pontosan azt a zavart okozza, ami miatt az egesz átalakítás
        # elindult: „melyiket használja épp?". A válasz mostantól egyértelmű: a
        # Paraméter lapét (a Futtatás lap újraépül, ha ott átírsz valamit).
        #
        # Önálló ablakként viszont MEGMARAD: ott nincs mellette paraméter-űrlap,
        # és a feltáró szerkesztés + „Vissza" a fő értéke.
        self._pentries = {}
        if self._host is None:
            phdr = tk.Frame(body, bg=BG)
            phdr.pack(fill="x", padx=12, pady=(2, 0))
            tk.Label(phdr, text=_t("bt.params_edit"), bg=BG,
                     fg=FG_GRAY, font=self._sf).pack(side="left")
            tk.Button(phdr, text=_t("bt.params_back"), bg=BG_HEADER, fg=FG_WHITE,
                      relief="flat", font=self._sf, cursor="hand2",
                      command=self._reset_params).pack(side="left", padx=(8, 0))
            pform = tk.Frame(body, bg=BG)
            pform.pack(anchor="w", padx=12, pady=(2, 2))
            _COLS = 2
            for i, k in enumerate(self._param_keys):
                r, c = divmod(i, _COLS)
                cell = tk.Frame(pform, bg=BG)
                cell.grid(row=r, column=c, sticky="w", padx=(0, 12), pady=1)
                tk.Label(cell, text=k, bg=BG, fg=FG_WHITE, font=self._sf,
                         anchor="w", width=22).pack(side="left")
                e = tk.Entry(cell, width=9, bg=BG_HEADER, fg=FG_WHITE,
                             font=self._sf, insertbackground=FG_WHITE)
                e.insert(0, str(self._init_params[k]))
                e.pack(side="left")
                self._pentries[k] = e
        else:
            tk.Label(body, bg=BG, fg=FG_GRAY_DIM, font=self._sf, anchor="w",
                     justify="left", wraplength=820,
                     text=_t("bt.params_on_tab")
                     ).pack(anchor="w", padx=12, pady=(2, 2))

        # ── Vezérlő-csoportok: Kockázatcsökkentés + Pozícióépítés (FELTÁRÓ) ──
        # Ugyanaz a logikai tiltás, mint az instrumentum-ablakban: a nem releváns
        # vezérlők ELREJTVE a preset/runner/építés szerint. A két csoport EGYMÁS
        # ALATT (nem egymás mellett): a kockázatcsökkentés sora hosszú, mellette a
        # Pozícióépítés kilógott az ablakból.
        ctl = tk.Frame(body, bg=BG)
        # ⚠ Beágyazva NEM csomagoljuk: a lapon FELJEBB ott a Kockázatcsökkentés
        # szakasz (preset · runner · exit · cost-cut · építés), és az dönt. A
        # widgetek LÉTREJÖNNEK — a láthatóság-logika és a belső hivatkozások rájuk
        # épülnek —, csak nem látszanak; az ÉRTÉKET a `_provide_rr`/`_provide_build`
        # adja, FUTÁSKOR lekérdezve.
        if self._host is None:
            ctl.pack(anchor="w", fill="x", padx=12, pady=(2, 0))

        rrg = tk.LabelFrame(ctl, text=_t("bt.rr_group"),
                            bg=BG, fg=FG_BLUE, font=self._sf, labelanchor="nw")
        rrg.pack(anchor="w", fill="x")
        row = tk.Frame(rrg, bg=BG)
        row.pack(anchor="w", padx=6, pady=4)
        tk.Label(row, text=_t("bt.preset"), bg=BG, fg=FG_GRAY,
                 font=self._sf).grid(row=0, column=0, sticky="w")
        self._rr_name = tk.StringVar(value=_rrs.NAME.get(self._init_preset, "Ki"))
        om = tk.OptionMenu(row, self._rr_name, *[_rrs.NAME[p] for p in _rrs.CYCLE],
                           command=self._on_rr_change_local)
        _style_om(om, self._sf)
        om.grid(row=0, column=1, padx=(4, 0))
        _attach_tooltip(om, _t("bt.preset_tip"))

        self._cautious_var = tk.BooleanVar(value=self._init_cautious)
        self._cautious_cb = tk.Checkbutton(
            row, text=_t("bt.cautious"), variable=self._cautious_var,
            bg=BG, fg=FG_GRAY, selectcolor=BG_HEADER, font=self._sf,
            activebackground=BG, activeforeground=FG_WHITE)
        self._cautious_cb.grid(row=0, column=2, padx=(10, 0))
        _attach_tooltip(self._cautious_cb, _t("bt.cautious_tip"))

        self._runner_frame = tk.Frame(row, bg=BG)
        self._runner_frame.grid(row=0, column=3, padx=(10, 0), sticky="w")
        tk.Label(self._runner_frame, text="Runner:", bg=BG, fg=FG_GRAY,
                 font=self._sf).pack(side="left")
        self._runner_name = tk.StringVar(
            value=_rrs.RUNNER_NAME.get(self._init_runner, "Trailing"))
        omr = tk.OptionMenu(self._runner_frame, self._runner_name,
                            *[_rrs.RUNNER_NAME[r] for r in _rrs.RUNNERS],
                            command=self._on_runner_change_local)
        _style_om(omr, self._sf)
        omr.pack(side="left", padx=(4, 0))
        _attach_tooltip(self._runner_frame, _t("bt.runner_tip"))

        # Cost-cut — idő-stop (feltáró, lokális); bármely presettel kombinálható
        self._cc_frame = tk.Frame(row, bg=BG)
        self._cc_frame.grid(row=0, column=5, padx=(10, 0), sticky="w")
        self._cc_var = tk.BooleanVar(value=self._init_cc)
        _ccb = tk.Checkbutton(self._cc_frame, text="Cost-cut", variable=self._cc_var,
                              bg=BG, fg=FG_GRAY, selectcolor=BG_HEADER, font=self._sf,
                              activebackground=BG, activeforeground=FG_WHITE)
        _ccb.pack(side="left")
        self._cc_bars_var = tk.StringVar(value=str(self._init_cc_bars))
        _cce = tk.Entry(self._cc_frame, textvariable=self._cc_bars_var, width=4,
                        bg=BG_HEADER, fg=FG_WHITE, font=self._sf, relief="flat",
                        insertbackground=FG_WHITE)
        _cce.pack(side="left", padx=(4, 0))
        _attach_tooltip(self._cc_frame, _t("bt.costcut_tip"))

        self._exit_frame = tk.Frame(row, bg=BG)
        self._exit_frame.grid(row=0, column=4, padx=(10, 0), sticky="w")
        tk.Label(self._exit_frame, text="Exit:", bg=BG, fg=FG_GRAY,
                 font=self._sf).pack(side="left")
        _exind = self._exit_cfg.get("indicator", "supertrend")
        self._exit_ind_name = tk.StringVar(value=_exind_name().get(_exind, "Supertrend"))
        ome = tk.OptionMenu(self._exit_frame, self._exit_ind_name, *_exind_name().values(),
                            command=self._on_exit_ind_change)
        _style_om(ome, self._sf)
        ome.pack(side="left", padx=(4, 0))
        _attach_tooltip(ome, _t("bt.exit_tip"))
        self._exit_pfrm = tk.Frame(self._exit_frame, bg=BG)
        self._exit_pfrm.pack(side="left", padx=(6, 0))
        self._exit_param_vars = {}
        self._rebuild_exit_params()

        bldg = tk.LabelFrame(ctl, text=_t("bt.build_group"),
                             bg=BG, fg=FG_BLUE, font=self._sf, labelanchor="nw")
        bldg.pack(anchor="w", fill="x", pady=(6, 0))
        brow = tk.Frame(bldg, bg=BG)
        brow.pack(anchor="w", padx=6, pady=4)
        tk.Label(brow, text=_t("bt.build"), bg=BG, fg=FG_GRAY,
                 font=self._sf).pack(side="left")
        self._build_mode_name = tk.StringVar(
            value=_bst.NAME.get(self._init_build.get("mode", _bst.MODE_OFF), "Ki"))
        omb = tk.OptionMenu(brow, self._build_mode_name, *_bst.NAME.values(),
                            command=self._on_build_mode_change_local)
        _style_om(omb, self._sf)
        omb.pack(side="left", padx=(4, 0))
        _attach_tooltip(omb, _t("bt.build_tip"))
        self._build_faktor_frame = tk.Frame(brow, bg=BG)
        tk.Label(self._build_faktor_frame, text=_t("bt.factor"), bg=BG, fg=FG_GRAY,
                 font=self._sf).pack(side="left")
        self._build_sf_var = tk.StringVar(value=str(self._init_build.get("size_factor", 0.7)))
        tk.Entry(self._build_faktor_frame, textvariable=self._build_sf_var, width=5,
                 bg=BG_HEADER, fg=FG_WHITE, font=self._sf, relief="flat",
                 insertbackground=FG_WHITE).pack(side="left", padx=(2, 0))
        _attach_tooltip(self._build_faktor_frame, _t("bt.factor_tip"))
        # Trigger + R-paraméterek (MIKOR) — az instrumentum-ablakkal egyezően
        self._build_trig_frame = tk.Frame(brow, bg=BG)
        tk.Label(self._build_trig_frame, text=_t("bt.trigger"), bg=BG, fg=FG_GRAY,
                 font=self._sf).pack(side="left")
        self._build_trig_name = tk.StringVar(
            value=_pb.TRIGGER_NAME.get(
                self._init_build.get("trigger", _pb.TRIGGER_CANDLE),
                _pb.TRIGGER_NAME[_pb.TRIGGER_CANDLE]))
        omt = tk.OptionMenu(self._build_trig_frame, self._build_trig_name,
                            *_pb.TRIGGER_NAME.values(), command=self._on_build_trigger_change_local)
        _style_om(omt, self._sf)
        omt.pack(side="left", padx=(4, 0))
        _attach_tooltip(omt, _t("bt.trigger_tip"))
        self._build_rstep_frame = tk.Frame(brow, bg=BG)
        tk.Label(self._build_rstep_frame, text=_t("bt.rstep"), bg=BG, fg=FG_GRAY,
                 font=self._sf).pack(side="left")
        self._build_rstep_var = tk.StringVar(value=str(self._init_build.get("r_step", 1.0)))
        tk.Entry(self._build_rstep_frame, textvariable=self._build_rstep_var, width=4,
                 bg=BG_HEADER, fg=FG_WHITE, font=self._sf, relief="flat",
                 insertbackground=FG_WHITE).pack(side="left", padx=(2, 0))
        _attach_tooltip(self._build_rstep_frame, _t("bt.rstep_tip"))
        self._build_rshrink_frame = tk.Frame(brow, bg=BG)
        tk.Label(self._build_rshrink_frame, text=_t("bt.rshrink"), bg=BG, fg=FG_GRAY,
                 font=self._sf).pack(side="left")
        self._build_rshrink_var = tk.StringVar(value=str(self._init_build.get("r_shrink", 0.5)))
        tk.Entry(self._build_rshrink_frame, textvariable=self._build_rshrink_var, width=4,
                 bg=BG_HEADER, fg=FG_WHITE, font=self._sf, relief="flat",
                 insertbackground=FG_WHITE).pack(side="left", padx=(2, 0))
        _attach_tooltip(self._build_rshrink_frame, _t("bt.rshrink_tip"))

        self._update_rr_visibility()

        _rrnote = tk.Label(body, text=_t("bt.rr_note"), bg=BG, fg=FG_GRAY_DIM,
            font=self._sf, justify="left", wraplength=620)
        if self._host is None:
            _rrnote.pack(anchor="w", padx=12, pady=(1, 4))

        # ── Progress ────────────────────────────────────────────────────────
        pf = tk.Frame(body, bg=BG)
        pf.pack(fill="x", padx=12, pady=(2, 2))
        self._pbar = ttk.Progressbar(pf, orient="horizontal", mode="determinate",
                                     maximum=100.0, length=380)
        self._pbar.pack(side="left")
        self._pct_lbl = tk.Label(pf, text="0%", bg=BG, fg=FG_GRAY, font=self._sf,
                                 width=6)
        self._pct_lbl.pack(side="left", padx=(8, 0))

        # ── Élő kijelzés ────────────────────────────────────────────────────
        live = tk.Frame(body, bg=BG)
        live.pack(anchor="w", padx=12, pady=(2, 2))
        self._live = {}
        for key, label in (("time", _t("bt.live.time")),
                           ("balance", _t("bt.live.balance")),
                           ("open", _t("bt.live.open")),
                           ("closed", _t("bt.live.closed"))):
            cell = tk.Frame(live, bg=BG)
            cell.pack(side="left", padx=(0, 14))
            tk.Label(cell, text=label, bg=BG, fg=FG_GRAY,
                     font=self._sf).pack(side="left")
            v = tk.Label(cell, text="—", bg=BG, fg=FG_WHITE, font=self._sf)
            v.pack(side="left")
            self._live[key] = v
        self._tech_lbl = tk.Label(body, text="", bg=BG, fg=FG_GRAY_DIM,
                                  font=self._sf)
        self._tech_lbl.pack(anchor="w", padx=12, pady=(0, 2))
        # A jelölt-lista állapota. ⚠ Ez NEM dísz: enélkül a gyorsítótár láthatatlan
        # volna, és egy elmaradt újraépítés észrevétlen maradna. Ha itt „újraszámolva"
        # áll, akkor a JEL-oldalt módosítottad — ha „újrahasznosítva", akkor csak a
        # végrehajtást, tehát a két futás ugyanazokat a jelölteket köti.
        self._series_lbl = tk.Label(body, text="", bg=BG, fg=FG_GRAY_DIM,
                                    font=self._sf)
        self._series_lbl.pack(anchor="w", padx=12, pady=(0, 2))

        # ── Összevetés-választó (előző/eredeti futás halvány overlay) ───────
        cmp_bar = tk.Frame(body, bg=BG)
        cmp_bar.pack(anchor="w", padx=12, pady=(2, 0))
        tk.Label(cmp_bar, text=_t("bt.compare"), bg=BG, fg=FG_GRAY,
                 font=self._sf).pack(side="left")
        # ⚠ FELIRAT a legördülőben, KÓD a döntésben (`_reference`) — a
        # lefordított szövegre hasonlítás ott némán „nincs összevetés"-t adna.
        self._overlay_choices = [(c, _t(f"backtest.overlay.{c}"))
                                 for c in ("none", "prev", "orig")]
        self._overlay_mode = tk.StringVar(value=self._overlay_choices[1][1])
        omc = tk.OptionMenu(cmp_bar, self._overlay_mode,
                            *[lbl for _c, lbl in self._overlay_choices],
                            command=lambda _=None: self._on_overlay_change())
        omc.config(bg=BG_HEADER, fg=FG_WHITE, font=self._sf, relief="flat",
                   highlightthickness=0, activebackground=BG_HEADER)
        omc["menu"].config(bg=BG_HEADER, fg=FG_WHITE)
        omc.pack(side="left", padx=(4, 0))
        self._ref_metrics_lbl = tk.Label(cmp_bar, text="", bg=BG, fg=FG_GRAY_DIM,
                                         font=self._sf)
        self._ref_metrics_lbl.pack(side="left", padx=(10, 0))

        # ── Egyenleg-görbe (sparkline) ──────────────────────────────────────
        self._canvas = tk.Canvas(body, width=400, height=90, bg=BG_HEADER,
                                 highlightthickness=0)
        self._canvas.pack(anchor="w", padx=12, pady=(4, 4))

        # ── Eredmény-sáv (minősítés + metrikák) ─────────────────────────────
        self._grade_lbl = tk.Label(body, bg=BG, font=self._hf, anchor="w",
                                   text="")
        self._grade_lbl.pack(anchor="w", padx=12, pady=(2, 0))
        self._metrics_frame = tk.Frame(body, bg=BG)
        self._metrics_frame.pack(anchor="w", padx=12, pady=(0, 4))

        # Pozícióépítés hozadéka (hány ráépítés + mennyit hozott R-ben és $-ban)
        self._build_lbl = tk.Label(body, text="", bg=BG, fg=FG_GRAY_DIM,
                                   font=self._sf, anchor="w", justify="left")
        self._build_lbl.pack(anchor="w", padx=12, pady=(0, 4))

        self._status = tk.Label(body, text="", bg=BG, fg=FG_GRAY, font=self._sf)
        self._status.pack(anchor="w", padx=12, pady=(0, 6))

        # ── Gombok (a RÖGZÍTETT alsó sávban — mindig látszanak) ─────────────
        btns = tk.Frame(footer, bg=BG)
        btns.pack(pady=10)
        self._btn_start = tk.Button(btns, text=_t("bt.start"), bg=BTN_BT_BG,
                                    fg=BTN_BT_FG, relief="flat", font=self._sf,
                                    state="disabled", command=self._start)
        # ⚠ Beágyazva a saját indító gomb NEM látszik: a gazda terv-sávján áll
        # EGY gomb, ami a bepipált dimenziók számából dönt (backtest / söprés /
        # optimalizálás). Két indító gomb ugyanazon a lapon pontosan azt a
        # „melyiket használja épp?" zavart okozná, ami miatt az átalakítás
        # elindult — ráadásul a másik a TERVET is megkerülné. A widget viszont
        # LÉTREJÖN: a belső állapotváltások (Megszakítás / vissza) rá hivatkoznak.
        if self._host is None:
            self._btn_start.pack(side="left", padx=6)
        # ⚠ Beágyazva ez a gomb NEM CSINÁLNA SEMMIT: a paraméterek a Paraméter
        # lapról jönnek (nincs mit visszaírni), a friss eredményt pedig az
        # `on_result` már átadta a metrika-sávnak. Egy tétlen gomb rosszabb, mint
        # a hiányzó: azt sugallná, hogy van egy külön mentendő állapot.
        self._btn_apply = tk.Button(btns, text=_t("bt.apply"),
                                    bg=BTN_PLAY_BG, fg=BTN_PLAY_FG, relief="flat",
                                    font=self._sf, command=self._apply_params)
        if self._on_apply_params is None:
            self._btn_apply.config(state="disabled")
        if self._host is None:
            self._btn_apply.pack(side="left", padx=6)
        # Építés CSV — a ráépítések TÉTELESEN (mint a Trials CSV). Csak akkor él,
        # ha a futásban volt ráépítés (a fájl ilyenkor készül el).
        # ⚠ A NÉV PONTOSÍTVA: „Építés CSV" alapján ésszerű volt azt hinni, hogy az
        # optimalizálás eredményét menti — NEM azt teszi. A pozícióépítés
        # (ráépítés) tételes sorait írja ki: egy sor = egy ÉPÍTETT kötés, a lábak
        # bontásával. Az optimalizálás trial-listája a Kísérletek lapon van.
        self._btn_build_csv = tk.Button(btns, text=_t("bt.build_csv"), bg=BTN_BT_BG,
                                        fg=BTN_BT_FG, relief="flat", font=self._sf,
                                        state="disabled", command=self._open_build_csv)
        _attach_tooltip(self._btn_build_csv, _t("bt.build_csv_tip"))
        self._btn_build_csv.pack(side="left", padx=6)
        # ⚠ Beágyazva NINCS „Bezárás": az a befoglaló ablakot zárná be, nem a
        # lapot — a felhasználó pedig azt hinné, csak a backtestet csukja be.
        if self._host is None:
            tk.Button(btns, text=_t("btn.close"), bg=BTN_DIS_BG, fg=BTN_DIS_FG,
                      relief="flat", font=self._sf,
                      command=self._close).pack(side="left", padx=6)
            # A szülő (Stratégia Paraméterek) ablak grab_set-tel modális → a
            # gyereknek is meg kell fognia a grabot, különben kattinthatatlan.
            # Záráskor a grabot visszaadjuk a szülőnek.
            win.grab_set()
            win.protocol("WM_DELETE_WINDOW", self._close)
            self._fit_to_screen(win, body, footer)
        else:
            # Beágyazva a befoglaló ablak mérete a mérvadó; a törzs a
            # rendelkezésre álló helyet tölti ki (nem a tartalom diktál).
            try:
                self._body_canvas.config(height=520)
            except Exception:
                pass

    def _fit_to_screen(self, win, body, footer):
        """Az ablak méretezése a KÉPERNYŐHÖZ: ha a tartalom elfér, minden látszik;
        ha nem, a törzs görgethetővé zsugorodik, a gombsor pedig marad az alján.
        A canvas magától nem kér magasságot (create_window), ezért a belső frame
        igényéből — a képernyőre vágva — állítjuk be. (Mint az instrumentum-ablak.)"""
        try:
            win.update_idletasks()
            need_h = body.winfo_reqheight()
            need_w = body.winfo_reqwidth()
            avail = int(win.winfo_screenheight() * 0.85) - footer.winfo_reqheight() - 80
            self._body_canvas.config(height=max(240, min(need_h, avail)),
                                     width=need_w)
        except Exception:
            pass

    # ── Szálbiztos UI-frissítés ─────────────────────────────────────────────
    # ⚠ A Tcl értelmező EGYSZÁLÚ. A háttérszálból hívott `win.after()` megsérti:
    # a tünet nem kivétel, hanem hogy a frissítés ELVÉSZ, vagy — rosszabb esetben
    # — a widgetek egyszer csak eltűnnek. (Ugyanez a hiba a söprésnél mérhető
    # volt: ~55 mp után magától megsemmisült a felugró ablak.)
    #
    # Amíg ez az osztály KÜLÖN ablak volt, egy ilyen sérülés a backtest-ablakot
    # vitte el. Beágyazva viszont a Paraméterek ablakot vinné — a paramétereiddel
    # együtt. Ezért lett a minta helyes: a szál egy SORBA ír, a főszál futtatja.
    def _post(self, fn):
        """Háttérszálból: futtasd ezt a FŐSZÁLON, amint lehet."""
        try:
            self._ui_q.put(fn)
        except Exception:
            pass

    def _ui_poll(self):
        import queue as _q
        if self._closed:
            return
        try:
            while True:
                fn = self._ui_q.get_nowait()
                try:
                    fn()
                except tk.TclError:
                    return          # a widgetek megsemmisültek — csendben állunk
                except Exception:
                    pass
        except _q.Empty:
            pass
        try:
            self.win.after(120, self._ui_poll)
        except tk.TclError:
            pass

    def shutdown(self):
        """A háttérmunka leállítása widget-rombolás NÉLKÜL.

        Beágyazott módban a BEFOGLALÓ ablak zárul be; ilyenkor is jeleznünk kell
        a szálnak, hogy ne ütemezzen több widget-frissítést, különben a
        megsemmisült progressbar miatt `TclError`-cunami jön az after-ekből.
        """
        self._closed = True
        if self._stop_flag is not None:
            self._stop_flag.set()

    def _close(self):
        # Előbb jelezzük a háttérszálnak: ne ütemezzen több widget-frissítést, és a
        # futó backtest álljon le — különben a megsemmisült progressbar/widgetek
        # miatt `TclError`-cunami jönne az after-callbackekből.
        self.shutdown()
        if self._host is not None:
            return          # beágyazva nincs mit bezárni (nem mi nyitottuk)
        try:
            self.parent.grab_set()
        except Exception:
            pass
        self.win.destroy()

    # ── Exit-indikátor paraméterei (feltáró, lokális) ─────────────────────────
    def _on_exit_ind_change(self, name: str):
        ind = {v: k for k, v in _exind_name().items()}.get(name, "supertrend")
        self._exit_cfg["indicator"] = ind
        self._rebuild_exit_params()

    # ── Vezérlők logikai tiltása (mint az instrumentum-ablakban) ──────────────
    def _on_rr_change_local(self, _name=None):
        # Riskyre váltva alapból óvatos méret (de a user átállíthatja).
        if self._preset_from_name(self._rr_name.get()) == _rrx.PRESET_RISKY:
            self._cautious_var.set(True)
        self._update_rr_visibility()

    def _on_runner_change_local(self, _name=None):
        self._update_rr_visibility()

    def _on_build_mode_change_local(self, _name=None):
        self._update_rr_visibility()

    def _on_build_trigger_change_local(self, _name=None):
        self._update_rr_visibility()

    def _update_rr_visibility(self):
        """Óvatos csak ha van kockázatcsökkentés; Runner csak Felező/Pajzsnál; Exit csak
        Felező/Pajzs + Runner=Kiszállási jel; Építésnél: Faktor+Trigger csak ha ≠ Ki,
        R-lépés csak R-alapú triggernél, Zsug csak R-felezőnél."""
        preset = self._preset_from_name(self._rr_name.get())
        (self._cautious_cb.grid_remove if preset == _rrx.PRESET_OFF
         else self._cautious_cb.grid)()
        partial = preset in (_rrx.PRESET_HALVING, _rrx.PRESET_SHIELD,
                             _rrx.PRESET_SHIELD_FIBO)
        (self._runner_frame.grid if partial else self._runner_frame.grid_remove)()
        runner = self._runner_from_name(self._runner_name.get())
        show_exit = partial and runner == _rrx.RUNNER_EXIT
        (self._exit_frame.grid if show_exit else self._exit_frame.grid_remove)()
        # Építés-vezérlők (sorrend-tartó)
        for f in (self._build_faktor_frame, self._build_trig_frame,
                  self._build_rstep_frame, self._build_rshrink_frame):
            f.pack_forget()
        build_on = self._build_mode_name.get() != _bst.NAME[_bst.MODE_OFF]
        trig = {v: k for k, v in _pb.TRIGGER_NAME.items()}.get(
            self._build_trig_name.get(), _pb.TRIGGER_CANDLE)
        if build_on:
            self._build_faktor_frame.pack(side="left", padx=(8, 0))
            self._build_trig_frame.pack(side="left", padx=(10, 0))
            if trig in (_pb.TRIGGER_R_FIXED, _pb.TRIGGER_R_CONVERGE):
                self._build_rstep_frame.pack(side="left", padx=(8, 0))
            if trig == _pb.TRIGGER_R_CONVERGE:
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
            cap  = int(self.win.winfo_screenwidth() * 0.95)
            cv.config(width=max(int(cv.cget("width")), min(need, cap)))
        except Exception:
            pass

    def _rebuild_exit_params(self):
        """Az exit-indikátor SZERKESZTHETŐ mezőinek újraépítése (a kiválasztott
        indikátor szerint), a LOKÁLIS exit-configból feltöltve."""
        for w in self._exit_pfrm.winfo_children():
            w.destroy()
        self._exit_param_vars = {}
        ind = {v: k for k, v in _exind_name().items()}.get(
            self._exit_ind_name.get(), "supertrend")
        for key, label in _EXIT_PARAM_SPEC.get(ind, []):
            lbl = tk.Label(self._exit_pfrm, text=f"{label}:", bg=BG, fg=FG_GRAY,
                           font=self._sf)
            lbl.pack(side="left")
            var = tk.StringVar(value=str(self._exit_cfg.get(key, "")))
            e = tk.Entry(self._exit_pfrm, textvariable=var,
                         width=(5 if key == "osc" else 4), bg=BG_HEADER,
                         fg=FG_WHITE, font=self._sf, relief="flat",
                         insertbackground=FG_WHITE)
            e.pack(side="left", padx=(2, 6))
            e.bind("<FocusOut>", lambda ev, k=key: self._save_exit_param(k))
            e.bind("<Return>",   lambda ev, k=key: self._save_exit_param(k))
            _tip = _exit_tip(key)
            _attach_tooltip(lbl, _tip)
            _attach_tooltip(e, _tip)
            self._exit_param_vars[key] = var

    def _save_exit_param(self, key: str):
        """Egy exit-paraméter a LOKÁLIS configba (típus-validálással)."""
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
        self._exit_cfg[key] = val

    # ── Paraméter-szerkesztés (feltáró) ──────────────────────────────────────
    def _reset_params(self):
        """„Vissza" — a megnyitáskori paraméterek visszaállítása az űrlapon."""
        for k, e in self._pentries.items():
            e.delete(0, "end")
            e.insert(0, str(self._init_params[k]))
        self._status.config(text=_t("bt.params_reset"), fg=FG_GRAY)

    def _collect_params(self):
        """Az Entry-k tartalma → típusos paraméter-dict (a megnyitáskori típus
        szerint). MINDEN megnyitáskori kulcsot megőrzünk (a szerkeszthetők felülírják),
        hogy a nem szerkeszthető, de a motornak KELLŐ mentett kulcsok se vesszenek el:
        pl. `atr_avg_ref` (fix volatilitás-mérce), `max_spread_atr_ratio`,
        `min_spread_points`. (Korábban csak a `_` kezdetűek maradtak → ezek a defaultra
        estek vissza.) Hiba → None."""
        new = dict(self.params)
        # Beágyazva nincs saját paraméter-űrlap: a lap a Paraméter lap értékeivel
        # épült (`self.params`), és ott is szerkeszted. Nincs mit összeszedni.
        if not self._pentries:
            return new
        for k in self._param_keys:
            raw = self._pentries[k].get().strip()
            orig = self._init_params.get(k)
            try:
                if isinstance(orig, bool):
                    new[k] = raw.lower() in ("true", "1", "igen", "yes")
                elif isinstance(orig, int):
                    new[k] = int(float(raw))
                elif isinstance(orig, float):
                    new[k] = float(raw)
                else:
                    fv = _num(raw)
                    new[k] = fv if (fv is not None and raw != "") else raw
            except ValueError:
                self._status.config(text=_t("bt.bad_value", key=k, value=repr(raw)),
                                    fg=FG_RED)
                return None
        return new

    def _apply_params(self):
        """„Mentés a Paraméterekhez" — az aktuális készletet visszaírja a szülő
        (Stratégia Paraméterek) űrlapjába (nem perzisztál lemezre; azt a szülő
        Mentés gombja teszi). Ha volt friss backtest, az eredményt is átadja."""
        if self._on_apply_params is None:
            return
        params = self._collect_params()
        if params is None:
            return
        try:
            self._on_apply_params(params, self._cur_summary)
            self._status.config(text=_t("bt.applied"), fg=FG_GREEN)
        except Exception as ex:
            self._status.config(text=_t("bt.apply_error", error=ex), fg=FG_RED)

    # ── Adatbetöltés (háttér) ────────────────────────────────────────────────
    def _load_data_async(self):
        self._span_lbl.config(text=_t("bt.loading"), fg=FG_GRAY_DIM)

        def work():
            df15 = df1 = None
            err = None
            try:
                from trading.backtest import load_data_ensure
                # Hiányzó előzmény → MAGÁTÓL letölti (frissen felvett instrumentum)
                def _st(msg):
                    try:
                        self._post(lambda: self._span_lbl.config(
                            text=_t("bt.history", msg=msg), fg=FG_GRAY_DIM))
                    except Exception:
                        pass
                df15, df1, err = load_data_ensure(self.symbol, self.cfg, status=_st)
            except Exception as ex:
                err = str(ex)
            try:
                self._post(lambda: self._data_ready(df15, df1, err))
            except Exception:
                pass

        threading.Thread(target=work, daemon=True, name="BtDlgLoad").start()

    def _data_ready(self, df15, df1, err):
        if self._closed:
            return   # az ablak bezárult a betöltés alatt — ne piszkáljuk a widgeteket
        if err:
            self._span_lbl.config(text=err, fg=FG_RED)
            return
        self._df15, self._df1 = df15, df1
        try:
            lo_ts, hi_ts = df1.index[0], df1.index[-1]
            lo = lo_ts.strftime("%Y-%m-%d")
            hi = hi_ts.strftime("%Y-%m-%d")
            # Alap-időszak: az utolsó ~18 hónap (a régebbi, eltérő piac alapból
            # kimarad — a teljes tartomány látszik és a mezőben bővíthető).
            default_start = max(lo_ts, hi_ts - pd.DateOffset(months=18))
            ds = default_start.strftime("%Y-%m-%d")
            self._span_lbl.config(text=_t("bt.available", lo=lo, hi=hi),
                                  fg=FG_GRAY_DIM)
            # Megjegyzett időszak (ha van) elsőbbséget élvez a ~18 hónap alap fölött.
            if not self._start_var.get():
                self._start_var.set(self._prefs.get("start", ds))
            if not self._end_var.get():
                self._end_var.set(self._prefs.get("end", hi))
        except Exception:
            self._span_lbl.config(text=_t("bt.loaded"), fg=FG_GRAY_DIM)
        # A figyelmeztetés csak MOST számolható: üres mezőknél az adat széleit
        # használja határnak, azok pedig eddig nem voltak meg.
        self._update_training_warning()
        self._btn_start.config(state="normal")

    def _update_training_warning(self):
        """A tanítási ablakkal való átfedés kiírása (üres, ha nincs mit mondani).

        Üres dátummezőnél a backtest a TELJES elérhető adaton fut — a hiányzó
        határt tehát az adat széleivel kell pótolni, különben a leggyakoribb
        eset (mindkét mező üres = minden adat) éppen NEM figyelmeztetne."""
        lbl = getattr(self, "_train_lbl", None)
        if lbl is None:
            return
        from core import training_overlap as _to
        start = self._start_var.get().strip() or None
        end = self._end_var.get().strip() or None
        df = getattr(self, "_df15", None)
        if df is not None and len(df):
            start = start or str(df.index[0])
            end = end or str(df.index[-1])
        ov = _to.for_strategy(self.strategy, self.symbol, self.cfg, start, end)
        msg = _to.message(ov)
        lbl.config(text=msg,
                   fg=FG_RED if _to.severity(ov.get("pct", 0.0)) == "full"
                   else FG_YELLOW)

    def _open_calendar(self, var, anchor):
        """Naptár-popup a `var` (kezdő/záró) dátumhoz, a letöltött history-hoz
        igazított választható tartománnyal."""
        try:
            cur = pd.Timestamp(var.get().strip()).date() if var.get().strip() else None
        except Exception:
            cur = None
        lo = hi = None
        if self._df1 is not None:
            try:
                lo = self._df1.index[0].date()
                hi = self._df1.index[-1].date()
            except Exception:
                pass
        CalendarPopup(self.win, anchor=anchor, initial=cur, lo=lo, hi=hi,
                      on_pick=lambda s: var.set(s), font=self._sf)

    # ── Futtatás ─────────────────────────────────────────────────────────────
    def _start(self):
        if self._running or self._df1 is None:
            return
        params = self._collect_params()
        if params is None:
            return
        self._run_params = params
        self._running = True
        self._stop_flag = threading.Event()
        # A start gomb futás közben MEGSZAKÍTÁS gombbá válik (a _done visszaállítja).
        self._btn_start.config(text=_t("bt.cancel"), state="normal",
                               command=self._cancel)
        if self._on_state:
            try:
                self._on_state(True)
            except Exception:
                pass
        self._status.config(text=_t("bt.running"), fg=FG_GRAY)
        self._pbar.config(value=0.0)
        self._pct_lbl.config(text="0%")
        self._canvas.delete("all")
        for w in self._metrics_frame.winfo_children():
            w.destroy()
        self._grade_lbl.config(text="")
        self._build_lbl.config(text="")
        self._build_csv = None
        self._btn_build_csv.config(state="disabled")

        start = self._start_var.get().strip() or None
        end   = self._end_var.get().strip() or None
        _ibn = _num(self._ib_var.get())            # a mezőből olvasott nyitó összeg
        ib = _ibn if _ibn is not None and _ibn > 0 else self._ib
        rr_spec = self._current_rr_spec()          # az ablakban választott (feltáró) rr
        build_cfg = self._current_build_cfg()      # az ablakban választott (feltáró) építés
        allowed = self._allowed_hours()            # None = minden óra; különben trade_hours
        tcfg = self._run_trading_cfg()             # a `Slotok` mezővel felülírt méretezés
        # ⚠ Beágyazva MINDIG BE: a „modellezze-e" döntés kapunként a Kapuk
        # szakaszban él (`gates_backtest`), és a `effects_for(for_backtest=True)`
        # ott dönti el. Egy fölérendelt mester-kapcsoló elnyomhatná — olyankor a
        # kapu-tábla pipái némán hatástalanok lennének.
        _exec_gates = (True if self._host is not None
                       else bool(self._exec_gates_var.get()))

        # Kényelmi beállítások megjegyzése (per stratégia+pár): időszak + nyitó
        # összeg + slotok. A következő megnyitáskor visszatöltődnek.
        _bprefs.save(self.symbol, self.strategy.name,
                     start=self._start_var.get().strip() or None,
                     end=self._end_var.get().strip() or None,
                     ib=self._ib_var.get().strip() or None,
                     slots=tcfg.get("max_open_slots"))

        stop_flag = self._stop_flag

        def cb(pct, m1_time, balance, n_open, n_closed, tech):
            if self._closed:
                return
            try:
                self._post(lambda: self._on_progress(
                    pct, m1_time, balance, n_open, n_closed, tech))
            except Exception:
                pass

        def work():
            summary, result, err, cancelled = None, None, None, False
            try:
                from trading.backtest import run_pair, signal_series_cached
                # ── Jelölt-lista gyorsítótár (feltáró munka) ────────────────
                # Ebben az ablakban tipikusan a VÉGREHAJTÁST hangolod: SL/TP,
                # rr-preset, slotok, kapuk, nyitó összeg. Ilyenkor a jel-oldal
                # (indikátorok + állapotgépek) változatlan, tehát nem kell újra
                # kiszámolni — mérve 1,7–2,0× a második futástól.
                # A szabályt a `signal_series_cached` őrzi: ha BÁRMI jel-oldali
                # (vagy az óra-szűrő / az időszak) változott, újraépít.
                series, reused = signal_series_cached(
                    self._sig_cache, self.symbol, self._df15, self._df1, params,
                    self.pair_cfg, strategy=self.strategy, test_start=start,
                    test_end=end, allowed_hours=allowed)
                self._sig_cache = series
                if not self._closed:
                    try:
                        self._post(lambda r=reused, n=len(series.signals):
                                       self._show_series_note(r, n))
                    except Exception:
                        pass
                result = run_pair(self.symbol, self._df15, self._df1, params,
                                  self.pair_cfg, tcfg, ib,
                                  strategy=self.strategy, rr=rr_spec,
                                  build=build_cfg, allowed_hours=allowed,
                                  test_start=start, test_end=end,
                                  progress_callback=cb, record_events=True,
                                  stop_flag=stop_flag,
                                  cfg=self.cfg, exec_gates=_exec_gates,
                                  signal_series=series)
                if stop_flag.is_set():
                    # Megszakítva: a részeredményt eldobjuk (nincs összegzés/CSV).
                    cancelled = True
                else:
                    summary = result.summary(ib)
                    from collections import Counter
                    tech = Counter(t.rr_technique for t in result.closed
                                   if getattr(t, "rr_technique", ""))
                    if summary and tech:
                        summary["_rr_tech"] = dict(tech)
                    # MT5 backtest-reprodukció: a belépők CSV-be (BacktestReplayer.mq5
                    # replay). „Amikor futtatok egy backtestet, elkészíti a belépőket."
                    try:
                        from tools.mt5_export import export_mt5_csv
                        from version import BASE_DIR
                        _p = export_mt5_csv(result, self.symbol, rr_spec,
                                            self.pair_cfg, BASE_DIR / "data" / "mt5_backtest")
                        if _p and summary is not None:
                            summary["_mt5_csv"] = _p.name
                    except Exception:
                        pass
                    # Pozícióépítés — tételes CSV (csak ha volt ráépítés). Az ablak
                    # „Építés CSV" gombja ezt nyitja meg (mint a Trials CSV).
                    try:
                        from tools.build_export import export_build_csv
                        from version import BASE_DIR
                        _bp = export_build_csv(result, self.symbol,
                                               BASE_DIR / "data" / "build_csv")
                        if _bp and summary is not None:
                            summary["_build_csv"] = str(_bp)
                    except Exception:
                        pass
            except Exception as ex:
                err = str(ex)
            if self._closed:
                return   # az ablak közben bezárult — ne érintsük a widgeteket
            try:
                self._post(lambda: self._done(summary, result, ib, err, cancelled))
            except Exception:
                pass

        threading.Thread(target=work, daemon=True, name="BtDlgRun").start()

    def _cancel(self):
        """A futó backtest megszakítása (a Megszakítás gomb). A run_pair a részered-
        ménnyel visszatér, a _done „Megszakítva"-ként zár (nem renderel, nincs CSV)."""
        if self._running and self._stop_flag is not None:
            self._stop_flag.set()
            self._btn_start.config(state="disabled")
            try:
                self._status.config(text=_t("bt.cancelling"), fg=FG_YELLOW)
            except Exception:
                pass

    def _show_series_note(self, reused: bool, n_signals: int):
        """A jelölt-lista sorsa — hogy a futás sebessége MAGYARÁZOTT legyen."""
        if self._closed:
            return
        try:
            if reused:
                self._series_lbl.config(
                    text=_t("bt.series_reused", n=n_signals),
                    fg=FG_GREEN)
            else:
                self._series_lbl.config(
                    text=_t("bt.series_recalc", n=n_signals),
                    fg=FG_GRAY_DIM)
        except tk.TclError:
            return

    def _on_progress(self, pct, m1_time, balance, n_open, n_closed, tech):
        if self._closed:
            return   # az ablak bezárult — a widgetek már nem léteznek
        try:
            self._pbar.config(value=pct * 100.0)
            self._pct_lbl.config(text=f"{pct * 100:.0f}%")
            self._live["time"].config(text=str(m1_time)[:16])
            col = FG_GREEN if balance >= 0 else FG_RED
            self._live["balance"].config(text=f"{balance:,.0f}$", fg=col)
            self._live["open"].config(text=str(n_open))
            self._live["closed"].config(text=str(n_closed))
            if tech:
                self._tech_lbl.config(text="Technika: " + ", ".join(
                    f"{_tech_name(k)}×{v}" for k, v in tech.items()))
        except tk.TclError:
            return   # a widgetek közben megsemmisültek (bezárás) — csendben kilép

    def _done(self, summary, result, ib, err, cancelled=False):
        self._running = False
        if self._closed:
            return   # az ablak bezárult — nincs mit frissíteni
        # A gomb visszaáll indító gombbá (a futás közben Megszakítás volt).
        try:
            if self._on_state:
                try:
                    self._on_state(False)
                except Exception:
                    pass
            self._btn_start.config(text=_t("bt.start"), state="normal",
                                   command=self._start)
        except Exception:
            return   # az ablak közben bezárult
        if cancelled:
            self._status.config(text=_t("bt.cancelled"), fg=FG_YELLOW)
            self._pbar.config(value=0.0)
            self._pct_lbl.config(text="0%")
            return
        if err:
            self._status.config(text=_t("bt.error", error=err), fg=FG_RED)
            return
        self._pbar.config(value=100.0)
        self._pct_lbl.config(text="100%")
        tech = (summary or {}).pop("_rr_tech", None) or {}
        _tech_txt = ""
        if tech:
            _tech_txt = _t("bt.tech_used") + ", ".join(
                f"{_tech_name(k)}×{v}" for k, v in tech.items())
        # Építés-CSV útvonala (a metrikák közül kivéve) — a gomb ezt nyitja.
        self._build_csv = (summary or {}).pop("_build_csv", None)
        # MT5 backtest-reprodukció CSV neve (a metrikák közül kivéve).
        _mt5 = (summary or {}).pop("_mt5_csv", None)
        if _mt5:
            _tech_txt = (_tech_txt + "   |   " if _tech_txt else "") + \
                        f"MT5 CSV: data/mt5_backtest/{_mt5}"
        if _tech_txt:
            self._tech_lbl.config(text=_tech_txt)
        self._summary = summary

        # Előző/eredeti futás görgetése (a #4 összevetéshez): a most lecserélt
        # aktuális lesz az „előző"; az első valaha futott az „eredeti".
        self._prev_result, self._prev_summary = self._cur_result, self._cur_summary
        self._cur_result,  self._cur_summary  = result, summary
        if self._orig_result is None and result is not None:
            self._orig_result, self._orig_summary = result, summary

        self._render_metrics(summary)
        self._render_build(summary)
        self._redraw()
        if self._on_run_done:
            try:
                self._on_run_done(result)
            except Exception:
                pass
        # Visszaírás a főképernyőre CSAK ha ugyanazt az rr-t mértük, mint a mentett
        # (fő ablak) rr — különben ez feltáró futtatás, nem szennyezi a mentendőt.
        same_rr = self._rr_key(self._current_rr_spec()) == self._opened_rr_key
        if same_rr and self._on_result and summary:
            try:
                self._on_result(summary)
                self._status.config(text=_t("bt.done_written"),
                                    fg=FG_GREEN)
            except Exception:
                self._status.config(text=_t("bt.done"), fg=FG_GREEN)
        else:
            self._status.config(
                text=_t("bt.done_explore"),
                fg=FG_YELLOW)

    # ── Renderelés ────────────────────────────────────────────────────────────
    def _render_metrics(self, summary):
        for w in self._metrics_frame.winfo_children():
            w.destroy()
        if not summary or summary.get("trades", 0) == 0:
            self._grade_lbl.config(text=_t("bt.grade", grade="—"), fg=FG_GRAY)
            tk.Label(self._metrics_frame, text=_t("bt.no_trades"),
                     bg=BG, fg=FG_YELLOW, font=self._sf).pack(side="left")
            return
        gtxt, gcol, greason = self.strategy.grade(summary, self.cfg)
        self._grade_lbl.config(
            text=_t("bt.grade", grade=gtxt) + (f"   ({greason})" if greason else ""),
            fg=sem_color(gcol))
        mc = metric_colors(summary, self.cfg)
        for label, fn, key in _METRIC_ORDER:
            color = "white" if key is None else mc.get(key, "white")
            cell = tk.Frame(self._metrics_frame, bg=BG)
            cell.pack(side="left", padx=(0, 12))
            tk.Label(cell, text=label, bg=BG, fg=FG_GRAY,
                     font=self._sf).pack(side="left")
            tk.Label(cell, text=fn(summary), bg=BG, fg=sem_color(color),
                     font=self._sf).pack(side="left")

    # ── Pozícióépítés hozadéka ───────────────────────────────────────────────
    def _open_build_csv(self):
        """Az Építés CSV megnyitása az alap alkalmazásban (Windows: Excel) —
        ugyanúgy, mint az optimalizálás Trials CSV-je."""
        if not self._build_csv:
            self._status.config(text=_t("bt.no_build_csv"), fg=FG_YELLOW)
            return
        try:
            import os
            os.startfile(str(self._build_csv))
        except Exception as ex:
            self._status.config(text=_t("bt.open_error", error=ex), fg=FG_RED)

    def _render_build(self, summary):
        """Hány ráépítés (adalék-láb) nyílt az Építés hatására, hány kötésen, és
        mennyit hozott KIZÁRÓLAG az adalék — R-ben (az induló láb kockázatához
        mérve) és $-ban. Ha az Építés be volt kapcsolva, de nem lett adalék, azt
        is kiírjuk (a modellezés csak Ki-preset + Auto / R-alapú Kézi mellett fut)."""
        adds = int((summary or {}).get("build_adds", 0) or 0)
        self._btn_build_csv.config(state=("normal" if self._build_csv else "disabled"))
        if not adds:
            on = self._build_mode_name.get() != _bst.NAME[_bst.MODE_OFF]
            self._build_lbl.config(
                text=(_t("bt.build_none") if on else ""),
                fg=FG_GRAY_DIM)
            return
        n_tr = int(summary.get("build_trades", 0) or 0)
        pkg  = float(summary.get("build_pkg_pnl", 0.0) or 0.0)
        pkgr = float(summary.get("build_pkg_r", 0.0) or 0.0)
        r    = float(summary.get("build_r", 0.0) or 0.0)
        pnl  = float(summary.get("build_pnl", 0.0) or 0.0)
        per  = (pkgr / n_tr) if n_tr else 0.0
        self._build_lbl.config(
            text=_t("bt.build_line", adds=adds, trades=n_tr,
                    pkg=_fmtnum(f"{pkg:+.0f}"), pkgr=_fmtnum(f"{pkgr:+.1f}"),
                    per=_fmtnum(f"{per:+.2f}"), pnl=_fmtnum(f"{pnl:+.0f}"),
                    r=_fmtnum(f"{r:+.1f}")),
            fg=(FG_GREEN if pkg > 0 else (FG_RED if pkg < 0 else FG_YELLOW)))

    # ── Összevetés (előző/eredeti) ────────────────────────────────────────────
    def _reference(self):
        """A kiválasztott összevetési (referencia) futás (result, summary, címke).
        (None, None, "") ha nincs / „Nincs" van választva."""
        _lbl = self._overlay_mode.get()
        mode = next((c for c, lb in self._overlay_choices if lb == _lbl), "none")
        if mode == "prev":
            return self._prev_result, self._prev_summary, _lbl
        if mode == "orig":
            return self._orig_result, self._orig_summary, _lbl
        return None, None, ""

    def _on_overlay_change(self):
        self._redraw()

    def _fmt_ref_metrics(self, summary, label):
        if not summary or summary.get("trades", 0) == 0:
            return ""
        pf = summary.get("profit_factor", 0)
        pf_s = "∞" if pf == float("inf") else f"{pf:.2f}"
        return (f"{label}: Trade {int(summary.get('trades', 0))} · "
                f"Win {summary.get('win_rate', 0) * 100:.0f}% · "
                f"P&L {summary.get('total_pnl', 0):+.0f}$ · PF {pf_s}")

    @staticmethod
    def _start_bal(summary, fallback):
        """A futás TÉNYLEGES nyitó egyenlege a summary-ből: final_balance − total_pnl
        (= initial_balance). Így a görbe a valós tőkéről indul, nem a config 1000-ről."""
        if summary and "final_balance" in summary and "total_pnl" in summary:
            try:
                return float(summary["final_balance"]) - float(summary["total_pnl"])
            except (TypeError, ValueError):
                pass
        return fallback

    def _redraw(self):
        """Az egyenleg-görbe újrarajzolása: az aktuális futás + (opcionálisan) a
        kiválasztott referencia (előző/eredeti) HALVÁNYAN, közös skálán."""
        ref_result, ref_summary, ref_label = self._reference()
        # Minden görbe a SAJÁT futásának nyitó egyenlegéről indul (a nyitó összeg
        # mezővel állítható); a config 1000 csak fallback, ha nincs summary.
        cur_ib = self._start_bal(self._cur_summary, self._ib)
        ref_ib = self._start_bal(ref_summary, cur_ib)
        # Ha a referencia MÁS nyitó összegen futott, az összevetés félrevezető (közös
        # abszolút tengelyen távol kerülnének) → kihagyjuk, de az előzményt megtartjuk
        # (ugyanarra a tőkére visszaállítva az összevetés magától visszatér).
        if ref_result is not None and abs(ref_ib - cur_ib) > 0.005:
            self._ref_metrics_lbl.config(
                text=_t("bt.ref_mismatch", label=ref_label,
                        balance=_fmtnum(f"{ref_ib:,.0f}")))
            ref_result = None
        else:
            self._ref_metrics_lbl.config(
                text=self._fmt_ref_metrics(ref_summary, ref_label))
        self._draw_equity(self._cur_result, cur_ib, ref_result, ref_ib)

    def _draw_equity(self, result, ib, ref_result=None, ref_ib=None):
        """Egyenleg-görbe a balance_curve-ből (matplotlib nélkül). A `ref_result`
        (ha van) HALVÁNYAN, ugyanazon a skálán rajzolódik az összevetéshez. Az `ib`
        az aktuális, a `ref_ib` a referencia futás nyitó egyenlege (eltérhetnek)."""
        c = self._canvas
        c.delete("all")
        W = int(c.cget("width")); H = int(c.cget("height"))
        pad = 6
        if ref_ib is None:
            ref_ib = ib

        def curve_ys(res, base):
            cur = getattr(res, "balance_curve", None) or [] if res is not None else []
            return [base] + [b for _, b in cur] if len(cur) >= 1 else []

        ys_cur = curve_ys(result, ib)
        ys_ref = curve_ys(ref_result, ref_ib)
        if len(ys_cur) < 2 and len(ys_ref) < 2:
            c.create_text(W // 2, H // 2, text=_t("bt.no_curve"),
                          fill=FG_GRAY_DIM, font=self._sf)
            return

        # Közös skála (mindkét görbét ugyanabba a tartományba rajzoljuk).
        allv = [v for v in (ys_cur + ys_ref)] or [ib]
        lo, hi = min(allv), max(allv)
        rng = (hi - lo) or 1.0

        def py(v):
            return H - pad - (H - 2 * pad) * (v - lo) / rng

        def draw(ys, color, width, dash=None):
            if len(ys) < 2:
                return
            n = len(ys)
            pts = []
            for i, v in enumerate(ys):
                x = pad + (W - 2 * pad) * i / (n - 1)
                pts += [x, py(v)]
            if dash:
                c.create_line(*pts, fill=color, width=width, smooth=False, dash=dash)
            else:
                c.create_line(*pts, fill=color, width=width, smooth=False)

        # Nulla-referencia (kezdő egyenleg) vonala
        if lo <= ib <= hi:
            y0 = py(ib)
            c.create_line(pad, y0, W - pad, y0, fill=FG_GRAY_DIM, dash=(2, 3))
        # Referencia (előző/eredeti) HALVÁNYAN, szaggatva — alulra.
        draw(ys_ref, FG_GRAY_DIM, 1, dash=(3, 3))
        # Aktuális futás — élénken, felülre.
        if len(ys_cur) >= 2:
            final = ys_cur[-1]
            line_col = FG_GREEN if final >= ib else FG_RED
            draw(ys_cur, line_col, 2)

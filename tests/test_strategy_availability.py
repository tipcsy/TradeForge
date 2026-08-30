"""A stratégia-felsorolás (config) es a live2 <-> motor PARITAS.

KET, egy tobol fakado hiba — ezert egy fajlban:

  1. A `config.json` nem mondta meg, MI LETEZIK. Az `available_strategies` kulcs
     TORLODOTT, ha minden strategia be volt kapcsolva („ne szennyezze a configot"),
     a kikapcsolt pedig egyszeruen kimaradt a listabol. Ket strategianal zavaro,
     4-5-nel hasznalhatatlan. Megoldas: TERKEP alak, amit a mentes MINDIG kiir,
     a teljes keszlettel.

  2. A live2 sor MINDEN paron az `available_strategies`-bol dolgozik (kell is:
     kulonben nem allnanak egy vonalban az oszlopok), a MOTOR viszont a par sajat
     `strategies` listajabol. E nelkul egy nem engedelyezett strategia blokkja
     ugyanugy nezett ki, Play gombbal — a Play `run_state`-be `live`-ot irt, a sor
     futonak mutatta, a motor pedig SOHA nem futtatta.

A motor keplete (`live_trader.run`):  `_active = _enabled & _intent`
A feluleté (`gui._strategy_live`) ezt SZO SZERINT kell hogy tukrozze.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


import json

from core import run_state as rs
from strategy import (available_strategy_names, strategy_availability,
                      enabled_strategy_names, registered_strategy_names)

REG = registered_strategy_names()
check("van legalabb ket regisztralt strategia (a teszt erre epul)",
      len(REG) >= 2, str(REG))

# ══ 1. available_strategies — TERKEP alak ═════════════════════════════════

# ⚠ MINDEN regisztraltat felsorolunk: ami NEM szerepel a terkepben, az a vaz
# szabalya szerint ELERHETO — egy uj strategia-modul kulonben elrontana a merest
# (2026-08-08: a bollinger_squeeze_breakout bevezetesekor pont ez tortent).
CFG_MAP = {"strategy": {"name": "wpr_sma"},
           "available_strategies": {**{n: False for n in REG},
                                    "wpr_sma": True, "ml_ai": False}}
check("terkep: a false-ra allitott strategia KIMARAD",
      available_strategy_names(CFG_MAP) == ["wpr_sma"],
      str(available_strategy_names(CFG_MAP)))

CFG_MAP_BOTH = {"strategy": {"name": "wpr_sma"},
                "available_strategies": {"ml_ai": True, "wpr_sma": True}}
check("terkep: a CONFIG sorrendje szamit (nem az abece)",
      available_strategy_names(CFG_MAP_BOTH)[:2] == ["ml_ai", "wpr_sma"],
      str(available_strategy_names(CFG_MAP_BOTH)))

# Egy frissen hozzaadott strategia-modul NE tunjon el nemán csak azert, mert a
# config meg nem tud rola. Kikapcsolni KIFEJEZETTEN kell (false).
CFG_PARTIAL = {"strategy": {"name": "wpr_sma"},
               "available_strategies": {"wpr_sma": True}}
check("terkep: a configban NEM szereplo (uj) strategia ELERHETO marad",
      set(available_strategy_names(CFG_PARTIAL)) == set(REG),
      str(available_strategy_names(CFG_PARTIAL)))

CFG_ALL_FALSE = {"strategy": {"name": "wpr_sma"},
                 "available_strategies": {n: False for n in REG}}
check("terkep: csupa false -> visszaesik az OSSZESRE (nem ures dashboard)",
      set(available_strategy_names(CFG_ALL_FALSE)) == set(REG),
      str(available_strategy_names(CFG_ALL_FALSE)))

# ══ 2. A REGI, lista alak valtozatlanul mukodik ═══════════════════════════

CFG_LIST = {"strategy": {"name": "wpr_sma"},
            "available_strategies": ["ml_ai"]}
check("lista (regi): whitelist-kent mukodik tovabb",
      available_strategy_names(CFG_LIST) == ["ml_ai"],
      str(available_strategy_names(CFG_LIST)))

CFG_NONE = {"strategy": {"name": "wpr_sma"}}
_none = available_strategy_names(CFG_NONE)
check("hianyzo kulcs: az OSSZES, az elsodleges ELOL",
      set(_none) == set(REG) and _none[0] == "wpr_sma", str(_none))

CFG_EMPTY = {"strategy": {"name": "wpr_sma"}, "available_strategies": []}
check("ures lista: az OSSZES (visszafele kompatibilis)",
      set(available_strategy_names(CFG_EMPTY)) == set(REG))

# ══ 3. strategy_availability — a TELJES keszlet, ezt irja ki a ⚙ ══════════

av = strategy_availability(CFG_MAP)
check("strategy_availability: MINDEN regisztralt szerepel benne",
      set(av) == set(REG), str(av))
check("strategy_availability: a kikapcsolt is benne van, False-szal",
      av.get("ml_ai") is False and av.get("wpr_sma") is True, str(av))
av_none = strategy_availability(CFG_NONE)
check("strategy_availability: kulcs nelkul mind True",
      all(av_none.values()) and set(av_none) == set(REG), str(av_none))

# ══ 4. A ⚙ Beallitas mentese: kiirja, nem torli ═══════════════════════════

src = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
check("a mentes NEM torli tobbe az available_strategies kulcsot",
      'new.pop("available_strategies"' not in src)
# v2.9.0 ota a jelolonegyzetek helyett KET LISTA all (Beallitasok -> Strategiak
# ful): a bekapcsoltak SORRENDBEN, a kikapcsoltak utanuk. A kulcs tovabbra is a
# TELJES keszletet sorolja fel — csak igy derul ki a fajlbol, MI LETEZIK.
check("a mentes a TELJES keszletet irja (bekapcsoltak + kikapcsoltak)",
      "chosen_av = {n: True for n in _on}" in src
      and "for n in _strat_ed.disabled():" in src)
check("a mentes megtagadja az ures keszletet", "if not _on:" in src)
check("a bekapcsoltak SORRENDJE a listabol jon (az lesz az oszlop-sorrend)",
      "_on = _strat_ed.get()" in src)

# ══ 5. A leszallitott config-fajlok felsoroljak a keszletet ═══════════════

for fname in ("config.json", "config.example.json"):
    p = ROOT / fname
    if not p.exists():
        check(f"{fname} letezik", False)
        continue
    d = json.loads(p.read_text(encoding="utf-8"))
    a = d.get("available_strategies")
    check(f"{fname}: van available_strategies", a is not None)
    check(f"{fname}: TERKEP alak (a kikapcsolt is latszana)",
          isinstance(a, dict), type(a).__name__)
    if isinstance(a, dict):
        check(f"{fname}: MINDEN regisztralt strategiat felsorol",
              set(a) == set(REG), str(sorted(a)))

# ══ 6. P0 — a felulet keplete = a motore ══════════════════════════════════
#
# A hibas allapot, ami a leletet adta: a par CSAK wpr_sma-t engedelyez, de a
# `run_state`-ben ott maradt egy korabbi `ml_ai: live` bejegyzes.

CFG_P0 = {"strategy": {"name": "wpr_sma"},
          "available_strategies": {"wpr_sma": True, "ml_ai": True},
          "pairs": {"X": {"enabled": True,
                          "strategies": ["wpr_sma"],
                          "run_state": {"wpr_sma": "live", "ml_ai": "live"}}}}

avail = available_strategy_names(CFG_P0)
enabled = enabled_strategy_names(CFG_P0, "X")
intent = rs.live_strategies(CFG_P0, "X", avail)
engine_active = sorted(set(enabled) & set(rs.live_strategies(CFG_P0, "X", enabled)))

check("a lelet all: a SZANDEK szerint az ml_ai 'live'",
      "ml_ai" in intent, str(intent))
check("a lelet all: a MOTOR viszont csak a wpr_sma-t futtatja",
      engine_active == ["wpr_sma"], str(engine_active))


def strategy_live(cfg, symbol, name):
    """A `gui._strategy_live` LOGIKAJA, tkinter nelkul. Ha ez elteveluk a
    motoretol, a sor ismet hazudni fog."""
    _enabled = enabled_strategy_names(cfg, symbol) or []
    if name not in _enabled:
        return False
    return name in (rs.live_strategies(cfg, symbol, _enabled) or [])


check("JAVITAS: a nem engedelyezett strategia NEM latszik futonak",
      strategy_live(CFG_P0, "X", "ml_ai") is False)
check("az engedelyezett+live strategia tovabbra is futonak latszik",
      strategy_live(CFG_P0, "X", "wpr_sma") is True)
check("a felulet es a motor UGYANAZT mondja",
      sorted(n for n in avail if strategy_live(CFG_P0, "X", n)) == engine_active)

# A `gui.py` tenylegesen ezt a keplet hasznalja-e (forras-szintu orzes: a
# metodus tkinter-gyokeret igenyelne, a REGRESSZIO viszont pont az, ha a
# `_enabled` szures kikerul belole).
# A `gui.py`-ban KET osztaly is definial `_strategy_live`-ot (OptimizerController =
# az OPT kapuja; DashboardWindow = a sor Play/Stop jelzese). MINDKETTONEK a motor
# kepletet kell kovetnie, ezert mindkettot ellenorizzuk — a nevre valo naiv
# `split` a masikat merne.
_slive_all = [b.split("\n    def ")[0] for b in src.split("def _strategy_live")[1:]]
check("gui.py: ket _strategy_live van (OPT-kapu + sor-jelzes)", len(_slive_all) == 2,
      str(len(_slive_all)))
check("MINDKET _strategy_live a par listajabol szur (a motor keplete)",
      all("enabled_strategy_names" in b for b in _slive_all))
_slive = next((b for b in _slive_all if "name: str" in b), "")
check("_strategy_live: a par listajabol dolgozik (nem az available-bol)",
      "def _strategy_live" in src
      and "_enabled = enabled_strategy_names(self.cfg, symbol) or []" in _slive)
check("_strategy_live: a nem engedelyezettre azonnal False",
      "if name not in _enabled:" in _slive)
check("_strategy_live: NEM az available_strategies-bol dolgozik tobbe",
      "_live2_strategies" not in _slive)
check("van _strategy_enabled seam a sorhoz", "def _strategy_enabled" in src)
check("_live2_rows atadja az enabled_of-ot a row_source-nak",
      "enabled_of=self._strategy_enabled" in src)

# ══ 7. P0 — a Play megtagadja a nem engedelyezett strategiat ══════════════

# ⚠ A teljes fuggvenytorzs (a kovetkezo `def`-ig): a rogzitett karakter-ablak
# a magyarazo kommentektol elcsuszott, es a teszt NEM a hosszra kivancsi.
_NEXT_DEF = chr(10) + "    def "
_start = src.split("def _start_strategy")[1].split(_NEXT_DEF)[0]

check("_start_strategy: ellenorzi az engedelyezettseget",
      "if not self._strategy_enabled(symbol, name):" in _start)
# ⚠ A kapu az ALLAPOT-IRAS elott legyen: kulonben a `run_state` `live`-ban
# ragadna a configban egy olyan strategiara, amit a motor sosem futtat.
# (A params-ellenorzes MEGSZUNT: mentett keszlet nelkul a strategia SAJAT
# alapertekeivel indul — lasd `live_trader.default_params`.)
check("_start_strategy: a kapu az allapot-iras ELOTT van (nem ragad be a run_state)",
      _start.index("_strategy_enabled") < _start.index("_rs.set_state"))
check("_start_strategy: NINCS tobbe params-fajl tiltas",
      "nincs paraméterkészlet" not in _start, _start[:200])
# ⚠ A felirat a nyelvi katalogusban van (i18n) — a forrasban a KULCS all.
import json as _json
_HU_CAT = _json.loads((ROOT / "lang" / "hu.json").read_text(encoding="utf-8"))
check("_start_strategy: beszedes uzenetet ad (nem nema no-op)",
      "gui.ctrl.not_enabled" in _start
      and "nincs engedélyezve ezen az"
      in _HU_CAT.get("gui.ctrl.not_enabled", ""))

# ══ 8. row_source: az 'enabled' atkerul a sorba, es metszi a 'live'-ot ════

from dashboard import row_source as rsrc


class _DS:
    bid = ask = None
    spread_pts = None
    atr_price = None
    tf_align_signs = []
    tf_align_labels = []
    tf_align_dir = None
    market_strategy = None
    market_state_label = ""
    strategy_cells = {}
    daily_by_strategy = {}


row = rsrc.row_data("X", _DS(), ["wpr_sma", "ml_ai"], CFG_P0, {}, {},
                    live_of=lambda s, n: True,          # SZANDEK: mindketto live
                    enabled_of=lambda s, n: n == "wpr_sma")
by_name = {s["name"]: s for s in row["strategies"]}
check("row_data: az 'enabled' megjelenik a strategia-blokkban",
      by_name["wpr_sma"]["enabled"] is True and by_name["ml_ai"]["enabled"] is False)
check("row_data: a nem engedelyezett blokk NEM tunik el (oszlop-egyvonal)",
      len(row["strategies"]) == 2, str(list(by_name)))
check("row_data: a 'live' metszve van az 'enabled'-del",
      by_name["wpr_sma"]["live"] is True and by_name["ml_ai"]["live"] is False)

row_default = rsrc.row_data("X", _DS(), ["wpr_sma"], CFG_P0, {}, {})
check("row_data: enabled_of nelkul az alap True (visszafele kompatibilis)",
      row_default["strategies"][0]["enabled"] is True)

# ══ 9. live_row: a Play/Stop halvany es tetlen, ha nincs engedelyezve ═════

from dashboard import live_row as lr
from dashboard.theme import FG_GRAY_DIM, FG_GREEN, FG_RED

# A glifakat NEVEN nevezzuk (a teszt-nevek ASCII-k: a Windows-konzol cp1250).
PLAY, STOP, IDLE = "▶", "■", "–"
check("_run_text: engedelyezett + all -> zold PLAY",
      lr._run_text({"enabled": True, "live": False}) == (PLAY, FG_GREEN))
check("_run_text: engedelyezett + fut -> piros STOP",
      lr._run_text({"enabled": True, "live": True}) == (STOP, FG_RED))
check("_run_text: NEM engedelyezett -> halvany gondolatjel",
      lr._run_text({"enabled": False, "live": False}) == (IDLE, FG_GRAY_DIM))
check("_run_text: a 'live' nem irhatja felul az engedelyezettseget",
      lr._run_text({"enabled": False, "live": True}) == (IDLE, FG_GRAY_DIM))
check("_run_text: hianyzo 'enabled' -> a regi viselkedes (True)",
      lr._run_text({"live": True}) == (STOP, FG_RED))

lsrc = (ROOT / "dashboard" / "live_row.py").read_text(encoding="utf-8")
check("a demo-szerzodes tartalmazza az 'enabled' kulcsot",
      '"enabled": True' in lsrc)

# A RAJZOLAS v2.7.0 ota a vaszon-tablae (a widget-alapu `LiveRow` megszunt), de
# a KET RECEPT valtozatlan — es epp ezert kell orizni oket:
#   • a KOTES a halvany vezerlon is megmarad (a hivo kiirja az OKOT),
#   • a KEZ-KURZOR viszont CSAK az aktivon (kulonben azt igerne, hogy tesz valamit).
import tkinter as _tkc
_tkok = True
try:
    _p = _tkc.Tk(); _p.destroy()
except Exception:
    _tkok = False

if _tkok:
    from dashboard import canvas_table as _ctb
    from dashboard import theme as _thm
    _r = _tkc.Tk(); _r.withdraw()
    _thm._FONTS.clear()
    _rowd = lr.demo_row()
    _rowd["strategies"][0]["enabled"] = False        # HALVANY Play
    _rowd["strategies"][0]["on_toggle"] = lambda: None
    _rowd["strategies"][1]["enabled"] = True         # AKTIV Play
    _rowd["strategies"][1]["on_toggle"] = lambda: None
    _t = _ctb.CanvasTable(_r, _thm.fonts(), rows=[_rowd], collapsed={})
    _t.frame.pack(); _r.update_idletasks()
    _n0 = _rowd["strategies"][0]["name"]
    _n1 = _rowd["strategies"][1]["name"]
    check("a Play/Stop KOTESE a HALVANY vezerlon is megmarad (kiirhassuk az okot)",
          (0, f"{_n0}|ctrl", "run") in _t.clickable(),
          str(sorted(k for k in _t.clickable() if "ctrl" in str(k))))
    _bc = _t._bc["mid"]

    # ⚠ A KEZ-KURZORT MERJUK, NEM A KOTES LETET. A halvany vezerlon MOSTANTOL
    # VAN `<Enter>` kotés — a BUBOREK-e, ami kattintas nelkul kiirja, miert
    # tetlen. Kez-kurzor viszont tovabbra sem jar neki: az azt igerne, hogy most
    # tenni fog valamit. A ket dolog ugyanazt az esemenyt hallgatja, ezert a
    # tabla KULON nyilvantartja, mely tagek kaptak kurzort (`_hand_tags`).
    def _has_cursor(n):
        return f"c0_{n}|ctrl_run" in _t._hand_tags

    check("a nem engedelyezett Play-en NINCS kez-kurzor", not _has_cursor(_n0))
    check("...az engedelyezetten viszont VAN", _has_cursor(_n1))
    _csrc = (ROOT / "dashboard" / "canvas_cells.py").read_text(encoding="utf-8")
    check("a cella-modell a _run_text-et hasznalja (nem csuszik szet)",
          "_lr._run_text(st)" in _csrc)
    _r.destroy()

# ══ 10. FUNKCIONALIS: valodi DashboardWindow (tkinter) ═══════════════════
#
# A fentiek a LOGIKAT es a forrast orzik. Itt a tenyleges felulet fut: a Play
# megtagadasa es a ⚙ mentes ugyanaz a ket ut, amit a felhasznalo hasznal.

import copy
import tempfile

try:
    import tkinter as _tk
    _tk.Tk().destroy()
    HAS_TK = True
except Exception as _e:
    HAS_TK = False
    print(f"SKIP  tkinter nem elerheto ({_e}) — a felulet-tesztek kimaradnak")

if HAS_TK:
    import dashboard.gui as G
    from dashboard import theme as _t
    from trading.live_trader import PairDashboardState

    BASE = {
        "strategy": {"name": "wpr_sma"},
        # ⚠ MINDEN regisztraltat felsorolunk (ami kimarad, az ELERHETO) — igy a
        # teszt akkor is azt meri, amit akar, ha uj strategia-modul kerul a
        # projektbe. Az uj modul itt szandekosan `false`.
        "available_strategies": {**{n: False for n in REG},
                                 "wpr_sma": True, "ml_ai": True},
        "trading": {"max_open_slots": 4},
        "pairs": {
            # A LELET allapota: a paron CSAK wpr_sma aktiv, de a run_state-ben
            # ott maradt egy korabbi `ml_ai: live` bejegyzes.
            "GOLD": {"enabled": True, "point_size": 0.01,
                     "strategies": ["wpr_sma"],
                     "run_state": {"wpr_sma": "live", "ml_ai": "live"}},
        },
    }

    w = None
    try:
        cfg = copy.deepcopy(BASE)
        _t._FONTS.clear()
        G.DashboardWindow._start_refresh_loops = lambda self: None
        G.DashboardWindow._start_bg_poller = lambda self: None
        G.DashboardWindow._poll_mt5 = lambda self: None
        G.DashboardWindow._ensure_pool = lambda self: None
        saves = []
        G.DashboardWindow._save_main_config = lambda self: saves.append(1)
        ds = PairDashboardState(symbol="GOLD", trained=True, enabled=True)
        ds.digits, ds.bid, ds.ask = 2, 2000.0, 2000.5
        w = G.DashboardWindow(cfg, {"GOLD": ds}, {"GOLD": "LIVE"}, {},
                              on_play_pair=None, on_stop_pair=None)
        w.root.withdraw()
        w.root.update_idletasks()

        check("felulet: az ml_ai NINCS engedelyezve a paron",
              w._strategy_enabled("GOLD", "ml_ai") is False)
        check("felulet: a wpr_sma engedelyezve van",
              w._strategy_enabled("GOLD", "wpr_sma") is True)
        check("felulet: az ml_ai NEM latszik futonak (a stale run_state ellenere)",
              w._strategy_live("GOLD", "ml_ai") is False)
        check("felulet: a wpr_sma futonak latszik",
              w._strategy_live("GOLD", "wpr_sma") is True)

        # A Play a nem engedelyezett strategian: NEM ment, NEM allit allapotot.
        saves.clear()
        _before = copy.deepcopy(cfg["pairs"]["GOLD"]["run_state"])
        w._handle_run_strategy("GOLD", "ml_ai")
        check("Play a nem engedelyezetten: NINCS config-mentes (nema no-op helyett)",
              saves == [], str(saves))
        check("Play a nem engedelyezetten: a run_state VALTOZATLAN",
              cfg["pairs"]["GOLD"]["run_state"] == _before,
              str(cfg["pairs"]["GOLD"]["run_state"]))

        # A sor adata: a blokk megvan, de tetlen.
        rows = w._live2_rows()
        _g = next((r for r in rows if r["symbol"] == "GOLD"), None)
        check("a sor eloall", _g is not None)
        if _g:
            _by = {s["name"]: s for s in _g["strategies"]}
            # A sor az ELERHETO strategiakat mutatja (oszlop-egyvonal). Egy uj,
            # `false`-ra allitott modul NEM jelenik meg — ezt is allitjuk.
            check("a sor a ket elerheto strategiat mutatja (oszlop-egyvonal)",
                  {"wpr_sma", "ml_ai"} <= set(_by), str(sorted(_by)))
            check("a `false`-ra allitott uj strategia NEM jelenik meg",
                  "bollinger_squeeze_breakout" not in _by, str(sorted(_by)))
            check("a sorban az ml_ai blokk 'enabled': False",
                  _by["ml_ai"]["enabled"] is False)
            check("a sorban az ml_ai NEM 'live'", _by["ml_ai"]["live"] is False)
            check("a sorban a wpr_sma 'live'", _by["wpr_sma"]["live"] is True)
            check("a nem engedelyezett blokk OPT-ja HASZNALHATO marad "
                  "(optimalizalj, mielott bekapcsolod)",
                  _by["ml_ai"]["opt_enabled"] is True)

        # ── A ⚙ Beallitas mentese: a TELJES keszlet kerul a fajlba ────────
        tmp = Path(tempfile.mkdtemp())
        _root_orig = G.ROOT
        try:
            G.ROOT = tmp
            w._show_settings()
            w.root.update_idletasks()
            # A megnyilt Toplevel „Mentes" gombjat hivjuk (a felhasznalo utja).
            tops = [c for c in w.root.winfo_children()
                    if isinstance(c, _tk.Toplevel) and "config.json" in c.title()]
            check("a ⚙ Beallitas ablak megnyilt", len(tops) == 1, str(len(tops)))
            if tops:
                btns = []

                def _walk(wd):
                    for c in wd.winfo_children():
                        if isinstance(c, _tk.Button):
                            btns.append(c)
                        _walk(c)
                _walk(tops[0])
                # v2.9.0: jelolonegyzetek helyett KET LISTA (Beallitasok ->
                # Strategiak ful). A keszlet UGYANAZ: minden regisztralt
                # strategia szerepel — a bekapcsoltak jobbra, a kikapcsoltak
                # balra —, kulonben a kikapcsolt strategia elerhetetlenne valna.
                _items = []

                def _walk_lb(wd):
                    for c in wd.winfo_children():
                        if isinstance(c, _tk.Listbox):
                            _items.extend(c.get(0, "end"))
                        _walk_lb(c)
                _walk_lb(tops[0])
                check("a ⚙ MINDEN regisztralt strategiat felkinal",
                      set(REG) <= set(_items), str(sorted(set(_items))))
                save_btn = next((b for b in btns if b.cget("text") == "Mentés"), None)
                check("van Mentes gomb", save_btn is not None)
                if save_btn is not None:
                    save_btn.invoke()
                    w.root.update_idletasks()
                    written = json.loads((tmp / "config.json").read_text(
                        encoding="utf-8"))
                    a = written.get("available_strategies")
                    check("a mentett config.json TERKEP alakban irja ki",
                          isinstance(a, dict), type(a).__name__)
                    check("a mentett config.json a TELJES keszletet felsorolja",
                          isinstance(a, dict) and set(a) == set(REG), str(a))
        finally:
            G.ROOT = _root_orig
            for c in list(w.root.winfo_children()):
                if isinstance(c, _tk.Toplevel):
                    try:
                        c.grab_release()
                    except Exception:
                        pass
                    c.destroy()
    finally:
        if w is not None:
            w.root.destroy()

# ══ A KIKAPCSOLT STRATEGIA NEM FUTHAT ═══════════════════════════════════════
# ⚠ ELESBEN MEGTORTENT (2026-08-23). A felhasznalo kivette a bollingert az aktiv
# strategiak kozul (`available_strategies.bollinger_squeeze_breakout = false`), a
# MOTOR viszont tovabbra is futtatta 9 paron: az `enabled_strategy_names` KIZAROLAG
# a par `strategies` listajat nezte, a globalis kapcsolot nem. A feluleten kozben
# oszlopa sem volt (`available_strategy_names` szurt), tehat sem elinditani, sem
# leallitani nem lehetett — „sem live, sem off, semmi", mikozben kereskedhetett.
#
# A ket lista JELENTESE kulon: a per-par lista a SZANDEK, a globalis kapcsolo a
# LEHETOSEG. A motor a kettő METSZETEN fut.
from strategy import enabled_strategy_names as _ensn2, strategies_for as _sf2

_cfg_off = {
    "available_strategies": {"wpr_sma": True, "bollinger_squeeze_breakout": False},
    "strategy": {"name": "wpr_sma"},
    "pairs": {"X": {"strategies": ["wpr_sma", "bollinger_squeeze_breakout"]}},
}
check("a globalisan KIKAPCSOLT strategia kimarad a motor listajabol",
      _ensn2(_cfg_off, "X") == ["wpr_sma"], str(_ensn2(_cfg_off, "X")))
check("...a strategies_for is ezt adja",
      [s.name for s in _sf2(_cfg_off, "X")] == ["wpr_sma"],
      str([s.name for s in _sf2(_cfg_off, "X")]))

# ⚠ Bekapcsolva viszont FUT — a szures nem tunteti el a valodi valasztast.
_cfg_on = {**_cfg_off, "available_strategies":
           {"wpr_sma": True, "bollinger_squeeze_breakout": True}}
check("bekapcsolva mindketto fut",
      _ensn2(_cfg_on, "X") == ["wpr_sma", "bollinger_squeeze_breakout"],
      str(_ensn2(_cfg_on, "X")))

# ⚠ A megjelenites es a futtatas EGYEZZEN: ami nem elerheto, az nem is futhat.
from strategy import available_strategy_names as _asn2
check("a motor listaja RESZHALMAZA az elerhetoknek",
      set(_ensn2(_cfg_off, "X")) <= set(_asn2(_cfg_off)),
      f"{_ensn2(_cfg_off,'X')} vs {_asn2(_cfg_off)}")

# ⚠ HA MINDEN KIVALASZTOTT KI VAN KAPCSOLVA, az eredmeny URES — es ez a HELYES
# valasz: „ezen a paron nincs mit futtatni". Az elsodlegesre visszaesni azt
# jelentene, hogy olyan strategiat inditunk, amit a felhasznalo erre a parra
# SOSEM valasztott ki. (Az elso valtozatom ezt rontotta el; a CLI tesztje fogta
# meg: ott a „nincs mit futtatni" beszedes figyelmeztetes, nem nema helyettesites.)
_cfg_all_off = {**_cfg_off,
                "pairs": {"X": {"strategies": ["bollinger_squeeze_breakout"]}}}
check("csupa kikapcsolt -> URES (nem helyettesitunk masikkal)",
      _ensn2(_cfg_all_off, "X") == [], str(_ensn2(_cfg_all_off, "X")))
# ...a HIANYZO lista viszont tovabbra is az elsodleges (visszafele kompatibilis).
_cfg_none = {**_cfg_off, "pairs": {"X": {}}}
check("hianyzo lista -> az elsodleges (valtozatlan)",
      _ensn2(_cfg_none, "X") == ["wpr_sma"], str(_ensn2(_cfg_none, "X")))

# Hianyzo `available_strategies` -> MINDEN regisztralt elerheto (visszafele komp.)
_cfg_no_key = {"strategy": {"name": "wpr_sma"},
               "pairs": {"X": {"strategies": ["wpr_sma", "bollinger_squeeze_breakout"]}}}
check("hianyzo kapcsolo-blokk -> valtozatlan viselkedes",
      _ensn2(_cfg_no_key, "X") == ["wpr_sma", "bollinger_squeeze_breakout"],
      str(_ensn2(_cfg_no_key, "X")))


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

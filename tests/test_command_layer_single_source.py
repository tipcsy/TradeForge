"""EGY parancs-reteg — a felulet, a konzol, a TUI es a Telegram ugyanott ir.

⚠ A LELET (2026-09-18). A `core/console_cmd.py` sajat nyito bekezdese szerint a
parancsok azert laknak egy helyen, mert kulonben „harom forras romlana el
kulon". A felulet viszont NEM ezen ment: a `dashboard/gui.py` hat helyen
kozvetlenul irta a `core.run_state`-et, es ezzel egy NEGYEDIK forras volt. A ket
oldal EL IS CSUSZOTT — harom merheto ponton:

  1. **Optimalizalas alatti INDITAS.** A felulet megtagadta (a futas vegen a
     strategia parameterfajlja irodik felul), a konzol/TUI/Telegram engedte.
  2. **Hangolatlan indulas jelzese.** A felulet kiirta, hogy a strategia az
     ALAPERTELMEZETT parametereivel indul; a parancs-reteg nemán inditott.
  3. **Kivezetes-figyelmeztetes.** A parancs-reteg rakerdezett, ha a leallitas az
     UTOLSO elo strategiat vinne el egy NYITOTT pozicios paron; a felulet nem —
     nemán kivezetesbe allitotta a part.

Ez a teszt a HELYREALLITOTT allapotot orzi: a szabalyok a kozos retegben vannak,
a felulet pedig csak bekoti a kornyezetet es megjelenit.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import logging
logging.disable(logging.INFO)

import json as _json

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from core import console_cmd as cc
from core import opt_activity as oa
from core import run_state as rs

_HU = _json.loads((ROOT / "lang" / "hu.json").read_text(encoding="utf-8"))


def _ctx(poz=None, mentes=True, forras=None):
    """Teljesen szintetikus kornyezet — se MT5, se tkinter, se fajl."""
    cfg = {"pairs": {"Ger40": {"enabled": True,
                               "strategies": ["wpr_sma", "ml_ai"],
                               "run_state": {"wpr_sma": "stopped",
                                             "ml_ai": "stopped"}}}}

    class _DS:
        position_pnl = poz

    return cfg, cc.Context(
        cfg=cfg,
        save_config=lambda: mentes,
        positions=list,
        close_position=lambda t: False,
        account=dict,
        dashboard={"Ger40": _DS()},
        instrument_state={"Ger40": "STOPPED"},
        strategies_of=lambda s: list(cfg["pairs"].get(s, {}).get("strategies", [])),
        params_source=(forras or (lambda s, n: "tuned")),
    )


# ── 1. A NEM ENGEDELYEZETT strategia nem indithato ────────────────────────
cfg, ctx = _ctx()
r = cc.start_strategies(ctx, "Ger40", ["bollinger_squeeze_breakout"])
check("a nem engedelyezett strategia nem indul", not r.ok)
check("...es a szandek NEM ragad be a configba",
      "bollinger_squeeze_breakout" not in cfg["pairs"]["Ger40"]["run_state"])
check("...es OKOT ad (nem nema no-op)",
      any("nincs engedélyezve" in x for x in r.lines), str(r.lines)[:80])


# ── 2. OPTIMALIZALAS ALATT nem indit — a felulet szabalya, MINDENKINEK ────
# ⚠ EZ VOLT AZ ELSO ELCSUSZAS. A `/play Ger40 wpr_sma` Telegramrol elinditotta
# volna azt a strategiat, amin epp optimalizalas fut — a futas vegen a sajat
# parameterfajlja irodott volna felul alola.
cfg, ctx = _ctx()
oa.set_state("Ger40", "wpr_sma", oa.RUNNING)
try:
    r = cc.start_strategies(ctx, "Ger40", ["wpr_sma"])
    check("optimalizalas alatt NEM indit", not r.ok)
    check("...es a szandek `stopped` marad",
          cfg["pairs"]["Ger40"]["run_state"]["wpr_sma"] == "stopped")
    check("...es megmondja, miert",
          any("OPTIMALIZÁLÁS" in x for x in r.lines), str(r.lines)[:90])
    # A SORBAN ALLO is szamit: barmikor indulhat.
    oa.set_state("Ger40", "wpr_sma", oa.QUEUED)
    check("a SORBAN ALLO optimalizalas is tilt",
          not cc.start_strategies(ctx, "Ger40", ["wpr_sma"]).ok)
finally:
    oa.set_state("Ger40", "wpr_sma", None)


# ── 3. HANGOLATLANUL INDULHAT — de nem nemán ─────────────────────────────
cfg, ctx = _ctx(forras=lambda s, n: "default")
r = cc.start_strategies(ctx, "Ger40", ["wpr_sma"])
check("mentett keszlet nelkul is INDUL", r.ok)
check("...es KIIRJA, hogy alapertelmezettel megy",
      any("ALAPÉRTELMEZETT" in x for x in r.lines), str(r.lines)[:90])
check("...a szandek `live` lett",
      cfg["pairs"]["Ger40"]["run_state"]["wpr_sma"] == rs.LIVE)
check("...es a par szimbolum-szinten is LIVE", ctx.instrument_state["Ger40"] == "LIVE")

# A bekotetlen `params_source` (alapertek) NEM hazudik — csak hallgat.
cfg, ctx = _ctx()
_c2 = cc.Context(cfg=cfg, save_config=lambda: True, positions=list,
                 close_position=lambda t: False, account=dict,
                 dashboard={}, instrument_state={},
                 strategies_of=lambda s: ["wpr_sma"])
r = cc.start_strategies(_c2, "Ger40", ["wpr_sma"])
check("bekotetlen params_source: indit, de nem allit semmit a hangoltsagrol",
      r.ok and not any("ALAPÉRTELMEZETT" in x for x in r.lines))


# ── 4. A MENTES EREDMENYE latszik ────────────────────────────────────────
cfg, ctx = _ctx(mentes=False)
r = cc.start_strategies(ctx, "Ger40", ["wpr_sma"])
check("sikertelen mentesnel az indulas NEM 'ok'", not r.ok)
check("...de a strategia MOST elindul (a motor ugyanabbol a dictbol olvas)",
      cfg["pairs"]["Ger40"]["run_state"]["wpr_sma"] == rs.LIVE)
check("...es kimondja, hogy ujrainditas utan nem folytatodna",
      any("újraindítás után nem" in x for x in r.lines), str(r.lines)[:90])


# ── 5. KIVEZETES: nyitott pozicionál MEGERSITEST ker ─────────────────────
# ⚠ EZ VOLT A HARMADIK ELCSUSZAS: a feluleten ez a kerdes fel sem merult.
cfg, ctx = _ctx(poz=12.5)
rs.set_state(cfg, "Ger40", "wpr_sma", rs.LIVE)
rs.set_state(cfg, "Ger40", "ml_ai", rs.LIVE)
ctx.instrument_state["Ger40"] = "LIVE"      # a par mar fut (ket elo strategiaval)
r = cc.stop_strategies(ctx, "Ger40", ["wpr_sma"])
check("amig MARAD elo strategia, nincs kerdes (a par tovabb fut)",
      not r.confirm and r.ok)
check("...es a par LIVE marad", ctx.instrument_state["Ger40"] != "STOPPED")

r = cc.stop_strategies(ctx, "Ger40", ["ml_ai"])
check("az UTOLSO elo strategianal NYITOTT pozicioval MEGERSITEST ker",
      bool(r.confirm), r.confirm[:60])
check("...es addig NEM csinal semmit",
      cfg["pairs"]["Ger40"]["run_state"]["ml_ai"] == rs.LIVE)

r = cc.stop_strategies(ctx, "Ger40", ["ml_ai"], confirmed=True)
check("megerositve KIVEZETESbe teszi (nem STOPPED)",
      ctx.instrument_state["Ger40"] == "CLOSING", ctx.instrument_state["Ger40"])

# Pozicio NELKUL nincs kerdes, es valodi STOPPED lesz.
cfg, ctx = _ctx()
rs.set_state(cfg, "Ger40", "wpr_sma", rs.LIVE)
r = cc.stop_strategies(ctx, "Ger40", ["wpr_sma", "ml_ai"])
check("pozicio nelkul nincs kerdes", not r.confirm)
check("...es a par STOPPED lesz", ctx.instrument_state["Ger40"] == "STOPPED")


# ── 6. A FELULET A KOZOS RETEGEN MEGY — forras-szintu orzes ──────────────
# ⚠ MIERT FORRAS-SZINTU: a `dashboard/gui.py` importja tkinter-gyokeret igenyel,
# a REGRESSZIO viszont pont az, ha valaki ujra a sajat irasi utjat nyitja meg.
_gui = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
check("a felulet NEM ir kozvetlenul a run_state-be",
      "_rs.set_state" not in _gui and "_rst.set_state" not in _gui
      and "run_state.set_state" not in _gui)
check("a felulet a kozos reteget hivja (inditas)", "_cc.start_strategies(" in _gui)
check("a felulet a kozos reteget hivja (leallitas)", "_cc.stop_strategies(" in _gui)
check("a felulet bekoti a MOTOR strategia-listajat",
      "strategies_of=lambda sym: _ensn(self.cfg, sym)" in _gui)
check("a felulet a SAJAT (allapotsorba iro) mentojet adja at",
      "save_config=self._save_main_config" in _gui)
# A megerosites-minta: a felulet is megkerdezi, amit a konzol megkerdez.
_runstop = _gui.split("def _run_stop")[1].split(chr(10) + "    def ")[0]
check("a felulet kezeli a `confirm` kort (nem hajtja vegre csendben)",
      "res.confirm" in _runstop and "confirmed=True" in _runstop)

# Es a masik iranyban: a szabalyok TENYLEG a kozos retegben vannak.
_cc_src = (ROOT / "core" / "console_cmd.py").read_text(encoding="utf-8")
_start = _cc_src.split("def start_strategies")[1].split(chr(10) + "def ")[0]
check("a kozos reteg ismeri az optimalizalas-tiltast", "_oa.busy(" in _start)
check("a kozos reteg ismeri a hangolatlan indulast",
      "console.play.default_params" in _start)
check("a `cmd_play` mar csak argumentumot bont",
      "return start_strategies(ctx, sym, names)" in _cc_src)
check("a `cmd_stop` is", "return stop_strategies(ctx, sym, names" in _cc_src)

# A feliratok a KATALOGUSBAN vannak (i18n), nem a forrasban.
for _k in ("console.play.opt_running", "console.play.default_params",
           "gui.ctrl.confirm_title"):
    check(f"van magyar felirat: {_k}", bool(_HU.get(_k)), _HU.get(_k, "")[:50])


# ── 7. UGYANEZ AZ OSZTALY: a risky_mode szinkron EGY gazdaval ────────────
# ⚠ A LELET. A „a regi risky_mode-ot szinkronban tartjuk (preset==risky)" sor
# HAROM helyen elt egymas mellett (sor „R" gomb · Poziciok-ful kiszallas-menu ·
# instrumentum-ablak), kettonel nema `except: pass` mogott. Aki NEGYEDIKKENT
# hivta volna a settert (motor, eszkoz, teszt, karmester), annal a szinkron
# csendben elmarad — a `risky_mode.json` a regi erteket orzi, es az azt olvaso
# elo/backtest ag MAS kockazattal fut, mint amit a felulet mutat.
import tempfile as _tf
from core import risky_mode as _rm, rr_state as _rrs, risk_reduction as _rr

_tmp = Path(_tf.mkdtemp(prefix="tf_rr_"))
_rm_path, _rrs_path = _rm.PATH, _rrs.PATH
_rm.PATH, _rrs.PATH = _tmp / "risky.json", _tmp / "risk_mode.json"
try:
    _rrs.set_preset("TESZT", _rr.PRESET_RISKY)
    check("set_preset(risky) bekapcsolja a regi risky_mode-ot", _rm.is_risky("TESZT"))
    _rrs.set_preset("TESZT", _rr.PRESET_SHIELD)
    check("...es MAS presetnel kikapcsolja", not _rm.is_risky("TESZT"))
    # A korbe-valtas is a setter utjan megy — minden allapotban egyeznie kell.
    _elteres = []
    for _ in range(len(_rrs.CYCLE)):
        _p = _rrs.cycle_preset("TESZT")
        if (_p == _rr.PRESET_RISKY) != _rm.is_risky("TESZT"):
            _elteres.append(_p)
    check("a cycle_preset MINDEN allapotaban egyezik a ket forras",
          not _elteres, str(_elteres))
finally:
    _rm.PATH, _rrs.PATH = _rm_path, _rrs_path

# ...es a hivoknal MAR NINCS masolat.
_idlg = (ROOT / "dashboard" / "instrument_dialog.py").read_text(encoding="utf-8")
check("a felulet nem szinkronizal kezzel (gui.py)",
      "risky_mode.set_risky" not in _gui)
check("...es az instrumentum-ablak sem",
      "risky_mode.set_risky" not in _idlg)
_rrsrc = (ROOT / "core" / "rr_state.py").read_text(encoding="utf-8")
check("a szinkron a setter mellekhatasa (rr_state)",
      "_sync_risky(symbol, p)" in _rrsrc and "_sync_risky(symbol, nxt)" in _rrsrc)
# ⚠ A `with _lock:` blokk 8 szokoznel all; a 4 szokozos behuzas = a zaron KIVUL.
_cyc = _rrsrc.split("def cycle_preset")[1].split(chr(10) + "def ")[0]
_sorok = [l for l in _cyc.splitlines() if "_sync_risky(" in l]
check("...es a ZARON KIVUL hivodik (holtpont-kerules)",
      bool(_sorok) and all(l.startswith("    ") and not l.startswith("     ")
                           for l in _sorok), str(_sorok))


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

"""Harom bejelentes (2026-08-04 este) — ml/optimizer.py + a 2.0 Opt-cellaja.

  1. „Ha megnyomtam az OPT gombot, valtson at STOP gombra, hogy le tudjam
     allitani az optimalizalast."
  2. „Most csak annyit latok, hogy fut… Itt azt kertem, hogy lassam azt is, hogy
     eppen hol tart, pl. 12%."
  3. A naplot elarasztja: `UserWarning: The distribution is specified by
     [0.5, 3.0] and step=0.2, but the range is not divisible by step`.

A 3. NEM kodhiba, hanem CONFIG-hiba (a felso hatar elerhetetlen) — de trialonkent
figyelmeztetni ROSSZ valasz ra: 500 trial x 4 ablak utan a naplo olvashatatlan.
Ezert a racs-igazitas csendes (az optuna is pontosan ezt tenne), a HIBAT viszont
INDULASKOR, EGYSZER jelezzuk — es meg is mondjuk, mit kell atirni.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from core import opt_activity as oa
from dashboard import live_row as lr
import ml.optimizer as opt


# ══ 1. Az OPT gomb MORPHOL ═══════════════════════════════════════════════
check("alapallapot: OPT", lr._opt_text({}) [0] == "OPT", lr._opt_text({})[0])
check("futo optimalizalas: STOP",
      lr._opt_text({"opt_state": "running"})[0] == "STOP")
check("sorban allo: SOR", lr._opt_text({"opt_state": "queued"})[0] == "SOR")

# A szin is valt (piros = leallitas, mint a Play/Stop ■-je)
from dashboard.theme import FG_BLUE, FG_RED, FG_GRAY_DIM
check("a STOP PIROS (a leallitas nyelve)",
      lr._opt_text({"opt_state": "running"})[1] == FG_RED)
check("kereskedo strategianal az OPT halvany",
      lr._opt_text({"opt_enabled": False})[1] == FG_GRAY_DIM)
# ...DE egy FUTO optimalizalast akkor is le lehessen allitani!
check("futo optimalizalas AKKOR IS leallithato, ha a strategia kereskedik",
      lr._opt_text({"opt_enabled": False, "opt_state": "running"})[0] == "STOP")

# A cella szelessege a LEGSZELESEBB feliratra meretezodik — kulonben a STOP
# megjelenesekor ugralna a tabla vagy levagodna a szoveg.
try:
    import tkinter as tk
    from tkinter import font as tkfont
    _r = tk.Tk(); _r.withdraw()
    f = {"mono": tkfont.Font(family="Consolas", size=10),
         "mono_bold": tkfont.Font(family="Consolas", size=10, weight="bold"),
         "small": tkfont.Font(family="Segoe UI", size=9)}
    w = lr.widths(f)["ctrl"]
    need = (f["small"].measure("■") + 2 * lr.CTRL_PADX + lr.CTRL_GAP
            + max(f["small"].measure(t) for t in lr.OPT_LABELS.values())
            + 2 * lr.CTRL_PADX + 2 * lr.PAD)
    check("a Vezerles-cella elbirja a leghosszabb OPT-feliratot is", w >= need,
          f"{w} >= {need}")
    _r.destroy()
except Exception as e:
    print(f"KIHAGYVA (szelesseg): {type(e).__name__}: {e}")


# ══ 2. A HALADAS szamkent elerheto (a rovid cellahoz) ════════════════════
SYM, ST = "TESZT_PAR", "wpr_sma"
oa.clear_symbol(SYM)
check("nincs bejegyzes -> nincs haladas", oa.progress_pct(SYM, ST) is None)

oa.set_state(SYM, ST, oa.RUNNING)
check("frissen indult futasnal meg nincs szazalek (adat-elokeszites)",
      oa.progress_pct(SYM, ST) is None)
oa.set_progress(SYM, ST, 60, 500)
check("60/500 -> 12%", oa.progress_pct(SYM, ST) == 12, str(oa.progress_pct(SYM, ST)))
oa.set_progress(SYM, ST, 500, 500)
check("500/500 -> 100%", oa.progress_pct(SYM, ST) == 100)
oa.set_progress(SYM, ST, 1, 0)
check("nulla total -> 0% (nem osztunk nullaval)", oa.progress_pct(SYM, ST) == 0)

# A haladas SZAM, nem formazott szoveg — kulonben a `classic` hosszu sora es a
# 2.0 rovid cellaja formatum-szinten osszeragadna.
check("a haladas int (nem szoveg)", isinstance(oa.progress_pct(SYM, ST), int))
oa.clear_symbol(SYM)
check("a bejegyzes torlese a haladast is elviszi",
      oa.progress_pct(SYM, ST) is None)

# A GUI a haladas-szivattyubol tolti — forras-szintu orzes (a pumpa MT5/pool-fuggo).
gui_src = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
check("a haladas-szivattyu bekoti az opt_activity-t",
      "_opt_activity.set_progress(symbol, strat, done, total)" in gui_src)
check("az Opt-cella a szazalekot mutatja, ha van",
      'f"{pct}%" if pct is not None else "fut…"' in gui_src)


# ══ 3. Racs-igazitas: az optuna NE figyelmeztessen trialonkent ═══════════
check("[0.5 … 3.0] step 0.2 -> 2.9 (ez a bejelentett eset)",
      abs(opt._grid_max(0.5, 3.0, 0.2) - 2.9) < 1e-9,
      str(opt._grid_max(0.5, 3.0, 0.2)))
check("[0.5 … 3.0] step 0.25 -> 3.0 (oszthato, nem valtozik)",
      abs(opt._grid_max(0.5, 3.0, 0.25) - 3.0) < 1e-9)
# A lebegopontos maradek csapdaja: (1.0-0.0)/0.1 = 9.999… -> a naiv floor 9-et
# adna, ami HIBASAN levagna egy ervenyes racspontot.
check("[0.0 … 1.0] step 0.1 -> 1.0 (a float-maradek nem vag le racspontot)",
      abs(opt._grid_max(0.0, 1.0, 0.1) - 1.0) < 1e-9,
      str(opt._grid_max(0.0, 1.0, 0.1)))
check("[0.2 … 1.0] step 0.1 -> 1.0", abs(opt._grid_max(0.2, 1.0, 0.1) - 1.0) < 1e-9)
check("ervenytelen step -> valtozatlan hatar", opt._grid_max(1.0, 2.0, 0) == 2.0)
check("hi <= lo -> valtozatlan", opt._grid_max(2.0, 1.0, 0.1) == 1.0)

# A FIGYELMEZTETES egyszer szol, es CSAK a hibas kulcsra.
import logging


class _Cap(logging.Handler):
    def __init__(self):
        super().__init__()
        self.msgs = []

    def emit(self, record):
        self.msgs.append(record.getMessage())


_h = _Cap()
_lg = logging.getLogger("ml.optimizer")
_lg.addHandler(_h)
try:
    opt._warn_step_grid("Ger40", {
        "tp_rr_ratio": {"min": 0.5, "max": 3.0, "step": 0.2},     # HIBAS
        "sl_atr_mult": {"min": 1.0, "max": 3.0, "step": 0.25},    # jo
        "atr_min_pct": {"min": 0.2, "max": 1.0, "step": 0.1},     # jo
        "sma_period":  {"min": 50, "max": 300, "step": 10},       # int-ag, kihagyva
    })
finally:
    _lg.removeHandler(_h)

check("PONTOSAN egy figyelmeztetes (csak a hibas tartomanyra)", len(_h.msgs) == 1,
      str(_h.msgs))
check("...es megnevezi a kulcsot", _h.msgs and "tp_rr_ratio" in _h.msgs[0])
check("...es megmondja a TENYLEGES felso hatart", _h.msgs and "2.9" in _h.msgs[0],
      _h.msgs[0] if _h.msgs else "")

# A suggeszt-ag a racs-igazitott hatart hasznalja (nem a nyerset).
opt_src = (ROOT / "ml" / "optimizer.py").read_text(encoding="utf-8")
check("a float-suggeszt a _grid_max-ot hasznalja",
      "_grid_max(lo, hi, step)" in opt_src)
check("az indulaskori ellenorzes be van kotve",
      "_warn_step_grid(symbol," in opt_src)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

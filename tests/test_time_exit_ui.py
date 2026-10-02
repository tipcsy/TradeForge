"""IDŐ-KILÉPÉS a felületen — az instrumentum-ablak mezői (2026-10-03).

Amit őrzünk (VALÓDI `InstrumentParamsDialog`-on):
  1. a „Napvége" és „Max perc" mező megjelenik a kockázatcsökkentés sorában;
  2. mentéskor a per-pár állapotba íródik (`rr_state.get_time_exit`), a „9:5"
     egységes „09:05" alakra áll;
  3. érvénytelen bevitel („25:00", „abc", negatív) NEM ment és NEM kapcsol ki
     csendben — a mezők a tárolt értékre állnak vissza;
  4. üres mező = kikapcsolva;
  5. a backtestnek átadott spec (`_rr_spec_from_ui`) viszi az idő-kilépést.

⚠⚠ AZ ÉLES ÁLLAPOTOT NEM ÍRJUK: a `rr_state.PATH` ideiglenes fájlra terítve
(ugyanaz a védelem, mint a `test_fullwidth_sections`-ben).
"""
import atexit as _atexit
import pathlib as _pathlib
import shutil as _shutil
import sys
import tempfile as _tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog  # noqa: E402
applog.harden_console()

from core import rr_state as _rrs  # noqa: E402
_RR_REAL = _rrs.PATH
_RR_TMP = _pathlib.Path(_tempfile.mkdtemp(prefix="tfv_rr_")) / "risk_mode.json"
if _RR_REAL.exists():
    _shutil.copy2(_RR_REAL, _RR_TMP)
_rrs.PATH = _RR_TMP
_atexit.register(lambda: setattr(_rrs, "PATH", _RR_REAL))
_atexit.register(lambda: _shutil.rmtree(_RR_TMP.parent, ignore_errors=True))
_rrs.load()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


try:
    import tkinter as tk
    _p = tk.Tk(); _p.destroy()
    TK = True
except Exception as e:
    TK = False
    print(f"KIHAGYVA: nincs hasznalhato tkinter ({type(e).__name__}: {e})")

if TK:
    import copy
    from strategy.settings import load_config
    from strategy import get_strategy_by_name
    from dashboard import instrument_dialog as idlg, theme
    from core import risk_reduction as rr

    root = tk.Tk(); root.withdraw()
    theme._FONTS.clear()
    f = theme.fonts()
    cfg = load_config("config.json")
    sym = next(s for s in cfg["pairs"] if not s.startswith("_"))
    _rrs.set_time_exit(sym, "", 0)                      # tiszta indulás (temp fájl)
    d = idlg.InstrumentParamsDialog(root, sym, cfg, get_strategy_by_name("wpr_sma"),
                                    f["header"], f["small"], lambda: None,
                                    root_cfg=copy.deepcopy(cfg))
    root.update_idletasks()

    check("a mezo-keret letezik es a sorban van", hasattr(d, "_te_frame")
          and d._te_frame.grid_info().get("column") in (6, "6"),
          str(getattr(d, "_te_frame", None) and d._te_frame.grid_info()))
    check("kiindulaskor ures (kikapcsolva)", d._te_eod_var.get() == ""
          and d._te_max_var.get() == "")

    d._te_eod_var.set("9:5"); d._te_max_var.set("480"); d._on_time_exit_save()
    te = _rrs.get_time_exit(sym)
    check("mentes: a per-par allapotba irodik", te == {"eod_close": "09:05",
                                                     "max_hold_min": 480.0}, str(te))
    check("a „9:5” egyseges alakra all", d._te_eod_var.get() == "09:05")

    d._te_eod_var.set("21:45"); d._on_time_exit_save()
    for bad_eod, bad_max in (("25:00", "480"), ("abc", "480"), ("21:45", "-5"),
                             ("21:45", "xyz")):
        d._te_eod_var.set(bad_eod); d._te_max_var.set(bad_max); d._on_time_exit_save()
        te = _rrs.get_time_exit(sym)
        check(f"ervenytelen ({bad_eod!r}, {bad_max!r}) nem ment",
              te == {"eod_close": "21:45", "max_hold_min": 480.0}, str(te))
        check(f"...es a mezok visszaallnak", d._te_eod_var.get() == "21:45"
              and d._te_max_var.get() == "480",
              f"{d._te_eod_var.get()!r} {d._te_max_var.get()!r}")

    _sp = _rrs.spec_for(sym)
    check("a motor spec_for-ja viszi", _sp.get("eod_close") == "21:45"
          and float(_sp.get("max_hold_min")) == 480.0 and rr.time_exit_active(_sp))

    # a backtestnek atadott UI-spec (nem-Ki presettel, hogy ne None legyen)
    d._rr_name.set(_rrs.NAME[rr.PRESET_HALVING])
    _ui = d._rr_spec_from_ui()
    check("a UI-spec viszi az ido-kilepest", _ui is None
          or (_ui.get("eod_close") == "21:45" and float(_ui.get("max_hold_min")) == 480.0),
          str(None if _ui is None else {k: _ui.get(k) for k in ("preset", "eod_close", "max_hold_min")}))

    d._te_eod_var.set(""); d._te_max_var.set(""); d._on_time_exit_save()
    te = _rrs.get_time_exit(sym)
    check("ures mezo = kikapcsolva", te == {"eod_close": "", "max_hold_min": 0.0}
          and not rr.time_exit_active(_rrs.spec_for(sym)), str(te))
    check("az eles risk_mode.json erintetlen (temp fajlba irtunk)",
          _rrs.PATH == _RR_TMP)

    try:
        d.destroy()
    except Exception:
        pass
    root.destroy()

print(f"\n{sum(results)}/{len(results)} teszt PASS")
if not all(results):
    sys.exit(1)

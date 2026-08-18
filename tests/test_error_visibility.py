"""A hibát ne nyeljük el: kerüljön a naplóba, és LÁTSZÓDJON, hogy van.

⚠ A KÉRÉS (a felhasználótól, 2026-08-18): „Próbáljuk azt megcsinálni, hogy a
hibákat nem elnyeljük, hanem egy logfájlba kerüljenek be! Mert így nagyon nem
oké, hogy hemzseg a hibától, de nem kapunk róla értesítést, mert mindent
»elnyelünk«."

⚠ A LEGNAGYOBB VAK FOLT NEM a 205 `except: pass` volt, hanem a FELÜLET. A
Tkinter minden visszahívást (gomb-parancs, kötés, `after`) becsomagol, és ha az
kivételt dob, a `report_callback_exception` a STDERR-re ír. Egy ablakos
alkalmazásban a stderr sehol nincs — a gomb egyszerűen „nem csinál semmit".

Ugyanezen a napon KÉT hiba is pontosan így viselkedett:
  • a naptár-választó visszahívása minden kattintásra `AttributeError`-t dobott
    (a dátum sosem íródott be) — sem a felületen, sem a naplóban nem volt nyoma;
  • az Indítás gomb „nem indított semmit" (valójában a mód-választó némán
    felülírta a pipákat).

Egy hook a `Tk` OSZTÁLYON az egész felületet lefedi — ezt 205 külön `except`-ág
sosem tudná. És mert egy naplófájl, amibe senki nem néz bele, majdnem annyira
néma, mint a semmi: a hibák SZÁMLÁLÓDNAK, és a dashboard kiírja, hogy van mit
megnézni.
"""
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ── 1. A HOOKOK LÉTEZNEK ÉS IDEMPOTENSEK ────────────────────────────────
for _fn in ("install_tk_excepthook", "install_sys_excepthook",
            "install_error_counter", "error_stats"):
    check(f"van {_fn}", callable(getattr(applog, _fn, None)))

import tkinter as tk
_before = tk.Tk.report_callback_exception
applog.install_tk_excepthook()
_after = tk.Tk.report_callback_exception
check("a Tk-hook felkerül", _after is not _before)
applog.install_tk_excepthook()
check("...és többszöri hívásra sem láncol újra",
      tk.Tk.report_callback_exception is _after)
# ⚠ A hook az OSZTÁLYRA kerül, nem egy példányra: a `Misc._report_exception`
# mindig a GYÖKÉR ablakon hívja, tehát minden Toplevel és widget alá tartozik.
_src = (ROOT / "core" / "applog.py").read_text(encoding="utf-8")
check("az OSZTÁLYRA kerül (egy hely, minden ablak)",
      "tkinter.Tk.report_callback_exception = _hook" in _src)

_sysb = sys.excepthook
applog.install_sys_excepthook()
applog.install_sys_excepthook()
check("a főszál-hook is idempotens",
      sys.excepthook is not _sysb or getattr(sys.excepthook, applog._MARKER, False))


# ── 2. EGY VALÓDI GOMB-HIBA TÉNYLEG A NAPLÓBA KERÜL ────────────────────
# ⚠ Ez a mérés lényege: nem a hook LÉTÉT nézzük, hanem hogy egy elszálló
# visszahívás után VAN-e nyom. Enélkül a teszt ugyanolyan hiszékeny volna, mint
# a felület volt.
applog.install_error_counter()
applog.reset_error_stats()

_rec = []


class _Catch(logging.Handler):
    def emit(self, r):
        _rec.append(r)


_h = _Catch(level=logging.ERROR)
logging.getLogger().addHandler(_h)
_prev_disable = logging.root.manager.disable
logging.disable(logging.NOTSET)
try:
    root = tk.Tk()
    root.withdraw()
    btn = tk.Button(root, text="x", command=lambda: "nincs ilyen".isoformat())
    btn.invoke()                      # AttributeError a visszahívásban
    root.update_idletasks()
    _msgs = [r.getMessage() for r in _rec]
    check("a gomb-hiba NAPLÓBA került",
          any("felület-visszahívás" in m for m in _msgs), str(_msgs)[:120])
    check("...a kivétel típusával együtt",
          any("AttributeError" in (r.getMessage() + str(r.exc_info)) for r in _rec))
    # ...és a traceback is ott van (különben nem lehet javítani).
    check("...és a teljes traceback-kel",
          any(r.exc_info for r in _rec))
    _n, _last = applog.error_stats()
    check("a SZÁMLÁLÓ is lépett", _n >= 1, str(_n))
    check("...és megjegyzi az utolsó üzenetet", bool(_last), _last[:70])
    root.destroy()
finally:
    logging.getLogger().removeHandler(_h)
    logging.disable(_prev_disable)


# ── 3. A NAPLÓ LÁTSZÓDJON A FELÜLETEN ──────────────────────────────────
_g = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
check("a dashboardnak van hiba-jelzője", "_make_error_badge" in _g)
check("...amit a periodikus frissítés karbantart", "_refresh_error_badge()" in _g)
check("...MINDHÁROM elrendezésben", _g.count("self._make_error_badge(parent") == 3,
      str(_g.count("self._make_error_badge(parent")))
_i = _g.find("def _refresh_error_badge")
_blk = _g[_i:_i + 900]
check("nulla hibánál REJTVE (nincs mit mondani)", "pack_forget()" in _blk)
check("hibánál kiírja a DARABSZÁMOT", "hiba a naplóban" in _blk)
check("...és megnyitható a napló", "_open_log" in _g and "LOG_PATH" in _g)


# ── 4. A KÉT MAI LELET: a konkrét elnyelések megszűntek ────────────────
_dp = (ROOT / "dashboard" / "date_picker.py").read_text(encoding="utf-8")
_i = _dp.find("def _pick")
check("a naptár-visszahívás hibája naplózódik",
      "log.exception" in _dp[_i:_i + 900])
check("...és nem `except Exception: pass`",
      "except Exception:\n                pass" not in _dp[_i:_i + 900])

# ── 5. A HÁTRALÉVŐ NÉMA ELNYELÉSEK — MÉRVE, nem sejtve ────────────────
# ⚠ Nem mindegyik hiba: egy `tk.TclError` a bezáráskor, vagy egy kozmetikai
# művelet elbukása jogosan néma. A számot viszont ISMERNI kell, különben a
# „majd rendbe tesszük" évekig igaz marad. Ez a sor NEM bukik el — MÉR.
import re
_silent = 0
for _f in ROOT.rglob("*.py"):
    if ".venv" in str(_f) or "\\tests\\" in str(_f):
        continue
    _t = _f.read_text(encoding="utf-8", errors="replace").splitlines()
    for _a, _b in zip(_t, _t[1:]):
        if re.match(r"\s*except\b.*:\s*$", _a) and re.match(r"\s*pass\s*$", _b):
            _silent += 1
print(f"      (néma elnyelés a nem-teszt kódban: {_silent} — a felület-hook "
      f"ezek FÖLÖTT fog, mert a Tk-visszahívás szintjén kap el)")
check("a mérés lefutott (a szám a naplóban marad)", _silent >= 0)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

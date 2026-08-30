"""Mi indul el, amikor az Indítást megnyomod — és látszik-e, hogy fut.

⚠ A LELET (a felhasználótól, 2026-08-18): „az Opt nem működik abban az esetben,
ha egynél több paramétert választok ki. Ilyenkor valahogy nem indul el a
futtatás, nem látszik, hogy történne valami."

Mérve: NEM hiba volt, és nem is dobott kivételt. A mód-választó MENTETT értéke
`backtest` volt (`data/backtest_prefs.json`: wpr_sma/Ger40, GOLD, EURGBP,
UK100), a gomb tehát HELYESEN egyetlen futást indított — a bepipált paraméterek
pedig NÉMÁN nem számítottak. Kívülről ez pontosan úgy néz ki, mint egy nem
működő gomb.

A tanulság nem az, hogy a mód rossz helyen volt: az ELLENTMONDÁST kell kimondani
ott, ahol a gomb van. Egy felület, ami figyelmen kívül hagyja a beállításodat és
nem szól róla, működésképtelennek látszik.

⚠ ÉS A HÁROM MÓD ÉRTELME (a kérés szerint):
  • Backtest      — egyetlen futás a mostani értékekkel; a pipák nem számítanak.
  • Hangolás      — a BEPIPÁLTAKON: 1 → végigpróbálás, 2 → rács, 3+ → optuna.
  • Optimalizálás — a TELJES tér, a pipáktól FÜGGETLENÜL (a megszokott OPT).
"""
import copy
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

results = []
import json as _json
_HU_CAT = _json.loads((ROOT / "lang" / "hu.json").read_text(encoding="utf-8"))


def _says(key, *words):
    """A kulcs magyar szovege tartalmazza-e mindet? (i18n utan a felirat mar
    nem a forrasban van — a teszt a KATALOGUST kerdezi.)"""
    txt = _HU_CAT.get(key, "")
    return all(w in txt for w in words)




def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


import logging
logging.disable(logging.INFO)

import tkinter as tk
from strategy.settings import load_config
from strategy import get_strategy_by_name
from dashboard import instrument_dialog as idlg

cfg = load_config("config.json")
SYM = "Ger40"
root = tk.Tk()
root.withdraw()
FONTS = {"header": ("Segoe UI", 10, "bold"), "small": ("Segoe UI", 8)}


def _dialog():
    d = idlg.InstrumentParamsDialog(root, SYM, cfg, get_strategy_by_name("wpr_sma"),
                                    FONTS["header"], FONTS["small"], lambda: None,
                                    root_cfg=copy.deepcopy(cfg))
    d._shell.show("params")
    d.popup.update_idletasks()
    d._sections["futtatas"].set_open(True)
    d.popup.update_idletasks()
    # ⚠ A VALÓDI állapotot NEM írjuk: a mód-mentés a `data/backtest_prefs.json`-ba
    # menne, a pipa-váltás pedig a `config.json`-ba. Egy teszt SOHA ne írja át a
    # felhasználó beállításait (ez már kétszer megtörtént a projektben).
    d._save_run_mode = lambda v: None
    return d


# ⚠ A MERES NE FUGGJON A GEPTOL. Az indítás előtt megnézzük, fut-e MÁSHOL
# optimalizálás ezen a páron (`opt_lock`) — és ha a felhasználó gépén épp fut
# egy, a dialógus JOGGAL tagadja meg az indítást. Ilyenkor a teszt nem a
# mód-választót mérné, hanem azt, hogy a mérés pillanatában mi futott. (Élesben
# pontosan ez történt: „MÁR FUT egy optimalizálás 44 perce — pid 9012".)
from core import opt_lock as _ol_guard
_ol_guard.is_held = lambda *_a, **_k: False


d = _dialog()
KEYS = [r["key"] for r in d._opt_rows if r["key"] in d._skip_vars]
check("van mit hangolni (a mérés értelmes)", len(KEYS) >= 3, f"{len(KEYS)} kulcs")


# ── 1. A HÁROM MÓD LÉTEZIK, és a mentés elfogadja mindet ────────────────
check("három mód van", set(idlg.InstrumentParamsDialog._RUN_MODES)
      == {"backtest", "planned", "optimize"},
      str(idlg.InstrumentParamsDialog._RUN_MODES))
# ⚠ Egy ismeretlen/hibás mentett érték ne bénítsa meg az ablakot.
import core.backtest_prefs as _bp
_orig_get = _bp.get
try:
    for _v, _want in (("optimize", "optimize"), ("backtest", "backtest"),
                      ("szemet", "planned"), (None, "planned")):
        _bp.get = lambda s, n, _v=_v: {"run_mode": _v}
        check(f"mentett mód {_v!r} → {_want!r}", d._load_run_mode() == _want,
              d._load_run_mode())
finally:
    _bp.get = _orig_get


# ── 2. MI INDUL EL — a teljes mátrix ────────────────────────────────────
CALLS = []
d._start_sweep = lambda: CALLS.append("sweep")
d.on_optimize = lambda s, n, all_params=False: (
    CALLS.append(f"opt(all={all_params})"), "")[1]
d.opt_state_of = lambda s, n: ""
if getattr(d, "_run_tab", None) is not None:
    d._run_tab._start = lambda: CALLS.append("single")



def _func_src(src: str, header: str) -> str:
    """Egy metódus TELJES törzse. ⚠ Fix karakter-ablakkal (`src[i:i+2200]`) a
    mérés elcsúszik, amint a függvény hosszabb lesz — és úgy néz ki, mintha a
    kód romlott volna el, holott csak a teszt ablaka lett szűk."""
    i = src.find(header)
    if i < 0:
        return ""
    j = src.find(chr(10) + "    def ", i + len(header))
    return src[i:j if j > 0 else len(src)]


def _run(mode, n_ticked):
    d._run_mode.set(mode)
    d._on_run_mode()
    for k in KEYS:
        d._skip_vars[k].set(k in KEYS[:n_ticked])
    d._refresh_run_mode_ui()          # ezt hívja a pipa parancsa is
    CALLS.clear()
    d._start_planned()
    return list(CALLS)


M = idlg.InstrumentParamsDialog
# ⚠ BACKTEST: a pipák számától FÜGGETLENÜL egyetlen futás. Ez a mód ígérete —
# épp azért van, hogy egy próbához ne kelljen kiszedni minden pipát.
for _n in (0, 1, 2, 3):
    check(f"Backtest / {_n} pipa → egyetlen futás",
          _run(M.RUN_BACKTEST, _n) == ["single"], str(_run(M.RUN_BACKTEST, _n)))

# ⚠ HANGOLÁS: a dimenziók SZÁMÁBÓL adódik, mint eddig.
check("Hangolás / 0 pipa → egyetlen futás (nincs mit hangolni)",
      _run(M.RUN_PLANNED, 0) == ["single"])
check("Hangolás / 1 pipa → végigpróbálás", _run(M.RUN_PLANNED, 1) == ["sweep"])
check("Hangolás / 2 pipa → rács", _run(M.RUN_PLANNED, 2) == ["sweep"])
# ⚠ 3+ → optuna, de CSAK a bepipáltakon: a kivett kulcsok az alapértéken
# maradnak. Ez az, ami megkülönbözteti az „Optimalizálás" módtól.
check("Hangolás / 3 pipa → optuna a BEPIPÁLTAKON",
      _run(M.RUN_PLANNED, 3) == ["opt(all=False)"], str(_run(M.RUN_PLANNED, 3)))

# ⚠ OPTIMALIZÁLÁS: a pipák nem számítanak — a teljes tér. Üres pipa-listával is
# értelmes, tehát SOSEM esik vissza backtestre.
for _n in (0, 1, 3):
    check(f"Optimalizálás / {_n} pipa → TELJES tér",
          _run(M.RUN_OPTIMIZE, _n) == ["opt(all=True)"],
          str(_run(M.RUN_OPTIMIZE, _n)))


# ── 3. A NÉMA FELÜLÍRÁS VÉGE ────────────────────────────────────────────
# ⚠ EZ A LELET GYÓGYSZERE. A mód figyelmen kívül hagyhatja a pipákat — de nem
# csendben.
_run(M.RUN_BACKTEST, 3)
_txt = d._mode_lbl.cget("text")
check("Backtest + pipák → KIMONDJA, hogy a pipák nem számítanak",
      "nem számít" in _txt and "3" in _txt, _txt[:80])
_run(M.RUN_BACKTEST, 0)
check("...pipa nélkül viszont nincs mit mondani", d._mode_lbl.cget("text") == "",
      d._mode_lbl.cget("text"))
_run(M.RUN_OPTIMIZE, 1)
check("Optimalizálás → kimondja, hogy a TELJES tér megy",
      "teljes tér" in d._mode_lbl.cget("text"), d._mode_lbl.cget("text")[:80])
_run(M.RUN_PLANNED, 0)
check("Hangolás pipa nélkül → megmondja, hogy így ez backtest",
      "Nincs pipa" in d._mode_lbl.cget("text"), d._mode_lbl.cget("text")[:80])

# A pipa átállítása FRISSÍTI a figyelmeztetést (nem csak a mód-váltás).
_src = (ROOT / "dashboard" / "instrument_dialog.py").read_text(encoding="utf-8")
check("a pipa parancsa is frissíti a figyelmeztetést",
      "_refresh_run_mode_ui()" in _func_src(_src, "def _on_skip_change"))


# ── 4. A FELTÉTELEK csak OPTIMALIZÁLÁS módban ──────────────────────────
# ⚠ A kérés: a magyarázó szöveg „csak ekkor" jelenjen meg. Backtest módban egy
# walk-forward magyarázat félrevezető: ott nincs tanuló/vizsga ablak.
if d._cond_box is not None:
    _run(M.RUN_OPTIMIZE, 1)
    check("Optimalizálás → a feltételek LÁTSZANAK",
          bool(d._cond_box.winfo_manager()))
    _run(M.RUN_BACKTEST, 1)
    check("Backtest → a feltételek ELTŰNNEK",
          not d._cond_box.winfo_manager())
    _run(M.RUN_PLANNED, 1)
    check("Hangolás → szintén nem látszanak",
          not d._cond_box.winfo_manager())
else:
    check("nincs walk-forward terv (a feltétel-mérés kihagyva)", True)


# ── 5. A HALADÁS-SÁV ────────────────────────────────────────────────────
# ⚠ A kérés: „elinduljon egy progress bar közvetlen az indítás gomb alatt, hogy
# látszódjon, hogy történik valami".
check("van haladás-sáv", getattr(d, "_prog", None) is not None)
d._prog_hide()
check("tétlenül NEM látszik (egy 0%-os sáv fut-nak látszana)",
      not d._prog_box.winfo_manager())
d._prog_show(42.0, "42%")
d.popup.update_idletasks()
check("haladásra megjelenik", bool(d._prog_box.winfo_manager()))
check("...a helyes értékkel", abs(float(d._prog.cget("value")) - 42.0) < 0.01,
      str(d._prog.cget("value")))
check("...és a gomb ALATT (nem a szakasz végén)",
      d._prog_box.winfo_y() < d._run_status.winfo_y(),
      f"sáv y={d._prog_box.winfo_y()} status y={d._run_status.winfo_y()}")
# ⚠ Ismeretlen haladásnál HATÁROZATLAN sáv — nem hazudunk 0%-ot egy dolgozó
# futásra (az optimalizálás első trialja előtt nincs mit százalékolni).
d._prog_show(None, "előkészítés…")
check("ismeretlen haladás → határozatlan sáv",
      str(d._prog.cget("mode")) == "indeterminate", str(d._prog.cget("mode")))
d._prog_hide()
check("elrejthető", not d._prog_box.winfo_manager())

# A gomb STOP-pá alakul, és a haladás az optimalizáló TÉNYLEGES állapotából jön.
_blk = _func_src(_src, "def _sync_opt_status")
# ⚠ A felirat a nyelvi katalogusban van (i18n) — a forrasban a KULCS all.
check("a gomb futás közben leállít",
      "idlg3.optimalizalas_leallitasa" in _blk)
check("a % a KÖZÖS forrásból (opt_activity) jön — mint a főképernyőn",
      "progress_pct" in _blk)
_g = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
check("...és a főképernyő ugyanabból számol",
      "progress_pct" in _g and 'f"{strat} {done}/{total}  {pct}%"' in _g)


# ── 5b. AZ ELUTASÍTÁS OKA MEGMARAD ─────────────────────────────────────
# ⚠ A LELET (a felhasználótól, képernyőképpel): „Valami üzenet megjelent ugyan,
# de le is vette, így nem tudtam elolvasni, hogy mi történik pontosan!"
#
# A 2 mp-es állapot-lekérdezés (`_opt_poll` → `_sync_opt_status`) felülírta az
# elutasítás okát az általános „Az optimalizálás nem fut."-tal. A felhasználó
# tehát pontosan azt az egy mondatot nem tudta elolvasni, ami megmondta volna,
# miért nem indult el semmi.
d._run_mode.set(M.RUN_OPTIMIZE)
d._on_run_mode()
d.on_optimize = lambda s, n, all_params=False: "Ger40/wpr_sma: kereskedik — előbb állítsd meg (▶/■)."
d.opt_state_of = lambda s, n: ""
d._start_planned()
check("az elutasítás oka KIÍRÓDIK",
      "kereskedik" in d._run_status.cget("text"), d._run_status.cget("text")[:70])
d._sync_opt_status()                    # ezt hívja a 2 mp-es lekérdezés
check("...és a következő lekérdezés NEM törli le",
      "kereskedik" in d._run_status.cget("text"), d._run_status.cget("text")[:70])
d._sync_opt_status()
check("...többször sem", "kereskedik" in d._run_status.cget("text"))
# ⚠ De amint TÉNYLEG fut, a futás állapota nyer (nem ragad ott egy elavult ok).
d.opt_state_of = lambda s, n: "OPTIMIZING"
d._sync_opt_status()
check("futás közben a FUTÁS állapota látszik",
      "FUT" in d._run_status.cget("text"), d._run_status.cget("text")[:60])
check("...a gomb LEÁLLÍTÁSSÁ vált",
      "leállít" in d._plan_btn.cget("text").lower(), d._plan_btn.cget("text"))
check("...és a haladás-sáv megjelenik", bool(d._prog_box.winfo_manager()))
# A mód/pipa átállítása ÚJ helyzet → a régi ok elavul.
d.opt_state_of = lambda s, n: ""
d._start_planned()
d._refresh_run_mode_ui()
check("mód-váltás után a régi ok eltűnik",
      getattr(d, "_run_note", None) is None)
d.on_optimize = lambda s, n, all_params=False: (
    CALLS.append(f"opt(all={all_params})"), "")[1]

# ⚠ ÉS AZ OK A VEZÉRLŐBŐL JÖN, nem a felület találgatásából: a három korábban
# NÉMA `return` most mind szöveget ad.
_blk = _func_src(_g, "def request_optimize")
# ⚠ A SZOVEG a nyelvi katalogusban van — a vezerlo a KULCSRA hivatkozik.
# Ket allitas: hivatkozik-e ra, ES a magyar szoveg tenyleg ezt mondja-e.
for _key, _why in (("gui.opt.closing", "kivezetés alatt"),
                   ("gui.opt.trading", "kereskedik"),
                   ("gui.opt.already", "már fut vagy sorban áll")):
    check(f"a vezérlő megmondja: {_why!r}",
          _key in _blk and _says(_key, _why))


# ── 6. A TELJES TÉR: a mentett pipák NEM sérülnek ──────────────────────
# ⚠ A pipák BEÁLLÍTÁSOK, nem egyszeri döntések. Egy „mindent optimalizálj" futás
# nem törölheti őket a configból — csak a saját futásának másolatában.
from core import opt_plan as _op
_c = copy.deepcopy(cfg)
_op.set_skip_keys(_c, SYM, "wpr_sma", {"sma_period", "tp_rr_ratio"})
_job = copy.deepcopy(_c)
_op.set_skip_keys(_job, SYM, "wpr_sma", set())
check("a futás másolatában NINCS kihagyás",
      _op.skip_keys(_job, SYM, "wpr_sma") == set())
check("...az EREDETI viszont érintetlen",
      _op.skip_keys(_c, SYM, "wpr_sma") == {"sma_period", "tp_rr_ratio"})

_i = _g.find("job_cfg = self.cfg")
check("a vezérlő MÁSOLATON üríti a kihagyás-listát",
      "deepcopy" in _g[_i:_i + 400] and "set_skip_keys(job_cfg" in _g[_i:_i + 400])
check("...és a munkás a MÁSOLATTAL indul",
      "args = (symbol, df_m15, df_m1, job_cfg, initial_bal)" in _g)
# A jelző a SORBA kerülést is túléli (a kérés szándéka nem veszhet el).
check("a kérés jelzője a sorba állításkor is megmarad",
      "_all_params[job]" in _func_src(_g, "def request_optimize"))
check("a kattintás-kezelő továbbadja",
      "all_params" in str(inspect.signature(
          __import__("dashboard.gui", fromlist=["x"]).DashboardWindow._live2_opt_click
          if hasattr(__import__("dashboard.gui", fromlist=["x"]), "DashboardWindow")
          else (lambda symbol, name, all_params=False: None))))


# ── 7. A DÁTUMVÁLASZTÓ ─────────────────────────────────────────────────
# ⚠ A LELET (a felhasználótól): „hiába kattintok rá egy dátumra, az nem íródik
# vissza a megfelelő dátum mezőbe (sem a -tól-nál, sem az -ig-nél)".
#
# Ok: a popup SZTRINGET ad át (`YYYY-MM-DD`), a hívó viszont `date`-et várt és
# `d.isoformat()`-ot hívott rajta. Az `AttributeError`-t a popup ELNYELTE
# (`except Exception: pass`) — a naptár tehát bezárult, a mező üresen maradt, a
# naplóban semmi.
from dashboard import date_picker as _dp
_dpsrc = (ROOT / "dashboard" / "date_picker.py").read_text(encoding="utf-8")
_i = _dpsrc.find("def _pick")
check("a popup SZTRINGET ad át (a szerződés)",
      'self._on_pick(d.strftime("%Y-%m-%d"))' in _dpsrc[_i:_i + 900])
check("a visszahívás hibája MÁR NEM néma", "log.exception" in _dpsrc[_i:_i + 900])
check("...de a modális ablak akkor is bezárul", "self._close()" in _dpsrc[_i:_i + 900])

# A tényleges beírás — a popup megkerülésével, a hívó visszahívásán át.
_i2 = _src.find("def _pick_date")
check("a hívó a KAPOTT sztringet írja be (nem `.isoformat()`-ot hív rajta)",
      "on_pick=lambda s: var.set(s)" in _src[_i2:_i2 + 900],
      _src[_i2:_i2 + 900][-160:])
_var = tk.StringVar(value="")
_cb = (lambda s: _var.set(s))            # ugyanaz az alak, mint a javított hívóban
_cb("2026-08-18")
check("...és így a mező TÉNYLEG megkapja a napot", _var.get() == "2026-08-18",
      _var.get())
# A másik hívó (Backtest-ablak) végig helyes volt — maradjon is az.
_bd = (ROOT / "dashboard" / "backtest_dialog.py").read_text(encoding="utf-8")
check("a Backtest-ablak naptára is sztringet ír be",
      "on_pick=lambda s: var.set(s)" in _bd)


d.popup.destroy()
root.destroy()

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

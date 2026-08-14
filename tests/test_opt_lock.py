"""Processzek KOZOTTI zar egy optimalizalasra — per (par x strategia).

⚠ A LELET (2026-08-04, ELESBEN megtortent). Egy CLI-futas
(`python main.py optimize Ger40`, 15:16) es egy GUI-bol inditott futas (19:56)
PARHUZAMOSAN dolgozott ugyanazon a (Ger40, wpr_sma) paron:

  • kozos optuna SQLite study -> a masodik `load_if_exists=True`-val ranezett az
    elsoere, es `remaining = 500 - kesz` alapjan szamolt: a „500 trial" a KETTO
    EGYUTTESE lett;
  • ugyanaz a kimeneti fajl -> a GUI 22:30-kor mentett, a CLI ~01:00-kor
    felulirta volna (kezi leallitassal allt meg);
  • eltero kodverzio (v1.95.0 vs v1.97.0) -> utolag nem bizonyithato, hogy a
    celfuggveny azonos volt.

A GUI sajat vedelme (`_symbol_busy`) csak a SAJAT sorara lat.

⚠ A ZAR HELYE: `optimize_symbol` — ez az EGYETLEN pont, amin a CLI es a GUI is
atmegy. Barmely FELULETRE tett zarat meg lehetne kerulni a masik felulettel.
"""
import inspect
import json
import os
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


from core import opt_lock as L

SYM, STRAT = "__TESZT_ZAR__", "wpr_sma"
P = L.lock_path(SYM, STRAT)
P.unlink(missing_ok=True)


def _write(**kw):
    P.write_text(json.dumps({"pid": 1, "started_at": 0.0, **kw}), encoding="utf-8")


# ── 1. ALAP ───────────────────────────────────────────────────────────────
check("zar nelkul nincs tartva", not L.is_held(SYM, STRAT))
ok, held = L.acquire(SYM, STRAT)
check("elso acquire sikerul", ok and held is None)
check("...es a fajl a STUDY MELLE kerul",
      P.exists() and P.name.endswith("_study.lock"), P.name)
check("...a sajat pid-unkkel", (L.read(SYM, STRAT) or {}).get("pid") == os.getpid())
check("mostantol TARTVA van", L.is_held(SYM, STRAT))

# ⚠ A SAJAT zarunkba ne akadjunk bele: az onmagunk kizarasa lenne, es a hivo
# szemszogebol megkulonboztethetetlen egy idegen futastol.
check("ugyanaz a processz UJRA megkaphatja", L.acquire(SYM, STRAT)[0])

check("release torli", L.release(SYM, STRAT) and not P.exists())
check("...utana mar nincs tartva", not L.is_held(SYM, STRAT))


# ── 2. ELO IDEGEN ZAR -> ELUTASITAS ──────────────────────────────────────
# Elo, de NEM a mienk: a szulo-processz biztosan letezik.
_alien = os.getppid() or 1
import time as _t
_write(pid=_alien, host="masik-gep", cmd="python main.py optimize Ger40",
       started_at=_t.time() - 3600 * 2 - 300)          # 2 ora 5 perce fut
ok, held = L.acquire(SYM, STRAT)
check("elo IDEGEN zar -> az acquire ELUTASIT", not ok and held is not None)
check("...es visszaadja, KI tartja", (held or {}).get("pid") == _alien, str(held))

# ⚠ AZ UZENET a teendot is mondja, es KIIRJA A FAJL UTVONALAT. Ha a zar tevesen
# el (PID-ujrahasznositas), ez az EGYETLEN kapaszkodo — enelkul a felhasznalo
# egy lathatatlan akadallyal allna szemben, amit nem tud feloldani.
_msg = L.describe(held, SYM, STRAT)
check("az uzenet megmondja, MIERT baj",
      "study" in _msg and "felülír" in _msg, _msg[:90])
check("...es hogy MIT tegyen", "Várd meg" in _msg or "állítsd le" in _msg)
check("...es KIIRJA a zar-fajl utvonalat", str(P) in _msg, _msg[-90:])
check("...es hogy MIOTA fut", "2 óra 5 perce" in _msg, _msg[:70])
# ⚠ Hianyzo idobelyegnel NE irjunk kort: a `0`-bol „496316 óra" lesz, ami nem
# hibauzenet, hanem zaj — aki ezt olvassa, a lenyeget veszti el.
check("...hianyzo idobelyegnel viszont SEMMIT",
      "óra" not in L.describe({"pid": 1}, SYM, STRAT).split("—")[0],
      L.describe({"pid": 1}, SYM, STRAT)[:60])

# ⚠ IDEGEN ZART NEM TORLUNK. Egy elarvult zarat atvevo processz befejezeskor
# kulonben letorolhetne annak a futasnak a zarat, amelyik idokozben atvette tole.
check("idegen zarat a release NEM torol",
      not L.release(SYM, STRAT) and P.exists())


# ── 3. ELARVULT ZAR -> ATVEHETO ──────────────────────────────────────────
# ⚠ Enelkul egy egyszeri osszeomlas OROKRE letiltana a par optimalizalasat — es
# a felhasznalo egy fajlt keresne, amirol nem tud.
_write(pid=999_999_999)          # ilyen pid nem letezik
check("halott pid -> NINCS tartva", not L.is_held(SYM, STRAT))
ok, held = L.acquire(SYM, STRAT)
check("halott pid -> a zar ATVEHETO", ok and held is None)
check("...es mar a mienk", (L.read(SYM, STRAT) or {}).get("pid") == os.getpid())
L.release(SYM, STRAT)


# ── 4. SERULT ZAR = NINCS ZAR ────────────────────────────────────────────
# Egy felig kiirt JSON miatt nem tagadhatjuk meg OROKRE az optimalizalast; a
# serules maga is azt jelzi, hogy az iro processz nem jutott a vegere.
P.write_text("{ ez nem json", encoding="utf-8")
check("serult zar -> olvasva None", L.read(SYM, STRAT) is None)
check("...tehat nem tartja semmi", not L.is_held(SYM, STRAT))
check("...es atveheto", L.acquire(SYM, STRAT)[0])
L.release(SYM, STRAT)
P.unlink(missing_ok=True)


# ── 5. A BEKOTES: az EGYETLEN kozos ponton ───────────────────────────────
import ml.optimizer as opt
_wrap = inspect.getsource(opt.optimize_symbol)
check("az optimize_symbol KERI a zarat", "opt_lock" in _wrap and "acquire" in _wrap)
check("...es elutasitaskor HIBAT ad vissza (nem indul el)",
      '"error"' in _wrap and "describe" in _wrap)
# ⚠ `finally`-val: a belso fuggvenynek ot visszatéresi aga van, plusz a
# kivetelek. Kezzel elengedni mindegyiken elobb-utobb kimaradna egy — es egy
# ottfelejtett zar a KOVETKEZO indulast tagadna meg.
check("...es MINDIG elengedi (finally)",
      "finally:" in _wrap and "release" in _wrap, "")
check("a munka kulon fuggvenyben van (a burok csak a zarat kezeli)",
      hasattr(opt, "_optimize_symbol_locked"))
_inner = inspect.getsource(opt._optimize_symbol_locked)
check("...es a belso NEM nyul a zarhoz", "opt_lock" not in _inner)

# A KET UT ugyanazon a fuggvenyen megy at — ezert eleg ide tenni a zarat.
_osrc = Path(opt.__file__).read_text(encoding="utf-8")
check("a CLI-ag is az optimize_symbol-t hivja",
      _osrc.count("optimize_symbol(symbol, df_m15, df_m1, cfg, initial_balance") >= 2,
      f"{_osrc.count('optimize_symbol(symbol, df_m15, df_m1, cfg, initial_balance')} hivas")


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

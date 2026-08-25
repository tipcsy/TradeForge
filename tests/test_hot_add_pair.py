"""Menet közben felvett instrumentum — újraindítás nélkül.

⚠ A KÉRÉS (2026-08-25): „Ha most felveszek egy új instrumentumot, akkor ugye
nem kell megint újraindítani a programot?" Addig kellett: az `all_pairs`
INDULÁSKOR épült fel, ezért a futás közben felvett pár csak a dashboardon
látszott — a motor soha nem dolgozta fel, és semmi nem mondta meg, miért.

A MEGOLDÁS HÁROM DÖNTÉSE, és mindegyik egy konkrét bajt előz meg:

  1. **A bekötés EGY függvényben** (`_bring_up_pair`), amit az induláskori
     ciklus ÉS a menet közbeni felvétel is hív. Két másolat előbb-utóbb
     elcsúszna, és az eltérés némán jelentkezne: az egyik úton induló pár
     máshogy viselkedne, mint a másikon.
  2. **A letöltés KÜLÖN SZÁLON.** Egy új instrumentum teljes előzménye percekig
     tarthat; a kereskedési körben elvégezve MINDEN pár állna addig — a már
     nyitott pozíciók kezelése is.
  3. **A bekötés viszont a FŐ SZÁLON.** A `dashboard`, az `instrument_state` és
     a `pair_states` szótárakat egyetlen szál írhatja; a két halmaz (folyamatban
     / kész) a kettő közti postaláda.

⚠ ÉS EGY NEGYEDIK, amit könnyű kihagyni: az új párt a `cfg["pairs"]`-be is be
kell tenni. Rengeteg segéd a TELJES configból keresi ki a pár beállításait
(kapuk, kereskedési mód, viz), és e nélkül a bekötött pár némán hiányos maradna.
"""
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


_lt = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")

# ── 1. EGY bekötő függvény, KÉT hívóval ────────────────────────────────
check("van közös bekötő függvény", "def _bring_up_pair(" in _lt)
check("⚠ ...és PONTOSAN kétszer hívjuk (indulás + menet közben)",
      _lt.count("_bring_up_pair(") == 3,          # 1 definíció + 2 hívás
      f"{_lt.count('_bring_up_pair(') - 1} hívás")

_i = _lt.find("for symbol, pair_cfg in all_pairs.items():\n        _bring_up_pair(")
check("az INDULÁS ezt használja", _i > 0)

# ── 2. A letöltés külön szálon, a bekötés a fő szálon ──────────────────
check("a letöltés háttérszálon indul",
      "threading.Thread(" in _lt and "_uj_par_elokeszit" in _lt)
check("⚠ ...és a fő szál csak ELINDÍTJA (nem várja meg)",
      "daemon=True, name=f\"UjPar-{_uj}\"" in _lt)
check("a szálnak SAJÁT neve van (a naplóban felismerhető)",
      'name=f"UjPar-' in _lt)

_j = _lt.find("def _uj_par_elokeszit(")
_szal = _lt[_j:_j + 1400]
check("a háttérszál az ensure_history-t hívja", "ensure_history(" in _szal)
check("⚠ ...és a sikertelen letöltés NEM néma",
      "az előzmény-letöltés nem sikerült" in _szal)
check("...a szál hibája sem viszi el a többi párt",
      "log.exception" in _szal and "TÖBBI pár fut tovább" in _szal)
check("a folyamatban-jelölés MINDIG feloldódik (finally)",
      "finally:" in _szal and "_uj_folyamatban.discard" in _szal)

# ── 3. Nem indul kétszer ugyanarra a párra ─────────────────────────────
check("⚠ ugyanarra a párra nem indul két letöltés",
      "if _uj in _uj_folyamatban:" in _lt and "continue" in _lt)
check("a két szál KÖZÖS zárral szinkronizál", "_uj_lock" in _lt)

# ── 4. A bekötés teljes: cfg, all_pairs, stratégiák ───────────────────
_k = _lt.find("for _uj, _upc in _behuzando:")
_be = _lt[_k:_k + 700]
check("a bekötés a KÉSZ párokon megy végig", _k > 0)
check("⚠ a `cfg[\"pairs\"]`-be is bekerül (különben némán hiányos volna)",
      'cfg.setdefault("pairs", {})[_uj] = _upc' in _be)
check("...az `all_pairs`-be is", "all_pairs[_uj] = _upc" in _be)
check("...és a stratégia-lista is felépül",
      "strats_by_symbol[_uj] = strategies_for(cfg, _uj)" in _be)
check("a bekötés tényét NAPLÓZZUK", "BEKÖTVE menet közben" in _be)

# ── 5. A szükséges importok modul-szinten vannak ──────────────────────
# ⚠ A `threading` és a `strategies_for` korábban CSAK lokálisan volt importálva
# — a ciklusban használva `NameError`-t adna, ami a LiveTrader szálat ölné meg.
check("a `threading` modul-szinten importált",
      "\nimport threading\n" in _lt)
check("a `strategies_for` is",
      "from strategy import get_strategy, get_strategy_by_name, strategies_for" in _lt)

# ── 6. A modul betölthető (a szintaxis és a nevek rendben) ────────────
import trading.live_trader as _mod   # noqa: E402
check("a live_trader betölthető", hasattr(_mod, "run"))
check("a threading elérhető a modulban", hasattr(_mod, "threading"))
check("a strategies_for is", hasattr(_mod, "strategies_for"))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

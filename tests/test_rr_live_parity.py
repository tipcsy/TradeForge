"""Az optimalizalo ne EGY MASIK VILAGBAN hangoljon, mint amiben a motor fut.

Lelet (2026-08-09, Ger40). Az `rr=None` ut (optimalizalo, elemzo eszkozok) a
presetet HARDKODOLTAN `off`-ra allitotta, es csak a numerikus kalibraciot huzta a
parrol. Az el viszont a `risk_mode.json`-bol olvas, ahol a par `none` volt:

    kulcs                  OPTIMALIZALO   EL
    preset                 off            none      <-- ELTER
    breakeven_pct          0.7            0.7
    trail_activation_atr   0.1            0.1
    trail_distance_atr     0.9            0.9
    BE/trailing hat?       IGEN           NEM

Vagyis az optimalizalo BE+trailinggel hangolt, az el meg sem mozditotta a stopot.
Merve (1080 kotes, 22 honap): `none` -512$ / 44,7% talalat vs `off` -414$ / 39,3%
— MAS eloszlas, mas optimum. Ugyanaz a hibaosztaly, mint az exec_gates v1.95.0
elott.

Masodik lelet: a `none` preset kapuja hianyzott az IKERPARBOL
(`_apply_be_and_trailing`), amit a no-trade orak aga preset-ellenorzes NELKUL hiv.
Ma egyik paron sincs no-trade ora -> latens; amint egy optimalizalas orakat
szukit, a `none` par a szurke orakban nemam BE-zne es trailelne.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from trading.backtest import _rr_spec
from core import rr_state, risk_reduction as rrm

# ── Determinisztikus allapot: NEM a valodi risk_mode.json-t hasznaljuk ────────
# (a teszt sosem fugghet a felhasznalo aktualis beallitasatol, es sosem irhat)
rr_state._state.clear()
rr_state._state.update({
    "NONEPAIR":  {"preset": rrm.PRESET_NONE, "breakeven_pct": 0.7,
                  "trail_activation_atr": 0.1, "trail_distance_atr": 0.9},
    "OFFPAIR":   {"preset": rrm.PRESET_OFF,  "breakeven_pct": 0.6},
    "SHIELDPAIR": {"preset": rrm.PRESET_SHIELD},
})

# ── 1. A LENYEG: az rr=None ut a par ELES presetjet veszi ─────────────────────
check("`none` paron az rr=None ut is `none` (nem hardkodolt off)",
      _rr_spec(None, False, "NONEPAIR")["preset"] == rrm.PRESET_NONE,
      _rr_spec(None, False, "NONEPAIR")["preset"])
check("`shield` paron a preset shield (nem off)",
      _rr_spec(None, False, "SHIELDPAIR")["preset"] == rrm.PRESET_SHIELD)
check("`off` paron marad off",
      _rr_spec(None, False, "OFFPAIR")["preset"] == rrm.PRESET_OFF)

# A BE/trailing TENYLEGES hatasa is egyezzen az ellel.
for sym in ("NONEPAIR", "OFFPAIR", "SHIELDPAIR"):
    o = rrm.be_trail_active(_rr_spec(None, False, sym)["preset"])
    e = rrm.be_trail_active(rr_state.spec_for(sym)["preset"])
    check(f"{sym}: a BE/trailing HATASA egyezik az ellel", o == e, f"{o} vs {e}")

# A par kalibracioja tovabbra is atjon (v1.96.0 lelet — ne essen vissza a modul
# alapertekere).
check("a par kalibracioja atjon (breakeven_pct)",
      _rr_spec(None, False, "NONEPAIR")["breakeven_pct"] == 0.7,
      str(_rr_spec(None, False, "NONEPAIR")["breakeven_pct"]))

# ── 2. Amit NEM szabad elrontani ──────────────────────────────────────────────
explicit = {"preset": rrm.PRESET_HALVING, "breakeven_pct": 0.123}
check("EXPLICIT rr mindent felulir (a regi viselkedes igy kerheto vissza)",
      _rr_spec(explicit, False, "NONEPAIR") is explicit)

check("risky=True felulirja a par presetjet (portfolio auto-risky ag)",
      _rr_spec(None, True, "NONEPAIR")["preset"] == rrm.PRESET_RISKY)
check("risky mellett is a par BE/trail kalibracioja jon",
      _rr_spec(None, True, "NONEPAIR")["breakeven_pct"] == 0.7)

check("ISMERETLEN szimbolum -> off (visszafele kompatibilis)",
      _rr_spec(None, False, "NINCSILYEN")["preset"] == rrm.PRESET_OFF)
check("szimbolum NELKUL -> off (visszafele kompatibilis)",
      _rr_spec(None, False, "")["preset"] == rrm.PRESET_OFF)

# ── 3. Az IKERPAR: a `none` kapu MINDKET agban ott legyen ────────────────────
SRC = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")

twin_pos = SRC.index("def _apply_be_and_trailing(")
twin = SRC[twin_pos:twin_pos + 4000]
check("az ikerparban van `none` kapu a breakeven elott",
      "_is_none" in twin and "0.0 if _is_none else" in twin)
check("az ikerparban a TRAILING is kapuzva van `none`-ra",
      "not _is_none" in twin)

# A fo ag a fajl KESOBBI reszen van (process_pair). Nev-fuggetlen ellenorzes: a
# ket kapunak MINDKET agban meg kell lennie, tehat a fajlban legalabb ketszer.
check("a breakeven-kapu MINDKET agban ott van (>=2 elofordulas)",
      SRC.count("0.0 if _is_none else") >= 2,
      f"{SRC.count('0.0 if _is_none else')} db")
check("a trailing-kapu MINDKET agban ott van (>=2 elofordulas)",
      SRC.count("not _is_none") >= 2, f"{SRC.count('not _is_none')} db")

main = SRC[twin_pos + 4000:]
check("a fo ag (process_pair) valtozatlanul kapuzza a breakeven-t",
      "0.0 if _is_none else" in main)
check("a fo ag valtozatlanul kapuzza a trailinget",
      "not _is_none" in main)

# A ket ag ugyanazt a kezi kapcsolot is nezi — ha valaki az egyiket atirja, ez bukik.
check("mindket ag a `trailing_enabled` kezi kapcsolot is nezi",
      "trailing_enabled" in twin and "trailing_enabled" in main)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

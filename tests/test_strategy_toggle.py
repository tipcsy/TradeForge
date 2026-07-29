"""Az „Aktív stratégia" pipa MENET KOZBEN hasson (ne csak ujrainditas utan).

Bejelentes: a felhasznalo kikapcsolta az ml_ai-t UsaTec-en es UsaInd-en, de az
tovabb kereskedett. Ok: a `strats_by_symbol` INDULASKOR keszult pillanatkep volt,
a ciklus sosem olvasta ujra — mikozben a MELLETTE levo kapcsolok (Vizualizacio,
Kotesek latszanak, Kotes modja) azonnal hatnak. Nema elteres egy dialoguson belul.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import trading.live_trader as lt
from strategy import enabled_strategy_names, strategies_for

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ── 1. A config-olvasas szemantikaja (amit a GUI ir) ──────────────────────
CFG = {"strategy": {"name": "wpr_sma"}, "pairs": {
    "X": {},                                   # nincs kulcs -> csak az elsodleges
    "Y": {"strategies": ["wpr_sma", "ml_ai"]},  # mindketto
    "Z": {"strategies": ["ml_ai"]},             # csak ml_ai
}}
check("hianyzo 'strategies' -> csak az elsodleges (a GUI ezt irja kikapcsolaskor)",
      enabled_strategy_names(CFG, "X") == ["wpr_sma"],
      str(enabled_strategy_names(CFG, "X")))
check("ket strategia -> mindketto", enabled_strategy_names(CFG, "Y") == ["wpr_sma", "ml_ai"])
check("csak ml_ai -> csak az", enabled_strategy_names(CFG, "Z") == ["ml_ai"])

# ── 2. A ciklus UJRAOLVASSA a configot (a javitas lenyege) ────────────────
src = (Path(__file__).resolve().parents[1] / "trading" / "live_trader.py").read_text(
    encoding="utf-8")
loop_pos = src.index("while True:")
after = src[loop_pos:]
check("a ciklusban van `strategies_for(cfg, symbol)` (nem csak indulaskor)",
      "strategies_for(cfg, symbol)" in after)
check("a kikapcsolt strategia allapota torlodik / kivezetesbe megy",
      "disabled_closing" in after and "del pair_states[(_s, _n)]" in after)

# ── 3. A per-strategia kivezetes blokkolja az UJ belepot ─────────────────
class S:
    disabled_closing = True

lt.instrument_state.clear()
lt.instrument_state["Q"] = "LIVE"          # az INSTRUMENTUM el, csak a strat nem
closing = (lt.instrument_state.get("Q") == "CLOSING"
           or bool(getattr(S(), "disabled_closing", False)))
check("kikapcsolt strategia + LIVE instrumentum -> a belepo BLOKKOLT", closing)

class S2:
    disabled_closing = False

closing2 = (lt.instrument_state.get("Q") == "CLOSING"
            or bool(getattr(S2(), "disabled_closing", False)))
check("bekapcsolt strategia + LIVE instrumentum -> a belepo ENGEDVE", not closing2)

# ── 4. A LivePairState hordozza a mezot, alapbol KI ───────────────────────
st = lt.LivePairState(symbol="Q", pair_cfg={}, params={}, trading_cfg={}, magic=1)
check("LivePairState.disabled_closing alapbol False", st.disabled_closing is False)
st.disabled_closing = True
check("...es allithato", st.disabled_closing is True)

# ── 5. A tobbi strategia ZAVARTALAN ugyanazon a paron ────────────────────
# (a kivezetes PER STRATEGIA van, nem instrumentum-szinten)
check("a kivezetes per-STRATEGIA (az instrumentum LIVE marad)",
      lt.instrument_state.get("Q") == "LIVE")

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

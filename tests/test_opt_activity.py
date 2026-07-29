"""Optimalizalasi tevekenyseg per (instrumentum x strategia).

Bejelentes: "Egy wpr_sma optimalizalas blokkolja a teljes instrumentumon valo
kereskedest, pedig az ml_ai ettol fuggetlen tudna mukodni."

Gyoker: az `instrument_state` KET tengelyt preselt egy valtozoba (kereskedesi
szandek + optimalizalasi tevekenyseg), ES csak szimbolum-kulccsal.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import opt_activity as oa
from core import run_state as rs

R = []


def check(name, ok, detail=""):
    R.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


oa.clear_symbol("GOLD")
oa.clear_symbol("Ger40")

# ══ 1. Alapok: per (symbol, strategy) ═════════════════════════════════════
check("ures allapot -> nincs tevekenyseg", oa.state_of("GOLD", "wpr_sma") is None)
check("...es a szimbolum sem foglalt", oa.symbol_busy("GOLD") is False)

oa.set_state("GOLD", "wpr_sma", oa.RUNNING, "Indul...")
check("a jelolt strategia FUT", oa.state_of("GOLD", "wpr_sma") == oa.RUNNING)

# ══ 2. A LENYEG: a MASIK strategia ERINTETLEN ════════════════════════════
check("a masik strategia UGYANAZON a paron NEM foglalt",
      oa.busy("GOLD", "ml_ai") is False)
check("...es a masik PAR sem", oa.busy("Ger40", "wpr_sma") is False)

# ══ 3. Szimbolum-szintu OSSZEVONAS (a jelenlegi egysoros kijelzeshez) ════
check("a szimbolum osszevont allapota OPTIMIZING",
      oa.symbol_state("GOLD") == oa.RUNNING)
oa.set_state("Ger40", "ml_ai", oa.QUEUED, "Varakozik...")
check("csak sorban allo -> QUEUED", oa.symbol_state("Ger40") == oa.QUEUED)
oa.set_state("Ger40", "wpr_sma", oa.RUNNING)
check("futo + sorban allo -> a FUTO nyer (az a lenyeges)",
      oa.symbol_state("Ger40") == oa.RUNNING)

# ══ 4. Statusz-szoveg ════════════════════════════════════════════════════
oa.set_status("GOLD", "wpr_sma", "40/500  8%")
check("statusz frissitheto", oa.status_of("GOLD", "wpr_sma") == "40/500  8%")
check("a szimbolum-szintu statusz a FUTOe", oa.symbol_status("GOLD") == "40/500  8%")
oa.set_status("GOLD", "ml_ai", "ez sehova")
check("nem letezo bejegyzesre a statusz NEM hoz letre allapotot",
      oa.state_of("GOLD", "ml_ai") is None)

# ══ 5. Torles: csak a sajatjat ═══════════════════════════════════════════
oa.set_state("Ger40", "wpr_sma", None)
check("a futo torolve -> a sorban allo marad", oa.symbol_state("Ger40") == oa.QUEUED)
check("...es tenyleg a masik maradt", oa.state_of("Ger40", "ml_ai") == oa.QUEUED)
oa.clear_symbol("Ger40")
check("clear_symbol mindent visz", oa.symbol_state("Ger40") is None)
check("...de a MASIK parra nincs hatasa", oa.symbol_state("GOLD") == oa.RUNNING)

# ══ 6. A `busy` a SORBAN ALLOT is szamitja ═══════════════════════════════
# (barmikor indulhat, tehat a kereskedest mar ott fel kell fuggeszteni)
oa.set_state("GOLD", "ml_ai", oa.QUEUED)
check("a sorban allo strategia is 'busy'", oa.busy("GOLD", "ml_ai") is True)
oa.set_state("GOLD", "ml_ai", None)

# ══ 7. run_state: a kereskedesi szandek PER STRATEGIA ════════════════════
oa.clear_symbol("GOLD")          # tiszta lap: a fenti szakaszok maradeka nelkul
CFG = {"pairs": {"GOLD": {"enabled": True,
                          "run_state": {"wpr_sma": "live", "ml_ai": "stopped"}}}}
check("wpr_sma live", rs.get_state(CFG, "GOLD", "wpr_sma", "wpr_sma") == rs.LIVE)
check("ml_ai stopped", rs.get_state(CFG, "GOLD", "ml_ai", "wpr_sma") == rs.STOPPED)

# Ez a kombinacio a bejelentes magja: a par KERESKEDIK (wpr_sma), es kozben az
# ml_ai-t optimalizaljuk. A regi kod ezt nem engedte (szimbolum-szintu LIVE-tiltas).
oa.set_state("GOLD", "ml_ai", oa.RUNNING)
_live_and_optimizing = (rs.get_state(CFG, "GOLD", "wpr_sma", "wpr_sma") == rs.LIVE
                        and oa.busy("GOLD", "ml_ai"))
check("A BEJELENTES ESETE: wpr_sma kereskedik ES az ml_ai optimalizal",
      _live_and_optimizing)
check("...es a kereskedo strategia NINCS felfuggesztve",
      oa.busy("GOLD", "wpr_sma") is False)

# ══ 8. A forditott irany: a kereskedo strategiat NEM optimalizaljuk ══════
# (a futas vegen felulirodna a parameterfajlja) — ezt a GUI _strategy_live
# ellenorzi; itt a run_state-alapu dontest igazoljuk.
check("a kereskedo strategia LIVE -> a keres elutasitando",
      rs.get_state(CFG, "GOLD", "wpr_sma", "wpr_sma") == rs.LIVE)

oa.clear_symbol("GOLD")
check("takaritas utan tiszta", oa.symbol_state("GOLD") is None)

print()
print(f"{sum(R)}/{len(R)} teszt PASS")
sys.exit(0 if all(R) else 1)

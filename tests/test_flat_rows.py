"""LAPOS elrendezes: egy sor = egy (instrumentum x strategia).

A szulo-gyerek fat a felhasznalo elvetette, negy konkret erevel:
  1. csukva nem latszik, melyik strategia hol tart;
  2. a NYITOTT poziciok sem latszanak, csak a lezartak osszege;
  3. ezert mindig mindent ki kellene nyitni -> a fa csak plusz ures sorokat ad;
  4. "keresni kell a sorokat".

Ez a teszt azt orzi, hogy a lapos valtozat mind a negyre valaszol.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import applog
applog.harden_console()

from dashboard.flat_rows import (COLUMNS, EDGE, INSTRUMENT_KEYS, SORT_WEIGHT,
                                 order, row_state)

R = []


def check(name, ok, detail=""):
    R.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ══ 1. SEMMI nincs elrejtve: minden lenyeges oszlop egy sorban ═══════════
keys = [c.key for c in COLUMNS]
check("a strategia neve a SORBAN van (nem kell kinyitni)", "strategy" in keys)
check("a kapuk a sorban", "gates" in keys)
check("a Minoseg a sorban", "quality" in keys)
check("NYITOTT pozicio ELO eredmenye kulon oszlop (a 2. panasz)",
      "open" in keys, str(keys))
check("...es a LEZARTAK napi osszege KULON", "daily" in keys)
check("az instrumentum-adatok csak a csoport elso soraban ismetlodnek",
      set(INSTRUMENT_KEYS) < set(keys))

# ══ 2. Allapot-kulcs: mi a sor "sulya" ═══════════════════════════════════
check("nyitott pozicio MINDENT megeloz",
      row_state(has_position=True, blocked=True, signal_only=True, live=False)
      == "position")
check("nem-elo (Stop) -> idle",
      row_state(has_position=False, blocked=False, signal_only=False, live=False)
      == "idle")
check("blokkolt", row_state(has_position=False, blocked=True,
                            signal_only=False, live=True) == "blocked")
check("csak jelzes", row_state(has_position=False, blocked=False,
                               signal_only=True, live=True) == "signal")
check("egeszseges elo", row_state(has_position=False, blocked=False,
                                  signal_only=False, live=True) == "live")
check("minden allapotnak van SZINE a bal csikhoz",
      set(SORT_WEIGHT) == set(EDGE), f"{set(SORT_WEIGHT) ^ set(EDGE)}")
check("a nyitott pozicio a legkisebb suly (legfelul)",
      SORT_WEIGHT["position"] == min(SORT_WEIGHT.values()))


def it(sym, strat, state, order_idx=0):
    return {"symbol": sym, "strategy": strat, "state": state,
            "strategy_order": order_idx}


# ══ 3. A 4. panasz: "keresni kell a sorokat" ═════════════════════════════
items = [
    it("UK100", "wpr_sma", "live", 0),   it("UK100", "ml_ai", "signal", 1),
    it("GOLD",  "wpr_sma", "position", 0), it("GOLD", "ml_ai", "blocked", 1),
    it("EURUSD", "wpr_sma", "live", 0),  it("EURUSD", "ml_ai", "signal", 1),
    it("Ger40", "wpr_sma", "blocked", 0), it("Ger40", "ml_ai", "signal", 1),
]
out = order(items)
seq = [(x["symbol"], x["strategy"]) for x in out]

check("a NYITOTT POZICIOS par a tabla tetejen", seq[0][0] == "GOLD", str(seq[:2]))
check("...a blokkolo par kovetkezik", seq[2][0] == "Ger40", str(seq[2:4]))
# A csoport EGYSEGE: egy par sorai nem szorodhatnak szet a tablaban
groups = []
for s, _ in seq:
    if not groups or groups[-1] != s:
        groups.append(s)
check("egy instrumentum sorai EGYUTT maradnak (nincs szetszorodas)",
      len(groups) == len(set(groups)), str(groups))

# ══ 4. A LENYEG: a csoporton BELULI sorrend ALLANDO ══════════════════════
# Az elso valtozat itt is fontossag szerint rendezett -> az egyik paron a
# wpr_sma, a masikon az ml_ai lett az elso sor. Pontosan ettol kell keresni.
firsts = {}
for s, st in seq:
    firsts.setdefault(s, st)
check("MINDEN csoport ugyanazzal a strategiaval kezdodik",
      len(set(firsts.values())) == 1, str(firsts))
check("...es az a strategy_order szerinti elso", set(firsts.values()) == {"wpr_sma"})

# Akkor is, ha a MASODIK strategia "fontosabb" allapotban van
items2 = [it("X", "wpr_sma", "live", 0), it("X", "ml_ai", "position", 1)]
seq2 = [(x["symbol"], x["strategy"]) for x in order(items2)]
check("a fontosabb allapotu MASODIK strategia sem elozi meg az elsot",
      seq2[0][1] == "wpr_sma", str(seq2))

# ══ 5. Robusztussag ══════════════════════════════════════════════════════
check("ures lista -> ures", order([]) == [])
check("ismeretlen allapot -> nem robban, a vegere kerul",
      order([it("A", "s", "valami_uj"), it("B", "s", "position")])[0]["symbol"] == "B")

print()
print(f"{sum(R)}/{len(R)} teszt PASS")
sys.exit(0 if all(R) else 1)

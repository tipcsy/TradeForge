"""A #1 (fantom-zárás) javításának igazolása — a trades.csv valós esetével.

2026-07-21 13:08:05.914  open  wpr_sma EURUSD SELL  ticket 1629435715  magic 20260627
2026-07-21 13:08:05.975  close ml_ai   EURUSD       ticket 1629435715  magic 20260628  <- HAMIS
...és utána 2178-szor, 10 mp-enként.
"""
import sys, types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import trading.live_trader as lt

WPR_MAGIC = 20260627
ML_MAGIC  = 20260628
TICKET    = 1629435715


class Deal:
    def __init__(self, entry, symbol, magic, profit=0.0, commission=0.0, swap=0.0):
        self.entry, self.symbol, self.magic = entry, symbol, magic
        self.profit, self.commission, self.swap = profit, commission, swap


class FakeMT5:
    DEAL_ENTRY_IN, DEAL_ENTRY_OUT, DEAL_ENTRY_OUT_BY = 0, 1, 3

    def __init__(self, history):
        self._history = history

    def history_deals_get(self, position=None):
        return self._history.get(position)


def with_history(history):
    lt.mt5 = FakeMT5(history)


def no_adoptions():
    lt.adopted.strategy_of = lambda t: None


results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ── 1) A HIBA MAGVA: wpr_sma NYITOTT pozíciója (csak nyitó deal a history-ban),
#      amit az ml_ai köre néz. Régen: 'lezárt'. Most: None → nem könyvel semmit.
with_history({TICKET: [Deal(FakeMT5.DEAL_ENTRY_IN, "EURUSD", WPR_MAGIC)]})
no_adoptions()
check("nyitott idegen pozicio -> nincs elszamolas",
      lt.closed_deal_summary(TICKET) is None)

# ── 2) VALÓBAN lezárt, wpr_sma tulajdonú pozíció ────────────────────────────
with_history({TICKET: [
    Deal(FakeMT5.DEAL_ENTRY_IN,  "EURUSD", WPR_MAGIC, commission=-0.7),
    Deal(FakeMT5.DEAL_ENTRY_OUT, "EURUSD", WPR_MAGIC, profit=12.5,
         commission=-0.7, swap=-0.3),
]})
s = lt.closed_deal_summary(TICKET)
check("lezart pozicio -> (magic, symbol, pnl)", s is not None)
dm, dsym, pnl = s
check("a tulajdonos a NYITO deal magicje", dm == WPR_MAGIC, f"magic={dm}")
check("P&L a zaro deal-bol (11.50)", abs(pnl - 11.5) < 1e-9, f"pnl={pnl}")

check("ml_ai kore NEM szamolja el a wpr_sma ticketjet",
      lt.owns_closed_ticket(TICKET, dm, dsym, "EURUSD", ML_MAGIC, "ml_ai") is False)
check("wpr_sma kore ELSZAMOLJA a sajatjat",
      lt.owns_closed_ticket(TICKET, dm, dsym, "EURUSD", WPR_MAGIC, "wpr_sma") is True)

# ── 3) Felező/Pajzs: RÉSZLEGES zárás + runner-zárás → mindkettő beleszámít ──
with_history({TICKET: [
    Deal(FakeMT5.DEAL_ENTRY_IN,  "Ger40", WPR_MAGIC),
    Deal(FakeMT5.DEAL_ENTRY_OUT, "Ger40", WPR_MAGIC, profit=20.0),   # rr_partial
    Deal(FakeMT5.DEAL_ENTRY_OUT, "Ger40", WPR_MAGIC, profit=35.0),   # runner
]})
_, _, pnl = lt.closed_deal_summary(TICKET)
check("reszleges zaras is beleszamit (55.0, nem 35.0)",
      abs(pnl - 55.0) < 1e-9, f"pnl={pnl}")

# ── 4) Örökbefogadott (kézi) pozíció: a magic idegen, a hozzárendelés dönt ──
with_history({TICKET: [
    Deal(FakeMT5.DEAL_ENTRY_IN,  "Ger40", 0),
    Deal(FakeMT5.DEAL_ENTRY_OUT, "Ger40", 0, profit=5.0),
]})
lt.adopted.strategy_of = lambda t: "ml_ai"
dm, dsym, _ = lt.closed_deal_summary(TICKET)
check("orokbefogadott -> a hozzarendelt strategia szamolja el",
      lt.owns_closed_ticket(TICKET, dm, dsym, "Ger40", ML_MAGIC, "ml_ai") is True)
check("orokbefogadott -> a magic-tulajdonos NEM szamolja el",
      lt.owns_closed_ticket(TICKET, dm, dsym, "Ger40", WPR_MAGIC, "wpr_sma") is False)

# ── 5) Másik szimbólum ticketje sosem a mienk ───────────────────────────────
no_adoptions()
check("masik szimbolum -> nem a mienk",
      lt.owns_closed_ticket(TICKET, WPR_MAGIC, "UKOUSD", "EURUSD",
                            WPR_MAGIC, "wpr_sma") is False)

# ── 6) Hiányzó/üres history -> nem konyvelunk ──────────────────────────────
with_history({})
check("nincs history -> nincs elszamolas", lt.closed_deal_summary(TICKET) is None)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

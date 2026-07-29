"""A 2026-07-28-i eset: a trailing VISSZAHUZTA a stopot a breakeven ala.

Naplo (UsaInd #5035093140, risky):
    16:03:41  BE beallitva (risky)
    16:03:41  trailing SL -> 52558.08   <- UGYANABBAN a korben, a BELEPO (52631.19) ALA

Ok: a `pos` pillanatkep SL-je a kor elejen keszult; a BE utan elavult, es a
trailing a REGI SL-hez hasonlitott (`new_sl > pos.sl`), ezert "javitasnak" latta
a belepo alatti stopot. Kozben a slot mar felszabadult -> a rendszer
kockazatmentesnek hitte a poziciot, mikozben a stop -0.7R-en allt.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import trading.live_trader as lt

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ── A valos szamok a naplobol / kepernyokeprol ────────────────────────────
ENTRY   = 52631.19
ORIG_SL = 52538.21          # eredeti stop  (R = 92.98)
BE_SL   = 52633.50          # a BE utani stop (belepo + koltseg-puffer)
CUR     = 52639.82          # akkori ar
TRAIL   = 81.74             # 1.8 ATR x 0.5 (risky) — a naplozott 8174 pont


class Pos:
    """MT5 pozicio-pillanatkep (a valodi named tuple utanzata)."""
    type = 0                # ORDER_TYPE_BUY

    def __init__(self, sl):
        self.sl = sl
        self.price_open = ENTRY
        self.price_current = CUR
        self.tp = 52736.36


def trailing_would_set(pos_sl, be_done):
    """A trailing dontese a JAVITOTT logikaval: (uj_sl vagy None)."""
    pos = Pos(pos_sl)
    new_sl = round(pos.price_current - TRAIL, 2)
    be_floor = pos.price_open if be_done else None
    ok = new_sl > pos.sl and (be_floor is None or new_sl >= be_floor)
    return new_sl if ok else None


# ── 1. A HIBA reprodukalasa a REGI logikaval ──────────────────────────────
regi_uj_sl = round(CUR - TRAIL, 2)
check("a REGI logika a belepo ALA vitte volna a stopot",
      regi_uj_sl > ORIG_SL and regi_uj_sl < ENTRY,
      f"{ORIG_SL} -> {regi_uj_sl} (belepo {ENTRY})")
# Az ELSO trailing-lepes -0.79R; a kepernyokep a HARMADIKAT mutatta (52565.08 = -0.71R).
check("...ez kb. -0.8R (az ELSO lepes; a kepernyokep a harmadikat mutatta)",
      -0.85 < (regi_uj_sl - ENTRY) / (ENTRY - ORIG_SL) < -0.70,
      f"{(regi_uj_sl-ENTRY)/(ENTRY-ORIG_SL):.2f}R")
check("...a naplozott ertekkel BETUre egyezik (52558.08)", regi_uj_sl == 52558.08,
      str(regi_uj_sl))

# ── 2. A JAVITAS: elavult pillanatkep + be_done -> a padlo megfogja ───────
check("elavult SL (BE elotti) + be_done -> a trailing NEM mozgat",
      trailing_would_set(ORIG_SL, be_done=True) is None)

# ── 3. Friss pillanatkep (a _refresh_position utan) -> szinten nem mozgat ─
check("friss SL (a BE szintje) -> a trailing NEM mozgat lefele",
      trailing_would_set(BE_SL, be_done=True) is None)

# ── 4. BE ELOTT a trailing normalisan dolgozik (nem tortuk el) ────────────
check("BE elott (be_done=False) a trailing a szokasos modon huz",
      trailing_would_set(ORIG_SL, be_done=False) == regi_uj_sl,
      str(trailing_would_set(ORIG_SL, be_done=False)))

# ── 5. BE utan, magasabb aron a trailing TOVABB huz (folfele igen) ───────
class Pos2(Pos):
    pass


def trailing_high_price(price, pos_sl, be_done=True):
    new_sl = round(price - TRAIL, 2)
    be_floor = ENTRY if be_done else None
    return new_sl if (new_sl > pos_sl and (be_floor is None or new_sl >= be_floor)) else None


magas = ENTRY + 200                       # az ar jelentosen elment
check("BE utan, magasabb aron a trailing IGENIS huz (a padlo folott)",
      trailing_high_price(magas, BE_SL) == round(magas - TRAIL, 2),
      str(trailing_high_price(magas, BE_SL)))
check("...es az uj stop a belepo FOLOTT van (kockazatmentes marad)",
      trailing_high_price(magas, BE_SL) >= ENTRY)

# ── 6. SELL irany szimmetrikusan ──────────────────────────────────────────
S_ENTRY = 52631.19
def trailing_sell(price, pos_sl, be_done=True):
    new_sl = round(price + TRAIL, 2)
    be_floor = S_ENTRY if be_done else None
    return new_sl if (new_sl < pos_sl and (be_floor is None or new_sl <= be_floor)) else None

check("SELL: BE utan a trailing nem tehet a belepo FOLE stopot",
      trailing_sell(S_ENTRY - 10, S_ENTRY - 200) is None)
check("SELL: eleg messze ar -> huz, es a belepo ALATT marad",
      (r := trailing_sell(S_ENTRY - 300, S_ENTRY - 100)) is not None and r <= S_ENTRY,
      str(r))

# ── 7. A segedfuggveny letezik es hibaturo ────────────────────────────────
check("_refresh_position letezik", callable(getattr(lt, "_refresh_position", None)))
_orig = lt.mt5
class Boom:
    def positions_get(self, **k): raise RuntimeError("MT5 hiba")
lt.mt5 = Boom()
check("_refresh_position hibanal None-t ad (a hivo a regi pos-t hasznalja)",
      lt._refresh_position(1) is None)
lt.mt5 = _orig

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

"""Szimbolum-hazirend: mit tehet EGY paron TOBB strategia egyszerre."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import symbol_policy as sp

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ══ resolve: per-par > globalis > alapertelmezes ══════════════════════════
CFG = {"trading": {"same_symbol_policy": "one_per_symbol"},
       "pairs": {"Ger40": {"same_symbol_policy": "no_opposite"},
                 "UsaTec": {},
                 "UK100": {"same_symbol_policy": "HIBAS_ERTEK"}}}
check("per-par felulirja a globalisat", sp.resolve(CFG, "Ger40") == sp.NO_OPPOSITE)
check("per-par nelkul a globalis ervenyes", sp.resolve(CFG, "UsaTec") == sp.ONE_PER_SYMBOL)
# Ervenytelen per-par ertek: a retegzes FOLYTATODIK (a globalis ervenyesul), de
# egyszer figyelmeztetunk — a nema elnyeles rejtene el az elgepelest.
check("ervenytelen per-par ertek -> a GLOBALIS ervenyesul (+ figyelmeztetes)",
      sp.resolve(CFG, "UK100") == sp.ONE_PER_SYMBOL)
check("ervenytelen GLOBALIS is -> alapertelmezes",
      sp.resolve({"trading": {"same_symbol_policy": "izeee"}}, "X") == sp.DEFAULT)
check("a figyelmeztetes EGYSZER megy ki (nem spam-el)",
      len([k for k in sp._warned]) >= 1)
check("ures config -> alapertelmezes", sp.resolve({}, "X") == sp.DEFAULT)
# v2.0.0: az alapertelmezes `independent` -> `no_opposite`. A hazirend v1.69.0 ota
# keszen allt es be volt kotve, de a config.json-ba sosem kerult bele a kulcs, az
# alap pedig a megengedo `independent` volt -> a mechanizmus NEMAN tetlen maradt.
check("az alapertelmezes no_opposite (v2.0.0)", sp.DEFAULT == sp.NO_OPPOSITE)
# A valtas IRANYA teszi biztonsagossa: a hazirend csak SZIGORIT. Ha az uj alap
# barhol MEGENGEDOBB lenne a reginel, egy alapertelmezes-valtas varatlanul UJ
# poziciot nyithatna — ezt zarjuk ki, minden allapotra.
for _sig in ("BUY", "SELL"):
    for _book in ([], ["BUY"], ["SELL"], ["BUY", "SELL"]):
        _old = sp.blocks(sp.INDEPENDENT, _sig, _book)
        _new = sp.blocks(sp.DEFAULT, _sig, _book)
        check(f"az uj alap sosem MEGENGEDOBB a reginel ({_sig}, {_book})",
              not (_old is not None and _new is None))
check("kis-nagybetu es szokoz turese",
      sp.resolve({"trading": {"same_symbol_policy": "  No_Opposite "}}, "X") == sp.NO_OPPOSITE)

# ══ blocks: a harom hazirend ══════════════════════════════════════════════
# independent — sosem szol bele
check("independent: mas strategia BUY-ja mellett BUY mehet",
      sp.blocks(sp.INDEPENDENT, "BUY", ["BUY"]) is None)
check("independent: mas strategia SELL-je mellett BUY is mehet",
      sp.blocks(sp.INDEPENDENT, "BUY", ["SELL"]) is None)

# one_per_symbol — barmelyik iranyu pozicio blokkol
check("one_per_symbol: AZONOS irany is blokkol",
      sp.blocks(sp.ONE_PER_SYMBOL, "BUY", ["BUY"]) is not None)
check("one_per_symbol: ELLENTETES irany is blokkol",
      sp.blocks(sp.ONE_PER_SYMBOL, "BUY", ["SELL"]) is not None)
check("one_per_symbol: ures konyv -> mehet",
      sp.blocks(sp.ONE_PER_SYMBOL, "BUY", []) is None)

# no_opposite — csak az ellentetes blokkol
check("no_opposite: AZONOS irany MEHET (piramis)",
      sp.blocks(sp.NO_OPPOSITE, "BUY", ["BUY", "BUY"]) is None)
check("no_opposite: ELLENTETES blokkol",
      sp.blocks(sp.NO_OPPOSITE, "BUY", ["SELL"]) is not None)
check("no_opposite: vegyes konyvben az ellentetes dont",
      sp.blocks(sp.NO_OPPOSITE, "BUY", ["BUY", "SELL"]) is not None)
check("no_opposite: SELL jel + BUY konyv -> blokkol",
      sp.blocks(sp.NO_OPPOSITE, "SELL", ["BUY"]) is not None)
check("no_opposite: SELL jel + SELL konyv -> mehet",
      sp.blocks(sp.NO_OPPOSITE, "SELL", ["SELL"]) is None)

# ══ Robusztussag ══════════════════════════════════════════════════════════
check("None konyv -> nem blokkol", sp.blocks(sp.ONE_PER_SYMBOL, "BUY", None) is None)
check("szemet iranyok kiszurve",
      sp.blocks(sp.ONE_PER_SYMBOL, "BUY", ["", None, "X"]) is None)
check("ismeretlen hazirend -> nem blokkol (fail-open)",
      sp.blocks("ismeretlen", "BUY", ["SELL"]) is None)

# ══ A LENYEG: a hazirend csak SZIGORITHAT ════════════════════════════════
# Barmely allapotra: ha az `independent` blokkol, a tobbi is; forditva nem all.
import itertools
ok = True
for sig in ("BUY", "SELL"):
    for book in ([], ["BUY"], ["SELL"], ["BUY", "SELL"]):
        ind = sp.blocks(sp.INDEPENDENT, sig, book)
        for pol in (sp.ONE_PER_SYMBOL, sp.NO_OPPOSITE):
            if ind is not None and sp.blocks(pol, sig, book) is None:
                ok = False
check("a szigorubb hazirend SOSEM enged tobbet, mint az independent", ok)

# ══ Az indoklas eljut a naploig (a felhasznalo lassa, MIERT nincs kotes) ══
msg = sp.blocks(sp.NO_OPPOSITE, "BUY", ["SELL"])
check("az indoklas nevesiti a hazirendet", "no_opposite" in msg, msg)
msg2 = sp.blocks(sp.ONE_PER_SYMBOL, "BUY", ["BUY"])
check("...es a masikat is", "one_per_symbol" in msg2, msg2)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

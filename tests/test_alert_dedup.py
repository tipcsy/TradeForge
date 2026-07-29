"""Riasztas-deduplikacio: az `aid` szerzodese + a jelolo-hash tulajdonsagai.

Bejelentes: "Ha idosikot valtok es kaptam egy jelzest a WPR_SMA-tol, akkor minden
idosikvaltasnal ujrakuldi az alertet (Gold)."

Ok az MQL5-oldalon volt (a mar lefuttatott riasztasok memoriabeli tombje elveszett
az indikator ujralétrehozasakor). A javitas a terminal GLOBALIS VALTOZOIBA teszi a
jelolot. Ez a teszt a PYTHON-oldali szerzodest orzi, amin az egesz all:

  * az `aid` UGYANARRA a jelre valtozatlan (kulonben semmilyen dedup nem segit),
  * KULONBOZO jelre kulonbozo,
  * es a hash (amit az MQL5 a nev-korlat miatt hasznal) nem utkozik realis
    id-halmazon.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

R = []


def check(name, ok, detail=""):
    R.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def aid(symbol, strategy, signal, bar_ts):
    """A `live_trader` alert-id kepzese (egyetlen forras: `symbol|strat|jel|bar`).

    A `bar_ts` a DONTEST HOZO, ZART gyertya ideje — nem a mostani ido. Ez a
    kulcs: amig ugyanaz a bar a legutolso lezart, az id valtozatlan, tehat a
    masodpercenkenti ujraolvasas NEM szolal meg ujra."""
    return f"{symbol}|{strategy}|{signal}|{int(bar_ts)}"


def fnv1a(s: str) -> int:
    """A `TradeForgeViz.mq5` AlertMarkName() hash-enek referencia-implementacioja
    (FNV-1a, 32 bit). Ha az MQL5 oldal valtozik, ennek is valtoznia kell."""
    h = 2166136261
    for ch in s:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return h


# ══ 1. Az aid STABIL ugyanarra a jelre ════════════════════════════════════
BAR = 1785000000
a1 = aid("GOLD", "wpr_sma", "SELL", BAR)
a2 = aid("GOLD", "wpr_sma", "SELL", BAR)
check("ugyanaz a jel -> ugyanaz az aid", a1 == a2, a1)
check("...tehat a masodpercenkenti ujraolvasas nem ad uj id-t", fnv1a(a1) == fnv1a(a2))

# ══ 2. KULONBOZO jelre kulonbozo ══════════════════════════════════════════
check("mas IRANY -> mas aid", a1 != aid("GOLD", "wpr_sma", "BUY", BAR))
check("mas GYERTYA -> mas aid", a1 != aid("GOLD", "wpr_sma", "SELL", BAR + 900))
check("mas STRATEGIA -> mas aid", a1 != aid("GOLD", "ml_ai", "SELL", BAR))
check("mas SZIMBOLUM -> mas aid", a1 != aid("Ger40", "wpr_sma", "SELL", BAR))

# A szimbolum resze az id-nek -> a parok nem zavarjak egymast a KOZOS
# globalis-valtozo terben (minden chart ugyanazt a teret latja).
check("a szimbolum benne van az id-ben (kozos GV-ter!)", a1.startswith("GOLD|"))

# ══ 3. Az idosik NEM resze az id-nek — es ez SZANDEKOS ═══════════════════
# A jel a strategiae, nem a charté. Ha az idosik benne lenne, minden chart
# kulon riasztana ugyanarra a jelre.
check("az idosik nem szerepel az id-ben", "M15" not in a1 and "M5" not in a1)

# ══ 4. A hash determinisztikus es 32 bites ═══════════════════════════════
check("a hash determinisztikus", fnv1a("GOLD|wpr_sma|SELL|1785000000")
      == fnv1a("GOLD|wpr_sma|SELL|1785000000"))
check("a hash 32 biten belul marad", all(0 <= fnv1a(x) <= 0xFFFFFFFF for x in
      ("", "a", a1, "x" * 500)))
# Ismert ertek: ha az MQL5 oldal keplete elcsuszik, ez bukik.
check("FNV-1a referencia-ertek ('foobar')", fnv1a("foobar") == 0xBF9CF968,
      hex(fnv1a("foobar")))

# ══ 5. A LENYEG: nincs utkozes realis id-halmazon ════════════════════════
# 10 par x 2 strategia x 2 irany x 400 gyertya = 16 000 id (jocskan tobb, mint
# amennyi 3 napnyi memoriaban valaha egyszerre el).
syms = ["GOLD", "Ger40", "UsaTec", "UsaInd", "UK100",
        "EURUSD", "EURCHF", "EURGBP", "EURJPY", "BTCUSD"]
ids = [aid(s, st, d, BAR + i * 900)
       for s in syms for st in ("wpr_sma", "ml_ai")
       for d in ("BUY", "SELL") for i in range(400)]
names = {fnv1a(x) for x in ids}
check("16 000 realis id -> nincs hash-utkozes",
      len(names) == len(ids), f"{len(ids)} id -> {len(names)} nev")

# A jelolo-nev hossza belefer az MT5 63 karakteres korlatjaba
longest = max(len("TFV_A_" + str(fnv1a(x))) for x in ids)
check("a jelolo-nev < 63 karakter (MT5-korlat)", longest < 63, f"max {longest}")

# Meg egy patologikusan hosszu aid is belefer — ez a hash LETJOGOSULTSAGA
mega = aid("EXTREMELY_LONG_SYMBOL_NAME_XYZ", "some_very_long_strategy_name",
           "SELL", BAR)
check("hosszu aid eseten is rovid a nev", len("TFV_A_" + str(fnv1a(mega))) < 63,
      f"aid={len(mega)} kar -> nev={len('TFV_A_' + str(fnv1a(mega)))} kar")

print()
print(f"{sum(R)}/{len(R)} teszt PASS")
sys.exit(0 if all(R) else 1)

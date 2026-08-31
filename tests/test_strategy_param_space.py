"""Minden stratégiának legyen VALÓDI keresési tere — és leírása.

⚠ A LELET (2026-08-31, a felhasználó kérdéséből): „a paraméterezésénél nincs
lehetőség a tól-ig változtatására". Az ablak valóban nem mutatott
tartomány-mezőket a `trend_pullback`-nél — de a hiány nem az ablakban volt.

A stratégia configja a tartományokat egy beágyazott `ranges` alkulcs alá tette:

    "optimizer": { "ranges": { "stoch_period": {"min": 9, "max": 21} } }

Minden MÁS stratégia KÖZVETLENÜL az `optimizer` alá teszi őket, és a kód is
onnan olvas — a `ranges` kulcsra EGYETLEN kódhely sem hivatkozik. Mérve:

    trend_pullback:  1 kombináció, 0 változó dimenzió
    wpr_sma:        50 kombináció, 15 változó dimenzió

⚠ ÉS AMIÉRT EZ TÖBB EGY FELÜLETI HIÁNYNÁL: így a stratégiát **nem lehetett
optimalizálni**. Az `Opt` gomb elindult volna, 500 trialt futtat, mindegyik
UGYANAZZAL a paraméterkészlettel — és a végén „kész"-t jelent. Semmi nem szólt
volna: se hiba, se figyelmeztetés, csak egy értelmetlen eredmény.

Ez a teszt a SZERZŐDÉST méri, nem egy konkrét stratégiát: minden bejegyzettre
lefut, tehát egy új stratégia ugyanezt nem hozhatja vissza.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import logging
logging.disable(logging.INFO)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from strategy import get_strategy_by_name, registered_strategy_names
from strategy.settings import config_for_strategy, load_config
from trading.live_trader import default_params

cfg = load_config("config.json")
nevek = registered_strategy_names()
check("van bejegyzett stratégia", bool(nevek), ", ".join(nevek))

for nev in nevek:
    st = get_strategy_by_name(nev)
    cs = config_for_strategy(cfg, nev)
    bp = default_params(st, cs)

    # ⚠ A TANÍTHATÓ stratégiánál (`fit`) az „optimalizálás" MODELL-TANÍTÁS, nem
    # paraméter-keresés — ott a nulla dimenzió a helyes állapot. A kivételt NEM
    # névsorral adjuk meg, hanem UGYANAZZAL a feltétellel, amivel az optimalizáló
    # dönt (`ml/optimizer.py`: `callable(getattr(strategy, "fit", None))`). Egy
    # kézzel karbantartott lista előbb-utóbb elcsúszna a kódtól.
    _tanithato = callable(getattr(st, "fit", None))

    # ── 1. A KERESÉSI TÉR nem üres ─────────────────────────────────────
    try:
        ter = st.param_space(cs, bp, "random", 40)
    except Exception as ex:
        ter = []
        check(f"'{nev}': a param_space lefut", False, f"{type(ex).__name__}: {ex}")
    else:
        check(f"'{nev}': a param_space lefut", True)

    valtozo = {k for komb in ter for k, v in komb.items()
               if any(masik.get(k) != v for masik in ter)}
    # ⚠ EGY dimenzió is kevés volna: az optimalizálás értelme a KOMBINÁCIÓK
    # keresése. A küszöb szándékosan alacsony (≥2) — nem a tér méretét
    # minősítjük, csak azt, hogy egyáltalán VAN mit keresni.
    if _tanithato:
        check(f"'{nev}': TANÍTHATÓ — a keresési tér jogosan üres",
              len(valtozo) == 0, f"{len(valtozo)} dimenzió (0 a várt)")
    else:
        check(f"⚠ '{nev}': VAN mit optimalizálni (≥2 változó dimenzió)",
              len(valtozo) >= 2, f"{len(ter)} kombináció, {len(valtozo)} dimenzió")

    # ── 2. A tartományok a MEGSZOKOTT helyen ───────────────────────────
    # ⚠ A `generate_*_params` és a paraméter-ablak is KÖZVETLENÜL az
    # `optimizer` alól olvas. Egy beágyazott alkulcs (`ranges`, `params`…)
    # NÉMÁN üres teret ad — a config érvényes marad, a keresés viszont nem
    # csinál semmit.
    _cf = ROOT / "strategy" / "config" / f"{nev}.json"
    if _cf.exists():
        _o = (json.load(open(_cf, encoding="utf-8")).get("optimizer") or {})
        _felul = [k for k, v in _o.items() if isinstance(v, dict) and "min" in v]
        _agyazott = [k for k, v in _o.items()
                     if isinstance(v, dict) and "min" not in v
                     and any(isinstance(x, dict) and "min" in x for x in v.values())]
        if not _tanithato:
            check(f"'{nev}': a tartományok KÖZVETLENÜL az `optimizer` alatt",
                  bool(_felul), f"{len(_felul)} tartomány")
        check(f"⚠ '{nev}': nincs BEÁGYAZOTT tartomány-blokk (némán inert lenne)",
              not _agyazott, f"beágyazva: {_agyazott}")

# ── 3. Minden stratégiának legyen LEÍRÁSA ──────────────────────────────
# ⚠ A `tools/i18n_scan.py` „stratégiák 4/4"-et ír, de az a MEGLÉVŐ leírások
# FORDÍTOTTSÁGÁT méri — nem azt, hogy minden stratégiának VAN-e leírása. Egy
# leírás nélküli stratégiánál a felület „Leírás" fülje üresen marad, és a
# scanner ettől még 100%-ot jelent.
_docs = ROOT / "strategy" / "docs"
for nev in nevek:
    check(f"'{nev}': van magyar leírása",
          (_docs / f"{nev}.md").exists(), f"{nev}.md")

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

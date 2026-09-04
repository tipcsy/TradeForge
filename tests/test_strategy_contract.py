"""A STRATEGIA-SZERZODES ORE — a szam ne hazudjon (v3.30.0).

⚠ A KERES (2026-09-02, a `.tfs` csomagolas 3/b kerdesere): „Igen a betolteskor
kozolje, hogy inkompatibilis verziot akarunk hasznalni. (Dobjon hibat. Ez viszont
felvet egy uj kerdeskort, meddig kompatibilis egy strategia a programmal? Erre
kellene egy kidolgozas, vagy egy szigorubb verziokezeles.)"

Ket dolgot orzunk, es a MASODIK a fontosabb:

  1. a KAPU mukodik: mas API-verzioju strategia nem tolt be, es a hibauzenet
     megmondja, MELYIK oldalt kell frissiteni;
  2. a SZAM NEM HAZUDIK: ha a szerzodes (az interfesz) elmozdul, ez a teszt
     bukik — akkor is, ha minden mas zold.

⚠ MIERT KELL A MASODIK. Egy verziószam annyit er, amennyire fegyelmezetten
emelik. Ebben a projektben ez mar egyszer megbukott: a `version.py` OT funkcion
at nem emelkedett, mikozben a commitok uj verziot hirdettek. Ugyanez a hiba itt
draggabb: a `.tfs` csomag `api: 1`-et mondana, a program `1`-et varna, es megis
MAS szerzodesre epulne — a strategia betoltodne, majd futas kozben torne el,
vagy ami rosszabb, mukodni latszana es mast csinalna.

⚠ EZ A TESZT NEM TILTJA A VALTOZAST. Dontest kenyszerit: ha a szerzodes valtozott,
el kell donteni, hogy TORO-e (akkor `STRATEGY_API` + 1), vagy sem (akkor eleg az
ujjlenyomatot frissiteni ITT). A hatarvonal a `strategy/contract.py` fejleceben van.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog  # noqa: E402
applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


from strategy import contract, registered_strategy_names, get_strategy_by_name  # noqa: E402
from strategy.base import Strategy, STRATEGY_API, STRATEGY_API_MIN              # noqa: E402

# ⚠ A SZERZODES UJJLENYOMATA. Ha ez a teszt emiatt bukik, NE csak ird at a
# szamot: elobb dontsd el a `strategy/contract.py` listaja alapjan, hogy a
# valtozas TORO-e. Ha igen, `STRATEGY_API` is emelendo (es a regi csomagok
# betoltese ettol kezdve hibat ad — ez a szandek).
UJJLENYOMAT = "edb6662bf868"
API_AKKOR = 1


# ══ 1. A SZAM ES AZ UJJLENYOMAT EGYUTT MOZOG ═══════════════════════════
_most = contract.fingerprint()
if _most != UJJLENYOMAT:
    print()
    print("!! A STRATEGIA-SZERZODES MEGVALTOZOTT.")
    print(f"   tarolt ujjlenyomat: {UJJLENYOMAT}   mostani: {_most}")
    print("   Dontsd el a `strategy/contract.py` listaja alapjan:")
    print("     * TORO valtozas (metodus torlese/atnevezese, alairas szukitese,")
    print("       visszaadott alak valtozasa) -> STRATEGY_API + 1 ES az")
    print("       ujjlenyomat frissitese ITT;")
    print("     * NEM toro (uj hook alapertelmezessel, uj MarketData-mezo, uj")
    print("       config-kulcs) -> eleg az ujjlenyomatot frissiteni ITT.")
    print()
    print("   A mostani szerzodes:")
    for _sor in contract.surface_text().splitlines():
        print("     " + _sor)
    print()
check("a szerzodes ujjlenyomata valtozatlan", _most == UJJLENYOMAT,
      f"{UJJLENYOMAT} -> {_most}")
check("...es a hozza tartozo API-verzio is", STRATEGY_API == API_AKKOR,
      f"{API_AKKOR} -> {STRATEGY_API}")
check("a MIN nem nagyobb a mostaninal", STRATEGY_API_MIN <= STRATEGY_API,
      f"{STRATEGY_API_MIN} > {STRATEGY_API}")


# ══ 2. A KAPU: melyik oldalt kell frissiteni? ══════════════════════════
_ok, _ind = contract.compatible(STRATEGY_API)
check("a sajat verziot elfogadja", _ok, _ind)
_ok_uj, _ind_uj = contract.compatible(STRATEGY_API + 1)
check("az UJABB strategiat elutasitja", not _ok_uj)
check("...es a PROGRAM frissiteset kéri", "TradeForge" in _ind_uj or
      "update" in _ind_uj.lower(), _ind_uj)
_ok_regi, _ind_regi = contract.compatible(STRATEGY_API_MIN - 1)
check("a TUL REGI strategiat elutasitja", not _ok_regi)
check("...es a STRATEGIA atirasat kéri",
      _ind_regi != _ind_uj and bool(_ind_regi), _ind_regi)
check("a nem-szam `api` is elutasitas, nem osszeomlas",
      not contract.compatible("valami")[0])
check("a hianyzo `api` (None) sem omlik ossze",
      not contract.compatible(None)[0])


# ══ 3. A REPOBAN LEVO STRATEGIAK MIND A MOSTANI SZERZODESRE ═══════════
_nevek = registered_strategy_names()
check("van mit ellenorizni", len(_nevek) >= 5, str(_nevek))
_rossz = [n for n in _nevek
          if int(getattr(get_strategy_by_name(n), "api", -1)) != STRATEGY_API]
check("minden repobeli strategia a mostani API-t deklaralja", not _rossz,
      ", ".join(_rossz))
check("az alaposztaly is", int(Strategy.api) == STRATEGY_API)


# ══ 4. A KAPU TENYLEG A FELDERITESBEN VAN ═════════════════════════════
# Nem eleg, hogy a `compatible` letezik: a registrynek hasznalnia is kell,
# kulonben a kapu egy soha meg nem hivott fuggveny.
_src = (ROOT / "strategy" / "__init__.py").read_text(encoding="utf-8")
check("a felderites hivja a szerzodes-kaput", "contract.compatible(" in _src)
check("...es a kizartakat NYILVANTARTJA", "_INCOMPATIBLE" in _src)
check("...es a naploba is kiirja", "log.warning" in _src and "KIMARAD" in _src)

from strategy import incompatible_strategies                    # noqa: E402
check("epp semmi nincs kizarva (a repo konzisztens)",
      incompatible_strategies() == {}, str(incompatible_strategies()))


# ══ 5. A KIZARAS NEM NEMA: egy hamis strategian VEGIGJATSZVA ══════════
# ⚠ Ez a lenyeg. A tobbi allitas szerkezeti; ez azt meri, hogy a kapu VALODI
# osztalyra is mukodik, es hogy az indok eljut a hivohoz.
class _JovobeliStrategia(Strategy):
    name = "_teszt_jovobeli"
    api = STRATEGY_API + 5

    def timeframes(self):
        return []

    def columns(self):
        return []

    def compute_display(self, md):
        return {}

    def new_signal_state(self, symbol):
        return None

    def on_bar_close(self, state, md):
        return state, "NONE"

    def base_params(self, cfg):
        return {}

    def param_space(self, cfg, base_params, method, max_trials):
        return []


_ok2, _ind2 = contract.compatible(_JovobeliStrategia.api)
check("egy jovobeli strategia a kapun FENNAKAD", not _ok2)
check("...es az indok megnevezi a ket verziot",
      str(_JovobeliStrategia.api) in _ind2 and str(STRATEGY_API) in _ind2, _ind2)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

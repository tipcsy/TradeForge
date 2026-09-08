"""A TRAILING egy forrásból — és az 1 R is (v3.56.0).

⚠ A LELET (2026-09-08, független code review). A trailing ~40 sora KÉTSZER élt a
`live_trader`-ben, „IKERPÁR"-ként megjelölve („HA ITT VÁLTOZTATSZ, azt is
módosítsd"). A duplikáció nem maradt ártalmatlan: a két példány **el is tért**.

    # `_apply_be_and_trailing` (a no-trade órák ága)
    if override_points is not None:
        dist_price = override_points * point
    else:
        _atr = float(pstate.get("entry_atr") or 0.0)     # ← CSAK ITT kap értéket
        ...
    act_price = (0.0 if risky else rr.get(...) * _atr)   # ← DE ITT is kell

Kézi követés-felülírás (`trail_points`, a Pozíciók fülről) + nem-risky pozíció →
**`NameError`**. A hívó `except`-je pedig `log.debug`-ba nyelte, és mivel a
`for` cikluson BELÜL van, a szünet-órákban nem csak a trailing maradt volna el,
hanem az adott körben a TÖBBI pozíció breakevenje is. A fő ág ugyanezt helyesen
csinálta (ott az `_atr` az elágazás ELŐTT vett fel értéket).

⚠ A MÁSIK LELET, ugyanabból a családból: az „1 R árban" képlet NÉGY helyen élt

    abs(pos.price_open - pstate.get("original_sl", pos.sl))

Az MT5 a stop NÉLKÜLI pozíciónak `sl = 0.0`-t ad, nem `None`-t (tehát a
`TypeError`, amit a review jelzett, nem tud bekövetkezni — a valódi hiba
rosszabb). Ilyenkor a képlet `|nyitóár − 0| = nyitóár`-t adott: egy MAGÁVAL AZ
ÁRRAL egyenlő „1 R". Nem kivétel, nem hibaüzenet — csak egy küszöb, ami soha
nem sül el: a `breakeven_r=1` a nyitóár kétszeresére, a Felező/Pajzs 1R-triggere
ugyanoda, a Harmados szintjei szintén. Ilyen pozíció létezik: örökbefogadott
(`core/adopted.py`), vagy amiről a stop lekerült.

AMIT ITT ŐRZÜNK:
  1. a KÖZÖS trailing-függvény viselkedése (a fő ág szemantikájával),
  2. hogy a régi NameError-eset már NEM száll el,
  3. hogy egyik élő ág SEM számolja újra a képletet kézzel,
  4. az `_one_r_price` szerződése: stop nélkül 0.0 (= „nem tudható"), és a
     hívók ezt kihagyásként kezelik.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog

applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from core import risk_reduction as rr

T = rr.trailing_new_sl

# Alapeset: BUY, nyitó 100, ár 105, SL 90, ATR 1.0, táv 0.4, aktiválás 0.5
BASE = dict(entry_atr=1.0, trail_distance_atr=0.4, trail_activation_atr=0.5,
            point=0.01, digits=2)


# ══ 1. A KÖZÖS FÜGGVÉNY ═══════════════════════════════════════════════════
_r = T(True, 100.0, 105.0, 90.0, **BASE)
check("BUY: az új stop = ár − (ATR × táv)", _r and abs(_r[0] - 104.6) < 1e-9,
      str(_r))
check("...és visszaadja a követési TÁVOLSÁGOT is (a naplóhoz)",
      _r and abs(_r[1] - 0.4) < 1e-9, str(_r))

_s = T(False, 100.0, 95.0, 110.0, **BASE)
check("SELL: tükrözve (ár + táv)", _s and abs(_s[0] - 95.4) < 1e-9, str(_s))

check("a távolság az rr-specből jön (más szorzó → más stop)",
      abs(T(True, 100.0, 105.0, 90.0, **{**BASE, "trail_distance_atr": 2.0})[0]
          - 103.0) < 1e-9)

# Aktiválás
check("aktiválás ALATT nincs húzás",
      T(True, 100.0, 100.4, 90.0, **BASE) is None)
check("aktiválás FÖLÖTT van", T(True, 100.0, 100.6, 90.0, **BASE) is not None)
check("risky → AZONNAL aktív (nincs aktiválási küszöb)",
      T(True, 100.0, 100.01, 90.0, **{**BASE, "risky": True}) is not None)
check("risky FELEZI a követési távot",
      abs(T(True, 100.0, 105.0, 90.0, **{**BASE, "risky": True})[1] - 0.2) < 1e-9)

# A stop csak SZORÍTHAT
check("a stop SOSEM lazul (BUY: az új nem lehet a régi alatt)",
      T(True, 100.0, 105.0, 104.9, **BASE) is None)
check("...SELL-en is", T(False, 100.0, 95.0, 95.1, **BASE) is None)

# BE-padló invariáns (a 2026-07-28-i eset)
# BUY: 100,6 − 1,0 = 99,6, ami a belépő ALATT van → tilos (kockázatmentesből
# nem lehet kockázatos). Ugyanez a szűkebb 0,4-es távval 100,2-t ad → mehet.
check("⚠ BE után a stop nem mehet a belépő ALÁ (BE-padló)",
      T(True, 100.0, 100.6, 99.0, **{**BASE, "trail_distance_atr": 1.0,
                                     "be_floor": 100.0}) is None,
      "100,6 − 1,0 = 99,6 < 100")
check("...de a padló FÖLÖTT húz",
      T(True, 100.0, 100.6, 99.0, **{**BASE, "be_floor": 100.0}) is not None,
      "100,6 − 0,4 = 100,2 ≥ 100")
check("SELL-en a padló tükrözve (99,4 + 1,0 = 100,4 > 100)",
      T(False, 100.0, 99.4, 101.0, **{**BASE, "trail_distance_atr": 1.0,
                                      "be_floor": 100.0}) is None)
check("...és a padló alatt SELL-en is húz",
      T(False, 100.0, 99.4, 101.0, **{**BASE, "be_floor": 100.0}) is not None)

# A bróker minimum stop-távolsága
check("a min. stop-távolság + 1 pont alá nem megyünk",
      abs(T(True, 100.0, 105.0, 90.0, **{**BASE, "stops_level": 100})[1]
          - (100 * 0.01 + 0.01)) < 1e-9,
      str(T(True, 100.0, 105.0, 90.0, **{**BASE, "stops_level": 100})))

# Kézi felülírás
check("kézi felülírás PONTBAN (risky NEM felezi)",
      abs(T(True, 100.0, 105.0, 90.0, **{**BASE, "override_points": 40,
                                         "risky": True})[1] - 0.4) < 1e-9)


# ══ 2. A RÉGI HIBA: kézi felülírás ISMERETLEN ATR-rel ════════════════════
# Ez az eset dobott `NameError`-t az egyik ikerpárban.
_bad = dict(BASE, entry_atr=0.0)
try:
    _res = T(True, 100.0, 105.0, 90.0, **{**_bad, "override_points": 40})
    _ok = True
except Exception as ex:                      # noqa: BLE001 — épp ezt mérjük
    _res, _ok = None, False
    check("⚠ kézi felülírás + ismeretlen ATR: NEM száll el", False, str(ex))
if _ok:
    check("⚠ kézi felülírás + ismeretlen ATR: NEM száll el (a régi NameError)",
          True)
    check("...és húz is (a felhasználó megadta a távot → azonnal aktív)",
          _res and abs(_res[0] - 104.6) < 1e-9, str(_res))

check("ismeretlen ATR + NINCS kézi táv → nincs trailing (None)",
      T(True, 100.0, 105.0, 90.0, **_bad) is None)
check("a hibás (nem szám) ATR sem omlik össze",
      T(True, 100.0, 105.0, 90.0, **{**BASE, "entry_atr": "x",
                                     "override_points": 40}) is not None)


# ══ 3. EGY FORRÁS: az élő ágak nem számolnak újra ════════════════════════
_lt = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
check("⚠ MINDKÉT élő ág a közös trailing_new_sl-t hívja",
      _lt.count("trailing_new_sl(") == 2, f"{_lt.count('trailing_new_sl(')} hívás")
# ⚠ A `min_stop_price` MAGA nem tiltott név: az `order_exec.min_stop_price()`
# a csomag-stopnál és a kézi belépőnél is használatos. A követés-KÉPLETET
# keressük, nem a szót — ugyanaz a lecke, mint a kommentbeli `pass`-nál.
check("⚠ a kézzel írt követés-képlet SEHOL nem maradt",
      "max(dist_price, min_stop_price + point)" not in _lt
      and "act_price" not in _lt,
      "eff_price / act_price")
check("...és a `_atr` hatóköri csapdája sem",
      'dist_price = override_points * point' not in _lt)

# A backteszt SZÁNDÉKOSAN külön: ott nincs bróker-stops_level és nincs
# kerekítés, a bemenet pedig a gyertya high/low-ja, nem az aktuális ár. Ha
# valaha összevonjuk, azt BITAZONOSSÁGGAL kell igazolni — lásd
# `test_native_exec.py`.
_bt = (ROOT / "trading" / "backtest.py").read_text(encoding="utf-8")
check("a backteszt trailingje (szándékosan) NEM ezt hívja",
      "trailing_new_sl(" not in _bt)


# ══ 4. AZ 1 R: stop nélkül „nem tudható", nem nulla-osztás és nem nyitóár ══
import trading.live_trader as lt


class _P:
    def __init__(self, sl):
        self.price_open, self.sl = 1.2000, sl


check("normál eset: |nyitóár − eredeti SL|",
      abs(lt._one_r_price(_P(1.1950), {"original_sl": 1.1950}) - 0.0050) < 1e-9,
      str(lt._one_r_price(_P(1.1950), {"original_sl": 1.1950})))
check("a pstate EREDETI stopja nyer az elmozdított pos.sl-lel szemben",
      abs(lt._one_r_price(_P(1.1990), {"original_sl": 1.1950}) - 0.0050) < 1e-9)
check("pstate nélkül a pos.sl-ből",
      abs(lt._one_r_price(_P(1.1950), {}) - 0.0050) < 1e-9)
check("⚠ STOP NÉLKÜL (sl=0.0) → 0.0, NEM a nyitóár",
      lt._one_r_price(_P(0.0), {}) == 0.0,
      str(lt._one_r_price(_P(0.0), {})))
check("⚠ ...és akkor sem, ha a pstate-ben 0.0 áll",
      lt._one_r_price(_P(0.0), {"original_sl": 0.0}) == 0.0)

# A hívók MIND ezt használják (nincs kézzel írt maradék).
check("⚠ MINDEN 1R-számítás a közös _one_r_price-ból jön",
      _lt.count("_one_r_price(") == 6,      # 1 definíció + 5 hívó
      f"{_lt.count('_one_r_price(')} előfordulás")
# ⚠ A régi alak a `_one_r_price` DOKUMENTÁCIÓJÁBAN szándékosan ott van (az
# magyarázza, miért nem azt használjuk) — ezért a KÓD-sorokban keressük.
_lt_kod = [ln for ln in _lt.splitlines()
           if ln.strip() and not ln.strip().startswith("#")
           and "⚠ MIÉRT NEM" not in ln]
check("⚠ a kézzel írt alak SEHOL nem maradt (a kódban)",
      not [ln for ln in _lt_kod if 'original_sl", pos.sl)' in ln],
      str([ln.strip()[:50] for ln in _lt_kod if 'original_sl", pos.sl)' in ln]))

# És a 0.0 tényleg KIHAGYÁSt jelent a hívóknál, nem azonnali elsülést:
# a breakeven_trigger None-t ad, a Felező/Pajzs `one_r > 0`-t vár.
check("a 0.0-ra a breakeven_trigger None-t ad (nem hamis küszöböt)",
      rr.breakeven_trigger(1.2, 1.21, 0.0, True, 0.5, 1.0) is None)
check("a Felező/Pajzs 1R-ága `one_r > 0`-t követel", "if one_r > 0 and reached" in _lt)

print()
n, m = sum(results), len(results)
print(f"{n}/{m} teszt PASS")
sys.exit(0 if n == m else 1)

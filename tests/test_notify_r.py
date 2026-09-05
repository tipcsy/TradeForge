"""AZ ERTESITESEK R-BEN IS BESZELJENEK — es a trailing ne „kockazatmentesites" legyen.

⚠ A FELHASZNALO BEJELENTESE (0014). Egy Ger40 pozicionál ezt kapta hatszor:

    [15:35] TradeForge: 🛡 Ger40 #5037489805 · KOCKAZATMENTESITVE (stop a belepon: 26102.59)
    [15:35] TradeForge: 🛡 Ger40 #5037489805 · KOCKAZATMENTESITVE (stop a belepon: 26111.28)
    [15:36] TradeForge: 🛡 Ger40 #5037489805 · KOCKAZATMENTESITVE (stop a belepon: 26117.59)
    ...

KET baj volt egyszerre:

  1. A `_be` jelzo azt kerdezi, hogy MOST kockazatmentes-e a pozicio (a stop a
     nyereseg-oldalon van-e). Ez az ELSO atlepes utan VEGIG igaz marad, tehat
     minden tovabbi TRAILING-lepes is „KOCKAZATMENTESITVE" neven ment ki. Az
     allitas ilyenkor mar hazudik is: a stop nem „a belepon" van, hanem jocskan
     folotte.
  2. Egy ARSZINT nem mondja meg, MENNYI van bebiztositva. Ahhoz fejben kell
     kivonni a belepot es elosztani a kockazattal.

Ugyanez a lezarasnal: „P&L +6.93" onmagaban ertelmezhetetlen — +6,93 $ lehet
remek (0,7 R egy 10 $-os teten) es gyenge is (0,07 R egy 100 $-oson).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog  # noqa: E402
applog.harden_console()

from core import position_meta as pm  # noqa: E402
from core.i18n import t as _t         # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


# ── 1. stop_r: a BEBIZTOSITOTT eredmeny ─────────────────────────────────
# A felhasznalo VALODI esete: Ger40, belepo 26102.59, point_size 0,01,
# eredeti stop 29 arpont (= 1 R = 10 $).
PS, BELEPO, TAV, RISK = 0.01, 26102.59, 29.0, 10.0
pm._state["1"] = {"ticket": 1, "symbol": "Ger40", "strategy": "wpr_sma",
                  "risk_ccy": RISK, "lot": 0.1, "sl_points": TAV / PS,
                  "entry_price": BELEPO, "opened_at": "x"}
pm._loaded = True

_r, _penz = pm.stop_r(1, 26111.28, True, PS)
check("a felhasznalo peldaja: stop 26111.28 -> 3 $ / 0,3 R",
      abs(_penz - 3.0) < 0.01 and abs(_r - 0.30) < 0.005, f"{_penz:+.2f}$ {_r:+.2f}R")

check("a belepon allo stop 0 R", abs(pm.stop_r(1, BELEPO, True, PS)[0]) < 1e-9)
check("az EREDETI stop tavolsaga definicio szerint -1 R",
      abs(pm.stop_r(1, BELEPO - TAV, True, PS)[0] + 1.0) < 1e-9)
check("...es a penz ilyenkor a teljes kockazat",
      abs(pm.stop_r(1, BELEPO - TAV, True, PS)[1] + RISK) < 1e-9)

# SELL: az irany megfordul.
pm._state["2"] = dict(pm._state["1"], ticket=2)
check("SELL-nel a belepo ALATTI stop a POZITIV",
      pm.stop_r(2, BELEPO - TAV, False, PS)[0] > 0)
check("...es a belepo FOLOTTI a negativ",
      pm.stop_r(2, BELEPO + TAV, False, PS)[0] < 0)

# Hianyzo/ertelmetlen adat -> None, NEM 0. (A 0 azt allitana, hogy „nulla R",
# ami hazugsag; a None-ra a hivo a regi, R nelkuli uzenetet kuldi.)
check("ismeretlen ticket -> None", pm.stop_r(999999, 26110.0, True, PS) is None)
pm._state["3"] = dict(pm._state["1"], ticket=3, risk_ccy=0.0)
check("nulla rogzitett kockazat -> None (nem osztunk nullaval)",
      pm.stop_r(3, 26110.0, True, PS) is None)
pm._state["4"] = dict(pm._state["1"], ticket=4, sl_points=0.0)
check("nulla stop-tavolsag -> None", pm.stop_r(4, 26110.0, True, PS) is None)

# ── 2. r_multiple a lezarashoz ──────────────────────────────────────────
check("a lezarult kotes R-je a belepeskori kockazathoz mer",
      abs(pm.r_multiple(1, 6.93) - 0.693) < 1e-6, str(pm.r_multiple(1, 6.93)))

# ── 3. AZ ESEMENY-NEV: elso atlepes vs. tovabbi lepesek ─────────────────
# ⚠ EZ A LENYEG. A `_be` (kockazatmentes-e MOST) az elso atlepes utan vegig
# igaz; az ertesitesnek viszont az ESEMENYT kell neveznie.
def _sorozat(stopok, belepo=BELEPO):
    """A live_trader logikaja kicsiben: (elso_be?) minden lepesre."""
    pstate, ki = {}, []
    for sl in stopok:
        be = bool(sl) and sl >= belepo
        elso = be and not pstate.get("be_hirdetve")
        pstate["be_hirdetve"] = be
        ki.append(elso)
    return ki

_valos = [26102.59, 26111.28, 26116.39, 26117.59, 26118.87, 26119.01]
_jel = _sorozat(_valos)
check("a felhasznalo 6 lepesebol PONTOSAN EGY a kockazatmentesites",
      sum(_jel) == 1, str(_jel))
check("...megpedig az ELSO", _jel[0] is True)
check("...a tobbi mind 'SL mozgatva'", not any(_jel[1:]))

# Ha a stop visszaesik a kockazatba, az ujboli atlepes ISMET esemeny.
_vissza = _sorozat([26110.0, 26090.0, 26112.0])
check("visszaeses utan az ujboli atlepes ismet kockazatmentesites",
      _vissza == [True, False, True], str(_vissza))

# A forrasban tenyleg igy van (kulonben a fenti csak egy szep elmelet).
_src = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
check("a live_trader az ELSO atlepest kuldi az ertesitesnek",
      "breakeven=_elso_be" in _src, "nem a mindig-igaz _be-t")
check("...es atadja a bebiztositott R-t is",
      "position_meta.stop_r(" in _src and "locked_ccy=" in _src)

# ── 4. AZ UZENETEK ──────────────────────────────────────────────────────
_be_szoveg = _t("notify.be_r", symbol="Ger40", ticket=5037489805,
                sl="26102.59", money="+0.00", r="+0.00")
_mv = _t("notify.sl_move_r", symbol="Ger40", ticket=5037489805,
         sl="26111.28", money="+3.00", r="+0.30")
_cl = _t("notify.close_r", symbol="Ger40", ticket=5037489805,
         pnl="+6.93", r="+0.69", strategy="wpr_sma")
check("az SL-mozgas uzenete tartalmazza a penzt ES az R-t",
      "+3.00" in _mv and "+0.30" in _mv and "R" in _mv, _mv)
check("...es NEM allitja, hogy a stop a belepon van",
      "belépőn" not in _mv, _mv)
check("a kockazatmentesites uzenete is mutatja a bebiztositottat",
      "R" in _be_szoveg, _be_szoveg)
check("a lezaras uzenete tartalmazza az R-t", "+0.69" in _cl and "R" in _cl, _cl)

# ⚠ Az R NELKULI valtozatok MEGMARADNAK: ha nincs rogzitett kockazat (regi
# pozicio, adoptalt kezi kotes), akkor is menjen ki az ertesites.
for k in ("notify.be", "notify.sl_move", "notify.close"):
    check(f"a(z) {k!r} tartalek kulcs megmaradt",
          _t(k, symbol="X", ticket=1, sl="1", pnl="+1", strategy="s") != k)

# Mindket nyelvben megvan-e (a hianyzo kulcs a kulcsot magat irna ki).
for lang in ("hu", "en"):
    d = json.loads((ROOT / "lang" / f"{lang}.json").read_text(encoding="utf-8"))
    hiany = [k for k in ("notify.be_r", "notify.sl_move_r", "notify.close_r")
             if k not in d]
    check(f"{lang}: mind a harom uj kulcs megvan", not hiany, str(hiany))
    for k in ("notify.be_r", "notify.sl_move_r"):
        check(f"{lang}/{k}: a {{money}} es {{r}} helyorzo benne van",
              "{money}" in d.get(k, "") and "{r}" in d.get(k, ""))
    check(f"{lang}/notify.close_r: az {{r}} helyorzo benne van",
          "{r}" in d.get("notify.close_r", ""))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

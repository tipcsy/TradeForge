"""NAPI VESZTESEG-LIMIT: fix osszeg ↔ az egyenleg szazaleka.

⚠ A LELET (a felhasznalotol, 2026-09-21). A configban `daily_loss_limit_usd=90`
ES `daily_loss_limit_pct=0.015` allt egyszerre — a motor a 90-et hasznalta, a
szazalek holt kulcs volt. A `config_check` szolt is erte, de a FELULETEN nem
lehetett szazalekra valtani: a ▼/▲ mindig a fix osszeget irta.

⚠ ES A SZAM KET ELLENTETES HIBAT TUD OKOZNI. A kockazati modell tobbi resze
szazalekos (`account_risk_pct`), tehat a „hany vesztes kotes fer bele egy napba"
arany NEMAN vandorol a szamlaval:
  •  962 € egyenlegnel a 90 $ a szamla ~9%-a (≈23 kotes 0,4%-os kockazattal)
     — vagyis nem ved;
  •  22 500 $-nal ugyanaz a 90 $ mar EGY kotes kockazata alatt van
     — vagyis az elso veszteseg lezarja a napot.
Ugyanaz a szam, ket ellentetes iranyu hiba. Ezert kell a modot VALASZTANI tudni,
es ezert kell LATSZANIA, melyik az ervenyes.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import logging
logging.disable(logging.WARNING)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from core import daily_limit as dl

# ══ 1. A MOD FELOLDASA ═════════════════════════════════════════════════
check("usd > 0 → FIX mod", dl.mode({"daily_loss_limit_usd": 90.0}) == dl.MODE_FIX)
check("usd == 0 → SZAZALEK mod", dl.mode({"daily_loss_limit_usd": 0}) == dl.MODE_PCT)
check("hianyzo usd → SZAZALEK mod", dl.mode({}) == dl.MODE_PCT)
# ⚠ A szemet nem kapcsol modot: ertelmezhetetlen ertek = nincs fix osszeg.
check("ertelmezhetetlen usd → SZAZALEK mod",
      dl.mode({"daily_loss_limit_usd": "hupp"}) == dl.MODE_PCT)

# ══ 2. AZ ERTEK — EGY IGAZSAGFORRAS ════════════════════════════════════
check("fix modban a szamla nem szamit",
      dl.value({"daily_loss_limit_usd": 90.0}, 962.0) == 90.0
      and dl.value({"daily_loss_limit_usd": 90.0}, 50000.0) == 90.0)
check("szazalek modban az egyenleggel mozog",
      abs(dl.value({"daily_loss_limit_pct": 0.015}, 962.0) - 14.43) < 0.01)
check("...es duplazodo szamlan duplazodik",
      abs(dl.value({"daily_loss_limit_pct": 0.015}, 1924.0) - 28.86) < 0.01)
check("pct hianyaban a regi alapertek (1,5%)", dl.ALAP_PCT == 0.015
      and abs(dl.value({}, 1000.0) - 15.0) < 1e-9)

# ⚠ A MOTOR, A BACKTESZT ES A FELULET UGYANEZT HIVJA. Ha a `backtest` sajat
# szamolast tartana meg, a fejlec mast mutatna, mint amit a motor betart.
_bt = (ROOT / "trading" / "backtest.py").read_text(encoding="utf-8")
check("⚠ a backteszt a KOZOS fuggvenyre delegal",
      "from core.daily_limit import value" in _bt)
check("...es nem szamol sajat kepletet",
      'balance * float(trading_cfg.get("daily_loss_limit_pct"' not in _bt)

# ══ 3. ⚠ A MODVALTAS NEM UGORHAT ═══════════════════════════════════════
# Aki modot valt, ne kapjon melle egy eszrevetlen szigoritast vagy lazitast.
t = {"daily_loss_limit_usd": 90.0, "daily_loss_limit_pct": 0.015}
B = 962.0
_elotte = dl.value(t, B)
check("⚠ fix → szazalek: a mod valtozik", dl.toggle(t, B) == dl.MODE_PCT)
check("⚠ ...de az ERTEK gyakorlatilag ugyanaz",
      abs(dl.value(t, B) - _elotte) < 0.1, f"{_elotte} → {dl.value(t, B)}")
check("...az usd 0 lett (KIMONDVA, nem torolve)",
      t["daily_loss_limit_usd"] == 0.0 and "daily_loss_limit_usd" in t)
check("...es a szazalek a valos arany", abs(t["daily_loss_limit_pct"] - 90.0 / 962.0) < 0.001,
      str(t["daily_loss_limit_pct"]))
# Mostantol EGYUTT MOZOG a szamlaval — ez volt a cel.
check("⚠ innentol a limit koveti az egyenleget",
      abs(dl.value(t, 2 * B) - 2 * _elotte) < 0.2, str(dl.value(t, 2 * B)))

_elotte = dl.value(t, B)
check("szazalek → fix: a mod visszavalt", dl.toggle(t, B) == dl.MODE_FIX)
check("...es az ertek itt sem ugrik", abs(dl.value(t, B) - _elotte) < dl.LEPES_USD)

# ⚠ EGYENLEG NELKUL NEM SZAMOLUNK ARANYT: a „hany szazalek" kerdesnek nulla
# egyenlegnel nincs ertelme — maradunk fixen, es nem talalgatunk.
t2 = {"daily_loss_limit_usd": 90.0}
check("⚠ nulla egyenlegnel a szazalekra valtas KIMARAD",
      dl.toggle(t2, 0.0) == dl.MODE_FIX and t2["daily_loss_limit_usd"] == 90.0)

# ══ 4. A LEPTETES AZT LEPTETI, AMI LATSZIK ═════════════════════════════
t = {"daily_loss_limit_usd": 90.0}
dl.step(t, B, +1)
check("fix modban dollart lep", t["daily_loss_limit_usd"] == 100.0,
      str(t["daily_loss_limit_usd"]))
dl.step(t, B, -1)
check("...es vissza", t["daily_loss_limit_usd"] == 90.0)
t = {"daily_loss_limit_usd": 0.0, "daily_loss_limit_pct": 0.015}
dl.step(t, B, +1)
check("szazalek modban szazalekot lep",
      abs(t["daily_loss_limit_pct"] - 0.016) < 1e-9, str(t["daily_loss_limit_pct"]))
check("...az usd kozben 0 marad (nem valt modot)", t["daily_loss_limit_usd"] == 0.0)

# ⚠ HATAROK: a limit se ne legyen nevetsegesen kicsi, se akkora, hogy ne legyen.
t = {"daily_loss_limit_usd": 10.0}
for _ in range(5):
    dl.step(t, B, -1)
check("a fix limit nem megy a minimum ala",
      t["daily_loss_limit_usd"] == dl.MIN_USD, str(t["daily_loss_limit_usd"]))
t = {"daily_loss_limit_usd": 0.0, "daily_loss_limit_pct": 0.001}
for _ in range(5):
    dl.step(t, B, -1)
check("a szazalek sem", t["daily_loss_limit_pct"] == dl.MIN_PCT,
      str(t["daily_loss_limit_pct"]))
t = {"daily_loss_limit_usd": 0.0, "daily_loss_limit_pct": dl.MAX_PCT}
dl.step(t, B, +1)
check("...es felfele sincs korlatlan", t["daily_loss_limit_pct"] == dl.MAX_PCT)

# ══ 5. A FELULET: EGY RAJZOLO, ES A MOD LATSZIK ════════════════════════
_gui = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
# ⚠ A CIMKE KET HELYEN KESZULT, kulon formazassal — ugyanaz a hiba, amit a
# slot-cimkenel mar egyszer megfizettunk.
check("⚠ a limit-cimke EGY helyen keszul", _gui.count("def _render_limit_label") == 1)
check("...es a periodikus frissites is azt hivja",
      _gui.count("self._render_limit_label()") >= 3,
      str(_gui.count("self._render_limit_label()")))
check("⚠ nincs tobbe kezzel osszerakott cimke-szoveg",
      'f"Napi limit:' not in _gui)
check("a felulet a KOZOS modulon at ir",
      "_dl.step(" in _gui and "_dl.toggle(" in _gui)
check("⚠ ...es NEM ir kozvetlenul a config kulcsba",
      'self.cfg["trading"]["daily_loss_limit_usd"]' not in _gui)
check("van MODVALTO gomb a fejlecben", "_toggle_daily_limit_mode" in _gui
      and "_btn_limit_mode" in _gui)
check("⚠ a MOD latszik a cimken (szazalek/fix)",
      "gui.limit.pct_tag" in _gui and "gui.limit.fix_tag" in _gui)

# A feliratok a KATALOGUSBAN vannak, nem a forrasban.
import json as _json
_HU = _json.loads((ROOT / "lang" / "hu.json").read_text(encoding="utf-8"))
for _k in ("gui.limit.row", "gui.limit.stop", "gui.limit.pct_tag",
           "gui.limit.fix_tag", "gui.limit.init"):
    check(f"van magyar felirat: {_k}", bool(_HU.get(_k)), _HU.get(_k, ""))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

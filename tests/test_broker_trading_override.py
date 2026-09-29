"""0029/6a: számlánként felülírható kockázati beállítások.

Tibi döntése (2026-09-30): a közös `trading` az alap; brókerenként
felülírható a slot-keret, a kockázat % és a napi limit (pl. kisebb számlán
kevesebb slot). Egy brókernél semmi nem változik.

⚠ A MENTÉS A VESZÉLY (lásd core/broker_profile, 3. lépés): ha egy mentés a
futásidejű (felülírt) `trading`-et írná ki, a MÁSIK számla slot-száma a
közösbe kerülne. Ezért a kör: betöltés → futás közbeni módosítás → mentés,
és visszaolvasva a közös érintetlen, a módosítás a bróker SAJÁT blokkjában.
⚠ IDEIGLENES config-fájl — a valódi config.json-t a teszt nem írja.
"""
import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                          # noqa: E402
applog.harden_console()

from core import broker_profile as BP                           # noqa: E402
from strategy import settings as S                              # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


ALAP = {
    "trading": {"max_open_slots": 6, "account_risk_pct": 0.01,
                "daily_loss_limit_usd": 90.0},
    "brokers": [
        {"id": "act", "tag": "Act", "name": "ActivTrades", "server": "a", "login": 1},
        {"id": "rob", "tag": "Rob", "name": "RoboForex", "server": "b", "login": 2,
         "trading": {"max_open_slots": 3, "daily_loss_limit_usd": 40.0}},
    ],
    "pairs": {},
}

# ── a profil ─────────────────────────────────────────────────────────────
ps = BP.profiles(ALAP)
check("a bróker saját trading-blokkja a profilban", ps[1].trading == {
    "max_open_slots": 3, "daily_loss_limit_usd": 40.0}, str(ps[1].trading))
check("a blokk nélküli brókeré üres (a közös érvényes)", ps[0].trading == {})
check("érvényes blokkra nincs profil-hiba", not BP.validate(ALAP), str(BP.validate(ALAP)))
_rossz = copy.deepcopy(ALAP)
_rossz["brokers"][1]["trading"] = {"max_open_slots": "sok", "pairs": 1}
_h = BP.validate(_rossz)
check("⚠ nem számlánként állítható kulcs → hiba (nem némán elnyelve)",
      any("nem számlánként" in h for h in _h), str(_h))
check("⚠ érvénytelen érték → hiba", any("max_open_slots érvénytelen" in h for h in _h), str(_h))

# ── felülírás + érvényes érték ───────────────────────────────────────────
cfg = copy.deepcopy(ALAP)
BP.overlay_trading(cfg, ps[1])
check("aktív Rob: a motor a SAJÁT értékeit látja",
      cfg["trading"]["max_open_slots"] == 3 and cfg["trading"]["daily_loss_limit_usd"] == 40.0)
check("...a nem felülírt kulcs a közös marad", cfg["trading"]["account_risk_pct"] == 0.01)
check("a felület a MÁSIK számla érvényes értékét is ki tudja számolni",
      BP.effective_trading(cfg, ps[0])["max_open_slots"] == 6
      and BP.effective_trading(cfg, ps[1])["max_open_slots"] == 3)
cfg0 = copy.deepcopy(ALAP)
BP.overlay_trading(cfg0, ps[0])
check("egy blokk nélküli (pl. egyetlen) brókernél SEMMI nem változik",
      cfg0 == ALAP)

# ── a mentés köre, IDEIGLENES fájlon ──────────────────────────────────────
TMP = Path(tempfile.mkdtemp())
p = TMP / "config.json"
p.write_text(json.dumps(ALAP, ensure_ascii=False, indent=2), encoding="utf-8")
BP.set_override("rob")
try:
    betoltve = S.load_config(p)
    check("betöltéskor Rob motorja a 3 slotot látja", betoltve["trading"]["max_open_slots"] == 3)
    betoltve["trading"]["max_open_slots"] = 2          # a felületen ▼
    uzenet = S.write_config_file(betoltve, p)
finally:
    BP.set_override(None)
ki = json.loads(p.read_text(encoding="utf-8"))
check("mentés sikerült", not uzenet or "hiba" not in str(uzenet).lower(), str(uzenet))
check("⚠ a KÖZÖS trading érintetlen (6 slot, 90 limit)",
      ki["trading"]["max_open_slots"] == 6 and ki["trading"]["daily_loss_limit_usd"] == 90.0,
      str(ki["trading"]))
check("⚠ a futás közbeni módosítás a bróker SAJÁT blokkjába került",
      ki["brokers"][1]["trading"]["max_open_slots"] == 2, str(ki["brokers"][1]))
check("a rejtett nyilvántartó kulcs NEM került a fájlba",
      BP.TRADING_OVERLAY_KEY not in ki and "_broker_overlay" not in ki)
check("az otthoni bróker blokkja érintetlen", "trading" not in ki["brokers"][0])

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

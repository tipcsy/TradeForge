"""A válaszos kötés kapcsolója — egy KÉSZ funkció, amit nem lehetett elérni.

⚠ A LELET (2026-09-02). A felhasználó jelzései kimentek a Telegramra, de
IGEN/NEM gomb nélkül: „a telegramon nem kaptam semmi nyomógombot, hogy igen
akarom-e a kötést vagy sem. vagy ilyenkor csak egy igennel kell válaszoljak?"

A funkció a v3.12.0 óta MEGVOLT. Csak épp:

  * a `notify.answer_trading` alapból KI,
  * a kulcs HIÁNYZOTT a `config.json`-ból, tehát a fájlból sem derült ki, hogy
    létezik ilyen beállítás,
  * és a felületen SEHOL nem volt kapcsoló hozzá.

Egy kész funkció, amit nem lehet bekapcsolni, pontosan annyit ér, mint a
hiányzó — ráadásul rosszabbul: a kód, a teszt és a dokumentáció is azt
állította, hogy van.

⚠ Ez a projekt visszatérő hibája: a config CSAK AZ ELTÉRÉST rögzíti, így egy
kikapcsolt funkció NÉMÁN tétlen marad (lásd a `config_check` születését). Ezért
a kapcsoló mostantól MINDIG kiírja a kulcsot — `false`-ként is.

⚠ A SZÖVEGES „IGEN" SZÁNDÉKOSAN NINCS: két egyidejű ajánlatnál kétértelmű
lenne, és a rossz páron nyitna pozíciót. A gomb viszi az ajánlat azonosítóját.
"""
import io
import json
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


# ── 1. A KAPU: a kapcsoló tényleg ezt vezérli ─────────────────────────────
from core import signal_offer as _so

check("kulcs nélkül a válaszos kötés KI van kapcsolva",
      _so.enabled({}) is False)
check("...és `notify` blokkal, de kulcs nélkül is",
      _so.enabled({"notify": {"enabled": True}}) is False)
check("`answer_trading: true` → BE", _so.enabled(
    {"notify": {"answer_trading": True}}) is True)
check("`answer_trading: false` → KI", _so.enabled(
    {"notify": {"answer_trading": False}}) is False)

# ── 2. A FELÜLETI kapcsoló bekötése ───────────────────────────────────────
_gui = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
_set = _gui.split("def _show_settings", 1)[1].split("\n    def ", 1)[0]

check("a Beállítások ablaknak van Telegram lapja",
      '("telegram", _t("tab.telegram"))' in _set)
check("a lap tartalmat is kap (`_page[\"telegram\"]`)",
      '_page["telegram"]' in _set)
check("a jelölőnégyzet a MOSTANI beállításból indul",
      '.get("answer_trading", False)' in _set)
check("a mentés kiírja a `notify.answer_trading` kulcsot",
      '["answer_trading"] = bool(' in _set)

# ⚠ A KULCS FELTÉTEL NÉLKÜL menjen ki: ha csak bekapcsoláskor íródna, a
# kikapcsolás után megint ELTŰNNE a fájlból — és ott lennénk, ahonnan
# indultunk.
_ment = _set.split("def save", 1)[1]
_sor = next((s for s in _ment.splitlines() if '["answer_trading"]' in s), "")
check("a kulcs feltétel nélkül íródik (kikapcsolva is)",
      bool(_sor) and "if " not in _sor, _sor.strip())

# ── 3. A feliratok ────────────────────────────────────────────────────────
for _nyelv in ("hu", "en"):
    _kat = json.loads((ROOT / "lang" / (_nyelv + ".json")).read_text(encoding="utf-8"))
    for _k in ("tab.telegram", "notify.answer_trading",
               "notify.answer_trading.warn"):
        check(f"{_nyelv}: van „{_k}” felirat", bool(_kat.get(_k)))

# ⚠ A FIGYELMEZTETÉS MONDJA KI, hogy a gomb VALÓDI pozíciót nyit. Ez az
# egyetlen kapcsoló a felületen, ami egy chatüzenetből megbízást csinál.
_hu = json.loads((ROOT / "lang" / "hu.json").read_text(encoding="utf-8"))
check("a magyar figyelmeztetés kimondja, hogy VALÓDI pozíciót nyit",
      "VALÓDI" in _hu.get("notify.answer_trading.warn", ""))

# ── 4. Szöveges „igen" NINCS ──────────────────────────────────────────────
from core import telegram_cmd as _tc

check("az engedélyezett parancsok között nincs kötés-parancs",
      not any(n in _tc.ENGEDETT for n in ("close", "quit", "buy", "sell")),
      ", ".join(_tc.ENGEDETT))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

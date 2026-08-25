"""A fejlécben látszódjon, MELYIK licenc-felhasználó belépője van a gépen.

⚠ A KÉRÉS (2026-08-25): „Még azt szeretném, ha ide fentre felírná a
bejelentkezett felhasználónevet."

MIÉRT HASZNOS. A portálon a token címkéje a GÉP NEVE — ott azt látod, melyik
géphez tartozik egy belépő. A dashboardon a fordítottja kell: **melyik
felhasználóé ez a gép**. Több fiók vagy több gép mellett ez az egyetlen hely,
ahol ez látszik.

⚠ ÉS AMIT NEM MOND: a fejléc csak AZONOSÍT, nem érvényességet jelez. Egy
visszavont token mellett is ott marad az e-mail — a licenc állapotáról az
indításkori kapu és a napló beszél. Ezért nem írunk oda „licenc rendben"-t.
"""
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from core import licence

# ── 1. A mentett e-mail visszaolvasható ────────────────────────────────
_REAL = licence.TOKEN_PATH
_TMP = Path(tempfile.mkdtemp(prefix="tf_hdr_"))
licence.TOKEN_PATH = _TMP / "token.json"
try:
    check("nincs mentés → ÜRES e-mail (nem hibázik)",
          licence.stored_email() == "")

    licence.save_token("tfl_proba", "valaki@example.com")
    check("mentés után visszaolvasható",
          licence.stored_email() == "valaki@example.com",
          licence.stored_email())

    # ⚠ SÉRÜLT fájl: a fejléc maradjon üres, de a program NE álljon meg. Egy
    # kivétel itt a Tk-visszahívásban a stderr-re menne, ahol egy ablakos
    # programban SENKI nem látja.
    licence.TOKEN_PATH.write_text("{ ez nem json", encoding="utf-8")
    check("SÉRÜLT fájl → üres, nem kivétel", licence.stored_email() == "")

    # ⚠ E-mail NÉLKÜL mentett token (régi formátum) sem törhet el semmit.
    licence.TOKEN_PATH.write_text(json.dumps({"token": "tfl_x"}), encoding="utf-8")
    check("e-mail nélküli mentés → üres", licence.stored_email() == "")
finally:
    licence.TOKEN_PATH = _REAL
    shutil.rmtree(_TMP, ignore_errors=True)

check("a valódi útvonal visszaállt",
      str(licence.TOKEN_PATH).endswith("licence_token.json"))

# ── 2. A felület tényleg kiírja ────────────────────────────────────────
_gui = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
check("van külön címke a fejlécben", "self.lbl_licence" in _gui)
check("...és van frissítő metódusa", "def _refresh_licence_label(" in _gui)
check("a `stored_email`-t használja", "stored_email()" in _gui)

_i = _gui.find("def _refresh_licence_label")
_j = _gui.find("\n    # ── Piaci adat", _i)
_blok = _gui[_i:_j]

# ⚠ A FÁJLBAN NINCS modul-szintű `logging` import — csak függvényeken belül.
# Egy modul-szintűnek hitt `_logging` itt NameError-t adna, és Tk-visszahívásban
# az a stderr-re menne, ahol egy ablakos programban SENKI nem látja. Ugyanaz a
# csapda, ami a `live_trader` menet közbeni bekötésénél is előjött.
check("⚠ a naplózás LOKÁLIS importtal megy (a fájlban nincs modul-szintű)",
      "import logging as _logging" in _blok)
check("a licenc-modul is lokálisan jön be",
      "from core import licence as _lic" in _blok)
check("⚠ hiba esetén ÜRES a mező (nem áll meg a felület)",
      '_email = ""' in _blok and "except Exception" in _blok)
check("...és a hiba OKA a naplóba kerül",
      "nem olvasható" in _blok)
check("a mező az e-mailt mutatja", "self.lbl_licence.config(text=_email)" in _blok)

# ⚠ NINCS emoji a címkében. A 👤 (U+1F464) emoji-kódpont a mono
# betűtípusból hiányzik, ezért a Segoe UI Emoji-ból esik vissza, aminek MÁS az
# alapvonala — láthatóan lejjebb ül a szövegnél (a felhasználó vette észre).
# A fejléc többi szimbóluma BMP és a szövegfontból jön, azok ezért ülnek jól.
check("⚠ nincs BMP-n kívüli emoji a fejléc-címkében",
      all(ord(c) < 0x1F000 for c in _blok))

# ── 3. A sorrend: a licenc-kapu a dashboard ELŐTT fut ──────────────────
# ⚠ Enélkül a fejléc az ELSŐ indításkor üres volna: a token még nem létezne,
# amikor az ablak felépül.
_main = (ROOT / "main.py").read_text(encoding="utf-8")
_lic_i = _main.find("ensure_licence(")
_win_i = _main.find("DashboardWindow(")
check("a licenc-kapu a DashboardWindow ELŐTT fut",
      0 < _lic_i < _win_i, f"kapu@{_lic_i} < ablak@{_win_i}")

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

"""A licenc állapota LÁTSZÓDJON a fejlécben — ne csak a naplóban.

⚠ A KÉRÉS (2026-08-25): „Még azt szeretném, ha ide fentre felírná a
bejelentkezett felhasználónevet." — majd a folytatás: ha a licencszerver
leáll, semmi nem szól róla.

A LELET. A türelmi idő eddig KIZÁRÓLAG egy naplósorban létezett („a szerver nem
érhető el — a mentett ellenőrzést nézem"), egy ablakos programban pedig a napló
az a hely, ahova senki nem néz. A felhasználó napokig futott volna abban a
hitben, hogy minden rendben, és a hiány pontosan akkor derült volna ki, amikor a
program 72 óra múlva **már nem indul el**. Ez a projekt visszatérő néma
osztálya: a rendszer mást csinál, mint amit a felhasználó hisz.

HÁROM ÁLLAPOT, három üzenettel:
  `nincs` — ebben a futásban nem volt ellenőrzés (a backtest és az
            optimalizálás licenc NÉLKÜL is megy) → csak az e-mail látszik.
            ⚠ Amiről nem tudunk, arról nem állítunk semmit.
  `ok`    — friss szerver-válasz. A közelgő LEJÁRAT is ide tartozik: azt
            azelőtt kell látni, hogy megállítana.
  `grace` — a szerver nem válaszolt, mentésből futunk, és ez VÉGES.
"""
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

results = []
import json as _json
_HU_CAT = _json.loads((ROOT / "lang" / "hu.json").read_text(encoding="utf-8"))


def _says(key, *words):
    """A kulcs magyar szovege tartalmazza-e mindet? (i18n utan a felirat mar
    nem a forrasban van — a teszt a KATALOGUST kerdezi.)"""
    txt = _HU_CAT.get(key, "")
    return all(w in txt for w in words)




def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from core import licence

# ── 1. A mentett e-mail visszaolvasható ────────────────────────────────
_REAL_T, _REAL_C = licence.TOKEN_PATH, licence.CACHE_PATH
_TMP = Path(tempfile.mkdtemp(prefix="tf_hdr_"))
licence.TOKEN_PATH = _TMP / "token.json"
licence.CACHE_PATH = _TMP / "cache.json"
try:
    check("nincs mentés → ÜRES e-mail (nem hibázik)",
          licence.stored_email() == "")

    licence.save_token("tfl_proba", "valaki@example.com")
    check("mentés után visszaolvasható",
          licence.stored_email() == "valaki@example.com")

    # ⚠ SÉRÜLT fájl: a fejléc maradjon üres, de a program NE álljon meg. Egy
    # kivétel itt a Tk-visszahívásban a stderr-re menne, ahol egy ablakos
    # programban SENKI nem látja.
    licence.TOKEN_PATH.write_text("{ ez nem json", encoding="utf-8")
    check("SÉRÜLT fájl → üres, nem kivétel", licence.stored_email() == "")

    licence.TOKEN_PATH.write_text(json.dumps({"token": "tfl_x"}), encoding="utf-8")
    check("e-mail nélküli mentés → üres", licence.stored_email() == "")

    # ── 2. `status()`: ellenőrzés NÉLKÜL nem állít semmit ──────────────
    licence._utolso = None
    st = licence.status()
    check("⚠ ellenőrzés nélkül az állapot „nincs”", st.get("allapot") == "nincs",
          str(st.get("allapot")))
    check("...és nincs kitalált türelmi idő", st.get("turelmi_ora") is None)

    # ── 3. A `check()` MINDEN ágon feljegyzi az eredményt ──────────────
    # ⚠ EZ A LÉNYEGI ÁLLÍTÁS. A korábbi hibaosztály pont az volt, hogy egy
    # korai `return` nyomtalanul elvitte az információt — a felület pedig nem
    # tudta megkülönböztetni a „minden rendben”-t a „fogalmam sincs”-től.
    licence.save_token("tfl_proba", "valaki@example.com")

    licence._utolso = None
    _elozo_token = licence.TOKEN_PATH
    licence.TOKEN_PATH = _TMP / "nincs_ilyen.json"
    licence.check("123")                       # → no_token ág
    licence.TOKEN_PATH = _elozo_token
    check("a `no_token` ág is feljegyződik",
          licence.last_result() is not None
          and licence.last_result().reason == "no_token",
          getattr(licence.last_result(), "reason", "—"))

    # Hálózati hiba + nincs mentés → offline_no_cache
    _eredeti_post = licence._post
    licence._post = lambda *a, **k: (False, "URLError: nincs hálózat")
    licence._utolso = None
    licence.check("123")
    check("a hálózati hiba ága is feljegyződik",
          licence.last_result().reason == "offline_no_cache",
          licence.last_result().reason)
    check("...és az állapot NEM „ok”", licence.status()["allapot"] == "nem")

    # ── 4. Türelmi idő: `grace` + a hátralévő órák ─────────────────────
    # Aláírt gyorsítótárat gyártunk: a `verify` a valódi kulcsot nézné, ezért
    # azt mókoljuk ki — itt nem az aláírást teszteljük, hanem az ÁLLAPOTOT.
    _eredeti_verify = licence.verify
    licence.verify = lambda *a, **k: True
    # ⚠ NEM PONTOSAN 20 óra: a `status()` ÓRÁRA KEREKÍT LEFELÉ, tehát egy pontos
    # órahatáron a két `time.time()` hívás közti EGY másodperc is átbillenti az
    # eredményt (52 → 51). Ez a teszt 2026-08-31-én pontosan így bukott el, egy
    # olyan futásban, ahol semmi nem változott körülötte. Egy perccel a határ
    # BELSŐ oldalára tesszük: az eredmény ugyanaz, de nem múlik másodperceken.
    _issued = int(time.time()) - 20 * 3600 + 60     # ~20 órája kelt
    licence._write_json(licence.CACHE_PATH, {
        "payload": {"ok": True, "account_number": "123", "issued_at": _issued,
                    "grace_seconds": 72 * 3600,
                    "expires_at": int(time.time()) + 200 * 86400,
                    "reason": "ok_already_bound"},
        "signature": "akarmi"})
    licence._utolso = None
    r = licence.check("123")
    check("a mentésből INDUL (türelmi idő)", r.ok and r.from_cache)
    st = licence.status()
    check("⚠ az állapot „grace”", st["allapot"] == "grace", st["allapot"])
    check("...és a hátralévő idő 72−20 = 52 óra", st["turelmi_ora"] == 52,
          str(st["turelmi_ora"]))

    # ⚠ A türelmi idő VÉGE: 0 óra, nem negatív szám.
    licence._write_json(licence.CACHE_PATH, {
        "payload": {"ok": True, "account_number": "123",
                    "issued_at": int(time.time()) - 71 * 3600 - 1800,
                    "grace_seconds": 72 * 3600,
                    "expires_at": int(time.time()) + 200 * 86400},
        "signature": "akarmi"})
    licence._utolso = None
    licence.check("123")
    check("a határon 0 óra (nem negatív)", licence.status()["turelmi_ora"] == 0,
          str(licence.status()["turelmi_ora"]))

    # ── 5. Közelgő lejárat — a friss válaszból is ──────────────────────
    # ⚠ Ezt AZELŐTT kell látni, hogy megállítana.
    licence._post = lambda *a, **k: (True, {
        "payload": {"ok": True, "v": 1, "reason": "ok_already_bound",
                    "account_number": "123", "issued_at": int(time.time()),
                    "grace_seconds": 72 * 3600,
                    "expires_at": int(time.time()) + 5 * 86400 + 3600},
        "signature": "akarmi"})
    licence._utolso = None
    licence.check("123")
    st = licence.status()
    check("friss válasz → az állapot „ok”", st["allapot"] == "ok", st["allapot"])
    check("...és NINCS türelmi idő kiírva", st["turelmi_ora"] is None)
    # 5 nap + 1 óra → FELFELÉ kerekítve 6. A túl korai figyelmeztetés
    # ártalmatlan, a késői nem.
    check("⚠ a lejáratig hátralévő nap FELFELÉ kerekít", st["lejar_nap"] == 6,
          str(st["lejar_nap"]))

    licence.verify = _eredeti_verify
    licence._post = _eredeti_post
finally:
    licence.TOKEN_PATH, licence.CACHE_PATH = _REAL_T, _REAL_C
    licence._utolso = None
    shutil.rmtree(_TMP, ignore_errors=True)

check("a valódi útvonalak visszaálltak",
      str(licence.TOKEN_PATH).endswith("licence_token.json")
      and str(licence.CACHE_PATH).endswith("licence_cache.json"))

# ── 6. A felület tényleg kiírja ────────────────────────────────────────
_gui = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
check("van külön címke a fejlécben", "self.lbl_licence" in _gui)
check("...és van frissítő metódusa", "def _refresh_licence_label(" in _gui)

_i = _gui.find("def _refresh_licence_label")
_j = _gui.find("\n    # ── Piaci adat", _i)
_blok = _gui[_i:_j]

check("a `status()`-t használja (nem csak az e-mailt)", "_lic.status()" in _blok)
check("⚠ a türelmi időt KIÍRJA", "gui.hdr.no_licence_server" in _blok
      and _says("gui.hdr.no_licence_server", "nincs licencszerver"))
check("⚠ a közelgő lejáratot is", "gui.hdr.licence_expires" in _blok
      and _says("gui.hdr.licence_expires", "licenc lejár"))
check("a türelmi idő SZÍNEZVE van (nem szürke sor a szürkék közt)",
      "FG_RED" in _blok and "FG_YELLOW" in _blok)
check("ellenőrzés nélkül csak az e-mail látszik",
      "szoveg, szin = _email, FG_GRAY" in _blok)

# ⚠ A FÁJLBAN NINCS modul-szintű `logging` import — csak függvényeken belül.
check("⚠ a naplózás LOKÁLIS importtal megy", "import logging as _logging" in _blok)
check("⚠ hiba esetén sem áll meg a felület",
      "except Exception" in _blok and "st = {}" in _blok)

# ⚠ Az U+1F464 emoji-kódpont a mono betűtípusból hiányzik → a rendszer
# emoji-fontjából esik vissza, aminek MÁS az alapvonala (a felhasználó vette
# észre: „az ember ikon egy kicsit lejjebb van mint a szöveg").
check("⚠ nincs BMP-n kívüli emoji a fejléc-címkében",
      all(ord(c) < 0x1F000 for c in _blok))

# ⚠ Másodpercenként fut: csak VÁLTOZÁSKOR nyúljon a widgethez.
check("csak változáskor rajzol újra", "_lic_utolso" in _blok)
check("⚠ ...és a másodperces frissítés MEGHÍVJA (a türelmi idő fogy)",
      _gui.count("self._refresh_licence_label()") >= 2,
      f"{_gui.count('self._refresh_licence_label()')} hívás")

# ── 7. A sorrend: a licenc-kapu a dashboard ELŐTT fut ──────────────────
_main = (ROOT / "main.py").read_text(encoding="utf-8")
_lic_i = _main.find("ensure_licence(")
_win_i = _main.find("DashboardWindow(")
check("a licenc-kapu a DashboardWindow ELŐTT fut", 0 < _lic_i < _win_i)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

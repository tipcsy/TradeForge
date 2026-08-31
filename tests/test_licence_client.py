"""A licenc-kliens: mit fogad el, mit nem, és mikor szabad offline indulni.

⚠ HÁLÓZAT NÉLKÜL fut — a `_post`-ot cseréljük ki. Egy olyan teszt, amihez élő
licencszerver kell, a gyakorlatban nem fut le; ez viszont a döntési logikát
méri, ami a lényeg.

A NÉGY KÉRDÉS, amit őriz:

  1. **Elutasítás vs. hálózati hiba.** A szerver MINDEN üzleti választ 200-zal
     ad, az `ok` mező dönt. Ha a szerver nemet mondott, a gyorsítótárhoz NEM
     szabad nyúlni — különben egy lejárt licenc örökké tovább futna. Ha viszont
     el sem értük, akkor igen: egy hálózati hiba reggel 8-kor ne állítsa le a
     kereskedést.
  2. **A gyorsítótár nem hamisítható.** Ez teszi a türelmi időt kényelmi
     funkcióvá és nem hátsó ajtóvá.
  3. **A csomag ehhez a SZÁMLÁHOZ szól.** Egy szabályosan kapott válasszal ne
     lehessen egy másik, be nem kötött számlán futni.
  4. **A türelmi idő véges**, és a szerver mondja meg, mennyi.
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


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from core import licence

# ── Saját kulcspár a teszthez ──────────────────────────────────────────
# ⚠ A beépített éles kulcsot NEM használjuk: ahhoz a szerver privát kulcsa
# kellene. Itt generálunk egyet, és a modul publikus kulcsát arra állítjuk.
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_PRIV = Ed25519PrivateKey.generate()
_PUB_B64 = base64.b64encode(_PRIV.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw)).decode()

_REAL_PUB = licence.SERVER_PUBLIC_KEY
licence.SERVER_PUBLIC_KEY = _PUB_B64

_TMP = Path(tempfile.mkdtemp(prefix="tf_lic_"))
licence.TOKEN_PATH = _TMP / "token.json"
licence.CACHE_PATH = _TMP / "cache.json"


def sign(payload: dict) -> str:
    return base64.b64encode(_PRIV.sign(licence._canonical(payload))).decode()


def payload(ok=True, reason="ok_newly_bound", account="6264021",
            issued_ago=0, grace_h=72, expires_in_days=365):
    now = int(time.time())
    return {"v": 1, "ok": ok, "reason": reason, "product": "tradeforge",
            "account_number": account, "issued_at": now - issued_ago,
            "grace_seconds": grace_h * 3600,
            "expires_at": now + expires_in_days * 86400,
            "account_limit": 3, "accounts_used": 1}


def server(reply=None, reachable=True):
    """A `_post` helyettesítése. `reachable=False` → hálózati hiba."""
    def _fake(api, path, body):
        if not reachable:
            return False, "URLError: nincs kapcsolat"
        p = reply if reply is not None else payload()
        return True, {"payload": p, "signature": sign(p),
                      "message": "", "bound_accounts": ["111", "222", "333"]}
    return _fake


try:
    # ── 1. Token nélkül ────────────────────────────────────────────────
    licence.forget_token()
    r = licence.check("6264021")
    check("token nélkül nem indul", not r.ok and r.reason == "no_token")
    check("...és belépést KÉR (nem csak hibát ír)", r.needs_login)

    licence.save_token("tfl_proba-token", "a@b.hu")
    check("a mentett token visszaolvasható",
          licence.stored_token() == "tfl_proba-token")

    # ── 2. Sikeres validálás ───────────────────────────────────────────
    licence._post = server()
    r = licence.check("6264021")
    check("érvényes válasz → indulhat", r.ok and r.reason == "ok_newly_bound")
    check("...és a gyorsítótár elkészült", licence.CACHE_PATH.exists())

    # ── 3. ELUTASÍTÁS: a gyorsítótárhoz NEM nyúlunk ────────────────────
    # ⚠ EZ A LEGFONTOSABB SZABÁLY. Ha az elutasítás után a program a tegnapi
    # csomaggal elindulna, egy lejárt licenc a türelmi idő végéig — vagy
    # rosszabb esetben örökké — tovább futna.
    licence._post = server(payload(ok=False, reason="expired"))
    r = licence.check("6264021")
    check("a szerver NEMET mond → nem indul", not r.ok and r.reason == "expired")
    check("⚠ ...és a régi gyorsítótárat ELDOBJA",
          not licence.CACHE_PATH.exists())

    # ── 4. Hálózati hiba → türelmi idő ─────────────────────────────────
    licence._post = server()
    licence.check("6264021")                     # friss mentés
    licence._post = server(reachable=False)
    r = licence.check("6264021")
    check("hálózati hibánál a mentésből INDUL", r.ok and r.from_cache,
          r.reason)
    check("...és megmondja, meddig", "óráig" in r.message, r.message)

    # ── 5. A türelmi idő VÉGES ─────────────────────────────────────────
    old = payload(issued_ago=80 * 3600)          # 80 órás, a keret 72
    licence.CACHE_PATH.write_text(
        json.dumps({"payload": old, "signature": sign(old)}), encoding="utf-8")
    r = licence.check("6264021")
    check("a lejárt türelmi idő NEM indít", not r.ok and r.reason == "offline_expired")

    # ── 6. A gyorsítótár nem hamisítható ───────────────────────────────
    jo = payload()
    hamis = dict(jo)
    hamis["expires_at"] = 4102444800             # 2100
    licence.CACHE_PATH.write_text(
        json.dumps({"payload": hamis, "signature": sign(jo)}), encoding="utf-8")
    r = licence.check("6264021")
    check("⚠ az ÁTÍRT csomag érvénytelen (aláírás)",
          not r.ok, r.reason)

    # ── 7. A csomag EHHEZ a számlához szól ─────────────────────────────
    jo = payload(account="6264021")
    licence.CACHE_PATH.write_text(
        json.dumps({"payload": jo, "signature": sign(jo)}), encoding="utf-8")
    r = licence.check("9999999")                 # MÁSIK számla, offline
    check("⚠ másik számlára a mentés NEM érvényes",
          not r.ok and r.reason == "offline_no_cache", r.reason)
    check("...és ezt MEGKÜLÖNBÖZTETI a lejárt türelmi időtől",
          "nincs korábbi" in r.message, r.message)

    # ── 8. Elutasítási okok szövege ────────────────────────────────────
    for ok_kod in ("bad_token", "no_free_slot", "suspended", "user_inactive",
                   "no_licence", "expired"):
        licence._post = server(payload(ok=False, reason=ok_kod))
        r = licence.check("6264021")
        check(f"'{ok_kod}' magyar üzenetet kap",
              bool(r.message) and r.message != ok_kod, r.message[:52])

    licence._post = server(payload(ok=False, reason="bad_token"))
    r = licence.check("6264021")
    check("a visszavont token ÚJRA belépést kér", r.needs_login)

    licence._post = server(payload(ok=False, reason="no_free_slot"))
    r = licence.check("6264021")
    check("a betelt slotnál KIÍRJA, mi van bekötve", "111" in r.message,
          r.message[:70])

    # ── 9. Formátum-verzió ─────────────────────────────────────────────
    # ⚠ Egy ÚJABB szerver-formátumot NEM értelmezünk félre: inkább elutasítunk.
    ujabb = payload()
    ujabb["v"] = 99
    licence._post = server(ujabb)
    r = licence.check("6264021")
    check("újabb csomag-formátum → frissítést kér",
          not r.ok and r.reason == "version_mismatch")

    # ── 10. Idegen kulccsal aláírt válasz ──────────────────────────────
    masik = Ed25519PrivateKey.generate()

    def _idegen(api, path, body):
        p = payload()
        return True, {"payload": p,
                      "signature": base64.b64encode(
                          masik.sign(licence._canonical(p))).decode()}
    licence._post = _idegen
    r = licence.check("6264021")
    check("⚠ IDEGEN kulccsal aláírt válasz elutasítva",
          not r.ok and r.reason == "bad_signature")

    # ── 11. A gépnév a token címkéje ───────────────────────────────────
    check("a gépnév kitöltődik (ez lesz a token címkéje)",
          bool(licence.machine_label()), licence.machine_label())

    # ── 11b. A KLIENS BEMUTATKOZÁSA ────────────────────────────────────
    # ⚠ EZ NEM UDVARIASSÁG, HANEM MŰKÖDÉSI FELTÉTEL. A Python `urllib`
    # alapértelmezett user-agentje `Python-urllib/<verzió>`, és a Cloudflare
    # bot-védelme ezt BLOKKOLJA. Mérve az éles szerveren (2026-08-25):
    #   Python-urllib/3.14  -> 403, majd időtúllépés
    #   TradeForge/2.73.0   -> 200
    # Enélkül a licenc-ellenőrzés SOHA nem sikerülne élesben: a kliens „a
    # szerver nem érhető el"-t látna, türelmi időbe menne, és 72 óra múlva
    # megállna — a hibaüzenet pedig a hálózatra mutatna, nem ide.
    _h = licence._headers()
    check("a kérés SAJÁT user-agenttel megy", "User-Agent" in _h)
    check("...és a TradeForge nevében mutatkozik be",
          _h["User-Agent"].startswith("TradeForge"), _h["User-Agent"])
    check("⚠ ...tehát NEM a Python alapértelmezettjével (azt a Cloudflare tiltja)",
          "urllib" not in _h["User-Agent"].lower())
    check("a verzió is benne van (a szerver naplójában látszik)",
          any(c.isdigit() for c in _h["User-Agent"]), _h["User-Agent"])
    _src = (ROOT / "core" / "licence.py").read_text(encoding="utf-8")
    check("MINDEN kérés a közös fejléc-építőt használja",
          _src.count("headers=_headers(") >= 2 and
          '"Content-Type": "application/json"}' not in _src.split("def _headers")[1],
          f"{_src.count('headers=_headers(')} hívás")

finally:
    licence.SERVER_PUBLIC_KEY = _REAL_PUB
    shutil.rmtree(_TMP, ignore_errors=True)

# ── 12. A kapu CSAK az élő kereskedést zárhatja ────────────────────────
# ⚠ A KAPU JELENLEG KI VAN VEZETVE a main.py-ból (a licencszerver még nincs
# élesítve, és bemutatóhoz a programnak meglepetés nélkül kell indulnia). Ezért
# a teszt NEM azt követeli, hogy be legyen kötve — hanem azt az invariánst
# őrzi, ami MINDKÉT állapotban igaz:
#
#     ha a kapu be van kötve, akkor PONTOSAN EGYSZER, és csakis a cmd_live-ban.
#
# Így a visszakapcsoláskor nem kell tesztet átírni, viszont ha valaki a
# backtest vagy az optimalizálás útjába tenné, itt bukik el.
_main = (ROOT / "main.py").read_text(encoding="utf-8")
# ⚠ A KOMMENTEKET KI KELL SZŰRNI: a visszakapcsolás mintája kommentként ott van
# a main.py-ban, és egy szöveges keresés kódnak látná.
_kod = chr(10).join(l for l in _main.splitlines()
                    if not l.strip().startswith("#"))
_hivas = _kod.count("ensure_licence(")

# ⚠ AZ INVARIÁNS NEM A HÍVÁSOK SZÁMA, HANEM A HELYE. Élő kereskedést TÖBB
# parancs is indíthat (`live` = motor + felület, `console` = motor felület
# nélkül), és mindegyiknek KELL a kapu — a szám tehát nőhet. Amit őrizni kell:
# a backtest, az optimalizálás és az adatletöltés SOSEM kapuzott. Azok nem
# nyúlnak a brókerszámlához, és ha egy lejárt licenc a backtestet is blokkolná,
# épp akkor nem tudnál dolgozni a rendszeren, amikor a megújításról döntesz.
_KAPUZOTT   = ("cmd_live", "cmd_console")     # élő kereskedés → KELL a kapu
_KAPUZATLAN = ("cmd_backtest", "cmd_optimize", "cmd_download", "cmd_dashboard")


def _fv_torzs(nev: str) -> str:
    """Egy `def <nev>` törzse a KÖVETKEZŐ `def`-ig (kommentek nélküli forrásból)."""
    i = _kod.find(f"def {nev}")
    if i < 0:
        return ""
    j = _kod.find(chr(10) + "def ", i + 5)
    return _kod[i:j if j > 0 else len(_kod)]


if _hivas:
    _hol = [n for n in (_KAPUZOTT + _KAPUZATLAN)
            if "ensure_licence(" in _fv_torzs(n)]
    check("⚠ a licenc-kapu CSAK élő kereskedésnél van bekötve",
          all(n in _KAPUZOTT for n in _hol), f"bekötve: {_hol}")
    check("⚠ ...és a backtest/optimalizálás/letöltés NEM kapuzott",
          not [n for n in _KAPUZATLAN if "ensure_licence(" in _fv_torzs(n)])
    check("...a `live` parancs kapuzott", "ensure_licence(" in _fv_torzs("cmd_live"))
    # ⚠ A `console` UGYANAZT a motort indítja, mint a `live` — ha ott kimaradna
    # a kapu, a licenc egyetlen paranccsal megkerülhető lenne.
    check("⚠ ...és a `console` is (különben megkerülhető a licenc)",
          "ensure_licence(" in _fv_torzs("cmd_console")
          if "def cmd_console" in _kod else True)
else:
    # Nem hiba, hanem ÁLLAPOT — de legyen látható, ne csak a kód olvasásából
    # derüljön ki. A visszakapcsolás mintája a main.py-ban, kommentben áll.
    check("a kapu jelenleg KI VAN VEZETVE (a szerver még nem éles)",
          "LICENC-KAPU: JELENLEG KI VAN VEZETVE" in _main)
    check("...és a visszakapcsolás mintája ott van a main.py-ban",
          "ensure_licence(cfg" in _main)
# ⚠ A BEÉPÍTETT KULCS ÉRVÉNYESSÉGE. Egy elgépelt, csonka vagy véletlenül
# levágott kulcstól a program MINDEN választ hamisnak látna, és soha nem
# indulna el — a hibaüzenet pedig („a válasz nem hitelesíthető") a szerverre
# mutatna, nem ide. Egy Ed25519 publikus kulcs pontosan 32 bájt.
check("a beépített PUBLIKUS kulcs ki van töltve", len(_REAL_PUB) > 20)
try:
    import base64 as _b64
    _nyers = _b64.b64decode(_REAL_PUB, validate=True)
except Exception as _ex:
    _nyers = b""
check("...és érvényes base64", len(_nyers) > 0)
check("...és pontosan 32 bájt (Ed25519)", len(_nyers) == 32, f"{len(_nyers)} bájt")
try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey as _PK
    _PK.from_public_bytes(_nyers)
    _betolt = True
except Exception:
    _betolt = False
check("...és a cryptography be tudja tölteni", _betolt)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

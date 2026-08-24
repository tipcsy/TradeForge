"""Licenc-ellenőrzés indításkor — a TradeForge oldali kliens.

A program induláskor megkérdezi a licencszervert: él-e a felhasználó, nem járt-e
le, és futhat-e EZEN a brókerszámlán. A szerver oldala külön repóban:
`TradeForge.Licence` (FastAPI + MariaDB).

A FOLYAMAT, és miért így:

  1. Ha van tárolt **token**, azzal validálunk. Nincs kérdés, nincs másolás.
  2. Ha nincs (első indítás), vagy a token érvénytelen (visszavonták), a hívó
     bekéri az e-mail címet és a jelszót, mi pedig `login` + `token` hívással
     szerzünk újat. A jelszót NEM tároljuk — a token a hosszú életű belépő, és
     a portálról bármikor visszavonható.
  3. A címke a **gép neve**, tehát a portálon látszik, melyik példány melyik.

⚠ A HÁLÓZATI HIBA ÉS AZ ELUTASÍTÁS KÉT KÜLÖNBÖZŐ DOLOG, és ezen múlik az egész
türelmi idő. A szerver MINDEN üzleti választ HTTP 200-zal ad, az `ok` mező dönt:

  * **200 + ok=false** → a szerver MONDOTT NEMET. Ilyenkor a gyorsítótárhoz
    NEM szabad nyúlni, különben egy lejárt licenc örökké tovább futna.
  * **hálózati/HTTP hiba** → nem tudjuk, mit mondana. Ilyenkor jöhet a
    gyorsítótár, a türelmi időn belül.

Ha egy 403-at használnánk elutasításra, a kettőt nem lehetne megkülönböztetni:
egy rosszul konfigurált proxy, egy Cloudflare hibaoldal vagy egy szállodai wifi
belépőoldala ugyanúgy 403-at ad.

⚠ A GYORSÍTÓTÁR ALÁÍRT. Enélkül a türelmi idő hátsó ajtó lenne: a fájlt bárki
átírhatná „lejár 2099-ben"-re. A szerver Ed25519-cel írja alá a választ, itt a
PUBLIKUS kulcs van beépítve, és a csomag viszi a kiállítás idejét — egy régi
csomag magától elévül.
"""

from __future__ import annotations

import base64
import json
import logging
import platform
import time
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
TOKEN_PATH = ROOT / "data" / "licence_token.json"
CACHE_PATH = ROOT / "data" / "licence_cache.json"

# A termék azonosítója a szerveren. Később stratégiánként külön termék jöhet;
# az alapprogram ez marad.
PRODUCT = "tradeforge"

# ⚠ A SZERVER PUBLIKUS ALÁÍRÓ KULCSA. NEM titok — a párja (a privát) a szerver
# `.env`-jében él, és sosem hagyja el azt. Ha a szerveren kulcsot cserélsz, ezt
# is cserélni kell, különben a program MINDEN választ hamisnak lát.
# A `GET /api/v1/pubkey` bármikor megmondja az aktuálisat.
SERVER_PUBLIC_KEY = "3FHqTdIqWCtP3BQioZgGQONJRCOaY8pLNINcEqYs8ns="

DEFAULT_API = "https://licence-api.tipcsy.hu/api/v1"

# A csomag-formátum, amit ez a kliens ért. Ha a szerver ennél újabbat küld, NEM
# értelmezzük félre: inkább elutasítjuk, és a felhasználó frissít.
PAYLOAD_VERSION = 1

TIMEOUT_SEC = 10


# ── Az eredmény ─────────────────────────────────────────────────────────
class Result:
    """A licenc-ellenőrzés kimenete. `ok` → indulhat a program."""

    def __init__(self, ok: bool, reason: str, message: str,
                 from_cache: bool = False, payload: "dict | None" = None,
                 needs_login: bool = False):
        self.ok = ok
        self.reason = reason
        self.message = message
        self.from_cache = from_cache
        self.payload = payload or {}
        # A hívó ebből tudja, hogy érdemes belépő-ablakot mutatni (nem pedig
        # csak hibát kiírni és kilépni).
        self.needs_login = needs_login

    def __repr__(self) -> str:
        return f"<Licenc {'OK' if self.ok else 'NEM'} {self.reason}>"


# ⚠ A SZÖVEG ITT VAN, nem a szerveren. A szerver gépi ok-kódot ad; a mondat a
# program nyelvén és stílusában szólal meg, és a szerver átírása nem töri el.
MESSAGES = {
    "ok_already_bound": "Licenc rendben.",
    "ok_newly_bound":   "Licenc rendben — a számla mostantól be van kötve.",
    "bad_token":        "A mentett belépő érvénytelen (talán visszavontad a "
                        "portálon). Jelentkezz be újra.",
    "user_inactive":    "A fiókod le van tiltva. Vedd fel a kapcsolatot az "
                        "üzemeltetővel.",
    "no_licence":       "Nincs licenced a TradeForge-hoz.",
    "suspended":        "A licenced fel van függesztve.",
    "expired":          "A licenced LEJÁRT.",
    "no_free_slot":     "Elfogytak a számla-slotok: ez a számlaszám nincs "
                        "bekötve, és nincs több hely.",
    "bad_request":      "Hibás kérés a licencszerver felé.",
    # Csak kliens-oldali okok
    "no_token":         "Még nincs mentett belépő. Jelentkezz be a licenchez.",
    "offline_grace":    "A licencszerver nem érhető el — a program a korábbi "
                        "ellenőrzés alapján indul.",
    "offline_expired":  "A licencszerver nem érhető el, és a türelmi idő lejárt.",
    "offline_no_cache": "A licencszerver nem érhető el, és nincs korábbi, "
                        "erre a számlára szóló ellenőrzés.",
    "bad_signature":    "A licencszerver válasza nem hitelesíthető.",
    "version_mismatch": "A licencszerver újabb formátumot használ — frissítsd a "
                        "programot.",
}


def _msg(reason: str, extra: str = "") -> str:
    return (MESSAGES.get(reason, reason) + (f" ({extra})" if extra else "")).strip()


# ── Aláírás-ellenőrzés (a szerver `app/signing.py`-jának párja) ─────────
def _canonical(payload: dict) -> bytes:
    """⚠ BITRE ugyanaz, mint a szerveren. Az aláírás a bájtokra vonatkozik,
    tehát a legkisebb eltérés (szóköz, kulcs-sorrend, unicode-escape) miatt
    MINDEN válasz hamisnak látszana — és ez csak egy szerver-kimaradáskor
    derülne ki, amikor a gyorsítótárra szükség lenne."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def verify(payload: dict, signature_b64: str, public_b64: str = "") -> bool:
    """⚠ A kulcs alapértéke FUTÁSIDŐBEN oldódik fel, nem a definiáláskor.

    A `public_b64: str = SERVER_PUBLIC_KEY` alak csapda volt: a Python az
    alapértéket a függvény DEFINIÁLÁSAKOR köti hozzá, tehát a modul-szintű
    konstans későbbi átírása (saját szerver másik kulccsal, teszt) NEM hatott
    volna rá — a program némán a régi kulccsal ellenőrzött volna tovább."""
    public_b64 = public_b64 or SERVER_PUBLIC_KEY
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey)
        Ed25519PublicKey.from_public_bytes(
            base64.b64decode(public_b64)).verify(
                base64.b64decode(signature_b64), _canonical(payload))
        return True
    except Exception:
        # Bármilyen hiba ELUTASÍTÁS. Itt a némaság helyes: a hívó a False-ból
        # tudja, mit tegyen, a részletek pedig csak támadónak adnának fogódzót.
        return False


# ── Tárolás ─────────────────────────────────────────────────────────────
def _read_json(p: Path) -> dict:
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception as ex:
        # ⚠ NEM néma: egy sérült token-fájl azt jelenti, hogy a felhasználó
        # újra be fog kényszerülni jelentkezni, és értenie kell, miért.
        log.warning("licenc: a(z) %s nem olvasható (%s) — újat kell kérni",
                    p.name, ex)
    return {}


def _write_json(p: Path, data: dict) -> bool:
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(p)            # atomikus csere
        return True
    except OSError as ex:
        log.error("licenc: a(z) %s nem írható (%s) — a következő indításnál "
                  "újra be kell jelentkezni", p.name, ex)
        return False


def stored_token() -> str:
    return str(_read_json(TOKEN_PATH).get("token") or "")


def save_token(token: str, email: str = "") -> bool:
    return _write_json(TOKEN_PATH, {"token": token, "email": email,
                                    "machine": machine_label(),
                                    "saved_at": int(time.time())})


def forget_token() -> None:
    """A mentett belépő eldobása (kijelentkezés a programból)."""
    for p in (TOKEN_PATH, CACHE_PATH):
        try:
            p.unlink(missing_ok=True)
        except OSError as ex:
            log.warning("licenc: a(z) %s nem törölhető (%s)", p.name, ex)


def machine_label() -> str:
    """A gép neve — ez lesz a token címkéje a portálon.

    ⚠ Ettől lesz a portál lista értelmezhető: a felhasználó felismeri, melyik
    sor melyik gépé, és a szerver ez alapján cseréli le a régi tokent, ha
    ugyanarról a gépről érkezik új kérés (gépenként EGY élő token)."""
    try:
        return platform.node() or "ismeretlen gép"
    except Exception:
        return "ismeretlen gép"


# ── Hálózat ─────────────────────────────────────────────────────────────
def _post(api: str, path: str, body: dict) -> tuple:
    """`(sikerult_e_beszelni_a_szerverrel, valasz_vagy_hibauzenet)`.

    ⚠ A visszatérés ELSŐ tagja a lényeg: azt mondja meg, hogy egyáltalán
    ELÉRTÜK-e a szervert. Ebből dől el, szabad-e a gyorsítótárhoz nyúlni."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(
        api.rstrip("/") + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as r:
            return True, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        # HTTP hibakód: a szerver (vagy egy közbeiktatott proxy) válaszolt, de
        # NEM üzleti válasszal. Ezt hálózati hibaként kezeljük — lásd a modul
        # fejlécét: az üzleti nem MINDIG 200-zal jön.
        try:
            _body = json.loads(ex.read().decode("utf-8"))
            _det = _body.get("detail") or ""
        except Exception:
            _det = ""
        return False, f"HTTP {ex.code}{': ' + str(_det) if _det else ''}"
    except Exception as ex:
        return False, f"{type(ex).__name__}: {ex}"


def login_and_get_token(email: str, password: str, api: str = DEFAULT_API,
                        label: str = "") -> tuple:
    """Egyszeri belépés → hosszú életű token. `(sikerult, token_vagy_hiba)`.

    A jelszó ITT ÉR VÉGET: a hívó eldobhatja, mi nem tároljuk. A tokent a hívó
    menti a `save_token`-nel."""
    ok, res = _post(api, "/auth/login", {"email": email, "password": password})
    if not ok:
        return False, f"Nem sikerült elérni a licencszervert ({res})."
    jwt = (res or {}).get("access_token")
    if not jwt:
        return False, "Hibás e-mail cím vagy jelszó."

    import urllib.error
    import urllib.request
    req = urllib.request.Request(
        api.rstrip("/") + "/auth/tokens",
        data=json.dumps({"label": label or machine_label()}).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {jwt}"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as r:
            data = json.loads(r.read().decode("utf-8"))
        return True, data["token"]
    except Exception as ex:
        return False, f"A belépő nem hozható létre ({type(ex).__name__}: {ex})."


# ── A gyorsítótár (türelmi idő) ─────────────────────────────────────────
def _cache_ok(account_number: str) -> "Result | None":
    """A tárolt, ALÁÍRT válasz — ha még elfogadható. `None`, ha nem használható.

    Négy feltétel, és mind a négy kell:
      1. az aláírás a mi publikus kulcsunkkal stimmel (nem hamisított),
      2. UGYANARRA a számlaszámra szól (nem egy másik gép csomagja),
      3. a kiállítás óta nem telt el a türelmi idő,
      4. a licenc lejárata a jövőben van.
    """
    c = _read_json(CACHE_PATH)
    payload, sig = c.get("payload"), c.get("signature")
    if not isinstance(payload, dict) or not sig:
        return None
    if not payload.get("ok"):
        # Elutasított választ SOSEM gyorsítótárazunk (lásd `check`), de ha
        # valahogy mégis ide kerülne, nem fogadjuk el.
        return None
    if not verify(payload, sig):
        log.warning("licenc: a mentett válasz aláírása ÉRVÉNYTELEN — eldobom")
        return None
    if str(payload.get("account_number")) != str(account_number):
        # Másik számlára szóló csomag: nem ér semmit. Enélkül egy szabályosan
        # kapott csomaggal egy MÁSIK, be nem kötött számlán is futna a program.
        return None
    now = int(time.time())
    grace = int(payload.get("grace_seconds") or 0)
    kor = now - int(payload.get("issued_at") or 0)
    if grace <= 0 or kor > grace:
        return Result(False, "offline_expired",
                      _msg("offline_expired",
                           f"a mentett ellenőrzés {kor // 3600} órás"),
                      from_cache=True, payload=payload)
    exp = int(payload.get("expires_at") or 0)
    if exp and exp <= now:
        return Result(False, "expired", _msg("expired"), from_cache=True,
                      payload=payload)
    hatra = (grace - kor) // 3600
    return Result(True, "offline_grace",
                  _msg("offline_grace", f"még {hatra} óráig"),
                  from_cache=True, payload=payload)


# ── A fő belépési pont ──────────────────────────────────────────────────
def check(account_number: str, api: str = DEFAULT_API, token: str = "",
          account_name: str = "", broker_server: str = "",
          app_version: str = "") -> Result:
    """A licenc ellenőrzése egy brókerszámlára. Ez fut a program indulásakor."""
    token = token or stored_token()
    if not token:
        return Result(False, "no_token", _msg("no_token"), needs_login=True)

    ok, res = _post(api, "/validate", {
        "token": token, "product": PRODUCT,
        "account_number": str(account_number),
        "account_name": account_name, "broker_server": broker_server,
        "app_version": app_version})

    if not ok:
        # ⚠ NEM ÉRTÜK EL a szervert → jöhet a gyorsítótár. Ez az egyetlen ág,
        # ahol szabad.
        log.warning("licenc: a szerver nem érhető el (%s) — a mentett "
                    "ellenőrzést nézem", res)
        cached = _cache_ok(str(account_number))
        if cached is not None:
            return cached
        # ⚠ KÜLÖN OK: nincs HASZNÁLHATÓ mentés erre a számlára — ez MÁS, mint
        # hogy a türelmi idő lejárt. A felhasználónak tudnia kell, hogy nem az
        # idővel van baj, hanem azzal, hogy ezen a számlán még sosem futott
        # sikeres ellenőrzés (pl. új számlaszám, vagy törölt gyorsítótár).
        return Result(False, "offline_no_cache",
                      _msg("offline_no_cache", str(res)))

    payload = (res or {}).get("payload") or {}
    sig = (res or {}).get("signature") or ""

    if int(payload.get("v") or 0) > PAYLOAD_VERSION:
        return Result(False, "version_mismatch", _msg("version_mismatch"))
    if not verify(payload, sig):
        # A szerver válaszolt, de nem a MI szerverünk (vagy kulcsot cseréltek).
        return Result(False, "bad_signature", _msg("bad_signature"))

    reason = str(payload.get("reason") or "")
    if payload.get("ok"):
        _write_json(CACHE_PATH, {"payload": payload, "signature": sig})
        return Result(True, reason, _msg(reason), payload=payload)

    # ⚠ A SZERVER MONDOTT NEMET → a gyorsítótárhoz NEM nyúlunk, sőt a régit
    # el is dobjuk: egy lejárt licenc ne indulhasson el a tegnapi csomaggal.
    try:
        CACHE_PATH.unlink(missing_ok=True)
    except OSError:
        pass

    extra = ""
    if reason == "no_free_slot":
        bound = (res or {}).get("bound_accounts") or []
        if bound:
            extra = "bekötve: " + ", ".join(str(b) for b in bound)
    elif reason == "expired" and payload.get("expires_at"):
        extra = time.strftime("%Y-%m-%d",
                              time.localtime(int(payload["expires_at"])))
    return Result(False, reason, _msg(reason, extra), payload=payload,
                  needs_login=(reason == "bad_token"))

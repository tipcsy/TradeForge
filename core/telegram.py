"""Telegram Bot API — a legkisebb réteg, ami az üzenetküldéshez kell.

⚠ SZÁNDÉKOSAN NINCS ÚJ FÜGGŐSÉG. A Bot API sima HTTPS+JSON; a `urllib` elég
hozzá, és a `core.licence` mintája (saját `User-Agent`, `(sikerult, valasz)`
visszatérés) itt is érvényes — egy CDN/WAF mögötti szolgáltatásnál a
`Python-urllib` alapértelmezett user-agent **működési feltétellé** vált, és ez
a projektben már egyszer pénzbe került (a licencszerver 403-at adott rá).

⚠ ÉS MIÉRT KÜLÖN MODUL a `core.notify`-tól: az értesítés DÖNTÉSI logikája
(csendes órák, dedup, per-pár kapcsolók) hálózat nélkül tesztelhető kell
maradjon. Itt van minden, ami hálózat; ott semmi.

⚠ A HIBA NEM SZÁLL FEL. Minden függvény `False`/üres értékkel tér vissza, ha
baj van — egy elérhetetlen Telegram nem állíthatja meg a kereskedést. Ami
elveszett, az egy üzenet; ami nem veszhet el, az a pozíció menedzsmentje.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

API = "https://api.telegram.org"
TIMEOUT_SEC = 15

# A Telegram üzenet-hossza 4096 karakter. Ennél hosszabbat DARABOLUNK, nem
# vágunk: egy félbevágott napi összefoglaló rosszabb, mint két üzenet.
MAX_HOSSZ = 4000


def _user_agent() -> str:
    try:
        from version import APP_VERSION
        return f"TradeForge/{APP_VERSION}"
    except Exception:
        return "TradeForge"


def _hivas(token: str, metodus: str, body: dict, timeout=None) -> tuple:
    """`(sikerult, valasz_vagy_hibauzenet)`. Kivételt SOSEM enged ki.

    ⚠ A `timeout` a SOCKET várakozása. Long pollingnál ennek NAGYOBBNAK kell
    lennie, mint amennyit a Telegramtól kérünk — különben a saját socketünk
    vágja el a válaszra váró kapcsolatot, és a hívó hálózati hibának látja."""
    if not token:
        return False, "nincs token"
    req = urllib.request.Request(
        f"{API}/bot{token}/{metodus}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "User-Agent": _user_agent()},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout or TIMEOUT_SEC) as r:
            return True, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        # ⚠ A Telegram a HIBÁT IS JSON-ban indokolja (`description`), és az
        # üzenet a felhasználóé: „chat not found", „bot was blocked by the
        # user". Enélkül csak egy 400-as kód maradna, amiből nem derül ki,
        # hogy a `chat_id` rossz-e vagy a bot van letiltva.
        try:
            _b = json.loads(ex.read().decode("utf-8"))
            _d = _b.get("description") or ""
        except Exception:
            _d = ""
        return False, f"HTTP {ex.code}{': ' + str(_d) if _d else ''}"
    except Exception as ex:
        return False, f"{type(ex).__name__}: {ex}"


def _darabol(szoveg: str) -> list:
    """Hosszú szöveg → üzenet-darabok, SORHATÁRON vágva."""
    if len(szoveg) <= MAX_HOSSZ:
        return [szoveg]
    ki, akt = [], ""
    for sor in szoveg.split(chr(10)):
        # ⚠ EGY TÚL HOSSZÚ SOR IS DARABOLANDÓ, nem levágandó. Az első változat
        # `sor[:MAX_HOSSZ]`-t írt: egy sortörés nélküli hosszú szöveg (például
        # egy kivétel nyoma egyetlen sorban) NÉMÁN elveszítette a végét — pont
        # azt a részt, ami a hibakereséshez kellett volna.
        while len(sor) > MAX_HOSSZ:
            if akt:
                ki.append(akt)
                akt = ""
            ki.append(sor[:MAX_HOSSZ])
            sor = sor[MAX_HOSSZ:]
        if len(akt) + len(sor) + 1 > MAX_HOSSZ:
            if akt:
                ki.append(akt)
            akt = sor
        else:
            akt = (akt + chr(10) + sor) if akt else sor
    if akt:
        ki.append(akt)
    return ki


def send(token: str, chat_ids, szoveg: str) -> bool:
    """Üzenet MINDEN engedélyezett címzettnek. `True`, ha legalább egynek ment.

    ⚠ A RÉSZLEGES SIKER IS SIKER: ha két címzettből az egyik letiltotta a
    botot, a másiknak akkor is menjen — és a hibáról legyen napló-nyom."""
    if isinstance(chat_ids, (str, int)):
        chat_ids = [chat_ids]
    ment = False
    for cid in (chat_ids or ()):
        for darab in _darabol(str(szoveg)):
            ok, res = _hivas(token, "sendMessage",
                             {"chat_id": str(cid), "text": darab,
                              "disable_web_page_preview": True})
            if ok and isinstance(res, dict) and res.get("ok"):
                ment = True
            else:
                log.warning("telegram: a küldés nem sikerült (%s): %s", cid, res)
    return ment


# A Telegram a KÉPALÁÍRÁST 1024 karakterre korlátozza (a sima üzenetet 4096-ra).
MAX_CAPTION = 1024


def _multipart(fields: dict, file_field: str, filename: str, data: bytes,
               mime: str = "image/png") -> tuple:
    """`(törzs, content_type)` egy `multipart/form-data` kéréshez — a képfeltöltés
    egyetlen módja a Bot API-ban (a JSON-törzs nem hordozhat bináris fájlt)."""
    import uuid
    hatar = uuid.uuid4().hex
    sorok = []
    for k, v in fields.items():
        sorok.append(f"--{hatar}\r\nContent-Disposition: form-data; "
                     f"name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8"))
    sorok.append(f"--{hatar}\r\nContent-Disposition: form-data; "
                 f"name=\"{file_field}\"; filename=\"{filename}\"\r\n"
                 f"Content-Type: {mime}\r\n\r\n".encode("utf-8"))
    sorok.append(data)
    sorok.append(f"\r\n--{hatar}--\r\n".encode("utf-8"))
    return b"".join(sorok), f"multipart/form-data; boundary={hatar}"


def send_photo(token: str, chat_id, png: bytes, caption: str = "",
               gombok=None) -> bool:
    """KÉP küldése (képaláírással, opcionálisan GOMBOKKAL — a jóváhagyó
    ajánlathoz). `True`, ha kiment.

    ⚠ A 1024 karakternél hosszabb aláírás levágódna — ilyenkor a kép rövid
    aláírással megy, a teljes szöveg utána KÜLÖN üzenetben (a gombokkal
    együtt, hogy a döntés a szöveg mellett legyen)."""
    if not token:
        return False
    szoveg = str(caption or "")
    hosszu = len(szoveg) > MAX_CAPTION
    fields = {"chat_id": str(chat_id),
              "caption": (szoveg.split(chr(10))[0][:MAX_CAPTION] if hosszu
                          else szoveg)}
    if gombok and not hosszu:
        fields["reply_markup"] = json.dumps({"inline_keyboard": [[
            {"text": str(f), "callback_data": str(a)[:64]} for f, a in gombok]]})
    body, ctype = _multipart(fields, "photo", "jelzes.png", png)
    req = urllib.request.Request(
        f"{API}/bot{token}/sendPhoto", data=body,
        headers={"Content-Type": ctype, "User-Agent": _user_agent()},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC * 2) as r:
            res = json.loads(r.read().decode("utf-8"))
    except Exception as ex:
        log.warning("telegram: a kép nem ment ki (%s): %s", chat_id, ex)
        return False
    if not (isinstance(res, dict) and res.get("ok")):
        log.warning("telegram: a kép nem ment ki (%s): %s", chat_id, res)
        return False
    if hosszu:
        if gombok:
            send_buttons(token, chat_id, szoveg, gombok)
        else:
            send(token, [chat_id], szoveg)
    return True


def send_buttons(token: str, chat_id, szoveg: str, gombok) -> bool:
    """Üzenet GOMBOKKAL (`inline_keyboard`). `gombok`: `[(felirat, adat), …]`.

    ⚠ MIÉRT GOMB, ÉS NEM „írd be, hogy igen". Három okból, és mindhárom
    számít: (1) a gomb felirata a katalógusból jön, tehát a nyelvvel együtt
    mozog; (2) nincs elgépelés („igen"/„Igen"/„i"/„ok" mind ugyanaz a szándék,
    de mind külön kezelendő szöveg volna); (3) ⚠ a gomb MAGÁVAL VISZI az
    ajánlat azonosítóját — egy szöveges „igen" két egyidejű ajánlatnál
    kétértelmű lenne, és épp egy rossz páron csinálna valamit.

    ⚠ A `callback_data` legfeljebb 64 BÁJT lehet, ezért rövid azonosítót adunk
    át, nem a parancsot magát."""
    ok, res = _hivas(token, "sendMessage", {
        "chat_id": str(chat_id), "text": str(szoveg)[:MAX_HOSSZ],
        "disable_web_page_preview": True,
        "reply_markup": {"inline_keyboard": [[
            {"text": str(f), "callback_data": str(a)[:64]} for f, a in gombok]]},
    })
    if ok and isinstance(res, dict) and res.get("ok"):
        return True
    log.warning("telegram: a gombos üzenet nem ment ki (%s): %s", chat_id, res)
    return False


def answer_callback(token: str, callback_id: str, szoveg: str = "") -> bool:
    """A gombnyomás NYUGTÁZÁSA. ⚠ Enélkül a Telegram a gombon pörgő órát mutat
    ~30 másodpercig, és a felhasználó azt hiszi, elakadt."""
    ok, res = _hivas(token, "answerCallbackQuery",
                     {"callback_query_id": str(callback_id),
                      "text": str(szoveg)[:200]})
    return bool(ok and isinstance(res, dict) and res.get("ok"))


def edit_message(token: str, chat_id, message_id: int, szoveg: str) -> bool:
    """Egy elküldött üzenet ÁTÍRÁSA (a gombok eltűnnek vele).

    ⚠ EZ AKADÁLYOZZA MEG A KÉTSZERI VÉGREHAJTÁST: a megnyomott gomb helyén
    onnantól az EREDMÉNY áll, tehát nincs mit még egyszer megnyomni."""
    ok, res = _hivas(token, "editMessageText", {
        "chat_id": str(chat_id), "message_id": int(message_id),
        "text": str(szoveg)[:MAX_HOSSZ]})
    if ok and isinstance(res, dict) and res.get("ok"):
        return True
    # ⚠ KÉPES üzenetnek nincs „szövege", csak ALÁÍRÁSA: az `editMessageText`
    # ott hibát ad („there is no text in the message to edit"). A jóváhagyó
    # ajánlat v3.106.0 óta képpel megy — enélkül a gombnyomás után a gombok
    # a képen maradnának, és újra meg lehetne nyomni őket.
    ok, res = _hivas(token, "editMessageCaption", {
        "chat_id": str(chat_id), "message_id": int(message_id),
        "caption": str(szoveg)[:MAX_CAPTION]})
    return bool(ok and isinstance(res, dict) and res.get("ok"))


def updates(token: str, offset: int = 0, timeout: int = 0) -> tuple:
    """`(sikerult, frissitesek_listaja)` — a bejövő üzenetek (`getUpdates`).

    `offset`: az utoljára feldolgozott `update_id` + 1 (a Telegram csak ezután
    törli a régieket). `timeout > 0` → LONG POLLING: a szerver eddig vár egy új
    üzenetre, mielőtt üres listát adna. ⚠ A hosszú várakozás ezért NEM
    hiba — a hívónak külön szálon kell lennie, hogy a motor körét ne fogja meg."""
    # ⚠ A SOCKET TÚLÉLI A LONG POLLINGOT. A `TIMEOUT_SEC` 15 mp volt, a hívók
    # viszont 25 mp-es long pollingot kértek: csendes időszakban a socket
    # ELŐBB szakadt el, mint ahogy a Telegram válaszolt volna. A hurok ezt
    # hálózati HIBÁNAK vette, és növekvő várakozásba (2, 4, … 60 mp) ment —
    # így egy parancsra a válasz akár 75 másodpercet is késett, miközben
    # semmi baj nem volt. Épp ezt panaszolta a felhasználó
    # (2026-09-02: „a telegram válasz nagyon lassan jelenik meg").
    _t = int(timeout)
    ok, res = _hivas(token, "getUpdates",
                     {"offset": int(offset), "timeout": _t},
                     timeout=(_t + TIMEOUT_SEC) if _t > 0 else None)
    if ok and isinstance(res, dict) and res.get("ok"):
        return True, list(res.get("result") or [])
    return False, []


def discover_chats(token: str) -> list:
    """Kik írtak eddig a botnak — `[{"id", "name"}, …]`.

    ⚠ EZ VÁLTJA KI A @userinfobot-ot. A bot ÚGYSEM tud írni annak, aki nem
    kezdeményezett vele beszélgetést; ha tehát valaki már írt neki, a
    `chat_id`-ja itt amúgy is megvan. Egy kézzel átmásolt azonosítónál ez
    kevesebbet is lehet elgépelni."""
    ok, upd = updates(token)
    if not ok:
        return []
    ki, latott = [], set()
    for u in upd:
        for kulcs in ("message", "edited_message", "channel_post",
                      "callback_query"):
            m = u.get(kulcs) or {}
            chat = (m.get("chat") or (m.get("message") or {}).get("chat") or {})
            cid = chat.get("id")
            if cid is None or cid in latott:
                continue
            latott.add(cid)
            nev = " ".join(x for x in (chat.get("first_name"),
                                       chat.get("last_name")) if x)
            ki.append({"id": str(cid),
                       "name": nev or chat.get("title") or
                               chat.get("username") or "?"})
    return ki


def set_commands(token: str, parancsok, language_code: str = "") -> bool:
    """A bot PARANCS-MENÜJE (`setMyCommands`). `parancsok`: `[(nev, leiras), …]`.

    ⚠ MIÉRT API-BÓL, ÉS NEM KÉZZEL A @BotFather-BEN. A menüt egyszer beírni
    könnyű — szinkronban tartani nem. Ha a kódban új parancs születik vagy egy
    leírás változik, a kézzel beállított menü NÉMÁN elavul, és a felhasználó
    olyat kínál fel, ami nincs (vagy nem kínálja fel, ami van). Innen minden
    induláskor a KÓDBÓL frissül.

    `language_code`: üres → az alapértelmezett menü; `"hu"`/`"en"` → az adott
    Telegram-nyelvű felhasználóknak."""
    body = {"commands": [{"command": str(n)[:32].lower(),
                          "description": str(d)[:256]} for n, d in parancsok]}
    if language_code:
        body["language_code"] = str(language_code)
    ok, res = _hivas(token, "setMyCommands", body)
    if ok and isinstance(res, dict) and res.get("ok"):
        return True
    log.warning("telegram: a parancs-menü nem állt be (%s): %s",
                language_code or "alap", res)
    return False


def me(token: str) -> tuple:
    """`(sikerult, bot_neve_vagy_hiba)` — a token ELLENŐRZÉSE.

    ⚠ Ez az egyetlen olcsó módja megmondani, hogy egy elgépelt token miatt
    hallgat-e a bot. Enélkül a felhasználó csak annyit látna, hogy nem jön
    üzenet — és a kereskedésben keresné a hibát."""
    ok, res = _hivas(token, "getMe", {})
    if ok and isinstance(res, dict) and res.get("ok"):
        return True, str((res.get("result") or {}).get("username") or "?")
    return False, str(res)

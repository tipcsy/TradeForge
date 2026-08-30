"""Nyelvi katalógus — a felület szövegei a kódból leválasztva.

A program alapnyelve a MAGYAR; a katalógus `lang/hu.json`, a fordítások mellette
(`lang/en.json`, később `de`, `es`). A hívás mindenhol:

    from core.i18n import t as _t
    ...
    tk.Button(frm, text=_t("btn.save"))

⚠ AZ ALIAS NEM ÍZLÉS. A `t` egybetűs név a kódbázisban FOGLALT: a `gui.py`-ban
kilenc helyen lokális változó (`t = pos["type"]`, `for t in tickets` …), a
matek-modulokban a `tr` a true range. Egy ilyen lokális elfedné a fordítót, és a
hiba a widget megépítésekor jönne — `TypeError: 'dict' object is not callable`,
látszólag ok nélkül. Az `_t` alias illeszkedik a projekt meglévő szokásához
(`_theme`, `_quality`, `_gate_layout`), és nem ütközik semmivel.

⚠ MIÉRT NEM `gettext`. A `.po`/`.mo` páros fordítóirodákhoz való: bináris
formátum, külön fordítóeszköz, és a kulcs maga a magyar mondat — egy elgépelés
javítása MINDEN nyelvben elárvítja a fordítást. Itt a kulcs egy STABIL azonosító
(`live.btn.start`), a szöveg pedig adat. Egy új nyelv = egy új JSON, kód nem
változik. Ez a feltétele annak, hogy a németet/spanyolt ne fejlesztőnek kelljen
csinálnia.

⚠ A HIÁNYZÓ KULCS SOSEM ÜRES KÉPERNYŐ. A visszaesés sorrendje: aktív nyelv →
magyar → maga a kulcs. Egy félig lefordított katalógus így magyarul jelenik meg,
nem üres gombként — de a hiány NEM néma: kulcsonként egyszer naplózunk, és a
`tools/i18n_scan.py` tételesen kiírja. (A néma átmenés rosszabb a bukásnál: egy
üres gombfelirat pont azt rejtené el, hogy a fordítás hiányos.)

⚠ A NYELVVÁLTÁS ÚJRAINDÍTÁST IGÉNYEL — ugyanaz a szerkezeti határ, mint a
témánál: a tkinter widget a feliratát a KONSTRUKTORBAN kapja, tehát egy futás
közbeni váltáshoz a teljes felületet újra kellene építeni. A beállító ablak
ezért ki is írja. A `set_language()` a teszteké és az előnézeté.

⚠ A NYELV NEVE SOHA NEM FORDÍTANDÓ. A legördülőben „Magyar / English / Deutsch"
áll — a saját nyelvén mindenki felismeri a sajátját, akkor is, ha épp egy
számára olvashatatlan nyelvre kapcsolt valaki. Ezért van a `LANGUAGES` a kódban
és nem a katalógusban.
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)

# A program alapnyelve. Ez a katalógus a TELJES kulcskészlet forrása: a többi
# nyelvet ehhez méri a teszt és a scanner.
BASE_LANG = "hu"

# Támogatott nyelvek — a kód a kulcs, az érték a nyelv SAJÁT neve (lásd a fenti
# ⚠-t). Új nyelv bevezetése: egy sor ide + a `lang/<kód>.json`.
LANGUAGES: dict[str, str] = {
    "hu": "Magyar",
    "en": "English",
}

_catalogs: dict[str, dict] = {}
_active: str = ""
_missing: set[str] = set()


def _lang_dir():
    from version import BASE_DIR
    return BASE_DIR / "lang"


def _load(code: str) -> dict:
    """Egy katalógus beolvasása. Hibás/hiányzó fájl → üres szótár: a program
    NEM állhat meg egy fordítási fájl miatt, a visszaesés úgyis magyar."""
    if code in _catalogs:
        return _catalogs[code]
    data: dict = {}
    p = _lang_dir() / f"{code}.json"
    try:
        with open(p, encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            # A `_comment` kulcsok a fordítónak szólnak, nem szövegek.
            data = {k: v for k, v in raw.items()
                    if isinstance(v, str) and not k.startswith("_")}
    except FileNotFoundError:
        log.warning("i18n: nincs nyelvi fájl: %s", p)
    except Exception as ex:
        log.error("i18n: a nyelvi fájl nem olvasható (%s): %s", p, ex)
    _catalogs[code] = data
    return data


def _config_language() -> str:
    """A `config.json` → `dashboard.language`. Külön olvassuk (nem a
    `strategy.settings` loaderen át), mert ez a modul a felületnél KORÁBBAN
    töltődik be — ugyanaz a döntés, mint a `dashboard/theme.py`-ban, és így
    nincs körkörös import."""
    try:
        from version import BASE_DIR
        with open(BASE_DIR / "config.json", encoding="utf-8") as f:
            code = ((json.load(f).get("dashboard") or {}).get("language") or "")
        code = str(code).strip().lower()
        if code in LANGUAGES:
            return code
        if code:
            log.warning("i18n: ismeretlen nyelv a configban: %r — marad a %s",
                        code, BASE_LANG)
    except FileNotFoundError:
        pass
    except Exception as ex:
        log.debug("i18n: a nyelv nem olvasható a configból (%s)", ex)
    return BASE_LANG


def language() -> str:
    """Az aktív nyelv kódja."""
    global _active
    if not _active:
        _active = _config_language()
    return _active


def set_language(code: str) -> None:
    """Nyelvváltás FUTÁS KÖZBEN — a teszteké és az előnézeté.

    ⚠ A már megépült widgetek feliratát NEM írja át (lásd a modul fejlécét): a
    valódi váltás a configba mentés + újraindítás."""
    global _active
    code = str(code or "").strip().lower()
    _active = code if code in LANGUAGES else BASE_LANG


def t(key: str, **kw) -> str:
    """A `key` szövege az aktív nyelven, `{név}` helykitöltőkkel.

    A visszaesés: aktív nyelv → magyar → maga a kulcs. Hiányzó helykitöltő
    esetén a nyers szöveget adjuk vissza (a felirat legyen csúnya, de a felület
    NE dőljön el egy fordítási hibától)."""
    cur = language()
    s = _load(cur).get(key)
    if s is None and cur != BASE_LANG:
        s = _load(BASE_LANG).get(key)
        if s is not None and key not in _missing:
            _missing.add(key)
            log.warning("i18n: hiányzó kulcs a(z) '%s' katalógusban: %s", cur, key)
    if s is None:
        if key not in _missing:
            _missing.add(key)
            log.warning("i18n: ismeretlen kulcs: %s", key)
        return key
    if not kw:
        return s
    try:
        return s.format(**kw)
    except Exception as ex:
        log.error("i18n: helykitöltő-hiba (%s): %s", key, ex)
        return s


def has(key: str) -> bool:
    """Van-e ilyen kulcs (bármelyik katalógusban)? A kód-kulcs ↔ címke
    leképezéseknek kell, ahol a hiány csendes visszaesést jelentene."""
    return key in _load(language()) or key in _load(BASE_LANG)


def catalog(code: str = "") -> dict:
    """Egy teljes katalógus — a teszté és a scanneré."""
    return dict(_load(code or language()))


def missing_keys() -> list:
    """Amit futás közben nem találtunk. A felület „nyelvi állapot" kiírásához."""
    return sorted(_missing)


def reset_cache() -> None:
    """A betöltött katalógusok eldobása — a teszté (fájlt írt, újra akarja olvasni)."""
    _catalogs.clear()
    _missing.clear()

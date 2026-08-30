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


def t(key: str, /, **kw) -> str:
    """A `key` szövege az aktív nyelven, `{név}` helykitöltőkkel.

    A visszaesés: aktív nyelv → magyar → maga a kulcs. Hiányzó helykitöltő
    esetén a nyers szöveget adjuk vissza (a felirat legyen csúnya, de a felület
    NE dőljön el egy fordítási hibától).

    ⚠ A `/` NEM DÍSZ: a kulcs POZÍCIÓ SZERINTI paraméter. Enélkül egy `{key}`
    nevű helykitöltő ütközne a paraméter nevével — `TypeError: t() got multiple
    values for argument 'key'` —, és ez pontosan egy ilyen szövegnél sült el
    („1 hangolt paraméter → VÉGIGPRÓBÁLÁS: … ({key} minden értéke)"). A hiba nem
    a fordításban van, hanem abban, hogy a szöveg egy hétköznapi szót akar
    behelyettesíteni."""
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


class LabelMap(dict):
    """KÓD → felirat leképezés, ami az AKTÍV nyelvből szolgál ki.

        NAME = LabelMap("rr.name", CYCLE)      # NAME[PRESET_HALVING] → „Felező"

    ⚠ MIÉRT NEM EGY SIMA SZÓTÁR. A felület tucatnyi helyen így épít legördülőt:

        om = OptionMenu(row, var, *[NAME[p] for p in CYCLE])
        ...
        preset = {v: k for k, v in NAME.items()}.get(var.get())

    A visszafejtés tehát UGYANABBÓL a táblából készül, mint a feliratok — ez a
    minta nyelvfüggetlen, DE csak akkor, ha a tábla nem fagy be. Egy modul
    betöltésekor `_t()`-vel kiszámolt szótár a betöltéskori nyelvet őrizné meg:
    egy későbbi nyelvváltás után a legördülő az ÚJ, a visszafejtés a RÉGI
    feliratokat ismerné — és a `.get()` csendben `None`-t adna, azaz a
    beállítás némán nem történne meg.

    Az osztály minden szótár-műveletet (indexelés, `get`, `items`, `values`,
    bejárás) a hívás pillanatában old fel, tehát a kettő nem tud elcsúszni."""

    def __init__(self, prefix: str, codes):
        super().__init__()
        self._prefix = prefix
        self._codes = tuple(codes)

    def _label(self, code):
        return t(f"{self._prefix}.{code}") if code in self._codes else str(code)

    def __getitem__(self, k):
        if k not in self._codes:
            raise KeyError(k)
        return self._label(k)

    def __contains__(self, k):
        return k in self._codes

    def __iter__(self):
        return iter(self._codes)

    def __len__(self):
        return len(self._codes)

    def get(self, k, default=None):
        return self._label(k) if k in self._codes else default

    def keys(self):
        return list(self._codes)

    def values(self):
        return [self._label(c) for c in self._codes]

    def items(self):
        return [(c, self._label(c)) for c in self._codes]

    def code_of(self, label: str, default=None):
        """Felirat → kód. A visszafejtés OLVASHATÓ alakja (a hívók eddig egy
        `{v: k for ...}` szótár-fordítást írtak le minden alkalommal)."""
        for c in self._codes:
            if self._label(c) == label:
                return c
        return default


def num(s: str) -> str:
    """ANGOL alakban megformázott szám → az aktív nyelv írásmódja.

    Bemenet az, amit a Python ad (`f"{v:,.2f}"` → `1,234.50`), kimenet a nyelv
    szerinti (`1 234,50` magyarul). Két kulcs vezérli: `number.group` és
    `number.decimal`.

    ⚠ MIÉRT KELL KÖZÖS HELYRE. Ez eddig tucatnyi ponton így nézett ki:
    `.replace(",", NBSP).replace(".", ",")` — vagyis a MAGYAR írásmód be volt
    drótozva a kijelzésbe. Angol felületen `1 234,50` jelent volna meg: nem hiba,
    nem is olvashatatlan, csak épp következetesen rossz, és tizenkét helyen
    kellett volna észrevenni."""
    grp = _load(language()).get("number.group",
                                _load(BASE_LANG).get("number.group", " "))
    dec = _load(language()).get("number.decimal",
                                _load(BASE_LANG).get("number.decimal", ","))
    # ⚠ Két lépésben, jelölőn át: egy naiv `replace(",", grp)` után a
    # `replace(".", dec)` visszahozhatná a vesszőt, és `1,234,50` lenne belőle.
    return s.replace(",", "\x00").replace(".", dec).replace("\x00", grp)


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

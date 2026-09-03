"""
SÁVOS KAPU-HATÁS — „mikor mi történjen", nem csak „mi történjen".

⚠ A KÉRÉS (2026-09-02): „És itt elvárnám azt is, hogy amelyiknél vannak sávok
szintek, ott hogyan valósuljon meg. Pl.: 10%-nál semmi, 40%-nál kockázatcsökkent,
50%-nál akadályozza a beszállást." — és a megvalósításra: „Lehet, hogy ezt is
felületvezérelten lehetne használni? (Azaz + gomb; felvesz egy új határt…) …aztán
ha nem tetszik, akkor egyszerűen letörölni az adott sávot."

Eddig egy kapunak EGY hatása volt: ha a mérés a küszöbön kívül esett, az történt
(blokkol / kockázatcsökkentés / ki). Ez bináris. A valóság nem az: egy 1,05×-ös
spread nem ugyanaz, mint egy 3×-os, mégis mindkettő ugyanazt váltotta ki.

── A MODELL: LÉTRA ────────────────────────────────────────────────────────
Egy kapu hatása egy LÉTRA: `[(határ, hatás), …]`. A mért érték megkeresi a
legmagasabb határt, amit már elért; annak a hatása érvényes. Ami az első határ
alatt van, azt a kapu nem bántja.

    [(80, "reduce"), (100, "block")]
      < 80%  → semmi
     80-99%  → kockázatcsökkentés
      ≥ 100% → blokkol

⚠ A LÉTRA HIÁNYA IS LÉTRA. Ha nincs sáv beállítva, a viselkedés pontosan a mai:
egyetlen implicit sáv a kapu SAJÁT küszöbén (`[(100, a beállított hatás)]`). Ezért
nem kell külön „sávos mód" kapcsoló, és ezért nem változik semmi attól, hogy ez a
modul létezik — a régi configok bitazonosan viselkednek.

── HÁROM MÉRŐSZÁM-FAJTA, MERT HÁROMFÉLE KAPUNK VAN ───────────────────────
A felhasználó döntése (2026-09-03): „skalár sáv, TF darabszám, piac kategória".

* **SKALÁR** (spread · költség · lendület · volatilitás) — a határ a kapu SAJÁT
  küszöbének SZÁZALÉKA. 100% = pontosan az a határ, ahol a kapu ma bukik. Miért
  nem a nyers mértékegység: egy „18 pont" spread-határ instrumentumonként mást
  jelent, a százalék viszont hordozható, tehát ÖRÖKÖLHETŐ (globális → pár →
  pár+stratégia). A felület a nyers értéket is kiírja a sáv mellé.
* **DARABSZÁM** (idősík-együttállás) — a határ az EGYÜTTÁLLÓ idősíkok száma, és
  itt a KEVESEBB a rosszabb. A létra ezért csökkenő: `[(2, "reduce"), (1, "block")]`
  = „legfeljebb 2 idősík áll együtt → csökkent; legfeljebb 1 → blokkol".
* **KATEGÓRIA** (piac-állapot) — nincs mit sorba rendezni: besorolásonként egy
  hatás. `{"dead": "block", "ranging": "reduce"}`.

── AMIT EZ A MODUL NEM CSINÁL ────────────────────────────────────────────
Nem mér. A mért értéket (szint / darabszám / kategória) a hívó adja — ugyanaz a
szétválasztás, mint a `gates.decide`-nál, és ugyanazért: a mérés ott van, ahol az
irány és a friss adat, a DÖNTÉS pedig egy helyen.

TISZTA modul: se tkinter, se MT5, se fájl.
"""

from __future__ import annotations

from core import gates as _g

# ── A mérőszám fajtája kapunként ─────────────────────────────────────────
SCALAR = "scalar"
COUNT = "count"
CATEGORY = "category"

KIND = {
    _g.SPREAD: SCALAR,
    _g.COST: SCALAR,
    _g.MOMENTUM: SCALAR,
    _g.VOLATILITY: SCALAR,
    _g.TF_ALIGN: COUNT,
    _g.MARKET: CATEGORY,
}

# A skalár kapuk határa SZÁZALÉK; 100 = a kapu saját küszöbe.
FULL = 100.0

# Ennél több sáv már nem beállítás, hanem programozás — és a felületen sem fér
# el olvashatóan. A korlát KIMONDOTT, nem néma csonkítás: a `validate` szól.
MAX_BANDS = 6
MAX_LEVEL = 1000.0        # 10× a kapu küszöbe — efölött a sáv sosem aktiválódna
MAX_COUNT = 8             # ennyi idősíkot figyelhet a TF-kapu (a spec 2..6)


def kind_of(key: str) -> str:
    """Milyen fajta mérőszáma van ennek a kapunak? (`""` ismeretlen kapura.)"""
    return KIND.get(key, "")


# ---------------------------------------------------------------------------
# A LÉTRA feloldása configból — ugyanaz az öröklődés, mint a hatásé
# ---------------------------------------------------------------------------
# ⚠ A KÉRÉS (2/c): „Szerintem úgy gondolj rá, ahogy az öröklődést is megcsináltuk.
# Ahol valami nincs beállítva, az örököl." Ezért BETŰRE ugyanaz a lánc, amit a
# `gates.effect_with_source` jár be — nem egy hasonló, hanem ugyanaz a sorrend:
#
#     pairs.<SYM>.gates.<kapu>.<stratégia>
#     pairs.<SYM>.gates.<kapu>.default
#     gates.<kapu>.<stratégia>
#     gates.<kapu>.default
#     → nincs létra (a kapu egyetlen küszöbe dönt, mint eddig)
#
# ⚠ EGY SZINT AKKOR „DÖNT", HA VAN BENNE `bands` KULCS. Egy sima `"block"`
# bejegyzés a hatást mondja meg, nem a létrát — afölött tehát tovább öröklünk.
# Az örökölt létra KIKAPCSOLÁSA ezen a szinten: `"bands": []` (üres lista).
# Enélkül nem lenne mód azt mondani, hogy „ezen a páron NE legyen sáv".


def _bands_of(entry):
    """Egy config-bejegyzés létrája, vagy `None`, ha nem dönt róla."""
    if isinstance(entry, dict) and "bands" in entry:
        return _clean(entry.get("bands"), None)
    return None


def _clean(raw, kind):
    """A nyers configból olvasott létra rendezett, érvényes alakja."""
    if isinstance(raw, dict):                       # KATEGÓRIA
        return {str(k): v for k, v in raw.items() if v in _g.EFFECTS}
    out = []
    for item in (raw or []):
        try:
            lim, eff = (item[0], item[1]) if not isinstance(item, dict) else \
                       (item.get("from"), item.get("effect"))
            if eff not in _g.EFFECTS:
                continue
            out.append((float(lim), str(eff)))
        except (TypeError, ValueError, IndexError, KeyError):
            continue
    return out


def ladder_with_source(cfg: dict, symbol: str, strategy: str, key: str) -> tuple:
    """`(létra, forrás)` — a lánc melyik szintje döntött.

    A `forrás` a `gates.SRC_*` kódok egyike; `SRC_BUILTIN`, ha sehol nincs sáv
    (ilyenkor a létra üres, és a kapu egyetlen küszöbe dönt, mint eddig)."""
    cfg = cfg or {}
    pair_gates = ((cfg.get("pairs") or {}).get(symbol) or {}).get("gates")
    for section, s_own, s_def in (
            ((pair_gates or {}).get(key), _g.SRC_PAIR, _g.SRC_PAIR_DEFAULT),
            (((cfg.get("gates") or {}).get(key)), _g.SRC_GLOBAL,
             _g.SRC_GLOBAL_DEFAULT)):
        if isinstance(section, dict):
            for name, src in ((strategy, s_own), ("default", s_def)):
                if not name:
                    continue
                b = _bands_of(section.get(name))
                if b is not None:
                    return b, src
    return ([] if kind_of(key) != CATEGORY else {}), _g.SRC_BUILTIN


def ladder(cfg: dict, symbol: str, strategy: str, key: str):
    return ladder_with_source(cfg, symbol, strategy, key)[0]


def ladders_for(cfg: dict, symbol: str, strategy: str) -> dict:
    """`{kapu: létra}` egy (pár, stratégia) párosra — EGYSZER feloldva.

    ⚠ A motor ezt a KÖRÖN KÍVÜL hívja (mint a `gates.effects_for`-t): a
    backtest belépő-ága bárokon fut, és egy per-bár config-bejárás ott ötszámjegyű
    szorzót jelentene. A létra nem függ a bártól, tehát nincs is miért újraolvasni."""
    return {k: ladder(cfg, symbol, strategy, k) for k in _g.KEYS}


def inherited_ladder(cfg: dict, symbol: str, strategy: str, key: str) -> tuple:
    """`(létra, forrás)` ÚGY, MINTHA a pár-szintű felülírás nem létezne — a
    felület ezt ajánlja fel „Örökölt" néven (ugyanaz a minta, mint a hatásnál)."""
    cfg = dict(cfg or {})
    pairs = dict(cfg.get("pairs") or {})
    pc = dict(pairs.get(symbol) or {})
    pc.pop("gates", None)
    pairs[symbol] = pc
    cfg["pairs"] = pairs
    return ladder_with_source(cfg, symbol, strategy, key)


# ---------------------------------------------------------------------------
# A DÖNTÉS: mért érték → hatás
# ---------------------------------------------------------------------------

def effect_at(key: str, bands, base_effect: str, measured, failed=None) -> str:
    """Milyen hatás érvényes EZEN a mérésen?

    `bands`: a `ladder()` eredménye.
    `base_effect`: a kapu beállított hatása (`gates.effect_for`).
    `measured`: SKALÁR-nál a szint %-ban (`scalar_level` / `two_sided_level` /
        `inverse_level`), DARABSZÁM-nál az együttálló idősíkok száma,
        KATEGÓRIÁ-nál a besorolás kulcsa.
    `failed`: a kapu SAJÁT, mai ítélete (bool) — a létra nélküli út ezt használja.

    ⚠ LÉTRA NÉLKÜL A `failed` DÖNT, NEM A SZINT. Ez nem kényelmi döntés: a szint
    egy osztás eredménye, a `failed` pedig a kapu eredeti, szigorú (`<`, nem
    `<=`) összehasonlítása. A kettő a HATÁRON eltérhet egy epszilonnal — mérve a
    volatilitásnál: ATR = padló pontosan → szint 100,0%, `failed` False. Ha itt a
    szintet néznénk, a sáv nélküli (tehát a MAI) viselkedés egy hajszálnyit
    megváltozna, némán, minden páron. A létra CSAK akkor vesz át, ha tényleg
    beállítottak sávot.

    `EFFECT_NONE` alap-hatás → a létra sem szólhat bele: egy kikapcsolt kapunak
    nincs sávja. (Enélkül egy örökölt létra visszakapcsolhatna egy szándékosan
    kikapcsolt kaput — némán.)
    """
    if base_effect == _g.EFFECT_NONE:
        return _g.EFFECT_NONE
    kind = kind_of(key)
    if not bands:
        return base_effect if failed else _g.EFFECT_NONE
    if measured is None:
        # Van létra, de nincs mérés → a régi ítéletre esünk vissza (fail-open
        # ugyanúgy, ahogy a kapuk adathiánynál mindenütt).
        return base_effect if failed else _g.EFFECT_NONE
    if kind == CATEGORY:
        return bands.get(str(measured), _g.EFFECT_NONE)
    try:
        val = float(measured)
    except (TypeError, ValueError):
        return base_effect if failed else _g.EFFECT_NONE
    if kind == COUNT:
        # KEVESEBB a rosszabb: a legszigorúbb (legkisebb) sáv nyer, amit a mért
        # darabszám még nem halad meg.
        hit = _g.EFFECT_NONE
        for lim, eff in sorted(bands, key=lambda b: -b[0]):
            if val <= lim:
                hit = eff
        return hit
    # SKALÁR: TÖBB a rosszabb — a legmagasabb elért határ nyer.
    hit = _g.EFFECT_NONE
    for lim, eff in sorted(bands, key=lambda b: b[0]):
        if val >= lim:
            hit = eff
    return hit


def momentum_level(value, signal: str, mode: str, params: dict = None) -> float:
    """A lendület-kapu szintje. KÉT bukási módja van, és a sáv EGYET tud olvasni:

    * **alapjárat** — folytonos: `küszöb / |fordulat|`, 100% a küszöbön;
    * **irány** — bináris (a fordulat szembemegy a jellel). Ez nem skálázható,
      ezért a szintje 100%: ugyanoda esik, ahol a kapu enélkül is bukna. Így egy
      sávos beállítás SOSEM gyengíti az irány-szűrőt — az a hiba, amit egy
      félkész sávozás könnyen okozna (a `dir` némán hatástalanná válna).

    A kettő közül a ROSSZABB (nagyobb) szint érvényes."""
    from core import momentum as _m
    lvl = 0.0
    p = {**_m.DEFAULTS, **(params or {})}
    if mode in ("idle", "both"):
        v = inverse_level(value, p.get("idle_threshold"))
        if v is not None:
            lvl = max(lvl, v)
    if mode in ("dir", "both"):
        d = _m.direction(value)
        if d and signal in ("BUY", "SELL") and d != signal:
            lvl = max(lvl, FULL)
    return lvl


def effects_at(base_effects: dict, ladders: dict, failed: dict,
               levels: dict = None) -> dict:
    """`{kapu: hatás}` a MOSTANI mérésre — a létrák feloldásával.

    A motor bemenete. A `failed` kulcsai mondják meg, MELY kapukat mérte a hívó;
    a többi kapu a beállított hatását tartja (de mivel nem bukott, nem is szól bele).
    """
    out = dict(base_effects or {})
    for k in (failed or {}):
        out[k] = effect_at(k, (ladders or {}).get(k),
                           (base_effects or {}).get(k) or _g.default_effect_of(k),
                           (levels or {}).get(k), (failed or {}).get(k))
    return out


def failed_at(effects_now: dict, failed: dict) -> dict:
    """`{kapu: bukott-e}` a `gates.decide` számára.

    ⚠ NEM a nyers `failed`-et adjuk tovább: sávos létránál a kapu a SAJÁT
    küszöbét még nem érte el (`failed=False`), a létra viszont már előír egy
    hatást (pl. 85%-nál kockázatcsökkentést). A `decide` bemenete ezért az, hogy
    a MOSTANI hatás nem `none` — különben a sávok némán hatástalanok lennének."""
    return {k: ((effects_now or {}).get(k) or _g.EFFECT_NONE) != _g.EFFECT_NONE
            for k in (failed or {})}


def scalar_level(measured, threshold) -> float:
    """A skalár kapuk KÖZÖS normalizálása: `mért / küszöb × 100`.

    100 = pontosan a kapu saját határa. `None`, ha nincs értelmes küszöb — a
    hívó ilyenkor a régi bool-mérésére támaszkodik (fail-open, mint eddig)."""
    try:
        m, t = float(measured), float(threshold)
    except (TypeError, ValueError):
        return None
    if not (t > 0) or m != m or t != t:
        return None
    return m / t * FULL


def inverse_level(measured, threshold) -> float:
    """Ugyanaz, ha a KEVESEBB a rosszabb (lendület-alapjárat): `küszöb / mért`.

    A lendületnél a kapu akkor bukik, ha a fordulat a küszöb ALÁ esik; a szint
    így ugyanúgy 100-nál éri el a határt, és a létra egy irányban olvasható."""
    try:
        m, t = abs(float(measured)), float(threshold)
    except (TypeError, ValueError):
        return None
    if not (t > 0) or m != m:
        return None
    if m <= 0:
        return MAX_LEVEL            # teljesen áll → a legrosszabb szint
    return min(MAX_LEVEL, t / m * FULL)


def two_sided_level(measured, lo, hi) -> float:
    """KÉTOLDALÚ kapu szintje (volatilitás): a padló ÉS a plafon közül a
    szorosabb oldal dönt.

    A padló felől `padló / mért`, a plafon felől `mért / plafon` — mindkettő
    100-at ad pontosan a határon, tehát a létra EGY irányban olvasható akkor is,
    ha a kapu kétféleképpen bukhat („túl csendes" / „túl kaotikus")."""
    try:
        m = float(measured)
    except (TypeError, ValueError):
        return None
    if not (m > 0) or m != m:
        return None
    lvl = 0.0
    try:
        if lo and float(lo) > 0:
            lvl = max(lvl, min(MAX_LEVEL, float(lo) / m * FULL))
    except (TypeError, ValueError):
        pass
    try:
        if hi and float(hi) > 0:
            lvl = max(lvl, m / float(hi) * FULL)
    except (TypeError, ValueError):
        pass
    return lvl


def level_volatility(atr, params: dict, base) -> float:
    """A volatilitás-kapu szintje a KÖZÖS mércéből (`core.vol_baseline`).

    ⚠ UGYANAZ a sáv, amiből a `vol_baseline.failed` is dolgozik — egy forrás,
    hogy a szint és az ítélet ne csúszhasson szét. 100% pontosan ott van, ahol a
    `failed` True-ra vált."""
    from core import vol_baseline as _vb
    b = _vb.effective(params or {}, base)
    if not b or b <= 0:
        return None
    lo, hi = _vb.band(params or {}, b)
    return two_sided_level(atr, lo, hi)


# ---------------------------------------------------------------------------
# Ellenőrzés és mentés
# ---------------------------------------------------------------------------

def validate(key: str, bands) -> list:
    """Hibaüzenetek listája (üres = rendben).

    ⚠ A RÉSZLEGES MENTÉS TILOS (a projekt szabálya): a hívó csak akkor ment, ha
    ez üres. Egy fél létra rosszabb, mint semmi — csendben mást csinálna."""
    from core.i18n import t as _t
    out = []
    kind = kind_of(key)
    if kind == CATEGORY:
        if not isinstance(bands, dict):
            return [_t("gb.err.shape")]
        for k, v in bands.items():
            if v not in _g.EFFECTS:
                out.append(_t("gb.err.effect", value=str(v)))
        return out
    if not isinstance(bands, (list, tuple)):
        return [_t("gb.err.shape")]
    if len(bands) > MAX_BANDS:
        out.append(_t("gb.err.too_many", n=len(bands), max=MAX_BANDS))
    seen = set()
    for item in bands:
        try:
            lim, eff = float(item[0]), item[1]
        except (TypeError, ValueError, IndexError):
            out.append(_t("gb.err.shape"))
            continue
        if eff not in _g.EFFECTS:
            out.append(_t("gb.err.effect", value=str(eff)))
        if lim in seen:
            out.append(_t("gb.err.duplicate", value=_fmt(lim)))
        seen.add(lim)
        if kind == COUNT:
            if not (0 <= lim <= MAX_COUNT) or lim != int(lim):
                out.append(_t("gb.err.count", value=_fmt(lim), max=MAX_COUNT))
        elif not (0 < lim <= MAX_LEVEL):
            out.append(_t("gb.err.level", value=_fmt(lim), max=_fmt(MAX_LEVEL)))
    return out


def _fmt(v) -> str:
    return f"{float(v):g}"


def normalize(key: str, bands):
    """A mentés előtti alak: rendezve, duplikátum nélkül.

    SKALÁR növekvő, DARABSZÁM csökkenő — hogy a config OLVASVA is a létra
    sorrendjét mutassa, ne egy véletlen beviteli sorrendet."""
    if kind_of(key) == CATEGORY:
        return {str(k): v for k, v in (bands or {}).items() if v in _g.EFFECTS}
    clean, seen = [], set()
    for item in (bands or []):
        lim, eff = float(item[0]), item[1]
        if lim in seen or eff not in _g.EFFECTS:
            continue
        seen.add(lim)
        clean.append([lim, eff])
    clean.sort(key=lambda b: b[0], reverse=(kind_of(key) == COUNT))
    return clean


def set_ladder(cfg: dict, symbol: str, strategy: str, key: str, bands) -> dict:
    """A létra mentése `pairs.<SYM>.gates.<kapu>.<stratégia>.bands`-be.

    ⚠ A CONFIG CSAK AZ ELTÉRÉST RÖGZÍTI. `bands=None` → a bejegyzés TÖRLŐDIK,
    tehát a pár visszatér az öröklésre. Üres lista (`[]`) viszont ÉRTELMES
    beállítás: „ezen a páron NE legyen sáv", és el is mentődik — különben nem
    lehetne kikapcsolni egy globális létrát.

    A `cfg`-t helyben módosítja, és vissza is adja."""
    cfg = cfg if cfg is not None else {}
    pc = cfg.setdefault("pairs", {}).setdefault(symbol, {})
    gates = pc.setdefault("gates", {})
    gg = gates.setdefault(key, {})
    entry = gg.get(strategy)
    entry = dict(entry) if isinstance(entry, dict) else (
        {"effect": entry} if entry in _g.EFFECTS else {})
    if bands is None:
        entry.pop("bands", None)
    else:
        entry["bands"] = normalize(key, bands)
    if entry:
        gg[strategy] = entry
    else:
        gg.pop(strategy, None)
    if not gg:
        gates.pop(key, None)
    if not gates:
        pc.pop("gates", None)
    return cfg


def describe(key: str, bands, base_effect: str) -> list:
    """`[(határ_szöveg, hatás_kulcs), …]` — a felület és a napló közös alakja.

    Létra nélkül is ad EGY sort (az implicit sávot), hogy a felület ne üres
    listát mutasson ott, ahol valójában történik valami."""
    kind = kind_of(key)
    if kind == CATEGORY:
        return [(str(k), v) for k, v in sorted((bands or {}).items())]
    if not bands:
        if base_effect == _g.EFFECT_NONE:
            return []
        return [("100%" if kind == SCALAR else "0", base_effect)]
    if kind == COUNT:
        return [(f"{int(l)}", e) for l, e in sorted(bands, key=lambda b: -b[0])]
    return [(f"{_fmt(l)}%", e) for l, e in sorted(bands, key=lambda b: b[0])]

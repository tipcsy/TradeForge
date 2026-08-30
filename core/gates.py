"""
Belépő-kapuk EGYSÉGES nyilvántartása — per (instrumentum × stratégia).

A dashboard három előszűrőt mutat: Spread · Idősík-együttállás · Piac-állapot.
Ez a modul egy helyre hozza a kiértékelésüket, és — a 2.0 terv 6. pontja szerint —
minden kapu **hatása stratégiánként állítható**:

    wpr_sma → Együtt → akadályozza a beszállást
    wpr_sma → Piac   → kockázatcsökkentés

**TISZTA modul**: se MT5, se tkinter, se fájl. A MÉRT értékeket (spread, ATR,
idősík-előjelek, piac-állapot) a hívó adja át egy `ctx` szótárban — így a döntés
egy sorban tesztelhető, és ugyanaz a kód szolgálja ki a dashboardot, a chart-sávot
és a későbbi szűrő-keretrendszert.

HATÓKÖRÖK (2026-07-31 állapot, v1.80.0 után):
  • **Spread** — a küszöb a KÖZÖS execution configból jön
    (`core/execution_params.py`: `max_spread_atr_ratio`, `min_spread_mult`),
    tehát egy instrumentumon MINDEN stratégiára ugyanaz. (v1.80.0 előtt ez még
    per stratégia volt.) A *hatása* viszont továbbra is stratégiánként állítható.
  • **Idősík-együttállás** — a mért állapot instrumentum-tulajdonság (az
    SMA-irányok), a KAPUZÁS viszont per stratégia (`tf_align.gate`).
  • **Piac-állapot** — instrumentum-szintű (`pairs.<sym>.market_strategy`).

Ebből következik a 2.0 elrendezése: a kapu-oszlopok az instrumentum szintjén
mondják meg, hogy „mi a helyzet", és a stratégia jelzés-cellájának KERETE mondja
meg, hogy „engem ez blokkol-e".
"""

from __future__ import annotations

from core.i18n import LabelMap as _LabelMap, t as _t

# ── Egy kapu ÁLLAPOTA (mért) ─────────────────────────────────────────────
PASS = "pass"          # be van kapcsolva és épp ÁTENGED
BLOCKING = "blocking"  # be van kapcsolva és épp BLOKKOL
OFF = "off"            # nincs bekapcsolva erre a (pár, stratégia) párosra
UNKNOWN = "unknown"    # nincs elég mért adat a döntéshez (pl. még nincs tick)

# ── Egy kapu HATÁSA (konfigurált) — zárt, kicsi halmaz ───────────────────
# A halmaz szándékosan kicsi: a motornak MINDEGYIKET implementálnia kell.
EFFECT_BLOCK = "block"    # nincs belépő (a mai tf_align.gate viselkedése)
EFFECT_REDUCE = "reduce"  # belép, de kisebb mérettel / kikényszerített preseten
EFFECT_NONE = "none"      # a kapu nem szól bele

EFFECTS = (EFFECT_BLOCK, EFFECT_REDUCE, EFFECT_NONE)

# A feliratok a beállító felülethez. ⚠ LabelMap: a legördülő ÉS a
# visszafejtése ugyanebből épül (lásd `core.i18n.LabelMap`).
EFFECT_LABEL = _LabelMap("gate.effect", EFFECTS)

# FONTOS: a „csak jelzés" NEM kapu-hatás. Az azt jelenti, hogy jelzést küldünk az
# MT5-nek kötés helyett — ez a STRATÉGIA kiváltsága (`core.trade_mode`), nem a
# kapué. A kapu ne küldjön jelzést.

SPREAD = "spread"
TF_ALIGN = "tf_align"
MARKET = "market"
MOMENTUM = "momentum"
COST = "cost"
VOLATILITY = "volatility"

# ── A LENDÜLET-kapu MÓDJA: MIT figyeljen ───────────────────────────────────
# A többi kapunál egyértelmű, mi a „bukás" (túl tág spread, nincs együttállás,
# kedvezőtlen besorolás). A lendület viszont KÉTFÉLEKÉPPEN mondhat nemet, és a
# kettő teljesen más kereskedési döntés — ezért választható, stratégiánként:
#
#   idle  „alapjárat": a piac áll (|fordulat| < küszöb) → ne kössünk bele
#   dir   „irány": a fordulat SZEMBEN megy a jellel → ne kössünk ellene
#   both  mindkettő
#
# A `mode` a HATÁSTÓL (block/reduce/none) FÜGGETLEN: a mód azt mondja meg, MIKOR
# bukik a kapu, a hatás azt, hogy AKKOR mi történjék.
MOM_IDLE = "idle"
MOM_DIR = "dir"
MOM_BOTH = "both"
MOM_MODES = (MOM_IDLE, MOM_DIR, MOM_BOTH)
MOM_MODE_LABEL = _LabelMap("gate.mom", MOM_MODES)
MOM_MODE_DEFAULT = MOM_IDLE

# ── A `reduce` hatás KONKRÉT jelentése a motorban (v1.97.0) ─────────────────
# „Belép, de kisebb mérettel." A méret-csökkentés ugyanaz a mechanizmus, amit a
# Risky preset `cautious` kapcsolója is használ (`account_risk_pct × faktor`) —
# szándékosan NEM új út: egy helyen dől el, mit jelent az „óvatosabb belépő".
REDUCE_RISK_FACTOR = 0.5

# ── A PIAC-kapu: mely besorolás számít KEDVEZŐTLENNEK ──────────────────────
# Ez KERESKEDÉSI döntés, ezért configból állítható (`gates.market.adverse`, ill.
# `pairs.<SYM>.gates.market.adverse`). Az alapértelmezés a két olyan kategória,
# amit a dashboard is „rossznak" színez: Érdektelen (dead) és Bizonytalan
# (uncertain). A kapu HATÁSA alapból `none`, tehát ez a lista addig nem számít,
# amíg a piac-kaput be nem kapcsolod.
MARKET_ADVERSE_DEFAULT = ("dead", "uncertain")


def market_adverse(cfg: dict, symbol: str) -> set:
    """Mely piac-besorolásoknál „bukik" a piac-kapu ezen a páron."""
    for section in (((cfg or {}).get("pairs") or {}).get(symbol) or {},
                    (cfg or {})):
        g = (section.get("gates") or {}).get(MARKET)
        if isinstance(g, dict) and isinstance(g.get("adverse"), (list, tuple)):
            return {str(x) for x in g["adverse"]}
    return set(MARKET_ADVERSE_DEFAULT)

# A kapuk SORRENDJE stabil: a kapu-blokk oszlopai így mindig ugyanott vannak.
# A `default_effect` a beépített alapértelmezés, ha a config nem mond mást — a mai
# viselkedést tükrözi (spread blokkol; a tf_align a `gate` lista szerint; a piac
# ma nem blokkol, csak a preset-választáshoz ad bemenetet).
REGISTRY = (
    {"key": SPREAD,   "default_effect": EFFECT_BLOCK},
    {"key": TF_ALIGN, "default_effect": EFFECT_NONE},
    {"key": MARKET,   "default_effect": EFFECT_NONE},
    # ÚJ kapu alapból NEM szól bele (`none`): egy frissítés SOHA ne kezdjen el
    # némán másképp kereskedni, mint amit tegnap tesztelted. Bekapcsolni a
    # kapu ablakában, stratégiánként kell.
    {"key": MOMENTUM, "default_effect": EFFECT_NONE},
    # Költség/kockázat: a spread mennyire torzítja a TERVEZETT RR-t. Alapból
    # `none` — a meglévő párok viselkedése nem változhat egy frissítéstől.
    {"key": COST,     "default_effect": EFFECT_NONE},
    # ⚠ CSAK KIJELZÉS. A volatilitás-szűrés NEM itt történik, hanem a stratégia
    # `bt_entry` hookjában (atr_min_pct/atr_max_pct) — ott van a backtest, a viz
    # és az él KÖZÖS belépő-kapuja. Ha ez a kapu is kapna állítható hatást, az
    # vagy DUPLÁN szűrne, vagy — `none`-ra állítva — azt ígérné, hogy kikapcsolta
    # a szűrést, holott a stratégia tovább szűrne. Az oszlop tehát MUTAT, nem dönt.
    #
    # Miért kell mégis oszlop: 2026-08-08-ig ez volt az EGYETLEN blokkoló ok, ami
    # nem látszott sehol. A BTCUSD hetekig némán nem kereskedett, mert az ATR a
    # kalibrált sáv alá csúszott (0,51×) — a chart üres maradt, és semmi nem
    # árulta el, miért. Minden más ok (spread, együttállás, piac, lendület,
    # költség) látható kapu volt; ez az aszimmetria került a felhasználónak hetekbe.
    {"key": VOLATILITY, "default_effect": EFFECT_NONE,
     "display_only": True},
)

KEYS = tuple(g["key"] for g in REGISTRY)


def is_display_only(key: str) -> bool:
    """CSAK KIJELZÉS kapu-e? Ilyennek NINCS állítható hatása: a szűrés
    máshol (a stratégiában) történik, az oszlop csak láthatóvá teszi."""
    for g in REGISTRY:
        if g["key"] == key:
            return bool(g.get("display_only"))
    return False


def doc_path(key: str):
    """A kapu leírásának útvonala: `core/docs/<kulcs>.md`.

    Ugyanaz a minta, mint a stratégiáknál (`strategy/docs/<név>.md`): a leírás
    FÁJLBAN él, nem a kódban — szerkeszthető anélkül, hogy hozzányúlnál a
    logikához, és a beállító ablak „Leírás" lapja mindig a lemezről olvassa.

    ⚠ NYELVFÜGGŐ: angol felületen `<kulcs>.en.md`, ha létezik — különben a
    magyar eredeti."""
    from pathlib import Path as _P
    from core.i18n import doc_path as _doc_path
    return _doc_path(_P(__file__).resolve().parent / "docs", key)


def doc_text(key: str) -> str:
    """A kapu leírása. Ha a fájl nincs, az ELVÁRT útvonalat adja vissza — így a
    hiányzó doksi nem üres lap, hanem felszólítás."""
    p = doc_path(key)
    try:
        from core.i18n import doc_note as _doc_note
        return _doc_note(p.parent, key) + p.read_text(encoding="utf-8")
    except OSError:
        _lines = ["# " + label_of(key), "",
                  _t("gate.no_doc"), "",
                  _t("gate.doc.expected_file"), "", "```", str(p), "```"]
        return chr(10).join(_lines) + chr(10)


def label_of(key: str) -> str:
    """A kapu felirata az aktív nyelven. ⚠ A REGISTRY-ben már NINCS `label`:
    a szöveg a katalógusban él (`gate.name.<kulcs>`), a REGISTRY a viselkedést
    írja le. Így egy új nyelv nem nyúl a kapu-definícióhoz."""
    return _t(f"gate.name.{key}") if key in KEYS else key


def default_effect_of(key: str) -> str:
    for g in REGISTRY:
        if g["key"] == key:
            return g["default_effect"]
    return EFFECT_NONE


# ---------------------------------------------------------------------------
# A HATÁS feloldása configból — örökléssel
# ---------------------------------------------------------------------------
# 3 kapu × 2 stratégia × 10 pár = 60 beállítás. Öröklés nélkül ez kitöltetlenül is
# átláthatatlan lenne, ezért ugyanazt a láncot használjuk, ami a `tf_align`-nál és
# a `core/execution_params.py`-nál is bevált:
#
#     pairs.<SYM>.gates.<kapu>.<stratégia>      ← a legszűkebb nyer
#     pairs.<SYM>.gates.<kapu>.default
#     gates.<kapu>.<stratégia>
#     gates.<kapu>.default
#     REGISTRY default_effect                   ← beépített
#
# Így a 60-ból a gyakorlatban 3-6 lesz ténylegesen kitöltve.

def _as_effect(v):
    """Egy bejegyzés HATÁSA. Két alak él egymás mellett:

        "block"                          — a régi, egyszerű alak
        {"effect": "block", "mode": …}   — ha a kapunak MÓDJA is van (Lendület)

    A szótáras alak azért kellett, mert a lendület kétféleképpen bukhat
    (alapjárat / irány), és a kettő stratégiánként külön választható. A régi
    alak változatlanul érvényes — a meglévő configok nem nyúlnak."""
    if v in EFFECTS:
        return v
    if isinstance(v, dict) and v.get("effect") in EFFECTS:
        return v["effect"]
    return None


def _effect_from(section: dict, key: str, strategy: str):
    g = (section or {}).get(key)
    if not isinstance(g, dict):
        return None
    for k in (strategy, "default"):
        if k:
            e = _as_effect(g.get(k))
            if e is not None:
                return e
    return None


def _legacy_tf_align_effect(cfg: dict, symbol: str, strategy: str):
    """Visszafelé kompatibilitás: a mai `tf_align.gate` egy LISTA (`["wpr_sma"]`),
    ami szó szerint azt jelenti, hogy „ezeket a stratégiákat blokkolja".

    Ha még nincs `gates` config, ebből olvassuk a hatást — így a meglévő
    beállítások változtatás nélkül tovább élnek. Per-pár felülírás elsőbbséget
    élvez a globális fölött (ugyanaz a szabály, mint a `tf_align` többi mezőjénél)."""
    pair_ta = ((cfg.get("pairs") or {}).get(symbol) or {}).get("tf_align")
    glob_ta = cfg.get("tf_align") or {}
    for ta in (pair_ta, glob_ta):
        if isinstance(ta, dict) and "gate" in ta:
            return EFFECT_BLOCK if strategy in (ta.get("gate") or []) else EFFECT_NONE
    return None


# A hatás FORRÁSA — a beállító felület ebből mondja meg, hogy egy érték örökölt
# vagy felülírt. Enélkül nem derülne ki, mit állítottál el ténylegesen.
SRC_PAIR = "pair"                  # pairs.<SYM>.gates.<kapu>.<stratégia>
SRC_PAIR_DEFAULT = "pair_default"  # pairs.<SYM>.gates.<kapu>.default
SRC_GLOBAL = "global"              # gates.<kapu>.<stratégia>
SRC_GLOBAL_DEFAULT = "global_default"
SRC_LEGACY = "legacy"              # a régi tf_align.gate lista
SRC_BUILTIN = "builtin"            # REGISTRY default_effect
SRC_MASTER_OFF = "master_off"      # a Beállításokban KIKAPCSOLT kapu

_SOURCES = (SRC_PAIR, SRC_PAIR_DEFAULT, SRC_GLOBAL, SRC_GLOBAL_DEFAULT,
            SRC_LEGACY, SRC_BUILTIN, SRC_MASTER_OFF)
SOURCE_LABEL = _LabelMap("gate.src", _SOURCES)


def effect_with_source(cfg: dict, symbol: str, strategy: str,
                       key: str) -> tuple:
    """`(hatás, forrás)` — a feloldási lánc melyik szintje döntött.

    A beállító felület ezt mutatja („ezen a páron beállítva" vs. „örökölt"),
    különben nem derülne ki, mit állítottál el ténylegesen, és mi jön feljebbről."""
    cfg = cfg or {}
    # ── MESTER-KAPCSOLÓ: a Beállításokban kikapcsolt kapu SEHOL nem szól bele ──
    # Nem töröljük a per-pár beállításokat — csak FELFÜGGESZTJÜK. Visszakapcsolva
    # minden úgy folytatódik, ahogy volt. A külön forrás-kód azért kell, hogy a
    # kapu ablaka KIÍRHASSA az okot: enélkül „Ki"-t mutatna, ami azt sugallná,
    # hogy a felhasználó állította így.
    try:
        from core import gate_layout as _gl
        if not _gl.is_enabled(cfg, key):
            return EFFECT_NONE, SRC_MASTER_OFF
    except Exception:
        pass
    pair_gates = ((cfg.get("pairs") or {}).get(symbol) or {}).get("gates")
    for section, s_own, s_def in (
            ((pair_gates or {}).get(key), SRC_PAIR, SRC_PAIR_DEFAULT),
            (((cfg.get("gates") or {}).get(key)), SRC_GLOBAL, SRC_GLOBAL_DEFAULT)):
        if isinstance(section, dict):
            e = _as_effect(section.get(strategy))
            if e is not None:
                return e, s_own
            e = _as_effect(section.get("default"))
            if e is not None:
                return e, s_def
    if key == TF_ALIGN:
        e = _legacy_tf_align_effect(cfg, symbol, strategy)
        if e:
            return e, SRC_LEGACY
    return default_effect_of(key), SRC_BUILTIN


# ── A LENDÜLET MÓDJA — ugyanaz a feloldási lánc, mint a hatásé ─────────────

def _as_mode(v):
    if v in MOM_MODES:
        return v
    if isinstance(v, dict) and v.get("mode") in MOM_MODES:
        return v["mode"]
    return None


def mode_with_source(cfg: dict, symbol: str, strategy: str,
                     key: str = MOMENTUM) -> tuple:
    """`(mód, forrás)` — MIT figyeljen a kapu erre a (pár, stratégia) párosra."""
    cfg = cfg or {}
    pair_gates = ((cfg.get("pairs") or {}).get(symbol) or {}).get("gates")
    for section, s_own, s_def in (
            ((pair_gates or {}).get(key), SRC_PAIR, SRC_PAIR_DEFAULT),
            (((cfg.get("gates") or {}).get(key)), SRC_GLOBAL, SRC_GLOBAL_DEFAULT)):
        if isinstance(section, dict):
            m = _as_mode(section.get(strategy))
            if m is not None:
                return m, s_own
            m = _as_mode(section.get("default"))
            if m is not None:
                return m, s_def
    return MOM_MODE_DEFAULT, SRC_BUILTIN


def mode_for(cfg: dict, symbol: str, strategy: str, key: str = MOMENTUM) -> str:
    return mode_with_source(cfg, symbol, strategy, key)[0]


def inherited_effect(cfg: dict, symbol: str, strategy: str, key: str) -> tuple:
    """`(hatás, forrás)` ÚGY, MINTHA a pár-szintű felülírás nem létezne.

    A felület ezt ajánlja fel „Örökölt (…)" néven: így látszik, mi lenne az
    érték, ha visszavonod a felülírást — nem kell kitalálni."""
    cfg = dict(cfg or {})
    pairs = dict(cfg.get("pairs") or {})
    pc = dict(pairs.get(symbol) or {})
    pc.pop("gates", None)
    pairs[symbol] = pc
    cfg["pairs"] = pairs
    return effect_with_source(cfg, symbol, strategy, key)


def effect_for(cfg: dict, symbol: str, strategy: str, key: str) -> str:
    """Egy kapu HATÁSA erre a (pár, stratégia) párosra."""
    return effect_with_source(cfg, symbol, strategy, key)[0]


# ---------------------------------------------------------------------------
# MODELLEZZE-E A BACKTEST? — kapunként, külön az éles hatástól
# ---------------------------------------------------------------------------
# A felhasználó kérése: a kapu-táblában az „állapot" azt mondja, mi történik
# ÉLESBEN, egy külön pipa pedig azt, hogy a BACKTEST modellezze-e.
#
# ⚠ MIÉRT KELL A KETTŐ KÜLÖN. Épp ezzel lehet megmérni, mennyit visz el egy
# kapu: kipipálod, futtatsz, kiveszed, futtatsz — a különbség a kapué. Egyetlen
# közös `exec_gates` kapcsolóval (mind vagy semmi) ez nem volt megkérdezhető, és
# a `tools/gate_ab.py` is csak azért létezik, mert a felületen nem lehetett.
#
# A tár a config-házirendet követi: CSAK AZ ELTÉRÉST rögzítjük. Alapértelmezés =
# „modellezze" minden olyan kapunál, ami élesben egyáltalán dönt.
_BT_SECTION = "gates_backtest"


def backtest_enabled(cfg: dict, symbol: str, strategy: str, key: str) -> bool:
    """Modellezze-e a backtest EZT a kaput ezen a páron/stratégián?

    ⚠ FÜGGETLEN az éles hatástól — MINDKÉT irányban. Egy élesben KIKAPCSOLT
    kapu is bekapcsolható a mérésre: a „mi lenne, ha bekapcsolnám?" épp a
    backtest dolga. (Egy korábbi változat ezt tiltotta, mert „a backtest ne
    modellezzen nem létező világot" — de éppen ez a feltáró mérés lényege, és a
    tiltás elvette a legfontosabb kérdést: megéri-e bekapcsolni.)

    Amit a felület KIMOND, ha a kettő eltér: hogy a mérés MÁST modellez, mint
    ami élesben történik. Az eltérés így látható marad, nem néma.

    ⚠ A CSAK KIJELZÉS kapu az EGYETLEN kivétel, és az nem házirend, hanem TÉNY:
    a `decide` átugorja, tehát a bepipálás semmit nem tenne. A valódi szűrés a
    stratégia saját `bt_entry`-jében van.

    Alapértelmezés: modellezze, ha élesben dönt; ne, ha nem. Így a mérés
    alapból az élet tükrözi, és csak akkor tér el, ha te kéred.
    """
    if is_display_only(key):
        return False
    sec = (((cfg or {}).get("pairs", {}).get(symbol) or {})
           .get(_BT_SECTION) or {}).get(strategy) or {}
    v = sec.get(key)
    if v is not None:
        return bool(v)
    return effect_for(cfg, symbol, strategy, key) != EFFECT_NONE


def set_backtest(cfg: dict, symbol: str, strategy: str, key: str,
                 value: bool) -> dict:
    """A backtest-pipa mentése (a `cfg`-t HELYBEN módosítja, és vissza is adja).

    Az ALAPÉRTELMEZÉSSEL egyező érték KIKERÜL a configból — a fájl csak az
    eltérést rögzítheti, különben egy későbbi alapérték-változás némán
    hatástalan maradna az így „beállított" kulcsokra. Az alapértelmezés itt az
    ÉLES állapot, tehát a bejegyzés akkor marad meg, ha a mérés eltér tőle.
    """
    cfg = cfg if cfg is not None else {}
    pairs = cfg.setdefault("pairs", {})
    pc = pairs.setdefault(symbol, {})
    sec = pc.get(_BT_SECTION) or {}
    per = dict(sec.get(strategy) or {})
    _dflt = effect_for(cfg, symbol, strategy, key) != EFFECT_NONE
    if bool(value) == _dflt:
        per.pop(key, None)
    else:
        per[key] = bool(value)
    if per:
        sec[strategy] = per
        pc[_BT_SECTION] = sec
    else:
        sec.pop(strategy, None)
        if sec:
            pc[_BT_SECTION] = sec
        else:
            pc.pop(_BT_SECTION, None)
    return cfg


def effects_for(cfg: dict, symbol: str, strategy: str,
                for_backtest: bool = False) -> dict:
    """`{kapu_kulcs: hatás}` egy (pár, stratégia) párosra — az `evaluate` bemenete.

    `for_backtest=True` → a kapu-táblában KIPIPÁLATLAN kapuk `EFFECT_NONE`-t
    kapnak. Így ugyanaz a hívás szolgálja az élt és a backtestet, és a kettő
    nem tud szétcsúszni: a backtest MINDIG az éles hatásból indul, és legfeljebb
    kivesz belőle — soha nem tesz hozzá.
    """
    out = {k: effect_for(cfg, symbol, strategy, k) for k in KEYS}
    if for_backtest:
        for k in KEYS:
            on = backtest_enabled(cfg, symbol, strategy, k)
            if not on:
                out[k] = EFFECT_NONE
            elif out[k] == EFFECT_NONE:
                # ⚠ „Mi lenne, ha bekapcsolnám?" — a mérés modellezi, holott
                # élesben ki van kapcsolva. Milyen HATÁSSAL? A kapu saját
                # alapértelmezésével; ha az is „nincs", akkor BLOKKOL — mert egy
                # kapu bekapcsolásán azt szokás érteni, hogy akadályoz.
                d = default_effect_of(k)
                out[k] = d if d != EFFECT_NONE else EFFECT_BLOCK
    return out


def backtest_differs(cfg: dict, symbol: str, strategy: str) -> list:
    """Mely kapuknál tér el a MÉRÉS az ÉLES viselkedéstől?

    A felület ezt írja ki: az eltérés legyen látható, ne néma. Enélkül egy
    feltáró beállítás hetekig ott maradhatna, és a backtest csendben mást
    mérne, mint ami történik.
    """
    live = effects_for(cfg, symbol, strategy)
    bt = effects_for(cfg, symbol, strategy, for_backtest=True)
    return [k for k in KEYS if live[k] != bt[k]]


# ---------------------------------------------------------------------------
# Kiértékelők — mindegyik `(state, detail)` párt ad
# ---------------------------------------------------------------------------
# A `detail` az EMBERI magyarázat (a kapu-panelre); a sorban csak az állapot
# látszik. Szándékosan nem betűkód: egy 10 kapus jövőben az `E`/`E2`/`E3`
# olvashatatlan lenne.

def _eval_spread(ctx: dict):
    """A mért spread a megengedett határon belül van-e. A határt a hívó számolja
    (`core.spread_gate`) — itt csak összevetünk, hogy a modul tiszta maradjon."""
    cur = ctx.get("spread_points")
    cap = ctx.get("max_spread_points")
    if cur is None:
        return UNKNOWN, _t("gate.why.no_quote")
    if not cap:
        return OFF, _t("gate.why.no_spread_cap")
    txt = _t("gate.why.spread", now=f"{cur:.0f}", cap=f"{cap:.0f}")
    return (BLOCKING if cur > cap else PASS), txt


def _eval_tf_align(ctx: dict):
    """Az idősíkok együttállása.

    Ha EGYETLEN irányba sem áll együtt (`dir` None), akkor MINDKÉT irányú belépő
    elbukna → BLOKKOL. Ha van együttállás, az abba az irányba szóló jel átmegy
    (a szembeni nem) → ÁTENGED, az iránnyal a magyarázatban."""
    signs = ctx.get("tf_align_signs") or []
    labels = ctx.get("tf_align_labels") or []
    if not signs:
        return UNKNOWN, _t("gate.why.no_tf_data")
    arrows = {1: "↑", -1: "↓", 0: "·"}
    txt = "  ".join(f"{labels[i] if i < len(labels) else '?'} {arrows.get(int(s), '·')}"
                    for i, s in enumerate(signs))
    d = ctx.get("tf_align_dir")
    if not d:
        return BLOCKING, _t("gate.why.no_align", dirs=txt)
    return PASS, _t("gate.why.align", dirs=txt, dir=d)


def _eval_market(ctx: dict):
    """Piac-állapot osztályozó. A besorolást adja; hogy ez blokkol, méretet
    csökkent vagy semmit nem tesz, azt a KONFIGURÁLT hatás dönti el."""
    if not ctx.get("market_name"):
        return OFF, _t("gate.why.no_market")
    lbl = ctx.get("market_label") or ""
    if not lbl:
        return UNKNOWN, _t("gate.why.no_class")
    return PASS, lbl


def _eval_cost(ctx: dict):
    """A spread okozta RR-torzítás. A MÉRT bemenetet (tervezett SL/TP + spread) a
    hívó adja: a stop a STRATÉGIA terve (`sl_tp_points`), nem a kapué."""
    import math as _math
    from core import cost_gate as _cg
    sl = ctx.get("plan_sl_points")
    tp = ctx.get("plan_tp_points")
    sp = ctx.get("spread_points")
    if not sl or not tp:
        return UNKNOWN, _t("gate.why.no_plan")
    d = _cg.distortion(sl, tp, sp)
    if d != d:
        return UNKNOWN, _t("gate.why.not_enough")
    cap = ctx.get("cost_max_distortion")
    txt = _t("gate.why.cost", planned=f"{float(tp) / float(sl):.1f}",
             actual=f"{_cg.effective_rr(sl, tp, sp):.1f}",
             pct=f"{d * 100:+.0f}")
    if cap is None:
        return PASS, txt
    txt += _t("gate.why.cost_cap", cap=f"{float(cap) * 100:+.0f}")
    return (BLOCKING if d > float(cap) else PASS), txt


def _eval_momentum(ctx: dict):
    """A piac „fordulatszáma" (`core.momentum`).

    A kijelzés NEM ismeri a jel irányát (az instrumentum szintjén állunk), ezért
    itt csak az ALAPJÁRAT-ot tudjuk eldönteni — az irány-szűrő irány-tudatos, azt
    a motor méri (`gates.decide`, ugyanaz a szétválasztás, mint a tf_align-nál).
    Így a sor nem ígér olyat, amit ezen a szinten nem lehet tudni."""
    import math as _math
    val = ctx.get("momentum")
    if val is None or (isinstance(val, float) and _math.isnan(val)):
        return UNKNOWN, _t("gate.why.no_bars")
    arrow = "↑" if val > 0 else ("↓" if val < 0 else "·")
    thr = ctx.get("momentum_idle_threshold")
    txt = _t("gate.why.momentum", arrow=arrow, value=f"{abs(val):.2f}")
    if thr is None:
        return PASS, txt
    txt += _t("gate.why.momentum_thr", threshold=f"{float(thr):.2f}")
    return (BLOCKING if abs(val) < float(thr) else PASS), txt


def _eval_volatility(ctx: dict):
    """Az ATR a stratégia kalibrált sávjában van-e (`core.vol_baseline`).

    ⚠ CSAK KIJELZÉS: a `decide` ezt a kaput átugorja, tehát a MÉRÉS nem dönt.
    Mégis fontos, hogy BLOCKING-ot adjon, ha a sávon kívül vagyunk: a `K.Össz.`
    számláló ebből tudja, hogy a motor MOST nem lépne be — pontosan ez hiányzott,
    amikor a BTCUSD hetekig némán nem kereskedett (0,51× a mércének)."""
    from core import vol_baseline as _vb
    atr, base = ctx.get("atr_price"), ctx.get("atr_baseline")
    if not atr or not base:
        return UNKNOWN, _t("gate.why.no_atr")
    st = _vb.status(float(atr), ctx.get("vol_params") or {}, float(base))
    txt = _t("gate.why.vol", ratio=f"{st['ratio']:.2f}")
    return (PASS, txt) if st["ok"] else (BLOCKING, st["why"])


_EVAL = {SPREAD: _eval_spread, TF_ALIGN: _eval_tf_align, MARKET: _eval_market,
         MOMENTUM: _eval_momentum, COST: _eval_cost,
         VOLATILITY: _eval_volatility}


def evaluate(ctx: dict, effects: dict = None) -> list:
    """Minden regisztrált kapu állapota, a REGISTRY sorrendjében.

    `effects`: `{kapu: hatás}` (az `effects_for` adja). Hiányzó → a beépített
    alapértelmezés. Az `EFFECT_NONE` hatású kapu állapota MINDIG `OFF`: ki van
    kapcsolva erre a stratégiára, tehát a mérése nem érdekes — így nem is
    villoghat pirosan olyasmi, ami úgysem szól bele.

    Visszaad: `[{key, label, effect, state, detail}, …]` — a sorrend STABIL."""
    out = []
    for g in REGISTRY:
        key = g["key"]
        eff = (effects or {}).get(key) or g["default_effect"]
        if eff == EFFECT_NONE:
            out.append({"key": key, "label": label_of(key), "effect": eff,
                        "state": OFF,
                        "detail": _t("gate.why.off_for_strategy")})
            continue
        state, detail = _EVAL[key](ctx or {})
        out.append({"key": key, "label": label_of(key), "effect": eff,
                    "state": state, "detail": detail})
    return out


# ---------------------------------------------------------------------------
# Összegzők a kijelzéshez
# ---------------------------------------------------------------------------

def blocking(states) -> list:
    """A ténylegesen BLOKKOLÓ kapuk. Csak az `EFFECT_BLOCK` hatásúak számítanak:
    egy kockázatcsökkentő kapu nem akadályozza a kötést, tehát nem szabad
    „blokkol"-ként mutatni."""
    return [s for s in (states or [])
            if s.get("state") == BLOCKING and s.get("effect") == EFFECT_BLOCK]


def reducing(states) -> list:
    """A KOCKÁZATCSÖKKENTÉST kiváltó kapuk (belép, de kisebben). A 2.0-ban ez a
    jelzés-cella SZAGGATOTT keretét indokolja, szemben a blokkolás tömör keretével."""
    return [s for s in (states or [])
            if s.get("state") == BLOCKING and s.get("effect") == EFFECT_REDUCE]


def is_blocked(states) -> bool:
    """Blokkolja-e BÁRMI most a belépőt?"""
    return bool(blocking(states))


def is_reduced(states) -> bool:
    """Kockázatcsökkentést ír-e elő valamelyik kapu?"""
    return bool(reducing(states))


# ---------------------------------------------------------------------------
# A MOTOR döntése — a belépő-ág közös kapu-logikája (v1.97.0)
# ---------------------------------------------------------------------------
# MIÉRT KÜLÖN az `evaluate()`-től. Az `evaluate` a KIJELZÉST szolgálja: az
# instrumentum szintjén mondja meg, „mi a helyzet", és nem ismeri a jel IRÁNYÁT.
# A motornak viszont irány-tudatos döntés kell: egy BUY jelet a SELL-irányú
# együttállás blokkol, egy SELL-t nem. Ha a motor az `evaluate`-re épülne, a
# TF-kapu GYENGÜLNE (csak a „nincs együttállás" esetet fogná).
#
# Ezért a MÉRÉST a hívó végzi (ott van az iránya és a friss adata), és ide csak
# azt adja be, hogy MELYIK KAPU BUKOTT MEG. Az, hogy ebből mi következik — kimarad
# a belépő, vagy kisebb mérettel megy —, EGY helyen dől el: itt.


def decide(failed: dict, effects: dict) -> dict:
    """A kapuk hatásának feloldása egy konkrét belépő-kísérletre.

    `failed`:  `{kapu: bukott_e}` — a hívó MÉRÉSE (irány-tudatosan).
    `effects`: `{kapu: hatás}` — az `effects_for` adja (config + öröklés).

    Visszaad: `{"blocked": [kapu, …], "reduced": [kapu, …], "risk_factor": float}`

    * `EFFECT_NONE` hatású kapu mérése SZÁMÍT SEM — a hívó akár be sem méri.
    * `EFFECT_BLOCK` + bukás → nincs belépő.
    * `EFFECT_REDUCE` + bukás → van belépő, de `REDUCE_RISK_FACTOR`-ral kisebb.
      Több kockázatcsökkentő kapu NEM szorzódik össze: a felezés felezés marad
      (különben három kapu 1/8-ra vinné a méretet, ami már nem „óvatos", hanem
      értelmetlen)."""
    blocked, reduced = [], []
    for key in KEYS:
        if not (failed or {}).get(key):
            continue
        # A CSAK KIJELZÉS kapuk sosem döntenek — a hatásuk máshol lakik. Enélkül
        # egy configba tévedt `block` némán duplán szűrne.
        if is_display_only(key):
            continue
        eff = (effects or {}).get(key) or default_effect_of(key)
        if eff == EFFECT_BLOCK:
            blocked.append(key)
        elif eff == EFFECT_REDUCE:
            reduced.append(key)
    return {"blocked": blocked, "reduced": reduced,
            "risk_factor": REDUCE_RISK_FACTOR if reduced else 1.0}


def active(effects: dict, key: str) -> bool:
    """Be van-e egyáltalán kapcsolva ez a kapu? (`none` → a hívó ne is mérje.)"""
    return ((effects or {}).get(key) or default_effect_of(key)) != EFFECT_NONE


def block_reason(decision: dict) -> str:
    """Emberi indoklás a naplóba: MELYIK kapu miatt maradt ki a belépő."""
    return ", ".join(label_of(k) for k in (decision or {}).get("blocked") or [])


def badge(states) -> str:
    """A `K.Össz.` cella tartalma: `⛔2` ha blokkol valami, `✓` ha semmi.

    SZÁNDÉKOSAN csak a blokkolást jelzi. Egy korábbi változat a nem-blokkoló
    kapuk „átenged" állapotára is glifát tett — az egy bekapcsolt piac-előszűrőnél
    MINDEN soron ott ült volna, holott semmi nem történik. A badge egy kérdésre
    válaszol: „akadályozza-e valami MOST a kötést?"."""
    blk = blocking(states)
    return f"⛔{len(blk)}" if blk else "✓"


def counts(states) -> dict:
    """`{BLOCKING: n, PASS: n, OFF: n}` — az összevont kijelzéshez.

    Az `UNKNOWN` az `OFF`-hoz számít: mindkettő azt jelenti, hogy ez a kapu MOST
    nem mond semmit. A különbség a kapu-panelen látszik, ahol elfér a magyarázat."""
    out = {BLOCKING: 0, PASS: 0, OFF: 0}
    for s in (states or []):
        st = s.get("state")
        out[BLOCKING if st == BLOCKING else PASS if st == PASS else OFF] += 1
    return out


def frame_state(states) -> str:
    """A 2.0 jelzés-cellájának KERET-állapota: `"blocked"` | `"reduced"` | `""`.

    A pöttyök a stratégia stádiumát mondják, a keret az engedélyt. Üres string =
    NINCS keret: semmi nem szól bele. Ez a leggyakoribb eset, ezért néma — a
    jelölés csak akkor szóljon, ha tényleg történik valami."""
    if is_blocked(states):
        return "blocked"
    if is_reduced(states):
        return "reduced"
    return ""


def ctx_from_state(ds, params: dict, pair_cfg: dict) -> dict:
    """Az `evaluate()` bemenete a dashboard-állapotból.

    `ds` a `live_trader.PairDashboardState` (duck-typed: csak attribútumokat
    olvasunk, nincs import — a modul tiszta marad). `params` a pár futásidejű
    paraméterei (a spread-küszöbhöz), `pair_cfg` a config pár-szekciója.

    A spread-korlát a KÖZÖS execution configból jön: a `params` a betöltéskor már
    tartalmazza (`live_trader._make_state`), tehát itt nincs külön teendő."""
    point_size = float((pair_cfg or {}).get("point_size") or 0.0) or None
    cap = 0.0
    if point_size:
        try:
            from core import spread_gate as _sg
            cap = _sg.max_spread_points(
                getattr(ds, "atr_price", None), point_size, params or {},
                normal_spread_points=(pair_cfg or {}).get("backtest_spread_points"))
        except Exception:
            cap = 0.0
    return {
        "spread_points": getattr(ds, "spread_pts", None),
        "max_spread_points": cap,
        # A NYERS bemenetek is átjönnek — nem a döntéshez (a `cap` már kész),
        # hanem hogy a kapu beállító ablaka MEGMUTATHASSA, miből jött a határ
        # (`core/gate_params.measured_rows`). Külön kiszámolva „kb. ugyanaz”
        # lenne, ami épp a legrosszabb fajta eltérés: némán szétcsúszna.
        "atr_price": getattr(ds, "atr_price", None),
        # VOLATILITÁS (csak kijelzés): a kalibrált mérce és a szűrő számai. A
        # mércét a `vol_baseline` állítja elő a kijelzés-úton (dashboard/gui) —
        # ITT nem számoljuk újra, mert két képlet némán szétcsúszna.
        "atr_baseline": getattr(ds, "atr_baseline", None),
        "vol_params": params or {},
        "point_size": point_size,
        "normal_spread_points": (pair_cfg or {}).get("backtest_spread_points"),
        "tf_align_signs": list(getattr(ds, "tf_align_signs", []) or []),
        "tf_align_labels": list(getattr(ds, "tf_align_labels", []) or []),
        "tf_align_dir": getattr(ds, "tf_align_dir", None),
        "market_name": getattr(ds, "market_strategy", None),
        "market_label": getattr(ds, "market_state_label", "") or "",
        # Lendület: a MÉRT fordulat (a kijelzés tölti `ds.momentum`-ba) és a
        # küszöb, amihez az „alapjárat" mérődik. A küszöb a kapu configjából jön,
        # hogy a sor és a beállító ablak UGYANAZT a számot mutassa.
        "momentum": getattr(ds, "momentum", None),
        "momentum_idle_threshold": momentum_idle_threshold(pair_cfg),
        # Költség/kockázat: a STRATÉGIA tervezett stopja/célja (a kijelzés tölti
        # `ds.plan_sl_points`/`plan_tp_points`-ba) + a pár küszöbe. A kapu csak
        # ezekből dolgozik — nem számol saját stopot.
        "plan_sl_points": getattr(ds, "plan_sl_points", None),
        "plan_tp_points": getattr(ds, "plan_tp_points", None),
        "cost_max_distortion": cost_max_distortion(pair_cfg),
    }


def cost_max_distortion(pair_cfg: dict, cfg: dict = None) -> float:
    """A megengedett RR-torzítás erre a párra (alap ← globális ← pár)."""
    from core import cost_gate as _cg
    out = _cg.DEFAULT_MAX_DISTORTION
    for section in ((cfg or {}).get("gates") or {},
                    (pair_cfg or {}).get("gates") or {}):
        g = section.get(COST)
        if isinstance(g, dict) and g.get("max_rr_distortion") is not None:
            try:
                out = float(g["max_rr_distortion"])
            except (TypeError, ValueError):
                pass
    return out


def momentum_config(pair_cfg: dict, cfg: dict = None) -> dict:
    """A Lendület-kapu MÉRÉSI paraméterei erre a párra (alap ← globális ← pár).

    A hatás/mód per stratégia dől el, a MÉRÉS viszont instrumentum-tulajdonság:
    egy páron egy fordulatszámmérő van, különben a `Lendület` oszlop nem tudna
    mit mutatni."""
    from core import momentum as _m
    out = dict(_m.DEFAULTS)
    for section in ((cfg or {}).get("gates") or {}, (pair_cfg or {}).get("gates") or {}):
        g = section.get(MOMENTUM)
        if isinstance(g, dict):
            for k in _m.DEFAULTS:
                if k in g:
                    out[k] = g[k]
    return out


def momentum_idle_threshold(pair_cfg: dict, cfg: dict = None) -> float:
    return float(momentum_config(pair_cfg, cfg).get("idle_threshold", 0.35))

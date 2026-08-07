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

# A magyar nevek a beállító felülethez (a 2.0 a stratégia paraméter-ablakába teszi).
EFFECT_LABEL = {
    EFFECT_BLOCK:  "Akadályozza a beszállást",
    EFFECT_REDUCE: "Kockázatcsökkentés",
    EFFECT_NONE:   "Ki",
}

# FONTOS: a „csak jelzés" NEM kapu-hatás. Az azt jelenti, hogy jelzést küldünk az
# MT5-nek kötés helyett — ez a STRATÉGIA kiváltsága (`core.trade_mode`), nem a
# kapué. A kapu ne küldjön jelzést.

SPREAD = "spread"
TF_ALIGN = "tf_align"
MARKET = "market"
MOMENTUM = "momentum"
COST = "cost"

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
MOM_MODE_LABEL = {
    MOM_IDLE: "Alapjárat (túl alacsony fordulat)",
    MOM_DIR:  "Irány-szűrő (szemben megy a jellel)",
    MOM_BOTH: "Mindkettő",
}
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
    {"key": SPREAD,   "label": "Spread",             "default_effect": EFFECT_BLOCK},
    {"key": TF_ALIGN, "label": "Idősík-együttállás", "default_effect": EFFECT_NONE},
    {"key": MARKET,   "label": "Piac-állapot",       "default_effect": EFFECT_NONE},
    # ÚJ kapu alapból NEM szól bele (`none`): egy frissítés SOHA ne kezdjen el
    # némán másképp kereskedni, mint amit tegnap tesztelted. Bekapcsolni a
    # kapu ablakában, stratégiánként kell.
    {"key": MOMENTUM, "label": "Lendület",           "default_effect": EFFECT_NONE},
    # Költség/kockázat: a spread mennyire torzítja a TERVEZETT RR-t. Alapból
    # `none` — a meglévő párok viselkedése nem változhat egy frissítéstől.
    {"key": COST,     "label": "Költség/kockázat",   "default_effect": EFFECT_NONE},
)

KEYS = tuple(g["key"] for g in REGISTRY)


def label_of(key: str) -> str:
    for g in REGISTRY:
        if g["key"] == key:
            return g["label"]
    return key


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

SOURCE_LABEL = {
    SRC_PAIR: "ezen a páron beállítva",
    SRC_PAIR_DEFAULT: "örökölt — a pár alapértéke",
    SRC_GLOBAL: "örökölt — globális, erre a stratégiára",
    SRC_GLOBAL_DEFAULT: "örökölt — globális alapérték",
    SRC_LEGACY: "örökölt — a régi tf_align.gate listából",
    SRC_BUILTIN: "örökölt — beépített alapérték",
}


def effect_with_source(cfg: dict, symbol: str, strategy: str,
                       key: str) -> tuple:
    """`(hatás, forrás)` — a feloldási lánc melyik szintje döntött.

    A beállító felület ezt mutatja („ezen a páron beállítva" vs. „örökölt"),
    különben nem derülne ki, mit állítottál el ténylegesen, és mi jön feljebbről."""
    cfg = cfg or {}
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


def effects_for(cfg: dict, symbol: str, strategy: str) -> dict:
    """`{kapu_kulcs: hatás}` egy (pár, stratégia) párosra — az `evaluate` bemenete."""
    return {k: effect_for(cfg, symbol, strategy, k) for k in KEYS}


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
        return UNKNOWN, "nincs friss árjegyzés"
    if not cap:
        return OFF, "nincs spread-korlát beállítva"
    txt = f"jelenlegi {cur:.0f} / határ {cap:.0f} pont"
    return (BLOCKING if cur > cap else PASS), txt


def _eval_tf_align(ctx: dict):
    """Az idősíkok együttállása.

    Ha EGYETLEN irányba sem áll együtt (`dir` None), akkor MINDKÉT irányú belépő
    elbukna → BLOKKOL. Ha van együttállás, az abba az irányba szóló jel átmegy
    (a szembeni nem) → ÁTENGED, az iránnyal a magyarázatban."""
    signs = ctx.get("tf_align_signs") or []
    labels = ctx.get("tf_align_labels") or []
    if not signs:
        return UNKNOWN, "még nincs adat az idősíkokról"
    arrows = {1: "↑", -1: "↓", 0: "·"}
    txt = "  ".join(f"{labels[i] if i < len(labels) else '?'} {arrows.get(int(s), '·')}"
                    for i, s in enumerate(signs))
    d = ctx.get("tf_align_dir")
    if not d:
        return BLOCKING, txt + "  — nincs együttállás"
    return PASS, txt + f"  — együtt: {d}"


def _eval_market(ctx: dict):
    """Piac-állapot osztályozó. A besorolást adja; hogy ez blokkol, méretet
    csökkent vagy semmit nem tesz, azt a KONFIGURÁLT hatás dönti el."""
    if not ctx.get("market_name"):
        return OFF, "nincs piac-előszűrő kiválasztva"
    lbl = ctx.get("market_label") or ""
    if not lbl:
        return UNKNOWN, "még nincs besorolás"
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
        return UNKNOWN, "nincs belépő-terv (SL/TP)"
    d = _cg.distortion(sl, tp, sp)
    if d != d:
        return UNKNOWN, "nincs elég adat"
    cap = ctx.get("cost_max_distortion")
    txt = (f"tervezett {float(tp) / float(sl):.1f}:1 → tényleges "
           f"{_cg.effective_rr(sl, tp, sp):.1f}:1  ({d * 100:+.0f}%)")
    if cap is None:
        return PASS, txt
    txt += f"  /  határ {float(cap) * 100:+.0f}%"
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
        return UNKNOWN, "még nincs elég gyertya a méréshez"
    arrow = "↑" if val > 0 else ("↓" if val < 0 else "·")
    thr = ctx.get("momentum_idle_threshold")
    txt = f"fordulat {arrow}{abs(val):.2f}"
    if thr is None:
        return PASS, txt
    txt += f"  /  alapjárat-küszöb {float(thr):.2f}"
    return (BLOCKING if abs(val) < float(thr) else PASS), txt


_EVAL = {SPREAD: _eval_spread, TF_ALIGN: _eval_tf_align, MARKET: _eval_market,
         MOMENTUM: _eval_momentum, COST: _eval_cost}


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
            out.append({"key": key, "label": g["label"], "effect": eff,
                        "state": OFF, "detail": "erre a stratégiára nincs bekapcsolva"})
            continue
        state, detail = _EVAL[key](ctx or {})
        out.append({"key": key, "label": g["label"], "effect": eff,
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

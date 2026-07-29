"""
Belépő-kapuk EGYSÉGES nyilvántartása — per (instrumentum × stratégia).

A dashboardon eddig három külön oszlop mutatta a Spread / Együtt / Piac
előszűrőt, **instrumentum-szinten**. A config viszont már régóta másképp
gondolkodik:

  • a spread-küszöb a stratégia `params`-ából jön (`min_spread_mult`,
    `max_spread_atr_ratio`) → **per stratégia**;
  • a `tf_align.gate` szó szerint **stratégia-nevek listája** (`["wpr_sma"]`);
  • a piac-előszűrő (`pairs.<sym>.market_strategy`) ma tényleg csak
    instrumentum-szintű — ez a kakukktojás.

Vagyis a felület kettőnél MÁST mutatott, mint amit a motor csinál. Ez a modul a
kiértékelést egy helyre hozza, per (szimbólum, stratégia).

**TISZTA modul**: se MT5, se tkinter, se fájl. A MÉRT értékeket (spread, ATR,
idősík-előjelek, piac-állapot) a hívó adja át egy `ctx` szótárban — így a döntés
egy sorban tesztelhető, és ugyanaz a kód szolgálja ki a dashboardot, a chart-sávot
és a későbbi szűrő-keretrendszert.

A KIJELZÉS szándékosan nem betűkódot ad vissza, hanem állapotot: egy 10 kapus
jövőben az `E`/`E2`/`E3` olvashatatlan lenne. A nevek teljes alakban élnek itt,
a sorban pedig csak az „hány blokkol" számít.
"""

from __future__ import annotations

# ── Egy kapu ÁLLAPOTA ────────────────────────────────────────────────────
PASS = "pass"          # be van kapcsolva és épp ÁTENGED
BLOCKING = "blocking"  # be van kapcsolva és épp BLOKKOL
OFF = "off"            # nincs bekapcsolva erre a (pár, stratégia) párosra
UNKNOWN = "unknown"    # nincs elég mért adat a döntéshez (pl. még nincs tick)

# ── Egy kapu HATÁSA (a felhasználó három pontja) ─────────────────────────
EFFECT_BLOCK = "block"    # megakadályozza a kötést
EFFECT_SIZE = "size"      # kisebb pozíciót nyit
EFFECT_PRESET = "preset"  # kockázatcsökkentő mechanizmust választ

EFFECT_GLYPH = {EFFECT_BLOCK: "⛔", EFFECT_SIZE: "▽", EFFECT_PRESET: "◈"}

# A kapuk SORRENDJE stabil: a sorban megjelenő csík szegmensei így mindig
# ugyanazon a helyen vannak, és a pozíciók maguktól rögzülnek — anélkül, hogy
# bárkinek meg KELLENE tanulnia őket (a nevek egy kattintásra ott vannak).
SPREAD = "spread"
TF_ALIGN = "tf_align"
MARKET = "market"

REGISTRY = (
    {"key": SPREAD,   "label": "Spread",              "effect": EFFECT_BLOCK},
    {"key": TF_ALIGN, "label": "Idősík-együttállás",  "effect": EFFECT_BLOCK},
    {"key": MARKET,   "label": "Piac-állapot",        "effect": EFFECT_PRESET},
)


def label_of(key: str) -> str:
    for g in REGISTRY:
        if g["key"] == key:
            return g["label"]
    return key


def effect_of(key: str) -> str:
    for g in REGISTRY:
        if g["key"] == key:
            return g["effect"]
    return EFFECT_BLOCK


# ── Kiértékelők ──────────────────────────────────────────────────────────
# Mindegyik `(state, detail)` párt ad: a `detail` az EMBERI magyarázat, ami a
# kapu-panelen jelenik meg (a sorban csak az állapot látszik).

def _eval_spread(ctx: dict):
    """A mért spread a megengedett határon belül van-e.

    A határt a hívó számolja a STRATÉGIA paramétereivel (`core.spread_gate`) —
    itt csak összevetünk, hogy a modul tiszta maradjon."""
    cur = ctx.get("spread_points")
    cap = ctx.get("max_spread_points")
    if cur is None:
        return UNKNOWN, "nincs friss árjegyzés"
    if not cap:
        return OFF, "nincs spread-korlát beállítva"
    txt = f"jelenlegi {cur:.0f} / határ {cap:.0f} pont"
    return (BLOCKING if cur > cap else PASS), txt


def _eval_tf_align(ctx: dict):
    """Az idősíkok együttállása. A kapu csak azokra a stratégiákra hat, amik a
    `tf_align.gate` listában szerepelnek — ezt a hívó adja át `gated`-ként.

    Ha EGYETLEN irányba sem áll együtt (`dir` None), akkor MINDKÉT irányú belépő
    elbukna → ez a BLOKKOL állapot. Ha van együttállás, az abba az irányba szóló
    jel átmegy (a szembeni nem) → ÁTENGED, az iránnyal a magyarázatban."""
    if not ctx.get("tf_align_gated"):
        return OFF, "erre a stratégiára nincs bekapcsolva"
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
    """Piac-állapot osztályozó. MA nem blokkol: a kockázatcsökkentő preset
    megválasztásához ad bemenetet (ezért `EFFECT_PRESET`).

    Amikor a szűrő-keretrendszer (a felhasználó 8. pontja) elkészül, ez a kapu
    is kaphat blokkoló vagy méret-csökkentő hatást — a szerkezet már áll."""
    if not ctx.get("market_name"):
        return OFF, "nincs piac-előszűrő kiválasztva"
    lbl = ctx.get("market_label") or ""
    if not lbl:
        return UNKNOWN, "még nincs besorolás"
    return PASS, lbl


_EVAL = {SPREAD: _eval_spread, TF_ALIGN: _eval_tf_align, MARKET: _eval_market}


def evaluate(ctx: dict) -> list:
    """Minden regisztrált kapu állapota, a REGISTRY sorrendjében.

    Visszaad: `[{key, label, effect, state, detail}, …]` — a sorrend STABIL, mert
    a csík szegmenseinek helye ebből következik."""
    out = []
    for g in REGISTRY:
        state, detail = _EVAL[g["key"]](ctx or {})
        out.append({**g, "state": state, "detail": detail})
    return out


def blocking(states) -> list:
    """A ténylegesen BLOKKOLÓ kapuk. Csak az `EFFECT_BLOCK` hatásúak számítanak
    ide: egy méret-csökkentő vagy preset-választó kapu nem akadályozza a kötést,
    tehát nem szabad „blokkol"-ként mutatni."""
    return [s for s in (states or [])
            if s.get("state") == BLOCKING and s.get("effect") == EFFECT_BLOCK]


def strip(states) -> str:
    """A sorban látható CSÍK: szegmensenként egy kapu, betű NÉLKÜL.

    ▮ = átenged · ▨ = blokkol · ▯ = kikapcsolva/ismeretlen

    Azért nincs benne betű, mert 10 kapunál a kódok (E, E2, E3…) olvashatatlanná
    válnának. Nem kell tudni, melyik a harmadik szegmens ahhoz, hogy lásd: valami
    blokkol — a nevek a kapu-panelen, teljes alakban vannak."""
    glyph = {PASS: "▮", BLOCKING: "▨"}
    return "".join(glyph.get(s.get("state"), "▯") for s in (states or []))


def badge(states) -> str:
    """A csík melletti rövid összefoglaló: `⛔2` ha blokkol, `✓` ha minden tiszta.

    A méret/preset hatásokat külön jelöljük — azok nem akadályozzák a kötést, de
    megváltoztatják, HOGYAN köt."""
    blk = blocking(states)
    if blk:
        return f"{EFFECT_GLYPH[EFFECT_BLOCK]}{len(blk)}"
    act = [s for s in (states or [])
           if s.get("state") == PASS and s.get("effect") != EFFECT_BLOCK]
    if act:
        return EFFECT_GLYPH[effect_of(act[0]["key"])] if len(act) == 1 else "◈"
    return "✓"


def is_blocked(states) -> bool:
    """Blokkolja-e BÁRMI most a belépőt? A sor halványítása ezt használja — így a
    „miért nem köt?" kérdésre nem kell se betűt, se számot olvasni."""
    return bool(blocking(states))


def ready_count(per_strategy: dict) -> tuple:
    """`(kereskedésre kész, összes)` az instrumentum-sor aggregátumához.

    `per_strategy`: {stratégia-név: states}. „Kész" = semmi nem blokkolja."""
    total = len(per_strategy or {})
    ok = sum(1 for st in (per_strategy or {}).values() if not is_blocked(st))
    return ok, total

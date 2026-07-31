"""Belepo-kapuk: allapot + KONFIGURALT hatas per (par x strategia) — core/gates.py.

A 2.0 terv 6. pontja: minden kapu hatasa strategiankent allithato (block /
reduce / none), oroklessel, hogy a config ne robbanjon fel. Ezek a tesztek a
feloldasi lancot es a kijelzes-osszegzoket orzik.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import gates as g

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def state_of(states, key):
    return next(s["state"] for s in states if s["key"] == key)


def effect_of(states, key):
    return next(s["effect"] for s in states if s["key"] == key)


# ══ 1. A hatas feloldasa — oroklesi lanc ═══════════════════════════════════
cfg = {
    "gates": {
        "spread":   {"default": "block"},
        "tf_align": {"default": "none", "wpr_sma": "block"},
        "market":   {"default": "none"},
    },
    "pairs": {
        "GOLD": {"gates": {"market": {"wpr_sma": "reduce"}}},
        "UK100": {},
    },
}

check("globalis default ervenyes", g.effect_for(cfg, "UK100", "ml_ai", g.SPREAD) == "block")
check("globalis strategia-felulriras nyer a default felett",
      g.effect_for(cfg, "UK100", "wpr_sma", g.TF_ALIGN) == "block")
check("...a masik strategia a defaultot kapja",
      g.effect_for(cfg, "UK100", "ml_ai", g.TF_ALIGN) == "none")
check("PAR-szintu felulriras nyer a globalis felett",
      g.effect_for(cfg, "GOLD", "wpr_sma", g.MARKET) == "reduce")
check("...de csak arra a strategiara",
      g.effect_for(cfg, "GOLD", "ml_ai", g.MARKET) == "none")
check("...es csak arra a parra",
      g.effect_for(cfg, "UK100", "wpr_sma", g.MARKET) == "none")

# Beepitett alapertelmezes, ha a config nem mond semmit
check("config nelkul a spread beepitetten blokkol",
      g.effect_for({}, "GOLD", "wpr_sma", g.SPREAD) == "block")
check("config nelkul a piac beepitetten ki van",
      g.effect_for({}, "GOLD", "wpr_sma", g.MARKET) == "none")
check("ervenytelen hatas-ertek -> a lanc tovabb megy",
      g.effect_for({"gates": {"spread": {"default": "hulyeseg"}}},
                   "GOLD", "x", g.SPREAD) == "block")

# ── Visszafele kompatibilitas: a REGI tf_align.gate LISTA ──
legacy = {"tf_align": {"gate": ["wpr_sma"]}, "pairs": {"GOLD": {}}}
check("regi tf_align.gate lista: a listaban levo strategiat blokkolja",
      g.effect_for(legacy, "GOLD", "wpr_sma", g.TF_ALIGN) == "block")
check("...a listan kivulit nem", g.effect_for(legacy, "GOLD", "ml_ai", g.TF_ALIGN) == "none")

legacy_pair = {"tf_align": {"gate": []},
               "pairs": {"GOLD": {"tf_align": {"gate": ["ml_ai"]}}}}
check("a PAR-szintu regi lista nyer a globalis felett",
      g.effect_for(legacy_pair, "GOLD", "ml_ai", g.TF_ALIGN) == "block")
check("...es a globalis ures lista nem blokkolja a masikat",
      g.effect_for(legacy_pair, "GOLD", "wpr_sma", g.TF_ALIGN) == "none")

# Az UJ gates config ELSOBBSEGET elvez a regi listaval szemben
mixed = {"gates": {"tf_align": {"default": "none"}},
         "tf_align": {"gate": ["wpr_sma"]}, "pairs": {"GOLD": {}}}
check("az uj gates config felulirja a regi listat",
      g.effect_for(mixed, "GOLD", "wpr_sma", g.TF_ALIGN) == "none")

check("effects_for mind a harom kaput adja",
      set(g.effects_for(cfg, "GOLD", "wpr_sma")) == set(g.KEYS))

# ══ 2. Kiertekeles ═════════════════════════════════════════════════════════
ctx_ok = {
    "spread_points": 250, "max_spread_points": 1312,
    "tf_align_signs": [1, 1, 1], "tf_align_labels": ["M1", "M5", "M15"],
    "tf_align_dir": "BUY",
    "market_name": "regime", "market_label": "Sz.Bika",
}
eff_all_block = {g.SPREAD: "block", g.TF_ALIGN: "block", g.MARKET: "block"}
st = g.evaluate(ctx_ok, eff_all_block)
check("tag spread -> ATENGED", state_of(st, g.SPREAD) == g.PASS)
check("egyutt allo idosikok -> ATENGED", state_of(st, g.TF_ALIGN) == g.PASS)
check("a sorrend STABIL (registry szerint)", [s["key"] for s in st] == list(g.KEYS))

ctx_wide = {**ctx_ok, "spread_points": 1400}
check("tul tag spread -> BLOKKOL",
      state_of(g.evaluate(ctx_wide, eff_all_block), g.SPREAD) == g.BLOCKING)

ctx_noalign = {**ctx_ok, "tf_align_dir": None}
check("nincs egyuttallas -> BLOKKOL",
      state_of(g.evaluate(ctx_noalign, eff_all_block), g.TF_ALIGN) == g.BLOCKING)

check("nincs arjegyzes -> ISMERETLEN",
      state_of(g.evaluate({**ctx_ok, "spread_points": None}, eff_all_block),
               g.SPREAD) == g.UNKNOWN)
check("nincs idosik-adat -> ISMERETLEN",
      state_of(g.evaluate({**ctx_ok, "tf_align_signs": []}, eff_all_block),
               g.TF_ALIGN) == g.UNKNOWN)
check("nincs piac-eloszuro -> KI",
      state_of(g.evaluate({**ctx_ok, "market_name": None}, eff_all_block),
               g.MARKET) == g.OFF)

# ── A 'none' hatasu kapu allapota MINDIG OFF: ne villogjon, ami nem szol bele ──
st_none = g.evaluate(ctx_wide, {g.SPREAD: "none"})
check("'none' hatas -> az allapot OFF, meg ha a meres blokkolna is",
      state_of(st_none, g.SPREAD) == g.OFF)
check("...es a hatas is 'none' marad", effect_of(st_none, g.SPREAD) == "none")

check("hianyzo effects -> a beepitett alapertelmezes",
      effect_of(g.evaluate(ctx_ok), g.SPREAD) == "block")

# ══ 3. Osszegzok — a kijelzes szerzodese ═══════════════════════════════════
blocked = g.evaluate(ctx_wide, eff_all_block)
check("blocking() megtalalja a blokkolot", len(g.blocking(blocked)) == 1)
check("is_blocked() igaz", g.is_blocked(blocked) is True)
check("K.Ossz. badge: koros tiltas + darabszam", g.badge(blocked) == "⛔1")
check("K.Ossz. badge minden rendben: pipa", g.badge(g.evaluate(ctx_ok, eff_all_block)) == "✓")

# ── A 'reduce' hatasu kapu NEM blokkol ──
eff_reduce = {g.SPREAD: "reduce", g.TF_ALIGN: "none", g.MARKET: "none"}
red = g.evaluate(ctx_wide, eff_reduce)
check("a 'reduce' hatasu kapu NEM szamit blokkolonak", g.is_blocked(red) is False)
check("...de kockazatcsokkentesnek igen", g.is_reduced(red) is True)
check("...es a badge pipat mutat (a kotes nincs akadalyozva)", g.badge(red) == "✓")

# ── A jelzes-cella KERETE (2.0) ──
check("keret: blokkolasnal 'blocked'", g.frame_state(blocked) == "blocked")
check("keret: kockazatcsokkentesnel 'reduced'", g.frame_state(red) == "reduced")
check("keret: ha semmi nem szol bele, URES (nema)",
      g.frame_state(g.evaluate(ctx_ok, eff_all_block)) == "")
check("a blokkolas ELSOBBSEGET elvez a csokkentessel szemben",
      g.frame_state(g.evaluate(ctx_wide, {g.SPREAD: "block", g.TF_ALIGN: "reduce",
                                          g.MARKET: "none"})) == "blocked")

c = g.counts(blocked)
check("counts: egy blokkol", c[g.BLOCKING] == 1)
check("counts: az UNKNOWN az OFF-hoz szamit",
      g.counts(g.evaluate({**ctx_ok, "spread_points": None},
                          {g.SPREAD: "block"}))[g.OFF] >= 1)

# ══ 4. Robusztussag ════════════════════════════════════════════════════════
check("ures ctx nem dob kivetelt", len(g.evaluate({}, eff_all_block)) == len(g.KEYS))
check("None ctx nem dob kivetelt", len(g.evaluate(None)) == len(g.KEYS))
check("blocking(None) ures", g.blocking(None) == [])
check("badge(None) pipa", g.badge(None) == "✓")
check("frame_state(None) ures", g.frame_state(None) == "")
check("label_of ismeretlen kulcsra a kulcsot adja", g.label_of("nincs") == "nincs")
check("effect_for None cfg-vel a beepitettet adja",
      g.effect_for(None, "GOLD", "x", g.SPREAD) == "block")


# ══ 5. ctx_from_state — a dashboard-allapotbol ═════════════════════════════
class DS:
    spread_pts = 250
    atr_price = 5.0
    tf_align_signs = [1, -1, 1]
    tf_align_labels = ["M1", "M5", "M15"]
    tf_align_dir = None
    market_strategy = "regime"
    market_state_label = "Sz.Bika"


ctx = g.ctx_from_state(DS(), {"max_spread_atr_ratio": 0.2}, {"point_size": 0.01})
check("ctx: a mert spread atkerul", ctx["spread_points"] == 250)
check("ctx: a spread-hatar szamolodik (ATR 5.0 / 0.01 x 0.2 = 100)",
      abs(ctx["max_spread_points"] - 100.0) < 1e-9, f'{ctx["max_spread_points"]}')
check("ctx: az idosik-elojelek atkerulnek", ctx["tf_align_signs"] == [1, -1, 1])
check("ctx: a piac-cimke atkerul", ctx["market_label"] == "Sz.Bika")

# A szuk spread-hatar (100 pont) a 250-es spreadet BLOKKOLJA — a spread-kapu
# beepitetten 'block'. Ez maga is helyes, de elfedne a tf_align kulonbseget,
# ezert a lanc-teszthez tagabb hatart adunk (0.6 x 500 = 300 > 250).
check("szuk hatar mellett mar a SPREAD is blokkol (a beepitett hatas 'block')",
      g.frame_state(g.evaluate(ctx, g.effects_for({}, "GOLD", "ml_ai"))) == "blocked")

ctx_wide_cap = g.ctx_from_state(DS(), {"max_spread_atr_ratio": 0.6},
                                {"point_size": 0.01})
check("tagabb hatar -> a spread mar atenged", ctx_wide_cap["max_spread_points"] > 250)

# A teljes lanc: allapotbol -> ctx -> evaluate. Nincs egyuttallas -> blokkol,
# de CSAK azt a strategiat, amelyikre a tf_align kapu be van kapcsolva.
_cfg_tf = {"gates": {"tf_align": {"wpr_sma": "block"}}}
check("teljes lanc: nincs egyuttallas -> a wpr_sma blokkolva",
      g.frame_state(g.evaluate(ctx_wide_cap,
                               g.effects_for(_cfg_tf, "GOLD", "wpr_sma"))) == "blocked")
check("...ugyanez az ml_ai-ra NEM blokkolas (nincs ra bekapcsolva)",
      g.frame_state(g.evaluate(ctx_wide_cap,
                               g.effects_for(_cfg_tf, "GOLD", "ml_ai"))) == "")

check("ctx point_size nelkul nem szall el", g.ctx_from_state(DS(), {}, {}) is not None)

# ══ 6. A hatas FORRASA — a beallito felulet ehhez igazodik ════════════════
# A felulet kiirja, hogy egy ertek OROKOLT vagy ezen a paron beallitott;
# enelkul nem derulne ki, mit allitottal el tenylegesen.
SRC_CFG = {
    "gates": {"spread": {"default": "block"},
              "tf_align": {"default": "none", "wpr_sma": "block"}},
    "pairs": {"GOLD": {"gates": {"market": {"wpr_sma": "reduce"},
                                 "spread": {"default": "none"}}},
              "UK100": {}},
}

check("par+strategia felulriras -> forras 'pair'",
      g.effect_with_source(SRC_CFG, "GOLD", "wpr_sma", g.MARKET)
      == ("reduce", g.SRC_PAIR))
check("par-szintu default -> forras 'pair_default'",
      g.effect_with_source(SRC_CFG, "GOLD", "ml_ai", g.SPREAD)
      == ("none", g.SRC_PAIR_DEFAULT))
check("globalis strategia-ertek -> forras 'global'",
      g.effect_with_source(SRC_CFG, "UK100", "wpr_sma", g.TF_ALIGN)
      == ("block", g.SRC_GLOBAL))
check("globalis default -> forras 'global_default'",
      g.effect_with_source(SRC_CFG, "UK100", "ml_ai", g.TF_ALIGN)
      == ("none", g.SRC_GLOBAL_DEFAULT))
check("semmi sincs configolva -> forras 'builtin'",
      g.effect_with_source({}, "X", "y", g.SPREAD) == ("block", g.SRC_BUILTIN))
check("a regi tf_align.gate lista -> forras 'legacy'",
      g.effect_with_source({"tf_align": {"gate": ["wpr_sma"]}, "pairs": {"G": {}}},
                           "G", "wpr_sma", g.TF_ALIGN) == ("block", g.SRC_LEGACY))
check("minden forrasnak van magyar felirata",
      all(s in g.SOURCE_LABEL for s in (g.SRC_PAIR, g.SRC_PAIR_DEFAULT,
                                        g.SRC_GLOBAL, g.SRC_GLOBAL_DEFAULT,
                                        g.SRC_LEGACY, g.SRC_BUILTIN)))

# inherited_effect: mi lenne az ertek, ha visszavonnad a par-szintu felulirast?
# A felulet ezt kinalja fel "Orokolt (…)" neven — igy nem kell kitalalni.
check("inherited_effect a par-szintu felulirast FIGYELMEN KIVUL hagyja",
      g.inherited_effect(SRC_CFG, "GOLD", "wpr_sma", g.MARKET)
      == ("none", g.SRC_BUILTIN))
check("...a spreadnel a globalisra esik vissza (nem a par defaultjara)",
      g.inherited_effect(SRC_CFG, "GOLD", "ml_ai", g.SPREAD)
      == ("block", g.SRC_GLOBAL_DEFAULT))
check("inherited_effect NEM modositja a configot",
      SRC_CFG["pairs"]["GOLD"]["gates"]["market"]["wpr_sma"] == "reduce")

check("effect_for valtozatlanul a hatast adja (a forras nelkul)",
      g.effect_for(SRC_CFG, "GOLD", "wpr_sma", g.MARKET) == "reduce")
check("minden hatasnak van magyar felirata",
      all(e in g.EFFECT_LABEL for e in g.EFFECTS))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

"""
Spread-kapu (piac-szintű VÉGREHAJTÁSI kapu) — EGY forrás, amit az él és a backtest
is hív, hogy sose csússzon szét.

A kapu a bróker pillanatnyi spreadjét a piac mozgékonyságához (ATR) méri: túl tág
spread (csendes/kaotikus piac vagy hír) → kihagyjuk a belépőt. NEM stratégia-jelzés,
hanem keretrendszer-szintű kapu.

Képlet (PONTBAN — a bróker natív egysége):
    max_spread_points = max(min_spread_points, (atr / point_size) * max_spread_atr_ratio)
    ok = spread_points <= max_spread_points

A hívó PONTBAN adja a spreadet és ÁRBAN az ATR-t + a `point_size`-ot (bármelyik oldal
a saját egységéből ide konvertál). Adathiány (nincs ATR / point_size) → fail-open
(nem szűrünk), pontosan úgy, ahogy az él is teszi.

Paraméterek (a stratégia `params`-ából, visszafelé kompatibilis alapértékekkel):
  • max_spread_atr_ratio (0.20) — a megengedett spread az ATR hányada
  • min_spread_mult      (1.5)  — az ALSÓ küszöb az instrumentum SAJÁT tipikus
                                   spreadjének ennyiszerese
  • min_spread_points             — ha meg van adva, EZ az abszolút alsó küszöb
                                   (kézi felülírás; a mult helyett)

MIÉRT RELATÍV A PADLÓ. Korábban fix 2.0 „pip" volt az alsó küszöb — csakhogy a
„pip" instrumentumonként mást jelent: EURUSD-n 20 pont, indexen és EURJPY-n 200.
Mérés a valós előzményen (mennyit blokkolt a kapu):

    GOLD    padló 200 pont, tipikus spread  45  →  0,1%   gyakorlatilag süket
    EURJPY  padló 200 pont, tipikus spread  25  →  0,8%   gyakorlatilag süket
    UsaInd  padló 200 pont, tipikus spread 309  →  0,4%   (ott az ATR-tag laza)
    UK100   padló 200 pont, tipikus spread 139  → 30,2%   szűrt

Vagyis ugyanaz a szám az egyik páron mindent átengedett, a másikon a kötések
harmadát vágta. A padló mostantól az instrumentum SAJÁT normál spreadjéhez mér
(`pair_cfg.backtest_spread_points`, amit a `tools/refresh_point_values.py` a valós
előzmény mediánjából tölt) — így minden páron ugyanazt JELENTI: „a szokásosnál
ennyivel tágabb spreadet még elfogadunk".
"""

from __future__ import annotations

DEFAULT_RATIO = 0.20
DEFAULT_MIN_MULT = 1.5      # a padló az instrumentum normál spreadjének ennyiszerese
DEFAULT_MIN_PIPS = 2.0      # tartalék, ha a normál spread nem ismert (régi config)


def spread_floor_points(params: dict, normal_spread_points: "float | None") -> float:
    """A kapu ALSÓ küszöbe PONTBAN.

    Sorrend: (1) kézzel megadott `min_spread_points`, (2) az instrumentum normál
    spreadje × `min_spread_mult`, (3) a régi fix alapérték, ha a normál spread
    ismeretlen (így a hiányos configok viselkedése nem változik)."""
    explicit = params.get("min_spread_points")
    if explicit is not None:
        try:
            return float(explicit)
        except (TypeError, ValueError):
            pass
    try:
        normal = float(normal_spread_points) if normal_spread_points else 0.0
    except (TypeError, ValueError):
        normal = 0.0
    if normal > 0:
        return normal * float(params.get("min_spread_mult", DEFAULT_MIN_MULT))
    return DEFAULT_MIN_PIPS


def max_spread_points(atr_price: "float | None", point_size: float, params: dict,
                    normal_spread_points: "float | None" = None) -> float:
    """A megengedett max spread PIPBEN. Adathiány → float('inf') (nem szűr).

    `normal_spread_points`: az instrumentum tipikus spreadje (a hívó a
    `pair_cfg["backtest_spread_points"]`-et adja) — ehhez mér a relatív padló."""
    if not point_size or point_size <= 0 or atr_price is None:
        return float("inf")
    try:
        atr_price = float(atr_price)
    except (TypeError, ValueError):
        return float("inf")
    if atr_price <= 0:
        return float("inf")
    ratio    = float(params.get("max_spread_atr_ratio", DEFAULT_RATIO))
    min_points = spread_floor_points(params, normal_spread_points)
    atr_points = atr_price / point_size
    return max(min_points, atr_points * ratio)


def spread_ok(spread_points: float, atr_price: "float | None", point_size: float,
              params: dict,
              normal_spread_points: "float | None" = None) -> tuple[bool, float]:
    """True, ha a spread (PONT) belefér a piac-kapuba. Visszaad: (ok, max_points) — a
    második a diagnosztikához/loghoz. Fail-open, ha nincs érvényes ATR/point_size.

    `normal_spread_points`: az instrumentum tipikus spreadje a relatív padlóhoz
    (a hívó a `pair_cfg["backtest_spread_points"]`-et adja)."""
    cap = max_spread_points(atr_price, point_size, params, normal_spread_points)
    try:
        sp = float(spread_points)
    except (TypeError, ValueError):
        return True, cap
    return sp <= cap, cap

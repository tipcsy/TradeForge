"""
Spread-kapu (piac-szintű VÉGREHAJTÁSI kapu) — EGY forrás, amit az él és a backtest
is hív, hogy sose csússzon szét.

A kapu a bróker pillanatnyi spreadjét a piac mozgékonyságához (ATR) méri: túl tág
spread (csendes/kaotikus piac vagy hír) → kihagyjuk a belépőt. NEM stratégia-jelzés,
hanem keretrendszer-szintű kapu.

Képlet (PIP-ben, egység-függetlenül):
    max_spread_pips = max(min_spread_pips, (atr / pip_size) * max_spread_atr_ratio)
    ok = spread_pips <= max_spread_pips

A hívó PIPBEN adja a spreadet és ÁRBAN az ATR-t + a `pip_size`-ot (bármelyik oldal
a saját egységéből ide konvertál). Adathiány (nincs ATR / pip_size) → fail-open
(nem szűrünk), pontosan úgy, ahogy az él is teszi.

Paraméterek (a stratégia `params`-ából, visszafelé kompatibilis alapértékekkel):
  • max_spread_atr_ratio (0.20) — a megengedett spread az ATR hányada
  • min_spread_pips      (2.0)  — abszolút alsó küszöb pipben (csendes piacon is
                                   enged ennyit, hogy a szűrő ne legyen túl szigorú)
"""

from __future__ import annotations

DEFAULT_RATIO = 0.20
DEFAULT_MIN_PIPS = 2.0


def max_spread_pips(atr_price: "float | None", pip_size: float, params: dict) -> float:
    """A megengedett max spread PIPBEN. Adathiány → float('inf') (nem szűr)."""
    if not pip_size or pip_size <= 0 or atr_price is None:
        return float("inf")
    try:
        atr_price = float(atr_price)
    except (TypeError, ValueError):
        return float("inf")
    if atr_price <= 0:
        return float("inf")
    ratio    = float(params.get("max_spread_atr_ratio", DEFAULT_RATIO))
    min_pips = float(params.get("min_spread_pips", DEFAULT_MIN_PIPS))
    atr_pips = atr_price / pip_size
    return max(min_pips, atr_pips * ratio)


def spread_ok(spread_pips: float, atr_price: "float | None", pip_size: float,
              params: dict) -> tuple[bool, float]:
    """True, ha a spread (pip) belefér a piac-kapuba. Visszaad: (ok, max_pips) — a
    második a diagnosztikához/loghoz. Fail-open, ha nincs érvényes ATR/pip_size."""
    cap = max_spread_pips(atr_price, pip_size, params)
    try:
        sp = float(spread_pips)
    except (TypeError, ValueError):
        return True, cap
    return sp <= cap, cap

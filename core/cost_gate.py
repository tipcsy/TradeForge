"""
KÖLTSÉG/KOCKÁZAT kapu — mennyire torzítja a spread a TERVEZETT kockázat/hozamot?

MIÉRT KELL, HA MÁR VAN SPREAD-KAPU. A `core/spread_gate.py` a spreadet az ATR-hez
méri, DE van egy relatív padlója (`min_spread_mult × normál_spread`), ami
konstrukció szerint mindig nagyobb a pár normál spreadjénél — tehát egy pár a
saját szokásos spreadjén SOHA nem akad fenn rajta. Mérve (2026-08-07):

    pár      spread   ATR-tag   padló   tényleges határ   blokkol?
    EURCHF       15       6,2    23,1              23,1        nem
    EURGBP       14       5,7    21,6              21,6        nem

Az ATR-tag (6,2) rég blokkolna, a padló (23,1) viszont átengedi. A spread-kapu
tehát a KITÁGULÓ spreadet fogja, a KRÓNIKUSAN drága instrumentumot nem — pedig
EURCHF-en a spread a tervezett stop HARMADA.

MIT MÉR EZ A KAPU. Nem a spread nagyságát önmagában, hanem azt, hogy mennyire
rontja el az üzletet. A stop és a cél a bróker másik oldalán teljesül:

    tényleges_RR = (TP + spread) / (SL − spread)

EURCHF-en a tervezett 2,0-ból így 3,3 lesz (+64%): nem 2:1-re kötsz, hanem
3,3:1-re — a stopod közelebb, a célod távolabb. Ugyanaz a jel ott strukturálisan
rosszabb üzlet, és ezt EGYETLEN meglévő kapu sem veszi észre.

MIÉRT KAPU ÉS NEM SZINT-MÓDOSÍTÓ. Mérve: a stop szélesítése NEM váltja meg a
drága instrumentumot. EURCHF-en a `sl_atr_mult` 1,5 → 3,0 emelése a spread/SL
arányt 31%-ról 15%-ra viszi, de a véletlen belépés éle közben +0,4-ről −16,4-re
zuhan (a 2× szélesebb TP elérhetetlenné válik a rendelkezésre álló idő alatt).
Nincs olyan geometria, ami kifizetné a spreadet.

A másik ok szerkezeti: ha egy kapu elmozdíthatná az SL-t, az „1 R" elveszítené a
jelentését. A rendszer R-alapú elszámolásra épül (`core/position_meta.py` a
belépéskori kockázatot rögzíti, a P&L-cellák R-ben is mutatnak, a
kockázatcsökkentő presetek R-ben gondolkodnak) — egy némán átírt stop minden
korábbi R-számot hazuggá tenne visszamenőleg.

TISZTA modul: se MT5, se config, se fájl — a hívó adja a mért értékeket.
"""

from __future__ import annotations

# A tervezett RR-t ennyivel torzíthatja a spread, mielőtt a kapu megszólal.
# 0.25 = „a 2:1-ből legfeljebb 2,5:1 lehet". Mérve ez EURCHF-et (+64%),
# EURGBP-t (+68%) és EURJPY-t (+26%) zárja ki, az EURUSD-t (+18%) átengedi.
DEFAULT_MAX_DISTORTION = 0.25


def effective_rr(sl_points: float, tp_points: float,
                 spread_points: float) -> float:
    """A ténylegesen vállalt kockázat/hozam a spreaddel együtt.

    `inf`, ha a spread felemészti a stopot (`spread >= sl`) — olyankor a belépő
    matematikailag reménytelen, nem csak kedvezőtlen."""
    try:
        sl = float(sl_points)
        tp = float(tp_points)
        sp = max(0.0, float(spread_points or 0.0))
    except (TypeError, ValueError):
        return float("nan")
    risk = sl - sp
    if sl <= 0 or tp <= 0:
        return float("nan")
    if risk <= 0:
        return float("inf")
    return (tp + sp) / risk


def distortion(sl_points: float, tp_points: float,
               spread_points: float) -> float:
    """Mennyivel rosszabb a TÉNYLEGES RR a tervezettnél (arányban).

    0.0 = a spread nem számít; 0.64 = a tervezett 2,0-ból 3,29 lett.
    `nan`, ha nincs értelmes terv (hiányzó SL/TP)."""
    import math
    eff = effective_rr(sl_points, tp_points, spread_points)
    if eff != eff:                       # nan
        return float("nan")
    try:
        planned = float(tp_points) / float(sl_points)
    except (TypeError, ValueError, ZeroDivisionError):
        return float("nan")
    if planned <= 0:
        return float("nan")
    if eff == float("inf"):
        return float("inf")
    return eff / planned - 1.0


def failed(sl_points: float, tp_points: float, spread_points: float,
           max_distortion: float = DEFAULT_MAX_DISTORTION) -> bool:
    """Bukik-e a kapu erre a konkrét belépő-tervre?

    Adathiánynál (`nan`) NEM szűrünk — fail-open, ugyanúgy, ahogy a spread-kapu
    is teszi: hiányzó mérésből nem hozunk kereskedési döntést."""
    import math
    d = distortion(sl_points, tp_points, spread_points)
    if d != d:                           # nan → nincs mit eldönteni
        return False
    return d > float(max_distortion)


def cell_text(sl_points: float, tp_points: float,
              spread_points: float) -> str:
    """A dashboard cellája: a tényleges RR és a torzítás (`3.3:1 +64%`)."""
    import math
    eff = effective_rr(sl_points, tp_points, spread_points)
    d = distortion(sl_points, tp_points, spread_points)
    if eff != eff or d != d:
        return "—"
    if eff == float("inf"):
        return "∞"
    return f"{eff:.1f}:1 {d * 100:+.0f}%"

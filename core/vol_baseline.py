"""
A VOLATILITÁS-SZŰRŐ MÉRCÉJE — egy definíció a backtestnek, a viznek és az élnek.

A szűrő azt kérdezi: „szokatlanul csendes vagy kaotikus-e most ez az instrumentum?"
A válasz csak akkor jelent bármit, ha van mihez viszonyítani. Két mérce közül
lehet választani:

  `atr_avg_ref` (alap)   Az optimalizáláskor a TELJES betöltött előzményre
                         számolt EGY szám. Előnye: a backtest reprodukálható —
                         több letöltött előzmény nem billenti el az eredményt.
                         Hátránya: BEFAGY. Ha az instrumentum volatilitási
                         rezsimje elmozdul, a szűrő jelentése vele csúszik.

  `atr_baseline_bars`    Gördülő ablak (N gyertya). Követi a rezsimváltást, és
                         szintén reprodukálható: BÁROKBAN van definiálva, tehát
                         nem függ attól, mennyi előzményt töltöttél le.

⚠ MIÉRT KELLETT EZ (2026-08-08). A BTCUSD hetekig NÉMÁN nem kereskedett. A
mentett mérce 272,75 volt, a friss ATR-medián 140,19 — a BTC volatilitása a
felére esett. Az `atr_min_pct = 0,9` padló így a gyertyák 94%-át kizárta: a
30 nap alatt keletkezett 26 M1-jelből MIND a 26 elbukott a szűrőn, tehát a
charton egyetlen jelölő sem jelent meg, és élesben egyetlen kötés sem született.
A többi páron ez nem látszott (Ger40 1,00×, GOLD 0,97×, UsaTec 1,34×) — a BTC
volt az egyetlen, ahol rezsimváltás történt.

⚠ A GÖRDÜLŐ MÉRCE NEM AZ ALAPÉRTELMEZÉS. Megmérve (7 pár, 2026-07-01…08-07):
a BTCUSD 0 kötés helyett 5–8 kötést ad, de azok VESZTESÉGESEK (−11…−19$), és a
teljes portfólió eredménye zajszinten változik (+1053$ → +1050…+1103$). Nincs
mérési alapja az átkapcsolásnak — a mechanizmus rendelkezésre áll, a döntés a
felhasználóé, páronként.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def baseline_bars(params: dict) -> int:
    """A gördülő ablak hossza gyertyában. 0 = fix `atr_avg_ref` (alap)."""
    try:
        return max(0, int(params.get("atr_baseline_bars", 0) or 0))
    except (TypeError, ValueError):
        return 0


def series(atr: pd.Series, params: dict) -> pd.Series:
    """Bar-onkénti mérce az ATR-sorozathoz.

    ⚠ OK-OKOZATI: a `rolling` csak a MÚLTAT nézi (i−N+1 … i), tehát az i. bár
    mércéje az i. bár zárásakor már ismert — nincs look-ahead. A sorozat elején
    kevesebb az adat, ezért `min_periods` + visszatöltés: enélkül a warmup-szakasz
    NaN mércét adna, és a szűrő ott mindent átengedne (néma viselkedés-váltás)."""
    n = baseline_bars(params)
    if n <= 0:
        return pd.Series(float(atr.mean()), index=atr.index)
    return atr.rolling(n, min_periods=max(20, n // 8)).mean().bfill()


def value_at(atr_values, i: int, params: dict, fallback: float = 0.0) -> float:
    """Egyetlen bár mércéje tömbből (a viz replay-hez, ahol nincs DataFrame).
    Gördülő mércénél az `i` előtti N érték átlaga, különben a `fallback`."""
    n = baseline_bars(params)
    if n <= 0:
        return float(fallback)
    lo = max(0, i - n + 1)
    win = np.asarray(atr_values[lo:i + 1], dtype=float)
    win = win[np.isfinite(win)]
    if len(win) < max(20, n // 8):
        return float(fallback)
    return float(win.mean())


def effective(params: dict, row_atr_avg: float) -> float:
    """A ténylegesen érvényes mérce: gördülőnél a SOR értéke, különben a
    befagyasztott `atr_avg_ref` (tartalék a sor értéke, régi params-nál)."""
    if baseline_bars(params) > 0:
        return float(row_atr_avg or 0.0)
    return float(params.get("atr_avg_ref") or row_atr_avg or 0.0)


def band(params: dict, base: float) -> tuple:
    """`(alsó, felső)` engedett ATR-tartomány. 0 = az adott oldal kikapcsolva."""
    if not base or base <= 0:
        return (0.0, 0.0)
    return (base * float(params.get("atr_min_pct", 0.0) or 0.0),
            base * float(params.get("atr_max_pct", 0.0) or 0.0))


def status(atr: float, params: dict, base: float) -> dict:
    """`{"ok", "ratio", "lo", "hi", "why"}` — MIÉRT nem lépne be a motor.

    Ez a hiányzó láthatóság: a szűrő eddig csak akkor szólt, ha ÉPP volt jel
    (`live_trader` napló), tehát egy hetekig néma instrumentumról semmi nem
    árulkodott. Ez a függvény jel NÉLKÜL is megmondja az állapotot."""
    lo, hi = band(params, base)
    ratio = (float(atr) / base) if base else float("nan")
    if not base or base <= 0:
        return {"ok": True, "ratio": float("nan"), "lo": 0.0, "hi": 0.0,
                "why": "nincs mérce (a szűrő kikapcsolva)"}
    if lo > 0 and atr < lo:
        return {"ok": False, "ratio": ratio, "lo": lo, "hi": hi,
                "why": f"túl csendes: ATR {ratio:.2f}× a mércének "
                       f"(a padló {params.get('atr_min_pct')}×)"}
    if hi > 0 and atr > hi:
        return {"ok": False, "ratio": ratio, "lo": lo, "hi": hi,
                "why": f"túl kaotikus: ATR {ratio:.2f}× a mércének "
                       f"(a plafon {params.get('atr_max_pct')}×)"}
    return {"ok": True, "ratio": ratio, "lo": lo, "hi": hi, "why": ""}

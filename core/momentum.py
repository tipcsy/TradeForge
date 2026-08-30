"""
LENDÜLET — a piac „fordulatszáma": folytonos, ELŐJELES, normált mutató.

A metafora pontos: rálépsz a gázra → a mutató kileng → aztán visszaáll az
alapjáratra. A gyors átlag ilyenkor elszakad a lassútól, majd visszatér hozzá.
Ezt mérjük.

MIÉRT KELL, HA MÁR VAN `tf_align` ÉS `regime`. A három szomszédos, de mást mond:

    tf_align  több idősík SMA-IRÁNYA          → csak ELŐJEL, nagyság nincs
    regime    ADX/DI/ATR → 8 KATEGÓRIA        → címke, nem szám
    momentum  előjeles, normált SZÁM          → „mennyire pörög, merre"

Két mérési alap (a kapu ablakában választható):

  • `sma` — EGY idősík, HÁROM SMA (8/32/100). Két „fordulat” adódik
    (gyors↔közép, közép↔lassú), az átlaguk a mutató. Ez a legszorosabb
    megfelelője a fordulatszámmérőnek, és nem fed át a tf_align-nal (az több
    idősíkot néz, ez egyet).

  • `tf` — HÁROM idősík (alap: M1/M5/M15), idősíkonként ugyanaz az SMA.
    Idősíkonként (záróár − SMA), az átlaguk a mutató.

NORMÁLÁS. A nyers árkülönbség instrumentumonként mást jelent (GOLD 6.5 vs.
EURUSD 0.0008), ezért mindkét alap ugyanazzal a mércével oszt: az utolsó `n`
gyertya ÁTLAGOS ABSZOLÚT ZÁRÓÁR-ELMOZDULÁSA. Így egy 1.0-s érték mindkét
alapon, minden páron ugyanazt jelenti: „a gyors és a lassú átlag egy átlagos
gyertyányira van egymástól”.

MIÉRT NEM ATR. A `tf` alap idősíkjaihoz (M1/M5) ma CSAK záróár-csatorna van
(`mt5_connector.tf_closes`, ezen fut a tf_align is) — az ATR-hez high/low kellene,
vagyis új adatút. A záróár-alapú mérce mindkét alapon MEGEGYEZIK, tehát a
küszöb hordozható a kettő közt; ha ATR-t használnánk az egyiken, a másikon meg
nem, ugyanaz a szám mást jelentene. (A spread-kapu ATR-t használ — ott van
high/low, és ott a bróker spreadjéhez kell mérni, nem a gyertyák méretéhez.)

TISZTA modul: se MT5, se tkinter, se fájl — a hívó adja a záróár-sorozatokat.
"""

from __future__ import annotations
from core.i18n import LabelMap as _LabelMap, t as _t

import math

# Mérési alapok
BASIS_SMA = "sma"      # egy idősík, három SMA
BASIS_TF = "tf"        # három idősík, egy SMA

BASIS_LABEL = _LabelMap("momentum.basis", (BASIS_SMA, BASIS_TF))

DEFAULTS = {
    "basis": BASIS_SMA,
    "timeframe": 15,                 # a `sma` alap idősíkja (perc)
    "sma_fast": 8,
    "sma_mid": 32,
    "sma_slow": 100,
    "timeframes": [1, 5, 15],        # a `tf` alap idősíkjai
    "tf_sma": 50,
    "vol_window": 14,                # a normáló ablak (átlagos |Δzáróár|)
    "idle_threshold": 0.35,          # ez alatt „alapjárat”
}


def _mean(vals) -> float:
    vals = [v for v in vals if v is not None and not math.isnan(v)]
    return sum(vals) / len(vals) if vals else float("nan")


def _sma(closes, n: int) -> float:
    """Az UTOLSÓ `n` záróár átlaga. `nan`, ha nincs elég adat — a hívó ilyenkor
    nem dönt (a kapu `UNKNOWN`), nem pedig véletlenszerűen enged/blokkol."""
    if closes is None or n <= 0 or len(closes) < n:
        return float("nan")
    tail = list(closes)[-n:]
    return sum(float(c) for c in tail) / n


def vol_unit(closes, window: int) -> float:
    """A normáló mérce: az utolsó `window` gyertya ÁTLAGOS ABSZOLÚT záróár-
    elmozdulása. `nan`, ha nincs elég adat vagy a piac teljesen áll (0)."""
    if closes is None or len(closes) < window + 1 or window <= 0:
        return float("nan")
    tail = [float(c) for c in list(closes)[-(window + 1):]]
    deltas = [abs(tail[i] - tail[i - 1]) for i in range(1, len(tail))]
    unit = sum(deltas) / len(deltas) if deltas else 0.0
    return unit if unit > 0 else float("nan")


def rpm_sma(closes, params: dict = None) -> float:
    """`sma` alap: (gyors−közép) és (közép−lassú), a mércével osztva, átlagolva."""
    p = {**DEFAULTS, **(params or {})}
    unit = vol_unit(closes, int(p["vol_window"]))
    if math.isnan(unit):
        return float("nan")
    fast = _sma(closes, int(p["sma_fast"]))
    mid = _sma(closes, int(p["sma_mid"]))
    slow = _sma(closes, int(p["sma_slow"]))
    if math.isnan(fast) or math.isnan(mid) or math.isnan(slow):
        return float("nan")
    return _mean([(fast - mid) / unit, (mid - slow) / unit])


def rpm_tf(closes_by_tf: dict, timeframes, params: dict = None) -> float:
    """`tf` alap: idősíkonként (utolsó záróár − SMA) a mércével osztva, átlagolva.

    A hiányzó/rövid idősíkot KIHAGYJUK (nem nullázzuk): egy még be nem melegedett
    M5 különben lefelé húzná az átlagot, és „alapjáratot” hazudna."""
    p = {**DEFAULTS, **(params or {})}
    legs = []
    for tf in (timeframes or []):
        closes = (closes_by_tf or {}).get(tf)
        if closes is None or len(closes) < 2:
            continue
        unit = vol_unit(closes, int(p["vol_window"]))
        sma = _sma(closes, int(p["tf_sma"]))
        if math.isnan(unit) or math.isnan(sma):
            continue
        legs.append((float(list(closes)[-1]) - sma) / unit)
    return _mean(legs) if legs else float("nan")


def rpm(closes_by_tf: dict, params: dict = None) -> float:
    """A mutató a beállított mérési alap szerint. `nan` = nincs elég adat.

    `closes_by_tf`: `{perc: záróár-sorozat}` — a `sma` alap ebből a saját
    idősíkját veszi, a `tf` alap többet."""
    p = {**DEFAULTS, **(params or {})}
    if str(p["basis"]) == BASIS_TF:
        return rpm_tf(closes_by_tf, p.get("timeframes") or [], p)
    return rpm_sma((closes_by_tf or {}).get(int(p["timeframe"])), p)


def needed_timeframes(params: dict = None) -> list:
    """Mely idősíkok záróárai kellenek a méréshez (a hívó ennyit tölt)."""
    p = {**DEFAULTS, **(params or {})}
    if str(p["basis"]) == BASIS_TF:
        return [int(t) for t in (p.get("timeframes") or [])]
    return [int(p["timeframe"])]


def needed_bars(params: dict = None) -> int:
    """Hány gyertya kell idősíkonként (a leghosszabb ablak + a normáló + tartalék)."""
    p = {**DEFAULTS, **(params or {})}
    longest = (int(p["sma_slow"]) if str(p["basis"]) != BASIS_TF
               else int(p["tf_sma"]))
    return max(longest, int(p["vol_window"])) + int(p["vol_window"]) + 5


def direction(value: float) -> str:
    """`"BUY"` (felfelé pörög) | `"SELL"` (lefelé) | `""` (nem tudni)."""
    if value is None or math.isnan(value) or value == 0:
        return ""
    return "BUY" if value > 0 else "SELL"


def is_idle(value: float, params: dict = None) -> bool:
    """Alapjáraton van-e? (`nan` → NEM: adathiánynál nem szűrünk — fail-open,
    ugyanúgy, ahogy a spread-kapu is teszi.)"""
    p = {**DEFAULTS, **(params or {})}
    if value is None or math.isnan(value):
        return False
    return abs(float(value)) < float(p["idle_threshold"])


# ---------------------------------------------------------------------------
# BACKTEST: per-gyertya sorozat, LOOK-AHEAD nélkül
# ---------------------------------------------------------------------------
# Az él pillanatnyi értéket mér; a backtestnek minden döntési időponthoz kell egy
# érték. A csapda a szokásos: egy `t` pillanatban CSAK az addig LEZÁRT gyertyák
# ismertek. Ezért a sorozatot a gyertya ZÁRÁSI idejére indexeljük (nyitás + hossz),
# és a döntéskor `ffill`-lel az utolsó MÁR LEZÁRT értéket vesszük. Ha nyitási időre
# indexelnénk, a döntés a saját, még FORMÁLÓDÓ gyertyájának végleges záróárát
# látná — pontosan az a look-ahead, amit a `tf_align` kapunál is javítani kellett.


def _resample_closes(df_m1, minutes: int):
    """M1 → `minutes` perces ZÁRÓÁRAK, a gyertya ZÁRÁSI idejére indexelve."""
    import pandas as pd
    if df_m1 is None or len(df_m1) == 0:
        return None
    if minutes <= 1:
        s = df_m1["close"].copy()
    else:
        s = df_m1["close"].resample(f"{int(minutes)}min", label="left",
                                    closed="left").last().dropna()
    return s.set_axis(s.index + pd.Timedelta(minutes=int(minutes)))


def _rolling_rpm(closes, params: dict):
    """Egy idősík `rpm`-sorozata (a `rpm_sma`/`rpm_tf` képlet vektorosan)."""
    p = {**DEFAULTS, **(params or {})}
    w = int(p["vol_window"])
    unit = closes.diff().abs().rolling(w).mean()
    unit = unit.where(unit > 0)
    if str(p["basis"]) == BASIS_TF:
        return (closes - closes.rolling(int(p["tf_sma"])).mean()) / unit
    fast = closes.rolling(int(p["sma_fast"])).mean()
    mid = closes.rolling(int(p["sma_mid"])).mean()
    slow = closes.rolling(int(p["sma_slow"])).mean()
    return (((fast - mid) / unit) + ((mid - slow) / unit)) / 2.0


def series_at(df_m1, decision_index, params: dict = None):
    """A fordulat értéke MINDEN döntési időpontra — a backtest kapujához.

    `df_m1`: M1 OHLC, idő-indexszel. `decision_index`: a döntési időpontok
    (a backtest M15 gyertya-idői). Visszaad: `pd.Series` ugyanezzel az indexszel;
    `NaN` ott, ahol még nincs elég lezárt gyertya (ilyenkor a kapu nem szűr).

    A `tf` alap idősíkjait (M1/M5/M15) M1-ből RESAMPLE-eljük: a backtest-adatban
    nincs natív M5. Az aggregált gyertyák ugyanazok, csak nem a brókertől jönnek —
    a különbség elhanyagolható, és így nem kell új adatcsatorna a backtesthez."""
    import pandas as pd
    p = {**DEFAULTS, **(params or {})}
    idx = pd.DatetimeIndex(decision_index)
    legs = []
    for tf in needed_timeframes(p):
        closes = _resample_closes(df_m1, tf)
        if closes is None or len(closes) < 3:
            continue
        ser = _rolling_rpm(closes, p)
        # `ffill`: az utolsó MÁR LEZÁRT gyertya értéke. A `reindex` a záráshoz
        # igazít, tehát a döntés sosem lát a saját gyertyájába.
        legs.append(ser.reindex(ser.index.union(idx)).ffill().reindex(idx))
    if not legs:
        return pd.Series([float("nan")] * len(idx), index=idx)
    return pd.concat(legs, axis=1).mean(axis=1, skipna=True)


def failed(value: float, signal: str, mode: str, params: dict = None) -> bool:
    """Bukik-e a kapu EGY konkrét belépő-kísérletre? (él és backtest KÖZÖS ága)

    `mode`: `"idle"` | `"dir"` | `"both"`. Adathiánynál (`nan`) nem szűrünk —
    fail-open, mint a spread-kapunál."""
    if value is None or math.isnan(value):
        return False
    if mode in ("idle", "both") and is_idle(value, params):
        return True
    if mode in ("dir", "both"):
        d = direction(value)
        if d and signal in ("BUY", "SELL") and d != signal:
            return True
    return False


def cell_text(value: float) -> str:
    """A dashboard `Lendület` cellája: nyíl + a fordulat nagysága."""
    if value is None or math.isnan(value):
        return "—"
    arrow = "↑" if value > 0 else ("↓" if value < 0 else "·")
    return f"{arrow}{abs(value):.2f}"

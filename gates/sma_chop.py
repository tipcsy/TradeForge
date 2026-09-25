"""
SMA-OLDALAZÁS — „az utolsó 20 gyertyában átütötte-e az ár az SMA-t?"

Trendben az ár az SMA EGYIK oldalán halad. Ha a közelmúltban többször is
átment a másik oldalra, a piac oldalaz: az SMA-irány ilyenkor zaj, és egy
trendkövető belépő (pl. a wpr_sma) véletlenszerű irányba lép be.

A SZABÁLY (a felhasználó definíciója, 2026-09-25):

    Az utolsó `lookback` LEZÁRT gyertyában hányszor váltott oldalt a záróár az
    SMA-hoz képest? Ha többször, mint `max_crosses` → oldalazás → a kapu bukik.

    Alap: M1, SMA(50), 20 gyertya, `max_crosses = 0` (egyetlen átütés is elég).

Az átütés = két EGYMÁST KÖVETŐ gyertya záróára az SMA KÜLÖNBÖZŐ oldalán van.
Pontosan az SMA-n záró gyertya nem vált oldalt (az előző oldalát örökli) — így
egy érintés nem számít kétszer.

⚠ A FELHASZNÁLÓ EMLÉKEZETE SZERINT „EZT MÁR CSINÁLTUK EGY INDIKÁTORRAL”. A kódban
és a jegyzetekben nem találtuk (2026-09-25). A legközelebbi meglévő a Lendület-
kapu „alapjárata”, ami viszont a gyors és a lassú SMA TÁVOLSÁGÁT méri, nem az
átütéseket — ezért ez önálló kapu lett.

⚠ IRÁNYTÓL FÜGGETLEN: ugyanúgy blokkol BUY-t és SELL-t. Jelzés-fázisú (a terv
előtt dönt), a célárhoz nincs köze.

TISZTA modul: a `ctx.bars` hozza a gyertyákat, itt csak számolunk.
"""

from __future__ import annotations

from core.i18n import t as _t

KEY = "sma_chop"

DEFAULTS = {
    "timeframe": 1,        # perc — a felhasználó döntése: M1
    "sma_period": 50,
    "lookback": 20,
    "max_crosses": 0,      # ennyi átütés még belefér; 0 = egy is blokkol
}

_TFS = (1, 5, 15, 30, 60)

GATE = {"key": KEY, "default_effect": "none", "phase": "signal"}

PARAMS = (
    {"key": "timeframe", "kind": "choice", "default": DEFAULTS["timeframe"],
     "choices": lambda: [(m, f"M{m}" if m < 60 else "H1") for m in _TFS]},
    {"key": "sma_period", "kind": "int", "default": DEFAULTS["sma_period"],
     "lo": 2, "hi": 2000},
    {"key": "lookback", "kind": "int", "default": DEFAULTS["lookback"],
     "lo": 2, "hi": 1000},
    {"key": "max_crosses", "kind": "int", "default": DEFAULTS["max_crosses"],
     "lo": 0, "hi": 100},
)


def params_of(pair_cfg: dict | None, cfg: dict | None) -> dict:
    """`pairs.<SYM>.sma_chop` → `sma_chop` → `DEFAULTS`."""
    p = dict(DEFAULTS)
    for forras in ((cfg or {}).get(KEY), (pair_cfg or {}).get(KEY)):
        if isinstance(forras, dict):
            for k in DEFAULTS:
                if forras.get(k) is not None:
                    p[k] = forras[k]
    try:
        p["timeframe"] = int(p["timeframe"])
        if p["timeframe"] not in _TFS:
            p["timeframe"] = DEFAULTS["timeframe"]
        p["sma_period"] = max(2, int(p["sma_period"]))
        p["lookback"] = max(1, int(p["lookback"]))
        p["max_crosses"] = max(0, int(p["max_crosses"]))
    except (TypeError, ValueError):
        p = dict(DEFAULTS)
    return p


def crosses(closes, sma_period: int, lookback: int):
    """Az SMA-átütések száma az utolsó `lookback` gyertyában — vagy `None`, ha
    nincs elég adat (a kapu ilyenkor fail-open).

    Kell hozzá `sma_period + lookback` záróár: az első `lookback` gyertya
    ELŐTTI gyertya oldala is számít (onnan „jön át” az első)."""
    import numpy as np
    c = np.asarray(closes, dtype=float)
    need = int(sma_period) + int(lookback)
    if len(c) < need or not np.isfinite(c[-need:]).all():
        return None
    c = c[-need:]
    kum = np.cumsum(np.insert(c, 0, 0.0))
    sma = (kum[sma_period:] - kum[:-sma_period]) / sma_period   # len = lookback+1
    diff = c[sma_period - 1:] - sma
    oldal = np.sign(diff)
    # Az SMA-n záró gyertya az előző oldalát örökli (egy érintés ≠ két átütés).
    for i in range(1, len(oldal)):
        if oldal[i] == 0:
            oldal[i] = oldal[i - 1]
    oldal = oldal[oldal != 0]
    return int((oldal[1:] != oldal[:-1]).sum())


def _measure_raw(ctx) -> tuple:
    P = params_of(getattr(ctx, "pair_cfg", None), getattr(ctx, "cfg", None))
    df = ctx.bars(P["timeframe"], P["sma_period"] + P["lookback"])
    if df is None or not len(df):
        return False, None, P
    n = crosses(df["close"].to_numpy(), P["sma_period"], P["lookback"])
    if n is None:
        return False, None, P
    return n > P["max_crosses"], n, P


def measure(ctx) -> tuple:
    """`(bukott_e, None)` — sáv-szintet nem adunk (a sávok a kapu saját
    küszöbének %-ában mérnek; egy darabszám-küszöb 0-nál ezt nem értelmezi)."""
    f, _n, _P = _measure_raw(ctx)
    return f, None


def block_log(ctx) -> str:
    f, n, P = _measure_raw(ctx)
    if n is None:
        return _t("gate.blocked_by", gate=_t(f"gate.name.{KEY}"))
    return _t("sma_chop.blocked", n=n, lookback=P["lookback"],
              period=P["sma_period"],
              tf=f"M{P['timeframe']}" if P["timeframe"] < 60 else "H1",
              max=P["max_crosses"])


def cell_text(ctx: dict) -> str:
    """A dashboard-cella: a beállítás röviden (`≤0×20`)."""
    P = params_of((ctx or {}).get("pair_cfg"), None)
    return f"≤{P['max_crosses']}×{P['lookback']}"


def evaluate(ctx: dict) -> tuple:
    """A dashboard-sor állapota. A sorban nincs gyertya-bemenet, ezért csak a
    beállítást írjuk ki; a döntés a belépő pillanatában születik."""
    from core.gates import UNKNOWN
    return UNKNOWN, _t("sma_chop.only_at_entry")

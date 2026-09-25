"""
CÉLÁR-ELÉRÉS — reális-e a célár? „Járt-e már ott az ár a közelmúltban?"

A célár eddig csak egy SZORZÓ volt (`tp_rr_ratio × stop`): azt mondta meg,
hány R-re van, azt nem, hogy a piac a közelmúltban mozgott-e egyáltalán
ennyit. Ez a kapu ezt kérdezi meg — MINDEN stratégiára egyformán, mert a kész
belépő-tervből (`sl_points`/`tp_points`) dolgozik, nem a stratégia belsejéből.

A SZABÁLY (a felhasználó definíciója, 2026-09-25):

    BUY:  az utolsó `lookback` lezárt gyertya LEGMAGASABB high-ja elérte-e a
          belépő + `reach_pct` × célár-távolság szintet?
    SELL: tükörkép — a LEGALACSONYABB low elérte-e a belépő − … szintet?

    Ha nem → a célár nem reális → a kapu bukik.

A `reach_pct` a „megengedőbb” rész: nem a teljes célár-távolságot várjuk el,
csak annak 60–80%-át (alap 0,7). A belépő referenciája a döntést hozó (lezárt)
gyertya záróára — ugyanaz az ár, amin a backtest belép.

⚠ MIT JELENT A GYAKORLATBAN. BUY-nál a feltétel azt kéri, hogy az ár a
közelmúltban MAGASABBAN járt, mint ahol most belép — vagyis egy visszahúzódás
utáni belépőt enged. A wpr_sma pont ilyen (trend + WPR-visszaesés), ezért
ott a kapu a „visszaesés mélysége ≥ a célár 70%-a” feltételként is olvasható.

⚠ AZ IDŐABLAK A CÉLÁRHOZ MÉRENDŐ. Az alapbeállítás (M1, 22 gyertya = 22 perc)
a felhasználó döntése; a célár viszont jellemzően több M15-ATR. Rövid ablaknál
a kapu sokat blokkol — ezt a bevezetéskor MÉRTÜK, lásd a kapu leírását.

⚠ A TÁVOLI CÉLÁR (`tp_rr_ratio` 15 = „nincs célár”) mellett a kapu szinte
mindig bukik. Ilyen készleten a hatás legyen `none`.

TISZTA modul: se MT5, se config-írás — a `ctx.bars` hozza a gyertyákat.
"""

from __future__ import annotations

from core.i18n import t as _t

KEY = "target_reach"

DEFAULTS = {
    "timeframe": 1,        # perc — a felhasználó döntése: M1
    "lookback": 22,        # ennyi LEZÁRT gyertyát nézünk vissza
    "reach_pct": 0.7,      # a célár-távolság ennyi részét kell elérnie (0,6–0,8)
}

_TFS = (1, 5, 15, 30, 60)

GATE = {"key": KEY, "default_effect": "none", "phase": "plan"}

# ⚠ SIMA ADAT (nem `ParamSpec`) — a kapu így nem importálja a keretet, és egy
# darabban csomagolható (`.tfg`). A feliratok: `gp.target_reach.<kulcs>.*`.
PARAMS = (
    {"key": "timeframe", "kind": "choice", "default": DEFAULTS["timeframe"],
     "choices": lambda: [(m, f"M{m}" if m < 60 else "H1") for m in _TFS]},
    {"key": "lookback", "kind": "int", "default": DEFAULTS["lookback"],
     "lo": 2, "hi": 1000},
    {"key": "reach_pct", "kind": "float", "default": DEFAULTS["reach_pct"],
     "lo": 0.05, "hi": 2.0},
)


def params_of(pair_cfg: dict | None, cfg: dict | None) -> dict:
    """`pairs.<SYM>.target_reach` → `target_reach` → `DEFAULTS` (ugyanaz a
    lánc, ahova a kapu ablaka ment — `dashboard.gate_dialog._plug_store`)."""
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
        p["lookback"] = max(1, int(p["lookback"]))
        p["reach_pct"] = float(p["reach_pct"])
    except (TypeError, ValueError):
        p = dict(DEFAULTS)
    return p


def check(signal: str, entry: float, tp_dist: float, highs, lows,
          reach_pct: float) -> tuple:
    """`(bukott_e, elért_arány)` — TISZTA függvény, a teszt ezen megy.

    `tp_dist`: a célár távolsága ÁRBAN. `elért_arány`: a közelmúlt legjobb
    kilengése a célár-távolsághoz képest (1,0 = pont a célárig ért). Rossz
    bemenetnél `(False, None)` — fail-open."""
    try:
        entry, tp_dist, reach_pct = float(entry), float(tp_dist), float(reach_pct)
    except (TypeError, ValueError):
        return False, None
    if not (tp_dist > 0) or signal not in ("BUY", "SELL"):
        return False, None
    if signal == "BUY":
        best = max(float(h) for h in highs) - entry
    else:
        best = entry - min(float(x) for x in lows)
    frac = best / tp_dist
    return frac < reach_pct, frac


def _measure_raw(ctx) -> tuple:
    """`(bukott_e, elért_arány, paraméterek)` — a `measure` és a `block_log` közös
    magja, hogy a naplóban ugyanaz a szám álljon, amiből a döntés született."""
    P = params_of(getattr(ctx, "pair_cfg", None), getattr(ctx, "cfg", None))
    sig = getattr(ctx, "signal", "NONE")
    tp = getattr(ctx, "tp_points", None)
    pt = float((getattr(ctx, "pair_cfg", None) or {}).get("point_size") or 0.0)
    if sig not in ("BUY", "SELL") or not tp or not (pt > 0):
        return False, None, P
    df = ctx.bars(P["timeframe"], P["lookback"])
    if df is None or not len(df):
        return False, None, P                     # nincs adat → fail-open
    f, frac = check(sig, float(df["close"].iloc[-1]), float(tp) * pt,
                    df["high"].to_numpy(), df["low"].to_numpy(), P["reach_pct"])
    return f, frac, P


def measure(ctx) -> tuple:
    """`(bukott_e, None)` — a keret szerződése. (Sáv-szintet nem adunk: a kapu
    „kevés” irányban bukik, a sávok skálája a „sok” irányra épül.)"""
    f, _frac, _P = _measure_raw(ctx)
    return f, None


def block_log(ctx) -> str:
    """A napló mondata: mennyit ért el a közelmúlt, és mennyi kellett volna."""
    f, frac, P = _measure_raw(ctx)
    if frac is None:
        return _t("gate.blocked_by", gate=_t(f"gate.name.{KEY}"))
    return _t("target_reach.blocked", got=f"{frac * 100:.0f}",
              need=f"{P['reach_pct'] * 100:.0f}", n=P["lookback"],
              tf=f"M{P['timeframe']}" if P["timeframe"] < 60 else "H1")


def cell_text(ctx: dict) -> str:
    """A dashboard-cella: a beállítás röviden (`70%·22`)."""
    P = params_of((ctx or {}).get("pair_cfg"), None)
    return f"{P['reach_pct'] * 100:.0f}%·{P['lookback']}"


def evaluate(ctx: dict) -> tuple:
    """A dashboard-sor állapota. ⚠ A kapu CSAK a belépő pillanatában mér (kell
    hozzá a kész célár); a sorban ezért nem állítunk semmit, csak kiírjuk."""
    from core.gates import UNKNOWN
    return UNKNOWN, _t("target_reach.only_at_entry")

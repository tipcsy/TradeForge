"""VÁRT AKTIVITÁS — mit ígért a mentett optimalizálás, és mit teljesít élesben.

⚠ MIÉRT EZ A HARMADIK DARAB. A telemetria megmondja, MI akadályozta a belépőt; a
`metrics` megmondja, hogyan teljesít a cella. Egyik sem veszi észre a
LEGGYAKORIBB néma bajt: hogy egy cella **elszáradt** — nem blokkolja semmi, nem
is veszít, egyszerűen nem köt. Ehhez kell egy VÁRAKOZÁS, amihez mérni lehet.

── HONNAN A VÁRAKOZÁS ─────────────────────────────────────────────────────
A mentett optimalizálási eredményből (`data/optimized_params/<strategia>/<SYM>.json`,
`test_summary`) — abból az OUT-OF-SAMPLE ablakból, amit az optimalizáló a
`optimizer.test_start_date`-től a futás napjáig mért. A kötés/nap tehát:

    test_summary.trades / (optimized_at − test_start_date)

⚠ AZ ABLAK HOSSZÁT MI SZÁMOLJUK, mert a mentett fájl nem tárolja. Ha az
`optimized_at` hiányzik, a MAI napig számolunk — ilyenkor az ablak HOSSZABB a
valódinál, tehát a várakozás ALACSONYABB. Ez a biztonságos irány: inkább ne
kiáltsunk elszáradást ott, ahol csak a metaadat hiányzik.

── ⚠ AMIT SOSEM HASONLÍTUNK ÖSSZE: A PÉNZT ──────────────────────────────
A backtest P&L-je NEM vethető össze az élő P&L-lel abszolút értékben: a méretezés
az AKKORI egyenleghez és kockázat-százalékhoz igazodott, az élő pedig a maihoz —
ugyanaz a stratégia ugyanazon a jelen más dollárt hoz. Ezért az eltérést csak
ARÁNYOKON és RÁTÁKON mérjük (kötés/nap, profit factor, találati arány). Egy
„a backtest 1200 $-t ígért, élesben 300 $ lett" mondat magában semmit nem
bizonyít — és pont ilyen mondatokból születnek rossz döntések.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)


def _ts(v):
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def saved(symbol: str, strategy: str) -> dict:
    """A mentett optimalizálási eredmény NYERSEN (üres dict, ha nincs).

    ⚠ NEM DOB: egy sérült vagy hiányzó fájl a karmester mérését nem viheti el —
    de naplózza, mert az üres eredmény különben „még nincs optimalizálva"-nak
    látszana, holott a fájl OTT VAN, csak olvashatatlan."""
    try:
        from core.params_store import params_file
        ut = params_file(symbol, strategy)
        if not ut.exists():
            return {}
        with open(ut, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception as ex:
        log.warning("conductor.expectation: %s/%s — a mentett eredmény nem "
                    "olvasható: %s", symbol, strategy, ex)
        return {}


def expected(symbol: str, strategy: str, cfg: dict, now=None) -> dict:
    """A cella VÁRAKOZÁSA a mentett out-of-sample mérésből.

    Visszaad: `{trades, window_days, trades_per_day, profit_factor, win_rate,
    optimized_at, source}`. `source`: `"saved"` | `""` (nincs mentett eredmény).
    """
    ki = {"trades": 0, "window_days": 0, "trades_per_day": None,
          "profit_factor": None, "win_rate": None, "optimized_at": None,
          "source": ""}
    d = saved(symbol, strategy)
    ts = (d or {}).get("test_summary") or {}
    if not ts:
        return ki

    ki["source"] = "saved"
    ki["trades"] = int(ts.get("trades") or 0)
    ki["profit_factor"] = ts.get("profit_factor")
    ki["win_rate"] = ts.get("win_rate")
    ki["optimized_at"] = d.get("optimized_at")

    kezd = _ts(((cfg or {}).get("optimizer") or {}).get("test_start_date"))
    veg = _ts(d.get("optimized_at")) or (now or datetime.now(timezone.utc))
    if kezd and veg > kezd:
        napok = max(1, int((veg - kezd).total_seconds() // 86400))
        ki["window_days"] = napok
        ki["trades_per_day"] = round(ki["trades"] / napok, 4)
    return ki


def divergence(live: dict, exp: dict) -> dict:
    """ÉLŐ ↔ VÁRT eltérés — arányokon, sosem pénzben.

    * `activity_ratio`: élő kötés/nap ÷ várt kötés/nap. `1.0` = ahogy ígérte,
      `0.0` = elszáradt, `None` = nincs mihez mérni.
    * `pf_delta`, `win_rate_delta`: élő − várt (`None`, ha bármelyik hiányzik;
      a PF `None` is lehet, ha nem volt veszteséges kötés — lásd `metrics`).
    * `enough`: van-e elég élő kötés ahhoz, hogy az eltérésnek JELENTÉSE legyen.
      ⚠ ENÉLKÜL AZ EGÉSZ FÉLREVEZET: három kötésből számolt PF-eltérés zaj, és
      épp az ilyen számokból lesz elhamarkodott visszaminősítés."""
    from conductor.metrics import CONFIDENCE_TRADES

    live = live or {}
    exp = exp or {}
    ki = {"activity_ratio": None, "pf_delta": None, "win_rate_delta": None,
          "enough": bool(int(live.get("trades") or 0) >= CONFIDENCE_TRADES)}

    e_tpd = exp.get("trades_per_day")
    l_tpd = live.get("trades_per_day")
    if e_tpd is not None and l_tpd is not None and e_tpd > 0:
        ki["activity_ratio"] = round(l_tpd / e_tpd, 3)

    for kulcs, mezo in (("pf_delta", "profit_factor"),
                        ("win_rate_delta", "win_rate")):
        a, b = live.get(mezo), exp.get(mezo)
        if a is not None and b is not None:
            ki[kulcs] = round(float(a) - float(b), 4)
    return ki

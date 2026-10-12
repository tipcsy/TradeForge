"""A Piac-kapu hordozható: az osztályozó a KAPUÉ, nem az instrumentumé.

Tibi (2026-10-12): „ha a piac kapu fent van, akkor minden instrumentumnál
jelenjen meg a piaci állapot, és majd a kapu eldönti, hogy hogyan kezelje az
instrumentumot (tehát instrumentum oldalról vegyük ki a beállítását!)". Előtte
a kapu csak ott mért, ahol a párra `market_strategy` volt kiválasztva — a GOLD
`wpr_sma: block` beállítása így hetekig NÉMÁN semmit nem csinált.

⚠ A valódi config.json-t nem olvassa és nem írja.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                         # noqa: E402
applog.harden_console()

import numpy as np                                               # noqa: E402
import pandas as pd                                              # noqa: E402

from core import gates as G, market_strategy as MS               # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ── osztályozó-feloldás ──────────────────────────────────────────────────
ures = {"pairs": {"GOLD": {}}}
check("alapból MINDEN páron van osztályozó (regime)",
      G.market_classifier(ures, "GOLD") == "regime")
check("...ismeretlen páron is (nincs pár-blokk)", G.market_classifier({}, "XYZ") == "regime")
check("a régi instrumentum-kulcs NEM kapcsolja ki",
      G.market_classifier({"pairs": {"GOLD": {"market_strategy": "none"}}}, "GOLD") == "regime")
check("a kapu globális beállítása kikapcsolhatja",
      G.market_classifier({"gates": {"market": {"classifier": "none"}}}, "GOLD") is None)
check("páronkénti felülírás a kapu SAJÁT blokkjában",
      G.market_classifier({"gates": {"market": {"classifier": "none"}},
                           "pairs": {"GOLD": {"gates": {"market": {"classifier": "regime"}}}}},
                          "GOLD") == "regime")
check("elgépelt osztályozó → None (nem talál ki valamit)",
      G.market_classifier({"gates": {"market": {"classifier": "regim"}}}, "GOLD") is None)
check("MS.name_for ugyanazt adja", MS.name_for(ures, "GOLD") == "regime")

# ── chart-sáv ─────────────────────────────────────────────────────────────
check("a chart-sáv alapból KI", G.market_viz(ures, "GOLD") is False)
check("...a régi `market_viz` kulcs nem kapcsolja be",
      G.market_viz({"pairs": {"GOLD": {"market_viz": True}}}, "GOLD") is False)
check("...a kapu `viz`-e igen",
      G.market_viz({"pairs": {"GOLD": {"gates": {"market": {"viz": True}}}}}, "GOLD") is True)

# ── a kapu mérési kulcsai nem keverednek a stratégia-hatással ────────────
_c = {"pairs": {"GOLD": {"gates": {"market": {"classifier": "regime", "viz": True,
                                              "wpr_sma": "block"}}}}}
check("a `classifier`/`viz` mellett a stratégia hatása érintetlen",
      G.effect_for(_c, "GOLD", "wpr_sma", G.MARKET) == "block")

# ── backtest: instrumentum-kulcs nélkül is van besorolás-sorozat ─────────
from trading import backtest as BT                               # noqa: E402
n = 400
idx = pd.date_range("2026-01-01", periods=n, freq="15min")
cl = 100 + np.cumsum(np.random.default_rng(1).normal(0, 0.3, n))
m15 = pd.DataFrame({"open": cl, "high": cl + 0.4, "low": cl - 0.4, "close": cl,
                    "tick_volume": 1}, index=idx)
_cfg = {"pairs": {"GOLD": {"strategies": ["wpr_sma"],
                           "gates": {"market": {"wpr_sma": "block"}}}}}
s = BT._pair_market_series(_cfg, "GOLD", "wpr_sma", m15, True)
check("backtest: `market_strategy` NÉLKÜL is mér a bekapcsolt kapu",
      s is not None and len(s) == n, None if s is None else len(s))

# ── kijelzés-gyorsítótár: azonos gyertyára nem számol újra ───────────────
a = MS.latest_category("regime", m15)
b = MS.latest_category("regime", m15)
check("a legutóbbi besorolás stabil és gyorsítótárazott", a == b and a is not None, a)

print(f"\n{sum(results)}/{len(results)} PASS")
sys.exit(0 if all(results) else 1)

"""A kapu-HATÁS bekötve a MOTORBA (v1.97.0) — él + backtest + portfólió.

A LELET (2026-08-04, a „Program működése" ábra ellenőrzésekor): a `core/gates.py`
három hatást ismer — `blokkol` / `kockázatcsökkentés` / `ki` —, per
(pár × stratégia × kapu), és a felületen v1.92.0 óta ÁLLÍTHATÓ. **De a motor nem
olvasta:** a `gates` modult CSAK a `dashboard/row_source.py` és a beállító ablak
importálta. Élesben minden bekapcsolt kapu KEMÉNY BLOKK volt, a `reduce` pedig
puszta kijelzés (a jelzés-cella narancs kerete).

Ráadásul a „Piac" kapu egyáltalán nem létezett a belépő-feltételben — a
`market_strategy` csak a `Piac` oszlopot és a chart-sávot töltötte.

AMIT ITT ORZUNK:
  1. az ALAPÉRTELMEZÉS a mai viselkedés (spread blokkol, tf a legacy lista
     szerint, piac semmit) — a bekötés önmagában NEM változtat semmit;
  2. a `reduce` tényleg KISEBB MÉRETET ad (nem blokkol, nem hagy figyelmen kívül);
  3. a `none` tényleg KIKAPCSOL (a mérés sem számít);
  4. a döntés EGY helyen születik — a három motor ugyanazt a `decide`-ot hívja.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from core import gates as g


# ══ 1. Az ALAPÉRTELMEZÉS = a mai viselkedés ══════════════════════════════
# Ha ez elromlik, a bekötés NÉMÁN megváltoztatja az élő kereskedést.
_empty = {}
check("spread alapból BLOKKOL (mint eddig)",
      g.effect_for(_empty, "GOLD", "wpr_sma", g.SPREAD) == g.EFFECT_BLOCK)
check("piac alapból SEMMIT nem tesz (eddig sem volt kapu)",
      g.effect_for(_empty, "GOLD", "wpr_sma", g.MARKET) == g.EFFECT_NONE)
# A tf_align a RÉGI `gate` listából örököl — a meglévő configok tovább élnek.
_legacy = {"tf_align": {"enabled": True, "gate": ["wpr_sma"]}}
check("tf_align: a legacy `gate` lista → a listázott stratégiát BLOKKOLJA",
      g.effect_for(_legacy, "GOLD", "wpr_sma", g.TF_ALIGN) == g.EFFECT_BLOCK)
check("...a nem listázottat NEM",
      g.effect_for(_legacy, "GOLD", "ml_ai", g.TF_ALIGN) == g.EFFECT_NONE)


# ══ 2. A döntés: blokkol / csökkent / ki ═════════════════════════════════
ALL_BLOCK = {k: g.EFFECT_BLOCK for k in g.KEYS}
ALL_NONE = {k: g.EFFECT_NONE for k in g.KEYS}

d = g.decide({g.SPREAD: True}, ALL_BLOCK)
check("blokkoló kapu bukása → BLOKK", d["blocked"] == [g.SPREAD] and d["risk_factor"] == 1.0,
      str(d))
d = g.decide({g.SPREAD: True}, {**ALL_BLOCK, g.SPREAD: g.EFFECT_REDUCE})
check("kockázatcsökkentő kapu bukása → NINCS blokk, DE kisebb méret",
      not d["blocked"] and d["reduced"] == [g.SPREAD]
      and d["risk_factor"] == g.REDUCE_RISK_FACTOR, str(d))
d = g.decide({g.SPREAD: True, g.TF_ALIGN: True}, ALL_NONE)
check("`ki` hatásnál a bukás SEM számít", not d["blocked"] and not d["reduced"])
d = g.decide({}, ALL_BLOCK)
check("semmi nem bukott → szabad az út", not d["blocked"] and d["risk_factor"] == 1.0)

# Több kockázatcsökkentő kapu NEM szorzódik: a felezés felezés marad.
d = g.decide({k: True for k in g.KEYS}, {k: g.EFFECT_REDUCE for k in g.KEYS})
check("HÁROM csökkentő kapu sem visz 1/8-ra (a felezés felezés marad)",
      d["risk_factor"] == g.REDUCE_RISK_FACTOR, str(d["risk_factor"]))

# Blokk + csökkentés együtt: a blokk erősebb.
d = g.decide({g.SPREAD: True, g.MARKET: True},
             {**ALL_BLOCK, g.MARKET: g.EFFECT_REDUCE})
check("blokk + csökkentés → a BLOKK nyer (nincs belépő)", bool(d["blocked"]))

check("az `active` megmondja, kell-e egyáltalán MÉRNI",
      g.active(ALL_BLOCK, g.SPREAD) and not g.active(ALL_NONE, g.SPREAD))
check("a blokkolás INDOKA emberi szöveg",
      "Spread" in g.block_reason(g.decide({g.SPREAD: True}, ALL_BLOCK)),
      g.block_reason(g.decide({g.SPREAD: True}, ALL_BLOCK)))


# ══ 3. A piac-kapu „kedvezőtlen" halmaza CONFIGBÓL ═══════════════════════
check("alapból a dead/uncertain számít kedvezőtlennek",
      g.market_adverse({}, "GOLD") == {"dead", "uncertain"},
      str(g.market_adverse({}, "GOLD")))
_cfg = {"gates": {"market": {"adverse": ["ranging"]}}}
check("globálisan felülírható", g.market_adverse(_cfg, "GOLD") == {"ranging"})
_cfg2 = {"gates": {"market": {"adverse": ["ranging"]}},
         "pairs": {"GOLD": {"gates": {"market": {"adverse": ["dead"]}}}}}
check("a PÁR felülírása nyer", g.market_adverse(_cfg2, "GOLD") == {"dead"})
check("...a többi páron marad a globális",
      g.market_adverse(_cfg2, "EURUSD") == {"ranging"})


# ══ 4. VISELKEDÉS: a backtest tényleg KISEBB mérettel lép be ═════════════
# A `reduce` nem lehet puszta felirat — a lotnak csökkennie kell.
import pandas as pd
from trading import backtest as bt


def _run(market_effect):
    """Egy minimál backtest, ahol a PIAC-kapu bukik (a besorolás 'dead')."""
    idx1 = pd.date_range("2025-03-03 08:00", periods=400, freq="1min", tz="UTC")
    idx15 = pd.date_range("2025-03-03 08:00", periods=40, freq="15min", tz="UTC")
    m1 = pd.DataFrame({"open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0,
                       "avg_spread": 0.01, "close_spread": 0.01}, index=idx1)
    m15 = pd.DataFrame({"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0},
                       index=idx15)

    class S:
        name = "wpr_sma"
        default_sl_method = "atr"

        def timeframes(self):
            from strategy.base import Timeframe
            return [Timeframe("M15", 15), Timeframe("M1", 1)]

        def bt_indicators(self, hi, lo, p):
            hi = hi.copy(); hi["atr"] = 1.0
            return hi, lo

        def bt_warmup(self, p, tf):
            return 0

        def bt_new_state(self, sym):
            return {}

        def bt_on_high_close(self, st, row, p):
            return st

        def bt_on_low_close(self, st, prev, row, p):
            # EGYETLEN belépő a 100. báron
            return "BUY" if row.name == idx1[100] else "NONE"

        def bt_entry(self, row, p, ps):
            return (100.0, 200.0)

    cfg = {"pairs": {"T": {"market_strategy": "regime"}},
           "gates": {"market": {"default": market_effect,
                                "adverse": ["dead", "uncertain", "ranging",
                                            "clean_bull", "clean_bear",
                                            "volatile_bull", "volatile_bear",
                                            "transition", "uncategorized"]},
                     "spread": {"default": "none"},
                     "tf_align": {"default": "none"}}}
    pair_cfg = {"point_size": 0.01, "pv1_point": 1.0, "min_lot": 0.01,
                "lot_step": 0.01, "backtest_spread_points": 1.0,
                "market_strategy": "regime"}
    res = bt.run_pair("T", m15, m1, {}, pair_cfg,
                      {"account_risk_pct": 0.02, "max_open_slots": 1},
                      10000.0, strategy=S(), cfg=cfg, exec_gates=True)
    return res


_none = _run("none")
_red = _run("reduce")
_blk = _run("block")
_lot_none = _none.trades[0].lot if _none.trades else None
_lot_red = _red.trades[0].lot if _red.trades else None
check("kapu KI → van belépő", _lot_none is not None, str(_lot_none))
check("`reduce` → VAN belépő (nem blokkol)", _lot_red is not None, str(_lot_red))
check("...de KISEBB lottal", (_lot_none and _lot_red and _lot_red < _lot_none),
      f"{_lot_none} -> {_lot_red}")
check("...méghozzá a felezéssel",
      _lot_none and _lot_red and abs(_lot_red - _lot_none * g.REDUCE_RISK_FACTOR) < 1e-6,
      f"{_lot_red} vs {_lot_none * g.REDUCE_RISK_FACTOR}")
check("`block` → NINCS belépő", not _blk.trades, str(len(_blk.trades)))


# ══ 5. MIND A HÁROM motor a KÖZÖS döntést hívja ══════════════════════════
live_src = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
bt_src = (ROOT / "trading" / "backtest.py").read_text(encoding="utf-8")
check("az ÉLŐ motor hívja a gates.decide-ot", "_gates.decide(" in live_src)
check("a run_pair hívja", bt_src.count("_gt.decide(") >= 1)
check("a portfólió-backtest is hívja", bt_src.count("_gt.decide(") >= 2,
      f"{bt_src.count('_gt.decide(')} hívás")
check("az élő motor MAGA méri a piac-állapotot (nem a GUI-ra vár)",
      "ds.market_state = _cat" in live_src)
check("a piac-kapu a NYERS besorolást nézi, nem a magyar címkét",
      "market_adverse" in live_src and "market_state_label" not in
      live_src[live_src.index("_gate_failed[_gates.MARKET]") - 400:
               live_src.index("_gate_failed[_gates.MARKET]")])

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

"""A VOLATILITAS VALODI KAPU (v3.27.0) — a szures kikerult a strategiabol.

⚠ A KERES (2026-09-02): „Van a kapuinknal egy olyan kapu, ami nem szur, csak
mutat. Annak meg mi ertelme van?" — es a valasz arra a kerdesre, hogy a `none`
hatas onnantol TENYLEG azt jelentse, hogy nincs volatilitas-szures: „Igen jo
sot! Igy egyre »egyszerubb« a strategiank!"

AMI VALTOZOTT. A szures eddig HAROM strategia `bt_entry`-jeben allt kulon-kulon
(`wpr_sma`, `bollinger_squeeze`, `candle_level_break`), a `trend_pullback`-ben es
az `ml_ai`-ban viszont NEM — vagyis attol fuggott, melyik strategia masolta be.
Most egy helyen dol el (`core.vol_baseline.failed` + `core.gates.decide`).

AMI NEM VALTOZOTT (es ezt orizzuk itt a legszigorubban): a VISELKEDES. A kapu
`block`-kal indul, mert a regi szuro feltetel nelkul futott; a „kikapcsolt"
allapotot pedig eddig is a NULLA kuszob jelentette. Merve a bevezetesnel: kuszobe
CSAK a `wpr_sma`-nak van (mind a 13 mentett keszletben), a tobbi strategianak
nincs — vagyis pontosan az a halmaz szur, amelyik eddig is szurt.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog  # noqa: E402
applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


import pandas as pd                                        # noqa: E402
from core import gates as g, vol_baseline as vb            # noqa: E402
from trading import backtest as bt                         # noqa: E402

PRM = {"atr_min_pct": 0.9, "atr_max_pct": 3.2, "atr_avg_ref": 272.75}


# ══ 1. AZ ITELET egy helyen szuletik ═════════════════════════════════════
# A regi, `bt_entry`-be masolt logika REFERENCIAKENT — ha a kozos fuggveny
# barmiben elter tole, az NEMA viselkedes-valtas lenne az egesz motorban.
def _regi_itelet(atr, params, row_atr_avg):
    base = vb.effective(params, row_atr_avg)
    if base and base > 0:
        lo, hi = vb.band(params, base)
        if lo > 0 and atr < lo:
            return True
        if hi > 0 and atr > hi:
            return True
    return False


_elter = []
for _atr in (50.0, 140.19, 245.0, 245.5, 272.75, 872.0, 873.0, 3000.0):
    for _p in (PRM, {**PRM, "atr_baseline_bars": 8640},
               {"atr_min_pct": 0, "atr_max_pct": 0}, {}):
        for _aa in (0.0, 140.19, 272.75):
            if vb.failed(_atr, _p, _aa) != _regi_itelet(_atr, _p, _aa):
                _elter.append((_atr, sorted(_p), _aa))
check("a kozos itelet BITRE egyezik a regi bt_entry-logikaval", not _elter,
      f"{len(_elter)} elteres")
check("ervenytelen ATR-nel nem szur (None/NaN/0)",
      not any(vb.failed(v, PRM, 0.0) for v in (None, float("nan"), 0.0, -1.0)))


# ══ 2. EGYETLEN strategia sem szur mar sajat maga ════════════════════════
_bt_entry_ben = [f.name for f in sorted((ROOT / "strategy").glob("*.py"))
                 if "    def bt_entry" in f.read_text(encoding="utf-8")]
check("a `bt_entry` mar CSAK az osben van (a felulirasok eltuntek)",
      _bt_entry_ben == ["base.py"], str(_bt_entry_ben))
# ⚠ A SAV-OSSZEHASONLITAS (`vol_baseline.band`) az, amit egyik strategia sem
# vegezhet el sajat maga — az az itelet, es az a kapue. A `series` (az `atr_avg`
# oszlop eloallitasa) es a `value_at` viszont MARAD: azok a MERCET adjak, amibol
# a kapu dolgozik. A `wpr_sma` viz-uton hivja a kozos `failed`-et, de csak
# `block` hatas mellett (lasd lentebb) — az nem sajat masolat.
_savoz = [f.name for f in sorted((ROOT / "strategy").glob("*.py"))
          if ".band(" in f.read_text(encoding="utf-8")]
check("egyetlen strategia sem vegzi el maga a sav-osszehasonlitast", not _savoz,
      ", ".join(_savoz))


# ══ 3. A HATAS: blokkol / csokkent / ki — a MOTORBAN ═════════════════════
# Ugyanaz a minimal backtest-vaz, mint a `test_gate_effects_engine.py`-ban.
def _run(effect, exec_gates=True):
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
            hi = hi.copy()
            # ⚠ AZ ATR A SAV ALATT: 140,19 a 272,75-os mercehez = 0,51× — a
            # VALODI BTCUSD-eset, ami hetekig nemitotta el a part.
            hi["atr"] = 140.19
            hi["atr_avg"] = 272.75
            return hi, lo

        def bt_warmup(self, p, tf):
            return 0

        def bt_new_state(self, sym):
            return {}

        def bt_on_high_close(self, st, row, p):
            return st

        def bt_on_low_close(self, st, prev, row, p):
            return "BUY" if row.name == idx1[100] else "NONE"

        def bt_entry(self, row, p, ps):
            return (100.0, 200.0)

    cfg = {"gates": {"volatility": {"default": effect},
                     "spread": {"default": "none"},
                     "tf_align": {"default": "none"}}}
    pair_cfg = {"point_size": 0.01, "pv1_point": 1.0, "min_lot": 0.01,
                "lot_step": 0.01, "backtest_spread_points": 1.0}
    return bt.run_pair("T", m15, m1, dict(PRM), pair_cfg,
                       {"account_risk_pct": 0.02, "max_open_slots": 1},
                       10000.0, strategy=S(), cfg=cfg, exec_gates=exec_gates)


_blk, _red, _none = _run("block"), _run("reduce"), _run("none")
check("`block` → NINCS belepo (a v3.27.0 ELOTTI viselkedes)", not _blk.trades,
      f"{len(_blk.trades)} kotes")
check("`none` → VAN belepo (a szures tenyleg kikapcsolt)", bool(_none.trades),
      f"{len(_none.trades)} kotes")
check("`reduce` → VAN belepo (nem blokkol)", bool(_red.trades),
      f"{len(_red.trades)} kotes")
_l_none = _none.trades[0].lot if _none.trades else None
_l_red = _red.trades[0].lot if _red.trades else None
check("...de KISEBB lottal, a felezessel",
      _l_none and _l_red and abs(_l_red - _l_none * g.REDUCE_RISK_FACTOR) < 1e-6,
      f"{_l_none} -> {_l_red}")


# ══ 4. PARAMETER-VEZERELT: az `exec_gates=False` NEM kapcsolja ki ════════
# ⚠ A sopres (`core/sweep.py`) `exec_gates=False`-szal fut, es epp az
# `atr_min_pct`/`atr_max_pct` az egyik soport parameter. Ha a kapcsolo ezt is
# levenne, a sopres olyan parametert merne, aminek nincs hatasa.
check("exec_gates=False mellett is BLOKKOL", not _run("block", False).trades)
check("...de a tobbi kapu ilyenkor kimarad",
      all(v == g.EFFECT_NONE for k, v in
          g.effects_for({}, "T", "wpr_sma", exec_gates=False).items()
          if k not in g.PARAM_DRIVEN))
check("a volatilitas a PARAM_DRIVEN halmazban van", g.VOLATILITY in g.PARAM_DRIVEN)


# ══ 5. MIND A NEGY UT ugyanezt a fuggvenyt hivja ═════════════════════════
# el · backtest/run_pair · backtest/portfolio · viz — ha barmelyik sajat masolatot
# tartana, a chart es a kotes ismet szetcsuszna (mar tobbszor megtortent).
_src = {
    "el (live_trader)": ROOT / "trading" / "live_trader.py",
    "backtest": ROOT / "trading" / "backtest.py",
    "viz (wpr_sma)": ROOT / "strategy" / "wpr_sma.py",
}
for _nev, _p in _src.items():
    check(f"{_nev}: a kozos `failed`-et hivja",
          ".failed(" in _p.read_text(encoding="utf-8"))
_btsrc = _src["backtest"].read_text(encoding="utf-8")
check("a backtest MINDKET aga meri (run_pair + portfolio)",
      _btsrc.count("_gt.VOLATILITY") >= 2, str(_btsrc.count("_gt.VOLATILITY")))
_vizsrc = _src["viz (wpr_sma)"].read_text(encoding="utf-8")
check("a viz CSAK `block` hatasnal szur (a `reduce`-nal is rajzol)",
      'gate_blocks("volatility")' in _vizsrc)


# ══ 6. A KIJELZES ugyanezt mondja ════════════════════════════════════════
_ctx = {"atr_price": 140.19, "atr_baseline": 272.75, "vol_params": PRM}
_st = g.evaluate(_ctx, {g.VOLATILITY: g.EFFECT_BLOCK})
_row = next(r for r in _st if r["key"] == g.VOLATILITY)
check("a kapu-sor BLOKKOL-t mutat a savon kivul", _row["state"] == g.BLOCKING,
      _row["state"])
check("...es a badge is szamolja", g.badge(_st).startswith("⛔"), g.badge(_st))
_st_off = g.evaluate(_ctx, {g.VOLATILITY: g.EFFECT_NONE})
check("`none` hatasnal a sor KI (nem villog feleslegesen)",
      next(r for r in _st_off if r["key"] == g.VOLATILITY)["state"] == g.OFF)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

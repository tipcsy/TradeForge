"""Parameter-osztaly: kell-e UJRASZAMOLNI a belepo-listat?

A user dokumentacio (Parameterek vs OPT vs Backtest) keresi: legyen ket osztaly —
amik miatt a teljes beszallo-listat ujra kell szamolni, es amik miatt nem.

Merve, MIERT szamit (UsaInd, 8 honapos WF-ablak, 237 572 M1 gyertya):
    indikatorok + M15 + M1 allapotgep : 7,5 mp
    a teljes run_pair                 : 11,1 mp
Egy VEGREHAJTASI sopresnel tehat a dolgok haromnegyede ujrahasznalhato.

⚠ A LEGFONTOSABB INVARIANS: az ismeretlen kulcs "signal".
Ha egy JEL-parametert tevedesbol vegrehajtasinak minositenenk, a gyorsitotar
olyankor is ujrahasznalodna, amikor nem szabadna -> CSENDESEN HAMIS eredmeny.
Forditva csak sebesseget veszitunk. A ket hibairany nem egyenrangu.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategy.settings import (SIGNAL_PARAM, EXEC_PARAM, param_class,
                               split_params, unclassified_params)

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ── 1. A BIZTONSAGOS ALAPERTELMEZES ──────────────────────────────────────────
check("ismeretlen kulcs -> 'signal' (a DRAGA, biztonsagos ag)",
      param_class({}, "nincs_ilyen") == SIGNAL_PARAM)
check("ures param_meta -> 'signal'",
      param_class({"param_meta": {}}, "akarmi") == SIGNAL_PARAM)
check("ERVENYTELEN ertek -> 'signal' (nem hisszuk el a szemetet)",
      param_class({"param_meta": {"params": {"x": {"recompute": "hopp"}}}}, "x")
      == SIGNAL_PARAM)
check("ervenyes 'execution' atmegy",
      param_class({"param_meta": {"params": {"x": {"recompute": "execution"}}}}, "x")
      == EXEC_PARAM)

# ── 2. MINDEN OPTIMALIZALHATO PARAMETER OSZTALYOZVA VAN ──────────────────────
for strat in ("wpr_sma", "bollinger_squeeze_breakout", "ml_ai"):
    cfg = json.loads((ROOT / "strategy" / "config" / f"{strat}.json").read_text(encoding="utf-8"))
    keys = list(((cfg.get("param_meta") or {}).get("params") or {}).keys())
    check(f"{strat}: van param_meta ({len(keys)} kulcs)", len(keys) > 0)
    miss = unclassified_params(cfg, keys)
    check(f"{strat}: MINDEN parameter osztalyozva", not miss, ", ".join(miss))
    # az optimizer-tartomanyban levo kulcsok is (a `constraints`/`training` nem parameter)
    opt = [k for k in (cfg.get("optimizer") or {})
           if not k.startswith("_") and k not in ("constraints", "training")]
    hianyzo = [k for k in opt if k not in keys]
    check(f"{strat}: minden HANGOLT kulcsnak van meta-ja", not hianyzo, ", ".join(hianyzo))

# ── 3. A KONKRET BESOROLASOK — a kod tenyleges hasznalata alapjan ────────────
# Ezek nem izles kerdesei: a jel-parametereket az indicator_engine/signal_detector
# olvassa (allapotgep), a vegrehajtasiakat a risk_manager/vol_baseline (szuro+meret).
W = json.loads((ROOT / "strategy" / "config" / "wpr_sma.json").read_text(encoding="utf-8"))
for k in ("sma_period", "wpr_m15_period", "wpr_m1_trigger", "wpr_m15_buy_extreme",
          "no_trade_resets_signal"):
    check(f"wpr_sma/{k} = signal", param_class(W, k) == SIGNAL_PARAM, param_class(W, k))
for k in ("sl_atr_mult", "tp_rr_ratio", "atr_min_pct", "atr_max_pct"):
    check(f"wpr_sma/{k} = execution", param_class(W, k) == EXEC_PARAM, param_class(W, k))

B = json.loads((ROOT / "strategy" / "config" / "bollinger_squeeze_breakout.json").read_text(encoding="utf-8"))
for k in ("signal_tf_min", "bb_period", "bw_lookback", "max_bars_after_squeeze"):
    check(f"bollinger/{k} = signal", param_class(B, k) == SIGNAL_PARAM, param_class(B, k))
for k in ("sl_atr_mult", "tp_rr"):
    check(f"bollinger/{k} = execution", param_class(B, k) == EXEC_PARAM, param_class(B, k))

# ── 4. split_params: sorrend-tarto, teljes ───────────────────────────────────
keys = ["sma_period", "sl_atr_mult", "wpr_m1_trigger", "tp_rr_ratio"]
sig, exe = split_params(W, keys)
check("split_params: a jel-agra a helyesek kerulnek",
      sig == ["sma_period", "wpr_m1_trigger"], str(sig))
check("split_params: a vegrehajtasi agra a helyesek",
      exe == ["sl_atr_mult", "tp_rr_ratio"], str(exe))
check("split_params: egyetlen kulcs sem VESZ EL",
      sorted(sig + exe) == sorted(keys))

# ── 5. A sebesseg-nyereseg csak akkor van meg, ha VAN vegrehajtasi parameter ──
for strat, cfg in (("wpr_sma", W), ("bollinger_squeeze_breakout", B)):
    allk = list(((cfg.get("param_meta") or {}).get("params") or {}).keys())
    s, e = split_params(cfg, allk)
    check(f"{strat}: van sopresre alkalmas (execution) parameter",
          len(e) > 0, f"jel={len(s)} vegrehajtas={len(e)}")


# ── 6. AZ INVARIANS, amire a gyorsitotar epul (empirikus) ────────────────────
# Az osztalyozas nem izles kerdese: ELLENORIZHETO. A helyes szint a JELOLT-lista
# (az allapotgepek kimenete), NEM a kotes-lista.
#
# ⚠ Miert: merve (UsaInd) a `tp_rr_ratio` valtoztatasa a KOTES-listat 194->193-ra
# vitte — mas TP -> mas zarasi ido -> mas slot-foglaltsag -> egy jel kimaradt. Az
# `atr_min_pct` pedig szurokent 194->529-re. Egyik sem cafolja a besorolast: a
# JELOLT-lista mindkettonel valtozatlan, es a gyorsitotar AZT tarolja.
import numpy as np
import pandas as pd

rng = np.random.default_rng(20260811)


def _bars(n, start, freq):
    px = 25000 + np.cumsum(rng.normal(0, 3.0, n))
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    hi = px + np.abs(rng.normal(0, 2.0, n))
    lo = px - np.abs(rng.normal(0, 2.0, n))
    return pd.DataFrame({"open": px, "high": hi, "low": lo, "close": px,
                         "volume": 1.0}, index=idx)


def _candidates(strategy, m15_raw, m1_raw, params):
    """CSAK az allapotgepek kimenete — szuro/slot/szimulacio nelkul."""
    m15, m1 = strategy.bt_indicators(m15_raw, m1_raw, params)
    st = strategy.bt_new_state("T")
    m15_t = list(m15.index)
    delta = pd.Timedelta(minutes=15)
    cols = list(m1.columns)
    arr = {c: m1[c].to_numpy() for c in cols}
    out, prev, ptr = [], None, 0
    for i, ts in enumerate(m1.index):
        while ptr + 1 < len(m15_t) and m15_t[ptr + 1] + delta <= ts:
            ptr += 1
            st = strategy.bt_on_high_close(st, m15.iloc[ptr], params)
        row = {c: arr[c][i] for c in cols}
        if prev is not None:
            sg = strategy.bt_on_low_close(st, prev, row, params)
            if sg in ("BUY", "SELL"):
                out.append((str(ts), sg))
        prev = row
    return out


from strategy import get_strategy_by_name
_st = get_strategy_by_name("wpr_sma")
_m15 = _bars(1200, "2026-01-01", "15min")
_m1 = _bars(1200 * 15, "2026-01-01", "1min")
_base = {"sma_period": 200, "wpr_m15_period": 21, "wpr_m1_period": 21,
         "wpr_m15_sell_extreme": -20, "wpr_m15_buy_extreme": -80,
         "wpr_m15_sell_trigger": -40, "wpr_m15_buy_trigger": -60,
         "wpr_m1_sell_extreme": -20, "wpr_m1_buy_extreme": -80,
         "wpr_m1_trigger": -50, "sl_atr_mult": 2.0, "tp_rr_ratio": 1.0,
         "atr_period": 14, "atr_min_pct": 0.5, "atr_max_pct": 3.0,
         "atr_avg_ref": 10.0, "point_size": 0.01}
_ref = _candidates(_st, _m15, _m1, _base)
check("a generalt adaton szuletik jelolt (a teszt ertelmes)", len(_ref) > 0, f"{len(_ref)} jel")

for _k, _v in (("sl_atr_mult", 4.0), ("tp_rr_ratio", 2.5),
               ("atr_min_pct", 0.0), ("atr_max_pct", 99.0)):
    _p = dict(_base); _p[_k] = _v
    check(f"EXECUTION {_k}: a JELOLT-lista VALTOZATLAN",
          _candidates(_st, _m15, _m1, _p) == _ref)

for _k, _v in (("sma_period", 120), ("wpr_m1_trigger", -35), ("wpr_m15_period", 9)):
    _p = dict(_base); _p[_k] = _v
    check(f"SIGNAL {_k}: a JELOLT-lista VALTOZIK (van ertelme ujraszamolni)",
          _candidates(_st, _m15, _m1, _p) != _ref)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

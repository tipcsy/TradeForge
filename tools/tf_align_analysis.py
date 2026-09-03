"""
TF-összhang teszt: a TÖBB-IDŐSÍKÚ trend-egyezés szétválasztja-e a nyerő/vesztő
wpr_sma-kötéseket? (A Tanulóklub „minden idősík egyezik" intuíciója, számszerűen.)

Hipotézis (mean-reversion stratégiára): ha M5/M15/H1 MIND egy irányba mutat (erős
összhang-trend), és a kötés EZ ELLEN fade-el → veszélyes → rosszabb R. Ha az
idősíkok nem egyeznek (vegyes), a fade biztonságosabb.

Minden kötést besorol a belépéskori idősík-egyezés szerint:
  against_aligned : M5/M15/H1 mind egy irányba, a kötés ELLENE fade-el
  with_aligned    : mind egy irányba, a kötés VELE
  mixed           : az idősíkok NEM mind egyeznek
majd IS/OOS bontásban csoportonként mean-R + a kulcs-különbség (against − mixed)
95% CI-vel. A trend-irány idősíkonként: sign(close − SMA(n)).

Futtatás:
    python tools/tf_align_analysis.py --symbol EURUSD
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))

from strategy.settings import load_config
from strategy import get_strategy
from core.params_store import params_file, set_active_strategy
from gates import tf_align as _tfa
from trading.backtest import load_data, run_pair

_SMA_N = 50    # trend-irány idősíkonként: close vs SMA(_SMA_N)


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    return pd.DataFrame({
        "open":  df["open"].resample(rule).first(),
        "high":  df["high"].resample(rule).max(),
        "low":   df["low"].resample(rule).min(),
        "close": df["close"].resample(rule).last(),
    }).dropna()


def _trend_sign(df: pd.DataFrame, n: int = _SMA_N) -> pd.Series:
    sma = df["close"].rolling(n).mean()
    return np.sign(df["close"] - sma)


def _bars(df: pd.DataFrame):
    """(nyitó-idő unix, záróár) — a `gates.tf_align` historikus kiértékelőjének
    bemenete."""
    return ((df.index.view("int64") // 1_000_000_000).astype(np.int64),
            df["close"].to_numpy(dtype=float))


def _mean_se(rs):
    n = len(rs)
    if n == 0:
        return 0.0, 0.0, 0
    m = sum(rs) / n
    se = (math.sqrt(sum((r - m) ** 2 for r in rs) / (n - 1)) / math.sqrt(n)) if n > 1 else 0.0
    return m, se, n


def _params_for(symbol, cfg, strategy):
    pf = params_file(symbol, strategy.name)
    if pf.exists():
        with open(pf, encoding="utf-8") as f:
            return json.load(f).get("params", {}) or strategy.base_params(cfg)
    return strategy.base_params(cfg)


def _harden():
    """A cp1250 konzol elszáll a nyilakon/ékezeteken — a `logging` ezt elnyeli, a
    `print` viszont KIVÉTELT dob és megszakítja a mérést. (Meg is tette: a Ger40
    riport a 3. sornál elhasalt.)"""
    from core import applog
    applog.harden_console()


def analyze(symbol, cfg, strategy, ib, oos_frac=0.4, with_m1=False):
    _harden()
    df15, df1 = load_data(symbol)
    if df15 is None:
        print(f"  {symbol}: nincs adat.")
        return
    pair_cfg = cfg.get("pairs", {}).get(symbol)
    if not isinstance(pair_cfg, dict):
        print(f"  {symbol}: nincs pár-config.")
        return

    # Idősík-jelek: M5 (M1-ből), M15 (nyers), H1 (M1-ből). Opcionálisan M1 (zajos).
    # A trend-előjelek a KÖZÖS, look-ahead-mentes magból (gates.tf_align). Korábban
    # `sign(bar_close − SMA)` volt, `asof(nyitó_idő)`-vel kiolvasva: az a kötés
    # idejét TARTALMAZÓ gyertya VÉGLEGES záróárából számolt — vagyis a besorolás
    # jövőt látott (H1-nél akár egy órányit), és ez torzította a mért „élt".
    # Mostantól a formálódó gyertya záróára a kötés BELÉPŐ ÁRA (ami akkor ismert
    # volt), az SMA-ba pedig csak lezárt gyertyák mennek — mint élesben.
    # Az idősíkokat és az SMA-t a PÁR TÉNYLEGES kapu-beállításából vesszük
    # (`tf_align.config_for`), nem bedrótozva. Enélkül a mérés MÁS definíciót
    # vizsgálna, mint amit a motor a belépő-kapuban használ — a válasz így nem a
    # feltett kérdésre vonatkozna.
    _en, _tfl, _sma, _gate = _tfa.config_for(cfg, symbol)
    if with_m1 and 1 not in _tfl:
        _tfl = [1] + list(_tfl)
    _RULE = {1: "1min", 5: "5min", 15: "15min", 30: "30min", 60: "60min", 240: "240min"}
    _tfs = {}
    for _tf in _tfl:
        _tf = int(_tf)
        if _tf == 15:
            _tfs[_tf] = _bars(df15)                       # natív M15
        elif _tf == 1:
            _tfs[_tf] = _bars(df1)                        # natív M1
        else:
            _tfs[_tf] = _bars(_resample(df1, _RULE.get(_tf, f"{_tf}min")))
    _order = [int(t) for t in _tfl]
    signs_at = _tfa.build_historical_signs({k: _tfs[k] for k in _order}, _sma)

    split_ts = df15.index[int(len(df15) * (1 - oos_frac))]
    params = _params_for(symbol, cfg, strategy)
    res = run_pair(symbol, df15, df1, params, pair_cfg, cfg["trading"], ib,
                   strategy=strategy)
    trades = [t for t in res.closed
              if t.close_time is not None and (getattr(t, "risk_usd", 0) or 0) > 0]
    if len(trades) < 200:
        print(f"  {symbol}: kevés kötés ({len(trades)}).")
        return

    groups = {"against_aligned": {"IS": [], "OOS": []},
              "with_aligned":    {"IS": [], "OOS": []},
              "mixed":           {"IS": [], "OOS": []}}
    for t in trades:
        ot = t.open_time
        signs = signs_at(int(ot.timestamp()), float(t.open_price))
        d = 1 if t.direction == "BUY" else -1
        if all(s == 1 for s in signs):
            grp = "with_aligned" if d == 1 else "against_aligned"
        elif all(s == -1 for s in signs):
            grp = "with_aligned" if d == -1 else "against_aligned"
        else:
            grp = "mixed"
        r = t.pnl_usd / t.risk_usd
        groups[grp]["IS" if ot < split_ts else "OOS"].append(r)

    n_tf = "/".join(f"M{t}" for t in _order) + f" · SMA{_sma}"
    if _en and strategy.name in _gate:
        n_tf += "  [a KAPU aktív ezen a páron]"
    n_oos = sum(len(g["OOS"]) for g in groups.values())
    print(f"\n  {symbol}  |  OOS {n_oos} kötés  |  idősíkok: {n_tf}  |  OOS-tól: {split_ts.date()}")
    print(f"  {'Csoport':<17} {'IS_n':>5} {'IS_R':>6}  {'OOS_n':>5} {'OOS_R':>6} {'OOS 95%CI':>16}  {'megoszl.':>8}")
    print("  " + "-" * 76)
    order = ["against_aligned", "mixed", "with_aligned"]
    stats = {}
    for g in order:
        im, _, inn = _mean_se(groups[g]["IS"])
        om, ose, onn = _mean_se(groups[g]["OOS"])
        stats[g] = (om, ose, onn)
        share = onn / n_oos * 100 if n_oos else 0
        ci = f"[{om-1.96*ose:+.2f},{om+1.96*ose:+.2f}]"
        print(f"  {g:<17} {inn:>5} {im:>+6.2f}  {onn:>5} {om:>+6.2f} {ci:>16}  {share:>6.0f}%")

    # Kulcs-teszt: against_aligned vs mixed (a hipotézis: against ROSSZABB)
    (am, ase, an) = stats["against_aligned"]
    (mm, mse, mn) = stats["mixed"]
    if an >= 30 and mn >= 30:
        spread = am - mm
        ci = 1.96 * math.sqrt(ase**2 + mse**2)
        sig = "SZIGNIFIKÁNS" if abs(spread) > ci else "nem szign."
        verdict = ("hipotézis IGAZOLVA (against rosszabb)"
                   if (spread < 0 and abs(spread) > ci) else
                   "hipotézis CÁFOLVA (against jobb)" if (spread > 0 and abs(spread) > ci)
                   else "nincs szign. különbség")
        print(f"  → against − mixed OOS: {spread:+.2f}  ±{ci:.2f}  [{sig}]  {verdict}")
    else:
        print(f"  → against_aligned kis minta (n={an}) — nem ítélünk.")


def main():
    ap = argparse.ArgumentParser(description="TF-összhang teszt")
    ap.add_argument("--symbol", default=None)
    ap.add_argument("--oos-frac", type=float, default=0.4)
    ap.add_argument("--with-m1", action="store_true", help="az M1 idősík is (zajos)")
    args = ap.parse_args()
    cfg = load_config(str(ROOT / "config.json"))
    strategy = get_strategy(cfg)
    set_active_strategy(strategy.name)
    ib = float(cfg.get("ml", {}).get("starting_balance_eur", 1000.0))
    symbols = ([args.symbol] if args.symbol else
               [s for s, p in cfg.get("pairs", {}).items()
                if isinstance(p, dict) and p.get("enabled", False)])
    print(f"TF-összhang teszt | stratégia: {strategy.name} | OOS-hányad: {args.oos_frac}"
          f" | az idősíkok/SMA a pár tf_align beállításából")
    for sym in symbols:
        try:
            analyze(sym, cfg, strategy, ib, args.oos_frac, args.with_m1)
        except Exception as e:
            import traceback
            print(f"  {sym}: hiba — {e}")
            traceback.print_exc()


if __name__ == "__main__":
    main()

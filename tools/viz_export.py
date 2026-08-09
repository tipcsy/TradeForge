"""
Viz-EXPORT egy MEGADOTT tól-ig ablakra — az MT4-es manuális visszajátszáshoz.

Az élő viz mindig az „utolsó N gyertyát" rajzolja. A manuális teszthez viszont
egy KONKRÉT hetet akarunk visszajátszani (pl. 2026-06-08 → 06-13), ezért ez az
eszköz a MEGADOTT ablakra számolja ki ugyanazt.

⚠ Ami NEM változik: a rajz a `live_trader.pair_visual_lines`-ból jön, tehát
bitre ugyanaz a számítás, mint élesben — csak az adat forrása más (parquet, nem
friss MT5-lekérés). Ha ez a fájl MÁSOLNÁ a logikát, a másolat előbb-utóbb
elcsúszna az eredetitől.

⚠ WARMUP: a stratégia jelzés-állapota ELŐZMÉNYFÜGGŐ (mély M15-ablak). Ezért a
kért ablak ELÉ betöltjük a `visual_lookback_bars` szerinti bemelegítést —
enélkül az ablak első napja MÁS jelzést adna, mint élesben.

⚠ A VALÓS kötések nyilai alapból KIMARADNAK (`--show-trades` kapcsolja be):
manuális teszthez azok a MEGFEJTÉST jelentenék.

Futtatás:
  python tools/viz_export.py --symbol Ger40 --from 2026-06-08 --to 2026-06-13
  python tools/viz_export.py --symbol Ger40 --from 2026-06-08 --to 2026-06-13 \
         --strategy wpr_sma --suffix _BT
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import mt5_visual
from core.execution_params import load_execution_params
from strategy import get_strategy_by_name, default_strategy_name
from strategy.settings import load_config
from trading.backtest import load_data
from trading.live_trader import pair_visual_lines

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("viz_export")


def _params_for(symbol: str, strat_name: str, strategy, cfg: dict) -> dict:
    """A pár mentett paraméterei + a KÖZÖS végrehajtási réteg.

    Ugyanaz a rétegzés, mint az optimalizálóban és a backtestben: az
    `atr_period` / spread-kapu 2026-08-03 óta nem a stratégia json-jában lakik.
    Enélkül a viz `KeyError: 'atr_period'`-del, NÉMÁN üres charttal állna le."""
    f = ROOT / "data" / "optimized_params" / strat_name / f"{symbol}.json"
    base = (json.loads(f.read_text(encoding="utf-8")).get("params")
            if f.exists() else None) or strategy.base_params(cfg)
    return {**base, **load_execution_params(symbol, cfg)}


def _window_bars(df: pd.DataFrame, tf_min: int, warmup: int,
                 t_from: pd.Timestamp, t_to: pd.Timestamp) -> pd.DataFrame:
    """A [t_from - warmup, t_to] szelet. A parquet `close_spread`-jét `spread`-re
    nevezzük — az élő úton az MT5 bar-spreadje ezen a néven érkezik (ÁRban), és a
    viz spread-kapuja ezt nézi."""
    if df is None or df.empty:
        return None
    start = t_from - pd.Timedelta(minutes=tf_min * max(0, warmup))
    out = df[(df.index >= start) & (df.index <= t_to)]
    if "close_spread" in out.columns and "spread" not in out.columns:
        out = out.rename(columns={"close_spread": "spread"})
    keep = [c for c in ("open", "high", "low", "close", "volume", "spread")
            if c in out.columns]
    return out[keep]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--from", dest="t_from", required=True, help="YYYY-MM-DD")
    ap.add_argument("--to", dest="t_to", required=True, help="YYYY-MM-DD (a nap VÉGÉIG)")
    ap.add_argument("--strategy", default=None, help="alap: a config elsődlegese")
    ap.add_argument("--suffix", default="",
                    help="külön fájlnév, pl. _BT → TFV_<SYM>_BT.csv (alap: az élővel közös)")
    ap.add_argument("--show-trades", action="store_true",
                    help="a VALÓS kötések nyilai is kerüljenek rá (manuális teszthez NE)")
    args = ap.parse_args()

    cfg = load_config(ROOT / "config.json")
    symbol = args.symbol
    pair_cfg = (cfg.get("pairs") or {}).get(symbol)
    if not isinstance(pair_cfg, dict):
        log.error("%s — nincs ilyen pár a config.json-ban.", symbol)
        sys.exit(1)
    point_size = pair_cfg.get("point_size")
    if not point_size:
        log.error("%s — hiányzó point_size.", symbol)
        sys.exit(1)

    strat_name = args.strategy or default_strategy_name(cfg)
    strategy = get_strategy_by_name(strat_name)
    params = _params_for(symbol, strat_name, strategy, cfg)

    t_from = pd.Timestamp(args.t_from, tz="UTC")
    t_to = pd.Timestamp(args.t_to, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    if t_to <= t_from:
        log.error("A --to nem lehet a --from előtt.")
        sys.exit(1)

    df15, df1 = load_data(symbol)
    if df15 is None or df1 is None:
        log.error("%s — nincs letöltött adat (data/m15, data/m1).", symbol)
        sys.exit(1)

    bars, src = {}, {"M15": (df15, 15), "M1": (df1, 1)}
    for tf in strategy.timeframes():
        if tf.label not in src:
            continue
        df, tf_min = src[tf.label]
        warmup = strategy.visual_lookback_bars(params, tf.label)
        w = _window_bars(df, tf_min, warmup, t_from, t_to)
        if w is None or len(w) < 3:
            log.error("%s %s — túl kevés gyertya ebben az ablakban (%s).",
                      symbol, tf.label, 0 if w is None else len(w))
            sys.exit(1)
        bars[tf.label] = w
        log.info("  %-3s  %6d gyertya  [%s → %s]  (ebből warmup: %d)",
                 tf.label, len(w), str(w.index[0])[:16], str(w.index[-1])[:16],
                 max(0, len(w[w.index < t_from])))

    lines = pair_visual_lines(symbol, params, strategy, point_size, pair_cfg,
                              bars=bars, actual_trades=args.show_trades)
    if not lines:
        log.error("%s — a viz üres lett (a stratégia nem adott objektumot).", symbol)
        sys.exit(1)

    path = mt5_visual.write_lines(symbol, lines, clear_first=True,
                                  name_suffix=args.suffix)
    if path is None:
        log.error("Nem sikerült írni a Common\\Files mappába.")
        sys.exit(1)

    kinds = {}
    for ln in lines:
        kinds[ln.split(";", 1)[0]] = kinds.get(ln.split(";", 1)[0], 0) + 1
    log.info("✅ %s / %s — %d sor kiírva: %s", symbol, strat_name, len(lines), path)
    log.info("   rekordok: %s", "  ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    log.info("   ablak: %s → %s%s", args.t_from, args.t_to,
             "" if args.show_trades else "   (valós kötések NÉLKÜL — manuális teszthez)")


if __name__ == "__main__":
    main()

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


def export_window(symbol: str, t_from: str, t_to: str, strategy_name: str = None,
                  suffix: str = "_BT", show_trades: bool = False,
                  cfg: dict = None, status=None) -> tuple:
    """Egy tól-ig ablak kiírása a viz-fájlba. `(ok, üzenet)`.

    A CLI és a dashboard-gomb IS ezt hívja — így a kettő nem csúszhat szét.
    `status`: opcionális fn(str) haladásjelző (a GUI a sor-státuszba teszi)."""
    def _say(m):
        log.info("%s", m)
        if status is not None:
            try:
                status(m)
            except Exception:
                pass

    cfg = cfg or load_config(ROOT / "config.json")
    pair_cfg = (cfg.get("pairs") or {}).get(symbol)
    if not isinstance(pair_cfg, dict):
        return False, f"{symbol} — nincs ilyen pár a config.json-ban."
    point_size = pair_cfg.get("point_size")
    if not point_size:
        return False, f"{symbol} — hiányzó point_size."

    strat_name = strategy_name or default_strategy_name(cfg)
    try:
        strategy = get_strategy_by_name(strat_name)
    except Exception as ex:
        return False, f"Ismeretlen stratégia: {strat_name} ({ex})"
    params = _params_for(symbol, strat_name, strategy, cfg)

    try:
        ts_from = pd.Timestamp(t_from, tz="UTC")
        ts_to = pd.Timestamp(t_to, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    except Exception:
        return False, "Hibás dátum (várt formátum: ÉÉÉÉ-HH-NN)."
    if ts_to <= ts_from:
        return False, "A „-ig” nem lehet a „-tól” előtt."

    df15, df1 = load_data(symbol)
    if df15 is None or df1 is None:
        return False, f"{symbol} — nincs letöltött adat (data/m15, data/m1)."

    bars, src = {}, {"M15": (df15, 15), "M1": (df1, 1)}
    for tf in strategy.timeframes():
        if tf.label not in src:
            continue
        df, tf_min = src[tf.label]
        warmup = strategy.visual_lookback_bars(params, tf.label)
        w = _window_bars(df, tf_min, warmup, ts_from, ts_to)
        if w is None or len(w) < 3:
            return False, (f"{symbol} {tf.label} — túl kevés gyertya ebben az "
                           f"ablakban ({0 if w is None else len(w)}).")
        bars[tf.label] = w
        _say(f"{tf.label}: {len(w)} gyertya (warmup {len(w[w.index < ts_from])})")

    lines = pair_visual_lines(symbol, params, strategy, point_size, pair_cfg,
                              bars=bars, actual_trades=show_trades)
    if not lines:
        return False, f"{symbol} — a viz üres lett (a stratégia nem adott objektumot)."

    path = mt5_visual.write_lines(symbol, lines, clear_first=True, name_suffix=suffix)
    if path is None:
        return False, "Nem sikerült írni a Common\\Files mappába."

    n_sig = sum(1 for ln in lines if ln.startswith("VLINE;"))
    return True, (f"{symbol} / {strat_name}: {n_sig} belépő jelzés kiírva "
                  f"({t_from} → {t_to}) → {path.name}"
                  + ("" if show_trades else "  ·  valós kötések nélkül"))


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

    ok, msg = export_window(args.symbol, args.t_from, args.t_to,
                            strategy_name=args.strategy, suffix=args.suffix,
                            show_trades=args.show_trades)
    log.info("%s %s", "✅" if ok else "❌", msg)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

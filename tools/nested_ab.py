"""LAPOS vs BEAGYAZOTT optimalizalas — AZONOS IDOBOL melyik talal jobbat?

⚠ MIERT KELL EZ: a beagyazott kereses NEM ugyanaz a kereses, csak gyorsabban. A
koltsegvetes maskepp oszlik: azonos idobol TOBB kiertekeles lesz, de KEVESEBB
jel-beallitasra. Hogy ez nyereseg-e, az a tajkeptol fugg — kitalalni nem lehet,
csak MERNI.

⚠ ES AMIT NEM SZABAD OSSZEHASONLITANI: a ket mod celfuggveny-erteket (wf_score).
Mindketto AZT maximalja, tehat a magasabb score nem jelent jobb strategiat, csak
tobb illesztest. A holdout-tanulsag (a szennyezett OOS 2,51x-esre fujt) pontosan
errol szolt.

Ezert a protokoll:
  1. az adat vegerol levagunk N honapot — ERRE EGYIK MOD SEM LAT RA,
  2. mindketto ugyanannyi PERCET kap a levagott adaton,
  3. a ket nyertes parameter-keszletet a LEVAGOTT reszen merjuk ossze.

A leallitast a meglevo stop-marker mechanika vegzi (ugyanaz, amit a GUI STOP
gombja hasznal) — igy a ket ag pontosan ugyanugy all le.

Hasznalat:
    python tools/nested_ab.py --symbol UsaInd --minutes 25 --holdout-months 3
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from core import applog
applog.harden_console()

log = logging.getLogger("nested_ab")

# Az idő a korlát, nem a trial-szam — ez csak egy elerhetetlenul magas plafon.
_TRIAL_CAP = 10 ** 6


def _metrics(trades, initial_balance=10000.0) -> dict:
    pnl = [t.pnl_usd for t in trades]
    if not pnl:
        return {"trades": 0, "pnl": 0.0, "pf": 0.0, "win_rate": 0.0, "mdd": 0.0}
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p <= 0]
    bal = peak = initial_balance
    mdd = 0.0
    for p in pnl:
        bal += p
        peak = max(peak, bal)
        mdd = max(mdd, (peak - bal) / peak if peak > 0 else 0.0)
    pf = (abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0
          else float("inf"))
    return {"trades": len(pnl), "pnl": sum(pnl), "pf": pf,
            "win_rate": len(wins) / len(pnl), "mdd": mdd}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--strategy", default="wpr_sma")
    ap.add_argument("--minutes", type=float, default=25.0,
                    help="AGANKENT ennyi perc (a ket ag azonos idot kap)")
    ap.add_argument("--holdout-months", type=int, default=3)
    ap.add_argument("--inner-trials", type=int, default=8)
    ap.add_argument("--splits", type=int, default=4)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for noisy in ("optuna",):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # A valodi data/optimized_params-t NEM piszkaljuk: a study/CSV temp mappaba megy.
    from core import params_store as ps
    tmp = Path(tempfile.mkdtemp(prefix="nested_ab_"))
    ps.PARAMS_DIR = tmp

    from trading import backtest as bt
    from strategy.settings import load_config, load_strategy_config
    from strategy import get_strategy_by_name
    from core.execution_params import load_execution_params
    from ml import optimizer as opt

    cfg = load_config("config.json")
    sym = args.symbol
    st = get_strategy_by_name(args.strategy)
    df_m15, df_m1 = bt.load_data(sym)
    if df_m15 is None:
        print(f"{sym}: nincs letoltott elozmeny.")
        return 2

    # ── A HOLDOUT: az adat utolso N honapja. Egyik ag sem lat ra. ───────────
    cut = df_m15.index.max() - pd.DateOffset(months=args.holdout_months)
    m15_opt, m1_opt = df_m15[df_m15.index < cut], df_m1[df_m1.index < cut]
    print(f"{sym}/{st.name}  optimalizalas: {str(df_m15.index.min())[:10]} … "
          f"{str(cut)[:10]}  |  HOLDOUT: {str(cut)[:10]} … "
          f"{str(df_m15.index.max())[:10]}")
    print(f"aganként {args.minutes:.0f} perc, {args.splits} walk-forward ablak, "
          f"belso trial/kulso: {args.inner_trials}\n")

    ocfg = {**load_strategy_config(st.name)["optimizer"],
            "inner_trials": args.inner_trials}
    base = {**st.base_params(cfg), **load_execution_params(sym, cfg)}
    pair_cfg, trading_cfg = cfg["pairs"][sym], cfg["trading"]

    out = {}
    for label, nested in (("LAPOS", False), ("BEAGYAZOTT", True)):
        marker = ps.stop_marker(sym, st.name)
        marker.unlink(missing_ok=True)
        ps.done_marker(sym, st.name).unlink(missing_ok=True)
        ps.study_db(sym, st.name).unlink(missing_ok=True)

        # Idozito: a meglevo stop-marker mechanikaval allitjuk le — ugyanaz az ut,
        # amit a GUI STOP gombja hasznal, tehat a ket ag azonosan all le.
        stop_at = time.time() + args.minutes * 60
        done = threading.Event()

        def _timer():
            while not done.wait(2.0):
                if time.time() >= stop_at:
                    marker.parent.mkdir(parents=True, exist_ok=True)
                    marker.touch()
                    return

        th = threading.Thread(target=_timer, daemon=True)
        th.start()
        counted = [0]

        def _prog(done_n, total, best):
            # ⚠ A ZARO visszahivas `n_trials`-t jelent (100%), nem a tenylegesen
            # lefutott trialokat — azt nem szabad beszamolni, kulonben a
            # "kiertekelesek" oszlop a trial-korlatot mutatna.
            if done_n < _TRIAL_CAP:
                counted[0] = done_n

        t0 = time.time()
        res = opt.optimize_pair_optuna(
            sym, m15_opt, m1_opt, ocfg, base, pair_cfg, trading_cfg, 10000.0, st,
            n_trials=_TRIAL_CAP,           # az ido a korlat, nem a trial-szam
            n_splits=args.splits, progress_callback=_prog,
            cfg=cfg, exec_gates=True, nested=nested)
        done.set()
        elapsed = time.time() - t0
        marker.unlink(missing_ok=True)

        if not res:
            print(f"{label}: nincs ertekelheto eredmeny ({elapsed/60:.1f} perc, "
                  f"{counted[0]} kulso trial)")
            out[label] = None
            continue

        # ── A NYERTES a HOLDOUTON (amit sosem latott) ───────────────────────
        # A run_pair NAIV idobelyeget var (maga lokalizalja UTC-re) — a tz-t le
        # kell venni, kulonben "Cannot localize tz-aware Timestamp".
        _cut_naive = str(cut.tz_localize(None) if cut.tzinfo else cut)
        hold = bt.run_pair(sym, df_m15, df_m1, res["params"], pair_cfg,
                           trading_cfg, 10000.0, test_start=_cut_naive,
                           strategy=st, rr=opt._rr_for_run(res.get("rr")),
                           cfg=cfg, exec_gates=True)
        m = _metrics([t for t in hold.closed if t.close_time is not None])
        evals = counted[0] * (args.inner_trials if nested else 1)
        out[label] = {"elapsed_min": elapsed / 60, "outer": counted[0],
                      "evals": evals, "wf_score": res["train_summary"]["wf_score"],
                      "holdout": m, "params": res["params"]}
        print(f"{label:11s} {elapsed/60:5.1f} perc | {counted[0]:4d} kulso trial "
              f"({evals} kiertekeles) | wf_score {res['train_summary']['wf_score']:8.2f}")
        print(f"            HOLDOUT: {m['trades']:4d} kotes | P&L {m['pnl']:9.2f}$ | "
              f"PF {m['pf']:.2f} | talalat {m['win_rate']*100:.1f}% | DD {m['mdd']*100:.1f}%")

    print()
    a, b = out.get("LAPOS"), out.get("BEAGYAZOTT")
    if a and b:
        print("=" * 68)
        print("A DONTO SZAM a holdout — a wf_score-t NEM szabad osszehasonlitani")
        print("(mindketto AZT maximalja; a magasabb tobb illesztest is jelenthet).")
        print("=" * 68)
        print(f"kiertekelesek:  lapos {a['evals']:5d}  vs  beagyazott {b['evals']:5d}"
              f"   ({b['evals']/max(a['evals'],1):.2f}x)")
        print(f"holdout P&L:    lapos {a['holdout']['pnl']:9.2f}$  vs  "
              f"beagyazott {b['holdout']['pnl']:9.2f}$")
        print(f"holdout PF:     lapos {a['holdout']['pf']:9.2f}   vs  "
              f"beagyazott {b['holdout']['pf']:9.2f}")
        if a["holdout"]["trades"] < 30 or b["holdout"]["trades"] < 30:
            print("\n⚠ KEVES holdout-kotes (<30) — a kulonbseg zaj is lehet. "
                  "Hosszabb holdout vagy tobb par kell a donteshez.")

    res_path = ROOT / "data" / f"nested_ab_{sym}_{st.name}.json"
    res_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nreszletek: {res_path}")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

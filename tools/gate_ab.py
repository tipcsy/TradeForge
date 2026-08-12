"""MENNYIT ER EGY KAPU? — kihagyasos (leave-one-out) meres.

A GOLD-eset (2026-07-14) megmutatta, hogy a TF-egyuttallas kapu egy nap ot
jelzesebol NEGYET kivett. Errol eddig senki nem tudta, hogy HASZNAL-e: a kapuk
be voltak kapcsolva, mert "ovatosabbnak" tuntek.

⚠ AMIT EZ A MERES CSINAL, es amit NEM:

  CSINALJA: ugyanazokkal a PARAMETEREKKEL vegigfuttatja ugyanazt az idoszakot
  tobb kapu-beallitassal. A kulonbseg TISZTAN a kapue — nincs benne
  ujraoptimalizalas, nincs mas parameter, nincs mas adat.

  NEM CSINALJA: nem mondja meg, hogy a parameterek JOK-e. A mentett parameterek
  walk-forwardon keszultek, tehat az idoszak nem fuggetlen — az ABSZOLUT szamok
  felfele torzitanak (a holdout-meres szerint 2,51x-esre). A KULONBSEG viszont
  ervenyes: mindegyik valtozat UGYANAZT a torzitast hordozza.

A modszer kihagyasos: eloszor minden kapuval, aztan EGYESEVEL kihagyva egyet-
egyet. Igy nem azt latod, hogy "a kapuk egyutt jok-e", hanem hogy MELYIK kapu
mit tesz hozza — es melyik visz el jelzest ingyen.

A kapcsolo a `dashboard.gate_order` (mester-kapcsolo): ami nincs benne, az sem
oszlopot nem kap, sem a kereskedesbe nem szol bele — ugyanaz az ut, amit a
felulet is hasznal, tehat a meres azt meri, amit be tudsz allitani.

Hasznalat:
    python tools/gate_ab.py --symbols GOLD,Ger40,UsaInd --months 6
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from core import applog
applog.harden_console()


def _metrics(trades, ib=10000.0) -> dict:
    pnl = [t.pnl_usd for t in trades]
    if not pnl:
        return {"trades": 0, "pnl": 0.0, "pf": 0.0, "wr": 0.0, "mdd": 0.0}
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p <= 0]
    bal = peak = ib
    mdd = 0.0
    for p in pnl:
        bal += p
        peak = max(peak, bal)
        mdd = max(mdd, (peak - bal) / peak if peak > 0 else 0.0)
    pf = (abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0
          else float("inf"))
    return {"trades": len(pnl), "pnl": sum(pnl), "pf": pf,
            "wr": len(wins) / len(pnl), "mdd": mdd}


def _cfg_with_gates(cfg: dict, keys) -> dict:
    """A config masolata, amiben CSAK a megadott kapuk elnek."""
    out = copy.deepcopy(cfg)
    out.setdefault("dashboard", {})["gate_order"] = list(keys)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="", help="vesszovel; ures = minden par")
    ap.add_argument("--strategy", default="wpr_sma")
    ap.add_argument("--months", type=int, default=6,
                    help="az adat UTOLSO ennyi honapja")
    args = ap.parse_args()

    from trading import backtest as bt
    from strategy.settings import load_config
    from strategy import get_strategy_by_name
    from core import gates as g, gate_layout as gl
    from core.params_store import params_file
    from core.execution_params import load_execution_params

    cfg = load_config("config.json")
    st = get_strategy_by_name(args.strategy)
    syms = ([s.strip() for s in args.symbols.split(",") if s.strip()]
            or [s for s in cfg["pairs"] if not s.startswith("_")])

    on_keys = list(gl.enabled_gates(cfg))
    print(f"strategia: {st.name} | bekapcsolt kapuk: {', '.join(on_keys) or '(egy sem)'}")
    print(f"idoszak: az adat utolso {args.months} honapja\n")
    print("⚠ A parameterek walk-forwardon keszultek, tehat az idoszak NEM")
    print("  fuggetlen: az ABSZOLUT szamok felfele torzitanak. A KULONBSEG")
    print("  viszont ervenyes — minden valtozat ugyanazt a torzitast hordozza.\n")

    # ⚠ A CSAK KIJELZES kapukat (pl. Volatilitas) kihagyjuk a kihagyasos
    # merésbol: a `decide` atugorja oket, tehat a soruk BETURE azonos volna a
    # "mind" sorral — es a felhasznalo joggal hinne, hogy meresi hiba. A valodi
    # volatilitas-szures a strategia sajat `bt_entry`-jeben van (atr_min/max_pct),
    # az nem kapu-kerdes.
    _display_only = [k for k in on_keys if g.is_display_only(k)]
    _deciding = [k for k in on_keys if k not in _display_only]
    if _display_only:
        print("  (csak kijelzes, a dontesbe nem szol bele: "
              + ", ".join(g.label_of(k) for k in _display_only) + ")\n")
    variants = [("mind (mai beallitas)", on_keys), ("egy kapu sem", [])]
    for k in _deciding:
        variants.append((f"– {g.label_of(k)} nelkul",
                         [x for x in on_keys if x != k]))

    all_rows = {}
    for sym in syms:
        f = params_file(sym, st.name)
        if not f.exists():
            print(f"{sym}: nincs mentett parameter — kihagyva")
            continue
        m15, m1 = bt.load_data(sym)
        if m15 is None:
            print(f"{sym}: nincs elozmeny — kihagyva")
            continue
        p = {**st.base_params(cfg), **load_execution_params(sym, cfg),
             **(json.loads(f.read_text(encoding="utf-8")).get("params") or {})}
        p = {k: v for k, v in p.items() if not isinstance(v, (dict, list))}
        cut = m15.index.max() - pd.DateOffset(months=args.months)
        start = str(cut.tz_localize(None) if cut.tzinfo else cut)
        pair_cfg, tcfg = cfg["pairs"][sym], cfg["trading"]

        # ⚠ A JELOLT-LISTA egyszer epul: a kapuk VEGREHAJTASI oldalon hatnak, a
        # jel-parameterek valtozatlanok. Igy a 3-8 valtozat egy epitest fizet.
        series, _ = bt.signal_series_cached(
            None, sym, m15, m1, p, pair_cfg, strategy=st, test_start=start)

        print(f"── {sym} ({len(series.signals)} jelolt a jel-oldalrol) "
              + "─" * max(0, 40 - len(sym)))
        rows = []
        for label, keys in variants:
            t0 = time.time()
            res = bt.run_pair(sym, m15, m1, p, pair_cfg, tcfg, 10000.0,
                              test_start=start, strategy=st,
                              cfg=_cfg_with_gates(cfg, keys), exec_gates=True,
                              signal_series=series)
            m = _metrics([t for t in res.closed if t.close_time is not None])
            m["label"] = label
            m["sec"] = time.time() - t0
            rows.append(m)
        base = next((r for r in rows if r["label"] == "egy kapu sem"), None)
        print("   %-26s %6s %10s %6s %7s %8s" %
              ("valtozat", "kotes", "P&L", "PF", "talalat", "kihagy"))
        for r in rows:
            cut_pct = ("" if not base or not base["trades"]
                       else f"{(1 - r['trades'] / base['trades']) * 100:5.0f}%")
            print("   %-26s %6d %9.0f$ %6.2f %6.0f%% %8s" %
                  (r["label"], r["trades"], r["pnl"], r["pf"], r["wr"] * 100,
                   cut_pct))
        all_rows[sym] = rows

    # ── Osszegzes: melyik kapu MIT tesz hozza, parokon atlagolva ───────────
    if len(all_rows) > 1:
        print("\n" + "=" * 72)
        print("OSSZEGZES — a 'mind' valtozathoz kepest (pozitiv = a kapu HASZNAL)")
        print("=" * 72)
        for k in _deciding:
            lbl = f"– {g.label_of(k)} nelkul"
            d_pnl, d_pf, n = 0.0, 0.0, 0
            for sym, rows in all_rows.items():
                allr = next((r for r in rows if r["label"].startswith("mind")), None)
                wo = next((r for r in rows if r["label"] == lbl), None)
                if not allr or not wo:
                    continue
                d_pnl += allr["pnl"] - wo["pnl"]
                d_pf += (allr["pf"] if allr["pf"] != float("inf") else 0) - \
                        (wo["pf"] if wo["pf"] != float("inf") else 0)
                n += 1
            if n:
                print(f"  {g.label_of(k):24s} P&L {d_pnl:+9.0f}$  "
                      f"atlag PF {d_pf / n:+.3f}  ({n} par)")
        print("\n  ⚠ Egy kapu akkor eri meg, ha a KIHAGYASA ROSSZABB eredmenyt ad")
        print("    (tehat a fenti szam POZITIV). A negativ szam azt jelenti, hogy")
        print("    a kapu jelzest visz el anelkul, hogy vedene.")

    out = ROOT / "data" / f"gate_ab_{st.name}.json"
    out.write_text(json.dumps(all_rows, indent=2, default=str), encoding="utf-8")
    print(f"\nreszletek: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

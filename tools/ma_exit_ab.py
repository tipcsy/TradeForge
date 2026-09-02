"""MENNYIT ER A MOZGOATLAG-SZALAG KISZALLASI JELKENT? — A/B a VALODI motoron.

⚠ MIERT A KISZALLAS, ES NEM A BELEPO. A 2026-09-02-i meres (`ma_stack.py`,
`ma_reversal.py`) szerint a negy SMA (8/21/100/250) tavolsagabol es lejtesebol
BELEPO nem lesz: a brutto el +0,02…+0,10 R, a koltseg −0,05…−0,23 R, tehat a
koltseg a 2-9-szerese. A LEJTES-EGYETERTES viszont monoton osszefugg a jovobeli
hozammal (Ger40: 0 egyetertesnel −0,191, 3-nal +0,024 ATR; a leggyorsabb SMA
ellentetes lejtese t = −3,89).

Egy KISZALLASI szabaly ingyen van: nem generál uj kotest, tehat nem fizet uj
spreadet. Es a projekt sajat merese szerint epp a kimenet-kezeles hozta a
legnagyobb egyetlen javulast (+0,031 R a celar elhagyasabol).

⚠ AMIT EZ MER, ES AMIT NEM. Ugyanaz a korlat, mint a `gate_ab.py`-nal: a
mentett parameterek walk-forwardon keszultek, tehat az ABSZOLUT szamok felfele
torzitanak (a holdout szerint 2,51x-esre). A KULONBSEG viszont ervenyes:
mindegyik valtozat UGYANAZT a torzitast hordozza, es csak a runner-kiszallas ter
el kozottuk.

⚠ A KISZALLASI MODUL A RUNNER LABRA HAT (`RUNNER_EXIT`), tehat olyan presetet
kell valasztani, aminek VAN runnere (Pajzs / Felezo). `off` preset mellett a
modul nem szolna bele semmibe — az A/B ott ket azonos futast hasonlitana ossze,
es "nincs kulonbseg"-et mondana, ami igaz, de ertelmetlen.

Hasznalat:
    python tools/ma_exit_ab.py --symbols GOLD,Ger40,UsaTec --months 12
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

import logging
logging.disable(logging.INFO)

from core import exit_signal as _exsig
from core import risk_reduction as _rrm
from core.execution_params import load_execution_params
from strategy import get_strategy_by_name
from strategy.settings import load_config
from trading import backtest as bt


def _metrics(zart) -> dict:
    if not zart:
        return {"trades": 0, "pnl": 0.0, "pf": 0.0, "wr": 0.0, "ossz_r": 0.0}
    pnl = sum(t.pnl_usd for t in zart)
    ny = sum(t.pnl_usd for t in zart if t.pnl_usd > 0)
    ve = -sum(t.pnl_usd for t in zart if t.pnl_usd < 0)
    r = 0.0
    for t in zart:
        try:
            r += t.pnl_usd / t.risk_usd if t.risk_usd else 0.0
        except (TypeError, ZeroDivisionError):
            pass
    return {"trades": len(zart), "pnl": pnl,
            "pf": (ny / ve) if ve else float("inf"),
            "wr": sum(1 for t in zart if t.pnl_usd > 0) / len(zart),
            "ossz_r": r}


def _rr(preset: str, exit_cfg: dict | None) -> dict:
    rr = {**_rrm.default_config(), "preset": preset}
    # ⚠ A KULCS NEVE `runner_stop`, NEM `runner`. Az elso valtozatomban
    # `runner`-t irtam, amit a motor NEM ismer — a beallitas nemán hatastalan
    # maradt, es mind az ot valtozat BITRE UGYANAZT adta. Egy A/B, ami "nincs
    # kulonbseg"-et mond, mert a kapcsolo be sem volt kotve, rosszabb a semminel.
    if exit_cfg is None:
        rr["runner_stop"] = _rrm.RUNNER_KEEP
        rr["exit"] = {**_exsig.default_config(), "enabled": False}
    else:
        rr["runner_stop"] = _rrm.RUNNER_EXIT
        rr["exit"] = {**_exsig.default_config(), "enabled": True, **exit_cfg}
    return rr


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbols", default="")
    ap.add_argument("--months", type=int, default=12)
    ap.add_argument("--preset", default=_rrm.PRESET_SHIELD)
    a = ap.parse_args(argv)

    cfg = load_config(ROOT / "config.json")
    syms = ([s for s in a.symbols.split(",") if s] or
            sorted((cfg.get("pairs") or {}).keys()))

    valtozatok = [
        ("nincs kiszallasi jel", None),
        ("Supertrend (a mai)", {"indicator": _exsig.INDICATOR_SUPERTREND}),
        ("MA-szalag  (0-nal zar)", {"indicator": _exsig.INDICATOR_MA_STACK,
                                    "ma_min_agree": 1}),
        ("MA-szalag  (1 alatt)", {"indicator": _exsig.INDICATOR_MA_STACK,
                                  "ma_min_agree": 2}),
        ("MA-szalag  (2 alatt)", {"indicator": _exsig.INDICATOR_MA_STACK,
                                  "ma_min_agree": 3}),
    ]

    ossz = {nev: {"pnl": 0.0, "r": 0.0, "kotes": 0, "parok": 0}
            for nev, _ in valtozatok}
    for sym in syms:
        pair_cfg = (cfg.get("pairs") or {}).get(sym)
        # ⚠ A `pairs` blokkban NEM csak parok vannak: egy `_comment` sztring is
        # ul benne. Szotar-ellenorzes nelkul a ciklus egy `AttributeError`-ral
        # allt meg a felmeres kozepen.
        if not isinstance(pair_cfg, dict):
            continue
        from strategy import enabled_strategy_names
        nevek = list(enabled_strategy_names(cfg, sym))
        if not nevek:
            continue
        st = get_strategy_by_name(nevek[0])
        # ⚠ A KOZOS TAROLOT kerdezzuk (`core.params_store`), nem sajat utvonalat:
        # a fajlok `<strategia>/<par>.json` alatt vannak, es ezt a ret eget mar
        # egyszer megirtak. Sajat utvonal-osszerakassal "nincs mentett
        # parameter"-t kaptam mindenre, holott a fajlok megvoltak.
        from core.params_store import params_file
        f = params_file(sym, st.name)
        if not f.exists():
            print(f"{sym}: nincs mentett parameter ({st.name}) — kihagyva")
            continue
        m15, m1 = bt.load_data(sym)
        if m15 is None:
            print(f"{sym}: nincs elozmeny — kihagyva")
            continue
        p = {**st.base_params(cfg), **load_execution_params(sym, cfg),
             **(json.loads(f.read_text(encoding="utf-8")).get("params") or {})}
        p = {k: v for k, v in p.items() if not isinstance(v, (dict, list))}
        cut = m15.index.max() - pd.DateOffset(months=a.months)
        start = str(cut.tz_localize(None) if cut.tzinfo else cut)

        # ⚠ A JELOLT-LISTA EGYSZER epul: a kiszallas a VEGREHAJTAS oldalan hat,
        # a jel-parameterek valtozatlanok. Igy az ot valtozat egy epitest fizet,
        # ES garantaltan UGYANAZOKAT a belepoket kapja — a kulonbseg tisztan a
        # kiszallase.
        series, _ = bt.signal_series_cached(
            None, sym, m15, m1, p, pair_cfg, strategy=st, test_start=start)
        print(f"── {sym} / {st.name}  ({len(series.signals)} jelolt) "
              + "─" * max(0, 30 - len(sym)))
        print("   %-24s %6s %11s %8s %7s %8s" %
              ("valtozat", "kotes", "P&L", "ossz R", "PF", "talalat"))
        for nev, ex in valtozatok:
            res = bt.run_pair(sym, m15, m1, p, pair_cfg, cfg["trading"], 10000.0,
                              test_start=start, strategy=st, cfg=cfg,
                              exec_gates=True, signal_series=series,
                              rr=_rr(a.preset, ex))
            m = _metrics([t for t in res.closed if t.close_time is not None])
            print("   %-24s %6d %10.0f$ %8.2f %7.2f %6.0f%%" %
                  (nev, m["trades"], m["pnl"], m["ossz_r"], m["pf"], m["wr"] * 100))
            ossz[nev]["pnl"] += m["pnl"]
            ossz[nev]["r"] += m["ossz_r"]
            ossz[nev]["kotes"] += m["trades"]
            ossz[nev]["parok"] += 1

    print()
    print(f"OSSZESITES ({a.months} honap, preset={a.preset})")
    print("   %-24s %6s %11s %9s" % ("valtozat", "kotes", "P&L", "ossz R"))
    _alap = ossz.get("nincs kiszallasi jel", {})
    for nev, _ in valtozatok:
        o = ossz[nev]
        _k = ("" if nev == "nincs kiszallasi jel" or not _alap.get("parok")
              else f"   ({o['pnl'] - _alap['pnl']:+.0f}$)")
        print("   %-24s %6d %10.0f$ %9.2f%s" %
              (nev, o["kotes"], o["pnl"], o["r"], _k))
    return 0


if __name__ == "__main__":
    sys.exit(main())

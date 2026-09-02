"""MIT TENNE A KOLTSEG-KAPU, HA BE LENNE KAPCSOLVA? — A/B a valodi motoron.

⚠ A LELET (2026-09-02). A `cost` kapu a MESTER-LISTABAN nincs benne
(`dashboard.gate_order` = spread, tf_align, volatility), tehat SEHOL nem hat —
a GOLD-ra beallitott `{"wpr_sma": "block"}` HALOTT CONFIG. A rendszer ezt meg is
mondja (`effect_with_source` -> `master_off`), csak eddig senki nem kerdezte meg.

Kozben a kapu sajat merteke szerint harom par tartosan a kuszob (25%) FOLOTT van:

    BTCUSD +47%   EURGBP +44%   EURCHF +36%   Euro50 +23%   …   UsaTec +3%

Es a 2026-09-02-i mozgoatlag-meresek makacs kozos vonasa ugyanez volt: brutto
pozitiv, netto nulla — vagyis a korlat a KOLTSEG, nem a jelzes.

⚠ AMIT EZ MER, ES AMIT NEM. Ugyanaz a korlat, mint a `gate_ab.py`-nal: a mentett
parameterek walk-forwardon keszultek, tehat az ABSZOLUT szamok felfele
torzitanak. A KULONBSEG viszont ervenyes: minden valtozat UGYANAZOKAT a
belepoket kapja (a jelolt-lista egyszer epul), es csak a kapu ter el.

⚠ EZ A KAPU EGY DRAGA PARON NEM SZURO, HANEM ITELET. Ha a torzitas MEDIANJA a
kuszob folott van, akkor a kotesek TOBBSEGE kiesik — vagyis a kapu azt mondja,
hogy "ezt az instrumentumot ezzel a geometriaval ne kereskedd". Ezt ki kell
mondani, mert egy 90%-kal kevesebb kotes nem "finomhangolas".

Hasznalat:
    python tools/cost_gate_ab.py --months 18
    python tools/cost_gate_ab.py --symbols EURCHF,EURGBP,BTCUSD --months 24
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from core import applog
applog.harden_console()

import logging
logging.disable(logging.INFO)

from core import gate_layout as gl, gates as G
from core.execution_params import load_execution_params
from core.params_store import params_file
from strategy import enabled_strategy_names, get_strategy_by_name
from strategy.settings import load_config
from trading import backtest as bt


def _metrics(zart) -> dict:
    if not zart:
        return {"n": 0, "pnl": 0.0, "pf": 0.0, "wr": 0.0, "r": 0.0}
    pnl = sum(t.pnl_usd for t in zart)
    ny = sum(t.pnl_usd for t in zart if t.pnl_usd > 0)
    ve = -sum(t.pnl_usd for t in zart if t.pnl_usd < 0)
    r = 0.0
    for t in zart:
        try:
            r += t.pnl_usd / t.risk_usd if t.risk_usd else 0.0
        except (TypeError, ZeroDivisionError):
            pass
    return {"n": len(zart), "pnl": pnl, "pf": (ny / ve) if ve else float("inf"),
            "wr": sum(1 for t in zart if t.pnl_usd > 0) / len(zart), "r": r}


def _cfg_kapuval(cfg: dict, bekapcsol: bool, kuszob: float,
                 strategia: str) -> dict:
    """A config masolata a koltseg-kapuval BE vagy KI.

    ⚠ KET SZINT KELL. A mester-lista (`dashboard.gate_order`) mondja meg, hogy a
    kapu LETEZIK-e, a per-par `gates.cost` pedig hogy MIT tesz. Ha csak az egyiket
    allitanank, a beallitas nemán hatastalan maradna — pontosan ez tortent a
    GOLD-dal."""
    out = copy.deepcopy(cfg)
    rend = list(gl.enabled_gates(cfg))
    if bekapcsol and G.COST not in rend:
        rend.append(G.COST)
    if not bekapcsol and G.COST in rend:
        rend.remove(G.COST)
    out.setdefault("dashboard", {})["gate_order"] = rend
    for sym, pc in (out.get("pairs") or {}).items():
        if not isinstance(pc, dict):
            continue
        g = pc.setdefault("gates", {}).setdefault("cost", {})
        if isinstance(g, dict):
            g[strategia] = "block" if bekapcsol else "none"
            # ⚠ A KUSZOB IS IDE tartozik (`max_rr_distortion`), NEM egy kulon
            # `cost_gate` blokkba. Az elso valtozatomban oda irtam, es a motor
            # nemán az alapertelmezessel (25%) futott — mindharom "kulonbozo"
            # kuszob BITRE AZONOS eredmenyt adott. Csak ez a gyanus egyezes
            # arulta el; a futas maga hibatlannak latszott.
            if bekapcsol:
                g["max_rr_distortion"] = float(kuszob)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbols", default="")
    ap.add_argument("--months", type=int, default=18)
    ap.add_argument("--kuszobok", default="0.15,0.25,0.35")
    a = ap.parse_args(argv)

    cfg = load_config(ROOT / "config.json")
    syms = ([s for s in a.symbols.split(",") if s] or
            sorted(k for k, v in (cfg.get("pairs") or {}).items()
                   if isinstance(v, dict)))
    kuszobok = [float(x) for x in a.kuszobok.split(",") if x]

    ossz = {}
    for sym in syms:
        pc = cfg["pairs"][sym]
        nevek = list(enabled_strategy_names(cfg, sym))
        if not nevek:
            continue
        st = get_strategy_by_name(nevek[0])
        f = params_file(sym, st.name)
        if not f.exists():
            continue
        m15, m1 = bt.load_data(sym)
        if m15 is None:
            continue
        p = {**st.base_params(cfg), **load_execution_params(sym, cfg),
             **(json.loads(f.read_text(encoding="utf-8")).get("params") or {})}
        p = {k: v for k, v in p.items() if not isinstance(v, (dict, list))}
        cut = m15.index.max() - pd.DateOffset(months=a.months)
        start = str(cut.tz_localize(None) if cut.tzinfo else cut)
        series, _ = bt.signal_series_cached(
            None, sym, m15, m1, p, pc, strategy=st, test_start=start)

        valtozatok = [("kapu KI (a mai)", _cfg_kapuval(cfg, False, 0, st.name))]
        for k in kuszobok:
            valtozatok.append((f"kapu BE ({k:.0%})",
                               _cfg_kapuval(cfg, True, k, st.name)))

        print(f"── {sym} / {st.name} " + "─" * max(0, 34 - len(sym)))
        print("   %-18s %6s %11s %9s %7s" % ("valtozat", "kotes", "P&L", "ossz R", "PF"))
        for nev, c2 in valtozatok:
            # ⚠ A PAR-CONFIGOT IS A MODOSITOTT cfg-BOL. A kapu HATASA a `cfg`-bol
            # jon (`effects_for`), a KUSZOBE viszont a `pair_cfg`-bol
            # (`cost_max_distortion(pair_cfg, cfg)`). Az elso valtozatomban az
            # eredeti `pc`-t adtam at — igy a kapu bekapcsolt, de MINDIG a 25%-os
            # alapertelmezessel futott, es harom "kulonbozo" kuszob bitre azonos
            # eredmenyt adott. Ugyanaz a beallitas ket helyen lakik; egyet
            # atallitani nem eleg.
            _pc2 = c2["pairs"][sym]
            res = bt.run_pair(sym, m15, m1, p, _pc2, cfg["trading"], 10000.0,
                              test_start=start, strategy=st, cfg=c2,
                              exec_gates=True, signal_series=series)
            m = _metrics([t for t in res.closed if t.close_time is not None])
            print("   %-18s %6d %10.0f$ %9.2f %7.2f" %
                  (nev, m["n"], m["pnl"], m["r"], m["pf"]))
            o = ossz.setdefault(nev, {"n": 0, "pnl": 0.0, "r": 0.0})
            o["n"] += m["n"]
            o["pnl"] += m["pnl"]
            o["r"] += m["r"]

    print()
    print(f"OSSZESITES ({a.months} honap)")
    print("   %-18s %6s %11s %9s %10s" % ("valtozat", "kotes", "P&L", "ossz R", "kihagy"))
    _alap = ossz.get("kapu KI (a mai)")
    for nev, o in ossz.items():
        _k = ("" if not _alap or not _alap["n"] or nev == "kapu KI (a mai)"
              else f"{100 * (1 - o['n'] / _alap['n']):9.0f}%")
        print("   %-18s %6d %10.0f$ %9.2f %10s" % (nev, o["n"], o["pnl"], o["r"], _k))
    return 0


if __name__ == "__main__":
    sys.exit(main())

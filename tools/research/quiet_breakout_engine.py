"""A `quiet_breakout` a VALÓDI motoron (`run_pair`) — 2026-10-02.

Ugyanaz a belépő, mint a kutatásban (`strategies/quiet_breakout_rules.py`,
paritás-tesztelve), de a KERET végrehajtásával: bid/ask, egy pozíció/pár,
óra-kapu 10–20 (a gyertya-index KANONIKUS fal-óra = magyar idő, átváltás
nélkül), `none` preset (nincs BE/trailing — mint a kutatásban), TP = 15 R,
swap/jutalék a motor szerint. A 3. argumentum `ido` → IDŐ-KILÉPÉS: napvégi
zárás 21:45-kor + max. 8 óra tartás (a kutatás kilépése, v. `core.risk_reduction`).

Kimenet: 100-as kockázatra vetített átlag (R × 100), kötés/év, évenként.
"""
from __future__ import annotations

import json
import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
from core import broker_paths as _BP                      # noqa: E402
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

import core.applog as _applog
_applog.harden_console()

from core.execution_params import load_execution_params
from strategy import get_strategy
from strategy.settings import config_for_strategy
from trading.backtest import run_pair

HOURS = set(range(10, 21))          # 10:00–20:59 fal-óra (= magyar idő)
BALANCE = 10_000.0
RR: dict = {}


def run(sym, start, end, exec_gates, cfg, st):
    m15 = pd.read_parquet(_BP.bars_file("m15", sym))
    m1 = pd.read_parquet(_BP.bars_file("m1", sym))
    m1 = m1[~m1.index.duplicated(keep="last")].sort_index()
    m15 = m15[~m15.index.duplicated(keep="last")].sort_index()
    lo = pd.Timestamp(start, tz="UTC") - pd.Timedelta(days=60)
    hi = pd.Timestamp(end, tz="UTC") if end else None
    m1 = m1[(m1.index >= lo) & ((m1.index < hi) if hi is not None else True)]
    m15 = m15[(m15.index >= lo) & ((m15.index < hi) if hi is not None else True)]
    if len(m1) < 100_000:
        return None
    params = {**st.base_params(cfg), **(load_execution_params(sym, cfg) or {})}
    r = run_pair(sym, m15, m1, params, cfg["pairs"][sym], cfg["trading"], BALANCE,
                 strategy=st, cfg=cfg, exec_gates=exec_gates,
                 allowed_hours=HOURS, rr=RR, test_start=start, test_end=end)
    rows = [dict(sym=sym, open=pd.Timestamp(t.open_time), close=pd.Timestamp(t.close_time),
                 R=t.pnl_usd / t.risk_usd, swap_R=t.swap_usd / t.risk_usd,
                 status=t.status)
            for t in r.closed if t.risk_usd]
    return pd.DataFrame(rows)


def main():
    raw = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    cfg = config_for_strategy(raw, "quiet_breakout")
    st = get_strategy({"strategy": {"name": "quiet_breakout"}})
    assert st.name == "quiet_breakout", st.name
    period = _sys.argv[1]
    gates = "kapu" in _sys.argv[2:]
    global RR
    from core import risk_reduction as _rrm
    RR = {**_rrm.default_config(), "preset": "none"}
    if "ido" in _sys.argv[2:]:
        RR.update(eod_close="21:45", max_hold_min=480)
    syms = (["GOLD", "USDJPY", "UsaInd", "UsaTec", "Ger40"] if period == "regi" else
            ["UsaTec", "UsaInd", "GOLD", "USDJPY", "Ger40", "UK100", "EURUSD",
             "Usa500", "GBPUSD", "Jp225"])
    start, end = (("2013-06-01", "2023-01-01") if period == "regi" else ("2023-01-01", None))
    out = []
    for s in syms:
        try:
            df = run(s, start, end, gates, cfg, st)
        except Exception as e:                       # egy pár hibája ne vigye el a többit
            print(f"{s}: HIBA {type(e).__name__}: {e}", flush=True)
            continue
        if df is None or not len(df):
            print(f"{s}: nincs kotes / adat", flush=True)
            continue
        print(f"{s}: n={len(df)}  atlag {100*df.R.mean():+.2f}/kotes  swap {100*df.swap_R.mean():+.2f}  "
              f"median tartas {(df.close-df.open).median()}", flush=True)
        out.append(df)
    res = pd.concat(out, ignore_index=True)
    tag = ("_kapu" if gates else "") + ("_ido" if "ido" in _sys.argv[2:] else "")
    res.to_parquet(_BP.research_dir() / f"quiet_breakout_engine_{period}{tag}.parquet")
    print("kesz", len(res))


if __name__ == "__main__":
    main()

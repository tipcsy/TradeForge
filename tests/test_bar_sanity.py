"""Torott arak szurese a gyertya-epitesben (core/bar_sanity.py, 2026-10-07).

A broker tick-elozmenyeben TOROTT arak vannak (GOLD/USDJPY 2016-05-20 13:00-13:08:
bid 0,34 / 0,341), es a GerMid50-en ket maganyos, 0,45-os spreadu jegyzes 4%-kal
a piac alatt (2026-09-22). Egy kutatasi kotes ettol 9 evig nyitva maradt.

Ez a teszt ket iranyt orzi:
  * a torott ar NEM kerulhet gyertyaba (tick- es gyertya-szinten sem),
  * a VALODI kiugras (pl. 2025-04-07 16:13, +3-4% percek alatt) MEGMARAD — egy
    3%-os kiugras-szuro ezt dobta volna ki.
Es azt, hogy mindharom iro ut (build_bars, download_history tick- es natív ut)
ugyanazt a szurot hasznalja.
"""
import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

results = []


def check_(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from core import bar_sanity as S
from tools import build_bars as B
from tools import download_history as DH

POINT = 0.01
rng = np.random.default_rng(3)

# ── tick-szint: 1 ora, 2 tick/mp, ~1256-os ar; 13:00-13:08 torott tickek ────
n = 7200
t0 = pd.Timestamp("2016-05-20 12:30:00", tz="UTC")
tms = (int(t0.value // 1_000_000) + np.arange(n) * 500).astype("int64")
bid_pt = (125600 + np.cumsum(rng.integers(-2, 3, n))).astype("int64")
ask_pt = (bid_pt + 35).astype("int64")
t = pd.to_datetime(tms, unit="ms", utc=True)
win = (t >= "2016-05-20 13:00") & (t < "2016-05-20 13:09")
bad_bid = win & (np.arange(n) % 4 == 0)            # az ablak tickjeinek 1/4-e torott
bad_ask = win & (np.arange(n) % 4 == 1)            # masik 1/4-ben csak az ask torott
bid_pt[bad_bid] = 34
ask_pt[bad_ask] = 1382
ticks = pd.DataFrame({"time_msc": tms, "bid_pt": bid_pt, "ask_pt": ask_pt})

keep, ask_ok = S.tick_masks(tms, bid_pt, ask_pt)
check_("tick: a torott bid-u tickek kiesnek", not keep[bad_bid].any())
check_("tick: a jo tickek megmaradnak", keep[~bad_bid].all(), f"{(~keep[~bad_bid]).sum()} elveszett")
check_("tick: a torott ask spreadje ervenytelen", not ask_ok[bad_ask].any())
check_("tick: a jo ask spreadje ervenyes", ask_ok[~bad_ask & ~bad_bid].all())

bars = B._bars_from_ticks(ticks, "1min", POINT)
check_("build_bars: nincs 0,34-es low a gyertyakban", bars["low"].min() > 1000, str(bars["low"].min()))
check_("build_bars: a torott ask nem fujja fel a spreadet",
       bars["avg_spread"].max() < 1.0, f"{bars['avg_spread'].max():.2f}")
check_("build_bars: a torott ablak gyertyai MEGVANNAK (a jo tickekbol)",
       all(pd.Timestamp(f"2016-05-20 13:0{m}", tz="UTC") in bars.index for m in range(9)))

# a download_history tick-utja (MT5 tick-tomb alak: time mp, bid, ask) ugyanigy
raw = pd.DataFrame({"time": tms // 1000, "bid": bid_pt * POINT, "ask": ask_pt * POINT}).to_records(index=False)
b2 = DH._ticks_to_bars(raw, "1min")
check_("download_history: nincs 0,34-es low", b2["low"].min() > 1000, str(b2["low"].min()))
check_("download_history: a torott ask nem fujja fel a spreadet",
       b2["avg_spread"].max() < 1.0, f"{b2['avg_spread'].max():.2f}")

# ── gyertya-szint (nativ gyertya, tick nelkul) ────────────────────────────
idx = pd.date_range("2025-04-07 15:30", periods=120, freq="1min", tz="UTC")
c = 20000 + np.cumsum(rng.normal(0, 5, len(idx)))
df = pd.DataFrame({"open": c, "high": c + 5, "low": c - 5, "close": c,
                   "volume": 50.0, "avg_spread": 3.0}, index=idx)
# VALODI kiugras: 16:13-16:18 +4%, sok tick, normal spread
spike = (idx >= "2025-04-07 16:13") & (idx <= "2025-04-07 16:18")
df.loc[spike, ["open", "high", "low", "close"]] *= 1.04
# torott ar: egy gyertya low = 0,34
df.loc[idx[20], "low"] = 0.34
# beragadt jegyzes: 1 tick, 4% alatt, 0,45-os spread (a szokasos 3,0 helyett)
for k in (90, 95):
    df.loc[idx[k], ["open", "high", "low", "close"]] = df["close"].iloc[k] * 0.96
    df.loc[idx[k], ["volume", "avg_spread"]] = [1.0, 0.045]
# valodi, ritka (1 tickes) de normal spreadu mozgas: 2% alatt — MARAD
df.loc[idx[100], ["open", "high", "low", "close"]] = df["close"].iloc[100] * 0.975
df.loc[idx[100], "volume"] = 1.0

m = S.broken_bar_mask(df)
check_("gyertya: a lehetetlen ar (0,34) torott", bool(m.iloc[20]))
check_("gyertya: a beragadt jegyzesek torottek", bool(m.iloc[90]) and bool(m.iloc[95]))
check_("gyertya: a VALODI kiugras megmarad", not m[spike].any(), f"{m[spike].sum()} eldobva")
check_("gyertya: a ritka, de normal spreadu mozgas megmarad", not bool(m.iloc[100]))
check_("gyertya: mas nem esik ki", int(m.sum()) == 3, str(int(m.sum())))

cl = S.clean_bars(df, "TESZT", "M1")
check_("clean_bars: 3 gyertyaval kevesebb", len(cl) == len(df) - 3)
cl_tail = S.clean_bars(df, "TESZT", "M1", tail=30)
check_("clean_bars(tail): csak a farokban szur (a 20. gyertya marad)",
       idx[20] in cl_tail.index and idx[90] not in cl_tail.index and idx[95] not in cl_tail.index)

# spread nelkuli nativ gyertya: a 2. szabaly nem futhat (nincs mibol), az 1. igen
nat = df.drop(columns=["avg_spread"])
mn = S.broken_bar_mask(nat)
check_("nativ (spread nelkul): a 0,34 torott, a beragadt jegyzes nem dontheto el",
       bool(mn.iloc[20]) and not bool(mn.iloc[90]))

# ── a szerzodes: minden iro ut a szurot hivja ─────────────────────────────
dh = io.open(ROOT / "tools" / "download_history.py", encoding="utf-8").read()
bb = io.open(ROOT / "tools" / "build_bars.py", encoding="utf-8").read()
n_write = dh.count(".to_parquet(")
n_clean = dh.count("bar_sanity.clean_bars(")
check_("download_history: minden gyertya-iras elott clean_bars", n_write == n_clean,
       f"{n_write} iras, {n_clean} szuro")
check_("download_history: a tick-ut tick_masks-ot hiv", "bar_sanity.tick_masks(" in dh)
check_("build_bars: tick_masks + clean_bars", "bar_sanity.tick_masks(" in bb and "bar_sanity.clean_bars(" in bb)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

"""A POTOLT FAROK SPREADJE: a gap-fill ne hagyja NaN-on az avg_spread-et.

⚠ A LELET (2026-10-11). A `_fill_gap` nativ gyertyat ker (gyors, nem fogja a
terminalt), annak viszont NINCS avg_spread/close_spread-je. 2026-08-26 / 09-04
ota MINDEN otthoni par farka NaN-spreaddel nott, es a backteszt ott a par
`backtest_spread_points`-ere esett — USDJPY/GBPUSD-n 0.0 volt, tehat NULLA spread.

MIT ORZUNK:
  1. M1, tickbol epult fajl (van spread-oszlop), rovid res → a farok spreadje
     a res TICKJEIBOL jon;
  2. NATIV fajl (nincs spread-oszlop) → EGYETLEN tick-keres sincs (az uj
     szimbolum tick-szinkronja a motort is megallitja — lasd
     test_history_download_isolation);
  3. hosszu res → nincs tick-keres (a terminalt nem fogjuk percekig);
  4. M15 → a spread a szomszed M1-bol, terminal-hivas NELKUL;
  5. `repair_spread`: CSAK a NaN cellakat tolti, a meglevo erteket nem irja at.
⚠ Hamis MT5, ideiglenes mappa — a valodi data/-t, a configot es a terminalt nem erinti.
"""
import sys
import tempfile
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                                  # noqa: E402
applog.harden_console()

import numpy as np                                                       # noqa: E402
import pandas as pd                                                      # noqa: E402

from tools import download_history as DH                                 # noqa: E402

_results, _fail = [], []


def check(name, ok, detail=""):
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


NAP = dt.datetime(2026, 9, 22, tzinfo=dt.timezone.utc)      # kedd
T0 = int((NAP + dt.timedelta(hours=8)).timestamp())          # 08:00
SPREAD = 0.00003


class HamisMT5:
    COPY_TICKS_ALL = -1
    TIMEFRAME_M1, TIMEFRAME_M15 = 1, 15

    def __init__(self):
        self.tick_kerdes = []

    def copy_ticks_range(self, sym, a, b, flags):
        self.tick_kerdes.append((a, b))
        dtp = [("time", "<i8"), ("bid", "<f8"), ("ask", "<f8"), ("last", "<f8"),
               ("volume", "<u8"), ("time_msc", "<i8"), ("flags", "<u4"),
               ("volume_real", "<f8")]
        if a.date() != NAP.date():
            return np.array([], dtype=dtp)
        rec = [(T0 + i * 30, 1.1, 1.1 + SPREAD, 0.0, 0, (T0 + i * 30) * 1000, 6, 0.0)
               for i in range(120)]                          # 08:00–08:59, 30 mp-enkent
        return np.array(rec, dtype=dtp)

    def copy_rates_range(self, sym, tf, a, b):
        lepes = 60 * (15 if tf == self.TIMEFRAME_M15 else 1)
        n = 3600 // lepes
        rec = [(T0 + i * lepes, 1.1, 1.2, 1.0, 1.1, 5, 2, 0) for i in range(n)]
        return np.array(rec, dtype=[("time", "<i8"), ("open", "<f8"), ("high", "<f8"),
                                    ("low", "<f8"), ("close", "<f8"),
                                    ("tick_volume", "<u8"), ("spread", "<i4"),
                                    ("real_volume", "<u8")])

    def symbol_select(self, s, e=True):
        return True

    def last_error(self):
        return (1, "Success")


def meglevo(veg: dt.datetime, freq="1min", n=60, spread=True):
    idx = pd.date_range(end=veg, periods=n, freq=freq)
    df = pd.DataFrame({"open": 1.1, "high": 1.2, "low": 1.0, "close": 1.1,
                       "volume": 5}, index=idx)
    if spread:
        df["avg_spread"] = 0.00002
        df["close_spread"] = 0.00002
    return df


hamis = HamisMT5()
_regi = (DH.mt5, DH.ROOT, DH._NAPI_SZUNET, DH.TF_MAP)
DH.mt5, DH._NAPI_SZUNET = hamis, 0
DH.TF_MAP = {"M1": hamis.TIMEFRAME_M1, "M15": hamis.TIMEFRAME_M15}
TMP = Path(tempfile.mkdtemp())
DH.ROOT = TMP
m1_dir, m15_dir = TMP / "data" / "m1", TMP / "data" / "m15"
m1_dir.mkdir(parents=True)
m15_dir.mkdir(parents=True)
VEG = NAP + dt.timedelta(hours=10)
try:
    print("== 1. Tickbol epult M1, rovid res: a farok spreadje a tickekbol ==")
    f = m1_dir / "AAA.parquet"
    meglevo(NAP - dt.timedelta(hours=1)).to_parquet(f)          # hetfo 23:00-ig
    DH._fill_gap(f, "AAA", "M1", VEG)
    d = pd.read_parquet(f)
    uj = d[d.index >= pd.Timestamp(NAP + dt.timedelta(hours=8))]
    check("a res gyertyai bekerultek", len(uj) == 60, str(len(uj)))
    check("a farok avg_spread-je NEM NaN", uj["avg_spread"].notna().all(),
          str(uj["avg_spread"].isna().sum()))
    check("...es a tickek valodi spreadje", np.allclose(uj["avg_spread"], SPREAD))
    check("a close_spread is potolva", uj["close_spread"].notna().all())
    check("a regi gyertyak spreadje valtozatlan",
          np.allclose(d[d.index < pd.Timestamp(NAP)]["avg_spread"], 0.00002))
    check("napi darabokban kert tickek (legfeljebb a res napjai)",
          0 < len(hamis.tick_kerdes) <= 3, str(len(hamis.tick_kerdes)))

    print("\n== 2. NATIV fajl (nincs spread-oszlop): EGYETLEN tick-keres sincs ==")
    hamis.tick_kerdes.clear()
    f = m1_dir / "BBB.parquet"
    meglevo(NAP - dt.timedelta(hours=1), spread=False).to_parquet(f)
    DH._fill_gap(f, "BBB", "M1", VEG)
    check("nincs tick-keres", not hamis.tick_kerdes, str(len(hamis.tick_kerdes)))
    check("a nativ fajl nativ marad (nem kap fel-NaN spread-oszlopot)",
          "avg_spread" not in pd.read_parquet(f).columns)

    print("\n== 3. Hosszu res: nem fogjuk percekig a terminalt ==")
    hamis.tick_kerdes.clear()
    f = m1_dir / "CCC.parquet"
    meglevo(NAP - dt.timedelta(days=DH.GAP_SPREAD_TICK_DAYS + 3)).to_parquet(f)
    DH._fill_gap(f, "CCC", "M1", VEG)
    check("nincs tick-keres", not hamis.tick_kerdes, str(len(hamis.tick_kerdes)))
    check("a gyertyak megis bekerultek (spread nelkul)",
          len(pd.read_parquet(f)) == 120)

    print("\n== 4. M15: a spread a szomszed M1-bol, terminal-hivas nelkul ==")
    hamis.tick_kerdes.clear()
    f15 = m15_dir / "AAA.parquet"
    meglevo(NAP - dt.timedelta(hours=1), freq="15min", n=8).to_parquet(f15)
    DH._fill_gap(f15, "AAA", "M15", VEG)
    d15 = pd.read_parquet(f15)
    uj15 = d15[d15.index >= pd.Timestamp(NAP + dt.timedelta(hours=8))]
    check("nincs tick-keres", not hamis.tick_kerdes, str(len(hamis.tick_kerdes)))
    check("az M15 farok spreadje az M1-bol", len(uj15) == 4
          and np.allclose(uj15["avg_spread"], SPREAD), str(uj15["avg_spread"].tolist()))

    print("\n== 5. repair_spread: CSAK a NaN cellak ==")
    hamis.tick_kerdes.clear()
    f = m1_dir / "DDD.parquet"
    idx = pd.date_range(NAP + dt.timedelta(hours=7), periods=120, freq="1min")
    d = pd.DataFrame({"open": 1.1, "high": 1.2, "low": 1.0, "close": 1.1,
                      "volume": 5, "avg_spread": 0.00002, "close_spread": 0.00002},
                     index=idx)
    d.loc[d.index >= pd.Timestamp(NAP + dt.timedelta(hours=8)),
          ["avg_spread", "close_spread"]] = np.nan            # a nativ farok
    d.to_parquet(f)
    f15 = m15_dir / "DDD.parquet"
    d15 = d.resample("15min").agg({"open": "first", "high": "max", "low": "min",
                                   "close": "last", "volume": "sum",
                                   "avg_spread": "mean", "close_spread": "last"})
    d15.to_parquet(f15)
    msg = DH.repair_spread("DDD", days=30)
    r = pd.read_parquet(f)
    elso, farok = r.iloc[:60], r.iloc[60:]
    check("a NaN farok potolva", farok["avg_spread"].notna().all()
          and np.allclose(farok["avg_spread"], SPREAD), msg)
    check("a meglevo ertek NEM irodott at", np.allclose(elso["avg_spread"], 0.00002))
    check("az OHLC erintetlen", (r["close"] == 1.1).all() and len(r) == 120)
    r15 = pd.read_parquet(f15)
    check("az M15 NaN-ja is potolva (az M1-bol)", r15["avg_spread"].notna().all(),
          str(r15["avg_spread"].tolist()))
    check("nincs maradek .tmp fajl", not list(TMP.rglob("*.tmp")))

    hamis.tick_kerdes.clear()
    msg = DH.repair_spread("BBB", days=30)
    check("nativ fajlon: kihagyja, tick-keres nelkul",
          "NINCS spread" in msg and not hamis.tick_kerdes, msg)
finally:
    DH.mt5, DH.ROOT, DH._NAPI_SZUNET, DH.TF_MAP = _regi

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)

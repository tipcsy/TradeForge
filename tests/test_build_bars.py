"""Gyertya-epites tickbol: a batch-hataron atnyulo gyertya NE csusszon el.

A kockazatos resz: egy honapnyi tick tul nagy egyben (UsaTec ~18M sor / ~440 MB),
ezert row-group-onkent olvassuk. Egy gyertya viszont ATNYULHAT ket batch kozott —
ha az utolso, meg nem lezart gyertyat aggregalnank, ketto lenne belole, rossz
OHLC-vel. A megoldas: a lezaratlan gyertya tickjeit atvisszuk a kovetkezo batchbe.

Ez a teszt azt orzi, hogy a DARABOLT epites BITAZONOS az egyben szamolttal, es
hogy a keplet ugyanaz, mint a `download_history._ticks_to_bars`-e (bid-alapu OHLC
+ avg_spread + close_spread) — kulonben a backteszt es az elo eredmeny széttartana.
"""
import io
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

results = []


def check_(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from tools import build_bars as B

TMP = Path(tempfile.mkdtemp(prefix="tf_bars_"))
B.TICK_DIR = TMP
check_("a teszt a sajat temp-konyvtaraba ir", str(B.TICK_DIR).startswith(str(TMP)))

POINT = 0.01
SYM = "TESZT"

# ── szintetikus tick-folyam: 3 ora, masodpercenkent egy tick ───────────────
rng = np.random.default_rng(7)
n = 3 * 3600
t0 = pd.Timestamp("2024-03-04 09:00:00", tz="UTC")
tms = (int(t0.value // 1_000_000) + np.arange(n) * 1000).astype("int64")
bid_pt = (200000 + np.cumsum(rng.integers(-3, 4, n))).astype("int64")
ask_pt = (bid_pt + rng.integers(1, 6, n)).astype("int64")
ticks = pd.DataFrame({"time_msc": tms, "bid_pt": bid_pt, "ask_pt": ask_pt})

# egyben szamolt referencia
ref = B._bars_from_ticks(ticks, "15min", POINT)
check_("referencia: 3 ora / 15 perc = 12 gyertya", len(ref) == 12, str(len(ref)))
check_("...a keplet BID-alapu (a close a bid utolso erteke)",
       abs(ref["close"].iloc[0] - bid_pt[899] * POINT) < 1e-12)
check_("...avg_spread = a baron beluli ATLAG",
       abs(ref["avg_spread"].iloc[0]
           - ((ask_pt[:900] - bid_pt[:900]) * POINT).mean()) < 1e-12)
check_("...close_spread = az UTOLSO tick spreadje",
       abs(ref["close_spread"].iloc[0]
           - (ask_pt[899] - bid_pt[899]) * POINT) < 1e-12)
check_("...volume = tick-darabszam", int(ref["volume"].iloc[0]) == 900,
       str(ref["volume"].iloc[0]))

# ── ugyanaz DARABOLVA: tobb parquet-fajl + kicsi batch ────────────────────
d = TMP / SYM
d.mkdir(parents=True, exist_ok=True)
# ket "havi" fajlra vagjuk, hogy a FAJL-hatar is atnyuljon egy gyertyan
cut = 4321                       # szandekosan NEM gyertya-hataron
ticks.iloc[:cut].to_parquet(d / "2024-03.parquet", index=False)
ticks.iloc[cut:].to_parquet(d / "2024-04.parquet", index=False)

for batch in (1000, 997, 100000):
    B.BATCH_ROWS = batch
    got = B.build_symbol(SYM, "M15", POINT)
    same = (len(got) == len(ref)) and np.allclose(
        got[B.COLS].to_numpy(), ref[B.COLS].to_numpy(), rtol=0, atol=1e-12)
    check_(f"darabolt epites (batch={batch}) BITAZONOS az egybenivel", same,
           f"{len(got)} vs {len(ref)}")

# a legkenyesebb: a batch-hatar PONT egy gyertya kozepere essen
B.BATCH_ROWS = 900 + 450         # 1.5 gyertya
got = B.build_symbol(SYM, "M15", POINT)
check_("batch-hatar a gyertya KOZEPEN sem csuszik el",
       len(got) == len(ref) and np.allclose(got[B.COLS].to_numpy(),
                                            ref[B.COLS].to_numpy(), atol=1e-12))

# M1-en is (sok kicsi gyertya, sok hatar)
B.BATCH_ROWS = 1000
ref1 = B._bars_from_ticks(ticks, "1min", POINT)
got1 = B.build_symbol(SYM, "M1", POINT)
check_("M1: 180 gyertya, darabolva is egyezik",
       len(got1) == len(ref1) == 180 and np.allclose(
           got1[B.COLS].to_numpy(), ref1[B.COLS].to_numpy(), atol=1e-12),
       f"{len(got1)} vs {len(ref1)}")

# ── ervenytelen ask (ask_pt = 0): a tick SZAMIT, a spread nem ─────────────
tk = pd.DataFrame({
    "time_msc": [int(t0.value // 1_000_000) + i * 1000 for i in range(4)],
    "bid_pt":   [100, 110, 90, 105],
    "ask_pt":   [102, 0, 92, 107],        # a masodiknal ervenytelen az ask
}).astype("int64")
bb = B._bars_from_ticks(tk, "15min", POINT)
check_("ervenytelen ask: a tick a VOLUMENBE beleszamit",
       int(bb["volume"].iloc[0]) == 4, str(bb["volume"].iloc[0]))
check_("...az OHLC-be is (a high a 110-es bid)",
       abs(bb["high"].iloc[0] - 110 * POINT) < 1e-12)
check_("...a spread-atlagba viszont NEM (csak a 3 ervenyes)",
       abs(bb["avg_spread"].iloc[0] - np.mean([2, 2, 2]) * POINT) < 1e-12,
       str(bb["avg_spread"].iloc[0]))


# ── a MEGLEVO parquet-tel valo osszevetes ─────────────────────────────────
old = TMP / "regi.parquet"
ref.to_parquet(old)
c = B.compare(got, old)
check_("azonos adat -> az osszevetes OK", c["allapot"] == "OK", str(c))
check_("...az atfedes a teljes hossz", c["atfedes"] == 12, str(c["atfedes"]))

rossz = ref.copy()
rossz.iloc[3, rossz.columns.get_loc("close")] += 5.0
rossz.to_parquet(old)
c2 = B.compare(got, old)
check_("elteres eseten SZOL (nem nyeli el)", c2["allapot"] != "OK", str(c2))
check_("...es megmondja, hany ertek ter el", c2["eltero_close"] == 1,
       str(c2.get("eltero_close")))

# ── a MEGLEVO fajl FRISSEBB farkat meg kell orizni ────────────────────────
# (A meglevo data/m1/Ger40.parquet 2026-08-27 14:08-ig tart, a tick-tarbol
#  epitett viszont csak 2026-08-26 21:59-ig: a letolto "tegnapig" tolt, a live
#  a mai gyertyakat is beirta. Felulirasnal ezek elvesznenek.)
src_w = io.open(ROOT / "tools" / "build_bars.py", encoding="utf-8").read()
check_("a meglevo fajl UJABB sorait hozzafuzi (nem dobja el)",
       "regi.index > bars.index[-1]" in src_w)
check_("...es ha a meglevo fajl olvashatatlan, INKABB nem ir",
       'NEM írok, hogy ne vesszen adat' in src_w)


# ── a szerzodes ───────────────────────────────────────────────────────────
src = io.open(ROOT / "tools" / "build_bars.py", encoding="utf-8").read()
check_("alapbol NEM ir (csak --write eseten)",
       'if args.write:' in src and '"--write", action="store_true"' in src)
check_("a bar cimkeje a NYITO ido (label=left)", 'label="left"' in src)
check_("row-group-onkent olvas (nem egyben)", "iter_batches" in src)

import shutil
shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

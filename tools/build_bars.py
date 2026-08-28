"""Gyertya-építő: tick → M1/M5/M15/H1/… parquet.

A `core/docs/tick_storage.md` terv 3. lépése. A tick a FORRÁS, a gyertya
származtatott — de a fájl **egyszer épül és marad a lemezen**: minden backteszt
és optimalizálás abból dolgozik, ahogy eddig is.

**A képlet NEM új.** Pontosan azt csinálja, amit a `tools/download_history.py`
`_ticks_to_bars`-a: a gyertya BID árból épül (az MT5 chart és a Strategy Tester
is BID-et rajzol; az ASK csak a végrehajtásnál jelenik meg), mellé megy az
`avg_spread` (a báron belüli ÁTLAG — az intrabar SL/TP-trigger becsléséhez) és a
`close_spread` (az UTOLSÓ tick spreadje — a belépő a gyertya ZÁRÁSÁN keletkezik,
ott ez a pontos). Ha ez a kettő elcsúszna, a backteszt és az élő eredmény
azonnal széttartana.

**Konstans memória.** Egy hónapnyi UsaTec tick ~18 millió sor (~440 MB) — nem
olvassuk be egyben. A parquet row-group-onként érkezik (`iter_batches`), és mivel
egy gyertya átnyúlhat két batch között, az utolsó, még NEM LEZÁRT gyertya
tickjeit átvisszük a következő batchbe. Így a mérleg pontos, a memória konstans.

**Alapból NEM ÍR.** Előbb ELLENŐRIZ: a meglévő `data/m1/<SYM>.parquet`-tel
összeveti az átfedő szakaszt. Ha a tickből épített gyertya nem egyezik a
korábban letöltöttel, az hiba — és jobb, ha kiderül, mielőtt felülírjuk a
rendszer élő adatát. Írni a `--write` kapcsolóval ír.

Futtatás:

    python tools/build_bars.py --symbols Ger40 --tfs M1,M15
    python tools/build_bars.py --symbols Ger40 --tfs M1,M15 --write
    python tools/build_bars.py --status
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-8s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

TICK_DIR = ROOT / "data" / "ticks"
MANIFEST_DIR = ROOT / "data" / "bars_manifest"
BUILDER_VERSION = 1
BATCH_ROWS = 2_000_000              # ~48 MB tick egy batchben

# A `download_history.RESAMPLE` konvenciója — ugyanaz a címkézés (a bar a NYITÓ
# idejével azonosított), különben a jelzés-időzítés csúszna.
TF_FREQ = {"M1": "1min", "M5": "5min", "M15": "15min", "M30": "30min",
           "H1": "1h", "H4": "4h", "D1": "1D"}
TF_DIR = {"M1": "m1", "M5": "m5", "M15": "m15", "M30": "m30",
          "H1": "h1", "H4": "h4", "D1": "d1"}
COLS = ["open", "high", "low", "close", "volume", "avg_spread", "close_spread"]


def month_files(sym: str) -> list[Path]:
    d = TICK_DIR / sym
    if not d.is_dir():
        return []
    out = sorted(d.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9].parquet"))
    days = sorted((d / "_napok").glob("*.parquet"))
    return out + days                # a még össze nem vont napok is számítanak


def _bars_from_ticks(df: pd.DataFrame, freq: str, point: float) -> pd.DataFrame:
    """Tick → gyertya. UGYANAZ a képlet, mint a `download_history._ticks_to_bars`.

    A tárolt ár PONTBAN van (int64) — itt váltjuk vissza árra."""
    if df.empty:
        return pd.DataFrame(columns=COLS)
    idx = pd.to_datetime(df["time_msc"].to_numpy(), unit="ms", utc=True)
    bid_pt = df["bid_pt"].to_numpy(dtype=np.float64)
    ask_pt = df["ask_pt"].to_numpy(dtype=np.float64)
    bid = bid_pt * point
    # `ask_pt == 0` = érvénytelen ask (lásd `download_ticks.to_frame`): a tick a
    # volumenbe és az OHLC-be BELESZÁMÍT, a spread-átlagba nem. Ugyanaz, mint a
    # `download_history._ticks_to_bars` NaN-os spreadje.
    spread = np.where(ask_pt > 0, (ask_pt - bid_pt) * point, np.nan)
    s = pd.DataFrame({"bid": bid, "spread": spread}, index=idx)
    r = s["bid"].resample(freq, label="left", closed="left")
    out = r.ohlc()
    out["volume"] = r.count()
    sp = s["spread"].resample(freq, label="left", closed="left")
    out["avg_spread"] = sp.mean()
    out["close_spread"] = sp.last()
    out = out.dropna(subset=["open"])
    return out[out["volume"] > 0][COLS]


def build_symbol(sym: str, tf: str, point: float) -> pd.DataFrame:
    """A teljes tick-tár → egy időkeret gyertyái. Konstans memóriával."""
    freq = TF_FREQ[tf]
    files = month_files(sym)
    if not files:
        return pd.DataFrame(columns=COLS)
    parts: list[pd.DataFrame] = []
    carry = pd.DataFrame(columns=["time_msc", "bid_pt", "ask_pt"]).astype("int64")
    for f in files:
        pf = pq.ParquetFile(f)
        for batch in pf.iter_batches(batch_size=BATCH_ROWS,
                                     columns=["time_msc", "bid_pt", "ask_pt"]):
            df = batch.to_pandas()
            if df.empty:
                continue
            if len(carry):
                df = pd.concat([carry, df], ignore_index=True)
            # ⚠ Az UTOLSÓ gyertya még nem biztos, hogy lezárult (átnyúlhat a
            # következő batchbe/hónapba) — a tickjeit átvisszük, nem aggregáljuk.
            last_ts = pd.Timestamp(int(df["time_msc"].iloc[-1]), unit="ms", tz="UTC")
            cut = last_ts.floor(freq)
            cut_ms = int(cut.value // 1_000_000)
            done = df[df["time_msc"] < cut_ms]
            carry = df[df["time_msc"] >= cut_ms].reset_index(drop=True)
            if len(done):
                parts.append(_bars_from_ticks(done, freq, point))
    if len(carry):
        parts.append(_bars_from_ticks(carry, freq, point))
    if not parts:
        return pd.DataFrame(columns=COLS)
    out = pd.concat(parts)
    return out[~out.index.duplicated(keep="last")].sort_index()


def compare(new: pd.DataFrame, old_path: Path) -> dict:
    """A tickből épített gyertyák vs. a MEGLÉVŐ parquet az átfedő szakaszon."""
    if not old_path.exists():
        return {"allapot": "nincs meglévő fájl", "atfedes": 0}
    old = pd.read_parquet(old_path)
    common = new.index.intersection(old.index)
    if len(common) == 0:
        return {"allapot": "nincs átfedés", "atfedes": 0}
    a, b = new.loc[common], old.loc[common]
    res = {"allapot": "OK", "atfedes": len(common),
           "meglevo_sor": len(old), "uj_sor": len(new)}
    for c in ("open", "high", "low", "close"):
        d = (a[c] - b[c]).abs()
        res[f"max_elteres_{c}"] = float(d.max())
        res[f"eltero_{c}"] = int((d > 1e-9).sum())
    rossz = sum(res[f"eltero_{c}"] for c in ("open", "high", "low", "close"))
    if rossz:
        res["allapot"] = f"⚠ {rossz} eltérő OHLC érték"
    return res


def write_manifest(sym: str, tf: str, first, last, rows: int) -> None:
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    p = MANIFEST_DIR / f"{sym}_{tf}.json"
    payload = {
        "symbol": sym, "tf": tf,
        "source_from": str(first), "source_to": str(last), "rows": rows,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "builder_version": BUILDER_VERSION,
    }
    tmp = p.with_suffix(".tmp")
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    tmp.replace(p)


def status(syms) -> pd.DataFrame:
    rows = []
    for sym in syms:
        files = month_files(sym)
        size = sum(f.stat().st_size for f in files)
        man = {}
        for tf in ("M1", "M15"):
            p = MANIFEST_DIR / f"{sym}_{tf}.json"
            if p.exists():
                try:
                    man[tf] = json.load(io.open(p, encoding="utf-8"))["built_at"][:16]
                except Exception:
                    man[tf] = "?"
        rows.append({"symbol": sym, "tick_fajl": len(files),
                     "tick_MB": round(size / 1e6, 1),
                     "elso": files[0].stem if files else "—",
                     "utolso": files[-1].stem if files else "—",
                     "M1_epult": man.get("M1", "—"),
                     "M15_epult": man.get("M15", "—")})
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", default="", help="vesszős lista")
    ap.add_argument("--tfs", default="M1,M15", help="pl. M1,M5,M15,H1")
    ap.add_argument("--write", action="store_true",
                    help="ÍRJA is a data/<tf>/<SYM>.parquet fájlokat "
                         "(alapból csak ellenőriz)")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    cfg = json.load(io.open(ROOT / "config.json", encoding="utf-8"))
    pairs = {k: v for k, v in cfg["pairs"].items() if k != "_comment"}
    syms = ([s.strip() for s in args.symbols.split(",") if s.strip()] or
            sorted(p.name for p in TICK_DIR.iterdir() if p.is_dir())
            if TICK_DIR.is_dir() else [])
    if args.status:
        print(status(syms).to_string(index=False))
        return 0

    tfs = [t.strip().upper() for t in args.tfs.split(",") if t.strip()]
    for tf in tfs:
        if tf not in TF_FREQ:
            log.error("ismeretlen időkeret: %s (van: %s)", tf, ", ".join(TF_FREQ))
            return 1

    rows = []
    for sym in syms:
        point = float((pairs.get(sym) or {}).get("point_size", 0.0) or 0.0)
        if point <= 0:
            log.warning("%s — nincs point_size a configban, kihagyva", sym)
            continue
        if not month_files(sym):
            log.warning("%s — nincs tick-adat, kihagyva", sym)
            continue
        for tf in tfs:
            log.info("%s %s — építés…", sym, tf)
            bars = build_symbol(sym, tf, point)
            if bars.empty:
                log.warning("%s %s — 0 gyertya", sym, tf)
                continue
            out = ROOT / "data" / TF_DIR[tf] / f"{sym}.parquet"
            cmp_ = compare(bars, out)
            log.info("%s %s — %s gyertya (%s … %s) | összevetés: %s",
                     sym, tf, f"{len(bars):,}", bars.index[0], bars.index[-1],
                     cmp_.get("allapot"))
            if args.write:
                # ⚠ A MEGLÉVŐ fájl VÉGE frissebb lehet, mint a tick-tár: a
                # letöltő „tegnapig" tölt, a live viszont a mai gyertyákat is
                # beírta. Felülírásnál ezek elvesznének, és az élő rendszer a
                # mai napra vakon maradna. Ezért a régi fájl ÚJABB sorait
                # hozzáfűzzük — nem dobjuk el.
                farok = 0
                if out.exists():
                    try:
                        regi = pd.read_parquet(out)
                        ujabb = regi[regi.index > bars.index[-1]]
                        if len(ujabb):
                            bars = pd.concat([bars, ujabb[COLS]])
                            farok = len(ujabb)
                    except Exception as ex:
                        log.error("%s %s — a meglévő fájl nem olvasható (%s); "
                                  "NEM írok, hogy ne vesszen adat.", sym, tf, ex)
                        continue
                out.parent.mkdir(parents=True, exist_ok=True)
                tmp = out.with_suffix(".tmp")
                bars.to_parquet(tmp)
                tmp.replace(out)
                write_manifest(sym, tf, bars.index[0], bars.index[-1], len(bars))
                log.info("   → megírva: %s (%s sor%s)", out, f"{len(bars):,}",
                         f", ebből {farok} a régi fájl frissebb farka"
                         if farok else "")
            rows.append({"symbol": sym, "tf": tf, "gyertya": len(bars),
                         "elso": str(bars.index[0])[:16],
                         "utolso": str(bars.index[-1])[:16], **cmp_})
    if rows:
        pd.set_option("display.width", 220)
        keep = ["symbol", "tf", "gyertya", "elso", "utolso", "allapot",
                "atfedes", "meglevo_sor", "max_elteres_close"]
        df = pd.DataFrame(rows)
        print()
        print(df[[c for c in keep if c in df]].to_string(index=False))
    if not args.write:
        print("\n(Csak ELLENŐRZÉS volt — írni a `--write` kapcsolóval ír.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Tick-letöltő — NAPI batchekben, folytathatóan, konstans memóriával.

A `core/docs/tick_storage.md` terv 2. lépése. Miért pont így:

**Napi batch.** Az MT5-ön át a letöltés drága. Egy hónap tickje egyben tipikusan
`None`-t ad (belső limit/memória), és ha félbeszakad, az egész hónap kárba vész.
Egy nap = egy `copy_ticks_range` hívás = egy fájl. Ennél kisebb szelet nem éri
meg (a hívás fix költsége dominálna), nagyobb pedig a fenti hibákba fut.

**A napi fájl MAGA az állapot.** Nincs külön állapot-fájl, ami elromolhat vagy
széttarthat a valósággal: ami napra van fájl, az megvan. Így a folytatás
triviális, és egy megszakadt futás után nem kell semmit kézzel takarítani.
Az üres napokat (hétvége, ünnep) 0 soros fájl jelöli — különben minden újrafutás
megpróbálná őket megint.

**Konstans memória.** Egyszerre EGY nap van a RAM-ban (a legnagyobb mért
szimbólum, UsaTec: ~833 ezer tick ≈ 20 MB). A havi összevonás `ParquetWriter`-rel
streamel: napról napra ír, nem gyűjt.

**Megszakadás.** Minden fájl `.tmp`-be íródik és `replace`-szel kerül a helyére
(félkész fájl sosem marad). Kapcsolat-vesztésnél újracsatlakozik és újrapróbál;
Ctrl+C-re a futó napot befejezi, majd tisztán kilép.

⚠ NE FUSSON EGYSZERRE A `main.py live`-VAL. A letöltés fogja az MT5 terminált,
és a második processz `mt5.initialize()`-e beáll — a dashboard főablaka meg sem
jelenik (lásd a terv 6. szakaszát).

Futtatás:

    python tools/download_ticks.py --status
    python tools/download_ticks.py --symbols Ger40 --from 2021-10-08
    python tools/download_ticks.py --symbols Ger40,UsaInd --all-history
    python tools/download_ticks.py --symbols GOLD --from 2021-01-01 --consolidate
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import MetaTrader5 as mt5                     # noqa: E402
from core import mt5_connector                # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-8s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

TICK_DIR = ROOT / "data" / "ticks"
DAY_RETRIES = 3            # egy napra ennyiszer próbálkozunk
RETRY_SLEEP = 3.0          # mp az újrapróbálkozások közt
POLITE_SLEEP = 0.05        # mp két nap közt (ne fojtsuk meg a terminált)

# A tároló-séma. Az ár PONTBAN, egészként: float32-ben a legalsó pont elveszne —
# épp az, amiből a spread áll. Lásd `core/docs/tick_storage.md`.
SCHEMA = pa.schema([("time_msc", pa.int64()),
                    ("bid_pt", pa.int64()),
                    ("ask_pt", pa.int64())])

_stop = False              # Ctrl+C → a futó nap után tisztán megállunk


def _on_sigint(signum, frame):
    global _stop
    if _stop:                       # második Ctrl+C: azonnal
        raise KeyboardInterrupt
    _stop = True
    log.warning("Megszakítás kérve — a futó nap után tisztán leállok "
                "(még egy Ctrl+C = azonnali).")


# ---------------------------------------------------------------------------
# útvonalak
# ---------------------------------------------------------------------------

def day_dir(sym: str) -> Path:
    return TICK_DIR / sym / "_napok"


def day_file(sym: str, d: datetime) -> Path:
    return day_dir(sym) / f"{d:%Y-%m-%d}.parquet"


def month_file(sym: str, year: int, month: int) -> Path:
    return TICK_DIR / sym / f"{year:04d}-{month:02d}.parquet"


def _write_atomic(df: pd.DataFrame, path: Path) -> None:
    """`.tmp` → `replace`: félkész fájl sosem marad a helyén."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    table = pa.Table.from_pandas(df, schema=SCHEMA, preserve_index=False)
    pq.write_table(table, tmp, compression="zstd")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# letöltés
# ---------------------------------------------------------------------------

def to_frame(ticks, point: float) -> pd.DataFrame:
    """MT5 tick-tömb → a tároló-alak. A `download_history._ticks_to_bars`
    szűrését követi, hogy a gyertyák bitre egyezzenek vele.

    ⚠ NINCS DEDUPLIKÁLÁS. Több VALÓDI tick osztozhat ugyanazon az
    ezredmásodpercen; ha azokat eldobjuk, a volumen csökken és a `high`/`low`
    LEVÁGÓDIK. Mérve (Ger40, 581 ezer bar): −3,6% tick, a barok 68,9%-án
    kevesebb, a `high` átlagosan 0,022 ponttal lejjebb, a `low` 0,0145-tel
    feljebb. Ezt a `build_bars.py` összevetése fogta meg.

    ⚠ A sor akkor is KELL, ha csak az ask érvénytelen: a gyertya BID-ből épül,
    tehát a tick a volumenbe és az OHLC-be beleszámít — csak a spreadbe nem.
    Ilyenkor `ask_pt = 0` a jelölés (a build ezt NaN spreadnek veszi)."""
    names = ticks.dtype.names or ()
    tms = (ticks["time_msc"].astype("int64") if "time_msc" in names
           else ticks["time"].astype("int64") * 1000)
    bid = ticks["bid"].astype(float)
    ask = ticks["ask"].astype(float)
    ok = bid > 0                       # a bar BID-ből épül → ez a feltétel
    b = bid[ok]
    a = ask[ok]
    ask_ok = (a > 0) & (a > b)
    df = pd.DataFrame({
        "time_msc": tms[ok],
        "bid_pt": np.round(b / point).astype("int64"),
        "ask_pt": np.where(ask_ok, np.round(a / point), 0).astype("int64"),
    })
    return df.sort_values("time_msc", kind="stable").reset_index(drop=True)


def fetch_day(sym: str, d: datetime, point: float, cfg: dict) -> "pd.DataFrame | None":
    """EGY nap tickjei. None = nem sikerült (a hívó ilyenkor NEM ír fájlt, hogy
    a következő futás újrapróbálja); üres DataFrame = tényleg nincs adat."""
    for attempt in range(DAY_RETRIES):
        with mt5_connector.MT5_LOCK:
            t = mt5.copy_ticks_range(sym, d, d + timedelta(days=1),
                                     mt5.COPY_TICKS_ALL)
        if t is not None:
            return to_frame(t, point) if len(t) else pd.DataFrame(
                {"time_msc": [], "bid_pt": [], "ask_pt": []}).astype("int64")
        err = mt5.last_error()
        # −10004/−10005 (nincs kapcsolat) → újracsatlakozás
        if attempt < DAY_RETRIES - 1:
            log.debug("%s %s — %s, újrapróba", sym, d.date(), err)
            time.sleep(RETRY_SLEEP)
            if err and err[0] in (-10004, -10005, -10003):
                try:
                    mt5_connector.ensure_connected(cfg)
                except Exception as ex:
                    log.warning("újracsatlakozás sikertelen: %s", ex)
    log.warning("%s %s — %d próba után sem jött adat (%s). Kihagyva, a "
                "következő futás újrapróbálja.", sym, d.date(), DAY_RETRIES,
                mt5.last_error())
    return None


def download_symbol(sym: str, start: datetime, end: datetime, cfg: dict) -> dict:
    with mt5_connector.MT5_LOCK:
        if not mt5.symbol_select(sym, True):
            log.error("%s — nem választható ki", sym)
            return {}
        info = mt5.symbol_info(sym)
    point = float(getattr(info, "point", 0.0) or 0.0)
    if point <= 0:
        log.error("%s — nincs érvényes point_size", sym)
        return {}

    day_dir(sym).mkdir(parents=True, exist_ok=True)
    # ⚠ A MÁR ÖSSZEVONT hónapok napi fájljai törlődtek — ha csak a napi fájl
    # létezését néznénk, egy újrafuttatás azokat MÉGEGYSZER letöltené (és a
    # `consolidate` utána árván hagyná őket, mert a havi fájl már megvan).
    # Ezért a havi fájl is „megvan" jelnek számít.
    kesz_honapok = {tuple(int(x) for x in f.stem.split("-"))
                    for f in (TICK_DIR / sym).glob(
                        "[0-9][0-9][0-9][0-9]-[0-9][0-9].parquet")}
    stat = {"uj": 0, "meglevo": 0, "ures": 0, "hiba": 0, "tick": 0}
    d = start
    t0 = time.time()
    while d < end and not _stop:
        if (d.year, d.month) in kesz_honapok:
            stat["meglevo"] += 1
            d += timedelta(days=1)
            continue
        p = day_file(sym, d)
        if p.exists():
            stat["meglevo"] += 1
            d += timedelta(days=1)
            continue
        if d.weekday() >= 5:
            # Hétvége: ÍRUNK üres fájlt, hogy a következő futás ne kérdezze újra.
            _write_atomic(pd.DataFrame({"time_msc": [], "bid_pt": [], "ask_pt": []}
                                       ).astype("int64"), p)
            stat["ures"] += 1
            d += timedelta(days=1)
            continue
        df = fetch_day(sym, d, point, cfg)
        if df is None:
            stat["hiba"] += 1
        else:
            _write_atomic(df, p)
            if len(df):
                stat["uj"] += 1
                stat["tick"] += len(df)
            else:
                stat["ures"] += 1
        if (stat["uj"] + stat["ures"]) % 50 == 0 and (stat["uj"] or stat["ures"]):
            el = time.time() - t0
            log.info("   %s … %s | %d nap, %s tick, %.0f mp",
                     sym, d.date(), stat["uj"], f"{stat['tick']:,}", el)
        time.sleep(POLITE_SLEEP)
        d += timedelta(days=1)
    return stat


# ---------------------------------------------------------------------------
# havi összevonás (STREAMELVE — egyszerre egy nap a memóriában)
# ---------------------------------------------------------------------------

def consolidate(sym: str, keep_days: bool = False) -> int:
    """A LEZÁRT hónapok napi fájljait egy havi fájlba fűzi. A folyó hónapot
    nem bántja (még jöhet bele nap). Visszaad: hány hónapot vont össze."""
    dd = day_dir(sym)
    if not dd.is_dir():
        return 0
    files = sorted(dd.glob("*.parquet"))
    by_month: dict[tuple, list] = {}
    for f in files:
        try:
            y, m, _ = f.stem.split("-")
            by_month.setdefault((int(y), int(m)), []).append(f)
        except ValueError:
            continue
    now = datetime.now(timezone.utc)
    done = 0
    for (y, m), day_files in sorted(by_month.items()):
        if (y, m) >= (now.year, now.month):
            continue                       # a folyó hónap még nem teljes
        out = month_file(sym, y, m)
        if out.exists():
            # Árva napi fájlok egy MÁR összevont hónapból (korábbi hibás
            # újrafuttatás maradéka) — a havi fájl a mérvadó, ezek mehetnek.
            if not keep_days:
                for f in day_files:
                    f.unlink(missing_ok=True)
                log.info("   %s %04d-%02d — %d árva napi fájl eltakarítva "
                         "(a havi fájl már megvolt)", sym, y, m, len(day_files))
            continue
        tmp = out.with_suffix(".tmp")
        out.parent.mkdir(parents=True, exist_ok=True)
        writer = pq.ParquetWriter(tmp, SCHEMA, compression="zstd")
        rows = 0
        try:
            for f in sorted(day_files):    # napról napra: konstans memória
                tbl = pq.read_table(f, schema=SCHEMA)
                if tbl.num_rows:
                    writer.write_table(tbl)
                    rows += tbl.num_rows
        finally:
            writer.close()
        tmp.replace(out)
        if not keep_days:
            for f in day_files:
                f.unlink(missing_ok=True)
        log.info("   %s %04d-%02d összevonva: %s tick, %.1f MB",
                 sym, y, m, f"{rows:,}", out.stat().st_size / 1e6)
        done += 1
    return done


def status(syms) -> pd.DataFrame:
    rows = []
    for sym in syms:
        months = sorted((TICK_DIR / sym).glob("[0-9][0-9][0-9][0-9]-[0-9][0-9].parquet"))
        days = sorted(day_dir(sym).glob("*.parquet"))
        size = sum(f.stat().st_size for f in months) + \
            sum(f.stat().st_size for f in days)
        rows.append({
            "symbol": sym,
            "havi_fajl": len(months),
            "napi_fajl": len(days),
            "elso": (months[0].stem if months else
                     (days[0].stem if days else "—")),
            "utolso": (days[-1].stem if days else
                       (months[-1].stem if months else "—")),
            "MB": round(size / 1e6, 1),
        })
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", default="", help="vesszős lista")
    ap.add_argument("--from", dest="frm", default="",
                    help="kezdő dátum (YYYY-MM-DD)")
    ap.add_argument("--to", dest="to", default="", help="záró dátum (kizárólag)")
    ap.add_argument("--all-history", action="store_true",
                    help="a `data/tick_probe.csv`-ben MÉRT legkorábbi ticktől")
    ap.add_argument("--consolidate", action="store_true",
                    help="a letöltés után vonja össze a lezárt hónapokat")
    ap.add_argument("--keep-days", action="store_true",
                    help="összevonás után a napi fájlok is maradjanak meg")
    ap.add_argument("--status", action="store_true", help="csak a jelenlegi állapot")
    args = ap.parse_args()

    cfg = json.load(io.open(ROOT / "config.json", encoding="utf-8"))
    syms = ([s.strip() for s in args.symbols.split(",") if s.strip()] or
            [k for k, v in cfg["pairs"].items()
             if k != "_comment" and v.get("enabled", True)])

    if args.status:
        print(status(syms).to_string(index=False))
        return 0

    # a MÉRT legkorábbi tick (tick_probe kimenete) — ne találgassunk
    probe = {}
    pcsv = ROOT / "data" / "tick_probe.csv"
    if pcsv.exists():
        try:
            t = pd.read_csv(pcsv, sep=";")
            probe = dict(zip(t["symbol"], t["legkorabbi"]))
        except Exception as ex:
            log.warning("tick_probe.csv nem olvasható: %s", ex)

    end = (datetime.strptime(args.to, "%Y-%m-%d").replace(tzinfo=timezone.utc)
           if args.to else datetime.now(timezone.utc).replace(
               hour=0, minute=0, second=0, microsecond=0))

    signal.signal(signal.SIGINT, _on_sigint)
    if not mt5_connector.connect(cfg):
        log.error("Nem sikerült csatlakozni az MT5-höz.")
        return 1
    try:
        for sym in syms:
            if _stop:
                break
            if args.frm:
                start = datetime.strptime(args.frm, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc)
            elif args.all_history and probe.get(sym, "—") != "—":
                start = datetime.strptime(str(probe[sym]), "%Y-%m-%d").replace(
                    tzinfo=timezone.utc)
            else:
                log.warning("%s — nincs megadva kezdő dátum (--from vagy "
                            "--all-history + tick_probe.csv), kihagyva", sym)
                continue
            log.info("%s — letöltés %s … %s", sym, start.date(), end.date())
            st = download_symbol(sym, start, end, cfg)
            if st:
                log.info("%s — kész: %d új nap, %d meglévő, %d üres, %d hiba, "
                         "%s tick", sym, st["uj"], st["meglevo"], st["ures"],
                         st["hiba"], f"{st['tick']:,}")
            if args.consolidate and not _stop:
                consolidate(sym, args.keep_days)
        print()
        print(status(syms).to_string(index=False))
        if _stop:
            print("\nMEGSZAKÍTVA — a következő futás onnan folytatja, ahol "
                  "abbahagyta (a napi fájlok az állapot).")
        return 0
    finally:
        mt5_connector.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())

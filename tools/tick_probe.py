"""Tick-felderítő: meddig nyúlik vissza a bróker tick-előzménye, és mekkora?

Ez a `core/docs/tick_storage.md` terv 1. lépése — a MÉRÉS, ami eldönti, érdemes-e
egyáltalán belevágni a teljes letöltésbe. Nem tölt le mindent: szimbólumonként
(a) visszafelé próbálgatva megkeresi, melyik évtől van tick, majd (b) letölt
NÉHÁNY kereskedési napot, és abból méri a VALÓDI tick/nap darabszámot és a
tömörített byte/tick arányt. Hónapot NEM kérünk egyben: arra az MT5 rendszerint
None-t ad (túl nagy), és az első változat ezért írt mindenhol 0 tick/hó-t.

Miért kell: az MT5 csak 1–2 év M1/M15 gyertyát tart, tickből viszont jóval
többet. A mostani ~480 kereskedési napos minta túl kicsi ahhoz, hogy egy kis
élet megkülönböztessünk a nullától.

⚠ NE FUSSON EGYSZERRE A `main.py live`-VAL. Mindkettő ugyanazt az MT5 terminált
hajtja, és a második processz `mt5.initialize()`-e BEÁLL, amíg az első nagy
tick-kéréseket futtat — a dashboard főablaka ilyenkor meg sem jelenik, és a
naplóba egyetlen MT5-sor sem kerül (2026-08-27). Előbb az egyiket, aztán a másikat.

Futtatás (a projekt gyökeréből, futó MT5 mellett):

    python tools/tick_probe.py
    python tools/tick_probe.py --symbols UsaTec,Ger40,GOLD,USDJPY
    python tools/tick_probe.py --quick              # CSAK a tartomány (másodpercek)
    python tools/tick_probe.py --keep               # a mintanapok maradjanak meg

A `--keep` a letöltött mintanapokat a `data/ticks/<SYM>/` alá menti (a végleges
formátumban) — így egyben a tároló-formátum próbája is.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import MetaTrader5 as mt5                     # noqa: E402
from core import mt5_connector                # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
log = logging.getLogger(__name__)

TICK_DIR = ROOT / "data" / "ticks"
SAMPLE_DAYS = 5         # ennyi KERESKEDÉSI nap tickjéből mérünk


def _ticks(sym: str, start: datetime, end: datetime, retries: int = 2):
    """Tickek egy ablakra, ÚJRAPRÓBÁLÁSSAL. None, ha tényleg nincs.

    ⚠ Két MT5-sajátosság, amin az első változat elbukott (mindenhol 0 tick):
      • az első kérés gyakran csak ELINDÍTJA a tick-előzmény letöltését a
        szerverről, és üresen/None-nal tér vissza — másodszorra jön az adat;
      • egy HÓNAPNYI tick egyszerre tipikusan túl nagy (memória/belső limit),
        a hívás None-t ad. Ezért NAPI darabokban kérünk (`sample_days`)."""
    for attempt in range(retries + 1):
        with mt5_connector.MT5_LOCK:
            t = mt5.copy_ticks_range(sym, start, end, mt5.COPY_TICKS_ALL)
        if t is not None and len(t):
            return t
        err = mt5.last_error()
        if err and err[0] != 0:
            log.debug("%s %s — MT5: %s", sym, start.date(), err)
        if attempt < retries:
            time.sleep(1.5)          # hagyjuk a terminált letölteni
    return None


def earliest_tick(sym: str, attempts: int = 8) -> "datetime | None":
    """A LEGKORÁBBI elérhető tick ideje.

    ⚠ MÉRT VISELKEDÉS (2026-08-27). A tick-előzmény NINCS a gépen, amíg le nem
    kéred. Az ELSŐ hívás elindítja a letöltést, ~90 mp-ig fut, majd `None`-nal és
    „Terminal: Call failed"-del tér vissza. A MÁSODIK hívás (további ~65 mp) már
    megkapja az adatot — RÉSZBEN már szinkronizált szimbólumon. HIDEG
    szimbólumnál (UsaTec, UsaInd) 3 próbálkozás is kevés volt, ezért az
    alapértelmezés 8 (~12 perc). Ez egyszeri költség szimbólumonként. Utána a történelmi napok 0,1 mp alatt jönnek — a szinkron
    tehát EGYSZERI, szimbólumonkénti költség.

    Ezért próbálkozunk többször; ez NEM hibatűrés, hanem maga a letöltési
    protokoll. Az első változat egyszer hívott, és ezért írt mindenhol „nincs"-et.

    (Az évente visszafelé próbálgatás — 13 kérés/szimbólum — még rosszabb volt:
    percekig fogta a terminált, és befagyasztotta a dashboardot.)"""
    ep = datetime(1970, 1, 2, tzinfo=timezone.utc)
    for i in range(attempts):
        with mt5_connector.MT5_LOCK:
            t = mt5.copy_ticks_from(sym, ep, 1, mt5.COPY_TICKS_ALL)
        if t is not None and len(t):
            names = t.dtype.names or ()
            sec = (int(t["time_msc"][0]) / 1000.0 if "time_msc" in names
                   else int(t["time"][0]))
            try:
                return datetime.fromtimestamp(sec, timezone.utc)
            except (OSError, OverflowError, ValueError):
                return None
        if i < attempts - 1:
            log.info("   %s — a terminál tölti a tick-előzményt… (%d/%d)",
                     sym, i + 1, attempts - 1)
    return None


def _to_frame(ticks, point: float) -> pd.DataFrame:
    """A terv szerinti tároló-alak: idő ms + ár PONTBAN, egészként.
    (float32-ben a legalsó pont elveszne — épp az, amiből a spread áll.)"""
    names = ticks.dtype.names or ()
    tms = (ticks["time_msc"].astype("int64") if "time_msc" in names
           else ticks["time"].astype("int64") * 1000)
    bid = ticks["bid"].astype(float)
    ask = ticks["ask"].astype(float)
    ok = (bid > 0) & (ask >= bid)
    df = pd.DataFrame({
        "time_msc": tms[ok],
        "bid_pt": np.round(bid[ok] / point).astype("int64"),
        "ask_pt": np.round(ask[ok] / point).astype("int64"),
    })
    return df.drop_duplicates(subset="time_msc", keep="last")


def sample_days(sym: str, point: float, keep: bool, n_days: int = SAMPLE_DAYS) -> dict:
    """`n_days` KERESKEDÉSI nap tickjének letöltése és megmérése.

    Nem egy hónapot kérünk egyben: az MT5 arra rendszerint None-t ad (túl nagy),
    és az első változat ezért írt mindenhol 0 tick/hó-t. Napi darabokban kérünk,
    a kapott napokból mérünk, és abból extrapolálunk."""
    day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0,
                                             microsecond=0) - timedelta(days=1)
    frames, per_day, tried = [], [], 0
    while len(per_day) < n_days and tried < n_days * 4:
        tried += 1
        if day.weekday() < 5:                     # hétvégén úgyis üres
            t = _ticks(sym, day, day + timedelta(days=1))
            if t is not None and len(t):
                df = _to_frame(t, point)
                if len(df):
                    frames.append(df)
                    per_day.append(len(df))
        day -= timedelta(days=1)
    if not frames:
        return {"nap": 0, "tick_nap": 0}

    allf = pd.concat(frames, ignore_index=True)
    out_dir = TICK_DIR / sym / "_minta"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"minta_{len(per_day)}nap.parquet"
    allf.to_parquet(path, compression="zstd", index=False)
    size = path.stat().st_size
    if not keep:
        path.unlink()
        try:
            out_dir.rmdir()
        except OSError:
            pass                     # nem üres — hagyjuk
    med = float(np.median(per_day))
    return {"nap": len(per_day), "tick_nap": med,
            "byte_per_tick": size / len(allf) if len(allf) else float("nan"),
            "MB_nap": (size / len(allf)) * med / 1e6 if len(allf) else 0.0}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", default="",
                    help="vesszős lista; elhagyva a config aktív párjai")
    ap.add_argument("--quick", action="store_true",
                    help="CSAK a legkorábbi tick ideje (szimbólumonként EGY hívás, "
                         "másodpercek) — nem tölt le mintanapokat")
    ap.add_argument("--keep", action="store_true",
                    help="a letöltött mintahónap maradjon meg a data/ticks alatt")
    args = ap.parse_args()

    cfg = json.load(io.open(ROOT / "config.json", encoding="utf-8"))
    if args.symbols:
        syms = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        syms = [k for k, v in cfg["pairs"].items()
                if k != "_comment" and v.get("enabled", True)]
    if not mt5_connector.connect(cfg):
        log.error("Nem sikerült csatlakozni az MT5-höz — fut a terminál?")
        return 1
    try:
        rows = []
        for sym in syms:
            with mt5_connector.MT5_LOCK:
                if not mt5.symbol_select(sym, True):
                    log.warning("%s — nem választható ki, kihagyva", sym)
                    continue
                info = mt5.symbol_info(sym)
            point = float(getattr(info, "point", 0.0) or 0.0)
            if point <= 0:
                log.warning("%s — nincs érvényes point_size, kihagyva", sym)
                continue
            first = earliest_tick(sym)
            y = first.year if first else None
            log.info("%s — legkorábbi tick: %s", sym,
                     first.strftime("%Y-%m-%d") if first else "nincs")
            if args.quick:
                rows.append({"symbol": sym,
                             "legkorabbi": first.strftime("%Y-%m-%d") if first else "—",
                             "legkorabbi_ev": y or "—",
                             "ev_szam": (datetime.now(timezone.utc).year - y + 1)
                                        if y else 0,
                             "minta_nap": 0, "tick_nap": 0, "byte_per_tick": 0.0,
                             "MB_nap": 0.0, "GB_ev_becsult": 0.0})
                continue
            log.info("%s — mintanapok letöltése…", sym)
            m = sample_days(sym, point, args.keep)
            # 252 kereskedési nap/év (a hétvégéket a napi minta már kihagyta)
            gb_ev = m.get("MB_nap", 0.0) * 252 / 1000
            rows.append({
                "symbol": sym,
                "legkorabbi": first.strftime("%Y-%m-%d") if first else "—",
                "legkorabbi_ev": y if y else "—",
                "ev_szam": (datetime.now(timezone.utc).year - y + 1) if y else 0,
                "minta_nap": m["nap"],
                "tick_nap": int(m["tick_nap"]),
                "byte_per_tick": round(m.get("byte_per_tick", 0.0), 2),
                "MB_nap": round(m.get("MB_nap", 0.0), 2),
                "GB_ev_becsult": round(gb_ev, 2),
            })
            r = rows[-1]
            log.info("%s — %s-tól · %s tick/nap (%d napból) · %.2f MB/nap · ~%.2f GB/év",
                     sym, r["legkorabbi"], f"{int(m['tick_nap']):,}", m["nap"],
                     m.get("MB_nap", 0.0), gb_ev)

        if not rows:
            log.warning("Egyetlen szimbólumot sem sikerült megmérni.")
            return 1
        df = pd.DataFrame(rows)
        out = ROOT / "data" / "tick_probe.csv"
        df.to_csv(out, sep=";", index=False, decimal=",")
        print()
        print(df.to_string(index=False))
        tot = df["GB_ev_becsult"].sum()
        print(f"\nÖSSZESEN ~{tot:.1f} GB/év mind a {len(df)} szimbólumra.")
        yrs = df["ev_szam"].replace("—", 0)
        if len(yrs):
            print(f"A teljes elérhető előzmény becsült mérete: "
                  f"~{(df['GB_ev_becsult'] * yrs).sum():.0f} GB")
        print(f"Részletes tábla: {out}")
        print("\nDöntési támpont: ha a legkorábbi év ≤ 2020 ÉS a teljes méret "
              "belefér a lemezre, a terv 2–4. lépése megéri "
              "(core/docs/tick_storage.md).")
        return 0
    finally:
        mt5_connector.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())

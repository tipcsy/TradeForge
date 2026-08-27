"""Szimbólum-felderítő: mit kínál a bróker, és mennyibe kerül ott EGY kötés.

Miért kell: a P&L-t nem a jelzés, hanem a KÖLTSÉG/volatilitás arány vezérli
(lásd a `koltsegR` oszlopot). Egy új instrumentum felvétele előtt ez az első
mérés — ha a `koltsegR` 0,2 fölött van, ott nincs az a belépő-jelzés, ami
behozná.

  koltsegR = (spread_pont + jutalek_pont) / stop_pont,
  ahol stop_pont = 1,5 × az M15 gyertyák átlagos valódi mozgása (True Range).

Ez azt mondja meg, hogy egy tipikus kötés a kockázat (1R) hány százalékát
fizeti ki indulásból. Minden instrumentumon UGYANAZ a stop-definíció, hogy az
összehasonlítás érvényes legyen.

⚠ KÉT LÉPCSŐ, és ez nem kényelmi kérdés
---------------------------------------
Az MT5 gyertya `spread` mezője NEM azt méri, amit fizetsz — a mérésünk szerint
ezeken a CFD-ken nagyjából a HARMADA a tick-ből számolt valódi (ask−bid)
spreadnek (UsaTec: 74 vs. 249 pont). Ha ez alapján választanál instrumentumot,
mindegyik háromszor olcsóbbnak látszana a valóságnál.

Ezért: 1. lépcső = gyors, gyertya-alapú ELŐSZŰRÉS az összes szimbólumra;
2. lépcső = a túlélőkön TICK-ből mért spread (ugyanaz a képlet, mint amivel a
`tools/download_history.py` az `avg_spread`-et számolja). A kiírt `koltsegR`
mindig a tick-alapú, ahol sikerült megmérni (`forras` oszlop).

Határidős (lejáratos) szerződések alapból KIMARADNAK: nincs hozzájuk hosszú,
folytonos előzmény a backtesthez, és lejáratkor görgetni kellene őket. A
`--futures` kapcsolóval megnézhetők (a spreadjük tanulságos: az index-futures
20–60%-kal olcsóbb, mint a készpénz-változata).

Futtatás (a projekt gyökeréből, futó MT5 mellett):

    python tools/symbol_scan.py --all --max-cost 0.10
    python tools/symbol_scan.py --grep 500,jpy,oil
    python tools/symbol_scan.py --all --futures          # a lejáratosokat is

MÁSIK BRÓKER összehasonlítása (pl. jutalékos ECN-számla): indíts egy második MT5
terminált, lépj be benne kézzel a másik számlára, és mutass rá a `--path`-szal —
a config.json-t ilyenkor nem használjuk, a már bejelentkezett terminált vesszük át:

    python tools/symbol_scan.py --path "C:\\MT5-Robo\\terminal64.exe" --all --commission 4.0

A `--commission` az ODA-VISSZA jutalék 1.0 lotra, a számla devizájában; az eszköz
pontra váltja, hogy a spreaddel egy skálán legyen.

A kimenet a `data/symbol_scan.csv`-be is kimegy.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import MetaTrader5 as mt5                     # noqa: E402
from core import mt5_connector                # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
log = logging.getLogger(__name__)

BARS = 2000            # ~3 hét M15 — stabil volatilitás-becsléshez elég, és gyors
TR_N = 140             # ennyi M15 gyertya átlagos True Range-e a volatilitás-mérce
STOP_ATR = 1.5
TICK_DAYS = 3          # ennyi nap tickjéből mérjük a valódi spreadet
TICK_CAP = 400_000     # ennél több ticket ritkítunk (a medián ettől nem romlik)
STAGE2_MAX = 60        # ennyi legjobb jelöltet mérünk meg tickből


def _mean_true_range(h, l, c) -> float:
    """Az utolsó `TR_N` gyertya átlagos valódi mozgása, ÁRBAN.

    Szándékosan hosszú átlag (nem 14 periódusú ATR): itt nem kereskedni akarunk,
    hanem instrumentumokat összehasonlítani — a hosszabb ablak stabilabb."""
    pc = np.concatenate([[np.nan], c[:-1]])
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    tr = tr[-TR_N:]
    return float(np.nanmean(tr)) if len(tr) else float("nan")


def _bar_spread_pts(rates, info) -> float:
    """GYORS, de OPTIMISTA spread-becslés a gyertya `spread` mezőjéből.
    Csak előszűrésre — a valódi értéket a `_tick_spread_pts` adja."""
    if rates.dtype.names and "spread" in rates.dtype.names:
        v = rates["spread"].astype(float)
        v = v[v > 0]
        if len(v):
            return float(np.median(v))
    return float(info.spread or 0.0)


def _tick_spread_pts(name: str, point: float) -> float:
    """VALÓDI spread: a tickek (ask − bid) mediánja pontban.

    Ugyanaz a forrás, amiből a `tools/download_history.py` az `avg_spread`
    oszlopot építi — így a scan és a backtest ugyanazt a számot látja."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=TICK_DAYS)
    with mt5_connector.MT5_LOCK:
        ticks = mt5.copy_ticks_range(name, start, end, mt5.COPY_TICKS_ALL)
    if ticks is None or len(ticks) == 0:
        return float("nan")
    names = ticks.dtype.names or ()
    if "bid" not in names or "ask" not in names:
        return float("nan")
    if len(ticks) > TICK_CAP:                      # egyenletes ritkítás
        ticks = ticks[:: len(ticks) // TICK_CAP + 1]
    bid = ticks["bid"].astype(float)
    ask = ticks["ask"].astype(float)
    ok = (bid > 0) & (ask > bid)
    if ok.sum() < 100:
        return float("nan")
    return float(np.median(ask[ok] - bid[ok]) / point)


def _commission_pts(info, commission_ccy: float, point: float) -> float:
    """Az oda-vissza jutalékot PONTRA váltja, hogy a spreaddel egy skálán legyen.
    1 pont értéke 1.0 lotra = tick_value × (point / tick_size)."""
    if not commission_ccy:
        return 0.0
    tick_val = float(info.trade_tick_value or 0.0)
    tick_sz = float(info.trade_tick_size or 0.0) or point
    pv1 = tick_val * (point / tick_sz) if tick_sz > 0 else 0.0
    return commission_ccy / pv1 if pv1 > 0 else float("nan")


def scan_symbol(name: str, commission_ccy: float = 0.0) -> dict | None:
    """1. lépcső: egy szimbólum gyors költség-profilja. None, ha nem mérhető."""
    with mt5_connector.MT5_LOCK:
        if not mt5.symbol_select(name, True):
            return None
        info = mt5.symbol_info(name)
        rates = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_M15, 0, BARS)
    if info is None or rates is None or len(rates) < TR_N // 2:
        return None
    point = info.point or 0.0
    if point <= 0:
        return None
    tr_price = _mean_true_range(rates["high"].astype(float),
                                rates["low"].astype(float),
                                rates["close"].astype(float))
    if not (tr_price > 0):
        return None
    sp_pts = _bar_spread_pts(rates, info)
    if not (sp_pts > 0):
        # 0 spread = nincs érvényes jegyzés (zárt piac, halott szimbólum) —
        # ez `koltsegR = 0`-t adna, ami a lista tetejére dobná. Kihagyjuk.
        return None
    stop_pts = STOP_ATR * tr_price / point
    if not (stop_pts > 0):
        return None
    com_pts = _commission_pts(info, commission_ccy, point)

    return {
        "symbol": name,
        "leiras": (info.description or "")[:38],
        "koltsegR": round((sp_pts + com_pts) / stop_pts, 4),
        "forras": "gyertya",
        "spread_pt": round(sp_pts, 1),
        "jutalek_pt": round(com_pts, 1),
        "tr15_pt": round(tr_price / point, 1),
        "stop_pt": round(stop_pts, 1),
        "lejarat": (datetime.fromtimestamp(info.expiration_time, timezone.utc)
                    .strftime("%Y-%m-%d") if info.expiration_time else ""),
        "point_size": point,
        "min_lot": info.volume_min,
        "lot_step": info.volume_step,
        "max_lot": info.volume_max,
        "tick_value": info.trade_tick_value,
        "swap_long": info.swap_long,
        "swap_short": info.swap_short,
        "csoport": (info.path or "").split("\\")[0],
    }


def refine(row: dict, commission_ccy: float) -> dict:
    """2. lépcső: a spreadet TICK-ből újramérjük, és frissítjük a `koltsegR`-t."""
    sp = _tick_spread_pts(row["symbol"], row["point_size"])
    if not (sp > 0):
        return row                                  # marad a gyertya-becslés
    row["spread_pt"] = round(sp, 1)
    row["forras"] = "tick"
    row["koltsegR"] = round((sp + row["jutalek_pt"]) / row["stop_pt"], 4)
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true",
                    help="a bróker TELJES kínálata (nem csak a Market Watch)")
    ap.add_argument("--grep", default="",
                    help="vesszős szűrő a névre (pl. 500,oil,jpy)")
    ap.add_argument("--max-cost", type=float, default=None,
                    help="csak ennél olcsóbb instrumentumok (koltsegR)")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--futures", action="store_true",
                    help="a lejáratos (határidős) szerződéseket is mutassa")
    ap.add_argument("--no-ticks", action="store_true",
                    help="hagyja ki a tick-alapú pontosítást (gyors, de OPTIMISTA)")
    ap.add_argument("--path", default="",
                    help="MÁSIK MT5 terminál elérési útja (a config.json helyett); "
                         "a terminálban már be kell lépni a kívánt számlára")
    ap.add_argument("--commission", type=float, default=0.0,
                    help="ODA-VISSZA jutalék 1.0 lotra, a számla devizájában")
    args = ap.parse_args()

    if args.path:
        # A már bejelentkezett terminált vesszük át — nincs login a configból.
        if not (mt5.initialize(path=args.path, portable=True)
                or mt5.initialize(path=args.path)):
            log.error("Nem sikerült megnyitni: %s (%s)", args.path, mt5.last_error())
            return 1
        acc = mt5.account_info()
        log.info("Külső terminál: %s — %s (%s)", args.path,
                 getattr(acc, "server", "?"), getattr(acc, "currency", "?"))
    else:
        cfg = json.load(io.open(ROOT / "config.json", encoding="utf-8"))
        if not mt5_connector.connect(cfg):
            log.error("Nem sikerült csatlakozni az MT5-höz — fut a terminál?")
            return 1
    try:
        with mt5_connector.MT5_LOCK:
            syms = mt5.symbols_get()
        names = [s.name for s in syms if args.all or getattr(s, "visible", True)]
        pats = [p.strip().lower() for p in args.grep.split(",") if p.strip()]
        if pats:
            names = [n for n in names if any(p in n.lower() for p in pats)]
        log.info("1. lépcső — %d szimbólum előszűrése…", len(names))

        rows = []
        for n in names:
            try:
                r = scan_symbol(n, args.commission)
            except Exception as ex:                 # egy rossz szimbólum ne állítson meg
                log.debug("%s — kihagyva: %s", n, ex)
                continue
            if r:
                rows.append(r)
        if not rows:
            log.warning("Nincs mérhető szimbólum a szűrőre.")
            return 1

        n_fut = sum(1 for r in rows if r["lejarat"])
        if not args.futures:
            rows = [r for r in rows if not r["lejarat"]]
            log.info("%d lejáratos szerződés kihagyva (--futures mutatja őket)", n_fut)

        rows.sort(key=lambda r: r["koltsegR"])
        # a gyertya-becslés OPTIMISTA, ezért a 2. lépcső elé bőven engedünk be
        cand = rows if args.max_cost is None else [
            r for r in rows if r["koltsegR"] <= args.max_cost * 3]
        cand = cand[:STAGE2_MAX]

        if not args.no_ticks:
            log.info("2. lépcső — %d jelölt spreadje tickből (%d nap)…",
                     len(cand), TICK_DAYS)
            for r in cand:
                try:
                    refine(r, args.commission)
                except Exception as ex:
                    log.debug("%s — tick-mérés sikertelen: %s", r["symbol"], ex)

        rows.sort(key=lambda r: r["koltsegR"])
        if args.max_cost is not None:
            rows = [r for r in rows if r["koltsegR"] <= args.max_cost]

        out = ROOT / "data" / "symbol_scan.csv"
        cols = list(rows[0].keys()) if rows else []
        with io.open(out, "w", encoding="utf-8", newline="") as f:
            f.write(";".join(cols) + "\n")
            for r in rows:
                f.write(";".join(str(r[c]).replace(".", ",") for c in cols) + "\n")

        head = (f"{'symbol':<16}{'koltsegR':>10}{'forras':>9}{'spread_pt':>11}"
                f"{'jutalek_pt':>12}{'tr15_pt':>10}  leiras")
        print(head)
        print("-" * len(head))
        for r in rows[:args.limit]:
            print(f"{r['symbol']:<16}{r['koltsegR']:>10.4f}{r['forras']:>9}"
                  f"{r['spread_pt']:>11.1f}{r['jutalek_pt']:>12.1f}"
                  f"{r['tr15_pt']:>10.1f}  {r['leiras']}")
        print(f"\n{len(rows)} sor — részletes tábla: {out}")
        print("Tájékozódás: <0,05 kiváló · 0,05–0,10 használható · "
              ">0,20 gyakorlatilag kereskedhetetlen")
        print("A `forras=gyertya` sorok OPTIMISTÁK (a valódi spread ~3× lehet) — "
              "döntés előtt tick-mérés kell.")
        return 0
    finally:
        if args.path:
            mt5.shutdown()
        else:
            mt5_connector.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())

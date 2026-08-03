"""MT5 backtest-reprodukció — a Python-backtest ESEMÉNYNAPLÓJÁT a
`BacktestReplayer.mq5` expert által olvasható CSV-be írja (12 oszlop).

FONTOS (v2): az EA már NEM szimulál újra semmit — a Python-backtest pontos
eseménynaplóját (`Trade.events`, `run_pair(record_events=True)`) JÁTSSZA VISSZA:
OPEN → SL_MODIFY / TP_MODIFY / PARTIAL_CLOSE / BUILD_ADD → CLOSE. Így BÁRMELY
preset (Felező/Pajzs/Fibo/Harmados/Risky) + a kiszállási jel + a pozícióépítés
azonos, mert a döntéseket a Python hozta, az MT5 csak végrehajtja. Az SL/TP-alapú
kilépéseket az MT5 a pozícióra rakott valódi SL/TP-vel, pontos áron tölti.

Visszafelé kompatibilis: ha a trade-nek nincs eseménynaplója (régi hívó,
record_events=False), a régi OFF-derivált OPEN/CLOSE sorokat írjuk.

CSV oszlopok: event, datetime, symbol, direction, price, sl, tp, lot, comment,
              be_trigger, trail_trigger, trail_dist_p
A `be_trigger/trail_trigger/trail_dist_p` az eseménynapló-úton 0 (nem kell újra-
szimuláció). Minden esemény időbélyege a detektáló M1-gyertya ZÁRÁSA (bar + 1 M1 =
a következő bar nyitása) `YYYY.MM.DD HH:MM:SS` formátumban → az EA a bar nyitásán
hajtja végre. A Strategy Testert M1-en, „Open prices only" modellel kell futtatni.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

MT5_HEADER = ["event", "datetime", "symbol", "direction", "price", "sl", "tp",
              "lot", "comment", "be_trigger", "trail_trigger", "trail_dist_p"]
BAR_MINUTES = 1     # TradeForge M1-belépő → az OPEN a belépő + 1 M1 (bar-záró)


def _fmt(dt) -> str:
    return pd.Timestamp(dt).strftime("%Y.%m.%d %H:%M:%S")


def _rows_from_event_log(t, tid: int, symbol: str, comment: str) -> list[tuple]:
    """Egy trade `events` naplójából (sort_ts, sor) párok. Minden esemény
    időbélyege + 1 M1 (a detektáló bar záró = a következő bar nyitása), így az EA
    a bar nyitásán, sorrendben hajtja végre. Az OPEN kommentje a stratégia (a
    címkéhez); a többi esemény a saját reason-jét viszi.

    A `be_trigger` oszlopba a `tid` (trade-azonosító) kerül: az EA ez alapján köti
    az SL_MODIFY / PARTIAL_CLOSE / CLOSE eseményt a HELYES pozícióhoz, így egy páron
    az EGYIDEJŰ pozíciók (kockázatmentes runner + új belépő) sem keverednek."""
    out: list[tuple] = []
    for etype, etime, price, sl, tp, lot, ecmt in t.events:
        ts = pd.Timestamp(etime) + pd.Timedelta(minutes=BAR_MINUTES)
        cmt = comment if etype == "OPEN" else (ecmt or etype)
        out.append((ts, [
            etype, _fmt(ts), symbol, t.direction,
            round(float(price), 5), round(float(sl), 5), round(float(tp), 5),
            round(float(lot), 2), cmt, tid, 0, 0,
        ]))
    return out


def _rows_legacy(t, symbol: str, params: dict, pair_cfg: dict,
                 comment: str) -> list[tuple]:
    """Visszafelé kompatibilis út: ha nincs eseménynapló (record_events=False),
    a régi OFF-derivált OPEN (kezdeti SL/TP + BE/trail trigger) + CLOSE sorok."""
    pip        = float(pair_cfg.get("point_size", 0.0001))
    be_pct     = float(params.get("breakeven_pct", 0.5))
    # ATR-szorzó × a kötés belépéskori ATR-je (ÁRban)
    _atr       = float(getattr(t, "entry_atr", 0.0) or 0.0)
    trail_act  = float(params.get("trail_activation_atr", 0.5)) * _atr
    trail_dist = float(params.get("trail_distance_atr", 0.4)) * _atr
    sign    = 1 if t.direction == "BUY" else -1
    init_sl = round(t.open_price - sign * t.sl_points * pip, 5)
    be_trig = round(t.open_price + sign * (t.tp - t.open_price) * be_pct, 5) if be_pct > 0 else 0.0
    tr_trig = round(t.open_price + sign * trail_act, 5) if trail_act > 0 else 0.0
    o_ts    = pd.Timestamp(t.open_time) + pd.Timedelta(minutes=BAR_MINUTES)
    out = [(o_ts, [
        "OPEN", _fmt(o_ts), symbol, t.direction,
        round(t.open_price, 5), init_sl, round(t.tp, 5), t.lot, comment,
        be_trig, tr_trig, round(trail_dist, 5),
    ])]
    if getattr(t, "close_time", None) is not None and t.close_price is not None:
        c_ts = pd.Timestamp(t.close_time)
        out.append((c_ts, [
            "CLOSE", _fmt(c_ts), symbol, t.direction,
            round(t.close_price, 5), 0, 0, t.lot, t.status, 0, 0, 0,
        ]))
    return out


def events_from_result(result, symbol: str, params: dict, pair_cfg: dict,
                       comment: str = "wpr_sma") -> list[list]:
    """A BacktestResult trade-jeiből MT5-események (globális időrendben rendezve).
    Elsődlegesen a trade `events` naplójából (az EA VÉGREHAJTJA); ha egy trade-nek
    nincs naplója, a régi OFF-derivált OPEN/CLOSE (fallback)."""
    events: list[tuple] = []   # (sort_ts, row)
    for tid, t in enumerate(getattr(result, "trades", [])):
        log = getattr(t, "events", None)
        if log:
            events.extend(_rows_from_event_log(t, tid, symbol, comment))
        else:
            events.extend(_rows_legacy(t, symbol, params, pair_cfg, comment))
    events.sort(key=lambda e: e[0])     # időrend (az EA sorrendben dolgozza fel)
    return [row for _, row in events]


def export_mt5_csv(result, symbol: str, params: dict, pair_cfg: dict,
                   out_dir, comment: str = "wpr_sma") -> Path | None:
    """A CSV kiírása `mt5_backtest_<symbol>_<ts>.csv` néven. A fájlt az MT5
    `Common\\Files\\` mappájába kell másolni (lásd az EA `ide_kell_helyezni.txt`
    útmutatóját). Visszaad: a fájl útvonala, vagy None, ha nincs esemény."""
    rows = events_from_result(result, symbol, params, pair_cfg, comment)
    if not rows:
        return None
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"mt5_backtest_{symbol}_{ts}.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(MT5_HEADER)
        w.writerows(rows)
    return path

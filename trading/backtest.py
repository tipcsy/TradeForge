"""
Backtestelő motor.

Működés:
  - M15 + M1 parquet fájlok beolvasása
  - Indikátorok számítása (SMA, WPR M15, WPR M1, ATR M15)
  - M1 szintű szimuláció: jelzés → pozíció nyitás → SL/TP/breakeven/trailing zárás
  - Slot menedzsment (portfólió szintű kockázat)

Futtatás: python trading/backtest.py
"""

import csv
import json
import logging
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np

RESULTS_DIR = Path(__file__).resolve().parents[1] / "data" / "backtest_results"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.risk_manager import calc_lot, calc_effective_slots, calc_swing_sl_tp_points
from core import risky_mode
from core import trade_costs as _costs
from strategy import get_strategy, get_strategy_by_name

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Adatstruktúrák
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    symbol: str
    direction: str          # "BUY" | "SELL"
    open_time: pd.Timestamp
    open_price: float
    sl: float
    tp: float
    lot: float
    point_size: float
    pv1_point: float
    sl_points: float
    # A BELÉPÉSKORI ATR (árban). A trailing ehhez méri az aktiválást és a követési
    # távolságot (`trail_activation_atr` / `trail_distance_atr`) — így a puffer
    # együtt mozog a piac zajszintjével, és nem kell instrumentumonként hangolni.
    entry_atr: float = 0.0
    close_time: Optional[pd.Timestamp] = None
    close_price: Optional[float] = None
    pnl_usd: float = 0.0        # NETTÓ (a jutalék és a swap már benne)
    commission_usd: float = 0.0  # levont jutalék (pozitív = költség)
    swap_usd: float = 0.0        # felhalmozott swap, ELŐJELES (negatív = levonás)
    pnl_points: float = 0.0
    status: str = "open"    # "open" | "tp" | "sl" | "be_trail"
    risk_free: bool = False  # SL átment breakeven-re
    entry_balance: float = 0.0
    risk_usd: float = 0.0
    risk_pct: float = 0.0
    # ── Kockázatcsökkentés (Felező/Pajzs) — részleges zárás modellezése ──
    booked_pnl: float = 0.0     # a részleges zárás(ok)ból már realizált P&L
    reduced: bool = False       # megtörtént-e a részleges zárás (1R-nél, egyszer)
    runner_mode: str = "keep"   # a maradék stopja: keep|breakeven|trailing
    rr_technique: str = ""      # a ténylegesen alkalmazott technika (log/CSV)
    rr_preset_eff: str = ""     # Pajzs↔Fibo auto: a belépéskor eldöntött hatásos preset
    # ── Pozícióépítés (AUTO) — több „láb" (ráépítés) egy átlagárral ──
    legs: list = field(default_factory=list)   # [(price, lot), …]; üres → egyleges
    build_ref: float = 0.0      # a következő ráépítés referencia-záróára
    # ── Esemény-napló (MT5 BacktestReplayer visszajátszáshoz) ──
    # CSAK ha a run_pair `record_events=True`-val fut (a Backtest-ablak); alapból
    # üres → az optimalizáló/portfólió-BT bitazonos, nincs overhead. Minden elem:
    # (típus, idő, ár, sl, tp, lot, komment). Típus: OPEN / SL_MODIFY / TP_MODIFY /
    # PARTIAL_CLOSE / BUILD_ADD / CLOSE. Az MT5 ezeket VÉGREHAJTJA (nem szimulál újra).
    events: list = field(default_factory=list)

    @property
    def built(self) -> bool:
        """Épített (több lábú) csomag-e? A live ilyenkor TÖRLI a TP-t (minden láb
        SL-je az átlagáron, TP nélkül fut) — a backtest ezt modellezi."""
        return len(self.legs) > 1


@dataclass
class BacktestResult:
    symbol: str
    trades: list = field(default_factory=list)
    balance_curve: list = field(default_factory=list)

    @property
    def closed(self):
        return [t for t in self.trades if t.status != "open"]

    def summary(self, initial_balance: float) -> dict:
        closed = self.closed
        if not closed:
            return {"symbol": self.symbol, "trades": 0}

        pnl_list = [t.pnl_usd for t in closed]
        wins   = [p for p in pnl_list if p > 0]
        losses = [p for p in pnl_list if p <= 0]
        tps    = [t for t in closed if t.status == "tp"]
        sls    = [t for t in closed if t.status == "sl"]
        be_tr  = [t for t in closed if t.status == "be_trail"]

        balance = initial_balance
        peak    = balance
        max_dd  = 0.0
        for p in pnl_list:
            balance += p
            if balance > peak:
                peak = balance
            dd = (peak - balance) / peak
            if dd > max_dd:
                max_dd = dd

        # Óránkénti (belépési óra szerinti) P&L-bontás — ebből dönthető el, mely
        # órákat érdemes kivenni (trade_hours). {óra(0-23): {"pnl","count"}}.
        hourly: dict = {}
        for t in closed:
            h = int(t.open_time.hour)
            b = hourly.setdefault(h, {"pnl": 0.0, "count": 0})
            b["pnl"]   += t.pnl_usd
            b["count"] += 1
        for b in hourly.values():
            b["pnl"] = round(b["pnl"], 2)

        # ── Pozícióépítés (ráépítés) hozadéka ────────────────────────────────
        # Kétféle nézet, mert kétféle kérdés van:
        #   • `build_pkg_pnl/_r` — az ÉPÍTETT KÖTÉSEK teljes eredménye (ez a
        #     „mennyit hoztak az épített csomagok"); ez a gyakorlati hozadék,
        #   • `build_pnl/_r` — KIZÁRÓLAG az adalék-lábak (legs[1:]) része a
        #     záróáron. FIGYELEM: ha a csomag az ÁTLAGÁR-stopon zár, ez definíció
        #     szerint az induló láb nyereségének a mínusza (nulla összegű) — a
        #     bontás a CSV-hez/diagnosztikához hasznos, nem „profit"-mérőszám.
        # Az igazi A/B a két futás (Építés Ki ↔ Auto) össz-P&L-jének különbsége.
        b_adds = b_trades = 0
        b_pnl = b_r = b_pkg_pnl = b_pkg_r = 0.0
        for t in closed:
            legs = getattr(t, "legs", None) or []
            if len(legs) < 2 or t.close_price is None:
                continue
            b_trades += 1
            b_adds   += len(legs) - 1
            b_pkg_pnl += t.pnl_usd
            p = 0.0
            for price, lot in legs[1:]:
                diff = t.close_price - price
                if t.direction == "SELL":
                    diff = -diff
                p += (diff / t.point_size) * lot * t.pv1_point
            b_pnl += p
            if t.risk_usd:
                b_r += p / t.risk_usd
                b_pkg_r += t.pnl_usd / t.risk_usd

        return {
            "symbol":        self.symbol,
            "trades":        len(closed),
            "win_rate":      len(wins) / len(closed) if closed else 0,
            "total_pnl":     sum(pnl_list),
            "avg_win":       sum(wins) / len(wins) if wins else 0,
            "avg_loss":      sum(losses) / len(losses) if losses else 0,
            "max_drawdown":  max_dd,
            "profit_factor": abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf"),
            "tp_count":      len(tps),
            "sl_count":      len(sls),
            "be_trail_count": len(be_tr),
            "final_balance": initial_balance + sum(pnl_list),
            "hourly_pnl":    hourly,
            # Pozícióépítés (ráépítés) — 0/0.0, ha nem volt építés
            "build_trades":  b_trades,   # hány kötésre épült rá
            "build_adds":    b_adds,     # összesen hány adalék (láb) nyílt
            "build_pkg_pnl": round(b_pkg_pnl, 2),  # az ÉPÍTETT kötések teljes P&L-je ($)
            "build_pkg_r":   round(b_pkg_r, 2),    # ugyanaz R-ben
            "build_pnl":     round(b_pnl, 2),   # ebből az adalék-lábak része ($)
            "build_r":       round(b_r, 2),     # ugyanaz R-ben (induló kockázathoz mérve)
        }


# ---------------------------------------------------------------------------
# Segédfüggvények
# ---------------------------------------------------------------------------

def load_data(symbol: str) -> tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    m15_path = ROOT / "data" / "m15" / f"{symbol}.parquet"
    m1_path  = ROOT / "data" / "m1"  / f"{symbol}.parquet"

    if not m15_path.exists() or not m1_path.exists():
        log.warning("%s — hiányzó adat fájl, kihagyva.", symbol)
        return None, None

    df_m15 = pd.read_parquet(m15_path)
    df_m1  = pd.read_parquet(m1_path)
    return df_m15, df_m1


def load_data_ensure(symbol: str, cfg: dict, status=None):
    """`load_data`, de ha hiányzik a parquet, ELŐBB letölti MT5-ből.

    A GUI backtest-útjai ezt hívják: egy frissen felvett instrumentumnál az első
    backtest ne „nincs letöltött adat"-tal álljon meg, hanem töltse le magától.
    `status`: opcionális callback(str) a haladáshoz.
    Visszaad: (df_m15, df_m1, hibaüzenet|None)."""
    df15, df1 = load_data(symbol)
    if df15 is not None:
        return df15, df1, None
    try:
        from tools.download_history import ensure_history
        ok, msg = ensure_history(symbol, cfg, status=status)
    except Exception as ex:
        return None, None, f"Nincs letöltött adat, és a letöltés sem sikerült: {ex}"
    df15, df1 = load_data(symbol)
    if df15 is None:
        return None, None, (msg if not ok else
                            "Nincs letöltött adat (data/m15, data/m1) ehhez a párhoz.")
    return df15, df1, None


def points_to_price(pips: float, point_size: float) -> float:
    return pips * point_size


def calc_pnl(trade: Trade, close_price: float) -> float:
    # Épített pozíció: a P&L a LÁBAKON (ráépítéseken) összegződik, mindegyik a saját
    # belépő áráról. Egyleges (üres legs) → a régi számítás (open_price, lot).
    legs = trade.legs if trade.legs else [(trade.open_price, trade.lot)]
    total = 0.0
    for price, lot in legs:
        diff = close_price - price
        if trade.direction == "SELL":
            diff = -diff
        total += (diff / trade.point_size) * lot * trade.pv1_point
    return total


# ---------------------------------------------------------------------------
# Risky mód — a live_trader viselkedésének modellezése a backtestben
# ---------------------------------------------------------------------------
# Instabil / gyenge minősítésű instrumentumnál a live óvatosabb. A backtestben
# ugyanezt modellezzük (különben a portfólió-BT túlbecsüli a gyenge párokat):
#   • feleződő kockázat (account_risk_pct × 0.5) → kisebb lot
#   • azonnali SL→BE (amint profitban van, nem vár a breakeven_pct küszöbre)
#   • azonnali trailing-aktiválás (0 pip) + feleződő trailing-távolság

RISKY_RISK_FACTOR  = 0.5   # account_risk_pct szorzó risky módban
RISKY_TRAIL_FACTOR = 0.5   # trail_distance szorzó risky módban


def _risky_trading_cfg(trading_cfg: dict, risky: bool) -> dict:
    """A méretezéshez használt trading_cfg — risky módban feleződő kockázattal."""
    if not risky:
        return trading_cfg
    return {**trading_cfg,
            "account_risk_pct": trading_cfg["account_risk_pct"] * RISKY_RISK_FACTOR}


def _update_stops(trade: "Trade", high: float, low: float, rr: dict,
                  point_size: float, risky: bool) -> None:
    """BE + trailing SL frissítése egy nyitott trade-re (mutálja trade.sl /
    risk_free). risky=False esetén BITAZONOS a korábbi inline logikával; risky=True
    a live_trader-t modellezi (azonnali BE, azonnali trailing, felezett távolság).

    ⚠ A paraméterek az `rr` SPECBŐL jönnek (v1.96.0), nem a stratégia
    `params`-ából: a BE/trailing a KOCKÁZATCSÖKKENTÉS része, nem a belépőjelzésé.
    Lásd `core/risk_reduction.BE_TRAIL_KEYS`."""
    # Épített pozíció (több láb): az SL az ÁTLAGÁRON van (a build kezeli) → nem
    # trailelünk (különben a trailing és az átlagár-stop egymással versenyezne).
    if len(trade.legs) > 1:
        return
    be_pct     = rr.get("breakeven_pct", 0.5)
    # A trailing aktiválása és követési távolsága a BELÉPÉSKORI ATR szorzója.
    # Miért nem abszolút távolság: az önmagában instrumentum-függő lenne (ugyanaz
    # a szám EURUSD-n és egy indexen mást jelent), ezért az optimalizálónak
    # páronként kellett kompenzálnia. Az ATR-szorzó instrumentumra ÉS volatilitási
    # rezsimre is normalizál, tehát egyetlen közös keresési tartomány elég.
    # FONTOS: az ismeretlen ATR csak a TRAILINGET tiltja, a BREAKEVEN-t nem — az
    # nem függ az ATR-től, és a kockázatmentesítés a fontosabb a kettő közül.
    _atr = float(getattr(trade, "entry_atr", 0.0) or 0.0)
    _trail_ok  = _atr > 0
    trail_act  = 0.0 if risky else rr.get("trail_activation_atr", 0.5) * _atr
    trail_dist = (rr.get("trail_distance_atr", 0.4) * _atr
                  * (RISKY_TRAIL_FACTOR if risky else 1.0))

    if trade.direction == "BUY":
        if (risky or be_pct > 0) and not trade.risk_free:
            be_trigger = (trade.open_price if risky
                          else trade.open_price + (trade.tp - trade.open_price) * be_pct)
            if high >= be_trigger:
                trade.sl = trade.open_price
                trade.risk_free = True
        if trade.risk_free and _trail_ok:
            trail_trigger = trade.open_price + trail_act      # ÁRban (ATR × szorzó)
            if high >= trail_trigger:
                new_sl = high - trail_dist
                if new_sl > trade.sl:
                    trade.sl = new_sl
    else:  # SELL
        if (risky or be_pct > 0) and not trade.risk_free:
            be_trigger = (trade.open_price if risky
                          else trade.open_price - (trade.open_price - trade.tp) * be_pct)
            if low <= be_trigger:
                trade.sl = trade.open_price
                trade.risk_free = True
        if trade.risk_free and _trail_ok:
            trail_trigger = trade.open_price - trail_act      # ÁRban (ATR × szorzó)
            if low <= trail_trigger:
                new_sl = low + trail_dist
                if new_sl < trade.sl:
                    trade.sl = new_sl


def daily_limit_usd(trading_cfg: dict, balance: float) -> float:
    """A napi veszteség-limit ÉRTÉKE $-ban — EGY igazságforrás (live + backtest +
    GUI). Az abszolút `daily_loss_limit_usd` nyer, ha > 0 (a felületről állítható);
    különben a régi `daily_loss_limit_pct` × egyenleg."""
    usd = float(trading_cfg.get("daily_loss_limit_usd", 0) or 0)
    if usd > 0:
        return usd
    return balance * float(trading_cfg.get("daily_loss_limit_pct", 0.015))


class _Row(dict):
    """Egy gyertya-sor a `bt_*` hookoknak — a pandas Series HELYETT.

    A hookok a soron három dolgot használnak: `row["oszlop"]`, `row.get(...)` és
    `row.name` (a sor időbélyege — pl. `ml_ai.bt_entry` gyorsítótár-kulcsa). A
    dict az elsőt kettőt tudja, a `name` slot a harmadikat.

    Miért nem pandas Series: az `iterrows()` SORONKÉNT új Series-t épít, ami a
    backtest futásidejének a legnagyobb egyedi tétele volt (mérve: 237 572 M1
    gyertyán 5,3 mp vs 0,17 mp — 20,7×; egy 500 triales optimalizálásban ~2,8 óra).
    """
    __slots__ = ("name",)


def _rr_spec(rr: "dict | None", risky: bool, symbol: str = "") -> dict:
    """A run_pair kockázatcsökkentő specje, ha a hívó nem adott sajátot.

    ⚠ A BE/trailing értékeket a PÁR SAJÁT kalibrációjából vesszük (v1.96.0).
    Enélkül az átköltöztetés NÉMA VISELKEDÉS-VÁLTOZÁS lett volna: korábban ezek a
    `params`-ban utaztak (a per-szimbólum execution-overlay-jel), most az rr-ben
    laknak — az `rr=None` hívók (optimalizáló, `run_backtest`) tehát a modul
    ALAPÉRTÉKÉRE estek volna vissza (0,5/0,5/0,4), a pár hangolt értéke helyett.

    ⚠⚠ A PRESET IS a páré (v2.23.0). Korábban az `rr=None` út a presetet
    HARDKÓDOLTAN `off`-ra állította, és csak a numerikus kalibrációt húzta a
    párról. Így az optimalizáló Ger40-en `off`-fal (BE + trailing AKTÍV) hangolt,
    miközben az él `none`-on futott (a stop meg sem mozdul) — a mentett
    paraméterek egy olyan világhoz tartoztak, ami élesben nem létezik. Mérve
    (1080 kötés, 22 hónap): `none` −512$ / 44,7% találat vs `off` −414$ / 39,3%
    — MÁS eloszlás, más optimum. Ugyanaz a hibaosztály, mint az `exec_gates`
    v1.95.0 előtt.

    Ezért: `rr=None` → a pár **ÉLES** specje (`rr_state.spec_for`), presettel,
    runnerrel, `cautious`/`cost_cut` kapcsolóval együtt. Ismeretlen szimbólumnál
    a `spec_for` maga is `off`-ot ad → a régi viselkedés megmarad.

    Kivétel a `risky=True`: azt a hívó KIFEJEZETTEN kéri (a portfólió-motor
    auto-risky ága a gyenge minősítésű párnál), tehát felülírja a pár presetjét.

    A régi viselkedés bármikor visszakérhető: adj át EXPLICIT `rr` specet."""
    if rr:
        return rr
    from core import risk_reduction as _rrm
    if risky:
        spec = _rrm.default_config()
        spec["preset"] = _rrm.PRESET_RISKY
        if symbol:
            try:
                from core import rr_state as _rrs
                _rrs.ensure_loaded()
                spec.update({k: v for k, v in _rrs.get_calibration(symbol).items()
                             if k in _rrm.BE_TRAIL_KEYS})
            except Exception:
                pass
        return spec
    if symbol:
        try:
            from core import rr_state as _rrs
            _rrs.ensure_loaded()
            return dict(_rrs.spec_for(symbol))     # ÉL-PARITÁS: preset is a páré
        except Exception:
            pass
    spec = _rrm.default_config()
    spec["preset"] = _rrm.PRESET_OFF
    return spec


def _manage_position(trade: "Trade", high: float, low: float,
                     point_size: float, min_lot: float, lot_step: float,
                     rr: dict) -> None:
    """Nyitott trade menedzselése egy bar-on: a preset szerint BE/trailing VAGY
    részleges zárás (Felező/Pajzs) 1R-nél + a runner stopja. Mutálja a trade-et
    (sl, lot, booked_pnl, reduced, runner_mode). A `booked_pnl` a záráskor adódik
    a végső P&L-hez.

    Meghívás: CSAK a nem-lezáró bar-okon (miután a TP/SL check nem zárt) — így a
    részleges zárás a beszálló és a stop KÖZÖTTI mozgásnál történik, 1R-nél.

    ⚠ NINCS `params` paramétere (v1.96.0). Ez SZERKEZETI döntés: a
    kockázatcsökkentés nem láthatja a stratégia paramétereit, mert semmi köze
    hozzájuk — minden, amire szüksége van, az `rr` specben van. Amíg a `params`
    itt volt, a BE/trailing „véletlenül" a stratégia listájából olvasott."""
    from core import risk_reduction as _rrm
    preset = rr.get("preset", _rrm.PRESET_OFF)
    if preset == _rrm.PRESET_SHIELD_FIBO:
        # Pajzs↔Fibo auto: a belépéskor eldöntött hatásos preset (a Trade-en
        # tárolva) — nagy mozgásnál fibo, különben shield.
        preset = trade.rr_preset_eff or _rrm.PRESET_SHIELD

    # none → TÉNYLEG semmi: a stop ott marad, ahol a belépéskor volt. Ez az egyetlen
    # preset, ami nem nyúl a pozícióhoz (a nyers stratégia-él méréséhez).
    if preset == _rrm.PRESET_NONE:
        return
    # off / risky → BE + trailing (BITAZONOS a korábbival; a néven változtattunk,
    # nem a viselkedésen — lásd risk_reduction.PRESET_OFF)
    if preset == _rrm.PRESET_OFF:
        _update_stops(trade, high, low, rr, point_size, risky=False)
        return
    if preset == _rrm.PRESET_RISKY:
        _update_stops(trade, high, low, rr, point_size, risky=True)
        return

    # fibo → stop-mozgatás a belépő→TP táv fibo_level (61,8%) pontján. NINCS
    # részleges zárás (a lot-létra sem érinti). A trigger ELŐTT a stop TÁVOL
    # marad (nincs BE/trailing — a tananyag: hagyjuk futni), a trigger UTÁN a
    # stop a fibo_stop_level szintre áll (0 = BE) és OTT MARAD; a TP változatlan.
    if preset == _rrm.PRESET_FIBO:
        if not trade.reduced:
            trig, new_stop = _rrm.fibo_levels(trade.open_price, trade.tp, rr)
            if trig:
                hit = (high >= trig if trade.direction == "BUY" else low <= trig)
                if hit:
                    trade.reduced = True
                    trade.runner_mode = _rrm.RUNNER_KEEP
                    trade.rr_technique = _rrm.PRESET_FIBO
                    if trade.direction == "BUY":
                        if new_stop > trade.sl:
                            trade.sl = new_stop
                        trade.risk_free = trade.sl >= trade.open_price
                    else:
                        if new_stop < trade.sl:
                            trade.sl = new_stop
                        trade.risk_free = trade.sl <= trade.open_price
        return

    # thirds → Harmados (1/3–2/3, „Birger"): R-alapú stop-létra, NINCS részleges
    # zárás. 1. lépcső: az ár megteszi a thirds_base_R×R alap-távot → a stop az
    # alap 1/3-ára (profitban → kockázatmentes, slot fel). 2. lépcső: a célár
    # (TP) érintésekor a stop a 2/3-ra — hard TP-nél a TP-check előbb zár, így
    # ez élesben akkor számít, ha a TP-t kézzel kivették/kitolták.
    if preset == _rrm.PRESET_THIRDS:
        is_buy = trade.direction == "BUY"
        trig, stop1, stop2 = _rrm.thirds_levels(
            trade.open_price, trade.sl_points * point_size, is_buy, rr)
        if not trig:
            return
        if not trade.reduced:
            hit = (high >= trig if is_buy else low <= trig)
            if hit:
                trade.reduced = True
                trade.runner_mode = _rrm.RUNNER_KEEP
                trade.rr_technique = _rrm.PRESET_THIRDS
                if is_buy and stop1 > trade.sl:
                    trade.sl = stop1
                elif not is_buy and stop1 < trade.sl:
                    trade.sl = stop1
                trade.risk_free = True   # a stop az alap 1/3-án: profit bezárva
        else:
            hit2 = (high >= trade.tp if is_buy else low <= trade.tp)
            if hit2:
                if is_buy and stop2 > trade.sl:
                    trade.sl = stop2
                elif not is_buy and stop2 < trade.sl:
                    trade.sl = stop2
        return

    # halving / shield → 1R-nél részleges zárás (egyszer), utána runner-stop
    if not trade.reduced:
        one_r = trade.sl_points * point_size
        hit = (high >= trade.open_price + one_r if trade.direction == "BUY"
               else low <= trade.open_price - one_r)
        if hit:
            plan = _rrm.plan_at_trigger(preset, rr, trade.lot, min_lot, lot_step)
            trade.reduced = True
            trade.runner_mode = plan.runner_stop
            trade.rr_technique = plan.effective
            if plan.close_lot > 0.0:
                # a lezárt lot +1R-t realizál (a 1R áron zárunk részlegesen)
                trade.booked_pnl += trade.sl_points * plan.close_lot * trade.pv1_point
                _new_lot = round(trade.lot - plan.close_lot, 8)
                # A LÁBAKAT is arányosan zsugorítjuk: a P&L a lábakon számolódik
                # (calc_pnl), így a részleges zárás nélkülük „elveszne" — az épített
                # csomag a zárás után is a teljes mérettel számolna. (A ráépítés csak
                # kockázatmentes pozícióra jön, ami épp ITT keletkezik → a részleges
                # zárás pillanatában a csomag még egyleges.)
                if trade.legs and trade.lot > 0:
                    _f = _new_lot / trade.lot
                    trade.legs = [(p, round(l * _f, 8)) for p, l in trade.legs]
                trade.lot = _new_lot
                # A trade mostantól KOCKÁZATMENTES: a lezárt (≥50%) profit fedezi a
                # runner max veszteségét (nettó ≥ 0). Ezért felszabadítja a slotot
                # (mint az OFF-nál a BE 1R-nél) — a runner "house money".
                trade.risk_free = True

    # A runner stopjának kezelése (a részleges zárás UTÁN, vagy risky-degradált BE)
    if trade.reduced:
        if trade.runner_mode == _rrm.RUNNER_BREAKEVEN and not trade.risk_free:
            if ((trade.direction == "BUY" and trade.sl < trade.open_price) or
                    (trade.direction == "SELL" and trade.sl > trade.open_price)):
                trade.sl = trade.open_price
                trade.risk_free = True
        elif trade.runner_mode == _rrm.RUNNER_TRAILING:
            trade.risk_free = True
            _update_stops(trade, high, low, rr, point_size, risky=False)
        # RUNNER_KEEP → a stop marad az EREDETI (távol) helyén — a videó Pajzsa


def _build_bigmove_evaluator(m15: pd.DataFrame, rr_spec: dict):
    """Pajzs↔Fibo auto: „nagy mozgás"-e a piac az i-edik M15 gyertyán?

    Visszaad egy `fn(i) -> bool`-t, vagy None-t, ha a preset nem shield_fibo.
    KERETRENDSZER-szintű, generikus ATR (mint a live spread-kapué, NEM a
    stratégia indikátora): ATR(14) vs a 100-gyertyás gördülő átlaga — az arány
    a spec `big_move_atr_mult` (alap 2.0) fölött = nagy mozgás → Fibo."""
    from core import risk_reduction as _rrm
    if rr_spec.get("preset") != _rrm.PRESET_SHIELD_FIBO:
        return None
    from core.indicator_engine import atr as _atrf
    a  = _atrf(m15["high"], m15["low"], m15["close"], 14)
    av = a.rolling(100, min_periods=20).mean()
    an, avn = a.to_numpy(), av.to_numpy()
    mult = float(rr_spec.get("big_move_atr_mult", 2.0))
    def _at(i):
        if i < 0 or i >= len(an):
            return False
        x, y = an[i], avn[i]
        if np.isnan(x) or np.isnan(y) or y <= 0:
            return False
        return bool(x > mult * y)
    return _at


def _build_exit_evaluator(m15: pd.DataFrame, rr_spec: dict):
    """A KISZÁLLÁSI-modul kiértékelője a backtesthez (mindkét motor használja).

    Visszaad egy `fn(i, direction) -> bool`-t: az `i`-edik (a backtest `m15_ptr`-je
    szerinti) M15 gyertyán szól-e a kiszállási jel. `None`, ha a modul nincs
    bekapcsolva (runner != exit). Az indikátort EGYSZER számoljuk ki a teljes M15-re
    (nem gyertyánként) → nincs teljesítmény-vesztés. A `core.exit_signal` élő
    logikájával AZONOS: Supertrend-flip / WPR-átzárás."""
    ex = rr_spec.get("exit") or {}
    if not ex.get("enabled"):
        return None
    from core import exit_signal as _exsig
    from core.indicator_engine import supertrend as _st, wpr as _wprf, sma as _smaf
    ind = ex.get("indicator", _exsig.INDICATOR_SUPERTREND)
    if ind == _exsig.INDICATOR_DIVERGENCE:
        # Divergencia: irányonként EGYSZER kiszámoljuk a gyertyánkénti jelet (a series
        # már look-ahead-mentes: a pivot az i+pivot gyertyán erősödik meg).
        osc = ex.get("osc", _exsig.OSC_RSI)
        per = int(ex.get("div_period", 14)); piv = int(ex.get("div_pivot", 5))
        buy_s  = _exsig.divergence_exit_series(m15, "BUY",  osc, per, piv)
        sell_s = _exsig.divergence_exit_series(m15, "SELL", osc, per, piv)
        def _at(i, direction):
            arr = buy_s if direction == "BUY" else sell_s
            return bool(0 <= i < len(arr) and arr[i])
        return _at
    if ind == _exsig.INDICATOR_WPR:
        w  = _wprf(m15["high"], m15["low"], m15["close"], int(ex.get("wpr_period", 20)))
        ma = _smaf(w, int(ex.get("wpr_ma_period", 100))).to_numpy()
        wa = w.to_numpy()
        def _at(i, direction):
            if i < 1 or i >= len(wa):
                return False
            wp, wc, mp, mc = wa[i-1], wa[i], ma[i-1], ma[i]
            if any(np.isnan(x) for x in (wp, wc, mp, mc)):
                return False
            return (wp >= mp and wc < mc) if direction == "BUY" else (wp <= mp and wc > mc)
        return _at
    # default: Supertrend — flip a pozícióval szembe
    _line, _dir = _st(m15["high"], m15["low"], m15["close"],
                      int(ex.get("st_period", 10)), float(ex.get("st_multiplier", 1.7)))
    da = _dir.to_numpy()
    def _at(i, direction):
        if i < 0 or i >= len(da):
            return False
        return (int(da[i]) == -1) if direction == "BUY" else (int(da[i]) == 1)
    return _at


# A `run_pair(tf_eval=…)` alapértéke. Külön sentinel kell, mert a `None` ÉRVÉNYES
# érték: „nincs TF-kapu ezen a páron/stratégián". Az alapérték jelentése: „építsd
# meg magad a cfg-ből". Az optimalizáló EGYSZER építi ablakonként, és ide adja be
# — a kapu ugyanis NEM függ a trial paramétereitől, viszont resample-t igényel.
_TF_EVAL_AUTO = object()


def _pair_market_series(cfg, symbol, strategy_name, m15, exec_gates: bool):
    """A piac-kapu per-gyertya besorolása (`pd.Series` kategória-nevekkel), vagy
    None, ha a kapu ki van kapcsolva / nincs kiválasztott osztályozó.

    EGYSZER épül párenként (mint a TF-kiértékelő): a besorolás nem függ a
    stratégia paramétereitől, tehát trialonként újraszámolni pazarlás volna."""
    if not exec_gates:
        return None
    try:
        from core import gates as _gt
        from core import market_strategy as _ms
        if not _gt.active(_gt.effects_for(cfg or {}, symbol, strategy_name),
                          _gt.MARKET):
            return None
        name = _ms.market_name_of((cfg.get("pairs") or {}).get(symbol) or {})
        return _ms.classify_series(name, m15) if name else None
    except Exception:
        return None


def _pair_momentum(cfg, symbol, strategy_name, m15, df_m1, exec_gates: bool) -> dict:
    """A Lendület-kapu előkészítése egy párra: `{mom_series, mom_cfg, mom_mode}`.

    EGYSZER épül párenként (mint a piac-besorolás és a TF-kiértékelő): a fordulat
    nem függ a stratégia paramétereitől. A `mom_series` `None`, ha a kapu ki van
    kapcsolva erre a (pár, stratégia) párosra — ilyenkor mérni sem kell."""
    out = {"mom_series": None, "mom_cfg": None, "mom_mode": None}
    if not exec_gates:
        return out
    try:
        from core import gates as _gt
        from core import momentum as _momx
        if not _gt.active(_gt.effects_for(cfg or {}, symbol, strategy_name),
                          _gt.MOMENTUM):
            return out
        pc = (cfg.get("pairs") or {}).get(symbol) or {}
        out["mom_cfg"] = _gt.momentum_config(pc, cfg)
        out["mom_mode"] = _gt.mode_for(cfg or {}, symbol, strategy_name)
        out["mom_series"] = _momx.series_at(df_m1, m15.index, out["mom_cfg"])
    except Exception:
        out["mom_series"] = None
    return out


def _build_tf_align_evaluator(cfg, symbol, strategy_name, df_m1):
    """A TF-együttállás VÉGREHAJTÁSI kapu historikus kiértékelője a backtesthez —
    UGYANAZ a logika, mint az él (`core.tf_align`) és a viz jel-replay-e
    (`live_trader.tf_align_gate_fn`), csak az adat a backtest saját M1-jéből jön.

    A kapu idősíkonként `sign(close − SMA(sma_period))`; a belépő csak akkor enged,
    ha MINDEN figyelt idősík a jel irányába állt. A magasabb idősíkokat (M5/M15…) az
    M1-ből mintázzuk újra, a `tf_align` SAJÁT `sma_period`-jával és idősíkjaival
    (per-pár felülírható) — így a backtest bitre azt a kaput modellezi, amit az él.

    A `df_m1` a TELJES (nem a test-ablakra vágott) M1 → a magasabb idősíkok SMA-ja
    a test-ablak elején is warmupolt (nem blokkol feleslegesen).

    KONVENCIÓ (közös a viz-replay-jel, `core.tf_align.build_historical_gate`): a jel
    pillanatában FORMÁLÓDÓ TF-gyertyát nézzük, de annak a záróára az AKKOR ISMERT ár
    (a döntést hozó M1-gyertya close-a), NEM a gyertya végleges záróára. Ez utóbbi
    LOOK-AHEAD volt: egy M15-kapunál akár 15 percnyi jövőbelátás, amitől a backtest
    más belépőket engedett át, mint az él.

    Visszaad: `fn(entry_unix, price, direction) -> bool`, vagy None, ha a kapu erre a
    stratégiára/instrumentumra nincs bekapcsolva."""
    try:
        import numpy as _np
        from core import tf_align as _tfa
        # ⚠ A STRATÉGIA is számít: az együttállás idősíkjai stratégiánként
        # eltérhetnek (H1-en döntő stratégiának az M1/M5/M15 zajt mér, nem
        # kontextust) — `tf_align.per_strategy`.
        en, tfs, sma, gate = _tfa.config_for(cfg, symbol, strategy_name)
        if not en or strategy_name not in gate or not tfs:
            return None
        if "close" not in df_m1.columns:
            return None
        close_m1 = df_m1["close"]
        bars_by_tf = {}
        for tf in tfs:
            tf = int(tf)
            closes = (close_m1 if tf <= 1
                      else close_m1.resample(f"{tf}min").last().dropna())
            open_unix = (closes.index.view("int64") // 1_000_000_000).astype(_np.int64)
            bars_by_tf[tf] = (open_unix, closes.to_numpy(dtype=float))
            if len(closes) < sma:
                # Az él ilyenkor BLOKKOLNA (nincs elég gyertya az SMA-hoz), ezért a
                # backtest is blokkol — de szóljunk, különben „miért nincs egy kötés
                # sem?" lesz belőle.
                log.warning("%s/%s — a TF-együttállás kapu M%d idősíkján csak %d "
                            "gyertya van (SMA %d kell) → a kapu MINDENT blokkol, "
                            "ahogy élesben is. Tölts le hosszabb előzményt.",
                            symbol, strategy_name, tf, len(closes), sma)
        return _tfa.build_historical_gate(bars_by_tf, sma)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Fő szimuláció egy párra
# ---------------------------------------------------------------------------

def run_pair(
    symbol: str,
    df_m15: pd.DataFrame,
    df_m1: pd.DataFrame,
    params: dict,
    pair_cfg: dict,
    trading_cfg: dict,
    initial_balance: float,
    test_start: Optional[str] = None,
    strategy=None,
    allowed_hours: Optional[set] = None,
    risky: bool = False,
    rr: "dict | None" = None,
    test_end: Optional[str] = None,
    progress_callback=None,
    build: "dict | None" = None,
    record_events: bool = False,
    stop_flag=None,
    cfg: "dict | None" = None,
    exec_gates: bool = False,
    tf_eval=_TF_EVAL_AUTO,
) -> BacktestResult:
    # A jelzést/indikátorokat a STRATÉGIA adja (seam); a végrehajtás (SL/TP/
    # breakeven/trailing, slot, lot) a motoré. strategy=None → config szerinti.
    # risky=True → a live_trader óvatos módját modellezzük (felezett kockázat,
    # azonnali BE, azonnali+felezett trailing). Az optimalizáló risky=False-szal
    # hív (a mentett test_summary/minősítés az ALAP-viselkedést tükrözze).
    # rr = kockázatcsökkentő spec (preset + kalibráció); None → a `risky` flagből
    # (off/risky) → a meglévő hívók BITAZONOSAK maradnak.
    if strategy is None:
        strategy = get_strategy({})
    # A stratégia-hookok pár-azonosító adatai (pl. az ml_ai modell-betöltése és
    # feature-normalizálása): a params-ba injektáljuk a pair config tényadatait.
    # A symbol/point_size a pair config-ból AUTORITATÍV; a session default-olható
    # (a per-pár optimalizált params felülírhatja). A wpr_sma ezeket nem olvassa
    # → a meglévő viselkedés bitazonos.
    params = {**params, "symbol": symbol, "point_size": pair_cfg["point_size"]}
    params.setdefault("sess_start", pair_cfg.get("sess_start", 0))
    params.setdefault("sess_end",   pair_cfg.get("sess_end", 24))
    from core import risk_reduction as _rrm
    rr_spec    = _rr_spec(rr, risky, symbol)
    # Óvatos (felezett) méret? A spec `cautious` felülbírálja, különben a preset
    # dönti (Risky felezi; a többi alap normál).
    _cautious  = rr_spec.get("cautious")
    if _cautious is None:
        _cautious = _rrm.wants_cautious_size(rr_spec.get("preset", _rrm.PRESET_OFF))
    sizing_cfg = _risky_trading_cfg(trading_cfg, bool(_cautious))
    tf_hi = strategy.timeframes()[0].label
    tf_lo = strategy.timeframes()[1].label

    result = BacktestResult(symbol=symbol)

    # Indikátorok számítása (a stratégia dönti el, mely indikátorok)
    m15, m1 = strategy.bt_indicators(df_m15, df_m1, params)

    # Warmup sor — az első érvényes indikátor sor
    m15 = m15.iloc[strategy.bt_warmup(params, tf_hi):].copy()
    m1  = m1.iloc[strategy.bt_warmup(params, tf_lo):].copy()

    # Test/train szétválasztás
    if test_start:
        ts = pd.Timestamp(test_start)
        # Ha az index UTC-aware, a Timestamp-ot is UTC-ra kell állítani
        if m15.index.tzinfo is not None:
            ts = ts.tz_localize("UTC")
        m15 = m15[m15.index >= ts]
        m1  = m1[m1.index >= ts]

    # Záró dátum (a B3 Backtest-ablak állítható időszakához; None → a hist. vége)
    if test_end:
        te = pd.Timestamp(test_end)
        if m15.index.tzinfo is not None:
            te = te.tz_localize("UTC")
        m15 = m15[m15.index <= te]
        m1  = m1[m1.index <= te]

    # Óra-szűrő: alapból MINDEN órát kereskedünk (az optimalizáló így teljes
    # óránkénti bontást ad, amiből a trade_hours kézzel dönthető el). Az
    # allowed_hours (ha adott) csak a preview-hoz szűr — a live óra-kapuja külön.
    # A belépés-szűrőket (pl. volatilitás) és az SL/TP-méretezést a STRATÉGIA adja
    # a `bt_entry` hookban → a motor stratégia-független.

    point_size = pair_cfg["point_size"]
    pv1_point  = pair_cfg["pv1_point"]
    min_lot  = pair_cfg.get("min_lot", 0.01)    # a lot-létrához (részleges zárás)
    lot_step = pair_cfg.get("lot_step", 0.01)

    state = strategy.bt_new_state(symbol)
    open_trades: list[Trade] = []
    balance = initial_balance
    daily_pnl: dict[str, float] = {}  # dátum → napi P&L

    # M15 gyertyák indexe gyors kereséshez
    m15_times = m15.index.to_list()
    m15_ptr = 0  # a legutóbb LEZÁRT és feldolgozott M15 gyertya indexe
    _m15_delta = pd.Timedelta(minutes=strategy.timeframes()[0].minutes)  # egy M15 hossza
    _exit_at = _build_exit_evaluator(m15, rr_spec)   # kiszállási-jel (None, ha nincs)
    _bigmove_at = _build_bigmove_evaluator(m15, rr_spec)  # Pajzs↔Fibo auto (None, ha nem az)
    # Cost-cut (idő-stop, tananyag 2.6): a nyitás után N fő-tf gyertyával még
    # VESZTESÉGES trade-et piaci áron zárjuk (kanóc/zaj korai levágása töredék-R
    # veszteséggel). Bármely presettel kombinálható; default KI.
    _cc_on    = bool(rr_spec.get("cost_cut"))
    _cc_delta = pd.Timedelta(minutes=strategy.timeframes()[0].minutes *
                             int(rr_spec.get("cost_cut_bars", 12)))
    # Pozícióépítés modellezése. BÁRMELY presettel (ahogy élesben is: a live minden
    # KOCKÁZATMENTES pozícióra épít — a Felező/Pajzs runnerére is, nem csak az OFF
    # preset breakeven-jére); a részleges zárás a lábakat arányosan zsugorítja.
    # Mód szerint: Auto MINDIG, Kézi CSAK R-alapú triggernél (az determinisztikus →
    # backtestelhető; a gyertyás Kézi user-kattintás, azt nem modellezzük).
    # A `build` override (a Backtest-ablak FELTÁRÓ Építés-beállítása) elsőbbséget élvez
    # a globális/live build_state fölött → az ablakban kísérletezhetünk anélkül, hogy a
    # live-ot piszkálnánk. None → a per-pár mentett állapot (mint eddig).
    _build_cfg = None
    try:
        from core import build_state as _bstate, position_build as _posbuild
        _bc = build if build is not None else _bstate.get_config(symbol)
        _bmode = _bc.get("mode")
        _btrig = _bc.get("trigger", _posbuild.TRIGGER_CANDLE)
        _r_based = _btrig in (_posbuild.TRIGGER_R_FIXED, _posbuild.TRIGGER_R_CONVERGE)
        if (_bmode == _posbuild.MODE_AUTO
                or (_bmode == _posbuild.MODE_MANUAL and _r_based)):
            _build_cfg = {**_posbuild.default_config(), **_bc}
    except Exception:
        _build_cfg = None

    prev_m1_row = None

    # ── Végrehajtási kapuk (él-paritás, opcionális) ─────────────────────────
    # exec_gates=True → a backtest ugyanazokat a VÉGREHAJTÁSI kapukat modellezi,
    # amiket az él: (1) spread-kapu (core.spread_gate — közös képlet), (2) TF-
    # együttállás (core.tf_align, ha a `cfg`-ben erre a stratégiára be van kapcsolva).
    # Alap KI → a meglévő hívók (optimizer stb.) BITAZONOSAK maradnak. A TF-kaput a
    # TELJES (vágatlan) df_m1-ből építjük, hogy a magasabb idősíkok SMA-ja warmupolt.
    #
    # A TF-kapu kiértékelője NEM függ a trial paramétereitől (csak a cfg-től, a
    # szimbólumtól és az M1 adattól), viszont resample-t + SMA-t igényel. Ezért a
    # hívó BEADHATJA előre megépítve (`tf_eval=`) — az optimalizáló ablakonként
    # EGYSZER építi, nem trialonként. Az alapérték a saját építés (a `None`
    # ÉRVÉNYES érték: „nincs kapu ezen a páron/stratégián").
    from core import spread_gate as _spread_gate
    from core import gates as _gt
    _exec_gates = bool(exec_gates)
    if tf_eval is not _TF_EVAL_AUTO:
        _tf_eval = tf_eval if _exec_gates else None
    else:
        _tf_eval = (_build_tf_align_evaluator(cfg, symbol, strategy.name, df_m1)
                    if (_exec_gates and cfg is not None) else None)
    # ── A kapuk HATÁSA (v1.97.0) — nem csak be/ki, hanem blokkol/csökkent/ki ──
    # Ugyanaz a config és ugyanaz a döntés-modul, mint élesben (`core/gates.py`),
    # így a backtest nem modellezhet mást, mint amit az él tesz.
    _gate_eff = (_gt.effects_for(cfg or {}, symbol, strategy.name)
                 if _exec_gates else {k: _gt.EFFECT_NONE for k in _gt.KEYS})
    # A piac-kapu per-gyertya besorolása — EGYSZER, mint a TF-kiértékelő
    # (paraméter-független). None, ha a kapu ki van kapcsolva vagy nincs osztályozó.
    _mkt_series, _mkt_adverse = None, set()
    if _exec_gates and _gt.active(_gate_eff, _gt.MARKET):
        try:
            from core import market_strategy as _msx
            _mname = _msx.market_name_of(pair_cfg)
            if _mname:
                _mkt_series = _msx.classify_series(_mname, df_m15)
                _mkt_adverse = _gt.market_adverse(cfg or {}, symbol)
        except Exception:
            _mkt_series = None
    # A Lendulet-kapu per-gyertya sorozata — EGYSZER, a dontesi idopontokra,
    # look-ahead nelkul (`momentum.series_at`: zarasi idohoz igazitva).
    # A költség-kapu küszöbe (alap ← globális ← pár) — a mérés a belépőnél megy.
    _cost_cap = _gt.cost_max_distortion(pair_cfg, cfg)
    _mom_series, _mom_cfg, _mom_mode = None, None, None
    if _exec_gates and _gt.active(_gate_eff, _gt.MOMENTUM):
        try:
            from core import momentum as _momx
            _mom_cfg = _gt.momentum_config(pair_cfg, cfg)
            _mom_mode = _gt.mode_for(cfg or {}, symbol, strategy.name)
            _mom_series = _momx.series_at(df_m1, df_m15.index, _mom_cfg)
        except Exception:
            _mom_series = None

    # ── BID/ASK modell előkészítés (MT5-hű) ─────────────────────────────────
    # Az MT5 chart/tester gyertyái BID árak; ask-gyertya NINCS. A mi adatunk is
    # BID-ből épül (tools/download_history), bar-onként az `avg_spread`-del
    # (ask−bid, ÁRBAN). A végrehajtás a valós mechanika szerint:
    #   BUY  → ASK-on lép be (close + s), a SL/TP a BID-en (nyers OHLC) triggerel
    #   SELL → BID-en lép be (close),     a SL/TP az ASK-on (OHLC + s) triggerel
    # Így egy körbeforduló kötés PONTOSAN egy spreadet fizet — mint élesben.
    # Ha nincs avg_spread (régi adat), a pár `backtest_spread_points`-e a tartalék.
    _spread_fallback = points_to_price(
        float(pair_cfg.get("backtest_spread_points", 1.5)), point_size)
    _spread_arr = (m1["avg_spread"].to_numpy(dtype=float)
                   if "avg_spread" in m1.columns else None)
    # A BELÉPŐ a gyertya ZÁRÁSÁN történik → ott a bar UTOLSÓ tickjének spreadje a
    # pontos (`close_spread`). Ha nincs (régi adat), az átlag a tartalék.
    _cspread_arr = (m1["close_spread"].to_numpy(dtype=float)
                    if "close_spread" in m1.columns else None)

    # Intrabar SL/TP sorrend: ha EGY baron belül a TP és az SL is elérhető, a
    # bar-adatból NEM derül ki, melyik jött előbb (ehhez tick kellene).
    #   "pessimistic" (ALAP) → az SL nyer  — óvatos, nem szépít
    #   "optimistic"         → a TP nyer   — a korábbi viselkedés
    _sl_first = str(params.get("intrabar_order", "pessimistic")) != "optimistic"

    # ── Progressz-visszajelzés (B3 Backtest-ablak) ──────────────────────────
    # Best-effort: időnként jelenti a haladást (%), az aktuális egyenleget, a
    # nyitott/lezárt kötések számát és a ténylegesen alkalmazott rr-technikákat.
    # progress_callback=None → nincs overhead (a meglévő hívók változatlanok).
    total_m1 = len(m1)
    _PROG_EVERY = 4096

    def _report(i: int, m1_time):
        if progress_callback is None:
            return
        from collections import Counter as _Counter
        tech = dict(_Counter(getattr(t, "rr_technique", "") for t in result.trades
                             if getattr(t, "rr_technique", "")))
        try:
            progress_callback((i + 1) / total_m1 if total_m1 else 1.0,
                              m1_time, balance, len(open_trades),
                              len(result.trades), tech)
        except Exception:
            pass

    # ── AZ M1-CIKLUS ADATELÉRÉSE — a futásidő legnagyobb egyedi tétele ─────────
    # A `m1.iterrows()` SORONKÉNT új pandas Series-t épít. Mérve (UsaInd, egy
    # 8 hónapos WF-ablak, 237 572 M1 gyertya):
    #     iterrows()                 5,30 mp
    #     dict numpy-tömbökből       0,21 mp   → 26×
    # Egy 500 triales optimalizálásban (4 ablak/trial) ez ~2,8 ÓRA tiszta
    # overhead a ~9-ből, nulla haszonnal.
    #
    # ⚠ Miért nem itertuples/nyers numpy: a STRATÉGIA-SZERZŐDÉS a `bt_*` hookoknak
    # egy pandas Series-SORT ígér. A ténylegesen használt felület három dolog:
    #     row["oszlop"] · row.get(...) · row.name  (a sor IDŐBÉLYEGE)
    # A `.name` nem elméleti: az `ml_ai.bt_entry` gyorsítótár-kulcsként használja
    # (`key = hi_row.name`). Ezért a sor egy dict-leszármazott, ami a `.name`-et is
    # viszi — így EGYETLEN stratégiát sem kell módosítani, a gyorsítás
    # viselkedés-semleges marad. (Mérve: 20,7× az iterrows()-hoz képest.)
    _m1_cols = list(m1.columns)
    _m1_col_arr = {c: m1[c].to_numpy() for c in _m1_cols}
    _m1_index = list(m1.index)          # pandas Timestamp — kell a .hour/.date()
    _m1_n = len(_m1_index)

    for i in range(_m1_n):
        m1_time = _m1_index[i]
        m1_row = _Row()
        m1_row.name = m1_time
        for _c in _m1_cols:
            m1_row[_c] = _m1_col_arr[_c][i]
        if i % _PROG_EVERY == 0:
            # Megszakítás (a Backtest-ablak „Megszakítás" gombja / ablak bezárása):
            # a részeredménnyel visszatérünk (a hívó eldobja). Ritkán ellenőrzünk
            # (4096 bar-onként) → nincs érdemi overhead.
            if stop_flag is not None and stop_flag.is_set():
                break
            if progress_callback is not None:
                _report(i, m1_time)
        # Óra-szűrő (csak ha allowed_hours adott — preview; egyébként minden óra).
        # A no-trade órában nem kereskedünk. A jelzés-reset (mint a live/viz) CSAK ha a
        # `no_trade_resets_signal` param be van kapcsolva (alap: KI) → a szünet után
        # nulláról fegyverkezik. Kikapcsolva a szünet előtti M15 ablak túléli a szünetet.
        # Óra-szűrő: a trade_hours-on kívül CSAK a BELÉPŐT tiltjuk (mint élesben). A
        # M15-állapot frissítése ÉS a nyitott pozíciók kezelése (SL/TP) MEGY tovább —
        # különben a szünet befagyasztaná a setupot (a belépő az engedélyezett órában
        # sem tüzelne), és az off-órában elért SL/TP sem záródna. (allowed_hours=None →
        # _off_hour végig False → a viselkedés BITAZONOS a korábbival.)
        hour = m1_time.hour
        _off_hour = allowed_hours is not None and hour not in allowed_hours
        if _off_hour and params.get("no_trade_resets_signal", False):
            state = strategy.bt_new_state(symbol)

        # ── Napi veszteség limit ──────────────────────────────────────────────
        # ⚠ A limit CSAK AZ ÚJ BELÉPŐT tiltja — pontosan úgy, ahogy az élő motor
        # (`live_trader`: „a limit CSAK az ÚJ belépőt tiltja — a nyitott pozíciók
        # kezelése … limit fölött is fut tovább (korábban a korai return azt is
        # leállította volna)"). Ezt a javítást az él MEGKAPTA, a backtest NEM: itt
        # egy korai `continue` állt, ami a bar TELJES feldolgozását átugrotta —
        # a nyitott pozíciók SL/TP-jét, a BE/trailinget és a jelzés-állapotgépeket is.
        #
        # Következménye kettő volt, és mindkettő az él ELLEN dolgozott:
        #  • egy limit-napon NYITOTT pozíció nem záródhatott (a stopja sem fogott),
        #  • az M15/M1 állapotgép megállt, tehát a limit-nap UTÁN más setupból indult.
        #
        # (Ugyanaz a minta, mint az óra-szűrőnél: ott is csak a BELÉPŐ tiltott,
        # a figyelés folyamatos — lásd a `_off_hour` kezelését lentebb.)
        day_key = str(m1_time.date())
        daily_loss = daily_pnl.get(day_key, 0.0)
        daily_limit = daily_limit_usd(trading_cfg, balance)
        _limit_hit = daily_loss <= -daily_limit

        # M15 állapot: minden ÚJONNAN ZÁRT M15 gyertyát EGYSZER dolgozunk fel, a
        # LEZÁRT bart használva (nem a formálódót). Korábban a motor MINDEN M1-ticknél
        # újrafuttatta a M15-állapotgépet a FORMÁLÓDÓ (open ≤ t) barra → look-ahead ÉS
        # az M1 arming-állapot ismételt újraszámítása → valós belépők maradtak ki (pl.
        # a délutáni trendben). Egy M15 bar (nyitó m15_times[j]) egy TF-periódus múlva zár.
        while (m15_ptr + 1 < len(m15_times)
               and m15_times[m15_ptr + 1] + _m15_delta <= m1_time):
            m15_ptr += 1
            state = strategy.bt_on_high_close(state, m15.iloc[m15_ptr], params)

        # Nyitott pozíciók kezelése (SL/TP/breakeven/trailing) — BID/ASK modellel
        _sp = _spread_arr[i] if _spread_arr is not None else float("nan")
        if not (_sp > 0):                       # NaN / hiány → config-tartalék
            _sp = _spread_fallback
        spread_points = _sp / point_size            # a pnl_points + swing-SL számításhoz
        # A gyertya BID; az ASK-sorozat = BID + spread. A kilépés mindig a
        # SZEMBENI oldalon történik (BUY→bid, SELL→ask).
        bid_hi, bid_lo = m1_row["high"], m1_row["low"]            # BUY ezen zár
        ask_hi, ask_lo = m1_row["high"] + _sp, m1_row["low"] + _sp  # SELL ezen zár

        for trade in list(open_trades):
            closed = False
            if record_events:
                _ev_sl0, _ev_lot0 = trade.sl, trade.lot

            if trade.direction == "BUY":
                # TP ellenőrzés — ÉPÍTETT csomagnál NINCS TP (a live a ráépítéskor
                # törli minden láb TP-jét, hogy az induló láb ne zárjon önállóan;
                # a csomag az átlagár-stopig / kiszállási jelig fut).
                # A BUY a BID-en zár → a TP/SL a BID-sorozaton triggerel. Ha MINDKETTŐ
                # elérhető egy baron, a sorrendet a `_sl_first` dönti (lásd fent).
                _tp_hit = (not trade.built) and bid_hi >= trade.tp
                _sl_hit = bid_lo <= trade.sl
                if _sl_hit and (_sl_first or not _tp_hit):
                    trade.close_price = trade.sl
                    trade.close_time  = m1_time
                    trade.pnl_usd     = calc_pnl(trade, trade.sl)
                    trade.status      = "sl"
                    closed = True
                elif _tp_hit:
                    trade.close_price = trade.tp
                    trade.close_time  = m1_time
                    trade.pnl_usd     = calc_pnl(trade, trade.tp)
                    trade.status      = "tp"
                    closed = True
                else:
                    # A BE/trailing is a KILÉPÉSI (bid) oldalon mér
                    _manage_position(trade, bid_hi, bid_lo,
                                     point_size, min_lot, lot_step, rr_spec)

            elif trade.direction == "SELL":
                # A SELL az ASK-on zár → a TP/SL az ASK-sorozaton triggerel. Ha MINDKETTŐ
                # elérhető egy baron, a sorrendet a `_sl_first` dönti (lásd fent).
                _tp_hit = (not trade.built) and ask_lo <= trade.tp
                _sl_hit = ask_hi >= trade.sl
                if _sl_hit and (_sl_first or not _tp_hit):
                    trade.close_price = trade.sl
                    trade.close_time  = m1_time
                    trade.pnl_usd     = calc_pnl(trade, trade.sl)
                    trade.status      = "sl"
                    closed = True
                elif _tp_hit:
                    trade.close_price = trade.tp
                    trade.close_time  = m1_time
                    trade.pnl_usd     = calc_pnl(trade, trade.tp)
                    trade.status      = "tp"
                    closed = True
                else:
                    _manage_position(trade, ask_hi, ask_lo,
                                     point_size, min_lot, lot_step, rr_spec)

            # ── Esemény-napló: a menedzsment-fázis (részleges zárás + stop-mozgás)
            # változásai. A TP/SL-záró bar-on a `else` nem futott → nincs változás.
            # (A build-fázis változásait külön, a ráépítés helyén naplózzuk.)
            if record_events and not closed:
                if trade.reduced and trade.lot < _ev_lot0:
                    _1r = trade.sl_points * point_size
                    _pp = (trade.open_price + _1r if trade.direction == "BUY"
                           else trade.open_price - _1r)
                    trade.events.append(("PARTIAL_CLOSE", m1_time, round(_pp, 6),
                                         0.0, 0.0, round(_ev_lot0 - trade.lot, 8),
                                         trade.rr_technique or "reduce"))
                if trade.sl != _ev_sl0:
                    _be = abs(trade.sl - trade.open_price) < point_size * 0.5
                    trade.events.append(("SL_MODIFY", m1_time, 0.0,
                                         round(trade.sl, 6), 0.0, 0.0,
                                         "BE" if _be else "TRAIL"))

            # Runner KISZÁLLÁSI JELRE zárása (Pajzs/Felező maradéka, TP nélkül fut):
            # a részleges zárás UTÁN figyeljük; a jel az m15_ptr gyertyán (ugyanaz az
            # index, amit a belépő-jel is használ → nincs look-ahead). A gyertyazáró
            # áron zárunk.
            if (not closed and _exit_at is not None and trade.reduced
                    and trade.runner_mode == _rrm.RUNNER_EXIT
                    and _exit_at(m15_ptr, trade.direction)):
                # piaci zárás a SZEMBENI oldalon (BUY→bid=close, SELL→ask=close+s)
                trade.close_price = (m1_row["close"] if trade.direction == "BUY"
                                     else m1_row["close"] + _sp)
                trade.close_time  = m1_time
                trade.pnl_usd     = calc_pnl(trade, trade.close_price)
                trade.status      = "exit"
                closed = True

            # ── Cost-cut (idő-stop): N fő-tf gyertya után még veszteséges →
            # korai zárás a gyertyazáró áron (a teljes SL kivárása helyett).
            if (not closed and _cc_on
                    and (m1_time - trade.open_time) >= _cc_delta):
                # piaci zárás a SZEMBENI oldalon (BUY→bid, SELL→ask)
                _px = float(m1_row["close"] if trade.direction == "BUY"
                            else m1_row["close"] + _sp)
                if (_px < trade.open_price if trade.direction == "BUY"
                        else _px > trade.open_price):
                    trade.close_price = _px
                    trade.close_time  = m1_time
                    trade.pnl_usd     = calc_pnl(trade, _px)
                    trade.status      = "cut"
                    closed = True

            # ── Pozícióépítés (AUTO, off preset): risk-free trade + gyertyás jel
            # (az M15 zárás túllép a build_ref-en) → piramidális ráépítés (új láb),
            # az SL az új ÁTLAGÁRRA. A build_ref = a jel-gyertya záróra → gyertyánként
            # legfeljebb egyszer épít. Az m15_ptr ugyanaz az index, amit a belépő is
            # használ (nincs plusz look-ahead).
            if (not closed and _build_cfg is not None and trade.risk_free
                    and 0 <= m15_ptr < len(m15)
                    and len(trade.legs) <= _posbuild.HARD_MAX_ADDS):
                _bc_close = float(m15["close"].iloc[m15_ptr])
                _btrig = _build_cfg.get("trigger", _posbuild.TRIGGER_CANDLE)
                if _btrig == _posbuild.TRIGGER_CANDLE:
                    _fired = ((_bc_close > trade.build_ref) if trade.direction == "BUY"
                              else (_bc_close < trade.build_ref))
                else:
                    # R-alapú: R = a kezdeti SL-távolság árban (sl_points×pip); az n_add-adik
                    # (= len(legs)) R-szintet éri-e el a gyertyazáró. Determinisztikus.
                    _rp  = trade.sl_points * point_size
                    _lvl = _posbuild.r_level(trade.open_price, _rp, trade.direction,
                                             len(trade.legs), _build_cfg)
                    _fired = _lvl is not None and (
                        _bc_close >= _lvl if trade.direction == "BUY" else _bc_close <= _lvl)
                if _fired:
                    _last = min(l[1] for l in trade.legs) if trade.legs else trade.lot
                    _add  = _posbuild.next_lot(_last, _build_cfg["size_factor"],
                                               min_lot, lot_step)
                    if _add > 0:
                        # ráépítés piaci áron a BELÉPŐ oldalon (BUY→ask, SELL→bid)
                        _add_px = float(m1_row["close"] + _sp
                                        if trade.direction == "BUY" else m1_row["close"])
                        trade.legs.append((_add_px, _add))
                        trade.lot = round(sum(l[1] for l in trade.legs), 8)
                        # A stop a NETTÓ null pont: az átlagár + költség (jutalék,
                        # eddigi negatív swap, spread) a profit oldalra tolva. A nyers
                        # átlagár BRUTTÓ nulla → a csomag a költséggel mínuszban zárna.
                        # Él-paritás: core.mt5_connector.package_cost_buffer.
                        _cbuf = _costs.package_stop_buffer(
                            trade.lot, trade.direction, trade.open_time.timestamp(),
                            m1_time.timestamp(), pair_cfg, _sp)
                        trade.sl  = round(_posbuild.package_stop(
                            _posbuild.average_price(trade.legs), trade.direction,
                            0.0, 0.0, 0.0, cost_buffer=_cbuf)[0], 6)
                        trade.build_ref = _bc_close
                        if record_events:
                            # Ráépítés: új láb (piaci áron) + az SL az új NETTÓ null
                            # pontra, és a csomag TP nélkül fut (minden láb TP-je törölve).
                            trade.events.append(("BUILD_ADD", m1_time,
                                                 round(float(m1_row["close"]), 6),
                                                 round(trade.sl, 6), 0.0,
                                                 round(_add, 8), "build"))
                            trade.events.append(("TP_MODIFY", m1_time, 0.0, 0.0,
                                                 0.0, 0.0, "build_no_tp"))

            if closed:
                # A részleges zárás(ok)ból már realizált P&L hozzáadása a runner
                # (maradék lot) záró P&L-jéhez → teljes trade P&L.
                trade.pnl_usd += trade.booked_pnl
                # BRÓKER-KÖLTSÉG: jutalék (oda-vissza) + swap (éjfelenként). Eddig
                # csak a spread volt modellezve — a Felező/Pajzs runnere viszont épp
                # a hosszú tartással szedi össze a swapot, tehát a technika hozadéka
                # költség nélkül szisztematikusan optimista volt.
                trade.pnl_usd, trade.commission_usd, trade.swap_usd = _costs.apply(
                    trade.pnl_usd, trade.lot, trade.direction,
                    trade.open_time.timestamp(), m1_time.timestamp(), pair_cfg)
                # pnl_points (a trades CSV pont-oszlopa) — a runner mozgásából.
                # ⚠ A spreadet NEM vonjuk le újra: a BUY már ASK-on nyitott, a SELL
                # pedig ASK-on zár, tehát az árakban BENNE VAN. A korábbi levonás
                # kétszer fizettette meg, így a CSV pont-oszlopa nem stimmelt a
                # dollár-P&L-lel (a pénz mindig az árakból számolt, az helyes volt).
                if trade.direction == "BUY":
                    trade.pnl_points = (trade.close_price - trade.open_price) / trade.point_size
                else:
                    trade.pnl_points = (trade.open_price - trade.close_price) / trade.point_size
                if record_events:
                    trade.events.append(("CLOSE", m1_time,
                                         round(trade.close_price, 6), 0.0, 0.0,
                                         round(trade.lot, 8), trade.status))
                open_trades.remove(trade)
                result.trades.append(trade)
                balance += trade.pnl_usd
                daily_pnl[day_key] = daily_pnl.get(day_key, 0.0) + trade.pnl_usd
                result.balance_curve.append((m1_time, balance))

        # Slot számítás
        occupied = sum(1 for t in open_trades if not t.risk_free)
        free_slots = trading_cfg["max_open_slots"] - occupied

        # M1 belépési jelzés. A jelzés-ÁLLAPOTGÉP (bt_on_low_close) MINDEN M1-báron fut —
        # az arming a nyitott pozíció (foglalt slot) ÉS a tiltott óra alatt is megőrződik,
        # különben a szünet/pozíció után elveszne a felfegyverzés, és valós belépők
        # maradnának ki (pl. a délutáni trend). A tényleges BELÉPŐ-nyitást a szabad slot
        # ÉS az óra-szűrő kapuzza — élesben is így: a M1-figyelés folyamatos, csak a
        # végrehajtás gátolt.
        if prev_m1_row is not None:
            signal = strategy.bt_on_low_close(state, prev_m1_row, m1_row, params)

            if (signal != "NONE" and free_slots > 0 and not _off_hour
                    and not _limit_hit and m15_ptr < len(m15_times)):
                m15_row = m15.iloc[m15_ptr]

                # ── Végrehajtási kapuk (él-paritás) — a stratégia-jel ELŐTT ─────
                # Ugyanazok a kapuk, amik élesben is szűrnek — és ugyanazzal a
                # HATÁSSAL (blokkol / kockázatcsökkentés / ki), a közös
                # `core.gates.decide`-on keresztül. A MÉRÉS itt is irány-tudatos.
                _gate_risk = 1.0
                if _exec_gates:
                    _failed = {}
                    if _gt.active(_gate_eff, _gt.SPREAD):
                        _atr_e = m15_row.get("atr", float("nan"))
                        if _atr_e and not pd.isna(_atr_e):
                            _sp_e = _cspread_arr[i] if _cspread_arr is not None else float("nan")
                            if not (_sp_e > 0):
                                _sp_e = _spread_arr[i] if _spread_arr is not None else _spread_fallback
                            _failed[_gt.SPREAD] = not _spread_gate.spread_ok(
                                _sp_e / point_size, float(_atr_e), point_size, params,
                                pair_cfg.get("backtest_spread_points"))[0]
                    if _tf_eval is not None:
                        # A belépő M1-gyertya nyitó-idejére, a DÖNTÉSKOR ISMERT árral
                        # (ennek az M1-gyertyának a záróára) — a formálódó TF-gyertya
                        # záróára ez, nem a (még ismeretlen) végleges close.
                        _failed[_gt.TF_ALIGN] = not _tf_eval(
                            int(m1_time.timestamp()), float(m1_row["close"]), signal)
                    if _mkt_series is not None:
                        _cat = _mkt_series.get(m15_times[m15_ptr])
                        _failed[_gt.MARKET] = bool(_cat) and _cat in _mkt_adverse
                    if _mom_series is not None:
                        from core import momentum as _momx
                        _failed[_gt.MOMENTUM] = _momx.failed(
                            _mom_series.get(m15_times[m15_ptr], float("nan")),
                            signal, _mom_mode, _mom_cfg)
                    _dec = _gt.decide(_failed, _gate_eff)
                    if _dec["blocked"]:
                        prev_m1_row = m1_row
                        continue
                    _gate_risk = _dec["risk_factor"]

                # A stratégia adja a pozíciótervet (SL/TP + saját szűrők); None → kihagyás
                plan = strategy.bt_entry(m15_row, params, point_size)

                if plan is not None:
                    sl_points, tp_points = plan
                    # SL-módszer: `swing20` → az utolsó N M1 gyertya swingjéből (ATR
                    # helyett): BUY = legalacsonyabb LOW − spread, SELL = legmagasabb
                    # HIGH + spread; a TP marad tp_rr_ratio × SL-táv. (`atr` = a régi.)
                    # Az alapértelmezést a STRATÉGIA adja (lásd Strategy.default_sl_method).
                    if params.get("sl_method", strategy.default_sl_method) == "swing20":
                        _nb = int(params.get("sl_swing_bars", 20) or 20)
                        _lo = m1["low"].iloc[max(0, i - _nb + 1):i + 1].to_numpy()
                        _hi = m1["high"].iloc[max(0, i - _nb + 1):i + 1].to_numpy()
                        _sw = calc_swing_sl_tp_points(float(m1_row["close"]), signal,
                                                    _lo, _hi, params, point_size, spread_points)
                        if _sw is None:
                            prev_m1_row = m1_row
                            continue
                        sl_points, tp_points = _sw

                    # ── KÖLTSÉG/KOCKÁZAT kapu — a TERV ISMERETÉBEN ────────────
                    # Ez az EGYETLEN kapu, ami a belépő-terv UTÁN dől el: a
                    # mérőszáma a spread és a TERVEZETT stop viszonya, tehát
                    # előbb tudni kell, mekkora stopot szán a stratégia.
                    if _exec_gates and _gt.active(_gate_eff, _gt.COST):
                        from core import cost_gate as _cgx
                        _csp = _cspread_arr[i] if _cspread_arr is not None else float("nan")
                        if not (_csp > 0):
                            _csp = _sp
                        _cdec = _gt.decide(
                            {_gt.COST: _cgx.failed(sl_points, tp_points,
                                                   _csp / point_size, _cost_cap)},
                            _gate_eff)
                        if _cdec["blocked"]:
                            prev_m1_row = m1_row
                            continue
                        _gate_risk = min(_gate_risk, _cdec["risk_factor"])

                    # KAPU-hatás: `kockázatcsökkentés` → kisebb mérettel lépünk be
                    # (ugyanaz a mechanizmus, mint a Risky `cautious`-é: az
                    # `account_risk_pct` szorzója).
                    _size_cfg = (sizing_cfg if _gate_risk >= 1.0 else
                                 {**sizing_cfg,
                                  "account_risk_pct": sizing_cfg["account_risk_pct"] * _gate_risk})
                    eff_slots = calc_effective_slots(balance, sl_points, pair_cfg, _size_cfg)
                    lot = calc_lot(balance, sl_points, pair_cfg, _size_cfg, eff_slots)

                    # A belépő a gyertya ZÁRÁSÁN → a bar UTOLSÓ tickjének spreadje
                    # (`close_spread`) a pontos; tartalék az átlag (_sp).
                    _esp = _cspread_arr[i] if _cspread_arr is not None else float("nan")
                    if not (_esp > 0):
                        _esp = _sp
                    open_price = m1_row["close"]
                    if signal == "BUY":
                        open_price += _esp          # BUY → ASK-on lép be
                        sl_price = open_price - points_to_price(sl_points, point_size)
                        tp_price = open_price + points_to_price(tp_points, point_size)
                    else:  # SELL
                        sl_price = open_price + points_to_price(sl_points, point_size)
                        tp_price = open_price - points_to_price(tp_points, point_size)

                    risk_usd = lot * sl_points * pv1_point
                    trade = Trade(
                        symbol=symbol,
                        direction=signal,
                        open_time=m1_time,
                        open_price=open_price,
                        sl=sl_price,
                        tp=tp_price,
                        lot=lot,
                        point_size=point_size,
                        pv1_point=pv1_point,
                        sl_points=sl_points,
                        # a belépéskori ATR (ÁRban) — ehhez mér a trailing
                        entry_atr=(float(m15_row.get("atr", 0.0) or 0.0)
                                   if not pd.isna(m15_row.get("atr", float("nan"))) else 0.0),
                        entry_balance=balance,
                        risk_usd=risk_usd,
                        risk_pct=risk_usd / balance * 100 if balance > 0 else 0,
                    )
                    trade.legs = [(open_price, lot)]     # 1. láb; a build a listát bővíti
                    trade.build_ref = open_price         # az első ráépítés innen figyel
                    if _bigmove_at is not None:
                        # Pajzs↔Fibo auto: BELÉPÉSKOR dől el — nagy mozgásnál Fibo
                        # (hagyjuk futni, később stop), különben Pajzs (alaphelyzet).
                        trade.rr_preset_eff = (_rrm.PRESET_FIBO if _bigmove_at(m15_ptr)
                                               else _rrm.PRESET_SHIELD)
                    open_trades.append(trade)
                    if record_events:
                        trade.events.append(("OPEN", m1_time, round(open_price, 6),
                                             round(sl_price, 6), round(tp_price, 6),
                                             round(lot, 8), ""))

        prev_m1_row = m1_row

    # Nyitva maradt pozíciók hozzáadása (nincs zárva)
    for trade in open_trades:
        result.trades.append(trade)

    # Záró progressz (100%)
    if progress_callback is not None and total_m1:
        _report(total_m1 - 1, m1.index[-1])

    return result


# ---------------------------------------------------------------------------
# Futtatás: összes aktív pár
# ---------------------------------------------------------------------------

def run_backtest(cfg: dict, params: Optional[dict] = None, test_mode: bool = False,
                 save_results: bool = True) -> list[dict]:
    initial_balance = cfg.get("ml", {}).get("starting_balance_eur", 1000.0)
    trading_cfg     = cfg["trading"]
    test_start      = cfg.get("optimizer", {}).get("test_start_date") if test_mode else None
    strategy        = get_strategy(cfg)
    set_active_strategy(strategy.name)     # stratégia-hatókörű params-tárolás

    _use_base_params = params is None
    if params is None:
        params = strategy.base_params(cfg)

    pairs = {s: p for s, p in cfg["pairs"].items() if isinstance(p, dict) and p.get("enabled", False)}
    summaries  = []
    all_trades: list[Trade] = []

    risky_mode.load()   # kézi risky állapot a data/risky_mode.json-ból

    for symbol, pair_cfg in pairs.items():
        df_m15, df_m1 = load_data(symbol)
        if df_m15 is None:
            continue

        # BE/trailing/atr_period/spread-kapu MÁR NEM stratégia-paraméter — a
        # közös, instrumentum-szintű execution config felülírje az alapértéket
        # (csak akkor, ha a hívó NEM adott explicit, kész paramétert).
        sym_params = ({**params, **load_execution_params(symbol, cfg)}
                      if _use_base_params else params)
        result = run_pair(
            symbol, df_m15, df_m1,
            sym_params, pair_cfg, trading_cfg,
            initial_balance, test_start, strategy=strategy,
            risky=risky_mode.is_risky(symbol),
        )
        summary = result.summary(initial_balance)
        summaries.append(summary)
        all_trades.extend(result.closed)
        log.info(
            "%s | Kötések: %d | Win: %.0f%% | P&L: %.2f$ | MaxDD: %.1f%%",
            symbol,
            summary.get("trades", 0),
            summary.get("win_rate", 0) * 100,
            summary.get("total_pnl", 0),
            summary.get("max_drawdown", 0) * 100,
        )

    if save_results and all_trades:
        _save_backtest_results(all_trades, summaries, initial_balance, test_start)

    return summaries


def _save_backtest_results(trades: list, summaries: list[dict],
                           initial_balance: float, test_start: Optional[str]):
    """CSV + TXT kimenet mentése a data/backtest_results/ könyvtárba."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts_str = datetime.now().strftime("%Y%m%d_%H%M")

    # ── 1) trades CSV ────────────────────────────────────────────────────────
    trades_csv = RESULTS_DIR / f"trades_{ts_str}.csv"
    with open(trades_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "direction", "open_time", "close_time", "status",
                    "open_price", "close_price", "sl", "tp", "lot",
                    "sl_points", "risk_usd", "risk_pct", "pnl_points", "pnl_usd",
                    "commission_usd", "swap_usd"])
        for t in sorted(trades, key=lambda x: x.open_time):
            w.writerow([
                t.symbol, t.direction,
                t.open_time, t.close_time, t.status,
                round(t.open_price, 5), round(t.close_price or 0, 5),
                round(t.sl, 5), round(t.tp, 5), t.lot,
                round(t.sl_points, 1),
                round(t.risk_usd, 2), round(t.risk_pct, 3),
                round(t.pnl_points, 2), round(t.pnl_usd, 2),
                round(t.commission_usd, 2), round(t.swap_usd, 2),
            ])

    # ── 2) daily CSV ─────────────────────────────────────────────────────────
    daily_pnl: dict = defaultdict(float)
    for t in trades:
        if t.close_time is not None:
            daily_pnl[t.close_time.date()] += t.pnl_usd

    daily_csv = RESULTS_DIR / f"daily_{ts_str}.csv"
    running = initial_balance
    with open(daily_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "pnl_usd", "balance", "ret_pct"])
        for date in sorted(daily_pnl):
            pv = daily_pnl[date]
            running += pv
            pct = pv / (running - pv) * 100 if (running - pv) > 0 else 0
            w.writerow([date, round(pv, 2), round(running, 2), round(pct, 4)])

    # ── 3) summary TXT ───────────────────────────────────────────────────────
    total_pnl    = sum(t.pnl_usd for t in trades)
    n_trades     = len(trades)
    n_wins       = sum(1 for t in trades if t.pnl_usd > 0)
    n_loss       = sum(1 for t in trades if t.pnl_usd <= 0)
    n_tp         = sum(1 for t in trades if t.status == "tp")
    n_sl         = sum(1 for t in trades if t.status == "sl")
    n_be         = sum(1 for t in trades if t.status == "be_trail")
    avg_w        = sum(t.pnl_usd for t in trades if t.pnl_usd > 0) / max(n_wins, 1)
    avg_l        = sum(t.pnl_usd for t in trades if t.pnl_usd < 0) / max(n_loss, 1)
    win_sum      = sum(t.pnl_usd for t in trades if t.pnl_usd > 0)
    loss_sum     = sum(t.pnl_usd for t in trades if t.pnl_usd < 0)
    pf           = abs(win_sum / loss_sum) if loss_sum != 0 else float("inf")
    final_bal    = initial_balance + total_pnl
    ret_pct      = total_pnl / initial_balance * 100

    # max drawdown portfólió szinten
    eq = initial_balance
    peak = eq; mdd = 0.0
    for t in sorted(trades, key=lambda x: x.close_time or x.open_time):
        eq += t.pnl_usd
        if eq > peak: peak = eq
        dd = (peak - eq) / peak * 100
        if dd > mdd: mdd = dd

    # havi bontás
    monthly_pnl: dict = defaultdict(float)
    monthly_trades: dict = defaultdict(int)
    for t in trades:
        if t.close_time:
            m = t.close_time.strftime("%Y-%m")
            monthly_pnl[m]    += t.pnl_usd
            monthly_trades[m] += 1

    # páronkénti összesítő
    by_sym: dict = defaultdict(list)
    for t in trades:
        by_sym[t.symbol].append(t)

    summary_txt = RESULTS_DIR / f"summary_{ts_str}.txt"
    with open(summary_txt, "w", encoding="utf-8") as f:
        f.write(f"BACKTEST ÖSSZESÍTŐ  —  {datetime.now():%Y-%m-%d %H:%M}\n")
        period = f"{min(daily_pnl):%Y-%m-%d} → {max(daily_pnl):%Y-%m-%d}" if daily_pnl else "—"
        mode   = f"TEST (out-of-sample, {test_start}-tól)" if test_start else "TELJES historikus"
        f.write(f"Mód       : {mode}\n")
        f.write(f"Időszak   : {period}  ({len(daily_pnl)} kereskedési nap)\n")
        f.write(f"Párok     : {len(by_sym)} aktív\n")
        f.write("=" * 65 + "\n")
        f.write(f"Trade-ek  : {n_trades}  ({n_trades/max(len(daily_pnl),1):.1f}/nap)\n")
        f.write(f"Exit típus: TP={n_tp}  SL={n_sl}  BE/Trail={n_be}\n")
        f.write(f"Nyerő     : {n_wins} ({n_wins/max(n_trades,1):.0%})  |  Vesztes: {n_loss} ({n_loss/max(n_trades,1):.0%})\n")
        f.write(f"Átl nyerő : ${avg_w:+.2f}   Átl vesztes: ${avg_l:+.2f}   Arány: {abs(avg_w/avg_l) if avg_l else 0:.2f}x\n")
        f.write(f"Profit F. : {pf:.2f}\n")
        f.write(f"Total P&L : ${total_pnl:+.2f}  ({ret_pct:+.1f}%)\n")
        # KÖLTSÉG: az eredmény nettó-e? Ha egyik páron sincs jutalék/swap beállítva,
        # ezt KI KELL írni — különben egy költségmentes szám valós eredménynek látszik.
        _com = sum(t.commission_usd for t in trades)
        _swp = sum(t.swap_usd for t in trades)
        if _com or _swp:
            f.write(f"Költség   : jutalék ${_com:.2f}  swap ${_swp:+.2f}  "
                    f"(a P&L NETTÓ)\n")
        else:
            f.write("Költség   : ⚠ NINCS modellezve (csak spread) — a P&L BRUTTÓ, "
                    "a valóságnál kedvezőbb.\n"
                    "            Kitöltés: python tools/refresh_costs.py --write\n")
        f.write(f"Kezdő     : ${initial_balance:.0f}   Záró: ${final_bal:.0f}\n")
        f.write(f"Max DD    : {mdd:.2f}%\n")
        dp = sum(1 for v in daily_pnl.values() if v >= initial_balance * 0.01)
        f.write(f"1% napok  : {dp}/{len(daily_pnl)} ({dp/max(len(daily_pnl),1):.0%})\n")
        f.write("\nPÁRONKÉNT:\n")
        f.write(f"  {'Pár':<10} {'Trade':>6} {'Nyerő%':>7} {'P&L$':>9} {'MaxDD%':>8}\n")
        for sym, tt in sorted(by_sym.items(), key=lambda x: -sum(t.pnl_usd for t in x[1])):
            nw  = sum(1 for t in tt if t.pnl_usd > 0)
            ps  = sum(t.pnl_usd for t in tt)
            s   = next((x for x in summaries if x.get("symbol") == sym), {})
            dd  = s.get("max_drawdown", 0) * 100
            f.write(f"  {sym:<10} {len(tt):6d} {nw/len(tt):7.0%} {ps:+9.2f} {dd:8.1f}%\n")
        f.write("\nHAVI BONTÁS:\n")
        f.write(f"  {'Hónap':<10} {'Trade':>6} {'P&L$':>9} {'Ret%':>7}  chart\n")
        running2 = initial_balance
        for m in sorted(monthly_pnl):
            pv  = monthly_pnl[m]
            pct = pv / running2 * 100 if running2 > 0 else 0
            running2 += pv
            bar = "+" * min(int(abs(pct) * 3), 20) if pv >= 0 else "-" * min(int(abs(pct) * 3), 20)
            f.write(f"  {m:<10} {monthly_trades[m]:6d} {pv:+9.2f} {pct:+7.2f}%  {bar}\n")
        f.write("\nNAPI BONTÁS:\n")
        f.write(f"  {'Dátum':<12} {'P&L$':>9} {'Egyenleg':>10} {'Ret%':>7}  chart\n")
        running3 = initial_balance
        for date in sorted(daily_pnl):
            pv  = daily_pnl[date]
            prev = running3
            running3 += pv
            pct = pv / prev * 100 if prev > 0 else 0
            bar = "+" * min(int(abs(pct) * 8), 22) if pv >= 0 else "-" * min(int(abs(pct) * 8), 22)
            tag = " TARGET" if pct >= 1.0 else (" STOP" if pct < -1.0 else "")
            f.write(f"  {str(date):<12} {pv:+9.2f} ${running3:9.0f} {pct:+7.2f}%  {bar}{tag}\n")

    log.info("=" * 65)
    log.info("ÖSSZESÍTETT | Kötések: %d | Win: %.0f%% | P&L: %.2f$ | MaxDD: %.1f%% | PF: %.2f",
             n_trades, n_wins / max(n_trades, 1) * 100, total_pnl, mdd, pf)
    log.info("Eredmények mentve -> %s", RESULTS_DIR)
    log.info("  trades_%s.csv", ts_str)
    log.info("  daily_%s.csv",  ts_str)
    log.info("  summary_%s.txt", ts_str)


# ---------------------------------------------------------------------------
# Portfolio Backtest — közös tőke, közös slot rendszer, kronológiai szimuláció
# ---------------------------------------------------------------------------

from core.params_store import (
    PARAMS_DIR, params_file, set_active_strategy, migrate_flat_layout,
)
from core.execution_params import load_execution_params


def _advance_m15_state(pd_info: dict, m1_time: pd.Timestamp, strategy) -> None:
    """M15 pointer előrehaladása és állapot frissítése (egy pár adatain).

    Minden ÚJONNAN ZÁRT M15 gyertyát EGYSZER dolgozunk fel, a LEZÁRT bart használva
    (nem a formálódót) — különben look-ahead ÉS az M1 arming ismételt újraszámítása
    minden M1-ticknél → valós belépők maradnának ki. (Ugyanaz a fix, mint a run_pair.)"""
    m15_times = pd_info["m15_times"]
    m15_df    = pd_info["m15"]
    params    = pd_info["params"]
    delta     = pd_info["m15_delta"]

    while (pd_info["m15_ptr"] + 1 < len(m15_times)
           and m15_times[pd_info["m15_ptr"] + 1] + delta <= m1_time):
        pd_info["m15_ptr"] += 1
        pd_info["state"] = strategy.bt_on_high_close(
            pd_info["state"], m15_df.iloc[pd_info["m15_ptr"]], params)


def run_portfolio_backtest(
    cfg: dict,
    symbols: list,
    date_from: str,
    date_to: str,
    initial_balance: Optional[float] = None,
    progress_callback=None,   # fn(date_str, balance, n_open, n_closed, pct_done)
    stop_flag=None,           # threading.Event — ha set(), leállítja
    rr: "dict | None" = None, # globális kockázatcsökkentő preset (mind a párra); None = a per-pár auto-risky
    strategy_name: "str | None" = None,  # melyik stratégián fut (None = a config elsődlegese)
    max_slots: "int | None" = None,      # egyszerre nyitott pozíciók száma (None = trading.max_open_slots)
    build: bool = False,                 # pozícióépítés (piramidális ráépítés) bekapcsolva?
    exec_gates: bool = False,            # él-paritású végrehajtási kapuk (spread + TF-együttállás)
) -> dict:
    """
    Portfólió szintű backtest: az összes szimbólum közös tőkén,
    kronológiai M1 szimulációval fut.

    Optimalizált params betöltése: data/optimized_params/<strategy>/<SYMBOL>.json

    rr: ha adott (pl. {"preset":"shield",...}), MINDEN pár erre a preset-re fut →
    így a GUI-ból összevethetők a technikák. None → a jelenlegi per-pár auto-risky
    (gyenge minősítés → risky).
    strategy_name: a portfólió ezen a stratégián fut (a párok params-fájljai is
    ebből az almappából jönnek). None → a config elsődleges stratégiája.
    max_slots: az egyidejűleg nyitott (nem risk-free) pozíciók max. száma. None →
    a trading.max_open_slots.
    build: ha True, a risk-free runnerek piramidálisan ráépítenek (mint a run_pair
    Auto-építése) — a párok build_state configjával, alapból AUTO/gyertyás.
    """
    if initial_balance is None:
        initial_balance = float(cfg.get("ml", {}).get("starting_balance_eur", 1000.0))
    trading_cfg = cfg["trading"]
    spread_default = 1.5
    strategy = get_strategy_by_name(strategy_name) if strategy_name else get_strategy(cfg)
    set_active_strategy(strategy.name)     # stratégia-hatókörű params-tárolás
    migrate_flat_layout(strategy.name)
    tf_hi = strategy.timeframes()[0].label
    tf_lo = strategy.timeframes()[1].label

    # ── Végrehajtási kapuk (él-paritás, opcionális) — UGYANAZ, mint a run_pair-ben ──
    from core import spread_gate as _spread_gate
    from core import gates as _gt
    _exec_gates = bool(exec_gates)

    # Risky mód forrásai: (1) kézi kapcsoló (data/risky_mode.json) + (2) auto:
    # a Közepes/Gyenge/Rossz minősítésű pár CSAK risky módban futhat (mint élőben).
    # (3) per-pár kockázatcsökkentő preset (data/risk_mode.json) — ha 'rr' (globális)
    # nincs megadva ("Auto"), a pár a saját választott presetjén fut.
    from core import rr_state as _rr_state
    from core import risk_reduction as _rrm2
    risky_mode.load()
    _rr_state.load()
    auto_risky = bool(trading_cfg.get("auto_risky_weak", True))

    def _pair_auto_rr(sym: str, weak_risky: bool) -> dict:
        spec = _rr_state.spec_for(sym)                     # per-pár preset + runner + cautious
        if spec.get("preset") == _rrm2.PRESET_OFF and weak_risky:  # gyenge → risky
            spec = {**spec, "preset": _rrm2.PRESET_RISKY, "cautious": True}
        return spec

    # Pozícióépítés: ha bekapcsolva, a párok build-configját használjuk (mode≠Ki),
    # egyébként alapból AUTO/gyertyás — így a portfólió-BT-ben is kísérletezhető.
    from core import build_state as _bstate
    from core import position_build as _pb
    def _pair_build_cfg(sym: str):
        if not build:
            return None
        bc = _bstate.get_config(sym) or {}
        if bc.get("mode", _pb.MODE_OFF) == _pb.MODE_OFF:
            bc = {**bc, "mode": _pb.MODE_AUTO}   # bekapcsolva → alapból AUTO
        return {**_pb.default_config(), **bc}

    # ── Per-pár optimalizált paraméterek + risky állapot betöltése ─────────
    pair_params: dict = {}
    pair_risky:  dict = {}
    for sym in symbols:
        f = params_file(sym, strategy.name)
        if f.exists():
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            # BE/trailing/atr_period/spread-kapu MÁR NEM stratégia-paraméter — a
            # közös, instrumentum-szintű execution config felülírja az esetleges
            # elavult másolatot a régi optimalizált json-ban.
            pair_params[sym] = {**data.get("params", {}), **load_execution_params(sym, cfg)}
            gtxt, _, _ = strategy.grade(data.get("test_summary", {}), cfg)
            weak = 1 <= strategy.grade_rank(gtxt) <= 3   # Közepes/Gyenge/Rossz
            pair_risky[sym] = risky_mode.is_risky(sym) or (auto_risky and weak)
            if pair_risky[sym]:
                log.info("Portfolio BT: %s — RISKY mód (minősítés: %s%s)", sym, gtxt,
                         ", kézi" if risky_mode.is_risky(sym) else "")
        else:
            log.warning("Portfolio BT: %s — nincs optimalizált params, kihagyva.", sym)

    if not pair_params:
        return {"error": "Nincs optimalizált paraméter egyetlen szimbólumhoz sem.",
                "trades": [], "daily_pnl": {}, "final_balance": initial_balance}

    # ── Adat betöltés és indikátor számítás ──────────────────────────────
    pair_data: dict = {}
    ts_from = pd.Timestamp(date_from)
    ts_to   = pd.Timestamp(date_to)
    # UTC-aware indexhez UTC-aware timestamp kell
    _sample_df = next(iter(pair_data.values()), None) if False else None  # placeholder
    _tz_needed = True  # mindig UTC-ra normalizálunk biztonságból
    if ts_from.tzinfo is None:
        ts_from = ts_from.tz_localize("UTC")
    if ts_to.tzinfo is None:
        ts_to = ts_to.tz_localize("UTC")

    for sym, params in pair_params.items():
        if sym not in cfg["pairs"] or not isinstance(cfg["pairs"][sym], dict):
            continue
        df_m15, df_m1 = load_data(sym)
        if df_m15 is None:
            log.warning("Portfolio BT: %s — nincs adat, kihagyva.", sym)
            continue

        # Pár-azonosító injektálás a stratégia-hookoknak (mint a run_pair-ben).
        _pcfg = cfg["pairs"][sym]
        params = {**params, "symbol": sym, "point_size": _pcfg["point_size"]}
        params.setdefault("sess_start", _pcfg.get("sess_start", 0))
        params.setdefault("sess_end",   _pcfg.get("sess_end", 24))

        m15, m1 = strategy.bt_indicators(df_m15, df_m1, params)

        m15 = m15.iloc[strategy.bt_warmup(params, tf_hi):].copy()
        m1  = m1.iloc[strategy.bt_warmup(params, tf_lo):].copy()

        # Dátum szűrés
        m15 = m15[(m15.index >= ts_from) & (m15.index <= ts_to)]
        m1  = m1[(m1.index  >= ts_from) & (m1.index  <= ts_to)]

        if len(m1) < 100:
            log.warning("Portfolio BT: %s — túl kevés adat a megadott időszakban.", sym)
            continue

        # A kockázatcsökkentő spec: globális rr (mind a párra), különben a
        # per-pár választott preset (rr_state) + gyenge-minősítés auto-risky.
        _rr_pair = rr if rr else _pair_auto_rr(sym, pair_risky.get(sym, False))
        pair_data[sym] = {
            "m15":       m15,
            "m1":        m1,
            "m15_times": m15.index.tolist(),
            "m15_ptr":   0,
            "m15_delta": pd.Timedelta(minutes=strategy.timeframes()[0].minutes),
            "params":    params,
            "pair_cfg":  cfg["pairs"][sym],
            "risky":     pair_risky.get(sym, False),
            "rr":        _rr_pair,
            # Kiszállási-jel kiértékelő (None, ha a runner != exit) — a runner
            # zárásához, ugyanaz a logika, mint a run_pair-ben és az élő motorban.
            "exit_at":   _build_exit_evaluator(m15, _rr_pair),
            # Pajzs↔Fibo auto kiértékelő (None, ha a preset nem shield_fibo).
            "bigmove_at": _build_bigmove_evaluator(m15, _rr_pair),
            "build_cfg": _pair_build_cfg(sym),   # pozícióépítés (None, ha kikapcsolva)
            "state":     strategy.bt_new_state(sym),
            "prev_row":  None,
            # TF-együttállás kapu kiértékelő (None, ha nincs bekapcsolva erre a párra/
            # stratégiára) — a TELJES df_m1-ből, hogy a magasabb idősíkok SMA-ja warmupolt.
            "tf_eval":   (_build_tf_align_evaluator(cfg, sym, strategy.name, df_m1)
                          if _exec_gates else None),
            # A kapuk HATÁSA per (pár × stratégia) — a `core.gates.decide` bemenete.
            "gate_eff":  (_gt.effects_for(cfg, sym, strategy.name) if _exec_gates
                          else {k: _gt.EFFECT_NONE for k in _gt.KEYS}),
            # Piac-kapu: per-gyertya besorolás (EGYSZER, mint a tf_eval — nem
            # paraméter-függő). None, ha a kapu ki van kapcsolva/nincs osztályozó.
            "mkt_series": _pair_market_series(cfg, sym, strategy.name, m15,
                                              _exec_gates),
            "mkt_adverse": _gt.market_adverse(cfg, sym),
            # Lendulet-kapu: per-gyertya fordulat (EGYSZER, mint a mkt_series),
            # a dontesi idopontokra, look-ahead nelkul.
            **_pair_momentum(cfg, sym, strategy.name, m15, df_m1, _exec_gates),
        }
        log.info("Portfolio BT: %s betöltve — M15=%d M1=%d bar", sym, len(m15), len(m1))

    if not pair_data:
        return {"error": "Nincs elegendő adat a megadott időszakban.",
                "trades": [], "daily_pnl": {}, "final_balance": initial_balance}

    # ── Egységes M1 idővonal ──────────────────────────────────────────────
    all_times: set = set()
    for info in pair_data.values():
        all_times.update(info["m1"].index.tolist())
    all_times_sorted = sorted(all_times)
    n_total = len(all_times_sorted)
    log.info("Portfolio BT: %d pár | %d M1 bar | tőke: $%.0f",
             len(pair_data), n_total, initial_balance)

    # ── Szimuláció állapot ────────────────────────────────────────────────
    balance        = initial_balance
    open_trades:   dict  = {}   # sym → Trade (max 1 pozíció/szimbólum)
    closed_trades: list  = []
    daily_pnl:     dict  = {}
    equity_curve:  list  = []   # (date_str, balance) pontok a görbe rajzához
    max_slots      = int(max_slots) if max_slots else trading_cfg["max_open_slots"]

    last_eq_date = ""

    for bar_idx, m1_time in enumerate(all_times_sorted):
        # Stop flag
        if stop_flag and stop_flag.is_set():
            log.info("Portfolio BT: leállítva a felhasználó által.")
            break

        day_key  = str(m1_time.date())
        date_str = day_key

        # Progress callback (~200 alkalommal összesen)
        if bar_idx % max(1, n_total // 200) == 0 or bar_idx == n_total - 1:
            pct = (bar_idx + 1) / n_total * 100
            if progress_callback:
                progress_callback(date_str, balance,
                                  len(open_trades), len(closed_trades), pct)
            # Equity curve pont napváltáskor
            if date_str != last_eq_date:
                equity_curve.append((date_str, balance))
                last_eq_date = date_str

        # ── 1. M15 állapot frissítése minden párhoz ───────────────────────
        for info in pair_data.values():
            _advance_m15_state(info, m1_time, strategy)

        # ── 2. Nyitott pozíciók kezelése ──────────────────────────────────
        for sym in list(open_trades.keys()):
            trade  = open_trades[sym]
            info   = pair_data[sym]
            m1_df  = info["m1"]
            params = info["params"]

            if m1_time not in m1_df.index:
                continue
            row      = m1_df.loc[m1_time]
            point_size = trade.point_size
            sp       = info["pair_cfg"].get("backtest_spread_points", spread_default)
            # ⚠ A gyertya BID; az ASK = BID + spread. A kilépés a SZEMBENI oldalon
            # történik (BUY→bid, SELL→ask) — ugyanaz a mechanika, mint a
            # `run_pair`-ben. Enélkül a SELL bid-en NYITOTT és bid-en ZÁRT, tehát
            # NULLA spreadet fizetett, míg a BUY egy teljeset: a portfólió-motor
            # rendszeresen felülbecsülte a short-oldalt.
            _psp = row.get("avg_spread", float("nan"))
            if not (_psp > 0):
                _psp = points_to_price(sp, point_size)
            _hi_x = float(row["high"]) + _psp     # SELL ezen zár (ask)
            _lo_x = float(row["low"]) + _psp
            rr_spec  = info.get("rr") or _rr_spec(None, info.get("risky", False), sym)
            _pc      = info["pair_cfg"]
            _minlot  = _pc.get("min_lot", 0.01)
            _lotstep = _pc.get("lot_step", 0.01)
            closed   = False

            if trade.direction == "BUY":
                # Épített csomagnál NINCS TP (mint a run_pair-ben / élesben)
                if not trade.built and row["high"] >= trade.tp:
                    trade.close_price = trade.tp
                    trade.close_time  = m1_time
                    trade.pnl_usd     = calc_pnl(trade, trade.tp)
                    trade.pnl_points    = (trade.tp - trade.open_price) / point_size
                    trade.status      = "tp";  closed = True
                elif row["low"] <= trade.sl:
                    trade.close_price = trade.sl
                    trade.close_time  = m1_time
                    trade.pnl_usd     = calc_pnl(trade, trade.sl)
                    trade.pnl_points    = (trade.sl - trade.open_price) / point_size
                    trade.status      = "sl";  closed = True
                else:
                    _manage_position(trade, row["high"], row["low"],
                                     point_size, _minlot, _lotstep, rr_spec)

            else:  # SELL — az ASK-sorozaton (bid + spread)
                if not trade.built and _lo_x <= trade.tp:
                    trade.close_price = trade.tp
                    trade.close_time  = m1_time
                    trade.pnl_usd     = calc_pnl(trade, trade.tp)
                    trade.pnl_points    = (trade.open_price - trade.tp) / point_size
                    trade.status      = "tp";  closed = True
                elif _hi_x >= trade.sl:
                    trade.close_price = trade.sl
                    trade.close_time  = m1_time
                    trade.pnl_usd     = calc_pnl(trade, trade.sl)
                    trade.pnl_points    = (trade.open_price - trade.sl) / point_size
                    trade.status      = "sl";  closed = True
                else:
                    # A BE/trailing is a KILÉPÉSI (ask) oldalon mér
                    _manage_position(trade, _hi_x, _lo_x,
                                     point_size, _minlot, _lotstep, rr_spec)

            # Runner KISZÁLLÁSI JELRE zárása (mint a run_pair-ben): a részleges zárás
            # UTÁN, a jel az info["m15_ptr"] gyertyán, a gyertyazáró áron.
            if (not closed and info.get("exit_at") is not None and trade.reduced
                    and trade.runner_mode == _rrm2.RUNNER_EXIT
                    and info["exit_at"](info["m15_ptr"], trade.direction)):
                trade.close_price = row["close"]
                trade.close_time  = m1_time
                trade.pnl_usd     = calc_pnl(trade, trade.close_price)
                trade.pnl_points    = ((trade.close_price - trade.open_price)
                                     if trade.direction == "BUY"
                                     else (trade.open_price - trade.close_price)) / point_size
                trade.status      = "exit"
                closed = True

            # Cost-cut (idő-stop, mint a run_pair-ben): N fő-tf gyertya után még
            # veszteséges → korai zárás a gyertyazáró áron. (A portfólió-motor
            # M15-centrikus — lásd m15_ptr —, ezért itt fixen 15 perc/gyertya.)
            if (not closed and rr_spec.get("cost_cut")
                    and (m1_time - trade.open_time) >= pd.Timedelta(
                        minutes=15 * int(rr_spec.get("cost_cut_bars", 12)))):
                _px = float(row["close"])
                if (_px < trade.open_price if trade.direction == "BUY"
                        else _px > trade.open_price):
                    trade.close_price = _px
                    trade.close_time  = m1_time
                    trade.pnl_usd     = calc_pnl(trade, _px)
                    trade.pnl_points    = ((_px - trade.open_price)
                                         if trade.direction == "BUY"
                                         else (trade.open_price - _px)) / point_size - sp
                    trade.status      = "cut"
                    closed = True

            # ── Pozícióépítés (ha bekapcsolva): risk-free runner + gyertyás/R jel
            # → piramidális ráépítés, az SL az új ÁTLAGÁRRA (mint a run_pair-ben).
            # A build_ref = a jel-gyertya záróra → gyertyánként legfeljebb egyszer.
            _bcfg = info.get("build_cfg")
            if (not closed and _bcfg is not None and trade.risk_free
                    and 0 <= info["m15_ptr"] < len(info["m15"])
                    and len(trade.legs) <= _pb.HARD_MAX_ADDS):
                _m15   = info["m15"]
                _bc_cl = float(_m15["close"].iloc[info["m15_ptr"]])
                _btrig = _bcfg.get("trigger", _pb.TRIGGER_CANDLE)
                if _btrig == _pb.TRIGGER_CANDLE:
                    _fired = ((_bc_cl > trade.build_ref) if trade.direction == "BUY"
                              else (_bc_cl < trade.build_ref))
                else:
                    _rp  = trade.sl_points * point_size
                    _lvl = _pb.r_level(trade.open_price, _rp, trade.direction,
                                       len(trade.legs), _bcfg)
                    _fired = _lvl is not None and (
                        _bc_cl >= _lvl if trade.direction == "BUY" else _bc_cl <= _lvl)
                if _fired:
                    _last = min(l[1] for l in trade.legs) if trade.legs else trade.lot
                    _add  = _pb.next_lot(_last, _bcfg["size_factor"], _minlot, _lotstep)
                    if _add > 0:
                        trade.legs.append((float(row["close"]), _add))
                        trade.lot = round(sum(l[1] for l in trade.legs), 8)
                        # NETTÓ null pont (nem a nyers átlagár) — lásd a run_pair
                        # ágát és a core.mt5_connector.package_cost_buffer-t.
                        # Itt az `sp` PONTBAN van (a run_pair-ben árban), ezért ×point_size.
                        _cbuf = _costs.package_stop_buffer(
                            trade.lot, trade.direction, trade.open_time.timestamp(),
                            m1_time.timestamp(), _pc, sp * point_size)
                        trade.sl  = round(_pb.package_stop(
                            _pb.average_price(trade.legs), trade.direction,
                            0.0, 0.0, 0.0, cost_buffer=_cbuf)[0], 6)
                        trade.build_ref = _bc_cl

            if closed:
                trade.pnl_usd += trade.booked_pnl   # a részleges zárás(ok) realizált P&L-je
                # Bróker-költség (jutalék + swap) — ugyanaz, mint a run_pair-ben.
                trade.pnl_usd, trade.commission_usd, trade.swap_usd = _costs.apply(
                    trade.pnl_usd, trade.lot, trade.direction,
                    trade.open_time.timestamp(), m1_time.timestamp(), pair_cfg)
                del open_trades[sym]
                closed_trades.append(trade)
                balance += trade.pnl_usd
                daily_pnl[day_key] = daily_pnl.get(day_key, 0.0) + trade.pnl_usd

        # ── 3. Napi limit ellenőrzés (portfólió szinten) ──────────────────
        daily_loss  = daily_pnl.get(day_key, 0.0)
        daily_limit = daily_limit_usd(trading_cfg, balance)
        if daily_loss <= -daily_limit:
            continue   # nap leállt, nem nyitunk új pozíciót

        # ── 4. Új belépések ellenőrzése ────────────────────────────────────
        occupied = sum(1 for t in open_trades.values() if not t.risk_free)

        for sym, info in pair_data.items():
            m1_df    = info["m1"]
            params   = info["params"]
            pair_cfg = info["pair_cfg"]

            if m1_time not in m1_df.index:
                continue
            row  = m1_df.loc[m1_time]
            hour = m1_time.hour
            _sess_ok = (pair_cfg.get("sess_start", 0) <= hour
                        < pair_cfg.get("sess_end", 24))

            prev_row = info["prev_row"]
            info["prev_row"] = row       # a következő bárhoz (MINDIG frissül)

            if prev_row is not None:
                # M1 jelzés-ÁLLAPOTGÉP MINDEN M1-báron fut (arming megőrzése) — a
                # nyitott pozíció / off-session / betelt slot alatt is; csak a tényleges
                # NYITÁST gátoljuk. (Ugyanaz a fix, mint a run_pair-ben.)
                signal = strategy.bt_on_low_close(info["state"], prev_row, row, params)

                if (signal != "NONE" and sym not in open_trades
                        and occupied < max_slots and _sess_ok):
                    ptr = info["m15_ptr"]
                    m15_df = info["m15"]
                    if ptr < len(m15_df):
                        m15_row = m15_df.iloc[ptr]
                        point_size = pair_cfg["point_size"]
                        pv1_point  = pair_cfg["pv1_point"]
                        sp       = pair_cfg.get("backtest_spread_points", spread_default)

                        # ── Végrehajtási kapuk (él-paritás) — UGYANAZ, mint a run_pair ──
                        # A HATÁS is: blokkol / kockázatcsökkentés / ki, a közös
                        # `core.gates.decide`-on keresztül (per pár × stratégia).
                        _gate_ok, _gate_risk = True, 1.0
                        if _exec_gates:
                            _eff = info["gate_eff"]
                            _failed = {}
                            if _gt.active(_eff, _gt.SPREAD):
                                _atr_e = m15_row.get("atr", float("nan"))
                                if _atr_e and not pd.isna(_atr_e):
                                    _sp_e = row.get("close_spread", float("nan"))
                                    if not (_sp_e > 0):
                                        _sp_e = row.get("avg_spread", float("nan"))
                                    if not (_sp_e > 0):
                                        _sp_e = points_to_price(sp, point_size)
                                    _failed[_gt.SPREAD] = not _spread_gate.spread_ok(
                                        _sp_e / point_size, float(_atr_e), point_size, params,
                                        pair_cfg.get("backtest_spread_points"))[0]
                            if info.get("tf_eval") is not None:
                                # A döntéskor ISMERT árral (az M1-gyertya záróára) —
                                # a formálódó TF-gyertya close-a ez, nem a végleges.
                                _failed[_gt.TF_ALIGN] = not info["tf_eval"](
                                    int(m1_time.timestamp()), float(row["close"]), signal)
                            if info.get("mkt_series") is not None:
                                _cat = info["mkt_series"].get(m15_df.index[ptr])
                                _failed[_gt.MARKET] = (bool(_cat)
                                                       and _cat in info["mkt_adverse"])
                            if info.get("mom_series") is not None:
                                from core import momentum as _momx
                                _failed[_gt.MOMENTUM] = _momx.failed(
                                    info["mom_series"].get(m15_df.index[ptr],
                                                           float("nan")),
                                    signal, info["mom_mode"], info["mom_cfg"])
                            _dec = _gt.decide(_failed, _eff)
                            _gate_ok = not _dec["blocked"]
                            _gate_risk = _dec["risk_factor"]

                        # A stratégia adja a pozíciótervet (SL/TP + saját szűrők)
                        plan = (strategy.bt_entry(m15_row, params, point_size)
                                if _gate_ok else None)
                        if plan is not None:
                            sl_points, tp_points = plan
                            # ── KÖLTSÉG/KOCKÁZAT kapu — a TERV ISMERETÉBEN ────
                            # (Ugyanaz, mint a run_pair-ben: a mérőszám a spread
                            # és a TERVEZETT stop viszonya, tehát a terv UTÁN dől el.)
                            if _exec_gates and _gt.active(info["gate_eff"], _gt.COST):
                                from core import cost_gate as _cgx
                                if _cgx.failed(sl_points, tp_points, sp,
                                               _gt.cost_max_distortion(pair_cfg, cfg)):
                                    _cd = _gt.decide({_gt.COST: True}, info["gate_eff"])
                                    if _cd["blocked"]:
                                        plan = None
                                    else:
                                        _gate_risk = min(_gate_risk, _cd["risk_factor"])
                        if plan is not None:
                            sl_points, tp_points = plan
                            # Óvatos (felezett) méret? A kockázatcsökkentő preset dönti
                            # (Risky felezi; a Felező/Pajzs alap: normál méret) — ÉS a
                            # kapu-hatás (`kockázatcsökkentés`), ugyanazon a szorzón.
                            from core import risk_reduction as _rrm
                            _rrp = (info.get("rr") or {}).get("preset", _rrm.PRESET_OFF)
                            sizing_cfg = _risky_trading_cfg(trading_cfg,
                                                            _rrm.wants_cautious_size(_rrp))
                            if _gate_risk < 1.0:
                                sizing_cfg = {**sizing_cfg, "account_risk_pct":
                                              sizing_cfg["account_risk_pct"] * _gate_risk}
                            eff_slots = calc_effective_slots(balance, sl_points, pair_cfg, sizing_cfg)
                            lot = calc_lot(balance, sl_points, pair_cfg, sizing_cfg, eff_slots)

                            open_price = float(row["close"])
                            if signal == "BUY":
                                open_price += points_to_price(sp, point_size)
                                sl_price = open_price - points_to_price(sl_points, point_size)
                                tp_price = open_price + points_to_price(tp_points, point_size)
                            else:
                                sl_price = open_price + points_to_price(sl_points, point_size)
                                tp_price = open_price - points_to_price(tp_points, point_size)

                            risk_usd = lot * sl_points * pv1_point
                            trade = Trade(
                                symbol=sym, direction=signal,
                                open_time=m1_time, open_price=open_price,
                                sl=sl_price, tp=tp_price, lot=lot,
                                point_size=point_size, pv1_point=pv1_point, sl_points=sl_points,
                                entry_atr=(float(m15_row.get("atr", 0.0) or 0.0)
                                           if not pd.isna(m15_row.get("atr", float("nan")))
                                           else 0.0),
                                entry_balance=balance,
                                risk_usd=risk_usd,
                                risk_pct=risk_usd / balance * 100 if balance > 0 else 0,
                            )
                            trade.legs = [(open_price, lot)]   # 1. láb; a build bővíti
                            trade.build_ref = open_price       # az első ráépítés innen figyel
                            if info.get("bigmove_at") is not None:
                                # Pajzs↔Fibo auto: belépéskor dől el (nagy mozgás → Fibo)
                                trade.rr_preset_eff = (
                                    _rrm.PRESET_FIBO if info["bigmove_at"](ptr)
                                    else _rrm.PRESET_SHIELD)
                            open_trades[sym] = trade
                            occupied += 1

    # ── Végeredmény ───────────────────────────────────────────────────────
    if progress_callback:
        progress_callback(last_eq_date or date_str, balance,
                          0, len(closed_trades), 100.0)
    equity_curve.append((last_eq_date, balance))

    # Per-pár összesítő
    by_sym: dict = defaultdict(list)
    for t in closed_trades:
        by_sym[t.symbol].append(t)

    per_pair: dict = {}
    for sym, tt in by_sym.items():
        r = BacktestResult(symbol=sym, trades=tt)
        s = r.summary(initial_balance)
        s["risky"] = pair_risky.get(sym, False)   # a GUI jelzi a risky párokat
        per_pair[sym] = s

    risky_syms = [s for s, v in pair_risky.items() if v and s in pair_data]
    log.info("Portfolio BT kész | Kötések: %d | P&L: $%.2f | Végegyenleg: $%.2f | Risky: %s",
             len(closed_trades), balance - initial_balance, balance,
             ", ".join(risky_syms) if risky_syms else "—")

    return {
        "trades":          closed_trades,
        "daily_pnl":       daily_pnl,
        "final_balance":   balance,
        "initial_balance": initial_balance,
        "per_pair":        per_pair,
        "risky_pairs":     risky_syms,
        "equity_curve":    equity_curve,
    }


if __name__ == "__main__":
    from strategy.settings import load_config
    cfg = load_config(ROOT / "config.json")

    run_backtest(cfg, save_results=True)

"""A JEL-GYERTYA hossza a motorban — look-ahead őr (2026-08-27).

A LELET. A `bollinger_squeeze_breakout` a saját keretét a `signal_tf_min` szerint
DURVÁBBRA mintázza (M15 → H1), de a `timeframes()`-ben M15-öt deklarál — mert a
LETÖLTÖTT adat tényleg M15, és az élő betöltés abból dolgozik. A motor viszont a
`timeframes()[0].minutes`-ból számolta, hogy egy magas idősíkú gyertya mikor ZÁRT:

    while m15_times[ptr + 1] + _m15_delta <= m1_time:   # _m15_delta = 15 perc

Így a H1 gyertyát a KEZDETE UTÁN 15 PERCCEL zártnak vette → **45 perc
look-ahead**. Élesben mérve: minden jel :15-kor tüzelt, és a sodródás-kontrollált
„él" a spread 400–5000%-a volt (t = 8,6…17,1). A belépőt 45 perccel eltolva az él
eltűnt (t = −2,6…+2,2) — vagyis az egész „él" a jövőbe látás volt.

A JAVÍTÁS. A stratégia a DÖNTÉSI gyertya hosszát már deklarálta
(`signal_bar_seconds` — a riasztás-dedup ebből dolgozott); a motor mostantól
ugyanazt az egy forrást használja (`_signal_bar_delta`). A `0`-t adó stratégiák
(pl. `wpr_sma`: az M1 állapotgép dönt) a RÉGI képletre esnek vissza → bitazonosak.

AMIT ITT ŐRZÜNK:
  1. durvább jel-gyertya → a jel CSAK a gyertya tényleges zárása után szólal meg;
  2. a `signal_bar_seconds() == 0` ág változatlan (a régi viselkedés);
  3. a fallback tényleg a `timeframes()[0]`-ból jön.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from core import applog
applog.harden_console()   # a projekt sajat konzol-vedelme (ekezet/nyil a kimenetben)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from trading import backtest as bt
from strategy.base import Timeframe


class _St:
    """Minimális kamu-stratégia: M15-öt deklarál, de H1-re mintáz át — pontosan
    az a minta, ami a bollingernél a hibát adta."""

    def __init__(self, sig_sec):
        self.name = "teszt_signal_bar"
        self._sig_sec = sig_sec

    def timeframes(self):
        return [Timeframe("M15", 15), Timeframe("M1", 1)]

    def signal_bar_seconds(self, params):
        return self._sig_sec

    def bt_indicators(self, df_hi, df_lo, params):
        hi = df_hi.resample("1h", label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        return hi, df_lo

    def bt_warmup(self, params, label):
        return 0

    def bt_new_state(self, symbol):
        return {"pending": "NONE"}

    def bt_on_high_close(self, state, hi_row, params):
        state["pending"] = "BUY"       # MINDEN lezárt jel-gyertya után jelez
        return state

    def bt_on_low_close(self, state, prev_lo, lo, params):
        sig, state["pending"] = state["pending"], "NONE"
        return sig


def _frames():
    idx15 = pd.date_range("2025-01-06 00:00", periods=24, freq="15min", tz="UTC")
    idx1 = pd.date_range("2025-01-06 00:00", periods=360, freq="1min", tz="UTC")
    mk = lambda idx: pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
         "close_spread": 0.1}, index=idx)
    return mk(idx15), mk(idx1)


PC = {"point_size": 0.01, "sess_start": 0, "sess_end": 24}
m15, m1 = _frames()


def _signal_minutes(sig_sec):
    ser = bt.build_signal_series("T", m15, m1, {}, PC, strategy=_St(sig_sec))
    return [ser.m1.index[i] for i in sorted(ser.signals)]


# ══ 1. Durvább jel-gyertya (H1): a jel CSAK a tényleges zárás után ════════
ts_fix = _signal_minutes(3600)
check("H1 jel-gyertya: van jel", len(ts_fix) > 0, f"{len(ts_fix)} jel")
check("MINDEN jel a teljes ora utan szolal meg (perc == 0)",
      all(t.minute == 0 for t in ts_fix),
      ", ".join(str(t.time()) for t in ts_fix[:4]))
check("egyetlen jel sem tüzel :15-kor (ez volt a 45 perces look-ahead)",
      all(t.minute != 15 for t in ts_fix))

# ══ 2. A régi viselkedés (signal_bar_seconds == 0) VÁLTOZATLAN ═══════════
ts_old = _signal_minutes(0)
check("a 0-t ado strategia a timeframes()[0]-ra esik vissza (M15, :15)",
      bool(ts_old) and all(t.minute % 15 == 0 for t in ts_old),
      ", ".join(str(t.time()) for t in ts_old[:4]))
check("a két ág TÉNYLEG különbözik (a javítás nem no-op)",
      [t.minute for t in ts_fix] != [t.minute for t in ts_old])

# ══ 3. A delta-számoló maga ══════════════════════════════════════════════
check("_signal_bar_delta: a deklarált jel-gyertyát adja",
      bt._signal_bar_delta(_St(3600), {}) == pd.Timedelta(hours=1))
check("_signal_bar_delta: 0 eseten a letoltott keret lepese (15 perc)",
      bt._signal_bar_delta(_St(0), {}) == pd.Timedelta(minutes=15))


class _Boom(_St):
    def signal_bar_seconds(self, params):
        raise RuntimeError("nem szabad elszállnia")


check("_signal_bar_delta: hibás hookot elnyel, nem dönti el a backtestet",
      bt._signal_bar_delta(_Boom(0), {}) == pd.Timedelta(minutes=15))

# ══ 4. A VALÓDI bollinger: a deklarált jel-gyertya = signal_tf_min ═══════
from strategy import get_strategy_by_name

_bb = get_strategy_by_name("bollinger_squeeze_breakout")
_tf = int(_bb.signal_bar_seconds({}) or 0)
check("bollinger: a jel-gyertya durvább, mint a deklarált keret (ezért kellett a fix)",
      _tf > _bb.timeframes()[0].minutes * 60, f"{_tf}s vs {_bb.timeframes()[0].minutes*60}s")
check("bollinger: a params felülírása is átüt a deltába (nem csúszhat szét "
      "az átmintázástól)",
      bt._signal_bar_delta(_bb, {"signal_tf_min": 30}) == pd.Timedelta(minutes=30))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)

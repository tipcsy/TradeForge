# wpr_sma — WPR + SMA trend follower

It uses two timeframes: the **higher** one (M15) gives the direction and the
„good zone", the **lower** one (M1) gives the timing.

## The basic idea

- The **SMA** tells the trend's direction: close above the SMA = buy side, below
  it = sell side. **The strategy is trend-following** — it does not fade, it is
  not mean-reversion.
- The **Williams %R (WPR)** times the entry: it enters in the trend's direction
  when the price turns back from the opposite extreme (that is, after a
  pullback).

## The state machine

One bar is not enough: the entry is decided in **two phases**.

1. **Arming** — on the higher timeframe's (M15) closed bar the WPR enters the
   extreme and the SMA direction allows it. From then on the window is **OPEN**.
2. **Firing** — on the lower timeframe (M1) the WPR **breaks through** the
   trigger level in the trend's direction.

> **Why in phases.** The earlier, adjacent-bar M1 entry **missed the gradual
> break-through** (the BUY side practically never fired). That is why it became
> the same arm → fire state machine as on M15. (v1.25.0)

## Worth knowing

- The M15 window needs a **deep warm-up**: the „good zone" can be armed by an OLD
  extreme, so replaying the signal state goes deeper than the indicator warm-up
  (`signal_warmup_bars`).
- The grey (no-trade) hour optionally **resets** the M15 window
  (`no_trade_resets_signal`, **OFF** by default).
- The SL method is **`swing20`** by default (the extreme of the last 20 bars),
  not ATR.

## Main parameters

| parameter | what it controls |
|---|---|
| `sma_period` | smoothing of the trend direction on the higher timeframe |
| `wpr_period` | the WPR window (higher timeframe) |
| `wpr_m1_period` | the WPR window on the timing timeframe |
| `wpr_entry` | the extreme that ARMS |
| `wpr_trigger` | the break-through level that FIRES |
| `tp_rr_ratio` | the TP as a multiple of the stop distance |
| `atr_max_pct` | volatility filter: above this it does not enter |

> The search range of `tp_rr_ratio` is **0.5–3.0** — deliberately open downwards
> as well, because of the „quick in / quick out" principle.

## Known limits

- The `atr_max_pct` filter was the **root cause of missing afternoon entries** —
  if you see few trades in a band, this is worth checking first.
- Trailing works with an **ATR multiplier** (`trail_activation_atr` /
  `trail_distance_atr`); the old absolute point values were not comparable across
  instruments.

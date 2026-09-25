# SMA chop — did price cross the SMA recently?

In a trend price travels on **one** side of the SMA. If it recently crossed to
the other side, the market is choppy: the SMA direction is noise, and a
trend-following entry goes in a random direction.

## The rule

How many times did the close switch sides of the SMA over the last `lookback`
**closed** bars? If **more** than `max_crosses`, the market is choppy and the
gate **fails**. Direction-independent: it filters BUY and SELL alike.

| parameter | default | meaning |
|---|---|---|
| `timeframe` | M1 | the timeframe |
| `sma_period` | 50 | the SMA length |
| `lookback` | 20 | crossings are counted over this many closed bars |
| `max_crosses` | 0 | this many crossings are still fine — 0 = a single one blocks |

A crossing = two **consecutive** bars close on **different** sides of the SMA.
A bar closing exactly on the SMA inherits the previous side, so a touch never
counts twice.

> The user remembered that "we already did this with an indicator". It was not
> found in the code or the notes (2026-09-25). The closest existing thing is the
> **Momentum** gate's idle state, but that measures the **distance** of the fast
> and slow SMA, not crossings.

## Measured (2026-09-25) — ⚠ effect within noise

14 wpr_sma pairs, 2025-11-01 – 2026-09-24, live-parity backtest (`run_pair`):

| variant | trades | R/trade |
|---|---|---|
| no gate | 6445 | −0.143 |
| SMA chop, **M1** / SMA50 / 20 / 0 | 2812 | −0.126 |
| SMA chop, **M15** / SMA50 / 20 / 0 | 3283 | −0.157 |

It takes away half of the trades, and the per-trade result **does not change
meaningfully** relative to the sample size (±0.015 R). So the gate is **off by
default** (`none`).

## Where it decides

A signal-phase gate (before the plan). Live, in the single-pair and portfolio
backtests and on the chart (viz), with the same measurement.

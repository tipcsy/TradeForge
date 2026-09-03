# Momentum — the market's „revs"

A continuous, **signed**, normalised indicator: the sign is the direction, the
magnitude is how much the market is revving. The metaphor is exact — you press
the accelerator, the needle swings out, then settles back to idle. That is when
the fast average pulls away from the slow one.

## Two measurement bases

- **One timeframe, 3 SMAs** (8/32/100) — two „turnovers" come out (fast↔mid,
  mid↔slow), and their average is the indicator. This is the tightest rev meter.
- **Three timeframes** (default M1/M5/M15) — (close − SMA) per timeframe,
  averaged.

Both divide by the SAME baseline: the average absolute close-to-close move of the
last `vol_window` bars. That is what makes **0.35 mean the same** on GOLD and on
EURUSD, and what makes the threshold portable between the two bases.

## The state vocabulary

The indicator has **exactly two states**, plus missing data — there are no
further grades, so it is not worth waiting for a „picking up" or „slowing down"
readout:

| state | when | what the gate does |
|---|---|---|
| **idle** | \|turnover\| < threshold | fails (per the configured effect) |
| **running** | \|turnover\| ≥ threshold | passes |
| no data | not enough bars yet | passes (fail-open) |

„Running" is deliberately neutral: it means **the market is not standing still**
— not that it is particularly lively. The magnitude is given by the number, not
by the word.

## What it should watch (per strategy)

- **Idle** — the market stands still (|turnover| < threshold) → do not get
  involved.
- **Direction filter** — the turnover runs AGAINST the signal → do not trade into
  it.
- **Both**.

## Measurement (2026-08-07, 5 pairs, ~20,000 M15 bars)

`wpr_sma`:

```
gate OFF          1625 trades   4342 $   PF 1.56   maxDD 42.5%
idle 0.35         1563          4394     PF 1.59   maxDD 40.3%
idle 0.75         1472          4165     PF 1.60   maxDD 33.9%
DIRECTION filter  1559          3876     PF 1.52   maxDD 42.3%
```

**The idle filter is not a profit generator but a drawdown reducer.** The +1.2%
(at 0.35) is noise over 1625 trades; the real benefit is between 0.5 and 0.75:
about a 20% relative DD reduction for about 4% of the profit.

> ⚠ **The DIRECTION filter is HARMFUL on `wpr_sma`** (−10.7% profit, worse PF,
> and it does not reduce the drawdown either). Likely reason: the `wpr_sma` entry
> is mean-reversion in nature, and the direction filter forces trend-following
> logic onto it — besides, the timeframe alignment already does something
> similar, tuned.

On `ml_ai` it is the other way round: there the idle filter only hurts, while the
direction filter is a genuine quality filter — but it throws away half the trades
and halves the profit as well.

## Banded effect (v3.28.0)

A gate's effect need not be a single yes/no. On the **Effect** tab you can build
a ladder: `+ Band` adds a threshold, `Remove` takes it out.

| level | what happens |
|---|---|
| 80% | reduce risk (half size) |
| 100% | block the entry |

**The level is a percentage of the gate's OWN threshold**: 100% is exactly where
this gate would fail anyway. That is what makes it portable, and what makes it
inheritable — global → instrument → instrument+strategy; wherever it is not set,
it is inherited.

> **Without bands nothing changes.** The absence of a ladder is itself a ladder:
> a single implicit band at the gate's own threshold, with the effect set above.
> Until you add a band, the gate behaves exactly as before.

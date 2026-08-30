# Volatility — „is this market moving enough right now?"

The column shows a single number: the **current ATR against the calibrated
baseline**.

```
0.51×   →  the ATR is half the baseline     (⛔ below the band)
1.00×   →  exactly what it was tuned for
1.37×   →  livelier than usual
```

## ⚠ This column SHOWS, it does not decide

Every other gate (Spread, Align, Market, Momentum, Cost) gets its effect here, in
the gate window. **This one does not.** Volatility filtering happens in the
strategy's entry hook (`bt_entry`) — where the backtest, the visualisation and
live trading share the **same** gate. If an effect could be set here too, it
would either filter twice or, set to `none`, promise that you switched the filter
off while the strategy keeps filtering.

The filter's numbers are **strategy parameters** (`atr_min_pct`, `atr_max_pct`),
under the Market filter category.

## Why it got its own column

Until 2026-08-08 this was the **only blocking reason that was visible nowhere**.
BTCUSD silently did not trade for weeks:

| | |
|---|---|
| baseline (`atr_avg_ref`) | 272.75 |
| recent ATR median | **140.19** |
| ratio | **0.51×** |
| allowed band | 245.5 … 872.8 |
| share of bars that fit | **6.0%** |

Over 30 days 26 entry signals were generated, and **all 26 failed on this
filter**. Not a single marker appeared on the chart, not a single trade was made
live — and nothing revealed why. The same was not visible on the other pairs
(Ger40 1.00× · GOLD 0.97× · UsaTec 1.34×): BTC was the only one whose volatility
regime had moved.

## The baseline can be of two kinds

| `atr_baseline_bars` | baseline | when |
|---|---|---|
| **0** (default) | the `atr_avg_ref` saved at optimisation time — **frozen** | the backtest is reproducible; more downloaded history does not tilt it |
| **> 0** | rolling window over N M15 bars (96 = 1 day) | it follows a regime change |

The drawback of the frozen baseline is exactly the case above: if the
instrument's volatility moves persistently, the filter's **meaning** slides with
it and the pair silently stops. The rolling baseline follows that, and is just as
reproducible (it is defined in bars, not in the length of the downloaded
history).

> **The default is not arbitrary.** Measured (7 pairs, 2026-07-01…08-07): with
> the rolling baseline BTCUSD gives 5–8 trades instead of 0, but they are losers
> (−11…−19$), and the portfolio result changes within noise (+1053$ →
> +1050…+1103$). There is no measured basis for switching — the mechanism is
> available, per pair.

## What to do when you see a ⛔

1. **Look at the ratio.** Below 0.9× it is „too quiet", above the cap „too wild"
   — the gate window's `Settings` tab tells you which.
2. **If it stays below the band**, the instrument has left the volatility regime
   it was tuned for. Two routes: a rolling baseline (`atr_baseline_bars`), or
   rethinking `atr_min_pct`.
3. **Re-optimising alone is not enough**: `atr_avg_ref` is computed from the
   whole history, so the same number would come out again.

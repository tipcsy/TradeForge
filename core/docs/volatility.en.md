# Volatility — „is this market moving enough right now?"

The column shows a single number: the **current ATR against the calibrated
baseline**.

```
0.51×   →  the ATR is half the baseline     (⛔ below the band)
1.00×   →  exactly what it was tuned for
1.37×   →  livelier than usual
```

## A real gate — its effect is adjustable (v3.27.0)

For a long time this gate only **showed**: the filtering ran unconditionally in
the strategy's entry hook (`bt_entry`), and the gate window offered nothing to
change. That was misleading — a gate that does not decide is not a gate.

From now on it gets an effect here, like every other gate:

| effect | what it does |
|---|---|
| **Block the entry** (default) | no entry while the ATR is outside the band — the pre-v3.27.0 behaviour |
| **Reduce risk** | enters, but at half size |
| **Off** | the gate **really** does not filter — and neither does the strategy |

> **The thresholds are still strategy parameters** (`atr_min_pct`,
> `atr_max_pct`), not gate config. That makes this the only
> **parameter-driven** gate: the optimiser and the sweep sweep those very
> numbers, which is why `exec_gates=False` ("do not model the execution gates")
> does **not** switch this gate off — otherwise the sweep would be measuring a
> parameter that has no effect.

> **⚠ Disabling the column in Settings now removes the filtering too.**
> Before v3.27.0, taking it out of `gate_order` was purely a display decision. If
> you removed it because "it only shows anyway", switch it back on — the program
> also says so in the log (`volatility_gate_off`).

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

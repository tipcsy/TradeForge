# Target reach — is the target realistic?

The target used to be just a **multiplier** (`tp_rr_ratio × stop`): it said how
many R away it is, not whether the market has recently moved that far at all.
This gate asks exactly that — **for every strategy alike**, because it works
from the final entry plan (stop + target), not from inside the strategy.

## The rule

| direction | passes when |
|---|---|
| **BUY** | the **highest high** of the last `lookback` closed bars reached entry + `reach_pct` × target distance |
| **SELL** | mirror image: the **lowest low** reached entry − … |

If it did not, the target is not realistic and the gate **fails**.

| parameter | default | meaning |
|---|---|---|
| `timeframe` | M1 | the timeframe we look back on |
| `lookback` | 22 | this many **closed** bars |
| `reach_pct` | 0.7 | the share of the target distance that must have been reached (the permissive band is 0.6–0.8) |

The entry reference is the close of the deciding (closed) bar — the same price
the backtest enters at.

> **What it means in practice.** For a BUY the rule requires that price was
> recently **higher** than where it now enters — i.e. it allows an entry after a
> pullback. For wpr_sma it reads as "the pullback was at least 70% of the
> target".

## Measured (2026-09-25) — ⚠ it makes the per-trade result WORSE

14 wpr_sma pairs, 2025-11-01 – 2026-09-24, live-parity backtest (`run_pair`):

| variant | trades | R/trade |
|---|---|---|
| no gate | 6445 | −0.143 |
| Target reach, **M1** / 22 / 70% | 3248 | **−0.204** |
| Target reach, **M15** / 22 / 70% | 4593 | **−0.223** |

- On M1 it **zeroes 10 pairs completely** (EURUSD, GOLD, Fra40, …): in 22
  minutes price almost never covers 70% of a target that is several M15 ATRs.
- The remaining trades are **worse** on both timeframes — the gate keeps the
  weaker entries. The dollar loss is smaller only because there are fewer trades.

So the gate is **off by default** (`none`). Re-measure with other `reach_pct` /
`lookback` values before switching it on.

## Distant targets

If the set's target is "infinite" (`tp_rr_ratio` 15 = no target, with trailing),
the gate fails almost always. On such sets keep the effect `Off`.

## Where it decides

A plan-phase gate: after the strategy's final stop and target, next to the Cost
gate. Live, in the single-pair and portfolio backtests and on the chart (viz),
with the same measurement.

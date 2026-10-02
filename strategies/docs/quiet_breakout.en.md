# Quiet structural breakout (`quiet_breakout`)

An entry signal that buys, in a **quiet market** with a **rising structure**,
the close above the previous M15 high **after a pullback**.

It comes from the HH/HL structure research (2026-10-02, `tools/research/swing_*.py`).
Structure alone carried no direction (trend length, size and nesting matched a
random series), but this filter combination held up on an independent period.
Its limits are below.

## When long?

| # | timeframe | condition |
|---|---|---|
| 1 | **M15** | the close FIRST moves above the last confirmed M15 high, and before that the M15 structure was not rising (there was a pullback) |
| 2 | **M1 / M5 / H1 / H4** | at least `min_align` (2) of them rising: the last two confirmed highs are a higher high AND the last two lows a higher low |
| 3 | **M15** | quiet market: ATR(14) at most `vol_max` (0.78) × its usual value in the same (Hungarian local) hour over the previous ~20 days |

Swing point: the bar is higher (lower for a low) than the `pivot_k` (3) bars
before and after it — so it is known only 3 bars LATER, no look-ahead.

**SL** = the last confirmed M15 low (structural stop); if the distance is not
within 0.5–4 ATR there is no entry. **TP** = SL × `tp_rr_ratio` (default 15 ≈ no target).

## When short?

**Never.** The short side was negative with every filter in the research.

## Measured result (risk 100 per trade, 10,000 account)

Entries 10:00–20:59 Hungarian time, closed at 21:45 or after 8 hours.

| period | venue | trades / year | net / trade | t |
|---|---|---|---|---|
| 2013–2022 (independent test) | research lab | 95 | **+9.07** | 1.58 |
| 2013–2022 | **engine** (`run_pair`, with time exit) | 94 | **+6.56** | 1.17 |
| 2023–2026 | research lab | 201 | +8.18 | 1.40 |
| 2023–2026 | **engine** (with time exit) | 199 | +6.58 | 1.16 |
| 2023–2026 | engine, WITHOUT time exit | 140 | +1.46 | 0.08 |

On 2013–2022 the candidate beats a random long significantly (difference +12.1,
t = 2.01); since 2023 the random long also makes +5.6, the difference is not significant.

⚠ **t < 2: a lead, not proof.** Run it in SIGNAL-ONLY mode first.

## What the framework provides, not the strategy

* **Session:** entries 10:00–20:59 — the framework's hour gate (`trade_hours`: 10–20).
  ⚠ The bar index is the CANONICAL wall clock (Berlin = Hungarian time), so the
  hour list is Hungarian hours directly — no UTC conversion.
* **Exit:** the risk-reduction TIME EXIT (`eod_close` = "21:45", `max_hold_min` =
  480; per pair, `core/risk_reduction.time_exit_due`). Without it the position
  stays open overnight and the swap eats the result (see the table).
  ⚠ Risk reduction is PER PAIR: another strategy on the same pair gets the time exit too.

## Parity

The rule lives in `strategies/quiet_breakout_rules.py`; both the research lab
and the strategy call it. Guarded by `tests/test_quiet_breakout_parity.py`.

# Candle level break (`candle_level_break`)

Waits at an **H4 reversal level** and enters when, after a retest of that level,
price breaks out of a narrow **M15 consolidation range**. The higher timeframe
supplies the level, the lower one the timing.

> ⚠ **This strategy has been measured, and no edge was found.** Read *What the
> measurement showed* before enabling it — the module works and is tested, but
> there is no evidence that it makes money.

## When does it enter?

Four steps, in order (LONG; SHORT mirrored):

| # | timeframe | what happens | what it means |
|---|---|---|---|
| 1 | **H4** | the **high** of the swing-low candle | this is the level — we expect a reversal from it |
| 2 | **H4** | a candle **body** closes above the level | the level has broken |
| 3 | **H4** | price returns to the level, but the body does not close below it | the level holds, flipping from resistance to support |
| 4 | **M15** | a narrow consolidation range forms, then a candle closes above its **high** | the entry |

**SL** = `stop_buffer_atr` × ATR below the level · **TP** = SL × `tp_rr_ratio`
(in points).

## Where it comes from

The method of a YouTube video ("How to build your own Forex strategy").

⚠ **This is our version, not the author's.** The video is not objective on
several points ("momentum candle", trend-line fitting, the exact moment of
entry), and the author did not answer clarifying questions. We made the missing
decisions ourselves — marked `[DÖNTÉS]` in the code. The measurement applies to
this version.

Two such decisions:

* **The "momentum candle" is avoidable.** The formation circled in the video is
  2-3 small candles at the level, and the entry is the breakout that follows. That
  sidesteps the question "how big is a momentum candle?": the breakout is
  measurable at the **range high**, with no threshold.
* **We do not implement the trend line.** Breaking a short trend line is
  practically the same as taking out the range high; a long one is subjective
  (which highs do we fit it to?).

## Why H4 for the level?

Measured on 2026-08-23 — the **density** of levels and the **cost** of the
distance between them:

| timeframe | levels / month | level distance in spreads (Ger40 / GOLD / EURUSD / UsaTec) |
|---|---|---|
| M15 | 230–300 | 13.9 / 17.9 / **4.2** / 20.6 |
| H1 | 60–75 | 33.4 / 41.0 / 10.2 / 49.5 |
| **H4** | 17–19 | 69.2 / 77.4 / 19.9 / 107 |
| D1 | 3 | 118 / 269 / 57.8 / 261 |

With M15 levels on EURUSD the whole trip from one level to the next is **4.2
spreads** — the cost eats it. On D1 there are 3 levels per month per instrument,
which would not reach the trade-count thresholds in any reasonable time. H4 sits
between the two.

The framework's data pipeline is M15+M1, so H4 is resampled **internally** from
M15 (the same way `bollinger_squeeze` derives its own signal timeframe).

## What the measurement showed

**The strategy failed its kill test, before any tuning** (2026-08-23).

Sweeping `stop_buffer_atr` (0.1 → 1.0) on the training half, in profit factor:
**1 of 7 instruments** reached PF > 1 — and that one is exactly **1.00**, i.e.
zero before costs. On the test half **0/7** met the pre-registered reading
(PF > 1.1 and ≥ 50 trades).

⚠ **And here is the substance of the finding:** the win rate sits **at or below
the required value** everywhere. Ger40: 36.7% hit rate against a 36.6%
requirement — that is not an edge, it is a coincidence. So the entry signal
**carries no directional information**: it hits exactly as often as the
risk/reward ratio demands.

The hypothesis fell too. The spec said "the edge can only come from the tight
stop". The direction of the tight stop is **right** (0.1 is best on 4 of 7), but
it produces no edge: **the win rate falls by exactly as much as the RR rises** —
the two cancel out. That is the measurement signature of "no edge": expectancy
cannot be manufactured from the stop, only risk can be moved around.

> Not an implementation error: the structural reward/risk was measured at 0.6–0.9
> (below 1) **before** the module was written, and the measured PF is exactly what
> that structure predicted. The code does what we designed; the method does not
> work.

**Bonus:** **0–5% of trades close at TP** — `tp_rr_ratio` is nearly inert here
too, the same picture as with `wpr_sma`.

## Parameters

| key | what it sets |
|---|---|
| `swing_bars` | how many H4 candles define a swing low/high |
| `level_ttl_bars` | how long a level survives if nothing happens to it |
| `retest_atr` | within what ATR distance a return counts as a retest |
| `cons_bars` | how many M15 candles make up the consolidation range |
| `cons_max_atr` | how **narrow** the range has to be |
| `stop_buffer_atr` | stop distance from the level (in ATR) |
| `tp_rr_ratio` | target as a multiple of the stop |
| `atr_min_pct` / `atr_max_pct` | volatility filter against the shared baseline |

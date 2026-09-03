# Bollinger Squeeze & Breakout

An entry signal that catches the narrowing of the Bollinger bands (**squeeze**)
and the **breakout** that follows it. After a quiet stretch, volatility typically
picks a direction — the strategy waits for that transition.

## When long?

1. **Squeeze active** — the BB is INSIDE the Keltner channel **AND** the
   BandWidth is in the lowest `bw_percentile` percent of the last `bw_lookback`
   bars
2. **The squeeze releases** (it was still on at the previous bar, not any more on
   this one)
3. **Trend** *(OFF by default — see „The DIRECTION VETO belongs to the gates")*:
   `ema_fast > ema_slow` and the price above `ema_fast`
4. **Breakout**: close above the upper BB **AND** `%B ≥ pb_long_threshold`

## When short?

The mirror image of the above (lower band, `%B ≤ pb_short_threshold`, reversed
EMA order).

## The double squeeze condition

The two conditions **answer different questions**, which is why both are needed:

| | what it measures |
|---|---|
| BB inside the KC | the standard deviation fell relative to the ATR — *relative* quiet |
| BW in the lowest percentile | the band is narrow relative to its OWN history — *historical* quiet |

With only the first, a trending but even market would also look like a
„squeeze"; with only the second, a persistently narrow instrument would signal
all the time.

> `bw_percentile` is computed from a **rolling** window, not from the whole
> sample. This is not a matter of style: a whole-sample percentile would also see
> the FUTURE, and the backtest would be silently biased upwards.

## The TIMEFRAME — the single most important setting

`signal_tf_min` (15 | 30 | 60 | 120 | 240 minutes), default **60**.

The **downloaded** data stays M15; the strategy resamples the signal bar from it
(the same resample that `ml_ai` and `tf_align` use). So no new data source is
needed, and switching is a matter of changing one number.

According to the course material, on M15 a squeeze often lasts only 1–2 bars, so
„it has no time to charge up" — the breakout after it carries no energy. Measured
(7 pairs, **three separate** 6-month periods, with untuned parameters):

| timeframe | 2025-02…08 | 2025-08…2026-02 | 2026-02…08 |
|---|---|---|---|
| M15 | 28.6% · **−133$** | 23.0% · **−691$** | 25.1% · **−487$** |
| M30 | 43.6% · +1470$ | 36.9% · +486$ | 44.6% · +2096$ |
| **M60** | **57.9% · +1709$** | **54.1% · +1438$** | **52.0% · +1737$** |
| M240 | 67.9% · +1148$ | 53.5% · +758$ | 65.6% · +1804$ |

**M15 is a loser in all three periods; M60 is a winner in all three.** The hit
rate rises monotonically with the timeframe and the trade count falls
monotonically — 60 minutes is where there are still enough trades (~300 per 6
months over 7 pairs) while the noise is already manageable.

> ⚠ These are **untuned** defaults — which is exactly what makes them worth
> attention: there is nothing to overfit on them. But not a single parameter is
> optimised, and `bw_lookback`/`ema_slow` mean something different on the new
> timeframe. **After changing the timeframe, re-optimisation is required.**

⚠ The warm-up is counted in the downloaded **M15**, while the indicators live on
the signal timeframe — so the bar count is multiplied (H1 → 4×). Without that the
longest window would stay NaN throughout, and the strategy would silently produce
no signal at all.

## The DIRECTION VETO belongs to the gates, not the strategy

The strategy's direction comes from **which band the price broke** — the upper
one (long) or the lower one (short). The EMA trend filter is a **veto** on top of
that: „only enter if the trend agrees too". That is not a signal but a filter —
and filtering is the **gates'** job (adjustable per pair and strategy, uniformly
across strategies).

Measured (5 pairs, 2026-02-01…08-07, untuned parameters):

| EMA filter | Align gate | trades | hit rate | P&L |
|---|---|---|---|---|
| ON | OFF | 399 | 27.1% | −342$ |
| ON | ON | 367 | 28.1% | −247$ |
| **OFF** | OFF | 766 | 28.7% | −142$ |
| **OFF** | **ON** | 700 | **29.4%** | **−31$** |

The EMA filter **halves the trade count without improving the hit rate** (27.1%
with it, 28.7% without) — that is, it does not select, it just cuts. The `Align`
gate, on the other hand, improves both cases.

> That is why the default is `require_trend_alignment: false`.

### …but the GATE does not help either — measured

It was tempting to let the `Align (tf_align)` gate take over the veto role. There
is one problem with it: by default it watches **M1/M5/M15**, which measures noise
rather than context for a strategy that decides on **H1**. So the gate is now
**parameterisable per strategy** (`tf_align.per_strategy`) — and we measured it
that way too.

7 pairs, three separate 6-month periods, M60 bollinger, untuned parameters:

| gate | trades (3 periods) | hit rate | **total P&L** |
|---|---|---|---|
| **OFF (no veto)** | 290 / 318 / 319 | 57.9 / 54.1 / 52.0% | **+4884$** |
| Align M1/M5/M15 | 251 / 273 / 254 | 55.0 / 52.4 / 49.6% | +3733$ |
| Align M15/H1/H4 | 142 / 146 / 149 | — | +1995$ |
| Align H1/H4/D1 | 93 / 114 / 109 | 53.8 / 45.6 / 54.1% | **+1483$** |

**Every gate setting makes it worse**, and the „more correct" higher timeframes
make it worst. The gate cuts the trade count to a third and does not improve the
hit rate.

> **Hypothesis** (not proven): the squeeze breakout is a **volatility-expansion**
> trade, not trend following. The best breakouts often turn out of a range, so
> they start AGAINST the momentary trend — and a trend veto cuts exactly those.

That is why the `Align` gate's effect on the bollinger strategy stays **`none`**.
The structure is ready: if a strategy does need it, it can get its own timeframes
and `sma_period` under `tf_align.per_strategy.<strategy>`, layered over the pair's
shared setting.

## Parameters

`strategies/config/bollinger_squeeze_breakout.json`, grouped into categories in the
parameter window.

| group | keys |
|---|---|
| Bollinger | `bb_period`, `bb_std` |
| Squeeze | `bw_lookback`, `bw_percentile` |
| Keltner | `kc_ema_period`, `kc_atr_period`, `kc_atr_mult` |
| Trend filter | `ema_fast`, `ema_slow`, `require_trend_alignment` |
| Breakout | `pb_long_threshold`, `pb_short_threshold`, `min_bars_since_squeeze`, `max_bars_after_squeeze` |
| SL/TP | `sl_atr_mult`, `tp_rr` |

⚠ `kc_atr_period` is the **channel's shape**, not the execution's. The ATR period
for sizing (`atr_period`) lives in the shared `core/execution_params.py` — as do
BE/trailing and the spread gate. The strategy gives the SL/TP **distance** in
points; the lot and the later movement of the stop are the framework's business.

## Signal architecture

The decision belongs to the **signal timeframe** (`signal_tf_min`, H1 by default)
— the breaking bar gives the signal, as the rules above say. The **M1 merely
delivers**: after the signal it fires on the first M1 bar, once. One release
window produces **one** entry (the further bars of the breakout do not fire
again).

## Earlier measurement (on the M15 timeframe — SUPERSEDED, see above)

Backtest 2026-02-01 … 08-07, 1000$ per pair:

| pair | trades | hit rate | PF | P&L |
|---|---|---|---|---|
| Ger40 | 78 | 35.9% | 0.91 | −46$ |
| UsaTec | 63 | 28.6% | 0.56 | −159$ |
| GOLD | 100 | 22.0% | 0.82 | −84$ |
| EURUSD | 85 | 21.2% | 0.45 | −75$ |
| UsaInd | 73 | 30.1% | **1.20** | +21$ |

> ⚠ **This is NOT the strategy's performance but the starting point's.** The
> numbers were produced with untuned defaults — the `Opt` button has not run on a
> single pair. At RR 2 the break-even is 33.3%: Ger40 (35.9%) and UsaInd are
> already above it, the rest are not. The next step is **per-pair optimisation**,
> and only the OOS result measured after that says anything.

## Direction for further work

The M1 currently only delivers. An **entry refined on M1** (catching the breakout
before the M15 closes) could give less slippage — but that changes the strategy's
character, so it is to be measured separately, not introduced by default.

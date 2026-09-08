# Pending order (WPR straddle)

**Module:** `strategies/pending_straddle.py` · **Config:** `strategies/config/pending_straddle.json`
**Signal timeframe:** `signal_tf_min` — default **M5** (1/5/15/30/60); fills are always watched on M1 · **Magic offset:** +4

---

## The rule

1. **Trigger** — WPR(14) on the **signal timeframe** (`signal_tf_min`, default
   M5). The signal fires when price leaves an **extreme zone** and breaks the
   middle level:
   * from the upper extreme (WPR ≥ −20) breaking **down** through −50, **or**
   * from the lower extreme (WPR ≤ −80) breaking **up** through −50.
2. **Straddle** — on the trigger, **two** orders are placed
   `straddle_spread_mult × spread` away from the signal bar's close: a BUY
   above and a SELL below.
3. **OCO** — whichever one triggers, the other is cancelled immediately.
4. **Expiry** — if neither triggers within `straddle_ttl_bars` M1 bars, both
   are cancelled.

### Two timeframes, two roles

| | timeframe | why |
|---|---|---|
| **trigger** (WPR, placing the straddle) | `signal_tf_min` (default M5) | the pace of the decision |
| **fill** (touching the levels) | **always M1** | a real stop order fills intrabar — watching more coarsely would only degrade the model |

Expiry (`straddle_ttl_bars`) counts **M1 bars**, so the setup's lifetime is
unchanged when the signal timeframe changes — the M1/M5/M15 comparison therefore
measures the same time window.

⚠ `signal_tf_min` is **not an optimiser axis**: the timeframe is a structural
decision, not a tuning parameter. If it were tuned, every trial would measure a
different strategy and the "best" timeframe would be a function of search noise.
**Re-optimise** after changing it.

### The WPR gives timing here, not direction

Breaking −50 says *"it is moving now"* — **which way** is decided by the
straddle. This is deliberate: earlier measurements in this project (`Timing, not
an entry signal`, `Indicator list screened`, 23 rules × 5 pairs × 2 directions)
found that indicators say nothing about direction, but plenty about volatility.

---

## ⚠ What this module cannot do — read before interpreting any result

**TradeForge has no pending orders.** `core/mt5_connector.py` only ever sends
`TRADE_ACTION_DEAL` (market order), and the backtest always opens at the M1
bar's **close** (`trading/backtest.py`: `open_price = _bar_c`). There is no
`BUY_STOP`, no OCO and no expiry anywhere in the framework.

So this module implements a **virtual straddle**: the strategy tracks the two
levels itself and signals on whichever one the M1 bar **touches first** — but
the actual entry happens at that bar's **close**, not at the level.

| | virtual straddle (this module) | real pending order |
|---|---|---|
| fill price | the M1 bar's close | exactly the pending level |
| live ↔ backtest | **bit-identical** (same hook) | needs framework work |
| implementation | one strategy module | connector + live OCO/expiry + intrabar fill model |

### ⚠ …but the difference MEASURES as zero

2026-09-07, 6 pairs, 19,371 fills. The **advantage** of filling at the level
versus at the M1 close, in R:

| pair | mean | median | positive |
|---|---:|---:|---:|
| Ger40 | −0.009 | +0.002 | 50.8% |
| UsaTec | −0.032 | −0.011 | 48.5% |
| GOLD | **+0.015** | +0.007 | 50.9% |
| EURUSD | −0.018 | −0.019 | 37.6% |
| UsaInd | −0.005 | +0.004 | 51.6% |
| UK100 | **+0.020** | +0.011 | 53.9% |

So the M1 close is an **unbiased** proxy for the pending level: higher variance,
same expectation. Exactly what an efficient market gives you (`The market became
more efficient`).

> **Consequence:** building real pending-order support into the framework would
> **not flip** the results below. The current numbers are not "provisional" —
> they are the verdict.

`max_chase_spread` (skip the entry if the M1 close is further than that many
spreads from the level) is therefore **off by default** (0): it buys no fidelity
while discarding 3–44% of the fills.

---

## Spread is the yardstick

The levels — and by default the stop as well — are measured in **spreads**, not
in ATR. This is deliberate: the `Instrument cost ranking` finding measured a 22×
spread of cost in R across instruments (UsaTec 0.032 R … EURHUF 0.707 R). With a
spread-scaled stop that dispersion disappears, so pairs become comparable.

Spread comes from the bar's **own** spread column:

| source | column | unit |
|---|---|---|
| parquet (backtest) | `close_spread`, fallback `avg_spread` | price |
| MT5 `copy_rates` (live/viz) | `spread` — `live_trader.get_candles` already converted it to price | price |

**If none is present the strategy does not signal** — and it says so in the log
once (`pending_straddle (M1): a gyertyákon NINCS spread-oszlop …`). A silent zero
would look exactly like a quiet market; that is this project's costliest class
of bug.

---

## SL / TP

| `sl_mode` | SL | when |
|---|---|---|
| `straddle` (default) | `sl_spread_mult × spread` | the straddle's natural scale |
| `atr` | `sl_atr_mult × ATR(M15)` | the codebase's usual stop |

The classic *"the opposite leg is the stop"* straddle setting is
`sl_spread_mult = 2 × straddle_spread_mult` (4.0 with the defaults).

TP is `tp_rr_ratio × SL` in both modes.

> ⚠ **A tight stop lets the spread eat the edge.** With a 4-spread stop, the one
> spread you pay on entry is **25% of R**. The `WPR-only M1 entry: no edge`
> finding died exactly on this. Hence the wide `sl_spread_mult` range (2…20) —
> it is the **second** axis to measure (the first is `straddle_spread_mult`).

> ⚠ **`min_lot` over-risk.** A tight stop makes `calc_lot` return a large lot.
> The weighted slot budget handles this, but check on the Positions tab how much
> risk actually reaches the market.

---

## What does NOT belong to this module

| request | where it lives |
|---|---|
| "move the SL to BE+spread" | **risk reduction** — `core/risk_reduction.py` + `core/rr_state.py` (per pair). Breakeven there is already **cost-aware**: the buffer must cover commission and swap. |
| how big the lot should be | `core/risk_manager.py` (balance × risk / slots) |
| spread gate, TF alignment, market state, volatility | the shared execution config + `core/gates.py` |

The strategy only supplies the SL/TP **distance** (`sl_tp_points`) — not the lot
and not any later stop movement. See `strategy/base.py`.

---

## Marker column (dashboard)

Three circles, left to right:

| circle | meaning | colour |
|---|---|---|
| **WPR extreme zone** | WPR has visited an extreme → armed | yellow / grey |
| **Pending pair placed** | the straddle is out and still alive | cyan / grey |
| **Fill** | filled on this M1 bar | green (BUY) / red (SELL) / grey |

## Chart drawing (MT5)

* The pending levels as **dashed** lines (green = BUY side, red = SELL side),
  spanning exactly the time the order was out.
* Fills use the usual entry marker (direction line + Entry/TP/SL levels).
* A WPR(14) sub-window with the four levels.
* The drawing only appears on the **M1 chart** (`TfOnly(1)`) — every decision is
  made there, so any other timeframe would be misleading.

---

## Modelling decisions

**`[DECISION]` Both levels are hit inside one bar.** Which came first cannot be
recovered from OHLC (that needs ticks). We take the **pessimistic** path, with
the same convention as the engine's intrabar SL/TP ordering: on an up bar
(close ≥ open) the path starts at the low → the **SELL** filled, and price then
went against it. That is the whipsaw — we do not paper over it.

**`[DECISION]` One straddle per setup.** After a trigger the `zone` (extreme
memory) is cleared, so the next placement requires price to visit an extreme
**again**. Without this, chop around −50 would place a new straddle every bar.

**Arm → fire, not "adjacent bars".** `zone` is the arming (the extreme may have
been visited any time in the past), crossing −50 is the firing. Per the `M1 entry
state machine` finding, the adjacent-bar pattern misses gradual breaches (BUY
essentially never fired).

**Deep warmup (M1: 1440 bars).** `zone` can be arbitrarily old. With a shallow
warmup the engine would not "see" the arming while the visualisation would —
exactly the `M15 warmup depth divergence` finding.

---

## First measurement — DEFAULT (untuned) parameters

`sl_spread_mult = 6`, `straddle_spread_mult = 2`, `tp_rr_ratio = 2`, ~2.5 months,
`exec_gates=True`:

| pair | trades | P&L | WR% | mean R |
|---|---:|---:|---:|---:|
| Ger40 | 1789 | −804 $ | 29.0 | −0.1394 |
| UsaTec | 2455 | −993 $ | 28.2 | −0.1559 |
| GOLD | 2650 | −764 $ | 30.8 | −0.1195 |
| EURUSD | 994 | −175 $ | 36.7 | −0.2616 |
| UsaInd | 2535 | −369 $ | 32.0 | −0.1645 |
| UK100 | 2314 | −281 $ | 39.4 | −0.1624 |

### The result is the cost

Sweeping `sl_spread_mult` shows the loss shrinking **proportionally** as the stop
widens — exactly as the `−1 / sl_spread_mult` cost formula predicts:

| `sl_spread_mult` | expected (−1/mult) | Ger40 | UsaTec | EURUSD |
|---:|---:|---:|---:|---:|
| 3 | −0.333 | −0.306 | −0.329 | −0.448 |
| 4 | −0.250 | −0.205 | −0.231 | −0.380 |
| 6 | −0.167 | −0.139 | −0.156 | −0.262 |
| 9 | −0.111 | −0.101 | −0.088 | −0.197 |
| 14 | −0.071 | −0.085 | −0.090 | −0.122 |
| 20 | −0.050 | −0.047 | −0.028 | −0.128 |

The residual (measured − expected) stays within **±0.03 R** on Ger40 and UsaTec
and is consistently **negative** on EURUSD. No consistent edge — the result is
practically *identical* to the cost, the same picture as the `Expectancy equals
minus the cost` finding.

### Kill test: the WPR trigger adds nothing

Replacing the WPR trigger with **random timing** (place a straddle every 30th M1
bar, everything else unchanged), `sl_spread_mult = 6`:

| pair | WPR trigger | random timing |
|---|---:|---:|
| Ger40 | −0.1394 | **−0.1134** |
| UsaTec | −0.1559 | **−0.1496** |
| EURUSD | −0.2616 | −0.3015 |

Random timing is **better on two pairs out of three**. So the −20/−80 → −50 break
carries no measurable information about entry timing — the same outcome as
`CLB: no edge`.

> ⚠ These are **untuned** parameters (`Untuned pairs contaminate measurements`).
> The optimiser may find a better combination — but the two tests above show the
> result is driven by the **cost ratio**, not by the WPR levels, and a parameter
> search cannot fix that, only hide it.

---

---

## The timeframe does not help (M1 vs M5 vs M15)

Same code, only `signal_tf_min` differs. Default parameters, same window:

| pair | M1 trades | M1 mean R | M5 trades | M5 mean R | M15 trades | M15 mean R |
|---|---:|---:|---:|---:|---:|---:|
| Ger40 | 1789 | −0.1394 | 428 | −0.1399 | 167 | −0.1060 |
| UsaTec | 2455 | −0.1559 | 632 | −0.1623 | 202 | −0.1535 |
| GOLD | 2650 | −0.1195 | 611 | −0.1193 | 210 | −0.0920 |
| EURUSD | 994 | −0.2616 | 466 | −0.2832 | 178 | −0.2211 |
| UsaInd | 2535 | −0.1645 | 569 | −0.1210 | 193 | −0.2619 |
| UK100 | 2314 | −0.1624 | 533 | −0.1368 | 175 | −0.1860 |
| **total** | **12,737** | **−0.167** | **3,239** | **−0.160** | **1,125** | **−0.170** |

Trade count falls in the expected ratio (1 : 3.9 : 11.3 ≈ the timeframe ratio),
but the **per-trade result is practically identical**. Absolute P&L is smaller on
M5 only because there are fewer trades — not because the trades are better.

### On M5 the kill test fails too — now 3 out of 3

`sl_spread_mult = 6`, WPR trigger replaced with random timing:

| pair | M5 WPR trigger | random timing |
|---|---:|---:|
| Ger40 | −0.1399 | **−0.0960** |
| UsaTec | −0.1623 | **−0.1368** |
| EURUSD | −0.2832 | **−0.2600** |

On M1 it was 2 out of 3; on M5 **random wins on all three**. The cost curve holds
on M5 as well (mult 3 → −0.37, 6 → −0.14, 14 → −0.08), so the loss is not a badly
chosen timeframe: per-trade expectancy equals the cost on every timeframe.

---

## Rollout / measurement — suggested order

1. **Enable it on one pair** (click the instrument name, tick the strategy).
   Every registered strategy is available by default.
2. **Look at the chart** (viz): are the levels and fills where you expect? If no
   markers appear, check the log for the missing-spread-column warning.
3. **Optimise** (Opt button) — the first two axes are `straddle_spread_mult` and
   `sl_spread_mult`.
4. **Holdout** per the `Holdout protocol`. ⚠ Because of the `Optuna crosses the
   OOS boundary` finding, walk-forward numbers are inflated; the verdict belongs
   to the separately held-out slice.
5. Building **real** pending-order support is **not justified** by the
   measurement above: the level-fill advantage is zero.

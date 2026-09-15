# Csilla's entry (`csilla`)

A structure break on **two timeframes**: after an M15 close beyond a
**significant daily/weekly level** (a confirmed D1 or W1 swing high/low), we
enter on the **break of an M1 "flag"** (pullback) in the direction of the break.
A mechanical reading of Csilla's discretionary method; the rule lives in
`strategies/csilla_rules.py`, which the research lab calls as well.

## The rule

| step | what happens |
|---|---|
| **level** | `level_kinds` (default `D1+W1`; any combination of H1 / H4 / D1 / W1): confirmed D1 fractal swing (`k_d1` = 2 → known 2 days later) or W1 swing (`k_w1` = 1); `k_h4`/`ttl_h4`, `k_h1`/`ttl_h1` for H4/H1. High = resistance, low = support. Lives `ttl_d1` / `ttl_w1` days or until broken. Each level breaks once. |
| **break** (M15) | an M15 candle closes ABOVE the level (BUY side) / BELOW it (SELL side) |
| **entry** (M1) | within `max_wait` × 15 min after the break, a confirmed M1 swing on the break side (`k_lo` = 3), then a close beyond it → **enter on that close**. Several entries may follow one break. |
| **session** | NOT a strategy parameter: Csilla's band (Ger40 8–11h, UsaTec and GOLD 15–18h, server time) is the framework's strategy-scoped **trading hours** (the dashboard's hour picker, `data/optimized_params/csilla/<PAIR>_hours.json`). The strategy signals in every hour; the hour gate decides. |

**SL** = `sl_atr_mult` (1.5) × ATR of the **break's M15 candle** · **TP** = SL ×
`tp_rr_ratio` — 30 R by default, i.e. effectively no target.

## The exit — NOT the strategy's

The measured (forward-tested) exit: **BE at +0.67 R**, then a **2 R trailing
stop**, no target, max 5 days. Set it in the pair's **risk reduction**:
`breakeven_r = 0.67`, `trail_activation_atr = 3.0`, `trail_distance_atr = 3.0`
(2 R = 3 ATR15), preset `off`. The target is far so the R-based breakeven is
not disabled by it.

## What was measured

8 pairs, 2013–2026 (tick-built M1), full costs: every-fractal variant −0.22 R
per trade; D1/W1 levels with an M15 stop −0.07 R; **Csilla's band** (named in
advance by the user) with a fixed 1.5 ATR15 stop, BE 0.67 R and 2R trailing:
**+0.12 R, t = 1.5, 9/14 years** — a lead, not proof. Hence a forward paper
test from 2026-09-15 (`tools/csilla_forward.py`) with a pre-registered kill
threshold (n ≥ 60 and R < −0.10). Small targets, early breakeven, trailing and
position building were all measured: none turns the 8-pair result positive.

Level parameters (`k_d1`, `k_w1`, `ttl_*`) define what a "significant level"
is and are not tuned during the forward test. Deep M15 warm-up (~1 year, for
the W1 levels); the context is cached per pair.

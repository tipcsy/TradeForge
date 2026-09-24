# Market sessions — where is the world's trading day?

Tracks the opening hours of six exchanges (Europe/Frankfurt, London, America,
Asia/Hong Kong, Japan, Australia) and distinguishes six states. It is a gate, not
merely a display, because the same inheritance and the same three effects apply to
it as to every other gate — but **no state blocks by default**. See below.

## The states (sharpest wins)

| state | when | colour in the column |
|---|---|---|
| **Open** | the opening minute | red |
| **After open** | `utan_perc` minutes after the open | red |
| **Before open** | `elott_perc` minutes before the open | yellow |
| **Before close** | `zaras_elott_perc` minutes before the close | yellow |
| **Open (session)** | the rest of the trading day | green |
| **Closed** | weekend, overnight, outside hours | grey |

When several watched markets report a state at once, the **sharpest** wins, and the
row also names the market causing it.

## Why no AND/OR rule engine is needed

An AND/OR rule system was considered. It turned out to be unnecessary: **"all
watched markets closed"** is AND, **"any market in its post-open window"** is OR —
and both are a SINGLE state over the market set assigned to the pair. The template
is therefore the `markets` list itself.

## ⚠ For per-state effects to be LIVE, the gate must not be "Off"

The bands (state → effect) **only take effect** when the gate's effect on this
pair/strategy is not `none`. That is not this gate's rule but the framework's:
"a disabled gate has no bands" — otherwise an inherited ladder could silently
re-enable a deliberately disabled gate.

So the order is: **1.** set the gate's effect to `block`, **2.** use the bands to
say what each state does (a state with no band passes). The gate's effect acts as
a master switch; the bands decide the detail.

## Two calendars: exchange vs. FX session

The user's decision (2026-09-24): **both, by instrument.**

| calendar | for | window |
|---|---|---|
| **Exchange hours** | index CFDs (Ger40, UsaTec, …) | the real opening bell: Frankfurt 09:00, NYSE 09:30 local |
| **FX session** | FX pairs, metals | the financial centre's business day: **08:00–17:00 local** |
| **Always open** | crypto | no opening bell, so no opening churn — a single "24/5" marker |

The `naptar` field defaults to `auto`: decided from the symbol NAME (six letters
from two known currency codes → session; XAU/GOLD → session; BTC/ETH → always
open; otherwise exchange). The broker's own classification
(`symbol_info().path`) would be more precise, but the gate must not import MT5
(pure module, packable into `.tfg`). So the heuristic is narrow, predictable and
**overridable per pair** — that is the final word.

### What this means in server time (September 2026)

| market | exchange | session |
|---|---|---|
| Australia | 02:00–08:00 | 00:00–09:00 |
| Japan | 02:00–08:00 | 01:00–10:00 |
| Asia | 03:30–10:00 | 02:00–11:00 |
| Europe | 09:00–17:30 | 08:00–17:00 |
| London | 09:00–17:30 | 09:00–18:00 |
| America | 15:30–22:00 | 14:00–23:00 |

⇒ the "all closed" window is 22:00–02:00 with the **exchange** calendar and
23:00–00:00 with the **session** one. So the session calendar does not claim
anything is open at 23:00 either: New York closes at 23:00, Sydney opens at
00:00. The difference is in the night hours (Sydney/Tokyo start earlier and
close later).

⚠ The server-time column holds for summer time. Boundaries are always computed
from local time (`zoneinfo`), so they shift by themselves in winter — there are
no hand-written "round" server hours to fix twice a year.

## Settings

| key | meaning | default |
|---|---|---|
| `markets` | which markets this pair watches | all six |
| `elott_perc` | length of the "before open" window | 10 |
| `utan_perc` | length of the "after open" window | 10 |
| `zaras_elott_perc` | length of the "before close" window | 10 |
| `adverse` | which states FAIL the gate | empty |

Inheritance: `pairs.<SYM>.sessions` → `sessions` → built-in default.

## ⚠ Time: measured, not assumed

Bar timestamps are in **server time**, and the server's clock is **Europe/Berlin**
local time (including summer time). This is not an assumption: the average range of
Ger40 M1 bars peaks at index **09h in both winter and summer** (= the Frankfurt
open), and the US bump at 15–16h — in true UTC these would fall on two different
hours. Reading them as "real UTC" makes the gate **two hours wrong in summer**,
missing exactly the opening spike it was built for.

## ⚠ It does not know holidays

Without an exchange calendar it would say "open" on Christmas Day. Actual tick
activity is measured per instrument by `core.market_state` — this module knows the
CALENDAR, not the turnover.

## Why it does not block by default

The project's own measurements disagree:

- **For:** across 186,471 trades the hour-of-day effect is almost entirely cost
  structure, and 22:00 is the only hour where even the GROSS edge is strongly
  negative (−0.179 R). But the mechanism is cost — which the spread and cost gates
  measure DIRECTLY; this is only a proxy.
- **Against:** in the candle-pattern study the 15:30–16:00 server window (= 09:30
  New York, the opening bell) came out as the BEST hour of the day.

So the gate SHOWS. Before any state is set to `block`, its effect **must be
measured**.

## The backtest measures it too (v3.102.0)

At first only the live engine knew about plugged gates: the backtest measured
the six BUILT-IN gates one by one, hand-imported. That would have meant a silent
divergence between live and backtest — the backtest taking signals this gate
filters out live.

Now **both backtest paths** (single-pair and portfolio) walk the gate registry,
and plugged gates measure through their own `measure(ctx)`. What the gate gets
in a backtest: the symbol, the direction, the pair config, the strategy
parameters, and **the entry M1 bar's time as "now"** — that is the backtest's
decision moment (live, the same moment is ≈ "now", so both paths ask about the
same minute).

The built-ins' fast path (precomputed series, array indexing) is unchanged: with
effect `none` a plugged gate gives **bit-identical** results to before it was
wired in — and is not even called.

## What it adds

The spread gate is **reactive**: it sees once the spread has already widened. This
one knows **in advance** — ten minutes before the London open it already knows it
is coming.

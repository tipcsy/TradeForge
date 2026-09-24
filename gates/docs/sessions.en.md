# Markets — where is the world's trading day?

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

## What it adds

The spread gate is **reactive**: it sees once the spread has already widened. This
one knows **in advance** — ten minutes before the London open it already knows it
is coming.

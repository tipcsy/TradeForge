# Market state gate

A **market classifier** categorises the current market (today: `regime` — based
on ADX/DI/ATR, 8 categories), and the gate „fails" when the classification is on
the **adverse** list.

## Categories

```
Cl.Bull  Cl.Bear       clean trend
Ch.Bull  Ch.Bear       choppy trend
Ranging                no direction
Dead                   dead market
Uncert.   Transit.     cannot be decided
```

## Settings

- **Market classifier** — `gates.market.classifier` (default: *Regime*). It runs
  on EVERY instrument, so the `Market` column shows the state everywhere.
- **Adverse classifications** — default: *Dead* + *Uncertain*.
- **Market band on the chart** — `gates.market.viz`, drawing only.

All three can be overridden per pair in the usual `pairs.<SYM>.gates.market`
block (the gate dialog saves there), like any other gate's measurement settings.

> ⚠ **Before 2026-10-12 the instrument switched it on** (`pairs.<SYM>.market_strategy`,
> „Market pre-filter"). Without it the gate SILENTLY let everything through, even
> when set to `block`. The old keys are no longer read (the config checker flags them).

## Banded effect (v3.28.0)

On the **Effect** tab you can give each classification its own effect: `+ Band`
adds a category, `Remove` takes it out. There is nothing to sort here — market
state is a category, not a scale:

| classification | what happens |
|---|---|
| Dead | block the entry |
| Ranging | reduce risk (half size) |

Anything not listed passes. The list is inherited: global → instrument →
instrument+strategy.

> **Without bands nothing changes**: the `adverse` set decides, as before.

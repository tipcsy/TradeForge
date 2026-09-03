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

- **Market classifier** — `pairs.<SYM>.market_strategy`. „None" → the gate is
  silent.
- **Adverse classifications** — default: *Dead* + *Uncertain*.
- **Market band on the chart** — drawing only.

> ⚠ **It takes two things.** Setting the effect alone is not enough: you must
> ALSO SELECT a classifier on the pair, otherwise the gate has nothing to measure
> and never fires. The config checker warns when this state occurs.

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

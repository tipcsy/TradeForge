# Cost/risk gate

It does not measure the **size** of the spread but how much the spread ruins the
trade.

## What the spread ruins — and what it does not

The spread **does NOT change the payout**: if the TP is hit you win `tp`, if the
SL is hit you lose `sl`. The ratio of profit to loss — and therefore the
break-even win rate, `1/(1+RR)` — is unchanged.

What it does ruin is the **DISTANCE** to cover, because the stop fills on the
broker's other side:

```
distance_to_win / distance_to_lose = (TP + spread) / (SL − spread)
```

On EURCHF the payout stays 2:1, but the ratio of the distances is **3.4:1** —
that is, you must cover a path with 3.4:1 odds for a 2:1 payout. That gap is the
cost.

## Measurement (2026-08-07)

Expected value of a random entry per trade, in R, over 12,000 M15 bars:

```
GOLD    +0.029R      UsaTec  −0.075R      EURUSD  −0.127R
EURJPY  −0.196R      EURCHF  −0.201R      EURGBP  −0.201R
```

On EURCHF, then, **every trade starts at −0.20R** before any signal quality even
enters the picture.

## Why it is needed when there is already a spread gate

The spread gate's relative floor (`min_spread_mult × normal_spread`) is by
construction larger than the pair's normal spread — so a pair NEVER trips over it
at its own usual spread:

```
pair     spread   ATR term   floor   effective limit   blocks?
EURCHF       15        6.2     23.1              23.1        no
EURGBP       14        5.7     21.6              21.6        no
```

The ATR term would have blocked long ago; the floor lets it through.

## Why a gate, and why it does not move the SL

**Measured:** widening the stop does not save an expensive instrument. On EURCHF
taking `sl_atr_mult` from 1.5 to 3.0 brings the spread/SL ratio from 31% down to
15%, but the edge of a random entry collapses meanwhile — the 2× wider TP becomes
unreachable. There is no geometry that pays for the spread.

**Structural reason:** if a gate could move the SL, „1 R" would lose its meaning.
The system is built on R-based accounting — the risk at entry is fixed, the P&L
cells also show R, and the risk-reduction presets think in R. A silently
rewritten stop would make every earlier R number a lie in hindsight.

> This is the ONLY gate that is decided after the entry PLAN — it needs the SL
> the strategy intends.

## Banded effect (v3.28.0)

A gate's effect need not be a single yes/no. On the **Effect** tab you can build
a ladder: `+ Band` adds a threshold, `Remove` takes it out.

| level | what happens |
|---|---|
| 80% | reduce risk (half size) |
| 100% | block the entry |

**The level is a percentage of the gate's OWN threshold**: 100% is exactly where
this gate would fail anyway. That is what makes it portable, and what makes it
inheritable — global → instrument → instrument+strategy; wherever it is not set,
it is inherited.

> **Without bands nothing changes.** The absence of a ladder is itself a ladder:
> a single implicit band at the gate's own threshold, with the effect set above.
> Until you add a band, the gate behaves exactly as before.

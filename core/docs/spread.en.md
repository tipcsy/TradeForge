# Spread gate

It measures the broker's **current spread** against how much the market moves
(ATR). When the spread is too wide — a quiet or chaotic market, news — the entry
is skipped.

## The formula

```
limit = max(floor, (ATR / point) × max_spread_atr_ratio)
ok    = current_spread ≤ limit
```

The `250/1312` form in the cell means **current / limit**, in points.

## The three numbers

- **Spread as a share of ATR** (`max_spread_atr_ratio`, default 0.20) — the
  allowed spread is this share of the ATR.
- **Floor** (`min_spread_mult`, default 1.5) — the lower threshold is this many
  times the instrument's OWN typical spread.
- **ATR window** (`atr_period`, default 14) — the volatility baseline.

All three are **strategy-independent**, per instrument:
`data/execution_params/<SYMBOL>.json`.

## Why the floor is relative

It used to be a fixed 2.0 „pip" — except a „pip" means something different on
every instrument. Measured on real history, how much the gate blocked:

```
GOLD    floor 200 points, typical spread  45  ->  0.1%   effectively deaf
EURJPY  floor 200 points, typical spread  25  ->  0.8%   effectively deaf
UK100   floor 200 points, typical spread 139  -> 30.2%   filtering
```

The same number let everything through on one pair and cut a third of the trades
on another. Since then the floor measures against the instrument's own normal
spread.

> ⚠ **What this gate does NOT catch.** By construction the floor is always
> larger than the pair's normal spread, so a pair never trips over it at its OWN
> usual spread. This gate catches the *widening* spread, not the *chronically
> expensive* instrument — that is what the **Cost/risk** gate is for.

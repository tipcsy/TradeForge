# Timeframe alignment („Align")

For each timeframe it checks whether the price is **above or below** the SMA, and
asks: do they ALL point the same way?

```
direction(timeframe) = sign(close − SMA(sma_period))
```

The dots in the cell show the direction per timeframe: **green** = up, **red** =
down, **faint** = neutral.

## Settings

- **Enabled** — this fills the „Align" column and feeds the gate.
- **Watched timeframes** (2–6, default M1/M5/M15) — a single timeframe is not an
  „alignment".
- **SMA period** (default 50).
- **SMA lines on the chart** — drawing only; the watching works regardless.

The measured state is an **instrument property**, while the gating is set **per
strategy**.

## Direction-aware

This gate does not simply „block or not": it looks at the **signal's direction**.
A downward alignment blocks a BUY but not a SELL. That is why the row can only
show whether there is an alignment at all — the final decision belongs to the
engine, where the signal's direction is also known.

> The gate can also inherit from the `tf_align.gate` LIST (the old config form).
> If the effect is „inherited" and you did not set it on this pair, the window
> writes out where it comes from.

## Banded effect (v3.28.0)

On the **Effect** tab you can build a ladder: `+ Band` adds a threshold, `Remove`
takes it out. For this gate the threshold is a **count** — how many timeframes
line up with the signal — and FEWER is worse:

| at most this many aligned | what happens |
|---|---|
| 2 | reduce risk (half size) |
| 1 | block the entry |

The ladder is inherited: global → instrument → instrument+strategy.

> **Without bands nothing changes**: the gate keeps its old all-or-nothing rule
> (only FULL alignment passes).

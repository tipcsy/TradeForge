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

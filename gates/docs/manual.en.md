# Manual pre-filter

The result of the morning **manual market review**, per instrument. On the table
it sits **before the Gates block** („Manual” column); click the cell and choose
today's state from the drop-down.

| State | Effect |
|---|---|
| **None** | nothing set — trade freely |
| **Do not trade!** | every entry blocked |
| **Cautious (half risk)** | enters with half the risk |
| **Nice chart ↑** | bull market: longs allowed, shorts blocked |
| **Nice chart ↓** | bear market: shorts allowed, longs blocked |
| **Nice chart ↕** | nice chart, both directions allowed |

## Notes

- **New day → everything „None”.** The choice is for today only (local date).
- **Switch:** `config.json` → `"manual_filter": {"enabled": true}`. Off = no
  column, no effect.
- **Same for every broker** (the view is about the instrument, not the account):
  `data/manual_filter.json`.
- In the engine it is a **gate**: can be turned off per strategy
  (`pairs.<SYM>.gates.manual.<strategy>: "none"`).
- **No effect in backtests** — the morning judgement has no history.

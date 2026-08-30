# Trend pullback (`trend_pullback`)

An entry signal that buys a short **pullback** in a **strong uptrend, in a lively
market**. The three conditions come from three **different timeframes** — that is
the point: the larger frame gives the context, the small one the timing.

This is not an invented rule: the `tools/research/` search system found it among
231,000 candidates, and it held up out of sample. Its origin and its limits are
below.

## When long?

All three conditions at once, and the entry is on the **rising edge** (when the
alignment *becomes* true, not while it is true):

| # | timeframe | condition | what it means |
|---|---|---|---|
| 1 | **H1** | price > the **upper** band of Keltner(14; 2.0) | strong uptrend |
| 2 | **M30** | ATR(14) > the 200-period average of the ATR | the market is alive, there is movement |
| 3 | **M5** | stoch(14) %K crosses **below** %D | a short pullback |

1–2 are the *context* (they persist for hours), 3 is the *event* (a single bar).
That is why it makes sense: we are not buying the breakout but the pullback
inside the trend.

**SL** = M15 ATR × `sl_atr_mult` · **TP** = SL × `tp_rr_ratio` (in points).

## When short?

**Never.** The research measured the short side separately: all six short
candidates of the search **lost** on the real engine. This is not a gap but a
result — do not „symmetrise" it.

## The rising edge — why „the alignment is true" is not enough

My first measurement evaluated every bar while the alignment held, and showed
**+0.029 R**. On the real engine it came out **−0.022**. The reason:

> the edge was spread over the **period**, it was not there at the **moment of
> entry**.

That is, the pattern marked out a good *period* (market timing), but at the
moment of entry there was no advantage. A state-like condition stays true for
hundreds of bars; the engine, however, opens one position on it. After the fix
(`rising edge`) the signal **passed** on the engine. See `on_bar_close` /
`bt_on_low_close`.

## Origin and validation

| step | what it did | result |
|---|---|---|
| search | 231,000 candidates, **2017–2022** | the pattern was chosen here |
| holdout | **2023–2026**, UNTOUCHED until then | R **+0.1225**/trade, **t = +2.94** |
| real engine | `run_pair` with slots and gates | **4/4 positive years** |
| drift test | is the swap a cost or a source | **cost** — better without it |
| intraday? | holding-time distribution | **median 1.8–3.4 hours** |

### The 2017–2022 „flatness" — solved

At first glance the pattern only worked from 2023 (+125 $ over six years vs
+955 $ over four), which raised the suspicion of the Nasdaq rally. **It was not
that.**

| period | net R | **without swap** | the swap's price in R |
|---|---|---|---|
| 2017–2022 | +0.0117 | **+0.2569** | **+0.2452** |
| 2023–2026 | +0.1416 | **+0.2214** | +0.0798 |

Without swap the two eras are **identical** — the edge had been there since 2017.
What changed is the swap's burden in R: **0.449 → 0.047** (a tenfold drop). The
mechanical reason: the swap is roughly constant in currency, while the stop
distance scales with the **price**. UsaTec stood at ~5000 points in 2017 and at
~20000 today, so the risk per trade grew from 2.47 $ to 21.78 $.

## ⚠ Validated on UsaTec only

Measured on 16 instruments, it passed **only there**. The picture is nuanced,
though:

| sym | net R | gross R | cost | verdict |
|---|---|---|---|---|
| **UsaTec** | **+0.1821** | +0.2108 | 0.0288 | validated |
| UsaInd | +0.0986 | +0.1340 | 0.0354 | the signal works, the cost eats it |
| Usa500 | −0.0355 | +0.0304 | 0.0659 | the same, weaker |
| Ger40 | −0.0365 | +0.0133 | 0.0499 | the same, weaker |
| GOLD | −0.0447 | +0.0177 | 0.0624 | the same, weaker |
| UK100 · Euro50 · FX · BTC | negative | **negative** | — | the signal does not work either |

The gross is positive on five pairs, and the net ordering follows the **cost**.
So it is not hopeless on another pair — but only go live there **with your own
measurement**.

## What this module is NOT about

> The strategy is an **entry signal**. What happens AFTER the entry is not its
> business.

Breakeven, trailing and cost-cut belong to **risk reduction**
(`core/risk_reduction.py`, per pair). Measured on the UsaTec holdout:

| setting | n | R/trade | t | net $ |
|---|---|---|---|---|
| **`off` preset (BE + trailing), cost_cut off** | 711 | **+0.1058** | **+2.75** | **+954.8** |
| the same + cost_cut 24 | 667 | +0.0836 | +2.24 | +764.9 |
| trailing off + cost_cut 24 | 669 | +0.0937 | +2.06 | +861.9 |

**The pair's current setting is the best one** — there is nothing to change. And
one lesson: `cost_cut` helps **without trailing** and hurts **with trailing**.
Both close early; together it is already too much. *An exit parameter can only be
read in the light of the others.*

⚠ Risk reduction is stored **per PAIR**. Three strategies run on UsaTec and they
**share it** — an exit tuned for `trend_pullback` would have made the Bollinger
strategy 27% worse (+1148 $ → +833 $). Before you change anything here, measure
it on EVERY strategy running on the pair.

## Parameters

`strategy/config/trend_pullback.json`:

| key | default | what it sets |
|---|---|---|
| `stoch_period` · `stoch_d` | 14 · 3 | the M5 entry |
| `atr_ref_period` | 200 | the length of the M30 volatility threshold |
| `keltner_period` · `keltner_mult` | 14 · 2.0 | the H1 trend channel |
| `sl_atr_mult` · `tp_rr_ratio` | 1.5 · 2.0 | SL/TP from the M15 ATR |

The **timeframes** (M5 / M30 / H1) are **not parameters**: the search found it on
these, and the combination is valid together.

### The ATR definition — do not swap it

The module computes the ATR as a **simple moving average** of the true range, not
with Wilder smoothing — even though the latter is more standard. This is
**deliberate**: the validation was done with the simple average, and the two
definitions differ on **0.3%** of the signals. The „better" variant would be a
*different, untested* strategy. Only swap it with a re-validation.

## What we do not know yet

Every number is an out-of-sample **backtest**. The strategy **has not run on a
live market yet** — the only remaining test is time. It is worth starting small.

The `t = +2.94` is encouraging but not irrefutable, and the magnitude is
**~20–25 %/year** at 1 % risk per trade — not 1 % per day.

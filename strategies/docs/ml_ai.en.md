# ml_ai — machine learning (LightGBM / RandomForest)

Not rule-based: a **trained model** decides. For this strategy the „Opt" button
means **training**, not a parameter search.

## How it works

1. **Features** (`ml_features.compute_smc`) — SMC-like structural measures
   (imbalances, distance from earlier highs/lows, etc.), normalised **in
   points**.
2. **Labelling** (`ml_train.label_outcomes`) — the entry is at the bar's close,
   the outcome over the next ~32 bars; within the same bar the **SL has
   priority**.
3. **Threshold calibration** — on a separate slice, so the decision boundary does
   not fit the training data.

The SL method is **`atr`** (not `swing20`): the model's label is built on an
ATR-based stop.

> This came from a real bug: the shared execution path used `swing20` as the
> default, which is **wpr_sma's own**. So the engine traded with a 1.4–1.5×
> tighter stop than the prediction referred to — **the prediction was about a
> different trade than the one the engine executed**. (v1.66.3)

## ⚠️ Current status: NOT recommended live

According to the measurements the models **carry no usable signal**:

| metric | value | what it means |
|---|---|---|
| AUC | 0.483–0.576 | **0.5 = random** |
| threshold coverage | 0.1–4% | the high training hit rate rests on a few dozen samples |
| OOS profit factor | 0.25–1.46 | it collapses out of sample |

The training pipeline is **methodologically sound** (no look-ahead in the
labelling, the chronological split is correct, the threshold is calibrated on a
separate slice). **The features carry no signal for this label** — the training
is not the problem.

That is why it runs in **„signal only"** mode on every pair: it computes
everything, alerts and logs, but **no order goes out**. This way it can keep being
measured, without money.

## Model versioning

The saved package's stamp: `meta.feature_unit = "point"`.

`compute_smc` normalises the features with the pair's **point size**. When the
project switched from pips to points, this meant a **100× scale jump** in the
input on indices — models trained on the pip scale would have silently produced
meaningless predictions. That is why loading **checks the stamp** and **skips** an
outdated model with a clear message.

> It cannot be fixed by conversion: **retraining is required.**

## If you retrain

- The „Opt" button starts it (per pair).
- Training uses the **full history** (`optimizer.training.lookback_years`), not
  `train_start_date` — more data, better model.
- It is worth checking the AUC afterwards: if it stays around 0.5, the model did
  **not improve**, the noise just rearranged itself. A fluctuating PF is not
  evidence in itself.

## ⚠ Measurement 2026-08-08: the models MEMORISE, they do not learn

Split at the training boundary, same code, same spread:

| | trades | hit rate | PF | P&L |
|---|---|---|---|---|
| BTCUSD **in-sample** | 874 | **70.4%** | 8.04 | +15,524$ |
| BTCUSD **OOS** | 130 | **26.2%** | 0.78 | −80$ |
| EURUSD **in-sample** | 476 | **72.7%** | 10.51 | +2,769$ |
| EURUSD **OOS** | 45 | **22.2%** | 0.57 | −31$ |

The saved models' AUC is **0.87–0.92 on the training data and 0.48–0.56 on fresh
data** (BTCUSD long is 0.482 — *worse* than a coin flip). So the in-sample result
is not partial knowledge but **pure recall**: there is practically no real
discriminating power.

### Why the gap is this large — the structural reason

`_train_direction` trains **twice**:

1. The model learns on the first 80% of the train set, the threshold is
   calibrated on the remaining 20% (which the model did NOT see) → the threshold
   is honest.
2. Then the model **retrains on the whole train set**, including the calibration
   tail.

The **second model** goes into the saved package, but with the threshold
calibrated to the **first** one. The threshold therefore refers to a different
distribution than the one we apply it to: the final model is already nearly
perfect on its own training data, so the 0.81 threshold selects the *actual
winners* there. On fresh data — with an AUC of 0.5 — the same threshold is just
flipping a coin.

### What to take from this

- **An ml_ai backtest is only meaningful OUTSIDE the training window.** The
  Backtest window now says so (`core/training_overlap.py`).
- `threshold = 1.01` is the „never fire" marker. A direction gets it when the
  calibration finds no acceptable threshold — on the UI this **silently** means
  that pair/direction never trades. (For the state after v2.13.0, see below.)
- An AUC of ~0.5 means **there is no signal in the features** — no threshold and
  no retraining helps with that. Either different features are needed, or a
  different target variable.

## FIXED (v2.13.0): the threshold belongs to the model that serves it

The threshold and the AUC now come from **out-of-fold** probabilities over the
whole train set (`oof_proba`), with a **purge band**: the label looks `lookahead`
bars ahead, so the outcomes of adjacent rows overlap — without a band cut around
the fold, the training part would also see the test part's future.

The saved model still trains on the whole train set (fresh data matters), but the
threshold now refers to the distribution it will see in production.

New protection: an **AUC floor** (`optimizer.training.min_model_auc`, default
0.52). If the model cannot discriminate, any threshold's „good" hit rate is
purely a by-product of the search — `min_calibration_signals` protects from the
sample-size side, this one from the signal-source side.

### What it brought (2026-08-08, retraining on 11 pairs)

Honest calibration **switched off 17 of 22 directions by itself**. On fresh OOS
(2026-05-01 … 08-07):

| | trades | P&L |
|---|---|---|
| ml_ai, old calibration | 340 | **−827$** |
| ml_ai, honest calibration | 164 | **−208$** |
| `wpr_sma` over the same period | 1314 | **+2394$** |

> The fix **does not create an edge** — nor could it. It stops the strategy from
> sharpening itself on noise: the damage fell to a quarter, but the sign did not
> flip.

## v2.15.0: the threshold calibrates to EXPECTED VALUE

The old score (`wr² × coverage^0.15`) chased the **hit rate**, so it always chose
the narrowest, highest-rate tail — the active directions consistently stood at
42–100 signals, right at the minimum. Except it is not the hit rate that pays:

> **E[R] = wr × (RR+1) − 1** — at RR 2 the break-even is 33.3%.

A 35% threshold with many signals (+0.05R × 500 trades) is worth more than a 50%
one that speaks twenty times less often. The sample size enters through the
**Wilson lower bound** (10/20 → 0.299; 500/1000 → 0.469), and the score is the
conservative expected value × count. This way `min_signals` is only a coarse
floor, not the main protection.

`optimizer.training.calibration_z` (default **1.28** = 80% one-sided). This is a
risk-appetite decision, not a statistical statement: at 95% (z=1.96) 2 of 8
directions survived with 108 signals, at 80% 3 directions with 1815 signals.

### The OOS progression (2026-05-01 … 08-07)

| step | trades | P&L |
|---|---|---|
| starting point (old calibration, old label) | 340 | −827$ |
| out-of-fold calibration (v2.13.0) | 164 | −208$ |
| honest label + time features (v2.14.0) | 14 | +0$ |
| expected-value calibration (v2.15.0) | 21 | **+6$** |

> ⚠ **21 trades in three months.** The source of the loss is gone; profitability
> is NOT proven. That would need substantially more trades — either a valid
> threshold must be found on more pairs, or stronger features are needed.

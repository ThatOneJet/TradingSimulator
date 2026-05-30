# Trading Algorithm — Build Priority Roadmap

## Tier 1 — Build Now

| # | What | Why now |
|---|------|---------|
| 1 | True risk-per-trade sizing: `size = (equity × risk%) / stop_distance` | Fixes all asset classes at once — BTC auto-sizes 4-5× smaller than SPY without any per-asset rules |
| 2 | Hard asset-class exposure caps enforced in the buy loop | Currently advisory only — needs to actually block trades |
| 3 | Portfolio heat tracking: total active risk as % of equity across all open positions | Prevents cascading losses during correlated market moves |
| 4 | Total correlated cluster cap (5–8% rule) | `_compute_corr_factor` halves per-position but doesn't cap the cluster total |
| 5 | User-facing Trade Brief: regime explanation, MTF alignment, S/R levels, ATR range projection, stop suggestion | All data already exists — just needs a UI surface |
| 6 | Asset-class setup guides (contextual, per-symbol) | No new data needed, immediately useful for manual traders |

---

## Tier 2 — Next Phase

| # | What | Why here |
|---|------|---------|
| 7 | Market-specific strategy engines: separate logic for crypto, forex, equities, futures | Biggest algorithm quality jump — one model for everything is the core weakness |
| 8 | Confidence score 0–100 combining trend alignment, volume, structure, MTF, liquidity | Replaces blunt score tiers with continuous allocation scaling |
| 9 | Session & calendar rules: London/NY forex overlap, earnings blackouts, FOMC/CPI gates | Completes after-hours coverage plan |
| 10 | Adaptive stop distance by regime: 1.5 ATR normal, 2.5 ATR panic, tighter in ranges | Stops work but aren't regime-aware yet |
| 11 | Futures gate fix: `=F` symbols treated as 24/7 like crypto | Currently blocked after hours incorrectly |
| 12 | Futures contract sizing: notional-aware position sizing for ES/NQ/GC | Currently treated like a $5k stock |

---

## Tier 3 — After Tier 2

| # | What | Why here |
|---|------|---------|
| 13 | Performance self-optimization: auto-reduce strategy weight when decay detected | `performance_engine.py` tracks it — needs feedback loop wired in |
| 14 | Backtesting engine: historical replay with realistic fill model | Validates everything built in Tiers 1–2 before going live |
| 15 | Market breadth signals: advance-decline, TICK, TRIN into scoring engine | Needs breadth data feed built first |
| 16 | ML scoring layer: logistic regression trained on `sim_trades` outcomes | Needs 200+ trades of labeled regime data first |

---

## Tier 4 — Options (blocked on data confirmation)

| # | What | Blocker |
|---|------|---------|
| 17 | Enable Alpaca options chain feed | Must confirm this works with your key before building anything |
| 18 | IV rank / IV percentile engine | Needs 52-week IV history per underlying |
| 19 | Options risk engine: Greeks-based sizing, delta/gamma/theta limits | Needs live Greeks per contract |
| 20 | Strategy selection by regime: calls/debit spreads vs iron condors vs credit spreads | Depends on regime engine (already built) |
| 21 | Expiration & theta management, liquidity filters | Depends on live chain data |
| 22 | Portfolio-level Greeks dashboard | Depends on all above |
| 23 | Volatility event detection: earnings IV crush, FOMC expansion | Depends on earnings calendar API |
| 24 | Hedging layer: auto-SPY puts when portfolio beta exceeds threshold | Depends on portfolio analytics (already built) |
| 25 | Options analytics engine | Depends on performance_engine (already built) |

---

## Tier 5 — Self-Optimization & ML

| # | What | Why here |
|---|------|---------|
| 26 | Wire decay detection into automatic strategy weight reduction | `performance_engine.py` already detects decay — needs to feed back into `_adaptive_weights` |
| 27 | `model_trainer.py`: nightly retraining of signal weights from `sim_trades` outcomes | Needs 200+ labeled trades from Tiers 1–3 before meaningful training |
| 28 | ML scoring layer: logistic regression on trade outcomes → adjust per-signal weights | Coefficients replace hardcoded weight multipliers in `_adaptive_weights` |
| 29 | Anomaly detection: Z-score flagging when 2+ indicators are statistically unusual | Standalone, no training data needed — flags and reduces position size automatically |
| 30 | Signal attribution feedback: disable signals with negative expected value per regime | Based on `performance_engine.signal_attribution()` — closes the self-improvement loop |

---

## Tier 6 — Reinforcement Learning & Full Adaptive Framework

| # | What | Why here |
|---|------|---------|
| 31 | RL strategy adaptation: state=(regime, MTF, structure, portfolio), action=(strategy, size tier, timing), reward=P&L/drawdown | Requires Tier 5 data pipeline + backtesting environment as training ground |
| 32 | Full market breadth feed: advance-decline line, TICK, TRIN wired into scoring engine | Needs `breadth_engine.py` data feed built and populated first |
| 33 | Order flow / Level 2: bid-ask depth and size imbalance from Alpaca quotes feed | Requires Alpaca quotes stream integration in `alpaca_stream.py` |
| 34 | Hybrid consensus scoring: deterministic rules + ML probabilities + RL policy → single score | Final form of the scoring engine — all prior tiers must be stable |
| 35 | Cross-asset macro signals: gold/bond/dollar correlation shifts wired into regime engine | Extends regime detection beyond single-asset indicators to macro environment |

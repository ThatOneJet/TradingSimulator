# TradeSimulator — Updated Build Priorities

## Current System Status (Built & Running)
- ✅ Real-time streaming: Coinbase WS (crypto), Alpaca WS (equities), Polygon (forex), Finnhub (fallback)
- ✅ CandleEngine: live 1m/5m/15m/1h/1d bars with full indicators
- ✅ Event-triggered exits: position checks fire within 2s of bar close
- ✅ 30-second scan interval with 87-symbol universe
- ✅ Market regime detection (13 regimes, adaptive weights)
- ✅ Multi-timeframe bias engine (1h/5m/1m alignment)
- ✅ Market-specific strategy engines (crypto/forex/equity/futures)
- ✅ Confidence scoring (0–100), session liquidity factors
- ✅ Risk engine: risk-per-trade sizing, exposure caps, portfolio heat, cluster cap
- ✅ Profit protection: breakeven → min locked → half locked → trailing
- ✅ Bearish intelligence: continuous 0–10 score, gradual position trimming
- ✅ Circuit breakers: consecutive loss pause, drawdown halt, strategy disabling
- ✅ Anomaly detection: Z-score outlier flagging, auto-size reduction
- ✅ Options engine: Black-Scholes, IV rank, Greeks, chain fetcher
- ✅ RL engine: Q-table strategy adaptation
- ✅ Order flow: Alpaca bid/ask imbalance wired into scoring
- ✅ Macro engine: GLD/TLT/UUP/SPY cross-asset signals
- ✅ News engine: Finnhub sentiment, earnings calendar, FOMC/CPI gates
- ✅ Pattern engine: candlestick patterns, relative strength, momentum, volume climax
- ✅ 30-day history review: regime win rates, decay detection, threshold auto-adjustment
- ✅ Market heatmap: equities + crypto + forex + futures with real change %
- ✅ Performance engine: equity curve, regime P&L, signal attribution
- ✅ Backtesting engine: historical replay with realistic FillModel
- ✅ Model trainer: nightly weight retraining from sim_trades outcomes

---

## Tier A — High ROI, Already Have the Data (Days)

| # | What | Why | Effort |
|---|------|-----|--------|
| 1 | **Options flow wired into scoring** | PCR and unusual activity already fetched — just add the signal block in `_ai_score_detailed`. PCR < 0.7 = bullish +1.0, PCR > 1.2 = bearish -1.0 | Half day |
| 2 | **Daily/weekly S/R from structure engine** | `structure_engine.py` only sees 1m swing points — blind to daily/weekly resistance institutions trade from. Seed SwingDetector on yfinance daily bars. Weekly S/R weighted 3× intraday. | 1 day |
| 3 | **Sector rotation scoring** | Compare 5-day performance of XLK/XLF/XLE/XLV/XLI. Strongest sector gets +0.5 score boost for names within it, weakest -0.5. ETFs already in universe. | Half day |
| 4 | **Volume Profile (POC)** | Price-volume histogram from existing yfinance daily bars. Point of Control = magnetic level. Price above POC = bullish, below = bearish, at = chop. | 1 day |
| 5 | **Correlation break detection** | BTC/ETH normally r≈0.90. When they diverge >2σ — that's a signal. Flag both for closer scoring scrutiny. Use existing correlation infrastructure. | Half day |

---

## Tier B — Next Phase, Structured Data (1–2 Weeks)

| # | What | Why | Effort |
|---|------|-----|--------|
| 6 | **Intermarket systematic rules** | Codify: oil spike → energy +2/airlines -1.5; yield surge → tech -1.5/banks +1; gold ATH → reduce equity exposure. All prices already in universe. | 1 day |
| 7 | **Rule-based event detection** | Scan Finnhub headlines for trigger keywords → apply causal score maps (earnings beat/miss, Fed language, sector news). More reliable than LLM for known events. | 1 day |
| 8 | **COT reports for futures** | Free CFTC weekly data: commercial vs speculator positioning. Commercials max long + specs max short = major bottom. Powerful for GC=F, CL=F, ZB=F, forex futures. | 1 day |
| 9 | **Chart patterns on daily bars** | Extend pattern_engine.py: cup & handle, bull/bear flag, ascending triangle, double top/bottom on daily OHLCV. Already have the data. | 1–2 days |
| 10 | **Breadth divergence** | Extend breadth_engine.py: price new high + fewer stocks participating = warning. Price drops + A/D holds = bounce likely. Already polling 31 stocks. | Half day |

---

## Tier C — Medium Term (2–4 Weeks)

| # | What | Why | Effort |
|---|------|-----|--------|
| 11 | **LLM narrative engine (Claude Haiku)** | Novel events rules can't anticipate. Call Claude only when news exists AND symbol near threshold. Cache 60min. ~$0.58/day. Returns structured thesis stored in ai_log. | 2 days |
| 12 | **Seasonality patterns** | January effect, sell-in-May, pre-earnings drift (stocks drift up 5–10 days before reports), OpEx volatility. Pure calendar math, no new data. | 1 day |
| 13 | **Live PCR wired into options scoring** | Options chain already fetched. Compute put/call ratio live per symbol, add as real signal contribution rather than static gate. | 1 day |
| 14 | **Short interest integration** | FINRA bi-monthly data: heavy short interest + upward momentum = potential squeeze accelerant. Score boost for breakouts in heavily shorted names. | 1–2 days |
| 15 | **Earnings pre-drift positioning** | Stocks statistically drift up 5–10 days before earnings. Systematic pre-earnings long bias for quality setups. Earnings calendar already in news_engine.py. | Half day |

---

## Tier D — Ongoing / Long-Term

| # | What | Why |
|---|------|-----|
| 16 | **ML feedback loop operational** | model_trainer.py needs 200+ labeled trades to be meaningful. Accumulate data first, then activate. |
| 17 | **RL strategy adaptation active** | rl_engine.py built and learning. Needs trade history before its recommendations are reliable. |
| 18 | **Walk-forward backtesting** | Validate on out-of-sample periods. Run backtester.py across multiple regimes to find regime-specific edge. |
| 19 | **Full options trading loop** | Close the loop: evaluate → paper trade contracts → track Greeks → exit at 50% profit capture. |
| 20 | **Hybrid consensus scoring** | Blend rule-based (70%) + ML weights (20%) + RL policy (10%). Requires Tier C data to be meaningful. |

---

## What NOT to Build

| Item | Why |
|------|-----|
| HFT / co-location | Requires exchange membership + millions in infrastructure |
| Dark pool detection | Data not available at retail level |
| Satellite / alt data | $50k+/year, overkill for this scale |
| Full neural network | ML trainer covers 90% of the benefit with far less complexity |
| Market making | Different business — requires inventory and exchange access |

---

## Build Now: Tier A (4–5 days total)
All five use data already in the system. No new APIs, no new data sources, immediate P&L impact.

"""
BacktestEngine — historical replay of the AI scoring algorithm.

Replays daily OHLCV bars from yfinance through the scoring engine,
applies a realistic fill model (spread + slippage + latency), and
returns detailed performance metrics and regime-tagged trade log.

Usage:
    from backtester import BacktestEngine
    engine = BacktestEngine()
    result = engine.run('AAPL', '2024-01-01', '2024-12-31')
    print(result.metrics)
"""

import logging
import math
import statistics as _stats
from collections import defaultdict
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


# ── Fill model ─────────────────────────────────────────────────────────────────

@dataclass
class FillModel:
    spread_bps:   float = 5.0    # bid-ask spread in basis points (0.05%)
    slippage_bps: float = 2.0    # market impact in bps
    latency_ms:   int   = 250    # simulated execution delay (unused in daily sim, noted)
    commission:   float = 0.0    # per-share commission (sim = 0)

    def buy_price(self, mid: float, size: float, adv: float) -> float:
        """Realistic fill for a buy: mid + half-spread + slippage."""
        spread = mid * self.spread_bps / 10000
        impact = mid * self.slippage_bps / 10000 * min(1.0, size / max(adv * 0.001, 1))
        return round(mid + spread / 2 + impact, 4)

    def sell_price(self, mid: float, size: float, adv: float) -> float:
        """Realistic fill for a sell: mid - half-spread - slippage."""
        spread = mid * self.spread_bps / 10000
        impact = mid * self.slippage_bps / 10000 * min(1.0, size / max(adv * 0.001, 1))
        return round(mid - spread / 2 - impact, 4)


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class BacktestPosition:
    symbol:      str
    shares:      float
    entry_price: float
    entry_date:  str
    stop_price:  float
    target:      float
    regime:      str
    score:       float
    strategy:    str = ''


@dataclass
class BacktestTrade:
    symbol:      str
    side:        str        # 'buy' | 'sell'
    entry_date:  str
    exit_date:   str
    entry_price: float
    exit_price:  float
    shares:      float
    realized_pl: float
    pct_return:  float
    regime:      str
    score:       float
    exit_reason: str        # 'sell_signal' | 'stop_loss' | 'take_profit' | 'end_of_period'
    strategy:    str = ''


@dataclass
class BacktestResult:
    symbol:       str
    start_date:   str
    end_date:     str
    trades:       list       # list of BacktestTrade dicts
    equity_curve: list       # [{date, equity, daily_pl}]
    _metrics:     dict       # computed metrics dict (backing store)
    by_regime:    dict       # regime → {trades, wins, win_rate, avg_pl}

    @property
    def metrics(self) -> dict:
        return self._metrics


# ── Self-contained indicator helpers ──────────────────────────────────────────

def _ema(values: list, period: int) -> list:
    """Exponential moving average."""
    if not values:
        return []
    k = 2 / (period + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def _compute_bar_indicators(closes: list, highs: list, lows: list, volumes: list) -> dict:
    """
    Compute all indicators from lists of OHLCV data (oldest-first).
    Mirrors _compute_indicators in candle_engine.py applied to daily bars.
    Requires at least 2 values; works best with 30+.
    """
    n = len(closes)
    if n < 2:
        return {}

    last_c = closes[-1]

    # RSI (14)
    gains  = [max(closes[i] - closes[i - 1], 0) for i in range(1, n)]
    losses = [max(closes[i - 1] - closes[i], 0) for i in range(1, n)]
    if len(gains) >= 14:
        avg_g = sum(gains[-14:]) / 14
        avg_l = sum(losses[-14:]) / 14
        rsi = round(100 - (100 / (1 + avg_g / avg_l)) if avg_l else 100.0, 2)
    else:
        rsi = 50.0

    # MACD (12, 26, 9)
    macd_cross = 'neutral'
    macd_value = 0.0
    macd_signal_value = 0.0
    if n >= 27:
        ema12 = _ema(closes, 12)
        ema26 = _ema(closes, 26)
        macd_vals = [ema12[i] - ema26[i] for i in range(25, n)]
        sig_vals  = _ema(macd_vals, 9)
        last_m = macd_vals[-1]
        last_s = sig_vals[-1]
        prev_m = macd_vals[-2] if len(macd_vals) > 1 else last_m
        prev_s = sig_vals[-2]  if len(sig_vals)  > 1 else last_s
        curr_h = last_m - last_s
        prev_h = prev_m - prev_s
        if   curr_h > 0 and prev_h <= 0: macd_cross = 'bullish_cross'
        elif curr_h < 0 and prev_h >= 0: macd_cross = 'bearish_cross'
        elif curr_h > 0:                 macd_cross = 'bullish'
        else:                            macd_cross = 'bearish'
        macd_value = round(last_m, 6)
        macd_signal_value = round(last_s, 6)

    # Stochastic (14)
    stoch_k = 50.0
    if n >= 14:
        stoch_k_arr = []
        for i in range(13, n):
            ph = max(highs[i - 13:i + 1])
            pl = min(lows[i - 13:i + 1])
            stoch_k_arr.append(((closes[i] - pl) / (ph - pl) * 100) if ph > pl else 50.0)
        stoch_k = stoch_k_arr[-1] if stoch_k_arr else 50.0

    # Bollinger Bands (20, 2σ)
    bb_pos = 'unknown'
    bb_mean = last_c
    bb_upper = last_c
    bb_lower = last_c
    if n >= 20:
        w    = closes[-20:]
        mean = sum(w) / 20
        std  = (sum((c - mean) ** 2 for c in w) / 20) ** 0.5
        bb_upper = mean + 2 * std
        bb_lower = mean - 2 * std
        bb_mean  = mean
        bw       = bb_upper - bb_lower
        if   bw < last_c * 0.03:     bb_pos = 'squeeze'
        elif last_c >= bb_upper * 0.995: bb_pos = 'overbought'
        elif last_c <= bb_lower * 1.005: bb_pos = 'oversold'
        elif last_c > mean:              bb_pos = 'upper_half'
        else:                            bb_pos = 'lower_half'

    # VWAP (rolling 20-bar typical-price × volume)
    vwap_signal = ''
    if n >= 20:
        tp  = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(n - 20, n)]
        vol = volumes[n - 20:n]
        tv  = sum(vol)
        if tv > 0:
            vwap_val = sum(p * v for p, v in zip(tp, vol)) / tv
            vwap_signal = 'above' if last_c > vwap_val else 'below'

    # Volume signal
    last_vol = volumes[-1] if volumes else 0
    avg_vol  = sum(volumes[-20:]) / min(20, len(volumes)) if volumes else 0
    vol_ratio = round(last_vol / avg_vol, 2) if avg_vol > 0 else 1.0
    price_chg = last_c - closes[-2] if n >= 2 else 0
    if   vol_ratio >= 1.5: vol_signal = 'high_up' if price_chg > 0 else 'high_down'
    elif vol_ratio <= 0.5: vol_signal = 'low'
    else:                  vol_signal = 'normal'

    # Trend slope (linear regression, 20 bars)
    last20 = closes[-20:] if n >= 20 else closes
    sz     = len(last20)
    x_mean = (sz - 1) / 2
    y_mean = sum(last20) / sz
    num    = sum((i - x_mean) * (last20[i] - y_mean) for i in range(sz))
    denom  = sum((i - x_mean) ** 2 for i in range(sz))
    slope  = num / denom if denom else 0
    trend  = 'up' if slope > 0.05 else 'down' if slope < -0.05 else 'sideways'

    # ATR (14)
    tr_vals = [max(highs[i] - lows[i],
                   abs(highs[i] - closes[i - 1]),
                   abs(lows[i]  - closes[i - 1]))
               for i in range(1, n)]
    atr = round(sum(tr_vals[-14:]) / 14, 6) if len(tr_vals) >= 14 else last_c * 0.02

    # EMA50
    ema50_arr = _ema(closes, min(50, n))
    ema50     = ema50_arr[-1]

    slope_pct = round((slope / last_c) * 100, 4) if last_c else 0.0

    # ADX approximation
    adx_val = 0.0
    if n >= 15:
        plus_dm  = [max(highs[i] - highs[i - 1], 0)
                    if (highs[i] - highs[i - 1]) > (lows[i - 1] - lows[i]) else 0
                    for i in range(1, n)]
        minus_dm = [max(lows[i - 1] - lows[i], 0)
                    if (lows[i - 1] - lows[i]) > (highs[i] - highs[i - 1]) else 0
                    for i in range(1, n)]
        atr14  = sum(tr_vals[-14:]) / 14 if len(tr_vals) >= 14 else 1
        pdm14  = sum(plus_dm[-14:]) / 14
        mdm14  = sum(minus_dm[-14:]) / 14
        pdi    = 100 * pdm14 / atr14 if atr14 else 0
        mdi    = 100 * mdm14 / atr14 if atr14 else 0
        dx     = abs(pdi - mdi) / (pdi + mdi) * 100 if (pdi + mdi) else 0
        adx_val = round(dx, 1)

    return {
        'last_price':        last_c,
        'rsi':               rsi,
        'macd_cross':        macd_cross,
        'macd_value':        macd_value,
        'macd_signal_value': macd_signal_value,
        'stoch_k_val':       round(stoch_k, 2),
        'stoch_d_val':       round(stoch_k, 2),
        'bb_position':       bb_pos,
        'vwap_signal':       vwap_signal,
        'volume_signal':     vol_signal,
        'volume_ratio':      vol_ratio,
        'trend':             trend,
        'slope':             round(slope, 6),
        'slope_pct':         slope_pct,
        'atr':               atr,
        'atr_pct':           round(atr / last_c * 100, 2) if last_c else 2.0,
        'ema50':             round(ema50, 4),
        'adx':               adx_val,
    }


# ── Regime classification (mirrors _classify_market_state in app.py) ──────────

def _classify_regime(ind: dict) -> str:
    """Classify market regime from indicator dict. Self-contained replica."""
    rsi     = float(ind.get('rsi', 50) or 50)
    trend   = ind.get('trend', 'sideways') or 'sideways'
    bb_pos  = ind.get('bb_position', '') or ''
    vol_sig = ind.get('volume_signal', '') or ''
    atr_pct = float(ind.get('atr_pct', 2.0) or 2.0)
    adx     = float(ind.get('adx', 0) or 0)
    macd_x  = ind.get('macd_cross', '') or ''
    stoch   = float(ind.get('stoch_k_val', 50) or 50)
    vol_r   = float(ind.get('volume_ratio', 1.0) or 1.0)

    # Panic: extreme oversold + high volatility + heavy selling volume
    if rsi < 25 and atr_pct > 3.5 and vol_sig == 'high_down':
        return 'panic'
    # Extreme overbought
    if rsi > 80 and stoch > 85 and bb_pos == 'overbought':
        return 'overbought_extreme'
    # Extreme oversold (not panic — no volume spike)
    if rsi < 22 and stoch < 20:
        return 'oversold_extreme'
    # Breakout: price at BB upper + volume spike + bullish momentum
    if bb_pos == 'overbought' and vol_sig == 'high_up' and 'bullish' in macd_x:
        return 'breakout'
    # Trending
    if adx > 20 and trend == 'up':
        return 'trending_up'
    if adx > 20 and trend == 'down':
        return 'trending_down'
    # Accumulation
    if 28 <= rsi <= 48 and trend in ('sideways', 'up') and vol_sig in ('high_up', 'normal'):
        return 'accumulation'
    # Ranging / BB squeeze
    if bb_pos == 'squeeze' or (trend == 'sideways' and adx < 15):
        return 'ranging'
    # Euphoric
    if rsi > 85 and atr_pct > 2.0 and vol_sig in ('high_up', 'normal'):
        return 'euphoric'
    # Distribution
    if 50 <= rsi <= 68 and vol_sig == 'high_down' and trend == 'sideways':
        return 'distribution'
    # News-driven
    if vol_sig in ('high_up', 'high_down') and vol_r >= 3.0:
        return 'news_driven'
    # Mild trends
    if trend == 'up':   return 'mild_uptrend'
    if trend == 'down': return 'mild_downtrend'
    return 'neutral'


def _adaptive_weights(regime: str) -> dict:
    """Return per-indicator weight multipliers. Mirrors _adaptive_weights in app.py."""
    base = {'rsi': 1.0, 'macd': 1.0, 'stoch': 1.0, 'bb': 1.0,
            'volume': 1.0, 'vwap': 1.0, 'trend': 1.0}
    if regime in ('trending_up', 'trending_down'):
        return {**base, 'macd': 1.4, 'trend': 1.4, 'rsi': 0.7, 'bb': 0.7}
    if regime in ('ranging', 'accumulation'):
        return {**base, 'rsi': 1.4, 'bb': 1.4, 'stoch': 1.2, 'macd': 0.6}
    if regime in ('panic', 'oversold_extreme'):
        return {**base, 'rsi': 0.5, 'macd': 0.5, 'stoch': 0.5, 'bb': 0.5,
                'volume': 0.5, 'trend': 0.5}
    if regime == 'breakout':
        return {**base, 'volume': 1.5, 'macd': 1.3, 'trend': 1.2, 'rsi': 0.8}
    if regime == 'euphoric':
        return {**base, 'rsi': 1.5, 'stoch': 1.3, 'bb': 1.3, 'macd': 0.6, 'trend': 0.5}
    if regime == 'distribution':
        return {**base, 'volume': 1.5, 'macd': 1.2, 'rsi': 0.8, 'trend': 0.7}
    if regime == 'news_driven':
        return {**base, 'volume': 2.0, 'macd': 0.4, 'rsi': 0.3, 'stoch': 0.3, 'bb': 0.4}
    return base


def _regime_stop_multiplier(regime: str) -> tuple:
    """Return (stop_mult, target_mult). Mirrors _regime_stop_multiplier in app.py."""
    if regime in ('panic', 'news_driven', 'euphoric'):
        return 2.5, 4.0
    if regime == 'breakout':
        return 2.0, 3.5
    if regime in ('ranging', 'accumulation', 'oversold_extreme', 'overbought_extreme'):
        return 1.0, 1.8
    if regime in ('trending_up', 'trending_down'):
        return 1.5, 3.0
    return 1.5, 2.5


# ── Standalone scoring ─────────────────────────────────────────────────────────

def _score_bar(ind: dict) -> tuple:
    """
    Returns (score, regime). Mirrors _ai_score_detailed logic from app.py,
    but self-contained — no MTF bias, no what-changed tracking.
    Score in range roughly -10 to +10.
    """
    rsi      = float(ind.get('rsi', 50) or 50)
    macd_x   = ind.get('macd_cross', '') or ''
    stoch_k  = float(ind.get('stoch_k_val', 50) or 50)
    vol_sig  = ind.get('volume_signal', '') or ''
    vol_r    = float(ind.get('volume_ratio', 1.0) or 1.0)
    bb_pos   = ind.get('bb_position', '') or ''
    vwap_sig = ind.get('vwap_signal', '') or ''
    trend    = ind.get('trend', '') or ''
    slope    = float(ind.get('slope', 0) or 0)
    price    = float(ind.get('last_price', 0) or 0)
    ema50    = float(ind.get('ema50', price) or price)

    regime  = _classify_regime(ind)
    weights = _adaptive_weights(regime)

    # Trend gate: RSI/BB buy signals at 40% weight in confirmed downtrend
    trend_penalty = 0.4 if slope < -0.05 else 1.0

    score = 0.0

    # RSI contribution
    if   rsi <= 20: raw = 3.0
    elif rsi <= 28: raw = 2.0
    elif rsi <= 38: raw = 1.0
    elif rsi >= 80: raw = -3.0
    elif rsi >= 72: raw = -2.0
    elif rsi >= 62: raw = -1.0
    else:           raw = 0.0
    score += raw * weights['rsi'] * (trend_penalty if raw > 0 else 1.0)

    # MACD contribution
    if   macd_x == 'bullish_cross': raw = 2.0
    elif macd_x == 'bullish':       raw = 1.0
    elif macd_x == 'bearish_cross': raw = -2.0
    elif macd_x == 'bearish':       raw = -1.0
    else:                           raw = 0.0
    score += raw * weights['macd']

    # Stochastic contribution
    if   stoch_k <= 15: raw = 1.5
    elif stoch_k <= 25: raw = 1.0
    elif stoch_k >= 85: raw = -1.5
    elif stoch_k >= 75: raw = -1.0
    else:               raw = 0.0
    score += raw * weights['stoch'] * (trend_penalty if raw > 0 else 1.0)

    # Volume contribution
    vol_mult = min(vol_r / 1.5, 1.5) if vol_r > 1.5 else 1.0
    if   vol_sig == 'high_up':   raw = 2.0 * vol_mult
    elif vol_sig == 'high_down': raw = -2.0 * vol_mult
    elif vol_sig == 'low':
        score *= 0.65  # low-volume dampen
        raw = 0.0
    else:
        raw = 0.0
    if vol_sig not in ('low', ''):
        score += raw * weights['volume']

    # BB contribution
    if   bb_pos == 'oversold':   raw = 1.5
    elif bb_pos == 'lower_half': raw = 0.5
    elif bb_pos == 'overbought': raw = -1.5
    elif bb_pos == 'upper_half': raw = -0.5
    else:                        raw = 0.0
    score += raw * weights['bb'] * (trend_penalty if raw > 0 else 1.0)

    # VWAP contribution
    if   vwap_sig == 'above': raw = 1.0
    elif vwap_sig == 'below': raw = -1.0
    else:                     raw = 0.0
    score += raw * weights['vwap']

    # Trend contribution
    if   trend == 'up':   raw = 1.5
    elif trend == 'down': raw = -1.5
    else:                 raw = 0.0
    score += raw * weights['trend']

    # EMA50 falling-knife gate
    if ema50 > 0 and price < ema50 * 0.85:
        score = min(score, 1.0)

    return round(score, 2), regime


# ── Main engine ────────────────────────────────────────────────────────────────

class BacktestEngine:
    """Historical replay of the AI scoring algorithm on daily OHLCV data."""

    WARMUP_BARS = 30   # bars before first trade is allowed

    def __init__(self, fill_model: FillModel = None, initial_capital: float = 100_000.0):
        self.fill    = fill_model or FillModel()
        self.capital = initial_capital

    def run(self, symbol: str, start_date: str, end_date: str,
            portfolio_size: float = None) -> BacktestResult:
        """
        Replay algorithm on historical daily OHLCV for symbol.

        Process per bar:
        1. Compute rolling indicators (RSI, MACD, BB, volume, trend, ATR)
        2. Score using _score_bar (RSI, MACD, BB, volume, trend)
        3. Apply FillModel on entry / exit
        4. Track position, stop, trailing stop, target
        5. Record equity curve daily
        """
        import yfinance as yf

        symbol = symbol.upper()
        log.info("[BACKTEST] Fetching %s  %s → %s", symbol, start_date, end_date)

        hist = yf.download(symbol, start=start_date, end=end_date,
                           interval='1d', auto_adjust=True, progress=False)
        if hist.empty or len(hist) < self.WARMUP_BARS:
            raise ValueError(f'Insufficient history for {symbol}: got {len(hist)} bars, need {self.WARMUP_BARS}')

        # Flatten multi-level columns if present (yfinance >= 0.2 behaviour)
        if hasattr(hist.columns, 'levels'):
            hist.columns = hist.columns.get_level_values(0)

        # Extract arrays (oldest first)
        dates   = [str(ts.date()) for ts in hist.index]
        opens   = list(hist['Open'].astype(float))
        highs   = list(hist['High'].astype(float))
        lows    = list(hist['Low'].astype(float))
        closes  = list(hist['Close'].astype(float))
        volumes = list(hist['Volume'].astype(float))

        capital      = portfolio_size if portfolio_size is not None else self.capital
        equity       = capital
        position     = None          # BacktestPosition or None
        trades       = []            # list of dicts
        equity_curve = []            # list of {date, equity, daily_pl}

        log.info("[BACKTEST] %s  %d bars loaded, starting replay...", symbol, len(dates))

        for i in range(len(dates)):
            date   = dates[i]
            close  = closes[i]
            high   = highs[i]
            low    = lows[i]
            volume = volumes[i]

            # Mark equity at open of bar — we'll update at close
            prev_equity = equity

            # --- Check stops / target on existing position (intraday high/low) ---
            if position is not None:
                # Stop hit? (intraday low breaches stop)
                if low <= position.stop_price:
                    exit_price = self.fill.sell_price(position.stop_price, position.shares,
                                                      max(volume, 1))
                    realized   = (exit_price - position.entry_price) * position.shares
                    equity    += realized
                    hold_days  = _date_diff(position.entry_date, date)
                    pct_ret    = (exit_price / position.entry_price - 1) if position.entry_price else 0
                    trades.append({
                        'symbol':      symbol,
                        'side':        'sell',
                        'entry_date':  position.entry_date,
                        'exit_date':   date,
                        'entry_price': position.entry_price,
                        'exit_price':  exit_price,
                        'shares':      position.shares,
                        'realized_pl': round(realized, 4),
                        'pct_return':  round(pct_ret, 6),
                        'regime':      position.regime,
                        'score':       position.score,
                        'exit_reason': 'stop_loss',
                        'strategy':    position.strategy,
                        'hold_days':   hold_days,
                    })
                    log.debug("[BACKTEST] %s  STOP  @ %.4f  pl=%.2f", date, exit_price, realized)
                    position = None

                # Target hit? (intraday high breaches target)
                elif high >= position.target:
                    exit_price = self.fill.sell_price(position.target, position.shares,
                                                      max(volume, 1))
                    realized   = (exit_price - position.entry_price) * position.shares
                    equity    += realized
                    hold_days  = _date_diff(position.entry_date, date)
                    pct_ret    = (exit_price / position.entry_price - 1) if position.entry_price else 0
                    trades.append({
                        'symbol':      symbol,
                        'side':        'sell',
                        'entry_date':  position.entry_date,
                        'exit_date':   date,
                        'entry_price': position.entry_price,
                        'exit_price':  exit_price,
                        'shares':      position.shares,
                        'realized_pl': round(realized, 4),
                        'pct_return':  round(pct_ret, 6),
                        'regime':      position.regime,
                        'score':       position.score,
                        'exit_reason': 'take_profit',
                        'strategy':    position.strategy,
                        'hold_days':   hold_days,
                    })
                    log.debug("[BACKTEST] %s  TARGET @ %.4f  pl=%.2f", date, exit_price, realized)
                    position = None

            # --- Compute indicators for bar i (use all bars up to and including i) ---
            if i < self.WARMUP_BARS:
                # Still in warmup — no trades, just track equity flat
                equity_curve.append({'date': date, 'equity': round(equity, 4),
                                     'daily_pl': 0.0})
                continue

            window_start = max(0, i - 60)
            c_win = closes[window_start:i + 1]
            h_win = highs[window_start:i + 1]
            l_win = lows[window_start:i + 1]
            v_win = volumes[window_start:i + 1]

            ind = _compute_bar_indicators(c_win, h_win, l_win, v_win)
            if not ind:
                equity_curve.append({'date': date, 'equity': round(equity, 4),
                                     'daily_pl': round(equity - prev_equity, 4)})
                continue

            score, regime = _score_bar(ind)
            atr = float(ind.get('atr') or (close * 0.02))
            stop_m, tgt_m = _regime_stop_multiplier(regime)

            # --- Position management ---
            if position is not None:
                # Update trailing stop (only tighten upward as price rises)
                new_stop = close - stop_m * atr
                if new_stop > position.stop_price:
                    position.stop_price = round(new_stop, 4)

                # Exit on sell signal
                if score <= -2.5:
                    exit_price = self.fill.sell_price(close, position.shares, max(volume, 1))
                    realized   = (exit_price - position.entry_price) * position.shares
                    equity    += realized
                    hold_days  = _date_diff(position.entry_date, date)
                    pct_ret    = (exit_price / position.entry_price - 1) if position.entry_price else 0
                    trades.append({
                        'symbol':      symbol,
                        'side':        'sell',
                        'entry_date':  position.entry_date,
                        'exit_date':   date,
                        'entry_price': position.entry_price,
                        'exit_price':  exit_price,
                        'shares':      position.shares,
                        'realized_pl': round(realized, 4),
                        'pct_return':  round(pct_ret, 6),
                        'regime':      position.regime,
                        'score':       position.score,
                        'exit_reason': 'sell_signal',
                        'strategy':    position.strategy,
                        'hold_days':   hold_days,
                    })
                    log.debug("[BACKTEST] %s  SELL_SIG @ %.4f  pl=%.2f", date, exit_price, realized)
                    position = None

            else:
                # No position — check for buy signal
                if score >= 2.5:
                    # Size: risk 2% of equity per trade, stop is 1.5× ATR below entry
                    risk_dollars = equity * 0.02
                    stop_dist    = stop_m * atr
                    if stop_dist <= 0:
                        stop_dist = close * 0.02
                    entry_price = self.fill.buy_price(close, 1, max(volume, 1))
                    shares_raw  = risk_dollars / stop_dist
                    # Cap to 20% of equity per position
                    max_shares  = (equity * 0.20) / entry_price if entry_price > 0 else 0
                    shares      = round(min(shares_raw, max_shares), 4)
                    if shares <= 0 or entry_price <= 0:
                        equity_curve.append({'date': date, 'equity': round(equity, 4),
                                             'daily_pl': round(equity - prev_equity, 4)})
                        continue

                    stop_price = round(entry_price - stop_m * atr, 4)
                    target     = round(entry_price + tgt_m * atr, 4)

                    # Deduct entry cost from equity (unrealized — will be realized on exit)
                    # (In this model equity tracks capital; unrealized not separately tracked)
                    position = BacktestPosition(
                        symbol=symbol,
                        shares=shares,
                        entry_price=entry_price,
                        entry_date=date,
                        stop_price=stop_price,
                        target=target,
                        regime=regime,
                        score=score,
                        strategy='',
                    )
                    log.debug("[BACKTEST] %s  BUY @ %.4f  stop=%.4f  tgt=%.4f  score=%.2f  regime=%s",
                              date, entry_price, stop_price, target, score, regime)

            # Track unrealized mark-to-market in equity curve
            if position is not None:
                mtm_equity = equity + (close - position.entry_price) * position.shares
            else:
                mtm_equity = equity

            daily_pl = round(mtm_equity - prev_equity, 4)
            equity_curve.append({'date': date, 'equity': round(mtm_equity, 4),
                                 'daily_pl': daily_pl})

        # --- End of period: close any open position ---
        if position is not None and closes:
            close      = closes[-1]
            date       = dates[-1]
            volume     = volumes[-1]
            exit_price = self.fill.sell_price(close, position.shares, max(volume, 1))
            realized   = (exit_price - position.entry_price) * position.shares
            equity    += realized
            hold_days  = _date_diff(position.entry_date, date)
            pct_ret    = (exit_price / position.entry_price - 1) if position.entry_price else 0
            trades.append({
                'symbol':      symbol,
                'side':        'sell',
                'entry_date':  position.entry_date,
                'exit_date':   date,
                'entry_price': position.entry_price,
                'exit_price':  exit_price,
                'shares':      position.shares,
                'realized_pl': round(realized, 4),
                'pct_return':  round(pct_ret, 6),
                'regime':      position.regime,
                'score':       position.score,
                'exit_reason': 'end_of_period',
                'strategy':    position.strategy,
                'hold_days':   hold_days,
            })
            # Update last equity_curve entry to reflect closed position
            if equity_curve:
                equity_curve[-1]['equity']   = round(equity, 4)
                equity_curve[-1]['daily_pl'] = round(
                    equity_curve[-1]['equity'] -
                    (equity_curve[-2]['equity'] if len(equity_curve) > 1 else capital), 4)
            position = None

        log.info("[BACKTEST] %s  done — %d trades", symbol, len(trades))

        metrics   = self._compute_metrics(trades, equity_curve, capital)
        by_regime = self._by_regime(trades)

        return BacktestResult(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            trades=trades,
            equity_curve=equity_curve,
            _metrics=metrics,
            by_regime=by_regime,
        )

    # ── Metrics ────────────────────────────────────────────────────────────────

    def _compute_metrics(self, trades: list, equity_curve: list,
                         initial_capital: float) -> dict:
        if not trades:
            return {'total_trades': 0, 'win_rate': 0, 'total_return': 0,
                    'sharpe': 0, 'max_drawdown': 0, 'profit_factor': 0,
                    'avg_win': 0, 'avg_loss': 0, 'avg_hold_days': 0}

        wins   = [t for t in trades if t['realized_pl'] > 0]
        losses = [t for t in trades if t['realized_pl'] <= 0]

        final_equity  = equity_curve[-1]['equity'] if equity_curve else initial_capital
        total_return  = (final_equity - initial_capital) / initial_capital

        # Sharpe: annualized daily return / daily std
        daily_rets = [e['daily_pl'] / (e['equity'] - e['daily_pl'])
                      for e in equity_curve
                      if e['equity'] > e['daily_pl'] > 0]
        sharpe = 0.0
        if daily_rets and len(daily_rets) > 1:
            avg = sum(daily_rets) / len(daily_rets)
            std = _stats.stdev(daily_rets)
            sharpe = round((avg / std * (252 ** 0.5)) if std > 0 else 0, 2)

        # Max drawdown
        peak   = initial_capital
        max_dd = 0.0
        for e in equity_curve:
            peak  = max(peak, e['equity'])
            dd    = (peak - e['equity']) / peak
            max_dd = max(max_dd, dd)

        profit_factor = (
            sum(t['realized_pl'] for t in wins) /
            abs(sum(t['realized_pl'] for t in losses))
            if losses else float('inf')
        )

        return {
            'total_trades':  len(trades),
            'win_rate':      round(len(wins) / len(trades), 3) if trades else 0,
            'total_return':  round(total_return, 4),
            'sharpe':        sharpe,
            'max_drawdown':  round(max_dd, 4),
            'profit_factor': round(profit_factor, 2),
            'avg_win':       round(sum(t['realized_pl'] for t in wins)   / len(wins),   2) if wins   else 0,
            'avg_loss':      round(sum(t['realized_pl'] for t in losses) / len(losses), 2) if losses else 0,
            'avg_hold_days': round(sum(t.get('hold_days', 1) for t in trades) / len(trades), 1) if trades else 0,
        }

    def _by_regime(self, trades: list) -> dict:
        groups = defaultdict(list)
        for t in trades:
            groups[t['regime']].append(t)
        result = {}
        for regime, ts in groups.items():
            wins = [t for t in ts if t['realized_pl'] > 0]
            result[regime] = {
                'trades':   len(ts),
                'wins':     len(wins),
                'win_rate': round(len(wins) / len(ts), 3),
                'avg_pl':   round(sum(t['realized_pl'] for t in ts) / len(ts), 2),
                'total_pl': round(sum(t['realized_pl'] for t in ts), 2),
            }
        return result


# ── Helpers ────────────────────────────────────────────────────────────────────

def _date_diff(date_a: str, date_b: str) -> int:
    """Return calendar days between two 'YYYY-MM-DD' strings."""
    from datetime import date as _date
    try:
        a = _date.fromisoformat(date_a[:10])
        b = _date.fromisoformat(date_b[:10])
        return abs((b - a).days)
    except Exception:
        return 1


# ── Module-level convenience ───────────────────────────────────────────────────

def run_backtest(symbol: str, start: str, end: str,
                 capital: float = 100_000) -> dict:
    """Convenience function returning a JSON-serializable dict."""
    engine = BacktestEngine(initial_capital=capital)
    result = engine.run(symbol, start, end)
    return {
        'symbol':       result.symbol,
        'start':        result.start_date,
        'end':          result.end_date,
        'trades':       result.trades,
        'equity_curve': result.equity_curve,
        'metrics':      result.metrics,
        'by_regime':    result.by_regime,
    }

"""
CandleEngine — converts raw ticks into OHLCV candles and computes indicators.

Subscribes to tick:* on the event bus.
On interval boundary close, publishes bar:{symbol}:{interval} with indicators attached.

Indicators computed on each closed bar:
  RSI(14), MACD(12,26,9), Bollinger Bands(20,2σ), ATR(14), VWAP(session), slope(20)

Replaces yfinance calls for symbols that are actively streaming.
"""

import logging
import math
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

INTERVALS_SECONDS = {
    '1s':  1,
    '1m':  60,
    '5m':  300,
    '15m': 900,
    '1h':  3600,
    '1d':  86400,
}

CANDLE_HISTORY = 120  # bars to keep per (symbol, interval) for indicator computation


@dataclass
class _OHLCV:
    open:   float
    high:   float
    low:    float
    close:  float
    volume: float
    ts:     float       # bar-open Unix timestamp
    vwap_num: float = 0.0   # cumulative price*volume
    vwap_den: float = 0.0   # cumulative volume
    tick_count: int = 0
    closed: bool = False


def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2 / (period + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def _compute_indicators(bars: deque) -> dict:
    """Compute all indicators from a deque of closed _OHLCV bars (oldest first)."""
    n = len(bars)
    if n < 2:
        return {}

    closes  = [b.close  for b in bars]
    highs   = [b.high   for b in bars]
    lows    = [b.low    for b in bars]
    volumes = [b.volume for b in bars]
    last_c  = closes[-1]

    # RSI (14)
    gains  = [max(closes[i] - closes[i-1], 0) for i in range(1, n)]
    losses = [max(closes[i-1] - closes[i], 0) for i in range(1, n)]
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
        last_m = macd_vals[-1]; last_s = sig_vals[-1]
        prev_m = macd_vals[-2] if len(macd_vals) > 1 else last_m
        prev_s = sig_vals[-2]  if len(sig_vals)  > 1 else last_s
        curr_h = last_m - last_s; prev_h = prev_m - prev_s
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
            ph = max(highs[i-13:i+1]); pl = min(lows[i-13:i+1])
            stoch_k_arr.append(((closes[i]-pl)/(ph-pl)*100) if ph > pl else 50.0)
        stoch_k = stoch_k_arr[-1] if stoch_k_arr else 50.0

    # Bollinger Bands (20, 2σ)
    bb_pos = 'unknown'
    if n >= 20:
        w = closes[-20:]; mean = sum(w) / 20
        std = (sum((c - mean) ** 2 for c in w) / 20) ** 0.5
        bb_u = mean + 2 * std; bb_l = mean - 2 * std
        bw   = bb_u - bb_l
        if   bw < last_c * 0.03:     bb_pos = 'squeeze'
        elif last_c >= bb_u * 0.995: bb_pos = 'overbought'
        elif last_c <= bb_l * 1.005: bb_pos = 'oversold'
        elif last_c > mean:          bb_pos = 'upper_half'
        else:                        bb_pos = 'lower_half'

    # VWAP (rolling 20-bar typical-price × volume)
    vwap_signal = ''
    if n >= 20:
        tp  = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(n-20, n)]
        vol = volumes[n-20:n]
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
    sz = len(last20); x_mean = (sz - 1) / 2; y_mean = sum(last20) / sz
    num   = sum((i - x_mean) * (last20[i] - y_mean) for i in range(sz))
    denom = sum((i - x_mean) ** 2 for i in range(sz))
    slope = num / denom if denom else 0
    trend = 'up' if slope > 0.05 else 'down' if slope < -0.05 else 'sideways'

    # ATR (14)
    tr_vals = [max(highs[i] - lows[i],
                   abs(highs[i] - closes[i-1]),
                   abs(lows[i]  - closes[i-1]))
               for i in range(1, n)]
    atr = round(sum(tr_vals[-14:]) / 14, 6) if len(tr_vals) >= 14 else last_c * 0.02

    # EMA50
    ema50_arr = _ema(closes, min(50, n))
    ema50 = ema50_arr[-1]

    slope_pct = round((slope / last_c) * 100, 4) if last_c else 0.0

    # ADX approximation
    adx_val = 0.0
    if n >= 15:
        plus_dm  = [max(highs[i]-highs[i-1], 0)
                    if (highs[i]-highs[i-1]) > (lows[i-1]-lows[i]) else 0
                    for i in range(1, n)]
        minus_dm = [max(lows[i-1]-lows[i], 0)
                    if (lows[i-1]-lows[i]) > (highs[i]-highs[i-1]) else 0
                    for i in range(1, n)]
        atr14 = sum(tr_vals[-14:]) / 14 if len(tr_vals) >= 14 else 1
        pdm14 = sum(plus_dm[-14:]) / 14; mdm14 = sum(minus_dm[-14:]) / 14
        pdi = 100 * pdm14 / atr14 if atr14 else 0
        mdi = 100 * mdm14 / atr14 if atr14 else 0
        dx  = abs(pdi - mdi) / (pdi + mdi) * 100 if (pdi + mdi) else 0
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
        'regime':            'neutral',
        '_source':           'candle_engine',
    }


class CandleBuilder:
    """Accumulates ticks into one interval. Returns closed bar when boundary crossed."""

    def __init__(self, interval: str):
        self.interval   = interval
        self.period_sec = INTERVALS_SECONDS[interval]
        self._current: _OHLCV | None = None

    def _bar_ts(self, ts: float) -> float:
        return (ts // self.period_sec) * self.period_sec

    def update(self, price: float, volume: float, ts: float) -> _OHLCV | None:
        """Feed a tick. Returns the closed bar if the interval boundary was crossed."""
        bar_ts = self._bar_ts(ts)
        closed = None

        if self._current is None:
            self._current = _OHLCV(price, price, price, price, volume, bar_ts)
        elif bar_ts > self._current.ts:
            # boundary crossed — close current bar, open new one
            closed = self._current
            self._current = _OHLCV(price, price, price, price, volume, bar_ts)
        else:
            c = self._current
            if price > c.high:   c.high   = price
            if price < c.low:    c.low    = price
            c.close   = price
            c.volume += volume
            c.vwap_num += price * volume
            c.vwap_den += volume
            c.tick_count += 1

        return closed


class CandleEngine:
    """
    Subscribes to tick:* on the event bus.
    Maintains CandleBuilders for 1m and 5m intervals per symbol.
    Publishes bar:{symbol}:{interval} with computed indicators when a bar closes.
    Also provides latest(symbol, interval) for _compute_indicators_fast() override.
    """

    TRACKED_INTERVALS = ('1m', '5m', '15m', '1h', '1d')

    def __init__(self, event_bus):
        self._bus      = event_bus
        self._lock     = threading.Lock()
        # {symbol: {interval: CandleBuilder}}
        self._builders: dict[str, dict[str, CandleBuilder]] = defaultdict(dict)
        # {symbol: {interval: deque[_OHLCV]}}  — closed bars for indicator computation
        self._history:  dict[str, dict[str, deque]] = defaultdict(lambda: defaultdict(lambda: deque(maxlen=CANDLE_HISTORY)))
        # {symbol: {interval: dict}}  — latest computed indicator dict
        self._latest:   dict[str, dict[str, dict]] = defaultdict(dict)

    def start(self) -> None:
        self._bus.subscribe('tick:*', self._on_tick)
        log.debug("[CANDLE] CandleEngine started — tracking intervals: %s", self.TRACKED_INTERVALS)

    def latest(self, symbol: str, interval: str = '1m') -> dict | None:
        """Return the most recent closed bar's indicator dict, or None if not available."""
        with self._lock:
            return self._latest.get(symbol, {}).get(interval)

    def get_recent_closes(self, symbol: str, interval: str = '1m', n: int = 20) -> list:
        """Return last n closed bar close prices for (symbol, interval)."""
        with self._lock:
            hist = self._history.get(symbol, {}).get(interval)
            if not hist:
                return []
            bars = list(hist)
            return [b.close for b in bars[-n:]]

    def bars_available(self, symbol: str, interval: str = '1m') -> int:
        """Return number of closed bars available for (symbol, interval)."""
        with self._lock:
            hist = self._history.get(symbol, {}).get(interval)
            return len(hist) if hist else 0

    def is_warmed_up(self, symbol: str, interval: str = '1m', min_bars: int = 26) -> bool:
        """Return True if enough bars exist for reliable indicator computation.
        MACD needs 26 bars minimum; use 26 as the default gate."""
        return self.bars_available(symbol, interval) >= min_bars

    def _on_tick(self, channel: str, data: dict) -> None:
        symbol = data.get('symbol')
        price  = data.get('price')
        size   = data.get('size', 0) or 0
        ts     = data.get('timestamp') or time.time()
        if not symbol or not price:
            return
        try:
            price = float(price)
            size  = float(size)
            ts    = float(ts)
        except (TypeError, ValueError):
            return
        # Timestamp sanity: reject future timestamps or timestamps >1h old
        _now = time.time()
        if ts > _now + 300:    # more than 5 min in future
            ts = _now
        elif ts < _now - 3600: # more than 1 hour old
            ts = _now

        closed_bars = []
        with self._lock:
            if symbol not in self._builders:
                self._builders[symbol] = {iv: CandleBuilder(iv) for iv in self.TRACKED_INTERVALS}
            for interval, builder in self._builders[symbol].items():
                closed = builder.update(price, size, ts)
                if closed:
                    self._history[symbol][interval].append(closed)
                    closed_bars.append((interval, closed))

        for interval, closed in closed_bars:
            self._publish_closed(symbol, interval, closed)

    def _publish_closed(self, symbol: str, interval: str, bar: _OHLCV) -> None:
        with self._lock:
            history = self._history[symbol][interval]
            bars_count = len(history)
            if bars_count < 26:
                log.debug("[CANDLE] %s %s: only %d bars — indicators unreliable (need 26+)",
                          symbol, interval, bars_count)
            indicators = _compute_indicators(history)

        if not indicators:
            return

        payload = {
            'symbol':   symbol,
            'interval': interval,
            'open':     bar.open,
            'high':     bar.high,
            'low':      bar.low,
            'close':    bar.close,
            'volume':   bar.volume,
            'vwap':     bar.vwap_num / bar.vwap_den if bar.vwap_den else None,
            'timestamp': bar.ts,
            'closed':   True,
            'source':   'candle_engine',
            **indicators,
        }

        with self._lock:
            self._latest[symbol][interval] = payload

        self._bus.publish(f'bar:{symbol}:{interval}', payload)
        log.debug("[CANDLE] %s %s closed @ %.4f  RSI=%.1f", symbol, interval, bar.close, indicators.get('rsi', 0))

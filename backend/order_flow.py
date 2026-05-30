"""
OrderFlowEngine — bid/ask size imbalance and order flow signals.

Subscribes to quote:* events on the EventBus (emitted by alpaca_stream.py).
Tracks rolling bid/ask size imbalance and cumulative delta (bid vol - ask vol)
to detect institutional buying or selling pressure.

Signal: order_flow_bias — 'buy_pressure' | 'sell_pressure' | 'neutral'
Score contribution: -1.0 to +1.0
"""

from collections import defaultdict, deque
import threading, logging, time

log = logging.getLogger(__name__)

IMBALANCE_WINDOW = 20   # rolling window of quotes to track
IMBALANCE_THRESH = 0.65  # 65% bid or ask dominance = directional signal


class OrderFlowEngine:
    def __init__(self, event_bus=None):
        self._bus  = event_bus
        self._lock = threading.Lock()
        # {symbol: deque of (bid_size, ask_size) tuples}
        self._quotes: dict[str, deque] = defaultdict(lambda: deque(maxlen=IMBALANCE_WINDOW))
        # {symbol: cumulative delta (bid_vol - ask_vol)}
        self._cum_delta: dict[str, float] = defaultdict(float)
        self._last_signal: dict[str, dict] = {}

    def start(self) -> None:
        if self._bus:
            self._bus.subscribe('quote:*', self._on_quote)
            log.info('[FLOW] OrderFlowEngine started')

    def _on_quote(self, channel: str, data: dict) -> None:
        try:
            sym      = data.get('symbol') or channel.replace('quote:', '')
            bid_size = float(data.get('bid_size') or data.get('bs') or 0)
            ask_size = float(data.get('ask_size') or data.get('as') or 0)
            if not sym or (bid_size == 0 and ask_size == 0):
                return
            with self._lock:
                self._quotes[sym].append((bid_size, ask_size))
                self._cum_delta[sym] += bid_size - ask_size
        except Exception as e:
            log.debug('[FLOW] _on_quote error: %s', e)

    def get_signal(self, symbol: str) -> dict:
        """
        Returns:
        {
            'bid_ask_ratio': float,    # bid_size / (bid_size + ask_size)
            'cum_delta':     float,    # cumulative (bid - ask) volume
            'bias':          str,      # 'buy_pressure'|'sell_pressure'|'neutral'
            'score_contrib': float,    # -1.0 to +1.0
            'samples':       int,
        }
        """
        try:
            with self._lock:
                quotes    = list(self._quotes.get(symbol, []))
                cum_delta = self._cum_delta.get(symbol, 0.0)

            if len(quotes) < 5:
                return {
                    'bid_ask_ratio': 0.5,
                    'cum_delta':     0.0,
                    'bias':          'neutral',
                    'score_contrib': 0.0,
                    'samples':       len(quotes),
                }

            total_bid = sum(q[0] for q in quotes)
            total_ask = sum(q[1] for q in quotes)
            total     = total_bid + total_ask

            ratio = total_bid / total if total > 0 else 0.5

            if ratio >= IMBALANCE_THRESH:
                bias    = 'buy_pressure'
                contrib = min(1.0, (ratio - 0.5) * 4)
            elif ratio <= (1 - IMBALANCE_THRESH):
                bias    = 'sell_pressure'
                contrib = max(-1.0, (ratio - 0.5) * 4)
            else:
                bias    = 'neutral'
                contrib = 0.0

            # Cumulative delta confirmation — amplify if delta agrees
            if (contrib > 0 and cum_delta > 0) or (contrib < 0 and cum_delta < 0):
                contrib = min(1.0, abs(contrib) * 1.2) * (1 if contrib > 0 else -1)

            return {
                'bid_ask_ratio': round(ratio, 3),
                'cum_delta':     round(cum_delta, 1),
                'bias':          bias,
                'score_contrib': round(contrib, 3),
                'samples':       len(quotes),
            }
        except Exception as e:
            log.debug('[FLOW] get_signal error for %s: %s', symbol, e)
            return {'bid_ask_ratio': 0.5, 'cum_delta': 0.0,
                    'bias': 'neutral', 'score_contrib': 0.0, 'samples': 0}

    def latest(self) -> dict:
        """Return signals for all tracked symbols."""
        try:
            with self._lock:
                symbols = list(self._quotes.keys())
            return {sym: self.get_signal(sym) for sym in symbols}
        except Exception as e:
            log.debug('[FLOW] latest error: %s', e)
            return {}

    def reset(self, symbol: str = None) -> None:
        """Reset state for one symbol or all symbols."""
        try:
            with self._lock:
                if symbol:
                    self._quotes.pop(symbol, None)
                    self._cum_delta.pop(symbol, None)
                    self._last_signal.pop(symbol, None)
                else:
                    self._quotes.clear()
                    self._cum_delta.clear()
                    self._last_signal.clear()
        except Exception as e:
            log.debug('[FLOW] reset error: %s', e)

    def inject_quote(self, symbol: str, bid_size: float, ask_size: float) -> None:
        """Manually inject a quote (for backtesting or replay)."""
        try:
            if not symbol or (bid_size == 0 and ask_size == 0):
                return
            with self._lock:
                self._quotes[symbol].append((float(bid_size), float(ask_size)))
                self._cum_delta[symbol] += float(bid_size) - float(ask_size)
        except Exception as e:
            log.debug('[FLOW] inject_quote error: %s', e)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine: OrderFlowEngine | None = None


def init(event_bus=None) -> OrderFlowEngine:
    global _engine
    _engine = OrderFlowEngine(event_bus)
    _engine.start()
    return _engine


def get_signal(symbol: str) -> dict:
    if _engine is None:
        return {'bias': 'neutral', 'score_contrib': 0.0, 'samples': 0}
    return _engine.get_signal(symbol)


def score_contrib(symbol: str) -> float:
    return get_signal(symbol).get('score_contrib', 0.0)


def latest() -> dict:
    if _engine is None:
        return {}
    return _engine.latest()

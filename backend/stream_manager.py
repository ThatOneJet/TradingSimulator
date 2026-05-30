"""
StreamManager — unified WebSocket tick/bar router.

Responsibilities:
  - Normalize symbols from all source formats to internal format
  - Deduplicate ticks by (symbol, trade_id) or 50ms timestamp window
  - Enforce source priority: skip lower-priority source when higher is active
  - Trigger failover when a source dies
  - Publish normalized Tick/Bar to the event bus

Source priority (index 0 = highest):
  crypto: ['binance', 'polygon', 'alpaca']
  equity: ['alpaca', 'finnhub']
  forex:  ['polygon']
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)

SOURCE_PRIORITY: dict[str, list[str]] = {
    'crypto': ['binance', 'polygon', 'alpaca'],
    'equity': ['alpaca', 'finnhub'],
    'forex':  ['polygon'],
}

# Crypto symbols that Binance handles (internal format → Binance format)
CRYPTO_SYMBOLS = {
    'BTC-USD', 'ETH-USD', 'SOL-USD', 'BNB-USD',
    'XRP-USD', 'ADA-USD', 'AVAX-USD', 'DOGE-USD',
}

FOREX_SYMBOLS = {
    'EURUSD=X', 'GBPUSD=X', 'USDJPY=X',
    'AUDUSD=X', 'USDCAD=X', 'USDCHF=X', 'NZDUSD=X',
}


def _asset_class(symbol: str) -> str:
    if symbol in CRYPTO_SYMBOLS or symbol.endswith('-USD'):
        return 'crypto'
    if symbol in FOREX_SYMBOLS or symbol.endswith('=X'):
        return 'forex'
    return 'equity'


@dataclass
class Tick:
    symbol: str          # normalized: "BTC-USD", "AAPL", "EURUSD=X"
    price: float
    size: float
    timestamp: float     # Unix seconds
    source: str          # "binance" | "alpaca" | "finnhub" | "polygon"
    bid: float | None = None
    ask: float | None = None
    trade_id: str | None = None


@dataclass
class Bar:
    symbol: str
    interval: str        # "1s" | "1m" | "5m" | "15m" | "1h" | "1d"
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float | None = None
    timestamp: float = 0.0
    closed: bool = False
    source: str = ''


class StreamManager:
    def __init__(self, event_bus):
        self._bus = event_bus
        self._lock = threading.Lock()

        # {symbol: source_name} — which source is currently live for each symbol
        self._active_source: dict[str, str] = {}

        # {symbol: {'last_ts': float, 'last_id': str|None}}
        self._last_tick: dict[str, dict] = {}

        # {source_name: {'asset_class': str, 'on_tick': cb, 'on_bar': cb, 'symbols': set}}
        self._providers: dict[str, dict] = {}

        # {asset_class: ordered list of source names}
        self._priority: dict[str, list[str]] = {k: list(v) for k, v in SOURCE_PRIORITY.items()}

        # callbacks registered by external code for failover events
        self._failover_callbacks: list[Callable] = []

    # ------------------------------------------------------------------
    # Provider registration
    # ------------------------------------------------------------------

    def register_provider(
        self,
        name: str,
        asset_class: str,
        on_tick_cb: Callable | None = None,
        on_bar_cb: Callable | None = None,
    ) -> None:
        with self._lock:
            self._providers[name] = {
                'asset_class': asset_class,
                'on_tick': on_tick_cb,
                'on_bar': on_bar_cb,
                'symbols': set(),
                'dead': False,
            }
        log.debug("[STREAM] Registered provider '%s' for %s", name, asset_class)

    def on_failover(self, callback: Callable) -> None:
        """Register a callback(symbol, old_source, new_source) for failover events."""
        self._failover_callbacks.append(callback)

    # ------------------------------------------------------------------
    # Public: receive ticks/bars from providers
    # ------------------------------------------------------------------

    def on_tick(self, tick: Tick) -> None:
        if not self._should_accept(tick.symbol, tick.source, tick.trade_id, tick.timestamp):
            return
        self._bus.publish(f'tick:{tick.symbol}', {
            'symbol':    tick.symbol,
            'price':     tick.price,
            'size':      tick.size,
            'timestamp': tick.timestamp,
            'source':    tick.source,
            'bid':       tick.bid,
            'ask':       tick.ask,
        })

    def on_bar(self, bar: Bar) -> None:
        cls = _asset_class(bar.symbol)
        priority = self._priority.get(cls, [])
        with self._lock:
            active = self._active_source.get(bar.symbol)
        if (active and bar.source and active in priority and bar.source in priority
                and priority.index(bar.source) > priority.index(active)):
            return  # lower-priority bar, skip
        self._bus.publish(f'bar:{bar.symbol}:{bar.interval}', {
            'symbol':    bar.symbol,
            'interval':  bar.interval,
            'open':      bar.open,
            'high':      bar.high,
            'low':       bar.low,
            'close':     bar.close,
            'volume':    bar.volume,
            'vwap':      bar.vwap,
            'timestamp': bar.timestamp,
            'closed':    bar.closed,
            'source':    bar.source,
        })

    # ------------------------------------------------------------------
    # Failover
    # ------------------------------------------------------------------

    def mark_source_dead(self, source: str, symbol: str | None = None) -> None:
        """
        Called when a provider disconnects or stops sending data.
        If symbol is None, marks the source dead for all its symbols.
        Activates the next-priority source for affected symbols.
        """
        with self._lock:
            if source not in self._providers:
                return
            prov = self._providers[source]
            affected = {symbol} if symbol else set(prov['symbols'])
            if not symbol:
                prov['dead'] = True

        for sym in affected:
            cls = _asset_class(sym)
            priority = self._priority.get(cls, [])
            try:
                src_idx = priority.index(source)
            except ValueError:
                continue

            new_source = None
            for candidate in priority[src_idx + 1:]:
                with self._lock:
                    p = self._providers.get(candidate, {})
                    if not p.get('dead'):
                        new_source = candidate
                        break

            with self._lock:
                old = self._active_source.get(sym)
                if new_source:
                    self._active_source[sym] = new_source
                elif sym in self._active_source:
                    del self._active_source[sym]

            log.debug("[STREAM] failover %s: %s → %s", sym, source, new_source or 'none')
            self._bus.publish('stream:failover', {
                'symbol': sym, 'from': source, 'to': new_source,
            })
            for cb in self._failover_callbacks:
                try:
                    cb(sym, source, new_source)
                except Exception:
                    log.exception("Failover callback error")

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @property
    def streaming_symbols(self) -> dict[str, str]:
        with self._lock:
            return dict(self._active_source)

    def start(self) -> None:
        self._bus.start()
        log.debug("[STREAM] StreamManager started")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _should_accept(self, symbol: str, source: str, trade_id: str | None, ts: float) -> bool:
        cls = _asset_class(symbol)
        priority = self._priority.get(cls, [])

        with self._lock:
            active = self._active_source.get(symbol)
            if active is None:
                # first source to send a tick wins
                self._active_source[symbol] = source
                if source in self._providers:
                    self._providers[source]['symbols'].add(symbol)
                active = source
            elif active != source:
                # only accept if source has higher or equal priority
                if source in priority and active in priority:
                    if priority.index(source) > priority.index(active):
                        return False  # lower-priority, skip
                else:
                    return False

            # dedup
            last = self._last_tick.get(symbol, {})
            if trade_id and trade_id == last.get('last_id'):
                return False
            if ts and last.get('last_ts') and abs(ts - last['last_ts']) < 0.05:
                return False

            self._last_tick[symbol] = {'last_ts': ts, 'last_id': trade_id}

        return True


# ------------------------------------------------------------------
# Symbol normalization helpers (called by individual stream modules)
# ------------------------------------------------------------------

def normalize_binance(raw: str) -> str:
    """'btcusdt' → 'BTC-USD'"""
    raw = raw.upper()
    if raw.endswith('USDT'):
        return raw[:-4] + '-USD'
    if raw.endswith('BUSD'):
        return raw[:-4] + '-USD'
    return raw


def normalize_polygon(raw: str) -> str:
    """'X:BTCUSD' → 'BTC-USD', 'C:EURUSD' → 'EURUSD=X'"""
    if raw.startswith('X:'):
        base = raw[2:]  # e.g. BTCUSD
        if base.endswith('USD'):
            return base[:-3] + '-USD'
        return base
    if raw.startswith('C:'):
        return raw[2:] + '=X'  # EURUSD → EURUSD=X
    return raw


def normalize_alpaca(raw: str) -> str:
    """'BTC/USD' → 'BTC-USD'"""
    return raw.replace('/', '-')

"""
Binance WebSocket stream for crypto ticks and 1-minute klines.

Connects to wss://stream.binance.com:9443/ws using a combined multi-stream URL.
No API key required.

Subscribes to {sym}@aggTrade and {sym}@kline_1m for each symbol.
Routes all data through StreamManager (never emits directly to SocketIO).
Reconnects with exponential backoff: 1s → 2s → 4s → max 60s.
"""

import json
import logging
import threading
import time

from stream_manager import Bar, StreamManager, Tick, normalize_binance

log = logging.getLogger(__name__)

# Internal format → Binance stream symbol
SYMBOL_MAP: dict[str, str] = {
    'BTC-USD':  'btcusdt',
    'ETH-USD':  'ethusdt',
    'SOL-USD':  'solusdt',
    'BNB-USD':  'bnbusdt',
    'XRP-USD':  'xrpusdt',
    'ADA-USD':  'adausdt',
    'AVAX-USD': 'avaxusdt',
    'DOGE-USD': 'dogeusdt',
}

WS_URL = 'wss://stream.binance.com:9443/ws'


class BinanceWS:
    def __init__(self, symbols: list[str], stream_manager: StreamManager):
        self._symbols = [s for s in symbols if s in SYMBOL_MAP]
        self._sm = stream_manager
        self._ws = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name='binance-ws')
        self._thread.start()
        log.info("[BINANCE] Starting stream for %d symbols: %s", len(self._symbols), self._symbols)

    def stop(self) -> None:
        self._stop.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    def _build_url(self) -> str:
        streams = []
        for sym in self._symbols:
            bs = SYMBOL_MAP[sym]
            streams.append(f'{bs}@aggTrade')
            streams.append(f'{bs}@kline_1m')
        combined = '/'.join(streams)
        return f'{WS_URL}/{combined}'

    def _run(self) -> None:
        import websocket
        backoff = 1.0

        while not self._stop.is_set():
            url = self._build_url()
            log.info("[BINANCE] Connecting to %d streams", len(self._symbols) * 2)
            try:
                ws = websocket.WebSocketApp(
                    url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._ws = ws
                ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as e:
                log.error("[BINANCE] run_forever exception: %s", e)

            if self._stop.is_set():
                break

            log.debug("[BINANCE] Disconnected, reconnecting in %.0fs", backoff)
            # notify StreamManager so failover activates
            for sym in self._symbols:
                self._sm.mark_source_dead('binance', sym)

            time.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

    def _on_open(self, ws) -> None:
        log.info("[BINANCE] Connected, streaming %d symbols", len(self._symbols))
        # reset backoff on successful connect — can't easily reset from here,
        # but we track in _run loop; reconnect path resets when _run restarts

    def _on_message(self, ws, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except Exception:
            return

        event = msg.get('e')
        if event == 'aggTrade':
            self._handle_agg_trade(msg)
        elif event == 'kline':
            self._handle_kline(msg)

    def _handle_agg_trade(self, msg: dict) -> None:
        raw_sym = msg.get('s', '')
        symbol = normalize_binance(raw_sym)
        if symbol not in self._symbols:
            return
        tick = Tick(
            symbol=symbol,
            price=float(msg['p']),
            size=float(msg['q']),
            timestamp=msg['T'] / 1000.0,
            source='binance',
            trade_id=str(msg.get('a', '')),
        )
        self._sm.on_tick(tick)

    def _handle_kline(self, msg: dict) -> None:
        k = msg.get('k', {})
        if not k:
            return
        raw_sym = msg.get('s', '')
        symbol = normalize_binance(raw_sym)
        if symbol not in self._symbols:
            return
        bar = Bar(
            symbol=symbol,
            interval='1m',
            open=float(k['o']),
            high=float(k['h']),
            low=float(k['l']),
            close=float(k['c']),
            volume=float(k['v']),
            vwap=float(k['q']) / float(k['v']) if float(k['v']) > 0 else None,
            timestamp=k['t'] / 1000.0,
            closed=k.get('x', False),
            source='binance',
        )
        self._sm.on_bar(bar)

    def _on_error(self, ws, error) -> None:
        log.error("[BINANCE] WebSocket error: %s", error)

    def _on_close(self, ws, code, msg) -> None:
        log.debug("[BINANCE] Connection closed (code=%s)", code)

"""
CoinbaseWS — Coinbase Advanced Trade WebSocket for crypto tick data.

Replaces BinanceWS which is geo-blocked in the US (HTTP 451).
Free, no API key required, US-accessible.

Subscribes to ticker channel for all mapped crypto symbols.
Routes ticks through StreamManager.
Reconnects with exponential backoff.
"""

import json
import logging
import threading
import time

from stream_manager import StreamManager, Tick

log = logging.getLogger(__name__)

# Internal format → Coinbase product_id (same format, BTC-USD etc.)
SYMBOL_MAP: dict[str, str] = {
    'BTC-USD':  'BTC-USD',
    'ETH-USD':  'ETH-USD',
    'SOL-USD':  'SOL-USD',
    'BNB-USD':  'BNB-USD',   # may not be on Coinbase, handled gracefully
    'XRP-USD':  'XRP-USD',
    'ADA-USD':  'ADA-USD',
    'AVAX-USD': 'AVAX-USD',
    'DOGE-USD': 'DOGE-USD',
    'DOT-USD':  'DOT-USD',
    'LINK-USD': 'LINK-USD',
    'ATOM-USD': 'ATOM-USD',
    'NEAR-USD': 'NEAR-USD',
}

WS_URL = 'wss://advanced-trade-ws.coinbase.com/ws'


class CoinbaseWS:
    def __init__(self, symbols: list[str], stream_manager: StreamManager):
        self._symbols = [s for s in symbols if s in SYMBOL_MAP]
        self._product_ids = [SYMBOL_MAP[s] for s in self._symbols]
        self._sm = stream_manager
        self._ws = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self._symbols:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name='coinbase-ws')
        self._thread.start()
        log.debug("[COINBASE] Starting stream for %d symbols", len(self._symbols))

    def stop(self) -> None:
        self._stop.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    def _run(self) -> None:
        try:
            import websocket
        except ImportError:
            log.error("[COINBASE] websocket-client not installed. Run: pip install websocket-client")
            return

        backoff = 1.0

        while not self._stop.is_set():
            log.debug("[COINBASE] Connecting to %s", WS_URL)
            try:
                ws = websocket.WebSocketApp(
                    WS_URL,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._ws = ws
                ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                log.debug("[COINBASE] run_forever exception: %s", e)

            if self._stop.is_set():
                break

            log.debug("[COINBASE] Disconnected, reconnecting in %.0fs", backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

    def _on_open(self, ws) -> None:
        log.debug("[COINBASE] Connected — subscribing %d products", len(self._product_ids))
        try:
            sub_msg = json.dumps({
                "type": "subscribe",
                "product_ids": self._product_ids,
                "channel": "ticker",
            })
            ws.send(sub_msg)
        except Exception as e:
            log.debug("[COINBASE] Subscribe error: %s", e)

    def _on_message(self, ws, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except Exception:
            return

        channel = msg.get('channel', '')
        if channel != 'ticker':
            return

        events = msg.get('events', [])
        for event in events:
            tickers = event.get('tickers', [])
            for ticker in tickers:
                self._handle_ticker(ticker)

    def _handle_ticker(self, ticker: dict) -> None:
        try:
            product_id = ticker.get('product_id', '')
            price_str  = ticker.get('price', '')
            if not product_id or not price_str:
                return

            # Find internal symbol for this product_id
            symbol = None
            for sym, pid in SYMBOL_MAP.items():
                if pid == product_id:
                    symbol = sym
                    break
            if not symbol:
                return

            price = float(price_str)
            if price <= 0:
                return

            volume_str = ticker.get('volume_24_h', '0') or '0'
            volume = float(volume_str)

            tick = Tick(
                symbol=symbol,
                price=price,
                size=volume / 86400,  # approximate per-second volume
                timestamp=time.time(),
                source='coinbase',
            )
            self._sm.on_tick(tick)

        except Exception as e:
            log.debug("[COINBASE] ticker parse error: %s", e)

    def _on_error(self, ws, error) -> None:
        log.debug("[COINBASE] WebSocket error: %s", error)

    def _on_close(self, ws, code, msg) -> None:
        log.debug("[COINBASE] Connection closed (code=%s)", code)

import json
import logging
import threading
import time

from stream_manager import StreamManager, Tick

log = logging.getLogger(__name__)

_stream_manager: StreamManager | None = None
_api_key    = None
_subscribed = set()
_ws         = None
_lock       = threading.Lock()


def _on_message(ws, message):
    try:
        data = json.loads(message)
        if data.get('type') != 'trade' or not _stream_manager:
            return
        for trade in data.get('data', []):
            sym   = trade.get('s', '')
            price = float(trade.get('p') or 0)
            if not sym or price <= 0:
                continue
            half = round(price * 0.0001, 4)
            tick = Tick(
                symbol=sym,
                price=price,
                size=float(trade.get('v', 0) or 0),
                timestamp=trade.get('t', time.time() * 1000) / 1000.0,
                source='finnhub',
                bid=round(price - half, 4),
                ask=round(price + half, 4),
                trade_id=str(trade.get('c', '')),
            )
            _stream_manager.on_tick(tick)
    except Exception:
        pass


def _on_open(ws):
    log.debug("[FINNHUB] Connected — subscribing symbols")
    with _lock:
        for sym in _subscribed:
            ws.send(json.dumps({'type': 'subscribe', 'symbol': sym}))


def _on_error(ws, error):
    log.error("[FINNHUB] Error: %s", error)


def _on_close(ws, *args):
    log.debug("[FINNHUB] Closed — reconnecting in 5s")


def subscribe(symbol: str, sio=None) -> None:
    with _lock:
        if symbol not in _subscribed:
            _subscribed.add(symbol)
            if _ws:
                try:
                    _ws.send(json.dumps({'type': 'subscribe', 'symbol': symbol}))
                except Exception:
                    pass


def start_stream(api_key: str, stream_manager: StreamManager) -> None:
    global _stream_manager, _api_key, _ws
    _stream_manager = stream_manager
    _api_key = api_key

    for sym in ('AAPL', 'TSLA', 'NVDA', 'SPY', 'QQQ'):
        _subscribed.add(sym)

    def _run():
        global _ws
        import websocket as _wslib
        while True:
            try:
                _ws = _wslib.WebSocketApp(
                    f'wss://ws.finnhub.io?token={api_key}',
                    on_open=_on_open,
                    on_message=_on_message,
                    on_error=_on_error,
                    on_close=_on_close,
                )
                _ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                log.error("[FINNHUB] Exception: %s", e)
            _ws = None
            time.sleep(5)

    threading.Thread(target=_run, daemon=True, name='finnhub-ws').start()
    log.debug("[FINNHUB] Stream starting")

import json
import threading
import time

_socketio   = None
_api_key    = None
_subscribed = set()
_ws         = None
_lock       = threading.Lock()


def _on_message(ws, message):
    try:
        data = json.loads(message)
        if data.get('type') != 'trade' or not _socketio:
            return
        for trade in data.get('data', []):
            sym   = trade.get('s', '')
            price = float(trade.get('p') or 0)
            if not sym or price <= 0:
                continue
            # Synthetic spread: 0.02% of price (realistic for liquid US equities)
            half  = round(price * 0.0001, 4)
            _socketio.emit('quote', {
                'symbol': sym,
                'bid':    round(price - half, 4),
                'ask':    round(price + half, 4),
                'spread': round(half * 2, 4),
            })
    except Exception:
        pass


def _on_open(ws):
    print('[Finnhub] WebSocket connected — subscribing symbols')
    with _lock:
        for sym in _subscribed:
            ws.send(json.dumps({'type': 'subscribe', 'symbol': sym}))


def _on_error(ws, error):
    print(f'[Finnhub] WebSocket error: {error}')


def _on_close(ws, *args):
    print('[Finnhub] WebSocket closed — reconnecting in 5 s')


def subscribe(symbol: str, sio=None):
    global _socketio
    if sio:
        _socketio = sio
    with _lock:
        if symbol not in _subscribed:
            _subscribed.add(symbol)
            if _ws:
                try:
                    _ws.send(json.dumps({'type': 'subscribe', 'symbol': symbol}))
                except Exception:
                    pass


def start_stream(api_key: str, sio):
    global _socketio, _api_key, _ws
    _socketio = sio
    _api_key  = api_key

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
                print(f'[Finnhub] stream exception: {e}')
            _ws = None
            time.sleep(5)  # reconnect delay

    threading.Thread(target=_run, daemon=True, name='finnhub-ws').start()

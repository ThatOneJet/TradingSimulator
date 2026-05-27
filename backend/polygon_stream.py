"""
Polygon.io WebSocket real-time feed.

Subscribes to per-minute aggregate bars (AM.*) and best bid/ask quotes (Q.*)
then relays them as SocketIO events ('bar' and 'quote') to connected browsers.

Set POLYGON_KEY in backend/.env to enable.
Free Polygon.io keys: https://polygon.io/dashboard/signup
"""

import json
import threading

_ws        = None
_sio       = None
_api_key   = None
_subscribed: set[str] = set()
_lock      = threading.Lock()


def _on_message(ws, message):
    try:
        events = json.loads(message)
    except Exception:
        return
    for ev in events:
        evt = ev.get('ev')
        if evt == 'status':
            status = ev.get('status')
            if status == 'auth_success':
                print('[Polygon] Authenticated.')
                # Subscribe to all currently-tracked symbols
                with _lock:
                    if _subscribed:
                        _send_sub(ws, _subscribed)
            elif status == 'auth_failed':
                print('[Polygon] Authentication failed — check POLYGON_KEY in .env')
        elif evt == 'AM' and _sio:
            # Per-minute aggregate bar
            _sio.emit('bar', {
                'symbol': ev['sym'],
                'bar': {
                    'time':   ev['s'] // 1000,   # start timestamp → seconds
                    'open':   ev['o'],
                    'high':   ev['h'],
                    'low':    ev['l'],
                    'close':  ev['c'],
                    'volume': ev['av'],           # accumulated volume for the day
                },
            })
        elif evt == 'Q' and _sio:
            bid = ev.get('bp', 0)
            ask = ev.get('ap', 0)
            _sio.emit('quote', {
                'symbol':   ev['sym'],
                'bid':      bid,
                'ask':      ask,
                'bid_size': ev.get('bs', 0),
                'ask_size': ev.get('as', 0),
                'spread':   round(ask - bid, 4),
            })


def _on_open(ws):
    print('[Polygon] Connected — authenticating...')
    ws.send(json.dumps({'action': 'auth', 'params': _api_key}))


def _on_error(ws, error):
    print(f'[Polygon] WebSocket error: {error}')


def _on_close(ws, code, msg):
    print(f'[Polygon] Connection closed ({code}): {msg}')


def _send_sub(ws, symbols: set[str]):
    params = ','.join(f'AM.{s},Q.{s}' for s in symbols)
    ws.send(json.dumps({'action': 'subscribe', 'params': params}))


def subscribe(symbol: str):
    """Add a symbol to the live subscription list."""
    with _lock:
        if symbol in _subscribed:
            return
        _subscribed.add(symbol)
        if _ws:
            _send_sub(_ws, {symbol})


def start_stream(api_key: str, sio):
    global _ws, _sio, _api_key
    _api_key = api_key
    _sio     = sio

    try:
        import websocket
    except ImportError:
        print('[Polygon] websocket-client not installed. Run: pip install websocket-client')
        return

    # Default subscriptions
    with _lock:
        for sym in ('AAPL', 'TSLA', 'NVDA', 'SPY'):
            _subscribed.add(sym)

    _ws = websocket.WebSocketApp(
        'wss://socket.polygon.io/stocks',
        on_open=_on_open,
        on_message=_on_message,
        on_error=_on_error,
        on_close=_on_close,
    )
    print('[Polygon] Connecting to wss://socket.polygon.io/stocks ...')
    _ws.run_forever(reconnect=5)

import asyncio
from alpaca.data.live import StockDataStream

_stream      = None
_subscribed  = set()
_socketio    = None
_loop        = None

def bar_to_dict(bar):
    return {
        'time':   int(bar.timestamp.timestamp()),
        'open':   float(bar.open),
        'high':   float(bar.high),
        'low':    float(bar.low),
        'close':  float(bar.close),
        'volume': float(bar.volume),
    }

async def on_bar(bar):
    if _socketio:
        _socketio.emit('bar', {'symbol': bar.symbol, 'bar': bar_to_dict(bar)})

async def on_quote(quote):
    if _socketio:
        _socketio.emit('quote', {
            'symbol':   quote.symbol,
            'bid':      float(quote.bid_price),
            'bid_size': float(quote.bid_size),
            'ask':      float(quote.ask_price),
            'ask_size': float(quote.ask_size),
        })

def subscribe(symbol: str, sio=None):
    global _stream, _subscribed, _socketio, _loop
    if sio:
        _socketio = sio
    if symbol not in _subscribed and _stream:
        _subscribed.add(symbol)
        # Schedule subscription on the stream's event loop
        if _loop and _loop.is_running():
            asyncio.run_coroutine_threadsafe(_do_subscribe(symbol), _loop)

async def _do_subscribe(symbol):
    _stream.subscribe_bars(on_bar, symbol)
    _stream.subscribe_quotes(on_quote, symbol)

def start_stream(api_key: str, secret_key: str, sio):
    global _stream, _socketio, _loop
    _socketio = sio
    _stream   = StockDataStream(api_key, secret_key, feed='iex')

    # Subscribe defaults
    for sym in ['AAPL', 'TSLA', 'NVDA', 'SPY']:
        _subscribed.add(sym)
        _stream.subscribe_bars(on_bar, sym)
        _stream.subscribe_quotes(on_quote, sym)

    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    _stream.run()

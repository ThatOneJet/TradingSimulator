import asyncio
import logging
from alpaca.data.live import StockDataStream
from stream_manager import Bar, StreamManager, Tick, normalize_alpaca

log = logging.getLogger(__name__)

_stream:         StockDataStream | None = None
_subscribed:     set = set()
_stream_manager: StreamManager | None = None
_loop:           asyncio.AbstractEventLoop | None = None


def _make_bar_handler(sm: StreamManager):
    async def on_bar(bar):
        b = Bar(
            symbol=normalize_alpaca(bar.symbol),
            interval='1m',
            open=float(bar.open),
            high=float(bar.high),
            low=float(bar.low),
            close=float(bar.close),
            volume=float(bar.volume),
            vwap=float(bar.vwap) if bar.vwap else None,
            timestamp=bar.timestamp.timestamp(),
            closed=True,
            source='alpaca',
        )
        sm.on_bar(b)
    return on_bar


def _make_quote_handler(sm: StreamManager):
    async def on_quote(quote):
        bid = float(quote.bid_price or 0)
        ask = float(quote.ask_price or 0)
        mid = (bid + ask) / 2 if bid and ask else bid or ask
        if not mid:
            return
        tick = Tick(
            symbol=normalize_alpaca(quote.symbol),
            price=mid,
            size=float(quote.bid_size or 0),
            timestamp=quote.timestamp.timestamp(),
            source='alpaca',
            bid=bid or None,
            ask=ask or None,
        )
        sm.on_tick(tick)
    return on_quote


def subscribe(symbol: str, sio=None) -> None:
    global _stream, _subscribed, _loop
    sym = normalize_alpaca(symbol.upper())
    if sym not in _subscribed and _stream and _stream_manager:
        _subscribed.add(sym)
        if _loop and _loop.is_running():
            on_bar   = _make_bar_handler(_stream_manager)
            on_quote = _make_quote_handler(_stream_manager)
            asyncio.run_coroutine_threadsafe(_do_subscribe(sym, on_bar, on_quote), _loop)


async def _do_subscribe(symbol: str, on_bar, on_quote) -> None:
    _stream.subscribe_bars(on_bar, symbol)
    _stream.subscribe_quotes(on_quote, symbol)


def start_stream(api_key: str, secret_key: str, stream_manager: StreamManager) -> None:
    global _stream, _stream_manager, _loop
    _stream_manager = stream_manager
    _stream = StockDataStream(api_key, secret_key, feed='iex')

    on_bar   = _make_bar_handler(stream_manager)
    on_quote = _make_quote_handler(stream_manager)

    for sym in ['AAPL', 'TSLA', 'NVDA', 'SPY']:
        _subscribed.add(sym)
        _stream.subscribe_bars(on_bar, sym)
        _stream.subscribe_quotes(on_quote, sym)

    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    log.info("[ALPACA] Stream starting (iex feed)")
    _stream.run()

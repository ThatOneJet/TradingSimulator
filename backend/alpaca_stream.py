import asyncio
import logging
import time
from alpaca.data.live import StockDataStream
from stream_manager import Bar, StreamManager, Tick, normalize_alpaca

log = logging.getLogger(__name__)

_stream:         StockDataStream | None = None
_subscribed:     set = set()
_stream_manager: StreamManager | None = None
_loop:           asyncio.AbstractEventLoop | None = None

# --- Reconnect / backoff tuning -------------------------------------------
# Alpaca's free tier allows only ONE concurrent websocket connection, so we
# must never stack reconnect attempts. We supervise the connection ourselves
# (instead of relying on the SDK's internal tight retry loop) and apply
# exponential backoff with a hard cap.
_BACKOFF_BASE_SEC      = 2.0    # first reconnect delay
_BACKOFF_CAP_SEC       = 60.0   # never wait longer than this between tries
_STABLE_RESET_SEC      = 30.0   # uptime after which backoff resets to base
_CONN_LIMIT_COOLDOWN   = 45.0   # fixed cooldown when "connection limit exceeded"
_LOG_THROTTLE_SEC      = 30.0   # suppress duplicate error logs within this window
_SHOULD_RUN            = True   # supervisor stop flag

# Throttled-logging state: {error_signature: (last_logged_ts, suppressed_count)}
_last_error_log: dict = {}


def _is_conn_limit_error(exc: Exception) -> bool:
    """True if the exception is Alpaca's one-connection-per-account limit."""
    msg = str(exc).lower()
    return 'connection limit' in msg or 'connection limit exceeded' in msg


def _log_throttled(signature: str, message: str, level=logging.WARNING) -> None:
    """
    Log `message` at most once per `_LOG_THROTTLE_SEC` per `signature`.

    The first occurrence logs immediately; subsequent identical errors are
    counted and the suppressed count is emitted with the next allowed log,
    so the logs don't get flooded by dozens of identical reconnect errors.
    """
    now = time.time()
    last_ts, suppressed = _last_error_log.get(signature, (0.0, 0))
    if now - last_ts >= _LOG_THROTTLE_SEC:
        if suppressed:
            message = f'{message} (suppressed {suppressed} duplicate(s))'
        log.log(level, message)
        _last_error_log[signature] = (now, 0)
    else:
        _last_error_log[signature] = (last_ts, suppressed + 1)


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
        normalized_symbol = normalize_alpaca(quote.symbol)
        tick = Tick(
            symbol=normalized_symbol,
            price=mid,
            size=float(quote.bid_size or 0),
            timestamp=quote.timestamp.timestamp(),
            source='alpaca',
            bid=bid or None,
            ask=ask or None,
        )
        sm.on_tick(tick)

        # Also publish a quote:{symbol} event so OrderFlowEngine receives data.
        try:
            bus = getattr(sm, '_bus', None)
            if bus is not None:
                bus.publish(f'quote:{normalized_symbol}', {
                    'symbol':    normalized_symbol,
                    'bid':       float(quote.bid_price or 0),
                    'ask':       float(quote.ask_price or 0),
                    'bid_size':  float(quote.bid_size or 0),
                    'ask_size':  float(quote.ask_size or 0),
                    'timestamp': time.time(),
                })
        except Exception as e:
            log.debug('[ALPACA] order_flow quote publish failed: %s', e)
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
    try:
        _stream_manager = stream_manager

        # Handle both old SDK (string) and new SDK (enum) for feed parameter
        feed_arg = 'iex'
        try:
            from alpaca.data.enums import DataFeed
            feed_arg = DataFeed.IEX
        except (ImportError, AttributeError):
            pass

        try:
            _stream = StockDataStream(api_key, secret_key, feed=feed_arg)
        except TypeError:
            # Some SDK versions don't accept feed at all
            try:
                _stream = StockDataStream(api_key, secret_key)
            except Exception as e:
                log.error("[ALPACA] Failed to create StockDataStream: %s", e)
                return
        except Exception as e:
            log.error("[ALPACA] Failed to create StockDataStream: %s", e)
            return

        on_bar   = _make_bar_handler(stream_manager)
        on_quote = _make_quote_handler(stream_manager)

        for sym in ['AAPL', 'TSLA', 'NVDA', 'SPY']:
            _subscribed.add(sym)
            _stream.subscribe_bars(on_bar, sym)
            _stream.subscribe_quotes(on_quote, sym)

        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
        log.debug("[ALPACA] Stream starting (iex feed)")
        # Supervise the connection ourselves with exponential backoff so a
        # brief network drop can't spin up stacked reconnects against
        # Alpaca's single-connection limit. We deliberately do NOT call
        # _stream.run() (its internal retry loop tight-spins on auth errors).
        _loop.run_until_complete(_supervise())
    except Exception as e:
        log.error("[ALPACA] Stream startup failed: %s", e)
        return


async def _supervise() -> None:
    """
    Resilient connection supervisor with exponential backoff.

    Replaces the Alpaca SDK's built-in run loop (which retries tightly and
    leaves sockets open on auth errors). For each attempt we open exactly one
    connection, fully tearing down any prior socket first, then consume until
    it drops. Backoff doubles on each failure (capped), resets after a stable
    uptime, and a longer fixed cooldown is used for the connection-limit error.
    """
    global _SHOULD_RUN
    backoff = _BACKOFF_BASE_SEC

    # Make the running loop visible to the SDK so dynamic subscribe() calls
    # (which use run_coroutine_threadsafe on _stream._loop) keep working.
    try:
        _stream._loop = asyncio.get_running_loop()
    except Exception:
        pass

    while _SHOULD_RUN:
        connected_at = None
        try:
            # Ensure no overlapping connection is still held before opening a
            # new one — closing is what releases Alpaca's single-conn slot.
            await _close_stream_socket()

            await _stream._start_ws()        # connect + auth (raises on failure)
            await _stream._send_subscribe_msg()
            _stream._running = True
            connected_at = time.monotonic()
            log.info('[ALPACA] Stream connected (iex feed)')

            await _stream._consume()         # blocks until the socket drops

            # Normal return from _consume means a stop was requested.
            if not _SHOULD_RUN:
                break

        except asyncio.CancelledError:
            break
        except Exception as e:
            # Always release the socket so the server stops counting it.
            await _close_stream_socket()

            if _is_conn_limit_error(e):
                # A prior connection is still held server-side; hammering makes
                # it worse, so wait a longer fixed cooldown.
                _log_throttled(
                    'conn_limit',
                    '[ALPACA] connection limit exceeded — a prior connection '
                    f'is still held; cooling down {_CONN_LIMIT_COOLDOWN:.0f}s',
                )
                await _interruptible_sleep(_CONN_LIMIT_COOLDOWN)
                # Keep escalating ordinary backoff too, but at least the cap.
                backoff = min(max(backoff, _BACKOFF_CAP_SEC / 2), _BACKOFF_CAP_SEC)
                continue

            _log_throttled(
                f'ws_err:{type(e).__name__}',
                f'[ALPACA] websocket error, reconnecting in {backoff:.0f}s: {e}',
            )
        finally:
            _stream._running = False

        if not _SHOULD_RUN:
            break

        # If the connection stayed up long enough, treat it as healthy and
        # reset the backoff to base; otherwise keep escalating.
        if connected_at is not None and (time.monotonic() - connected_at) >= _STABLE_RESET_SEC:
            backoff = _BACKOFF_BASE_SEC

        await _interruptible_sleep(backoff)
        backoff = min(backoff * 2, _BACKOFF_CAP_SEC)

    await _close_stream_socket()
    log.info('[ALPACA] Stream supervisor stopped')


async def _close_stream_socket() -> None:
    """Fully close and await teardown of any open websocket, ignoring errors."""
    try:
        if _stream is not None and getattr(_stream, '_ws', None) is not None:
            await _stream.close()
    except Exception as e:
        log.debug('[ALPACA] error closing socket (ignored): %s', e)
    finally:
        if _stream is not None:
            _stream._running = False


async def _interruptible_sleep(seconds: float) -> None:
    """Sleep that bails out early if a stop has been signalled."""
    step = 1.0
    waited = 0.0
    while waited < seconds and _SHOULD_RUN:
        await asyncio.sleep(min(step, seconds - waited))
        waited += step


def stop_stream() -> None:
    """Signal the supervisor to stop and tear down the connection."""
    global _SHOULD_RUN
    _SHOULD_RUN = False

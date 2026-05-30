"""
Polygon.io WebSocket streams.

Roles:
  1. Forex primary: real-time quotes for 7 major forex pairs (wss://socket.polygon.io/forex)
  2. Crypto failover: activated by StreamManager when Binance drops (wss://socket.polygon.io/crypto)

All data is routed through StreamManager — no direct SocketIO emission.
Symbol normalization: X:BTCUSD → BTC-USD, C:EURUSD → EURUSD=X

Free-tier constraints respected:
  - 1 WebSocket connection per cluster (forex + crypto are separate clusters)
  - ~10-15 symbol subscription budget (7 forex + up to 8 crypto failover)
"""

import json
import logging
import threading
import time

from stream_manager import Bar, StreamManager, Tick, normalize_polygon

log = logging.getLogger(__name__)

FOREX_SYMBOLS = [
    'C:EURUSD', 'C:GBPUSD', 'C:USDJPY',
    'C:AUDUSD', 'C:USDCAD', 'C:USDCHF', 'C:NZDUSD',
]

# Binance format → Polygon crypto format for failover
CRYPTO_FAILOVER_MAP: dict[str, str] = {
    'BTC-USD':  'X:BTCUSD',
    'ETH-USD':  'X:ETHUSD',
    'SOL-USD':  'X:SOLUSD',
    'BNB-USD':  'X:BNBUSD',
    'XRP-USD':  'X:XRPUSD',
    'ADA-USD':  'X:ADAUSD',
    'AVAX-USD': 'X:AVAXUSD',
    'DOGE-USD': 'X:DOGEUSD',
}


class _PolygonCluster:
    """
    Manages one Polygon WebSocket cluster connection (forex OR crypto).
    Reconnects with exponential backoff on disconnect.
    """

    def __init__(self, url: str, api_key: str, stream_manager: StreamManager, cluster: str):
        self._url = url
        self._api_key = api_key
        self._sm = stream_manager
        self._cluster = cluster   # 'forex' or 'crypto'
        self._ws = None
        self._lock = threading.Lock()
        self._subscribed: set[str] = set()
        self._authenticated = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, initial_subs: list[str] = None) -> None:
        if initial_subs:
            with self._lock:
                self._subscribed.update(initial_subs)
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=f'polygon-{self._cluster}'
        )
        self._thread.start()

    def subscribe(self, symbols: list[str]) -> None:
        with self._lock:
            new = [s for s in symbols if s not in self._subscribed]
            self._subscribed.update(new)
        if new and self._ws and self._authenticated:
            self._send_sub(self._ws, new)

    def stop(self) -> None:
        self._stop.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    def _run(self) -> None:
        import websocket
        backoff = 1.0
        while not self._stop.is_set():
            log.debug("[POLYGON/%s] Connecting to %s", self._cluster, self._url)
            try:
                ws = websocket.WebSocketApp(
                    self._url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._ws = ws
                self._authenticated = False
                ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as e:
                log.error("[POLYGON/%s] Exception: %s", self._cluster, e)

            if self._stop.is_set():
                break
            log.debug("[POLYGON/%s] Disconnected, retry in %.0fs", self._cluster, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

    def _on_open(self, ws) -> None:
        log.debug("[POLYGON/%s] Connected — authenticating", self._cluster)
        ws.send(json.dumps({'action': 'auth', 'params': self._api_key}))

    def _on_message(self, ws, raw: str) -> None:
        try:
            events = json.loads(raw)
        except Exception:
            return
        for ev in events:
            evt = ev.get('ev')
            if evt == 'status':
                self._handle_status(ws, ev)
            elif evt in ('CA', 'C'):
                self._handle_forex(ev)
            elif evt in ('XA', 'XT', 'XQ'):
                self._handle_crypto(ev)

    def _handle_status(self, ws, ev: dict) -> None:
        s = ev.get('status', '')
        if s == 'auth_success':
            log.debug("[POLYGON/%s] Authenticated", self._cluster)
            self._authenticated = True
            with self._lock:
                subs = list(self._subscribed)
            if subs:
                self._send_sub(ws, subs)
        elif s == 'auth_failed':
            log.error("[POLYGON/%s] Authentication failed — check POLYGON_KEY", self._cluster)
        else:
            log.debug("[POLYGON/%s] Status: %s %s", self._cluster, s, ev.get('message', ''))

    def _handle_forex(self, ev: dict) -> None:
        raw_sym = ev.get('p', ev.get('pair', ''))
        if not raw_sym:
            return
        # Polygon forex pairs come as "EUR/USD" in CA events, or "C:EURUSD" key form
        # Normalize: "EUR/USD" → "EURUSD=X"; "C:EURUSD" → "EURUSD=X"
        if '/' in raw_sym:
            symbol = raw_sym.replace('/', '') + '=X'
        else:
            symbol = normalize_polygon('C:' + raw_sym) if not raw_sym.startswith('C:') else normalize_polygon(raw_sym)

        mid = ev.get('c', ev.get('a', 0)) or ev.get('o', 0)
        if not mid:
            bid = ev.get('b', 0)
            ask = ev.get('a', 0)
            mid = (bid + ask) / 2 if bid and ask else 0
        if not mid:
            return

        bid = ev.get('b', 0) or 0
        ask = ev.get('a', 0) or 0
        ts = ev.get('t', ev.get('s', 0))
        if ts and ts > 1e12:
            ts /= 1000.0

        tick = Tick(
            symbol=symbol,
            price=float(mid),
            size=0.0,
            timestamp=float(ts) if ts else time.time(),
            source='polygon',
            bid=float(bid) if bid else None,
            ask=float(ask) if ask else None,
        )
        self._sm.on_tick(tick)

    def _handle_crypto(self, ev: dict) -> None:
        raw_sym = ev.get('pair', ev.get('sym', ''))
        if not raw_sym:
            return
        # Polygon crypto: "BTC-USD", "X:BTCUSD", or "BTC/USD"
        if raw_sym.startswith('X:'):
            symbol = normalize_polygon(raw_sym)
        elif '/' in raw_sym:
            symbol = raw_sym.replace('/', '-')
        else:
            symbol = raw_sym

        evt = ev.get('ev', '')
        if evt == 'XA':
            # Crypto aggregate bar
            bar = Bar(
                symbol=symbol,
                interval='1m',
                open=float(ev.get('o', 0)),
                high=float(ev.get('h', 0)),
                low=float(ev.get('l', 0)),
                close=float(ev.get('c', 0)),
                volume=float(ev.get('av', ev.get('v', 0))),
                vwap=float(ev.get('vw', 0)) or None,
                timestamp=ev.get('s', 0) / 1000.0 if ev.get('s', 0) > 1e12 else ev.get('s', 0),
                closed=True,
                source='polygon',
            )
            self._sm.on_bar(bar)
        else:
            # XT trade or XQ quote
            price = float(ev.get('p', ev.get('bp', 0)) or 0)
            if not price:
                return
            ts = ev.get('t', ev.get('s', 0))
            if ts and ts > 1e12:
                ts /= 1000.0
            tick = Tick(
                symbol=symbol,
                price=price,
                size=float(ev.get('s', ev.get('bs', 0)) or 0),
                timestamp=float(ts) if ts else time.time(),
                source='polygon',
                trade_id=str(ev.get('i', '')),
            )
            self._sm.on_tick(tick)

    def _send_sub(self, ws, symbols: list[str]) -> None:
        params = ','.join(symbols)
        try:
            ws.send(json.dumps({'action': 'subscribe', 'params': params}))
            log.debug("[POLYGON/%s] Subscribed: %s", self._cluster, params)
        except Exception as e:
            log.error("[POLYGON/%s] Subscribe error: %s", self._cluster, e)

    def _on_error(self, ws, error) -> None:
        log.error("[POLYGON/%s] Error: %s", self._cluster, error)

    def _on_close(self, ws, code, msg) -> None:
        log.debug("[POLYGON/%s] Closed (code=%s)", self._cluster, code)
        self._authenticated = False


# Module-level cluster handles
_forex_cluster: _PolygonCluster | None = None
_crypto_cluster: _PolygonCluster | None = None
_api_key_global: str = ''
_sm_global: StreamManager | None = None


def start_stream(api_key: str, stream_manager: StreamManager) -> None:
    """Start Polygon forex stream (primary) and prepare crypto cluster for failover."""
    global _forex_cluster, _crypto_cluster, _api_key_global, _sm_global
    _api_key_global = api_key
    _sm_global = stream_manager

    try:
        import websocket  # noqa: F401
    except ImportError:
        log.error("[POLYGON] websocket-client not installed. Run: pip install websocket-client")
        return

    # Forex cluster — subscribe all 7 pairs at start
    # Polygon forex: subscribe with e.g. "CA.EUR/USD" or "C.EUR/USD"
    # On the forex cluster, the subscription format is "CA.*" (currency aggregate)
    forex_subs = [s.replace('C:', 'CA.').replace('USD', '/USD').replace('EUR/', 'EUR/') for s in FOREX_SYMBOLS]
    # Simplest reliable format for Polygon forex WS: "CA.*"
    forex_subs_formatted = []
    for s in FOREX_SYMBOLS:
        # C:EURUSD → CA.EUR/USD
        pair = s[2:]  # EURUSD
        if pair.endswith('USD') and len(pair) == 6:
            formatted = f"CA.{pair[:3]}/USD"
        elif pair.startswith('USD') and len(pair) == 6:
            formatted = f"CA.USD/{pair[3:]}"
        else:
            formatted = f"CA.{pair[:3]}/{pair[3:]}"
        forex_subs_formatted.append(formatted)

    _forex_cluster = _PolygonCluster(
        'wss://socket.polygon.io/forex',
        api_key,
        stream_manager,
        'forex',
    )
    _forex_cluster.start(forex_subs_formatted)

    # Crypto cluster — start connected but no subscriptions until Binance fails
    _crypto_cluster = _PolygonCluster(
        'wss://socket.polygon.io/crypto',
        api_key,
        stream_manager,
        'crypto',
    )
    _crypto_cluster.start([])  # subscribes on failover


def activate_crypto_failover(symbols: list[str]) -> None:
    """
    Called by StreamManager when Binance goes dead for given symbols.
    Subscribes those symbols on the Polygon crypto cluster.
    """
    global _crypto_cluster
    if not _crypto_cluster:
        return
    poly_syms = []
    for sym in symbols:
        poly_raw = CRYPTO_FAILOVER_MAP.get(sym)
        if poly_raw:
            # Subscribe both aggregate and trade channels
            pair = poly_raw[2:]  # BTCUSD → for XT.BTC-USD
            if pair.endswith('USD') and len(pair) > 3:
                base = pair[:-3]
                poly_syms.append(f"XA.{base}-USD")
                poly_syms.append(f"XT.{base}-USD")
    if poly_syms:
        _crypto_cluster.subscribe(poly_syms)
        log.debug("[POLYGON/crypto] Failover subscribed: %s", poly_syms)


def subscribe(symbol: str) -> None:
    """Legacy-compatible: subscribe a symbol to the forex cluster."""
    global _forex_cluster
    if _forex_cluster:
        _forex_cluster.subscribe([symbol])

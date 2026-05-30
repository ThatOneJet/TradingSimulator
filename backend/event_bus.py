"""
Lightweight publish-subscribe event bus.

Uses asyncio.Queue in-process by default.
Upgrades to Redis Pub/Sub when REDIS_URL env var is set and redis is installed.

Channel conventions:
  tick:{SYMBOL}            – raw tick (deduplicated, normalized)
  bar:{SYMBOL}:{INTERVAL}  – closed candle + indicators
  ai:scan:{PORTFOLIO_ID}   – scan batch complete
  position:{PORTFOLIO_ID}  – buy/sell executed → frontend push
  alert:{PORTFOLIO_ID}     – signal threshold crossed
  stream:failover          – source went dead, failover activated

Glob patterns are supported in subscribe(): e.g. "bar:*:1m" or "tick:*".
"""

import fnmatch
import json
import logging
import os
import threading
from collections import defaultdict
from typing import Any, Callable

log = logging.getLogger(__name__)


class _AsyncioEventBus:
    """In-process event bus backed by plain thread-safe structures."""

    def __init__(self):
        self._lock = threading.Lock()
        # {pattern: [handler, ...]}
        self._subs: dict[str, list[Callable]] = defaultdict(list)

    def publish(self, channel: str, data: Any) -> None:
        handlers = []
        with self._lock:
            for pattern, hs in self._subs.items():
                if fnmatch.fnmatchcase(channel, pattern):
                    handlers.extend(hs)
        for h in handlers:
            try:
                h(channel, data)
            except Exception:
                log.exception("EventBus handler error on channel %s", channel)

    def subscribe(self, pattern: str, handler: Callable) -> None:
        with self._lock:
            if handler not in self._subs[pattern]:
                self._subs[pattern].append(handler)

    def unsubscribe(self, pattern: str, handler: Callable) -> None:
        with self._lock:
            try:
                self._subs[pattern].remove(handler)
            except ValueError:
                pass

    def start(self) -> None:
        pass  # nothing to start for in-process bus


class _RedisEventBus:
    """Redis Pub/Sub-backed event bus (optional; requires redis package + REDIS_URL)."""

    def __init__(self, url: str):
        import redis
        self._r = redis.from_url(url)
        self._pub = redis.from_url(url)
        self._lock = threading.Lock()
        # {pattern: [handler, ...]}
        self._subs: dict[str, list[Callable]] = defaultdict(list)
        self._patterns: set[str] = set()
        self._ps = None
        self._thread: threading.Thread | None = None

    def publish(self, channel: str, data: Any) -> None:
        payload = json.dumps(data, default=str)
        self._pub.publish(channel, payload)

    def subscribe(self, pattern: str, handler: Callable) -> None:
        with self._lock:
            if handler not in self._subs[pattern]:
                self._subs[pattern].append(handler)
            if pattern not in self._patterns and self._ps is not None:
                self._ps.psubscribe(pattern)
                self._patterns.add(pattern)

    def unsubscribe(self, pattern: str, handler: Callable) -> None:
        with self._lock:
            try:
                self._subs[pattern].remove(handler)
            except ValueError:
                pass

    def start(self) -> None:
        import redis
        self._ps = self._r.pubsub()
        with self._lock:
            for p in self._subs:
                self._ps.psubscribe(p)
                self._patterns.add(p)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.debug("[EVENTBUS] Redis backend started at %s", self._pub.connection_pool.connection_kwargs.get('host', '?'))

    def _run(self) -> None:
        for msg in self._ps.listen():
            if msg['type'] != 'pmessage':
                continue
            channel = msg['channel']
            if isinstance(channel, bytes):
                channel = channel.decode()
            try:
                data = json.loads(msg['data'])
            except Exception:
                data = msg['data']
            pattern_key = msg['pattern']
            if isinstance(pattern_key, bytes):
                pattern_key = pattern_key.decode()
            handlers = []
            with self._lock:
                for pat, hs in self._subs.items():
                    if fnmatch.fnmatchcase(channel, pat):
                        handlers.extend(hs)
            for h in handlers:
                try:
                    h(channel, data)
                except Exception:
                    log.exception("EventBus Redis handler error on %s", channel)


def create_event_bus():
    """Return the best available EventBus implementation."""
    url = os.environ.get('REDIS_URL', '')
    if url:
        try:
            import redis
            bus = _RedisEventBus(url)
            log.debug("[EVENTBUS] Using Redis backend: %s", url)
            return bus
        except ImportError:
            log.debug("[EVENTBUS] REDIS_URL set but redis package not installed; using in-process bus")
    bus = _AsyncioEventBus()
    log.debug("[EVENTBUS] Using in-process asyncio bus")
    return bus


# Module-level singleton
event_bus = create_event_bus()

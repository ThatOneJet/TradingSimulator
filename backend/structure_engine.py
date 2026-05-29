"""
StructureEngine — detects market structure from real-time 1m bars.

Provides:
  - Swing point tracking: HH, HL, LH, LL (zigzag with ATR-based threshold)
  - Break of Structure (BOS) detection
  - Support/Resistance zone mapping from clustered swing points
  - Fair Value Gap (FVG) detection: 3-candle pattern leaving untouched price gaps
  - Session levels: opening range, session high/low, prior day levels
  - Consolidation range detection

Subscribes to bar:*:1m on EventBus.
Call StructureEngine.snapshot(symbol) to get the current structure dict.
"""

import logging
import statistics
import threading
import time
from collections import deque, defaultdict
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal data holder
# ---------------------------------------------------------------------------

@dataclass
class _Bar:
    open:  float
    high:  float
    low:   float
    close: float
    atr:   float
    ts:    float  # Unix timestamp of bar open


# ---------------------------------------------------------------------------
# Swing Detector
# ---------------------------------------------------------------------------

class SwingDetector:
    """
    Detects swing highs and lows using a 3-bar zigzag pattern.
    Classifies each swing as HH, HL, LH, or LL.
    Tracks BOS (Break of Structure) events.
    """

    def __init__(self):
        self._bars: deque = deque(maxlen=200)
        self._swings: list = []          # {type, price, ts}
        self._last_swing_high: Optional[float] = None
        self._last_swing_low:  Optional[float] = None
        self._last_bos: Optional[dict] = None
        # track recent LH and HL prices for BOS checking
        self._last_lh_price: Optional[float] = None
        self._last_hl_price: Optional[float] = None

    def update(self, bar: _Bar) -> Optional[dict]:
        """
        Add a new bar. Returns a new swing dict if one was detected, else None.
        """
        try:
            self._bars.append(bar)
            if len(self._bars) < 5:
                return None

            bars = list(self._bars)
            b1, b2, b3 = bars[-3], bars[-2], bars[-1]
            atr = b2.atr or (b2.close * 0.02)
            threshold = 0.3 * atr

            new_swing = None

            # --- Swing High ---
            if b1.high < b2.high > b3.high and (b2.high - max(b1.high, b3.high)) >= threshold:
                price = b2.high
                if self._last_swing_high is None or price > self._last_swing_high:
                    swing_type = 'HH'
                else:
                    swing_type = 'LH'
                    self._last_lh_price = price  # track for BOS

                new_swing = {'type': swing_type, 'price': price, 'ts': b2.ts}
                self._last_swing_high = price

            # --- Swing Low ---
            elif b1.low > b2.low < b3.low and (min(b1.low, b3.low) - b2.low) >= threshold:
                price = b2.low
                if self._last_swing_low is None or price > self._last_swing_low:
                    swing_type = 'HL'
                    self._last_hl_price = price  # track for BOS
                else:
                    swing_type = 'LL'

                new_swing = {'type': swing_type, 'price': price, 'ts': b2.ts}
                self._last_swing_low = price

            if new_swing:
                self._swings.append(new_swing)
                if len(self._swings) > 20:
                    self._swings = self._swings[-20:]

            # --- BOS detection using current close ---
            close = bar.close
            self._check_bos(close, bar.ts)

            return new_swing

        except Exception:
            log.exception("[STRUCTURE] SwingDetector.update error")
            return None

    def _check_bos(self, close: float, ts: float) -> None:
        """Check if close breaks structure (BOS)."""
        try:
            # Bullish BOS: close above the most recent LH (breaks bearish structure)
            if self._last_lh_price is not None and close > self._last_lh_price:
                if self._last_bos is None or self._last_bos.get('price') != self._last_lh_price:
                    self._last_bos = {
                        'direction': 'bullish',
                        'price': self._last_lh_price,
                        'ts': ts,
                    }
                    self._last_lh_price = None  # consumed

            # Bearish BOS: close below the most recent HL (breaks bullish structure)
            elif self._last_hl_price is not None and close < self._last_hl_price:
                if self._last_bos is None or self._last_bos.get('price') != self._last_hl_price:
                    self._last_bos = {
                        'direction': 'bearish',
                        'price': self._last_hl_price,
                        'ts': ts,
                    }
                    self._last_hl_price = None  # consumed
        except Exception:
            log.exception("[STRUCTURE] BOS check error")

    def structure_bias(self) -> str:
        """
        Determine market bias from the last 4 swings.
        Returns 'bullish', 'bearish', or 'undefined'.
        """
        try:
            recent = self._swings[-4:]
            if len(recent) < 4:
                return 'undefined'

            types = [s['type'] for s in recent]
            highs = [t for t in types if t in ('HH', 'LH')]
            lows  = [t for t in types if t in ('HL', 'LL')]

            if all(t == 'HH' for t in highs) and all(t == 'HL' for t in lows) and highs and lows:
                return 'bullish'
            if all(t == 'LH' for t in highs) and all(t == 'LL' for t in lows) and highs and lows:
                return 'bearish'
            return 'undefined'
        except Exception:
            log.exception("[STRUCTURE] structure_bias error")
            return 'undefined'

    def last_bos(self) -> Optional[dict]:
        """Return the most recent BOS event dict, or None."""
        return self._last_bos


# ---------------------------------------------------------------------------
# Support / Resistance
# ---------------------------------------------------------------------------

class SupportResistance:
    """
    Clusters swing highs into resistance zones and swing lows into support zones.
    Keeps the 3 nearest support and 3 nearest resistance zones.
    """

    def __init__(self):
        self._zones: list = []  # {price, type, touches, ts}

    def update(self, swings: list, atr: float) -> None:
        """Rebuild zones from the current swing list."""
        try:
            if not swings or atr <= 0:
                return

            cluster_dist = 0.5 * atr

            highs = [s for s in swings if s['type'] in ('HH', 'LH')]
            lows  = [s for s in swings if s['type'] in ('HL', 'LL')]

            resistance_zones = self._cluster(highs, cluster_dist, 'resistance')
            support_zones    = self._cluster(lows,  cluster_dist, 'support')

            # Keep top 3 of each by touch count, then trim to nearest 6 total
            resistance_zones = sorted(resistance_zones, key=lambda z: z['touches'], reverse=True)[:3]
            support_zones    = sorted(support_zones,    key=lambda z: z['touches'], reverse=True)[:3]

            self._zones = resistance_zones + support_zones
        except Exception:
            log.exception("[STRUCTURE] SupportResistance.update error")

    @staticmethod
    def _cluster(swings: list, dist: float, zone_type: str) -> list:
        """Group swings within `dist` of each other into zones."""
        if not swings:
            return []

        prices = sorted(s['price'] for s in swings)
        clusters: list[list[float]] = []
        current_cluster: list[float] = [prices[0]]

        for p in prices[1:]:
            if p - current_cluster[-1] <= dist:
                current_cluster.append(p)
            else:
                clusters.append(current_cluster)
                current_cluster = [p]
        clusters.append(current_cluster)

        zones = []
        for cluster in clusters:
            median_price = statistics.median(cluster)
            # Find latest ts among swings that fall in this cluster
            latest_ts = max(
                s['ts'] for s in swings
                if abs(s['price'] - median_price) <= dist
            )
            zones.append({
                'price':   median_price,
                'type':    zone_type,
                'touches': len(cluster),
                'ts':      latest_ts,
            })
        return zones

    def nearest_support(self, price: float) -> Optional[float]:
        """Highest support zone price below current price."""
        try:
            candidates = [z['price'] for z in self._zones if z['type'] == 'support' and z['price'] < price]
            return max(candidates) if candidates else None
        except Exception:
            return None

    def nearest_resistance(self, price: float) -> Optional[float]:
        """Lowest resistance zone price above current price."""
        try:
            candidates = [z['price'] for z in self._zones if z['type'] == 'resistance' and z['price'] > price]
            return min(candidates) if candidates else None
        except Exception:
            return None

    def at_key_level(self, price: float, atr: float) -> bool:
        """True if price is within 0.3×ATR of any zone."""
        try:
            margin = 0.3 * atr
            return any(abs(z['price'] - price) <= margin for z in self._zones)
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Fair Value Gap Detector
# ---------------------------------------------------------------------------

class FVGDetector:
    """
    Detects Fair Value Gaps (imbalances) using a 3-candle pattern.
    Tracks filled/unfilled status and discards stale FVGs.
    """

    _MAX_AGE_SECONDS = 4 * 3600  # 4 hours

    def __init__(self):
        self._bars: deque = deque(maxlen=100)
        self._fvgs: list = []  # {type, top, bottom, ts, filled}

    def update(self, bar: _Bar, current_price: float) -> list:
        """
        Add bar, detect new FVGs, mark filled ones.
        Returns list of newly detected FVGs (may be empty).
        """
        try:
            self._bars.append(bar)
            new_fvgs = []

            if len(self._bars) >= 3:
                b1, b2, b3 = list(self._bars)[-3], list(self._bars)[-2], list(self._bars)[-1]

                # Bullish FVG: bar1.high < bar3.low — gap going up
                if b1.high < b3.low:
                    fvg = {
                        'type':   'bullish',
                        'top':    b3.low,
                        'bottom': b1.high,
                        'ts':     b2.ts,
                        'filled': False,
                    }
                    new_fvgs.append(fvg)
                    self._fvgs.append(fvg)

                # Bearish FVG: bar1.low > bar3.high — gap going down
                elif b1.low > b3.high:
                    fvg = {
                        'type':   'bearish',
                        'top':    b1.low,
                        'bottom': b3.high,
                        'ts':     b2.ts,
                        'filled': False,
                    }
                    new_fvgs.append(fvg)
                    self._fvgs.append(fvg)

            # Mark filled FVGs
            now = time.time()
            for fvg in self._fvgs:
                if fvg['filled']:
                    continue
                if fvg['type'] == 'bullish' and current_price < fvg['bottom']:
                    fvg['filled'] = True
                elif fvg['type'] == 'bearish' and current_price > fvg['top']:
                    fvg['filled'] = True

            # Discard stale FVGs (older than 4 hours) and keep last 10
            self._fvgs = [
                f for f in self._fvgs
                if (now - f['ts']) < self._MAX_AGE_SECONDS
            ][-10:]

            return new_fvgs

        except Exception:
            log.exception("[STRUCTURE] FVGDetector.update error")
            return []

    def nearest_unfilled(self, price: float, direction: str) -> Optional[dict]:
        """
        direction='above' → nearest unfilled FVG above price (potential resistance / target).
        direction='below' → nearest unfilled FVG below price (potential support / target).
        """
        try:
            unfilled = [f for f in self._fvgs if not f['filled']]
            if direction == 'above':
                candidates = [f for f in unfilled if f['bottom'] > price]
                return min(candidates, key=lambda f: f['bottom']) if candidates else None
            elif direction == 'below':
                candidates = [f for f in unfilled if f['top'] < price]
                return max(candidates, key=lambda f: f['top']) if candidates else None
            return None
        except Exception:
            log.exception("[STRUCTURE] FVGDetector.nearest_unfilled error")
            return None

    def recent_unfilled(self, n: int = 5) -> list:
        """Return the n most recent unfilled FVGs (newest first)."""
        try:
            unfilled = [f for f in self._fvgs if not f['filled']]
            return list(reversed(unfilled))[:n]
        except Exception:
            return []


# ---------------------------------------------------------------------------
# Session Levels
# ---------------------------------------------------------------------------

class SessionLevels:
    """
    Tracks US equity session levels (09:30–16:00 ET) or UTC-day sessions for crypto.
    Maintains session high/low, opening range (first 30 bars), and prior day levels.
    """

    # Opening range = first 30 1m bars of the session
    _OR_BARS = 30
    # US equity session open in ET: 09:30 → UTC offset -5h (EST) or -4h (EDT).
    # We approximate using UTC 14:30 (EST winter) as a simple heuristic.
    _SESSION_OPEN_UTC_HOUR = 14
    _SESSION_OPEN_UTC_MIN  = 30
    _SESSION_CLOSE_UTC_HOUR = 21  # 16:00 ET ≈ 21:00 UTC

    def __init__(self):
        self._session_high:  Optional[float] = None
        self._session_low:   Optional[float] = None
        self._or_high:       Optional[float] = None
        self._or_low:        Optional[float] = None
        self._or_established: bool = False
        self._pdh:           Optional[float] = None  # prior day high
        self._pdl:           Optional[float] = None  # prior day low
        self._current_date:  Optional[str]   = None
        self._or_bar_count:  int = 0
        self._prev_session_high: Optional[float] = None
        self._prev_session_low:  Optional[float] = None

    def on_bar(self, bar: _Bar, symbol: str) -> None:
        try:
            import datetime
            dt = datetime.datetime.utcfromtimestamp(bar.ts)
            date_str = dt.strftime('%Y-%m-%d')

            # Detect new session
            if date_str != self._current_date:
                # Save prior session levels as PDH/PDL
                if self._session_high is not None:
                    self._pdh = self._session_high
                if self._session_low is not None:
                    self._pdl = self._session_low

                # Reset session state
                self._current_date   = date_str
                self._session_high   = bar.high
                self._session_low    = bar.low
                self._or_high        = bar.high
                self._or_low         = bar.low
                self._or_established = False
                self._or_bar_count   = 1
            else:
                # Update session high/low
                if self._session_high is None or bar.high > self._session_high:
                    self._session_high = bar.high
                if self._session_low is None or bar.low < self._session_low:
                    self._session_low = bar.low

                # Opening range: first 30 bars
                if not self._or_established:
                    self._or_bar_count += 1
                    if self._or_high is None or bar.high > self._or_high:
                        self._or_high = bar.high
                    if self._or_low is None or bar.low < self._or_low:
                        self._or_low = bar.low
                    if self._or_bar_count >= self._OR_BARS:
                        self._or_established = True

        except Exception:
            log.exception("[STRUCTURE] SessionLevels.on_bar error")

    def get(self) -> dict:
        return {
            'session_high':    self._session_high,
            'session_low':     self._session_low,
            'or_high':         self._or_high,
            'or_low':          self._or_low,
            'pdh':             self._pdh,
            'pdl':             self._pdl,
            'or_established':  self._or_established,
        }


# ---------------------------------------------------------------------------
# Per-symbol state container
# ---------------------------------------------------------------------------

class _SymbolState:
    __slots__ = ('swing', 'sr', 'fvg', 'session', 'bars', 'lock')

    def __init__(self):
        self.swing   = SwingDetector()
        self.sr      = SupportResistance()
        self.fvg     = FVGDetector()
        self.session = SessionLevels()
        self.bars: deque = deque(maxlen=20)  # last 20 bars for consolidation check
        self.lock    = threading.Lock()


# ---------------------------------------------------------------------------
# StructureEngine
# ---------------------------------------------------------------------------

class StructureEngine:
    """
    Wires SwingDetector, SupportResistance, FVGDetector, and SessionLevels
    together per symbol. Subscribes to bar:*:1m on the EventBus.

    Usage:
        engine = StructureEngine(event_bus)
        engine.start()
        snap = engine.snapshot('AAPL')
    """

    _EMPTY_SNAPSHOT = {
        'swing_bias':          'undefined',
        'last_bos':            None,
        'nearest_support':     None,
        'nearest_resistance':  None,
        'at_key_level':        False,
        'fvg_below':           None,
        'fvg_above':           None,
        'recent_fvgs':         [],
        'session':             {},
        'in_consolidation':    False,
        'swing_count':         0,
    }

    def __init__(self, event_bus):
        self._bus   = event_bus
        self._data: dict[str, _SymbolState] = {}
        self._lock  = threading.Lock()  # guards _data dict keys only

    def start(self) -> None:
        """Subscribe to 1m bars and begin processing."""
        self._bus.subscribe('bar:*:1m', self._on_bar)
        log.info("[STRUCTURE] StructureEngine started — listening on bar:*:1m")

    def _get_or_create(self, symbol: str) -> _SymbolState:
        """Return existing state or create a new one (thread-safe)."""
        with self._lock:
            if symbol not in self._data:
                self._data[symbol] = _SymbolState()
            return self._data[symbol]

    def _on_bar(self, channel: str, bar_dict: dict) -> None:
        """Handle an incoming 1m closed bar from the EventBus."""
        try:
            symbol = bar_dict.get('symbol')
            if not symbol:
                # Fallback: extract from channel 'bar:{symbol}:1m'
                parts = channel.split(':')
                symbol = parts[1] if len(parts) >= 2 else None
            if not symbol:
                return

            # Only process closed bars
            if not bar_dict.get('closed', True):
                return

            try:
                open_  = float(bar_dict['open'])
                high   = float(bar_dict['high'])
                low    = float(bar_dict['low'])
                close  = float(bar_dict['close'])
            except (KeyError, TypeError, ValueError):
                log.warning("[STRUCTURE] Bad bar payload on %s: %s", channel, bar_dict)
                return

            atr_raw = bar_dict.get('atr')
            atr = float(atr_raw) if atr_raw else close * 0.02
            ts  = float(bar_dict.get('timestamp', time.time()))

            bar = _Bar(open=open_, high=high, low=low, close=close, atr=atr, ts=ts)

            state = self._get_or_create(symbol)
            with state.lock:
                state.bars.append(bar)
                state.swing.update(bar)
                state.sr.update(state.swing._swings, atr)
                state.fvg.update(bar, close)
                state.session.on_bar(bar, symbol)

        except Exception:
            log.exception("[STRUCTURE] _on_bar unhandled error on channel %s", channel)

    @staticmethod
    def _is_consolidating(bars: deque) -> bool:
        """True if the last 20 bars have a range less than 1.5×ATR."""
        try:
            if len(bars) < 5:
                return False
            bar_list = list(bars)
            highs  = [b.high  for b in bar_list]
            lows   = [b.low   for b in bar_list]
            atrs   = [b.atr   for b in bar_list if b.atr > 0]
            rng    = max(highs) - min(lows)
            avg_atr = sum(atrs) / len(atrs) if atrs else bar_list[-1].close * 0.02
            return rng < 1.5 * avg_atr
        except Exception:
            return False

    def snapshot(self, symbol: str) -> dict:
        """
        Thread-safe snapshot of all structure data for a symbol.
        Returns an empty-valued dict if the symbol has not been tracked yet.
        """
        try:
            with self._lock:
                state = self._data.get(symbol)
            if state is None:
                return dict(self._EMPTY_SNAPSHOT)

            with state.lock:
                close = state.bars[-1].close if state.bars else 0.0
                atr   = state.bars[-1].atr   if state.bars else 0.02

                bias           = state.swing.structure_bias()
                last_bos       = state.swing.last_bos()
                nearest_sup    = state.sr.nearest_support(close)
                nearest_res    = state.sr.nearest_resistance(close)
                at_key         = state.sr.at_key_level(close, atr)
                fvg_below      = state.fvg.nearest_unfilled(close, 'below')
                fvg_above      = state.fvg.nearest_unfilled(close, 'above')
                recent_fvgs    = state.fvg.recent_unfilled(5)
                session        = state.session.get()
                in_consol      = self._is_consolidating(state.bars)
                swing_count    = len(state.swing._swings)

            return {
                'swing_bias':          bias,
                'last_bos':            last_bos,
                'nearest_support':     nearest_sup,
                'nearest_resistance':  nearest_res,
                'at_key_level':        at_key,
                'fvg_below':           fvg_below,
                'fvg_above':           fvg_above,
                'recent_fvgs':         recent_fvgs,
                'session':             session,
                'in_consolidation':    in_consol,
                'swing_count':         swing_count,
            }
        except Exception:
            log.exception("[STRUCTURE] snapshot error for %s", symbol)
            return dict(self._EMPTY_SNAPSHOT)


# ---------------------------------------------------------------------------
# Module-level singleton helpers
# ---------------------------------------------------------------------------

_engine: Optional[StructureEngine] = None


def init(event_bus) -> StructureEngine:
    """
    Create and start the module-level StructureEngine singleton.
    Call once at application startup after the EventBus is ready.
    """
    global _engine
    _engine = StructureEngine(event_bus)
    _engine.start()
    return _engine


def snapshot(symbol: str) -> dict:
    """
    Module-level convenience wrapper around StructureEngine.snapshot().
    Returns an empty snapshot dict if the engine has not been initialized.
    """
    if _engine is None:
        log.warning("[STRUCTURE] snapshot() called before init()")
        return dict(StructureEngine._EMPTY_SNAPSHOT)
    return _engine.snapshot(symbol)

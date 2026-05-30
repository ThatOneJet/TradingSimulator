"""
VolumeProfile — Point of Control (POC) and Value Area from daily volume-by-price.
Price above POC = bullish bias, below = bearish, near POC = chop/magnet.

Builds a histogram of traded volume distributed across price buckets between the
period low and high. The bucket with the most volume is the Point of Control —
a price level the market keeps returning to. The Value Area (VAH..VAL) is the
range containing 70% of total volume, expanded outward from the POC.

Trading read:
  - price above the Value Area High → accepted higher, bullish breakout
  - price below the Value Area Low  → rejected lower, bearish breakdown
  - price hugging the POC           → magnet / chop, no edge
"""

import logging
import time

log = logging.getLogger(__name__)

# How long a computed profile stays fresh (seconds)
_CACHE_TTL = 3600          # 1 hour
# Fraction of total volume that defines the Value Area
_VALUE_AREA_FRAC = 0.70
# "At POC" tolerance — within this fraction of price counts as on the POC
_POC_TOL = 0.003           # 0.3%


class VolumeProfileEngine:
    """Compute and cache per-symbol volume profiles from yfinance daily bars."""

    def __init__(self):
        # symbol -> (profile_dict, timestamp)
        self._cache: dict = {}

    # ------------------------------------------------------------------
    # Core computation
    # ------------------------------------------------------------------

    def compute(self, symbol: str, lookback_days: int = 60, bins: int = 50) -> dict:
        """
        Fetch daily bars and build a volume-by-price profile.

        Returns {poc, vah, val, current_price, position} or a neutral
        empty profile on any failure.
        """
        try:
            now = time.time()
            cached = self._cache.get(symbol)
            if cached and (now - cached[1]) < _CACHE_TTL:
                return cached[0]

            import yfinance as yf

            hist = yf.Ticker(symbol).history(period=f'{lookback_days}d')
            if hist is None or hist.empty or len(hist) < 5:
                return self._empty()

            highs   = [float(x) for x in hist['High'].tolist()]
            lows    = [float(x) for x in hist['Low'].tolist()]
            closes  = [float(x) for x in hist['Close'].tolist()]
            volumes = [float(x) for x in hist['Volume'].tolist()]
            n = len(closes)

            lo, hi = min(lows), max(highs)
            if hi <= lo:
                return self._empty()

            bin_w = (hi - lo) / bins
            if bin_w <= 0:
                return self._empty()

            # Distribute each bar's volume across the buckets its range spans
            buckets = [0.0] * bins
            for i in range(n):
                vol = volumes[i]
                if vol <= 0:
                    continue
                b_lo = int((lows[i] - lo) / bin_w)
                b_hi = int((highs[i] - lo) / bin_w)
                b_lo = max(0, min(bins - 1, b_lo))
                b_hi = max(0, min(bins - 1, b_hi))
                span = b_hi - b_lo + 1
                share = vol / span
                for b in range(b_lo, b_hi + 1):
                    buckets[b] += share

            total_vol = sum(buckets)
            if total_vol <= 0:
                return self._empty()

            # Point of Control = highest-volume bucket centre
            poc_idx = buckets.index(max(buckets))
            poc = lo + (poc_idx + 0.5) * bin_w

            # Value Area: expand outward from the POC, each step taking the
            # neighbouring bucket with the larger volume, until we've captured
            # 70% of total volume.
            vah_idx, val_idx = self._value_area(buckets, poc_idx, total_vol)
            vah = lo + (vah_idx + 0.5) * bin_w
            val = lo + (val_idx + 0.5) * bin_w

            current_price = closes[-1]
            position = self._classify(current_price, poc, vah, val)

            profile = {
                'poc':           round(poc, 6),
                'vah':           round(vah, 6),
                'val':           round(val, 6),
                'current_price': round(current_price, 6),
                'position':      position,
            }
            self._cache[symbol] = (profile, now)
            log.debug('[VOLPROFILE] %s poc=%.4f vah=%.4f val=%.4f pos=%s',
                      symbol, poc, vah, val, position)
            return profile

        except Exception as e:
            log.debug('[VOLPROFILE] compute(%s) error: %s', symbol, e)
            return self._empty()

    # ------------------------------------------------------------------
    # Signal
    # ------------------------------------------------------------------

    def get_signal(self, symbol: str) -> dict:
        """
        Derive a score (-2.0..+2.0) and description from the volume profile.

        Returns {score, description, poc, vah, val, position}.
        """
        try:
            p = self.compute(symbol)
            poc, vah, val = p['poc'], p['vah'], p['val']
            price = p['current_price']

            # No usable profile → neutral
            if not poc or not price:
                return self._neutral_signal(p)

            # On the POC → magnet / chop
            if abs(price - poc) <= poc * _POC_TOL:
                score, desc = 0.0, 'at point of control — magnet/chop'
            elif price > vah:
                score, desc = 1.2, 'above value area — bullish'
            elif price < val:
                score, desc = -1.2, 'below value area — bearish'
            elif price >= poc:
                # in value area, upper half
                score, desc = 0.4, 'in upper value area — mild bullish'
            else:
                # in value area, lower half
                score, desc = -0.4, 'in lower value area — mild bearish'

            return {
                'score':       round(float(score), 3),
                'description': desc,
                'poc':         poc,
                'vah':         vah,
                'val':         val,
                'position':    p['position'],
            }

        except Exception as e:
            log.debug('[VOLPROFILE] get_signal(%s) error: %s', symbol, e)
            return self._neutral_signal(self._empty())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _value_area(buckets: list, poc_idx: int, total_vol: float) -> tuple:
        """Expand from the POC outward until 70% of volume is captured."""
        n = len(buckets)
        lo_i = hi_i = poc_idx
        captured = buckets[poc_idx]
        target = total_vol * _VALUE_AREA_FRAC

        while captured < target and (lo_i > 0 or hi_i < n - 1):
            below = buckets[lo_i - 1] if lo_i > 0 else -1.0
            above = buckets[hi_i + 1] if hi_i < n - 1 else -1.0
            # take whichever adjacent bucket holds more volume
            if above >= below:
                hi_i += 1
                captured += buckets[hi_i]
            else:
                lo_i -= 1
                captured += buckets[lo_i]
        return hi_i, lo_i

    @staticmethod
    def _classify(price: float, poc: float, vah: float, val: float) -> str:
        if poc and abs(price - poc) <= poc * _POC_TOL:
            return 'at_poc'
        if price > vah:
            return 'above_value'
        if price < val:
            return 'below_value'
        return 'in_value'

    @staticmethod
    def _empty() -> dict:
        return {
            'poc':           0.0,
            'vah':           0.0,
            'val':           0.0,
            'current_price': 0.0,
            'position':      'in_value',
        }

    @staticmethod
    def _neutral_signal(profile: dict) -> dict:
        return {
            'score':       0.0,
            'description': 'no volume profile',
            'poc':         profile.get('poc', 0.0),
            'vah':         profile.get('vah', 0.0),
            'val':         profile.get('val', 0.0),
            'position':    profile.get('position', 'in_value'),
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine: 'VolumeProfileEngine | None' = None


def get_engine() -> VolumeProfileEngine:
    """Return the lazily-created module-level engine singleton."""
    global _engine
    if _engine is None:
        _engine = VolumeProfileEngine()
    return _engine


def get_signal(symbol: str) -> dict:
    """Volume-profile signal dict for ``symbol`` (never raises)."""
    try:
        return get_engine().get_signal(symbol)
    except Exception as e:
        log.debug('[VOLPROFILE] module get_signal error: %s', e)
        return {
            'score': 0.0, 'description': 'no volume profile',
            'poc': 0.0, 'vah': 0.0, 'val': 0.0, 'position': 'in_value',
        }


def score_contrib(symbol: str) -> float:
    """Just the float score for ``symbol`` (0.0 on failure)."""
    try:
        return float(get_signal(symbol).get('score', 0.0))
    except Exception:
        return 0.0

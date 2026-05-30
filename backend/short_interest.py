"""
ShortInterest — short interest ratio as squeeze-accelerant signal.
Heavy short interest + rising price = short squeeze fuel.
Data via yfinance Ticker.info (shortRatio, shortPercentOfFloat) where available.

Short-interest data updates only twice a month, so it is cached aggressively
(12h per symbol). The signal is meaningless without price-momentum context:
crowded shorts only become fuel when price is already turning up.
"""

import logging
import threading
import time

log = logging.getLogger(__name__)

CACHE_TTL = 12 * 3600   # 12 hours — SI data updates bi-monthly

# Thresholds for "heavy" short positioning
HEAVY_SHORT_PCT_FLOAT = 15.0   # >15% of float shorted
HEAVY_SHORT_RATIO     = 5.0    # >5 days to cover


def _classify(symbol: str) -> str:
    """Cheap asset-class classification by ticker suffix."""
    s = (symbol or '').upper()
    if s.endswith('-USD'):
        return 'crypto'
    if s.endswith('=X'):
        return 'forex'
    if s.endswith('=F'):
        return 'futures'
    return 'equity'


class ShortInterestEngine:
    """Fetches and interprets short-interest metrics for equities."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cache: dict = {}   # symbol -> {'data': {...}, 'ts': float}

    # ------------------------------------------------------------------
    # Data fetch (cached)
    # ------------------------------------------------------------------

    def get_short_data(self, symbol: str) -> dict:
        """
        Return {'short_pct_float', 'short_ratio'} for an equity, or {} if the
        data is unavailable / the symbol is not an equity. Cached for 12h.
        """
        try:
            sym = (symbol or '').upper()
            if _classify(sym) != 'equity':
                return {}

            now = time.time()
            with self._lock:
                entry = self._cache.get(sym)
                if entry and (now - entry['ts']) < CACHE_TTL:
                    return dict(entry['data'])

            data = self._fetch(sym)

            with self._lock:
                self._cache[sym] = {'data': dict(data), 'ts': now}
            return data

        except Exception as e:
            log.debug('[SHORT] get_short_data(%s) error: %s', symbol, e)
            return {}

    def _fetch(self, sym: str) -> dict:
        """Pull shortRatio / shortPercentOfFloat from yfinance Ticker.info."""
        try:
            import yfinance as yf
        except ImportError:
            log.debug('[SHORT] yfinance not installed; skipping')
            return {}

        try:
            info = yf.Ticker(sym).info or {}
        except Exception as e:
            log.debug('[SHORT] info fetch failed for %s: %s', sym, e)
            return {}

        out = {}
        try:
            spf = info.get('shortPercentOfFloat')
            if spf is not None:
                # yfinance returns a fraction (0.18) — normalise to percent.
                spf = float(spf)
                out['short_pct_float'] = round(spf * 100.0 if spf <= 1.0 else spf, 2)
        except Exception:
            pass
        try:
            sr = info.get('shortRatio')
            if sr is not None:
                out['short_ratio'] = round(float(sr), 2)
        except Exception:
            pass

        if out:
            log.debug('[SHORT] %s — pct_float=%s ratio=%s',
                      sym, out.get('short_pct_float'), out.get('short_ratio'))
        return out

    # ------------------------------------------------------------------
    # Momentum context
    # ------------------------------------------------------------------

    @staticmethod
    def _momentum_from_data(data: dict) -> str | None:
        """Derive 'up'/'down'/'flat' from a precomputed indicators dict."""
        if not isinstance(data, dict):
            return None
        trend = (data.get('trend') or '').lower()
        if trend == 'up':
            return 'up'
        if trend == 'down':
            return 'down'
        try:
            slope = data.get('slope_pct')
            if slope is not None:
                slope = float(slope)
                if slope > 0.05:
                    return 'up'
                if slope < -0.05:
                    return 'down'
                return 'flat'
        except Exception:
            pass
        return None

    def _quick_momentum(self, sym: str) -> str | None:
        """Fallback: 5-day return sign from yfinance daily bars."""
        try:
            import yfinance as yf
            hist = yf.Ticker(sym).history(period='7d', interval='1d')
            if hist.empty or len(hist) < 2:
                return None
            closes = [float(x) for x in hist['Close'].tolist()]
            first, last = closes[0], closes[-1]
            if first <= 0:
                return None
            ret = (last - first) / first * 100.0
            if ret > 0.5:
                return 'up'
            if ret < -0.5:
                return 'down'
            return 'flat'
        except Exception as e:
            log.debug('[SHORT] quick momentum failed for %s: %s', sym, e)
            return None

    # ------------------------------------------------------------------
    # Signal
    # ------------------------------------------------------------------

    def get_signal(self, symbol: str, data: dict | None = None) -> dict:
        """
        Combine short-interest crowding with price momentum.

        Returns {score, description, short_pct_float, short_ratio}.
        """
        neutral = {'score': 0.0, 'description': 'no notable short interest',
                   'short_pct_float': None, 'short_ratio': None}
        try:
            sym = (symbol or '').upper()
            if _classify(sym) != 'equity':
                return {'score': 0.0, 'description': 'not an equity — no short data',
                        'short_pct_float': None, 'short_ratio': None}

            sd = self.get_short_data(sym)
            spf = sd.get('short_pct_float')
            sr = sd.get('short_ratio')
            if spf is None and sr is None:
                return neutral

            heavy = (spf is not None and spf > HEAVY_SHORT_PCT_FLOAT) or \
                    (sr is not None and sr > HEAVY_SHORT_RATIO)

            if not heavy:
                return {'score': 0.0, 'description': 'short interest not elevated',
                        'short_pct_float': spf, 'short_ratio': sr}

            momentum = self._momentum_from_data(data)
            if momentum is None:
                momentum = self._quick_momentum(sym)

            if momentum == 'up':
                score = 1.2
                desc = 'high short interest + uptrend — squeeze potential'
            elif momentum == 'down':
                score = -0.3
                desc = 'shorts in control, justified'
            else:
                score = 0.0
                desc = 'high short interest, no momentum confirmation'

            return {'score': round(float(score), 3), 'description': desc,
                    'short_pct_float': spf, 'short_ratio': sr}

        except Exception as e:
            log.debug('[SHORT] get_signal(%s) error: %s', symbol, e)
            return neutral


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine: 'ShortInterestEngine | None' = None


def get_engine() -> ShortInterestEngine:
    """Return the lazily-created module-level engine singleton."""
    global _engine
    if _engine is None:
        _engine = ShortInterestEngine()
    return _engine


def get_signal(symbol: str, data: dict | None = None) -> dict:
    """Short-interest squeeze signal dict for ``symbol`` (never raises)."""
    try:
        return get_engine().get_signal(symbol, data)
    except Exception as e:
        log.debug('[SHORT] module get_signal error: %s', e)
        return {'score': 0.0, 'description': 'error',
                'short_pct_float': None, 'short_ratio': None}


def score_contrib(symbol: str, data: dict | None = None) -> float:
    """Just the float score for ``symbol`` (0.0 on failure)."""
    try:
        return float(get_signal(symbol, data).get('score', 0.0))
    except Exception:
        return 0.0

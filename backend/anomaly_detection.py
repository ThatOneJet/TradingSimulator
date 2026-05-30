"""
AnomalyDetector — Z-score anomaly flagging for indicator readings.

Tracks rolling distribution (mean, std) of each indicator over the
last 60 bars and flags when 2+ indicators simultaneously deviate
more than 2.5 standard deviations from their rolling baseline.

Anomaly flags reduce position size automatically and add a warning
to the AI scan log.
"""

import threading
import logging
import time
import datetime
from collections import defaultdict, deque

log = logging.getLogger(__name__)


class AnomalyDetector:
    WINDOW        = 60    # bars for rolling distribution
    Z_THRESHOLD   = 2.5   # standard deviations to flag
    MIN_ANOMALIES = 2     # simultaneous anomalies needed to trigger

    TRACKED = [
        'rsi',
        'macd_value',
        'stoch_k_val',
        'volume_ratio',
        'atr_pct',
        'slope_pct',
        'adx',
    ]

    def __init__(self):
        self._lock = threading.Lock()
        # {symbol: {indicator: deque[float]}}
        self._history: dict = defaultdict(
            lambda: {k: deque(maxlen=self.WINDOW) for k in self.TRACKED}
        )

    def update(self, symbol: str, data: dict) -> None:
        """Feed current indicator readings into rolling history."""
        try:
            with self._lock:
                for key in self.TRACKED:
                    val = data.get(key)
                    if val is not None:
                        try:
                            self._history[symbol][key].append(float(val))
                        except (TypeError, ValueError):
                            pass
        except Exception as e:
            log.exception('[ANOMALY] update error symbol=%s: %s', symbol, e)

    def check(self, symbol: str, data: dict) -> dict:
        """
        Compute Z-scores for current indicator readings against the rolling
        baseline, and flag an anomaly when enough indicators deviate.

        Returns:
        {
            'anomaly':     bool,
            'z_scores':    dict,   # {indicator: z_score}
            'flagged':     list,   # indicators with |z| > threshold
            'size_mult':   float,  # 0.5 if anomaly, 1.0 otherwise
            'description': str,
        }
        """
        try:
            with self._lock:
                # Snapshot the history so we release the lock before computing
                history_snapshot = {
                    key: list(self._history[symbol][key])
                    for key in self.TRACKED
                    if symbol in self._history
                }

            z_scores: dict = {}
            flagged:  list = []

            for key in self.TRACKED:
                vals = history_snapshot.get(key, [])
                if len(vals) < 20:
                    # Not enough history to compute a meaningful baseline
                    continue

                val = data.get(key)
                if val is None:
                    continue

                try:
                    val  = float(val)
                    n    = len(vals)
                    mean = sum(vals) / n
                    variance = sum((v - mean) ** 2 for v in vals) / n
                    std  = variance ** 0.5

                    if std < 1e-9:
                        # Flat/constant indicator — skip to avoid division by zero
                        continue

                    z = (val - mean) / std
                    # Cap z-scores at ±10 — values beyond this indicate a data
                    # source switch (daily→1m bars) rather than a real anomaly
                    z = max(-10.0, min(10.0, z))
                    z_scores[key] = round(z, 2)

                    if abs(z) >= self.Z_THRESHOLD:
                        flagged.append(key)

                except (TypeError, ValueError):
                    continue

            anomaly = len(flagged) >= self.MIN_ANOMALIES

            description = ''
            if anomaly:
                parts = [f'{k}(z={z_scores[k]:+.1f})' for k in flagged]
                description = (
                    f'Anomaly detected: {", ".join(parts)} '
                    f'— unusual market conditions'
                )
                log.debug('[ANOMALY] %s: %s', symbol, description)

            return {
                'anomaly':     anomaly,
                'z_scores':    z_scores,
                'flagged':     flagged,
                'size_mult':   0.5 if anomaly else 1.0,
                'description': description,
            }

        except Exception as e:
            log.exception('[ANOMALY] check error symbol=%s: %s', symbol, e)
            return {
                'anomaly':     False,
                'z_scores':    {},
                'flagged':     [],
                'size_mult':   1.0,
                'description': '',
            }

    def reset(self, symbol: str) -> None:
        """Clear rolling history for a symbol (e.g. after a data gap)."""
        try:
            with self._lock:
                if symbol in self._history:
                    del self._history[symbol]
            log.info('[ANOMALY] history reset for %s', symbol)
        except Exception as e:
            log.exception('[ANOMALY] reset error symbol=%s: %s', symbol, e)

    def summary(self) -> dict:
        """
        Return a snapshot of how many bars of history are tracked per symbol
        and indicator. Useful for health-check endpoints.
        """
        try:
            with self._lock:
                result = {}
                for symbol, indicators in self._history.items():
                    result[symbol] = {k: len(v) for k, v in indicators.items()}
            return result
        except Exception as e:
            log.exception('[ANOMALY] summary error: %s', e)
            return {}

    def bulk_update(self, symbol: str, bars: list) -> None:
        """
        Seed the rolling history from a list of historical bar dicts.
        Useful on startup to pre-warm the detector before live data arrives.

        Each element of `bars` should be a dict with the same keys as TRACKED.
        """
        try:
            for bar in bars:
                self.update(symbol, bar)
            log.debug(
                '[ANOMALY] bulk_update %s: %d bars ingested', symbol, len(bars)
            )
        except Exception as e:
            log.exception('[ANOMALY] bulk_update error symbol=%s: %s', symbol, e)

    def check_and_update(self, symbol: str, data: dict) -> dict:
        """
        Convenience method: run check() then update() in a single call.
        Returns the same dict as check().
        """
        result = self.check(symbol, data)
        self.update(symbol, data)
        return result


# ---------------------------------------------------------------------------
# Module-level singleton helpers
# ---------------------------------------------------------------------------

_detector: 'AnomalyDetector | None' = None


def get_detector() -> AnomalyDetector:
    """Return (or lazily create) the module singleton."""
    global _detector
    if _detector is None:
        _detector = AnomalyDetector()
        log.info('[ANOMALY] AnomalyDetector singleton created')
    return _detector


def check(symbol: str, data: dict) -> dict:
    """
    Module-level check against rolling Z-score baseline.
    Safe to call before explicit initialisation.
    """
    return get_detector().check(symbol, data)


def update(symbol: str, data: dict) -> None:
    """
    Module-level update — feed a new bar of indicator readings into history.
    Safe to call before explicit initialisation.
    """
    get_detector().update(symbol, data)


def check_and_update(symbol: str, data: dict) -> dict:
    """Module-level convenience: check then update in one call."""
    return get_detector().check_and_update(symbol, data)

"""
BearishEngine — continuous bearish risk scoring per symbol.

Scores 0–10 where:
  0–2: healthy, no action
  2–4: mild deterioration, monitor
  4–6: moderate risk, consider trimming 30%
  6–8: significant deterioration, trim to 50%
  8–10: high risk, full exit

Components:
  - Trend deterioration (slope flipping, ADX weakening)
  - Momentum decay (RSI falling from peak, MACD bearish cross)
  - Volume shift (selling volume increasing)
  - Volatility expansion (ATR% rising = stop widening risk)
  - Price structure (price vs EMA50, BB position)
"""

import logging

log = logging.getLogger(__name__)

LEVELS = [
    (0,  2,  'safe',   'Hold — no deterioration detected'),
    (2,  4,  'watch',  'Monitor — mild weakness, hold full position'),
    (4,  6,  'trim',   'Trim 30% — conditions weakening, protect capital'),
    (6,  8,  'reduce', 'Reduce to 50% — significant deterioration'),
    (8,  10, 'exit',   'Full exit — high bearish risk, protect profits'),
]


class BearishEngine:
    """Computes a continuous bearish risk score (0–10) for a held position."""

    # ------------------------------------------------------------------
    # Component scorers
    # ------------------------------------------------------------------

    def _trend_score(self, data: dict) -> float:
        """Trend deterioration component — max 2.0."""
        try:
            trend   = data.get('trend', 'sideways') or 'sideways'
            slope_p = float(data.get('slope_pct', 0) or 0)

            if trend == 'down' and slope_p < -0.15:
                return 2.0
            elif trend == 'down':
                return 1.5
            elif trend == 'sideways' and slope_p < -0.05:
                return 0.8
            else:
                return 0.0
        except Exception:
            log.exception('_trend_score error')
            return 0.0

    def _momentum_score(self, data: dict) -> float:
        """Momentum decay component — max 2.0."""
        try:
            rsi    = float(data.get('rsi', 50) or 50)
            macd_x = data.get('macd_cross', '') or ''

            if macd_x == 'bearish_cross' and rsi > 50:
                return 2.0
            elif macd_x == 'bearish_cross':
                return 1.5
            elif macd_x == 'bearish' and rsi < 45:
                return 1.2
            elif macd_x == 'bearish':
                return 0.8
            elif rsi < 40:
                return 0.5
            else:
                return 0.0
        except Exception:
            log.exception('_momentum_score error')
            return 0.0

    def _volume_score(self, data: dict) -> float:
        """Volume shift component — max 2.0."""
        try:
            vol_sig = data.get('volume_signal', '') or ''
            vol_r   = float(data.get('volume_ratio', 1) or 1)
            trend   = data.get('trend', 'sideways') or 'sideways'

            if vol_sig == 'high_down' and vol_r >= 2.0:
                return 2.0
            elif vol_sig == 'high_down':
                return 1.5
            elif vol_sig == 'low' and trend == 'down':
                return 1.0
            else:
                return 0.0
        except Exception:
            log.exception('_volume_score error')
            return 0.0

    def _volatility_score(self, data: dict) -> float:
        """Volatility expansion component — max 2.0."""
        try:
            atr_pct = float(data.get('atr_pct', 2) or 2)

            if atr_pct > 6:
                return 2.0
            elif atr_pct > 4:
                return 1.5
            elif atr_pct > 3:
                return 0.8
            else:
                return 0.0
        except Exception:
            log.exception('_volatility_score error')
            return 0.0

    def _structure_score(self, data: dict, current_price: float) -> float:
        """Price structure component — max 2.0."""
        try:
            bb_pos = data.get('bb_position', '') or ''
            ema50  = float(data.get('ema50', current_price) or current_price)
            price  = current_price or float(data.get('last_price', 0) or 0)
            vwap_s = data.get('vwap_signal', '') or ''
            trend  = data.get('trend', 'sideways') or 'sideways'

            structure_score = 0.0
            if price > 0 and ema50 > 0 and price < ema50 * 0.97:
                structure_score += 1.0
            if bb_pos == 'overbought' and trend != 'up':
                structure_score += 0.5
            if vwap_s == 'below':
                structure_score += 0.5
            return min(2.0, structure_score)
        except Exception:
            log.exception('_structure_score error')
            return 0.0

    # ------------------------------------------------------------------
    # Level lookup
    # ------------------------------------------------------------------

    def _resolve_level(self, total: float) -> tuple[str, str]:
        """Return (level, action) for a given total score."""
        for lo, hi, level, action in LEVELS:
            if lo <= total < hi:
                return level, action
        # score == 10 edge case
        return LEVELS[-1][2], LEVELS[-1][3]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(self, symbol: str, data: dict, entry_price: float = 0,
              current_price: float = 0) -> dict:
        """
        Compute bearish risk score for a held position.

        Args:
            symbol:        ticker
            data:          indicator dict from _compute_indicators_fast
            entry_price:   avg_cost of the position
            current_price: current market price

        Returns:
            {
                'score':       float,
                'level':       str,   # 'safe'|'watch'|'trim'|'reduce'|'exit'
                'action':      str,
                'components':  dict,
                'description': str,
            }
        """
        try:
            c_trend      = self._trend_score(data)
            c_momentum   = self._momentum_score(data)
            c_volume     = self._volume_score(data)
            c_volatility = self._volatility_score(data)
            c_structure  = self._structure_score(data, current_price)

            total = min(10.0, c_trend + c_momentum + c_volume + c_volatility + c_structure)
            level, action = self._resolve_level(total)

            description = (
                f'{symbol} bearish risk {total:.1f}/10 [{level}] — '
                f'trend={c_trend:.1f} momentum={c_momentum:.1f} '
                f'volume={c_volume:.1f} volatility={c_volatility:.1f} '
                f'structure={c_structure:.1f}'
            )
            log.debug(description)

            return {
                'score': round(total, 2),
                'level': level,
                'action': action,
                'components': {
                    'trend':      round(c_trend, 2),
                    'momentum':   round(c_momentum, 2),
                    'volume':     round(c_volume, 2),
                    'volatility': round(c_volatility, 2),
                    'structure':  round(c_structure, 2),
                },
                'description': description,
            }
        except Exception:
            log.exception('BearishEngine.score error for %s', symbol)
            return {
                'score': 0.0,
                'level': 'safe',
                'action': 'Hold — scoring error, defaulting to safe',
                'components': {},
                'description': f'{symbol}: scoring error',
            }

    def score_for_exit(self, symbol: str, data: dict,
                       entry_price: float = 0, current_price: float = 0) -> float:
        """Convenience wrapper — returns just the 0–10 score."""
        try:
            return self.score(symbol, data, entry_price, current_price)['score']
        except Exception:
            log.exception('score_for_exit error for %s', symbol)
            return 0.0

    def trim_fraction(self, score: float) -> float:
        """
        Returns the fraction of the position to sell based on the bearish score.

          score < 4  → 0.0  (hold)
          4 <= score < 6 → 0.30 (trim 30%)
          6 <= score < 8 → 0.50 (reduce to half)
          score >= 8 → 1.0  (full exit)
        """
        try:
            if score < 4:
                return 0.0
            elif score < 6:
                return 0.30
            elif score < 8:
                return 0.50
            else:
                return 1.0
        except Exception:
            log.exception('trim_fraction error')
            return 0.0


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine: 'BearishEngine | None' = None


def get_engine() -> BearishEngine:
    global _engine
    if _engine is None:
        _engine = BearishEngine()
    return _engine


def score(symbol: str, data: dict,
          entry_price: float = 0, current_price: float = 0) -> dict:
    """Module-level convenience — delegates to the singleton BearishEngine."""
    return get_engine().score(symbol, data, entry_price, current_price)

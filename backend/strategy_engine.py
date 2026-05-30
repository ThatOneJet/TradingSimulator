"""
StrategyEngine — market-specific scoring logic per asset class.

Each strategy adjusts indicator weights, thresholds, and scoring behavior
based on the characteristics of its asset class.

Usage:
    from strategy_engine import StrategyEngine
    engine = StrategyEngine()
    result = engine.score(symbol, data)
    # result: {score, strategy, confidence_0_100, breakdown_adjustments, rationale}
"""

import logging

log = logging.getLogger(__name__)


def _get_asset_class(sym: str) -> str:
    """Module-level helper — duplicated here for independence from app.py."""
    if sym.endswith('-USD'):
        return 'crypto'
    if sym.endswith('=X'):
        return 'forex'
    if sym.endswith('=F'):
        return 'futures'
    return 'equity'


# ---------------------------------------------------------------------------
# Base strategy
# ---------------------------------------------------------------------------

class BaseStrategy:
    name: str = 'base'

    def weight_overrides(self) -> dict:
        """Return per-indicator weight multipliers (on top of regime weights)."""
        return {}

    def score_adjustments(self, data: dict, base_score: float) -> tuple:
        """Apply strategy-specific adjustments to the base score.
        Returns (adjusted_score, list_of_rationale_strings).
        """
        return base_score, []

    def confidence(self, data: dict, adjusted_score: float, uncertainty: float) -> int:
        """Return 0–100 confidence score."""
        base = max(0, min(100, int(abs(adjusted_score) / 10 * 100)))
        penalty = int(uncertainty * 40)
        return max(5, min(95, base - penalty))


# ---------------------------------------------------------------------------
# Crypto strategy
# ---------------------------------------------------------------------------

class CryptoStrategy(BaseStrategy):
    name = 'crypto'

    def weight_overrides(self) -> dict:
        return {
            'volume': 1.6,    # volume spikes are more meaningful in crypto
            'rsi':    1.3,    # RSI extremes more reliable
            'macd':   1.2,    # momentum carries farther
            'vwap':   0.6,    # session VWAP less meaningful 24/7
            'bb':     1.1,
        }

    def score_adjustments(self, data: dict, base_score: float) -> tuple:
        rationale = []
        score = base_score
        try:
            vol_r   = float(data.get('volume_ratio', 1) or 1)
            rsi     = float(data.get('rsi', 50) or 50)
            atr_pct = float(data.get('atr_pct', 3) or 3)

            # Crypto momentum amplifier: strong volume confirms trend harder
            if vol_r >= 2.5 and abs(score) >= 2.0:
                score *= 1.15
                rationale.append(f'crypto volume surge ({vol_r:.1f}×) amplifies signal')

            # Extreme RSI dampener: crypto can stay extreme longer, but eventually snaps
            if rsi >= 88:
                score = min(score, -1.5)
                rationale.append(f'RSI {rsi:.0f} extreme — crypto parabolic top risk')
            elif rsi <= 12:
                score = max(score, 1.5)
                rationale.append(f'RSI {rsi:.0f} — panic capitulation, mean reversion likely')

            # High volatility penalty on entries (wider stops needed, reduce conviction)
            if atr_pct > 8:
                score *= 0.8
                rationale.append(f'ATR {atr_pct:.1f}% extreme — sizing down for crypto volatility')

        except Exception:
            log.exception('CryptoStrategy.score_adjustments failed — returning base score')
            return base_score, rationale

        return round(score, 2), rationale

    def confidence(self, data: dict, score: float, uncertainty: float) -> int:
        # Crypto confidence boosts on volume, reduces on high volatility
        try:
            base    = max(0, min(100, int(abs(score) / 10 * 100)))
            vol_r   = float(data.get('volume_ratio', 1) or 1)
            atr_pct = float(data.get('atr_pct', 3) or 3)
            penalty     = int(uncertainty * 35)
            vol_boost   = min(15, int((vol_r - 1) * 8)) if vol_r > 1.5 else 0
            vol_penalty = min(20, int((atr_pct - 5) * 3)) if atr_pct > 5 else 0
            return max(5, min(95, base - penalty + vol_boost - vol_penalty))
        except Exception:
            log.exception('CryptoStrategy.confidence failed — returning default')
            return 30


# ---------------------------------------------------------------------------
# Forex strategy
# ---------------------------------------------------------------------------

class ForexStrategy(BaseStrategy):
    name = 'forex'

    def weight_overrides(self) -> dict:
        return {
            'rsi':    1.4,    # mean reversion dominant in forex
            'bb':     1.5,    # Bollinger mean reversion key
            'stoch':  1.4,    # stochastic works well in ranging forex
            'macd':   0.7,    # momentum less reliable in forex
            'vwap':   0.4,    # VWAP irrelevant for 24/7 forex
            'trend':  0.8,    # forex trends are slower
            'volume': 0.5,    # forex volume data unreliable from yfinance
        }

    def score_adjustments(self, data: dict, base_score: float) -> tuple:
        rationale = []
        score = base_score
        try:
            rsi    = float(data.get('rsi', 50) or 50)
            bb_pos = data.get('bb_position', '') or ''
            trend  = data.get('trend', 'sideways') or 'sideways'

            # Forex mean-reversion amplifier: BB oversold/overbought carry more weight
            if bb_pos == 'oversold' and rsi < 35:
                score += 0.8
                rationale.append('forex BB oversold + RSI confirm mean-reversion setup')
            elif bb_pos == 'overbought' and rsi > 65:
                score -= 0.8
                rationale.append('forex BB overbought + RSI confirm reversal risk')

            # Forex trend dampener: trending moves are slower, reduce conviction
            if trend in ('up', 'down') and abs(score) > 3:
                score *= 0.85
                rationale.append('forex trend signal dampened — macro trends are slow-moving')

            # Cap forex scores tighter — moves are smaller
            score = max(-6.0, min(6.0, score))

        except Exception:
            log.exception('ForexStrategy.score_adjustments failed — returning base score')
            return base_score, rationale

        return round(score, 2), rationale

    def confidence(self, data: dict, score: float, uncertainty: float) -> int:
        # Forex confidence: mean-reversion setups get full confidence; trending gets less
        try:
            base              = max(0, min(100, int(abs(score) / 6 * 100)))  # scale to max 6 for forex
            trend             = data.get('trend', 'sideways') or 'sideways'
            trend_penalty     = 15 if trend in ('up', 'down') else 0
            uncertainty_penalty = int(uncertainty * 30)
            return max(5, min(90, base - uncertainty_penalty - trend_penalty))
        except Exception:
            log.exception('ForexStrategy.confidence failed — returning default')
            return 30


# ---------------------------------------------------------------------------
# Equity strategy
# ---------------------------------------------------------------------------

class EquityStrategy(BaseStrategy):
    name = 'equity'

    def weight_overrides(self) -> dict:
        # Balanced — equity is the base case the original model was calibrated for
        return {}

    def score_adjustments(self, data: dict, base_score: float) -> tuple:
        rationale = []
        score = base_score
        try:
            # Earnings risk check (simple heuristic: if ATR suddenly > 3× normal, likely earnings)
            atr_pct = float(data.get('atr_pct', 2) or 2)
            if atr_pct > 6:
                score *= 0.75
                rationale.append(f'ATR {atr_pct:.1f}% — possible earnings/event risk, sizing reduced')

        except Exception:
            log.exception('EquityStrategy.score_adjustments failed — returning base score')
            return base_score, rationale

        return round(score, 2), rationale

    def confidence(self, data: dict, score: float, uncertainty: float) -> int:
        try:
            base      = max(0, min(100, int(abs(score) / 10 * 100)))
            vol_r     = float(data.get('volume_ratio', 1) or 1)
            vol_bonus = min(10, int((vol_r - 1) * 6)) if vol_r > 1.5 else 0
            penalty   = int(uncertainty * 40)
            return max(5, min(95, base + vol_bonus - penalty))
        except Exception:
            log.exception('EquityStrategy.confidence failed — returning default')
            return 30


# ---------------------------------------------------------------------------
# Futures strategy
# ---------------------------------------------------------------------------

class FuturesStrategy(BaseStrategy):
    name = 'futures'

    def weight_overrides(self) -> dict:
        return {
            'trend':  1.6,    # trend-following is primary in futures
            'macd':   1.4,    # momentum key for futures directional plays
            'volume': 1.5,    # volume confirmation critical
            'rsi':    0.7,    # RSI less reliable — futures can trend extremely
            'bb':     0.8,    # BB less useful in strong trends
            'stoch':  0.6,    # stochastic noisy in trending futures
            'vwap':   1.2,    # VWAP relevant during RTH
        }

    def score_adjustments(self, data: dict, base_score: float) -> tuple:
        rationale = []
        score = base_score
        try:
            trend = data.get('trend', 'sideways') or 'sideways'
            vol_r = float(data.get('volume_ratio', 1) or 1)
            adx   = float(data.get('adx', 0) or 0)

            # Futures trend amplifier: confirmed ADX trend gets a boost
            if adx > 25 and trend in ('up', 'down') and vol_r > 1.2:
                boost = min(1.5, adx / 25 * 0.8)
                score = score + boost if score > 0 else score - boost
                rationale.append(
                    f'futures trend confirmed (ADX {adx:.0f}) with volume — boosting signal'
                )

            # No-trend dampener: futures chop is expensive with leverage
            if adx < 15 and trend == 'sideways':
                score *= 0.6
                rationale.append('futures choppy (low ADX) — reducing conviction, leverage risk')

        except Exception:
            log.exception('FuturesStrategy.score_adjustments failed — returning base score')
            return base_score, rationale

        return round(score, 2), rationale

    def confidence(self, data: dict, score: float, uncertainty: float) -> int:
        try:
            base      = max(0, min(100, int(abs(score) / 10 * 100)))
            adx       = float(data.get('adx', 0) or 0)
            adx_bonus = min(15, int((adx - 20) * 0.6)) if adx > 20 else -10
            penalty   = int(uncertainty * 35)
            return max(5, min(95, base + adx_bonus - penalty))
        except Exception:
            log.exception('FuturesStrategy.confidence failed — returning default')
            return 30


# ---------------------------------------------------------------------------
# Strategy engine
# ---------------------------------------------------------------------------

class StrategyEngine:
    _strategies = {
        'crypto':  CryptoStrategy(),
        'forex':   ForexStrategy(),
        'equity':  EquityStrategy(),
        'futures': FuturesStrategy(),
    }

    def score(
        self,
        symbol: str,
        data: dict,
        base_score: float,
        uncertainty: float = 0.3,
    ) -> dict:
        """
        Apply market-specific strategy on top of the base score from _ai_score_detailed.

        Args:
            symbol:      ticker symbol
            data:        indicator dict from _compute_indicators_fast
            base_score:  score from _ai_score_detailed (before strategy adjustment)
            uncertainty: uncertainty value from _ai_score_detailed

        Returns:
            {
                'score':            float,       # final adjusted score
                'strategy':         str,         # which strategy was applied
                'confidence':       int,         # 0–100 confidence score
                'rationale':        list[str],   # strategy-specific explanations
                'weight_overrides': dict,        # which weights were changed
            }
        """
        asset_class = _get_asset_class(symbol)
        strategy = self._strategies.get(asset_class, self._strategies['equity'])

        adjusted_score, rationale = strategy.score_adjustments(data, base_score)
        confidence = strategy.confidence(data, adjusted_score, uncertainty)

        return {
            'score':            adjusted_score,
            'strategy':         strategy.name,
            'confidence':       confidence,
            'rationale':        rationale,
            'weight_overrides': strategy.weight_overrides(),
        }

    def get_weights(self, symbol: str) -> dict:
        """Return weight overrides for the asset class of this symbol."""
        asset_class = _get_asset_class(symbol)
        return self._strategies.get(asset_class, self._strategies['equity']).weight_overrides()

    def get_strategy_name(self, symbol: str) -> str:
        return _get_asset_class(symbol)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine: 'StrategyEngine | None' = None


def get_engine() -> StrategyEngine:
    global _engine
    if _engine is None:
        _engine = StrategyEngine()
    return _engine

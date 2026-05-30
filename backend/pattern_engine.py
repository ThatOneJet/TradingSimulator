"""
PatternEngine — multi-layer pattern recognition adding score contributions to AI.

Layers (each -2.0 to +2.0, capped total at ±6.0):
  1. Relative strength vs SPY (equities only, 20-bar RS ratio)
  2. Momentum acceleration (ROC-10 + ROC-5 acceleration)
  3. Candlestick patterns (1-3 bar visual patterns)
  4. Volume climax detection (exhaustion reversal signal)
"""

import logging
import threading
import time

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Candlestick primitives
# ---------------------------------------------------------------------------

def _body(b):     return abs(b['close'] - b['open'])
def _rng(b):      return max(b['high'] - b['low'], 0.0001)
def _uw(b):       return b['high'] - max(b['open'], b['close'])
def _lw(b):       return min(b['open'], b['close']) - b['low']
def _bull(b):     return b['close'] >= b['open']
def _body_pct(b): return _body(b) / _rng(b)
def _is_doji(b):  return _body_pct(b) < 0.10
def _is_hammer(b):
    body = _body(b); lw = _lw(b); uw = _uw(b)
    return body > 0 and lw >= 2 * body and uw <= 0.3 * body
def _is_star(b):
    body = _body(b); lw = _lw(b); uw = _uw(b)
    return body > 0 and uw >= 2 * body and lw <= 0.3 * body
def _bull_engulf(p, c):
    return _bull(c) and not _bull(p) and c['open'] <= p['close'] and c['close'] >= p['open']
def _bear_engulf(p, c):
    return not _bull(c) and _bull(p) and c['open'] >= p['close'] and c['close'] <= p['open']


# ---------------------------------------------------------------------------
# Four analysis functions
# ---------------------------------------------------------------------------

def detect_candlestick_patterns(bars):
    """
    Detect candlestick patterns from a list of bar dicts {open, high, low, close}.
    Requires at least 3 bars, newest last.

    Returns {'name': str, 'score': float, 'description': str}.
    """
    try:
        if not bars or len(bars) < 3:
            return {'name': 'none', 'score': 0, 'description': ''}

        b0, b1, b2 = bars[-3], bars[-2], bars[-1]
        prev = bars[-2]
        curr = bars[-1]

        # 1. Bullish Engulfing
        if _bull_engulf(prev, curr):
            return {
                'name': 'bullish_engulfing',
                'score': 1.8,
                'description': 'Bullish candle fully engulfs prior bearish candle',
            }

        # 2. Bearish Engulfing
        if _bear_engulf(prev, curr):
            return {
                'name': 'bearish_engulfing',
                'score': -1.8,
                'description': 'Bearish candle fully engulfs prior bullish candle',
            }

        # 3. Morning Star
        b0_bearish = not _bull(b0)
        b1_small   = _is_doji(b1) or _body_pct(b1) < 0.30
        b2_bullish = _bull(b2)
        b0_mid     = (b0['open'] + b0['close']) / 2
        if b0_bearish and b1_small and b2_bullish and b2['close'] > b0_mid:
            return {
                'name': 'morning_star',
                'score': 1.5,
                'description': 'Three-bar morning star reversal pattern',
            }

        # 4. Evening Star
        b0_bullish = _bull(b0)
        b2_bearish = not _bull(b2)
        b0_mid2    = (b0['open'] + b0['close']) / 2
        if b0_bullish and b1_small and b2_bearish and b2['close'] < b0_mid2:
            return {
                'name': 'evening_star',
                'score': -1.5,
                'description': 'Three-bar evening star reversal pattern',
            }

        # 5. Hammer (after downtrend: bars[-4].close > bars[-1].close if available)
        if _is_hammer(curr):
            if len(bars) >= 4:
                in_downtrend = bars[-4]['close'] > curr['close']
            else:
                in_downtrend = bars[-3]['close'] > curr['close']
            if in_downtrend:
                return {
                    'name': 'hammer',
                    'score': 1.2,
                    'description': 'Hammer candle after downtrend signals potential reversal',
                }

        # 6. Shooting Star (after uptrend)
        if _is_star(curr):
            if len(bars) >= 4:
                in_uptrend = bars[-4]['close'] < curr['close']
            else:
                in_uptrend = bars[-3]['close'] < curr['close']
            if in_uptrend:
                return {
                    'name': 'shooting_star',
                    'score': -1.2,
                    'description': 'Shooting star after uptrend signals potential reversal',
                }

        # 7. Doji at extreme
        if _is_doji(curr):
            prior = bars[-4:-1] if len(bars) >= 4 else bars[-3:-1]
            closes_prior = [x['close'] for x in prior]
            if len(closes_prior) >= 2:
                trending_down = all(closes_prior[i] > closes_prior[i + 1]
                                    for i in range(len(closes_prior) - 1))
                trending_up   = all(closes_prior[i] < closes_prior[i + 1]
                                    for i in range(len(closes_prior) - 1))
                if trending_down:
                    return {
                        'name': 'doji_at_low',
                        'score': 0.6,
                        'description': 'Doji after downtrend indicates indecision / possible reversal',
                    }
                if trending_up:
                    return {
                        'name': 'doji_at_high',
                        'score': -0.6,
                        'description': 'Doji after uptrend indicates indecision / possible reversal',
                    }

        # 8. No pattern
        return {'name': 'none', 'score': 0, 'description': ''}

    except Exception:
        return {'name': 'none', 'score': 0, 'description': ''}


def compute_relative_strength(sym_closes, spy_closes, period=20):
    """
    Compute 20-bar relative strength of a symbol vs SPY.

    Returns {'rs': float, 'score': float, 'label': str}.
    """
    try:
        sym_ret = (sym_closes[-1] / sym_closes[-period] - 1) if sym_closes[-period] != 0 else 0
        spy_ret = (spy_closes[-1] / spy_closes[-period] - 1) if spy_closes[-period] != 0 else 0
        rs = (1 + sym_ret) / (1 + spy_ret) if spy_ret != -1 else 1.0

        if rs >= 1.3:
            score, label = 1.5, 'strong_outperform'
        elif rs >= 1.1:
            score, label = 0.8, 'outperform'
        elif rs <= 0.7:
            score, label = -1.5, 'strong_underperform'
        elif rs <= 0.9:
            score, label = -0.8, 'underperform'
        else:
            score, label = 0.0, 'neutral'

        return {'rs': rs, 'score': score, 'label': label}

    except Exception:
        return {'rs': 1.0, 'score': 0.0, 'label': 'neutral'}


def compute_momentum(closes):
    """
    Compute ROC-10 and ROC-5 momentum with acceleration.

    Returns {'roc': float, 'roc5': float, 'acceleration': float,
             'score': float, 'accelerating': bool}.
    """
    try:
        if not closes or len(closes) < 11:
            return {'roc': 0.0, 'roc5': 0.0, 'acceleration': 0.0,
                    'score': 0.0, 'accelerating': False}

        roc10 = (closes[-1] - closes[-11]) / closes[-11] * 100

        if len(closes) >= 6:
            roc5 = (closes[-1] - closes[-6]) / closes[-6] * 100
        else:
            roc5 = 0.0

        accel = roc5 - roc10

        if roc10 > 5 and accel > 0.5:
            score = 1.5
        elif roc10 > 2 and accel > 0:
            score = 0.8
        elif roc10 > 0:
            score = 0.3
        elif roc10 < -5 and accel < -0.5:
            score = -1.5
        elif roc10 < -2 and accel < 0:
            score = -0.8
        elif roc10 < 0:
            score = -0.3
        else:
            score = 0.0

        return {
            'roc': roc10,
            'roc5': roc5,
            'acceleration': accel,
            'score': score,
            'accelerating': accel > 0,
        }

    except Exception:
        return {'roc': 0.0, 'roc5': 0.0, 'acceleration': 0.0,
                'score': 0.0, 'accelerating': False}


def detect_volume_climax(volumes, closes):
    """
    Detect volume climax (exhaustion reversal) from the last 20 bars.

    Returns {'climax': bool, 'score': float, 'direction': str}.
    """
    try:
        if not volumes or not closes or len(volumes) < 20 or len(closes) < 20:
            return {'climax': False, 'score': 0, 'direction': 'none'}

        avg_vol = sum(volumes[-20:]) / 20
        avg_rng = sum(abs(closes[i] - closes[i - 1]) for i in range(-20, 0)) / 20
        last_vol = volumes[-1]
        last_rng = abs(closes[-1] - closes[-2]) if len(closes) >= 2 else 0

        climax = last_vol > avg_vol * 3 and last_rng > avg_rng * 2

        if not climax:
            return {'climax': False, 'score': 0, 'direction': 'none'}

        recent_down = sum(1 for i in range(-5, -1) if closes[i] < closes[i - 1])
        price_up = closes[-1] > closes[-2]

        if not price_up and recent_down >= 3:
            direction = 'bullish_exhaustion'
            score = 1.0
        elif price_up and recent_down <= 1:
            direction = 'bearish_exhaustion'
            score = -1.0
        else:
            direction = 'neutral'
            score = 0.0

        return {'climax': True, 'direction': direction, 'score': score}

    except Exception:
        return {'climax': False, 'score': 0, 'direction': 'none'}


# ---------------------------------------------------------------------------
# PatternEngine class
# ---------------------------------------------------------------------------

class PatternEngine:
    def __init__(self):
        self._spy_closes: list = []
        self._spy_ts: float = 0.0
        self._lock = threading.Lock()

    def _get_spy_closes(self) -> list:
        with self._lock:
            if time.time() - self._spy_ts < 300 and self._spy_closes:
                return list(self._spy_closes)
        try:
            import yfinance as yf
            hist = yf.Ticker('SPY').history(period='30d', interval='1d')
            closes = list(hist['Close'].dropna()) if not hist.empty else []
            with self._lock:
                self._spy_closes = closes
                self._spy_ts = time.time()
            return closes
        except Exception:
            return []

    def analyze(self, symbol: str, data: dict,
                closes=None, highs=None, lows=None,
                volumes=None, opens=None) -> dict:
        """
        Run all pattern layers. Returns dict with total_score and per-layer results.
        total_score is capped at ±6.0.
        """
        total = 0.0
        breakdown = {}
        descriptions = []

        if not closes or len(closes) < 5:
            return {'total_score': 0.0, 'patterns': {}, 'rs': {},
                    'momentum': {}, 'climax': {}, 'breakdown': {},
                    'description': ''}

        # Layer 1: Relative strength (equities only)
        rs_result = {}
        is_equity = not (symbol.endswith('-USD') or symbol.endswith('=X')
                         or symbol.endswith('=F'))
        if is_equity and len(closes) >= 20:
            spy = self._get_spy_closes()
            if len(spy) >= 20:
                rs_result = compute_relative_strength(closes, spy, 20)
                total += rs_result['score']
                breakdown['rs'] = rs_result['score']
                lbl = rs_result.get('label', '')
                if 'outperform' in lbl:
                    descriptions.append(f'RS {rs_result["rs"]:.2f}× SPY')

        # Layer 2: Momentum
        mom_result = compute_momentum(closes)
        total += mom_result['score']
        breakdown['momentum'] = mom_result['score']
        if abs(mom_result['score']) >= 0.8:
            roc = mom_result.get('roc', 0)
            descriptions.append(
                f'{"+" if roc > 0 else ""}{roc:.1f}% ROC '
                f'{"↑" if mom_result.get("accelerating") else "↓"}'
            )

        # Layer 3: Candlestick patterns
        patt_result = {'name': 'none', 'score': 0}
        if opens and highs and lows and len(opens) >= 3:
            bars = [
                {'open': opens[i], 'high': highs[i], 'low': lows[i], 'close': closes[i]}
                for i in range(-3, 0)
            ]
            patt_result = detect_candlestick_patterns(bars)
            total += patt_result['score']
            breakdown['pattern'] = patt_result['score']
            if patt_result['name'] != 'none':
                descriptions.append(patt_result['name'].replace('_', ' ').title())

        # Layer 4: Volume climax
        climax_result = {}
        if volumes and len(volumes) >= 20:
            climax_result = detect_volume_climax(volumes, closes)
            total += climax_result.get('score', 0)
            breakdown['climax'] = climax_result.get('score', 0)
            if climax_result.get('climax'):
                descriptions.append(
                    climax_result.get('direction', '').replace('_', ' ')
                )

        total = round(max(-6.0, min(6.0, total)), 2)

        return {
            'total_score': total,
            'patterns':    patt_result,
            'rs':          rs_result,
            'momentum':    mom_result,
            'climax':      climax_result,
            'breakdown':   breakdown,
            'description': ' | '.join(d for d in descriptions if d),
        }


# ---------------------------------------------------------------------------
# Module singleton
# ---------------------------------------------------------------------------

_engine: 'PatternEngine | None' = None


def get_engine() -> 'PatternEngine':
    global _engine
    if _engine is None:
        _engine = PatternEngine()
    return _engine


def analyze(symbol: str, data: dict, closes=None, highs=None,
            lows=None, volumes=None, opens=None) -> dict:
    try:
        return get_engine().analyze(symbol, data, closes, highs, lows, volumes, opens)
    except Exception as e:
        log.debug('[PATTERN] analyze error: %s', e)
        return {'total_score': 0.0, 'patterns': {}, 'rs': {},
                'momentum': {}, 'climax': {}, 'breakdown': {}, 'description': ''}

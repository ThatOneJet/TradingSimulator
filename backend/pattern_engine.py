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
# Multi-bar DAILY chart patterns (require ~60+ daily bars)
# ---------------------------------------------------------------------------

def _pivots(values, kind='high'):
    """
    Find 3-bar pivot points (local extrema) in a value series.

    Returns a list of (index, value) tuples. A pivot high is a bar whose value
    is >= both neighbours; a pivot low is <= both neighbours.
    """
    out = []
    n = len(values)
    if n < 3:
        return out
    for i in range(1, n - 1):
        v = values[i]
        if kind == 'high':
            if v >= values[i - 1] and v >= values[i + 1]:
                out.append((i, v))
        else:
            if v <= values[i - 1] and v <= values[i + 1]:
                out.append((i, v))
    return out


def _slope(points):
    """
    Crude least-squares slope of a list of (x, y) tuples. Returns 0.0 on failure
    or when fewer than 2 points are supplied.
    """
    try:
        n = len(points)
        if n < 2:
            return 0.0
        sx = sum(p[0] for p in points)
        sy = sum(p[1] for p in points)
        sxx = sum(p[0] * p[0] for p in points)
        sxy = sum(p[0] * p[1] for p in points)
        denom = (n * sxx - sx * sx)
        if denom == 0:
            return 0.0
        return (n * sxy - sx * sy) / denom
    except Exception:
        return 0.0


def detect_chart_patterns(opens, highs, lows, closes, volumes):
    """
    Detect larger multi-week DAILY chart patterns from ~60+ daily bars.

    Detects (returns the single highest-conviction match):
      - Bull Flag / Bear Flag (pole + tight consolidation continuation)
      - Double Bottom (W) / Double Top (M) reversals with breakout
      - Ascending / Descending Triangle (flat side + sloping side)
      - Cup and Handle (rounded base + small handle near breakout)

    Returns {'name': str, 'score': float, 'description': str} or
    {'name':'none','score':0,'description':''}.
    """
    try:
        if (not closes or not highs or not lows or
                len(closes) < 30 or len(highs) < 30 or len(lows) < 30):
            return {'name': 'none', 'score': 0, 'description': ''}

        n = len(closes)
        last = closes[-1]
        candidates = []   # (abs_score, result_dict)

        # ------------------------------------------------------------------
        # Bull / Bear Flag
        # Look for a sharp pole (~5-10 bars) then a tight consolidation (3-8 bars)
        # ending at the most recent bar.
        # ------------------------------------------------------------------
        for cons_len in range(3, 9):           # consolidation length
            if n < cons_len + 5:
                continue
            cons = closes[-cons_len:]
            cons_hi = max(highs[-cons_len:])
            cons_lo = min(lows[-cons_len:])
            cons_range = cons_hi - cons_lo
            for pole_len in range(5, 11):       # pole length
                start = n - cons_len - pole_len
                if start < 0:
                    continue
                pole_start = closes[start]
                pole_end = closes[n - cons_len - 1]
                if pole_start <= 0:
                    continue
                pole_move = (pole_end - pole_start) / pole_start
                pole_abs = abs(pole_end - pole_start)
                if pole_abs <= 0:
                    continue
                tight = cons_range < 0.40 * pole_abs

                # Bull flag: sharp up pole, tight down/sideways consolidation
                if pole_move > 0.08 and tight:
                    drift = (cons[-1] - cons[0]) / cons[0] if cons[0] else 0
                    if drift <= 0.02:           # consolidation drifts down / flat
                        candidates.append((1.5, {
                            'name': 'bull_flag',
                            'score': 1.5,
                            'description': (
                                f'Bull flag: {pole_move * 100:.0f}% pole then '
                                f'tight {cons_len}-bar consolidation (continuation long)'
                            ),
                        }))
                # Bear flag: sharp down pole, tight up/sideways consolidation
                if pole_move < -0.08 and tight:
                    drift = (cons[-1] - cons[0]) / cons[0] if cons[0] else 0
                    if drift >= -0.02:          # consolidation drifts up / flat
                        candidates.append((1.5, {
                            'name': 'bear_flag',
                            'score': -1.5,
                            'description': (
                                f'Bear flag: {pole_move * 100:.0f}% pole then '
                                f'tight {cons_len}-bar consolidation (continuation short)'
                            ),
                        }))

        # ------------------------------------------------------------------
        # Double Bottom (W) / Double Top (M)
        # ------------------------------------------------------------------
        lows_piv = _pivots(lows, 'low')
        highs_piv = _pivots(highs, 'high')

        # Double Bottom: two pivot lows within ~3%, a peak between, price now
        # breaking above that middle peak.
        if len(lows_piv) >= 2:
            for a in range(len(lows_piv) - 1):
                for b in range(a + 1, len(lows_piv)):
                    i1, v1 = lows_piv[a]
                    i2, v2 = lows_piv[b]
                    if i2 - i1 < 5:             # need real separation
                        continue
                    if v1 <= 0:
                        continue
                    if abs(v1 - v2) / v1 > 0.03:
                        continue
                    mid_peak = max(highs[i1:i2 + 1]) if i2 > i1 else 0
                    if mid_peak <= max(v1, v2):
                        continue
                    # price now breaking above the middle peak
                    if last > mid_peak:
                        candidates.append((1.8, {
                            'name': 'double_bottom',
                            'score': 1.8,
                            'description': 'double bottom breakout (W reversal long)',
                        }))

        # Double Top: two pivot highs within ~3%, a trough between, price now
        # breaking below that middle trough.
        if len(highs_piv) >= 2:
            for a in range(len(highs_piv) - 1):
                for b in range(a + 1, len(highs_piv)):
                    i1, v1 = highs_piv[a]
                    i2, v2 = highs_piv[b]
                    if i2 - i1 < 5:
                        continue
                    if v1 <= 0:
                        continue
                    if abs(v1 - v2) / v1 > 0.03:
                        continue
                    mid_trough = min(lows[i1:i2 + 1]) if i2 > i1 else 0
                    if mid_trough >= min(v1, v2):
                        continue
                    if last < mid_trough:
                        candidates.append((1.8, {
                            'name': 'double_top',
                            'score': -1.8,
                            'description': 'double top breakdown (M reversal short)',
                        }))

        # ------------------------------------------------------------------
        # Ascending / Descending Triangle (use recent ~25 bars)
        # ------------------------------------------------------------------
        win = min(25, n)
        seg_hi = highs[-win:]
        seg_lo = lows[-win:]
        hp = _pivots(seg_hi, 'high')
        lp = _pivots(seg_lo, 'low')
        if len(hp) >= 2 and len(lp) >= 2:
            hi_vals = [v for _, v in hp]
            lo_vals = [v for _, v in lp]
            hi_mean = sum(hi_vals) / len(hi_vals)
            lo_mean = sum(lo_vals) / len(lo_vals)
            hi_slope = _slope(hp)
            lo_slope = _slope(lp)
            # Flatness measured relative to price level (per-bar slope as % of price)
            hi_flat = hi_mean > 0 and abs(hi_slope) / hi_mean < 0.002
            lo_flat = lo_mean > 0 and abs(lo_slope) / lo_mean < 0.002
            hi_rising = hi_mean > 0 and hi_slope / hi_mean > 0.002
            lo_rising = lo_mean > 0 and lo_slope / lo_mean > 0.002
            hi_falling = hi_mean > 0 and hi_slope / hi_mean < -0.002
            lo_falling = lo_mean > 0 and lo_slope / lo_mean < -0.002

            # Ascending: flat highs (resistance) + rising lows
            if hi_flat and lo_rising:
                candidates.append((1.2, {
                    'name': 'ascending_triangle',
                    'score': 1.2,
                    'description': 'ascending triangle: flat resistance, rising lows (bullish breakout bias)',
                }))
            # Descending: flat lows (support) + falling highs
            elif lo_flat and hi_falling:
                candidates.append((1.2, {
                    'name': 'descending_triangle',
                    'score': -1.2,
                    'description': 'descending triangle: flat support, falling highs (bearish breakdown bias)',
                }))

        # ------------------------------------------------------------------
        # Cup and Handle
        # Rounded U-shaped base over ~15-30 bars (excluding a small recent handle)
        # then a small pullback handle, price near the breakout level.
        # ------------------------------------------------------------------
        for handle_len in range(2, 7):
            for cup_len in range(15, 31):
                total_len = cup_len + handle_len
                if n < total_len + 1:
                    continue
                cup = closes[-total_len:-handle_len] if handle_len > 0 else closes[-cup_len:]
                if len(cup) < 10:
                    continue
                handle = closes[-handle_len:]
                cup_start = cup[0]
                cup_end = cup[-1]
                cup_min = min(cup)
                cup_min_i = cup.index(cup_min)
                rim = max(cup_start, cup_end)
                if rim <= 0 or cup_min <= 0:
                    continue
                depth = (rim - cup_min) / rim
                # U shape: rims roughly level, real depth, bottom in the middle third
                rims_level = abs(cup_start - cup_end) / rim < 0.06
                bottom_centered = (len(cup) * 0.30) <= cup_min_i <= (len(cup) * 0.70)
                deep_enough = 0.10 <= depth <= 0.50
                # Handle: shallow pullback off the rim, price near breakout
                handle_low = min(handle)
                handle_pullback = (cup_end - handle_low) / cup_end if cup_end else 0
                shallow_handle = 0 <= handle_pullback <= 0.5 * depth
                near_breakout = last >= rim * 0.97

                if (rims_level and bottom_centered and deep_enough and
                        shallow_handle and near_breakout):
                    candidates.append((1.5, {
                        'name': 'cup_and_handle',
                        'score': 1.5,
                        'description': (
                            f'cup and handle: rounded {len(cup)}-bar base, '
                            f'{handle_len}-bar handle, near breakout (continuation long)'
                        ),
                    }))
                    break
            else:
                continue
            break

        if not candidates:
            return {'name': 'none', 'score': 0, 'description': ''}

        # Highest-conviction match wins (largest absolute score)
        candidates.sort(key=lambda c: c[0], reverse=True)
        return candidates[0][1]

    except Exception:
        return {'name': 'none', 'score': 0, 'description': ''}


# ---------------------------------------------------------------------------
# PatternEngine class
# ---------------------------------------------------------------------------

class PatternEngine:
    def __init__(self):
        self._spy_closes: list = []
        self._spy_ts: float = 0.0
        self._lock = threading.Lock()
        # Per-symbol cache of daily chart-pattern signals: sym -> (ts, result)
        self._daily_cache: dict = {}
        self._daily_lock = threading.Lock()

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

    def daily_pattern_signal(self, symbol: str) -> dict:
        """
        Fetch ~90 daily bars for `symbol` and detect multi-week chart patterns.

        Results are cached for 1 hour per symbol.

        Returns {'score': float, 'description': str, 'pattern': str}.
        """
        sym = (symbol or '').upper()
        if not sym:
            return {'score': 0.0, 'description': '', 'pattern': 'none'}

        with self._daily_lock:
            cached = self._daily_cache.get(sym)
            if cached and time.time() - cached[0] < 3600:
                return dict(cached[1])

        result = {'score': 0.0, 'description': '', 'pattern': 'none'}
        try:
            import yfinance as yf
            hist = yf.Ticker(sym).history(period='90d', interval='1d')
            if hist is not None and not hist.empty and len(hist) >= 30:
                opens   = list(hist['Open'].dropna())
                highs   = list(hist['High'].dropna())
                lows    = list(hist['Low'].dropna())
                closes  = list(hist['Close'].dropna())
                volumes = list(hist['Volume'].dropna()) if 'Volume' in hist else []
                patt = detect_chart_patterns(opens, highs, lows, closes, volumes)
                result = {
                    'score':       float(patt.get('score', 0.0)),
                    'description': patt.get('description', ''),
                    'pattern':     patt.get('name', 'none'),
                }
        except Exception as e:
            log.debug('[PATTERN] daily_pattern_signal error for %s: %s', sym, e)

        with self._daily_lock:
            self._daily_cache[sym] = (time.time(), dict(result))
        return result


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


def daily_pattern_signal(symbol: str) -> dict:
    """
    Module-level wrapper: detect multi-week DAILY chart patterns for `symbol`.

    Returns {'score': float, 'description': str, 'pattern': str}.
    Cached 1 hour per symbol on the engine singleton.
    """
    try:
        return get_engine().daily_pattern_signal(symbol)
    except Exception as e:
        log.debug('[PATTERN] daily_pattern_signal error: %s', e)
        return {'score': 0.0, 'description': '', 'pattern': 'none'}


def daily_pattern_contrib(symbol: str) -> float:
    """Return just the daily chart-pattern score contribution for `symbol`."""
    try:
        return float(daily_pattern_signal(symbol).get('score', 0.0))
    except Exception:
        return 0.0

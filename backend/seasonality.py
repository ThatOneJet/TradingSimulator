"""
Seasonality — calendar-based statistical tendencies.
Sell-in-May, January effect, turn-of-month strength, OpEx week volatility,
day-of-week patterns, pre-holiday drift.

Pure date math, no external data. Effects are summed and clamped to
[-1.0, +1.0]. Equity/ETF seasonality only; crypto/forex/futures get mostly
neutral treatment (crypto carries a small weekend-liquidity caution).
"""

import logging
import calendar
from datetime import datetime, date, timedelta

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hardcoded US equity-market holidays (full market closures) for 2025-2026.
# Used for pre-holiday drift detection. Half-days are intentionally excluded.
# ---------------------------------------------------------------------------
US_MARKET_HOLIDAYS = {
    # 2025
    date(2025, 1, 1),    # New Year's Day
    date(2025, 1, 20),   # MLK Jr. Day
    date(2025, 2, 17),   # Presidents' Day
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 26),   # Memorial Day
    date(2025, 6, 19),   # Juneteenth
    date(2025, 7, 4),    # Independence Day
    date(2025, 9, 1),    # Labor Day
    date(2025, 11, 27),  # Thanksgiving
    date(2025, 12, 25),  # Christmas
    # 2026
    date(2026, 1, 1),    # New Year's Day
    date(2026, 1, 19),   # MLK Jr. Day
    date(2026, 2, 16),   # Presidents' Day
    date(2026, 4, 3),    # Good Friday
    date(2026, 5, 25),   # Memorial Day
    date(2026, 6, 19),   # Juneteenth
    date(2026, 7, 3),    # Independence Day (observed)
    date(2026, 9, 7),    # Labor Day
    date(2026, 11, 26),  # Thanksgiving
    date(2026, 12, 25),  # Christmas
}

# Small-/mid-cap names that benefit most from the January effect. Large megacaps
# show little January effect, so the bonus is reserved for these.
SMALL_MID_CAP_PROXY = {
    'IWM', 'IJR', 'IJH', 'VB', 'VBR', 'MDY', 'SCHA', 'IWO', 'IWN',
    'PLTR', 'HOOD', 'SOFI', 'RIVN', 'LCID', 'AFRM', 'UPST', 'SMCI',
    'RBLX', 'DKNG', 'CHWY', 'PINS', 'SNAP', 'FUBO', 'GME', 'AMC',
}


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


def _is_trading_day(d: date) -> bool:
    """Weekday and not a full-closure holiday."""
    return d.weekday() < 5 and d not in US_MARKET_HOLIDAYS


def _trading_days_in_range(start: date, end: date) -> list:
    """Inclusive list of trading days between start and end."""
    out, cur = [], start
    while cur <= end:
        if _is_trading_day(cur):
            out.append(cur)
        cur += timedelta(days=1)
    return out


def _third_friday(year: int, month: int) -> date:
    """Date of the 3rd Friday of the given month (monthly OpEx)."""
    fridays = [
        date(year, month, day)
        for day in range(1, calendar.monthrange(year, month)[1] + 1)
        if date(year, month, day).weekday() == 4
    ]
    return fridays[2]


class SeasonalityEngine:
    """Computes calendar-effect bias for a symbol from the current date."""

    # ------------------------------------------------------------------
    # Individual effect detectors (all take a date for testability).
    # ------------------------------------------------------------------

    def _is_turn_of_month(self, d: date) -> bool:
        """Last 2 trading days of the month OR first 3 of the next month."""
        month_days = _trading_days_in_range(d.replace(day=1),
                                            d.replace(day=calendar.monthrange(d.year, d.month)[1]))
        if not month_days:
            return False
        last_two = set(month_days[-2:])
        first_three = set(month_days[:3])
        return d in last_two or d in first_three

    def _is_january_effect_window(self, d: date) -> bool:
        """First 5 trading days of January."""
        if d.month != 1:
            return False
        jan_days = _trading_days_in_range(date(d.year, 1, 1), date(d.year, 1, 15))
        return d in set(jan_days[:5])

    def _is_opex_week(self, d: date) -> bool:
        """Week (Mon-Fri) containing the 3rd Friday of the month."""
        try:
            tf = _third_friday(d.year, d.month)
        except Exception:
            return False
        monday = tf - timedelta(days=tf.weekday())   # Monday of OpEx week
        return monday <= d <= tf

    def _is_pre_holiday(self, d: date) -> bool:
        """True if the next trading day is a market holiday."""
        nxt = d + timedelta(days=1)
        # Walk forward over weekends to the next calendar trading slot.
        steps = 0
        while nxt.weekday() >= 5 and steps < 4:
            nxt += timedelta(days=1)
            steps += 1
        return nxt in US_MARKET_HOLIDAYS

    # ------------------------------------------------------------------
    # Signal
    # ------------------------------------------------------------------

    def get_signal(self, symbol: str, now: datetime | None = None) -> dict:
        """
        Aggregate active calendar effects into a single bias score.

        Returns {score, description, effects, opex_week}.
        """
        try:
            now = now or datetime.now()
            today = now.date()
            asset = _classify(symbol)
            sym = (symbol or '').upper()

            score = 0.0
            effects: list = []
            opex_week = self._is_opex_week(today)

            # ---- Crypto: weekend liquidity effect only (24/7, no equity calendar)
            if asset == 'crypto':
                wd = today.weekday()  # 0=Mon .. 6=Sun
                if wd == 4 and now.hour >= 16:   # Friday afternoon → weekend ahead
                    score -= 0.1
                    effects.append('crypto_weekend_low_liquidity')
                elif wd in (5, 6):               # Sat / Sun
                    score -= 0.1
                    effects.append('crypto_weekend_low_liquidity')
                score = round(max(-1.0, min(1.0, score)), 3)
                desc = '; '.join(effects) if effects else 'no notable seasonal effect'
                return {'score': score, 'description': desc,
                        'effects': effects, 'opex_week': False}

            # ---- Forex / futures: minimal calendar seasonality → neutral-ish
            if asset in ('forex', 'futures'):
                return {'score': 0.0,
                        'description': 'no equity calendar seasonality for this asset class',
                        'effects': [], 'opex_week': opex_week}

            # ---- Equities / ETFs --------------------------------------------
            # Turn of month
            if self._is_turn_of_month(today):
                score += 0.4
                effects.append('turn-of-month strength')

            # Sell in May (May 1 - Oct 31 weak; Nov 1 - Apr 30 strong)
            if 5 <= today.month <= 10:
                score -= 0.2
                effects.append('seasonally weak period (sell-in-May)')
            else:
                score += 0.2
                effects.append('seasonally strong period')

            # January effect (small/mid caps only)
            if self._is_january_effect_window(today) and sym in SMALL_MID_CAP_PROXY:
                score += 0.5
                effects.append('January effect')

            # OpEx week — informational (mean-reversion / elevated volatility),
            # score-neutral but surfaced via the opex_week flag.
            if opex_week:
                effects.append('opex week (elevated volatility / mean-reversion)')

            # Day of week
            wd = today.weekday()
            if wd == 0:                          # Monday
                score -= 0.1
                effects.append('monday weakness')
            elif wd == 4 and now.hour >= 13:     # Friday afternoon
                score += 0.1
                effects.append('friday afternoon strength')

            # Pre-holiday drift
            if self._is_pre_holiday(today):
                score += 0.3
                effects.append('pre-holiday drift')

            score = round(max(-1.0, min(1.0, score)), 3)
            desc = '; '.join(e for e in effects
                             if not e.startswith('opex week')) or 'no notable seasonal effect'

            return {'score': score, 'description': desc,
                    'effects': effects, 'opex_week': opex_week}

        except Exception as e:
            log.debug('[SEASON] get_signal(%s) error: %s', symbol, e)
            return {'score': 0.0, 'description': 'error',
                    'effects': [], 'opex_week': False}


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine: 'SeasonalityEngine | None' = None


def get_engine() -> SeasonalityEngine:
    """Return the lazily-created module-level engine singleton."""
    global _engine
    if _engine is None:
        _engine = SeasonalityEngine()
    return _engine


def get_signal(symbol: str) -> dict:
    """Seasonality signal dict for ``symbol`` (never raises)."""
    try:
        return get_engine().get_signal(symbol)
    except Exception as e:
        log.debug('[SEASON] module get_signal error: %s', e)
        return {'score': 0.0, 'description': 'error',
                'effects': [], 'opex_week': False}


def score_contrib(symbol: str) -> float:
    """Just the float score for ``symbol`` (0.0 on failure)."""
    try:
        return float(get_signal(symbol).get('score', 0.0))
    except Exception:
        return 0.0

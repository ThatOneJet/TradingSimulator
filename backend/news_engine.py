"""
NewsEngine — news sentiment and event calendar for AI scoring.

Provides:
  - Finnhub company news sentiment (bullish/bearish/neutral score)
  - News velocity detection (article count spike = news_driven flag)
  - Earnings calendar: days until next earnings per symbol
  - Economic calendar: FOMC, CPI, NFP dates
  - Composite news signal: -2.0 to +2.0 score contribution

Usage:
    from news_engine import NewsEngine, get_engine
    engine = get_engine()
    result = engine.get_signal('AAPL')
    # result: {sentiment_score, news_count, days_to_earnings, event_risk, signal, description}
"""

import os
import logging
import time as _time

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SENTIMENT_TTL  = 900    # 15 min cache for sentiment
EARNINGS_TTL   = 3600   # 1 hour cache for earnings dates
NEWS_WINDOW_H  = 4      # look at news in last 4 hours for velocity
HIGH_VELOCITY  = 5      # articles in window = news_driven flag

# ---------------------------------------------------------------------------
# Hardcoded economic event calendar (2025-2026)
# ---------------------------------------------------------------------------

_ECONOMIC_EVENTS = [
    # FOMC meetings (approximate — update quarterly)
    ('FOMC', '2025-07-30'), ('FOMC', '2025-09-17'), ('FOMC', '2025-11-05'),
    ('FOMC', '2025-12-17'), ('FOMC', '2026-01-28'), ('FOMC', '2026-03-18'),
    ('FOMC', '2026-04-29'), ('FOMC', '2026-06-10'),
    # CPI releases (approximately 2nd week of each month)
    ('CPI', '2025-07-15'), ('CPI', '2025-08-12'), ('CPI', '2025-09-10'),
    ('CPI', '2025-10-15'), ('CPI', '2025-11-13'), ('CPI', '2025-12-11'),
    ('CPI', '2026-01-14'), ('CPI', '2026-02-11'), ('CPI', '2026-03-11'),
    ('CPI', '2026-04-14'), ('CPI', '2026-05-13'),
    # NFP (first Friday of each month)
    ('NFP', '2025-08-01'), ('NFP', '2025-09-05'), ('NFP', '2025-10-03'),
    ('NFP', '2025-11-07'), ('NFP', '2025-12-05'),
    ('NFP', '2026-01-09'), ('NFP', '2026-02-06'), ('NFP', '2026-03-06'),
    ('NFP', '2026-04-03'), ('NFP', '2026-05-01'), ('NFP', '2026-06-05'),
]

# ---------------------------------------------------------------------------
# Internal Finnhub fetch helper
# ---------------------------------------------------------------------------

def _fetch_finnhub(path: str, params: dict):
    """Fetch from Finnhub REST API. Returns parsed JSON or None on failure."""
    key = os.getenv('FINNHUB_KEY', '')
    if not key:
        return None
    import urllib.request
    import urllib.parse
    import json as _json
    params = dict(params)
    params['token'] = key
    url = f'https://finnhub.io/api/v1{path}?' + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return _json.loads(r.read())
    except Exception as e:
        log.debug('[NEWS] Finnhub fetch failed: %s', e)
        return None


# ---------------------------------------------------------------------------
# NewsEngine
# ---------------------------------------------------------------------------

class NewsEngine:
    """Aggregates Finnhub news sentiment and macro calendar into a single signal."""

    def __init__(self):
        self._sentiment_cache: dict[str, tuple[dict, float]] = {}
        self._earnings_cache: dict[str, tuple] = {}  # sym -> (days|None, ts)

    # ------------------------------------------------------------------
    # Sentiment
    # ------------------------------------------------------------------

    def get_sentiment(self, symbol: str) -> dict:
        """
        Fetch Finnhub news-sentiment for *symbol*.

        Returns the raw Finnhub response dict (may include buzz, sentiment,
        companyNewsScore, etc.) or {} on failure.  Cached for SENTIMENT_TTL s.
        """
        now = _time.time()
        cached = self._sentiment_cache.get(symbol)
        if cached and (now - cached[1]) < SENTIMENT_TTL:
            return cached[0]

        data = _fetch_finnhub('/news-sentiment', {'symbol': symbol})
        result = data if isinstance(data, dict) else {}
        self._sentiment_cache[symbol] = (result, now)
        return result

    # ------------------------------------------------------------------
    # Recent news (velocity)
    # ------------------------------------------------------------------

    def get_recent_news(self, symbol: str, hours: int = NEWS_WINDOW_H) -> list:
        """
        Return news items published in the last *hours* hours for *symbol*.

        Calls Finnhub /company-news.  Not cached (volatile endpoint).
        """
        import datetime
        now_dt = datetime.datetime.utcnow()
        from_dt = now_dt - datetime.timedelta(hours=hours)
        date_fmt = '%Y-%m-%d'
        params = {
            'symbol': symbol,
            'from': from_dt.strftime(date_fmt),
            'to': now_dt.strftime(date_fmt),
        }
        data = _fetch_finnhub('/company-news', params)
        if not isinstance(data, list):
            return []

        # Filter to items actually within the requested window
        cutoff_ts = from_dt.timestamp()
        filtered = []
        for item in data:
            ts = item.get('datetime', 0)
            if ts and ts >= cutoff_ts:
                filtered.append(item)
        return filtered

    # ------------------------------------------------------------------
    # Earnings calendar
    # ------------------------------------------------------------------

    def get_days_to_earnings(self, symbol: str) -> 'int | None':
        """
        Return calendar days until the next earnings date for *symbol*.

        Returns None for crypto (-USD), forex (=X), and futures (=F).
        Uses yfinance; result cached for EARNINGS_TTL seconds.
        Returns a negative number if the most-recent next date is already past.
        """
        # Skip non-equity instruments
        if symbol.endswith('-USD') or symbol.endswith('=X') or symbol.endswith('=F'):
            return None

        now = _time.time()
        cached = self._earnings_cache.get(symbol)
        if cached and (now - cached[1]) < EARNINGS_TTL:
            return cached[0]

        days = self._fetch_days_to_earnings(symbol)
        self._earnings_cache[symbol] = (days, now)
        return days

    def _fetch_days_to_earnings(self, symbol: str) -> 'int | None':
        try:
            import yfinance as yf
            import datetime
            ticker = yf.Ticker(symbol)
            ed = ticker.earnings_dates
            if ed is None or ed.empty:
                return None

            now_date = datetime.datetime.utcnow().date()
            # earnings_dates index is tz-aware; convert to plain dates
            future_dates = []
            for idx in ed.index:
                try:
                    d = idx.date() if hasattr(idx, 'date') else idx
                    future_dates.append(d)
                except Exception:
                    continue

            if not future_dates:
                return None

            # Find the nearest upcoming date (or least-past if all in the past)
            future_dates.sort()
            upcoming = [d for d in future_dates if d >= now_date]
            target = upcoming[0] if upcoming else future_dates[-1]
            return (target - now_date).days
        except Exception as e:
            log.debug('[NEWS] Earnings fetch failed for %s: %s', symbol, e)
            return None

    # ------------------------------------------------------------------
    # Economic event calendar
    # ------------------------------------------------------------------

    def is_economic_event_today(self, hours_ahead: int = 24) -> dict:
        """
        Check whether an FOMC, CPI, or NFP event falls within *hours_ahead* hours
        of now (UTC).

        Returns {'event': str|None, 'hours_away': float}.
        If multiple events qualify, returns the nearest one.
        """
        import datetime
        now = datetime.datetime.utcnow()
        best_event = None
        best_hours = float('inf')

        for event_name, date_str in _ECONOMIC_EVENTS:
            try:
                event_dt = datetime.datetime.strptime(date_str, '%Y-%m-%d')
                # Treat event as occurring at 14:00 UTC (typical US release time)
                event_dt = event_dt.replace(hour=14, minute=0, second=0)
                diff_hours = (event_dt - now).total_seconds() / 3600.0
                # Include events up to hours_ahead in the future OR up to 6h in the past
                if -6.0 <= diff_hours <= hours_ahead:
                    if abs(diff_hours) < abs(best_hours):
                        best_hours = diff_hours
                        best_event = event_name
            except Exception:
                continue

        return {
            'event': best_event,
            'hours_away': round(best_hours, 1) if best_event else 0.0,
        }

    # ------------------------------------------------------------------
    # Composite signal
    # ------------------------------------------------------------------

    def get_signal(self, symbol: str) -> dict:
        """
        Compute a composite news/event signal for *symbol*.

        Returns
        -------
        dict with keys:
            signal           float   -2.0 to +2.0 score contribution
            sentiment_score  float   0-1 bullish fraction from Finnhub
            news_count       int     articles in last 4 hours
            news_velocity    bool    True if count >= HIGH_VELOCITY
            days_to_earnings int|None  None for non-equities
            earnings_risk    str     'high'|'moderate'|'low'|'none'
            economic_event   str|None 'FOMC'|'CPI'|'NFP'|None
            description      str     plain-English summary
        """
        signal = 0.0
        description_parts = []

        # --- Sentiment ---
        sentiment = {}
        sentiment_score = 0.5  # neutral default
        try:
            sentiment = self.get_sentiment(symbol)
            bull_pct = sentiment.get('sentiment', {}).get('bullishPercent', 0.5)
            sentiment_score = float(bull_pct)
        except Exception as e:
            log.debug('[NEWS] Sentiment parse error for %s: %s', symbol, e)
            bull_pct = 0.5

        if bull_pct >= 0.75:
            signal += 1.5
            description_parts.append(
                f'strong bullish sentiment ({bull_pct:.0%} of coverage)'
            )
        elif bull_pct >= 0.60:
            signal += 0.8
            description_parts.append('moderately bullish news sentiment')
        elif bull_pct <= 0.30:
            signal -= 1.5
            description_parts.append(
                f'strong bearish sentiment ({1 - bull_pct:.0%} negative coverage)'
            )
        elif bull_pct <= 0.45:
            signal -= 0.8

        # --- News velocity ---
        recent_news = []
        try:
            recent_news = self.get_recent_news(symbol, hours=NEWS_WINDOW_H)
        except Exception as e:
            log.debug('[NEWS] Recent news fetch error for %s: %s', symbol, e)
        news_count = len(recent_news)
        news_velocity = news_count >= HIGH_VELOCITY
        if news_velocity:
            description_parts.append(
                f'{news_count} articles in last 4h — news-driven volatility likely'
            )
        # Velocity is a caution flag, not directional — do not shift signal

        # --- Earnings proximity ---
        days_to_earnings = None
        earnings_risk = 'none'
        try:
            days_to_earnings = self.get_days_to_earnings(symbol)
        except Exception as e:
            log.debug('[NEWS] Earnings lookup error for %s: %s', symbol, e)

        if days_to_earnings is not None:
            if days_to_earnings <= 1:
                signal *= 0.2
                earnings_risk = 'high'
                description_parts.append('earnings tomorrow — signal unreliable')
            elif days_to_earnings <= 3:
                signal *= 0.5
                earnings_risk = 'moderate'
                description_parts.append(
                    f'earnings in {days_to_earnings} days — reduced conviction'
                )
            elif days_to_earnings <= 7:
                signal *= 0.75
                earnings_risk = 'low'
            else:
                earnings_risk = 'none'

        # --- Economic event risk ---
        economic_event = None
        try:
            eco = self.is_economic_event_today(48)
            economic_event = eco['event']
            if eco['event'] and eco['hours_away'] <= 24:
                signal *= 0.5
                description_parts.append(
                    f"{eco['event']} in {eco['hours_away']:.0f}h — macro risk"
                )
        except Exception as e:
            log.debug('[NEWS] Economic event check error: %s', e)
            eco = {'event': None, 'hours_away': 0.0}

        # --- Clamp and package ---
        signal = round(max(-2.0, min(2.0, signal)), 2)
        description = '; '.join(description_parts) if description_parts else 'no notable news signals'

        return {
            'signal': signal,
            'sentiment_score': round(sentiment_score, 4),
            'news_count': news_count,
            'news_velocity': news_velocity,
            'days_to_earnings': days_to_earnings,
            'earnings_risk': earnings_risk,
            'economic_event': economic_event,
            'description': description,
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine: 'NewsEngine | None' = None


def get_engine() -> NewsEngine:
    """Return the shared NewsEngine singleton, creating it on first call."""
    global _engine
    if _engine is None:
        _engine = NewsEngine()
    return _engine

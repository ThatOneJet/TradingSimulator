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

SENTIMENT_TTL  = 3600   # 1 hour cache — was 15min, causing 429s on free tier (60 req/min limit)
EARNINGS_TTL   = 7200   # 2 hour cache
EVENT_TTL      = 3600   # 1 hour cache
NEWS_WINDOW_H  = 4      # look at news in last 4 hours for velocity
HIGH_VELOCITY  = 5      # articles in window = news_driven flag

# ---------------------------------------------------------------------------
# Rule-based event detection (keyword -> causal impact)
# ---------------------------------------------------------------------------
#
# Specific event types in headlines map to a directional score, a label, and a
# typical horizon.  These are more reliable than raw aggregate sentiment for
# known, well-understood catalysts.
#
#   EVENT_KEYWORDS[key] = (score, label, horizon)
#
EVENT_KEYWORDS = {
    # (keywords) : (score, label, horizon)
    'earnings_beat':   (1.5,  'earnings beat',          'swing'),
    'earnings_miss':   (-2.0, 'earnings miss',          'swing'),
    'guidance_raise':  (1.5,  'raised guidance',        'multi-day'),
    'guidance_cut':    (-1.8, 'cut guidance',           'multi-day'),
    'upgrade':         (1.0,  'analyst upgrade',        'swing'),
    'downgrade':       (-1.0, 'analyst downgrade',      'swing'),
    'acquisition':     (1.2,  'M&A / buyout',           'multi-day'),
    'investigation':   (-1.5, 'regulatory/legal risk',  'multi-day'),
    'lawsuit':         (-0.8, 'lawsuit',                'swing'),
    'partnership':     (0.8,  'partnership/deal',        'swing'),
    'layoffs':         (0.3,  'cost cutting (mild pos)', 'swing'),
    'recall':          (-1.0, 'product recall',          'swing'),
    'bankruptcy':      (-2.0, 'bankruptcy risk',         'multi-day'),
}

# Phrase fragments that, when found in a headline (case-insensitive), map to one
# of the EVENT_KEYWORDS keys above.  Order does not matter — detection keeps the
# highest-magnitude match across all headlines.
EVENT_PHRASES = {
    'earnings_beat': (
        'beat', 'beats', 'tops estimates', 'beats expectations',
        'beats estimates', 'tops expectations', 'tops forecast',
        'better than expected', 'earnings beat', 'crushes estimates',
    ),
    'earnings_miss': (
        'misses', 'miss estimates', 'misses estimates', 'falls short',
        'misses expectations', 'worse than expected', 'earnings miss',
        'disappointing results', 'disappoints',
    ),
    'guidance_raise': (
        'raises guidance', 'raises outlook', 'raises forecast',
        'lifts guidance', 'boosts outlook', 'raises full-year',
        'hikes guidance', 'upbeat guidance', 'raised guidance',
    ),
    'guidance_cut': (
        'cuts guidance', 'lowers outlook', 'lowers guidance',
        'cuts forecast', 'lowers forecast', 'slashes guidance',
        'warns on', 'profit warning', 'cut guidance',
    ),
    'upgrade': (
        'upgrades', 'upgraded', 'buy rating', 'raises price target',
        'raised to buy', 'overweight rating', 'outperform rating',
        'initiates buy', 'analyst upgrade',
    ),
    'downgrade': (
        'downgrades', 'downgraded', 'sell rating', 'cuts price target',
        'cut to sell', 'underweight rating', 'underperform rating',
        'initiates sell', 'analyst downgrade',
    ),
    'acquisition': (
        'to acquire', 'acquires', 'merger', 'buyout', 'takeover',
        'to buy', 'acquisition of', 'agrees to acquire', 'm&a',
    ),
    'investigation': (
        'sec probe', 'investigation', 'probe', 'doj investigation',
        'regulatory probe', 'antitrust', 'under investigation',
        'ftc probe', 'subpoena',
    ),
    'lawsuit': (
        'lawsuit', 'sued', 'sues', 'class action', 'legal action',
        'files suit', 'litigation',
    ),
    'partnership': (
        'partnership', 'partners with', 'strategic deal', 'signs deal',
        'collaboration', 'teams up', 'joint venture', 'new contract',
        'wins contract', 'inks deal',
    ),
    'layoffs': (
        'layoffs', 'job cuts', 'cuts jobs', 'restructuring',
        'cost cutting', 'cost-cutting', 'reduces workforce', 'lay off',
    ),
    'recall': (
        'recall', 'recalls', 'product recall', 'safety recall',
    ),
    'bankruptcy': (
        'bankruptcy', 'chapter 11', 'insolvency', 'files for bankruptcy',
        'going concern', 'default on debt',
    ),
}

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

_finnhub_last_call = 0.0
_finnhub_min_gap   = 2.0   # minimum 2 seconds between Finnhub calls (free tier: 60/min)

def _fetch_finnhub(path: str, params: dict):
    """Fetch from Finnhub REST API with rate limiting. Returns parsed JSON or None."""
    global _finnhub_last_call
    key = os.getenv('FINNHUB_KEY', '')
    if not key:
        return None
    import urllib.request, urllib.parse, json as _json
    # Rate limit: wait if called too fast
    elapsed = time.time() - _finnhub_last_call
    if elapsed < _finnhub_min_gap:
        time.sleep(_finnhub_min_gap - elapsed)
    params = dict(params)
    params['token'] = key
    url = f'https://finnhub.io/api/v1{path}?' + urllib.parse.urlencode(params)
    try:
        _finnhub_last_call = time.time()
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
        self._event_cache: dict[str, tuple[dict, float]] = {}  # sym -> (event_dict, ts)

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
    # Rule-based event detection from headlines
    # ------------------------------------------------------------------

    @staticmethod
    def _neutral_event() -> dict:
        """A neutral (no-event) detection result."""
        return {
            'event': None,
            'score': 0.0,
            'label': 'no notable event',
            'horizon': 'none',
            'headline': '',
        }

    def detect_events(self, symbol: str) -> dict:
        """
        Scan recent company-news headlines for known causal event types.

        Reuses ``get_recent_news`` (widened to a 48-hour window so freshly
        published catalysts are not missed), matches each headline against the
        EVENT_PHRASES keyword groups (case-insensitive), and returns the single
        highest-magnitude event found.

        Returns
        -------
        dict with keys:
            event    str|None  EVENT_KEYWORDS key (e.g. 'earnings_beat') or None
            score    float     directional impact (negative = bearish)
            label    str        human-readable label
            horizon  str        'swing' | 'multi-day' | 'none'
            headline str        the headline that triggered the match ('' if none)

        Cached for EVENT_TTL (30 min).  Returns a neutral default on any error.
        """
        try:
            now = _time.time()
            cached = self._event_cache.get(symbol)
            if cached and (now - cached[1]) < EVENT_TTL:
                return cached[0]

            # Look back far enough to catch a just-released catalyst.
            try:
                news = self.get_recent_news(symbol, hours=48)
            except Exception as e:
                log.debug('[NEWS] detect_events news fetch error for %s: %s', symbol, e)
                news = []

            best = self._neutral_event()
            best_mag = 0.0

            for item in news:
                try:
                    headline = (item.get('headline') or item.get('summary') or '')
                except AttributeError:
                    continue
                if not headline:
                    continue
                text = headline.lower()

                for key, phrases in EVENT_PHRASES.items():
                    if any(p in text for p in phrases):
                        score, label, horizon = EVENT_KEYWORDS[key]
                        mag = abs(score)
                        if mag > best_mag:
                            best_mag = mag
                            best = {
                                'event': key,
                                'score': float(score),
                                'label': label,
                                'horizon': horizon,
                                'headline': headline,
                            }

            self._event_cache[symbol] = (best, now)
            return best
        except Exception as e:
            log.debug('[NEWS] detect_events failed for %s: %s', symbol, e)
            return self._neutral_event()

    # ------------------------------------------------------------------
    # Earnings pre-drift positioning
    # ------------------------------------------------------------------

    def earnings_drift_signal(self, symbol: str) -> dict:
        """
        Pre-earnings drift / run-up positioning signal.

        Stocks statistically drift UP in the ~5-10 trading days before an
        earnings release.  Uses ``get_days_to_earnings``.

            * 3-10 days out  -> +0.8 (pre-earnings drift window, long bias)
            * 1-2 days out   ->  0.0 (too close — IV-crush risk handled elsewhere)
            * 0 or negative  ->  0.0 (just reported)
            * otherwise      ->  0.0

        Returns
        -------
        dict with keys:
            score             float    score contribution (0.0 or +0.8)
            description       str       plain-English summary
            days_to_earnings  int|None  days until next earnings (None for non-equity)
        """
        try:
            try:
                dte = self.get_days_to_earnings(symbol)
            except Exception as e:
                log.debug('[NEWS] earnings_drift lookup error for %s: %s', symbol, e)
                dte = None

            if dte is None:
                return {
                    'score': 0.0,
                    'description': 'no earnings date available',
                    'days_to_earnings': None,
                }

            if 3 <= dte <= 10:
                return {
                    'score': 0.8,
                    'description': f'pre-earnings drift window ({dte}d out) — long bias',
                    'days_to_earnings': dte,
                }
            if 1 <= dte <= 2:
                return {
                    'score': 0.0,
                    'description': 'earnings imminent — IV-crush risk, no drift bias',
                    'days_to_earnings': dte,
                }
            if dte <= 0:
                return {
                    'score': 0.0,
                    'description': 'just reported — no pre-earnings drift',
                    'days_to_earnings': dte,
                }
            return {
                'score': 0.0,
                'description': f'earnings {dte}d out — outside drift window',
                'days_to_earnings': dte,
            }
        except Exception as e:
            log.debug('[NEWS] earnings_drift_signal failed for %s: %s', symbol, e)
            return {
                'score': 0.0,
                'description': 'earnings drift unavailable',
                'days_to_earnings': None,
            }

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
            event            dict    headline-event detection
                                     {event, score, label, horizon, headline}
            pre_earnings     dict    pre-earnings drift positioning
                                     {score, description, days_to_earnings}
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

        # --- Rule-based headline event (additive, independent catalyst) ---
        event = self._neutral_event()
        try:
            event = self.detect_events(symbol)
            if event.get('event'):
                signal += float(event.get('score', 0.0))
                description_parts.append(
                    f"{event['label']} detected ({event['horizon']})"
                )
        except Exception as e:
            log.debug('[NEWS] Event detection error for %s: %s', symbol, e)
            event = self._neutral_event()

        # --- Pre-earnings drift positioning (additive long bias) ---
        pre_earnings = {'score': 0.0, 'description': '', 'days_to_earnings': days_to_earnings}
        try:
            pre_earnings = self.earnings_drift_signal(symbol)
            if pre_earnings.get('score'):
                signal += float(pre_earnings['score'])
                description_parts.append(pre_earnings.get('description', 'pre-earnings drift'))
        except Exception as e:
            log.debug('[NEWS] Earnings drift error for %s: %s', symbol, e)
            pre_earnings = {'score': 0.0, 'description': '', 'days_to_earnings': days_to_earnings}

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
            'event': event,
            'pre_earnings': pre_earnings,
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


# ---------------------------------------------------------------------------
# Module-level convenience wrappers (for the main scorer)
# ---------------------------------------------------------------------------

def event_signal(symbol: str) -> dict:
    """
    Detect the highest-magnitude headline event for *symbol*.

    Returns dict: {event, score, label, horizon, headline}.
    Neutral default ({event: None, score: 0.0, ...}) on any error.
    """
    try:
        return get_engine().detect_events(symbol)
    except Exception as e:
        log.debug('[NEWS] event_signal failed for %s: %s', symbol, e)
        return NewsEngine._neutral_event()


def earnings_drift_signal(symbol: str) -> dict:
    """
    Pre-earnings drift positioning for *symbol*.

    Returns dict: {score, description, days_to_earnings}.
    Neutral default ({score: 0.0, ...}) on any error.
    """
    try:
        return get_engine().earnings_drift_signal(symbol)
    except Exception as e:
        log.debug('[NEWS] earnings_drift_signal (module) failed for %s: %s', symbol, e)
        return {'score': 0.0, 'description': 'earnings drift unavailable', 'days_to_earnings': None}


def event_contrib(symbol: str) -> float:
    """Just the numeric headline-event score contribution (0.0 on error/no event)."""
    try:
        return float(event_signal(symbol).get('score', 0.0) or 0.0)
    except Exception:
        return 0.0


def drift_contrib(symbol: str) -> float:
    """Just the numeric pre-earnings drift score contribution (0.0 on error)."""
    try:
        return float(earnings_drift_signal(symbol).get('score', 0.0) or 0.0)
    except Exception:
        return 0.0

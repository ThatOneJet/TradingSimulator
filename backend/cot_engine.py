"""
COT — CFTC Commitment of Traders weekly positioning for futures.
Commercials (smart-money hedgers) at positioning extremes precede major turns.
Maps futures symbols to CFTC market codes; fetches the public CFTC report.
"""

import threading
import logging
import time as _time

log = logging.getLogger(__name__)

# Cache weekly data for 24h — the CFTC report updates only once per week.
CACHE_TTL = 86400  # 24 hours

# How many weeks of history to pull for the COT index range.
LOOKBACK_WEEKS = 26

# CFTC contract market codes (legacy futures-only report, dataset 6dca-aqww).
# Best-known codes; an unknown/failed code simply yields a neutral signal.
CFTC_CODES = {
    'GC=F':     '088691',   # Gold
    'SI=F':     '084691',   # Silver
    'HG=F':     '085692',   # Copper
    'CL=F':     '067651',   # WTI Crude Oil
    'NG=F':     '023651',   # Natural Gas
    'ZB=F':     '020601',   # 30Y US Treasury Bond
    'ZN=F':     '043602',   # 10Y US Treasury Note
    'ES=F':     '13874A',   # E-mini S&P 500
    'ZC=F':     '002602',   # Corn
    'ZW=F':     '001602',   # Wheat
    'ZS=F':     '005602',   # Soybeans
    'EURUSD=X': '099741',   # Euro FX
    'GBPUSD=X': '096742',   # British Pound
    'JPYUSD=X': '097741',   # Japanese Yen
    'AUDUSD=X': '232741',   # Australian Dollar
}

CFTC_URL = (
    'https://publicreporting.cftc.gov/resource/6dca-aqww.json'
    '?cftc_contract_market_code={code}'
    '&$order=report_date_as_yyyy_mm_dd%20DESC'
    '&$limit={limit}'
)


class COTEngine:
    """
    Fetches and caches CFTC Commitment of Traders positioning per futures/forex
    symbol, then derives a 0-100 COT index from the commercial net position.
    """

    def __init__(self):
        self._lock = threading.Lock()
        # symbol -> {'index': float, 'commercial_net': int, 'nets': [...],
        #            'fetched_at': float}
        self._cache = {}

    # ------------------------------------------------------------------
    # Fetch
    # ------------------------------------------------------------------

    def _fetch(self, code: str) -> list:
        """
        Pull the last LOOKBACK_WEEKS rows for a contract code from the CFTC
        public API. Returns a list of weekly dicts ordered newest-first:
            {'date', 'comm_net', 'spec_net'}
        Returns [] on any error or unexpected format.
        """
        import urllib.request
        import json

        url = CFTC_URL.format(code=code, limit=LOOKBACK_WEEKS)
        try:
            req = urllib.request.Request(
                url, headers={'User-Agent': 'TradeSimulator-COT/1.0'}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
            rows = json.loads(raw)
        except Exception as e:
            log.debug('[COT] fetch failed for %s: %s', code, e)
            return []

        if not isinstance(rows, list) or not rows:
            return []

        weekly = []
        for row in rows:
            try:
                comm_long = self._num(row.get('comm_positions_long_all'))
                comm_short = self._num(row.get('comm_positions_short_all'))
                spec_long = self._num(row.get('noncomm_positions_long_all'))
                spec_short = self._num(row.get('noncomm_positions_short_all'))
                if comm_long is None or comm_short is None:
                    continue
                entry = {
                    'date': row.get('report_date_as_yyyy_mm_dd', ''),
                    'comm_net': comm_long - comm_short,
                }
                if spec_long is not None and spec_short is not None:
                    entry['spec_net'] = spec_long - spec_short
                else:
                    entry['spec_net'] = 0
                weekly.append(entry)
            except Exception:
                continue

        return weekly

    @staticmethod
    def _num(val):
        """Coerce a CFTC field (string) to int, or None if not parseable."""
        try:
            if val is None:
                return None
            return int(float(val))
        except Exception:
            return None

    # ------------------------------------------------------------------
    # COT index
    # ------------------------------------------------------------------

    def _compute(self, symbol: str) -> dict:
        """Fetch + compute the COT index for a covered symbol; cache result."""
        code = CFTC_CODES.get(symbol)
        if not code:
            return self._neutral()

        weekly = self._fetch(code)
        if not weekly:
            return self._neutral()

        nets = [w['comm_net'] for w in weekly if 'comm_net' in w]
        if len(nets) < 2:
            return self._neutral()

        current = nets[0]                      # newest week (DESC order)
        lo = min(nets)
        hi = max(nets)
        span = hi - lo
        if span <= 0:
            cot_index = 50.0
        else:
            # Where current commercial net sits in its 26-week range.
            cot_index = (current - lo) / span * 100.0

        result = {
            'index': round(float(cot_index), 1),
            'commercial_net': int(current),
            'weeks': len(nets),
            'fetched_at': _time.time(),
        }
        with self._lock:
            self._cache[symbol] = result
        log.info(
            '[COT] %s — index=%.1f commercial_net=%d (%d wks)',
            symbol, result['index'], result['commercial_net'], result['weeks'],
        )
        return result

    @staticmethod
    def _neutral() -> dict:
        return {
            'index': 50.0,
            'commercial_net': 0,
            'weeks': 0,
            'fetched_at': _time.time(),
        }

    def _get_cached(self, symbol: str) -> dict:
        """Return a fresh cached result or recompute if stale/missing."""
        try:
            with self._lock:
                cached = self._cache.get(symbol)
            if cached and (_time.time() - cached.get('fetched_at', 0)) < CACHE_TTL:
                return cached
            return self._compute(symbol)
        except Exception as e:
            log.debug('[COT] cache resolve error for %s: %s', symbol, e)
            return self._neutral()

    # ------------------------------------------------------------------
    # Signal
    # ------------------------------------------------------------------

    def get_signal(self, symbol: str) -> dict:
        """
        Translate the COT index into a positioning signal.
        Only futures/forex symbols with a known CFTC code are scored.
        """
        try:
            sym = (symbol or '').upper().strip()
            if sym not in CFTC_CODES:
                return {
                    'score': 0.0,
                    'description': 'no CFTC coverage for symbol',
                    'cot_index': None,
                    'commercial_net': None,
                }

            data = self._get_cached(sym)
            cot_index = data.get('index', 50.0)
            commercial_net = data.get('commercial_net', 0)

            if data.get('weeks', 0) < 2:
                return {
                    'score': 0.0,
                    'description': 'COT data unavailable',
                    'cot_index': None,
                    'commercial_net': None,
                }

            if cot_index > 80:
                score = 1.5
                desc = 'commercials max long — smart money bullish'
            elif cot_index < 20:
                score = -1.5
                desc = 'commercials max short — smart money bearish'
            else:
                # Proportional small score: maps [20,80] index → roughly [-0.5,+0.5].
                score = round((cot_index - 50.0) / 60.0, 3)
                desc = 'commercials in mid-range positioning'

            return {
                'score': float(score),
                'description': desc,
                'cot_index': round(float(cot_index), 1),
                'commercial_net': int(commercial_net),
            }
        except Exception as e:
            log.debug('[COT] get_signal error for %s: %s', symbol, e)
            return {
                'score': 0.0,
                'description': 'COT unavailable',
                'cot_index': None,
                'commercial_net': None,
            }

    def score_contrib(self, symbol: str) -> float:
        try:
            return float(self.get_signal(symbol).get('score', 0.0))
        except Exception as e:
            log.debug('[COT] score_contrib error for %s: %s', symbol, e)
            return 0.0


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine = None


def get_engine() -> COTEngine:
    """Return the lazily-constructed module singleton."""
    global _engine
    if _engine is None:
        _engine = COTEngine()
    return _engine


def get_signal(symbol: str) -> dict:
    try:
        return get_engine().get_signal(symbol)
    except Exception as e:
        log.debug('[COT] module get_signal error: %s', e)
        return {
            'score': 0.0,
            'description': 'COT unavailable',
            'cot_index': None,
            'commercial_net': None,
        }


def score_contrib(symbol: str) -> float:
    try:
        return get_engine().score_contrib(symbol)
    except Exception as e:
        log.debug('[COT] module score_contrib error: %s', e)
        return 0.0

"""
Intermarket — systematic cross-asset rules. Oil spikes help energy, hurt airlines.
Rising yields hurt growth/tech, help banks. Gold ATH = risk-off. Dollar strength
hurts commodities. These relationships are mechanical, not predictive.
"""

import threading
import logging
import time as _time

log = logging.getLogger(__name__)

# How long a cached macro snapshot stays fresh before a lazy refresh fires.
REFRESH_INTERVAL = 600  # 10 minutes

# Macro instruments fetched in one bulk download.
#   CL=F      crude oil futures
#   GC=F      gold futures
#   ZN=F      10Y Treasury note futures (bond price; inverse of yield)
#   DX-Y.NYB  US dollar index
#   ^TNX      CBOE 10Y Treasury yield index
#   UUP       Invesco dollar bullish ETF (dollar fallback)
#   SPY       S&P 500 ETF (broad equities)
MACRO_TICKERS = ['CL=F', 'GC=F', 'ZN=F', 'DX-Y.NYB', '^TNX', 'UUP', 'SPY']

# ---------------------------------------------------------------------------
# Symbol → category classifier
# ---------------------------------------------------------------------------

_ENERGY = {'XOM', 'CVX', 'COP', 'SLB', 'OXY', 'EOG', 'PSX', 'VLO', 'MPC', 'HAL'}
_TECH_GROWTH = {
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'GOOG', 'META', 'AMZN', 'TSLA', 'AMD',
    'NFLX', 'CRM', 'ADBE', 'SHOP', 'SNOW', 'PLTR', 'COIN', 'ARKK', 'QQQ',
}
_BANKS = {'JPM', 'BAC', 'GS', 'MS', 'WFC', 'C', 'USB', 'PNC', 'TFC', 'SCHW'}
_MATERIALS = {
    'FCX', 'NEM', 'GOLD', 'SCCO', 'AA', 'X', 'CLF', 'NUE', 'VALE', 'GLD',
    'SLV', 'GDX', 'MOS', 'CF', 'DOW',
}


def classify(symbol: str) -> str:
    """Map a trading symbol to a coarse intermarket category."""
    try:
        s = (symbol or '').upper().strip()
        if not s:
            return 'broad'
        # Crypto convention: BTC-USD, ETH/USD, BTCUSDT, etc.
        if ('-USD' in s or '/USD' in s or s.endswith('USDT')
                or s in {'BTC', 'ETH', 'SOL', 'XRP', 'DOGE', 'ADA'}):
            return 'crypto'
        base = s.split('-')[0].split('/')[0]
        if base in _ENERGY:
            return 'energy'
        if base in _BANKS:
            return 'bank'
        if base in _TECH_GROWTH:
            return 'tech_growth'
        if base in _MATERIALS:
            return 'material'
        return 'broad'
    except Exception as e:
        log.debug('[INTERMARKET] classify error for %s: %s', symbol, e)
        return 'broad'


class IntermarketEngine:
    """
    Lazily refreshes a snapshot of macro instrument moves and applies
    mechanical cross-asset rules per symbol category.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._state = {}          # {oil_chg, gold_chg, yield_chg, dollar_chg, spy_chg, ...}
        self._fetched_at = 0.0

    # ------------------------------------------------------------------
    # State / refresh
    # ------------------------------------------------------------------

    def _is_stale(self) -> bool:
        return (_time.time() - self._fetched_at) > REFRESH_INTERVAL

    def get_state(self) -> dict:
        """Return recent macro moves, lazy-refreshing if the cache is stale."""
        try:
            if self._is_stale():
                self._refresh()
            with self._lock:
                return dict(self._state)
        except Exception as e:
            log.debug('[INTERMARKET] get_state error: %s', e)
            with self._lock:
                return dict(self._state)

    def _refresh(self) -> None:
        """Bulk-fetch macro instruments and compute 3d/5d % moves + trend."""
        try:
            import yfinance as yf
        except ImportError:
            log.debug('[INTERMARKET] yfinance not installed; skipping refresh')
            return

        try:
            data = yf.download(
                MACRO_TICKERS, period='7d', interval='1d',
                progress=False, group_by='ticker', threads=True,
            )
        except Exception as e:
            log.debug('[INTERMARKET] bulk download failed: %s', e)
            return

        moves = {}
        for ticker in MACRO_TICKERS:
            moves[ticker] = self._instrument_move(data, ticker)

        state = self._build_state(moves)
        if not state:
            return

        with self._lock:
            self._state = state
            self._fetched_at = _time.time()

        log.info(
            '[INTERMARKET] refreshed — oil=%+.1f%% gold=%+.1f%% yield=%+.2f '
            'dollar=%+.1f%% spy=%+.1f%%',
            state.get('oil_chg', 0), state.get('gold_chg', 0),
            state.get('yield_chg', 0), state.get('dollar_chg', 0),
            state.get('spy_chg', 0),
        )

    @staticmethod
    def _closes(data, ticker):
        """Extract a clean list of closes for one ticker from a bulk download."""
        try:
            # Multi-ticker download => columns are MultiIndex (ticker, field)
            if ticker in getattr(data, 'columns', []) or (
                hasattr(data.columns, 'levels') and ticker in data.columns.levels[0]
            ):
                sub = data[ticker]['Close']
            else:
                sub = data['Close']
            closes = [float(c) for c in sub.tolist() if c == c]  # drop NaN
            return closes
        except Exception:
            return []

    def _instrument_move(self, data, ticker) -> dict:
        """Compute 3-day and 5-day % change (absolute change for ^TNX) + trend."""
        try:
            closes = self._closes(data, ticker)
            if len(closes) < 2:
                return {}
            last = closes[-1]
            # 3-day and 5-day lookbacks (clamped to available history).
            ref3 = closes[-4] if len(closes) >= 4 else closes[0]
            ref5 = closes[-6] if len(closes) >= 6 else closes[0]

            # ^TNX is a yield in percent points; report absolute change, not %.
            if ticker == '^TNX':
                chg3 = last - ref3
                chg5 = last - ref5
            else:
                chg3 = (last - ref3) / ref3 * 100 if ref3 else 0.0
                chg5 = (last - ref5) / ref5 * 100 if ref5 else 0.0

            ma = sum(closes[-5:]) / min(5, len(closes))
            trend = 'up' if last > ma else 'down'
            return {
                'last': round(last, 4),
                'chg3': round(chg3, 4),
                'chg5': round(chg5, 4),
                'trend': trend,
            }
        except Exception as e:
            log.debug('[INTERMARKET] move calc failed for %s: %s', ticker, e)
            return {}

    def _build_state(self, moves) -> dict:
        """Collapse per-instrument moves into the flat macro state dict."""
        try:
            oil = moves.get('CL=F', {})
            gold = moves.get('GC=F', {})
            tnx = moves.get('^TNX', {})
            bond = moves.get('ZN=F', {})
            dxy = moves.get('DX-Y.NYB', {})
            uup = moves.get('UUP', {})
            spy = moves.get('SPY', {})

            # Yield: prefer ^TNX week change; fall back to inverse of bond price.
            if tnx:
                yield_chg = tnx.get('chg5', 0.0)          # absolute pts over ~week
                yield_trend = tnx.get('trend', 'flat')
            elif bond:
                # Bond price up => yields down; invert the % move into a proxy.
                yield_chg = -bond.get('chg5', 0.0) * 0.05  # rough pts proxy
                yield_trend = 'down' if bond.get('trend') == 'up' else 'up'
            else:
                yield_chg = None
                yield_trend = None

            # Dollar: prefer DX-Y.NYB; fall back to UUP.
            if dxy:
                dollar_chg = dxy.get('chg5', 0.0)
                dollar_trend = dxy.get('trend', 'flat')
            elif uup:
                dollar_chg = uup.get('chg5', 0.0)
                dollar_trend = uup.get('trend', 'flat')
            else:
                dollar_chg = 0.0
                dollar_trend = 'flat'

            # Gold multi-week high proxy: positive week move + uptrend.
            gold_chg5 = gold.get('chg5', 0.0)
            gold_high = gold.get('trend') == 'up' and gold_chg5 > 1.0

            return {
                'oil_chg': oil.get('chg3', 0.0),
                'oil_chg5': oil.get('chg5', 0.0),
                'oil_trend': oil.get('trend', 'flat'),
                'gold_chg': gold_chg5,
                'gold_trend': gold.get('trend', 'flat'),
                'gold_at_high': gold_high,
                'yield_chg': yield_chg,           # absolute pts over week (or None)
                'yield_trend': yield_trend,
                'dollar_chg': dollar_chg,         # % over week
                'dollar_trend': dollar_trend,
                'spy_chg': spy.get('chg3', 0.0),
                'spy_trend': spy.get('trend', 'flat'),
            }
        except Exception as e:
            log.debug('[INTERMARKET] build_state error: %s', e)
            return {}

    # ------------------------------------------------------------------
    # Signal
    # ------------------------------------------------------------------

    def get_signal(self, symbol: str) -> dict:
        """Apply mechanical cross-asset rules for a symbol's category."""
        try:
            category = classify(symbol)
            state = self.get_state()
            score = 0.0
            applied = []
            desc = []

            oil = state.get('oil_chg', 0.0)
            yield_chg = state.get('yield_chg')        # may be None if unavailable
            dollar = state.get('dollar_chg', 0.0)
            gold_high = state.get('gold_at_high', False)
            spy_down = state.get('spy_trend') == 'down'

            if category == 'energy':
                if oil > 3.0:
                    score += 1.5
                    applied.append('oil_rally_energy')
                    desc.append('oil rally lifts energy')
                elif oil < -3.0:
                    score -= 1.0
                    applied.append('oil_drop_energy')
                    desc.append('falling oil hurts energy')

            elif category == 'tech_growth':
                if yield_chg is not None:
                    if yield_chg > 0.15:
                        score -= 1.2
                        applied.append('yields_up_growth')
                        desc.append('rising yields pressure growth')
                    elif yield_chg < -0.15:
                        score += 0.6
                        applied.append('yields_down_growth')
                        desc.append('falling yields support growth')

            elif category == 'bank':
                if yield_chg is not None and yield_chg > 0.15:
                    score += 1.0
                    applied.append('yields_up_banks')
                    desc.append('rising yields help bank margins')

            elif category == 'material':
                if dollar > 1.0:
                    score -= 0.8
                    applied.append('dollar_up_commodities')
                    desc.append('strong dollar pressures commodities')
                elif dollar < -1.0:
                    score += 0.5
                    applied.append('dollar_down_commodities')
                    desc.append('weak dollar supports commodities')

            elif category == 'crypto':
                if dollar > 1.0:
                    score -= 0.3
                    applied.append('dollar_up_crypto')
                    desc.append('dollar strength is mild risk-off for crypto')

            # Broad risk-off overlay applies to broad equities and any equity name.
            if category in ('broad', 'tech_growth', 'bank', 'energy', 'material'):
                if gold_high and spy_down:
                    score -= 0.5
                    applied.append('risk_off_backdrop')
                    desc.append('risk-off backdrop')

            score = round(max(-2.0, min(2.0, score)), 3)
            description = '; '.join(desc) if desc else 'no active intermarket rules'
            return {
                'score': score,
                'description': description,
                'applied_rules': applied,
                'category': category,
            }
        except Exception as e:
            log.debug('[INTERMARKET] get_signal error for %s: %s', symbol, e)
            return {
                'score': 0.0,
                'description': 'intermarket unavailable',
                'applied_rules': [],
                'category': 'broad',
            }

    def score_contrib(self, symbol: str) -> float:
        try:
            return float(self.get_signal(symbol).get('score', 0.0))
        except Exception as e:
            log.debug('[INTERMARKET] score_contrib error for %s: %s', symbol, e)
            return 0.0


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine = None


def get_engine() -> IntermarketEngine:
    """Return the lazily-constructed module singleton."""
    global _engine
    if _engine is None:
        _engine = IntermarketEngine()
    return _engine


def get_state() -> dict:
    try:
        return get_engine().get_state()
    except Exception as e:
        log.debug('[INTERMARKET] module get_state error: %s', e)
        return {}


def get_signal(symbol: str) -> dict:
    try:
        return get_engine().get_signal(symbol)
    except Exception as e:
        log.debug('[INTERMARKET] module get_signal error: %s', e)
        return {
            'score': 0.0,
            'description': 'intermarket unavailable',
            'applied_rules': [],
            'category': 'broad',
        }


def score_contrib(symbol: str) -> float:
    try:
        return get_engine().score_contrib(symbol)
    except Exception as e:
        log.debug('[INTERMARKET] module score_contrib error: %s', e)
        return 0.0

"""
CorrelationBreak — detects when two normally-correlated assets diverge.
BTC/ETH normally r≈0.9; when one moves and the other doesn't, that's a signal.

For each known pair we measure the typical rolling correlation and the recent
short-term return spread. When a historically tight pair suddenly diverges
(the recent spread blows out beyond ~2σ of its normal range), the laggard
often catches up toward the leader, while the leader that ran ahead carries
mild mean-reversion risk.
"""

import logging
import math
import time

log = logging.getLogger(__name__)

# Historically correlated pairs (a, b)
PAIRS = [
    ('BTC-USD', 'ETH-USD'),
    ('ETH-USD', 'SOL-USD'),
    ('XLK', 'QQQ'),
    ('GC=F', 'SI=F'),
    ('SPY', 'QQQ'),
    ('XOM', 'CVX'),
    ('EURUSD=X', 'GBPUSD=X'),
]

_CACHE_TTL = 300            # 5 minutes
_CORR_THRESHOLD = 0.6       # pair must be this correlated to "count"
_SIGMA_MULT = 2.0           # divergence threshold in σ of the spread
_RECENT_N = 3              # short-term window (days) for the divergence spread


class CorrelationEngine:
    """Caches a divergence scan across known correlated pairs."""

    def __init__(self):
        self._divergences: list = []   # list of break dicts
        self._ts = 0.0

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------

    def _recent_returns(self, symbol: str, n: int = 10) -> list:
        """Trailing daily % returns for ``symbol`` (most recent last)."""
        try:
            import yfinance as yf

            hist = yf.Ticker(symbol).history(period='15d')
            if hist is None or hist.empty:
                return []
            closes = [float(x) for x in hist['Close'].tolist() if x and x > 0]
            if len(closes) < 2:
                return []
            rets = []
            for i in range(1, len(closes)):
                prev = closes[i - 1]
                if prev > 0:
                    rets.append((closes[i] - prev) / prev * 100.0)
            return rets[-n:]
        except Exception as e:
            log.debug('[CORR] _recent_returns(%s) error: %s', symbol, e)
            return []

    @staticmethod
    def _pearson(xs: list, ys: list) -> float:
        """Pearson correlation of two equal-length return series."""
        try:
            n = min(len(xs), len(ys))
            if n < 3:
                return 0.0
            xs, ys = xs[-n:], ys[-n:]
            mx = sum(xs) / n
            my = sum(ys) / n
            cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
            vx = sum((x - mx) ** 2 for x in xs)
            vy = sum((y - my) ** 2 for y in ys)
            if vx <= 0 or vy <= 0:
                return 0.0
            return cov / math.sqrt(vx * vy)
        except Exception:
            return 0.0

    @staticmethod
    def _stdev(vals: list) -> float:
        n = len(vals)
        if n < 2:
            return 0.0
        m = sum(vals) / n
        var = sum((v - m) ** 2 for v in vals) / (n - 1)
        return math.sqrt(var)

    # ------------------------------------------------------------------
    # Divergence scan
    # ------------------------------------------------------------------

    def check_divergence(self) -> list:
        """
        Scan all pairs and return the list of currently-diverging ones.

        Each entry: {pair, leader, laggard, spread, signal}. Cached 5 min.
        """
        try:
            if self._divergences is not None and (time.time() - self._ts) < _CACHE_TTL:
                return list(self._divergences)

            results = []
            for a, b in PAIRS:
                try:
                    ra = self._recent_returns(a, n=10)
                    rb = self._recent_returns(b, n=10)
                    if len(ra) < 5 or len(rb) < 5:
                        continue

                    n = min(len(ra), len(rb))
                    ra, rb = ra[-n:], rb[-n:]

                    # Typical relationship over the window
                    corr = self._pearson(ra, rb)
                    if abs(corr) < _CORR_THRESHOLD:
                        continue   # not reliably correlated → nothing to break

                    # Spread series and its normal dispersion
                    spreads = [ra[i] - rb[i] for i in range(n)]
                    sd = self._stdev(spreads)
                    if sd <= 0:
                        continue

                    # Recent short-term divergence (sum of last few days)
                    recent_spread = sum(spreads[-_RECENT_N:])
                    cum_a = sum(ra[-_RECENT_N:])
                    cum_b = sum(rb[-_RECENT_N:])

                    # σ of the cumulative recent spread
                    threshold = _SIGMA_MULT * sd * math.sqrt(_RECENT_N)
                    if abs(recent_spread) < threshold:
                        continue   # within normal range → no break

                    # Leader = the one that moved more (by recent cumulative return)
                    if abs(cum_a) >= abs(cum_b):
                        leader, laggard, lead_move = a, b, cum_a
                    else:
                        leader, laggard, lead_move = b, a, cum_b

                    signal = 'up' if lead_move > 0 else 'down'
                    results.append({
                        'pair':    (a, b),
                        'leader':  leader,
                        'laggard': laggard,
                        'spread':  round(recent_spread, 3),
                        'signal':  signal,
                    })
                    log.debug('[CORR] break %s/%s leader=%s spread=%.2f r=%.2f',
                              a, b, leader, recent_spread, corr)
                except Exception as e:
                    log.debug('[CORR] pair %s/%s error: %s', a, b, e)
                    continue

            self._divergences = results
            self._ts = time.time()
            return list(results)

        except Exception as e:
            log.debug('[CORR] check_divergence error: %s', e)
            return []

    # ------------------------------------------------------------------
    # Signal
    # ------------------------------------------------------------------

    def get_signal(self, symbol: str) -> dict:
        """
        If ``symbol`` is the laggard in a fresh divergence it may catch up to
        the leader (momentum in the leader's direction). If it's the leader
        that ran ahead, flag mild mean-reversion caution.

        Returns {score, description, diverged, partner}. Score in -1.0..+1.0.
        """
        try:
            sym = (symbol or '').upper()
            breaks = self.check_divergence()

            for br in breaks:
                leader = br['leader'].upper()
                laggard = br['laggard'].upper()
                direction = br['signal']  # leader's move direction

                if sym == laggard:
                    # Laggard catches up toward the leader's direction
                    score = 0.7 if direction == 'up' else -0.7
                    desc = ('correlated leader %s moved %s — laggard may catch up'
                            % (br['leader'], direction))
                    return self._signal(score, desc, True, br['leader'])

                if sym == leader:
                    # Leader ran ahead → mild mean-reversion caution (opposite sign)
                    score = -0.4 if direction == 'up' else 0.4
                    desc = ('ran ahead of %s — mild mean-reversion risk'
                            % br['laggard'])
                    return self._signal(score, desc, True, br['laggard'])

            return self._signal(0.0, 'no correlation break', False, None)

        except Exception as e:
            log.debug('[CORR] get_signal(%s) error: %s', symbol, e)
            return self._signal(0.0, 'error', False, None)

    @staticmethod
    def _signal(score: float, desc: str, diverged: bool, partner) -> dict:
        return {
            'score':       round(float(max(-1.0, min(1.0, score))), 3),
            'description': desc,
            'diverged':    diverged,
            'partner':     partner,
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine: 'CorrelationEngine | None' = None


def get_engine() -> CorrelationEngine:
    """Return the lazily-created module-level engine singleton."""
    global _engine
    if _engine is None:
        _engine = CorrelationEngine()
    return _engine


def get_signal(symbol: str) -> dict:
    """Correlation-break signal dict for ``symbol`` (never raises)."""
    try:
        return get_engine().get_signal(symbol)
    except Exception as e:
        log.debug('[CORR] module get_signal error: %s', e)
        return {'score': 0.0, 'description': 'error',
                'diverged': False, 'partner': None}


def score_contrib(symbol: str) -> float:
    """Just the float score for ``symbol`` (0.0 on failure)."""
    try:
        return float(get_signal(symbol).get('score', 0.0))
    except Exception:
        return 0.0

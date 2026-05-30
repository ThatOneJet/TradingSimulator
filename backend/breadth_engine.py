"""
BreadthEngine — market-wide advance-decline and breadth signals.

Polls yfinance for a basket of S&P 500 representative stocks
every 5 minutes and computes:
  - Advance-decline ratio
  - % of stocks above their 20-day MA
  - Overall market breadth signal: strong_bull/bull/neutral/bear/strong_bear

Subscribes to no events — runs its own polling thread.
Publishes breadth:market on EventBus when data updates.
"""

import logging
import threading
import time

log = logging.getLogger(__name__)

# Representative basket — covers all major sectors
BREADTH_BASKET = [
    # Tech
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'META', 'AMZN', 'AMD', 'INTC',
    # Finance
    'JPM', 'BAC', 'GS', 'MS',
    # Healthcare
    'JNJ', 'UNH', 'PFE', 'ABBV',
    # Energy
    'XOM', 'CVX', 'COP',
    # Consumer
    'WMT', 'HD', 'MCD', 'NKE',
    # Industrial
    'CAT', 'BA', 'HON', 'GE',
    # ETFs as anchors
    'SPY', 'QQQ', 'IWM',
]

POLL_INTERVAL = 300   # 5 minutes


class BreadthEngine:
    """
    Polls a basket of representative S&P 500 stocks on a background thread
    and computes advance-decline and moving-average breadth metrics.

    Publishes 'breadth:market' on the provided EventBus each cycle.
    """

    def __init__(self, event_bus=None):
        self._bus     = event_bus
        self._lock    = threading.Lock()
        self._latest  = {}       # latest breadth snapshot
        self._thread  = None
        self._running = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background polling thread."""
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        log.info('[BREADTH] BreadthEngine started')

    def stop(self) -> None:
        """Signal the polling thread to stop (best-effort)."""
        self._running = False
        log.info('[BREADTH] BreadthEngine stopping')

    def latest(self) -> dict:
        """Return the most recent breadth snapshot (thread-safe)."""
        with self._lock:
            return dict(self._latest)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        """Main polling loop — runs forever until stop() is called."""
        # Do an initial update immediately so callers get data fast
        try:
            self._update()
        except Exception as e:
            log.debug('[BREADTH] initial poll error: %s', e)

        while self._running:
            time.sleep(POLL_INTERVAL)
            if not self._running:
                break
            try:
                self._update()
            except Exception as e:
                log.debug('[BREADTH] poll error: %s', e)

    def _update(self) -> None:
        """Fetch historical data for each ticker, compute breadth metrics, publish."""
        import yfinance as yf

        advancing   = 0
        declining   = 0
        above_ma20  = 0
        total_valid = 0

        for sym in BREADTH_BASKET:
            try:
                hist = yf.Ticker(sym).history(period='25d', interval='1d')
                if hist.empty or len(hist) < 2:
                    continue
                closes = list(hist['Close'])
                last   = closes[-1]
                prev   = closes[-2]
                # Use however many closes we have (up to 20)
                ma20   = sum(closes[-20:]) / min(20, len(closes))

                if last > prev:
                    advancing += 1
                else:
                    declining += 1

                if last > ma20:
                    above_ma20 += 1

                total_valid += 1

            except Exception:
                continue

        if total_valid == 0:
            log.warning('[BREADTH] No valid tickers — skipping snapshot')
            return

        ad_ratio  = advancing / total_valid
        ma20_pct  = above_ma20 / total_valid

        # Classify breadth signal
        if   ad_ratio >= 0.70 and ma20_pct >= 0.65:
            signal = 'strong_bull'
        elif ad_ratio >= 0.55 and ma20_pct >= 0.50:
            signal = 'bull'
        elif ad_ratio <= 0.30 and ma20_pct <= 0.35:
            signal = 'strong_bear'
        elif ad_ratio <= 0.45 and ma20_pct <= 0.45:
            signal = 'bear'
        else:
            signal = 'neutral'

        # Score contribution for AI scoring: range -1.5 to +1.5
        score_contrib = (
             1.5 if signal == 'strong_bull' else
             0.8 if signal == 'bull'        else
            -0.8 if signal == 'bear'        else
            -1.5 if signal == 'strong_bear' else
             0.0
        )

        snapshot = {
            'advancing':      advancing,
            'declining':      declining,
            'total':          total_valid,
            'ad_ratio':       round(ad_ratio, 3),
            'above_ma20_pct': round(ma20_pct, 3),
            'signal':         signal,
            'score_contrib':  score_contrib,
            'updated_at':     time.time(),
        }

        with self._lock:
            self._latest = snapshot

        if self._bus:
            self._bus.publish('breadth:market', snapshot)

        log.info(
            '[BREADTH] %s — A/D=%.0f%% above_MA20=%.0f%%',
            signal, ad_ratio * 100, ma20_pct * 100,
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine: 'BreadthEngine | None' = None


def init(event_bus=None) -> BreadthEngine:
    """
    Create and start the module-level BreadthEngine singleton.

    Call once at application startup:
        import breadth_engine
        breadth_engine.init(event_bus=my_bus)
    """
    global _engine
    _engine = BreadthEngine(event_bus)
    _engine.start()
    return _engine


def latest() -> dict:
    """Return the most recent breadth snapshot, or {} if not yet initialised."""
    return _engine.latest() if _engine else {}


def score_contrib() -> float:
    """
    Return the AI score contribution from market breadth (-1.5 … +1.5).

    Returns 0.0 if the engine has not been initialised or has no data yet.
    """
    data = latest()
    return float(data.get('score_contrib', 0.0))


def get_signal() -> str:
    """
    Return the current breadth signal string
    ('strong_bull', 'bull', 'neutral', 'bear', 'strong_bear').

    Returns 'neutral' if the engine has not been initialised or has no data yet.
    """
    data = latest()
    return data.get('signal', 'neutral')

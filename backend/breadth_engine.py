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
        # Short rolling history for price/breadth divergence detection.
        # Each entry: {'price': float, 'breadth_pct': float,
        #              'ad_ratio': float, 'ts': float}
        self._history = []
        self._history_max = 12

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

    def detect_divergence(self) -> dict:
        """
        Compare recent index price action against breadth participation.

        Bearish divergence: price makes a new recent high but breadth (% above
        MA20) is LOWER than at the prior swing high — fewer stocks confirming.
        Bullish divergence: price makes a new recent low but advance/decline /
        breadth is HOLDING UP or improving — selling exhaustion.

        Returns {'divergence': 'bearish'|'bullish'|'none',
                 'score': float, 'description': str}.
        """
        none = {'divergence': 'none', 'score': 0.0, 'description': ''}
        try:
            with self._lock:
                hist = list(self._history)
            if len(hist) < 4:
                return none

            prices  = [h['price'] for h in hist]
            breadth = [h['breadth_pct'] for h in hist]
            ad      = [h['ad_ratio'] for h in hist]

            cur_price   = prices[-1]
            cur_breadth = breadth[-1]
            cur_ad      = ad[-1]

            prior_prices  = prices[:-1]
            prior_breadth = breadth[:-1]
            prior_ad      = ad[:-1]

            max_prior_price = max(prior_prices)
            min_prior_price = min(prior_prices)

            # --- Bearish divergence: new recent high, weaker breadth ---
            if cur_price >= max_prior_price:
                # breadth reading at the prior price high
                prior_high_idx = prior_prices.index(max_prior_price)
                breadth_at_prior_high = prior_breadth[prior_high_idx]
                if cur_breadth < breadth_at_prior_high - 0.03:
                    return {
                        'divergence': 'bearish',
                        'score': -1.0,
                        'description': 'breadth not confirming new high',
                    }

            # --- Bullish divergence: new recent low, breadth firming ---
            if cur_price <= min_prior_price:
                prior_low_idx = prior_prices.index(min_prior_price)
                ad_at_prior_low = prior_ad[prior_low_idx]
                breadth_at_prior_low = prior_breadth[prior_low_idx]
                if (cur_ad > ad_at_prior_low + 0.03 or
                        cur_breadth > breadth_at_prior_low + 0.03):
                    return {
                        'divergence': 'bullish',
                        'score': 1.0,
                        'description': 'selling exhaustion, breadth firming',
                    }

            return none
        except Exception as e:
            log.debug('[BREADTH] detect_divergence error: %s', e)
            return none

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
        spy_last    = None          # SPY price level (preferred index proxy)
        basket_sum  = 0.0           # sum of last closes (basket-average fallback)

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

                if sym == 'SPY':
                    spy_last = last
                basket_sum += last
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

        # Index price proxy: prefer SPY's level, else the basket average.
        price_level = spy_last if spy_last is not None else (basket_sum / total_valid)

        snapshot = {
            'advancing':      advancing,
            'declining':      declining,
            'total':          total_valid,
            'ad_ratio':       round(ad_ratio, 3),
            'above_ma20_pct': round(ma20_pct, 3),
            'price_level':    round(price_level, 4),
            'signal':         signal,
            'score_contrib':  score_contrib,
            'updated_at':     time.time(),
        }

        with self._lock:
            self._latest = snapshot
            # Append to rolling price/breadth history for divergence detection.
            self._history.append({
                'price':       price_level,
                'breadth_pct': ma20_pct,
                'ad_ratio':    ad_ratio,
                'ts':          time.time(),
            })
            if len(self._history) > self._history_max:
                self._history = self._history[-self._history_max:]

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


def divergence_signal() -> dict:
    """
    Return the MARKET-WIDE price/breadth divergence signal.

    This is not per-symbol — it reflects whether the index price action and
    market breadth agree, and applies to equity/index symbols.

    Returns {'divergence': 'bearish'|'bullish'|'none',
             'score': float, 'description': str}.
    Returns the 'none' result if the engine is not initialised / lacks history.
    """
    if not _engine:
        return {'divergence': 'none', 'score': 0.0, 'description': ''}
    return _engine.detect_divergence()


def divergence_contrib() -> float:
    """
    Return just the market-wide divergence score contribution (-1.0 … +1.0).

    Returns 0.0 if the engine is not initialised or there is no divergence.
    """
    return float(divergence_signal().get('score', 0.0))

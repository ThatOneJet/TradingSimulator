"""
MacroEngine — cross-asset correlation and macro regime signals.

Tracks key macro instruments every 15 minutes using yfinance:
  - GLD: gold (inflation hedge / fear asset)
  - TLT: 20Y Treasury bonds (risk-off / rates)
  - UUP: US Dollar ETF (global risk appetite)
  - VIX proxy: SPY ATR% vs 20-day average

Computes:
  - risk_on / risk_off / neutral environment
  - Sector sensitivity (equity, crypto correlated with macro differently)
  - Per-symbol macro adjustment score: -1.0 to +1.0
"""

import threading, logging, time as _time

log = logging.getLogger(__name__)

MACRO_POLL_INTERVAL = 900  # 15 minutes
MACRO_INSTRUMENTS = {
    'GLD': 'gold',
    'TLT': 'bonds',
    'UUP': 'dollar',
    'SPY': 'equity',
}


class MacroEngine:
    def __init__(self):
        self._lock    = threading.Lock()
        self._latest  = {}      # {ticker: {price, change_pct, trend}}
        self._regime  = 'neutral'
        self._score   = 0.0
        self._running = False

    def start(self) -> None:
        self._running = True
        t = threading.Thread(target=self._poll_loop, daemon=True)
        t.start()
        log.info('[MACRO] MacroEngine started (15m poll)')

    def stop(self) -> None:
        self._running = False
        log.info('[MACRO] MacroEngine stopped')

    def _poll_loop(self) -> None:
        while self._running:
            try:
                self._update()
            except Exception as e:
                log.debug('[MACRO] poll error: %s', e)
            _time.sleep(MACRO_POLL_INTERVAL)

    def _update(self) -> None:
        try:
            import yfinance as yf
        except ImportError:
            log.debug('[MACRO] yfinance not installed; skipping update')
            return

        readings = {}
        for ticker, name in MACRO_INSTRUMENTS.items():
            try:
                hist = yf.Ticker(ticker).history(period='5d', interval='1d')
                if hist.empty or len(hist) < 2:
                    continue
                closes  = list(hist['Close'])
                last    = closes[-1]
                prev    = closes[-2]
                chg_pct = (last - prev) / prev * 100 if prev else 0
                ma5     = sum(closes[-5:]) / min(5, len(closes))
                trend   = 'up' if last > ma5 else 'down'
                readings[name] = {
                    'price':      round(float(last), 4),
                    'change_pct': round(float(chg_pct), 3),
                    'trend':      trend,
                }
            except Exception as e:
                log.debug('[MACRO] failed to fetch %s: %s', ticker, e)
                continue

        if not readings:
            return

        # Macro regime logic:
        # Risk-ON:  bonds down + dollar flat/down + gold flat + equities up
        # Risk-OFF: bonds up  + dollar up         + gold up   + equities down

        bond_up   = readings.get('bonds',  {}).get('trend') == 'up'
        dollar_up = readings.get('dollar', {}).get('trend') == 'up'
        gold_up   = readings.get('gold',   {}).get('trend') == 'up'
        equity_up = readings.get('equity', {}).get('trend') == 'up'

        risk_on_signals  = [equity_up, not bond_up, not dollar_up]
        risk_off_signals = [bond_up, gold_up, dollar_up, not equity_up]

        risk_on_count  = sum(risk_on_signals)
        risk_off_count = sum(risk_off_signals)

        if risk_on_count >= 2 and risk_off_count <= 1:
            regime = 'risk_on'
            score  = 0.8
        elif risk_off_count >= 3:
            regime = 'risk_off'
            score  = -1.0
        elif risk_off_count >= 2:
            regime = 'cautious'
            score  = -0.4
        else:
            regime = 'neutral'
            score  = 0.0

        # Gold surge = inflation fear = negative for growth stocks
        gold_chg = readings.get('gold', {}).get('change_pct', 0)
        if gold_chg > 1.5:
            score -= 0.3
        elif gold_chg < -1.0:
            score += 0.2

        # Dollar strength = negative for commodities and international
        dollar_chg = readings.get('dollar', {}).get('change_pct', 0)
        if dollar_chg > 0.5:
            score -= 0.2
        elif dollar_chg < -0.5:
            score += 0.2

        score = round(max(-1.0, min(1.0, score)), 3)

        with self._lock:
            self._latest = readings
            self._regime = regime
            self._score  = score

        log.info('[MACRO] %s — score=%.2f (bonds=%s dollar=%s gold=%s equity=%s)',
                 regime, score,
                 readings.get('bonds',  {}).get('trend', '?'),
                 readings.get('dollar', {}).get('trend', '?'),
                 readings.get('gold',   {}).get('trend', '?'),
                 readings.get('equity', {}).get('trend', '?'))

    def get_signal(self, asset_class: str = 'equity') -> dict:
        """
        Returns macro score adjusted for asset class sensitivity.
        Crypto is less macro-sensitive than equities; forex is macro-driven.
        """
        try:
            with self._lock:
                regime = self._regime
                score  = self._score
                latest = dict(self._latest)

            # Asset class sensitivity multipliers
            sensitivity = {
                'equity':  1.0,   # fully exposed to macro
                'crypto':  0.4,   # partially correlated (risk-on/off matters but less)
                'futures': 0.9,   # very macro-sensitive
                'forex':   0.7,   # macro matters but has its own drivers
            }.get(asset_class, 1.0)

            return {
                'regime':        regime,
                'score':         score,
                'score_contrib': round(score * sensitivity, 3),
                'sensitivity':   sensitivity,
                'readings':      latest,
            }
        except Exception as e:
            log.debug('[MACRO] get_signal error: %s', e)
            return {
                'regime':        'neutral',
                'score':         0.0,
                'score_contrib': 0.0,
                'sensitivity':   1.0,
                'readings':      {},
            }

    def latest(self) -> dict:
        try:
            with self._lock:
                return {
                    'regime':   self._regime,
                    'score':    self._score,
                    'readings': dict(self._latest),
                }
        except Exception as e:
            log.debug('[MACRO] latest error: %s', e)
            return {'regime': 'neutral', 'score': 0.0, 'readings': {}}

    def force_refresh(self) -> None:
        """Trigger an immediate macro data update (blocking)."""
        try:
            self._update()
        except Exception as e:
            log.debug('[MACRO] force_refresh error: %s', e)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine: MacroEngine | None = None


def init() -> MacroEngine:
    global _engine
    _engine = MacroEngine()
    _engine.start()
    return _engine


def get_signal(asset_class: str = 'equity') -> dict:
    if _engine is None:
        return {
            'regime':        'neutral',
            'score':         0.0,
            'score_contrib': 0.0,
            'sensitivity':   1.0,
            'readings':      {},
        }
    return _engine.get_signal(asset_class)


def score_contrib(asset_class: str = 'equity') -> float:
    return get_signal(asset_class).get('score_contrib', 0.0)


def regime() -> str:
    return _engine._regime if _engine else 'neutral'


def latest() -> dict:
    if _engine is None:
        return {'regime': 'neutral', 'score': 0.0, 'readings': {}}
    return _engine.latest()

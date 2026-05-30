"""
OptionsEngine — Black-Scholes pricing, Greeks computation, IV solving, and
option chain fetching from Alpaca.

Provides:
  - Black-Scholes call/put pricing and analytical Greeks (delta, gamma, theta, vega)
  - Implied volatility solver via Newton-Raphson iteration
  - IV Rank and IV Percentile from stored historical IV
  - Option chain fetching: pick best contract for a given signal and DTE target
  - OptionSignal: composite options-specific trade recommendation

All math is pure Python stdlib — no scipy, no numpy.
"""

import os
import math
import logging
import time
from datetime import date, datetime, timedelta

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Normal distribution helpers
# ---------------------------------------------------------------------------

def _norm_cdf(x: float) -> float:
    """Standard normal CDF using Abramowitz & Stegun approximation."""
    a1, a2, a3, a4, a5 = 0.319381530, -0.356563782, 1.781477937, -1.821255978, 1.330274429
    p = 0.2316419
    k = 1.0 / (1.0 + p * abs(x))
    poly = k * (a1 + k * (a2 + k * (a3 + k * (a4 + k * a5))))
    val  = 1.0 - (1.0 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * x * x) * poly
    return val if x >= 0 else 1.0 - val


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


# ---------------------------------------------------------------------------
# Black-Scholes pricing
# ---------------------------------------------------------------------------

def bs_price(S: float, K: float, T: float, r: float, sigma: float,
             opt_type: str = 'call') -> float:
    """Black-Scholes option price. T in years, sigma annualized."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return max(0.0, (S - K) if opt_type == 'call' else (K - S))
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if opt_type == 'call':
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    else:
        return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def bs_greeks(S: float, K: float, T: float, r: float, sigma: float,
              opt_type: str = 'call') -> dict:
    """Compute delta, gamma, theta, vega, rho analytically."""
    if T <= 0 or sigma <= 0:
        return {'delta': 0.0, 'gamma': 0.0, 'theta': 0.0, 'vega': 0.0, 'rho': 0.0}
    d1  = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2  = d1 - sigma * math.sqrt(T)
    pdf = _norm_pdf(d1)
    if opt_type == 'call':
        delta = _norm_cdf(d1)
        rho   = K * T * math.exp(-r * T) * _norm_cdf(d2) / 100
    else:
        delta = _norm_cdf(d1) - 1.0
        rho   = -K * T * math.exp(-r * T) * _norm_cdf(-d2) / 100
    gamma = pdf / (S * sigma * math.sqrt(T))
    vega  = S * pdf * math.sqrt(T) / 100          # per 1% move in vol
    theta = (-(S * pdf * sigma) / (2 * math.sqrt(T))
             - r * K * math.exp(-r * T) * (_norm_cdf(d2) if opt_type == 'call' else _norm_cdf(-d2))
             ) / 365                               # per calendar day
    return {
        'delta': round(delta, 4), 'gamma': round(gamma, 6),
        'theta': round(theta, 4), 'vega': round(vega, 4), 'rho': round(rho, 4),
    }


def implied_vol(market_price: float, S: float, K: float, T: float,
                r: float, opt_type: str = 'call',
                max_iter: int = 100, tol: float = 1e-6) -> float | None:
    """Newton-Raphson IV solver. Returns annualized IV or None if no solution."""
    if T <= 0 or market_price <= 0:
        return None
    sigma = 0.3  # initial guess
    for _ in range(max_iter):
        price = bs_price(S, K, T, r, sigma, opt_type)
        vega  = S * _norm_pdf((math.log(S/K) + (r + 0.5*sigma**2)*T)/(sigma*math.sqrt(T))) * math.sqrt(T)
        if vega < 1e-10:
            break
        diff = price - market_price
        if abs(diff) < tol:
            return round(max(0.001, min(5.0, sigma)), 4)
        sigma -= diff / vega
        sigma = max(0.001, min(5.0, sigma))
    return round(sigma, 4) if 0.001 < sigma < 5.0 else None


# ---------------------------------------------------------------------------
# IVHistory — track historical IV for IV Rank / Percentile
# ---------------------------------------------------------------------------

class IVHistory:
    """Stores daily IV readings per symbol for IV Rank computation."""
    WINDOW = 252  # trading days (1 year)

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_table()

    def _init_table(self):
        import sqlite3
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''CREATE TABLE IF NOT EXISTS iv_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    iv REAL NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT (date('now'))
                )''')
                conn.execute(
                    'CREATE INDEX IF NOT EXISTS ix_iv_sym ON iv_history(symbol, recorded_at)'
                )
        except Exception as e:
            log.warning('[IV_HISTORY] Failed to init table: %s', e)

    def record(self, symbol: str, iv: float):
        """Record a daily IV observation (one per symbol per day)."""
        import sqlite3
        try:
            with sqlite3.connect(self.db_path) as conn:
                existing = conn.execute(
                    "SELECT id FROM iv_history WHERE symbol=? AND recorded_at=date('now')",
                    (symbol,)).fetchone()
                if not existing:
                    conn.execute(
                        'INSERT INTO iv_history (symbol, iv) VALUES (?, ?)', (symbol, iv)
                    )
        except Exception as e:
            log.debug('[IV_HISTORY] record error for %s: %s', symbol, e)

    def iv_rank(self, symbol: str, current_iv: float) -> float | None:
        """IV Rank: (current - 52wk_low) / (52wk_high - 52wk_low). Returns 0-100."""
        import sqlite3
        try:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    f'SELECT iv FROM iv_history WHERE symbol=? '
                    f'ORDER BY recorded_at DESC LIMIT {self.WINDOW}',
                    (symbol,)).fetchall()
            if len(rows) < 20:
                return None
            ivs = [r[0] for r in rows]
            lo, hi = min(ivs), max(ivs)
            if hi <= lo:
                return 50.0
            return round((current_iv - lo) / (hi - lo) * 100, 1)
        except Exception as e:
            log.debug('[IV_HISTORY] iv_rank error for %s: %s', symbol, e)
            return None

    def iv_percentile(self, symbol: str, current_iv: float) -> float | None:
        """IV Percentile: % of days in past year where IV was below current."""
        import sqlite3
        try:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    f'SELECT iv FROM iv_history WHERE symbol=? '
                    f'ORDER BY recorded_at DESC LIMIT {self.WINDOW}',
                    (symbol,)).fetchall()
            if len(rows) < 20:
                return None
            ivs = [r[0] for r in rows]
            below = sum(1 for v in ivs if v < current_iv)
            return round(below / len(ivs) * 100, 1)
        except Exception as e:
            log.debug('[IV_HISTORY] iv_percentile error for %s: %s', symbol, e)
            return None


# ---------------------------------------------------------------------------
# OptionsChain — fetch and filter contracts from Alpaca
# ---------------------------------------------------------------------------

class OptionsChain:
    RISK_FREE_RATE = 0.045  # ~4.5% US Treasury — update periodically

    def __init__(self):
        self._key    = os.getenv('ALPACA_API_KEY', '')
        self._secret = os.getenv('ALPACA_SECRET_KEY', '')

    def _fetch(self, url: str) -> dict:
        import urllib.request
        import json as _json
        try:
            req = urllib.request.Request(url, headers={
                'APCA-API-KEY-ID': self._key,
                'APCA-API-SECRET-KEY': self._secret,
            })
            with urllib.request.urlopen(req, timeout=8) as r:
                return _json.loads(r.read())
        except Exception as e:
            log.debug('[OPTIONS_CHAIN] fetch error (%s): %s', url, e)
            raise

    def get_contracts(self, underlying: str, dte_min: int = 20, dte_max: int = 60,
                      opt_type: str | None = None,
                      underlying_price: float | None = None) -> list[dict]:
        """Fetch tradable contracts within DTE range, filtered near ATM."""
        try:
            today   = date.today()
            date_lo = (today + timedelta(days=dte_min)).isoformat()
            date_hi = (today + timedelta(days=dte_max)).isoformat()
            url = (f'https://paper-api.alpaca.markets/v2/options/contracts'
                   f'?underlying_symbols={underlying}'
                   f'&expiration_date_gte={date_lo}&expiration_date_lte={date_hi}'
                   f'&status=active&limit=100')
            if opt_type:
                url += f'&type={opt_type}'
            data = self._fetch(url)
            contracts = [c for c in data.get('option_contracts', []) if c.get('tradable')]

            # Filter near-ATM strikes (within 20% of underlying price)
            if underlying_price and underlying_price > 0 and contracts:
                lo = underlying_price * 0.80
                hi = underlying_price * 1.20
                atm = [c for c in contracts
                       if lo <= float(c.get('strike_price', 0)) <= hi]
                contracts = atm if atm else contracts

            return contracts
        except Exception as e:
            log.debug('[OPTIONS_CHAIN] get_contracts error for %s: %s', underlying, e)
            return []

    def get_quote(self, option_symbol: str) -> dict | None:
        """Get bid/ask for a specific option contract."""
        try:
            url  = f'https://data.alpaca.markets/v1beta1/options/snapshots?symbols={option_symbol}'
            data = self._fetch(url)
            snap = data.get('snapshots', {}).get(option_symbol, {})
            q    = snap.get('latestQuote', {})
            if not q:
                return None
            bid, ask = float(q.get('bp', 0)), float(q.get('ap', 0))
            mid = (bid + ask) / 2
            spread_pct = (ask - bid) / mid * 100 if mid > 0 else 999
            return {'bid': bid, 'ask': ask, 'mid': mid, 'spread_pct': round(spread_pct, 1)}
        except Exception as e:
            log.debug('[OPTIONS_CHAIN] get_quote error for %s: %s', option_symbol, e)
            return None

    def _hist_vol(self, underlying: str) -> float:
        """Compute 20-day historical volatility from yfinance as IV fallback."""
        try:
            import yfinance as yf, math
            hist = yf.Ticker(underlying).history(period='30d', interval='1d')
            if hist.empty or len(hist) < 5:
                return 0.30
            closes = list(hist['Close'].dropna())
            rets   = [math.log(closes[i] / closes[i-1]) for i in range(1, len(closes))]
            mean   = sum(rets) / len(rets)
            var    = sum((r - mean) ** 2 for r in rets) / len(rets)
            return round(max(0.05, min(2.0, (var ** 0.5) * (252 ** 0.5))), 4)
        except Exception:
            return 0.30

    def enrich_contract(self, contract: dict, underlying_price: float) -> dict:
        """Add Greeks, IV, and theoretical price to a contract dict.
        Uses live bid/ask when valid; falls back to Black-Scholes with
        historical volatility when paper trading quotes are stale."""
        try:
            K        = float(contract['strike_price'])
            exp      = date.fromisoformat(contract['expiration_date'])
            T        = max(0.001, (exp - date.today()).days / 365.0)
            S        = underlying_price
            r        = self.RISK_FREE_RATE
            opt_type = contract.get('type', 'call')
            dte_days = (exp - date.today()).days

            # Always use theoretical pricing in paper trading —
            # live option quotes are stale and unreliable in paper accounts.
            # Use live quote only to check if contract is actively traded.
            quote = self.get_quote(contract['symbol'])
            is_liquid = (quote and quote.get('bid', 0) > 0 and quote.get('ask', 0) > 0)

            underlying_sym = contract.get('underlying_symbol') or contract.get('root_symbol', '')
            iv = self._hist_vol(underlying_sym) if underlying_sym else 0.30
            mid_price  = bs_price(S, K, T, r, iv, opt_type)
            spread_pct = quote.get('spread_pct', 5.0) if is_liquid else 5.0
            bid        = round(mid_price * 0.975, 4)
            ask        = round(mid_price * 1.025, 4)

            greeks = bs_greeks(S, K, T, r, iv or 0.30, opt_type)

            return {**contract,
                    'mid': quote['mid'], 'bid': quote['bid'], 'ask': quote['ask'],
                    'spread_pct': quote['spread_pct'],
                    'iv': iv, 'T': round(T, 4), 'dte': (exp - date.today()).days,
                    **greeks}
        except Exception as e:
            log.debug('[OPTIONS_CHAIN] enrich_contract error for %s: %s',
                      contract.get('symbol'), e)
            return contract


# ---------------------------------------------------------------------------
# OptionsEngine — main class combining everything
# ---------------------------------------------------------------------------

def _asset_class(sym: str) -> str:
    """Coarse asset-class detection (self-contained — no app.py dependency).
    Options PCR is only meaningful for listed equities/ETFs."""
    s = (sym or '').upper().strip()
    if s.endswith('-USD') or s.endswith('/USD') or s.endswith('USDT'):
        return 'crypto'
    if s.endswith('=X'):
        return 'forex'
    if s.endswith('=F'):
        return 'futures'
    return 'equity'


class OptionsEngine:
    MAX_SPREAD_PCT = 8.0   # skip illiquid contracts
    MIN_DELTA_LONG = 0.30  # min delta for long options (not too far OTM)
    MAX_DELTA_LONG = 0.70  # max delta for long options (not deep ITM)

    # Put/Call Ratio sentiment thresholds
    PCR_BULLISH_BELOW = 0.7    # pcr < 0.7 → bullish positioning
    PCR_BEARISH_ABOVE = 1.3    # pcr > 1.3 → bearish positioning
    PCR_CACHE_TTL     = 1800   # cache live PCR for 30 minutes per symbol

    def __init__(self, db_path: str):
        self.chain   = OptionsChain()
        self.iv_hist = IVHistory(db_path)
        self._pcr_cache: dict[str, tuple[float, dict]] = {}   # symbol → (ts, result)

    def get_signal(self, underlying: str, underlying_price: float,
                   ai_score: float, regime: str) -> dict:
        """
        Given an AI score and regime, recommend an options strategy and contract.

        Returns:
        {
            'strategy':      str,    # 'long_call'|'long_put'|'bull_spread'|'bear_spread'|'iron_condor'|'none'
            'contract':      dict,   # enriched contract dict (or None)
            'contract_b':   dict,   # second leg for spreads (or None)
            'iv_rank':       float|None,
            'iv_percentile': float|None,
            'rationale':     str,
            'max_risk':      float,  # max loss per contract in dollars
            'max_reward':    float,  # max gain per contract in dollars
        }
        """
        try:
            # Determine strategy based on score + IV environment
            strategy = self._select_strategy(ai_score, regime)
            if strategy == 'none':
                return self._empty(strategy, 'Score too weak for options trade')

            opt_type = 'call' if 'call' in strategy or 'bull' in strategy else 'put'

            # Fetch chain
            contracts_raw = self.chain.get_contracts(
                underlying, dte_min=15, dte_max=90,
                opt_type=opt_type, underlying_price=underlying_price
            )
            if not contracts_raw:
                return self._empty(strategy, 'No tradable contracts in 25-50 DTE window')

            # Enrich and filter
            enriched = []
            for c in contracts_raw[:10]:   # limit API calls
                ec = self.chain.enrich_contract(c, underlying_price)
                if (ec.get('iv') and
                        ec.get('spread_pct', 999) <= self.MAX_SPREAD_PCT and
                        self.MIN_DELTA_LONG <= abs(ec.get('delta', 0)) <= self.MAX_DELTA_LONG):
                    enriched.append(ec)

            if not enriched:
                return self._empty(strategy, 'No liquid contracts with suitable delta')

            # Pick best contract (closest delta to 0.50)
            target_delta = 0.50
            best = min(enriched, key=lambda c: abs(abs(c.get('delta', 0)) - target_delta))

            # IV rank / percentile
            iv  = best.get('iv')
            ivr = self.iv_hist.iv_rank(underlying, iv) if iv else None
            ivp = self.iv_hist.iv_percentile(underlying, iv) if iv else None
            if iv:
                self.iv_hist.record(underlying, iv)

            # Risk / reward
            multiplier = 100
            if 'long' in strategy:
                max_risk   = best['mid'] * multiplier
                max_reward = (underlying_price * 0.10) * multiplier  # estimate 10% move
            elif 'spread' in strategy:
                max_risk   = best['mid'] * multiplier
                max_reward = max_risk * 2  # typical 1:2 risk/reward spread
            else:
                max_risk   = best['mid'] * multiplier
                max_reward = max_risk

            rationale = self._build_rationale(strategy, best, ivr, ivp, ai_score)

            return {
                'strategy':      strategy,
                'contract':      best,
                'contract_b':    None,
                'iv_rank':       ivr,
                'iv_percentile': ivp,
                'rationale':     rationale,
                'max_risk':      round(max_risk, 2),
                'max_reward':    round(max_reward, 2),
            }
        except Exception as e:
            log.debug('[OPTIONS] get_signal error: %s', e)
            return self._empty('none', str(e))

    def _select_strategy(self, score: float, regime: str) -> str:
        """
        Strategy selection based on score strength and IV regime.
        High IV favors premium selling (spreads); low IV favors buying.
        """
        if abs(score) < 3.0:
            return 'none'   # not strong enough for options
        if score >= 5.0:
            return 'long_call'
        if score >= 3.0:
            return 'bull_spread'
        if score <= -5.0:
            return 'long_put'
        if score <= -3.0:
            return 'bear_spread'
        if regime == 'ranging':
            return 'iron_condor'
        return 'none'

    def _build_rationale(self, strategy: str, contract: dict,
                         ivr: float | None, ivp: float | None,
                         score: float) -> str:
        parts = [f'{strategy.replace("_", " ").title()} — score {score:+.1f}']
        if ivr is not None:
            if ivr > 70:
                env = 'elevated IV (favor selling)'
            elif ivr < 30:
                env = 'low IV (favor buying)'
            else:
                env = 'normal IV'
            parts.append(f'IV rank {ivr:.0f} — {env}')
        if contract.get('delta'):
            parts.append(f'delta {contract["delta"]:.2f}, DTE {contract.get("dte", "?")}')
        if contract.get('theta'):
            parts.append(f'theta {contract["theta"]:.3f}/day')
        return ' | '.join(parts)

    def _empty(self, strategy: str, reason: str) -> dict:
        return {
            'strategy':      strategy,
            'contract':      None,
            'contract_b':    None,
            'iv_rank':       None,
            'iv_percentile': None,
            'rationale':     reason,
            'max_risk':      0,
            'max_reward':    0,
        }

    # ------------------------------------------------------------------
    # Put/Call Ratio (live sentiment from the options chain)
    # ------------------------------------------------------------------

    def _liquid_weight(self, contract: dict) -> float | None:
        """Return the PCR weight for a near-ATM contract if it is liquid.

        A contract is liquid when it has a valid bid AND ask. Weight is the
        open interest when present, otherwise 1.0 (count-based). Returns None
        for illiquid contracts so they are excluded from the ratio.
        """
        try:
            quote = self.chain.get_quote(contract.get('symbol', ''))
            if not quote:
                return None
            bid, ask = quote.get('bid', 0) or 0, quote.get('ask', 0) or 0
            if bid <= 0 or ask <= 0:
                return None   # not actively traded
            oi = contract.get('open_interest')
            try:
                oi = float(oi) if oi not in (None, '') else 0.0
            except (TypeError, ValueError):
                oi = 0.0
            return oi if oi > 0 else 1.0
        except Exception as e:
            log.debug('[OPTIONS_PCR] weight error for %s: %s',
                      contract.get('symbol'), e)
            return None

    def compute_pcr(self, underlying: str, underlying_price: float) -> dict:
        """Compute a live Put/Call Ratio from near-ATM chain liquidity.

        Approximates PCR using open interest when available, otherwise a count
        of liquid (valid bid/ask) near-ATM puts vs calls. Cached 30 min/symbol.

        Returns {'pcr', 'put_count', 'call_count', 'available'}.
        If the chain is unavailable returns {'available': False, 'pcr': 1.0}.
        """
        now = time.time()
        cached = self._pcr_cache.get(underlying)
        if cached and (now - cached[0]) < self.PCR_CACHE_TTL:
            return cached[1]

        try:
            if not underlying_price or underlying_price <= 0:
                result = {'available': False, 'pcr': 1.0,
                          'put_count': 0, 'call_count': 0}
                self._pcr_cache[underlying] = (now, result)
                return result

            calls = self.chain.get_contracts(
                underlying, dte_min=15, dte_max=60,
                opt_type='call', underlying_price=underlying_price)
            puts = self.chain.get_contracts(
                underlying, dte_min=15, dte_max=60,
                opt_type='put', underlying_price=underlying_price)

            if not calls and not puts:
                result = {'available': False, 'pcr': 1.0,
                          'put_count': 0, 'call_count': 0}
                self._pcr_cache[underlying] = (now, result)
                return result

            # Limit API calls — examine the contracts closest to the money.
            def _atm_sort(cs):
                return sorted(
                    cs, key=lambda c: abs(float(c.get('strike_price', 0) or 0)
                                          - underlying_price))[:12]

            call_weight = 0.0
            call_count  = 0
            for c in _atm_sort(calls):
                w = self._liquid_weight(c)
                if w is not None:
                    call_weight += w
                    call_count  += 1

            put_weight = 0.0
            put_count  = 0
            for p in _atm_sort(puts):
                w = self._liquid_weight(p)
                if w is not None:
                    put_weight += w
                    put_count  += 1

            if call_weight <= 0 and put_weight <= 0:
                # No liquid contracts on either side — no signal.
                result = {'available': False, 'pcr': 1.0,
                          'put_count': put_count, 'call_count': call_count}
                self._pcr_cache[underlying] = (now, result)
                return result

            # Avoid division by zero: a clean lean to one side.
            if call_weight <= 0:
                pcr = 2.0
            elif put_weight <= 0:
                pcr = 0.5
            else:
                pcr = put_weight / call_weight

            result = {
                'pcr':        round(pcr, 3),
                'put_count':  put_count,
                'call_count': call_count,
                'available':  True,
            }
            self._pcr_cache[underlying] = (now, result)
            return result
        except Exception as e:
            log.debug('[OPTIONS_PCR] compute_pcr error for %s: %s', underlying, e)
            result = {'available': False, 'pcr': 1.0,
                      'put_count': 0, 'call_count': 0}
            self._pcr_cache[underlying] = (now, result)
            return result

    def pcr_signal(self, underlying: str,
                   underlying_price: float | None = None) -> dict:
        """Translate the live Put/Call Ratio into a sentiment score.

        Contrarian-aware directional read:
          pcr < 0.7  → +1.0  'low put/call ratio — bullish options positioning'
          pcr > 1.3  → -1.0  'high put/call ratio — bearish options positioning'
          0.7–1.3    → small proportional score trending toward 0

        Only meaningful for equities/ETFs. Crypto/forex/futures and the case
        where the caller has no underlying price both return a neutral score.

        Returns {'score', 'description', 'pcr'}.
        """
        try:
            if _asset_class(underlying) != 'equity':
                return {'score': 0.0, 'pcr': 1.0,
                        'description': 'put/call ratio n/a (non-equity)'}

            if underlying_price is None or underlying_price <= 0:
                # Caller may not have a price — skip gracefully.
                return {'score': 0.0, 'pcr': 1.0,
                        'description': 'put/call ratio unavailable (no price)'}

            pcr_data = self.compute_pcr(underlying, underlying_price)
            if not pcr_data.get('available'):
                return {'score': 0.0, 'pcr': pcr_data.get('pcr', 1.0),
                        'description': 'put/call ratio unavailable'}

            pcr = pcr_data['pcr']

            if pcr < self.PCR_BULLISH_BELOW:
                return {'score': 1.0, 'pcr': pcr,
                        'description': 'low put/call ratio — '
                                       'bullish options positioning'}
            if pcr > self.PCR_BEARISH_ABOVE:
                return {'score': -1.0, 'pcr': pcr,
                        'description': 'high put/call ratio — '
                                       'bearish options positioning'}

            # Neutral band 0.7–1.3: linearly fade toward 0 around pcr = 1.0.
            mid = 1.0
            if pcr <= mid:
                # 0.7 → +1.0 boundary, 1.0 → 0.0
                span  = mid - self.PCR_BULLISH_BELOW           # 0.3
                score = (mid - pcr) / span if span > 0 else 0.0
            else:
                # 1.0 → 0.0, 1.3 → -1.0 boundary
                span  = self.PCR_BEARISH_ABOVE - mid           # 0.3
                score = -(pcr - mid) / span if span > 0 else 0.0
            score = round(max(-1.0, min(1.0, score)), 3)
            return {'score': score, 'pcr': pcr,
                    'description': f'neutral put/call ratio ({pcr:.2f})'}
        except Exception as e:
            log.debug('[OPTIONS_PCR] pcr_signal error for %s: %s', underlying, e)
            return {'score': 0.0, 'pcr': 1.0,
                    'description': 'put/call ratio error'}


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine: OptionsEngine | None = None


def init(db_path: str) -> OptionsEngine:
    """Initialise the module-level OptionsEngine singleton."""
    global _engine
    _engine = OptionsEngine(db_path)
    log.info('[OPTIONS] OptionsEngine initialised (db=%s)', db_path)
    return _engine


def get_engine() -> OptionsEngine | None:
    """Return the module-level singleton (None if not yet initialised)."""
    return _engine


def pcr_signal(underlying: str, underlying_price: float | None = None) -> dict:
    """Module-level live Put/Call Ratio sentiment signal.

    Returns {'score', 'description', 'pcr'}. Neutral if the engine is not
    initialised, the asset is non-equity, or no price/chain is available.
    """
    eng = _engine
    if eng is None:
        return {'score': 0.0, 'pcr': 1.0,
                'description': 'options engine not initialised'}
    return eng.pcr_signal(underlying, underlying_price)


def pcr_contrib(underlying: str, underlying_price: float | None = None) -> float:
    """Scalar score contribution from the live Put/Call Ratio signal."""
    try:
        return float(pcr_signal(underlying, underlying_price).get('score', 0.0))
    except Exception:
        return 0.0

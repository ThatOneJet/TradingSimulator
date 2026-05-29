"""
PortfolioAnalytics — portfolio-level risk and concentration analysis.

Computes:
  - Sector exposure weights
  - Portfolio beta vs SPY
  - Pairwise correlation clusters
  - Concentration risk score
  - Plain-English risk warnings

Usage:
    from portfolio_analytics import PortfolioAnalytics
    analytics = PortfolioAnalytics(candle_engine)
    result = analytics.compute(positions, prices)
    # result: {sector_weights, beta, correlation_clusters, concentration_risk, crypto_pct, warnings}
"""

import logging
import math

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sector map
# ---------------------------------------------------------------------------

SECTOR_MAP = {
    # Tech
    'AAPL': 'tech', 'MSFT': 'tech', 'GOOGL': 'tech', 'GOOG': 'tech',
    'META': 'tech', 'NVDA': 'tech', 'AMD': 'tech', 'INTC': 'tech',
    'TSLA': 'tech', 'NFLX': 'tech', 'AMZN': 'tech', 'CRM': 'tech',
    'ORCL': 'tech', 'ADBE': 'tech', 'QCOM': 'tech', 'TXN': 'tech',
    'AVGO': 'tech', 'MU': 'tech', 'AMAT': 'tech', 'LRCX': 'tech',
    # Finance
    'JPM': 'finance', 'BAC': 'finance', 'WFC': 'finance', 'GS': 'finance',
    'MS': 'finance', 'C': 'finance', 'BLK': 'finance', 'SCHW': 'finance',
    'AXP': 'finance', 'V': 'finance', 'MA': 'finance', 'PYPL': 'finance',
    # Healthcare
    'JNJ': 'healthcare', 'UNH': 'healthcare', 'PFE': 'healthcare',
    'ABBV': 'healthcare', 'MRK': 'healthcare', 'LLY': 'healthcare',
    'BMY': 'healthcare', 'GILD': 'healthcare', 'AMGN': 'healthcare',
    # Energy
    'XOM': 'energy', 'CVX': 'energy', 'COP': 'energy', 'SLB': 'energy',
    'EOG': 'energy', 'PXD': 'energy', 'OXY': 'energy',
    # Consumer
    'WMT': 'consumer', 'COST': 'consumer', 'TGT': 'consumer', 'HD': 'consumer',
    'MCD': 'consumer', 'SBUX': 'consumer', 'NKE': 'consumer', 'PG': 'consumer',
    # Industrial
    'CAT': 'industrial', 'DE': 'industrial', 'BA': 'industrial',
    'GE': 'industrial', 'HON': 'industrial', 'MMM': 'industrial',
    # Crypto
    'BTC-USD': 'crypto', 'ETH-USD': 'crypto', 'SOL-USD': 'crypto',
    'BNB-USD': 'crypto', 'XRP-USD': 'crypto', 'ADA-USD': 'crypto',
    'AVAX-USD': 'crypto', 'DOGE-USD': 'crypto', 'MATIC-USD': 'crypto',
    # Forex
    'EURUSD=X': 'forex', 'GBPUSD=X': 'forex', 'USDJPY=X': 'forex',
    'AUDUSD=X': 'forex', 'USDCAD=X': 'forex', 'USDCHF=X': 'forex',
    # ETFs / Indices
    'SPY': 'etf', 'QQQ': 'etf', 'IWM': 'etf', 'DIA': 'etf',
    'GLD': 'commodities', 'SLV': 'commodities', 'USO': 'commodities',
}


def get_sector(symbol: str) -> str:
    """Return sector for symbol, defaulting to 'other'."""
    return SECTOR_MAP.get(symbol.upper(), 'other')


# ---------------------------------------------------------------------------
# Pure-stdlib helpers
# ---------------------------------------------------------------------------

def _mean(xs: list) -> float:
    return sum(xs) / len(xs)


def _std(xs: list) -> float:
    if len(xs) < 2:
        return 0.0
    mu = _mean(xs)
    var = sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)
    return math.sqrt(var)


def _pearson(a: list, b: list) -> float:
    """Pearson correlation between two equal-length lists. Returns 0 on failure."""
    n = min(len(a), len(b))
    if n < 2:
        return 0.0
    a, b = a[-n:], b[-n:]
    mu_a, mu_b = _mean(a), _mean(b)
    num = sum((a[i] - mu_a) * (b[i] - mu_b) for i in range(n))
    den_a = math.sqrt(sum((x - mu_a) ** 2 for x in a))
    den_b = math.sqrt(sum((x - mu_b) ** 2 for x in b))
    if den_a == 0 or den_b == 0:
        return 0.0
    return num / (den_a * den_b)


def _compute_beta(sym_closes: list, spy_closes: list) -> float:
    """Beta of sym relative to SPY using returns."""
    n = min(len(sym_closes), len(spy_closes))
    if n < 3:
        return 1.0
    sym_ret = [sym_closes[i] / sym_closes[i - 1] - 1 for i in range(1, n)]
    spy_ret = [spy_closes[i] / spy_closes[i - 1] - 1 for i in range(1, n)]
    corr = _pearson(sym_ret, spy_ret)
    std_sym = _std(sym_ret)
    std_spy = _std(spy_ret)
    if std_spy == 0:
        return 1.0
    return corr * (std_sym / std_spy)


# ---------------------------------------------------------------------------
# Union-Find for cluster merging
# ---------------------------------------------------------------------------

def _find(parent: dict, x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def _union(parent: dict, x, y):
    rx, ry = _find(parent, x), _find(parent, y)
    if rx != ry:
        parent[ry] = rx


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class PortfolioAnalytics:

    def __init__(self, candle_engine=None):
        self._candle_engine = candle_engine

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute(self, positions: list, prices: dict) -> dict:
        """
        positions: list of {'symbol': str, 'shares': float, 'current_price': float, ...}
        prices: {symbol: current_price}

        Returns:
        {
            'sector_weights': dict,          # {sector: weight_pct}
            'beta': float,                   # portfolio beta vs SPY
            'correlation_clusters': list,    # [{'symbols': [str,...], 'avg_correlation': float}]
            'concentration_risk': float,     # highest single-sector weight (0-1)
            'crypto_pct': float,
            'total_value': float,
            'warnings': list[str],
        }
        """
        if not positions:
            return {
                'sector_weights': {}, 'beta': 1.0, 'correlation_clusters': [],
                'concentration_risk': 0.0, 'crypto_pct': 0.0,
                'total_value': 0.0, 'warnings': [],
            }

        # Resolve current price for each position
        mv = {}  # symbol -> market_value
        for pos in positions:
            sym = pos['symbol']
            price = prices.get(sym) or pos.get('current_price') or 0.0
            mv[sym] = abs(pos.get('shares', 0.0)) * price

        total_value = sum(mv.values())
        if total_value == 0:
            return {
                'sector_weights': {}, 'beta': 1.0, 'correlation_clusters': [],
                'concentration_risk': 0.0, 'crypto_pct': 0.0,
                'total_value': 0.0, 'warnings': [],
            }

        # -- Sector weights --------------------------------------------------
        sector_totals: dict = {}
        for sym, val in mv.items():
            sector = get_sector(sym)
            sector_totals[sector] = sector_totals.get(sector, 0.0) + val

        sector_weights = {s: round(v / total_value, 3) for s, v in sector_totals.items()}
        concentration_risk = max(sector_weights.values(), default=0.0)
        crypto_pct = sector_weights.get('crypto', 0.0)

        # -- Beta ------------------------------------------------------------
        beta = self._portfolio_beta(mv, total_value)

        # -- Correlation clusters --------------------------------------------
        clusters = self._correlation_clusters(list(mv.keys()))

        # -- Warnings --------------------------------------------------------
        warnings = self._generate_warnings(
            sector_weights=sector_weights,
            crypto_pct=crypto_pct,
            clusters=clusters,
            mv=mv,
            total_value=total_value,
            beta=beta,
        )

        return {
            'sector_weights': sector_weights,
            'beta': round(beta, 3),
            'correlation_clusters': clusters,
            'concentration_risk': round(concentration_risk, 3),
            'crypto_pct': round(crypto_pct, 3),
            'total_value': round(total_value, 2),
            'warnings': warnings,
        }

    def check_new_position(
        self,
        new_symbol: str,
        new_value: float,
        existing_positions: list,
        prices: dict,
    ) -> list:
        """
        Simulate adding new_symbol at new_value to existing_positions.
        Returns list of warnings that would be triggered; empty list = safe to add.
        """
        simulated = list(existing_positions) + [{
            'symbol': new_symbol,
            'shares': 1.0,
            'current_price': new_value,
        }]
        simulated_prices = dict(prices)
        simulated_prices[new_symbol] = new_value
        result = self.compute(simulated, simulated_prices)
        return result.get('warnings', [])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_closes(self, symbol: str, n: int = 20) -> list:
        if self._candle_engine is None:
            return []
        try:
            closes = self._candle_engine.get_recent_closes(symbol, '1m', n)
            return closes if closes else []
        except Exception as exc:
            log.debug("get_recent_closes(%s) failed: %s", symbol, exc)
            return []

    def _portfolio_beta(self, mv: dict, total_value: float) -> float:
        if self._candle_engine is None:
            return 1.0
        spy_closes = self._get_closes('SPY', 21)
        if len(spy_closes) < 3:
            return 1.0

        weighted_beta = 0.0
        total_weight = 0.0
        for sym, val in mv.items():
            if sym == 'SPY':
                sym_beta = 1.0
            else:
                sym_closes = self._get_closes(sym, 21)
                if len(sym_closes) < 3:
                    sym_beta = 1.0
                else:
                    sym_beta = _compute_beta(sym_closes, spy_closes)
            weight = val / total_value
            weighted_beta += sym_beta * weight
            total_weight += weight

        if total_weight == 0:
            return 1.0
        return weighted_beta / total_weight

    def _correlation_clusters(self, symbols: list) -> list:
        if len(symbols) < 2 or self._candle_engine is None:
            return []

        # Fetch closes for all symbols
        closes_map = {}
        for sym in symbols:
            c = self._get_closes(sym, 20)
            if len(c) >= 3:
                closes_map[sym] = c

        valid_syms = list(closes_map.keys())
        if len(valid_syms) < 2:
            return []

        # Compute pairwise correlations
        pair_corr: dict = {}
        for i in range(len(valid_syms)):
            for j in range(i + 1, len(valid_syms)):
                a, b = valid_syms[i], valid_syms[j]
                r = _pearson(closes_map[a], closes_map[b])
                pair_corr[(a, b)] = r

        # Union-Find clustering on r > 0.65
        parent = {s: s for s in valid_syms}
        for (a, b), r in pair_corr.items():
            if r > 0.65:
                _union(parent, a, b)

        # Group by root
        groups: dict = {}
        for sym in valid_syms:
            root = _find(parent, sym)
            groups.setdefault(root, []).append(sym)

        # Build cluster list
        clusters = []
        for members in groups.values():
            if len(members) < 2:
                continue
            # Average correlation across all pairs within cluster
            corrs = []
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    a, b = members[i], members[j]
                    key = (a, b) if (a, b) in pair_corr else (b, a)
                    if key in pair_corr:
                        corrs.append(pair_corr[key])
            avg_r = round(_mean(corrs), 3) if corrs else 0.0
            clusters.append({'symbols': sorted(members), 'avg_correlation': avg_r})

        # Sort by avg_correlation descending
        clusters.sort(key=lambda c: c['avg_correlation'], reverse=True)
        return clusters

    def _generate_warnings(
        self,
        sector_weights: dict,
        crypto_pct: float,
        clusters: list,
        mv: dict,
        total_value: float,
        beta: float,
    ) -> list:
        warnings = []

        # 1. Any sector > 35%
        for sector, weight in sector_weights.items():
            if weight > 0.35:
                warnings.append(
                    f"{sector.capitalize()} overweight: {round(weight * 100)}% of portfolio"
                )

        # 2. Crypto > 30%
        if crypto_pct > 0.30:
            warnings.append(
                f"Crypto concentration: {round(crypto_pct * 100)}% of portfolio"
            )

        # 3. Correlated cluster avg r > 0.75
        for cluster in clusters:
            if cluster['avg_correlation'] > 0.75:
                sym_str = ' + '.join(cluster['symbols'])
                r_val = cluster['avg_correlation']
                warnings.append(
                    f"Correlated cluster: {sym_str} (r={r_val}) — reduce one"
                )

        # 4. Single position > 20% of total
        for sym, val in mv.items():
            pct = val / total_value
            if pct > 0.20:
                warnings.append(
                    f"{sym} position is {round(pct * 100)}% of portfolio — oversized"
                )

        # 5. High beta
        if beta > 1.5:
            warnings.append(
                f"High beta portfolio ({round(beta, 1)}x) — elevated market sensitivity"
            )

        # 6. Forex > 25%
        forex_pct = sector_weights.get('forex', 0.0)
        if forex_pct > 0.25:
            warnings.append(
                f"Forex concentration: {round(forex_pct * 100)}% of portfolio"
            )

        return warnings


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

def create_analytics(candle_engine=None) -> PortfolioAnalytics:
    return PortfolioAnalytics(candle_engine)

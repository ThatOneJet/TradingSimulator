"""
SectorRotation — 5-day sector ETF momentum ranking. Stocks in leading sectors
get a buy bias, lagging sectors a penalty. Detects active money rotation.

Bulk-downloads the eleven sector SPDR ETFs, computes each one's trailing 5-day
return, and ranks the sectors best-to-worst. An individual equity inherits its
sector's rank: top-3 sectors get a buy bias, bottom-3 a penalty. Non-equities
(crypto / forex / futures) are neutral — they don't belong to a stock sector.
"""

import logging
import threading
import time

log = logging.getLogger(__name__)

# Each sector's representative SPDR ETF
SECTOR_ETF = {
    'tech':       'XLK',
    'financials': 'XLF',
    'energy':     'XLE',
    'healthcare': 'XLV',
    'industrials':'XLI',
    'consumer':   'XLY',
    'staples':    'XLP',
    'materials':  'XLB',
    'realestate': 'XLRE',
    'utilities':  'XLU',
}

# Compact stock -> sector-key map for the trading universe (~70 names)
STOCK_SECTOR = {
    # Tech
    'AAPL':'tech','MSFT':'tech','NVDA':'tech','GOOGL':'tech','GOOG':'tech',
    'META':'tech','TSLA':'tech','AVGO':'tech','ADBE':'tech','CRM':'tech',
    'AMD':'tech','INTC':'tech','QCOM':'tech','TXN':'tech','ORCL':'tech',
    'IBM':'tech','INTU':'tech','NOW':'tech','PLTR':'tech','CRWD':'tech',
    'PANW':'tech','MU':'tech','AMAT':'tech','LRCX':'tech','SMCI':'tech',
    'ARM':'tech','ANET':'tech','MRVL':'tech','ASML':'tech',
    # Financials
    'JPM':'financials','BAC':'financials','GS':'financials','MS':'financials',
    'WFC':'financials','C':'financials','V':'financials','MA':'financials',
    'AXP':'financials','BLK':'financials','SCHW':'financials','SPGI':'financials',
    'BX':'financials','KKR':'financials','HOOD':'financials',
    # Energy
    'XOM':'energy','CVX':'energy','COP':'energy','SLB':'energy','OXY':'energy',
    'EOG':'energy','PSX':'energy','MPC':'energy','VLO':'energy',
    # Healthcare
    'UNH':'healthcare','LLY':'healthcare','JNJ':'healthcare','PFE':'healthcare',
    'MRK':'healthcare','ABBV':'healthcare','TMO':'healthcare','DHR':'healthcare',
    'AMGN':'healthcare','GILD':'healthcare','ISRG':'healthcare','CVS':'healthcare',
    # Industrials
    'CAT':'industrials','DE':'industrials','HON':'industrials','BA':'industrials',
    'GE':'industrials','UPS':'industrials','FDX':'industrials','RTX':'industrials',
    'LMT':'industrials','NOC':'industrials',
    # Consumer (discretionary)
    'WMT':'consumer','HD':'consumer','MCD':'consumer','NKE':'consumer',
    'SBUX':'consumer','LOW':'consumer','TGT':'consumer','BKNG':'consumer',
    'ABNB':'consumer','CMG':'consumer',
    # Staples
    'COST':'staples','PG':'staples','KO':'staples','PEP':'staples',
    'PM':'staples','MO':'staples','MDLZ':'staples',
    # Materials
    'LIN':'materials','APD':'materials','NEM':'materials','FCX':'materials','NUE':'materials',
    # Real estate
    'PLD':'realestate','AMT':'realestate','EQIX':'realestate','O':'realestate','SPG':'realestate',
    # Utilities
    'NEE':'utilities','DUK':'utilities','SO':'utilities','D':'utilities',
}

REFRESH_INTERVAL = 600   # 10 minutes


class SectorRotationEngine:
    """Ranks sector ETFs by trailing 5-day return; lazy-refreshes when stale."""

    def __init__(self):
        self._lock = threading.Lock()
        self._rankings: dict = {}   # sector -> {'ret_5d', 'rank'}
        self._ts = 0.0

    # ------------------------------------------------------------------
    # Rankings
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        """Bulk-download sector ETFs and rebuild the ranking table."""
        try:
            import yfinance as yf

            tickers = list(SECTOR_ETF.values())
            data = yf.download(tickers, period='7d', progress=False,
                               auto_adjust=True, threads=True)
            if data is None or len(data) == 0:
                return

            # Extract Close columns robustly across yfinance frame shapes
            try:
                closes = data['Close']
            except Exception:
                closes = data

            rets = {}  # sector -> 5d % return
            for sector, etf in SECTOR_ETF.items():
                try:
                    if hasattr(closes, 'columns') and etf in closes.columns:
                        series = closes[etf].dropna()
                    elif hasattr(closes, 'dropna'):
                        series = closes.dropna()
                    else:
                        continue
                    vals = [float(x) for x in series.tolist()]
                    if len(vals) < 2:
                        continue
                    first, last = vals[0], vals[-1]
                    if first <= 0:
                        continue
                    rets[sector] = (last - first) / first * 100.0
                except Exception as e:
                    log.debug('[SECTOR] return calc failed for %s: %s', etf, e)
                    continue

            if not rets:
                return

            # Rank best (rank 1) to worst
            ordered = sorted(rets.items(), key=lambda kv: kv[1], reverse=True)
            rankings = {}
            for idx, (sector, ret) in enumerate(ordered):
                rankings[sector] = {'ret_5d': round(ret, 3), 'rank': idx + 1}

            with self._lock:
                self._rankings = rankings
                self._ts = time.time()

            log.info('[SECTOR] refreshed — leaders: %s',
                     ', '.join(s for s, _ in ordered[:3]))

        except Exception as e:
            log.debug('[SECTOR] refresh error: %s', e)

    def get_rankings(self) -> dict:
        """Return {sector: {'ret_5d', 'rank'}}, lazy-refreshing if stale."""
        try:
            with self._lock:
                fresh = self._rankings and (time.time() - self._ts) < REFRESH_INTERVAL
                snapshot = dict(self._rankings)
            if fresh:
                return snapshot
            self._refresh()
            with self._lock:
                return dict(self._rankings)
        except Exception as e:
            log.debug('[SECTOR] get_rankings error: %s', e)
            return {}

    # ------------------------------------------------------------------
    # Signal
    # ------------------------------------------------------------------

    def get_signal(self, symbol: str) -> dict:
        """
        Map symbol → sector → ranking and emit a rotation bias.

        Returns {score, description, sector, sector_rank, sector_ret_5d}.
        Non-equity symbols are neutral.
        """
        try:
            sym = (symbol or '').upper()

            # Crypto / forex / futures are not stock sectors → neutral
            if sym.endswith('-USD') or sym.endswith('=X') or sym.endswith('=F'):
                return self._neutral('not an equity — no sector')

            sector = STOCK_SECTOR.get(sym)
            if not sector:
                return self._neutral('unknown sector')

            rankings = self.get_rankings()
            info = rankings.get(sector)
            if not info:
                return self._neutral('sector data unavailable', sector=sector)

            rank = info['rank']
            ret_5d = info['ret_5d']
            total = len(rankings)

            if rank <= 3:
                score, desc = 0.5, 'sector leading rotation'
            elif rank > total - 3:
                score, desc = -0.5, 'sector lagging'
            else:
                score, desc = 0.0, 'sector mid-pack'

            return {
                'score':         round(float(score), 3),
                'description':   desc,
                'sector':        sector,
                'sector_rank':   rank,
                'sector_ret_5d': ret_5d,
            }

        except Exception as e:
            log.debug('[SECTOR] get_signal(%s) error: %s', symbol, e)
            return self._neutral('error')

    @staticmethod
    def _neutral(desc: str, sector=None) -> dict:
        return {
            'score':         0.0,
            'description':   desc,
            'sector':        sector,
            'sector_rank':   None,
            'sector_ret_5d': None,
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine: 'SectorRotationEngine | None' = None


def get_engine() -> SectorRotationEngine:
    """Return the lazily-created module-level engine singleton."""
    global _engine
    if _engine is None:
        _engine = SectorRotationEngine()
    return _engine


def get_signal(symbol: str) -> dict:
    """Sector-rotation signal dict for ``symbol`` (never raises)."""
    try:
        return get_engine().get_signal(symbol)
    except Exception as e:
        log.debug('[SECTOR] module get_signal error: %s', e)
        return {
            'score': 0.0, 'description': 'error', 'sector': None,
            'sector_rank': None, 'sector_ret_5d': None,
        }


def score_contrib(symbol: str) -> float:
    """Just the float score for ``symbol`` (0.0 on failure)."""
    try:
        return float(get_signal(symbol).get('score', 0.0))
    except Exception:
        return 0.0

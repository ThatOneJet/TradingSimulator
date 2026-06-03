"""
CircuitBreakers — hard safety rules for AI trading protection.

Three independent breakers:
1. Consecutive loss breaker: pause strategy after N consecutive losses
2. Drawdown halt: reduce sizing at 8% DD, full pause at 15% DD
3. Strategy disabling: disable specific strategy+regime combos below 40% win rate

All breakers are stateful and persist across scan cycles.
Query breakers before opening any new position.
"""

import threading
import logging
import time
import datetime
from collections import defaultdict

log = logging.getLogger(__name__)

# BreakState constants
BREAK_NONE     = 'none'       # no breaker active
BREAK_REDUCED  = 'reduced'    # reduced sizing (50% of normal)
BREAK_PAUSED   = 'paused'     # no new positions
BREAK_DISABLED = 'disabled'   # specific strategy disabled


class CircuitBreakers:
    CONSEC_LOSS_LIMIT    = 5    # consecutive losses before pause
    CONSEC_PAUSE_MINUTES = 30   # minutes to pause after consecutive losses
                                # (fast paper sandbox — was 24h, far too long)
    DD_REDUCED_PCT     = 0.08   # 8% drawdown → reduced mode
    DD_HALT_PCT        = 0.15   # 15% drawdown → full halt
    MIN_WIN_RATE       = 0.40   # below this → disable strategy+regime combo
    MIN_TRADES_DISABLE = 20     # need this many trades to disable

    def __init__(self, db_path):
        self.db_path   = db_path
        self._lock     = threading.Lock()
        # In-memory state
        self._consec_losses:   dict = {}   # {pid: consecutive_loss_count}
        self._pause_until:     dict = {}   # {pid: unix_ts_until}
        self._disabled_combos: set  = set()  # {'strategy:regime'}
        self._hwm:             dict = {}   # {pid: high_water_mark_equity}

    def check(self, pid, equity, strategy='', regime='') -> dict:
        """
        Main check — call before opening any new position.

        Returns:
        {
            'allowed': bool,
            'state':   str,       # BREAK_NONE / BREAK_REDUCED / BREAK_PAUSED / BREAK_DISABLED
            'size_mult': float,   # 1.0 (normal), 0.5 (reduced), 0.0 (paused/disabled)
            'reason':  str,
        }
        """
        try:
            with self._lock:
                # 1. Consecutive loss pause
                if pid in self._pause_until:
                    if time.time() < self._pause_until[pid]:
                        remaining = int((self._pause_until[pid] - time.time()) / 60)
                        return {
                            'allowed': False,
                            'state': BREAK_PAUSED,
                            'size_mult': 0.0,
                            'reason': f'consecutive loss pause — {remaining}m remaining',
                        }
                    else:
                        del self._pause_until[pid]
                        self._consec_losses[pid] = 0

                # 2. Drawdown halt
                hwm = self._hwm.get(pid, equity)
                self._hwm[pid] = max(hwm, equity)
                drawdown = (
                    (self._hwm[pid] - equity) / self._hwm[pid]
                    if self._hwm[pid] > 0
                    else 0
                )

                if drawdown >= self.DD_HALT_PCT:
                    return {
                        'allowed': False,
                        'state': BREAK_PAUSED,
                        'size_mult': 0.0,
                        'reason': (
                            f'drawdown halt: {drawdown:.1%} from peak '
                            f'(limit {self.DD_HALT_PCT:.0%})'
                        ),
                    }

                if drawdown >= self.DD_REDUCED_PCT:
                    # Still allowed but at 50% size
                    dd_result = {
                        'allowed': True,
                        'state': BREAK_REDUCED,
                        'size_mult': 0.5,
                        'reason': f'drawdown reduced: {drawdown:.1%} from peak',
                    }
                else:
                    dd_result = {
                        'allowed': True,
                        'state': BREAK_NONE,
                        'size_mult': 1.0,
                        'reason': '',
                    }

                # 3. Disabled strategy+regime combo
                combo_key = f'{strategy}:{regime}'
                if combo_key in self._disabled_combos:
                    return {
                        'allowed': False,
                        'state': BREAK_DISABLED,
                        'size_mult': 0.0,
                        'reason': f'{strategy}/{regime} disabled: win rate too low',
                    }

                return dd_result

        except Exception as e:
            log.exception('[CIRCUIT] check error pid=%s: %s', pid, e)
            return {'allowed': True, 'state': BREAK_NONE, 'size_mult': 1.0, 'reason': ''}

    def record_trade_result(self, pid, profitable, strategy='', regime=''):
        """Call after each trade closes. Updates consecutive loss count."""
        try:
            with self._lock:
                if profitable:
                    self._consec_losses[pid] = 0
                else:
                    count = self._consec_losses.get(pid, 0) + 1
                    self._consec_losses[pid] = count
                    if count >= self.CONSEC_LOSS_LIMIT:
                        self._pause_until[pid] = (
                            time.time() + self.CONSEC_PAUSE_MINUTES * 60
                        )
                        self._consec_losses[pid] = 0
                        log.warning(
                            '[CIRCUIT] pid=%d: %d consecutive losses — pausing %dm',
                            pid, count, self.CONSEC_PAUSE_MINUTES,
                        )
        except Exception as e:
            log.exception('[CIRCUIT] record_trade_result error pid=%s: %s', pid, e)

    def evaluate_strategies(self, pid: int = 1, days: int = 30):
        """
        Periodically call to update disabled_combos set.

        Reads ai_log to check win rates per strategy+regime combo.
        If any combo has < MIN_WIN_RATE over MIN_TRADES_DISABLE trades,
        adds to disabled set.
        """
        try:
            import sqlite3

            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cutoff = (
                datetime.datetime.utcnow() - datetime.timedelta(days=days)
            ).isoformat()

            # Fetch all buy/short actions in the window for this portfolio
            rows = conn.execute(
                '''
                SELECT action, market_state,
                       COALESCE(strategy, 'default') AS strategy
                FROM ai_log
                WHERE portfolio_id=? AND created_at > ?
                  AND action IN ('BUY','SHORT')
                ''',
                (pid, cutoff),
            ).fetchall()
            conn.close()

            # Group by strategy+market_state, count wins and total trades
            # We approximate "win" as a BUY in an uptrend or SHORT in a downtrend
            combo_totals: dict = defaultdict(int)
            combo_wins:   dict = defaultdict(int)

            for row in rows:
                strategy   = row['strategy'] or 'default'
                regime     = row['market_state'] or 'unknown'
                action     = row['action']
                combo_key  = f'{strategy}:{regime}'
                combo_totals[combo_key] += 1

                # Heuristic win: BUY in bull/uptrend, SHORT in bear/downtrend
                bullish_regime = any(
                    tag in regime.lower() for tag in ('bull', 'up', 'strong')
                )
                bearish_regime = any(
                    tag in regime.lower() for tag in ('bear', 'down', 'weak')
                )
                if (action == 'BUY' and bullish_regime) or (
                    action == 'SHORT' and bearish_regime
                ):
                    combo_wins[combo_key] += 1

            new_disabled: set = set()
            for combo_key, total in combo_totals.items():
                if total < self.MIN_TRADES_DISABLE:
                    continue
                win_rate = combo_wins.get(combo_key, 0) / total
                if win_rate < self.MIN_WIN_RATE:
                    new_disabled.add(combo_key)
                    log.warning(
                        '[CIRCUIT] disabling combo %s: win_rate=%.1f%% over %d trades',
                        combo_key, win_rate * 100, total,
                    )

            with self._lock:
                self._disabled_combos = new_disabled

            log.info(
                '[CIRCUIT] evaluate_strategies pid=%d: %d combos disabled',
                pid, len(new_disabled),
            )

        except Exception as e:
            log.debug('[CIRCUIT] evaluate_strategies error: %s', e)

    def status(self, pid: int) -> dict:
        """Returns current state of all breakers for a portfolio."""
        try:
            with self._lock:
                paused = pid in self._pause_until and time.time() < self._pause_until.get(pid, 0)
                pause_remaining_m = (
                    int((self._pause_until[pid] - time.time()) / 60)
                    if paused
                    else 0
                )
                hwm       = self._hwm.get(pid, 0)
                consec    = self._consec_losses.get(pid, 0)
                disabled  = list(self._disabled_combos)

            return {
                'pid': pid,
                'consecutive_losses': consec,
                'paused': paused,
                'pause_remaining_minutes': pause_remaining_m,
                'high_water_mark': hwm,
                'disabled_combos': disabled,
            }
        except Exception as e:
            log.exception('[CIRCUIT] status error pid=%s: %s', pid, e)
            return {'pid': pid, 'error': str(e)}

    def reset_pause(self, pid: int):
        """Manually clear a consecutive-loss pause (e.g. after manual review)."""
        try:
            with self._lock:
                self._pause_until.pop(pid, None)
                self._consec_losses[pid] = 0
            log.info('[CIRCUIT] pause reset for pid=%d', pid)
        except Exception as e:
            log.exception('[CIRCUIT] reset_pause error pid=%s: %s', pid, e)

    def reset_hwm(self, pid: int, equity: float):
        """Reset high-water mark to current equity (e.g. after capital injection)."""
        try:
            with self._lock:
                self._hwm[pid] = equity
            log.info('[CIRCUIT] HWM reset for pid=%d to %.2f', pid, equity)
        except Exception as e:
            log.exception('[CIRCUIT] reset_hwm error pid=%s: %s', pid, e)


# ---------------------------------------------------------------------------
# Module-level singleton helpers
# ---------------------------------------------------------------------------

_breakers: 'CircuitBreakers | None' = None


def init(db_path) -> CircuitBreakers:
    """Initialise the module singleton. Call once at app startup."""
    global _breakers
    _breakers = CircuitBreakers(db_path)
    log.info('[CIRCUIT] CircuitBreakers initialised (db=%s)', db_path)
    return _breakers


def get() -> 'CircuitBreakers | None':
    """Return the module singleton, or None if not yet initialised."""
    return _breakers


def check(pid, equity, strategy='', regime='') -> dict:
    """Module-level check — safe to call even before init()."""
    if _breakers is None:
        return {'allowed': True, 'state': BREAK_NONE, 'size_mult': 1.0, 'reason': ''}
    return _breakers.check(pid, equity, strategy, regime)


def record_result(pid, profitable, strategy='', regime=''):
    """Module-level record — safe to call even before init()."""
    if _breakers:
        _breakers.record_trade_result(pid, profitable, strategy, regime)

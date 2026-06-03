"""
PerformanceEngine — self-analysis and journaling for AI trading strategy.

Computes:
  - Win rates and P&L broken down by market regime
  - Win rates broken down by strategy module
  - Signal attribution: which indicators drove profitable vs losing trades
  - Daily equity curve from trade history
  - Strategy decay detection: rolling win rate vs all-time win rate
  - Execution quality: score-at-entry vs actual outcome
"""

import sqlite3
import logging
import json
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

log = logging.getLogger(__name__)


def _migrate_db(conn):
    """Add market_state and strategy columns to ai_log if not present."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(ai_log)")}
    if 'market_state' not in cols:
        conn.execute("ALTER TABLE ai_log ADD COLUMN market_state TEXT")
    if 'strategy' not in cols:
        conn.execute("ALTER TABLE ai_log ADD COLUMN strategy TEXT")


class PerformanceEngine:

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def _get_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _regime_stats(self, rows):
        """Aggregate a list of (realized_pl, regime) tuples into a stats dict."""
        buckets = defaultdict(lambda: {'trades': 0, 'wins': 0, 'total_pl': 0.0})
        for pl, key in rows:
            pl = pl or 0.0
            buckets[key]['trades'] += 1
            if pl > 0:
                buckets[key]['wins'] += 1
            buckets[key]['total_pl'] += pl

        result = {}
        for key, s in buckets.items():
            t = s['trades']
            result[key] = {
                'trades': t,
                'wins': s['wins'],
                'win_rate': round(s['wins'] / t, 4) if t else 0.0,
                'avg_pl': round(s['total_pl'] / t, 2) if t else 0.0,
                'total_pl': round(s['total_pl'], 2),
            }
        return result

    def _fetch_closed_trades(self, conn, pid: int, days: int):
        """
        Return list of (realized_pl, ai_log_row) for each closed sim_trade
        matched to its opening ai_log entry.
        """
        since = (datetime.utcnow() - timedelta(days=days)).isoformat()
        trades = conn.execute(
            """
            SELECT id, symbol, side, realized_pl, created_at
            FROM sim_trades
            WHERE side IN ('sell', 'cover')
              AND status = 'filled'
              AND realized_pl IS NOT NULL
              AND created_at >= ?
            ORDER BY created_at
            """,
            (since,),
        ).fetchall()

        pairs = []
        for trade in trades:
            open_action = 'BUY' if trade['side'] == 'sell' else 'SHORT'
            log_row = conn.execute(
                """
                SELECT score, reason, market_state, strategy, action, created_at
                FROM ai_log
                WHERE portfolio_id = ?
                  AND symbol = ?
                  AND action = ?
                  AND created_at <= ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (pid, trade['symbol'], open_action, trade['created_at']),
            ).fetchone()
            pairs.append((trade['realized_pl'] or 0.0, log_row))
        return pairs

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def by_regime(self, pid: int, days: int = 90) -> dict:
        try:
            with self._get_db() as conn:
                _migrate_db(conn)
                pairs = self._fetch_closed_trades(conn, pid, days)

            rows = []
            all_pl, all_wins, total = 0.0, 0, 0
            for pl, log_row in pairs:
                regime = (log_row['market_state'] if log_row and log_row['market_state'] else 'neutral')
                action = (log_row['action'] if log_row and log_row['action'] else '') if log_row else ''
                direction = 'short' if action == 'SHORT' else 'long'
                # Key includes direction: e.g. "trending_down | short"
                key = f"{regime} | {direction}"
                rows.append((pl, key))
                all_pl += pl
                all_wins += 1 if pl > 0 else 0
                total += 1

            result = self._regime_stats(rows)
            result['_total'] = {
                'trades': total,
                'wins': all_wins,
                'win_rate': round(all_wins / total, 4) if total else 0.0,
                'avg_pl': round(all_pl / total, 2) if total else 0.0,
                'total_pl': round(all_pl, 2),
            }
            return result
        except Exception:
            log.exception("by_regime failed")
            return {}

    def by_score_bucket(self, pid: int, days: int = 90) -> dict:
        def bucket_for(score):
            if score is None:
                return 'unknown'
            score = float(score)
            if score >= 8.0:
                return '8.0+'
            if score >= 6.0:
                return '6.0-8.0'
            if score >= 4.0:
                return '4.0-6.0'
            if score >= 2.5:
                return '2.5-4.0'
            return '<2.5'

        try:
            with self._get_db() as conn:
                _migrate_db(conn)
                pairs = self._fetch_closed_trades(conn, pid, days)

            rows = []
            for pl, log_row in pairs:
                score = log_row['score'] if log_row else None
                rows.append((pl, bucket_for(score)))

            return self._regime_stats(rows)
        except Exception:
            log.exception("by_score_bucket failed")
            return {}

    def signal_attribution(self, pid: int, days: int = 90) -> dict:
        keywords = ['RSI', 'MACD', 'oversold', 'overbought', 'breakout',
                    'accumulation', 'trending', 'volume', 'BB', 'VWAP', 'panic']
        try:
            with self._get_db() as conn:
                _migrate_db(conn)
                pairs = self._fetch_closed_trades(conn, pid, days)

            buckets = defaultdict(lambda: {'trades': 0, 'wins': 0, 'total_pl': 0.0})
            for pl, log_row in pairs:
                reason = (log_row['reason'] if log_row and log_row['reason'] else '')
                for kw in keywords:
                    if kw.lower() in reason.lower():
                        buckets[kw]['trades'] += 1
                        if pl > 0:
                            buckets[kw]['wins'] += 1
                        buckets[kw]['total_pl'] += pl

            result = {}
            for kw, s in buckets.items():
                t = s['trades']
                result[kw] = {
                    'trades': t,
                    'total_pl': round(s['total_pl'], 2),
                    'avg_pl': round(s['total_pl'] / t, 2) if t else 0.0,
                    'win_rate': round(s['wins'] / t, 4) if t else 0.0,
                }
            return result
        except Exception:
            log.exception("signal_attribution failed")
            return {}

    def equity_curve(self, pid: int, days: int = 30) -> list:
        try:
            with self._get_db() as conn:
                state = conn.execute(
                    "SELECT initial_cash FROM sim_state ORDER BY id DESC LIMIT 1"
                ).fetchone()
                initial_cash = float(state['initial_cash']) if state else 100_000.0

                since = (datetime.utcnow() - timedelta(days=days)).isoformat()
                trades = conn.execute(
                    """
                    SELECT DATE(created_at) AS day, SUM(COALESCE(realized_pl, 0)) AS day_pl
                    FROM sim_trades
                    WHERE status = 'filled'
                      AND created_at >= ?
                    GROUP BY day
                    ORDER BY day
                    """,
                    (since,),
                ).fetchall()

            # Build day-by-day map
            pl_by_day = {row['day']: float(row['day_pl']) for row in trades}

            start_date = datetime.utcnow().date() - timedelta(days=days - 1)
            curve = []
            running_equity = initial_cash
            # Add all realized PL before our window as baseline
            for i in range(days):
                day = start_date + timedelta(days=i)
                day_str = day.isoformat()
                daily_pl = pl_by_day.get(day_str, 0.0)
                running_equity += daily_pl
                curve.append({
                    'date': day_str,
                    'equity': round(running_equity, 2),
                    'daily_pl': round(daily_pl, 2),
                })
            return curve
        except Exception:
            log.exception("equity_curve failed")
            return []

    def decay_check(self, pid: int, short_window: int = 30, long_window: int = 90) -> dict:
        try:
            with self._get_db() as conn:
                _migrate_db(conn)

                def _window_stats(days):
                    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
                    rows = conn.execute(
                        """
                        SELECT realized_pl
                        FROM sim_trades
                        WHERE side IN ('sell', 'cover')
                          AND status = 'filled'
                          AND realized_pl IS NOT NULL
                          AND created_at >= ?
                        """,
                        (since,),
                    ).fetchall()
                    if not rows:
                        return 0, 0.0, 0.0
                    pls = [float(r['realized_pl']) for r in rows]
                    wins = sum(1 for p in pls if p > 0)
                    return len(pls), wins / len(pls), sum(pls) / len(pls)

                r_trades, r_wr, r_avg = _window_stats(short_window)
                l_trades, l_wr, l_avg = _window_stats(long_window)

            decay = (r_trades >= 5 and l_wr > 0 and r_wr < l_wr * 0.75)
            msg = (
                f"Win rate dropped from {l_wr:.0%} to {r_wr:.0%} over last {short_window} days"
                " — review strategy"
                if decay else "Performance within normal range"
            )
            return {
                'recent_win_rate': round(r_wr, 4),
                'longterm_win_rate': round(l_wr, 4),
                'recent_avg_pl': round(r_avg, 2),
                'longterm_avg_pl': round(l_avg, 2),
                'decay_detected': decay,
                'message': msg,
            }
        except Exception:
            log.exception("decay_check failed")
            return {
                'recent_win_rate': 0.0,
                'longterm_win_rate': 0.0,
                'recent_avg_pl': 0.0,
                'longterm_avg_pl': 0.0,
                'decay_detected': False,
                'message': 'Error computing decay',
            }

    def ev_by_setup(self, pid: int, days: int = 90) -> list:
        """
        Compute Expected Value per (regime, dominant_signal) setup.
        Returns list sorted by EV descending.
        Each entry: {setup, regime, signal, trades, win_rate, avg_win, avg_loss, ev, profitable}
        """
        try:
            with self._get_db() as conn:
                _migrate_db(conn)
                cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
                rows = conn.execute('''
                    SELECT t.realized_pl, t.created_at,
                           l.market_state, l.reason, l.score
                    FROM sim_trades t
                    LEFT JOIN ai_log l ON l.portfolio_id = ?
                        AND l.symbol = t.symbol
                        AND l.action IN ('BUY', 'SHORT')
                        AND l.created_at <= t.created_at
                    WHERE t.portfolio_id = ? AND t.status = 'filled'
                    AND t.side IN ('sell', 'cover') AND t.created_at > ?
                ''', (pid, pid, cutoff)).fetchall()

            groups = defaultdict(list)
            for row in rows:
                regime = row['market_state'] or 'neutral'
                reason = (row['reason'] or '').lower()
                # Extract dominant signal from reason text
                signal = 'neutral'
                for kw in ['rsi', 'macd', 'vwap', 'volume', 'trend', 'bb', 'stoch', 'pattern', 'news']:
                    if kw in reason:
                        signal = kw
                        break
                key = f'{regime}:{signal}'
                groups[key].append(float(row['realized_pl'] or 0))

            result = []
            for setup, pls in groups.items():
                if len(pls) < 3:
                    continue
                regime, signal = setup.split(':', 1)
                wins   = [p for p in pls if p > 0]
                losses = [p for p in pls if p <= 0]
                wr     = len(wins) / len(pls)
                avg_w  = sum(wins) / len(wins) if wins else 0
                avg_l  = sum(losses) / len(losses) if losses else 0
                ev     = wr * avg_w - (1 - wr) * abs(avg_l)
                result.append({
                    'setup':      setup,
                    'regime':     regime,
                    'signal':     signal,
                    'trades':     len(pls),
                    'win_rate':   round(wr, 3),
                    'avg_win':    round(avg_w, 2),
                    'avg_loss':   round(avg_l, 2),
                    'ev':         round(ev, 2),
                    'profitable': ev > 0,
                    'total_pl':   round(sum(pls), 2),
                })

            return sorted(result, key=lambda x: x['ev'], reverse=True)
        except Exception as e:
            log.debug('[PERF] ev_by_setup error: %s', e)
            return []

    def summary(self, pid: int) -> dict:
        try:
            regime_data = self.by_regime(pid, days=90)
            decay = self.decay_check(pid)
            curve = self.equity_curve(pid, days=7)

            total_info = regime_data.get('_total', {})
            total_trades = total_info.get('trades', 0)
            win_rate = total_info.get('win_rate', 0.0)
            total_pl = total_info.get('total_pl', 0.0)
            avg_pl = total_info.get('avg_pl', 0.0)

            # Find best/worst regime (min 3 trades, exclude _total)
            eligible = {k: v for k, v in regime_data.items()
                        if k != '_total' and v.get('trades', 0) >= 3}
            best_regime = max(eligible, key=lambda k: eligible[k]['win_rate'], default='n/a')
            worst_regime = min(eligible, key=lambda k: eligible[k]['win_rate'], default='n/a')

            return {
                'total_trades': total_trades,
                'win_rate': win_rate,
                'total_pl': total_pl,
                'avg_pl_per_trade': avg_pl,
                'best_regime': best_regime,
                'worst_regime': worst_regime,
                'decay': decay,
                'equity_curve_7d': curve,
            }
        except Exception:
            log.exception("summary failed")
            return {
                'total_trades': 0,
                'win_rate': 0.0,
                'total_pl': 0.0,
                'avg_pl_per_trade': 0.0,
                'best_regime': 'n/a',
                'worst_regime': 'n/a',
                'decay': {},
                'equity_curve_7d': [],
            }


# ------------------------------------------------------------------
# Module-level convenience
# ------------------------------------------------------------------

_engine: PerformanceEngine | None = None


def init_engine(db_path) -> PerformanceEngine:
    global _engine
    _engine = PerformanceEngine(db_path)
    return _engine


def get_engine() -> PerformanceEngine | None:
    return _engine


def get_ev_by_setup(db_path, pid: int, days: int = 90) -> list:
    """Module-level convenience for app.py to call."""
    try:
        return PerformanceEngine(db_path).ev_by_setup(pid, days)
    except Exception:
        return []

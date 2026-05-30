"""
RLEngine — Q-table reinforcement learning for trading strategy adaptation.

State: (regime, mtf_bias, swing_bias, portfolio_heat_tier)
Action: (strategy_name, size_tier, entry_timing)
Reward: realized_pl / max_drawdown_risk (Calmar-style)

Learns which actions work best in each state over time.
Q-table persists in SQLite. Updates on each trade close.
Falls back to rule-based defaults when insufficient data.
"""

import logging
import random
import sqlite3

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State space
# ---------------------------------------------------------------------------

REGIMES = [
    'trending_up', 'trending_down', 'breakout', 'accumulation',
    'ranging', 'panic', 'euphoric', 'distribution',
    'mild_uptrend', 'mild_downtrend', 'oversold_extreme',
    'overbought_extreme', 'news_driven', 'neutral',
]

MTF_BIAS   = ['bullish', 'bearish', 'neutral']
SWING_BIAS = ['bullish', 'bearish', 'undefined']
HEAT_TIER  = ['low', 'medium', 'high']


def encode_state(regime: str, mtf_bias: str, swing_bias: str, heat: float) -> str:
    """Encode market state as a compact string key for the Q-table."""
    heat_tier = 'low' if heat < 0.02 else 'high' if heat > 0.04 else 'medium'
    mtf   = mtf_bias   if mtf_bias   in MTF_BIAS   else 'neutral'
    swing = swing_bias if swing_bias in SWING_BIAS else 'undefined'
    reg   = regime     if regime     in REGIMES    else 'neutral'
    return f'{reg}|{mtf}|{swing}|{heat_tier}'


# ---------------------------------------------------------------------------
# Action space
# ---------------------------------------------------------------------------

STRATEGIES = ['trend_follow', 'mean_revert', 'breakout', 'momentum', 'neutral']
SIZE_TIERS = ['small', 'medium', 'large']   # 0.3%, 0.5%, 1.0% risk
TIMINGS    = ['immediate', 'wait_pullback']

SIZE_RISK  = {'small': 0.003, 'medium': 0.005, 'large': 0.010}


def encode_action(strategy: str, size_tier: str, timing: str) -> str:
    return f'{strategy}|{size_tier}|{timing}'


def decode_action(action_key: str) -> dict:
    parts = action_key.split('|')
    return {'strategy': parts[0], 'size_tier': parts[1], 'timing': parts[2]}


# ---------------------------------------------------------------------------
# Q-table — SQLite-backed
# ---------------------------------------------------------------------------

class QTable:
    LEARNING_RATE = 0.1    # alpha
    DISCOUNT      = 0.95   # gamma
    EXPLORATION   = 0.15   # epsilon — explore vs exploit
    MIN_VISITS    = 3      # minimum (state, action) visits before trusting the Q-value

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_table()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_table(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS rl_qtable (
                        state_key   TEXT NOT NULL,
                        action_key  TEXT NOT NULL,
                        q_value     REAL NOT NULL DEFAULT 0.0,
                        visits      INTEGER NOT NULL DEFAULT 0,
                        last_reward REAL NOT NULL DEFAULT 0.0,
                        updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
                        PRIMARY KEY (state_key, action_key)
                    )
                ''')
        except Exception as exc:
            log.error('[RL] Failed to initialise Q-table: %s', exc)

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def get_q(self, state: str, action: str) -> float:
        """Return the current Q-value for (state, action); 0.0 if unseen."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    'SELECT q_value FROM rl_qtable WHERE state_key=? AND action_key=?',
                    (state, action),
                ).fetchone()
            return row[0] if row else 0.0
        except Exception as exc:
            log.error('[RL] get_q error: %s', exc)
            return 0.0

    def _all_action_keys(self) -> list:
        return [
            encode_action(s, sz, t)
            for s in STRATEGIES
            for sz in SIZE_TIERS
            for t in TIMINGS
        ]

    # ------------------------------------------------------------------
    # Write / update
    # ------------------------------------------------------------------

    def update_q(self, state: str, action: str, reward: float, next_state: str):
        """
        Bellman equation update:
        Q(s,a) += lr * (reward + gamma * max_Q(s') - Q(s,a))
        """
        try:
            current_q = self.get_q(state, action)
            all_actions = self._all_action_keys()
            next_qs = [self.get_q(next_state, a) for a in all_actions]
            max_next_q = max(next_qs) if next_qs else 0.0

            new_q = current_q + self.LEARNING_RATE * (
                reward + self.DISCOUNT * max_next_q - current_q
            )

            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT INTO rl_qtable (state_key, action_key, q_value, visits, last_reward)
                    VALUES (?, ?, ?, 1, ?)
                    ON CONFLICT(state_key, action_key) DO UPDATE SET
                        q_value     = excluded.q_value,
                        visits      = visits + 1,
                        last_reward = excluded.last_reward,
                        updated_at  = datetime('now')
                ''', (state, action, round(new_q, 6), round(reward, 6)))
        except Exception as exc:
            log.error('[RL] update_q error: %s', exc)

    # ------------------------------------------------------------------
    # Policy
    # ------------------------------------------------------------------

    def best_action(self, state: str, explore: bool = True) -> dict:
        """
        Return the best action for the given state using epsilon-greedy exploration.
        Falls back to 'momentum|medium|immediate' when the Q-table has no
        trusted data for this state.
        """
        # --- Explore ---
        if explore and random.random() < self.EXPLORATION:
            strategy = random.choice(STRATEGIES)
            size     = random.choice(SIZE_TIERS)
            timing   = random.choice(TIMINGS)
            return {
                'strategy': strategy,
                'size_tier': size,
                'timing': timing,
                'source': 'explore',
                'q_value': 0.0,
            }

        # --- Exploit: best trusted Q-value for this state ---
        try:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    '''SELECT action_key, q_value, visits
                       FROM rl_qtable
                       WHERE state_key = ? AND visits >= ?
                       ORDER BY q_value DESC
                       LIMIT 1''',
                    (state, self.MIN_VISITS),
                ).fetchall()
        except Exception as exc:
            log.error('[RL] best_action db error: %s', exc)
            rows = []

        if rows:
            action = decode_action(rows[0][0])
            action['source']  = 'exploit'
            action['q_value'] = round(rows[0][1], 4)
            return action

        # --- Default fallback ---
        return {
            'strategy': 'momentum',
            'size_tier': 'medium',
            'timing': 'immediate',
            'source': 'default',
            'q_value': 0.0,
        }

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """Return Q-table summary statistics."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                total  = conn.execute('SELECT COUNT(*) FROM rl_qtable').fetchone()[0]
                visits = conn.execute('SELECT SUM(visits) FROM rl_qtable').fetchone()[0] or 0
                best   = conn.execute(
                    '''SELECT state_key, action_key, q_value
                       FROM rl_qtable
                       ORDER BY q_value DESC
                       LIMIT 5'''
                ).fetchall()
            return {
                'state_action_pairs': total,
                'total_updates': visits,
                'top_5': [
                    {'state': r[0], 'action': r[1], 'q': round(r[2], 4)}
                    for r in best
                ],
            }
        except Exception as exc:
            log.error('[RL] stats error: %s', exc)
            return {'state_action_pairs': 0, 'total_updates': 0, 'top_5': []}


# ---------------------------------------------------------------------------
# RLEngine — main class
# ---------------------------------------------------------------------------

class RLEngine:
    def __init__(self, db_path: str):
        self.qtable = QTable(db_path)

    def get_action(
        self,
        regime: str,
        mtf_bias: str,
        swing_bias: str,
        portfolio_heat: float,
        explore: bool = True,
    ) -> dict:
        """
        Get the RL-recommended action for the current market state.

        Returns a dict with keys:
            strategy, size_tier, timing, source, q_value, risk_pct, state_key
        """
        state  = encode_state(regime, mtf_bias, swing_bias, portfolio_heat)
        action = self.qtable.best_action(state, explore=explore)
        action['risk_pct']  = SIZE_RISK.get(action.get('size_tier', 'medium'), 0.005)
        action['state_key'] = state
        return action

    def record_outcome(
        self,
        state_key: str,
        action_key: str,
        realized_pl: float,
        max_risk: float,
        next_state_key: str,
    ):
        """
        Called after a trade closes.  Computes a Calmar-style reward and
        updates the Q-table via the Bellman equation.

        reward = realized_pl / max_risk, clipped to [-3, +3]
        """
        if max_risk <= 0:
            reward = 0.0
        else:
            reward = max(-3.0, min(3.0, realized_pl / max_risk))

        self.qtable.update_q(state_key, action_key, reward, next_state_key)
        log.debug(
            '[RL] Q-update: state=%s action=%s reward=%.3f',
            state_key, action_key, reward,
        )

    def stats(self) -> dict:
        return self.qtable.stats()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine: 'RLEngine | None' = None


def init(db_path: str) -> RLEngine:
    """Initialise the module-level RLEngine singleton."""
    global _engine
    _engine = RLEngine(db_path)
    log.info('[RL] RLEngine initialized — Q-table ready')
    return _engine


def get_engine() -> 'RLEngine | None':
    """Return the module-level engine instance (None if not yet initialised)."""
    return _engine


def get_action(
    regime: str,
    mtf_bias: str = 'neutral',
    swing_bias: str = 'undefined',
    portfolio_heat: float = 0.02,
    explore: bool = True,
) -> dict:
    """
    Module-level convenience wrapper.
    Returns a safe default when the engine has not been initialised.
    """
    if _engine is None:
        return {
            'strategy': 'momentum',
            'size_tier': 'medium',
            'timing': 'immediate',
            'source': 'uninitialized',
            'risk_pct': 0.005,
        }
    return _engine.get_action(regime, mtf_bias, swing_bias, portfolio_heat, explore)


def record_outcome(
    state_key: str,
    action_key: str,
    realized_pl: float,
    max_risk: float,
    next_state_key: str = 'neutral|neutral|undefined|medium',
):
    """Module-level convenience wrapper for recording trade outcomes."""
    if _engine:
        _engine.record_outcome(state_key, action_key, realized_pl, max_risk, next_state_key)

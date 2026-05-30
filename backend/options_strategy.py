"""
OptionsStrategy — regime-driven options strategy selection and portfolio Greeks management.

Builds on OptionsEngine to:
  - Map market regime → preferred options strategy
  - Construct spread legs (bull spread, bear spread, iron condor)
  - Track total portfolio delta/gamma/theta/vega across all open options
  - Implement adaptive exits: 50% profit target for short premium, delta-based for long

Usage:
    from options_strategy import OptionsStrategyManager
    mgr = OptionsStrategyManager(db_path)
    signal = mgr.evaluate(symbol, underlying_price, ai_score, regime, uncertainty)
"""

import logging
import math
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Strategy-regime mapping
# ---------------------------------------------------------------------------

# Which options strategies are appropriate for each market regime
REGIME_STRATEGY_MAP: dict[str, list[str]] = {
    'trending_up':        ['long_call', 'bull_spread'],
    'trending_down':      ['long_put',  'bear_spread'],
    'breakout':           ['long_call', 'long_put'],       # direction TBD by score
    'ranging':            ['iron_condor', 'short_strangle'],
    'accumulation':       ['bull_spread', 'long_call'],
    'panic':              ['long_put', 'bear_spread'],     # volatility already high
    'euphoric':           ['bear_spread', 'long_put'],     # expect reversal
    'distribution':       ['bear_spread', 'long_put'],
    'mild_uptrend':       ['bull_spread'],
    'mild_downtrend':     ['bear_spread'],
    'overbought_extreme': ['bear_spread'],
    'oversold_extreme':   ['bull_spread'],
    'news_driven':        [],   # too unpredictable — no options in news regime
    'neutral':            [],   # no edge — skip
}


def _iv_regime(iv_rank: float | None) -> str:
    """Classify IV rank into a regime label."""
    if iv_rank is None:
        return 'unknown'
    if iv_rank >= 70:
        return 'high_iv'   # sell premium
    if iv_rank <= 30:
        return 'low_iv'    # buy premium
    return 'normal_iv'


# Strategies favored (or penalised) by IV regime
IV_STRATEGY_PREFERENCE: dict[str, dict[str, list[str]]] = {
    'high_iv': {
        'prefer': ['iron_condor', 'short_strangle', 'bull_spread', 'bear_spread'],
        'avoid':  ['long_call', 'long_put'],
    },
    'low_iv': {
        'prefer': ['long_call', 'long_put'],
        'avoid':  ['iron_condor', 'short_strangle'],
    },
    'normal_iv': {'prefer': [], 'avoid': []},
    'unknown':   {'prefer': [], 'avoid': []},
}


# ---------------------------------------------------------------------------
# Spread construction helpers
# ---------------------------------------------------------------------------

def build_bull_spread(atm_contract: dict, step_pct: float = 0.05) -> list[dict]:
    """
    Construct a bull call spread: buy ATM call, sell OTM call ~5% above.

    Returns a two-element list of leg descriptors:
        [{'action': 'buy', 'strike': ..., 'type': 'call', 'role': 'long_leg'},
         {'action': 'sell', 'strike': ..., 'type': 'call', 'role': 'short_leg'}]
    """
    try:
        strike = atm_contract.get('strike', 0)
        otm_strike = round(strike * (1 + step_pct), 2)
        return [
            {'action': 'buy',  'strike': strike,     'type': 'call', 'role': 'long_leg'},
            {'action': 'sell', 'strike': otm_strike, 'type': 'call', 'role': 'short_leg'},
        ]
    except Exception as exc:
        log.warning('build_bull_spread error: %s', exc)
        return []


def build_bear_spread(atm_contract: dict, step_pct: float = 0.05) -> list[dict]:
    """
    Construct a bear put spread: buy ATM put, sell OTM put ~5% below.

    Returns a two-element list of leg descriptors.
    """
    try:
        strike = atm_contract.get('strike', 0)
        otm_strike = round(strike * (1 - step_pct), 2)
        return [
            {'action': 'buy',  'strike': strike,     'type': 'put', 'role': 'long_leg'},
            {'action': 'sell', 'strike': otm_strike, 'type': 'put', 'role': 'short_leg'},
        ]
    except Exception as exc:
        log.warning('build_bear_spread error: %s', exc)
        return []


def build_iron_condor(atm_contract: dict, wing_pct: float = 0.05) -> list[dict]:
    """
    Construct an iron condor around ATM:
      - Sell OTM call (atm * 1.05), buy further OTM call (atm * 1.10)
      - Sell OTM put  (atm * 0.95), buy further OTM put  (atm * 0.90)

    Returns a four-element list of leg descriptors.
    """
    try:
        strike = atm_contract.get('strike', 0)
        call_short = round(strike * (1 + wing_pct),       2)
        call_long  = round(strike * (1 + wing_pct * 2),   2)
        put_short  = round(strike * (1 - wing_pct),       2)
        put_long   = round(strike * (1 - wing_pct * 2),   2)
        return [
            {'action': 'sell', 'strike': call_short, 'type': 'call', 'role': 'short_call'},
            {'action': 'buy',  'strike': call_long,  'type': 'call', 'role': 'long_call'},
            {'action': 'sell', 'strike': put_short,  'type': 'put',  'role': 'short_put'},
            {'action': 'buy',  'strike': put_long,   'type': 'put',  'role': 'long_put'},
        ]
    except Exception as exc:
        log.warning('build_iron_condor error: %s', exc)
        return []


def build_legs(strategy: str, atm_contract: dict) -> list[dict]:
    """
    Dispatch spread-leg construction by strategy name.

    Single-leg strategies (long_call, long_put, short_strangle) return an
    empty list — the caller uses the primary contract directly.
    """
    try:
        if strategy == 'bull_spread':
            return build_bull_spread(atm_contract)
        if strategy == 'bear_spread':
            return build_bear_spread(atm_contract)
        if strategy == 'iron_condor':
            return build_iron_condor(atm_contract)
        # long_call / long_put / short_strangle — no spread legs
        return []
    except Exception as exc:
        log.warning('build_legs error for %s: %s', strategy, exc)
        return []


# ---------------------------------------------------------------------------
# PortfolioGreeks
# ---------------------------------------------------------------------------

@dataclass
class GreeksSnapshot:
    """Aggregated portfolio-level Greeks across all open options positions."""
    delta:     float = 0.0   # net directional exposure
    gamma:     float = 0.0   # rate of delta change
    theta:     float = 0.0   # daily time decay (negative = losing value)
    vega:      float = 0.0   # volatility sensitivity
    positions: int   = 0


class PortfolioGreeks:
    """Reads open options positions from DB and aggregates Greeks."""

    # Risk limits
    MAX_NET_DELTA         = 0.50    # max net delta (0.5 = ~50 share-equivalent)
    MAX_SHORT_VEGA        = -500    # max negative vega exposure (short vol risk)
    MAX_SHORT_THETA_DAILY = -200    # max theta decay per day across all positions

    def __init__(self, db_path: str):
        self.db_path = db_path

    def compute(self, pid: int) -> GreeksSnapshot:
        """Aggregate Greeks from sim_options_positions for a portfolio."""
        try:
            import sqlite3
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                'SELECT contracts, delta, gamma, theta, vega, side '
                'FROM sim_options_positions WHERE portfolio_id=? AND status=?',
                (pid, 'open'),
            ).fetchall()
            conn.close()
        except Exception as exc:
            log.debug('PortfolioGreeks.compute DB error: %s', exc)
            return GreeksSnapshot()

        snap = GreeksSnapshot(positions=len(rows))
        for r in rows:
            try:
                mult = 100 * (r['contracts'] or 1)
                sign = -1 if r['side'] == 'short' else 1
                snap.delta += (r['delta'] or 0.0) * mult * sign
                snap.gamma += (r['gamma'] or 0.0) * mult * sign
                snap.theta += (r['theta'] or 0.0) * mult * sign
                snap.vega  += (r['vega']  or 0.0) * mult * sign
            except Exception as row_exc:
                log.warning('PortfolioGreeks row error: %s', row_exc)

        return snap

    def check_limits(self, snap: GreeksSnapshot) -> list[str]:
        """Return list of risk warning strings derived from the Greeks snapshot."""
        warnings: list[str] = []
        try:
            if abs(snap.delta) > self.MAX_NET_DELTA * 100:
                warnings.append(
                    f'Net delta {snap.delta:.1f} — excessive directional exposure'
                )
            if snap.vega < self.MAX_SHORT_VEGA:
                warnings.append(
                    f'Short vega {snap.vega:.0f} — dangerous if volatility spikes'
                )
            if snap.theta < self.MAX_SHORT_THETA_DAILY:
                warnings.append(
                    f'Theta {snap.theta:.0f}/day — heavy time decay burden'
                )
        except Exception as exc:
            log.warning('check_limits error: %s', exc)
        return warnings


# ---------------------------------------------------------------------------
# ExitManager
# ---------------------------------------------------------------------------

class ExitManager:
    """
    Rules for exiting options positions.
    Different rules for long premium vs short premium positions.
    """

    LONG_PROFIT_TARGET  = 0.60   # take profit at 60% gain on long options
    LONG_STOP_LOSS      = 0.50   # stop loss at 50% of premium paid
    SHORT_PROFIT_TARGET = 0.50   # take profit at 50% of max premium collected
    DTE_DANGER_ZONE     = 14     # close all positions with < 14 DTE (gamma risk)
    DTE_EXIT_SHORT      = 21     # close short premium at 21 DTE

    def should_exit(self, position: dict, current_price: float) -> tuple[bool, str]:
        """
        Evaluate whether a position should be closed.

        Args:
            position: dict with keys entry_price, side, strategy,
                      dte_remaining, current_iv, entry_iv, current_delta (optional)
            current_price: current mid-price of the option contract

        Returns:
            (should_exit: bool, reason: str)
        """
        try:
            entry_price = position.get('entry_price', 0)
            side        = position.get('side', 'long')
            dte         = position.get('dte_remaining', 999)

            if entry_price <= 0:
                return False, ''

            # DTE danger zone — always exit regardless of P&L
            if dte <= self.DTE_DANGER_ZONE:
                return True, f'DTE danger zone ({dte} days remaining — gamma risk)'

            if side == 'long':
                pct_gain = (current_price - entry_price) / entry_price

                if pct_gain >= self.LONG_PROFIT_TARGET:
                    return True, f'profit target hit ({pct_gain:.0%} gain)'

                if pct_gain <= -self.LONG_STOP_LOSS:
                    return True, f'stop loss ({pct_gain:.0%} loss)'

                # Delta weakness: intrinsic value mostly gone
                delta = position.get('current_delta', 0.5)
                if abs(delta) < 0.15 and pct_gain < 0:
                    return True, (
                        f'delta collapsed ({delta:.2f}) — '
                        'position losing directional edge'
                    )

            elif side == 'short':
                pct_captured = (entry_price - current_price) / entry_price

                if pct_captured >= self.SHORT_PROFIT_TARGET:
                    return True, (
                        f'{self.SHORT_PROFIT_TARGET:.0%} of premium captured — closing'
                    )

                if dte <= self.DTE_EXIT_SHORT:
                    return True, f'short premium DTE exit at {dte} days'

                # Circuit breaker: loss at 2× premium collected
                if current_price >= entry_price * 2:
                    return True, 'loss at 200% of premium — circuit breaker'

        except Exception as exc:
            log.warning('ExitManager.should_exit error: %s', exc)

        return False, ''


# ---------------------------------------------------------------------------
# OptionsStrategyManager — main class
# ---------------------------------------------------------------------------

class OptionsStrategyManager:
    """Regime-driven options strategy selection with portfolio Greeks management."""

    MIN_SCORE_FOR_OPTIONS      = 3.0    # don't trade options on weak signals
    MAX_OPTIONS_PORTFOLIO_PCT  = 0.10   # max 10% of portfolio in options premium

    def __init__(self, db_path):
        from pathlib import Path
        self.db_path      = str(db_path)
        self.port_greeks  = PortfolioGreeks(self.db_path)
        self.exit_manager = ExitManager()
        log.info('OptionsStrategyManager initialised (db=%s)', self.db_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        symbol: str,
        underlying_price: float,
        ai_score: float,
        regime: str,
        uncertainty: float = 0.3,
        portfolio_equity: float = 100_000,
        pid: int = 1,
    ) -> dict:
        """
        Full options trade evaluation for a given symbol and market context.

        Returns:
        {
            'recommend':        bool,
            'strategy':         str,
            'rationale':        str,
            'contract':         dict | None,
            'legs':             list[dict],         # spread legs (empty for single-leg)
            'size_contracts':   int,
            'max_risk':         float,
            'portfolio_greeks': dict,
            'greeks_warnings':  list[str],
            'iv_rank':          float | None,
            'iv_percentile':    float | None,
        }
        """
        try:
            # Gate 1: signal strength
            if abs(ai_score) < self.MIN_SCORE_FOR_OPTIONS:
                return self._no_trade('Signal too weak for options', regime)

            # Gate 2: uncertainty too high
            if uncertainty > 0.7:
                return self._no_trade('Uncertainty too high for options', regime)

            # Gate 3: regime suitability
            suitable = REGIME_STRATEGY_MAP.get(regime, [])
            if not suitable:
                return self._no_trade(
                    f'Regime {regime!r} not suitable for options', regime
                )

            # Gate 4: portfolio Greeks limits
            greeks = self.port_greeks.compute(pid)
            greek_warnings = self.port_greeks.check_limits(greeks)

            # Fetch signal from options engine
            try:
                import options_engine as _oe
                engine = _oe.get_engine()
                if not engine:
                    return self._no_trade('Options engine not initialised', regime)
                signal = engine.get_signal(symbol, underlying_price, ai_score, regime)
            except Exception as eng_exc:
                return self._no_trade(f'Options engine error: {eng_exc}', regime)

            if not signal.get('contract'):
                return self._no_trade(
                    signal.get('rationale', 'No suitable contract'), regime
                )

            # IV regime alignment check
            iv_rank   = signal.get('iv_rank')
            iv_regime = _iv_regime(iv_rank)
            pref      = IV_STRATEGY_PREFERENCE.get(iv_regime, {})
            strategy  = signal.get('strategy', suitable[0])

            if strategy in pref.get('avoid', []):
                alternatives = [s for s in suitable if s in pref.get('prefer', [])]
                if alternatives:
                    strategy = alternatives[0]
                    log.debug(
                        'IV regime %s: switched strategy from %s → %s',
                        iv_regime, signal['strategy'], strategy,
                    )
                else:
                    return self._no_trade(
                        f'IV environment ({iv_regime}) unfavorable for {strategy}',
                        regime,
                    )

            # Build spread legs where applicable
            legs = build_legs(strategy, signal['contract'])

            # Position sizing: risk fixed % of equity (default 0.5%)
            risk_budget   = portfolio_equity * 0.005
            contract_cost = (signal['contract'].get('mid') or 0) * 100
            if contract_cost > 0:
                size = max(1, int(risk_budget / contract_cost))
            else:
                size = 1
            size = min(size, 5)   # cap at 5 contracts per position

            return {
                'recommend':        True,
                'strategy':         strategy,
                'rationale':        signal.get('rationale', ''),
                'contract':         signal['contract'],
                'legs':             legs,
                'size_contracts':   size,
                'max_risk':         round(contract_cost * size, 2),
                'portfolio_greeks': {
                    'delta': greeks.delta,
                    'gamma': greeks.gamma,
                    'theta': greeks.theta,
                    'vega':  greeks.vega,
                },
                'greeks_warnings':  greek_warnings,
                'iv_rank':          iv_rank,
                'iv_percentile':    signal.get('iv_percentile'),
            }

        except Exception as exc:
            log.error('OptionsStrategyManager.evaluate unexpected error: %s', exc)
            return self._no_trade(f'Unexpected error: {exc}', regime)

    def check_exits(self, open_positions: list[dict]) -> list[dict]:
        """
        Evaluate all open options positions for exit signals.

        Args:
            open_positions: list of position dicts (from DB or in-memory store)

        Returns:
            list of position dicts that should be closed, each augmented with
            an 'exit_reason' key.
        """
        exits: list[dict] = []
        try:
            for pos in open_positions:
                try:
                    current_price = pos.get('current_price') or pos.get('entry_price', 0)
                    should_exit, reason = self.exit_manager.should_exit(pos, current_price)
                    if should_exit:
                        exits.append({**pos, 'exit_reason': reason})
                except Exception as pos_exc:
                    log.warning('check_exits position error: %s', pos_exc)
        except Exception as exc:
            log.error('check_exits error: %s', exc)
        return exits

    def portfolio_greeks_summary(self, pid: int = 1) -> dict:
        """
        Return the current portfolio Greeks snapshot as a plain dict,
        together with any active risk warnings.
        """
        try:
            snap = self.port_greeks.compute(pid)
            warnings = self.port_greeks.check_limits(snap)
            return {
                'delta':     snap.delta,
                'gamma':     snap.gamma,
                'theta':     snap.theta,
                'vega':      snap.vega,
                'positions': snap.positions,
                'warnings':  warnings,
            }
        except Exception as exc:
            log.error('portfolio_greeks_summary error: %s', exc)
            return {'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0,
                    'positions': 0, 'warnings': []}

    # ------------------------------------------------------------------
    # Execution layer — open/manage simulated options positions
    # ------------------------------------------------------------------

    def _get_db(self):
        """Open a sqlite3 connection with row access by column name."""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _position_side(strategy: str) -> str:
        """Map a strategy name to 'long' (debit) or 'short' (credit)."""
        s = (strategy or '').lower()
        # Credit / premium-selling strategies are net short.
        if s in ('iron_condor', 'short_strangle', 'short_straddle',
                 'credit_spread', 'short_put', 'short_call'):
            return 'short'
        # long_call / long_put / bull_spread / bear_spread (debit) buying.
        return 'long'

    def open_position(self, pid: int, evaluation: dict) -> dict | None:
        """Open a simulated options position from an evaluate() recommendation.

        Inserts a row into sim_options_positions. Position sizing and risk are
        already enforced upstream in evaluate(); this only executes the trade.

        Returns a summary dict for the opened position, or None when the
        evaluation does not recommend a trade or insertion fails.
        """
        try:
            if not evaluation or not evaluation.get('recommend'):
                return None

            contract = evaluation.get('contract') or {}
            symbol   = contract.get('symbol')
            if not symbol:
                log.debug('open_position: evaluation has no contract symbol')
                return None

            strategy   = evaluation.get('strategy', 'none')
            side       = self._position_side(strategy)
            contracts  = int(evaluation.get('size_contracts') or 1)
            if contracts <= 0:
                return None

            underlying  = (contract.get('underlying_symbol')
                           or contract.get('root_symbol')
                           or evaluation.get('symbol')
                           or '')
            entry_price = float(contract.get('mid') or 0.0)
            strike      = float(contract.get('strike_price')
                                or contract.get('strike') or 0.0)
            expiry      = contract.get('expiration_date') or contract.get('expiry') or ''
            dte_entry   = contract.get('dte')
            try:
                dte_entry = int(dte_entry) if dte_entry is not None else None
            except (TypeError, ValueError):
                dte_entry = None

            iv_entry = contract.get('iv')
            delta    = contract.get('delta')
            gamma    = contract.get('gamma')
            theta    = contract.get('theta')
            vega     = contract.get('vega')

            with self._get_db() as conn:
                cur = conn.execute(
                    '''INSERT INTO sim_options_positions
                       (portfolio_id, underlying, symbol, strategy, side,
                        contracts, entry_price, current_price,
                        delta, gamma, theta, vega, iv_at_entry,
                        strike, expiry, dte_at_entry, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (pid, underlying, symbol, strategy, side,
                     contracts, entry_price, entry_price,
                     delta, gamma, theta, vega, iv_entry,
                     strike, expiry, dte_entry, 'open'),
                )
                new_id = cur.lastrowid

            log.info('options open_position: %s %s x%d @ %.2f (%s) id=%s',
                     side, symbol, contracts, entry_price, strategy, new_id)
            return {
                'id':          new_id,
                'portfolio_id': pid,
                'underlying':  underlying,
                'symbol':      symbol,
                'strategy':    strategy,
                'side':        side,
                'contracts':   contracts,
                'entry_price': round(entry_price, 4),
                'strike':      strike,
                'expiry':      expiry,
                'dte_at_entry': dte_entry,
                'status':      'open',
            }
        except Exception as exc:
            log.error('open_position error: %s', exc)
            return None

    def manage_open_positions(self, pid: int) -> dict:
        """Re-price and evaluate every open options position for a portfolio.

        For each open position: refresh current_price from the live chain
        (falling back to a Black-Scholes theoretical price), recompute days to
        expiry, and apply ExitManager rules. Triggered exits are closed with a
        realized P&L and reason. Meant to run each scan cycle.

        Returns {'checked': int, 'closed': [{'symbol', 'reason', 'pl'}, ...]}.
        """
        result = {'checked': 0, 'closed': []}
        try:
            with self._get_db() as conn:
                rows = conn.execute(
                    '''SELECT * FROM sim_options_positions
                       WHERE portfolio_id=? AND status=?''',
                    (pid, 'open'),
                ).fetchall()
        except Exception as exc:
            log.error('manage_open_positions DB read error: %s', exc)
            return result

        try:
            import options_engine as _oe
            engine = _oe.get_engine()
        except Exception as exc:
            log.debug('manage_open_positions: options engine unavailable: %s', exc)
            engine = None

        for row in rows:
            try:
                result['checked'] += 1
                pos = dict(row)
                symbol      = pos.get('symbol')
                entry_price = pos.get('entry_price') or 0.0

                current_price = self._current_price(engine, pos)
                dte_remaining = self._dte_remaining(pos)

                exit_pos = {
                    'entry_price':   entry_price,
                    'side':          pos.get('side', 'long'),
                    'strategy':      pos.get('strategy', ''),
                    'dte_remaining': dte_remaining,
                    'current_delta': pos.get('delta', 0.5),
                    'entry_iv':      pos.get('iv_at_entry'),
                }
                should_exit, reason = self.exit_manager.should_exit(
                    exit_pos, current_price)

                if should_exit:
                    realized_pl = (current_price - entry_price) * \
                        (pos.get('contracts') or 1) * 100
                    if pos.get('side') == 'short':
                        realized_pl = -realized_pl
                    realized_pl = round(realized_pl, 2)
                    self._close_position(
                        pos['id'], current_price, reason, realized_pl)
                    result['closed'].append(
                        {'symbol': symbol, 'reason': reason, 'pl': realized_pl})
                    log.info('options exit: %s — %s (P&L %.2f)',
                             symbol, reason, realized_pl)
                else:
                    self._update_price(pos['id'], current_price)
            except Exception as pos_exc:
                log.warning('manage_open_positions position error: %s', pos_exc)

        return result

    # -- execution helpers --------------------------------------------------

    def _current_price(self, engine, pos: dict) -> float:
        """Best-available current mid price for an open contract."""
        entry_price = pos.get('entry_price') or 0.0
        symbol      = pos.get('symbol')
        if engine is None or not symbol:
            return entry_price
        try:
            quote = engine.chain.get_quote(symbol)
            if quote and quote.get('mid', 0) > 0:
                return float(quote['mid'])
        except Exception as exc:
            log.debug('get_quote failed for %s: %s', symbol, exc)

        # Fall back to a Black-Scholes theoretical price.
        try:
            import options_engine as _oe
            from datetime import date
            strike = float(pos.get('strike') or 0)
            expiry = pos.get('expiry')
            if strike > 0 and expiry:
                exp = date.fromisoformat(str(expiry)[:10])
                T   = max(0.001, (exp - date.today()).days / 365.0)
                opt_type   = 'put' if 'put' in (pos.get('strategy') or '').lower() \
                    else 'call'
                # Positions are opened near-the-money, so approximate the
                # underlying spot with the strike — avoids extra market-data
                # calls while keeping the theoretical fallback sane.
                S  = strike
                iv = pos.get('iv_at_entry') or 0.30
                r  = getattr(engine.chain, 'RISK_FREE_RATE', 0.045) \
                    if engine else 0.045
                price = _oe.bs_price(S, strike, T, r, iv or 0.30, opt_type)
                if price > 0:
                    return round(price, 4)
        except Exception as exc:
            log.debug('bs_price fallback failed for %s: %s', symbol, exc)
        return entry_price

    def _dte_remaining(self, pos: dict) -> int:
        """Days to expiry from today, falling back to the entry DTE."""
        try:
            from datetime import date
            expiry = pos.get('expiry')
            if expiry:
                exp = date.fromisoformat(str(expiry)[:10])
                return max(0, (exp - date.today()).days)
        except Exception:
            pass
        dte = pos.get('dte_at_entry')
        try:
            return int(dte) if dte is not None else 999
        except (TypeError, ValueError):
            return 999

    def _update_price(self, pos_id: int, current_price: float):
        """Persist the latest mark for an open position."""
        try:
            with self._get_db() as conn:
                conn.execute(
                    'UPDATE sim_options_positions SET current_price=? WHERE id=?',
                    (round(float(current_price), 4), pos_id),
                )
        except Exception as exc:
            log.debug('_update_price error for id=%s: %s', pos_id, exc)

    def _close_position(self, pos_id: int, current_price: float,
                        reason: str, realized_pl: float):
        """Mark a position closed with realized P&L and exit reason."""
        try:
            with self._get_db() as conn:
                conn.execute(
                    '''UPDATE sim_options_positions
                       SET status='closed', current_price=?, exit_reason=?,
                           realized_pl=?, closed_at=datetime('now')
                       WHERE id=?''',
                    (round(float(current_price), 4), reason, realized_pl, pos_id),
                )
        except Exception as exc:
            log.error('_close_position error for id=%s: %s', pos_id, exc)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _no_trade(self, reason: str, regime: str) -> dict:
        log.debug('options no-trade [%s]: %s', regime, reason)
        return {
            'recommend':        False,
            'strategy':         'none',
            'rationale':        reason,
            'contract':         None,
            'legs':             [],
            'size_contracts':   0,
            'max_risk':         0,
            'portfolio_greeks': {},
            'greeks_warnings':  [],
            'iv_rank':          None,
            'iv_percentile':    None,
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_manager: OptionsStrategyManager | None = None


def init(db_path) -> OptionsStrategyManager:
    """Initialise the module-level OptionsStrategyManager singleton."""
    global _manager
    _manager = OptionsStrategyManager(db_path)
    return _manager


def get_manager() -> OptionsStrategyManager | None:
    """Return the current module-level singleton (or None if not yet initialised)."""
    return _manager

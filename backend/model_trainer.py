"""
ModelTrainer — statistical learning from trade outcomes.

Reads sim_trades + ai_log to build a labeled dataset of
(indicator_signals → profitable: bool) and fits a logistic regression
to learn which signals matter most in each regime.

Outputs weight multipliers stored in SQLite model_weights table,
consumed by _adaptive_weights() in app.py.

Requires 20+ trades per regime to produce meaningful weights.
Falls back to default weights if insufficient data.
"""

import datetime
import logging
import threading
import time as _t

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ModelTrainer
# ---------------------------------------------------------------------------

class ModelTrainer:
    """
    Reads sim_trades + ai_log to build a labeled dataset of
    (indicator_signals → profitable: bool) and derives per-signal weight
    multipliers using win-rate ratios (no sklearn required).

    Trained weights are persisted in a `model_weights` SQLite table
    and consumed by _adaptive_weights() in app.py.
    """

    SIGNALS     = ['rsi', 'macd', 'bb', 'volume', 'vwap', 'trend', 'stoch']
    MIN_SAMPLES = 20    # minimum trades per regime to train
    MAX_WEIGHT  = 2.5   # cap weight multipliers
    MIN_WEIGHT  = 0.2   # floor weight multipliers

    # ------------------------------------------------------------------
    # Construction / schema init
    # ------------------------------------------------------------------

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_weights_table()

    def _get_db(self):
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_weights_table(self) -> None:
        with self._get_db() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS model_weights (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    regime      TEXT    NOT NULL,
                    signal      TEXT    NOT NULL,
                    weight      REAL    NOT NULL DEFAULT 1.0,
                    sample_size INTEGER NOT NULL DEFAULT 0,
                    win_rate    REAL    NOT NULL DEFAULT 0.5,
                    trained_at  TEXT    NOT NULL DEFAULT (datetime('now'))
                )
            ''')

    # ------------------------------------------------------------------
    # Dataset construction
    # ------------------------------------------------------------------

    def _extract_features(self, reason: str) -> dict:
        """
        Parse a free-text ai_log reason field into binary signal features.

        Example reason:
            "score +3.5 | RSI at 28 is oversold. MACD bullish but no fresh crossover."
        """
        r = reason.lower() if reason else ''
        return {
            'rsi':    1 if ('rsi' in r or 'oversold' in r or 'overbought' in r) else 0,
            'macd':   1 if ('macd' in r or 'momentum' in r) else 0,
            'bb':     1 if ('bollinger' in r or 'band' in r or ' bb ' in r or r.startswith('bb ')) else 0,
            'volume': 1 if ('volume' in r or 'institutional' in r) else 0,
            'vwap':   1 if 'vwap' in r else 0,
            'trend':  1 if ('trend' in r or 'uptrend' in r or 'downtrend' in r) else 0,
            'stoch':  1 if ('stoch' in r or '%k' in r) else 0,
        }

    def _build_dataset(self, pid: int, days: int = 90) -> list:
        """
        Query sim_trades for closed positions and match each to its ai_log entry.

        Returns a list of dicts:
            {regime, label (0/1), features (dict), reason_text}
        """
        cutoff = (
            datetime.datetime.utcnow() - datetime.timedelta(days=days)
        ).strftime('%Y-%m-%d %H:%M:%S')

        dataset = []

        try:
            with self._get_db() as conn:
                # Fetch closed sell/cover trades with a realised P&L
                trades = conn.execute(
                    '''
                    SELECT id, symbol, realized_pl, created_at as closed_at
                    FROM   sim_trades
                    WHERE  portfolio_id = ?
                      AND  side         IN ('sell', 'cover')
                      AND  realized_pl  IS NOT NULL
                      AND  created_at  >= ?
                    ORDER  BY created_at ASC
                    ''',
                    (pid, cutoff),
                ).fetchall()

                for trade in trades:
                    symbol      = trade['symbol']
                    realized_pl = trade['realized_pl']
                    closed_at   = trade['closed_at']

                    # Find the most recent BUY/SHORT ai_log entry for this
                    # symbol before the trade was closed.
                    ai_row = conn.execute(
                        '''
                        SELECT reason, regime
                        FROM   ai_log
                        WHERE  portfolio_id = ?
                          AND  symbol       = ?
                          AND  action       IN ('BUY', 'SHORT')
                          AND  timestamp    <= ?
                        ORDER  BY timestamp DESC
                        LIMIT  1
                        ''',
                        (pid, symbol, closed_at),
                    ).fetchone()

                    if ai_row is None:
                        continue

                    reason = ai_row['reason'] or ''
                    regime = ai_row['regime'] or 'unknown'
                    label  = 1 if realized_pl > 0 else 0

                    dataset.append({
                        'regime':      regime,
                        'label':       label,
                        'features':    self._extract_features(reason),
                        'reason_text': reason,
                    })

        except Exception as e:
            log.error('[MODEL] _build_dataset error: %s', e)

        log.debug('[MODEL] Dataset built: %d samples (last %d days)', len(dataset), days)
        return dataset

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(self, pid: int = 1, days: int = 90) -> dict:
        """
        Main training method.

        For each regime with >= MIN_SAMPLES trades:
          1. Compute per-signal win rate when that signal was present vs absent.
          2. Weight = wr_present / wr_absent (clipped to [MIN_WEIGHT, MAX_WEIGHT]).
          3. Persist results to model_weights table.

        Returns a summary dict with status, regime weights, and sample count.
        """
        dataset = self._build_dataset(pid, days)

        if len(dataset) < self.MIN_SAMPLES:
            log.info('[MODEL] Insufficient data for training: %d samples', len(dataset))
            return {'status': 'insufficient_data', 'samples': len(dataset)}

        from collections import defaultdict
        by_regime: dict = defaultdict(list)
        for row in dataset:
            by_regime[row['regime']].append(row)

        results = {}

        for regime, rows in by_regime.items():
            if len(rows) < self.MIN_SAMPLES:
                log.debug('[MODEL] Skipping regime %r — only %d samples', regime, len(rows))
                continue

            overall_wr = sum(1 for r in rows if r['label'] == 1) / len(rows)
            regime_weights = {}

            for signal in self.SIGNALS:
                present = [r for r in rows if r['features'].get(signal, 0) == 1]
                absent  = [r for r in rows if r['features'].get(signal, 0) == 0]

                if len(present) < 5:
                    # Not enough observations for this signal — keep neutral weight
                    regime_weights[signal] = 1.0
                    continue

                wr_present = sum(1 for r in present if r['label'] == 1) / len(present)
                wr_absent  = (
                    sum(1 for r in absent if r['label'] == 1) / len(absent)
                    if absent else 0.5
                )

                # Weight = how much better (or worse) this signal performs vs baseline
                raw_weight = wr_present / max(wr_absent, 0.01)
                weight = max(self.MIN_WEIGHT, min(self.MAX_WEIGHT, raw_weight))
                regime_weights[signal] = round(weight, 3)

                log.debug(
                    '[MODEL] %s/%s: wr_present=%.1f%% wr_absent=%.1f%% → weight=%.3f',
                    regime, signal,
                    wr_present * 100, wr_absent * 100, weight,
                )

            # Persist to DB (insert new rows; get_weights reads latest)
            try:
                with self._get_db() as conn:
                    for signal, weight in regime_weights.items():
                        conn.execute(
                            '''
                            INSERT INTO model_weights
                                (regime, signal, weight, sample_size, win_rate)
                            VALUES (?, ?, ?, ?, ?)
                            ''',
                            (regime, signal, weight, len(rows), overall_wr),
                        )
            except Exception as e:
                log.error('[MODEL] Failed to save weights for regime %r: %s', regime, e)
                continue

            results[regime] = regime_weights
            log.info(
                '[MODEL] Trained regime=%r samples=%d win_rate=%.1f%%',
                regime, len(rows), overall_wr * 100,
            )

        return {
            'status':        'trained',
            'regimes':       results,
            'total_samples': len(dataset),
        }

    # ------------------------------------------------------------------
    # Weight retrieval
    # ------------------------------------------------------------------

    def get_weights(self, regime: str) -> dict:
        """
        Return the most recently trained weights for this regime.

        Falls back to all-1.0 weights if no trained data exists for the regime
        or if a DB error occurs.
        """
        default = {s: 1.0 for s in self.SIGNALS}

        try:
            with self._get_db() as conn:
                rows = conn.execute(
                    '''
                    SELECT   signal, weight
                    FROM     model_weights
                    WHERE    regime      = ?
                      AND    sample_size >= ?
                    ORDER BY trained_at  DESC
                    ''',
                    (regime, self.MIN_SAMPLES),
                ).fetchall()

            if not rows:
                return default

            # rows are ordered newest-first; use the most recent weight per signal
            seen: dict = {}
            for row in rows:
                sig = row['signal']
                if sig not in seen:
                    seen[sig] = row['weight']

            return {s: seen.get(s, 1.0) for s in self.SIGNALS}

        except Exception as e:
            log.error('[MODEL] get_weights error for regime %r: %s', regime, e)
            return default


# ---------------------------------------------------------------------------
# Module-level singleton + nightly scheduler
# ---------------------------------------------------------------------------

_trainer: 'ModelTrainer | None' = None


def init_trainer(db_path: str) -> ModelTrainer:
    """
    Initialise the module-level ModelTrainer singleton.

    Call once at application startup:
        import model_trainer
        model_trainer.init_trainer(db_path='/path/to/trades.db')
    """
    global _trainer
    _trainer = ModelTrainer(db_path)
    return _trainer


def get_trainer() -> 'ModelTrainer | None':
    """Return the module-level singleton, or None if not yet initialised."""
    return _trainer


def start_nightly_training(db_path: str, pid: int = 1) -> ModelTrainer:
    """
    Initialise the trainer and start a background thread that retrains
    weights nightly at 2 AM Eastern Time.

    Returns the ModelTrainer instance so callers can also invoke .train()
    or .get_weights() directly.
    """
    import zoneinfo

    trainer = init_trainer(db_path)

    def _loop() -> None:
        while True:
            try:
                now    = datetime.datetime.now(zoneinfo.ZoneInfo('America/New_York'))
                target = now.replace(hour=2, minute=0, second=0, microsecond=0)
                if now >= target:
                    target += datetime.timedelta(days=1)

                secs = (target - now).total_seconds()
                log.info('[MODEL] Next training in %.0f s (2AM ET)', secs)
                _t.sleep(max(60, secs))

                result = trainer.train(pid=pid, days=90)
                log.info('[MODEL] Nightly training complete: %s', result.get('status'))

            except Exception as e:
                log.error('[MODEL] Training loop error: %s', e)
                _t.sleep(3600)   # back off 1 hour on unexpected failure

    t = threading.Thread(target=_loop, daemon=True, name='model-trainer-nightly')
    t.start()
    log.info('[MODEL] Nightly trainer scheduled (2AM ET)')
    return trainer

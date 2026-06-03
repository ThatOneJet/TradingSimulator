"""
walkforward.py — honest walk-forward, out-of-sample backtest harness.

Question it answers: does this strategy have a POSITIVE average edge PER TRADE
after realistic costs? It reports the truth even when that's negative, and it
never lets the out-of-sample segment influence any choice (no curve-fitting).

It runs on an intraday DECISION TIMEFRAME (default 10-minute bars): the scanner
decides on each 10-minute bar close and fills at the next bar's open — matching
the live "10-minute scans of 10-minute ticks" cadence.

Everything reused from backtester.py so costs/signals are identical to the rest
of the system:
  - FillModel               → ATR-based slippage (atr*0.08) + commission, applied
                              identically on entry and exit, train and test
  - _compute_bar_indicators → RSI/MACD/Stoch/BB/VWAP/Volume/Trend/ATR/ADX/EMA50
  - _classify_regime / _adaptive_weights / _regime_stop_multiplier
The per-signal scoring mirrors backtester._score_bar but is toggle-aware so you
can run a STRIPPED CORE (one or two signals, everything else off).

No look-ahead: indicators for bar i use only closes[..i]; the fill is opens[i+1].
RL / adaptive live components are OFF here — they require live network state and
cannot be guaranteed leak-free in a historical replay.

Run it:
    python backend/walkforward.py                 # anchored 70/30, default universe
    python backend/walkforward.py --preset stripped_core
    python backend/walkforward.py --mode rolling --symbols SPY AAPL BTC-USD
    python backend/walkforward.py --tf 10min --lookback 59

Reports: console table, per-trade CSV (walkforward_trades.csv), and a markdown
report (walkforward_report.md). The single verdict is the OOS average trade (net)
and profit factor.
"""

import csv
import argparse
import statistics as _stats
from collections import defaultdict
from datetime import datetime

from backtester import (
    FillModel,
    _compute_bar_indicators,
    _classify_regime,
    _adaptive_weights,
    _regime_stop_multiplier,
)

# ── Config presets ──────────────────────────────────────────────────────────────
# Toggle individual signals, the adaptive weights, the entry-threshold sweep, the
# exit threshold, and (optionally) fixed stop/target ATR multipliers.

DEFAULT_UNIVERSE = ['SPY', 'AAPL', 'MSFT', 'NVDA', 'BTC-USD']

_ALL_SIGNALS = ('rsi', 'macd', 'stoch', 'volume', 'bb', 'vwap', 'trend')

FULL_SYSTEM = {
    'name': 'full_system',
    'decision_tf': '10min',
    'signals': {s: True for s in _ALL_SIGNALS},
    'use_adaptive_weights': True,
    'entry_thresholds': [2.0, 2.5, 3.0, 3.5, 4.0],
    'exit_threshold': -2.5,
    'stop_mult': None,    # None → use _regime_stop_multiplier(regime)
    'target_mult': None,
    'risk_per_trade': 0.01,
    'min_trades': 20,     # a train threshold needs this many trades to be eligible
}

# Stripped core: RSI + MACD only, flat weights, fixed stops. The simplest thing
# you can actually reason about — diagnose this before adding anything back.
STRIPPED_CORE = {
    'name': 'stripped_core',
    'decision_tf': '10min',
    'signals': {'rsi': True, 'macd': True, 'stoch': False, 'volume': False,
                'bb': False, 'vwap': False, 'trend': False},
    'use_adaptive_weights': False,
    'entry_thresholds': [1.0, 1.5, 2.0, 2.5, 3.0],
    'exit_threshold': -1.5,
    'stop_mult': 1.5,
    'target_mult': 2.5,
    'risk_per_trade': 0.01,
    'min_trades': 20,
}

PRESETS = {'full_system': FULL_SYSTEM, 'stripped_core': STRIPPED_CORE}

_WINDOW = 120   # bars of history used to compute indicators at each decision bar
_WARMUP = 60    # bars before the first trade is allowed (need MACD26/EMA50 warm)


# ── Toggle-aware scorer (mirrors backtester._score_bar, gated by config) ────────

def _score_toggled(ind: dict, cfg: dict):
    """Return (score, regime). Same per-signal contributions as
    backtester._score_bar, but each signal is included only if enabled in
    cfg['signals'], and weights are flat unless cfg['use_adaptive_weights']."""
    rsi      = float(ind.get('rsi', 50) or 50)
    macd_x   = ind.get('macd_cross', '') or ''
    stoch_k  = float(ind.get('stoch_k_val', 50) or 50)
    vol_sig  = ind.get('volume_signal', '') or ''
    vol_r    = float(ind.get('volume_ratio', 1.0) or 1.0)
    bb_pos   = ind.get('bb_position', '') or ''
    vwap_sig = ind.get('vwap_signal', '') or ''
    trend    = ind.get('trend', '') or ''
    slope    = float(ind.get('slope', 0) or 0)
    price    = float(ind.get('last_price', 0) or 0)
    ema50    = float(ind.get('ema50', price) or price)

    regime = _classify_regime(ind)
    w = _adaptive_weights(regime) if cfg['use_adaptive_weights'] \
        else {k: 1.0 for k in _ALL_SIGNALS}
    sig = cfg['signals']
    trend_penalty = 0.4 if slope < -0.05 else 1.0
    score = 0.0

    if sig.get('rsi'):
        if   rsi <= 20: raw = 3.0
        elif rsi <= 28: raw = 2.0
        elif rsi <= 38: raw = 1.0
        elif rsi >= 80: raw = -3.0
        elif rsi >= 72: raw = -2.0
        elif rsi >= 62: raw = -1.0
        else:           raw = 0.0
        score += raw * w['rsi'] * (trend_penalty if raw > 0 else 1.0)

    if sig.get('macd'):
        if   macd_x == 'bullish_cross': raw = 2.0
        elif macd_x == 'bullish':       raw = 1.0
        elif macd_x == 'bearish_cross': raw = -2.0
        elif macd_x == 'bearish':       raw = -1.0
        else:                           raw = 0.0
        score += raw * w['macd']

    if sig.get('stoch'):
        if   stoch_k <= 15: raw = 1.5
        elif stoch_k <= 25: raw = 1.0
        elif stoch_k >= 85: raw = -1.5
        elif stoch_k >= 75: raw = -1.0
        else:               raw = 0.0
        score += raw * w['stoch'] * (trend_penalty if raw > 0 else 1.0)

    if sig.get('volume'):
        vol_mult = min(vol_r / 1.5, 1.5) if vol_r > 1.5 else 1.0
        if   vol_sig == 'high_up':   raw = 2.0 * vol_mult
        elif vol_sig == 'high_down': raw = -2.0 * vol_mult
        elif vol_sig == 'low':       score *= 0.65; raw = 0.0
        else:                        raw = 0.0
        if vol_sig not in ('low', ''):
            score += raw * w['volume']

    if sig.get('bb'):
        if   bb_pos == 'oversold':   raw = 1.5
        elif bb_pos == 'lower_half': raw = 0.5
        elif bb_pos == 'overbought': raw = -1.5
        elif bb_pos == 'upper_half': raw = -0.5
        else:                        raw = 0.0
        score += raw * w['bb'] * (trend_penalty if raw > 0 else 1.0)

    if sig.get('vwap'):
        if   vwap_sig == 'above': raw = 1.0
        elif vwap_sig == 'below': raw = -1.0
        else:                     raw = 0.0
        score += raw * w['vwap']

    if sig.get('trend'):
        if   trend == 'up':   raw = 1.5
        elif trend == 'down': raw = -1.5
        else:                 raw = 0.0
        score += raw * w['trend']

    # EMA50 falling-knife gate (identical to live/backtester)
    if ema50 > 0 and price < ema50 * 0.85:
        score = min(score, 1.0)

    return round(score, 2), regime


# ── Data: intraday OHLCV resampled to the decision timeframe ────────────────────

def load_bars(symbol: str, decision_tf: str = '10min', lookback_days: int = 59):
    """Fetch 5-minute history (yfinance, ~60d max) and resample up to the decision
    timeframe. Returns a dict of parallel lists (oldest-first) or None."""
    import yfinance as yf
    days = min(int(lookback_days), 59)   # 5m data is limited to ~60 days
    df = yf.download(symbol, period=f'{days}d', interval='5m',
                     auto_adjust=True, progress=False)
    if df is None or df.empty:
        return None
    if hasattr(df.columns, 'levels'):
        df.columns = df.columns.get_level_values(0)

    tf = decision_tf if decision_tf.endswith('min') or decision_tf.endswith('h') else f'{decision_tf}min'
    if tf not in ('5min',):
        df = df.resample(tf).agg({'Open': 'first', 'High': 'max', 'Low': 'min',
                                  'Close': 'last', 'Volume': 'sum'}).dropna()
    if len(df) < _WARMUP + 10:
        return None

    return {
        'symbol':  symbol,
        'times':   [t.isoformat() for t in df.index],
        'opens':   [float(x) for x in df['Open']],
        'highs':   [float(x) for x in df['High']],
        'lows':    [float(x) for x in df['Low']],
        'closes':  [float(x) for x in df['Close']],
        'volumes': [float(x) for x in df['Volume']],
    }


# ── Replay one symbol over a bar-index slice [start, end) ───────────────────────

def replay(bars: dict, cfg: dict, entry_threshold: float,
           start: int, end: int, capital: float = 100_000.0,
           fill: FillModel = None) -> dict:
    """Long-only replay (mirrors backtester scope). Decisions on bar i close, fills
    at bar i+1 open. Indicators use bars [i-_WINDOW .. i] (all past data — legit
    even when i is in the test slice). Returns {'trades': [...], 'equity': [...]}.
    """
    fill = fill or FillModel()
    opens, highs, lows = bars['opens'], bars['highs'], bars['lows']
    closes, vols, times = bars['closes'], bars['volumes'], bars['times']
    n = len(closes)
    end = min(end, n - 1)   # need i+1 to exist for the fill

    exit_thr = cfg['exit_threshold']
    risk     = cfg['risk_per_trade']

    equity = capital
    pos = None            # dict or None
    trades = []
    equity_curve = []     # realized-equity points: (time, equity)

    i = max(start, _WARMUP)
    while i < end:
        w0 = max(0, i - _WINDOW)
        ind = _compute_bar_indicators(closes[w0:i + 1], highs[w0:i + 1],
                                      lows[w0:i + 1], vols[w0:i + 1])
        if not ind:
            i += 1
            continue
        score, regime = _score_toggled(ind, cfg)
        atr = float(ind.get('atr') or (closes[i] * 0.02))
        if cfg['stop_mult'] is not None:
            stop_m, tgt_m = cfg['stop_mult'], cfg['target_mult']
        else:
            stop_m, tgt_m = _regime_stop_multiplier(regime)

        # ── Manage an open position on THIS bar (intrabar stop/target, gap-aware) ──
        if pos is not None:
            exit_ref = None
            reason = None
            if lows[i] <= pos['stop']:
                exit_ref = min(pos['stop'], opens[i])   # gap-through fills at open
                reason = 'stop'
            elif highs[i] >= pos['target']:
                exit_ref = max(pos['target'], opens[i])
                reason = 'target'
            elif score <= exit_thr and i + 1 < n:
                exit_ref = opens[i + 1]                 # signal flip → next open
                reason = 'signal'
            if exit_ref is not None:
                exit_fill = fill.sell_price(exit_ref, pos['shares'], max(vols[i], 1), atr)
                gross = (exit_ref - pos['entry_ref']) * pos['shares']
                net   = (exit_fill - pos['entry_fill']) * pos['shares']
                equity += net
                trades.append({
                    'symbol': bars['symbol'], 'side': 'long',
                    'entry_time': pos['entry_time'], 'exit_time': times[i],
                    'entry': round(pos['entry_fill'], 4), 'exit': round(exit_fill, 4),
                    'shares': round(pos['shares'], 4),
                    'gross_pl': round(gross, 2), 'cost': round(gross - net, 2),
                    'net_pl': round(net, 2), 'regime': pos['regime'],
                    'exit_reason': reason,
                })
                equity_curve.append((times[i], round(equity, 2)))
                pos = None

        # ── Open a new position at next bar's open ──
        if pos is None and score >= entry_threshold and i + 1 < n:
            entry_ref  = opens[i + 1]
            entry_fill = fill.buy_price(entry_ref, 1, max(vols[i + 1], 1), atr)
            stop_dist  = stop_m * atr
            if stop_dist <= 0:
                stop_dist = entry_ref * 0.01
            # Risk-based sizing with a score cap (mirrors backtester)
            risk_dollars = equity * risk
            shares_raw   = risk_dollars / stop_dist
            cap_pct = 0.12 if score >= 7 else 0.10 if score >= 5 else 0.07 if score >= 3.5 else 0.05
            max_sh  = (equity * cap_pct) / entry_fill if entry_fill > 0 else 0
            shares  = round(min(shares_raw, max_sh), 6)
            if shares > 0:
                pos = {
                    'entry_ref': entry_ref, 'entry_fill': entry_fill,
                    'shares': shares, 'stop': entry_fill - stop_m * atr,
                    'target': entry_fill + tgt_m * atr, 'regime': regime,
                    'entry_time': times[i + 1],
                }
        i += 1

    # Force-close any open position at the slice's last close
    if pos is not None:
        last = min(end, n - 1)
        exit_fill = fill.sell_price(closes[last], pos['shares'], max(vols[last], 1),
                                    float(_compute_bar_indicators(
                                        closes[max(0, last - _WINDOW):last + 1],
                                        highs[max(0, last - _WINDOW):last + 1],
                                        lows[max(0, last - _WINDOW):last + 1],
                                        vols[max(0, last - _WINDOW):last + 1]).get('atr')
                                        or closes[last] * 0.02))
        net = (exit_fill - pos['entry_fill']) * pos['shares']
        gross = (closes[last] - pos['entry_ref']) * pos['shares']
        equity += net
        trades.append({
            'symbol': bars['symbol'], 'side': 'long',
            'entry_time': pos['entry_time'], 'exit_time': times[last],
            'entry': round(pos['entry_fill'], 4), 'exit': round(exit_fill, 4),
            'shares': round(pos['shares'], 4),
            'gross_pl': round(gross, 2), 'cost': round(gross - net, 2),
            'net_pl': round(net, 2), 'regime': pos['regime'], 'exit_reason': 'eod',
        })
        equity_curve.append((times[last], round(equity, 2)))

    return {'trades': trades, 'equity': equity_curve, 'final_equity': equity,
            'start_capital': capital}


# ── Metrics ─────────────────────────────────────────────────────────────────────

def metrics(trades: list, start_capital: float = 100_000.0) -> dict:
    if not trades:
        return {'trades': 0, 'win_rate': 0.0, 'avg_win': 0.0, 'avg_loss': 0.0,
                'avg_trade': 0.0, 'profit_factor': 0.0, 'total_return': 0.0,
                'max_drawdown': 0.0, 'total_net': 0.0}
    nets   = [t['net_pl'] for t in trades]
    wins   = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    gross_w = sum(wins)
    gross_l = abs(sum(losses))
    total_net = sum(nets)
    # Realized-equity drawdown from the cumulative net-P&L curve
    cum = start_capital; peak = start_capital; max_dd = 0.0
    for x in nets:
        cum += x
        peak = max(peak, cum)
        max_dd = max(max_dd, (peak - cum) / peak if peak > 0 else 0)
    return {
        'trades':        len(trades),
        'win_rate':      round(len(wins) / len(trades), 4),
        'avg_win':       round(gross_w / len(wins), 2) if wins else 0.0,
        'avg_loss':      round(-gross_l / len(losses), 2) if losses else 0.0,
        'avg_trade':     round(total_net / len(trades), 2),     # expectancy per trade, net
        'profit_factor': round(gross_w / gross_l, 3) if gross_l > 0 else float('inf'),
        'total_return':  round(total_net / start_capital, 4),
        'max_drawdown':  round(max_dd, 4),
        'total_net':     round(total_net, 2),
    }


# ── Walk-forward orchestration ──────────────────────────────────────────────────

def _tune_threshold(all_bars: list, cfg: dict, train_bounds: dict, capital: float):
    """Sweep entry thresholds on the TRAIN slice only; pick the one with the best
    average-trade (expectancy) among thresholds clearing the min-trade gate."""
    sweep = {}
    fill = FillModel()
    for thr in cfg['entry_thresholds']:
        pooled = []
        for bars in all_bars:
            s, e = train_bounds[bars['symbol']]
            pooled.extend(replay(bars, cfg, thr, s, e, capital, fill)['trades'])
        sweep[thr] = metrics(pooled, capital)
    eligible = {t: m for t, m in sweep.items() if m['trades'] >= cfg['min_trades']}
    pool = eligible or sweep
    best = max(pool, key=lambda t: (pool[t]['avg_trade'], pool[t]['profit_factor']))
    return best, sweep, bool(eligible)


def run_anchored(all_bars: list, cfg: dict, train_frac: float = 0.70,
                 capital: float = 100_000.0) -> dict:
    """Single 70/30 split: tune on the first `train_frac`, freeze, test on the rest."""
    train_bounds, test_bounds = {}, {}
    for bars in all_bars:
        n = len(bars['closes'])
        split = int(n * train_frac)
        train_bounds[bars['symbol']] = (_WARMUP, split)
        test_bounds[bars['symbol']]  = (split, n - 1)

    best_thr, sweep, had_eligible = _tune_threshold(all_bars, cfg, train_bounds, capital)

    fill = FillModel()
    is_trades, oos_trades = [], []
    for bars in all_bars:
        s, e = train_bounds[bars['symbol']]
        is_trades.extend(replay(bars, cfg, best_thr, s, e, capital, fill)['trades'])
        s, e = test_bounds[bars['symbol']]
        oos_trades.extend(replay(bars, cfg, best_thr, s, e, capital, fill)['trades'])

    return {
        'mode': 'anchored_70_30', 'chosen_threshold': best_thr,
        'had_eligible': had_eligible,
        'sweep': {str(t): m for t, m in sweep.items()},
        'in_sample': metrics(is_trades, capital),
        'out_of_sample': metrics(oos_trades, capital),
        'oos_trades': oos_trades,
    }


def run_rolling(all_bars: list, cfg: dict, n_blocks: int = 4,
                train_frac: float = 0.70, capital: float = 100_000.0) -> dict:
    """Rolling walk-forward: split each symbol into n_blocks sequential blocks;
    within each block tune on the first `train_frac` and test on the remainder
    with frozen params. Concatenate all OOS test trades into one curve."""
    is_all, oos_all = [], []
    fill = FillModel()
    block_thresholds = []
    for b in range(n_blocks):
        train_bounds, test_bounds = {}, {}
        for bars in all_bars:
            n = len(bars['closes'])
            blk = (n - _WARMUP) // n_blocks
            b0 = _WARMUP + b * blk
            b1 = _WARMUP + (b + 1) * blk if b < n_blocks - 1 else n - 1
            split = b0 + int((b1 - b0) * train_frac)
            train_bounds[bars['symbol']] = (b0, split)
            test_bounds[bars['symbol']]  = (split, b1)
        best_thr, _, _ = _tune_threshold(all_bars, cfg, train_bounds, capital)
        block_thresholds.append(best_thr)
        for bars in all_bars:
            s, e = train_bounds[bars['symbol']]
            is_all.extend(replay(bars, cfg, best_thr, s, e, capital, fill)['trades'])
            s, e = test_bounds[bars['symbol']]
            oos_all.extend(replay(bars, cfg, best_thr, s, e, capital, fill)['trades'])
    return {
        'mode': f'rolling_{n_blocks}_blocks',
        'block_thresholds': block_thresholds,
        'in_sample': metrics(is_all, capital),
        'out_of_sample': metrics(oos_all, capital),
        'oos_trades': oos_all,
    }


# ── Reporting ───────────────────────────────────────────────────────────────────

def _pf(m):
    return 'inf' if m['profit_factor'] == float('inf') else f"{m['profit_factor']:.2f}"

def _verdict(oos: dict, is_: dict, min_trades: int) -> str:
    if oos['trades'] < min_trades:
        return 'INCONCLUSIVE — too few out-of-sample trades to judge'
    if oos['avg_trade'] <= 0:
        return 'NEGATIVE — no edge; out-of-sample average trade is <= 0 after costs'
    decay = (oos['avg_trade'] / is_['avg_trade']) if is_['avg_trade'] > 0 else 0
    if oos['profit_factor'] >= 1.3 and decay >= 0.6:
        return 'POSITIVE & STABLE — edge survives out-of-sample after costs'
    return 'MARGINAL — positive but weak or decaying out-of-sample'

def _print_block(title, m):
    print(f"  {title}")
    print(f"    trades={m['trades']:<5} win%={m['win_rate']*100:5.1f}  "
          f"avg_trade(net)={'+' if m['avg_trade']>=0 else ''}{m['avg_trade']:.2f}  "
          f"PF={_pf(m)}")
    print(f"    avg_win=+{m['avg_win']:.2f}  avg_loss={m['avg_loss']:.2f}  "
          f"total_net={'+' if m['total_net']>=0 else ''}{m['total_net']:.2f}  "
          f"maxDD={m['max_drawdown']*100:.1f}%  total_return={m['total_return']*100:.2f}%")

def report(result: dict, cfg: dict, universe: list, tf: str,
           csv_path='walkforward_trades.csv', md_path='walkforward_report.md'):
    is_, oos = result['in_sample'], result['out_of_sample']
    verdict = _verdict(oos, is_, cfg['min_trades'])

    print('=' * 76)
    print(f"  WALK-FORWARD OUT-OF-SAMPLE  |  preset={cfg['name']}  tf={tf}  mode={result['mode']}")
    print('=' * 76)
    print(f"  Universe : {', '.join(universe)}")
    print(f"  Signals  : {', '.join(s for s,on in cfg['signals'].items() if on)}"
          f"   adaptive_weights={cfg['use_adaptive_weights']}")
    if 'sweep' in result:
        print('-' * 76)
        print('  IN-SAMPLE THRESHOLD SWEEP (tuning only; OOS never used to choose):')
        for t in cfg['entry_thresholds']:
            m = result['sweep'][str(t)]
            mark = '  <-- chosen' if t == result['chosen_threshold'] else ''
            gate = '' if m['trades'] >= cfg['min_trades'] else '  (too few trades)'
            print(f"    thr={t:<4} trades={m['trades']:<5} "
                  f"avg_trade={m['avg_trade']:+.2f}  PF={_pf(m)}{mark}{gate}")
    if 'chosen_threshold' in result:
        print(f"  Chosen entry threshold: {result['chosen_threshold']}")
    if 'block_thresholds' in result:
        print(f"  Per-block chosen thresholds: {result['block_thresholds']}")
    print('-' * 76)
    _print_block('IN-SAMPLE  (train):', is_)
    print()
    _print_block('OUT-OF-SAMPLE  (test, frozen params):', oos)
    print('-' * 76)
    if is_['avg_trade'] > 0:
        print(f"  Decay  OOS/IS avg_trade = {oos['avg_trade']/is_['avg_trade']:.2f}   "
              f"(1.0 = none, <0 = edge flips negative)")
    print(f"  >>> OOS average trade (net): {oos['avg_trade']:+.2f}   "
          f"OOS profit factor: {_pf(oos)}")
    print(f"  VERDICT: {verdict}")
    print('=' * 76)

    # Per-trade CSV (out-of-sample)
    cols = ['symbol', 'side', 'entry_time', 'exit_time', 'entry', 'exit', 'shares',
            'gross_pl', 'cost', 'net_pl', 'regime', 'exit_reason']
    with open(csv_path, 'w', newline='') as f:
        wr = csv.DictWriter(f, fieldnames=cols)
        wr.writeheader()
        for t in result['oos_trades']:
            wr.writerow(t)
    print(f"  Saved {len(result['oos_trades'])} OOS trades -> {csv_path}")

    # Markdown report
    def md_metrics(m):
        return (f"| trades | {m['trades']} |\n| win rate | {m['win_rate']*100:.1f}% |\n"
                f"| avg trade (net) | {m['avg_trade']:+.2f} |\n| profit factor | {_pf(m)} |\n"
                f"| avg win | +{m['avg_win']:.2f} |\n| avg loss | {m['avg_loss']:.2f} |\n"
                f"| total net | {m['total_net']:+.2f} |\n| max drawdown | {m['max_drawdown']*100:.1f}% |\n"
                f"| total return | {m['total_return']*100:.2f}% |\n")
    with open(md_path, 'w') as f:
        f.write(f"# Walk-forward out-of-sample report\n\n")
        f.write(f"- Preset: **{cfg['name']}**  |  Timeframe: **{tf}**  |  Mode: **{result['mode']}**\n")
        f.write(f"- Universe: {', '.join(universe)}\n")
        f.write(f"- Signals on: {', '.join(s for s,on in cfg['signals'].items() if on)} "
                f"(adaptive weights: {cfg['use_adaptive_weights']})\n\n")
        f.write(f"## In-sample (train)\n\n| metric | value |\n|---|---|\n{md_metrics(is_)}\n")
        f.write(f"## Out-of-sample (test, frozen params)\n\n| metric | value |\n|---|---|\n{md_metrics(oos)}\n")
        f.write(f"## Verdict\n\n**{verdict}**\n\n")
        f.write(f"OOS average trade (net): **{oos['avg_trade']:+.2f}**, "
                f"OOS profit factor: **{_pf(oos)}**.\n")
    print(f"  Saved report -> {md_path}")
    return verdict


# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description='Walk-forward out-of-sample harness')
    ap.add_argument('--preset', choices=list(PRESETS), default='full_system')
    ap.add_argument('--symbols', nargs='+', default=DEFAULT_UNIVERSE)
    ap.add_argument('--tf', default=None, help='decision timeframe (e.g. 10min, 15min, 1h)')
    ap.add_argument('--lookback', type=int, default=59, help='days of 5m history (max ~59)')
    ap.add_argument('--mode', choices=['anchored', 'rolling'], default='anchored')
    ap.add_argument('--blocks', type=int, default=4)
    ap.add_argument('--capital', type=float, default=100_000)
    args = ap.parse_args()

    cfg = dict(PRESETS[args.preset])
    cfg['signals'] = dict(cfg['signals'])
    if args.tf:
        cfg['decision_tf'] = args.tf
    tf = cfg['decision_tf']

    print(f"Loading {len(args.symbols)} symbols @ {tf} ({args.lookback}d of 5m history)...")
    all_bars = []
    for sym in args.symbols:
        try:
            b = load_bars(sym, tf, args.lookback)
            if b:
                all_bars.append(b)
                print(f"  {sym}: {len(b['closes'])} {tf} bars")
            else:
                print(f"  {sym}: insufficient data — skipped")
        except Exception as e:
            print(f"  {sym}: load error — {e}")
    if not all_bars:
        print("No data loaded. Intraday history is limited to ~60 days; check symbols/network.")
        return

    if args.mode == 'anchored':
        result = run_anchored(all_bars, cfg, capital=args.capital)
    else:
        result = run_rolling(all_bars, cfg, n_blocks=args.blocks, capital=args.capital)

    report(result, cfg, [b['symbol'] for b in all_bars], tf)


if __name__ == '__main__':
    main()

"""
Walk-forward optimisation CLI — the honest measurement harness.

Tunes the strategy's entry threshold on an in-sample slice of history, then
measures the chosen value on a later, never-touched out-of-sample slice, and
prints net expectancy per trade, profit factor, max drawdown, and the decay
between in-sample and out-of-sample. This is how a change becomes a measured
decision instead of a vibe.

Usage:
    python walkforward_cli.py
    python walkforward_cli.py --symbols AAPL MSFT SPY QQQ --train-days 540 --test-days 180
    python walkforward_cli.py --train-start 2024-01-01 --train-end 2024-12-31 \
                              --test-start 2025-01-01 --test-end 2025-06-30

Run it before and after every structural change (slow-clock, cluster cap, etc.)
and watch whether out-of-sample expectancy actually moves.
"""

import argparse
from datetime import date, timedelta

from backtester import walk_forward_optimize

# A focused, liquid, lower-correlation default universe (reviewer item #4) —
# not 80 symbols. Mix of large-cap equity, an index, and a couple of uncorrelated
# names so the pooled test isn't just one beta.
DEFAULT_SYMBOLS = ['SPY', 'AAPL', 'MSFT', 'NVDA', 'JPM', 'XOM', 'UNH', 'BTC-USD']


def _fmt_money(x):
    if x is None:
        return '   n/a'
    return f"{'+' if x >= 0 else '-'}${abs(x):,.2f}"


def _fmt_metrics(m: dict) -> str:
    pf = m['profit_factor']
    pf_s = 'inf' if pf == float('inf') else f'{pf:.2f}'
    return (
        f"    trades={m['total_trades']:<4}  win%={m['win_rate']*100:5.1f}  "
        f"expectancy/trade={_fmt_money(m['expectancy'])}  PF={pf_s}\n"
        f"    total P&L={_fmt_money(m['total_pl'])}  "
        f"avg win={_fmt_money(m['avg_win'])}  avg loss={_fmt_money(m['avg_loss'])}  "
        f"maxDD={_fmt_money(m['max_drawdown'])}"
    )


def main():
    ap = argparse.ArgumentParser(description='Walk-forward optimisation harness')
    ap.add_argument('--symbols', nargs='+', default=DEFAULT_SYMBOLS)
    ap.add_argument('--train-start')
    ap.add_argument('--train-end')
    ap.add_argument('--test-start')
    ap.add_argument('--test-end')
    ap.add_argument('--train-days', type=int, default=540,
                    help='if explicit dates omitted: train window length (days)')
    ap.add_argument('--test-days', type=int, default=180,
                    help='if explicit dates omitted: test window length (days)')
    ap.add_argument('--thresholds', nargs='+', type=float,
                    default=[2.0, 2.5, 3.0, 3.5, 4.0])
    ap.add_argument('--capital', type=float, default=100_000)
    args = ap.parse_args()

    # Derive contiguous train->test windows ending today if explicit dates absent.
    if not (args.train_start and args.test_end):
        today = date.today()
        test_end    = today
        test_start  = today - timedelta(days=args.test_days)
        train_end   = test_start - timedelta(days=1)
        train_start = train_end - timedelta(days=args.train_days)
        args.train_start = args.train_start or train_start.isoformat()
        args.train_end   = args.train_end   or train_end.isoformat()
        args.test_start  = args.test_start  or test_start.isoformat()
        args.test_end    = args.test_end    or test_end.isoformat()

    print('=' * 72)
    print('  WALK-FORWARD OPTIMISATION  (tune in-sample -> validate out-of-sample)')
    print('=' * 72)
    print(f"  Symbols : {', '.join(args.symbols)}")
    print(f"  Train   : {args.train_start} -> {args.train_end}")
    print(f"  Test    : {args.test_start} -> {args.test_end}  (never seen during tuning)")
    print(f"  Sweep   : entry thresholds {args.thresholds}")
    print('-' * 72)
    print('  Running... (downloading history + replaying each symbol per threshold)')

    res = walk_forward_optimize(
        args.symbols, args.train_start, args.train_end,
        args.test_start, args.test_end,
        thresholds=tuple(args.thresholds), capital=args.capital,
    )

    print('-' * 72)
    min_tr = res['min_trades']
    print(f"  IN-SAMPLE THRESHOLD SWEEP (tuning; need >={min_tr} trades to be eligible,")
    print(f"  so high thresholds with tiny samples can't be cherry-picked):")
    for thr in args.thresholds:
        m = res['train_sweep'][str(thr)]
        mark = '  <-- chosen' if thr == res['chosen_threshold'] else ''
        gate = '' if m['total_trades'] >= min_tr else '  (too few trades — ineligible)'
        pf = m['profit_factor']; pf_s = 'inf' if pf == float('inf') else f'{pf:.2f}'
        print(f"    thr={thr:<4} trades={m['total_trades']:<4} "
              f"exp/trade={_fmt_money(m['expectancy'])}  PF={pf_s}{mark}{gate}")

    print('-' * 72)
    print(f"  CHOSEN THRESHOLD: {res['chosen_threshold']}")
    print()
    print('  IN-SAMPLE  (train, tuned):')
    print(_fmt_metrics(res['in_sample']))
    print()
    print('  OUT-OF-SAMPLE  (test, untouched):')
    print(_fmt_metrics(res['out_of_sample']))
    print('-' * 72)
    d = res['decay']
    er = d['expectancy_ratio']
    print(f"  DECAY  expectancy OOS/IS = {er}   "
          f"(1.0 = no decay, <0 = edge flips negative)")
    print(f"  VERDICT: {res['verdict']}")
    print('=' * 72)


if __name__ == '__main__':
    main()

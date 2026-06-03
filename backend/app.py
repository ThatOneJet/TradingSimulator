import os, threading, sqlite3, time as _time, json as _json, csv, io, hashlib, random, math, logging, warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)  # suppress Eventlet deprecation
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory
from flask_socketio import SocketIO
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

# ── Logging — only show WARNING+ in terminal; silence noisy libraries ─────────
logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(name)s: %(message)s')
for _noisy in ('werkzeug', 'engineio', 'socketio', 'urllib3', 'yfinance',
               'peewee', 'alpaca', 'websocket', 'asyncio'):
    logging.getLogger(_noisy).setLevel(logging.ERROR)

# ── Optional Alpaca clients (data feeds only — portfolio is handled locally) ───
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

API_KEY    = os.getenv('ALPACA_API_KEY',    '')
SECRET_KEY = os.getenv('ALPACA_SECRET_KEY', '')
AV_KEY     = os.getenv('ALPHA_VANTAGE_KEY', '')
POLYGON_KEY  = os.getenv('POLYGON_KEY',  '')
FINNHUB_KEY  = os.getenv('FINNHUB_KEY',  '')

KEYS_SET         = bool(API_KEY and SECRET_KEY
                        and API_KEY    != 'your_api_key_here'
                        and SECRET_KEY != 'your_secret_key_here')
AV_KEYS_SET      = bool(AV_KEY      and AV_KEY      != 'your_alpha_vantage_key_here')
POLYGON_KEYS_SET = bool(POLYGON_KEY  and POLYGON_KEY != 'your_polygon_key_here')
FINNHUB_KEYS_SET = bool(FINNHUB_KEY  and FINNHUB_KEY != 'your_finnhub_key_here')

app      = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}, r"/socket.io/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Data clients (optional — for real-time bars/quotes)
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY) if KEYS_SET else None

# ── Database ───────────────────────────────────────────────────────────────────
DB_PATH = Path(__file__).parent / 'holdings.db'

def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _init_db():
    with _get_db() as conn:
        # Personal holdings tracker (unchanged)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS holdings (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol     TEXT    NOT NULL,
                shares     REAL    NOT NULL,
                buy_date   TEXT    NOT NULL,
                buy_price  REAL    NOT NULL,
                note       TEXT,
                created_at TEXT    DEFAULT (datetime('now'))
            )
        ''')
        # Simulation portfolio
        conn.execute('''
            CREATE TABLE IF NOT EXISTS sim_state (
                id           INTEGER PRIMARY KEY,
                cash         REAL    NOT NULL DEFAULT 100000.0,
                initial_cash REAL    NOT NULL DEFAULT 100000.0,
                last_equity  REAL    NOT NULL DEFAULT 100000.0,
                reset_at     TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS sim_positions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol      TEXT NOT NULL,
                shares      REAL NOT NULL DEFAULT 0,
                avg_cost    REAL NOT NULL DEFAULT 0,
                realized_pl REAL NOT NULL DEFAULT 0,
                portfolio_id INTEGER NOT NULL DEFAULT 1
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS sim_trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol      TEXT    NOT NULL,
                side        TEXT    NOT NULL,
                qty         REAL    NOT NULL,
                price       REAL    NOT NULL,
                filled_qty  REAL    NOT NULL DEFAULT 0,
                status      TEXT    NOT NULL DEFAULT 'filled',
                order_type  TEXT    NOT NULL DEFAULT 'market',
                limit_price REAL,
                realized_pl REAL    NOT NULL DEFAULT 0,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        ''')
        conn.execute('INSERT OR IGNORE INTO sim_state (id) VALUES (1)')

        # Users table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                username     TEXT    NOT NULL UNIQUE,
                pw_hash      TEXT    NOT NULL,
                display_name TEXT,
                avatar_color TEXT    NOT NULL DEFAULT '#ff6a1a',
                created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        ''')

        # Portfolios table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS portfolios (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                name       TEXT    NOT NULL DEFAULT 'Main Portfolio',
                color      TEXT    NOT NULL DEFAULT '#ff6a1a',
                created_at TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        ''')

        # Safe migration: add portfolio_id to existing sim tables (ignore if column already exists)
        for tbl in ('sim_state', 'sim_positions', 'sim_trades'):
            try:
                conn.execute(f'ALTER TABLE {tbl} ADD COLUMN portfolio_id INTEGER NOT NULL DEFAULT 1')
            except Exception:
                pass  # column already exists

        # Per-portfolio watchlist table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS watchlist_items (
                portfolio_id INTEGER NOT NULL,
                symbol       TEXT    NOT NULL,
                PRIMARY KEY (portfolio_id, symbol)
            )
        ''')

        # Seed default user and portfolio so existing data still works
        conn.execute("INSERT OR IGNORE INTO users (id, username, pw_hash, display_name) VALUES (1, 'default', '', 'Default')")
        conn.execute("INSERT OR IGNORE INTO portfolios (id, user_id, name) VALUES (1, 1, 'Main Portfolio')")

        # Ensure sim_state row 1 has portfolio_id = 1
        conn.execute("UPDATE sim_state SET portfolio_id = 1 WHERE id = 1 AND portfolio_id != 1")

        try:
            conn.execute('ALTER TABLE sim_trades ADD COLUMN fill_price REAL')
        except Exception:
            pass
        try:
            conn.execute('ALTER TABLE sim_trades ADD COLUMN slippage_cost REAL')
        except Exception:
            pass
        try:
            conn.execute('ALTER TABLE sim_positions ADD COLUMN stop_price REAL')
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE sim_positions ADD COLUMN created_at TEXT")
        except Exception:
            pass

        # Signal history — tracks per-symbol state for "what changed?" detection
        conn.execute('''
            CREATE TABLE IF NOT EXISTS signal_history (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol       TEXT    NOT NULL,
                portfolio_id INTEGER NOT NULL DEFAULT 0,
                score        REAL,
                market_state TEXT,
                rsi          REAL,
                macd_cross   TEXT,
                trend        TEXT,
                bb_position  TEXT,
                volume_signal TEXT,
                recorded_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        ''')

        # Safe migration: add priority column if not present
        try:
            conn.execute('ALTER TABLE watchlist_items ADD COLUMN priority INTEGER NOT NULL DEFAULT 0')
        except Exception:
            pass

        # Safe migration: AI-controlled flag on portfolios
        try:
            conn.execute('ALTER TABLE portfolios ADD COLUMN ai_controlled INTEGER NOT NULL DEFAULT 0')
        except Exception:
            pass

        # Migration: fix sim_positions unique constraint (old schema had UNIQUE on symbol alone;
        # must be UNIQUE on (symbol, portfolio_id) to allow multiple portfolios to hold the same stock)
        try:
            conn.execute("INSERT INTO sim_positions (symbol, shares, avg_cost, portfolio_id) VALUES ('__chk__', 0, 0, 1)")
            conn.execute("INSERT INTO sim_positions (symbol, shares, avg_cost, portfolio_id) VALUES ('__chk__', 0, 0, 2)")
            conn.execute("DELETE FROM sim_positions WHERE symbol = '__chk__'")
        except Exception:
            # UNIQUE constraint on symbol alone — rebuild without it
            conn.execute('''
                CREATE TABLE sim_positions_new (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol       TEXT    NOT NULL,
                    shares       REAL    NOT NULL DEFAULT 0,
                    avg_cost     REAL    NOT NULL DEFAULT 0,
                    realized_pl  REAL    NOT NULL DEFAULT 0,
                    portfolio_id INTEGER NOT NULL DEFAULT 1
                )
            ''')
            conn.execute('INSERT INTO sim_positions_new (symbol, shares, avg_cost, realized_pl, portfolio_id) SELECT symbol, shares, avg_cost, realized_pl, portfolio_id FROM sim_positions')
            conn.execute('DROP TABLE sim_positions')
            conn.execute('ALTER TABLE sim_positions_new RENAME TO sim_positions')

        # AI trade log
        conn.execute('''
            CREATE TABLE IF NOT EXISTS ai_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                portfolio_id INTEGER NOT NULL,
                symbol       TEXT    NOT NULL,
                action       TEXT    NOT NULL,
                score        REAL,
                price        REAL,
                shares       REAL,
                reason       TEXT,
                created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        ''')

        # AI scan run history
        conn.execute('''
            CREATE TABLE IF NOT EXISTS ai_scan_runs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                portfolio_id INTEGER NOT NULL,
                scanned      INTEGER DEFAULT 0,
                bought_count INTEGER DEFAULT 0,
                sold_count   INTEGER DEFAULT 0,
                error_count  INTEGER DEFAULT 0,
                bought_json  TEXT,
                sold_json    TEXT,
                batch_json   TEXT,
                created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        ''')

        # Seed default watchlist for portfolio 1
        for _sym in ('AAPL', 'TSLA', 'NVDA', 'SPY'):
            conn.execute('INSERT OR IGNORE INTO watchlist_items (portfolio_id, symbol) VALUES (1, ?)', (_sym,))

        # Migrations: add columns introduced after initial schema
        for _col, _defn in [
            ('mode',        "TEXT DEFAULT 'full'"),
            ('skip_reason', 'TEXT'),
        ]:
            try:
                conn.execute(f'ALTER TABLE ai_scan_runs ADD COLUMN {_col} {_defn}')
            except Exception:
                pass  # column already exists

        try:
            conn.execute("ALTER TABLE ai_scan_runs ADD COLUMN history_context TEXT")
        except Exception:
            pass  # column already exists
        try:
            conn.execute("ALTER TABLE ai_scan_runs ADD COLUMN skipped_json TEXT")
        except Exception:
            pass  # column already exists

        conn.execute('''
            CREATE TABLE IF NOT EXISTS sim_options_positions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                portfolio_id    INTEGER NOT NULL DEFAULT 1,
                underlying      TEXT    NOT NULL,
                symbol          TEXT    NOT NULL,
                strategy        TEXT    NOT NULL,
                side            TEXT    NOT NULL DEFAULT 'long',
                contracts       INTEGER NOT NULL DEFAULT 1,
                entry_price     REAL    NOT NULL,
                current_price   REAL    NOT NULL DEFAULT 0,
                delta           REAL,
                gamma           REAL,
                theta           REAL,
                vega            REAL,
                iv_at_entry     REAL,
                strike          REAL    NOT NULL,
                expiry          TEXT    NOT NULL,
                dte_at_entry    INTEGER,
                status          TEXT    NOT NULL DEFAULT 'open',
                exit_reason     TEXT,
                realized_pl     REAL    NOT NULL DEFAULT 0,
                opened_at       TEXT    NOT NULL DEFAULT (datetime('now')),
                closed_at       TEXT
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS iv_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol      TEXT NOT NULL,
                iv          REAL NOT NULL,
                recorded_at TEXT NOT NULL DEFAULT (date('now'))
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS ix_iv_sym ON iv_history(symbol, recorded_at)')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS ai_decisions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                portfolio_id INTEGER NOT NULL,
                symbol       TEXT NOT NULL,
                decision     TEXT NOT NULL,
                score        REAL,
                regime       TEXT,
                reason       TEXT,
                detail       TEXT,
                quality_score REAL,
                size_mult    REAL,
                signal_json  TEXT,
                created_at   TEXT NOT NULL DEFAULT (datetime('now'))
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS ix_aid_pid ON ai_decisions(portfolio_id, created_at)')

_init_db()

# in-memory watchlist
_watchlist: list[str] = ['AAPL', 'TSLA', 'NVDA', 'SPY']

# ── Price / quote cache ────────────────────────────────────────────────────────
_price_cache: dict[str, tuple[float, float]] = {}
_PRICE_TTL = 30
_quote_cache: dict[str, tuple[dict, float]] = {}
_QUOTE_TTL  = 60
_earnings_cache: dict[str, tuple[int | None, float]] = {}  # {symbol: (days_to_earnings, ts)}
EARNINGS_CACHE_TTL = 3600  # 1 hour
_subscribed_symbols: set = set()
_stream_manager    = None  # set in __main__ after StreamManager is instantiated
_candle_engine     = None  # set in __main__ after CandleEngine is instantiated
_structure_engine  = None  # set in __main__ after StructureEngine is instantiated
_portfolio_analytics = None  # set in __main__ after PortfolioAnalytics is instantiated
_perf_engine       = None  # set in __main__ after PerformanceEngine is instantiated

def _fetch_price_live(symbol: str) -> float:
    # Always use yfinance for simulation prices — no Alpaca dependency
    return _quote_yfinance(symbol)['bid']

def _get_crypto_price(symbol: str) -> float | None:
    """Get current crypto price from Coinbase REST API (no key, US-accessible)."""
    try:
        import urllib.request, json as _json
        # Convert BTC-USD → BTC-USD (Coinbase uses same format)
        cb_sym = symbol  # e.g. BTC-USD
        url = f'https://api.coinbase.com/v2/prices/{cb_sym}/spot'
        req = urllib.request.Request(url, headers={'CB-VERSION': '2016-02-18'})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = _json.loads(r.read())
            return float(data['data']['amount'])
    except Exception:
        return None


def _get_current_price(symbol: str) -> float:
    # For crypto: try Coinbase REST first (reliable, no key, US-accessible)
    if symbol.endswith('-USD'):
        cb_price = _get_crypto_price(symbol)
        if cb_price and cb_price > 0:
            return cb_price

    now = _time.time()
    if symbol in _price_cache:
        price, ts = _price_cache[symbol]
        if now - ts < _PRICE_TTL:
            return price
    price = _fetch_price_live(symbol)
    _price_cache[symbol] = (price, now)
    return price

# ── Portfolio simulation helpers ───────────────────────────────────────────────
def _sim_state(portfolio_id: int = 1) -> dict:
    with _get_db() as conn:
        row = conn.execute('SELECT * FROM sim_state WHERE portfolio_id = ?', (portfolio_id,)).fetchone()
        if not row:
            # Auto-create sim_state for this portfolio
            conn.execute(
                'INSERT INTO sim_state (cash, initial_cash, last_equity, portfolio_id) VALUES (100000,100000,100000,?)',
                (portfolio_id,)
            )
            row = conn.execute('SELECT * FROM sim_state WHERE portfolio_id = ?', (portfolio_id,)).fetchone()
        return dict(row)

_COMMISSION_PER_SHARE = 0.005   # $0.005/share (Alpaca-like tiered rate)
_COMMISSION_MIN       = 1.00    # $1 minimum per order

def _apply_slippage(price, side, atr_val, volume_ratio=1.0, qty=1.0):
    base_slip = atr_val * 0.08
    if volume_ratio < 0.5:
        base_slip *= 2.0
    noise = random.uniform(0.8, 1.2)
    slip  = base_slip * noise
    # Per-order commission spread into per-share cost
    commission = max(_COMMISSION_MIN, qty * _COMMISSION_PER_SHARE) / max(qty, 1)
    total_slip = slip + commission
    # buy + cover = pay the ask (price rises); sell + short = receive the bid (price falls)
    return round(price + total_slip, 4) if side in ('buy', 'cover') else round(price - total_slip, 4)

def _sim_buy(symbol: str, qty: float, price: float, portfolio_id: int = 1, record: bool = True):
    cost = qty * price
    with _get_db() as conn:
        state = conn.execute('SELECT cash FROM sim_state WHERE portfolio_id = ?', (portfolio_id,)).fetchone()
        if not state:
            # Auto-create
            conn.execute(
                'INSERT INTO sim_state (cash, initial_cash, last_equity, portfolio_id) VALUES (100000,100000,100000,?)',
                (portfolio_id,)
            )
            state = conn.execute('SELECT cash FROM sim_state WHERE portfolio_id = ?', (portfolio_id,)).fetchone()
        if cost > state['cash']:
            raise ValueError(f'Insufficient cash: need ${cost:.2f}, have ${state["cash"]:.2f}')
        conn.execute('UPDATE sim_state SET cash = cash - ? WHERE portfolio_id = ?', (cost, portfolio_id))
        existing = conn.execute(
            'SELECT shares, avg_cost FROM sim_positions WHERE symbol = ? AND portfolio_id = ?',
            (symbol, portfolio_id)
        ).fetchone()
        if existing:
            total_shares = existing['shares'] + qty
            new_avg      = (existing['shares'] * existing['avg_cost'] + qty * price) / total_shares
            conn.execute(
                'UPDATE sim_positions SET shares = ?, avg_cost = ? WHERE symbol = ? AND portfolio_id = ?',
                (total_shares, new_avg, symbol, portfolio_id)
            )
        else:
            conn.execute(
                "INSERT INTO sim_positions (symbol, shares, avg_cost, realized_pl, portfolio_id, created_at) VALUES (?,?,?,0,?,datetime('now'))",
                (symbol, qty, price, portfolio_id)
            )
        # Auto-add to watchlist so positions always appear in the watchlist
        conn.execute(
            'INSERT OR IGNORE INTO watchlist_items (portfolio_id, symbol) VALUES (?,?)',
            (portfolio_id, symbol)
        )
        # Record in trade history so AI buys appear alongside manual trades
        if record:
            conn.execute(
                'INSERT INTO sim_trades (symbol, side, qty, price, filled_qty, status, order_type, realized_pl, portfolio_id, fill_price, slippage_cost) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (symbol, 'buy', qty, price, qty, 'filled', 'market', 0, portfolio_id, price, 0)
            )

def _sim_sell(symbol: str, qty: float, price: float, portfolio_id: int = 1, record: bool = True) -> float:
    with _get_db() as conn:
        pos = conn.execute(
            'SELECT shares, avg_cost FROM sim_positions WHERE symbol = ? AND portfolio_id = ?',
            (symbol, portfolio_id)
        ).fetchone()
        if not pos or pos['shares'] < qty - 0.0001:
            have = pos['shares'] if pos else 0
            raise ValueError(f'Insufficient shares: need {qty}, have {have:.4f}')
        realized_pl = (price - pos['avg_cost']) * qty
        proceeds     = qty * price
        conn.execute('UPDATE sim_state SET cash = cash + ? WHERE portfolio_id = ?', (proceeds, portfolio_id))
        new_shares = pos['shares'] - qty
        if new_shares < 0.0001:
            conn.execute(
                'DELETE FROM sim_positions WHERE symbol = ? AND portfolio_id = ?',
                (symbol, portfolio_id)
            )
        else:
            conn.execute(
                'UPDATE sim_positions SET shares = ?, realized_pl = realized_pl + ? WHERE symbol = ? AND portfolio_id = ?',
                (new_shares, realized_pl, symbol, portfolio_id)
            )
        # Record in trade history
        if record:
            conn.execute(
                'INSERT INTO sim_trades (symbol, side, qty, price, filled_qty, status, order_type, realized_pl, portfolio_id, fill_price, slippage_cost) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (symbol, 'sell', qty, price, qty, 'filled', 'market', realized_pl, portfolio_id, price, 0)
            )
        return realized_pl

def _sim_short(symbol: str, qty: float, price: float, portfolio_id: int = 1, record: bool = True):
    """Open a short position — credits proceeds to cash, stores negative shares."""
    proceeds = qty * price
    with _get_db() as conn:
        state = conn.execute('SELECT cash FROM sim_state WHERE portfolio_id = ?', (portfolio_id,)).fetchone()
        if not state:
            conn.execute(
                'INSERT INTO sim_state (cash, initial_cash, last_equity, portfolio_id) VALUES (100000,100000,100000,?)',
                (portfolio_id,)
            )
        # Short margin: require at least 50% of position value as collateral
        if state and proceeds * 0.5 > state['cash']:
            raise ValueError(f'Insufficient margin for short: need ${proceeds*0.5:.2f} collateral, have ${state["cash"]:.2f}')
        # Credit proceeds (will be debited when covering)
        conn.execute('UPDATE sim_state SET cash = cash + ? WHERE portfolio_id = ?', (proceeds, portfolio_id))
        existing = conn.execute(
            'SELECT shares, avg_cost FROM sim_positions WHERE symbol = ? AND portfolio_id = ?',
            (symbol, portfolio_id)
        ).fetchone()
        if existing:
            if existing['shares'] > 0:
                raise ValueError(f'Already long {symbol} — close long before shorting')
            # Add to existing short
            total = existing['shares'] - qty   # more negative
            new_avg = (abs(existing['shares']) * existing['avg_cost'] + qty * price) / abs(total)
            conn.execute(
                'UPDATE sim_positions SET shares = ?, avg_cost = ? WHERE symbol = ? AND portfolio_id = ?',
                (total, new_avg, symbol, portfolio_id)
            )
        else:
            conn.execute(
                'INSERT INTO sim_positions (symbol, shares, avg_cost, realized_pl, portfolio_id) VALUES (?,?,?,0,?)',
                (symbol, -qty, price, portfolio_id)
            )
        conn.execute('INSERT OR IGNORE INTO watchlist_items (portfolio_id, symbol) VALUES (?,?)', (portfolio_id, symbol))
        if record:
            conn.execute(
                'INSERT INTO sim_trades (symbol, side, qty, price, filled_qty, status, order_type, realized_pl, portfolio_id, fill_price, slippage_cost) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (symbol, 'short', qty, price, qty, 'filled', 'market', 0, portfolio_id, price, 0)
            )


def _sim_cover(symbol: str, qty: float, price: float, portfolio_id: int = 1, record: bool = True) -> float:
    """Close (cover) a short position — debits cash to buy back shares."""
    with _get_db() as conn:
        pos = conn.execute(
            'SELECT shares, avg_cost FROM sim_positions WHERE symbol = ? AND portfolio_id = ?',
            (symbol, portfolio_id)
        ).fetchone()
        if not pos or pos['shares'] >= 0:
            raise ValueError(f'No short position in {symbol}')
        short_qty = abs(pos['shares'])
        if qty > short_qty + 0.0001:
            raise ValueError(f'Cover qty {qty} exceeds short {short_qty:.4f}')
        # Profit = (entry_price - cover_price) * qty  (shorted high, covered low)
        realized_pl = (pos['avg_cost'] - price) * qty
        cost = qty * price
        cash_state = conn.execute('SELECT cash FROM sim_state WHERE portfolio_id = ?', (portfolio_id,)).fetchone()
        if cash_state and cost > cash_state['cash']:
            raise ValueError(f'Insufficient cash to cover: need ${cost:.2f}, have ${cash_state["cash"]:.2f}')
        conn.execute('UPDATE sim_state SET cash = cash - ? WHERE portfolio_id = ?', (cost, portfolio_id))
        remaining = pos['shares'] + qty   # shares is negative, adding qty makes it less negative
        if abs(remaining) < 0.0001:
            conn.execute('DELETE FROM sim_positions WHERE symbol = ? AND portfolio_id = ?', (symbol, portfolio_id))
        else:
            conn.execute(
                'UPDATE sim_positions SET shares = ?, realized_pl = realized_pl + ? WHERE symbol = ? AND portfolio_id = ?',
                (remaining, realized_pl, symbol, portfolio_id)
            )
        if record:
            conn.execute(
                'INSERT INTO sim_trades (symbol, side, qty, price, filled_qty, status, order_type, realized_pl, portfolio_id, fill_price, slippage_cost) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (symbol, 'cover', qty, price, qty, 'filled', 'market', realized_pl, portfolio_id, price, 0)
            )
        return realized_pl


def _real_holdings_with_prices() -> list[dict]:
    with _get_db() as conn:
        rows = conn.execute(
            'SELECT symbol, shares, buy_price FROM holdings WHERE shares > 0'
        ).fetchall()
    out = []
    for row in rows:
        symbol = row['symbol']
        qty    = float(row['shares'])
        avg    = float(row['buy_price'])
        price  = _get_current_price(symbol)
        prev_close = None
        try:
            if FINNHUB_KEYS_SET:
                q = _quote_finnhub(symbol)
                price      = q['bid']
                prev_close = q.get('prev_close')
        except Exception:
            pass
        mv    = price * qty
        upl   = (price - avg) * qty
        day_pl = round((price - prev_close) * qty, 2) if prev_close and prev_close > 0 else None
        out.append({
            'symbol':          symbol,
            'qty':             qty,
            'avg_entry_price': avg,
            'current_price':   price,
            'market_value':    round(mv, 2),
            'unrealized_pl':   round(upl, 2),
            'unrealized_plpc': (upl / (avg * qty)) if avg and qty else 0,
            'side':            'long',
            'day_pl':          day_pl,
            'is_real':         True,
        })
    return out

def _sim_positions_with_prices(portfolio_id: int = 1) -> list[dict]:
    with _get_db() as conn:
        rows = conn.execute(
            'SELECT * FROM sim_positions WHERE ABS(shares) > 0.0001 AND portfolio_id = ?',
            (portfolio_id,)
        ).fetchall()
    out = []
    for row in rows:
        price    = _get_current_price(row['symbol'])
        qty      = row['shares']        # negative for shorts
        avg      = row['avg_cost']
        is_short = qty < 0
        abs_qty  = abs(qty)
        # market_value: positive for longs, NEGATIVE for shorts.
        # For equity = cash + sum(market_value):
        #   cash already includes short proceeds received, so subtracting the
        #   short market value gives the correct net equity (avoids double-counting).
        mv       = price * abs_qty if not is_short else -(price * abs_qty)
        # Long P&L: (price - avg) * abs_qty.  Short P&L: (avg - price) * abs_qty
        upl      = (price - avg) * abs_qty if not is_short else (avg - price) * abs_qty
        out.append({
            'symbol':          row['symbol'],
            'qty':             qty,
            'avg_entry_price': avg,
            'current_price':   price,
            'market_value':    mv,
            'unrealized_pl':   upl,
            'unrealized_plpc': (upl / (avg * abs_qty)) if avg and abs_qty else 0,
            'side':            'short' if is_short else 'long',
        })
    return out

# ── Static asset list & Alpaca asset cache ─────────────────────────────────────
_STATIC_ASSETS = [
    ('AAPL','Apple Inc.','NASDAQ'),('MSFT','Microsoft Corp.','NASDAQ'),('GOOGL','Alphabet Inc. Class A','NASDAQ'),
    ('AMZN','Amazon.com Inc.','NASDAQ'),('NVDA','NVIDIA Corp.','NASDAQ'),('META','Meta Platforms Inc.','NASDAQ'),
    ('TSLA','Tesla Inc.','NASDAQ'),('BRK.B','Berkshire Hathaway Class B','NYSE'),('UNH','UnitedHealth Group','NYSE'),
    ('JPM','JPMorgan Chase & Co.','NYSE'),('V','Visa Inc.','NYSE'),('JNJ','Johnson & Johnson','NYSE'),
    ('XOM','Exxon Mobil Corp.','NYSE'),('LLY','Eli Lilly and Co.','NYSE'),('AVGO','Broadcom Inc.','NASDAQ'),
    ('PG','Procter & Gamble Co.','NYSE'),('MA','Mastercard Inc.','NYSE'),('HD','Home Depot Inc.','NYSE'),
    ('CVX','Chevron Corp.','NYSE'),('MRK','Merck & Co.','NYSE'),('ABBV','AbbVie Inc.','NYSE'),
    ('PEP','PepsiCo Inc.','NASDAQ'),('KO','Coca-Cola Co.','NYSE'),('COST','Costco Wholesale Corp.','NASDAQ'),
    ('ADBE','Adobe Inc.','NASDAQ'),('WMT','Walmart Inc.','NYSE'),('MCD',"McDonald's Corp.",'NYSE'),
    ('CRM','Salesforce Inc.','NYSE'),('CSCO','Cisco Systems Inc.','NASDAQ'),('BAC','Bank of America Corp.','NYSE'),
    ('AMD','Advanced Micro Devices','NASDAQ'),('ACN','Accenture plc','NYSE'),('LIN','Linde plc','NYSE'),
    ('TMO','Thermo Fisher Scientific','NYSE'),('ORCL','Oracle Corp.','NYSE'),('NFLX','Netflix Inc.','NASDAQ'),
    ('ABT','Abbott Laboratories','NYSE'),('TXN','Texas Instruments Inc.','NASDAQ'),('PM','Philip Morris International','NYSE'),
    ('NEE','NextEra Energy Inc.','NYSE'),('QCOM','Qualcomm Inc.','NASDAQ'),('DHR','Danaher Corp.','NYSE'),
    ('IBM','International Business Machines','NYSE'),('INTU','Intuit Inc.','NASDAQ'),('GE','GE Aerospace','NYSE'),
    ('RTX','RTX Corp.','NYSE'),('HON','Honeywell International','NASDAQ'),('AMGN','Amgen Inc.','NASDAQ'),
    ('UNP','Union Pacific Corp.','NYSE'),('CAT','Caterpillar Inc.','NYSE'),('SPGI','S&P Global Inc.','NYSE'),
    ('BA','Boeing Co.','NYSE'),('GS','Goldman Sachs Group','NYSE'),('MS','Morgan Stanley','NYSE'),
    ('BLK','BlackRock Inc.','NYSE'),('ISRG','Intuitive Surgical Inc.','NASDAQ'),('SYK','Stryker Corp.','NYSE'),
    ('DE','Deere & Co.','NYSE'),('SBUX','Starbucks Corp.','NASDAQ'),('GILD','Gilead Sciences Inc.','NASDAQ'),
    ('NOW','ServiceNow Inc.','NYSE'),('PLD','Prologis Inc.','NYSE'),('AXP','American Express Co.','NYSE'),
    ('UBER','Uber Technologies Inc.','NYSE'),('BKNG','Booking Holdings Inc.','NASDAQ'),('MDLZ','Mondelez International','NASDAQ'),
    ('ADI','Analog Devices Inc.','NASDAQ'),('REGN','Regeneron Pharmaceuticals','NASDAQ'),('CI','Cigna Group','NYSE'),
    ('MU','Micron Technology Inc.','NASDAQ'),('KLAC','KLA Corp.','NASDAQ'),('LRCX','Lam Research Corp.','NASDAQ'),
    ('PANW','Palo Alto Networks Inc.','NASDAQ'),('SNPS','Synopsys Inc.','NASDAQ'),('CDNS','Cadence Design Systems','NASDAQ'),
    ('PYPL','PayPal Holdings Inc.','NASDAQ'),('INTC','Intel Corp.','NASDAQ'),('AMAT','Applied Materials Inc.','NASDAQ'),
    ('COIN','Coinbase Global Inc.','NASDAQ'),('HOOD','Robinhood Markets Inc.','NASDAQ'),('SOFI','SoFi Technologies Inc.','NASDAQ'),
    ('PLTR','Palantir Technologies Inc.','NYSE'),('SNOW','Snowflake Inc.','NYSE'),('DDOG','Datadog Inc.','NASDAQ'),
    ('CRWD','CrowdStrike Holdings Inc.','NASDAQ'),('NET','Cloudflare Inc.','NYSE'),('ZS','Zscaler Inc.','NASDAQ'),
    ('SPY','SPDR S&P 500 ETF Trust','NYSE'),('QQQ','Invesco QQQ Trust','NASDAQ'),('IWM','iShares Russell 2000 ETF','NYSE'),
    ('DIA','SPDR Dow Jones Industrial Average ETF','NYSE'),('VTI','Vanguard Total Stock Market ETF','NYSE'),
    ('GLD','SPDR Gold Shares','NYSE'),('SLV','iShares Silver Trust','NYSE'),('TLT','iShares 20+ Year Treasury Bond ETF','NASDAQ'),
    ('XLK','Technology Select Sector SPDR','NYSE'),('XLF','Financial Select Sector SPDR','NYSE'),
    ('XLE','Energy Select Sector SPDR','NYSE'),('XLV','Health Care Select Sector SPDR','NYSE'),
]
_STATIC_ASSETS_DICTS = [{'symbol': s, 'name': n, 'exchange': e} for s, n, e in _STATIC_ASSETS]

# ── Comprehensive ticker database (NASDAQ + NYSE full listings) ────────────────
_ticker_db: list[dict] = []
_ticker_db_loaded = False
_TICKER_DB_PATH = Path(__file__).parent / 'ticker_db.json'

def _load_ticker_db():
    global _ticker_db, _ticker_db_loaded
    if _ticker_db_loaded:
        return
    if _TICKER_DB_PATH.exists():
        try:
            age = _time.time() - _TICKER_DB_PATH.stat().st_mtime
            if age < 86400 * 7:  # 7-day cache
                with open(_TICKER_DB_PATH) as f:
                    _ticker_db = _json.load(f)
                _ticker_db_loaded = True
                print(f'[TradeSimulator] Loaded {len(_ticker_db)} tickers from cache.')
                return
        except Exception:
            pass
    try:
        import requests as _req
        all_tickers = []
        for url, exch in (
            ('https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt', 'NASDAQ'),
            ('https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt',  'NYSE'),
        ):
            r = _req.get(url, timeout=15)
            reader = csv.reader(io.StringIO(r.text), delimiter='|')
            next(reader, None)  # skip header
            for row in reader:
                if not row or row[0].startswith('File'):
                    continue
                sym = row[0].strip()
                if not sym or '.' in sym or '$' in sym or len(sym) > 5:
                    continue
                name = row[1].strip() if len(row) > 1 else ''
                all_tickers.append({'symbol': sym, 'name': name, 'exchange': exch})
        if all_tickers:
            _ticker_db = all_tickers
            _ticker_db_loaded = True
            with open(_TICKER_DB_PATH, 'w') as f:
                _json.dump(_ticker_db, f)
            print(f'[TradeSimulator] Downloaded {len(_ticker_db)} tickers from NASDAQ/NYSE.')
        else:
            raise ValueError('Empty ticker list')
    except Exception as e:
        print(f'[TradeSimulator] Ticker DB download failed: {e} — using static list.')
        _ticker_db = _STATIC_ASSETS_DICTS[:]
        _ticker_db_loaded = True

_asset_cache: list[dict] = []
_asset_cache_loaded = False

def _load_assets():
    global _asset_cache, _asset_cache_loaded
    if _asset_cache_loaded or not KEYS_SET:
        return
    try:
        from alpaca.trading.client import TradingClient as TC
        from alpaca.trading.requests import GetAssetsRequest
        from alpaca.trading.enums import AssetClass, AssetStatus
        tc     = TC(API_KEY, SECRET_KEY, paper=True)
        req    = GetAssetsRequest(asset_class=AssetClass.US_EQUITY, status=AssetStatus.ACTIVE)
        assets = tc.get_all_assets(req)
        _asset_cache = [
            {'symbol': a.symbol, 'name': a.name or '', 'exchange': str(a.exchange)}
            for a in assets if a.tradable and a.symbol
        ]
        _asset_cache_loaded = True
        print(f'[TradeSimulator] Loaded {len(_asset_cache)} assets into cache')
    except Exception as e:
        print(f'[TradeSimulator] Asset cache load failed: {e}')

# Alpha Vantage search cache
_av_search_cache: dict[str, list] = {}

def _search_alpha_vantage(q: str) -> list:
    q_key = q.upper()
    if q_key in _av_search_cache:
        return _av_search_cache[q_key]
    try:
        import requests as _req
        r = _req.get('https://www.alphavantage.co/query', params={
            'function': 'SYMBOL_SEARCH', 'keywords': q, 'apikey': AV_KEY,
        }, timeout=5)
        matches = r.json().get('bestMatches', [])
        results = [
            {'symbol': m.get('1. symbol',''), 'name': m.get('2. name',''), 'exchange': 'US'}
            for m in matches
            if m.get('4. region') == 'United States'
            and m.get('3. type') in ('Equity', 'ETF')
            and '.' not in m.get('1. symbol','')
        ]
        _av_search_cache[q_key] = results
        return results
    except Exception as e:
        print(f'[TradeSimulator] Alpha Vantage search failed: {e}')
        return []

# Sparkline cache (1h TTL)
_sparkline_cache: dict[str, list]  = {}
_sparkline_cache_ts: dict[str, float] = {}
_SPARKLINE_TTL = 3600

# ── Core routes ────────────────────────────────────────────────────────────────
@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

@app.route('/api/version')
def version():
    """Debug: confirm which backend version is running and what it can see."""
    import datetime, zoneinfo
    now_et = datetime.datetime.now(zoneinfo.ZoneInfo('America/New_York'))
    with _get_db() as conn:
        ai_pids = [r[0] for r in conn.execute('SELECT id FROM portfolios WHERE ai_controlled=1').fetchall()]
        recent = conn.execute(
            'SELECT portfolio_id, scanned, error_count, created_at FROM ai_scan_runs ORDER BY id DESC LIMIT 5'
        ).fetchall()
    return jsonify({
        'version':         '2026-05-30-tiers1-6',
        'candle_engine':   _candle_engine is not None,
        'stream_manager':  _stream_manager is not None,
        'market_open':     _market_is_open(),
        'et_time':         now_et.strftime('%H:%M ET'),
        'ai_portfolios':   ai_pids,
        'recent_scans':    [dict(r) for r in recent],
    })

@app.route('/api/status')
def status():
    return jsonify({
        'keys_configured':     KEYS_SET,
        'av_configured':       AV_KEYS_SET,
        'polygon_configured':  POLYGON_KEYS_SET,
    })

# ── Auth ──────────────────────────────────────────────────────────────────────
def _hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode('utf-8')).hexdigest()

@app.route('/api/auth/register', methods=['POST'])
def auth_register():
    data         = request.json or {}
    username     = data.get('username', '').strip().lower()
    password     = data.get('password', '')
    display_name = data.get('display_name', '').strip() or username
    avatar_color = data.get('avatar_color', '#ff6a1a')
    if not username or len(username) < 2:
        return jsonify({'error': 'Username must be at least 2 characters'}), 400
    if len(password) < 4:
        return jsonify({'error': 'Password must be at least 4 characters'}), 400
    try:
        with _get_db() as conn:
            cur = conn.execute(
                'INSERT INTO users (username, pw_hash, display_name, avatar_color) VALUES (?,?,?,?)',
                (username, _hash_pw(password), display_name, avatar_color)
            )
            user_id = cur.lastrowid
            # Create default portfolio for new user
            conn.execute('INSERT INTO portfolios (user_id, name, color) VALUES (?,?,?)',
                         (user_id, 'Main Portfolio', '#ff6a1a'))
        return jsonify({'user_id': user_id, 'username': username, 'display_name': display_name, 'avatar_color': avatar_color})
    except Exception as e:
        if 'UNIQUE' in str(e):
            return jsonify({'error': 'Username already taken'}), 409
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    data     = request.json or {}
    username = data.get('username', '').strip().lower()
    password = data.get('password', '')
    with _get_db() as conn:
        row = conn.execute(
            'SELECT id, username, pw_hash, display_name, avatar_color FROM users WHERE username = ?',
            (username,)
        ).fetchone()
    if not row or row['pw_hash'] != _hash_pw(password):
        return jsonify({'error': 'Invalid username or password'}), 401
    return jsonify({
        'user_id':      row['id'],
        'username':     row['username'],
        'display_name': row['display_name'] or row['username'],
        'avatar_color': row['avatar_color'],
    })

# ── Portfolios ────────────────────────────────────────────────────────────────
@app.route('/api/portfolios')
def get_portfolios():
    user_id = request.args.get('user_id', 1, type=int)
    with _get_db() as conn:
        rows = conn.execute(
            'SELECT * FROM portfolios WHERE user_id = ? ORDER BY id', (user_id,)
        ).fetchall()
    result = []
    for row in rows:
        pid = row['id']
        result.append({
            'id':            pid,
            'name':          row['name'],
            'color':         row['color'],
            'ai_controlled': int(row['ai_controlled']) if 'ai_controlled' in row.keys() else 0,
        })
    return jsonify(result)

@app.route('/api/portfolios', methods=['POST'])
def create_portfolio():
    data          = request.json or {}
    user_id       = data.get('user_id', 1)
    name          = data.get('name', 'New Portfolio').strip()
    color         = data.get('color', '#ff6a1a')
    initial_cash  = float(data.get('initial_cash', 100000))
    ai_controlled = int(bool(data.get('ai_controlled', False)))
    if not name:
        return jsonify({'error': 'Name required'}), 400
    if initial_cash < 100 or initial_cash > 10_000_000:
        return jsonify({'error': 'Starting balance must be between $100 and $10,000,000'}), 400
    with _get_db() as conn:
        cur = conn.execute(
            'INSERT INTO portfolios (user_id, name, color, ai_controlled) VALUES (?,?,?,?)',
            (user_id, name, color, ai_controlled)
        )
        pid = cur.lastrowid
        # Seed sim_state for this portfolio with the chosen starting balance
        conn.execute(
            "INSERT OR IGNORE INTO sim_state (id, cash, initial_cash, last_equity, reset_at, portfolio_id) VALUES (?,?,?,?,datetime('now'),?)",
            (pid + 1000, initial_cash, initial_cash, initial_cash, pid)
        )
    return jsonify({'id': pid, 'name': name, 'color': color,
                    'user_id': user_id, 'ai_controlled': ai_controlled})

@app.route('/api/portfolios/<int:pid>', methods=['PATCH'])
def update_portfolio(pid):
    data = request.json or {}
    with _get_db() as conn:
        if 'name' in data:
            conn.execute('UPDATE portfolios SET name = ? WHERE id = ?', (data['name'], pid))
        if 'color' in data:
            conn.execute('UPDATE portfolios SET color = ? WHERE id = ?', (data['color'], pid))
        ai_controlled = data.get('ai_controlled')
        if ai_controlled is not None:
            conn.execute('UPDATE portfolios SET ai_controlled=? WHERE id=?', (1 if ai_controlled else 0, pid))
    return jsonify({'status': 'updated'})

@app.route('/api/portfolios/<int:pid>/reset', methods=['POST'])
def reset_portfolio(pid):
    """Reset portfolio: clear positions, trades, AI log, and restore initial cash."""
    try:
        with _get_db() as conn:
            state = conn.execute('SELECT initial_cash FROM sim_state WHERE portfolio_id=?', (pid,)).fetchone()
            initial_cash = state['initial_cash'] if state else 100000.0
            conn.execute("UPDATE sim_state SET cash=?, last_equity=?, reset_at=datetime('now') WHERE portfolio_id=?",
                         (initial_cash, initial_cash, pid))
            conn.execute('DELETE FROM sim_positions WHERE portfolio_id=?', (pid,))
            conn.execute('DELETE FROM sim_trades WHERE portfolio_id=?', (pid,))
            conn.execute('DELETE FROM ai_log WHERE portfolio_id=?', (pid,))
            conn.execute('DELETE FROM ai_scan_runs WHERE portfolio_id=?', (pid,))
        return jsonify({'status': 'reset', 'cash': initial_cash})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/portfolios/<int:pid>', methods=['DELETE'])
def delete_portfolio(pid):
    if pid == 1:
        return jsonify({'error': 'Cannot delete default portfolio'}), 400
    with _get_db() as conn:
        conn.execute('DELETE FROM portfolios WHERE id = ?', (pid,))
        conn.execute('DELETE FROM sim_positions WHERE portfolio_id = ?', (pid,))
        conn.execute('DELETE FROM sim_trades WHERE portfolio_id = ?', (pid,))
    return jsonify({'status': 'deleted'})

@app.route('/api/portfolios/<int:pid>/ai/log')
def ai_log(pid):
    with _get_db() as conn:
        rows = conn.execute(
            'SELECT * FROM ai_log WHERE portfolio_id=? ORDER BY id DESC LIMIT 50', (pid,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d.get('created_at') and not d['created_at'].endswith('Z'):
            d['created_at'] += 'Z'
        out.append(d)
    return jsonify(out)

@app.route('/api/portfolios/<int:pid>/ai/scans')
def ai_scans(pid):
    """Return AI scan run history with bought/sold/batch details."""
    import json as _json
    limit = int(request.args.get('limit', 30))
    with _get_db() as conn:
        rows = conn.execute(
            '''SELECT id, portfolio_id, scanned, bought_count, sold_count, error_count,
                      bought_json, sold_json, batch_json, mode, skip_reason, created_at,
                      skipped_json
               FROM ai_scan_runs WHERE portfolio_id=? ORDER BY id DESC LIMIT ?''',
            (pid, limit)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d.get('created_at') and not d['created_at'].endswith('Z'):
            d['created_at'] += 'Z'
        for key in ('bought_json', 'sold_json', 'batch_json', 'skipped_json'):
            try:
                d[key] = _json.loads(d[key] or '[]')
            except Exception:
                d[key] = []
        out.append(d)
    return jsonify(out)


@app.route('/api/portfolios/<int:pid>/trades')
def portfolio_trades(pid):
    """Trade history with P&L. Open trades show pl=null; closed trades show realized P&L.
    Also backfills P&L for any closed trades where realized_pl was 0 by FIFO matching."""
    limit = int(request.args.get('limit', 200))
    try:
        with _get_db() as conn:
            # Join sim_trades with ai_log to get reasoning for each trade
            # Match on symbol + approximate time (within 10 seconds) + action mapping
            rows = conn.execute(
                '''SELECT t.id, t.symbol, t.side, t.qty, t.price, t.realized_pl,
                          t.created_at,
                          l.reason, l.score as ai_score, l.market_state, l.strategy
                   FROM sim_trades t
                   LEFT JOIN ai_log l ON (
                       l.portfolio_id = t.portfolio_id
                       AND l.symbol = t.symbol
                       AND ABS(strftime('%s', l.created_at) - strftime('%s', t.created_at)) <= 15
                       AND (
                           (t.side = 'buy'   AND l.action = 'BUY')   OR
                           (t.side = 'sell'  AND l.action = 'SELL')  OR
                           (t.side = 'short' AND l.action = 'SHORT') OR
                           (t.side = 'cover' AND l.action = 'COVER')
                       )
                   )
                   WHERE t.portfolio_id=?
                   ORDER BY t.id DESC LIMIT ?''',
                (pid, limit)
            ).fetchall()

        trades = []
        for r in rows:
            d = dict(r)
            if d.get('created_at') and not d['created_at'].endswith('Z'):
                d['created_at'] += 'Z'
            is_close = d['side'] in ('sell', 'cover')
            d['pl']      = round(d['realized_pl'], 4) if is_close else None
            d['is_open'] = not is_close
            # Clean up reason text
            if d.get('reason'):
                d['reason'] = d['reason'].encode('utf-8', errors='replace').decode('utf-8')
            trades.append(d)

        # Summary stats
        closed = [t for t in trades if not t['is_open']]
        total_pl   = round(sum(t['pl'] for t in closed), 2)
        win_count  = sum(1 for t in closed if (t['pl'] or 0) > 0)
        loss_count = sum(1 for t in closed if (t['pl'] or 0) < 0)
        win_rate   = round(win_count / len(closed) * 100, 1) if closed else 0

        return jsonify({
            'trades':     trades,
            'summary': {
                'total_pl':   total_pl,
                'closed':     len(closed),
                'wins':       win_count,
                'losses':     loss_count,
                'win_rate':   win_rate,
                'avg_win':    round(sum(t['pl'] for t in closed if (t['pl'] or 0)>0) / max(win_count,1), 2),
                'avg_loss':   round(sum(t['pl'] for t in closed if (t['pl'] or 0)<0) / max(loss_count,1), 2),
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolios/<int:pid>/ai/run', methods=['POST'])
def ai_run(pid):
    with _get_db() as conn:
        row = conn.execute('SELECT ai_controlled FROM portfolios WHERE id=?', (pid,)).fetchone()
    if not row:
        return jsonify({'error': 'Portfolio not found'}), 404
    if not row['ai_controlled']:
        return jsonify({'error': 'Portfolio is not AI-controlled'}), 400
    summary = _ai_run_portfolio(pid)
    return jsonify(summary)


@app.route('/api/portfolios/<int:pid>/ai/scan/suggestions')
def ai_scan_suggestions(pid):
    """Run AI scan and return suggestions without placing any trades.
    Works regardless of whether the portfolio is AI-controlled."""
    try:
        # Run a read-only scan: compute scores but don't execute anything
        with _get_db() as conn:
            wl_syms = [r['symbol'] for r in conn.execute(
                'SELECT symbol FROM watchlist_items WHERE portfolio_id=?', (pid,)
            ).fetchall()]
            held_syms = [r['symbol'] for r in conn.execute(
                'SELECT symbol FROM sim_positions WHERE portfolio_id=? AND shares!=0', (pid,)
            ).fetchall()]

        market_open = _market_is_open()
        combined = list(dict.fromkeys(_AI_UNIVERSE + wl_syms))
        if not market_open:
            combined = [s for s in combined if _is_fractional_asset(s)]

        batch = combined[:40]  # scan top 40
        suggestions = {'long': [], 'short': [], 'neutral': []}

        for sym in batch:
            try:
                data = _compute_indicators_fast(sym)
                data['symbol'] = sym
                price = data.get('last_price')
                if not price or price <= 0:
                    continue
                detail = _ai_score_detailed(data)
                score = detail['score']
                regime = detail['market_state']

                entry = {
                    'symbol': sym,
                    'score': round(score, 2),
                    'regime': regime,
                    'rsi': round(data.get('rsi', 50), 1),
                    'price': round(price, 4),
                    'confidence': detail.get('uncertainty', 0.5),
                    'summary': detail.get('summary', '')[:100],
                    'direction': 'short' if score <= -2.5 else 'long' if score >= 2.5 else 'neutral',
                    'currently_held': sym in held_syms,
                    'disclaimer': 'Metrics only. Not financial advice.',
                }

                if score >= 2.5:
                    suggestions['long'].append(entry)
                elif score <= -2.5:
                    suggestions['short'].append(entry)
                else:
                    suggestions['neutral'].append(entry)
            except Exception:
                pass

        # Sort each by |score| descending
        for k in suggestions:
            suggestions[k].sort(key=lambda x: abs(x['score']), reverse=True)

        return jsonify({
            'suggestions': suggestions,
            'market_open': market_open,
            'scanned': len(batch),
            'disclaimer': 'Algorithmic analysis only. Not financial advice. Past performance does not guarantee future results.',
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolios/<int:pid>/heat')
def portfolio_heat(pid):
    """Return portfolio risk heat and asset-class exposure breakdown."""
    try:
        state  = _sim_state(pid)
        equity = state.get('last_equity') or state.get('cash') or 100000
        heat   = _compute_portfolio_heat(pid, equity)
        held_prices = {}
        with _get_db() as conn:
            rows = conn.execute(
                'SELECT symbol, shares FROM sim_positions WHERE portfolio_id=? AND shares!=0', (pid,)
            ).fetchall()
        for row in rows:
            try:
                held_prices[row['symbol']] = _get_current_price(row['symbol'])
            except Exception:
                pass
        exposure = _compute_exposure(pid, equity, held_prices)
        return jsonify({
            'heat':       heat,
            'heat_pct':   f'{heat*100:.1f}%',
            'max_heat':   MAX_PORTFOLIO_HEAT,
            'exposure':   {k: round(v, 4) for k, v in exposure.items()},
            'caps':       ASSET_CLASS_CAPS,
            'equity':     equity,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolios/<int:pid>/analytics')
def portfolio_analytics_endpoint(pid):
    """Portfolio-level risk analytics: sector exposure, beta, correlation clusters."""
    if not _portfolio_analytics:
        return jsonify({'error': 'Portfolio analytics not initialized'}), 503
    with _get_db() as conn:
        pos_rows = conn.execute(
            'SELECT symbol, shares, avg_cost FROM sim_positions WHERE portfolio_id=? AND shares!=0', (pid,)
        ).fetchall()
    positions = [{'symbol': r['symbol'], 'shares': r['shares'], 'avg_cost': r['avg_cost'],
                  'current_price': _get_current_price(r['symbol'])} for r in pos_rows]
    prices = {p['symbol']: p['current_price'] for p in positions}
    result = _portfolio_analytics.compute(positions, prices)
    return jsonify(result)


@app.route('/api/portfolios/<int:pid>/breakers')
def portfolio_breakers(pid):
    """Circuit breaker status for a portfolio."""
    try:
        import circuit_breakers as _cb_mod
        cb = _cb_mod.get()
        if cb is None:
            return jsonify({'status': 'not_initialized'})
        state = _sim_state(pid)
        equity = state.get('last_equity') or state.get('cash') or 100000
        state = _cb_mod.check(pid, equity)
        return jsonify({
            'state':            state,
            'consec_losses':    cb._consec_losses.get(pid, 0),
            'paused_until':     cb._pause_until.get(pid),
            'disabled_combos':  list(cb._disabled_combos),
            'hwm':              cb._hwm.get(pid),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolios/<int:pid>/circuit-breaker/reset', methods=['POST'])
def reset_circuit_breaker(pid):
    """Reset the consecutive-loss pause for a portfolio so the AI can resume immediately."""
    try:
        import circuit_breakers as _cb_mod
        cb = _cb_mod.get()
        if cb is None:
            return jsonify({'status': 'not_initialized'})
        cb.reset_pause(pid)
        return jsonify({'status': 'reset', 'portfolio_id': pid})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/breadth')
def market_breadth():
    """Current market breadth snapshot."""
    try:
        import breadth_engine as _be
        return jsonify(_be.latest())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/rl/stats')
def rl_stats():
    """Q-table statistics and top-performing state/action pairs."""
    try:
        import rl_engine as _rl_mod
        eng = _rl_mod.get_engine()
        if not eng:
            return jsonify({'status': 'not_initialized'})
        return jsonify(eng.stats())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/macro')
def macro_signal():
    """Current macro environment (cross-asset signals)."""
    try:
        import macro_engine as _me
        return jsonify(_me.latest())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/orderflow/<symbol>')
def order_flow_signal(symbol):
    """Real-time order flow / bid-ask imbalance for a symbol."""
    try:
        import order_flow as _of
        return jsonify(_of.get_signal(symbol.upper()))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/sentiment/<symbol>')
def symbol_news(symbol):
    """News sentiment and event calendar for a symbol."""
    try:
        import news_engine as _ne
        return jsonify(_ne.get_engine().get_signal(symbol.upper()))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/backtest', methods=['POST'])
def run_backtest_endpoint():
    """Run historical backtest for a symbol."""
    body    = request.json or {}
    symbol  = body.get('symbol', 'AAPL').upper()
    start   = body.get('start', '2024-01-01')
    end     = body.get('end',   '2024-12-31')
    capital = float(body.get('capital', 100000))
    try:
        from backtester import run_backtest
        result = run_backtest(symbol, start, end, capital)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/backtest/walkforward', methods=['POST'])
def run_walkforward_endpoint():
    """Walk-forward validation — tests strategy robustness across rolling windows."""
    body    = request.json or {}
    symbol  = body.get('symbol', 'AAPL').upper()
    start   = body.get('start', '2023-01-01')
    end     = body.get('end',   '2024-12-31')
    window  = int(body.get('window_days', 90))
    step    = int(body.get('step_days', 30))
    capital = float(body.get('capital', 100000))
    try:
        from backtester import run_walk_forward
        return jsonify(run_walk_forward(symbol, start, end, window, step, capital))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/options/signal/<symbol>')
def options_signal(symbol):
    """Get options trade recommendation for a symbol."""
    try:
        sym = symbol.upper()
        data   = _compute_indicators_fast(sym)
        data['symbol'] = sym
        detail = _ai_score_detailed(data)
        score  = detail['score']
        regime = detail['market_state']
        price  = data.get('last_price') or _get_current_price(sym)

        import options_strategy as _os_mod
        mgr = _os_mod.get_manager()
        if not mgr:
            return jsonify({'error': 'Options strategy manager not initialized'}), 503

        pid    = int(request.args.get('pid', 1))
        equity = _sim_state(pid).get('cash', 100000)
        result = mgr.evaluate(sym, price, score, regime,
                              uncertainty=detail.get('uncertainty', 0.3),
                              portfolio_equity=equity, pid=pid)
        result['ai_score']  = score
        result['regime']    = regime
        result['price']     = price
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolios/<int:pid>/options')
def portfolio_options(pid):
    """List open options positions for a portfolio."""
    try:
        with _get_db() as conn:
            rows = conn.execute(
                '''SELECT * FROM sim_options_positions
                   WHERE portfolio_id=? AND status='open'
                   ORDER BY opened_at DESC''', (pid,)
            ).fetchall()
        positions = [dict(r) for r in rows]

        # Compute total portfolio Greeks
        import options_strategy as _os_mod
        mgr = _os_mod.get_manager()
        greeks_summary = {}
        if mgr:
            snap = mgr.portfolio_greeks_summary(pid)
            greeks_summary = snap

        return jsonify({'positions': positions, 'portfolio_greeks': greeks_summary})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolios/<int:pid>/options/<int:pos_id>/close', methods=['POST'])
def close_options_position(pid, pos_id):
    """Manually close an options position."""
    try:
        with _get_db() as conn:
            row = conn.execute(
                'SELECT * FROM sim_options_positions WHERE id=? AND portfolio_id=?',
                (pos_id, pid)
            ).fetchone()
            if not row:
                return jsonify({'error': 'Position not found'}), 404

            # Get current price from options engine
            import options_engine as _oe_mod
            eng = _oe_mod.get_engine()
            current_price = row['entry_price']  # fallback
            if eng:
                try:
                    quote = eng.chain.get_quote(row['symbol'])
                    if quote:
                        current_price = quote['mid']
                except Exception:
                    pass

            realized_pl = (current_price - row['entry_price']) * row['contracts'] * 100
            if row['side'] == 'short':
                realized_pl = -realized_pl

            conn.execute(
                '''UPDATE sim_options_positions
                   SET status='closed', exit_reason='manual', realized_pl=?,
                       current_price=?, closed_at=datetime('now')
                   WHERE id=?''',
                (round(realized_pl, 2), current_price, pos_id)
            )
        return jsonify({'closed': True, 'realized_pl': round(realized_pl, 2)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/options/chain/<symbol>')
def options_chain(symbol):
    """Fetch live options chain for a symbol."""
    try:
        import options_engine as _oe_mod
        eng = _oe_mod.get_engine()
        if not eng:
            return jsonify({'error': 'Options engine not initialized'}), 503

        sym   = symbol.upper()
        price = _get_current_price(sym)
        dte_min = int(request.args.get('dte_min', 20))
        dte_max = int(request.args.get('dte_max', 60))
        opt_type = request.args.get('type')  # 'call', 'put', or None for both

        contracts = eng.chain.get_contracts(sym, dte_min, dte_max, opt_type)
        # Enrich top 10 contracts with Greeks + IV (limited to control API calls)
        enriched = []
        for c in contracts[:10]:
            ec = eng.chain.enrich_contract(c, price)
            enriched.append(ec)

        return jsonify({'symbol': sym, 'underlying_price': price,
                        'contracts': enriched, 'count': len(enriched)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolios/<int:pid>/performance')
def portfolio_performance_endpoint(pid):
    """Self-analysis: win rate by regime, signal attribution, equity curve, decay check."""
    if not _perf_engine:
        return jsonify({'error': 'Performance engine not initialized'}), 503
    days = request.args.get('days', 90, type=int)
    return jsonify({
        'summary':             _perf_engine.summary(pid),
        'by_regime':           _perf_engine.by_regime(pid, days),
        'by_score_bucket':     _perf_engine.by_score_bucket(pid, days),
        'signal_attribution':  _perf_engine.signal_attribution(pid, days),
        'equity_curve':        _perf_engine.equity_curve(pid, min(days, 30)),
        'decay':               _perf_engine.decay_check(pid),
    })


@app.route('/api/portfolios/<int:pid>/history/review')
def portfolio_history_review(pid):
    """30-day trade review: regime perf, decay status, signal attribution, equity curve."""
    try:
        from performance_engine import PerformanceEngine
        pe  = PerformanceEngine(DB_PATH)
        ctx = _build_history_context(pid)
        return jsonify({
            'by_regime':    pe.by_regime(pid, 30),
            'decay':        pe.decay_check(pid, 7, 30),
            'attribution':  pe.signal_attribution(pid, 30),
            'equity_curve': pe.equity_curve(pid, 30),
            'adjustments':  {
                'buy_thresh_raised': ctx['buy_thresh_adj'] > 0,
                'sell_thresh_raised': ctx['sell_thresh_adj'] > 0,
                'cautious_regimes': list(ctx['cautious_regimes']),
                'strong_regimes':   list(ctx['strong_regimes']),
                'decay_detected':   ctx['decay_detected'],
            },
            'summary': ctx['summary'],
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolios/<int:pid>/history/clear', methods=['DELETE'])
def portfolio_history_clear(pid):
    """Delete all 30D AI history for a portfolio. Restricted to thatonejet.
    Auth: portfolio_id must belong to a user whose username is 'thatonejet'.
    No client-supplied user identity — ownership is verified server-side only.
    """
    with _get_db() as conn:
        row = conn.execute(
            'SELECT u.username FROM portfolios p JOIN users u ON p.user_id=u.id WHERE p.id=?',
            (pid,)
        ).fetchone()
    if not row or row['username'] != 'thatonejet':
        return jsonify({'error': 'Not authorized'}), 403
    cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat()
    with _get_db() as conn:
        conn.execute('DELETE FROM ai_log        WHERE portfolio_id=? AND created_at >= ?', (pid, cutoff))
        conn.execute('DELETE FROM sim_trades     WHERE portfolio_id=? AND created_at >= ?', (pid, cutoff))
        conn.execute('DELETE FROM ai_scan_runs   WHERE portfolio_id=? AND created_at >= ?', (pid, cutoff))
        conn.execute('DELETE FROM ai_decisions   WHERE portfolio_id=? AND created_at >= ?', (pid, cutoff))
        try:
            conn.execute('DELETE FROM ai_rejections WHERE portfolio_id=? AND created_at >= ?', (pid, cutoff))
        except Exception:
            pass
    return jsonify({'status': 'cleared', 'portfolio_id': pid})


@app.route('/api/portfolios/<int:pid>/ev')
def portfolio_ev(pid):
    """Expected Value per setup from 90-day trade history."""
    try:
        from performance_engine import get_ev_by_setup
        days = int(request.args.get('days', 90))
        return jsonify(get_ev_by_setup(DB_PATH, pid, days))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/portfolios/<int:pid>/portfolio_regime')
def portfolio_regime_endpoint(pid):
    """Current portfolio regime and size multiplier."""
    try:
        state  = _sim_state(pid)
        equity = state.get('equity') or state.get('cash') or 100000
        return jsonify(_portfolio_regime(pid, equity))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolios/<int:pid>/positions/protection')
def positions_protection(pid):
    """Protection status for each open position — stage, stop, bearish risk."""
    try:
        with _get_db() as conn:
            rows = conn.execute(
                'SELECT symbol, shares, avg_cost, stop_price FROM sim_positions WHERE portfolio_id=? AND shares!=0',
                (pid,)
            ).fetchall()

        result = []
        for row in rows:
            sym   = row['symbol']
            try:
                data  = _compute_indicators_fast(sym)
                price = data.get('last_price') or _get_current_price(sym)
                atr   = data.get('atr') or (price * 0.02 if price else 0)

                prot  = _protection_stage(row['avg_cost'], price, row['stop_price'], atr)

                bearish_info = {}
                try:
                    import bearish_engine as _be
                    bearish_info = _be.score(sym, data, row['avg_cost'], price)
                except Exception:
                    pass

                result.append({
                    'symbol':        sym,
                    'shares':        row['shares'],
                    'avg_cost':      row['avg_cost'],
                    'current_price': price,
                    'stop_price':    row['stop_price'],
                    'protection':    prot,
                    'bearish':       bearish_info,
                })
            except Exception as e:
                result.append({'symbol': sym, 'error': str(e)})

        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolios/<int:pid>/decisions/summary')
def decisions_summary(pid):
    """Decision log summary: rejection reasons, accept rate, top symbols."""
    try:
        days = int(request.args.get('days', 7))
        from datetime import datetime, timedelta
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with _get_db() as conn:
            by_decision = conn.execute(
                'SELECT decision, COUNT(*) as n FROM ai_decisions WHERE portfolio_id=? AND created_at>? GROUP BY decision',
                (pid, cutoff)
            ).fetchall()
            by_reason = conn.execute(
                'SELECT reason, COUNT(*) as n FROM ai_decisions WHERE portfolio_id=? AND decision="REJECT" AND created_at>? GROUP BY reason ORDER BY n DESC',
                (pid, cutoff)
            ).fetchall()
            top_rejected = conn.execute(
                'SELECT symbol, COUNT(*) as n FROM ai_decisions WHERE portfolio_id=? AND decision="REJECT" AND created_at>? GROUP BY symbol ORDER BY n DESC LIMIT 10',
                (pid, cutoff)
            ).fetchall()
            top_accepted = conn.execute(
                'SELECT symbol, COUNT(*) as n FROM ai_decisions WHERE portfolio_id=? AND decision="ACCEPT" AND created_at>? GROUP BY symbol ORDER BY n DESC LIMIT 10',
                (pid, cutoff)
            ).fetchall()

        total = sum(r['n'] for r in by_decision)
        rejects = next((r['n'] for r in by_decision if r['decision'] == 'REJECT'), 0)
        accepts = next((r['n'] for r in by_decision if r['decision'] == 'ACCEPT'), 0)

        return jsonify({
            'total': total, 'accepts': accepts, 'rejects': rejects,
            'accept_rate': round(accepts/total*100, 1) if total else 0,
            'by_reason': {r['reason']: {'count': r['n'], 'pct': round(r['n']/max(rejects,1)*100,1)} for r in by_reason},
            'top_rejected_symbols': [dict(r) for r in top_rejected],
            'top_accepted_symbols': [dict(r) for r in top_accepted],
            'days': days,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/analysis/<symbol>/structure')
def symbol_structure_endpoint(symbol):
    """Market structure snapshot: swing bias, S/R levels, FVGs, session levels."""
    if not _structure_engine:
        return jsonify({'error': 'Structure engine not initialized'}), 503
    snap = _structure_engine.snapshot(symbol.upper())
    return jsonify({'symbol': symbol.upper(), **snap})


@app.route('/api/users/<int:uid>', methods=['PATCH'])
def update_user(uid):
    data = request.json or {}
    fields, vals = [], []
    if 'display_name' in data:
        fields.append('display_name = ?')
        vals.append(data['display_name'])
    if 'avatar_color' in data:
        fields.append('avatar_color = ?')
        vals.append(data['avatar_color'])
    if not fields:
        return jsonify({'error': 'Nothing to update'}), 400
    vals.append(uid)
    with _get_db() as conn:
        conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", vals)
        row = conn.execute(
            'SELECT id, username, display_name, avatar_color FROM users WHERE id = ?', (uid,)
        ).fetchone()
    if not row:
        return jsonify({'error': 'User not found'}), 404
    return jsonify({
        'user_id':      row['id'],
        'username':     row['username'],
        'display_name': row['display_name'],
        'avatar_color': row['avatar_color'],
    })

# ── Portfolio simulation routes (no Alpaca required) ──────────────────────────
@app.route('/api/account')
def account():
    pid = request.args.get('portfolio_id', 1, type=int)
    if pid == 0:
        pos = _real_holdings_with_prices()
        total_value = sum(p['market_value'] for p in pos)
        total_cost  = sum(p['avg_entry_price'] * p['qty'] for p in pos)
        pnl = total_value - total_cost
        day_pls = [p['day_pl'] for p in pos if p.get('day_pl') is not None]
        pnl_day = round(sum(day_pls), 2) if day_pls else None
        return jsonify({
            'equity':          round(total_value, 2),
            'cash':            0,
            'buying_power':    0,
            'portfolio_value': round(total_value, 2),
            'daytrade_count':  0,
            'pnl_day':         pnl_day,
            'pnl':             round(pnl, 2),
            'pnl_pct':         round((pnl / total_cost * 100) if total_cost else 0, 2),
            'initial_cost':    round(total_cost, 2),
            'is_real':         True,
        })
    state     = _sim_state(pid)
    positions = _sim_positions_with_prices(pid)
    portfolio_value = state['cash'] + sum(p['market_value'] for p in positions)
    buying_power    = round(portfolio_value * 0.90, 2)

    # Day P&L = realized gains/losses from trades CLOSED today (not open positions)
    import datetime
    today_start = datetime.datetime.utcnow().strftime('%Y-%m-%d') + ' 00:00:00'
    with _get_db() as conn:
        prow = conn.execute('SELECT ai_controlled, strategy_type FROM portfolios WHERE id=?', (pid,)).fetchone()
        ai_controlled = int(prow['ai_controlled']) if prow else 0
        strategy_type = prow['strategy_type'] if prow and 'strategy_type' in prow.keys() else 'balanced'
        day_realized = conn.execute(
            '''SELECT COALESCE(SUM(realized_pl), 0) as total
               FROM sim_trades
               WHERE portfolio_id=? AND status='filled'
               AND side IN ('sell','cover')
               AND created_at >= ?''',
            (pid, today_start)
        ).fetchone()['total']

    # Unrealized P&L = current gain/loss on ALL open positions
    unrealized_pl = sum(p.get('unrealized_pl', 0) or 0 for p in positions)

    return jsonify({
        'equity':          round(portfolio_value, 2),
        'cash':            round(state['cash'], 2),
        'buying_power':    buying_power,
        'portfolio_value': round(portfolio_value, 2),
        'daytrade_count':  0,
        'pnl_day':         round(day_realized, 2),      # realized P&L from closed trades today
        'pnl_unrealized':  round(unrealized_pl, 2),     # open position gain/loss
        'pnl_total':       round(day_realized + unrealized_pl, 2),
        'ai_controlled':   ai_controlled,
        'strategy_type':   strategy_type,
    })

@app.route('/api/positions')
def positions():
    pid = request.args.get('portfolio_id', 1, type=int)
    if pid == 0:
        return jsonify(_real_holdings_with_prices())
    return jsonify(_sim_positions_with_prices(pid))

@app.route('/api/orders', methods=['GET'])
def get_orders():
    pid = request.args.get('portfolio_id', 1, type=int)
    with _get_db() as conn:
        rows = conn.execute(
            'SELECT * FROM sim_trades WHERE portfolio_id = ? ORDER BY created_at DESC LIMIT 100',
            (pid,)
        ).fetchall()
    return jsonify([{
        'id':               str(row['id']),
        'symbol':           row['symbol'],
        'qty':              row['qty'],
        'filled_qty':       row['filled_qty'],
        'side':             row['side'],
        'type':             row['order_type'],
        'status':           row['status'],
        'limit_price':      row['limit_price'],
        'filled_avg_price': row['price'],
        'fill_price':       row['fill_price'] if row['fill_price'] else row['price'],
        'realized_pl':      row['realized_pl'],
        'created_at':       (row['created_at'] + 'Z') if row['created_at'] and not row['created_at'].endswith('Z') else row['created_at'],
    } for row in rows])

@app.route('/api/orders', methods=['POST'])
def place_order():
    data       = request.json
    symbol     = data.get('symbol', '').upper().strip()
    qty        = float(data.get('qty', 0))
    side       = data.get('side', 'buy').lower()
    otype      = data.get('type', 'market').lower()
    limit_price = data.get('limit_price')
    pid        = request.args.get('portfolio_id', data.get('portfolio_id', 1), type=int)

    if not symbol or qty <= 0:
        return jsonify({'error': 'Invalid symbol or qty'}), 400

    try:
        price     = _get_current_price(symbol)
        if price <= 0:
            return jsonify({'error': f'Could not get price for {symbol}'}), 400

        fill_price  = price
        status      = 'filled'
        realized_pl = 0.0

        # Limit order: check if immediately fillable
        if otype == 'limit' and limit_price:
            lp = float(limit_price)
            if side == 'buy' and price > lp:
                return jsonify({'error': f'Limit buy at ${lp:.2f} rejected: current price is ${price:.2f}. Lower prices will not be checked automatically.'}), 400
            if side == 'sell' and price < lp:
                return jsonify({'error': f'Limit sell at ${lp:.2f} rejected: current price is ${price:.2f}.'}), 400
            fill_price = lp

        # Slippage model
        try:
            _ind = _compute_indicators(symbol)
            _atr = _ind.get('atr', fill_price * 0.01) if _ind else fill_price * 0.01
            _vr  = _ind.get('volume_ratio', 1.0) if _ind else 1.0
        except Exception:
            _atr = fill_price * 0.01; _vr = 1.0
        slip_fill = _apply_slippage(fill_price, side, _atr, _vr, qty)
        # Clamp limit orders: never fill a buy above its limit or a sell below its limit
        if otype == 'limit' and limit_price:
            lp = float(limit_price)
            if side == 'buy':   slip_fill = min(slip_fill, lp)
            elif side == 'sell': slip_fill = max(slip_fill, lp)
        slippage_cost = round(abs(slip_fill - fill_price) * qty, 4)
        fill_price = slip_fill

        if side == 'buy':
            _sim_buy(symbol, qty, fill_price, pid, record=False)
        elif side == 'short':
            _sim_short(symbol, qty, fill_price, pid, record=False)
        elif side == 'cover':
            realized_pl = _sim_cover(symbol, qty, fill_price, pid, record=False)
        else:
            realized_pl = _sim_sell(symbol, qty, fill_price, pid, record=False)

        with _get_db() as conn:
            cur = conn.execute(
                'INSERT INTO sim_trades (symbol, side, qty, price, filled_qty, status, order_type, limit_price, realized_pl, portfolio_id, fill_price, slippage_cost) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (symbol, side, qty, fill_price, qty, status, otype, limit_price, realized_pl, pid, fill_price, slippage_cost)
            )
            order_id = cur.lastrowid

        return jsonify({'id': str(order_id), 'symbol': symbol, 'status': status, 'filled_avg_price': fill_price})

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/orders/<order_id>', methods=['DELETE'])
def cancel_order(order_id):
    with _get_db() as conn:
        row = conn.execute('SELECT status FROM sim_trades WHERE id = ?', (order_id,)).fetchone()
        if not row:
            return jsonify({'error': 'Order not found'}), 404
        if row['status'] != 'pending':
            return jsonify({'error': 'Only pending orders can be cancelled'}), 400
        conn.execute("UPDATE sim_trades SET status = 'cancelled' WHERE id = ?", (order_id,))
    return jsonify({'status': 'cancelled'})

@app.route('/api/account/reset', methods=['POST'])
def reset_account():
    pid = 1
    if request.json:
        pid = request.json.get('portfolio_id', 1)
    with _get_db() as conn:
        row = conn.execute('SELECT initial_cash FROM sim_state WHERE portfolio_id=?', (pid,)).fetchone()
        start = float(row['initial_cash']) if row and row['initial_cash'] else 100000.0
        conn.execute(
            "UPDATE sim_state SET cash=?, last_equity=?, reset_at=datetime('now') WHERE portfolio_id=?",
            (start, start, pid)
        )
        conn.execute('DELETE FROM sim_positions WHERE portfolio_id=?', (pid,))
        conn.execute('DELETE FROM sim_trades WHERE portfolio_id=?', (pid,))
        if pid == 1:
            conn.execute('DELETE FROM holdings')
    return jsonify({
        'status':  'reset',
        'message': f'Account reset to ${start:,.0f}. All positions and trades cleared.',
    })

# ── Market data routes ─────────────────────────────────────────────────────────
def _flatten_yf_df(df):
    if df is None or df.empty:
        return df
    if hasattr(df.columns, 'levels'):
        df.columns = df.columns.get_level_values(0)
    return df

def _bars_yfinance(symbol: str, tf_str: str, limit: int) -> list:
    import yfinance as yf
    interval_map = {
        '1Min':'1m','5Min':'5m','15Min':'15m','1Hour':'1h','1Day':'1d',
        '1Wk':'1h','1Mo':'1d','3Mo':'1d','YTD':'1d','1Yr':'1d','5Yr':'1wk',
    }
    period_map = {
        '1Min':'5d','5Min':'5d','15Min':'5d','1Hour':'60d','1Day':'1y',
        '1Wk':'5d','1Mo':'60d','3Mo':'90d','YTD':'ytd','1Yr':'1y','5Yr':'5y',
    }
    df = yf.download(symbol, period=period_map.get(tf_str,'1y'),
                     interval=interval_map.get(tf_str,'1d'),
                     progress=False, auto_adjust=True)
    df = _flatten_yf_df(df)
    if df is None or df.empty:
        return []
    rows = []
    for ts, row in df.tail(limit).iterrows():
        try:
            rows.append({'time': int(ts.timestamp()),
                         'open':   round(float(row['Open']),   4),
                         'high':   round(float(row['High']),   4),
                         'low':    round(float(row['Low']),    4),
                         'close':  round(float(row['Close']),  4),
                         'volume': round(float(row['Volume']), 0)})
        except (TypeError, ValueError):
            continue
    return rows

@app.route('/api/bars/<symbol>')
def get_bars(symbol):
    tf_str = request.args.get('timeframe', '1Min')
    limit  = int(request.args.get('limit', 300))
    symbol = symbol.upper()
    # Use yfinance for all symbols — Alpaca IEX feed has data gaps and enum issues
    try:
        return jsonify(_bars_yfinance(symbol, tf_str, limit))
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    tf_map = {
        '1Min':  TimeFrame(1,  TimeFrameUnit.Minute),
        '5Min':  TimeFrame(5,  TimeFrameUnit.Minute),
        '15Min': TimeFrame(15, TimeFrameUnit.Minute),
        '1Hour': TimeFrame(1,  TimeFrameUnit.Hour),
        '1Day':  TimeFrame(1,  TimeFrameUnit.Day),
        '1Wk':   TimeFrame(1,  TimeFrameUnit.Hour),
        '1Mo':   TimeFrame(1,  TimeFrameUnit.Day),
        '3Mo':   TimeFrame(1,  TimeFrameUnit.Day),
        'YTD':   TimeFrame(1,  TimeFrameUnit.Day),
        '1Yr':   TimeFrame(1,  TimeFrameUnit.Day),
        '5Yr':   TimeFrame(1,  TimeFrameUnit.Week),
    }
    tf  = tf_map.get(tf_str, TimeFrame(1, TimeFrameUnit.Minute))
    end = datetime.utcnow()
    _days_back = {'1Min':5,'5Min':5,'15Min':5,'1Hour':60,'1Day':365,
                  '1Wk':7,'1Mo':60,'3Mo':90,'1Yr':365,'5Yr':1826}
    if tf_str == 'YTD':
        start = datetime(end.year, 1, 1)
    else:
        start = end - timedelta(days=_days_back.get(tf_str, 365))
    req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=tf,
                           start=start, end=end, limit=limit, feed='iex')
    bars = data_client.get_stock_bars(req)[symbol]
    return jsonify([{'time': int(b.timestamp.timestamp()),
                     'open': float(b.open), 'high': float(b.high),
                     'low': float(b.low), 'close': float(b.close),
                     'volume': float(b.volume)} for b in bars])

@app.route('/api/sparkline/<symbol>')
def get_sparkline(symbol):
    symbol = symbol.upper()
    now = _time.time()
    if symbol in _sparkline_cache and now - _sparkline_cache_ts.get(symbol, 0) < _SPARKLINE_TTL:
        return jsonify(_sparkline_cache[symbol])
    try:
        import yfinance as yf
        df = yf.download(symbol, period='30d', interval='1d', progress=False, auto_adjust=True)
        df = _flatten_yf_df(df)
        if df is None or df.empty:
            return jsonify([])
        closes = [round(float(v), 4) for v in df['Close'].dropna().tail(30)
                  if v == v]  # skip NaN
        _sparkline_cache[symbol] = closes
        _sparkline_cache_ts[symbol] = now
        return jsonify(closes)
    except Exception:
        return jsonify([])

def _quote_yfinance(symbol: str) -> dict:
    now = _time.time()
    if symbol in _quote_cache:
        q, ts = _quote_cache[symbol]
        if now - ts < _QUOTE_TTL:
            return q
    import yfinance as yf
    price = 0.0; prev = 0.0
    try:
        closes = yf.Ticker(symbol).history(period='5d')['Close'].dropna()
        if len(closes) >= 2:
            price = float(closes.iloc[-1]); prev = float(closes.iloc[-2])
        elif len(closes) == 1:
            price = float(closes.iloc[0])
    except Exception:
        pass
    change     = round(price - prev, 4) if prev else 0.0
    change_pct = round((change / prev) * 100, 2) if prev else 0.0
    q = {'symbol': symbol, 'bid': price, 'bid_size': 0, 'ask': price, 'ask_size': 0,
         'spread': 0.0, 'change': change, 'change_pct': change_pct, 'delayed': True}
    _quote_cache[symbol] = (q, now)
    _price_cache[symbol] = (price, now)
    return q

_FINNHUB_QUOTE_TTL = 30  # 30s cache — reduce Finnhub 429s on free tier

def _quote_finnhub(symbol: str) -> dict:
    import requests
    now = _time.time()
    if symbol in _quote_cache:
        q, ts = _quote_cache[symbol]
        if now - ts < _FINNHUB_QUOTE_TTL:
            return q
    url  = f'https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_KEY}'
    resp = requests.get(url, timeout=5)
    resp.raise_for_status()
    d     = resp.json()
    price = float(d.get('c') or 0)
    prev  = float(d.get('pc') or 0)
    high  = float(d.get('h') or 0)
    low   = float(d.get('l') or 0)
    open_ = float(d.get('o') or 0)
    ts_   = int(d.get('t') or 0)
    if price <= 0:
        raise ValueError(f'Finnhub returned no price for {symbol}')
    change     = round(price - prev, 4)
    change_pct = round((change / prev * 100), 2) if prev else 0
    q = {'symbol': symbol, 'bid': price, 'ask': price, 'bid_size': 0, 'ask_size': 0,
         'spread': 0.0, 'change': change, 'change_pct': change_pct, 'delayed': False,
         'high': high, 'low': low, 'open': open_, 'prev_close': prev, 'timestamp': ts_}
    _quote_cache[symbol] = (q, now)
    _price_cache[symbol] = (price, now)
    return q

@app.route('/api/quote/<symbol>')
def get_quote(symbol):
    symbol = symbol.upper()
    if FINNHUB_KEYS_SET:
        try:
            return jsonify(_quote_finnhub(symbol))
        except Exception:
            pass  # fall through to yfinance
    if not KEYS_SET:
        try:
            return jsonify(_quote_yfinance(symbol))
        except Exception as e:
            return jsonify({'error': str(e)}), 400
    try:
        req = StockLatestQuoteRequest(symbol_or_symbols=symbol, feed='iex')
        q   = data_client.get_stock_latest_quote(req)[symbol]
        yq  = _quote_yfinance(symbol)
        return jsonify({'symbol': symbol,
                        'bid': float(q.bid_price), 'bid_size': float(q.bid_size),
                        'ask': float(q.ask_price), 'ask_size': float(q.ask_size),
                        'spread': float(q.ask_price) - float(q.bid_price),
                        'change': yq.get('change', 0.0), 'change_pct': yq.get('change_pct', 0.0)})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/orderbook/<symbol>')
def order_book(symbol):
    """Level 2 order book depth.
    Crypto (-USD): Coinbase REST public API — free, no key, up to 50 levels.
    Others: Alpaca latest quote — best bid/ask only (IEX free tier limitation).
    """
    sym = symbol.upper()
    try:
        if sym.endswith('-USD'):
            # Coinbase Level 2 order book — free, no auth required
            import urllib.request as _ur
            cb_sym = sym  # BTC-USD format matches Coinbase
            url = f'https://api.exchange.coinbase.com/products/{cb_sym}/book?level=2'
            req = _ur.Request(url, headers={'User-Agent': 'TradeSimulator/1.0'})
            with _ur.urlopen(req, timeout=6) as r:
                raw = __import__('json').loads(r.read())

            # Top 20 levels each side, format: [price, size, num_orders]
            bids = [[float(b[0]), float(b[1]), int(b[2])] for b in raw.get('bids', [])[:20]]
            asks = [[float(a[0]), float(a[1]), int(a[2])] for a in raw.get('asks', [])[:20]]

            # Calculate totals for depth bars
            max_size = max(
                max((b[1] for b in bids), default=0),
                max((a[1] for a in asks), default=0)
            )

            best_bid = bids[0][0] if bids else 0
            best_ask = asks[0][0] if asks else 0
            spread    = best_ask - best_bid if best_bid and best_ask else 0
            spread_pct = spread / best_bid * 100 if best_bid else 0
            mid_price = (best_bid + best_ask) / 2 if best_bid and best_ask else 0

            # Total bid/ask liquidity in the top 20 levels
            total_bid_size = sum(b[1] for b in bids)
            total_ask_size = sum(a[1] for a in asks)

            return jsonify({
                'symbol': sym, 'source': 'coinbase', 'levels': 'full',
                'bids': bids, 'asks': asks,
                'best_bid': best_bid, 'best_ask': best_ask,
                'spread': round(spread, 4), 'spread_pct': round(spread_pct, 4),
                'mid_price': round(mid_price, 4),
                'max_size': max_size,
                'total_bid_liquidity': round(total_bid_size, 4),
                'total_ask_liquidity': round(total_ask_size, 4),
            })

        else:
            # Alpaca IEX — best bid/ask only (free tier)
            price = _get_current_price(sym)
            quote_data = _quote_yfinance(sym) if not KEYS_SET else None
            bid = ask = price or 0
            try:
                if KEYS_SET:
                    from alpaca.data.requests import StockLatestQuoteRequest as SLQR
                    q = data_client.get_stock_latest_quote(SLQR(symbol_or_symbols=sym, feed='iex'))
                    if sym in q:
                        bid = float(q[sym].bid_price or 0)
                        ask = float(q[sym].ask_price or 0)
            except Exception:
                bid = ask = price or 0

            spread = ask - bid if bid and ask else 0
            mid = (bid + ask) / 2 if bid and ask else bid

            return jsonify({
                'symbol': sym, 'source': 'alpaca_iex', 'levels': 'top_only',
                'bids': [[bid, 0, 0]] if bid else [],
                'asks': [[ask, 0, 0]] if ask else [],
                'best_bid': bid, 'best_ask': ask,
                'spread': round(spread, 4),
                'spread_pct': round(spread / bid * 100, 4) if bid else 0,
                'mid_price': round(mid, 4),
                'max_size': 0,
                'total_bid_liquidity': 0,
                'total_ask_liquidity': 0,
                'note': 'Alpaca IEX free tier — best bid/ask only. Upgrade to SIP for full depth.',
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── Markets: Futures / Forex / Options ───────────────────────────────────────

_FUTURES_LIST = [
    {'symbol': 'ES=F',  'display': 'ES',      'name': 'S&P 500 E-mini'},
    {'symbol': 'NQ=F',  'display': 'NQ',      'name': 'NASDAQ E-mini'},
    {'symbol': 'YM=F',  'display': 'YM',      'name': 'Dow Jones E-mini'},
    {'symbol': 'RTY=F', 'display': 'RTY',     'name': 'Russell 2000 E-mini'},
    {'symbol': 'CL=F',  'display': 'CL',      'name': 'Crude Oil WTI'},
    {'symbol': 'GC=F',  'display': 'GC',      'name': 'Gold'},
    {'symbol': 'SI=F',  'display': 'SI',      'name': 'Silver'},
    {'symbol': 'NG=F',  'display': 'NG',      'name': 'Natural Gas'},
    {'symbol': 'ZB=F',  'display': 'ZB',      'name': 'US 30Y T-Bond'},
    {'symbol': 'ZN=F',  'display': 'ZN',      'name': 'US 10Y T-Note'},
    {'symbol': 'BTC=F', 'display': 'BTC',     'name': 'Bitcoin Futures'},
    {'symbol': 'ETH=F', 'display': 'ETH',     'name': 'Ether Futures'},
]

_FOREX_LIST = [
    {'symbol': 'EURUSD=X', 'display': 'EUR/USD', 'name': 'Euro / US Dollar'},
    {'symbol': 'GBPUSD=X', 'display': 'GBP/USD', 'name': 'British Pound / USD'},
    {'symbol': 'USDJPY=X', 'display': 'USD/JPY', 'name': 'US Dollar / Japanese Yen'},
    {'symbol': 'USDCHF=X', 'display': 'USD/CHF', 'name': 'US Dollar / Swiss Franc'},
    {'symbol': 'AUDUSD=X', 'display': 'AUD/USD', 'name': 'Australian Dollar / USD'},
    {'symbol': 'USDCAD=X', 'display': 'USD/CAD', 'name': 'US Dollar / Canadian Dollar'},
    {'symbol': 'NZDUSD=X', 'display': 'NZD/USD', 'name': 'New Zealand Dollar / USD'},
    {'symbol': 'EURGBP=X', 'display': 'EUR/GBP', 'name': 'Euro / British Pound'},
    {'symbol': 'EURJPY=X', 'display': 'EUR/JPY', 'name': 'Euro / Japanese Yen'},
    {'symbol': 'GBPJPY=X', 'display': 'GBP/JPY', 'name': 'British Pound / Yen'},
    {'symbol': 'USDCNY=X', 'display': 'USD/CNY', 'name': 'US Dollar / Chinese Yuan'},
    {'symbol': 'USDINR=X', 'display': 'USD/INR', 'name': 'US Dollar / Indian Rupee'},
]

_markets_cache: dict = {}
_MARKETS_TTL = 45  # seconds

_HEATMAP_CACHE: tuple | None = None
_HEATMAP_TTL   = 300  # 5 minutes

_MCAP_WEIGHTS = {
    'AAPL':100,'MSFT':100,'NVDA':95,'GOOGL':80,'AMZN':80,
    'META':65,'TSLA':55,'AVGO':50,'LLY':48,'JPM':45,
    'V':40,'UNH':40,'XOM':38,'COST':35,'MA':35,
    'HD':32,'WMT':32,'NFLX':30,'ORCL':30,'BAC':28,
    'JNJ':28,'ABBV':26,'CRM':25,'AMD':25,'GS':22,
    'ADBE':22,'QCOM':20,'T':18,'VZ':16,'AMGN':15,
    'TMO':15,'DHR':14,'CVX':14,'COP':13,'MS':13,
    'AXP':12,'BLK':12,'SCHW':11,'REGN':11,'VRTX':10,
}
_SECTOR_MAP = {
    'AAPL':'Technology','MSFT':'Technology','NVDA':'Technology','GOOGL':'Technology',
    'META':'Technology','TSLA':'Technology','AVGO':'Technology','ADBE':'Technology',
    'CRM':'Technology','AMD':'Technology','INTC':'Technology','QCOM':'Technology',
    'TXN':'Technology','ORCL':'Technology','IBM':'Technology','INTU':'Technology',
    'NOW':'Technology','SNOW':'Technology','PLTR':'Technology','NET':'Technology',
    'CRWD':'Technology','ZS':'Technology','PANW':'Technology','DDOG':'Technology',
    'MDB':'Technology','COIN':'Technology','UBER':'Technology','LYFT':'Technology',
    'ABNB':'Consumer','BKNG':'Consumer','DASH':'Consumer','RBLX':'Technology',
    'ARM':'Technology','SMCI':'Technology','ANET':'Technology','MRVL':'Technology',
    'KLAC':'Technology','LRCX':'Technology','AMAT':'Technology','ASML':'Technology',
    'MU':'Technology','WDC':'Technology','HOOD':'Financials',
    'JPM':'Financials','BAC':'Financials','GS':'Financials','MS':'Financials',
    'V':'Financials','MA':'Financials','AXP':'Financials','BLK':'Financials',
    'C':'Financials','WFC':'Financials','SCHW':'Financials','BX':'Financials',
    'KKR':'Financials','APO':'Financials','SPGI':'Financials','MCO':'Financials',
    'UNH':'Healthcare','LLY':'Healthcare','JNJ':'Healthcare','PFE':'Healthcare',
    'MRK':'Healthcare','ABBV':'Healthcare','TMO':'Healthcare','DHR':'Healthcare',
    'AMGN':'Healthcare','GILD':'Healthcare','REGN':'Healthcare','VRTX':'Healthcare',
    'ISRG':'Healthcare','BSX':'Healthcare','ELV':'Healthcare','CI':'Healthcare',
    'HUM':'Healthcare','CVS':'Healthcare','BIIB':'Healthcare','MRNA':'Healthcare',
    'WMT':'Consumer','COST':'Consumer','HD':'Consumer','TGT':'Consumer',
    'NKE':'Consumer','MCD':'Consumer','SBUX':'Consumer','CMG':'Consumer',
    'LOW':'Consumer','TJX':'Consumer','ROST':'Consumer','DG':'Consumer',
    'DKNG':'Consumer','YUM':'Consumer',
    'NFLX':'Communication','DIS':'Communication','CMCSA':'Communication',
    'T':'Communication','VZ':'Communication','SNAP':'Communication','PINS':'Communication',
    'RDDT':'Communication',
    'XOM':'Energy','CVX':'Energy','COP':'Energy','SLB':'Energy','OXY':'Energy',
    'EOG':'Energy','PSX':'Energy','MPC':'Energy','VLO':'Energy','HES':'Energy',
    'HAL':'Energy','BKR':'Energy','DVN':'Energy','AR':'Energy','EQT':'Energy',
    'CAT':'Industrials','DE':'Industrials','HON':'Industrials','BA':'Industrials',
    'GE':'Industrials','UPS':'Industrials','FDX':'Industrials','RTX':'Industrials',
    'LMT':'Industrials','NOC':'Industrials','EMR':'Industrials','ETN':'Industrials',
    'LIN':'Materials','APD':'Materials','NEM':'Materials','FCX':'Materials',
    'NUE':'Materials','CF':'Materials','MOS':'Materials','ALB':'Materials',
    'PLD':'Real Estate','AMT':'Real Estate','EQIX':'Real Estate',
    'WELL':'Real Estate','SPG':'Real Estate','O':'Real Estate',
    'SPY':'ETF','QQQ':'ETF','IWM':'ETF','DIA':'ETF','VTI':'ETF',
    'XLK':'ETF','XLF':'ETF','XLE':'ETF','XLV':'ETF','XLI':'ETF',
    'SMH':'ETF','SOXX':'ETF','IBB':'ETF','ARKK':'ETF','GLD':'ETF','TLT':'ETF',
}

def _get_market_quotes(instruments: list) -> list:
    import yfinance as yf
    result = []
    for inst in instruments:
        sym = inst['symbol']
        try:
            hist   = yf.Ticker(sym).history(period='5d')
            closes = hist['Close'].dropna()
            highs  = hist['High'].dropna()
            lows   = hist['Low'].dropna()
            if len(closes) >= 2:
                price = float(closes.iloc[-1]); prev = float(closes.iloc[-2])
                high  = float(highs.iloc[-1]);  low  = float(lows.iloc[-1])
            elif len(closes) == 1:
                price = float(closes.iloc[0]);  prev = 0.0
                high  = float(highs.iloc[0]);   low  = float(lows.iloc[0])
            else:
                price = prev = high = low = 0.0
            change     = round(price - prev, 6) if prev else 0.0
            change_pct = round((change / prev) * 100, 3) if prev else 0.0
            result.append({
                'symbol': sym, 'display': inst['display'], 'name': inst['name'],
                'price': round(price, 6), 'prev_close': round(prev, 6),
                'change': change, 'change_pct': change_pct,
                'high': round(high, 6), 'low': round(low, 6),
            })
        except Exception as e:
            print(f'[TradeSimulator] market quote failed {sym}: {e}')
            result.append({'symbol': sym, 'display': inst['display'], 'name': inst['name'],
                           'price': 0.0, 'prev_close': 0.0, 'change': 0.0,
                           'change_pct': 0.0, 'high': 0.0, 'low': 0.0})
    return result

_CRYPTO_LIST = [
    {'symbol': 'BTC-USD',  'display': 'BTC/USD',  'name': 'Bitcoin'},
    {'symbol': 'ETH-USD',  'display': 'ETH/USD',  'name': 'Ethereum'},
    {'symbol': 'SOL-USD',  'display': 'SOL/USD',  'name': 'Solana'},
    {'symbol': 'BNB-USD',  'display': 'BNB/USD',  'name': 'BNB'},
    {'symbol': 'XRP-USD',  'display': 'XRP/USD',  'name': 'XRP'},
    {'symbol': 'ADA-USD',  'display': 'ADA/USD',  'name': 'Cardano'},
    {'symbol': 'AVAX-USD', 'display': 'AVAX/USD', 'name': 'Avalanche'},
    {'symbol': 'DOGE-USD', 'display': 'DOGE/USD', 'name': 'Dogecoin'},
    {'symbol': 'LINK-USD', 'display': 'LINK/USD', 'name': 'Chainlink'},
    {'symbol': 'ATOM-USD', 'display': 'ATOM/USD', 'name': 'Cosmos'},
    {'symbol': 'AAVE-USD', 'display': 'AAVE/USD', 'name': 'Aave'},
    {'symbol': 'LTC-USD',  'display': 'LTC/USD',  'name': 'Litecoin'},
    {'symbol': 'BCH-USD',  'display': 'BCH/USD',  'name': 'Bitcoin Cash'},
    {'symbol': 'XLM-USD',  'display': 'XLM/USD',  'name': 'Stellar'},
    {'symbol': 'TRX-USD',  'display': 'TRX/USD',  'name': 'TRON'},
]

@app.route('/api/markets/crypto')
def get_crypto():
    now = _time.time()
    if 'crypto' in _markets_cache:
        data, ts = _markets_cache['crypto']
        if now - ts < _MARKETS_TTL:
            return jsonify(data)
    data = _get_market_quotes(_CRYPTO_LIST)
    _markets_cache['crypto'] = (data, now)
    return jsonify(data)

@app.route('/api/markets/futures')
def get_futures():
    now = _time.time()
    if 'futures' in _markets_cache:
        data, ts = _markets_cache['futures']
        if now - ts < _MARKETS_TTL:
            return jsonify(data)
    data = _get_market_quotes(_FUTURES_LIST)
    _markets_cache['futures'] = (data, now)
    return jsonify(data)

@app.route('/api/markets/forex')
def get_forex():
    now = _time.time()
    if 'forex' in _markets_cache:
        data, ts = _markets_cache['forex']
        if now - ts < _MARKETS_TTL:
            return jsonify(data)
    data = _get_market_quotes(_FOREX_LIST)
    _markets_cache['forex'] = (data, now)
    return jsonify(data)

@app.route('/api/market/heatmap')
def market_heatmap():
    """Market heatmap: top companies by sector with % change. Cached 5 min."""
    global _HEATMAP_CACHE
    now = _time.time()
    if _HEATMAP_CACHE and now - _HEATMAP_CACHE[1] < _HEATMAP_TTL:
        return jsonify(_HEATMAP_CACHE[0])

    equity_syms = [s for s in _AI_UNIVERSE
                   if not s.endswith('-USD') and not s.endswith('=X')
                   and not s.endswith('=F')][:80]
    crypto_syms = [s for s in _AI_UNIVERSE if s.endswith('-USD')][:15]
    forex_syms  = ['EURUSD=X','GBPUSD=X','USDJPY=X','AUDUSD=X','USDCAD=X',
                   'USDCHF=X','NZDUSD=X','EURGBP=X','EURJPY=X','GBPJPY=X']
    futures_syms = ['ES=F','NQ=F','CL=F','BZ=F','GC=F','SI=F','NG=F','ZC=F','ZS=F']

    result = {'sectors': {}, 'crypto': [], 'forex': [], 'futures': [], 'updated_at': now}

    try:
        import yfinance as yf
        bulk = yf.download(equity_syms, period='2d', interval='1d',
                           auto_adjust=True, progress=False, threads=True,
                           group_by='ticker', timeout=12)
        for sym in equity_syms:
            try:
                df = bulk[sym] if len(equity_syms) > 1 else bulk
                if df is None or df.empty or len(df) < 2:
                    continue
                closes = list(df['Close'].dropna())
                if len(closes) < 2:
                    continue
                chg = (closes[-1] - closes[-2]) / closes[-2] * 100
                sector = _SECTOR_MAP.get(sym, 'Other')
                weight = _MCAP_WEIGHTS.get(sym, 8)
                if sector not in result['sectors']:
                    result['sectors'][sector] = []
                result['sectors'][sector].append({
                    'symbol': sym, 'chg_pct': round(chg, 2),
                    'price': round(closes[-1], 2), 'weight': weight,
                })
            except Exception:
                pass
    except Exception:
        pass

    # Crypto + Forex + Futures: bulk download for real change %
    other_syms = crypto_syms + forex_syms + futures_syms
    try:
        import yfinance as yf
        obulk = yf.download(other_syms, period='2d', interval='1d',
                            auto_adjust=True, progress=False, threads=True,
                            group_by='ticker', timeout=12)
        for sym in other_syms:
            try:
                df = obulk[sym] if len(other_syms) > 1 else obulk
                if df is None or df.empty or len(df) < 1:
                    continue
                if hasattr(df.columns, 'levels'):
                    df.columns = df.columns.get_level_values(0)
                closes = [float(x) for x in df['Close'].dropna()]
                if not closes:
                    continue
                price = closes[-1]
                chg = ((closes[-1] - closes[-2]) / closes[-2] * 100) if len(closes) >= 2 and closes[-2] else 0.0
                if sym.endswith('-USD'):
                    result['crypto'].append({'symbol': sym, 'chg_pct': round(chg,2), 'price': round(price,4), 'weight': 10})
                elif sym.endswith('=X'):
                    result['forex'].append({'symbol': sym.replace('=X',''), 'chg_pct': round(chg,3), 'price': round(price,5), 'weight': 5})
                elif sym.endswith('=F'):
                    result['futures'].append({'symbol': sym, 'chg_pct': round(chg,2), 'price': round(price,2), 'weight': 8})
            except Exception:
                continue
    except Exception:
        pass

    _HEATMAP_CACHE = (result, now)
    return jsonify(result)

def _bs_price(S, K, T, r, sigma, option_type='call'):
    """Full Black-Scholes option price."""
    if S <= 0 or K <= 0 or sigma <= 0:
        return max(0.0, (S - K) if option_type == 'call' else (K - S))
    if T <= 0:
        return max(0.0, (S - K) if option_type == 'call' else (K - S))
    try:
        from statistics import NormalDist
        nd = NormalDist()
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        if option_type == 'call':
            return S * nd.cdf(d1) - K * math.exp(-r * T) * nd.cdf(d2)
        else:
            return K * math.exp(-r * T) * nd.cdf(-d2) - S * nd.cdf(-d1)
    except Exception:
        return max(0.0, (S - K) if option_type == 'call' else (K - S))

def _bs_greeks(S, K, T, r, sigma, option_type='call'):
    if T <= 0 or sigma <= 0 or S <= 0:
        return {'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0, 'prob_itm': 0}
    try:
        from statistics import NormalDist
        nd = NormalDist()
        d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        pdf_d1 = nd.pdf(d1)
        if option_type == 'call':
            delta = nd.cdf(d1)
            prob_itm = nd.cdf(d2)
            theta = (-(S * pdf_d1 * sigma) / (2*math.sqrt(T)) - r*K*math.exp(-r*T)*nd.cdf(d2)) / 365
        else:
            delta = nd.cdf(d1) - 1
            prob_itm = nd.cdf(-d2)
            theta = (-(S * pdf_d1 * sigma) / (2*math.sqrt(T)) + r*K*math.exp(-r*T)*nd.cdf(-d2)) / 365
        gamma = pdf_d1 / (S * sigma * math.sqrt(T))
        vega = S * pdf_d1 * math.sqrt(T) / 100
        return {'delta': round(delta,4), 'gamma': round(gamma,6), 'theta': round(theta,4), 'vega': round(vega,4), 'prob_itm': round(prob_itm,4)}
    except Exception:
        return {'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0, 'prob_itm': 0}

@app.route('/api/options/<symbol>')
def get_options(symbol):
    symbol = symbol.upper()
    expiry = request.args.get('expiry', '')
    cache_key = f'options:{symbol}:{expiry}'
    now = _time.time()
    if cache_key in _markets_cache:
        data, ts = _markets_cache[cache_key]
        if now - ts < 120:
            return jsonify(data)
    try:
        import yfinance as yf
        ticker      = yf.Ticker(symbol)
        expirations = list(ticker.options or [])
        if not expirations:
            return jsonify({'symbol': symbol, 'expirations': [], 'calls': [], 'puts': [], 'selected': None})
        selected = expiry if expiry in expirations else expirations[0]
        chain    = ticker.option_chain(selected)

        # Compute time-to-expiry and risk-free rate
        from datetime import datetime as _dt
        try:
            expiry_dt = _dt.strptime(selected, '%Y-%m-%d')
            days_to_expiry = max((expiry_dt - _dt.utcnow()).days, 0)
        except Exception:
            days_to_expiry = 30
        T = days_to_expiry / 365.0
        r_rate = 0.045

        # Get current underlying price for ATM reference
        try:
            _hist  = ticker.history(period='1d')
            _hist_closes = _hist['Close'].dropna()
            spot  = float(_hist_closes.iloc[-1]) if len(_hist_closes) else 0.0
        except Exception:
            spot = 0.0

        def _df(df, opt_type='call'):
            rows = []
            df = df.fillna(0)  # NaN is truthy; int(NaN) raises ValueError
            for _, r in df.iterrows():
                raw_iv = float(r.get('impliedVolatility', 0))
                greeks = _bs_greeks(spot, float(r.get('strike', 0)), T, r_rate, raw_iv, opt_type)
                opt_last = float(r.get('lastPrice', 0)) or float(r.get('bid', 0))
                scenarios = {}
                K_strike = float(r.get('strike', 0))
                # Use a minimum IV floor so zero-IV options still produce a smooth curve
                iv_for_scenarios = max(raw_iv, 0.10)
                for chg in [-0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15]:
                    new_S = spot * (1 + chg)
                    est = _bs_price(new_S, K_strike, T, r_rate, iv_for_scenarios, opt_type)
                    chg_pct = round(chg * 100)
                    key = f'{chg_pct:+d}%' if chg_pct != 0 else '0%'
                    scenarios[key] = round(est, 2)
                rows.append({
                    'strike':          round(float(r.get('strike', 0)), 4),
                    'bid':             round(float(r.get('bid', 0)), 4),
                    'ask':             round(float(r.get('ask', 0)), 4),
                    'last':            round(float(r.get('lastPrice', 0)), 4),
                    'iv':              round(raw_iv * 100, 1),
                    'volume':          int(float(r.get('volume', 0))),
                    'oi':              int(float(r.get('openInterest', 0))),
                    'itm':             bool(r.get('inTheMoney', False)),
                    'change':          round(float(r.get('change', 0)), 4),
                    'change_pct':      round(float(r.get('percentChange', 0)), 2),
                    'greeks':          greeks,
                    'scenarios':       scenarios,
                    'days_to_expiry':  days_to_expiry,
                })
            return rows

        data = {
            'symbol':      symbol,
            'spot':        round(spot, 4),
            'expirations': expirations[:16],
            'selected':    selected,
            'calls':       _df(chain.calls, 'call'),
            'puts':        _df(chain.puts, 'put'),
        }
        _markets_cache[cache_key] = (data, now)
        return jsonify(data)
    except Exception as e:
        print(f'[TradeSimulator] options failed for {symbol}: {e}')
        return jsonify({'error': str(e)}), 500

# ── Watchlist ──────────────────────────────────────────────────────────────────
@app.route('/api/watchlist', methods=['GET'])
def get_watchlist():
    pid = request.args.get('portfolio_id', 1, type=int)
    if pid == 0:
        with _get_db() as conn:
            rows = conn.execute('SELECT DISTINCT symbol FROM holdings ORDER BY symbol').fetchall()
        sym_rows = [(r['symbol'], False) for r in rows]
    else:
        with _get_db() as conn:
            rows = conn.execute(
                'SELECT symbol, priority FROM watchlist_items WHERE portfolio_id = ? ORDER BY rowid',
                (pid,)
            ).fetchall()
        sym_rows = [(r['symbol'], bool(r['priority'])) for r in rows]
    result = []
    for sym, priority in sym_rows:
        try:
            q = _quote_yfinance(sym)
            result.append({'symbol': sym, 'price': q['bid'], 'bid': q['bid'], 'ask': q['bid'],
                           'change': q.get('change', 0.0), 'change_pct': q.get('change_pct', 0.0),
                           'priority': priority})
        except:
            result.append({'symbol': sym, 'price': None, 'change': 0.0, 'change_pct': 0.0, 'priority': priority})
    return jsonify(result)

@app.route('/api/watchlist', methods=['POST'])
def update_watchlist():
    data   = request.json
    action = data.get('action', 'add')
    symbol = data.get('symbol', '').upper()
    pid    = data.get('portfolio_id', 1)
    if pid == 0:
        return jsonify({'error': 'Real Holdings watchlist is auto-generated from your holdings'}), 400
    with _get_db() as conn:
        if action == 'add' and symbol:
            conn.execute('INSERT OR IGNORE INTO watchlist_items (portfolio_id, symbol) VALUES (?,?)', (pid, symbol))
        elif action == 'remove' and symbol:
            conn.execute('DELETE FROM watchlist_items WHERE portfolio_id = ? AND symbol = ?', (pid, symbol))
        elif action == 'priority' and symbol:
            row = conn.execute(
                'SELECT priority FROM watchlist_items WHERE portfolio_id = ? AND symbol = ?',
                (pid, symbol)
            ).fetchone()
            if row and row['priority']:
                # Already priority — toggle off
                conn.execute('UPDATE watchlist_items SET priority = 0 WHERE portfolio_id = ? AND symbol = ?', (pid, symbol))
            else:
                # Set as priority, clear any previous
                conn.execute('UPDATE watchlist_items SET priority = 0 WHERE portfolio_id = ?', (pid,))
                conn.execute('UPDATE watchlist_items SET priority = 1 WHERE portfolio_id = ? AND symbol = ?', (pid, symbol))
    return jsonify({'status': 'ok'})

_MARKET_SYMBOLS = ['SPY','QQQ','DIA','IWM','AAPL','MSFT','NVDA','TSLA','AMZN','GOOGL','META','JPM','BAC','AMD','NFLX']

@app.route('/api/market-prices')
def market_prices():
    result = []
    for sym in _MARKET_SYMBOLS:
        try:
            q = _quote_yfinance(sym)
            result.append({'symbol': sym, 'price': q['bid'],
                           'change': q.get('change', 0.0), 'change_pct': q.get('change_pct', 0.0)})
        except:
            pass
    return jsonify(result)

@app.route('/api/subscribe/<symbol>', methods=['POST'])
def subscribe_symbol(symbol):
    sym = symbol.upper()
    _subscribed_symbols.add(sym)
    if KEYS_SET:
        try:
            from alpaca_stream import subscribe as alp_sub
            alp_sub(sym)
        except Exception:
            pass
    if FINNHUB_KEYS_SET:
        try:
            from finnhub_stream import subscribe as fh_sub
            fh_sub(sym)
        except Exception:
            pass
    return jsonify({'status': 'subscribed', 'symbol': sym})


@app.route('/api/stream/status', methods=['GET'])
def stream_status():
    streaming = _stream_manager.streaming_symbols if _stream_manager else {}
    polling   = list(_subscribed_symbols - set(streaming.keys()))
    return jsonify({'streaming': streaming, 'polling': polling})

# ── Asset search ───────────────────────────────────────────────────────────────
@app.route('/api/assets/search')
def search_assets():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    q_upper = q.upper()

    if KEYS_SET:
        if not _asset_cache_loaded:
            threading.Thread(target=_load_assets, daemon=True).start()
        if _asset_cache_loaded:
            results = []
            for a in _asset_cache:
                sym = a['symbol']; name = a['name'].upper()
                if sym == q_upper:           results.append((0, a))
                elif sym.startswith(q_upper): results.append((1, a))
                elif q_upper in name:         results.append((2, a))
            results.sort(key=lambda x: (x[0], x[1]['symbol']))
            return jsonify([r[1] for r in results[:12]])

    if AV_KEYS_SET:
        av = _search_alpha_vantage(q)
        if av:
            return jsonify(av[:12])

    try:
        import yfinance as yf
        search_cls = getattr(yf, 'Search', None)
        if search_cls:
            s      = search_cls(q, max_results=20)
            quotes = getattr(s, 'quotes', None) or []
            results = [{'symbol': i.get('symbol',''), 'name': i.get('shortname') or i.get('longname',''), 'exchange': i.get('exchange','')}
                       for i in quotes
                       if i.get('quoteType') in ('EQUITY','ETF') and '.' not in i.get('symbol','') and i.get('symbol')]
            if results:
                return jsonify(results[:12])
    except Exception as e:
        print(f'[TradeSimulator] yfinance Search failed: {e}')

    if not _ticker_db_loaded:
        threading.Thread(target=_load_ticker_db, daemon=True).start()
    search_list = _ticker_db if _ticker_db_loaded else _STATIC_ASSETS_DICTS
    results = []
    for a in search_list:
        sym = a['symbol']; name = a['name'].upper()
        if sym == q_upper:            results.append((0, a))
        elif sym.startswith(q_upper): results.append((1, a))
        elif q_upper in name:         results.append((2, a))
    results.sort(key=lambda x: (x[0], x[1]['symbol']))
    return jsonify([r[1] for r in results[:12]])

# ── Holdings CRUD (personal tracker — separate from simulation) ────────────────
def _fetch_price_on_date(symbol: str, date_str: str) -> float | None:
    from datetime import date as _date
    if KEYS_SET:
        try:
            d     = _date.fromisoformat(date_str)
            start = datetime.combine(d, datetime.min.time())
            end   = start + timedelta(days=4)
            req   = StockBarsRequest(symbol_or_symbols=symbol,
                                     timeframe=TimeFrame(1, TimeFrameUnit.Day),
                                     start=start, end=min(end, datetime.utcnow()), feed='iex')
            bars = data_client.get_stock_bars(req).get(symbol, [])
            if bars:
                return float(bars[0].close)
        except Exception as e:
            print(f'[TradeSimulator] Alpaca price lookup failed for {symbol} on {date_str}: {e}')
    # yfinance fallback — uses Ticker.history() which avoids MultiIndex issues
    try:
        import yfinance as yf
        from datetime import date as _d2
        d     = _d2.fromisoformat(date_str)
        end_d = d + timedelta(days=10)   # extra window for weekends/holidays
        hist  = yf.Ticker(symbol).history(start=str(d), end=str(end_d))
        if not hist.empty:
            closes = hist['Close'].dropna()
            if not closes.empty:
                return round(float(closes.iloc[0]), 4)
    except Exception as e:
        print(f'[TradeSimulator] yfinance price lookup failed for {symbol} on {date_str}: {e}')
    return None

def _holding_row(row, current_prices: dict) -> dict:
    price_now = current_prices.get(row['symbol'])
    valid     = price_now is not None and price_now > 0
    shares    = row['shares']
    cost      = row['buy_price'] * shares
    value     = price_now * shares if valid else None
    pnl       = (value - cost) if value is not None else None
    pnl_pct   = (pnl / cost * 100) if (pnl is not None and cost) else None
    return {
        'id': row['id'], 'symbol': row['symbol'], 'shares': shares,
        'buy_date': row['buy_date'], 'buy_price': row['buy_price'], 'note': row['note'],
        'cost_basis':    round(cost, 2),
        'current_price': round(price_now, 2) if valid else None,
        'market_value':  round(value, 2)     if valid else None,
        'pnl':           round(pnl, 2)       if pnl is not None else None,
        'pnl_pct':       round(pnl_pct, 2)   if pnl_pct is not None else None,
    }

@app.route('/api/holdings', methods=['GET'])
def get_holdings():
    with _get_db() as conn:
        rows = conn.execute('SELECT * FROM holdings ORDER BY created_at DESC').fetchall()
    if not rows:
        return jsonify([])
    symbols = list({r['symbol'] for r in rows})
    current_prices = {}
    if KEYS_SET:
        try:
            from alpaca.data.requests import StockLatestQuoteRequest as SLQR
            req    = SLQR(symbol_or_symbols=symbols, feed='iex')
            quotes = data_client.get_stock_latest_quote(req)
            for sym, q in quotes.items():
                current_prices[sym] = (float(q.bid_price) + float(q.ask_price)) / 2
        except Exception as e:
            print(f'[TradeSimulator] holdings price fetch failed: {e}')
    if not current_prices:
        for sym in symbols:
            try:
                current_prices[sym] = _quote_yfinance(sym)['bid']
            except:
                pass
    return jsonify([_holding_row(r, current_prices) for r in rows])

@app.route('/api/holdings', methods=['POST'])
def add_holding():
    data      = request.json
    symbol    = data.get('symbol','').upper().strip()
    shares    = float(data.get('shares', 0))
    buy_date  = data.get('buy_date', '')
    buy_price = data.get('buy_price')
    note      = data.get('note', '')
    if not symbol or shares <= 0 or not buy_date:
        return jsonify({'error': 'symbol, shares, and buy_date are required'}), 400
    if buy_price is None or buy_price == '':
        buy_price = _fetch_price_on_date(symbol, buy_date)
    if buy_price is None:
        return jsonify({'error': f'Could not fetch price for {symbol} on {buy_date}. Enter price manually.'}), 400
    with _get_db() as conn:
        cur = conn.execute(
            'INSERT INTO holdings (symbol, shares, buy_date, buy_price, note) VALUES (?,?,?,?,?)',
            (symbol, shares, buy_date, float(buy_price), note)
        )
    return jsonify({'id': cur.lastrowid, 'symbol': symbol, 'shares': shares,
                    'buy_date': buy_date, 'buy_price': float(buy_price)})

@app.route('/api/holdings/<int:holding_id>', methods=['DELETE'])
def delete_holding(holding_id):
    with _get_db() as conn:
        conn.execute('DELETE FROM holdings WHERE id = ?', (holding_id,))
    return jsonify({'status': 'deleted'})

# ── News feed ─────────────────────────────────────────────────────────────────
_news_cache: dict[str, tuple[list, float]] = {}
_NEWS_TTL = 1800  # 30 minutes — reduce API call frequency
_FINNHUB_GENERAL_LAST = 0.0  # rate-limit tracker for general news

def _fetch_news_av(symbol: str = '', topics: str = 'technology,finance') -> list:
    """Fetch from Alpha Vantage NEWS_SENTIMENT."""
    if not AV_KEYS_SET:
        return []
    try:
        import requests as _req
        params = {'function': 'NEWS_SENTIMENT', 'apikey': AV_KEY, 'limit': 20, 'sort': 'LATEST'}
        if symbol:
            params['tickers'] = symbol
        else:
            params['topics'] = topics
        r = _req.get('https://www.alphavantage.co/query', params=params, timeout=8)
        feed = r.json().get('feed', [])
        result = []
        for item in feed[:15]:
            # Find ticker-specific sentiment if symbol provided
            sentiment_score = 0.0
            sentiment_label = 'Neutral'
            if symbol and item.get('ticker_sentiment'):
                for ts in item['ticker_sentiment']:
                    if ts.get('ticker') == symbol:
                        sentiment_score = float(ts.get('ticker_sentiment_score', 0))
                        sentiment_label = ts.get('ticker_sentiment_label', 'Neutral')
                        break
            else:
                sentiment_score = float(item.get('overall_sentiment_score', 0))
                sentiment_label = item.get('overall_sentiment_label', 'Neutral')
            result.append({
                'title':     item.get('title', ''),
                'summary':   item.get('summary', '')[:200],
                'url':       item.get('url', ''),
                'source':    item.get('source', ''),
                'published': item.get('time_published', ''),
                'sentiment_score': round(sentiment_score, 3),
                'sentiment_label': sentiment_label,  # Bullish/Somewhat Bullish/Neutral/Somewhat Bearish/Bearish
                'banner_image': item.get('banner_image', ''),
            })
        return result
    except Exception as e:
        print(f'[TradeSimulator] AV news fetch failed: {e}')
        return []

def _fetch_news_polygon(symbol: str = '') -> list:
    """Fallback: Polygon.io news."""
    if not POLYGON_KEYS_SET:
        return []
    try:
        import requests as _req
        params = {'apiKey': POLYGON_KEY, 'limit': 10, 'order': 'desc'}
        if symbol:
            params['ticker'] = symbol
        r = _req.get('https://api.polygon.io/v2/reference/news', params=params, timeout=8)
        results = r.json().get('results', [])
        return [{
            'title':     a.get('title', ''),
            'summary':   a.get('description', '')[:200],
            'url':       a.get('article_url', ''),
            'source':    a.get('publisher', {}).get('name', ''),
            'published': a.get('published_utc', ''),
            'sentiment_score': 0.0,
            'sentiment_label': 'Neutral',
            'banner_image':    a.get('image_url', ''),
        } for a in results]
    except Exception as e:
        print(f'[TradeSimulator] Polygon news fetch failed: {e}')
        return []

def _yf_news_to_articles(raw: list) -> list:
    """Normalize yfinance Ticker.news items to the app's article format."""
    from datetime import datetime
    result = []
    for item in raw:
        c = item.get('content', {})
        title = c.get('title', '')
        if not title:
            continue
        pub_date = c.get('pubDate', '')
        try:
            dt = datetime.fromisoformat(pub_date.replace('Z', '+00:00'))
            published = dt.strftime('%Y%m%dT%H%M%S')
        except Exception:
            published = ''
        thumb = c.get('thumbnail') or {}
        banner = ''
        for res in thumb.get('resolutions', []):
            if res.get('width', 9999) <= 500:
                banner = res.get('url', '')
                break
        if not banner:
            banner = thumb.get('originalUrl', '')
        url = ((c.get('canonicalUrl') or {}).get('url')
               or (c.get('clickThroughUrl') or {}).get('url', ''))
        source = (c.get('provider') or {}).get('displayName', 'Yahoo Finance')
        result.append({
            'title':           title,
            'summary':         (c.get('summary') or '')[:200],
            'url':             url,
            'source':          source,
            'published':       published,
            'sentiment_score': 0.0,
            'sentiment_label': 'Neutral',
            'banner_image':    banner,
        })
    return result

def _fetch_news_yfinance(symbol: str) -> list:
    """Fetch symbol news via yfinance — no API key needed."""
    try:
        import yfinance as yf
        raw = yf.Ticker(symbol).news or []
        return _yf_news_to_articles(raw[:15])
    except Exception as e:
        print(f'[TradeSimulator] yfinance symbol news failed ({symbol}): {e}')
        return []

def _fetch_general_news_yfinance() -> list:
    """Aggregate general market news from major tickers via yfinance."""
    try:
        import yfinance as yf
        tickers = [
            'AAPL', 'NVDA', 'MSFT', 'AMZN', 'GOOGL', 'META', 'TSLA',
            'SPY', 'QQQ', 'NFLX', 'AMD', 'INTC', 'JPM', 'GS', 'BAC',
            'XOM', 'CVX', 'BRK-B', 'V', 'MA', 'COIN', 'PLTR', 'HOOD',
        ]
        seen, result = set(), []
        for sym in tickers:
            if len(result) >= 40:
                break
            try:
                raw = yf.Ticker(sym).news or []
                for art in _yf_news_to_articles(raw[:6]):
                    if art['title'] not in seen:
                        seen.add(art['title'])
                        result.append(art)
            except Exception:
                continue
        return result
    except Exception as e:
        print(f'[TradeSimulator] yfinance general news failed: {e}')
        return []


def _fetch_news_finnhub_general() -> list:
    """Fetch market-moving news from Finnhub general news endpoint."""
    if not FINNHUB_KEYS_SET:
        return []
    try:
        import requests as _req
        r = _req.get(
            'https://finnhub.io/api/v1/news',
            params={'category': 'general', 'token': FINNHUB_KEY},
            timeout=5,
        )
        r.raise_for_status()
        items = r.json() or []
        result = []
        for item in items[:40]:
            headline = (item.get('headline') or '').strip()
            if not headline:
                continue
            result.append({
                'title':            headline,
                'source':           item.get('source', 'Finnhub'),
                'url':              item.get('url', ''),
                'published_at':     item.get('datetime', 0),
                'summary':          item.get('summary', ''),
                'ticker_sentiment': ([{'ticker': item['related'], 'sentiment_label': 'neutral', 'sentiment_score': 0}]
                                     if item.get('related') else []),
                'sentiment_label':  'neutral',
                'banner_image':     item.get('image', ''),
            })
        return result
    except Exception as e:
        if '429' not in str(e):  # only log non-rate-limit errors
            print(f'[TradeSimulator] Finnhub general news failed: {e}')
        return []

@app.route('/api/news/<symbol>')
def get_news_symbol(symbol):
    symbol = symbol.upper()
    cache_key = f'sym:{symbol}'
    now = _time.time()
    if cache_key in _news_cache:
        items, ts = _news_cache[cache_key]
        if now - ts < _NEWS_TTL:
            return jsonify(items)
    items = _fetch_news_av(symbol) or _fetch_news_polygon(symbol) or _fetch_news_yfinance(symbol)
    _news_cache[cache_key] = (items, now)
    return jsonify(items)

_TOPIC_AV = {
    'finance':    'financial_markets,economy_fiscal',
    'technology': 'technology',
    'earnings':   'earnings',
    'macro':      'economy_macro,economy_monetary,economy_fiscal',
    'crypto':     'blockchain',
}
_TOPIC_FINNHUB = {
    'finance': 'general',
    'macro':   'general',
    'crypto':  'crypto',
}
_TOPIC_YF = {
    'finance':    ['JPM','GS','BAC','V','MA','BRK-B','SPY','QQQ'],
    'technology': ['AAPL','MSFT','GOOGL','META','NVDA','AMD','INTC','TSLA'],
    'earnings':   ['AAPL','MSFT','AMZN','GOOGL','META','NVDA','TSLA','JPM'],
    'macro':      ['SPY','QQQ','TLT','GLD','IWM','DIA','VIX'],
    'crypto':     ['BTC-USD','ETH-USD','COIN','HOOD','MARA','RIOT'],
}

def _fetch_news_finnhub_category(category: str) -> list:
    if not FINNHUB_KEYS_SET:
        return []
    try:
        import requests as _req
        r = _req.get(
            'https://finnhub.io/api/v1/news',
            params={'category': category, 'token': FINNHUB_KEY},
            timeout=5,
        )
        r.raise_for_status()
        items = r.json() or []
        result = []
        for item in items[:40]:
            headline = (item.get('headline') or '').strip()
            if not headline:
                continue
            result.append({
                'title':        headline,
                'source':       item.get('source', 'Finnhub'),
                'url':          item.get('url', ''),
                'published_at': item.get('datetime', 0),
                'summary':      item.get('summary', ''),
                'sentiment_label': 'neutral',
                'banner_image': item.get('image', ''),
            })
        return result
    except Exception as e:
        print(f'[TradeSimulator] Finnhub {category} news failed: {e}')
        return []

def _fetch_general_news_yfinance_topic(tickers: list) -> list:
    try:
        import yfinance as yf
        seen, result = set(), []
        for sym in tickers:
            if len(result) >= 40:
                break
            try:
                raw = yf.Ticker(sym).news or []
                for art in _yf_news_to_articles(raw[:6]):
                    if art['title'] not in seen:
                        seen.add(art['title'])
                        result.append(art)
            except Exception:
                continue
        return result
    except Exception as e:
        print(f'[TradeSimulator] yfinance topic news failed: {e}')
        return []

@app.route('/api/news/general')
def get_news_general():
    topic = request.args.get('topic', 'finance')
    cache_key = f'general:{topic}'
    now = _time.time()
    if cache_key in _news_cache:
        items, ts = _news_cache[cache_key]
        if now - ts < _NEWS_TTL:
            return jsonify(items)

    av_topics  = _TOPIC_AV.get(topic, 'financial_markets')
    fh_cat     = _TOPIC_FINNHUB.get(topic)
    yf_tickers = _TOPIC_YF.get(topic, ['SPY', 'QQQ', 'AAPL', 'MSFT'])

    items = (
        (_fetch_news_finnhub_category(fh_cat) if fh_cat else [])
        or _fetch_news_av(topics=av_topics)
        or _fetch_news_polygon()
        or _fetch_general_news_yfinance_topic(yf_tickers)
    )
    _news_cache[cache_key] = (items, now)
    return jsonify(items)

# ── AI portfolio trading ───────────────────────────────────────────────────────

_AI_UNIVERSE = [
    # ── Equities ──────────────────────────────────────────────────────────────
    'AAPL','MSFT','NVDA','GOOGL','META','AMZN','TSLA','AVGO','ADBE','CRM',
    'AMD','INTC','QCOM','TXN','ORCL','IBM','INTU','NOW','SNOW','PLTR',
    'JPM','BAC','GS','MS','V','MA','AXP','BLK','C','WFC',
    'UNH','LLY','JNJ','PFE','MRK','ABBV','TMO','DHR','AMGN','GILD',
    'WMT','COST','HD','TGT','NKE','MCD','SBUX','CMG',
    'XOM','CVX','COP','SLB','OXY','EOG',
    'CAT','DE','HON','BA','GE','UPS','FDX','RTX','LMT',
    'NFLX','DIS','CMCSA','T','VZ',
    'SPY','QQQ','IWM','GLD','TLT',

    # ── Futures ───────────────────────────────────────────────────────────────
    'ES=F','NQ=F','YM=F','RTY=F',
    'CL=F','GC=F','SI=F','NG=F',
    'ZB=F','ZN=F','BTC=F','ETH=F',

    # ── Forex ─────────────────────────────────────────────────────────────────
    'EURUSD=X','GBPUSD=X','USDJPY=X','USDCHF=X',
    'AUDUSD=X','USDCAD=X','NZDUSD=X',
    'EURGBP=X','EURJPY=X','GBPJPY=X',

    # ── Crypto (spot) — only tickers with reliable yfinance history ───────────
    'BTC-USD','ETH-USD','SOL-USD','BNB-USD','XRP-USD',
    # Major crypto only — sufficient liquidity and institutional participation
    # Removed: HBAR, ALGO, INJ, DOT, NEAR, OP (low-cap, bounce-and-fail pattern)
    'ADA-USD','AVAX-USD','DOGE-USD','LINK-USD',
    'ATOM-USD','AAVE-USD',
    # Replacements with real liquidity and market depth:
    # 'UNI-USD' — delisted from yfinance, removed
    'LTC-USD',    # Litecoin — OG crypto, highly liquid
    'BCH-USD',    # Bitcoin Cash — high volume, liquid
    'XLM-USD',    # Stellar — institutional partnerships, liquid
    'TRX-USD',    # Tron — high transaction volume, liquid
    'FIL-USD',    # Filecoin — real utility, institutional interest
]
_AI_UNIVERSE = list(dict.fromkeys(_AI_UNIVERSE))  # deduplicate, preserve order

# Per-portfolio rotating scan cursor: {portfolio_id: int}
_ai_scan_cursor: dict = {}

# In-memory signal cache for "what changed?" detection: symbol -> last signal dict
_prev_signals: dict = {}


def _ema(vals, period):
    k = 2.0 / (period + 1)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _compute_indicators_fast(symbol: str) -> dict:
    """Fetch indicators for a symbol. Priority: CandleEngine → cache → yfinance.

    Never returns a price_only dict if real historical data is obtainable.
    Handles all symbol types: equity, crypto (-USD), forex (=X), futures (=F).
    """
    # ── 1. CandleEngine live data (only if mature — enough bars for real indicators) ──
    # A just-connected stream (e.g. Coinbase) has few closed 1m bars, so RSI/MACD
    # return their neutral defaults (RSI=50). Require 30+ closed bars before trusting
    # live data; otherwise fall through to yfinance daily history.
    if _candle_engine and _candle_engine.is_warmed_up(symbol, '1m', min_bars=26):
        ce_data = _candle_engine.latest(symbol, '1m')
        if ce_data:
            return ce_data
    elif _candle_engine:
        bars = _candle_engine.bars_available(symbol, '1m')
        if bars > 0:
            logging.debug('[INDICATORS] %s: only %d/26 bars warmed — using yfinance', symbol, bars)

    # ── 2. Warm cache (full indicator dict, not a bulk prefetch stub) ──────────
    now = _time.time()
    if symbol in _proj_cache:
        payload, ts = _proj_cache[symbol]
        if now - ts < _PROJ_TTL and isinstance(payload, dict) and 'rsi' in payload:
            return payload

    # ── 3. yfinance historical data ────────────────────────────────────────────
    import yfinance as yf
    hist = None

    # Check for pre-fetched bulk DataFrame (from scan batch prefetch)
    if symbol in _proj_cache:
        payload, ts = _proj_cache[symbol]
        if now - ts < _PROJ_TTL and isinstance(payload, dict) and '_yf_bulk' in payload:
            hist = payload['_yf_bulk']
            del _proj_cache[symbol]  # consume the stub

    if hist is None:
        try:
            hist = yf.Ticker(symbol).history(period='60d')
        except Exception:
            pass

    # ── 4. Validate and flatten DataFrame ──────────────────────────────────────
    if hist is not None and not hist.empty:
        # Flatten MultiIndex columns if present (newer yfinance for bulk downloads)
        if hasattr(hist.columns, 'levels') and len(hist.columns.levels) > 1:
            hist.columns = hist.columns.get_level_values(0)
        # Drop rows with NaN close
        hist = hist.dropna(subset=['Close'])

    if hist is None or hist.empty or len(hist) < 20:
        # Last resort: fetch current price only
        try:
            price = _get_current_price(symbol)
            if price and price > 0:
                # Try to get a meaningful price series from yfinance with shorter period
                try:
                    h2 = yf.Ticker(symbol).history(period='30d')
                    if h2 is not None and not h2.empty and len(h2) >= 5:
                        if hasattr(h2.columns, 'levels'):
                            h2.columns = h2.columns.get_level_values(0)
                        h2 = h2.dropna(subset=['Close'])
                        if len(h2) >= 5:
                            hist = h2
                except Exception:
                    pass
        except Exception:
            pass

    if hist is None or hist.empty or len(hist) < 5:
        raise ValueError(f'Insufficient data for {symbol}')

    # ── 5. Extract OHLCV arrays ────────────────────────────────────────────────
    def _to_float_list(series):
        """Convert a pandas Series to a list of floats, handling any type."""
        try:
            return [float(x) for x in series if x is not None and str(x) != 'nan']
        except Exception:
            return []

    closes  = _to_float_list(hist['Close'])
    highs   = _to_float_list(hist['High'])
    lows    = _to_float_list(hist['Low'])
    volumes = _to_float_list(hist.get('Volume', hist['Close'] * 0))

    n = min(len(closes), len(highs), len(lows), len(volumes))
    if n < 5:
        raise ValueError(f'Insufficient valid rows for {symbol}: {n}')

    closes  = closes[-n:]; highs = highs[-n:]; lows = lows[-n:]; volumes = volumes[-n:]
    last_c  = closes[-1]

    # ── 6. RSI (14) ────────────────────────────────────────────────────────────
    gains  = [max(closes[i] - closes[i-1], 0) for i in range(1, n)]
    losses = [max(closes[i-1] - closes[i], 0) for i in range(1, n)]
    if len(gains) >= 14:
        avg_g = sum(gains[-14:]) / 14
        avg_l = sum(losses[-14:]) / 14
        rsi   = round(100 - (100 / (1 + avg_g / avg_l)) if avg_l else 100.0, 2)
    else:
        rsi   = 50.0

    # ── 7. MACD (12, 26, 9) ────────────────────────────────────────────────────
    def _ema_calc(vals, period):
        if not vals: return []
        k = 2 / (period + 1); out = [vals[0]]
        for v in vals[1:]: out.append(v * k + out[-1] * (1 - k))
        return out

    macd_cross = 'neutral'; macd_val = 0.0; macd_sig_val = 0.0
    if n >= 27:
        ema12 = _ema_calc(closes, 12); ema26 = _ema_calc(closes, 26)
        macd_vals = [ema12[i] - ema26[i] for i in range(25, n)]
        sig_vals  = _ema_calc(macd_vals, 9)
        if macd_vals and sig_vals:
            lm = macd_vals[-1]; ls = sig_vals[-1]
            pm = macd_vals[-2] if len(macd_vals) > 1 else lm
            ps = sig_vals[-2]  if len(sig_vals)  > 1 else ls
            ch = lm - ls; ph = pm - ps
            if   ch > 0 and ph <= 0: macd_cross = 'bullish_cross'
            elif ch < 0 and ph >= 0: macd_cross = 'bearish_cross'
            elif ch > 0:             macd_cross = 'bullish'
            else:                    macd_cross = 'bearish'
            macd_val = round(lm, 6); macd_sig_val = round(ls, 6)

    # ── 8. Stochastic (14) ────────────────────────────────────────────────────
    stoch_k = 50.0
    if n >= 14:
        arr = []
        for i in range(13, n):
            ph = max(highs[i-13:i+1]); pl = min(lows[i-13:i+1])
            arr.append((closes[i]-pl)/(ph-pl)*100 if ph > pl else 50.0)
        stoch_k = arr[-1] if arr else 50.0

    # ── 9. Bollinger Bands (20, 2σ) ───────────────────────────────────────────
    bb_pos = 'unknown'
    if n >= 20:
        w = closes[-20:]; mean = sum(w) / 20
        std = (sum((c - mean) ** 2 for c in w) / 20) ** 0.5
        bbu = mean + 2*std; bbl = mean - 2*std; bw = bbu - bbl
        if   bw < last_c * 0.03:     bb_pos = 'squeeze'
        elif last_c >= bbu * 0.995:  bb_pos = 'overbought'
        elif last_c <= bbl * 1.005:  bb_pos = 'oversold'
        elif last_c > mean:          bb_pos = 'upper_half'
        else:                        bb_pos = 'lower_half'

    # ── 10. VWAP (20-bar rolling) ─────────────────────────────────────────────
    vwap_signal = ''
    if n >= 20:
        tp  = [(highs[i]+lows[i]+closes[i])/3 for i in range(n-20, n)]
        vol = volumes[n-20:n]
        tv  = sum(vol)
        if tv > 0:
            vwap_val = sum(p*v for p,v in zip(tp,vol)) / tv
            vwap_signal = 'above' if last_c > vwap_val else 'below'

    # ── 11. Volume signal ─────────────────────────────────────────────────────
    last_vol = volumes[-1] if volumes else 0
    avg_vol  = sum(volumes[-20:]) / min(20, len(volumes)) if volumes else 0
    vol_ratio = round(last_vol / avg_vol, 2) if avg_vol > 0 else 1.0
    price_chg = last_c - closes[-2] if n >= 2 else 0
    if   vol_ratio >= 1.5: vol_signal = 'high_up' if price_chg > 0 else 'high_down'
    elif vol_ratio <= 0.5: vol_signal = 'low'
    else:                  vol_signal = 'normal'

    # ── 12. Trend (20-bar linear regression) ─────────────────────────────────
    last20 = closes[-20:] if n >= 20 else closes
    sz = len(last20); xm = (sz-1)/2; ym = sum(last20)/sz
    num   = sum((i-xm)*(last20[i]-ym) for i in range(sz))
    denom = sum((i-xm)**2 for i in range(sz))
    slope = num/denom if denom else 0
    trend = 'up' if slope > 0.05 else 'down' if slope < -0.05 else 'sideways'

    # ── 13. ATR (14) ──────────────────────────────────────────────────────────
    tr_vals = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
               for i in range(1, n)]
    atr = round(sum(tr_vals[-14:])/14, 6) if len(tr_vals) >= 14 else last_c * 0.02

    # ── 14. EMA50 ─────────────────────────────────────────────────────────────
    ema50_arr = _ema_calc(closes, min(50, n))
    ema50 = ema50_arr[-1] if ema50_arr else last_c

    slope_pct = round((slope / last_c) * 100, 4) if last_c else 0.0

    # ── 15. ADX approximation ─────────────────────────────────────────────────
    adx_val = 0.0
    if n >= 15:
        plus_dm  = [max(highs[i]-highs[i-1],0) if (highs[i]-highs[i-1])>(lows[i-1]-lows[i]) else 0 for i in range(1,n)]
        minus_dm = [max(lows[i-1]-lows[i],0) if (lows[i-1]-lows[i])>(highs[i]-highs[i-1]) else 0 for i in range(1,n)]
        atr14 = sum(tr_vals[-14:])/14 if len(tr_vals)>=14 else 1
        pdm14 = sum(plus_dm[-14:])/14; mdm14 = sum(minus_dm[-14:])/14
        pdi = 100*pdm14/atr14 if atr14 else 0; mdi = 100*mdm14/atr14 if atr14 else 0
        dx  = abs(pdi-mdi)/(pdi+mdi)*100 if (pdi+mdi) else 0
        adx_val = round(dx, 1)

    result = {
        'last_price':        last_c,
        'rsi':               rsi,
        'macd_cross':        macd_cross,
        'macd_value':        macd_val,
        'macd_signal_value': macd_sig_val,
        'stoch_k_val':       round(stoch_k, 2),
        'stoch_d_val':       round(stoch_k, 2),
        'bb_position':       bb_pos,
        'vwap_signal':       vwap_signal,
        'volume_signal':     vol_signal,
        'volume_ratio':      vol_ratio,
        'trend':             trend,
        'slope':             round(slope, 6),
        'slope_pct':         slope_pct,
        'atr':               atr,
        'atr_pct':           round(atr / last_c * 100, 2) if last_c else 2.0,
        'ema50':             round(ema50, 4),
        'adx':               adx_val,
        'regime':            'neutral',
    }

    _proj_cache[symbol] = (result, now)
    return result


def _compute_mtf_bias(symbol: str) -> dict:
    """Classify market directional bias across 1h, 5m, 1m timeframes."""
    if not _candle_engine:
        return {'h1': 'neutral', 'm5': 'neutral', 'm1': 'neutral', 'alignment': 0.5, 'bias': 'neutral'}

    def _classify_tf(data):
        if not data:
            return 'neutral'
        rsi   = float(data.get('rsi', 50) or 50)
        trend = data.get('trend', 'sideways') or 'sideways'
        macd  = data.get('macd_cross', '') or ''
        bull  = sum([rsi < 50, trend == 'up', 'bullish' in macd])
        bear  = sum([rsi > 50, trend == 'down', 'bearish' in macd])
        if bull >= 2: return 'bullish'
        if bear >= 2: return 'bearish'
        return 'neutral'

    h1 = _classify_tf(_candle_engine.latest(symbol, '1h'))
    m5 = _classify_tf(_candle_engine.latest(symbol, '5m'))
    m1 = _classify_tf(_candle_engine.latest(symbol, '1m'))

    states = [h1, m5, m1]
    bull_n = states.count('bullish')
    bear_n = states.count('bearish')

    if bull_n >= 2:   bias = 'bullish';  alignment = bull_n / 3
    elif bear_n >= 2: bias = 'bearish';  alignment = bear_n / 3
    else:             bias = 'neutral';  alignment = 0.33

    return {'h1': h1, 'm5': m5, 'm1': m1, 'alignment': round(alignment, 2), 'bias': bias}


def _classify_market_state(data: dict) -> str:
    """Classify current market conditions into a named regime."""
    rsi     = float(data.get('rsi', 50) or 50)
    trend   = data.get('trend', 'sideways') or 'sideways'
    bb_pos  = data.get('bb_position', '') or ''
    vol_sig = data.get('volume_signal', '') or ''
    atr_pct = float(data.get('atr_pct', 2.0) or 2.0)
    adx     = float(data.get('adx', 0) or 0)
    macd_x  = data.get('macd_cross', '') or ''
    stoch   = float(data.get('stoch_k_val', 50) or 50)

    # Panic: extreme oversold + high volatility + heavy selling volume
    if rsi < 25 and atr_pct > 3.5 and vol_sig == 'high_down':
        return 'panic'

    # Extreme overbought
    if rsi > 80 and stoch > 85 and bb_pos == 'overbought':
        return 'overbought_extreme'

    # Extreme oversold (not panic — no volume spike)
    if rsi < 22 and stoch < 20:
        return 'oversold_extreme'

    # Breakout: price at BB upper + volume spike + bullish momentum
    if bb_pos == 'overbought' and vol_sig == 'high_up' and 'bullish' in macd_x:
        return 'breakout'

    # Trending markets (ADX > 20 is a reasonable directional threshold from our approx)
    if adx > 20 and trend == 'up':
        return 'trending_up'
    if adx > 20 and trend == 'down':
        return 'trending_down'

    # Accumulation: RSI 30-48, flat/rising trend, volume building
    if 28 <= rsi <= 48 and trend in ('sideways', 'up') and vol_sig in ('high_up', 'normal'):
        return 'accumulation'

    # Ranging / BB squeeze
    if bb_pos == 'squeeze' or (trend == 'sideways' and adx < 15):
        return 'ranging'

    # Euphoric: parabolic extension — mean-reversion risk
    if rsi > 85 and atr_pct > 2.0 and vol_sig in ('high_up', 'normal'):
        return 'euphoric'

    # Distribution: price stalling at highs with selling volume
    if 50 <= rsi <= 68 and vol_sig == 'high_down' and trend == 'sideways':
        return 'distribution'

    # News-driven: explosive volume spike in either direction
    if vol_sig in ('high_up', 'high_down') and float(data.get('volume_ratio', 1.0) or 1.0) >= 3.0:
        return 'news_driven'

    # Mild trends without ADX confirmation
    if trend == 'up':   return 'mild_uptrend'
    if trend == 'down': return 'mild_downtrend'
    return 'neutral'


def _regime_stop_multiplier(market_state: str) -> tuple[float, float]:
    """Return (stop_mult, target_mult) based on regime."""
    if market_state in ('panic', 'news_driven', 'euphoric'):
        return 2.0, 2.0   # volatile — still take profit quickly
    if market_state in ('breakout',):
        return 1.5, 2.0   # breakouts: let it run a bit but don't overstay
    if market_state in ('ranging', 'accumulation', 'oversold_extreme', 'overbought_extreme'):
        return 1.0, 1.2   # mean-reversion: tight target, take it fast
    if market_state in ('trending_up', 'trending_down'):
        return 1.5, 1.8   # trends: slightly wider target
    return 1.5, 1.5        # default: symmetric stop and target


def _predict_regime_transition(symbol: str, current_regime: str, data: dict) -> dict:
    """
    Detect early signs of regime change from current indicators.
    Returns {transition, confidence, description, score_adj}
    where score_adj is a score adjustment to apply (+/- up to 0.5).
    """
    try:
        adx     = float(data.get('adx', 0) or 0)
        rsi     = float(data.get('rsi', 50) or 50)
        vol_sig = data.get('volume_signal', '') or ''
        vol_r   = float(data.get('volume_ratio', 1) or 1)
        slope   = float(data.get('slope_pct', 0) or 0)
        macd_x  = data.get('macd_cross', '') or ''
        bb_pos  = data.get('bb_position', '') or ''

        # Use _prev_signals to detect divergence
        prev = _prev_signals.get(symbol, {})
        prev_adx  = float(prev.get('adx', adx))
        prev_rsi  = float(prev.get('rsi', rsi))

        adx_rising  = adx > prev_adx + 2
        adx_falling = adx < prev_adx - 2
        rsi_diverge = (rsi < prev_rsi - 5) and slope > 0  # price up, RSI down = divergence

        transition = 'none'
        confidence = 0.0
        desc       = ''
        score_adj  = 0.0

        if current_regime in ('ranging', 'accumulation') and adx_rising and vol_r > 1.3:
            transition = 'breakout_forming'
            confidence = min(1.0, adx / 25 * vol_r / 1.5)
            desc = f'ADX rising ({adx:.0f}) with volume — breakout likely'
            score_adj = +0.4 * confidence  # boost breakout setups

        elif current_regime in ('trending_up',) and adx_falling and vol_r < 0.8:
            transition = 'distribution_forming'
            confidence = min(1.0, (prev_adx - adx) / 10)
            desc = f'ADX declining ({adx:.0f}) on low volume — trend weakening'
            score_adj = -0.3 * confidence  # dampen long signals

        elif rsi_diverge and current_regime in ('trending_up', 'breakout'):
            transition = 'momentum_fade'
            confidence = min(1.0, (prev_rsi - rsi) / 10)
            desc = f'RSI divergence ({rsi:.0f}) while price rising — exhaustion signal'
            score_adj = -0.4 * confidence

        elif current_regime == 'panic' and rsi < 25 and vol_r > 2:
            transition = 'capitulation_reversal'
            confidence = min(1.0, (25 - rsi) / 15 * vol_r / 3)
            desc = f'Panic at RSI {rsi:.0f} with {vol_r:.1f}× volume — reversal possible'
            score_adj = +0.5 * confidence

        return {
            'transition':  transition,
            'confidence':  round(confidence, 2),
            'description': desc,
            'score_adj':   round(score_adj, 2),
        }
    except Exception:
        return {'transition': 'none', 'confidence': 0, 'description': '', 'score_adj': 0}


def _protection_stage(avg_cost: float, current_price: float,
                      stop_price: float | None, atr: float) -> dict:
    """
    Compute current profit-protection stage and recommended new stop level.

    Stages:
      0 at_risk:    < 0.5% gain — normal ATR stop, can lose money
      1 breakeven:  >= 0.5% gain — stop moved to entry, can't lose
      2 min_locked: >= 1.5% gain — stop at entry+0.5%, locking small gain
      3 half_locked: >= 3% gain  — stop at entry + 50% of current gain
      4 trailing:   >= 5% gain   — ATR trail above half-locked level

    Stop NEVER moves down — only ratchets upward.
    """
    if avg_cost <= 0 or current_price <= 0:
        return {'stage': 0, 'label': 'at_risk', 'new_stop': None,
                'gain_pct': 0, 'description': 'No data'}

    gain_pct  = (current_price - avg_cost) / avg_cost
    atr_stop  = current_price - 1.5 * atr   # normal ATR trail level

    if gain_pct >= 0.05:
        # Stage 4: full ATR trailing, but never below half-locked level
        half_locked = avg_cost + (current_price - avg_cost) * 0.5
        new_stop = max(half_locked, atr_stop)
        label    = 'trailing'
        desc     = f'Trailing stop — locked in {gain_pct/2*100:.1f}% minimum gain'
        next_lvl = None
    elif gain_pct >= 0.03:
        # Stage 3: lock 50% of current gain
        new_stop = avg_cost + (current_price - avg_cost) * 0.5
        label    = 'half_locked'
        desc     = f'Half gain locked — stop at +{(new_stop/avg_cost-1)*100:.1f}% from entry'
        next_lvl = f'+5% to full ATR trail'
    elif gain_pct >= 0.015:
        # Stage 2: lock minimum +0.5% gain
        new_stop = avg_cost * 1.005
        label    = 'min_locked'
        desc     = f'Minimum gain locked (+0.5%) — stop above entry'
        next_lvl = f'+3% to lock half the gain'
    elif gain_pct >= 0.005:
        # Stage 1: breakeven — stop at entry
        new_stop = avg_cost
        label    = 'breakeven'
        desc     = 'Breakeven protected — cannot lose money on this trade'
        next_lvl = f'+1.5% to lock minimum gain'
    else:
        # Stage 0: at risk — normal ATR stop below entry
        new_stop = avg_cost - 1.5 * atr
        label    = 'at_risk'
        desc     = f'At risk — stop ${new_stop:.2f} ({gain_pct*100:+.1f}% from entry)'
        next_lvl = f'+0.5% to move stop to breakeven'

    # Never let stop go below entry once we've reached breakeven
    if stop_price and stop_price >= avg_cost and new_stop < avg_cost:
        new_stop = avg_cost

    # Stops only ratchet upward — never move down
    if stop_price:
        new_stop = max(new_stop, stop_price)

    stage_num = {'at_risk': 0, 'breakeven': 1, 'min_locked': 2,
                 'half_locked': 3, 'trailing': 4}[label]

    return {
        'stage':     stage_num,
        'label':     label,
        'new_stop':  round(new_stop, 4) if new_stop else None,
        'gain_pct':  round(gain_pct * 100, 2),
        'description': desc,
        'next_level': next_lvl if 'next_lvl' in dir() else None,
    }


# Map 13 display regimes → 4 macro buckets for weight selection
# Keeps display labels (shown in UI/logs) but learns on broader categories
REGIME_MACRO_BUCKET = {
    'trending_up':       'bull',
    'mild_uptrend':      'bull',
    'breakout':          'bull',
    'accumulation':      'bull',
    'trending_down':     'bear',
    'mild_downtrend':    'bear',
    'distribution':      'bear',
    'euphoric':          'bear',
    'ranging':           'range',
    'neutral':           'range',
    'panic':             'crisis',
    'oversold_extreme':  'crisis',
    'overbought_extreme':'crisis',
    'news_driven':       'crisis',
}


def _adaptive_weights(market_state: str) -> dict:
    """Return per-indicator weight multipliers. Uses 4 macro buckets for learning,
    keeps specific overrides for extreme regimes."""
    base = {'rsi': 1.0, 'macd': 1.0, 'stoch': 1.0, 'bb': 1.0, 'volume': 1.0,
            'vwap': 1.0, 'trend': 1.0}
    bucket = REGIME_MACRO_BUCKET.get(market_state, 'range')

    if bucket == 'bull':
        weights = {**base, 'macd': 1.3, 'trend': 1.3, 'rsi': 0.8, 'bb': 0.8}
    elif bucket == 'bear':
        weights = {**base, 'macd': 1.4, 'trend': 1.4, 'rsi': 0.7, 'bb': 0.7}
    elif bucket == 'range':
        weights = {**base, 'rsi': 1.4, 'bb': 1.4, 'stoch': 1.2, 'macd': 0.6}
    elif bucket == 'crisis':
        weights = {**base, 'volume': 1.5, 'rsi': 0.5, 'macd': 0.5, 'trend': 0.5}
    else:
        weights = base

    # Specific overrides for extreme regimes (highest priority)
    if market_state == 'breakout':
        return {**base, 'volume': 1.5, 'macd': 1.3, 'trend': 1.2, 'rsi': 0.8}
    if market_state == 'euphoric':
        return {**base, 'rsi': 1.5, 'stoch': 1.3, 'bb': 1.3, 'macd': 0.6, 'trend': 0.5}
    if market_state == 'distribution':
        return {**base, 'volume': 1.5, 'macd': 1.2, 'rsi': 0.8, 'trend': 0.7}
    if market_state == 'news_driven':
        return {**base, 'volume': 2.0, 'macd': 0.4, 'rsi': 0.3, 'stoch': 0.3, 'bb': 0.4}

    # Blend in ML-learned weights if available (Tier 5)
    try:
        import model_trainer as _mt_mod
        trainer = _mt_mod.get_trainer()
        if trainer:
            learned = trainer.get_weights(market_state)
            for k in weights:
                if k in learned:
                    weights[k] = round(weights[k] * 0.7 + learned[k] * 0.3, 3)
    except Exception:
        pass

    return weights


def _ai_score_detailed(data: dict) -> dict:
    """Full traceable analysis. Returns score, per-signal breakdown, uncertainty,
    market_state, plain-English summary, and what-changed list."""
    rsi      = float(data.get('rsi', 50) or 50)
    macd_x   = data.get('macd_cross', '') or ''
    stoch_k  = float(data.get('stoch_k_val', 50) or 50)
    vol_sig  = data.get('volume_signal', '') or ''
    vol_r    = float(data.get('volume_ratio', 1.0) or 1.0)
    bb_pos   = data.get('bb_position', '') or ''
    vwap_sig = data.get('vwap_signal', '') or ''
    trend    = data.get('trend', '') or ''
    slope    = float(data.get('slope', 0) or 0)
    price    = float(data.get('last_price', 0) or 0)
    ema50    = float(data.get('ema50', price) or price)
    atr_pct  = float(data.get('atr_pct', 2.0) or 2.0)
    symbol   = data.get('symbol', '')

    market_state = _classify_market_state(data)
    weights = _adaptive_weights(market_state)

    # Intraday boost: live 1m CandleEngine readings weight momentum/volume more
    if data.get('_source') == 'candle_engine':
        weights = {**weights, 'volume': weights['volume'] * 1.2,
                   'macd': weights['macd'] * 1.2}

    # Countertrend penalty based on regime confirmation
    _strong_downtrend = market_state in ('trending_down', 'distribution', 'euphoric')
    _strong_uptrend   = market_state in ('trending_up', 'breakout')
    if _strong_downtrend and slope < -0.05:
        trend_penalty = 0.15  # 15% weight on bullish signals — strong downtrend confirmed
    elif slope < -0.05:
        trend_penalty = 0.35  # moderate downtrend
    else:
        trend_penalty = 1.0

    breakdown = {}
    score = 0.0

    # ── RSI ──────────────────────────────────────────────────────────────────
    if   rsi <= 20: raw = 3.0; sig = 'extreme_oversold'
    elif rsi <= 28: raw = 2.0; sig = 'oversold'
    elif rsi <= 38: raw = 1.0; sig = 'mild_oversold'
    elif rsi >= 80: raw = -3.0; sig = 'extreme_overbought'
    elif rsi >= 72: raw = -2.0; sig = 'overbought'
    elif rsi >= 62: raw = -1.0; sig = 'mild_overbought'
    else:           raw = 0.0;  sig = 'neutral'
    contrib = raw * weights['rsi'] * (trend_penalty if raw > 0 else 1.0)
    breakdown['rsi'] = {'value': round(rsi, 1), 'signal': sig,
                        'contribution': round(contrib, 2), 'weight': weights['rsi'],
                        'trend_penalty_applied': trend_penalty < 1.0 and raw > 0}
    score += contrib

    # ── MACD ─────────────────────────────────────────────────────────────────
    if   macd_x == 'bullish_cross': raw = 2.0; sig = 'bullish_crossover'
    elif macd_x == 'bullish':       raw = 1.0; sig = 'bullish'
    elif macd_x == 'bearish_cross': raw = -2.0; sig = 'bearish_crossover'
    elif macd_x == 'bearish':       raw = -1.0; sig = 'bearish'
    else:                           raw = 0.0;  sig = 'neutral'
    contrib = raw * weights['macd']
    breakdown['macd'] = {'value': round(data.get('macd_value', 0) or 0, 4),
                         'signal': sig, 'contribution': round(contrib, 2),
                         'weight': weights['macd']}
    score += contrib

    # ── Stochastic ───────────────────────────────────────────────────────────
    if   stoch_k <= 15: raw = 1.5; sig = 'deep_oversold'
    elif stoch_k <= 25: raw = 1.0; sig = 'oversold'
    elif stoch_k >= 85: raw = -1.5; sig = 'deep_overbought'
    elif stoch_k >= 75: raw = -1.0; sig = 'overbought'
    else:               raw = 0.0;  sig = 'neutral'
    contrib = raw * weights['stoch'] * (trend_penalty if raw > 0 else 1.0)
    breakdown['stoch'] = {'value': round(stoch_k, 1), 'signal': sig,
                          'contribution': round(contrib, 2), 'weight': weights['stoch']}
    score += contrib

    # ── Volume ───────────────────────────────────────────────────────────────
    vol_mult = min(vol_r / 1.5, 1.5) if vol_r > 1.5 else 1.0
    if   vol_sig == 'high_up':   raw = 2.0 * vol_mult; sig = 'high_buying'
    elif vol_sig == 'high_down': raw = -2.0 * vol_mult; sig = 'high_selling'
    elif vol_sig == 'low':       raw = 0.0; sig = 'low_volume'; score *= 0.65
    else:                        raw = 0.0; sig = 'normal'
    if vol_sig not in ('low', ''):
        contrib = raw * weights['volume']
        breakdown['volume'] = {'value': round(vol_r, 2), 'signal': sig,
                               'contribution': round(contrib, 2), 'weight': weights['volume']}
        score += contrib
    else:
        breakdown['volume'] = {'value': round(vol_r, 2), 'signal': sig,
                               'contribution': 0.0, 'weight': weights['volume']}

    # ── Bollinger Bands ───────────────────────────────────────────────────────
    if   bb_pos == 'oversold':   raw = 1.5; sig = 'oversold'
    elif bb_pos == 'lower_half': raw = 0.5; sig = 'lower_half'
    elif bb_pos == 'overbought': raw = -1.5; sig = 'overbought'
    elif bb_pos == 'upper_half': raw = -0.5; sig = 'upper_half'
    elif bb_pos == 'squeeze':    raw = 0.0; sig = 'squeeze'
    else:                        raw = 0.0; sig = 'neutral'
    contrib = raw * weights['bb'] * (trend_penalty if raw > 0 else 1.0)
    breakdown['bb'] = {'value': bb_pos, 'signal': sig,
                       'contribution': round(contrib, 2), 'weight': weights['bb']}
    score += contrib

    # ── VWAP ─────────────────────────────────────────────────────────────────
    if   vwap_sig == 'above': raw = 1.0; sig = 'above_vwap'
    elif vwap_sig == 'below': raw = -1.0; sig = 'below_vwap'
    else:                     raw = 0.0; sig = 'neutral'
    contrib = raw * weights['vwap']
    breakdown['vwap'] = {'value': vwap_sig, 'signal': sig,
                         'contribution': round(contrib, 2), 'weight': weights['vwap']}
    score += contrib

    # ── Trend ────────────────────────────────────────────────────────────────
    if   trend == 'up':       raw = 1.5; sig = 'uptrend'
    elif trend == 'down':     raw = -1.5; sig = 'downtrend'
    else:                     raw = 0.0; sig = 'sideways'
    contrib = raw * weights['trend']
    breakdown['trend'] = {'value': trend, 'signal': sig,
                          'contribution': round(contrib, 2), 'weight': weights['trend']}
    score += contrib

    # ── EMA50 falling-knife gate ──────────────────────────────────────────────
    ema50_gate = False
    if ema50 > 0 and price < ema50 * 0.85:
        score = min(score, 1.0)
        ema50_gate = True
    breakdown['ema50_gate'] = {'price_vs_ema50': round((price / ema50 - 1) * 100, 1) if ema50 else 0,
                               'gate_triggered': ema50_gate}

    score = round(score, 2)

    # ── Multi-timeframe alignment ─────────────────────────────────────────────
    mtf = _compute_mtf_bias(symbol) if symbol else {'h1': 'neutral', 'm5': 'neutral', 'm1': 'neutral', 'alignment': 0.5, 'bias': 'neutral'}
    score_dir = 1 if score > 0 else (-1 if score < 0 else 0)
    bias_dir  = 1 if mtf['bias'] == 'bullish' else (-1 if mtf['bias'] == 'bearish' else 0)
    if score_dir != 0 and bias_dir != 0:
        if score_dir == bias_dir:
            score = score * (0.8 + mtf['alignment'] * 0.2)   # up to 1.0x — confirming
        else:
            score = score * (1.0 - mtf['alignment'] * 0.4)   # as low as 0.6x — opposing
    score = round(score, 2)
    breakdown['mtf'] = {'h1': mtf['h1'], 'm5': mtf['m5'], 'm1': mtf['m1'],
                        'bias': mtf['bias'], 'alignment': mtf['alignment']}

    # ── Market breadth signal ─────────────────────────────────────────────────
    try:
        import breadth_engine as _be
        breadth_contrib = _be.score_contrib()
        if breadth_contrib != 0:
            score += breadth_contrib * 0.5   # breadth is market-wide, weight 50%
            breakdown['breadth'] = {'contrib': round(breadth_contrib * 0.5, 2),
                                    'signal': _be.latest().get('signal', 'neutral')}
    except Exception:
        pass

    # ── Macro market filter ───────────────────────────────────────────────────
    # If SPY is trending down, dampen all bullish signals across all symbols
    try:
        _spy_data = _proj_cache.get('SPY', (None, 0))
        if _spy_data[0] and isinstance(_spy_data[0], dict):
            _spy_trend = _spy_data[0].get('trend', 'sideways')
            _spy_rsi   = float(_spy_data[0].get('rsi', 50) or 50)
            if _spy_trend == 'down' and _spy_rsi < 45 and score > 0:
                # SPY is in downtrend — dampen all bullish individual signals by 40%
                score = score * 0.60
                breakdown['macro_filter'] = {'signal': 'spy_downtrend', 'contrib': round(score * -0.40, 2)}
    except Exception:
        pass

    # ── News sentiment signal ─────────────────────────────────────────────────
    if symbol:
        try:
            import news_engine as _news
            ns = _news.get_engine().get_signal(symbol)
            news_sig = ns.get('signal', 0.0)
            if news_sig != 0:
                score += news_sig
                breakdown['news'] = {'signal': round(news_sig, 2),
                                     'sentiment': ns.get('sentiment_score', 0.5),
                                     'earnings_risk': ns.get('earnings_risk', 'none'),
                                     'economic_event': ns.get('economic_event')}
        except Exception:
            pass

    # ── Order flow signal ─────────────────────────────────────────────────────
    if symbol:
        try:
            import order_flow as _of
            of_sig = _of.get_signal(symbol)
            of_contrib = of_sig.get('score_contrib', 0.0)
            if of_contrib != 0:
                score += of_contrib
                breakdown['order_flow'] = {'bias': of_sig.get('bias', 'neutral'),
                                           'contrib': round(of_contrib, 3),
                                           'bid_ask_ratio': of_sig.get('bid_ask_ratio', 0.5)}
        except Exception:
            pass

    # ── Macro environment signal ──────────────────────────────────────────────
    try:
        import macro_engine as _me
        asset_class = _get_asset_class(symbol) if symbol else 'equity'
        mac = _me.get_signal(asset_class)
        mac_contrib = mac.get('score_contrib', 0.0)
        if mac_contrib != 0:
            score += mac_contrib * 0.5  # macro is background context, weight 50%
            breakdown['macro'] = {'regime': mac.get('regime', 'neutral'),
                                  'contrib': round(mac_contrib * 0.5, 3)}
    except Exception:
        pass

    # ── Regime transition prediction ──────────────────────────────────────────
    if symbol:
        try:
            trans = _predict_regime_transition(symbol, market_state, data)
            if trans['score_adj'] != 0:
                score += trans['score_adj']
                breakdown['transition'] = {
                    'signal': trans['transition'],
                    'contrib': trans['score_adj'],
                    'description': trans['description'],
                }
        except Exception:
            pass

    # ── Extended signal engines (Tier A–C) — each adds a small weighted nudge ──
    # All wrapped individually so any one failing never breaks scoring.
    _ext_price = price or 0
    for _eng_name, _fn in (
        ('volume_profile', lambda: __import__('volume_profile').score_contrib(symbol)),
        ('sector_rotation', lambda: __import__('sector_rotation').score_contrib(symbol)),
        ('correlation',     lambda: __import__('correlation_engine').score_contrib(symbol)),
        ('intermarket',     lambda: __import__('intermarket').score_contrib(symbol)),
        ('cot',             lambda: __import__('cot_engine').score_contrib(symbol)),
        ('htf_sr',          lambda: __import__('structure_engine').htf_score_contrib(symbol, _ext_price)),
        ('daily_pattern',   lambda: __import__('pattern_engine').daily_pattern_contrib(symbol)),
        ('breadth_div',     lambda: __import__('breadth_engine').divergence_contrib()),
        ('event',           lambda: __import__('news_engine').event_contrib(symbol)),
        ('earnings_drift',  lambda: __import__('news_engine').drift_contrib(symbol)),
        ('seasonality',     lambda: __import__('seasonality').score_contrib(symbol)),
        ('short_interest',  lambda: __import__('short_interest').score_contrib(symbol, data)),
        ('options_pcr',     lambda: __import__('options_engine').pcr_contrib(symbol, _ext_price)),
    ):
        try:
            _c = float(_fn() or 0.0)
            if _c != 0:
                score += _c
                breakdown[_eng_name] = {'contrib': round(_c, 2)}
        except Exception:
            pass

    score = round(score, 2)

    # ── Uncertainty score ─────────────────────────────────────────────────────
    def _sig_contrib(v):
        return v.get('contribution', v.get('contrib', 0))
    bull_count = sum(1 for k, v in breakdown.items()
                     if isinstance(v, dict) and _sig_contrib(v) > 0)
    bear_count = sum(1 for k, v in breakdown.items()
                     if isinstance(v, dict) and _sig_contrib(v) < 0)
    conflicts = min(bull_count, bear_count)
    uncertainty = 0.25
    uncertainty += conflicts * 0.08          # conflicting signals add uncertainty
    if vol_sig == 'low':     uncertainty += 0.10
    if bb_pos == 'squeeze':  uncertainty += 0.08
    if atr_pct > 4.0:        uncertainty += 0.10
    if market_state in ('ranging', 'neutral'): uncertainty += 0.12
    if market_state == 'panic': uncertainty += 0.20
    if abs(score) >= 5.0:    uncertainty -= 0.10  # strong alignment = more certain
    if ema50_gate:           uncertainty += 0.15
    uncertainty = round(max(0.05, min(0.95, uncertainty)), 2)

    # ── Plain-English summary ─────────────────────────────────────────────────
    parts = []
    rsi_sig = breakdown['rsi']['signal']
    if rsi_sig in ('extreme_oversold', 'oversold'):
        parts.append(f"RSI at {rsi:.0f} is {'extremely ' if rsi_sig == 'extreme_oversold' else ''}oversold")
    elif rsi_sig in ('extreme_overbought', 'overbought'):
        parts.append(f"RSI at {rsi:.0f} is {'extremely ' if rsi_sig == 'extreme_overbought' else ''}overbought")

    macd_sig = breakdown['macd']['signal']
    if macd_sig == 'bullish_crossover':  parts.append("MACD just crossed bullish — momentum shift")
    elif macd_sig == 'bearish_crossover': parts.append("MACD just crossed bearish — selling pressure building")
    elif macd_sig == 'bullish':          parts.append("MACD bullish but no fresh crossover")
    elif macd_sig == 'bearish':          parts.append("MACD bearish")

    trend_sig = breakdown['trend']['signal']
    if trend_sig == 'downtrend' and trend_penalty < 1.0:
        parts.append("downtrend reduces confidence in buy signals")
    elif trend_sig == 'uptrend':
        parts.append("price in uptrend supporting bullish case")

    vol_sig2 = breakdown['volume']['signal']
    if vol_sig2 == 'high_buying':   parts.append(f"volume {vol_r:.1f}× average on an up day — institutional buying")
    elif vol_sig2 == 'high_selling': parts.append(f"volume {vol_r:.1f}× average on a down day — distribution")
    elif vol_sig2 == 'low_volume':  parts.append("thin volume reduces signal reliability")

    state_msgs = {
        'panic': "Panic-level selling detected — extreme caution, signals unreliable.",
        'breakout': "Breakout pattern: price clearing resistance on high volume.",
        'accumulation': "Accumulation pattern: smart money likely building positions.",
        'overbought_extreme': "Extreme overbought — pullback risk elevated.",
        'oversold_extreme': "Extreme oversold — snap-back likely but timing uncertain.",
        'ranging': "Market ranging — momentum strategies less effective.",
        'trending_up': "Strong uptrend — trend-following indicators weighted higher.",
        'trending_down': "Strong downtrend — exercise extra caution on buy signals.",
    }
    if market_state in state_msgs:
        parts.append(state_msgs[market_state])

    if ema50_gate:
        parts.append(f"price {abs(breakdown['ema50_gate']['price_vs_ema50']):.1f}% below 50-day EMA — buy signal capped")

    if score >= 5.0:      qualifier = "Strong BUY signal."
    elif score >= 2.5:    qualifier = "Moderate BUY opportunity."
    elif score <= -5.0:   qualifier = "Strong SELL signal."
    elif score <= -2.5:   qualifier = "Moderate SELL pressure."
    else:                 qualifier = "Mixed signals — no clear edge."

    summary = qualifier + (" " + ". ".join(parts) + "." if parts else "")

    # ── What changed? ─────────────────────────────────────────────────────────
    changes = []
    prev = _prev_signals.get(symbol, {})
    watch_keys = [('macd_cross', 'MACD'), ('trend', 'Trend'),
                  ('bb_position', 'BB position'), ('volume_signal', 'Volume'),
                  ('market_state', 'Market state')]
    check_data = {**data, 'market_state': market_state}
    for key, label in watch_keys:
        old_v = prev.get(key)
        new_v = check_data.get(key)
        if old_v and new_v and old_v != new_v:
            changes.append(f"{label}: {old_v} → {new_v}")
    if symbol:
        _prev_signals[symbol] = {k: check_data.get(k) for k, _ in watch_keys}
        _prev_signals[symbol]['score'] = score

    return {
        'score':        score,
        'market_state': market_state,
        'breakdown':    breakdown,
        'uncertainty':  uncertainty,
        'summary':      summary,
        'what_changed': changes,
        'weights_used': weights,
        'mtf_bias':     mtf,
    }


def _ai_score(data: dict) -> float:
    """Return just the numeric score (backward-compatible wrapper)."""
    return _ai_score_detailed(data)['score']


def _ai_log_entry(pid: int, symbol: str, action: str, score: float,
                  price: float, shares: float, reason: str, market_state: str = ''):
    with _get_db() as conn:
        conn.execute(
            'INSERT INTO ai_log (portfolio_id, symbol, action, score, price, shares, reason, market_state) VALUES (?,?,?,?,?,?,?,?)',
            (pid, symbol, action, score, price, shares, reason, market_state or '')
        )


def _log_decision(pid: int, symbol: str, decision: str, score: float = 0,
                  regime: str = '', reason: str = '', detail: str = '',
                  quality_score: float = None, size_mult: float = None,
                  signal_json: str = None):
    """Log every AI decision — both ACCEPT and REJECT — to ai_decisions table."""
    try:
        with _get_db() as conn:
            conn.execute(
                '''INSERT INTO ai_decisions
                   (portfolio_id, symbol, decision, score, regime, reason, detail,
                    quality_score, size_mult, signal_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (pid, symbol or '', decision, score or 0, regime or '', reason or '',
                 (detail or '')[:200], quality_score, size_mult, signal_json)
            )
    except Exception:
        pass


def _score_to_pct(score: float) -> float:
    """Scale position size to signal conviction. High-score trades get more capital."""
    if score >= 7.0: return 0.12
    if score >= 5.0: return 0.10
    if score >= 3.5: return 0.07
    return 0.05


def _compute_confidence(score: float, data: dict, detail: dict) -> int:
    """Compute 0–100 confidence score combining score strength, MTF alignment,
    volume confirmation, uncertainty, and regime clarity."""
    uncertainty = float(detail.get('uncertainty', 0.3) or 0.3)
    mtf         = detail.get('mtf_bias', {}) or {}
    vol_r       = float(data.get('volume_ratio', 1) or 1)
    regime      = detail.get('market_state', 'neutral') or 'neutral'

    # Base: score magnitude → 0–60 pts
    base = min(60, int(abs(score) / 10 * 60))

    # MTF alignment bonus: 0–20 pts
    alignment = float(mtf.get('alignment', 0.33) or 0.33)
    bias       = mtf.get('bias', 'neutral') or 'neutral'
    score_dir  = 1 if score > 0 else -1 if score < 0 else 0
    bias_dir   = 1 if bias == 'bullish' else -1 if bias == 'bearish' else 0
    if score_dir != 0 and bias_dir == score_dir:
        mtf_bonus = int(alignment * 20)   # up to +20
    elif bias_dir != 0 and bias_dir != score_dir:
        mtf_bonus = -int(alignment * 15)  # opposing MTF: up to -15
    else:
        mtf_bonus = 0

    # Volume confirmation bonus: 0–10 pts
    vol_sig = data.get('volume_signal', '') or ''
    if vol_sig in ('high_up', 'high_down') and vol_r >= 1.5:
        vol_bonus = min(10, int((vol_r - 1) * 6))
    elif vol_sig == 'low':
        vol_bonus = -10
    else:
        vol_bonus = 0

    # Uncertainty penalty: 0–25 pts subtracted
    uncertainty_penalty = int(uncertainty * 25)

    # Regime clarity bonus: clear regime → +5, neutral/ranging → -5
    regime_bonus = 5 if regime in ('trending_up', 'trending_down', 'breakout', 'panic') else \
                  -5 if regime in ('neutral', 'ranging') else 0

    confidence = base + mtf_bonus + vol_bonus - uncertainty_penalty + regime_bonus
    return max(5, min(95, confidence))


def _compute_trade_quality(c: dict, history_ctx: dict, portfolio_reg: dict,
                            liq: dict, data: dict) -> dict:
    """
    Composite trade quality score 0–100. Threshold ≥62 to open position.

    Components:
      Signal conviction (20): abs(score)/10 * 20, capped at 20
      Confidence (15): existing confidence/100 * 15
      EV historical (15): 15 if EV>0 known, 8 if unknown, 0 if EV<0
      Regime suitability (10): strong=10, normal=5, cautious=0, avoid=-5
      MTF alignment (10): all agree=10, 2/3=6, 1/3=2, opposing=0
      Liquidity (10): liq.score/10 * 10
      Pattern confirmation (10): detected candlestick/momentum = 10, none = 5
      Portfolio regime (10): favorable=10, normal=8, defensive=5, preservation=0
    """
    try:
        score = abs(c.get('score', 0))
        conf  = c.get('confidence', 50) or 50
        detail = c.get('detail', {}) or {}
        mtf   = (detail.get('mtf_bias') or detail.get('breakdown', {}).get('mtf') or {})

        # 1. Signal conviction (0-20)
        pts_signal = min(20, score / 10 * 20)

        # 2. Confidence score (0-15) — floor at 5 so volatile assets aren't unfairly penalized
        # Crypto gets confidence 15-30 due to ATR penalties, which unfairly caps quality scores
        pts_conf = max(5.0, conf / 100 * 15)

        # 3. EV historical (0-15) — default 8 (unknown) if no history yet
        pts_ev = 8.0  # neutral: no history yet

        # 4. Regime suitability (0-10)
        regime = detail.get('market_state', 'neutral') or 'neutral'
        if regime in history_ctx.get('strong_regimes', set()):
            pts_regime = 10
        elif regime in history_ctx.get('cautious_regimes', set()):
            pts_regime = 0
        elif regime in ('panic', 'news_driven', 'euphoric'):
            pts_regime = 2
        else:
            pts_regime = 5

        # 5. MTF alignment (0-10)
        mtf_bias   = mtf.get('bias', 'neutral') if isinstance(mtf, dict) else 'neutral'
        alignment  = float(mtf.get('alignment', 0.33) if isinstance(mtf, dict) else 0.33)
        score_dir  = 1 if c.get('score', 0) > 0 else -1
        bias_dir   = 1 if mtf_bias == 'bullish' else -1 if mtf_bias == 'bearish' else 0
        if bias_dir != 0 and bias_dir == score_dir:
            pts_mtf = alignment * 10
        elif bias_dir != 0 and bias_dir != score_dir:
            pts_mtf = 0
        else:
            pts_mtf = 3  # neutral MTF

        # 6. Liquidity (0-10)
        pts_liq = float(liq.get('score', 5)) if liq else 5.0

        # 7. Pattern confirmation (0-10)
        breakdown = detail.get('breakdown', {}) or {}
        pattern_score = float((breakdown.get('pattern') or {}).get('score', 0) if isinstance(breakdown.get('pattern'), dict) else breakdown.get('pattern', 0) or 0)
        momentum_score = float((breakdown.get('momentum') or {}).get('score', 0) if isinstance(breakdown.get('momentum'), dict) else breakdown.get('momentum', 0) or 0)
        pts_pattern = min(10, max(0, (abs(pattern_score) + abs(momentum_score)) * 3 + 5))

        # 8. Portfolio regime (0-10)
        port_regime = portfolio_reg.get('regime', 'normal')
        pts_portfolio = {'favorable': 10, 'normal': 8, 'defensive': 5,
                         'capital_preservation': 0}.get(port_regime, 8)

        total = (pts_signal + pts_conf + pts_ev + pts_regime +
                 pts_mtf + pts_liq + pts_pattern + pts_portfolio)
        total = round(min(100, max(0, total)), 1)

        # ── Adaptive threshold — specific to this asset in this condition ────────
        # The threshold reflects what quality score is achievable and expected
        # for this exact asset class, regime, volatility, and trend strength.
        is_short_side = c.get('side', 'long') == 'short'
        _detail  = c.get('detail') or {}
        _sym     = c.get('symbol', '')
        _regime  = _detail.get('market_state', 'neutral')
        _adx     = float((data or {}).get('adx', 0) or 0)
        _atr_pct = float((data or {}).get('atr_pct', 2) or 2)
        _abs_score = abs(c.get('score', 0))

        # 1. Asset-class base (reflects structurally achievable confidence range)
        _asset_cls = _get_asset_class(_sym)
        _base = {'crypto': 44, 'forex': 46, 'futures': 46, 'equity': 50}.get(_asset_cls, 48)

        # 2. Regime clarity adjustment
        if _regime in ('trending_up', 'trending_down', 'breakout', 'accumulation'):
            _base -= 3   # clear regime = signals more reliable
        elif _regime in ('neutral', 'ranging'):
            _base += 3   # unclear regime = need stronger setup
        elif _regime in ('panic', 'news_driven', 'euphoric'):
            _base += 5   # chaotic regime = need very strong setup

        # 3. Trend strength (ADX)
        if _adx > 30:    _base -= 4   # very strong trend, high reliability
        elif _adx > 20:  _base -= 2   # confirmed trend
        elif _adx < 10:  _base += 3   # no trend, signals noisy

        # 4. Volatility — high ATR means confidence is structurally lower (not trader's fault)
        if _atr_pct > 6:   _base -= 4   # very volatile, confidence scoring penalizes heavily
        elif _atr_pct > 3: _base -= 2   # moderate-high volatility
        elif _atr_pct < 1: _base += 3   # stable asset, high confidence should be achievable

        # 5. Signal strength bonus — very strong signals get a lower bar
        if _abs_score >= 6.0:  _base -= 5
        elif _abs_score >= 4.5: _base -= 3
        elif _abs_score >= 3.5: _base -= 1

        # 6. Short direction gets slightly lower bar (downtrend confidence naturally lower)
        if is_short_side: _base -= 4

        # 7. Decay mode: tighten by 7pts when losing streak detected
        if history_ctx.get('decay_detected'): _base += 7

        # 8. Counter-trend: going against the confirmed regime needs higher bar
        _is_counter_trend = (
            (not is_short_side and _regime in ('trending_down', 'distribution', 'mild_downtrend')) or
            (is_short_side and _regime in ('trending_up', 'breakout', 'mild_uptrend'))
        )
        if _is_counter_trend: _base += 12   # counter-trend needs meaningful extra conviction

        # 9. Historical regime performance — auto-adjust from past trade outcomes
        _regime_history = history_ctx.get('regime_win_rates', {}).get(_regime, {})
        if _regime_history.get('trades', 0) >= 5:
            _wr = _regime_history['win_rate']
            if _wr >= 0.70:   _base -= 6   # this regime has been very profitable — lower bar
            elif _wr >= 0.60: _base -= 3   # above average — slight advantage
            elif _wr <= 0.30: _base += 8   # this regime has been losing — raise bar significantly
            elif _wr <= 0.40: _base += 4   # below average — tighten

        # 10. Historical per-symbol performance — learns from specific stock behavior
        _sym_history = history_ctx.get('symbol_win_rates', {}).get(_sym, {})
        if _sym_history.get('trades', 0) >= 3:
            _sym_wr = _sym_history['win_rate']
            _sym_pl = _sym_history.get('avg_pl', 0)
            if _sym_wr >= 0.70 and _sym_pl > 0:   _base -= 5   # symbol consistently profitable
            elif _sym_wr >= 0.60:                   _base -= 2   # slightly above average
            elif _sym_wr <= 0.30 or _sym_pl < -20: _base += 7   # symbol consistently losing
            elif _sym_wr <= 0.40:                   _base += 3   # below average

        threshold = int(max(34, min(70, _base)))  # slightly more permissive floor/ceiling

        return {
            'score':     total,
            'threshold': threshold,
            'passed':    total >= threshold,
            'breakdown': {
                'signal':    round(pts_signal, 1),
                'confidence': round(pts_conf, 1),
                'ev':        round(pts_ev, 1),
                'regime':    round(pts_regime, 1),
                'mtf':       round(pts_mtf, 1),
                'liquidity': round(pts_liq, 1),
                'pattern':   round(pts_pattern, 1),
                'portfolio': round(pts_portfolio, 1),
            },
        }
    except Exception:
        return {'score': 50, 'threshold': 62, 'passed': True, 'breakdown': {}}


def _compute_exposure(pid: int, equity: float, held_prices: dict) -> dict:
    """Return current exposure by asset class as fraction of equity."""
    if equity <= 0:
        return {k: 0.0 for k in ASSET_CLASS_CAPS}
    result = {k: 0.0 for k in ASSET_CLASS_CAPS}
    with _get_db() as conn:
        rows = conn.execute(
            'SELECT symbol, shares FROM sim_positions WHERE portfolio_id=? AND shares!=0', (pid,)
        ).fetchall()
    for row in rows:
        sym = row['symbol']
        price = held_prices.get(sym) or _get_current_price(sym)
        mkt_val = abs(row['shares']) * price
        cls = _get_asset_class(sym)
        result[cls] = result.get(cls, 0.0) + mkt_val / equity
    return result


def _compute_portfolio_heat(pid: int, equity: float) -> float:
    """Total active risk as fraction of equity: sum(pos_value * atr_pct / 100) across positions."""
    if equity <= 0:
        return 0.0
    total_heat = 0.0
    with _get_db() as conn:
        rows = conn.execute(
            'SELECT symbol, shares, avg_cost, stop_price FROM sim_positions WHERE portfolio_id=? AND shares!=0', (pid,)
        ).fetchall()
    for row in rows:
        try:
            sym = row['symbol']
            price = _get_current_price(sym)
            if not price:
                continue
            # Risk = distance from current price to stop
            if row['stop_price']:
                stop_dist = abs(price - row['stop_price'])
            else:
                # Estimate: use 2% as default risk
                stop_dist = price * 0.02
            position_risk = (abs(row['shares']) * stop_dist) / equity
            total_heat += position_risk
        except Exception:
            pass
    return round(total_heat, 4)


def _compute_cluster_exposure(new_sym: str, held_syms: list, pid: int, equity: float, held_prices: dict) -> float:
    """Return total portfolio exposure in the correlated cluster containing new_sym (as fraction of equity)."""
    if not _candle_engine or equity <= 0:
        return 0.0
    new_closes = _candle_engine.get_recent_closes(new_sym, '1m', 20)
    if len(new_closes) < 8:
        return 0.0
    cluster_value = 0.0
    with _get_db() as conn:
        rows = conn.execute(
            'SELECT symbol, shares FROM sim_positions WHERE portfolio_id=? AND shares!=0',
            (pid,)
        ).fetchall()
        pos_map = {r['symbol']: r['shares'] for r in rows}

    for held in held_syms:
        hc = _candle_engine.get_recent_closes(held, '1m', 20)
        n = min(len(new_closes), len(hc))
        if n < 8:
            continue
        a, b = new_closes[-n:], hc[-n:]
        ma, mb = sum(a)/n, sum(b)/n
        sa = (sum((x-ma)**2 for x in a)/n)**0.5
        sb = (sum((x-mb)**2 for x in b)/n)**0.5
        if sa > 0 and sb > 0:
            r = sum((a[i]-ma)*(b[i]-mb) for i in range(n)) / (n * sa * sb)
            if abs(r) > 0.65:
                price = held_prices.get(held) or _get_current_price(held)
                shares = abs(pos_map.get(held, 0))
                cluster_value += shares * price
    return cluster_value / equity


def _compute_corr_factor(new_sym: str, held_syms: list) -> float:
    """Return 0.5 if new symbol is highly correlated (r>0.7) with any held position."""
    if not _candle_engine or not held_syms:
        return 1.0
    new_closes = _candle_engine.get_recent_closes(new_sym, '1m', 20)
    if len(new_closes) < 8:
        return 1.0
    for held in held_syms:
        hc = _candle_engine.get_recent_closes(held, '1m', 20)
        n = min(len(new_closes), len(hc))
        if n < 8:
            continue
        a, b = new_closes[-n:], hc[-n:]
        ma, mb = sum(a)/n, sum(b)/n
        num = sum((a[i]-ma)*(b[i]-mb) for i in range(n))
        sa  = (sum((x-ma)**2 for x in a)/n)**0.5
        sb  = (sum((x-mb)**2 for x in b)/n)**0.5
        if sa > 0 and sb > 0 and abs(num / (n * sa * sb)) > 0.7:
            return 0.5
    return 1.0


def _is_fractional_asset(sym: str) -> bool:
    return sym.endswith('-USD') or sym.endswith('=X') or sym.endswith('=F')


def _liquidity_check(symbol: str, position_value: float, price: float) -> dict:
    """
    Estimate liquidity quality and slippage for a proposed trade.
    Returns {liquid, spread_pct, slippage_pct, score_0_10, skip_reason}
    """
    try:
        # Get avg daily volume from proj_cache or quick yfinance fetch
        avg_vol = 0
        if symbol in _proj_cache:
            payload, _ = _proj_cache[symbol]
            avg_vol = float(payload.get('_avg_vol', 0))

        if avg_vol <= 0:
            try:
                import yfinance as yf
                hist = yf.Ticker(symbol).history(period='20d', interval='1d')
                if not hist.empty:
                    avg_vol = float(hist['Volume'].mean())
                    # Cache it
                    if symbol in _proj_cache:
                        _proj_cache[symbol][0]['_avg_vol'] = avg_vol
            except Exception:
                pass

        # Spread from order_flow if available
        spread_pct = 0.05  # default 5bps assumption
        try:
            import order_flow as _of
            of_sig = _of.get_signal(symbol)
            ratio = of_sig.get('bid_ask_ratio', 0.5)
            spread_pct = abs(ratio - 0.5) * 0.2  # rough spread proxy
        except Exception:
            pass

        # Slippage estimate: position_value / (avg_daily_notional) × impact factor
        avg_notional = avg_vol * price if avg_vol > 0 and price > 0 else 1e9
        slippage_pct = min(0.05, (position_value / avg_notional) * 0.10) if avg_notional > 0 else 0.01

        # Liquidity score 0-10 (higher = more liquid)
        liq_score = 10.0
        if avg_notional < 1_000_000:    liq_score -= 4  # very thin
        elif avg_notional < 10_000_000: liq_score -= 2  # thin
        if spread_pct > 0.01:           liq_score -= 2  # wide spread
        if slippage_pct > 0.005:        liq_score -= 1  # significant impact
        liq_score = max(0.0, liq_score)

        return {
            'liquid':        liq_score >= 5,
            'spread_pct':    round(spread_pct * 100, 3),
            'slippage_pct':  round(slippage_pct * 100, 4),
            'score':         round(liq_score, 1),
            'avg_daily_vol': int(avg_vol),
            'skip_reason':   f'Illiquid ({liq_score:.0f}/10)' if liq_score < 3 else '',
        }
    except Exception:
        return {'liquid': True, 'spread_pct': 0, 'slippage_pct': 0,
                'score': 5.0, 'avg_daily_vol': 0, 'skip_reason': ''}


def _get_asset_class(sym: str) -> str:
    if sym.endswith('-USD'): return 'crypto'
    if sym.endswith('=X'):   return 'forex'
    if sym.endswith('=F'):   return 'futures'
    return 'equity'

# Hard caps: max portfolio exposure per asset class
ASSET_CLASS_CAPS = {
    'equity':  0.40,
    'crypto':  0.15,
    'forex':   0.20,
    'futures': 0.25,
}
# Profit floor multiplier × ATR% per asset class (replaces fixed 1.5%)
_PROFIT_FLOOR_ATR = {'crypto': 0.5, 'equity': 1.0, 'futures': 1.2, 'forex': 0.4}
# Target: $8 per position per 10 minutes = 0.1% on $8k position
# crypto 0.5×ATR: 1m ATR for BTC ~0.2% → floor = 0.1% = $8 per trade ✓
# equity 1.0×ATR: ~0.5% intraday move
# forex 0.4×ATR: ~0.15% on small pip moves
SINGLE_POS_CAPS = {
    'crypto':  0.08,   # raised: 4% → 8% per crypto ($8k on $100k) — need size for real profits
    'equity':  0.07,   # raised: 5% → 7% per stock position
    'forex':   0.05,   # raised: 4% → 5% per forex position
    'futures': 0.03,   # futures excluded from sim anyway
}
MAX_PORTFOLIO_HEAT = 0.05   # max 5% of equity at risk simultaneously
MAX_CLUSTER_EXPOSURE = 0.07 # max 7% of equity in any correlated cluster

# Futures contract multipliers (price × multiplier = notional value)
FUTURES_MULTIPLIERS = {
    'ES=F': 50, 'NQ=F': 20, 'YM=F': 5,  'RTY=F': 50,
    'CL=F': 1000, 'GC=F': 100, 'SI=F': 5000, 'NG=F': 10000,
    'ZB=F': 1000, 'ZN=F': 1000, 'BTC=F': 5, 'ETH=F': 50,
}
MAX_FUTURES_CONTRACTS = 3  # never hold more than 3 contracts of any futures instrument


def _seed_daily_candles(symbols: list) -> None:
    """Seed CandleEngine's 1d history from yfinance for MTF alignment on daily timeframe."""
    if not _candle_engine:
        return
    try:
        import yfinance as yf
        from candle_engine import _OHLCV
    except ImportError:
        return

    # Download all symbols at once
    try:
        bulk = yf.download(symbols, period='90d', interval='1d',
                           auto_adjust=True, progress=False, threads=True,
                           group_by='ticker')
    except Exception as e:
        print(f'[SEED] Bulk download failed: {e}')
        return

    for sym in symbols:
        try:
            # Extract per-symbol DataFrame
            if len(symbols) == 1:
                df = bulk
            elif sym in bulk.columns.get_level_values(0):
                df = bulk[sym]
            else:
                continue

            # Flatten if needed
            if hasattr(df.columns, 'levels'):
                df.columns = df.columns.get_level_values(0)

            df = df.dropna(subset=['Close'])
            if df.empty or len(df) < 5:
                continue

            with _candle_engine._lock:
                hist = _candle_engine._history[sym]['1d']
                for ts, row in df.iterrows():
                    try:
                        bar_ts = ts.timestamp()
                        o  = float(row['Open'])  if hasattr(row['Open'],  '__float__') else float(row['Open'].iloc[0])
                        h  = float(row['High'])  if hasattr(row['High'],  '__float__') else float(row['High'].iloc[0])
                        l  = float(row['Low'])   if hasattr(row['Low'],   '__float__') else float(row['Low'].iloc[0])
                        cl = float(row['Close']) if hasattr(row['Close'], '__float__') else float(row['Close'].iloc[0])
                        v  = float(row['Volume'] or 0)
                        if cl > 0:
                            hist.append(_OHLCV(open=o, high=h, low=l, close=cl, volume=v, ts=bar_ts))
                    except Exception:
                        continue
            print(f'[SEED] {sym}: {len(df)} bars')
        except Exception as e:
            print(f'[SEED] {sym}: {e}')


def _seed_intraday_candles(symbols: list) -> None:
    """Seed CandleEngine 1m history from intraday REST candles so indicators
    are warmed up immediately after restart (no waiting for 26+ live ticks).

    Crypto: Coinbase REST (free, US-accessible, no key)
    Others: yfinance 1m intraday
    """
    if not _candle_engine:
        return
    from candle_engine import _OHLCV
    import urllib.request, json as _json_seed

    def _seed_symbol(sym):
        try:
            bars = []
            if sym.endswith('-USD'):
                # Coinbase REST candles: granularity=60 (1 minute), up to 300 bars
                cb_sym = sym  # BTC-USD, ETH-USD etc. — Coinbase format matches
                url = f'https://api.exchange.coinbase.com/products/{cb_sym}/candles?granularity=60'
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=8) as r:
                    data = _json_seed.loads(r.read())
                # Coinbase returns [[time, low, high, open, close, volume], ...] newest first
                for row in reversed(data):
                    ts, lo, hi, op, cl, vol = float(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])
                    if cl > 0:
                        bars.append(_OHLCV(open=op, high=hi, low=lo, close=cl, volume=vol, ts=ts))
            else:
                # yfinance 1m intraday (equities, forex, futures)
                import yfinance as yf
                hist = yf.Ticker(sym).history(period='1d', interval='1m')
                if not hist.empty:
                    for ts_idx, row in hist.iterrows():
                        bar_ts = ts_idx.timestamp() if hasattr(ts_idx, 'timestamp') else float(ts_idx)
                        cl = float(row.get('Close', 0) or 0)
                        if cl > 0:
                            bars.append(_OHLCV(
                                open=float(row.get('Open', cl)),
                                high=float(row.get('High', cl)),
                                low=float(row.get('Low', cl)),
                                close=cl,
                                volume=float(row.get('Volume', 0) or 0),
                                ts=bar_ts,
                            ))

            if bars:
                with _candle_engine._lock:
                    _candle_engine._history[sym]['1m'].extend(bars)

                # Immediately compute indicators on seeded history so
                # candle_engine.latest() returns real data — not None — from first scan
                try:
                    from candle_engine import _compute_indicators
                    with _candle_engine._lock:
                        hist_deque = _candle_engine._history[sym]['1m']
                        indicators = _compute_indicators(hist_deque)
                    if indicators:
                        payload = {
                            'symbol': sym, 'interval': '1m',
                            'open':  bars[-1].open, 'high': bars[-1].high,
                            'low':   bars[-1].low,  'close': bars[-1].close,
                            'volume': bars[-1].volume,
                            'timestamp': bars[-1].ts, 'closed': True,
                            'source': 'seed', **indicators,
                        }
                        with _candle_engine._lock:
                            _candle_engine._latest[sym]['1m'] = payload
                    print(f'[SEED_1M] {sym}: {len(bars)} bars + indicators ready')
                except Exception as ie:
                    print(f'[SEED_1M] {sym}: {len(bars)} bars loaded (indicator error: {ie})')
        except Exception as e:
            print(f'[SEED_1M] {sym} failed: {e}')

    # Seed in parallel (quick, non-blocking)
    import threading
    threads = [threading.Thread(target=_seed_symbol, args=(s,), daemon=True) for s in symbols]
    for t in threads: t.start()
    for t in threads: t.join(timeout=15)


def _market_is_open() -> bool:
    """Return True if US equity market is currently open (Mon–Fri 09:30–16:00 ET)."""
    import datetime, zoneinfo
    now = datetime.datetime.now(zoneinfo.ZoneInfo('America/New_York'))
    if now.weekday() >= 5:          # Saturday=5, Sunday=6
        return False
    open_t  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    close_t = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    return open_t <= now < close_t


def _days_to_earnings(sym: str) -> int | None:
    """Return days until next earnings, or None if unknown. Negative = days since last."""
    if sym.endswith('-USD') or sym.endswith('=X') or sym.endswith('=F'):
        return None  # no earnings for crypto/forex/futures
    now_ts = _time.time()
    if sym in _earnings_cache:
        days, ts = _earnings_cache[sym]
        if now_ts - ts < EARNINGS_CACHE_TTL:
            return days
    try:
        import yfinance as yf
        import datetime
        dates = yf.Ticker(sym).earnings_dates
        if dates is None or dates.empty:
            _earnings_cache[sym] = (None, now_ts)
            return None
        now = datetime.datetime.now(datetime.timezone.utc)
        future = [d for d in dates.index if d.to_pydatetime() > now]
        if not future:
            _earnings_cache[sym] = (None, now_ts)
            return None
        next_e = min(future)
        delta = (next_e.to_pydatetime() - now).days
        _earnings_cache[sym] = (delta, now_ts)
        return delta
    except Exception:
        _earnings_cache[sym] = (None, now_ts)
        return None


def _session_size_factor(sym: str) -> float:
    """Return a position size multiplier (0.3–1.0) based on current session quality.

    Reduces allocation during low-liquidity periods:
    - Forex: full size only during London/NY overlap (8AM-12PM ET)
    - Equity/Futures: full size during RTH, reduced pre/post market
    - Crypto: slight reduction during low-liquidity weekend overnight
    - All: reduced during known high-risk event windows (FOMC day approx, etc.)
    Also reduces size around earnings events for equities.
    """
    asset_class = _get_asset_class(sym)

    # Earnings proximity check — overrides session timing for equities
    if asset_class == 'equity':
        dte = _days_to_earnings(sym)
        if dte is not None:
            if dte <= 1:  return 0.25   # earnings today/tomorrow — minimal size
            if dte <= 2:  return 0.50
            if dte <= 5:  return 0.75   # earnings week — reduced

    import datetime, zoneinfo
    now = datetime.datetime.now(zoneinfo.ZoneInfo('America/New_York'))
    hour = now.hour + now.minute / 60.0
    weekday = now.weekday()  # 0=Mon, 6=Sun

    if asset_class == 'forex':
        # London open: 3AM ET, NY open: 8AM ET, overlap ends: 12PM ET, London close: 12PM ET
        if 8.0 <= hour < 12.0:   return 1.0   # London/NY overlap — best liquidity
        if 3.0 <= hour < 8.0:    return 0.7   # London session only
        if 12.0 <= hour < 17.0:  return 0.6   # NY afternoon — fading liquidity
        if weekday >= 5:          return 0.3   # weekend — very thin
        return 0.4                              # Asian session / overnight

    if asset_class in ('equity', 'futures'):
        if not (weekday < 5):     return 0.5   # weekend futures
        if 9.5 <= hour < 10.0:   return 1.0   # opening 30 min — highest volatility/opportunity
        if 15.5 <= hour < 16.0:  return 1.0   # closing 30 min — high opportunity
        if 9.5 <= hour < 16.0:   return 0.85  # normal RTH
        if 8.0 <= hour < 9.5:    return 0.5   # pre-market
        if 16.0 <= hour < 18.0:  return 0.45  # early after-hours
        return 0.3                              # overnight

    if asset_class == 'crypto':
        if weekday >= 5 and (hour < 8.0 or hour > 22.0):
            return 0.6   # late weekend night — thin
        if 9.5 <= hour < 16.0:   return 1.0   # US market hours — highest crypto liquidity too
        return 0.85                             # other hours — still active

    return 1.0


def _build_history_context(pid: int) -> dict:
    """Read 30-day trade history, return threshold adjustments for this scan cycle.

    Includes per-regime win rates and per-symbol historical performance so the
    adaptive quality threshold can learn from specific past trades.
    """
    default = {'buy_thresh_adj': 0.0, 'sell_thresh_adj': 0.0,
                'cautious_regimes': set(), 'strong_regimes': set(),
                'regime_win_rates': {},    # {regime: win_rate} for threshold tuning
                'symbol_win_rates': {},    # {symbol: {win_rate, trades, avg_pl}} for per-symbol tuning
                'decay_detected': False, 'summary': ''}
    try:
        from performance_engine import PerformanceEngine
        pe = PerformanceEngine(DB_PATH)
        by_regime = pe.by_regime(pid, days=30)
        decay     = pe.decay_check(pid, short_window=7, long_window=30)

        ctx = dict(default)

        # Raise thresholds if recent 7-day performance is poor
        if decay.get('decay_detected') and decay.get('recent_win_rate', 0.5) < 0.40:
            ctx['buy_thresh_adj']  = 0.8
            ctx['sell_thresh_adj'] = 0.4
            ctx['decay_detected']  = True

        # Classify regimes + store win rates for threshold adaptation
        # Keys are now "regime | direction" e.g. "trending_down | short"
        for regime_key, stats in by_regime.items():
            if regime_key == '_total':
                continue
            n  = stats.get('trades', 0)
            wr = stats.get('win_rate', 0.5)
            ctx['regime_win_rates'][regime_key] = {'win_rate': wr, 'trades': n,
                                                   'avg_pl': stats.get('avg_pl', 0)}
            if n >= 5 and wr < 0.35:
                ctx['cautious_regimes'].add(regime_key)
            elif n >= 5 and wr > 0.65:
                ctx['strong_regimes'].add(regime_key)

        # Per-symbol historical performance (min 3 trades to be meaningful)
        try:
            import sqlite3
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            from datetime import datetime, timedelta
            cutoff = (datetime.utcnow() - timedelta(days=60)).isoformat()
            rows = conn.execute('''
                SELECT symbol, COUNT(*) as n,
                       AVG(CASE WHEN realized_pl > 0 THEN 1.0 ELSE 0.0 END) as win_rate,
                       AVG(realized_pl) as avg_pl
                FROM sim_trades
                WHERE portfolio_id=? AND side IN ('sell','cover')
                AND status='filled' AND created_at > ?
                GROUP BY symbol HAVING COUNT(*) >= 3
            ''', (pid, cutoff)).fetchall()
            conn.close()
            for r in rows:
                ctx['symbol_win_rates'][r['symbol']] = {
                    'win_rate': round(float(r['win_rate'] or 0.5), 3),
                    'trades':   int(r['n']),
                    'avg_pl':   round(float(r['avg_pl'] or 0), 2),
                }
        except Exception:
            pass

        parts = []
        if ctx['decay_detected']:
            parts.append(f"7d win rate {decay['recent_win_rate']:.0%} — thresholds raised")
        if ctx['cautious_regimes']:
            parts.append(f"Cautious regimes: {', '.join(sorted(ctx['cautious_regimes']))}")
        if ctx['strong_regimes']:
            parts.append(f"Strong regimes: {', '.join(sorted(ctx['strong_regimes']))}")
        good_syms = [s for s,v in ctx['symbol_win_rates'].items() if v['win_rate'] > 0.65]
        bad_syms  = [s for s,v in ctx['symbol_win_rates'].items() if v['win_rate'] < 0.35]
        if good_syms: parts.append(f"Profitable symbols: {', '.join(good_syms[:3])}")
        if bad_syms:  parts.append(f"Losing symbols: {', '.join(bad_syms[:3])}")
        ctx['summary'] = ' | '.join(parts) or 'Normal — no history adjustments'

        return ctx
    except Exception:
        return default


def _portfolio_regime(pid: int, equity: float) -> dict:
    """Classify the portfolio's own regime and return a size multiplier."""
    try:
        from performance_engine import PerformanceEngine
        pe = PerformanceEngine(DB_PATH)
        decay = pe.decay_check(pid, short_window=7, long_window=30)
        recent_wr = decay.get('recent_win_rate', 0.5)

        # Drawdown from high-water mark
        cb = None
        try:
            import circuit_breakers as _cb_mod
            cb = _cb_mod.get()
        except Exception:
            pass
        hwm = cb._hwm.get(pid, equity) if cb else equity
        drawdown = (hwm - equity) / hwm if hwm > equity else 0.0

        # Breadth signal
        try:
            import breadth_engine as _be
            breadth = _be.latest().get('signal', 'neutral')
        except Exception:
            breadth = 'neutral'

        # Classify portfolio regime
        if drawdown >= 0.10:
            regime = 'capital_preservation'
            mult   = 0.40
            reason = f'Drawdown {drawdown:.1%} — capital preservation mode'
        elif drawdown >= 0.06 and breadth in ('bear', 'strong_bear'):
            regime = 'defensive'
            mult   = 0.70
            reason = f'Drawdown {drawdown:.1%} + weak breadth — defensive sizing'
        elif recent_wr >= 0.60 and breadth in ('bull', 'strong_bull') and drawdown < 0.02:
            regime = 'favorable'
            mult   = 1.15
            reason = f'Win rate {recent_wr:.0%} + strong breadth — increasing allocation'
        else:
            regime = 'normal'
            mult   = 1.0
            reason = 'Normal conditions'

        return {'regime': regime, 'size_multiplier': mult, 'reason': reason,
                'drawdown': round(drawdown, 4), 'recent_win_rate': recent_wr}
    except Exception:
        return {'regime': 'normal', 'size_multiplier': 1.0, 'reason': 'default',
                'drawdown': 0.0, 'recent_win_rate': 0.5}


def _check_single_position_exit(pid: int, symbol: str, data: dict) -> None:
    """Event-triggered exit check for a single held position (called on bar close)."""
    try:
        with _get_db() as conn:
            row = conn.execute(
                'SELECT id, symbol, shares, avg_cost, stop_price FROM sim_positions WHERE portfolio_id=? AND symbol=? AND shares!=0',
                (pid, symbol)
            ).fetchone()
        if not row:
            return
        ATR_STOP_M = 1.5
        SELL_THRESH = -1.8
        COVER_THRESH = 1.0
        PROFIT_FLOOR = 0.015
        market_open = _market_is_open()
        tradeable = market_open or _is_fractional_asset(symbol)
        if not tradeable:
            return
        data['symbol'] = symbol
        detail = _ai_score_detailed(data)
        score  = detail['score']
        price  = data.get('last_price') or _get_current_price(symbol)
        if not price or price <= 0:
            return
        atr = data.get('atr') or (price * 0.02)
        is_short = row['shares'] < 0
        if is_short:
            entry = row['avg_cost']
            stop_m, tgt_m = _regime_stop_multiplier(detail['market_state'])
            new_stop = price + stop_m * atr
            cur_stop = row['stop_price'] if row['stop_price'] else entry + stop_m * atr
            trail = min(cur_stop, new_stop)
            tgt   = entry - tgt_m * atr
            if score >= COVER_THRESH or price >= trail or price <= tgt:
                reason = ('cover_signal' if score >= COVER_THRESH else 'stop_loss' if price >= trail else 'take_profit')
                fill = _apply_slippage(price, 'buy', atr, data.get('volume_ratio', 1.0), abs(row['shares']))
                _sim_cover(symbol, abs(row['shares']), fill, pid)
                _ai_log_entry(pid, symbol, 'COVER', score, fill, abs(row['shares']), f'{reason} (event) | {detail["summary"][:60]}',
                             market_state=detail.get('market_state', ''))
        else:
            prot = _protection_stage(row['avg_cost'], price, row['stop_price'], atr)
            trail = prot['new_stop'] or (row['avg_cost'] - ATR_STOP_M * atr)
            cur_stop = row['stop_price'] or (row['avg_cost'] - ATR_STOP_M * atr)
            if trail > cur_stop:
                with _get_db() as conn:
                    conn.execute('UPDATE sim_positions SET stop_price=? WHERE id=?', (round(trail,4), row['id']))
            _, tgt_m = _regime_stop_multiplier(detail['market_state'])
            tgt = row['avg_cost'] + tgt_m * atr
            profit_pct = (price - row['avg_cost']) / row['avg_cost'] if row['avg_cost'] > 0 else 0
            hit_floor = profit_pct >= PROFIT_FLOOR
            if score <= SELL_THRESH or price <= trail or price >= tgt or hit_floor:
                reason = ('sell_signal' if score <= SELL_THRESH else 'stop_loss' if price <= trail else 'profit_floor' if hit_floor else 'take_profit')
                fill = _apply_slippage(price, 'sell', atr, data.get('volume_ratio', 1.0), row['shares'])
                _sim_sell(symbol, row['shares'], fill, pid)
                _ai_log_entry(pid, symbol, 'SELL', score, fill, row['shares'], f'{reason} (event) | {detail["summary"][:60]}',
                             market_state=detail.get('market_state', ''))
    except Exception:
        pass


def _ai_run_portfolio(pid: int) -> dict:
    """One AI scan cycle: check existing positions, then scan a batch for buys."""
    MAX_POS      = 10   # max 10 positions — concentrate on quality
    CASH_RESERVE = 0.35    # keep 35% cash always — no more 50% in one trade
    ATR_STOP_M   = 0.8    # tighter stops — was 1.5, letting losers bleed too long
    ATR_TGT_M    = 2.0
    BATCH_SIZE   = 30   # raised from 25 — scan more symbols per cycle
    BUY_THRESH   = 3.5     # raised: overnight longs lost while shorts won — need higher long conviction
    SELL_THRESH  = -1.8    # exit sooner when signals turn bearish
    SHORT_THRESH = -2.5    # lowered: shorts working — allow more short entries
    COVER_THRESH = 1.0     # close short when signal turns neutral/bullish

    history_ctx = _build_history_context(pid)
    BUY_THRESH  = BUY_THRESH  + history_ctx['buy_thresh_adj']
    SELL_THRESH = SELL_THRESH + history_ctx['sell_thresh_adj']

    market_open = _market_is_open()
    mode        = 'full' if market_open else 'crypto_forex'
    summary     = {'pid': pid, 'scanned': 0, 'bought': [], 'sold': [],
                   'shorted': [], 'covered': [],
                   'errors': [], 'skipped': [], 'mode': mode, 'skip_reason': None}
    batch_data  = []

    # Load strategy engine (lazy import — engine is in same directory)
    try:
        import strategy_engine as _se
        _strategy_engine = _se.get_engine()
    except Exception:
        _strategy_engine = None

    try:
        # ── 1. Check held positions for exits + cover shorts ───────────────
        # Exits run regardless of market hours (stops/signals still evaluated)
        with _get_db() as conn:
            pos_rows = conn.execute(
                'SELECT id, symbol, shares, avg_cost, stop_price, created_at FROM sim_positions WHERE portfolio_id=? AND shares!=0',
                (pid,)
            ).fetchall()

        for row in pos_rows:
            sym       = row['symbol']
            is_short  = row['shares'] < 0
            try:
                data  = _compute_indicators_fast(sym)
                data['symbol'] = sym
                price  = data.get('last_price') or _get_current_price(sym)
                detail = _ai_score_detailed(data)
                score  = detail['score']
                atr    = data.get('atr') or (price * 0.02)
                tradeable = market_open or _is_fractional_asset(sym)

                if is_short:
                    # ── Short position: trailing stop trails DOWN as price falls ──
                    short_qty    = abs(row['shares'])
                    entry_price  = row['avg_cost']
                    # Trailing stop for shorts: min(current_stop, price + stop_m*atr)
                    # — stop trails downward as price falls, protecting profit
                    stop_m, tgt_m = _regime_stop_multiplier(detail['market_state'])
                    new_stop     = price + stop_m * atr
                    current_stop = row['stop_price'] if row['stop_price'] else (entry_price + stop_m * atr)
                    trailing_stop = min(current_stop, new_stop)
                    if trailing_stop < current_stop:
                        with _get_db() as conn:
                            conn.execute('UPDATE sim_positions SET stop_price=? WHERE id=?',
                                         (trailing_stop, row['id']))
                    # Target: price falling tgt_m below entry
                    tgt_price    = entry_price - tgt_m * atr

                    if tradeable and (score >= COVER_THRESH or price >= trailing_stop or price <= tgt_price):
                        reason = ('cover_signal' if score >= COVER_THRESH
                                  else 'stop_loss'    if price >= trailing_stop
                                  else 'take_profit')
                        fill = _apply_slippage(price, 'buy', atr, data.get('volume_ratio', 1.0), short_qty)
                        _sim_cover(sym, short_qty, fill, pid)
                        try:
                            import circuit_breakers as _cb_mod
                            _cb_mod.record_result(
                                pid,
                                profitable=(price <= entry_price),
                                strategy=detail.get('strategy', ''),
                                regime=detail.get('market_state', '')
                            )
                        except Exception:
                            pass
                        summary['covered'].append({'symbol': sym, 'price': round(fill, 2),
                                                   'score': score, 'reason': reason,
                                                   'market_state': detail['market_state'],
                                                   'type': 'cover'})
                        _ai_log_entry(pid, sym, 'COVER', score, fill, short_qty,
                                      f"{reason} | short closed | {detail['summary'][:80]}",
                                      market_state=detail.get('market_state',''))
                else:
                    # ── Long position: profit-protection engine ────────────────────
                    stop_m, tgt_m = _regime_stop_multiplier(detail['market_state'])
                    prot = _protection_stage(row['avg_cost'], price,
                                             row['stop_price'], atr)
                    trailing = prot['new_stop'] or (row['avg_cost'] - stop_m * atr)
                    tgt      = row['avg_cost'] + tgt_m * atr

                    # Update stop if protection engine recommends higher level
                    current_stop = row['stop_price'] or (row['avg_cost'] - stop_m * atr)
                    if trailing > current_stop:
                        with _get_db() as conn:
                            conn.execute('UPDATE sim_positions SET stop_price=? WHERE id=?',
                                         (round(trailing, 4), row['id']))
                    profit_pct = (price - row['avg_cost']) / row['avg_cost'] if row['avg_cost'] > 0 else 0
                    _pf_mult    = _PROFIT_FLOOR_ATR.get(_get_asset_class(sym), 1.0)
                    _atr_pct_v  = float(data.get('atr_pct', 2.0) or 2.0)
                    profit_floor = _pf_mult * _atr_pct_v / 100   # dynamic: e.g., crypto 0.8×3% = 2.4%
                    hit_profit_floor = profit_pct >= profit_floor

                    if tradeable and (score <= SELL_THRESH or price <= trailing or price >= tgt or hit_profit_floor):
                        reason = ('sell_signal'   if score <= SELL_THRESH
                                  else 'stop_loss'    if price <= trailing
                                  else 'profit_floor' if hit_profit_floor
                                  else 'take_profit')
                        fill = _apply_slippage(price, 'sell', atr, data.get('volume_ratio', 1.0), row['shares'])
                        _sim_sell(sym, row['shares'], fill, pid)
                        try:
                            import circuit_breakers as _cb_mod
                            _cb_mod.record_result(
                                pid,
                                profitable=(price >= row['avg_cost']),
                                strategy=detail.get('strategy', ''),
                                regime=detail.get('market_state', '')
                            )
                        except Exception:
                            pass
                        # RL outcome recording
                        try:
                            import rl_engine as _rl_mod
                            if _rl_mod.get_engine():
                                # Find the original RL state/action from ai_log (best effort)
                                with _get_db() as _conn:
                                    _log = _conn.execute(
                                        'SELECT reason FROM ai_log WHERE portfolio_id=? AND symbol=? AND action=? ORDER BY id DESC LIMIT 1',
                                        (pid, sym, 'BUY')
                                    ).fetchone()
                                pl = (fill - row['avg_cost']) * row['shares']
                                max_r = ATR_STOP_M * atr * row['shares']
                                _rl_mod.record_outcome('', '', pl, max(max_r, 1.0))
                        except Exception:
                            pass
                        summary['sold'].append({'symbol': sym, 'price': round(fill, 2),
                                                'score': score, 'reason': reason,
                                                'market_state': detail['market_state'],
                                                'type': 'sell'})
                        _ai_log_entry(pid, sym, 'SELL', score, fill, row['shares'],
                                      f"{reason} | {detail['summary'][:80]}",
                                      market_state=detail.get('market_state',''))
                    # ── Bearish intelligence: gradual trim ────────────────────────
                    elif tradeable and not (score <= SELL_THRESH or price <= trailing or price >= tgt or hit_profit_floor):
                        try:
                            import bearish_engine as _be
                            b_result = _be.score(sym, data, row['avg_cost'], price)
                            trim_frac = _be.get_engine().trim_fraction(b_result['score'])
                            if trim_frac > 0:
                                trim_shares = round(row['shares'] * trim_frac, 4)
                                remaining_shares = row['shares'] - trim_shares
                                # If remainder would be dust (< $10 value), close the full position
                                if remaining_shares * price < 10.0:
                                    trim_shares = row['shares']
                                if trim_shares >= 0.001:
                                    fill = _apply_slippage(price, 'sell', atr, data.get('volume_ratio', 1.0), trim_shares)
                                    _sim_sell(sym, trim_shares, fill, pid)
                                    summary['sold'].append({
                                        'symbol': sym, 'price': round(fill, 2),
                                        'score': score, 'reason': f'bearish_trim_{b_result["level"]}',
                                        'market_state': detail['market_state'],
                                        'trim_pct': int(trim_frac * 100),
                                    })
                                    _ai_log_entry(pid, sym, 'SELL', score, fill, trim_shares,
                                                  f'bearish trim {int(trim_frac*100)}% | {b_result["description"][:60]}',
                                                  market_state=detail.get('market_state',''))
                        except Exception:
                            pass
            except Exception as e:
                summary['errors'].append(f'exit {sym}: {e}')

        # ── 2. Compute equity and available cash ───────────────────────────
        state = _sim_state(pid)
        cash  = state['cash']
        with _get_db() as conn:
            held = [r['symbol'] for r in conn.execute(
                'SELECT symbol FROM sim_positions WHERE portfolio_id=? AND shares!=0', (pid,)
            ).fetchall()]

        equity = cash
        for sym in held:
            try:
                equity += _get_current_price(sym) * next(
                    r['shares'] for r in pos_rows if r['symbol'] == sym
                )
            except Exception:
                pass

        # Portfolio regime — computed once after equity is known
        port_regime = _portfolio_regime(pid, equity)

        # ── Portfolio P&L awareness + emergency unrealized loss gate ──────────
        state_initial = _sim_state(pid).get('initial_cash', 100000)
        portfolio_loss_pct = (state_initial - equity) / state_initial if state_initial > 0 else 0
        if portfolio_loss_pct > 0.05:
            BUY_THRESH = 99.0
            summary['skip_reason'] = summary.get('skip_reason') or 'portfolio_loss_protection'
        elif portfolio_loss_pct > 0.03:
            BUY_THRESH = max(BUY_THRESH, 5.0)

        # Emergency: if open unrealized losses > 1.5% of equity, tighten all stops to near-current price
        try:
            unreal = sum(p.get('unrealized_pl', 0) or 0 for p in _sim_positions_with_prices(pid))
            unreal_pct = abs(unreal) / equity if equity > 0 and unreal < 0 else 0
            if unreal_pct > 0.015:  # losing more than 1.5% on open positions
                ATR_STOP_M = 0.3   # emergency tighten — get out faster
                BUY_THRESH = 99.0  # no new entries while bleeding
        except Exception:
            pass

        # FIX: reserve is a % of CASH, not equity
        available = cash - cash * CASH_RESERVE
        can_buy   = len(held) < MAX_POS and available > 100
        if not can_buy:
            summary['skip_reason'] = 'max_positions' if len(held) >= MAX_POS else 'low_cash'

        # ── 3. Scan batch of universe symbols ──────────────────────────────
        # Always scan regardless of buy eligibility — gives visibility into market state.
        # Merge AI universe with portfolio's watchlist so any watchlisted symbol gets scanned
        with _get_db() as conn:
            wl_syms = [r['symbol'] for r in conn.execute(
                'SELECT symbol FROM watchlist_items WHERE portfolio_id=?', (pid,)
            ).fetchall()]
        combined_universe = list(dict.fromkeys(_AI_UNIVERSE + wl_syms))
        universe = [s for s in combined_universe if s not in held]
        # Outside market hours only scan crypto/forex (24/7 assets)
        if not market_open:
            universe = [s for s in universe if _is_fractional_asset(s)]
        if not universe:
            return summary
        cursor   = _ai_scan_cursor.get(pid, 0)
        batch    = [universe[(cursor + i) % len(universe)] for i in range(min(BATCH_SIZE, len(universe)))]
        _ai_scan_cursor[pid] = (cursor + BATCH_SIZE) % max(len(universe), 1)

        candidates = []
        batch_data = []
        for sym in batch:
            try:
                data  = _compute_indicators_fast(sym)
                data['symbol'] = sym
                price = data.get('last_price')
                if not price or price <= 0:
                    batch_data.append({'symbol': sym, 'score': 0, 'price': 0,
                                       'market_state': 'neutral', 'rsi': 50,
                                       'trend': '—', 'qualifies': False,
                                       'qualifies_short': False, 'error': 'no_price'})
                    continue
                # Anomaly detection — updates rolling history and flags outliers
                try:
                    import anomaly_detection as _ad
                    anomaly = _ad.check_and_update(sym, data)
                    data['_anomaly']      = anomaly['anomaly']
                    data['_anomaly_mult'] = anomaly['size_mult']
                    if anomaly['anomaly']:
                        data['_anomaly_desc'] = anomaly['description']
                except Exception:
                    pass
                detail = _ai_score_detailed(data)
                score  = detail['score']
                # Apply market-specific strategy adjustments
                if _strategy_engine:
                    try:
                        strat_result = _strategy_engine.score(
                            sym, data, score, detail.get('uncertainty', 0.3)
                        )
                        score  = strat_result['score']
                        detail['strategy']   = strat_result['strategy']
                        detail['confidence'] = strat_result['confidence']
                        detail['rationale']  = strat_result['rationale']
                    except Exception:
                        pass
                confidence = _compute_confidence(score, data, detail)
                summary['scanned'] += 1
                qualifies_long  = score >= BUY_THRESH
                qualifies_short = score <= SHORT_THRESH
                # Block shorts when price is going UP or direction is unknown
                # accumulation removed: longs in accumulation had 3% win rate (74 trades) — allow shorts instead
                _no_short_regimes = ('ranging', 'neutral', 'mild_uptrend',
                                     'oversold_extreme', 'trending_up', 'breakout', 'news_driven')
                if qualifies_short and detail['market_state'] in _no_short_regimes:
                    qualifies_short = False
                    _log_decision(pid, sym, 'REJECT', score, detail['market_state'],
                                  'regime_no_short', f'no shorts in {detail["market_state"]} — sideways market')

                # accumulation added: longs in accumulation had 3% win rate (74 trades) — blocked
                _no_long_regimes = ('breakout', 'trending_up', 'overbought_extreme', 'euphoric',
                                    'distribution', 'trending_down', 'mild_downtrend', 'news_driven',
                                    'accumulation')
                if qualifies_long and detail['market_state'] in _no_long_regimes:
                    qualifies_long = False
                    _log_decision(pid, sym, 'REJECT', score, detail['market_state'],
                                  'regime_no_long', f'longs blocked in {detail["market_state"]}')

                # Crypto macro filter: if BTC is trending down on 1h, block ALL crypto longs
                isCrypto = lambda s: s.endswith('-USD')
                # Micro-caps bounce off RSI oversold but don't sustain without BTC leadership
                if qualifies_long and isCrypto(sym):
                    try:
                        _btc_data = _candle_engine.latest('BTC-USD', '1h') if _candle_engine else None
                        if not _btc_data:
                            import yfinance as _yf_btc
                            _btc_hist = _yf_btc.Ticker('BTC-USD').history(period='2d', interval='1h')
                            if not _btc_hist.empty and len(_btc_hist) >= 5:
                                _btc_closes = list(_btc_hist['Close'].dropna())
                                _btc_trend = 'up' if _btc_closes[-1] > sum(_btc_closes[-5:])/5 else 'down'
                            else:
                                _btc_trend = 'neutral'
                        else:
                            _btc_trend = _btc_data.get('trend', 'sideways')
                        if _btc_trend == 'down':
                            qualifies_long = False
                            _log_decision(pid, sym, 'REJECT', score, detail['market_state'],
                                          'btc_macro', f'BTC 1h trending down — no crypto longs')
                    except Exception:
                        pass

                # Skip entries in regime+direction combos with poor 30-day history
                _long_key  = f"{detail['market_state']} | long"
                _short_key = f"{detail['market_state']} | short"
                if qualifies_long and _long_key in history_ctx['cautious_regimes']:
                    qualifies_long = False
                    _log_decision(pid, sym, 'REJECT', score, detail['market_state'],
                                  'cautious_regime', f'{_long_key} has <35% win rate')
                if qualifies_short and _short_key in history_ctx['cautious_regimes']:
                    qualifies_short = False
                    _log_decision(pid, sym, 'REJECT', score, detail['market_state'],
                                  'cautious_regime', f'{_short_key} has <35% win rate')

                # Compute quality preview for every symbol (not just qualifying ones)
                # Uses lightweight assumptions for liquidity (avoids slow per-symbol API calls)
                _preview_side = 'short' if score < 0 else 'long'
                try:
                    _preview_q = _compute_trade_quality(
                        {'score': score, 'confidence': confidence, 'detail': detail,
                         'side': _preview_side},
                        history_ctx,
                        port_regime,
                        {'score': 6.0, 'liquid': True},   # assume reasonable liquidity
                        data,
                    )
                    _preview_qual = _preview_q['score']
                    _preview_thresh = _preview_q['threshold']
                except Exception:
                    _preview_qual  = None
                    _preview_thresh = 62

                batch_data.append({
                    'symbol': sym, 'score': round(score, 2), 'price': round(price, 2),
                    'market_state': detail['market_state'],
                    'rsi': round(data.get('rsi', 50), 1),
                    'trend': data.get('trend', ''),
                    'qualifies': qualifies_long,
                    'qualifies_short': qualifies_short,
                    'confidence': confidence,
                    'trade_quality': round(_preview_qual, 1) if _preview_qual is not None else None,
                    'quality_threshold': _preview_thresh,
                })
                if qualifies_long:
                    candidates.append({'symbol': sym, 'score': score, 'price': price,
                                       'atr': data.get('atr'), 'atr_pct': float(data.get('atr_pct', 2.0) or 2.0),
                                       'detail': detail,
                                       'volume_ratio': data.get('volume_ratio', 1.0),
                                       'side': 'long', 'confidence': confidence,
                                       'anomaly': data.get('_anomaly', False),
                                       'anomaly_mult': data.get('_anomaly_mult', 1.0)})
                elif qualifies_short:
                    candidates.append({'symbol': sym, 'score': score, 'price': price,
                                       'atr': data.get('atr'), 'atr_pct': float(data.get('atr_pct', 2.0) or 2.0),
                                       'detail': detail,
                                       'volume_ratio': data.get('volume_ratio', 1.0),
                                       'side': 'short', 'confidence': confidence,
                                       'anomaly': data.get('_anomaly', False),
                                       'anomaly_mult': data.get('_anomaly_mult', 1.0)})
            except Exception as e:
                summary['errors'].append(f'scan {sym}: {e}')
                batch_data.append({'symbol': sym, 'score': 0, 'price': 0,
                                   'market_state': 'neutral', 'rsi': 50,
                                   'trend': '—', 'qualifies': False,
                                   'qualifies_short': False, 'error': str(e)[:40]})

        candidates.sort(key=lambda x: abs(x['score']), reverse=True)

        # Build held prices for exposure calculations
        held_prices = {}
        for sym in held:
            try:
                held_prices[sym] = _get_current_price(sym)
            except Exception:
                pass

        # ── 4. Buy top candidates (only if eligible) ───────────────────────
        n_pos = len(held)
        for c in candidates if can_buy else []:
            if n_pos >= MAX_POS or available <= 100:
                break

            asset_class = _get_asset_class(c['symbol'])

            # ── Liquidity check ───────────────────────────────────────────────
            liq_info = _liquidity_check(c['symbol'], 0, c['price'])  # position_value TBD
            if liq_info.get('score', 5) < 3:  # extremely illiquid
                summary['errors'].append(f"skip {c['symbol']}: {liq_info['skip_reason']}")
                continue

            # ── Trade Quality gate ────────────────────────────────────────────
            quality = _compute_trade_quality(c, history_ctx, port_regime, liq_info, {})
            c['trade_quality'] = quality['score']
            if not quality['passed']:
                summary['errors'].append(
                    f"skip {c['symbol']}: quality {quality['score']:.0f}/{quality['threshold']} below threshold"
                )
                _log_decision(pid, c['symbol'], 'REJECT', c.get('score', 0),
                              c.get('detail', {}).get('market_state', ''),
                              'quality_gate', f"quality {quality['score']:.0f}/{quality['threshold']}")
                continue

            # ── RL engine: get recommended action for this market state ────────
            rl_action = {}
            rl_state_key  = ''
            rl_action_key = ''
            rl_risk_pct   = 0.005
            try:
                import rl_engine as _rl_mod
                _closed_count = 0
                try:
                    with _get_db() as _rc:
                        _closed_count = (_rc.execute(
                            "SELECT COUNT(*) FROM sim_trades WHERE portfolio_id=? AND side IN ('sell','cover')",
                            (pid,)
                        ).fetchone() or [0])[0]
                except Exception:
                    pass
                # RL needs 500+ real closed trades before its Q-table has meaningful data
                if _rl_mod.get_engine() and _closed_count >= 500:
                    mtf_b  = c.get('detail', {}).get('mtf_bias', {}).get('bias', 'neutral')
                    swing_b = 'undefined'
                    try:
                        import structure_engine as _se
                        snap = _se.snapshot(c['symbol'])
                        swing_b = snap.get('swing_bias', 'undefined')
                    except Exception:
                        pass
                    heat = _compute_portfolio_heat(pid, equity)
                    rl_action = _rl_mod.get_action(
                        regime=c.get('detail', {}).get('market_state', 'neutral'),
                        mtf_bias=mtf_b, swing_bias=swing_b, portfolio_heat=heat
                    )
                    rl_state_key  = rl_action.get('state_key', '')
                    rl_action_key = f"{rl_action.get('strategy','momentum')}|{rl_action.get('size_tier','medium')}|{rl_action.get('timing','immediate')}"
                    rl_risk_pct = rl_action.get('risk_pct', 0.005)
            except Exception:
                rl_risk_pct = 0.005

            # Store RL keys in candidate for later outcome recording
            c['_rl_state']  = rl_state_key
            c['_rl_action'] = rl_action_key

            # ── 1. Risk-per-trade sizing ──────────────────────────────────────
            # Risk 1.5%–2.5% of equity per trade — was 0.5–1.0%, was leaving $90k idle
            RISK_PER_TRADE     = 0.010   # 1.0% risk per trade — need real size for real profits
            MAX_RISK_PER_TRADE = 0.015   # 1.5% on high-conviction signals
            score_factor = min(1.0, max(0.0, (abs(c['score']) - BUY_THRESH) / max(5.0 - BUY_THRESH, 1)))
            rule_risk_pct = RISK_PER_TRADE + score_factor * (MAX_RISK_PER_TRADE - RISK_PER_TRADE)
            # Blend 70% rule-based + 30% RL-recommended risk
            rl_r = rl_risk_pct
            risk_pct = rule_risk_pct * 0.7 + rl_r * 0.3

            atr_val       = c.get('atr') or (c['price'] * 0.02)
            stop_m, _     = _regime_stop_multiplier(c['detail']['market_state'])
            stop_dist     = stop_m * atr_val               # dollars of risk per share
            dollar_risk   = equity * risk_pct              # total dollars to risk on this trade
            raw_shares    = dollar_risk / stop_dist if stop_dist > 0 else 0
            position_value = raw_shares * c['price']

            # ── 2. Correlation scale ──────────────────────────────────────────
            corr_scale    = _compute_corr_factor(c['symbol'], held)
            position_value *= corr_scale

            # ── 3. Single-position cap ────────────────────────────────────────
            single_cap    = SINGLE_POS_CAPS.get(asset_class, 0.05)
            position_value = min(position_value, equity * single_cap)

            # ── 4. Asset-class exposure cap ───────────────────────────────────
            try:
                exposure = _compute_exposure(pid, equity, held_prices)
                class_used = exposure.get(asset_class, 0.0)
                class_cap  = ASSET_CLASS_CAPS.get(asset_class, 0.40)
                class_room = max(0.0, (class_cap - class_used) * equity)
                position_value = min(position_value, class_room)
            except Exception:
                pass

            # ── 5. Portfolio heat cap ─────────────────────────────────────────
            try:
                heat = _compute_portfolio_heat(pid, equity)
                if heat >= MAX_PORTFOLIO_HEAT:
                    summary['skipped'].append(f'{c["symbol"]}: heat {heat:.1%}')
                    _log_decision(pid, c['symbol'], 'REJECT', c.get('score', 0),
                                  '', 'portfolio_heat', f'heat {heat:.1%}')
                    continue
                heat_room = (MAX_PORTFOLIO_HEAT - heat) * equity
                trade_heat = raw_shares * stop_dist
                if trade_heat > heat_room:
                    scale = heat_room / trade_heat if trade_heat > 0 else 1.0
                    position_value *= scale
                    raw_shares *= scale
            except Exception:
                pass

            # ── 6. Correlated cluster cap ─────────────────────────────────────
            try:
                cluster_exp = _compute_cluster_exposure(c['symbol'], held, pid, equity, held_prices)
                if cluster_exp >= MAX_CLUSTER_EXPOSURE:
                    summary['skipped'].append(f'{c["symbol"]}: correlated cluster {cluster_exp:.1%}')
                    _log_decision(pid, c['symbol'], 'REJECT', c.get('score', 0),
                                  '', 'correlation', f'cluster {cluster_exp:.1%}')
                    continue
                cluster_room = max(0.0, (MAX_CLUSTER_EXPOSURE - cluster_exp) * equity)
                position_value = min(position_value, cluster_room)
            except Exception:
                pass

            # ── Portfolio regime sizing ───────────────────────────────────────
            position_value *= port_regime.get('size_multiplier', 1.0)

            # ── 7. Session quality factor ─────────────────────────────────────
            session_f  = _session_size_factor(c['symbol'])
            position_value *= session_f
            if session_f < 1.0:
                summary.setdefault('session_notes', []).append(
                    f"{c['symbol']}: session factor {session_f:.0%}"
                )

            # ── Volume confirmation ───────────────────────────────────────────
            _vol_sig = c.get('detail', {}).get('breakdown', {}).get('volume', {})
            if isinstance(_vol_sig, dict):
                _vsig_name = _vol_sig.get('signal', '')
                if _vsig_name == 'low_volume':
                    # Low volume: reduce size 50% (uncertain signal)
                    position_value *= 0.5

            # Confidence gate REMOVED — confidence is already baked into quality score.
            # Blocking on confidence separately caused 98.1% of all rejections (crypto
            # structurally scores 15-30 due to ATR penalty, so this gate blocked everything).

            # ── Circuit breaker check ─────────────────────────────────────────
            try:
                import circuit_breakers as _cb_mod
                breaker = _cb_mod.check(
                    pid, equity,
                    strategy=c.get('detail', {}).get('strategy', ''),
                    regime=c.get('detail', {}).get('market_state', '')
                )
                if not breaker['allowed']:
                    summary['errors'].append(
                        f"skip {c['symbol']}: circuit breaker — {breaker['reason']}"
                    )
                    _log_decision(pid, c['symbol'], 'REJECT', c.get('score', 0),
                                  c.get('detail', {}).get('market_state', ''),
                                  'circuit_breaker', breaker.get('reason', ''))
                    continue
                position_value *= breaker['size_mult']
            except Exception:
                pass

            # ── Anomaly size reduction ────────────────────────────────────────
            anomaly_mult = c.get('anomaly_mult', 1.0)
            if anomaly_mult < 1.0:
                position_value *= anomaly_mult

            # ── Futures: skip entirely — notional exposure is too large for sim
            # YM=F at $51k per contract, ES=F at $250k notional — distort portfolio badly
            # Futures signals are useful for market context but not for sim trading
            if asset_class == 'futures':
                _log_decision(pid, c['symbol'], 'REJECT', c.get('score', 0),
                              c.get('detail', {}).get('market_state', ''),
                              'futures_skipped', 'futures excluded from sim — notional too large')
                continue

            alloc = min(position_value, available)
            if alloc < 10:
                continue
            raw_shares = alloc / c['price']
            shares = raw_shares if _is_fractional_asset(c['symbol']) else max(1, int(raw_shares))
            alloc  = shares * c['price']
            if alloc > available:
                continue
            try:
                side = c.get('side', 'long')
                atr_val = c.get('atr') or c['price'] * 0.02
                if side == 'long':
                    fill = _apply_slippage(c['price'], 'buy', atr_val, c.get('volume_ratio', 1.0), shares)
                    _sim_buy(c['symbol'], shares, fill, pid)
                    init_stop = fill - stop_m * atr_val   # for longs
                    with _get_db() as conn:
                        conn.execute(
                            'UPDATE sim_positions SET stop_price=? WHERE symbol=? AND portfolio_id=? AND stop_price IS NULL',
                            (init_stop, c['symbol'], pid)
                        )
                    summary['bought'].append({
                        'symbol': c['symbol'], 'price': round(fill, 2),
                        'shares': round(shares, 4), 'score': c['score'],
                        'market_state': c['detail']['market_state'],
                        'summary': c['detail']['summary'][:100],
                        'type': 'buy',
                        'trade_quality': c.get('trade_quality', None),
                    })
                    _ai_log_entry(pid, c['symbol'], 'BUY', c['score'], fill, shares,
                                  f"score {c['score']:+.1f} | {c['detail']['summary'][:80]}",
                                  market_state=c.get('detail', {}).get('market_state', ''))
                    import json as _json_d
                    _log_decision(pid, c['symbol'], 'ACCEPT', c.get('score', 0),
                                  c.get('detail', {}).get('market_state', ''),
                                  'opened', f"long at ${fill:.2f}",
                                  quality_score=quality.get('score') if 'quality' in dir() else None,
                                  size_mult=c.get('quality_size_mult'),
                                  signal_json=_json_d.dumps({
                                      'confidence': c.get('confidence', 0),
                                      'atr_pct': c.get('atr_pct', 0),
                                  }))
                else:  # short
                    fill = _apply_slippage(c['price'], 'sell', atr_val, c.get('volume_ratio', 1.0), shares)
                    _sim_short(c['symbol'], shares, fill, pid)
                    summary['shorted'].append({
                        'symbol': c['symbol'], 'price': round(fill, 2),
                        'shares': round(shares, 4), 'score': c['score'],
                        'market_state': c['detail']['market_state'],
                        'summary': c['detail']['summary'][:100],
                        'type': 'short',
                    })
                    _ai_log_entry(pid, c['symbol'], 'SHORT', c['score'], fill, shares,
                                  f"score {c['score']:+.1f} | bearish short | {c['detail']['summary'][:80]}",
                                  market_state=c.get('detail', {}).get('market_state', ''))
                    import json as _json_d
                    _log_decision(pid, c['symbol'], 'ACCEPT', c.get('score', 0),
                                  c.get('detail', {}).get('market_state', ''),
                                  'opened', f"short at ${fill:.2f}",
                                  quality_score=quality.get('score') if 'quality' in dir() else None,
                                  size_mult=c.get('quality_size_mult'),
                                  signal_json=_json_d.dumps({
                                      'confidence': c.get('confidence', 0),
                                      'atr_pct': c.get('atr_pct', 0),
                                  }))
                n_pos    += 1
                available -= alloc
            except Exception as e:
                summary['errors'].append(f'open {c["symbol"]}: {e}')

        # ── Manage open options positions (exit at profit target / DTE / stop) ──
        try:
            import options_strategy as _os_mod
            _mgr = _os_mod.get_manager()
            if _mgr:
                _opt_result = _mgr.manage_open_positions(pid)
                for _closed in _opt_result.get('closed', []):
                    summary['sold'].append({
                        'symbol': _closed.get('symbol', ''), 'price': 0,
                        'score': 0, 'reason': f"options_{_closed.get('reason','exit')}",
                        'market_state': 'options',
                    })
        except Exception:
            pass

    except Exception as e:
        summary['errors'].append(f'portfolio error: {e}')
    finally:
        # Always record the scan run (even when early-returning due to max positions)
        import json as _json
        try:
            with _get_db() as conn:
                conn.execute(
                    '''INSERT INTO ai_scan_runs
                       (portfolio_id, scanned, bought_count, sold_count, error_count,
                        bought_json, sold_json, batch_json, mode, skip_reason,
                        history_context, skipped_json)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (pid, summary['scanned'],
                     len(summary['bought']) + len(summary['shorted']),
                     len(summary['sold'])   + len(summary['covered']),
                     len(summary['errors']),
                     _json.dumps(summary['bought'] + summary['shorted']),
                     _json.dumps(summary['sold']   + summary['covered']),
                     _json.dumps(batch_data),
                     summary.get('mode', 'full'),
                     summary.get('skip_reason'),
                     history_ctx.get('summary', ''),
                     _json.dumps(summary.get('skipped', [])))
                )
        except Exception:
            pass

    return summary


# ── AI background worker ───────────────────────────────────────────────────────
_AI_INTERVAL = 30   # seconds between scans

def _ai_worker():
    """Daemon thread: scan all AI portfolios every _AI_INTERVAL seconds."""
    _time.sleep(10)   # let app finish startup
    while True:
        try:
            with _get_db() as conn:
                rows = conn.execute(
                    'SELECT id FROM portfolios WHERE ai_controlled=1'
                ).fetchall()
            for row in rows:
                try:
                    result = _ai_run_portfolio(row['id'])
                    if result['bought'] or result['sold'] or result['errors']:
                        print(f'[AI] pid={row["id"]} scanned={result["scanned"]} '
                              f'bought={[b["symbol"] for b in result["bought"]]} '
                              f'sold={[s["symbol"] for s in result["sold"]]} '
                              f'errors={result["errors"][:3]}')
                    else:
                        print(f'[AI] pid={row["id"]} scanned={result["scanned"]} — no trades')
                except Exception as e:
                    print(f'[AI] portfolio {row["id"]} error: {e}')
        except Exception as e:
            print(f'[AI] worker error: {e}')
        _time.sleep(_AI_INTERVAL)

threading.Thread(target=_ai_worker, daemon=True, name='ai-trader').start()


# ── Price projection ──────────────────────────────────────────────────────────
_proj_cache: dict = {}
_PROJ_TTL = 60  # seconds — matches frontend poll interval


def _compute_indicators(symbol: str, force: bool = False) -> dict:
    """Compute all technical indicators for a symbol. Returns indicator dict."""
    now = _time.time()
    if not force and symbol in _proj_cache:
        payload, ts = _proj_cache[symbol]
        if now - ts < _PROJ_TTL:
            return payload

    import yfinance as yf

    hist = yf.Ticker(symbol).history(period='120d')
    if hist.empty or len(hist) < 20:
        raise ValueError(f'Insufficient data for {symbol}')

    closes  = list(hist['Close'].dropna())
    highs   = list(hist['High'].dropna())
    lows    = list(hist['Low'].dropna())
    volumes = list(hist['Volume'].dropna())
    times   = [int(ts.timestamp()) for ts in hist.index]

    n = min(len(closes), len(highs), len(lows), len(volumes), len(times))
    closes  = closes[-n:]; highs   = highs[-n:]
    lows    = lows[-n:];   volumes = volumes[-n:]
    times   = times[-n:]

    # ── SMA20 / SMA50 ──
    sma20 = [{'time': times[i], 'value': round(sum(closes[i-19:i+1]) / 20, 4)} for i in range(19, n)]
    sma50 = ([{'time': times[i], 'value': round(sum(closes[i-49:i+1]) / 50, 4)} for i in range(49, n)]
             if n >= 50 else [])

    # ── Linear regression (slope/intercept for indicators) ──
    last20_y  = closes[-20:]
    x_mean    = 9.5
    y_mean    = sum(last20_y) / 20
    num       = sum((i - x_mean) * (last20_y[i] - y_mean) for i in range(20))
    denom     = sum((i - x_mean) ** 2 for i in range(20))
    slope     = num / denom if denom else 0
    intercept = y_mean - slope * x_mean

    # ── RSI (14-period) ──
    gains  = [max(closes[i] - closes[i-1], 0) for i in range(1, n)]
    losses = [max(closes[i-1] - closes[i], 0) for i in range(1, n)]
    rsi_series = []
    for i in range(13, len(gains)):
        ag = sum(gains[i-13:i+1]) / 14
        al = sum(losses[i-13:i+1]) / 14
        rsi_series.append({'time': times[i+1], 'value': round(100 - (100 / (1 + ag / al)) if al else 100.0, 2)})
    avg_g = sum(gains[-14:]) / 14
    avg_l = sum(losses[-14:]) / 14
    rsi   = round(100 - (100 / (1 + avg_g / avg_l)) if avg_l else 100.0, 2)
    rsi_signal = 'overbought' if rsi >= 70 else 'oversold' if rsi <= 30 else 'neutral'

    # ── MACD (12, 26, 9) ──
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_raw   = [ema12[i] - ema26[i] for i in range(n)]
    macd_vals  = macd_raw[25:]
    macd_times = times[25:]
    sig_vals   = _ema(macd_vals, 9)
    macd_out = [{'time': macd_times[i], 'value': round(macd_vals[i], 4)} for i in range(len(macd_vals))]
    sig_out  = [{'time': macd_times[8+i], 'value': round(sig_vals[8+i], 4)} for i in range(len(sig_vals)-8)]
    hist_out = [
        {'time': macd_times[8+i],
         'value': round(macd_vals[8+i] - sig_vals[8+i], 4),
         'color': '#26d97f66' if (macd_vals[8+i] - sig_vals[8+i]) >= 0 else '#ff4d4d66'}
        for i in range(len(sig_vals) - 8)
    ]
    last_m = macd_vals[-1];  last_s = sig_vals[-1]
    prev_m = macd_vals[-2] if len(macd_vals) > 1 else last_m
    prev_s = sig_vals[-2]  if len(sig_vals)  > 1 else last_s
    curr_h = last_m - last_s;  prev_h = prev_m - prev_s
    if   curr_h > 0 and prev_h <= 0: macd_cross = 'bullish_cross'
    elif curr_h < 0 and prev_h >= 0: macd_cross = 'bearish_cross'
    elif curr_h > 0:                 macd_cross = 'bullish'
    else:                            macd_cross = 'bearish'

    # ── Bollinger Bands (20, 2σ) ──
    bb_upper, bb_lower, bb_mid = [], [], []
    for i in range(19, n):
        w    = closes[i-19:i+1]
        mean = sum(w) / 20
        std  = (sum((c - mean)**2 for c in w) / 20) ** 0.5
        bb_upper.append({'time': times[i], 'value': round(mean + 2*std, 4)})
        bb_lower.append({'time': times[i], 'value': round(mean - 2*std, 4)})
        bb_mid.append(  {'time': times[i], 'value': round(mean,         4)})
    last_c = closes[-1]
    bb_u   = bb_upper[-1]['value'] if bb_upper else None
    bb_l   = bb_lower[-1]['value'] if bb_lower else None
    bb_m   = bb_mid[-1]['value']   if bb_mid   else None
    if bb_u and bb_l:
        bw = bb_u - bb_l
        if   bw < last_c * 0.03:     bb_pos = 'squeeze'
        elif last_c >= bb_u * 0.995: bb_pos = 'overbought'
        elif last_c <= bb_l * 1.005: bb_pos = 'oversold'
        elif last_c > bb_m:          bb_pos = 'upper_half'
        else:                        bb_pos = 'lower_half'
    else:
        bb_pos = 'unknown'

    # ── Stochastic (14, 3) ──
    stoch_k_arr = []
    for i in range(13, n):
        ph = max(highs[i-13:i+1]);  pl = min(lows[i-13:i+1])
        k  = ((closes[i] - pl) / (ph - pl) * 100) if (ph - pl) > 0 else 50.0
        stoch_k_arr.append({'time': times[i], 'value': round(k, 2)})
    k_raw = [p['value'] for p in stoch_k_arr]
    stoch_d_arr = [{'time': stoch_k_arr[i]['time'], 'value': round(sum(k_raw[i-2:i+1]) / 3, 2)}
                   for i in range(2, len(k_raw))]
    last_k = k_raw[-1] if k_raw else 50.0
    last_d = stoch_d_arr[-1]['value'] if stoch_d_arr else 50.0
    stoch_signal = 'overbought' if last_k >= 80 else 'oversold' if last_k <= 20 else 'neutral'

    # ── ATR (14) ──
    tr_vals = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
               for i in range(1, n)]
    atr     = round(sum(tr_vals[-14:]) / 14, 4) if len(tr_vals) >= 14 else None
    atr_pct = round(atr / last_c * 100, 2)       if atr and last_c   else None

    # Monte Carlo projection (300 paths, 10-day horizon)
    _price = closes[-1] if closes[-1] > 0 else 1.0
    daily_vol = (atr / _price) if (atr and _price > 0) else 0.01
    drift = slope / _price if _price > 0 else 0
    _n_paths = 300
    _horizon = 10
    _all_paths = []
    for _ in range(_n_paths):
        _path = [_price]
        for _d in range(_horizon):
            _shock = random.gauss(0, daily_vol)
            _path.append(_path[-1] * (1 + drift + _shock))
        _all_paths.append(_path[1:])

    def _pct(lst, p):
        s = sorted(lst)
        k = (len(s)-1) * p / 100
        f, c = int(k), min(int(k)+1, len(s)-1)
        return s[f] + (s[c]-s[f])*(k-f)

    _bull_path, _base_path, _bear_path = [], [], []
    _conf_upper, _conf_lower = [], []
    for _day_vals in zip(*_all_paths):
        _dv = list(_day_vals)
        _bull_path.append(round(_pct(_dv, 75), 4))
        _base_path.append(round(_pct(_dv, 50), 4))
        _bear_path.append(round(_pct(_dv, 25), 4))
        _conf_upper.append(round(_pct(_dv, 84), 4))
        _conf_lower.append(round(_pct(_dv, 16), 4))

    prob_up = sum(1 for _p in _all_paths if _p[-1] > _price) / _n_paths
    _day_sec = 86400
    _lt = times[-1]
    bull_proj = [{'time': _lt + (i+1)*_day_sec, 'value': v} for i, v in enumerate(_bull_path)]
    base_proj = [{'time': _lt + (i+1)*_day_sec, 'value': v} for i, v in enumerate(_base_path)]
    bear_proj = [{'time': _lt + (i+1)*_day_sec, 'value': v} for i, v in enumerate(_bear_path)]
    conf_upper_proj = [{'time': _lt + (i+1)*_day_sec, 'value': v} for i, v in enumerate(_conf_upper)]
    conf_lower_proj = [{'time': _lt + (i+1)*_day_sec, 'value': v} for i, v in enumerate(_conf_lower)]
    projection = base_proj  # backward compat

    _bull_chg = round((_bull_path[-1]/_price-1)*100, 2) if _price else 0
    _base_chg = round((_base_path[-1]/_price-1)*100, 2) if _price else 0
    _bear_chg = round((_bear_path[-1]/_price-1)*100, 2) if _price else 0
    scenarios_proj = {
        'bull': {'path': bull_proj, 'label': f'Bullish ({_bull_chg:+.1f}%)', 'prob': round(prob_up, 2)},
        'base': {'path': base_proj, 'label': f'Neutral ({_base_chg:+.1f}%)', 'prob': round(1 - abs(prob_up-0.5)*2, 2)},
        'bear': {'path': bear_proj, 'label': f'Bearish ({_bear_chg:+.1f}%)', 'prob': round(1-prob_up, 2)},
    }
    confidence_band = {'upper': conf_upper_proj, 'lower': conf_lower_proj}

    # ── VWAP (20-day rolling) ──
    vwap_arr = []
    for i in range(19, n):
        tp  = [(highs[j] + lows[j] + closes[j]) / 3 for j in range(i-19, i+1)]
        vol = volumes[i-19:i+1]
        tv  = sum(vol)
        if tv > 0:
            vwap_arr.append({'time': times[i], 'value': round(sum(p*v for p,v in zip(tp, vol)) / tv, 4)})
    last_vwap   = vwap_arr[-1]['value'] if vwap_arr else None
    if last_vwap is None:
        vwap_signal = ''       # no volume data (forex) — treat as neutral
    elif last_c > last_vwap:
        vwap_signal = 'above'
    else:
        vwap_signal = 'below'

    # ── Volume ──
    last_vol  = volumes[-1] if volumes else 0
    avg_vol   = sum(volumes[-20:]) / min(20, len(volumes)) if volumes else 0
    vol_ratio = round(last_vol / avg_vol, 2) if avg_vol > 0 else 1.0
    price_chg = last_c - closes[-2] if n >= 2 else 0
    if   vol_ratio >= 1.5: vol_signal = 'high_up' if price_chg > 0 else 'high_down'
    elif vol_ratio <= 0.5: vol_signal = 'low'
    else:                  vol_signal = 'normal'

    # ── Support / Resistance ──
    sorted_c   = sorted(closes[-min(60, n):])
    support    = round(sorted_c[int(len(sorted_c) * 0.10)], 2)
    resistance = round(sorted_c[int(len(sorted_c) * 0.90)], 2)

    trend = 'up' if slope > 0.05 else 'down' if slope < -0.05 else 'sideways'

    # Market regime detection
    def _adx(h_list, l_list, c_list, period=14):
        if len(c_list) < period + 1:
            return 20.0
        tr_list, pdm_list, ndm_list = [], [], []
        for i in range(1, len(c_list)):
            h, l, pc = h_list[i], l_list[i], c_list[i-1]
            tr_list.append(max(h-l, abs(h-pc), abs(l-pc)))
            pdm_list.append(max(h_list[i]-h_list[i-1], 0))
            ndm_list.append(max(l_list[i-1]-l_list[i], 0))
        def _wilders(lst, p):
            r = [sum(lst[:p])]
            for v in lst[p:]:
                r.append(r[-1] - r[-1]/p + v)
            return r
        _atr14 = _wilders(tr_list, period)
        _pdi = [100*p/a if a else 0 for p, a in zip(_wilders(pdm_list, period), _atr14)]
        _ndi = [100*n/a if a else 0 for n, a in zip(_wilders(ndm_list, period), _atr14)]
        _dx = [100*abs(p-n)/(p+n) if (p+n) else 0 for p, n in zip(_pdi, _ndi)]
        return round(sum(_dx[-period:]) / period, 1) if len(_dx) >= period else 20.0

    adx_val = _adx(highs, lows, closes)

    # BB squeeze detection using bb_widths history
    _bb_widths = []
    for _i in range(20, min(len(closes), 80)):
        _w = closes[_i-20:_i]
        _m = sum(_w)/20
        _s = (sum((x-_m)**2 for x in _w)/20)**0.5
        _bb_widths.append((4*_s)/_m if _m else 0)
    # Use mean and std from BB loop (last iteration values)
    _current_bb_w = (4*std/mean) if mean else 0
    _bb_threshold = sorted(_bb_widths)[int(len(_bb_widths)*0.2)] if len(_bb_widths) >= 5 else 0.03
    _consolidating = _current_bb_w < _bb_threshold
    _high_vol = (atr / closes[-1] * 100) > 4.0 if closes[-1] else False

    if adx_val > 25 and slope > 0.02:
        regime = 'trending_up'
    elif adx_val > 25 and slope < -0.02:
        regime = 'trending_down'
    elif _consolidating:
        regime = 'consolidating'
    elif _high_vol:
        regime = 'high_volatility'
    else:
        regime = 'neutral'

    # Multi-timeframe analysis
    def _rsi_quick(c, p=14):
        if len(c) < p+1: return 50.0
        gains = [max(c[i]-c[i-1], 0) for i in range(1, len(c))]
        losses = [max(c[i-1]-c[i], 0) for i in range(1, len(c))]
        ag = sum(gains[-p:])/p; al = sum(losses[-p:])/p
        return round(100 - 100/(1+ag/al), 1) if al else 100.0

    # 1D: use existing data
    _d_trend = 'up' if slope > 0.02 else ('down' if slope < -0.02 else 'sideways')
    mtf_1d = {'rsi': round(rsi, 1), 'trend': _d_trend, 'bb': bb_pos}

    # 1W: weekly bars
    try:
        import yfinance as yf
        _df_w = yf.download(symbol, period='52wk', interval='1wk', progress=False, auto_adjust=True)
        if isinstance(_df_w.columns, type(_df_w.columns)) and hasattr(_df_w.columns, 'levels'):
            _df_w.columns = _df_w.columns.droplevel(1)
        if len(_df_w) >= 14:
            _wc = _df_w['Close'].values.tolist()
            _w_rsi = _rsi_quick(_wc)
            _wm5 = sum(_wc[-5:])/5 if len(_wc)>=5 else _wc[-1]
            _wm10 = sum(_wc[-10:])/10 if len(_wc)>=10 else _wc[-1]
            _w_trend = 'up' if _wm5 > _wm10 else 'down'
            mtf_1w = {'rsi': _w_rsi, 'trend': _w_trend}
        else:
            mtf_1w = {'rsi': 50, 'trend': 'sideways'}
    except Exception:
        mtf_1w = {'rsi': 50, 'trend': 'sideways'}

    # 1H: hourly bars
    try:
        _df_h = yf.download(symbol, period='5d', interval='1h', progress=False, auto_adjust=True)
        if isinstance(_df_h.columns, type(_df_h.columns)) and hasattr(_df_h.columns, 'levels'):
            _df_h.columns = _df_h.columns.droplevel(1)
        if len(_df_h) >= 14:
            _hc = _df_h['Close'].values.tolist()
            _h_rsi = _rsi_quick(_hc)
            _hm5 = sum(_hc[-5:])/5 if len(_hc)>=5 else _hc[-1]
            _hm10 = sum(_hc[-10:])/10 if len(_hc)>=10 else _hc[-1]
            _h_trend = 'up' if _hm5 > _hm10 else 'down'
            mtf_1h = {'rsi': round(_h_rsi,1), 'trend': _h_trend}
        else:
            mtf_1h = {'rsi': 50, 'trend': 'sideways'}
    except Exception:
        mtf_1h = {'rsi': 50, 'trend': 'sideways'}

    _bull_count = sum([
        1 if mtf_1h.get('trend') == 'up' else 0,
        1 if mtf_1d.get('trend') == 'up' else 0,
        1 if mtf_1w.get('trend') == 'up' else 0,
    ])
    _bear_count = sum([
        1 if mtf_1h.get('trend') == 'down' else 0,
        1 if mtf_1d.get('trend') == 'down' else 0,
        1 if mtf_1w.get('trend') == 'down' else 0,
    ])
    _alignment = 'bullish' if _bull_count >= 2 else ('bearish' if _bear_count >= 2 else 'mixed')
    mtf = {'1H': mtf_1h, '1D': mtf_1d, '1W': mtf_1w, 'alignment': _alignment, 'bull_count': _bull_count, 'bear_count': _bear_count}

    payload = {
        'last_price':  round(last_c, 4),
        'sma20':       sma20,       'sma50':       sma50,
        'projection':  projection,  'support':     support,
        'resistance':  resistance,  'trend':       trend,
        'slope':       round(slope, 4),
        'rsi':         rsi,         'rsi_signal':  rsi_signal,
        'rsi_series':  rsi_series,
        'macd':        macd_out,    'macd_signal': sig_out,
        'macd_hist':   hist_out,    'macd_value':  round(last_m, 4),
        'macd_signal_value': round(last_s, 4),
        'macd_cross':  macd_cross,
        'bb_upper':    bb_upper,    'bb_lower':    bb_lower,
        'bb_middle':   bb_mid,      'bb_position': bb_pos,
        'bb_upper_val': bb_u,       'bb_lower_val': bb_l,
        'stoch_k':     stoch_k_arr, 'stoch_d':     stoch_d_arr,
        'stoch_k_val': round(last_k, 2), 'stoch_d_val': round(last_d, 2),
        'stoch_signal': stoch_signal,
        'atr':         atr,         'atr_pct':     atr_pct,
        'vwap':        vwap_arr,    'vwap_value':  last_vwap,
        'vwap_signal': vwap_signal,
        'avg_volume':  round(avg_vol), 'last_volume': round(last_vol),
        'volume_ratio': vol_ratio,     'volume_signal': vol_signal,
        'price':            round(last_c, 4),
        'scenarios':        scenarios_proj,
        'confidence_band':  confidence_band,
        'prob_up':          round(prob_up, 2),
        'bull_proj':        bull_proj,
        'base_proj':        base_proj,
        'bear_proj':        bear_proj,
        'regime':           regime,
        'adx':              adx_val,
        'mtf':              mtf,
    }
    _proj_cache[symbol] = (payload, _time.time())
    return payload


@app.route('/api/projection/<symbol>')
def get_projection(symbol):
    symbol = symbol.upper()
    force  = request.args.get('force', '') == '1'
    try:
        return jsonify(_compute_indicators(symbol, force=force))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/risk/<symbol>')
def api_risk(symbol):
    portfolio_id = request.args.get('portfolio_id', 1, type=int)
    data = _compute_indicators(symbol)
    if not data:
        return jsonify({'error': 'no data'}), 400
    price = data.get('price', data.get('last_price', 0))
    atr = data.get('atr', 0) or 0
    atr_pct = data.get('atr_pct', 1.0) or 1.0
    support = data.get('support', price * 0.95)
    with _get_db() as conn:
        state = conn.execute('SELECT cash, last_equity FROM sim_state WHERE portfolio_id=?', (portfolio_id,)).fetchone()
    equity = (state['last_equity'] or 10000) if state else 10000
    cash = (state['cash'] or 10000) if state else 10000
    max_dd_pct = round(atr_pct * 2, 2)
    daily_vol = atr / price if price else 0.01
    var_95 = round(price * daily_vol * 1.645, 2)
    ideal_stop = price - 1.5 * atr
    stop_to_support = abs(ideal_stop - support)
    stop_quality = 'tight' if stop_to_support < atr * 0.5 else ('adequate' if stop_to_support < atr * 1.5 else 'loose')
    risk_per_share = 1.5 * atr
    risk_budget = equity * 0.02
    suggested_shares = int(risk_budget / risk_per_share) if risk_per_share > 0 else 0
    suggested_shares = min(suggested_shares, int(cash * 0.15 / price) if price else 0)
    target = price + 2.5 * atr
    stop = price - 1.5 * atr
    rr = round((target - price) / (price - stop), 2) if (price - stop) > 0 else 0
    grade_score = 0
    if rr >= 2.5: grade_score += 2
    elif rr >= 1.5: grade_score += 1
    if max_dd_pct < 3: grade_score += 2
    elif max_dd_pct < 6: grade_score += 1
    if stop_quality == 'adequate': grade_score += 1
    elif stop_quality == 'tight': grade_score -= 1
    if atr_pct < 2: grade_score += 1
    grade_map = {6:'A', 5:'A', 4:'B+', 3:'B', 2:'C', 1:'D', 0:'F'}
    risk_grade = grade_map.get(min(max(grade_score,0), 6), 'F')
    return jsonify({
        'risk_grade': risk_grade,
        'max_drawdown_pct': max_dd_pct,
        'var_95': var_95,
        'stop_quality': stop_quality,
        'suggested_shares': suggested_shares,
        'rr_ratio': rr,
        'invalidation_price': round(price - 2.0 * atr, 2),
        'atr_pct': round(atr_pct, 2),
        'regime': data.get('regime', 'neutral'),
    })

# ── Company info ─────────────────────────────────────────────────────────────
@app.route('/api/company/<symbol>')
def get_company(symbol):
    symbol = symbol.upper()
    if not _ticker_db_loaded:
        threading.Thread(target=_load_ticker_db, daemon=True).start()
    search_list = _ticker_db if _ticker_db_loaded else _STATIC_ASSETS_DICTS
    for a in search_list:
        if a['symbol'] == symbol:
            return jsonify({'symbol': symbol, 'name': a['name'], 'exchange': a.get('exchange', '')})
    # Fallback: try yfinance
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info
        name = info.get('longName') or info.get('shortName') or symbol
        exchange = info.get('exchange', '')
        return jsonify({'symbol': symbol, 'name': name, 'exchange': exchange})
    except Exception:
        pass
    return jsonify({'symbol': symbol, 'name': symbol, 'exchange': ''})

# ── Serve built React frontend ────────────────────────────────────────────────
def _poll_worker():
    """Emit quotes every 25 s — uses Finnhub REST when key is set, yfinance otherwise."""
    while True:
        _time.sleep(25)
        syms = list(_subscribed_symbols | set(_watchlist))
        for sym in syms:
            try:
                _quote_cache.pop(sym, None)  # bypass cache for fresh data
                q = _quote_finnhub(sym) if FINNHUB_KEYS_SET else _quote_yfinance(sym)
                socketio.emit('quote', {
                    'symbol':  sym,
                    'bid':     q['bid'],
                    'ask':     q.get('ask', q['bid']),
                    'spread':  q.get('spread', 0),
                    'delayed': not FINNHUB_KEYS_SET,
                })
            except Exception:
                pass

# ── Analysis / Rankings / Market-state endpoints ──────────────────────────────
# Must be registered BEFORE the serve_frontend catch-all.

@app.route('/api/analysis/<symbol>', methods=['GET'])
def get_analysis(symbol):
    """Full traceable analysis for a symbol — breakdown, uncertainty, market state, summary."""
    try:
        data = _compute_indicators_fast(symbol.upper())
        data['symbol'] = symbol.upper()
        detail = _ai_score_detailed(data)

        # Apply strategy engine
        strategy_info = {}
        try:
            import strategy_engine as _se
            se = _se.get_engine()
            strat = se.score(symbol.upper(), data, detail['score'], detail.get('uncertainty', 0.3))
            detail['score'] = strat['score']
            strategy_info = {
                'strategy':   strat['strategy'],
                'confidence': strat['confidence'],
                'rationale':  strat['rationale'],
            }
        except Exception:
            pass

        return jsonify({
            'symbol':       symbol.upper(),
            'price':        data.get('last_price'),
            'score':        detail['score'],
            'market_state': detail['market_state'],
            'uncertainty':  detail['uncertainty'],
            'breakdown':    detail['breakdown'],
            'summary':      detail['summary'],
            'what_changed': detail['what_changed'],
            'weights_used': detail['weights_used'],
            'strategy':     strategy_info,
            'indicators': {
                'rsi':          data.get('rsi'),
                'macd_cross':   data.get('macd_cross'),
                'macd_value':   data.get('macd_value'),
                'stoch_k':      data.get('stoch_k_val'),
                'bb_position':  data.get('bb_position'),
                'vwap_signal':  data.get('vwap_signal'),
                'volume_signal':data.get('volume_signal'),
                'volume_ratio': data.get('volume_ratio'),
                'trend':        data.get('trend'),
                'atr':          data.get('atr'),
                'atr_pct':      data.get('atr_pct'),
                'ema50':        data.get('ema50'),
                'adx':          data.get('adx'),
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/analysis/<symbol>/brief')
def analysis_brief(symbol):
    """Compiled Trade Brief: regime, MTF, structure, projection, setup guide."""
    sym = symbol.upper()
    try:
        data   = _compute_indicators_fast(sym)
        data['symbol'] = sym
        detail = _ai_score_detailed(data)

        price     = float(data.get('last_price') or 0)
        atr       = float(data.get('atr') or price * 0.02)
        atr_pct   = float(data.get('atr_pct') or 2.0)
        regime    = detail['market_state']
        mtf       = detail.get('mtf_bias', {})
        score     = detail['score']

        # Asset class
        if sym.endswith('-USD'):   asset_class = 'crypto'
        elif sym.endswith('=X'):   asset_class = 'forex'
        elif sym.endswith('=F'):   asset_class = 'futures'
        else:                      asset_class = 'equity'

        # Projected range (±1 ATR for 24h, ±0.5 ATR for intraday)
        proj_high = round(price + atr, 4)
        proj_low  = round(price - atr, 4)

        # Stop suggestion based on current regime
        stop_mult = 2.5 if regime in ('panic', 'news_driven', 'euphoric') else 1.5
        long_stop  = round(price - stop_mult * atr, 4)
        short_stop = round(price + stop_mult * atr, 4)

        # Structure snapshot if engine available
        structure = {}
        try:
            import structure_engine as se
            structure = se.snapshot(sym)
        except Exception:
            pass

        # Regime descriptions
        regime_desc = {
            'trending_up':       'Strong uptrend — momentum indicators dominant, follow the trend.',
            'trending_down':     'Strong downtrend — caution on longs, shorts favored.',
            'breakout':          'Breakout pattern — price clearing resistance on high volume.',
            'accumulation':      'Accumulation — smart money likely building positions quietly.',
            'ranging':           'Ranging market — momentum strategies less effective, mean reversion favored.',
            'panic':             'Panic selling — signals unreliable, extreme caution advised.',
            'oversold_extreme':  'Extreme oversold — snap-back likely but timing uncertain.',
            'overbought_extreme':'Extreme overbought — pullback risk elevated.',
            'mild_uptrend':      'Mild uptrend — moderate bullish bias, confirmation needed.',
            'mild_downtrend':    'Mild downtrend — moderate bearish bias.',
            'euphoric':          'Euphoric extension — parabolic move, mean-reversion risk high.',
            'distribution':      'Distribution — supply overwhelming demand at current levels.',
            'news_driven':       'News-driven volatility — wait for stabilization before entering.',
            'neutral':           'Neutral conditions — no clear edge, wait for setup.',
        }.get(regime, 'Conditions unclear.')

        # Asset-class setup guides
        setup_guides = {
            'crypto': {
                'title': 'Crypto Trading Guide',
                'tips': [
                    'Crypto trades 24/7 — highest volume during US market hours (9AM–5PM ET) and Asia open (8PM–12AM ET)',
                    'Watch BTC as the lead indicator — most altcoins follow BTC direction with a lag',
                    'Crypto ATR is typically 3–8× higher than equities — size positions accordingly',
                    'Avoid entries during overnight weekend hours (Fri 10PM – Sun 8PM ET) — thin liquidity',
                    f'Current ATR: {atr_pct:.1f}% daily — position sizing should reflect this volatility',
                ],
                'best_sessions': 'US Open (9AM–12PM ET), Asia Open (8PM–11PM ET)',
                'avoid': 'Late weekend nights, major macro announcements without a clear thesis',
            },
            'forex': {
                'title': 'Forex Trading Guide',
                'tips': [
                    'Highest liquidity: London/New York overlap (8AM–12PM ET) — best spreads, clearest trends',
                    'Asian session (7PM–2AM ET) — low volatility, good for range strategies on JPY pairs',
                    'Avoid trading 30 min before/after major data releases (CPI, NFP, FOMC)',
                    'Forex moves in pips — 1% daily moves are significant; size positions conservatively',
                    f'Current ATR: {atr_pct:.1f}% — {"elevated, wider stops needed" if atr_pct > 0.8 else "normal range"}',
                ],
                'best_sessions': 'London/NY overlap (8AM–12PM ET)',
                'avoid': 'Asian session for trend trades, major economic calendar events',
            },
            'futures': {
                'title': 'Futures Trading Guide',
                'tips': [
                    'Index futures (ES, NQ) mirror the stock market but trade nearly 24/7 Sun–Fri',
                    'Highest volume: regular trading hours (9:30AM–4PM ET) and Globex pre-market',
                    'Futures use leverage — one ES contract controls ~$250k notional; size carefully',
                    'Watch for roll dates — contracts expire quarterly (Mar/Jun/Sep/Dec)',
                    'Economic data (CPI, NFP, FOMC) causes sharp moves — reduce exposure beforehand',
                ],
                'best_sessions': 'RTH (9:30AM–4PM ET), pre-market 8–9:30AM ET for gap setups',
                'avoid': 'Overnight Sunday open (thin), contract expiration week (gamma risk)',
            },
            'equity': {
                'title': 'Stock Trading Guide',
                'tips': [
                    'Highest volatility: first 30 min (9:30–10AM ET) and last 30 min (3:30–4PM ET)',
                    'Avoid chasing earnings plays without an options hedge — IV crush is real',
                    'Check float and average volume — thin stocks can gap violently on news',
                    'SPY/QQQ direction sets the tone for most stocks — check market breadth first',
                    f'Current ATR: ${atr:.2f} ({atr_pct:.1f}%) — {"high volatility day" if atr_pct > 3 else "normal session"}',
                ],
                'best_sessions': 'Power hour open (9:30–10:30AM ET), close (3–4PM ET)',
                'avoid': 'Mid-day chop (12–2PM ET), pre-earnings without a clear catalyst edge',
            },
        }

        return jsonify({
            'symbol':       sym,
            'price':        price,
            'asset_class':  asset_class,
            'score':        round(score, 2),
            'regime':       regime,
            'regime_desc':  regime_desc,
            'mtf_bias':     mtf,
            'atr':          round(atr, 4),
            'atr_pct':      round(atr_pct, 2),
            'proj_high':    proj_high,
            'proj_low':     proj_low,
            'long_stop':    long_stop,
            'short_stop':   short_stop,
            'nearest_support':    structure.get('nearest_support'),
            'nearest_resistance': structure.get('nearest_resistance'),
            'swing_bias':         structure.get('swing_bias', 'undefined'),
            'in_consolidation':   structure.get('in_consolidation', False),
            'setup_guide':  setup_guides.get(asset_class, {}),
            'summary':      detail['summary'],
            'breakdown':    detail['breakdown'],
            'uncertainty':  detail['uncertainty'],
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/rankings', methods=['GET'])
def get_rankings():
    """Rank all watchlist + held symbols by AI score.
    cached_only=1 skips network fetches and returns only already-cached symbols."""
    portfolio_id = int(request.args.get('portfolio_id', 1))
    cached_only  = request.args.get('cached_only', '0') == '1'
    try:
        # portfolio_id=0 is the real Alpaca account; its watchlist lives under pid=1
        watchlist_pid = 1 if portfolio_id == 0 else portfolio_id
        with _get_db() as conn:
            watch_syms = [r['symbol'] for r in conn.execute(
                'SELECT symbol FROM watchlist_items WHERE portfolio_id=?', (watchlist_pid,)
            ).fetchall()]
            held_syms = [r['symbol'] for r in conn.execute(
                'SELECT symbol FROM sim_positions WHERE portfolio_id=? AND shares>0', (portfolio_id,)
            ).fetchall()]
        # For real account, also include Alpaca positions as "held"
        if portfolio_id == 0:
            try:
                real_pos = _alpaca_positions()
                held_syms = list(dict.fromkeys(held_syms + [p['symbol'] for p in real_pos]))
            except Exception:
                pass
        symbols = list(dict.fromkeys(watch_syms + held_syms))

        now = _time.time()
        results = []
        uncached = []
        for sym in symbols:
            if sym in _proj_cache:
                payload, ts = _proj_cache[sym]
                if now - ts < _PROJ_TTL:
                    try:
                        data = dict(payload)
                        data['symbol'] = sym
                        detail = _ai_score_detailed(data)
                        results.append({
                            'symbol':       sym,
                            'score':        detail['score'],
                            'market_state': detail['market_state'],
                            'uncertainty':  detail['uncertainty'],
                            'summary':      detail['summary'],
                            'price':        round(data.get('last_price', 0), 2),
                            'rsi':          round(data.get('rsi', 50), 1),
                            'trend':        data.get('trend', ''),
                            'atr_pct':      data.get('atr_pct', 0),
                            'held':         sym in held_syms,
                            'what_changed': detail['what_changed'],
                            'cached':       True,
                        })
                    except Exception:
                        uncached.append(sym)
                else:
                    uncached.append(sym)
            else:
                uncached.append(sym)

        if not cached_only:
            for sym in uncached:
                try:
                    data = _compute_indicators_fast(sym)
                    data['symbol'] = sym
                    detail = _ai_score_detailed(data)
                    results.append({
                        'symbol':       sym,
                        'score':        detail['score'],
                        'market_state': detail['market_state'],
                        'uncertainty':  detail['uncertainty'],
                        'summary':      detail['summary'],
                        'price':        round(data.get('last_price', 0), 2),
                        'rsi':          round(data.get('rsi', 50), 1),
                        'trend':        data.get('trend', ''),
                        'atr_pct':      data.get('atr_pct', 0),
                        'held':         sym in held_syms,
                        'what_changed': detail['what_changed'],
                        'cached':       False,
                    })
                except Exception:
                    pass

        results.sort(key=lambda x: x['score'], reverse=True)
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/market-state', methods=['GET'])
def get_market_state():
    """Overall market conditions based on SPY/QQQ/VIX proxy signals."""
    try:
        spy = _compute_indicators_fast('SPY')
        spy['symbol'] = 'SPY'
        spy_detail = _ai_score_detailed(spy)

        qqq = _compute_indicators_fast('QQQ')
        qqq['symbol'] = 'QQQ'
        qqq_detail = _ai_score_detailed(qqq)

        # Aggregate market score
        avg_score = round((spy_detail['score'] + qqq_detail['score']) / 2, 2)
        # Dominant regime: pick whichever is more extreme
        spy_state = spy_detail['market_state']
        qqq_state = qqq_detail['market_state']
        priority_order = ['panic', 'breakout', 'overbought_extreme', 'oversold_extreme',
                          'trending_up', 'trending_down', 'accumulation', 'ranging',
                          'mild_uptrend', 'mild_downtrend', 'neutral']
        market_regime = spy_state
        for s in priority_order:
            if spy_state == s or qqq_state == s:
                market_regime = s
                break

        return jsonify({
            'market_score':  avg_score,
            'market_regime': market_regime,
            'spy': {'score': spy_detail['score'], 'state': spy_state,
                    'rsi': spy.get('rsi'), 'trend': spy.get('trend'),
                    'summary': spy_detail['summary']},
            'qqq': {'score': qqq_detail['score'], 'state': qqq_state,
                    'rsi': qqq.get('rsi'), 'trend': qqq.get('trend'),
                    'summary': qqq_detail['summary']},
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/debug/indicator_audit')
def indicator_audit():
    """Compare our indicator values against a second source to verify data integrity.
    Returns delta analysis — any indicator > 5% off is a red flag."""
    symbol = request.args.get('symbol', 'BTC-USD')
    try:
        # Source 1: our candle engine
        ce_data = _candle_engine.latest(symbol, '1m') if _candle_engine else None

        # Source 2: yfinance daily (different timeframe but sanity check)
        import yfinance as yf
        hist = yf.Ticker(symbol).history(period='30d', interval='1d')

        result = {'symbol': symbol, 'sources': {}, 'deltas': {}, 'status': 'ok'}

        if ce_data:
            result['sources']['candle_engine_1m'] = {
                'rsi': ce_data.get('rsi'),
                'macd': ce_data.get('macd_value'),
                'atr_pct': ce_data.get('atr_pct'),
                'trend': ce_data.get('trend'),
                'bars': _candle_engine.bars_available(symbol, '1m') if _candle_engine else 0,
            }

        if not hist.empty and len(hist) >= 14:
            from candle_engine import _compute_indicators
            from collections import deque
            from candle_engine import _OHLCV
            bars_d = deque(maxlen=120)
            for ts, row in hist.iterrows():
                bars_d.append(_OHLCV(
                    open=float(row.get('Open', 0)),
                    high=float(row.get('High', 0)),
                    low=float(row.get('Low', 0)),
                    close=float(row.get('Close', 0)),
                    volume=float(row.get('Volume', 0) or 0),
                    ts=ts.timestamp(),
                ))
            daily_ind = _compute_indicators(bars_d)
            result['sources']['yfinance_daily'] = {
                'rsi': daily_ind.get('rsi'),
                'macd': daily_ind.get('macd_value'),
                'atr_pct': daily_ind.get('atr_pct'),
                'trend': daily_ind.get('trend'),
                'bars': len(hist),
            }

        # Compare if both sources available
        s1 = result['sources'].get('candle_engine_1m', {})
        s2 = result['sources'].get('yfinance_daily', {})
        flags = []
        for key in ['rsi', 'atr_pct']:
            v1, v2 = s1.get(key), s2.get(key)
            if v1 and v2 and v2 != 0:
                delta = abs(v1 - v2) / abs(v2) * 100
                result['deltas'][key] = round(delta, 1)
                if delta > 30:  # allow large delta since 1m vs daily is expected to differ
                    flags.append(f'{key}: {delta:.0f}% delta (1m vs daily — expected)')

        result['flags'] = flags
        result['note'] = '1m candle engine vs daily yfinance — large deltas expected due to different timeframes'
        result['integrity'] = 'ok' if ce_data and ce_data.get('rsi') else 'no_candle_data'

        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Static frontend (catch-all — must be last) ────────────────────────────────

DIST_DIR = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'dist')

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_frontend(path):
    if path.startswith('api/') or path.startswith('socket.io/'):
        from flask import abort
        abort(404)
    full = os.path.join(DIST_DIR, path)
    if path and os.path.exists(full) and os.path.isfile(full):
        return send_from_directory(DIST_DIR, path)
    return send_from_directory(DIST_DIR, 'index.html')


if __name__ == '__main__':
    threading.Thread(target=_load_ticker_db, daemon=True).start()

    # ── Real-time streaming infrastructure ──────────────────────────────────────
    from event_bus import event_bus
    from stream_manager import StreamManager, CRYPTO_SYMBOLS
    from candle_engine import CandleEngine

    _stream_manager = StreamManager(event_bus)
    _stream_manager.start()

    # CandleEngine: tick → OHLCV + indicators server-side
    _candle_engine = CandleEngine(event_bus)
    _candle_engine.start()

    # Seed daily candles for MTF analysis (runs in background, ~30s)
    _seed_symbols = list(set(CRYPTO_SYMBOLS) | {'SPY', 'QQQ', 'AAPL', 'MSFT', 'NVDA', 'TSLA', 'META', 'GOOGL', 'AMZN', 'JPM'})

    # Seed intraday 1m bars FIRST so indicators are warmed up immediately
    _seed_1m_syms = [s for s in _seed_symbols if s.endswith('-USD') or not s.endswith('=F')]
    threading.Thread(target=_seed_intraday_candles, args=(_seed_1m_syms,), daemon=True).start()
    print(f'[TradeSimulator] Seeding intraday candles for {len(_seed_1m_syms)} symbols...')

    threading.Thread(target=_seed_daily_candles, args=(_seed_symbols,), daemon=True).start()
    print(f'[TradeSimulator] Seeding daily candles for {len(_seed_symbols)} symbols in background...')

    # ── Tier 3-5 module initialization ────────────────────────────────────────
    try:
        import breadth_engine as _breadth
        _breadth.init(event_bus=event_bus)
        print('[TradeSimulator] BreadthEngine started (31-stock basket, 5m poll).')
    except Exception as e:
        print(f'[TradeSimulator] BreadthEngine failed: {e}')

    try:
        import model_trainer as _mt
        _mt.start_nightly_training(db_path=DB_PATH, pid=1)
        print('[TradeSimulator] ModelTrainer nightly scheduler started.')
    except Exception as e:
        print(f'[TradeSimulator] ModelTrainer failed: {e}')

    try:
        import circuit_breakers as _cb
        _cb.init(DB_PATH)
        print('[TradeSimulator] CircuitBreakers initialized.')
    except Exception as e:
        print(f'[TradeSimulator] CircuitBreakers failed: {e}')

    try:
        import options_engine as _oe
        _oe.init(DB_PATH)
        print('[TradeSimulator] OptionsEngine initialized (Black-Scholes + Alpaca chain).')
    except Exception as e:
        print(f'[TradeSimulator] OptionsEngine failed: {e}')

    try:
        import options_strategy as _os
        _os.init(DB_PATH)
        print('[TradeSimulator] OptionsStrategyManager initialized.')
    except Exception as e:
        print(f'[TradeSimulator] OptionsStrategy failed: {e}')

    try:
        import rl_engine as _rl
        _rl.init(DB_PATH)
        print('[TradeSimulator] RLEngine initialized (Q-table strategy adaptation).')
    except Exception as e:
        print(f'[TradeSimulator] RLEngine failed: {e}')

    try:
        import order_flow as _of
        _of.init(event_bus=event_bus)
        print('[TradeSimulator] OrderFlowEngine started (bid/ask imbalance tracking).')
    except Exception as e:
        print(f'[TradeSimulator] OrderFlow failed: {e}')

    try:
        import macro_engine as _me
        _me.init()
        print('[TradeSimulator] MacroEngine started (cross-asset signals, 15m poll).')
    except Exception as e:
        print(f'[TradeSimulator] MacroEngine failed: {e}')

    try:
        import news_engine as _ne
        _ne.get_engine()   # pre-warm singleton
        print('[TradeSimulator] NewsEngine ready (Finnhub sentiment).')
    except Exception as e:
        print(f'[TradeSimulator] NewsEngine failed: {e}')

    # ── Structure Engine — market structure per symbol ─────────────────────────
    try:
        import structure_engine as _se_mod
        _structure_engine = _se_mod.init(event_bus)
        print('[TradeSimulator] StructureEngine started (swing detection, S/R, FVG, session levels).')
    except Exception as e:
        print(f'[TradeSimulator] StructureEngine failed to start: {e}')

    # ── Portfolio Analytics ────────────────────────────────────────────────────
    try:
        from portfolio_analytics import PortfolioAnalytics
        _portfolio_analytics = PortfolioAnalytics(_candle_engine)
        print('[TradeSimulator] PortfolioAnalytics initialized (sector, beta, correlation).')
    except Exception as e:
        print(f'[TradeSimulator] PortfolioAnalytics failed: {e}')

    # ── Performance Engine ─────────────────────────────────────────────────────
    try:
        import performance_engine as _pe_mod
        _perf_engine = _pe_mod.init_engine(DB_PATH)
        print('[TradeSimulator] PerformanceEngine initialized (regime stats, equity curve, decay).')
    except Exception as e:
        print(f'[TradeSimulator] PerformanceEngine failed: {e}')

    # Broadcast ticks and bars to connected browsers
    event_bus.subscribe('tick:*',    lambda ch, d: socketio.emit('quote', d))
    event_bus.subscribe('bar:*:1m',  lambda ch, d: socketio.emit('bar',   {'symbol': d['symbol'], 'bar': d}))

    # Phase 3: event-triggered AI scoring — score each symbol within 2s of its 1m bar close
    def _on_bar_for_ai(channel: str, bar: dict) -> None:
        symbol = bar.get('symbol', '')
        if not symbol or not bar.get('closed'):
            return
        try:
            data   = _compute_indicators_fast(symbol)
            _proj_cache[symbol] = (data, _time.time())
        except Exception:
            return
        # Event-triggered exit check: if this symbol is held by any AI portfolio,
        # check it for exit immediately (sub-2s reaction vs 30s timer)
        try:
            with _get_db() as conn:
                holders = conn.execute(
                    '''SELECT DISTINCT sp.portfolio_id
                       FROM sim_positions sp
                       JOIN portfolios p ON p.id = sp.portfolio_id
                       WHERE sp.symbol=? AND sp.shares!=0 AND p.ai_controlled=1''',
                    (symbol,)
                ).fetchall()
            for h in holders:
                _check_single_position_exit(h['portfolio_id'], symbol, data)
        except Exception:
            pass

    event_bus.subscribe('bar:*:1m', _on_bar_for_ai)

    # Coinbase — primary crypto source (no API key needed, US-accessible)
    try:
        from coinbase_ws import CoinbaseWS
        crypto_syms = list(CRYPTO_SYMBOLS)
        _coinbase = CoinbaseWS(crypto_syms, _stream_manager)
        _stream_manager.register_provider('coinbase', 'crypto')
        _coinbase.start()
        print(f'[TradeSimulator] Coinbase crypto stream starting ({len(crypto_syms)} symbols).')
    except Exception as e:
        print(f'[TradeSimulator] Coinbase stream failed: {e}')

    # Polygon — forex primary + crypto failover
    if POLYGON_KEYS_SET:
        try:
            from polygon_stream import start_stream as poly_start, activate_crypto_failover
            _stream_manager.register_provider('polygon', 'forex')
            _stream_manager.register_provider('polygon', 'crypto')
            threading.Thread(
                target=poly_start, args=(POLYGON_KEY, _stream_manager), daemon=True
            ).start()
            # When Coinbase dies, activate Polygon crypto failover
            def _on_failover(symbol, old_src, new_src):
                if old_src in ('binance', 'coinbase') and new_src == 'polygon':
                    activate_crypto_failover([symbol])
            _stream_manager.on_failover(_on_failover)
            print('[TradeSimulator] Polygon forex + crypto-failover stream starting.')
        except Exception as e:
            print(f'[TradeSimulator] Polygon stream failed: {e}')

    # Alpaca — equity primary (real-time IEX)
    if KEYS_SET:
        try:
            from alpaca_stream import start_stream as alp_start
            _stream_manager.register_provider('alpaca', 'equity')
            threading.Thread(
                target=alp_start, args=(API_KEY, SECRET_KEY, _stream_manager), daemon=True
            ).start()
            print('[TradeSimulator] Alpaca equity stream starting (iex feed).')
        except Exception as e:
            print(f'[TradeSimulator] Alpaca stream failed: {e}')

    # Finnhub — equity failover
    if FINNHUB_KEYS_SET:
        try:
            from finnhub_stream import start_stream as fh_start
            _stream_manager.register_provider('finnhub', 'equity')
            fh_start(FINNHUB_KEY, _stream_manager)
            print('[TradeSimulator] Finnhub equity-failover stream starting.')
        except Exception as e:
            print(f'[TradeSimulator] Finnhub stream failed: {e}')

    if not (KEYS_SET or POLYGON_KEYS_SET or FINNHUB_KEYS_SET):
        print('[TradeSimulator] No equity/forex keys — using yfinance polling (delayed).')

    # Poll worker fills gaps for non-streaming symbols and outside market hours
    threading.Thread(target=_poll_worker, daemon=True).start()

    if AV_KEYS_SET:
        print('[TradeSimulator] Alpha Vantage key configured — comprehensive symbol search enabled.')
    socketio.run(app, host='0.0.0.0', port=8765, debug=False)
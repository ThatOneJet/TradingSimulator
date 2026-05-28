import os, threading, sqlite3, time as _time, json as _json, csv, io, hashlib, random
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory
from flask_socketio import SocketIO
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

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

        # Seed default watchlist for portfolio 1
        for _sym in ('AAPL', 'TSLA', 'NVDA', 'SPY'):
            conn.execute('INSERT OR IGNORE INTO watchlist_items (portfolio_id, symbol) VALUES (1, ?)', (_sym,))

_init_db()

# in-memory watchlist
_watchlist: list[str] = ['AAPL', 'TSLA', 'NVDA', 'SPY']

# ── Price / quote cache ────────────────────────────────────────────────────────
_price_cache: dict[str, tuple[float, float]] = {}
_PRICE_TTL = 30
_quote_cache: dict[str, tuple[dict, float]] = {}
_QUOTE_TTL  = 60
_subscribed_symbols: set = set()

def _fetch_price_live(symbol: str) -> float:
    # Always use yfinance for simulation prices — no Alpaca dependency
    return _quote_yfinance(symbol)['bid']

def _get_current_price(symbol: str) -> float:
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

def _sim_buy(symbol: str, qty: float, price: float, portfolio_id: int = 1):
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
                'INSERT INTO sim_positions (symbol, shares, avg_cost, realized_pl, portfolio_id) VALUES (?,?,?,0,?)',
                (symbol, qty, price, portfolio_id)
            )

def _sim_sell(symbol: str, qty: float, price: float, portfolio_id: int = 1) -> float:
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
            'SELECT * FROM sim_positions WHERE shares > 0.0001 AND portfolio_id = ?',
            (portfolio_id,)
        ).fetchall()
    out = []
    for row in rows:
        price = _get_current_price(row['symbol'])
        qty   = row['shares']
        avg   = row['avg_cost']
        mv    = price * qty
        upl   = (price - avg) * qty
        out.append({
            'symbol':          row['symbol'],
            'qty':             qty,
            'avg_entry_price': avg,
            'current_price':   price,
            'market_value':    mv,
            'unrealized_pl':   upl,
            'unrealized_plpc': (upl / (avg * qty)) if avg and qty else 0,
            'side':            'long',
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
    return jsonify({'status': 'updated'})

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
    return jsonify([dict(r) for r in rows])

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
    pnl_day   = portfolio_value - state['last_equity']
    return jsonify({
        'equity':          portfolio_value,
        'cash':            state['cash'],
        'buying_power':    state['cash'],
        'portfolio_value': portfolio_value,
        'daytrade_count':  0,
        'pnl_day':         pnl_day,
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
        'realized_pl':      row['realized_pl'],
        'created_at':       row['created_at'],
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

        if side == 'buy':
            _sim_buy(symbol, qty, fill_price, pid)
        else:
            realized_pl = _sim_sell(symbol, qty, fill_price, pid)

        with _get_db() as conn:
            cur = conn.execute(
                'INSERT INTO sim_trades (symbol, side, qty, price, filled_qty, status, order_type, limit_price, realized_pl, portfolio_id) VALUES (?,?,?,?,?,?,?,?,?,?)',
                (symbol, side, qty, fill_price, qty, status, otype, limit_price, realized_pl, pid)
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
    if not KEYS_SET:
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

_FINNHUB_QUOTE_TTL = 8   # seconds — REST cache when WebSocket hasn't updated yet

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

        def _df(df):
            rows = []
            df = df.fillna(0)  # NaN is truthy; int(NaN) raises ValueError
            for _, r in df.iterrows():
                rows.append({
                    'strike':     round(float(r.get('strike', 0)), 4),
                    'bid':        round(float(r.get('bid', 0)), 4),
                    'ask':        round(float(r.get('ask', 0)), 4),
                    'last':       round(float(r.get('lastPrice', 0)), 4),
                    'iv':         round(float(r.get('impliedVolatility', 0)) * 100, 1),
                    'volume':     int(float(r.get('volume', 0))),
                    'oi':         int(float(r.get('openInterest', 0))),
                    'itm':        bool(r.get('inTheMoney', False)),
                    'change':     round(float(r.get('change', 0)), 4),
                    'change_pct': round(float(r.get('percentChange', 0)), 2),
                })
            return rows

        # Get current underlying price for ATM reference
        try:
            hist  = ticker.history(period='1d')
            closes = hist['Close'].dropna()
            spot  = float(closes.iloc[-1]) if len(closes) else 0.0
        except Exception:
            spot = 0.0

        data = {
            'symbol':      symbol,
            'spot':        round(spot, 4),
            'expirations': expirations[:16],
            'selected':    selected,
            'calls':       _df(chain.calls),
            'puts':        _df(chain.puts),
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
    if FINNHUB_KEYS_SET:
        try:
            from finnhub_stream import subscribe as fh_sub
            fh_sub(sym, socketio)
        except Exception:
            pass
    if KEYS_SET:
        try:
            from alpaca_stream import subscribe
            subscribe(sym, socketio)
        except Exception:
            pass
    if POLYGON_KEYS_SET:
        try:
            from polygon_stream import subscribe as poly_sub
            poly_sub(sym)
        except Exception:
            pass
    return jsonify({'status': 'subscribed', 'symbol': sym})

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
_NEWS_TTL = 300  # 5 minutes

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
    # Mega-cap tech
    'AAPL','MSFT','NVDA','GOOGL','META','AMZN','TSLA','AVGO','ADBE','CRM',
    # Semiconductors / tech
    'AMD','INTC','QCOM','TXN','ORCL','IBM','INTU','NOW','SNOW','PLTR',
    # Financials
    'JPM','BAC','GS','MS','V','MA','AXP','BLK','C','WFC',
    # Healthcare
    'UNH','LLY','JNJ','PFE','MRK','ABBV','TMO','DHR','AMGN','GILD',
    # Consumer
    'WMT','COST','HD','TGT','NKE','MCD','SBUX','CMG',
    # Energy
    'XOM','CVX','COP','SLB','OXY','EOG',
    # Industrials
    'CAT','DE','HON','BA','GE','UPS','FDX','RTX','LMT',
    # Communication / media
    'NFLX','DIS','CMCSA','T','VZ',
    # ETFs (liquid, indicator-friendly)
    'SPY','QQQ','IWM','GLD','TLT',
]
_AI_UNIVERSE = list(dict.fromkeys(_AI_UNIVERSE))  # deduplicate, preserve order

# Per-portfolio rotating scan cursor: {portfolio_id: int}
_ai_scan_cursor: dict = {}


def _ema(vals, period):
    k = 2.0 / (period + 1)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _ai_score(data: dict) -> float:
    """Replicate the frontend computeDecision score. BUY ≥ 2.0, SELL ≤ -2.0."""
    rsi      = float(data.get('rsi', 50) or 50)
    macd_x   = data.get('macd_cross', '') or ''
    stoch_k  = float(data.get('stoch_k_val', 50) or 50)
    vol_sig  = data.get('volume_signal', '') or ''
    vol_r    = float(data.get('volume_ratio', 1.0) or 1.0)
    bb_pos   = data.get('bb_position', '') or ''
    vwap_sig = data.get('vwap_signal', '') or ''
    trend    = data.get('trend', '') or ''

    score = 0.0

    if   rsi <= 20: score += 3.0
    elif rsi <= 28: score += 2.0
    elif rsi <= 38: score += 1.0
    elif rsi >= 80: score -= 3.0
    elif rsi >= 72: score -= 2.0
    elif rsi >= 62: score -= 1.0

    if   macd_x == 'bullish_cross': score += 3.0
    elif macd_x == 'bullish':       score += 1.5
    elif macd_x == 'bearish_cross': score -= 3.0
    elif macd_x == 'bearish':       score -= 1.5

    if   stoch_k <= 15: score += 1.5
    elif stoch_k <= 25: score += 1.0
    elif stoch_k >= 85: score -= 1.5
    elif stoch_k >= 75: score -= 1.0

    vol_mult = min(vol_r / 1.5, 1.5) if vol_r > 1.5 else 1.0
    if   vol_sig == 'high_up':   score += 2.0 * vol_mult
    elif vol_sig == 'high_down': score -= 2.0 * vol_mult
    elif vol_sig == 'low':       score *= 0.65

    if   bb_pos == 'oversold':   score += 1.5
    elif bb_pos == 'lower_half': score += 0.5
    elif bb_pos == 'overbought': score -= 1.5
    elif bb_pos == 'upper_half': score -= 0.5

    if   vwap_sig == 'above': score += 1.0
    elif vwap_sig == 'below': score -= 1.0

    if   trend == 'up':   score += 1.5
    elif trend == 'down': score -= 1.5

    return round(score, 2)


def _ai_log_entry(pid: int, symbol: str, action: str, score: float,
                  price: float, shares: float, reason: str):
    with _get_db() as conn:
        conn.execute(
            'INSERT INTO ai_log (portfolio_id, symbol, action, score, price, shares, reason) VALUES (?,?,?,?,?,?,?)',
            (pid, symbol, action, score, price, shares, reason)
        )


def _ai_run_portfolio(pid: int) -> dict:
    """One AI scan cycle: check existing positions, then scan a batch for buys."""
    MAX_POS      = 8
    POS_PCT      = 0.10    # max 10% equity per new position
    CASH_RESERVE = 0.10    # keep ≥10% equity in cash
    ATR_STOP_M   = 1.5
    ATR_TGT_M    = 2.5
    BATCH_SIZE   = 15

    summary = {'pid': pid, 'scanned': 0, 'bought': [], 'sold': [], 'errors': []}

    try:
        # ── 1. Check held positions for exits ──────────────────────────────
        with _get_db() as conn:
            pos_rows = conn.execute(
                'SELECT symbol, shares, avg_cost FROM sim_positions WHERE portfolio_id=? AND shares>0',
                (pid,)
            ).fetchall()

        for row in pos_rows:
            sym = row['symbol']
            try:
                data  = _compute_indicators(sym)
                price = data.get('last_price') or _get_current_price(sym)
                score = _ai_score(data)
                atr   = data.get('atr') or (price * 0.02)
                stop  = row['avg_cost'] - ATR_STOP_M * atr
                tgt   = row['avg_cost'] + ATR_TGT_M  * atr

                if score <= -2.0 or price <= stop or price >= tgt:
                    reason = ('sell_signal' if score <= -2.0
                              else 'stop_loss' if price <= stop
                              else 'take_profit')
                    _sim_sell(sym, row['shares'], price, pid)
                    summary['sold'].append({'symbol': sym, 'price': round(price, 2),
                                            'score': score, 'reason': reason})
                    _ai_log_entry(pid, sym, 'SELL', score, price, row['shares'], reason)
            except Exception as e:
                summary['errors'].append(f'exit {sym}: {e}')

        # ── 2. Compute equity for position sizing ──────────────────────────
        state = _sim_state(pid)
        cash  = state['cash']
        with _get_db() as conn:
            held = [r['symbol'] for r in conn.execute(
                'SELECT symbol FROM sim_positions WHERE portfolio_id=? AND shares>0', (pid,)
            ).fetchall()]

        equity = cash
        for sym in held:
            try:
                equity += _get_current_price(sym) * next(
                    r['shares'] for r in pos_rows if r['symbol'] == sym
                )
            except Exception:
                pass

        available = cash - equity * CASH_RESERVE
        if len(held) >= MAX_POS or available <= 100:
            return summary

        # ── 3. Scan batch of universe symbols for buys ─────────────────────
        universe = [s for s in _AI_UNIVERSE if s not in held]
        cursor   = _ai_scan_cursor.get(pid, 0)
        batch    = [universe[(cursor + i) % len(universe)] for i in range(min(BATCH_SIZE, len(universe)))]
        _ai_scan_cursor[pid] = (cursor + BATCH_SIZE) % max(len(universe), 1)

        candidates = []
        for sym in batch:
            try:
                data  = _compute_indicators(sym)
                price = data.get('last_price')
                if not price or price <= 0:
                    continue
                score = _ai_score(data)
                summary['scanned'] += 1
                if score >= 2.0:
                    candidates.append({'symbol': sym, 'score': score,
                                       'price': price, 'atr': data.get('atr')})
            except Exception as e:
                summary['errors'].append(f'scan {sym}: {e}')

        candidates.sort(key=lambda x: x['score'], reverse=True)

        # ── 4. Buy top candidates ──────────────────────────────────────────
        n_pos = len(held)
        for c in candidates:
            if n_pos >= MAX_POS or available <= 100:
                break
            alloc  = min(equity * POS_PCT, available)
            shares = alloc / c['price']
            if shares < 0.001:
                continue
            try:
                _sim_buy(c['symbol'], shares, c['price'], pid)
                n_pos    += 1
                available -= alloc
                summary['bought'].append({'symbol': c['symbol'], 'price': round(c['price'], 2),
                                          'shares': round(shares, 4), 'score': c['score']})
                _ai_log_entry(pid, c['symbol'], 'BUY', c['score'], c['price'], shares,
                              f"score {c['score']:+.1f}")
            except Exception as e:
                summary['errors'].append(f'buy {c["symbol"]}: {e}')

    except Exception as e:
        summary['errors'].append(f'portfolio error: {e}')

    return summary


# ── AI background worker ───────────────────────────────────────────────────────
_AI_INTERVAL = 600   # seconds between scans (10 min)

def _ai_worker():
    """Daemon thread: every _AI_INTERVAL seconds scan all AI portfolios."""
    _time.sleep(30)   # let app finish startup
    while True:
        try:
            with _get_db() as conn:
                rows = conn.execute(
                    'SELECT id FROM portfolios WHERE ai_controlled=1'
                ).fetchall()
            for row in rows:
                try:
                    _ai_run_portfolio(row['id'])
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

    # ── Linear regression → 10-day projection ──
    last20_y  = closes[-20:]
    x_mean    = 9.5
    y_mean    = sum(last20_y) / 20
    num       = sum((i - x_mean) * (last20_y[i] - y_mean) for i in range(20))
    denom     = sum((i - x_mean) ** 2 for i in range(20))
    slope     = num / denom if denom else 0
    intercept = y_mean - slope * x_mean
    last_time = times[-1]
    projection = [
        {'time': last_time + (i + 1) * 86400,
         'value': round(intercept + slope * (19 + i + 1), 4)}
        for i in range(10)
    ]

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

    # ── VWAP (20-day rolling) ──
    vwap_arr = []
    for i in range(19, n):
        tp  = [(highs[j] + lows[j] + closes[j]) / 3 for j in range(i-19, i+1)]
        vol = volumes[i-19:i+1]
        tv  = sum(vol)
        if tv > 0:
            vwap_arr.append({'time': times[i], 'value': round(sum(p*v for p,v in zip(tp, vol)) / tv, 4)})
    last_vwap   = vwap_arr[-1]['value'] if vwap_arr else None
    vwap_signal = 'above' if (last_vwap and last_c > last_vwap) else 'below'

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
    if FINNHUB_KEYS_SET:
        try:
            from finnhub_stream import start_stream as fh_start
            fh_start(FINNHUB_KEY, socketio)
            print('[TradeSimulator] Finnhub real-time WebSocket stream starting.')
        except Exception as e:
            print(f'[TradeSimulator] Finnhub stream failed: {e}')
    elif KEYS_SET:
        try:
            from alpaca_stream import start_stream
            threading.Thread(target=start_stream, args=(API_KEY, SECRET_KEY, socketio), daemon=True).start()
        except Exception as e:
            print(f'[TradeSimulator] Alpaca stream failed: {e}')
    elif POLYGON_KEYS_SET:
        try:
            from polygon_stream import start_stream as poly_start
            threading.Thread(target=poly_start, args=(POLYGON_KEY, socketio), daemon=True).start()
            print('[TradeSimulator] Polygon.io real-time feed starting.')
        except Exception as e:
            print(f'[TradeSimulator] Polygon stream failed: {e}')
    else:
        print('[TradeSimulator] No live price feed — using yfinance (delayed).')
    # Poll worker runs always: fills gaps outside market hours and handles watchlist price updates
    threading.Thread(target=_poll_worker, daemon=True).start()
    if AV_KEYS_SET:
        print('[TradeSimulator] Alpha Vantage key configured — comprehensive symbol search enabled.')
    socketio.run(app, host='0.0.0.0', port=8765, debug=False)

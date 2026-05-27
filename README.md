# TradeSimulator

A paper trading desktop app for practicing day trading with real market prices. No real money involved — trades execute against a simulated $100,000 account while prices come from live market data.

![Stack](https://img.shields.io/badge/React_18-Vite-blue) ![Stack](https://img.shields.io/badge/Flask-Python-green) ![Stack](https://img.shields.io/badge/Electron-34-lightblue)

---

## Features

- **Candlestick charts** — powered by TradingView lightweight-charts with full dark theme, no watermark, and timezone-aware time axis
- **11 timeframes** — 1Min, 5Min, 15Min, 1Hour, 1Day, 1Wk, 1Mo, 3Mo, YTD, 1Yr, 5Yr
- **Order simulation** — market and limit buy/sell orders with instant fill; avg cost basis tracking per symbol
- **In-memory P&L engine** — unrealized gains, realized gains, portfolio equity, and day P&L — all calculated locally, no brokerage account needed
- **Holdings tracker** — log real or hypothetical stock purchases by date; historical price lookup fills in buy price automatically
- **Comprehensive search** — 8,000+ NASDAQ/NYSE tickers downloaded on first launch; sparkline preview in dropdown
- **Real-time prices** — Polygon.io WebSocket (minute bars + quotes) if key is set; falls back to Alpaca IEX feed; falls back to yfinance delayed data
- **Watchlist** — pin symbols, see live prices update
- **Account reset** — wipe all positions and trades, restore $100k cash in one click
- **Electron desktop app** — frameless window, custom title bar, spawns Flask server automatically

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + Vite 5 |
| Charts | lightweight-charts 4.2 |
| Backend | Python Flask + Flask-SocketIO |
| Real-time | Polygon.io WebSocket → SocketIO → browser |
| Market data | yfinance (free, delayed) / Alpaca IEX / Polygon.io |
| Storage | SQLite (positions, trades, holdings) |
| Desktop | Electron 34 |

---

## Project Structure

```
TradeSimulator/
├── backend/
│   ├── app.py              # Flask REST API + portfolio simulation engine
│   ├── alpaca_stream.py    # Alpaca WebSocket → SocketIO relay
│   ├── polygon_stream.py   # Polygon.io WebSocket → SocketIO relay
│   ├── requirements.txt
│   └── .env.example        # API key template
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── index.css
│   │   ├── api.js
│   │   └── components/
│   │       ├── Chart.jsx       # Candlestick chart + live bar updates
│   │       ├── SymbolSearch.jsx # Search dropdown with sparklines
│   │       ├── Watchlist.jsx
│   │       ├── OrderForm.jsx
│   │       ├── OrderBook.jsx
│   │       ├── Positions.jsx
│   │       ├── Portfolio.jsx
│   │       ├── Holdings.jsx
│   │       └── TitleBar.jsx
│   ├── vite.config.js
│   └── package.json
├── electron/
│   ├── main.js             # Spawns Flask, creates BrowserWindow
│   ├── preload.cjs         # contextBridge: window controls
│   └── package.json
└── launcher.py             # Direct Python launcher (no Electron)
```

---

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/ThatOneJet/TradeSimulator.git
cd TradeSimulator

# Backend
cd backend
pip install -r requirements.txt
cd ..

# Frontend
cd frontend
npm install
cd ..

# Electron
cd electron
npm install
cd ..
```

### 2. Configure API keys (optional)

Copy `backend/.env.example` to `backend/.env` and fill in any keys you have. All keys are optional — the app works with zero keys using yfinance for delayed prices.

```env
# Real-time bars + quotes (free paper account at alpaca.markets)
ALPACA_API_KEY=
ALPACA_SECRET_KEY=

# Comprehensive symbol search (free at alphavantage.co)
ALPHA_VANTAGE_KEY=

# Best real-time feed (free at polygon.io)
POLYGON_KEY=
```

**Recommended priority for best experience:**
1. Polygon.io key — best real-time data (free tier supports stocks)
2. Alpaca paper keys — good IEX feed + full asset search
3. Alpha Vantage key — improves symbol search results
4. No keys — works fine with yfinance (15-min delayed prices)

### 3. Run

**Desktop app (Electron + Flask + Vite together):**
```bash
cd electron
npm run dev
```

**Browser dev mode (Flask + Vite separately):**
```bash
# Terminal 1
cd backend && python app.py

# Terminal 2
cd frontend && npm run dev
# Open http://localhost:5173
```

---

## How It Works

### Portfolio simulation

All trades are paper trades stored in a local SQLite database (`backend/holdings.db`, not committed). The engine tracks:

- **Cash ledger** — starts at $100,000; decremented on buy, incremented on sell
- **Average cost basis** — recalculated on each buy using weighted average
- **Unrealized P&L** — `(current price − avg cost) × shares`, updated every 5 seconds
- **Realized P&L** — locked in at sell time: `(sell price − avg cost) × shares`
- **Portfolio equity** — cash + sum of all position market values

No Alpaca or brokerage account is needed for trading. Only the price feed touches external APIs.

### Symbol search

On first launch, TradeSimulator downloads the full NASDAQ + NYSE listing from nasdaqtrader.com (~8,000+ tickers) and caches it locally for 7 days. Search matches on symbol prefix first, then name substring. If an Alpha Vantage key is configured, results also include AV's ranked matches.

### Real-time data flow

```
Polygon.io WS  ─┐
Alpaca WS      ─┼─▶  Flask SocketIO  ─▶  browser (socket.io-client)
yfinance poll  ─┘         │
                           └─▶  REST /api/bars, /api/quote, /api/positions
```

---

## Building a distributable

```bash
# Build frontend first
cd frontend && npm run build && cd ..

# Build Windows installer
cd electron && npm run build:win
# Output: dist-electron/TradeSimulator Setup *.exe
```

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/account` | Equity, cash, day P&L |
| GET | `/api/positions` | Open positions with live P&L |
| GET | `/api/orders` | Trade history (last 100) |
| POST | `/api/orders` | Place market or limit order |
| DELETE | `/api/orders/:id` | Cancel pending order |
| POST | `/api/account/reset` | Reset to $100k, clear all data |
| GET | `/api/bars/:symbol` | OHLCV bars (`?timeframe=1Min&limit=300`) |
| GET | `/api/quote/:symbol` | Latest bid/ask snapshot |
| GET | `/api/sparkline/:symbol` | Last 30 daily closes (for search UI) |
| GET | `/api/assets/search` | Symbol search (`?q=AAPL`) |
| GET | `/api/watchlist` | Watchlist with live prices |
| POST | `/api/watchlist` | Add/remove symbol |
| GET | `/api/holdings` | Personal holdings with P&L |
| POST | `/api/holdings` | Add holding (auto-fetches historical price) |
| DELETE | `/api/holdings/:id` | Remove holding |

---

## License

Private — all rights reserved.

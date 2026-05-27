import { useState, useEffect, useCallback } from 'react'
import { io } from 'socket.io-client'
import TitleBar from './components/TitleBar.jsx'
import Rail from './components/Rail.jsx'
import NavSidebar from './components/NavSidebar.jsx'
import Chart from './components/Chart.jsx'
import OrderForm from './components/OrderForm.jsx'
import OrderBook from './components/OrderBook.jsx'
import Portfolio from './components/Portfolio.jsx'
import Positions from './components/Positions.jsx'
import Holdings from './components/Holdings.jsx'
import Login from './pages/Login.jsx'
import PortfolioTabs from './components/PortfolioTabs.jsx'
import NewsPage from './pages/NewsPage.jsx'
import NewsWidget from './components/NewsWidget.jsx'
import ExplorePage from './pages/ExplorePage.jsx'
import ProjectionWidget from './components/ProjectionWidget.jsx'
import Settings from './pages/Settings.jsx'
import NewsTicker from './components/NewsTicker.jsx'
import api from './api.js'

const socket = io('http://localhost:8765')

const TF_LABELS = {
  '1Min': '1m', '5Min': '5m', '15Min': '15m', '1Hour': '1h', '1Day': '1D',
  '1Wk': '1W',  '1Mo': '1M', '3Mo': '3M',    'YTD': 'YTD', '1Yr': '1Y', '5Yr': '5Y',
}

export default function App() {
  // ── Auth ──────────────────────────────────────────────────────────────────
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem('ts_user')) } catch { return null }
  })

  function handleUserUpdate(updated) {
    setUser(updated)
  }

  // ── UI state ──────────────────────────────────────────────────────────────
  const [sideOpen,     setSideOpen]     = useState(true)
  const [navCollapsed, setNavCollapsed] = useState(false)
  const [railTab,      setRailTab]      = useState('chart') // 'chart' | 'news' | 'holdings' | 'explore'

  // ── Trading state ─────────────────────────────────────────────────────────
  const [symbol,    setSymbol]    = useState('AAPL')
  const [account,   setAccount]   = useState(null)
  const [positions, setPositions] = useState([])
  const [quote,     setQuote]     = useState(null)
  const [timeframe, setTimeframe] = useState('1Min')
  const [delta,     setDelta]     = useState(null)
  const [company,   setCompany]   = useState(null) // { name, exchange }

  // ── Chart overlay toggles ─────────────────────────────────────────────────
  const [overlays, setOverlays] = useState(new Set())
  const toggleOverlay = (name) => setOverlays(prev => {
    const n = new Set(prev)
    n.has(name) ? n.delete(name) : n.add(name)
    return n
  })

  // ── Portfolio ─────────────────────────────────────────────────────────────
  const [portfolioId, setPortfolioId] = useState(() => {
    const stored = localStorage.getItem('ts_portfolio_id')
    return stored ? Number(stored) : 1
  })

  // ── Watchlist symbol list (fed to news page) ──────────────────────────────
  const [watchlistSymbols, setWatchlistSymbols] = useState([])

  // ── Subscribe to active symbol + fetch day delta + company name ───────────
  useEffect(() => {
    api.post(`/subscribe/${symbol}`)
    setDelta(null)
    setCompany(null)
    api.get(`/quote/${symbol}`).then(r => setDelta(r.data)).catch(() => {})
    api.get(`/company/${symbol}`).then(r => setCompany(r.data)).catch(() => {})
  }, [symbol])

  // ── Live quote via SocketIO ───────────────────────────────────────────────
  useEffect(() => {
    const handler = (data) => {
      if (data.symbol === symbol) setQuote(data)
    }
    socket.on('quote', handler)
    return () => socket.off('quote', handler)
  }, [symbol])

  // ── Poll account + positions every 5s ────────────────────────────────────
  const refresh = useCallback(() => {
    api.get(`/account?portfolio_id=${portfolioId}`).then(r => setAccount(r.data)).catch(() => {})
    api.get(`/positions?portfolio_id=${portfolioId}`).then(r => setPositions(r.data)).catch(() => {})
  }, [portfolioId])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 5000)
    return () => clearInterval(id)
  }, [refresh])

  // ── Persist portfolioId to localStorage ──────────────────────────────────
  useEffect(() => {
    localStorage.setItem('ts_portfolio_id', String(portfolioId))
  }, [portfolioId])

  // ── Auth guard ────────────────────────────────────────────────────────────
  if (!user) return <Login onLogin={setUser} />

  const midPrice = quote ? ((quote.bid + quote.ask) / 2).toFixed(2) : null

  return (
    <div className={`app-shell${sideOpen ? ' side-open' : ''}${navCollapsed ? ' nav-col-collapsed' : ''}`}>

      {/* ── TitleBar: row 1, all columns ── */}
      <TitleBar symbol={symbol} account={account} />

      {/* ── Rail: row 2, col 1 ── */}
      <Rail
        activeTab={railTab}
        onTabChange={setRailTab}
        sideOpen={sideOpen}
        onToggleSide={() => setSideOpen(s => !s)}
      />

      {/* ── NavSidebar: row 2, col 2 ── */}
      <NavSidebar
        active={symbol}
        onSelect={setSymbol}
        socket={socket}
        user={user}
        onWatchlistChange={setWatchlistSymbols}
        onLogout={() => { localStorage.removeItem('ts_user'); window.location.reload() }}
        onCollapseChange={(c) => setNavCollapsed(c)}
      />

      {/* ── Main content: row 2, col 3 ── */}
      <main className="main">
        <NewsTicker />

        {railTab === 'chart' && (
          <>
            {/* Portfolio tabs row */}
            <PortfolioTabs
              portfolioId={portfolioId}
              onSwitch={setPortfolioId}
              userId={user?.user_id}
            />

            {/* Chart header bar */}
            <div className="ch-header">
              <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                <span className="chart-symbol">{symbol}</span>
                {company?.name && company.name !== symbol && (
                  <span style={{ fontSize: 10, color: 'var(--t-3)', lineHeight: 1 }}>
                    {company.name}
                    {company.exchange ? ` · ${company.exchange}` : ''}
                  </span>
                )}
              </div>

              {midPrice && (
                <span className="chart-price mono">
                  ${midPrice}
                  {quote?.spread != null && (
                    <span className="chart-spread"> spread ${Number(quote.spread).toFixed(2)}</span>
                  )}
                </span>
              )}

              {delta?.change !== undefined && delta.change !== 0 && (
                <span className={`chart-delta mono ${delta.change >= 0 ? 'ok' : 'err'}`}>
                  {delta.change >= 0 ? '+' : ''}{Number(delta.change).toFixed(2)}&nbsp;
                  ({delta.change >= 0 ? '+' : ''}{Number(delta.change_pct).toFixed(2)}%)
                </span>
              )}

              {/* Timeframe buttons */}
              <div className="tf-group">
                {Object.keys(TF_LABELS).map(tf => (
                  <button
                    key={tf}
                    className={`tf-btn${timeframe === tf ? ' active' : ''}`}
                    onClick={() => setTimeframe(tf)}
                  >
                    {TF_LABELS[tf]}
                  </button>
                ))}
              </div>

              {/* Overlay toggles */}
              <div className="overlay-group">
                {['SMA20', 'SMA50', 'Proj', 'RSI'].map(o => (
                  <button
                    key={o}
                    className={`tf-btn${overlays.has(o) ? ' active' : ''}`}
                    onClick={() => toggleOverlay(o)}
                  >
                    {o}
                  </button>
                ))}
              </div>

              {/* Toggle side panel */}
              <button
                className="ch-btn"
                title={sideOpen ? 'Hide panel' : 'Show panel'}
                onClick={() => setSideOpen(s => !s)}
              >
                ⊞
              </button>
            </div>

            {/* Chart + order form */}
            <div className="ch-body">
              <Chart
                symbol={symbol}
                timeframe={timeframe}
                socket={socket}
                overlays={overlays}
              />
              <OrderForm
                symbol={symbol}
                account={account}
                onOrderPlaced={refresh}
                portfolioId={portfolioId}
              />
            </div>
          </>
        )}

        {railTab === 'news' && (
          <NewsPage symbol={symbol} watchlist={watchlistSymbols} />
        )}

        {railTab === 'holdings' && (
          <Holdings
            onSelectSymbol={(sym) => { setSymbol(sym); setRailTab('chart') }}
            portfolioId={portfolioId}
            positions={positions}
            onRefresh={refresh}
          />
        )}

        {railTab === 'explore' && (
          <ExplorePage
            onSelectSymbol={(sym) => { setSymbol(sym); setRailTab('chart') }}
          />
        )}

        {railTab === 'settings' && (
          <Settings
            user={user}
            onUserUpdate={handleUserUpdate}
            portfolioId={portfolioId}
            onReset={refresh}
            onLogout={() => { localStorage.removeItem('ts_user'); window.location.reload() }}
          />
        )}

      </main>

      {/* ── Side panel: row 2, col 4 ── */}
      {sideOpen && (
        <aside className="side">
          <Portfolio account={account} onReset={refresh} portfolioId={portfolioId} />
          <Positions positions={positions} onRefresh={refresh} portfolioId={portfolioId} />
          <OrderBook symbol={symbol} quote={quote} />
          <ProjectionWidget symbol={symbol} />
          <NewsWidget symbol={symbol} />
        </aside>
      )}

    </div>
  )
}

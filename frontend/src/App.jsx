import { useState, useEffect, useCallback } from 'react'
import { io } from 'socket.io-client'
import TitleBar from './components/TitleBar.jsx'
import Rail from './components/Rail.jsx'
import Watchlist from './components/Watchlist.jsx'
// NavSidebar no longer rendered — watchlist moved to left widget column
import Chart from './components/Chart.jsx'
import TradePanel from './components/TradePanel.jsx'
import Positions from './components/Positions.jsx'
import Holdings from './components/Holdings.jsx'
import Login from './pages/Login.jsx'
import PortfolioTabs from './components/PortfolioTabs.jsx'
import NewsPage from './pages/NewsPage.jsx'
import SetupGuideWidget from './components/SetupGuideWidget.jsx'
import ExplorePage from './pages/ExplorePage.jsx'
import MarketsPage from './pages/MarketsPage.jsx'
import MarketMap from './pages/MarketMap.jsx'
import AnalysisPanel from './components/AnalysisPanel.jsx'
import RiskPanel from './components/RiskPanel'
import OptionsPanel from './components/OptionsPanel'
import AILogPanel from './components/AILogPanel'
import ArbitragePanel from './components/ArbitragePanel.jsx'
import TradeBrief from './components/TradeBrief.jsx'
import RankingsPanel from './components/RankingsPanel.jsx'
import Settings from './pages/Settings.jsx'
import NewsTicker from './components/NewsTicker.jsx'
import ConfirmModal from './components/ConfirmModal.jsx'
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
  const [railOpen,    setRailOpen]    = useState(false)
  const [widgetsOpen, setWidgetsOpen] = useState(true)
  const [railTab,     setRailTab]     = useState('chart')
  const [leftTab,     setLeftTab]     = useState('watch') // 'watch'|'analysis'|'options'|'rankings'|'aiscan'
  const [signOutModal, setSignOutModal] = useState(false)

  // ── Projection data (fetched on symbol change, shared across panels) ──────
  const [projectionData, setProjectionData] = useState(null)

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
    setProjectionData(null)
    api.get(`/quote/${symbol}`).then(r => setDelta(r.data)).catch(() => {})
    api.get(`/company/${symbol}`).then(r => setCompany(r.data)).catch(() => {})
    api.get(`/projection/${symbol}`).then(r => setProjectionData(r.data)).catch(() => {})
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

  const midPrice = quote
    ? ((quote.bid + quote.ask) / 2).toFixed(2)
    : delta?.bid
      ? ((Number(delta.bid) + Number(delta.ask || delta.bid)) / 2).toFixed(2)
      : null
  const priceDelayed = !quote && delta?.delayed
  // Market is closed if it's a weekend or outside 9:30-16:00 ET
  const _nowET = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/New_York' }))
  const _isWeekend = _nowET.getDay() === 0 || _nowET.getDay() === 6
  const _hour = _nowET.getHours() + _nowET.getMinutes() / 60
  const marketClosed = _isWeekend || _hour < 9.5 || _hour >= 16
  const priceLabel = priceDelayed ? (marketClosed ? 'closed' : 'delayed') : null

  // ── User initials helper ──────────────────────────────────────────────────
  function userInitials(name) {
    if (!name) return '?'
    const parts = name.trim().split(/\s+/)
    return parts.length >= 2
      ? (parts[0][0] + parts[1][0]).toUpperCase()
      : name.slice(0, 2).toUpperCase()
  }

  return (
    <div className={`app-shell${railOpen ? ' rail-open' : ''}${!widgetsOpen ? ' widgets-collapsed' : ''}`}>

      {/* ── TitleBar: row 1, all columns ── */}
      <TitleBar symbol={symbol} account={account} />

      {/* ── Left panel: row 2, col 1 ── */}
      <aside className="widgets-col">
        {/* Tab bar */}
        <div style={{
          display: 'flex', flexShrink: 0,
          borderBottom: '1px solid rgba(140,170,220,0.08)',
          background: 'rgba(0,0,0,0.2)',
        }}>
          {[
            { key: 'watch',    label: 'Watch'    },
            { key: 'analysis', label: 'Analysis' },
            { key: 'options',  label: 'Options'  },
            { key: 'rankings', label: 'Rank'     },
            { key: 'aiscan',   label: 'AI Scan'  },
            { key: 'arb',      label: 'Arb'      },
          ].map(t => (
            <button
              key={t.key}
              onClick={() => setLeftTab(t.key)}
              style={{
                flex: 1, padding: '7px 0', border: 'none', cursor: 'pointer',
                background: leftTab === t.key ? 'rgba(179,157,255,0.1)' : 'transparent',
                color: leftTab === t.key ? '#b39dff' : '#475061',
                fontSize: '10px', fontWeight: leftTab === t.key ? 700 : 400,
                borderBottom: leftTab === t.key ? '2px solid #b39dff' : '2px solid transparent',
                fontFamily: 'var(--font-sans)', transition: 'color 0.15s',
                whiteSpace: 'nowrap', overflow: 'hidden',
              }}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Tab content — scrollable */}
        <div className="widgets-scroll">
          {leftTab === 'watch' && (
            <>
              <Watchlist
                active={symbol}
                onSelect={setSymbol}
                socket={socket}
                onWatchlistChange={setWatchlistSymbols}
                portfolioId={portfolioId}
                onPrioritySymbol={setSymbol}
              />
              <div style={{ borderTop: '1px solid rgba(140,170,220,0.08)' }}>
                <Positions positions={positions} onRefresh={refresh} portfolioId={portfolioId} totalValue={account?.portfolio_value} />
              </div>
              <div style={{ borderTop: '1px solid rgba(140,170,220,0.08)' }}>
                <TradePanel
                  symbol={symbol}
                  account={account}
                  portfolioId={portfolioId}
                  quote={quote}
                  onReset={refresh}
                />
              </div>
              <div style={{ borderTop: '1px solid rgba(140,170,220,0.08)' }}>
                <SetupGuideWidget symbol={symbol} quote={quote} delta={delta} />
              </div>
            </>
          )}
          {leftTab === 'analysis' && (
            <AnalysisPanel symbol={symbol} quote={quote} delta={delta} portfolioId={portfolioId} price={midPrice} />
          )}
          {leftTab === 'options' && (
            <OptionsPanel symbol={symbol} />
          )}
          {leftTab === 'rankings' && (
            <RankingsPanel portfolioId={portfolioId} onSelect={(sym) => { setSymbol(sym); setLeftTab('watch') }} />
          )}
          {leftTab === 'aiscan' && (
            <AILogPanel portfolioId={portfolioId} isAiControlled={true} user={user} />
          )}
          {leftTab === 'arb' && (
            <ArbitragePanel portfolioId={portfolioId} />
          )}
        </div>

        {/* User profile footer */}
        <div className="wl-user-foot">
          <div
            className="nav-foot-avatar"
            style={{ background: user?.avatar_color || 'var(--acc)' }}
            title={user?.username}
          >
            {userInitials(user?.username || '')}
          </div>
          <div className="nav-foot-text">
            <span className="nav-foot-name">{user?.username || 'Trader'}</span>
            <span className="nav-foot-plan">PAPER</span>
          </div>
          <button
            className="nav-foot-logout"
            title="Log out"
            onClick={() => setSignOutModal(true)}
          >⏻</button>
          {signOutModal && (
            <ConfirmModal
              message="Sign out of TradeSimulator?"
              confirmLabel="Sign Out"
              danger
              onConfirm={() => { localStorage.removeItem('ts_user'); window.location.reload() }}
              onCancel={() => setSignOutModal(false)}
            />
          )}
        </div>
      </aside>

      {/* ── Main content: row 2, col 2 ── */}
      <main className="main">
        <NewsTicker onSelectSymbol={(sym) => { setSymbol(sym); setRailTab('chart') }} />

        {railTab === 'chart' && (
          <>
            <PortfolioTabs
              portfolioId={portfolioId}
              onSwitch={setPortfolioId}
              userId={user?.user_id}
            />

            <div className="ch-header">
              <button
                className="ch-btn"
                title={widgetsOpen ? 'Collapse panel' : 'Expand panel'}
                onClick={() => setWidgetsOpen(o => !o)}
                style={{ fontSize: 13, letterSpacing: '-0.5px', width: 26, flexShrink: 0 }}
              >
                {widgetsOpen ? '«' : '»'}
              </button>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                <span className="chart-symbol">{symbol}</span>
                {company?.name && company.name !== symbol && (
                  <span style={{ fontSize: 10, color: 'var(--t-3)', lineHeight: 1 }}>
                    {company.name}{company.exchange ? ` · ${company.exchange}` : ''}
                  </span>
                )}
              </div>

              {midPrice && (
                <span className="chart-price mono">
                  ${midPrice}
                  {quote?.spread != null && (
                    <span className="chart-spread"> spread ${Number(quote.spread).toFixed(2)}</span>
                  )}
                  {priceLabel && (
                    <span style={{ fontSize: 9, color: priceLabel === 'closed' ? 'var(--t-4)' : 'var(--warn)', marginLeft: 5, opacity: 0.7 }}>{priceLabel}</span>
                  )}
                </span>
              )}

              {delta?.change !== undefined && delta.change !== 0 && (
                <span className={`chart-delta mono ${delta.change >= 0 ? 'ok' : 'err'}`}>
                  {delta.change >= 0 ? '+' : ''}{Number(delta.change).toFixed(2)}&nbsp;
                  ({delta.change >= 0 ? '+' : ''}{Number(delta.change_pct).toFixed(2)}%)
                </span>
              )}

              <div className="tf-group">
                {Object.keys(TF_LABELS).map(tf => (
                  <button
                    key={tf}
                    className={`tf-btn${timeframe === tf ? ' active' : ''}`}
                    onClick={() => setTimeframe(tf)}
                  >{TF_LABELS[tf]}</button>
                ))}
              </div>

              <div className="overlay-group" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                {/* Quick trade buttons — full order in Analysis tab */}
                <button
                  onClick={() => setLeftTab('analysis')}
                  style={{ padding: '3px 12px', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 11, fontWeight: 700, letterSpacing: '0.04em', background: 'rgba(61,220,151,0.15)', color: '#3ddc97', border: '1px solid rgba(61,220,151,0.3)' }}
                  title="Go long — open Analysis tab for full order entry or Shift+drag on chart">
                  ▲ LONG
                </button>
                <button
                  onClick={() => setLeftTab('analysis')}
                  style={{ padding: '3px 12px', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 11, fontWeight: 700, letterSpacing: '0.04em', background: 'rgba(255,71,111,0.15)', color: '#ff476f', border: '1px solid rgba(255,71,111,0.3)' }}
                  title="Go short — open Analysis tab for full order entry or Shift+drag on chart">
                  ▼ SHORT
                </button>
                <span style={{ fontSize: 8, color: 'var(--t-4)', marginLeft: 4 }}>or Shift+drag chart</span>
              </div>
            </div>

            {/* Signal strip — compact inline stats bar (no longer expandable) */}
            {projectionData && (
              <div style={{ height: '26px', display: 'flex', alignItems: 'center', padding: '0 10px', gap: '10px', borderTop: '1px solid rgba(140,170,220,0.07)', background: 'rgba(0,0,0,0.1)', flexShrink: 0 }}>
                <span style={{ fontSize: '9px', color: '#475061', letterSpacing: '0.07em', textTransform: 'uppercase' }}>Signals</span>
                {projectionData.regime && (
                  <span style={{ fontSize: '10px', padding: '0 6px', borderRadius: '3px', background: 'rgba(140,170,220,0.08)', color: '#aab4c5' }}>
                    {projectionData.regime.replace(/_/g, ' ')}
                  </span>
                )}
                {projectionData.rsi != null && (
                  <span style={{ fontSize: '10px', color: projectionData.rsi <= 30 ? '#3ddc97' : projectionData.rsi >= 70 ? '#ff476f' : '#6b7689' }}>
                    RSI {Number(projectionData.rsi).toFixed(0)}
                  </span>
                )}
                {projectionData.macd_cross && (
                  <span style={{ fontSize: '10px', color: projectionData.macd_cross.startsWith('bullish') ? '#3ddc97' : '#ff476f' }}>
                    MACD {projectionData.macd_cross.replace(/_/g, ' ')}
                  </span>
                )}
                {projectionData.mtf?.alignment && (
                  <span style={{ fontSize: '10px', padding: '0 6px', borderRadius: '3px', background: projectionData.mtf.alignment === 'bullish' ? 'rgba(61,220,151,0.1)' : projectionData.mtf.alignment === 'bearish' ? 'rgba(255,71,111,0.1)' : 'rgba(245,179,66,0.1)', color: projectionData.mtf.alignment === 'bullish' ? '#3ddc97' : projectionData.mtf.alignment === 'bearish' ? '#ff476f' : '#f5b342' }}>
                    MTF {projectionData.mtf.alignment}
                  </span>
                )}
              </div>
            )}

            <div className="ch-body">
              <Chart symbol={symbol} timeframe={timeframe} socket={socket} overlays={overlays} quote={quote} delta={delta} />
            </div>
          </>
        )}

        {railTab === 'news'     && <NewsPage symbol={symbol} watchlist={watchlistSymbols} positions={positions} />}
        {railTab === 'holdings' && (
          <Holdings
            onSelectSymbol={(sym) => { setSymbol(sym); setRailTab('chart') }}
            portfolioId={portfolioId}
            positions={positions}
            onRefresh={refresh}
          />
        )}
        {railTab === 'explore'  && (
          <ExplorePage onSelectSymbol={(sym) => { setSymbol(sym); setRailTab('chart') }} />
        )}
        {railTab === 'markets'  && (
          <MarketsPage
            symbol={symbol}
            onSelectSymbol={(sym) => { setSymbol(sym); setRailTab('chart') }}
          />
        )}
        {railTab === 'map' && (
          <MarketMap onSymbolSelect={(sym) => { setSymbol(sym); setRailTab('chart') }} />
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

      {/* ── Right rail: row 2, col 3 ── */}
      <Rail
        activeTab={railTab}
        onTabChange={setRailTab}
        sideOpen={railOpen}
        onToggleSide={() => setRailOpen(s => !s)}
      />

    </div>
  )
}

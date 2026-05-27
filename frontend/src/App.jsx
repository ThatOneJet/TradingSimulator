import { useState, useEffect, useCallback } from 'react'
import { io } from 'socket.io-client'
import TitleBar from './components/TitleBar.jsx'
import Watchlist from './components/Watchlist.jsx'
import Chart from './components/Chart.jsx'
import OrderForm from './components/OrderForm.jsx'
import OrderBook from './components/OrderBook.jsx'
import Portfolio from './components/Portfolio.jsx'
import Positions from './components/Positions.jsx'
import Holdings from './components/Holdings.jsx'
import api from './api.js'

const socket = io('http://localhost:8765')

export default function App() {
  const [symbol,    setSymbol]    = useState('AAPL')
  const [account,   setAccount]   = useState(null)
  const [positions, setPositions] = useState([])
  const [quote,     setQuote]     = useState(null)
  const [timeframe, setTimeframe] = useState('1Min')
  const [centerTab, setCenterTab] = useState('chart')  // 'chart' | 'holdings'

  // Subscribe to the active symbol's real-time data
  useEffect(() => {
    api.post(`/subscribe/${symbol}`)
  }, [symbol])

  // Live quote from SocketIO
  useEffect(() => {
    const handler = (data) => {
      if (data.symbol === symbol) setQuote(data)
    }
    socket.on('quote', handler)
    return () => socket.off('quote', handler)
  }, [symbol])

  // Poll account + positions every 5s
  const refresh = useCallback(() => {
    api.get('/account').then(r => setAccount(r.data)).catch(() => {})
    api.get('/positions').then(r => setPositions(r.data)).catch(() => {})
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 5000)
    return () => clearInterval(id)
  }, [refresh])

  return (
    <div className="app-shell">
      <TitleBar symbol={symbol} account={account} />
      <div className="main-grid">
        <aside className="panel-left">
          <Watchlist active={symbol} onSelect={setSymbol} socket={socket} />
        </aside>
        <main className="panel-center">
          <div className="center-tabs">
            <button className={`center-tab${centerTab === 'chart' ? ' active' : ''}`} onClick={() => setCenterTab('chart')}>Chart</button>
            <button className={`center-tab${centerTab === 'holdings' ? ' active' : ''}`} onClick={() => setCenterTab('holdings')}>Holdings</button>
          </div>
          {centerTab === 'chart' ? (
            <>
              <div className="chart-header">
                <span className="chart-symbol">{symbol}</span>
                {quote && (
                  <span className="chart-price mono">
                    ${((quote.bid + quote.ask) / 2).toFixed(2)}
                    <span className="chart-spread"> spread ${quote.spread?.toFixed(2)}</span>
                  </span>
                )}
                <div className="tf-group">
                  {['1Min','5Min','15Min','1Hour','1Day','1Wk','1Mo','3Mo','YTD','1Yr','5Yr'].map(tf => (
                    <button key={tf} className={`tf-btn${timeframe === tf ? ' active' : ''}`}
                      onClick={() => setTimeframe(tf)}>{tf}</button>
                  ))}
                </div>
              </div>
              <Chart symbol={symbol} timeframe={timeframe} socket={socket} />
              <OrderForm symbol={symbol} account={account} onOrderPlaced={refresh} />
            </>
          ) : (
            <Holdings onSelectSymbol={(sym) => { setSymbol(sym); setCenterTab('chart') }} />
          )}
        </main>
        <aside className="panel-right">
          <Portfolio account={account} onReset={refresh} />
          <Positions positions={positions} onRefresh={refresh} />
          <OrderBook symbol={symbol} quote={quote} socket={socket} />
        </aside>
      </div>
    </div>
  )
}

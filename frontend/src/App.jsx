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

const TF_LABELS = {
  '1Min':'1m', '5Min':'5m', '15Min':'15m', '1Hour':'1h', '1Day':'1D',
  '1Wk':'1W',  '1Mo':'1M',  '3Mo':'3M',   'YTD':'YTD',  '1Yr':'1Y', '5Yr':'5Y',
}

export default function App() {
  const [symbol,    setSymbol]    = useState('AAPL')
  const [account,   setAccount]   = useState(null)
  const [positions, setPositions] = useState([])
  const [quote,     setQuote]     = useState(null)
  const [timeframe, setTimeframe] = useState('1Min')
  const [centerTab, setCenterTab] = useState('chart')  // 'chart' | 'holdings'
  const [delta,     setDelta]     = useState(null)

  // Subscribe to active symbol + fetch initial quote for day delta
  useEffect(() => {
    api.post(`/subscribe/${symbol}`)
    setDelta(null)
    api.get(`/quote/${symbol}`).then(r => setDelta(r.data)).catch(() => {})
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
                {delta?.change !== undefined && delta.change !== 0 && (
                  <span className={`chart-delta mono ${delta.change >= 0 ? 'ok' : 'err'}`}>
                    {delta.change >= 0 ? '+' : ''}{Number(delta.change).toFixed(2)}&nbsp;
                    ({delta.change >= 0 ? '+' : ''}{Number(delta.change_pct).toFixed(2)}%)
                  </span>
                )}
                <div className="tf-group">
                  {Object.keys(TF_LABELS).map(tf => (
                    <button key={tf} className={`tf-btn${timeframe === tf ? ' active' : ''}`}
                      onClick={() => setTimeframe(tf)}>{TF_LABELS[tf]}</button>
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

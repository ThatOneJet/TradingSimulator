import { useState } from 'react'
import api from '../api.js'

export default function OrderForm({ symbol, account, onOrderPlaced, portfolioId }) {
  const [qty,        setQty]        = useState('')
  const [side,       setSide]       = useState('buy')
  const [orderType,  setOrderType]  = useState('market')
  const [limitPrice, setLimitPrice] = useState('')
  const [status,     setStatus]     = useState(null)
  const [loading,    setLoading]    = useState(false)

  async function submit(e) {
    e.preventDefault()
    if (!qty || isNaN(qty) || Number(qty) <= 0) { setStatus({ err: 'Enter a valid quantity' }); return }
    if (orderType === 'limit' && (!limitPrice || isNaN(limitPrice))) { setStatus({ err: 'Enter a valid limit price' }); return }
    setLoading(true); setStatus(null)
    try {
      const body = { symbol, qty: Number(qty), side, type: orderType, portfolio_id: portfolioId || 1 }
      if (orderType === 'limit') body.limit_price = Number(limitPrice)
      const r = await api.post('/orders', body)
      setStatus({ ok: `Order submitted: ${r.data.id?.slice(0,8)}…` })
      setQty(''); setLimitPrice('')
      onOrderPlaced?.()
    } catch (e) {
      setStatus({ err: e.response?.data?.error || 'Order failed' })
    }
    setLoading(false)
  }

  const estCost = account && qty ? (Number(qty) * (orderType === 'limit' && limitPrice ? Number(limitPrice) : 0)).toFixed(2) : null

  return (
    <form className="card order-form" onSubmit={submit}>
      <div className="card-header">Place Order</div>
      <div className="of-symbol mono">{symbol}</div>
      <div className="of-row">
        <div className="of-side-toggle">
          <button type="button" className={`of-side-btn${side === 'buy' ? ' active-buy' : ''}`} onClick={() => setSide('buy')}>BUY</button>
          <button type="button" className={`of-side-btn${side === 'sell' ? ' active-sell' : ''}`} onClick={() => setSide('sell')}>SELL</button>
        </div>
        <div className="of-type-toggle">
          <button type="button" className={`of-type-btn${orderType === 'market' ? ' active' : ''}`} onClick={() => setOrderType('market')}>Market</button>
          <button type="button" className={`of-type-btn${orderType === 'limit' ? ' active' : ''}`} onClick={() => setOrderType('limit')}>Limit</button>
        </div>
      </div>
      <div className="of-inputs">
        <label>Shares<input type="number" min="1" step="1" value={qty} onChange={e => setQty(e.target.value)} placeholder="0" /></label>
        {orderType === 'limit' && (
          <label>Limit Price<input type="number" step="0.01" value={limitPrice} onChange={e => setLimitPrice(e.target.value)} placeholder="0.00" /></label>
        )}
      </div>
      {account && <div className="of-meta">Available: <span className="mono">${Number(account.buying_power).toLocaleString('en-US',{maximumFractionDigits:0})}</span></div>}
      {status?.err && <div className="of-err">{status.err}</div>}
      {status?.ok  && <div className="of-ok">{status.ok}</div>}
      <button type="submit" className={`of-submit ${side === 'buy' ? 'buy' : 'sell'}`} disabled={loading}>
        {loading ? '…' : `${side.toUpperCase()} ${symbol}`}
      </button>
    </form>
  )
}

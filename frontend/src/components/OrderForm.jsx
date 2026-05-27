import { useState } from 'react'
import api from '../api.js'

export default function OrderForm({ symbol, account, onOrderPlaced, portfolioId, quote }) {
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

  // Live cost estimate
  const marketPrice = quote
    ? (side === 'buy' ? quote.ask : quote.bid)
    : null
  const effectivePrice = (orderType === 'limit' && limitPrice)
    ? Number(limitPrice)
    : marketPrice
  const shares        = Number(qty)
  const estimatedCost = (shares > 0 && effectivePrice > 0) ? shares * effectivePrice : null
  const buyingPower   = account ? Number(account.buying_power) : null
  const overBudget    = side === 'buy' && estimatedCost != null && buyingPower != null && estimatedCost > buyingPower

  const fmt = (n) => n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

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

      {/* Live cost estimate */}
      <div className="of-cost-block">
        {effectivePrice != null && effectivePrice > 0 && (
          <div className="of-cost-row">
            <span className="of-cost-label">@ price</span>
            <span className="of-cost-price mono">${fmt(effectivePrice)}</span>
          </div>
        )}
        {estimatedCost != null && (
          <div className="of-cost-row of-cost-total">
            <span className="of-cost-label">{side === 'buy' ? 'Est. Cost' : 'Est. Proceeds'}</span>
            <span className={`of-cost-value mono${overBudget ? ' err' : ''}`}>
              ${fmt(estimatedCost)}
            </span>
          </div>
        )}
        {account && (
          <div className="of-cost-row">
            <span className="of-cost-label">Available</span>
            <span className={`of-cost-avail mono${overBudget ? ' err' : ''}`}>
              ${Number(account.buying_power).toLocaleString('en-US', { maximumFractionDigits: 0 })}
              {overBudget && <span className="of-cost-warn"> — insufficient</span>}
            </span>
          </div>
        )}
      </div>

      {status?.err && <div className="of-err">{status.err}</div>}
      {status?.ok  && <div className="of-ok">{status.ok}</div>}
      <button type="submit" className={`of-submit ${side === 'buy' ? 'buy' : 'sell'}`} disabled={loading}>
        {loading ? '…' : `${side.toUpperCase()} ${symbol}`}
      </button>
    </form>
  )
}

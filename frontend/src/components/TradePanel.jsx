import { useState } from 'react'
import api from '../api.js'
import OrderConfirmModal from './OrderConfirmModal.jsx'

function PortfolioCard({ account, onReset, portfolioId }) {
  const [resetting, setResetting] = useState(false)
  const [msg, setMsg] = useState('')

  async function handleReset() {
    if (!window.confirm('Reset account to $100,000 and clear all positions?')) return
    setResetting(true)
    try {
      const r = await api.post('/account/reset', { portfolio_id: portfolioId || 1 })
      setMsg(r.data.message || 'Reset.')
      onReset?.()
    } catch { setMsg('Failed.') }
    setResetting(false)
    setTimeout(() => setMsg(''), 4000)
  }

  if (!account) return (
    <div className="tp-card">
      <div className="tp-skeleton-line" style={{ width: '55%', marginBottom: 10 }} />
      <div className="tp-skeleton-line" style={{ width: '40%' }} />
    </div>
  )

  const isReal = account.is_real
  const fmt = n => Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  const pnl      = isReal ? account.pnl : account.pnl_day
  const pnlDay   = account.pnl_day
  const pnlColor = pnl != null && pnl >= 0 ? 'var(--ok)' : 'var(--err)'
  const dayColor = pnlDay != null && pnlDay >= 0 ? 'var(--ok)' : 'var(--err)'

  return (
    <div className="tp-card">
      <div className="tp-card-hd">
        {isReal ? 'Real Holdings' : 'Portfolio'}
        {!isReal && (
          <button className="pf-reset-btn" onClick={handleReset} disabled={resetting}>
            {resetting ? '…' : 'Reset'}
          </button>
        )}
        {isReal && <span className="tp-badge-real">READ-ONLY</span>}
      </div>
      <div className="tp-metrics">
        <div className="tp-metric">
          <span className="tp-lbl">EQUITY</span>
          <span className="tp-val mono">${fmt(account.equity)}</span>
        </div>
        {isReal ? (
          <div className="tp-metric">
            <span className="tp-lbl">COST BASIS</span>
            <span className="tp-val mono">${fmt(account.initial_cost ?? 0)}</span>
          </div>
        ) : (
          <div className="tp-metric">
            <span className="tp-lbl">CASH</span>
            <span className="tp-val mono">${fmt(account.cash)}</span>
          </div>
        )}
        <div className="tp-metric">
          <span className="tp-lbl">{isReal ? 'TOTAL P&L' : 'DAY P&L'}</span>
          <span className="tp-val mono" style={{ color: pnlColor }}>
            {pnl != null ? `${pnl >= 0 ? '+' : ''}$${fmt(pnl)}` : '—'}
          </span>
        </div>
        {isReal ? (
          <div className="tp-metric">
            <span className="tp-lbl">RETURN</span>
            <span className="tp-val mono" style={{ color: pnlColor }}>
              {account.pnl_pct != null
                ? `${account.pnl_pct >= 0 ? '+' : ''}${Number(account.pnl_pct).toFixed(2)}%`
                : '—'}
            </span>
          </div>
        ) : (
          <div className="tp-metric">
            <span className="tp-lbl">BUYING PWR</span>
            <span className="tp-val mono">${fmt(account.buying_power)}</span>
          </div>
        )}
        {isReal && (
          <div className="tp-metric tp-metric-full">
            <span className="tp-lbl">DAY P&L</span>
            <span className="tp-val mono" style={{ color: pnlDay != null ? dayColor : 'var(--t-3)' }}>
              {pnlDay != null ? `${pnlDay >= 0 ? '+' : ''}$${fmt(pnlDay)}` : '— (no prior close)'}
            </span>
          </div>
        )}
      </div>
      {msg && <div className="tp-msg">{msg}</div>}
    </div>
  )
}

function PositionCard({ pos, portfolioId, onOrderPlaced }) {
  const isReal = portfolioId === 0
  const fmt = n => Number(n).toFixed(2)
  const pnlColor = pos.unrealized_pl >= 0 ? 'var(--ok)' : 'var(--err)'

  async function closeAll() {
    try {
      await api.post('/orders', {
        symbol: pos.symbol,
        qty: pos.qty,
        side: 'sell',
        type: 'market',
        portfolio_id: portfolioId || 1,
      })
      onOrderPlaced?.()
    } catch {}
  }

  return (
    <div className="tp-card tp-position-card">
      <div className="tp-card-hd">
        Position
        {!isReal && (
          <button className="close-btn" onClick={closeAll} title="Close entire position"
            style={{ marginLeft: 'auto', fontSize: 10, padding: '2px 8px' }}>
            Close All
          </button>
        )}
      </div>
      <div className="tp-metrics">
        <div className="tp-metric">
          <span className="tp-lbl">SHARES</span>
          <span className="tp-val mono">{pos.qty}</span>
        </div>
        <div className="tp-metric">
          <span className="tp-lbl">AVG COST</span>
          <span className="tp-val mono">${fmt(pos.avg_entry_price)}</span>
        </div>
        <div className="tp-metric">
          <span className="tp-lbl">CURRENT</span>
          <span className="tp-val mono">${fmt(pos.current_price)}</span>
        </div>
        <div className="tp-metric">
          <span className="tp-lbl">UNREAL. P&amp;L</span>
          <span className="tp-val mono" style={{ color: pnlColor }}>
            {pos.unrealized_pl >= 0 ? '+' : ''}${fmt(pos.unrealized_pl)}
            <span className="tp-pct"> ({(pos.unrealized_plpc * 100).toFixed(2)}%)</span>
          </span>
        </div>
      </div>
    </div>
  )
}

function OrderBookCard({ symbol, quote }) {
  const bid       = quote?.bid  ?? 0
  const ask       = quote?.ask  ?? 0
  const bidSz     = quote?.bid_size ?? 0
  const askSz     = quote?.ask_size ?? 0
  const spread    = ask - bid
  const spreadPct = bid > 0 ? ((spread / bid) * 100).toFixed(3) : '—'

  return (
    <div className="tp-card tp-ob-card">
      <div className="tp-card-hd">
        Order Book
        <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--t-3)', fontWeight: 400 }}>{symbol}</span>
      </div>
      <div style={{ fontSize: 10, color: 'var(--t-3)', fontFamily: 'var(--font-mono)', marginBottom: 8 }}>
        SPREAD&nbsp;
        <span style={{ color: 'var(--cy)' }}>{spread > 0 ? `$${spread.toFixed(4)}` : '—'}</span>
        <span style={{ color: 'var(--t-4)', marginLeft: 4 }}>({spreadPct}%)</span>
      </div>
      <table className="ob-table" style={{ width: '100%', tableLayout: 'fixed' }}>
        <thead>
          <tr><th>Price</th><th>Size</th><th>Side</th></tr>
        </thead>
        <tbody>
          <tr className="ob-ask">
            <td className="mono err">{ask > 0 ? ask.toFixed(2) : '—'}</td>
            <td className="mono">{askSz || '—'}</td>
            <td style={{ color: 'var(--err)', fontSize: 10, letterSpacing: '0.06em' }}>ASK</td>
          </tr>
          <tr className="ob-bid">
            <td className="mono ok">{bid > 0 ? bid.toFixed(2) : '—'}</td>
            <td className="mono">{bidSz || '—'}</td>
            <td style={{ color: 'var(--ok)', fontSize: 10, letterSpacing: '0.06em' }}>BID</td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}

export default function TradePanel({ symbol, account, positions, onOrderPlaced, portfolioId, quote, onReset }) {
  const [qty,        setQty]        = useState('')
  const [side,       setSide]       = useState('buy')
  const [orderType,  setOrderType]  = useState('market')
  const [limitPrice, setLimitPrice] = useState('')
  const [status,     setStatus]     = useState(null)
  const [loading,    setLoading]    = useState(false)
  const [showModal,  setShowModal]  = useState(false)

  const pos    = positions?.find(p => p.symbol === symbol)
  const isReal = portfolioId === 0

  // Validate then open confirmation modal
  function submit(e) {
    e.preventDefault()
    if (!qty || isNaN(qty) || Number(qty) <= 0) { setStatus({ err: 'Enter a valid quantity' }); return }
    if (orderType === 'limit' && (!limitPrice || isNaN(limitPrice))) { setStatus({ err: 'Enter a valid limit price' }); return }
    setStatus(null)
    setShowModal(true)
  }

  // Called by modal on confirm
  async function placeOrder() {
    setLoading(true)
    try {
      const body = { symbol, qty: Number(qty), side, type: orderType, portfolio_id: portfolioId || 1 }
      if (orderType === 'limit') body.limit_price = Number(limitPrice)
      const r = await api.post('/orders', body)
      setStatus({ ok: `Filled: ${r.data.id?.slice(0, 8) ?? ''}…` })
      setQty(''); setLimitPrice('')
      onOrderPlaced?.()
    } catch (err) {
      setStatus({ err: err.response?.data?.error || 'Order failed' })
    }
    setLoading(false)
    setShowModal(false)
  }

  const marketPrice    = quote ? (side === 'buy' ? quote.ask : quote.bid) : null
  const effectivePrice = (orderType === 'limit' && limitPrice) ? Number(limitPrice) : marketPrice
  const shares         = Number(qty)
  const estimatedCost  = shares > 0 && effectivePrice > 0 ? shares * effectivePrice : null
  const buyingPower    = account ? Number(account.buying_power) : null
  const overBudget     = side === 'buy' && estimatedCost != null && buyingPower != null && estimatedCost > buyingPower
  const fmt            = n => n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

  return (
    <>
    <div className="trade-panel">
      <PortfolioCard account={account} onReset={onReset} portfolioId={portfolioId} />

      {pos && (
        <PositionCard pos={pos} portfolioId={portfolioId} onOrderPlaced={onOrderPlaced} />
      )}

      <OrderBookCard symbol={symbol} quote={quote} />

      {isReal ? (
        <div className="tp-card" style={{ color: 'var(--t-3)', fontSize: 11, lineHeight: 1.5 }}>
          Read-only mode — switch to a simulation portfolio to place orders.
        </div>
      ) : (
        <div className="tp-card tp-order-card">
          <div className="tp-card-hd">Place Order</div>
          <form onSubmit={submit}>
            <div className="of-symbol mono">{symbol}</div>
            <div className="of-row">
              <div className="of-side-toggle">
                <button type="button" className={`of-side-btn${side === 'buy'  ? ' active-buy'  : ''}`} onClick={() => setSide('buy')}>BUY</button>
                <button type="button" className={`of-side-btn${side === 'sell' ? ' active-sell' : ''}`} onClick={() => setSide('sell')}>SELL</button>
              </div>
              <div className="of-type-toggle">
                <button type="button" className={`of-type-btn${orderType === 'market' ? ' active' : ''}`} onClick={() => setOrderType('market')}>Market</button>
                <button type="button" className={`of-type-btn${orderType === 'limit'  ? ' active' : ''}`} onClick={() => setOrderType('limit')}>Limit</button>
              </div>
            </div>
            <div className="of-inputs">
              <label>Shares
                <input type="number" min="1" step="1" value={qty}
                  onChange={e => setQty(e.target.value)} placeholder="0" />
              </label>
              {orderType === 'limit' && (
                <label>Limit Price
                  <input type="number" step="0.01" value={limitPrice}
                    onChange={e => setLimitPrice(e.target.value)} placeholder="0.00" />
                </label>
              )}
            </div>
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
                  <span className={`of-cost-value mono${overBudget ? ' err' : ''}`}>${fmt(estimatedCost)}</span>
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
        </div>
      )}
    </div>

    {showModal && (
      <OrderConfirmModal
        symbol={symbol}
        side={side}
        qty={Number(qty)}
        orderType={orderType}
        limitPrice={limitPrice}
        quote={quote}
        account={account}
        portfolioId={portfolioId}
        onConfirm={placeOrder}
        onCancel={() => setShowModal(false)}
      />
    )}
    </>
  )
}

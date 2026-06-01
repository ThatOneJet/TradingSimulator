import { useState } from 'react'
import api from '../api.js'

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
            <span className="tp-lbl" title={account.cash > (account.equity - (account.pnl_unrealized || 0)) ? 'Includes short sale proceeds held as collateral' : 'Available cash'}>
              CASH {account.cash > 100001 ? '⚠' : ''}
            </span>
            <span className="tp-val mono" style={{ fontSize: account.cash > 110000 ? 11 : undefined }}>
              ${fmt(account.cash)}
              {account.cash > 100001 && (
                <span style={{ display: 'block', fontSize: 8, color: 'var(--t-4)', fontWeight: 400 }}>incl. short proceeds</span>
              )}
            </span>
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
          <span className="tp-lbl">
            {pos.qty < 0 ? 'SHORT QTY' : 'SHARES'}
          </span>
          <span className="tp-val mono" style={{ color: pos.qty < 0 ? '#ff6a6a' : undefined }}>
            {pos.qty < 0 && <span style={{ fontSize: 8, background: 'rgba(255,71,111,0.15)', color: '#ff476f', border: '1px solid rgba(255,71,111,0.3)', borderRadius: 3, padding: '1px 4px', marginRight: 5 }}>SHORT</span>}
            {Math.abs(pos.qty).toFixed(4)}
          </span>
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

export default function TradePanel({ symbol, account, portfolioId, quote, onReset }) {
  return (
    <div className="trade-panel">
      <PortfolioCard account={account} onReset={onReset} portfolioId={portfolioId} />
      <OrderBookCard symbol={symbol} quote={quote} />
    </div>
  )
}

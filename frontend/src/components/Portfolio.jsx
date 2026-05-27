import { useState } from 'react'
import api from '../api.js'

export default function Portfolio({ account, onReset, portfolioId }) {
  const [resetting, setResetting] = useState(false)
  const [msg,       setMsg]       = useState('')

  async function handleReset() {
    if (!window.confirm('Reset account to $100,000 and clear all positions and trade history?')) return
    setResetting(true)
    setMsg('')
    try {
      const r = await api.post('/account/reset', { portfolio_id: portfolioId || 1 })
      setMsg(r.data.message || 'Account reset.')
      onReset?.()
    } catch {
      setMsg('Reset failed.')
    } finally {
      setResetting(false)
      setTimeout(() => setMsg(''), 5000)
    }
  }

  if (!account) return (
    <div className="widget" style={{ minHeight: 90 }}>
      <div style={{ height: 12, width: '60%', background: 'var(--hairline-2)', borderRadius: 4, marginBottom: 8 }} />
      <div style={{ height: 12, width: '40%', background: 'var(--hairline-2)', borderRadius: 4 }} />
    </div>
  )

  const pnlColor = account.pnl_day >= 0 ? 'var(--ok)' : 'var(--err)'
  const fmt = (n) => Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

  return (
    <div className="widget">
      <div className="widget-hd">
        Portfolio
        <button className="pf-reset-btn" onClick={handleReset} disabled={resetting} style={{ marginLeft: 'auto' }}>
          {resetting ? '…' : 'Reset'}
        </button>
      </div>
      <div className="pf-metrics">
        <div className="pf-metric">
          <span className="lbl">EQUITY</span>
          <span className="val mono">${fmt(account.equity)}</span>
        </div>
        <div className="pf-metric">
          <span className="lbl">CASH</span>
          <span className="val mono">${fmt(account.cash)}</span>
        </div>
        <div className="pf-metric">
          <span className="lbl">DAY P&L</span>
          <span className="val mono" style={{ color: pnlColor }}>
            {account.pnl_day >= 0 ? '+' : ''}${fmt(account.pnl_day)}
          </span>
        </div>
        <div className="pf-metric">
          <span className="lbl">BUYING PWR</span>
          <span className="val mono">${fmt(account.buying_power)}</span>
        </div>
      </div>
      {msg && <div className="pf-msg">{msg}</div>}
    </div>
  )
}

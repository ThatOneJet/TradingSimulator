import { useState } from 'react'
import api from '../api.js'

export default function Portfolio({ account, onReset }) {
  const [resetting, setResetting] = useState(false)
  const [msg,       setMsg]       = useState('')

  async function handleReset() {
    if (!window.confirm('Liquidate all positions and cancel all open orders?\n\nNote: To reset cash back to $100k, visit paper.alpaca.markets → Account → Reset.')) return
    setResetting(true)
    setMsg('')
    try {
      const r = await api.post('/account/reset')
      setMsg(r.data.message || 'Account liquidated.')
      onReset?.()
    } catch (e) {
      setMsg(e?.response?.data?.description || 'Reset failed — check Alpaca keys.')
    } finally {
      setResetting(false)
      setTimeout(() => setMsg(''), 6000)
    }
  }

  if (!account) return <div className="card portfolio skeleton-card" />

  const pnlColor = account.pnl_day >= 0 ? 'var(--ok)' : 'var(--err)'
  const fmt = (n, decimals = 2) =>
    Number(n).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })

  return (
    <div className="card portfolio">
      <div className="card-header">
        Portfolio
        <button className="pf-reset-btn" onClick={handleReset} disabled={resetting} title="Liquidate all positions">
          {resetting ? '…' : 'Liquidate All'}
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

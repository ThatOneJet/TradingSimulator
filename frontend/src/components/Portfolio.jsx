import { useState } from 'react'
import api from '../api.js'
import ConfirmModal from './ConfirmModal.jsx'

export default function Portfolio({ account, onReset, portfolioId }) {
  const [resetting,    setResetting]    = useState(false)
  const [msg,          setMsg]          = useState('')
  const [resetModal,   setResetModal]   = useState(false)

  async function handleReset() {
    setResetting(true)
    setResetModal(false)
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

  const isReal   = account.is_real
  const fmt = (n) => Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  const pnl      = isReal ? account.pnl : account.pnl_day
  const pnlColor = pnl != null && pnl >= 0 ? 'var(--ok)' : 'var(--err)'

  return (
    <div className="widget">
      <div className="widget-hd">
        {isReal ? 'Real Holdings' : 'Portfolio'}
        {!isReal && (
          <button className="pf-reset-btn" onClick={() => setResetModal(true)} disabled={resetting} style={{ marginLeft: 'auto' }}>
            {resetting ? '…' : 'Reset'}
          </button>
        )}
        {resetModal && (
          <ConfirmModal
            message="Reset account to $100,000?"
            detail="All positions and trade history will be cleared."
            confirmLabel="Reset"
            danger
            onConfirm={handleReset}
            onCancel={() => setResetModal(false)}
          />
        )}
        {isReal && (
          <span style={{ marginLeft: 'auto', fontSize: 9, color: 'var(--ok)', fontFamily: 'var(--font-mono)', opacity: 0.8 }}>
            READ-ONLY
          </span>
        )}
      </div>
      <div className="pf-metrics">
        <div className="pf-metric">
          <span className="lbl">MARKET VALUE</span>
          <span className="val mono">${fmt(account.equity)}</span>
        </div>
        {isReal ? (
          <div className="pf-metric">
            <span className="lbl">COST BASIS</span>
            <span className="val mono">${fmt(account.initial_cost ?? 0)}</span>
          </div>
        ) : (
          <div className="pf-metric">
            <span className="lbl">CASH</span>
            <span className="val mono">${fmt(account.cash)}</span>
          </div>
        )}
        <div className="pf-metric">
          <span className="lbl">{isReal ? 'TOTAL P&L' : 'DAY P&L'}</span>
          <span className="val mono" style={{ color: pnlColor }}>
            {pnl != null ? `${pnl >= 0 ? '+' : ''}$${fmt(pnl)}` : '—'}
          </span>
        </div>
        {isReal ? (
          <div className="pf-metric">
            <span className="lbl">RETURN</span>
            <span className="val mono" style={{ color: pnlColor }}>
              {account.pnl_pct != null ? `${account.pnl_pct >= 0 ? '+' : ''}${Number(account.pnl_pct).toFixed(2)}%` : '—'}
            </span>
          </div>
        ) : (
          <div className="pf-metric">
            <span className="lbl">BUYING PWR</span>
            <span className="val mono">${fmt(account.buying_power)}</span>
          </div>
        )}
      </div>
      {msg && <div className="pf-msg">{msg}</div>}
    </div>
  )
}

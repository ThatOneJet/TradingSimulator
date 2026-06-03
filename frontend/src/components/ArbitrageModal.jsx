import { useState, useEffect } from 'react'
import api from '../api.js'

// ── Helpers ───────────────────────────────────────────────────────────────────

function money(n) {
  if (n == null || isNaN(n)) return '—'
  const v = Number(n)
  return (v < 0 ? '-$' : '$') + Math.abs(v).toFixed(2)
}

function num(n, d = 4) {
  return (n == null || isNaN(n)) ? '—' : Number(n).toFixed(d)
}

function fmtAbsTime(ts) {
  if (!ts) return ''
  const d = new Date(ts.endsWith('Z') ? ts : ts + 'Z')
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    + '  ' + d.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

const TYPE_CFG = {
  triangular:     { color: '#b39dff', glyph: '🔺', label: 'TRIANGULAR'    },
  cross_exchange: { color: '#4ad9ff', glyph: '⇄',  label: 'CROSS-EXCHANGE' },
}

const overlay = {
  position: 'fixed', inset: 0, zIndex: 9999,
  background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(3px)',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  padding: 16,
}

function Chip({ label, color = '#8899aa' }) {
  return (
    <span style={{
      fontSize: 8.5, fontFamily: 'var(--font-mono)', fontWeight: 700,
      color, border: `1px solid ${color}44`, borderRadius: 4,
      padding: '2px 7px', letterSpacing: '0.05em', whiteSpace: 'nowrap',
    }}>
      {label}
    </span>
  )
}

// ── Modal ─────────────────────────────────────────────────────────────────────

export default function ArbitrageModal({ tradeId, onClose }) {
  const [trade,   setTrade]   = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(false)

  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose?.() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  useEffect(() => {
    if (tradeId == null) return
    let cancelled = false
    setLoading(true); setError(false)
    api.get(`/arbitrage/trades/${tradeId}`)
      .then(r => { if (!cancelled) { setTrade(r.data); setLoading(false) } })
      .catch(() => { if (!cancelled) { setError(true); setLoading(false) } })
    return () => { cancelled = true }
  }, [tradeId])

  const cfg      = trade ? (TYPE_CFG[trade.type] ?? TYPE_CFG.cross_exchange) : TYPE_CFG.cross_exchange
  const profit   = trade?.profit ?? 0
  const profCol  = profit >= 0 ? 'var(--ok)' : 'var(--err)'
  const path     = trade?.path || []

  return (
    <div style={overlay} onClick={(e) => { if (e.target === e.currentTarget) onClose?.() }}>
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: '#141922',
          border: '1px solid rgba(140,170,220,0.15)',
          borderRadius: 10,
          width: '100%', minWidth: 480, maxWidth: 640,
          maxHeight: '88vh',
          display: 'flex', flexDirection: 'column',
          boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
          fontFamily: 'var(--font-sans)',
          overflow: 'hidden',
        }}
      >
        {/* ── Header ── */}
        <div style={{
          display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
          gap: 12, padding: '14px 18px',
          borderBottom: '1px solid rgba(140,170,220,0.10)', flexShrink: 0,
        }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}>
              <span style={{
                fontSize: 9, fontFamily: 'var(--font-mono)', fontWeight: 700,
                color: cfg.color, border: `1px solid ${cfg.color}44`, borderRadius: 4,
                padding: '2px 7px', letterSpacing: '0.05em',
              }}>
                {cfg.glyph} {cfg.label}
              </span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 800, color: 'var(--t-1)' }}>
                {trade?.start_asset ?? '—'} <span style={{ color: 'var(--t-4)' }}>→</span> {trade?.end_asset ?? '—'}
              </span>
            </div>
            {trade && (
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 22, fontWeight: 800, color: profCol, lineHeight: 1 }}>
                  {profit >= 0 ? '+' : ''}{money(profit)}
                </span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 700, color: profCol }}>
                  {(trade.profit_pct ?? 0) >= 0 ? '+' : ''}{num(trade.profit_pct, 2)}%
                </span>
                <span style={{ fontSize: 9, color: 'var(--t-4)', fontFamily: 'var(--font-mono)' }}>
                  {fmtAbsTime(trade.created_at)}
                </span>
              </div>
            )}
            {trade?.exchanges?.length > 0 && (
              <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginTop: 8 }}>
                {trade.exchanges.map((ex, i) => <Chip key={i} label={ex} color="#8899aa" />)}
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', color: '#475061', cursor: 'pointer', fontSize: 16, padding: '0 4px', lineHeight: 1, flexShrink: 0 }}
          >✕</button>
        </div>

        {/* ── Body — leg-by-leg path ── */}
        <div style={{ overflowY: 'auto', flex: 1, padding: '14px 18px' }}>
          {loading && (
            <div style={{ textAlign: 'center', padding: '24px 0', color: 'var(--t-4)', fontSize: 11 }}>Loading…</div>
          )}
          {error && !loading && (
            <div style={{ textAlign: 'center', padding: '24px 0', color: 'var(--err)', fontSize: 11 }}>
              Failed to load trade.
            </div>
          )}

          {!loading && !error && path.length === 0 && (
            <div style={{ textAlign: 'center', padding: '24px 0', color: 'var(--t-4)', fontSize: 11 }}>
              No path data for this trade.
            </div>
          )}

          {!loading && !error && path.length > 0 && (
            <div>
              {path.map((leg, i) => {
                const isLast    = i === path.length - 1
                const actionUp  = String(leg.action || '').toUpperCase()
                const actionCol = actionUp === 'BUY' ? 'var(--ok)' : actionUp === 'SELL' ? 'var(--err)' : '#4ad9ff'
                return (
                  <div key={leg.step ?? i} style={{ display: 'flex', gap: 12 }}>
                    {/* Step indicator + connector */}
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flexShrink: 0 }}>
                      <div style={{
                        width: 26, height: 26, borderRadius: '50%', flexShrink: 0,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        background: `${cfg.color}1a`, border: `1px solid ${cfg.color}55`,
                        color: cfg.color, fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 800,
                      }}>
                        {leg.step ?? i + 1}
                      </div>
                      {!isLast && (
                        <div style={{ width: 1, flex: 1, minHeight: 22, background: 'rgba(140,170,220,0.18)', margin: '2px 0' }} />
                      )}
                    </div>

                    {/* Leg card */}
                    <div style={{
                      flex: 1, minWidth: 0, marginBottom: isLast ? 0 : 10,
                      background: 'rgba(140,170,220,0.04)',
                      border: '1px solid rgba(140,170,220,0.10)',
                      borderRadius: 8, padding: '10px 12px',
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                          <span style={{
                            fontSize: 8.5, fontFamily: 'var(--font-mono)', fontWeight: 700,
                            color: actionCol, border: `1px solid ${actionCol}44`, borderRadius: 4,
                            padding: '1px 6px', letterSpacing: '0.05em',
                          }}>
                            {actionUp || '—'}
                          </span>
                          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 700, color: 'var(--t-1)' }}>
                            {leg.from_asset ?? '—'} <span style={{ color: 'var(--t-4)' }}>→</span> {leg.to_asset ?? '—'}
                          </span>
                        </div>
                        {leg.exchange && <Chip label={leg.exchange} color="#8899aa" />}
                      </div>

                      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'baseline' }}>
                        <span style={{ fontSize: 9.5, color: 'var(--t-3)', fontFamily: 'var(--font-mono)' }}>
                          <span style={{ color: 'var(--t-4)' }}>price </span>{num(leg.price, 6)}
                        </span>
                        {leg.fee_pct != null && (
                          <span style={{ fontSize: 9.5, color: 'var(--err)', fontFamily: 'var(--font-mono)' }}>
                            -{num(leg.fee_pct, 3)}%
                          </span>
                        )}
                        <span style={{ fontSize: 9.5, color: 'var(--t-2)', fontFamily: 'var(--font-mono)', marginLeft: 'auto' }}>
                          {money(leg.value_before)} <span style={{ color: 'var(--t-4)' }}>→</span>{' '}
                          <span style={{ fontWeight: 700 }}>{money(leg.value_after)}</span>
                        </span>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* ── Footer summary ── */}
        {trade && !loading && !error && (
          <div style={{
            flexShrink: 0, padding: '12px 18px',
            borderTop: '1px solid rgba(140,170,220,0.10)',
            background: 'rgba(140,170,220,0.03)',
          }}>
            <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', alignItems: 'baseline' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                <span style={{ fontSize: 7.5, color: 'var(--t-4)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>Start</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700, color: 'var(--t-2)' }}>{money(trade.start_value)}</span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                <span style={{ fontSize: 7.5, color: 'var(--t-4)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>End</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700, color: 'var(--t-2)' }}>{money(trade.end_value)}</span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                <span style={{ fontSize: 7.5, color: 'var(--t-4)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>Net Profit</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700, color: profCol }}>
                  {profit >= 0 ? '+' : ''}{money(profit)} ({(trade.profit_pct ?? 0) >= 0 ? '+' : ''}{num(trade.profit_pct, 2)}%)
                </span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                <span style={{ fontSize: 7.5, color: 'var(--t-4)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>Legs</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700, color: 'var(--t-2)' }}>{trade.num_legs ?? path.length}</span>
              </div>
            </div>
            {trade.notes && (
              <div style={{ fontSize: 9.5, color: 'var(--t-4)', lineHeight: 1.55, marginTop: 10, paddingTop: 8, borderTop: '1px solid rgba(140,170,220,0.08)' }}>
                {trade.notes}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

import { useState } from 'react'

const SCENARIO_KEYS = ['-15%', '-10%', '-5%', '0%', '+5%', '+10%', '+15%']

export default function OptionProjectionWidget({ option, underlyingPrice, onAddToPortfolio, onClose, compact = false }) {
  if (!option) return null

  const last = option.last || ((option.bid || 0) + (option.ask || 0)) / 2 || 0
  const breakeven = option.type === 'calls'
    ? (option.strike || 0) + last
    : (option.strike || 0) - last

  const greeks = option.greeks || {}
  const scenarios = option.scenarios || {}

  const fmt = (v, decimals = 4) => v != null && v !== 0 ? v.toFixed(decimals) : '—'
  const fmtPct = (v) => v != null && v !== 0 ? `${(v * 100).toFixed(1)}%` : '—'
  const fmtPrice = (v) => v != null ? `$${v.toFixed(2)}` : '—'

  const ivPct = option.iv ? `${option.iv.toFixed(1)}%` : '—'
  const dte = option.days_to_expiry != null ? `${option.days_to_expiry}d` : ''
  const headerTitle = `${option.type === 'calls' ? 'CALL' : 'PUT'} $${(option.strike || 0).toFixed(2)}${dte ? ` · ${dte}` : ''}${ivPct !== '—' ? ` · IV ${ivPct}` : ''}`

  // ── Size tokens ──────────────────────────────────────────────────────────────
  const fs = {
    header: compact ? '11px' : '13px',
    close:  compact ? '13px' : '16px',
    label:  compact ? '8px'  : '10px',
    row:    compact ? '10px' : '12px',
    scenKey:compact ? '9px'  : '11px',
    btn:    compact ? '11px' : '13px',
  }
  const pad = {
    header: compact ? '7px 10px'  : '10px 14px',
    body:   compact ? '8px 10px'  : '12px 14px',
    btn:    compact ? '5px 0'     : '8px 0',
    footer: compact ? '7px 10px'  : '10px 14px',
  }

  const greekRows = [
    ['Δ Delta',  fmt(greeks.delta,   4)],
    ['Γ Gamma',  fmt(greeks.gamma,   5)],
    ['Θ Theta',  fmt(greeks.theta,   4)],
    ['ν Vega',   fmt(greeks.vega,    4)],
    ['Prob ITM', fmtPct(greeks.prob_itm)],
    ['Breakeven',fmtPrice(breakeven)],
  ]

  return (
    <div style={{
      background: '#141925',
      border: '1px solid rgba(140,170,220,0.18)',
      borderRadius: compact ? '7px' : '10px',
      overflow: 'hidden',
      marginTop: compact ? '8px' : '12px',
      fontFamily: 'var(--font-sans)',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: pad.header,
        background: 'rgba(140,170,220,0.05)',
        borderBottom: '1px solid rgba(140,170,220,0.1)',
      }}>
        <span style={{ fontSize: fs.header, fontWeight: 600, color: '#e6ecf5', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, marginRight: 6 }}>
          {headerTitle}
        </span>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'rgba(140,170,220,0.5)', cursor: 'pointer', fontSize: fs.close, padding: '0 2px', lineHeight: 1, flexShrink: 0 }}>×</button>
      </div>

      {/* Body */}
      {compact ? (
        /* Compact: single-column, Greeks + Scenarios stacked */
        <div style={{ borderBottom: '1px solid rgba(140,170,220,0.08)' }}>
          {/* Greeks */}
          <div style={{ padding: pad.body, borderBottom: '1px solid rgba(140,170,220,0.06)' }}>
            <div style={{ fontSize: fs.label, letterSpacing: '0.06em', color: '#6b7689', textTransform: 'uppercase', marginBottom: 5 }}>Greeks</div>
            {greekRows.map(([label, val]) => (
              <div key={label} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0', fontSize: fs.row }}>
                <span style={{ color: '#6b7689' }}>{label}</span>
                <span style={{ color: '#e6ecf5', fontFamily: 'var(--font-mono)' }}>{val}</span>
              </div>
            ))}
          </div>

          {/* Scenarios */}
          <div style={{ padding: pad.body }}>
            <div style={{ fontSize: fs.label, letterSpacing: '0.06em', color: '#6b7689', textTransform: 'uppercase', marginBottom: 5 }}>Scenarios</div>
            {SCENARIO_KEYS.map(key => {
              const val = scenarios[key]
              const chgNum = parseInt(key)
              const isProfit = option.type === 'calls' ? chgNum > 0 : chgNum < 0
              const isLoss   = option.type === 'calls' ? chgNum < 0 : chgNum > 0
              const color = val == null ? 'rgba(140,170,220,0.3)' : isProfit ? '#3ddc97' : isLoss ? '#ff476f' : '#f5b342'
              return (
                <div key={key} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0', fontSize: fs.row }}>
                  <span style={{ color: 'rgba(140,170,220,0.5)', fontFamily: 'var(--font-mono)', fontSize: fs.scenKey }}>{key}</span>
                  <span style={{ color, fontFamily: 'var(--font-mono)' }}>{val != null ? `$${val.toFixed(2)}` : '—'}</span>
                </div>
              )
            })}
          </div>
        </div>
      ) : (
        /* Full-width: 2-column grid */
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', borderBottom: '1px solid rgba(140,170,220,0.08)' }}>
          {/* Left: Greeks */}
          <div style={{ padding: pad.body, borderRight: '1px solid rgba(140,170,220,0.08)' }}>
            <div style={{ fontSize: fs.label, letterSpacing: '0.06em', color: '#6b7689', textTransform: 'uppercase', marginBottom: '8px' }}>Greeks</div>
            {[
              ['Δ Delta', fmt(greeks.delta, 4)],
              ['Γ Gamma', fmt(greeks.gamma, 5)],
              ['Θ Theta', fmt(greeks.theta, 4)],
              ['ν Vega',  fmt(greeks.vega,  4)],
            ].map(([label, val]) => (
              <div key={label} style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', fontSize: fs.row }}>
                <span style={{ color: '#6b7689' }}>{label}</span>
                <span style={{ color: '#e6ecf5', fontFamily: 'var(--font-mono)' }}>{val}</span>
              </div>
            ))}
            <div style={{ height: '1px', background: 'rgba(140,170,220,0.08)', margin: '8px 0' }} />
            {[
              ['Prob ITM',  fmtPct(greeks.prob_itm)],
              ['Breakeven', fmtPrice(breakeven)],
            ].map(([label, val]) => (
              <div key={label} style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', fontSize: fs.row }}>
                <span style={{ color: '#6b7689' }}>{label}</span>
                <span style={{ color: '#e6ecf5', fontFamily: 'var(--font-mono)' }}>{val}</span>
              </div>
            ))}
          </div>

          {/* Right: Scenarios */}
          <div style={{ padding: pad.body }}>
            <div style={{ fontSize: fs.label, letterSpacing: '0.06em', color: '#6b7689', textTransform: 'uppercase', marginBottom: '8px' }}>Stock Price Scenarios</div>
            {SCENARIO_KEYS.map(key => {
              const val = scenarios[key]
              const chgNum = parseInt(key)
              const isProfit = option.type === 'calls' ? chgNum > 0 : chgNum < 0
              const isLoss   = option.type === 'calls' ? chgNum < 0 : chgNum > 0
              const color = val == null ? 'rgba(140,170,220,0.3)' : isProfit ? '#3ddc97' : isLoss ? '#ff476f' : '#f5b342'
              return (
                <div key={key} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0', fontSize: fs.row }}>
                  <span style={{ color: 'rgba(140,170,220,0.5)', fontFamily: 'var(--font-mono)', fontSize: fs.scenKey }}>{key}</span>
                  <span style={{ color, fontFamily: 'var(--font-mono)' }}>{val != null ? `$${val.toFixed(2)}` : '—'}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Footer */}
      <div style={{ padding: pad.footer }}>
        <button
          onClick={() => onAddToPortfolio && onAddToPortfolio(option)}
          style={{
            width: '100%', padding: pad.btn, border: 'none',
            borderRadius: compact ? '4px' : '6px',
            background: '#ff6a1a', color: '#fff', cursor: 'pointer',
            fontSize: fs.btn, fontWeight: 600,
          }}
        >
          Add to Portfolio
        </button>
      </div>
    </div>
  )
}

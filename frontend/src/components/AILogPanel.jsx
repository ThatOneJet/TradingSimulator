import { useState, useEffect, useRef } from 'react'
import api from '../api.js'

const MARKET_STATE_CFG = {
  panic:              { color: '#ff1a4e', label: 'PANIC'         },
  overbought_extreme: { color: '#ff476f', label: 'OVERBOUGHT'    },
  oversold_extreme:   { color: '#3ddc97', label: 'OVERSOLD'      },
  breakout:           { color: '#f5b342', label: 'BREAKOUT'      },
  trending_up:        { color: '#3ddc97', label: 'TRENDING UP'   },
  trending_down:      { color: '#ff476f', label: 'TRENDING DOWN' },
  accumulation:       { color: '#4ad9ff', label: 'ACCUM'         },
  ranging:            { color: '#8899aa', label: 'RANGING'       },
  mild_uptrend:       { color: '#5ee8a9', label: 'MILD UP'       },
  mild_downtrend:     { color: '#ff6a6a', label: 'MILD DOWN'     },
  neutral:            { color: '#6b7689', label: 'NEUTRAL'       },
}

function f(n, d = 2) { return (n == null || isNaN(n)) ? '—' : Number(n).toFixed(d) }

function fmtTime(ts) {
  if (!ts) return ''
  const d   = new Date(ts.endsWith('Z') ? ts : ts + 'Z')
  const now = new Date()
  const diff = (now - d) / 1000
  if (diff < 60)    return `${Math.floor(diff)}s ago`
  if (diff < 3600)  return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

function fmtAbsTime(ts) {
  if (!ts) return ''
  const d = new Date(ts.endsWith('Z') ? ts : ts + 'Z')
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    + '  ' + d.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

// ── Countdown to next scan ────────────────────────────────────────────────────

function NextScanCountdown({ lastScanTs, intervalSec = 90 }) {
  const [secsLeft, setSecsLeft] = useState(null)

  useEffect(() => {
    if (!lastScanTs) return
    const tick = () => {
      const elapsed = (Date.now() - new Date(lastScanTs.endsWith('Z') ? lastScanTs : lastScanTs + 'Z').getTime()) / 1000
      setSecsLeft(Math.max(0, Math.round(intervalSec - elapsed)))
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [lastScanTs, intervalSec])

  if (secsLeft === null) return null
  const color = secsLeft <= 10 ? '#3ddc97' : secsLeft <= 30 ? '#f5b342' : '#475061'
  return (
    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color }}>
      next {secsLeft}s
    </span>
  )
}

// ── Scan detail modal ─────────────────────────────────────────────────────────

function ScanModal({ run, onClose }) {
  const [batchOpen, setBatchOpen] = useState(false)
  if (!run) return null

  const allBought = run.bought_json  || []
  const allSold   = run.sold_json    || []
  const batch     = run.batch_json   || []
  const skipped   = run.skipped_json || []
  // Split by type field (new) or fall back to treating all as buy/sell
  // For new records: use explicit type field
  // For old records without type: use score direction (negative score in bought_json = was a short)
  const bought   = allBought.filter(b => b.type === 'buy'   || (!b.type && (b.score ?? 0) >= 0))
  const shorted  = allBought.filter(b => b.type === 'short' || (!b.type && (b.score ?? 0) < 0))
  const sold     = allSold.filter(s => s.type === 'sell'   || (!s.type && !(s.reason || '').toLowerCase().includes('cover')))
  const covered  = allSold.filter(s => s.type === 'cover'  || (!s.type && (s.reason || '').toLowerCase().includes('cover')))

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 9999,
        background: 'rgba(0,0,8,0.82)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 16,
      }}
      onClick={onClose}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: '#0b0f1a',
          border: '1px solid rgba(140,170,220,0.14)',
          borderRadius: 10,
          width: '100%', maxWidth: 480,
          maxHeight: '88vh',
          display: 'flex', flexDirection: 'column',
          boxShadow: '0 24px 80px rgba(0,0,0,0.7)',
          overflow: 'hidden',
        }}
      >
        {/* Modal header */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '12px 16px',
          borderBottom: '1px solid rgba(140,170,220,0.10)',
          flexShrink: 0,
        }}>
          <div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700, color: 'var(--t-1)', letterSpacing: '0.06em' }}>
              SCAN #{run.id}
            </div>
            <div style={{ fontSize: 9, color: 'var(--t-4)', marginTop: 2 }}>{fmtAbsTime(run.created_at)}</div>
          </div>
          {/* Stats row */}
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <Chip label={`${run.scanned} scanned`}  color="#8899aa" />
            {run.mode === 'crypto_forex' && <Chip label="CRYPTO/FX" color="#4ad9ff" />}
            {run.skip_reason === 'max_positions' && <Chip label="MAX POS" color="#f5b342" />}
            {run.skip_reason === 'low_cash'      && <Chip label="LOW CASH" color="#f5b342" />}
            {bought.length   > 0 && <Chip label={`${bought.length} bought`}    color="#3ddc97" />}
            {shorted.length  > 0 && <Chip label={`${shorted.length} shorted`}  color="#ff6a6a" />}
            {sold.length     > 0 && <Chip label={`${sold.length} sold`}        color="#ff476f" />}
            {covered.length  > 0 && <Chip label={`${covered.length} covered`}  color="#4ad9ff" />}
            {skipped.length  > 0 && <Chip label={`${skipped.length} skipped`}  color="#f5b342" />}
            {run.error_count > 0 && <Chip label={`${run.error_count} no data`} color="#ff476f" />}
          </div>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', color: '#475061', cursor: 'pointer', fontSize: 16, padding: '0 4px', lineHeight: 1 }}
          >✕</button>
        </div>

        {/* Modal body */}
        <div style={{ overflowY: 'auto', flex: 1, padding: '12px 16px' }}>

          {/* Bought */}
          {bought.length > 0 && (
            <section style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 9, fontWeight: 700, color: '#3ddc97', letterSpacing: '0.12em', textTransform: 'uppercase', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 5 }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#3ddc97', display: 'inline-block' }} />
                Bought
              </div>
              {bought.map((b, i) => {
                const stCfg = MARKET_STATE_CFG[b.market_state] ?? MARKET_STATE_CFG.neutral
                return (
                  <div key={i} style={{
                    background: 'rgba(61,220,151,0.04)', border: '1px solid rgba(61,220,151,0.12)',
                    borderRadius: 7, padding: '10px 12px', marginBottom: 8,
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 800, color: '#3ddc97' }}>{b.symbol}</span>
                      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                        <span style={{
                          fontSize: 8, fontFamily: 'var(--font-mono)', padding: '1px 5px',
                          border: `1px solid ${stCfg.color}44`, borderRadius: 3, color: stCfg.color,
                        }}>{stCfg.label}</span>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700, color: '#3ddc97' }}>
                          {(b.score ?? 0) >= 0 ? '+' : ''}{f(b.score, 1)}
                        </span>
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: 14, marginBottom: b.summary ? 6 : 0 }}>
                      <span style={{ fontSize: 10, color: 'var(--t-3)', fontFamily: 'var(--font-mono)' }}>${f(b.price)}</span>
                      <span style={{ fontSize: 10, color: 'var(--t-4)', fontFamily: 'var(--font-mono)' }}>×{f(b.shares, 4)}</span>
                    </div>
                    {b.summary && (
                      <div style={{ fontSize: 9.5, color: 'var(--t-3)', lineHeight: 1.55, borderTop: '1px solid rgba(61,220,151,0.08)', paddingTop: 6, marginTop: 2 }}>
                        {b.summary}
                      </div>
                    )}
                  </div>
                )
              })}
            </section>
          )}

          {/* Sold */}
          {sold.length > 0 && (
            <section style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 9, fontWeight: 700, color: '#ff476f', letterSpacing: '0.12em', textTransform: 'uppercase', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 5 }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#ff476f', display: 'inline-block' }} />
                Sold
              </div>
              {sold.map((s, i) => {
                const stCfg = MARKET_STATE_CFG[s.market_state] ?? MARKET_STATE_CFG.neutral
                const reasonLabel = { sell_signal: 'Sell Signal', stop_loss: 'Stop Loss', take_profit: 'Take Profit' }[s.reason] ?? s.reason ?? '—'
                const reasonColor = s.reason === 'take_profit' ? '#3ddc97' : s.reason === 'stop_loss' ? '#f5b342' : '#ff476f'
                return (
                  <div key={i} style={{
                    background: 'rgba(255,71,111,0.04)', border: '1px solid rgba(255,71,111,0.12)',
                    borderRadius: 7, padding: '10px 12px', marginBottom: 8,
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 800, color: '#ff6a6a' }}>{s.symbol}</span>
                      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                        <span style={{ fontSize: 8, fontFamily: 'var(--font-mono)', color: reasonColor, border: `1px solid ${reasonColor}44`, borderRadius: 3, padding: '1px 5px' }}>
                          {reasonLabel}
                        </span>
                        {s.market_state && (
                          <span style={{ fontSize: 8, fontFamily: 'var(--font-mono)', padding: '1px 5px', border: `1px solid ${stCfg.color}44`, borderRadius: 3, color: stCfg.color }}>{stCfg.label}</span>
                        )}
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700, color: s.score >= 0 ? '#3ddc97' : '#ff476f' }}>
                          {s.score >= 0 ? '+' : ''}{f(s.score, 1)}
                        </span>
                      </div>
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--t-3)', fontFamily: 'var(--font-mono)', marginTop: 4 }}>${f(s.price)}</div>
                  </div>
                )
              })}
            </section>
          )}

          {/* Skipped — risk gates (low confidence, heat cap, cluster cap) */}
          {skipped.length > 0 && (
            <section style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 9, fontWeight: 700, color: '#f5b342', letterSpacing: '0.12em', textTransform: 'uppercase', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 5 }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#f5b342', display: 'inline-block' }} />
                Skipped — risk gate
              </div>
              {skipped.map((s, i) => (
                <div key={i} style={{ fontSize: 9.5, color: 'var(--t-3)', padding: '2px 0', fontFamily: 'var(--font-mono)' }}>
                  ⊘ {s}
                </div>
              ))}
            </section>
          )}

          {/* Shorted */}
          {shorted.length > 0 && (
            <section style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 9, fontWeight: 700, color: '#ff6a6a', letterSpacing: '0.12em', textTransform: 'uppercase', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 5 }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#ff6a6a', display: 'inline-block' }} />
                Shorted
              </div>
              {shorted.map((b, i) => {
                const stCfg = MARKET_STATE_CFG[b.market_state] ?? MARKET_STATE_CFG.neutral
                return (
                  <div key={i} style={{ background: 'rgba(255,106,106,0.04)', border: '1px solid rgba(255,106,106,0.12)', borderRadius: 7, padding: '10px 12px', marginBottom: 8 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 800, color: '#ff6a6a' }}>{b.symbol}</span>
                      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                        <span style={{ fontSize: 8, fontFamily: 'var(--font-mono)', padding: '1px 5px', border: `1px solid ${stCfg.color}44`, borderRadius: 3, color: stCfg.color }}>{stCfg.label}</span>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700, color: '#ff6a6a' }}>{f(b.score, 1)}</span>
                      </div>
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--t-3)', fontFamily: 'var(--font-mono)', marginBottom: b.summary ? 6 : 0 }}>${f(b.price)} × {f(b.shares, 4)}</div>
                    {b.summary && <div style={{ fontSize: 9.5, color: 'var(--t-3)', lineHeight: 1.55, borderTop: '1px solid rgba(255,106,106,0.08)', paddingTop: 6, marginTop: 2 }}>{b.summary}</div>}
                  </div>
                )
              })}
            </section>
          )}

          {/* Covered */}
          {covered.length > 0 && (
            <section style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 9, fontWeight: 700, color: '#4ad9ff', letterSpacing: '0.12em', textTransform: 'uppercase', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 5 }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#4ad9ff', display: 'inline-block' }} />
                Covered
              </div>
              {covered.map((s, i) => {
                const stCfg = MARKET_STATE_CFG[s.market_state] ?? MARKET_STATE_CFG.neutral
                const reasonLabel = { cover_signal: 'Cover Signal', stop_loss: 'Stop Loss', take_profit: 'Take Profit' }[s.reason] ?? s.reason ?? '—'
                return (
                  <div key={i} style={{ background: 'rgba(74,217,255,0.04)', border: '1px solid rgba(74,217,255,0.12)', borderRadius: 7, padding: '10px 12px', marginBottom: 8 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 800, color: '#4ad9ff' }}>{s.symbol}</span>
                      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                        <span style={{ fontSize: 8, fontFamily: 'var(--font-mono)', padding: '1px 5px', border: `1px solid ${stCfg.color}44`, borderRadius: 3, color: stCfg.color }}>{stCfg.label}</span>
                        <span style={{ fontSize: 8, fontFamily: 'var(--font-mono)', padding: '1px 5px', border: '1px solid rgba(74,217,255,0.3)', borderRadius: 3, color: '#4ad9ff' }}>{reasonLabel}</span>
                      </div>
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--t-3)', fontFamily: 'var(--font-mono)' }}>${f(s.price)}</div>
                  </div>
                )
              })}
            </section>
          )}

          {/* No action */}
          {bought.length === 0 && shorted.length === 0 && sold.length === 0 && covered.length === 0 && (
            <div style={{ textAlign: 'center', padding: '12px 0 16px', color: 'var(--t-4)', fontSize: 11 }}>
              No trades executed this scan.
            </div>
          )}

          {/* Scanned batch — collapsible */}
          {batch.length > 0 && (
            <section>
              <button
                onClick={() => setBatchOpen(o => !o)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 6, width: '100%',
                  background: 'none', border: 'none', cursor: 'pointer',
                  padding: '4px 0 8px', textAlign: 'left',
                }}
              >
                <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--t-3)', letterSpacing: '0.12em', textTransform: 'uppercase' }}>
                  Scanned Batch ({batch.length})
                  {batch.filter(b => b.error).length > 0 && (
                    <span style={{ color: '#ff476f', fontWeight: 400, marginLeft: 6 }}>
                      · {batch.filter(b => !b.error).length} w/ data · {batch.filter(b => b.error).length} no data
                    </span>
                  )}
                </span>
                <span style={{ fontSize: 9, color: 'var(--t-4)' }}>{batchOpen ? '▲' : '▼'}</span>
              </button>

              {batchOpen && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {/* Column headers */}
                  <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1.2fr 0.8fr 0.8fr', padding: '3px 8px' }}>
                    {['SYMBOL', 'SCORE', 'REGIME', 'RSI', 'QUAL'].map(h => (
                      <span key={h} style={{ fontSize: 8, color: 'var(--t-4)', fontFamily: 'var(--font-mono)', letterSpacing: '0.08em' }}>{h}</span>
                    ))}
                  </div>
                  {batch.map((b, i) => {
                    const failed     = !!b.error
                    const stCfg      = MARKET_STATE_CFG[b.market_state] ?? MARKET_STATE_CFG.neutral
                    const scoreColor = b.score >= 2.5 ? '#3ddc97' : b.score <= -2.5 ? '#ff476f' : b.score > 0 ? '#5ee8a9' : 'var(--t-4)'
                    return (
                      <div key={i} style={{
                        display: 'grid', gridTemplateColumns: '2fr 1fr 1.2fr 0.8fr 0.8fr',
                        padding: '5px 8px',
                        background: b.qualifies ? 'rgba(61,220,151,0.04)' : b.qualifies_short ? 'rgba(255,71,111,0.04)' : 'transparent',
                        borderRadius: 5,
                        borderBottom: '1px solid rgba(140,170,220,0.04)',
                        opacity: failed ? 0.4 : 1,
                      }}>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: b.qualifies || b.qualifies_short ? 700 : 400, color: b.qualifies ? '#3ddc97' : b.qualifies_short ? '#ff476f' : failed ? 'var(--t-4)' : 'var(--t-2)' }}>
                          {b.symbol}
                          {b.qualifies       && <span style={{ fontSize: 8, color: '#3ddc97', marginLeft: 4 }}>★</span>}
                          {b.qualifies_short && <span style={{ fontSize: 8, color: '#ff476f', marginLeft: 4 }}>↓</span>}
                          {failed            && <span style={{ fontSize: 8, color: '#475061', marginLeft: 4 }}>✕</span>}
                        </span>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 700, color: failed ? 'var(--t-4)' : scoreColor }}>
                          {failed ? '—' : (b.score >= 0 ? '+' : '') + f(b.score, 1)}
                        </span>
                        <span style={{ fontSize: 8, fontFamily: 'var(--font-mono)', color: failed ? 'var(--t-4)' : stCfg.color }}>
                          {failed ? 'NO DATA' : stCfg.label}
                        </span>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: failed ? 'var(--t-4)' : b.rsi <= 30 ? '#3ddc97' : b.rsi >= 70 ? '#ff476f' : 'var(--t-3)' }}>
                          {failed ? '—' : f(b.rsi, 0)}
                        </span>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color:
                          !b.trade_quality ? 'var(--t-4)' :
                          b.trade_quality >= 62 ? '#4ade80' : b.trade_quality >= 45 ? '#f59e0b' : '#ff476f'
                        }}>
                          {b.trade_quality != null ? `${Math.round(b.trade_quality)}` : '—'}
                        </span>
                      </div>
                    )
                  })}
                </div>
              )}
            </section>
          )}
        </div>
      </div>
    </div>
  )
}

function TradeRow({ t, isClose, pl, plColor, sideColor, hasReason }) {
  const [open, setOpen] = useState(false)
  return (
    <div style={{ borderBottom: '1px solid rgba(140,170,220,0.05)' }}>
      {/* Main row */}
      <div
        onClick={() => hasReason && setOpen(o => !o)}
        style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '6px 0',
          cursor: hasReason ? 'pointer' : 'default',
        }}
        onMouseEnter={e => { if (hasReason) e.currentTarget.style.background = 'rgba(140,170,220,0.04)' }}
        onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
      >
        <span style={{ fontSize: 8, fontWeight: 700, color: sideColor, fontFamily: 'var(--font-mono)', width: 36, flexShrink: 0, textTransform: 'uppercase' }}>
          {t.side}
        </span>
        <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--t-1)', fontFamily: 'var(--font-mono)', width: 80, flexShrink: 0 }}>
          {t.symbol}
        </span>
        <span style={{ fontSize: 9, color: 'var(--t-4)', fontFamily: 'var(--font-mono)', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {Number(t.qty).toFixed(4)} @ ${Number(t.price).toFixed(4)}
        </span>
        <span style={{ fontSize: 10, fontWeight: 700, fontFamily: 'var(--font-mono)', color: isClose ? plColor : 'var(--t-4)', flexShrink: 0, width: 70, textAlign: 'right' }}>
          {isClose ? `${pl >= 0 ? '+' : ''}$${pl?.toFixed(2)}` : '—'}
        </span>
        <span style={{ fontSize: 8, color: 'var(--t-4)', flexShrink: 0, width: 40, textAlign: 'right' }}>
          {fmtTime(t.created_at)}
        </span>
        {hasReason && (
          <span style={{ fontSize: 8, color: 'var(--t-4)', flexShrink: 0 }}>{open ? '▲' : '▼'}</span>
        )}
      </div>

      {/* Expanded reasoning */}
      {open && hasReason && (
        <div style={{
          margin: '0 0 8px 44px',
          padding: '8px 10px',
          background: 'rgba(0,0,0,0.2)',
          borderRadius: 6,
          border: `1px solid ${sideColor}22`,
        }}>
          {/* Score + regime + strategy */}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
            {t.ai_score != null && (
              <span style={{ fontSize: 8.5, fontFamily: 'var(--font-mono)', color: t.ai_score >= 0 ? 'var(--ok)' : 'var(--err)', fontWeight: 700 }}>
                score {t.ai_score >= 0 ? '+' : ''}{Number(t.ai_score).toFixed(2)}
              </span>
            )}
            {t.market_state && (
              <span style={{ fontSize: 8, color: '#f5b342', background: 'rgba(245,179,66,0.1)', border: '1px solid rgba(245,179,66,0.25)', borderRadius: 3, padding: '1px 5px', fontFamily: 'var(--font-mono)' }}>
                {t.market_state.replace(/_/g, ' ')}
              </span>
            )}
            {t.strategy && (
              <span style={{ fontSize: 8, color: '#4ad9ff', background: 'rgba(74,217,255,0.08)', border: '1px solid rgba(74,217,255,0.2)', borderRadius: 3, padding: '1px 5px', fontFamily: 'var(--font-mono)' }}>
                {t.strategy}
              </span>
            )}
          </div>
          {/* Reasoning text */}
          <div style={{ fontSize: 9.5, color: 'var(--t-2)', lineHeight: 1.65 }}>
            {t.reason}
          </div>
        </div>
      )}
    </div>
  )
}

function Chip({ label, color }) {
  return (
    <span style={{
      fontSize: 8.5, fontFamily: 'var(--font-mono)', fontWeight: 700,
      color, border: `1px solid ${color}44`, borderRadius: 4,
      padding: '2px 7px', letterSpacing: '0.05em',
    }}>
      {label}
    </span>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────────

export default function AILogPanel({ portfolioId, isAiControlled }) {
  const [runs,       setRuns]       = useState([])
  const [loading,    setLoading]    = useState(false)
  const [modal,      setModal]      = useState(null)   // run object for open modal
  const [flash,      setFlash]      = useState(false)
  const [review,      setReview]      = useState(null)
  const [reviewLoad,  setReviewLoad]  = useState(false)
  const [reviewTab,   setReviewTab]   = useState('scans')  // 'scans' | '30d' | 'trades'
  const [tradeHist,   setTradeHist]   = useState(null)
  const [tradeLoad,   setTradeLoad]   = useState(false)
  const prevCountRef = useRef(0)

  useEffect(() => {
    if (reviewTab !== '30d' || !portfolioId) return
    setReviewLoad(true)
    api.get(`/portfolios/${portfolioId}/history/review`)
      .then(r => { setReview(r.data); setReviewLoad(false) })
      .catch(() => setReviewLoad(false))
  }, [reviewTab, portfolioId])

  useEffect(() => {
    if (reviewTab !== 'trades' || !portfolioId) return
    setTradeLoad(true)
    api.get(`/portfolios/${portfolioId}/trades?limit=200`)
      .then(r => { setTradeHist(r.data); setTradeLoad(false) })
      .catch(() => setTradeLoad(false))
  }, [reviewTab, portfolioId])

  useEffect(() => {
    if (!portfolioId) return
    let cancelled = false

    function load() {
      api.get(`/portfolios/${portfolioId}/ai/scans?limit=30`)
        .then(r => {
          if (cancelled) return
          const data = r.data || []
          if (data.length !== prevCountRef.current) {
            prevCountRef.current = data.length
            setFlash(true)
            setTimeout(() => setFlash(false), 800)
          }
          setRuns(data)
          setLoading(false)
        })
        .catch(() => { if (!cancelled) setLoading(false) })
    }

    setLoading(true)
    load()
    const id = setInterval(load, isAiControlled ? 10000 : 30000)
    return () => { cancelled = true; clearInterval(id) }
  }, [portfolioId, isAiControlled])

  const lastRun  = runs[0] ?? null
  const totalBought = runs.reduce((s, r) => s + (r.bought_count || 0), 0)
  const totalSold   = runs.reduce((s, r) => s + (r.sold_count   || 0), 0)

  return (
    <>
      {modal && <ScanModal run={modal} onClose={() => setModal(null)} />}

      <div style={{ display: 'flex', flexDirection: 'column', height: '100%', fontFamily: 'var(--font-sans)' }}>

        {/* ── Header ── */}
        <div style={{
          padding: '8px 12px', flexShrink: 0,
          borderBottom: '1px solid rgba(140,170,220,0.08)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
              <span style={{
                width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
                background: isAiControlled ? (flash ? '#3ddc97' : 'rgba(61,220,151,0.5)') : '#2a3040',
                boxShadow: isAiControlled && flash ? '0 0 8px #3ddc97' : 'none',
                transition: 'all 0.3s',
              }} />
              <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--t-2)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                AI Scan
              </span>
              <span style={{ fontSize: 9, color: isAiControlled ? '#3ddc97' : '#475061', fontFamily: 'var(--font-mono)' }}>
                {isAiControlled ? 'AUTO' : 'MANUAL'}
              </span>
            </div>
            {lastRun && isAiControlled && (
              <NextScanCountdown lastScanTs={lastRun.created_at} intervalSec={90} />
            )}
          </div>

          {/* Stats row */}
          <div style={{ display: 'flex', gap: 10 }}>
            <StatPill label="Scans" value={runs.length} color="var(--t-3)" />
            <StatPill label="Bought" value={totalBought} color="#3ddc97" />
            <StatPill label="Sold"   value={totalSold}   color="#ff476f" />
            {lastRun && <StatPill label="Last scan" value={fmtTime(lastRun.created_at)} color="var(--t-4)" mono />}
          </div>
        </div>

        {/* ── Tab switcher ── */}
        <div style={{ display: 'flex', borderBottom: '1px solid rgba(140,170,220,0.08)', flexShrink: 0 }}>
          {[['scans', 'Scans'], ['trades', 'Trade P&L'], ['30d', '30D Review']].map(([key, label]) => (
            <button key={key} onClick={() => setReviewTab(key)} style={{
              flex: 1, padding: '6px 0', border: 'none', cursor: 'pointer',
              background: reviewTab === key ? 'rgba(179,157,255,0.08)' : 'transparent',
              color: reviewTab === key ? '#b39dff' : '#475061',
              fontSize: '10px', fontWeight: reviewTab === key ? 700 : 400,
              borderBottom: reviewTab === key ? '2px solid #b39dff' : '2px solid transparent',
              fontFamily: 'var(--font-sans)',
            }}>
              {label}
            </button>
          ))}
        </div>

        {/* ── 30D Review panel ── */}
        {/* ── Trade P&L History ── */}
        {reviewTab === 'trades' && (
          <div style={{ flex: 1, overflowY: 'auto', padding: '10px 12px' }}>
            {tradeLoad && <div style={{ color: 'var(--t-4)', fontSize: 11, textAlign: 'center', marginTop: 20 }}>Loading…</div>}
            {tradeHist && !tradeLoad && (
              <>
                {/* Summary bar */}
                {tradeHist.summary && (
                  <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 10, padding: '8px 10px', background: 'rgba(140,170,220,0.04)', borderRadius: 6, border: '1px solid rgba(140,170,220,0.1)' }}>
                    {[
                      { label: 'Total P&L', value: `${tradeHist.summary.total_pl >= 0 ? '+' : ''}$${tradeHist.summary.total_pl?.toFixed(2)}`, color: tradeHist.summary.total_pl >= 0 ? 'var(--ok)' : 'var(--err)' },
                      { label: 'Closed', value: tradeHist.summary.closed, color: 'var(--t-2)' },
                      { label: 'Win rate', value: `${tradeHist.summary.win_rate}%`, color: tradeHist.summary.win_rate >= 50 ? 'var(--ok)' : 'var(--err)' },
                      { label: 'Avg win', value: `+$${tradeHist.summary.avg_win?.toFixed(2)}`, color: 'var(--ok)' },
                      { label: 'Avg loss', value: `$${tradeHist.summary.avg_loss?.toFixed(2)}`, color: 'var(--err)' },
                    ].map(({ label, value, color }) => (
                      <div key={label} style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                        <span style={{ fontSize: 8, color: 'var(--t-4)', letterSpacing: '0.07em', textTransform: 'uppercase' }}>{label}</span>
                        <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', fontWeight: 700, color }}>{value}</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Trade rows — click to expand reasoning */}
                {(tradeHist.trades || []).map((t, i) => {
                  const isClose   = !t.is_open
                  const pl        = t.pl
                  const plColor   = pl > 0 ? 'var(--ok)' : pl < 0 ? 'var(--err)' : 'var(--t-4)'
                  const sideColor = t.side === 'buy' ? '#3ddc97' : t.side === 'sell' ? '#ff476f'
                                  : t.side === 'short' ? '#ff6a6a' : '#4ad9ff'
                  const hasReason = !!t.reason
                  return (
                    <TradeRow key={t.id || i}
                      t={t} isClose={isClose} pl={pl} plColor={plColor}
                      sideColor={sideColor} hasReason={hasReason} />
                  )
                })}
              </>
            )}
          </div>
        )}

        {reviewTab === '30d' && (
          <div style={{ flex: 1, overflowY: 'auto', padding: '10px 12px' }}>
            {reviewLoad && <div style={{ color: 'var(--t-4)', fontSize: 11, textAlign: 'center', marginTop: 20 }}>Loading…</div>}
            {review && !reviewLoad && (
              <>
                {/* Summary / active adjustments */}
                <div style={{ fontSize: 10, color: 'var(--t-3)', marginBottom: 10, lineHeight: 1.55, padding: '6px 8px', background: 'rgba(140,170,220,0.04)', borderRadius: 5, borderLeft: '2px solid rgba(179,157,255,0.4)' }}>
                  {review.summary}
                </div>

                {/* Decay alert */}
                {review.decay?.decay_detected && (
                  <div style={{ background: 'rgba(245,179,66,0.1)', border: '1px solid rgba(245,179,66,0.3)', borderRadius: 5, padding: '6px 10px', marginBottom: 10, fontSize: 9.5, color: '#f5b342' }}>
                    ⚠ {review.decay.message || `Win rate dropped to ${(review.decay.recent_win_rate * 100).toFixed(0)}% (7d) vs ${(review.decay.longterm_win_rate * 100).toFixed(0)}% (30d) — thresholds raised`}
                  </div>
                )}

                {/* Active adjustments chips */}
                {(review.adjustments?.buy_thresh_raised || review.adjustments?.cautious_regimes?.length > 0) && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 10 }}>
                    {review.adjustments.buy_thresh_raised && (
                      <span style={{ fontSize: 8.5, color: '#f59e0b', background: 'rgba(245,158,11,0.1)', border: '1px solid rgba(245,158,11,0.25)', borderRadius: 3, padding: '2px 7px' }}>
                        Buy threshold +0.8
                      </span>
                    )}
                    {review.adjustments.cautious_regimes?.map(r => (
                      <span key={r} style={{ fontSize: 8.5, color: '#ff6a6a', background: 'rgba(255,106,106,0.1)', border: '1px solid rgba(255,106,106,0.25)', borderRadius: 3, padding: '2px 7px' }}>
                        ⚠ Skip: {r.replace(/_/g, ' ')}
                      </span>
                    ))}
                    {review.adjustments.strong_regimes?.map(r => (
                      <span key={r} style={{ fontSize: 8.5, color: '#4ade80', background: 'rgba(74,222,128,0.1)', border: '1px solid rgba(74,222,128,0.25)', borderRadius: 3, padding: '2px 7px' }}>
                        ✓ {r.replace(/_/g, ' ')}
                      </span>
                    ))}
                  </div>
                )}

                {/* Equity curve — simple SVG line */}
                {review.equity_curve?.length > 1 && (() => {
                  const curve = review.equity_curve
                  const equities = curve.map(p => p.equity)
                  const minE = Math.min(...equities), maxE = Math.max(...equities)
                  const range = maxE - minE || 1
                  const W = 280, H = 60
                  const pts = curve.map((p, i) => {
                    const x = (i / (curve.length - 1)) * W
                    const y = H - ((p.equity - minE) / range * (H - 8) + 4)
                    return `${x},${y}`
                  }).join(' ')
                  const last = equities[equities.length - 1]
                  const first = equities[0]
                  const color = last >= first ? '#4ade80' : '#ff476f'
                  return (
                    <div style={{ marginBottom: 10 }}>
                      <div style={{ fontSize: 9, color: 'var(--t-4)', marginBottom: 4, letterSpacing: '0.06em', textTransform: 'uppercase' }}>30-Day Equity</div>
                      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block', borderRadius: 4, background: 'rgba(140,170,220,0.04)' }}>
                        <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" />
                      </svg>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 8.5, color: 'var(--t-4)', fontFamily: 'var(--font-mono)', marginTop: 3 }}>
                        <span>${first.toLocaleString()}</span>
                        <span style={{ color }}>${last.toLocaleString()}</span>
                      </div>
                    </div>
                  )
                })()}

                {/* Regime performance table */}
                {review.by_regime && Object.keys(review.by_regime).filter(k => k !== '_total').length > 0 && (
                  <div style={{ marginBottom: 10 }}>
                    <div style={{ fontSize: 9, color: 'var(--t-4)', marginBottom: 5, letterSpacing: '0.06em', textTransform: 'uppercase' }}>Regime Performance (30d)</div>
                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                      <thead>
                        <tr>
                          {['Regime', 'Trades', 'Win%', 'Avg P&L'].map(h => (
                            <th key={h} style={{ fontSize: 8, color: 'var(--t-4)', fontFamily: 'var(--font-mono)', textAlign: 'left', padding: '2px 4px', fontWeight: 400 }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(review.by_regime)
                          .filter(([k]) => k !== '_total')
                          .sort((a, b) => (b[1].trades || 0) - (a[1].trades || 0))
                          .map(([regime, stats]) => {
                            const isCautious = review.adjustments?.cautious_regimes?.includes(regime)
                            const isStrong   = review.adjustments?.strong_regimes?.includes(regime)
                            const wr = stats.win_rate || 0
                            const wrColor = wr > 0.6 ? '#4ade80' : wr < 0.4 ? '#ff6a6a' : 'var(--t-3)'
                            return (
                              <tr key={regime} style={{ borderBottom: '1px solid rgba(140,170,220,0.05)' }}>
                                <td style={{ fontSize: 9, color: 'var(--t-2)', padding: '3px 4px', fontFamily: 'var(--font-mono)' }}>
                                  {isCautious && <span style={{ color: '#ff6a6a', marginRight: 3 }}>⚠</span>}
                                  {isStrong   && <span style={{ color: '#4ade80', marginRight: 3 }}>✓</span>}
                                  {regime.replace(/_/g, ' ')}
                                </td>
                                <td style={{ fontSize: 9, color: 'var(--t-3)', padding: '3px 4px', fontFamily: 'var(--font-mono)', textAlign: 'right' }}>{stats.trades || 0}</td>
                                <td style={{ fontSize: 9, color: wrColor, padding: '3px 4px', fontFamily: 'var(--font-mono)', textAlign: 'right', fontWeight: 700 }}>{(wr * 100).toFixed(0)}%</td>
                                <td style={{ fontSize: 9, color: (stats.avg_pl || 0) >= 0 ? 'var(--ok)' : 'var(--err)', padding: '3px 4px', fontFamily: 'var(--font-mono)', textAlign: 'right' }}>
                                  {(stats.avg_pl || 0) >= 0 ? '+' : ''}{(stats.avg_pl || 0).toFixed(0)}
                                </td>
                              </tr>
                            )
                          })}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* Signal attribution */}
                {review.attribution && Object.keys(review.attribution).length > 0 && (
                  <div>
                    <div style={{ fontSize: 9, color: 'var(--t-4)', marginBottom: 5, letterSpacing: '0.06em', textTransform: 'uppercase' }}>Signal Attribution</div>
                    {Object.entries(review.attribution)
                      .sort((a, b) => (b[1].trades || 0) - (a[1].trades || 0))
                      .slice(0, 6)
                      .map(([signal, stats]) => {
                        const wr = stats.win_rate || 0
                        const barW = Math.min(100, wr * 100)
                        const barColor = wr > 0.6 ? '#4ade80' : wr < 0.4 ? '#ff6a6a' : '#f5b342'
                        return (
                          <div key={signal} style={{ marginBottom: 5 }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                              <span style={{ fontSize: 8.5, color: 'var(--t-3)', fontFamily: 'var(--font-mono)' }}>{signal}</span>
                              <span style={{ fontSize: 8.5, color: barColor, fontFamily: 'var(--font-mono)' }}>
                                {(wr * 100).toFixed(0)}% · {stats.trades} trades · avg {(stats.avg_pl || 0) >= 0 ? '+' : ''}{(stats.avg_pl || 0).toFixed(0)}
                              </span>
                            </div>
                            <div style={{ height: 3, background: 'rgba(140,170,220,0.1)', borderRadius: 2 }}>
                              <div style={{ width: `${barW}%`, height: '100%', background: barColor, borderRadius: 2, transition: 'width 0.4s' }} />
                            </div>
                          </div>
                        )
                      })}
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* ── Scan feed ── */}
        {reviewTab === 'scans' && <div style={{ flex: 1, overflowY: 'auto' }}>
          {loading && runs.length === 0 && (
            <div style={{ padding: 24, textAlign: 'center', fontSize: 11, color: 'var(--t-4)' }}>Loading…</div>
          )}
          {!loading && runs.length === 0 && (
            <div style={{ padding: '32px 16px', textAlign: 'center' }}>
              <div style={{ fontSize: 24, marginBottom: 10, opacity: 0.3 }}>🤖</div>
              <div style={{ fontSize: 11, color: 'var(--t-4)', lineHeight: 1.6 }}>
                {isAiControlled ? 'Waiting for first scan… (runs every 90s)' : 'Enable AI on this portfolio to start scanning.'}
              </div>
            </div>
          )}

          {runs.map(run => {
            const hasTrades   = run.bought_count > 0 || run.sold_count > 0
            const isCryptoOnly = run.mode === 'crypto_forex'
            const skipReason   = run.skip_reason
            return (
              <div
                key={run.id}
                onClick={() => setModal(run)}
                style={{
                  padding: '9px 12px',
                  borderBottom: '1px solid rgba(140,170,220,0.05)',
                  cursor: 'pointer',
                  background: 'transparent',
                  transition: 'background 0.12s',
                }}
                onMouseEnter={e => e.currentTarget.style.background = 'rgba(140,170,220,0.04)'}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
              >
                {/* Row 1: time + mode badge + scanned count */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                    <span style={{ fontSize: 9, color: 'var(--t-4)', fontFamily: 'var(--font-mono)' }}>
                      {fmtTime(run.created_at)}
                    </span>
                    {isCryptoOnly && (
                      <span style={{
                        fontSize: 7.5, fontFamily: 'var(--font-mono)', fontWeight: 700,
                        color: '#4ad9ff', border: '1px solid #4ad9ff33',
                        borderRadius: 3, padding: '1px 4px', letterSpacing: '0.06em',
                      }}>
                        CRYPTO/FX
                      </span>
                    )}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                    <span style={{ fontSize: 9, color: 'var(--t-4)', fontFamily: 'var(--font-mono)' }}>
                      {run.scanned} scanned
                    </span>
                    <span style={{ fontSize: 9, color: 'var(--t-4)' }}>›</span>
                  </div>
                </div>

                {/* Row 2: trade badges, skip reason, or "no trades" */}
                <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                  {run.bought_count > 0 && (
                    <span style={{
                      fontSize: 9, fontFamily: 'var(--font-mono)', fontWeight: 700,
                      color: '#3ddc97', background: 'rgba(61,220,151,0.10)',
                      border: '1px solid rgba(61,220,151,0.25)', borderRadius: 4, padding: '2px 7px',
                    }}>
                      ▲ {run.bought_count} bought
                    </span>
                  )}
                  {run.sold_count > 0 && (
                    <span style={{
                      fontSize: 9, fontFamily: 'var(--font-mono)', fontWeight: 700,
                      color: '#ff476f', background: 'rgba(255,71,111,0.10)',
                      border: '1px solid rgba(255,71,111,0.25)', borderRadius: 4, padding: '2px 7px',
                    }}>
                      ▼ {run.sold_count} sold
                    </span>
                  )}
                  {skipReason && (
                    <span style={{ fontSize: 8.5, color: '#f5b342', fontFamily: 'var(--font-mono)', fontStyle: 'italic' }}>
                      {{ max_positions: 'max positions', low_cash: 'low cash' }[skipReason] ?? skipReason}
                    </span>
                  )}
                  {!hasTrades && !skipReason && (
                    <span style={{ fontSize: 9, color: 'var(--t-4)', fontStyle: 'italic' }}>no trades</span>
                  )}
                  {run.error_count > 0 && (
                    <span style={{ fontSize: 9, color: '#f5b342', marginLeft: 'auto', fontFamily: 'var(--font-mono)' }}>
                      {run.error_count} err
                    </span>
                  )}
                </div>

                {/* Row 3: symbol pills for bought/sold */}
                {hasTrades && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 5 }}>
                    {(run.bought_json || []).map(b => (
                      <span key={b.symbol} style={{ fontSize: 8.5, fontFamily: 'var(--font-mono)', color: '#3ddc97', background: 'rgba(61,220,151,0.07)', borderRadius: 3, padding: '1px 5px' }}>
                        {b.symbol}
                      </span>
                    ))}
                    {(run.sold_json || []).map(s => (
                      <span key={s.symbol} style={{ fontSize: 8.5, fontFamily: 'var(--font-mono)', color: '#ff6a6a', background: 'rgba(255,71,111,0.07)', borderRadius: 3, padding: '1px 5px' }}>
                        {s.symbol}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>}

        {/* Footer hint */}
        {reviewTab === 'scans' && runs.length > 0 && (
          <div style={{ padding: '5px 12px', borderTop: '1px solid rgba(140,170,220,0.06)', flexShrink: 0 }}>
            <span style={{ fontSize: 8, color: 'var(--t-4)' }}>Tap any row to see full scan details</span>
          </div>
        )}
      </div>
    </>
  )
}

function StatPill({ label, value, color, mono }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <span style={{ fontSize: 7.5, color: 'var(--t-4)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>{label}</span>
      <span style={{ fontFamily: mono ? 'var(--font-mono)' : 'inherit', fontSize: 10, fontWeight: 700, color }}>{value}</span>
    </div>
  )
}

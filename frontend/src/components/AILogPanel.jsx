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

  const bought = run.bought_json || []
  const sold   = run.sold_json   || []
  const batch  = run.batch_json  || []

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
            {bought.length > 0 && <Chip label={`${bought.length} bought`}  color="#3ddc97" />}
            {sold.length   > 0 && <Chip label={`${sold.length} sold`}     color="#ff476f" />}
            {run.error_count > 0 && <Chip label={`${run.error_count} err`} color="#f5b342" />}
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
                          +{f(b.score, 1)}
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

          {/* No action */}
          {bought.length === 0 && sold.length === 0 && (
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
                </span>
                <span style={{ fontSize: 9, color: 'var(--t-4)' }}>{batchOpen ? '▲' : '▼'}</span>
              </button>

              {batchOpen && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {/* Column headers */}
                  <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1.2fr 1fr', padding: '3px 8px' }}>
                    {['SYMBOL', 'SCORE', 'REGIME', 'RSI'].map(h => (
                      <span key={h} style={{ fontSize: 8, color: 'var(--t-4)', fontFamily: 'var(--font-mono)', letterSpacing: '0.08em' }}>{h}</span>
                    ))}
                  </div>
                  {batch.map((b, i) => {
                    const stCfg     = MARKET_STATE_CFG[b.market_state] ?? MARKET_STATE_CFG.neutral
                    const scoreColor = b.score >= 2.5 ? '#3ddc97' : b.score <= -2.5 ? '#ff476f' : b.score > 0 ? '#5ee8a9' : 'var(--t-4)'
                    return (
                      <div key={i} style={{
                        display: 'grid', gridTemplateColumns: '2fr 1fr 1.2fr 1fr',
                        padding: '5px 8px',
                        background: b.qualifies ? 'rgba(61,220,151,0.04)' : 'transparent',
                        borderRadius: 5,
                        borderBottom: '1px solid rgba(140,170,220,0.04)',
                      }}>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: b.qualifies ? 700 : 400, color: b.qualifies ? '#3ddc97' : 'var(--t-2)' }}>
                          {b.symbol}
                          {b.qualifies && <span style={{ fontSize: 8, color: '#3ddc97', marginLeft: 4 }}>★</span>}
                        </span>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 700, color: scoreColor }}>
                          {b.score >= 0 ? '+' : ''}{f(b.score, 1)}
                        </span>
                        <span style={{ fontSize: 8, fontFamily: 'var(--font-mono)', color: stCfg.color }}>{stCfg.label}</span>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: b.rsi <= 30 ? '#3ddc97' : b.rsi >= 70 ? '#ff476f' : 'var(--t-3)' }}>
                          {f(b.rsi, 0)}
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
  const [runs,    setRuns]    = useState([])
  const [loading, setLoading] = useState(false)
  const [modal,   setModal]   = useState(null)   // run object for open modal
  const [flash,   setFlash]   = useState(false)
  const prevCountRef = useRef(0)

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

        {/* ── Scan feed ── */}
        <div style={{ flex: 1, overflowY: 'auto' }}>
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
        </div>

        {/* Footer hint */}
        {runs.length > 0 && (
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

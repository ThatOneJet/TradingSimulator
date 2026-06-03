import { useState, useEffect, useRef } from 'react'
import api from '../api.js'
import ArbitrageModal from './ArbitrageModal.jsx'

// ── Helpers ───────────────────────────────────────────────────────────────────

function money(n) {
  if (n == null || isNaN(n)) return '—'
  const v = Number(n)
  return (v < 0 ? '-$' : '$') + Math.abs(v).toFixed(2)
}

function signedMoney(n) {
  if (n == null || isNaN(n)) return '—'
  const v = Number(n)
  return (v >= 0 ? '+' : '') + money(v)
}

function f(n, d = 2) { return (n == null || isNaN(n)) ? '—' : Number(n).toFixed(d) }

function fmtTime(ts) {
  if (!ts) return ''
  const d    = new Date(ts.endsWith('Z') ? ts : ts + 'Z')
  const now  = new Date()
  const diff = (now - d) / 1000
  if (diff < 60)    return `${Math.floor(diff)}s ago`
  if (diff < 3600)  return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

const TYPE_CFG = {
  triangular:     { color: '#b39dff', glyph: '🔺', label: 'TRI' },
  cross_exchange: { color: '#4ad9ff', glyph: '⇄',  label: 'CROSS' },
}

// ── Small bits ────────────────────────────────────────────────────────────────

function StatPill({ label, value, color, mono }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <span style={{ fontSize: 7.5, color: 'var(--t-4)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>{label}</span>
      <span style={{ fontFamily: mono ? 'var(--font-mono)' : 'inherit', fontSize: 10, fontWeight: 700, color }}>{value}</span>
    </div>
  )
}

function TypeBadge({ type, withGlyph = true }) {
  const cfg = TYPE_CFG[type] ?? TYPE_CFG.cross_exchange
  return (
    <span style={{
      fontSize: 8, fontFamily: 'var(--font-mono)', fontWeight: 700,
      color: cfg.color, border: `1px solid ${cfg.color}44`, borderRadius: 4,
      padding: '1px 6px', letterSpacing: '0.05em', flexShrink: 0, whiteSpace: 'nowrap',
    }}>
      {withGlyph ? `${cfg.glyph} ` : ''}{cfg.label}
    </span>
  )
}

function ExchangeChips({ exchanges }) {
  if (!exchanges?.length) return null
  return (
    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
      {exchanges.map((ex, i) => (
        <span key={i} style={{
          fontSize: 7.5, fontFamily: 'var(--font-mono)', color: '#8899aa',
          background: 'rgba(140,170,220,0.06)', border: '1px solid rgba(140,170,220,0.12)',
          borderRadius: 3, padding: '0px 4px', whiteSpace: 'nowrap',
        }}>
          {ex}
        </span>
      ))}
    </div>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────────

export default function ArbitragePanel({ portfolioId }) {
  const [opps,    setOpps]    = useState([])
  const [trades,  setTrades]  = useState([])
  const [loading, setLoading] = useState(true)
  const [flash,   setFlash]   = useState(false)
  const [modalId, setModalId] = useState(null)
  const [autoOn,  setAutoOn]  = useState(false)
  const prevCountRef = useRef(0)

  useEffect(() => {
    if (!portfolioId) return
    api.get(`/portfolios/${portfolioId}/arbitrage/status`)
      .then(r => setAutoOn(!!r.data?.arb_enabled))
      .catch(() => {})
  }, [portfolioId])

  const toggleAuto = async () => {
    const next = !autoOn
    setAutoOn(next)
    try { await api.post(`/portfolios/${portfolioId}/arbitrage/toggle`, { enabled: next }) }
    catch { setAutoOn(!next) }
  }

  useEffect(() => {
    if (!portfolioId) return
    let cancelled = false

    function load() {
      api.get('/arbitrage/opportunities')
        .then(r => { if (!cancelled) setOpps(r.data?.opportunities || []) })
        .catch(() => {})

      api.get(`/portfolios/${portfolioId}/arbitrage/trades?limit=50`)
        .then(r => {
          if (cancelled) return
          const data = Array.isArray(r.data) ? r.data : (r.data?.trades || [])
          if (data.length !== prevCountRef.current) {
            prevCountRef.current = data.length
            setFlash(true)
            setTimeout(() => setFlash(false), 800)
          }
          setTrades(data)
          setLoading(false)
        })
        .catch(() => { if (!cancelled) setLoading(false) })
    }

    setLoading(true)
    load()
    const id = setInterval(load, 8000)
    return () => { cancelled = true; clearInterval(id) }
  }, [portfolioId])

  const totalProfit = trades.reduce((s, t) => s + (t.profit || 0), 0)
  const profitCol   = totalProfit >= 0 ? 'var(--ok)' : 'var(--err)'

  return (
    <>
      {modalId != null && <ArbitrageModal tradeId={modalId} onClose={() => setModalId(null)} />}

      <div style={{ display: 'flex', flexDirection: 'column', height: '100%', fontFamily: 'var(--font-sans)' }}>

        {/* ── Header ── */}
        <div style={{ padding: '8px 12px', flexShrink: 0, borderBottom: '1px solid rgba(140,170,220,0.08)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 6 }}>
            <span style={{
              width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
              background: flash ? '#3ddc97' : 'rgba(61,220,151,0.5)',
              boxShadow: flash ? '0 0 8px #3ddc97' : 'none',
              transition: 'all 0.3s',
            }} />
            <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--t-2)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
              Arbitrage
            </span>
            <span style={{ fontSize: 9, color: opps.length > 0 ? '#3ddc97' : '#475061', fontFamily: 'var(--font-mono)' }}>
              {opps.length > 0 ? 'LIVE' : 'SCANNING'}
            </span>
            <button
              onClick={toggleAuto}
              title={autoOn ? 'Auto-execution ON — profitable arbs are captured automatically' : 'Auto-execution OFF — detection only'}
              style={{
                marginLeft: 'auto', padding: '2px 9px', borderRadius: 4, cursor: 'pointer',
                fontSize: 8.5, fontWeight: 700, letterSpacing: '0.06em', fontFamily: 'var(--font-mono)',
                background: autoOn ? 'rgba(61,220,151,0.15)' : 'transparent',
                color: autoOn ? '#3ddc97' : '#475061',
                border: `1px solid ${autoOn ? 'rgba(61,220,151,0.4)' : 'rgba(140,170,220,0.15)'}`,
              }}
            >
              {autoOn ? '● AUTO ON' : '○ AUTO OFF'}
            </button>
          </div>

          {/* Stats row */}
          <div style={{ display: 'flex', gap: 14, alignItems: 'center' }}>
            <StatPill label="Executed"   value={trades.length}             color="var(--t-3)" />
            <StatPill label="Net Profit" value={signedMoney(totalProfit)}  color={profitCol} mono />
            <StatPill label="Live Ops"   value={opps.length}               color={opps.length > 0 ? '#3ddc97' : 'var(--t-4)'} />
          </div>
        </div>

        {/* ── Live Opportunities ── */}
        <div style={{ flexShrink: 0, borderBottom: '1px solid rgba(140,170,220,0.08)', padding: '8px 12px', maxHeight: 150, overflowY: 'auto' }}>
          <div style={{ fontSize: 8.5, fontWeight: 700, color: 'var(--t-4)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 6 }}>
            Live Opportunities
          </div>
          {opps.length === 0 ? (
            <div style={{ fontSize: 10, color: 'var(--t-4)', padding: '2px 0' }}>
              No opportunities above threshold right now.
            </div>
          ) : (
            opps.map((o, i) => {
              const pct = o.profit_pct ?? 0
              const pctCol = pct > 0 ? 'var(--ok)' : 'var(--t-3)'
              return (
                <div key={i} style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  padding: '4px 0', borderBottom: '1px solid rgba(140,170,220,0.04)',
                }}>
                  <TypeBadge type={o.type} withGlyph={false} />
                  <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--t-2)', fontFamily: 'var(--font-mono)', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {o.start_asset ?? '—'} <span style={{ color: 'var(--t-4)' }}>→</span> {o.end_asset ?? '—'}
                  </span>
                  <span style={{ fontSize: 10, fontWeight: 700, color: pctCol, fontFamily: 'var(--font-mono)', marginLeft: 'auto', flexShrink: 0 }}>
                    {pct > 0 ? '+' : ''}{f(pct, 2)}%
                  </span>
                  <span style={{
                    fontSize: 7.5, fontFamily: 'var(--font-mono)', fontWeight: 700, flexShrink: 0,
                    color: o.executable ? '#3ddc97' : '#475061',
                    border: `1px solid ${o.executable ? 'rgba(61,220,151,0.3)' : 'rgba(140,170,220,0.12)'}`,
                    borderRadius: 3, padding: '0px 5px',
                  }}>
                    {o.executable ? 'EXEC' : 'WATCH'}
                  </span>
                </div>
              )
            })
          )}
        </div>

        {/* ── Executed log ── */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '8px 12px' }}>
          <div style={{ fontSize: 8.5, fontWeight: 700, color: 'var(--t-4)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 6 }}>
            Executed
          </div>

          {loading && trades.length === 0 && (
            <div style={{ textAlign: 'center', padding: '20px 0', color: 'var(--t-4)', fontSize: 11 }}>Loading…</div>
          )}

          {!loading && trades.length === 0 && (
            <div style={{ textAlign: 'center', padding: '20px 0', color: 'var(--t-4)', fontSize: 11 }}>
              No arbitrage trades executed yet.
            </div>
          )}

          {trades.map((t, i) => {
            const profCol = (t.profit ?? 0) >= 0 ? 'var(--ok)' : 'var(--err)'
            return (
              <div
                key={t.id ?? i}
                onClick={() => setModalId(t.id)}
                style={{
                  display: 'flex', flexDirection: 'column', gap: 5,
                  padding: '8px 0', cursor: 'pointer',
                  borderBottom: '1px solid rgba(140,170,220,0.05)',
                }}
                onMouseEnter={e => { e.currentTarget.style.background = 'rgba(140,170,220,0.04)' }}
                onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <TypeBadge type={t.type} />
                  <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--t-1)', fontFamily: 'var(--font-mono)', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {t.start_asset ?? '—'} <span style={{ color: 'var(--t-4)' }}>→</span> {t.end_asset ?? '—'}
                  </span>
                  <span style={{ fontSize: 11, fontWeight: 700, color: profCol, fontFamily: 'var(--font-mono)', marginLeft: 'auto', flexShrink: 0 }}>
                    {signedMoney(t.profit)}
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <ExchangeChips exchanges={t.exchanges} />
                  <span style={{ fontSize: 9, fontWeight: 700, color: profCol, fontFamily: 'var(--font-mono)', marginLeft: 'auto', flexShrink: 0 }}>
                    {(t.profit_pct ?? 0) >= 0 ? '+' : ''}{f(t.profit_pct, 2)}%
                  </span>
                  <span style={{ fontSize: 8, color: 'var(--t-4)', flexShrink: 0 }}>
                    {fmtTime(t.created_at)}
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </>
  )
}

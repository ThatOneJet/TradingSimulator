import { useState, useEffect } from 'react'
import api from '../api.js'

const isCrypto = sym => sym.endsWith('-USD')
const isForex  = sym => sym.endsWith('=X')
const is24_7   = sym => isCrypto(sym) || isForex(sym)

function getCategory(sym) {
  if (isCrypto(sym)) return 'crypto'
  if (isForex(sym))  return 'forex'
  return 'equities'
}

const CATEGORY_META = {
  crypto:   { label: 'Crypto',   dot: '#4ad9ff', badge: '24/7' },
  forex:    { label: 'Forex',    dot: '#a78bfa', badge: '24/7' },
  equities: { label: 'Equities', dot: '#f59e0b', badge: 'Mkt Hours' },
}

function fmt(n, d = 2) {
  return Number(n).toFixed(d)
}

const STAGE_COLORS = ['#ff476f', '#f59e0b', '#4ad9ff', '#a78bfa', '#4ade80']
const STAGE_LABELS = ['At Risk', 'Breakeven', 'Min Locked', 'Half Locked', 'Trailing']

function ProtectionGuide({ prot, bearish, isShort }) {
  const [open, setOpen] = useState(false)
  if (!prot) return null

  const stage     = prot.protection?.stage ?? 0
  const label     = prot.protection?.label ?? 'at_risk'
  const stopPrice = prot.protection?.new_stop ?? prot.stop_price
  const gainPct   = prot.protection?.gain_pct ?? 0
  const desc      = prot.protection?.description ?? ''
  const nextLvl   = prot.protection?.next_level
  const bScore    = bearish?.score ?? 0
  const bLevel    = bearish?.level ?? 'safe'
  const bDesc     = bearish?.description ?? ''
  const bColor    = bScore < 3 ? '#4ade80' : bScore < 5 ? '#f59e0b' : bScore < 7 ? '#fb923c' : '#ff476f'
  const stageColor = STAGE_COLORS[stage] ?? '#ff476f'

  // For shorts: bearish signal is GOOD (position working in our favour), don't warn
  // Only show bearish warning on long positions
  const showBearishWarn = bScore >= 4 && !isShort

  // Don't render anything at stage 0 (At Risk) when collapsed — just show a subtle
  // "monitoring" line so it's not overwhelming. Only expand on click.
  return (
    <div style={{ marginTop: 2, marginBottom: 4 }}>
      {/* Collapsed toggle row */}
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', background: 'none', border: 'none', cursor: 'pointer',
          display: 'flex', alignItems: 'center', gap: 6, padding: '3px 0',
          textAlign: 'left',
        }}
      >
        {/* Stage pip strip */}
        <div style={{ display: 'flex', gap: 3, alignItems: 'center' }}>
          {[0,1,2,3,4].map(i => (
            <div key={i} style={{
              width: i <= stage ? 10 : 6, height: i <= stage ? 6 : 4,
              borderRadius: 2,
              background: i <= stage ? STAGE_COLORS[i] : 'rgba(140,170,220,0.15)',
              transition: 'all 0.2s',
            }} />
          ))}
        </div>
        <span style={{ fontSize: 9, color: stage === 0 ? 'var(--t-4)' : stageColor, fontWeight: stage === 0 ? 400 : 700, letterSpacing: '0.05em' }}>
          {stage === 0 ? 'monitoring' : STAGE_LABELS[stage]}
        </span>
        {showBearishWarn && (
          <span style={{ fontSize: 8, color: bColor, marginLeft: 4 }}>
            ⚠ {bLevel}
          </span>
        )}
        <span style={{ fontSize: 8, color: 'var(--t-4)', marginLeft: 'auto' }}>
          {open ? '▲' : '▼'}
        </span>
      </button>

      {open && (
        <div style={{
          background: 'rgba(0,0,0,0.25)', borderRadius: 6,
          border: `1px solid ${stageColor}22`,
          padding: '8px 10px', marginTop: 3,
        }}>
          {/* Stage description */}
          <div style={{ fontSize: 9.5, color: 'var(--t-2)', lineHeight: 1.6, marginBottom: 6 }}>
            {desc}
          </div>

          {/* Stop level */}
          {stopPrice && (
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ fontSize: 9, color: 'var(--t-4)' }}>Stop level</span>
              <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', fontWeight: 700, color: stageColor }}>
                ${Number(stopPrice).toFixed(2)}
                {stage >= 1 && <span style={{ fontSize: 8, color: 'var(--t-4)', fontWeight: 400, marginLeft: 4 }}>
                  {stage === 1 ? '(breakeven)' : stage === 2 ? '(+0.5% min)' : '(gain locked)'}
                </span>}
              </span>
            </div>
          )}

          {/* Next protection level */}
          {nextLvl && (
            <div style={{
              fontSize: 8.5, color: '#4ad9ff', background: 'rgba(74,217,255,0.07)',
              borderRadius: 4, padding: '3px 7px', marginBottom: 6,
            }}>
              Next: {nextLvl}
            </div>
          )}

          {/* Bearish risk bar */}
          {bScore > 0 && (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                <span style={{ fontSize: 8.5, color: 'var(--t-4)' }}>Bearish risk</span>
                <span style={{ fontSize: 8.5, color: bColor, fontWeight: 700 }}>
                  {bScore.toFixed(1)}/10 · {bLevel}
                </span>
              </div>
              <div style={{ height: 4, background: 'rgba(140,170,220,0.1)', borderRadius: 2 }}>
                <div style={{
                  width: `${bScore * 10}%`, height: '100%',
                  background: bColor, borderRadius: 2,
                  transition: 'width 0.4s',
                }} />
              </div>
              {bDesc && (
                <div style={{ fontSize: 8.5, color: 'var(--t-4)', marginTop: 3, lineHeight: 1.4 }}>
                  {bDesc}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function PositionCard({ p, isReal, totalValue, onClose, protData }) {
  const isShort = p.side === 'short'
  const absQty  = Math.abs(p.qty)
  const mktVal  = absQty * p.current_price
  const pct     = totalValue > 0 ? (mktVal / totalValue * 100) : 0
  const plPos   = p.unrealized_pl >= 0
  const plColor = plPos ? 'var(--ok)' : 'var(--err)'

  return (
    <div style={{
      padding: '7px 0',
      borderBottom: '1px solid rgba(140,170,220,0.06)',
    }}>
      {/* Row 1: symbol + allocation bar + close */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700, color: isShort ? '#ff6a6a' : 'var(--t-1)', flexShrink: 0 }}>
          {p.symbol}
        </span>
        {isShort && (
          <span style={{
            fontSize: 7, fontWeight: 700, color: '#ff476f',
            border: '1px solid rgba(255,71,111,0.4)', borderRadius: 3,
            padding: '1px 3px', lineHeight: 1.4, letterSpacing: '0.04em', flexShrink: 0,
          }}>SHORT</span>
        )}

        {/* Allocation bar */}
        {totalValue > 0 && (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 4, minWidth: 0 }}>
            <div style={{ flex: 1, height: 3, background: 'rgba(140,170,220,0.1)', borderRadius: 2 }}>
              <div style={{
                width: `${Math.min(100, pct * 3)}%`, height: '100%',
                background: isShort ? '#ff6a6a' : '#4ad9ff',
                borderRadius: 2, opacity: 0.7,
              }} />
            </div>
            <span style={{ fontSize: 8.5, color: 'var(--t-4)', fontFamily: 'var(--font-mono)', flexShrink: 0 }}>
              {pct.toFixed(1)}%
            </span>
          </div>
        )}

        {!isReal && (
          <button
            className="close-btn"
            onClick={onClose}
            title={isShort ? 'Cover short' : 'Close position'}
            style={{ flexShrink: 0, color: isShort ? '#ff476f' : undefined }}
          >
            {isShort ? '↑' : '✕'}
          </button>
        )}
      </div>

      {/* Row 2: qty · avg → price · P&L */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 9.5, color: 'var(--t-4)', fontFamily: 'var(--font-mono)' }}>
          {isShort ? '-' : ''}{absQty}
        </span>
        <span style={{ fontSize: 9.5, color: 'var(--t-4)', fontFamily: 'var(--font-mono)' }}>
          ${fmt(p.avg_entry_price)} → ${fmt(p.current_price)}
        </span>
        <span style={{ fontSize: 10, fontWeight: 700, color: plColor, fontFamily: 'var(--font-mono)', marginLeft: 'auto' }}>
          {plPos ? '+' : ''}{Number(p.unrealized_pl).toFixed(2)}
          <span style={{ fontSize: 8.5, fontWeight: 400, color: 'var(--t-4)', marginLeft: 3 }}>
            ({plPos ? '+' : ''}{(Number(p.unrealized_plpc) * 100).toFixed(2)}%)
          </span>
        </span>
      </div>

      {/* Protection guide — sim portfolios only */}
      {!isReal && protData && (
        <ProtectionGuide prot={protData} bearish={protData.bearish} isShort={isShort} />
      )}
    </div>
  )
}

export default function Positions({ positions, onRefresh, portfolioId, totalValue }) {
  const isReal = portfolioId === 0
  const [protection, setProtection] = useState({})

  useEffect(() => {
    if (!portfolioId || portfolioId === 0) return
    api.get(`/portfolios/${portfolioId}/positions/protection`)
      .then(r => {
        const map = {}
        ;(r.data || []).forEach(p => { if (p.symbol) map[p.symbol] = p })
        setProtection(map)
      })
      .catch(() => {})
  }, [portfolioId, positions.length])

  async function closePosition(symbol, qty, side) {
    try {
      const orderSide = side === 'short' ? 'cover' : 'sell'
      await api.post('/orders', { symbol, qty: Math.abs(qty), side: orderSide, type: 'market', portfolio_id: portfolioId || 1 })
      setTimeout(onRefresh, 800)
    } catch {}
  }

  const shorts = positions.filter(p => p.side === 'short')

  const groups = { crypto: [], forex: [], equities: [] }
  for (const p of positions) groups[getCategory(p.symbol)].push(p)
  const orderedGroups = ['crypto', 'forex', 'equities'].filter(g => groups[g].length > 0)

  return (
    <div className="widget" style={{ padding: '12px 14px' }}>
      <div className="widget-hd">
        {isReal ? 'Holdings' : 'Positions'}
        <span className="badge" style={{ marginLeft: 6 }}>{positions.length}</span>
        {shorts.length > 0 && (
          <span className="badge" style={{ marginLeft: 4, background: 'rgba(255,71,111,0.15)', color: '#ff476f', border: '1px solid rgba(255,71,111,0.3)' }}>
            {shorts.length} short
          </span>
        )}
      </div>

      {positions.length === 0
        ? <div className="empty-state">{isReal ? 'No holdings tracked' : 'No open positions'}</div>
        : (
          <div style={{ overflowY: 'auto', maxHeight: 320, width: '100%' }}>
            {orderedGroups.map(cat => {
              const meta = CATEGORY_META[cat]
              const is247 = cat !== 'equities'
              return (
                <div key={cat}>
                  {/* Category header */}
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 6,
                    padding: '8px 0 4px',
                    borderBottom: '1px solid rgba(140,170,220,0.08)',
                    marginBottom: 2,
                  }}>
                    <div style={{ width: 6, height: 6, borderRadius: '50%', background: meta.dot, flexShrink: 0 }} />
                    <span style={{ fontSize: 9.5, fontWeight: 700, color: 'var(--t-3)', letterSpacing: '0.07em', textTransform: 'uppercase' }}>
                      {meta.label}
                    </span>
                    <span style={{
                      fontSize: 8, color: is247 ? '#4ade80' : '#f59e0b',
                      background: is247 ? 'rgba(74,222,128,0.1)' : 'rgba(245,158,11,0.1)',
                      border: `1px solid ${is247 ? 'rgba(74,222,128,0.2)' : 'rgba(245,158,11,0.2)'}`,
                      borderRadius: 3, padding: '1px 4px',
                    }}>
                      {meta.badge}
                    </span>
                    <span style={{ fontSize: 8.5, color: 'var(--t-4)', marginLeft: 'auto' }}>
                      {groups[cat].length}
                    </span>
                  </div>

                  {groups[cat].map(p => (
                    <PositionCard
                      key={p.symbol + (p.side === 'short' ? '-s' : '')}
                      p={p}
                      isReal={isReal}
                      totalValue={totalValue}
                      onClose={() => closePosition(p.symbol, p.qty, p.side)}
                      protData={protection[p.symbol]}
                    />
                  ))}
                </div>
              )
            })}
          </div>
        )
      }
    </div>
  )
}

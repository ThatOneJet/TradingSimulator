import { useState, useEffect } from 'react'
import api from '../api.js'

const isCrypto  = sym => sym.endsWith('-USD')
const isForex   = sym => sym.endsWith('=X')
const isFutures = sym => sym.endsWith('=F')

function getTab(sym) {
  if (isCrypto(sym))  return 'crypto'
  if (isForex(sym))   return 'forex'
  if (isFutures(sym)) return 'futures'
  return 'equities'
}

const TAB_META = {
  all:      { label: 'All',      dot: '#8899aa' },
  equities: { label: 'Stocks',   dot: '#f59e0b', badge: 'Mkt Hours' },
  crypto:   { label: 'Crypto',   dot: '#4ad9ff', badge: '24/7' },
  forex:    { label: 'Forex',    dot: '#a78bfa', badge: '24/7' },
  futures:  { label: 'Futures',  dot: '#fb923c', badge: '24/7' },
}

const STAGE_COLORS = ['#ff476f', '#f59e0b', '#4ad9ff', '#a78bfa', '#4ade80']
const STAGE_LABELS = ['At Risk', 'Breakeven', 'Min Locked', 'Half Locked', 'Trailing']

function ProtectionGuide({ prot, bearish, isShort }) {
  const [open, setOpen] = useState(false)
  if (!prot) return null

  const stage     = prot.protection?.stage ?? 0
  const stopPrice = prot.protection?.new_stop ?? prot.stop_price
  const desc      = prot.protection?.description ?? ''
  const nextLvl   = prot.protection?.next_level
  const bScore    = bearish?.score ?? 0
  const bLevel    = bearish?.level ?? 'safe'
  const bDesc     = bearish?.description ?? ''
  const bColor    = bScore < 3 ? '#4ade80' : bScore < 5 ? '#f59e0b' : bScore < 7 ? '#fb923c' : '#ff476f'
  const stageColor = STAGE_COLORS[stage] ?? '#ff476f'
  const showBearishWarn = bScore >= 4 && !isShort

  return (
    <div style={{ marginTop: 2, marginBottom: 4 }}>
      <button onClick={() => setOpen(o => !o)} style={{
        width: '100%', background: 'none', border: 'none', cursor: 'pointer',
        display: 'flex', alignItems: 'center', gap: 6, padding: '3px 0', textAlign: 'left',
      }}>
        <div style={{ display: 'flex', gap: 3, alignItems: 'center' }}>
          {[0,1,2,3,4].map(i => (
            <div key={i} style={{
              width: i <= stage ? 10 : 6, height: i <= stage ? 6 : 4, borderRadius: 2,
              background: i <= stage ? STAGE_COLORS[i] : 'rgba(140,170,220,0.15)',
              transition: 'all 0.2s',
            }} />
          ))}
        </div>
        <span style={{ fontSize: 9, color: stage === 0 ? 'var(--t-4)' : stageColor, fontWeight: stage === 0 ? 400 : 700, letterSpacing: '0.05em' }}>
          {stage === 0 ? 'monitoring' : STAGE_LABELS[stage]}
        </span>
        {showBearishWarn && <span style={{ fontSize: 8, color: bColor, marginLeft: 4 }}>⚠ {bLevel}</span>}
        <span style={{ fontSize: 8, color: 'var(--t-4)', marginLeft: 'auto' }}>{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div style={{ background: 'rgba(0,0,0,0.25)', borderRadius: 6, border: `1px solid ${stageColor}22`, padding: '8px 10px', marginTop: 3 }}>
          <div style={{ fontSize: 9.5, color: 'var(--t-2)', lineHeight: 1.6, marginBottom: 6 }}>{desc}</div>
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
          {nextLvl && (
            <div style={{ fontSize: 8.5, color: '#4ad9ff', background: 'rgba(74,217,255,0.07)', borderRadius: 4, padding: '3px 7px', marginBottom: 6 }}>
              Next: {nextLvl}
            </div>
          )}
          {bScore > 0 && (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                <span style={{ fontSize: 8.5, color: 'var(--t-4)' }}>Bearish risk</span>
                <span style={{ fontSize: 8.5, color: bColor, fontWeight: 700 }}>{bScore.toFixed(1)}/10 · {bLevel}</span>
              </div>
              <div style={{ height: 4, background: 'rgba(140,170,220,0.1)', borderRadius: 2 }}>
                <div style={{ width: `${bScore * 10}%`, height: '100%', background: bColor, borderRadius: 2, transition: 'width 0.4s' }} />
              </div>
              {bDesc && <div style={{ fontSize: 8.5, color: 'var(--t-4)', marginTop: 3, lineHeight: 1.4 }}>{bDesc}</div>}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function fmtQty(n) {
  const v = Math.abs(Number(n))
  if (isNaN(v)) return '—'
  if (v >= 100)  return v.toFixed(2)
  if (v >= 1)    return v.toFixed(4)
  if (v >= 0.01) return v.toFixed(6)
  return v.toFixed(8)
}

function PositionCard({ p, isReal, totalValue, onClose, protData }) {
  const isShort = p.side === 'short'
  const absQty  = Math.abs(p.qty)
  const mktVal  = absQty * p.current_price
  const pct     = totalValue > 0 ? (mktVal / totalValue * 100) : 0
  const plPos   = p.unrealized_pl >= 0
  const plColor = plPos ? 'var(--ok)' : 'var(--err)'

  return (
    <div style={{ padding: '7px 0', borderBottom: '1px solid rgba(140,170,220,0.06)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700, color: isShort ? '#ff6a6a' : 'var(--t-1)', flexShrink: 0 }}>
          {p.symbol}
        </span>
        {isShort && (
          <span style={{ fontSize: 7, fontWeight: 700, color: '#ff476f', border: '1px solid rgba(255,71,111,0.4)', borderRadius: 3, padding: '1px 3px', lineHeight: 1.4, letterSpacing: '0.04em', flexShrink: 0 }}>
            SHORT
          </span>
        )}
        {totalValue > 0 && (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 4, minWidth: 0 }}>
            <div style={{ flex: 1, height: 3, background: 'rgba(140,170,220,0.1)', borderRadius: 2 }}>
              <div style={{ width: `${Math.min(100, pct * 3)}%`, height: '100%', background: isShort ? '#ff6a6a' : '#4ad9ff', borderRadius: 2, opacity: 0.7 }} />
            </div>
            <span style={{ fontSize: 8.5, color: 'var(--t-4)', fontFamily: 'var(--font-mono)', flexShrink: 0 }}>{pct.toFixed(1)}%</span>
          </div>
        )}
        {!isReal && (
          <button className="close-btn" onClick={onClose} title={isShort ? 'Cover short' : 'Close position'} style={{ flexShrink: 0, color: isShort ? '#ff476f' : undefined }}>
            {isShort ? '↑' : '✕'}
          </button>
        )}
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 9.5, color: 'var(--t-4)', fontFamily: 'var(--font-mono)' }}>{fmtQty(absQty)}</span>
        <span style={{ fontSize: 9.5, color: 'var(--t-4)', fontFamily: 'var(--font-mono)' }}>${Number(p.avg_entry_price).toFixed(2)} → ${Number(p.current_price).toFixed(2)}</span>
        <span style={{ fontSize: 10, fontWeight: 700, color: plColor, fontFamily: 'var(--font-mono)', marginLeft: 'auto' }}>
          {plPos ? '+' : ''}{Number(p.unrealized_pl).toFixed(2)}
          <span style={{ fontSize: 8.5, fontWeight: 400, color: 'var(--t-4)', marginLeft: 3 }}>
            ({plPos ? '+' : ''}{(Number(p.unrealized_plpc) * 100).toFixed(2)}%)
          </span>
        </span>
      </div>
      {!isReal && protData && <ProtectionGuide prot={protData} bearish={protData.bearish} isShort={isShort} />}
    </div>
  )
}

function SideGroup({ label, color, positions, isReal, totalValue, protection, onClose }) {
  if (!positions.length) return null
  return (
    <div style={{ marginBottom: 6 }}>
      <div style={{ fontSize: 8.5, fontWeight: 700, color, letterSpacing: '0.08em', textTransform: 'uppercase', padding: '5px 0 3px', opacity: 0.8 }}>
        {label} <span style={{ opacity: 0.5, fontWeight: 400 }}>({positions.length})</span>
      </div>
      {positions.map(p => (
        <PositionCard
          key={p.symbol + (p.side === 'short' ? '-s' : '')}
          p={p} isReal={isReal} totalValue={totalValue}
          onClose={() => onClose(p.symbol, p.qty, p.side)}
          protData={protection[p.symbol]}
        />
      ))}
    </div>
  )
}

export default function Positions({ positions, onRefresh, portfolioId, totalValue }) {
  const isReal = portfolioId === 0
  const [protection, setProtection] = useState({})
  const [activeTab, setActiveTab]   = useState('all')

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

  // Build tab counts
  const tabCounts = { all: positions.length, equities: 0, crypto: 0, forex: 0, futures: 0 }
  positions.forEach(p => { tabCounts[getTab(p.symbol)] = (tabCounts[getTab(p.symbol)] || 0) + 1 })
  const availableTabs = ['all', 'equities', 'crypto', 'forex', 'futures'].filter(t => t === 'all' || tabCounts[t] > 0)

  // Filter positions by active tab
  const visible = activeTab === 'all' ? positions : positions.filter(p => getTab(p.symbol) === activeTab)

  // Split into longs and shorts
  const longs  = visible.filter(p => p.side !== 'short')
  const shorts = visible.filter(p => p.side === 'short')

  const totalPL = visible.reduce((s, p) => s + (p.unrealized_pl || 0), 0)
  const plPos   = totalPL >= 0

  return (
    <div className="widget" style={{ padding: '0' }}>
      {/* Header */}
      <div style={{ padding: '10px 14px 0' }}>
        <div className="widget-hd" style={{ marginBottom: 0 }}>
          <span>{isReal ? 'Holdings' : 'Positions'}</span>
          <span className="badge" style={{ marginLeft: 6 }}>{positions.length}</span>
          {visible.length > 0 && (
            <span style={{ marginLeft: 'auto', fontSize: 10, fontFamily: 'var(--font-mono)', fontWeight: 700, color: plPos ? 'var(--ok)' : 'var(--err)' }}>
              {plPos ? '+' : ''}{totalPL.toFixed(2)}
            </span>
          )}
        </div>
      </div>

      {/* Tab bar */}
      {positions.length > 0 && availableTabs.length > 1 && (
        <div style={{ display: 'flex', borderBottom: '1px solid rgba(140,170,220,0.08)', padding: '0 14px', marginTop: 8 }}>
          {availableTabs.map(tab => {
            const meta = TAB_META[tab]
            const active = activeTab === tab
            return (
              <button key={tab} onClick={() => setActiveTab(tab)} style={{
                padding: '5px 10px 6px', border: 'none', cursor: 'pointer', background: 'transparent',
                fontSize: 9.5, fontWeight: active ? 700 : 400,
                color: active ? (tab === 'all' ? 'var(--t-1)' : meta.dot) : 'var(--t-4)',
                borderBottom: active ? `2px solid ${tab === 'all' ? 'var(--acc)' : meta.dot}` : '2px solid transparent',
                transition: 'color 0.15s',
                display: 'flex', alignItems: 'center', gap: 4,
              }}>
                {tab !== 'all' && <div style={{ width: 5, height: 5, borderRadius: '50%', background: active ? meta.dot : 'var(--t-4)', flexShrink: 0, transition: 'background 0.15s' }} />}
                {meta.label}
                <span style={{ fontSize: 8.5, opacity: 0.7 }}>{tabCounts[tab]}</span>
              </button>
            )
          })}
        </div>
      )}

      {/* Content */}
      <div style={{ padding: '4px 14px 10px' }}>
        {positions.length === 0
          ? <div className="empty-state">{isReal ? 'No holdings tracked' : 'No open positions'}</div>
          : (
            <div style={{ overflowY: 'auto', maxHeight: 320 }}>
              {visible.length === 0
                ? <div style={{ color: 'var(--t-4)', fontSize: 11, textAlign: 'center', padding: '16px 0' }}>No {activeTab} positions</div>
                : (
                  <>
                    <SideGroup label="Long" color="#4ad9ff" positions={longs} isReal={isReal} totalValue={totalValue} protection={protection} onClose={closePosition} />
                    <SideGroup label="Short" color="#ff6a6a" positions={shorts} isReal={isReal} totalValue={totalValue} protection={protection} onClose={closePosition} />
                  </>
                )
              }
            </div>
          )
        }
      </div>
    </div>
  )
}

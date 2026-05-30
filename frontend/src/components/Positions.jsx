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

function PositionCard({ p, isReal, totalValue, onClose }) {
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
          {plPos ? '+' : ''}{fmt(p.unrealized_pl)}
          <span style={{ fontSize: 8.5, fontWeight: 400, color: 'var(--t-4)', marginLeft: 3 }}>
            ({plPos ? '+' : ''}{fmt(p.unrealized_plpc * 100)}%)
          </span>
        </span>
      </div>
    </div>
  )
}

export default function Positions({ positions, onRefresh, portfolioId, totalValue }) {
  const isReal = portfolioId === 0

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

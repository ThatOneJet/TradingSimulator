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
  crypto:   { label: 'Crypto', dot: '#4ad9ff', badge: '24/7' },
  forex:    { label: 'Forex',  dot: '#a78bfa', badge: '24/7' },
  equities: { label: 'Equities', dot: '#f59e0b', badge: 'Market Hours' },
}

export default function Positions({ positions, onRefresh, portfolioId, totalValue }) {
  const isReal = portfolioId === 0

  async function closePosition(symbol, qty, side) {
    try {
      const orderSide = side === 'short' ? 'cover' : 'sell'
      const absQty    = Math.abs(qty)
      await api.post('/orders', { symbol, qty: absQty, side: orderSide, type: 'market', portfolio_id: portfolioId || 1 })
      setTimeout(onRefresh, 800)
    } catch {}
  }

  const shorts = positions.filter(p => p.side === 'short')

  // Group by category, preserving sort within each group
  const groups = { crypto: [], forex: [], equities: [] }
  for (const p of positions) groups[getCategory(p.symbol)].push(p)

  const orderedGroups = ['crypto', 'forex', 'equities'].filter(g => groups[g].length > 0)

  function PositionRow({ p }) {
    const isShort = p.side === 'short'
    const absQty  = Math.abs(p.qty)
    const mktVal  = absQty * p.current_price
    const pct     = totalValue > 0 ? (mktVal / totalValue * 100) : 0
    const barW    = Math.min(100, pct * 4)

    return (
      <tr key={p.symbol + (isShort ? '-short' : '')}>
        <td className="mono bold" style={{ paddingBottom: 6 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            {p.symbol}
            {isShort && (
              <span style={{
                fontSize: 7, fontWeight: 700, color: '#ff476f',
                border: '1px solid rgba(255,71,111,0.4)', borderRadius: 3,
                padding: '1px 3px', lineHeight: 1.4, letterSpacing: '0.04em',
              }}>
                SHORT
              </span>
            )}
          </div>
          {totalValue > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 2 }}>
              <div style={{ width: 28, height: 2, background: 'rgba(140,170,220,0.12)', borderRadius: 1 }}>
                <div style={{
                  width: `${barW}%`, height: '100%',
                  background: isShort ? '#ff6a6a' : '#4ad9ff',
                  borderRadius: 1, opacity: 0.75,
                }} />
              </div>
              <span style={{ fontSize: 8.5, color: 'var(--t-4)', fontFamily: 'var(--font-mono)', letterSpacing: '0.02em' }}>
                {pct.toFixed(1)}%
              </span>
            </div>
          )}
        </td>
        <td className="mono" style={{ color: isShort ? '#ff6a6a' : undefined }}>
          {isShort ? '-' : ''}{absQty}
        </td>
        <td className="mono muted">${Number(p.avg_entry_price).toFixed(2)}</td>
        <td className="mono">${Number(p.current_price).toFixed(2)}</td>
        <td className="mono" style={{ color: p.unrealized_pl >= 0 ? 'var(--ok)' : 'var(--err)', whiteSpace: 'nowrap' }}>
          {p.unrealized_pl >= 0 ? '+' : ''}{Number(p.unrealized_pl).toFixed(2)}
          <span className="muted"> ({(p.unrealized_plpc * 100).toFixed(2)}%)</span>
        </td>
        {!isReal && (
          <td>
            <button
              className="close-btn"
              onClick={() => closePosition(p.symbol, p.qty, p.side)}
              title={isShort ? 'Cover short' : 'Close position'}
              style={isShort ? { color: '#ff476f' } : undefined}
            >
              {isShort ? '↑' : '✕'}
            </button>
          </td>
        )}
      </tr>
    )
  }

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
          <div style={{ overflowX: 'auto', overflowY: 'auto', maxHeight: 300, width: '100%' }}>
            {orderedGroups.map(cat => {
              const meta = CATEGORY_META[cat]
              return (
                <div key={cat}>
                  {/* Category separator */}
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 6,
                    padding: '6px 0 4px',
                    borderBottom: '1px solid rgba(140,170,220,0.08)',
                    marginBottom: 2,
                  }}>
                    <div style={{ width: 6, height: 6, borderRadius: '50%', background: meta.dot, flexShrink: 0 }} />
                    <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--t-3)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                      {meta.label}
                    </span>
                    <span style={{
                      fontSize: 8.5, color: is24_7(groups[cat][0]?.symbol) ? '#4ade80' : '#f59e0b',
                      background: is24_7(groups[cat][0]?.symbol) ? 'rgba(74,222,128,0.1)' : 'rgba(245,158,11,0.1)',
                      border: `1px solid ${is24_7(groups[cat][0]?.symbol) ? 'rgba(74,222,128,0.25)' : 'rgba(245,158,11,0.25)'}`,
                      borderRadius: 3, padding: '1px 4px', lineHeight: 1.5,
                    }}>
                      {meta.badge}
                    </span>
                    <span style={{ fontSize: 9, color: 'var(--t-4)', marginLeft: 'auto' }}>
                      {groups[cat].length} position{groups[cat].length !== 1 ? 's' : ''}
                    </span>
                  </div>

                  <table className="pos-table" style={{ minWidth: isReal ? 280 : 340, width: '100%', marginBottom: 4 }}>
                    <thead>
                      <tr>
                        <th>Symbol</th><th>Qty</th><th>Avg</th><th>Price</th><th>P&L</th>
                        {!isReal && <th />}
                      </tr>
                    </thead>
                    <tbody>
                      {groups[cat].map(p => <PositionRow key={p.symbol + (p.side === 'short' ? '-short' : '')} p={p} />)}
                    </tbody>
                  </table>
                </div>
              )
            })}
          </div>
        )
      }
    </div>
  )
}

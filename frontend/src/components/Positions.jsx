import api from '../api.js'

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
          <div style={{ overflowX: 'auto', overflowY: 'auto', maxHeight: 260, width: '100%', display: 'block' }}>
            <table className="pos-table" style={{ minWidth: isReal ? 280 : 340 }}>
              <thead>
                <tr>
                  <th>Symbol</th><th>Qty</th><th>Avg</th><th>Price</th><th>P&L</th>
                  {!isReal && <th />}
                </tr>
              </thead>
              <tbody>
                {positions.map(p => {
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
                })}
              </tbody>
            </table>
          </div>
        )
      }
    </div>
  )
}

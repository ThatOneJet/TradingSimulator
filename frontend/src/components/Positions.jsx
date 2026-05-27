import api from '../api.js'

export default function Positions({ positions, onRefresh, portfolioId }) {
  async function closePosition(symbol, qty) {
    try {
      await api.post('/orders', { symbol, qty, side: 'sell', type: 'market', portfolio_id: portfolioId || 1 })
      setTimeout(onRefresh, 800)
    } catch {}
  }

  return (
    <div className="widget" style={{ padding: '12px 14px' }}>
      <div className="widget-hd">
        Positions
        <span className="badge" style={{ marginLeft: 6 }}>{positions.length}</span>
      </div>
      {positions.length === 0
        ? <div className="empty-state">No open positions</div>
        : (
          <div style={{ overflowX: 'auto', overflowY: 'auto', maxHeight: 220 }}>
            <table className="pos-table" style={{ minWidth: 340 }}>
              <thead>
                <tr>
                  <th>Symbol</th><th>Qty</th><th>Avg</th><th>Price</th><th>P&L</th><th />
                </tr>
              </thead>
              <tbody>
                {positions.map(p => (
                  <tr key={p.symbol}>
                    <td className="mono bold">{p.symbol}</td>
                    <td className="mono">{p.qty}</td>
                    <td className="mono muted">${Number(p.avg_entry_price).toFixed(2)}</td>
                    <td className="mono">${Number(p.current_price).toFixed(2)}</td>
                    <td className="mono" style={{ color: p.unrealized_pl >= 0 ? 'var(--ok)' : 'var(--err)', whiteSpace: 'nowrap' }}>
                      {p.unrealized_pl >= 0 ? '+' : ''}{Number(p.unrealized_pl).toFixed(2)}
                      <span className="muted"> ({(p.unrealized_plpc * 100).toFixed(2)}%)</span>
                    </td>
                    <td>
                      <button className="close-btn" onClick={() => closePosition(p.symbol, p.qty)} title="Close">✕</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      }
    </div>
  )
}

export default function OrderBook({ symbol, quote }) {
  const bid    = quote?.bid ?? 0
  const ask    = quote?.ask ?? 0
  const bidSz  = quote?.bid_size ?? 0
  const askSz  = quote?.ask_size ?? 0
  const spread = ask - bid
  const spreadPct = bid > 0 ? ((spread / bid) * 100).toFixed(3) : '—'

  return (
    <div className="widget" style={{ padding: '12px 14px' }}>
      <div className="widget-hd">
        Order Book
        <span className="muted" style={{ marginLeft: 6, fontSize: 11 }}>{symbol}</span>
      </div>
      <div className="ob-spread" style={{ marginBottom: 8, fontSize: 11, color: 'var(--t-3)' }}>
        SPREAD <span className="mono" style={{ color: 'var(--cy)' }}>
          {spread > 0 ? `$${spread.toFixed(4)}` : '—'}
        </span>
        <span className="muted"> ({spreadPct}%)</span>
      </div>
      <table className="ob-table" style={{ width: '100%', tableLayout: 'fixed' }}>
        <thead>
          <tr>
            <th>Price</th><th>Size</th><th>Side</th>
          </tr>
        </thead>
        <tbody>
          <tr className="ob-ask">
            <td className="mono err" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ask > 0 ? ask.toFixed(2) : '—'}</td>
            <td className="mono" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{askSz || '—'}</td>
            <td style={{ color: 'var(--err)', fontSize: 10, letterSpacing: '0.06em', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>ASK</td>
          </tr>
          <tr className="ob-bid">
            <td className="mono ok" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{bid > 0 ? bid.toFixed(2) : '—'}</td>
            <td className="mono" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{bidSz || '—'}</td>
            <td style={{ color: 'var(--ok)', fontSize: 10, letterSpacing: '0.06em', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>BID</td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}

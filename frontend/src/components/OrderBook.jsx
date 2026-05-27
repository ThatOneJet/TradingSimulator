export default function OrderBook({ symbol, quote }) {
  const bid = quote?.bid ?? 0
  const ask = quote?.ask ?? 0
  const bidSz = quote?.bid_size ?? 0
  const askSz = quote?.ask_size ?? 0
  const spread = ask - bid
  const spreadPct = bid > 0 ? ((spread / bid) * 100).toFixed(3) : '—'

  return (
    <div className="card order-book">
      <div className="card-header">Order Book <span className="muted">{symbol}</span></div>
      <div className="ob-spread">SPREAD <span className="mono">${spread > 0 ? spread.toFixed(4) : '—'}</span> <span className="muted">({spreadPct}%)</span></div>
      <table className="ob-table">
        <thead><tr><th>Price</th><th>Size</th><th>Side</th></tr></thead>
        <tbody>
          <tr className="ob-ask"><td className="mono err">{ask > 0 ? ask.toFixed(2) : '—'}</td><td className="mono">{askSz}</td><td>ASK</td></tr>
          <tr className="ob-bid"><td className="mono ok">{bid > 0 ? bid.toFixed(2) : '—'}</td><td className="mono">{bidSz}</td><td>BID</td></tr>
        </tbody>
      </table>
      <div className="ob-note">IEX free tier: best bid/ask only</div>
    </div>
  )
}

import { useState, useEffect } from 'react'
import SymbolSearch from './SymbolSearch.jsx'
import api from '../api.js'

// ── Real Portfolio tab ──────────────────────────────────────────────────────
function RealPortfolio({ onSelectSymbol }) {
  const [holdings, setHoldings] = useState([])
  const [loading,  setLoading]  = useState(false)

  // Form state
  const [sym,       setSym]       = useState('')
  const [shares,    setShares]    = useState('')
  const [buyDate,   setBuyDate]   = useState('')
  const [buyPrice,  setBuyPrice]  = useState('')
  const [note,      setNote]      = useState('')
  const [adding,    setAdding]    = useState(false)
  const [formErr,   setFormErr]   = useState('')
  const [priceHint, setPriceHint] = useState('')

  function load() {
    setLoading(true)
    api.get('/holdings').then(r => { setHoldings(r.data); setLoading(false) }).catch(() => setLoading(false))
  }
  useEffect(() => { load(); const id = setInterval(load, 15000); return () => clearInterval(id) }, [])

  async function submit(e) {
    e.preventDefault()
    setFormErr('')
    if (!sym || !shares || !buyDate) { setFormErr('Symbol, shares, and date are required'); return }
    setAdding(true)
    try {
      const body = { symbol: sym, shares: Number(shares), buy_date: buyDate, note }
      if (buyPrice) body.buy_price = Number(buyPrice)
      else setPriceHint('auto-fetching price…')
      await api.post('/holdings', body)
      setSym(''); setShares(''); setBuyDate(''); setBuyPrice(''); setNote(''); setPriceHint('')
      load()
    } catch (err) {
      setFormErr(err.response?.data?.error || 'Failed to add position')
      setPriceHint('')
    }
    setAdding(false)
  }

  async function remove(id) {
    await api.delete(`/holdings/${id}`)
    load()
  }

  const totalCost  = holdings.reduce((s, h) => s + (h.cost_basis || 0), 0)
  const totalValue = holdings.reduce((s, h) => s + (h.market_value || 0), 0)
  const totalPnl   = holdings.reduce((s, h) => s + (h.pnl || 0), 0)
  const totalPct   = totalCost > 0 ? (totalPnl / totalCost * 100) : 0

  const fmt      = (n, d = 2) => n != null ? Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d }) : '—'
  const pnlColor = (v) => v == null ? 'var(--t-3)' : v >= 0 ? 'var(--ok)' : 'var(--err)'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>

      {/* Add Position form */}
      <div className="widget" style={{ padding: '14px 16px' }}>
        <div className="widget-hd">Add Position</div>
        <form onSubmit={submit}>
          <div className="hf-row">
            <div className="hf-field wide">
              <label>Symbol</label>
              <SymbolSearch
                value={sym}
                onChange={setSym}
                onSelect={a => setSym(a.symbol)}
                placeholder="Search symbol or company…"
              />
            </div>
            <div className="hf-field">
              <label>Shares</label>
              <input type="number" step="0.001" min="0.001" value={shares} onChange={e => setShares(e.target.value)} placeholder="0" />
            </div>
            <div className="hf-field">
              <label>Purchase date</label>
              <input type="date" value={buyDate} onChange={e => setBuyDate(e.target.value)} max={new Date().toISOString().split('T')[0]} />
            </div>
            <div className="hf-field">
              <label>Price per share <span className="muted">(optional — auto-fetched)</span></label>
              <input type="number" step="0.01" min="0" value={buyPrice} onChange={e => setBuyPrice(e.target.value)} placeholder="auto" />
            </div>
            <div className="hf-field wide">
              <label>Note <span className="muted">(optional)</span></label>
              <input type="text" value={note} onChange={e => setNote(e.target.value)} placeholder="e.g. Roth IRA, DCA…" />
            </div>
          </div>
          {priceHint && <div className="hf-hint">{priceHint}</div>}
          {formErr   && <div className="of-err">{formErr}</div>}
          <button type="submit" className="hf-submit" disabled={adding}>
            {adding ? 'Adding…' : 'Add Position'}
          </button>
        </form>
      </div>

      {/* Holdings table */}
      <div className="widget" style={{ padding: '14px 16px', flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <div className="widget-hd">
          My Holdings
          <span className="badge" style={{ marginLeft: 4 }}>{holdings.length}</span>
          {totalValue > 0 && (
            <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 12, color: pnlColor(totalPnl) }}>
              {totalPnl >= 0 ? '+' : ''}${fmt(totalPnl)} ({totalPct >= 0 ? '+' : ''}{fmt(totalPct)}%)
            </span>
          )}
        </div>

        {holdings.length === 0 && !loading && (
          <div className="empty-state">No positions yet — add your first above</div>
        )}

        {holdings.length > 0 && (
          <div className="holdings-scroll">
            <table className="holdings-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Shares</th>
                  <th>Bought</th>
                  <th>Buy Price</th>
                  <th>Cost Basis</th>
                  <th>Current</th>
                  <th>Value</th>
                  <th>P&amp;L</th>
                  <th>%</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {holdings.map(h => (
                  <tr key={h.id} className="holdings-row" onClick={() => onSelectSymbol?.(h.symbol)}>
                    <td className="mono bold" style={{ color: 'var(--cy)' }}>{h.symbol}</td>
                    <td className="mono">{h.shares}</td>
                    <td className="muted">{h.buy_date}</td>
                    <td className="mono">${fmt(h.buy_price)}</td>
                    <td className="mono">${fmt(h.cost_basis)}</td>
                    <td className="mono">{h.current_price != null ? `$${fmt(h.current_price)}` : '—'}</td>
                    <td className="mono">{h.market_value != null ? `$${fmt(h.market_value)}` : '—'}</td>
                    <td className="mono" style={{ color: pnlColor(h.pnl) }}>
                      {h.pnl != null ? `${h.pnl >= 0 ? '+' : ''}$${fmt(h.pnl)}` : '—'}
                    </td>
                    <td className="mono" style={{ color: pnlColor(h.pnl_pct) }}>
                      {h.pnl_pct != null ? `${h.pnl_pct >= 0 ? '+' : ''}${fmt(h.pnl_pct)}%` : '—'}
                    </td>
                    <td>
                      <button className="close-btn" onClick={e => { e.stopPropagation(); remove(h.id) }}>✕</button>
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="holdings-totals">
                  <td colSpan="4" className="muted">TOTAL</td>
                  <td className="mono">${fmt(totalCost)}</td>
                  <td />
                  <td className="mono">{totalValue > 0 ? `$${fmt(totalValue)}` : '—'}</td>
                  <td className="mono" style={{ color: pnlColor(totalPnl) }}>
                    {totalPnl !== 0 ? `${totalPnl >= 0 ? '+' : ''}$${fmt(totalPnl)}` : '—'}
                  </td>
                  <td className="mono" style={{ color: pnlColor(totalPct) }}>
                    {totalValue > 0 ? `${totalPct >= 0 ? '+' : ''}${fmt(totalPct)}%` : '—'}
                  </td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Trade row with collapsible reasoning ─────────────────────────────────────
function TradeRow({ o }) {
  const [open, setOpen] = useState(false)
  const side = (o.side || '').toLowerCase()
  const isClose = side === 'sell' || side === 'cover'
  const pl = o.pl ?? o.realized_pl ?? null
  const plPos = pl != null && pl >= 0
  const hasReason = !!o.reason

  const sideColor = side === 'buy'   ? '#3ddc97'
                  : side === 'sell'  ? '#ff476f'
                  : side === 'short' ? '#ff6a6a'
                  : '#4ad9ff' // cover

  const fmtQty = (q) => {
    const n = Number(q)
    if (isNaN(n)) return q
    return n >= 1 ? n.toFixed(2) : n.toFixed(4)
  }

  const fmtTime = (ts) => {
    if (!ts) return '—'
    const d = new Date(ts.endsWith('Z') ? ts : ts + 'Z')
    return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  }

  return (
    <div style={{ borderBottom: '1px solid rgba(140,170,220,0.05)' }}>
      {/* Main row */}
      <div
        onClick={() => hasReason && setOpen(v => !v)}
        style={{
          display: 'grid', gridTemplateColumns: '1.4fr 0.7fr 1fr 0.8fr 0.9fr',
          gap: 4, padding: '7px 8px', alignItems: 'center',
          cursor: hasReason ? 'pointer' : 'default',
          transition: 'background 0.1s',
        }}
        onMouseEnter={e => { if (hasReason) e.currentTarget.style.background = 'rgba(140,170,220,0.04)' }}
        onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
      >
        {/* Symbol */}
        <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--cy)', fontSize: 12, display: 'flex', alignItems: 'center', gap: 5 }}>
          {o.symbol}
          {hasReason && <span style={{ fontSize: 8, color: 'var(--t-4)', opacity: 0.6 }}>{open ? '▲' : '▼'}</span>}
        </span>
        {/* Side */}
        <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: sideColor, fontSize: 10, textTransform: 'uppercase' }}>
          {o.side}
        </span>
        {/* Qty */}
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t-2)' }}>
          {fmtQty(o.qty)}
        </span>
        {/* Fill price + P&L inline */}
        <div>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t-1)' }}>
            ${Number(o.price ?? o.fill_price ?? 0).toFixed(2)}
          </span>
          {isClose && pl != null && (
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, fontWeight: 700, color: plPos ? 'var(--ok)' : 'var(--err)', marginTop: 1 }}>
              {plPos ? '+' : ''}${Number(pl).toFixed(2)}
            </div>
          )}
        </div>
        {/* Time */}
        <span style={{ fontSize: 10, color: 'var(--t-4)' }}>
          {fmtTime(o.created_at)}
        </span>
      </div>

      {/* Expanded reasoning */}
      {open && hasReason && (
        <div style={{
          margin: '0 8px 8px 8px', padding: '8px 10px',
          background: 'rgba(0,0,0,0.2)', borderRadius: 6,
          border: `1px solid ${sideColor}20`,
        }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
            {o.ai_score != null && (
              <span style={{ fontSize: 8.5, fontFamily: 'var(--font-mono)', fontWeight: 700, color: Number(o.ai_score) >= 0 ? 'var(--ok)' : 'var(--err)' }}>
                score {Number(o.ai_score) >= 0 ? '+' : ''}{Number(o.ai_score).toFixed(2)}
              </span>
            )}
            {o.market_state && (
              <span style={{ fontSize: 8, color: '#f5b342', background: 'rgba(245,179,66,0.1)', border: '1px solid rgba(245,179,66,0.25)', borderRadius: 3, padding: '1px 5px', fontFamily: 'var(--font-mono)' }}>
                {o.market_state.replace(/_/g, ' ')}
              </span>
            )}
            {o.strategy && (
              <span style={{ fontSize: 8, color: '#4ad9ff', background: 'rgba(74,217,255,0.08)', border: '1px solid rgba(74,217,255,0.2)', borderRadius: 3, padding: '1px 5px', fontFamily: 'var(--font-mono)' }}>
                {o.strategy}
              </span>
            )}
          </div>
          <div style={{ fontSize: 9.5, color: 'var(--t-2)', lineHeight: 1.65 }}>{o.reason}</div>
        </div>
      )}
    </div>
  )
}

// ── Sim Portfolio tab ───────────────────────────────────────────────────────
function SimPortfolio({ positions, portfolioId, onSelectSymbol, onRefresh }) {
  const [orders,  setOrders]  = useState([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!portfolioId) return
    setLoading(true)
    api.get(`/portfolios/${portfolioId}/trades?limit=200`)
      .then(r => { setOrders(r.data?.trades || []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [portfolioId])

  async function closePosition(symbol, qty) {
    try {
      await api.post('/orders', { symbol, qty, side: 'sell', type: 'market', portfolio_id: portfolioId })
      setTimeout(onRefresh, 800)
    } catch {}
  }

  const fmt = (n, d = 2) => n != null ? Number(n).toFixed(d) : '—'

  function fmtTimestamp(ts) {
    if (!ts) return '—'
    try {
      return new Date(ts).toLocaleString('en-US', {
        month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit', hour12: false,
      })
    } catch { return ts }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>

      {/* Open Positions */}
      <div className="widget" style={{ padding: '14px 16px' }}>
        <div className="widget-hd">
          Open Positions
          <span className="badge" style={{ marginLeft: 4 }}>{positions.length}</span>
        </div>

        {positions.length === 0
          ? <div className="empty-state">No open positions</div>
          : (
            <div style={{ overflowX: 'auto' }}>
              <table className="pos-table" style={{ minWidth: 500 }}>
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Qty</th>
                    <th>Avg Entry</th>
                    <th>Current Price</th>
                    <th>Unrealized P&amp;L</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {positions.map(p => (
                    <tr key={p.symbol}>
                      <td className="mono bold" style={{ color: 'var(--cy)' }}>{p.symbol}</td>
                      <td className="mono">{p.qty}</td>
                      <td className="mono muted">${fmt(p.avg_entry_price)}</td>
                      <td className="mono">${fmt(p.current_price)}</td>
                      <td className="mono" style={{
                        color: p.unrealized_pl >= 0 ? 'var(--ok)' : 'var(--err)',
                        whiteSpace: 'nowrap',
                      }}>
                        {p.unrealized_pl >= 0 ? '+' : ''}{fmt(p.unrealized_pl)}
                        <span className="muted"> ({(p.unrealized_plpc * 100).toFixed(2)}%)</span>
                      </td>
                      <td style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                        <button
                          className="sim-action-btn"
                          onClick={() => onSelectSymbol?.(p.symbol)}
                          title="View chart"
                        >
                          Chart
                        </button>
                        <button
                          className="close-btn"
                          onClick={() => closePosition(p.symbol, p.qty)}
                          title="Close position"
                        >
                          Close
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
      </div>

      {/* Trade History */}
      <div className="widget" style={{ padding: '14px 16px' }}>
        <div className="widget-hd">
          Trade History
          {!loading && <span className="badge" style={{ marginLeft: 4 }}>{orders.length}</span>}
        </div>

        {loading && <div className="empty-state">Loading…</div>}

        {!loading && orders.length === 0 && (
          <div className="empty-state">No orders yet</div>
        )}

        {!loading && orders.length > 0 && (
          <div>
            {/* Column headers */}
            <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 0.7fr 1fr 0.8fr 0.9fr', gap: 4, padding: '4px 8px 6px', borderBottom: '1px solid rgba(140,170,220,0.1)' }}>
              {['SYMBOL','SIDE','QTY','FILL PRICE','TIME'].map(h => (
                <span key={h} style={{ fontSize: 8.5, color: 'var(--t-4)', fontFamily: 'var(--font-mono)', letterSpacing: '0.07em' }}>{h}</span>
              ))}
            </div>
            {orders.map((o, i) => <TradeRow key={o.id ?? i} o={o} />)}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main unified Holdings page ──────────────────────────────────────────────
export default function Holdings({ onSelectSymbol, portfolioId, positions = [], onRefresh }) {
  const [activeTab, setActiveTab] = useState('real')

  const tabStyle = (tab) => ({
    padding: '6px 18px',
    borderRadius: 99,
    border: 'none',
    cursor: 'pointer',
    fontSize: 12,
    fontWeight: 600,
    fontFamily: 'var(--font-sans)',
    letterSpacing: '0.04em',
    transition: 'all .15s',
    background: activeTab === tab ? 'var(--acc-soft)' : 'transparent',
    color: activeTab === tab ? 'var(--acc)' : 'var(--t-3)',
    outline: activeTab === tab ? '1px solid var(--acc-line)' : '1px solid transparent',
  })

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      overflow: 'hidden',
      background: 'var(--bg-main)',
    }}>
      {/* Tab switcher bar */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        padding: '8px 16px',
        borderBottom: '1px solid var(--hairline)',
        background: 'var(--bg-main)',
        flexShrink: 0,
      }}>
        <button style={tabStyle('real')} onClick={() => setActiveTab('real')}>
          Real Portfolio
        </button>
        <button style={tabStyle('sim')} onClick={() => setActiveTab('sim')}>
          Sim Portfolio
        </button>
      </div>

      {/* Tab content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 12px', display: 'flex', flexDirection: 'column' }}>
        {activeTab === 'real' && (
          <RealPortfolio onSelectSymbol={onSelectSymbol} />
        )}
        {activeTab === 'sim' && (
          <SimPortfolio
            positions={positions}
            portfolioId={portfolioId}
            onSelectSymbol={onSelectSymbol}
            onRefresh={onRefresh}
          />
        )}
      </div>
    </div>
  )
}

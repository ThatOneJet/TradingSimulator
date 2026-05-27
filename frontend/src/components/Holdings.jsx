import { useState, useEffect } from 'react'
import SymbolSearch from './SymbolSearch.jsx'
import api from '../api.js'

export default function Holdings({ onSelectSymbol }) {
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
  const [priceHint, setPriceHint] = useState('')  // "auto-fetching…" indicator

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

  // Totals
  const totalCost  = holdings.reduce((s, h) => s + (h.cost_basis || 0), 0)
  const totalValue = holdings.reduce((s, h) => s + (h.market_value || 0), 0)
  const totalPnl   = holdings.reduce((s, h) => s + (h.pnl || 0), 0)
  const totalPct   = totalCost > 0 ? (totalPnl / totalCost * 100) : 0

  const fmt  = (n, d = 2) => n != null ? Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d }) : '—'
  const pnlColor = (v) => v == null ? 'var(--muted)' : v >= 0 ? 'var(--ok)' : 'var(--err)'

  return (
    <div className="holdings-view">
      {/* Add form */}
      <div className="card holdings-form">
        <div className="card-header">Add Position</div>
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
          {formErr && <div className="of-err">{formErr}</div>}
          <button type="submit" className="hf-submit" disabled={adding}>
            {adding ? 'Adding…' : 'Add Position'}
          </button>
        </form>
      </div>

      {/* Holdings table */}
      <div className="card holdings-table-wrap">
        <div className="card-header">
          My Holdings
          <span className="badge">{holdings.length}</span>
          {totalValue > 0 && (
            <span style={{ marginLeft: 'auto', fontFamily: 'Roboto Mono', fontSize: 12, color: pnlColor(totalPnl) }}>
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
                    <td className="mono bold acc">{h.symbol}</td>
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

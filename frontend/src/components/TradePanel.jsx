import { useState, useEffect } from 'react'
import api from '../api.js'
import ConfirmModal from './ConfirmModal.jsx'

function PortfolioCard({ account, onReset, portfolioId }) {
  const [resetting,   setResetting]   = useState(false)
  const [msg,         setMsg]         = useState('')
  const [resetModal,  setResetModal]  = useState(false)

  async function handleReset() {
    setResetModal(false)
    setResetting(true)
    try {
      const r = await api.post('/account/reset', { portfolio_id: portfolioId || 1 })
      setMsg(r.data.message || 'Reset.')
      onReset?.()
    } catch { setMsg('Failed.') }
    setResetting(false)
    setTimeout(() => setMsg(''), 4000)
  }

  if (!account) return (
    <div className="tp-card">
      <div className="tp-skeleton-line" style={{ width: '55%', marginBottom: 10 }} />
      <div className="tp-skeleton-line" style={{ width: '40%' }} />
    </div>
  )

  const isReal = account.is_real
  const fmt = n => Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  const pnl      = isReal ? account.pnl : account.pnl_day
  const pnlDay   = account.pnl_day
  const pnlColor = pnl != null && pnl >= 0 ? 'var(--ok)' : 'var(--err)'
  const dayColor = pnlDay != null && pnlDay >= 0 ? 'var(--ok)' : 'var(--err)'

  return (
    <div className="tp-card">
      <div className="tp-card-hd">
        {isReal ? 'Real Holdings' : 'Portfolio'}
        {!isReal && (
          <button className="pf-reset-btn" onClick={() => setResetModal(true)} disabled={resetting}>
            {resetting ? '…' : 'Reset'}
          </button>
        )}
        {isReal && <span className="tp-badge-real">READ-ONLY</span>}
        {resetModal && (
          <ConfirmModal
            message="Reset account to $100,000?"
            detail="All positions will be cleared."
            confirmLabel="Reset"
            danger
            onConfirm={handleReset}
            onCancel={() => setResetModal(false)}
          />
        )}
      </div>
      <div className="tp-metrics">
        <div className="tp-metric">
          <span className="tp-lbl">EQUITY</span>
          <span className="tp-val mono">${fmt(account.equity)}</span>
        </div>
        {isReal ? (
          <div className="tp-metric">
            <span className="tp-lbl">COST BASIS</span>
            <span className="tp-val mono">${fmt(account.initial_cost ?? 0)}</span>
          </div>
        ) : (
          <div className="tp-metric">
            <span className="tp-lbl" title={account.cash > (account.equity - (account.pnl_unrealized || 0)) ? 'Includes short sale proceeds held as collateral' : 'Available cash'}>
              CASH {account.cash > 100001 ? '⚠' : ''}
            </span>
            <span className="tp-val mono" style={{ fontSize: account.cash > 110000 ? 11 : undefined }}>
              ${fmt(account.cash)}
              {account.cash > 100001 && (
                <span style={{ display: 'block', fontSize: 8, color: 'var(--t-4)', fontWeight: 400 }}>incl. short proceeds</span>
              )}
            </span>
          </div>
        )}
        <div className="tp-metric">
          <span className="tp-lbl">{isReal ? 'TOTAL P&L' : 'DAY P&L'}</span>
          <span className="tp-val mono" style={{ color: pnlColor }}>
            {pnl != null ? `${pnl >= 0 ? '+' : ''}$${fmt(pnl)}` : '—'}
          </span>
        </div>
        {isReal ? (
          <div className="tp-metric">
            <span className="tp-lbl">RETURN</span>
            <span className="tp-val mono" style={{ color: pnlColor }}>
              {account.pnl_pct != null
                ? `${account.pnl_pct >= 0 ? '+' : ''}${Number(account.pnl_pct).toFixed(2)}%`
                : '—'}
            </span>
          </div>
        ) : (
          <div className="tp-metric">
            <span className="tp-lbl">BUYING PWR</span>
            <span className="tp-val mono">${fmt(account.buying_power)}</span>
          </div>
        )}
        {isReal && (
          <div className="tp-metric tp-metric-full">
            <span className="tp-lbl">DAY P&L</span>
            <span className="tp-val mono" style={{ color: pnlDay != null ? dayColor : 'var(--t-3)' }}>
              {pnlDay != null ? `${pnlDay >= 0 ? '+' : ''}$${fmt(pnlDay)}` : '— (no prior close)'}
            </span>
          </div>
        )}
      </div>
      {msg && <div className="tp-msg">{msg}</div>}
    </div>
  )
}

function PositionCard({ pos, portfolioId, onOrderPlaced }) {
  const isReal = portfolioId === 0
  const fmt = n => Number(n).toFixed(2)
  const pnlColor = pos.unrealized_pl >= 0 ? 'var(--ok)' : 'var(--err)'

  async function closeAll() {
    try {
      await api.post('/orders', {
        symbol: pos.symbol,
        qty: pos.qty,
        side: 'sell',
        type: 'market',
        portfolio_id: portfolioId || 1,
      })
      onOrderPlaced?.()
    } catch {}
  }

  return (
    <div className="tp-card tp-position-card">
      <div className="tp-card-hd">
        Position
        {!isReal && (
          <button className="close-btn" onClick={closeAll} title="Close entire position"
            style={{ marginLeft: 'auto', fontSize: 10, padding: '2px 8px' }}>
            Close All
          </button>
        )}
      </div>
      <div className="tp-metrics">
        <div className="tp-metric">
          <span className="tp-lbl">
            {pos.qty < 0 ? 'SHORT QTY' : 'SHARES'}
          </span>
          <span className="tp-val mono" style={{ color: pos.qty < 0 ? '#ff6a6a' : undefined }}>
            {pos.qty < 0 && <span style={{ fontSize: 8, background: 'rgba(255,71,111,0.15)', color: '#ff476f', border: '1px solid rgba(255,71,111,0.3)', borderRadius: 3, padding: '1px 4px', marginRight: 5 }}>SHORT</span>}
            {Math.abs(pos.qty).toFixed(4)}
          </span>
        </div>
        <div className="tp-metric">
          <span className="tp-lbl">AVG COST</span>
          <span className="tp-val mono">${fmt(pos.avg_entry_price)}</span>
        </div>
        <div className="tp-metric">
          <span className="tp-lbl">CURRENT</span>
          <span className="tp-val mono">${fmt(pos.current_price)}</span>
        </div>
        <div className="tp-metric">
          <span className="tp-lbl">UNREAL. P&amp;L</span>
          <span className="tp-val mono" style={{ color: pnlColor }}>
            {pos.unrealized_pl >= 0 ? '+' : ''}${fmt(pos.unrealized_pl)}
            <span className="tp-pct"> ({(pos.unrealized_plpc * 100).toFixed(2)}%)</span>
          </span>
        </div>
      </div>
    </div>
  )
}

function OrderBookCard({ symbol, quote }) {
  const [book, setBook] = useState(null)
  const [loading, setLoading] = useState(false)
  const isCrypto = symbol?.endsWith('-USD')

  useEffect(() => {
    if (!symbol) return
    let cancelled = false
    const load = () => {
      if (!cancelled) setLoading(true)
      api.get(`/orderbook/${symbol}`)
        .then(r => { if (!cancelled) { setBook(r.data); setLoading(false) } })
        .catch(() => { if (!cancelled) setLoading(false) })
    }
    load()
    // Refresh every 3s for crypto, 10s for equities
    const id = setInterval(load, isCrypto ? 3000 : 10000)
    return () => { cancelled = true; clearInterval(id) }
  }, [symbol, isCrypto])

  const bid = book?.best_bid || quote?.bid || 0
  const ask = book?.best_ask || quote?.ask || 0
  const spread = book?.spread || (ask - bid)
  const spreadPct = book?.spread_pct || (bid > 0 ? (spread / bid * 100) : 0)
  const maxSize = book?.max_size || 1

  const fmtPrice = (p) => {
    if (!p) return '—'
    return p >= 100 ? p.toFixed(2) : p >= 1 ? p.toFixed(4) : p.toFixed(6)
  }
  const fmtSize = (s) => {
    if (!s) return ''
    if (s >= 1000) return `${(s/1000).toFixed(1)}K`
    if (s >= 1) return s.toFixed(3)
    return s.toFixed(6)
  }

  return (
    <div className="tp-card tp-ob-card">
      <div className="tp-card-hd">
        Order Book
        <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--t-3)', fontWeight: 400 }}>{symbol}</span>
        {loading && <span style={{ marginLeft: 'auto', fontSize: 9, color: 'var(--t-4)' }}>…</span>}
        {book?.source && !loading && (
          <span style={{ marginLeft: 'auto', fontSize: 8, color: 'var(--t-4)' }}>
            {book.source === 'coinbase' ? '● Coinbase L2' : '● IEX (1 level)'}
          </span>
        )}
      </div>

      {/* Spread row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8, padding: '4px 0', borderBottom: '1px solid rgba(140,170,220,0.07)' }}>
        <span style={{ fontSize: 9, color: 'var(--t-4)' }}>SPREAD</span>
        <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--cy)' }}>
          ${fmtPrice(spread)}
          <span style={{ fontSize: 8, color: 'var(--t-4)', marginLeft: 4 }}>({spreadPct.toFixed(3)}%)</span>
        </span>
      </div>

      {/* Liquidity balance bar (crypto only) */}
      {isCrypto && book?.total_bid_liquidity > 0 && (
        <div style={{ marginBottom: 8 }}>
          {(() => {
            const totalLiq = book.total_bid_liquidity + book.total_ask_liquidity
            const bidPct = totalLiq > 0 ? (book.total_bid_liquidity / totalLiq * 100) : 50
            const askPct = 100 - bidPct
            const bidDom = bidPct > 55
            return (
              <>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 8, color: 'var(--t-4)', marginBottom: 3 }}>
                  <span style={{ color: '#3ddc97' }}>Bids {bidPct.toFixed(0)}%</span>
                  <span style={{ color: '#ff476f' }}>Asks {askPct.toFixed(0)}%</span>
                </div>
                <div style={{ display: 'flex', height: 5, borderRadius: 3, overflow: 'hidden' }}>
                  <div style={{ width: `${bidPct}%`, background: '#3ddc97', opacity: 0.7 }} />
                  <div style={{ width: `${askPct}%`, background: '#ff476f', opacity: 0.7 }} />
                </div>
                <div style={{ fontSize: 8, color: bidDom ? '#3ddc97' : '#ff476f', textAlign: 'center', marginTop: 2 }}>
                  {bidDom ? '▲ Buy pressure dominates' : '▼ Sell pressure dominates'}
                </div>
              </>
            )
          })()}
        </div>
      )}

      {/* Order book table */}
      {book && book.asks?.length > 0 && (
        <div>
          {/* Column headers */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', padding: '2px 0', marginBottom: 2 }}>
            <span style={{ fontSize: 8, color: 'var(--t-4)', fontFamily: 'var(--font-mono)' }}>PRICE</span>
            <span style={{ fontSize: 8, color: 'var(--t-4)', fontFamily: 'var(--font-mono)', textAlign: 'right' }}>SIZE</span>
          </div>

          {/* Asks — show top 8, reversed so lowest ask is closest to spread */}
          <div>
            {[...(book.asks || [])].slice(0, 8).reverse().map((level, i) => {
              const [price, size] = level
              const barW = maxSize > 0 ? Math.min(100, size / maxSize * 100) : 0
              return (
                <div key={i} style={{ position: 'relative', display: 'grid', gridTemplateColumns: '1fr 1fr', padding: '1.5px 0', alignItems: 'center' }}>
                  <div style={{ position: 'absolute', right: 0, top: 0, bottom: 0, width: `${barW}%`, background: 'rgba(255,71,111,0.12)', borderRadius: 2 }} />
                  <span style={{ fontSize: 9.5, fontFamily: 'var(--font-mono)', color: '#ff476f', position: 'relative', zIndex: 1 }}>
                    {fmtPrice(price)}
                  </span>
                  <span style={{ fontSize: 9, fontFamily: 'var(--font-mono)', color: 'var(--t-3)', textAlign: 'right', position: 'relative', zIndex: 1 }}>
                    {fmtSize(size)}
                  </span>
                </div>
              )
            })}
          </div>

          {/* Mid price divider */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, margin: '4px 0', padding: '3px 0', borderTop: '1px solid rgba(140,170,220,0.15)', borderBottom: '1px solid rgba(140,170,220,0.15)' }}>
            <span style={{ fontSize: 11, fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--t-1)' }}>
              ${fmtPrice(book.mid_price)}
            </span>
            <span style={{ fontSize: 8, color: 'var(--t-4)' }}>MID</span>
          </div>

          {/* Bids — top 8 */}
          <div>
            {(book.bids || []).slice(0, 8).map((level, i) => {
              const [price, size] = level
              const barW = maxSize > 0 ? Math.min(100, size / maxSize * 100) : 0
              return (
                <div key={i} style={{ position: 'relative', display: 'grid', gridTemplateColumns: '1fr 1fr', padding: '1.5px 0', alignItems: 'center' }}>
                  <div style={{ position: 'absolute', right: 0, top: 0, bottom: 0, width: `${barW}%`, background: 'rgba(61,220,151,0.12)', borderRadius: 2 }} />
                  <span style={{ fontSize: 9.5, fontFamily: 'var(--font-mono)', color: '#3ddc97', position: 'relative', zIndex: 1 }}>
                    {fmtPrice(price)}
                  </span>
                  <span style={{ fontSize: 9, fontFamily: 'var(--font-mono)', color: 'var(--t-3)', textAlign: 'right', position: 'relative', zIndex: 1 }}>
                    {fmtSize(size)}
                  </span>
                </div>
              )
            })}
          </div>

          {/* Note for equity single-level */}
          {book.note && (
            <div style={{ fontSize: 8, color: 'var(--t-4)', marginTop: 6, lineHeight: 1.4, opacity: 0.7 }}>
              {book.note}
            </div>
          )}
        </div>
      )}

      {!book && !loading && (
        <div style={{ fontSize: 9, color: 'var(--t-4)', textAlign: 'center', marginTop: 8 }}>No data</div>
      )}
    </div>
  )
}

export default function TradePanel({ symbol, account, portfolioId, quote, onReset }) {
  return (
    <div className="trade-panel">
      <PortfolioCard account={account} onReset={onReset} portfolioId={portfolioId} />
      <OrderBookCard symbol={symbol} quote={quote} />
    </div>
  )
}

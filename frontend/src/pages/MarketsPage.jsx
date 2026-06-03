import { useState, useEffect, useCallback } from 'react'
import api from '../api.js'
import OptionProjectionWidget from '../components/OptionProjectionWidget'
import ConfirmModal from '../components/ConfirmModal.jsx'

// ── Formatting helpers ────────────────────────────────────────────────────────

function fmtPrice(price, symbol = '') {
  if (!price) return '—'
  const n = Number(price)
  if (isNaN(n) || n === 0) return '—'
  // Forex pairs — more decimal places for small prices
  if (symbol.includes('=X')) {
    if (n < 5) return n.toFixed(4)
    return n.toFixed(2)
  }
  if (n >= 10000) return n.toLocaleString('en-US', { maximumFractionDigits: 0 })
  if (n >= 100)   return n.toFixed(2)
  if (n >= 1)     return n.toFixed(3)
  return n.toFixed(5)
}

function fmtChange(c, pct) {
  if (c == null) return null
  const sign = c >= 0 ? '+' : ''
  return `${sign}${Number(c).toFixed(c >= 100 ? 1 : 2)} (${sign}${Number(pct).toFixed(2)}%)`
}

function fmtVol(n) {
  if (!n) return '—'
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(0) + 'K'
  return String(n)
}

// ── Instrument tile ───────────────────────────────────────────────────────────

function InstrumentTile({ inst, onChart }) {
  const c         = Number(inst.change ?? 0)
  const pct       = Number(inst.change_pct ?? 0)
  const positive  = c >= 0
  const color     = inst.price ? (positive ? '#3ddc97' : '#ff476f') : 'var(--t-3)'
  const changeStr = inst.price ? fmtChange(c, pct) : null

  return (
    <div
      onClick={() => inst.price && onChart(inst.symbol)}
      style={{
        background:   'var(--bg-card)',
        border:       `1px solid var(--hairline-2)`,
        borderRadius: 8,
        padding:      '12px 14px',
        cursor:       inst.price ? 'pointer' : 'default',
        transition:   'border-color .15s, background .15s',
        display:      'flex',
        flexDirection:'column',
        gap:          4,
        minWidth:     0,
      }}
      onMouseEnter={e => { if (inst.price) e.currentTarget.style.borderColor = 'var(--acc-line)' }}
      onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--hairline-2)' }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 6 }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 700, color: 'var(--cy)', letterSpacing: '0.04em' }}>
          {inst.display}
        </span>
        {changeStr && (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color, fontWeight: 600, textAlign: 'right' }}>
            {changeStr}
          </span>
        )}
      </div>
      <div style={{ fontSize: 10, color: 'var(--t-3)', letterSpacing: '0.02em', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {inst.name}
      </div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 20, fontWeight: 700, color, marginTop: 4, letterSpacing: '0.02em' }}>
        {inst.price ? fmtPrice(inst.price, inst.symbol) : <span style={{ color: 'var(--t-4)', fontSize: 12 }}>No data</span>}
      </div>
      {inst.high > 0 && inst.low > 0 && (
        <div style={{ display: 'flex', gap: 10, marginTop: 2 }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t-3)' }}>
            H <span style={{ color: '#3ddc97' }}>{fmtPrice(inst.high, inst.symbol)}</span>
          </span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t-3)' }}>
            L <span style={{ color: '#ff476f' }}>{fmtPrice(inst.low, inst.symbol)}</span>
          </span>
        </div>
      )}
      {inst.price > 0 && (
        <div style={{ marginTop: 4, fontSize: 10, color: 'var(--acc)', letterSpacing: '0.04em', fontFamily: 'var(--font-mono)', opacity: 0.7 }}>
          Open Chart →
        </div>
      )}
    </div>
  )
}

// ── Tile grid section ─────────────────────────────────────────────────────────

function TileGrid({ endpoint, onChart, label }) {
  const [data,    setData]    = useState([])
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(false)
    api.get(endpoint)
      .then(r => { if (!cancelled) { setData(r.data || []); setLoading(false) } })
      .catch(() => { if (!cancelled) { setError(true); setLoading(false) } })
    return () => { cancelled = true }
  }, [endpoint])

  return (
    <div>
      <div style={{ fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--t-3)', marginBottom: 12, fontWeight: 500 }}>
        {label}
      </div>
      {loading && <div style={{ color: 'var(--t-3)', fontSize: 12, padding: '16px 0' }}>Loading market data…</div>}
      {error   && <div style={{ color: 'var(--err)', fontSize: 12, padding: '16px 0' }}>Failed to load data. Is the backend running?</div>}
      {!loading && !error && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))', gap: 10 }}>
          {data.map(inst => <InstrumentTile key={inst.symbol} inst={inst} onChart={onChart} />)}
        </div>
      )}
    </div>
  )
}

// ── Options chain ─────────────────────────────────────────────────────────────

function OptionsChain({ defaultSymbol }) {
  const [sym,            setSym]            = useState(defaultSymbol || 'AAPL')
  const [input,          setInput]          = useState(defaultSymbol || 'AAPL')
  const [data,           setData]           = useState(null)
  const [expiry,         setExpiry]         = useState('')
  const [side,           setSide]           = useState('calls')  // 'calls' | 'puts'
  const [loading,        setLoading]        = useState(false)
  const [error,          setError]          = useState('')
  const [selectedOption, setSelectedOption] = useState(null)
  const [infoModal,      setInfoModal]      = useState('')

  const fetchChain = useCallback((symbol, exp) => {
    if (!symbol) return
    setLoading(true)
    setError('')
    const params = exp ? `?expiry=${exp}` : ''
    api.get(`/options/${symbol}${params}`)
      .then(r => {
        setData(r.data)
        setExpiry(r.data.selected || '')
        setLoading(false)
      })
      .catch(e => {
        setError(e?.response?.data?.error || 'Failed to load options chain.')
        setLoading(false)
      })
  }, [])

  useEffect(() => { fetchChain(sym, '') }, [sym])

  function handleSubmit(e) {
    e.preventDefault()
    const s = input.trim().toUpperCase()
    if (s) { setSym(s); setData(null) }
  }

  const rows = data ? (side === 'calls' ? data.calls : data.puts) : []
  const spot = data?.spot || 0

  return (
    <div>
      {/* Controls bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
        <form onSubmit={handleSubmit} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <span style={{ fontSize: 10, color: 'var(--t-3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>Symbol</span>
          <input
            value={input}
            onChange={e => setInput(e.target.value.toUpperCase())}
            style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 700, color: 'var(--cy)', background: 'var(--bg-card)', border: '1px solid var(--hairline-2)', borderRadius: 5, padding: '4px 10px', width: 90, outline: 'none' }}
            placeholder="AAPL"
          />
          <button type="submit" style={{ background: 'var(--acc)', border: 'none', borderRadius: 5, color: '#fff', fontSize: 11, fontWeight: 600, padding: '4px 12px', cursor: 'pointer' }}>
            Load
          </button>
        </form>

        {data?.expirations?.length > 0 && (
          <>
            <span style={{ fontSize: 10, color: 'var(--t-3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>Expiry</span>
            <select
              value={expiry}
              onChange={e => { setExpiry(e.target.value); fetchChain(sym, e.target.value) }}
              style={{ background: 'var(--bg-card)', border: '1px solid var(--hairline-2)', borderRadius: 5, color: 'var(--t-1)', fontSize: 11, padding: '4px 8px', fontFamily: 'var(--font-mono)', outline: 'none', cursor: 'pointer' }}
            >
              {data.expirations.map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          </>
        )}

        {data && (
          <div style={{ display: 'flex', background: 'var(--bg-card)', border: '1px solid var(--hairline-2)', borderRadius: 5, overflow: 'hidden' }}>
            {['calls', 'puts'].map(s => (
              <button key={s} onClick={() => setSide(s)} style={{ background: side === s ? (s === 'calls' ? 'rgba(61,220,151,0.18)' : 'rgba(255,71,111,0.18)') : 'transparent', border: 'none', color: side === s ? (s === 'calls' ? '#3ddc97' : '#ff476f') : 'var(--t-3)', fontSize: 11, fontWeight: side === s ? 700 : 400, padding: '4px 14px', cursor: 'pointer', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                {s}
              </button>
            ))}
          </div>
        )}

        {spot > 0 && (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t-2)', marginLeft: 'auto' }}>
            Spot <span style={{ color: 'var(--cy)', fontWeight: 700 }}>${spot.toFixed(2)}</span>
          </span>
        )}
      </div>

      {infoModal && <ConfirmModal message={infoModal} alertOnly onConfirm={() => setInfoModal('')} onCancel={() => setInfoModal('')} />}

      {/* Projection widget renders ABOVE the table so it's always visible on click */}
      {selectedOption && (
        <OptionProjectionWidget
          option={selectedOption}
          underlyingPrice={spot}
          onClose={() => setSelectedOption(null)}
          onAddToPortfolio={() => setInfoModal('Select a portfolio in the main view first, then use the Trade panel to add positions.')}
        />
      )}

      {loading && <div style={{ color: 'var(--t-3)', fontSize: 12, padding: '20px 0' }}>Loading options chain…</div>}
      {error   && <div style={{ color: 'var(--err)', fontSize: 12, padding: '20px 0' }}>{error}</div>}

      {!loading && data && rows.length === 0 && (
        <div style={{ color: 'var(--t-3)', fontSize: 12, padding: '20px 0' }}>No {side} data for this expiry.</div>
      )}

      {!loading && rows.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--hairline-2)' }}>
                {['Strike', 'Bid', 'Ask', 'Last', 'IV %', 'Volume', 'OI', 'Chg %', 'ITM'].map(h => (
                  <th key={h} style={{ padding: '5px 10px', textAlign: h === 'Strike' ? 'left' : 'right', fontSize: 9, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--t-3)', fontWeight: 600, whiteSpace: 'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const isATM      = spot > 0 && Math.abs(r.strike - spot) === Math.min(...rows.map(x => Math.abs(x.strike - spot)))
                const itmBg      = r.itm ? (side === 'calls' ? 'rgba(61,220,151,0.06)' : 'rgba(255,71,111,0.06)') : 'transparent'
                const isSelected = selectedOption?.strike === r.strike && selectedOption?.type === side
                const baseBg     = isSelected ? 'rgba(255,106,26,0.10)' : (isATM ? 'rgba(100,140,255,0.08)' : itmBg)
                const chgColor   = r.change_pct >= 0 ? '#3ddc97' : '#ff476f'
                return (
                  <tr key={i}
                    style={{ background: baseBg, borderBottom: '1px solid rgba(140,170,220,0.05)', cursor: 'pointer' }}
                    onClick={() => setSelectedOption(isSelected ? null : { ...r, type: side })}
                    onMouseEnter={e => { e.currentTarget.style.background = isSelected ? 'rgba(255,106,26,0.15)' : 'var(--bg-card-hi)' }}
                    onMouseLeave={e => { e.currentTarget.style.background = baseBg }}
                  >
                    <td style={{ padding: '5px 10px', fontWeight: isATM ? 700 : 500, color: isATM ? 'var(--cy)' : 'var(--t-1)' }}>
                      {isATM && <span style={{ fontSize: 8, color: 'var(--cy)', marginRight: 4, opacity: 0.7 }}>ATM</span>}
                      ${r.strike.toFixed(2)}
                    </td>
                    <td style={{ padding: '5px 10px', textAlign: 'right', color: 'var(--t-2)' }}>{r.bid ? r.bid.toFixed(2) : '—'}</td>
                    <td style={{ padding: '5px 10px', textAlign: 'right', color: 'var(--t-2)' }}>{r.ask ? r.ask.toFixed(2) : '—'}</td>
                    <td style={{ padding: '5px 10px', textAlign: 'right', color: 'var(--t-1)', fontWeight: 600 }}>{r.last ? r.last.toFixed(2) : '—'}</td>
                    <td style={{ padding: '5px 10px', textAlign: 'right', color: r.iv > 60 ? '#f5b342' : r.iv > 30 ? 'var(--t-2)' : 'var(--t-3)' }}>{r.iv ? `${r.iv.toFixed(1)}%` : '—'}</td>
                    <td style={{ padding: '5px 10px', textAlign: 'right', color: 'var(--t-2)' }}>{fmtVol(r.volume)}</td>
                    <td style={{ padding: '5px 10px', textAlign: 'right', color: 'var(--t-3)' }}>{fmtVol(r.oi)}</td>
                    <td style={{ padding: '5px 10px', textAlign: 'right', color: chgColor, fontWeight: 600 }}>{r.change_pct ? `${r.change_pct >= 0 ? '+' : ''}${r.change_pct.toFixed(1)}%` : '—'}</td>
                    <td style={{ padding: '5px 10px', textAlign: 'right' }}>
                      {r.itm && <span style={{ fontSize: 9, color: side === 'calls' ? '#3ddc97' : '#ff476f', fontWeight: 700, border: `1px solid ${side === 'calls' ? '#3ddc9744' : '#ff476f44'}`, borderRadius: 3, padding: '1px 5px' }}>ITM</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Main MarketsPage ──────────────────────────────────────────────────────────

const SECTIONS = [
  { key: 'crypto',  label: 'Crypto'  },
  { key: 'futures', label: 'Futures' },
  { key: 'forex',   label: 'Forex'   },
  { key: 'options', label: 'Options' },
]

export default function MarketsPage({ onSelectSymbol, symbol }) {
  const [active, setActive] = useState('crypto')

  function handleChart(sym) {
    onSelectSymbol?.(sym)
  }

  return (
    <div className="ch-body" style={{ flexDirection: 'column', gap: 0, overflowY: 'auto' }}>

      {/* ── Tab bar ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0, marginBottom: 16 }}>
        {SECTIONS.map(s => (
          <button key={s.key} onClick={() => setActive(s.key)}
            style={{
              background:   active === s.key ? 'var(--acc)' : 'var(--bg-card)',
              border:       `1px solid ${active === s.key ? 'var(--acc)' : 'var(--hairline-2)'}`,
              borderRadius: 6, color: active === s.key ? '#fff' : 'var(--t-2)',
              cursor: 'pointer', fontSize: 11, fontWeight: active === s.key ? 600 : 400,
              padding: '5px 18px', transition: 'all .15s', letterSpacing: '0.04em',
            }}>
            {s.label}
          </button>
        ))}
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 10, color: 'var(--t-4)', fontFamily: 'var(--font-mono)' }}>
          via yfinance · delayed
        </span>
      </div>

      {/* ── Content ── */}
      {active === 'crypto' && (
        <TileGrid
          endpoint="/markets/crypto"
          onChart={handleChart}
          label="Crypto — 24/7 · click any tile to open chart"
        />
      )}

      {active === 'futures' && (
        <TileGrid
          endpoint="/markets/futures"
          onChart={handleChart}
          label="Futures — click any tile to open chart"
        />
      )}

      {active === 'forex' && (
        <TileGrid
          endpoint="/markets/forex"
          onChart={handleChart}
          label="Forex pairs — click any tile to open chart"
        />
      )}

      {active === 'options' && (
        <div>
          <div style={{ fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--t-3)', marginBottom: 14, fontWeight: 500 }}>
            Options Chain — enter any stock symbol
          </div>
          <OptionsChain defaultSymbol={symbol} />
        </div>
      )}

    </div>
  )
}

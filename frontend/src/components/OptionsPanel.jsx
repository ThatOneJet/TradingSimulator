import { useState, useEffect, useCallback } from 'react'
import api from '../api.js'
import OptionProjectionWidget from './OptionProjectionWidget'
import ConfirmModal from './ConfirmModal.jsx'

function fv(n, d = 2) { return n != null && n !== 0 ? Number(n).toFixed(d) : '—' }
function fmtVol(n) {
  if (!n) return '—'
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(0) + 'K'
  return String(n)
}

export default function OptionsPanel({ symbol }) {
  const [data,           setData]           = useState(null)
  const [expiry,         setExpiry]         = useState('')
  const [side,           setSide]           = useState('calls')
  const [loading,        setLoading]        = useState(false)
  const [error,          setError]          = useState('')
  const [selectedOption, setSelectedOption] = useState(null)
  const [infoModal,      setInfoModal]      = useState('')

  const fetchChain = useCallback((sym, exp) => {
    if (!sym) return
    setLoading(true)
    setError('')
    setSelectedOption(null)
    const params = exp ? `?expiry=${exp}` : ''
    api.get(`/options/${sym}${params}`)
      .then(r => { setData(r.data); setExpiry(r.data.selected || ''); setLoading(false) })
      .catch(e => { setError(e?.response?.data?.error || 'No options data'); setLoading(false) })
  }, [])

  useEffect(() => { setData(null); setExpiry(''); fetchChain(symbol, '') }, [symbol])

  const rows = data ? (side === 'calls' ? data.calls : data.puts) : []
  const spot = data?.spot || 0
  const sideColor = side === 'calls' ? '#3ddc97' : '#ff476f'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', fontFamily: 'var(--font-sans)', fontSize: 11 }}>
      {infoModal && <ConfirmModal message={infoModal} alertOnly onConfirm={() => setInfoModal('')} onCancel={() => setInfoModal('')} />}

      {/* Controls */}
      <div style={{ padding: '8px 10px', borderBottom: '1px solid rgba(140,170,220,0.08)', flexShrink: 0 }}>
        {/* Expiry + spot */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
          {data?.expirations?.length > 0 ? (
            <select
              value={expiry}
              onChange={e => { setExpiry(e.target.value); fetchChain(symbol, e.target.value) }}
              style={{
                flex: 1, background: 'var(--bg-card)', border: '1px solid var(--hairline-2)', borderRadius: 4,
                color: 'var(--t-1)', fontSize: 10, padding: '3px 6px',
                fontFamily: 'var(--font-mono)', outline: 'none', cursor: 'pointer',
              }}
            >
              {data.expirations.map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          ) : (
            <span style={{ flex: 1, fontSize: 10, color: 'var(--t-4)' }}>—</span>
          )}
          {spot > 0 && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t-3)', flexShrink: 0 }}>
              <span style={{ color: 'var(--cy)', fontWeight: 700 }}>${spot.toFixed(2)}</span>
            </span>
          )}
        </div>

        {/* Calls / Puts toggle */}
        <div style={{ display: 'flex', background: 'var(--bg-card)', border: '1px solid var(--hairline-2)', borderRadius: 4, overflow: 'hidden' }}>
          {['calls', 'puts'].map(s => (
            <button key={s} onClick={() => setSide(s)} style={{
              flex: 1, border: 'none', padding: '4px 0', cursor: 'pointer',
              background: side === s ? (s === 'calls' ? 'rgba(61,220,151,0.18)' : 'rgba(255,71,111,0.18)') : 'transparent',
              color: side === s ? (s === 'calls' ? '#3ddc97' : '#ff476f') : 'var(--t-3)',
              fontSize: 10, fontWeight: side === s ? 700 : 400,
              textTransform: 'uppercase', letterSpacing: '0.06em', transition: 'all .15s',
            }}>
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* Selected option projection */}
      {selectedOption && (
        <div style={{ padding: '0 8px', flexShrink: 0 }}>
          <OptionProjectionWidget
            option={selectedOption}
            underlyingPrice={spot}
            onClose={() => setSelectedOption(null)}
            onAddToPortfolio={() => setInfoModal('Use the Trade panel to add positions.')}
            compact
          />
        </div>
      )}

      {/* Status messages */}
      {loading && <div style={{ padding: '16px 10px', color: 'var(--t-4)', fontSize: 11 }}>Loading…</div>}
      {error   && <div style={{ padding: '16px 10px', color: 'var(--err)', fontSize: 11 }}>{error}</div>}
      {!loading && data && rows.length === 0 && (
        <div style={{ padding: '16px 10px', color: 'var(--t-4)', fontSize: 11 }}>No {side} data.</div>
      )}

      {/* Compact chain table */}
      {!loading && rows.length > 0 && (
        <div style={{ overflowY: 'auto', flex: 1 }}>
          {/* Header */}
          <div style={{
            display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 36px',
            padding: '4px 10px', position: 'sticky', top: 0,
            background: 'var(--bg)', borderBottom: '1px solid rgba(140,170,220,0.08)',
          }}>
            {['Strike', 'Bid', 'Ask', ''].map((h, i) => (
              <div key={i} style={{
                fontSize: 8, letterSpacing: '0.09em', textTransform: 'uppercase',
                color: 'var(--t-4)', textAlign: i === 0 ? 'left' : 'right',
              }}>{h}</div>
            ))}
          </div>

          {rows.map((r, i) => {
            const isATM = spot > 0 && Math.abs(r.strike - spot) === Math.min(...rows.map(x => Math.abs(x.strike - spot)))
            const isSelected = selectedOption?.strike === r.strike && selectedOption?.type === side
            const itmBg = r.itm ? `${sideColor}08` : 'transparent'
            const bg = isSelected ? `${sideColor}18` : isATM ? 'rgba(100,140,255,0.07)' : itmBg

            return (
              <div key={i}
                style={{
                  display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 36px',
                  padding: '5px 10px', cursor: 'pointer',
                  background: bg,
                  borderBottom: '1px solid rgba(140,170,220,0.04)',
                  transition: 'background .1s',
                }}
                onClick={() => setSelectedOption(isSelected ? null : { ...r, type: side })}
                onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = 'var(--bg-card-hi)' }}
                onMouseLeave={e => { e.currentTarget.style.background = bg }}
              >
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: isATM ? 700 : 500, color: isATM ? 'var(--cy)' : 'var(--t-1)' }}>
                  {isATM && <span style={{ fontSize: 7, opacity: 0.6, marginRight: 2 }}>ATM</span>}
                  ${r.strike.toFixed(2)}
                </div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, textAlign: 'right', color: 'var(--t-2)' }}>
                  {fv(r.bid)}
                </div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, textAlign: 'right', color: 'var(--t-2)' }}>
                  {fv(r.ask)}
                </div>
                <div style={{ textAlign: 'right' }}>
                  {r.itm && (
                    <span style={{ fontSize: 8, color: sideColor, fontWeight: 700, border: `1px solid ${sideColor}44`, borderRadius: 2, padding: '1px 3px' }}>
                      ITM
                    </span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

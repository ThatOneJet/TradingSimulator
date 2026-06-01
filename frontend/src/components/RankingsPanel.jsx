import { useState, useEffect } from 'react'
import api from '../api.js'

const MARKET_STATE_CFG = {
  panic:              { color: '#ff1a4e', label: 'PANIC'         },
  overbought_extreme: { color: '#ff476f', label: 'OVERBOUGHT'    },
  oversold_extreme:   { color: '#3ddc97', label: 'OVERSOLD'      },
  breakout:           { color: '#f5b342', label: 'BREAKOUT'      },
  trending_up:        { color: '#3ddc97', label: 'TRENDING UP'   },
  trending_down:      { color: '#ff476f', label: 'TRENDING DOWN' },
  accumulation:       { color: '#4ad9ff', label: 'ACCUM'         },
  ranging:            { color: '#8899aa', label: 'RANGING'       },
  mild_uptrend:       { color: '#5ee8a9', label: 'MILD UP'       },
  mild_downtrend:     { color: '#ff6a6a', label: 'MILD DOWN'     },
  neutral:            { color: '#6b7689', label: 'NEUTRAL'       },
}

function f(n, d = 2) { return (n == null || isNaN(n)) ? '—' : Number(n).toFixed(d) }

function ScoreBar({ score }) {
  const pct   = Math.min(100, Math.abs(score) / 10 * 100)
  const color = score >= 2.5 ? '#3ddc97' : score <= -2.5 ? '#ff476f' : score > 0 ? '#5ee8a9' : score < 0 ? '#ff6a6a' : '#475061'
  return (
    <div style={{ position: 'relative', height: 3, background: 'rgba(140,170,220,0.1)', borderRadius: 2 }}>
      <div style={{ position: 'absolute', left: '50%', top: 0, bottom: 0, width: 1, background: 'rgba(140,170,220,0.18)' }} />
      {score !== 0 && (
        <div style={{
          position: 'absolute',
          left: score >= 0 ? '50%' : `${50 - pct / 2}%`,
          width: `${pct / 2}%`,
          top: 0, bottom: 0,
          background: color, borderRadius: 2, opacity: 0.85,
        }} />
      )}
    </div>
  )
}

export default function RankingsPanel({ portfolioId = 1, onSelect }) {
  const [rankings,  setRankings]  = useState([])
  const [loading,   setLoading]   = useState(false)
  const [computing, setComputing] = useState(false)
  const [lastFetch, setLastFetch] = useState(null)
  const [error,     setError]     = useState(null)

  const doFetch = () => {
    setLoading(true)
    setError(null)
    api.get(`/rankings?portfolio_id=${portfolioId}&cached_only=1`, { timeout: 10000 })
      .then(r => {
        if (Array.isArray(r.data)) setRankings(r.data)
        setLoading(false)
        setLastFetch(Date.now())
        setComputing(true)
        api.get(`/rankings?portfolio_id=${portfolioId}`, { timeout: 90000 })
          .then(r2 => {
            if (Array.isArray(r2.data)) setRankings(r2.data)
            setLastFetch(Date.now())
            setComputing(false)
          })
          .catch(() => setComputing(false))
      })
      .catch(e => {
        setError(e?.response?.data?.error || e?.message || 'Request failed')
        setLoading(false)
      })
  }

  useEffect(() => {
    doFetch()
    const id = setInterval(doFetch, 120_000)
    return () => clearInterval(id)
  }, [portfolioId])

  const age = lastFetch ? Math.floor((Date.now() - lastFetch) / 1000) : null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>

      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '8px 12px', borderBottom: '1px solid rgba(140,170,220,0.08)',
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#b39dff', boxShadow: '0 0 5px #b39dff' }} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--t-2)', textTransform: 'uppercase' }}>
              Asset Rankings
            </span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 7.5, color: '#b39dff', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
              Profitability Assessment
            </span>
          </div>
          {rankings.length > 0 && (
            <span style={{ fontSize: 8, color: 'var(--t-4)', fontFamily: 'var(--font-mono)' }}>
              {rankings.length} symbols
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {computing && (
            <span style={{ fontSize: 8, color: '#f5b342', fontFamily: 'var(--font-mono)' }}>computing…</span>
          )}
          {age != null && !computing && (
            <span style={{ fontSize: 8, color: 'var(--t-4)', fontFamily: 'var(--font-mono)' }}>{age}s ago</span>
          )}
          <button
            onClick={doFetch}
            disabled={loading || computing}
            style={{
              background: 'none', border: '1px solid rgba(140,170,220,0.15)', borderRadius: 4,
              color: (loading || computing) ? 'var(--t-4)' : 'var(--t-3)',
              cursor: (loading || computing) ? 'default' : 'pointer',
              fontSize: 11, padding: '2px 7px', fontFamily: 'var(--font-mono)',
            }}
          >
            {loading ? '…' : '↻'}
          </button>
        </div>
      </div>

      {/* Disclaimer */}
      <div style={{
        padding: '5px 12px',
        borderBottom: '1px solid rgba(140,170,220,0.06)',
        flexShrink: 0,
      }}>
        <div style={{
          fontSize: 8.5, color: '#f5b342', background: 'rgba(245,179,66,0.07)',
          border: '1px solid rgba(245,179,66,0.2)', borderRadius: 4,
          padding: '5px 10px', lineHeight: 1.5,
        }}>
          ⚠ Algorithmic signals only. These are metrics, not financial advice.
          Past performance does not guarantee future results.
        </div>
      </div>

      {/* List */}
      <div style={{ overflowY: 'auto', flex: 1 }}>
        {loading && rankings.length === 0 && (
          <div style={{ padding: '20px 12px', textAlign: 'center', fontSize: 11, color: 'var(--t-3)' }}>
            <div style={{ marginBottom: 4 }}>Fetching indicators for each symbol…</div>
            <div style={{ fontSize: 9, color: 'var(--t-4)' }}>This may take 20–60s on first load</div>
          </div>
        )}
        {!loading && error && (
          <div style={{ padding: '16px 12px', textAlign: 'center' }}>
            <div style={{ fontSize: 10, color: '#ff6a6a', marginBottom: 6 }}>⚠ {error}</div>
            <button onClick={doFetch} style={{ fontSize: 10, color: 'var(--t-3)', background: 'none', border: '1px solid rgba(140,170,220,0.15)', borderRadius: 4, padding: '3px 10px', cursor: 'pointer' }}>Retry</button>
          </div>
        )}
        {rankings.length === 0 && !loading && !error && (
          <div style={{ padding: '20px 12px', textAlign: 'center', fontSize: 11, color: 'var(--t-4)' }}>
            Add symbols to your watchlist to see rankings.
          </div>
        )}

        {rankings.map((item, idx) => {
          const cfg         = MARKET_STATE_CFG[item.market_state] ?? MARKET_STATE_CFG.neutral
          const scoreColor  = item.score >= 2.5 ? '#3ddc97' : item.score <= -2.5 ? '#ff476f' : item.score > 0 ? '#5ee8a9' : item.score < 0 ? '#ff6a6a' : '#8899aa'
          const uncertColor = item.uncertainty >= 0.6 ? '#ff476f' : item.uncertainty >= 0.4 ? '#f5b342' : '#3ddc97'
          const isTop       = idx < 3 && item.score >= 2.5
          const rank        = idx + 1

          return (
            <div
              key={item.symbol}
              onClick={() => onSelect?.(item.symbol)}
              style={{
                padding: '10px 12px',
                borderBottom: '1px solid rgba(140,170,220,0.06)',
                cursor: 'pointer',
                background: isTop ? 'rgba(61,220,151,0.03)' : 'transparent',
                transition: 'background 0.15s',
              }}
              onMouseEnter={e => e.currentTarget.style.background = 'rgba(140,170,220,0.05)'}
              onMouseLeave={e => e.currentTarget.style.background = isTop ? 'rgba(61,220,151,0.03)' : 'transparent'}
            >
              {/* Row 1: rank + symbol + tags | direction + score + regime */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 7 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: isTop ? '#b39dff' : 'var(--t-4)', fontWeight: isTop ? 700 : 400, minWidth: 14 }}>
                    {rank}
                  </span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 800, color: 'var(--t-1)', letterSpacing: '0.02em' }}>
                    {item.symbol}
                  </span>
                  {item.held && (
                    <span style={{ fontSize: 7.5, color: '#4ad9ff', border: '1px solid #4ad9ff44', borderRadius: 3, padding: '1px 4px', fontFamily: 'var(--font-mono)', lineHeight: 1.4 }}>
                      HELD
                    </span>
                  )}
                  {item.what_changed?.length > 0 && (
                    <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#f5b342', flexShrink: 0, display: 'inline-block' }} title="Signal changed" />
                  )}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  {(() => {
                    const direction = item.score > 1 ? 'long' : item.score < -1 ? 'short' : 'neutral'
                    const dirColor  = direction === 'long' ? '#3ddc97' : direction === 'short' ? '#ff476f' : '#f5b342'
                    const dirLabel  = direction === 'long' ? 'LONG ↑' : direction === 'short' ? 'SHORT ↓' : 'NEUTRAL'
                    return (
                      <span style={{
                        fontSize: 8, fontWeight: 700, letterSpacing: '0.06em',
                        color: dirColor, background: `${dirColor}18`,
                        border: `1px solid ${dirColor}44`,
                        borderRadius: 3, padding: '1px 5px',
                        fontFamily: 'var(--font-mono)', lineHeight: 1.5,
                      }}>
                        {dirLabel}
                      </span>
                    )
                  })()}
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 800, color: scoreColor }}>
                    {item.score > 0 ? '+' : ''}{f(item.score, 1)}
                  </span>
                  <span style={{
                    fontSize: 8, fontFamily: 'var(--font-mono)', fontWeight: 700,
                    color: cfg.color, letterSpacing: '0.05em',
                    border: `1px solid ${cfg.color}33`, borderRadius: 3, padding: '2px 6px',
                    lineHeight: 1.5,
                  }}>
                    {cfg.label}
                  </span>
                </div>
              </div>

              {/* Row 2: score bar */}
              <ScoreBar score={item.score} />

              {/* Row 3: price · RSI · uncertainty */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 6 }}>
                <div style={{ display: 'flex', gap: 12 }}>
                  <span style={{ fontSize: 10, color: 'var(--t-3)', fontFamily: 'var(--font-mono)' }}>
                    ${f(item.price)}
                  </span>
                  <span style={{ fontSize: 10, color: 'var(--t-4)', fontFamily: 'var(--font-mono)' }}>
                    RSI {f(item.rsi, 0)}
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                  <span style={{ fontSize: 8.5, color: 'var(--t-4)', fontFamily: 'var(--font-mono)' }}>UNCERT</span>
                  <div style={{ width: 36, height: 3, background: 'rgba(140,170,220,0.1)', borderRadius: 2 }}>
                    <div style={{ height: '100%', width: `${item.uncertainty * 100}%`, background: uncertColor, borderRadius: 2, opacity: 0.75 }} />
                  </div>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, fontWeight: 700, color: uncertColor }}>
                    {Math.round(item.uncertainty * 100)}%
                  </span>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* Footer */}
      {rankings.length > 0 && (
        <div style={{ padding: '5px 12px', borderTop: '1px solid rgba(140,170,220,0.06)', flexShrink: 0 }}>
          <span style={{ fontSize: 8, color: 'var(--t-4)', fontFamily: 'var(--font-mono)' }}>
            Ranked by AI score · refreshes every 2min · tap row to chart
          </span>
        </div>
      )}
    </div>
  )
}

import { useState, useEffect } from 'react'
import api from '../api.js'

const BADGE_COLORS = {
  crypto:  { bg: 'rgba(74,217,255,0.15)',  text: '#4ad9ff' },
  forex:   { bg: 'rgba(167,139,250,0.15)', text: '#a78bfa' },
  futures: { bg: 'rgba(251,146,60,0.15)',  text: '#fb923c' },
  equity:  { bg: 'rgba(245,158,11,0.15)',  text: '#f59e0b' },
}

function mtfColor(trend) {
  if (trend === 'up')   return { bg: 'rgba(74,222,128,0.15)',  text: '#4ade80' }
  if (trend === 'down') return { bg: 'rgba(255,71,111,0.15)',  text: '#ff476f' }
  return { bg: 'rgba(140,170,220,0.1)', text: 'var(--t-3)' }
}

function fmt(n, d = 2) {
  if (n == null || isNaN(n)) return '—'
  return Number(n).toFixed(d)
}

export default function TradeBrief({ symbol, onClose }) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)
  const [guideOpen, setGuideOpen] = useState(false)

  useEffect(() => {
    if (!symbol) return
    setLoading(true)
    setError(null)
    api.get(`/analysis/${symbol}/brief`)
      .then(r => { setData(r.data); setLoading(false) })
      .catch(() => { setError('Failed to load trade brief'); setLoading(false) })
  }, [symbol])

  const s = { padding: '14px 16px', background: 'var(--bg-2)', borderRadius: 8, border: '1px solid rgba(140,170,220,0.1)', display: 'flex', flexDirection: 'column', gap: 12 }

  if (loading) return (
    <div style={s}>
      <span style={{ fontSize: 11, color: 'var(--t-3)', fontFamily: 'var(--font-mono)' }}>Loading trade brief…</span>
    </div>
  )
  if (error) return (
    <div style={s}>
      <span style={{ fontSize: 11, color: 'var(--err)' }}>{error}</span>
    </div>
  )
  if (!data) return null

  // Score bar geometry
  const scoreWidth = Math.abs(data.score) / 10 * 50
  const scoreLeft  = data.score < 0 ? (50 - scoreWidth) : 50
  const scoreColor = data.score >= 2.5 ? 'var(--ok)' : data.score <= -2.5 ? 'var(--err)' : '#888'

  const badge = BADGE_COLORS[data.asset_class] ?? BADGE_COLORS.equity
  const mtf   = data.mtf_bias ?? {}
  const guide = data.setup_guide ?? {}

  return (
    <div style={s}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 15, color: 'var(--t-1)', letterSpacing: '0.04em' }}>
          {data.symbol}
        </span>
        <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', padding: '2px 7px', borderRadius: 4, background: badge.bg, color: badge.text }}>
          {data.asset_class}
        </span>
        <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 600, color: 'var(--t-1)' }}>
          ${fmt(data.price, data.price >= 100 ? 2 : 4)}
        </span>
        {onClose && (
          <button onClick={onClose} style={{ marginLeft: 6, background: 'none', border: 'none', color: 'var(--t-3)', cursor: 'pointer', fontSize: 14, lineHeight: 1, padding: '2px 4px' }}>
            ✕
          </button>
        )}
      </div>

      {/* Score bar */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
          <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--t-3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            {String(data.regime).replace(/_/g, ' ')}
          </span>
          <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', fontWeight: 700, color: scoreColor }}>
            {data.score >= 0 ? '+' : ''}{fmt(data.score, 1)}
          </span>
        </div>
        <div style={{ position: 'relative', height: 6, borderRadius: 3, background: 'rgba(140,170,220,0.08)' }}>
          <div style={{ position: 'absolute', left: '50%', top: 0, bottom: 0, width: 1, background: 'rgba(140,170,220,0.2)' }} />
          <div style={{ position: 'absolute', left: `${scoreLeft}%`, width: `${scoreWidth}%`, top: 0, bottom: 0, borderRadius: 3, background: scoreColor, opacity: 0.8, transition: 'all 0.4s' }} />
        </div>
        <p style={{ margin: '5px 0 0', fontSize: 10, color: 'var(--t-3)', lineHeight: 1.5 }}>{data.regime_desc}</p>
      </div>

      {/* MTF alignment */}
      {Object.keys(mtf).length > 0 && (
        <div>
          <div style={{ fontSize: 9, fontFamily: 'var(--font-mono)', color: 'var(--t-3)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 6 }}>
            Multi-Timeframe &nbsp;
            <span style={{ color: mtf.alignment === 'bullish' ? '#4ade80' : mtf.alignment === 'bearish' ? '#ff476f' : 'var(--t-3)' }}>
              {mtf.alignment ?? '—'}
            </span>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            {['1H', '1D', '1W'].map(tf => {
              const frame = mtf[tf] ?? {}
              const c = mtfColor(frame.trend)
              return (
                <div key={tf} style={{ flex: 1, padding: '5px 8px', borderRadius: 5, background: c.bg, textAlign: 'center' }}>
                  <div style={{ fontSize: 9, fontFamily: 'var(--font-mono)', fontWeight: 700, color: c.text }}>{tf}</div>
                  <div style={{ fontSize: 9, fontFamily: 'var(--font-mono)', color: c.text, marginTop: 2, textTransform: 'uppercase' }}>
                    {frame.trend ?? '—'}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Price projection */}
      <div style={{ background: 'var(--bg-3)', borderRadius: 6, padding: '10px 12px' }}>
        <div style={{ fontSize: 9, fontFamily: 'var(--font-mono)', color: 'var(--t-3)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 6 }}>
          24h Projection
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--ok)' }}>
            ↑ ${fmt(data.proj_high, 4)}
          </span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t-3)' }}>
            ATR {fmt(data.atr_pct, 1)}%
          </span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--err)' }}>
            ↓ ${fmt(data.proj_low, 4)}
          </span>
        </div>
        {(data.nearest_support != null || data.nearest_resistance != null) && (
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, paddingTop: 6, borderTop: '1px solid rgba(140,170,220,0.07)' }}>
            <span style={{ fontSize: 9, fontFamily: 'var(--font-mono)', color: 'var(--t-3)' }}>
              Sup <span style={{ color: '#4ade80' }}>${fmt(data.nearest_support, 4)}</span>
            </span>
            <span style={{ fontSize: 9, fontFamily: 'var(--font-mono)', color: 'var(--t-3)' }}>
              Res <span style={{ color: '#ff476f' }}>${fmt(data.nearest_resistance, 4)}</span>
            </span>
          </div>
        )}
      </div>

      {/* Stop levels */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, fontFamily: 'var(--font-mono)' }}>
          <span style={{ color: 'var(--t-3)' }}>Long stop</span>
          <span style={{ color: 'var(--err)' }}>${fmt(data.long_stop, 4)}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, fontFamily: 'var(--font-mono)' }}>
          <span style={{ color: 'var(--t-3)' }}>Short stop</span>
          <span style={{ color: 'var(--ok)' }}>${fmt(data.short_stop, 4)}</span>
        </div>
      </div>

      {/* Setup Guide (collapsible) */}
      {guide.title && (
        <div style={{ borderTop: '1px solid rgba(140,170,220,0.08)', paddingTop: 10 }}>
          <button
            onClick={() => setGuideOpen(o => !o)}
            style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
          >
            <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--t-2)', letterSpacing: '0.04em' }}>
              {guide.title}
            </span>
            <span style={{ fontSize: 10, color: 'var(--t-3)' }}>{guideOpen ? '▲' : '▼'}</span>
          </button>
          {guideOpen && (
            <div style={{ marginTop: 8 }}>
              <ul style={{ margin: 0, padding: '0 0 0 14px', display: 'flex', flexDirection: 'column', gap: 5 }}>
                {(guide.tips ?? []).map((tip, i) => (
                  <li key={i} style={{ fontSize: 10, color: 'var(--t-2)', lineHeight: 1.55 }}>{tip}</li>
                ))}
              </ul>
              {guide.best_sessions && (
                <div style={{ marginTop: 8, fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--t-3)' }}>
                  <span style={{ color: 'var(--ok)' }}>Best: </span>{guide.best_sessions}
                </div>
              )}
              {guide.avoid && (
                <div style={{ marginTop: 4, fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--t-3)' }}>
                  <span style={{ color: 'var(--err)' }}>Avoid: </span>{guide.avoid}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* AI Summary */}
      {data.summary && (
        <p style={{ margin: 0, fontSize: 10.5, color: 'var(--t-2)', fontStyle: 'italic', lineHeight: 1.6, borderLeft: '2px solid rgba(140,170,220,0.15)', paddingLeft: 10 }}>
          {data.summary}
        </p>
      )}

      {/* EV hint — show when brief has score data */}
      {data && Math.abs(data.score) >= 2.5 && (
        <div style={{
          marginTop: 8, padding: '5px 8px',
          background: 'rgba(140,170,220,0.04)', borderRadius: 4,
          border: '1px solid rgba(140,170,220,0.1)',
        }}>
          <div style={{ fontSize: 8, color: 'var(--t-4)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 3 }}>
            Trade Quality Factors
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {[
              { label: 'Signal', value: `${Math.abs(data.score).toFixed(1)}/10`, ok: Math.abs(data.score) >= 3 },
              { label: 'Regime', value: data.regime?.replace(/_/g,' '), ok: !['panic','neutral','ranging'].includes(data.regime) },
              { label: 'MTF', value: data.mtf_bias?.bias || '—', ok: data.mtf_bias?.bias !== 'neutral' },
              { label: 'Liquidity', value: data.asset_class, ok: data.asset_class !== 'other' },
            ].map(({ label, value, ok }) => (
              <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                <div style={{ width: 5, height: 5, borderRadius: '50%', background: ok ? '#4ade80' : '#f59e0b', flexShrink: 0 }} />
                <span style={{ fontSize: 8.5, color: 'var(--t-4)' }}>{label}:</span>
                <span style={{ fontSize: 8.5, color: 'var(--t-2)', fontFamily: 'var(--font-mono)' }}>{value}</span>
              </div>
            ))}
          </div>
        </div>
      )}

    </div>
  )
}

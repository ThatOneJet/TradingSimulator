import { useState, useEffect } from 'react'
import api from '../api.js'

// ── helpers ────────────────────────────────────────────────────────────────

function last(arr) {
  if (!arr || arr.length === 0) return null
  return arr[arr.length - 1]
}

function fmt(n, decimals = 2) {
  if (n == null || isNaN(n)) return '—'
  return Number(n).toFixed(decimals)
}

// ── sub-components ─────────────────────────────────────────────────────────

function SkeletonBar({ width = '100%', height = 10, style = {} }) {
  return (
    <div
      style={{
        width,
        height,
        borderRadius: 4,
        background: 'rgba(140,170,220,0.08)',
        ...style,
      }}
    />
  )
}

function LoadingSkeleton() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '4px 0' }}>
      <SkeletonBar width="55%" height={9} />
      <SkeletonBar width="100%" height={9} />
      <SkeletonBar width="75%" height={9} />
    </div>
  )
}

function RsiMeter({ rsi }) {
  // clamp 0–100
  const pct = Math.max(0, Math.min(100, rsi ?? 50))

  let valueColor = 'var(--t-3)'
  let label = 'Neutral'
  if (pct >= 70) { valueColor = 'var(--err)'; label = 'Overbought' }
  else if (pct <= 30) { valueColor = 'var(--ok)'; label = 'Oversold' }

  return (
    <div style={{ marginBottom: 12 }}>
      {/* label row */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
        marginBottom: 5,
      }}>
        <span style={{
          fontSize: 9,
          letterSpacing: '0.1em',
          textTransform: 'uppercase',
          color: 'var(--t-3)',
          fontFamily: 'var(--font-mono)',
        }}>
          RSI
        </span>
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: valueColor,
          letterSpacing: '0.04em',
        }}>
          {fmt(pct, 1)} <span style={{ fontSize: 9, color: valueColor, opacity: 0.8 }}>{label}</span>
        </span>
      </div>

      {/* bar track */}
      <div style={{
        position: 'relative',
        height: 6,
        borderRadius: 3,
        background: 'var(--hairline-2)',
        overflow: 'visible',
      }}>
        {/* green zone 0–30 */}
        <div style={{
          position: 'absolute',
          left: 0,
          top: 0,
          bottom: 0,
          width: '30%',
          borderRadius: '3px 0 0 3px',
          background: 'rgba(61,220,151,0.25)',
        }} />
        {/* red zone 70–100 */}
        <div style={{
          position: 'absolute',
          right: 0,
          top: 0,
          bottom: 0,
          width: '30%',
          borderRadius: '0 3px 3px 0',
          background: 'rgba(255,71,111,0.25)',
        }} />
        {/* fill up to current value */}
        <div style={{
          position: 'absolute',
          left: 0,
          top: 0,
          bottom: 0,
          width: `${pct}%`,
          borderRadius: 3,
          background: pct >= 70
            ? 'rgba(255,71,111,0.55)'
            : pct <= 30
              ? 'rgba(61,220,151,0.55)'
              : 'rgba(140,170,220,0.30)',
          transition: 'width .4s ease',
        }} />
        {/* position tick */}
        <div style={{
          position: 'absolute',
          top: -2,
          bottom: -2,
          left: `calc(${pct}% - 2px)`,
          width: 4,
          borderRadius: 2,
          background: '#fff',
          boxShadow: '0 0 4px rgba(0,0,0,0.6)',
          transition: 'left .4s ease',
        }} />
      </div>

      {/* scale labels */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        marginTop: 3,
        fontFamily: 'var(--font-mono)',
        fontSize: 8,
        color: 'var(--t-3)',
      }}>
        <span>0</span>
        <span style={{ color: 'var(--ok)', opacity: 0.7 }}>30</span>
        <span>50</span>
        <span style={{ color: 'var(--err)', opacity: 0.7 }}>70</span>
        <span>100</span>
      </div>
    </div>
  )
}

// ── main component ─────────────────────────────────────────────────────────

export default function ProjectionWidget({ symbol }) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(false)

  useEffect(() => {
    if (!symbol) return
    let cancelled = false

    async function load() {
      setLoading(true)
      setError(false)
      setData(null)
      try {
        const res = await api.get(`/projection/${symbol}`)
        if (!cancelled) setData(res.data)
      } catch {
        if (!cancelled) setError(true)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => { cancelled = true }
  }, [symbol])

  if (!symbol) return null

  // ── trend badge ──────────────────────────────────────────────────────────
  function TrendBadge({ trend }) {
    let icon  = '→'
    let label = 'SIDEWAYS'
    let color = 'var(--warn)'
    let bg    = 'rgba(245,179,66,0.10)'
    let border= 'rgba(245,179,66,0.28)'

    if (trend === 'up') {
      icon = '↑'; label = 'UPTREND'
      color = 'var(--ok)'; bg = 'rgba(61,220,151,0.10)'; border = 'rgba(61,220,151,0.28)'
    } else if (trend === 'down') {
      icon = '↓'; label = 'DOWNTREND'
      color = 'var(--err)'; bg = 'rgba(255,71,111,0.10)'; border = 'rgba(255,71,111,0.28)'
    }

    return (
      <span style={{
        display:       'inline-flex',
        alignItems:    'center',
        gap:           3,
        background:    bg,
        border:        `1px solid ${border}`,
        borderRadius:  4,
        padding:       '1px 6px',
        fontSize:      9,
        fontFamily:    'var(--font-mono)',
        fontWeight:    700,
        letterSpacing: '0.07em',
        color,
      }}>
        {icon} {label}
      </span>
    )
  }

  // ── projection table rows ─────────────────────────────────────────────
  function ProjectionRows({ projection, sma20Last }) {
    if (!projection || projection.length === 0) return null

    // Indices 0,2,4,6,9 → "Day 1,3,5,7,10"
    const picks = [
      { dayLabel: 'Day 1',  idx: 0 },
      { dayLabel: 'Day 3',  idx: 2 },
      { dayLabel: 'Day 5',  idx: 4 },
      { dayLabel: 'Day 7',  idx: 6 },
      { dayLabel: 'Day 10', idx: 9 },
    ]

    return (
      <>
        {picks.map(({ dayLabel, idx }) => {
          const point = projection[idx]
          if (!point) return null
          const above = sma20Last != null && point.value > sma20Last
          const priceColor = sma20Last == null
            ? 'var(--t-2)'
            : above ? 'var(--ok)' : 'var(--err)'

          return (
            <div
              key={dayLabel}
              style={{
                display:        'flex',
                justifyContent: 'space-between',
                alignItems:     'center',
                padding:        '3px 0',
                borderBottom:   '1px solid var(--hairline)',
              }}
            >
              <span style={{
                fontSize:      10,
                fontFamily:    'var(--font-mono)',
                color:         'var(--t-3)',
                letterSpacing: '0.04em',
              }}>
                {dayLabel}
              </span>
              <span style={{
                fontSize:      11,
                fontFamily:    'var(--font-mono)',
                color:         priceColor,
                fontWeight:    600,
              }}>
                ${fmt(point.value)}
              </span>
            </div>
          )
        })}
      </>
    )
  }

  // ── section label ────────────────────────────────────────────────────────
  function SectionLabel({ children, style = {} }) {
    return (
      <div style={{
        fontSize:      9,
        letterSpacing: '0.1em',
        textTransform: 'uppercase',
        color:         'var(--t-3)',
        fontFamily:    'var(--font-mono)',
        marginBottom:  6,
        ...style,
      }}>
        {children}
      </div>
    )
  }

  // ── metric row ───────────────────────────────────────────────────────────
  function MetricRow({ label, value, valueColor = 'var(--t-2)', style = {} }) {
    return (
      <div style={{
        display:        'flex',
        justifyContent: 'space-between',
        alignItems:     'center',
        padding:        '4px 0',
        borderBottom:   '1px solid var(--hairline)',
        ...style,
      }}>
        <span style={{
          fontSize:      10,
          fontFamily:    'var(--font-mono)',
          color:         'var(--t-3)',
          letterSpacing: '0.04em',
        }}>
          {label}
        </span>
        <span style={{
          fontSize:   11,
          fontFamily: 'var(--font-mono)',
          color:      valueColor,
          fontWeight: 600,
        }}>
          {value}
        </span>
      </div>
    )
  }

  // ── divider ──────────────────────────────────────────────────────────────
  function Divider() {
    return (
      <div style={{
        height:     1,
        background: 'var(--hairline-2)',
        margin:     '10px 0',
      }} />
    )
  }

  // ── derived values ───────────────────────────────────────────────────────
  const sma20Last  = last(data?.sma20)?.value ?? null
  const sma50Last  = last(data?.sma50)?.value ?? null
  const slope      = data?.slope ?? null
  const slopeColor = slope == null ? 'var(--t-2)' : slope >= 0 ? 'var(--ok)' : 'var(--err)'
  const slopeLabel = slope == null
    ? '—'
    : `${slope >= 0 ? '+' : ''}$${fmt(slope, 2)}/day`

  // ── render ───────────────────────────────────────────────────────────────
  return (
    <div className="widget" style={{ padding: '12px 14px' }}>

      {/* ── Header ── */}
      <div className="widget-hd" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
        <span>PROJECTION</span>
        {data && <TrendBadge trend={data.trend} />}
      </div>

      {/* ── Loading skeleton ── */}
      {loading && <LoadingSkeleton />}

      {/* ── Error state ── */}
      {!loading && error && (
        <div style={{
          fontSize:   11,
          color:      'var(--t-3)',
          textAlign:  'center',
          padding:    '10px 0',
          fontFamily: 'var(--font-sans)',
        }}>
          No projection data available
        </div>
      )}

      {/* ── Data ── */}
      {!loading && !error && data && (
        <>
          {/* RSI meter */}
          <RsiMeter rsi={data.rsi} />

          <Divider />

          {/* Price levels */}
          <SectionLabel>Levels</SectionLabel>

          <div style={{ marginBottom: 10 }}>
            {/* Resistance row */}
            <div style={{
              display:        'flex',
              justifyContent: 'space-between',
              alignItems:     'center',
              padding:        '4px 0',
              borderBottom:   '1px solid var(--hairline)',
            }}>
              <span style={{
                display:    'flex',
                alignItems: 'center',
                gap:        5,
                fontSize:   10,
                fontFamily: 'var(--font-mono)',
                color:      'var(--t-3)',
              }}>
                <span style={{ color: 'var(--err)', fontSize: 11 }}>▶</span>
                RESISTANCE
              </span>
              <span style={{
                fontSize:   11,
                fontFamily: 'var(--font-mono)',
                color:      'var(--err)',
                fontWeight: 600,
              }}>
                ${fmt(data.resistance)}
              </span>
            </div>

            {/* Support row */}
            <div style={{
              display:        'flex',
              justifyContent: 'space-between',
              alignItems:     'center',
              padding:        '4px 0',
              borderBottom:   '1px solid var(--hairline)',
            }}>
              <span style={{
                display:    'flex',
                alignItems: 'center',
                gap:        5,
                fontSize:   10,
                fontFamily: 'var(--font-mono)',
                color:      'var(--t-3)',
              }}>
                <span style={{ color: 'var(--ok)', fontSize: 11 }}>▶</span>
                SUPPORT
              </span>
              <span style={{
                fontSize:   11,
                fontFamily: 'var(--font-mono)',
                color:      'var(--ok)',
                fontWeight: 600,
              }}>
                ${fmt(data.support)}
              </span>
            </div>
          </div>

          <Divider />

          {/* Momentum */}
          <SectionLabel>Momentum</SectionLabel>
          <MetricRow
            label="MOMENTUM"
            value={slopeLabel}
            valueColor={slopeColor}
            style={{ marginBottom: 10, borderBottom: 'none' }}
          />

          <Divider />

          {/* 10-day projection */}
          <SectionLabel>10-Day Projection</SectionLabel>
          <div style={{ marginBottom: 10 }}>
            <ProjectionRows
              projection={data.projection}
              sma20Last={sma20Last}
            />
          </div>

          <Divider />

          {/* SMA summary */}
          <SectionLabel>Moving Averages</SectionLabel>
          <MetricRow
            label="SMA20"
            value={sma20Last != null ? `$${fmt(sma20Last)}` : '—'}
            valueColor="var(--cy)"
          />
          <MetricRow
            label="SMA50"
            value={sma50Last != null ? `$${fmt(sma50Last)}` : 'N/A'}
            valueColor="var(--cy)"
            style={{ borderBottom: 'none' }}
          />
        </>
      )}
    </div>
  )
}

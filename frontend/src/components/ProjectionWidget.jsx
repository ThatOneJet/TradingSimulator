import { useState, useEffect } from 'react'
import api from '../api.js'

function fmt(n, d = 2) {
  if (n == null || isNaN(n)) return '—'
  return Number(n).toFixed(d)
}
function fmtVol(n) {
  if (!n) return '—'
  if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B'
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(0) + 'K'
  return String(n)
}
function last(arr) { return arr?.length ? arr[arr.length - 1] : null }

// ── Sub-components ─────────────────────────────────────────────────────────────

function SectionLabel({ children }) {
  return (
    <div style={{ fontSize: 9, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--t-3)', fontFamily: 'var(--font-mono)', marginBottom: 6, marginTop: 10 }}>
      {children}
    </div>
  )
}

function Row({ label, value, color = 'var(--t-2)', sub }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '3px 0', borderBottom: '1px solid var(--hairline)' }}>
      <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--t-3)', letterSpacing: '0.04em' }}>{label}</span>
      <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 5 }}>
        {value}
        {sub && <span style={{ fontSize: 9, color: 'var(--t-3)', fontWeight: 400 }}>{sub}</span>}
      </span>
    </div>
  )
}

function Divider() {
  return <div style={{ height: 1, background: 'var(--hairline-2)', margin: '10px 0' }} />
}

function SkeletonBar({ width = '100%' }) {
  return <div style={{ width, height: 9, borderRadius: 3, background: 'rgba(140,170,220,0.08)', marginBottom: 8 }} />
}

function MeterBar({ value, min = 0, max = 100, zones }) {
  const pct = Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100))
  return (
    <div style={{ position: 'relative', height: 5, borderRadius: 3, background: 'var(--hairline-2)', overflow: 'visible', marginBottom: 4 }}>
      {zones?.map(z => (
        <div key={z.label} style={{ position: 'absolute', left: `${z.start}%`, width: `${z.end - z.start}%`, top: 0, bottom: 0, background: z.color, borderRadius: z.start === 0 ? '3px 0 0 3px' : z.end === 100 ? '0 3px 3px 0' : 0 }} />
      ))}
      <div style={{ position: 'absolute', left: `calc(${pct}% - 2px)`, top: -3, bottom: -3, width: 4, borderRadius: 2, background: '#fff', boxShadow: '0 0 4px rgba(0,0,0,0.6)' }} />
    </div>
  )
}

function TrendBadge({ trend }) {
  const map = {
    up:       { icon: '↑', label: 'UPTREND',   color: 'var(--ok)',  bg: 'rgba(61,220,151,0.10)',  border: 'rgba(61,220,151,0.28)' },
    down:     { icon: '↓', label: 'DOWNTREND', color: 'var(--err)', bg: 'rgba(255,71,111,0.10)',  border: 'rgba(255,71,111,0.28)' },
    sideways: { icon: '→', label: 'SIDEWAYS',  color: 'var(--warn)',bg: 'rgba(245,179,66,0.10)',  border: 'rgba(245,179,66,0.28)' },
  }
  const t = map[trend] ?? map.sideways
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3, background: t.bg, border: `1px solid ${t.border}`, borderRadius: 4, padding: '1px 6px', fontSize: 9, fontFamily: 'var(--font-mono)', fontWeight: 700, letterSpacing: '0.07em', color: t.color }}>
      {t.icon} {t.label}
    </span>
  )
}

function SignalPill({ label, color }) {
  const colorMap = {
    green: { color: 'var(--ok)',   border: 'rgba(61,220,151,0.35)' },
    red:   { color: 'var(--err)',  border: 'rgba(255,71,111,0.35)' },
    warn:  { color: 'var(--warn)', border: 'rgba(245,179,66,0.35)' },
    muted: { color: 'var(--t-3)',  border: 'var(--hairline-2)' },
  }
  const c = colorMap[color] ?? colorMap.muted
  return (
    <span style={{ fontSize: 9, fontFamily: 'var(--font-mono)', fontWeight: 700, color: c.color, border: `1px solid ${c.border}`, borderRadius: 3, padding: '1px 5px', letterSpacing: '0.05em' }}>
      {label}
    </span>
  )
}

// ── Main component ──────────────────────────────────────────────────────────────

export default function ProjectionWidget({ symbol }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(false)

  useEffect(() => {
    if (!symbol) return
    let cancelled = false
    async function load() {
      setLoading(true); setError(false); setData(null)
      try {
        const res = await api.get(`/projection/${symbol}`)
        if (!cancelled) setData(res.data)
      } catch { if (!cancelled) setError(true) }
      finally  { if (!cancelled) setLoading(false) }
    }
    load()
    return () => { cancelled = true }
  }, [symbol])

  if (!symbol) return null

  const sma20Last = last(data?.sma20)?.value ?? null
  const sma50Last = last(data?.sma50)?.value ?? null
  const slope     = data?.slope ?? null

  // Signal colour helpers
  const macdCross  = data?.macd_cross
  const macdColor  = macdCross?.startsWith('bullish') ? 'var(--ok)' : 'var(--err)'
  const macdPill   = macdCross?.startsWith('bullish') ? (macdCross === 'bullish_cross' ? 'green' : 'green') : (macdCross === 'bearish_cross' ? 'red' : 'red')

  const bbPosMap = { overbought: 'red', oversold: 'green', squeeze: 'warn', upper_half: 'muted', lower_half: 'muted', unknown: 'muted' }
  const bbColor  = { overbought: 'var(--err)', oversold: 'var(--ok)', squeeze: 'var(--warn)', upper_half: 'var(--t-2)', lower_half: 'var(--t-2)' }

  const volColor  = { high_up: 'var(--ok)', high_down: 'var(--err)', low: 'var(--warn)', normal: 'var(--t-2)' }
  const volPill   = { high_up: 'green',     high_down: 'red',        low: 'warn',        normal: 'muted' }
  const volLabel  = { high_up: 'High + Up ✓', high_down: 'High + Down ✗', low: 'Low volume', normal: 'Normal' }

  return (
    <div className="widget" style={{ padding: '12px 14px' }}>

      {data && <div style={{ marginBottom: 10 }}><TrendBadge trend={data.trend} /></div>}
      {loading && <><SkeletonBar width="55%" /><SkeletonBar width="100%" /><SkeletonBar width="75%" /></>}
      {!loading && error && <div style={{ fontSize: 11, color: 'var(--t-3)', textAlign: 'center', padding: '10px 0' }}>No data available</div>}

      {!loading && !error && data && (<>

        {/* ── RSI ── */}
        <div style={{ marginBottom: 6 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 5 }}>
            <span style={{ fontSize: 9, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--t-3)', fontFamily: 'var(--font-mono)' }}>RSI(14)</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: data.rsi >= 70 ? 'var(--err)' : data.rsi <= 30 ? 'var(--ok)' : 'var(--t-3)' }}>
              {fmt(data.rsi, 1)} <span style={{ fontSize: 9, opacity: 0.8 }}>{data.rsi_signal}</span>
            </span>
          </div>
          <MeterBar value={data.rsi} zones={[
            { start: 0,  end: 30,  color: 'rgba(61,220,151,0.25)',  label: 'os' },
            { start: 70, end: 100, color: 'rgba(255,71,111,0.25)',  label: 'ob' },
          ]} />
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 2, fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--t-3)' }}>
            <span>0</span><span style={{ color: 'var(--ok)', opacity: 0.7 }}>30</span><span>50</span><span style={{ color: 'var(--err)', opacity: 0.7 }}>70</span><span>100</span>
          </div>
        </div>

        <Divider />

        {/* ── MACD ── */}
        <SectionLabel>MACD (12,26,9)</SectionLabel>
        <Row label="MACD LINE"   value={`${data.macd_value > 0 ? '+' : ''}${fmt(data.macd_value, 3)}`}      color={macdColor} />
        <Row label="SIGNAL LINE" value={fmt(data.macd_signal_value, 3)} color="var(--t-2)" />
        <Row label="HISTOGRAM"   value={`${(data.macd_value - data.macd_signal_value) >= 0 ? '+' : ''}${fmt(data.macd_value - data.macd_signal_value, 3)}`} color={macdColor} sub={<SignalPill label={macdCross?.replace('_', ' ')} color={macdPill} />} />

        <Divider />

        {/* ── Volume ── */}
        <SectionLabel>Volume</SectionLabel>
        <Row label="LAST VOL"   value={fmtVol(data.last_volume)} color="var(--t-2)" />
        <Row label="20D AVG"    value={fmtVol(data.avg_volume)}  color="var(--t-3)" />
        <Row label="RATIO"      value={`${fmt(data.volume_ratio, 2)}x`}
          color={volColor[data.volume_signal]}
          sub={<SignalPill label={volLabel[data.volume_signal]} color={volPill[data.volume_signal]} />} />
        <div style={{ fontSize: 10, color: 'var(--t-3)', margin: '5px 0 0', lineHeight: 1.4 }}>
          {data.volume_signal === 'high_up'   && 'High volume on up day — confirms buying pressure.'}
          {data.volume_signal === 'high_down' && 'High volume on down day — confirms selling pressure.'}
          {data.volume_signal === 'low'       && 'Below-average volume — treat signals with caution.'}
          {data.volume_signal === 'normal'    && 'Volume is within normal range.'}
        </div>

        <Divider />

        {/* ── Bollinger Bands ── */}
        <SectionLabel>Bollinger Bands (20,2)</SectionLabel>
        <Row label="UPPER BAND" value={`$${fmt(data.bb_upper_val)}`} color="var(--warn)" />
        <Row label="MIDDLE"     value={`$${fmt(last(data.bb_middle)?.value)}`} color="var(--t-3)" />
        <Row label="LOWER BAND" value={`$${fmt(data.bb_lower_val)}`} color="var(--warn)" />
        <Row label="POSITION"   value={data.bb_position?.replace('_', ' ')} color={bbColor[data.bb_position]} sub={<SignalPill label={data.bb_position?.replace('_', ' ')} color={bbPosMap[data.bb_position]} />} />

        <Divider />

        {/* ── Stochastic ── */}
        <SectionLabel>Stochastic (14,3)</SectionLabel>
        <Row label="%K (FAST)" value={fmt(data.stoch_k_val, 1)}
          color={data.stoch_k_val >= 80 ? 'var(--err)' : data.stoch_k_val <= 20 ? 'var(--ok)' : 'var(--t-2)'} />
        <Row label="%D (SLOW)" value={fmt(data.stoch_d_val, 1)} color="var(--t-2)" />
        <Row label="SIGNAL"    value={data.stoch_signal}
          color={data.stoch_signal === 'overbought' ? 'var(--err)' : data.stoch_signal === 'oversold' ? 'var(--ok)' : 'var(--t-3)'}
          sub={<SignalPill label={data.stoch_signal} color={data.stoch_signal === 'overbought' ? 'red' : data.stoch_signal === 'oversold' ? 'green' : 'muted'} />} />
        <MeterBar value={data.stoch_k_val} zones={[
          { start: 0,  end: 20,  color: 'rgba(61,220,151,0.25)',  label: 'os' },
          { start: 80, end: 100, color: 'rgba(255,71,111,0.25)',  label: 'ob' },
        ]} />

        <Divider />

        {/* ── ATR ── */}
        <SectionLabel>ATR (14) — Volatility / Stop Loss</SectionLabel>
        <Row label="ATR VALUE"  value={`$${fmt(data.atr)}`} color="var(--t-2)" />
        <Row label="ATR %"      value={`${fmt(data.atr_pct)}%`} color={data.atr_pct > 3 ? 'var(--warn)' : 'var(--t-2)'} />
        <Row label="1x ATR STOP" value={`$${fmt(last(data.sma20)?.value - data.atr, 2)}`} color="var(--err)" sub="below SMA20" />
        <div style={{ fontSize: 10, color: 'var(--t-3)', margin: '5px 0 0', lineHeight: 1.4 }}>
          {data.atr_pct > 3 ? 'High volatility — use wider stop loss.' : data.atr_pct > 1.5 ? 'Moderate volatility.' : 'Low volatility — tighter stops viable.'}
        </div>

        <Divider />

        {/* ── VWAP ── */}
        <SectionLabel>VWAP (20-day rolling)</SectionLabel>
        <Row label="VWAP"    value={`$${fmt(data.vwap_value)}`} color="var(--acc)" />
        <Row label="SIGNAL"  value={data.vwap_signal === 'above' ? 'Price above VWAP' : 'Price below VWAP'}
          color={data.vwap_signal === 'above' ? 'var(--ok)' : 'var(--err)'}
          sub={<SignalPill label={data.vwap_signal === 'above' ? 'Bullish' : 'Bearish'} color={data.vwap_signal === 'above' ? 'green' : 'red'} />} />

        <Divider />

        {/* ── Price Levels ── */}
        <SectionLabel>Levels</SectionLabel>
        <Row label="▶ RESISTANCE" value={`$${fmt(data.resistance)}`} color="var(--err)" />
        <Row label="▶ SUPPORT"    value={`$${fmt(data.support)}`}    color="var(--ok)"  />

        <Divider />

        {/* ── Momentum + projection ── */}
        <SectionLabel>Momentum</SectionLabel>
        <Row label="SLOPE" value={`${slope >= 0 ? '+' : ''}$${fmt(slope, 2)}/day`} color={slope >= 0 ? 'var(--ok)' : 'var(--err)'} style={{ borderBottom: 'none' }} />

        <Divider />

        <SectionLabel>10-Day Projection</SectionLabel>
        <div style={{ marginBottom: 10 }}>
          {[[0,'Day 1'],[2,'Day 3'],[4,'Day 5'],[6,'Day 7'],[9,'Day 10']].map(([idx, label]) => {
            const pt = data.projection?.[idx]
            if (!pt) return null
            const above = sma20Last != null && pt.value > sma20Last
            return (
              <div key={label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '3px 0', borderBottom: '1px solid var(--hairline)' }}>
                <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--t-3)' }}>{label}</span>
                <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', fontWeight: 600, color: sma20Last == null ? 'var(--t-2)' : above ? 'var(--ok)' : 'var(--err)' }}>
                  ${fmt(pt.value)}
                </span>
              </div>
            )
          })}
        </div>

        <Divider />

        <SectionLabel>Moving Averages</SectionLabel>
        <Row label="SMA20" value={sma20Last != null ? `$${fmt(sma20Last)}` : '—'} color="var(--cy)" />
        <Row label="SMA50" value={sma50Last != null ? `$${fmt(sma50Last)}` : 'N/A'} color="var(--cy)" />

      </>)}
    </div>
  )
}

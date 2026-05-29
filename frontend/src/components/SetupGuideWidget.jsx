import { useState, useEffect } from 'react'
import api from '../api.js'
import { computeDecision } from '../utils/tradeDecision.js'

/* ── Status square colour helper ── */
const statusColor = (status) => {
  if (status === 'met')                           return '#3ddc97'
  if (status === 'partial' || status === 'watch') return '#f5b342'
  return null   // missing = outlined square
}

/* ── Inner content (mounted only when data + price are ready) ── */
function GuideContent({ data, price }) {
  const [side, setSide] = useState('BUY')

  /* ── Raw indicator values ── */
  const rsi    = data.rsi           ?? 50
  const stochK = data.stoch_k_val   ?? 50
  const stochD = data.stoch_d_val   ?? 50
  const macd   = data.macd_cross    ?? ''
  const vol    = data.volume_signal ?? ''
  const volR   = data.volume_ratio  ?? 1
  const bb     = data.bb_position   ?? ''
  const vwap   = data.vwap_signal   ?? ''
  const trend  = data.trend         ?? ''
  const atrPct = data.atr_pct       ?? 2

  /* ── Decision engine ── */
  const dec    = computeDecision(data, price)
  const score  = dec?.score  ?? 0
  const action = dec?.action ?? 'HOLD'

  /* ── Action badge colours ── */
  const acColor = action === 'BUY'  ? '#3ddc97'
                : action === 'SELL' ? '#ff476f'
                :                    '#f5b342'
  const acBg    = action === 'BUY'  ? 'rgba(61,220,151,0.15)'
                : action === 'SELL' ? 'rgba(255,71,111,0.15)'
                :                    'rgba(245,179,66,0.15)'

  /* ── Progress bar: distance to ±2.0 threshold ── */
  const barPct = Math.min(100, (Math.abs(score) / 2.0) * 100)
  const barColor = action === 'BUY'  ? '#3ddc97'
                 : action === 'SELL' ? '#ff476f'
                 :                    '#f5b342'

  const buyGap  = Math.max(0, 2.0 - score).toFixed(1)
  const sellGap = Math.max(0, score + 2.0).toFixed(1)
  const gapText = score >= 2.0   ? 'BUY threshold met'
                : score <= -2.0  ? 'SELL threshold met'
                : side === 'BUY' ? `Need +${buyGap} more for BUY`
                :                  `Need −${sellGap} more for SELL`

  /* ── BUY checklist ── */
  const buyItems = [
    {
      name: 'RSI',
      desc: rsi <= 20 ? `${rsi.toFixed(1)} — extreme oversold, top buy signal`
          : rsi <= 28 ? `${rsi.toFixed(1)} — oversold zone, buyers step in here`
          : rsi <= 38 ? `${rsi.toFixed(1)} — mild oversold, momentum fading`
          : `${rsi.toFixed(1)} — needs to fall below 38${rsi >= 62 ? ' (currently overbought)' : ''}`,
      status: rsi <= 20 ? 'met' : rsi <= 28 ? 'met' : rsi <= 38 ? 'partial' : 'missing',
      pts:    rsi <= 20 ? 3.0 : rsi <= 28 ? 2.0 : rsi <= 38 ? 1.0 : 0,
    },
    {
      name: 'MACD',
      desc: macd === 'bullish_cross' ? 'Fresh bullish crossover — strongest momentum signal'
          : macd === 'bullish'       ? 'Above signal line — sustained bullish momentum'
          : macd === 'bearish_cross' ? 'Just bearish-crossed — watch for reversal cross'
          : 'Below signal line — needs bullish crossover for signal',
      status: macd === 'bullish_cross' ? 'met' : macd === 'bullish' ? 'partial' : 'missing',
      pts:    macd === 'bullish_cross' ? 3.0 : macd === 'bullish' ? 1.5 : 0,
    },
    {
      name: 'Stochastic',
      desc: stochK <= 15 ? `%K ${stochK.toFixed(1)} — deep oversold, snap-back likely`
          : stochK <= 25 ? `%K ${stochK.toFixed(1)} — oversold; confirm %K cross above %D ${stochD.toFixed(1)}`
          : `%K at ${stochK.toFixed(1)} — needs to drop below 25`,
      status: stochK <= 15 ? 'met' : stochK <= 25 ? 'partial' : 'missing',
      pts:    stochK <= 15 ? 1.5 : stochK <= 25 ? 1.0 : 0,
    },
    {
      name: 'Volume',
      desc: vol === 'high_up' ? `${volR.toFixed(2)}× avg on up day — institutional accumulation`
          : vol === 'low'     ? `${volR.toFixed(2)}× avg — thin; signals at 65% weight`
          : 'Needs > 1.5× avg on a green candle for +2 pts',
      status: vol === 'high_up' ? 'met' : vol === 'low' ? 'watch' : 'missing',
      pts:    vol === 'high_up' ? 2.0 : 0,
    },
    {
      name: 'Bollinger Bands',
      desc: bb === 'oversold'   ? 'Below lower band — mean reversion expected'
          : bb === 'lower_half' ? 'Lower half — mild bullish lean'
          : bb === 'squeeze'    ? 'Bands squeezing — breakout imminent, direction TBD'
          : 'Upper bands — needs pullback toward lower band region',
      status: bb === 'oversold' ? 'met' : bb === 'lower_half' ? 'partial' : bb === 'squeeze' ? 'watch' : 'missing',
      pts:    bb === 'oversold' ? 1.5 : bb === 'lower_half' ? 0.5 : 0,
    },
    {
      name: 'VWAP',
      desc: vwap === 'above' ? 'Price above VWAP — institutions net long'
          : 'Price below VWAP — needs to reclaim VWAP for support',
      status: vwap === 'above' ? 'met' : 'missing',
      pts:    vwap === 'above' ? 1.0 : 0,
    },
    {
      name: 'Trend',
      desc: trend === 'up'       ? 'Uptrend confirmed — regression slope positive'
          : trend === 'sideways' ? 'Sideways — breakout above resistance needed'
          : 'Downtrend in effect — needs trend structure reversal',
      status: trend === 'up' ? 'met' : trend === 'sideways' ? 'watch' : 'missing',
      pts:    trend === 'up' ? 1.5 : 0,
    },
  ]

  /* ── SELL checklist ── */
  const sellItems = [
    {
      name: 'RSI',
      desc: rsi >= 80 ? `${rsi.toFixed(1)} — extreme overbought, reversal likely`
          : rsi >= 72 ? `${rsi.toFixed(1)} — overbought, selling pressure increases`
          : rsi >= 62 ? `${rsi.toFixed(1)} — mild overbought, upside thinning`
          : `${rsi.toFixed(1)} — needs to rise above 62${rsi <= 38 ? ' (currently oversold)' : ''}`,
      status: rsi >= 80 ? 'met' : rsi >= 72 ? 'met' : rsi >= 62 ? 'partial' : 'missing',
      pts:    rsi >= 80 ? 3.0 : rsi >= 72 ? 2.0 : rsi >= 62 ? 1.0 : 0,
    },
    {
      name: 'MACD',
      desc: macd === 'bearish_cross' ? 'Fresh bearish crossover — strongest sell signal'
          : macd === 'bearish'       ? 'Below signal line — bears control momentum'
          : macd === 'bullish_cross' ? 'Just bullish-crossed — watch for failure and reversal'
          : 'Above signal line — needs bearish crossover for signal',
      status: macd === 'bearish_cross' ? 'met' : macd === 'bearish' ? 'partial' : 'missing',
      pts:    macd === 'bearish_cross' ? 3.0 : macd === 'bearish' ? 1.5 : 0,
    },
    {
      name: 'Stochastic',
      desc: stochK >= 85 ? `%K ${stochK.toFixed(1)} — deep overbought, exhaustion zone`
          : stochK >= 75 ? `%K ${stochK.toFixed(1)} — overbought; confirm %K cross below %D ${stochD.toFixed(1)}`
          : `%K at ${stochK.toFixed(1)} — needs to rise above 75`,
      status: stochK >= 85 ? 'met' : stochK >= 75 ? 'partial' : 'missing',
      pts:    stochK >= 85 ? 1.5 : stochK >= 75 ? 1.0 : 0,
    },
    {
      name: 'Volume',
      desc: vol === 'high_down' ? `${volR.toFixed(2)}× avg on down day — institutional distribution`
          : vol === 'low'       ? `${volR.toFixed(2)}× avg — thin; signals at 65% weight`
          : 'Needs > 1.5× avg on a red candle for +2 pts',
      status: vol === 'high_down' ? 'met' : vol === 'low' ? 'watch' : 'missing',
      pts:    vol === 'high_down' ? 2.0 : 0,
    },
    {
      name: 'Bollinger Bands',
      desc: bb === 'overbought' ? 'Above upper band — statistically extreme, expect reversion'
          : bb === 'upper_half' ? 'Upper half — mild bearish lean'
          : bb === 'squeeze'    ? 'Bands squeezing — breakout imminent, direction TBD'
          : 'Lower bands — needs push to upper band region',
      status: bb === 'overbought' ? 'met' : bb === 'upper_half' ? 'partial' : bb === 'squeeze' ? 'watch' : 'missing',
      pts:    bb === 'overbought' ? 1.5 : bb === 'upper_half' ? 0.5 : 0,
    },
    {
      name: 'VWAP',
      desc: vwap === 'below' ? 'Price below VWAP — institutions net short'
          : 'Price above VWAP — needs to break below VWAP for resistance',
      status: vwap === 'below' ? 'met' : 'missing',
      pts:    vwap === 'below' ? 1.0 : 0,
    },
    {
      name: 'Trend',
      desc: trend === 'down'     ? 'Downtrend confirmed — regression slope negative'
          : trend === 'sideways' ? 'Sideways — break below support needed for downtrend'
          : 'Uptrend in effect — needs price structure reversal first',
      status: trend === 'down' ? 'met' : trend === 'sideways' ? 'watch' : 'missing',
      pts:    trend === 'down' ? 1.5 : 0,
    },
  ]

  const items = side === 'BUY' ? buyItems : sellItems

  return (
    <>
      {/* ── Header: two rows so BUY/SELL never overflows ── */}
      <div style={{
        background: 'rgba(0,0,0,0.2)',
        borderBottom: '1px solid rgba(140,170,220,0.1)',
      }}>
        {/* Row 1: label · action badge · score · High Vol chip */}
        <div style={{
          padding: '7px 12px 3px',
          display: 'flex', alignItems: 'center', gap: 7,
        }}>
          <span style={{
            fontSize: 9, letterSpacing: '0.08em', color: '#b39dff',
            textTransform: 'uppercase', flexShrink: 0, fontFamily: 'var(--font-mono)',
          }}>
            Signals
          </span>
          <span style={{
            background: acBg, color: acColor,
            border: `1px solid ${acColor}`,
            borderRadius: 4, padding: '1px 7px',
            fontSize: 11, fontWeight: 700, fontFamily: 'var(--font-mono)',
            flexShrink: 0,
          }}>
            {action}
          </span>
          <span style={{
            fontSize: 12, color: '#e6ecf5',
            fontFamily: 'var(--font-mono)', fontWeight: 600, flexShrink: 0,
          }}>
            {score > 0 ? '+' : ''}{score.toFixed(1)}
          </span>
          {atrPct > 3 && (
            <span style={{
              fontSize: 10, background: 'rgba(245,179,66,0.15)',
              color: '#f5b342', border: '1px solid rgba(245,179,66,0.3)',
              borderRadius: 4, padding: '1px 6px', flexShrink: 0,
            }}>
              ⚡ High Vol
            </span>
          )}
        </div>
        {/* Row 2: BUY / SELL toggle */}
        <div style={{ padding: '3px 12px 7px', display: 'flex', gap: 4 }}>
          {['BUY', 'SELL'].map(s => (
            <button
              key={s}
              onClick={() => setSide(s)}
              style={{
                flex: 1, padding: '3px 0', borderRadius: 4,
                fontSize: 10, cursor: 'pointer',
                border: 'none', fontWeight: 600,
                fontFamily: 'var(--font-mono)',
                background: side === s
                  ? (s === 'BUY' ? '#3ddc97' : '#ff476f')
                  : 'rgba(140,170,220,0.1)',
                color: side === s ? '#000' : 'rgba(140,170,220,0.6)',
                transition: 'all .15s',
              }}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* ── Progress bar ── */}
      <div style={{
        padding: '6px 12px 4px',
        borderBottom: '1px solid rgba(140,170,220,0.07)',
      }}>
        <div style={{
          height: 3, background: 'rgba(140,170,220,0.1)',
          borderRadius: 2, overflow: 'hidden',
        }}>
          <div style={{
            height: '100%',
            width: `${barPct}%`,
            background: barColor,
            borderRadius: 2,
            transition: 'width 0.3s',
          }} />
        </div>
        <div style={{
          marginTop: 3, fontSize: 10,
          color: 'rgba(140,170,220,0.45)',
          fontFamily: 'var(--font-mono)',
        }}>
          {gapText}
        </div>
      </div>

      {/* ── Checklist rows ── */}
      <div style={{ paddingBottom: 6 }}>
        {items.map((item, idx) => {
          const sq = statusColor(item.status)
          const hasPts = item.pts !== 0
          return (
            <div
              key={item.name}
              style={{
                display: 'flex', alignItems: 'flex-start', gap: 10,
                padding: '6px 12px',
                background: idx % 2 === 0 ? 'rgba(140,170,220,0.025)' : 'transparent',
                cursor: 'default',
                transition: 'background .12s',
              }}
              onMouseEnter={e => { e.currentTarget.style.background = 'rgba(140,170,220,0.07)' }}
              onMouseLeave={e => { e.currentTarget.style.background = idx % 2 === 0 ? 'rgba(140,170,220,0.025)' : 'transparent' }}
            >
              {/* Status square */}
              <div style={{
                width: 10, height: 10,
                borderRadius: 2,
                flexShrink: 0,
                marginTop: 3,
                background: sq ?? 'transparent',
                border: sq ? 'none' : '1.5px solid rgba(140,170,220,0.25)',
              }} />

              {/* Name + description */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontSize: 12, fontWeight: 600,
                  color: item.status === 'missing' ? 'rgba(230,236,245,0.45)' : '#e6ecf5',
                  lineHeight: 1.3,
                  fontFamily: 'var(--font-mono)',
                }}>
                  {item.name}
                </div>
                <div style={{
                  fontSize: 11, color: '#6b7689',
                  lineHeight: 1.3, marginTop: 1,
                }}>
                  {item.desc}
                </div>
              </div>

              {/* Score */}
              <div style={{
                fontSize: 12, fontFamily: 'var(--font-mono)',
                fontWeight: 700, flexShrink: 0,
                color: hasPts ? '#3ddc97' : 'rgba(140,170,220,0.3)',
                minWidth: 32, textAlign: 'right',
              }}>
                {hasPts ? `+${item.pts}` : '—'}
              </div>
            </div>
          )
        })}
      </div>
    </>
  )
}

/* ── Outer shell — handles data fetching, loading / empty states ── */
export default function SetupGuideWidget({ symbol, quote, delta }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!symbol) return
    let cancelled = false
    setData(null)
    setLoading(true)
    api.get(`/projection/${symbol}`)
      .then(r  => { if (!cancelled) { setData(r.data); setLoading(false) } })
      .catch(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [symbol])

  const price = quote
    ? (quote.bid + quote.ask) / 2
    : delta?.bid
      ? (Number(delta.bid) + Number(delta.ask || delta.bid)) / 2
      : null

  return (
    <div style={{
      background: 'rgba(14,20,32,0.95)',
      border: '1px solid rgba(140,170,220,0.18)',
      borderRadius: 10,
      borderLeft: '3px solid #b39dff',
      fontFamily: 'var(--font-sans)',
      overflow: 'hidden',
      flexShrink: 0,
      boxShadow: '0 4px 24px rgba(0,0,0,0.35)',
    }}>
      {loading && (
        <div style={{
          padding: '28px 14px', textAlign: 'center',
          fontSize: 11, color: 'rgba(140,170,220,0.4)',
          fontFamily: 'var(--font-mono)',
        }}>
          Loading indicators…
        </div>
      )}
      {!loading && (!data || !price) && (
        <div style={{
          padding: '28px 14px', textAlign: 'center',
          fontSize: 11, color: 'rgba(140,170,220,0.4)',
          fontFamily: 'var(--font-mono)',
        }}>
          Waiting for data…
        </div>
      )}
      {!loading && data && price && (
        <GuideContent data={data} price={price} />
      )}
    </div>
  )
}

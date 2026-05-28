import { useState, useEffect } from 'react'
import api from '../api.js'
import { computeDecision } from '../utils/tradeDecision.js'

const GUIDE_STATUS = {
  met:     { char: '✓', color: '#3ddc97' },
  partial: { char: '◑', color: '#f5b342' },
  watch:   { char: '◔', color: '#f5b342' },
  missing: { char: '○', color: 'rgba(140,170,220,0.22)' },
}

function GuideContent({ data, price }) {
  const [side, setSide] = useState('buy')

  const rsi    = data.rsi          ?? 50
  const stochK = data.stoch_k_val  ?? 50
  const stochD = data.stoch_d_val  ?? 50
  const macd   = data.macd_cross   ?? ''
  const vol    = data.volume_signal ?? ''
  const volR   = data.volume_ratio  ?? 1
  const bb     = data.bb_position  ?? ''
  const vwap   = data.vwap_signal  ?? ''
  const trend  = data.trend        ?? ''
  const atrPct = data.atr_pct      ?? 2

  const dec    = computeDecision(data, price)
  const score  = dec?.score  ?? 0
  const action = dec?.action ?? 'HOLD'
  const acColor = action === 'BUY' ? '#3ddc97' : action === 'SELL' ? '#ff476f' : '#f5b342'

  const buyItems = [
    {
      name: 'RSI',
      status: rsi <= 20 ? 'met' : rsi <= 28 ? 'met' : rsi <= 38 ? 'partial' : 'missing',
      pts:   rsi <= 20 ? '+3.0' : rsi <= 28 ? '+2.0' : rsi <= 38 ? '+1.0' : null,
      text:  rsi <= 20 ? `${rsi.toFixed(1)} — extreme oversold, top buy signal`
           : rsi <= 28 ? `${rsi.toFixed(1)} — oversold zone, buyers step in here`
           : rsi <= 38 ? `${rsi.toFixed(1)} — mild oversold, momentum fading`
           : `${rsi.toFixed(1)} — needs to fall below 38${rsi >= 62 ? ' (currently overbought)' : ''}`,
    },
    {
      name: 'MACD',
      status: macd === 'bullish_cross' ? 'met' : macd === 'bullish' ? 'partial' : 'missing',
      pts:   macd === 'bullish_cross' ? '+3.0' : macd === 'bullish' ? '+1.5' : null,
      text:  macd === 'bullish_cross' ? `Fresh bullish crossover — strongest momentum signal`
           : macd === 'bullish'       ? `Above signal line — sustained bullish momentum`
           : macd === 'bearish_cross' ? `Just bearish-crossed — watch for reversal cross`
           : `Below signal line — needs bullish crossover for signal`,
    },
    {
      name: 'Stochastic',
      status: stochK <= 15 ? 'met' : stochK <= 25 ? 'partial' : 'missing',
      pts:   stochK <= 15 ? '+1.5' : stochK <= 25 ? '+1.0' : null,
      text:  stochK <= 15 ? `%K ${stochK.toFixed(1)} — deep oversold, snap-back likely`
           : stochK <= 25 ? `%K ${stochK.toFixed(1)} — oversold; confirm %K cross above %D ${stochD.toFixed(1)}`
           : `%K at ${stochK.toFixed(1)} — needs to drop below 25`,
    },
    {
      name: 'Volume',
      status: vol === 'high_up' ? 'met' : vol === 'low' ? 'watch' : 'missing',
      pts:   vol === 'high_up' ? '+2.0' : null,
      text:  vol === 'high_up' ? `${volR.toFixed(2)}× avg on up day — institutional accumulation`
           : vol === 'low'     ? `${volR.toFixed(2)}× avg — thin; signals at 65% weight`
           : `Needs > 1.5× avg on a green candle for +2 pts`,
    },
    {
      name: 'Bollinger Bands',
      status: bb === 'oversold' ? 'met' : bb === 'lower_half' ? 'partial' : bb === 'squeeze' ? 'watch' : 'missing',
      pts:   bb === 'oversold' ? '+1.5' : bb === 'lower_half' ? '+0.5' : null,
      text:  bb === 'oversold'   ? `Below lower band — mean reversion expected`
           : bb === 'lower_half' ? `Lower half — mild bullish lean`
           : bb === 'squeeze'    ? `Bands squeezing — breakout imminent, direction TBD`
           : `Upper bands — needs pullback toward lower band region`,
    },
    {
      name: 'VWAP',
      status: vwap === 'above' ? 'met' : 'missing',
      pts:   vwap === 'above' ? '+1.0' : null,
      text:  vwap === 'above' ? `Price above VWAP — institutions net long`
           : `Price below VWAP — needs to reclaim VWAP for support`,
    },
    {
      name: 'Trend',
      status: trend === 'up' ? 'met' : trend === 'sideways' ? 'watch' : 'missing',
      pts:   trend === 'up' ? '+1.5' : null,
      text:  trend === 'up'       ? `Uptrend confirmed — regression slope positive`
           : trend === 'sideways' ? `Sideways — breakout above resistance needed`
           : `Downtrend in effect — needs trend structure reversal`,
    },
  ]

  const sellItems = [
    {
      name: 'RSI',
      status: rsi >= 80 ? 'met' : rsi >= 72 ? 'met' : rsi >= 62 ? 'partial' : 'missing',
      pts:   rsi >= 80 ? '+3.0' : rsi >= 72 ? '+2.0' : rsi >= 62 ? '+1.0' : null,
      text:  rsi >= 80 ? `${rsi.toFixed(1)} — extreme overbought, reversal likely`
           : rsi >= 72 ? `${rsi.toFixed(1)} — overbought, selling pressure increases`
           : rsi >= 62 ? `${rsi.toFixed(1)} — mild overbought, upside thinning`
           : `${rsi.toFixed(1)} — needs to rise above 62${rsi <= 38 ? ' (currently oversold)' : ''}`,
    },
    {
      name: 'MACD',
      status: macd === 'bearish_cross' ? 'met' : macd === 'bearish' ? 'partial' : 'missing',
      pts:   macd === 'bearish_cross' ? '+3.0' : macd === 'bearish' ? '+1.5' : null,
      text:  macd === 'bearish_cross' ? `Fresh bearish crossover — strongest sell signal`
           : macd === 'bearish'       ? `Below signal line — bears control momentum`
           : macd === 'bullish_cross' ? `Just bullish-crossed — watch for failure and reversal`
           : `Above signal line — needs bearish crossover for signal`,
    },
    {
      name: 'Stochastic',
      status: stochK >= 85 ? 'met' : stochK >= 75 ? 'partial' : 'missing',
      pts:   stochK >= 85 ? '+1.5' : stochK >= 75 ? '+1.0' : null,
      text:  stochK >= 85 ? `%K ${stochK.toFixed(1)} — deep overbought, exhaustion zone`
           : stochK >= 75 ? `%K ${stochK.toFixed(1)} — overbought; confirm %K cross below %D ${stochD.toFixed(1)}`
           : `%K at ${stochK.toFixed(1)} — needs to rise above 75`,
    },
    {
      name: 'Volume',
      status: vol === 'high_down' ? 'met' : vol === 'low' ? 'watch' : 'missing',
      pts:   vol === 'high_down' ? '+2.0' : null,
      text:  vol === 'high_down' ? `${volR.toFixed(2)}× avg on down day — institutional distribution`
           : vol === 'low'       ? `${volR.toFixed(2)}× avg — thin; signals at 65% weight`
           : `Needs > 1.5× avg on a red candle for +2 pts`,
    },
    {
      name: 'Bollinger Bands',
      status: bb === 'overbought' ? 'met' : bb === 'upper_half' ? 'partial' : bb === 'squeeze' ? 'watch' : 'missing',
      pts:   bb === 'overbought' ? '+1.5' : bb === 'upper_half' ? '+0.5' : null,
      text:  bb === 'overbought' ? `Above upper band — statistically extreme, expect reversion`
           : bb === 'upper_half' ? `Upper half — mild bearish lean`
           : bb === 'squeeze'    ? `Bands squeezing — breakout imminent, direction TBD`
           : `Lower bands — needs push to upper band region`,
    },
    {
      name: 'VWAP',
      status: vwap === 'below' ? 'met' : 'missing',
      pts:   vwap === 'below' ? '+1.0' : null,
      text:  vwap === 'below' ? `Price below VWAP — institutions net short`
           : `Price above VWAP — needs to break below VWAP for resistance`,
    },
    {
      name: 'Trend',
      status: trend === 'down' ? 'met' : trend === 'sideways' ? 'watch' : 'missing',
      pts:   trend === 'down' ? '+1.5' : null,
      text:  trend === 'down'     ? `Downtrend confirmed — regression slope negative`
           : trend === 'sideways' ? `Sideways — break below support needed for downtrend`
           : `Uptrend in effect — needs price structure reversal first`,
    },
  ]

  const activeItems = side === 'buy' ? buyItems : sellItems
  const buyGap  = Math.max(0, 2.0 - score).toFixed(1)
  const sellGap = Math.max(0, score + 2.0).toFixed(1)

  return (
    <>
      {/* Score + BUY/SELL toggle */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, paddingBottom: 8, borderBottom: '1px solid var(--hairline)' }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 9, color: 'var(--t-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 2 }}>
            Current Signal
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 700, color: acColor }}>
            {action}&nbsp;<span style={{ opacity: 0.65, fontSize: 10 }}>(score {score > 0 ? '+' : ''}{score})</span>
          </div>
          {action === 'HOLD' && (
            <div style={{ fontSize: 9, color: 'var(--t-4)', marginTop: 2 }}>
              {side === 'buy'
                ? `+${buyGap} pts needed for BUY`
                : `${sellGap} pts to drop for SELL`}
            </div>
          )}
        </div>
        <div style={{ display: 'flex', background: 'var(--bg-card-hi)', border: '1px solid var(--hairline-2)', borderRadius: 5, overflow: 'hidden', flexShrink: 0 }}>
          {['buy', 'sell'].map(s => (
            <button key={s} onClick={() => setSide(s)} style={{
              background: side === s
                ? (s === 'buy' ? 'rgba(61,220,151,0.16)' : 'rgba(255,71,111,0.16)')
                : 'transparent',
              border: 'none',
              color: side === s ? (s === 'buy' ? '#3ddc97' : '#ff476f') : 'var(--t-3)',
              fontSize: 10, fontWeight: side === s ? 700 : 400,
              padding: '4px 12px', cursor: 'pointer',
              textTransform: 'uppercase', letterSpacing: '0.06em', transition: 'all .15s',
            }}>
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* Checklist */}
      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {activeItems.map((item, i) => {
          const st = GUIDE_STATUS[item.status]
          return (
            <div key={i} style={{ display: 'flex', gap: 7, padding: '5px 0', borderBottom: '1px solid rgba(140,170,220,0.05)' }}>
              <span style={{ fontSize: 11, color: st.color, flexShrink: 0, width: 13, textAlign: 'center', fontWeight: 700, marginTop: 1 }}>
                {st.char}
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 4 }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 700, color: item.status === 'missing' ? 'var(--t-3)' : 'var(--t-2)', letterSpacing: '0.04em' }}>
                    {item.name}
                  </span>
                  {item.pts && (
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: st.color, fontWeight: 700, flexShrink: 0 }}>
                      {item.pts}
                    </span>
                  )}
                </div>
                <div style={{ fontSize: 10, color: item.status === 'missing' ? 'var(--t-4)' : 'var(--t-3)', lineHeight: 1.4, marginTop: 1 }}>
                  {item.text}
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {atrPct > 3 && (
        <div style={{ marginTop: 8, padding: '5px 8px', background: 'rgba(255,71,111,0.06)', border: '1px solid rgba(255,71,111,0.15)', borderRadius: 4, fontSize: 10, color: '#ff6a6a', lineHeight: 1.4 }}>
          ⚠ ATR {atrPct.toFixed(1)}% — high volatility; reduce size, widen stops
        </div>
      )}
    </>
  )
}

export default function SetupGuideWidget({ symbol, quote, delta }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!symbol) return
    let cancelled = false
    setData(null)
    setLoading(true)
    api.get(`/projection/${symbol}`)
      .then(r => { if (!cancelled) { setData(r.data); setLoading(false) } })
      .catch(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [symbol])

  const price = quote
    ? (quote.bid + quote.ask) / 2
    : delta?.bid
      ? (Number(delta.bid) + Number(delta.ask || delta.bid)) / 2
      : null

  return (
    <div className="setup-guide">

      <div className="setup-guide-hd">
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#b39dff', boxShadow: '0 0 5px #b39dff66', flexShrink: 0 }} />
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--t-2)' }}>
            Setup Guide
          </span>
        </div>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--t-4)', letterSpacing: '0.06em' }}>
          {symbol}
        </span>
      </div>

      <div className="setup-guide-body">
        {loading && (
          <div style={{ padding: '16px 0', textAlign: 'center', fontSize: 11, color: 'var(--t-3)' }}>
            Loading indicators…
          </div>
        )}
        {!loading && (!data || !price) && (
          <div style={{ padding: '16px 0', textAlign: 'center', fontSize: 11, color: 'var(--t-3)' }}>
            Waiting for data…
          </div>
        )}
        {!loading && data && price && <GuideContent data={data} price={price} />}
      </div>

    </div>
  )
}

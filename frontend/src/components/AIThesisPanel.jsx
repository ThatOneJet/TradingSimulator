import { useMemo } from 'react'
import { computeDecision } from '../utils/tradeDecision'

const REGIME_DISPLAY = {
  'trending_up':     { label: 'Trending Up',     icon: '↗', color: '#3ddc97' },
  'trending_down':   { label: 'Trending Down',   icon: '↘', color: '#ff476f' },
  'consolidating':   { label: 'Consolidating',   icon: '↔', color: '#f5b342' },
  'high_volatility': { label: 'High Volatility', icon: '⚡', color: '#ff9a3c' },
  'neutral':         { label: 'Neutral',          icon: '→', color: '#6b7689' },
}

function buildExplanation(decision, data, price) {
  const { action, score, bulls, bears } = decision
  const parts = []

  // Why section
  if (action === 'HOLD') {
    parts.push('Mixed signals — no clear directional edge at current levels.')
  } else if (action === 'BUY') {
    if (data?.rsi != null && data.rsi <= 35)
      parts.push(`RSI at ${data.rsi.toFixed(1)} is oversold — buyers historically step in here.`)
    if (data?.stoch_k_val != null && data.stoch_k_val <= 25)
      parts.push(`Stochastic %K at ${data.stoch_k_val.toFixed(1)} is deep oversold, increasing snap-back probability.`)
    if (data?.bb_position === 'oversold' || data?.bb_position === 'lower_half')
      parts.push('Price near the lower Bollinger Band — statistical mean reversion setup.')
    if (data?.macd_cross === 'bullish_cross')
      parts.push('MACD bullish crossover signals a fresh momentum shift.')
    else if (data?.macd_cross === 'bullish')
      parts.push('MACD is trending bullish above its signal line.')
    if (data?.volume_signal === 'high_up')
      parts.push('Above-average volume on an up day confirms institutional accumulation.')
    if (data?.trend === 'up')
      parts.push('Broader regression slope is positive — trading with the trend.')
  } else {
    if (data?.rsi != null && data.rsi >= 65)
      parts.push(`RSI at ${data.rsi.toFixed(1)} is overbought — exhaustion risk is rising.`)
    if (data?.macd_cross === 'bearish_cross')
      parts.push('MACD bearish crossover signals loss of upside momentum.')
    if (data?.bb_position === 'overbought' || data?.bb_position === 'upper_half')
      parts.push('Price at the upper Bollinger Band — a distribution zone.')
    if (data?.volume_signal === 'high_down')
      parts.push('High volume on a down move signals active institutional selling.')
  }

  if (parts.length === 0)
    parts.push(`Score of ${score > 0 ? '+' : ''}${score.toFixed(1)} with ${bulls?.length || 0} bullish and ${bears?.length || 0} bearish signals.`)

  // Invalidation woven in at the end
  const inv = []
  if (action === 'BUY') {
    if (data?.atr && price) inv.push(`a close below $${(price - 2 * data.atr).toFixed(2)} (2× ATR stop)`)
    if (data?.macd_cross === 'bullish' || data?.macd_cross === 'bullish_cross')
      inv.push('a MACD bearish crossover')
    if (data?.vwap_signal === 'above' && data?.vwap_value)
      inv.push(`failure to hold VWAP ($${Number(data.vwap_value).toFixed(2)})`)
  } else if (action === 'SELL') {
    if (data?.atr && price) inv.push(`a recovery above $${(price + 2 * data.atr).toFixed(2)} (2× ATR)`)
    inv.push('a MACD bullish crossover')
  } else {
    inv.push('score reaching ≥ +2.0 or ≤ −2.0')
    inv.push('a significant volume expansion in either direction')
  }

  if (inv.length > 0)
    parts.push(`Exit the trade on: ${inv.join(', ')}.`)

  return parts.join(' ')
}

export default function AIThesisPanel({ data, price, symbol }) {
  const decision = useMemo(() => {
    if (!data || !price) return null
    try { return computeDecision(data, price) } catch { return null }
  }, [data, price])

  if (!decision) return (
    <div style={{ padding: '24px', textAlign: 'center', color: '#6b7689', fontSize: '13px' }}>
      Load a symbol to see AI analysis
    </div>
  )

  const { action, score, confidence } = decision
  const actionColor = action === 'BUY' ? '#3ddc97' : action === 'SELL' ? '#ff476f' : '#f5b342'
  const actionBg    = action === 'BUY' ? 'rgba(61,220,151,0.12)' : action === 'SELL' ? 'rgba(255,71,111,0.12)' : 'rgba(245,179,66,0.12)'
  const explanation = buildExplanation(decision, data, price)
  const regime      = data?.regime ? (REGIME_DISPLAY[data.regime] || REGIME_DISPLAY.neutral) : null

  return (
    <div style={{ fontFamily: 'var(--font-sans)', fontSize: '13px' }}>
      {/* Header */}
      <div style={{
        padding: '12px 14px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        background: 'rgba(0,0,0,0.15)',
        borderBottom: '1px solid rgba(140,170,220,0.07)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{
            padding: '3px 12px', borderRadius: '5px', fontSize: '13px', fontWeight: 700,
            background: actionBg, color: actionColor, border: `1px solid ${actionColor}`,
            fontFamily: 'var(--font-mono)',
          }}>{action}</span>
          <span style={{ fontSize: '12px', color: '#e6ecf5', fontFamily: 'var(--font-mono)' }}>
            {score > 0 ? '+' : ''}{score.toFixed(1)}&nbsp;·&nbsp;{confidence}%
          </span>
        </div>
        {regime && (
          <span style={{ fontSize: '11px', color: regime.color, display: 'flex', alignItems: 'center', gap: '4px' }}>
            <span>{regime.icon}</span><span>{regime.label}</span>
          </span>
        )}
      </div>

      {/* Explanation + invalidation combined */}
      <div style={{ padding: '14px' }}>
        <div style={{ fontSize: '9px', letterSpacing: '0.08em', color: '#6b7689', textTransform: 'uppercase', marginBottom: '8px' }}>
          AI Explanation
        </div>
        <p style={{
          margin: 0, color: '#aab4c5', lineHeight: '1.7', fontSize: '12px',
          padding: '10px 12px',
          background: `${actionColor}08`,
          borderLeft: `2px solid ${actionColor}44`,
          borderRadius: '0 6px 6px 0',
        }}>
          {explanation}
        </p>
      </div>
    </div>
  )
}

import { useState, useEffect, useRef, lazy, Suspense } from 'react'
import api from '../api.js'
import { computeDecision } from '../utils/tradeDecision.js'
import AIThesisPanel from './AIThesisPanel.jsx'
import RiskPanel from './RiskPanel'

function RiskPanelInline({ symbol, portfolioId, price }) {
  return (
    <div style={{ padding: '4px 0' }}>
      <RiskPanel symbol={symbol} portfolioId={portfolioId} price={price} />
    </div>
  )
}

function f(n, d = 2) { return (n == null || isNaN(n)) ? '—' : Number(n).toFixed(d) }

function fmtVol(n) {
  if (!n) return '—'
  if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B'
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(0) + 'K'
  return String(Math.round(n))
}

const SIG_COLOR = {
  bullish_cross: '#3ddc97', bullish: '#3ddc97',
  bearish_cross: '#ff476f', bearish: '#ff476f',
  overbought: '#ff476f', oversold: '#3ddc97',
  upper_half: '#aab4c5', lower_half: '#aab4c5',
  squeeze: '#f5b342', neutral: '#6b7689',
  above: '#3ddc97', below: '#ff476f',
  high_up: '#3ddc97', high_down: '#ff476f',
  low: '#f5b342', normal: '#6b7689',
}

const MARKET_STATE_CFG = {
  panic:              { color: '#ff1a4e', label: 'PANIC',          bg: 'rgba(255,26,78,0.12)'  },
  overbought_extreme: { color: '#ff476f', label: 'OVERBOUGHT',     bg: 'rgba(255,71,111,0.10)' },
  oversold_extreme:   { color: '#3ddc97', label: 'OVERSOLD',       bg: 'rgba(61,220,151,0.10)' },
  breakout:           { color: '#f5b342', label: 'BREAKOUT',       bg: 'rgba(245,179,66,0.10)' },
  trending_up:        { color: '#3ddc97', label: 'TRENDING UP',    bg: 'rgba(61,220,151,0.08)' },
  trending_down:      { color: '#ff476f', label: 'TRENDING DOWN',  bg: 'rgba(255,71,111,0.08)' },
  accumulation:       { color: '#4ad9ff', label: 'ACCUMULATION',   bg: 'rgba(74,217,255,0.08)' },
  ranging:            { color: '#8899aa', label: 'RANGING',        bg: 'rgba(136,153,170,0.07)' },
  mild_uptrend:       { color: '#5ee8a9', label: 'MILD UPTREND',   bg: 'rgba(94,232,169,0.07)' },
  mild_downtrend:     { color: '#ff6a6a', label: 'MILD DOWNTREND', bg: 'rgba(255,106,106,0.07)' },
  neutral:            { color: '#6b7689', label: 'NEUTRAL',        bg: 'rgba(107,118,137,0.06)' },
}

function SigBadge({ val }) {
  const color = SIG_COLOR[val] ?? '#6b7689'
  return (
    <span style={{ fontSize: 9, fontFamily: 'var(--font-mono)', fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color, border: `1px solid ${color}44`, borderRadius: 3, padding: '1px 5px', flexShrink: 0 }}>
      {String(val).replace(/_/g, ' ')}
    </span>
  )
}

function MiniMeter({ value = 50, lo = 30, hi = 70 }) {
  const pct  = Math.max(0, Math.min(100, value))
  const fill = value >= hi ? '#ff476f' : value <= lo ? '#3ddc97' : '#8899aa'
  return (
    <div style={{ position: 'relative', height: 4, borderRadius: 2, background: 'rgba(140,170,220,0.08)', margin: '5px 0 2px' }}>
      <div style={{ position: 'absolute', left: `${lo}%`, width: `${hi - lo}%`, top: 0, bottom: 0, background: 'rgba(140,170,220,0.06)' }} />
      <div style={{ position: 'absolute', left: 0, width: `${pct}%`, top: 0, bottom: 0, borderRadius: 2, background: fill, opacity: 0.65, transition: 'width .4s' }} />
      <div style={{ position: 'absolute', left: `calc(${pct}% - 2px)`, top: -3, bottom: -3, width: 4, borderRadius: 2, background: '#fff', boxShadow: '0 0 4px rgba(0,0,0,0.5)', transition: 'left .4s' }} />
    </div>
  )
}

function MeterLabels({ lo, hi }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 8, fontFamily: 'var(--font-mono)', color: 'var(--t-3)', marginBottom: 6 }}>
      <span style={{ color: '#3ddc97' }}>Oversold {lo}</span>
      <span style={{ color: '#ff476f' }}>{hi} Overbought</span>
    </div>
  )
}

function Row({ label, value, color, badge, mono = true }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0', borderBottom: '1px solid rgba(140,170,220,0.06)' }}>
      <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--t-3)', letterSpacing: '0.04em', flexShrink: 0, marginRight: 8 }}>{label}</span>
      <span style={{ fontFamily: mono ? 'var(--font-mono)' : 'var(--font-sans)', fontSize: 11, color: color ?? 'var(--t-2)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6 }}>
        {badge && <SigBadge val={badge} />}
        {value}
      </span>
    </div>
  )
}

function ContribBar({ label, contrib, signal, weight = 1, penalty = false }) {
  const maxC = 3.5
  const pct   = Math.min(100, Math.abs(contrib) / maxC * 100)
  const color = contrib > 0.05 ? '#3ddc97' : contrib < -0.05 ? '#ff476f' : '#475061'
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3 }}>
        <div style={{ display: 'flex', gap: 5, alignItems: 'center' }}>
          <span style={{ fontSize: 9.5, fontFamily: 'var(--font-mono)', color: 'var(--t-3)', letterSpacing: '0.05em' }}>{label}</span>
          {weight !== 1 && <span style={{ fontSize: 8, color: '#f5b342', fontFamily: 'var(--font-mono)' }}>×{weight.toFixed(1)}</span>}
          {penalty   && <span style={{ fontSize: 8, color: '#ff6a6a' }}>trend↓</span>}
        </div>
        <div style={{ display: 'flex', gap: 5, alignItems: 'center' }}>
          {signal && <SigBadge val={signal} />}
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color, fontWeight: 700 }}>
            {contrib > 0 ? '+' : ''}{contrib.toFixed(2)}
          </span>
        </div>
      </div>
      <div style={{ position: 'relative', height: 4, background: 'rgba(140,170,220,0.08)', borderRadius: 2 }}>
        <div style={{ position: 'absolute', left: '50%', top: 0, bottom: 0, width: 1, background: 'rgba(140,170,220,0.15)' }} />
        {contrib !== 0 && (
          <div style={{
            position: 'absolute',
            [contrib > 0 ? 'left' : 'right']: 0,
            width: `${pct / 2}%`,
            top: 0, bottom: 0,
            background: color, borderRadius: 2, opacity: 0.8,
            transition: 'width 0.4s',
          }} />
        )}
      </div>
    </div>
  )
}

function Interp({ children }) {
  return (
    <div style={{ fontSize: 10.5, color: 'var(--t-2)', lineHeight: 1.65, marginTop: 10, padding: '8px 10px', background: 'rgba(140,170,220,0.04)', borderLeft: '2px solid rgba(140,170,220,0.15)', borderRadius: '0 4px 4px 0' }}>
      {children}
    </div>
  )
}

// ── Plain-language interpretation helpers ─────────────────────────────────────

function rsiInterp(rsi) {
  if (rsi == null) return null
  const r = Number(rsi)
  if (r <= 20) return `RSI of ${r.toFixed(1)} is extreme oversold. Sellers are exhausted — this level appears fewer than 2% of trading days. A reversal candle or MACD bullish cross would be a high-conviction buy signal.`
  if (r <= 30) return `RSI of ${r.toFixed(1)} is oversold. Buyers historically step in here. Watch for RSI to cross back above 30 — that confirmation often precedes a sustained bounce.`
  if (r <= 42) return `RSI of ${r.toFixed(1)} is in the lower neutral range. Downside momentum is fading but no buy signal yet. Price has room to push higher without becoming overbought.`
  if (r <= 58) return `RSI of ${r.toFixed(1)} is neutral — neither overbought nor oversold. Price is in balance. Rely on other signals (MACD, VWAP) to determine direction.`
  if (r <= 65) return `RSI of ${r.toFixed(1)} is in the upper neutral range. Momentum is positive and there's still room to run. Holding longs is reasonable, but fresh entries carry moderate risk.`
  if (r <= 75) return `RSI of ${r.toFixed(1)} is approaching overbought. Buyers remain in control but the stock is getting stretched. Avoid chasing — wait for a pullback to enter.`
  if (r <= 85) return `RSI of ${r.toFixed(1)} is overbought. The rally is extended and a pullback or consolidation is likely before any further upside. Consider trimming positions.`
  return `RSI of ${r.toFixed(1)} is extremely overbought. Very rare reading — sharp mean reversion is likely near term. High risk for new buyers.`
}

function macdInterp(cross, macdVal, signalVal) {
  const diff = (macdVal ?? 0) - (signalVal ?? 0)
  if (cross === 'bullish_cross') return `MACD just crossed above its signal line — a confirmed bullish momentum shift. This is one of the most reliable entry signals in technical analysis. Early buyers get the best risk/reward.`
  if (cross === 'bearish_cross') return `MACD just crossed below its signal line — momentum has turned bearish. Classic exit or short signal. Selling pressure is gaining control and may accelerate.`
  if (cross === 'bullish') return `MACD (${f(macdVal, 4)}) has been consistently above its signal line — sustained bullish momentum. The trend is intact; pullbacks are buying opportunities as long as MACD stays above signal.`
  if (cross === 'bearish') return `MACD (${f(macdVal, 4)}) has been below its signal line — bears control momentum. Any bounce is likely a selling opportunity rather than the start of a new uptrend.`
  return `MACD is near neutral (${diff >= 0 ? '+' : ''}${diff.toFixed(4)}). No directional conviction from this indicator. Wait for a clear cross before acting on MACD.`
}

function stochInterp(k, d) {
  const kv = Number(k ?? 50)
  const dv = Number(d ?? 50)
  if (kv <= 15) return `%K of ${kv.toFixed(1)} is deeply oversold. Stochastic at these levels nearly always precedes a snap-back rally. A %K cross above %D (${dv.toFixed(1)}) here would be a strong trigger.`
  if (kv <= 25) return `%K of ${kv.toFixed(1)} is oversold. Sellers are losing steam. A %K crossing above %D (${dv.toFixed(1)}) would confirm buyers are stepping in and a reversal is underway.`
  if (kv >= 85) return `%K of ${kv.toFixed(1)} is deeply overbought. Buying momentum is fading at extremes. Watch for %K to cross below %D (${dv.toFixed(1)}) as a sell trigger.`
  if (kv >= 75) return `%K of ${kv.toFixed(1)} is overbought. The stock has been strong but may need a rest. A cross below %D (${dv.toFixed(1)}) would signal bearish momentum is resuming.`
  return `%K of ${kv.toFixed(1)} is in the neutral zone (${dv.toFixed(1)} %D). No extreme reading from Stochastic — use RSI and MACD for directional guidance.`
}

function volumeInterp(signal, ratio) {
  const r = Number(ratio ?? 1)
  if (signal === 'high_up') return `Volume is ${r.toFixed(2)}× above average on an up day — institutional accumulation. High-volume advances carry conviction and are statistically more likely to continue.`
  if (signal === 'high_down') return `Volume is ${r.toFixed(2)}× above average on a down day — institutional distribution. Institutions are unloading shares, which typically leads to further downside.`
  if (signal === 'low') return `Volume is only ${r.toFixed(2)}× of its 20-day average — well below normal. Without volume confirmation, any signal today carries reduced reliability. Wait for volume to return.`
  return `Volume is ${r.toFixed(2)}× of average — within normal range. Signals carry full weight. Volume is not skewing the read either way today.`
}

function bbInterp(pos, upper, lower) {
  const mid = ((upper ?? 0) + (lower ?? 0)) / 2
  if (pos === 'overbought') return `Price has broken above the upper band ($${f(upper)}). This happens ~2% of trading days. Statistical gravity pulls price back toward the midline ($${f(mid)}). Avoid new longs; look to take profits.`
  if (pos === 'oversold') return `Price has broken below the lower band ($${f(lower)}). Mean reversion toward the midline ($${f(mid)}) is the most probable next move. A volume-confirmed bounce here is a high-probability setup.`
  if (pos === 'squeeze') return `Bollinger Bands are squeezing — volatility is near historical lows. A large directional move is imminent. The first candle that breaks outside the bands will set the direction for the trade.`
  if (pos === 'upper_half') return `Price is in the upper half of the bands (midline: $${f(mid)}). Bulls are in mild control. A break above the upper band ($${f(upper)}) would signal a strong momentum move.`
  if (pos === 'lower_half') return `Price is in the lower half of the bands (midline: $${f(mid)}). Bears have mild control. The lower band ($${f(lower)}) is key support — a break below turns the read decisively bearish.`
  return `Price is trading inside the Bollinger Bands with the midline at $${f(mid)}. Range-bound conditions. The midline acts as dynamic support/resistance.`
}

function atrInterp(atr, atrPct) {
  const a = Number(atr ?? 0)
  const p = Number(atrPct ?? 0)
  const stop = (a * 1.5).toFixed(2)
  if (p > 4) return `ATR of $${f(atr)} (${f(atrPct)}% of price) signals high volatility. Widen your stop to 1.5×ATR = $${stop} to avoid noise-driven exits. Reduce position size to keep dollar risk constant.`
  if (p > 2) return `ATR of $${f(atr)} (${f(atrPct)}%) is elevated but manageable. A 1.5×ATR stop at $${stop} gives good protection. This is an active stock — adjust size accordingly.`
  if (p > 1) return `ATR of $${f(atr)} (${f(atrPct)}%) is moderate. A stop at $${stop} (1.5×ATR) is standard and appropriate. Price swings are predictable in this environment.`
  return `ATR of $${f(atr)} (${f(atrPct)}%) is very low — compressed volatility. Tight stops ($${stop}) are viable, but watch for a sudden volatility expansion. This often precedes a Bollinger Band breakout.`
}

function vwapInterp(signal, vwapVal, price) {
  const pct = price && vwapVal ? ((price - vwapVal) / vwapVal * 100).toFixed(2) : null
  if (signal === 'above') return `Price is ${pct != null ? `${pct}% ` : ''}above VWAP ($${f(vwapVal)}). Institutional VWAP algorithms are net buyers — this confirms today's tape favors longs. VWAP acts as dynamic support on any intraday dip.`
  if (signal === 'below') return `Price is ${pct != null ? `${Math.abs(pct)}% ` : ''}below VWAP ($${f(vwapVal)}). Institutional algorithms are net sellers. Bounces toward VWAP are resistance, not buying opportunities.`
  return `Price is trading at VWAP ($${f(vwapVal)}) — the key equilibrium level. The direction of the next significant move from here often sets the intraday trend.`
}

// ── Smart Summary Card — plain-language bias + group states ──────────────────

function SmartSummaryCard({ data, price }) {
  if (!data || !price) return null
  const dec = computeDecision(data, price)
  if (!dec) return null

  const rsi    = data.rsi          ?? 50
  const stochK = data.stoch_k_val  ?? 50
  const macd   = data.macd_cross   ?? ''
  const vol    = data.volume_signal ?? ''
  const volR   = data.volume_ratio  ?? 1
  const bb     = data.bb_position  ?? ''
  const vwap   = data.vwap_signal  ?? ''
  const trend  = data.trend        ?? ''
  const atrPct = data.atr_pct      ?? 2
  const vwapV  = data.vwap_value   ?? 0
  const res    = data.resistance   ?? price * 1.02
  const sup    = data.support      ?? price * 0.98

  // ── Trend group ──────────────────────────────────────────────────────────────
  const [trendState, trendColor] =
    trend === 'up'   && vwap === 'above' ? ['Strong Bullish Trend',  '#3ddc97'] :
    trend === 'up'                        ? ['Bullish Trend',         '#3ddc97'] :
    trend === 'down' && vwap === 'below'  ? ['Strong Bearish Trend',  '#ff476f'] :
    trend === 'down'                      ? ['Bearish Trend',         '#ff476f'] :
                                            ['Range-Bound',           '#f5b342']

  // ── Momentum group ───────────────────────────────────────────────────────────
  const [momState, momColor] =
    rsi >= 80 && (macd === 'bullish' || macd === 'bullish_cross') ? ['Extremely Overheated',       '#ff476f'] :
    rsi >= 72                                                      ? ['Momentum Overextended',      '#ff6a6a'] :
    macd === 'bullish_cross'                                       ? ['Momentum Turning Bullish',   '#3ddc97'] :
    macd === 'bullish' && rsi >= 55                                ? ['Momentum Accelerating',      '#3ddc97'] :
    macd === 'bullish'                                             ? ['Momentum Bullish',           '#5ee8a9'] :
    rsi <= 20 && (macd === 'bearish' || macd === 'bearish_cross')  ? ['Deeply Oversold',            '#3ddc97'] :
    rsi <= 30                                                      ? ['Oversold — Watch for Turn',  '#f5b342'] :
    macd === 'bearish_cross'                                       ? ['Momentum Turning Bearish',   '#ff476f'] :
    macd === 'bearish'                                             ? ['Momentum Bearish',           '#ff6a6a'] :
                                                                     ['Momentum Neutral',           '#8899aa']

  // ── Risk group ───────────────────────────────────────────────────────────────
  const [riskState, riskColor] =
    atrPct > 5                                  ? ['Risk Elevated — High Volatility',   '#ff476f'] :
    bb === 'squeeze'                             ? ['Coiled — Breakout Risk Imminent',   '#f5b342'] :
    bb === 'overbought' || bb === 'oversold'     ? ['Price at Statistical Extreme',      '#f5b342'] :
    vol === 'low'                                ? ['Low Conviction — Thin Volume',      '#f5b342'] :
    atrPct > 3                                   ? ['Risk Moderate',                     '#f5b342'] :
                                                   ['Normal Conditions',                 '#3ddc97']

  // ── Entry Quality group ──────────────────────────────────────────────────────
  const [entryState, entryColor] =
    dec.action === 'BUY'  && vwap === 'above' && (bb === 'oversold' || bb === 'lower_half') ? ['Excellent Entry Zone', '#3ddc97'] :
    dec.action === 'BUY'  && vwap === 'above'                                               ? ['Good Entry Zone',      '#3ddc97'] :
    dec.action === 'BUY'                                                                     ? ['Acceptable Entry',     '#5ee8a9'] :
    dec.action === 'SELL' && vwap === 'below'                                               ? ['Sell Setup Active',    '#ff476f'] :
    dec.action === 'SELL'                                                                    ? ['Bearish Setup',        '#ff6a6a'] :
    trend === 'up' && vwap === 'below'                                                       ? ['Wait — Reclaim VWAP', '#f5b342'] :
    rsi >= 70 || stochK >= 80                                                                ? ['Avoid Chasing',        '#f5b342'] :
    trend === 'up'                                                                            ? ['Hold Winners',         '#f5b342'] :
    trend === 'sideways'                                                                      ? ['Range-Trade Only',     '#8899aa'] :
                                                                                               ['Wait for Setup',       '#8899aa']

  // ── Current Bias ─────────────────────────────────────────────────────────────
  const [biasLabel, biasColor, biasBg] =
    dec.score >= 5   ? ['Strong Buy Signal',   '#3ddc97', 'rgba(61,220,151,0.10)']  :
    dec.score >= 2   ? ['Bullish Bias',         '#3ddc97', 'rgba(61,220,151,0.07)']  :
    dec.score >= 0.5 ? ['Mild Bullish Lean',    '#5ee8a9', 'rgba(61,220,151,0.04)']  :
    dec.score <= -5  ? ['Strong Sell Signal',   '#ff476f', 'rgba(255,71,111,0.10)']  :
    dec.score <= -2  ? ['Bearish Bias',         '#ff476f', 'rgba(255,71,111,0.07)']  :
    dec.score <= -0.5? ['Mild Bearish Lean',    '#ff6a6a', 'rgba(255,71,111,0.04)']  :
                       ['No Clear Bias',         '#f5b342', 'rgba(245,179,66,0.05)']

  // ── Plain-language explanation ────────────────────────────────────────────────
  const parts = []
  if      (macd === 'bullish_cross') parts.push('MACD just flipped bullish — this is a fresh momentum shift with high conviction.')
  else if (macd === 'bearish_cross') parts.push('MACD just flipped bearish — momentum has turned and selling pressure is building.')
  else if (macd === 'bullish')       parts.push('Momentum remains in sustained bullish mode above the signal line.')
  else if (macd === 'bearish')       parts.push('Momentum is in sustained bearish control below the signal line.')

  if      (rsi >= 75) parts.push(`RSI at ${rsi.toFixed(0)} is extremely overextended — new longs carry high mean-reversion risk.`)
  else if (rsi <= 25) parts.push(`RSI at ${rsi.toFixed(0)} is deeply oversold — exhaustion selling may be approaching its end.`)

  if      (vol === 'high_up')   parts.push('Above-average volume on an up day confirms institutional accumulation is real.')
  else if (vol === 'high_down') parts.push('Above-average volume on a down day signals active institutional distribution.')
  else if (vol === 'low')       parts.push('Volume is thin — any signal today carries reduced weight until volume picks up.')

  if (atrPct > 4) parts.push(`High ATR (${atrPct.toFixed(1)}%) means wider swings — size down and use 2× ATR for stops.`)
  if (bb === 'squeeze') parts.push('Bollinger Bands are squeezing — an explosive directional move is loading.')
  const explanation = parts.slice(0, 3).join(' ') || 'Multiple indicators are neutral — no dominant catalyst today.'

  // ── If-Then Scenarios ─────────────────────────────────────────────────────────
  const scenarios = []
  if (trend === 'up') {
    if (vwap === 'above') {
      scenarios.push(`If price holds above VWAP and RSI cools, continuation toward $${res.toFixed(2)} (resistance) is probable.`)
    } else {
      scenarios.push(`If price reclaims VWAP ($${vwapV.toFixed(2)}) on strong volume, the uptrend resumes.`)
    }
    scenarios.push(`If price breaks below support ($${sup.toFixed(2)}) with rising sell volume, a deeper pullback begins.`)
  } else if (trend === 'down') {
    if (vwap === 'below') {
      scenarios.push(`If price cannot reclaim VWAP ($${vwapV.toFixed(2)}), downside continuation toward $${sup.toFixed(2)} is likely.`)
    } else {
      scenarios.push(`If price breaks below VWAP ($${vwapV.toFixed(2)}) with volume, the downtrend re-accelerates.`)
    }
    scenarios.push(`If MACD shows bullish divergence while RSI stabilizes above ${Math.max(20, rsi - 5).toFixed(0)}, watch for a reversal.`)
  } else {
    scenarios.push(`If price breaks above resistance ($${res.toFixed(2)}) with expanding volume, a new uptrend begins.`)
    scenarios.push(`If price falls below support ($${sup.toFixed(2)}), range breaks down and sellers take control.`)
  }

  const groups = [
    { label: 'Trend',         state: trendState,  color: trendColor  },
    { label: 'Momentum',      state: momState,    color: momColor    },
    { label: 'Risk',          state: riskState,   color: riskColor   },
    { label: 'Entry Quality', state: entryState,  color: entryColor  },
  ]

  return (
    <div className="ap-card" style={{ background: biasBg, border: `1px solid ${biasColor}28`, marginBottom: 2 }}>
      {/* Bias headline */}
      <div style={{ textAlign: 'center', paddingBottom: 10, borderBottom: '1px solid rgba(140,170,220,0.08)', marginBottom: 10 }}>
        <div style={{ fontSize: 8, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'var(--t-4)', marginBottom: 4 }}>Current Bias</div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 15, fontWeight: 900, color: biasColor, letterSpacing: '0.03em' }}>
          {biasLabel}
        </div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--t-4)', marginTop: 3 }}>
          score {dec.score > 0 ? '+' : ''}{dec.score} · confidence {dec.confidence}%
        </div>
      </div>

      {/* 4 group tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 5, marginBottom: 10 }}>
        {groups.map(g => (
          <div key={g.label} style={{ background: 'rgba(5,8,15,0.5)', border: `1px solid ${g.color}1a`, borderRadius: 5, padding: '6px 8px' }}>
            <div style={{ fontSize: 8, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--t-4)', marginBottom: 3 }}>{g.label}</div>
            <div style={{ fontSize: 10, fontWeight: 700, color: g.color, lineHeight: 1.3 }}>{g.state}</div>
          </div>
        ))}
      </div>

      {/* Why explanation */}
      <div style={{ fontSize: 10.5, color: 'var(--t-2)', lineHeight: 1.7, padding: '7px 9px', background: 'rgba(140,170,220,0.03)', borderLeft: `2px solid ${biasColor}44`, borderRadius: '0 4px 4px 0', marginBottom: 10 }}>
        {explanation}
      </div>

      {/* Scenarios */}
      <div>
        <div style={{ fontSize: 8, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--t-4)', marginBottom: 6 }}>If-Then Scenarios</div>
        {scenarios.map((s, i) => (
          <div key={i} style={{ display: 'flex', gap: 6, padding: '3px 0', fontSize: 10, color: 'var(--t-3)', lineHeight: 1.55 }}>
            <span style={{ color: biasColor, flexShrink: 0, fontWeight: 700 }}>›</span>
            <span>{s}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Page section header with color ────────────────────────────────────────────

function PageHd({ label, color }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 9, letterSpacing: '0.12em', textTransform: 'uppercase', color, fontFamily: 'var(--font-mono)', fontWeight: 700, marginBottom: 8, paddingBottom: 5, borderBottom: `1px solid ${color}30` }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: color, flexShrink: 0, boxShadow: `0 0 5px ${color}` }} />
      {label}
    </div>
  )
}

// ── Paginated content — nav + page body, no outer card wrapper ───────────────

function PaginatedContent({ dot, pages }) {
  const [page, setPage] = useState(0)
  const n = pages.length
  const prev = () => setPage(p => (p - 1 + n) % n)
  const next = () => setPage(p => (p + 1) % n)
  return (
    <>
      {n > 1 && (
        <div className="ap-pnav" style={{ justifyContent: 'center', marginBottom: 2 }}>
          <button className="ap-pnav-btn" onClick={prev}>‹</button>
          <span className="ap-pnav-label">{pages[page].name}</span>
          <button className="ap-pnav-btn" onClick={next}>›</button>
        </div>
      )}
      {n > 1 && (
        <div className="ap-pdots">
          {pages.map((_, i) => (
            <div key={i} className={`ap-pdot${i === page ? ' on' : ''}`}
              onClick={() => setPage(i)}
              style={i === page ? { background: dot } : undefined} />
          ))}
        </div>
      )}
      <div className="ap-page-body">
        {pages[page]?.content}
      </div>
    </>
  )
}

// ── Tabbed indicator card — two tabs each with their own paginated content ────

function TabbedIndicatorCard({ momentumPages, contextPages }) {
  const [activeTab, setActiveTab] = useState('momentum')
  const tabs = [
    { key: 'momentum', label: 'Momentum Signals', dot: '#4ad9ff', pages: momentumPages },
    { key: 'context',  label: 'Market Context',   dot: '#3ddc97', pages: contextPages  },
  ]
  const active = tabs.find(t => t.key === activeTab)

  return (
    <div className="ap-card ap-paged-card">
      {/* Tab switcher */}
      <div style={{ display: 'flex', marginBottom: 12, marginLeft: -12, marginRight: -12, marginTop: -8, borderBottom: '1px solid rgba(140,170,220,0.10)' }}>
        {tabs.map(t => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            style={{
              flex: 1, padding: '7px 4px 8px', border: 'none', cursor: 'pointer',
              background: activeTab === t.key ? `${t.dot}0d` : 'transparent',
              color: activeTab === t.key ? t.dot : '#475061',
              fontSize: '9px', fontWeight: activeTab === t.key ? 700 : 400,
              letterSpacing: '0.08em', textTransform: 'uppercase',
              borderBottom: activeTab === t.key ? `2px solid ${t.dot}` : '2px solid transparent',
              fontFamily: 'var(--font-mono)', transition: 'color 0.15s',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      <PaginatedContent key={activeTab} dot={active.dot} pages={active.pages} />
    </div>
  )
}

// ── Paginated Card — standalone card (kept for backward compat) ───────────────

function PaginatedCard({ title, dot, pages }) {
  return (
    <div className="ap-card ap-paged-card">
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 7, fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--t-2)', marginBottom: 8 }}>
        <div className="ap-dot" style={{ background: dot }} />
        <span>{title}</span>
      </div>
      <PaginatedContent dot={dot} pages={pages} />
    </div>
  )
}

// ── Trade Setup Guide ─────────────────────────────────────────────────────────

const GUIDE_STATUS = {
  met:     { char: '✓', color: '#3ddc97' },
  partial: { char: '◑', color: '#f5b342' },
  watch:   { char: '◔', color: '#f5b342' },
  missing: { char: '○', color: 'rgba(140,170,220,0.22)' },
}

function TradeGuide({ data, price }) {
  const [side, setSide] = useState('buy')

  if (!data || !price) return null

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

  const buyItems = [
    {
      name: 'RSI',
      status: rsi <= 20 ? 'met' : rsi <= 28 ? 'met' : rsi <= 38 ? 'partial' : 'missing',
      pts:   rsi <= 20 ? '+3.0' : rsi <= 28 ? '+2.0' : rsi <= 38 ? '+1.0' : null,
      text:  rsi <= 20 ? `${rsi.toFixed(1)} — extreme oversold, top buy signal`
           : rsi <= 28 ? `${rsi.toFixed(1)} — oversold zone, buyers step in here`
           : rsi <= 38 ? `${rsi.toFixed(1)} — mild oversold, momentum fading`
           : `${rsi.toFixed(1)} — neutral${rsi >= 62 ? '/overbought' : ''}; needs to fall below 38`,
    },
    {
      name: 'MACD',
      status: macd === 'bullish_cross' ? 'met' : macd === 'bullish' ? 'partial' : 'missing',
      pts:   macd === 'bullish_cross' ? '+3.0' : macd === 'bullish' ? '+1.5' : null,
      text:  macd === 'bullish_cross' ? `Fresh bullish crossover — strongest momentum signal`
           : macd === 'bullish'       ? `Above signal line — sustained bullish momentum`
           : macd === 'bearish_cross' ? `Just bearish-crossed — watch for reversal cross above`
           : `Below signal line — needs bullish crossover for full signal`,
    },
    {
      name: 'Stochastic',
      status: stochK <= 15 ? 'met' : stochK <= 25 ? 'partial' : 'missing',
      pts:   stochK <= 15 ? '+1.5' : stochK <= 25 ? '+1.0' : null,
      text:  stochK <= 15 ? `%K ${stochK.toFixed(1)} — deep oversold, snap-back likely`
           : stochK <= 25 ? `%K ${stochK.toFixed(1)} — oversold; confirm with %K cross above %D ${stochD.toFixed(1)}`
           : `%K at ${stochK.toFixed(1)} — needs to drop below 25`,
    },
    {
      name: 'Volume',
      status: vol === 'high_up' ? 'met' : vol === 'low' ? 'watch' : 'missing',
      pts:   vol === 'high_up' ? '+2.0' : null,
      text:  vol === 'high_up'   ? `${volR.toFixed(2)}× avg on up day — institutional accumulation`
           : vol === 'low'       ? `${volR.toFixed(2)}× avg — too thin; signals at 65% weight`
           : `Normal volume — needs > 1.5× avg on a green candle for +2 pts`,
    },
    {
      name: 'Bollinger Bands',
      status: bb === 'oversold' ? 'met' : bb === 'lower_half' ? 'partial' : bb === 'squeeze' ? 'watch' : 'missing',
      pts:   bb === 'oversold' ? '+1.5' : bb === 'lower_half' ? '+0.5' : null,
      text:  bb === 'oversold'   ? `Below lower band — mean reversion to midline expected`
           : bb === 'lower_half' ? `Lower half of bands — mild bullish lean`
           : bb === 'squeeze'    ? `Bands squeezing — big move imminent, direction TBD`
           : `Upper bands/overbought — needs pullback toward lower band region`,
    },
    {
      name: 'VWAP',
      status: vwap === 'above' ? 'met' : 'missing',
      pts:   vwap === 'above' ? '+1.0' : null,
      text:  vwap === 'above' ? `Price above VWAP — institutional algorithms net long`
           : `Price below VWAP — needs to reclaim VWAP for institutional support`,
    },
    {
      name: 'Trend',
      status: trend === 'up' ? 'met' : trend === 'sideways' ? 'watch' : 'missing',
      pts:   trend === 'up' ? '+1.5' : null,
      text:  trend === 'up'       ? `Uptrend confirmed — regression slope positive`
           : trend === 'sideways' ? `Sideways — breakout above resistance needed for uptrend`
           : `Downtrend in effect — needs price structure reversal first`,
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
           : `${rsi.toFixed(1)} — neutral${rsi <= 38 ? '/oversold' : ''}; needs to rise above 62`,
    },
    {
      name: 'MACD',
      status: macd === 'bearish_cross' ? 'met' : macd === 'bearish' ? 'partial' : 'missing',
      pts:   macd === 'bearish_cross' ? '+3.0' : macd === 'bearish' ? '+1.5' : null,
      text:  macd === 'bearish_cross' ? `Fresh bearish crossover — strongest sell momentum signal`
           : macd === 'bearish'       ? `Below signal line — bears control momentum`
           : macd === 'bullish_cross' ? `Just bullish-crossed — watch for failure and reversal cross`
           : `Above signal line — needs bearish crossover for full signal`,
    },
    {
      name: 'Stochastic',
      status: stochK >= 85 ? 'met' : stochK >= 75 ? 'partial' : 'missing',
      pts:   stochK >= 85 ? '+1.5' : stochK >= 75 ? '+1.0' : null,
      text:  stochK >= 85 ? `%K ${stochK.toFixed(1)} — deep overbought, exhaustion zone`
           : stochK >= 75 ? `%K ${stochK.toFixed(1)} — overbought; confirm with %K cross below %D ${stochD.toFixed(1)}`
           : `%K at ${stochK.toFixed(1)} — needs to rise above 75`,
    },
    {
      name: 'Volume',
      status: vol === 'high_down' ? 'met' : vol === 'low' ? 'watch' : 'missing',
      pts:   vol === 'high_down' ? '+2.0' : null,
      text:  vol === 'high_down' ? `${volR.toFixed(2)}× avg on down day — institutional distribution`
           : vol === 'low'       ? `${volR.toFixed(2)}× avg — too thin; signals at 65% weight`
           : `Normal volume — needs > 1.5× avg on a red candle for +2 pts`,
    },
    {
      name: 'Bollinger Bands',
      status: bb === 'overbought' ? 'met' : bb === 'upper_half' ? 'partial' : bb === 'squeeze' ? 'watch' : 'missing',
      pts:   bb === 'overbought' ? '+1.5' : bb === 'upper_half' ? '+0.5' : null,
      text:  bb === 'overbought' ? `Above upper band — statistically extreme, expect reversion`
           : bb === 'upper_half' ? `Upper half of bands — mild bearish lean`
           : bb === 'squeeze'    ? `Bands squeezing — big move imminent, direction TBD`
           : `Lower bands/oversold — needs push to upper band region`,
    },
    {
      name: 'VWAP',
      status: vwap === 'below' ? 'met' : 'missing',
      pts:   vwap === 'below' ? '+1.0' : null,
      text:  vwap === 'below' ? `Price below VWAP — institutional algorithms net short`
           : `Price above VWAP — needs to break below VWAP for resistance context`,
    },
    {
      name: 'Trend',
      status: trend === 'down' ? 'met' : trend === 'sideways' ? 'watch' : 'missing',
      pts:   trend === 'down' ? '+1.5' : null,
      text:  trend === 'down'     ? `Downtrend confirmed — regression slope negative`
           : trend === 'sideways' ? `Sideways — break below support needed for downtrend`
           : `Uptrend in effect — needs lower-highs/lower-lows price structure first`,
    },
  ]

  const activeItems = side === 'buy' ? buyItems : sellItems
  const metCount    = activeItems.filter(i => i.status === 'met' || i.status === 'partial').length
  const acColor     = action === 'BUY' ? '#3ddc97' : action === 'SELL' ? '#ff476f' : '#f5b342'
  const buyGap      = Math.max(0, 2.0 - score).toFixed(1)
  const sellGap     = Math.max(0, score + 2.0).toFixed(1)

  return (
    <div className="ap-card">
      <div className="ap-card-hd">
        <div className="ap-dot" style={{ background: '#b39dff' }} />
        Setup Guide
      </div>

      {/* Score + toggle */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, paddingBottom: 8, borderBottom: '1px solid var(--hairline)' }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 9, color: 'var(--t-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 2 }}>Current Signal</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 700, color: acColor }}>
            {action} &nbsp;<span style={{ opacity: 0.7, fontSize: 10 }}>(score {score > 0 ? '+' : ''}{score})</span>
          </div>
          {action === 'HOLD' && (
            <div style={{ fontSize: 9, color: 'var(--t-4)', marginTop: 2 }}>
              {side === 'buy'
                ? `+${buyGap} pts needed for BUY signal`
                : `${sellGap} pts to shed for SELL signal`}
            </div>
          )}
        </div>
        <div style={{ display: 'flex', background: 'var(--bg-card-hi)', border: '1px solid var(--hairline-2)', borderRadius: 5, overflow: 'hidden', flexShrink: 0 }}>
          {['buy', 'sell'].map(s => (
            <button key={s} onClick={() => setSide(s)} style={{
              background: side === s ? (s === 'buy' ? 'rgba(61,220,151,0.16)' : 'rgba(255,71,111,0.16)') : 'transparent',
              border: 'none',
              color:  side === s ? (s === 'buy' ? '#3ddc97' : '#ff476f') : 'var(--t-3)',
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

      {/* High-vol warning */}
      {atrPct > 3 && (
        <div style={{ marginTop: 8, padding: '5px 8px', background: 'rgba(255,71,111,0.06)', border: '1px solid rgba(255,71,111,0.15)', borderRadius: 4, fontSize: 10, color: '#ff6a6a', lineHeight: 1.4 }}>
          ⚠ ATR {atrPct.toFixed(1)}% — high volatility; reduce size, widen stops
        </div>
      )}
    </div>
  )
}

// ── Analysis Tab ───────────────────────────────────────────────────────────────

const ASSET_COLORS = {
  crypto:  { text: '#4ad9ff', bg: 'rgba(74,217,255,0.12)' },
  forex:   { text: '#a78bfa', bg: 'rgba(167,139,250,0.12)' },
  futures: { text: '#fb923c', bg: 'rgba(251,146,60,0.12)'  },
  equity:  { text: '#f59e0b', bg: 'rgba(245,158,11,0.12)'  },
}

function ContextBar({ brief, price, portReg }) {
  const [guideOpen, setGuideOpen] = useState(false)
  if (!brief) return null
  const ac    = brief.asset_class || 'equity'
  const acCol = ASSET_COLORS[ac] || ASSET_COLORS.equity
  const is247 = ac === 'crypto' || ac === 'forex'
  const atr   = brief.atr || 0
  const guide = brief.setup_guide || {}

  return (
    <div style={{ margin: '0 0 6px', padding: '10px 12px', background: 'rgba(0,0,0,0.25)', borderRadius: 6, border: '1px solid rgba(140,170,220,0.07)' }}>
      {/* Row 1: asset class + session badge + stop levels */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.09em', textTransform: 'uppercase', color: acCol.text, background: acCol.bg, padding: '2px 7px', borderRadius: 4 }}>
          {ac}
        </span>
        <span style={{ fontSize: 9, color: is247 ? '#4ade80' : '#f59e0b', background: is247 ? 'rgba(74,222,128,0.1)' : 'rgba(245,158,11,0.1)', border: `1px solid ${is247 ? 'rgba(74,222,128,0.2)' : 'rgba(245,158,11,0.2)'}`, borderRadius: 3, padding: '1px 5px' }}>
          {is247 ? '24/7' : 'Market Hours'}
        </span>
        {atr > 0 && price > 0 && (
          <span style={{ fontSize: 9, color: 'var(--t-4)', fontFamily: 'var(--font-mono)', marginLeft: 'auto' }}>
            ATR {brief.atr_pct?.toFixed(1)}%
          </span>
        )}
      </div>

      {/* Row 2: projected range + stops */}
      {brief.proj_high && brief.proj_low && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 4, marginBottom: 8 }}>
          {[
            { label: '↑ Proj High', val: `$${Number(brief.proj_high).toFixed(2)}`, color: 'var(--ok)' },
            { label: '↓ Proj Low',  val: `$${Number(brief.proj_low).toFixed(2)}`,  color: 'var(--err)' },
            { label: 'Long Stop',   val: `$${Number(brief.long_stop).toFixed(2)}`,  color: '#ff6a6a' },
            { label: 'Short Stop',  val: `$${Number(brief.short_stop).toFixed(2)}`, color: '#4ade80' },
          ].map(({ label, val, color }) => (
            <div key={label} style={{ background: 'rgba(140,170,220,0.04)', borderRadius: 4, padding: '5px 7px', textAlign: 'center' }}>
              <div style={{ fontSize: 8, color: 'var(--t-4)', marginBottom: 2, letterSpacing: '0.04em' }}>{label}</div>
              <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', fontWeight: 700, color }}>{val}</div>
            </div>
          ))}
        </div>
      )}

      {/* Row 3: S/R from structure engine if available */}
      {(brief.nearest_support || brief.nearest_resistance) && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
          {brief.nearest_support && (
            <div style={{ flex: 1, fontSize: 9, color: 'var(--t-3)' }}>
              <span style={{ color: 'var(--ok)', fontWeight: 700 }}>S </span>
              <span style={{ fontFamily: 'var(--font-mono)' }}>${Number(brief.nearest_support).toFixed(2)}</span>
            </div>
          )}
          {brief.nearest_resistance && (
            <div style={{ flex: 1, fontSize: 9, color: 'var(--t-3)' }}>
              <span style={{ color: 'var(--err)', fontWeight: 700 }}>R </span>
              <span style={{ fontFamily: 'var(--font-mono)' }}>${Number(brief.nearest_resistance).toFixed(2)}</span>
            </div>
          )}
          {brief.swing_bias && brief.swing_bias !== 'undefined' && (
            <span style={{ fontSize: 9, color: brief.swing_bias === 'bullish' ? 'var(--ok)' : 'var(--err)', fontWeight: 600 }}>
              {brief.swing_bias} structure
            </span>
          )}
        </div>
      )}

      {/* Row 4: session guide toggle */}
      {guide.title && (
        <>
          <button
            onClick={() => setGuideOpen(o => !o)}
            style={{ width: '100%', background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '3px 0', color: 'var(--t-3)', fontSize: 9, letterSpacing: '0.06em', textTransform: 'uppercase' }}
          >
            <span>{guide.title}</span>
            <span style={{ fontSize: 10 }}>{guideOpen ? '▲' : '▼'}</span>
          </button>
          {guideOpen && (
            <div style={{ marginTop: 6, paddingTop: 6, borderTop: '1px solid rgba(140,170,220,0.07)' }}>
              {(guide.tips || []).map((tip, i) => (
                <div key={i} style={{ display: 'flex', gap: 6, fontSize: 9.5, color: 'var(--t-3)', lineHeight: 1.55, marginBottom: 4 }}>
                  <span style={{ color: acCol.text, flexShrink: 0 }}>›</span>
                  <span>{tip}</span>
                </div>
              ))}
              {guide.best_sessions && (
                <div style={{ fontSize: 9, color: 'var(--ok)', marginTop: 4 }}>
                  <span style={{ color: 'var(--t-4)' }}>Best: </span>{guide.best_sessions}
                </div>
              )}
              {guide.avoid && (
                <div style={{ fontSize: 9, color: 'var(--err)', marginTop: 2 }}>
                  <span style={{ color: 'var(--t-4)' }}>Avoid: </span>{guide.avoid}
                </div>
              )}
            </div>
          )}
        </>
      )}
      {portReg && portReg.regime !== 'normal' && (
        <div style={{
          marginTop: 6, padding: '4px 8px',
          background: portReg.regime === 'favorable' ? 'rgba(74,222,128,0.07)' : 'rgba(255,106,106,0.07)',
          borderRadius: 4,
          border: `1px solid ${portReg.regime === 'favorable' ? 'rgba(74,222,128,0.2)' : 'rgba(255,106,106,0.2)'}`,
          fontSize: 9, color: portReg.regime === 'favorable' ? '#4ade80' : '#fb923c',
        }}>
          Portfolio: {portReg.reason}
        </div>
      )}
    </div>
  )
}

function AnalysisTab({ data, price, symbol, brief, portReg }) {
  if (!data) return <div className="ap-placeholder">Loading indicators…</div>

  const macdDiff   = (data.macd_value ?? 0) - (data.macd_signal_value ?? 0)
  const macdColor  = macdDiff >= 0 ? '#3ddc97' : '#ff476f'
  const trendColor = data.trend === 'up' ? '#3ddc97' : data.trend === 'down' ? '#ff476f' : '#f5b342'
  const trendLabel = data.trend === 'up' ? '▲ UPTREND' : data.trend === 'down' ? '▼ DOWNTREND' : '→ SIDEWAYS'

  // MTF helpers
  const mtf = data.mtf
  const mtfArrow = (d) => d?.trend === 'up' ? '↗' : d?.trend === 'down' ? '↘' : '→'
  const mtfColor = (d) => d?.trend === 'up' ? '#3ddc97' : d?.trend === 'down' ? '#ff476f' : '#f5b342'
  const mtfMacdColor = (d) => (d?.macd ?? '').startsWith('bullish') ? '#3ddc97' : (d?.macd ?? '').startsWith('bearish') ? '#ff476f' : '#475061'
  const mtfBbColor   = (d) => {
    const b = d?.bb ?? ''
    return (b === 'oversold' || b === 'lower_half') ? '#3ddc97' : (b === 'overbought' || b === 'upper_half') ? '#ff476f' : '#475061'
  }
  const alignColor = mtf?.alignment === 'bullish' ? '#3ddc97' : mtf?.alignment === 'bearish' ? '#ff476f' : '#f5b342'
  const total   = (mtf?.bull_count ?? 0) + (mtf?.bear_count ?? 0)
  const bullPct = total > 0 ? ((mtf?.bull_count ?? 0) / total) * 100 : 50

  const momentumPages = [
    {
      name: 'Trend',
      content: (
        <>
          <PageHd label="Trend Direction" color={trendColor} />
          <div style={{ textAlign: 'center', padding: '10px 0 6px' }}>
            <span style={{ fontSize: 22, fontWeight: 900, fontFamily: 'var(--font-mono)', color: trendColor, letterSpacing: '0.06em' }}>{trendLabel}</span>
          </div>
          <Row label="DIRECTION"  value={data.trend ?? '—'} color={trendColor} />
          <Row label="ATR"        value={`$${f(data.atr)}`} color="var(--t-2)" />
          <Row label="SUPPORT"    value={data.support    != null ? `$${f(data.support)}`    : '—'} color="#3ddc97" />
          <Row label="RESISTANCE" value={data.resistance != null ? `$${f(data.resistance)}` : '—'} color="#ff476f" />
          <Interp>
            {data.trend === 'up'   && `Linear regression slope is positive — price is making higher highs and higher lows. Buy dips toward support ($${f(data.support)}). Resistance at $${f(data.resistance)} is the next target.`}
            {data.trend === 'down' && `Regression slope is negative — price is making lower highs and lower lows. Sell rallies toward resistance ($${f(data.resistance)}). Support at $${f(data.support)} is the next target.`}
            {data.trend !== 'up' && data.trend !== 'down' && `Price is moving sideways. Range-trade between support ($${f(data.support)}) and resistance ($${f(data.resistance)}). Wait for a breakout before taking a directional trade.`}
          </Interp>
        </>
      ),
    },
    {
      name: 'RSI (14)',
      content: (
        <>
          <PageHd label="RSI · Relative Strength Index" color="#f5b342" />
          <Row label="VALUE" value={f(data.rsi, 1)}
            color={data.rsi >= 70 ? '#ff476f' : data.rsi <= 30 ? '#3ddc97' : 'var(--t-2)'}
            badge={data.rsi_signal} />
          <MiniMeter value={data.rsi} lo={30} hi={70} />
          <MeterLabels lo={30} hi={70} />
          <Interp>{rsiInterp(data.rsi)}</Interp>
        </>
      ),
    },
    {
      name: 'MACD (12,26,9)',
      content: (
        <>
          <PageHd label="MACD · Momentum Divergence" color="#4ad9ff" />
          <Row label="MACD LINE"   value={`${data.macd_value >= 0 ? '+' : ''}${f(data.macd_value, 4)}`} color={macdColor} />
          <Row label="SIGNAL LINE" value={f(data.macd_signal_value, 4)} color="var(--t-2)" />
          <Row label="HISTOGRAM"   value={`${macdDiff >= 0 ? '+' : ''}${f(macdDiff, 4)}`} color={macdColor} badge={data.macd_cross} />
          <Interp>{macdInterp(data.macd_cross, data.macd_value, data.macd_signal_value)}</Interp>
        </>
      ),
    },
    {
      name: 'Stochastic (14,3)',
      content: (
        <>
          <PageHd label="Stochastic Oscillator" color="#ff6a1a" />
          <Row label="%K FAST" value={f(data.stoch_k_val, 1)}
            color={data.stoch_k_val >= 80 ? '#ff476f' : data.stoch_k_val <= 20 ? '#3ddc97' : 'var(--t-2)'}
            badge={data.stoch_signal} />
          <Row label="%D SLOW" value={f(data.stoch_d_val, 1)} color="var(--t-3)" />
          <MiniMeter value={data.stoch_k_val} lo={20} hi={80} />
          <MeterLabels lo={20} hi={80} />
          <Interp>{stochInterp(data.stoch_k_val, data.stoch_d_val)}</Interp>
        </>
      ),
    },
  ]

  const contextPages = [
    {
      name: 'Volume',
      content: (
        <>
          <PageHd label="Volume Analysis" color="#3ddc97" />
          <Row label="LAST"    value={fmtVol(data.last_volume)} color="var(--t-2)" />
          <Row label="20D AVG" value={fmtVol(data.avg_volume)}  color="var(--t-3)" />
          <Row label="RATIO"   value={`${f(data.volume_ratio, 2)}×`}
            color={SIG_COLOR[data.volume_signal]} badge={data.volume_signal} />
          <Interp>{volumeInterp(data.volume_signal, data.volume_ratio)}</Interp>
        </>
      ),
    },
    {
      name: 'Bollinger Bands',
      content: (
        <>
          <PageHd label="Bollinger Bands (20, 2σ)" color="#f5b342" />
          <Row label="UPPER" value={`$${f(data.bb_upper_val)}`} color="#f5b342" />
          <Row label="MID"   value={`$${f(((data.bb_upper_val ?? 0) + (data.bb_lower_val ?? 0)) / 2)}`} color="var(--t-3)" />
          <Row label="LOWER" value={`$${f(data.bb_lower_val)}`} color="#f5b342" />
          <Row label="POSITION" value={String(data.bb_position ?? '').replace(/_/g, ' ')}
            color={SIG_COLOR[data.bb_position] ?? 'var(--t-2)'} badge={data.bb_position} />
          <Interp>{bbInterp(data.bb_position, data.bb_upper_val, data.bb_lower_val)}</Interp>
        </>
      ),
    },
    {
      name: 'ATR · Volatility',
      content: (
        <>
          <PageHd label="ATR (14) · Average True Range" color="#ff476f" />
          <Row label="ATR VALUE"   value={`$${f(data.atr)}`}               color="var(--t-2)" />
          <Row label="ATR %"       value={`${f(data.atr_pct)}%`}           color={data.atr_pct > 3 ? '#f5b342' : 'var(--t-2)'} />
          <Row label="1.5× STOP"   value={`$${f((data.atr ?? 0) * 1.5)}`} color="#ff476f" />
          <Row label="2.5× TARGET" value={`$${f((data.atr ?? 0) * 2.5)}`} color="#3ddc97" />
          <Interp>{atrInterp(data.atr, data.atr_pct)}</Interp>
        </>
      ),
    },
    {
      name: 'VWAP',
      content: (
        <>
          <PageHd label="VWAP · Volume-Weighted Avg Price" color="#ff6a1a" />
          <Row label="VWAP"   value={`$${f(data.vwap_value)}`} color="var(--acc)" />
          <Row label="SIGNAL" value={data.vwap_signal === 'above' ? 'Above VWAP' : 'Below VWAP'}
            color={data.vwap_signal === 'above' ? '#3ddc97' : '#ff476f'} badge={data.vwap_signal} />
          <Interp>{vwapInterp(data.vwap_signal, data.vwap_value, null)}</Interp>
        </>
      ),
    },
    ...(mtf ? [{
      name: 'Multi-Timeframe',
      content: (
        <>
          <PageHd label="Multi-Timeframe Alignment" color={alignColor} />

          {/* 3-column timeframe grid */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 0, border: '1px solid rgba(140,170,220,0.08)', borderRadius: 6, overflow: 'hidden', marginBottom: 10 }}>
            {[['1H', mtf['1H']], ['1D', mtf['1D']], ['1W', mtf['1W']]].map(([tf, d], i) => (
              <div key={tf} style={{
                padding: '10px 4px 8px',
                textAlign: 'center',
                borderRight: i < 2 ? '1px solid rgba(140,170,220,0.08)' : 'none',
                background: 'rgba(0,0,0,0.2)',
              }}>
                <div style={{ fontSize: 9, color: '#475061', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 5 }}>{tf}</div>
                <div style={{ fontSize: 26, color: mtfColor(d), lineHeight: 1 }}>{mtfArrow(d)}</div>
                {d?.rsi != null && (
                  <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: d.rsi <= 30 ? '#3ddc97' : d.rsi >= 70 ? '#ff476f' : '#6b7689', marginTop: 5 }}>
                    RSI {d.rsi.toFixed(0)}
                  </div>
                )}
                <div style={{ display: 'flex', justifyContent: 'center', gap: 4, marginTop: 6 }}>
                  <span title={`MACD: ${d?.macd ?? '—'}`} style={{ width: 6, height: 6, borderRadius: '50%', background: mtfMacdColor(d), display: 'inline-block' }} />
                  <span title={`BB: ${d?.bb ?? '—'}`}     style={{ width: 6, height: 6, borderRadius: '50%', background: mtfBbColor(d),   display: 'inline-block' }} />
                </div>
                <div style={{ fontSize: 8, color: '#333d4d', marginTop: 4 }}>MACD · BB</div>
              </div>
            ))}
          </div>

          {/* Alignment badge + consensus bar */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
            <span style={{ fontSize: 9, color: '#475061', textTransform: 'uppercase', letterSpacing: '0.07em' }}>Consensus</span>
            <span style={{
              padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 700,
              background: `${alignColor}18`, color: alignColor,
              border: `1px solid ${alignColor}44`, textTransform: 'capitalize',
            }}>
              {mtf.alignment ?? 'mixed'}
            </span>
          </div>
          <div style={{ marginBottom: 4 }}>
            <div style={{ height: 6, borderRadius: 3, overflow: 'hidden', background: 'rgba(255,71,111,0.2)', display: 'flex' }}>
              <div style={{ width: `${bullPct}%`, background: '#3ddc97', transition: 'width 0.4s', borderRadius: 3 }} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, color: '#475061', marginTop: 3 }}>
              <span style={{ color: '#3ddc97' }}>▲ {mtf.bull_count ?? 0} bullish</span>
              <span style={{ color: '#ff476f' }}>{mtf.bear_count ?? 0} bearish ▼</span>
            </div>
          </div>
        </>
      ),
    }] : []),
  ]

  return (
    <div className="ap-content">
      <ContextBar brief={brief} price={price} portReg={portReg} />
      <TabbedIndicatorCard momentumPages={momentumPages} contextPages={contextPages} />
      <div style={{ borderTop: '1px solid rgba(140,170,220,0.07)', marginTop: 2 }}>
        <AIThesisPanel data={data} price={price} symbol={symbol} />
      </div>
    </div>
  )
}

// ── AI Decision Tab ────────────────────────────────────────────────────────────

const ACTION_CFG = {
  BUY:  { grad: 'linear-gradient(140deg, rgba(61,220,151,0.16), rgba(61,220,151,0.04))', color: '#3ddc97', border: 'rgba(61,220,151,0.30)', glow: '0 0 28px rgba(61,220,151,0.22)' },
  SELL: { grad: 'linear-gradient(140deg, rgba(255,71,111,0.16), rgba(255,71,111,0.04))', color: '#ff476f', border: 'rgba(255,71,111,0.30)', glow: '0 0 28px rgba(255,71,111,0.22)' },
  HOLD: { grad: 'linear-gradient(140deg, rgba(245,179,66,0.14), rgba(245,179,66,0.03))',  color: '#f5b342', border: 'rgba(245,179,66,0.30)',  glow: '0 0 28px rgba(245,179,66,0.18)' },
}

function AIDecisionTab({ data, price }) {
  const dec = computeDecision(data, price)

  if (!data || !price)
    return <div className="ap-placeholder">Waiting for live price data…</div>
  if (!dec)
    return <div className="ap-placeholder">Insufficient data for analysis.</div>

  const cfg    = ACTION_CFG[dec.action]
  const rrNum  = parseFloat(dec.rr)
  const rrColor = rrNum >= 2 ? '#3ddc97' : rrNum >= 1.5 ? '#f5b342' : '#ff476f'
  const rrLabel = rrNum >= 2 ? 'Favorable' : rrNum >= 1.5 ? 'Acceptable' : 'Tight'

  return (
    <div className="ap-content">

      {/* Recommendation card */}
      <div className="ap-card ap-action-card" style={{ background: cfg.grad, border: `1px solid ${cfg.border}`, boxShadow: cfg.glow }}>
        <div className="ai-action-header">
          <div className="ai-action-label" style={{ color: cfg.color, textShadow: `0 0 40px ${cfg.color}88` }}>
            {dec.action}
          </div>
          <div className="ai-action-sub">AI RECOMMENDATION</div>
        </div>

        {/* Suggested Action */}
        {(() => {
          const topBull  = dec.bulls[0]?.t
          const topBear  = dec.bears[0]?.t
          const waitHint = topBull ? topBull.toLowerCase() : topBear ? `${topBear.toLowerCase()} to resolve` : 'a clearer signal'
          let sentence
          if (dec.action === 'BUY') {
            sentence = `Enter long near $${f(dec.price)} — stop at $${f(dec.stopLoss)}, target $${f(dec.target)}. Risk no more than 1–2% of your portfolio on this trade.`
          } else if (dec.action === 'SELL') {
            sentence = `Exit longs or go short near $${f(dec.price)} — stop at $${f(dec.stopLoss)}, target $${f(dec.target)}. Keep size conservative given current conditions.`
          } else {
            sentence = `No trade yet. Wait for ${waitHint} before committing capital. Stay flat or reduce size.`
          }
          return (
            <div style={{
              margin: '0 0 10px',
              padding: '9px 11px',
              background: 'rgba(0,0,0,0.25)',
              borderRadius: 6,
              borderLeft: `2px solid ${cfg.color}`,
              fontSize: 11,
              lineHeight: 1.55,
              color: 'var(--t-1)',
            }}>
              <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.09em', textTransform: 'uppercase', color: cfg.color, marginBottom: 4 }}>Suggested Action</div>
              {sentence}
            </div>
          )
        })()}

        <div className="ai-conf-block">
          <div className="ai-conf-row">
            <span className="ai-conf-lbl">CONFIDENCE</span>
            <span className="ai-conf-pct" style={{ color: cfg.color }}>{dec.confidence}%</span>
          </div>
          <div className="ai-conf-track">
            <div className="ai-conf-fill" style={{ width: `${dec.confidence}%`, background: cfg.color }} />
          </div>
          <div className="ai-score-row">
            <span>Score: <span style={{ color: cfg.color, fontWeight: 700 }}>{dec.score > 0 ? '+' : ''}{dec.score}</span></span>
            <span>{dec.bulls.length}↑ · {dec.bears.length}↓ signals</span>
          </div>
        </div>

        <div className="ai-grid">
          <div className="ai-cell">
            <div className="ai-cell-lbl">Entry Price</div>
            <div className="ai-cell-val" style={{ color: '#4ad9ff' }}>${f(dec.price)}</div>
          </div>
          <div className="ai-cell">
            <div className="ai-cell-lbl">Stop Loss</div>
            <div className="ai-cell-val" style={{ color: '#ff476f' }}>${f(dec.stopLoss)}</div>
            <div className="ai-cell-sub">−${f(dec.riskDist)}</div>
          </div>
          <div className="ai-cell">
            <div className="ai-cell-lbl">Price Target</div>
            <div className="ai-cell-val" style={{ color: '#3ddc97' }}>${f(dec.target)}</div>
            <div className="ai-cell-sub">+${f(dec.rewardDist)}</div>
          </div>
          <div className="ai-cell">
            <div className="ai-cell-lbl">Risk / Reward</div>
            <div className="ai-cell-val" style={{ color: rrColor }}>1 : {dec.rr}</div>
            <div className="ai-cell-sub" style={{ color: rrColor }}>{rrLabel}</div>
          </div>
        </div>

        <div className="ai-atr-note" style={{ borderColor: cfg.border }}>
          Stop = 1.5× ATR (${f(data.atr)}) &nbsp;·&nbsp; Target = 2.5× ATR
        </div>
      </div>

      {/* Summary + signals */}
      <div className="ap-card">
        <div className="ap-card-hd">
          <div className="ap-dot" style={{ background: cfg.color }} />
          Why {dec.action}?
        </div>

        <div className="ai-summary">{dec.summary}</div>

        {dec.bulls.length > 0 && (
          <div className="ai-sig-group">
            <div className="ai-sig-group-hd" style={{ color: '#3ddc97' }}>Bullish Signals</div>
            {dec.bulls.map((s, i) => (
              <div key={i} className="ai-sig-row">
                <span className="ai-sig-dot" style={{ background: '#3ddc97' }} />
                <span className="ai-sig-text">{s.t}</span>
              </div>
            ))}
          </div>
        )}

        {dec.bears.length > 0 && (
          <div className="ai-sig-group">
            <div className="ai-sig-group-hd" style={{ color: '#ff476f' }}>Bearish Signals</div>
            {dec.bears.map((s, i) => (
              <div key={i} className="ai-sig-row">
                <span className="ai-sig-dot" style={{ background: '#ff476f' }} />
                <span className="ai-sig-text">{s.t}</span>
              </div>
            ))}
          </div>
        )}

        {dec.neutrals.length > 0 && (
          <div className="ai-sig-group">
            <div className="ai-sig-group-hd" style={{ color: '#f5b342' }}>Neutral / Watch</div>
            {dec.neutrals.map((s, i) => (
              <div key={i} className="ai-sig-row">
                <span className="ai-sig-dot" style={{ background: '#f5b342' }} />
                <span className="ai-sig-text">{s.t}</span>
              </div>
            ))}
          </div>
        )}

        <div className="ai-disclaimer">
          ⚠ Rule-based analysis only — not financial advice.
        </div>
      </div>

    </div>
  )
}

// ── AI Intel Tab ──────────────────────────────────────────────────────────────

const INDIC_LABELS = { rsi: 'RSI', macd: 'MACD', stoch: 'STOCH', volume: 'VOLUME', bb: 'BB', vwap: 'VWAP', trend: 'TREND' }

function AIIntelTab({ detail, aiLoading, aiError }) {
  if (aiLoading && !detail) return <div className="ap-placeholder">Fetching AI analysis…</div>
  if (aiError && !detail) return (
    <div style={{ padding: 16, textAlign: 'center' }}>
      <div style={{ fontSize: 10, color: '#ff6a6a', marginBottom: 4 }}>⚠ {aiError}</div>
      <div style={{ fontSize: 9, color: 'var(--t-4)' }}>Restart the backend if this persists</div>
    </div>
  )
  if (!detail) return <div className="ap-placeholder">No intelligence data yet.</div>

  const { market_state, uncertainty, summary, what_changed, breakdown, score, weights_used } = detail
  const cfg          = MARKET_STATE_CFG[market_state] ?? MARKET_STATE_CFG.neutral
  const scoreColor   = score >= 2.5 ? '#3ddc97' : score <= -2.5 ? '#ff476f' : score > 0 ? '#5ee8a9' : score < 0 ? '#ff6a6a' : '#8899aa'
  const uncertColor  = uncertainty >= 0.6 ? '#ff476f' : uncertainty >= 0.4 ? '#f5b342' : '#3ddc97'
  const uncertLabel  = uncertainty >= 0.6 ? 'High' : uncertainty >= 0.4 ? 'Moderate' : 'Low'
  const scorePct     = Math.min(100, Math.abs(score) / 10 * 100)

  return (
    <div className="ap-content">

      {/* Market Regime Card */}
      <div className="ap-card" style={{ background: cfg.bg, border: `1px solid ${cfg.color}28`, padding: '14px 12px', textAlign: 'center' }}>
        <div style={{ fontSize: 8, letterSpacing: '0.14em', color: 'var(--t-4)', marginBottom: 5 }}>MARKET REGIME</div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 18, fontWeight: 900, color: cfg.color, letterSpacing: '0.06em', marginBottom: 10 }}>
          {cfg.label}
        </div>
        <div style={{ fontSize: 8, color: 'var(--t-4)', marginBottom: 4 }}>AI SCORE</div>
        <div style={{ position: 'relative', height: 6, background: 'rgba(140,170,220,0.08)', borderRadius: 3, marginBottom: 5 }}>
          <div style={{ position: 'absolute', left: '50%', top: 0, bottom: 0, width: 1, background: 'rgba(140,170,220,0.2)' }} />
          {score !== 0 && (
            <div style={{
              position: 'absolute',
              left: score >= 0 ? '50%' : `${50 - scorePct / 2}%`,
              width: `${scorePct / 2}%`,
              top: 0, bottom: 0,
              background: scoreColor, borderRadius: 3, opacity: 0.85, transition: 'width 0.4s',
            }} />
          )}
        </div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: scoreColor, fontWeight: 700 }}>
          {score > 0 ? '+' : ''}{score.toFixed(2)}
        </div>
      </div>

      {/* Uncertainty + What Changed */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
        <div className="ap-card" style={{ padding: '10px 10px' }}>
          <div style={{ fontSize: 8, letterSpacing: '0.1em', color: 'var(--t-4)', marginBottom: 5 }}>UNCERTAINTY</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 16, fontWeight: 800, color: uncertColor, marginBottom: 5 }}>
            {Math.round(uncertainty * 100)}%
          </div>
          <div style={{ height: 4, background: 'rgba(140,170,220,0.08)', borderRadius: 2 }}>
            <div style={{ height: '100%', width: `${uncertainty * 100}%`, background: uncertColor, borderRadius: 2, opacity: 0.75, transition: 'width 0.4s' }} />
          </div>
          <div style={{ fontSize: 8, color: uncertColor, marginTop: 3, fontWeight: 700, letterSpacing: '0.07em' }}>{uncertLabel}</div>
        </div>

        <div className="ap-card" style={{ padding: '10px 10px' }}>
          <div style={{ fontSize: 8, letterSpacing: '0.1em', color: 'var(--t-4)', marginBottom: 5 }}>WHAT CHANGED</div>
          {what_changed?.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              {what_changed.slice(0, 3).map((c, i) => (
                <div key={i} style={{ fontSize: 8.5, color: '#f5b342', fontFamily: 'var(--font-mono)', lineHeight: 1.4, letterSpacing: '0.02em' }}>
                  › {c}
                </div>
              ))}
            </div>
          ) : (
            <div style={{ fontSize: 9, color: 'var(--t-4)', lineHeight: 1.5 }}>No changes detected</div>
          )}
        </div>
      </div>

      {/* AI Summary */}
      <div className="ap-card">
        <div style={{ fontSize: 8, letterSpacing: '0.12em', color: 'var(--t-4)', marginBottom: 6, textTransform: 'uppercase' }}>AI Market Summary</div>
        <div style={{ fontSize: 10.5, color: 'var(--t-2)', lineHeight: 1.7, padding: '8px 10px', background: 'rgba(140,170,220,0.03)', borderLeft: `2px solid ${cfg.color}55`, borderRadius: '0 4px 4px 0' }}>
          {summary || 'Analysis pending…'}
        </div>
      </div>

      {/* Per-Indicator Breakdown */}
      <div className="ap-card">
        <div className="ap-card-hd">
          <div className="ap-dot" style={{ background: '#b39dff' }} />
          Signal Breakdown
        </div>
        {Object.entries(INDIC_LABELS).map(([key, label]) => {
          const b = breakdown?.[key]
          if (!b) return null
          return (
            <ContribBar
              key={key}
              label={label}
              contrib={b.contribution ?? 0}
              signal={b.signal}
              weight={b.weight ?? 1}
              penalty={b.trend_penalty_applied}
            />
          )
        })}

        {breakdown?.ema50_gate?.gate_triggered && (
          <div style={{ marginTop: 6, padding: '5px 8px', background: 'rgba(255,71,111,0.06)', border: '1px solid rgba(255,71,111,0.15)', borderRadius: 4, fontSize: 9.5, color: '#ff6a6a', lineHeight: 1.4 }}>
            ⚠ EMA50 gate — price is {Math.abs(Math.round((1 - (breakdown.ema50_gate.price_vs_ema50 ?? 1)) * 100))}% below 50-day MA. Buy signals capped.
          </div>
        )}

        {/* Adaptive weights legend */}
        {weights_used && Object.keys(weights_used).length > 0 && (
          <div style={{ marginTop: 10, paddingTop: 8, borderTop: '1px solid rgba(140,170,220,0.07)' }}>
            <div style={{ fontSize: 8, color: 'var(--t-4)', letterSpacing: '0.1em', marginBottom: 4 }}>
              ADAPTIVE WEIGHTS · {(market_state ?? '').replace(/_/g, ' ').toUpperCase()}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {Object.entries(weights_used).map(([k, v]) => (
                <span key={k} style={{
                  fontSize: 8, fontFamily: 'var(--font-mono)', padding: '2px 6px',
                  border: '1px solid rgba(140,170,220,0.15)', borderRadius: 3,
                  color: v > 1.1 ? '#f5b342' : v < 0.9 ? '#8899aa' : 'var(--t-4)',
                  background: v > 1.1 ? 'rgba(245,179,66,0.06)' : 'transparent',
                }}>
                  {k.toUpperCase()} ×{Number(v).toFixed(1)}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

    </div>
  )
}

// ── Live Quote Bar ─────────────────────────────────────────────────────────────

function LiveQuoteBar({ quote, extQuote, secsAgo }) {
  if (!quote && !extQuote) return null
  const price     = quote ? (quote.bid + quote.ask) / 2 : extQuote?.bid
  const change    = extQuote?.change    ?? quote?.change    ?? 0
  const changePct = extQuote?.change_pct ?? quote?.change_pct ?? 0
  const high      = extQuote?.high
  const low       = extQuote?.low
  const bid       = quote?.bid ?? extQuote?.bid
  const ask       = quote?.ask ?? extQuote?.ask
  const isLive    = secsAgo <= 8
  const pColor    = change >= 0 ? '#3ddc97' : '#ff476f'

  return (
    <div className="ap-quote-bar">
      <div className="ap-quote-row1">
        <span className="ap-quote-price" style={{ color: pColor }}>
          ${price != null ? Number(price).toFixed(2) : '—'}
        </span>
        <span className="ap-quote-change" style={{ color: pColor }}>
          {change >= 0 ? '+' : ''}{Number(change).toFixed(2)}&thinsp;
          ({change >= 0 ? '+' : ''}{Number(changePct).toFixed(2)}%)
        </span>
        <div style={{ flex: 1 }} />
        <span className={`ap-live-badge${isLive ? ' live' : ''}`}>
          <span className="ap-live-dot" style={{ background: isLive ? '#3ddc97' : '#f5b342' }} />
          {secsAgo < 3 ? 'LIVE' : `${secsAgo}s`}
        </span>
      </div>
      <div className="ap-quote-row2">
        {bid != null && <span>B&thinsp;<b>{Number(bid).toFixed(2)}</b></span>}
        {ask != null && <span>A&thinsp;<b>{Number(ask).toFixed(2)}</b></span>}
        {high > 0    && <span>H&thinsp;<b>{Number(high).toFixed(2)}</b></span>}
        {low  > 0    && <span>L&thinsp;<b>{Number(low).toFixed(2)}</b></span>}
      </div>
    </div>
  )
}

// ── Main export ────────────────────────────────────────────────────────────────

export default function AnalysisPanel({ symbol, quote, delta, portfolioId }) {
  const [tab,       setTab]      = useState('analysis')
  const [data,      setData]     = useState(null)
  const [loading,   setLoading]  = useState(false)
  const [extQuote,  setExtQuote] = useState(null)
  const [secsAgo,   setSecsAgo]  = useState(0)
  const [aiDetail,  setAiDetail] = useState(null)
  const [aiLoading, setAiLoading]= useState(false)
  const [aiError,   setAiError]  = useState(null)
  const [brief,     setBrief]    = useState(null)
  const [portReg,   setPortReg]  = useState(null)
  const lastUpdRef = useRef(null)
  const refreshRef = useRef(null)

  useEffect(() => {
    setExtQuote(null)
    setSecsAgo(0)
    setAiDetail(null)
    setAiError(null)
    lastUpdRef.current = null
  }, [symbol])

  // AI Intelligence fetch — /api/analysis/<symbol> every 90s
  useEffect(() => {
    if (!symbol) return
    let cancelled = false
    const doFetch = () => {
      setAiLoading(true)
      setAiError(null)
      api.get(`/analysis/${symbol}`, { timeout: 30000 })
        .then(r => {
          if (!cancelled) {
            if (r.data?.error) setAiError(r.data.error)
            else setAiDetail(r.data)
            setAiLoading(false)
          }
        })
        .catch(e => {
          if (!cancelled) {
            setAiError(e?.response?.data?.error || e?.message || 'Request failed')
            setAiLoading(false)
          }
        })
    }
    doFetch()
    const id = setInterval(doFetch, 90_000)
    return () => { cancelled = true; clearInterval(id) }
  }, [symbol])

  // Brief fetch — asset class, stop levels, session guide, S/R from structure engine
  useEffect(() => {
    if (!symbol) return
    let cancelled = false
    api.get(`/analysis/${symbol}/brief`).then(r => {
      if (!cancelled) setBrief(r.data)
    }).catch(() => {})
    return () => { cancelled = true }
  }, [symbol])

  // Portfolio regime fetch
  useEffect(() => {
    if (!portfolioId || portfolioId === 0) return
    api.get(`/portfolios/${portfolioId}/portfolio_regime`)
      .then(r => setPortReg(r.data))
      .catch(() => {})
  }, [portfolioId])

  useEffect(() => {
    if (!quote) return
    lastUpdRef.current = Date.now()
    setSecsAgo(0)
  }, [quote])

  useEffect(() => {
    const id = setInterval(() => {
      if (lastUpdRef.current)
        setSecsAgo(Math.floor((Date.now() - lastUpdRef.current) / 1000))
    }, 1000)
    return () => clearInterval(id)
  }, [])

  // 30s REST poll for H/L/O/change
  useEffect(() => {
    if (!symbol) return
    let cancelled = false
    const poll = () => {
      api.get(`/quote/${symbol}`).then(r => {
        if (cancelled) return
        setExtQuote(r.data)
        if (!lastUpdRef.current) { lastUpdRef.current = Date.now(); setSecsAgo(0) }
      }).catch(() => {})
    }
    poll()
    const id = setInterval(poll, 30_000)
    return () => { cancelled = true; clearInterval(id) }
  }, [symbol])

  // Projection fetch — initial + 60s auto-refresh + manual refresh
  useEffect(() => {
    if (!symbol) return
    let cancelled = false

    const doFetch = (force = false) => {
      setLoading(true)
      const url = `/projection/${symbol}${force ? '?force=1' : ''}`
      api.get(url)
        .then(r => { if (!cancelled) { setData(r.data); setLoading(false) } })
        .catch(() => { if (!cancelled) setLoading(false) })
    }

    // Expose a force-refresh that clears stale data, re-fetches projection,
    // and also re-fetches the live quote to reset the timer
    refreshRef.current = () => {
      setData(null)
      doFetch(true)
      api.get(`/quote/${symbol}`).then(r => {
        if (!cancelled) {
          setExtQuote(r.data)
          lastUpdRef.current = Date.now()
          setSecsAgo(0)
        }
      }).catch(() => {})
    }

    setData(null)
    doFetch(false)
    const id = setInterval(() => doFetch(false), 60_000)
    return () => {
      cancelled = true
      clearInterval(id)
      refreshRef.current = null
    }
  }, [symbol])

  const price = quote
    ? (quote.bid + quote.ask) / 2
    : extQuote?.bid ?? delta?.bid
      ? (Number(delta?.bid ?? 0) + Number(delta?.ask ?? delta?.bid ?? 0)) / 2
      : null

  return (
    <div className="analysis-panel">

      <div className="ap-tabbar">
        <button className={`ap-tab${tab === 'analysis' ? ' active' : ''}`} onClick={() => setTab('analysis')}>
          Analysis
        </button>
        <button className={`ap-tab${tab === 'ai' ? ' active ai-tab' : ' ai-tab'}`} onClick={() => setTab('ai')}>
          AI Decision
        </button>
        <button className={`ap-tab${tab === 'intel' ? ' active' : ''}`} onClick={() => setTab('intel')}
          style={{ position: 'relative' }}>
          AI Intel
          {aiDetail && tab !== 'intel' && aiDetail.what_changed?.length > 0 && (
            <span style={{ position: 'absolute', top: 5, right: 4, width: 5, height: 5, borderRadius: '50%', background: '#f5b342' }} />
          )}
        </button>
        <button className={`ap-tab${tab === 'risk' ? ' active' : ''}`} onClick={() => setTab('risk')}>
          Risk
        </button>
        <div className="ap-tab-indicators">
          {(loading || aiLoading) && <span className="ap-spinner" />}
          {data && price && !loading && <span className="ap-live-pip" title="Data ready" />}
          <button
            className="ap-refresh-btn"
            title="Force-refresh indicators"
            onClick={() => refreshRef.current?.()}
            disabled={loading}
          >↻</button>
        </div>
      </div>

      <LiveQuoteBar quote={quote} extQuote={extQuote} secsAgo={secsAgo} />

      {tab === 'analysis' && <AnalysisTab data={data} price={price} symbol={symbol} brief={brief} portReg={portReg} />}
      {tab === 'ai'       && <AIDecisionTab data={data} price={price} />}
      {tab === 'intel'    && <AIIntelTab detail={aiDetail} aiLoading={aiLoading} aiError={aiError} />}
      {tab === 'risk'     && (
        <div className="ap-content">
          <RiskPanelInline symbol={symbol} portfolioId={portfolioId} price={price} />
        </div>
      )}

    </div>
  )
}

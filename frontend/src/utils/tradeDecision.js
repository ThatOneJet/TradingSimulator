export function computeDecision(data, price) {
  if (!data || !price) return null

  let score = 0
  const signals = []
  const rsi = data.rsi ?? 50
  const stochK = data.stoch_k_val ?? 50
  const atr = data.atr || price * 0.02
  const atrPct = data.atr_pct ?? 2

  // ── Regime weight multipliers ───────────────────────────────────────────────
  const rsibbMult  = data.regime === 'consolidating'                                    ? 1.3 : 1.0
  const macdtrendMult = (data.regime === 'trending_up' || data.regime === 'trending_down') ? 1.3 : 1.0

  // ── RSI — 6-tier grading ────────────────────────────────────────────────────
  if      (rsi <= 20)  { score += 3.0 * rsibbMult;  signals.push({ t: `RSI ${rsi.toFixed(1)} — extreme oversold (top 1% of readings). Mean-reversion buy is high probability`,          bull: true  }) }
  else if (rsi <= 28)  { score += 2.0 * rsibbMult;  signals.push({ t: `RSI ${rsi.toFixed(1)} — oversold zone. Buyers historically dominate at these levels; watch for confirmation`,     bull: true  }) }
  else if (rsi <= 38)  { score += 1.0 * rsibbMult;  signals.push({ t: `RSI ${rsi.toFixed(1)} — mild oversold bias. Momentum is fading from the downside`,                               bull: true  }) }
  else if (rsi >= 80)  { score -= 3.0 * rsibbMult;  signals.push({ t: `RSI ${rsi.toFixed(1)} — extreme overbought (top 1% of readings). Sharp reversal or pullback likely`,              bull: false }) }
  else if (rsi >= 72)  { score -= 2.0 * rsibbMult;  signals.push({ t: `RSI ${rsi.toFixed(1)} — overbought zone. Selling pressure typically increases at these levels`,                   bull: false }) }
  else if (rsi >= 62)  { score -= 1.0 * rsibbMult;  signals.push({ t: `RSI ${rsi.toFixed(1)} — mild overbought bias. Upside momentum is thinning`,                                      bull: false }) }

  // ── MACD — fresh crossovers weighted more than sustained ────────────────────
  if      (data.macd_cross === 'bullish_cross') { score += 3.0 * macdtrendMult;  signals.push({ t: `MACD bullish crossover — momentum just flipped positive. One of the strongest short-term entry signals`,   bull: true  }) }
  else if (data.macd_cross === 'bearish_cross') { score -= 3.0 * macdtrendMult;  signals.push({ t: `MACD bearish crossover — momentum just flipped negative. Classic exit or short signal`,                     bull: false }) }
  else if (data.macd_cross === 'bullish')       { score += 1.5 * macdtrendMult;  signals.push({ t: `MACD ${(data.macd_value ?? 0).toFixed(4)} above signal (${(data.macd_signal_value ?? 0).toFixed(4)}) — sustained bullish momentum. Histogram: ${((data.macd_value ?? 0) - (data.macd_signal_value ?? 0)).toFixed(4)}`, bull: true }) }
  else if (data.macd_cross === 'bearish')       { score -= 1.5 * macdtrendMult;  signals.push({ t: `MACD ${(data.macd_value ?? 0).toFixed(4)} below signal (${(data.macd_signal_value ?? 0).toFixed(4)}) — sustained bearish momentum. Bears are in control`,                                             bull: false }) }

  // ── Stochastic — with actual %K and %D values ───────────────────────────────
  if      (stochK <= 15) { score += 1.5;  signals.push({ t: `Stoch %K ${stochK.toFixed(1)} — deep oversold (below 15). Snap-back rally typically follows; watch for %K > %D cross`,  bull: true  }) }
  else if (stochK <= 25) { score += 1.0;  signals.push({ t: `Stoch %K ${stochK.toFixed(1)} — oversold. %D at ${(data.stoch_d_val ?? 0).toFixed(1)}. Buy signal on %K cross above %D`, bull: true  }) }
  else if (stochK >= 85) { score -= 1.5;  signals.push({ t: `Stoch %K ${stochK.toFixed(1)} — deep overbought (above 85). Exhaustion likely; watch for %K < %D reversal`,              bull: false }) }
  else if (stochK >= 75) { score -= 1.0;  signals.push({ t: `Stoch %K ${stochK.toFixed(1)} — overbought. %D at ${(data.stoch_d_val ?? 0).toFixed(1)}. Sell signal on %K cross below %D`, bull: false }) }

  // ── Volume — with ratio in signal text ─────────────────────────────────────
  const volRatio = data.volume_ratio ?? 1
  if      (data.volume_signal === 'high_up')   { score += 2.0;  signals.push({ t: `Volume ${volRatio.toFixed(2)}× above average on green day — institutional accumulation confirmed. High-volume advances sustain`,  bull: true  }) }
  else if (data.volume_signal === 'high_down') { score -= 2.0;  signals.push({ t: `Volume ${volRatio.toFixed(2)}× above average on red day — institutional distribution. High-volume declines typically continue`,   bull: false }) }
  else if (data.volume_signal === 'low')       { score *= 0.65; signals.push({ t: `Volume ${volRatio.toFixed(2)}× of average — well below normal. All signals carry reduced weight until volume confirms`,           bull: null  }) }

  // ── Bollinger Bands ──────────────────────────────────────────────────────────
  if      (data.bb_position === 'oversold')   { score += 1.5 * rsibbMult;  signals.push({ t: `Price below lower BB ($${(data.bb_lower_val ?? 0).toFixed(2)}) — statistically extreme, only ~2.3% of days. Reversion to midline probable`,          bull: true  }) }
  else if (data.bb_position === 'overbought') { score -= 1.5 * rsibbMult;  signals.push({ t: `Price above upper BB ($${(data.bb_upper_val ?? 0).toFixed(2)}) — statistically extreme, only ~2.3% of days. Mean reversion probable`,                 bull: false }) }
  else if (data.bb_position === 'squeeze')    {                              signals.push({ t: `BB squeeze active — bands narrowing to historical low. A large volatility breakout is imminent; direction TBD`,                                        bull: null  }) }
  else if (data.bb_position === 'lower_half') { score += 0.5 * rsibbMult;  signals.push({ t: `Price in lower BB half — approaching support near lower band ($${(data.bb_lower_val ?? 0).toFixed(2)}). Mild mean-reversion bullish lean`,            bull: true  }) }
  else if (data.bb_position === 'upper_half') { score -= 0.5 * rsibbMult;  signals.push({ t: `Price in upper BB half — approaching resistance near upper band ($${(data.bb_upper_val ?? 0).toFixed(2)}). Mild mean-reversion bearish lean`,          bull: false }) }

  // ── VWAP — with distance ────────────────────────────────────────────────────
  const vwapDist = data.vwap_value ? ((price - data.vwap_value) / data.vwap_value * 100).toFixed(2) : null
  if      (data.vwap_signal === 'above') { score += 1.0;  signals.push({ t: `Price ${vwapDist != null ? `${vwapDist}% ` : ''}above VWAP ($${(data.vwap_value ?? 0).toFixed(2)}) — institutional algorithms net long today`, bull: true  }) }
  else if (data.vwap_signal === 'below') { score -= 1.0;  signals.push({ t: `Price ${vwapDist != null ? `${Math.abs(vwapDist)}% ` : ''}below VWAP ($${(data.vwap_value ?? 0).toFixed(2)}) — institutional algorithms net short today`, bull: false }) }

  // ── Trend — linear regression direction ────────────────────────────────────
  if      (data.trend === 'up')   { score += 1.5 * macdtrendMult;  signals.push({ t: `Regression slope positive — price in confirmed uptrend. Buy dips, trail stops on strength`,    bull: true  }) }
  else if (data.trend === 'down') { score -= 1.5 * macdtrendMult;  signals.push({ t: `Regression slope negative — price in confirmed downtrend. Sell rallies, shorting has tailwind`, bull: false }) }
  else                            {                                  signals.push({ t: `Sideways trend — no directional edge from price structure. Breakout required for trend trade`,   bull: null  }) }

  // ── Volatility regime adjustment ────────────────────────────────────────────
  if (atrPct > 5) {
    score *= 0.85  // High-volatility environments produce more noise
    signals.push({ t: `ATR ${(atr).toFixed(2)} (${atrPct.toFixed(1)}%) — elevated volatility regime. All signals discounted; widen stops to 2× ATR`, bull: null })
  } else if (atrPct < 0.8) {
    signals.push({ t: `ATR ${(atr).toFixed(2)} (${atrPct.toFixed(1)}%) — very low volatility. Compressed coil; breakout likely. Direction unclear until it fires`, bull: null })
  }

  // ── Regime high-volatility discount ─────────────────────────────────────────
  if (data.regime === 'high_volatility') {
    score *= 0.70
  }

  // ── MTF alignment bonus/penalty ──────────────────────────────────────────────
  if (data.mtf) {
    if (data.mtf.bull_count >= 2) score += 0.5
    else if (data.mtf.bear_count >= 2) score -= 0.5
  }

  // ── Decision ────────────────────────────────────────────────────────────────
  const action   = score >= 2.0 ? 'BUY' : score <= -2.0 ? 'SELL' : 'HOLD'
  const absScore = Math.abs(score)
  const maxScore = 14  // theoretical max with all signals aligned

  // Full-range confidence: 50% at score=0, 96% at max score
  const bulls    = signals.filter(s => s.bull === true)
  const bears    = signals.filter(s => s.bull === false)
  const neutrals = signals.filter(s => s.bull === null)
  const alignment = action === 'BUY'  ? (bulls.length - bears.length) / Math.max(1, bulls.length + bears.length)
                  : action === 'SELL' ? (bears.length - bulls.length) / Math.max(1, bulls.length + bears.length)
                  : 0

  const rawConf = 50 + (absScore / maxScore) * 46 + alignment * 6
  const confidence = Math.min(97, Math.max(12, Math.round(rawConf)))

  let stopLoss, target
  if      (action === 'BUY')  { stopLoss = price - 1.5 * atr; target = price + 2.5 * atr }
  else if (action === 'SELL') { stopLoss = price + 1.5 * atr; target = price - 2.5 * atr }
  else                        { stopLoss = price - atr;       target = price + atr        }

  const riskDist   = Math.abs(price - stopLoss)
  const rewardDist = Math.abs(target - price)
  const rr         = riskDist > 0 ? (rewardDist / riskDist).toFixed(2) : '—'
  const rrNum      = parseFloat(rr)

  let summary
  if (action === 'BUY') {
    const topBull = bulls[0]?.t.split('—')[0].trim() ?? 'multiple factors'
    const rrQual  = rrNum >= 2.5 ? 'excellent' : rrNum >= 1.7 ? 'favorable' : 'acceptable'
    summary = `${bulls.length} of ${signals.length} signals bullish (score ${score > 0 ? '+' : ''}${score.toFixed(1)}). Entry near $${price.toFixed(2)} — ${topBull}. Stop at $${stopLoss.toFixed(2)} risks $${riskDist.toFixed(2)}/share. Target $${target.toFixed(2)} yields $${rewardDist.toFixed(2)} (1:${rr} R/R — ${rrQual}).`
  } else if (action === 'SELL') {
    const topBear = bears[0]?.t.split('—')[0].trim() ?? 'multiple factors'
    summary = `${bears.length} of ${signals.length} signals bearish (score ${score.toFixed(1)}). Bearish setup at $${price.toFixed(2)} — ${topBear}. Stop at $${stopLoss.toFixed(2)}, target $${target.toFixed(2)}. R/R 1:${rr}. Consider reducing exposure or shorting with protective stop.`
  } else {
    const lean = bulls.length > bears.length ? 'mildly bullish' : bears.length > bulls.length ? 'mildly bearish' : 'neutral'
    const needed = bulls.length > bears.length
      ? `MACD bullish crossover or RSI dip below 35 needed for a BUY signal`
      : `MACD bearish crossover or RSI push above 65 needed for a SELL signal`
    summary = `Score ${score > 0 ? '+' : ''}${score.toFixed(1)} — tape is ${lean} but below conviction threshold. ${needed}. No edge entering at $${price.toFixed(2)} right now. Wait for a cleaner setup.`
  }

  return {
    action, score: +score.toFixed(1), confidence,
    price:      +price.toFixed(2),
    stopLoss:   +stopLoss.toFixed(2),
    target:     +target.toFixed(2),
    riskDist:   +riskDist.toFixed(2),
    rewardDist: +rewardDist.toFixed(2),
    rr, signals, bulls, bears, neutrals, summary,
    regime: data.regime || 'neutral',
    mtf: data.mtf || null,
  }
}

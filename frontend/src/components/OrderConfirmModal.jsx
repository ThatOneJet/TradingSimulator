import { useEffect, useRef, useState } from 'react'
import { createChart } from 'lightweight-charts'
import api from '../api.js'
import { computeDecision } from '../utils/tradeDecision.js'

const ACTION_CFG = {
  BUY:  { color: '#3ddc97', border: 'rgba(61,220,151,0.25)',  glow: '0 0 24px rgba(61,220,151,0.15)'  },
  SELL: { color: '#ff476f', border: 'rgba(255,71,111,0.25)',  glow: '0 0 24px rgba(255,71,111,0.15)'  },
  HOLD: { color: '#f5b342', border: 'rgba(245,179,66,0.25)',  glow: '0 0 24px rgba(245,179,66,0.12)'  },
}

function f(n, d = 2) { return (n == null || isNaN(n)) ? '—' : Number(n).toFixed(d) }

export default function OrderConfirmModal({
  symbol, side, qty, orderType, limitPrice,
  quote, account, portfolioId,
  onConfirm, onCancel,
}) {
  const chartRef   = useRef()
  const [proj,     setProj]     = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const bidPrice  = quote?.bid ?? 0
  const askPrice  = quote?.ask ?? 0
  const midPrice  = quote ? (bidPrice + askPrice) / 2 : null
  const tradePrice = (orderType === 'limit' && limitPrice)
    ? Number(limitPrice)
    : side === 'buy' ? askPrice : bidPrice
  const estCost   = qty > 0 && tradePrice > 0 ? qty * tradePrice : null
  const fmt       = n => n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

  // Fetch projection for AI card (cached on backend, fast)
  useEffect(() => {
    api.get(`/projection/${symbol}`).then(r => setProj(r.data)).catch(() => {})
  }, [symbol])

  // Mini chart — last 80 one-minute bars
  useEffect(() => {
    const el = chartRef.current
    if (!el) return
    const chart = createChart(el, {
      width: el.clientWidth, height: el.clientHeight,
      layout:          { background: { color: '#06080f' }, textColor: '#5a6a7a' },
      grid:            { vertLines: { color: '#0e1420' }, horzLines: { color: '#0e1420' } },
      crosshair:       { mode: 0 },
      rightPriceScale: { borderColor: '#1a2234', scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale:       { visible: false },
      watermark:       { visible: false },
      handleScroll:    false,
      handleScale:     false,
    })
    const candle = chart.addCandlestickSeries({
      upColor: '#26d97f', downColor: '#ff4d4d',
      borderUpColor: '#26d97f', borderDownColor: '#ff4d4d',
      wickUpColor: '#26d97f', wickDownColor: '#ff4d4d',
    })
    api.get(`/bars/${symbol}?timeframe=1Min&limit=80`).then(r => {
      candle.setData(r.data)
      chart.timeScale().fitContent()
    }).catch(() => {})
    setTimeout(() => el?.querySelectorAll('a[href*="tradingview"],a[target="_blank"]').forEach(a => a.remove()), 60)
    return () => chart.remove()
  }, [symbol])

  const decision = proj && midPrice ? computeDecision(proj, midPrice) : null
  const cfg      = decision ? ACTION_CFG[decision.action] : null
  const rrNum    = parseFloat(decision?.rr)
  const rrColor  = rrNum >= 2 ? '#3ddc97' : rrNum >= 1.5 ? '#f5b342' : '#ff476f'

  async function confirm() {
    setSubmitting(true)
    await onConfirm()
    // onConfirm handles closing modal after API call
  }

  // Dismiss on Escape key
  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') onCancel() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onCancel])

  return (
    <div className="ocm-overlay" onClick={onCancel}>
      <div className="ocm-card" onClick={e => e.stopPropagation()}>

        {/* ── Header ── */}
        <div className="ocm-hd">
          <span>Confirm Order</span>
          <button className="ocm-close" onClick={onCancel}>×</button>
        </div>

        {/* ── Mini chart ── */}
        <div className="ocm-chart-wrap">
          <div className="ocm-chart-sym">{symbol}</div>
          {midPrice && (
            <div className="ocm-chart-price" style={{ color: (quote?.change ?? 0) >= 0 ? '#3ddc97' : '#ff476f' }}>
              ${f(midPrice)}
            </div>
          )}
          <div ref={chartRef} className="ocm-chart" />
        </div>

        {/* ── Order summary ── */}
        <div className="ocm-order-summary">
          <div className="ocm-order-row">
            <span className={`ocm-side-pill ${side}`}>{side.toUpperCase()}</span>
            <span className="ocm-order-text">
              <b>{qty}</b> share{qty !== 1 ? 's' : ''} of <b>{symbol}</b>
            </span>
            <span className="ocm-order-type mono">{orderType === 'limit' ? `Limit $${f(tradePrice)}` : 'Market'}</span>
          </div>
          {estCost != null && (
            <div className="ocm-cost-row">
              <span>Est. {side === 'buy' ? 'Cost' : 'Proceeds'}</span>
              <span className="mono">${fmt(estCost)}</span>
            </div>
          )}
          {account && side === 'buy' && (
            <div className="ocm-cost-row" style={{ opacity: 0.6 }}>
              <span>Buying power after</span>
              <span className="mono">${fmt(Math.max(0, Number(account.buying_power) - (estCost ?? 0)))}</span>
            </div>
          )}
        </div>

        {/* ── AI recommendation ── */}
        {decision && cfg ? (
          <div className="ocm-ai-card" style={{ borderColor: cfg.border, boxShadow: cfg.glow }}>
            <div className="ocm-ai-top">
              <div className="ocm-ai-left">
                <span className="ocm-ai-action" style={{ color: cfg.color }}>{decision.action}</span>
                <span className="ocm-ai-label">AI SIGNAL</span>
              </div>
              <div className="ocm-ai-right">
                <div className="ocm-ai-conf-row">
                  <span className="ocm-ai-conf-lbl">CONFIDENCE</span>
                  <span className="ocm-ai-conf-val" style={{ color: cfg.color }}>{decision.confidence}%</span>
                </div>
                <div className="ocm-ai-conf-track">
                  <div className="ocm-ai-conf-fill" style={{ width: `${decision.confidence}%`, background: cfg.color }} />
                </div>
                <div className="ocm-ai-score">{decision.bulls.length}↑ · {decision.bears.length}↓ signals</div>
              </div>
            </div>

            <div className="ocm-ai-grid">
              <div className="ocm-ai-cell">
                <div className="ocm-ai-lbl">Entry</div>
                <div className="ocm-ai-val" style={{ color: '#4ad9ff' }}>${f(decision.price)}</div>
              </div>
              <div className="ocm-ai-cell">
                <div className="ocm-ai-lbl">Stop Loss</div>
                <div className="ocm-ai-val" style={{ color: '#ff476f' }}>${f(decision.stopLoss)}</div>
                <div className="ocm-ai-sub">−${f(decision.riskDist)}</div>
              </div>
              <div className="ocm-ai-cell">
                <div className="ocm-ai-lbl">Target</div>
                <div className="ocm-ai-val" style={{ color: '#3ddc97' }}>${f(decision.target)}</div>
                <div className="ocm-ai-sub">+${f(decision.rewardDist)}</div>
              </div>
              <div className="ocm-ai-cell">
                <div className="ocm-ai-lbl">Risk / Reward</div>
                <div className="ocm-ai-val" style={{ color: rrColor }}>1 : {decision.rr}</div>
              </div>
            </div>

            {/* Top signal */}
            {decision.signals[0] && (
              <div className="ocm-ai-signal">
                <span className="ocm-ai-sig-dot" style={{
                  background: decision.signals[0].bull === true ? '#3ddc97'
                    : decision.signals[0].bull === false ? '#ff476f' : '#f5b342'
                }} />
                {decision.signals[0].t}
              </div>
            )}
          </div>
        ) : (
          <div className="ocm-ai-loading">
            {proj === null ? '⟳ Loading AI analysis…' : 'Insufficient data for AI analysis.'}
          </div>
        )}

        {/* ── Footer buttons ── */}
        <div className="ocm-actions">
          <button className="ocm-cancel" onClick={onCancel}>Cancel</button>
          <button
            className={`ocm-confirm ${side}`}
            onClick={confirm}
            disabled={submitting}
          >
            {submitting ? '…' : `Confirm ${side.toUpperCase()} ${symbol}`}
          </button>
        </div>

      </div>
    </div>
  )
}

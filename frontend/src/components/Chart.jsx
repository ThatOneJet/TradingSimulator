import { useCallback, useEffect, useRef, useState } from 'react'
import { createChart } from 'lightweight-charts'
import api from '../api.js'

const CHART_BASE = {
  layout:          { background: { color: '#0a0d14' }, textColor: '#6b7a90' },
  grid:            { vertLines: { color: 'rgba(30,41,60,0.8)' }, horzLines: { color: 'rgba(30,41,60,0.8)' } },
  crosshair:       { mode: 1, vertLine: { color: 'rgba(140,170,220,0.3)', labelBackgroundColor: '#1a2234' }, horzLine: { color: 'rgba(140,170,220,0.3)', labelBackgroundColor: '#1a2234' } },
  rightPriceScale: { borderColor: '#1a2234', scaleMargins: { top: 0.06, bottom: 0.06 } },
  timeScale:       { borderColor: '#1a2234', timeVisible: true, secondsVisible: false, fixRightEdge: true },
  watermark:       { visible: false },
  handleScroll:    { mouseWheel: true, pressedMouseMove: true },
  handleScale:     { mouseWheel: true, pinch: true },
}

const SUB_BASE = {
  ...CHART_BASE,
  layout: { background: { color: '#080b12' }, textColor: '#6b7a90' },
  timeScale: { ...CHART_BASE.timeScale, visible: false },
  rightPriceScale: { ...CHART_BASE.rightPriceScale, scaleMargins: { top: 0.1, bottom: 0.1 } },
}

function removeAttribution(el) {
  setTimeout(() => el?.querySelectorAll('a[href*="tradingview"],a[target="_blank"]').forEach(a => a.remove()), 60)
}

function fmtTime(t, isDaily) {
  if (!t) return ''
  let d
  if (typeof t === 'number') {
    d = new Date(t * 1000)
  } else if (typeof t === 'string' && t.includes('-')) {
    const [y, m, day] = t.split('-').map(Number)
    d = new Date(y, m - 1, day)
  } else {
    return String(t)
  }
  if (isDaily) {
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  }
  return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true })
}

function makeTimeFmt(isDaily) {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone
  return (t) => {
    const d = new Date(t * 1000)
    return isDaily
      ? d.toLocaleDateString('en-US', { timeZone: tz, month: 'short', day: 'numeric', year: 'numeric' })
      : d.toLocaleTimeString('en-US', { timeZone: tz, hour: 'numeric', minute: '2-digit', hour12: true })
  }
}

export default function Chart({ symbol, timeframe, socket, overlays, quote, delta }) {
  const mainRef    = useRef()
  const macdRef    = useRef()
  const oscRef     = useRef()
  const tooltipEl  = useRef()

  const [dragState, setDragState] = useState(null) // {startX, startY, endX, endY}
  const [orderBox,  setOrderBox]  = useState(null) // {topY, botY, leftX, rightX, show}

  // Derive mid price from live quote or fallback delta
  const midPrice = quote
    ? (quote.bid + quote.ask) / 2
    : delta?.bid
      ? (Number(delta.bid) + Number(delta.ask || delta.bid)) / 2
      : null

  const mainChartRef  = useRef()
  const candleRef     = useRef()
  const volumeRef     = useRef()
  const macdChartRef  = useRef()
  const oscChartRef   = useRef()
  const namedSeries   = useRef({})
  const priceLinesRef = useRef([])
  const intervalRef   = useRef(null)

  const [lastUpdated,  setLastUpdated]  = useState(null)
  const [refreshFlash, setRefreshFlash] = useState(false)
  const [badges, setBadges] = useState({})

  const showMacd = !!overlays?.has('MACD')
  const showOsc  = !!(overlays?.has('RSI') || overlays?.has('Stoch'))
  const isDaily  = !['1Min', '5Min', '15Min', '1Hour'].includes(timeframe)

  // ── Bar polling ──────────────────────────────────────────────────────────────
  const fetchBars = useCallback(() => {
    api.get(`/bars/${symbol}?timeframe=${timeframe}&limit=300`).then(r => {
      candleRef.current?.setData(r.data)
      volumeRef.current?.setData(r.data.map(b => ({
        time: b.time, value: b.volume,
        color: b.close >= b.open ? 'rgba(38,217,127,0.25)' : 'rgba(255,77,77,0.25)',
      })))
      // Always snap to latest tick after loading data
      mainChartRef.current?.timeScale().scrollToRealTime()
      setLastUpdated(new Date())
      setRefreshFlash(true)
      setTimeout(() => setRefreshFlash(false), 800)
    }).catch(() => {})
  }, [symbol, timeframe])

  useEffect(() => {
    fetchBars()
    intervalRef.current = setInterval(fetchBars, 60_000)
    return () => clearInterval(intervalRef.current)
  }, [fetchBars])

  // ── Main chart (candle + volume + tooltip) — no MACD/OSC ────────────────────
  useEffect(() => {
    const timeFmt = makeTimeFmt(isDaily)
    const mainEl  = mainRef.current
    if (!mainEl) return

    const mainChart = createChart(mainEl, {
      ...CHART_BASE,
      width:  mainEl.clientWidth,
      height: mainEl.clientHeight || 300,
      localization: { timeFormatter: timeFmt },
    })
    removeAttribution(mainEl)

    const candle = mainChart.addCandlestickSeries({
      upColor: '#26d97f', downColor: '#ff4d4d',
      borderUpColor: '#26d97f', borderDownColor: '#ff4d4d',
      wickUpColor: '#1ea860', wickDownColor: '#cc2222',
    })
    const volume = mainChart.addHistogramSeries({
      priceFormat:  { type: 'volume' },
      priceScaleId: 'vol',
      scaleMargins: { top: 0.88, bottom: 0 },
    })
    mainChart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.88, bottom: 0 } })

    mainChartRef.current = mainChart
    candleRef.current    = candle
    volumeRef.current    = volume

    // tooltip
    const tip = tooltipEl.current
    const handleCrosshair = (param) => {
      if (!tip) return
      if (!param.time || !param.point) { tip.style.display = 'none'; return }
      const d = param.seriesData?.get(candle)
      if (!d) { tip.style.display = 'none'; return }

      const chartW = mainEl.clientWidth
      const x      = param.point.x
      const tipW   = 130
      const flip   = x + tipW + 20 > chartW
      const isUp   = d.close >= d.open
      const chg    = d.close - d.open
      const chgPct = d.open > 0 ? (chg / d.open * 100).toFixed(2) : '0.00'
      const fmt    = n => n?.toFixed(2) ?? '—'
      const upC = '#26d97f', dnC = '#ff4d4d'
      const cc  = isUp ? upC : dnC

      tip.style.display = 'flex'
      tip.style.left    = (flip ? x - tipW - 10 : x + 14) + 'px'
      tip.innerHTML = `
        <div class="ct-time">${fmtTime(param.time, isDaily)}</div>
        <div class="ct-chg" style="color:${cc}">${isUp ? '▲' : '▼'} ${fmt(Math.abs(chg))} (${isUp ? '+' : ''}${chgPct}%)</div>
        <div class="ct-r"><span class="ct-l">OPEN</span><span style="color:var(--t-2)">${fmt(d.open)}</span></div>
        <div class="ct-r"><span class="ct-l">HIGH</span><span style="color:${upC}">${fmt(d.high)}</span></div>
        <div class="ct-r"><span class="ct-l">LOW</span><span style="color:${dnC}">${fmt(d.low)}</span></div>
        <div class="ct-r"><span class="ct-l">CLOSE</span><span style="color:${cc};font-weight:700">${fmt(d.close)}</span></div>
      `
    }
    mainChart.subscribeCrosshairMove(handleCrosshair)

    const ro = new ResizeObserver(() => {
      mainChart.applyOptions({ width: mainEl.clientWidth, height: mainEl.clientHeight })
    })
    ro.observe(mainEl)

    return () => {
      if (tip) tip.style.display = 'none'
      mainChart.unsubscribeCrosshairMove(handleCrosshair)
      ro.disconnect()
      mainChart.remove()
      mainChartRef.current = null
      candleRef.current    = null
      volumeRef.current    = null
    }
  }, [symbol, timeframe, isDaily])

  // ── MACD sub-chart (independent of main chart lifecycle) ─────────────────────
  useEffect(() => {
    if (!showMacd) {
      if (macdChartRef.current) { macdChartRef.current.remove(); macdChartRef.current = null }
      return
    }
    const macdEl = macdRef.current
    if (!macdEl) return

    const timeFmt  = makeTimeFmt(isDaily)
    const macdChart = createChart(macdEl, {
      ...SUB_BASE, width: macdEl.clientWidth, height: macdEl.clientHeight,
      localization: { timeFormatter: timeFmt },
    })
    removeAttribution(macdEl)
    macdChartRef.current = macdChart

    const syncHandler = (range) => { if (range) macdChart.timeScale().setVisibleLogicalRange(range) }
    mainChartRef.current?.timeScale().subscribeVisibleLogicalRangeChange(syncHandler)

    const ro = new ResizeObserver(() => {
      macdChart.applyOptions({ width: macdEl.clientWidth, height: macdEl.clientHeight })
    })
    ro.observe(macdEl)

    return () => {
      mainChartRef.current?.timeScale().unsubscribeVisibleLogicalRangeChange(syncHandler)
      ro.disconnect()
      macdChart.remove()
      macdChartRef.current = null
    }
  }, [showMacd, symbol, timeframe, isDaily])

  // ── OSC sub-chart (RSI / Stoch) ──────────────────────────────────────────────
  useEffect(() => {
    if (!showOsc) {
      if (oscChartRef.current) { oscChartRef.current.remove(); oscChartRef.current = null }
      return
    }
    const oscEl = oscRef.current
    if (!oscEl) return

    const timeFmt = makeTimeFmt(isDaily)
    const oscChart = createChart(oscEl, {
      ...SUB_BASE, width: oscEl.clientWidth, height: oscEl.clientHeight,
      localization: { timeFormatter: timeFmt },
    })
    removeAttribution(oscEl)
    oscChartRef.current = oscChart

    const syncHandler = (range) => { if (range) oscChart.timeScale().setVisibleLogicalRange(range) }
    mainChartRef.current?.timeScale().subscribeVisibleLogicalRangeChange(syncHandler)

    const ro = new ResizeObserver(() => {
      oscChart.applyOptions({ width: oscEl.clientWidth, height: oscEl.clientHeight })
    })
    ro.observe(oscEl)

    return () => {
      mainChartRef.current?.timeScale().unsubscribeVisibleLogicalRangeChange(syncHandler)
      ro.disconnect()
      oscChart.remove()
      oscChartRef.current = null
    }
  }, [showOsc, symbol, timeframe, isDaily])

  // ── Live bar updates via socket ──────────────────────────────────────────────
  useEffect(() => {
    if (!socket) return
    const handler = ({ symbol: s, bar }) => {
      if (s !== symbol) return
      candleRef.current?.update(bar)
      volumeRef.current?.update({
        time: bar.time, value: bar.volume,
        color: bar.close >= bar.open ? 'rgba(38,217,127,0.25)' : 'rgba(255,77,77,0.25)',
      })
    }
    socket.on('bar', handler)
    return () => socket.off('bar', handler)
  }, [socket, symbol])

  // ── Overlays + indicator data ────────────────────────────────────────────────
  useEffect(() => {
    const mainChart = mainChartRef.current
    const candle    = candleRef.current
    if (!mainChart) return

    function clearAll() {
      const mc   = mainChartRef.current
      const macd = macdChartRef.current
      const osc  = oscChartRef.current
      Object.values(namedSeries.current).forEach(s => {
        try { mc?.removeSeries(s)   } catch {}
        try { macd?.removeSeries(s) } catch {}
        try { osc?.removeSeries(s)  } catch {}
      })
      priceLinesRef.current.forEach(pl => { try { candleRef.current?.removePriceLine(pl) } catch {} })
      priceLinesRef.current = []
      namedSeries.current   = {}
      setBadges({})
    }

    function setOrCreate(name, chart, mkSeries, data) {
      if (!data?.length || !chart) return
      let s = namedSeries.current[name]
      if (!s) { s = mkSeries(chart); namedSeries.current[name] = s }
      try { s.setData(data) } catch {}
    }

    function applyData(d) {
      const mc   = mainChartRef.current
      const macd = macdChartRef.current
      const osc  = oscChartRef.current
      const cv   = candleRef.current
      const newBadges = {}

      if (overlays.has('SMA20') && d.sma20?.length)
        setOrCreate('sma20', mc, c => c.addLineSeries({ color: '#4ad9ff88', lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false }), d.sma20)

      if (overlays.has('SMA50') && d.sma50?.length)
        setOrCreate('sma50', mc, c => c.addLineSeries({ color: '#ff6a1a88', lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false }), d.sma50)

      if (overlays.has('BB')) {
        const bbOpts = { priceLineVisible: false, lastValueVisible: false }
        setOrCreate('bb_upper',  mc, c => c.addLineSeries({ ...bbOpts, color: 'rgba(245,179,66,0.6)', lineWidth: 1 }), d.bb_upper)
        setOrCreate('bb_lower',  mc, c => c.addLineSeries({ ...bbOpts, color: 'rgba(245,179,66,0.6)', lineWidth: 1 }), d.bb_lower)
        setOrCreate('bb_middle', mc, c => c.addLineSeries({ ...bbOpts, color: 'rgba(245,179,66,0.22)', lineWidth: 1, lineStyle: 2 }), d.bb_middle)
        if (d.bb_position) newBadges.bb = { position: d.bb_position, upper: d.bb_upper_val, lower: d.bb_lower_val }
      }

      if (overlays.has('VWAP') && d.vwap?.length) {
        setOrCreate('vwap', mc, c => c.addLineSeries({ color: 'rgba(255,106,26,0.85)', lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false }), d.vwap)
        newBadges.vwap = { signal: d.vwap_signal, value: d.vwap_value }
      }

      // Proj: only S/R horizontal price lines, no forward path series
      if (overlays.has('Proj') && cv) {
        if (!priceLinesRef.current.length) {
          if (d.support    != null) priceLinesRef.current.push(cv.createPriceLine({ price: d.support,    color: '#3ddc97aa', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'S' }))
          if (d.resistance != null) priceLinesRef.current.push(cv.createPriceLine({ price: d.resistance, color: '#ff476faa', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'R' }))
        }
      }

      if (overlays.has('MACD') && macd) {
        setOrCreate('macd_hist', macd, c => c.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false }), d.macd_hist)
        setOrCreate('macd_line', macd, c => c.addLineSeries({ color: '#4ad9ff', lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false }), d.macd)
        setOrCreate('macd_sig',  macd, c => c.addLineSeries({ color: '#ff6a1a', lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false }), d.macd_signal)
        newBadges.macd = { value: d.macd_value, sigVal: d.macd_signal_value, cross: d.macd_cross }
      }

      if (osc) {
        if (overlays.has('RSI') && d.rsi_series?.length) {
          setOrCreate('rsi', osc, c => {
            const s = c.addLineSeries({ color: '#f5b342', lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false })
            s.createPriceLine({ price: 70, color: 'rgba(255,71,111,0.4)', lineWidth: 1, lineStyle: 3, axisLabelVisible: true })
            s.createPriceLine({ price: 30, color: 'rgba(61,220,151,0.4)', lineWidth: 1, lineStyle: 3, axisLabelVisible: true })
            return s
          }, d.rsi_series)
          newBadges.rsi = { value: d.rsi, signal: d.rsi_signal }
        }
        if (overlays.has('Stoch')) {
          setOrCreate('stoch_k', osc, c => {
            const s = c.addLineSeries({ color: '#4ad9ff', lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false })
            s.createPriceLine({ price: 80, color: 'rgba(255,71,111,0.4)', lineWidth: 1, lineStyle: 3, axisLabelVisible: true })
            s.createPriceLine({ price: 20, color: 'rgba(61,220,151,0.4)', lineWidth: 1, lineStyle: 3, axisLabelVisible: true })
            return s
          }, d.stoch_k)
          setOrCreate('stoch_d', osc, c => c.addLineSeries({ color: '#ff6a1a', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false }), d.stoch_d)
          newBadges.stoch = { k: d.stoch_k_val, d: d.stoch_d_val, signal: d.stoch_signal }
        }
      }

      if (d.volume_signal) newBadges.vol = { ratio: d.volume_ratio, signal: d.volume_signal }
      setBadges(newBadges)
    }

    if (!overlays || overlays.size === 0) { clearAll(); return }

    let cancelled = false
    api.get(`/projection/${symbol}`).then(r => {
      if (cancelled || !mainChartRef.current) return
      clearAll()
      applyData(r.data)
    }).catch(() => { if (!cancelled) clearAll() })

    const overlayInterval = setInterval(() => {
      if (!mainChartRef.current) return
      api.get(`/projection/${symbol}`).then(r => {
        if (!mainChartRef.current) return
        applyData(r.data)
      }).catch(() => {})
    }, 60_000)

    return () => {
      cancelled = true
      clearInterval(overlayInterval)
      clearAll()
    }
  }, [symbol, overlays])

  const rsiColor   = (v) => v >= 70 ? '#ff476f' : v <= 30 ? '#3ddc97' : '#8899aa'
  const macdColor  = (c) => c?.startsWith('bullish') ? '#3ddc97' : '#ff476f'
  const stochColor = (s) => s === 'overbought' ? '#ff476f' : s === 'oversold' ? '#3ddc97' : '#8899aa'
  const bbColor    = (p) => p === 'overbought' ? '#ff476f' : p === 'oversold' ? '#3ddc97' : p === 'squeeze' ? '#f5b342' : '#8899aa'

  const oscLabel = overlays?.has('RSI') && overlays?.has('Stoch') ? 'RSI(14) + Stoch(14,3)'
    : overlays?.has('RSI') ? 'RSI(14)'
    : 'Stoch(14,3)'

  // Disable chart panning while Shift is held for zone drag
  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Shift' && mainChartRef.current) {
      mainChartRef.current.applyOptions({ handleScroll: false })
    }
  }, [])
  const handleKeyUp = useCallback((e) => {
    if (e.key === 'Shift' && mainChartRef.current) {
      mainChartRef.current.applyOptions({ handleScroll: { mouseWheel: true, pressedMouseMove: true } })
      // Snap back to latest tick after drag
      mainChartRef.current.timeScale().scrollToRealTime()
    }
  }, [])

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown)
    window.addEventListener('keyup', handleKeyUp)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('keyup', handleKeyUp)
    }
  }, [handleKeyDown, handleKeyUp])

  return (
    <div className="chart-stack">
      <div
        style={{ position: 'relative', flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}
        onMouseDown={(e) => {
          if (!e.shiftKey) return
          e.preventDefault()
          e.stopPropagation()  // prevent chart from receiving this event
          const rect = e.currentTarget.getBoundingClientRect()
          setDragState({ startX: e.clientX - rect.left, startY: e.clientY - rect.top, endX: e.clientX - rect.left, endY: e.clientY - rect.top })
          setOrderBox(null)
        }}
        onMouseMove={(e) => {
          if (!dragState) return
          e.preventDefault()
          const rect = e.currentTarget.getBoundingClientRect()
          setDragState(prev => ({ ...prev, endX: e.clientX - rect.left, endY: e.clientY - rect.top }))
        }}
        onMouseUp={(e) => {
          if (!dragState) return
          const rect = e.currentTarget.getBoundingClientRect()
          const endX = e.clientX - rect.left
          const endY = e.clientY - rect.top
          setOrderBox({
            topY:  Math.min(dragState.startY, endY),
            botY:  Math.max(dragState.startY, endY),
            leftX: Math.min(dragState.startX, endX),
            rightX: Math.max(dragState.startX, endX),
            show: true,
          })
          setDragState(null)
          // Re-enable scroll and snap to latest tick
          if (mainChartRef.current) {
            mainChartRef.current.applyOptions({ handleScroll: { mouseWheel: true, pressedMouseMove: true } })
            mainChartRef.current.timeScale().scrollToRealTime()
          }
        }}
        onMouseLeave={() => {
          if (dragState) {
            setDragState(null)
            if (mainChartRef.current) {
              mainChartRef.current.applyOptions({ handleScroll: { mouseWheel: true, pressedMouseMove: true } })
            }
          }
        }}
      >
        <div ref={mainRef} className="chart-main" />
        <div ref={tooltipEl} className="chart-tooltip" />

        {/* Drag selection overlay */}
        {dragState && (
          <div style={{
            position: 'absolute',
            left:   Math.min(dragState.startX, dragState.endX),
            top:    Math.min(dragState.startY, dragState.endY),
            width:  Math.abs(dragState.endX - dragState.startX),
            height: Math.abs(dragState.endY - dragState.startY),
            border: '1px dashed rgba(74,217,255,0.6)',
            background: 'rgba(74,217,255,0.08)',
            pointerEvents: 'none',
            zIndex: 10,
          }} />
        )}

        {/* Order box after drag */}
        {orderBox?.show && (() => {
          const zoneHeight = orderBox.botY - orderBox.topY
          const targetPrice = midPrice ? midPrice * (1 + zoneHeight / 400) : null
          const stopPrice   = midPrice ? midPrice * (1 - zoneHeight / 400) : null
          return (
            <div style={{
              position: 'absolute',
              right: 16, top: orderBox.topY,
              background: '#0e1320', border: '1px solid rgba(74,217,255,0.3)',
              borderRadius: 8, padding: '10px 12px', zIndex: 20, minWidth: 200,
              boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
            }}>
              <div style={{ fontSize: 9, color: '#4ad9ff', letterSpacing: '0.08em', marginBottom: 8 }}>
                ZONE SELECTED
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: 9, color: 'var(--t-4)' }}>Top (target)</span>
                  <span style={{ fontSize: 10, color: 'var(--ok)', fontFamily: 'var(--font-mono)' }}>
                    {targetPrice ? `$${targetPrice.toFixed(2)}` : '—'}
                  </span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: 9, color: 'var(--t-4)' }}>Bottom (stop)</span>
                  <span style={{ fontSize: 10, color: 'var(--err)', fontFamily: 'var(--font-mono)' }}>
                    {stopPrice ? `$${stopPrice.toFixed(2)}` : '—'}
                  </span>
                </div>
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                <button
                  onClick={() => setOrderBox(null)}
                  style={{ flex: 1, background: 'rgba(61,220,151,0.15)', border: '1px solid rgba(61,220,151,0.3)', color: '#3ddc97', borderRadius: 4, padding: '5px 0', fontSize: 10, cursor: 'pointer' }}
                >
                  LONG
                </button>
                <button
                  onClick={() => setOrderBox(null)}
                  style={{ flex: 1, background: 'rgba(255,71,111,0.15)', border: '1px solid rgba(255,71,111,0.3)', color: '#ff476f', borderRadius: 4, padding: '5px 0', fontSize: 10, cursor: 'pointer' }}
                >
                  SHORT
                </button>
                <button
                  onClick={() => setOrderBox(null)}
                  style={{ background: 'none', border: '1px solid rgba(140,170,220,0.2)', color: 'var(--t-4)', borderRadius: 4, padding: '5px 8px', fontSize: 10, cursor: 'pointer' }}
                >
                  ✕
                </button>
              </div>
              <div style={{ fontSize: 8, color: 'var(--t-4)', marginTop: 6, lineHeight: 1.4 }}>
                Shift+drag to select zone. Prices are approximate.
              </div>
            </div>
          )
        })()}

        {/* Hint label */}
        <div style={{ position: 'absolute', bottom: 40, right: 16, fontSize: 8, color: 'rgba(140,170,220,0.3)', pointerEvents: 'none' }}>
          Shift+drag to set trade zone
        </div>
      </div>

      {showMacd && (
        <div className="chart-sub chart-sub-macd">
          <span className="chart-sub-label">MACD (12,26,9)</span>
          <div ref={macdRef} style={{ width: '100%', height: '100%' }} />
        </div>
      )}

      {showOsc && (
        <div className="chart-sub chart-sub-osc">
          <span className="chart-sub-label">{oscLabel}</span>
          <div ref={oscRef} style={{ width: '100%', height: '100%' }} />
        </div>
      )}

      {lastUpdated && (
        <div style={{ display: 'flex', alignItems: 'center', padding: '2px 8px 4px' }}>
          <span style={{
            display: 'inline-block', width: '6px', height: '6px', borderRadius: '50%',
            background: refreshFlash ? '#3ddc97' : 'rgba(61,220,151,0.25)',
            transition: 'background 0.3s ease', marginRight: '6px', flexShrink: 0,
          }} />
          <span style={{ fontSize: '10px', color: 'rgba(140,170,220,0.45)', fontFamily: 'var(--font-mono)' }}>
            Updated {lastUpdated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </span>
        </div>
      )}

      {Object.keys(badges).length > 0 && (
        <div className="chart-badges">
          {badges.rsi && (
            <div className="chart-badge" style={{ borderColor: rsiColor(badges.rsi.value), color: rsiColor(badges.rsi.value) }}>
              RSI {badges.rsi.value.toFixed(1)} <span className="badge-sub">{badges.rsi.signal}</span>
            </div>
          )}
          {badges.macd && (
            <div className="chart-badge" style={{ borderColor: macdColor(badges.macd.cross), color: macdColor(badges.macd.cross) }}>
              MACD {badges.macd.value > 0 ? '+' : ''}{badges.macd.value?.toFixed(3)} <span className="badge-sub">{badges.macd.cross?.replace('_', ' ')}</span>
            </div>
          )}
          {badges.stoch && (
            <div className="chart-badge" style={{ borderColor: stochColor(badges.stoch.signal), color: stochColor(badges.stoch.signal) }}>
              Stoch K:{badges.stoch.k?.toFixed(1)} D:{badges.stoch.d?.toFixed(1)} <span className="badge-sub">{badges.stoch.signal}</span>
            </div>
          )}
          {badges.bb && (
            <div className="chart-badge" style={{ borderColor: bbColor(badges.bb.position), color: bbColor(badges.bb.position) }}>
              BB <span className="badge-sub">{badges.bb.position?.replace('_', ' ')}</span>
            </div>
          )}
          {badges.vwap && (
            <div className="chart-badge" style={{ borderColor: badges.vwap.signal === 'above' ? '#3ddc97' : '#ff476f', color: badges.vwap.signal === 'above' ? '#3ddc97' : '#ff476f' }}>
              VWAP ${badges.vwap.value?.toFixed(2)} <span className="badge-sub">{badges.vwap.signal}</span>
            </div>
          )}
          {badges.vol && (
            <div className="chart-badge" style={{
              borderColor: badges.vol.signal === 'high_up' ? '#3ddc97' : badges.vol.signal === 'high_down' ? '#ff476f' : badges.vol.signal === 'low' ? '#f5b342' : '#475061',
              color:       badges.vol.signal === 'high_up' ? '#3ddc97' : badges.vol.signal === 'high_down' ? '#ff476f' : badges.vol.signal === 'low' ? '#f5b342' : '#475061',
            }}>
              Vol {badges.vol.ratio?.toFixed(1)}× <span className="badge-sub">{badges.vol.signal?.replace('_', ' ')}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

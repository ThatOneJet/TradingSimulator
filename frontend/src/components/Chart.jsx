import { useEffect, useRef, useState } from 'react'
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
  // t can be a unix timestamp (number) or date string "YYYY-MM-DD"
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

export default function Chart({ symbol, timeframe, socket, overlays }) {
  const mainRef = useRef()
  const macdRef = useRef()
  const oscRef  = useRef()
  const tooltipEl = useRef()

  const mainChartRef  = useRef()
  const candleRef     = useRef()
  const volumeRef     = useRef()
  const macdChartRef  = useRef()
  const oscChartRef   = useRef()
  const namedSeries   = useRef({})
  const priceLinesRef = useRef([])

  const [badges, setBadges] = useState({})

  const showMacd = !!overlays?.has('MACD')
  const showOsc  = !!(overlays?.has('RSI') || overlays?.has('Stoch'))

  const isDaily = !['1Min', '5Min', '15Min', '1Hour'].includes(timeframe)

  // ── Main chart lifecycle ──────────────────────────────────────────────────────
  useEffect(() => {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone
    const timeFmt = (t) => {
      const d = new Date(t * 1000)
      return isDaily
        ? d.toLocaleDateString('en-US', { timeZone: tz, month: 'short', day: 'numeric', year: 'numeric' })
        : d.toLocaleTimeString('en-US', { timeZone: tz, hour: 'numeric', minute: '2-digit', hour12: true })
    }

    const mainEl = mainRef.current
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

    // ── Custom OHLC tooltip ──
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
      const upC    = '#26d97f', dnC = '#ff4d4d'
      const cc     = isUp ? upC : dnC

      tip.style.display  = 'flex'
      tip.style.left     = (flip ? x - tipW - 10 : x + 14) + 'px'

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

    // ── Bars fetch + 60s refresh ──
    const loadBars = () => {
      api.get(`/bars/${symbol}?timeframe=${timeframe}&limit=300`).then(r => {
        candle.setData(r.data)
        volume.setData(r.data.map(b => ({
          time: b.time, value: b.volume,
          color: b.close >= b.open ? 'rgba(38,217,127,0.25)' : 'rgba(255,77,77,0.25)',
        })))
      }).catch(() => {})
    }
    loadBars()
    const barInterval = setInterval(loadBars, 60_000)

    // ── MACD sub-chart ──
    let macdChart = null
    const macdEl = macdRef.current
    if (showMacd && macdEl) {
      macdChart = createChart(macdEl, { ...SUB_BASE, width: macdEl.clientWidth, height: macdEl.clientHeight, localization: { timeFormatter: timeFmt } })
      removeAttribution(macdEl)
      macdChartRef.current = macdChart
    } else {
      macdChartRef.current = null
    }

    // ── Oscillator sub-chart ──
    let oscChart = null
    const oscEl = oscRef.current
    if (showOsc && oscEl) {
      oscChart = createChart(oscEl, { ...SUB_BASE, width: oscEl.clientWidth, height: oscEl.clientHeight, localization: { timeFormatter: timeFmt } })
      removeAttribution(oscEl)
      oscChartRef.current = oscChart
    } else {
      oscChartRef.current = null
    }

    const syncRange = (range) => {
      if (!range) return
      macdChart?.timeScale().setVisibleLogicalRange(range)
      oscChart?.timeScale().setVisibleLogicalRange(range)
    }
    mainChart.timeScale().subscribeVisibleLogicalRangeChange(syncRange)

    const ro = new ResizeObserver(() => {
      mainChart.applyOptions({ width: mainEl.clientWidth, height: mainEl.clientHeight })
      if (macdChart && macdEl) macdChart.applyOptions({ width: macdEl.clientWidth, height: macdEl.clientHeight })
      if (oscChart  && oscEl)  oscChart.applyOptions( { width: oscEl.clientWidth,  height: oscEl.clientHeight  })
    })
    ro.observe(mainEl)
    if (macdEl) ro.observe(macdEl)
    if (oscEl)  ro.observe(oscEl)

    return () => {
      clearInterval(barInterval)
      if (tip) tip.style.display = 'none'
      mainChart.unsubscribeCrosshairMove(handleCrosshair)
      mainChart.timeScale().unsubscribeVisibleLogicalRangeChange(syncRange)
      ro.disconnect()
      mainChart.remove()
      macdChart?.remove()
      oscChart?.remove()
    }
  }, [symbol, timeframe, showMacd, showOsc, isDaily])

  // ── Live bar updates via socket ──
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

  // ── Overlays + indicator data ──
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
      priceLinesRef.current.forEach(pl => { try { candle?.removePriceLine(pl) } catch {} })
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

    function applyData(d, creating) {
      const mc   = mainChartRef.current
      const macd = macdChartRef.current
      const osc  = oscChartRef.current
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

      if (overlays.has('Proj')) {
        setOrCreate('proj', mc, c => c.addLineSeries({ color: 'rgba(255,255,255,0.22)', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false }), d.projection)
        if (creating && candle) {
          priceLinesRef.current.forEach(pl => { try { candle.removePriceLine(pl) } catch {} })
          priceLinesRef.current = []
          if (d.support    != null) priceLinesRef.current.push(candle.createPriceLine({ price: d.support,    color: '#3ddc97aa', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'S' }))
          if (d.resistance != null) priceLinesRef.current.push(candle.createPriceLine({ price: d.resistance, color: '#ff476faa', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'R' }))
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
    const fetchOverlays = (creating) => {
      api.get(`/projection/${symbol}`).then(r => {
        if (cancelled || !mainChartRef.current) return
        if (creating) clearAll()
        applyData(r.data, creating)
      }).catch(() => { if (!cancelled && creating) clearAll() })
    }

    fetchOverlays(true)
    const overlayInterval = setInterval(() => fetchOverlays(false), 60_000)

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

  return (
    <div className="chart-stack">
      {/* Main chart + tooltip overlay */}
      <div style={{ position: 'relative', flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        <div ref={mainRef} className="chart-main" />
        <div ref={tooltipEl} className="chart-tooltip" />
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

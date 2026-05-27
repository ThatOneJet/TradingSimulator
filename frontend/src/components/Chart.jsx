import { useEffect, useRef, useState } from 'react'
import { createChart } from 'lightweight-charts'
import api from '../api.js'

export default function Chart({ symbol, timeframe, socket, overlays }) {
  const containerRef     = useRef()
  const chartRef         = useRef()
  const candleRef        = useRef()
  const volumeRef        = useRef()
  const overlaySeriesRef = useRef([])
  const priceLineRef     = useRef([])
  const rsiDataRef       = useRef(null)

  const [rsiBadge, setRsiBadge] = useState(null) // { value, signal }

  useEffect(() => {
    const isDaily = !['1Min','5Min','15Min','1Hour'].includes(timeframe)
    const tz      = Intl.DateTimeFormat().resolvedOptions().timeZone

    const chart = createChart(containerRef.current, {
      width:  containerRef.current.clientWidth,
      height: containerRef.current.clientHeight || 340,
      layout: { background: { color: '#0d1119' }, textColor: '#8899aa' },
      grid:   { vertLines: { color: '#1a2234' }, horzLines: { color: '#1a2234' } },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: '#1e2940' },
      timeScale: { borderColor: '#1e2940', timeVisible: true, secondsVisible: false },
      watermark: { visible: false },
      localization: {
        timeFormatter: (t) => {
          const d = new Date(t * 1000)
          if (isDaily) {
            return d.toLocaleDateString('en-US', { timeZone: tz, month: 'short', day: 'numeric', year: 'numeric' })
          }
          return d.toLocaleTimeString('en-US', { timeZone: tz, hour: 'numeric', minute: '2-digit', hour12: true })
        },
      },
    })

    // Remove TradingView attribution link
    setTimeout(() => {
      containerRef.current
        ?.querySelectorAll('a[href*="tradingview"], a[target="_blank"]')
        .forEach(a => a.remove())
    }, 50)

    const candle = chart.addCandlestickSeries({
      upColor:         '#26d97f',
      downColor:       '#ff4d4d',
      borderUpColor:   '#26d97f',
      borderDownColor: '#ff4d4d',
      wickUpColor:     '#26d97f',
      wickDownColor:   '#ff4d4d',
    })

    const volume = chart.addHistogramSeries({
      priceFormat:  { type: 'volume' },
      priceScaleId: 'vol',
      scaleMargins: { top: 0.8, bottom: 0 },
    })
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } })

    chartRef.current  = chart
    candleRef.current = candle
    volumeRef.current = volume

    api.get(`/bars/${symbol}?timeframe=${timeframe}&limit=300`)
      .then(r => {
        candle.setData(r.data)
        volume.setData(r.data.map(b => ({
          time:  b.time,
          value: b.volume,
          color: b.close >= b.open ? '#26d97f44' : '#ff4d4d44',
        })))
      })

    const ro = new ResizeObserver(() => {
      if (!containerRef.current) return
      chart.applyOptions({
        width:  containerRef.current.clientWidth,
        height: containerRef.current.clientHeight,
      })
    })
    ro.observe(containerRef.current)

    return () => { ro.disconnect(); chart.remove() }
  }, [symbol, timeframe])

  useEffect(() => {
    if (!socket || !candleRef.current) return
    const handler = ({ symbol: s, bar }) => {
      if (s === symbol) {
        candleRef.current.update(bar)
        volumeRef.current.update({ time: bar.time, value: bar.volume, color: bar.close >= bar.open ? '#26d97f44' : '#ff4d4d44' })
      }
    }
    socket.on('bar', handler)
    return () => socket.off('bar', handler)
  }, [socket, symbol])

  // Overlay effect — depends on symbol and overlays
  useEffect(() => {
    // Cleanup helper: remove all tracked overlay series and price lines
    const removeOverlays = () => {
      const chart  = chartRef.current
      const candle = candleRef.current
      if (chart) {
        overlaySeriesRef.current.forEach(s => {
          try { chart.removeSeries(s) } catch {}
        })
      }
      overlaySeriesRef.current = []
      if (candle) {
        priceLineRef.current.forEach(pl => {
          try { candle.removePriceLine(pl) } catch {}
        })
      }
      priceLineRef.current = []
      rsiDataRef.current = null
      setRsiBadge(null)
    }

    // Nothing to do if chart not ready or no overlays requested
    if (!chartRef.current || !overlays || overlays.size === 0) {
      removeOverlays()
      return
    }

    let cancelled = false

    api.get(`/projection/${symbol}`)
      .then(r => {
        if (cancelled) return
        const data  = r.data
        const chart = chartRef.current
        const candle = candleRef.current
        if (!chart) return

        const newSeries = []
        const newLines  = []

        if (overlays.has('SMA20') && data.sma20?.length) {
          const s = chart.addLineSeries({
            color: '#4ad9ff',
            lineWidth: 1,
            priceLineVisible: false,
            lastValueVisible: false,
          })
          s.setData(data.sma20)
          newSeries.push(s)
        }

        if (overlays.has('SMA50') && data.sma50?.length) {
          const s = chart.addLineSeries({
            color: '#ff6a1a',
            lineWidth: 1,
            priceLineVisible: false,
            lastValueVisible: false,
          })
          s.setData(data.sma50)
          newSeries.push(s)
        }

        if (overlays.has('Proj')) {
          if (data.projection?.length) {
            const s = chart.addLineSeries({
              color: 'rgba(255,255,255,0.3)',
              lineWidth: 1,
              lineStyle: 2,
              priceLineVisible: false,
              lastValueVisible: false,
            })
            s.setData(data.projection)
            newSeries.push(s)
          }

          // Support / resistance price lines on the candle series
          if (candle && data.support != null) {
            const pl = candle.createPriceLine({
              price: data.support,
              color: '#3ddc97',
              lineWidth: 1,
              lineStyle: 2,
              axisLabelVisible: true,
              title: 'S',
            })
            newLines.push(pl)
          }
          if (candle && data.resistance != null) {
            const pl = candle.createPriceLine({
              price: data.resistance,
              color: '#ff476f',
              lineWidth: 1,
              lineStyle: 2,
              axisLabelVisible: true,
              title: 'R',
            })
            newLines.push(pl)
          }
        }

        if (overlays.has('RSI') && data.rsi != null) {
          rsiDataRef.current = { value: data.rsi, signal: data.rsi_signal }
          setRsiBadge({ value: data.rsi, signal: data.rsi_signal })
        }

        overlaySeriesRef.current = newSeries
        priceLineRef.current     = newLines
      })
      .catch(() => {
        if (!cancelled) removeOverlays()
      })

    return () => {
      cancelled = true
      removeOverlays()
    }
  }, [symbol, overlays])

  const rsiBadgeColor =
    rsiBadge?.signal === 'oversold'   ? '#ff476f' :
    rsiBadge?.signal === 'overbought' ? '#f5a623' :
    '#8899aa'

  return (
    <div style={{ position: 'relative', flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div ref={containerRef} className="chart-container" style={{ flex: 1, minHeight: 0 }} />
      {rsiBadge && overlays?.has('RSI') && (
        <div style={{
          position:     'absolute',
          bottom:       8,
          left:         8,
          background:   'rgba(13,17,25,0.75)',
          border:       `1px solid ${rsiBadgeColor}`,
          borderRadius: 4,
          padding:      '2px 7px',
          fontSize:     11,
          color:        rsiBadgeColor,
          pointerEvents: 'none',
          zIndex:       10,
          letterSpacing: '0.02em',
        }}>
          RSI {rsiBadge.value.toFixed(1)} <span style={{ opacity: 0.7 }}>({rsiBadge.signal})</span>
        </div>
      )}
    </div>
  )
}

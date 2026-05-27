import { useEffect, useRef } from 'react'
import { createChart } from 'lightweight-charts'
import api from '../api.js'

export default function Chart({ symbol, timeframe, socket }) {
  const containerRef = useRef()
  const chartRef     = useRef()
  const candleRef    = useRef()
  const volumeRef    = useRef()

  useEffect(() => {
    const isDaily = timeframe === '1Day'
    const tz      = Intl.DateTimeFormat().resolvedOptions().timeZone

    const chart = createChart(containerRef.current, {
      width:  containerRef.current.clientWidth,
      height: 340,
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
          return d.toLocaleTimeString('en-US', { timeZone: tz, hour: '2-digit', minute: '2-digit', hour12: false })
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
      chart.applyOptions({ width: containerRef.current.clientWidth })
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

  return <div ref={containerRef} className="chart-container" />
}

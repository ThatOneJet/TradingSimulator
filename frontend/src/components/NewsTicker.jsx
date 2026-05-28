import { useState, useEffect } from 'react'
import api from '../api.js'

function sentimentColor(article) {
  const label = (article.sentiment_label || '').toLowerCase()
  if (label === 'bullish' || label === 'somewhat bullish') return 'var(--ok)'
  if (label === 'bearish' || label === 'somewhat bearish') return 'var(--err)'
  return 'var(--t-2)'
}

function truncate(str, max) {
  if (!str) return ''
  return str.length > max ? str.slice(0, max) + '…' : str
}

function PricePill({ item, onSelect }) {
  const up = item.change_pct >= 0
  return (
    <span
      onClick={() => onSelect?.(item.symbol)}
      style={{
        display:    'inline-flex',
        alignItems: 'center',
        gap:        5,
        marginRight: 20,
        flexShrink: 0,
        cursor: onSelect ? 'pointer' : 'default',
      }}
    >
      <span style={{ color: 'var(--acc)', fontSize: 10, fontFamily: 'var(--font-mono)', letterSpacing: '0.05em', fontWeight: 700 }}>
        {item.symbol}
      </span>
      <span style={{ color: item.change_pct >= 0 ? 'var(--ok)' : 'var(--err)', fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 600 }}>
        ${item.price != null ? Number(item.price).toFixed(2) : '—'}
      </span>
      {item.change_pct != null && (
        <span style={{
          fontSize: 9, fontFamily: 'var(--font-mono)',
          color: up ? 'var(--ok)' : 'var(--err)',
        }}>
          {up ? '▲' : '▼'}{Math.abs(item.change_pct).toFixed(2)}%
        </span>
      )}
      <span style={{ color: 'var(--hairline-3)', marginLeft: 4 }}>|</span>
    </span>
  )
}

export default function NewsTicker({ onSelectSymbol }) {
  const [prices,   setPrices]   = useState([])
  const [articles, setArticles] = useState([])

  async function loadPrices() {
    try {
      const res = await api.get('/market-prices')
      setPrices(res.data || [])
    } catch {}
  }

  async function loadNews() {
    try {
      const res = await api.get('/news/general')
      setArticles((res.data || []).slice(0, 30))
    } catch {}
  }

  useEffect(() => {
    loadPrices()
    loadNews()
    const priceTimer = setInterval(loadPrices, 30 * 1000)
    const newsTimer  = setInterval(loadNews,   5 * 60 * 1000)
    return () => { clearInterval(priceTimer); clearInterval(newsTimer) }
  }, [])

  if (prices.length === 0 && articles.length === 0) return null

  const priceContent = prices.map((p, i) => <PricePill key={i} item={p} onSelect={onSelectSymbol} />)

  const newsContent = articles.map((a, i) => (
    <span key={i} style={{ marginRight: 28, flexShrink: 0, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      {a.source && (
        <span style={{ fontSize: 8, fontFamily: 'var(--font-mono)', color: 'var(--acc)', fontWeight: 700, letterSpacing: '0.05em', opacity: 0.8, flexShrink: 0 }}>
          {a.source.toUpperCase().slice(0, 10)}
        </span>
      )}
      <span style={{ color: sentimentColor(a), fontSize: 10 }}>{truncate(a.title, 80)}</span>
      <span style={{ color: 'var(--hairline-3)', marginLeft: 4 }}>|</span>
    </span>
  ))

  const content = [...priceContent, ...newsContent]

  return (
    <div className="ticker-outer">
      <div className="ticker-live-badge">
        <span className="ticker-dot" />
        MKT
      </div>
      <div className="ticker-track">
        <div className="ticker-inner">
          {content}{content}
        </div>
      </div>
    </div>
  )
}

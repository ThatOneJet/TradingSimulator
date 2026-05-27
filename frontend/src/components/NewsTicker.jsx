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

export default function NewsTicker() {
  const [articles, setArticles] = useState([])

  async function load() {
    try {
      const res = await api.get('/news/general')
      setArticles((res.data || []).slice(0, 10))
    } catch {
      // silently ignore — don't show broken ticker
    }
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 5 * 60 * 1000)
    return () => clearInterval(id)
  }, [])

  // Don't render until we have data
  if (articles.length === 0) return null

  const content = articles.map((a, i) => (
    <span key={i}>
      <span style={{ color: sentimentColor(a) }}>{truncate(a.title, 80)}</span>
      <span style={{ color: 'var(--t-4)', margin: '0 14px' }}>·</span>
    </span>
  ))

  return (
    <div className="ticker-outer">
      <div className="ticker-live-badge">
        <span className="ticker-dot" />
        LIVE
      </div>
      <div className="ticker-track">
        <div className="ticker-inner">
          {content}{content}
        </div>
      </div>
    </div>
  )
}

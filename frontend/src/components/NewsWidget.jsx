import { useState, useEffect, useCallback } from 'react'
import api from '../api.js'

// Convert Alpha Vantage timestamp '20240115T130000' to relative time string
function relTime(published) {
  if (!published) return ''
  // Parse YYYYMMDDTHHMMSS
  const s = String(published)
  const year  = parseInt(s.slice(0, 4),  10)
  const month = parseInt(s.slice(4, 6),  10) - 1
  const day   = parseInt(s.slice(6, 8),  10)
  const hour  = parseInt(s.slice(9, 11), 10)
  const min   = parseInt(s.slice(11,13), 10)
  const sec   = parseInt(s.slice(13,15), 10)
  const date  = new Date(year, month, day, hour, min, sec)
  const diffMs = Date.now() - date.getTime()
  if (isNaN(diffMs) || diffMs < 0) return ''
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1)   return 'just now'
  if (diffMin < 60)  return `${diffMin} min ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24)   return `${diffHr}h ago`
  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 30)  return `${diffDay}d ago`
  const diffMo = Math.floor(diffDay / 30)
  return `${diffMo}mo ago`
}

// Map sentiment_label → CSS color variable string
function sentimentColor(label) {
  if (!label) return 'var(--t-3)'
  const l = label.toLowerCase()
  if (l === 'bullish' || l === 'somewhat bullish') return 'var(--ok)'
  if (l === 'bearish' || l === 'somewhat bearish') return 'var(--err)'
  return 'var(--t-3)'
}

const GENERAL_TOPICS = ['technology', 'finance', 'earnings', 'macro']

export default function NewsWidget({ symbol }) {
  const [mode,        setMode]        = useState('symbol') // 'symbol' | 'all'
  const [articles,    setArticles]    = useState([])
  const [loading,     setLoading]     = useState(false)
  const [spinning,    setSpinning]    = useState(false)
  const [lastUpdated, setLastUpdated] = useState(null) // Date object

  const load = useCallback(async () => {
    setLoading(true)
    try {
      let res
      if (mode === 'symbol' && symbol) {
        res = await api.get(`/news/${symbol}`)
      } else {
        res = await api.get('/news/general', { params: { topic: 'finance' } })
      }
      setArticles((res.data || []).slice(0, 5))
      setLastUpdated(new Date())
    } catch {
      setArticles([])
    } finally {
      setLoading(false)
    }
  }, [mode, symbol])

  // Auto-refresh every 5 minutes
  useEffect(() => {
    load()
    const id = setInterval(load, 5 * 60 * 1000)
    return () => clearInterval(id)
  }, [load])

  // Manual refresh with brief spin animation
  async function handleRefresh() {
    setSpinning(true)
    await load()
    setTimeout(() => setSpinning(false), 600)
  }

  // "Updated X min ago" helper
  function updatedAgo() {
    if (!lastUpdated) return ''
    const diff = Math.floor((Date.now() - lastUpdated.getTime()) / 60000)
    if (diff < 1) return 'Updated just now'
    return `Updated ${diff} min ago`
  }

  return (
    <div className="widget" style={{ padding: '12px 14px' }}>
      {/* Header row */}
      <div className="widget-hd" style={{ marginBottom: 10, justifyContent: 'space-between' }}>
        <span>Market News</span>
        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          {/* Manual refresh button */}
          <button
            onClick={handleRefresh}
            title="Refresh news"
            style={{
              background:   'transparent',
              border:       'none',
              color:        'var(--t-3)',
              cursor:       'pointer',
              fontSize:     13,
              lineHeight:   1,
              padding:      '1px 4px',
              display:      'flex',
              alignItems:   'center',
              transform:    spinning ? 'rotate(360deg)' : 'rotate(0deg)',
              transition:   'transform .6s ease, color .15s',
            }}
          >
            ↻
          </button>
          <button
            onClick={() => setMode('symbol')}
            style={{
              background:    mode === 'symbol' ? 'var(--acc-soft)' : 'transparent',
              border:        `1px solid ${mode === 'symbol' ? 'var(--acc-line)' : 'var(--hairline-2)'}`,
              borderRadius:  4,
              color:         mode === 'symbol' ? 'var(--acc)' : 'var(--t-3)',
              cursor:        'pointer',
              fontSize:      10,
              fontFamily:    'var(--font-mono)',
              fontWeight:    600,
              letterSpacing: '0.05em',
              padding:       '2px 6px',
              transition:    'all .15s',
            }}
          >
            {symbol || '—'}
          </button>
          <button
            onClick={() => setMode('all')}
            style={{
              background:    mode === 'all' ? 'var(--acc-soft)' : 'transparent',
              border:        `1px solid ${mode === 'all' ? 'var(--acc-line)' : 'var(--hairline-2)'}`,
              borderRadius:  4,
              color:         mode === 'all' ? 'var(--acc)' : 'var(--t-3)',
              cursor:        'pointer',
              fontSize:      10,
              fontFamily:    'var(--font-mono)',
              fontWeight:    600,
              letterSpacing: '0.05em',
              padding:       '2px 6px',
              transition:    'all .15s',
            }}
          >
            ALL
          </button>
        </div>
      </div>

      {/* Article list */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
        {loading && (
          <div style={{ color: 'var(--t-3)', fontSize: 11, padding: '8px 0', textAlign: 'center' }}>
            Loading…
          </div>
        )}

        {!loading && articles.length === 0 && (
          <div style={{ color: 'var(--t-3)', fontSize: 11, padding: '8px 0', textAlign: 'center' }}>
            No news available
          </div>
        )}

        {!loading && articles.map((item, i) => (
          <div
            key={i}
            onClick={() => item.url && window.open(item.url, '_blank', 'noopener')}
            style={{
              display:       'flex',
              alignItems:    'flex-start',
              gap:           8,
              padding:       '7px 0',
              borderBottom:  i < articles.length - 1 ? '1px solid var(--hairline)' : 'none',
              cursor:        item.url ? 'pointer' : 'default',
            }}
          >
            {/* Sentiment dot */}
            <span
              style={{
                width:        6,
                height:       6,
                borderRadius: '50%',
                background:   sentimentColor(item.sentiment_label),
                flexShrink:   0,
                marginTop:    4,
              }}
            />

            {/* Text block */}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  fontSize:    12,
                  fontWeight:  500,
                  color:       'var(--t-1)',
                  lineHeight:  1.4,
                  display:     '-webkit-box',
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: 'vertical',
                  overflow:    'hidden',
                }}
              >
                {item.title || 'Untitled'}
              </div>
              <div
                style={{
                  fontSize:    10,
                  color:       'var(--t-3)',
                  marginTop:   2,
                  whiteSpace:  'nowrap',
                  overflow:    'hidden',
                  textOverflow:'ellipsis',
                }}
              >
                {item.source && <span>{item.source}</span>}
                {item.source && item.published && <span> · </span>}
                {item.published && <span>{relTime(item.published)}</span>}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Last updated timestamp */}
      {lastUpdated && !loading && (
        <div style={{
          marginTop:  8,
          fontSize:   9,
          color:      'var(--t-4)',
          textAlign:  'right',
        }}>
          {updatedAgo()}
        </div>
      )}
    </div>
  )
}

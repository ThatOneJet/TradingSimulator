import { useState, useEffect, useCallback, useRef } from 'react'
import api from '../api.js'

// ── Helpers ──────────────────────────────────────────────────────────────────

function relTime(published) {
  if (!published) return ''
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
  if (diffMin < 60)  return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24)   return `${diffHr}h ago`
  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 30)  return `${diffDay}d ago`
  return `${Math.floor(diffDay / 30)}mo ago`
}

function sentimentColor(label) {
  if (!label) return 'var(--t-3)'
  const l = label.toLowerCase()
  if (l === 'bullish' || l === 'somewhat bullish') return 'var(--ok)'
  if (l === 'somewhat bearish' || l === 'bearish') return 'var(--err)'
  return 'var(--t-3)'
}

// Average sentiment_score from article array. Returns null if no data.
function avgScore(articles) {
  if (!articles || articles.length === 0) return null
  const scores = articles
    .map(a => a.sentiment_score)
    .filter(s => s !== null && s !== undefined && !isNaN(Number(s)))
  if (scores.length === 0) return null
  return scores.reduce((a, b) => a + Number(b), 0) / scores.length
}

// Clamp a value between -1 and 1, then map to 0-100% fill for bar
function scoreToBarPct(score) {
  const clamped = Math.max(-1, Math.min(1, score))
  return Math.abs(clamped) * 100
}

function scoreLabel(score) {
  if (score === null || score === undefined) return 'Neutral'
  if (score >  0.35) return 'Bullish'
  if (score >  0.08) return 'Somewhat Bullish'
  if (score < -0.35) return 'Bearish'
  if (score < -0.08) return 'Somewhat Bearish'
  return 'Neutral'
}

// ── Sub-components ────────────────────────────────────────────────────────────

// Gradient placeholder background for articles without a banner image
const GRADIENTS = [
  'linear-gradient(135deg, #1a2030 0%, #0d1119 100%)',
  'linear-gradient(135deg, #1c1a2e 0%, #0d1119 100%)',
  'linear-gradient(135deg, #1a2820 0%, #0d1119 100%)',
  'linear-gradient(135deg, #2a1a18 0%, #0d1119 100%)',
]

function ArticleCard({ item, index }) {
  const [imgError, setImgError] = useState(false)
  const hasBanner = item.banner_image && !imgError

  return (
    <div
      className="widget"
      onClick={() => item.url && window.open(item.url, '_blank', 'noopener')}
      style={{
        cursor:  item.url ? 'pointer' : 'default',
        padding: 0,
        overflow:'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Banner */}
      <div
        style={{
          width:        '100%',
          height:       120,
          flexShrink:   0,
          overflow:     'hidden',
          background:   hasBanner ? 'var(--bg-card-hi)' : GRADIENTS[index % GRADIENTS.length],
          borderRadius: '6px 6px 0 0',
          position:     'relative',
        }}
      >
        {hasBanner && (
          <img
            src={item.banner_image}
            alt=""
            loading="lazy"
            onError={() => setImgError(true)}
            style={{
              objectFit:    'cover',
              borderRadius: '6px 6px 0 0',
              width:        '100%',
              height:       120,
              display:      'block',
            }}
          />
        )}
        {/* Sentiment badge overlay */}
        {item.sentiment_label && (
          <div
            style={{
              position:     'absolute',
              top:           6,
              right:         8,
              background:    'rgba(13,17,25,0.80)',
              border:        `1px solid ${sentimentColor(item.sentiment_label)}`,
              borderRadius:  4,
              color:         sentimentColor(item.sentiment_label),
              fontSize:      9,
              fontWeight:    700,
              letterSpacing: '0.06em',
              padding:       '2px 6px',
              textTransform: 'uppercase',
              backdropFilter:'blur(4px)',
            }}
          >
            {item.sentiment_label}
          </div>
        )}
      </div>

      {/* Text body */}
      <div style={{ padding: '10px 12px 10px', flex: 1, display: 'flex', flexDirection: 'column', gap: 5 }}>
        <div
          style={{
            fontSize:        14,
            fontWeight:      600,
            color:           'var(--t-1)',
            lineHeight:      1.4,
            display:         '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
            overflow:        'hidden',
          }}
        >
          {item.title || 'Untitled'}
        </div>

        {item.summary && (
          <div
            style={{
              fontSize:        11,
              color:           'var(--t-3)',
              lineHeight:      1.5,
              display:         '-webkit-box',
              WebkitLineClamp: 3,
              WebkitBoxOrient: 'vertical',
              overflow:        'hidden',
              flex:            1,
            }}
          >
            {item.summary}
          </div>
        )}

        {/* Source + time footer */}
        <div
          style={{
            display:    'flex',
            alignItems: 'center',
            gap:        6,
            marginTop:  'auto',
            paddingTop: 4,
            borderTop:  '1px solid var(--hairline)',
          }}
        >
          {item.source && (
            <span style={{ fontSize: 10, color: 'var(--t-3)', fontWeight: 500 }}>
              {item.source}
            </span>
          )}
          {item.source && item.published && (
            <span style={{ fontSize: 10, color: 'var(--t-4, var(--t-3))' }}>·</span>
          )}
          {item.published && (
            <span style={{ fontSize: 10, color: 'var(--t-3)', fontFamily: 'var(--font-mono)' }}>
              {relTime(item.published)}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

// Small headline row used in the active-symbol section of the sidebar
function HeadlineRow({ item }) {
  return (
    <div
      onClick={() => item.url && window.open(item.url, '_blank', 'noopener')}
      style={{
        display:    'flex',
        alignItems: 'flex-start',
        gap:        7,
        padding:    '6px 0',
        cursor:     item.url ? 'pointer' : 'default',
        borderBottom: '1px solid var(--hairline)',
      }}
    >
      <span
        style={{
          width:        5,
          height:       5,
          borderRadius: '50%',
          background:   sentimentColor(item.sentiment_label),
          flexShrink:   0,
          marginTop:    5,
        }}
      />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize:        11,
            fontWeight:      500,
            color:           'var(--t-1)',
            lineHeight:      1.4,
            display:         '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
            overflow:        'hidden',
          }}
        >
          {item.title || 'Untitled'}
        </div>
        <div style={{ fontSize: 10, color: 'var(--t-3)', marginTop: 2 }}>
          {item.source && <span>{item.source}</span>}
          {item.source && item.published && <span> · </span>}
          {item.published && <span style={{ fontFamily: 'var(--font-mono)' }}>{relTime(item.published)}</span>}
        </div>
      </div>
    </div>
  )
}

// Animated pulse dot for the live indicator
function PulseDot() {
  return (
    <span style={{ position: 'relative', display: 'inline-flex', width: 8, height: 8, flexShrink: 0 }}>
      <span
        style={{
          position:     'absolute',
          inset:         0,
          borderRadius: '50%',
          background:   'var(--ok)',
          opacity:       0.4,
          animation:    'news-pulse 1.6s ease-in-out infinite',
        }}
      />
      <span
        style={{
          position:     'relative',
          width:        8,
          height:       8,
          borderRadius: '50%',
          background:   'var(--ok)',
          display:      'block',
        }}
      />
      <style>{`
        @keyframes news-pulse {
          0%, 100% { transform: scale(1); opacity: 0.4; }
          50%       { transform: scale(2.2); opacity: 0; }
        }
      `}</style>
    </span>
  )
}

// ── WatchlistSentimentBar ─────────────────────────────────────────────────────
function WatchlistSentimentBar({ sym }) {
  const [score,   setScore]   = useState(null)
  const [label,   setLabel]   = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    api.get(`/news/${sym}`)
      .then(r => {
        if (cancelled) return
        const avg = avgScore(r.data || [])
        setScore(avg)
        setLabel(avg !== null ? scoreLabel(avg) : 'Neutral')
      })
      .catch(() => {
        if (!cancelled) { setScore(null); setLabel('Neutral') }
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [sym])

  const pct      = score !== null ? scoreToBarPct(score) : 0
  const positive = score !== null && score >= 0
  const barColor = score === null
    ? 'var(--t-3)'
    : positive
      ? 'var(--ok)'
      : 'var(--err)'

  return (
    <div
      style={{
        display:    'flex',
        alignItems: 'center',
        gap:        8,
        padding:    '5px 0',
        borderBottom: '1px solid var(--hairline)',
      }}
    >
      {/* Symbol label */}
      <span
        style={{
          fontFamily:  'var(--font-mono)',
          fontSize:    11,
          fontWeight:  600,
          color:       'var(--cy)',
          minWidth:    60,
          flexShrink:  0,
        }}
      >
        {sym}
      </span>

      {/* Bar track */}
      <div
        style={{
          flex:         1,
          height:       6,
          background:   'var(--hairline-2)',
          borderRadius: 3,
          overflow:     'hidden',
          position:     'relative',
        }}
      >
        {!loading && (
          <div
            style={{
              position:     'absolute',
              top:           0,
              bottom:        0,
              left:          positive ? '50%' : `calc(50% - ${pct / 2}%)`,
              width:         `${pct / 2}%`,
              background:    barColor,
              borderRadius:  3,
              // For negative: anchor right side at 50%, extend left
              ...(positive
                ? { left: '50%', width: `${pct / 2}%` }
                : { right: '50%', left: 'unset', width: `${pct / 2}%` }),
            }}
          />
        )}
      </div>

      {/* Score + label */}
      <div
        style={{
          fontFamily:  'var(--font-mono)',
          fontSize:    10,
          color:       loading ? 'var(--t-3)' : barColor,
          minWidth:    110,
          flexShrink:  0,
          textAlign:   'right',
        }}
      >
        {loading
          ? '…'
          : score !== null
            ? `${label} ${score >= 0 ? '+' : ''}${score.toFixed(2)}`
            : 'No data'
        }
      </div>
    </div>
  )
}

// ── Main NewsPage ─────────────────────────────────────────────────────────────

const TABS = [
  { label: 'Tech',     topic: 'technology' },
  { label: 'Markets',  topic: 'finance'    },
  { label: 'Earnings', topic: 'earnings'   },
  { label: 'Macro',    topic: 'macro'      },
]

export default function NewsPage({ symbol, watchlist = [] }) {
  const [activeTab,    setActiveTab]    = useState(0)
  const [articles,     setArticles]     = useState([])
  const [loading,      setLoading]      = useState(false)
  const [symArticles,  setSymArticles]  = useState([])
  const [symLoading,   setSymLoading]   = useState(false)
  const loadedTabRef = useRef(null)

  // Load general news when tab changes
  const loadGeneral = useCallback(async (tabIdx) => {
    if (loadedTabRef.current === tabIdx) return
    loadedTabRef.current = tabIdx
    setLoading(true)
    try {
      const res = await api.get('/news/general', { params: { topic: TABS[tabIdx].topic } })
      setArticles((res.data || []).slice(0, 6))
    } catch {
      setArticles([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadedTabRef.current = null // force reload on tab change
    loadGeneral(activeTab)
  }, [activeTab, loadGeneral])

  // Load active symbol news for sidebar
  useEffect(() => {
    if (!symbol) return
    let cancelled = false
    setSymLoading(true)
    api.get(`/news/${symbol}`)
      .then(r => { if (!cancelled) setSymArticles((r.data || []).slice(0, 3)) })
      .catch(() => { if (!cancelled) setSymArticles([]) })
      .finally(() => { if (!cancelled) setSymLoading(false) })
    return () => { cancelled = true }
  }, [symbol])

  const handleTabClick = (i) => {
    setActiveTab(i)
    loadedTabRef.current = null
  }

  return (
    <div className="ch-body">

      {/* ── Category tabs row ── */}
      <div
        style={{
          display:    'flex',
          alignItems: 'center',
          gap:        6,
          flexShrink: 0,
        }}
      >
        {TABS.map((tab, i) => (
          <button
            key={tab.topic}
            onClick={() => handleTabClick(i)}
            style={{
              background:    activeTab === i ? 'var(--acc)' : 'var(--bg-card)',
              border:        `1px solid ${activeTab === i ? 'var(--acc)' : 'var(--hairline-2)'}`,
              borderRadius:  6,
              color:         activeTab === i ? '#fff' : 'var(--t-2)',
              cursor:        'pointer',
              fontSize:      11,
              fontWeight:    activeTab === i ? 600 : 400,
              padding:       '5px 14px',
              transition:    'all .15s',
              letterSpacing: '0.03em',
            }}
          >
            {tab.label}
          </button>
        ))}

        {/* Spacer + live dot */}
        <div style={{ flex: 1 }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <PulseDot />
          <span style={{ fontSize: 10, color: 'var(--ok)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
            Live
          </span>
        </div>
      </div>

      {/* ── Two-column layout: stories + sidebar ── */}
      <div
        style={{
          display:  'flex',
          gap:      12,
          flex:     1,
          minHeight: 0,
          alignItems: 'flex-start',
        }}
      >

        {/* ── Left: Top Stories grid (60%) ── */}
        <div style={{ flex: '0 0 60%', minWidth: 0 }}>
          <div
            style={{
              fontSize:      10,
              letterSpacing: '0.1em',
              textTransform: 'uppercase',
              color:         'var(--t-3)',
              marginBottom:  8,
              fontWeight:    500,
            }}
          >
            Top Stories — {TABS[activeTab].label}
          </div>

          {loading && (
            <div
              style={{
                color:     'var(--t-3)',
                fontSize:  12,
                padding:   '20px 0',
                textAlign: 'center',
              }}
            >
              Loading news…
            </div>
          )}

          {!loading && articles.length === 0 && (
            <div
              style={{
                color:     'var(--t-3)',
                fontSize:  12,
                padding:   '20px 0',
                textAlign: 'center',
              }}
            >
              No articles available
            </div>
          )}

          {!loading && articles.length > 0 && (
            <div
              style={{
                display:             'grid',
                gridTemplateColumns: '1fr 1fr',
                gap:                 10,
              }}
            >
              {articles.map((item, i) => (
                <ArticleCard key={i} item={item} index={i} />
              ))}
            </div>
          )}
        </div>

        {/* ── Right sidebar (40%) ── */}
        <div
          style={{
            flex:          '0 0 40%',
            minWidth:      0,
            display:       'flex',
            flexDirection: 'column',
            gap:           12,
          }}
        >

          {/* Watchlist Sentiment section */}
          <div className="widget" style={{ padding: '12px 14px' }}>
            <div className="widget-hd" style={{ marginBottom: 8 }}>
              Watchlist Sentiment
            </div>

            {watchlist.length === 0 ? (
              <div style={{ color: 'var(--t-3)', fontSize: 11, padding: '4px 0' }}>
                Add symbols to your watchlist to see sentiment.
              </div>
            ) : (
              <div>
                {watchlist.map(sym => (
                  <WatchlistSentimentBar key={sym} sym={sym} />
                ))}
              </div>
            )}
          </div>

          {/* Active Symbol section */}
          {symbol && (
            <div className="widget" style={{ padding: '12px 14px' }}>
              <div className="widget-hd" style={{ marginBottom: 8 }}>
                <span>Active Symbol</span>
                <span
                  style={{
                    fontFamily:  'var(--font-mono)',
                    fontSize:    11,
                    fontWeight:  700,
                    color:       'var(--cy)',
                    marginLeft:  6,
                    textTransform: 'none',
                    letterSpacing: '0.05em',
                  }}
                >
                  {symbol}
                </span>
              </div>

              {symLoading && (
                <div style={{ color: 'var(--t-3)', fontSize: 11, padding: '6px 0' }}>
                  Loading…
                </div>
              )}

              {!symLoading && symArticles.length === 0 && (
                <div style={{ color: 'var(--t-3)', fontSize: 11, padding: '4px 0' }}>
                  No news available for {symbol}.
                </div>
              )}

              {!symLoading && symArticles.map((item, i) => (
                <HeadlineRow key={i} item={item} />
              ))}
            </div>
          )}

        </div>
      </div>
    </div>
  )
}

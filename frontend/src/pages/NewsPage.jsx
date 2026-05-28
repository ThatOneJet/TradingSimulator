import { useState, useEffect, useCallback, useRef } from 'react'
import api from '../api.js'

// ── Time helpers ─────────────────────────────────────────────────────────────

function relTime(published) {
  if (!published) return ''
  const n = Number(published)
  if (!isNaN(n) && n > 1_000_000_000) {
    const diffMs  = Date.now() - n * 1000
    if (diffMs < 0) return ''
    const diffMin = Math.floor(diffMs / 60_000)
    if (diffMin < 1)   return 'just now'
    if (diffMin < 60)  return `${diffMin}m ago`
    const diffHr = Math.floor(diffMin / 60)
    if (diffHr  < 24)  return `${diffHr}h ago`
    return `${Math.floor(diffHr / 24)}d ago`
  }
  const s = String(published)
  if (s.length < 8) return ''
  const year  = parseInt(s.slice(0, 4),  10)
  const month = parseInt(s.slice(4, 6),  10) - 1
  const day   = parseInt(s.slice(6, 8),  10)
  const hour  = s.length > 9  ? parseInt(s.slice(9, 11),  10) : 0
  const min   = s.length > 11 ? parseInt(s.slice(11, 13), 10) : 0
  const date  = new Date(year, month, day, hour, min)
  const diffMs = Date.now() - date.getTime()
  if (isNaN(diffMs) || diffMs < 0) return ''
  const diffMin = Math.floor(diffMs / 60_000)
  if (diffMin < 1)   return 'just now'
  if (diffMin < 60)  return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr  < 24)  return `${diffHr}h ago`
  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 30)  return `${diffDay}d ago`
  return `${Math.floor(diffDay / 30)}mo ago`
}

function sentimentColor(label) {
  if (!label) return 'var(--t-4)'
  const l = label.toLowerCase()
  if (l === 'bullish' || l === 'somewhat bullish') return 'var(--ok)'
  if (l === 'somewhat bearish' || l === 'bearish') return 'var(--err)'
  return 'var(--t-4)'
}

function avgScore(articles) {
  if (!articles?.length) return null
  const scores = articles.map(a => a.sentiment_score).filter(s => s != null && !isNaN(Number(s)))
  if (!scores.length) return null
  return scores.reduce((a, b) => a + Number(b), 0) / scores.length
}

function scoreLabel(score) {
  if (score == null) return 'Neutral'
  if (score >  0.35) return 'Bullish'
  if (score >  0.08) return 'Somewhat Bullish'
  if (score < -0.35) return 'Bearish'
  if (score < -0.08) return 'Somewhat Bearish'
  return 'Neutral'
}

// ── Horizontal article card ───────────────────────────────────────────────────

const GRADIENTS = [
  'linear-gradient(135deg, #1a2234 0%, #0d1119 100%)',
  'linear-gradient(135deg, #1c1a2e 0%, #0d1119 100%)',
  'linear-gradient(135deg, #1a2820 0%, #0d1119 100%)',
  'linear-gradient(135deg, #2a1a18 0%, #0d1119 100%)',
]

function ArticleCard({ item, index }) {
  const [imgError, setImgError] = useState(false)
  const hasBanner = item.banner_image && !imgError
  const sentColor = sentimentColor(item.sentiment_label)
  const timeStr   = relTime(item.published_at || item.published)

  return (
    <div
      className="news-hcard"
      onClick={() => item.url && window.open(item.url, '_blank', 'noopener')}
    >
      <div className="news-hcard-accent" style={{ background: sentColor }} />
      <div className="news-hcard-thumb">
        {hasBanner ? (
          <img src={item.banner_image} alt="" loading="lazy" onError={() => setImgError(true)} />
        ) : (
          <div style={{ width: '100%', height: '100%', background: GRADIENTS[index % GRADIENTS.length] }} />
        )}
      </div>
      <div className="news-hcard-body">
        <div className="news-hcard-title">{item.title || 'Untitled'}</div>
        {item.summary && <div className="news-hcard-summary">{item.summary}</div>}
        <div className="news-hcard-meta">
          {item.source && <span className="news-hcard-source">{item.source}</span>}
          {item.sentiment_label && item.sentiment_label !== 'Neutral' && (
            <span className="news-hcard-sent" style={{ color: sentColor }}>
              {item.sentiment_label}
            </span>
          )}
          {timeStr && <span className="news-hcard-time">{timeStr}</span>}
        </div>
      </div>
    </div>
  )
}

// ── Animated live dot ─────────────────────────────────────────────────────────

function PulseDot() {
  return (
    <span style={{ position: 'relative', display: 'inline-flex', width: 8, height: 8, flexShrink: 0 }}>
      <span style={{ position: 'absolute', inset: 0, borderRadius: '50%', background: 'var(--ok)', opacity: 0.4, animation: 'news-pulse 1.6s ease-in-out infinite' }} />
      <span style={{ position: 'relative', width: 8, height: 8, borderRadius: '50%', background: 'var(--ok)', display: 'block' }} />
      <style>{`@keyframes news-pulse{0%,100%{transform:scale(1);opacity:.4}50%{transform:scale(2.2);opacity:0}}`}</style>
    </span>
  )
}

// ── Watchlist sentiment bars ──────────────────────────────────────────────────

function SentimentBar({ sym }) {
  const [score,   setScore]   = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    api.get(`/news/${sym}`)
      .then(r => { if (!cancelled) { const avg = avgScore(r.data); setScore(avg) } })
      .catch(() => { if (!cancelled) setScore(null) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [sym])

  const label    = scoreLabel(score)
  const positive = score != null && score >= 0
  const barColor = score == null ? 'var(--t-4)' : positive ? 'var(--ok)' : 'var(--err)'
  const pct      = score != null ? Math.abs(score) * 100 : 0

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 0', borderBottom: '1px solid var(--hairline)' }}>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600, color: 'var(--cy)', minWidth: 52, flexShrink: 0 }}>{sym}</span>
      <div style={{ flex: 1, height: 5, background: 'var(--hairline-2)', borderRadius: 3, overflow: 'hidden', position: 'relative' }}>
        {!loading && (
          <div style={{
            position: 'absolute', top: 0, bottom: 0, borderRadius: 3, background: barColor,
            ...(positive ? { left: '50%', width: `${pct / 2}%` } : { right: '50%', width: `${pct / 2}%` }),
          }} />
        )}
      </div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: loading ? 'var(--t-4)' : barColor, minWidth: 110, textAlign: 'right', flexShrink: 0 }}>
        {loading ? '…' : score != null ? `${label} ${score >= 0 ? '+' : ''}${score.toFixed(2)}` : 'No data'}
      </div>
    </div>
  )
}

// ── Headline row (symbol sidebar) ─────────────────────────────────────────────

function HeadlineRow({ item }) {
  return (
    <div onClick={() => item.url && window.open(item.url, '_blank', 'noopener')}
      style={{ display: 'flex', alignItems: 'flex-start', gap: 7, padding: '6px 0', cursor: item.url ? 'pointer' : 'default', borderBottom: '1px solid var(--hairline)' }}>
      <span style={{ width: 5, height: 5, borderRadius: '50%', background: sentimentColor(item.sentiment_label), flexShrink: 0, marginTop: 5 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 11, fontWeight: 500, color: 'var(--t-1)', lineHeight: 1.4, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
          {item.title || 'Untitled'}
        </div>
        <div style={{ fontSize: 10, color: 'var(--t-3)', marginTop: 2 }}>
          {item.source && <span>{item.source}</span>}
          {item.source && (item.published_at || item.published) && <span> · </span>}
          {(item.published_at || item.published) && <span style={{ fontFamily: 'var(--font-mono)' }}>{relTime(item.published_at || item.published)}</span>}
        </div>
      </div>
    </div>
  )
}

// ── Holdings news feed ────────────────────────────────────────────────────────

function HoldingsNews({ positions }) {
  const [articles, setArticles] = useState([])
  const [loading,  setLoading]  = useState(false)
  const symbols = [...new Set((positions || []).map(p => p.symbol).filter(Boolean))]

  useEffect(() => {
    if (!symbols.length) return
    let cancelled = false
    setLoading(true)
    setArticles([])

    Promise.allSettled(symbols.map(sym => api.get(`/news/${sym}`).then(r => ({ sym, items: r.data || [] }))))
      .then(results => {
        if (cancelled) return
        const seen = new Set()
        const merged = []
        for (const res of results) {
          if (res.status !== 'fulfilled') continue
          const { sym, items } = res.value
          for (const item of items.slice(0, 6)) {
            if (!seen.has(item.title)) {
              seen.add(item.title)
              merged.push({ ...item, _sym: sym })
            }
          }
        }
        // Sort by recency — unix timestamps first, then string timestamps
        merged.sort((a, b) => {
          const ta = Number(a.published_at || a.published) || 0
          const tb = Number(b.published_at || b.published) || 0
          return tb - ta
        })
        setArticles(merged.slice(0, 30))
      })
      .finally(() => { if (!cancelled) setLoading(false) })

    return () => { cancelled = true }
  }, [symbols.join(',')])

  if (!symbols.length) {
    return (
      <div style={{ color: 'var(--t-3)', fontSize: 12, padding: '32px 0', textAlign: 'center' }}>
        You have no open positions. Buy some stocks to see portfolio news here.
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', gap: 12, flex: 1, minHeight: 0, alignItems: 'flex-start' }}>
      <div style={{ flex: '0 0 65%', minWidth: 0 }}>
        <div style={{ fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--t-3)', marginBottom: 10, fontWeight: 500 }}>
          Your Holdings · Latest News
        </div>
        {loading && <div style={{ color: 'var(--t-3)', fontSize: 12, padding: '24px 0', textAlign: 'center' }}>Loading…</div>}
        {!loading && articles.length === 0 && (
          <div style={{ color: 'var(--t-3)', fontSize: 12, padding: '24px 0', textAlign: 'center' }}>No recent news found for your positions.</div>
        )}
        {!loading && articles.length > 0 && (
          <div className="news-article-list">
            {articles.map((item, i) => (
              <div key={i}>
                {i === 0 || item._sym !== articles[i - 1]._sym ? (
                  <div style={{ fontSize: 9, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--cy)', fontFamily: 'var(--font-mono)', fontWeight: 700, margin: '10px 0 4px', opacity: 0.8 }}>
                    {item._sym}
                  </div>
                ) : null}
                <ArticleCard item={item} index={i} />
              </div>
            ))}
          </div>
        )}
      </div>

      <div style={{ flex: '0 0 35%', minWidth: 0 }}>
        <div className="widget" style={{ padding: '12px 14px' }}>
          <div className="widget-hd" style={{ marginBottom: 8 }}>Portfolio Sentiment</div>
          {symbols.map(sym => <SentimentBar key={sym} sym={sym} />)}
        </div>
      </div>
    </div>
  )
}

// ── Main NewsPage ─────────────────────────────────────────────────────────────

const TABS = [
  { label: 'Markets',  topic: 'finance'     },
  { label: 'Tech',     topic: 'technology'  },
  { label: 'Earnings', topic: 'earnings'    },
  { label: 'Macro',    topic: 'macro'       },
  { label: 'Crypto',   topic: 'crypto'      },
]

export default function NewsPage({ symbol, watchlist = [], positions = [] }) {
  const [activeTab,   setActiveTab]   = useState(0)   // index into TABS; -1 = Holdings
  const [articles,    setArticles]    = useState([])
  const [loading,     setLoading]     = useState(false)
  const [symArticles, setSymArticles] = useState([])
  const [symLoading,  setSymLoading]  = useState(false)
  const loadedTabRef = useRef(null)

  const positionSymbols = [...new Set((positions || []).map(p => p.symbol).filter(Boolean))]
  const hasPositions    = positionSymbols.length > 0

  const loadGeneral = useCallback(async (tabIdx) => {
    if (loadedTabRef.current === tabIdx) return
    loadedTabRef.current = tabIdx
    setLoading(true)
    setArticles([])
    try {
      const res = await api.get('/news/general', { params: { topic: TABS[tabIdx].topic } })
      setArticles((res.data || []).slice(0, 25))
    } catch {
      setArticles([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (activeTab < 0) return
    loadedTabRef.current = null
    loadGeneral(activeTab)
  }, [activeTab, loadGeneral])

  useEffect(() => {
    if (!symbol) return
    let cancelled = false
    setSymLoading(true)
    api.get(`/news/${symbol}`)
      .then(r => { if (!cancelled) setSymArticles((r.data || []).slice(0, 8)) })
      .catch(() => { if (!cancelled) setSymArticles([]) })
      .finally(() => { if (!cancelled) setSymLoading(false) })
    return () => { cancelled = true }
  }, [symbol])

  const isHoldings = activeTab === -1

  return (
    <div className="ch-body" style={{ flexDirection: 'column', gap: 10, overflowY: 'auto' }}>

      {/* ── Top bar: filters + live indicator ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0, flexWrap: 'wrap' }}>
        {TABS.map((tab, i) => (
          <button key={tab.topic} onClick={() => { setActiveTab(i); loadedTabRef.current = null }}
            style={{
              background:   activeTab === i ? 'var(--acc)' : 'var(--bg-card)',
              border:       `1px solid ${activeTab === i ? 'var(--acc)' : 'var(--hairline-2)'}`,
              borderRadius: 6, color: activeTab === i ? '#fff' : 'var(--t-2)',
              cursor: 'pointer', fontSize: 11, fontWeight: activeTab === i ? 600 : 400,
              padding: '5px 14px', transition: 'all .15s', letterSpacing: '0.03em',
            }}>
            {tab.label}
          </button>
        ))}

        {/* Holdings tab — only shown when user has positions */}
        {hasPositions && (
          <button onClick={() => setActiveTab(-1)}
            style={{
              background:   isHoldings ? '#2a1f4a' : 'var(--bg-card)',
              border:       `1px solid ${isHoldings ? '#7c4dff' : 'var(--hairline-2)'}`,
              borderRadius: 6, color: isHoldings ? '#b39dff' : 'var(--t-2)',
              cursor: 'pointer', fontSize: 11, fontWeight: isHoldings ? 600 : 400,
              padding: '5px 14px', transition: 'all .15s', letterSpacing: '0.03em',
            }}>
            My Holdings
          </button>
        )}

        <div style={{ flex: 1 }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <PulseDot />
          <span style={{ fontSize: 10, color: 'var(--ok)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>Live</span>
        </div>
      </div>

      {/* ── Holdings view ── */}
      {isHoldings && <HoldingsNews positions={positions} />}

      {/* ── Two-column layout (general tabs) ── */}
      {!isHoldings && (
        <div style={{ display: 'flex', gap: 12, flex: 1, minHeight: 0, alignItems: 'flex-start' }}>

          {/* Article list — 65% */}
          <div style={{ flex: '0 0 65%', minWidth: 0 }}>
            <div style={{ fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--t-3)', marginBottom: 10, fontWeight: 500 }}>
              {TABS[activeTab].label} · Top Stories
            </div>

            {loading && (
              <div style={{ color: 'var(--t-3)', fontSize: 12, padding: '24px 0', textAlign: 'center' }}>
                Loading…
              </div>
            )}

            {!loading && articles.length === 0 && (
              <div style={{ color: 'var(--t-3)', fontSize: 12, padding: '24px 0', textAlign: 'center' }}>
                No articles available — check back soon.
              </div>
            )}

            {!loading && articles.length > 0 && (
              <div className="news-article-list">
                {articles.map((item, i) => <ArticleCard key={i} item={item} index={i} />)}
              </div>
            )}
          </div>

          {/* Sidebar — 35% */}
          <div style={{ flex: '0 0 35%', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 10 }}>

            {/* Symbol headlines */}
            {symbol && (
              <div className="widget" style={{ padding: '12px 14px' }}>
                <div className="widget-hd" style={{ marginBottom: 8 }}>
                  <span>Symbol News</span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700, color: 'var(--cy)', marginLeft: 6, textTransform: 'none' }}>
                    {symbol}
                  </span>
                </div>
                {symLoading ? (
                  <div style={{ color: 'var(--t-3)', fontSize: 11 }}>Loading…</div>
                ) : symArticles.length === 0 ? (
                  <div style={{ color: 'var(--t-3)', fontSize: 11 }}>No news for {symbol}.</div>
                ) : (
                  symArticles.map((item, i) => <HeadlineRow key={i} item={item} />)
                )}
              </div>
            )}

            {/* Watchlist sentiment */}
            <div className="widget" style={{ padding: '12px 14px' }}>
              <div className="widget-hd" style={{ marginBottom: 8 }}>Watchlist Sentiment</div>
              {watchlist.length === 0 ? (
                <div style={{ color: 'var(--t-3)', fontSize: 11, padding: '4px 0' }}>
                  Add symbols to your watchlist to see sentiment.
                </div>
              ) : (
                watchlist.map(sym => <SentimentBar key={sym} sym={sym} />)
              )}
            </div>

          </div>
        </div>
      )}
    </div>
  )
}

import { useState, useEffect, useRef, useCallback } from 'react'
import api from '../api.js'

// ── Time helper ───────────────────────────────────────────────────────────────
// Converts '20240115T130000' → "14 min ago" / "2h ago" / "3d ago"
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
  if (diffMin < 60)  return `${diffMin} min ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24)   return `${diffHr}h ago`
  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 30)  return `${diffDay}d ago`
  const diffMo = Math.floor(diffDay / 30)
  return `${diffMo}mo ago`
}

// ── Sentiment dot color ───────────────────────────────────────────────────────
function sentimentColor(label) {
  if (!label) return 'var(--t-3)'
  const l = label.toLowerCase()
  if (l === 'bullish' || l === 'somewhat bullish') return 'var(--ok)'
  if (l === 'bearish' || l === 'somewhat bearish') return 'var(--err)'
  return 'var(--t-3)'
}

// ── Popular symbols ───────────────────────────────────────────────────────────
const POPULAR = ['AAPL', 'TSLA', 'NVDA', 'SPY', 'MSFT', 'AMZN', 'GOOGL', 'AMD', 'NFLX', 'META']

// ── Main component ────────────────────────────────────────────────────────────
export default function ExplorePage({ onSelectSymbol }) {
  // Search state
  const [query,          setQuery]          = useState('')
  const [searchResults,  setSearchResults]  = useState([])
  const [dropdownOpen,   setDropdownOpen]   = useState(false)
  const [focusedIdx,     setFocusedIdx]     = useState(0)

  // Selected symbol state
  const [selectedSymbol, setSelectedSymbol] = useState(null)
  const [selectedName,   setSelectedName]   = useState('')
  const [selectedExch,   setSelectedExch]   = useState('')

  // Quote state
  const [quote,          setQuote]          = useState(null)
  const [quoteLoading,   setQuoteLoading]   = useState(false)
  const [quoteError,     setQuoteError]     = useState(false)

  // News state
  const [newsItems,      setNewsItems]      = useState([])
  const [newsLoading,    setNewsLoading]    = useState(false)

  // Watchlist button state
  const [addedToWL,      setAddedToWL]      = useState(false)
  const [addingToWL,     setAddingToWL]     = useState(false)

  const debounceRef = useRef(null)
  const wrapRef     = useRef(null)

  // ── Search input handler ──────────────────────────────────────────────────
  function handleQueryChange(e) {
    const q = e.target.value
    setQuery(q)
    clearTimeout(debounceRef.current)
    if (q.length < 1) {
      setSearchResults([])
      setDropdownOpen(false)
      return
    }
    debounceRef.current = setTimeout(async () => {
      try {
        const r = await api.get(`/assets/search?q=${encodeURIComponent(q)}`)
        const results = (r.data || []).slice(0, 8)
        setSearchResults(results)
        setDropdownOpen(results.length > 0)
        setFocusedIdx(0)
      } catch {
        setSearchResults([])
        setDropdownOpen(false)
      }
    }, 300)
  }

  function handleKeyDown(e) {
    if (!dropdownOpen) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setFocusedIdx(i => Math.min(i + 1, searchResults.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setFocusedIdx(i => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (searchResults[focusedIdx]) pickResult(searchResults[focusedIdx])
    } else if (e.key === 'Escape') {
      setDropdownOpen(false)
    }
  }

  // ── Pick a symbol from dropdown or popular chips ──────────────────────────
  function pickResult(asset) {
    setQuery(asset.symbol)
    setSearchResults([])
    setDropdownOpen(false)
    selectSymbol(asset.symbol, asset.name || '', asset.exchange || '')
  }

  function pickPopular(sym) {
    setQuery(sym)
    selectSymbol(sym, '', '')
  }

  // ── Load quote + news for a symbol ───────────────────────────────────────
  const selectSymbol = useCallback(async (sym, name, exchange) => {
    setSelectedSymbol(sym)
    setSelectedName(name)
    setSelectedExch(exchange)
    setAddedToWL(false)
    setQuote(null)
    setNewsItems([])

    // Load quote
    setQuoteLoading(true)
    setQuoteError(false)
    try {
      const r = await api.get(`/quote/${sym}`)
      setQuote(r.data)
      // Fill in name/exchange from quote if not provided
      if (!name && r.data.name)     setSelectedName(r.data.name)
      if (!exchange && r.data.exchange) setSelectedExch(r.data.exchange)
    } catch {
      setQuoteError(true)
    } finally {
      setQuoteLoading(false)
    }

    // Load news (non-blocking)
    setNewsLoading(true)
    try {
      const r = await api.get(`/news/${sym}`)
      setNewsItems((r.data || []).slice(0, 3))
    } catch {
      setNewsItems([])
    } finally {
      setNewsLoading(false)
    }
  }, [])

  // ── Add to watchlist ──────────────────────────────────────────────────────
  async function handleAddToWatchlist() {
    if (!selectedSymbol || addedToWL || addingToWL) return
    setAddingToWL(true)
    try {
      await api.post('/watchlist', { action: 'add', symbol: selectedSymbol })
      setAddedToWL(true)
      setTimeout(() => setAddedToWL(false), 2000)
    } catch {
      // silently fail
    } finally {
      setAddingToWL(false)
    }
  }

  // ── Price / change display helpers ────────────────────────────────────────
  const midPrice = quote
    ? ((Number(quote.bid || 0) + Number(quote.ask || 0)) / 2)
    : null

  const priceDisplay = midPrice != null && midPrice > 0
    ? `$${midPrice.toFixed(2)}`
    : quote?.last != null
      ? `$${Number(quote.last).toFixed(2)}`
      : null

  const change    = quote?.change    != null ? Number(quote.change)    : null
  const changePct = quote?.change_pct != null ? Number(quote.change_pct) : null
  const isPositive = change != null ? change >= 0 : null

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <>
      {/* ── Header: search bar ─────────────────────────────────────────── */}
      <div className="ch-header" style={{ gap: 10, padding: '0 14px', position: 'relative' }}>

        {/* Search icon */}
        <svg
          width="14" height="14" viewBox="0 0 14 14" fill="none"
          style={{ flexShrink: 0, color: 'var(--t-3)' }}
        >
          <circle cx="6" cy="6" r="4.5" stroke="currentColor" strokeWidth="1.4" fill="none"/>
          <line x1="9.5" y1="9.5" x2="13" y2="13" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
        </svg>

        {/* Search input + dropdown wrapper */}
        <div
          ref={wrapRef}
          style={{ position: 'relative', flex: 1 }}
          onBlur={e => {
            if (!e.currentTarget.contains(e.relatedTarget)) setDropdownOpen(false)
          }}
        >
          <input
            value={query}
            onChange={handleQueryChange}
            onKeyDown={handleKeyDown}
            onFocus={() => searchResults.length > 0 && setDropdownOpen(true)}
            placeholder="Search for any stock or ETF…"
            autoComplete="off"
            spellCheck={false}
            style={{
              width:        '100%',
              background:   'var(--bg-input)',
              border:       '1px solid var(--hairline-2)',
              borderRadius: 6,
              color:        'var(--t-1)',
              fontSize:     12,
              fontFamily:   'var(--font-sans)',
              padding:      '5px 10px',
              outline:      'none',
              transition:   'border-color .15s',
            }}
            onFocusCapture={e => { e.target.style.borderColor = 'var(--acc)' }}
            onBlurCapture={e  => { e.target.style.borderColor = 'var(--hairline-2)' }}
          />

          {/* Dropdown */}
          {dropdownOpen && (
            <div
              style={{
                position:    'absolute',
                top:         'calc(100% + 4px)',
                left:        0,
                right:       0,
                background:  'var(--bg-card)',
                border:      '1px solid var(--hairline-2)',
                borderRadius: 'var(--radius)',
                zIndex:      300,
                boxShadow:   '0 8px 24px rgba(0,0,0,0.55)',
                overflow:    'hidden',
              }}
            >
              {searchResults.map((a, i) => (
                <div
                  key={a.symbol}
                  onMouseDown={() => pickResult(a)}
                  onMouseEnter={() => setFocusedIdx(i)}
                  style={{
                    display:        'flex',
                    alignItems:     'center',
                    gap:            10,
                    padding:        '8px 12px',
                    cursor:         'pointer',
                    background:     i === focusedIdx ? 'var(--bg-card-hi)' : 'transparent',
                    borderBottom:   i < searchResults.length - 1 ? '1px solid var(--hairline)' : 'none',
                    transition:     'background .1s',
                  }}
                >
                  <span style={{
                    fontFamily:  'var(--font-mono)',
                    fontWeight:  700,
                    fontSize:    12,
                    color:       'var(--acc)',
                    minWidth:    52,
                    flexShrink:  0,
                  }}>
                    {a.symbol}
                  </span>
                  <span style={{
                    fontSize:     12,
                    color:        'var(--t-2)',
                    flex:         1,
                    overflow:     'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace:   'nowrap',
                  }}>
                    {a.name}
                  </span>
                  <span style={{
                    fontSize:    10,
                    color:       'var(--t-3)',
                    fontFamily:  'var(--font-mono)',
                    flexShrink:  0,
                  }}>
                    {a.exchange}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── Body ───────────────────────────────────────────────────────────── */}
      <div className="ch-body" style={{ padding: 14 }}>

        {/* Popular chips — shown when nothing is selected */}
        {!selectedSymbol && (
          <div>
            <div style={{
              fontSize:      10,
              letterSpacing: '0.1em',
              textTransform: 'uppercase',
              color:         'var(--t-3)',
              marginBottom:  10,
            }}>
              Popular
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 7 }}>
              {POPULAR.map(sym => (
                <PopularChip key={sym} symbol={sym} onClick={() => pickPopular(sym)} />
              ))}
            </div>
            <div style={{
              marginTop: 18,
              fontSize:  12,
              color:     'var(--t-3)',
              lineHeight: 1.6,
            }}>
              Search for a symbol above or click a chip to explore its quote and news.
            </div>
          </div>
        )}

        {/* Symbol info panel — shown when a symbol is selected */}
        {selectedSymbol && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>

            {/* ── Symbol header card ── */}
            <div className="widget" style={{ padding: '14px 16px' }}>

              {/* Top row: symbol + name + exchange */}
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, marginBottom: 10 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{
                    fontFamily:  'var(--font-mono)',
                    fontSize:    24,
                    fontWeight:  700,
                    color:       'var(--cy)',
                    lineHeight:  1.1,
                    letterSpacing: '0.02em',
                  }}>
                    {selectedSymbol}
                  </div>
                  {selectedName && (
                    <div style={{
                      fontSize:     15,
                      color:        'var(--t-2)',
                      marginTop:    3,
                      overflow:     'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace:   'nowrap',
                    }}>
                      {selectedName}
                    </div>
                  )}
                </div>
                {selectedExch && (
                  <span style={{
                    fontSize:      10,
                    fontFamily:    'var(--font-mono)',
                    color:         'var(--t-3)',
                    background:    'var(--bg-card-hi)',
                    border:        '1px solid var(--hairline-2)',
                    borderRadius:  4,
                    padding:       '3px 7px',
                    whiteSpace:    'nowrap',
                    flexShrink:    0,
                    alignSelf:     'flex-start',
                    marginTop:     3,
                    letterSpacing: '0.06em',
                  }}>
                    {selectedExch}
                  </span>
                )}
              </div>

              {/* Price row */}
              {quoteLoading && (
                <div style={{ color: 'var(--t-3)', fontSize: 12, marginBottom: 10 }}>
                  Loading quote…
                </div>
              )}
              {quoteError && (
                <div style={{ color: 'var(--err)', fontSize: 12, marginBottom: 10 }}>
                  Could not load quote.
                </div>
              )}
              {!quoteLoading && !quoteError && quote && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
                    {priceDisplay && (
                      <span style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize:   22,
                        fontWeight: 700,
                        color:      'var(--t-1)',
                      }}>
                        {priceDisplay}
                      </span>
                    )}
                    {change != null && changePct != null && (
                      <span style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize:   13,
                        fontWeight: 600,
                        color:      isPositive ? 'var(--ok)' : 'var(--err)',
                      }}>
                        {isPositive ? '+' : ''}{change.toFixed(2)}
                        &nbsp;
                        ({isPositive ? '+' : ''}{changePct.toFixed(2)}%)
                      </span>
                    )}
                    {quote.delayed && (
                      <span style={{
                        fontSize:      10,
                        fontFamily:    'var(--font-mono)',
                        color:         'var(--t-3)',
                        letterSpacing: '0.06em',
                        alignSelf:     'center',
                      }}>
                        DELAYED
                      </span>
                    )}
                  </div>

                  {/* Live indicator dot */}
                  {!quote.delayed && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginTop: 4 }}>
                      <span style={{
                        width:        6,
                        height:       6,
                        borderRadius: '50%',
                        background:   'var(--ok)',
                        boxShadow:    '0 0 5px var(--ok)',
                        display:      'inline-block',
                      }} />
                      <span style={{ fontSize: 10, color: 'var(--t-3)', fontFamily: 'var(--font-mono)' }}>
                        Live
                      </span>
                    </div>
                  )}
                </div>
              )}

              {/* Action buttons */}
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  onClick={() => onSelectSymbol && onSelectSymbol(selectedSymbol)}
                  style={{
                    flex:         1,
                    background:   'var(--acc)',
                    border:       'none',
                    borderRadius: 6,
                    color:        '#fff',
                    fontFamily:   'var(--font-sans)',
                    fontSize:     13,
                    fontWeight:   600,
                    padding:      '8px 12px',
                    cursor:       'pointer',
                    transition:   'background .15s, transform .1s',
                    letterSpacing: '0.02em',
                  }}
                  onMouseEnter={e => { e.currentTarget.style.background = 'var(--acc-hi)' }}
                  onMouseLeave={e => { e.currentTarget.style.background = 'var(--acc)' }}
                  onMouseDown={e  => { e.currentTarget.style.transform = 'scale(0.97)' }}
                  onMouseUp={e    => { e.currentTarget.style.transform = 'scale(1)' }}
                >
                  Open Chart
                </button>

                <button
                  onClick={handleAddToWatchlist}
                  disabled={addedToWL || addingToWL}
                  style={{
                    flex:         1,
                    background:   addedToWL ? 'rgba(61,220,151,0.10)' : 'transparent',
                    border:       `1px solid ${addedToWL ? 'var(--ok)' : 'var(--hairline-2)'}`,
                    borderRadius: 6,
                    color:        addedToWL ? 'var(--ok)' : 'var(--t-1)',
                    fontFamily:   'var(--font-sans)',
                    fontSize:     13,
                    fontWeight:   600,
                    padding:      '8px 12px',
                    cursor:       addedToWL ? 'default' : 'pointer',
                    transition:   'all .15s',
                    letterSpacing: '0.02em',
                    opacity:      addingToWL ? 0.6 : 1,
                  }}
                  onMouseEnter={e => {
                    if (!addedToWL && !addingToWL) {
                      e.currentTarget.style.borderColor = 'var(--acc-line)'
                      e.currentTarget.style.background  = 'var(--acc-soft)'
                    }
                  }}
                  onMouseLeave={e => {
                    if (!addedToWL && !addingToWL) {
                      e.currentTarget.style.borderColor = 'var(--hairline-2)'
                      e.currentTarget.style.background  = 'transparent'
                    }
                  }}
                >
                  {addedToWL ? '✓ Added' : '+ Add to Watchlist'}
                </button>
              </div>
            </div>

            {/* ── News section ── */}
            <div className="widget" style={{ padding: '12px 14px' }}>
              <div className="widget-hd" style={{ marginBottom: 10 }}>
                Latest News
              </div>

              {newsLoading && (
                <div style={{ color: 'var(--t-3)', fontSize: 11, padding: '6px 0', textAlign: 'center' }}>
                  Loading…
                </div>
              )}

              {!newsLoading && newsItems.length === 0 && (
                <div style={{ color: 'var(--t-3)', fontSize: 11, padding: '6px 0', textAlign: 'center' }}>
                  No news available
                </div>
              )}

              {!newsLoading && newsItems.map((item, i) => (
                <div
                  key={i}
                  onClick={() => item.url && window.open(item.url, '_blank', 'noopener')}
                  style={{
                    display:      'flex',
                    alignItems:   'flex-start',
                    gap:          8,
                    padding:      '8px 0',
                    borderBottom: i < newsItems.length - 1 ? '1px solid var(--hairline)' : 'none',
                    cursor:       item.url ? 'pointer' : 'default',
                  }}
                >
                  {/* Sentiment dot */}
                  <span style={{
                    width:        7,
                    height:       7,
                    borderRadius: '50%',
                    background:   sentimentColor(item.sentiment_label),
                    flexShrink:   0,
                    marginTop:    4,
                    display:      'inline-block',
                  }} />

                  {/* Text */}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{
                      fontSize:           12,
                      fontWeight:         500,
                      color:              'var(--t-1)',
                      lineHeight:         1.45,
                      display:            '-webkit-box',
                      WebkitLineClamp:    2,
                      WebkitBoxOrient:    'vertical',
                      overflow:           'hidden',
                    }}>
                      {item.title || 'Untitled'}
                    </div>
                    <div style={{
                      fontSize:     10,
                      color:        'var(--t-3)',
                      marginTop:    3,
                      whiteSpace:   'nowrap',
                      overflow:     'hidden',
                      textOverflow: 'ellipsis',
                    }}>
                      {item.source && <span>{item.source}</span>}
                      {item.source && item.published && <span> · </span>}
                      {item.published && <span>{relTime(item.published)}</span>}
                    </div>
                  </div>
                </div>
              ))}
            </div>

          </div>
        )}

      </div>
    </>
  )
}

// ── Popular chip sub-component ────────────────────────────────────────────────
function PopularChip({ symbol, onClick }) {
  const [hovered, setHovered] = useState(false)
  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        background:   hovered ? 'var(--acc-soft)'   : 'var(--bg-card)',
        border:       `1px solid ${hovered ? 'var(--acc-line)' : 'var(--hairline-2)'}`,
        borderRadius: 6,
        padding:      '6px 14px',
        cursor:       'pointer',
        fontFamily:   'var(--font-mono)',
        color:        'var(--acc)',
        fontSize:     13,
        fontWeight:   600,
        transition:   'all .15s',
        lineHeight:   1,
      }}
    >
      {symbol}
    </button>
  )
}

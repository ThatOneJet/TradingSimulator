import { useState, useEffect, useRef } from 'react'
import api from '../api.js'

const _sparkCache = new Map()

function Sparkline({ closes }) {
  if (!closes || closes.length < 2) return <div className="sym-spark-placeholder" />
  const W = 80, H = 28
  const min   = Math.min(...closes)
  const max   = Math.max(...closes)
  const range = max - min || 1
  const pts   = closes.map((v, i) => {
    const x = ((i / (closes.length - 1)) * W).toFixed(1)
    const y = (H - 2 - ((v - min) / range) * (H - 4)).toFixed(1)
    return `${x},${y}`
  }).join(' ')
  const up = closes[closes.length - 1] >= closes[0]
  return (
    <svg width={W} height={H} className="sym-spark">
      <polyline points={pts} fill="none"
        stroke={up ? '#26d97f' : '#ff4d4d'} strokeWidth="1.5"
        strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}

export default function SymbolSearch({ value, onChange, onSelect, placeholder = 'Search symbol or company…', autoFocus = false }) {
  const [query,      setQuery]     = useState(value || '')
  const [results,    setResults]   = useState([])
  const [sparklines, setSparklines] = useState({})
  const [open,       setOpen]      = useState(false)
  const [focused,    setFocused]   = useState(0)
  const [dropStyle,  setDropStyle] = useState({})
  const debounce = useRef(null)
  const inputRef = useRef(null)
  const wrapRef  = useRef(null)

  useEffect(() => {
    if (autoFocus) inputRef.current?.focus()
  }, [autoFocus])

  // Recalculate fixed position of dropdown to escape overflow clipping
  function recalcDrop() {
    const el = wrapRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    setDropStyle({
      position: 'fixed',
      top:   rect.bottom + 4,
      left:  rect.left,
      width: rect.width,
      zIndex: 9999,
    })
  }

  useEffect(() => {
    if (open) recalcDrop()
  }, [open, results])

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e) => {
      if (!wrapRef.current?.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  // Fetch sparklines for current results
  useEffect(() => {
    if (!results.length) { setSparklines({}); return }
    const cached = {}
    results.forEach(a => {
      if (_sparkCache.has(a.symbol) && _sparkCache.get(a.symbol) !== null)
        cached[a.symbol] = _sparkCache.get(a.symbol)
    })
    if (Object.keys(cached).length) setSparklines(cached)
    results.forEach(a => {
      if (_sparkCache.has(a.symbol)) return
      _sparkCache.set(a.symbol, null)
      api.get(`/sparkline/${a.symbol}`)
        .then(r => {
          _sparkCache.set(a.symbol, r.data)
          setSparklines(prev => ({ ...prev, [a.symbol]: r.data }))
        })
        .catch(() => { _sparkCache.set(a.symbol, []) })
    })
  }, [results])

  function handleChange(e) {
    const q = e.target.value
    setQuery(q)
    onChange?.(q)
    clearTimeout(debounce.current)
    if (q.length < 1) { setResults([]); setOpen(false); return }
    debounce.current = setTimeout(async () => {
      try {
        const r = await api.get(`/assets/search?q=${encodeURIComponent(q)}`)
        setResults(r.data)
        setOpen(r.data.length > 0)
        setFocused(0)
      } catch {}
    }, 200)
  }

  function pick(asset) {
    setQuery(asset.symbol)
    setResults([])
    setOpen(false)
    onSelect?.(asset)
  }

  function handleKeyDown(e) {
    if (!open) return
    if (e.key === 'ArrowDown') { e.preventDefault(); setFocused(f => Math.min(f + 1, results.length - 1)) }
    if (e.key === 'ArrowUp')   { e.preventDefault(); setFocused(f => Math.max(f - 1, 0)) }
    if (e.key === 'Enter')     { e.preventDefault(); if (results[focused]) pick(results[focused]) }
    if (e.key === 'Escape')    { setOpen(false) }
  }

  return (
    <div ref={wrapRef} className="sym-search-wrap">
      <input
        ref={inputRef}
        className="sym-search-input"
        value={query}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        onFocus={() => results.length > 0 && setOpen(true)}
        placeholder={placeholder}
        autoComplete="off"
        spellCheck={false}
      />
      {open && results.length > 0 && (
        <div className="sym-search-dropdown" style={dropStyle}>
          {results.map((a, i) => (
            <div
              key={a.symbol}
              className={`sym-search-item${i === focused ? ' focused' : ''}`}
              onMouseDown={() => pick(a)}
              onMouseEnter={() => setFocused(i)}
            >
              <div className="sym-search-left">
                <span className="sym-search-sym">{a.symbol}</span>
                <span className="sym-search-name">{a.name}</span>
                <span className="sym-search-exch">{a.exchange}</span>
              </div>
              <Sparkline closes={sparklines[a.symbol]} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

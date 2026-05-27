// NavSidebar — collapsible watchlist nav (column 2, row 2 of app-shell grid)
// Hover-driven collapse: expands on mouseenter, collapses (with 200ms delay) on mouseleave.

import { useState, useEffect, useRef } from 'react'
import api from '../api.js'
import SymbolSearch from './SymbolSearch.jsx'

/** Derive initials (up to 2 chars) from a ticker symbol */
function symbolInitials(sym) {
  if (!sym) return '?'
  return sym.slice(0, Math.min(2, sym.length)).toUpperCase()
}

/** Derive avatar initials from a username */
function userInitials(username) {
  if (!username) return '?'
  const parts = username.trim().split(/\s+/)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  return username.slice(0, 2).toUpperCase()
}

export default function NavSidebar({
  // collapsed / onCollapse kept as optional for backward-compat but no longer used
  active,
  onSelect,
  socket,
  user,
  onWatchlistChange,
  onLogout,
  onCollapseChange,  // NEW: called with boolean whenever collapsed state changes
}) {
  const [collapsed, setCollapsed] = useState(true)
  const [items, setItems] = useState([])
  const leaveTimer = useRef(null)

  // ── Hover handlers ─────────────────────────────────────────────────────
  function handleMouseEnter() {
    if (leaveTimer.current) {
      clearTimeout(leaveTimer.current)
      leaveTimer.current = null
    }
    setCollapsed(false)
    if (onCollapseChange) onCollapseChange(false)
  }

  function handleMouseLeave() {
    leaveTimer.current = setTimeout(() => {
      setCollapsed(true)
      if (onCollapseChange) onCollapseChange(true)
    }, 200)
  }

  // ── Load watchlist ──────────────────────────────────────────────────────
  function load() {
    api.get('/watchlist').then(r => {
      setItems(r.data)
      if (onWatchlistChange) {
        onWatchlistChange(r.data.map(it => it.symbol))
      }
    }).catch(() => {})
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 10000)
    return () => clearInterval(id)
  }, [])

  // Cleanup leave timer on unmount
  useEffect(() => {
    return () => {
      if (leaveTimer.current) clearTimeout(leaveTimer.current)
    }
  }, [])

  // ── Live price updates via SocketIO ────────────────────────────────────
  useEffect(() => {
    if (!socket) return
    const handler = ({ symbol, bid, ask }) => {
      setItems(prev => prev.map(it =>
        it.symbol === symbol
          ? { ...it, price: (bid + ask) / 2, bid, ask }
          : it
      ))
    }
    socket.on('quote', handler)
    return () => socket.off('quote', handler)
  }, [socket])

  // ── Add / remove ───────────────────────────────────────────────────────
  async function addSymbol(asset) {
    await api.post('/watchlist', { action: 'add', symbol: asset.symbol })
    load()
  }

  async function removeSymbol(sym, e) {
    e.stopPropagation()
    await api.post('/watchlist', { action: 'remove', symbol: sym })
    load()
  }

  // ── Avatar color (use user.avatar_color if present, fallback to --acc) ─
  const avatarBg = user?.avatar_color || 'var(--acc)'
  const initials = userInitials(user?.username || '')

  return (
    <nav
      className={`nav${collapsed ? ' nav-collapsed' : ''}`}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >

      {/* ── Header row ── */}
      <div className="nav-head">
        <span className="nav-head-text">Watchlist</span>
      </div>

      {/* ── Symbol search (hidden when collapsed) ── */}
      {!collapsed && (
        <div className="nav-search">
          <SymbolSearch
            onSelect={addSymbol}
            placeholder="Add to watchlist…"
          />
        </div>
      )}

      {/* ── Watchlist items ── */}
      <div className="nav-items">
        {items.map(it => (
          <div
            key={it.symbol}
            className={`wl-item${it.symbol === active ? ' active' : ''}`}
            onClick={() => onSelect(it.symbol)}
            title={collapsed ? it.symbol : undefined}
          >
            {/* Symbol icon square — always visible, centered when collapsed */}
            <div
              className="wl-item-icon"
              style={collapsed ? { margin: '0 auto' } : undefined}
            >
              {symbolInitials(it.symbol)}
            </div>

            {/* Text columns — hidden when collapsed */}
            <span className="wl-sym-name">{it.symbol}</span>

            {it.price
              ? <span className="wl-price">${Number(it.price).toFixed(2)}</span>
              : <span className="wl-price">—</span>
            }

            {it.price && it.change_pct !== undefined && (
              <span className={`wl-chg ${it.change_pct >= 0 ? 'ok' : 'err'}`}>
                {it.change_pct >= 0 ? '+' : ''}{Number(it.change_pct).toFixed(2)}%
              </span>
            )}

            <button
              className="wl-rm"
              onClick={e => removeSymbol(it.symbol, e)}
              title="Remove"
            >
              ×
            </button>
          </div>
        ))}
      </div>

      {/* ── User profile footer ── */}
      <div className="nav-foot">
        <div
          className="nav-foot-avatar"
          style={{ background: avatarBg }}
          title={user?.username}
        >
          {initials}
        </div>

        <div className="nav-foot-text">
          <span className="nav-foot-name">{user?.username || 'Trader'}</span>
          <span className="nav-foot-plan">PAPER</span>
        </div>

        <button
          className="nav-foot-logout"
          title="Log out"
          onClick={onLogout}
        >
          ⏻
        </button>
      </div>
    </nav>
  )
}

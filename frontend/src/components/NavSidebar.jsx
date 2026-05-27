// NavSidebar — collapsible watchlist nav (column 2, row 2 of app-shell grid)
// Replaces the old Watchlist component.

import { useState, useEffect } from 'react'
import api from '../api.js'
import SymbolSearch from './SymbolSearch.jsx'

function ChevronLeftIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <polyline points="9,2 4,7 9,12" stroke="currentColor" strokeWidth="1.6"
        strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  )
}

function ChevronRightIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <polyline points="5,2 10,7 5,12" stroke="currentColor" strokeWidth="1.6"
        strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  )
}

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
  collapsed,
  onCollapse,
  active,
  onSelect,
  socket,
  user,
  onWatchlistChange,
  onLogout,
}) {
  const [items, setItems] = useState([])

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
    <nav className={`nav${collapsed ? ' nav-collapsed' : ''}`}>

      {/* ── Header row with collapse toggle ── */}
      <div className="nav-head">
        <span className="nav-head-text">Watchlist</span>
        <button
          className="nav-collapse-btn"
          title={collapsed ? 'Expand' : 'Collapse'}
          onClick={onCollapse}
        >
          {collapsed ? <ChevronRightIcon /> : <ChevronLeftIcon />}
        </button>
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
            {/* Symbol icon square — always visible */}
            <div className="wl-item-icon">
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

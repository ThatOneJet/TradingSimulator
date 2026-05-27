import { useState, useEffect } from 'react'
import api from '../api.js'
import SymbolSearch from './SymbolSearch.jsx'

export default function Watchlist({ active, onSelect, socket }) {
  const [items,  setItems]  = useState([])

  function load() {
    api.get('/watchlist').then(r => setItems(r.data)).catch(() => {})
  }
  useEffect(() => { load(); const id = setInterval(load, 10000); return () => clearInterval(id) }, [])

  useEffect(() => {
    if (!socket) return
    const handler = ({ symbol, bid, ask }) => {
      setItems(prev => prev.map(it =>
        it.symbol === symbol ? { ...it, price: (bid + ask) / 2, bid, ask } : it
      ))
    }
    socket.on('quote', handler)
    return () => socket.off('quote', handler)
  }, [socket])

  async function removeSymbol(sym, e) {
    e.stopPropagation()
    await api.post('/watchlist', { action: 'remove', symbol: sym })
    load()
  }

  return (
    <div className="watchlist">
      <div className="wl-header">Watchlist</div>
      <div className="wl-search">
        <SymbolSearch
          onSelect={async (asset) => {
            await api.post('/watchlist', { action: 'add', symbol: asset.symbol })
            load()
          }}
          placeholder="Add to watchlist…"
        />
      </div>
      <div className="wl-items">
        {items.map(it => (
          <div
            key={it.symbol}
            className={`wl-item${it.symbol === active ? ' active' : ''}`}
            onClick={() => onSelect(it.symbol)}
          >
            <span className="wl-sym">{it.symbol}</span>
            <span className="wl-price mono">{it.price ? `$${Number(it.price).toFixed(2)}` : '—'}</span>
            <button className="wl-rm" onClick={e => removeSymbol(it.symbol, e)}>×</button>
          </div>
        ))}
      </div>
    </div>
  )
}

import { useState, useEffect, useCallback } from 'react'
import api from '../api.js'

const PRESET_COLORS = ['#ff6a1a', '#3ddc97', '#4ad9ff', '#f5b342', '#ff476f', '#b06aff']

function fmt(n) {
  if (n == null || isNaN(n)) return '—'
  return '$' + Number(n).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
}

function fmtPnl(n) {
  if (n == null || isNaN(n)) return null
  const sign = n >= 0 ? '+' : ''
  return sign + '$' + Math.abs(Number(n)).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
}

// ── New Portfolio Form ──────────────────────────────────────────────────────
function NewPortfolioForm({ onCancel, onCreate }) {
  const [name, setName]         = useState('')
  const [color, setColor]       = useState(PRESET_COLORS[0])
  const [error, setError]       = useState('')
  const [loading, setLoading]   = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    if (!name.trim()) { setError('Name is required.'); return }
    setLoading(true)
    try {
      await onCreate(name.trim(), color)
    } catch (err) {
      setError(err?.response?.data?.error || 'Failed to create portfolio.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      noValidate
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '8px 16px',
        background: 'var(--bg-card-hi)',
        borderTop: '1px solid var(--hairline-2)',
        flexShrink: 0,
        flexWrap: 'wrap',
      }}
    >
      <input
        autoFocus
        type="text"
        value={name}
        onChange={e => setName(e.target.value)}
        placeholder="Portfolio name"
        maxLength={40}
        style={{
          background: 'var(--bg-input)',
          border: '1px solid var(--hairline-2)',
          borderRadius: 6,
          padding: '6px 10px',
          fontSize: 12,
          color: 'var(--t-1)',
          fontFamily: 'var(--font-sans)',
          outline: 'none',
          width: 160,
        }}
      />

      {/* Color presets */}
      <div style={{ display: 'flex', gap: 5, alignItems: 'center' }}>
        {PRESET_COLORS.map(c => (
          <button
            key={c}
            type="button"
            onClick={() => setColor(c)}
            title={c}
            style={{
              width: 18,
              height: 18,
              borderRadius: '50%',
              background: c,
              border: color === c ? '2px solid var(--t-1)' : '2px solid transparent',
              cursor: 'pointer',
              padding: 0,
              flexShrink: 0,
              outline: 'none',
              boxShadow: color === c ? '0 0 0 1px ' + c : 'none',
              transition: 'border .1s, box-shadow .1s',
            }}
          />
        ))}
        {/* Native color picker fallback */}
        <input
          type="color"
          value={color}
          onChange={e => setColor(e.target.value)}
          title="Custom color"
          style={{
            width: 18,
            height: 18,
            padding: 0,
            border: '1px solid var(--hairline-2)',
            borderRadius: '50%',
            cursor: 'pointer',
            background: 'none',
          }}
        />
      </div>

      {error && (
        <span style={{ color: 'var(--err)', fontSize: 11 }}>{error}</span>
      )}

      <div style={{ display: 'flex', gap: 6, marginLeft: 'auto' }}>
        <button
          type="button"
          onClick={onCancel}
          style={{
            padding: '5px 12px',
            background: 'transparent',
            border: '1px solid var(--hairline-2)',
            borderRadius: 6,
            color: 'var(--t-3)',
            fontFamily: 'var(--font-sans)',
            fontSize: 12,
            cursor: 'pointer',
          }}
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={loading}
          style={{
            padding: '5px 14px',
            background: 'var(--acc)',
            border: 'none',
            borderRadius: 6,
            color: '#fff',
            fontFamily: 'var(--font-sans)',
            fontWeight: 700,
            fontSize: 12,
            cursor: loading ? 'default' : 'pointer',
            opacity: loading ? 0.6 : 1,
            transition: 'background .15s',
          }}
        >
          {loading ? 'Creating…' : 'Create'}
        </button>
      </div>
    </form>
  )
}

// ── Portfolio Tab Card ──────────────────────────────────────────────────────
function PortfolioCard({ portfolio, account, isActive, onClick, onDelete, canDelete }) {
  const [hover, setHover] = useState(false)

  const pnl    = account?.pnl_day
  const equity = account?.equity

  const cardStyle = {
    background: 'var(--bg-card)',
    border: isActive
      ? '1px solid var(--acc)'
      : hover
        ? '1px solid var(--hairline-3)'
        : '1px solid var(--hairline-2)',
    borderRadius: 8,
    padding: '6px 12px',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    whiteSpace: 'nowrap',
    flexShrink: 0,
    transition: 'all .15s',
    boxShadow: isActive
      ? '0 0 0 1px var(--acc-line), 0 0 12px var(--acc-glow)'
      : hover
        ? '0 2px 8px rgba(0,0,0,0.3)'
        : 'none',
    position: 'relative',
    userSelect: 'none',
  }

  const pnlStr   = fmtPnl(pnl)
  const pnlColor = pnl != null ? (pnl >= 0 ? 'var(--ok)' : 'var(--err)') : 'var(--t-3)'

  return (
    <div
      style={cardStyle}
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      {/* Colored dot */}
      <span style={{
        width: 8,
        height: 8,
        borderRadius: '50%',
        background: portfolio.color || 'var(--acc)',
        flexShrink: 0,
        display: 'inline-block',
      }} />

      {/* Name + numbers */}
      <span style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: isActive ? 'var(--t-1)' : 'var(--t-2)' }}>
          {portfolio.name}
        </span>
        <span style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
          <span style={{ fontSize: 11, color: 'var(--t-2)', fontFamily: 'var(--font-mono)' }}>
            {fmt(equity)}
          </span>
          {pnlStr && (
            <span style={{ fontSize: 10, color: pnlColor, fontFamily: 'var(--font-mono)' }}>
              {pnlStr}
            </span>
          )}
        </span>
      </span>

      {/* Delete button — only when hovered, not active, and canDelete */}
      {canDelete && !isActive && hover && (
        <button
          type="button"
          onClick={e => { e.stopPropagation(); onDelete() }}
          title="Delete portfolio"
          style={{
            marginLeft: 4,
            width: 16,
            height: 16,
            borderRadius: '50%',
            background: 'var(--err)',
            border: 'none',
            color: '#fff',
            fontSize: 10,
            lineHeight: '16px',
            textAlign: 'center',
            cursor: 'pointer',
            padding: 0,
            flexShrink: 0,
            opacity: 0.85,
            transition: 'opacity .15s',
          }}
        >
          ×
        </button>
      )}
    </div>
  )
}

// ── Main Component ──────────────────────────────────────────────────────────
export default function PortfolioTabs({ portfolioId, onSwitch, userId }) {
  const [portfolios, setPortfolios] = useState([])
  const [accounts, setAccounts]     = useState({})   // { [portfolioId]: accountData }
  const [showForm, setShowForm]     = useState(false)
  const [loading, setLoading]       = useState(true)

  const loadAll = useCallback(async () => {
    if (!userId) return
    setLoading(true)
    try {
      const { data: ports } = await api.get(`/portfolios?user_id=${userId}`)
      setPortfolios(ports)

      // Load account data for all portfolios in parallel
      const results = await Promise.all(
        ports.map(p =>
          api.get(`/account?portfolio_id=${p.id}`)
            .then(r => ({ id: p.id, data: r.data }))
            .catch(() => ({ id: p.id, data: null }))
        )
      )
      const map = {}
      results.forEach(r => { map[r.id] = r.data })
      setAccounts(map)
    } catch (err) {
      console.error('PortfolioTabs: failed to load portfolios', err)
    } finally {
      setLoading(false)
    }
  }, [userId])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  // Reload account data for the active portfolio when portfolioId changes from outside
  useEffect(() => {
    if (!portfolioId) return
    api.get(`/account?portfolio_id=${portfolioId}`)
      .then(r => setAccounts(prev => ({ ...prev, [portfolioId]: r.data })))
      .catch(() => {})
  }, [portfolioId])

  async function handleCreate(name, color) {
    const { data } = await api.post('/portfolios', { user_id: userId, name, color })
    setShowForm(false)
    await loadAll()
    onSwitch(data.id)
  }

  async function handleDelete(id) {
    const port = portfolios.find(p => p.id === id)
    if (!window.confirm(`Delete portfolio "${port?.name}"? This cannot be undone.`)) return
    try {
      await api.delete(`/portfolios/${id}`)
      const remaining = portfolios.filter(p => p.id !== id)
      await loadAll()
      // If deleted portfolio was active, switch to first remaining
      if (portfolioId === id && remaining.length > 0) {
        onSwitch(remaining[0].id)
      }
    } catch (err) {
      console.error('PortfolioTabs: delete failed', err)
      alert(err?.response?.data?.error || 'Failed to delete portfolio.')
    }
  }

  const canDelete = portfolios.length > 1

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flexShrink: 0 }}>
      {/* Tab row */}
      <div
        className="portfolio-tabs"
        style={{
          display: 'flex',
          gap: 8,
          padding: '8px 16px',
          borderBottom: '1px solid var(--hairline)',
          background: 'var(--bg-main)',
          overflowX: 'auto',
          flexShrink: 0,
          alignItems: 'center',
          scrollbarWidth: 'none',
        }}
      >
        {loading && portfolios.length === 0 && (
          <span style={{ color: 'var(--t-4)', fontSize: 11 }}>Loading…</span>
        )}

        {portfolios.map(p => (
          <PortfolioCard
            key={p.id}
            portfolio={p}
            account={accounts[p.id]}
            isActive={p.id === portfolioId}
            onClick={() => onSwitch(p.id)}
            onDelete={() => handleDelete(p.id)}
            canDelete={canDelete}
          />
        ))}

        {/* Add portfolio button */}
        <button
          type="button"
          onClick={() => setShowForm(v => !v)}
          title="New portfolio"
          style={{
            width: 28,
            height: 28,
            borderRadius: 7,
            background: showForm ? 'var(--acc-soft)' : 'transparent',
            border: '1px solid ' + (showForm ? 'var(--acc-line)' : 'var(--hairline-2)'),
            color: showForm ? 'var(--acc)' : 'var(--t-3)',
            fontSize: 18,
            lineHeight: '28px',
            textAlign: 'center',
            cursor: 'pointer',
            flexShrink: 0,
            padding: 0,
            fontWeight: 300,
            transition: 'all .15s',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          ＋
        </button>
      </div>

      {/* Inline new-portfolio form */}
      {showForm && (
        <NewPortfolioForm
          onCancel={() => setShowForm(false)}
          onCreate={handleCreate}
        />
      )}
    </div>
  )
}

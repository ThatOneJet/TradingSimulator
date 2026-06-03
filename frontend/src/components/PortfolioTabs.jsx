import { useState, useEffect, useCallback } from 'react'
import api from '../api.js'
import ConfirmModal from './ConfirmModal.jsx'

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
  const [name,         setName]         = useState('')
  const [color,        setColor]        = useState(PRESET_COLORS[0])
  const [initialCash,  setInitialCash]  = useState('100000')
  const [aiControlled, setAiControlled] = useState(false)
  const [error,        setError]        = useState('')
  const [loading,      setLoading]      = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    if (!name.trim()) { setError('Name is required.'); return }
    const cash = parseFloat(initialCash)
    if (isNaN(cash) || cash < 100) { setError('Starting balance must be at least $100.'); return }
    setLoading(true)
    try {
      await onCreate(name.trim(), color, cash, aiControlled)
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
        flexDirection: 'column',
        gap: 8,
        padding: '10px 16px',
        background: 'var(--bg-card-hi)',
        borderTop: '1px solid var(--hairline-2)',
        flexShrink: 0,
      }}
    >
      {/* Row 1: name, balance, colors */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'nowrap' }}>
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
            padding: '5px 9px',
            fontSize: 12,
            color: 'var(--t-1)',
            fontFamily: 'var(--font-sans)',
            outline: 'none',
            width: 130,
            flexShrink: 0,
          }}
        />

        {/* Starting balance */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 3, flexShrink: 0 }}>
          <span style={{ fontSize: 11, color: 'var(--t-3)', fontFamily: 'var(--font-mono)' }}>$</span>
          <input
            type="number"
            value={initialCash}
            onChange={e => setInitialCash(e.target.value)}
            min={100}
            max={10000000}
            step={1000}
            placeholder="100000"
            title="Starting balance"
            style={{
              background: 'var(--bg-input)',
              border: '1px solid var(--hairline-2)',
              borderRadius: 6,
              padding: '5px 7px',
              fontSize: 12,
              color: 'var(--t-1)',
              fontFamily: 'var(--font-mono)',
              outline: 'none',
              width: 85,
            }}
          />
        </div>

        {/* Color presets */}
        <div style={{ display: 'flex', gap: 5, alignItems: 'center', flexShrink: 0 }}>
          {PRESET_COLORS.map(c => (
            <button
              key={c}
              type="button"
              onClick={() => setColor(c)}
              title={c}
              style={{
                width: 16,
                height: 16,
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
          <input
            type="color"
            value={color}
            onChange={e => setColor(e.target.value)}
            title="Custom color"
            style={{
              width: 16, height: 16, padding: 0,
              border: '1px solid var(--hairline-2)',
              borderRadius: '50%', cursor: 'pointer', background: 'none',
            }}
          />
        </div>
      </div>

      {/* Row 2: AI toggle + buttons */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {/* AI toggle */}
        <div
          onClick={() => setAiControlled(v => !v)}
          title="Let the AI autonomously scan and trade this portfolio"
          style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', userSelect: 'none', flexShrink: 0 }}
        >
          <div style={{
            width: 28, height: 16, borderRadius: 8,
            background: aiControlled ? '#b39dff' : 'rgba(140,170,220,0.2)',
            position: 'relative', transition: 'background .2s', flexShrink: 0,
          }}>
            <div style={{
              position: 'absolute', top: 2,
              left: aiControlled ? 14 : 2,
              width: 12, height: 12, borderRadius: '50%',
              background: '#fff', transition: 'left .2s',
              boxShadow: '0 1px 3px rgba(0,0,0,0.4)',
            }} />
          </div>
          <span style={{
            fontSize: 11, fontWeight: aiControlled ? 700 : 400,
            color: aiControlled ? '#b39dff' : 'var(--t-3)',
            transition: 'color .2s',
          }}>
            AI Managed
          </span>
        </div>

        {error && <span style={{ color: 'var(--err)', fontSize: 11 }}>{error}</span>}

        <div style={{ display: 'flex', gap: 6, marginLeft: 'auto' }}>
          <button
            type="button"
            onClick={onCancel}
            style={{
              padding: '5px 12px', background: 'transparent',
              border: '1px solid var(--hairline-2)', borderRadius: 6,
              color: 'var(--t-3)', fontFamily: 'var(--font-sans)', fontSize: 12, cursor: 'pointer',
            }}
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={loading}
            style={{
              padding: '5px 14px',
              background: aiControlled ? '#b39dff' : 'var(--acc)',
              border: 'none', borderRadius: 6, color: '#fff',
              fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: 12,
              cursor: loading ? 'default' : 'pointer',
              opacity: loading ? 0.6 : 1, transition: 'background .15s',
            }}
          >
            {loading ? 'Creating…' : 'Create'}
          </button>
        </div>
      </div>
    </form>
  )
}

// ── Portfolio Tab Card ──────────────────────────────────────────────────────
function PortfolioCard({ portfolio, account, isActive, onClick, onDelete, canDelete, onContextMenu }) {
  const [hover, setHover] = useState(false)

  const pnl    = account?.pnl_day          // realized today (closed trades)
  const pnlOpen = account?.pnl_unrealized  // open position gain/loss
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
      onContextMenu={onContextMenu}
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
        <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: isActive ? 'var(--t-1)' : 'var(--t-2)' }}>
            {portfolio.ai_controlled && (
              <span style={{ fontSize: '10px', marginRight: '4px', animation: 'aiPulse 2s infinite', display: 'inline-block' }}>🤖</span>
            )}
            {portfolio.name}
          </span>
          {portfolio.ai_controlled ? (
            <span style={{
              fontSize: 9,
              fontWeight: 700,
              letterSpacing: '0.06em',
              color: '#b39dff',
              background: 'rgba(179,157,255,0.12)',
              border: '1px solid rgba(179,157,255,0.3)',
              borderRadius: 3,
              padding: '1px 4px',
              lineHeight: 1,
              flexShrink: 0,
            }}>
              AI
            </span>
          ) : null}
        </span>
        <span style={{ display: 'flex', gap: 6, alignItems: 'baseline', flexWrap: 'wrap' }}>
          <span style={{ fontSize: 11, color: 'var(--t-2)', fontFamily: 'var(--font-mono)' }}>
            {fmt(equity)}
          </span>
          {/* Day P&L — realized from closed trades today */}
          {pnlStr && (
            <span title="Day P&L — realized from closed trades today" style={{ fontSize: 10, color: pnlColor, fontFamily: 'var(--font-mono)' }}>
              {pnlStr}
            </span>
          )}
          {/* Unrealized — open positions currently up/down */}
          {pnlOpen != null && pnlOpen !== 0 && (
            <span title="Unrealized — open positions" style={{ fontSize: 9, color: pnlOpen >= 0 ? 'rgba(61,220,151,0.7)' : 'rgba(255,71,111,0.7)', fontFamily: 'var(--font-mono)' }}>
              ({pnlOpen >= 0 ? '+' : ''}{pnlOpen.toFixed(2)} open)
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
  const [accounts, setAccounts]     = useState({})
  const [showForm, setShowForm]     = useState(false)
  const [loading, setLoading]       = useState(true)
  const [ctxMenu, setCtxMenu]       = useState(null)
  const [renaming, setRenaming]     = useState(null)   // {id, name}
  const [renameVal, setRenameVal]   = useState('')
  const [confirmDel,   setConfirmDel]   = useState(null)  // portfolio to delete
  const [confirmReset, setConfirmReset] = useState(null)  // portfolio to reset
  const [errorMsg,     setErrorMsg]     = useState('')

  const loadAll = useCallback(async () => {
    if (!userId) return
    setLoading(true)
    try {
      const { data: ports } = await api.get(`/portfolios?user_id=${userId}`)
      setPortfolios(ports)

      const results = await Promise.all([
        api.get('/account?portfolio_id=0')
          .then(r => ({ id: 0, data: r.data }))
          .catch(() => ({ id: 0, data: null })),
        ...ports.map(p =>
          api.get(`/account?portfolio_id=${p.id}`)
            .then(r => ({ id: p.id, data: r.data }))
            .catch(() => ({ id: p.id, data: null }))
        ),
      ])
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

  useEffect(() => {
    const close = () => setCtxMenu(null)
    if (ctxMenu) document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [ctxMenu])

  useEffect(() => {
    if (!portfolioId) return
    api.get(`/account?portfolio_id=${portfolioId}`)
      .then(r => setAccounts(prev => ({ ...prev, [portfolioId]: r.data })))
      .catch(() => {})
  }, [portfolioId])

  async function handleCreate(name, color, initialCash, aiControlled) {
    const { data } = await api.post('/portfolios', {
      user_id: userId, name, color,
      initial_cash: initialCash,
      ai_controlled: aiControlled,
    })
    setShowForm(false)
    await loadAll()
    onSwitch(data.id)
  }

  async function handleDelete(id) {
    try {
      await api.delete(`/portfolios/${id}`)
      const remaining = portfolios.filter(p => p.id !== id)
      await loadAll()
      if (portfolioId === id && remaining.length > 0) onSwitch(remaining[0].id)
    } catch (err) {
      console.error('PortfolioTabs: delete failed', err)
      setErrorMsg(err?.response?.data?.error || 'Failed to delete portfolio.')
    } finally {
      setConfirmDel(null)
    }
  }

  const handleRename = async () => {
    const name = renameVal.trim()
    if (!name || !renaming) return
    try {
      await api.patch(`/portfolios/${renaming.id}`, { name })
      await loadAll()
    } catch (err) {
      console.error('Rename failed', err)
    } finally {
      setRenaming(null)
      setRenameVal('')
    }
  }

  const handleResetBalance = async (portfolio) => {
    try {
      await api.post(`/portfolios/${portfolio.id}/reset`)
      await loadAll()
      setCtxMenu(null)
    } catch (err) {
      console.error('Reset failed', err)
    } finally {
      setConfirmReset(null)
    }
  }

  const toggleAI = async (portfolio) => {
    try {
      const newVal = !portfolio.ai_controlled
      await api.patch(`/portfolios/${portfolio.id}`, { ai_controlled: newVal })
      await loadAll()
      setCtxMenu(null)
    } catch (err) {
      console.error('Failed to toggle AI', err)
    }
  }

  const canDelete = portfolios.length > 1

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flexShrink: 0 }}>
      <style>{`@keyframes aiPulse { 0%,100%{opacity:1} 50%{opacity:0.5} }`}</style>
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

        <PortfolioCard
          key={0}
          portfolio={{ id: 0, name: 'Real Holdings', color: '#3ddc97' }}
          account={accounts[0]}
          isActive={portfolioId === 0}
          onClick={() => onSwitch(0)}
          onDelete={null}
          canDelete={false}
        />

        {portfolios.map(p => (
          <PortfolioCard
            key={p.id}
            portfolio={p}
            account={accounts[p.id]}
            isActive={p.id === portfolioId}
            onClick={() => onSwitch(p.id)}
            onDelete={() => handleDelete(p.id)}
            canDelete={canDelete}
            onContextMenu={e => {
              e.preventDefault()
              e.stopPropagation()
              setCtxMenu({ x: e.clientX, y: e.clientY, portfolio: p })
            }}
          />
        ))}

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

      {showForm && (
        <NewPortfolioForm
          onCancel={() => setShowForm(false)}
          onCreate={handleCreate}
        />
      )}

      {renaming && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 10000,
          background: 'rgba(0,0,8,0.7)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }} onClick={() => setRenaming(null)}>
          <div onClick={e => e.stopPropagation()} style={{
            background: '#141925', border: '1px solid rgba(140,170,220,0.18)',
            borderRadius: 10, padding: '20px 24px', minWidth: 300,
            boxShadow: '0 16px 48px rgba(0,0,0,0.6)',
          }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--t-2)', marginBottom: 12, letterSpacing: '0.05em' }}>
              RENAME PORTFOLIO
            </div>
            <input
              autoFocus
              value={renameVal}
              onChange={e => setRenameVal(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleRename(); if (e.key === 'Escape') setRenaming(null) }}
              style={{
                width: '100%', boxSizing: 'border-box',
                background: 'rgba(140,170,220,0.07)', border: '1px solid rgba(140,170,220,0.2)',
                borderRadius: 6, padding: '8px 10px', fontSize: 13,
                color: 'var(--t-1)', outline: 'none', fontFamily: 'var(--font-sans)',
                marginBottom: 12,
              }}
            />
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button onClick={() => setRenaming(null)} style={{
                background: 'none', border: '1px solid rgba(140,170,220,0.2)',
                borderRadius: 6, padding: '6px 14px', color: 'var(--t-3)', cursor: 'pointer', fontSize: 12,
              }}>Cancel</button>
              <button onClick={handleRename} style={{
                background: 'rgba(179,157,255,0.15)', border: '1px solid rgba(179,157,255,0.3)',
                borderRadius: 6, padding: '6px 14px', color: '#b39dff', cursor: 'pointer', fontSize: 12, fontWeight: 700,
              }}>Rename</button>
            </div>
          </div>
        </div>
      )}

      {ctxMenu && (
        <div
          onMouseDown={e => e.stopPropagation()}
          onClick={e => e.stopPropagation()}
          style={{
            position: 'fixed', top: ctxMenu.y, left: ctxMenu.x,
            zIndex: 9999,
            background: '#141925',
            border: '1px solid rgba(140,170,220,0.18)',
            borderRadius: '8px',
            padding: '6px 0',
            minWidth: '180px',
            boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
            fontFamily: 'var(--font-sans)',
            fontSize: '13px',
          }}
        >
          {/* AI Toggle */}
          <div
            onClick={() => toggleAI(ctxMenu.portfolio)}
            style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 14px', cursor: 'pointer', color: '#e6ecf5', borderBottom: '1px solid rgba(140,170,220,0.08)' }}
            onMouseEnter={e => e.currentTarget.style.background = 'rgba(140,170,220,0.07)'}
            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
          >
            <span>🤖 AI Controlled</span>
            <div style={{ width: '32px', height: '18px', borderRadius: '9px', background: ctxMenu.portfolio.ai_controlled ? '#3ddc97' : 'rgba(140,170,220,0.2)', position: 'relative', transition: 'background 0.2s', flexShrink: 0 }}>
              <div style={{ position: 'absolute', top: '2px', left: ctxMenu.portfolio.ai_controlled ? '16px' : '2px', width: '14px', height: '14px', borderRadius: '50%', background: '#fff', transition: 'left 0.2s' }} />
            </div>
          </div>
          {/* Rename */}
          <div
            onClick={() => { setRenaming({ id: ctxMenu.portfolio.id, name: ctxMenu.portfolio.name }); setRenameVal(ctxMenu.portfolio.name); setCtxMenu(null) }}
            style={{ padding: '8px 14px', cursor: 'pointer', color: '#aab4c5' }}
            onMouseEnter={e => e.currentTarget.style.background = 'rgba(140,170,220,0.07)'}
            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
          >
            ✎ Rename
          </div>
          {/* Refresh P&L */}
          <div
            onClick={async () => {
              try {
                await loadAll()
                setCtxMenu(null)
              } catch {}
            }}
            style={{ padding: '8px 14px', cursor: 'pointer', color: '#4ad9ff' }}
            onMouseEnter={e => e.currentTarget.style.background = 'rgba(140,170,220,0.07)'}
            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
          >
            ↻ Refresh P&L
          </div>
          {/* Reset Balance */}
          <div
            onClick={() => { setConfirmReset(ctxMenu.portfolio); setCtxMenu(null) }}
            style={{ padding: '8px 14px', cursor: 'pointer', color: '#aab4c5' }}
            onMouseEnter={e => e.currentTarget.style.background = 'rgba(140,170,220,0.07)'}
            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
          >
            ↺ Reset Balance
          </div>
          {/* Delete — only for non-default portfolios */}
          {ctxMenu.portfolio.id !== 1 && (
            <div
              onClick={() => { setConfirmDel(ctxMenu.portfolio); setCtxMenu(null) }}
              style={{ padding: '8px 14px', cursor: 'pointer', color: '#ff476f', borderTop: '1px solid rgba(140,170,220,0.08)', marginTop: '4px' }}
              onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,71,111,0.08)'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >
              Delete Portfolio
            </div>
          )}
        </div>
      )}

      {confirmDel && (
        <ConfirmModal
          message={`Delete "${confirmDel.name}"?`}
          detail="This cannot be undone."
          confirmLabel="Delete"
          danger
          onConfirm={() => handleDelete(confirmDel.id)}
          onCancel={() => setConfirmDel(null)}
        />
      )}
      {confirmReset && (
        <ConfirmModal
          message={`Reset "${confirmReset.name}" to $100,000?`}
          detail="All positions and trade history will be cleared."
          confirmLabel="Reset"
          danger
          onConfirm={() => handleResetBalance(confirmReset)}
          onCancel={() => setConfirmReset(null)}
        />
      )}
      {errorMsg && (
        <ConfirmModal
          message={errorMsg}
          alertOnly
          onConfirm={() => setErrorMsg('')}
          onCancel={() => setErrorMsg('')}
        />
      )}
    </div>
  )
}

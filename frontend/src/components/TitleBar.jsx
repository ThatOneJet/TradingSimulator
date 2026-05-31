import { useState, useEffect } from 'react'

const pyw = () => window.pywebview?.api
const win = {
  minimize: () => window.electronAPI?.minimize() ?? pyw()?.minimize_window(),
  maximize: () => window.electronAPI?.maximize() ?? pyw()?.maximize_window(),
  restore:  () => window.electronAPI?.restore()  ?? pyw()?.restore_window(),
  close:    () => window.electronAPI?.close()    ?? pyw()?.close_window(),
  move:     (x, y) => window.electronAPI?.move(x, y) ?? pyw()?.move_window(x, y),
}

function MinimizeIcon() { return <svg width="10" height="10" viewBox="0 0 10 10"><rect y="4.5" width="10" height="1" fill="currentColor"/></svg> }
function MaximizeIcon() { return <svg width="10" height="10" viewBox="0 0 10 10"><rect x=".5" y=".5" width="9" height="9" stroke="currentColor" strokeWidth="1" fill="none"/></svg> }
function RestoreIcon()  { return <svg width="10" height="10" viewBox="0 0 10 10"><rect x="0" y="3" width="7" height="7" stroke="currentColor" strokeWidth="1" fill="none"/><polyline points="3,3 3,0 10,0 10,7 7,7" stroke="currentColor" strokeWidth="1" fill="none"/></svg> }
function CloseIcon()    { return <svg width="10" height="10" viewBox="0 0 10 10"><line x1="0" y1="0" x2="10" y2="10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/><line x1="10" y1="0" x2="0" y2="10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg> }

export default function TitleBar({ symbol, account }) {
  const [maximized, setMaximized] = useState(false)
  const [time, setTime] = useState('')

  useEffect(() => {
    const tick = () => {
      const now = new Date()
      const tz  = now.toLocaleTimeString('en-US', { timeZoneName: 'short' }).split(' ').pop()
      const t   = now.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', second: '2-digit', hour12: true })
      setTime(`${t} ${tz}`)
    }
    tick(); const id = setInterval(tick, 1000); return () => clearInterval(id)
  }, [])

  useEffect(() => { window.electronAPI?.onMaximize?.(setMaximized) }, [])

  function startDrag(e) {
    if (e.target.closest('.tb-controls')) return
    if (e.button !== 0) return
    e.preventDefault()
    const startX = e.screenX, startY = e.screenY
    const originX = window.screenX, originY = window.screenY
    const onMove = (ev) => win.move(originX + ev.screenX - startX, originY + ev.screenY - startY)
    const onUp = () => { document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp) }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }

  const toggleMax = () => { maximized ? win.restore() : win.maximize(); if (!window.electronAPI) setMaximized(m => !m) }

  return (
    <div className="titlebar" onMouseDown={startDrag} onDoubleClick={toggleMax}>
      <span className="tb-dot" />
      <span className="tb-wordmark">TRADESIM</span>
      <span className="tb-sep" style={{ color: 'var(--t-3)' }}>/</span>
      <span className="tb-symbol" style={{ color: 'var(--cy)' }}>{symbol}</span>
      <div className="tb-spacer" />
      {account && (
        <span className="tb-cluster-item">
          <span className="lbl" style={{ color: 'var(--t-3)' }}>EQUITY</span>
          <span className="val mono" style={{ color: 'var(--t-1)' }}>
            ${Number(account.equity).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        </span>
      )}
      {account && (
        <span className="tb-cluster-item">
          <span className="lbl" style={{ color: 'var(--t-3)' }}>DAY P&L</span>
          <span className="val mono" style={{ color: (account.pnl_day || 0) >= 0 ? 'var(--ok)' : 'var(--err)' }}>
            {(account.pnl_day || 0) >= 0 ? '+' : ''}{Number(account.pnl_day || 0).toFixed(2)}
          </span>
        </span>
      )}
      {account && account.pnl_unrealized != null && (
        <span className="tb-cluster-item">
          <span className="lbl" style={{ color: 'var(--t-3)' }}>OPEN</span>
          <span className="val mono" style={{ color: account.pnl_unrealized >= 0 ? 'var(--ok)' : 'var(--err)' }}>
            {account.pnl_unrealized >= 0 ? '+' : ''}{Number(account.pnl_unrealized).toFixed(2)}
          </span>
        </span>
      )}
      <span className="tb-cluster-item" style={{ borderLeft: '1px solid var(--hairline)' }}>
        <span className="tb-dot" style={{ background: 'var(--ok)', boxShadow: '0 0 6px var(--ok)' }} />
        <span className="lbl" style={{ color: 'var(--t-3)' }}>PAPER</span>
      </span>
      <span className="tb-cluster-item" style={{ borderLeft: '1px solid var(--hairline)' }}>
        <span className="val mono" style={{ color: 'var(--t-3)' }}>{time}</span>
      </span>
      <div className="tb-controls">
        <button className="tb-btn" onClick={win.minimize}><MinimizeIcon /></button>
        <button className="tb-btn" onClick={toggleMax}>{maximized ? <RestoreIcon /> : <MaximizeIcon />}</button>
        <button className="tb-btn tb-close" onClick={win.close}><CloseIcon /></button>
      </div>
    </div>
  )
}

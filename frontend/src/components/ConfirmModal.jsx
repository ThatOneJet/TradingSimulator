import { useEffect } from 'react'

const overlay = {
  position: 'fixed', inset: 0, zIndex: 9999,
  background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(3px)',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
}
const box = {
  background: '#141922', border: '1px solid rgba(140,170,220,0.15)',
  borderRadius: 10, padding: '24px 28px', minWidth: 300, maxWidth: 420,
  boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
  fontFamily: 'var(--font-sans)',
}

export default function ConfirmModal({
  message,
  detail,
  confirmLabel = 'Confirm',
  cancelLabel  = 'Cancel',
  danger       = false,
  alertOnly    = false,   // no cancel button — just OK
  onConfirm,
  onCancel,
}) {
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onCancel?.() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onCancel])

  return (
    <div style={overlay} onClick={(e) => { if (e.target === e.currentTarget) onCancel?.() }}>
      <div style={box}>
        <p style={{ margin: '0 0 6px', fontSize: 13, fontWeight: 600, color: 'var(--t-1)', lineHeight: 1.4 }}>
          {message}
        </p>
        {detail && (
          <p style={{ margin: '0 0 18px', fontSize: 11, color: 'var(--t-3)', lineHeight: 1.5 }}>
            {detail}
          </p>
        )}
        {!detail && <div style={{ marginBottom: 18 }} />}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          {!alertOnly && (
            <button
              onClick={onCancel}
              style={{
                padding: '7px 18px', border: '1px solid rgba(140,170,220,0.15)',
                borderRadius: 6, cursor: 'pointer', fontSize: 12,
                background: 'transparent', color: 'var(--t-3)',
                fontFamily: 'var(--font-sans)',
              }}
            >
              {cancelLabel}
            </button>
          )}
          <button
            autoFocus
            onClick={onConfirm}
            style={{
              padding: '7px 18px', border: 'none', borderRadius: 6, cursor: 'pointer',
              fontSize: 12, fontWeight: 700, fontFamily: 'var(--font-sans)',
              background: danger ? 'rgba(255,71,111,0.2)' : 'rgba(179,157,255,0.15)',
              color: danger ? '#ff476f' : '#b39dff',
              border: danger ? '1px solid rgba(255,71,111,0.3)' : '1px solid rgba(179,157,255,0.25)',
            }}
          >
            {alertOnly ? 'OK' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

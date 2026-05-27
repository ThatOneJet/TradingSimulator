import { useState } from 'react'
import api from '../api.js'

const AVATAR_COLORS = ['#ff6a1a', '#4ad9ff', '#3ddc97', '#f5b342', '#b07aff', '#ff476f']

// ── shared primitives ──────────────────────────────────────────────────────

function SectionCard({ title, subtitle, children }) {
  return (
    <div style={{
      background:   'var(--bg-card)',
      border:       '1px solid var(--hairline-2)',
      borderRadius: 'var(--radius)',
      padding:      '20px 22px',
      marginBottom: 16,
      position:     'relative',
      overflow:     'hidden',
    }}>
      {/* left accent bar */}
      <div style={{
        position:     'absolute',
        left: 0, top: 12, bottom: 12,
        width:        2,
        background:   'var(--acc)',
        opacity:      0.5,
        borderRadius: '0 2px 2px 0',
      }} />
      <div style={{ marginBottom: subtitle ? 4 : 16 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--t-1)', letterSpacing: '0.03em' }}>
          {title}
        </div>
        {subtitle && (
          <div style={{ fontSize: 11, color: 'var(--t-3)', marginTop: 2 }}>{subtitle}</div>
        )}
      </div>
      {subtitle && <div style={{ marginBottom: 14 }} />}
      {children}
    </div>
  )
}

function Label({ children }) {
  return (
    <div style={{
      fontSize:      11,
      fontWeight:    600,
      letterSpacing: '0.06em',
      color:         'var(--t-3)',
      textTransform: 'uppercase',
      marginBottom:  6,
    }}>
      {children}
    </div>
  )
}

function TextInput({ value, onChange, placeholder, readOnly }) {
  const [focused, setFocused] = useState(false)
  return (
    <input
      type="text"
      value={value}
      onChange={e => onChange?.(e.target.value)}
      placeholder={placeholder || ''}
      readOnly={readOnly}
      style={{
        width:        '100%',
        background:   readOnly ? 'var(--bg-outside)' : 'var(--bg-input)',
        border:       `1px solid ${focused ? 'var(--acc-line)' : 'var(--hairline-2)'}`,
        borderRadius: 6,
        padding:      '9px 12px',
        fontSize:     13,
        color:        readOnly ? 'var(--t-3)' : 'var(--t-1)',
        fontFamily:   'var(--font-sans)',
        outline:      'none',
        cursor:       readOnly ? 'default' : 'text',
        transition:   'border-color .15s',
        marginBottom: 12,
      }}
      onFocus={() => !readOnly && setFocused(true)}
      onBlur={() => setFocused(false)}
      autoComplete="off"
    />
  )
}

function Btn({ children, onClick, disabled, variant = 'primary', style = {} }) {
  const [hover, setHover] = useState(false)
  const base = {
    padding:      '9px 18px',
    fontSize:     13,
    fontWeight:   600,
    fontFamily:   'var(--font-sans)',
    borderRadius: 6,
    border:       'none',
    cursor:       disabled ? 'not-allowed' : 'pointer',
    opacity:      disabled ? 0.5 : 1,
    transition:   'background .15s, box-shadow .15s',
    ...style,
  }

  const styles = {
    primary: {
      ...base,
      background: hover && !disabled ? 'var(--acc-hi)' : 'var(--acc)',
      color:      '#fff',
      boxShadow:  hover && !disabled ? '0 0 14px var(--acc-glow)' : 'none',
    },
    danger: {
      ...base,
      background: hover && !disabled ? 'rgba(255,71,111,0.22)' : 'rgba(255,71,111,0.10)',
      color:      'var(--err)',
      border:     '1px solid rgba(255,71,111,0.30)',
      boxShadow:  hover && !disabled ? '0 0 10px rgba(255,71,111,0.25)' : 'none',
    },
    ghost: {
      ...base,
      background: hover && !disabled ? 'var(--hairline-2)' : 'transparent',
      color:      'var(--t-2)',
      border:     '1px solid var(--hairline-2)',
    },
  }

  return (
    <button
      onClick={disabled ? undefined : onClick}
      style={styles[variant]}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      {children}
    </button>
  )
}

function Toast({ msg }) {
  if (!msg) return null
  return (
    <div style={{
      marginTop:    10,
      padding:      '8px 12px',
      borderRadius: 6,
      fontSize:     12,
      fontFamily:   'var(--font-sans)',
      background:   msg.ok ? 'rgba(61,220,151,0.10)' : 'rgba(255,71,111,0.10)',
      border:       `1px solid ${msg.ok ? 'rgba(61,220,151,0.25)' : 'rgba(255,71,111,0.25)'}`,
      color:        msg.ok ? 'var(--ok)' : 'var(--err)',
    }}>
      {msg.text}
    </div>
  )
}

// ── main component ─────────────────────────────────────────────────────────

export default function Settings({ user, onUserUpdate, portfolioId, onReset, onLogout }) {
  // ── Profile state ───────────────────────────────────────────────────────
  const [displayName,    setDisplayName]    = useState(user?.display_name || user?.username || '')
  const [avatarColor,    setAvatarColor]    = useState(user?.avatar_color || '#ff6a1a')
  const [profileSaving,  setProfileSaving]  = useState(false)
  const [profileMsg,     setProfileMsg]     = useState(null)

  // ── Reset state ─────────────────────────────────────────────────────────
  const [resetConfirm,   setResetConfirm]   = useState(false)
  const [resetting,      setResetting]      = useState(false)
  const [resetMsg,       setResetMsg]       = useState(null)

  // ── Handlers ────────────────────────────────────────────────────────────
  async function saveProfile() {
    if (!user?.user_id) return
    setProfileSaving(true)
    setProfileMsg(null)
    try {
      const { data } = await api.patch(`/users/${user.user_id}`, {
        display_name: displayName.trim() || user.username,
        avatar_color: avatarColor,
      })
      const updated = { ...user, display_name: data.display_name, avatar_color: data.avatar_color }
      localStorage.setItem('ts_user', JSON.stringify(updated))
      if (onUserUpdate) onUserUpdate(updated)
      setProfileMsg({ ok: true, text: 'Profile saved successfully.' })
    } catch {
      setProfileMsg({ ok: false, text: 'Failed to save profile.' })
    } finally {
      setProfileSaving(false)
    }
  }

  async function doReset() {
    setResetting(true)
    setResetMsg(null)
    try {
      await api.post('/account/reset', { portfolio_id: portfolioId || 1 })
      if (onReset) onReset()
      setResetMsg({ ok: true, text: 'Account reset to $100,000. All positions and trade history cleared.' })
      setResetConfirm(false)
    } catch {
      setResetMsg({ ok: false, text: 'Reset failed — try again.' })
    } finally {
      setResetting(false)
    }
  }

  // ── Layout ───────────────────────────────────────────────────────────────
  return (
    <div style={{
      padding:    '24px 28px',
      maxWidth:   560,
      margin:     '0 auto',
      height:     '100%',
      overflowY:  'auto',
    }}>

      {/* Page heading */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--t-1)', letterSpacing: '0.02em' }}>
          Settings
        </div>
        <div style={{ fontSize: 12, color: 'var(--t-3)', marginTop: 3 }}>
          Manage your profile and account preferences
        </div>
      </div>

      {/* ── Profile section ─────────────────────────────────────────────── */}
      <SectionCard title="Profile" subtitle="Your public display name and avatar color">
        <div style={{ marginBottom: 12 }}>
          <Label>Username</Label>
          <TextInput value={user?.username || ''} readOnly placeholder="username" />
        </div>

        <div style={{ marginBottom: 16 }}>
          <Label>Display Name</Label>
          <TextInput
            value={displayName}
            onChange={setDisplayName}
            placeholder="Your Name"
          />
        </div>

        <div style={{ marginBottom: 18 }}>
          <Label>Avatar Color</Label>
          <div style={{ display: 'flex', gap: 8, marginTop: 2 }}>
            {AVATAR_COLORS.map(c => (
              <button
                key={c}
                onClick={() => setAvatarColor(c)}
                style={{
                  width:        28,
                  height:       28,
                  borderRadius: '50%',
                  background:   c,
                  border:       avatarColor === c
                    ? '2px solid #fff'
                    : '2px solid transparent',
                  boxShadow:    avatarColor === c
                    ? `0 0 0 2px ${c}, 0 0 10px ${c}66`
                    : 'none',
                  cursor:       'pointer',
                  transition:   'box-shadow .15s',
                  flexShrink:   0,
                }}
              />
            ))}

            {/* Preview */}
            <div style={{
              marginLeft:   12,
              width:        28,
              height:       28,
              borderRadius: '50%',
              background:   avatarColor,
              display:      'flex',
              alignItems:   'center',
              justifyContent: 'center',
              fontSize:     11,
              fontWeight:   700,
              color:        '#fff',
              flexShrink:   0,
              border:       '1px solid var(--hairline-2)',
            }}>
              {(displayName || user?.username || 'U').slice(0, 2).toUpperCase()}
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Btn onClick={saveProfile} disabled={profileSaving}>
            {profileSaving ? 'Saving…' : 'Save Changes'}
          </Btn>
        </div>
        <Toast msg={profileMsg} />
      </SectionCard>

      {/* ── Account Reset section ───────────────────────────────────────── */}
      <SectionCard title="Reset Account" subtitle="Restore paper trading balance to $100,000">
        <div style={{ fontSize: 13, color: 'var(--t-2)', marginBottom: 16, lineHeight: 1.6 }}>
          This will close all open positions, clear your entire trade history, and
          reset your cash balance to{' '}
          <span style={{ color: 'var(--ok)', fontFamily: 'var(--font-mono)' }}>$100,000</span>{' '}
          for the current portfolio.
        </div>

        {!resetConfirm ? (
          <Btn variant="danger" onClick={() => setResetConfirm(true)}>
            Reset Account
          </Btn>
        ) : (
          <div>
            <div style={{
              padding:      '10px 14px',
              background:   'rgba(255,71,111,0.08)',
              border:       '1px solid rgba(255,71,111,0.25)',
              borderRadius: 6,
              fontSize:     12,
              color:        'var(--err)',
              marginBottom: 12,
            }}>
              Are you sure? This cannot be undone.
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <Btn variant="danger" onClick={doReset} disabled={resetting}>
                {resetting ? 'Resetting…' : 'Yes, Reset Now'}
              </Btn>
              <Btn variant="ghost" onClick={() => setResetConfirm(false)}>
                Cancel
              </Btn>
            </div>
          </div>
        )}
        <Toast msg={resetMsg} />
      </SectionCard>

      {/* ── Session section ─────────────────────────────────────────────── */}
      <SectionCard title="Session">
        <div style={{ fontSize: 13, color: 'var(--t-2)', marginBottom: 16, lineHeight: 1.6 }}>
          Signed in as{' '}
          <span style={{ color: 'var(--t-1)', fontWeight: 600 }}>
            {user?.username}
          </span>
          .
        </div>
        <Btn variant="ghost" onClick={onLogout}>
          Sign Out
        </Btn>
      </SectionCard>

    </div>
  )
}

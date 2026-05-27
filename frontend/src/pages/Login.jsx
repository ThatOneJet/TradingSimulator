import { useState } from 'react'
import api from '../api.js'

const WORDMARK = (
  <div style={{
    fontFamily: 'var(--font-mono)',
    fontWeight: 700,
    fontSize: 22,
    letterSpacing: '0.18em',
    color: 'var(--acc)',
    textAlign: 'center',
    marginBottom: 28,
    userSelect: 'none',
  }}>
    TRADESIM
  </div>
)

const inputStyle = {
  width: '100%',
  background: 'var(--bg-input)',
  border: '1px solid var(--hairline-2)',
  borderRadius: 6,
  padding: '9px 12px',
  fontSize: 13,
  color: 'var(--t-1)',
  fontFamily: 'var(--font-sans)',
  outline: 'none',
  transition: 'border-color .15s',
}

const labelStyle = {
  display: 'block',
  fontSize: 11,
  fontWeight: 600,
  letterSpacing: '0.06em',
  color: 'var(--t-3)',
  textTransform: 'uppercase',
  marginBottom: 5,
}

const fieldStyle = { marginBottom: 14 }

const submitStyle = {
  width: '100%',
  padding: '10px 0',
  background: 'var(--acc)',
  color: '#fff',
  fontFamily: 'var(--font-sans)',
  fontWeight: 700,
  fontSize: 13,
  letterSpacing: '0.06em',
  border: 'none',
  borderRadius: 6,
  cursor: 'pointer',
  marginTop: 4,
  transition: 'background .15s, box-shadow .15s',
}

const submitHoverStyle = {
  ...submitStyle,
  background: 'var(--acc-hi)',
  boxShadow: '0 0 16px var(--acc-glow)',
}

function Field({ label, type, value, onChange, placeholder }) {
  const [focused, setFocused] = useState(false)
  return (
    <div style={fieldStyle}>
      <label style={labelStyle}>{label}</label>
      <input
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder || ''}
        style={{
          ...inputStyle,
          borderColor: focused ? 'var(--acc-line)' : 'var(--hairline-2)',
        }}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        autoComplete={type === 'password' ? 'current-password' : 'off'}
      />
    </div>
  )
}

function LoginForm({ onLogin }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError]       = useState('')
  const [loading, setLoading]   = useState(false)
  const [hover, setHover]       = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    if (!username.trim() || !password) { setError('Enter username and password.'); return }
    setLoading(true)
    try {
      const { data } = await api.post('/auth/login', { username: username.trim(), password })
      localStorage.setItem('ts_user', JSON.stringify(data))
      onLogin(data)
    } catch (err) {
      const msg = err.response?.data?.error
      setError(msg || (err.response?.status === 401 ? 'Invalid username or password.' : 'Login failed.'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate>
      <Field label="Username" type="text"     value={username} onChange={setUsername} placeholder="your_username" />
      <Field label="Password" type="password" value={password} onChange={setPassword} placeholder="••••••••" />
      {error && (
        <div style={{ color: 'var(--err)', fontSize: 12, marginBottom: 10, marginTop: -6 }}>
          {error}
        </div>
      )}
      <button
        type="submit"
        disabled={loading}
        style={hover && !loading ? submitHoverStyle : { ...submitStyle, opacity: loading ? 0.6 : 1 }}
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
      >
        {loading ? 'Signing in…' : 'Sign In'}
      </button>
    </form>
  )
}

function RegisterForm({ onLogin }) {
  const [displayName, setDisplayName] = useState('')
  const [username, setUsername]       = useState('')
  const [password, setPassword]       = useState('')
  const [confirm, setConfirm]         = useState('')
  const [error, setError]             = useState('')
  const [loading, setLoading]         = useState(false)
  const [hover, setHover]             = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')

    if (username.trim().length < 2) { setError('Username must be at least 2 characters.'); return }
    if (password.length < 4)        { setError('Password must be at least 4 characters.'); return }
    if (password !== confirm)       { setError('Passwords do not match.'); return }

    setLoading(true)
    try {
      const { data } = await api.post('/auth/register', {
        username:     username.trim(),
        password,
        display_name: displayName.trim() || username.trim(),
      })
      localStorage.setItem('ts_user', JSON.stringify(data))
      onLogin(data)
    } catch (err) {
      const msg = err.response?.data?.error
      if (err.response?.status === 409) {
        setError('Username is already taken.')
      } else {
        setError(msg || 'Registration failed.')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate>
      <Field label="Display Name" type="text"     value={displayName} onChange={setDisplayName} placeholder="Your Name" />
      <Field label="Username"     type="text"     value={username}    onChange={setUsername}    placeholder="your_username" />
      <Field label="Password"     type="password" value={password}    onChange={setPassword}    placeholder="Min 4 characters" />
      <Field label="Confirm Password" type="password" value={confirm} onChange={setConfirm}    placeholder="Repeat password" />
      {error && (
        <div style={{ color: 'var(--err)', fontSize: 12, marginBottom: 10, marginTop: -6 }}>
          {error}
        </div>
      )}
      <button
        type="submit"
        disabled={loading}
        style={hover && !loading ? submitHoverStyle : { ...submitStyle, opacity: loading ? 0.6 : 1 }}
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
      >
        {loading ? 'Creating account…' : 'Create Account'}
      </button>
    </form>
  )
}

export default function Login({ onLogin }) {
  const [tab, setTab] = useState('login')

  const tabBase = {
    flex: 1,
    padding: '8px 0',
    fontSize: 13,
    fontWeight: 600,
    fontFamily: 'var(--font-sans)',
    border: 'none',
    borderRadius: 6,
    cursor: 'pointer',
    transition: 'all .15s',
    background: 'transparent',
  }

  const tabActive = {
    ...tabBase,
    background: 'var(--acc-soft)',
    color: 'var(--acc)',
    boxShadow: 'inset 0 -2px 0 var(--acc)',
  }

  const tabInactive = {
    ...tabBase,
    color: 'var(--t-3)',
  }

  return (
    <div style={{
      minHeight: '100vh',
      background: 'var(--bg-outside)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: 'var(--font-sans)',
    }}>
      <div style={{
        width: '100%',
        maxWidth: 380,
        background: 'var(--bg-card)',
        border: '1px solid var(--hairline-2)',
        borderRadius: 12,
        padding: '32px 28px 28px',
        boxShadow: '0 8px 40px rgba(0,0,0,0.55)',
        position: 'relative',
      }}>
        {/* Left accent bar */}
        <div style={{
          position: 'absolute',
          left: 0,
          top: 16,
          bottom: 16,
          width: 3,
          background: 'var(--acc)',
          borderRadius: '0 2px 2px 0',
          opacity: 0.85,
        }} />

        {WORDMARK}

        {/* Tab pills */}
        <div style={{
          display: 'flex',
          gap: 4,
          background: 'var(--bg-input)',
          borderRadius: 8,
          padding: 3,
          marginBottom: 24,
          border: '1px solid var(--hairline-2)',
        }}>
          <button
            type="button"
            onClick={() => setTab('login')}
            style={tab === 'login' ? tabActive : tabInactive}
          >
            Log In
          </button>
          <button
            type="button"
            onClick={() => setTab('register')}
            style={tab === 'register' ? tabActive : tabInactive}
          >
            Create Account
          </button>
        </div>

        {tab === 'login'
          ? <LoginForm    onLogin={onLogin} />
          : <RegisterForm onLogin={onLogin} />
        }
      </div>
    </div>
  )
}

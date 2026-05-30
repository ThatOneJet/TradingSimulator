import { useState, useEffect } from 'react'
import axios from 'axios'
const riskApi = axios.create({ baseURL: '/api', timeout: 30000 })

const GRADE_COLOR = {
  'A': '#3ddc97', 'B+': '#7ed97c', 'B': '#f5b342',
  'C': '#ff9a3c', 'D': '#ff476f', 'F': '#ff476f',
}

const REGIME_DISPLAY = {
  'trending_up':    { label: 'Trending Up',    icon: '↗', color: '#3ddc97' },
  'trending_down':  { label: 'Trending Down',  icon: '↘', color: '#ff476f' },
  'consolidating':  { label: 'Consolidating',  icon: '↔', color: '#f5b342' },
  'high_volatility':{ label: 'High Volatility', icon: '⚡', color: '#ff9a3c' },
  'neutral':        { label: 'Neutral',         icon: '→', color: '#6b7689' },
}

export default function RiskPanel({ symbol, portfolioId, price }) {
  const [risk, setRisk] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!symbol) return
    setLoading(true)
    setError(null)
    riskApi.get(`/risk/${symbol}?portfolio_id=${portfolioId || 1}`)
      .then(r => { setRisk(r.data); setError(null) })
      .catch(e => {
        setRisk(null)
        setError(e?.code === 'ECONNABORTED' ? 'timeout' : 'error')
      })
      .finally(() => setLoading(false))
  }, [symbol, portfolioId])

  if (loading) return (
    <div style={{ padding: '24px', textAlign: 'center', color: '#6b7689', fontSize: '13px' }}>
      <div style={{ marginBottom: '8px' }}>Computing risk analysis...</div>
      <div style={{ fontSize: '11px', color: '#475061' }}>First load may take 15–20s</div>
    </div>
  )

  if (!risk) return (
    <div style={{ padding: '24px', textAlign: 'center', color: '#6b7689', fontSize: '13px' }}>
      {error === 'timeout'
        ? <><div>Timed out — market data is loading</div><div style={{ fontSize: '11px', marginTop: '6px', color: '#475061' }}>Switch tabs and come back in a moment</div></>
        : <div>No risk data for {symbol}</div>
      }
    </div>
  )

  const gradeColor = GRADE_COLOR[risk.risk_grade] || '#6b7689'
  const regime = REGIME_DISPLAY[risk.regime] || REGIME_DISPLAY['neutral']
  const ddFill = Math.min(100, (risk.max_drawdown_pct / 10) * 100)  // 10% max = full
  const suggestedCost = risk.suggested_shares && price
    ? (risk.suggested_shares * price).toLocaleString('en-US', { maximumFractionDigits: 0 })
    : null

  const rrTotal = 1 + risk.rr_ratio
  const riskPct = rrTotal > 0 ? (1 / rrTotal) * 100 : 33
  const rewardPct = rrTotal > 0 ? (risk.rr_ratio / rrTotal) * 100 : 67

  const row = (label, value, extra = null) => (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '7px 0', borderBottom: '1px solid rgba(140,170,220,0.06)' }}>
      <span style={{ fontSize: '12px', color: '#6b7689' }}>{label}</span>
      <span style={{ fontSize: '12px', color: '#e6ecf5', fontFamily: 'var(--font-mono)' }}>
        {value}
        {extra}
      </span>
    </div>
  )

  return (
    <div style={{ padding: '14px', fontFamily: 'var(--font-sans)' }}>
      {/* Grade + Regime row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{
            width: '52px', height: '52px', borderRadius: '10px',
            background: `${gradeColor}18`,
            border: `2px solid ${gradeColor}`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: '22px', fontWeight: 800, color: gradeColor,
            fontFamily: 'var(--font-mono)',
          }}>
            {risk.risk_grade}
          </div>
          <div>
            <div style={{ fontSize: '13px', color: '#e6ecf5', fontWeight: 600 }}>Risk Grade</div>
            <div style={{ fontSize: '11px', color: '#6b7689', marginTop: '2px' }}>
              {risk.risk_grade === 'A' ? 'Excellent setup' :
               risk.risk_grade === 'B+' ? 'Good setup' :
               risk.risk_grade === 'B' ? 'Acceptable' :
               risk.risk_grade === 'C' ? 'Use caution' : 'High risk'}
            </div>
          </div>
        </div>
        <div style={{
          padding: '4px 10px', borderRadius: '20px',
          background: `${regime.color}18`,
          border: `1px solid ${regime.color}40`,
          fontSize: '11px', color: regime.color,
          display: 'flex', alignItems: 'center', gap: '4px',
        }}>
          <span>{regime.icon}</span>
          <span>{regime.label}</span>
        </div>
      </div>

      {/* Max Drawdown bar */}
      <div style={{ marginBottom: '14px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
          <span style={{ fontSize: '11px', color: '#6b7689' }}>Max Drawdown Estimate</span>
          <span style={{ fontSize: '11px', color: '#e6ecf5', fontFamily: 'var(--font-mono)' }}>{risk.max_drawdown_pct}%</span>
        </div>
        <div style={{ height: '4px', background: 'rgba(140,170,220,0.1)', borderRadius: '2px', overflow: 'hidden' }}>
          <div style={{
            height: '100%',
            width: `${ddFill}%`,
            background: ddFill < 40 ? '#3ddc97' : ddFill < 70 ? '#f5b342' : '#ff476f',
            borderRadius: '2px', transition: 'width 0.5s',
          }} />
        </div>
      </div>

      {/* R:R visualization */}
      <div style={{ marginBottom: '14px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
          <span style={{ fontSize: '11px', color: '#6b7689' }}>Risk / Reward</span>
          <span style={{ fontSize: '11px', color: '#e6ecf5', fontFamily: 'var(--font-mono)' }}>1 : {risk.rr_ratio}</span>
        </div>
        <div style={{ display: 'flex', height: '6px', borderRadius: '3px', overflow: 'hidden' }}>
          <div style={{ width: `${riskPct}%`, background: '#ff476f' }} />
          <div style={{ width: `${rewardPct}%`, background: '#3ddc97' }} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '3px' }}>
          <span style={{ fontSize: '10px', color: '#ff476f' }}>Risk</span>
          <span style={{ fontSize: '10px', color: '#3ddc97' }}>Reward</span>
        </div>
      </div>

      {/* Detail rows */}
      <div>
        {row('VaR (95%)', `$${risk.var_95} / share`)}
        {row('Stop Quality', (
          <span style={{
            padding: '1px 8px', borderRadius: '4px', fontSize: '11px',
            background: risk.stop_quality === 'adequate' ? 'rgba(61,220,151,0.15)' : risk.stop_quality === 'tight' ? 'rgba(245,179,66,0.15)' : 'rgba(140,170,220,0.1)',
            color: risk.stop_quality === 'adequate' ? '#3ddc97' : risk.stop_quality === 'tight' ? '#f5b342' : '#6b7689',
            border: `1px solid ${risk.stop_quality === 'adequate' ? 'rgba(61,220,151,0.3)' : risk.stop_quality === 'tight' ? 'rgba(245,179,66,0.3)' : 'rgba(140,170,220,0.1)'}`,
          }}>{risk.stop_quality}</span>
        ))}
        {risk.suggested_shares > 0 && row(
          'Suggested Size',
          `${risk.suggested_shares} shares${suggestedCost ? ` (~$${suggestedCost})` : ''}`
        )}
        {row('ATR Volatility', `${risk.atr_pct}%`)}
      </div>

      {/* Invalidation warning */}
      {risk.invalidation_price > 0 && (
        <div style={{
          marginTop: '12px', padding: '10px 12px', borderRadius: '8px',
          background: 'rgba(245,179,66,0.08)', border: '1px solid rgba(245,179,66,0.2)',
        }}>
          <div style={{ fontSize: '10px', color: '#f5b342', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '3px' }}>Invalidation Level</div>
          <div style={{ fontSize: '13px', color: '#e6ecf5', fontFamily: 'var(--font-mono)' }}>
            Exit if price drops below ${risk.invalidation_price.toFixed(2)}
          </div>
        </div>
      )}
    </div>
  )
}

import { useState, useEffect, useCallback } from 'react'
import api from '../api.js'

const SECTOR_COLORS = {
  Technology: '#4ad9ff', Financials: '#f59e0b', Healthcare: '#4ade80',
  Consumer: '#fb923c', Energy: '#ff6a6a', Industrials: '#a78bfa',
  Communication: '#38bdf8', Materials: '#86efac', 'Real Estate': '#fbbf24',
  ETF: '#94a3b8', Other: '#64748b',
}

function HeatmapBox({ symbol, chgPct, price, weight, onClick }) {
  const pct = chgPct || 0
  const intensity = Math.min(1, Math.abs(pct) / 3)
  let bg
  if (pct > 0.1)       bg = `rgba(${Math.round(30+intensity*20)},${Math.round(140+intensity*80)},${Math.round(60+intensity*30)},0.85)`
  else if (pct < -0.1) bg = `rgba(${Math.round(160+intensity*80)},${Math.round(35+intensity*15)},${Math.round(35+intensity*15)},0.85)`
  else                 bg = 'rgba(55,65,85,0.75)'

  const minW = Math.max(55, Math.min(200, weight * 1.9))
  const h    = Math.max(45, Math.min(110, weight * 1.1))
  const fs   = Math.max(8, Math.min(13, weight / 8))

  const displaySym = symbol.replace('-USD','').replace('=X','').replace('=F','')
  const displayPrice = price >= 10000 ? `${(price/1000).toFixed(1)}k`
                     : price >= 1000  ? price.toFixed(0)
                     : price >= 1     ? price.toFixed(2)
                     : price.toFixed(4)

  return (
    <div
      onClick={() => onClick && onClick(symbol)}
      title={`${symbol}  ${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%  $${displayPrice}`}
      style={{
        background: bg, border: '1px solid rgba(0,0,0,0.35)', borderRadius: 4,
        padding: '5px 7px', cursor: 'pointer', margin: 2,
        minWidth: minW, height: h, flex: `${weight} 0 ${minW}px`,
        display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        transition: 'filter 0.12s', userSelect: 'none',
      }}
      onMouseEnter={e => e.currentTarget.style.filter = 'brightness(1.25)'}
      onMouseLeave={e => e.currentTarget.style.filter = 'none'}
    >
      <div style={{ fontSize: fs, fontWeight: 700, color: '#fff', letterSpacing: '0.02em', fontFamily: 'var(--font-mono)' }}>
        {displaySym}
      </div>
      <div style={{ fontSize: Math.max(7, fs-2), color: 'rgba(255,255,255,0.88)', marginTop: 1 }}>
        {pct >= 0 ? '+' : ''}{pct.toFixed(2)}%
      </div>
      {weight > 18 && (
        <div style={{ fontSize: 7.5, color: 'rgba(255,255,255,0.55)', marginTop: 1 }}>
          ${displayPrice}
        </div>
      )}
    </div>
  )
}

function SectorGroup({ name, items, onSymbolClick }) {
  if (!items || items.length === 0) return null
  const color = SECTOR_COLORS[name] || '#94a3b8'
  const sorted = [...items].sort((a, b) => b.weight - a.weight)
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color, marginBottom: 3, paddingLeft: 2 }}>
        {name}
        <span style={{ color: 'rgba(255,255,255,0.25)', fontWeight: 400, marginLeft: 5 }}>({items.length})</span>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 0 }}>
        {sorted.map(item => (
          <HeatmapBox key={item.symbol} symbol={item.symbol} chgPct={item.chg_pct}
            price={item.price} weight={item.weight} onClick={onSymbolClick} />
        ))}
      </div>
    </div>
  )
}

function AssetGroup({ name, items, color, onSymbolClick }) {
  if (!items || items.length === 0) return null
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color, marginBottom: 3, paddingLeft: 2 }}>
        {name}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 0 }}>
        {items.map(item => (
          <HeatmapBox key={item.symbol} symbol={item.symbol} chgPct={item.chg_pct}
            price={item.price} weight={item.weight} onClick={onSymbolClick} />
        ))}
      </div>
    </div>
  )
}

const TABS = [
  { key: 'all',      label: 'All' },
  { key: 'equities', label: 'Equities' },
  { key: 'crypto',   label: 'Crypto' },
  { key: 'forex',    label: 'Forex' },
  { key: 'futures',  label: 'Futures' },
]

export default function MarketMap({ onSymbolSelect }) {
  const [data,      setData]      = useState(null)
  const [loading,   setLoading]   = useState(true)
  const [filter,    setFilter]    = useState('all')
  const [updatedAt, setUpdatedAt] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    api.get('/market/heatmap')
      .then(r => { setData(r.data); setUpdatedAt(new Date()); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    const id = setInterval(load, 300_000)
    return () => clearInterval(id)
  }, [load])

  const showEquities = filter === 'all' || filter === 'equities'
  const showCrypto   = filter === 'all' || filter === 'crypto'
  const showForex    = filter === 'all' || filter === 'forex'
  const showFutures  = filter === 'all' || filter === 'futures'

  const sectorOrder = ['Technology','Financials','Healthcare','Consumer',
                       'Energy','Industrials','Communication','Materials',
                       'Real Estate','ETF','Other']

  return (
    <div style={{ display:'flex', flexDirection:'column', height:'100%', background:'#07090f', overflow:'hidden' }}>
      {/* Header */}
      <div style={{ display:'flex', alignItems:'center', gap:10, padding:'8px 14px', borderBottom:'1px solid rgba(140,170,220,0.1)', flexShrink:0, background:'rgba(0,0,0,0.35)' }}>
        <span style={{ fontFamily:'var(--font-mono)', fontSize:11, fontWeight:700, color:'var(--t-1)', letterSpacing:'0.1em' }}>
          MARKET MAP
        </span>
        <div style={{ display:'flex', gap:3, marginLeft:6 }}>
          {TABS.map(tab => (
            <button key={tab.key} onClick={() => setFilter(tab.key)} style={{
              padding:'3px 9px', border:'none', cursor:'pointer', borderRadius:3,
              fontSize:9, fontWeight: filter===tab.key ? 700 : 400,
              background: filter===tab.key ? 'rgba(74,217,255,0.15)' : 'transparent',
              color: filter===tab.key ? '#4ad9ff' : 'var(--t-4)',
              fontFamily:'var(--font-mono)', letterSpacing:'0.04em',
            }}>
              {tab.label}
            </button>
          ))}
        </div>
        <div style={{ marginLeft:'auto', display:'flex', alignItems:'center', gap:8 }}>
          {updatedAt && (
            <span style={{ fontSize:8, color:'var(--t-4)', fontFamily:'var(--font-mono)' }}>
              {updatedAt.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}
            </span>
          )}
          <button onClick={load} disabled={loading} style={{
            background:'none', border:'1px solid rgba(140,170,220,0.2)',
            color: loading ? 'var(--t-4)' : 'var(--t-2)', cursor:'pointer',
            borderRadius:4, padding:'3px 8px', fontSize:10,
          }}>{loading ? '…' : '↻'}</button>
        </div>
      </div>

      {/* Legend */}
      <div style={{ display:'flex', alignItems:'center', gap:10, padding:'4px 14px', flexShrink:0, borderBottom:'1px solid rgba(140,170,220,0.06)' }}>
        {[[-3,'#c53030'],[-1.5,'#9b4040'],[0,'#3d4a60'],[1.5,'#2e7a3e'],[3,'#1a5c2e']].map(([pct,col]) => (
          <div key={pct} style={{ display:'flex', alignItems:'center', gap:3 }}>
            <div style={{ width:10, height:10, background:col, borderRadius:2 }} />
            <span style={{ fontSize:8, color:'var(--t-4)', fontFamily:'var(--font-mono)' }}>{pct>0?'+':''}{pct}%</span>
          </div>
        ))}
        <span style={{ fontSize:8, color:'var(--t-4)', marginLeft:4 }}>Click any tile to open chart</span>
      </div>

      {/* Heatmap body */}
      <div style={{ flex:1, overflowY:'auto', padding:'10px 12px' }}>
        {loading && !data && (
          <div style={{ color:'var(--t-4)', fontSize:11, textAlign:'center', marginTop:60 }}>
            Fetching market data…
          </div>
        )}
        {data && (
          <>
            {showEquities && data.sectors && sectorOrder
              .filter(s => data.sectors[s]?.length > 0)
              .map(sector => (
                <SectorGroup key={sector} name={sector}
                  items={data.sectors[sector]} onSymbolClick={onSymbolSelect} />
              ))}
            {showCrypto && (
              <AssetGroup name="Crypto · 24/7" items={data.crypto}
                color="#4ad9ff" onSymbolClick={onSymbolSelect} />
            )}
            {showForex && (
              <AssetGroup name="Forex" items={data.forex}
                color="#a78bfa" onSymbolClick={onSymbolSelect} />
            )}
            {showFutures && (
              <AssetGroup name="Futures" items={data.futures}
                color="#fb923c" onSymbolClick={onSymbolSelect} />
            )}
          </>
        )}
      </div>
    </div>
  )
}

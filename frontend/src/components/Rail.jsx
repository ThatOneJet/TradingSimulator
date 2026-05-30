// Rail — 56px vertical icon strip (column 1, row 2 of app-shell grid)

function LogoIcon() {
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
      <circle cx="14" cy="14" r="13" fill="var(--acc)" opacity="0.15" stroke="var(--acc)" strokeWidth="1.5"/>
      <text x="14" y="18.5" textAnchor="middle" fontSize="13" fontWeight="700"
        fontFamily="'JetBrains Mono', monospace" fill="var(--acc)">T</text>
    </svg>
  )
}

function ChartIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
      <rect x="1" y="10" width="3" height="7" rx="1" fill="currentColor"/>
      <rect x="7" y="6" width="3" height="11" rx="1" fill="currentColor"/>
      <rect x="13" y="2" width="3" height="15" rx="1" fill="currentColor"/>
    </svg>
  )
}

function NewsIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
      <rect x="2" y="3" width="14" height="12" rx="2" stroke="currentColor" strokeWidth="1.4" fill="none"/>
      <line x1="5" y1="7" x2="13" y2="7" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
      <line x1="5" y1="10" x2="11" y2="10" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
      <line x1="5" y1="13" x2="9" y2="13" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
    </svg>
  )
}

function HoldingsIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
      <rect x="1.5" y="1.5" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.4" fill="none"/>
      <rect x="10.5" y="1.5" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.4" fill="none"/>
      <rect x="1.5" y="10.5" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.4" fill="none"/>
      <rect x="10.5" y="10.5" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.4" fill="none"/>
    </svg>
  )
}

function SidePanelIcon({ open }) {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
      <rect x="1.5" y="2.5" width="15" height="13" rx="2" stroke="currentColor" strokeWidth="1.4" fill="none"/>
      <line x1="12" y1="2.5" x2="12" y2="15.5" stroke="currentColor" strokeWidth="1.4"/>
      {open
        ? <polyline points="14,7 15.5,9 14,11" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
        : <polyline points="15.5,7 14,9 15.5,11" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
      }
    </svg>
  )
}

function ExploreIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
      <circle cx="8" cy="8" r="5.5" stroke="currentColor" strokeWidth="1.4"/>
      <line x1="12.5" y1="12.5" x2="16" y2="16" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
    </svg>
  )
}

function MarketsIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
      <circle cx="9" cy="9" r="7" stroke="currentColor" strokeWidth="1.4" fill="none"/>
      <line x1="2" y1="9" x2="16" y2="9" stroke="currentColor" strokeWidth="1.2"/>
      <path d="M9 2 C11.5 4.5 11.5 13.5 9 16" stroke="currentColor" strokeWidth="1.2" fill="none"/>
      <path d="M9 2 C6.5 4.5 6.5 13.5 9 16" stroke="currentColor" strokeWidth="1.2" fill="none"/>
    </svg>
  )
}

function SettingsIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
      <circle cx="9" cy="9" r="2.5" stroke="currentColor" strokeWidth="1.4" fill="none"/>
      <path
        d="M9 1.5v2M9 14.5v2M1.5 9h2M14.5 9h2M3.2 3.2l1.4 1.4M13.4 13.4l1.4 1.4M14.8 3.2l-1.4 1.4M4.6 13.4l-1.4 1.4"
        stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"
      />
    </svg>
  )
}

export default function Rail({ activeTab, onTabChange, sideOpen, onToggleSide, onSettingsClick }) {
  return (
    <div className="rail">
      {/* Logo */}
      <div className="rail-logo">
        <LogoIcon />
      </div>

      {/* Primary nav tabs */}
      <button
        className={`rail-btn${activeTab === 'chart' ? ' active' : ''}`}
        title="Chart"
        onClick={() => onTabChange('chart')}
      >
        <ChartIcon />
      </button>

      <button
        className={`rail-btn${activeTab === 'news' ? ' active' : ''}`}
        title="News"
        onClick={() => onTabChange('news')}
      >
        <NewsIcon />
      </button>

      <button
        className={`rail-btn${activeTab === 'holdings' ? ' active' : ''}`}
        title="Holdings"
        onClick={() => onTabChange('holdings')}
      >
        <HoldingsIcon />
      </button>

      <button
        className={`rail-btn${activeTab === 'explore' ? ' active' : ''}`}
        title="Explore"
        onClick={() => onTabChange('explore')}
      >
        <ExploreIcon />
      </button>

      <button
        className={`rail-btn${activeTab === 'markets' ? ' active' : ''}`}
        title="Markets"
        onClick={() => onTabChange('markets')}
      >
        <MarketsIcon />
      </button>

      <button
        className={`rail-btn${activeTab === 'map' ? ' active' : ''}`}
        title="Market Map"
        onClick={() => onTabChange('map')}
      >
        <svg width="17" height="17" viewBox="0 0 17 17" fill="none">
          <rect x="1" y="1" width="6" height="5" rx="1" fill="currentColor" opacity="0.9"/>
          <rect x="9" y="1" width="7" height="5" rx="1" fill="currentColor" opacity="0.9"/>
          <rect x="1" y="8" width="4" height="8" rx="1" fill="currentColor" opacity="0.9"/>
          <rect x="7" y="8" width="9" height="3.5" rx="1" fill="currentColor" opacity="0.9"/>
          <rect x="7" y="13" width="9" height="2.5" rx="1" fill="currentColor" opacity="0.45"/>
        </svg>
      </button>

      {/* Push remaining buttons to the bottom */}
      <div className="rail-spacer" />

      {/* Toggle side panel */}
      <button
        className={`rail-btn${sideOpen ? ' active' : ''}`}
        title={sideOpen ? 'Hide side panel' : 'Show side panel'}
        onClick={onToggleSide}
      >
        <SidePanelIcon open={sideOpen} />
      </button>

      {/* Settings */}
      <button
        className={`rail-btn${activeTab === 'settings' ? ' active' : ''}`}
        title="Settings"
        onClick={() => onTabChange('settings')}
      >
        <SettingsIcon />
      </button>
    </div>
  )
}

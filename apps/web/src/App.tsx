import { useCallback, useEffect, useState } from 'react'
import { fetchSignalsAssetClass } from './api'
import { fmtKst, fmtPct, fmtPrice, splitLabel } from './format'
import { useAsync, useQuotes } from './hooks'
import { SignalsView } from './views/SignalsView'
import { ChartView } from './views/ChartView'
import { ReportsView } from './views/ReportsView'

type Tab = 'signals' | 'chart' | 'reports'
type Theme = 'dark' | 'light'

const THEME_KEY = 'invest-assistant-theme'
const DEFAULT_TICKER = 'SPY'

function readTheme(): Theme {
  try {
    const saved = localStorage.getItem(THEME_KEY)
    if (saved === 'dark' || saved === 'light') return saved
  } catch {
    // Storage can be unavailable (private mode); fall back to the MTS-style dark default.
  }
  return 'dark'
}

const NAV: readonly { key: Tab; label: string; icon: string }[] = [
  { key: 'signals', label: '시그널', icon: 'M4 19h16M6 16V10M10 16V5M14 16v-8M18 16v-4' },
  { key: 'chart', label: '차트', icon: 'M3 17l5-6 4 4 8-9M15 6h5v5' },
  { key: 'reports', label: '리포트', icon: 'M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6' },
]

function TickerTape({ onSelect }: { onSelect: (ticker: string) => void }) {
  const { data } = useAsync(fetchSignalsAssetClass, 'asset-class')
  const tickers = data?.tickers.map((t) => t.ticker) ?? []
  const quotes = useQuotes(tickers)
  if (!data) return <div className="tape" />

  // The track is rendered twice so the CSS marquee loops seamlessly; the copy is hidden from
  // assistive tech and keyboard focus.
  const renderItems = (copy: boolean) =>
    data.tickers.map((t) => {
      const change = quotes[t.ticker]?.change
      return (
        <button key={t.ticker} className="tape-item" tabIndex={copy ? -1 : undefined} onClick={() => onSelect(t.ticker)}>
          <span className="tape-name">{splitLabel(t.label)[0]}</span>
          <span className="num">{fmtPrice(change?.close ?? t.close)}</span>
          {change && <span className={`num tone-${change.dir}`}>{fmtPct(change.pct)}</span>}
        </button>
      )
    })

  return (
    <div className="tape" aria-label="대표 자산군 시세">
      <div className="tape-track">
        <span className="tape-set">{renderItems(false)}</span>
        <span className="tape-set" aria-hidden>
          {renderItems(true)}
        </span>
      </div>
    </div>
  )
}

function App() {
  const [tab, setTab] = useState<Tab>('signals')
  const [chartTicker, setChartTicker] = useState(DEFAULT_TICKER)
  const [theme, setTheme] = useState<Theme>(readTheme)
  const { data: assetClass } = useAsync(fetchSignalsAssetClass, 'asset-class')

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try {
      localStorage.setItem(THEME_KEY, theme)
    } catch {
      // Non-persistent theme is fine.
    }
  }, [theme])

  const openChart = useCallback((ticker: string) => {
    setChartTicker(ticker)
    setTab('chart')
    window.scrollTo({ top: 0 })
  }, [])

  return (
    <div className="app">
      <header className="appbar">
        <div className="appbar-row">
          <div className="brand">
            <span className="brand-mark" aria-hidden>
              AI
            </span>
            <div>
              <div className="brand-title">AI 투자 어시스턴트</div>
              <div className="brand-sub">
                <span className="live-dot" aria-hidden />
                {assetClass ? `${fmtKst(assetClass.generated_at)} KST 기준` : '시그널 동기화 중'}
              </div>
            </div>
          </div>
          <button
            className="icon-btn"
            aria-label={theme === 'dark' ? '라이트 모드로 전환' : '다크 모드로 전환'}
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          >
            <svg viewBox="0 0 24 24" aria-hidden>
              {theme === 'dark' ? (
                <path d="M12 4V2M12 22v-2M4 12H2M22 12h-2M5.6 5.6 4.2 4.2M19.8 19.8l-1.4-1.4M5.6 18.4l-1.4 1.4M19.8 4.2l-1.4 1.4M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              ) : (
                <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
              )}
            </svg>
          </button>
        </div>
        <TickerTape onSelect={openChart} />
      </header>

      <main className="content">
        {tab === 'signals' && <SignalsView onOpenChart={openChart} />}
        {tab === 'chart' && <ChartView ticker={chartTicker} theme={theme} onTickerChange={setChartTicker} />}
        {tab === 'reports' && <ReportsView />}
      </main>

      <nav className="tabbar">
        {NAV.map(({ key, label, icon }) => (
          <button key={key} className={tab === key ? 'active' : ''} aria-current={tab === key ? 'page' : undefined} onClick={() => setTab(key)}>
            <svg viewBox="0 0 24 24" aria-hidden>
              <path d={icon} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span>{label}</span>
          </button>
        ))}
      </nav>
    </div>
  )
}

export default App

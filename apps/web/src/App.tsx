import { useEffect, useState } from 'react'
import { SignalsView } from './views/SignalsView'
import { ChartView } from './views/ChartView'
import { ReportsView } from './views/ReportsView'

type Tab = 'signals' | 'chart' | 'reports'
const TABS: readonly Tab[] = ['signals', 'chart', 'reports']

// The URL hash (#chart, #reports) selects the tab so each view can be linked directly.
const tabFromHash = (): Tab => {
  const hash = window.location.hash.slice(1)
  return (TABS as readonly string[]).includes(hash) ? (hash as Tab) : 'signals'
}

function App() {
  const [tab, setTabState] = useState<Tab>(tabFromHash)

  useEffect(() => {
    const onHash = () => setTabState(tabFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const setTab = (next: Tab) => {
    setTabState(next)
    history.replaceState(null, '', next === 'signals' ? window.location.pathname : `#${next}`)
  }

  return (
    <div style={{ maxWidth: tab === 'chart' ? 1480 : 1100, margin: '0 auto', padding: '24px 16px' }}>
      <h1 style={{ fontSize: '1.4rem' }}>AI 투자 어시스턴트 — 오늘의 시그널</h1>
      <p style={{ color: '#888', fontSize: '0.85rem' }}>
        매일 자동으로 계산된 매수/HOLD/매도 시그널과 차트를 보여주는 정적 페이지입니다. 여기서 뉴스 수집이나 LLM 호출은 실시간으로 일어나지 않습니다.
      </p>
      <nav style={{ display: 'flex', gap: 8, borderBottom: '1px solid #ddd', marginBottom: 20 }}>
        {(
          [
            ['signals', '오늘의 시그널'],
            ['chart', '차트 분석'],
            ['reports', '리포트 히스토리'],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            style={{
              padding: '8px 14px',
              border: 'none',
              borderBottom: tab === key ? '2px solid #1976d2' : '2px solid transparent',
              background: 'transparent',
              fontWeight: tab === key ? 700 : 400,
              cursor: 'pointer',
              fontSize: '0.95rem',
            }}
          >
            {label}
          </button>
        ))}
      </nav>
      {tab === 'signals' && <SignalsView />}
      {tab === 'chart' && <ChartView />}
      {tab === 'reports' && <ReportsView />}
    </div>
  )
}

export default App

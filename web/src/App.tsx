import { useState } from 'react'
import { SignalsView } from './views/SignalsView'
import { ChartView } from './views/ChartView'

type Tab = 'signals' | 'chart'

function App() {
  const [tab, setTab] = useState<Tab>('signals')

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '24px 16px' }}>
      <h1 style={{ fontSize: '1.4rem' }}>AI 투자 어시스턴트 — 오늘의 시그널</h1>
      <p style={{ color: '#888', fontSize: '0.85rem' }}>
        매일 자동으로 계산된 매수/HOLD/매도 시그널과 차트를 보여주는 정적 페이지입니다. 여기서 뉴스 수집이나 LLM 호출은 실시간으로 일어나지 않습니다.
      </p>
      <nav style={{ display: 'flex', gap: 8, borderBottom: '1px solid #ddd', marginBottom: 20 }}>
        {(
          [
            ['signals', '오늘의 시그널'],
            ['chart', '차트 분석'],
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
      {tab === 'signals' ? <SignalsView /> : <ChartView />}
    </div>
  )
}

export default App

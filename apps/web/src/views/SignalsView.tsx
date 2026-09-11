import { useEffect, useState } from 'react'
import { fetchSignalsAssetClass, fetchSignalsSp500 } from '../api'
import type { Action, AssetClassSignal, SignalsAssetClass, SignalsSp500 } from '../types'

const ACTION_COLOR: Record<Action, string> = {
  매수: '#2e7d32',
  HOLD: '#757575',
  매도: '#c62828',
}

function ActionBadge({ action }: { action: Action }) {
  return (
    <span
      style={{
        color: '#fff',
        background: ACTION_COLOR[action],
        borderRadius: 4,
        padding: '2px 8px',
        fontWeight: 700,
        fontSize: '0.85rem',
      }}
    >
      {action}
    </span>
  )
}

function AssetClassCard({ item }: { item: AssetClassSignal }) {
  return (
    <div style={{ border: '1px solid #ddd', borderRadius: 8, padding: 16, marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <strong style={{ fontSize: '1.05rem' }}>
          {item.label} ({item.ticker})
        </strong>
        <ActionBadge action={item.action} />
        <span style={{ color: '#666', fontSize: '0.85rem' }}>
          종가 {item.close.toLocaleString()} · {item.date}
        </span>
      </div>
      <p style={{ whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>{item.text}</p>
      {item.news.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {item.news.map((n) => (
            <a
              key={n.link || n.title}
              href={n.link}
              target="_blank"
              rel="noreferrer"
              style={{ fontSize: '0.85rem', color: 'inherit', textDecoration: 'none', border: '1px solid #eee', borderRadius: 6, padding: 8 }}
            >
              <div style={{ fontWeight: 600 }}>{n.title}</div>
              <div style={{ color: '#888', fontSize: '0.78rem' }}>
                {n.publisher} {n.published_at ? `· ${n.published_at}` : ''}
              </div>
              {n.summary && <div style={{ marginTop: 4 }}>{n.summary}</div>}
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

export function SignalsView() {
  const [assetClass, setAssetClass] = useState<SignalsAssetClass | null>(null)
  const [sp500, setSp500] = useState<SignalsSp500 | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([fetchSignalsAssetClass(), fetchSignalsSp500()])
      .then(([ac, sp]) => {
        setAssetClass(ac)
        setSp500(sp)
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  if (error) return <p style={{ color: '#c62828' }}>데이터를 불러오지 못했습니다: {error}</p>
  if (!assetClass || !sp500) return <p>불러오는 중...</p>

  const sortedSp500 = [...sp500.signals].sort((a, b) => a.action.localeCompare(b.action) || a.ticker.localeCompare(b.ticker))

  return (
    <div>
      <p style={{ color: '#888', fontSize: '0.8rem' }}>기준 시각: {assetClass.generated_at}</p>
      {assetClass.overview && (
        <div style={{ background: '#f5f5f5', borderRadius: 8, padding: 16, marginBottom: 20 }}>{assetClass.overview}</div>
      )}

      <h2>대표 자산군 (12종)</h2>
      {assetClass.tickers.map((item) => (
        <AssetClassCard key={item.ticker} item={item} />
      ))}

      <h2>S&amp;P 500 매수/매도 시그널</h2>
      <p style={{ color: '#888', fontSize: '0.8rem' }}>
        기계적 규칙(Donchian 돌파/추세추종 청산)만으로 판정 — 뉴스·LLM 분석은 대표 자산군 12종에만 적용됩니다.
      </p>
      {sortedSp500.length === 0 ? (
        <p>오늘은 매수/매도 시그널이 발생한 S&amp;P 500 종목이 없습니다.</p>
      ) : (
        <table style={{ borderCollapse: 'collapse', width: '100%' }}>
          <thead>
            <tr>
              {['티커', '설명', '섹터', '액션', '종가', '일자'].map((h) => (
                <th key={h} style={{ textAlign: 'left', borderBottom: '1px solid #ccc', padding: '4px 8px' }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedSp500.map((s) => (
              <tr key={s.ticker}>
                <td style={{ padding: '4px 8px' }}>{s.ticker}</td>
                <td style={{ padding: '4px 8px' }}>{s.description}</td>
                <td style={{ padding: '4px 8px' }}>{s.sector}</td>
                <td style={{ padding: '4px 8px' }}>
                  <ActionBadge action={s.action} />
                </td>
                <td style={{ padding: '4px 8px' }}>{s.close.toLocaleString()}</td>
                <td style={{ padding: '4px 8px' }}>{s.date}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

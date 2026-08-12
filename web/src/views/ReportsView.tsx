import { useEffect, useMemo, useState } from 'react'
import { fetchReportsIndex, fetchUniverse } from '../api'
import type { Action, ReportEntry } from '../types'

// docs/reports/{date}.html is a separate static page (report_builder.py's full daily HTML
// report, not part of this React app) -- link out to it directly rather than trying to
// reproduce it here.
const REPORTS_BASE = `${import.meta.env.BASE_URL}reports`

const ACTION_COLOR: Record<Action, string> = { 매수: '#2e7d32', HOLD: '#757575', 매도: '#c62828' }
const ACTION_LETTER: Record<Action, string> = { 매수: 'B', HOLD: 'H', 매도: 'S' }

function ActionGrid({ actions, tickers }: { actions: Record<string, Action>; tickers: string[] }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3, marginTop: 6 }}>
      {tickers.map((ticker) => {
        const action = actions[ticker]
        return (
          <span
            key={ticker}
            title={`${ticker}: ${action ?? '기록 없음'}`}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: 16,
              height: 16,
              fontSize: '0.62rem',
              fontWeight: 700,
              borderRadius: 3,
              color: '#fff',
              background: action ? ACTION_COLOR[action] : '#ccc',
            }}
          >
            {action ? ACTION_LETTER[action] : '-'}
          </span>
        )
      })}
    </div>
  )
}

export function ReportsView() {
  const [entries, setEntries] = useState<ReportEntry[] | null>(null)
  const [tickers, setTickers] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState('')

  useEffect(() => {
    Promise.all([fetchReportsIndex(), fetchUniverse()])
      .then(([reports, universe]) => {
        setEntries(reports.dates)
        setTickers(universe.asset_classes.map((a) => a.ticker))
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  const filtered = useMemo(() => (entries ?? []).filter((e) => e.date.includes(filter.trim())), [entries, filter])

  if (error) return <p style={{ color: '#c62828' }}>리포트 목록을 불러오지 못했습니다: {error}</p>
  if (!entries) return <p>불러오는 중...</p>

  return (
    <div>
      <p style={{ color: '#888', fontSize: '0.85rem' }}>
        그날의 전체 리포트(자산군별 LLM 해석, 뉴스, 차트 포함)로 연결되는 링크입니다. 배지는 대표 자산군 12종의 그날 매수(B)/HOLD(H)/매도(S) 액션입니다. 총 {entries.length}개.
      </p>
      <input
        type="text"
        placeholder="YYYY-MM-DD로 검색"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        style={{ padding: '6px 10px', marginBottom: 16, width: 220 }}
      />
      {filtered.length === 0 ? (
        <p>해당하는 리포트가 없습니다.</p>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 8 }}>
          {filtered.map((entry) => (
            <a
              key={entry.date}
              href={`${REPORTS_BASE}/${entry.date}.html`}
              target="_blank"
              rel="noreferrer"
              style={{ display: 'block', border: '1px solid #ddd', borderRadius: 6, padding: '8px 10px', color: 'inherit', textDecoration: 'none' }}
            >
              <div style={{ fontWeight: 600 }}>{entry.date}</div>
              <ActionGrid actions={entry.actions} tickers={tickers} />
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

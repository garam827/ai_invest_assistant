import { useEffect, useMemo, useState } from 'react'
import { fetchReportsIndex } from '../api'

// docs/reports/{date}.html is a separate static page (report_builder.py's full daily HTML
// report, not part of this React app) -- link out to it directly rather than trying to
// reproduce it here.
const REPORTS_BASE = `${import.meta.env.BASE_URL}reports`

export function ReportsView() {
  const [dates, setDates] = useState<string[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState('')

  useEffect(() => {
    fetchReportsIndex()
      .then((data) => setDates(data.dates))
      .catch((e: Error) => setError(e.message))
  }, [])

  const filtered = useMemo(() => (dates ?? []).filter((d) => d.includes(filter.trim())), [dates, filter])

  if (error) return <p style={{ color: '#c62828' }}>리포트 목록을 불러오지 못했습니다: {error}</p>
  if (!dates) return <p>불러오는 중...</p>

  return (
    <div>
      <p style={{ color: '#888', fontSize: '0.85rem' }}>
        그날의 전체 리포트(자산군별 LLM 해석, 뉴스, 차트 포함)로 연결되는 링크입니다. 총 {dates.length}개.
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
        <ul style={{ listStyle: 'none', padding: 0, display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8 }}>
          {filtered.map((date) => (
            <li key={date}>
              <a
                href={`${REPORTS_BASE}/${date}.html`}
                target="_blank"
                rel="noreferrer"
                style={{ display: 'block', border: '1px solid #ddd', borderRadius: 6, padding: '8px 10px', color: 'inherit', textDecoration: 'none' }}
              >
                {date}
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

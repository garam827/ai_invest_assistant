import { useMemo, useState } from 'react'
import { fetchReportsIndex, fetchUniverse } from '../api'
import { SearchInput, StatusMessage } from '../components/ui'
import { ACTION_TONE, weekdayOf } from '../format'
import { useAsync } from '../hooks'
import type { Action, ReportEntry } from '../types'

// docs/reports/{date}.html is a separate static page (report_builder.py's full daily HTML
// report, not part of this React app) -- link out to it directly rather than trying to
// reproduce it here.
const REPORTS_BASE = `${import.meta.env.BASE_URL}reports`

const ACTION_LETTER: Record<Action, string> = { 매수: 'B', HOLD: 'H', 매도: 'S' }

function ActionGrid({ actions, tickers }: { actions: Record<string, Action>; tickers: string[] }) {
  return (
    <div className="action-grid">
      {tickers.map((ticker) => {
        const action = actions[ticker]
        return (
          <span key={ticker} title={`${ticker}: ${action ?? '기록 없음'}`} className={`cell${action ? ` tone-${ACTION_TONE[action]}` : ' none'}`}>
            {action ? ACTION_LETTER[action] : '-'}
          </span>
        )
      })}
    </div>
  )
}

function ReportRow({ entry, tickers }: { entry: ReportEntry; tickers: string[] }) {
  const values = Object.values(entry.actions)
  const buys = values.filter((a) => a === '매수').length
  const sells = values.filter((a) => a === '매도').length
  return (
    <li>
      <a className="row report-row" href={`${REPORTS_BASE}/${entry.date}.html`} target="_blank" rel="noreferrer">
        <div className="report-date">
          <span className="num day">{entry.date.slice(8, 10)}</span>
          <span className="weekday">{weekdayOf(entry.date)}</span>
        </div>
        <div className="row-main">
          <div className="report-counts">
            <span>
              매수 <b className="num tone-up">{buys}</b>
            </span>
            <span>
              매도 <b className="num tone-down">{sells}</b>
            </span>
            <span>
              HOLD <b className="num">{values.length - buys - sells}</b>
            </span>
          </div>
          <ActionGrid actions={entry.actions} tickers={tickers} />
        </div>
        <svg className="chevron" viewBox="0 0 24 24" aria-hidden>
          <path d="M9 6l6 6-6 6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </a>
    </li>
  )
}

export function ReportsView() {
  const reports = useAsync(fetchReportsIndex, 'reports')
  const universe = useAsync(fetchUniverse, 'universe')
  const [filter, setFilter] = useState('')

  const byMonth = useMemo(() => {
    const q = filter.trim()
    const months = new Map<string, ReportEntry[]>()
    for (const entry of reports.data?.dates ?? []) {
      if (q && !entry.date.includes(q)) continue
      const month = entry.date.slice(0, 7)
      months.set(month, [...(months.get(month) ?? []), entry])
    }
    return [...months.entries()]
  }, [reports.data, filter])

  const error = reports.error ?? universe.error
  if (error) return <StatusMessage error={error}>리포트 목록을 불러오지 못했습니다</StatusMessage>
  if (!reports.data || !universe.data) return <StatusMessage />

  const tickers = universe.data.asset_classes.map((a) => a.ticker)

  return (
    <div className="stack">
      <section className="card">
        <div className="card-title">
          리포트 히스토리 <span className="num muted">{reports.data.dates.length}건</span>
        </div>
        <p className="note">
          날짜를 누르면 그날의 전체 리포트(자산군별 LLM 해석, 뉴스, 차트)가 열립니다. 배지는 대표 자산군 {tickers.length}종의 매수(B)·HOLD(H)·매도(S) 액션입니다.
        </p>
        <SearchInput value={filter} onChange={setFilter} placeholder="YYYY-MM-DD로 검색" />
      </section>

      {byMonth.length === 0 ? (
        <div className="empty">해당하는 리포트가 없습니다.</div>
      ) : (
        byMonth.map(([month, entries]) => (
          <section key={month}>
            <h2 className="month-head num">{month.replace('-', '.')}</h2>
            <ul className="list card">
              {entries.map((entry) => (
                <ReportRow key={entry.date} entry={entry} tickers={tickers} />
              ))}
            </ul>
          </section>
        ))
      )}
    </div>
  )
}

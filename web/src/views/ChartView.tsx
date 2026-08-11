import { useEffect, useMemo, useState } from 'react'
import { fetchChart, fetchUniverse } from '../api'
import { TickerChart } from '../components/TickerChart'
import type { ChartRow, Universe } from '../types'

const GROUP_ASSET_CLASS = '대표 자산군'

export function ChartView() {
  const [universe, setUniverse] = useState<Universe | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [group, setGroup] = useState<string>(GROUP_ASSET_CLASS)
  const [ticker, setTicker] = useState<string>('')
  const [rows, setRows] = useState<ChartRow[] | null>(null)
  const [chartError, setChartError] = useState<string | null>(null)

  useEffect(() => {
    fetchUniverse()
      .then(setUniverse)
      .catch((e: Error) => setError(e.message))
  }, [])

  const sp500Sectors = useMemo(() => {
    if (!universe) return []
    return Array.from(new Set(universe.sp500.map((s) => s.sector))).sort()
  }, [universe])

  const groupOptions = useMemo(() => [GROUP_ASSET_CLASS, ...sp500Sectors], [sp500Sectors])

  const tickerOptions = useMemo(() => {
    if (!universe) return []
    if (group === GROUP_ASSET_CLASS) {
      return universe.asset_classes.map((a) => ({ ticker: a.ticker, label: `${a.label} (${a.ticker})` }))
    }
    return universe.sp500
      .filter((s) => s.sector === group)
      .map((s) => ({ ticker: s.ticker, label: s.description ? `${s.ticker} — ${s.description}` : s.ticker }))
  }, [universe, group])

  useEffect(() => {
    if (tickerOptions.length > 0) setTicker(tickerOptions[0].ticker)
  }, [tickerOptions])

  useEffect(() => {
    if (!ticker) return
    setRows(null)
    setChartError(null)
    fetchChart(ticker)
      .then(setRows)
      .catch((e: Error) => setChartError(e.message))
  }, [ticker])

  if (error) return <p style={{ color: '#c62828' }}>종목 목록을 불러오지 못했습니다: {error}</p>
  if (!universe) return <p>불러오는 중...</p>

  return (
    <div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <select value={group} onChange={(e) => setGroup(e.target.value)}>
          {groupOptions.map((g) => (
            <option key={g} value={g}>
              {g}
            </option>
          ))}
        </select>
        <select value={ticker} onChange={(e) => setTicker(e.target.value)}>
          {tickerOptions.map((t) => (
            <option key={t.ticker} value={t.ticker}>
              {t.label}
            </option>
          ))}
        </select>
      </div>

      {chartError && <p style={{ color: '#c62828' }}>차트 데이터를 불러오지 못했습니다: {chartError}</p>}
      {!chartError && !rows && <p>차트 불러오는 중...</p>}
      {rows && rows.length === 0 && <p>이 종목의 차트 데이터가 아직 없습니다.</p>}
      {rows && rows.length > 0 && <TickerChart ticker={ticker} rows={rows} />}
    </div>
  )
}

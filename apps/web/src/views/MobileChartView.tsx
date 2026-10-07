import { useCallback, useEffect, useMemo, useState } from 'react'
import { fetchChart, fetchSignalsAssetClass, fetchSignalsSp500, fetchUniverse } from '../api'
import { MobileTickerChart, type Overlay, type Period } from '../components/MobileTickerChart'
import { ActionPill, Chip, SearchInput, StatusMessage } from '../components/ui'
import { dailyChange, directionOf, fmtPct, fmtPrice, fmtSignedPrice, fmtVolume, splitLabel } from '../format'
import { useAsync } from '../hooks'
import type { Action, ChartRow, Universe } from '../types'

const GROUP_ASSET_CLASS = '대표 자산군'
const PERIODS: readonly Period[] = ['1M', '3M', '6M', '1Y', 'ALL']
const PERIOD_LABEL: Record<Period, string> = { '1M': '1개월', '3M': '3개월', '6M': '6개월', '1Y': '1년', ALL: '전체' }
const OVERLAYS: readonly [Overlay, string][] = [
  ['markers', '매매신호'],
  ['stop', '추적손절'],
  ['dc20', '돈키언20'],
  ['dc100', '돈키언100'],
  ['bb', '볼린저'],
  ['ichimoku', '일목'],
]
const DEFAULT_OVERLAYS: Record<Overlay, boolean> = { markers: true, stop: true, dc20: true, dc100: true, bb: false, ichimoku: false }

export interface ChartViewProps {
  ticker: string
  theme: string
  onTickerChange: (ticker: string) => void
}

interface Instrument {
  ticker: string
  name: string
  sub: string
  group: string
}

function instrumentsOf(universe: Universe): Instrument[] {
  return [
    ...universe.asset_classes.map((a) => {
      const [name, sub] = splitLabel(a.label)
      return { ticker: a.ticker, name, sub: sub || a.category, group: GROUP_ASSET_CLASS }
    }),
    ...universe.sp500.map((s) => {
      const [name, sub] = splitLabel(s.description || s.ticker)
      return { ticker: s.ticker, name, sub: sub || s.sector, group: s.sector }
    }),
  ]
}

function TickerPicker({ instruments, current, onPick, onClose }: { instruments: Instrument[]; current: string; onPick: (ticker: string) => void; onClose: () => void }) {
  const [query, setQuery] = useState('')
  const [group, setGroup] = useState(() => instruments.find((i) => i.ticker === current)?.group ?? GROUP_ASSET_CLASS)
  const groups = useMemo(() => [GROUP_ASSET_CLASS, ...Array.from(new Set(instruments.filter((i) => i.group !== GROUP_ASSET_CLASS).map((i) => i.group))).sort()], [instruments])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (q) return instruments.filter((i) => i.ticker.toLowerCase().includes(q) || i.name.toLowerCase().includes(q)).slice(0, 80)
    return instruments.filter((i) => i.group === group)
  }, [instruments, query, group])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [onClose])

  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet" role="dialog" aria-modal="true" aria-label="종목 검색" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-grip" aria-hidden />
        <div className="sheet-head">
          <span>종목 검색</span>
          <button className="icon-btn" aria-label="닫기" onClick={onClose}>
            ×
          </button>
        </div>
        <SearchInput value={query} onChange={setQuery} placeholder="티커 또는 종목명" autoFocus />
        {!query && (
          <div className="chips scroll">
            {groups.map((g) => (
              <Chip key={g} active={g === group} onClick={() => setGroup(g)}>
                {g}
              </Chip>
            ))}
          </div>
        )}
        <ul className="sheet-list">
          {visible.length === 0 && <li className="empty">검색 결과가 없습니다.</li>}
          {visible.map((i) => (
            <li key={i.ticker}>
              <button className={`row compact${i.ticker === current ? ' selected' : ''}`} onClick={() => onPick(i.ticker)}>
                <span className="ticker-code">{i.ticker}</span>
                <div className="row-main">
                  <div className="ellipsis">{i.name}</div>
                  <div className="row-sub ellipsis">{i.sub}</div>
                </div>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

function QuoteGrid({ row }: { row: ChartRow }) {
  const stopGap = row.Trailing_Stop != null ? ((row.Close - row.Trailing_Stop) / row.Close) * 100 : null
  const cells: [string, string, string?][] = [
    ['시가', fmtPrice(row.Open)],
    ['고가', fmtPrice(row.High), 'tone-up'],
    ['저가', fmtPrice(row.Low), 'tone-down'],
    ['거래량', fmtVolume(row.Volume), row.Volume_Surge ? 'tone-warn' : undefined],
    ['ATR(14)', row.ATR != null ? fmtPrice(row.ATR) : '—'],
    ['추적 손절', row.Trailing_Stop != null ? fmtPrice(row.Trailing_Stop) : '—', 'tone-warn'],
    ['20일 상단', row.Donchian_Upper_20 != null ? fmtPrice(row.Donchian_Upper_20) : '—'],
    ['20일 하단', row.Donchian_Lower_20 != null ? fmtPrice(row.Donchian_Lower_20) : '—'],
    ['100일 상단', row.Donchian_Upper_100 != null ? fmtPrice(row.Donchian_Upper_100) : '—'],
    ['100일 하단', row.Donchian_Lower_100 != null ? fmtPrice(row.Donchian_Lower_100) : '—'],
    ['손절까지', stopGap != null ? fmtPct(-stopGap) : '—'],
    ['거래량 급증', row.Volume_Surge ? '발생' : '—', row.Volume_Surge ? 'tone-warn' : undefined],
  ]
  return (
    <dl className="quote-grid">
      {cells.map(([label, value, tone]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd className={`num ${tone ?? ''}`}>{value}</dd>
        </div>
      ))}
    </dl>
  )
}

export function MobileChartView({ ticker, theme, onTickerChange }: ChartViewProps) {
  const universe = useAsync(fetchUniverse, 'universe')
  const assetSignals = useAsync(fetchSignalsAssetClass, 'asset-class')
  const sp500Signals = useAsync(fetchSignalsSp500, 'sp500')
  const chart = useAsync(() => fetchChart(ticker), `chart:${ticker}`)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [period, setPeriod] = useState<Period>('6M')
  const [overlays, setOverlays] = useState(DEFAULT_OVERLAYS)
  const [hover, setHover] = useState<ChartRow | null>(null)

  const instruments = useMemo(() => (universe.data ? instrumentsOf(universe.data) : []), [universe.data])
  const instrument = instruments.find((i) => i.ticker === ticker)

  const action: Action | undefined = useMemo(
    () => assetSignals.data?.tickers.find((t) => t.ticker === ticker)?.action ?? sp500Signals.data?.signals.find((s) => s.ticker === ticker)?.action,
    [assetSignals.data, sp500Signals.data, ticker],
  )

  useEffect(() => setHover(null), [ticker])
  const closePicker = useCallback(() => setPickerOpen(false), [])

  if (universe.error) return <StatusMessage error={universe.error}>종목 목록을 불러오지 못했습니다</StatusMessage>
  if (!universe.data) return <StatusMessage />

  const rows = chart.data
  const last = rows && rows.length > 0 ? rows[rows.length - 1] : null
  const change = rows ? dailyChange(rows) : null
  const shown = hover ?? last
  const shownIndex = rows && shown ? rows.indexOf(shown) : -1
  const shownPrev = rows && shownIndex > 0 ? rows[shownIndex - 1].Close : null
  const shownDiff = shown && shownPrev != null ? shown.Close - shownPrev : null
  const dir = change?.dir ?? 'flat'

  return (
    <div className="stack">
      <section className="card quote-head">
        <button className="instrument-btn" onClick={() => setPickerOpen(true)} aria-haspopup="dialog">
          <span className="instrument-name ellipsis">{instrument?.name ?? ticker}</span>
          <svg viewBox="0 0 24 24" aria-hidden>
            <path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
        </button>
        <div className="instrument-sub">
          <span className="ticker-code">{ticker}</span>
          <span className="ellipsis">{instrument?.sub}</span>
          {action && <ActionPill action={action} solid />}
        </div>
        {last && (
          <div className="quote-price">
            <span className={`num big tone-${dir}`}>{fmtPrice(last.Close)}</span>
            {change && (
              <span className={`num tone-${dir}`}>
                {fmtSignedPrice(change.diff)} ({fmtPct(change.pct)})
              </span>
            )}
            <span className="muted">{last.Date} 종가</span>
          </div>
        )}
      </section>

      <section className="card chart-card">
        <div className="chart-toolbar">
          <div className="period-tabs" role="tablist" aria-label="기간">
            {PERIODS.map((p) => (
              <button key={p} role="tab" aria-selected={period === p} className={period === p ? 'active' : ''} onClick={() => setPeriod(p)}>
                {PERIOD_LABEL[p]}
              </button>
            ))}
          </div>
        </div>
        <div className="chips scroll overlay-chips">
          {OVERLAYS.map(([key, label]) => (
            <Chip key={key} active={overlays[key]} onClick={() => setOverlays({ ...overlays, [key]: !overlays[key] })}>
              <span className={`legend-dot dot-${key}`} aria-hidden />
              {label}
            </Chip>
          ))}
        </div>

        {shown && (
          <div className="ohlc num" aria-live="off">
            <span className="muted">{shown.Date}</span>
            <span>
              시 <b>{fmtPrice(shown.Open)}</b>
            </span>
            <span>
              고 <b className="tone-up">{fmtPrice(shown.High)}</b>
            </span>
            <span>
              저 <b className="tone-down">{fmtPrice(shown.Low)}</b>
            </span>
            <span>
              종 <b className={shownDiff != null ? `tone-${directionOf(shownDiff)}` : ''}>{fmtPrice(shown.Close)}</b>
            </span>
          </div>
        )}

        {chart.error && <StatusMessage error={chart.error}>차트 데이터를 불러오지 못했습니다</StatusMessage>}
        {!chart.error && !rows && <StatusMessage>차트 불러오는 중...</StatusMessage>}
        {rows && rows.length === 0 && <div className="empty">이 종목의 차트 데이터가 아직 없습니다.</div>}
        {rows && rows.length > 0 && <MobileTickerChart rows={rows} theme={theme} overlays={overlays} period={period} onHover={setHover} />}
        <div className="pane-labels muted">
          <span>상단: 가격 · 중단: 거래량(주황=급증) · 하단: ATR(14)</span>
        </div>
      </section>

      {last && (
        <section className="card">
          <div className="card-title">시세 정보</div>
          <QuoteGrid row={last} />
          <p className="note">볼린저 밴드·일목·거래량 급증은 참고 지표이며, 매수/매도 판정과 포지션 크기에는 사용되지 않습니다.</p>
        </section>
      )}

      {pickerOpen && (
        <TickerPicker
          instruments={instruments}
          current={ticker}
          onPick={(t) => {
            onTickerChange(t)
            setPickerOpen(false)
          }}
          onClose={closePicker}
        />
      )}
    </div>
  )
}

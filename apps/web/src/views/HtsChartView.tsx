import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fetchChart, fetchSignalsAssetClass, fetchSignalsSp500, fetchUniverse } from '../api'
import { TickerChart, type TickerChartHandle } from '../components/TickerChart'
import { HTS_COLORS, type ChartSettings, type IndicatorKey, type RangeKey } from '../components/chartConfig'
import type { Action, ChartRow, Universe } from '../types'
import type { ChartViewProps } from './MobileChartView'
import './HtsChartView.css'

const GROUP_ASSET_CLASS = '대표 자산군'
const GROUP_ALL_SP500 = 'S&P 500 전체'
const SETTINGS_KEY = 'hts-chart-settings-v1'
const WEEKS_52_BARS = 252

const RANGES: { key: RangeKey; label: string }[] = [
  { key: '1M', label: '1M' },
  { key: '3M', label: '3M' },
  { key: '6M', label: '6M' },
  { key: '1Y', label: '1Y' },
  { key: 'ALL', label: '전체' },
]

const INDICATORS: { key: IndicatorKey; label: string; color: string }[] = [
  { key: 'signals', label: '매매신호', color: HTS_COLORS.up },
  { key: 'stop', label: '손절선', color: HTS_COLORS.stop },
  { key: 'dc20', label: 'DC20', color: HTS_COLORS.dc20 },
  { key: 'dc100', label: 'DC100', color: HTS_COLORS.dc100 },
  { key: 'bb', label: 'BB', color: HTS_COLORS.bb },
  { key: 'ichimoku', label: '일목', color: HTS_COLORS.senkouA },
]

const DEFAULT_SETTINGS: ChartSettings = {
  range: '6M',
  chartType: 'candle',
  logScale: false,
  indicators: { signals: true, stop: true, dc20: true, dc100: true, bb: false, ichimoku: false },
}

interface WatchItem {
  ticker: string
  name: string
  action: Action | null
  close: number | null
}

function loadSettings(): ChartSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY)
    if (!raw) return DEFAULT_SETTINGS
    const saved = JSON.parse(raw) as Partial<ChartSettings>
    return { ...DEFAULT_SETTINGS, ...saved, indicators: { ...DEFAULT_SETTINGS.indicators, ...saved.indicators } }
  } catch {
    return DEFAULT_SETTINGS
  }
}

const fmtPrice = (v: number | null | undefined) =>
  v == null ? '-' : v.toLocaleString('ko-KR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

function fmtVolume(v: number): string {
  if (v >= 1e8) return `${(v / 1e8).toFixed(2)}억`
  if (v >= 1e4) return `${(v / 1e4).toFixed(1)}만`
  return v.toLocaleString('ko-KR')
}

const fmtPct = (v: number) => `${v > 0 ? '+' : ''}${v.toFixed(2)}%`
const toneOf = (v: number) => (v > 0 ? 'up' : v < 0 ? 'down' : 'flat')

function ActionBadge({ action }: { action: Action | null }) {
  if (!action) return null
  const cls = action === '매수' ? 'buy' : action === '매도' ? 'sell' : 'hold'
  return <span className={`hts-badge ${cls}`}>{action}</span>
}

export function HtsChartView({ ticker, onTickerChange: setTicker }: ChartViewProps) {
  const [universe, setUniverse] = useState<Universe | null>(null)
  const [actions, setActions] = useState<Map<string, { action: Action; close: number }>>(new Map())
  const [error, setError] = useState<string | null>(null)
  const [group, setGroup] = useState(GROUP_ASSET_CLASS)
  const [query, setQuery] = useState('')
  const [rows, setRows] = useState<ChartRow[] | null>(null)
  const [chartError, setChartError] = useState<string | null>(null)
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)
  const [settings, setSettings] = useState<ChartSettings>(loadSettings)
  const [fullscreen, setFullscreen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<TickerChartHandle>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLUListElement>(null)

  useEffect(() => {
    fetchUniverse()
      .then(setUniverse)
      .catch((e: Error) => setError(e.message))
    // Signal badges are a convenience; the chart still works if either file is unavailable.
    Promise.allSettled([fetchSignalsAssetClass(), fetchSignalsSp500()]).then(([asset, sp500]) => {
      const map = new Map<string, { action: Action; close: number }>()
      if (sp500.status === 'fulfilled') sp500.value.signals.forEach((s) => map.set(s.ticker, { action: s.action, close: s.close }))
      if (asset.status === 'fulfilled') asset.value.tickers.forEach((s) => map.set(s.ticker, { action: s.action, close: s.close }))
      setActions(map)
    })
  }, [])

  useEffect(() => {
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings))
    } catch {
      // Storage may be unavailable (private mode); settings then last for this visit only.
    }
  }, [settings])

  const assetTickers = useMemo(() => new Set(universe?.asset_classes.map((a) => a.ticker) ?? []), [universe])

  const groupOptions = useMemo(() => {
    if (!universe) return [GROUP_ASSET_CLASS]
    const sectors = Array.from(new Set(universe.sp500.map((s) => s.sector))).sort()
    return [GROUP_ASSET_CLASS, GROUP_ALL_SP500, ...sectors]
  }, [universe])

  const nameOf = useMemo(() => {
    const map = new Map<string, string>()
    universe?.asset_classes.forEach((a) => map.set(a.ticker, a.label))
    universe?.sp500.forEach((s) => map.set(s.ticker, s.description || s.ticker))
    return map
  }, [universe])

  const watchlist = useMemo<WatchItem[]>(() => {
    if (!universe) return []
    const source =
      group === GROUP_ASSET_CLASS
        ? universe.asset_classes.map((a) => a.ticker)
        : universe.sp500.filter((s) => group === GROUP_ALL_SP500 || s.sector === group).map((s) => s.ticker)
    const q = query.trim().toLowerCase()
    return source
      .filter((t) => !q || t.toLowerCase().includes(q) || (nameOf.get(t) ?? '').toLowerCase().includes(q))
      .map((t) => {
        const known = actions.get(t)
        // signals_sp500.json lists only 매수/매도 tickers, so an S&P 500 name missing from it is HOLD.
        const action = known?.action ?? (actions.size > 0 && !assetTickers.has(t) ? 'HOLD' : null)
        return { ticker: t, name: nameOf.get(t) ?? t, action, close: known?.close ?? null }
      })
  }, [universe, group, query, actions, nameOf, assetTickers])

  useEffect(() => {
    if (!ticker) return
    let cancelled = false
    setRows(null)
    setChartError(null)
    setHoverIdx(null)
    fetchChart(ticker)
      .then((data) => {
        if (!cancelled) setRows(data)
      })
      .catch((e: Error) => {
        if (!cancelled) setChartError(e.message)
      })
    return () => {
      cancelled = true
    }
  }, [ticker])

  // Keyboard: ↑/↓ walks the watchlist, "/" focuses search, "f" toggles fullscreen.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement
      const inField = target.tagName === 'SELECT' || target.tagName === 'TEXTAREA' || (target.tagName === 'INPUT' && target !== searchRef.current)
      if (inField || e.altKey || e.ctrlKey || e.metaKey) return
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        if (watchlist.length === 0) return
        e.preventDefault()
        const idx = watchlist.findIndex((w) => w.ticker === ticker)
        const next = e.key === 'ArrowDown' ? Math.min(idx + 1, watchlist.length - 1) : Math.max(idx - 1, 0)
        setTicker(watchlist[idx < 0 ? 0 : next].ticker)
      } else if (target !== searchRef.current && e.key === '/') {
        e.preventDefault()
        searchRef.current?.focus()
      } else if (target !== searchRef.current && (e.key === 'f' || e.key === 'F')) {
        toggleFullscreen()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  useEffect(() => {
    listRef.current?.querySelector('.active')?.scrollIntoView({ block: 'nearest' })
  }, [ticker, watchlist])

  useEffect(() => {
    const onChange = () => setFullscreen(document.fullscreenElement === rootRef.current)
    document.addEventListener('fullscreenchange', onChange)
    return () => document.removeEventListener('fullscreenchange', onChange)
  }, [])

  const toggleFullscreen = () => {
    if (document.fullscreenElement) {
      void document.exitFullscreen()
    } else {
      void rootRef.current?.requestFullscreen?.()
    }
  }

  const handleHover = useCallback((idx: number | null) => setHoverIdx(idx), [])

  const stats = useMemo(() => {
    if (!rows || rows.length === 0) return null
    const last = rows[rows.length - 1]
    const prev = rows.length > 1 ? rows[rows.length - 2] : last
    const window52 = rows.slice(-WEEKS_52_BARS)
    const change = last.Close - prev.Close
    const signals = rows
      .filter((r) => r.Buy_Trigger || r.Sell_Trigger)
      .map((r) => ({ date: r.Date, kind: r.Buy_Trigger ? ('매수' as const) : ('매도' as const), close: r.Close }))
      .reverse()
    return {
      last,
      change,
      changePct: prev.Close ? (change / prev.Close) * 100 : 0,
      high52: Math.max(...window52.map((r) => r.High)),
      low52: Math.min(...window52.map((r) => r.Low)),
      stopGapPct: last.Trailing_Stop != null ? ((last.Close - last.Trailing_Stop) / last.Close) * 100 : null,
      atrPct: last.ATR != null ? (last.ATR / last.Close) * 100 : null,
      signals,
    }
  }, [rows])

  const legendRow = rows && rows.length > 0 ? rows[hoverIdx ?? rows.length - 1] : null
  const legendPrev = rows && legendRow ? rows[Math.max((hoverIdx ?? rows.length - 1) - 1, 0)] : null

  const setIndicator = (key: IndicatorKey) =>
    setSettings((s) => ({ ...s, indicators: { ...s.indicators, [key]: !s.indicators[key] } }))

  if (error) return <p className="hts-error">종목 목록을 불러오지 못했습니다: {error}</p>
  if (!universe) return <p>불러오는 중...</p>

  const currentAction = actions.get(ticker)?.action ?? (actions.size > 0 && !assetTickers.has(ticker) ? 'HOLD' : null)

  return (
    <div ref={rootRef} className={`hts${fullscreen ? ' is-fullscreen' : ''}`}>
      <aside className="hts-watch">
        <div className="hts-watch-controls">
          <select value={group} onChange={(e) => setGroup(e.target.value)} aria-label="종목 그룹">
            {groupOptions.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </select>
          <input
            ref={searchRef}
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="종목 검색 ( / )"
            aria-label="종목 검색"
          />
        </div>
        <div className="hts-watch-head">
          <span>종목</span>
          <span>종가</span>
          <span>신호</span>
        </div>
        <ul ref={listRef} className="hts-watch-list" role="listbox" aria-label="관심 종목">
          {watchlist.map((w) => (
            <li
              key={w.ticker}
              role="option"
              aria-selected={w.ticker === ticker}
              className={w.ticker === ticker ? 'active' : undefined}
              onClick={() => setTicker(w.ticker)}
              title={w.name}
            >
              <span className="hts-watch-name">
                <b>{w.ticker}</b>
                <small>{w.name}</small>
              </span>
              <span className="num">{fmtPrice(w.close)}</span>
              <span>
                <ActionBadge action={w.action} />
              </span>
            </li>
          ))}
          {watchlist.length === 0 && <li className="hts-empty">검색 결과 없음</li>}
        </ul>
      </aside>

      <section className="hts-main">
        <header className="hts-quote">
          <div className="hts-quote-title">
            <h2>{ticker}</h2>
            <span className="hts-quote-name">{nameOf.get(ticker)}</span>
            <ActionBadge action={currentAction} />
          </div>
          {stats && (
            <div className="hts-quote-price">
              <span className={`hts-last ${toneOf(stats.change)}`}>{fmtPrice(stats.last.Close)}</span>
              <span className={toneOf(stats.change)}>
                {stats.change > 0 ? '▲' : stats.change < 0 ? '▼' : ''} {fmtPrice(Math.abs(stats.change))} ({fmtPct(stats.changePct)})
              </span>
              <span className="hts-muted">{stats.last.Date} 종가</span>
            </div>
          )}
        </header>

        <div className="hts-toolbar" role="toolbar" aria-label="차트 설정">
          <div className="hts-seg" role="group" aria-label="기간">
            {RANGES.map((r) => (
              <button
                key={r.key}
                className={settings.range === r.key ? 'on' : undefined}
                aria-pressed={settings.range === r.key}
                onClick={() => setSettings((s) => ({ ...s, range: r.key }))}
              >
                {r.label}
              </button>
            ))}
          </div>
          <div className="hts-seg" role="group" aria-label="차트 종류">
            <button className={settings.chartType === 'candle' ? 'on' : undefined} aria-pressed={settings.chartType === 'candle'} onClick={() => setSettings((s) => ({ ...s, chartType: 'candle' }))}>
              캔들
            </button>
            <button className={settings.chartType === 'line' ? 'on' : undefined} aria-pressed={settings.chartType === 'line'} onClick={() => setSettings((s) => ({ ...s, chartType: 'line' }))}>
              라인
            </button>
            <button className={settings.logScale ? 'on' : undefined} aria-pressed={settings.logScale} onClick={() => setSettings((s) => ({ ...s, logScale: !s.logScale }))}>
              로그
            </button>
          </div>
          <div className="hts-chips" role="group" aria-label="보조지표">
            {INDICATORS.map((ind) => (
              <button
                key={ind.key}
                className={`hts-chip${settings.indicators[ind.key] ? ' on' : ''}`}
                aria-pressed={settings.indicators[ind.key]}
                onClick={() => setIndicator(ind.key)}
              >
                <i style={{ background: ind.color }} />
                {ind.label}
              </button>
            ))}
          </div>
          <button className="hts-icon-btn" onClick={toggleFullscreen} title="전체 화면 (F)" aria-label="전체 화면">
            {fullscreen ? '⤡' : '⤢'}
          </button>
        </div>

        <div className="hts-chart">
          {legendRow && legendPrev && (
            <div className="hts-legend" aria-live="off">
              <div>
                <span className="hts-muted">{legendRow.Date}</span>
                <span>시 <b className={toneOf(legendRow.Open - legendPrev.Close)}>{fmtPrice(legendRow.Open)}</b></span>
                <span>고 <b className={toneOf(legendRow.High - legendPrev.Close)}>{fmtPrice(legendRow.High)}</b></span>
                <span>저 <b className={toneOf(legendRow.Low - legendPrev.Close)}>{fmtPrice(legendRow.Low)}</b></span>
                <span>종 <b className={toneOf(legendRow.Close - legendPrev.Close)}>{fmtPrice(legendRow.Close)}</b></span>
                <span className={toneOf(legendRow.Close - legendPrev.Close)}>
                  {legendPrev.Close ? fmtPct(((legendRow.Close - legendPrev.Close) / legendPrev.Close) * 100) : ''}
                </span>
                <span>거래량 <b>{fmtVolume(legendRow.Volume)}</b>{legendRow.Volume_Surge && <em className="hts-surge">급증</em>}</span>
              </div>
              <div className="hts-legend-ind">
                {settings.indicators.stop && <span style={{ color: HTS_COLORS.stop }}>손절 {fmtPrice(legendRow.Trailing_Stop)}</span>}
                {settings.indicators.dc20 && (
                  <span style={{ color: HTS_COLORS.dc20 }}>DC20 {fmtPrice(legendRow.Donchian_Upper_20)} / {fmtPrice(legendRow.Donchian_Lower_20)}</span>
                )}
                {settings.indicators.dc100 && (
                  <span style={{ color: HTS_COLORS.dc100 }}>DC100 {fmtPrice(legendRow.Donchian_Upper_100)} / {fmtPrice(legendRow.Donchian_Lower_100)}</span>
                )}
                {settings.indicators.bb && (
                  <span style={{ color: HTS_COLORS.bb }}>BB {fmtPrice(legendRow.BB_Upper)} / {fmtPrice(legendRow.BB_Middle)} / {fmtPrice(legendRow.BB_Lower)}</span>
                )}
                {settings.indicators.ichimoku && (
                  <span style={{ color: HTS_COLORS.senkouA }}>선행A {fmtPrice(legendRow.Ichimoku_SenkouA)} · 선행B {fmtPrice(legendRow.Ichimoku_SenkouB)}</span>
                )}
                <span style={{ color: HTS_COLORS.atr }}>ATR(14) {fmtPrice(legendRow.ATR)}</span>
              </div>
            </div>
          )}
          {chartError && <p className="hts-chart-msg">차트 데이터를 불러오지 못했습니다: {chartError}</p>}
          {!chartError && !rows && <p className="hts-chart-msg">차트 불러오는 중...</p>}
          {rows && rows.length === 0 && <p className="hts-chart-msg">이 종목의 차트 데이터가 아직 없습니다.</p>}
          {rows && rows.length > 0 && <TickerChart ref={chartRef} rows={rows} settings={settings} onHover={handleHover} />}
        </div>

        {stats && (
          <div className="hts-info">
            <dl className="hts-stats">
              <div>
                <dt>52주 최고</dt>
                <dd className="num">{fmtPrice(stats.high52)}</dd>
              </div>
              <div>
                <dt>52주 최저</dt>
                <dd className="num">{fmtPrice(stats.low52)}</dd>
              </div>
              <div>
                <dt>20일 돌파선</dt>
                <dd className="num">{fmtPrice(stats.last.Donchian_Upper_20)}</dd>
              </div>
              <div>
                <dt>손절선 (3 ATR)</dt>
                <dd className="num">
                  {fmtPrice(stats.last.Trailing_Stop)}
                  {stats.stopGapPct != null && <small> 거리 {stats.stopGapPct.toFixed(1)}%</small>}
                </dd>
              </div>
              <div>
                <dt>ATR(14)</dt>
                <dd className="num">
                  {fmtPrice(stats.last.ATR)}
                  {stats.atrPct != null && <small> {stats.atrPct.toFixed(2)}%</small>}
                </dd>
              </div>
              <div>
                <dt>거래량</dt>
                <dd className="num">{fmtVolume(stats.last.Volume)}</dd>
              </div>
            </dl>
            <div className="hts-signals">
              <h3>최근 매매 신호</h3>
              {stats.signals.length === 0 ? (
                <p className="hts-muted">표시 기간 내 신호 없음</p>
              ) : (
                <ul>
                  {stats.signals.slice(0, 6).map((s) => (
                    <li key={s.date}>
                      <button onClick={() => chartRef.current?.focusDate(s.date)} title="차트에서 보기">
                        <span className="hts-muted">{s.date}</span>
                        <span className={s.kind === '매수' ? 'up' : 'down'}>{s.kind}</span>
                        <span className="num">{fmtPrice(s.close)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
        <p className="hts-hint">
          ↑/↓ 종목 이동 · 드래그/휠로 스크롤·확대 · / 검색 · F 전체 화면. 거래량 진한 막대는 거래량 급증일입니다. 보조지표는 참고용이며 매매 판단에 쓰이지 않습니다.
        </p>
      </section>
    </div>
  )
}

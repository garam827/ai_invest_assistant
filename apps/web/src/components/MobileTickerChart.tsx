import { useEffect, useRef } from 'react'
import {
  AreaSeries,
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type SeriesType,
  type Time,
} from 'lightweight-charts'
import type { ChartRow } from '../types'

export type Overlay = 'bb' | 'dc20' | 'dc100' | 'ichimoku' | 'stop' | 'markers'
export type Period = '1M' | '3M' | '6M' | '1Y' | 'ALL'

const PERIOD_SESSIONS: Record<Period, number | null> = { '1M': 21, '3M': 63, '6M': 126, '1Y': 252, ALL: null }

interface Props {
  rows: ChartRow[]
  theme: string
  overlays: Record<Overlay, boolean>
  period: Period
  onHover: (row: ChartRow | null) => void
}

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

// Mirrors chart_builder.py's overlay set as closely as a JS charting lib reasonably allows:
// candlestick + BB/DC20/DC100/trailing-stop overlays in pane 0, volume in pane 1, ATR in pane
// 2. lightweight-charts has no "fill between two arbitrary lines" primitive (unlike Plotly's
// fill="tonexty"), so the Ichimoku cloud is drawn as two plain lines (Senkou A/B) rather than
// a shaded band -- a deliberate v1 simplification, not a bug.
//
// Candle colours follow the Korean brokerage convention (rising = red, falling = blue) and are
// read from the CSS theme tokens, so the chart is rebuilt when the theme changes.
export function MobileTickerChart({ rows, theme, overlays, period, onHover }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const overlayRef = useRef<Partial<Record<Overlay, ISeriesApi<SeriesType>[]>>>({})
  const markersRef = useRef<{ setMarkers: (m: SeriesMarker<Time>[]) => void; all: SeriesMarker<Time>[] } | null>(null)
  const hoverRef = useRef(onHover)
  hoverRef.current = onHover

  useEffect(() => {
    const container = containerRef.current
    if (!container || rows.length === 0) return

    const up = cssVar('--up')
    const down = cssVar('--down')
    const text = cssVar('--text-3')
    const grid = cssVar('--chart-grid')
    const compact = container.clientWidth < 600

    const chart = createChart(container, {
      height: compact ? 520 : 620,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: text,
        fontSize: 11,
        fontFamily: getComputedStyle(document.body).fontFamily,
        attributionLogo: false,
        panes: { separatorColor: grid, separatorHoverColor: grid },
      },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, rightOffset: 3 },
      localization: { locale: 'ko-KR' },
    })
    chartRef.current = chart

    chart.addPane()
    chart.addPane()
    const PANE_PRICE = 0
    const PANE_VOLUME = 1
    const PANE_ATR = 2
    chart.panes()[PANE_PRICE].setHeight(compact ? 340 : 420)
    chart.panes()[PANE_VOLUME].setHeight(90)
    chart.panes()[PANE_ATR].setHeight(90)

    const times = rows.map((r) => r.Date as Time)
    const toLineData = (values: (number | null)[]) =>
      values
        .map((v, i) => (v == null ? null : { time: times[i], value: v }))
        .filter((d): d is { time: Time; value: number } => d != null)

    const candleSeries = chart.addSeries(
      CandlestickSeries,
      { upColor: up, downColor: down, borderVisible: false, wickUpColor: up, wickDownColor: down },
      PANE_PRICE,
    )
    candleSeries.setData(rows.map((r) => ({ time: r.Date as Time, open: r.Open, high: r.High, low: r.Low, close: r.Close })))

    const groups: Partial<Record<Overlay, ISeriesApi<SeriesType>[]>> = {}
    const addLine = (overlay: Overlay, values: (number | null)[], color: string, dashed = false) => {
      const series = chart.addSeries(
        LineSeries,
        { color, lineWidth: 1, lineStyle: dashed ? 2 : 0, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false },
        PANE_PRICE,
      )
      series.setData(toLineData(values))
      ;(groups[overlay] ??= []).push(series)
    }
    addLine('bb', rows.map((r) => r.BB_Upper), 'rgba(148,163,184,0.55)')
    addLine('bb', rows.map((r) => r.BB_Lower), 'rgba(148,163,184,0.55)')
    addLine('bb', rows.map((r) => r.BB_Middle), 'rgba(148,163,184,0.75)', true)
    addLine('dc20', rows.map((r) => r.Donchian_Upper_20), '#22c3a6', true)
    addLine('dc20', rows.map((r) => r.Donchian_Lower_20), '#22c3a6', true)
    addLine('dc100', rows.map((r) => r.Donchian_Upper_100), '#a78bfa', true)
    addLine('dc100', rows.map((r) => r.Donchian_Lower_100), '#a78bfa', true)
    addLine('stop', rows.map((r) => r.Trailing_Stop), '#ffb020')
    addLine('ichimoku', rows.map((r) => r.Ichimoku_SenkouA), 'rgba(244,114,182,0.6)')
    addLine('ichimoku', rows.map((r) => r.Ichimoku_SenkouB), 'rgba(56,189,248,0.6)')
    overlayRef.current = groups

    const allMarkers: SeriesMarker<Time>[] = []
    rows.forEach((r) => {
      if (r.Buy_Trigger) allMarkers.push({ time: r.Date as Time, position: 'belowBar', color: up, shape: 'arrowUp' })
      if (r.Sell_Trigger) allMarkers.push({ time: r.Date as Time, position: 'aboveBar', color: down, shape: 'arrowDown' })
    })
    const markerPlugin = createSeriesMarkers(candleSeries, allMarkers)
    markersRef.current = { setMarkers: (m) => markerPlugin.setMarkers(m), all: allMarkers }

    const volumeSeries = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false }, PANE_VOLUME)
    volumeSeries.setData(
      rows.map((r, i) => {
        const rising = r.Close >= (i > 0 ? rows[i - 1].Close : r.Open)
        const base = rising ? up : down
        return { time: r.Date as Time, value: r.Volume, color: r.Volume_Surge ? '#ffb020' : `${base}66` }
      }),
    )

    const atrSeries = chart.addSeries(
      AreaSeries,
      { lineColor: '#ffb020', lineWidth: 1, topColor: 'rgba(255,176,32,0.22)', bottomColor: 'rgba(255,176,32,0)', lastValueVisible: false, priceLineVisible: false },
      PANE_ATR,
    )
    atrSeries.setData(toLineData(rows.map((r) => r.ATR)))

    const byTime = new Map(rows.map((r) => [r.Date, r]))
    chart.subscribeCrosshairMove((param) => {
      hoverRef.current(param.time ? (byTime.get(String(param.time)) ?? null) : null)
    })

    const observer = new ResizeObserver(() => chart.applyOptions({ width: container.clientWidth }))
    observer.observe(container)

    return () => {
      observer.disconnect()
      chart.remove()
      chartRef.current = null
      overlayRef.current = {}
      markersRef.current = null
    }
  }, [rows, theme])

  useEffect(() => {
    for (const [key, series] of Object.entries(overlayRef.current) as [Overlay, ISeriesApi<SeriesType>[]][]) {
      series.forEach((s) => s.applyOptions({ visible: overlays[key] }))
    }
    const markers = markersRef.current
    if (markers) markers.setMarkers(overlays.markers ? markers.all : [])
  }, [overlays, rows, theme])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    const sessions = PERIOD_SESSIONS[period]
    if (sessions == null || sessions >= rows.length) {
      chart.timeScale().fitContent()
    } else {
      chart.timeScale().setVisibleLogicalRange({ from: rows.length - sessions, to: rows.length + 2 })
    }
  }, [period, rows, theme])

  return <div ref={containerRef} className="chart-canvas" />
}

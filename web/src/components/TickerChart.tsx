import { useEffect, useRef } from 'react'
import {
  AreaSeries,
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts'
import type { ChartRow } from '../types'

interface Props {
  ticker: string
  rows: ChartRow[]
}

// Mirrors chart_builder.py's overlay set as closely as a JS charting lib reasonably allows:
// candlestick + BB/DC20/DC100/trailing-stop overlays in pane 0, volume in pane 1, ATR in pane
// 2. lightweight-charts has no "fill between two arbitrary lines" primitive (unlike Plotly's
// fill="tonexty"), so the Ichimoku cloud is drawn as two plain lines (Senkou A/B) rather than
// a shaded band -- a deliberate v1 simplification, not a bug.
export function TickerChart({ ticker, rows }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container || rows.length === 0) return

    const chart: IChartApi = createChart(container, {
      height: 640,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#333' },
      grid: { vertLines: { color: 'rgba(150,150,150,0.15)' }, horzLines: { color: 'rgba(150,150,150,0.15)' } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false },
    })

    chart.addPane()
    chart.addPane()
    const PANE_PRICE = 0
    const PANE_VOLUME = 1
    const PANE_ATR = 2
    chart.panes()[PANE_PRICE].setHeight(360)
    chart.panes()[PANE_VOLUME].setHeight(140)
    chart.panes()[PANE_ATR].setHeight(140)

    const times = rows.map((r) => r.Date as Time)
    const toLineData = (values: (number | null)[]) =>
      values
        .map((v, i) => (v == null ? null : { time: times[i], value: v }))
        .filter((d): d is { time: Time; value: number } => d != null)

    const candleSeries = chart.addSeries(
      CandlestickSeries,
      { upColor: '#26a69a', downColor: '#ef5350', borderVisible: false, wickUpColor: '#26a69a', wickDownColor: '#ef5350' },
      PANE_PRICE,
    )
    candleSeries.setData(
      rows.map((r) => ({ time: r.Date as Time, open: r.Open, high: r.High, low: r.Low, close: r.Close })),
    )

    const addLine = (values: (number | null)[], color: string, dashed = false) => {
      const series = chart.addSeries(LineSeries, { color, lineWidth: 1, lineStyle: dashed ? 2 : 0, lastValueVisible: false, priceLineVisible: false }, PANE_PRICE)
      series.setData(toLineData(values))
      return series
    }
    addLine(rows.map((r) => r.BB_Upper), 'rgba(120,144,156,0.5)')
    addLine(rows.map((r) => r.BB_Lower), 'rgba(120,144,156,0.5)')
    addLine(rows.map((r) => r.BB_Middle), 'rgba(84,110,122,0.6)', true)
    addLine(rows.map((r) => r.Donchian_Upper_20), '#42a5f5', true)
    addLine(rows.map((r) => r.Donchian_Lower_20), '#42a5f5', true)
    addLine(rows.map((r) => r.Donchian_Upper_100), '#7e57c2', true)
    addLine(rows.map((r) => r.Donchian_Lower_100), '#7e57c2', true)
    addLine(rows.map((r) => r.Trailing_Stop), '#ef5350')
    addLine(rows.map((r) => r.Ichimoku_SenkouA), 'rgba(239,83,80,0.6)')
    addLine(rows.map((r) => r.Ichimoku_SenkouB), 'rgba(66,165,245,0.6)')

    const markers: SeriesMarker<Time>[] = []
    rows.forEach((r) => {
      if (r.Buy_Trigger) markers.push({ time: r.Date as Time, position: 'belowBar', color: '#2e7d32', shape: 'arrowUp', text: '매수' })
      if (r.Sell_Trigger) markers.push({ time: r.Date as Time, position: 'aboveBar', color: '#c62828', shape: 'arrowDown', text: '매도' })
    })
    createSeriesMarkers(candleSeries, markers)

    const volumeSeries = chart.addSeries(HistogramSeries, { color: '#90a4ae', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false }, PANE_VOLUME)
    volumeSeries.setData(
      rows.map((r) => ({ time: r.Date as Time, value: r.Volume, color: r.Volume_Surge ? '#ff7043' : '#90a4ae' })),
    )

    const atrSeries = chart.addSeries(AreaSeries, { lineColor: '#ffa726', topColor: 'rgba(255,167,38,0.2)', bottomColor: 'rgba(255,167,38,0.0)', lastValueVisible: false, priceLineVisible: false }, PANE_ATR)
    atrSeries.setData(toLineData(rows.map((r) => r.ATR)))

    chart.timeScale().fitContent()

    const resize = () => chart.applyOptions({ width: container.clientWidth })
    resize()
    window.addEventListener('resize', resize)

    return () => {
      window.removeEventListener('resize', resize)
      chart.remove()
    }
  }, [ticker, rows])

  return <div ref={containerRef} style={{ width: '100%' }} />
}

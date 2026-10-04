import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import {
  AreaSeries,
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  PriceScaleMode,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type MouseEventParams,
  type SeriesMarker,
  type SeriesType,
  type Time,
} from 'lightweight-charts'
import type { ChartRow } from '../types'
import { HTS_COLORS, RANGE_BARS, type ChartSettings, type IndicatorKey } from './chartConfig'

export interface TickerChartHandle {
  focusDate: (date: string) => void
}

interface Props {
  rows: ChartRow[]
  settings: ChartSettings
  onHover: (index: number | null) => void
}

interface SeriesBundle {
  candle: ISeriesApi<'Candlestick'>
  closeLine: ISeriesApi<'Line'>
  candleMarkers: ISeriesMarkersPluginApi<Time>
  lineMarkers: ISeriesMarkersPluginApi<Time>
  markers: SeriesMarker<Time>[]
  groups: Record<Exclude<IndicatorKey, 'signals'>, ISeriesApi<SeriesType>[]>
}

const PANE_PRICE = 0
const PANE_VOLUME = 1
const PANE_ATR = 2

function withAlpha(hex: string, alpha: number): string {
  const n = parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`
}

// Same overlay set as chart_builder.py (candles + BB/DC20/DC100/trailing stop/Ichimoku, volume
// pane, ATR pane). Overlays are display-only; they never feed the mechanical signal.
// lightweight-charts has no fill-between-lines primitive, so the Ichimoku cloud is drawn as its
// two Senkou span lines.
export const TickerChart = forwardRef<TickerChartHandle, Props>(function TickerChart({ rows, settings, onHover }, ref) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<SeriesBundle | null>(null)
  const onHoverRef = useRef(onHover)

  useEffect(() => {
    onHoverRef.current = onHover
  }, [onHover])

  useImperativeHandle(
    ref,
    () => ({
      focusDate: (date: string) => {
        const idx = rows.findIndex((r) => r.Date === date)
        if (idx < 0 || !chartRef.current) return
        chartRef.current.timeScale().setVisibleLogicalRange({ from: idx - 40, to: idx + 40 })
      },
    }),
    [rows],
  )

  // Build the chart once per data set; settings are applied in place below so toggling an
  // overlay never resets the user's zoom/scroll position.
  useEffect(() => {
    const container = containerRef.current
    if (!container || rows.length === 0) return

    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: HTS_COLORS.bg },
        textColor: HTS_COLORS.text,
        fontSize: 11,
        panes: { separatorColor: HTS_COLORS.border, separatorHoverColor: 'rgba(255,255,255,0.08)', enableResize: true },
      },
      grid: { vertLines: { color: HTS_COLORS.grid }, horzLines: { color: HTS_COLORS.grid } },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: HTS_COLORS.crosshair, labelBackgroundColor: '#363c4a' },
        horzLine: { color: HTS_COLORS.crosshair, labelBackgroundColor: '#363c4a' },
      },
      rightPriceScale: { borderColor: HTS_COLORS.border },
      timeScale: { borderColor: HTS_COLORS.border, rightOffset: 4, minBarSpacing: 2 },
      localization: { locale: 'ko-KR', dateFormat: 'yyyy-MM-dd' },
    })
    chartRef.current = chart

    chart.addPane()
    chart.addPane()
    chart.panes()[PANE_PRICE].setStretchFactor(5)
    chart.panes()[PANE_VOLUME].setStretchFactor(1.2)
    chart.panes()[PANE_ATR].setStretchFactor(1)

    const times = rows.map((r) => r.Date as Time)
    const toLineData = (values: (number | null)[]) =>
      values
        .map((v, i) => (v == null ? null : { time: times[i], value: v }))
        .filter((d): d is { time: Time; value: number } => d != null)

    const candle = chart.addSeries(
      CandlestickSeries,
      {
        upColor: HTS_COLORS.up,
        downColor: HTS_COLORS.down,
        borderUpColor: HTS_COLORS.up,
        borderDownColor: HTS_COLORS.down,
        wickUpColor: HTS_COLORS.up,
        wickDownColor: HTS_COLORS.down,
      },
      PANE_PRICE,
    )
    candle.setData(rows.map((r) => ({ time: r.Date as Time, open: r.Open, high: r.High, low: r.Low, close: r.Close })))

    const closeLine = chart.addSeries(LineSeries, { color: HTS_COLORS.close, lineWidth: 2, visible: false }, PANE_PRICE)
    closeLine.setData(toLineData(rows.map((r) => r.Close)))

    const addLine = (values: (number | null)[], color: string, opts: { dashed?: boolean; title?: string; width?: 1 | 2 } = {}) => {
      const series = chart.addSeries(
        LineSeries,
        {
          color,
          lineWidth: opts.width ?? 1,
          lineStyle: opts.dashed ? LineStyle.Dashed : LineStyle.Solid,
          lastValueVisible: Boolean(opts.title),
          title: opts.title ?? '',
          priceLineVisible: false,
          crosshairMarkerVisible: false,
        },
        PANE_PRICE,
      )
      series.setData(toLineData(values))
      return series
    }

    const groups: SeriesBundle['groups'] = {
      bb: [
        addLine(rows.map((r) => r.BB_Upper), HTS_COLORS.bb),
        addLine(rows.map((r) => r.BB_Lower), HTS_COLORS.bb),
        addLine(rows.map((r) => r.BB_Middle), HTS_COLORS.bb, { dashed: true }),
      ],
      dc20: [
        addLine(rows.map((r) => r.Donchian_Upper_20), HTS_COLORS.dc20, { dashed: true }),
        addLine(rows.map((r) => r.Donchian_Lower_20), HTS_COLORS.dc20, { dashed: true }),
      ],
      dc100: [
        addLine(rows.map((r) => r.Donchian_Upper_100), HTS_COLORS.dc100, { dashed: true }),
        addLine(rows.map((r) => r.Donchian_Lower_100), HTS_COLORS.dc100, { dashed: true }),
      ],
      stop: [addLine(rows.map((r) => r.Trailing_Stop), HTS_COLORS.stop, { title: '손절', width: 2 })],
      ichimoku: [
        addLine(rows.map((r) => r.Ichimoku_SenkouA), HTS_COLORS.senkouA),
        addLine(rows.map((r) => r.Ichimoku_SenkouB), HTS_COLORS.senkouB),
      ],
    }

    const markers: SeriesMarker<Time>[] = []
    rows.forEach((r) => {
      if (r.Buy_Trigger) markers.push({ time: r.Date as Time, position: 'belowBar', color: HTS_COLORS.up, shape: 'arrowUp' })
      if (r.Sell_Trigger) markers.push({ time: r.Date as Time, position: 'aboveBar', color: HTS_COLORS.down, shape: 'arrowDown' })
    })

    const volume = chart.addSeries(
      HistogramSeries,
      { priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false },
      PANE_VOLUME,
    )
    volume.setData(
      rows.map((r) => {
        const base = r.Close >= r.Open ? HTS_COLORS.up : HTS_COLORS.down
        return { time: r.Date as Time, value: r.Volume, color: withAlpha(base, r.Volume_Surge ? 0.95 : 0.45) }
      }),
    )

    const atr = chart.addSeries(
      AreaSeries,
      {
        lineColor: HTS_COLORS.atr,
        lineWidth: 1,
        topColor: withAlpha(HTS_COLORS.atr, 0.25),
        bottomColor: withAlpha(HTS_COLORS.atr, 0),
        priceLineVisible: false,
        crosshairMarkerVisible: false,
      },
      PANE_ATR,
    )
    atr.setData(toLineData(rows.map((r) => r.ATR)))

    seriesRef.current = {
      candle,
      closeLine,
      candleMarkers: createSeriesMarkers(candle, []),
      lineMarkers: createSeriesMarkers(closeLine, []),
      markers,
      groups,
    }

    const indexByTime = new Map(rows.map((r, i) => [r.Date, i]))
    const handleMove = (param: MouseEventParams<Time>) => {
      const idx = param.point && param.time != null ? indexByTime.get(String(param.time)) : undefined
      onHoverRef.current(idx ?? null)
    }
    chart.subscribeCrosshairMove(handleMove)

    return () => {
      chart.unsubscribeCrosshairMove(handleMove)
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [rows])

  const { chartType, logScale, indicators, range } = settings

  useEffect(() => {
    const s = seriesRef.current
    if (!s) return
    const candleMode = chartType === 'candle'
    s.candle.applyOptions({ visible: candleMode })
    s.closeLine.applyOptions({ visible: !candleMode })
    const shown = indicators.signals ? s.markers : []
    s.candleMarkers.setMarkers(candleMode ? shown : [])
    s.lineMarkers.setMarkers(candleMode ? [] : shown)
    ;(Object.keys(s.groups) as (keyof SeriesBundle['groups'])[]).forEach((key) => {
      s.groups[key].forEach((series) => series.applyOptions({ visible: indicators[key] }))
    })
    s.candle.priceScale().applyOptions({ mode: logScale ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal })
  }, [rows, chartType, logScale, indicators])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    const bars = RANGE_BARS[range]
    if (bars == null || bars >= rows.length) {
      chart.timeScale().fitContent()
    } else {
      chart.timeScale().setVisibleLogicalRange({ from: rows.length - bars, to: rows.length + 3 })
    }
  }, [rows, range])

  return <div ref={containerRef} className="hts-chart-canvas" />
})

// Korean HTS convention: rising = red, falling = blue.
export const HTS_COLORS = {
  up: '#f23645',
  down: '#2b7bf3',
  bg: '#12161f',
  grid: 'rgba(255,255,255,0.05)',
  border: '#2a2f3a',
  text: '#a9b1c1',
  crosshair: '#6b7385',
  bb: 'rgba(171,178,191,0.55)',
  dc20: '#26c6da',
  dc100: '#b388ff',
  stop: '#ff9800',
  senkouA: 'rgba(242,54,69,0.55)',
  senkouB: 'rgba(43,123,243,0.55)',
  atr: '#ffb74d',
  close: '#e0e3eb',
} as const

export type RangeKey = '1M' | '3M' | '6M' | '1Y' | 'ALL'
export const RANGE_BARS: Record<RangeKey, number | null> = { '1M': 21, '3M': 63, '6M': 126, '1Y': 252, ALL: null }

export type IndicatorKey = 'bb' | 'dc20' | 'dc100' | 'stop' | 'ichimoku' | 'signals'

export interface ChartSettings {
  range: RangeKey
  chartType: 'candle' | 'line'
  logScale: boolean
  indicators: Record<IndicatorKey, boolean>
}

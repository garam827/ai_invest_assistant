// Mirrors static_export.py's JSON output shapes exactly (docs/data/*.json) -- keep in sync
// with that module if the export schema changes.

export type Action = '매수' | 'HOLD' | '매도'

export interface NewsItem {
  title: string
  summary: string
  publisher: string
  link: string
  published_at: string | null
}

export interface AssetClassSignal {
  ticker: string
  action: Action
  text: string
  news: NewsItem[]
  close: number
  date: string
  label: string
  category: string
}

export interface SignalsAssetClass {
  generated_at: string
  overview: string | null
  tickers: AssetClassSignal[]
}

export interface Sp500Signal {
  ticker: string
  description: string
  sector: string
  action: Action
  close: number
  date: string
}

export interface SignalsSp500 {
  generated_at: string
  signals: Sp500Signal[]
}

export interface AssetClassMeta {
  ticker: string
  label: string
  category: string
  description: string
}

export interface Sp500Meta {
  ticker: string
  sector: string
  description: string
}

export interface Universe {
  asset_classes: AssetClassMeta[]
  sp500: Sp500Meta[]
}

// One row of docs/data/charts/{ticker}.json. Numeric indicator columns are `number | null` --
// null covers a recently-listed ticker's Donchian-100/ATR/Ichimoku warm-up period (see
// static_export._chart_rows_for_ticker).
export interface ChartRow {
  Date: string
  Open: number
  High: number
  Low: number
  Close: number
  Volume: number
  ATR: number | null
  Donchian_Upper_20: number | null
  Donchian_Lower_20: number | null
  Donchian_Upper_100: number | null
  Donchian_Lower_100: number | null
  Trailing_Stop: number | null
  BB_Upper: number | null
  BB_Lower: number | null
  BB_Middle: number | null
  Ichimoku_SenkouA: number | null
  Ichimoku_SenkouB: number | null
  Ichimoku_SenkouA_Raw: number | null
  Ichimoku_SenkouB_Raw: number | null
  Buy_Trigger: boolean
  Sell_Trigger: boolean
  Volume_Surge: boolean
}

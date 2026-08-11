import type { ChartRow, SignalsAssetClass, SignalsSp500, Universe } from './types'

// import.meta.env.BASE_URL is Vite's own copy of vite.config.ts's `base` ('/ai_invest_assistant/'
// in production, '/' in dev) -- using it instead of a hardcoded path keeps `npm run dev` working
// against a local docs/data/ copy without any extra proxy config.
const DATA_BASE = `${import.meta.env.BASE_URL}data`

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${DATA_BASE}/${path}`)
  if (!res.ok) {
    throw new Error(`${path}: ${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

export const fetchSignalsAssetClass = () => fetchJson<SignalsAssetClass>('signals_asset_class.json')
export const fetchSignalsSp500 = () => fetchJson<SignalsSp500>('signals_sp500.json')
export const fetchUniverse = () => fetchJson<Universe>('universe.json')
export const fetchChart = (ticker: string) => fetchJson<ChartRow[]>(`charts/${encodeURIComponent(ticker)}.json`)

import type { ChartRow, ReportsIndex, SignalsAssetClass, SignalsSp500, Universe } from './types'

// import.meta.env.BASE_URL is Vite's own copy of vite.config.ts's `base` ('/ai_invest_assistant/'
// in production, '/' in dev) -- using it instead of a hardcoded path keeps `npm run dev` working
// against a local docs/data/ copy without any extra proxy config.
const DATA_BASE = `${import.meta.env.BASE_URL}data`

// The header ticker tape, watchlist sparklines and chart tab all read the same files, so each
// path is fetched once per page load and the promise is shared. Failed fetches are evicted so a
// later mount can retry.
const cache = new Map<string, Promise<unknown>>()

function fetchJson<T>(path: string): Promise<T> {
  const cached = cache.get(path)
  if (cached) return cached as Promise<T>
  const promise = fetch(`${DATA_BASE}/${path}`).then((res) => {
    if (!res.ok) throw new Error(`${path}: ${res.status} ${res.statusText}`)
    return res.json() as Promise<T>
  })
  promise.catch(() => cache.delete(path))
  cache.set(path, promise)
  return promise
}

export const fetchSignalsAssetClass = () => fetchJson<SignalsAssetClass>('signals_asset_class.json')
export const fetchSignalsSp500 = () => fetchJson<SignalsSp500>('signals_sp500.json')
export const fetchUniverse = () => fetchJson<Universe>('universe.json')
export const fetchChart = (ticker: string) => fetchJson<ChartRow[]>(`charts/${encodeURIComponent(ticker)}.json`)
export const fetchReportsIndex = () => fetchJson<ReportsIndex>('reports.json')

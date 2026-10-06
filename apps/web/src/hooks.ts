import { useEffect, useState } from 'react'
import { fetchChart } from './api'
import { dailyChange, type DailyChange } from './format'

export interface AsyncState<T> {
  data: T | null
  error: string | null
}

// Resolves a (shared, cached) fetch promise into component state. `key` re-runs the loader,
// and a stale response from a previous key is ignored.
export function useAsync<T>(load: () => Promise<T>, key: string): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T> & { key: string }>({ data: null, error: null, key })

  useEffect(() => {
    let active = true
    load()
      .then((data) => active && setState({ data, error: null, key }))
      .catch((e: Error) => active && setState({ data: null, error: e.message, key }))
    return () => {
      active = false
    }
    // `load` is expected to be derived from `key`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  return state.key === key ? state : { data: null, error: null }
}

export interface Quote {
  change: DailyChange | null
  closes: number[]
}

// Daily change and a 30-session sparkline per ticker, derived from the per-ticker chart files
// (the signal JSON only carries the latest close). Quotes fill in as each file arrives; a
// failed file simply leaves that ticker without a change figure.
export function useQuotes(tickers: string[]): Record<string, Quote> {
  const [quotes, setQuotes] = useState<Record<string, Quote>>({})
  const key = tickers.join(',')

  useEffect(() => {
    let active = true
    for (const ticker of tickers) {
      fetchChart(ticker)
        .then((rows) => {
          if (!active) return
          const quote = { change: dailyChange(rows), closes: rows.slice(-30).map((r) => r.Close) }
          setQuotes((prev) => ({ ...prev, [ticker]: quote }))
        })
        .catch(() => undefined)
    }
    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  return quotes
}

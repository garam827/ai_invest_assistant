import { useEffect, useState } from 'react'
import { HtsChartView } from './HtsChartView'
import { MobileChartView, type ChartViewProps } from './MobileChartView'

// Wide screens get the HTS trading screen (watchlist sidebar, log scale, fullscreen, keyboard
// navigation); phones get the MTS-style single-column chart. Both share the selected ticker
// through App, so switching layouts (rotation, resizing) keeps the same instrument.
const WIDE_QUERY = '(min-width: 900px)'

function useIsWide(): boolean {
  const [wide, setWide] = useState(() => window.matchMedia(WIDE_QUERY).matches)
  useEffect(() => {
    const mql = window.matchMedia(WIDE_QUERY)
    const onChange = () => setWide(mql.matches)
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [])
  return wide
}

export function ChartView(props: ChartViewProps) {
  return useIsWide() ? <HtsChartView {...props} /> : <MobileChartView {...props} />
}

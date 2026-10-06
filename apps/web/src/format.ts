import type { Action, ChartRow } from './types'

export type Direction = 'up' | 'down' | 'flat'

export interface DailyChange {
  close: number
  diff: number
  pct: number
  dir: Direction
}

// Korean brokerage convention: rising = red, falling = blue; buy = red, sell = blue.
export const ACTION_TONE: Record<Action, Direction> = { 매수: 'up', HOLD: 'flat', 매도: 'down' }

export function dailyChange(rows: ChartRow[]): DailyChange | null {
  if (rows.length < 2) return null
  const close = rows[rows.length - 1].Close
  const prev = rows[rows.length - 2].Close
  const diff = close - prev
  const pct = prev === 0 ? 0 : (diff / prev) * 100
  return { close, diff, pct, dir: directionOf(diff) }
}

export function directionOf(value: number): Direction {
  if (value > 0) return 'up'
  if (value < 0) return 'down'
  return 'flat'
}

export function fmtPrice(value: number): string {
  const digits = Math.abs(value) >= 1 ? 2 : 4
  return value.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function fmtSignedPrice(value: number): string {
  const arrow = value > 0 ? '▲' : value < 0 ? '▼' : ''
  return `${arrow}${fmtPrice(Math.abs(value))}`
}

export function fmtPct(value: number): string {
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

export function fmtVolume(value: number): string {
  if (value >= 1e9) return `${(value / 1e9).toFixed(2)}B`
  if (value >= 1e6) return `${(value / 1e6).toFixed(2)}M`
  if (value >= 1e3) return `${(value / 1e3).toFixed(1)}K`
  return value.toLocaleString('en-US')
}

export function fmtKst(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토']

export function weekdayOf(date: string): string {
  const d = new Date(`${date.slice(0, 10)}T00:00:00Z`)
  return Number.isNaN(d.getTime()) ? '' : WEEKDAYS[d.getUTCDay()]
}

// "S&P 500 (미국 대형주)" -> ["S&P 500", "미국 대형주"], so rows can show a short name with a
// muted subtitle the way brokerage watchlists do.
export function splitLabel(label: string): [string, string] {
  const match = label.match(/^(.*?)\s*\((.*)\)\s*$/)
  return match ? [match[1], match[2]] : [label, '']
}

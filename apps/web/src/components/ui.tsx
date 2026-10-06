import type { ReactNode } from 'react'
import { ACTION_TONE, type Direction } from '../format'
import type { Action } from '../types'

export function ActionPill({ action, solid = false }: { action: Action; solid?: boolean }) {
  return <span className={`pill tone-${ACTION_TONE[action]}${solid ? ' solid' : ''}`}>{action}</span>
}

export function Sparkline({ values, dir }: { values: number[]; dir: Direction }) {
  if (values.length < 2) return <svg className="spark" viewBox="0 0 64 28" aria-hidden />
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const points = values
    .map((v, i) => `${((i / (values.length - 1)) * 64).toFixed(1)},${(26 - ((v - min) / span) * 24).toFixed(1)}`)
    .join(' ')
  return (
    <svg className={`spark tone-${dir}`} viewBox="0 0 64 28" preserveAspectRatio="none" aria-hidden>
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  )
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T
  options: readonly (readonly [T, ReactNode])[]
  onChange: (value: T) => void
}) {
  return (
    <div className="segmented" role="tablist">
      {options.map(([key, label]) => (
        <button key={key} role="tab" aria-selected={value === key} className={value === key ? 'active' : ''} onClick={() => onChange(key)}>
          {label}
        </button>
      ))}
    </div>
  )
}

export function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button className={`chip${active ? ' active' : ''}`} aria-pressed={active} onClick={onClick}>
      {children}
    </button>
  )
}

export function StatusMessage({ error, children }: { error?: string | null; children?: ReactNode }) {
  if (error) return <div className="status error">{children ?? '데이터를 불러오지 못했습니다'}: {error}</div>
  return (
    <div className="status">
      <span className="spinner" aria-hidden />
      {children ?? '불러오는 중...'}
    </div>
  )
}

export function SearchInput({ value, onChange, placeholder, autoFocus }: { value: string; onChange: (v: string) => void; placeholder: string; autoFocus?: boolean }) {
  return (
    <label className="search">
      <svg viewBox="0 0 24 24" aria-hidden>
        <circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" strokeWidth="2" />
        <path d="M20 20l-4-4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </svg>
      <input type="search" value={value} placeholder={placeholder} autoFocus={autoFocus} onChange={(e) => onChange(e.target.value)} />
      {value && (
        <button type="button" className="search-clear" aria-label="지우기" onClick={() => onChange('')}>
          ×
        </button>
      )}
    </label>
  )
}

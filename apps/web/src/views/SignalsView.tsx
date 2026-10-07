import { useMemo, useState } from 'react'
import { fetchSignalsAssetClass, fetchSignalsSp500 } from '../api'
import { ActionPill, Chip, SearchInput, Segmented, Sparkline, StatusMessage } from '../components/ui'
import { fmtPct, fmtPrice, splitLabel } from '../format'
import { useAsync, useQuotes, type Quote } from '../hooks'
import type { Action, AssetClassSignal, Sp500Signal } from '../types'

type Section = 'asset' | 'sp500'
type ActionFilter = 'all' | Action

interface Props {
  onOpenChart: (ticker: string) => void
}

function countActions(actions: Action[]): Record<Action, number> {
  const counts: Record<Action, number> = { 매수: 0, HOLD: 0, 매도: 0 }
  actions.forEach((a) => (counts[a] += 1))
  return counts
}

function SummaryCard({ counts, total, date }: { counts: Record<Action, number>; total: number; date: string }) {
  return (
    <section className="card summary">
      <div className="summary-head">
        <div>
          <div className="eyebrow">대표 자산군 시그널</div>
          <div className="summary-date">{date.slice(0, 10)} 종가 기준</div>
        </div>
        <div className="summary-total num">{total}종목</div>
      </div>
      <div className="ratio-bar" aria-hidden>
        {(['매수', 'HOLD', '매도'] as const).map((a) =>
          counts[a] > 0 ? <span key={a} className={`seg seg-${a === '매수' ? 'up' : a === '매도' ? 'down' : 'flat'}`} style={{ flexGrow: counts[a] }} /> : null,
        )}
      </div>
      <div className="summary-stats">
        <div>
          <span className="stat-label">매수</span>
          <span className="stat-value num tone-up">{counts['매수']}</span>
        </div>
        <div>
          <span className="stat-label">HOLD</span>
          <span className="stat-value num">{counts.HOLD}</span>
        </div>
        <div>
          <span className="stat-label">매도</span>
          <span className="stat-value num tone-down">{counts['매도']}</span>
        </div>
      </div>
    </section>
  )
}

function Briefing({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  return (
    <section className="card briefing">
      <div className="briefing-head">
        <span className="badge-ai">AI</span>
        <span className="briefing-title">오늘의 시황 브리핑</span>
      </div>
      <p className={open ? 'briefing-text' : 'briefing-text clamped'}>{text}</p>
      <button className="link-btn" onClick={() => setOpen(!open)}>
        {open ? '접기' : '전체 보기'}
      </button>
    </section>
  )
}

function AssetRow({ item, quote, expanded, onToggle, onOpenChart }: { item: AssetClassSignal; quote?: Quote; expanded: boolean; onToggle: () => void; onOpenChart: () => void }) {
  const [name, sub] = splitLabel(item.label)
  const change = quote?.change
  const dir = change?.dir ?? 'flat'
  return (
    <li className={`row-wrap${expanded ? ' expanded' : ''}`}>
      <button className="row" aria-expanded={expanded} onClick={onToggle}>
        <div className="row-main">
          <div className="row-title">
            <span className="cat">{item.category}</span>
            <span className="ellipsis">{name}</span>
          </div>
          <div className="row-sub ellipsis">
            {item.ticker}
            {sub && ` · ${sub}`}
          </div>
        </div>
        <Sparkline values={quote?.closes ?? []} dir={dir} />
        <div className="row-quote">
          <div className={`num price tone-${dir}`}>{fmtPrice(change?.close ?? item.close)}</div>
          <div className={`num change tone-${dir}`}>{change ? fmtPct(change.pct) : '—'}</div>
        </div>
        <ActionPill action={item.action} />
      </button>
      {expanded && (
        <div className="row-detail">
          <p className="detail-text">{item.text}</p>
          {item.news.length > 0 && (
            <div className="news">
              <div className="eyebrow">관련 뉴스 {item.news.length}</div>
              {item.news.map((n) => (
                <a key={n.link || n.title} className="news-item" href={n.link} target="_blank" rel="noreferrer">
                  <div className="news-title">{n.title}</div>
                  <div className="news-meta">
                    {n.publisher}
                    {n.published_at ? ` · ${n.published_at}` : ''}
                  </div>
                  {n.summary && <div className="news-summary">{n.summary}</div>}
                </a>
              ))}
            </div>
          )}
          <button className="primary-btn" onClick={onOpenChart}>
            {item.ticker} 차트 보기
          </button>
        </div>
      )}
    </li>
  )
}

function Sp500Row({ item, onOpen }: { item: Sp500Signal; onOpen: () => void }) {
  const [company, industry] = splitLabel(item.description || item.ticker)
  return (
    <li>
      <button className="row" onClick={onOpen}>
        <div className="row-main">
          <div className="row-title">
            <span className="ticker-code">{item.ticker}</span>
            <span className="ellipsis">{company}</span>
          </div>
          <div className="row-sub ellipsis">{industry || item.sector}</div>
        </div>
        <div className="row-quote">
          <div className="num price">{fmtPrice(item.close)}</div>
          <div className="num change muted">{item.date.slice(5, 10)}</div>
        </div>
        <ActionPill action={item.action} />
      </button>
    </li>
  )
}

function Sp500List({ signals, onOpenChart }: { signals: Sp500Signal[]; onOpenChart: (ticker: string) => void }) {
  const [filter, setFilter] = useState<ActionFilter>('all')
  const [query, setQuery] = useState('')
  const counts = useMemo(() => countActions(signals.map((s) => s.action)), [signals])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return signals
      .filter((s) => filter === 'all' || s.action === filter)
      .filter((s) => !q || s.ticker.toLowerCase().includes(q) || s.description.toLowerCase().includes(q) || s.sector.toLowerCase().includes(q))
      .sort((a, b) => a.action.localeCompare(b.action) || a.ticker.localeCompare(b.ticker))
  }, [signals, filter, query])

  return (
    <>
      <div className="toolbar">
        <SearchInput value={query} onChange={setQuery} placeholder="티커·종목명·섹터 검색" />
        <div className="chips">
          <Chip active={filter === 'all'} onClick={() => setFilter('all')}>
            전체 <span className="num">{signals.length}</span>
          </Chip>
          <Chip active={filter === '매수'} onClick={() => setFilter('매수')}>
            매수 <span className="num tone-up">{counts['매수']}</span>
          </Chip>
          <Chip active={filter === '매도'} onClick={() => setFilter('매도')}>
            매도 <span className="num tone-down">{counts['매도']}</span>
          </Chip>
        </div>
      </div>
      <p className="note">기계적 규칙(Donchian 돌파/추세추종 청산)만으로 판정합니다. 뉴스·LLM 분석은 대표 자산군 12종에만 적용됩니다.</p>
      {visible.length === 0 ? (
        <div className="empty">{signals.length === 0 ? '오늘은 매수/매도 시그널이 발생한 S&P 500 종목이 없습니다.' : '조건에 맞는 종목이 없습니다.'}</div>
      ) : (
        <ul className="list card">
          {visible.map((s) => (
            <Sp500Row key={s.ticker} item={s} onOpen={() => onOpenChart(s.ticker)} />
          ))}
        </ul>
      )}
    </>
  )
}

export function SignalsView({ onOpenChart }: Props) {
  const assetClass = useAsync(fetchSignalsAssetClass, 'asset-class')
  const sp500 = useAsync(fetchSignalsSp500, 'sp500')
  const [section, setSection] = useState<Section>('asset')
  const [expanded, setExpanded] = useState<string | null>(null)
  const quotes = useQuotes(assetClass.data?.tickers.map((t) => t.ticker) ?? [])

  const error = assetClass.error ?? sp500.error
  if (error) return <StatusMessage error={error} />
  if (!assetClass.data || !sp500.data) return <StatusMessage />

  const tickers = assetClass.data.tickers
  const counts = countActions(tickers.map((t) => t.action))

  return (
    <div className="stack">
      <SummaryCard counts={counts} total={tickers.length} date={tickers[0]?.date ?? assetClass.data.generated_at} />
      {assetClass.data.overview && <Briefing text={assetClass.data.overview} />}

      <Segmented
        value={section}
        onChange={setSection}
        options={[
          ['asset', `대표 자산군 ${tickers.length}`],
          ['sp500', `S&P 500 ${sp500.data.signals.length}`],
        ]}
      />

      {section === 'asset' ? (
        <ul className="list card">
          <li className="list-head" aria-hidden>
            <span>종목</span>
            <span>현재가 · 등락률</span>
          </li>
          {tickers.map((item) => (
            <AssetRow
              key={item.ticker}
              item={item}
              quote={quotes[item.ticker]}
              expanded={expanded === item.ticker}
              onToggle={() => setExpanded(expanded === item.ticker ? null : item.ticker)}
              onOpenChart={() => onOpenChart(item.ticker)}
            />
          ))}
        </ul>
      ) : (
        <Sp500List signals={sp500.data.signals} onOpenChart={onOpenChart} />
      )}

      <p className="disclaimer">
        매일 자동으로 계산된 매수/HOLD/매도 시그널을 보여주는 정적 페이지입니다. 이 화면에서는 뉴스 수집이나 LLM 호출이 실시간으로 일어나지 않으며, 투자 판단의 책임은 본인에게 있습니다.
      </p>
    </div>
  )
}

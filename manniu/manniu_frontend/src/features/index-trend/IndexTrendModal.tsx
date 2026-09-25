import { useEffect, useRef, useState } from 'react'
import { fetchCompositeTrend, fetchMarketSentimentTrend, fetchShanghaiTrend, type IndexTrendPayload, type IndexTrendPoint } from './indexTrendApi'
import './index-trend.css'
import './index-trend-overrides.css'

type Metric = 'PE' | 'PETTM' | 'PB'
type WindowKey = '30D' | '60D' | '90D' | '1Y' | '3Y' | '5Y' | '10Y' | 'ALL'
type TrendTarget = 'composite' | 'shanghai'

type Summary = {
  current: number
  percentile: number
  p10: number
  p50: number
  p90: number
  date: string
}

const metricLabels: Record<Metric, string> = { PE: 'PE', PETTM: 'PETTM', PB: 'PB' }
const windowLabels: Array<[WindowKey, string]> = [['30D', '30D'], ['60D', '60D'], ['90D', '90D'], ['1Y', '1Y'], ['3Y', '3Y'], ['5Y', '5Y'], ['10Y', '10Y'], ['ALL', '所有']]
function formatValue(value: number, metric: Metric) { return value.toFixed(metric === 'PB' ? 2 : 2) }

function monthlyTicks(startDate: string, endDate: string) {
  if (!startDate || !endDate) return []
  const start = new Date(`${startDate}T00:00:00Z`)
  const end = new Date(`${endDate}T00:00:00Z`)
  const anchorDay = start.getUTCDate()
  const ticks: Array<{ date: string; label: string }> = []
  for (let monthOffset = 0; ; monthOffset += 1) {
    const targetMonth = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + monthOffset, 1))
    const lastDay = new Date(Date.UTC(targetMonth.getUTCFullYear(), targetMonth.getUTCMonth() + 1, 0)).getUTCDate()
    const tickDate = new Date(Date.UTC(targetMonth.getUTCFullYear(), targetMonth.getUTCMonth(), Math.min(anchorDay, lastDay)))
    if (tickDate > end) break
    const date = tickDate.toISOString().slice(0, 10)
    ticks.push({ date, label: date })
  }
  return ticks
}

function toSummary(payload: IndexTrendPayload): Summary {
  const summary = payload.summary
  return {
    current: summary.current ?? payload.points.at(-1)?.value ?? 0,
    percentile: summary.percentile ?? 0,
    p10: summary.p10 ?? 0,
    p50: summary.p50 ?? 0,
    p90: summary.p90 ?? 0,
    date: summary.end_date ?? payload.points.at(-1)?.date ?? '',
  }
}

function TrendChart({ values, dates, summary, metric, label, color, loading }: { values: number[]; dates: string[]; summary: Summary; metric: Metric; label: string; color: string; loading?: boolean }) {
  const width = 640
  const height = 216
  const pad = { top: 18, right: 46, bottom: 30, left: 38 }
  const allValues = [...values, summary.p10, summary.p50, summary.p90]
  const rawMin = Math.min(...allValues)
  const rawMax = Math.max(...allValues)
  const rawRange = Math.max(rawMax - rawMin, 0)
  const midpoint = (rawMin + rawMax) / 2
  const minimumVisualRange = metric === 'PB' ? Math.max(Math.abs(midpoint) * 0.35, 0.4) : 0
  const visualRange = Math.max(rawRange, minimumVisualRange, 1e-6)
  const min = midpoint - visualRange / 2 - visualRange * 0.12
  const max = midpoint + visualRange / 2 + visualRange * 0.12
  const domainStart = dates[0] ?? ''
  const domainEnd = dates.at(-1) ?? domainStart
  const domainStartTime = Date.parse(`${domainStart}T00:00:00`)
  const domainDuration = Math.max(Date.parse(`${domainEnd}T00:00:00`) - domainStartTime, 1)
  const x = (date: string) => pad.left + ((Date.parse(`${date}T00:00:00`) - domainStartTime) / domainDuration) * (width - pad.left - pad.right)
  const y = (value: number) => pad.top + ((max - value) / Math.max(max - min, 1)) * (height - pad.top - pad.bottom)
  const points = values.map((value, index) => `${x(dates[index])},${y(value)}`).join(' ')
  const gridValues = [min + (max - min) * 0.15, min + (max - min) * 0.5, min + (max - min) * 0.85]
  const ticks = monthlyTicks(domainStart, domainEnd)

  return <div className="index-trend-chart-wrap">
    {loading && <div className="index-trend-chart-loading">正在加载...</div>}
    <svg className="index-trend-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${label}${metric}历史趋势`}>
      {gridValues.map((value) => <line key={value} x1={pad.left} x2={width - pad.right} y1={y(value)} y2={y(value)} className="index-trend-grid" />)}
      {ticks.map(({ date, label }) => <g key={date}><line x1={x(date)} x2={x(date)} y1={pad.top} y2={height - pad.bottom} className="index-trend-month-grid" />{label && <text x={x(date)} y={height - 15} textAnchor="middle" className="index-trend-axis-label">{label}</text>}</g>)}
      {[['P90', summary.p90, '#e56b55'], ['P50', summary.p50, '#e6a33d'], ['P10', summary.p10, '#39a98b']].map(([name, value, lineColor]) => <g key={name as string}><line x1={pad.left} x2={width - pad.right} y1={y(value as number)} y2={y(value as number)} stroke={lineColor as string} className="index-trend-reference" /><text x={width - pad.right + 7} y={y(value as number) + 4} fill={lineColor as string} className="index-trend-reference-label">{name as string}</text></g>)}
      <polyline points={points} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
    <MarketSentimentChart dates={dates} />
  </div>
}

function MarketSentimentChart({ dates }: { dates: string[] }) {
  const [points, setPoints] = useState<IndexTrendPoint[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const endDate = dates.at(-1) ?? new Date().toISOString().slice(0, 10)
  const yearAgo = new Date(`${endDate}T00:00:00`)
  yearAgo.setDate(yearAgo.getDate() - 365)
  const earliestDate = yearAgo.toISOString().slice(0, 10)
  const startDate = dates[0] && dates[0] > earliestDate ? dates[0] : earliestDate

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')
    fetchMarketSentimentTrend(startDate, endDate, controller.signal).then((loadedPoints) => {
      setPoints(loadedPoints)
    }).catch((requestError: unknown) => {
      if (!controller.signal.aborted) {
        setError(requestError instanceof Error ? requestError.message : '市场情绪历史加载失败。')
      }
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false)
    })
    return () => controller.abort()
  }, [startDate, endDate])

  const width = 640
  const height = 80
  const pad = { top: 8, right: 46, bottom: 22, left: 38 }
  const values = points.map((point) => point.value)
  const sortedValues = [...values].sort((left, right) => left - right)
  const quantile = (probability: number) => sortedValues[Math.floor((sortedValues.length - 1) * probability)]
  const p10 = quantile(0.1)
  const p90 = quantile(0.9)
  const rawMin = Math.min(...values)
  const rawMax = Math.max(...values)
  const range = Math.max(rawMax - rawMin, Math.abs(rawMax) * 0.08, 1)
  const min = rawMin - range * 0.08
  const max = rawMax + range * 0.08
  const domainStart = dates[0] ?? startDate
  const domainEnd = dates.at(-1) ?? endDate
  const domainStartTime = Date.parse(`${domainStart}T00:00:00`)
  const domainDuration = Math.max(Date.parse(`${domainEnd}T00:00:00`) - domainStartTime, 1)
  const x = (date: string) => pad.left + ((Date.parse(`${date}T00:00:00`) - domainStartTime) / domainDuration) * (width - pad.left - pad.right)
  const y = (value: number) => pad.top + ((max - value) / (max - min)) * (height - pad.top - pad.bottom)
  const line = points.map((point) => `${x(point.date)},${y(point.value)}`).join(' ')
  const ticks = monthlyTicks(domainStart, domainEnd)
  const latest = points.at(-1)

  return <section className="index-trend-sentiment" aria-label="市场情绪指数历史">
    <div className="index-trend-sentiment-heading"><span>市场情绪指数</span><MarketSentimentSummary point={latest ?? null} loading={loading} error={Boolean(error)} /></div>
    {loading ? <div className="index-trend-sentiment-state">正在加载情绪历史...</div> : error ? <div className="index-trend-sentiment-state is-error" role="alert">{error}</div> : points.length ? <svg className="index-trend-sentiment-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="市场情绪 score 历史趋势">
      {[0.25, 0.75].map((ratio) => <line key={ratio} x1={pad.left} x2={width - pad.right} y1={pad.top + ratio * (height - pad.top - pad.bottom)} y2={pad.top + ratio * (height - pad.top - pad.bottom)} className="index-trend-grid" />)}
      {[['P90', p90, '#e56b55'], ['P10', p10, '#39a98b']].map(([name, value, color]) => <g key={name as string}><line x1={pad.left} x2={width - pad.right} y1={y(value as number)} y2={y(value as number)} stroke={color as string} className="index-trend-reference" /><text x={width - pad.right + 7} y={y(value as number) + 4} fill={color as string} className="index-trend-reference-label">{name as string}</text></g>)}
      {ticks.map(({ date, label }) => <g key={date}><line x1={x(date)} x2={x(date)} y1={pad.top} y2={height - pad.bottom} className="index-trend-month-grid" />{label && <text x={x(date)} y={height - 13} textAnchor="middle" className="index-trend-axis-label">{label}</text>}</g>)}
      <polyline points={line} fill="none" stroke="#16a34a" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg> : <div className="index-trend-sentiment-state">所选区间暂无情绪历史数据</div>}
  </section>
}

function sentimentBand(score: number) {
  if (score < 30) return { code: 'PANIC', label: '恐慌', meaning: '显著抛压' }
  if (score < 45) return { code: 'CAUTIOUS', label: '谨慎', meaning: '偏弱' }
  if (score <= 55) return { code: 'NEUTRAL', label: '中性', meaning: '多空均衡' }
  if (score < 70) return { code: 'POSITIVE', label: '偏乐观', meaning: '趋势偏强' }
  return { code: 'EUPHORIC', label: '亢奋', meaning: '追涨风险较高' }
}

function MarketSentimentSummary({ point, loading, error }: { point: IndexTrendPoint | null; loading: boolean; error: boolean }) {
  const score = point?.value != null && Number.isFinite(point.value) ? point.value : null
  const band = score == null ? null : sentimentBand(score)
  const status = loading ? '正在获取情绪摘要' : error ? '情绪摘要加载失败' : band ? `${band.code} · ${band.label} · ${band.meaning}` : '情绪数据暂无'
  return <div className={`index-trend-market-sentiment ${band?.code.toLowerCase() ?? ''}`} aria-label="指数情绪摘要">
    <div className="index-trend-market-sentiment-value"><span>指数情绪</span><strong>{score == null ? '--' : score.toFixed(1)}</strong></div>
    <small>{status}{point?.date ? ` · 截至 ${point.date}` : ''}</small>
  </div>
}

function SummaryStrip({ summary, metric, title }: { summary: Summary; metric: Metric; title: string }) {
  return <div className="index-trend-summary" aria-label={`${title}摘要`}><span><b>{title}</b> {metricLabels[metric]} 最新值 <strong>{formatValue(summary.current, metric)}</strong></span><span>日期 <strong>{summary.date}</strong></span><span><em>当前分位</em> <strong>{summary.percentile.toFixed(1)}%</strong></span><span>P10 <strong>{formatValue(summary.p10, metric)}</strong></span><span>P50 <strong>{formatValue(summary.p50, metric)}</strong></span><span>P90 <strong>{formatValue(summary.p90, metric)}</strong></span></div>
}

export function IndexTrendModal({ onClose }: { onClose: () => void }) {
  const [metric, setMetric] = useState<Metric>('PE')
  const [windowKey, setWindowKey] = useState<WindowKey>('60D')
  const [target, setTarget] = useState<TrendTarget>('composite')
  const [compositePayload, setCompositePayload] = useState<IndexTrendPayload | null>(null)
  const [shanghaiPayload, setShanghaiPayload] = useState<IndexTrendPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const closeButtonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    closeButtonRef.current?.focus()
    function handleKeyDown(event: KeyboardEvent) { if (event.key === 'Escape') onClose() }
    document.addEventListener('keydown', handleKeyDown)
    document.body.classList.add('index-trend-modal-open')
    return () => { document.removeEventListener('keydown', handleKeyDown); document.body.classList.remove('index-trend-modal-open') }
  }, [onClose])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')
    Promise.all([
      fetchCompositeTrend(metric, windowKey, controller.signal),
      fetchShanghaiTrend(metric, windowKey, controller.signal),
    ]).then(([composite, shanghai]) => {
      setCompositePayload(composite)
      setShanghaiPayload(shanghai)
    }).catch((requestError: unknown) => {
      if (!controller.signal.aborted) setError(requestError instanceof Error ? requestError.message : '指数趋势数据加载失败，请稍后重试。')
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false)
    })
    return () => controller.abort()
  }, [metric, windowKey])

  const compositeSummary = compositePayload ? toSummary(compositePayload) : null
  const shanghaiSummary = shanghaiPayload ? toSummary(shanghaiPayload) : null

  return <div className="index-trend-modal-layer" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}><section className="index-trend-modal" role="dialog" aria-modal="true" aria-labelledby="index-trend-title">
    <header className="index-trend-modal-header"><div><p className="index-trend-kicker">MARKET PULSE / VALUATION</p><h2 id="index-trend-title">指数趋势</h2></div><button ref={closeButtonRef} type="button" className="index-trend-close" onClick={onClose} aria-label="关闭指数趋势">×</button></header>
    <div className="index-trend-toolbar"><div className="index-trend-control"><span>数据对象</span><div className="index-trend-segmented" role="tablist" aria-label="数据对象"><button type="button" className={target === 'composite' ? 'active' : ''} onClick={() => setTarget('composite')}>综合指数</button><button type="button" className={target === 'shanghai' ? 'active' : ''} onClick={() => setTarget('shanghai')}>上证分位</button></div></div><div className="index-trend-control"><span>指标</span><div className="index-trend-segmented" role="tablist" aria-label="估值指标">{(['PE', 'PETTM', 'PB'] as Metric[]).map((item) => <button key={item} type="button" className={metric === item ? 'active' : ''} onClick={() => setMetric(item)}>{item}</button>)}</div></div><div className="index-trend-control"><span>窗口</span><div className="index-trend-segmented" role="tablist" aria-label="时间窗口">{windowLabels.map(([value, label]) => <button key={value} type="button" className={windowKey === value ? 'active' : ''} onClick={() => setWindowKey(value)}>{label}</button>)}</div></div></div>
    {error ? <div className="index-trend-data-state is-error">{error}</div> : <>
      <div className="index-trend-summary-slot">{compositeSummary && shanghaiSummary && <SummaryStrip summary={target === 'composite' ? compositeSummary : shanghaiSummary} metric={metric} title={target === 'composite' ? '综合指数' : '上证综指'} />}</div>
      <div className="index-trend-panels">
        {target === 'composite' ? <article className="index-trend-panel">
          <div className="index-trend-panel-heading"><div><span className="index-trend-panel-tag">OVERALL · 7 INDICES</span><h3>综合指数</h3><p>7 指数共同有效日期的 {metric} 估值序列</p></div><div className="index-trend-panel-value">{compositeSummary && <strong>{formatValue(compositeSummary.current, metric)}</strong>}</div></div>
          {compositePayload?.points.length && compositeSummary ? <TrendChart values={compositePayload.points.map((point) => point.value)} dates={compositePayload.points.map((point) => point.date)} summary={compositeSummary} metric={metric} label="综合指数" color="#3268d6" loading={loading} /> : <div className="index-trend-chart-loading is-empty">正在加载...</div>}
        </article> : <article className="index-trend-panel">
          <div className="index-trend-panel-heading"><div><span className="index-trend-panel-tag">000001.SH · SHANGHAI</span><h3>上证综指</h3><p>000001.SH 日频 {metric} 基本面趋势</p></div><div className="index-trend-panel-value">{shanghaiSummary && <strong>{formatValue(shanghaiSummary.current, metric)}</strong>}</div></div>
          {shanghaiPayload?.points.length && shanghaiSummary ? <TrendChart values={shanghaiPayload.points.map((point) => point.value)} dates={shanghaiPayload.points.map((point) => point.date)} summary={shanghaiSummary} metric={metric} label="上证综指" color="#168c83" loading={loading} /> : <div className="index-trend-chart-loading is-empty">正在加载...</div>}
        </article>}
      </div>
    </>}
    <footer className="index-trend-modal-footer"><span>分位线：P10 低估参考 · P50 中位参考 · P90 高估参考</span><span>数据截至 {new Date().toISOString().slice(0, 10)} · 定时更新</span></footer>
  </section></div>
}

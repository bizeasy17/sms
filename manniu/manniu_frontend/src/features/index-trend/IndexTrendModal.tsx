import { useEffect, useRef, useState } from 'react'
import { fetchCompositeTrend, fetchShanghaiTrend, type IndexTrendPayload } from './indexTrendApi'
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
  const x = (index: number) => pad.left + (index / Math.max(values.length - 1, 1)) * (width - pad.left - pad.right)
  const y = (value: number) => pad.top + ((max - value) / Math.max(max - min, 1)) * (height - pad.top - pad.bottom)
  const points = values.map((value, index) => `${x(index)},${y(value)}`).join(' ')
  const gridValues = [min + (max - min) * 0.15, min + (max - min) * 0.5, min + (max - min) * 0.85]

  return <div className="index-trend-chart-wrap">
    {loading && <div className="index-trend-chart-loading">正在加载...</div>}
    <svg className="index-trend-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${label}${metric}历史趋势`}>
      {gridValues.map((value) => <line key={value} x1={pad.left} x2={width - pad.right} y1={y(value)} y2={y(value)} className="index-trend-grid" />)}
      {[['P90', summary.p90, '#e56b55'], ['P50', summary.p50, '#e6a33d'], ['P10', summary.p10, '#39a98b']].map(([name, value, lineColor]) => <g key={name as string}><line x1={pad.left} x2={width - pad.right} y1={y(value as number)} y2={y(value as number)} stroke={lineColor as string} className="index-trend-reference" /><text x={width - pad.right + 7} y={y(value as number) + 4} fill={lineColor as string} className="index-trend-reference-label">{name as string}</text></g>)}
      <polyline points={points} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <text x={pad.left} y={height - 8} className="index-trend-axis-label">{dates[0]}</text>
      <text x={width - pad.right} y={height - 8} textAnchor="end" className="index-trend-axis-label">{dates.at(-1)}</text>
    </svg>
  </div>
}

function SummaryStrip({ summary, metric, title }: { summary: Summary; metric: Metric; title: string }) {
  return <div className="index-trend-summary" aria-label={`${title}摘要`}><span><b>{title}</b> {metricLabels[metric]} 最新值 <strong>{formatValue(summary.current, metric)}</strong></span><span>日期 <strong>{summary.date}</strong></span><span><em>1Y 分位</em> <strong>{summary.percentile.toFixed(1)}%</strong></span><span>P10 <strong>{formatValue(summary.p10, metric)}</strong></span><span>P50 <strong>{formatValue(summary.p50, metric)}</strong></span><span>P90 <strong>{formatValue(summary.p90, metric)}</strong></span></div>
}

export function IndexTrendModal({ onClose }: { onClose: () => void }) {
  const [metric, setMetric] = useState<Metric>('PE')
  const [windowKey, setWindowKey] = useState<WindowKey>('1Y')
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
    {error ? <div className="index-trend-data-state is-error">{error}</div> : <><div className="index-trend-summary-slot">{compositeSummary && shanghaiSummary && <SummaryStrip summary={target === 'composite' ? compositeSummary : shanghaiSummary} metric={metric} title={target === 'composite' ? '综合指数' : '上证综指'} />}</div><div className="index-trend-panels">{target === 'composite' ? <article className="index-trend-panel"><div className="index-trend-panel-heading"><div><span className="index-trend-panel-tag">OVERALL · 7 INDICES</span><h3>综合指数</h3><p>7 指数共同有效日期的 {metric} 估值序列</p></div>{compositeSummary && <strong>{formatValue(compositeSummary.current, metric)}</strong>}</div>{compositePayload?.points.length && compositeSummary ? <TrendChart values={compositePayload.points.map((point) => point.value)} dates={compositePayload.points.map((point) => point.date)} summary={compositeSummary} metric={metric} label="综合指数" color="#3268d6" loading={loading} /> : <div className="index-trend-chart-loading is-empty">正在加载...</div>}<div className="index-trend-panel-foot"><span>数据完整 · 7/7 指数参与</span>{compositeSummary && <span>当前分位 {compositeSummary.percentile.toFixed(1)}%</span>}</div></article> : <article className="index-trend-panel"><div className="index-trend-panel-heading"><div><span className="index-trend-panel-tag">000001.SH · SHANGHAI</span><h3>上证综指</h3><p>000001.SH 日频 {metric} 基本面趋势</p></div>{shanghaiSummary && <strong>{formatValue(shanghaiSummary.current, metric)}</strong>}</div>{shanghaiPayload?.points.length && shanghaiSummary ? <TrendChart values={shanghaiPayload.points.map((point) => point.value)} dates={shanghaiPayload.points.map((point) => point.date)} summary={shanghaiSummary} metric={metric} label="上证综指" color="#168c83" loading={loading} /> : <div className="index-trend-chart-loading is-empty">正在加载...</div>}<div className="index-trend-panel-foot"><span>数据完整 · 交易日序列</span>{shanghaiSummary && <span>当前分位 {shanghaiSummary.percentile.toFixed(1)}%</span>}</div></article>}</div></>}
    <footer className="index-trend-modal-footer"><span>分位线：P10 低估参考 · P50 中位参考 · P90 高估参考</span><span>数据截至 {new Date().toISOString().slice(0, 10)} · 定时更新</span></footer>
  </section></div>
}

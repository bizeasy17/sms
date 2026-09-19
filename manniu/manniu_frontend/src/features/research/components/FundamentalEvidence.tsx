import { ModuleStateNotice, type ModuleState } from './ModuleStateNotice'
import type { FinancialMetric } from '../types'

const metricDefinitions: Array<[string, string, 'amount' | 'rate']> = [
	['revenue', '营收', 'amount'], ['gross_margin', '毛利率', 'rate'], ['roe', 'ROE', 'rate'],
	['operating_cash_flow', '经营现金流', 'amount'], ['net_profit', '净利润', 'amount'], ['ebit', 'EBIT', 'amount'],
	['net_margin', '净利率', 'rate'], ['debt_to_assets', '负债率', 'rate'],
]

function formatValue(metric: FinancialMetric, kind: 'amount' | 'rate') {
	if (!metric.available || metric.value == null) return '暂无数据'
	return kind === 'amount' ? `¥${(metric.value / 100000000).toFixed(1)}亿` : `${metric.value.toFixed(1)}%`
}

function formatYoy(metric: FinancialMetric) {
	if (!metric.available || metric.yoy == null) return '同比暂无数据'
	return metric.yoyUnit === 'ratio' ? `${metric.yoy >= 0 ? '+' : ''}${(metric.yoy * 100).toFixed(1)}% 同比` : `${metric.yoy >= 0 ? '+' : ''}${metric.yoy.toFixed(1)}pp 同比`
}

export function FundamentalEvidence({ metrics, state = 'ready', onRetry }: { metrics: Record<string, FinancialMetric> | null; state?: ModuleState; onRetry?: () => void }) {
	const period = Object.values(metrics ?? {}).find((metric) => metric.period)?.period
	return <section className="section"><div className="section-heading"><div><p className="kicker">03 / FUNDAMENTALS</p><h2>基本面证据</h2></div><span className="section-note">最新报告期 · {period ?? '暂无'}</span></div>{state === 'ready' && metrics ? <div className="metric-grid">{metricDefinitions.map(([key, label, kind]) => { const metric = metrics[key] ?? { key, value: null, yoy: null, yoyUnit: 'ratio', rolling12: null, rolling12Unit: '', period: null, sourceDataset: '', available: false } as FinancialMetric; const yoyClass = metric.available && metric.yoy != null ? metric.yoy > 0 ? 'positive' : metric.yoy < 0 ? 'negative' : 'neutral' : 'neutral'; return <div className="metric-cell" key={key}><span>{label}</span><strong>{formatValue(metric, kind)}</strong><em className={yoyClass}>{formatYoy(metric)}</em></div>})}</div> : <ModuleStateNotice state={state === 'ready' ? 'empty' : state} label="基本面证据" onRetry={onRetry} />}</section>
}
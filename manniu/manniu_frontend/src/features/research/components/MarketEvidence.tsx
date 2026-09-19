import { useEffect, useMemo, useState } from 'react'
import { fetchMarketEvidence } from '../services/researchApi'
import type { MarketEvidence as MarketEvidenceData } from '../types'
import { ModuleStateNotice, type ModuleState } from './ModuleStateNotice'

type Props = { state?: ModuleState; tsCode?: string }
const chart = { width: 740, height: 220, left: 38, right: 38, top: 16, bottom: 32 }

function percentile(values: number[], ratio: number) {
	if (!values.length) return null
	const sorted = [...values].sort((left, right) => left - right)
	const index = (sorted.length - 1) * ratio
	const lower = Math.floor(index)
	const upper = Math.ceil(index)
	return sorted[lower] + (sorted[upper] - sorted[lower]) * (index - lower)
}

function range(values: number[]) {
	const min = Math.min(...values)
	const max = Math.max(...values)
	const padding = (max - min || Math.abs(max) * 0.04 || 1) * 0.08
	return [min - padding, max + padding]
}

function linePath(values: number[], minimum: number, maximum: number) {
	const xStart = chart.left
	const xEnd = chart.width - chart.right
	const yTop = chart.top
	const yBottom = chart.height - chart.bottom
	return values.map((value, index) => {
		const x = xStart + (xEnd - xStart) * (index / Math.max(values.length - 1, 1))
		const y = yBottom - ((value - minimum) / (maximum - minimum || 1)) * (yBottom - yTop)
		return `${index === 0 ? 'M' : 'L'}${x.toFixed(2)} ${y.toFixed(2)}`
	}).join(' ')
}

function formatNumber(value: number | null, digits = 1) {
	return value == null || !Number.isFinite(value) ? '暂无' : value.toFixed(digits)
}

function trendLabel(value: string | null) {
	return value === 'UP' ? '向上' : value === 'DOWN' ? '向下' : value === 'FLAT' ? '走平' : '暂无'
}

function EvidenceChart({ data }: { data: MarketEvidenceData }) {
	const stockValues = data.history.map((row) => row.close).filter((value): value is number => value != null)
	const industryValues = data.history.map((row) => row.industryClose).filter((value): value is number => value != null)
	const stockRange = range(stockValues)
	const industryRange = industryValues.length ? range(industryValues) : [0, 1]
	const yTop = chart.top
	const yBottom = chart.height - chart.bottom
	const stockY = (value: number) => yBottom - ((value - stockRange[0]) / (stockRange[1] - stockRange[0] || 1)) * (yBottom - yTop)
	const p10 = percentile(stockValues, 0.1)
	const p50 = percentile(stockValues, 0.5)
	const p90 = percentile(stockValues, 0.9)
	const labels = data.history.filter((_, index) => index === 0 || index === Math.floor(data.history.length / 3) || index === Math.floor(data.history.length * 2 / 3) || index === data.history.length - 1)
	const industryLabel = data.industry.name || 'SW 行业名称暂无'
	return <>
		<div className="chart-legend"><span><i className="legend-blue" /> {data.security.name}</span><span><i className="legend-gray" /> {industryLabel}</span><span><i className="legend-p10" /> 10 分位</span><span><i className="legend-median" /> 50 分位</span><span><i className="legend-p90" /> 90 分位</span></div>
		<svg className="trend-chart" viewBox={`0 0 ${chart.width} ${chart.height}`} role="img" aria-label={`${data.security.name} 与 ${industryLabel} 收盘走势`}>
			<path className="grid-line" d={`M${chart.left} ${yTop + 32}H${chart.width - chart.right}M${chart.left} ${yTop + 78}H${chart.width - chart.right}M${chart.left} ${yTop + 124}H${chart.width - chart.right}M${chart.left} ${yBottom}H${chart.width - chart.right}`} />
			{p90 != null && <path className="percentile-line percentile-p90" d={`M${chart.left} ${stockY(p90)}H${chart.width - chart.right}`} />}
			{p50 != null && <path className="percentile-line percentile-median" d={`M${chart.left} ${stockY(p50)}H${chart.width - chart.right}`} />}
			{p10 != null && <path className="percentile-line percentile-p10" d={`M${chart.left} ${stockY(p10)}H${chart.width - chart.right}`} />}
			{industryValues.length > 0 && <path className="industry-line" d={linePath(industryValues, industryRange[0], industryRange[1])} />}
			{stockValues.length > 0 && <path className="price-line" d={linePath(stockValues, stockRange[0], stockRange[1])} />}
			<text className="chart-axis-label" x="4" y={yTop + 5}>{formatNumber(stockRange[1])}</text><text className="chart-axis-label" x="4" y={yBottom}>{formatNumber(stockRange[0])}</text>
			<text className="chart-axis-label chart-axis-right" x={chart.width - 4} y={yTop + 5}>{formatNumber(industryRange[1])}</text><text className="chart-axis-label chart-axis-right" x={chart.width - 4} y={yBottom}>{formatNumber(industryRange[0])}</text>
		</svg>
		<div className="chart-axis">{labels.map((row) => <span key={row.tradeDate}>{row.tradeDate.slice(5)}</span>)}</div>
	</>
}

export function MarketEvidence({ state = 'ready', tsCode }: Props) {
	const code = tsCode ?? new URLSearchParams(window.location.search).get('ts_code') ?? ''
	const [data, setData] = useState<MarketEvidenceData | null>(null)
	const [dataState, setDataState] = useState<ModuleState>(state === 'ready' ? 'loading' : state)
	const [retry, setRetry] = useState(0)
	useEffect(() => {
		if (!code || state !== 'ready') return
		const controller = new AbortController()
		setData(null); setDataState('loading')
		fetchMarketEvidence(code, 60, controller.signal).then((result) => { setData(result); setDataState(result.history.length ? 'ready' : 'empty') }).catch(() => { if (!controller.signal.aborted) setDataState('error') })
		return () => controller.abort()
	}, [code, retry, state])
	const summary = data?.summary
	const stats = useMemo(() => ({
		atr: summary?.atr14 == null ? '暂无' : formatNumber(summary.atr14, 2),
		atrPercentile: summary?.atr14Percentile60d == null ? '历史分位 暂无' : `历史分位 ${formatNumber(summary.atr14Percentile60d, 0)}%`,
		ma25: trendLabel(summary?.ma25Trend ?? null),
		ma25Relation: summary?.priceToMa25 == null ? '价格高于均线 暂无' : `价格高于均线 ${formatNumber((summary.priceToMa25 - 1) * 100)}%`,
		ma200: summary?.ma200 == null ? trendLabel(summary?.ma200Trend ?? null) : `${trendLabel(summary?.ma200Trend ?? null)} · ${formatNumber(summary.ma200)}`,
		strength: summary?.relativeStrengthVsIndustry == null ? '暂无' : `${summary.relativeStrengthVsIndustry >= 0 ? '+' : ''}${formatNumber(summary.relativeStrengthVsIndustry * 100)}%`,
	}), [summary])
	return <section className="section"><div className="section-heading"><div><p className="kicker">02 / MARKET EVIDENCE</p><h2>市场证据</h2></div><span className="section-note">近 {data?.returnedDays ?? 60} 个交易日</span></div>{dataState === 'ready' && data ? <div className="market-grid"><div><EvidenceChart data={data} /></div><div className="market-stats"><div><span>14日 ATR</span><strong>{stats.atr}</strong><em>{stats.atrPercentile}</em></div><div><span>MA25 趋势</span><strong className={summary?.ma25Trend === 'UP' ? 'positive' : ''}>{stats.ma25}</strong><em>{stats.ma25Relation}</em></div><div><span>MA200 趋势</span><strong className={summary?.ma200Trend === 'UP' ? 'positive' : ''}>{stats.ma200}</strong><em>长期趋势</em></div><div><span>相对行业强度</span><strong className={summary?.relativeStrengthVsIndustry != null && summary.relativeStrengthVsIndustry >= 0 ? 'positive' : ''}>{stats.strength}</strong><em>近 {data.returnedDays} 日</em></div></div></div> : <ModuleStateNotice state={dataState === 'ready' ? 'empty' : dataState} label="市场证据" onRetry={() => setRetry((value) => value + 1)} />}</section>
}
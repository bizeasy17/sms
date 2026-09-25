import { useEffect, useRef, useState } from 'react'
import { fetchStockSentiment, fetchTechnicalChips, fetchTechnicalTrend } from '../services/researchApi'
import type { Stock, StockSentiment, TechnicalChip, TechnicalTrend as TechnicalTrendData } from '../types'
import { ModuleStateNotice, type ModuleState } from './ModuleStateNotice'

type Props = { stock: Stock }

type SentimentBand = { code: 'PANIC' | 'CAUTIOUS' | 'NEUTRAL' | 'POSITIVE' | 'EUPHORIC'; label: string; meaning: string }

function sentimentBand(score: number | null): SentimentBand | null {
	if (score == null || !Number.isFinite(score)) return null
	if (score < 30) return { code: 'PANIC', label: '恐慌', meaning: '显著抛压' }
	if (score < 45) return { code: 'CAUTIOUS', label: '谨慎', meaning: '偏弱' }
	if (score <= 55) return { code: 'NEUTRAL', label: '中性', meaning: '多空均衡' }
	if (score < 70) return { code: 'POSITIVE', label: '偏乐观', meaning: '趋势偏强' }
	return { code: 'EUPHORIC', label: '亢奋', meaning: '追涨风险较高' }
}

function percentile(values: number[], ratio: number) {
	const sorted = [...values].sort((left, right) => left - right)
	const position = (sorted.length - 1) * ratio
	const lower = Math.floor(position)
	const upper = Math.ceil(position)
	return sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower)
}

function PriceChart({ bars }: { bars: TechnicalTrendData['series'] }) {
	const [hoveredIndex, setHoveredIndex] = useState<number | null>(null)
	const sourceCandles = bars.filter((bar): bar is TechnicalTrendData['series'][number] & { open: number; high: number; low: number; close: number; volume: number } => bar.open != null && bar.high != null && bar.low != null && bar.close != null && bar.volume != null)
	const candles = sourceCandles
	const width = 720
	const plotLeft = 42
	const plotRight = 674
	const priceTop = 18
	const priceBottom = 180
	const volumeTop = 218
	const volumeBottom = 268
	const priceMax = Math.max(...candles.map((candle) => candle.high))
	const priceMin = Math.min(...candles.map((candle) => candle.low))
	const pricePadding = Math.max((priceMax - priceMin) * 0.08, 0.1)
	const volumeMax = Math.max(...candles.map((candle) => candle.volume), 1)
	const closeValues = candles.map((candle) => candle.close)
	const percentiles = [
		{ ratio: 0.1, className: 'percentile-p10', label: 'P10' },
		{ ratio: 0.5, className: 'percentile-median', label: 'P50' },
		{ ratio: 0.9, className: 'percentile-p90', label: 'P90' },
	].map((item) => ({ ...item, value: percentile(closeValues, item.ratio) }))
	const step = (plotRight - plotLeft) / Math.max(candles.length - 1, 1)
	const candleWidth = Math.max(2, Math.min(12, step * 0.62))
	const x = (index: number) => plotLeft + index * step
	const priceY = (price: number) => priceBottom - ((price - (priceMin - pricePadding)) / (priceMax - priceMin + pricePadding * 2)) * (priceBottom - priceTop)
	const volumeY = (volume: number) => volumeBottom - (volume / volumeMax) * (volumeBottom - volumeTop)
	const ma = candles.filter((candle) => candle.ma25 != null).map((candle) => ({ x: x(candles.indexOf(candle)), y: priceY(candle.ma25 as number) }))
	const ma200 = candles.filter((candle) => candle.ma200 != null).map((candle) => ({ x: x(candles.indexOf(candle)), y: priceY(candle.ma200 as number) }))
	const maPath = ma.map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x} ${point.y}`).join(' ')
	const ma200Path = ma200.map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x} ${point.y}`).join(' ')
	const hoveredCandle = hoveredIndex == null ? null : candles[hoveredIndex]
	const tooltipWidth = 152
	const tooltipHeight = 142
	const tooltipX = hoveredIndex == null ? 0 : Math.min(Math.max(plotLeft, x(hoveredIndex) - tooltipWidth / 2), width - tooltipWidth - 6)
	const tooltipY = hoveredIndex == null ? 0 : x(hoveredIndex) > width / 2 ? 8 : 8
	const formatTooltipValue = (value: number | null | undefined, digits = 2) => value == null ? '--' : value.toFixed(digits)
	const changePercent = hoveredCandle?.open ? (hoveredCandle.close - hoveredCandle.open) / hoveredCandle.open * 100 : null
	return <svg className="technical-price-chart" viewBox={`0 0 ${width} 285`} role="img" aria-label="价格、均线与成交量技术图表">
		{[priceTop, priceTop + 54, priceTop + 108, priceBottom, volumeTop, volumeTop + 25, volumeBottom].map((line) => <path key={line} className="technical-grid-line" d={`M${plotLeft} ${line}H${plotRight}`} />)}
		{percentiles.map((item) => <path key={item.label} className={`percentile-line ${item.className}`} d={`M${plotLeft} ${priceY(item.value)}H${plotRight}`} />)}
		<path className="technical-ma-line" d={maPath} />
		<path className="technical-ma200-line" d={ma200Path} />
		{candles.map((candle, index) => {
			const candleX = x(index)
			const rising = candle.close >= candle.open
			const top = priceY(Math.max(candle.open, candle.close))
			const bodyHeight = Math.max(2, Math.abs(priceY(candle.open) - priceY(candle.close)))
			return <g key={candleX} className={rising ? 'technical-candle rising' : 'technical-candle falling'} onMouseEnter={() => setHoveredIndex(index)} onMouseLeave={() => setHoveredIndex(null)}><path d={`M${candleX} ${priceY(candle.high)}V${priceY(candle.low)}`} /><rect x={candleX - candleWidth / 2} y={top} width={candleWidth} height={bodyHeight} /><rect className="technical-volume" x={candleX - candleWidth / 2} y={volumeY(candle.volume)} width={candleWidth} height={volumeBottom - volumeY(candle.volume)} /></g>
		})}
		{hoveredCandle && hoveredIndex != null && <g className="technical-tooltip" pointerEvents="none">
			<path className="technical-hover-line" d={`M${x(hoveredIndex)} ${priceTop}V${volumeBottom}`} />
			<rect className="technical-tooltip-box" x={tooltipX} y={tooltipY} width={tooltipWidth} height={tooltipHeight} rx="2" />
			<text className="technical-tooltip-title" x={tooltipX + 8} y={tooltipY + 16}>{hoveredCandle.tradeDate}</text>
			<text x={tooltipX + 8} y={tooltipY + 34}>开盘 {formatTooltipValue(hoveredCandle.open)}</text>
			<text x={tooltipX + 8} y={tooltipY + 49}>最高 {formatTooltipValue(hoveredCandle.high)}</text>
			<text x={tooltipX + 8} y={tooltipY + 64}>最低 {formatTooltipValue(hoveredCandle.low)}</text>
			<text x={tooltipX + 8} y={tooltipY + 79}>收盘 {formatTooltipValue(hoveredCandle.close)}</text>
			<text x={tooltipX + 8} y={tooltipY + 94}>涨跌 {changePercent == null ? '--' : `${changePercent >= 0 ? '+' : ''}${changePercent.toFixed(2)}%`}</text>
			<text x={tooltipX + 8} y={tooltipY + 109}>成交量 {formatTooltipValue(hoveredCandle.volume, 0)}</text>
			<text x={tooltipX + 8} y={tooltipY + 124}>MA25 {formatTooltipValue(hoveredCandle.ma25)}</text>
			<text x={tooltipX + 8} y={tooltipY + 139}>MA200 {formatTooltipValue(hoveredCandle.ma200)}</text>
		</g>}
		{[priceMax, priceMax - (priceMax - priceMin) / 3, priceMax - (priceMax - priceMin) * 2 / 3, priceMin].map((value) => <text key={value} className="technical-axis-label chart-axis-right" x="714" y={priceY(value) + 4}>{value.toFixed(2)}</text>)}
		{[volumeMax, volumeMax / 2, 0].map((value) => <text key={value} className="technical-axis-label" x="2" y={volumeY(value) + 4}>{value >= 10000 ? `${(value / 10000).toFixed(1)}万` : Math.round(value).toString()}</text>)}
		{percentiles.map((item) => <text key={`${item.label}-axis`} className="technical-axis-label chart-axis-right" x="714" y={priceY(item.value) + 4}>{item.label} {item.value.toFixed(2)}</text>)}
		<text className="technical-volume-label" x={plotLeft} y="282">成交量</text>
	</svg>
}

function ChipPanel({ chips, currentPrice, tradeDate }: { chips: TechnicalChip[]; currentPrice: number | null; tradeDate: string }) {
	const merged = Array.from(chips.reduce((groups, chip) => groups.set(chip.price, (groups.get(chip.price) ?? 0) + chip.percent), new Map<number, number>())).map(([price, percent]) => ({ price, percent })).sort((left, right) => right.price - left.price)
	const totalPercent = merged.reduce((total, chip) => total + chip.percent, 0)
	const maximum = Math.max(...merged.map((chip) => chip.percent), 1)
	const winningRate = totalPercent > 0 && currentPrice != null ? merged.filter((chip) => chip.price <= currentPrice).reduce((total, chip) => total + chip.percent, 0) / totalPercent * 100 : null
	const topCount = Math.max(1, Math.ceil(merged.length * 0.1))
	const concentration = totalPercent > 0 ? merged.slice().sort((left, right) => right.percent - left.percent).slice(0, topCount).reduce((total, chip) => total + chip.percent, 0) / totalPercent * 100 : null
	const labelStep = Math.max(1, Math.ceil(merged.length / 10))
	return <div className="chip-panel"><div className="chip-panel-heading"><div><span>筹码分布 · {tradeDate}</span><strong>当前价 {currentPrice == null ? '暂无' : currentPrice.toFixed(2)}</strong></div><div className="chip-panel-metrics"><span>获胜率 <strong>{winningRate == null ? '暂无' : `${winningRate.toFixed(2)}%`}</strong></span><span>筹码集中率 <strong>{concentration == null ? '暂无' : `${concentration.toFixed(2)}%`}</strong></span></div></div><div className="chip-bars">{merged.map((chip, index) => { const showLabel = index % labelStep === 0 || index === merged.length - 1; const normalizedTop = merged.length === 1 ? 0.5 : index / (merged.length - 1); const top = 7 + normalizedTop * 86; return <div className="chip-row" key={chip.price} style={{ top: `${top}%` }}><span>{showLabel ? chip.price.toFixed(2) : ''}</span><i className={currentPrice != null && chip.price <= currentPrice ? 'below-current' : 'above-current'} style={{ width: `${Math.max(4, chip.percent / maximum * 100)}%` }} /><em>{showLabel ? `${chip.percent.toFixed(2)}%` : ''}</em></div> })}</div><div className="chip-foot"><span>真实价格档位</span><strong>{merged.length}</strong></div></div>
}

function ChipPanelNotice({ state, onRetry }: { state: Exclude<ModuleState, 'ready'>; onRetry?: () => void }) {
	return <div className="chip-panel"><div className="chip-panel-heading"><div><span>筹码分布</span><strong>暂无</strong></div><small>CYQ_CHIPS · 后台数据</small></div><ModuleStateNotice state={state} label="筹码分布" onRetry={onRetry} /></div>
}

export function TechnicalTrend({ stock }: Props) {
	const [period, setPeriod] = useState('60D')
	const [trend, setTrend] = useState<TechnicalTrendData | null>(null)
	const [barsStockCode, setBarsStockCode] = useState('')
	const [barsState, setBarsState] = useState<ModuleState>('loading')
	const [retry, setRetry] = useState(0)
	const [chips, setChips] = useState<TechnicalChip[]>([])
	const [chipsState, setChipsState] = useState<ModuleState>('loading')
	const [chipsRetry, setChipsRetry] = useState(0)
	const [sentiment, setSentiment] = useState<StockSentiment | null>(null)
	const [sentimentState, setSentimentState] = useState<ModuleState>('loading')
	const [sentimentRetry, setSentimentRetry] = useState(0)
	const chipsLoadedStock = useRef('')
	const requestedDays = Number.parseInt(period, 10)
	useEffect(() => {
		const controller = new AbortController()
		setTrend(null)
		setBarsState('loading')
		setBarsStockCode('')
		if (chipsLoadedStock.current !== stock.code) {
			setChips([])
			setChipsState('loading')
		}
		fetchTechnicalTrend(stock.code, requestedDays, controller.signal).then((result) => {
			const usableBars = result.series.filter((bar) => bar.open != null && bar.high != null && bar.low != null && bar.close != null && bar.volume != null)
			setTrend({ ...result, series: usableBars })
			setBarsStockCode(stock.code)
			setBarsState(usableBars.length ? 'ready' : 'empty')
		}).catch(() => {
			if (!controller.signal.aborted) setBarsState('error')
		})
		return () => controller.abort()
	}, [requestedDays, retry, stock.code])
	useEffect(() => {
		const controller = new AbortController()
		setSentiment(null)
		setSentimentState('loading')
		fetchStockSentiment(stock.code, controller.signal).then((result) => {
			setSentiment(result)
			setSentimentState('ready')
		}).catch(() => {
			if (!controller.signal.aborted) setSentimentState('error')
		})
		return () => controller.abort()
	}, [sentimentRetry, stock.code])
	useEffect(() => {
		if (barsState !== 'ready' || barsStockCode !== stock.code || !trend?.series.length) return
		if (chipsLoadedStock.current === stock.code && chipsRetry === 0) return
		const controller = new AbortController()
		const startDate = trend.series[0].tradeDate
		const endDate = trend.series[trend.series.length - 1].tradeDate
		setChips([])
		setChipsState('loading')
		fetchTechnicalChips(stock.code, startDate, endDate, controller.signal).then((result) => {
			const latestDate = result.reduce((latest, chip) => chip.tradeDate > latest ? chip.tradeDate : latest, '')
			setChips(result.filter((chip) => chip.tradeDate === latestDate))
			setChipsState(latestDate ? 'ready' : 'empty')
			chipsLoadedStock.current = stock.code
			setChipsRetry(0)
		}).catch(() => {
			if (!controller.signal.aborted) setChipsState('error')
		})
		return () => controller.abort()
	}, [trend, barsStockCode, barsState, chipsRetry, stock.code])
	const bars = trend?.series ?? []
	const latestBar = bars[bars.length - 1]
	const sentimentScore = sentiment?.score ?? null
	const sentimentBandValue = sentimentBand(sentimentScore)
	const formatMetric = (value: number | null | undefined, digits = 2) => value == null ? '暂无' : value.toFixed(digits)
	const trendLabel = trend?.summary.trend === 'UP' ? '上行' : trend?.summary.trend === 'DOWN' ? '下行' : trend?.summary.trend === 'FLAT' ? '横盘' : '暂无'
	const directionLabel = (direction: string | null | undefined) => direction === 'UP' ? '偏强' : direction === 'DOWN' ? '偏弱' : direction === 'FLAT' ? '平稳' : '暂无'
	return <div className="technical-trend">
		<section className="technical-summary section">
			<div><p className="kicker">02 / TECHNICAL TREND</p><h2>技术趋势</h2><p className="technical-context">{stock.name} · {stock.code} · 数据状态：{trend?.summary.data_status ?? '加载中'}</p></div>
			<div className="technical-summary-metrics"><div><span>趋势状态</span><strong className={trend?.summary.trend === 'DOWN' ? 'negative' : 'positive'}>{trendLabel}</strong></div><div><span>趋势评分</span><strong>{trend?.summary.trend_score ?? '暂无'}</strong></div><div><span>波动状态</span><strong>{trend?.summary.volatility_status ?? '暂无'}</strong></div></div>
		</section>
		<section className="section technical-workspace">
			<div className="section-heading"><div><p className="kicker">PRICE &amp; CHIPS</p><h2>价格趋势与筹码</h2></div><div className="technical-periods" role="group" aria-label="技术趋势周期">{['60D', '120D', '250D'].map((value) => <button className={period === value ? 'active' : ''} key={value} onClick={() => setPeriod(value)}>{value}</button>)}</div></div>
			<div className="technical-chart-layout"><div className="technical-chart-panel"><div className="technical-legend"><span><i className="legend-candle-up" />上涨</span><span><i className="legend-candle-down" />下跌</span><span><i className="legend-ma" />MA25</span><span><i className="legend-ma200" />MA200</span><span><i className="legend-percentile percentile-p10" />P10</span><span><i className="legend-percentile percentile-median" />P50</span><span><i className="legend-percentile percentile-p90" />P90</span></div>{barsState === 'error' ? <ModuleStateNotice state="error" label="价格趋势" detail="新股上市时间较短或历史行情不足，后台暂时无法计算技术趋势。" onRetry={() => setRetry((value) => value + 1)} /> : barsState === 'empty' ? <ModuleStateNotice state="empty" label="价格趋势" detail="新股或历史行情不足时，尚未积累足够交易日计算技术指标。" /> : barsState === 'loading' ? <ModuleStateNotice state="loading" label="价格趋势" /> : <PriceChart bars={bars} />}<div className="technical-sentiment"><div><span>情绪指数 · stock_sentiment_v2{sentimentBandValue ? ` · ${sentimentBandValue.label}` : ''}</span><strong>{sentimentState === 'loading' ? '加载中' : sentimentScore == null ? '暂无' : sentimentScore.toFixed(1)}</strong></div><div className="sentiment-track"><i style={{ width: `${sentimentScore == null ? 0 : Math.min(100, Math.max(0, sentimentScore))}%` }} /></div>{sentimentState === 'error' ? <small>情绪数据加载失败 <button type="button" onClick={() => setSentimentRetry((value) => value + 1)}>重试</button></small> : <small>{sentiment?.status === 'WARMING_UP' || sentiment?.status === 'INSUFFICIENT_DATA' || sentiment?.status === 'STALE' ? `情绪数据${sentiment.status === 'WARMING_UP' ? '预热中' : '暂不可用'} · 截至 ${sentiment.sourceTradeDate ?? sentiment.tradeDate}` : `${sentimentBandValue ? `${sentimentBandValue.code} · ${sentimentBandValue.meaning}` : '情绪状态暂无'} · 截至 ${sentiment?.sourceTradeDate ?? sentiment?.tradeDate ?? '暂无日期'}`}</small>}</div></div>
				{chipsState === 'error' ? <ChipPanelNotice state="error" onRetry={() => setChipsRetry((value) => value + 1)} /> : chipsState === 'empty' ? <ChipPanelNotice state="empty" /> : chipsState === 'loading' ? <ChipPanelNotice state="loading" /> : <ChipPanel chips={chips} currentPrice={latestBar?.close ?? null} tradeDate={chips[0]?.tradeDate ?? latestBar?.tradeDate ?? '暂无'} />}
			</div>
		</section>
		<div className="technical-lower-grid"><section className="section"><div className="section-heading"><div><p className="kicker">MOMENTUM</p><h2>动量指标</h2></div></div><div className="technical-indicator-list"><div><span>RSI(14)</span><strong>{formatMetric(trend?.momentum.latest.rsi14)}</strong><em className={trend?.momentum.latest.rsi14 != null && trend.momentum.latest.rsi14 >= 50 ? 'positive' : ''}>{trend?.momentum.latest.rsi14 == null ? '暂无' : directionLabel(trend.momentum.latest.rsi14 >= 50 ? 'UP' : 'DOWN')}</em></div><div><span>MACD</span><strong>{formatMetric(trend?.momentum.latest.macd_histogram, 4)}</strong><em className={trend?.momentum.latest.macd_histogram != null && trend.momentum.latest.macd_histogram >= 0 ? 'positive' : ''}>{directionLabel(trend?.momentum.latest.macd_histogram != null && trend.momentum.latest.macd_histogram >= 0 ? 'UP' : 'DOWN')}</em></div><div><span>ATR(14)</span><strong>{formatMetric(trend?.momentum.latest.atr14)}</strong><em>{trend?.summary.volatility_status ?? '暂无'}</em></div></div></section><section className="section"><div className="section-heading"><div><p className="kicker">RELATIVE STRENGTH</p><h2>行业相对强度</h2></div></div><div className="relative-strength"><div><span>个股相对行业</span><strong>{trend?.relativeStrength.relativeStrength == null ? '暂无' : `${trend.relativeStrength.relativeStrength >= 0 ? '+' : ''}${(trend.relativeStrength.relativeStrength * 100).toFixed(2)}%`}</strong></div><div><span>{trend?.relativeStrength.name ?? stock.industry ?? '所属行业'}</span><strong>{directionLabel(trend?.relativeStrength.direction)}</strong></div><div className="strength-track"><i style={{ width: `${Math.min(100, Math.max(0, 50 + (trend?.relativeStrength.relativeStrength ?? 0) * 500))}%` }} /></div><small>{trend?.relativeStrength.status === 'COMPLETE' ? '后端按共同交易日计算' : '行业数据暂无'}</small></div></section></div>
		<section className="section technical-signals"><div className="section-heading"><div><p className="kicker">TECHNICAL SIGNALS</p><h2>技术信号</h2></div><span className="section-note">基于当前周期</span></div><div className="signal-list">{trend?.signals.length ? trend.signals.map((signal) => <div key={`${signal.tradeDate}-${signal.type}`}><i className={`signal-dot ${signal.direction === 'UP' ? 'positive-dot' : signal.direction === 'DOWN' ? 'warning-dot' : 'neutral-dot'}`} /><strong>{signal.type}</strong><span>{signal.evidence} · {signal.tradeDate}</span></div>) : <div><i className="signal-dot neutral-dot" /><strong>暂无技术信号</strong><span>当前周期没有检测到已确认的技术信号</span></div>}</div></section>
	</div>
}
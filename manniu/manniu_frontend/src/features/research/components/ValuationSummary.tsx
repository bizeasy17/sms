import { ModuleStateNotice, type ModuleState } from './ModuleStateNotice'
import { predictiveStatement, ThesisStrip, traditionalStatement } from './ThesisStrip'
import type { PredictiveTier, PredictiveValuation, TraditionalValuation } from '../types'

function money(value: number | null | undefined) { return value == null ? '暂无' : `¥${value.toFixed(2)}` }

function updateDate(valuation?: TraditionalValuation) {
	const value = valuation?.asofDate ?? valuation?.sourceTradeDate
	if (!value) return '暂无更新'
	const date = new Date(`${value}T00:00:00`)
	return Number.isNaN(date.getTime()) ? value : `${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

function predictiveDate(valuation?: PredictiveValuation) {
	if (!valuation?.asofDate) return '暂无更新'
	return valuation.asofDate
}

function priceScale(values: Array<number | null | undefined>) {
	const available = values.filter((value): value is number => value != null && Number.isFinite(value))
	if (available.length < 2) return null
	const low = Math.min(...available)
	const high = Math.max(...available)
	return high > low ? { low, high } : null
}

function pricePosition(value: number | null | undefined, scale: { low: number; high: number } | null) {
	if (value == null || !scale) return 50
	return Math.max(0, Math.min(100, ((value - scale.low) / (scale.high - scale.low)) * 100))
}

function priceStyle(value: number | null | undefined, scale: { low: number; high: number } | null) {
	return { left: `clamp(8px, ${pricePosition(value, scale)}%, calc(100% - 8px))` }
}

function priceLabelLanes(values: Array<number | null | undefined>, scale: { low: number; high: number } | null) {
	const minimumGap = 16
	const placements = values.map((value, index) => ({ index, position: pricePosition(value, scale), side: 0, lane: 0 }))
	const placed: typeof placements = []
	for (const placement of [...placements].sort((left, right) => left.position - right.position)) {
		if (placed.some((other) => other.side === 0 && Math.abs(other.position - placement.position) < minimumGap)) {
			placement.side = placed.some((other) => other.side === 1 && Math.abs(other.position - placement.position) < minimumGap) ? 0 : 1
		}
		while (placed.some((other) => other.side === placement.side && other.lane === placement.lane && Math.abs(other.position - placement.position) < minimumGap)) {
			placement.lane += 1
		}
		placed.push(placement)
	}
	return placements.map((placement) => ({ side: placement.side, lane: placement.lane }))
}

function ValuationBlock({ kind, valuation, latestClose }: { kind: 'fundamental' | 'model'; valuation?: TraditionalValuation; latestClose?: number | null }) {
	const isFundamental = kind === 'fundamental'
	const methods = valuation?.methods ?? []
	const conservative = valuation?.conservativePrice ?? null
	const center = valuation?.centerPrice ?? null
	const optimistic = valuation?.optimisticPrice ?? center
	const current = latestClose ?? valuation?.currentPrice ?? null
	const scale = priceScale([conservative, center, optimistic])
	const labelPlacements = priceLabelLanes([conservative, center, optimistic], scale)
	const position = pricePosition(current, scale)
	const pointerPosition = `clamp(8px, ${position}%, calc(100% - 8px))`
	const pointerBoundary = position === 0 ? 'range-pointer-start' : position === 100 ? 'range-pointer-end' : ''
	return <div className={`fundamental-valuation-block ${isFundamental ? '' : 'model-valuation-block'}`}>
		<div className="section-heading"><div><p className="kicker">{isFundamental ? '01.1 / FUNDAMENTAL VALUATION' : '01.2 / MODEL VALUATION'}</p><h2>{isFundamental ? '价值估值摘要' : '模型估值摘要'}</h2></div><span className="section-note">{methods.length} 个模型 · 更新于 {updateDate(valuation)}</span></div>
		<ThesisStrip score={isFundamental ? valuation?.undervalueScore : null} buyCandidate={isFundamental ? valuation?.buyCandidate : null} riskLevel={isFundamental ? valuation?.riskLevel : null} statement={traditionalStatement(current, center, conservative, optimistic, methods.length)} />
		<div className="valuation-layout"><div><div className={`range-values range-values-lanes-${Math.max(...labelPlacements.map(({ lane, side }) => lane + side))} ${labelPlacements.some(({ side }) => side === 1) ? 'range-values-has-lower' : ''}`}><span className={`range-label-side-${labelPlacements[0].side} range-label-lane-${labelPlacements[0].lane}`} style={priceStyle(conservative, scale)}>保守 <strong>{money(conservative)}</strong></span><span className={`range-label-side-${labelPlacements[1].side} range-label-lane-${labelPlacements[1].lane}`} style={priceStyle(center, scale)}>中枢 <strong>{money(center)}</strong></span><span className={`range-label-side-${labelPlacements[2].side} range-label-lane-${labelPlacements[2].lane}`} style={priceStyle(optimistic, scale)}>乐观 <strong>{money(optimistic)}</strong></span></div><div className="range-bar"><span className={`range-pointer ${pointerBoundary}`} style={{ left: pointerPosition }}><i>{money(current)}</i></span></div><div className="range-labels"><span>低估</span><span>合理</span><span>高估</span></div><p className="range-caption">{current != null && scale ? <>当前价格位于综合估值区间的 <strong>{Math.round(position)}%</strong>。</> : '当前价格或估值区间暂无数据。'}</p></div><div className="valuation-methods"><div className="method-list">{methods.map((method) => <div key={method.valuationMethod}><span>{method.valuationMethod}</span><strong>{money(method.valuationPrice)}</strong><em className={method.note.startsWith('-') ? 'negative' : 'positive'}>{method.note}</em></div>)}</div></div></div>
	</div>
}

function PredictiveBlock({ valuation, latestClose }: { valuation?: PredictiveValuation; latestClose?: number | null }) {
	const conservative = valuation?.tiers.conservative.targetPrice
	const balance = valuation?.tiers.balance.targetPrice
	const aggressive = valuation?.tiers.aggressive.targetPrice
	const current = latestClose ?? null
	const scale = priceScale([conservative, balance, aggressive])
	const labelPlacements = priceLabelLanes([conservative, balance, aggressive], scale)
	const position = pricePosition(current, scale)
	const pointerPosition = `clamp(8px, ${position}%, calc(100% - 8px))`
	const pointerBoundary = position === 0 ? 'range-pointer-start' : position === 100 ? 'range-pointer-end' : ''
	const tiers: Array<[string, PredictiveTier]> = [['保守', valuation?.tiers.conservative ?? { targetPrice: null, targetPriceLow: null, targetPriceHigh: null, riskLevel: null }], ['平衡', valuation?.tiers.balance ?? { targetPrice: null, targetPriceLow: null, targetPriceHigh: null, riskLevel: null }], ['进取', valuation?.tiers.aggressive ?? { targetPrice: null, targetPriceLow: null, targetPriceHigh: null, riskLevel: null }]]
	return <div className="fundamental-valuation-block model-valuation-block"><div className="section-heading"><div><p className="kicker">01.2 / MODEL VALUATION</p><h2>模型估值摘要</h2></div><span className="section-note">预测模型 · 更新于 {predictiveDate(valuation)}</span></div><ThesisStrip action={valuation?.action} score={valuation?.signalScore} riskLevel={valuation?.riskLevel} statement={predictiveStatement(current, valuation?.targetPrice ?? balance, valuation?.targetPriceLow, valuation?.targetPriceHigh)} /><div className="valuation-layout"><div><div className={`range-values range-values-lanes-${Math.max(...labelPlacements.map(({ lane, side }) => lane + side))} ${labelPlacements.some(({ side }) => side === 1) ? 'range-values-has-lower' : ''}`}><span className={`range-label-side-${labelPlacements[0].side} range-label-lane-${labelPlacements[0].lane}`} style={priceStyle(conservative, scale)}>保守 <strong>{money(conservative)}</strong></span><span className={`range-label-side-${labelPlacements[1].side} range-label-lane-${labelPlacements[1].lane}`} style={priceStyle(balance, scale)}>平衡 <strong>{money(balance)}</strong></span><span className={`range-label-side-${labelPlacements[2].side} range-label-lane-${labelPlacements[2].lane}`} style={priceStyle(aggressive, scale)}>进取 <strong>{money(aggressive)}</strong></span></div><div className="range-bar"><span className={`range-pointer ${pointerBoundary}`} style={{ left: pointerPosition }}><i>{money(current)}</i></span></div><div className="range-labels"><span>低估</span><span>合理</span><span>高估</span></div><p className="range-caption">{current != null && scale ? <>当前价格位于模型目标区间的 <strong>{Math.round(position)}%</strong>。</> : '当前价格或模型目标区间暂无数据。'}</p></div><div className="predictive-tier-list" aria-label="三档预测估值模型">{tiers.map(([label, tier]) => <div className="predictive-tier-row" key={label}><strong>{label}</strong><span>{tier.targetPriceLow != null || tier.targetPriceHigh != null ? `${money(tier.targetPriceLow)} - ${money(tier.targetPriceHigh)}` : money(tier.targetPrice)}</span><em>{tier.riskLevel ?? '暂不可用'}</em></div>)}</div></div></div>
}

export function ValuationSummary({ valuation, predictiveValuation, latestClose, state = 'ready', predictiveState = 'ready' }: { valuation?: TraditionalValuation; predictiveValuation?: PredictiveValuation; latestClose?: number | null; state?: ModuleState; predictiveState?: ModuleState }) { return <section className="section valuation-summary-section">{state === 'ready' ? <ValuationBlock kind="fundamental" valuation={valuation} latestClose={latestClose} /> : <ModuleStateNotice state={state} label="基本面估值" />}{predictiveState === 'ready' ? <PredictiveBlock valuation={predictiveValuation} latestClose={latestClose} /> : <ModuleStateNotice state={predictiveState} label="模型估值" />}</section> }
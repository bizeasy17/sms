import { ModuleStateNotice, type ModuleState } from './ModuleStateNotice'
import { ThesisStrip } from './ThesisStrip'
import type { TraditionalValuation } from '../types'

function money(value: number | null) { return value == null ? '暂无' : `¥${value.toFixed(2)}` }

function updateDate(valuation?: TraditionalValuation) {
	const value = valuation?.asofDate ?? valuation?.sourceTradeDate
	if (!value) return '暂无更新'
	const date = new Date(`${value}T00:00:00`)
	return Number.isNaN(date.getTime()) ? value : `${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

function ValuationBlock({ kind, valuation, latestClose }: { kind: 'fundamental' | 'model'; valuation?: TraditionalValuation; latestClose?: number | null }) {
	const isFundamental = kind === 'fundamental'
	const methods = valuation?.methods ?? []
	const conservative = valuation?.conservativePrice ?? null
	const center = valuation?.centerPrice ?? null
	const optimistic = valuation?.optimisticPrice ?? center
	const current = latestClose ?? valuation?.currentPrice ?? null
	const low = conservative ?? center
	const high = optimistic ?? center
	const position = current != null && low != null && high != null && high > low ? Math.max(0, Math.min(100, ((current - low) / (high - low)) * 100)) : 50
	const pointerPosition = `clamp(8px, ${position}%, calc(100% - 8px))`
	const pointerBoundary = position === 0 ? 'range-pointer-start' : position === 100 ? 'range-pointer-end' : ''
	return <div className={`fundamental-valuation-block ${isFundamental ? '' : 'model-valuation-block'}`}>
		<div className="section-heading"><div><p className="kicker">{isFundamental ? '01.1 / FUNDAMENTAL VALUATION' : '01.2 / MODEL VALUATION'}</p><h2>{isFundamental ? '价值估值摘要' : '模型估值摘要'}</h2></div><span className="section-note">{methods.length} 个模型 · 更新于 {updateDate(valuation)}</span></div>
		<ThesisStrip score={isFundamental ? valuation?.undervalueScore : null} buyCandidate={isFundamental ? valuation?.buyCandidate : null} riskLevel={isFundamental ? valuation?.riskLevel : null} />
		<div className="valuation-layout"><div><div className="range-values"><span>保守 <strong>{money(conservative)}</strong></span><span>中枢 <strong>{money(center)}</strong></span><span>乐观 <strong>{money(optimistic)}</strong></span></div><div className="range-bar"><span className={`range-pointer ${pointerBoundary}`} style={{ left: pointerPosition }}><i>{money(current)}</i></span></div><div className="range-labels"><span>低估</span><span>合理</span><span>高估</span></div><p className="range-caption">{current != null && low != null && high != null ? <>当前价格位于综合估值区间的 <strong>{Math.round(position)}%</strong>。</> : '当前价格或估值区间暂无数据。'}</p></div><div className="valuation-methods"><div className="method-list">{methods.map((method) => <div key={method.valuationMethod}><span>{method.valuationMethod}</span><strong>{money(method.valuationPrice)}</strong><em className={method.note.startsWith('-') ? 'negative' : 'positive'}>{method.note}</em></div>)}</div></div></div>
	</div>
}

export function ValuationSummary({ valuation, latestClose, state = 'ready' }: { valuation?: TraditionalValuation; latestClose?: number | null; state?: ModuleState }) { return <section className="section valuation-summary-section">{state === 'ready' ? <><ValuationBlock kind="fundamental" valuation={valuation} latestClose={latestClose} /><ValuationBlock kind="model" valuation={valuation} latestClose={latestClose} /></> : <ModuleStateNotice state={state} label="估值摘要" />}</section> }
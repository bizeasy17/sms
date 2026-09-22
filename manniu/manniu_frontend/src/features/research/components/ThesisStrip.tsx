function actionLabel(action?: string | null) {
	const labels: Record<string, string> = { BUY: '买入', HOLD: '持有', SELL: '卖出' }
	return action ? labels[action.trim().toUpperCase()] ?? null : null
}

function money(value: number | null | undefined) { return value == null ? '暂无' : `¥${value.toFixed(2)}` }

function traditionalStatement(currentPrice: number | null | undefined, centerPrice: number | null | undefined, conservativePrice: number | null | undefined, optimisticPrice: number | null | undefined, methodCount: number) {
	if (currentPrice == null || centerPrice == null) return `传统估值已返回 ${methodCount} 个估值模型结果，当前价格或估值中枢暂无数据。`
	const relation = currentPrice < centerPrice ? '低于' : currentPrice > centerPrice ? '高于' : '等于'
	return `传统估值基于 ${methodCount} 个模型：当前价 ${money(currentPrice)}${relation}估值中枢 ${money(centerPrice)}，区间为 ${money(conservativePrice)} 至 ${money(optimisticPrice)}。`
}

function predictiveStatement(currentPrice: number | null | undefined, targetPrice: number | null | undefined, low: number | null | undefined, high: number | null | undefined) {
	if (targetPrice == null && low == null && high == null) return '预测估值暂未返回有效的目标价区间。'
	const range = low != null || high != null ? `目标区间为 ${money(low)} 至 ${money(high)}` : `目标价为 ${money(targetPrice)}`
	if (currentPrice == null) return `预测模型${range}。当前价格暂无数据。`
	if (low != null && high != null) {
		const position = currentPrice < low ? '低于' : currentPrice > high ? '高于' : '处于'
		return `预测模型${range}，当前价 ${money(currentPrice)}${position}该区间。`
	}
	return `预测模型${range}，当前价为 ${money(currentPrice)}。`
}

export function ThesisStrip({ score = null, buyCandidate = null, action = null, riskLevel = null, statement }: { score?: number | null; buyCandidate?: boolean | null; action?: string | null; riskLevel?: string | null; statement: string }) { const riskLabels: Record<string, string> = { HIGH: '高', MEDIUM: '中', LOW: '低' }; const normalizedAction = action?.trim().toUpperCase(); const displayRisk = riskLevel ? riskLabels[riskLevel] ?? riskLevel : '暂无'; const verdict = actionLabel(action) ?? (buyCandidate === true ? '买入候选' : buyCandidate === false ? '中性持有' : '暂无研究结论'); const signalClass = normalizedAction === 'BUY' || buyCandidate === true ? 'buy-signal' : normalizedAction === 'SELL' ? 'sell-signal' : 'neutral-signal'; return <section className={`thesis-strip ${signalClass}`}><div className="thesis-verdict"><span className="verdict-dot" /><div><p className="kicker">CURRENT VIEW</p><h2>{verdict}</h2></div></div><div className="thesis-copy"><strong>{statement}</strong><p>以上内容根据当前返回的估值数据生成。</p></div><div className="confidence"><span>估值分数</span><strong>{typeof score === 'number' ? Math.round(score) : '暂无'}</strong>{typeof score === 'number' && <small>/ 100</small>}<span className="risk-level"><span>风险级别</span><strong>{displayRisk}</strong></span></div></section> }

export { predictiveStatement, traditionalStatement }
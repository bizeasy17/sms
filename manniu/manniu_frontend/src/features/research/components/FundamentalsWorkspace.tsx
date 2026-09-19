import { FundamentalEvidence } from './FundamentalEvidence'
import type { FinancialMetric, FinancialOverview, FundamentalEvaluation, Stock } from '../types'

function TrendChart({ points, tone }: { points: Array<{ value: number; label: string }>; tone: string }) {
  const lastIndex = Math.max(points.length - 1, 1)
  const xFor = (index: number) => 4 + (index * 100) / lastIndex
  const line = points.map((point, index) => `${xFor(index)},${100 - point.value}`).join(' ')
  return <div className="fundamentals-chart-wrap"><svg className={`fundamentals-chart ${tone}`} viewBox="0 0 108 108" preserveAspectRatio="none" role="img" aria-label={`${points.at(-1)?.label ?? '最新'} 财务评判趋势`}><path className="fundamentals-chart-grid" d="M4 20H104M4 50H104M4 80H104" /><polyline points={line} /></svg><div className="fundamentals-chart-labels">{points.map((point) => <span key={point.label}>{point.label}</span>)}</div></div>
}

function scoreValue(dimension?: { score: number | null }) {
  return dimension?.score == null ? null : Math.round(dimension.score)
}

function overallLabel(status: string) {
  const labels: Record<string, string> = {
    STRONG: '强劲', HEALTHY: '健康', NEUTRAL: '中性', WEAK: '较弱',
    GOOD: '稳健', WARN: '需关注', RISK: '存在风险', NOT_AVAILABLE: '暂无研究结论',
  }
  return labels[status] ?? status
}

function dimensionLabel(key: string) {
  return ({ growth: '增长能力', profitability: '盈利能力', cash_flow_quality: '现金流质量', solvency: '偿债能力' } as Record<string, string>)[key] ?? key
}

export function FundamentalsWorkspace({ stock, metrics, evaluation, financialOverview, financialState, onFinancialRetry }: { stock: Stock; metrics: Record<string, FinancialMetric> | null; evaluation: FundamentalEvaluation | null; financialOverview: FinancialOverview | null; financialState: 'loading' | 'ready' | 'empty' | 'error'; onFinancialRetry: () => void }) {
  const trend = evaluation?.trend ?? []
  const dimensions = Object.entries(evaluation?.dimensions ?? {})
  const reports = evaluation?.reports ?? []
  const signals = evaluation?.signals ?? []
  const overall = evaluation?.overall
  return <div className="fundamentals-workspace">
    <section className="section fundamentals-summary"><div className="section-heading"><div><p className="kicker">03 / FUNDAMENTALS &amp; FILINGS</p><h2>基本面与财务档案</h2><p className="fundamentals-context">{stock.name} · {stock.code} · 最新报告期 {financialOverview?.period ?? '暂无报告期'}</p></div><div className="fundamentals-controls"><label htmlFor="fundamentals-period">报告期</label><select id="fundamentals-period" defaultValue="LATEST"><option value="LATEST">最新报告期</option></select></div></div><div className="fundamentals-summary-grid"><div><span>经营结论</span><strong className={overall?.status === 'WEAK' ? 'weak' : overall?.status === 'STRONG' || overall?.status === 'HEALTHY' ? 'positive' : ''}>{overallLabel(overall?.status ?? 'NOT_AVAILABLE')}</strong><p>{overall?.score == null ? '当前暂无综合评分。' : `综合评分 ${Math.round(overall.score)}/100`}</p></div><div><span>可用权重</span><strong>{overall?.availableWeight == null ? '暂无' : `${Math.round(overall.availableWeight)}%`}</strong><p>{overall?.missingDimensions.length ? `缺失：${overall.missingDimensions.map(dimensionLabel).join('、')}` : '评判维度完整'}</p></div><div><span>数据状态</span><strong>{financialState === 'ready' ? '完整' : financialState === 'loading' ? '加载中' : '待补充'}</strong><p className="mono">{evaluation?.evaluationVersion ?? '评判版本暂无'} · {financialOverview?.period ?? '暂无报告期'}</p></div></div>{evaluation?.warnings.map((warning) => <p className="fundamentals-warning" key={warning}>{warning}</p>)}</section>
    <FundamentalEvidence metrics={metrics} state={financialState} onRetry={onFinancialRetry} />
    <section className="section"><div className="section-heading"><div><p className="kicker">FINANCIAL TRENDS</p><h2>财务趋势</h2></div><span className="section-note">后端评判结果</span></div><div className="fundamentals-trend-grid">{dimensions.map(([key, dimension], index) => { const points = trend.map((item) => ({ value: scoreValue(item.dimensions[key]), label: item.period ?? '暂无期次' })).filter((point): point is { value: number; label: string } => point.value != null); const current = scoreValue(dimension); const isWeak = dimension.status === 'WEAK'; const tone = isWeak ? 'weak' : index % 2 ? 'red' : 'blue'; return <div className="fundamentals-trend" key={key}><div className="fundamentals-trend-heading"><div><h3>{dimensionLabel(key)}</h3><span className={isWeak ? 'weak' : ''}>{dimension.available ? overallLabel(dimension.status) : '数据不足'}</span></div><b className={isWeak ? 'weak' : index % 2 ? 'positive' : 'primary'}>{current == null ? '暂无' : current}<small>{current == null ? '' : '/100'}</small></b></div>{points.length ? <TrendChart points={points} tone={tone} /> : <p className="fundamentals-empty">暂无趋势数据</p>}</div> })}</div></section>
    <div className="fundamentals-bottom-grid"><section className="section"><div className="section-heading"><div><p className="kicker">REPORT ARCHIVE</p><h2>财报档案</h2></div><span className="section-note">{reports.length} 个报告期</span></div><div className="report-list">{reports.length ? reports.map((report) => <details key={`${report.period}-${report.endDate}`} open={report === reports[0]}><summary><span className="mono">{report.period}</span><strong>{report.reportType ?? '报告'}</strong><small>{report.endDate}</small><em>{report.dataStatus}</em></summary><p>{report.annDate ?? '暂无发布日期'} · {report.sourceRevision ?? '当前版本'}</p></details>) : <p className="fundamentals-empty">暂无财报档案</p>}</div></section><section className="section"><div className="section-heading"><div><p className="kicker">FUNDAMENTAL SIGNALS</p><h2>基本面信号</h2></div><span className="section-note">后端确认</span></div><div className="fundamental-signal-list">{signals.length ? signals.map((signal) => <div key={`${signal.asofDate}-${signal.signalCode}`}><span className={`signal-dot ${signal.severity.toLowerCase()}`} /><div><div className="signal-meta"><span>{signal.asofDate ?? '暂无日期'}</span><strong>{signal.label}</strong><em>{signal.status}</em></div><p>{signal.evidence || '暂无证据'}</p></div></div>) : <p className="fundamentals-empty">近期暂无明确基本面信号</p>}</div></section></div>
  </div>
}

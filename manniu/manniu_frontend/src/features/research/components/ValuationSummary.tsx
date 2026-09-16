import { ModuleStateNotice, type ModuleState } from './ModuleStateNotice'
import { ThesisStrip } from './ThesisStrip'

const fundamentalMethods = [['PE 估值', '¥25.10', '+1.7% · 合理'], ['FCFF 模型', '¥28.40', '+15.1% · 低估'], ['盈利预测', '¥23.60', '-4.4% · 偏高']]
const modelMethods = [['预测模型 A', '¥27.20', '+10.2% · 低估'], ['预测模型 B', '¥25.80', '+4.5% · 合理'], ['融合模型', '¥26.40', '+7.0% · 合理']]

function ValuationBlock({ kind }: { kind: 'fundamental' | 'model' }) {
	const isFundamental = kind === 'fundamental'
	const methods = isFundamental ? fundamentalMethods : modelMethods
	return <div className={`fundamental-valuation-block ${isFundamental ? '' : 'model-valuation-block'}`}>
		<div className="section-heading"><div><p className="kicker">{isFundamental ? '01.1 / FUNDAMENTAL VALUATION' : '01.2 / MODEL VALUATION'}</p><h2>{isFundamental ? '基本面估值摘要' : '模型估值摘要'}</h2></div><span className="section-note">3 个模型 · 更新于 08-17</span></div>
		<ThesisStrip />
		<div className="valuation-layout"><div><div className="range-values"><span>保守 <strong>¥20.40</strong></span><span>中枢 <strong>¥26.80</strong></span><span>乐观 <strong>¥34.60</strong></span></div><div className="range-bar"><span className="range-pointer"><i>¥24.68</i></span></div><div className="range-labels"><span>低估</span><span>合理</span><span>高估</span></div><p className="range-caption">当前价格位于综合估值区间的 <strong>57%</strong>，接近合理区间下沿。</p></div><div className="valuation-methods"><div className="method-list">{methods.map(([name, value, note]) => <div key={name}><span>{name}</span><strong>{value}</strong><em className={note.startsWith('-') ? 'negative' : 'positive'}>{note}</em></div>)}</div></div></div>
	</div>
}

export function ValuationSummary({ state = 'ready' }: { state?: ModuleState }) { return <section className="section valuation-summary-section">{state === 'ready' ? <><ValuationBlock kind="fundamental" /><ValuationBlock kind="model" /></> : <ModuleStateNotice state={state} label="估值摘要" />}</section> }
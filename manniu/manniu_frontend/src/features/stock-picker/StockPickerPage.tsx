import { useState } from 'react'
import { TopBar } from '../../shared/ui/TopBar'
import type { StockSelectionFilterDraft, StockSelectionItem, StockSelectionPreset, StockSelectionRangeKey, StockSelectionToggleKey } from './services/stockSelectionApi'
import { useStockSelection } from './hooks/useStockSelection'
import './stock-picker.css'

type SortKey = 'score' | 'valueValuationScore' | 'modelValuationScore' | 'revenueYoy' | 'profitYoy' | 'ebitYoy' | 'roe' | 'liquidityRatio'
const PRESET_OPTIONS: { key: StockSelectionPreset; label: string; group: '精选方案' | '全部预设' }[] = [
  { key: 'maniu-selected', label: '慢牛牛精选', group: '精选方案' },
  { key: 'buffett-moat', label: '巴菲特护城河', group: '精选方案' },
  { key: 'high-growth', label: '高成长', group: '精选方案' },
  { key: 'cash-cow', label: '现金奶牛', group: '精选方案' },
  { key: 'undervalued', label: '低估价值股', group: '精选方案' },
  { key: 'high-dividend', label: '高股息', group: '全部预设' },
  { key: 'small-beautiful', label: '小而美', group: '全部预设' },
  { key: 'turnaround', label: '困境反转', group: '全部预设' },
  { key: 'net-cash-bargain', label: '净现金便宜货', group: '全部预设' },
  { key: 'risk-scan', label: '排雷模式', group: '全部预设' },
]

const RANGE_GROUPS: { title: string; fields: { key: StockSelectionRangeKey; label: string; unit: string; hint: string }[] }[] = [
  { title: '成长性', fields: [
    { key: 'revenue_yoy', label: '营收增长率', unit: '%', hint: '建议 0–50%' },
    { key: 'profit_yoy', label: '净利润增长率', unit: '%', hint: '建议 0–50%' },
    { key: 'ebit_yoy', label: 'EBIT 增长率', unit: '%', hint: '建议 0–50%' },
  ] },
  { title: '盈利质量', fields: [
    { key: 'roe', label: 'ROE', unit: '%', hint: '建议 0–30%' },
    { key: 'roic', label: 'ROIC', unit: '%', hint: '建议 0–30%' },
    { key: 'gross_margin', label: '毛利率', unit: '%', hint: '建议 0–80%' },
  ] },
  { title: '现金流质量', fields: [
    { key: 'cash_profit_ratio', label: '现金利润比', unit: '倍', hint: '可按需设上下限' },
  ] },
  { title: '财务健康', fields: [
    { key: 'debt_to_assets', label: '资产负债率', unit: '%', hint: '建议 0–100%' },
    { key: 'liquidity_ratio', label: '流动比率', unit: '倍', hint: '建议 0–5' },
    { key: 'goodwill_to_equity', label: '商誉 / 净资产', unit: '%', hint: '建议 0–100%' },
  ] },
  { title: '估值水平', fields: [
    { key: 'pe_ttm', label: 'PE（TTM）', unit: '倍', hint: '建议 0–100' },
    { key: 'pb', label: 'PB', unit: '倍', hint: '建议 0–10' },
    { key: 'peg', label: 'PEG', unit: '倍', hint: '建议 0–5' },
    { key: 'dividend_yield', label: '股息率', unit: '%', hint: '建议 0–10%' },
    { key: 'market_cap', label: '总市值', unit: '亿', hint: '建议 20–200 亿' },
  ] },
]

const TOGGLE_GROUPS: { title: string; fields: { key: StockSelectionToggleKey; label: string }[] }[] = [
  { title: '盈利质量', fields: [{ key: 'net_profit_positive', label: '净利润为正' }, { key: 'gross_margin_improved', label: '毛利率同比改善' }] },
  { title: '现金流质量', fields: [{ key: 'operating_cash_flow_positive', label: '经营现金流为正' }, { key: 'free_cash_flow_positive', label: '自由现金流为正' }, { key: 'net_cash', label: '净现金企业' }] },
]

const PRESET_DEFAULTS: Record<StockSelectionPreset, { ranges?: Partial<Record<StockSelectionRangeKey, { min?: number; max?: number }>>; toggles?: Partial<Record<StockSelectionToggleKey, boolean>> }> = {
  'maniu-selected': { ranges: { revenue_yoy: { min: 8 }, profit_yoy: { min: 8 }, ebit_yoy: { min: 8 }, roe: { min: 15 }, roic: { min: 12 }, debt_to_assets: { max: 50 }, liquidity_ratio: { min: 1.5 }, pe_ttm: { max: 25 }, dividend_yield: { min: 2 } }, toggles: { gross_margin_improved: true, operating_cash_flow_positive: true, free_cash_flow_positive: true } },
  'buffett-moat': { ranges: { revenue_yoy: { min: 5 }, profit_yoy: { min: 5 }, roe: { min: 20 }, roic: { min: 15 }, gross_margin: { min: 40 }, debt_to_assets: { max: 50 }, pe_ttm: { max: 30 } }, toggles: { operating_cash_flow_positive: true, free_cash_flow_positive: true } },
  'high-growth': { ranges: { revenue_yoy: { min: 20 }, profit_yoy: { min: 20 }, ebit_yoy: { min: 20 }, roe: { min: 10 }, peg: { max: 1.5 } }, toggles: { operating_cash_flow_positive: true } },
  'cash-cow': { ranges: { roe: { min: 15 }, roic: { min: 12 }, pe_ttm: { max: 20 } }, toggles: { operating_cash_flow_positive: true, free_cash_flow_positive: true, net_cash: true } },
  undervalued: { ranges: { roe: { min: 10 }, debt_to_assets: { max: 60 }, pe_ttm: { max: 15 }, pb: { max: 1.5 } }, toggles: { operating_cash_flow_positive: true } },
  'high-dividend': { ranges: { roe: { min: 10 }, dividend_yield: { min: 5 } }, toggles: { operating_cash_flow_positive: true } },
  'small-beautiful': { ranges: { revenue_yoy: { min: 15 }, profit_yoy: { min: 15 }, roe: { min: 15 }, market_cap: { min: 20, max: 200 } }, toggles: { operating_cash_flow_positive: true } },
  turnaround: { ranges: { revenue_yoy: { min: 0 }, profit_yoy: { min: 0 }, roe: { min: 8 }, pb: { max: 2 } }, toggles: { operating_cash_flow_positive: true } },
  'net-cash-bargain': { ranges: { pe_ttm: { max: 12 }, pb: { max: 1.5 } }, toggles: { net_profit_positive: true, net_cash: true } },
  'risk-scan': {},
}

function createFilterDraft(preset: StockSelectionPreset): StockSelectionFilterDraft {
  const defaults = PRESET_DEFAULTS[preset]
  return {
    ranges: Object.fromEntries(RANGE_GROUPS.flatMap((group) => group.fields).map(({ key }) => [key, { min: String(defaults.ranges?.[key]?.min ?? ''), max: String(defaults.ranges?.[key]?.max ?? '') }])) as StockSelectionFilterDraft['ranges'],
    toggles: Object.fromEntries(TOGGLE_GROUPS.flatMap((group) => group.fields).map(({ key }) => [key, Boolean(defaults.toggles?.[key])])) as StockSelectionFilterDraft['toggles'],
  }
}

type StockRow = {
  code: string
  name: string
  industry: string
  mainBusiness: string
  score: number
  valueValuationScore: number
  modelValuationScore: number
  revenueYoy: number
  profitYoy: number
  ebitYoy: number
  roe: number
  grossMarginChange: number
  cashFlow: number
  liquidityRatio: number
}

function mapSelectionRow(item: StockSelectionItem): StockRow {
  const industry = item.industry || item.sw_industry?.name || '暂无行业'
  const mainBusiness = item.main_business || '主营业务暂无数据'
  const wrappedBusiness = mainBusiness.match(/.{1,15}/g)?.join('\n') || mainBusiness
  return { code: item.ts_code, name: item.name, industry: `${industry}\n${wrappedBusiness}`, mainBusiness, score: roundValue(item.financial_score, 0), valueValuationScore: roundValue(item.value_valuation_score, 0), modelValuationScore: roundValue(item.model_valuation_score, 0), revenueYoy: roundValue(item.revenue_yoy, 1), profitYoy: roundValue(item.profit_yoy, 1), ebitYoy: roundValue(item.ebit_yoy, 1), roe: roundValue(item.roe, 1), grossMarginChange: roundValue(item.gross_margin_change, 1), cashFlow: roundValue(item.operating_cash_flow != null ? Number(item.operating_cash_flow) / 100000000 : null, 2), liquidityRatio: roundValue(item.liquidity_ratio, 1) }
}

function displayNumber(value: number, digits = 1, suffix = '') { return Number.isNaN(value) ? '--' : `${value.toFixed(digits)}${suffix}` }

function roundValue(value: number | string | null | undefined, digits: number) {
  if (value == null || value === '') return Number.NaN
  const numericValue = Number(value)
  return Number.isFinite(numericValue) ? Number(numericValue.toFixed(digits)) : Number.NaN
}

function ToggleField({ label, checked, onChange }: { label: string; checked: boolean; onChange: () => void }) {
  return <div className="filter-toggle"><span>{label}</span><button type="button" role="switch" aria-checked={checked} aria-label={label} className={`toggle ${checked ? 'on' : ''}`} onClick={onChange}><i /></button></div>
}

function ThresholdField({ name, label, unit, hint, minValue, maxValue, onChange }: { name: string; label: string; unit: string; hint: string; minValue: string; maxValue: string; onChange: (bound: 'min' | 'max', value: string) => void }) {
  return <div className="threshold-field" role="group" aria-labelledby={`${name}-label`}><span id={`${name}-label`} className="threshold-label">{label}</span><div className="threshold-inputs"><input id={`${name}-min`} aria-label={`${label}最低值`} type="number" step="any" value={minValue} onChange={(event) => onChange('min', event.target.value)} /><span aria-hidden="true">~</span><input id={`${name}-max`} aria-label={`${label}最高值`} type="number" step="any" value={maxValue} onChange={(event) => onChange('max', event.target.value)} /><span>{unit}</span></div><small>{hint}</small></div>
}

export function StockPickerPage() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [sortKey, setSortKey] = useState<SortKey>('score')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc')
  const [page, setPage] = useState(1)
  const [selectedIndustry, setSelectedIndustry] = useState('all')
  const [reportType, setReportType] = useState('26H1')
  const [market, setMarket] = useState('all')
  const [asofDate, setAsofDate] = useState('2026-09-19')
  const [selectedPreset, setSelectedPreset] = useState<StockSelectionPreset>('maniu-selected')
  const [filterDraft, setFilterDraft] = useState(() => createFilterDraft('maniu-selected'))

  const { industries, industryStatus, industryError, resultRows, marketStockCount, matchedCount, queryStatus, queryError, updateResults: queryResults } = useStockSelection(selectedPreset, filterDraft, sortKey, sortDirection, market, reportType, asofDate, selectedIndustry)

  function updateBound(key: StockSelectionRangeKey, bound: 'min' | 'max', value: string) { setFilterDraft((current) => ({ ...current, ranges: { ...current.ranges, [key]: { ...current.ranges[key], [bound]: value } } })); setSubmitted(false) }
  function updateToggle(key: StockSelectionToggleKey) { setFilterDraft((current) => ({ ...current, toggles: { ...current.toggles, [key]: !current.toggles[key] } })); setSubmitted(false) }
  function selectPreset(value: string) { const preset = value as StockSelectionPreset; setSelectedPreset(preset); setFilterDraft(createFilterDraft(preset)); setSubmitted(false) }
  function updateSort(nextKey: SortKey) { setSortKey(nextKey); setPage(1) }
  function toggleSortDirection() { setSortDirection((value) => value === 'desc' ? 'asc' : 'desc'); setPage(1) }
  async function updateResults() {
    setPage(1)
    if (await queryResults(1, true)) { setSubmitted(true); setSidebarOpen(false) }
  }
  async function changePage(nextPage: number) {
    const totalPages = Math.max(1, Math.ceil(matchedCount / 10))
    if (!submitted || queryStatus === 'loading' || nextPage < 1 || nextPage > totalPages || nextPage === page) return
    setPage(nextPage)
    await queryResults(nextPage)
  }
  function exportCsv() {
    const header = '公司,股票代码,所属行业,主营业务,财务评分,价值估分,模型估分,营收增长,净利润增长,EBIT增长,ROE,毛利率变化,经营现金流,流动比率'
    const csvRows = resultRows.map(mapSelectionRow).map((row) => [row.name, row.code, row.industry.replace('\n', ' '), row.mainBusiness, displayNumber(row.score, 0), displayNumber(row.valueValuationScore, 0), displayNumber(row.modelValuationScore, 0), displayNumber(row.revenueYoy, 1, '%'), displayNumber(row.profitYoy, 1, '%'), displayNumber(row.ebitYoy, 1, '%'), displayNumber(row.roe, 1, '%'), displayNumber(row.grossMarginChange, 1, 'pct'), displayNumber(row.cashFlow, 2, '亿元'), displayNumber(row.liquidityRatio, 1)].join(','))
    const url = URL.createObjectURL(new Blob([`${header}\n${csvRows.join('\n')}`], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a'); link.href = url; link.download = 'stock_picker_financial_20260919_H1.csv'; link.click(); URL.revokeObjectURL(url)
  }

  const sortedRows = resultRows.map(mapSelectionRow).sort((left, right) => {
    const difference = (right[sortKey] ?? -Infinity) - (left[sortKey] ?? -Infinity)
    return sortDirection === 'desc' ? difference : -difference
  })

  return <div className="app-shell stock-picker-page stock-picker-shell">
    <TopBar activeSection="picker" onMenu={() => setSidebarOpen((open) => !open)} onSelect={() => undefined} />
    <div className="stock-picker-layout">
      <aside className={`picker-sidebar ${sidebarOpen ? 'open' : ''}`} aria-label="选股筛选器">
        <div className="sidebar-title">筛选器</div>
        <label className="saved-screen-picker">预设方案<select value={selectedPreset} aria-label="选择预设方案" onChange={(event) => selectPreset(event.target.value)}><optgroup label="首页精选">{PRESET_OPTIONS.filter((option) => option.group === '精选方案').map((option) => <option key={option.key} value={option.key}>{option.label}</option>)}</optgroup><optgroup label="全部预设">{PRESET_OPTIONS.filter((option) => option.group === '全部预设').map((option) => <option key={option.key} value={option.key}>{option.label}</option>)}</optgroup></select></label>
        <div className="filter-draft-actions"><button type="button" onClick={() => { setFilterDraft(createFilterDraft(selectedPreset)); setSubmitted(false) }}>恢复预设</button><button type="button" onClick={() => { setFilterDraft(createFilterDraft('risk-scan')); setSubmitted(false) }}>清空条件</button></div>
        {selectedPreset === 'risk-scan' ? <section className="filter-group risk-rules"><h2>排雷规则 <span>命中任一项</span></h2>{['连续两年净利润同比为负', 'ROE < 5%', '经营现金流为负', '资产负债率 > 70%', '商誉 / 净资产 > 30%'].map((rule) => <div key={rule}><i aria-hidden="true">!</i><span>{rule}</span></div>)}</section> : <>
          {RANGE_GROUPS.map((group) => <section className="filter-group" key={group.title}><h2>{group.title}</h2>{group.fields.map(({ key, ...field }) => <ThresholdField key={key} name={key} {...field} minValue={filterDraft.ranges[key].min} maxValue={filterDraft.ranges[key].max} onChange={(bound, value) => updateBound(key, bound, value)} />)}{TOGGLE_GROUPS.filter((toggleGroup) => toggleGroup.title === group.title).flatMap((toggleGroup) => toggleGroup.fields).map((field) => <ToggleField key={field.key} label={field.label} checked={filterDraft.toggles[field.key]} onChange={() => updateToggle(field.key)} />)}</section>)}
        </>}
        <section className="filter-group range-group"><h2>数据范围</h2><label>报告期<select value={reportType} onChange={(event) => { setReportType(event.target.value); setSubmitted(false) }}><option value="26H1">2026 H1</option><option value="26FY">2026 FY</option><option value="25FY">2025 FY</option><option value="25H1">2025 H1</option></select></label><label>市场<select value={market} onChange={(event) => { setMarket(event.target.value); setSubmitted(false) }}><option value="all">沪深 A 股</option><option value="sh-main">沪市主板</option><option value="sz-main">深市主板</option><option value="cyb">创业板</option><option value="star">科创板</option></select></label><label>选股日期<input type="date" value={asofDate} max="2026-09-19" onChange={(event) => { setAsofDate(event.target.value); setSubmitted(false) }} /></label><label>SW 行业<select value={selectedIndustry} onChange={(event) => { setSelectedIndustry(event.target.value); setSubmitted(false) }} disabled={industryStatus === 'loading'} aria-label="选择 SW 行业"><option value="all">{industryStatus === 'error' ? '行业列表加载失败' : industryStatus === 'loading' ? '正在加载行业...' : industries.length ? '全部行业' : '暂无可选行业'}</option>{industries.map((industry) => <option key={industry.industry_code} value={industry.industry_code}>{industry.name}</option>)}</select>{industryStatus === 'error' && <small role="alert" className="filter-error">{industryError}</small>}</label></section>
        <button type="button" className="sidebar-run" onClick={updateResults} disabled={queryStatus === 'loading'}>{queryStatus === 'loading' ? '更新中...' : submitted ? '已更新结果' : '更新结果'} <b>↗</b></button>
      </aside>
      {sidebarOpen && <button className="sidebar-backdrop" aria-label="关闭筛选器" onClick={() => setSidebarOpen(false)} />}
      <main className="picker-workspace"><div className="picker-crumb">发现 <b>/</b> 因子筛选 <b>/</b> <strong>财务表现</strong></div><div className="picker-heading"><div><h1>财务表现选股</h1><p>从盈利质量、成长性与财务安全性中筛出值得深入研究的公司。</p></div><button type="button" className="run-results" onClick={updateResults} disabled={queryStatus === 'loading'}>{queryStatus === 'loading' ? '更新中...' : submitted ? '结果已更新' : '更新结果'}</button></div>
        {queryStatus === 'error' && <p role="alert" className="filter-error">{queryError}</p>}
        <section className="result-summary"><div><label>符合条件</label><b>{matchedCount} <i>只</i></b></div><div><label>覆盖公司</label><b>{marketStockCount.toLocaleString()} <i>只</i></b></div><div><label>最近更新</label><b>{asofDate}</b></div></section>
        {!submitted && <div className="result-empty-state"><strong>尚未查询选股结果</strong><span>请配置左侧筛选条件后，点击“更新结果”开始查询。</span></div>}
        {submitted && resultRows.length === 0 && queryStatus !== 'error' && <div className="result-empty-state"><strong>暂无符合条件的股票</strong><span>当前筛选条件没有匹配结果，请调整报告期、市场或财务条件后重试。</span></div>}
        <div className="result-toolbar"><div><h2>筛选结果 <span>按{sortKey === 'score' ? '综合财务评分' : sortKey === 'valueValuationScore' ? '价值估分' : sortKey === 'modelValuationScore' ? '模型估分' : sortKey === 'revenueYoy' ? '营收增长' : sortKey === 'profitYoy' ? '净利润增长' : sortKey === 'ebitYoy' ? 'EBIT 增长' : sortKey === 'roe' ? 'ROE' : '流动比率'}{sortDirection === 'desc' ? '降序' : '升序'}</span></h2></div>{queryStatus === 'loading' && <div className="selection-progress is-loading" role="status" aria-live="polite"><div className="selection-progress-track"><span /></div><span className="selection-progress-label">正在执行选股...</span></div>}<div className="view-switch"><button className="active" type="button">财务表现</button><button type="button" disabled title="估值视图尚未接入">估值</button><button type="button" disabled title="技术面视图尚未接入">技术面</button></div></div>
        <section className="financial-table-card"><div className="table-actions"><label>排序<select value={sortKey} onChange={(event) => updateSort(event.target.value as SortKey)}><option value="score">财务评分</option><option value="valueValuationScore">价值估分</option><option value="modelValuationScore">模型估分</option><option value="revenueYoy">营收增速</option><option value="profitYoy">净利润增速</option><option value="ebitYoy">EBIT 增速</option><option value="roe">ROE</option><option value="liquidityRatio">流动比率</option></select></label><button type="button" className="sort-direction" onClick={toggleSortDirection}>{sortDirection === 'desc' ? '↓ 从高到低' : '↑ 从低到高'}</button><button type="button" className="export-button" onClick={exportCsv}>↓ 导出 CSV</button></div><div className="financial-table-wrap"><table><thead><tr><th scope="col">公司</th><th scope="col">所属行业</th><th scope="col">财务评分</th><th scope="col">价值估分</th><th scope="col">模型估分</th><th scope="col">营收增速</th><th scope="col">净利润增速</th><th scope="col">EBIT 增长</th><th scope="col">ROE</th><th scope="col">毛利率变化</th><th scope="col">经营现金流（亿元）</th><th scope="col">流动比率</th></tr></thead><tbody>{sortedRows.map((row) => <tr key={row.code}><td><a href={`/?ts_code=${row.code}&tab=fundamentals&picker=financial`} target="_blank" rel="noopener noreferrer">{row.name}</a><code>{row.code}</code></td><td className="sector">{row.industry}</td><td><span className={`financial-score ${row.score < 80 ? 'watch' : ''}`}>{row.score}</span></td><td><span className={`financial-score ${row.valueValuationScore < 80 ? 'watch' : ''}`}>{row.valueValuationScore}</span></td><td><span className={`financial-score ${row.modelValuationScore < 80 ? 'watch' : ''}`}>{row.modelValuationScore}</span></td><td className="positive">+{row.revenueYoy}%</td><td className="positive">+{row.profitYoy}%</td><td className="positive">+{row.ebitYoy}%</td><td>{row.roe}%</td><td className={row.grossMarginChange < 0 ? 'negative' : 'positive'}>{row.grossMarginChange > 0 ? '+' : ''}{row.grossMarginChange}pct</td><td className={row.cashFlow < 0 ? 'negative' : 'positive'}>{row.cashFlow > 0 ? '+' : ''}{displayNumber(row.cashFlow, 2)}亿元</td><td>{row.liquidityRatio}</td></tr>)}</tbody></table></div><p className="result-note">评分由盈利质量、成长质量、现金流与资产负债表四类指标加权计算；点击公司可进入个股研究档案。</p><div className="picker-pagination"><span>命中总数：{matchedCount} <i /> 当前范围：{resultRows.length ? `${(page - 1) * 10 + 1}-${(page - 1) * 10 + resultRows.length}` : '0-0'}</span><div>{(() => { const totalPages = Math.max(1, Math.ceil(matchedCount / 10)); return <><button type="button" disabled={page === 1 || queryStatus === 'loading'} onClick={() => void changePage(page - 1)}>‹</button>{Array.from({ length: totalPages }, (_, index) => index + 1).map((pageNumber) => <button key={pageNumber} type="button" className={page === pageNumber ? 'current' : ''} disabled={queryStatus === 'loading'} onClick={() => void changePage(pageNumber)}>{pageNumber}</button>)}<button type="button" disabled={page === totalPages || queryStatus === 'loading'} onClick={() => void changePage(page + 1)}>›</button></> })()}</div></div></section>
      </main>
    </div>
  </div>
}

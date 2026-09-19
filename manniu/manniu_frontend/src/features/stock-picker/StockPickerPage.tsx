import { useState } from 'react'
import { TopBar } from '../research/components/TopBar'
import './stock-picker.css'

type FilterKey = 'revenueYoy' | 'profitYoy' | 'pePercentile'
type SortKey = 'score' | 'revenueYoy' | 'profitYoy' | 'roe' | 'pePercentile'

type StockRow = {
  code: string
  name: string
  industry: string
  score: number
  revenueYoy: number
  profitYoy: number
  roe: number
  grossMarginChange: number
  cashFlow: number
  pePercentile: number
}

const rows: StockRow[] = [
  { code: '300750.SZ', name: '宁德时代', industry: '电力设备', score: 92, revenueYoy: 18.4, profitYoy: 22.8, roe: 19.7, grossMarginChange: 2.1, cashFlow: 36.5, pePercentile: 48 },
  { code: '000333.SZ', name: '美的集团', industry: '家用电器', score: 89, revenueYoy: 12.6, profitYoy: 14.1, roe: 23.4, grossMarginChange: 0.8, cashFlow: 11.2, pePercentile: 53 },
  { code: '300760.SZ', name: '迈瑞医疗', industry: '医疗器械', score: 87, revenueYoy: 11.3, profitYoy: 16.7, roe: 28.1, grossMarginChange: 1.4, cashFlow: 8.6, pePercentile: 44 },
  { code: '600900.SH', name: '长江电力', industry: '公用事业', score: 84, revenueYoy: 9.8, profitYoy: 12.4, roe: 15.8, grossMarginChange: 0.2, cashFlow: 13.7, pePercentile: 58 },
  { code: '002415.SZ', name: '海康威视', industry: '安防设备', score: 78, revenueYoy: 10.5, profitYoy: 8.2, roe: 14.9, grossMarginChange: -0.3, cashFlow: 5.1, pePercentile: 62 },
  { code: '600519.SH', name: '贵州茅台', industry: '食品饮料', score: 76, revenueYoy: 15.1, profitYoy: 14.8, roe: 35.2, grossMarginChange: 0.5, cashFlow: 17.6, pePercentile: 71 },
]

function ToggleField({ label, checked, onChange }: { label: string; checked: boolean; onChange: () => void }) {
  return <label className="filter-toggle"><span>{label}</span><button type="button" role="switch" aria-checked={checked} aria-label={label} className={`toggle ${checked ? 'on' : ''}`} onClick={onChange}><i /></button></label>
}

function ThresholdField({ label, value, max, onChange }: { label: string; value: number; max: number; onChange: (value: number) => void }) {
  return <div className="threshold-field"><label htmlFor={`threshold-${label}`}>{label} <b>≥ {value}%</b></label><input id={`threshold-${label}`} type="range" min="0" max={max} value={value} onChange={(event) => onChange(Number(event.target.value))} /><div><span>0%</span><span>{max}%</span></div></div>
}

export function StockPickerPage() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [sortKey, setSortKey] = useState<SortKey>('score')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc')
  const [page, setPage] = useState(1)
  const [filters, setFilters] = useState({ roe: true, grossMargin: true, cashFlow: true, revenueYoy: 10, profitYoy: 10, pePercentile: 70 })

  function updateFilter(key: FilterKey, value: number) { setFilters((current) => ({ ...current, [key]: value })); setSubmitted(false) }
  function updateSort(nextKey: SortKey) { setSortKey(nextKey); setPage(1); setSubmitted(false) }
  function toggleSortDirection() { setSortDirection((value) => value === 'desc' ? 'asc' : 'desc'); setPage(1); setSubmitted(false) }
  function updateResults() { setSubmitted(true); setPage(1); setSidebarOpen(false) }
  function exportCsv() {
    const header = '公司,股票代码,所属行业,财务评分,营收增速,净利润增速,ROE,毛利率变化,经营现金流,PE分位'
    const csvRows = rows.map((row) => [row.name, row.code, row.industry, row.score, `${row.revenueYoy}%`, `${row.profitYoy}%`, `${row.roe}%`, `${row.grossMarginChange}pct`, `${row.cashFlow}%`, `${row.pePercentile}%`].join(','))
    const url = URL.createObjectURL(new Blob([`${header}\n${csvRows.join('\n')}`], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a'); link.href = url; link.download = 'stock_picker_financial_20260919_H1.csv'; link.click(); URL.revokeObjectURL(url)
  }

  const sortedRows = [...rows].sort((left, right) => {
    const difference = right[sortKey] - left[sortKey]
    return sortDirection === 'desc' ? difference : -difference
  })
  const matchedCount = submitted ? rows.length : 86

  return <div className="app-shell stock-picker-shell">
    <TopBar activeSection="picker" onMenu={() => setSidebarOpen((open) => !open)} onSelect={() => undefined} />
    <div className="stock-picker-layout">
      <aside className={`picker-sidebar ${sidebarOpen ? 'open' : ''}`} aria-label="选股筛选器">
        <div className="sidebar-title">筛选器</div>
        <section className="saved-screen"><strong>优质盈利增长</strong><p>高 ROE、收入与利润增长，同时控制估值与负债风险。</p></section>
        <section className="filter-group"><h2>盈利质量</h2><ToggleField label="ROE ≥ 10%" checked={filters.roe} onChange={() => setFilters((current) => ({ ...current, roe: !current.roe }))} /><ToggleField label="毛利率同比改善" checked={filters.grossMargin} onChange={() => setFilters((current) => ({ ...current, grossMargin: !current.grossMargin }))} /><ToggleField label="经营现金流为正" checked={filters.cashFlow} onChange={() => setFilters((current) => ({ ...current, cashFlow: !current.cashFlow }))} /></section>
        <section className="filter-group"><h2>成长性</h2><ThresholdField label="营收增速" value={filters.revenueYoy} max={30} onChange={(value) => updateFilter('revenueYoy', value)} /><ThresholdField label="净利润增速" value={filters.profitYoy} max={30} onChange={(value) => updateFilter('profitYoy', value)} /></section>
        <section className="filter-group"><h2>估值与风险</h2><ThresholdField label="PE 分位低于" value={filters.pePercentile} max={100} onChange={(value) => updateFilter('pePercentile', value)} /><ToggleField label="资产负债率 ≤ 60%" checked={filters.cashFlow} onChange={() => setFilters((current) => ({ ...current, cashFlow: !current.cashFlow }))} /></section>
        <section className="filter-group range-group"><h2>数据范围</h2><label>报告期<select defaultValue="2026 H1"><option>2026 H1</option><option>2025 FY</option><option>2025 H1</option></select></label><label>市场<select defaultValue="all"><option value="all">沪深 A 股</option><option value="sh">沪市</option><option value="sz">深市</option></select></label><label>选股日期<input type="date" defaultValue="2026-09-19" max="2026-09-19" /></label><label>SW 行业<select defaultValue="all"><option value="all">全部行业</option><option>电力设备</option><option>家用电器</option><option>医疗器械</option><option>食品饮料</option></select></label></section>
        <button type="button" className="sidebar-run" onClick={updateResults}>{submitted ? '已更新结果' : '更新结果'} <b>↗</b></button>
      </aside>
      {sidebarOpen && <button className="sidebar-backdrop" aria-label="关闭筛选器" onClick={() => setSidebarOpen(false)} />}
      <main className="picker-workspace"><div className="picker-crumb">发现 <b>/</b> 因子筛选 <b>/</b> <strong>财务表现</strong></div><div className="picker-heading"><div><h1>财务表现选股</h1><p>从盈利质量、成长性与财务安全性中筛出值得深入研究的公司。</p></div><button type="button" className="run-results" onClick={updateResults}>{submitted ? '结果已更新' : '更新结果'}</button></div>
        <section className="result-summary"><div><label>符合条件</label><b>{matchedCount} <i>只</i></b></div><div><label>覆盖公司</label><b>5,214 <i>只</i></b></div><div><label>最近更新</label><b>08-17 <i>2026</i></b></div></section>
        <div className="result-toolbar"><div><h2>筛选结果 <span>按{sortKey === 'score' ? '综合财务评分' : sortKey === 'revenueYoy' ? '营收增速' : sortKey === 'profitYoy' ? '净利润增速' : sortKey === 'roe' ? 'ROE' : 'PE 分位'}{sortDirection === 'desc' ? '降序' : '升序'}</span></h2></div><div className="view-switch"><button className="active" type="button">财务表现</button><button type="button" disabled title="估值视图尚未接入">估值</button><button type="button" disabled title="技术面视图尚未接入">技术面</button></div></div>
        <section className="financial-table-card"><div className="table-actions"><label>排序<select value={sortKey} onChange={(event) => updateSort(event.target.value as SortKey)}><option value="score">财务评分</option><option value="revenueYoy">营收增速</option><option value="profitYoy">净利润增速</option><option value="roe">ROE</option><option value="pePercentile">PE 分位</option></select></label><button type="button" className="sort-direction" onClick={toggleSortDirection}>{sortDirection === 'desc' ? '↓ 从高到低' : '↑ 从低到高'}</button><button type="button" className="export-button" onClick={exportCsv}>↓ 导出 CSV</button></div><div className="financial-table-wrap"><table><thead><tr><th scope="col">公司</th><th scope="col">所属行业</th><th scope="col">财务评分</th><th scope="col">营收增速</th><th scope="col">净利润增速</th><th scope="col">ROE</th><th scope="col">毛利率变化</th><th scope="col">经营现金流</th><th scope="col">PE 分位</th></tr></thead><tbody>{sortedRows.map((row) => <tr key={row.code}><td><a href={`/?ts_code=${row.code}&tab=fundamentals&picker=financial`}>{row.name}</a><code>{row.code}</code></td><td className="sector">{row.industry}</td><td><span className={`financial-score ${row.score < 80 ? 'watch' : ''}`}>{row.score}</span></td><td className="positive">+{row.revenueYoy}%</td><td className="positive">+{row.profitYoy}%</td><td>{row.roe}%</td><td className={row.grossMarginChange < 0 ? 'negative' : 'positive'}>{row.grossMarginChange > 0 ? '+' : ''}{row.grossMarginChange}pct</td><td className="positive">+{row.cashFlow}%</td><td>{row.pePercentile}%</td></tr>)}</tbody></table></div><p className="result-note">评分由盈利质量、成长质量、现金流与资产负债表四类指标加权计算；点击公司可进入个股研究档案。</p><div className="picker-pagination"><span>命中总数：{matchedCount} <i /> 当前范围：{page === 1 ? '1-6' : '7-12'}</span><div><button type="button" disabled={page === 1} onClick={() => setPage(1)}>‹</button><button type="button" className={page === 1 ? 'current' : ''} onClick={() => setPage(1)}>1</button><button type="button" className={page === 2 ? 'current' : ''} onClick={() => setPage(2)}>2</button><button type="button" disabled={page === 2} onClick={() => setPage(2)}>›</button></div></div></section>
      </main>
    </div>
  </div>
}

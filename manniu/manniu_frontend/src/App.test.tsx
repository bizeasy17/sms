import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import App from './App'
import { ModuleStateNotice } from './features/research/components/ModuleStateNotice'

beforeEach(() => {
  window.history.replaceState({}, '', '/')
  const items = [
    { ts_code: '002236.SZ', name: '大华股份', sw_industry: { name: '计算机设备' }, market: { pct_change: 1.84 }, traditional_valuation: { action: 'BUY', undervalue_score: 82 }, predictive_valuation: { action: 'BUY', undervalue_score: 61.5 } },
    { ts_code: '600519.SH', name: '贵州茅台', sw_industry: { name: '白酒' }, market: { pct_change: -0.62 }, traditional_valuation: { action: 'BUY', undervalue_score: 74 }, predictive_valuation: { action: 'HOLD', undervalue_score: 58 } },
    { ts_code: '300750.SZ', name: '宁德时代', sw_industry: { name: '电池' }, market: { pct_change: 2.17 }, traditional_valuation: { action: 'SELL', undervalue_score: 69 }, predictive_valuation: { action: 'BUY', undervalue_score: 63 } },
    { ts_code: '688981.SH', name: '中芯国际', sw_industry: { name: '半导体' }, market: { pct_change: -1.05 }, traditional_valuation: {}, predictive_valuation: {} },
  ]
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
    const url = new URL(String(input), window.location.origin)
    if (url.pathname.includes('/valuations/traditional')) return Promise.resolve(new Response(JSON.stringify({ data: { current_price: 24.68, summary: { conservative_valuation_price_optimized: 20.4, composite_valuation_price_optimized: 26.8, traditional_tiered_template: { aggressive: { target_price: 34.6 } }, buy_candidate: true, undervalue_score: 97 }, risk: { confidence: 72, risk_level: 'MEDIUM' }, methods: [{ valuation_method: 'pe', valuation_price: 25.1, deviation_pct: 1.7 }, { valuation_method: 'fcff_dcf', valuation_price: 28.4, deviation_pct: 15.1 }, { valuation_method: 'ddm', available: false, skip_reason: 'dividend_unavailable' }] } }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    if (url.pathname.includes('/valuations/predictive')) return Promise.resolve(new Response(JSON.stringify({ data: { asof_date: '2026-09-17', action: 'BUY', signal_score: 82.5, risk_level: 'LOW', target_price: { low: 22.4, center: 28.6, high: 35.2 }, predictive_tiered_template: { conservative: { target_price_low: 21.2, target_price_high: 25.4, risk_level: 'MEDIUM' }, balanced: { target_price_low: 24.8, target_price: 28.6, risk_level: 'LOW' }, aggressive: { target_price_low: 28.6, target_price_high: 35.2, risk_level: 'HIGH' } } } }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    if (url.pathname.includes('/financials/overview')) return Promise.resolve(new Response(JSON.stringify({ data: { metrics: { net_profit: { key: 'net_profit', available: true }, ebit: { key: 'ebit', available: true }, net_margin: { key: 'net_margin', available: true }, debt_to_assets: { key: 'debt_to_assets', available: true } } } }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    if (url.pathname.includes('/market-evidence')) return Promise.resolve(new Response(JSON.stringify({ data: { security: { ts_code: '002236.SZ', name: '大华股份' }, industry: { name: '计算机设备', index_code: '801081.SI' }, history: [{ trade_date: '2026-09-15', close: 23.8, industry_close: 1200 }, { trade_date: '2026-09-16', close: 24.1, industry_close: 1210 }, { trade_date: '2026-09-17', close: 24.68, industry_close: 1220 }], summary: { atr_14: 1.16, atr_14_percentile_60d: 50, ma25: 23.8, ma25_trend: 'UP', ma200: 21.4, ma200_trend: 'UP', current_price: 24.68, price_to_ma25: 1.03, relative_strength_vs_industry: 0.045 }, returned_days: 3, warnings: [] } }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    if (url.pathname.includes('/technical-trend')) return Promise.resolve(new Response(JSON.stringify({ data: { security: { ts_code: '002236.SZ', name: '大华股份' }, series: [{ trade_date: '2026-09-17', open: 24.1, high: 25.2, low: 23.8, close: 24.68, volume: 58, ma25: 23.8, ma200: 21.4 }], momentum: { latest: { rsi14: 61.8, macd_histogram: 0.42, atr14: 1.16 } }, summary: { trend: 'UP', trend_score: 72, trend_level: 'MODERATE', volatility_status: 'NORMAL', data_status: 'COMPLETE' }, relative_strength: { name: '计算机设备', relative_strength: 0.045, direction: 'UP', status: 'COMPLETE' }, market_sentiment: { status: 'VALID', score: 64, level: 'HIGH', source_trade_date: '2026-09-17' }, signals: [{ trade_date: '2026-09-17', type: 'MA_CROSS', direction: 'UP', evidence: 'MA6 上穿 MA25', status: 'CONFIRMED' }], warnings: [], rule_version: 'technical_rule_v1', adjust: 'qfq', frequency: 'D', period: 60 } }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    if (url.pathname.includes('/bars')) return Promise.resolve(new Response(JSON.stringify({ data: [{ trade_date: '2026-09-17', open: 24.1, high: 25.2, low: 23.8, close: 24.68, volume: 58, change: 0.45, pct_change: 1.84 }] }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    if (url.pathname.includes('/chips')) return Promise.resolve(new Response(JSON.stringify({ data: [{ trade_date: '2026-09-17', price: 24.5, percent: 12.5 }, { trade_date: '2026-09-17', price: 25, percent: 20 }] }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    const market = url.searchParams.get('market')
    const data = market === 'cyb' ? items.filter((item) => item.ts_code.startsWith('300')) : items
    return Promise.resolve(new Response(JSON.stringify({ data }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
  }))
})
afterEach(() => { cleanup() })

test('renders the research workspace with the selected stock', async () => {
  render(<App />)
  expect(await screen.findByRole('heading', { name: '大华股份' })).toBeTruthy()
  expect((await screen.findAllByText('风险级别')).length).toBe(2)
  expect(screen.getByText('97')).toBeTruthy()
  expect(screen.getByRole('heading', { name: '买入候选' })).toBeTruthy()
  expect(screen.queryByText(/已覆盖/)).toBeNull()
  expect(screen.getByRole('heading', { name: '买入候选' })).toBeTruthy()
  expect(screen.getByRole('heading', { name: '买入' })).toBeTruthy()
  expect(screen.getByRole('heading', { name: '价值估值摘要' })).toBeTruthy()
  expect(screen.getByRole('heading', { name: '模型估值摘要' })).toBeTruthy()
  expect(screen.getByText('01.1 / FUNDAMENTAL VALUATION')).toBeTruthy()
  expect(screen.getByText('01.2 / MODEL VALUATION')).toBeTruthy()
  expect(screen.queryByText('模型估值')).toBeNull()
  expect(screen.getAllByText('CURRENT VIEW')).toHaveLength(2)
  expect(screen.getByRole('heading', { name: '市场证据' })).toBeTruthy()
  expect(screen.getByText('净利润')).toBeTruthy()
  expect(screen.getByText('EBIT')).toBeTruthy()
  expect(screen.getByText('净利率')).toBeTruthy()
  expect(screen.getByText('负债率')).toBeTruthy()
  expect(document.querySelectorAll('.range-bar')).toHaveLength(2)
  expect(document.querySelectorAll('.valuation-methods .method-list > div')).toHaveLength(3)
  expect(document.querySelectorAll('.predictive-tier-row')).toHaveLength(3)
  expect(screen.getByText('83')).toBeTruthy()
  expect(screen.getByText('¥21.20 - ¥25.40')).toBeTruthy()
})

test('switches stock and exposes research tabs from the API list', async () => {
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: /贵州茅台/ }))
  expect(screen.getAllByText('600519.SH').length).toBeGreaterThan(0)
  expect(screen.getByRole('button', { name: '技术趋势' })).toBeTruthy()
})

test('renders the technical trend workspace without valuation conclusions', async () => {
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: '技术趋势' }))
  expect(await screen.findByRole('heading', { name: '技术趋势' })).toBeTruthy()
  expect(screen.getByText('价格趋势与筹码')).toBeTruthy()
  expect(await screen.findByText('筹码分布 · 2026-09-17')).toBeTruthy()
  expect(screen.getByText('12.50%')).toBeTruthy()
  expect(screen.getByText('获胜率')).toBeTruthy()
  expect(screen.getByText('筹码集中率')).toBeTruthy()
  const concentration = document.querySelector('.chip-foot strong')?.textContent ?? ''
  expect(concentration).toBe('2')
  const chipMetrics = [...document.querySelectorAll('.chip-panel-metrics strong')].map((item) => item.textContent ?? '')
  expect(chipMetrics).toHaveLength(2)
  chipMetrics.forEach((value) => {
    expect(value).toMatch(/^\d+(\.\d+)?%$/)
    expect(Number.parseFloat(value)).toBeGreaterThanOrEqual(0)
    expect(Number.parseFloat(value)).toBeLessThanOrEqual(100)
  })
  expect(screen.queryByText('CYQ_CHIPS · 后台数据')).toBeNull()
  expect(screen.getByText('动量指标')).toBeTruthy()
  expect(screen.getByText('行业相对强度')).toBeTruthy()
  expect(screen.getByText('价值估值摘要').closest('[hidden]')).toBeTruthy()
  expect(screen.getByText('买入候选').closest('[hidden]')).toBeTruthy()
})

test('renders backend research tags and filters stocks by board', async () => {
  render(<App />)
  await screen.findByRole('heading', { name: '大华股份' })
  const tags = [...document.querySelectorAll('.stock-tags i')]
  expect(tags.some((tag) => tag.textContent?.includes('价值 - ') && tag.textContent.includes('82分'))).toBe(true)
  expect(tags.some((tag) => tag.textContent?.includes('模型 - ') && tag.textContent.includes('62分'))).toBe(true)
  expect(tags.some((tag) => tag.textContent?.includes('模型 - ') && tag.textContent.includes('58分'))).toBe(true)
  expect(tags.some((tag) => tag.textContent?.includes('价值 - ') && tag.textContent.includes('69分'))).toBe(true)
  expect(document.querySelector('.tag-action.buy')?.textContent).toBe('买')
  expect(document.querySelector('.tag-action.hold')?.textContent).toBe('持')
  expect(document.querySelector('.tag-action.sell')?.textContent).toBe('卖')

  fireEvent.change(screen.getByRole('combobox', { name: '市场筛选' }), { target: { value: 'cyb' } })
  expect(await screen.findByRole('button', { name: /宁德时代/ })).toBeTruthy()
  expect(screen.queryByRole('button', { name: /大华股份/ })).toBeNull()
})

test('renders one empty label when valuation data is unavailable', async () => {
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: /中芯国际/ }))
  expect(screen.getAllByText('价值 - 暂无')).toHaveLength(1)
  expect(screen.getAllByText('模型 - 暂无')).toHaveLength(1)
  expect(screen.queryByText(/暂无分数/)).toBeNull()
})

test('keeps login route available', () => {
  window.history.replaceState({}, '', '/login')
  render(<App />)
  expect(screen.getByRole('heading', { name: '登录 API Lab' })).toBeTruthy()
})

test('exposes a retryable error state for research modules', () => {
  const retry = () => undefined
  render(<ModuleStateNotice state="error" label="估值摘要" onRetry={retry} />)
  expect(screen.getByRole('alert')).toBeTruthy()
  expect(screen.getByText('估值摘要暂时不可用，请稍后重试')).toBeTruthy()
  expect(screen.getByRole('button', { name: '重试' })).toBeTruthy()
})

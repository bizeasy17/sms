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
    const market = new URL(String(input), window.location.origin).searchParams.get('market')
    const data = market === 'cyb' ? items.filter((item) => item.ts_code.startsWith('300')) : items
    return Promise.resolve(new Response(JSON.stringify({ data }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
  }))
})
afterEach(() => { cleanup() })

test('renders the research workspace with the selected stock', async () => {
  render(<App />)
  expect(await screen.findByRole('heading', { name: '大华股份' })).toBeTruthy()
  expect(screen.queryByText(/已覆盖/)).toBeNull()
  expect(screen.getAllByRole('heading', { name: '中性持有' })).toHaveLength(2)
  expect(screen.getByRole('heading', { name: '基本面估值摘要' })).toBeTruthy()
  expect(screen.getByRole('heading', { name: '模型估值摘要' })).toBeTruthy()
  expect(screen.getByText('01.1 / FUNDAMENTAL VALUATION')).toBeTruthy()
  expect(screen.getByText('01.2 / MODEL VALUATION')).toBeTruthy()
  expect(screen.queryByText('模型估值')).toBeNull()
  expect(screen.getAllByText('CURRENT VIEW')).toHaveLength(2)
  expect(screen.getByText('14日波动率')).toBeTruthy()
  expect(screen.getByText('净利润')).toBeTruthy()
  expect(screen.getByText('EBIT')).toBeTruthy()
  expect(screen.getByText('净利率')).toBeTruthy()
  expect(screen.getByText('负债率')).toBeTruthy()
  expect(document.querySelectorAll('.range-bar')).toHaveLength(2)
  expect(document.querySelectorAll('.valuation-methods .method-list > div')).toHaveLength(6)
  expect(document.querySelectorAll('.percentile-line')).toHaveLength(3)
})

test('switches stock and exposes research tabs from the API list', async () => {
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: /贵州茅台/ }))
  expect(screen.getAllByText('600519.SH').length).toBeGreaterThan(0)
  expect(screen.getByRole('button', { name: '技术趋势' })).toBeTruthy()
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

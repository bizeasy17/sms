import type { FinancialMetric, Market, Pool, Stock, StockQuote, StockTag, TagAction, TraditionalValuation, TraditionalValuationMethod } from '../types'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

type ResearchListItem = {
    ts_code: string
    name: string
    sw_industry?: { name?: string }
    market?: { pct_change?: number | null }
    traditional_valuation?: { action?: string | null; undervalue_score?: number | null }
    predictive_valuation?: { action?: string | null; undervalue_score?: number | null }
}

type ResearchListResponse = { data?: ResearchListItem[]; error?: { message?: string } }
type Bar = { trade_date?: string; close?: number | null; change?: number | null; pct_change?: number | null }
type BarsResponse = { data?: Bar[]; error?: { message?: string } }
type FinancialOverviewResponse = { data?: { period?: string | null; metrics?: Record<string, FinancialMetricResponse> }; error?: { message?: string } }
type FinancialMetricResponse = { key?: string; value?: number | null; yoy?: number | null; yoy_unit?: 'ratio' | 'percentage_points'; rolling12?: number | null; rolling12_unit?: string; period?: string | null; source_dataset?: string; available?: boolean }
type ValuationResult = { action?: string | null; undervalue_score?: number | null }
type TraditionalValuationResponse = { current_price?: number | null; asof_date?: string | null; summary?: Record<string, unknown>; risk?: { confidence?: number | null; risk_level?: string | null }; source_trade_date?: string | null; methods?: Array<Record<string, unknown>> }

function actionLabel(action?: string | null) {
    if (action === 'BUY') return '买'
    if (action === 'HOLD') return '持'
    if (action === 'SELL') return '卖'
    return '暂无'
}

function tagAction(action?: string | null): TagAction {
    return action === 'BUY' || action === 'SELL' || action === 'HOLD' ? action : null
}

function scoreLabel(score?: number | null) {
    return typeof score === 'number' && Number.isFinite(score) ? `${Math.round(score)}分` : null
}

function valuationTag(label: string, valuation?: ValuationResult): StockTag {
    if (!valuation || (valuation.action == null && valuation.undervalue_score == null)) return { text: `${label} - 暂无`, label: `${label} - 暂无`, action: null }
    const parts: string[] = []
    if (valuation.action != null) parts.push(actionLabel(valuation.action))
    const score = scoreLabel(valuation.undervalue_score)
    if (score != null) parts.push(score)
    return {
        text: parts.length ? `${label} - ${parts.join(' · ')}` : `${label} - 暂无`,
        label: `${label} - `,
        action: tagAction(valuation.action),
        actionText: valuation.action != null ? actionLabel(valuation.action) : undefined,
        scoreText: score ?? undefined,
    }
}

function mapStock(item: ResearchListItem): Stock {
    const change = item.market?.pct_change
    return {
        code: item.ts_code,
        name: item.name,
        market: item.ts_code.split('.')[1] ?? '',
        industry: item.sw_industry?.name || '暂无行业',
        tags: [
            valuationTag('价值', item.traditional_valuation),
            valuationTag('模型', item.predictive_valuation),
        ],
        change: typeof change === 'number' ? `${change >= 0 ? '+' : ''}${change.toFixed(2)}%` : '暂无涨跌',
        positive: typeof change === 'number' ? change > 0 : null,
    }
}

export async function fetchResearchList(pool: Pool, market: Market, signal?: AbortSignal): Promise<Stock[]> {
    const query = new URLSearchParams({ pool, market, page: '1', page_size: '200' })
    const accessToken = window.localStorage.getItem('access_token') ?? window.localStorage.getItem('auth_access_token')
    const headers: HeadersInit = { Accept: 'application/json' }
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`
    const response = await fetch(`${API_BASE}/market-analysis/securities/research-list?${query}`, { headers, signal })
    const body = await response.json() as ResearchListResponse
    if (!response.ok || !Array.isArray(body.data)) throw new Error(body.error?.message ?? '股票池加载失败，请稍后重试。')
    return body.data.map(mapStock)
}

function dateString(date: Date) {
    return date.toISOString().slice(0, 10)
}

export async function fetchLatestStockQuote(tsCode: string, signal?: AbortSignal): Promise<StockQuote | null> {
    const endDate = new Date()
    const startDate = new Date(endDate)
    startDate.setFullYear(startDate.getFullYear() - 1)
    const query = new URLSearchParams({
        start_date: dateString(startDate),
        end_date: dateString(endDate),
        adjust: 'qfq',
        frequency: 'D',
        page: '1',
        page_size: '200',
    })
    const accessToken = window.localStorage.getItem('access_token') ?? window.localStorage.getItem('auth_access_token')
    const headers: HeadersInit = { Accept: 'application/json' }
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`
    const response = await fetch(`${API_BASE}/market-analysis/securities/${encodeURIComponent(tsCode)}/bars?${query}`, { headers, signal })
    const body = await response.json() as BarsResponse
    if (!response.ok || !Array.isArray(body.data)) throw new Error(body.error?.message ?? '行情加载失败，请稍后重试。')
    const latest = [...body.data].sort((left, right) => (right.trade_date ?? '').localeCompare(left.trade_date ?? ''))[0]
    if (!latest?.trade_date) return null
    return { tradeDate: latest.trade_date, close: latest.close ?? null, change: latest.change ?? null, pctChange: latest.pct_change ?? null }
}

export async function fetchFinancialOverview(tsCode: string, signal?: AbortSignal): Promise<Record<string, FinancialMetric>> {
    const query = new URLSearchParams({ asof_date: dateString(new Date()), report_type: 'LATEST' })
    const accessToken = window.localStorage.getItem('access_token') ?? window.localStorage.getItem('auth_access_token')
    const headers: HeadersInit = { Accept: 'application/json' }
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`
    const response = await fetch(`${API_BASE}/market-analysis/securities/${encodeURIComponent(tsCode)}/financials/overview?${query}`, { headers, signal })
    const body = await response.json() as FinancialOverviewResponse
    if (!response.ok || !body.data?.metrics) throw new Error(body.error?.message ?? '基本面数据加载失败，请稍后重试。')
    return Object.fromEntries(Object.entries(body.data.metrics).map(([key, metric]) => [key, {
        key: metric.key ?? key,
        value: metric.value ?? null,
        yoy: metric.yoy ?? null,
        yoyUnit: metric.yoy_unit ?? 'ratio',
        rolling12: metric.rolling12 ?? null,
        rolling12Unit: metric.rolling12_unit ?? '',
        period: metric.period ?? body.data?.period ?? null,
        sourceDataset: metric.source_dataset ?? '',
        available: metric.available === true,
    }]))
}

function numberField(row: Record<string, unknown>, ...keys: string[]) {
    const value = keys.map((key) => row[key]).find((candidate) => typeof candidate === 'number')
    return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function methodLabel(name: string) {
    const labels: Record<string, string> = { pe: 'PE 估值', pb: 'PB 估值', ps: 'PS 估值', peg: 'PEG 估值', fcff_dcf: 'FCFF 模型', ddm: 'DDM 模型', ev_ebitda: 'EV/EBITDA', sw_history: '行业历史估值', market_cap: '市值估值' }
    return labels[name] ?? name.replace(/_/g, ' ')
}

function mapTraditionalMethod(row: Record<string, unknown>): TraditionalValuationMethod {
    const name = String(row.valuation_method ?? '')
    const valuationPrice = numberField(row, 'valuation_price', 'implied_price', 'target_price', 'fair_value', 'price')
    const available = row.available !== false && valuationPrice != null
    const deviation = numberField(row, 'deviation_pct', 'premium_pct', 'return_pct')
    const judgment = typeof row.judgment === 'string' ? row.judgment : typeof row.status === 'string' ? row.status : ''
    const note = !available ? '暂不可用' : deviation != null ? `${deviation >= 0 ? '+' : ''}${deviation.toFixed(1)}%${judgment ? ` · ${judgment}` : ''}` : judgment
    return { valuationMethod: methodLabel(name), valuationPrice, note, available }
}

export async function fetchTraditionalValuation(tsCode: string, signal?: AbortSignal): Promise<TraditionalValuation> {
    const query = new URLSearchParams({ asof_date: dateString(new Date()), include_methods: 'true', include_risk: 'true' })
    const accessToken = window.localStorage.getItem('access_token') ?? window.localStorage.getItem('auth_access_token')
    const headers: HeadersInit = { Accept: 'application/json' }
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`
    const response = await fetch(`${API_BASE}/market-analysis/securities/${encodeURIComponent(tsCode)}/valuations/traditional?${query}`, { headers, signal })
    const body = await response.json() as { data?: TraditionalValuationResponse; error?: { message?: string } }
    if (!response.ok || !body.data) throw new Error(body.error?.message ?? '传统估值加载失败，请稍后重试。')
    const data = body.data
    const summary = data.summary ?? {}
    const tiered = summary.traditional_tiered_template as { aggressive?: { target_price?: number | null } } | undefined
    return { currentPrice: data.current_price ?? null, conservativePrice: numberField(summary, 'conservative_valuation_price_optimized', 'conservative_valuation_price_raw', 'conservative_valuation_price'), centerPrice: numberField(summary, 'composite_valuation_price_optimized', 'composite_valuation_price_raw', 'composite_valuation_price'), optimisticPrice: tiered?.aggressive?.target_price ?? numberField(summary, 'optimistic_valuation_price', 'optimistic_price', 'upper_valuation_price'), confidence: data.risk?.confidence ?? null, undervalueScore: numberField(summary, 'undervalue_score'), buyCandidate: typeof summary.buy_candidate === 'boolean' ? summary.buy_candidate : null, riskLevel: data.risk?.risk_level ?? null, asofDate: data.asof_date ?? null, sourceTradeDate: data.source_trade_date ?? null, methods: (data.methods ?? []).map(mapTraditionalMethod) }
}
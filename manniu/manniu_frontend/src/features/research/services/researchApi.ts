import type { FinancialOverview, FundamentalDimension, FundamentalEvaluation, Market, MarketEvidence, MarketEvidenceHistory, PersonalStockState, Pool, PredictiveTier, PredictiveValuation, SecurityEvent, Stock, StockQuote, StockSentiment, StockTag, TagAction, TechnicalBar, TechnicalChip, TechnicalTrend, TraditionalValuation, TraditionalValuationMethod } from '../types'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

type ResearchListItem = {
    ts_code: string
    name: string
    sw_industry?: { name?: string }
    market?: { pct_change?: number | null }
    traditional_valuation?: { action?: string | null; undervalue_score?: number | null }
    predictive_valuation?: { action?: string | null; undervalue_score?: number | null }
}
type SecurityDetailResponse = { data?: { ts_code?: string; name?: string; industry?: string | null }; error?: { message?: string } }
type ResearchListResponse = { data?: ResearchListItem[]; error?: { message?: string } }
type Bar = { trade_date?: string; open?: number | null; high?: number | null; low?: number | null; close?: number | null; volume?: number | null; change?: number | null; pct_change?: number | null }
type BarsResponse = { data?: Bar[]; error?: { message?: string } }
type SecurityEventItem = { event_type?: string; source_system?: string; source_event_key?: string; event_date?: string; source_trade_date?: string | null; payload?: Record<string, unknown>; status?: string }
type SecurityEventsResponse = { data?: { items?: SecurityEventItem[] }; error?: { message?: string } }
type TechnicalTrendResponse = { data?: { security?: { ts_code?: string; name?: string }; series?: Array<Bar & { ma25?: number | null; ma200?: number | null }>; momentum?: { latest?: { rsi14?: number | null; macd_histogram?: number | null; atr14?: number | null } }; summary?: { trend?: string | null; trend_score?: number | null; trend_level?: string | null; volatility_status?: string | null; data_status?: string }; relative_strength?: { name?: string | null; relative_strength?: number | null; direction?: string | null; status?: string }; market_sentiment?: { status?: string; score?: number | null; level?: string | null; source_trade_date?: string | null }; signals?: Array<{ trade_date?: string; type?: string; direction?: string; evidence?: string; status?: string }>; warnings?: string[]; rule_version?: string; adjust?: string; frequency?: string; period?: number }; error?: { message?: string } }
type StockSentimentResponse = { data?: { ts_code?: string; trade_date?: string; score?: number | null; level?: string | null; status?: string; source_trade_date?: string | null; momentum?: number | null; activity?: number | null; fear?: number | null; coverage?: number | null; sample_count?: number; engine_version?: string }; error?: { message?: string } }
type ChipsResponse = { data?: Array<{ trade_date?: string; price?: number | null; percent?: number | null }>; error?: { message?: string } }
type MarketEvidenceResponse = { data?: { security?: { ts_code?: string; name?: string }; industry?: { index_code?: string | null; industry_code?: string | null; name?: string | null }; history?: Array<{ trade_date?: string; open?: number | null; high?: number | null; low?: number | null; close?: number | null; industry_close?: number | null }>; summary?: { atr_14?: number | null; atr_14_percentile_60d?: number | null; ma25?: number | null; ma25_trend?: string | null; ma200?: number | null; ma200_trend?: string | null; current_price?: number | null; price_to_ma25?: number | null; relative_strength_vs_industry?: number | null }; requested_days?: number; returned_days?: number; warnings?: string[] }; error?: { message?: string } }
type FinancialOverviewResponse = { data?: { period?: string | null; report_type?: string; metrics?: Record<string, FinancialMetricResponse>; evaluation?: FinancialEvaluationResponse | null; source_dates?: Record<string, string>; warnings?: string[] }; meta?: { warnings?: string[] }; error?: { message?: string } }
type FinancialMetricResponse = { key?: string; value?: number | null; yoy?: number | null; yoy_unit?: 'ratio' | 'percentage_points'; rolling12?: number | null; rolling12_unit?: string; period?: string | null; source_dataset?: string; available?: boolean }
type FinancialDimensionResponse = { score?: number | null; status?: string; available?: boolean; evidence?: string[]; missing_metrics?: string[] }
type FinancialEvaluationResponse = { evaluation_version?: string; overall?: { score?: number | null; status?: string; available_weight?: number; missing_dimensions?: string[] }; dimensions?: Record<string, FinancialDimensionResponse>; trend?: Array<{ period?: string | null; source_period?: string | null; overall?: FinancialEvaluationResponse['overall']; dimensions?: Record<string, FinancialDimensionResponse> }>; reports?: Array<{ period?: string; report_type?: string | null; end_date?: string; ann_date?: string | null; effective_date?: string | null; data_status?: string; source_revision?: string | null }>; signals?: Array<{ signal_code?: string; label?: string; severity?: string; status?: string; asof_date?: string | null; evidence?: string; metrics?: string[]; provenance?: Record<string, unknown> }>; warnings?: string[] }
type ValuationResult = { action?: string | null; undervalue_score?: number | null }
type TraditionalValuationResponse = { current_price?: number | null; asof_date?: string | null; summary?: Record<string, unknown>; risk?: { confidence?: number | null; risk_level?: string | null }; source_trade_date?: string | null; methods?: Array<Record<string, unknown>> }
type PredictiveValuationResponse = { action?: string | null; signal_score?: number | null; risk_level?: string | null; asof_date?: string | null; target_price?: Record<string, unknown> | number | null; predictive_tiered_template?: Record<string, unknown> }
type PersonalItem = { id: number; security?: { ts_code?: string } }
type PersonalListResponse = { data?: { items?: PersonalItem[] }; error?: { message?: string } }
type PersonalItemResponse = { data?: PersonalItem; error?: { message?: string } }
type Portfolio = { id: number; is_default?: boolean; archived_at?: string | null }
type PortfolioResponse = { data?: { items?: Portfolio[] }; error?: { message?: string } }
type Position = { id: number; security?: { ts_code?: string } }

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

function mapSecurityDetail(item: NonNullable<SecurityDetailResponse['data']>, code: string): Stock {
    return {
        code: item.ts_code ?? code,
        name: item.name ?? code,
        market: (item.ts_code ?? code).split('.')[1] ?? '',
        industry: item.industry || '暂无行业',
        tags: [valuationTag('价值'), valuationTag('模型')],
        change: '暂无涨跌',
        positive: null,
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

export async function fetchSecurityByCode(tsCode: string, signal?: AbortSignal): Promise<Stock> {
    const accessToken = window.localStorage.getItem('access_token') ?? window.localStorage.getItem('auth_access_token')
    const headers: HeadersInit = { Accept: 'application/json' }
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`
    const response = await fetch(`${API_BASE}/market-analysis/securities/${encodeURIComponent(tsCode)}`, { headers, signal })
    const body = await response.json() as SecurityDetailResponse
    if (!response.ok || !body.data) throw new Error(body.error?.message ?? '股票信息加载失败，请稍后重试。')
    return mapSecurityDetail(body.data, tsCode)
}

export async function fetchSecurityEvents(tsCode: string, signal?: AbortSignal): Promise<SecurityEvent[]> {
    const endDate = new Date()
    const startDate = new Date(endDate)
    startDate.setFullYear(startDate.getFullYear() - 1)
    const query = new URLSearchParams({ start_date: dateString(startDate), end_date: dateString(endDate), page: '1', page_size: '200' })
    const accessToken = window.localStorage.getItem('access_token') ?? window.localStorage.getItem('auth_access_token')
    const headers: HeadersInit = { Accept: 'application/json' }
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`
    const response = await fetch(`${API_BASE}/market-analysis/securities/${encodeURIComponent(tsCode)}/events?${query}`, { headers, signal })
    const body = await response.json() as SecurityEventsResponse
    if (!response.ok || !Array.isArray(body.data?.items)) throw new Error(body.error?.message ?? '研究事件加载失败，请稍后重试。')
    return body.data.items.filter((item): item is SecurityEventItem & Required<Pick<SecurityEventItem, 'event_type' | 'source_system' | 'source_event_key' | 'event_date'>> => Boolean(item.event_type && item.source_system && item.source_event_key && item.event_date)).map((item) => ({
        eventType: item.event_type as SecurityEvent['eventType'],
        sourceSystem: item.source_system,
        sourceEventKey: item.source_event_key,
        eventDate: item.event_date,
        sourceTradeDate: item.source_trade_date ?? null,
        payload: item.payload ?? {},
        status: item.status ?? 'COMMITTED',
    }))
}

function dateString(date: Date) {
    return date.toISOString().slice(0, 10)
}

function subtractWeekdays(date: Date, weekdays: number) {
    const result = new Date(date)
    let remaining = Math.max(0, Math.floor(weekdays))
    while (remaining > 0) {
        result.setDate(result.getDate() - 1)
        const day = result.getDay()
        if (day !== 0 && day !== 6) remaining -= 1
    }
    return result
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

function mapDimension(metric?: FinancialDimensionResponse): FundamentalDimension {
    return { score: metric?.score ?? null, status: metric?.status ?? 'NOT_AVAILABLE', available: metric?.available === true, evidence: metric?.evidence ?? [], missingMetrics: metric?.missing_metrics ?? [] }
}

function mapEvaluation(evaluation?: FinancialEvaluationResponse | null): FundamentalEvaluation | null {
    if (!evaluation) return null
    const mapOverall = (overall?: FinancialEvaluationResponse['overall']) => ({ score: overall?.score ?? null, status: overall?.status ?? 'NOT_AVAILABLE', availableWeight: overall?.available_weight ?? 0, missingDimensions: overall?.missing_dimensions ?? [] })
    return {
        evaluationVersion: evaluation.evaluation_version ?? 'unknown',
        overall: mapOverall(evaluation.overall),
        dimensions: Object.fromEntries(Object.entries(evaluation.dimensions ?? {}).map(([key, value]) => [key, mapDimension(value)])),
        trend: (evaluation.trend ?? []).map((item) => ({ period: item.period ?? null, sourcePeriod: item.source_period ?? item.period ?? null, overall: mapOverall(item.overall), dimensions: Object.fromEntries(Object.entries(item.dimensions ?? {}).map(([key, value]) => [key, mapDimension(value)])) })),
        reports: (evaluation.reports ?? []).filter((item) => item.period && item.end_date).map((item) => ({ period: item.period!, reportType: item.report_type ?? null, endDate: item.end_date!, annDate: item.ann_date ?? null, effectiveDate: item.effective_date ?? null, dataStatus: item.data_status ?? 'NOT_AVAILABLE', sourceRevision: item.source_revision ?? null })),
        signals: (evaluation.signals ?? []).filter((item) => item.signal_code && item.label).map((item) => ({ signalCode: item.signal_code!, label: item.label!, severity: item.severity ?? 'INFO', status: item.status ?? 'NOT_AVAILABLE', asofDate: item.asof_date ?? null, evidence: item.evidence ?? '', metrics: item.metrics ?? [], provenance: item.provenance ?? {} })),
        warnings: evaluation.warnings ?? [],
    }
}

export async function fetchFinancialOverview(tsCode: string, signal?: AbortSignal): Promise<FinancialOverview> {
    const query = new URLSearchParams({ asof_date: dateString(new Date()), report_type: 'LATEST' })
    const accessToken = window.localStorage.getItem('access_token') ?? window.localStorage.getItem('auth_access_token')
    const headers: HeadersInit = { Accept: 'application/json' }
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`
    const response = await fetch(`${API_BASE}/market-analysis/securities/${encodeURIComponent(tsCode)}/financials/overview?${query}`, { headers, signal })
    const body = await response.json() as FinancialOverviewResponse
    if (!response.ok || !body.data?.metrics) throw new Error(body.error?.message ?? '基本面数据加载失败，请稍后重试。')
    const metrics = Object.fromEntries(Object.entries(body.data.metrics).map(([key, metric]) => [key, {
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
    return { period: body.data.period ?? null, reportType: body.data.report_type ?? 'LATEST', metrics, evaluation: mapEvaluation(body.data.evaluation), sourceDates: body.data.source_dates ?? {}, warnings: [...(body.meta?.warnings ?? []), ...(body.data.warnings ?? [])] }
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

function mapPredictiveTier(value: unknown): PredictiveTier {
    const tier = value && typeof value === 'object' ? value as Record<string, unknown> : {}
    return { targetPrice: numberField(tier, 'target_price', 'center'), targetPriceLow: numberField(tier, 'target_price_low', 'low'), targetPriceHigh: numberField(tier, 'target_price_high', 'high'), riskLevel: typeof tier.risk_level === 'string' ? tier.risk_level : null }
}

export async function fetchPredictiveValuation(tsCode: string, signal?: AbortSignal): Promise<PredictiveValuation> {
    const query = new URLSearchParams({ asof_date: dateString(new Date()) })
    const accessToken = window.localStorage.getItem('access_token') ?? window.localStorage.getItem('auth_access_token')
    const headers: HeadersInit = { Accept: 'application/json' }
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`
    const response = await fetch(`${API_BASE}/market-analysis/securities/${encodeURIComponent(tsCode)}/valuations/predictive?${query}`, { headers, signal })
    const body = await response.json() as { data?: PredictiveValuationResponse; error?: { message?: string } }
    if (!response.ok || !body.data) throw new Error(body.error?.message ?? '模型估值加载失败，请稍后重试。')
    const data = body.data
    const target = data.target_price && typeof data.target_price === 'object' ? data.target_price : {}
    const template = data.predictive_tiered_template ?? {}
    const balance = template.balance ?? template.balanced
    return { action: data.action ?? null, signalScore: data.signal_score ?? null, riskLevel: data.risk_level ?? null, targetPrice: typeof data.target_price === 'number' ? data.target_price : numberField(target, 'center', 'target_price'), targetPriceLow: numberField(target, 'low', 'target_price_low'), targetPriceHigh: numberField(target, 'high', 'target_price_high'), asofDate: data.asof_date ?? null, tiers: { conservative: mapPredictiveTier(template.conservative), balance: mapPredictiveTier(balance), aggressive: mapPredictiveTier(template.aggressive) } }
}

export async function fetchMarketEvidence(tsCode: string, days = 60, signal?: AbortSignal): Promise<MarketEvidence> {
    const query = new URLSearchParams({ days: String(days) })
    const accessToken = window.localStorage.getItem('access_token') ?? window.localStorage.getItem('auth_access_token')
    const headers: HeadersInit = { Accept: 'application/json' }
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`
    const response = await fetch(`${API_BASE}/market-analysis/securities/${encodeURIComponent(tsCode)}/market-evidence?${query}`, { headers, signal })
    const body = await response.json() as MarketEvidenceResponse
    if (!response.ok || !body.data?.history || !body.data.summary) throw new Error(body.error?.message ?? '市场证据加载失败，请稍后重试。')
    const data = body.data
    const sourceHistory = data.history ?? []
    const sourceSummary = data.summary ?? {}
    const history: MarketEvidenceHistory[] = sourceHistory.map((row) => ({ tradeDate: row.trade_date ?? '', open: row.open ?? null, high: row.high ?? null, low: row.low ?? null, close: row.close ?? null, industryClose: row.industry_close ?? null })).filter((row) => row.tradeDate)
    return {
        security: { tsCode: data.security?.ts_code ?? tsCode, name: data.security?.name ?? tsCode },
        industry: { indexCode: data.industry?.index_code ?? null, industryCode: data.industry?.industry_code ?? null, name: data.industry?.name ?? null },
        history,
        summary: { atr14: sourceSummary.atr_14 ?? null, atr14Percentile60d: sourceSummary.atr_14_percentile_60d ?? null, ma25: sourceSummary.ma25 ?? null, ma25Trend: sourceSummary.ma25_trend ?? null, ma200: sourceSummary.ma200 ?? null, ma200Trend: sourceSummary.ma200_trend ?? null, currentPrice: sourceSummary.current_price ?? null, priceToMa25: sourceSummary.price_to_ma25 ?? null, relativeStrengthVsIndustry: sourceSummary.relative_strength_vs_industry ?? null },
        requestedDays: data.requested_days ?? days,
        returnedDays: data.returned_days ?? history.length,
        warnings: data.warnings ?? [],
    }
}

function personalHeaders(): HeadersInit {
    const token = window.localStorage.getItem('access_token') ?? window.localStorage.getItem('auth_access_token')
    return { Accept: 'application/json', 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) }
}

async function personalRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(`${API_BASE}${path}`, { ...init, headers: { ...personalHeaders(), ...init.headers } })
    const body = await response.json() as T & { error?: { message?: string } }
    if (!response.ok) throw new Error(body.error?.message ?? '个人股票状态操作失败，请稍后重试。')
    return body
}

export async function fetchPersonalStockState(tsCode: string, signal?: AbortSignal): Promise<PersonalStockState> {
    const [watchlist, observations, portfolios] = await Promise.all([
        personalRequest<PersonalListResponse>('/me/watchlist?limit=100', { signal }),
        personalRequest<PersonalListResponse>('/me/observations?limit=100', { signal }),
        personalRequest<PortfolioResponse>('/me/portfolios?limit=100', { signal }),
    ])
    const watch = watchlist.data?.items?.find((item) => item.security?.ts_code === tsCode)
    const observation = observations.data?.items?.find((item) => item.security?.ts_code === tsCode)
    const portfolio = portfolios.data?.items?.find((item) => item.is_default && !item.archived_at) ?? portfolios.data?.items?.find((item) => !item.archived_at)
    if (!portfolio) return { watched: Boolean(watch), watchlistId: watch?.id ?? null, holding: false, portfolioId: null, positionId: null, observed: Boolean(observation), observationId: observation?.id ?? null }
    const positions = await personalRequest<{ data?: { items?: Position[] } }>(`/me/portfolios/${portfolio.id}/positions?limit=100`, { signal })
    const position = positions.data?.items?.find((item) => item.security?.ts_code === tsCode)
    return { watched: Boolean(watch), watchlistId: watch?.id ?? null, holding: Boolean(position), portfolioId: portfolio.id, positionId: position?.id ?? null, observed: Boolean(observation), observationId: observation?.id ?? null }
}

export async function toggleWatchlist(tsCode: string, state: PersonalStockState): Promise<void> {
    if (state.watched && state.watchlistId != null) {
        await personalRequest(`/me/watchlist/${state.watchlistId}`, { method: 'DELETE' })
        return
    }
    await personalRequest<PersonalItemResponse>('/me/watchlist', { method: 'POST', body: JSON.stringify({ ts_code: tsCode }) })
}

export async function toggleObservation(tsCode: string, state: PersonalStockState): Promise<void> {
    if (state.observed && state.observationId != null) {
        await personalRequest(`/me/observations/${state.observationId}`, { method: 'DELETE' })
        return
    }
    await personalRequest<PersonalItemResponse>('/me/observations', { method: 'POST', body: JSON.stringify({ ts_code: tsCode }) })
}

export async function toggleHolding(tsCode: string, state: PersonalStockState): Promise<void> {
    if (state.holding && state.portfolioId != null && state.positionId != null) {
        await personalRequest(`/me/portfolios/${state.portfolioId}/positions/${state.positionId}`, { method: 'DELETE' })
        return
    }
    let portfolioId = state.portfolioId
    if (portfolioId == null) {
        const portfolios = await personalRequest<PortfolioResponse>('/me/portfolios?limit=100')
        const portfolio = portfolios.data?.items?.find((item) => item.is_default && !item.archived_at) ?? portfolios.data?.items?.find((item) => !item.archived_at)
        if (portfolio) portfolioId = portfolio.id
        else {
            const created = await personalRequest<{ data?: Portfolio }>('/me/portfolios', { method: 'POST', body: JSON.stringify({ name: '默认组合' }) })
            portfolioId = created.data?.id ?? null
        }
    }
    if (portfolioId == null) throw new Error('无法创建持仓组合，请稍后重试。')
    await personalRequest(`/me/portfolios/${portfolioId}/positions`, { method: 'POST', body: JSON.stringify({ ts_code: tsCode, quantity: 0, available_quantity: 0, average_cost: 0, as_of_date: dateString(new Date()) }) })
}

export async function fetchTechnicalBars(tsCode: string, days: number, signal?: AbortSignal): Promise<TechnicalBar[]> {
    const endDate = new Date()
    const startDate = subtractWeekdays(endDate, Math.min(365, days))
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
    const response = await fetch(`${API_BASE}/market-analysis/securities/${encodeURIComponent(tsCode)}/technical-trend?${query}&period=${days >= 250 ? 250 : days >= 120 ? 120 : 60}`, { headers, signal })
    const body = await response.json() as TechnicalTrendResponse
    if (!response.ok || !Array.isArray(body.data?.series)) throw new Error(body.error?.message ?? '技术趋势行情加载失败，请稍后重试。')
    return body.data.series.map((row) => ({ tradeDate: row.trade_date ?? '', open: row.open ?? null, high: row.high ?? null, low: row.low ?? null, close: row.close ?? null, volume: row.volume ?? null })).filter((row) => row.tradeDate)
}

export async function fetchTechnicalTrend(tsCode: string, days: number, signal?: AbortSignal): Promise<TechnicalTrend> {
    const endDate = new Date()
    const startDate = subtractWeekdays(endDate, Math.min(365, days))
    const period = days >= 250 ? 250 : days >= 120 ? 120 : 60
    const query = new URLSearchParams({ start_date: dateString(startDate), end_date: dateString(endDate), adjust: 'qfq', frequency: 'D', period: String(period) })
    const accessToken = window.localStorage.getItem('access_token') ?? window.localStorage.getItem('auth_access_token')
    const headers: HeadersInit = { Accept: 'application/json' }
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`
    const response = await fetch(`${API_BASE}/market-analysis/securities/${encodeURIComponent(tsCode)}/technical-trend?${query}`, { headers, signal })
    const body = await response.json() as TechnicalTrendResponse
    if (!response.ok || !body.data?.series || !body.data.summary || !body.data.momentum?.latest) throw new Error(body.error?.message ?? '技术趋势加载失败，请稍后重试。')
    const data = body.data
    const series = data.series!
    const momentum = data.momentum!
    const summary = data.summary!
    return {
        security: { tsCode: data.security?.ts_code ?? tsCode, name: data.security?.name ?? tsCode },
        series: series.map((row) => ({ tradeDate: row.trade_date ?? '', open: row.open ?? null, high: row.high ?? null, low: row.low ?? null, close: row.close ?? null, volume: row.volume ?? null, ma25: row.ma25 ?? null, ma200: row.ma200 ?? null })).filter((row) => row.tradeDate),
        momentum: { latest: { rsi14: momentum.latest!.rsi14 ?? null, macd_histogram: momentum.latest!.macd_histogram ?? null, atr14: momentum.latest!.atr14 ?? null } },
        summary: { trend: summary.trend ?? null, trend_score: summary.trend_score ?? null, trend_level: summary.trend_level ?? null, volatility_status: summary.volatility_status ?? null, data_status: summary.data_status ?? 'NOT_AVAILABLE' },
        relativeStrength: { name: data.relative_strength?.name ?? null, relativeStrength: data.relative_strength?.relative_strength ?? null, direction: data.relative_strength?.direction ?? null, status: data.relative_strength?.status ?? 'NOT_AVAILABLE' },
        marketSentiment: { status: data.market_sentiment?.status ?? 'NOT_AVAILABLE', score: data.market_sentiment?.score ?? null, level: data.market_sentiment?.level ?? null, sourceTradeDate: data.market_sentiment?.source_trade_date ?? null },
        signals: (data.signals ?? []).map((signal) => ({ tradeDate: signal.trade_date ?? '', type: signal.type ?? '', direction: signal.direction ?? '', evidence: signal.evidence ?? '', status: signal.status ?? '' })),
        warnings: data.warnings ?? [], ruleVersion: data.rule_version ?? '', adjust: data.adjust ?? 'qfq', frequency: data.frequency ?? 'D', period: data.period ?? period,
    }
}

export async function fetchStockSentiment(tsCode: string, signal?: AbortSignal): Promise<StockSentiment> {
    const accessToken = window.localStorage.getItem('access_token') ?? window.localStorage.getItem('auth_access_token')
    const headers: HeadersInit = { Accept: 'application/json' }
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`
    const response = await fetch(`${API_BASE}/market-analysis/sentiment/stocks/${encodeURIComponent(tsCode)}`, { headers, signal })
    const body = await response.json() as StockSentimentResponse
    const data = body.data
    if (!response.ok || !data?.ts_code || !data.trade_date || !data.status) throw new Error(body.error?.message ?? '个股情绪加载失败，请稍后重试。')
    return {
        tsCode: data.ts_code,
        tradeDate: data.trade_date,
        score: data.score ?? null,
        level: data.level ?? null,
        status: data.status,
        sourceTradeDate: data.source_trade_date ?? null,
        momentum: data.momentum ?? null,
        activity: data.activity ?? null,
        fear: data.fear ?? null,
        coverage: data.coverage ?? null,
        sampleCount: data.sample_count ?? 0,
        engineVersion: data.engine_version ?? '',
    }
}

export async function fetchTechnicalChips(tsCode: string, startDate: string, endDate: string, signal?: AbortSignal): Promise<TechnicalChip[]> {
    const query = new URLSearchParams({ start_date: startDate, end_date: endDate })
    const accessToken = window.localStorage.getItem('access_token') ?? window.localStorage.getItem('auth_access_token')
    const headers: HeadersInit = { Accept: 'application/json' }
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`
    const response = await fetch(`${API_BASE}/market-analysis/securities/${encodeURIComponent(tsCode)}/chips?${query}`, { headers, signal })
    const body = await response.json() as ChipsResponse
    if (!response.ok || !Array.isArray(body.data)) throw new Error(body.error?.message ?? '筹码分布加载失败，请稍后重试。')
    return body.data.filter((row): row is { trade_date: string; price: number; percent: number } => typeof row.trade_date === 'string' && typeof row.price === 'number' && Number.isFinite(row.price) && typeof row.percent === 'number' && Number.isFinite(row.percent)).map((row) => ({ tradeDate: row.trade_date, price: row.price, percent: row.percent }))
}

export type SwIndustry = { industry_code: string; index_code?: string; level: string; name: string }
export type StockSelectionQuery = {
    preset?: string
    market: string
    report_type: string
    asof_date: string
    industry?: string
    revenue_yoy_min: number
    profit_yoy_min: number
    ebit_yoy_min: number
    roe_min: number
    gross_margin_improved: boolean
    operating_cash_flow_positive: boolean
    liquidity_ratio_min: number
    net_cash: boolean
    sort: string
    direction: 'asc' | 'desc'
    page: number
    page_size: number
}
export type StockSelectionItem = {
    ts_code: string
    name: string
    industry?: string | null
    main_business?: string | null
    sw_industry?: { name?: string | null }
    financial_score?: number | null
    value_valuation_score?: number | null
    model_valuation_score?: number | null
    revenue_yoy?: number | null
    profit_yoy?: number | null
    ebit_yoy?: number | null
    roe?: number | null
    gross_margin_change?: number | null
    operating_cash_flow?: number | null
    liquidity_ratio?: number | null
}

type SwIndustryResponse = { data?: SwIndustry[]; error?: { message?: string } }
type StockSelectionResponse = { data?: { summary?: { market_stock_count?: number; matched_count?: number; returned_count?: number }; items?: StockSelectionItem[] }; error?: { message?: string } }

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

function authHeaders(): HeadersInit {
    const accessToken = window.localStorage.getItem('access_token') ?? window.localStorage.getItem('auth_access_token')
    return accessToken ? { Accept: 'application/json', Authorization: `Bearer ${accessToken}` } : { Accept: 'application/json' }
}

export async function fetchSwIndustries(level = 'L3', signal?: AbortSignal): Promise<SwIndustry[]> {
    const query = new URLSearchParams({ level, page: '1', page_size: '200' })
    const response = await fetch(`${API_BASE}/market-analysis/sw-industries?${query}`, { headers: authHeaders(), signal })
    const body = await response.json() as SwIndustryResponse
    if (!response.ok || !Array.isArray(body.data)) throw new Error(body.error?.message ?? 'SW 行业列表加载失败，请稍后重试。')
    return body.data
}

export async function fetchStockSelection(queryValues: StockSelectionQuery, signal?: AbortSignal): Promise<NonNullable<StockSelectionResponse['data']>> {
    const query = new URLSearchParams()
    Object.entries(queryValues).forEach(([key, value]) => { if (value !== undefined && value !== '') query.set(key, String(value)) })
    const response = await fetch(`${API_BASE}/market-analysis/stock-selection/results?${query}`, { headers: authHeaders(), signal })
    const body = await response.json() as StockSelectionResponse
    if (!response.ok || !body.data) throw new Error(body.error?.message ?? '选股结果加载失败，请稍后重试。')
    return body.data
}

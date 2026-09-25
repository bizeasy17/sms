export type SwIndustry = { industry_code: string; index_code?: string; level: string; name: string }
export type StockSelectionPreset = 'maniu-selected' | 'buffett-moat' | 'high-growth' | 'cash-cow' | 'undervalued' | 'high-dividend' | 'small-beautiful' | 'turnaround' | 'net-cash-bargain' | 'risk-scan'
export type StockSelectionRangeKey = 'revenue_yoy' | 'profit_yoy' | 'ebit_yoy' | 'roe' | 'roic' | 'gross_margin' | 'cash_profit_ratio' | 'debt_to_assets' | 'liquidity_ratio' | 'goodwill_to_equity' | 'pe_ttm' | 'pb' | 'peg' | 'dividend_yield' | 'market_cap'
export type StockSelectionToggleKey = 'net_profit_positive' | 'gross_margin_improved' | 'operating_cash_flow_positive' | 'free_cash_flow_positive' | 'net_cash'
export type StockSelectionFilterDraft = {
    ranges: Record<StockSelectionRangeKey, { min: string; max: string }>
    toggles: Record<StockSelectionToggleKey, boolean>
}
type NumericFilterKey = `${StockSelectionRangeKey}_${'min' | 'max'}`

export type StockSelectionQuery = {
    preset: StockSelectionPreset
    screen_mode: 'screen' | 'risk'
    market: string
    report_type: string
    asof_date: string
    industry?: string
    sort: string
    direction: 'asc' | 'desc'
    page: number
    page_size: number
} & Partial<Record<NumericFilterKey, number | ''>>
    & Partial<Record<StockSelectionToggleKey, boolean>>
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
    market_cap?: number | null
}

type SwIndustryResponse = { data?: SwIndustry[]; error?: { message?: string } }
type StockSelectionResponse = { data?: { summary?: { market_stock_count?: number; matched_count?: number; returned_count?: number }; items?: StockSelectionItem[]; filter_units?: { market_cap?: 'CNY_10K' }; units?: { market_cap?: 'CNY_100M' } }; error?: { message?: string } }

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
    Object.entries(queryValues).forEach(([key, value]) => { if (value !== undefined) query.set(key, String(value)) })
    const response = await fetch(`${API_BASE}/market-analysis/stock-selection/results?${query}`, { headers: authHeaders(), signal })
    const body = await response.json() as StockSelectionResponse
    if (!response.ok || !body.data) throw new Error(body.error?.message ?? '选股结果加载失败，请稍后重试。')
    return body.data
}

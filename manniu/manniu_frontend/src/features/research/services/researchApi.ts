import type { Market, Pool, Stock, StockTag, TagAction } from '../types'

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
type ValuationResult = { action?: string | null; undervalue_score?: number | null }

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
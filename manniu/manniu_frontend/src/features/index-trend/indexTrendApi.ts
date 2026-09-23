const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

type Metric = 'PE' | 'PETTM' | 'PB'
type WindowKey = '30D' | '60D' | '90D' | '1Y' | '3Y' | '5Y' | '10Y' | 'ALL'

type ApiSummary = {
    current?: number | null
    percentile?: number | null
    p10?: number | null
    p50?: number | null
    p90?: number | null
    start_date?: string | null
    end_date?: string | null
}

type CompositeResponse = {
    data?: { summary?: ApiSummary; series?: Record<string, number | null> }
    error?: { message?: string }
}

type ShanghaiRow = { trade_date?: string; pe?: number | null; pe_ttm?: number | null; pb?: number | null }
type ShanghaiResponse = { data?: ShanghaiRow[]; error?: { message?: string } }

export type IndexTrendPoint = { date: string; value: number }
export type IndexTrendPayload = { points: IndexTrendPoint[]; summary: ApiSummary }

function dateString(date: Date) {
    return date.toISOString().slice(0, 10)
}

function dateRange(window: WindowKey) {
    const end = new Date()
    const start = new Date(end)
    const days = window === '30D' ? 30 : window === '60D' ? 60 : window === '90D' ? 90 : window === '1Y' ? 365 : window === '3Y' ? 1095 : window === '5Y' ? 1825 : window === '10Y' ? 3650 : 2555
    start.setDate(start.getDate() - days)
    return { start_date: dateString(start), end_date: dateString(end) }
}

function headers(): HeadersInit {
    const result: HeadersInit = { Accept: 'application/json' }
    const token = window.localStorage.getItem('access_token') ?? window.localStorage.getItem('auth_access_token')
    if (token) result.Authorization = `Bearer ${token}`
    return result
}

async function readJson<T>(url: string, signal: AbortSignal): Promise<T> {
    const response = await fetch(url, { headers: headers(), signal })
    const body = await response.json() as T & { error?: { message?: string } }
    if (!response.ok) throw new Error(body.error?.message ?? '指数趋势数据加载失败，请稍后重试。')
    return body
}

export async function fetchCompositeTrend(metric: Metric, window: WindowKey, signal: AbortSignal): Promise<IndexTrendPayload> {
    const query = new URLSearchParams({ metric, ...dateRange(window) })
    const body = await readJson<CompositeResponse>(`${API_BASE}/market-analysis/indices/composite/fundamentals?${query}`, signal)
    const series = body.data?.series ?? {}
    const points = Object.entries(series)
        .filter((entry): entry is [string, number] => typeof entry[1] === 'number' && Number.isFinite(entry[1]))
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([date, value]) => ({ date, value }))
    return { points, summary: body.data?.summary ?? {} }
}

export async function fetchShanghaiTrend(metric: Metric, window: WindowKey, signal: AbortSignal): Promise<IndexTrendPayload> {
    const query = new URLSearchParams({ ...dateRange(window), page: '1', page_size: '200' })
    const body = await readJson<ShanghaiResponse>(`${API_BASE}/market-analysis/indices/sh/fundamentals?${query}`, signal)
    const field = metric === 'PETTM' ? 'pe_ttm' : metric.toLowerCase() as 'pe' | 'pb'
    const points = (body.data ?? [])
        .filter((row): row is ShanghaiRow & { trade_date: string } => typeof row.trade_date === 'string' && typeof row[field] === 'number' && Number.isFinite(row[field]))
        .sort((left, right) => left.trade_date.localeCompare(right.trade_date))
        .map((row) => ({ date: row.trade_date, value: row[field] as number }))
    const values = points.map((point) => point.value)
    const current = points.at(-1)?.value ?? null
    const sorted = [...values].sort((left, right) => left - right)
    const quantile = (probability: number) => sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * probability))] : null
    const percentile = current == null || !sorted.length ? null : (sorted.filter((value) => value <= current).length / sorted.length) * 100
    return { points, summary: { current, percentile, p10: quantile(.1), p50: quantile(.5), p90: quantile(.9), start_date: points[0]?.date, end_date: points.at(-1)?.date } }
}

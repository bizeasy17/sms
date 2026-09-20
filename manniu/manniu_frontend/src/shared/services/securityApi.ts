export type SecuritySearchResult = {
    code: string
    name: string
    market: string
    industry: string
    listDate: string | null
    tags: never[]
    change: string
    positive: null
}

export type AuthUser = { display_name?: string; username?: string }

type SecuritiesResponse = { data?: Array<{ ts_code: string; name: string; industry?: string | null; list_date?: string | null }>; error?: { message?: string } }
type AuthUserResponse = { data?: AuthUser; error?: { message?: string } }

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

function authHeaders(): HeadersInit {
    const accessToken = window.localStorage.getItem('access_token') ?? window.localStorage.getItem('auth_access_token')
    return accessToken ? { Accept: 'application/json', Authorization: `Bearer ${accessToken}` } : { Accept: 'application/json' }
}

export async function searchSecurities(queryText: string, signal?: AbortSignal): Promise<SecuritySearchResult[]> {
    const query = new URLSearchParams({ q: queryText, asset_type: 'STOCK', page: '1', page_size: '8' })
    const response = await fetch(`${API_BASE}/market-analysis/securities?${query}`, { headers: authHeaders(), signal })
    const body = await response.json() as SecuritiesResponse
    if (!response.ok || !Array.isArray(body.data)) throw new Error(body.error?.message ?? '证券搜索失败，请稍后重试。')
    return body.data.map((item) => ({ code: item.ts_code, name: item.name, market: item.ts_code.split('.')[1] ?? '', industry: item.industry || '暂无行业', listDate: item.list_date ?? null, tags: [], change: '暂无涨跌', positive: null }))
}

export async function fetchCurrentUser(signal?: AbortSignal): Promise<AuthUser | null> {
    if (!window.localStorage.getItem('access_token') && !window.localStorage.getItem('auth_access_token')) return null
    const response = await fetch(`${API_BASE}/auth/me`, { headers: authHeaders(), signal })
    const body = await response.json() as AuthUserResponse
    if (!response.ok || !body.data) throw new Error(body.error?.message ?? '当前账户加载失败。')
    return body.data
}

export async function logoutCurrentUser(): Promise<void> {
    const response = await fetch(`${API_BASE}/auth/logout`, { method: 'POST', headers: authHeaders() })
    if (!response.ok && response.status !== 401) throw new Error('注销失败，请稍后重试。')
}

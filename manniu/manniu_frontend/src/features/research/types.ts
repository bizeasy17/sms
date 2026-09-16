export type Pool = 'holding' | 'watchlist' | 'observe'
export type Market = 'all' | 'sh-main' | 'sz-main' | 'cyb' | 'star'
export type Tab = 'summary' | 'technical' | 'fundamental' | 'financials'
export type TagAction = 'BUY' | 'SELL' | 'HOLD' | null
export type StockTag = { text: string; label: string; action: TagAction; actionText?: string; scoreText?: string }
export type Stock = { code: string; name: string; market: string; industry: string; tags: StockTag[]; change: string; positive: boolean | null }
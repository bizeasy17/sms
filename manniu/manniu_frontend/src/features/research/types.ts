export type Pool = 'holding' | 'watchlist' | 'observe'
export type Market = 'all' | 'sh-main' | 'sz-main' | 'cyb' | 'star'
export type Tab = 'summary' | 'technical' | 'fundamentals'
export type TagAction = 'BUY' | 'SELL' | 'HOLD' | null
export type StockTag = { text: string; label: string; action: TagAction; actionText?: string; scoreText?: string }
export type Stock = { code: string; name: string; market: string; industry: string; tags: StockTag[]; change: string; positive: boolean | null }
export type StockQuote = { tradeDate: string; close: number | null; change: number | null; pctChange: number | null }
export type TechnicalBar = { tradeDate: string; open: number | null; high: number | null; low: number | null; close: number | null; volume: number | null }
export type TechnicalChip = { tradeDate: string; price: number; percent: number }
export type TechnicalTrend = {
    security: { tsCode: string; name: string }
    series: Array<TechnicalBar & { ma25: number | null; ma200: number | null }>
    momentum: { latest: { rsi14: number | null; macd_histogram: number | null; atr14: number | null } }
    summary: { trend: string | null; trend_score: number | null; trend_level: string | null; volatility_status: string | null; data_status: string }
    relativeStrength: { name: string | null; relativeStrength: number | null; direction: string | null; status: string }
    marketSentiment: { status: string; score: number | null; level: string | null; sourceTradeDate: string | null }
    signals: Array<{ tradeDate: string; type: string; direction: string; evidence: string; status: string }>
    warnings: string[]
    ruleVersion: string
    adjust: string
    frequency: string
    period: number
}
export type PersonalStockState = { watched: boolean; watchlistId: number | null; holding: boolean; portfolioId: number | null; positionId: number | null; observed: boolean; observationId: number | null }
export type MarketEvidenceHistory = { tradeDate: string; open: number | null; high: number | null; low: number | null; close: number | null; industryClose: number | null }
export type MarketEvidence = {
    security: { tsCode: string; name: string }
    industry: { indexCode: string | null; industryCode: string | null; name: string | null }
    history: MarketEvidenceHistory[]
    summary: { atr14: number | null; atr14Percentile60d: number | null; ma25: number | null; ma25Trend: string | null; ma200: number | null; ma200Trend: string | null; currentPrice: number | null; priceToMa25: number | null; relativeStrengthVsIndustry: number | null }
    requestedDays: number
    returnedDays: number
    warnings: string[]
}
export type FinancialMetric = { key: string; value: number | null; yoy: number | null; yoyUnit: 'ratio' | 'percentage_points'; rolling12: number | null; rolling12Unit: string; period: string | null; sourceDataset: string; available: boolean }
export type FundamentalDimension = { score: number | null; status: string; available: boolean; evidence: string[]; missingMetrics: string[] }
export type FundamentalEvaluation = {
    evaluationVersion: string
    overall: { score: number | null; status: string; availableWeight: number; missingDimensions: string[] }
    dimensions: Record<string, FundamentalDimension>
    trend: Array<{ period: string | null; sourcePeriod: string | null; overall: { score: number | null; status: string; availableWeight: number; missingDimensions: string[] }; dimensions: Record<string, FundamentalDimension> }>
    reports: Array<{ period: string; reportType: string | null; endDate: string; annDate: string | null; effectiveDate: string | null; dataStatus: string; sourceRevision: string | null }>
    signals: Array<{ signalCode: string; label: string; severity: string; status: string; asofDate: string | null; evidence: string; metrics: string[]; provenance: Record<string, unknown> }>
    warnings: string[]
}
export type FinancialOverview = { period: string | null; reportType: string; metrics: Record<string, FinancialMetric>; evaluation: FundamentalEvaluation | null; sourceDates: Record<string, string>; warnings: string[] }
export type TraditionalValuationMethod = { valuationMethod: string; valuationPrice: number | null; note: string; available: boolean }
export type TraditionalValuation = { currentPrice: number | null; conservativePrice: number | null; centerPrice: number | null; optimisticPrice: number | null; confidence: number | null; undervalueScore: number | null; buyCandidate: boolean | null; riskLevel: string | null; asofDate: string | null; sourceTradeDate: string | null; methods: TraditionalValuationMethod[] }
export type PredictiveTier = { targetPrice: number | null; targetPriceLow: number | null; targetPriceHigh: number | null; riskLevel: string | null }
export type PredictiveValuation = { action: string | null; signalScore: number | null; riskLevel: string | null; targetPrice: number | null; targetPriceLow: number | null; targetPriceHigh: number | null; asofDate: string | null; tiers: { conservative: PredictiveTier; balance: PredictiveTier; aggressive: PredictiveTier } }
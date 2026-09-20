import { useEffect, useState } from 'react'
import { fetchStockSelection, fetchSwIndustries, type StockSelectionItem, type StockSelectionQuery, type SwIndustry } from '../services/stockSelectionApi'

export type StockSelectionFilters = {
    roe: boolean
    grossMargin: boolean
    cashFlow: boolean
    netCash: boolean
    revenueYoy: number
    profitYoy: number
    ebitYoy: number
    liquidityRatio: number
}

type SortKey = 'score' | 'valueValuationScore' | 'modelValuationScore' | 'revenueYoy' | 'profitYoy' | 'ebitYoy' | 'roe' | 'liquidityRatio'
type QueryStatus = 'idle' | 'loading' | 'error'

export function useStockSelection(filters: StockSelectionFilters, sortKey: SortKey, sortDirection: 'asc' | 'desc', market: string, reportType: string, asofDate: string, selectedIndustry: string) {
    const [industries, setIndustries] = useState<SwIndustry[]>([])
    const [industryStatus, setIndustryStatus] = useState<'loading' | 'ready' | 'error'>('loading')
    const [industryError, setIndustryError] = useState('')
    const [resultRows, setResultRows] = useState<StockSelectionItem[]>([])
    const [marketStockCount, setMarketStockCount] = useState(0)
    const [matchedCount, setMatchedCount] = useState(0)
    const [queryStatus, setQueryStatus] = useState<QueryStatus>('idle')
    const [queryError, setQueryError] = useState('')

    useEffect(() => {
        const controller = new AbortController()
        fetchSwIndustries('L3', controller.signal).then((items) => { setIndustries(items); setIndustryStatus('ready') }).catch((error: unknown) => {
            if (error instanceof DOMException && error.name === 'AbortError') return
            const message = error instanceof Error ? error.message : 'SW 行业列表加载失败，请稍后重试。'
            if (/认证凭证无效或已过期|未认证|unauthorized|401/i.test(message)) { setIndustryError(''); setIndustryStatus('ready'); return }
            setIndustryError(message); setIndustryStatus('error')
        })
        return () => controller.abort()
    }, [])

    async function updateResults(page = 1): Promise<boolean> {
        if (queryStatus === 'loading') return false
        setQueryStatus('loading'); setQueryError('')
        const controller = new AbortController()
        const query: StockSelectionQuery = { preset: 'quality-growth', market, report_type: reportType, asof_date: asofDate, industry: selectedIndustry === 'all' ? undefined : selectedIndustry, revenue_yoy_min: filters.revenueYoy, profit_yoy_min: filters.profitYoy, ebit_yoy_min: filters.ebitYoy, roe_min: filters.roe ? 10 : -100, gross_margin_improved: filters.grossMargin, operating_cash_flow_positive: filters.cashFlow, liquidity_ratio_min: filters.liquidityRatio, net_cash: filters.netCash, sort: sortKey === 'valueValuationScore' ? 'value_valuation_score' : sortKey === 'modelValuationScore' ? 'model_valuation_score' : sortKey === 'revenueYoy' ? 'revenue_yoy' : sortKey === 'profitYoy' ? 'profit_yoy' : sortKey === 'ebitYoy' ? 'ebit_yoy' : sortKey, direction: sortDirection, page, page_size: 10 }
        try {
            const data = await fetchStockSelection(query, controller.signal)
            setResultRows(data.items ?? []); setMarketStockCount(data.summary?.market_stock_count ?? 0); setMatchedCount(data.summary?.matched_count ?? 0); setQueryStatus('idle')
        } catch (error: unknown) {
            if (error instanceof DOMException && error.name === 'AbortError') return false
            setQueryError(error instanceof Error ? error.message : '选股结果加载失败，请稍后重试。'); setQueryStatus('error')
            return false
        }
        return true
    }

    return { industries, industryStatus, industryError, resultRows, marketStockCount, matchedCount, queryStatus, queryError, updateResults }
}

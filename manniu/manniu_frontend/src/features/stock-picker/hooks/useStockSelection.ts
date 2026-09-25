import { useEffect, useState } from 'react'
import { fetchStockSelection, fetchSwIndustries, type StockSelectionFilterDraft, type StockSelectionItem, type StockSelectionPreset, type StockSelectionQuery, type StockSelectionRangeKey, type SwIndustry } from '../services/stockSelectionApi'

type SortKey = 'score' | 'valueValuationScore' | 'modelValuationScore' | 'revenueYoy' | 'profitYoy' | 'ebitYoy' | 'roe' | 'liquidityRatio'
type QueryStatus = 'idle' | 'loading' | 'error'

export function useStockSelection(preset: StockSelectionPreset, filters: StockSelectionFilterDraft, sortKey: SortKey, sortDirection: 'asc' | 'desc', market: string, reportType: string, asofDate: string, selectedIndustry: string) {
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
        const query: StockSelectionQuery = {
            preset,
            screen_mode: preset === 'risk-scan' ? 'risk' : 'screen',
            market,
            report_type: reportType,
            asof_date: asofDate,
            industry: selectedIndustry === 'all' ? undefined : selectedIndustry,
            sort: sortKey === 'valueValuationScore' ? 'value_valuation_score' : sortKey === 'modelValuationScore' ? 'model_valuation_score' : sortKey === 'revenueYoy' ? 'revenue_yoy' : sortKey === 'profitYoy' ? 'profit_yoy' : sortKey === 'ebitYoy' ? 'ebit_yoy' : sortKey,
            direction: sortDirection,
            page,
            page_size: 10,
        }
        if (preset !== 'risk-scan') {
            const numericFilters: Partial<Record<`${StockSelectionRangeKey}_${'min' | 'max'}`, number | ''>> = {}
            for (const key of Object.keys(filters.ranges) as StockSelectionRangeKey[]) {
                for (const bound of ['min', 'max'] as const) {
                    const rawValue = filters.ranges[key][bound]
                    const parsedValue = rawValue.trim() === '' ? '' : Number(rawValue)
                    numericFilters[`${key}_${bound}`] = parsedValue === '' || !Number.isFinite(parsedValue)
                        ? ''
                        : key === 'market_cap' ? parsedValue * 10_000 : parsedValue
                }
            }
            Object.assign(query, numericFilters, filters.toggles)
        }
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

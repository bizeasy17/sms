import './App.css'
import './features/research/research-overrides.css'
import { ApiLab, ApiLoginPage } from './ApiLab'
import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Events } from './features/research/components/Events'
import { FundamentalEvidence } from './features/research/components/FundamentalEvidence'
import { FundamentalsWorkspace } from './features/research/components/FundamentalsWorkspace'
import { MarketEvidence } from './features/research/components/MarketEvidence'
import { ResearchTabs } from './features/research/components/ResearchTabs'
import { StockIdentity } from './features/research/components/StockIdentity'
import { StockRail } from './features/research/components/StockRail'
import { TechnicalTrend } from './features/research/components/TechnicalTrend'
import { TopBar } from './features/research/components/TopBar'
import { ValuationSummary } from './features/research/components/ValuationSummary'
import { fetchFinancialOverview, fetchLatestStockQuote, fetchPersonalStockState, fetchPredictiveValuation, fetchResearchList, fetchTraditionalValuation, toggleHolding, toggleObservation, toggleWatchlist } from './features/research/services/researchApi'
import type { FinancialMetric, FinancialOverview, Market, PersonalStockState, Pool, PredictiveValuation, Stock, StockQuote, Tab, TraditionalValuation } from './features/research/types'

function ResearchHomePage() {
  const [selected, setSelected] = useState<Stock | null>(null)
  const [stocks, setStocks] = useState<Stock[]>([])
  const [stocksLoading, setStocksLoading] = useState(true)
  const [stocksError, setStocksError] = useState('')
  const [pool, setPool] = useState<Pool>('watchlist')
  const [market, setMarket] = useState<Market>('all')
  const [tab, setTab] = useState<Tab>('summary')
  const [visitedTabs, setVisitedTabs] = useState<Record<Tab, boolean>>({ summary: true, technical: false, fundamentals: false })
  const [railOpen, setRailOpen] = useState(false)
  const [quote, setQuote] = useState<StockQuote | null>(null)
  const [quoteState, setQuoteState] = useState<'loading' | 'ready' | 'empty' | 'error'>('loading')
  const [quoteRetry, setQuoteRetry] = useState(0)
  const [financialMetrics, setFinancialMetrics] = useState<Record<string, FinancialMetric> | null>(null)
  const [financialOverview, setFinancialOverview] = useState<FinancialOverview | null>(null)
  const [financialState, setFinancialState] = useState<'loading' | 'ready' | 'empty' | 'error'>('loading')
  const [financialRetry, setFinancialRetry] = useState(0)
  const [traditionalValuation, setTraditionalValuation] = useState<TraditionalValuation | null>(null)
  const [traditionalState, setTraditionalState] = useState<'loading' | 'ready' | 'empty' | 'error'>('loading')
  const [predictiveValuation, setPredictiveValuation] = useState<PredictiveValuation | null>(null)
  const [predictiveState, setPredictiveState] = useState<'loading' | 'ready' | 'empty' | 'error'>('loading')
  const [personalState, setPersonalState] = useState<PersonalStockState | null>(null)
  const [personalStateStatus, setPersonalStateStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [personalNotice, setPersonalNotice] = useState('')
  const [personalNoticeType, setPersonalNoticeType] = useState<'success' | 'error'>('success')

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (['holding', 'watchlist', 'observe'].includes(params.get('pool') ?? '')) setPool(params.get('pool') as Pool)
    if (['all', 'sh-main', 'sz-main', 'cyb', 'star'].includes(params.get('market') ?? '')) setMarket(params.get('market') as Market)
    if (['summary', 'technical', 'fundamentals'].includes(params.get('tab') ?? '')) setTab(params.get('tab') as Tab)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    setStocksLoading(true)
    setStocksError('')
    fetchResearchList(pool, market, controller.signal).then((items) => {
      setStocks(items)
      const requestedCode = new URLSearchParams(window.location.search).get('ts_code')
      setSelected((current) => current ?? items.find((stock) => stock.code === requestedCode) ?? items[0] ?? null)
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setStocksError(error instanceof Error ? error.message : '股票池加载失败，请稍后重试。')
    }).finally(() => {
      if (!controller.signal.aborted) setStocksLoading(false)
    })
    return () => controller.abort()
  }, [pool, market])

  useEffect(() => {
    if (!selected) return
    const controller = new AbortController()
    setPersonalState(null)
    setPersonalStateStatus('loading')
    fetchPersonalStockState(selected.code, controller.signal).then((state) => {
      setPersonalState(state)
      setPersonalStateStatus('ready')
    }).catch(() => {
      if (!controller.signal.aborted) setPersonalStateStatus('error')
    })
    return () => controller.abort()
  }, [selected?.code])

  useEffect(() => {
    if (!personalNotice) return
    const timer = window.setTimeout(() => setPersonalNotice(''), 2500)
    return () => window.clearTimeout(timer)
  }, [personalNotice])

  useEffect(() => {
    if (!selected) return
    const controller = new AbortController()
    setQuote(null)
    setQuoteState('loading')
    fetchLatestStockQuote(selected.code, controller.signal).then((latest) => {
      if (latest) {
        setQuote(latest)
        setQuoteState('ready')
      } else {
        setQuoteState('empty')
      }
    }).catch(() => {
      if (!controller.signal.aborted) setQuoteState('error')
    })
    return () => controller.abort()
  }, [selected?.code, quoteRetry])

  useEffect(() => {
    if (!selected) return
    const controller = new AbortController()
    setFinancialMetrics(null)
    setFinancialOverview(null)
    setFinancialState('loading')
    fetchFinancialOverview(selected.code, controller.signal).then((overview) => {
      setFinancialOverview(overview)
      setFinancialMetrics(overview.metrics)
      setFinancialState(Object.values(overview.metrics).some((metric) => metric.available) ? 'ready' : 'empty')
    }).catch(() => {
      if (!controller.signal.aborted) setFinancialState('error')
    })
    return () => controller.abort()
  }, [selected?.code, financialRetry])

  useEffect(() => {
    if (!selected) return
    const controller = new AbortController()
    setTraditionalValuation(null)
    setTraditionalState('loading')
    fetchTraditionalValuation(selected.code, controller.signal).then((value) => {
      setTraditionalValuation(value)
      setTraditionalState(value.methods.length || value.centerPrice != null ? 'ready' : 'empty')
    }).catch(() => {
      if (!controller.signal.aborted) setTraditionalState('error')
    })
    return () => controller.abort()
  }, [selected?.code])

  useEffect(() => {
    if (!selected) return
    const controller = new AbortController()
    setPredictiveValuation(null)
    setPredictiveState('loading')
    fetchPredictiveValuation(selected.code, controller.signal).then((value) => {
      setPredictiveValuation(value)
      setPredictiveState(value.targetPrice != null || value.action != null ? 'ready' : 'empty')
    }).catch(() => {
      if (!controller.signal.aborted) setPredictiveState('error')
    })
    return () => controller.abort()
  }, [selected?.code])

  async function handlePersonalAction(action: 'watchlist' | 'holding' | 'observe') {
    if (!selected || !personalState) return
    try {
      if (action === 'watchlist') await toggleWatchlist(selected.code, personalState)
      if (action === 'holding') await toggleHolding(selected.code, personalState)
      if (action === 'observe') await toggleObservation(selected.code, personalState)
      const nextState = await fetchPersonalStockState(selected.code)
      setPersonalState(nextState)
      setPersonalStateStatus('ready')
      setPersonalNoticeType('success')
      const active = action === 'watchlist' ? nextState.watched : action === 'holding' ? nextState.holding : nextState.observed
      setPersonalNotice(`${active ? '已加入' : '已移除'}${action === 'watchlist' ? '自选' : action === 'holding' ? '持仓' : '观察'}`)
    } catch (error) {
      setPersonalNoticeType('error')
      setPersonalNotice(error instanceof Error ? error.message : '个人股票状态操作失败')
    }
  }

  function selectStock(stock: Stock) {
    setSelected(stock)
    setRailOpen(false)
    window.history.replaceState({}, '', `/?ts_code=${stock.code}&tab=${tab}&pool=${pool}&market=${market}`)
  }

  function updatePool(nextPool: Pool) {
    setPool(nextPool)
    window.history.replaceState({}, '', `/?${selected ? `ts_code=${selected.code}&` : ''}tab=${tab}&pool=${nextPool}&market=${market}`)
  }

  function updateMarket(nextMarket: Market) {
    setMarket(nextMarket)
    window.history.replaceState({}, '', `/?${selected ? `ts_code=${selected.code}&` : ''}tab=${tab}&pool=${pool}&market=${nextMarket}`)
  }

  function changeTab(nextTab: Tab) {
    setVisitedTabs((current) => current[nextTab] ? current : { ...current, [nextTab]: true })
    setTab(nextTab)
  }

  function tabPanel(tabName: Tab, content: ReactNode) {
    if (!visitedTabs[tabName]) return null
    return <div hidden={tab !== tabName}>{content}</div>
  }

  return <div className="app-shell"><TopBar onMenu={() => setRailOpen(true)} /><main className="research-layout"><StockRail selected={selected} stocks={stocks} setSelected={selectStock} pool={pool} setPool={updatePool} market={market} setMarket={updateMarket} open={railOpen} loading={stocksLoading} error={stocksError} onRetry={() => setPool(pool)} />{selected ? <section className="research-dossier"><StockIdentity stock={selected} quote={quote} quoteState={quoteState} onRetry={() => setQuoteRetry((value) => value + 1)} personalState={personalState} personalStateStatus={personalStateStatus} personalNotice={personalNotice} personalNoticeType={personalNoticeType} onAction={handlePersonalAction} /><ResearchTabs tab={tab} setTab={changeTab} />{tabPanel('summary', <><ValuationSummary valuation={traditionalValuation ?? undefined} predictiveValuation={predictiveValuation ?? undefined} latestClose={quote?.close} state={traditionalState} predictiveState={predictiveState} /><MarketEvidence /><FundamentalEvidence metrics={financialMetrics} state={financialState} onRetry={() => setFinancialRetry((value) => value + 1)} /></>)}{tabPanel('technical', <TechnicalTrend stock={selected} />)}{tabPanel('fundamentals', <FundamentalsWorkspace stock={selected} metrics={financialMetrics} evaluation={financialOverview?.evaluation ?? null} financialOverview={financialOverview} financialState={financialState} onFinancialRetry={() => setFinancialRetry((value) => value + 1)} />)}</section> : <section className="research-dossier"><div className="tab-placeholder"><p className="kicker">RESEARCH LIST</p><h2>{stocksLoading ? '正在加载股票池' : stocksError ? '股票池暂时不可用' : '暂无可研究股票'}</h2></div></section>}<Events /></main><div className={`mobile-backdrop ${railOpen ? 'visible' : ''}`} onClick={() => setRailOpen(false)} /></div>
}

export default function RootApp() {
  if (window.location.pathname === '/public/api') return <ApiLab />
  if (window.location.pathname === '/login') return <ApiLoginPage />
  return <ResearchHomePage />
}

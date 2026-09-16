import './App.css'
import './features/research/research-overrides.css'
import { ApiLab, ApiLoginPage } from './ApiLab'
import { useEffect, useState } from 'react'
import { Events } from './features/research/components/Events'
import { FundamentalEvidence } from './features/research/components/FundamentalEvidence'
import { MarketEvidence } from './features/research/components/MarketEvidence'
import { ResearchTabs } from './features/research/components/ResearchTabs'
import { StockIdentity } from './features/research/components/StockIdentity'
import { StockRail } from './features/research/components/StockRail'
import { TopBar } from './features/research/components/TopBar'
import { ValuationSummary } from './features/research/components/ValuationSummary'
import { fetchResearchList } from './features/research/services/researchApi'
import type { Market, Pool, Stock, Tab } from './features/research/types'

function ResearchHomePage() {
  const [selected, setSelected] = useState<Stock | null>(null)
  const [stocks, setStocks] = useState<Stock[]>([])
  const [stocksLoading, setStocksLoading] = useState(true)
  const [stocksError, setStocksError] = useState('')
  const [pool, setPool] = useState<Pool>('watchlist')
  const [market, setMarket] = useState<Market>('all')
  const [tab, setTab] = useState<Tab>('summary')
  const [railOpen, setRailOpen] = useState(false)

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (['holding', 'watchlist', 'observe'].includes(params.get('pool') ?? '')) setPool(params.get('pool') as Pool)
    if (['all', 'sh-main', 'sz-main', 'cyb', 'star'].includes(params.get('market') ?? '')) setMarket(params.get('market') as Market)
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

  return <div className="app-shell"><TopBar onMenu={() => setRailOpen(true)} /><main className="research-layout"><StockRail selected={selected} stocks={stocks} setSelected={selectStock} pool={pool} setPool={updatePool} market={market} setMarket={updateMarket} open={railOpen} loading={stocksLoading} error={stocksError} onRetry={() => setPool(pool)} />{selected ? <section className="research-dossier"><StockIdentity stock={selected} /><ResearchTabs tab={tab} setTab={setTab} />{tab === 'summary' ? <><ValuationSummary /><MarketEvidence /><FundamentalEvidence /></> : <div className="tab-placeholder"><p className="kicker">{tab.toUpperCase()}</p><h2>研究模块已准备</h2><p>该模块将在下一阶段接入真实数据，目前保留统一的研究工作台结构。</p></div>}</section> : <section className="research-dossier"><div className="tab-placeholder"><p className="kicker">RESEARCH LIST</p><h2>{stocksLoading ? '正在加载股票池' : stocksError ? '股票池暂时不可用' : '暂无可研究股票'}</h2></div></section>}<Events /></main><div className={`mobile-backdrop ${railOpen ? 'visible' : ''}`} onClick={() => setRailOpen(false)} /></div>
}

export default function RootApp() {
  if (window.location.pathname === '/public/api') return <ApiLab />
  if (window.location.pathname === '/login') return <ApiLoginPage />
  return <ResearchHomePage />
}

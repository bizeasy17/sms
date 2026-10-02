import { useEffect, useState } from 'react'
import { fetchThsBoardCatalog } from '../services/researchApi'
import type { ListSource, Market, PersonalPool, Pool, Stock, ThsBoard } from '../types'

const marketOptions: [Market, string][] = [['all', '全市场'], ['sh-main', '沪主板'], ['sz-main', '深主板'], ['cyb', '创业板'], ['star', '科创板']]
const RECENT_VIEWED_KEY = 'manniu.recent-viewed-stocks'
const MAX_RECENT_VIEWED = 3

export function StockRail({ selected, stocks, setSelected, pool, source, setSource, setPool, market, setMarket, selectedThsBoard, setThsBoard, open, loading, error, onRetry, hasMore, loadingMore, loadMoreError, onLoadMore }: { selected: Stock | null; stocks: Stock[]; setSelected: (stock: Stock) => void; pool: Pool; source: ListSource; setSource: (source: ListSource) => void; setPool: (pool: PersonalPool) => void; market: Market; setMarket: (market: Market) => void; selectedThsBoard: string | null; setThsBoard: (board: string | null) => void; open: boolean; loading: boolean; error: string; onRetry: () => void; hasMore: boolean; loadingMore: boolean; loadMoreError: string; onLoadMore: () => void }) {
	const [recentViewed, setRecentViewed] = useState<Stock[]>(() => {
		try {
			const stored = window.localStorage.getItem(RECENT_VIEWED_KEY)
			const parsed = stored ? JSON.parse(stored) : []
			return Array.isArray(parsed) ? parsed.slice(0, MAX_RECENT_VIEWED) as Stock[] : []
		} catch { return [] }
	})
	const [searchTerm, setSearchTerm] = useState('')
	const [searchQuery, setSearchQuery] = useState('')
	const [catalogPage, setCatalogPage] = useState(1)
	const [catalogResult, setCatalogResult] = useState<{ requestKey: string; items: ThsBoard[]; hasNext: boolean; error?: string } | null>(null)
	const [catalogRetry, setCatalogRetry] = useState(0)
	const [catalogOpen, setCatalogOpen] = useState(false)
	const [recentExpanded, setRecentExpanded] = useState(false)
	const visibleStocks = stocks
	const catalogQuery = searchTerm.trim() ? searchQuery : selectedThsBoard ?? ''
	const catalogRequestKey = `${catalogQuery}:${catalogPage}:${catalogRetry}`
	const catalogLoading = source === 'ths' && catalogResult?.requestKey !== catalogRequestKey
	const catalogError = catalogResult?.requestKey === catalogRequestKey ? catalogResult.error ?? '' : ''
	const catalogItems = catalogResult?.items ?? []
	const catalogHasNext = catalogResult?.requestKey === catalogRequestKey && catalogResult.hasNext

	useEffect(() => {
		const timer = window.setTimeout(() => {
			setSearchQuery(searchTerm.trim())
			setCatalogPage(1)
		}, 250)
		return () => window.clearTimeout(timer)
	}, [searchTerm])

	useEffect(() => {
		if (source !== 'ths') return
		const controller = new AbortController()
		fetchThsBoardCatalog(catalogQuery, catalogPage, controller.signal).then((result) => {
			setCatalogResult({ requestKey: catalogRequestKey, items: result.items, hasNext: result.hasNext })
		}).catch((reason: unknown) => {
			if (!controller.signal.aborted) setCatalogResult({ requestKey: catalogRequestKey, items: [], hasNext: false, error: reason instanceof Error ? reason.message : 'THS 概念目录加载失败，请稍后重试。' })
		})
		return () => controller.abort()
	}, [source, catalogQuery, catalogPage, catalogRetry, catalogRequestKey])

	function selectStock(stock: Stock) {
		setRecentViewed((current) => {
			const next = [stock, ...current.filter((item) => item.code !== stock.code)].slice(0, MAX_RECENT_VIEWED)
			window.localStorage.setItem(RECENT_VIEWED_KEY, JSON.stringify(next))
			return next
		})
		setSelected(stock)
	}

	return <aside className={`stock-rail ${open ? 'open' : ''}`} aria-label="股票列表">
		<div className="rail-heading">
			<div><p className="kicker">RESEARCH LIST</p><h2>股票池</h2></div>
			<span className="stock-count">{loading ? '—' : visibleStocks.length}</span>
		</div>
		<div className="rail-controls">
			<div className="source-switch" role="group" aria-label="列表来源">
				{([['personal', '我的股票'], ['market', 'A股板块'], ['ths', 'THS概念']] as [ListSource, string][]).map(([value, label]) => <button key={value} type="button" aria-pressed={source === value} className={source === value ? 'selected' : ''} onClick={() => setSource(value)}>{label}</button>)}
			</div>
			{source === 'personal' && <div className="rail-filters">
				<div className="segmented">{(['holding', 'watchlist', 'observe'] as PersonalPool[]).map((item) => <button key={item} type="button" className={pool === item ? 'selected' : ''} onClick={() => setPool(item)}>{item === 'holding' ? '持仓' : item === 'watchlist' ? '自选' : '观察'}</button>)}</div>
				<MarketSelect market={market} setMarket={setMarket} />
			</div>}
			{source === 'market' && <div className="rail-filters market-filter"><span>A股范围</span><MarketSelect market={market} setMarket={setMarket} /></div>}
			{source === 'ths' && <div className="ths-controls">
				<div className="ths-filter-row">
					<div className="board-picker">
						<label className="sr-only" htmlFor="ths-board-search">搜索概念名称或代码</label>
						<input id="ths-board-search" type="search" value={searchTerm} placeholder="搜索概念名称或代码" autoComplete="off" aria-label="搜索概念名称或代码" aria-expanded={catalogOpen} aria-controls="ths-board-options" onFocus={() => setCatalogOpen(true)} onKeyDown={(event) => { if (event.key === 'Escape') setCatalogOpen(false) }} onChange={(event) => { setSearchTerm(event.target.value); setCatalogOpen(true) }} />
						{catalogOpen && <div id="ths-board-options" className="board-options" role="listbox" aria-label="THS概念板块搜索结果">
							{catalogLoading ? <p className="board-feedback">正在搜索概念目录...</p> : catalogError ? <div className="board-feedback"><p>{catalogError}</p><button type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => setCatalogRetry((value) => value + 1)}>重试</button></div> : catalogItems.length ? <>
								{catalogItems.map((board) => <button type="button" role="option" aria-selected={selectedThsBoard === board.tsCode} key={board.tsCode} onMouseDown={(event) => event.preventDefault()} onClick={() => { setThsBoard(board.tsCode); setCatalogOpen(false); setSearchTerm('') }}><span>{board.name}<small>{board.tsCode}</small></span><small>{board.count == null ? '成分数暂无' : `${board.count} 只`}</small></button>)}
								<div className="board-pagination"><button type="button" disabled={catalogPage <= 1} onMouseDown={(event) => event.preventDefault()} onClick={() => setCatalogPage((page) => Math.max(1, page - 1))}>上一页</button><span>{catalogPage}</span><button type="button" disabled={!catalogHasNext} onMouseDown={(event) => event.preventDefault()} onClick={() => setCatalogPage((page) => page + 1)}>下一页</button></div>
							</> : <p className="board-feedback">没有匹配的概念板块</p>}
						</div>}
					</div>
					<div className="rail-filters ths-market-filter"><MarketSelect market={market} setMarket={setMarket} /></div>
				</div>
				{selectedThsBoard && <div className="selected-board"><span>{catalogItems.find((board) => board.tsCode === selectedThsBoard)?.name ?? selectedThsBoard}<small>{selectedThsBoard}</small></span><button type="button" aria-label="清除概念板块" onClick={() => setThsBoard(null)}>清除</button></div>}
			</div>}
		</div>
		<div className="rail-list" onScroll={(event) => { const element = event.currentTarget; if (element.scrollHeight - element.scrollTop - element.clientHeight < 96) onLoadMore() }}>
			{source === 'ths' && !selectedThsBoard ? <div className="stock-empty">请选择概念板块</div> : <>
				{loading && visibleStocks.length > 0 && <p className="rail-list-status">正在更新，暂时显示上次结果</p>}
				{error && visibleStocks.length > 0 && <div className="rail-list-status error" role="status"><span>更新失败，显示上次成功列表</span><button type="button" onClick={onRetry}>重试</button></div>}
				{loading && visibleStocks.length === 0 ? <div className="stock-empty">加载股票池...</div> : error && visibleStocks.length === 0 ? <div className="stock-empty" role="alert"><p>{error}</p><button type="button" onClick={onRetry}>重试</button></div> : visibleStocks.length ? visibleStocks.map((stock) => <button key={stock.code} className={`stock-item ${stock.code === selected?.code ? 'selected' : ''}`} onClick={() => selectStock(stock)}><span className="stock-name">{stock.name}<small>{stock.code}</small></span><span className="stock-meta"><small>{stock.industry}</small><em className={stock.positive === true ? 'up' : stock.positive === false ? 'down' : ''}>{stock.change}</em></span><span className="stock-tags">{stock.tags.map((tag) => <i key={tag.text}>{tag.actionText ? <><span>{tag.label}</span><span className={`tag-action ${tag.action?.toLowerCase() ?? ''}`}>{tag.actionText}</span>{tag.scoreText && <> <span> · </span><span className={`tag-score ${tag.action?.toLowerCase() ?? ''}`}>{tag.scoreText}</span></>}</> : tag.text}</i>)}</span></button>) : <div className="stock-empty">暂无股票</div>}
				{hasMore && <div className="rail-list-status" role="status" aria-live="polite">{loadMoreError ? <><span>{loadMoreError}</span><button type="button" onClick={onLoadMore}>重试加载</button></> : loadingMore ? '正在加载更多...' : <button type="button" onClick={onLoadMore}>加载更多股票</button>}</div>}
			</>}
		</div>
		{recentViewed.length > 0 && <div className="recent"><button type="button" className="recent-toggle" aria-expanded={recentExpanded} onClick={() => setRecentExpanded((expanded) => !expanded)}><span className="kicker">RECENTLY VIEWED</span><span>{recentExpanded ? '收起' : `${recentViewed.length} 只`}</span></button>{recentExpanded && recentViewed.map((stock) => <button key={stock.code} onClick={() => selectStock(stock)}>{stock.name} <small>{stock.code}</small></button>)}</div>}
	</aside>
}

function MarketSelect({ market, setMarket }: { market: Market; setMarket: (market: Market) => void }) {
	return <select aria-label="市场筛选" value={market} onChange={(event) => setMarket(event.target.value as Market)}>{marketOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
}
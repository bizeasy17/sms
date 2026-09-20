import { useState } from 'react'
import type { Market, Pool, Stock } from '../types'

const marketOptions: [Market, string][] = [['all', '全市场'], ['sh-main', '沪主板'], ['sz-main', '深主板'], ['cyb', '创业板'], ['star', '科创板']]
const RECENT_VIEWED_KEY = 'manniu.recent-viewed-stocks'
const MAX_RECENT_VIEWED = 3

export function StockRail({ selected, stocks, setSelected, pool, setPool, market, setMarket, open, loading, error, onRetry }: { selected: Stock | null; stocks: Stock[]; setSelected: (stock: Stock) => void; pool: Pool; setPool: (pool: Pool) => void; market: Market; setMarket: (market: Market) => void; open: boolean; loading: boolean; error: string; onRetry: () => void }) {
	const [recentViewed, setRecentViewed] = useState<Stock[]>(() => {
		try {
			const stored = window.localStorage.getItem(RECENT_VIEWED_KEY)
			const parsed = stored ? JSON.parse(stored) : []
			return Array.isArray(parsed) ? parsed.slice(0, MAX_RECENT_VIEWED) as Stock[] : []
		} catch { return [] }
	})
	const visibleStocks = stocks

	function selectStock(stock: Stock) {
		setRecentViewed((current) => {
			const next = [stock, ...current.filter((item) => item.code !== stock.code)].slice(0, MAX_RECENT_VIEWED)
			window.localStorage.setItem(RECENT_VIEWED_KEY, JSON.stringify(next))
			return next
		})
		setSelected(stock)
	}

	return <aside className={`stock-rail ${open ? 'open' : ''}`} aria-label="股票列表"><div className="rail-heading"><div><p className="kicker">RESEARCH LIST</p><h2>股票池</h2></div><span className="stock-count">{loading ? '—' : visibleStocks.length}</span></div><div className="rail-filters"><div className="segmented">{(['holding', 'watchlist', 'observe'] as Pool[]).map((item) => <button key={item} className={pool === item ? 'selected' : ''} onClick={() => setPool(item)}>{item === 'holding' ? '持仓' : item === 'watchlist' ? '自选' : '观察'}</button>)}</div><select aria-label="市场筛选" value={market} onChange={(event) => setMarket(event.target.value as Market)}>{marketOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div><div className="rail-list">{loading ? <div className="stock-empty">加载股票池...</div> : error ? <div className="stock-empty"><p>{error}</p><button onClick={onRetry}>重试</button></div> : visibleStocks.length ? visibleStocks.map((stock) => <button key={stock.code} className={`stock-item ${stock.code === selected?.code ? 'selected' : ''}`} onClick={() => selectStock(stock)}><span className="stock-name">{stock.name}<small>{stock.code}</small></span><span className="stock-meta"><small>{stock.industry}</small><em className={stock.positive === true ? 'up' : stock.positive === false ? 'down' : ''}>{stock.change}</em></span><span className="stock-tags">{stock.tags.map((tag) => <i key={tag.text}>{tag.actionText ? <><span>{tag.label}</span><span className={`tag-action ${tag.action?.toLowerCase() ?? ''}`}>{tag.actionText}</span>{tag.scoreText && <> <span> · </span><span className={`tag-score ${tag.action?.toLowerCase() ?? ''}`}>{tag.scoreText}</span></>}</> : tag.text}</i>)}</span></button>) : <div className="stock-empty">暂无股票</div>}</div>{recentViewed.length > 0 && <div className="recent"><p className="kicker">RECENTLY VIEWED</p>{recentViewed.map((stock) => <button key={stock.code} onClick={() => selectStock(stock)}>{stock.name} <small>{stock.code}</small></button>)}</div>}</aside>
}
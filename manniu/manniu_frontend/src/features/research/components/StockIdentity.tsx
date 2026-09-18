import type { Stock, StockQuote } from '../types'

function formatNumber(value: number | null, digits: number) {
	return value == null ? '暂无' : value.toFixed(digits)
}

export function StockIdentity({ stock, quote, quoteState, onRetry }: { stock: Stock; quote: StockQuote | null; quoteState: 'loading' | 'ready' | 'empty' | 'error'; onRetry: () => void }) {
	const positive = quote?.pctChange != null && quote.pctChange > 0
	const negative = quote?.pctChange != null && quote.pctChange < 0
	const quoteClass = positive ? 'up' : negative ? 'down' : ''
	const quoteLabel = quoteState === 'loading' ? '加载行情...' : quoteState === 'error' ? '行情加载失败' : quoteState === 'empty' ? '暂无行情' : `¥${formatNumber(quote?.close ?? null, 2)}`
	return <><div className="breadcrumb"><span>覆盖池</span><b>/</b><span>{stock.industry}</span><b>/</b><strong>个股研究</strong></div><section className="stock-identity"><div><div className="identity-title"><h1>{stock.name}</h1><span className="code">{stock.code}</span><span className="exchange">{stock.market}</span></div><p>{stock.industry} · 数据截至 {quote?.tradeDate ?? '暂无'}</p></div><div className="quote"><strong>{quoteLabel}</strong>{quoteState === 'ready' ? <span className={quoteClass}>{positive ? '+' : ''}{formatNumber(quote?.change ?? null, 2)}&nbsp;&nbsp; {positive ? '+' : ''}{formatNumber(quote?.pctChange ?? null, 2)}%</span> : quoteState === 'error' ? <button type="button" onClick={onRetry}>重试</button> : <span className="quote-status">{quoteState === 'loading' ? '正在获取最新交易日' : '数据暂无'}</span>}</div></section></>
}
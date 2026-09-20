import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent } from 'react'
import { fetchCurrentUser, logoutCurrentUser, searchSecurities, type AuthUser, type SecuritySearchResult } from '../services/securityApi'
import { loginPath } from '../routing/queryParams'

function formatListDate(value: string | null) { return value ? value.replace(/-/g, '.') : '上市时间暂无' }
const RECENT_SEARCHES_KEY = 'manniu.recent-security-searches'
const MAX_RECENT_SEARCHES = 10
type TopBarProps = { onMenu: () => void; onSelect: (stock: SecuritySearchResult) => void; activeSection?: 'research' | 'picker' }

export function TopBar({ onMenu, onSelect, activeSection = 'research' }: TopBarProps) {
	const [query, setQuery] = useState('')
	const [results, setResults] = useState<SecuritySearchResult[]>([])
	const [activeIndex, setActiveIndex] = useState(-1)
	const [status, setStatus] = useState<'idle' | 'loading' | 'empty' | 'error'>('idle')
	const [open, setOpen] = useState(false)
	const [accountOpen, setAccountOpen] = useState(false)
	const [account, setAccount] = useState<AuthUser | null>(null)
	const [loggingOut, setLoggingOut] = useState(false)
	const [recentSearches, setRecentSearches] = useState<SecuritySearchResult[]>(() => {
		try {
			const stored = window.localStorage.getItem(RECENT_SEARCHES_KEY)
			const parsed = stored ? JSON.parse(stored) : []
			return Array.isArray(parsed) ? parsed.slice(0, MAX_RECENT_SEARCHES) : []
		} catch { return [] }
	})
	const inputRef = useRef<HTMLInputElement>(null)
	const searchId = useRef(0)

	useEffect(() => {
		const controller = new AbortController()
		fetchCurrentUser(controller.signal).then(setAccount).catch(() => undefined)
		return () => controller.abort()
	}, [])

	useEffect(() => {
		function handleShortcut(event: KeyboardEvent) {
			if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); inputRef.current?.focus(); inputRef.current?.select() }
		}
		window.addEventListener('keydown', handleShortcut)
		return () => window.removeEventListener('keydown', handleShortcut)
	}, [])

	useEffect(() => {
		const value = query.trim()
		if (!value) { setResults([]); setActiveIndex(-1); setStatus('idle'); setOpen(false); return }
		const controller = new AbortController(); const currentId = ++searchId.current
		setOpen(true); setStatus('loading')
		const timer = window.setTimeout(() => searchSecurities(value, controller.signal).then((items) => {
			if (currentId !== searchId.current) return
			setResults(items); setActiveIndex(items.length ? 0 : -1); setStatus(items.length ? 'idle' : 'empty')
		}).catch(() => { if (!controller.signal.aborted && currentId === searchId.current) setStatus('error') }), 220)
		return () => { window.clearTimeout(timer); controller.abort() }
	}, [query])

	function selectResult(stock: SecuritySearchResult) {
		const nextRecentSearches = [stock, ...recentSearches.filter((item) => item.code !== stock.code)].slice(0, MAX_RECENT_SEARCHES)
		setRecentSearches(nextRecentSearches); window.localStorage.setItem(RECENT_SEARCHES_KEY, JSON.stringify(nextRecentSearches))
		onSelect(stock); setQuery(''); setOpen(false); setResults([]); setActiveIndex(-1)
	}

	function handleKeyDown(event: ReactKeyboardEvent<HTMLInputElement>) {
		const selectableResults = query.trim() ? results : recentSearches
		if (event.key === 'ArrowDown' && selectableResults.length) { event.preventDefault(); setActiveIndex((index) => (index + 1) % selectableResults.length) }
		else if (event.key === 'ArrowUp' && selectableResults.length) { event.preventDefault(); setActiveIndex((index) => (index - 1 + selectableResults.length) % selectableResults.length) }
		else if (event.key === 'Enter' && activeIndex >= 0 && selectableResults[activeIndex]) { event.preventDefault(); selectResult(selectableResults[activeIndex]) }
		else if (event.key === 'Escape') setOpen(false)
	}

	async function handleLogout() {
		setLoggingOut(true)
		try { await logoutCurrentUser() } catch { setLoggingOut(false); return }
		window.localStorage.removeItem('access_token'); window.localStorage.removeItem('auth_access_token'); window.localStorage.removeItem('refresh_token'); window.location.assign('/login')
	}

	const accountName = account?.display_name || account?.username || ''
	const accountAction = account ? <button onClick={handleLogout} disabled={loggingOut}>{loggingOut ? '退出中...' : '退出登录'}</button> : <a href={loginPath()}>去登录</a>
	const selectableResults = query.trim() ? results : recentSearches
	return <header className="top-bar"><button className="icon-button menu-button" aria-label="打开股票列表" onClick={onMenu}>☰</button><a className="brand" href="/"><span className="brand-symbol">M</span><span>ManNiuNiu</span></a><nav className="main-nav" aria-label="主导航"><a className={activeSection === 'research' ? 'active' : ''} href="/">研究</a><a className={activeSection === 'picker' ? 'active' : ''} href="/stock-picker">选股</a></nav><div className="global-search-wrap"><label className="global-search"><span>⌕</span><input ref={inputRef} role="combobox" aria-label="搜索公司、代码或主题" aria-expanded={open} aria-controls="security-search-results" aria-activedescendant={activeIndex >= 0 ? `security-result-${activeIndex}` : undefined} value={query} onChange={(event) => setQuery(event.target.value)} onFocus={() => setOpen(Boolean(query.trim() || recentSearches.length))} onBlur={() => window.setTimeout(() => setOpen(false), 0)} onKeyDown={handleKeyDown} placeholder="搜索公司、代码或主题" /></label>{open && <div className="security-search-results" id="security-search-results" role="listbox">{!query.trim() && recentSearches.length > 0 && <div className="search-history-heading">最近搜索</div>}{selectableResults.map((stock, index) => <button key={stock.code} id={`security-result-${index}`} className={`security-search-result ${index === activeIndex ? 'active' : ''}`} role="option" aria-selected={index === activeIndex} onMouseDown={(event) => event.preventDefault()} onClick={() => selectResult(stock)}><span className="search-result-main"><strong>{stock.name}</strong><code>{stock.code}</code></span><span className="search-result-meta"><span>{stock.industry}</span><span>{formatListDate(stock.listDate)}</span></span></button>)}{query.trim() && status === 'loading' && <div className="search-state">正在搜索...</div>}{query.trim() && status === 'empty' && <div className="search-state">未找到匹配证券</div>}{query.trim() && status === 'error' && <div className="search-state search-error">搜索失败，请稍后重试</div>}</div>}</div><div className="user-menu-wrap"><button className="user-menu" onClick={() => setAccountOpen((value) => !value)}><span className="avatar">{accountName.slice(0, 1) || '访'}</span><span>{accountName || '访客'}</span></button>{accountOpen && <div className="account-dropdown"><div className="account-dropdown-name">{accountName || '访客'}</div>{accountAction}</div>}</div></header>
}

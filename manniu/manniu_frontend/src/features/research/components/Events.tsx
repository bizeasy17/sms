import { useEffect, useState } from 'react'
import { fetchSecurityEvents } from '../services/researchApi'
import type { SecurityEvent } from '../types'

type Props = { tsCode?: string }

function eventLabel(event: SecurityEvent) {
	return event.eventType === 'FINANCIAL_DISCLOSED' ? '财报披露' : '风格变化'
}

function eventTitle(event: SecurityEvent) {
	if (event.eventType === 'FINANCIAL_DISCLOSED') {
		const reportType = typeof event.payload.report_type === 'string' ? event.payload.report_type : '财报'
		return `${reportType} 财报已披露`
	}
	const oldRegime = typeof event.payload.old_regime === 'string' ? event.payload.old_regime : '原风格'
	const newRegime = typeof event.payload.new_regime === 'string' ? event.payload.new_regime : '新风格'
	return `风格由 ${oldRegime} 转为 ${newRegime}`
}

function eventDescription(event: SecurityEvent) {
	if (event.eventType === 'FINANCIAL_DISCLOSED') {
		const endDate = typeof event.payload.financial_end_date === 'string' ? event.payload.financial_end_date : ''
		return endDate ? `报告期 ${endDate} 的财务披露已进入研究时间线。` : '新的财务披露已进入研究时间线。'
	}
	return '个股风格分类已确认发生变化，可结合行情和基本面继续复核。'
}

function formatDate(value: string) {
	return value.length >= 10 ? value.slice(5, 10) : value
}

export function Events({ tsCode }: Props) {
	const [events, setEvents] = useState<SecurityEvent[]>([])
	const [state, setState] = useState<'loading' | 'ready' | 'empty' | 'error'>('loading')
	const [loadedCode, setLoadedCode] = useState<string | null>(null)
	const [retry, setRetry] = useState(0)

	useEffect(() => {
		if (!tsCode) return
		const controller = new AbortController()
		fetchSecurityEvents(tsCode, controller.signal).then((result) => {
			if (!controller.signal.aborted) {
				setEvents(result)
				setLoadedCode(tsCode)
				setState(result.length ? 'ready' : 'empty')
			}
		}).catch(() => {
			if (!controller.signal.aborted) {
				setLoadedCode(tsCode)
				setState('error')
			}
		})
		return () => controller.abort()
	}, [tsCode, retry])

	const displayState = !tsCode ? 'empty' : loadedCode !== tsCode ? 'loading' : state
	return <aside className="events-panel"><div className="events-heading"><div><p className="kicker">TIMELINE</p><h2>研究事件</h2></div><button aria-label="事件筛选">•••</button></div><div className="event-list">{displayState === 'loading' && <p className="events-state">正在加载事件...</p>}{displayState === 'error' && <div className="events-state"><p>事件暂时不可用</p><button type="button" onClick={() => setRetry((value) => value + 1)}>重试</button></div>}{displayState === 'empty' && <p className="events-state">近一年暂无事件</p>}{displayState === 'ready' && events.map((event) => <article key={`${event.sourceSystem}:${event.sourceEventKey}`}><time>{formatDate(event.eventDate)} · {eventLabel(event)}</time><h3>{eventTitle(event)}</h3><p>{eventDescription(event)}</p></article>)}</div>{displayState === 'ready' && <button className="view-all" type="button">查看全部事件 <span>→</span></button>}</aside>
}
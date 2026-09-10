import { type FormEvent, useEffect, useMemo, useState } from 'react'
import './App.css'

type Parameter = {
  name: string
  in: 'path' | 'query' | 'header'
  type?: string
  required?: boolean
  default?: string | number | boolean
  example?: string | number | boolean
  enum?: string[]
}

type Endpoint = {
  id: string
  method: string
  path: string
  name: string
  description: string
  visibility: string
  access_mode: string
  parameters: Parameter[]
  limits?: Record<string, string | number | boolean>
}

type EndpointGroup = { key: string; name: string; endpoints: Endpoint[] }
type Catalog = { catalog_version: string; groups: EndpointGroup[] }
type ApiEnvelope = {
  success?: boolean
  request_id?: string
  error?: { code?: string; message?: string; retryable?: boolean }
  [key: string]: unknown
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'
const TOKEN_KEYS = ['access_token', 'auth_access_token']

function getAccessToken() {
  for (const key of TOKEN_KEYS) {
    const token = window.localStorage.getItem(key)
    if (token) return token
  }
  return null
}

function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setIsSubmitting(true)
    try {
      const result = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password, client_type: 'WEB' }),
      })
      const body = (await result.json()) as { data?: { access_token?: string; refresh_token?: string }; error?: { message?: string } }
      if (!result.ok || !body.data?.access_token) {
        throw new Error(body.error?.message ?? '登录失败，请检查用户名和密码。')
      }
      window.localStorage.setItem('access_token', body.data.access_token)
      if (body.data.refresh_token) window.localStorage.setItem('refresh_token', body.data.refresh_token)
      window.location.assign('/public/api')
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : '登录失败，请稍后重试。')
    } finally {
      setIsSubmitting(false)
    }
  }

  return <main className="auth-wall"><div className="auth-mark">MI / API</div><p className="eyebrow">MARKET ANALYSIS GATEWAY</p><h1>登录 API Lab</h1><p>使用已有账号访问受保护的接口目录和只读测试工具。</p><form className="login-form" onSubmit={submit}><label>用户名<input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required /></label><label>密码<input autoComplete="current-password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>{error && <p className="field-error">{error}</p>}<button className="primary-button" type="submit" disabled={isSubmitting}>{isSubmitting ? '登录中...' : '登录并继续'}</button></form><a className="back-link" href="/public/api">返回 API Lab</a></main>
}

function ApiBrowser() {
  const [token, setToken] = useState<string | null>(() => getAccessToken())
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [selectedId, setSelectedId] = useState('')
  const [search, setSearch] = useState('')
  const [groupFilter, setGroupFilter] = useState('all')
  const [methodFilter, setMethodFilter] = useState('all')
  const [values, setValues] = useState<Record<string, string>>({})
  const [catalogState, setCatalogState] = useState<'idle' | 'loading' | 'error'>('idle')
  const [catalogError, setCatalogError] = useState('')
  const [requestState, setRequestState] = useState<'idle' | 'loading' | 'done'>('idle')
  const [response, setResponse] = useState<ApiEnvelope | null>(null)
  const [responseStatus, setResponseStatus] = useState<number | null>(null)
  const [responseDuration, setResponseDuration] = useState<number | null>(null)
  const [responseRequestId, setResponseRequestId] = useState('')
  const [fieldError, setFieldError] = useState('')

  const selectedEndpoint = useMemo(
    () => catalog?.groups.flatMap((group) => group.endpoints).find((endpoint) => endpoint.id === selectedId) ?? null,
    [catalog, selectedId],
  )

  const visibleGroups = useMemo(() => {
    if (!catalog) return []
    const query = search.trim().toLowerCase()
    return catalog.groups
      .filter((group) => groupFilter === 'all' || group.key === groupFilter)
      .map((group) => ({
        ...group,
        endpoints: group.endpoints.filter((endpoint) => {
          const matchesMethod = methodFilter === 'all' || endpoint.method === methodFilter
          const searchable = `${endpoint.name} ${endpoint.path} ${endpoint.description}`.toLowerCase()
          return matchesMethod && (!query || searchable.includes(query))
        }),
      }))
      .filter((group) => group.endpoints.length > 0)
  }, [catalog, groupFilter, methodFilter, search])

  async function loadCatalog(activeToken: string) {
    setCatalogState('loading')
    setCatalogError('')
    try {
      const result = await fetch(`${API_BASE}/public-api/catalog`, {
        headers: { Authorization: `Bearer ${activeToken}` },
      })
      const body = (await result.json()) as { data?: Catalog; error?: { message?: string } }
      if (result.status === 401) {
        window.localStorage.removeItem('access_token')
        window.localStorage.removeItem('auth_access_token')
        setToken(null)
        throw new Error('登录凭证已过期，请重新登录。')
      }
      if (!result.ok || !body.data) throw new Error(body.error?.message ?? '接口目录加载失败。')
      setCatalog(body.data)
      setSelectedId(body.data.groups[0]?.endpoints[0]?.id ?? '')
      setCatalogState('idle')
    } catch (error) {
      setCatalogState('error')
      setCatalogError(error instanceof Error ? error.message : '接口目录加载失败。')
    }
  }

  useEffect(() => {
    if (token) void Promise.resolve().then(() => loadCatalog(token))
  }, [token])

  function selectEndpoint(endpoint: Endpoint) {
    setSelectedId(endpoint.id)
    setValues(Object.fromEntries(endpoint.parameters.map((parameter) => [
      parameter.name,
      String(parameter.default ?? parameter.example ?? ''),
    ])))
    setResponse(null)
    setResponseStatus(null)
    setResponseDuration(null)
    setResponseRequestId('')
    setFieldError('')
  }

  function updateValue(name: string, value: string) {
    setValues((current) => ({ ...current, [name]: value }))
  }

  async function sendRequest() {
    if (!selectedEndpoint || !token) return
    const parameters = selectedEndpoint.parameters.filter((parameter) => parameter.in !== 'header')
    const missing = parameters.find((parameter) => parameter.required && !values[parameter.name]?.trim())
    if (missing) {
      setFieldError(`请填写必填参数：${missing.name}`)
      return
    }
    setFieldError('')
    setRequestState('loading')
    const startedAt = performance.now()
    const path = selectedEndpoint.path.replace(/:([\w_]+)/g, (_, name: string) => encodeURIComponent(values[name] ?? ''))
    const query = new URLSearchParams()
    parameters.filter((parameter) => parameter.in === 'query' && values[parameter.name]).forEach((parameter) => {
      query.set(parameter.name, values[parameter.name])
    })
    try {
      const requestPath = path.replace('/api/v1', '')
      const result = await fetch(`${API_BASE}${requestPath}${query.size ? `?${query.toString()}` : ''}`, {
        headers: { Authorization: `Bearer ${token}`, 'X-Request-ID': crypto.randomUUID() },
      })
      const body = (await result.json()) as ApiEnvelope
      setResponse(body)
      setResponseStatus(result.status)
      setResponseDuration(Math.round(performance.now() - startedAt))
      setResponseRequestId(result.headers.get('X-Request-ID') ?? body.request_id ?? '')
    } catch {
      setResponse({ success: false, error: { code: 'NETWORK_ERROR', message: '请求未能完成，请检查服务状态。' } })
      setResponseStatus(0)
      setResponseDuration(Math.round(performance.now() - startedAt))
    } finally {
      setRequestState('done')
    }
  }

  if (!token) {
    return <main className="auth-wall"><div className="auth-mark">MI / API</div><p className="eyebrow">MARKET ANALYSIS GATEWAY</p><h1>登录后查看接口目录</h1><p>此页面沿用现有登录态和访问权限。请先登录，再返回 API 浏览测试页。</p><a className="primary-button" href="/login">前往登录</a></main>
  }

  return <main className="api-shell">
    <header className="topbar"><div className="brand"><span className="brand-dot" /> Market Analysis <strong>API Lab</strong></div><div className="topbar-meta"><span className="status-dot" />已登录 <button type="button" onClick={() => { window.localStorage.removeItem('access_token'); window.localStorage.removeItem('auth_access_token'); setToken(null) }}>退出</button></div></header>
    <section className="intro"><div><p className="eyebrow">AUTHENTICATED DEVELOPER CONSOLE</p><h1>接口浏览测试</h1><p className="intro-copy">浏览已对外开放的只读接口，使用当前账号权限快速验证请求参数与返回结果。</p></div><div className="catalog-badge"><span>CATALOG</span><strong>{catalog?.catalog_version ?? '—'}</strong><small>{catalog ? '目录已同步' : '等待加载'}</small></div></section>
    {catalogState === 'error' && <div className="notice error"><strong>目录不可用</strong><span>{catalogError}</span><button type="button" onClick={() => void loadCatalog(token)}>重试</button></div>}
    {catalogState === 'loading' && <div className="notice">正在读取接口目录...</div>}
    <section className="workspace"><aside className="catalog-panel"><div className="panel-heading"><div><p className="eyebrow">PUBLIC ENDPOINTS</p><h2>接口目录</h2></div><span className="count">{catalog?.groups.flatMap((group) => group.endpoints).length ?? 0}</span></div><label className="search-box"><span aria-hidden="true">⌕</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索路径或接口名称" /></label><div className="filters"><select value={groupFilter} onChange={(event) => setGroupFilter(event.target.value)}><option value="all">所有领域</option>{catalog?.groups.map((group) => <option key={group.key} value={group.key}>{group.name}</option>)}</select><select value={methodFilter} onChange={(event) => setMethodFilter(event.target.value)}><option value="all">所有方法</option><option value="GET">GET</option><option value="HEAD">HEAD</option></select></div><div className="endpoint-list">{visibleGroups.map((group) => <div className="endpoint-group" key={group.key}><p className="group-label">{group.name}</p>{group.endpoints.map((endpoint) => <button type="button" className={`endpoint-item ${endpoint.id === selectedId ? 'selected' : ''}`} key={endpoint.id} onClick={() => selectEndpoint(endpoint)}><span className="method">{endpoint.method}</span><span><strong>{endpoint.name}</strong><small>{endpoint.path}</small></span></button>)}</div>)}{!visibleGroups.length && <div className="empty">没有匹配的接口</div>}</div></aside><div className="detail-panel">{selectedEndpoint ? <><div className="detail-heading"><div><div className="path-line"><span className="method large">{selectedEndpoint.method}</span><code>{selectedEndpoint.path}</code></div><h2>{selectedEndpoint.name}</h2><p>{selectedEndpoint.description}</p></div><span className="public-tag">PUBLIC · AUTH</span></div><div className="detail-grid"><section><div className="section-title"><span>01</span><h3>请求参数</h3></div><div className="parameter-form">{selectedEndpoint.parameters.length ? selectedEndpoint.parameters.map((parameter) => <label className="parameter-field" key={parameter.name}><span><strong>{parameter.name}</strong>{parameter.required && <em>必填</em>}<small>{parameter.in} · {parameter.type ?? 'string'}</small></span>{parameter.enum ? <select value={values[parameter.name] ?? ''} onChange={(event) => updateValue(parameter.name, event.target.value)}><option value="">请选择</option>{parameter.enum.map((value) => <option value={value} key={value}>{value}</option>)}</select> : <input value={values[parameter.name] ?? ''} onChange={(event) => updateValue(parameter.name, event.target.value)} placeholder={String(parameter.example ?? '输入参数值')} />}</label>) : <p className="muted">此接口无需请求参数。</p>}</div>{fieldError && <p className="field-error">{fieldError}</p>}<div className="request-actions"><button className="primary-button" type="button" onClick={() => void sendRequest()} disabled={requestState === 'loading'}>{requestState === 'loading' ? '请求中...' : '发送请求'}</button><button className="text-button" type="button" onClick={() => setValues({})}>重置参数</button></div></section><section className="response-section"><div className="section-title"><span>02</span><h3>响应结果</h3>{responseStatus !== null && <b className={responseStatus >= 200 && responseStatus < 300 ? 'ok' : 'bad'}>{responseStatus || '网络错误'}</b>}</div>{response ? <><div className="response-meta"><span>{responseDuration} ms</span><span>{responseRequestId ? `Request ID ${responseRequestId}` : '未返回 Request ID'}</span></div><pre>{JSON.stringify(response, null, 2)}</pre></> : <div className="response-empty"><span>⌁</span><p>填写参数并发送请求</p><small>响应会显示在这里</small></div>}</section></div></> : <div className="empty large-empty">登录后加载接口目录</div>}</div></section>
    <footer><span>Read-only gateway tools</span><span>API version v1 · Authorization required</span></footer>
  </main>
}

function App() {
  return window.location.pathname === '/login' ? <LoginPage /> : <ApiBrowser />
}

export default App

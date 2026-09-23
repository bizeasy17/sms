import { type FormEvent, useState } from 'react'
import './LoginPage.css'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

function loginRedirect() {
  const redirect = new URLSearchParams(window.location.search).get('redirect')
  return redirect && redirect.startsWith('/') && !redirect.startsWith('//') ? redirect : '/'
}

export function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setLoading(true)
    try {
      const result = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password, client_type: 'WEB' }),
      })
      const body = await result.json() as { data?: { access_token?: string; refresh_token?: string }; error?: { message?: string } }
      if (!result.ok || !body.data?.access_token) throw new Error(body.error?.message ?? '登录失败，请检查用户名和密码。')
      window.localStorage.setItem('access_token', body.data.access_token)
      if (body.data.refresh_token) window.localStorage.setItem('refresh_token', body.data.refresh_token)
      window.location.assign(loginRedirect())
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : '登录失败，请稍后重试。')
    } finally {
      setLoading(false)
    }
  }

  return <main className="login-page">
    <section className="login-showcase" aria-label="产品介绍">
      <a className="login-logo" href="/">M<span>/</span>N</a>
      <div className="login-showcase-copy">
        <p className="login-kicker">MARKET INTELLIGENCE PLATFORM</p>
        <h1>让每一次判断，<br /><em>更接近事实。</em></h1>
        <p>连接行情、财务与估值信号，在一个清晰的工作台里理解市场。</p>
      </div>
      <div className="login-signal" aria-hidden="true"><span>LIVE SIGNAL</span><strong>+18.6%</strong><i /></div>
      <p className="login-showcase-foot">慢牛牛 · 研究工作台</p>
    </section>
    <section className="login-panel">
      <div className="login-panel-inner">
        <div className="login-mobile-brand"><a className="login-logo" href="/">M<span>/</span>N</a><span>研究工作台</span></div>
        <div className="login-heading"><p className="login-kicker">WELCOME BACK</p><h2>登录你的账户</h2><p>继续使用你的市场研究与分析工具。</p></div>
        <form className="login-form" onSubmit={submit}>
          <label>用户名<input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} placeholder="输入用户名" required /></label>
          <label>密码<input autoComplete="current-password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="输入密码" required /></label>
          {error && <div className="login-error" role="alert">{error}</div>}
          <button className="login-submit" disabled={loading}>{loading ? '正在登录...' : '登录并进入工作台'}<span aria-hidden="true">↗</span></button>
        </form>
        <p className="login-security"><span aria-hidden="true">◇</span> 你的连接受到安全保护</p>
        <a className="login-back" href="/">返回研究工作台</a>
      </div>
    </section>
  </main>
}
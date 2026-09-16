export type ModuleState = 'loading' | 'ready' | 'empty' | 'error'

type ModuleStateNoticeProps = {
  state: Exclude<ModuleState, 'ready'>
  label: string
  onRetry?: () => void
}

export function ModuleStateNotice({ state, label, onRetry }: ModuleStateNoticeProps) {
  const content = {
    loading: { title: '正在加载', detail: `${label}数据正在更新` },
    empty: { title: '暂无数据', detail: `${label}暂时没有可展示的数据` },
    error: { title: '加载失败', detail: `${label}暂时不可用，请稍后重试` },
  }[state]

  return <div className={`module-state module-state-${state}`} role={state === 'error' ? 'alert' : 'status'}><strong>{content.title}</strong><span>{content.detail}</span>{state === 'error' && onRetry ? <button type="button" onClick={onRetry}>重试</button> : null}</div>
}

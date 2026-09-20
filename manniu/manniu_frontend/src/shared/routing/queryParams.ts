export function readQueryParam(name: string): string | null {
    return new URLSearchParams(window.location.search).get(name)
}

export function currentPathWithQuery(): string {
    return `${window.location.pathname}${window.location.search}${window.location.hash}`
}

export function loginPath(redirect = currentPathWithQuery()): string {
    return `/login?redirect=${encodeURIComponent(redirect)}`
}

export function replaceQueryParams(values: Record<string, string | null | undefined>) {
    const params = new URLSearchParams(window.location.search)
    Object.entries(values).forEach(([key, value]) => {
        if (value == null || value === '') params.delete(key)
        else params.set(key, value)
    })
    window.history.replaceState({}, '', `${window.location.pathname}${params.toString() ? `?${params}` : ''}${window.location.hash}`)
}

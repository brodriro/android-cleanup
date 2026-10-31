import { useCallback, useEffect, useRef, useState } from 'react'

/** Minimal hash router: "#/informe/abc" → ["informe", "abc"]. */
export function useRoute(): string[] {
  const parse = () => window.location.hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent)
  const [route, setRoute] = useState(parse)
  useEffect(() => {
    const on = () => {
      setRoute(parse())
      window.scrollTo({ top: 0 })
    }
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return route
}

export function go(...parts: string[]) {
  window.location.hash = '/' + parts.map(encodeURIComponent).join('/')
}

export const href = (...parts: string[]) => '#/' + parts.map(encodeURIComponent).join('/')

export interface Async<T> {
  data: T | undefined
  error: Error | undefined
  loading: boolean
  reload: () => void
}

/** Load once per dependency change; keeps the previous data while reloading. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): Async<T> {
  const [data, setData] = useState<T>()
  const [error, setError] = useState<Error>()
  const [loading, setLoading] = useState(true)
  const [tick, setTick] = useState(0)
  const fnRef = useRef(fn)
  fnRef.current = fn
  useEffect(() => {
    let alive = true
    setLoading(true)
    fnRef.current().then(
      (d) => {
        if (!alive) return
        setData(d)
        setError(undefined)
        setLoading(false)
      },
      (e: Error) => {
        if (!alive) return
        setError(e)
        setLoading(false)
      },
    )
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])
  const reload = useCallback(() => setTick((t) => t + 1), [])
  return { data, error, loading, reload }
}

/** true while the tab is visible (Page Visibility API). */
export function usePageVisible(): boolean {
  const [vis, setVis] = useState(() => document.visibilityState !== 'hidden')
  useEffect(() => {
    const on = () => setVis(document.visibilityState !== 'hidden')
    document.addEventListener('visibilitychange', on)
    return () => document.removeEventListener('visibilitychange', on)
  }, [])
  return vis
}

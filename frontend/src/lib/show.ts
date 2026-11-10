// The current show (convention) shared by both routes.
// Source of truth: the :slug in /exhibitions/:slug/..., else ?show= on other routes, else localStorage.
import { useCallback, useEffect } from 'react'
import { matchPath, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { load, save } from './storage'

const KEY = 'leads.show'

export function storedShow(): string {
  return load<string>(KEY, '')
}

export function useCurrentShow() {
  const location = useLocation()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const m = matchPath('/exhibitions/:slug/*', location.pathname)
  const pathSlug = m?.params.slug
  const paramSlug = params.get('show')
  const slug = pathSlug ?? paramSlug ?? ''

  useEffect(() => {
    if (pathSlug) save(KEY, pathSlug)
    else if (paramSlug !== null) save(KEY, paramSlug)
  }, [pathSlug, paramSlug])

  const setShow = useCallback(
    (next: string) => {
      save(KEY, next)
      if (pathSlug && m) {
        const rest = m.params['*'] ?? ''
        // a person's floor list belongs to one show; keep the person, swap the show
        navigate(next ? `/exhibitions/${encodeURIComponent(next)}/${rest || 'map'}` : '/exhibitions')
        return
      }
      if (location.pathname === '/exhibitions' || location.pathname === '/exhibitions/') {
        if (next) navigate(`/exhibitions/${encodeURIComponent(next)}/map`)
        return
      }
      const p = new URLSearchParams(params)
      if (next) p.set('show', next)
      else p.delete('show')
      p.delete('page')
      setParams(p)
    },
    [pathSlug, m, navigate, location.pathname, params, setParams],
  )

  return { slug, setShow }
}

/** On Leads routes, carry the stored show into the URL when it is missing. */
export function useShowSync() {
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  useEffect(() => {
    if (!location.pathname.startsWith('/leads')) return
    if (params.get('show') !== null) return
    const s = storedShow()
    if (s) {
      const p = new URLSearchParams(params)
      p.set('show', s)
      setParams(p, { replace: true })
    }
  }, [location.pathname, params, setParams])
}

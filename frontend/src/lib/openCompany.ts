import { useCallback } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useIsDesktop } from './hooks'

/** Desktop: open the company window as a drawer (?company=id). Phone on Leads: full page. */
export function useOpenCompany() {
  const isDesktop = useIsDesktop()
  const navigate = useNavigate()
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  return useCallback(
    (id: number, opts?: { tab?: string }) => {
      const onLeads = location.pathname.startsWith('/leads')
      if (!isDesktop && onLeads) {
        const show = params.get('show')
        const p = new URLSearchParams()
        if (show) p.set('show', show)
        if (opts?.tab) p.set('tab', opts.tab)
        navigate(`/leads/companies/${id}${p.toString() ? `?${p}` : ''}`)
        return
      }
      const p = new URLSearchParams(params)
      p.set('company', String(id))
      if (opts?.tab) p.set('tab', opts.tab)
      else p.delete('tab')
      setParams(p)
    },
    [isDesktop, location.pathname, navigate, params, setParams],
  )
}

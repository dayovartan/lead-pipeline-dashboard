import { NavLink, useLocation } from 'react-router-dom'
import { Eye } from 'lucide-react'
import { useMe } from '@/lib/hooks'
import { useCurrentShow } from '@/lib/show'
import { cn } from '@/lib/utils'
import { GlobalSearch } from './GlobalSearch'
import { ShowPicker } from './ShowPicker'
import { Badge } from './ui/badge'

const sub = 'rounded-md px-2.5 py-1.5 text-sm font-medium text-muted-foreground hover:text-foreground aria-[current=page]:bg-accent aria-[current=page]:text-foreground'

export function TopBar() {
  const { pathname } = useLocation()
  const { slug } = useCurrentShow()
  const { data: me } = useMe()
  const onLeads = !pathname.startsWith('/exhibitions')
  const q = slug ? `?show=${encodeURIComponent(slug)}` : ''
  const exBase = slug ? `/exhibitions/${encodeURIComponent(slug)}` : '/exhibitions'

  return (
    <header className="no-print sticky top-0 z-30 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2">
        <NavLink to={`/leads/board${q}`} className="mr-1 flex items-center gap-2 font-semibold">
          <img src="/icon.svg" alt="" className="size-6" /> <span className="hidden sm:inline">Leads</span>
        </NavLink>
        <nav aria-label="Knowledge base" className="flex rounded-lg border p-0.5 text-sm">
          <NavLink
            to={`/leads/board${q}`}
            className={cn('rounded-md px-3 py-1 font-medium', onLeads ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground')}
          >
            Leads
          </NavLink>
          <NavLink
            to={slug ? `${exBase}/map` : '/exhibitions'}
            className={cn('rounded-md px-3 py-1 font-medium', !onLeads ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground')}
          >
            Exhibitions
          </NavLink>
        </nav>
        <ShowPicker />
        <GlobalSearch className="order-last w-full sm:order-none sm:ml-auto sm:w-72 lg:w-96" />
        <div className="ml-auto flex items-center gap-2 text-sm sm:ml-0">
          {me && !me.is_editor ? (
            <Badge variant="secondary" title="Read-only: you don't have the leads_editor role">
              <Eye className="size-3" /> viewer
            </Badge>
          ) : null}
          <span className="max-w-[10rem] truncate text-muted-foreground" title={me?.email}>
            {me?.name || me?.email || ''}
          </span>
        </div>
      </div>
      <div className="mx-auto flex max-w-[1600px] items-center gap-1 overflow-x-auto px-4 pb-1.5">
        {onLeads ? (
          <>
            <NavLink to={`/leads/board${q}`} className={sub}>Board</NavLink>
            <NavLink to={`/leads/companies${q}`} className={sub}>Companies</NavLink>
          </>
        ) : slug ? (
          <>
            <NavLink end to="/exhibitions" className={sub}>Shows</NavLink>
            <span className="text-muted-foreground/40">/</span>
            {(['intake', 'map', 'tags', 'coverage', 'dispatch'] as const).map((s) => (
              <NavLink key={s} to={`${exBase}/${s}`} className={cn(sub, 'capitalize')}>
                {s}
              </NavLink>
            ))}
          </>
        ) : (
          <NavLink end to="/exhibitions" className={sub}>Shows</NavLink>
        )}
      </div>
    </header>
  )
}

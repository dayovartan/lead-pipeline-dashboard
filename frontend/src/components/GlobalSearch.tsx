import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Building2, NotebookText, Search, User } from 'lucide-react'
import { api } from '@/api/client'
import { useDebounced } from '@/lib/hooks'
import { useOpenCompany } from '@/lib/openCompany'
import { Input } from './ui/input'
import { Popover, PopoverAnchor, PopoverContent } from './ui/popover'
import { Spinner } from './ui/states'
import { cn, fmtDate } from '@/lib/utils'

type Hit = { key: string; icon: JSX.Element; title: string; sub?: string; go: () => void }

export function GlobalSearch({ className }: { className?: string }) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const dq = useDebounced(q.trim(), 250)
  const inputRef = useRef<HTMLInputElement>(null)
  const openCompany = useOpenCompany()
  const navigate = useNavigate()
  const { data, isFetching, isError } = useQuery({
    queryKey: ['search', dq],
    queryFn: () => api.search(dq),
    enabled: dq.length >= 2,
    staleTime: 30_000,
  })

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (e.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName) && !t.isContentEditable) {
        e.preventDefault()
        inputRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const close = () => {
    setOpen(false)
    setQ('')
    inputRef.current?.blur()
  }
  const hits: Hit[] = []
  for (const c of data?.companies ?? [])
    hits.push({ key: `c${c.id}`, icon: <Building2 />, title: c.name, sub: c.country ?? undefined, go: () => openCompany(c.id) })
  for (const c of data?.contacts ?? [])
    hits.push({
      key: `p${c.id}`,
      icon: <User />,
      title: c.name,
      sub: [c.email, c.company_name].filter(Boolean).join(' · '),
      go: () => navigate(`/leads/contacts/${c.id}`),
    })
  for (const m of data?.meetings ?? [])
    hits.push({
      key: `m${m.id}`,
      icon: <NotebookText />,
      title: `${m.company_name} · ${fmtDate(m.met_on)}`,
      sub: m.snippet,
      go: () => openCompany(m.company_id, { tab: 'meetings' }),
    })

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((a) => Math.min(a + 1, hits.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((a) => Math.max(a - 1, 0))
    } else if (e.key === 'Enter' && hits[active]) {
      e.preventDefault()
      hits[active].go()
      close()
    } else if (e.key === 'Escape') {
      close()
    }
  }

  return (
    <Popover open={open && dq.length >= 2} onOpenChange={setOpen}>
      <PopoverAnchor asChild>
        <div className={cn('relative', className)}>
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            ref={inputRef}
            value={q}
            onChange={(e) => {
              setQ(e.target.value)
              setActive(0)
              setOpen(true)
            }}
            onFocus={() => setOpen(true)}
            onKeyDown={onKeyDown}
            placeholder="Search companies, contacts, notes"
            aria-label="Global search"
            className="pl-8"
          />
          {isFetching ? <Spinner className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" /> : null}
        </div>
      </PopoverAnchor>
      <PopoverContent
        className="w-[min(32rem,calc(100vw-1rem))] p-1"
        onOpenAutoFocus={(e) => e.preventDefault()}
        onInteractOutside={(e) => {
          if (inputRef.current?.contains(e.target as Node)) e.preventDefault()
        }}
      >
        {isError ? <p className="p-2 text-sm text-destructive">Search failed.</p> : null}
        {!isFetching && data && hits.length === 0 ? <p className="p-2 text-sm text-muted-foreground">No matches.</p> : null}
        <ul role="listbox" className="max-h-[60vh] overflow-y-auto">
          {hits.map((h, i) => (
            <li key={h.key} role="option" aria-selected={i === active}>
              <button
                type="button"
                onMouseEnter={() => setActive(i)}
                onClick={() => {
                  h.go()
                  close()
                }}
                className={cn(
                  'flex w-full items-start gap-2 rounded-sm px-2 py-1.5 text-left text-sm [&_svg]:mt-0.5 [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-muted-foreground',
                  i === active && 'bg-accent',
                )}
              >
                {h.icon}
                <span className="min-w-0">
                  <span className="block truncate font-medium">{h.title}</span>
                  {h.sub ? <span className="block truncate text-xs text-muted-foreground">{h.sub}</span> : null}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  )
}
